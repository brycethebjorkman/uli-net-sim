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

# OMNeT++ on PATH; INET_ROOT for -l / -n (must not be empty — empty becomes /out/...).
if [ -f "$PROJ_DIR/scripts/omnetpp-env.sh" ]; then
    # shellcheck source=omnetpp-env.sh
    . "$PROJ_DIR/scripts/omnetpp-env.sh"
fi

if [ -z "${INET_ROOT:-}" ]; then
    if [ -n "${INET4_5_PROJ:-}" ]; then
        INET_ROOT="$INET4_5_PROJ"
    elif [ -n "${OMNETPP_ROOT:-}" ] && [ -d "$OMNETPP_ROOT/samples/inet4.5" ]; then
        INET_ROOT="$OMNETPP_ROOT/samples/inet4.5"
    elif [ -d "/Applications/omnetpp-6.3.0/samples/inet4.5" ]; then
        INET_ROOT="/Applications/omnetpp-6.3.0/samples/inet4.5"
    elif [ -d "$BASE_DIR/inet4.5" ]; then
        INET_ROOT="$BASE_DIR/inet4.5"
    else
        echo "Error: INET_ROOT is not set and inet4.5 was not found." >&2
        echo "Set INET_ROOT or INET4_5_PROJ to your inet4.5 source tree (same as build.sh)." >&2
        exit 1
    fi
    export INET_ROOT
fi

INET_RELEASE_DIR="$INET_ROOT/out/clang-release/src"
INET_LIB=""
if [ -f "$INET_RELEASE_DIR/libINET.dylib" ]; then
    INET_LIB="$INET_RELEASE_DIR/libINET.dylib"
elif [ -f "$INET_RELEASE_DIR/libINET.so" ]; then
    INET_LIB="$INET_RELEASE_DIR/libINET.so"
else
    echo "Error: INET library not found under $INET_RELEASE_DIR" >&2
    echo "Build INET (release) in the IDE or: cd \"\$INET_ROOT\" && make MODE=release" >&2
    exit 1
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
    -l "$INET_LIB"
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
