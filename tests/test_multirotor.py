"""
Regression tests for MultirotorMobility 6-DoF dynamics.

Runs HoverTest and FreefallTest configs from simulations/multirotor_test/,
exports mobility and beacon vectors, and verifies:
  - Hover: position constant, thrust = m*g, angles/rates zero
  - Freefall: z follows analytical z(t) = z0 - 0.5*g*t^2, thrust = 0

To update hashes after intentional changes:
    pytest tests/test_multirotor.py -v
"""

import json
import subprocess
import shutil
import tempfile
from pathlib import Path

import pytest

from .conftest import (RUN_SH, extract_our_vectors, diff_vector_hashes)
from datagen.vec2parquet import hash_vector_data

GRAVITY = 9.81
REPO_ROOT = Path(__file__).parent.parent
TEST_OUT = Path(__file__).parent / "out" / "multirotor"
SIM_INI = REPO_ROOT / "simulations" / "multirotor_test" / "omnetpp.ini"
EXPECTED_DIR = Path(__file__).parent / "expected_hashes"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_sim(config: str, result_dir: Path):
    """Run one multirotor_test config."""
    result_dir.mkdir(parents=True, exist_ok=True)
    args = [str(RUN_SH), "-f", str(SIM_INI), "-c", config,
            "-r", str(result_dir), "-q"]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Simulation {config} failed:\n{r.stderr[-2000:]}")
    return result_dir / f"{config}-#0.vec"


def _get_vector(vectors: dict, module_suffix: str, name: str):
    """Get (times, values) for a vector matching module suffix and name."""
    for (mod, n), (times, vals) in vectors.items():
        if mod.endswith(module_suffix) and n == name:
            return times, vals
    raise KeyError(f"Vector not found: module=*{module_suffix}, name={name}")


def _value_at_time(times, values, target_t, tol=0.01):
    """Find the value closest to target_t within tolerance."""
    best_idx = min(range(len(times)), key=lambda i: abs(times[i] - target_t))
    if abs(times[best_idx] - target_t) > tol:
        raise ValueError(f"No sample near t={target_t} (closest: {times[best_idx]})")
    return values[best_idx]


def _load_expected(name: str) -> dict:
    """Load expected hashes from JSON file."""
    path = EXPECTED_DIR / f"{name}.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _hash_all_vectors(vectors: dict) -> dict:
    """Compute per-vector hashes, keyed by 'module||name'."""
    return {f"{mod}||{name}": hash_vector_data(times, values)
            for (mod, name), (times, values) in vectors.items()}


def _check_hashes(vectors: dict, expected_file: str, label: str):
    """Compare extracted vectors against expected hashes, fail with diff."""
    actual = _hash_all_vectors(vectors)
    expected = _load_expected(expected_file)
    if not expected:
        pytest.fail(f"{label} hashes (create {expected_file}.json):\n"
                    f"{json.dumps(actual, indent=2, sort_keys=True)}")
    if actual != expected:
        diff = diff_vector_hashes(expected, actual)
        pytest.fail(f"{label} vector hashes changed:\n{diff}")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def hover_outputs():
    """Run HoverTest and export vectors."""
    out = TEST_OUT / "hover"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("HoverTest", result_dir)
    vectors = extract_our_vectors(vec_file)

    return {
        "vec_file": vec_file,
        "vectors": vectors,
    }


@pytest.fixture(scope="session")
def freefall_outputs():
    """Run FreefallTest and export vectors."""
    out = TEST_OUT / "freefall"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("FreefallTest", result_dir)
    vectors = extract_our_vectors(vec_file)

    return {
        "vec_file": vec_file,
        "vectors": vectors,
    }


# ---------------------------------------------------------------------------
# Hash-based regression (catches any change in dynamics output)
# ---------------------------------------------------------------------------

def test_hover_vec_hashes(hover_outputs):
    _check_hashes(hover_outputs["vectors"], "hover", "Hover")


def test_freefall_vec_hashes(freefall_outputs):
    _check_hashes(freefall_outputs["vectors"], "freefall", "Freefall")


# ---------------------------------------------------------------------------
# Hover physics tests
# ---------------------------------------------------------------------------

def test_hover_thrust_equals_mg(hover_outputs):
    """Thrust should be m*g = 5 * 9.81 = 49.05 N throughout."""
    times, values = _get_vector(hover_outputs["vectors"],
                                "host[0].mobility", "thrust:vector")
    expected_thrust = 5.0 * GRAVITY
    for v in values:
        assert abs(v - expected_thrust) < 1e-6, f"Thrust {v} != {expected_thrust}"


def test_hover_position_constant(hover_outputs):
    """Host 0 should stay at (100, 100, 50) and host 1 at (200, 200, 80)."""
    vectors = hover_outputs["vectors"]

    for host_idx, (ex, ey, ez) in [(0, (100, 100, 50)), (1, (200, 200, 80))]:
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        for coord, expected in [("Transmission My X Coordinate", ex),
                                ("Transmission My Y Coordinate", ey),
                                ("Transmission My Z Coordinate", ez)]:
            times, values = _get_vector(vectors, suffix, coord)
            for i, v in enumerate(values):
                assert abs(v - expected) < 1e-3, \
                    f"host[{host_idx}] {coord} at t={times[i]}: {v} != {expected}"


def test_hover_angles_zero(hover_outputs):
    """All Euler angles and angular rates should remain zero."""
    vectors = hover_outputs["vectors"]
    for signal in ["phi:vector", "theta:vector", "psi:vector",
                   "omegaP:vector", "omegaQ:vector", "omegaR:vector"]:
        times, values = _get_vector(vectors, "host[0].mobility", signal)
        for v in values:
            assert abs(v) < 1e-10, f"{signal}: got {v}, expected 0"


def test_hover_torques_zero(hover_outputs):
    """All torques should be zero during hover."""
    vectors = hover_outputs["vectors"]
    for signal in ["tauPhi:vector", "tauTheta:vector", "tauPsi:vector"]:
        times, values = _get_vector(vectors, "host[0].mobility", signal)
        for v in values:
            assert abs(v) < 1e-10, f"{signal}: got {v}, expected 0"


# ---------------------------------------------------------------------------
# Freefall physics tests
# ---------------------------------------------------------------------------

def test_freefall_thrust_zero(freefall_outputs):
    """Thrust should be zero throughout freefall."""
    times, values = _get_vector(freefall_outputs["vectors"],
                                "host[0].mobility", "thrust:vector")
    for v in values:
        assert v == 0.0, f"Thrust {v} != 0"


def test_freefall_z_analytical(freefall_outputs):
    """Z position should follow z(t) = 100 - 0.5 * g * t^2."""
    vectors = freefall_outputs["vectors"]
    times, values = _get_vector(vectors, "host[0].wlan[0].mgmt",
                                "Transmission My Z Coordinate")

    for t, z_actual in zip(times, values):
        z_expected = 100.0 - 0.5 * GRAVITY * t * t
        assert abs(z_actual - z_expected) < 0.05, \
            f"Freefall z at t={t:.3f}: {z_actual:.3f} != {z_expected:.3f} (analytical)"


def test_freefall_xy_constant(freefall_outputs):
    """X and Y should remain at 0 during freefall (no lateral forces)."""
    vectors = freefall_outputs["vectors"]
    for coord in ["Transmission My X Coordinate",
                  "Transmission My Y Coordinate"]:
        times, values = _get_vector(vectors, "host[0].wlan[0].mgmt", coord)
        for v in values:
            assert abs(v) < 1e-3, f"{coord}: {v} != 0"


def test_freefall_angles_zero(freefall_outputs):
    """No rotation should occur during pure freefall."""
    vectors = freefall_outputs["vectors"]
    for signal in ["phi:vector", "theta:vector", "psi:vector",
                   "omegaP:vector", "omegaQ:vector", "omegaR:vector"]:
        times, values = _get_vector(vectors, "host[0].mobility", signal)
        for v in values:
            assert abs(v) < 1e-10, f"{signal}: got {v}, expected 0"


def test_freefall_z_checkpoints(freefall_outputs):
    """Verify specific z values at t=1, 2, 3 against analytical solution."""
    vectors = freefall_outputs["vectors"]
    times, values = _get_vector(vectors, "host[0].wlan[0].mgmt",
                                "Transmission My Z Coordinate")

    checkpoints = {
        1.0: 100.0 - 0.5 * GRAVITY * 1.0,   # 95.095
        2.0: 100.0 - 0.5 * GRAVITY * 4.0,   # 80.38
        3.0: 100.0 - 0.5 * GRAVITY * 9.0,   # 55.855
    }

    for target_t, expected_z in checkpoints.items():
        z_actual = _value_at_time(times, values, target_t, tol=0.05)
        assert abs(z_actual - expected_z) < 0.1, \
            f"z(t={target_t}): {z_actual:.3f} != {expected_z:.3f}"


# ---------------------------------------------------------------------------
# Signal recording completeness
# ---------------------------------------------------------------------------

def test_hover_all_signals_recorded(hover_outputs):
    """All 10 MultirotorMobility signals should be present for each host."""
    expected_signals = {"thrust:vector", "tauPhi:vector", "tauTheta:vector",
                        "tauPsi:vector", "phi:vector", "theta:vector",
                        "psi:vector", "omegaP:vector", "omegaQ:vector",
                        "omegaR:vector"}
    vectors = hover_outputs["vectors"]

    for host_idx in range(2):
        suffix = f"host[{host_idx}].mobility"
        recorded = {name for (mod, name) in vectors if mod.endswith(suffix)}
        missing = expected_signals - recorded
        assert not missing, f"host[{host_idx}] missing signals: {missing}"


def test_freefall_all_signals_recorded(freefall_outputs):
    """All 10 MultirotorMobility signals should be present."""
    expected_signals = {"thrust:vector", "tauPhi:vector", "tauTheta:vector",
                        "tauPsi:vector", "phi:vector", "theta:vector",
                        "psi:vector", "omegaP:vector", "omegaQ:vector",
                        "omegaR:vector"}
    vectors = freefall_outputs["vectors"]

    recorded = {name for (mod, name) in vectors
                if mod.endswith("host[0].mobility")}
    missing = expected_signals - recorded
    assert not missing, f"Missing signals: {missing}"
