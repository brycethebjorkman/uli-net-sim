//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

import inet.linklayer.ieee80211.mgmt.Ieee80211MgmtFrame;

namespace inet::ieee80211;

//
// Custom Beacon frame with additional fields
//
class RidBeaconFrame extends Ieee80211BeaconFrame
{
    int serialNumber;
    int64_t timestamp;
    bool emergencyStatus;
    double posX;
    double posY;
    double posZ;
    // speeds in meters per second
    double speedVertical;
    double speedHorizontal;
    // degrees clockwise from true north
    double heading;
}