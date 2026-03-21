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

#include <cmath>
#include <sstream>

using namespace inet;
using namespace physicallayer;

Define_Module(GcsModule);

GcsModule::~GcsModule()
{
    cancelAndDelete(tickTimer);
    for (auto& [name, vec] : logVectors)
        delete vec;
}

// ── Shared result handler (log + commands) ──────────────────────────────────

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
