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

#include <cmath>
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
        refreshCanvasOverlay();
}

void GcsModule::addClaimedTrailPoint(double x, double y, double z, bool detected)
{
    if (!getEnvir()->isGUI())
        return;

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
        refreshCanvasOverlay();
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

void GcsModule::computeOverlayBounds(double& minX, double& maxX, double& minY, double& maxY) const
{
    minX = par("overlayMapMinX").doubleValueInUnit("m");
    maxX = par("overlayMapMaxX").doubleValueInUnit("m");
    minY = par("overlayMapMinY").doubleValueInUnit("m");
    maxY = par("overlayMapMaxY").doubleValueInUnit("m");

    if (par("overlayFollowSpoofer").boolValue() && trackHostId >= 0) {
        double tx = 0, ty = 0, tz = 0;
        if (queryHostPosition(trackHostId, tx, ty, tz)) {
            double hs = par("overlayFollowHalfSpan").doubleValueInUnit("m");
            minX = tx - hs;
            maxX = tx + hs;
            minY = ty - hs;
            maxY = ty + hs;
        }
    }

    if (maxX <= minX)
        maxX = minX + 1.0;
    if (maxY <= minY)
        maxY = minY + 1.0;
}

void GcsModule::mapWorldToCanvas(double wx, double wy, double& outCx, double& outCy) const
{
    double minX, maxX, minY, maxY;
    computeOverlayBounds(minX, maxX, minY, maxY);

    // Match BasicUav.ned @display("bgb=1000,1000") — canvas mapping is in layout pixels.
    const double cw = 1000;
    const double ch = 1000;

    const double margin = 40;
    double W = std::max(10.0, cw - 2 * margin);
    double H = std::max(10.0, ch - 2 * margin);
    outCx = margin + (wx - minX) / (maxX - minX) * W;
    outCy = ch - margin - (wy - minY) / (maxY - minY) * H;
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
        for (int i = 0; i <= N; ++i) {
            double t = (2.0 * M_PI * i) / N;
            double lx = axisMajor * std::cos(t);
            double ly = axisMinor * std::sin(t);
            double wx = cx0 + lx * std::cos(angle) - ly * std::sin(angle);
            double wy = cy0 + lx * std::sin(angle) + ly * std::cos(angle);
            double cpx, cpy;
            mapWorldToCanvas(wx, wy, cpx, cpy);
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
            mapWorldToCanvas(std::get<0>(p), std::get<1>(p), cpx, cpy);
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
            mapWorldToCanvas(tx, ty, cpx, cpy);
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
        mapWorldToCanvas(std::get<0>(tail), std::get<1>(tail), cpx, cpy);
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

        if (viz.contains("track_host_id") && !viz["track_host_id"].is_none())
            gcs->trackHostId = py::cast<int>(viz["track_host_id"]);

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
        // Periodic tick
        pyOnTick();
        scheduleAt(simTime() + tickInterval, tickTimer);
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

        // Cache host final goal from waypoint script once (deterministic, no runtime inference).
        if (hostGoalsByHost.find(hid) == hostGoalsByHost.end() && mobilityMod->hasPar("waypointScript")) {
            cXMLElement *wpXml = mobilityMod->par("waypointScript").xmlValue();
            if (wpXml) {
                bool foundMoveto = false;
                std::array<double, 3> goal = {NAN, NAN, NAN};
                for (cXMLElement *child = wpXml->getFirstChild(); child; child = child->getNextSibling()) {
                    const char *tag = child->getTagName();
                    double x = atof(child->getAttribute("x") ? child->getAttribute("x") : "0");
                    double y = atof(child->getAttribute("y") ? child->getAttribute("y") : "0");
                    double z = atof(child->getAttribute("z") ? child->getAttribute("z") : "0");
                    if (strcmp(tag, "set") == 0 && !foundMoveto) {
                        goal = {x, y, z};
                    }
                    else if (strcmp(tag, "moveto") == 0) {
                        goal = {x, y, z};
                        foundMoveto = true;
                    }
                }
                if (std::isfinite(goal[0]) && std::isfinite(goal[1]) && std::isfinite(goal[2])) {
                    hostGoalsByHost[hid] = goal;
                }
            }
        }
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
