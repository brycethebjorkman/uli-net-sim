"""
Regression tests for Python demo modules (pymodules/).

Tests the PyBridge hook points:
  1. MultirotorMobility Python controller (HoverController, CascadedPidController)
  2. GcsModule Python decision algorithm (SerialImpersonationDetector)
  3. RidBeaconMgmt Python TX hook (PositionOffsetSpoofer)

To update hashes after intentional changes:
    .venv/bin/pytest tests/test_pymodules.py -v
"""

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

from .conftest import (RUN_SH, extract_our_vectors, diff_vector_hashes)
from datagen.vec2parquet import hash_vector_data

REPO_ROOT = Path(__file__).parent.parent
TEST_OUT = Path(__file__).parent / "out" / "pymodules"
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
def py_hover_outputs():
    """Run PyHoverTest and export vectors."""
    out = TEST_OUT / "hover"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PyHoverTest", result_dir)
    vectors = extract_our_vectors(vec_file)

    return {
        "vec_file": vec_file,
        "vectors": vectors,
    }


@pytest.fixture(scope="session")
def py_spoofer_outputs():
    """Run PySpooferTest and export vectors."""
    out = TEST_OUT / "spoofer"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PySpooferTest", result_dir)
    vectors = extract_our_vectors(vec_file)

    return {
        "vec_file": vec_file,
        "vectors": vectors,
    }


@pytest.fixture(scope="session")
def py_planner_outputs():
    """Run PyPlannerTest and export vectors."""
    out = TEST_OUT / "planner"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PyPlannerTest", result_dir)
    vectors = extract_our_vectors(vec_file)

    return {
        "vec_file": vec_file,
        "vectors": vectors,
    }


@pytest.fixture(scope="session")
def py_planner_perturbed_outputs():
    """Run PyPlannerPerturbed and export vectors."""
    out = TEST_OUT / "planner_perturbed"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PyPlannerPerturbed", result_dir)
    vectors = extract_our_vectors(vec_file)

    return {
        "vec_file": vec_file,
        "vectors": vectors,
    }


@pytest.fixture(scope="session")
def py_detector_outputs():
    """Run PyDetectorTest and export vectors."""
    out = TEST_OUT / "detector"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PyDetectorTest", result_dir)
    vectors = extract_our_vectors(vec_file)

    return {
        "vec_file": vec_file,
        "vectors": vectors,
    }


# ---------------------------------------------------------------------------
# Hash-based regression
# ---------------------------------------------------------------------------

def test_py_hover_vec_hashes(py_hover_outputs):
    _check_hashes(py_hover_outputs["vectors"], "py_hover", "PyHoverTest")


def test_py_spoofer_vec_hashes(py_spoofer_outputs):
    _check_hashes(py_spoofer_outputs["vectors"], "py_spoofer", "PySpooferTest")


def test_py_planner_vec_hashes(py_planner_outputs):
    _check_hashes(py_planner_outputs["vectors"], "py_planner", "PyPlannerTest")


def test_py_detector_vec_hashes(py_detector_outputs):
    _check_hashes(py_detector_outputs["vectors"], "py_detector", "PyDetectorTest")


def test_py_planner_perturbed_vec_hashes(py_planner_perturbed_outputs):
    _check_hashes(py_planner_perturbed_outputs["vectors"],
                  "py_planner_perturbed", "PyPlannerPerturbed")


# ---------------------------------------------------------------------------
# Hover controller tests
# ---------------------------------------------------------------------------

def test_py_hover_position_bounded(py_hover_outputs):
    """Host 0 (perturbed with vx=2, vy=-1) should stay within 20m of target."""
    vectors = py_hover_outputs["vectors"]

    for coord, target in [("Transmission My X Coordinate", 100.0),
                          ("Transmission My Y Coordinate", 100.0),
                          ("Transmission My Z Coordinate", 50.0)]:
        times, values = _get_vector(vectors, "host[0].wlan[0].mgmt", coord)
        for i, v in enumerate(values):
            assert abs(v - target) < 20.0, \
                f"host[0] {coord} at t={times[i]:.1f}: {v:.2f} too far from {target}"


def test_py_hover_host1_stable(py_hover_outputs):
    """Host 1 (at rest) should stay very close to (200, 200, 80)."""
    vectors = py_hover_outputs["vectors"]

    for coord, target in [("Transmission My X Coordinate", 200.0),
                          ("Transmission My Y Coordinate", 200.0),
                          ("Transmission My Z Coordinate", 80.0)]:
        times, values = _get_vector(vectors, "host[1].wlan[0].mgmt", coord)
        for i, v in enumerate(values):
            assert abs(v - target) < 1.0, \
                f"host[1] {coord} at t={times[i]:.1f}: {v:.2f} too far from {target}"


# ---------------------------------------------------------------------------
# Spoofer tests
# ---------------------------------------------------------------------------

def test_py_spoofer_offset_applied(py_spoofer_outputs):
    """Host 1's TX beacon should claim (250, 250, 50) not (200, 200, 50)."""
    vectors = py_spoofer_outputs["vectors"]

    for coord, expected in [("Transmission X Coordinate", 250.0),
                            ("Transmission Y Coordinate", 250.0),
                            ("Transmission Z Coordinate", 50.0)]:
        _times, values = _get_vector(vectors, "host[1].wlan[0].mgmt", coord)
        for v in values:
            assert abs(v - expected) < 1e-3, \
                f"host[1] spoofed {coord}: {v} != {expected}"


def test_py_spoofer_actual_unchanged(py_spoofer_outputs):
    """Host 1's actual position should still be (200, 200, 50)."""
    vectors = py_spoofer_outputs["vectors"]

    for coord, expected in [("Transmission My X Coordinate", 200.0),
                            ("Transmission My Y Coordinate", 200.0),
                            ("Transmission My Z Coordinate", 50.0)]:
        _times, values = _get_vector(vectors, "host[1].wlan[0].mgmt", coord)
        for v in values:
            assert abs(v - expected) < 1e-3, \
                f"host[1] actual {coord}: {v} != {expected}"


def test_py_spoofer_benign_unmodified(py_spoofer_outputs):
    """Host 0 (no TX hook) should claim its actual position (100, 100, 50)."""
    vectors = py_spoofer_outputs["vectors"]

    for coord, expected in [("Transmission X Coordinate", 100.0),
                            ("Transmission Y Coordinate", 100.0)]:
        _times, values = _get_vector(vectors, "host[0].wlan[0].mgmt", coord)
        for v in values:
            assert abs(v - expected) < 1e-3, \
                f"host[0] benign {coord}: {v} != {expected}"


# ---------------------------------------------------------------------------
# Detector tests (serial impersonation)
# ---------------------------------------------------------------------------

def test_py_detector_signals_recorded(py_detector_outputs):
    """GCS[0] should have recorded is_impersonation and total_detections."""
    vectors = py_detector_outputs["vectors"]
    recorded_names = {name for (_mod, name) in vectors}

    expected = {"is_impersonation", "total_detections"}
    missing = expected - recorded_names
    assert not missing, f"GCS missing output vectors: {missing}"


def test_py_detector_impersonation_detected(py_detector_outputs):
    """is_impersonation should be 1.0 for spoofer beacons (serial=0) and 0.0 for others."""
    vectors = py_detector_outputs["vectors"]
    times, values = _get_vector(vectors, "gcs[0]", "is_impersonation")

    # With staggered offsets (0.0, 0.1, 0.2, 0.5), gcs[0] sees 3 transmissions/sec:
    # host 1 (serial=1, offset=0.1) -> is_impersonation=0
    # host 2 (serial=2, offset=0.2) -> is_impersonation=0
    # host 3 (serial=0, offset=0.5) -> is_impersonation=1
    assert len(values) > 0, "No is_impersonation values recorded"
    assert 1.0 in values, "Spoofer impersonation was not detected"
    assert 0.0 in values, "Expected some non-impersonation transmissions"


def test_py_detector_total_detections(py_detector_outputs):
    """total_detections should reach 10 (one per second over 10s)."""
    vectors = py_detector_outputs["vectors"]
    _times, values = _get_vector(vectors, "gcs[0]", "total_detections")

    assert len(values) > 0, "No total_detections values recorded"
    assert max(values) == 10.0, \
        f"Expected 10 total detections, got max={max(values)}"


# ---------------------------------------------------------------------------
# Planner tests (GCS on_tick + command forwarding)
# ---------------------------------------------------------------------------

def test_py_planner_tick_count(py_planner_outputs):
    """GCS should record 10 ticks (20s sim / 2s interval)."""
    vectors = py_planner_outputs["vectors"]
    _times, values = _get_vector(vectors, "gcs[0]", "tick_count")

    assert len(values) == 10, f"Expected 10 ticks, got {len(values)}"
    assert values[-1] == 10.0, f"Last tick_count should be 10, got {values[-1]}"


def test_py_planner_altitude_changes(py_planner_outputs):
    """Each host's altitude should change over time (not constant)."""
    vectors = py_planner_outputs["vectors"]

    for host_idx in range(4):
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        _times, values = _get_vector(vectors, suffix,
                                     "Transmission My Z Coordinate")
        z_min = min(values)
        z_max = max(values)
        assert z_max - z_min > 5.0, \
            f"host[{host_idx}] altitude range too small: {z_min:.1f}-{z_max:.1f}"


def test_py_planner_xy_stable(py_planner_outputs):
    """X/Y positions should stay near initial values (only altitude changes)."""
    vectors = py_planner_outputs["vectors"]

    initials = {0: (100.0, 100.0), 1: (200.0, 100.0),
                2: (100.0, 200.0), 3: (200.0, 200.0)}

    for host_idx, (init_x, init_y) in initials.items():
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        for coord, target in [("Transmission My X Coordinate", init_x),
                              ("Transmission My Y Coordinate", init_y)]:
            _times, values = _get_vector(vectors, suffix, coord)
            for v in values:
                assert abs(v - target) < 30.0, \
                    f"host[{host_idx}] {coord}: {v:.1f} too far from {target}"


def test_py_planner_varied_dynamics(py_planner_outputs):
    """Different drone masses should produce different altitude responses."""
    vectors = py_planner_outputs["vectors"]

    # Collect altitude standard deviations for each host
    std_devs = []
    for host_idx in range(4):
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        _times, values = _get_vector(vectors, suffix,
                                     "Transmission My Z Coordinate")
        mean_z = sum(values) / len(values)
        std_z = (sum((v - mean_z) ** 2 for v in values) / len(values)) ** 0.5
        std_devs.append(std_z)

    # Not all std_devs should be identical — different dynamics produce different responses
    assert max(std_devs) - min(std_devs) > 1.0, \
        f"All hosts have similar altitude variance: {std_devs}"


# ---------------------------------------------------------------------------
# Planner perturbed tests (initial velocity/angle perturbations)
# ---------------------------------------------------------------------------

def test_py_planner_perturbed_hosts_drift(py_planner_perturbed_outputs):
    """All hosts should drift from initial XY due to initial velocity perturbations."""
    vectors = py_planner_perturbed_outputs["vectors"]

    initials = {0: (100.0, 100.0), 1: (200.0, 100.0),
                2: (100.0, 200.0), 3: (200.0, 200.0)}

    for host_idx, (init_x, init_y) in initials.items():
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        _t, x_vals = _get_vector(vectors, suffix, "Transmission My X Coordinate")
        _t, y_vals = _get_vector(vectors, suffix, "Transmission My Y Coordinate")

        # Max deviation at any point should exceed 1m (drag may damp drift
        # before end of sim, so check peak deviation rather than final position)
        max_dx = max(abs(v - init_x) for v in x_vals)
        max_dy = max(abs(v - init_y) for v in y_vals)
        assert max_dx > 1.0 or max_dy > 1.0, \
            f"host[{host_idx}] never drifted: max_dx={max_dx:.1f}, max_dy={max_dy:.1f}"


def test_py_planner_perturbed_altitude_still_controlled(py_planner_perturbed_outputs):
    """Despite perturbations, altitude should still change (GCS commands work)."""
    vectors = py_planner_perturbed_outputs["vectors"]

    for host_idx in range(4):
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        _t, z_vals = _get_vector(vectors, suffix, "Transmission My Z Coordinate")
        z_range = max(z_vals) - min(z_vals)
        assert z_range > 5.0, \
            f"host[{host_idx}] altitude range too small: {z_range:.1f}m"


def test_py_planner_perturbed_different_trajectories(py_planner_perturbed_outputs):
    """Each host should follow a distinct trajectory (different initial conditions)."""
    vectors = py_planner_perturbed_outputs["vectors"]

    final_positions = []
    for host_idx in range(4):
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        _t, x_vals = _get_vector(vectors, suffix, "Transmission My X Coordinate")
        _t, y_vals = _get_vector(vectors, suffix, "Transmission My Y Coordinate")
        final_positions.append((x_vals[-1], y_vals[-1]))

    # All final positions should be distinct (pairwise distance > 10m)
    for i in range(4):
        for j in range(i + 1, 4):
            dx = final_positions[i][0] - final_positions[j][0]
            dy = final_positions[i][1] - final_positions[j][1]
            dist = (dx**2 + dy**2) ** 0.5
            assert dist > 10.0, \
                f"host[{i}] and host[{j}] too close: {dist:.1f}m"


# ---------------------------------------------------------------------------
# CascadedPID GCS command fixture and tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def py_cascaded_gcs_outputs():
    """Run PyCascadedPidGcsTest and export vectors."""
    out = TEST_OUT / "cascaded_gcs"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PyCascadedPidGcsTest", result_dir)
    vectors = extract_our_vectors(vec_file)

    return {
        "vec_file": vec_file,
        "vectors": vectors,
    }


def test_py_cascaded_gcs_vec_hashes(py_cascaded_gcs_outputs):
    _check_hashes(py_cascaded_gcs_outputs["vectors"],
                  "py_cascaded_gcs", "PyCascadedPidGcsTest")


def test_py_cascaded_gcs_goto_heading(py_cascaded_gcs_outputs):
    """After goto (250, 250, 60) at t=2s, host 0 should move toward target."""
    vectors = py_cascaded_gcs_outputs["vectors"]

    xt, xv = _get_vector(vectors, "host[0].wlan[0].mgmt",
                         "Transmission My X Coordinate")
    _t, yv = _get_vector(vectors, "host[0].wlan[0].mgmt",
                         "Transmission My Y Coordinate")

    # Distance to target should decrease between t=3s and t=6s
    target = (250.0, 250.0)
    dists = {}
    for i in range(len(xt)):
        if xt[i] in (3.0, 6.0):
            dists[xt[i]] = math.sqrt((xv[i] - target[0])**2 + (yv[i] - target[1])**2)

    assert 3.0 in dists and 6.0 in dists, "Missing samples at t=3s or t=6s"
    assert dists[6.0] < dists[3.0], \
        f"Host 0 not moving toward goto target: d(t=3)={dists[3.0]:.1f}, d(t=6)={dists[6.0]:.1f}"


def test_py_cascaded_gcs_hold_stable(py_cascaded_gcs_outputs):
    """After hold at t=6s, host 0 position should stabilize (low velocity)."""
    vectors = py_cascaded_gcs_outputs["vectors"]

    xt, xv = _get_vector(vectors, "host[0].wlan[0].mgmt",
                         "Transmission My X Coordinate")
    _t, yv = _get_vector(vectors, "host[0].wlan[0].mgmt",
                         "Transmission My Y Coordinate")

    # Samples between t=8s and t=10s (2-4s after hold command)
    positions = [(xv[i], yv[i]) for i in range(len(xt)) if 8.0 <= xt[i] <= 10.0]
    if len(positions) >= 2:
        # Position spread should be small (drone is holding)
        x_vals = [p[0] for p in positions]
        y_vals = [p[1] for p in positions]
        x_spread = max(x_vals) - min(x_vals)
        y_spread = max(y_vals) - min(y_vals)
        assert x_spread < 30.0 and y_spread < 30.0, \
            f"Host 0 not holding position: x_spread={x_spread:.1f}, y_spread={y_spread:.1f}"


def test_py_cascaded_gcs_waypoints_followed(py_cascaded_gcs_outputs):
    """After waypoints command at t=10s, host 0 should resume moving and reach ~60m altitude."""
    vectors = py_cascaded_gcs_outputs["vectors"]

    xt, xv = _get_vector(vectors, "host[0].wlan[0].mgmt",
                         "Transmission My X Coordinate")
    _t, yv = _get_vector(vectors, "host[0].wlan[0].mgmt",
                         "Transmission My Y Coordinate")
    _t, zv = _get_vector(vectors, "host[0].wlan[0].mgmt",
                         "Transmission My Z Coordinate")

    # After waypoints command, drone should move steadily (X/Y increasing toward 300,300)
    # and altitude should rise toward 60-80m (first wp at z=60, second at z=80)
    late_x = [xv[i] for i in range(len(xt)) if xt[i] >= 20.0]
    late_y = [yv[i] for i in range(len(xt)) if xt[i] >= 20.0]
    late_z = [zv[i] for i in range(len(xt)) if xt[i] >= 14.0]

    assert late_x, "No samples after t=20s"
    # X and Y should be increasing (heading toward 300, 300)
    assert late_x[-1] > late_x[0], \
        f"Host 0 X not increasing after waypoints: {late_x[0]:.1f} -> {late_x[-1]:.1f}"
    assert late_y[-1] > late_y[0], \
        f"Host 0 Y not increasing after waypoints: {late_y[0]:.1f} -> {late_y[-1]:.1f}"
    # Altitude should reach near 60m (first waypoint target)
    assert max(late_z) > 55.0, \
        f"Host 0 altitude didn't reach 55m after waypoints (max={max(late_z):.1f}m)"


def test_py_cascaded_gcs_tick_count(py_cascaded_gcs_outputs):
    """GCS should record 15 ticks (30s sim / 2s interval)."""
    vectors = py_cascaded_gcs_outputs["vectors"]
    _times, values = _get_vector(vectors, "gcs[0]", "tick_count")

    assert len(values) == 15, f"Expected 15 ticks, got {len(values)}"
    assert values[-1] == 15.0, f"Last tick_count should be 15, got {values[-1]}"


# ---------------------------------------------------------------------------
# Trajectory controller fixture and tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def py_trajectory_outputs():
    """Run PyTrajectoryTest and export vectors."""
    out = TEST_OUT / "trajectory"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PyTrajectoryTest", result_dir)
    vectors = extract_our_vectors(vec_file)

    return {
        "vec_file": vec_file,
        "vectors": vectors,
    }


def test_py_trajectory_vec_hashes(py_trajectory_outputs):
    _check_hashes(py_trajectory_outputs["vectors"],
                  "py_trajectory", "PyTrajectoryTest")


def test_py_trajectory_reaches_waypoints(py_trajectory_outputs):
    """Host 0 should pass within 10m of each waypoint (beacon-sampled)."""
    vectors = py_trajectory_outputs["vectors"]

    waypoints = [(200, 100, 50), (200, 200, 60), (200, 300, 50)]

    xt, xv = _get_vector(vectors, "host[0].wlan[0].mgmt",
                         "Transmission My X Coordinate")
    _t, yv = _get_vector(vectors, "host[0].wlan[0].mgmt",
                         "Transmission My Y Coordinate")
    _t, zv = _get_vector(vectors, "host[0].wlan[0].mgmt",
                         "Transmission My Z Coordinate")

    for wp in waypoints:
        min_dist = min(
            math.sqrt((xv[i] - wp[0])**2 + (yv[i] - wp[1])**2 +
                       (zv[i] - wp[2])**2)
            for i in range(len(xv))
        )
        assert min_dist < 10.0, \
            f"Host 0 never reached within 10m of {wp} (min_dist={min_dist:.1f}m)"


def test_py_trajectory_hover_at_end(py_trajectory_outputs):
    """Host 1 should hover near final waypoint (150, 150, 40) at sim end."""
    vectors = py_trajectory_outputs["vectors"]

    for coord, target in [("Transmission My X Coordinate", 150.0),
                          ("Transmission My Y Coordinate", 150.0),
                          ("Transmission My Z Coordinate", 40.0)]:
        _t, values = _get_vector(vectors, "host[1].wlan[0].mgmt", coord)
        # Check last 5 samples are within 10m of target
        for v in values[-5:]:
            assert abs(v - target) < 10.0, \
                f"Host 1 not hovering near {coord}={target}: {v:.2f}"


def test_py_trajectory_altitude_tracking(py_trajectory_outputs):
    """Host 1 should reach altitude 70m (wp1) then descend to 40m (wp2)."""
    vectors = py_trajectory_outputs["vectors"]

    _t, zv = _get_vector(vectors, "host[1].wlan[0].mgmt",
                         "Transmission My Z Coordinate")

    # Should reach near 70m at some point, then settle near 40m
    assert max(zv) > 65.0, \
        f"Host 1 never reached altitude 70m (max={max(zv):.1f}m)"
    assert abs(zv[-1] - 40.0) < 5.0, \
        f"Host 1 didn't settle near 40m (final={zv[-1]:.1f}m)"
