#!/usr/bin/env bash
#
# generate_dataset.sh
#
# End-to-end pipeline for generating Remote ID spoofing detection datasets.
# Supports two modes:
#   - random_waypoints: Generates random waypoints, runs simulations, converts to CSV
#   - urbanenv: Generates corridor-constrained urban environments with buildings
#
# USAGE:
#   This script must be run from the uav_rid directory with setenv sourced:
#     cd /usr/uli-net-sim/uav_rid && . container/setenv
#     ./container/generate_dataset.sh <mode> [options]
#
#   Output goes to datasets/ by default (visible on host).
#

set -e

# Determine script location and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_DIR="$(cd "$PROJ_DIR/.." && pwd)"

# Common defaults
OUTPUT_DIR="$PROJ_DIR/datasets"
SEED_START=42

# Show top-level usage
usage_main() {
    cat <<EOF
Usage: $0 <mode> [options]

Generate datasets for Remote ID spoofing detection analysis.

IMPORTANT: Must be run from the uav_rid directory with setenv sourced:
  cd /usr/uli-net-sim/uav_rid && . container/setenv
  ./container/generate_dataset.sh <mode> [options]

Modes:
    random_waypoints    Generate random waypoint trajectories (original mode)
    urbanenv            Generate corridor-constrained urban environments

Run '$0 <mode> --help' for mode-specific options.

Examples:
    $0 random_waypoints -n 10 -h 5 -s 1
    $0 urbanenv --param-variants 2 --corridor-variants 3
EOF
    exit 0
}

# ============================================================================
# RANDOM WAYPOINTS MODE
# ============================================================================

# Random waypoints defaults
RW_NUM_SCENARIOS=5
RW_CONFIG="RandomWaypoints5Host1Spoofer"
RW_HOSTS=5
RW_SPOOFERS=1
RW_WAYPOINTS=15
RW_GRID_SIZE=1000
RW_SPEED_RANGE="5-15"
RW_ALT_RANGE="30-100"
RW_SIM_DIR="$PROJ_DIR/simulations/random_waypoints"

usage_random_waypoints() {
    cat <<EOF
Usage: $0 random_waypoints [options]

Generate datasets using random waypoint trajectories.

Options:
    -n NUM        Number of scenario repetitions (default: $RW_NUM_SCENARIOS)
    -c CONFIG     OMNeT++ config name (default: $RW_CONFIG)
    -h HOSTS      Number of hosts (default: $RW_HOSTS)
    -s SPOOFERS   Number of spoofer hosts (default: $RW_SPOOFERS)
    -w WAYPOINTS  Waypoints per host (default: $RW_WAYPOINTS)
    -g SIZE       Grid size in meters (default: $RW_GRID_SIZE)
    -r RANGE      Speed range as 'min-max' (default: $RW_SPEED_RANGE)
    -a RANGE      Altitude range as 'min-max' (default: $RW_ALT_RANGE)
    -o DIR        Output directory (default: \$PROJ_DIR/datasets)
    --seed NUM    Starting seed (default: $SEED_START)
    --help        Show this help message

Examples:
    # Generate 10 scenarios with 5 hosts (1 spoofer)
    $0 random_waypoints -n 10 -h 5 -s 1

    # Generate 20 scenarios with 10 hosts (2 spoofers), custom grid
    $0 random_waypoints -n 20 -h 10 -s 2 -g 2000 -w 20

    # Generate dataset without spoofers
    $0 random_waypoints -n 5 -c RandomWaypoints5Host -h 5 -s 0
EOF
    exit 0
}

run_random_waypoints() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -n) RW_NUM_SCENARIOS="$2"; shift 2 ;;
            -c) RW_CONFIG="$2"; shift 2 ;;
            -h) RW_HOSTS="$2"; shift 2 ;;
            -s) RW_SPOOFERS="$2"; shift 2 ;;
            -w) RW_WAYPOINTS="$2"; shift 2 ;;
            -g) RW_GRID_SIZE="$2"; shift 2 ;;
            -r) RW_SPEED_RANGE="$2"; shift 2 ;;
            -a) RW_ALT_RANGE="$2"; shift 2 ;;
            -o) OUTPUT_DIR="$2"; shift 2 ;;
            --seed) SEED_START="$2"; shift 2 ;;
            --help) usage_random_waypoints ;;
            *) echo "Unknown option: $1"; usage_random_waypoints ;;
        esac
    done

    echo "=================================================="
    echo "Remote ID Dataset Generation Pipeline"
    echo "Mode: random_waypoints"
    echo "=================================================="
    echo "Scenarios:         $RW_NUM_SCENARIOS"
    echo "Config:            $RW_CONFIG"
    echo "Hosts:             $RW_HOSTS ($RW_SPOOFERS spoofers)"
    echo "Waypoints:         $RW_WAYPOINTS"
    echo "Grid size:         $RW_GRID_SIZE m"
    echo "Speed range:       $RW_SPEED_RANGE m/s"
    echo "Altitude range:    $RW_ALT_RANGE m"
    echo "Starting seed:     $SEED_START"
    echo "Output directory:  $OUTPUT_DIR"
    echo "=================================================="
    echo ""

    # Create output directory
    mkdir -p "$OUTPUT_DIR"

    # Check for required scripts
    WAYPOINTS_PY="$PROJ_DIR/src/utils/random_waypoints.py"
    if [ ! -f "$WAYPOINTS_PY" ]; then
        echo "Error: random_waypoints.py not found at $WAYPOINTS_PY"
        exit 1
    fi

    # Generate and run scenarios
    for i in $(seq 1 $RW_NUM_SCENARIOS); do
        SEED=$((SEED_START + i - 1))
        SCENARIO_NAME="${RW_CONFIG}_seed${SEED}"

        echo "----------------------------------------"
        echo "Scenario $i/$RW_NUM_SCENARIOS: $SCENARIO_NAME"
        echo "----------------------------------------"

        # Step 1: Generate waypoints XML
        WAYPOINTS_XML="${RW_SIM_DIR}/waypoints_${SCENARIO_NAME}.xml"
        echo "[1/3] Generating waypoints..."
        python3 "$WAYPOINTS_PY" \
            --out "$WAYPOINTS_XML" \
            --hosts "$RW_HOSTS" \
            --spoofer-hosts "$RW_SPOOFERS" \
            --waypoints "$RW_WAYPOINTS" \
            --grid-size "$RW_GRID_SIZE" \
            --speed "$RW_SPEED_RANGE" \
            --altitude "$RW_ALT_RANGE" \
            --seed "$SEED"

        # Step 2: Run OMNeT++ simulation
        echo "[2/3] Running simulation..."
        VEC_FILE="${RW_SIM_DIR}/results/${SCENARIO_NAME}-#0.vec"

        # Create a temporary ini file in the same directory as the base ini
        TMP_INI="${RW_SIM_DIR}/omnetpp_${SCENARIO_NAME}.ini"
        cat "${RW_SIM_DIR}/omnetpp.ini" > "$TMP_INI"

        # Use relative path to waypoints XML (relative to SIM_DIR)
        WAYPOINTS_REL=$(basename "$WAYPOINTS_XML")

        # Append scenario configuration
        cat >> "$TMP_INI" <<EOF

[Config ${SCENARIO_NAME}]
extends = $RW_CONFIG
sim-time-limit = 500s
repeat = 1
seed-set = \${runnumber}
**.vector-recording = true
**.scalar-recording = true
EOF

        # Add per-host turtleScript lines (XPath doesn't support variable substitution)
        for h in $(seq 0 $((RW_HOSTS - 1))); do
            echo "*.host[$h].mobility.turtleScript = xmldoc(\"$WAYPOINTS_REL\", \"movements/movement[@id='$h']\")" >> "$TMP_INI"
        done

        # Run simulation (use absolute paths for clarity)
        ${UAV_RID_BIN} -m \
            -u Cmdenv \
            -c "$SCENARIO_NAME" \
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
            -f "$TMP_INI" \
            --cmdenv-express-mode=true \
            --cmdenv-status-frequency=10s \
            --result-dir="results"

        rm "$TMP_INI"

        # Step 3: Convert .vec to CSV
        if [ -f "$VEC_FILE" ]; then
            echo "[3/3] Converting to CSV..."
            CSV_FILE="${OUTPUT_DIR}/${SCENARIO_NAME}.csv"
            python3 "$VEC2CSV" "$VEC_FILE" -o "$CSV_FILE"
            echo "Created: $CSV_FILE"
        else
            echo "Warning: Vector file not found: $VEC_FILE"
        fi

        echo ""
    done

    echo "=================================================="
    echo "Dataset generation complete!"
    echo "Output files: $OUTPUT_DIR/*.csv"
    echo "=================================================="
}

# ============================================================================
# URBANENV MODE
# ============================================================================

# Urbanenv defaults - parameter ranges
UE_GRID_SIZE="400"
UE_NUM_HOSTS="5"
UE_SIM_TIME="300"

# Spoofer/ghost settings (optional)
UE_ENABLE_SPOOFER=false

# Federate labeling
UE_NUM_FEDERATES=4
UE_MAX_FEDERATE_VARIANTS=8

# Corridor parameters
UE_NUM_EW="2"
UE_NUM_NS="2"
UE_CORRIDOR_WIDTH="20"
UE_CORRIDOR_SPACING="120"

# Building parameters
UE_NUM_BUILDINGS="20"
UE_BUILDING_HEIGHT="60-150"

# Trajectory parameters
UE_SPEED="5-15"
UE_ALTITUDE="30-100"

# Radio parameters
UE_TX_POWER="10-16"
UE_BEACON_INTERVAL="0.25-0.75"
UE_BEACON_OFFSET="0-0.1"
UE_BACKGROUND_NOISE="-90"

# Branching factors (all default to 1)
UE_PARAM_VARIANTS=1
UE_CORRIDOR_VARIANTS=1
UE_BUILDING_VARIANTS=1
UE_TRAJECTORY_VARIANTS=1
UE_SCENARIO_VARIANTS=1

usage_urbanenv() {
    cat <<EOF
Usage: $0 urbanenv [options]

Generate datasets using corridor-constrained urban environments.

Parameter Ranges (use 'min-max' for ranges, or single value):
    --grid-size RANGE         Grid size in meters (default: $UE_GRID_SIZE)
    --num-hosts RANGE         Number of hosts (default: $UE_NUM_HOSTS)
    --sim-time RANGE          Simulation time in seconds (default: $UE_SIM_TIME)

Corridor Parameters:
    --num-ew RANGE            Number of east-west corridors (default: $UE_NUM_EW)
    --num-ns RANGE            Number of north-south corridors (default: $UE_NUM_NS)
    --corridor-width RANGE    Corridor width in meters (default: $UE_CORRIDOR_WIDTH)
    --corridor-spacing RANGE  Corridor spacing in meters (default: $UE_CORRIDOR_SPACING)

Building Parameters:
    --num-buildings RANGE     Number of buildings, 0 for none (default: $UE_NUM_BUILDINGS)
    --building-height RANGE   Building height range (default: $UE_BUILDING_HEIGHT)

Trajectory Parameters:
    --speed RANGE             UAV speed in m/s (default: $UE_SPEED)
    --altitude RANGE          UAV altitude in m (default: $UE_ALTITUDE)

Radio Parameters:
    --tx-power RANGE          TX power in dBm (default: $UE_TX_POWER)
    --beacon-interval RANGE   Beacon interval in s (default: $UE_BEACON_INTERVAL)
    --beacon-offset RANGE     Beacon offset in s (default: $UE_BEACON_OFFSET)
    --background-noise dBm    Background noise power (default: $UE_BACKGROUND_NOISE)

Spoofer/Ghost Configuration:
    --enable-spoofer          Enable spoofer (randomly selects ghost and spoofer hosts)

Federate Labeling:
    --num-federates N         Number of federates for multilateration (default: $UE_NUM_FEDERATES)
    --max-federate-variants N Max federate combination variants (default: $UE_MAX_FEDERATE_VARIANTS)

Branching Factors:
    --param-variants N        Number of top-level parameter sets (default: $UE_PARAM_VARIANTS)
    --corridor-variants N     Corridor layouts per param set (default: $UE_CORRIDOR_VARIANTS)
    --building-variants N     Building layouts per corridor (default: $UE_BUILDING_VARIANTS)
    --trajectory-variants N   Trajectory sets per corridor (default: $UE_TRAJECTORY_VARIANTS)
    --scenario-variants N     Scenarios per building+trajectory combo (default: $UE_SCENARIO_VARIANTS)

General Options:
    --seed NUM                Starting seed (default: $SEED_START)
    -o DIR                    Output directory (default: \$PROJ_DIR/datasets)
    --help                    Show this help message

Output Structure:
    datasets/urbanenv/
    └── grid{G}_hosts{H}_sim{T}/
        └── ew{E}_ns{N}_w{W}_sp{S}/
            ├── corridors.ndjson
            ├── buildings/
            │   └── n{B}_h{H}_seed{S}.xml
            ├── trajectories/
            │   └── spd{V}_alt{A}_seed{S}.xml
            └── scenarios/
                └── bldg_...__traj_...__tx{P}_bint{I}_seed{S}/
                    ├── omnetpp.ini
                    └── output.csv

Examples:
    # Simple: one scenario
    $0 urbanenv

    # Multiple scenarios with same environment
    $0 urbanenv --scenario-variants 10

    # Vary everything
    $0 urbanenv --param-variants 2 --corridor-variants 3 \\
                --building-variants 2 --trajectory-variants 2 \\
                --scenario-variants 5

    # Large grid, more hosts, no buildings
    $0 urbanenv --grid-size 800 --num-hosts 10 --num-buildings 0

    # With spoofer (randomly selected ghost and spoofer hosts)
    $0 urbanenv --num-hosts 6 --enable-spoofer
EOF
    exit 0
}

# Helper: sample a value from a range string like "10-20" or "15"
sample_range() {
    local range="$1"
    local seed="$2"

    if [[ "$range" == *-* ]]; then
        local min="${range%-*}"
        local max="${range#*-}"
        # Use awk for floating point random with seed
        awk -v min="$min" -v max="$max" -v seed="$seed" \
            'BEGIN { srand(seed); printf "%.2f", min + rand() * (max - min) }'
    else
        echo "$range"
    fi
}

# Helper: sample an integer from a range string
sample_range_int() {
    local range="$1"
    local seed="$2"

    if [[ "$range" == *-* ]]; then
        local min="${range%-*}"
        local max="${range#*-}"
        awk -v min="$min" -v max="$max" -v seed="$seed" \
            'BEGIN { srand(seed); printf "%d", int(min + rand() * (max - min + 1)) }'
    else
        echo "$range"
    fi
}

run_urbanenv() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --grid-size) UE_GRID_SIZE="$2"; shift 2 ;;
            --num-hosts) UE_NUM_HOSTS="$2"; shift 2 ;;
            --sim-time) UE_SIM_TIME="$2"; shift 2 ;;
            --num-ew) UE_NUM_EW="$2"; shift 2 ;;
            --num-ns) UE_NUM_NS="$2"; shift 2 ;;
            --corridor-width) UE_CORRIDOR_WIDTH="$2"; shift 2 ;;
            --corridor-spacing) UE_CORRIDOR_SPACING="$2"; shift 2 ;;
            --num-buildings) UE_NUM_BUILDINGS="$2"; shift 2 ;;
            --building-height) UE_BUILDING_HEIGHT="$2"; shift 2 ;;
            --speed) UE_SPEED="$2"; shift 2 ;;
            --altitude) UE_ALTITUDE="$2"; shift 2 ;;
            --tx-power) UE_TX_POWER="$2"; shift 2 ;;
            --beacon-interval) UE_BEACON_INTERVAL="$2"; shift 2 ;;
            --beacon-offset) UE_BEACON_OFFSET="$2"; shift 2 ;;
            --background-noise) UE_BACKGROUND_NOISE="$2"; shift 2 ;;
            --enable-spoofer) UE_ENABLE_SPOOFER=true; shift ;;
            --num-federates) UE_NUM_FEDERATES="$2"; shift 2 ;;
            --max-federate-variants) UE_MAX_FEDERATE_VARIANTS="$2"; shift 2 ;;
            --param-variants) UE_PARAM_VARIANTS="$2"; shift 2 ;;
            --corridor-variants) UE_CORRIDOR_VARIANTS="$2"; shift 2 ;;
            --building-variants) UE_BUILDING_VARIANTS="$2"; shift 2 ;;
            --trajectory-variants) UE_TRAJECTORY_VARIANTS="$2"; shift 2 ;;
            --scenario-variants) UE_SCENARIO_VARIANTS="$2"; shift 2 ;;
            --seed) SEED_START="$2"; shift 2 ;;
            -o) OUTPUT_DIR="$2"; shift 2 ;;
            --help) usage_urbanenv ;;
            *) echo "Unknown option: $1"; usage_urbanenv ;;
        esac
    done

    # Calculate total scenarios
    TOTAL_SCENARIOS=$((UE_PARAM_VARIANTS * UE_CORRIDOR_VARIANTS * UE_BUILDING_VARIANTS * UE_TRAJECTORY_VARIANTS * UE_SCENARIO_VARIANTS))

    echo "=================================================="
    echo "Remote ID Dataset Generation Pipeline"
    echo "Mode: urbanenv"
    echo "=================================================="
    echo "Parameter ranges:"
    echo "  Grid size:         $UE_GRID_SIZE m"
    echo "  Num hosts:         $UE_NUM_HOSTS"
    echo "  Sim time:          $UE_SIM_TIME s"
    echo "Corridor parameters:"
    echo "  EW corridors:      $UE_NUM_EW"
    echo "  NS corridors:      $UE_NUM_NS"
    echo "  Width:             $UE_CORRIDOR_WIDTH m"
    echo "  Spacing:           $UE_CORRIDOR_SPACING m"
    echo "Building parameters:"
    echo "  Num buildings:     $UE_NUM_BUILDINGS"
    echo "  Height:            $UE_BUILDING_HEIGHT m"
    echo "Trajectory parameters:"
    echo "  Speed:             $UE_SPEED m/s"
    echo "  Altitude:          $UE_ALTITUDE m"
    echo "Radio parameters:"
    echo "  TX power:          $UE_TX_POWER dBm"
    echo "  Beacon interval:   $UE_BEACON_INTERVAL s"
    echo "  Beacon offset:     $UE_BEACON_OFFSET s"
    echo "  Background noise:  $UE_BACKGROUND_NOISE dBm"
    echo "Spoofer:             $UE_ENABLE_SPOOFER"
    echo "Federate labeling:"
    echo "  Num federates:     $UE_NUM_FEDERATES"
    echo "  Max variants:      $UE_MAX_FEDERATE_VARIANTS"
    echo "Branching factors:"
    echo "  Param variants:    $UE_PARAM_VARIANTS"
    echo "  Corridor variants: $UE_CORRIDOR_VARIANTS"
    echo "  Building variants: $UE_BUILDING_VARIANTS"
    echo "  Trajectory variants: $UE_TRAJECTORY_VARIANTS"
    echo "  Scenario variants: $UE_SCENARIO_VARIANTS"
    echo "Total scenarios:     $TOTAL_SCENARIOS"
    echo "Starting seed:       $SEED_START"
    echo "Output directory:    $OUTPUT_DIR"
    echo "=================================================="
    echo ""

    # Create base output directory
    URBANENV_DIR="$OUTPUT_DIR/urbanenv"
    mkdir -p "$URBANENV_DIR"

    # Paths to urbanenv generation tools
    GEN_CORRIDORS="$SCRIPT_DIR/urbanenv/generate_corridors.py"
    GEN_BUILDINGS="$SCRIPT_DIR/urbanenv/generate_buildings.py"
    GEN_TRAJECTORIES="$SCRIPT_DIR/urbanenv/generate_trajectories.py"
    GEN_SCENARIO="$SCRIPT_DIR/urbanenv/generate_scenario.py"

    # Check for required tools
    for tool in "$GEN_CORRIDORS" "$GEN_BUILDINGS" "$GEN_TRAJECTORIES" "$GEN_SCENARIO"; do
        if [ ! -f "$tool" ]; then
            echo "Error: Required tool not found: $tool"
            exit 1
        fi
    done

    # Counter for progress
    SCENARIO_COUNT=0

    # Seed offset formula:
    # param_seed = SEED_START + p * 10000
    # corridor_seed = param_seed + c * 1000
    # building_seed = corridor_seed + b * 100
    # trajectory_seed = corridor_seed + t * 100 (parallel to buildings, offset by 50)
    # scenario_seed = sequential counter

    SCENARIO_SEED_COUNTER=$SEED_START

    # Loop through parameter variants
    for p in $(seq 0 $((UE_PARAM_VARIANTS - 1))); do
        PARAM_SEED=$((SEED_START + p * 10000))

        # Sample top-level parameters
        GRID=$(sample_range_int "$UE_GRID_SIZE" $PARAM_SEED)
        HOSTS=$(sample_range_int "$UE_NUM_HOSTS" $((PARAM_SEED + 1)))
        SIM_TIME=$(sample_range_int "$UE_SIM_TIME" $((PARAM_SEED + 2)))

        PARAM_DIR="grid${GRID}_hosts${HOSTS}_sim${SIM_TIME}"
        echo "========================================"
        echo "Parameter set $((p + 1))/$UE_PARAM_VARIANTS: $PARAM_DIR"
        echo "========================================"

        # Loop through corridor variants
        for c in $(seq 0 $((UE_CORRIDOR_VARIANTS - 1))); do
            CORRIDOR_SEED=$((PARAM_SEED + c * 1000))

            # Sample corridor parameters
            NUM_EW=$(sample_range_int "$UE_NUM_EW" $CORRIDOR_SEED)
            NUM_NS=$(sample_range_int "$UE_NUM_NS" $((CORRIDOR_SEED + 1)))
            CORR_WIDTH=$(sample_range_int "$UE_CORRIDOR_WIDTH" $((CORRIDOR_SEED + 2)))
            CORR_SPACING=$(sample_range_int "$UE_CORRIDOR_SPACING" $((CORRIDOR_SEED + 3)))

            CORRIDOR_DIR="ew${NUM_EW}_ns${NUM_NS}_w${CORR_WIDTH}_sp${CORR_SPACING}"
            CORRIDOR_PATH="$URBANENV_DIR/$PARAM_DIR/$CORRIDOR_DIR"

            echo "  ----------------------------------------"
            echo "  Corridor $((c + 1))/$UE_CORRIDOR_VARIANTS: $CORRIDOR_DIR"
            echo "  ----------------------------------------"

            # Create corridor directory structure
            mkdir -p "$CORRIDOR_PATH/buildings"
            mkdir -p "$CORRIDOR_PATH/trajectories"
            mkdir -p "$CORRIDOR_PATH/scenarios"

            # Generate corridors (once per corridor variant)
            CORRIDORS_FILE="$CORRIDOR_PATH/corridors.ndjson"
            if [ ! -f "$CORRIDORS_FILE" ]; then
                echo "  [corridors] Generating..."
                python3 "$GEN_CORRIDORS" \
                    --grid-size "$GRID" \
                    --num-ew "$NUM_EW" \
                    --num-ns "$NUM_NS" \
                    --width "$CORR_WIDTH" \
                    --spacing "$CORR_SPACING" \
                    --seed "$CORRIDOR_SEED" \
                    -o "$CORRIDORS_FILE"
            fi

            # Generate building variants
            declare -a BUILDING_FILES=()
            for b in $(seq 0 $((UE_BUILDING_VARIANTS - 1))); do
                BUILDING_SEED=$((CORRIDOR_SEED + b * 100))

                # Sample building parameters
                NUM_BLDG=$(sample_range_int "$UE_NUM_BUILDINGS" $BUILDING_SEED)
                BLDG_HEIGHT="$UE_BUILDING_HEIGHT"  # Keep as range for generator

                if [ "$NUM_BLDG" -eq 0 ]; then
                    BLDG_NAME="none"
                    BUILDING_FILES+=("")
                    echo "  [buildings $((b + 1))/$UE_BUILDING_VARIANTS] No buildings"
                else
                    BLDG_NAME="n${NUM_BLDG}_h${BLDG_HEIGHT}_seed${BUILDING_SEED}"
                    BLDG_FILE="$CORRIDOR_PATH/buildings/${BLDG_NAME}.xml"
                    BUILDING_FILES+=("$BLDG_FILE")

                    if [ ! -f "$BLDG_FILE" ]; then
                        echo "  [buildings $((b + 1))/$UE_BUILDING_VARIANTS] Generating $BLDG_NAME..."
                        python3 "$GEN_BUILDINGS" \
                            -c "$CORRIDORS_FILE" \
                            --num-buildings "$NUM_BLDG" \
                            --grid-size "$GRID" \
                            --height "$BLDG_HEIGHT" \
                            --seed "$BUILDING_SEED" \
                            --format xml \
                            -o "$BLDG_FILE"
                    fi
                fi
            done

            # Generate trajectory variants
            declare -a TRAJECTORY_FILES=()
            for t in $(seq 0 $((UE_TRAJECTORY_VARIANTS - 1))); do
                TRAJECTORY_SEED=$((CORRIDOR_SEED + 50 + t * 100))

                # Sample trajectory parameters
                TRAJ_SPEED="$UE_SPEED"  # Keep as range for generator
                TRAJ_ALT="$UE_ALTITUDE"

                TRAJ_NAME="spd${TRAJ_SPEED}_alt${TRAJ_ALT}_seed${TRAJECTORY_SEED}"
                TRAJ_FILE="$CORRIDOR_PATH/trajectories/${TRAJ_NAME}.xml"
                TRAJECTORY_FILES+=("$TRAJ_FILE")

                if [ ! -f "$TRAJ_FILE" ]; then
                    echo "  [trajectories $((t + 1))/$UE_TRAJECTORY_VARIANTS] Generating $TRAJ_NAME..."
                    python3 "$GEN_TRAJECTORIES" \
                        -c "$CORRIDORS_FILE" \
                        --hosts "$HOSTS" \
                        --grid-size "$GRID" \
                        --min-duration "$SIM_TIME" \
                        --speed "$TRAJ_SPEED" \
                        --altitude "$TRAJ_ALT" \
                        --seed "$TRAJECTORY_SEED" \
                        -o "$TRAJ_FILE"
                fi
            done

            # Generate scenarios: cross-product of buildings × trajectories × scenario variants
            for b in $(seq 0 $((UE_BUILDING_VARIANTS - 1))); do
                BLDG_FILE="${BUILDING_FILES[$b]}"

                # Derive building name for directory
                if [ -z "$BLDG_FILE" ]; then
                    BLDG_PART="bldg_none"
                else
                    BLDG_BASENAME=$(basename "$BLDG_FILE" .xml)
                    BLDG_PART="bldg_${BLDG_BASENAME}"
                fi

                for t in $(seq 0 $((UE_TRAJECTORY_VARIANTS - 1))); do
                    TRAJ_FILE="${TRAJECTORY_FILES[$t]}"
                    TRAJ_BASENAME=$(basename "$TRAJ_FILE" .xml)
                    TRAJ_PART="traj_${TRAJ_BASENAME}"

                    for s in $(seq 0 $((UE_SCENARIO_VARIANTS - 1))); do
                        SCENARIO_SEED=$SCENARIO_SEED_COUNTER
                        SCENARIO_SEED_COUNTER=$((SCENARIO_SEED_COUNTER + 1))
                        SCENARIO_COUNT=$((SCENARIO_COUNT + 1))

                        # Use original ranges - generate_scenario.py will sample per-host
                        # Directory name uses seed since per-host values vary
                        SCENARIO_NAME="${BLDG_PART}__${TRAJ_PART}__seed${SCENARIO_SEED}"
                        SCENARIO_PATH="$CORRIDOR_PATH/scenarios/$SCENARIO_NAME"

                        echo "    [$SCENARIO_COUNT/$TOTAL_SCENARIOS] $SCENARIO_NAME"

                        mkdir -p "$SCENARIO_PATH"

                        # Generate scenario ini
                        INI_FILE="$SCENARIO_PATH/omnetpp.ini"
                        if [ ! -f "$INI_FILE" ]; then
                            SCENARIO_ARGS=(
                                -t "$TRAJ_FILE"
                                --tx-power "$UE_TX_POWER"
                                --beacon-interval "$UE_BEACON_INTERVAL"
                                --beacon-offset "$UE_BEACON_OFFSET"
                                --background-noise "$UE_BACKGROUND_NOISE"
                                --sim-time-limit "$SIM_TIME"
                                --config-name "Scenario"
                                --seed "$SCENARIO_SEED"
                                -o "$INI_FILE"
                            )
                            if [ -n "$BLDG_FILE" ]; then
                                SCENARIO_ARGS+=(-b "$BLDG_FILE")
                            fi
                            if [ "$UE_ENABLE_SPOOFER" = true ]; then
                                SCENARIO_ARGS+=(--enable-spoofer)
                            fi
                            # Capture output to extract SPOOFER_HOST
                            SCENARIO_OUTPUT=$(python3 "$GEN_SCENARIO" "${SCENARIO_ARGS[@]}")
                            echo "$SCENARIO_OUTPUT"
                            # Extract spoofer host from output (format: SPOOFER_HOST=N)
                            SPOOFER_HOST=$(echo "$SCENARIO_OUTPUT" | grep -oP 'SPOOFER_HOST=\K\d+' || true)
                        else
                            # INI already exists, extract spoofer host from it
                            SPOOFER_HOST=$(grep -oP 'spoofer_host": \K\d+' "$INI_FILE" || true)
                        fi

                        # Determine which configs to run
                        # ScenarioOpenSpace is always present
                        # ScenarioWithBuildings is only present if buildings were specified
                        CONFIGS_TO_RUN=("ScenarioOpenSpace")
                        if [ -n "$BLDG_FILE" ]; then
                            CONFIGS_TO_RUN+=("ScenarioWithBuildings")
                        fi

                        RESULTS_DIR="$SCENARIO_PATH/results"
                        mkdir -p "$RESULTS_DIR"

                        # Compute hash for CSV naming based on relative path from urbanenv/
                        # Path: grid400_hosts3_sim30/ew2_ns2_w20_sp120/scenarios/bldg_...__seed42
                        SCENARIO_REL_PATH="${PARAM_DIR}/${CORRIDOR_DIR}/scenarios/${SCENARIO_NAME}"
                        SCENARIO_HASH=$(echo -n "$SCENARIO_REL_PATH" | md5sum | cut -c1-8)

                        # Run each config
                        for CONFIG_NAME in "${CONFIGS_TO_RUN[@]}"; do
                            echo "      Running $CONFIG_NAME..."

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
                            # -o suffix for OpenSpace, -b suffix for WithBuildings
                            VEC_FILE="$RESULTS_DIR/${CONFIG_NAME}-#0.vec"
                            if [ -f "$VEC_FILE" ]; then
                                if [ "$CONFIG_NAME" = "ScenarioOpenSpace" ]; then
                                    CSV_SUFFIX="-o"
                                else
                                    CSV_SUFFIX="-b"
                                fi
                                CSV_FILE="$SCENARIO_PATH/${SCENARIO_HASH}${CSV_SUFFIX}.csv"
                                echo "      Converting to CSV..."
                                python3 "$VEC2CSV" "$VEC_FILE" -o "$CSV_FILE"

                                # Add host_type column
                                if [ -n "$SPOOFER_HOST" ]; then
                                    python3 "$ADD_HOST_TYPE" "$CSV_FILE" --in-place --spoofer-hosts "$SPOOFER_HOST"
                                else
                                    python3 "$ADD_HOST_TYPE" "$CSV_FILE" --in-place
                                fi

                                # Generate federate variants (base CSV is kept)
                                echo "      Generating federate variants..."
                                python3 "$LABEL_FEDERATES" "$CSV_FILE" \
                                    --num-federates "$UE_NUM_FEDERATES" \
                                    --max-variants "$UE_MAX_FEDERATE_VARIANTS" \
                                    --seed "$SCENARIO_SEED"
                                echo "      Created: $CSV_FILE (+ federate variants)"
                            else
                                echo "      Warning: Vector file not found: $VEC_FILE"
                            fi
                        done

                        echo ""
                    done
                done
            done
        done
    done

    echo "=================================================="
    echo "Dataset generation complete!"
    echo "Total scenarios: $SCENARIO_COUNT"
    echo "Output directory: $URBANENV_DIR"
    echo "=================================================="
}

# ============================================================================
# MAIN
# ============================================================================

# Check for required environment variables
if [ -z "$INET_ROOT" ]; then
    echo "Error: INET_ROOT not set. Please source setenv first."
    echo "  cd $PROJ_DIR && . container/setenv"
    exit 1
fi

# Check for required tools
if ! command -v opp_scavetool &> /dev/null; then
    echo "Error: opp_scavetool not found. Please source setenv first."
    exit 1
fi

# Check for container binary (out-of-tree build location)
UAV_RID_BIN="$BASE_DIR/container-build/out/clang-release/uav_rid"
if [ ! -f "$UAV_RID_BIN" ]; then
    echo "Error: Container binary not found at $UAV_RID_BIN"
    echo ""
    echo "To build: cd $PROJ_DIR && . container/setenv && ./container/build.sh"
    exit 1
fi

# Check for vec2csv
VEC2CSV="$SCRIPT_DIR/vec2csv.py"
if [ ! -f "$VEC2CSV" ]; then
    echo "Error: vec2csv.py not found at $VEC2CSV"
    exit 1
fi

# Check for add_host_type
ADD_HOST_TYPE="$SCRIPT_DIR/add_host_type.py"
if [ ! -f "$ADD_HOST_TYPE" ]; then
    echo "Error: add_host_type.py not found at $ADD_HOST_TYPE"
    exit 1
fi

# Check for label_federates
LABEL_FEDERATES="$SCRIPT_DIR/label_federates.py"
if [ ! -f "$LABEL_FEDERATES" ]; then
    echo "Error: label_federates.py not found at $LABEL_FEDERATES"
    exit 1
fi

# Parse mode
if [ $# -eq 0 ]; then
    usage_main
fi

MODE="$1"
shift

case "$MODE" in
    random_waypoints)
        run_random_waypoints "$@"
        ;;
    urbanenv)
        run_urbanenv "$@"
        ;;
    --help|-h)
        usage_main
        ;;
    *)
        echo "Unknown mode: $MODE"
        echo ""
        usage_main
        ;;
esac
