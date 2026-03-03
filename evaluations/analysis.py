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

from .metrics import compute_roc_auc, compute_distance_stats


def analyze_scores(
    scores_dir: Path,
    output_dir: Path | None = None,
    kf_threshold: float | None = None,
    mlat_threshold: float | None = None,
    mlp_predictions_path: Path | None = None,
) -> dict:
    """
    Analyze pre-computed score CSVs: compute ROC/AUC, confusion matrix, distance stats, plots.

    Reads kf_scores.csv, mlat_scores.csv, and optionally thresholds.json from scores_dir.

    Args:
        scores_dir: Directory containing kf_scores.csv, mlat_scores.csv, thresholds.json
        output_dir: Where to write results (defaults to scores_dir)
        kf_threshold: Override KF threshold (otherwise read from thresholds.json)
        mlat_threshold: Override MLAT threshold (otherwise read from thresholds.json)
        mlp_predictions_path: Optional MLP predictions CSV

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

    print("=" * 70)
    if mlp_predictions_path:
        print("ANALYSIS - Comparing KF, MLAT, MLP")
    else:
        print("ANALYSIS - Comparing KF, MLAT (MLP skipped)")
    print("=" * 70)
    print(f"\n  KF threshold:   {kf_threshold}")
    print(f"  MLAT threshold: {mlat_threshold}")

    # Load score CSVs
    kf_path = scores_dir / "kf_scores.csv"
    mlat_path = scores_dir / "mlat_scores.csv"

    kf_df = pd.read_csv(kf_path)
    mlat_df = pd.read_csv(mlat_path)

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

    # Load MLP predictions if provided
    all_mlp_scores = np.array([])
    all_mlp_labels = np.array([])
    if mlp_predictions_path:
        print(f"\n  Loading MLP predictions from {mlp_predictions_path}...")
        mlp_df = pd.read_csv(mlp_predictions_path)
        all_mlp_scores = mlp_df['y_proba'].values
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
    if mlp_predictions_path:
        methods_to_eval.append(('MLP', all_mlp_scores, all_mlp_labels, 0.5))

    for name, scores, labels, threshold in methods_to_eval:
        auc, fpr_arr, tpr_arr, thresholds = compute_roc_auc(labels, scores)
        predictions = scores >= threshold
        tp = ((predictions == 1) & (labels == 1)).sum()
        tn = ((predictions == 0) & (labels == 0)).sum()
        fp = ((predictions == 1) & (labels == 0)).sum()
        fn = ((predictions == 0) & (labels == 1)).sum()

        tpr = tp / (tp + fn) if (tp + fn) > 0 else 0
        fpr = fp / (fp + tn) if (fp + tn) > 0 else 0

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

    # KF distance analysis
    kf_predictions = all_kf_scores >= kf_threshold
    kf_spoofed_mask = all_kf_labels
    kf_tp_mask = kf_spoofed_mask & kf_predictions
    kf_fn_mask = kf_spoofed_mask & ~kf_predictions

    kf_distance_stats = {
        'all_spoofed': {
            'spoofing_dist': compute_distance_stats(all_kf_spoofing_dists[kf_spoofed_mask]),
            'distance_discrepancy': compute_distance_stats(all_kf_dist_discrepancies[kf_spoofed_mask]),
        },
        'true_positives': {
            'spoofing_dist': compute_distance_stats(all_kf_spoofing_dists[kf_tp_mask]),
            'distance_discrepancy': compute_distance_stats(all_kf_dist_discrepancies[kf_tp_mask]),
        },
        'false_negatives': {
            'spoofing_dist': compute_distance_stats(all_kf_spoofing_dists[kf_fn_mask]),
            'distance_discrepancy': compute_distance_stats(all_kf_dist_discrepancies[kf_fn_mask]),
        },
    }
    results['kf']['distance_stats'] = kf_distance_stats

    def fmt_stat(stats, key):
        val = stats.get(key)
        return f"{val:>8.2f}" if val is not None else "     N/A"

    print("\nKF Distance Stats (spoofing_dist = ||tx_actual - rid_claimed||):")
    s = kf_distance_stats['all_spoofed']['spoofing_dist']
    print(f"  All spoofed:     n={s['count']:>6}, mean={fmt_stat(s, 'mean')}m, median={fmt_stat(s, 'median')}m")
    s = kf_distance_stats['true_positives']['spoofing_dist']
    print(f"  True Positives:  n={s['count']:>6}, mean={fmt_stat(s, 'mean')}m, median={fmt_stat(s, 'median')}m")
    s = kf_distance_stats['false_negatives']['spoofing_dist']
    print(f"  False Negatives: n={s['count']:>6}, mean={fmt_stat(s, 'mean')}m, median={fmt_stat(s, 'median')}m")

    # MLAT distance analysis
    mlat_predictions = all_mlat_scores >= mlat_threshold
    mlat_spoofed_mask = all_mlat_labels
    mlat_tp_mask = mlat_spoofed_mask & mlat_predictions
    mlat_fn_mask = mlat_spoofed_mask & ~mlat_predictions

    mlat_distance_stats = {
        'all_spoofed': {
            'spoofing_dist': compute_distance_stats(all_mlat_spoofing_dists[mlat_spoofed_mask]),
            'distance_discrepancy': compute_distance_stats(all_mlat_dist_discrepancies[mlat_spoofed_mask]),
        },
        'true_positives': {
            'spoofing_dist': compute_distance_stats(all_mlat_spoofing_dists[mlat_tp_mask]),
            'distance_discrepancy': compute_distance_stats(all_mlat_dist_discrepancies[mlat_tp_mask]),
        },
        'false_negatives': {
            'spoofing_dist': compute_distance_stats(all_mlat_spoofing_dists[mlat_fn_mask]),
            'distance_discrepancy': compute_distance_stats(all_mlat_dist_discrepancies[mlat_fn_mask]),
        },
    }
    results['mlat']['distance_stats'] = mlat_distance_stats

    print("\nMLAT Distance Stats (spoofing_dist = ||tx_actual - rid_claimed||):")
    s = mlat_distance_stats['all_spoofed']['spoofing_dist']
    print(f"  All spoofed:     n={s['count']:>6}, mean={fmt_stat(s, 'mean')}m, median={fmt_stat(s, 'median')}m")
    s = mlat_distance_stats['true_positives']['spoofing_dist']
    print(f"  True Positives:  n={s['count']:>6}, mean={fmt_stat(s, 'mean')}m, median={fmt_stat(s, 'median')}m")
    s = mlat_distance_stats['false_negatives']['spoofing_dist']
    print(f"  False Negatives: n={s['count']:>6}, mean={fmt_stat(s, 'mean')}m, median={fmt_stat(s, 'median')}m")

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

        # KF: Spoofing distance distribution
        ax = axes[0, 0]
        kf_spoof_valid = _dropnan(all_kf_spoofing_dists[kf_spoofed_mask])
        bins = np.linspace(0, max(np.nanmax(kf_spoof_valid), 1), 50) if len(kf_spoof_valid) else 50
        ax.hist(_dropnan(all_kf_spoofing_dists[kf_tp_mask]), bins=bins, alpha=0.7,
                label=f'True Positives (n={kf_tp_mask.sum()})', color='green')
        ax.hist(_dropnan(all_kf_spoofing_dists[kf_fn_mask]), bins=bins, alpha=0.7,
                label=f'False Negatives (n={kf_fn_mask.sum()})', color='red')
        ax.set_xlabel('Spoofing Distance (m)', fontsize=11)
        ax.set_ylabel('Count', fontsize=11)
        ax.set_title('KF: Spoofing Distance Distribution', fontsize=12)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

        # KF: Distance discrepancy distribution
        ax = axes[0, 1]
        kf_disc_valid = _dropnan(all_kf_dist_discrepancies[kf_spoofed_mask])
        bins = np.linspace(kf_disc_valid.min(), kf_disc_valid.max(), 50) if len(kf_disc_valid) else 50
        ax.hist(_dropnan(all_kf_dist_discrepancies[kf_tp_mask]), bins=bins, alpha=0.7,
                label=f'True Positives (n={kf_tp_mask.sum()})', color='green')
        ax.hist(_dropnan(all_kf_dist_discrepancies[kf_fn_mask]), bins=bins, alpha=0.7,
                label=f'False Negatives (n={kf_fn_mask.sum()})', color='red')
        ax.set_xlabel('Distance Discrepancy (m)', fontsize=11)
        ax.set_ylabel('Count', fontsize=11)
        ax.set_title('KF: Distance Discrepancy (actual - claimed)', fontsize=12)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

        # MLAT: Spoofing distance distribution
        ax = axes[1, 0]
        mlat_spoof_valid = _dropnan(all_mlat_spoofing_dists[mlat_spoofed_mask])
        bins = np.linspace(0, max(np.nanmax(mlat_spoof_valid), 1), 50) if len(mlat_spoof_valid) else 50
        ax.hist(_dropnan(all_mlat_spoofing_dists[mlat_tp_mask]), bins=bins, alpha=0.7,
                label=f'True Positives (n={mlat_tp_mask.sum()})', color='green')
        ax.hist(_dropnan(all_mlat_spoofing_dists[mlat_fn_mask]), bins=bins, alpha=0.7,
                label=f'False Negatives (n={mlat_fn_mask.sum()})', color='red')
        ax.set_xlabel('Spoofing Distance (m)', fontsize=11)
        ax.set_ylabel('Count', fontsize=11)
        ax.set_title('MLAT: Spoofing Distance Distribution', fontsize=12)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

        # MLAT: Distance discrepancy distribution
        ax = axes[1, 1]
        mlat_disc_valid = _dropnan(all_mlat_dist_discrepancies[mlat_spoofed_mask])
        bins = np.linspace(mlat_disc_valid.min(), mlat_disc_valid.max(), 50) if len(mlat_disc_valid) else 50
        ax.hist(_dropnan(all_mlat_dist_discrepancies[mlat_tp_mask]), bins=bins, alpha=0.7,
                label=f'True Positives (n={mlat_tp_mask.sum()})', color='green')
        ax.hist(_dropnan(all_mlat_dist_discrepancies[mlat_fn_mask]), bins=bins, alpha=0.7,
                label=f'False Negatives (n={mlat_fn_mask.sum()})', color='red')
        ax.set_xlabel('Distance Discrepancy (m)', fontsize=11)
        ax.set_ylabel('Count', fontsize=11)
        ax.set_title('MLAT: Distance Discrepancy (actual - claimed)', fontsize=12)
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)

    for fmt, dpi in [('pdf', 300), ('png', 150)]:
        fig, axes = plt.subplots(2, 2, figsize=(14, 10))
        _plot_distance_distributions(axes)
        plt.tight_layout()
        dist_path = output_dir / f"distance_distributions.{fmt}"
        fig.savefig(dist_path, bbox_inches='tight', dpi=dpi)
        plt.close(fig)
        print(f"Distance distributions saved to {dist_path}")

    return results
