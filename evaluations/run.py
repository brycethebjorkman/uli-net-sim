#!/usr/bin/env python3
"""
CLI for running spoofing detection evaluations.

Usage:
    python -m evaluations.run kf datasets/scitech26/train datasets/scitech26/test
    python -m evaluations.run mlat datasets/scitech26/train datasets/scitech26/test
    python -m evaluations.run all datasets/scitech26/train datasets/scitech26/test -o results/
"""

import argparse
import json
from pathlib import Path

from .detectors import KalmanFilterDetector, MultilatDetector
from .evaluate import run_evaluation
from .optimize import grid_search
from .data import load_dataset


def run_kf(args):
    """Run Kalman Filter detector evaluation."""
    detector = KalmanFilterDetector()
    opt, eval_result = run_evaluation(
        detector,
        train_dir=args.train_dir,
        test_dir=args.test_dir,
        output_path=args.output / "kf_results.json" if args.output else None,
        train_limit=args.train_limit,
        test_limit=args.test_limit,
        verbose=True,
    )
    return opt, eval_result


def run_mlat(args):
    """Run multilateration detector evaluation with grid search."""
    print("=== Grid Search for Multilateration Parameters ===")

    train_scenarios = load_dataset(args.train_dir, limit=args.train_limit)
    print(f"Loaded {len(train_scenarios)} training scenarios")

    # Grid search over path loss exponent and score type
    # Note: MultilatDetector now jointly estimates position and TX power
    param_grid = {
        "path_loss_exp": [1.6, 1.8, 2.0, 2.2, 2.4],
        "use_filtered_error": [True, False],
    }

    best_opt, best_params = grid_search(
        MultilatDetector,
        param_grid,
        train_scenarios,
        verbose=True,
    )

    print(f"\nBest parameters: {best_params}")
    print(f"Best AUC: {best_opt.best_auc:.4f}")

    # Evaluate with best params
    detector = MultilatDetector(**best_params)
    opt, eval_result = run_evaluation(
        detector,
        train_dir=args.train_dir,
        test_dir=args.test_dir,
        output_path=args.output / "mlat_results.json" if args.output else None,
        train_limit=args.train_limit,
        test_limit=args.test_limit,
        verbose=True,
    )
    return opt, eval_result


def run_all(args):
    """Run all detectors."""
    results = {}

    print("=" * 60)
    print("KALMAN FILTER DETECTOR")
    print("=" * 60)
    kf_opt, kf_eval = run_kf(args)
    results["kf"] = kf_eval.to_dict()

    print("\n" + "=" * 60)
    print("MULTILATERATION DETECTOR")
    print("=" * 60)
    mlat_opt, mlat_eval = run_mlat(args)
    results["mlat"] = mlat_eval.to_dict()

    # Save combined results
    if args.output:
        combined_path = args.output / "all_results.json"
        with open(combined_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nCombined results saved to {combined_path}")

    # Print comparison
    print("\n" + "=" * 60)
    print("COMPARISON")
    print("=" * 60)
    print(f"{'Detector':<15} {'AUC':>8} {'TPR':>8} {'FPR':>8} {'Mean TTD':>10}")
    print("-" * 60)
    for name, r in results.items():
        ttd = r.get("mean_time_to_detection")
        ttd_str = f"{ttd:.3f}s" if ttd else "N/A"
        print(f"{name:<15} {r['metrics']['auc']:>8.4f} {r['metrics']['tpr']:>8.4f} "
              f"{r['metrics']['fpr']:>8.4f} {ttd_str:>10}")


def main():
    parser = argparse.ArgumentParser(description="Run spoofing detection evaluations")
    parser.add_argument(
        "detector",
        choices=["kf", "mlat", "all"],
        help="Detector to evaluate (kf=Kalman Filter, mlat=Multilateration, all=both)",
    )
    parser.add_argument("train_dir", type=Path, help="Training data directory")
    parser.add_argument("test_dir", type=Path, help="Test data directory")
    parser.add_argument("-o", "--output", type=Path, help="Output directory for results")
    parser.add_argument("--train-limit", type=int, help="Limit training scenarios")
    parser.add_argument("--test-limit", type=int, help="Limit test scenarios")

    args = parser.parse_args()

    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)

    if args.detector == "kf":
        run_kf(args)
    elif args.detector == "mlat":
        run_mlat(args)
    elif args.detector == "all":
        run_all(args)


if __name__ == "__main__":
    main()
