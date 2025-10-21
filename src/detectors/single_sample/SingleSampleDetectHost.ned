//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.detectors.single_sample;

import uav_rid.rid_host.DroneHost;

import uav_rid.detectors.single_sample.SingleSampleDetectMgmt;

module SingleSampleDetectHost extends DroneHost
{
    parameters:
        wlan[0].mgmt.typename = "SingleSampleDetectMgmt";
}
