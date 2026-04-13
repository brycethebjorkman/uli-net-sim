"""
Gaussian Process models for GP-tracking spoofing detection and active planning.

Two GP classes:

  PropagationGP  -- learns geometry -> RSSI mapping for spoofing detection.
                    2D input: (log10(distance), altitude_difference).
                    Physics-informed mean: log-distance path loss.
                    Matern-5/2 kernel. Hyperparameters optimized via marginal likelihood.

  DeclarationGP  -- predicts future declared (RID) positions for trajectory planning.
                    Three independent scalar GPs over time (x, y, z).
                    RBF kernel with linear-extrapolation mean.
                    Sliding window of recent observations.

Both use numpy/scipy only (no external GP libraries).
"""

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import minimize
from scipy.spatial.distance import cdist


# ---------------------------------------------------------------------------
# Matern-5/2 kernel
# ---------------------------------------------------------------------------

def matern52(X1, X2, sigma_f_sq, ell):
    """Matern-5/2 covariance matrix between row-arrays X1 and X2.

    ell can be a scalar (isotropic) or per-dimension array (ARD).
    """
    ell = np.atleast_1d(np.asarray(ell, dtype=float))
    D = cdist(X1 / ell, X2 / ell, metric="euclidean")
    r = np.sqrt(5.0) * D
    K = sigma_f_sq * (1.0 + r + r**2 / 3.0) * np.exp(-r)
    return K


def rbf(X1, X2, sigma_sq, ell):
    """Squared-exponential (RBF) covariance matrix."""
    D_sq = cdist(X1, X2, metric="sqeuclidean")
    return sigma_sq * np.exp(-0.5 * D_sq / ell**2)


# ---------------------------------------------------------------------------
# PropagationGP
# ---------------------------------------------------------------------------

class PropagationGP:
    """GP model mapping (log10(distance), altitude_diff) -> RSSI (dBm).

    Mean function:  mu(u) = P0 - 10 * gamma * u[0]
    Kernel:         Matern-5/2(sigma_f^2, ell)
    Noise:          sigma_n^2

    Hyperparameters {P0, gamma, sigma_f^2, ell, sigma_n^2} are optimized
    by maximizing the log marginal likelihood via L-BFGS-B.
    """

    # Hyperparameter bounds (in raw space before transforms)
    # ell has per-dimension bounds: [ell_logd, ell_dz]
    BOUNDS = {
        "P0":         (-60.0, -10.0),
        "gamma":      (1.5, 5.0),
        "sigma_f_sq": (1.0, 100.0),
        "ell_logd":   (0.05, 5.0),
        "ell_dz":     (1.0, 200.0),
        "sigma_n_sq": (1.0, 50.0),
    }

    def __init__(
        self,
        P0: float = -35.0,
        gamma: float = 2.0,
        sigma_f_sq: float = 25.0,
        ell_logd: float = 0.3,
        ell_dz: float = 50.0,
        sigma_n_sq: float = 16.0,
        window: int | None = None,
    ):
        self.P0 = P0
        self.gamma = gamma
        self.sigma_f_sq = sigma_f_sq
        self.ell = np.array([ell_logd, ell_dz])
        self.sigma_n_sq = sigma_n_sq
        self.window = window

        # Training data
        self._U: list[np.ndarray] = []   # list of 2D feature vectors
        self._y: list[float] = []

        # Cached Cholesky factor of (K + sigma_n^2 I)
        self._cho: tuple | None = None
        self._alpha: np.ndarray | None = None  # A^{-1} (y - mu)

    @property
    def n(self) -> int:
        return len(self._y)

    # -- data management ----------------------------------------------------

    def add_observation(self, u: np.ndarray, y: float) -> None:
        """Append a training point and invalidate the cache."""
        self._U.append(np.asarray(u, dtype=float).ravel())
        self._y.append(float(y))
        if self.window is not None and len(self._y) > self.window:
            self._U.pop(0)
            self._y.pop(0)
        self._cho = None
        self._alpha = None

    # -- mean function ------------------------------------------------------

    def _mean(self, U: np.ndarray) -> np.ndarray:
        """Evaluate mean function on (N, 2) array. Returns (N,)."""
        return self.P0 - 10.0 * self.gamma * U[:, 0]

    # -- kernel + cache -----------------------------------------------------

    def _build_cache(self) -> None:
        """Compute and cache Cholesky of A = K + sigma_n^2 I, and alpha."""
        if self.n == 0:
            return
        U = np.array(self._U)
        y = np.array(self._y)
        K = matern52(U, U, self.sigma_f_sq, self.ell)
        A = K + self.sigma_n_sq * np.eye(self.n)
        self._cho = cho_factor(A)
        self._alpha = cho_solve(self._cho, y - self._mean(U))

    def _ensure_cache(self) -> None:
        if self._cho is None and self.n > 0:
            self._build_cache()

    # -- prediction ---------------------------------------------------------

    def predict(self, u_star: np.ndarray) -> tuple[float, float]:
        """Predict mean and variance at a single 2D input point."""
        u_star = np.asarray(u_star, dtype=float).reshape(1, -1)
        m, v = self.predict_batch(u_star)
        return float(m[0]), float(v[0])

    def predict_batch(self, U_star: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Predict means and variances at (M, 2) array of test points."""
        U_star = np.atleast_2d(U_star)
        mu_star = self._mean(U_star)

        if self.n == 0:
            # Prior only
            v_star = self.sigma_f_sq + self.sigma_n_sq
            return mu_star, np.full(len(U_star), v_star)

        self._ensure_cache()
        U = np.array(self._U)
        k_star = matern52(U, U_star, self.sigma_f_sq, self.ell)  # (n, M)

        # Posterior mean: mu* + k*^T A^{-1} (y - mu)
        means = mu_star + k_star.T @ self._alpha

        # Posterior variance: k** + sigma_n^2 - k*^T A^{-1} k*
        k_ss = self.sigma_f_sq + self.sigma_n_sq  # diagonal of k(u*, u*) + noise
        v = cho_solve(self._cho, k_star)  # A^{-1} k*, shape (n, M)
        variances = k_ss - np.einsum("ij,ij->j", k_star, v)
        variances = np.maximum(variances, 1e-10)

        return means, variances

    # -- variance reduction for active planning -----------------------------

    def variance_reduction(
        self, u_new: np.ndarray, U_ref: np.ndarray
    ) -> float:
        """Integrated variance reduction from hypothetically observing at u_new.

        Sums delta_v(u*) = cov(u*, u_new)^2 / v(u_new) over reference grid U_ref.
        This is independent of the observation value (GP property).
        """
        u_new = np.asarray(u_new, dtype=float).reshape(1, -1)
        U_ref = np.atleast_2d(U_ref)

        if self.n == 0:
            # Prior: cov(u*, u_new) = k(u*, u_new), v(u_new) = k(u_new, u_new) + sigma_n^2
            k_ref_new = matern52(U_ref, u_new, self.sigma_f_sq, self.ell).ravel()
            v_new = self.sigma_f_sq + self.sigma_n_sq
            return float(np.sum(k_ref_new**2) / v_new)

        self._ensure_cache()
        U = np.array(self._U)

        # Posterior covariance between reference points and u_new
        # cov(u*, u_new | D) = k(u*, u_new) - k_*^T A^{-1} k_new
        k_train_ref = matern52(U, U_ref, self.sigma_f_sq, self.ell)   # (n, M)
        k_train_new = matern52(U, u_new, self.sigma_f_sq, self.ell)   # (n, 1)
        k_ref_new = matern52(U_ref, u_new, self.sigma_f_sq, self.ell) # (M, 1)

        Ainv_k_new = cho_solve(self._cho, k_train_new)   # (n, 1)

        # Posterior covariance: c(u*, u_new) = k(u*, u_new) - k_*^T A^{-1} k_new
        c = k_ref_new.ravel() - (k_train_ref.T @ Ainv_k_new).ravel()  # (M,)

        # Posterior variance at u_new: v(u_new) = k(u_new, u_new) + sigma_n^2 - k_new^T A^{-1} k_new
        v_new = (self.sigma_f_sq + self.sigma_n_sq
                 - float((k_train_new.T @ Ainv_k_new).item()))
        v_new = max(v_new, 1e-10)

        return float(np.sum(c**2) / v_new)

    def variance_reduction_batch(
        self, U_new: np.ndarray, U_ref: np.ndarray
    ) -> np.ndarray:
        """Integrated variance reduction for multiple candidate points.

        Like variance_reduction() but precomputes shared reference-grid terms
        once, then vectorizes across all candidates.

        Parameters:
            U_new: (C, 2) candidate observation locations
            U_ref: (M, 2) reference grid

        Returns:
            (C,) array of variance reduction scores
        """
        U_new = np.atleast_2d(U_new)
        U_ref = np.atleast_2d(U_ref)

        if self.n == 0:
            k_ref_new = matern52(U_ref, U_new, self.sigma_f_sq, self.ell)
            v_new = self.sigma_f_sq + self.sigma_n_sq
            return np.sum(k_ref_new**2, axis=0) / v_new

        self._ensure_cache()
        U = np.array(self._U)

        # Reference-grid kernel (shared across all candidates, computed once)
        k_train_ref = matern52(U, U_ref, self.sigma_f_sq, self.ell)  # (n, M)

        # Candidate kernels (vectorized over C candidates)
        k_train_new = matern52(U, U_new, self.sigma_f_sq, self.ell)   # (n, C)
        k_ref_new = matern52(U_ref, U_new, self.sigma_f_sq, self.ell) # (M, C)
        Ainv_k_new = cho_solve(self._cho, k_train_new)                # (n, C)

        # Posterior covariance: c = k(ref, new) - k_ref^T A^{-1} k_new
        c = k_ref_new - k_train_ref.T @ Ainv_k_new  # (M, C)

        # Posterior variance at each candidate
        k_ss = self.sigma_f_sq + self.sigma_n_sq
        v_new = k_ss - np.einsum("ij,ij->j", k_train_new, Ainv_k_new)  # (C,)
        v_new = np.maximum(v_new, 1e-10)

        return np.sum(c**2, axis=0) / v_new

    # -- hyperparameter optimization ----------------------------------------

    def _log_marginal_likelihood(self, theta: np.ndarray) -> float:
        """Negative log marginal likelihood (for minimization)."""
        P0, gamma, sigma_f_sq, ell_logd, ell_dz, sigma_n_sq = theta
        ell = np.array([ell_logd, ell_dz])

        U = np.array(self._U)
        y = np.array(self._y)
        mu = P0 - 10.0 * gamma * U[:, 0]
        r = y - mu

        K = matern52(U, U, sigma_f_sq, ell)
        A = K + sigma_n_sq * np.eye(self.n)

        try:
            L = cho_factor(A)
            alpha = cho_solve(L, r)
            logdet = 2.0 * np.sum(np.log(np.diag(L[0])))
        except np.linalg.LinAlgError:
            return 1e12

        nll = 0.5 * r @ alpha + 0.5 * logdet + 0.5 * self.n * np.log(2.0 * np.pi)
        return float(nll)

    def optimize_hyperparameters(self, max_iter: int = 50) -> float:
        """Optimize hyperparameters via L-BFGS-B. Returns final neg-log-likelihood."""
        if self.n < 3:
            return float("nan")

        theta0 = np.array([
            self.P0, self.gamma, self.sigma_f_sq,
            self.ell[0], self.ell[1], self.sigma_n_sq
        ])
        bounds = [
            self.BOUNDS["P0"],
            self.BOUNDS["gamma"],
            self.BOUNDS["sigma_f_sq"],
            self.BOUNDS["ell_logd"],
            self.BOUNDS["ell_dz"],
            self.BOUNDS["sigma_n_sq"],
        ]

        result = minimize(
            self._log_marginal_likelihood,
            theta0,
            method="L-BFGS-B",
            bounds=bounds,
            options={"maxiter": max_iter, "ftol": 1e-6},
        )

        self.P0 = result.x[0]
        self.gamma = result.x[1]
        self.sigma_f_sq = result.x[2]
        self.ell = np.array([result.x[3], result.x[4]])
        self.sigma_n_sq = result.x[5]
        self._cho = None
        self._alpha = None
        return float(result.fun)

    def log_marginal_likelihood(self) -> float:
        """Current log marginal likelihood (positive convention)."""
        if self.n < 2:
            return float("nan")
        theta = np.array([
            self.P0, self.gamma, self.sigma_f_sq,
            self.ell[0], self.ell[1], self.sigma_n_sq
        ])
        return -self._log_marginal_likelihood(theta)


# ---------------------------------------------------------------------------
# DeclarationGP
# ---------------------------------------------------------------------------

class DeclarationGP:
    """Predicts future declared (RID) positions from recent trajectory history.

    Three independent scalar GPs over time (one per spatial coordinate).
    Uses a sliding window of the last N_g observations and a linear-
    extrapolation mean function.
    """

    def __init__(self, window: int = 15, ell: float = 5.0, sigma_sq: float = 100.0,
                 sigma_n_sq: float = 1.0):
        self.window = window
        self.ell = ell
        self.sigma_sq = sigma_sq
        self.sigma_n_sq = sigma_n_sq

        self._times: list[float] = []
        self._positions: list[np.ndarray] = []  # each is (3,)

    @property
    def n(self) -> int:
        return len(self._times)

    def add_observation(self, t: float, pos: np.ndarray) -> None:
        """Record a declared position at time t."""
        self._times.append(float(t))
        self._positions.append(np.asarray(pos, dtype=float).ravel()[:3])

    def _window_data(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (times, positions) arrays for the sliding window."""
        start = max(0, self.n - self.window)
        t = np.array(self._times[start:])
        p = np.array(self._positions[start:])
        return t, p

    def _linear_mean(self, t_train: np.ndarray, p_train: np.ndarray,
                     t_star: np.ndarray) -> np.ndarray:
        """Linear extrapolation mean from the last two training points.

        Returns (len(t_star), 3) array.
        """
        n = len(t_train)
        if n < 2:
            # Constant mean from the only point
            return np.tile(p_train[-1], (len(t_star), 1))

        dt = t_train[-1] - t_train[-2]
        if abs(dt) < 1e-9:
            return np.tile(p_train[-1], (len(t_star), 1))

        vel = (p_train[-1] - p_train[-2]) / dt
        dt_star = t_star - t_train[-1]
        return p_train[-1][None, :] + dt_star[:, None] * vel[None, :]

    def _predict_axis(self, t_train: np.ndarray, y_train: np.ndarray,
                      mu_train: np.ndarray, mu_star: np.ndarray,
                      t_star: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """GP prediction for one coordinate axis."""
        T = t_train.reshape(-1, 1)
        T_star = t_star.reshape(-1, 1)
        r = y_train - mu_train

        K = rbf(T, T, self.sigma_sq, self.ell)
        A = K + self.sigma_n_sq * np.eye(len(T))

        try:
            L = cho_factor(A)
        except np.linalg.LinAlgError:
            return mu_star, np.full(len(t_star), self.sigma_sq + self.sigma_n_sq)

        k_star = rbf(T, T_star, self.sigma_sq, self.ell)
        alpha = cho_solve(L, r)

        means = mu_star + k_star.T @ alpha
        k_ss = self.sigma_sq + self.sigma_n_sq
        v = cho_solve(L, k_star)
        variances = k_ss - np.einsum("ij,ij->j", k_star, v)
        variances = np.maximum(variances, 1e-10)

        return means.ravel(), variances.ravel()

    def predict(self, t_star: float) -> tuple[np.ndarray, np.ndarray]:
        """Predict declared position at a future time.

        Returns (mean_3d, var_3d) where each is shape (3,).
        """
        if self.n == 0:
            return np.zeros(3), np.full(3, self.sigma_sq + self.sigma_n_sq)

        t_train, p_train = self._window_data()
        t_arr = np.array([t_star])
        mu_all = self._linear_mean(t_train, p_train, np.concatenate([t_train, t_arr]))
        mu_train = mu_all[:len(t_train)]
        mu_star = mu_all[len(t_train):]

        mean_3d = np.zeros(3)
        var_3d = np.zeros(3)
        for j in range(3):
            m, v = self._predict_axis(
                t_train, p_train[:, j], mu_train[:, j], mu_star[:, j], t_arr
            )
            mean_3d[j] = m[0]
            var_3d[j] = v[0]

        return mean_3d, var_3d

    def sample(self, t_star: float, n_samples: int, rng: np.random.Generator | None = None
               ) -> np.ndarray:
        """Draw n_samples from the predictive distribution at t_star.

        Returns (n_samples, 3) array.
        """
        if rng is None:
            rng = np.random.default_rng()

        mean, var = self.predict(t_star)
        std = np.sqrt(var)
        samples = rng.normal(mean, std, size=(n_samples, 3))
        return samples
