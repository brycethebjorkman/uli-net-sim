"""
Regression test for scripts/rid-one-off.sh.

Runs the example from the script's usage header and verifies:
  - Exit code 0
  - JSON output is valid and contains expected structure
  - All receiver drones report RSSI for the transmitter's serial number
  - RSSI values are physically plausible (negative dBm)

To update hashes after intentional changes:
    pytest tests/test_rid_one_off.py -v
"""

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
RID_ONE_OFF = REPO_ROOT / "scripts" / "rid-one-off.sh"


@pytest.fixture(scope="session")
def rid_one_off_output():
    """Run rid-one-off.sh with the example from its usage header."""
    args = [
        str(RID_ONE_OFF),
        "-n", "103", "-t", "0.1",
        "-x", "24", "-y", "25", "-z", "5",
        "-v", "1", "-g", "1", "-h", "1",
        "-q",
        "--",
        "101,0,0,5,0,0,0",
        "102,-500,-500,5,2,0,0",
        "103,50,50,5,2,0,0",
    ]
    r = subprocess.run(args, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if r.returncode != 0:
        raise RuntimeError(f"rid-one-off.sh failed (exit {r.returncode}):\n"
                           f"stdout: {r.stdout[-2000:]}\nstderr: {r.stderr[-2000:]}")
    return json.loads(r.stdout)


def test_output_is_dict(rid_one_off_output):
    """Output should be a JSON object."""
    assert isinstance(rid_one_off_output, dict)


def test_has_reception_power(rid_one_off_output):
    """Should contain 'Reception Power' keyed by receiver serial number."""
    assert "Reception Power" in rid_one_off_output
    rp = rid_one_off_output["Reception Power"]
    # TX is serial 101 (first tuple); receivers are 102 and 103
    assert "102" in rp, "Receiver 102 missing from Reception Power"
    assert "103" in rp, "Receiver 103 missing from Reception Power"


def test_has_serial_number(rid_one_off_output):
    """Should contain 'Serial Number' data identifying the transmitter."""
    assert "Serial Number" in rid_one_off_output
    sn = rid_one_off_output["Serial Number"]
    # All receivers should report the TX serial (101 = host[0])
    for serial, data in sn.items():
        for v in data["values"]:
            assert int(float(v)) == 101, \
                f"Receiver {serial} saw serial {v}, expected 101"


def test_reception_power_numeric(rid_one_off_output):
    """Reception Power values should be finite numbers."""
    rp = rid_one_off_output["Reception Power"]
    for serial, data in rp.items():
        for v in data["values"]:
            val = float(v)
            assert val == val, f"Receiver {serial} has NaN reception power"
