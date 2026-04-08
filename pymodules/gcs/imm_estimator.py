"""
Interactive Multiple Model (IMM) estimator for spoofer state localization.

Fuses CV (constant velocity) and CA (constant acceleration) motion hypotheses
to provide optimal state estimate (mu, Sigma) for the spoofer position.
Measurement: 3D position from multilateration (Eq. 17 in paper).

The IMM framework recursively combines weighted filter estimates to maintain
a probabilistic belief over the spoofer state through time (Sec. V-B).
"""

import numpy as np


class KalmanFilter3D:
    """Linear Kalman filter for 3D position tracking."""

    def __init__(self, F, H, Q, R, x0, P0):
        self.F = np.array(F, dtype=float)
        self.H = np.array(H, dtype=float)
        self.Q = np.array(Q, dtype=float)
        self.R = np.array(R, dtype=float)
        self.x = np.array(x0, dtype=float)
        self.P = np.array(P0, dtype=float)

    def predict(self):
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q

    def update(self, z, meas_cov: np.ndarray | None = None):
        z = np.asarray(z, dtype=float).ravel()
        y = z - self.H @ self.x
        R_eff = self.R if meas_cov is None else np.asarray(meas_cov, dtype=float)
        R_eff = np.nan_to_num(R_eff, nan=1e3, posinf=1e6, neginf=1e3)
        if R_eff.shape != (3, 3):
            R_eff = np.eye(3) * 1e3
        R_eff = 0.5 * (R_eff + R_eff.T)

        S = self.H @ self.P @ self.H.T + R_eff
        S = np.nan_to_num(S, nan=1e3, posinf=1e6, neginf=1e3)
        S = 0.5 * (S + S.T)
        try:
            S_inv = np.linalg.inv(S)
        except np.linalg.LinAlgError:
            S_inv = np.linalg.pinv(S)

        K = self.P @ self.H.T @ S_inv
        self.x = self.x + K @ y
        self.x = np.nan_to_num(self.x, nan=0.0, posinf=0.0, neginf=0.0)
        I = np.eye(len(self.x))
        self.P = (I - K @ self.H) @ self.P
        self.P = np.nan_to_num(self.P, nan=1e3, posinf=1e6, neginf=-1e6)
        return y, S

    @staticmethod
    def create_cv(dt, pos_noise=1.0, vel_noise=20.0, measurement_noise=1000.0):
        """Constant velocity model (Eq. 19) with structured process noise."""
        F = np.eye(6)
        F[0, 3] = dt
        F[1, 4] = dt
        F[2, 5] = dt
        H = np.zeros((3, 6))
        H[0, 0] = H[1, 1] = H[2, 2] = 1.0
        Q = np.diag([pos_noise, pos_noise, pos_noise,
                      vel_noise, vel_noise, vel_noise])
        R = np.eye(3) * measurement_noise
        x0 = np.zeros(6)
        P0 = np.eye(6) * 500.0
        return KalmanFilter3D(F, H, Q, R, x0, P0)

    @staticmethod
    def create_ca(dt, pos_noise=1.0, vel_noise=10.0, acc_noise=20.0, measurement_noise=1000.0):
        """Constant acceleration model (Eq. 20) with structured process noise."""
        F = np.eye(9)
        F[0, 3] = dt; F[1, 4] = dt; F[2, 5] = dt
        F[0, 6] = 0.5*dt*dt; F[1, 7] = 0.5*dt*dt; F[2, 8] = 0.5*dt*dt
        F[3, 6] = dt; F[4, 7] = dt; F[5, 8] = dt
        H = np.zeros((3, 9))
        H[0, 0] = H[1, 1] = H[2, 2] = 1.0
        Q = np.diag([pos_noise, pos_noise, pos_noise,
                      vel_noise, vel_noise, vel_noise,
                      acc_noise, acc_noise, acc_noise])
        R = np.eye(3) * measurement_noise
        x0 = np.zeros(9)
        P0 = np.eye(9) * 500.0
        return KalmanFilter3D(F, H, Q, R, x0, P0)


class IMMEstimator:
    """
    Interacting Multiple Model estimator (Sec. V-B.3).

    Fuses CV and CA hypotheses with model-transition probabilities.
    Produces merged position estimate (mu) and covariance (Sigma).

    predict() is only called internally right before update() to avoid
    unbounded covariance growth between measurements.
    """

    def __init__(
        self,
        dt: float = 1.0,
        cv_pos_noise: float = 2.0,
        cv_vel_noise: float = 40.0,
        cv_measurement_noise: float = 100.0,
        ca_pos_noise: float = 2.0,
        ca_vel_noise: float = 25.0,
        ca_acc_noise: float = 60.0,
        ca_measurement_noise: float = 100.0,
        init_mode_cv: float = 0.6,
        p_cv_stay: float = 0.95,
        p_ca_stay: float = 0.95,
    ):
        # Use a more responsive process model so a maneuvering spoofer track
        # does not remain anchored after detection.
        self.dt = float(max(dt, 1e-3))
        cv_measurement_noise = float(max(cv_measurement_noise, 1e-6))
        ca_measurement_noise = float(max(ca_measurement_noise, 1e-6))
        self.kf_cv = KalmanFilter3D.create_cv(
            self.dt,
            pos_noise=float(max(cv_pos_noise, 1e-9)),
            vel_noise=float(max(cv_vel_noise, 1e-9)),
            measurement_noise=cv_measurement_noise,
        )
        self.kf_ca = KalmanFilter3D.create_ca(
            self.dt,
            pos_noise=float(max(ca_pos_noise, 1e-9)),
            vel_noise=float(max(ca_vel_noise, 1e-9)),
            acc_noise=float(max(ca_acc_noise, 1e-9)),
            measurement_noise=ca_measurement_noise,
        )
        init_mode_cv = float(np.clip(init_mode_cv, 0.0, 1.0))
        self.mu = np.array([init_mode_cv, 1.0 - init_mode_cv], dtype=float)
        p_cv_stay = float(np.clip(p_cv_stay, 0.0, 1.0))
        p_ca_stay = float(np.clip(p_ca_stay, 0.0, 1.0))
        self.pi = np.array(
            [
                [p_cv_stay, 1.0 - p_cv_stay],
                [1.0 - p_ca_stay, p_ca_stay],
            ],
            dtype=float,
        )
        self._initialized = False
        self._last_z: np.ndarray | None = None
        self._snap_distance_m = 15.0
        self._min_pos_var = 1.0
        self._max_pos_var = 2500.0
        self._predicts_since_update = 0
        self._last_nis_cv = float("nan")
        self._last_nis_ca = float("nan")
        self._last_nis_mix = float("nan")
        self._last_meas_time_s = float("nan")

    def _clamp_pos_cov(self, P: np.ndarray) -> np.ndarray:
        """Clamp position covariance eigenvalues to avoid collapse/blow-up."""
        C = np.asarray(P[:3, :3], dtype=float)
        vmin = float(max(self._min_pos_var, 1e-6))
        vmax = float(max(vmin, self._max_pos_var))

        # Clean non-finite values first.
        C = np.nan_to_num(C, nan=0.0, posinf=vmax, neginf=-vmax)
        C = 0.5 * (C + C.T)

        # Robust eigendecomposition with progressive jitter.
        success = False
        for k in range(6):
            jitter = (10.0 ** k) * 1e-9
            try:
                vals, vecs = np.linalg.eigh(C + np.eye(3) * jitter)
                vals = np.clip(vals, vmin, vmax)
                C_out = vecs @ np.diag(vals) @ vecs.T
                C_out = 0.5 * (C_out + C_out.T)
                if np.all(np.isfinite(C_out)):
                    P[:3, :3] = C_out
                    success = True
                    break
            except np.linalg.LinAlgError:
                continue

        if not success:
            # Last-resort diagonal fallback.
            d = np.diag(C)
            d = np.nan_to_num(d, nan=vmin, posinf=vmax, neginf=vmin)
            d = np.clip(d, vmin, vmax)
            P[:3, :3] = np.diag(d)
        return P

    def _propagate_modes(self) -> None:
        self.mu = self.pi.T @ self.mu
        s = float(self.mu.sum())
        if s > 1e-12:
            self.mu /= s

    def predict_only(self, max_predict_steps: int | None = None) -> None:
        """
        Propagate IMM state without a measurement update.

        Used to provide smooth, continuous unsafe-region motion between
        1 Hz RID/multilateration updates.
        """
        if not self._initialized:
            return
        if max_predict_steps is not None and self._predicts_since_update >= max_predict_steps:
            return
        self.kf_cv.predict()
        self.kf_ca.predict()
        self.kf_cv.P = self._clamp_pos_cov(self.kf_cv.P)
        self.kf_ca.P = self._clamp_pos_cov(self.kf_ca.P)
        self._propagate_modes()
        self._predicts_since_update += 1

    def update(
        self,
        z: np.ndarray,
        meas_cov: np.ndarray | None = None,
        do_predict: bool = True,
        measurement_time_s: float | None = None,
    ):
        """Predict-then-update cycle, called when a new measurement arrives."""
        z = np.asarray(z, dtype=float).ravel()[:3]
        if not self._initialized:
            self.kf_cv.x[:3] = z
            self.kf_ca.x[:3] = z
            if meas_cov is not None:
                m = np.asarray(meas_cov, dtype=float)
                self.kf_cv.P[:3, :3] = m
                self.kf_ca.P[:3, :3] = m
            self.kf_cv.P = self._clamp_pos_cov(self.kf_cv.P)
            self.kf_ca.P = self._clamp_pos_cov(self.kf_ca.P)
            self._initialized = True
            self._last_z = z.copy()
            self._predicts_since_update = 0
            if measurement_time_s is not None:
                self._last_meas_time_s = float(measurement_time_s)
            return

        # Finite-difference velocity cue from multilateration positions.
        vel_meas = None
        if self._last_z is not None:
            vel_meas = (z - self._last_z) / self.dt
            self.kf_cv.x[3:6] = 0.5 * self.kf_cv.x[3:6] + 0.5 * vel_meas
            self.kf_ca.x[3:6] = 0.5 * self.kf_ca.x[3:6] + 0.5 * vel_meas

        # Optional predict step right before measurement.
        if do_predict:
            self.predict_only()
        pred_pos = self.mu[0] * self.kf_cv.x[:3] + self.mu[1] * self.kf_ca.x[:3]

        # Update step
        y_cv, S_cv = self.kf_cv.update(z, meas_cov=meas_cov)
        y_ca, S_ca = self.kf_ca.update(z, meas_cov=meas_cov)
        self.kf_cv.P = self._clamp_pos_cov(self.kf_cv.P)
        self.kf_ca.P = self._clamp_pos_cov(self.kf_ca.P)

        L_cv = self._gaussian_likelihood(y_cv, S_cv)
        L_ca = self._gaussian_likelihood(y_ca, S_ca)
        self._last_nis_cv = self._nis(y_cv, S_cv)
        self._last_nis_ca = self._nis(y_ca, S_ca)

        c = self.mu[0] * L_cv + self.mu[1] * L_ca
        if c > 1e-300:
            self.mu[0] = self.mu[0] * L_cv / c
            self.mu[1] = self.mu[1] * L_ca / c
        self._last_nis_mix = (
            float(self.mu[0]) * self._last_nis_cv + float(self.mu[1]) * self._last_nis_ca
        )

        # If prediction is far from current multilateration, snap position to
        # measurement to prevent a "stuck bubble" while preserving covariance.
        if np.linalg.norm(z - pred_pos) > self._snap_distance_m:
            self.kf_cv.x[:3] = z
            self.kf_ca.x[:3] = z
            if vel_meas is not None:
                self.kf_cv.x[3:6] = vel_meas
                self.kf_ca.x[3:6] = vel_meas
            if meas_cov is not None:
                m = np.asarray(meas_cov, dtype=float)
                self.kf_cv.P[:3, :3] = m
                self.kf_ca.P[:3, :3] = m
            self.kf_cv.P = self._clamp_pos_cov(self.kf_cv.P)
            self.kf_ca.P = self._clamp_pos_cov(self.kf_ca.P)
            # Favor CA briefly after large jumps.
            self.mu = np.array([0.35, 0.65], dtype=float)

        self._last_z = z.copy()
        self._predicts_since_update = 0
        if measurement_time_s is not None:
            self._last_meas_time_s = float(measurement_time_s)

    def get_state(self) -> tuple[np.ndarray, np.ndarray]:
        """Return merged (mu_pos, Sigma_pos) — position only."""
        pos_cv = self.kf_cv.x[:3]
        pos_ca = self.kf_ca.x[:3]
        cov_cv = self.kf_cv.P[:3, :3]
        cov_ca = self.kf_ca.P[:3, :3]

        mu_merged = self.mu[0] * pos_cv + self.mu[1] * pos_ca
        d_cv = (pos_cv - mu_merged).reshape(-1, 1)
        d_ca = (pos_ca - mu_merged).reshape(-1, 1)
        cov_merged = (
            self.mu[0] * (cov_cv + d_cv @ d_cv.T) +
            self.mu[1] * (cov_ca + d_ca @ d_ca.T)
        )
        return mu_merged, cov_merged

    def get_diagnostics(self) -> dict[str, float]:
        return {
            "mode_prob_cv": float(self.mu[0]),
            "mode_prob_ca": float(self.mu[1]),
            "nis_cv": float(self._last_nis_cv),
            "nis_ca": float(self._last_nis_ca),
            "nis_mix": float(self._last_nis_mix),
            "last_measurement_time_s": float(self._last_meas_time_s),
        }

    @staticmethod
    def _gaussian_likelihood(y, S):
        n = len(y)
        y = np.nan_to_num(np.asarray(y, dtype=float).ravel(), nan=0.0, posinf=0.0, neginf=0.0)
        S = np.nan_to_num(np.asarray(S, dtype=float), nan=1e3, posinf=1e6, neginf=1e3)
        if S.shape != (n, n):
            return 1e-300
        S = 0.5 * (S + S.T)

        # Robust slogdet/inverse with progressive jitter.
        for k in range(6):
            jitter = (10.0 ** k) * 1e-9
            Sj = S + np.eye(n) * jitter
            try:
                sign, logdet = np.linalg.slogdet(Sj)
                if not np.isfinite(logdet) or sign <= 0:
                    continue
                try:
                    S_inv = np.linalg.inv(Sj)
                except np.linalg.LinAlgError:
                    S_inv = np.linalg.pinv(Sj)
                quad = float(y @ S_inv @ y)
                if not np.isfinite(quad):
                    continue
                exp_term = -0.5 * quad
                log_L = -0.5 * n * np.log(2 * np.pi) - 0.5 * logdet + exp_term
                if not np.isfinite(log_L):
                    continue
                return max(float(np.exp(log_L)), 1e-300)
            except np.linalg.LinAlgError:
                continue
        return 1e-300

    @staticmethod
    def _nis(y: np.ndarray, S: np.ndarray) -> float:
        yv = np.nan_to_num(np.asarray(y, dtype=float).ravel(), nan=0.0, posinf=0.0, neginf=0.0)
        Sm = np.nan_to_num(np.asarray(S, dtype=float), nan=1e3, posinf=1e6, neginf=1e3)
        n = yv.shape[0]
        if Sm.shape != (n, n):
            return float("nan")
        Sm = 0.5 * (Sm + Sm.T)
        for k in range(6):
            jitter = (10.0 ** k) * 1e-9
            Sj = Sm + np.eye(n) * jitter
            try:
                Sinv = np.linalg.inv(Sj)
            except np.linalg.LinAlgError:
                try:
                    Sinv = np.linalg.pinv(Sj)
                except np.linalg.LinAlgError:
                    continue
            nis = float(yv @ Sinv @ yv)
            if np.isfinite(nis):
                return nis
        return float("nan")
