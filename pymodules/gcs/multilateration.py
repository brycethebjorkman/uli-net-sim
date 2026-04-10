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
POS_BOUNDS_LO = np.array([-2000.0, -2000.0, -200.0], dtype=float)
POS_BOUNDS_HI = np.array([2000.0, 2000.0, 1000.0], dtype=float)


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
    if initial_pos.shape[0] < 3:
        initial_pos = np.pad(initial_pos, (0, 3 - initial_pos.shape[0]), mode="constant")
    initial_pos = np.nan_to_num(initial_pos, nan=0.0, posinf=0.0, neginf=0.0)
    initial_pos = np.clip(initial_pos, POS_BOUNDS_LO, POS_BOUNDS_HI)

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
    bounds = ([POS_BOUNDS_LO[0], POS_BOUNDS_LO[1], POS_BOUNDS_LO[2], -50.0],
              [POS_BOUNDS_HI[0], POS_BOUNDS_HI[1], POS_BOUNDS_HI[2], 50.0])

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
    if initial_pos.shape[0] < 3:
        initial_pos = np.pad(initial_pos, (0, 3 - initial_pos.shape[0]), mode="constant")
    initial_pos = np.nan_to_num(initial_pos, nan=0.0, posinf=0.0, neginf=0.0)
    initial_pos = np.clip(initial_pos, POS_BOUNDS_LO, POS_BOUNDS_HI)

    def residuals(pos):
        distances = np.linalg.norm(receivers - pos, axis=1)
        distances = np.maximum(distances, 0.1)
        expected_rssi = tx_power - 20.0 * np.log10(distances) - FSPL_CONSTANT_DB
        return rssi_values - expected_rssi

    try:
        result = least_squares(
            residuals, initial_pos, method="trf", max_nfev=200,
            bounds=(POS_BOUNDS_LO, POS_BOUNDS_HI)
        )
        if result.success or result.cost < 200:
            return result.x[:3]
        return None
    except Exception:
        return None


def multilateration_position_covariance(
    receivers: np.ndarray,
    estimated_pos: np.ndarray,
    tx_power: float,
    residual_rssi: np.ndarray,
    min_var: float = 1.0,
    max_var: float = 1600.0,
) -> np.ndarray:
    """
    Approximate position covariance from local NLLS geometry.

    Uses the Gauss-Newton approximation:
        Cov(x) ~= sigma_rssi^2 * (J^T J)^(-1)
    where J is the RSSI Jacobian w.r.t. position at the current estimate.
    """
    receivers = np.asarray(receivers, dtype=float)
    pos = np.asarray(estimated_pos, dtype=float).ravel()[:3]
    residual_rssi = np.asarray(residual_rssi, dtype=float).ravel()

    n = receivers.shape[0]
    if n < 3:
        return np.eye(3) * 1000.0

    # RSSI = Ptx - 20*log10(d) - C
    # dRSSI/dx = -20 / ln(10) * (x-rx) / ||x-rx||^2
    k = -20.0 / np.log(10.0)
    J = np.zeros((n, 3), dtype=float)
    for i in range(n):
        diff = pos - receivers[i]
        d = np.linalg.norm(diff)
        d2 = max(d * d, 1e-4)
        J[i, :] = k * (diff / d2)

    dof = max(1, n - 3)
    sigma_rssi2 = float(np.sum(residual_rssi ** 2) / dof)
    sigma_rssi2 = max(sigma_rssi2, 1e-3)

    JTJ = J.T @ J
    try:
        cov = sigma_rssi2 * np.linalg.inv(JTJ)
    except np.linalg.LinAlgError:
        cov = sigma_rssi2 * np.linalg.pinv(JTJ)

    # Numerical regularization: positive-definite floor.
    cov = 0.5 * (cov + cov.T)
    success = False
    for k in range(6):
        jitter = (10.0 ** k) * 1e-9
        try:
            eigvals, eigvecs = np.linalg.eigh(cov + np.eye(3) * jitter)
            eigvals = np.clip(eigvals, min_var, max_var)
            cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
            cov = 0.5 * (cov + cov.T)
            success = np.all(np.isfinite(cov))
            if success:
                break
        except np.linalg.LinAlgError:
            continue
    if not success:
        d = np.diag(cov)
        d = np.nan_to_num(d, nan=min_var, posinf=max_var, neginf=min_var)
        d = np.clip(d, min_var, max_var)
        cov = np.diag(d)
    return cov


def multilaterate_position_with_covariance(
    receivers: np.ndarray,
    rssi_values: np.ndarray,
    initial_pos: np.ndarray,
    tx_power: float,
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """
    Position-only localization plus anisotropic covariance estimate.

    Returns:
        (estimated_pos, estimated_covariance) or (None, None) if failed.
    """
    n = len(rssi_values)
    if n < 3:
        return None, None

    receivers = np.asarray(receivers, dtype=float)
    rssi_values = np.asarray(rssi_values, dtype=float)
    initial_pos = np.asarray(initial_pos, dtype=float).ravel()[:3]
    if initial_pos.shape[0] < 3:
        initial_pos = np.pad(initial_pos, (0, 3 - initial_pos.shape[0]), mode="constant")
    initial_pos = np.nan_to_num(initial_pos, nan=0.0, posinf=0.0, neginf=0.0)
    initial_pos = np.clip(initial_pos, POS_BOUNDS_LO, POS_BOUNDS_HI)

    def residuals(pos):
        distances = np.linalg.norm(receivers - pos, axis=1)
        distances = np.maximum(distances, 0.1)
        expected_rssi = tx_power - 20.0 * np.log10(distances) - FSPL_CONSTANT_DB
        return rssi_values - expected_rssi

    try:
        result = least_squares(
            residuals, initial_pos, method="trf", max_nfev=200,
            bounds=(POS_BOUNDS_LO, POS_BOUNDS_HI)
        )
        if not (result.success or result.cost < 200):
            return None, None
        est_pos = result.x[:3]
        resid = residuals(est_pos)
        cov = multilateration_position_covariance(receivers, est_pos, tx_power, resid)
        # Geometry inflation:
        # Scale covariance up when receiver geometry is weak (nearly collinear/
        # coplanar) or when target range is large relative to anchor spread.
        rx_centered = receivers - np.mean(receivers, axis=0, keepdims=True)
        try:
            svals = np.linalg.svd(rx_centered, compute_uv=False)
            s_max = float(max(svals[0], 1e-6))
            s_min = float(max(svals[-1], 1e-6))
            rank_ratio = float(np.clip(s_min / s_max, 0.0, 1.0))
            geom_penalty = 1.0 + 2.0 * ((1.0 - rank_ratio) ** 2)
            anchor_span_m = float(max(s_max, 1.0))
        except np.linalg.LinAlgError:
            geom_penalty = 3.0
            anchor_span_m = 1.0

        # Model-mismatch inflation:
        # With fixed TX-power localization, TX lock bias and channel mismatch can
        # shift the mean while residuals remain deceptively small. Inflate the
        # covariance based on equivalent range uncertainty implied by RSSI mismatch.
        dists = np.linalg.norm(receivers - est_pos, axis=1)
        d_med = float(np.median(np.maximum(dists, 1.0)))

        sigma_rssi_db = float(np.std(resid))
        tx_bias_db = float(abs(np.median(resid)))
        # dR/dRSSI ≈ ln(10)/20 * R
        gain = np.log(10.0) / 20.0
        sigma_from_noise_m = gain * d_med * sigma_rssi_db
        sigma_from_bias_m = gain * d_med * tx_bias_db
        range_penalty = float(np.clip(d_med / anchor_span_m, 1.0, 3.0))
        geom_penalty = float(np.clip(geom_penalty, 1.0, 3.0))
        geom_scale = float(np.clip(0.5 * (geom_penalty + range_penalty), 1.0, 3.0))
        sigma_model_m = max(0.0, sigma_from_noise_m + sigma_from_bias_m)
        sigma_model_m *= np.sqrt(geom_scale)
        sigma_model_m = min(sigma_model_m, 20.0)  # keep model-mismatch inflation bounded

        if sigma_model_m > 0.0:
            cov = cov + np.eye(3) * (sigma_model_m ** 2)
        cov = cov * geom_scale

        # Final clamp to avoid pathological late-run bubble blow-up.
        cov = 0.5 * (cov + cov.T)
        success = False
        for k in range(6):
            jitter = (10.0 ** k) * 1e-9
            try:
                eigvals, eigvecs = np.linalg.eigh(cov + np.eye(3) * jitter)
                eigvals = np.clip(eigvals, 2.25, 2500.0)  # 2.25..2500 m^2 (std <= 50 m)
                cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
                cov = 0.5 * (cov + cov.T)
                success = np.all(np.isfinite(cov))
                if success:
                    break
            except np.linalg.LinAlgError:
                continue
        if not success:
            d = np.diag(cov)
            d = np.nan_to_num(d, nan=2.25, posinf=2500.0, neginf=2.25)
            d = np.clip(d, 2.25, 2500.0)
            cov = np.diag(d)

        return est_pos, cov
    except Exception:
        return None, None
