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

        // upper bound on random delay for first transmission
        double startupJitter @unit(s) = default(beaconInterval);

        // fixed offset added to first transmission time (after jitter)
        double beaconOffset @unit(s) = default(0s);

        // if false this instance should not transmit at all
        bool transmitBeacon = default(true);
        
        // if true this instance terminates simulation after one transmission
        bool oneOff = default(false);

        // Python TX hook class (empty = no hook). Called after fillRidMsg()
        // to optionally modify beacon fields (e.g. Python-based spoofing).
        string pyTxClass = default("");

        // Path to PyBridge module (used by pyTxClass)
        string pyBridgePath = default("^.^.^.pyBridge");

        // Path to GCS module for RX report forwarding (empty = no forwarding)
        string gcsModulePath = default("");

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

