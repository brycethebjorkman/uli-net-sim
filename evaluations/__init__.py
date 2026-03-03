"""
Remote ID Spoofing Detection - Evaluation Framework

This package provides infrastructure for training (parameter optimization) and
evaluating spoofing detection methods on simulated UAV Remote ID data.

Detection Methods:
1. Kalman Filter (KF) - Threshold on KF NIS from single receiver
2. RSSI Multilateration (MLAT) - Federated position estimation from multiple receivers

Two-stage CLI workflow:

    # Stage 1: Score test set (expensive)
    python -m evaluations.unified_eval score \\
        --train-dir datasets/scitech26/train \\
        --test-dir datasets/scitech26/test \\
        -o evaluations/results/

    # Stage 2: Analyze scores (cheap, iterate freely)
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
from .metrics import DetectionMetrics, compute_metrics, compute_roc_auc, compute_distance_stats
from .data import load_scenario, load_dataset, iter_dataset, ScenarioData
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
    "iter_dataset",
    "ScenarioData",
    # Metrics
    "DetectionMetrics",
    "compute_metrics",
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
