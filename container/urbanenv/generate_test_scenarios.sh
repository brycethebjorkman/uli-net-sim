#!/usr/bin/env bash
#
# generate_test_scenarios.sh
#
# Generate test scenarios for manual validation of urbanenv pipeline.
# Outputs all artifacts to simulations/urbanenv_testing/ with fixed seeds
# for deterministic, reproducible results.
#
# Usage:
#   cd /usr/uli-net-sim/uav_rid
#   ./container/urbanenv/generate_test_scenarios.sh
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
OUTPUT_DIR="$PROJ_DIR/simulations/urbanenv_testing"

echo "=============================================="
echo "Urban Environment Test Scenario Generator"
echo "=============================================="
echo "Output directory: $OUTPUT_DIR"
echo ""

mkdir -p "$OUTPUT_DIR"
cd "$SCRIPT_DIR"

# ------------------------------------------------------------------------------
# Scenario 1: Simple 2x2 grid, 5 hosts, no buildings
# ------------------------------------------------------------------------------
echo "--- Scenario 1: Simple 2x2 Grid (no buildings) ---"

python3 generate_corridors.py \
    --num-ew 2 --num-ns 2 \
    --width 20 --spacing 120 \
    --seed 1 \
    -o "$OUTPUT_DIR/scenario1_corridors.ndjson"

python3 generate_trajectories.py \
    -c "$OUTPUT_DIR/scenario1_corridors.ndjson" \
    --hosts 5 \
    --min-duration 300 \
    --speed 5-15 \
    --altitude 30-100 \
    --waypoint-interval 30-60 \
    --seed 1 \
    -o "$OUTPUT_DIR/scenario1_waypoints.xml"

mkdir -p "$OUTPUT_DIR/scenario1"
python3 generate_scenario.py \
    -t "$OUTPUT_DIR/scenario1_waypoints.xml" \
    --tx-power 10-16 \
    --beacon-interval 0.25-0.75 \
    --beacon-offset 0-0.1 \
    --sim-time-limit 300 \
    --config-name Scenario1_Simple2x2 \
    --seed 1 \
    -o "$OUTPUT_DIR/scenario1/omnetpp.ini"

echo ""

# ------------------------------------------------------------------------------
# Scenario 2: Dense 3x3 grid with buildings, 5 hosts
# ------------------------------------------------------------------------------
echo "--- Scenario 2: Dense 3x3 Grid with Buildings ---"

python3 generate_corridors.py \
    --num-ew 3 --num-ns 3 \
    --width 15 --spacing 100 \
    --seed 2 \
    -o "$OUTPUT_DIR/scenario2_corridors.ndjson"

python3 generate_buildings.py \
    -c "$OUTPUT_DIR/scenario2_corridors.ndjson" \
    -n 25 \
    --width-x 20-35 --width-y 20-35 \
    --height 60-150 \
    --seed 2 \
    -o "$OUTPUT_DIR/scenario2_buildings.ndjson"

python3 generate_buildings.py \
    -c "$OUTPUT_DIR/scenario2_corridors.ndjson" \
    -n 25 \
    --width-x 20-35 --width-y 20-35 \
    --height 60-150 \
    --seed 2 \
    --format xml \
    -o "$OUTPUT_DIR/scenario2_buildings.xml"

python3 generate_trajectories.py \
    -c "$OUTPUT_DIR/scenario2_corridors.ndjson" \
    --hosts 5 \
    --min-duration 300 \
    --speed 5-15 \
    --altitude 40-80 \
    --waypoint-interval 30-60 \
    --seed 2 \
    -o "$OUTPUT_DIR/scenario2_waypoints.xml"

mkdir -p "$OUTPUT_DIR/scenario2"
python3 generate_scenario.py \
    -t "$OUTPUT_DIR/scenario2_waypoints.xml" \
    -b "$OUTPUT_DIR/scenario2_buildings.xml" \
    --tx-power 10-16 \
    --beacon-interval 0.25-0.75 \
    --beacon-offset 0-0.1 \
    --sim-time-limit 300 \
    --config-name Scenario2_Dense3x3WithBuildings \
    --seed 2 \
    -o "$OUTPUT_DIR/scenario2/omnetpp.ini"

# Also generate a no-buildings variant for comparison
mkdir -p "$OUTPUT_DIR/scenario2_nobuildings"
python3 generate_scenario.py \
    -t "$OUTPUT_DIR/scenario2_waypoints.xml" \
    --tx-power 10-16 \
    --beacon-interval 0.25-0.75 \
    --beacon-offset 0-0.1 \
    --sim-time-limit 300 \
    --config-name Scenario2_NoBuildingsComparison \
    --seed 2 \
    -o "$OUTPUT_DIR/scenario2_nobuildings/omnetpp.ini"

echo ""

# ------------------------------------------------------------------------------
# Scenario 3: Wide corridors, low buildings, 3 hosts
# ------------------------------------------------------------------------------
echo "--- Scenario 3: Wide Corridors, Low Buildings ---"

python3 generate_corridors.py \
    --num-ew 2 --num-ns 2 \
    --width 30 --spacing 150 \
    --seed 3 \
    -o "$OUTPUT_DIR/scenario3_corridors.ndjson"

python3 generate_buildings.py \
    -c "$OUTPUT_DIR/scenario3_corridors.ndjson" \
    -n 15 \
    --width-x 40-60 --width-y 40-60 \
    --height 30-60 \
    --seed 3 \
    --format xml \
    -o "$OUTPUT_DIR/scenario3_buildings.xml"

python3 generate_trajectories.py \
    -c "$OUTPUT_DIR/scenario3_corridors.ndjson" \
    --hosts 3 \
    --min-duration 300 \
    --speed 8-12 \
    --altitude 50-100 \
    --waypoint-interval 40-80 \
    --seed 3 \
    -o "$OUTPUT_DIR/scenario3_waypoints.xml"

mkdir -p "$OUTPUT_DIR/scenario3"
python3 generate_scenario.py \
    -t "$OUTPUT_DIR/scenario3_waypoints.xml" \
    -b "$OUTPUT_DIR/scenario3_buildings.xml" \
    --tx-power 10-16 \
    --beacon-interval 0.25-0.75 \
    --beacon-offset 0-0.1 \
    --sim-time-limit 300 \
    --config-name Scenario3_WideCorridorsLowBuildings \
    --seed 3 \
    -o "$OUTPUT_DIR/scenario3/omnetpp.ini"

echo ""

# ------------------------------------------------------------------------------
# Scenario 4: Skyscraper district, narrow corridors, 4 hosts
# ------------------------------------------------------------------------------
echo "--- Scenario 4: Skyscraper District ---"

python3 generate_corridors.py \
    --num-ew 3 --num-ns 3 \
    --width 18 --spacing 90 \
    --seed 4 \
    -o "$OUTPUT_DIR/scenario4_corridors.ndjson"

python3 generate_buildings.py \
    -c "$OUTPUT_DIR/scenario4_corridors.ndjson" \
    -n 20 \
    --width-x 25-40 --width-y 25-40 \
    --height 120-250 \
    --seed 4 \
    --format xml \
    -o "$OUTPUT_DIR/scenario4_buildings.xml"

python3 generate_trajectories.py \
    -c "$OUTPUT_DIR/scenario4_corridors.ndjson" \
    --hosts 4 \
    --min-duration 300 \
    --speed 6-10 \
    --altitude 80-150 \
    --waypoint-interval 25-50 \
    --seed 4 \
    -o "$OUTPUT_DIR/scenario4_waypoints.xml"

mkdir -p "$OUTPUT_DIR/scenario4"
python3 generate_scenario.py \
    -t "$OUTPUT_DIR/scenario4_waypoints.xml" \
    -b "$OUTPUT_DIR/scenario4_buildings.xml" \
    --tx-power 10-16 \
    --beacon-interval 0.25-0.75 \
    --beacon-offset 0-0.1 \
    --sim-time-limit 300 \
    --config-name Scenario4_SkyscraperDistrict \
    --seed 4 \
    -o "$OUTPUT_DIR/scenario4/omnetpp.ini"

echo ""

# ------------------------------------------------------------------------------
# Summary
# ------------------------------------------------------------------------------
echo "=============================================="
echo "Generated files:"
echo "=============================================="
ls -la "$OUTPUT_DIR"/*.xml "$OUTPUT_DIR"/*.ndjson 2>/dev/null || true
echo ""
ls -la "$OUTPUT_DIR"/scenario*/omnetpp.ini 2>/dev/null || true
echo ""
echo "Generated scenario configs:"
echo "  scenario1/omnetpp.ini - Simple 2x2 grid (no buildings)"
echo "  scenario2/omnetpp.ini - Dense 3x3 grid with buildings"
echo "  scenario2_nobuildings/omnetpp.ini - Same trajectories, no buildings (comparison)"
echo "  scenario3/omnetpp.ini - Wide corridors, low buildings"
echo "  scenario4/omnetpp.ini - Skyscraper district"
echo ""
echo "To run a scenario:"
echo "  cd simulations/urbanenv_testing/scenario1"
echo "  /usr/uli-net-sim/container-build/out/clang-release/uav_rid \\"
echo "    -u Cmdenv -c Scenario1_Simple2x2 \\"
echo "    -n ../..:../../../src:\$INET_ROOT/src"
echo "=============================================="
