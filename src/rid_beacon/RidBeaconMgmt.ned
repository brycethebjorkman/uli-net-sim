//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.rid_beacon;

import inet.linklayer.ieee80211.mgmt.IIeee80211Mgmt;

simple RidBeaconMgmt like IIeee80211Mgmt
{
    parameters:
        string ssid = default("SSID");
        double beaconInterval @unit(s) = default(100ms);
        
        // use host index by default
        int serialNumber = default(ancestorIndex(2));

		// like Ieee80211MgmtAp for Ieee80211Interface compatibility
        string mibModule;
        string interfaceTableModule;
        string radioModule = default("^.radio");

        // IIeee80211Mgmt
        @display("i=block/cogwheel");
        string macModule;
    gates:
        // IIeee80211Mgmt
        input macIn @labels(Ieee80211MacHeader);
        output macOut @labels(Ieee80211MacHeader);
        input agentIn @loose;
        output agentOut @loose;
}

