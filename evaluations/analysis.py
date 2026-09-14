"""
Analysis functions for spoofing detection evaluation.

Reads pre-computed score CSVs (from scoring.py) and produces
ROC curves, confusion matrices, distance statistics, and plots.
"""

from pathlib import Path
import json

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from .metrics import compute_roc_auc, compute_confusion_at_threshold, compute_distance_stats


def analyze_scores(
    scores_dir: Path,
    output_dir: Path | None = None,
    kf_threshold: float | None = None,
    mlat_threshold: float | None = None,
) -> dict:
    """
    Analyze pre-computed score CSVs: compute ROC/AUC, confusion matrix, distance stats, plots.

    Reads kf_scores.parquet, mlat_scores.parquet, and optionally mlp_scores.parquet from scores_dir.

    Args:
        scores_dir: Directory containing kf_scores.parquet, mlat_scores.parquet,
                    mlp_scores.parquet (optional), thresholds.json
        output_dir: Where to write results (defaults to scores_dir)
        kf_threshold: Override KF threshold (otherwise read from thresholds.json)
        mlat_threshold: Override MLAT threshold (otherwise read from thresholds.json)

    Returns:
        Results dict (same structure as evaluate_on_test_transmissions)
    """
    scores_dir = Path(scores_dir)
    if output_dir is None:
        output_dir = scores_dir
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load thresholds
    if kf_threshold is None or mlat_threshold is None:
        thresholds_path = scores_dir / "thresholds.json"
        if not thresholds_path.exists():
            raise FileNotFoundError(
                f"No thresholds.json in {scores_dir}. "
                "Provide --kf-threshold and --mlat-threshold, or run 'score' first."
            )
        with open(thresholds_path) as f:
            thresholds_data = json.load(f)
        if kf_threshold is None:
            kf_threshold = thresholds_data['kf_threshold']
        if mlat_threshold is None:
            mlat_threshold = thresholds_data['mlat_threshold']

    # Load MLP scores if available (produced by score stage)
    mlp_path = scores_dir / "mlp_scores.parquet"
    mlp_available = mlp_path.exists()

    print("=" * 70)
    if mlp_available:
        print("ANALYSIS - Comparing KF, MLAT, MLP")
    else:
        print("ANALYSIS - Comparing KF, MLAT (no mlp_scores.parquet found)")
    print("=" * 70)
    print(f"\n  KF threshold:   {kf_threshold}")
    print(f"  MLAT threshold: {mlat_threshold}")

    # Load score CSVs
    kf_path = scores_dir / "kf_scores.parquet"
    mlat_path = scores_dir / "mlat_scores.parquet"

    kf_df = pd.read_parquet(kf_path)
    mlat_df = pd.read_parquet(mlat_path)

    print(f"\n  KF: {len(kf_df)} RX events ({kf_df['is_spoofed'].sum()} spoofed)")
    print(f"  MLAT: {len(mlat_df)} transmissions ({mlat_df['is_spoofed'].sum()} spoofed)")

    # Convert to numpy arrays
    all_kf_scores = kf_df['kf_score'].values
    all_kf_labels = kf_df['is_spoofed'].values.astype(bool)
    all_kf_spoofing_dists = kf_df['spoofing_dist'].values
    all_kf_dist_discrepancies = kf_df['distance_discrepancy'].values

    all_mlat_scores = mlat_df['mlat_score'].values
    all_mlat_labels = mlat_df['is_spoofed'].values.astype(bool)
    all_mlat_spoofing_dists = mlat_df['spoofing_dist'].values
    all_mlat_dist_discrepancies = mlat_df['distance_discrepancy'].values

    # Load MLP scores if present
    all_mlp_scores = np.array([])
    all_mlp_labels = np.array([])
    if mlp_available:
        mlp_df = pd.read_parquet(mlp_path)
        all_mlp_scores = mlp_df['mlp_score'].values
        all_mlp_labels = mlp_df['is_spoofed'].values.astype(bool)
        print(f"  MLP: {len(all_mlp_labels)} transmissions ({all_mlp_labels.sum()} spoofed)")

    # Compute metrics for each method
    print("\n" + "=" * 70)
    print("RESULTS (each method evaluated on its natural granularity)")
    print("=" * 70)

    results = {}

    methods_to_eval = [
        ('KF', all_kf_scores, all_kf_labels, kf_threshold),
        ('MLAT', all_mlat_scores, all_mlat_labels, mlat_threshold),
    ]
    if mlp_available:
        methods_to_eval.append(('MLP', all_mlp_scores, all_mlp_labels, 0.5))

    for name, scores, labels, threshold in methods_to_eval:
        auc, fpr_arr, tpr_arr, thresholds = compute_roc_auc(labels, scores)
        tp, tn, fp, fn, tpr, fpr = compute_confusion_at_threshold(labels, scores, threshold)

        results[name.lower()] = {
            'auc': float(auc),
            'tpr': float(tpr),
            'fpr': float(fpr),
            'threshold': float(threshold),
            'tp': int(tp),
            'tn': int(tn),
            'fp': int(fp),
            'fn': int(fn),
            'n_total': int(len(labels)),
            'n_spoofed': int(labels.sum()),
            'n_benign': int((~labels).sum()),
            'fpr_curve': fpr_arr.tolist(),
            'tpr_curve': tpr_arr.tolist(),
        }

        print(f"\n{name}:")
        print(f"  AUC: {auc:.4f}")
        print(f"  TPR: {tpr:.4f}, FPR: {fpr:.4f} (at threshold={threshold})")
        print(f"  TP={tp}, TN={tn}, FP={fp}, FN={fn}")

    # Distance analysis
    print("\n" + "=" * 70)
    print("DISTANCE ANALYSIS (spoofed samples only)")
    print("=" * 70)

    def _compute_detector_distances(scores, labels, threshold, spoofing_dists, dist_discrepancies, name):
        """Compute distance stats for TP/FN breakdown of a single detector."""
        predictions = scores >= threshold
        spoofed_mask = labels
        tp_mask = spoofed_mask & predictions
        fn_mask = spoofed_mask & ~predictions

        distance_stats = {
            'all_spoofed': {
                'spoofing_dist': compute_distance_stats(spoofing_dists[spoofed_mask]),
                'distance_discrepancy': compute_distance_stats(dist_discrepancies[spoofed_mask]),
            },
            'true_positives': {
                'spoofing_dist': compute_distance_stats(spoofing_dists[tp_mask]),
                'distance_discrepancy': compute_distance_stats(dist_discrepancies[tp_mask]),
            },
            'false_negatives': {
                'spoofing_dist': compute_distance_stats(spoofing_dists[fn_mask]),
                'distance_discrepancy': compute_distance_stats(dist_discrepancies[fn_mask]),
            },
        }

        def fmt_stat(stats, key):
            val = stats.get(key)
            return f"{val:>8.2f}" if val is not None else "     N/A"

        print(f"\n{name} Distance Stats (spoofing_dist = ||tx_actual - rid_claimed||):")
        for label, key in [("All spoofed", "all_spoofed"), ("True Positives", "true_positives"), ("False Negatives", "false_negatives")]:
            s = distance_stats[key]['spoofing_dist']
            print(f"  {label:<17}n={s['count']:>6}, mean={fmt_stat(s, 'mean')}m, median={fmt_stat(s, 'median')}m")

        return distance_stats, spoofed_mask, tp_mask, fn_mask

    kf_distance_stats, kf_spoofed_mask, kf_tp_mask, kf_fn_mask = _compute_detector_distances(
        all_kf_scores, all_kf_labels, kf_threshold, all_kf_spoofing_dists, all_kf_dist_discrepancies, "KF"
    )
    results['kf']['distance_stats'] = kf_distance_stats

    mlat_distance_stats, mlat_spoofed_mask, mlat_tp_mask, mlat_fn_mask = _compute_detector_distances(
        all_mlat_scores, all_mlat_labels, mlat_threshold, all_mlat_spoofing_dists, all_mlat_dist_discrepancies, "MLAT"
    )
    results['mlat']['distance_stats'] = mlat_distance_stats

    # Comparison table
    print("\n" + "=" * 70)
    print("COMPARISON TABLE")
    print("=" * 70)
    print(f"{'Method':<10} {'AUC':>8} {'TPR':>8} {'FPR':>8} {'Threshold':>12} {'N_events':>10}")
    print("-" * 60)
    for name in results.keys():
        r = results[name]
        print(f"{name.upper():<10} {r['auc']:>8.4f} {r['tpr']:>8.4f} {r['fpr']:>8.4f} {r['threshold']:>12.4f} {r['n_total']:>10}")

    # Save results and generate plots
    # Save results JSON
    results_path = output_dir / "unified_results.json"
    with open(results_path, 'w') as f:
        results_json = {k: {kk: vv for kk, vv in v.items() if not kk.endswith('_curve')}
                      for k, v in results.items()}
        json.dump(results_json, f, indent=2)
    print(f"\nResults saved to {results_path}")

    # Generate ROC curve figure
    colors = {'kf': 'blue', 'mlat': 'green', 'mlp': 'red'}
    labels_map = {'kf': 'Kalman Filter', 'mlat': 'Multilateration', 'mlp': 'MLP'}

    for fmt, dpi, suffix in [('pdf', 300, ''), ('png', 150, '')]:
        fig, ax = plt.subplots(figsize=(8, 6))
        for name in results.keys():
            fpr_curve = results[name]['fpr_curve']
            tpr_curve = results[name]['tpr_curve']
            auc = results[name]['auc']
            ax.plot(fpr_curve, tpr_curve, color=colors[name], linewidth=2,
                   label=f'{labels_map[name]} (AUC={auc:.3f})')
        ax.plot([0, 1], [0, 1], 'k--', linewidth=1, label='Random')
        ax.set_xlabel('False Positive Rate', fontsize=12)
        ax.set_ylabel('True Positive Rate', fontsize=12)
        ax.set_title('ROC Curves - Spoofing Detection Methods', fontsize=14)
        ax.legend(loc='lower right', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.set_xlim([0, 1])
        ax.set_ylim([0, 1])
        roc_path = output_dir / f"roc_curves.{fmt}"
        fig.savefig(roc_path, bbox_inches='tight', dpi=dpi)
        plt.close(fig)
        print(f"ROC curves saved to {roc_path}")

    # Generate distance distribution plots
    def _plot_distance_distributions(axes):
        def _dropnan(arr):
            return arr[~np.isnan(arr)]

        def _plot_histogram(ax, data, tp_mask, fn_mask, spoofed_mask, xlabel, title, zero_based=True):
            valid = _dropnan(data[spoofed_mask])
            if len(valid):
                lo = 0 if zero_based else valid.min()
                bins = np.linspace(lo, max(valid.max(), 1) if zero_based else valid.max(), 50)
            else:
                bins = 50
            ax.hist(_dropnan(data[tp_mask]), bins=bins, alpha=0.7,
                    label=f'True Positives (n={tp_mask.sum()})', color='green')
            ax.hist(_dropnan(data[fn_mask]), bins=bins, alpha=0.7,
                    label=f'False Negatives (n={fn_mask.sum()})', color='red')
            ax.set_xlabel(xlabel, fontsize=11)
            ax.set_ylabel('Count', fontsize=11)
            ax.set_title(title, fontsize=12)
            ax.legend(fontsize=9)
            ax.grid(True, alpha=0.3)

        _plot_histogram(axes[0, 0], all_kf_spoofing_dists, kf_tp_mask, kf_fn_mask, kf_spoofed_mask,
                        'Spoofing Distance (m)', 'KF: Spoofing Distance Distribution')
        _plot_histogram(axes[0, 1], all_kf_dist_discrepancies, kf_tp_mask, kf_fn_mask, kf_spoofed_mask,
                        'Distance Discrepancy (m)', 'KF: Distance Discrepancy (actual - claimed)', zero_based=False)
        _plot_histogram(axes[1, 0], all_mlat_spoofing_dists, mlat_tp_mask, mlat_fn_mask, mlat_spoofed_mask,
                        'Spoofing Distance (m)', 'MLAT: Spoofing Distance Distribution')
        _plot_histogram(axes[1, 1], all_mlat_dist_discrepancies, mlat_tp_mask, mlat_fn_mask, mlat_spoofed_mask,
                        'Distance Discrepancy (m)', 'MLAT: Distance Discrepancy (actual - claimed)', zero_based=False)

    for fmt, dpi in [('pdf', 300), ('png', 150)]:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        _plot_distance_distributions(axes)
        plt.tight_layout()
        dist_path = output_dir / f"distance_distributions.{fmt}"
        fig.savefig(dist_path, bbox_inches='tight', dpi=dpi)
        plt.close(fig)
        print(f"Distance distributions saved to {dist_path}")

    return results
