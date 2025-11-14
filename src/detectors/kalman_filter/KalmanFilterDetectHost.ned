//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.detectors.kalman_filter;

import uav_rid.rid_host.DroneHost;

import uav_rid.detectors.kalman_filter.KalmanFilterDetectMgmt;

module KalmanFilterDetectHost extends DroneHost
{
    parameters:
        wlan[0].mgmt.typename = "KalmanFilterDetectMgmt";
}
