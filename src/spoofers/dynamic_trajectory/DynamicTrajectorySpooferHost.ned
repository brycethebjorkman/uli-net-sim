//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.spoofers.dynamic_trajectory;

import uav_rid.rid_host.DroneHost;

//
// A drone host that impersonates another drone's location in its Remote ID broadcasts.
// The spoofer flies its own trajectory but broadcasts RID messages with position and
// velocity copied from the target drone specified by targetHostIndex parameter.
//
module DynamicTrajectorySpooferHost extends DroneHost
{
    parameters:
        wlan[0].mgmt.typename = "DynamicTrajectorySpooferMgmt";
}
