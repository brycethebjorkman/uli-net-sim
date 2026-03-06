//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

//
// Command message sent from GcsModule to UAV mobility modules.
// Contains a JSON-encoded command string produced by Python.
//
class GcsCommand extends cMessage
{
    int targetHostId;         // Index of the target host
    string commandJson;       // JSON string from Python (parsed by mobility module)
}
