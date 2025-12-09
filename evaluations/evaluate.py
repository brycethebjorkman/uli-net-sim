"""
Evaluation runner for spoofing detectors.

Evaluates detectors on test data using optimized parameters from training.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
import json
import numpy as np

from .data import ScenarioData, iter_dataset, load_dataset
from .detectors import Detector
from .metrics import DetectionMetrics, compute_metrics
from .optimize import OptimizationResult, collect_scores_and_labels


@dataclass
class EvaluationResult:
    """Result of evaluating a detector on test data."""

    detector_name: str
    threshold: float
    params: dict

    # Aggregate metrics across all test scenarios
    metrics: DetectionMetrics

    # Per-scenario time-to-detection (for scenarios with spoofers)
    time_to_detection_list: list[float]

    @property
    def mean_time_to_detection(self) -> float | None:
        if not self.time_to_detection_list:
            return None
        return float(np.mean(self.time_to_detection_list))

    @property
    def median_time_to_detection(self) -> float | None:
        if not self.time_to_detection_list:
            return None
        return float(np.median(self.time_to_detection_list))

    def __str__(self) -> str:
        ttd_mean = self.mean_time_to_detection
        ttd_str = f"{ttd_mean:.3f}s" if ttd_mean is not None else "N/A"
        return (
            f"EvaluationResult(\n"
            f"  detector={self.detector_name}\n"
            f"  threshold={self.threshold:.4f}\n"
            f"  AUC={self.metrics.auc:.4f}\n"
            f"  TPR={self.metrics.tpr:.4f}, FPR={self.metrics.fpr:.4f}\n"
            f"  Mean Time-to-Detection={ttd_str}\n"
            f"  Scenarios with TTD: {len(self.time_to_detection_list)}\n"
            f")"
        )

    def to_dict(self) -> dict:
        return {
            "detector_name": self.detector_name,
            "threshold": self.threshold,
            "params": self.params,
            "metrics": self.metrics.to_dict(),
            "mean_time_to_detection": self.mean_time_to_detection,
            "median_time_to_detection": self.median_time_to_detection,
            "n_scenarios_with_ttd": len(self.time_to_detection_list),
        }


def evaluate_detector(
    detector: Detector,
    threshold: float,
    scenarios: Iterator[ScenarioData] | list[ScenarioData],
    verbose: bool = False,
) -> EvaluationResult:
    """
    Evaluate a detector on test scenarios.

    Args:
        detector: Detector to evaluate
        threshold: Detection threshold (from optimization)
        scenarios: Test scenarios
        verbose: Print progress

    Returns:
        EvaluationResult with aggregate metrics
    """
    if verbose:
        print(f"Evaluating {detector.name} with threshold={threshold:.4f}...")

    all_times = []
    all_labels = []
    all_scores = []
    ttd_list = []

    for i, scenario in enumerate(scenarios):
        if verbose and i > 0 and i % 100 == 0:
            print(f"  Processed {i} scenarios...")

        scores = detector.score(scenario)
        all_times.append(scenario.time)
        all_labels.append(scenario.is_spoofed)
        all_scores.append(scores)

        # Compute per-scenario TTD
        if scenario.n_spoofed > 0:
            from .metrics import compute_time_to_detection
            ttd = compute_time_to_detection(
                scenario.time, scenario.is_spoofed, scores, threshold
            )
            if ttd is not None:
                ttd_list.append(ttd)

    times = np.concatenate(all_times)
    labels = np.concatenate(all_labels)
    scores = np.concatenate(all_scores)

    if verbose:
        print(f"  Total events: {len(labels)}, spoofed: {np.sum(labels)}")

    metrics = compute_metrics(times, labels, scores, threshold)

    if verbose:
        print(f"  {metrics}")

    return EvaluationResult(
        detector_name=detector.name,
        threshold=threshold,
        params=detector.params,
        metrics=metrics,
        time_to_detection_list=ttd_list,
    )


def run_evaluation(
    detector: Detector,
    train_dir: Path | str,
    test_dir: Path | str,
    output_path: Path | str | None = None,
    train_limit: int | None = None,
    test_limit: int | None = None,
    verbose: bool = True,
) -> tuple[OptimizationResult, EvaluationResult]:
    """
    Full evaluation pipeline: optimize on train, evaluate on test.

    Args:
        detector: Detector to evaluate
        train_dir: Directory with training CSVs
        test_dir: Directory with test CSVs
        output_path: Optional path to save results JSON
        train_limit: Limit training scenarios (for testing)
        test_limit: Limit test scenarios (for testing)
        verbose: Print progress

    Returns:
        Tuple of (OptimizationResult, EvaluationResult)
    """
    from .optimize import optimize_threshold

    train_dir = Path(train_dir)
    test_dir = Path(test_dir)

    # Optimize on training data
    if verbose:
        print(f"=== Training Phase ===")
        print(f"Loading training data from {train_dir}...")

    train_scenarios = load_dataset(train_dir, limit=train_limit)
    if verbose:
        print(f"Loaded {len(train_scenarios)} training scenarios")

    opt_result = optimize_threshold(detector, train_scenarios, verbose=verbose)

    # Evaluate on test data
    if verbose:
        print(f"\n=== Evaluation Phase ===")
        print(f"Loading test data from {test_dir}...")

    test_scenarios = iter_dataset(test_dir, limit=test_limit)

    eval_result = evaluate_detector(
        detector, opt_result.best_threshold, test_scenarios, verbose=verbose
    )

    # Save results
    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        results = {
            "optimization": {
                "detector_name": opt_result.detector_name,
                "best_threshold": opt_result.best_threshold,
                "best_auc": opt_result.best_auc,
                "best_params": opt_result.best_params,
            },
            "evaluation": eval_result.to_dict(),
        }

        with open(output_path, "w") as f:
            json.dump(results, f, indent=2)

        if verbose:
            print(f"\nResults saved to {output_path}")

    return opt_result, eval_result
