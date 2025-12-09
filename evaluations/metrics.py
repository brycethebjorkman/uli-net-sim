"""
Detection metrics for RX event-level spoofing detection.

Metrics:
1. In-place accuracy: AUC, FPR, TPR at operating threshold
2. Time to detection: Latency from first spoofed RX to first correct detection
"""

from dataclasses import dataclass
import numpy as np


@dataclass
class DetectionMetrics:
    """Metrics for RX event-level spoofing detection."""

    # ROC metrics
    auc: float
    fpr: float  # At operating threshold
    tpr: float  # At operating threshold
    threshold: float  # Operating threshold used

    # Time to detection (seconds from first spoofed RX)
    # None if no spoofed events or no detections
    time_to_detection: float | None

    # Counts at operating threshold
    true_positives: int
    true_negatives: int
    false_positives: int
    false_negatives: int

    @property
    def total(self) -> int:
        return (
            self.true_positives
            + self.true_negatives
            + self.false_positives
            + self.false_negatives
        )

    @property
    def accuracy(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.true_positives + self.true_negatives) / self.total

    def __str__(self) -> str:
        ttd_str = f"{self.time_to_detection:.3f}s" if self.time_to_detection is not None else "N/A"
        return (
            f"DetectionMetrics(\n"
            f"  AUC={self.auc:.4f}, TPR={self.tpr:.4f}, FPR={self.fpr:.4f}\n"
            f"  Threshold={self.threshold:.4f}, Time-to-Detection={ttd_str}\n"
            f"  TP={self.true_positives}, TN={self.true_negatives}, "
            f"FP={self.false_positives}, FN={self.false_negatives}\n"
            f")"
        )

    def to_dict(self) -> dict:
        return {
            "auc": self.auc,
            "fpr": self.fpr,
            "tpr": self.tpr,
            "threshold": self.threshold,
            "time_to_detection": self.time_to_detection,
            "true_positives": self.true_positives,
            "true_negatives": self.true_negatives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "accuracy": self.accuracy,
        }


def compute_roc_auc(y_true: np.ndarray, scores: np.ndarray) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute ROC curve and AUC from ground truth and continuous scores.

    Args:
        y_true: Ground truth labels (1 = spoofed, 0 = benign)
        scores: Continuous detection scores (higher = more likely spoofed)

    Returns:
        Tuple of (auc, fpr_curve, tpr_curve, thresholds)
    """
    y_true = np.asarray(y_true, dtype=bool)
    scores = np.asarray(scores)

    # Sort by descending score
    sorted_indices = np.argsort(-scores)
    y_sorted = y_true[sorted_indices]
    scores_sorted = scores[sorted_indices]

    # Count positives and negatives
    n_pos = np.sum(y_true)
    n_neg = len(y_true) - n_pos

    if n_pos == 0 or n_neg == 0:
        # Degenerate case
        return 0.5, np.array([0, 1]), np.array([0, 1]), np.array([scores.max(), scores.min()])

    # Compute TPR and FPR at each unique threshold
    tps = np.cumsum(y_sorted)
    fps = np.cumsum(~y_sorted)

    tpr = tps / n_pos
    fpr = fps / n_neg

    # Add (0, 0) point
    tpr = np.concatenate([[0], tpr])
    fpr = np.concatenate([[0], fpr])
    thresholds = np.concatenate([[scores_sorted[0] + 1], scores_sorted])

    # Compute AUC using trapezoidal rule
    auc = float(np.trapz(tpr, fpr))

    return auc, fpr, tpr, thresholds


def compute_confusion_at_threshold(
    y_true: np.ndarray,
    scores: np.ndarray,
    threshold: float,
) -> tuple[int, int, int, int, float, float]:
    """
    Compute confusion matrix and rates at a given threshold.

    Returns:
        Tuple of (tp, tn, fp, fn, tpr, fpr)
    """
    y_true = np.asarray(y_true, dtype=bool)
    y_pred = scores >= threshold

    tp = int(np.sum(y_true & y_pred))
    tn = int(np.sum(~y_true & ~y_pred))
    fp = int(np.sum(~y_true & y_pred))
    fn = int(np.sum(y_true & ~y_pred))

    tpr = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    fpr = fp / (fp + tn) if (fp + tn) > 0 else 0.0

    return tp, tn, fp, fn, tpr, fpr


def compute_time_to_detection(
    times: np.ndarray,
    y_true: np.ndarray,
    scores: np.ndarray,
    threshold: float,
) -> float | None:
    """
    Compute time from first spoofed RX to first correct detection.

    Args:
        times: Timestamps for each event
        y_true: Ground truth labels (1 = spoofed, 0 = benign)
        scores: Detection scores
        threshold: Detection threshold

    Returns:
        Time to detection in seconds, or None if no spoofed events or no detections
    """
    y_true = np.asarray(y_true, dtype=bool)
    y_pred = scores >= threshold

    # Find first spoofed event
    spoofed_indices = np.where(y_true)[0]
    if len(spoofed_indices) == 0:
        return None

    first_spoofed_time = times[spoofed_indices[0]]

    # Find first correct detection (true positive)
    tp_indices = np.where(y_true & y_pred)[0]
    if len(tp_indices) == 0:
        return None

    first_detection_time = times[tp_indices[0]]

    return float(first_detection_time - first_spoofed_time)


def compute_metrics(
    times: np.ndarray,
    y_true: np.ndarray,
    scores: np.ndarray,
    threshold: float,
) -> DetectionMetrics:
    """
    Compute all detection metrics for a set of RX events.

    Args:
        times: Timestamps for each RX event
        y_true: Ground truth labels (1 = spoofed, 0 = benign)
        scores: Detection scores (higher = more likely spoofed)
        threshold: Detection threshold for binary classification

    Returns:
        DetectionMetrics with AUC, FPR, TPR, time-to-detection, and confusion matrix
    """
    auc, _, _, _ = compute_roc_auc(y_true, scores)
    tp, tn, fp, fn, tpr, fpr = compute_confusion_at_threshold(y_true, scores, threshold)
    ttd = compute_time_to_detection(times, y_true, scores, threshold)

    return DetectionMetrics(
        auc=auc,
        fpr=fpr,
        tpr=tpr,
        threshold=threshold,
        time_to_detection=ttd,
        true_positives=tp,
        true_negatives=tn,
        false_positives=fp,
        false_negatives=fn,
    )
