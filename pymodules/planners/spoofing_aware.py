"""
Spoofing-aware planner for GcsModule.

Aggregates RX reports from federate receivers and tracks per-serial RSSI
statistics.  On each tick, logs a simple anomaly indicator per tracked
serial number (placeholder for a real risk-domain replanning algorithm).

Demonstrates combining on_reports() (per-transmission) with on_tick()
(periodic) in a single GCS Python class.

INI usage:
    *.gcs[0].pyClass = "pymodules.planners.spoofing_aware.SpoofingAwarePlanner"
    *.gcs[0].tickInterval = 2s
    *.gcs[0].sendControlCommands = true
"""

import math


class SpoofingAwarePlanner:
    """Performs spoofing localization and uses a risk-domain approach to plan federate trajectories."""

    def __init__(self):
        # Per-serial tracking: serial -> list of (claimed_x, claimed_y, claimed_z, mean_rssi)
        self._observations = {}
        self._tick_count = 0

    # ------------------------------------------------------------------
    # on_reports: called once per transmission with aggregated RX reports
    # ------------------------------------------------------------------
    def on_gcs_reports(self, data):
        serial = data['serial_number']
        reports = data['reports']

        if not reports:
            return {'log': {}}

        # Compute mean RSSI across all receivers for this transmission
        rssi_values = [r['rssi_dbm'] for r in reports]
        mean_rssi = sum(rssi_values) / len(rssi_values)

        # Store claimed position + mean RSSI
        claimed = data['claimed_pos']  # (x, y, z) — same for all reports
        obs = (claimed[0], claimed[1], claimed[2], mean_rssi)

        if serial not in self._observations:
            self._observations[serial] = []
        self._observations[serial].append(obs)

        return {
            'log': {
                'report_serial': serial,
                'report_mean_rssi': mean_rssi,
                'report_num_receivers': len(reports),
            },
        }

    # ------------------------------------------------------------------
    # on_tick: called periodically — issue commands to federate hosts
    # ------------------------------------------------------------------
    def on_gcs_tick(self, data):
        host_ids = data['host_ids']
        self._tick_count += 1

        # --- Placeholder anomaly score per serial ---
        # A real implementation would compare RSSI-predicted distance to
        # claimed position distance and flag inconsistencies.
        anomaly_scores = {}
        for serial, obs_list in self._observations.items():
            if len(obs_list) < 2:
                anomaly_scores[serial] = 0.0
                continue
            # Simple heuristic: large RSSI variance across transmissions
            rssi_vals = [o[3] for o in obs_list]
            mean_r = sum(rssi_vals) / len(rssi_vals)
            variance = sum((r - mean_r) ** 2 for r in rssi_vals) / len(rssi_vals)
            anomaly_scores[serial] = variance

        # --- Placeholder command generation ---
        # A real implementation would replan trajectories to improve
        # geometric diversity around suspected spoofers.
        commands = {}
        for hid in host_ids:
            commands[hid] = {
                'task': 'hold',  # no replanning yet — just hold position
            }

        # Log anomaly scores for the top-scoring serial (if any)
        log = {'tick_count': self._tick_count}
        if anomaly_scores:
            worst_serial = max(anomaly_scores, key=anomaly_scores.get)
            log['worst_serial'] = worst_serial
            log['worst_anomaly'] = anomaly_scores[worst_serial]
            log['num_tracked_serials'] = len(anomaly_scores)

        return {
            'commands': commands,
            'log': log,
        }
