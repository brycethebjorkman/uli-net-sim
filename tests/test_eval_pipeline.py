"""
Regression tests for the evaluation pipeline (train → score → analyze).

Verifies that the pipeline produces bit-for-bit identical outputs
given the same inputs and seed.

To update hashes after intentional changes, run the tests with --update-hashes:
    .venv/bin/pytest tests/ -v --update-hashes
"""

from .conftest import hash_file

EXPECTED = {
    "thresholds.json":      "3260381fe4ac81502261bb0e8922293f5fdedc5cb8147740a5851ffffed03745",
    "kf_scores.csv":        "8daccb0088cb7506ed9215c8966cc1e98a7f9bb15b7a586a9aa66e7cdd953908",
    "mlat_scores.csv":      "78323c0b2029f74e3cf69d02fbfefe4c371402aca3ba5e50aa32b5c4a64abadb",
    "mlp_scores.csv":       "61e6111b43ec57944813e8a0c528fb4d293222e7458216b4a01c71b509008eef",
    "unified_results.json": "c78f34e5adad65b6d1cdb3ff1146d30c783b8c6ef5c15bf71707489b7523f1bf",
}


def test_thresholds_json(eval_outputs):
    assert hash_file(eval_outputs["thresholds.json"]) == EXPECTED["thresholds.json"]


def test_kf_scores(eval_outputs):
    assert hash_file(eval_outputs["kf_scores.csv"]) == EXPECTED["kf_scores.csv"]


def test_mlat_scores(eval_outputs):
    assert hash_file(eval_outputs["mlat_scores.csv"]) == EXPECTED["mlat_scores.csv"]


def test_mlp_scores(eval_outputs):
    assert hash_file(eval_outputs["mlp_scores.csv"]) == EXPECTED["mlp_scores.csv"]


def test_unified_results(eval_outputs):
    assert hash_file(eval_outputs["unified_results.json"]) == EXPECTED["unified_results.json"]
