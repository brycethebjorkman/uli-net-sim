//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// IMPORTANT: PyBridgePy.h must come BEFORE omnetpp.h to avoid macro conflicts.
//

#include "pybridge/PyBridgePy.h"
#include "GcsModule.h"
#include "pybridge/PyBridge.h"

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

Define_Module(GcsModule);

#ifdef WITH_OSG
static constexpr bool hasOsg = true;
#else
static constexpr bool hasOsg = false;
#endif

GcsModule::~GcsModule()
{
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
    if constexpr (hasOsg) {
#ifdef WITH_OSG
        if (!getEnvir()->isGUI())
            return;

        auto *osgCanvas = getSystemModule()->getOsgCanvas();
        auto *scene = osgCanvas ? dynamic_cast< ::osg::Group*>(osgCanvas->getScene()) : nullptr;
        if (!scene)
            return;

        if (mu.size() < 3 || sigma.size() < 3)
            return;

        // Build 3x3 covariance matrix
        Eigen::Matrix3d cov;
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++)
                cov(i, j) = (sigma[i].size() > (size_t)j) ? sigma[i][j] : 0.0;

        // Eigendecomposition for ellipsoid axes
        Eigen::SelfAdjointEigenSolver<Eigen::Matrix3d> solver(cov);
        if (solver.info() != Eigen::Success)
            return;

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
#endif
    }
}

void GcsModule::addClaimedTrailPoint(double x, double y, double z)
{
    if constexpr (hasOsg) {
#ifdef WITH_OSG
        if (!getEnvir()->isGUI())
            return;

        claimedTrailPoints.emplace_back(x, y, z);

        auto *osgCanvas = getSystemModule()->getOsgCanvas();
        auto *scene = osgCanvas ? dynamic_cast< ::osg::Group*>(osgCanvas->getScene()) : nullptr;
        if (!scene)
            return;

        // Remove previous trail group and rebuild (includes all spheres + line)
        if (claimedTrailGeode) {
            scene->removeChild(static_cast< ::osg::Node*>(claimedTrailGeode));
            claimedTrailGeode = nullptr;
        }

        auto *group = new ::osg::Group();

        // Red sphere breadcrumb at each claimed position
        for (const auto& [px, py, pz] : claimedTrailPoints) {
            auto *sphere = new ::osg::ShapeDrawable(
                new ::osg::Sphere(::osg::Vec3d(px, py, pz), 3.0));
            sphere->setColor(::osg::Vec4(1.0f, 0.0f, 0.0f, 0.85f));
            auto *geode = new ::osg::Geode();
            geode->addDrawable(sphere);
            geode->getOrCreateStateSet()->setMode(GL_LIGHTING, ::osg::StateAttribute::OFF);
            group->addChild(geode);
        }

        // Thin red connecting line between spheres
        if (claimedTrailPoints.size() >= 2) {
            auto *lineGeom = new ::osg::Geometry();
            auto *verts = new ::osg::Vec3Array();
            for (const auto& [px, py, pz] : claimedTrailPoints)
                verts->push_back(::osg::Vec3d(px, py, pz));
            lineGeom->setVertexArray(verts);
            lineGeom->addPrimitiveSet(
                new ::osg::DrawArrays(::osg::PrimitiveSet::LINE_STRIP, 0, verts->size()));

            auto *lineColors = new ::osg::Vec4Array();
            lineColors->push_back(::osg::Vec4(1.0f, 0.15f, 0.15f, 0.7f));
            lineGeom->setColorArray(lineColors, ::osg::Array::BIND_OVERALL);

            auto *lineState = lineGeom->getOrCreateStateSet();
            lineState->setAttributeAndModes(
                new ::osg::LineWidth(2.0f), ::osg::StateAttribute::ON);
            lineState->setMode(GL_LIGHTING, ::osg::StateAttribute::OFF);

            auto *lineGeode = new ::osg::Geode();
            lineGeode->addDrawable(lineGeom);
            group->addChild(lineGeode);
        }

        scene->addChild(group);
        claimedTrailGeode = static_cast<void*>(group);
#endif
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

    // Visualization: ellipsoid + claimed_pos for OSG rendering
    if (d.contains("visualization") && !d["visualization"].is_none()) {
        py::dict viz = d["visualization"].cast<py::dict>();

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
                gcs->addClaimedTrailPoint(
                    pos[0].cast<double>(),
                    pos[1].cast<double>(),
                    pos[2].cast<double>());
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
    }
    data["ground_truth_positions"] = groundTruth;

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
