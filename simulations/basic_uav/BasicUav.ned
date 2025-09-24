//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.simulations.basic_uav;

import inet.environment.common.PhysicalEnvironment;
import inet.physicallayer.wireless.ieee80211.packetlevel.Ieee80211DimensionalRadioMedium;
import inet.visualizer.common.IntegratedVisualizer;

import uav_rid.rid_host.DroneHost;

network BasicUav
{
    parameters:
        int numHosts;
        @display("bgb=1000,1000");
    submodules:
        visualizer: IntegratedVisualizer {
            @display("p=100,50");
        }
        host[numHosts]: DroneHost {
            @display("i=misc/node_vs;p=217,472");
        }
        physicalEnvironment: PhysicalEnvironment {
            @display("p=458,713");
        }
        radioMedium: Ieee80211DimensionalRadioMedium {
            @display("p=624,470");
        }
}
