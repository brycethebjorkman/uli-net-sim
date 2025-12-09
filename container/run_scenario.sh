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
#   UAV_RID_BIN, INET_ROOT, PROJ_DIR, VEC2CSV, ADD_HOST_TYPE
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
    ${UAV_RID_BIN} -m \
        -u Cmdenv \
        -c "$CONFIG_NAME" \
        -l "$INET_ROOT/out/clang-release/src/libINET.so" \
        -n "$INET_ROOT/src" \
        -n "$INET_ROOT/src/inet/visualizer/common" \
        -n "$INET_ROOT/examples" \
        -n "$INET_ROOT/showcases" \
        -n "$INET_ROOT/tests/validation" \
        -n "$INET_ROOT/tests/networks" \
        -n "$INET_ROOT/tutorials" \
        -n "$PROJ_DIR/simulations" \
        -n "$PROJ_DIR/src" \
        -f "omnetpp.ini" \
        --cmdenv-express-mode=true \
        --cmdenv-status-frequency=10s \
        --result-dir="results" \
        2>&1 | grep -v "^$" || true
    popd > /dev/null

    # Convert to CSV with hash-based name
    VEC_FILE="$RESULTS_DIR/${CONFIG_NAME}-#0.vec"
    if [ -f "$VEC_FILE" ]; then
        if [ "$CONFIG_NAME" = "ScenarioOpenSpace" ]; then
            CSV_SUFFIX="-o"
        else
            CSV_SUFFIX="-b"
        fi
        CSV_FILE="$SCENARIO_PATH/${SCENARIO_HASH}${CSV_SUFFIX}.csv"
        echo "  [$SCENARIO_NAME] Converting to CSV..."
        python3 "$VEC2CSV" "$VEC_FILE" -o "$CSV_FILE"

        # Add host_type column
        if [ -n "$SPOOFER_HOST" ] && [ "$SPOOFER_HOST" != "-" ]; then
            python3 "$ADD_HOST_TYPE" "$CSV_FILE" --in-place --spoofer-hosts "$SPOOFER_HOST"
        else
            python3 "$ADD_HOST_TYPE" "$CSV_FILE" --in-place
        fi

        echo "  [$SCENARIO_NAME] Created: $(basename "$CSV_FILE")"
    else
        echo "  [$SCENARIO_NAME] Warning: Vector file not found: $VEC_FILE"
    fi
done

echo "  [$SCENARIO_NAME] Complete"
