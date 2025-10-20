//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.spoofers.static_location;

import uav_rid.rid_host.DroneHost;

import uav_rid.spoofers.static_location.StaticLocationSpooferMgmt;

module StaticLocationSpooferHost extends DroneHost
{
    parameters:
        wlan[0].mgmt.typename = "StaticLocationSpooferMgmt";
}
