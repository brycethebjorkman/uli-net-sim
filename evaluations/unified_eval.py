#!/usr/bin/env python3
"""
Unified evaluation CLI for comparing KF, MLAT, and MLP detectors.

Three subcommands:

Train (saves thresholds and MLP weights, no test scoring):
    python -m evaluations.unified_eval train \
        --train-dir datasets/scitech26/train \
        -o evaluations/results/

    Writes thresholds.json, mlp_weights.pth, mlp_scaler.pkl.
    Use --detectors to train only a subset (kf, mlat, mlp).

Score (expensive, runs detectors on test set):
    python -m evaluations.unified_eval score \
        --test-dir datasets/scitech26/test \
        --train-dir datasets/scitech26/train \
        -o evaluations/results/

    Writes kf_scores.csv, mlat_scores.csv, mlp_scores.csv, thresholds.json,
    mlp_weights.pth, and mlp_scaler.pkl to the output directory.
    Loads existing mlp_weights.pth + mlp_scaler.pkl if present (skip MLP retraining).

Analyze (cheap, iterate freely on thresholds/plots):
    python -m evaluations.unified_eval analyze \
        --scores-dir evaluations/results/ \
        -o evaluations/results/

    Reads mlp_scores.csv automatically if present in scores-dir.
"""

import argparse
from pathlib import Path

from .scoring import score_test_set, train_detectors
from .analysis import analyze_scores


def main():
    parser = argparse.ArgumentParser(
        description="Unified evaluation comparing KF, MLAT, and MLP detectors"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- train subcommand ---
    train_parser = subparsers.add_parser(
        "train",
        help="Train detectors on training data, write thresholds/weights (no test scoring)",
    )
    train_parser.add_argument("--train-dir", type=Path, required=True,
                              help="Training data directory")
    train_parser.add_argument("-o", "--output", type=Path, required=True,
                              help="Output directory for thresholds.json and MLP weights")
    train_parser.add_argument("--detectors", nargs="+",
                              choices=["kf", "mlat", "mlp"],
                              default=["kf", "mlat", "mlp"],
                              metavar="DETECTOR",
                              help="Detectors to train: kf, mlat, mlp (default: all)")
    train_parser.add_argument("--train-limit", type=int,
                              help="Limit training scenarios (for testing)")
    train_parser.add_argument("--seed", type=int, default=42,
                              help="Random seed for MLP training (default: 42)")

    # --- score subcommand ---
    score_parser = subparsers.add_parser(
        "score",
        help="Run detectors on test set, write per-sample score CSVs (expensive)",
    )
    score_parser.add_argument("--test-dir", type=Path, required=True,
                              help="Test data directory")
    score_parser.add_argument("--train-dir", type=Path,
                              help="Training data directory (for threshold optimization)")
    score_parser.add_argument("-o", "--output", type=Path, required=True,
                              help="Output directory for score CSVs and thresholds")
    score_parser.add_argument("--kf-threshold", type=float,
                              help="Pre-computed KF threshold (skips training)")
    score_parser.add_argument("--mlat-threshold", type=float,
                              help="Pre-computed MLAT threshold (skips training)")
    score_parser.add_argument("--train-limit", type=int,
                              help="Limit training scenarios (for testing)")
    score_parser.add_argument("--test-limit", type=int,
                              help="Limit test scenarios (for testing)")
    score_parser.add_argument("--detectors", nargs="+",
                              choices=["kf", "mlat", "mlp"],
                              default=["kf", "mlat", "mlp"],
                              metavar="DETECTOR",
                              help="Detectors to score: kf, mlat, mlp (default: all)")
    score_parser.add_argument("--seed", type=int, default=42,
                              help="Random seed for MLP training (default: 42)")

    # --- analyze subcommand ---
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze pre-computed scores: ROC, confusion matrix, plots (cheap)",
    )
    analyze_parser.add_argument("--scores-dir", type=Path, required=True,
                                help="Directory containing kf_scores.csv, mlat_scores.csv, "
                                     "mlp_scores.csv (optional), thresholds.json")
    analyze_parser.add_argument("-o", "--output", type=Path,
                                help="Output directory (defaults to scores-dir)")
    analyze_parser.add_argument("--kf-threshold", type=float,
                                help="Override KF threshold from thresholds.json")
    analyze_parser.add_argument("--mlat-threshold", type=float,
                                help="Override MLAT threshold from thresholds.json")

    args = parser.parse_args()

    if args.command == "train":
        train_detectors(
            train_dir=args.train_dir,
            output_dir=args.output,
            detectors=set(args.detectors),
            train_limit=args.train_limit,
            seed=args.seed,
        )

    elif args.command == "score":
        detectors = set(args.detectors)
        if 'kf' in detectors or 'mlat' in detectors:
            if (args.kf_threshold is None or args.mlat_threshold is None) and args.train_dir is None:
                parser.error(
                    "score requires --train-dir (or --kf-threshold + --mlat-threshold) "
                    "when scoring kf or mlat"
                )
                return  # unreachable, for type checker

        score_test_set(
            test_dir=args.test_dir,
            output_dir=args.output,
            train_dir=args.train_dir,
            detectors=detectors,
            test_limit=args.test_limit,
            train_limit=args.train_limit,
            kf_threshold=args.kf_threshold,
            mlat_threshold=args.mlat_threshold,
            seed=args.seed,
        )

    elif args.command == "analyze":
        analyze_scores(
            scores_dir=args.scores_dir,
            output_dir=args.output,
            kf_threshold=args.kf_threshold,
            mlat_threshold=args.mlat_threshold,
        )


if __name__ == "__main__":
    main()
