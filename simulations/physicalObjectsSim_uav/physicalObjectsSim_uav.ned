//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU Lesser General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU Lesser General Public License for more details.
//
// You should have received a copy of the GNU Lesser General Public License
// along with this program.  If not, see http://www.gnu.org/licenses/.
//

package uav_rid.simulations.physicalObjectsSim_uav;

import inet.environment.common.PhysicalEnvironment;
import inet.physicallayer.wireless.ieee80211.packetlevel.Ieee80211DimensionalRadioMedium;
import inet.visualizer.common.IntegratedVisualizer;

import uav_rid.rid_host.DroneHost;

network objectsUAV
{
    parameters:
        int numHosts;   // number of UAVs
        @display("bgb=400,400");
    submodules:
        visualizer: IntegratedVisualizer {
            @display("p=100,100");
        }
        host[numHosts]: DroneHost {
            @display("i=misc/node_vs;p=200,200");
        }
        physicalEnvironment: PhysicalEnvironment {
            @display("p=300,300");
        }
        radioMedium: Ieee80211DimensionalRadioMedium {
            @display("p=350,350");
        }
}

