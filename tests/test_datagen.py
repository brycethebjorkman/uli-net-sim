"""
Regression tests for datagen tools and OMNeT++ simulation.

Verifies that urbanenv generators and simulation produce bit-for-bit
identical outputs with fixed seeds.

To update hashes after intentional changes, run the tests with --update-hashes:
    .venv/bin/pytest tests/ -v --update-hashes
"""

import json
from pathlib import Path

import pytest

from .conftest import hash_file, extract_our_vectors, diff_vector_hashes
from datagen.vec2parquet import hash_vector_data

# Expected SHA256 hashes (update these when pipeline changes intentionally)
EXPECTED = {
    "corridors.ndjson":  "400414d7074120791ab04ffc7b5f00473d348dd3aa13c16dc49d64d932ba520a",
    "buildings.xml":     "7cb38f3c58eb84eaa79aade9daa469a4d5c766fd11e8acb7cd0f019a334ca0b5",
    "trajectories.xml":  "81acc917eea2c3b3a616afce5d93aabeaf0cfa9bd6d2d212c0b96bca421d935e",
    "scenario.ini":      "81d093802ddfab2c0b1f9eb9e2e980e24a003f7427198ffd38760dad9b258057",
    "raw_scenario.csv":  "4dd9f773ca3273c8bb08c3c2c510d2e6d667891f6d2bd5c7606a0aedbe8722a3",
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


def test_simulation_csv(sim_outputs):
    assert hash_file(sim_outputs["raw.csv"]) == EXPECTED["raw_scenario.csv"]
