"""
Regression tests for scenario regeneration round-trip.

Verifies that generate_scenario.py can reproduce a scenario's INI and
parquet from a manifest — proving the manifest contains all parameters
needed for deterministic reproduction.

Pipeline: generate_manifest → generate_scenario → run_batch → pick parquet
          → delete INI + parquet → generate_scenario (regen) → run_batch → compare
"""

import sys
from pathlib import Path

import pytest

from .conftest import REPO_ROOT, TEST_OUT, _clean_dir
from .test_eval_pipeline import hash_parquet_data


@pytest.fixture(scope="session")
def regen_dataset():
    """Generate a small dataset via the manifest-driven pipeline."""
    out = _clean_dir(TEST_OUT / "regen")

    sys.path.insert(0, str(REPO_ROOT))

    # 1. Create manifest
    from datagen.generate_manifest import main as manifest_main
    manifest_path = out / "manifest.json"
    manifest_main([
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
        "-o", str(manifest_path),
    ])
    assert manifest_path.exists()

    # 2. Materialize artifacts + INIs
    from datagen.generate_scenario import main as scenario_main
    scenario_main([str(manifest_path)])

    # 3. Run simulations
    from datagen.run_batch import discover_scenarios, run_batch
    urbanenv_dir = out / "urbanenv"
    scenarios = discover_scenarios(
        urbanenv_dir, configs=["ScenarioOpenSpace", "ScenarioWithBuildings"])
    run_batch(scenarios, parallel=1,
              venv_python=str(REPO_ROOT / ".venv" / "bin" / "python3"))

    # Find all parquet files in the dataset
    parquets = sorted(urbanenv_dir.rglob("*.parquet"))
    assert len(parquets) > 0, "No parquet files produced"

    return {
        "manifest": manifest_path,
        "parquets": parquets,
        "base": out,
    }


def test_regeneration_round_trip(regen_dataset):
    """Delete INI + parquet, regenerate from manifest, verify hash matches."""
    manifest_path = regen_dataset["manifest"]
    parquet_path = regen_dataset["parquets"][0]

    # Record initial content hash
    initial_hash = hash_parquet_data(parquet_path)

    # Delete the parquet AND its INI to force full regeneration
    scenario_dir = parquet_path.parent
    ini_path = scenario_dir / "omnetpp.ini"
    parquet_path.unlink()
    if ini_path.exists():
        ini_path.unlink()

    assert not parquet_path.exists()
    assert not ini_path.exists()

    # Regenerate INI from manifest (selective)
    from datagen.generate_scenario import main as scenario_main
    scenario_main([str(manifest_path), "--scenarios", parquet_path.name])

    assert ini_path.exists(), f"Regenerated INI not found: {ini_path}"

    # Re-run simulation for this scenario
    from datagen.run_scenario import run_scenario
    venv_python = str(REPO_ROOT / ".venv" / "bin" / "python3")

    # Determine which config to run from the parquet filename suffix
    if parquet_path.name.endswith("-o.parquet"):
        configs = ["ScenarioOpenSpace"]
    elif parquet_path.name.endswith("-b.parquet"):
        configs = ["ScenarioWithBuildings"]
    else:
        configs = None  # auto-detect

    run_scenario(scenario_dir, venv_python=venv_python, configs=configs)

    # Verify the regenerated parquet exists and matches
    assert parquet_path.exists(), f"Regenerated parquet not found: {parquet_path}"
    regenerated_hash = hash_parquet_data(parquet_path)
    assert regenerated_hash == initial_hash, (
        f"Regenerated parquet content differs!\n"
        f"  Initial:     {initial_hash}\n"
        f"  Regenerated: {regenerated_hash}"
    )
