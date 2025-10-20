//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.spoofers.static_location;

import uav_rid.rid_beacon.RidBeaconMgmt;

simple StaticLocationSpooferMgmt extends RidBeaconMgmt
{
    parameters:
        @class(StaticLocationSpooferMgmt);
        
        double spoofPosX;
        double spoofPosY;
        double spoofPosZ;
}

