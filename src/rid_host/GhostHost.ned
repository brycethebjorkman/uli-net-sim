//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.rid_host;

import inet.node.base.NodeBase;
import inet.mobility.contract.IMobility;

//
// A "ghost" drone that flies a trajectory but does not transmit or receive
// any Remote ID messages. This represents a physical drone presence without
// RF emissions. Unlike DroneHost, this module has no wireless interface at all.
//
// This is useful for having the simulator update a TurtleMobility trajectory
// to be referenced by other modules such as spoofers.
//
module GhostHost extends NodeBase
{
    parameters:
        @display("i=misc/drone");
        @networkNode();
        mobility.typename = default("TurtleMobility");
        osgModel = "3d/drone.ive.25.scale.0,0,90.rot";
}
