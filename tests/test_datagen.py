"""
Regression tests for datagen tools and OMNeT++ simulation.

Verifies that urbanenv generators and simulation produce bit-for-bit
identical outputs with fixed seeds.

To update hashes after intentional changes, run the tests with --update-hashes:
    pytest tests/ -v --update-hashes
"""

import json
from pathlib import Path

import pytest

from .conftest import hash_file, extract_our_vectors, diff_vector_hashes
from .test_eval_pipeline import hash_parquet_data
from datagen.vec2parquet import hash_vector_data

# Expected SHA256 hashes (update these when pipeline changes intentionally)
EXPECTED = {
    "corridors.ndjson":  "400414d7074120791ab04ffc7b5f00473d348dd3aa13c16dc49d64d932ba520a",
    "buildings.xml":     "7cb38f3c58eb84eaa79aade9daa469a4d5c766fd11e8acb7cd0f019a334ca0b5",
    "trajectories.xml":  "81acc917eea2c3b3a616afce5d93aabeaf0cfa9bd6d2d212c0b96bca421d935e",
    "scenario.ini":      "29405c20f27a02f4fd1a6d4f9e1acbbe116c45b3762ce2498009ed79d3992ff6",
    "raw_scenario.parquet": "f4bba8113b0c76265024ba7b8d9c4594fda572c3fd6ce0f947a6db8569b2a681",
}

EXPECTED_VEC_HASHES_FILE = Path(__file__).parent / "expected_hashes" / "datagen_scenario.json"


def test_generate_corridors(datagen_outputs):
    assert hash_file(datagen_outputs["corridors.ndjson"]) == EXPECTED["corridors.ndjson"]


def test_generate_buildings(datagen_outputs):
    assert hash_file(datagen_outputs["buildings.xml"]) == EXPECTED["buildings.xml"]


def test_generate_trajectories(datagen_outputs):
    assert hash_file(datagen_outputs["trajectories.xml"]) == EXPECTED["trajectories.xml"]


def test_generate_scenario(datagen_outputs):
    assert hash_file(datagen_outputs["scenario_inis"]["scenario_seed1.ini"]) == EXPECTED["scenario.ini"]


def test_simulation_vec(sim_outputs):
    vectors = extract_our_vectors(sim_outputs["scenario.vec"])
    actual = {f"{mod}||{name}": hash_vector_data(times, values)
              for (mod, name), (times, values) in vectors.items()}
    if not EXPECTED_VEC_HASHES_FILE.exists():
        pytest.fail(f"Create {EXPECTED_VEC_HASHES_FILE} with:\n"
                    f"{json.dumps(actual, indent=2, sort_keys=True)}")
    with open(EXPECTED_VEC_HASHES_FILE) as f:
        expected = json.load(f)
    if actual != expected:
        diff = diff_vector_hashes(expected, actual)
        pytest.fail(f"Scenario .vec vector hashes changed:\n{diff}")


def test_simulation_parquet(sim_outputs):
    assert hash_parquet_data(sim_outputs["raw.parquet"]) == EXPECTED["raw_scenario.parquet"]


def test_vec2parquet_raw_mode(sim_outputs, tmp_path):
    """Exercise vec2parquet --raw CLI mode."""
    from datagen.vec2parquet import main as v2p_main
    out = tmp_path / "raw.parquet"
    v2p_main([str(sim_outputs["scenario.vec"]), "--raw", "-o", str(out)])
    assert out.exists()
    import pyarrow.parquet as pq
    table = pq.read_table(out)
    assert set(table.column_names) == {"module", "name", "times", "values"}
    assert len(table) > 0


def test_vec2parquet_hash_mode(sim_outputs, capsys):
    """Exercise vec2parquet --hash CLI mode."""
    from datagen.vec2parquet import main as v2p_main
    v2p_main([str(sim_outputs["scenario.vec"]), "--hash"])
    captured = capsys.readouterr()
    hashes = json.loads(captured.out)
    assert len(hashes) > 0
    assert all(len(v) == 64 for v in hashes.values())  # SHA256 hex


def test_vec2parquet_default_mode(sim_outputs, tmp_path):
    """Exercise vec2parquet default (event-per-row) CLI mode."""
    from datagen.vec2parquet import main as v2p_main
    out = tmp_path / "events.parquet"
    v2p_main([str(sim_outputs["scenario.vec"]), "-o", str(out),
              "--spoofer-hosts", "1"])
    assert out.exists()
    import pandas as pd
    df = pd.read_parquet(out)
    assert "host_type" in df.columns
    assert "is_spoofed" in df.columns
    assert len(df) > 0
