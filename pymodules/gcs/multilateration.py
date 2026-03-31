"""
RSSI-based multilateration for spoofer localization.

Jointly estimates transmitter position and TX power from multiple receiver
RSSI measurements using 2.4 GHz free-space path loss model (Eq. 8-10 in paper).

    RSSI = P_tx - 20*log10(d) - 40.04
"""

import numpy as np
from scipy.optimize import least_squares

FSPL_CONSTANT_DB = 40.04


def multilaterate_with_tx(
    receivers: np.ndarray,
    rssi_values: np.ndarray,
    initial_pos: np.ndarray,
) -> tuple[np.ndarray | None, float | None]:
    """
    Jointly estimate transmitter position and TX power via nonlinear least squares.

    Args:
        receivers: (N, 3) receiver positions
        rssi_values: (N,) RSSI measurements (dBm)
        initial_pos: Initial guess (e.g. claimed position)

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

    distances_init = np.maximum(np.linalg.norm(receivers - initial_pos, axis=1), 0.1)
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
