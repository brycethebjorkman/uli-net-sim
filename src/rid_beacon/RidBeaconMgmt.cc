//
// SPDX-License-Identifier: LGPL-3.0-or-later
//
// Based on inet/linklayer/ieee80211/mgmt/Ieee80211MgmtAp.cc
//

#include "RidBeaconMgmt.h"

#include "inet/linklayer/common/MacAddressTag_m.h"
#include "inet/linklayer/ieee80211/mac/Ieee80211SubtypeTag_m.h"
#include "inet/physicallayer/wireless/common/contract/packetlevel/SignalTag_m.h"
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
        serialNumber = par("serialNumber");
        beaconInterval = par("beaconInterval");
        channelNumber = -1; // value will arrive from physical layer in receiveChangeNotification()
        WATCH(ssid);
        WATCH(channelNumber);
        WATCH(beaconInterval);

        // set descriptive names for the Analysis Tool
        recvec.power.setName("Reception Power");
        recvec.time.setName("Reception Time");
        recvec.timestamp.setName("Reception Timestamp");
        recvec.packetId.setName("Packet ID");
        recvec.serialNumber.setName("Serial Number");
        recvec.txPosX.setName("Transmission X Coordinate");
        recvec.txPosY.setName("Transmission Y Coordinate");
        recvec.txPosZ.setName("Transmission Z Coordinate");
        recvec.rxPosX.setName("Reception X Coordinate");
        recvec.rxPosY.setName("Reception Y Coordinate");
        recvec.rxPosZ.setName("Reception Z Coordinate");
        recvec.txSpeedVertical.setName("Transmission Vertical Speed");
        recvec.txSpeedHorizontal.setName("Transmission Horizontal Speed");
        recvec.txHeading.setName("Transmission Heading");
        recvec.rxSpeedVertical.setName("Reception Vertical Speed");
        recvec.rxSpeedHorizontal.setName("Reception Horizontal Speed");
        recvec.rxHeading.setName("Reception Heading");
        recvec.rxMyPosX.setName("Reception My X Coordinate");
        recvec.rxMyPosY.setName("Reception My Y Coordinate");
        recvec.rxMyPosZ.setName("Reception My Z Coordinate");

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
    const auto& body = makeShared<RidBeaconFrame>();
    body->setSSID(ssid.c_str());
    body->setSupportedRates(supportedRates);
    body->setBeaconInterval(beaconInterval);
    body->setChannelNumber(channelNumber);
    body->setChunkLength(B(8 + 2 + 2 + (2 + ssid.length()) + (2 + supportedRates.numRates)));

    // use specific implementation logic to fill in Remote ID message fields
    fillRidMsg(body);

    EV << "BODY: " << body << std::endl;
    recvec.txPosX.record(body->getPosX());
    recvec.txPosY.record(body->getPosY());
    recvec.txPosZ.record(body->getPosZ());
    recvec.txSpeedVertical.record(body->getSpeedVertical());
    recvec.txSpeedHorizontal.record(body->getSpeedHorizontal());
    recvec.txHeading.record(body->getHeading());
    sendManagementFrame("Beacon", body, ST_BEACON, MacAddress::BROADCAST_ADDRESS);
}

void RidBeaconMgmt::fillRidMsg(const inet::Ptr<RidBeaconFrame> & body)
{
    auto currentTime = simTime();
    body->setTimestamp(currentTime.inUnit(SimTimeUnit::SIMTIME_MS));
    body->setSerialNumber(serialNumber);
    auto host = getContainingNode(this);
    auto mobility = check_and_cast<IMobility*>(host->getSubmodule("mobility"));
    auto pos = mobility->getCurrentPosition();
    auto velocity = mobility->getCurrentVelocity();
    EV << "VELOCITY: " << velocity << std::endl;
    double posX = pos.getX();
    double posY = pos.getY();
    double posZ = pos.getZ();
    // assume that (X,Y,Z) corresponds to (East,North,Up)
    double speedVertical = velocity.getZ();
    auto horizontal = Coord(velocity.getX(), velocity.getY(), 0.0);
    double speedHorizontal = horizontal.length();
    auto north = Coord(0,1,0);
    double heading = north.angle(horizontal) * (180.00 / M_PI);
    body->setPosX(posX);
    body->setPosY(posY);
    body->setPosZ(posZ);
    body->setSpeedVertical(speedVertical);
    body->setSpeedHorizontal(speedHorizontal);
    body->setHeading(heading);
}

void RidBeaconMgmt::handleBeaconFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header)
{
    msgid_t packetId = packet->getId();
    if (packetId >= 0) {
        recvec.packetId.record(packetId);
    }

    auto signalPowerInd = packet->findTag<SignalPowerInd>();
    if (signalPowerInd != nullptr) {
        /*
         * received power ratings for 802.11 networks:
         *  - Strong: 1e-6  W (-30 dBm)
         *  - Good  : 1e-9  W (-60 dBm)
         *  - Okay  : 1e-10 W (-70 dBm)
         *  - Bad   : 1e-11 W (-80 dBm)
         *  - Weak  : 1e-12 W (-90 dBm)
         */
        W receivedPower = signalPowerInd->getPower();
        // convert to dBm for more readable values
        double powerDbm = 10 * std::log10(receivedPower.get() * 1000);
        recvec.power.record(powerDbm);
    }

    // get reception time
    auto signalTimeInd = packet->findTag<SignalTimeInd>();
    if (signalTimeInd != nullptr) {
        simtime_t receptionStart = signalTimeInd->getStartTime();
        recvec.time.record(receptionStart.dbl());
    }

    auto beaconBody = packet->peekAtFront<RidBeaconFrame>();
    if (beaconBody != nullptr) {
        recvec.timestamp.record(beaconBody->getTimestamp());
        recvec.serialNumber.record(beaconBody->getSerialNumber());
        recvec.rxPosX.record(beaconBody->getPosX());
        recvec.rxPosY.record(beaconBody->getPosY());
        recvec.rxPosZ.record(beaconBody->getPosZ());
        recvec.rxSpeedVertical.record(beaconBody->getSpeedVertical());
        recvec.rxSpeedHorizontal.record(beaconBody->getSpeedHorizontal());
        recvec.rxHeading.record(beaconBody->getHeading());
    } else {
        throw cRuntimeError("Missing RidBeaconFrame header in received Packet");
    }

    auto host = getContainingNode(this);
    auto mobility = check_and_cast<IMobility*>(host->getSubmodule("mobility"));
    auto pos = mobility->getCurrentPosition();
    recvec.rxMyPosX.record(pos.getX());
    recvec.rxMyPosY.record(pos.getY());
    recvec.rxMyPosZ.record(pos.getZ());

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
