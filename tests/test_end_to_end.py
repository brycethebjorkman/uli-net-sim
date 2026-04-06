"""
End-to-end pipeline test exercising the full researcher workflow:

    generate_manifest → generate_scenario → run_batch → split → train → score → analyze

Validates that all three detectors (KF, MLAT, MLP) produce expected metric
values from unified_results.json. All seeds are fixed for determinism.
"""

import json
import sys
from pathlib import Path

import pytest

from .conftest import REPO_ROOT, TEST_OUT, _clean_dir

# Expected metrics (bootstrapped from first deterministic run)
EXPECTED = {
    "kf": {"auc": 0.765826520855559, "tpr": 0.7523219814241486, "fpr": 0.35302879841112217,
           "tp": 243, "tn": 1303, "fp": 711, "fn": 80},
    "mlat": {"auc": 0.7871888281724349, "tpr": 0.8518518518518519, "fpr": 0.819672131147541,
             "tp": 46, "tn": 22, "fp": 100, "fn": 8},
    "mlp": {"auc": 0.8080728482619735, "tpr": 0.25925925925925924, "fpr": 0.02009456264775414,
            "tp": 28, "tn": 829, "fp": 17, "fn": 80},
}


@pytest.fixture(scope="session")
def e2e_results():
    """Run the full pipeline: manifest → scenarios → batch → split → eval."""
    base = _clean_dir(TEST_OUT / "e2e")
    results_dir = base / "results"
    results_dir.mkdir()

    sys.path.insert(0, str(REPO_ROOT))

    # 1. Generate manifest
    from datagen.generate_manifest import main as manifest_main
    manifest_path = base / "manifest.json"
    manifest_main([
        "--grid-size", "300",
        "--num-hosts", "8",
        "--sim-time", "30",
        "--scenario-variants", "4",
        "--enable-spoofer",
        "--seed", "77",
        "-o", str(manifest_path),
    ])

    # 2. Materialize artifacts + INIs
    from datagen.generate_scenario import main as scenario_main
    scenario_main([str(manifest_path)])

    # 3. Run simulations
    from datagen.run_batch import discover_scenarios, run_batch
    urbanenv_dir = base / "urbanenv"
    venv_python = str(REPO_ROOT / ".venv" / "bin" / "python3")
    scenarios = discover_scenarios(
        urbanenv_dir, configs=["ScenarioOpenSpace", "ScenarioWithBuildings"])
    run_batch(scenarios, parallel=1, venv_python=venv_python)

    # 4. Split into train/test
    from datagen.split_dataset import split_dataset
    train_dir, test_dir = split_dataset(base, train_ratio=0.75, seed=42)

    # 5. Train → Score → Analyze (in-process for coverage)
    from evaluations.unified_eval import main as eval_main

    eval_main(["train",
               "--train-dir", str(train_dir),
               "-o", str(results_dir),
               "--seed", "42"])

    eval_main(["score",
               "--train-dir", str(train_dir),
               "--test-dir", str(test_dir),
               "-o", str(results_dir),
               "--seed", "42"])

    eval_main(["analyze",
               "--scores-dir", str(results_dir),
               "-o", str(results_dir)])

    # Load results
    with open(results_dir / "unified_results.json") as f:
        results = json.load(f)

    return {"results": results, "dir": results_dir}


def test_all_detectors_present(e2e_results):
    """All three detector keys must be present."""
    for key in ("kf", "mlat", "mlp"):
        assert key in e2e_results["results"], f"Missing detector: {key}"


def test_kf_metrics(e2e_results):
    kf = e2e_results["results"]["kf"]
    e = EXPECTED["kf"]
    assert kf["auc"] == pytest.approx(e["auc"], abs=1e-6)
    assert kf["tpr"] == pytest.approx(e["tpr"], abs=1e-6)
    assert kf["fpr"] == pytest.approx(e["fpr"], abs=1e-6)
    assert (kf["tp"], kf["tn"], kf["fp"], kf["fn"]) == (e["tp"], e["tn"], e["fp"], e["fn"])


def test_mlat_metrics(e2e_results):
    mlat = e2e_results["results"]["mlat"]
    e = EXPECTED["mlat"]
    assert mlat["auc"] == pytest.approx(e["auc"], abs=1e-6)
    assert mlat["tpr"] == pytest.approx(e["tpr"], abs=1e-6)
    assert mlat["fpr"] == pytest.approx(e["fpr"], abs=1e-6)
    assert (mlat["tp"], mlat["tn"], mlat["fp"], mlat["fn"]) == (e["tp"], e["tn"], e["fp"], e["fn"])


def test_mlp_metrics(e2e_results):
    mlp = e2e_results["results"]["mlp"]
    e = EXPECTED["mlp"]
    assert mlp["auc"] == pytest.approx(e["auc"], abs=1e-6)
    assert mlp["tpr"] == pytest.approx(e["tpr"], abs=1e-6)
    assert mlp["fpr"] == pytest.approx(e["fpr"], abs=1e-6)
    assert (mlp["tp"], mlp["tn"], mlp["fp"], mlp["fn"]) == (e["tp"], e["tn"], e["fp"], e["fn"])
