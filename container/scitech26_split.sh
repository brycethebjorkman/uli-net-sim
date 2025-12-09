#!/usr/bin/env bash
#
# scitech26_split.sh
#
# Partition the SciTech 2026 dataset into train/test sets at the scenario level.
# All CSV variants for a given scenario stay together in the same partition.
#
# USAGE:
#   ./container/scitech26_split.sh [options]
#
# OPTIONS:
#   --input DIR       Input dataset directory (default: datasets/scitech26)
#   --train-ratio N   Training set ratio 0.0-1.0 (default: 0.8)
#   --seed N          Random seed for deterministic splitting (default: 42)
#   --dry-run         Show what would be done without copying files
#   --help            Show this help message
#
# OUTPUT:
#   datasets/scitech26/train/*.csv   (80% of scenarios)
#   datasets/scitech26/test/*.csv    (20% of scenarios)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Defaults
INPUT_DIR="$PROJ_DIR/datasets/scitech26"
TRAIN_RATIO=0.8
SEED=42
DRY_RUN=false

usage() {
    cat <<EOF
Usage: $0 [options]

Partition the SciTech 2026 dataset into train/test sets at the scenario level.
All CSV variants for a given scenario stay together in the same partition.

Options:
    --input DIR       Input dataset directory (default: datasets/scitech26)
    --train-ratio N   Training set ratio 0.0-1.0 (default: 0.8)
    --seed N          Random seed for deterministic splitting (default: 42)
    --dry-run         Show what would be done without copying files
    --help            Show this help message

Output:
    datasets/scitech26/train/*.csv   (train_ratio of scenarios)
    datasets/scitech26/test/*.csv    (1 - train_ratio of scenarios)

Example:
    $0 --train-ratio 0.8 --seed 42
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --input) INPUT_DIR="$2"; shift 2 ;;
        --train-ratio) TRAIN_RATIO="$2"; shift 2 ;;
        --seed) SEED="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

# Validate input directory
URBANENV_DIR="$INPUT_DIR/urbanenv"
if [ ! -d "$URBANENV_DIR" ]; then
    echo "Error: Input directory not found: $URBANENV_DIR"
    echo "Make sure the dataset has been generated first."
    exit 1
fi

# Output directories
TRAIN_DIR="$INPUT_DIR/train"
TEST_DIR="$INPUT_DIR/test"

echo "============================================================"
echo "SciTech 2026 Dataset Train/Test Split"
echo "============================================================"
echo ""
echo "Input directory:   $URBANENV_DIR"
echo "Train ratio:       $TRAIN_RATIO"
echo "Random seed:       $SEED"
echo "Output:"
echo "  Train:           $TRAIN_DIR"
echo "  Test:            $TEST_DIR"
echo ""

# Find all scenario directories (contain CSV files)
# Scenario dirs are under: urbanenv/grid.../ew.../scenarios/bldg_...__traj_...__seed.../
echo "Finding scenarios..."
SCENARIO_DIRS=()
while IFS= read -r -d '' dir; do
    # Check if directory contains CSV files
    if ls "$dir"/*.csv &>/dev/null; then
        SCENARIO_DIRS+=("$dir")
    fi
done < <(find "$URBANENV_DIR" -type d -path "*/scenarios/*" -print0 2>/dev/null)

TOTAL_SCENARIOS=${#SCENARIO_DIRS[@]}

if [ "$TOTAL_SCENARIOS" -eq 0 ]; then
    echo "Error: No scenarios with CSV files found in $URBANENV_DIR"
    exit 1
fi

echo "Found $TOTAL_SCENARIOS scenarios"
echo ""

# Use Python for deterministic random shuffling and splitting
read -r TRAIN_COUNT TEST_COUNT < <(python3 -c "
import math
train_ratio = $TRAIN_RATIO
total = $TOTAL_SCENARIOS
train_count = int(math.floor(total * train_ratio))
test_count = total - train_count
print(train_count, test_count)
")

echo "Split:"
echo "  Train scenarios: $TRAIN_COUNT ($TRAIN_RATIO)"
echo "  Test scenarios:  $TEST_COUNT ($(echo "1 - $TRAIN_RATIO" | bc))"
echo ""

# Get shuffled indices using Python for determinism
SHUFFLED_INDICES=$(python3 -c "
import random
random.seed($SEED)
indices = list(range($TOTAL_SCENARIOS))
random.shuffle(indices)
print(' '.join(map(str, indices)))
")

# Convert to array
read -ra INDICES <<< "$SHUFFLED_INDICES"

# Split indices
TRAIN_INDICES=("${INDICES[@]:0:$TRAIN_COUNT}")
TEST_INDICES=("${INDICES[@]:$TRAIN_COUNT}")

if [ "$DRY_RUN" = true ]; then
    echo "=== DRY RUN MODE ==="
    echo ""
    echo "Would create directories:"
    echo "  $TRAIN_DIR"
    echo "  $TEST_DIR"
    echo ""

    # Count CSVs
    TRAIN_CSV_COUNT=0
    for idx in "${TRAIN_INDICES[@]}"; do
        count=$(ls "${SCENARIO_DIRS[$idx]}"/*.csv 2>/dev/null | wc -l)
        TRAIN_CSV_COUNT=$((TRAIN_CSV_COUNT + count))
    done

    TEST_CSV_COUNT=0
    for idx in "${TEST_INDICES[@]}"; do
        count=$(ls "${SCENARIO_DIRS[$idx]}"/*.csv 2>/dev/null | wc -l)
        TEST_CSV_COUNT=$((TEST_CSV_COUNT + count))
    done

    echo "Would copy:"
    echo "  Train: $TRAIN_CSV_COUNT CSV files from $TRAIN_COUNT scenarios"
    echo "  Test:  $TEST_CSV_COUNT CSV files from $TEST_COUNT scenarios"
    echo ""

    echo "Sample train scenarios (first 5):"
    for i in "${TRAIN_INDICES[@]:0:5}"; do
        echo "  $(basename "${SCENARIO_DIRS[$i]}")"
    done
    echo ""

    echo "Sample test scenarios (first 5):"
    for i in "${TEST_INDICES[@]:0:5}"; do
        echo "  $(basename "${SCENARIO_DIRS[$i]}")"
    done

    exit 0
fi

# Create output directories
echo "Creating output directories..."
mkdir -p "$TRAIN_DIR"
mkdir -p "$TEST_DIR"

# Copy train CSVs
echo "Copying train set ($TRAIN_COUNT scenarios)..."
TRAIN_CSV_COUNT=0
for idx in "${TRAIN_INDICES[@]}"; do
    scenario_dir="${SCENARIO_DIRS[$idx]}"
    for csv in "$scenario_dir"/*.csv; do
        if [ -f "$csv" ]; then
            cp "$csv" "$TRAIN_DIR/"
            TRAIN_CSV_COUNT=$((TRAIN_CSV_COUNT + 1))
        fi
    done
done
echo "  Copied $TRAIN_CSV_COUNT CSV files"

# Copy test CSVs
echo "Copying test set ($TEST_COUNT scenarios)..."
TEST_CSV_COUNT=0
for idx in "${TEST_INDICES[@]}"; do
    scenario_dir="${SCENARIO_DIRS[$idx]}"
    for csv in "$scenario_dir"/*.csv; do
        if [ -f "$csv" ]; then
            cp "$csv" "$TEST_DIR/"
            TEST_CSV_COUNT=$((TEST_CSV_COUNT + 1))
        fi
    done
done
echo "  Copied $TEST_CSV_COUNT CSV files"

echo ""
echo "============================================================"
echo "Split complete!"
echo "============================================================"
echo ""
echo "Train set: $TRAIN_DIR"
echo "  Scenarios: $TRAIN_COUNT"
echo "  CSV files: $TRAIN_CSV_COUNT"
echo ""
echo "Test set: $TEST_DIR"
echo "  Scenarios: $TEST_COUNT"
echo "  CSV files: $TEST_CSV_COUNT"
echo ""
echo "Total CSV files: $((TRAIN_CSV_COUNT + TEST_CSV_COUNT))"
