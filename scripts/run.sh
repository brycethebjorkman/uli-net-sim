#!/usr/bin/env bash
#
# run.sh - Run a basic simulation
#
# Usage:
#   cd /usr/uli-net-sim/uav_rid && . container/setenv && ./container/run.sh
#

# Determine script location and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_DIR="$(cd "$PROJ_DIR/.." && pwd)"

# Source environment if not already sourced
if [ -z "$INET_ROOT" ]; then
    . "$SCRIPT_DIR/setenv"
fi

# Use container binary
UAV_RID_BIN="$BASE_DIR/container-build/out/clang-release/uav_rid"
if [ ! -f "$UAV_RID_BIN" ]; then
    echo "Error: Container binary not found at $UAV_RID_BIN"
    echo "To build: cd $PROJ_DIR && . container/setenv && ./container/build.sh"
    exit 1
fi

$UAV_RID_BIN -m \
    -f "$PROJ_DIR/simulations/basic_uav/omnetpp.ini" \
    -c PerpendicularDrones \
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