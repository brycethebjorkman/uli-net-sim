//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.visualizer;

import inet.visualizer.canvas.mobility.MobilityCanvasVisualizer;

simple SpooferAwareMobilityCanvasVisualizer extends MobilityCanvasVisualizer
{
    // C++ lives in namespace uav_rid (not uav_rid::visualizer); spell full @class for linker.
    @class(uav_rid::SpooferAwareMobilityCanvasVisualizer);
}
