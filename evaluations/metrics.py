"""
Detection metrics for spoofing detection evaluation.

Provides ROC/AUC computation, confusion matrix, and distance statistics.
"""

import numpy as np


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
    auc = float(np.trapezoid(tpr, fpr))

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



def compute_distance_stats(distances: np.ndarray) -> dict:
    """Compute summary statistics for a distance distribution."""
    # Filter out NaN values (from failed TX/RX joins)
    distances = distances[~np.isnan(distances)]
    if len(distances) == 0:
        return {
            'count': 0,
            'mean': None,
            'std': None,
            'min': None,
            'max': None,
            'median': None,
            'p25': None,
            'p75': None,
            'p90': None,
            'p95': None,
        }
    return {
        'count': int(len(distances)),
        'mean': float(np.mean(distances)),
        'std': float(np.std(distances)),
        'min': float(np.min(distances)),
        'max': float(np.max(distances)),
        'median': float(np.median(distances)),
        'p25': float(np.percentile(distances, 25)),
        'p75': float(np.percentile(distances, 75)),
        'p90': float(np.percentile(distances, 90)),
        'p95': float(np.percentile(distances, 95)),
    }
