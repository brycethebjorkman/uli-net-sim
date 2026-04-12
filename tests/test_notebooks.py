"""
Smoke tests for converted Jupyter notebooks (percent-format .py files).

Executes each notebook as a script and verifies it doesn't crash.
Visualization notebooks are self-contained; evaluation notebooks receive
test-generated data paths via environment variables.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from .conftest import REPO_ROOT, PYTHON

# ---------------------------------------------------------------------------
# Self-contained visualization notebooks (no external data needed)
# ---------------------------------------------------------------------------

# Non-interactive rendering: suppress browser popups from fig.show() / plt.show()
HEADLESS_ENV = {
    **os.environ,
    "PLOTLY_RENDERER": "json",
    "MPLBACKEND": "Agg",
}

VISUALIZATION_NOTEBOOKS = [
    ("datagen/urbanenv/corridor_visualization.py", "datagen/urbanenv"),
    ("datagen/urbanenv/building_visualization.py", "datagen/urbanenv"),
    ("datagen/urbanenv/trajectory_visualization.py", "datagen/urbanenv"),
]


@pytest.mark.parametrize("script,cwd", VISUALIZATION_NOTEBOOKS,
                         ids=[s.split("/")[-1] for s, _ in VISUALIZATION_NOTEBOOKS])
def test_visualization_notebook(script, cwd):
    """Execute a visualization notebook and verify it exits cleanly."""
    result = subprocess.run(
        [PYTHON, str(REPO_ROOT / script)],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT / cwd),
        env=HEADLESS_ENV, timeout=120,
    )
    assert result.returncode == 0, (
        f"{script} failed (exit {result.returncode}):\n"
        f"stderr: {result.stderr[-3000:]}"
    )


# ---------------------------------------------------------------------------
# Evaluation notebooks (need test-generated data via env vars)
# ---------------------------------------------------------------------------

def _find_spoofed_scenario(test_dir: Path) -> Path:
    """Find a test parquet that contains spoofed events."""
    import pandas as pd
    for pq in sorted(test_dir.glob("*.parquet")):
        df = pd.read_parquet(pq, columns=["is_spoofed"])
        if df["is_spoofed"].any():
            return pq
    # Fall back to first file
    return next(test_dir.glob("*.parquet"))


def test_kalman_filter_notebook(sim_outputs):
    """Execute kalman_filter_detection.py with test data."""
    scenario = _find_spoofed_scenario(sim_outputs["test"])
    env = {**HEADLESS_ENV, "NOTEBOOK_SCENARIO": str(scenario)}

    result = subprocess.run(
        [PYTHON, str(REPO_ROOT / "evaluations/notebooks/kalman_filter_detection.py")],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT / "evaluations/notebooks"),
        env=env, timeout=120,
    )
    assert result.returncode == 0, (
        f"kalman_filter_detection.py failed:\nstderr: {result.stderr[-3000:]}"
    )


def test_multilateration_notebook(sim_outputs):
    """Execute multilateration_detection.py with test data."""
    scenario = _find_spoofed_scenario(sim_outputs["test"])
    env = {**HEADLESS_ENV, "NOTEBOOK_SCENARIO": str(scenario)}

    result = subprocess.run(
        [PYTHON, str(REPO_ROOT / "evaluations/notebooks/multilateration_detection.py")],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT / "evaluations/notebooks"),
        env=env, timeout=120,
    )
    assert result.returncode == 0, (
        f"multilateration_detection.py failed:\nstderr: {result.stderr[-3000:]}"
    )


def test_evaluation_analysis_notebook(sim_outputs, eval_outputs):
    """Execute evaluation_analysis.py with test data and scores."""
    scores_dir = eval_outputs["kf_scores.parquet"].parent
    env = {
        **HEADLESS_ENV,
        "NOTEBOOK_DATA_DIR": str(sim_outputs["test"]),
        "NOTEBOOK_SCORES_DIR": str(scores_dir),
    }

    result = subprocess.run(
        [PYTHON, str(REPO_ROOT / "evaluations/notebooks/evaluation_analysis.py")],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT / "evaluations/notebooks"),
        env=env, timeout=120,
    )
    assert result.returncode == 0, (
        f"evaluation_analysis.py failed:\nstderr: {result.stderr[-3000:]}"
    )


def test_scenario_animation_notebook(sim_outputs):
    """Execute datavis/scenario_animation.py with test data."""
    scenario = _find_spoofed_scenario(sim_outputs["test"])
    env = {
        **HEADLESS_ENV,
        "NOTEBOOK_SCENARIO": str(scenario),
    }

    result = subprocess.run(
        [PYTHON, str(REPO_ROOT / "datavis/scenario_animation.py")],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT / "datavis"),
        env=env, timeout=120,
    )
    assert result.returncode == 0, (
        f"datavis/scenario_animation.py failed:\nstderr: {result.stderr[-3000:]}"
    )
