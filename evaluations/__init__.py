"""
Remote ID Spoofing Detection - Evaluation Framework

This package provides infrastructure for training (parameter optimization) and
evaluating spoofing detection methods on simulated UAV Remote ID data.

Detection Methods:
1. Kalman Filter (KF) - Threshold on KF NIS from single receiver
2. RSSI Multilateration (MLAT) - Federated position estimation from multiple receivers

Usage:
    # Run unified evaluation comparing KF and MLAT
    python -m evaluations.unified_eval \\
        --train-dir datasets/scitech26/train \\
        --test-dir datasets/scitech26/test \\
        -o evaluations/results/

    # Programmatic usage
    from evaluations import (
        KalmanFilterDetector,
        MultilatDetector,
        load_dataset,
        optimize_threshold,
    )

    detector = KalmanFilterDetector()
    scenarios = load_dataset("datasets/scitech26/train")
    result = optimize_threshold(detector, scenarios, federate_only=True)
    print(f"Best threshold: {result.best_threshold}")
"""

from .detectors import Detector, KalmanFilterDetector, MultilatDetector
from .metrics import DetectionMetrics, compute_metrics, compute_roc_auc
from .data import load_scenario, load_dataset, iter_dataset, ScenarioData
from .optimize import optimize_threshold, OptimizationResult

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
    "OptimizationResult",
]
