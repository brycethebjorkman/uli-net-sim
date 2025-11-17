//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.simulations.localization;

import uav_rid.rid_network.BasicUav;
import uav_rid.detectors.rssi_mlat.RssiMlatGcs;

network RssiMlat extends BasicUav
{
    submodules:
        gcs: RssiMlatGcs;
}

