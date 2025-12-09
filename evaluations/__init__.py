"""
Remote ID Spoofing Detection - Evaluation Framework

This package provides infrastructure for training (parameter optimization) and
evaluating spoofing detection methods on simulated UAV Remote ID data.

Detection Methods:
1. Kalman Filter (KF) - Threshold on KF NIS from single receiver
2. RSSI Multilateration (MLAT) - Federated position estimation from multiple receivers

Usage:
    from evaluations import (
        KalmanFilterDetector,
        MultilatDetector,
        run_evaluation,
        load_dataset,
    )

    # Simple evaluation
    detector = KalmanFilterDetector()
    opt_result, eval_result = run_evaluation(
        detector,
        train_dir="datasets/scitech26/train",
        test_dir="datasets/scitech26/test",
    )

    # Grid search for multilateration parameters
    from evaluations.optimize import grid_search

    param_grid = {
        "path_loss_exp": [1.8, 2.0, 2.2],
        "min_receivers": [3, 4],
    }
    best_result, best_params = grid_search(
        MultilatDetector,
        param_grid,
        train_scenarios,
    )
"""

from .detectors import Detector, KalmanFilterDetector, MultilatDetector
from .metrics import DetectionMetrics, compute_metrics, compute_roc_auc
from .data import load_scenario, load_dataset, iter_dataset, ScenarioData
from .optimize import optimize_threshold, grid_search, OptimizationResult
from .evaluate import evaluate_detector, run_evaluation, EvaluationResult

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
    # Optimization
    "optimize_threshold",
    "grid_search",
    "OptimizationResult",
    # Evaluation
    "evaluate_detector",
    "run_evaluation",
    "EvaluationResult",
]
