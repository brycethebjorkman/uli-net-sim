"""
Parameter optimization for spoofing detectors.

Optimization strategies:
1. Line search for detection threshold (maximize AUC or find operating point)
2. Grid search for detector parameters (path loss model, etc.)

Uses training set to find optimal parameters, then evaluates on test set.
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np

from .data import ScenarioData, load_scenario
from .detectors import Detector, KalmanFilterDetector, MultilatDetector
from .metrics import compute_roc_auc


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



def collect_scores_and_labels(
    detector: Detector,
    scenarios,
    verbose: bool = False,
    federate_only: bool = False,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Collect detection scores and ground truth labels from scenarios.

    Args:
        detector: Detector to evaluate
        scenarios: Iterable of ScenarioData
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
    scenarios,
    verbose: bool = False,
    federate_only: bool = False,
) -> OptimizationResult:
    """
    Find optimal detection threshold using AUC on training data.

    Args:
        detector: Detector to optimize
        scenarios: Iterable of ScenarioData
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


def train_thresholds(
    train_dir: Path,
    train_limit: int | None = None,
) -> tuple[float, float]:
    """
    Train optimal KF and MLAT thresholds in a single streaming pass.

    Loads one scenario at a time, scores it with both detectors, and
    discards the full ScenarioData before loading the next.  Only the
    compact score/label arrays are kept in memory.
    """
    print("=" * 70)
    print("TRAINING PHASE")
    print("=" * 70)

    train_files = sorted(Path(train_dir).glob("*.parquet"))
    if train_limit:
        train_files = train_files[:train_limit]
    n_train = len(train_files)
    print(f"Training on {n_train} scenarios from {train_dir}\n")

    kf_detector = KalmanFilterDetector()
    mlat_detector = MultilatDetector()

    kf_labels, kf_scores = [], []
    mlat_labels, mlat_scores = [], []

    for i, path in enumerate(train_files):
        scenario = load_scenario(path)
        federate_ids = set(scenario.federate_host_ids)
        mask = np.array([hid in federate_ids for hid in scenario.host_id])

        # KF scores (federate-only, per-RX-event)
        s = kf_detector.score(scenario)[mask]
        kf_scores.append(s)
        kf_labels.append(scenario.is_spoofed[mask])

        # MLAT scores (federate-only, per-RX-event)
        s = mlat_detector.score(scenario)[mask]
        mlat_scores.append(s)
        mlat_labels.append(scenario.is_spoofed[mask])

        if (i + 1) % max(1, n_train // 10) == 0:
            print(f"  Scored {i + 1}/{n_train} scenarios...")

    # Optimize KF threshold
    print("\nOptimizing KF threshold (federate-only, per-RX-event)...")
    all_kf_labels = np.concatenate(kf_labels)
    all_kf_scores = np.concatenate(kf_scores)
    print(f"  Total events: {len(all_kf_labels)}, spoofed: {np.sum(all_kf_labels)}")

    kf_auc, kf_fpr, kf_tpr, kf_thresh = compute_roc_auc(all_kf_labels, all_kf_scores)
    kf_j = kf_tpr - kf_fpr
    kf_best_idx = np.argmax(kf_j)
    kf_threshold = float(kf_thresh[kf_best_idx])
    print(f"  AUC: {kf_auc:.4f}")
    print(f"  Best threshold: {kf_threshold:.4f}")
    print(f"  At threshold: TPR={kf_tpr[kf_best_idx]:.4f}, FPR={kf_fpr[kf_best_idx]:.4f}")

    # Optimize MLAT threshold
    print("\nOptimizing MLAT threshold (federate-only, per-transmission)...")
    all_mlat_labels = np.concatenate(mlat_labels)
    all_mlat_scores = np.concatenate(mlat_scores)
    print(f"  Total events: {len(all_mlat_labels)}, spoofed: {np.sum(all_mlat_labels)}")

    mlat_auc, mlat_fpr, mlat_tpr, mlat_thresh = compute_roc_auc(all_mlat_labels, all_mlat_scores)
    mlat_j = mlat_tpr - mlat_fpr
    mlat_best_idx = np.argmax(mlat_j)
    mlat_threshold = float(mlat_thresh[mlat_best_idx])
    print(f"  AUC: {mlat_auc:.4f}")
    print(f"  Best threshold: {mlat_threshold:.4f}")
    print(f"  At threshold: TPR={mlat_tpr[mlat_best_idx]:.4f}, FPR={mlat_fpr[mlat_best_idx]:.4f}")

    return kf_threshold, mlat_threshold
