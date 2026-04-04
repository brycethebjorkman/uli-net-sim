#!/usr/bin/env bash
#
# run_scenario.sh
#
# Execute a single urbanenv scenario (simulation + CSV conversion + post-processing).
# Designed to be called in parallel by generate_dataset.sh.
#
# Usage:
#   ./run_scenario.sh <scenario_path> <spoofer_host>
#
# Environment variables required (set by parent script):
#   PROJ_DIR, VEC2CSV, ADD_HOST_TYPE
#

set -e

SCENARIO_PATH="$1"
SPOOFER_HOST="$2"

if [ -z "$SCENARIO_PATH" ]; then
    echo "Error: scenario_path required"
    exit 1
fi

# Extract scenario hash from the path
SCENARIO_NAME=$(basename "$SCENARIO_PATH")
# Walk up to get the relative path structure for hashing
CORRIDOR_PATH=$(dirname "$SCENARIO_PATH")
CORRIDOR_PATH=$(dirname "$CORRIDOR_PATH")  # Go past 'scenarios'
CORRIDOR_DIR=$(basename "$CORRIDOR_PATH")
PARAM_PATH=$(dirname "$CORRIDOR_PATH")
PARAM_DIR=$(basename "$PARAM_PATH")

SCENARIO_REL_PATH="${PARAM_DIR}/${CORRIDOR_DIR}/scenarios/${SCENARIO_NAME}"
SCENARIO_HASH=$(echo -n "$SCENARIO_REL_PATH" | md5sum | cut -c1-8)

INI_FILE="$SCENARIO_PATH/omnetpp.ini"
RESULTS_DIR="$SCENARIO_PATH/results"

if [ ! -f "$INI_FILE" ]; then
    echo "Error: INI file not found: $INI_FILE"
    exit 1
fi

mkdir -p "$RESULTS_DIR"

# Determine which configs to run based on INI file contents
CONFIGS_TO_RUN=("ScenarioOpenSpace")
if grep -q "ScenarioWithBuildings" "$INI_FILE"; then
    CONFIGS_TO_RUN+=("ScenarioWithBuildings")
fi

# Run each config
for CONFIG_NAME in "${CONFIGS_TO_RUN[@]}"; do
    echo "  [$SCENARIO_NAME] Running $CONFIG_NAME..."

    # Run from the scenario directory so relative paths in ini work
    pushd "$SCENARIO_PATH" > /dev/null
    "$PROJ_DIR/scripts/run.sh" -f "omnetpp.ini" -c "$CONFIG_NAME" -r "results" \
        2>&1 | grep -v "^$" || true
    popd > /dev/null

    # Convert to Parquet with hash-based name
    VEC_FILE="$RESULTS_DIR/${CONFIG_NAME}-#0.vec"
    if [ -f "$VEC_FILE" ]; then
        if [ "$CONFIG_NAME" = "ScenarioOpenSpace" ]; then
            PQ_SUFFIX="-o"
        else
            PQ_SUFFIX="-b"
        fi
        PQ_FILE="$SCENARIO_PATH/${SCENARIO_HASH}${PQ_SUFFIX}.parquet"
        echo "  [$SCENARIO_NAME] Converting to Parquet..."
        VEC2PQ_ARGS=("$VEC_FILE" -o "$PQ_FILE")
        if [ -n "$SPOOFER_HOST" ] && [ "$SPOOFER_HOST" != "-" ]; then
            VEC2PQ_ARGS+=(--spoofer-hosts "$SPOOFER_HOST")
        fi
        python3 "$VEC2CSV" "${VEC2PQ_ARGS[@]}"

        echo "  [$SCENARIO_NAME] Created: $(basename "$PQ_FILE")"
    else
        echo "  [$SCENARIO_NAME] Warning: Vector file not found: $VEC_FILE"
    fi
done

# Clean up intermediate artifacts (VEC, SCA files) to save disk space
if [ -d "$RESULTS_DIR" ]; then
    rm -rf "$RESULTS_DIR"
    echo "  [$SCENARIO_NAME] Cleaned up intermediate results"
fi

echo "  [$SCENARIO_NAME] Complete"
