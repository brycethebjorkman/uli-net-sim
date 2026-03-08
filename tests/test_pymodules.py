"""
Regression tests for Python demo modules (pymodules/).

Tests the three PyBridge hook points:
  1. MultirotorMobility Python controller (HoverController)
  2. GcsModule Python decision algorithm (SerialImpersonationDetector)
  3. RidBeaconMgmt Python TX hook (PositionOffsetSpoofer)

To update hashes after intentional changes:
    .venv/bin/pytest tests/test_pymodules.py -v
"""

import csv
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from .conftest import OMNETPP_ARGS, UAV_RID_BIN, hash_vec_file

REPO_ROOT = Path(__file__).parent.parent
TEST_OUT = Path(__file__).parent / "out" / "pymodules"
SIM_INI = REPO_ROOT / "simulations" / "multirotor_test" / "omnetpp.ini"


# ---------------------------------------------------------------------------
# Helpers (reuse patterns from test_multirotor.py)
# ---------------------------------------------------------------------------

def _run_sim(config: str, result_dir: Path):
    """Run one multirotor_test config."""
    result_dir.mkdir(parents=True, exist_ok=True)
    args = [str(UAV_RID_BIN), "-m", "-u", "Cmdenv", "-c", config,
            *[str(a) for a in OMNETPP_ARGS],
            "-f", str(SIM_INI),
            "--cmdenv-express-mode=true",
            f"--result-dir={result_dir}"]
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"Simulation {config} failed:\n{r.stderr[-2000:]}")
    return result_dir / f"{config}-#0.vec"


def _export_vectors(vec_file: Path, module_filter: str) -> str:
    """Export vectors from .vec file using opp_scavetool, return temp CSV path."""
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    cmd = ['opp_scavetool', 'export', '-F', 'CSV-R', '-x', 'columnNames=true',
           '-f', f'type=~"vector" and module=~"{module_filter}"',
           '-o', tmp.name, str(vec_file)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"opp_scavetool failed: {r.stderr}")
    return tmp.name


def _parse_vectors(csv_path: str) -> dict:
    """Parse CSV-R format into {(module, name): (times[], values[])}."""
    vectors = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['type'] != 'vector':
                continue
            key = (row['module'], row['name'])
            times = [float(t) for t in row['vectime'].split()]
            values = [float(v) for v in row['vecvalue'].split()]
            vectors[key] = (times, values)
    return vectors


def _get_vector(vectors: dict, module_suffix: str, name: str):
    """Get (times, values) for a vector matching module suffix and name."""
    for (mod, n), (times, vals) in vectors.items():
        if mod.endswith(module_suffix) and n == name:
            return times, vals
    raise KeyError(f"Vector not found: module=*{module_suffix}, name={name}")


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

    mobility_csv = _export_vectors(vec_file, "*.host[*].mobility")
    beacon_csv = _export_vectors(vec_file, "*.host[*].wlan[0].mgmt")

    return {
        "vec_file": vec_file,
        "mobility": _parse_vectors(mobility_csv),
        "beacon": _parse_vectors(beacon_csv),
    }


@pytest.fixture(scope="session")
def py_spoofer_outputs():
    """Run PySpooferTest and export vectors."""
    out = TEST_OUT / "spoofer"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PySpooferTest", result_dir)

    beacon_csv = _export_vectors(vec_file, "*.host[*].wlan[0].mgmt")

    return {
        "vec_file": vec_file,
        "beacon": _parse_vectors(beacon_csv),
    }


@pytest.fixture(scope="session")
def py_planner_outputs():
    """Run PyPlannerTest and export vectors."""
    out = TEST_OUT / "planner"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PyPlannerTest", result_dir)

    beacon_csv = _export_vectors(vec_file, "*.host[*].wlan[0].mgmt")
    gcs_csv = _export_vectors(vec_file, "*.gcs[*]")

    return {
        "vec_file": vec_file,
        "beacon": _parse_vectors(beacon_csv),
        "gcs": _parse_vectors(gcs_csv),
    }


@pytest.fixture(scope="session")
def py_planner_perturbed_outputs():
    """Run PyPlannerPerturbed and export vectors."""
    out = TEST_OUT / "planner_perturbed"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PyPlannerPerturbed", result_dir)

    beacon_csv = _export_vectors(vec_file, "*.host[*].wlan[0].mgmt")
    mobility_csv = _export_vectors(vec_file, "*.host[*].mobility")

    return {
        "vec_file": vec_file,
        "beacon": _parse_vectors(beacon_csv),
        "mobility": _parse_vectors(mobility_csv),
    }


@pytest.fixture(scope="session")
def py_detector_outputs():
    """Run PyDetectorTest and export vectors."""
    out = TEST_OUT / "detector"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("PyDetectorTest", result_dir)

    beacon_csv = _export_vectors(vec_file, "*.host[*].wlan[0].mgmt")
    # Export GCS vectors (cOutVector outputs)
    gcs_csv = _export_vectors(vec_file, "*.gcs[*]")

    return {
        "vec_file": vec_file,
        "beacon": _parse_vectors(beacon_csv),
        "gcs": _parse_vectors(gcs_csv),
    }


# ---------------------------------------------------------------------------
# Hash-based regression
# ---------------------------------------------------------------------------

EXPECTED_HASHES = {
    "py_hover.vec":    "e667d6a5a8b2a943dc2a8dceafdb72b932f0af4f420bf91c5d467aa91ea62024",
    "py_spoofer.vec":  "c46ad62f6b60f93cfda7eb299cf6722c85d470f48a791602e1422ba330c83855",
    "py_detector.vec": "2830fa25fa3049510739ac18603b867f77cc0d113b177f648c160c56a5b298c2",
    "py_planner.vec":  "9fd99d3bbeda1cd59c28cc9f45416eebb6ab307e008e58a20d1388c5a485be9a",
    "py_planner_perturbed.vec": "c6a1f2df29a0ed4b65998257973862d8cd1c63e6beffed55c32b50d25a848711",
}


def test_py_hover_vec_hash(py_hover_outputs):
    h = hash_vec_file(py_hover_outputs["vec_file"])
    expected = EXPECTED_HASHES["py_hover.vec"]
    assert h == expected, f"PyHoverTest .vec hash changed: {h}"


def test_py_spoofer_vec_hash(py_spoofer_outputs):
    h = hash_vec_file(py_spoofer_outputs["vec_file"])
    expected = EXPECTED_HASHES["py_spoofer.vec"]
    assert h == expected, f"PySpooferTest .vec hash changed: {h}"


def test_py_planner_vec_hash(py_planner_outputs):
    h = hash_vec_file(py_planner_outputs["vec_file"])
    expected = EXPECTED_HASHES["py_planner.vec"]
    assert h == expected, f"PyPlannerTest .vec hash changed: {h}"


def test_py_detector_vec_hash(py_detector_outputs):
    h = hash_vec_file(py_detector_outputs["vec_file"])
    expected = EXPECTED_HASHES["py_detector.vec"]
    assert h == expected, f"PyDetectorTest .vec hash changed: {h}"


# ---------------------------------------------------------------------------
# Hover controller tests
# ---------------------------------------------------------------------------

def test_py_hover_position_bounded(py_hover_outputs):
    """Host 0 (perturbed with vx=2, vy=-1) should stay within 20m of target."""
    beacon = py_hover_outputs["beacon"]

    for coord, target in [("Transmission My X Coordinate", 100.0),
                          ("Transmission My Y Coordinate", 100.0),
                          ("Transmission My Z Coordinate", 50.0)]:
        times, values = _get_vector(beacon, "host[0].wlan[0].mgmt", coord)
        for i, v in enumerate(values):
            assert abs(v - target) < 20.0, \
                f"host[0] {coord} at t={times[i]:.1f}: {v:.2f} too far from {target}"


def test_py_hover_host1_stable(py_hover_outputs):
    """Host 1 (at rest) should stay very close to (200, 200, 80)."""
    beacon = py_hover_outputs["beacon"]

    for coord, target in [("Transmission My X Coordinate", 200.0),
                          ("Transmission My Y Coordinate", 200.0),
                          ("Transmission My Z Coordinate", 80.0)]:
        times, values = _get_vector(beacon, "host[1].wlan[0].mgmt", coord)
        for i, v in enumerate(values):
            assert abs(v - target) < 1.0, \
                f"host[1] {coord} at t={times[i]:.1f}: {v:.2f} too far from {target}"


# ---------------------------------------------------------------------------
# Spoofer tests
# ---------------------------------------------------------------------------

def test_py_spoofer_offset_applied(py_spoofer_outputs):
    """Host 1's TX beacon should claim (250, 250, 50) not (200, 200, 50)."""
    beacon = py_spoofer_outputs["beacon"]

    for coord, expected in [("Transmission X Coordinate", 250.0),
                            ("Transmission Y Coordinate", 250.0),
                            ("Transmission Z Coordinate", 50.0)]:
        _times, values = _get_vector(beacon, "host[1].wlan[0].mgmt", coord)
        for v in values:
            assert abs(v - expected) < 1e-3, \
                f"host[1] spoofed {coord}: {v} != {expected}"


def test_py_spoofer_actual_unchanged(py_spoofer_outputs):
    """Host 1's actual position should still be (200, 200, 50)."""
    beacon = py_spoofer_outputs["beacon"]

    for coord, expected in [("Transmission My X Coordinate", 200.0),
                            ("Transmission My Y Coordinate", 200.0),
                            ("Transmission My Z Coordinate", 50.0)]:
        _times, values = _get_vector(beacon, "host[1].wlan[0].mgmt", coord)
        for v in values:
            assert abs(v - expected) < 1e-3, \
                f"host[1] actual {coord}: {v} != {expected}"


def test_py_spoofer_benign_unmodified(py_spoofer_outputs):
    """Host 0 (no TX hook) should claim its actual position (100, 100, 50)."""
    beacon = py_spoofer_outputs["beacon"]

    for coord, expected in [("Transmission X Coordinate", 100.0),
                            ("Transmission Y Coordinate", 100.0)]:
        _times, values = _get_vector(beacon, "host[0].wlan[0].mgmt", coord)
        for v in values:
            assert abs(v - expected) < 1e-3, \
                f"host[0] benign {coord}: {v} != {expected}"


# ---------------------------------------------------------------------------
# Detector tests (serial impersonation)
# ---------------------------------------------------------------------------

def test_py_detector_signals_recorded(py_detector_outputs):
    """GCS[0] should have recorded is_impersonation and total_detections."""
    gcs = py_detector_outputs["gcs"]
    recorded_names = {name for (_mod, name) in gcs}

    expected = {"is_impersonation", "total_detections"}
    missing = expected - recorded_names
    assert not missing, f"GCS missing output vectors: {missing}"


def test_py_detector_impersonation_detected(py_detector_outputs):
    """is_impersonation should be 1.0 for spoofer beacons (serial=0) and 0.0 for others."""
    gcs = py_detector_outputs["gcs"]
    times, values = _get_vector(gcs, "gcs[0]", "is_impersonation")

    # With staggered offsets (0.0, 0.1, 0.2, 0.5), gcs[0] sees 3 transmissions/sec:
    # host 1 (serial=1, offset=0.1) -> is_impersonation=0
    # host 2 (serial=2, offset=0.2) -> is_impersonation=0
    # host 3 (serial=0, offset=0.5) -> is_impersonation=1
    assert len(values) > 0, "No is_impersonation values recorded"
    assert 1.0 in values, "Spoofer impersonation was not detected"
    assert 0.0 in values, "Expected some non-impersonation transmissions"


def test_py_detector_total_detections(py_detector_outputs):
    """total_detections should reach 10 (one per second over 10s)."""
    gcs = py_detector_outputs["gcs"]
    _times, values = _get_vector(gcs, "gcs[0]", "total_detections")

    assert len(values) > 0, "No total_detections values recorded"
    assert max(values) == 10.0, \
        f"Expected 10 total detections, got max={max(values)}"


# ---------------------------------------------------------------------------
# Planner tests (GCS on_tick + command forwarding)
# ---------------------------------------------------------------------------

def test_py_planner_tick_count(py_planner_outputs):
    """GCS should record 10 ticks (20s sim / 2s interval)."""
    gcs = py_planner_outputs["gcs"]
    _times, values = _get_vector(gcs, "gcs[0]", "tick_count")

    assert len(values) == 10, f"Expected 10 ticks, got {len(values)}"
    assert values[-1] == 10.0, f"Last tick_count should be 10, got {values[-1]}"


def test_py_planner_altitude_changes(py_planner_outputs):
    """Each host's altitude should change over time (not constant)."""
    beacon = py_planner_outputs["beacon"]

    for host_idx in range(4):
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        _times, values = _get_vector(beacon, suffix,
                                     "Transmission My Z Coordinate")
        z_min = min(values)
        z_max = max(values)
        assert z_max - z_min > 5.0, \
            f"host[{host_idx}] altitude range too small: {z_min:.1f}-{z_max:.1f}"


def test_py_planner_xy_stable(py_planner_outputs):
    """X/Y positions should stay near initial values (only altitude changes)."""
    beacon = py_planner_outputs["beacon"]

    initials = {0: (100.0, 100.0), 1: (200.0, 100.0),
                2: (100.0, 200.0), 3: (200.0, 200.0)}

    for host_idx, (init_x, init_y) in initials.items():
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        for coord, target in [("Transmission My X Coordinate", init_x),
                              ("Transmission My Y Coordinate", init_y)]:
            _times, values = _get_vector(beacon, suffix, coord)
            for v in values:
                assert abs(v - target) < 30.0, \
                    f"host[{host_idx}] {coord}: {v:.1f} too far from {target}"


def test_py_planner_varied_dynamics(py_planner_outputs):
    """Different drone masses should produce different altitude responses."""
    beacon = py_planner_outputs["beacon"]

    # Collect altitude standard deviations for each host
    std_devs = []
    for host_idx in range(4):
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        _times, values = _get_vector(beacon, suffix,
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

def test_py_planner_perturbed_vec_hash(py_planner_perturbed_outputs):
    h = hash_vec_file(py_planner_perturbed_outputs["vec_file"])
    expected = EXPECTED_HASHES["py_planner_perturbed.vec"]
    assert h == expected, f"PyPlannerPerturbed .vec hash changed: {h}"


def test_py_planner_perturbed_hosts_drift(py_planner_perturbed_outputs):
    """All hosts should drift from initial XY due to initial velocities (no drag)."""
    beacon = py_planner_perturbed_outputs["beacon"]

    initials = {0: (100.0, 100.0), 1: (200.0, 100.0),
                2: (100.0, 200.0), 3: (200.0, 200.0)}

    for host_idx, (init_x, init_y) in initials.items():
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        _t, x_vals = _get_vector(beacon, suffix, "Transmission My X Coordinate")
        _t, y_vals = _get_vector(beacon, suffix, "Transmission My Y Coordinate")

        # Last position should differ from initial by at least 5m in some axis
        dx = abs(x_vals[-1] - init_x)
        dy = abs(y_vals[-1] - init_y)
        assert dx > 5.0 or dy > 5.0, \
            f"host[{host_idx}] didn't drift: dx={dx:.1f}, dy={dy:.1f}"


def test_py_planner_perturbed_altitude_still_controlled(py_planner_perturbed_outputs):
    """Despite perturbations, altitude should still change (GCS commands work)."""
    beacon = py_planner_perturbed_outputs["beacon"]

    for host_idx in range(4):
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        _t, z_vals = _get_vector(beacon, suffix, "Transmission My Z Coordinate")
        z_range = max(z_vals) - min(z_vals)
        assert z_range > 5.0, \
            f"host[{host_idx}] altitude range too small: {z_range:.1f}m"


def test_py_planner_perturbed_different_trajectories(py_planner_perturbed_outputs):
    """Each host should follow a distinct trajectory (different initial conditions)."""
    beacon = py_planner_perturbed_outputs["beacon"]

    final_positions = []
    for host_idx in range(4):
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        _t, x_vals = _get_vector(beacon, suffix, "Transmission My X Coordinate")
        _t, y_vals = _get_vector(beacon, suffix, "Transmission My Y Coordinate")
        final_positions.append((x_vals[-1], y_vals[-1]))

    # All final positions should be distinct (pairwise distance > 10m)
    for i in range(4):
        for j in range(i + 1, 4):
            dx = final_positions[i][0] - final_positions[j][0]
            dy = final_positions[i][1] - final_positions[j][1]
            dist = (dx**2 + dy**2) ** 0.5
            assert dist > 10.0, \
                f"host[{i}] and host[{j}] too close: {dist:.1f}m"
