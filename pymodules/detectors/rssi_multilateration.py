"""
GCS-side RSSI multilateration detector.

Uses the same algorithm as evaluations.detectors.MultilatDetector but runs
online during simulation via the GcsModule on_gcs_reports() callback.

For each transmission, jointly estimates transmitter position and TX power
from RSSI at multiple federate receivers via nonlinear least squares, then
tracks the position error with a per-transmitter Kalman filter. High filtered
error indicates spoofing.

Requires >=4 federate receivers to multilaterate.

INI usage:
    *.numGcs = 1
    *.gcs[0].pyClass = "pymodules.detectors.rssi_multilateration.RssiMultilaterationDetector"
    *.gcs[0].federateIndices = "0 1 2 3"
"""

import numpy as np
from pymodules.gcs.multilateration import multilaterate_with_tx_power, PositionErrorKF


class RssiMultilaterationDetector:
    """Online RSSI multilateration spoofing detector."""

    def __init__(self):
        self._kf_per_tx = {}  # serial_number -> PositionErrorKF
        self._min_receivers = 4
        self._kf_process_noise = 100.0
        self._kf_measurement_noise = 250000.0

    def on_gcs_reports(self, data):
        serial = data['serial_number']
        reports = data['reports']
        claimed = data['claimed_pos']
        receiver_count = int(len(reports))
        skipped = receiver_count < self._min_receivers

        if skipped:
            return {
                'log': {
                    'mlat_score': 0.0,
                    'mlat_raw_error': 0.0,
                    'mlat_receiver_count': float(receiver_count),
                    'mlat_skipped_insufficient_receivers': 1.0,
                }
            }

        # Build arrays from report dicts
        rx_positions = np.array([r['pos'] for r in reports])
        rssi_values = np.array([r['rssi_dbm'] for r in reports])
        claimed_pos = np.array(claimed)

        # Jointly estimate position and TX power
        est_pos, est_tx = multilaterate_with_tx_power(
            rx_positions, rssi_values, claimed_pos
        )

        if est_pos is None:
            return {
                'log': {
                    'mlat_score': 0.0,
                    'mlat_raw_error': 0.0,
                    'mlat_receiver_count': float(receiver_count),
                    'mlat_skipped_insufficient_receivers': 0.0,
                }
            }

        raw_error = float(np.linalg.norm(est_pos - claimed_pos))

        # Per-transmitter Kalman filter for error smoothing
        if serial not in self._kf_per_tx:
            self._kf_per_tx[serial] = PositionErrorKF(
                process_noise=self._kf_process_noise,
                measurement_noise=self._kf_measurement_noise,
            )

        _nis, filtered_error, _innov = self._kf_per_tx[serial].update(raw_error)

        return {
            'log': {
                'mlat_score': filtered_error,
                'mlat_raw_error': raw_error,
                'mlat_est_x_m': float(est_pos[0]),
                'mlat_est_y_m': float(est_pos[1]),
                'mlat_est_z_m': float(est_pos[2]) if len(est_pos) > 2 else 0.0,
                'mlat_est_tx_dbm': float(est_tx),
                'mlat_receiver_count': float(receiver_count),
                'mlat_skipped_insufficient_receivers': 0.0,
            },
        }
