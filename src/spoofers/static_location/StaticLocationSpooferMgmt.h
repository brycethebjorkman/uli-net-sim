//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef _STATIC_LOCATION_SPOOFER_H
#define _STATIC_LOCATION_SPOOFER_H

#include "rid_beacon/RidBeaconMgmt.h"

using namespace inet;
using namespace inet::ieee80211;

class StaticLocationSpooferMgmt : public RidBeaconMgmt
{
protected:
    /** parameters for spoofed position **/
    double spoofPosX;
    double spoofPosY;
    double spoofPosZ;

    /** Utility function: fills in Remote ID message fields */
    virtual void fillRidMsg(const inet::Ptr<RidBeaconFrame> & body) override;
};

#endif
