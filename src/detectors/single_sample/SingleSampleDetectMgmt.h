//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef _STATIC_LOCATION_SPOOFER_H
#define _STATIC_LOCATION_SPOOFER_H

#include "rid_beacon/RidBeaconMgmt.h"

using namespace inet;
using namespace inet::ieee80211;

class SingleSampleDetectMgmt : public RidBeaconMgmt
{
protected:

    virtual void hookRidMsg(Packet *packet, const Ptr<const RidBeaconFrame>& beaconBody, double rssiDbm) override;

    virtual void runDetectionAlgo();

};

#endif
