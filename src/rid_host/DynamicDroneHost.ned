//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.rid_host;

//
// DroneHost variant that defaults to MultirotorMobility for physics-based
// 6-DoF flight with optional Python control.
//
// Use this host type when you want dynamic trajectory control rather than
// pre-generated TurtleMobility waypoints.
//
module DynamicDroneHost extends DroneHost
{
    parameters:
        mobility.typename = default("MultirotorMobility");
}
