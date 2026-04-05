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
    "thresholds.json":      "c21e01cb305487ac5c84c91f943519b85d7a48c448dc87d94f6c899d7b0b4c3f",
    "kf_scores.parquet":    "f6eecaf9f02d2b2144db9cc16936b8fb9cbb0870d0c02e4ce6f5d881f6f5a509",
    "mlat_scores.parquet":  "485c6ee1909e5e6ade99c7f009fccf779c4f36ba60b1326ad6c11ad68d786911",
    "mlp_scores.parquet":   "6aeefd9682a2304d647d60ed8aaffb0a4f44f284fc68f3f82c4a4fecf4ab2135",
    "unified_results.json": "c2f7ee188bb6bb41b6098a2139382347c4294d6c472fd065719066c0c80b090b",
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
