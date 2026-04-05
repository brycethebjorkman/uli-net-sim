"""
End-to-end pipeline test exercising the full researcher workflow:

    generate_dataset.py → split_dataset.py → unified_eval train → score → analyze

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
    "kf": {"auc": 0.7594352792648433, "tpr": 0.7581120943952803, "fpr": 0.37037037037037035,
           "tp": 257, "tn": 1224, "fp": 720, "fn": 82},
    "mlat": {"auc": 0.7860023041474654, "tpr": 1.0, "fpr": 1.0,
             "tp": 56, "tn": 0, "fp": 124, "fn": 0},
    "mlp": {"auc": 0.8204664254121432, "tpr": 0.3333333333333333, "fpr": 0.018094089264173704,
            "tp": 38, "tn": 814, "fp": 15, "fn": 76},
}


@pytest.fixture(scope="session")
def e2e_results():
    """Run the full pipeline: generate → split → train → score → analyze."""
    base = _clean_dir(TEST_OUT / "e2e")
    results_dir = base / "results"
    results_dir.mkdir()

    # 1. Generate dataset
    sys.path.insert(0, str(REPO_ROOT))
    from datagen.generate_dataset import main as generate_main
    generate_main([
        "--grid-size", "300",
        "--num-hosts", "8",
        "--sim-time", "30",
        "--scenario-variants", "4",
        "--enable-spoofer",
        "--seed", "77",
        "-o", str(base),
    ])

    # 2. Split into train/test
    from datagen.split_dataset import split_dataset
    train_dir, test_dir = split_dataset(base, train_ratio=0.75, seed=42)

    # 3. Train → Score → Analyze (in-process for coverage)
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
    if EXPECTED is None:
        pytest.fail(
            f"Bootstrap EXPECTED with:\n"
            f'"kf": {{"auc": {kf["auc"]}, "tpr": {kf["tpr"]}, "fpr": {kf["fpr"]}, '
            f'"tp": {kf["tp"]}, "tn": {kf["tn"]}, "fp": {kf["fp"]}, "fn": {kf["fn"]}}}'
        )
    e = EXPECTED["kf"]
    assert kf["auc"] == pytest.approx(e["auc"], abs=1e-6)
    assert kf["tpr"] == pytest.approx(e["tpr"], abs=1e-6)
    assert kf["fpr"] == pytest.approx(e["fpr"], abs=1e-6)
    assert (kf["tp"], kf["tn"], kf["fp"], kf["fn"]) == (e["tp"], e["tn"], e["fp"], e["fn"])


def test_mlat_metrics(e2e_results):
    mlat = e2e_results["results"]["mlat"]
    if EXPECTED is None:
        pytest.fail(
            f"Bootstrap EXPECTED with:\n"
            f'"mlat": {{"auc": {mlat["auc"]}, "tpr": {mlat["tpr"]}, "fpr": {mlat["fpr"]}, '
            f'"tp": {mlat["tp"]}, "tn": {mlat["tn"]}, "fp": {mlat["fp"]}, "fn": {mlat["fn"]}}}'
        )
    e = EXPECTED["mlat"]
    assert mlat["auc"] == pytest.approx(e["auc"], abs=1e-6)
    assert mlat["tpr"] == pytest.approx(e["tpr"], abs=1e-6)
    assert mlat["fpr"] == pytest.approx(e["fpr"], abs=1e-6)
    assert (mlat["tp"], mlat["tn"], mlat["fp"], mlat["fn"]) == (e["tp"], e["tn"], e["fp"], e["fn"])


def test_mlp_metrics(e2e_results):
    mlp = e2e_results["results"]["mlp"]
    if EXPECTED is None:
        pytest.fail(
            f"Bootstrap EXPECTED with:\n"
            f'"mlp": {{"auc": {mlp["auc"]}, "tpr": {mlp["tpr"]}, "fpr": {mlp["fpr"]}, '
            f'"tp": {mlp["tp"]}, "tn": {mlp["tn"]}, "fp": {mlp["fp"]}, "fn": {mlp["fn"]}}}'
        )
    e = EXPECTED["mlp"]
    assert mlp["auc"] == pytest.approx(e["auc"], abs=1e-6)
    assert mlp["tpr"] == pytest.approx(e["tpr"], abs=1e-6)
    assert mlp["fpr"] == pytest.approx(e["fpr"], abs=1e-6)
    assert (mlp["tp"], mlp["tn"], mlp["fp"], mlp["fn"]) == (e["tp"], e["tn"], e["fp"], e["fn"])
