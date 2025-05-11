//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// Based on inet/linklayer/ieee80211/mgmt/Ieee80211MgmtAp.cc
//

#include "RidBeaconMgmt.h"

#include "inet/linklayer/common/MacAddressTag_m.h"
#include "inet/linklayer/ieee80211/mac/Ieee80211SubtypeTag_m.h"
#include "inet/physicallayer/wireless/ieee80211/packetlevel/Ieee80211Radio.h"

using namespace physicallayer;

Define_Module(RidBeaconMgmt);

RidBeaconMgmt::~RidBeaconMgmt()
{
    cancelAndDelete(beaconTimer);
}

void RidBeaconMgmt::initialize(int stage)
{
    Ieee80211MgmtApBase::initialize(stage);

    if (stage == INITSTAGE_LOCAL) {
        // read params and init vars
        ssid = par("ssid").stdstringValue();
        beaconInterval = par("beaconInterval");
        channelNumber = -1; // value will arrive from physical layer in receiveChangeNotification()
        WATCH(ssid);
        WATCH(channelNumber);
        WATCH(beaconInterval);

        // subscribe for notifications
        cModule *radioModule = getModuleFromPar<cModule>(par("radioModule"), this);
        radioModule->subscribe(Ieee80211Radio::radioChannelChangedSignal, this);

        // start beacon timer (randomize startup time)
        beaconTimer = new cMessage("beaconTimer");
    }
}

void RidBeaconMgmt::handleTimer(cMessage *msg)
{
    if (msg == beaconTimer) {
        sendBeacon();
        scheduleAfter(beaconInterval, beaconTimer);
    }
    else {
        throw cRuntimeError("internal error: unrecognized timer '%s'", msg->getName());
    }
}

void RidBeaconMgmt::receiveSignal(cComponent *source, simsignal_t signalID, intval_t value, cObject *details)
{
    Enter_Method("%s", cComponent::getSignalName(signalID));

    if (signalID == Ieee80211Radio::radioChannelChangedSignal) {
        EV << "updating channel number\n";
        channelNumber = value;
    }
}

void RidBeaconMgmt::sendManagementFrame(const char *name, const Ptr<Ieee80211MgmtFrame>& body, int subtype, const MacAddress& destAddr)
{
    auto packet = new Packet(name);
    packet->addTag<MacAddressReq>()->setDestAddress(destAddr);
    packet->addTag<Ieee80211SubtypeReq>()->setSubtype(subtype);
    packet->insertAtBack(body);
    sendDown(packet);
}

void RidBeaconMgmt::sendBeacon()
{
    EV << "Sending beacon\n";
    const auto& body = makeShared<Ieee80211BeaconFrame>();
    body->setSSID(ssid.c_str());
    body->setSupportedRates(supportedRates);
    body->setBeaconInterval(beaconInterval);
    body->setChannelNumber(channelNumber);
    body->setChunkLength(B(8 + 2 + 2 + (2 + ssid.length()) + (2 + supportedRates.numRates)));
    sendManagementFrame("Beacon", body, ST_BEACON, MacAddress::BROADCAST_ADDRESS);
}

void RidBeaconMgmt::handleBeaconFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header)
{
    dropManagementFrame(packet);
}

void RidBeaconMgmt::start()
{
    Ieee80211MgmtApBase::start();
    scheduleAfter(uniform(0, beaconInterval), beaconTimer);
}

void RidBeaconMgmt::stop()
{
    cancelEvent(beaconTimer);
    Ieee80211MgmtApBase::stop();
}
