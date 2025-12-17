#!/usr/bin/env python3
"""
Unified evaluation script for comparing KF, MLAT, and MLP detectors.

Ensures fair comparison by:
1. Evaluating all methods on the same test set
2. Using transmission-level predictions (grouped by serial_number, rid_timestamp)
3. Using only 4 federate receivers for KF (matching MLAT and MLP)

Usage:
    python -m evaluations.unified_eval \
        --test-dir datasets/scitech26-1920-scenarios/test \
        --train-dir datasets/scitech26-1920-scenarios/train \
        --mlp-predictions datasets/mlp_test_predictions.csv \
        -o evaluations/results/

    # Test-only mode (skip training, use provided thresholds)
    python -m evaluations.unified_eval \
        --test-dir datasets/scitech26-1920-scenarios/test \
        --mlp-predictions datasets/mlp_test_predictions.csv \
        --test-only \
        --kf-threshold 0.6254 \
        --mlat-threshold 114.3571 \
        --mlat-ple 1.6 \
        -o evaluations/results/
"""

import argparse
import json
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from .data import load_scenario, iter_dataset, load_dataset, ScenarioData
from .detectors import KalmanFilterDetector, MultilatDetector
from .metrics import compute_roc_auc
from .optimize import optimize_threshold


def collect_kf_scores_per_rx_event(
    scenario: ScenarioData,
    federate_ids: set[int],
) -> tuple[list[float], list[bool]]:
    """
    Collect KF scores at the per-RX-event level using only federate receivers.

    Each federate's reception is treated as an independent detection trial.
    No aggregation across receivers.

    Args:
        scenario: ScenarioData with RX events
        federate_ids: Set of host IDs designated as federates

    Returns:
        Tuple of (scores, labels) lists for all federate RX events with valid KF NIS
    """
    scores = []
    labels = []

    for i in range(scenario.n_events):
        # Only use federate receivers
        if scenario.host_id[i] not in federate_ids:
            continue

        nis = scenario.kf_nis[i]
        if not np.isnan(nis):
            scores.append(nis)
            labels.append(scenario.is_spoofed[i])

    return scores, labels


def evaluate_on_test_transmissions(
    test_dir: Path,
    mlp_predictions_path: Path | None,
    kf_threshold: float,
    mlat_threshold: float,
    mlat_ple: float,
    output_dir: Path | None = None,
    test_limit: int | None = None,
):
    """
    Evaluate all three methods on test data.

    Each method is evaluated on its natural granularity:
    - KF: Per-RX-event from federate receivers (each federate is independent trial)
    - MLAT: Per-transmission (requires 4 federates)
    - MLP: Per-transmission (as trained)
    """
    print("=" * 70)
    if mlp_predictions_path:
        print("UNIFIED EVALUATION - Comparing KF, MLAT, MLP")
    else:
        print("UNIFIED EVALUATION - Comparing KF, MLAT (MLP skipped)")
    print("=" * 70)

    # Load MLP predictions (if provided)
    mlp_predictions = {}
    test_csv_names = None  # None means no filtering by MLP coverage
    if mlp_predictions_path:
        print(f"\nLoading MLP predictions from {mlp_predictions_path}...")
        mlp_df = pd.read_csv(mlp_predictions_path)

        # Fix filename paths: ./datasets/test/X.csv -> just the filename
        mlp_df['csv_name'] = mlp_df['filename'].apply(lambda x: Path(x).name)

        # Group MLP predictions by (csv_name, serial_number, rid_timestamp)
        for _, row in mlp_df.iterrows():
            key = (row['csv_name'], row['serial_number'], row['rid_timestamp'])
            mlp_predictions[key] = {
                'y_pred': row['y_pred'],
                'y_proba': row['y_proba'],
                'is_spoofed': row['is_spoofed'],
            }
        print(f"  Loaded {len(mlp_predictions)} MLP transmission predictions")

        # Get list of test CSV files that have MLP predictions
        test_csv_names = set(mlp_df['csv_name'].unique())
        print(f"  MLP covers {len(test_csv_names)} test scenarios")
    else:
        print("\nSkipping MLP evaluation (no predictions file provided)")

    # Initialize MLAT detector
    mlat_detector = MultilatDetector(path_loss_exp=mlat_ple)

    # Collect scores for each method separately (different granularities)
    all_kf_scores = []
    all_kf_labels = []
    all_mlat_scores = []
    all_mlat_labels = []
    all_mlp_scores = []
    all_mlp_labels = []

    print(f"\nProcessing test scenarios from {test_dir}...")

    csv_files = sorted(test_dir.glob("*.csv"))
    if test_limit:
        csv_files = csv_files[:test_limit]

    n_processed = 0
    for csv_path in csv_files:
        csv_name = csv_path.name

        # Skip if no MLP predictions for this scenario (only when MLP is enabled)
        if test_csv_names is not None and csv_name not in test_csv_names:
            continue

        scenario = load_scenario(csv_path)
        federate_ids = set(scenario.federate_host_ids)

        # KF: Collect per-RX-event scores from federates (no aggregation)
        kf_scores, kf_labels = collect_kf_scores_per_rx_event(scenario, federate_ids)
        all_kf_scores.extend(kf_scores)
        all_kf_labels.extend(kf_labels)

        # MLAT: Collect per-transmission scores
        mlat_scores_array = mlat_detector.score(scenario)

        # Group MLAT scores by transmission (take first occurrence)
        mlat_transmission_scores = {}
        for i in range(scenario.n_events):
            if mlat_scores_array[i] > 0:  # MLAT only produces non-zero for 4+ federates
                key = (scenario.serial_number[i], scenario.rid_timestamp[i])
                if key not in mlat_transmission_scores:
                    mlat_transmission_scores[key] = (mlat_scores_array[i], scenario.is_spoofed[i])

        for (sn, rid_ts), (mlat_score, label) in mlat_transmission_scores.items():
            all_mlat_scores.append(mlat_score)
            all_mlat_labels.append(label)

        # MLP: Collect per-transmission scores for this scenario (if MLP enabled)
        if mlp_predictions:
            scenario_mlp_keys = [(csv, sn, ts) for (csv, sn, ts) in mlp_predictions.keys() if csv == csv_name]
            for key in scenario_mlp_keys:
                mlp_data = mlp_predictions[key]
                all_mlp_scores.append(mlp_data['y_proba'])
                all_mlp_labels.append(mlp_data['is_spoofed'])

        n_processed += 1
        if n_processed % 100 == 0:
            print(f"  Processed {n_processed} scenarios...")

    print(f"\n  Total scenarios processed: {n_processed}")

    # Convert to numpy
    all_kf_scores = np.array(all_kf_scores)
    all_kf_labels = np.array(all_kf_labels)
    all_mlat_scores = np.array(all_mlat_scores)
    all_mlat_labels = np.array(all_mlat_labels)
    all_mlp_scores = np.array(all_mlp_scores)
    all_mlp_labels = np.array(all_mlp_labels)

    print(f"\n  KF: {len(all_kf_labels)} RX events ({all_kf_labels.sum()} spoofed)")
    print(f"  MLAT: {len(all_mlat_labels)} transmissions ({all_mlat_labels.sum()} spoofed)")
    if mlp_predictions:
        print(f"  MLP: {len(all_mlp_labels)} transmissions ({all_mlp_labels.sum()} spoofed)")

    # Compute metrics for each method on its own data
    print("\n" + "=" * 70)
    print("RESULTS (each method evaluated on its natural granularity)")
    print("=" * 70)

    results = {}

    # Build list of methods to evaluate (MLP only if predictions provided)
    methods_to_eval = [
        ('KF', all_kf_scores, all_kf_labels, kf_threshold),
        ('MLAT', all_mlat_scores, all_mlat_labels, mlat_threshold),
    ]
    if mlp_predictions:
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

    # Print comparison table
    print("\n" + "=" * 70)
    print("COMPARISON TABLE")
    print("=" * 70)
    print(f"{'Method':<10} {'AUC':>8} {'TPR':>8} {'FPR':>8} {'Threshold':>12} {'N_events':>10}")
    print("-" * 60)
    for name in results.keys():
        r = results[name]
        print(f"{name.upper():<10} {r['auc']:>8.4f} {r['tpr']:>8.4f} {r['fpr']:>8.4f} {r['threshold']:>12.4f} {r['n_total']:>10}")

    # Generate ROC curve figure
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Save results JSON
        results_path = output_dir / "unified_results.json"
        with open(results_path, 'w') as f:
            # Remove curve data for JSON (too large)
            results_json = {k: {kk: vv for kk, vv in v.items() if not kk.endswith('_curve')}
                          for k, v in results.items()}
            json.dump(results_json, f, indent=2)
        print(f"\nResults saved to {results_path}")

        # Generate ROC curve figure
        fig, ax = plt.subplots(figsize=(8, 6))

        colors = {'kf': 'blue', 'mlat': 'green', 'mlp': 'red'}
        labels_map = {'kf': 'Kalman Filter', 'mlat': 'Multilateration', 'mlp': 'MLP'}

        for name in results.keys():
            fpr = results[name]['fpr_curve']
            tpr = results[name]['tpr_curve']
            auc = results[name]['auc']
            ax.plot(fpr, tpr, color=colors[name], linewidth=2,
                   label=f'{labels_map[name]} (AUC={auc:.3f})')

        ax.plot([0, 1], [0, 1], 'k--', linewidth=1, label='Random')
        ax.set_xlabel('False Positive Rate', fontsize=12)
        ax.set_ylabel('True Positive Rate', fontsize=12)
        ax.set_title('ROC Curves - Spoofing Detection Methods', fontsize=14)
        ax.legend(loc='lower right', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.set_xlim([0, 1])
        ax.set_ylim([0, 1])

        roc_path = output_dir / "roc_curves.pdf"
        fig.savefig(roc_path, bbox_inches='tight', dpi=300)
        plt.close(fig)
        print(f"ROC curves saved to {roc_path}")

        # Also save as PNG for quick viewing
        fig, ax = plt.subplots(figsize=(8, 6))
        for name in results.keys():
            fpr = results[name]['fpr_curve']
            tpr = results[name]['tpr_curve']
            auc = results[name]['auc']
            ax.plot(fpr, tpr, color=colors[name], linewidth=2,
                   label=f'{labels_map[name]} (AUC={auc:.3f})')
        ax.plot([0, 1], [0, 1], 'k--', linewidth=1, label='Random')
        ax.set_xlabel('False Positive Rate', fontsize=12)
        ax.set_ylabel('True Positive Rate', fontsize=12)
        ax.set_title('ROC Curves - Spoofing Detection Methods', fontsize=14)
        ax.legend(loc='lower right', fontsize=10)
        ax.grid(True, alpha=0.3)
        ax.set_xlim([0, 1])
        ax.set_ylim([0, 1])
        roc_png_path = output_dir / "roc_curves.png"
        fig.savefig(roc_png_path, bbox_inches='tight', dpi=150)
        plt.close(fig)
        print(f"ROC curves (PNG) saved to {roc_png_path}")

    return results


def train_thresholds(
    train_dir: Path,
    train_limit: int | None = None,
) -> tuple[float, float, float]:
    """
    Train optimal thresholds for KF and MLAT on training data.
    Also finds best path loss exponent for MLAT.

    Returns:
        Tuple of (kf_threshold, mlat_threshold, mlat_ple)
    """
    print("=" * 70)
    print("TRAINING PHASE")
    print("=" * 70)

    train_scenarios = load_dataset(train_dir, limit=train_limit)
    print(f"Loaded {len(train_scenarios)} training scenarios")

    # Train KF threshold (using only federate receivers, per-RX-event)
    print("\nOptimizing KF threshold (federate-only, per-RX-event)...")
    kf_detector = KalmanFilterDetector()
    kf_opt = optimize_threshold(kf_detector, train_scenarios, verbose=True, federate_only=True)
    kf_threshold = kf_opt.best_threshold

    # Line search for MLAT path loss exponent
    print("\nLine search for MLAT path loss exponent...")
    path_loss_values = [1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0]

    best_auc = -1
    best_ple = 2.0
    best_mlat_threshold = 100.0

    for ple in path_loss_values:
        mlat_detector = MultilatDetector(path_loss_exp=ple)
        opt = optimize_threshold(mlat_detector, train_scenarios, verbose=False, federate_only=True)
        print(f"  path_loss_exp={ple:.1f}: AUC={opt.best_auc:.4f}")

        if opt.best_auc > best_auc:
            best_auc = opt.best_auc
            best_ple = ple
            best_mlat_threshold = opt.best_threshold

    print(f"\nBest path_loss_exp: {best_ple}")
    print(f"Best MLAT threshold: {best_mlat_threshold:.4f}")

    return kf_threshold, best_mlat_threshold, best_ple


def main():
    parser = argparse.ArgumentParser(
        description="Unified evaluation comparing KF, MLAT, and MLP detectors"
    )
    parser.add_argument("--test-dir", type=Path, required=True,
                       help="Test data directory")
    parser.add_argument("--train-dir", type=Path,
                       help="Training data directory (required unless --test-only)")
    parser.add_argument("--mlp-predictions", type=Path,
                       help="MLP predictions CSV file (optional, skip MLP if not provided)")
    parser.add_argument("-o", "--output", type=Path,
                       help="Output directory for results and figures")
    parser.add_argument("--test-only", action="store_true",
                       help="Skip training, use provided thresholds")
    parser.add_argument("--kf-threshold", type=float, default=0.6254,
                       help="KF detection threshold (for --test-only)")
    parser.add_argument("--mlat-threshold", type=float, default=114.3571,
                       help="MLAT detection threshold (for --test-only)")
    parser.add_argument("--mlat-ple", type=float, default=1.6,
                       help="MLAT path loss exponent (for --test-only)")
    parser.add_argument("--train-limit", type=int,
                       help="Limit training scenarios (for testing)")
    parser.add_argument("--test-limit", type=int,
                       help="Limit test scenarios (for testing)")

    args = parser.parse_args()

    if args.test_only:
        kf_threshold = args.kf_threshold
        mlat_threshold = args.mlat_threshold
        mlat_ple = args.mlat_ple
        print(f"Using provided thresholds: KF={kf_threshold}, MLAT={mlat_threshold}, PLE={mlat_ple}")
    else:
        if args.train_dir is None:
            parser.error("--train-dir is required unless --test-only is specified")
        kf_threshold, mlat_threshold, mlat_ple = train_thresholds(
            args.train_dir,
            train_limit=args.train_limit
        )

    evaluate_on_test_transmissions(
        test_dir=args.test_dir,
        mlp_predictions_path=args.mlp_predictions,
        kf_threshold=kf_threshold,
        mlat_threshold=mlat_threshold,
        mlat_ple=mlat_ple,
        output_dir=args.output,
        test_limit=args.test_limit,
    )


if __name__ == "__main__":
    main()
