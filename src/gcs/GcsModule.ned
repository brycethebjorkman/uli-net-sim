//
// SPDX-License-Identifier: LGPL-3.0-or-later
//

package uav_rid.gcs;

//
// Ground Control Station module.
//
// Aggregates RX reports from assigned federate hosts and calls a Python
// decision algorithm once per transmission (grouped by serial_number +
// rid_timestamp).
//
// Reports arrive via sendDirect() from beacon management modules.
// Processing is triggered by IRadioMedium::signalRemovedSignal, which
// fires after all receivers have processed a transmission.
//
// The Python class's on_reports() method receives aggregated report data
// and returns a dict with optional keys:
//   - "commands": {host_id: {...}, ...}  — forwarded to UAV mobility
//   - "log": {"name": value, ...}        — emitted as named OMNeT++ signals
//
// This keeps the GCS general-purpose: the Python class decides what
// algorithm to run (detection, coordination, mission planning, etc.)
// and what to log.
//
simple GcsModule
{
    parameters:
        @class(GcsModule);
        @display("i=misc/globe");

        // Space-separated host indices this GCS is responsible for.
        // Empty string = all hosts.
        string federateIndices = default("");

        // Python class for decision algorithm (empty = no Python)
        string pyClass = default("");

        // Path to PyBridge module
        string pyBridgePath = default("^.pyBridge");

        // Whether to forward Python control commands to UAV mobility modules
        bool sendControlCommands = default(false);

    gates:
        input directIn @directIn;
}
