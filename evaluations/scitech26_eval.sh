#!/bin/bash
#
# Reproducible evaluation for the SciTech26 paper
#
# This script runs test-only evaluation on the scitech26-1920-scenarios dataset
# using pre-optimized thresholds, producing the results and figures for the paper.
#
# Threshold Optimization (performed on 300 training scenarios due to memory constraints):
#   - KF threshold: 0.6126 (optimized via Youden's J on 300 scenarios, ~8M events)
#   - MLAT PLE: 1.8 (best from line search: 1.6→0.8087, 1.8→0.8094, 2.0→0.8085)
#   - MLAT threshold: 114.3571 (position error threshold)
#
# Usage:
#   cd /usr/uli-net-sim/uav_rid
#   . container/setenv
#   ./evaluations/scitech26_eval.sh
#
# Output:
#   evaluations/results/unified_results.json - Numeric results
#   evaluations/results/roc_curves.pdf       - ROC curve figure for paper
#   evaluations/results/roc_curves.png       - ROC curve figure (preview)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Dataset paths
DATASET_DIR="$PROJECT_DIR/datasets/scitech26-1920-scenarios"
TEST_DIR="$DATASET_DIR/test"
MLP_PREDICTIONS="$PROJECT_DIR/datasets/mlp_test_predictions.csv"
OUTPUT_DIR="$SCRIPT_DIR/results"

# Pre-optimized thresholds (from training on 300 scenarios)
KF_THRESHOLD=0.6126
MLAT_THRESHOLD=114.3571
MLAT_PLE=1.8

# Validate inputs
echo "============================================================"
echo "SciTech26 Paper Evaluation - Reproducible Results"
echo "============================================================"
echo ""
echo "Configuration:"
echo "  Test dir:         $TEST_DIR"
echo "  MLP predictions:  $MLP_PREDICTIONS"
echo "  Output dir:       $OUTPUT_DIR"
echo ""
echo "Pre-optimized thresholds:"
echo "  KF threshold:     $KF_THRESHOLD"
echo "  MLAT threshold:   $MLAT_THRESHOLD"
echo "  MLAT PLE:         $MLAT_PLE"
echo ""

if [ ! -d "$TEST_DIR" ]; then
    echo "ERROR: Test directory not found: $TEST_DIR"
    exit 1
fi

if [ ! -f "$MLP_PREDICTIONS" ]; then
    echo "ERROR: MLP predictions file not found: $MLP_PREDICTIONS"
    exit 1
fi

# Count scenarios
N_TEST=$(ls -1 "$TEST_DIR"/*.csv 2>/dev/null | wc -l)
echo "Dataset:"
echo "  Test scenarios:     $N_TEST"
echo ""

# Run test-only evaluation with pre-optimized thresholds
echo "Starting test-only evaluation..."
echo ""

cd "$PROJECT_DIR"
python -u -m evaluations.unified_eval \
    --test-dir "$TEST_DIR" \
    --mlp-predictions "$MLP_PREDICTIONS" \
    --test-only \
    --kf-threshold "$KF_THRESHOLD" \
    --mlat-threshold "$MLAT_THRESHOLD" \
    --mlat-ple "$MLAT_PLE" \
    -o "$OUTPUT_DIR"

echo ""
echo "============================================================"
echo "Evaluation complete!"
echo "============================================================"
echo ""
echo "Results saved to:"
echo "  $OUTPUT_DIR/unified_results.json"
echo "  $OUTPUT_DIR/roc_curves.pdf"
echo "  $OUTPUT_DIR/roc_curves.png"
