"""
Parameter optimization for spoofing detectors.

Optimization strategies:
1. Line search for detection threshold (maximize AUC or find operating point)
2. Grid search for detector parameters (path loss model, etc.)

Uses training set to find optimal parameters, then evaluates on test set.
"""

from dataclasses import dataclass
from typing import Callable, Iterator
import numpy as np

from .data import ScenarioData, iter_dataset
from .detectors import Detector
from .metrics import compute_roc_auc, compute_confusion_at_threshold


@dataclass
class OptimizationResult:
    """Result of parameter optimization."""

    detector_name: str
    best_threshold: float
    best_auc: float
    best_params: dict

    # ROC curve from training data
    fpr_curve: np.ndarray
    tpr_curve: np.ndarray
    thresholds: np.ndarray

    def __str__(self) -> str:
        return (
            f"OptimizationResult(\n"
            f"  detector={self.detector_name}\n"
            f"  best_threshold={self.best_threshold:.4f}\n"
            f"  best_auc={self.best_auc:.4f}\n"
            f"  best_params={self.best_params}\n"
            f")"
        )

    def find_threshold_for_fpr(self, target_fpr: float) -> float:
        """Find threshold that achieves target FPR (or closest below)."""
        # FPR decreases as threshold increases
        valid = self.fpr_curve <= target_fpr
        if not np.any(valid):
            return self.thresholds[-1]  # Highest threshold
        return self.thresholds[valid][0]

    def find_threshold_for_tpr(self, target_tpr: float) -> float:
        """Find threshold that achieves target TPR (or closest above)."""
        # TPR decreases as threshold increases
        valid = self.tpr_curve >= target_tpr
        if not np.any(valid):
            return self.thresholds[0]  # Lowest threshold
        return self.thresholds[valid][-1]


def collect_scores_and_labels(
    detector: Detector,
    scenarios: Iterator[ScenarioData] | list[ScenarioData],
    verbose: bool = False,
    federate_only: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Collect detection scores and ground truth labels from scenarios.

    Args:
        detector: Detector to evaluate
        scenarios: Iterator or list of ScenarioData
        verbose: Print progress
        federate_only: If True, only include RX events from federate receivers

    Returns:
        Tuple of (times, labels, scores) arrays concatenated across scenarios
    """
    all_times = []
    all_labels = []
    all_scores = []

    for i, scenario in enumerate(scenarios):
        if verbose and i > 0 and i % 100 == 0:
            print(f"  Processed {i} scenarios...")

        scores = detector.score(scenario)

        if federate_only:
            # Filter to federate receivers only
            federate_ids = set(scenario.federate_host_ids)
            mask = np.array([hid in federate_ids for hid in scenario.host_id])
            scores = scores[mask]
            times = scenario.time[mask]
            labels = scenario.is_spoofed[mask]
        else:
            times = scenario.time
            labels = scenario.is_spoofed

        all_times.append(times)
        all_labels.append(labels)
        all_scores.append(scores)

    return (
        np.concatenate(all_times),
        np.concatenate(all_labels),
        np.concatenate(all_scores),
    )


def optimize_threshold(
    detector: Detector,
    scenarios: Iterator[ScenarioData] | list[ScenarioData],
    verbose: bool = False,
    federate_only: bool = False,
) -> OptimizationResult:
    """
    Find optimal detection threshold using AUC on training data.

    Args:
        detector: Detector to optimize
        scenarios: Training scenarios
        verbose: Print progress
        federate_only: If True, only use RX events from federate receivers

    Returns:
        OptimizationResult with best threshold and ROC curve
    """
    if verbose:
        print(f"Optimizing threshold for {detector.name}...")

    times, labels, scores = collect_scores_and_labels(detector, scenarios, verbose, federate_only)

    if verbose:
        print(f"  Total events: {len(labels)}, spoofed: {np.sum(labels)}")

    # Compute ROC curve
    auc, fpr, tpr, thresholds = compute_roc_auc(labels, scores)

    if verbose:
        print(f"  AUC: {auc:.4f}")

    # Find threshold that maximizes Youden's J statistic (TPR - FPR)
    j_statistic = tpr - fpr
    best_idx = np.argmax(j_statistic)
    best_threshold = thresholds[best_idx]

    if verbose:
        print(f"  Best threshold: {best_threshold:.4f}")
        print(f"  At threshold: TPR={tpr[best_idx]:.4f}, FPR={fpr[best_idx]:.4f}")

    return OptimizationResult(
        detector_name=detector.name,
        best_threshold=float(best_threshold),
        best_auc=auc,
        best_params=detector.params,
        fpr_curve=fpr,
        tpr_curve=tpr,
        thresholds=thresholds,
    )


def grid_search(
    detector_factory: Callable[..., Detector],
    param_grid: dict[str, list],
    scenarios: list[ScenarioData],
    verbose: bool = False,
) -> tuple[OptimizationResult, dict]:
    """
    Grid search over detector parameters to maximize AUC.

    Args:
        detector_factory: Callable that creates Detector given **params
        param_grid: Dict mapping param names to lists of values to try
        scenarios: Training scenarios (list, will be iterated multiple times)
        verbose: Print progress

    Returns:
        Tuple of (best OptimizationResult, best params dict)
    """
    import itertools

    param_names = list(param_grid.keys())
    param_values = list(param_grid.values())

    best_result = None
    best_params = None
    best_auc = -1.0

    total_combos = 1
    for v in param_values:
        total_combos *= len(v)

    if verbose:
        print(f"Grid search over {total_combos} parameter combinations...")

    for i, combo in enumerate(itertools.product(*param_values)):
        params = dict(zip(param_names, combo))
        detector = detector_factory(**params)

        if verbose:
            print(f"  [{i+1}/{total_combos}] {params}")

        result = optimize_threshold(detector, scenarios, verbose=False)

        if result.best_auc > best_auc:
            best_auc = result.best_auc
            best_result = result
            best_params = params

            if verbose:
                print(f"    New best AUC: {best_auc:.4f}")

    if verbose:
        print(f"Best params: {best_params}")
        print(f"Best AUC: {best_auc:.4f}")

    return best_result, best_params


def line_search_threshold(
    detector: Detector,
    scenarios: list[ScenarioData],
    target_fpr: float | None = None,
    target_tpr: float | None = None,
    verbose: bool = False,
    federate_only: bool = False,
) -> tuple[float, float, float]:
    """
    Find threshold for a specific operating point.

    Args:
        detector: Detector to use
        scenarios: Training scenarios
        target_fpr: Target false positive rate (find threshold <= this FPR)
        target_tpr: Target true positive rate (find threshold >= this TPR)
        verbose: Print progress
        federate_only: If True, only use RX events from federate receivers

    Returns:
        Tuple of (threshold, actual_tpr, actual_fpr)
    """
    result = optimize_threshold(detector, scenarios, verbose=verbose, federate_only=federate_only)

    if target_fpr is not None:
        threshold = result.find_threshold_for_fpr(target_fpr)
    elif target_tpr is not None:
        threshold = result.find_threshold_for_tpr(target_tpr)
    else:
        threshold = result.best_threshold

    # Get actual rates at this threshold
    times, labels, scores = collect_scores_and_labels(detector, scenarios, federate_only=federate_only)
    _, _, _, _, tpr, fpr = compute_confusion_at_threshold(labels, scores, threshold)

    return threshold, tpr, fpr
