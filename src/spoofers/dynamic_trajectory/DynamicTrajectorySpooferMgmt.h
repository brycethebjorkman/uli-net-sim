//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

#ifndef _DYNAMIC_TRAJECTORY_SPOOFER_MGMT_H
#define _DYNAMIC_TRAJECTORY_SPOOFER_MGMT_H

#include "rid_beacon/RidBeaconMgmt.h"
#include "inet/mobility/contract/IMobility.h"

using namespace inet;
using namespace inet::ieee80211;

/**
 * Spoofer that impersonates another drone by copying its position and velocity
 * into the Remote ID broadcast messages.
 *
 * The spoofer flies its own trajectory but broadcasts RID data claiming to be
 * at the target drone's (ghost's) position. This enables testing detection
 * methods against sophisticated spoofing attacks.
 */
class DynamicTrajectorySpooferMgmt : public RidBeaconMgmt
{
protected:
    /** Index of the target host whose position to copy (host[targetHostIndex]) */
    int targetHostIndex;

    /** Cached pointer to target host's mobility module (resolved at init) */
    IMobility *targetMobility = nullptr;

    virtual int numInitStages() const override { return NUM_INIT_STAGES; }
    virtual void initialize(int stage) override;

    /** Utility function: fills Remote ID fields with target drone's position */
    virtual void fillRidMsg(const inet::Ptr<RidBeaconFrame> & body) override;
};

#endif
