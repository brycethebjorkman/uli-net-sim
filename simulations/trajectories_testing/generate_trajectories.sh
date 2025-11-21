#!/usr/bin/env bash
#
# generate_trajectories.sh
#
# Generates the trajectories.xml file for the trajectories_testing simulation.
# This script configures 4 different UAV trajectory patterns:
#   - Movement 1: Logarithmic curve (y = ln(x))
#   - Movement 2: Exponential curve (y = e^x)
#   - Movement 3: Linear trajectory
#   - Movement 4: Parabolic curve (y = x^2)
#

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Path to the trajectories.py utility (relative to project root)
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TRAJECTORIES_PY="$PROJ_ROOT/src/utils/trajectories.py"

# Output file (in the same directory as this script)
OUTPUT_FILE="$SCRIPT_DIR/trajectories.xml"

# Check if trajectories.py exists
if [ ! -f "$TRAJECTORIES_PY" ]; then
    echo "Error: trajectories.py not found at $TRAJECTORIES_PY" >&2
    exit 1
fi

# Generate the trajectories
python3 "$TRAJECTORIES_PY" \
    --out "$OUTPUT_FILE" \
    --points 200 \
    --xmin 0.1 \
    --xmax 4.0 \
    --scale-x 20.0 \
    --scale-y 15.0 \
    --z 50.0 \
    --speed 10.0 \
    --add-log 1 150.0 75.0 \
    --add-exp 2 150.0 250.0 \
    --add-linear 3 200.0 150.0 0.5 \
    --add-parabolic 4 250.0 100.0 0.3

echo "Successfully generated $OUTPUT_FILE"
