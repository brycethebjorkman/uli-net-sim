//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.spoofers.dynamic_trajectory;

import uav_rid.rid_beacon.RidBeaconMgmt;

//
// Management module for a drone that impersonates another drone's location.
// The spoofer flies its own trajectory but broadcasts RID messages copying
// the position and velocity of a target drone specified by targetHostIndex.
//
simple DynamicTrajectorySpooferMgmt extends RidBeaconMgmt
{
    parameters:
        @class(DynamicTrajectorySpooferMgmt);

        // Index of the host whose position to copy (e.g., 4 means host[4])
        int targetHostIndex;
}
