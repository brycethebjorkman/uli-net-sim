//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.spoofers.py_tx_hook;

import uav_rid.rid_beacon.RidBeaconMgmt;

//
// Beacon management with a Python TX hook for position spoofing.
// Overrides fillRidMsg() to first populate the beacon with the host's
// true position (via the base class), then call a Python class that
// can overwrite beacon fields (e.g. SnowPlowSpoofer, PositionOffsetSpoofer).
//
simple PyTxHookSpooferMgmt extends RidBeaconMgmt
{
    parameters:
        @class(PyTxHookSpooferMgmt);

        // Python class implementing on_rid_tx(state) -> dict or None.
        string pyTxClass;

        // Path to PyBridge module
        string pyBridgePath = default("^.^.^.pyBridge");
}
