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

        // Qtenv 2D overlay (network canvas): top-down XY slice of unsafe ellipsoid,
        // claimed-RID polyline, and true spoofer position when trackHostId is set.
        // When overlayBenignRiskMarkers=true: benign hosts inside the published 3D unsafe
        // ellipsoid (ground-truth pose) get a filled red highlight; hosts only within
        // overlayNmacProximityM of the spoofer truth (not in the ellipsoid) get a hollow
        // darkorange outline instead.
        bool drawPresentationOverlay = default(true);
        bool overlayBenignRiskMarkers = default(true);
        double overlayNmacProximityM @unit(m) = default(50m);
        // Legacy: overlay was linear-mapped in GcsModule; it now uses INET CanvasProjection
        // (same transform as mobility trails). These are kept for compatibility but unused.
        bool overlayFollowSpoofer = default(true);
        double overlayFollowHalfSpan @unit(m) = default(350m);
        double overlayMapMinX @unit(m) = default(-100m);
        double overlayMapMaxX @unit(m) = default(600m);
        double overlayMapMinY @unit(m) = default(-100m);
        double overlayMapMaxY @unit(m) = default(600m);
        int overlayMaxClaimedPoints = default(800);
        // If a new claimed point is farther than this from the previous, drop the trail
        // (avoids one bad sample / serial mix-up drawing a long "dragging" segment).
        double overlayClaimedJumpResetM @unit(m) = default(400m);
        // Per-host final waypoint (from mobility waypointScript) as filled dots on the 2D
        // overlay; colors match BasicUav canvas mobility trail palette by host index.
        bool overlayShowHostGoals = default(true);

    gates:
        input directIn @directIn;
}
