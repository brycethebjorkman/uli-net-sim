#!/usr/bin/env bash
#
# scitech26_gen.sh
#
# Generate evaluation dataset for SciTech 2026 paper on UAV Remote ID spoofing detection.
#
# USAGE:
#   cd /usr/uli-net-sim/uav_rid && . container/setenv
#   ./container/scitech26_gen.sh [--dry-run]
#
# Output: datasets/scitech26/
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Check for dry-run mode
DRY_RUN=false
if [ "$1" = "--dry-run" ]; then
    DRY_RUN=true
    echo "=== DRY RUN MODE - showing configuration only ==="
    echo ""
fi

# =============================================================================
# Dataset Parameters
# =============================================================================

# Grid and simulation
GRID_SIZE="500-1000"           # 500m to 1000m
SIM_TIME="300-600"             # 5min to 10min (in seconds)
NUM_HOSTS="6-12"               # 6 to 12 hosts (includes 1 ghost + 1 spoofer)

# Corridors
NUM_EW="4-6"
NUM_NS="4-6"
CORRIDOR_WIDTH="10-50"         # 10m to 50m
CORRIDOR_SPACING="60-120"      # 60m to 120m

# Buildings
NUM_BUILDINGS="10-20"          # Will vary with grid size via param variants
BUILDING_HEIGHT="10-100"       # 10m to 100m

# Trajectory
SPEED="5-15"                   # 5 to 15 m/s
ALTITUDE="30-100"              # 30m to 100m

# Radio
TX_POWER="10-25"               # 10 to 25 dBm
BEACON_INTERVAL="0.75-1.0"     # 0.75s to 1.0s
BEACON_OFFSET="0-0.5"          # Small random offset
BACKGROUND_NOISE="-90"         # Realistic urban noise floor

# Spoofer: always enabled (1 ghost + 1 spoofer)
ENABLE_SPOOFER="--enable-spoofer"

# Federates: always 4
NUM_FEDERATES=4
MAX_FEDERATE_VARIANTS=8

# Parallelization: 0 = auto-detect (nproc)
PARALLEL_JOBS=0

# =============================================================================
# Branching Factors
# =============================================================================
# Goal: Generate diverse dataset with good coverage of parameter space
#
# Structure:
#   param-variants: Top-level parameter sets (grid size, hosts, sim time)
#   corridor-variants: Different corridor layouts per param set
#   building-variants: Different building placements per corridor
#   trajectory-variants: Different flight paths per corridor
#   scenario-variants: Different radio params + random spoofer selection
#
# Total scenarios = param * corridor * building * trajectory * scenario
# Each scenario produces: 2 configs (open/buildings) * up to 8 federate variants
# = up to 16 CSV files per scenario

PARAM_VARIANTS=10              # different grid/host/time combinations
CORRIDOR_VARIANTS=5            # corridor layouts per param set
BUILDING_VARIANTS=6            # building layouts per corridor
TRAJECTORY_VARIANTS=7          # trajectory sets per corridor
SCENARIO_VARIANTS=8            # radio/spoofer variants per combo

# Compute totals
TOTAL_SCENARIOS=$((PARAM_VARIANTS * CORRIDOR_VARIANTS * BUILDING_VARIANTS * TRAJECTORY_VARIANTS * SCENARIO_VARIANTS))

# Time estimate: ~5 seconds per scenario (based on benchmark with similar params)
# This includes: corridor gen, building gen, trajectory gen, 2x simulation runs,
#                2x CSV conversion, 2x federate variant generation
SECONDS_PER_SCENARIO=5

# Resolve parallel jobs for time estimate (0 = auto-detect)
if [ "$PARALLEL_JOBS" -eq 0 ]; then
    EFFECTIVE_PARALLEL=$(nproc 2>/dev/null || echo 4)
else
    EFFECTIVE_PARALLEL=$PARALLEL_JOBS
fi

# Estimate wall-clock time accounting for parallelization
TOTAL_SECONDS=$(( (TOTAL_SCENARIOS * SECONDS_PER_SCENARIO + EFFECTIVE_PARALLEL - 1) / EFFECTIVE_PARALLEL ))
TOTAL_MINUTES=$((TOTAL_SECONDS / 60))
TOTAL_HOURS=$((TOTAL_MINUTES / 60))
REMAINING_MINUTES=$((TOTAL_MINUTES % 60))

# =============================================================================
# Output Configuration
# =============================================================================
OUTPUT_DIR="$PROJ_DIR/datasets/scitech26"
SEED=42

# =============================================================================
# Display Configuration
# =============================================================================
echo "============================================================"
echo "SciTech 2026 Evaluation Dataset Generation"
echo "============================================================"
echo ""
echo "Parameter Ranges:"
echo "  Grid size:         $GRID_SIZE m"
echo "  Sim time:          $SIM_TIME s (5-10 min)"
echo "  Num hosts:         $NUM_HOSTS (includes ghost+spoofer)"
echo ""
echo "Corridor Parameters:"
echo "  EW corridors:      $NUM_EW"
echo "  NS corridors:      $NUM_NS"
echo "  Width:             $CORRIDOR_WIDTH m"
echo "  Spacing:           $CORRIDOR_SPACING m"
echo ""
echo "Building Parameters:"
echo "  Num buildings:     $NUM_BUILDINGS"
echo "  Height:            $BUILDING_HEIGHT m"
echo ""
echo "Trajectory Parameters:"
echo "  Speed:             $SPEED m/s"
echo "  Altitude:          $ALTITUDE m"
echo ""
echo "Radio Parameters:"
echo "  TX power:          $TX_POWER dBm"
echo "  Beacon interval:   $BEACON_INTERVAL s"
echo "  Beacon offset:     $BEACON_OFFSET s"
echo "  Background noise:  $BACKGROUND_NOISE dBm"
echo ""
echo "Spoofer:             enabled (1 ghost + 1 spoofer per scenario)"
echo "Federates:           $NUM_FEDERATES (up to $MAX_FEDERATE_VARIANTS variants)"
echo "Parallel jobs:       $EFFECTIVE_PARALLEL"
echo ""
echo "Branching Factors:"
echo "  Param variants:      $PARAM_VARIANTS"
echo "  Corridor variants:   $CORRIDOR_VARIANTS"
echo "  Building variants:   $BUILDING_VARIANTS"
echo "  Trajectory variants: $TRAJECTORY_VARIANTS"
echo "  Scenario variants:   $SCENARIO_VARIANTS"
echo ""
echo "Estimates:"
echo "  Total scenarios:     $TOTAL_SCENARIOS"
echo "  Max CSV files:       $((TOTAL_SCENARIOS * 2 * (MAX_FEDERATE_VARIANTS + 1)))"
echo "  Est. time:           ${TOTAL_HOURS}h ${REMAINING_MINUTES}m (~${SECONDS_PER_SCENARIO}s/scenario)"
echo ""
echo "Output directory:      $OUTPUT_DIR"
echo "Starting seed:         $SEED"
echo "============================================================"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo "Command that would be run:"
    echo ""
    echo "  ./container/generate_dataset.sh urbanenv \\"
    echo "    --grid-size \"$GRID_SIZE\" \\"
    echo "    --num-hosts \"$NUM_HOSTS\" \\"
    echo "    --sim-time \"$SIM_TIME\" \\"
    echo "    --num-ew \"$NUM_EW\" \\"
    echo "    --num-ns \"$NUM_NS\" \\"
    echo "    --corridor-width \"$CORRIDOR_WIDTH\" \\"
    echo "    --corridor-spacing \"$CORRIDOR_SPACING\" \\"
    echo "    --num-buildings \"$NUM_BUILDINGS\" \\"
    echo "    --building-height \"$BUILDING_HEIGHT\" \\"
    echo "    --speed \"$SPEED\" \\"
    echo "    --altitude \"$ALTITUDE\" \\"
    echo "    --tx-power \"$TX_POWER\" \\"
    echo "    --beacon-interval \"$BEACON_INTERVAL\" \\"
    echo "    --beacon-offset \"$BEACON_OFFSET\" \\"
    echo "    --background-noise \"$BACKGROUND_NOISE\" \\"
    echo "    $ENABLE_SPOOFER \\"
    echo "    --num-federates $NUM_FEDERATES \\"
    echo "    --max-federate-variants $MAX_FEDERATE_VARIANTS \\"
    echo "    --param-variants $PARAM_VARIANTS \\"
    echo "    --corridor-variants $CORRIDOR_VARIANTS \\"
    echo "    --building-variants $BUILDING_VARIANTS \\"
    echo "    --trajectory-variants $TRAJECTORY_VARIANTS \\"
    echo "    --scenario-variants $SCENARIO_VARIANTS \\"
    echo "    --parallel $PARALLEL_JOBS \\"
    echo "    --seed $SEED \\"
    echo "    -o \"$OUTPUT_DIR\""
    echo ""
    exit 0
fi

# =============================================================================
# Run Generation
# =============================================================================
echo "Starting dataset generation..."
echo "This may take a long time. Consider running in screen/tmux."
echo ""

exec ./container/generate_dataset.sh urbanenv \
    --grid-size "$GRID_SIZE" \
    --num-hosts "$NUM_HOSTS" \
    --sim-time "$SIM_TIME" \
    --num-ew "$NUM_EW" \
    --num-ns "$NUM_NS" \
    --corridor-width "$CORRIDOR_WIDTH" \
    --corridor-spacing "$CORRIDOR_SPACING" \
    --num-buildings "$NUM_BUILDINGS" \
    --building-height "$BUILDING_HEIGHT" \
    --speed "$SPEED" \
    --altitude "$ALTITUDE" \
    --tx-power "$TX_POWER" \
    --beacon-interval "$BEACON_INTERVAL" \
    --beacon-offset "$BEACON_OFFSET" \
    --background-noise "$BACKGROUND_NOISE" \
    $ENABLE_SPOOFER \
    --num-federates $NUM_FEDERATES \
    --max-federate-variants $MAX_FEDERATE_VARIANTS \
    --param-variants $PARAM_VARIANTS \
    --corridor-variants $CORRIDOR_VARIANTS \
    --building-variants $BUILDING_VARIANTS \
    --trajectory-variants $TRAJECTORY_VARIANTS \
    --scenario-variants $SCENARIO_VARIANTS \
    --parallel $PARALLEL_JOBS \
    --seed $SEED \
    -o "$OUTPUT_DIR"
