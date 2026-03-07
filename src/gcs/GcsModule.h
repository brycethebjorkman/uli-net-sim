//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef __GCS_MODULE_H
#define __GCS_MODULE_H

#include <omnetpp.h>
#include <map>
#include <set>
#include <vector>
#include <string>

using namespace omnetpp;

class PyBridge;
class GcsReport;

//
// Ground Control Station: aggregates per-transmission RX reports,
// calls a Python decision algorithm, optionally sends control commands.
//
class GcsModule : public cSimpleModule, public cListener
{
  public:
    virtual ~GcsModule();

    // Record log entries as cOutVector
    void emitLogEntries(const std::map<std::string, double>& entries);

    // Forward a control command to a UAV's mobility module
    void sendCommand(int hostId, const std::string& commandJson);

  protected:
    // Federate host indices this GCS manages (empty = all)
    std::set<int> federateSet;
    bool allFederates = true;

    // Report aggregation: key = (serialNumber, ridTimestamp)
    using BeaconKey = std::pair<int, int64_t>;
    std::map<BeaconKey, std::vector<GcsReport*>> reportsByBeacon;

    // Radio medium for signal subscription
    cModule *radioMedium = nullptr;

    // Python bridge
    PyBridge *pyBridge = nullptr;
    int pyHandle = -1;
    bool sendControlCommands = false;

    // Periodic tick timer
    cMessage *tickTimer = nullptr;
    double tickInterval = 0;   // 0 = disabled
    int tickCount = 0;

    // Dynamic vector registry: Python "log" keys → cOutVector (always recorded)
    std::map<std::string, cOutVector*> logVectors;

    virtual void initialize() override;
    virtual void handleMessage(cMessage *msg) override;

    // IRadioMedium::signalRemovedSignal handler
    virtual void receiveSignal(cComponent *source, simsignal_t signalID,
                               cObject *obj, cObject *details) override;

    // Process one transmission's worth of collected reports
    void processTransmission(const BeaconKey& key,
                             const std::vector<GcsReport*>& reports);

    // Call Python on_reports() with transmission data
    void pyOnReport(const BeaconKey& key,
                    const std::vector<GcsReport*>& reports);

    // Call Python on_tick() periodically
    void pyOnTick();
};

#endif
