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
    """Run multilateration detector evaluation with line search over path loss exponent."""
    print("=== Line Search for Path Loss Exponent ===")

    train_scenarios = load_dataset(args.train_dir, limit=args.train_limit)
    print(f"Loaded {len(train_scenarios)} training scenarios")

    # Line search over path loss exponent only
    # n=2.0 is free space, but buildings/obstacles can increase it
    path_loss_values = [1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0]

    from .optimize import optimize_threshold

    best_auc = -1
    best_ple = 2.0
    best_opt = None

    for ple in path_loss_values:
        detector = MultilatDetector(path_loss_exp=ple)
        opt = optimize_threshold(detector, train_scenarios, verbose=False)
        print(f"  path_loss_exp={ple:.1f}: AUC={opt.best_auc:.4f}")

        if opt.best_auc > best_auc:
            best_auc = opt.best_auc
            best_ple = ple
            best_opt = opt

    print(f"\nBest path_loss_exp: {best_ple}")
    print(f"Best AUC: {best_auc:.4f}")

    # Evaluate with best path loss exponent
    detector = MultilatDetector(path_loss_exp=best_ple)
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

    # Load train and test results from saved files for comparison
    train_test_results = {}
    if args.output:
        for detector_name in ["kf", "mlat"]:
            results_file = args.output / f"{detector_name}_results.json"
            if results_file.exists():
                with open(results_file) as f:
                    train_test_results[detector_name] = json.load(f)

        # Save combined results
        combined_path = args.output / "all_results.json"
        with open(combined_path, "w") as f:
            json.dump(train_test_results, f, indent=2)
        print(f"\nCombined results saved to {combined_path}")

    # Print comparison with both train and test
    print("\n" + "=" * 80)
    print("COMPARISON (Train / Test)")
    print("=" * 80)
    print(f"{'Detector':<12} {'Split':<6} {'AUC':>8} {'TPR':>8} {'FPR':>8} {'Mean TTD':>10}")
    print("-" * 80)
    for name in ["kf", "mlat"]:
        if name in train_test_results:
            r = train_test_results[name]
            for split in ["train", "test"]:
                eval_key = f"{split}_evaluation"
                if eval_key in r:
                    e = r[eval_key]
                    ttd = e.get("mean_time_to_detection")
                    ttd_str = f"{ttd:.3f}s" if ttd else "N/A"
                    print(f"{name:<12} {split:<6} {e['metrics']['auc']:>8.4f} {e['metrics']['tpr']:>8.4f} "
                          f"{e['metrics']['fpr']:>8.4f} {ttd_str:>10}")
            print("-" * 80)


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
