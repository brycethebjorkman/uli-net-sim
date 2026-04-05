"""
Regression tests for scenario regeneration round-trip.

Verifies that regenerate_scenario.py can reproduce a scenario parquet
from a manifest — proving the manifest contains all parameters needed
for deterministic reproduction.

Pipeline: generate_dataset.py → pick parquet → delete → regenerate → compare
"""

import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import REPO_ROOT, TEST_OUT, _clean_dir
from .test_eval_pipeline import hash_parquet_data

REGENERATE = REPO_ROOT / "datagen" / "regenerate_scenario.py"
PYTHON = sys.executable


@pytest.fixture(scope="session")
def regen_dataset():
    """Run generate_dataset.py to produce a small dataset with manifest."""
    out = _clean_dir(TEST_OUT / "regen")

    sys.path.insert(0, str(REPO_ROOT))
    from datagen.generate_dataset import main as generate_main
    generate_main([
        "--grid-size", "300",
        "--num-hosts", "4",
        "--sim-time", "20",
        "--num-ew", "2",
        "--num-ns", "2",
        "--num-buildings", "5",
        "--building-height", "50-100",
        "--speed", "8-12",
        "--altitude", "40-80",
        "--scenario-variants", "1",
        "--enable-spoofer",
        "--seed", "99",
        "-o", str(out),
    ])

    manifest_path = out / "manifest.json"
    assert manifest_path.exists(), f"Manifest not found: {manifest_path}"

    # Find all parquet files in the dataset
    parquets = sorted((out / "urbanenv").rglob("*.parquet"))
    assert len(parquets) > 0, "No parquet files produced by generate_dataset.sh"

    return {
        "manifest": manifest_path,
        "parquets": parquets,
        "base": out,
    }


def test_regeneration_round_trip(regen_dataset):
    """Delete a parquet and regenerate it, verify content hash matches."""
    manifest_path = regen_dataset["manifest"]
    parquet_path = regen_dataset["parquets"][0]

    # Record initial content hash
    initial_hash = hash_parquet_data(parquet_path)

    # Delete the parquet to force regeneration
    parquet_path.unlink()
    assert not parquet_path.exists()

    # Run regenerate_scenario.py
    result = subprocess.run(
        [str(PYTHON), str(REGENERATE), str(manifest_path), parquet_path.name],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"regenerate_scenario.py failed (exit {result.returncode}):\n"
        f"stdout: {result.stdout[-3000:]}\n"
        f"stderr: {result.stderr[-3000:]}"
    )

    # Verify the regenerated parquet exists and matches
    assert parquet_path.exists(), f"Regenerated parquet not found: {parquet_path}"
    regenerated_hash = hash_parquet_data(parquet_path)
    assert regenerated_hash == initial_hash, (
        f"Regenerated parquet content differs!\n"
        f"  Initial:     {initial_hash}\n"
        f"  Regenerated: {regenerated_hash}"
    )
