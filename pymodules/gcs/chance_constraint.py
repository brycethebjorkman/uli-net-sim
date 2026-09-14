"""
Chance-constrained unsafe region from spoofer state estimate (Sec. VI-A).

Given spoofer state x_s ~ N(mu_s, Sigma_s), enforce:
    (x_t - mu_t)^T Sigma_t^{-1} (x_t - mu_t) > F^{-1}_{chi^2_3}(1 - alpha)

Satisfaction guarantees Pr(collision) <= alpha (Eq. 24-25 in paper).
"""

import numpy as np
from scipy.stats import chi2


def ellipsoid_threshold(alpha: float = 0.05, ndim: int = 3) -> float:
    """Inverse CDF of chi-squared distribution: F^{-1}_{chi^2_ndim}(1 - alpha)."""
    return float(chi2.ppf(1.0 - alpha, df=ndim))


def mahalanobis_squared(x: np.ndarray, mu: np.ndarray, sigma: np.ndarray) -> float:
    """Squared Mahalanobis distance: (x - mu)^T Sigma^{-1} (x - mu)."""
    x = np.asarray(x, dtype=float).ravel()[:3]
    mu = np.asarray(mu, dtype=float).ravel()[:3]
    sigma = np.asarray(sigma, dtype=float)
    diff = x - mu
    try:
        return float(diff @ np.linalg.inv(sigma) @ diff)
    except np.linalg.LinAlgError:
        return 0.0


def is_safe(x: np.ndarray, mu: np.ndarray, sigma: np.ndarray, alpha: float = 0.05) -> bool:
    """True if position x is outside the (1-alpha) confidence ellipsoid."""
    threshold = ellipsoid_threshold(alpha, ndim=3)
    return mahalanobis_squared(x, mu, sigma) > threshold


def unsafe_region_to_dict(mu: np.ndarray, sigma: np.ndarray, alpha: float = 0.05) -> dict:
    """Serialize unsafe region for GCS broadcast."""
    return {
        "mu": mu.tolist(),
        "sigma": sigma.tolist(),
        "alpha": alpha,
        "threshold": ellipsoid_threshold(alpha, ndim=3),
    }
