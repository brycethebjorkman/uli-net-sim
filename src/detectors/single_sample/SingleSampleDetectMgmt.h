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
    virtual void runDetectionAlgo();

    /** Utility function: handles a received beacon frame */
    virtual void handleBeaconFrame(Packet *packet, const Ptr<const Ieee80211MgmtHeader>& header) override;
};

#endif
