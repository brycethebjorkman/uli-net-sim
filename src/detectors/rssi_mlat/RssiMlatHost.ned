//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.detectors.rssi_mlat;

import uav_rid.rid_host.DroneHost;

import uav_rid.detectors.rssi_mlat.RssiMlatMgmt;

module RssiMlatHost extends DroneHost
{
    parameters:
        wlan[0].mgmt.typename = "RssiMlatMgmt";
}
