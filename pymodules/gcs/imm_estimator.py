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

    def update(self, z):
        z = np.asarray(z, dtype=float).ravel()
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        K = self.P @ self.H.T @ np.linalg.inv(S)
        self.x = self.x + K @ y
        I = np.eye(len(self.x))
        self.P = (I - K @ self.H) @ self.P
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

    def __init__(self, dt: float = 1.0):
        self.kf_cv = KalmanFilter3D.create_cv(dt)
        self.kf_ca = KalmanFilter3D.create_ca(dt)
        self.mu = np.array([0.6, 0.4])  # prefer CV (spoofer likely steady)
        self.pi = np.array([[0.95, 0.05],
                            [0.05, 0.95]])
        self._initialized = False

    def update(self, z: np.ndarray):
        """Predict-then-update cycle, called when a new measurement arrives."""
        z = np.asarray(z, dtype=float).ravel()[:3]
        if not self._initialized:
            self.kf_cv.x[:3] = z
            self.kf_ca.x[:3] = z
            self._initialized = True
            return

        # Predict step (only right before measurement)
        self.kf_cv.predict()
        self.kf_ca.predict()
        self.mu = self.pi.T @ self.mu
        self.mu /= self.mu.sum()

        # Update step
        y_cv, S_cv = self.kf_cv.update(z)
        y_ca, S_ca = self.kf_ca.update(z)

        L_cv = self._gaussian_likelihood(y_cv, S_cv)
        L_ca = self._gaussian_likelihood(y_ca, S_ca)

        c = self.mu[0] * L_cv + self.mu[1] * L_ca
        if c > 1e-300:
            self.mu[0] = self.mu[0] * L_cv / c
            self.mu[1] = self.mu[1] * L_ca / c

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

    @staticmethod
    def _gaussian_likelihood(y, S):
        n = len(y)
        sign, logdet = np.linalg.slogdet(S)
        if sign <= 0:
            return 1e-300
        exp_term = -0.5 * y @ np.linalg.inv(S) @ y
        log_L = -0.5 * n * np.log(2 * np.pi) - 0.5 * logdet + exp_term
        return max(np.exp(log_L), 1e-300)
