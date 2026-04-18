//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// IMPORTANT: PyBridgePy.h must come BEFORE omnetpp.h to avoid macro conflicts.
//

#include "pybridge/PyBridgePy.h"
#include "GcsModule.h"
#include "pybridge/PyBridge.h"

#include <omnetpp/ccanvas.h>

#include "GcsReport_m.h"
#include "GcsCommand_m.h"
#include "inet/physicallayer/wireless/common/contract/packetlevel/IRadioMedium.h"
#include "inet/mobility/contract/IMobility.h"
#include "inet/common/geometry/common/CanvasProjection.h"

#include <algorithm>
#include <cstdio>
#include <cmath>
#include <cstring>
#include <limits>
#include <sstream>

#ifdef WITH_OSG
#include <osg/Geode>
#include <osg/Geometry>
#include <osg/LineWidth>
#include <osg/Material>
#include <osg/MatrixTransform>
#include <osg/ShapeDrawable>
#include <osg/BlendFunc>
#include <osg/Depth>
#include <Eigen/Dense>
#endif

using namespace inet;
using namespace physicallayer;

namespace {

double chi2Threshold2D(double alpha)
{
    if (alpha <= 0.01)
        return 9.210;
    if (alpha <= 0.05)
        return 5.991;
    if (alpha <= 0.10)
        return 4.605;
    return 5.991;
}

double chi2Threshold3D(double alpha)
{
    if (alpha <= 0.01)
        return 11.345;
    if (alpha <= 0.05)
        return 7.815;
    if (alpha <= 0.10)
        return 6.251;
    return 7.815;
}

// Cholesky A = L L^T for 3x3 SPD; returns false if not factorable.
bool cholesky3(const double A[3][3], double L[3][3])
{
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            L[i][j] = 0.0;

    for (int i = 0; i < 3; ++i) {
        for (int j = 0; j <= i; ++j) {
            double sum = A[i][j];
            for (int k = 0; k < j; ++k)
                sum -= L[i][k] * L[j][k];
            if (i == j) {
                if (sum <= 1e-18)
                    return false;
                L[i][j] = std::sqrt(sum);
            }
            else {
                if (std::abs(L[j][j]) < 1e-18)
                    return false;
                L[i][j] = sum / L[j][j];
            }
        }
    }
    return true;
}

// Mahalanobis^2 = d^T Sigma^{-1} d  with Sigma symmetric SPD (via Cholesky).
bool mahalanobisSquared3(const double Sigma[3][3], const double d[3], double& outM2)
{
    double L[3][3];
    if (!cholesky3(Sigma, L))
        return false;
    double y0 = d[0] / L[0][0];
    double y1 = (d[1] - L[1][0] * y0) / L[1][1];
    double y2 = (d[2] - L[2][0] * y0 - L[2][1] * y1) / L[2][2];
    outM2 = y0 * y0 + y1 * y1 + y2 * y2;
    return std::isfinite(outM2);
}

// Same order as BasicUav.ned movementTrailLineColor / MultirotorMobility kInetTrailPalette.
// Red is reserved for the designated spoofer (host[numHosts-1]) in goalDotColorForHostIndex.
const char* const kHostGoalDotPalette[] = {
    "#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#2ca02c", "#98df8a",
    "#9467bd", "#c5b0d5", "#404040", "#bdbdbd", "#e377c2", "#f7b6d2",
    "#7f7f7f", "#c7c7c7", "#bcbd22", "#dbdb8d", "#17becf", "#9edae5",
    "#393b79", "#5254a3", "#637939", "#8ca252", "#3182bd", "#6baed6",
    "#31a354", "#756bb1",
};
static constexpr size_t kHostGoalDotPaletteLen = sizeof(kHostGoalDotPalette) / sizeof(kHostGoalDotPalette[0]);

static const char* goalDotColorForHostIndex(int hid)
{
    cModule *net = getSimulation()->getSystemModule();
    if (net && net->hasPar("numHosts")) {
        int nh = net->par("numHosts").intValue();
        if (hid == nh - 1)
            return "#ea4335";
    }
    return kHostGoalDotPalette[static_cast<size_t>(hid) % kHostGoalDotPaletteLen];
}

} // namespace

Define_Module(GcsModule);

#ifdef WITH_OSG
static constexpr bool hasOsg = true;
#else
static constexpr bool hasOsg = false;
#endif

GcsModule::~GcsModule()
{
    removePresentationCanvas();
    cancelAndDelete(tickTimer);
    cancelAndDelete(canvasOverlayRefreshMsg);
    for (auto& [name, vec] : logVectors)
        delete vec;
}

// ── OSG Visualization ───────────────────────────────────────────────────────

void GcsModule::updateVisualization(const std::vector<double>& mu,
                                    const std::vector<std::vector<double>>& sigma,
                                    double alpha,
                                    bool detected)
{
    if (!getEnvir()->isGUI())
        return;

    if (mu.size() < 3 || sigma.size() < 3)
        return;

    lastEllipsoidMu = mu;
    lastEllipsoidSigma = sigma;
    lastEllipsoidAlpha = alpha;
    lastEllipsoidDetected = detected;
    lastEllipsoidValid = true;

    if constexpr (hasOsg) {
#ifdef WITH_OSG
        auto *osgCanvas = getSystemModule()->getOsgCanvas();
        auto *scene = osgCanvas ? dynamic_cast< ::osg::Group*>(osgCanvas->getScene()) : nullptr;
        if (scene) {
            // Build 3x3 covariance matrix
            Eigen::Matrix3d cov;
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++)
                    cov(i, j) = (sigma[i].size() > (size_t)j) ? sigma[i][j] : 0.0;

            // Eigendecomposition for ellipsoid axes
            Eigen::SelfAdjointEigenSolver<Eigen::Matrix3d> solver(cov);
            if (solver.info() == Eigen::Success) {

        Eigen::Vector3d eigenvals = solver.eigenvalues();
        Eigen::Matrix3d eigenvecs = solver.eigenvectors();

        // chi-squared threshold for 3 DOF at (1 - alpha) confidence
        // alpha=0.05 -> threshold ~7.81
        double threshold = 7.815;  // default for alpha=0.05
        if (alpha <= 0.01) threshold = 11.345;
        else if (alpha <= 0.05) threshold = 7.815;
        else if (alpha <= 0.10) threshold = 6.251;

        // Semi-axis lengths = sqrt(eigenvalue * threshold)
        double sx = std::sqrt(std::max(eigenvals(0), 0.01) * threshold);
        double sy = std::sqrt(std::max(eigenvals(1), 0.01) * threshold);
        double sz = std::sqrt(std::max(eigenvals(2), 0.01) * threshold);

        // Remove previous ellipsoid
        if (ellipsoidTransform) {
            scene->removeChild(static_cast< ::osg::Node*>(ellipsoidTransform));
            ellipsoidTransform = nullptr;
        }

        // Build transform hierarchy:
        //   rootTranslate: world placement at mu
        //   localShape:    local rotation+scale of unit sphere
        // Using two nodes avoids matrix order ambiguity across conventions.
        auto *rootTranslate = new ::osg::MatrixTransform();
        auto *localShape = new ::osg::MatrixTransform();

        ::osg::Matrixd scaleMat = ::osg::Matrixd::scale(sx, sy, sz);

        // Rotation from eigenvectors (column-major → osg row-major)
        ::osg::Matrixd rotMat;
        rotMat.makeIdentity();
        for (int r = 0; r < 3; r++)
            for (int c = 0; c < 3; c++)
                rotMat(r, c) = eigenvecs(r, c);

        ::osg::Matrixd transMat = ::osg::Matrixd::translate(mu[0], mu[1], mu[2]);
        rootTranslate->setMatrix(transMat);
        localShape->setMatrix(rotMat * scaleMat);

        // Semi-transparent red ellipsoid (unit sphere scaled by transform)
        auto *sphere = new ::osg::ShapeDrawable(
            new ::osg::Sphere(::osg::Vec3(0, 0, 0), 1.0));

        ::osg::Vec4 color = detected
            ? ::osg::Vec4(1.0f, 0.0f, 0.0f, 0.25f)   // red when detected
            : ::osg::Vec4(1.0f, 0.5f, 0.0f, 0.15f);   // orange pre-detection
        sphere->setColor(color);

        auto *geode = new ::osg::Geode();
        geode->addDrawable(sphere);

        // Enable transparency
        auto *stateSet = geode->getOrCreateStateSet();
        stateSet->setMode(GL_BLEND, ::osg::StateAttribute::ON);
        stateSet->setAttributeAndModes(new ::osg::BlendFunc(
            ::osg::BlendFunc::SRC_ALPHA, ::osg::BlendFunc::ONE_MINUS_SRC_ALPHA));
        stateSet->setRenderingHint(::osg::StateSet::TRANSPARENT_BIN);
        stateSet->setAttributeAndModes(new ::osg::Depth(
            ::osg::Depth::LESS, 0.0, 1.0, false));  // write depth disabled for transparency
        stateSet->setMode(GL_LIGHTING, ::osg::StateAttribute::OFF);

        // Wireframe outline for visibility
        auto *wireGeom = new ::osg::Geometry();
        auto *wireVerts = new ::osg::Vec3Array();
        auto *wireColors = new ::osg::Vec4Array();
        wireColors->push_back(::osg::Vec4(1.0f, 0.0f, 0.0f, 0.8f));

        // Draw 3 great circles (XY, XZ, YZ planes)
        const int CIRCLE_SEGS = 48;
        for (int plane = 0; plane < 3; plane++) {
            for (int i = 0; i <= CIRCLE_SEGS; i++) {
                double angle = 2.0 * M_PI * i / CIRCLE_SEGS;
                double ca = std::cos(angle), sa = std::sin(angle);
                ::osg::Vec3 pt;
                if (plane == 0) pt = ::osg::Vec3(ca, sa, 0);       // XY
                else if (plane == 1) pt = ::osg::Vec3(ca, 0, sa);  // XZ
                else pt = ::osg::Vec3(0, ca, sa);                   // YZ
                wireVerts->push_back(pt);
            }
        }
        wireGeom->setVertexArray(wireVerts);
        wireGeom->setColorArray(wireColors, ::osg::Array::BIND_OVERALL);
        for (int plane = 0; plane < 3; plane++) {
            wireGeom->addPrimitiveSet(
                new ::osg::DrawArrays(::osg::PrimitiveSet::LINE_STRIP,
                                      plane * (CIRCLE_SEGS + 1),
                                      CIRCLE_SEGS + 1));
        }
        auto *wireStateSet = wireGeom->getOrCreateStateSet();
        wireStateSet->setAttributeAndModes(
            new ::osg::LineWidth(2.0f), ::osg::StateAttribute::ON);
        wireStateSet->setMode(GL_LIGHTING, ::osg::StateAttribute::OFF);
        geode->addDrawable(wireGeom);

        localShape->addChild(geode);
        rootTranslate->addChild(localShape);
        scene->addChild(rootTranslate);
        ellipsoidTransform = static_cast<void*>(rootTranslate);

            } // eigen success
        }     // scene
#endif
    }

    if (hasPar("drawPresentationOverlay") && par("drawPresentationOverlay").boolValue())
        requestCanvasOverlayRefresh();
}

void GcsModule::resetClaimedTrail()
{
    claimedTrailPoints.clear();
    claimedTrailDetected.clear();
    if constexpr (hasOsg) {
#ifdef WITH_OSG
        auto *osgCanvas = getSystemModule()->getOsgCanvas();
        auto *scene = osgCanvas ? dynamic_cast< ::osg::Group*>(osgCanvas->getScene()) : nullptr;
        if (scene && claimedTrailGeode) {
            scene->removeChild(static_cast< ::osg::Node*>(claimedTrailGeode));
            claimedTrailGeode = nullptr;
        }
#endif
    }
    if (hasPar("drawPresentationOverlay") && par("drawPresentationOverlay").boolValue())
        requestCanvasOverlayRefresh();
}

void GcsModule::addClaimedTrailPoint(double x, double y, double z, bool detected)
{
    if (!getEnvir()->isGUI())
        return;

    if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z))
        return;

    if (!claimedTrailPoints.empty()) {
        const auto& prev = claimedTrailPoints.back();
        double dx = x - std::get<0>(prev);
        double dy = y - std::get<1>(prev);
        double dz = z - std::get<2>(prev);
        double dist = std::sqrt(dx * dx + dy * dy + dz * dz);
        double lim = hasPar("overlayClaimedJumpResetM")
            ? par("overlayClaimedJumpResetM").doubleValueInUnit("m")
            : 400.0;
        if (dist > lim)
            resetClaimedTrail();
    }

    claimedTrailPoints.emplace_back(x, y, z);
    claimedTrailDetected.push_back(detected);

    int cap = hasPar("overlayMaxClaimedPoints") ? par("overlayMaxClaimedPoints").intValue() : 800;
    if (cap > 0) {
        while ((int)claimedTrailPoints.size() > cap) {
            claimedTrailPoints.erase(claimedTrailPoints.begin());
            if (!claimedTrailDetected.empty())
                claimedTrailDetected.erase(claimedTrailDetected.begin());
        }
    }

    if constexpr (hasOsg) {
#ifdef WITH_OSG
        auto *osgCanvas = getSystemModule()->getOsgCanvas();
        auto *scene = osgCanvas ? dynamic_cast< ::osg::Group*>(osgCanvas->getScene()) : nullptr;
        if (scene) {
            // Remove previous trail group and rebuild (spheres only).
            if (claimedTrailGeode) {
                scene->removeChild(static_cast< ::osg::Node*>(claimedTrailGeode));
                claimedTrailGeode = nullptr;
            }

            auto *group = new ::osg::Group();

            // Claimed RID breadcrumb:
            // - pre-detection points: red
            // - post-detection points: black
            for (size_t i = 0; i < claimedTrailPoints.size(); ++i) {
                const auto& [px, py, pz] = claimedTrailPoints[i];
                bool pointDetected = (i < claimedTrailDetected.size()) ? claimedTrailDetected[i] : false;
                auto *sphere = new ::osg::ShapeDrawable(
                    new ::osg::Sphere(::osg::Vec3d(px, py, pz), 3.0));
                if (pointDetected)
                    sphere->setColor(::osg::Vec4(0.0f, 0.0f, 0.0f, 0.9f));
                else
                    sphere->setColor(::osg::Vec4(1.0f, 0.0f, 0.0f, 0.85f));
                auto *geode = new ::osg::Geode();
                geode->addDrawable(sphere);
                geode->getOrCreateStateSet()->setMode(GL_LIGHTING, ::osg::StateAttribute::OFF);
                group->addChild(geode);
            }

            scene->addChild(group);
            claimedTrailGeode = static_cast<void*>(group);
        }
#endif
    }

    if (hasPar("drawPresentationOverlay") && par("drawPresentationOverlay").boolValue())
        requestCanvasOverlayRefresh();
}

void GcsModule::removePresentationCanvas()
{
    if (!presentationRoot)
        return;
    if (presentationRoot->getParentFigure())
        presentationRoot->removeFromParent();
    delete presentationRoot;
    presentationRoot = nullptr;
    canvasEllipseFig = nullptr;
    canvasClaimedFig = nullptr;
    canvasTruthFig = nullptr;
    canvasClaimedHeadFig = nullptr;
    canvasBenignRiskFigs.clear();
    canvasBenignSpooferNmacRings.clear();
    canvasGoalDots.clear();
    canvasGoalLabels.clear();
    canvasScaleLeftSpine = nullptr;
    canvasScaleBottomSpine = nullptr;
    canvasScaleLeftTickSegs.clear();
    canvasScaleBottomTickSegs.clear();
    canvasScaleLeftLabels.clear();
    canvasScaleBottomLabels.clear();
    canvasScalePoolCreated = false;
}

void GcsModule::ensurePresentationCanvas()
{
    cModule *sys = getSystemModule();
    cCanvas *canvas = sys->getCanvas();
    if (!canvas)
        return;

    if (presentationRoot)
        return;
    presentationRoot = new cGroupFigure("uliGcsPresentation");
    presentationRoot->setZIndex(8000);

    canvasEllipseFig = new cPolylineFigure("unsafeEllipse");
    canvasEllipseFig->setZIndex(8010);
    canvasEllipseFig->setLineWidth(2);
    canvasEllipseFig->setLineColor(cFigure::parseColor("red"));
    presentationRoot->addFigure(canvasEllipseFig);

    canvasClaimedFig = new cPolylineFigure("claimedTrail");
    canvasClaimedFig->setZIndex(8020);
    canvasClaimedFig->setLineWidth(2);
    canvasClaimedFig->setLineColor(cFigure::parseColor("darkred"));
    presentationRoot->addFigure(canvasClaimedFig);

    canvasTruthFig = new cOvalFigure("spooferTruth");
    canvasTruthFig->setZIndex(8030);
    canvasTruthFig->setFilled(true);
    canvasTruthFig->setLineWidth(1);
    canvasTruthFig->setFillColor(cFigure::parseColor("lime"));
    canvasTruthFig->setLineColor(cFigure::parseColor("darkgreen"));
    presentationRoot->addFigure(canvasTruthFig);

    canvasClaimedHeadFig = new cOvalFigure("claimedHead");
    canvasClaimedHeadFig->setZIndex(8040);
    canvasClaimedHeadFig->setFilled(true);
    canvasClaimedHeadFig->setLineWidth(1);
    presentationRoot->addFigure(canvasClaimedHeadFig);

    canvas->addFigure(presentationRoot);
}

void GcsModule::ensureBenignRiskMarkerCapacity(size_t need)
{
    if (!presentationRoot)
        return;
    while (canvasBenignRiskFigs.size() < need) {
        auto *fig = new cRectangleFigure(("benignAlert" + std::to_string(canvasBenignRiskFigs.size())).c_str());
        fig->setZIndex(8015);
        fig->setFilled(true);
        fig->setLineWidth(2);
        fig->setLineColor(cFigure::parseColor("red"));
        fig->setFillColor(cFigure::parseColor("#FF8888"));
        fig->setCornerRadius(0);
        fig->setVisible(false);
        presentationRoot->addFigure(fig);
        canvasBenignRiskFigs.push_back(fig);
    }
}

void GcsModule::ensureBenignSpooferNmacRingCapacity(size_t need)
{
    if (!presentationRoot)
        return;
    while (canvasBenignSpooferNmacRings.size() < need) {
        auto *ring = new cOvalFigure(("benignSpooferNmac" + std::to_string(canvasBenignSpooferNmacRings.size())).c_str());
        ring->setZIndex(8018);
        ring->setFilled(false);
        ring->setLineWidth(2.5);
        ring->setLineColor(cFigure::parseColor("#cc5500"));
        ring->setVisible(false);
        presentationRoot->addFigure(ring);
        canvasBenignSpooferNmacRings.push_back(ring);
    }
}

void GcsModule::ensureGoalDotCapacity(size_t need)
{
    if (!presentationRoot)
        return;
    while (canvasGoalDots.size() < need) {
        const size_t idx = canvasGoalDots.size();
        auto *fig = new cOvalFigure(("hostGoal" + std::to_string(idx)).c_str());
        fig->setZIndex(8025);
        fig->setFilled(true);
        fig->setLineWidth(2);
        fig->setLineColor(cFigure::parseColor("#202020"));
        fig->setVisible(false);
        presentationRoot->addFigure(fig);
        canvasGoalDots.push_back(fig);

        auto *lbl = new cTextFigure(("hostGoalLbl" + std::to_string(idx)).c_str());
        lbl->setZIndex(8026);
        lbl->setText("");
        // cAbstractTextFigure: anchor + alignment (no setHAlign/setVAlign in OMNeT++ 6.3)
        lbl->setAnchor(cFigure::ANCHOR_N);
        lbl->setAlignment(cFigure::ALIGN_CENTER);
        lbl->setColor(cFigure::parseColor("#101010"));
        lbl->setVisible(false);
        presentationRoot->addFigure(lbl);
        canvasGoalLabels.push_back(lbl);
    }
}

void GcsModule::tryCacheWaypointGoalForHost(int hid)
{
    if (hostGoalsByHost.find(hid) != hostGoalsByHost.end())
        return;
    cModule *network = getSystemModule();
    if (!network)
        return;
    std::string path = "host[" + std::to_string(hid) + "].mobility";
    cModule *mobilityMod = network->getModuleByPath(path.c_str());
    if (!mobilityMod || !mobilityMod->hasPar("waypointScript"))
        return;
    cXMLElement *wpXml = mobilityMod->par("waypointScript").xmlValue();
    if (!wpXml)
        return;
    bool foundMoveto = false;
    std::array<double, 3> goal = {NAN, NAN, NAN};
    for (cXMLElement *child = wpXml->getFirstChild(); child; child = child->getNextSibling()) {
        const char *tag = child->getTagName();
        double x = atof(child->getAttribute("x") ? child->getAttribute("x") : "0");
        double y = atof(child->getAttribute("y") ? child->getAttribute("y") : "0");
        double z = atof(child->getAttribute("z") ? child->getAttribute("z") : "0");
        if (strcmp(tag, "set") == 0 && !foundMoveto)
            goal = {x, y, z};
        else if (strcmp(tag, "moveto") == 0) {
            goal = {x, y, z};
            foundMoveto = true;
        }
    }
    if (std::isfinite(goal[0]) && std::isfinite(goal[1]) && std::isfinite(goal[2]))
        hostGoalsByHost[hid] = goal;
}

bool GcsModule::queryHostPosition(int hostId, double& x, double& y, double& z) const
{
    if (hostId < 0)
        return false;
    std::string path = "host[" + std::to_string(hostId) + "].mobility";
    cModule *mobilityMod = getSimulation()->getSystemModule()->getModuleByPath(path.c_str());
    if (!mobilityMod)
        return false;
    auto *mobility = check_and_cast<IMobility *>(mobilityMod);
    Coord pos = mobility->getCurrentPosition();
    x = pos.getX();
    y = pos.getY();
    z = pos.getZ();
    return true;
}

void GcsModule::mapWorldToCanvas(double wx, double wy, double wz, double& outCx, double& outCy) const
{
    cModule *sys = getSystemModule();
    cCanvas *canvas = sys ? sys->getCanvas() : nullptr;
    if (!canvas) {
        outCx = 0;
        outCy = 0;
        return;
    }
    CanvasProjection *proj = CanvasProjection::getCanvasProjection(canvas);
    cFigure::Point p = proj->computeCanvasPoint(Coord(wx, wy, wz));
    outCx = p.x;
    outCy = p.y;
}

void GcsModule::ensureCanvasDistanceScalePool()
{
    if (!presentationRoot || canvasScalePoolCreated)
        return;
    canvasScalePoolCreated = true;

    auto addSpine = [this](const char *name) {
        auto *p = new cPolylineFigure(name);
        p->setZIndex(7975);
        p->setLineWidth(1.5);
        p->setLineColor(cFigure::parseColor("#2a2a2a"));
        p->setVisible(false);
        presentationRoot->addFigure(p);
        return p;
    };
    canvasScaleLeftSpine = addSpine("canvasScaleLeftSpine");
    canvasScaleBottomSpine = addSpine("canvasScaleBottomSpine");

    for (int i = 0; i < kMaxScaleTicks; ++i) {
        auto *ls = new cPolylineFigure(("canvasScaleLTick" + std::to_string(i)).c_str());
        ls->setZIndex(7976);
        ls->setLineWidth(1.2);
        ls->setLineColor(cFigure::parseColor("#2a2a2a"));
        ls->setVisible(false);
        presentationRoot->addFigure(ls);
        canvasScaleLeftTickSegs.push_back(ls);

        auto *bs = new cPolylineFigure(("canvasScaleBTick" + std::to_string(i)).c_str());
        bs->setZIndex(7976);
        bs->setLineWidth(1.2);
        bs->setLineColor(cFigure::parseColor("#2a2a2a"));
        bs->setVisible(false);
        presentationRoot->addFigure(bs);
        canvasScaleBottomTickSegs.push_back(bs);

        auto *ll = new cTextFigure(("canvasScaleLLbl" + std::to_string(i)).c_str());
        ll->setZIndex(7977);
        ll->setAnchor(cFigure::ANCHOR_E);
        ll->setAlignment(cFigure::ALIGN_CENTER);
        ll->setColor(cFigure::parseColor("#1a1a1a"));
        ll->setText("");
        ll->setVisible(false);
        presentationRoot->addFigure(ll);
        canvasScaleLeftLabels.push_back(ll);

        auto *bl = new cTextFigure(("canvasScaleBLbl" + std::to_string(i)).c_str());
        bl->setZIndex(7977);
        bl->setAnchor(cFigure::ANCHOR_N);
        bl->setAlignment(cFigure::ALIGN_CENTER);
        bl->setColor(cFigure::parseColor("#1a1a1a"));
        bl->setText("");
        bl->setVisible(false);
        presentationRoot->addFigure(bl);
        canvasScaleBottomLabels.push_back(bl);
    }
}

void GcsModule::updateCanvasDistanceScales()
{
    auto hideAllScales = [&]() {
        if (canvasScaleLeftSpine)
            canvasScaleLeftSpine->setVisible(false);
        if (canvasScaleBottomSpine)
            canvasScaleBottomSpine->setVisible(false);
        for (auto *s : canvasScaleLeftTickSegs)
            if (s)
                s->setVisible(false);
        for (auto *s : canvasScaleBottomTickSegs)
            if (s)
                s->setVisible(false);
        for (auto *t : canvasScaleLeftLabels)
            if (t)
                t->setVisible(false);
        for (auto *t : canvasScaleBottomLabels)
            if (t)
                t->setVisible(false);
    };

    if (!presentationRoot || !hasPar("overlayDistanceScales") || !par("overlayDistanceScales").boolValue()) {
        hideAllScales();
        return;
    }

    ensureCanvasDistanceScalePool();

    cModule *net = getSystemModule();
    int nHosts = net->hasPar("numHosts") ? net->par("numHosts").intValue() : 0;
    if (nHosts <= 0) {
        hideAllScales();
        return;
    }

    // Fixed world rectangle (NED params): rulers stay put; only zRef follows hosts for projection.
    const double xLo = hasPar("overlayMapMinX") ? par("overlayMapMinX").doubleValueInUnit("m") : -100.0;
    const double xHi = hasPar("overlayMapMaxX") ? par("overlayMapMaxX").doubleValueInUnit("m") : 1000.0;
    const double yLo = hasPar("overlayMapMinY") ? par("overlayMapMinY").doubleValueInUnit("m") : -100.0;
    const double yHi = hasPar("overlayMapMaxY") ? par("overlayMapMaxY").doubleValueInUnit("m") : 1000.0;
    if (!std::isfinite(xLo) || !std::isfinite(xHi) || !std::isfinite(yLo) || !std::isfinite(yHi) || xHi - xLo < 1.0
        || yHi - yLo < 1.0) {
        hideAllScales();
        return;
    }

    double zSum = 0.0;
    int nPos = 0;
    for (int hid = 0; hid < nHosts; ++hid) {
        double x = 0, y = 0, z = 0;
        if (!queryHostPosition(hid, x, y, z))
            continue;
        (void)x;
        (void)y;
        zSum += z;
        ++nPos;
    }
    const double zRef = nPos > 0 ? zSum / nPos : 0.0;

    const double inset = hasPar("overlayScaleAxisInsetM") ? par("overlayScaleAxisInsetM").doubleValueInUnit("m") : 0.0;
    double tick = hasPar("overlayScaleTickSpacingM") ? par("overlayScaleTickSpacingM").doubleValueInUnit("m") : 200.0;
    const double tickLen = hasPar("overlayScaleTickLengthM") ? par("overlayScaleTickLengthM").doubleValueInUnit("m") : 35.0;
    if (tick < 5.0)
        tick = 100.0;

    const double spanX = xHi - xLo;
    const double spanY = yHi - yLo;
    const double insetClamped = std::max(0.0, std::min(inset, 0.49 * std::min(spanX, spanY)));
    const double xLeft = xLo + insetClamped;
    const double yBottom = yLo + insetClamped;

    // First major tick on or inside the map rect (avoids e.g. -200 m when yLo=-100 m: floor()
    // would start below the spine so labels sit off the axis until the swarm moves).
    const double tickEps = 1e-9;
    auto firstMajorTick = [&](double lo) {
        double t = std::floor(lo / tick) * tick;
        const int guard = 10000;
        for (int k = 0; k < guard && t < lo - tickEps; ++k)
            t += tick;
        return t;
    };

    // Left spine (world X = const, varying Y)
    {
        std::vector<cFigure::Point> pts;
        pts.reserve(129);
        for (int s = 0; s <= 128; ++s) {
            const double y = yLo + (yHi - yLo) * (s / 128.0);
            double cx = 0, cy = 0;
            mapWorldToCanvas(xLeft, y, zRef, cx, cy);
            pts.emplace_back(cx, cy);
        }
        canvasScaleLeftSpine->setPoints(pts);
        canvasScaleLeftSpine->setVisible(true);
    }

    // Bottom spine (world Y = const, varying X)
    {
        std::vector<cFigure::Point> pts;
        pts.reserve(129);
        for (int s = 0; s <= 128; ++s) {
            const double x = xLo + (xHi - xLo) * (s / 128.0);
            double cx = 0, cy = 0;
            mapWorldToCanvas(x, yBottom, zRef, cx, cy);
            pts.emplace_back(cx, cy);
        }
        canvasScaleBottomSpine->setPoints(pts);
        canvasScaleBottomSpine->setVisible(true);
    }

    auto formatM = [](double m, char *buf, size_t n) {
        const double a = std::fabs(m);
        if (a >= 1000.0)
            snprintf(buf, n, "%.2f km", m / 1000.0);
        else
            snprintf(buf, n, "%.0f m", m);
    };

    // Major ticks along Y (left axis)
    {
        const double yStart = firstMajorTick(yLo);
        int ti = 0;
        for (double y = yStart; y <= yHi + tickEps && ti < kMaxScaleTicks; y += tick, ++ti) {
            double cx0 = 0, cy0 = 0, cx1 = 0, cy1 = 0;
            mapWorldToCanvas(xLeft, y, zRef, cx0, cy0);
            mapWorldToCanvas(xLeft - tickLen, y, zRef, cx1, cy1);
            std::vector<cFigure::Point> seg = {cFigure::Point(cx0, cy0), cFigure::Point(cx1, cy1)};
            canvasScaleLeftTickSegs[static_cast<size_t>(ti)]->setPoints(seg);
            canvasScaleLeftTickSegs[static_cast<size_t>(ti)]->setVisible(true);

            char buf[64];
            formatM(y, buf, sizeof(buf));
            cTextFigure *lbl = canvasScaleLeftLabels[static_cast<size_t>(ti)];
            lbl->setText(buf);
            lbl->setPosition(cFigure::Point(cx1 - 4, cy0));
            lbl->setVisible(true);
        }
        for (int j = ti; j < kMaxScaleTicks; ++j) {
            canvasScaleLeftTickSegs[static_cast<size_t>(j)]->setVisible(false);
            canvasScaleLeftLabels[static_cast<size_t>(j)]->setVisible(false);
        }
    }

    // Major ticks along X (bottom axis)
    {
        const double xStart = firstMajorTick(xLo);
        int ti = 0;
        for (double x = xStart; x <= xHi + tickEps && ti < kMaxScaleTicks; x += tick, ++ti) {
            double cx0 = 0, cy0 = 0, cx1 = 0, cy1 = 0;
            mapWorldToCanvas(x, yBottom, zRef, cx0, cy0);
            mapWorldToCanvas(x, yBottom + tickLen, zRef, cx1, cy1);
            std::vector<cFigure::Point> seg = {cFigure::Point(cx0, cy0), cFigure::Point(cx1, cy1)};
            canvasScaleBottomTickSegs[static_cast<size_t>(ti)]->setPoints(seg);
            canvasScaleBottomTickSegs[static_cast<size_t>(ti)]->setVisible(true);

            char buf[64];
            formatM(x, buf, sizeof(buf));
            cTextFigure *lbl = canvasScaleBottomLabels[static_cast<size_t>(ti)];
            lbl->setText(buf);
            lbl->setPosition(cFigure::Point(cx0, std::max(cy0, cy1) + 10));
            lbl->setVisible(true);
        }
        for (int j = ti; j < kMaxScaleTicks; ++j) {
            canvasScaleBottomTickSegs[static_cast<size_t>(j)]->setVisible(false);
            canvasScaleBottomLabels[static_cast<size_t>(j)]->setVisible(false);
        }
    }
}

void GcsModule::requestCanvasOverlayRefresh()
{
    if (!getEnvir()->isGUI())
        return;
    if (!hasPar("drawPresentationOverlay") || !par("drawPresentationOverlay").boolValue())
        return;
    if (!canvasOverlayRefreshMsg)
        return;
    // Coalesce: one refresh per simTime; high scheduling priority runs after default (0)
    // mobility/control events at the same timestamp so benign markers use a full snapshot.
    if (canvasOverlayRefreshMsg->isScheduled()) {
        if (canvasOverlayRefreshMsg->getArrivalTime() == simTime())
            return;
        cancelEvent(canvasOverlayRefreshMsg);
    }
    scheduleAt(simTime(), canvasOverlayRefreshMsg);
}

void GcsModule::refreshCanvasOverlay()
{
    if (!getEnvir()->isGUI())
        return;
    if (!hasPar("drawPresentationOverlay") || !par("drawPresentationOverlay").boolValue())
        return;

    ensurePresentationCanvas();
    if (!presentationRoot)
        return;

    // ── XY marginal confidence ellipse (top-down) ───────────────────────────
    if (lastEllipsoidValid && canvasEllipseFig && lastEllipsoidMu.size() >= 3
        && lastEllipsoidSigma.size() >= 2 && lastEllipsoidSigma[0].size() >= 2
        && lastEllipsoidSigma[1].size() >= 2) {

        double s00 = lastEllipsoidSigma[0][0];
        double s01 = lastEllipsoidSigma[0][1];
        double s10 = lastEllipsoidSigma[1][0];
        double s11 = lastEllipsoidSigma[1][1];
        double s01m = 0.5 * (s01 + s10);
        double tr = s00 + s11;
        double det = s00 * s11 - s01m * s01m;
        double disc = tr * tr * 0.25 - det;
        if (disc < 0)
            disc = 0;
        double l1 = tr * 0.5 + std::sqrt(disc);
        double l2 = tr * 0.5 - std::sqrt(disc);
        double lmax = std::max(l1, l2);
        double lmin = std::min(l1, l2);

        double chi2 = chi2Threshold2D(lastEllipsoidAlpha);
        double axisMajor = std::sqrt(std::max(0.0, lmax * chi2));
        double axisMinor = std::sqrt(std::max(0.0, lmin * chi2));

        double vx, vy;
        if (std::abs(s01m) > 1e-9) {
            vx = lmax - s11;
            vy = s01m;
        }
        else if (lmax > s00 + 1e-9) {
            vx = 1;
            vy = 0;
        }
        else {
            vx = 0;
            vy = 1;
        }
        double vlen = std::hypot(vx, vy);
        if (vlen < 1e-12) {
            vx = 1;
            vy = 0;
            vlen = 1;
        }
        vx /= vlen;
        vy /= vlen;
        double angle = std::atan2(vy, vx);

        const int N = 72;
        std::vector<cFigure::Point> pts;
        pts.reserve(N + 1);
        double cx0 = lastEllipsoidMu[0];
        double cy0 = lastEllipsoidMu[1];
        const double cz0 = lastEllipsoidMu.size() >= 3 ? lastEllipsoidMu[2] : 0.0;
        for (int i = 0; i <= N; ++i) {
            double t = (2.0 * M_PI * i) / N;
            double lx = axisMajor * std::cos(t);
            double ly = axisMinor * std::sin(t);
            double wx = cx0 + lx * std::cos(angle) - ly * std::sin(angle);
            double wy = cy0 + lx * std::sin(angle) + ly * std::cos(angle);
            double cpx, cpy;
            mapWorldToCanvas(wx, wy, cz0, cpx, cpy);
            pts.push_back(cFigure::Point(cpx, cpy));
        }
        if (pts.size() >= 2)
            pts.push_back(pts[0]);
        canvasEllipseFig->setPoints(pts);
        canvasEllipseFig->setLineColor(
            cFigure::parseColor(lastEllipsoidDetected ? "red" : "darkorange"));
        canvasEllipseFig->setVisible(true);
    }
    else if (canvasEllipseFig) {
        canvasEllipseFig->setVisible(false);
    }

    // ── Claimed RID trail (broadcast positions) ───────────────────────────
    if (canvasClaimedFig && !claimedTrailPoints.empty()) {
        std::vector<cFigure::Point> pts;
        pts.reserve(claimedTrailPoints.size());
        for (const auto& p : claimedTrailPoints) {
            double cpx, cpy;
            mapWorldToCanvas(std::get<0>(p), std::get<1>(p), std::get<2>(p), cpx, cpy);
            pts.push_back(cFigure::Point(cpx, cpy));
        }
        canvasClaimedFig->setPoints(pts);
        canvasClaimedFig->setVisible(true);
    }
    else if (canvasClaimedFig) {
        canvasClaimedFig->setVisible(false);
    }

    // ── True spoofer position (follow / explain ground truth) ──────────────
    if (trackHostId >= 0 && canvasTruthFig) {
        double tx, ty, tz;
        if (queryHostPosition(trackHostId, tx, ty, tz)) {
            double cpx, cpy;
            mapWorldToCanvas(tx, ty, tz, cpx, cpy);
            const double d = 12;
            canvasTruthFig->setBounds(
                cFigure::Rectangle(cpx - d * 0.5, cpy - d * 0.5, d, d));
            canvasTruthFig->setVisible(true);
        }
        else {
            canvasTruthFig->setVisible(false);
        }
    }
    else if (canvasTruthFig) {
        canvasTruthFig->setVisible(false);
    }

    // ── Latest claimed position marker ─────────────────────────────────────
    if (canvasClaimedHeadFig && !claimedTrailPoints.empty()) {
        const auto& tail = claimedTrailPoints.back();
        double cpx, cpy;
        mapWorldToCanvas(std::get<0>(tail), std::get<1>(tail), std::get<2>(tail), cpx, cpy);
        const double d = 14;
        canvasClaimedHeadFig->setBounds(
            cFigure::Rectangle(cpx - d * 0.5, cpy - d * 0.5, d, d));
        bool det = !claimedTrailDetected.empty() && claimedTrailDetected.back();
        canvasClaimedHeadFig->setFillColor(cFigure::parseColor(det ? "black" : "red"));
        canvasClaimedHeadFig->setLineColor(cFigure::parseColor(det ? "black" : "darkred"));
        canvasClaimedHeadFig->setVisible(true);
    }
    else if (canvasClaimedHeadFig) {
        canvasClaimedHeadFig->setVisible(false);
    }

    // ── Benign hosts: filled red = unsafe region; hollow orange rect = 3D NMAC to spoofer
    //    truth only; optional hollow orange *oval* repeats that NMAC cue (also when unsafe). ──
    const bool showBenignRisk =
        hasPar("overlayBenignRiskMarkers") && par("overlayBenignRiskMarkers").boolValue();
    const bool showBenignSpooferNmacRing =
        showBenignRisk
        && (!hasPar("overlayBenignSpooferNmacRing") || par("overlayBenignSpooferNmacRing").boolValue());
    if (showBenignRisk) {
        cModule *sys = getSystemModule();
        int nHosts = sys->hasPar("numHosts") ? sys->par("numHosts").intValue() : 0;
        if (nHosts > 0) {
            ensureBenignRiskMarkerCapacity(static_cast<size_t>(nHosts));
            ensureBenignSpooferNmacRingCapacity(static_cast<size_t>(nHosts));
            // NMAC uses ground-truth spoofer position (last host), not trackHostId (Python track).
            const int spooferHostId = nHosts - 1;

            const bool ellipsoidReady =
                lastEllipsoidValid && lastEllipsoidMu.size() >= 3
                && lastEllipsoidSigma.size() >= 3 && lastEllipsoidSigma[0].size() >= 3
                && lastEllipsoidSigma[1].size() >= 3 && lastEllipsoidSigma[2].size() >= 3;
            double S3[3][3];
            if (ellipsoidReady) {
                for (int i = 0; i < 3; ++i)
                    for (int j = 0; j < 3; ++j)
                        S3[i][j] = 0.5
                            * (lastEllipsoidSigma[i][j] + lastEllipsoidSigma[j][i]);
            }

            const double thr3 = chi2Threshold3D(lastEllipsoidAlpha);
            const double thr2 = chi2Threshold2D(lastEllipsoidAlpha);
            const double mu0 = lastEllipsoidMu.size() >= 3 ? lastEllipsoidMu[0] : 0.0;
            const double mu1 = lastEllipsoidMu.size() >= 3 ? lastEllipsoidMu[1] : 0.0;
            const double mu2 = lastEllipsoidMu.size() >= 3 ? lastEllipsoidMu[2] : 0.0;

            // Same XY marginal as the canvas confidence ellipse (only needs 2×2 Σ block).
            // The 3D test below can fail (incomplete Σ, Cholesky) while the ellipse still draws.
            bool marginal2dReady = false;
            double mInv00 = 0, mInv01 = 0, mInv11 = 0;
            if (lastEllipsoidValid && lastEllipsoidMu.size() >= 3
                && lastEllipsoidSigma.size() >= 2 && lastEllipsoidSigma[0].size() >= 2
                && lastEllipsoidSigma[1].size() >= 2) {
                const double s00 = lastEllipsoidSigma[0][0];
                const double s01 = lastEllipsoidSigma[0][1];
                const double s10 = lastEllipsoidSigma[1][0];
                const double s11 = lastEllipsoidSigma[1][1];
                const double s01m = 0.5 * (s01 + s10);
                const double det2 = s00 * s11 - s01m * s01m;
                if (det2 > 1e-18) {
                    mInv00 = s11 / det2;
                    mInv01 = -s01m / det2;
                    mInv11 = s00 / det2;
                    marginal2dReady = true;
                }
            }

            double sx = 0, sy = 0, sz = 0;
            const bool haveSpooferTruth =
                spooferHostId >= 0 && queryHostPosition(spooferHostId, sx, sy, sz);
            const double nmacR = hasPar("overlayNmacProximityM")
                ? par("overlayNmacProximityM").doubleValueInUnit("m")
                : 50.0;

            for (int hid = 0; hid < nHosts; ++hid) {
                cRectangleFigure *fig = canvasBenignRiskFigs[static_cast<size_t>(hid)];
                cOvalFigure *nmacRing = canvasBenignSpooferNmacRings[static_cast<size_t>(hid)];
                nmacRing->setVisible(false);
                if (hid == spooferHostId) {
                    fig->setVisible(false);
                    continue;
                }
                double x = 0, y = 0, z = 0;
                if (!queryHostPosition(hid, x, y, z)) {
                    fig->setVisible(false);
                    continue;
                }

                bool in3d = false;
                if (ellipsoidReady) {
                    const double dx = x - mu0;
                    const double dy = y - mu1;
                    const double dz = z - mu2;
                    double diff[3] = {dx, dy, dz};
                    double md3 = 0;
                    const bool ok3 = mahalanobisSquared3(S3, diff, md3);
                    in3d = ok3 && md3 <= thr3 + 1e-6;
                }

                bool in2dMarginal = false;
                if (marginal2dReady) {
                    const double ddx2 = x - mu0;
                    const double ddy2 = y - mu1;
                    const double md2 =
                        ddx2 * (mInv00 * ddx2 + mInv01 * ddy2) + ddy2 * (mInv01 * ddx2 + mInv11 * ddy2);
                    in2dMarginal = md2 <= thr2 + 1e-6;
                }
                const bool plannerInside =
                    benignInsideUnsafePlannerActive
                    && benignInsideUnsafeFromPlanner.find(hid) != benignInsideUnsafeFromPlanner.end();
                // When Python publishes benign_inside_unsafe_host_ids, use it alone for the
                // filled red "unsafe" marker so canvas does not fight NumPy ellipsoid tests.
                const bool geomUnsafe = in3d || in2dMarginal;
                const bool inUnsafeSet =
                    benignInsideUnsafePlannerActive ? plannerInside : geomUnsafe;

                bool nmac = false;
                if (haveSpooferTruth) {
                    const double ddx = x - sx;
                    const double ddy = y - sy;
                    const double ddz = z - sz;
                    const double dist = std::sqrt(ddx * ddx + ddy * ddy + ddz * ddz);
                    nmac = dist < nmacR;
                }

                if (!inUnsafeSet && !nmac) {
                    fig->setVisible(false);
                    continue;
                }

                double cpx = 0, cpy = 0;
                mapWorldToCanvas(x, y, z, cpx, cpy);
                const double box = inUnsafeSet ? 28.0 : 22.0;
                fig->setBounds(cFigure::Rectangle(cpx - box * 0.5, cpy - box * 0.5, box, box));
                if (inUnsafeSet) {
                    fig->setFilled(true);
                    fig->setLineWidth(3);
                    fig->setLineColor(cFigure::parseColor("red"));
                    fig->setFillColor(cFigure::parseColor("#FF6666"));
                }
                else {
                    // NMAC-only (outside published unsafe set): hollow warning
                    fig->setFilled(false);
                    fig->setLineWidth(2);
                    fig->setLineColor(cFigure::parseColor("darkorange"));
                }
                fig->setVisible(true);

                if (showBenignSpooferNmacRing && nmac && haveSpooferTruth) {
                    const double ringD = std::max(box + 10.0, 30.0);
                    nmacRing->setBounds(cFigure::Rectangle(cpx - ringD * 0.5, cpy - ringD * 0.5, ringD, ringD));
                    nmacRing->setVisible(true);
                }
            }
            for (size_t i = static_cast<size_t>(nHosts); i < canvasBenignRiskFigs.size(); ++i)
                canvasBenignRiskFigs[i]->setVisible(false);
            for (size_t i = static_cast<size_t>(nHosts); i < canvasBenignSpooferNmacRings.size(); ++i)
                canvasBenignSpooferNmacRings[i]->setVisible(false);
        }
        else {
            for (auto *r : canvasBenignSpooferNmacRings)
                if (r)
                    r->setVisible(false);
        }
    }
    else {
        for (auto *fig : canvasBenignRiskFigs)
            if (fig)
                fig->setVisible(false);
        for (auto *r : canvasBenignSpooferNmacRings)
            if (r)
                r->setVisible(false);
    }

    // ── Per-host waypoint goals (2D): dot color matches mobility trail palette by index ──
    const bool showHostGoals =
        hasPar("overlayShowHostGoals") && par("overlayShowHostGoals").boolValue();
    if (showHostGoals) {
        cModule *sys = getSystemModule();
        int nHosts = sys->hasPar("numHosts") ? sys->par("numHosts").intValue() : 0;
        if (nHosts > 0) {
            ensureGoalDotCapacity(static_cast<size_t>(nHosts));
            for (int hid = 0; hid < nHosts; ++hid) {
                tryCacheWaypointGoalForHost(hid);
                cOvalFigure *fig = canvasGoalDots[static_cast<size_t>(hid)];
                cTextFigure *lbl = canvasGoalLabels[static_cast<size_t>(hid)];
                auto git = hostGoalsByHost.find(hid);
                if (git == hostGoalsByHost.end()) {
                    fig->setVisible(false);
                    lbl->setVisible(false);
                    continue;
                }
                const double gx = git->second[0];
                const double gy = git->second[1];
                const double gz = git->second[2];
                double cpx = 0, cpy = 0;
                mapWorldToCanvas(gx, gy, gz, cpx, cpy);
                const double d = 14;
                fig->setBounds(cFigure::Rectangle(cpx - d * 0.5, cpy - d * 0.5, d, d));
                fig->setFillColor(cFigure::parseColor(goalDotColorForHostIndex(hid)));
                fig->setLineColor(cFigure::parseColor("#202020"));
                fig->setTooltip(
                    (std::string("Waypoint goal for host[") + std::to_string(hid) + "]").c_str());
                fig->setVisible(true);

                std::string hostNum = std::to_string(hid);
                lbl->setText(hostNum.c_str());
                lbl->setColor(cFigure::parseColor("#101010"));
                lbl->setPosition(cFigure::Point(cpx, cpy + d * 0.5 + 1));
                lbl->setTooltip(
                    (std::string("Waypoint goal for host[") + std::to_string(hid) + "]").c_str());
                lbl->setVisible(true);
            }
            for (size_t i = static_cast<size_t>(nHosts); i < canvasGoalDots.size(); ++i) {
                if (canvasGoalDots[i])
                    canvasGoalDots[i]->setVisible(false);
                if (i < canvasGoalLabels.size() && canvasGoalLabels[i])
                    canvasGoalLabels[i]->setVisible(false);
            }
        }
        else {
            for (auto *fig : canvasGoalDots)
                if (fig)
                    fig->setVisible(false);
            for (auto *lbl : canvasGoalLabels)
                if (lbl)
                    lbl->setVisible(false);
        }
    }
    else {
        for (auto *fig : canvasGoalDots)
            if (fig)
                fig->setVisible(false);
        for (auto *lbl : canvasGoalLabels)
            if (lbl)
                lbl->setVisible(false);
    }

    updateCanvasDistanceScales();
}

// ── Shared result handler (log + commands + visualization) ──────────────────

static void handlePyResult(GcsModule *gcs, const py::object& result)
{
    if (result.is_none() || !py::isinstance<py::dict>(result))
        return;

    py::dict d = result.cast<py::dict>();

    // Log entries: {"name": numeric_value, ...} → recorded as cOutVector
    if (d.contains("log") && !d["log"].is_none()) {
        py::dict logDict = d["log"].cast<py::dict>();
        std::map<std::string, double> entries;
        for (auto& item : logDict) {
            std::string name = item.first.cast<std::string>();
            double value = item.second.cast<double>();
            entries[name] = value;
        }
        gcs->emitLogEntries(entries);
    }

    // Control commands: {host_id: {...}, ...} → forwarded to UAV mobility
    if (d.contains("commands") && !d["commands"].is_none()) {
        py::dict commands = d["commands"].cast<py::dict>();
        py::module_ json = py::module_::import("json");
        for (auto& item : commands) {
            int hostId = item.first.cast<int>();
            std::string cmdJson = json.attr("dumps")(item.second).cast<std::string>();
            gcs->sendCommand(hostId, cmdJson);
        }
    }

    // Visualization: ellipsoid + claimed_pos (+ track_host_id) → OSG and/or canvas
    if (d.contains("visualization") && !d["visualization"].is_none()) {
        py::dict viz = d["visualization"].cast<py::dict>();

        // Benign unsafe host list: only refresh when Python sends the key (tick path).
        // Do not clear on unrelated visualization (e.g. claimed_pos-only beacons), or red
        // boxes flicker between geometric test and stale planner ids between ticks.
        if (py::len(viz) == 0) {
            gcs->benignInsideUnsafePlannerActive = false;
            gcs->benignInsideUnsafeFromPlanner.clear();
        }
        else if (viz.contains("benign_inside_unsafe_host_ids") && !viz["benign_inside_unsafe_host_ids"].is_none()) {
            gcs->benignInsideUnsafePlannerActive = true;
            gcs->benignInsideUnsafeFromPlanner.clear();
            py::list idlist = viz["benign_inside_unsafe_host_ids"].cast<py::list>();
            for (auto item : idlist)
                gcs->benignInsideUnsafeFromPlanner.insert(py::cast<int>(item));
        }

        if (viz.contains("track_host_id") && !viz["track_host_id"].is_none()) {
            int newTrack = py::cast<int>(viz["track_host_id"]);
            if (gcs->trackHostId >= 0 && newTrack != gcs->trackHostId)
                gcs->resetClaimedTrail();
            gcs->trackHostId = newTrack;
        }

        // Chance-constraint ellipsoid
        if (viz.contains("ellipsoid") && !viz["ellipsoid"].is_none()) {
            py::dict ellipsoid = viz["ellipsoid"].cast<py::dict>();
            bool detected = viz.contains("detected") && viz["detected"].cast<bool>();

            std::vector<double> mu;
            for (auto item : ellipsoid["mu"].cast<py::list>())
                mu.push_back(item.cast<double>());

            std::vector<std::vector<double>> sigma;
            for (auto row : ellipsoid["sigma"].cast<py::list>()) {
                std::vector<double> r;
                for (auto val : row.cast<py::list>())
                    r.push_back(val.cast<double>());
                sigma.push_back(r);
            }

            double alpha = ellipsoid.contains("alpha") ? ellipsoid["alpha"].cast<double>() : 0.05;

            gcs->updateVisualization(mu, sigma, alpha, detected);
        }

        // Claimed position trail
        if (viz.contains("claimed_pos") && !viz["claimed_pos"].is_none()) {
            py::list pos = viz["claimed_pos"].cast<py::list>();
            if (py::len(pos) >= 3) {
                bool claimedDetected =
                    viz.contains("claimed_detected") && !viz["claimed_detected"].is_none()
                    ? viz["claimed_detected"].cast<bool>()
                    : false;
                gcs->addClaimedTrailPoint(
                    pos[0].cast<double>(),
                    pos[1].cast<double>(),
                    pos[2].cast<double>(),
                    claimedDetected);
            }
        }
    }
}

// ── Initialization ──────────────────────────────────────────────────────────

void GcsModule::initialize()
{
    // Parse federate indices
    std::string indices = par("federateIndices").stdstringValue();
    if (!indices.empty()) {
        allFederates = false;
        std::istringstream iss(indices);
        int idx;
        while (iss >> idx) {
            federateSet.insert(idx);
        }
    }

    sendControlCommands = par("sendControlCommands").boolValue();

    // Subscribe to radio medium signal
    radioMedium = getSimulation()->getModuleByPath("radioMedium");
    if (!radioMedium) {
        throw cRuntimeError("GcsModule: radioMedium not found");
    }
    radioMedium->subscribe(IRadioMedium::signalRemovedSignal, this);

    claimedTrailPoints.clear();
    claimedTrailDetected.clear();
    lastEllipsoidValid = false;
    trackHostId = -1;
    benignInsideUnsafeFromPlanner.clear();
    benignInsideUnsafePlannerActive = false;
    removePresentationCanvas();

    // Initialize Python class if configured
    std::string pyClassName = par("pyClass").stdstringValue();
    if (!pyClassName.empty()) {
        cModule *mod = getModuleByPath(par("pyBridgePath").stdstringValue().c_str());
        pyBridge = check_and_cast<PyBridge *>(mod);
        pyHandle = pyBridge->instantiateClass(pyClassName);
    }

    // Schedule periodic tick timer if configured
    tickInterval = par("tickInterval").doubleValueInUnit("s");
    if (tickInterval > 0 && pyHandle >= 0) {
        tickTimer = new cMessage("gcsTick");
        scheduleAt(simTime() + tickInterval, tickTimer);
    }

    canvasOverlayRefreshMsg = new cMessage("gcsCanvasOverlayRefresh");
    // Smaller priority runs first in OMNeT++; use large value so overlay runs after mobility at same t.
    // OMNeT++ uses short priorities; keep in [-32768, 32767] (100000 overflows).
    canvasOverlayRefreshMsg->setSchedulingPriority(25000);
}

void GcsModule::finish()
{
    pyOnFinish();
}

void GcsModule::pyOnFinish()
{
    if (pyHandle < 0 || pyBridge == nullptr)
        return;

    PyBridgeImpl *impl = pyBridge->getImpl();
    py::gil_scoped_acquire gil;

    py::object instance = impl->getInstance(pyHandle);
    if (!py::hasattr(instance, "on_gcs_finish"))
        return;

    py::object result = impl->callMethod(pyHandle, "on_gcs_finish");
    if (result.is_none() || !py::isinstance<py::dict>(result))
        return;

    py::dict d = result.cast<py::dict>();
    if (!d.contains("scalars") || d["scalars"].is_none())
        return;

    py::dict scalars = d["scalars"].cast<py::dict>();
    for (auto &item : scalars) {
        std::string name = item.first.cast<std::string>();
        double value = item.second.cast<double>();
        recordScalar(name.c_str(), value);
    }
}

// ── Message handling ────────────────────────────────────────────────────────

void GcsModule::handleMessage(cMessage *msg)
{
    if (msg->isSelfMessage()) {
        if (msg == canvasOverlayRefreshMsg) {
            refreshCanvasOverlay();
            return;
        }
        if (tickTimer && msg == tickTimer) {
            pyOnTick();
            if (tickInterval > 0)
                scheduleAt(simTime() + tickInterval, tickTimer);
            return;
        }
        EV_WARN << "GcsModule: unexpected self-message: " << msg->getName() << endl;
        return;
    }

    GcsReport *report = dynamic_cast<GcsReport*>(msg);
    if (!report) {
        EV_WARN << "GcsModule: received unexpected message: " << msg->getName() << endl;
        delete msg;
        return;
    }

    // Filter by federate set
    int hostId = report->getReceiverHostId();
    if (!allFederates && federateSet.find(hostId) == federateSet.end()) {
        delete report;
        return;
    }

    // Store report grouped by (serialNumber, ridTimestamp)
    BeaconKey key(report->getSenderSerialNumber(), report->getRidTimestamp());
    reportsByBeacon[key].push_back(report);
}

// ── Signal handler ──────────────────────────────────────────────────────────

void GcsModule::receiveSignal(cComponent *source, simsignal_t signalID,
                              cObject *obj, cObject *details)
{
    if (signalID != IRadioMedium::signalRemovedSignal)
        return;

    Enter_Method_Silent();

    // Process all collected reports
    for (auto& [key, reports] : reportsByBeacon) {
        processTransmission(key, reports);

        // Clean up
        for (auto* r : reports)
            delete r;
    }
    reportsByBeacon.clear();
}

// ── Processing ──────────────────────────────────────────────────────────────

void GcsModule::processTransmission(const BeaconKey& key,
                                    const std::vector<GcsReport*>& reports)
{
    if (reports.empty())
        return;

    EV << "GcsModule: processing transmission (serial=" << key.first
       << ", ts=" << key.second << ") with " << reports.size()
       << " reports" << endl;

    if (pyHandle >= 0) {
        pyOnReport(key, reports);
    }
}

// ── Python on_gcs_reports() callback ────────────────────────────────────────

void GcsModule::pyOnReport(const BeaconKey& key,
                           const std::vector<GcsReport*>& reports)
{
    PyBridgeImpl *impl = pyBridge->getImpl();
    py::gil_scoped_acquire gil;

    // Build transmission data dict
    py::dict txData;
    txData["serial_number"] = key.first;
    txData["rid_timestamp"] = key.second;

    // Claimed position/velocity (same for all reports in a transmission)
    const GcsReport* first = reports[0];
    txData["claimed_pos"] = py::make_tuple(first->getClaimedPosX(),
                                           first->getClaimedPosY(),
                                           first->getClaimedPosZ());
    txData["claimed_vel"] = py::make_tuple(first->getClaimedSpeedVertical(),
                                           first->getClaimedSpeedHorizontal(),
                                           first->getClaimedHeading());

    // Optional true transmitter position for debugging/analysis.
    // Assumes sender serial maps to host index (default RID config).
    {
        int senderId = key.first;
        cModule *network = getSimulation()->getSystemModule();
        std::string path = "host[" + std::to_string(senderId) + "].mobility";
        cModule *mobilityMod = network->getModuleByPath(path.c_str());
        if (mobilityMod) {
            auto *mobility = check_and_cast<IMobility *>(mobilityMod);
            Coord pos = mobility->getCurrentPosition();
            txData["tx_true_pos"] = py::make_tuple(pos.getX(), pos.getY(), pos.getZ());
        }
    }

    // Per-receiver reports
    py::list reportList;
    for (const auto* r : reports) {
        py::dict rd;
        rd["host_id"]  = r->getReceiverHostId();
        rd["pos"]      = py::make_tuple(r->getRxPosX(), r->getRxPosY(), r->getRxPosZ());
        rd["rssi_dbm"] = r->getRssiDbm();
        double kfNis = r->getKfNis();
        rd["kf_nis"]   = (kfNis < 0) ? py::none().cast<py::object>() : py::cast(kfNis);
        reportList.append(rd);
    }
    txData["reports"] = reportList;
    // Provide host ids on report path too, so Python can keep visualization
    // source stable from the first transmission.
    py::list hostIds;
    if (!allFederates) {
        for (int id : federateSet)
            hostIds.append(id);
    }
    else {
        int n = getSystemModule()->par("numHosts").intValue();
        for (int i = 0; i < n; ++i)
            hostIds.append(i);
    }
    txData["host_ids"] = hostIds;
    txData["num_hosts"] = getSystemModule()->par("numHosts").intValue();
    txData["time"] = simTime().dbl();

    // Call Python: on_gcs_reports(transmission_data) — skip if method not defined
    py::object instance = impl->getInstance(pyHandle);
    if (!py::hasattr(instance, "on_gcs_reports"))
        return;

    py::object result = impl->callMethod(pyHandle, "on_gcs_reports", txData);
    handlePyResult(this, result);
}

// ── Python on_gcs_tick() callback ───────────────────────────────────────────

void GcsModule::pyOnTick()
{
    PyBridgeImpl *impl = pyBridge->getImpl();
    py::gil_scoped_acquire gil;

    tickCount++;

    py::dict data;
    data["time"] = simTime().dbl();
    data["tick_count"] = tickCount;
    data["num_hosts"] = getSystemModule()->par("numHosts").intValue();

    // Provide list of federate host IDs
    py::list hostIds;
    if (allFederates) {
        // If no explicit set, provide empty list (Python can decide)
        // In practice, planners should use explicit federateIndices
    } else {
        for (int id : federateSet)
            hostIds.append(id);
    }
    data["host_ids"] = hostIds;

    // Ground-truth positions (simulation mobility) for NMAC / analysis — host_id -> (x,y,z)
    py::dict groundTruth;
    std::vector<int> hostIdList;
    if (!allFederates) {
        for (int id : federateSet)
            hostIdList.push_back(id);
    }
    else {
        int n = getSystemModule()->par("numHosts").intValue();
        for (int i = 0; i < n; ++i)
            hostIdList.push_back(i);
    }
    cModule *network = getSimulation()->getSystemModule();
    for (int hid : hostIdList) {
        std::string path = "host[" + std::to_string(hid) + "].mobility";
        cModule *mobilityMod = network->getModuleByPath(path.c_str());
        if (!mobilityMod)
            continue;
        auto *mobility = check_and_cast<IMobility *>(mobilityMod);
        Coord pos = mobility->getCurrentPosition();
        groundTruth[py::int_(hid)] = py::make_tuple(pos.getX(), pos.getY(), pos.getZ());

        tryCacheWaypointGoalForHost(hid);
    }
    data["ground_truth_positions"] = groundTruth;
    py::dict hostGoals;
    for (const auto &it : hostGoalsByHost) {
        int hid = it.first;
        const auto &g = it.second;
        hostGoals[py::int_(hid)] = py::make_tuple(g[0], g[1], g[2]);
    }
    data["host_goals"] = hostGoals;

    // Skip if method not defined
    py::object instance = impl->getInstance(pyHandle);
    if (!py::hasattr(instance, "on_gcs_tick"))
        return;

    py::object result = impl->callMethod(pyHandle, "on_gcs_tick", data);
    handlePyResult(this, result);
}

// ── Log recording ───────────────────────────────────────────────────────────

void GcsModule::emitLogEntries(const std::map<std::string, double>& entries)
{
    for (auto& [name, value] : entries) {
        // Create cOutVector on first use (always records to .vec, no NED needed)
        auto it = logVectors.find(name);
        if (it == logVectors.end()) {
            it = logVectors.emplace(name, new cOutVector(name.c_str())).first;
        }
        it->second->record(value);
    }
}

// ── Control command forwarding ──────────────────────────────────────────────

void GcsModule::sendCommand(int hostId, const std::string& commandJson)
{
    if (!sendControlCommands)
        return;

    // Find the target host's mobility module
    std::string path = "host[" + std::to_string(hostId) + "].mobility";
    cModule *mobility = getSimulation()->getSystemModule()->getModuleByPath(path.c_str());
    if (!mobility) {
        EV_WARN << "GcsModule: cannot find mobility for host[" << hostId << "]" << endl;
        return;
    }

    GcsCommand *cmd = new GcsCommand("GcsCommand");
    cmd->setTargetHostId(hostId);
    cmd->setCommandJson(commandJson.c_str());
    sendDirect(cmd, mobility, "commandIn");
}
