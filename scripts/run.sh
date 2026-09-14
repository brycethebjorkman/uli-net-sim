#!/usr/bin/env bash
#
# run.sh - Run the uav_rid OMNeT++ simulation (headless, express mode)
#
# Provides the common binary path, library, NED-path, and Cmdenv arguments
# that every headless invocation needs.  Always forces the sequential
# scheduler so INI-level scheduler-class settings are ignored.
#
# Usage:
#   scripts/run.sh -f FILE -c CONFIG [-r DIR] [-q] [-- extra_args...]
#
# Options:
#   -f FILE   INI file (required)
#   -c CONFIG Config name (required)
#   -r DIR    Result directory (--result-dir)
#   -q        Quiet (suppress logs, banners, performance display)
#
# Examples:
#   scripts/run.sh -f simulations/multirotor_test/omnetpp.ini -c HoverTest \
#       -r /tmp/results
#
#   scripts/run.sh -f scenario/omnetpp.ini -c ScenarioOpenSpace -q \
#       -- --cmdenv-status-frequency=10s
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_DIR="$(cd "$PROJ_DIR/.." && pwd)"

# Source environment if not already sourced
if [ -z "$INET_ROOT" ]; then
    unset __uav_rid_env_loaded  # reset guard so setenv re-sources from bash
    . "$PROJ_DIR/setenv"
fi

UAV_RID_BIN="$BASE_DIR/container-build/out/clang-release/uav_rid"
if [ ! -f "$UAV_RID_BIN" ]; then
    echo "Error: Container binary not found at $UAV_RID_BIN" >&2
    echo "To build: cd $PROJ_DIR && ./scripts/build.sh" >&2
    exit 1
fi

# Parse options
ini_file=""
config=""
result_dir=""
quiet=false

while getopts "f:c:r:q" opt; do
    case "$opt" in
        f) ini_file="$OPTARG" ;;
        c) config="$OPTARG" ;;
        r) result_dir="$OPTARG" ;;
        q) quiet=true ;;
        *) sed -n '2,/^$/{ s/^# \?//; p }' "$0" >&2; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

if [ -z "$ini_file" ]; then
    echo "Error: -f INI_FILE is required" >&2
    exit 1
fi
if [ -z "$config" ]; then
    echo "Error: -c CONFIG is required" >&2
    exit 1
fi

# Build argument list
args=(
    "$UAV_RID_BIN" -m
    -u Cmdenv
    -c "$config"
    -f "$ini_file"
    -l "$INET_ROOT/out/clang-release/src/libINET.so"
    -n "$INET_ROOT/src"
    -n "$INET_ROOT/src/inet/visualizer/common"
    -n "$INET_ROOT/examples"
    -n "$INET_ROOT/showcases"
    -n "$INET_ROOT/tests/validation"
    -n "$INET_ROOT/tests/networks"
    -n "$INET_ROOT/tutorials"
    -n "$PROJ_DIR/simulations"
    -n "$PROJ_DIR/src"
    --scheduler-class=omnetpp::cSequentialScheduler
    --cmdenv-express-mode=true
)

if [ -n "$result_dir" ]; then
    args+=("--result-dir=$result_dir")
fi

if [ "$quiet" = true ]; then
    args+=(
        "--cmdenv-status-frequency=0s"
        "--cmdenv-performance-display=false"
        "--cmdenv-event-banners=false"
        "--**.cmdenv-log-level=off"
    )
fi

# Append any extra arguments after --
args+=("$@")

exec "${args[@]}"
