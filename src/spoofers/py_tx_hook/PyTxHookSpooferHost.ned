//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.spoofers.py_tx_hook;

import uav_rid.rid_host.DroneHost;
import uav_rid.spoofers.py_tx_hook.PyTxHookSpooferMgmt;

//
// A drone host that uses a Python TX hook to modify its RID beacon fields.
// Flies its own trajectory normally but broadcasts spoofed position/velocity
// as determined by the configured pyTxClass.
//
module PyTxHookSpooferHost extends DroneHost
{
    parameters:
        wlan[0].mgmt.typename = "PyTxHookSpooferMgmt";
}
