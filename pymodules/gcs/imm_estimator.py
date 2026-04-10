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
        # Joseph-form covariance update is numerically safer and less likely to
        # create non-PSD / overconfident covariance under finite precision.
        IKH = I - K @ self.H
        self.P = IKH @ self.P @ IKH.T + K @ R_eff @ K.T
        self.P = 0.5 * (self.P + self.P.T)
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
        self._nominal_dt = float(self.dt)
        self._cv_pos_noise = float(max(cv_pos_noise, 1e-9))
        self._cv_vel_noise = float(max(cv_vel_noise, 1e-9))
        self._ca_pos_noise = float(max(ca_pos_noise, 1e-9))
        self._ca_vel_noise = float(max(ca_vel_noise, 1e-9))
        self._ca_acc_noise = float(max(ca_acc_noise, 1e-9))
        cv_measurement_noise = float(max(cv_measurement_noise, 1e-6))
        ca_measurement_noise = float(max(ca_measurement_noise, 1e-6))
        self.kf_cv = KalmanFilter3D.create_cv(
            self.dt,
            pos_noise=self._cv_pos_noise,
            vel_noise=self._cv_vel_noise,
            measurement_noise=cv_measurement_noise,
        )
        self.kf_ca = KalmanFilter3D.create_ca(
            self.dt,
            pos_noise=self._ca_pos_noise,
            vel_noise=self._ca_vel_noise,
            acc_noise=self._ca_acc_noise,
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
        self._min_pos_var = 4.0
        self._max_pos_var = 2500.0
        self._min_meas_var = 4.0
        self._max_meas_var = 6400.0
        self._nis_gate = 11.34  # chi2_3 @ 99%
        self._nis_reject_gate = 60.0
        self._meas_downweight_max = 16.0
        self._cov_inflate_gain = 0.25
        self._cov_inflate_max = 8.0
        self._cv_to_ca_acc_var = 64.0
        self._predicts_since_update = 0
        self._last_nis_cv = float("nan")
        self._last_nis_ca = float("nan")
        self._last_nis_mix = float("nan")
        self._last_meas_time_s = float("nan")
        self._max_speed_mps = 120.0
        self._max_acc_mps2 = 40.0
        self._pos_bounds_lo = np.array([-2500.0, -2500.0, -300.0], dtype=float)
        self._pos_bounds_hi = np.array([2500.0, 2500.0, 1200.0], dtype=float)

    def _set_model_dt(self, dt_s: float) -> None:
        """Update CV/CA transition matrices and Q for the provided timestep."""
        dt = float(max(dt_s, 1e-3))
        self.kf_cv.F = np.eye(6, dtype=float)
        self.kf_cv.F[0, 3] = dt
        self.kf_cv.F[1, 4] = dt
        self.kf_cv.F[2, 5] = dt

        self.kf_ca.F = np.eye(9, dtype=float)
        self.kf_ca.F[0, 3] = dt
        self.kf_ca.F[1, 4] = dt
        self.kf_ca.F[2, 5] = dt
        dt2 = dt * dt
        self.kf_ca.F[0, 6] = 0.5 * dt2
        self.kf_ca.F[1, 7] = 0.5 * dt2
        self.kf_ca.F[2, 8] = 0.5 * dt2
        self.kf_ca.F[3, 6] = dt
        self.kf_ca.F[4, 7] = dt
        self.kf_ca.F[5, 8] = dt

        # Treat configured process noise as nominal per-step values at init dt,
        # and scale by elapsed dynamics time to preserve per-second behavior.
        dt_scale = float(max(dt / max(self._nominal_dt, 1e-3), 1e-3))
        self.kf_cv.Q = np.diag(
            [
                self._cv_pos_noise * dt_scale,
                self._cv_pos_noise * dt_scale,
                self._cv_pos_noise * dt_scale,
                self._cv_vel_noise * dt_scale,
                self._cv_vel_noise * dt_scale,
                self._cv_vel_noise * dt_scale,
            ]
        )
        self.kf_ca.Q = np.diag(
            [
                self._ca_pos_noise * dt_scale,
                self._ca_pos_noise * dt_scale,
                self._ca_pos_noise * dt_scale,
                self._ca_vel_noise * dt_scale,
                self._ca_vel_noise * dt_scale,
                self._ca_vel_noise * dt_scale,
                self._ca_acc_noise * dt_scale,
                self._ca_acc_noise * dt_scale,
                self._ca_acc_noise * dt_scale,
            ]
        )

    def _effective_measurement_dt(self, measurement_time_s: float | None) -> float:
        """Use true measurement spacing when available; fall back to nominal dt."""
        dt_eff = float(self.dt)
        if (
            measurement_time_s is not None
            and np.isfinite(measurement_time_s)
            and np.isfinite(self._last_meas_time_s)
        ):
            dt_candidate = float(measurement_time_s) - float(self._last_meas_time_s)
            if dt_candidate > 1e-3:
                dt_eff = dt_candidate
        return float(max(dt_eff, 1e-3))

    def _sanitize_states(self) -> None:
        """Bound model states to physically plausible ranges."""
        # CV: [x,y,z,vx,vy,vz]
        self.kf_cv.x = np.nan_to_num(self.kf_cv.x, nan=0.0, posinf=0.0, neginf=0.0)
        self.kf_cv.x[:3] = np.clip(self.kf_cv.x[:3], self._pos_bounds_lo, self._pos_bounds_hi)
        self.kf_cv.x[3:6] = np.clip(self.kf_cv.x[3:6], -self._max_speed_mps, self._max_speed_mps)

        # CA: [x,y,z,vx,vy,vz,ax,ay,az]
        self.kf_ca.x = np.nan_to_num(self.kf_ca.x, nan=0.0, posinf=0.0, neginf=0.0)
        self.kf_ca.x[:3] = np.clip(self.kf_ca.x[:3], self._pos_bounds_lo, self._pos_bounds_hi)
        self.kf_ca.x[3:6] = np.clip(self.kf_ca.x[3:6], -self._max_speed_mps, self._max_speed_mps)
        self.kf_ca.x[6:9] = np.clip(self.kf_ca.x[6:9], -self._max_acc_mps2, self._max_acc_mps2)

    def _cv_to_ca_state_cov(self, x_cv: np.ndarray, P_cv: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x9 = np.zeros(9, dtype=float)
        x9[:6] = np.asarray(x_cv, dtype=float).ravel()[:6]
        P9 = np.zeros((9, 9), dtype=float)
        P6 = np.asarray(P_cv, dtype=float)[:6, :6]
        P9[:6, :6] = P6
        P9[6:, 6:] = np.eye(3) * self._cv_to_ca_acc_var
        return x9, P9

    @staticmethod
    def _ca_to_cv_state_cov(x_ca: np.ndarray, P_ca: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x6 = np.asarray(x_ca, dtype=float).ravel()[:6].copy()
        P6 = np.asarray(P_ca, dtype=float)[:6, :6].copy()
        return x6, P6

    @staticmethod
    def _mix_states_covariances(
        weights: np.ndarray,
        states: list[np.ndarray],
        covariances: list[np.ndarray],
    ) -> tuple[np.ndarray, np.ndarray]:
        w = np.asarray(weights, dtype=float).ravel()
        s = float(np.sum(w))
        if s <= 1e-12:
            w = np.ones_like(w) / float(len(w))
        else:
            w = w / s
        x_mix = np.zeros_like(states[0], dtype=float)
        for wi, xi in zip(w, states):
            x_mix = x_mix + float(wi) * np.asarray(xi, dtype=float)
        P_mix = np.zeros_like(covariances[0], dtype=float)
        for wi, xi, Pi in zip(w, states, covariances):
            dx = (np.asarray(xi, dtype=float) - x_mix).reshape(-1, 1)
            P_mix = P_mix + float(wi) * (np.asarray(Pi, dtype=float) + dx @ dx.T)
        P_mix = 0.5 * (P_mix + P_mix.T)
        return x_mix, P_mix

    def _regularize_meas_cov(self, meas_cov: np.ndarray | None) -> np.ndarray | None:
        if meas_cov is None:
            return None
        m = np.asarray(meas_cov, dtype=float)
        if m.shape != (3, 3):
            return np.eye(3) * self._max_meas_var
        m = np.nan_to_num(m, nan=self._max_meas_var, posinf=self._max_meas_var, neginf=self._min_meas_var)
        m = 0.5 * (m + m.T)
        success = False
        for k in range(6):
            jitter = (10.0 ** k) * 1e-9
            try:
                eigvals, eigvecs = np.linalg.eigh(m + np.eye(3) * jitter)
                eigvals = np.clip(eigvals, self._min_meas_var, self._max_meas_var)
                m = eigvecs @ np.diag(eigvals) @ eigvecs.T
                m = 0.5 * (m + m.T)
                if np.all(np.isfinite(m)):
                    success = True
                    break
            except np.linalg.LinAlgError:
                continue
        if not success:
            d = np.diag(m)
            d = np.nan_to_num(d, nan=self._min_meas_var, posinf=self._max_meas_var, neginf=self._min_meas_var)
            d = np.clip(d, self._min_meas_var, self._max_meas_var)
            m = np.diag(d)
        return m

    def _inflate_cov_from_nis(self, nis: float) -> float:
        if not np.isfinite(nis):
            return 1.0
        gate = float(max(self._nis_gate, 1e-6))
        if nis <= gate:
            return 1.0
        factor = 1.0 + self._cov_inflate_gain * (nis / gate - 1.0)
        return float(np.clip(factor, 1.0, self._cov_inflate_max))

    @staticmethod
    def _nis_from_innovation(y: np.ndarray, S: np.ndarray) -> float:
        yv = np.asarray(y, dtype=float).ravel()
        Sm = np.asarray(S, dtype=float)
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

    def _interaction_and_mode_prediction(self) -> None:
        """Standard IMM interaction + Markov mode probability prediction."""
        mu_prev = np.asarray(self.mu, dtype=float).ravel()
        c = self.pi.T @ mu_prev
        c_safe = np.clip(c, 1e-12, None)
        mixing = (self.pi * mu_prev[:, None]) / c_safe[None, :]

        # Destination model j=0 (CV): mix CV and projected CA.
        x_cv_from_cv = self.kf_cv.x.copy()
        P_cv_from_cv = self.kf_cv.P.copy()
        x_cv_from_ca, P_cv_from_ca = self._ca_to_cv_state_cov(self.kf_ca.x, self.kf_ca.P)
        x_cv_mix, P_cv_mix = self._mix_states_covariances(
            mixing[:, 0],
            [x_cv_from_cv, x_cv_from_ca],
            [P_cv_from_cv, P_cv_from_ca],
        )

        # Destination model j=1 (CA): mix CA and lifted CV.
        x_ca_from_cv, P_ca_from_cv = self._cv_to_ca_state_cov(self.kf_cv.x, self.kf_cv.P)
        x_ca_from_ca = self.kf_ca.x.copy()
        P_ca_from_ca = self.kf_ca.P.copy()
        x_ca_mix, P_ca_mix = self._mix_states_covariances(
            mixing[:, 1],
            [x_ca_from_cv, x_ca_from_ca],
            [P_ca_from_cv, P_ca_from_ca],
        )

        self.kf_cv.x = x_cv_mix
        self.kf_cv.P = P_cv_mix
        self.kf_ca.x = x_ca_mix
        self.kf_ca.P = P_ca_mix

        self.mu = c
        s = float(self.mu.sum())
        if s > 1e-12:
            self.mu /= s

    def predict_only(
        self,
        max_predict_steps: int | None = None,
        predict_dt_s: float | None = None,
        do_interaction: bool = True,
    ) -> None:
        """
        Propagate IMM state without a measurement update.

        Used to provide smooth, continuous unsafe-region motion between
        1 Hz RID/multilateration updates.
        """
        if not self._initialized:
            return
        if max_predict_steps is not None and self._predicts_since_update >= max_predict_steps:
            return
        if do_interaction:
            self._interaction_and_mode_prediction()
        self._set_model_dt(self.dt if predict_dt_s is None else predict_dt_s)
        self.kf_cv.predict()
        self.kf_ca.predict()
        self._sanitize_states()
        self.kf_cv.P = self._clamp_pos_cov(self.kf_cv.P)
        self.kf_ca.P = self._clamp_pos_cov(self.kf_ca.P)
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
        dt_meas = self._effective_measurement_dt(measurement_time_s)
        meas_cov_eff = self._regularize_meas_cov(meas_cov)
        if not self._initialized:
            self._set_model_dt(dt_meas)
            self.kf_cv.x[:3] = z
            self.kf_ca.x[:3] = z
            if meas_cov_eff is not None:
                m = meas_cov_eff
                self.kf_cv.P[:3, :3] = m
                self.kf_ca.P[:3, :3] = m
            self.kf_cv.P = self._clamp_pos_cov(self.kf_cv.P)
            self.kf_ca.P = self._clamp_pos_cov(self.kf_ca.P)
            self._sanitize_states()
            self._initialized = True
            self._last_z = z.copy()
            self._predicts_since_update = 0
            if measurement_time_s is not None:
                self._last_meas_time_s = float(measurement_time_s)
            return

        # Optional predict step right before measurement.
        if do_predict:
            self.predict_only(predict_dt_s=dt_meas, do_interaction=True)

        x_cv_pred = self.kf_cv.x.copy()
        P_cv_pred = self.kf_cv.P.copy()
        x_ca_pred = self.kf_ca.x.copy()
        P_ca_pred = self.kf_ca.P.copy()

        # Innovation pre-gating on predicted state to avoid pulling toward bad
        # multilateration outliers.
        y_cv_pred = z - self.kf_cv.H @ self.kf_cv.x
        S_cv_pred = self.kf_cv.H @ self.kf_cv.P @ self.kf_cv.H.T + (
            self.kf_cv.R if meas_cov_eff is None else meas_cov_eff
        )
        y_ca_pred = z - self.kf_ca.H @ self.kf_ca.x
        S_ca_pred = self.kf_ca.H @ self.kf_ca.P @ self.kf_ca.H.T + (
            self.kf_ca.R if meas_cov_eff is None else meas_cov_eff
        )
        nis_cv_pred = self._nis_from_innovation(y_cv_pred, S_cv_pred)
        nis_ca_pred = self._nis_from_innovation(y_ca_pred, S_ca_pred)
        nis_pred_mix = float(self.mu[0]) * nis_cv_pred + float(self.mu[1]) * nis_ca_pred

        # Soft downweight: inflate measurement covariance for this update only.
        meas_cov_update = meas_cov_eff
        if np.isfinite(nis_pred_mix) and nis_pred_mix > self._nis_gate:
            scale = float(np.clip(nis_pred_mix / self._nis_gate, 1.0, self._meas_downweight_max))
            if meas_cov_update is None:
                meas_cov_update = np.eye(3) * float(np.mean(np.diag(self.kf_cv.R)))
            meas_cov_update = np.asarray(meas_cov_update, dtype=float) * scale
            meas_cov_update = self._regularize_meas_cov(meas_cov_update)

        # Hard reject: skip measurement update if innovation is implausibly large.
        if np.isfinite(nis_pred_mix) and nis_pred_mix > self._nis_reject_gate:
            self.kf_cv.x = x_cv_pred
            self.kf_cv.P = self._clamp_pos_cov(P_cv_pred)
            self.kf_ca.x = x_ca_pred
            self.kf_ca.P = self._clamp_pos_cov(P_ca_pred)
            self._last_nis_cv = float(nis_cv_pred)
            self._last_nis_ca = float(nis_ca_pred)
            self._last_nis_mix = float(nis_pred_mix)
            self._last_z = z.copy()
            self._predicts_since_update = 0
            if measurement_time_s is not None:
                self._last_meas_time_s = float(measurement_time_s)
            return

        # Update step
        y_cv, S_cv = self.kf_cv.update(z, meas_cov=meas_cov_update)
        y_ca, S_ca = self.kf_ca.update(z, meas_cov=meas_cov_update)
        self._sanitize_states()
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
        inflate_cv = self._inflate_cov_from_nis(self._last_nis_cv)
        inflate_ca = self._inflate_cov_from_nis(self._last_nis_ca)
        if inflate_cv > 1.0:
            self.kf_cv.P *= inflate_cv
        if inflate_ca > 1.0:
            self.kf_ca.P *= inflate_ca
        self.kf_cv.P = self._clamp_pos_cov(self.kf_cv.P)
        self.kf_ca.P = self._clamp_pos_cov(self.kf_ca.P)

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
        # Keep published merged covariance numerically stable.
        cov_merged = 0.5 * (cov_merged + cov_merged.T)
        success = False
        for k in range(6):
            jitter = (10.0 ** k) * 1e-9
            try:
                eigvals, eigvecs = np.linalg.eigh(cov_merged + np.eye(3) * jitter)
                eigvals = np.clip(eigvals, self._min_pos_var, self._max_pos_var)
                cov_merged = eigvecs @ np.diag(eigvals) @ eigvecs.T
                cov_merged = 0.5 * (cov_merged + cov_merged.T)
                if np.all(np.isfinite(cov_merged)):
                    success = True
                    break
            except np.linalg.LinAlgError:
                continue
        if not success:
            d = np.diag(cov_merged)
            d = np.nan_to_num(d, nan=self._min_pos_var, posinf=self._max_pos_var, neginf=self._min_pos_var)
            d = np.clip(d, self._min_pos_var, self._max_pos_var)
            cov_merged = np.diag(d)
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
