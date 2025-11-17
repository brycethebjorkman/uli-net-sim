//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#include "RssiMlatMgmt.h"
#include "RssiMlatReport_m.h"

#include "inet/linklayer/common/MacAddressTag_m.h"
#include "inet/linklayer/ieee80211/mac/Ieee80211SubtypeTag_m.h"
#include "inet/physicallayer/wireless/common/contract/packetlevel/SignalTag_m.h"
#include "inet/physicallayer/wireless/ieee80211/packetlevel/Ieee80211Radio.h"

#include "utils/py_call.h"

using namespace physicallayer;

Define_Module(RssiMlatMgmt);

void RssiMlatMgmt::hookRidMsg(Packet *packet, const Ptr<const RidBeaconFrame>& beaconBody, double rssiDbm)
{
    // Find the GCS module
    cModule *network = getSimulation()->getSystemModule();
    cModule *gcs = network->getSubmodule("gcs");

    if (!gcs) {
        EV_WARN << "GCS module not found in network" << endl;
        return;
    }

    // Create the report message
    RssiMlatReport *report = new RssiMlatReport("RssiMlatReport");

    // Get receiver host ID
    cModule *host = getContainingNode(this);
    report->setReceiverHostId(host->getIndex());

    // Get receiver position
    auto mobility = check_and_cast<IMobility*>(host->getSubmodule("mobility"));
    auto rxPos = mobility->getCurrentPosition();
    report->setRxPosX(rxPos.getX());
    report->setRxPosY(rxPos.getY());
    report->setRxPosZ(rxPos.getZ());

    // Get beacon data
    report->setSenderSerialNumber(beaconBody->getSerialNumber());
    report->setTimestamp(beaconBody->getTimestamp());
    report->setTxPosX(beaconBody->getPosX());
    report->setTxPosY(beaconBody->getPosY());
    report->setTxPosZ(beaconBody->getPosZ());

    // Use the passed RSSI value
    report->setRssi(rssiDbm);

    // Send to GCS
    sendDirect(report, gcs, "directIn");
}

