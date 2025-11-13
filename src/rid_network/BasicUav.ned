//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.rid_network;

import inet.environment.common.PhysicalEnvironment;
import inet.node.contract.INetworkNode;
import inet.physicallayer.wireless.ieee80211.packetlevel.Ieee80211DimensionalRadioMedium;
import inet.visualizer.common.IntegratedVisualizer;

import uav_rid.rid_host.DroneHost;

network BasicUav
{
    parameters:
        int numHosts;
        @display("bgb=1000,1000");
        bool hasVisualizer = default(true);
    submodules:
        visualizer: IntegratedVisualizer if hasVisualizer {
            @display("p=100,50");
        }
        host[numHosts]: <default("DroneHost")> like INetworkNode {
            @display("i=misc/node_vs;p=217,472");
        }
        physicalEnvironment: PhysicalEnvironment {
            @display("p=458,713");
        }
        radioMedium: Ieee80211DimensionalRadioMedium {
            @display("p=624,470");
        }
        Control: Drone;
        Spoof: Drone;
        
}
