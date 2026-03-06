"""
Remote ID Spoofing Detection - Evaluation Framework

This package provides infrastructure for training (parameter optimization) and
evaluating spoofing detection methods on simulated UAV Remote ID data.

Detection Methods:
1. Kalman Filter (KF) - Threshold on KF NIS from single receiver
2. RSSI Multilateration (MLAT) - Federated position estimation from multiple receivers
3. Multilayer Perceptron (MLP) - Supervised learning on per-transmission features

Three-stage CLI workflow:

    # Stage 1: Train detectors (optimize thresholds, train MLP)
    python -m evaluations.unified_eval train \\
        --train-dir datasets/scitech26/train \\
        -o evaluations/results/

    # Stage 2: Score test set (expensive)
    python -m evaluations.unified_eval score \\
        --train-dir datasets/scitech26/train \\
        --test-dir datasets/scitech26/test \\
        -o evaluations/results/

    # Stage 3: Analyze scores (cheap, iterate freely)
    python -m evaluations.unified_eval analyze \\
        --scores-dir evaluations/results/ \\
        -o evaluations/results/

Programmatic usage:

    from evaluations import (
        KalmanFilterDetector,
        MultilatDetector,
        load_dataset,
        optimize_threshold,
        score_test_set,
        analyze_scores,
    )
"""

from .detectors import Detector, KalmanFilterDetector, MultilatDetector
from .metrics import compute_roc_auc, compute_distance_stats
from .data import load_scenario, load_dataset, ScenarioData
from .optimize import optimize_threshold, OptimizationResult, train_thresholds
from .scoring import score_test_set, compute_sample_distances
from .analysis import analyze_scores

__all__ = [
    # Detectors
    "Detector",
    "KalmanFilterDetector",
    "MultilatDetector",
    # Data
    "load_scenario",
    "load_dataset",
    "ScenarioData",
    # Metrics
    "compute_roc_auc",
    "compute_distance_stats",
    # Optimization
    "optimize_threshold",
    "OptimizationResult",
    "train_thresholds",
    # Scoring
    "score_test_set",
    "compute_sample_distances",
    # Analysis
    "analyze_scores",
]
