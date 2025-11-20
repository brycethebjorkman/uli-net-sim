//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#include "RssiMlatGcs.h"

#include "RssiMlatReport_m.h"
#include "inet/physicallayer/wireless/common/contract/packetlevel/IRadioMedium.h"

#include "utils/py_call.h"

#include <sstream>

using namespace inet;
using namespace physicallayer;

Define_Module(RssiMlatGcs);

const std::string mlat_script_path = utils::proj_dir + "/src/rssi_mlat.py";

void RssiMlatGcs::initialize()
{
    // Get the radio medium module and subscribe to signal removal
    radioMedium = getSimulation()->getModuleByPath("radioMedium");
    if (!radioMedium) {
        throw cRuntimeError("radioMedium not found");
    }
    radioMedium->subscribe(IRadioMedium::signalRemovedSignal, this);
}

void RssiMlatGcs::handleMessage(cMessage *msg)
{
    RssiMlatReport *report = dynamic_cast<RssiMlatReport*>(msg);
    if (report) {
        EV << "GCS received report from host " << report->getReceiverHostId()
           << " about beacon from serial " << report->getSenderSerialNumber()
           << " with RSSI " << report->getRssi() << " dBm" << std::endl;

        // Store the report grouped by (senderSerialNumber, timestamp)
        auto key = std::make_pair(report->getSenderSerialNumber(), report->getTimestamp());
        reportsByBeacon[key].push_back(report);

        EV << "Stored report. Total reports for this beacon: " << reportsByBeacon[key].size() << std::endl;
    } else {
        EV_WARN << "GCS received unknown message type" << std::endl;
        delete msg;
    }
}

void RssiMlatGcs::receiveSignal(cComponent *source, simsignal_t signalID, cObject *obj, cObject *details)
{
    if (signalID == IRadioMedium::signalRemovedSignal) {
        Enter_Method_Silent();

        EV << "Signal removed from radio medium. Processing multilateration for all beacons..." << std::endl;

        // Process all collected reports
        for (auto& entry : reportsByBeacon) {
            const auto& reports = entry.second;
            if (reports.size() >= 3) {
                EV << "Running multilateration for beacon (serial=" << entry.first.first
                   << ", timestamp=" << entry.first.second
                   << ") with " << reports.size() << " reports" << std::endl;
                runMultilateration(reports);
            } else {
                EV_WARN << "Not enough reports (" << reports.size()
                        << ") for beacon (serial=" << entry.first.first
                        << ", timestamp=" << entry.first.second << ")" << std::endl;
            }

            // Clean up reports
            for (auto* report : reports) {
                delete report;
            }
        }

        // Clear all stored reports
        reportsByBeacon.clear();
    }
}

void RssiMlatGcs::runMultilateration(const std::vector<RssiMlatReport*>& reports)
{
    if (reports.empty()) {
        return;
    }

    // Build JSON data for the Python script
    std::ostringstream json;
    json << "{ \"x\": [";

    for (size_t i = 0; i < reports.size(); ++i) {
        if (i > 0) json << ", ";
        json << "[" << reports[i]->getRxPosX() << ", "
             << reports[i]->getRxPosY() << ", "
             << reports[i]->getRxPosZ() << "]";
    }

    json << "], \"r\": [";

    for (size_t i = 0; i < reports.size(); ++i) {
        if (i > 0) json << ", ";
        json << reports[i]->getRssi();
    }

    json << "] }";

    // Call the Python script
    std::string cmd = mlat_script_path + " '" + json.str() + "'";
    EV << "Calling multilateration script with: " << json.str() << std::endl;

    std::string result = utils::py_call(cmd);

    EV << "Multilateration result: " << result << std::endl;

    // Print actual transmitter position from first report for comparison
    EV << "Transmitted position: ("
       << reports[0]->getTxPosX() << ", "
       << reports[0]->getTxPosY() << ", "
       << reports[0]->getTxPosZ() << ")" << std::endl;
}
