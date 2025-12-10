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


def aggregate_kf_scores_per_transmission(
    scenario: ScenarioData,
    federate_ids: set[int],
) -> dict[tuple[int, int], tuple[float, bool]]:
    """
    Aggregate KF scores at the transmission level using only federate receivers.

    For each transmission (serial_number, rid_timestamp), take the max KF NIS
    across federate receivers. This matches how a ground station would aggregate
    alerts from multiple receivers.

    Args:
        scenario: ScenarioData with RX events
        federate_ids: Set of host IDs designated as federates

    Returns:
        Dict mapping (serial_number, rid_timestamp) -> (max_nis, is_spoofed)
    """
    transmission_scores: dict[tuple[int, int], list[float]] = defaultdict(list)
    transmission_labels: dict[tuple[int, int], bool] = {}

    for i in range(scenario.n_events):
        # Only use federate receivers
        if scenario.host_id[i] not in federate_ids:
            continue

        sn = scenario.serial_number[i]
        rid_ts = scenario.rid_timestamp[i]
        key = (sn, rid_ts)

        nis = scenario.kf_nis[i]
        if not np.isnan(nis):
            transmission_scores[key].append(nis)
        transmission_labels[key] = scenario.is_spoofed[i]

    # Aggregate: use max NIS per transmission
    result = {}
    for key, scores in transmission_scores.items():
        if scores:
            result[key] = (max(scores), transmission_labels[key])

    return result


def evaluate_on_test_transmissions(
    test_dir: Path,
    mlp_predictions_path: Path,
    kf_threshold: float,
    mlat_threshold: float,
    mlat_ple: float,
    output_dir: Path | None = None,
    test_limit: int | None = None,
):
    """
    Evaluate all three methods on the same set of test transmissions.

    Only evaluates on transmissions that:
    1. Have MLP predictions
    2. Have scores from all 4 federates (for MLAT)
    3. Have KF scores from at least one federate
    """
    print("=" * 70)
    print("UNIFIED EVALUATION - Comparing KF, MLAT, MLP")
    print("=" * 70)

    # Load MLP predictions
    print(f"\nLoading MLP predictions from {mlp_predictions_path}...")
    mlp_df = pd.read_csv(mlp_predictions_path)

    # Fix filename paths: ./datasets/test/X.csv -> just the filename
    mlp_df['csv_name'] = mlp_df['filename'].apply(lambda x: Path(x).name)

    # Group MLP predictions by (csv_name, serial_number, rid_timestamp)
    mlp_predictions = {}
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

    # Initialize detectors
    kf_detector = KalmanFilterDetector()
    mlat_detector = MultilatDetector(path_loss_exp=mlat_ple)

    # Collect predictions for all methods
    all_kf_scores = []
    all_kf_labels = []
    all_mlat_scores = []
    all_mlat_labels = []
    all_mlp_scores = []
    all_mlp_labels = []

    # Common transmissions (have scores from all three methods)
    common_scores = {'kf': [], 'mlat': [], 'mlp': []}
    common_labels = []

    print(f"\nProcessing test scenarios from {test_dir}...")

    csv_files = sorted(test_dir.glob("*.csv"))
    if test_limit:
        csv_files = csv_files[:test_limit]

    n_processed = 0
    for csv_path in csv_files:
        csv_name = csv_path.name

        # Skip if no MLP predictions for this scenario
        if csv_name not in test_csv_names:
            continue

        scenario = load_scenario(csv_path)
        federate_ids = set(scenario.federate_host_ids)

        # Get KF scores per transmission (federate-only)
        kf_transmission_scores = aggregate_kf_scores_per_transmission(scenario, federate_ids)

        # Get MLAT scores
        mlat_scores_array = mlat_detector.score(scenario)

        # Group MLAT scores by transmission
        mlat_transmission_scores = {}
        for i in range(scenario.n_events):
            if mlat_scores_array[i] > 0:  # MLAT only produces non-zero for 4+ federates
                key = (scenario.serial_number[i], scenario.rid_timestamp[i])
                if key not in mlat_transmission_scores:
                    mlat_transmission_scores[key] = (mlat_scores_array[i], scenario.is_spoofed[i])

        # Match with MLP predictions
        for (sn, rid_ts), (mlat_score, label) in mlat_transmission_scores.items():
            mlp_key = (csv_name, sn, rid_ts)

            if mlp_key not in mlp_predictions:
                continue

            kf_key = (sn, rid_ts)
            if kf_key not in kf_transmission_scores:
                continue

            kf_score, _ = kf_transmission_scores[kf_key]
            mlp_data = mlp_predictions[mlp_key]

            # All methods have scores for this transmission
            all_kf_scores.append(kf_score)
            all_kf_labels.append(label)
            all_mlat_scores.append(mlat_score)
            all_mlat_labels.append(label)
            all_mlp_scores.append(mlp_data['y_proba'])
            all_mlp_labels.append(mlp_data['is_spoofed'])

            # Common set
            common_scores['kf'].append(kf_score)
            common_scores['mlat'].append(mlat_score)
            common_scores['mlp'].append(mlp_data['y_proba'])
            common_labels.append(label)

        n_processed += 1
        if n_processed % 100 == 0:
            print(f"  Processed {n_processed} scenarios...")

    print(f"\n  Total scenarios processed: {n_processed}")
    print(f"  Common transmissions (all 3 methods): {len(common_labels)}")

    # Convert to numpy
    common_labels = np.array(common_labels)
    for k in common_scores:
        common_scores[k] = np.array(common_scores[k])

    print(f"  Spoofed: {common_labels.sum()}, Benign: {(~common_labels).sum()}")

    # Compute metrics on common set
    print("\n" + "=" * 70)
    print("RESULTS ON COMMON TRANSMISSIONS")
    print("=" * 70)

    results = {}

    for name, scores, threshold in [
        ('KF', common_scores['kf'], kf_threshold),
        ('MLAT', common_scores['mlat'], mlat_threshold),
        ('MLP', common_scores['mlp'], 0.5),
    ]:
        auc, fpr_arr, tpr_arr, thresholds = compute_roc_auc(common_labels, scores)
        predictions = scores >= threshold
        tp = ((predictions == 1) & (common_labels == 1)).sum()
        tn = ((predictions == 0) & (common_labels == 0)).sum()
        fp = ((predictions == 1) & (common_labels == 0)).sum()
        fn = ((predictions == 0) & (common_labels == 1)).sum()

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
    print(f"{'Method':<10} {'AUC':>8} {'TPR':>8} {'FPR':>8} {'Threshold':>12}")
    print("-" * 50)
    for name in ['kf', 'mlat', 'mlp']:
        r = results[name]
        print(f"{name.upper():<10} {r['auc']:>8.4f} {r['tpr']:>8.4f} {r['fpr']:>8.4f} {r['threshold']:>12.4f}")

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
            results_json['n_transmissions'] = len(common_labels)
            results_json['n_spoofed'] = int(common_labels.sum())
            results_json['n_benign'] = int((~common_labels).sum())
            json.dump(results_json, f, indent=2)
        print(f"\nResults saved to {results_path}")

        # Generate ROC curve figure
        fig, ax = plt.subplots(figsize=(8, 6))

        colors = {'kf': 'blue', 'mlat': 'green', 'mlp': 'red'}
        labels = {'kf': 'Kalman Filter', 'mlat': 'Multilateration', 'mlp': 'MLP'}

        for name in ['kf', 'mlat', 'mlp']:
            fpr = results[name]['fpr_curve']
            tpr = results[name]['tpr_curve']
            auc = results[name]['auc']
            ax.plot(fpr, tpr, color=colors[name], linewidth=2,
                   label=f'{labels[name]} (AUC={auc:.3f})')

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
        for name in ['kf', 'mlat', 'mlp']:
            fpr = results[name]['fpr_curve']
            tpr = results[name]['tpr_curve']
            auc = results[name]['auc']
            ax.plot(fpr, tpr, color=colors[name], linewidth=2,
                   label=f'{labels[name]} (AUC={auc:.3f})')
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

    # Train KF threshold
    print("\nOptimizing KF threshold...")
    kf_detector = KalmanFilterDetector()
    kf_opt = optimize_threshold(kf_detector, train_scenarios, verbose=True)
    kf_threshold = kf_opt.best_threshold

    # Line search for MLAT path loss exponent
    print("\nLine search for MLAT path loss exponent...")
    path_loss_values = [1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0]

    best_auc = -1
    best_ple = 2.0
    best_mlat_threshold = 100.0

    for ple in path_loss_values:
        mlat_detector = MultilatDetector(path_loss_exp=ple)
        opt = optimize_threshold(mlat_detector, train_scenarios, verbose=False)
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
    parser.add_argument("--mlp-predictions", type=Path, required=True,
                       help="MLP predictions CSV file")
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
