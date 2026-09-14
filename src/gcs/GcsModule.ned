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
// The Python class can implement two callbacks:
//   - on_reports(data): called per transmission with aggregated RX reports
//   - on_tick(data): called periodically (if tickInterval > 0)
//
// Both return a dict with optional keys:
//   - "commands": {host_id: {...}, ...}  — forwarded to UAV mobility
//   - "log": {"name": value, ...}        — recorded as cOutVector entries
//
// Optional: on_gcs_finish() at simulation end:
//   - "scalars": {"name": value, ...}    — recorded via recordScalar() → .sca
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

        // Periodic tick interval for on_tick() callback (0 = disabled)
        double tickInterval @unit(s) = default(0s);

    gates:
        input directIn @directIn;
}
