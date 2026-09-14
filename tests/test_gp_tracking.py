"""
Unit tests for the GP-tracking components (PropagationGP, DeclarationGP, CUSUM).

Tests the math in isolation without running OMNeT++ simulations.
"""

import numpy as np
import pytest

from pymodules.gcs.gaussian_process import PropagationGP, DeclarationGP, matern52, rbf


# ---------------------------------------------------------------------------
# Matern-5/2 kernel
# ---------------------------------------------------------------------------

class TestMatern52Kernel:
    def test_self_covariance(self):
        """k(u, u) = sigma_f^2."""
        X = np.array([[1.0, 2.0]])
        K = matern52(X, X, sigma_f_sq=25.0, ell=0.3)
        assert K.shape == (1, 1)
        assert abs(K[0, 0] - 25.0) < 1e-10

    def test_symmetry(self):
        rng = np.random.default_rng(42)
        X = rng.standard_normal((5, 2))
        K = matern52(X, X, sigma_f_sq=10.0, ell=0.5)
        np.testing.assert_allclose(K, K.T, atol=1e-12)

    def test_positive_semidefinite(self):
        rng = np.random.default_rng(42)
        X = rng.standard_normal((10, 2))
        K = matern52(X, X, sigma_f_sq=10.0, ell=0.5)
        eigvals = np.linalg.eigvalsh(K)
        assert np.all(eigvals >= -1e-10)

    def test_decays_with_distance(self):
        """Covariance should decrease as distance increases."""
        X1 = np.array([[0.0, 0.0]])
        near = np.array([[0.1, 0.0]])
        far = np.array([[2.0, 0.0]])
        k_near = matern52(X1, near, sigma_f_sq=10.0, ell=0.5)[0, 0]
        k_far = matern52(X1, far, sigma_f_sq=10.0, ell=0.5)[0, 0]
        assert k_near > k_far

    def test_positivity(self):
        rng = np.random.default_rng(42)
        X1 = rng.standard_normal((5, 2))
        X2 = rng.standard_normal((3, 2))
        K = matern52(X1, X2, sigma_f_sq=10.0, ell=0.5)
        assert np.all(K > 0)


# ---------------------------------------------------------------------------
# RBF kernel
# ---------------------------------------------------------------------------

class TestRBFKernel:
    def test_self_covariance(self):
        X = np.array([[1.0]])
        K = rbf(X, X, sigma_sq=5.0, ell=1.0)
        assert abs(K[0, 0] - 5.0) < 1e-10

    def test_symmetry(self):
        rng = np.random.default_rng(42)
        X = rng.standard_normal((5, 1))
        K = rbf(X, X, sigma_sq=5.0, ell=1.0)
        np.testing.assert_allclose(K, K.T, atol=1e-12)


# ---------------------------------------------------------------------------
# PropagationGP
# ---------------------------------------------------------------------------

def _make_synthetic_data(rng, n=50, P0=-35.0, gamma=2.0, noise_std=3.0):
    """Generate synthetic RSSI data from a log-distance path loss model."""
    log_d = rng.uniform(0.5, 2.5, n)
    dz = rng.uniform(-80, 80, n)
    U = np.column_stack([log_d, dz])
    y = P0 - 10.0 * gamma * log_d + rng.normal(0, noise_std, n)
    return U, y


class TestPropagationGP:
    def test_prior_prediction(self):
        """With no data, predict returns prior mean and variance."""
        gp = PropagationGP(P0=-35.0, gamma=2.0, sigma_f_sq=25.0, sigma_n_sq=16.0)
        u = np.array([1.5, 10.0])
        m, v = gp.predict(u)
        expected_mean = -35.0 - 10.0 * 2.0 * 1.5
        assert abs(m - expected_mean) < 1e-10
        assert abs(v - (25.0 + 16.0)) < 1e-10

    def test_prediction_converges(self):
        """With sufficient data from the true model, predictions are accurate."""
        rng = np.random.default_rng(42)
        U, y = _make_synthetic_data(rng, n=80, noise_std=3.0)

        gp = PropagationGP(P0=-35.0, gamma=2.0, sigma_f_sq=25.0,
                           ell_logd=0.3, ell_dz=50.0, sigma_n_sq=9.0)
        for i in range(len(U)):
            gp.add_observation(U[i], y[i])

        # Test at several points
        test_U = np.array([[1.0, 0.0], [1.5, 20.0], [2.0, -30.0]])
        true_mean = -35.0 - 10.0 * 2.0 * test_U[:, 0]

        pred_m, pred_v = gp.predict_batch(test_U)

        # Predictions should be within ~2 noise stds of true mean
        np.testing.assert_allclose(pred_m, true_mean, atol=8.0)
        # Variance should be much less than prior
        assert np.all(pred_v < 25.0 + 16.0)

    def test_variance_decreases_with_data(self):
        """Adding observations should reduce predictive variance."""
        rng = np.random.default_rng(42)
        gp = PropagationGP()
        u_test = np.array([1.5, 0.0])

        _, v_prior = gp.predict(u_test)

        # Add 20 observations
        U, y = _make_synthetic_data(rng, n=20)
        for i in range(len(U)):
            gp.add_observation(U[i], y[i])

        _, v_after = gp.predict(u_test)
        assert v_after < v_prior

    def test_hyperparameter_optimization(self):
        """Optimizing hyperparameters should improve log marginal likelihood."""
        rng = np.random.default_rng(42)
        gp = PropagationGP(P0=-30.0, gamma=3.0, sigma_f_sq=50.0,
                           ell_logd=1.0, ell_dz=100.0, sigma_n_sq=25.0)

        U, y = _make_synthetic_data(rng, n=40, P0=-35.0, gamma=2.0, noise_std=3.0)
        for i in range(len(U)):
            gp.add_observation(U[i], y[i])

        lml_before = gp.log_marginal_likelihood()
        gp.optimize_hyperparameters()
        lml_after = gp.log_marginal_likelihood()

        assert lml_after > lml_before

    def test_optimized_params_near_true(self):
        """After optimization, params should be close to the generating model."""
        rng = np.random.default_rng(42)
        true_P0, true_gamma = -35.0, 2.0
        gp = PropagationGP(P0=-30.0, gamma=3.0, sigma_f_sq=50.0,
                           ell_logd=1.0, ell_dz=100.0, sigma_n_sq=25.0)

        U, y = _make_synthetic_data(rng, n=100, P0=true_P0, gamma=true_gamma,
                                    noise_std=3.0)
        for i in range(len(U)):
            gp.add_observation(U[i], y[i])

        gp.optimize_hyperparameters(max_iter=100)

        assert abs(gp.P0 - true_P0) < 5.0
        assert abs(gp.gamma - true_gamma) < 1.0

    def test_batch_matches_single(self):
        """predict_batch results match individual predict calls."""
        rng = np.random.default_rng(42)
        gp = PropagationGP()
        U, y = _make_synthetic_data(rng, n=20)
        for i in range(len(U)):
            gp.add_observation(U[i], y[i])

        test_U = np.array([[1.0, 0.0], [1.5, 20.0], [2.0, -30.0]])
        batch_m, batch_v = gp.predict_batch(test_U)

        for i in range(len(test_U)):
            m, v = gp.predict(test_U[i])
            assert abs(m - batch_m[i]) < 1e-10
            assert abs(v - batch_v[i]) < 1e-10


# ---------------------------------------------------------------------------
# Variance reduction
# ---------------------------------------------------------------------------

class TestVarianceReduction:
    def _make_trained_gp(self, n=30):
        rng = np.random.default_rng(42)
        gp = PropagationGP()
        U, y = _make_synthetic_data(rng, n=n)
        for i in range(len(U)):
            gp.add_observation(U[i], y[i])
        return gp

    def test_nonnegative(self):
        """Variance reduction must be non-negative."""
        gp = self._make_trained_gp()
        U_ref = np.array([[1.0, 0.0], [1.5, 50.0], [2.0, -50.0]])
        u_new = np.array([1.2, 20.0])
        vr = gp.variance_reduction(u_new, U_ref)
        assert vr >= 0.0

    def test_positive_at_unexplored_region(self):
        """Variance reduction should be positive when observing in a new region."""
        gp = self._make_trained_gp()
        # Reference grid spanning the full range
        log_d = np.linspace(0.5, 2.7, 5)
        dz = np.linspace(-100, 100, 5)
        U_ref = np.array([[ld, z] for ld in log_d for z in dz])

        u_new = np.array([0.6, -90.0])  # edge of range, likely unexplored
        vr = gp.variance_reduction(u_new, U_ref)
        assert vr > 0.01

    def test_diminishes_with_redundancy(self):
        """Adding a point near existing data yields less reduction than a distant point."""
        rng = np.random.default_rng(42)
        gp = PropagationGP()
        # Cluster training data around log_d=1.5, dz=0
        for _ in range(20):
            u = np.array([1.5 + rng.normal(0, 0.05), rng.normal(0, 5)])
            y = -35.0 - 20.0 * u[0] + rng.normal(0, 3)
            gp.add_observation(u, y)

        U_ref = np.array([[1.0, 0.0], [1.5, 0.0], [2.0, 0.0], [2.5, 0.0]])

        # Redundant point (near cluster)
        vr_near = gp.variance_reduction(np.array([1.5, 0.0]), U_ref)
        # Novel point (far from cluster)
        vr_far = gp.variance_reduction(np.array([2.5, 0.0]), U_ref)

        assert vr_far > vr_near

    def test_works_with_no_data(self):
        """Variance reduction from prior should be well-defined."""
        gp = PropagationGP()
        U_ref = np.array([[1.0, 0.0], [2.0, 0.0]])
        u_new = np.array([1.5, 0.0])
        vr = gp.variance_reduction(u_new, U_ref)
        assert vr >= 0.0
        assert np.isfinite(vr)

    def test_batch_matches_individual(self):
        """variance_reduction_batch matches individual calls."""
        gp = self._make_trained_gp()
        U_ref = np.array([[1.0, 0.0], [1.5, 50.0], [2.0, -50.0]])
        U_new = np.array([[1.2, 20.0], [0.8, -30.0], [2.5, 0.0]])

        batch_scores = gp.variance_reduction_batch(U_new, U_ref)
        individual_scores = [gp.variance_reduction(u, U_ref) for u in U_new]

        np.testing.assert_allclose(batch_scores, individual_scores, rtol=1e-10)

    def test_batch_works_with_no_data(self):
        """Batch variance reduction from prior matches individual."""
        gp = PropagationGP()
        U_ref = np.array([[1.0, 0.0], [2.0, 0.0]])
        U_new = np.array([[1.5, 0.0], [0.8, 10.0]])

        batch_scores = gp.variance_reduction_batch(U_new, U_ref)
        individual_scores = [gp.variance_reduction(u, U_ref) for u in U_new]

        np.testing.assert_allclose(batch_scores, individual_scores, rtol=1e-10)


class TestPropagationGPWindow:
    def test_window_limits_observations(self):
        """With a window, old observations are dropped."""
        gp = PropagationGP(window=10)
        rng = np.random.default_rng(42)
        for i in range(25):
            u = np.array([rng.uniform(0.5, 2.5), rng.uniform(-80, 80)])
            y = -35.0 - 20.0 * u[0] + rng.normal(0, 3)
            gp.add_observation(u, y)

        assert gp.n == 10

    def test_window_none_keeps_all(self):
        """With window=None, all observations are retained."""
        gp = PropagationGP(window=None)
        rng = np.random.default_rng(42)
        for i in range(25):
            u = np.array([rng.uniform(0.5, 2.5), rng.uniform(-80, 80)])
            gp.add_observation(u, -50.0)

        assert gp.n == 25

    def test_window_prediction_valid(self):
        """Prediction still works correctly after window truncation."""
        gp = PropagationGP(window=15)
        rng = np.random.default_rng(42)
        for i in range(30):
            u = np.array([rng.uniform(0.5, 2.5), rng.uniform(-80, 80)])
            y = -35.0 - 20.0 * u[0] + rng.normal(0, 3)
            gp.add_observation(u, y)

        m, v = gp.predict(np.array([1.5, 0.0]))
        assert np.isfinite(m)
        assert v > 0


# ---------------------------------------------------------------------------
# CUSUM logic (standalone, not yet in a class)
# ---------------------------------------------------------------------------

class TestCUSUM:
    @staticmethod
    def _run_cusum(s_values, beta=1.5, h=8.0):
        """Run CUSUM on a sequence of standardized squared errors."""
        C = 0.0
        cusum_trace = []
        triggered = False
        trigger_idx = None
        for i, s in enumerate(s_values):
            C = max(0.0, C + s - beta)
            cusum_trace.append(C)
            if C > h and not triggered:
                triggered = True
                trigger_idx = i
        return cusum_trace, triggered, trigger_idx

    def test_honest_stays_below_threshold(self):
        """Under honest conditions (s ~ chi2(1)), CUSUM should rarely trigger."""
        rng = np.random.default_rng(42)
        # chi-squared(1) has mean=1, so s_k - beta has negative mean.
        # With beta=2.0, h=20.0, false alarm rate over 300 steps is very low.
        n_trials = 50
        triggers = 0
        for _ in range(n_trials):
            s = rng.chisquare(df=1, size=300)
            _, triggered, _ = self._run_cusum(s, beta=2.0, h=20.0)
            if triggered:
                triggers += 1
        # False alarm rate should be low (< 10%)
        assert triggers / n_trials < 0.10

    def test_spoofed_triggers(self):
        """With inflated errors, CUSUM should trigger quickly."""
        rng = np.random.default_rng(42)
        # Spoofing: mean of s_k >> 1 (e.g., noncentral chi-squared)
        delta_sq = 10.0  # strong bias
        s = rng.chisquare(df=1, size=300) + delta_sq
        _, triggered, trigger_idx = self._run_cusum(s, beta=2.0, h=20.0)
        assert triggered
        assert trigger_idx < 10  # should trigger within first few steps

    def test_cusum_resets_after_honest_period(self):
        """CUSUM should drift back to zero during honest periods."""
        rng = np.random.default_rng(42)
        # 50 honest steps
        s_honest = rng.chisquare(df=1, size=50)
        trace, _, _ = self._run_cusum(s_honest, beta=2.0, h=100.0)
        # After 50 honest steps, CUSUM should be near zero
        assert trace[-1] < 5.0


# ---------------------------------------------------------------------------
# DeclarationGP
# ---------------------------------------------------------------------------

class TestDeclarationGP:
    def test_linear_trajectory_prediction(self):
        """On a linear trajectory, one-step-ahead prediction should be accurate."""
        gp = DeclarationGP(window=15, ell=5.0, sigma_sq=100.0, sigma_n_sq=0.1)
        vel = np.array([10.0, 5.0, -2.0])
        p0 = np.array([100.0, 200.0, 50.0])

        for k in range(20):
            t = float(k)
            pos = p0 + vel * t
            gp.add_observation(t, pos)

        # Predict one step ahead
        t_next = 20.0
        mean, var = gp.predict(t_next)
        expected = p0 + vel * t_next

        np.testing.assert_allclose(mean, expected, atol=2.0)
        # Variance should be small for a well-observed linear trajectory
        assert np.all(var < 10.0)

    def test_sample_shape(self):
        """Samples have correct shape."""
        gp = DeclarationGP()
        for k in range(5):
            gp.add_observation(float(k), np.array([k * 10.0, k * 5.0, 50.0]))

        samples = gp.sample(5.0, 10, rng=np.random.default_rng(42))
        assert samples.shape == (10, 3)

    def test_empty_gp(self):
        """Prediction with no data returns prior."""
        gp = DeclarationGP(sigma_sq=100.0, sigma_n_sq=1.0)
        mean, var = gp.predict(1.0)
        np.testing.assert_array_equal(mean, np.zeros(3))
        assert np.all(var > 0)

    def test_single_observation(self):
        """With one observation, mean should be close to that point."""
        gp = DeclarationGP(sigma_sq=100.0, sigma_n_sq=0.1)
        gp.add_observation(0.0, np.array([10.0, 20.0, 30.0]))
        mean, _ = gp.predict(0.0)
        np.testing.assert_allclose(mean, [10.0, 20.0, 30.0], atol=1.0)

    def test_sliding_window(self):
        """Only the last N_g observations should influence predictions."""
        gp = DeclarationGP(window=5, ell=2.0, sigma_sq=100.0, sigma_n_sq=0.1)

        # Add 10 observations at wildly different positions
        for k in range(5):
            gp.add_observation(float(k), np.array([1000.0, 1000.0, 1000.0]))
        for k in range(5, 10):
            gp.add_observation(float(k), np.array([0.0, 0.0, 0.0]))

        # Prediction near recent data should be near zero, not near 1000
        mean, _ = gp.predict(10.0)
        assert np.all(np.abs(mean) < 50.0)

    def test_curved_trajectory(self):
        """On a smoothly curving trajectory, prediction should still be reasonable."""
        gp = DeclarationGP(window=15, ell=5.0, sigma_sq=200.0, sigma_n_sq=0.1)

        for k in range(20):
            t = float(k)
            pos = np.array([
                100.0 * np.cos(0.1 * t),
                100.0 * np.sin(0.1 * t),
                50.0,
            ])
            gp.add_observation(t, pos)

        t_next = 20.0
        mean, _ = gp.predict(t_next)
        expected = np.array([
            100.0 * np.cos(0.1 * t_next),
            100.0 * np.sin(0.1 * t_next),
            50.0,
        ])
        # Curved trajectory prediction won't be perfect but should be in the ballpark
        np.testing.assert_allclose(mean, expected, atol=20.0)
