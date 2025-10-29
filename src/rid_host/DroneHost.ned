//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.rid_host;

import inet.node.inet.WirelessHost;

import uav_rid.rid_beacon.RidBeaconMgmt;

// WirelessHost extends LinkLayerNodeBase which has
// wlan vector of default type Ieee80211Interface (inet/linklayer/ieee80211/Ieee80211Interface.ned)
// which has Ieee80211MgmtSta (inet/linklayer/ieee80211/mgmt/Ieee80211MgmtSta)
// and Ieee80211AgentSta (inet/linklayer/ieee80211/mgmt/Ieee80211AgentSta)
// by default

module DroneHost extends WirelessHost
{
    parameters:
        @display("bgb=1806,1526");
        wlan[0].agent.typename = "";
        wlan[0].mgmt.typename = default("RidBeaconMgmt");
        wlan[0].radio.typename = "Ieee80211DimensionalRadio";
        wlan[0].radio.channelNumber = 6;
        wlan[0].radio.transmitter.power = default(13dBm);
}
