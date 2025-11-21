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
        wlan[0].radio.antenna.typename = "DipoleAntenna";
        wlan[0].radio.antenna.length = 0.059m;
        wlan[0].radio.channelNumber = 6;
        
		// Typical transmitter conducted power ranges (in dBm):
		//	0 to  5 (min)
		//  5 to 10 (low; 10 typical for Bluetooth, 13 typical for Wi-Fi clients)
		// 10 to 20 (mid; 20 typical for Wi-Fi access points)
		// 20 to 30 (max; FCC limit on EIRP is 36 which means conducted power of 30 for typical antenna gain)
        wlan[0].radio.transmitter.power = default(13dBm);
        
        osgModel = "3d/drone.ive.25.scale.0,0,90.rot";
}
