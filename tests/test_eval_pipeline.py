"""
Regression tests for the evaluation pipeline (train → score → analyze).

Verifies that the pipeline produces identical data outputs given the same
inputs and seed. Parquet files are hashed by DataFrame content (not file
bytes) so results are stable across pyarrow versions.

To update hashes after intentional changes, run the tests with --update-hashes:
    .venv/bin/pytest tests/ -v --update-hashes
"""

import hashlib

import pandas as pd

from .conftest import hash_file


def hash_parquet_data(path) -> str:
    """Hash the data content of a Parquet file (column values, not file encoding).

    Converts all columns to float64 or string bytes for deterministic hashing,
    handling nullable integer columns and mixed types gracefully.
    """
    df = pd.read_parquet(path)
    h = hashlib.sha256()
    for col in df.columns:
        h.update(col.encode())
        series = df[col]
        if pd.api.types.is_numeric_dtype(series):
            h.update(series.astype('float64').to_numpy().tobytes())
        else:
            h.update(series.astype(str).str.encode('utf-8').sum())
    return h.hexdigest()


EXPECTED = {
    "thresholds.json":      "3260381fe4ac81502261bb0e8922293f5fdedc5cb8147740a5851ffffed03745",
    "kf_scores.parquet":    "588eee06422e82274549d6587202a5f1a28d8668da992efed8aa895d81dc629b",
    "mlat_scores.parquet":  "c08d79f75a10847cb781b1ac2f504ed25e7b1afc9ef304e1f208bccd7ec7f17c",
    "mlp_scores.parquet":   "94b696664b958f5a2a24e85fe54fc2137839153ff39b7238b5d36d867d91c3b1",
    "unified_results.json": "6a1a7cfc987ae3f7c38e6a5ab01e8a9127ee95f6de9902b5acdc202030e55db3",
}


def test_thresholds_json(eval_outputs):
    assert hash_file(eval_outputs["thresholds.json"]) == EXPECTED["thresholds.json"]


def test_kf_scores(eval_outputs):
    assert hash_parquet_data(eval_outputs["kf_scores.parquet"]) == EXPECTED["kf_scores.parquet"]


def test_mlat_scores(eval_outputs):
    assert hash_parquet_data(eval_outputs["mlat_scores.parquet"]) == EXPECTED["mlat_scores.parquet"]


def test_mlp_scores(eval_outputs):
    assert hash_parquet_data(eval_outputs["mlp_scores.parquet"]) == EXPECTED["mlp_scores.parquet"]


def test_unified_results(eval_outputs):
    assert hash_file(eval_outputs["unified_results.json"]) == EXPECTED["unified_results.json"]
