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


void SingleSampleDetectMgmt::hookRidMsg(Packet *packet, const Ptr<const RidBeaconFrame>& beaconBody, double rssiDbm)
{
    runDetectionAlgo();
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
