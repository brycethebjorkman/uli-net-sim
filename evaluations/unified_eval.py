#!/usr/bin/env python3
"""
Unified evaluation CLI for comparing KF, MLAT, and MLP detectors.

Two-stage workflow:

Stage 1 - Score (expensive, runs detectors on test set):
    python -m evaluations.unified_eval score \
        --test-dir datasets/scitech26/test \
        --train-dir datasets/scitech26/train \
        -o evaluations/results/

Stage 2 - Analyze (cheap, iterate freely on thresholds/plots):
    python -m evaluations.unified_eval analyze \
        --scores-dir evaluations/results/ \
        --mlp-predictions datasets/mlp_test_predictions.csv \
        -o evaluations/results/
"""

import argparse
from pathlib import Path

from .scoring import score_test_set
from .analysis import analyze_scores


def main():
    parser = argparse.ArgumentParser(
        description="Unified evaluation comparing KF, MLAT, and MLP detectors"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

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

    # --- analyze subcommand ---
    analyze_parser = subparsers.add_parser(
        "analyze",
        help="Analyze pre-computed scores: ROC, confusion matrix, plots (cheap)",
    )
    analyze_parser.add_argument("--scores-dir", type=Path, required=True,
                                help="Directory containing kf_scores.csv, mlat_scores.csv, thresholds.json")
    analyze_parser.add_argument("--mlp-predictions", type=Path,
                                help="MLP predictions CSV file (optional)")
    analyze_parser.add_argument("-o", "--output", type=Path,
                                help="Output directory (defaults to scores-dir)")
    analyze_parser.add_argument("--kf-threshold", type=float,
                                help="Override KF threshold from thresholds.json")
    analyze_parser.add_argument("--mlat-threshold", type=float,
                                help="Override MLAT threshold from thresholds.json")

    args = parser.parse_args()

    if args.command == "score":
        if args.kf_threshold is not None and args.mlat_threshold is not None:
            kf_thresh = args.kf_threshold
            mlat_thresh = args.mlat_threshold
        elif args.train_dir is not None:
            kf_thresh = args.kf_threshold
            mlat_thresh = args.mlat_threshold
        else:
            parser.error("score requires --train-dir or both --kf-threshold and --mlat-threshold")
            return  # unreachable, for type checker

        score_test_set(
            test_dir=args.test_dir,
            output_dir=args.output,
            train_dir=args.train_dir,
            test_limit=args.test_limit,
            train_limit=args.train_limit,
            kf_threshold=kf_thresh,
            mlat_threshold=mlat_thresh,
        )

    elif args.command == "analyze":
        analyze_scores(
            scores_dir=args.scores_dir,
            output_dir=args.output,
            kf_threshold=args.kf_threshold,
            mlat_threshold=args.mlat_threshold,
            mlp_predictions_path=args.mlp_predictions,
        )


if __name__ == "__main__":
    main()
