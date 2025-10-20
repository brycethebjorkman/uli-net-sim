//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#include "StaticLocationSpooferMgmt.h"

#include "inet/linklayer/common/MacAddressTag_m.h"
#include "inet/linklayer/ieee80211/mac/Ieee80211SubtypeTag_m.h"
#include "inet/physicallayer/wireless/common/contract/packetlevel/SignalTag_m.h"
#include "inet/physicallayer/wireless/ieee80211/packetlevel/Ieee80211Radio.h"

using namespace physicallayer;

Define_Module(StaticLocationSpooferMgmt);

void StaticLocationSpooferMgmt::fillRidMsg(const inet::Ptr<RidBeaconFrame> & body)
{
    body->setPosX(par("spoofPosX"));
    body->setPosY(par("spoofPosY"));
    body->setPosZ(par("spoofPosZ"));
}
