"""
Regression tests for MultirotorMobility 6-DoF dynamics.

Runs HoverTest and FreefallTest configs from simulations/multirotor_test/,
exports mobility and beacon vectors, and verifies:
  - Hover: position constant, thrust = m*g, angles/rates zero
  - Freefall: z follows analytical z(t) = z0 - 0.5*g*t^2, thrust = 0

To update hashes after intentional changes:
    .venv/bin/pytest tests/test_multirotor.py -v
"""

import csv
import subprocess
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import pytest

from .conftest import OMNETPP_ARGS, UAV_RID_BIN, hash_vec_file

GRAVITY = 9.81
REPO_ROOT = Path(__file__).parent.parent
TEST_OUT = Path(__file__).parent / "out" / "multirotor"
SIM_INI = REPO_ROOT / "simulations" / "multirotor_test" / "omnetpp.ini"


# ---------------------------------------------------------------------------
# Helpers
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


def _value_at_time(times, values, target_t, tol=0.01):
    """Find the value closest to target_t within tolerance."""
    best_idx = min(range(len(times)), key=lambda i: abs(times[i] - target_t))
    if abs(times[best_idx] - target_t) > tol:
        raise ValueError(f"No sample near t={target_t} (closest: {times[best_idx]})")
    return values[best_idx]


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

    mobility_csv = _export_vectors(vec_file, "*.host[*].mobility")
    beacon_csv = _export_vectors(vec_file, "*.host[*].wlan[0].mgmt")

    return {
        "vec_file": vec_file,
        "mobility": _parse_vectors(mobility_csv),
        "beacon": _parse_vectors(beacon_csv),
    }


@pytest.fixture(scope="session")
def freefall_outputs():
    """Run FreefallTest and export vectors."""
    out = TEST_OUT / "freefall"
    if out.exists():
        shutil.rmtree(out)
    result_dir = out / "results"
    vec_file = _run_sim("FreefallTest", result_dir)

    mobility_csv = _export_vectors(vec_file, "*.host[*].mobility")
    beacon_csv = _export_vectors(vec_file, "*.host[*].wlan[0].mgmt")

    return {
        "vec_file": vec_file,
        "mobility": _parse_vectors(mobility_csv),
        "beacon": _parse_vectors(beacon_csv),
    }


# ---------------------------------------------------------------------------
# Hash-based regression (catches any change in dynamics output)
# ---------------------------------------------------------------------------

EXPECTED_HASHES = {
    "hover.vec":    "c9b6c2b8ecf7663199c5e60dc30652625522990531dfe78221f03231808d516d",
    "freefall.vec": "8aff2180e0906f2f456ecb9960153d87657f10d7994cdf34f689a70918a7b2c3",
}


def test_hover_vec_hash(hover_outputs):
    h = hash_vec_file(hover_outputs["vec_file"])
    expected = EXPECTED_HASHES["hover.vec"]
    if expected == "PLACEHOLDER":
        pytest.fail(f"Hover .vec hash (update EXPECTED_HASHES): {h}")
    assert h == expected, f"Hover .vec hash changed: {h}"


def test_freefall_vec_hash(freefall_outputs):
    h = hash_vec_file(freefall_outputs["vec_file"])
    expected = EXPECTED_HASHES["freefall.vec"]
    if expected == "PLACEHOLDER":
        pytest.fail(f"Freefall .vec hash (update EXPECTED_HASHES): {h}")
    assert h == expected, f"Freefall .vec hash changed: {h}"


# ---------------------------------------------------------------------------
# Hover physics tests
# ---------------------------------------------------------------------------

def test_hover_thrust_equals_mg(hover_outputs):
    """Thrust should be m*g = 5 * 9.81 = 49.05 N throughout."""
    times, values = _get_vector(hover_outputs["mobility"],
                                "host[0].mobility", "thrust:vector")
    expected_thrust = 5.0 * GRAVITY
    for v in values:
        assert abs(v - expected_thrust) < 1e-6, f"Thrust {v} != {expected_thrust}"


def test_hover_position_constant(hover_outputs):
    """Host 0 should stay at (100, 100, 50) and host 1 at (200, 200, 80)."""
    beacon = hover_outputs["beacon"]

    for host_idx, (ex, ey, ez) in [(0, (100, 100, 50)), (1, (200, 200, 80))]:
        suffix = f"host[{host_idx}].wlan[0].mgmt"
        for coord, expected in [("Transmission My X Coordinate", ex),
                                ("Transmission My Y Coordinate", ey),
                                ("Transmission My Z Coordinate", ez)]:
            times, values = _get_vector(beacon, suffix, coord)
            for i, v in enumerate(values):
                assert abs(v - expected) < 1e-3, \
                    f"host[{host_idx}] {coord} at t={times[i]}: {v} != {expected}"


def test_hover_angles_zero(hover_outputs):
    """All Euler angles and angular rates should remain zero."""
    mobility = hover_outputs["mobility"]
    for signal in ["phi:vector", "theta:vector", "psi:vector",
                   "omegaP:vector", "omegaQ:vector", "omegaR:vector"]:
        times, values = _get_vector(mobility, "host[0].mobility", signal)
        for v in values:
            assert abs(v) < 1e-10, f"{signal}: got {v}, expected 0"


def test_hover_torques_zero(hover_outputs):
    """All torques should be zero during hover."""
    mobility = hover_outputs["mobility"]
    for signal in ["tauPhi:vector", "tauTheta:vector", "tauPsi:vector"]:
        times, values = _get_vector(mobility, "host[0].mobility", signal)
        for v in values:
            assert abs(v) < 1e-10, f"{signal}: got {v}, expected 0"


# ---------------------------------------------------------------------------
# Freefall physics tests
# ---------------------------------------------------------------------------

def test_freefall_thrust_zero(freefall_outputs):
    """Thrust should be zero throughout freefall."""
    times, values = _get_vector(freefall_outputs["mobility"],
                                "host[0].mobility", "thrust:vector")
    for v in values:
        assert v == 0.0, f"Thrust {v} != 0"


def test_freefall_z_analytical(freefall_outputs):
    """Z position should follow z(t) = 100 - 0.5 * g * t^2."""
    beacon = freefall_outputs["beacon"]
    times, values = _get_vector(beacon, "host[0].wlan[0].mgmt",
                                "Transmission My Z Coordinate")

    for t, z_actual in zip(times, values):
        z_expected = 100.0 - 0.5 * GRAVITY * t * t
        assert abs(z_actual - z_expected) < 0.05, \
            f"Freefall z at t={t:.3f}: {z_actual:.3f} != {z_expected:.3f} (analytical)"


def test_freefall_xy_constant(freefall_outputs):
    """X and Y should remain at 0 during freefall (no lateral forces)."""
    beacon = freefall_outputs["beacon"]
    for coord in ["Transmission My X Coordinate",
                  "Transmission My Y Coordinate"]:
        times, values = _get_vector(beacon, "host[0].wlan[0].mgmt", coord)
        for v in values:
            assert abs(v) < 1e-3, f"{coord}: {v} != 0"


def test_freefall_angles_zero(freefall_outputs):
    """No rotation should occur during pure freefall."""
    mobility = freefall_outputs["mobility"]
    for signal in ["phi:vector", "theta:vector", "psi:vector",
                   "omegaP:vector", "omegaQ:vector", "omegaR:vector"]:
        times, values = _get_vector(mobility, "host[0].mobility", signal)
        for v in values:
            assert abs(v) < 1e-10, f"{signal}: got {v}, expected 0"


def test_freefall_z_checkpoints(freefall_outputs):
    """Verify specific z values at t=1, 2, 3 against analytical solution."""
    beacon = freefall_outputs["beacon"]
    times, values = _get_vector(beacon, "host[0].wlan[0].mgmt",
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
    mobility = hover_outputs["mobility"]

    for host_idx in range(2):
        suffix = f"host[{host_idx}].mobility"
        recorded = {name for (mod, name) in mobility if mod.endswith(suffix)}
        missing = expected_signals - recorded
        assert not missing, f"host[{host_idx}] missing signals: {missing}"


def test_freefall_all_signals_recorded(freefall_outputs):
    """All 10 MultirotorMobility signals should be present."""
    expected_signals = {"thrust:vector", "tauPhi:vector", "tauTheta:vector",
                        "tauPsi:vector", "phi:vector", "theta:vector",
                        "psi:vector", "omegaP:vector", "omegaQ:vector",
                        "omegaR:vector"}
    mobility = freefall_outputs["mobility"]

    recorded = {name for (mod, name) in mobility
                if mod.endswith("host[0].mobility")}
    missing = expected_signals - recorded
    assert not missing, f"Missing signals: {missing}"
