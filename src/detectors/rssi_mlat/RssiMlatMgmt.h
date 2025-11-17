//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef _RSSI_MLAT_MGMT_H
#define _RSSI_MLAT_MGMT_H

#include "rid_beacon/RidBeaconMgmt.h"

using namespace inet;
using namespace inet::ieee80211;

class RssiMlatMgmt : public RidBeaconMgmt
{
  protected:
    virtual void hookRidMsg(Packet *packet, const Ptr<const RidBeaconFrame>& beaconBody, double rssiDbm) override;
};

#endif
