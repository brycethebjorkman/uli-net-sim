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
        host[numHosts]: <default("DroneHost")> like INetworkNode {
            @display("i=misc/node_vs;p=217,472");
        }
        physicalEnvironment: PhysicalEnvironment {
            @display("p=458,713");
        }
        radioMedium: Ieee80211DimensionalRadioMedium {
            @display("p=624,470");
            backgroundNoise.power = default(-100dBm);
        }
        visualizer: IntegratedVisualizer if hasVisualizer {
            @display("p=100,50");

			// Note: defaults set here may be spuriously flagged with "no such parameter" by the IDE

            // Scene visualization defaults
            osgVisualizer.sceneVisualizer.axisLength = default(4000m);
            osgVisualizer.sceneVisualizer.clearColor = default("skyblue");
            osgVisualizer.sceneVisualizer.sceneMinZ = default(0m);

            // Medium visualization defaults
            osgVisualizer.mediumVisualizer.displaySignals = default(true);
            osgVisualizer.mediumVisualizer.signalColor = default("red");
            osgVisualizer.mediumVisualizer.signalFadingDistance = default(50m);
            osgVisualizer.mediumVisualizer.signalRingSize = default(50m);
            osgVisualizer.mediumVisualizer.signalShape = default("ring");

            // Mobility visualization defaults
            osgVisualizer.mobilityVisualizer.displayMobility = default(true);
            osgVisualizer.mobilityVisualizer.displayMovementTrails = default(true);
            osgVisualizer.mobilityVisualizer.displayOrientations = default(true);
            osgVisualizer.mobilityVisualizer.displayPositions = default(true);
            osgVisualizer.mobilityVisualizer.displayVelocities = default(true);

            // Network Node visualization defaults
            osgVisualizer.networkNodeVisualizer.displayModuleName = default(false);
        }
}
