//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.rid_network;

import inet.environment.common.PhysicalEnvironment;
import inet.node.contract.INetworkNode;
import inet.physicallayer.wireless.ieee80211.packetlevel.Ieee80211DimensionalRadioMedium;
import inet.visualizer.common.IntegratedVisualizer;

import uav_rid.visualizer.SpooferAwareMobilityCanvasVisualizer;
import uav_rid.visualizer.SpooferAwareMobilityOsgVisualizer;
import uav_rid.rid_host.DroneHost;
import uav_rid.pybridge.PyBridge;
import uav_rid.gcs.GcsModule;

network BasicUav
{
    parameters:
        int numHosts;
        int numGcs = default(0);
        @display("bgb=1000,1000");
        bool hasVisualizer = default(true);
        // Qtenv draws red sendDirect arrows for WirelessSignal hops on the network canvas;
        // this flag disables those built-in animations at the network root (see PyBridge).
        bool suppressQtenvWirelessAnimations = default(true);
    submodules:
        pyBridge: PyBridge {
            @display("p=850,50");
        }
        gcs[numGcs]: GcsModule {
            @display("p=850,150");
        }
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

            // Medium visualization defaults (canvas + OSG; keep off for legible 2D runs)
            canvasVisualizer.mediumVisualizer.displaySignals = default(false);
            canvasVisualizer.mediumVisualizer.displaySignalDepartures = default(false);
            canvasVisualizer.mediumVisualizer.displaySignalArrivals = default(false);
            osgVisualizer.mediumVisualizer.displaySignals = default(false);
            osgVisualizer.mediumVisualizer.displaySignalDepartures = default(false);
            osgVisualizer.mediumVisualizer.displaySignalArrivals = default(false);
            osgVisualizer.mediumVisualizer.signalColor = default("red");
            osgVisualizer.mediumVisualizer.signalFadingDistance = default(50m);
            osgVisualizer.mediumVisualizer.signalRingSize = default(50m);
            osgVisualizer.mediumVisualizer.signalShape = default("ring");

            // Mobility visualization (SpooferAware*: last host = red trail only; see SpooferTrailColor.h)
            osgVisualizer.mobilityVisualizer.typename = default("SpooferAwareMobilityOsgVisualizer");
            canvasVisualizer.mobilityVisualizer.typename = default("SpooferAwareMobilityCanvasVisualizer");
            osgVisualizer.mobilityVisualizer.displayMobility = default(true);
            osgVisualizer.mobilityVisualizer.displayMovementTrails = default(true);
            osgVisualizer.mobilityVisualizer.displayOrientations = default(true);
            osgVisualizer.mobilityVisualizer.displayPositions = default(true);
            osgVisualizer.mobilityVisualizer.displayVelocities = default(true);
            osgVisualizer.mobilityVisualizer.trailLength = default(1000);
            // Benign palette: no red hues — spoofer color is forced in C++ (SpooferAware* visualizers).
            // If you change this list, update kInetTrailPalette[] and kHostGoalDotPalette[] (GcsModule.cc).
            osgVisualizer.mobilityVisualizer.movementTrailLineWidth = default(2);
            osgVisualizer.mobilityVisualizer.movementTrailLineColor = default("#1f77b4 #aec7e8 #ff7f0e #ffbb78 #2ca02c #98df8a #9467bd #c5b0d5 #404040 #bdbdbd #e377c2 #f7b6d2 #7f7f7f #c7c7c7 #bcbd22 #dbdb8d #17becf #9edae5 #393b79 #5254a3 #637939 #8ca252 #3182bd #6baed6 #31a354 #756bb1");
            canvasVisualizer.mobilityVisualizer.movementTrailLineWidth = default(2);
            canvasVisualizer.mobilityVisualizer.movementTrailLineColor = default("#1f77b4 #aec7e8 #ff7f0e #ffbb78 #2ca02c #98df8a #9467bd #c5b0d5 #404040 #bdbdbd #e377c2 #f7b6d2 #7f7f7f #c7c7c7 #bcbd22 #dbdb8d #17becf #9edae5 #393b79 #5254a3 #637939 #8ca252 #3182bd #6baed6 #31a354 #756bb1");

            // Network Node visualization defaults
            osgVisualizer.networkNodeVisualizer.displayModuleName = default(false);

            // Radio state icons (red TX/RX badges cycling on hosts) — off for clean 2D runs
            canvasVisualizer.radioVisualizer.displayTransmissionState = default(false);
            canvasVisualizer.radioVisualizer.displayReceptionState = default(false);
            osgVisualizer.radioVisualizer.displayTransmissionState = default(false);
            osgVisualizer.radioVisualizer.displayReceptionState = default(false);
        }
}
