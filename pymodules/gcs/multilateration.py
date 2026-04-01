"""
RSSI-based multilateration for spoofer detection and localization.

Contains both functions needed by the GCS pipeline, avoiding any dependency
on the evaluations package (which requires pandas/torch).

Detection phase:
  multilaterate_with_tx_power — joint position + TX power (4 unknowns)
  PositionErrorKF             — per-transmitter error smoothing

Localization phase:
  multilaterate_position      — position-only with known TX power (3 unknowns)

All functions use the same FSPL model (2.4 GHz):
    RSSI = P_tx - 20*log10(d) - 40.04

These are the same algorithms as evaluations.detectors.multilaterate_with_tx_power
and evaluations.detectors.PositionErrorKF.
"""

import numpy as np
from scipy.optimize import least_squares

FSPL_CONSTANT_DB = 40.04


# ==========================================================================
# Detection: joint position + TX power estimation
# ==========================================================================

def multilaterate_with_tx_power(
    receivers: np.ndarray,
    rssi_values: np.ndarray,
    initial_pos: np.ndarray,
) -> tuple[np.ndarray | None, float | None]:
    """
    Jointly estimate transmitter position and TX power via NLLS.

    4 unknowns (x, y, z, P_tx), needs N >= 4 receivers.
    Same algorithm as evaluations.detectors.multilaterate_with_tx_power.

    Returns:
        (estimated_pos, estimated_tx_power) or (None, None) if failed
    """
    n = len(rssi_values)
    if n < 4:
        return None, None

    receivers = np.asarray(receivers, dtype=float)
    rssi_values = np.asarray(rssi_values, dtype=float)
    initial_pos = np.asarray(initial_pos, dtype=float).ravel()[:3]

    def residuals(params):
        pos = params[:3]
        tx_power = params[3]
        distances = np.linalg.norm(receivers - pos, axis=1)
        distances = np.maximum(distances, 0.1)
        expected_rssi = tx_power - 20.0 * np.log10(distances) - FSPL_CONSTANT_DB
        return rssi_values - expected_rssi

    distances_init = np.linalg.norm(receivers - initial_pos, axis=1)
    distances_init = np.maximum(distances_init, 0.1)
    tx_power_init = float(np.median(
        rssi_values + 20.0 * np.log10(distances_init) + FSPL_CONSTANT_DB
    ))
    x0 = np.concatenate([initial_pos, [tx_power_init]])
    bounds = ([-np.inf, -np.inf, -np.inf, -50], [np.inf, np.inf, np.inf, 50])

    try:
        result = least_squares(residuals, x0, bounds=bounds, method="trf", max_nfev=100)
        if result.success or result.cost < 100:
            return result.x[:3], result.x[3]
        return None, None
    except Exception:
        return None, None


# ==========================================================================
# Detection: position error smoothing KF
# ==========================================================================

class PositionErrorKF:
    """
    Kalman Filter for tracking position error magnitude.

    State: x = [error] (scalar)
    Measurement: z = |estimated_pos - claimed_pos|

    Same as evaluations.detectors.PositionErrorKF.
    """

    def __init__(
        self,
        process_noise: float = 1.0,
        measurement_noise: float = 100.0,
        initial_estimate: float = 0.0,
        initial_covariance: float = 1000.0,
    ):
        self.Q = process_noise
        self.R = measurement_noise
        self.x = initial_estimate
        self.P = initial_covariance

    def update(self, measurement: float) -> tuple[float, float, float]:
        """
        Process a position error measurement.

        Returns:
            (NIS, filtered_error, innovation)
        """
        x_pred = self.x
        P_pred = self.P + self.Q

        innovation = measurement - x_pred
        S = P_pred + self.R

        nis = (innovation ** 2) / S

        K = P_pred / S
        self.x = x_pred + K * innovation
        self.P = (1 - K) * P_pred

        return nis, self.x, innovation


# ==========================================================================
# Localization: position-only with known TX power
# ==========================================================================

def multilaterate_position(
    receivers: np.ndarray,
    rssi_values: np.ndarray,
    initial_pos: np.ndarray,
    tx_power: float,
) -> np.ndarray | None:
    """
    Position-only localization with known TX power.

    3 unknowns (x, y, z), overdetermined with N >= 3 receivers.

    Returns:
        estimated_pos or None if failed
    """
    n = len(rssi_values)
    if n < 3:
        return None

    receivers = np.asarray(receivers, dtype=float)
    rssi_values = np.asarray(rssi_values, dtype=float)
    initial_pos = np.asarray(initial_pos, dtype=float).ravel()[:3]

    def residuals(pos):
        distances = np.linalg.norm(receivers - pos, axis=1)
        distances = np.maximum(distances, 0.1)
        expected_rssi = tx_power - 20.0 * np.log10(distances) - FSPL_CONSTANT_DB
        return rssi_values - expected_rssi

    try:
        result = least_squares(residuals, initial_pos, method="trf", max_nfev=200)
        if result.success or result.cost < 200:
            return result.x[:3]
        return None
    except Exception:
        return None
