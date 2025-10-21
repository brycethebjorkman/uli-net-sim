//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#include "SingleSampleDetectMgmt.h"

#include "inet/linklayer/common/MacAddressTag_m.h"
#include "inet/linklayer/ieee80211/mac/Ieee80211SubtypeTag_m.h"
#include "inet/physicallayer/wireless/common/contract/packetlevel/SignalTag_m.h"
#include "inet/physicallayer/wireless/ieee80211/packetlevel/Ieee80211Radio.h"

using namespace physicallayer;

Define_Module(SingleSampleDetectMgmt);



void SingleSampleDetectMgmt::handleBeaconFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header)
{
    DetectionSample sample;
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
        sample.power = powerDbm;

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
        recvec.txPosX.record(beaconBody->getPosX());
        recvec.txPosY.record(beaconBody->getPosY());
        recvec.txPosZ.record(beaconBody->getPosZ());
        recvec.txSpeedVertical.record(beaconBody->getSpeedVertical());
        recvec.txSpeedHorizontal.record(beaconBody->getSpeedHorizontal());
        recvec.txHeading.record(beaconBody->getHeading());

        // should be tx, because we are recieving from the transmitter
        sample.timestamp = beaconBody->getTimestamp();
        sample.serialNumber = beaconBody->getSerialNumber();
        sample.txPosX = beaconBody->getPosX();
        sample.txPosY = beaconBody->getPosY();
        sample.txPosZ = beaconBody->getPosZ();
        sample.txSpeedVertical = beaconBody->getSpeedVertical();
        sample.txSpeedHorizontal = beaconBody->getSpeedHorizontal();
        sample.txHeading = beaconBody->getHeading();

        // get curr positions
        auto host = getContainingNode(this);
        auto mobility = check_and_cast<IMobility*>(host->getSubmodule("mobility"));
        Coord rxPos = mobility->getCurrentPosition();
        sample.rxPosX = rxPos.x;
        sample.rxPosY = rxPos.y;
        sample.rxPosZ = rxPos.z;

        detectVector.push_back(sample);
        runDetectionAlgo();
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

void SingleSampleDetectMgmt::runDetectionAlgo()
{
    // compute expected power using free space path loss model

    const double pathLossExp = 2.0; // free-space path loss exponent, ~2.0 for no obstructions
    const double threshold = 10;
    const double fMHz = 2400.0; // *.host[*].wlan[*].radio.channelNumber = 6, this means 2.4 GHz wifi

    //assume the first sample has the correct txPower
    // const double txPowerDbm = 13.0;

    if (detectVector.empty()) return;

    const DetectionSample& refSample = detectVector.front();

    double dx_ref = refSample.txPosX - refSample.rxPosX;
    double dy_ref = refSample.txPosY - refSample.rxPosY;
    double dz_ref = refSample.txPosZ - refSample.rxPosZ;
    double dist_ref = sqrt(dx_ref * dx_ref + dy_ref * dy_ref + dz_ref * dz_ref);

    double txPowerDbm = refSample.power +
        (32.44 + 10 * pathLossExp * (log10(dist_ref / 1000.0) + log10(fMHz)));

    const DetectionSample& sample = detectVector.back();

    // compute distance
    double dx = sample.txPosX - sample.rxPosX;
    double dy = sample.txPosY - sample.rxPosY;
    double dz = sample.txPosZ - sample.rxPosZ;
    double distance = sqrt(dx*dx + dy*dy + dz*dz);

    double expectedPowerDbm = txPowerDbm - (32.44 + 10 * pathLossExp * (log10(distance / 1000.0) + log10(fMHz)));

    EV_INFO << "Potential spoof detected."
                    << "| Distance=" << distance << " m "
                    << "| Measured=" << sample.power << " dBm "
                    << "| Expected=" << expectedPowerDbm << " dBm "
                    << "| Diff=" << fabs(expectedPowerDbm - sample.power) << " dB"
                    << std::endl;

    if (fabs(expectedPowerDbm - sample.power) > threshold) {
        EV_INFO << "Potential spoof detected."
                << "| Distance=" << distance << " m "
                << "| Measured=" << sample.power << " dBm "
                << "| Expected=" << expectedPowerDbm << " dBm "
                << "| Diff=" << fabs(expectedPowerDbm - sample.power) << " dB"
                << std::endl;
    }

}
