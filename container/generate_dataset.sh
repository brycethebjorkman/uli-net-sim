#!/usr/bin/env bash
#
# generate_dataset.sh
#
# End-to-end pipeline for generating Remote ID spoofing detection datasets.
# Generates random waypoints, runs OMNeT++ simulations, and converts results to CSV.
#
# USAGE:
#   This script must be run from /usr/uli-net-sim with setenv sourced:
#     cd /usr/uli-net-sim && . setenv
#     ./generate_dataset.sh [options]
#

set -e

# Default parameters
NUM_SCENARIOS=5
CONFIG="RandomWaypoints5Host1Spoofer"
HOSTS=5
SPOOFERS=1
WAYPOINTS=15
GRID_SIZE=1000
SPEED_RANGE="5-15"
ALT_RANGE="30-100"
SIM_DIR="uav_rid/simulations/random_waypoints"
OUTPUT_DIR="datasets"
SEED_START=42

usage() {
    cat <<EOF
Usage: $0 [options]

Generate datasets for Remote ID spoofing detection analysis.

IMPORTANT: Must be run from /usr/uli-net-sim with setenv sourced:
  cd /usr/uli-net-sim && . setenv
  ./generate_dataset.sh [options]

Options:
    -n NUM        Number of scenario repetitions (default: $NUM_SCENARIOS)
    -c CONFIG     OMNeT++ config name (default: $CONFIG)
    -h HOSTS      Number of hosts (default: $HOSTS)
    -s SPOOFERS   Number of spoofer hosts (default: $SPOOFERS)
    -w WAYPOINTS  Waypoints per host (default: $WAYPOINTS)
    -g SIZE       Grid size in meters (default: $GRID_SIZE)
    -r RANGE      Speed range as 'min-max' (default: $SPEED_RANGE)
    -a RANGE      Altitude range as 'min-max' (default: $ALT_RANGE)
    -o DIR        Output directory (default: $OUTPUT_DIR)
    --seed NUM    Starting seed (default: $SEED_START)
    --help        Show this help message

Examples:
    # Generate 10 scenarios with 5 hosts (1 spoofer)
    $0 -n 10 -h 5 -s 1

    # Generate 20 scenarios with 10 hosts (2 spoofers), custom grid
    $0 -n 20 -h 10 -s 2 -g 2000 -w 20

    # Generate dataset without spoofers
    $0 -n 5 -c RandomWaypoints5Host -h 5 -s 0
EOF
    exit 0
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -n) NUM_SCENARIOS="$2"; shift 2 ;;
        -c) CONFIG="$2"; shift 2 ;;
        -h) HOSTS="$2"; shift 2 ;;
        -s) SPOOFERS="$2"; shift 2 ;;
        -w) WAYPOINTS="$2"; shift 2 ;;
        -g) GRID_SIZE="$2"; shift 2 ;;
        -r) SPEED_RANGE="$2"; shift 2 ;;
        -a) ALT_RANGE="$2"; shift 2 ;;
        -o) OUTPUT_DIR="$2"; shift 2 ;;
        --seed) SEED_START="$2"; shift 2 ;;
        --help) usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

echo "=================================================="
echo "Remote ID Dataset Generation Pipeline"
echo "=================================================="
echo "Scenarios:         $NUM_SCENARIOS"
echo "Config:            $CONFIG"
echo "Hosts:             $HOSTS ($SPOOFERS spoofers)"
echo "Waypoints:         $WAYPOINTS"
echo "Grid size:         $GRID_SIZE m"
echo "Speed range:       $SPEED_RANGE m/s"
echo "Altitude range:    $ALT_RANGE m"
echo "Starting seed:     $SEED_START"
echo "Output directory:  $OUTPUT_DIR"
echo "=================================================="
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Check for required environment variables
if [ -z "$INET_ROOT" ]; then
    echo "Error: INET_ROOT not set. Please source setenv first."
    echo "  cd /usr/uli-net-sim && . setenv"
    exit 1
fi

# Check for required tools
if ! command -v opp_scavetool &> /dev/null; then
    echo "Error: opp_scavetool not found. Please source setenv first."
    exit 1
fi

# Check for container binary (has rpath, doesn't need LD_LIBRARY_PATH)
UAV_RID_BIN="uav_rid/out/clang-release/uav_rid"
if [ ! -f "$UAV_RID_BIN" ]; then
    echo "Error: Container binary not found at $UAV_RID_BIN"
    echo "This script must be run from /usr/uli-net-sim"
    exit 1
fi

# Check for required scripts
if [ ! -f "vec2csv.py" ]; then
    echo "Error: vec2csv.py not found at vec2csv.py"
    exit 1
fi

if [ ! -f "uav_rid/src/utils/random_waypoints.py" ]; then
    echo "Error: random_waypoints.py not found at uav_rid/src/utils/random_waypoints.py"
    exit 1
fi

# Generate and run scenarios
for i in $(seq 1 $NUM_SCENARIOS); do
    SEED=$((SEED_START + i - 1))
    SCENARIO_NAME="${CONFIG}_seed${SEED}"

    echo "----------------------------------------"
    echo "Scenario $i/$NUM_SCENARIOS: $SCENARIO_NAME"
    echo "----------------------------------------"

    # Step 1: Generate waypoints XML
    WAYPOINTS_XML="${SIM_DIR}/waypoints_${SCENARIO_NAME}.xml"
    echo "[1/3] Generating waypoints..."
    python3 uav_rid/src/utils/random_waypoints.py \
        --out "$WAYPOINTS_XML" \
        --hosts "$HOSTS" \
        --spoofer-hosts "$SPOOFERS" \
        --waypoints "$WAYPOINTS" \
        --grid-size "$GRID_SIZE" \
        --speed "$SPEED_RANGE" \
        --altitude "$ALT_RANGE" \
        --seed "$SEED"

    # Step 2: Run OMNeT++ simulation
    echo "[2/3] Running simulation..."
    VEC_FILE="${SIM_DIR}/results/${SCENARIO_NAME}-#0.vec"

    # Create a temporary ini file in the same directory as the base ini
    TMP_INI="${SIM_DIR}/omnetpp_${SCENARIO_NAME}.ini"
    cat "${SIM_DIR}/omnetpp.ini" > "$TMP_INI"

    # Use relative path to waypoints XML (relative to SIM_DIR)
    WAYPOINTS_REL=$(basename "$WAYPOINTS_XML")

    # Append scenario configuration
    cat >> "$TMP_INI" <<EOF

[Config ${SCENARIO_NAME}]
extends = $CONFIG
*.host[*].mobility.turtleScript = xmldoc("$WAYPOINTS_REL")
sim-time-limit = 500s
repeat = 1
seed-set = \${runnumber}
**.vector-recording = true
**.scalar-recording = true
EOF

    # Run simulation
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
        -n "./uav_rid/simulations" \
        -n "./uav_rid/src" \
        -f "$TMP_INI" \
        --cmdenv-express-mode=true \
        --cmdenv-status-frequency=10s \
        --result-dir="results"

    rm "$TMP_INI"

    # Step 3: Convert .vec to CSV
    if [ -f "$VEC_FILE" ]; then
        echo "[3/3] Converting to CSV..."
        CSV_FILE="${OUTPUT_DIR}/${SCENARIO_NAME}.csv"
        python3 vec2csv.py "$VEC_FILE" -o "$CSV_FILE"
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
