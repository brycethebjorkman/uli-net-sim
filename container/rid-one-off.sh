#!/usr/bin/env bash
#
# rid-one-off.sh - Run a one-off Remote ID simulation
#
# Usage:
#   cd /usr/uli-net-sim/uav_rid && . container/setenv && ./container/rid-one-off.sh [options]
#

set -e

# Determine script location and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_DIR="$(cd "$PROJ_DIR/.." && pwd)"

usage_text="
Remote ID One-Off Simulation:
    Launch a one-off simulation for a single Remote ID beacon broadcast.
    The options configure the Remote ID.
    The operands are given as a list of tuples, each configuring a drone.
    The first tuple given is assumed to be the transmitter.

Usage:
    $0 [options] -- n,x,y,z,s,h,e [n,x,y,z,s,h,e ...]

Example:
    $0 -n 103 -t 0.1 -x 24 -y 25 -z 5 -v 1 -g 1 -h 1 -- 101,0,0,5,0,0,0 102,-500,-500,5,2,0,0 103,50,50,5,2,0,0

Options:
    -n      int     Remote ID serial number
    -t      float   Remote ID timestamp
    -x      float   Remote ID X position
    -y      float   Remote ID Y position
    -z      float   Remote ID Z position
    -v      float   Remote ID vertical speed
    -g      float   Remote ID horizontal (ground) speed
    -h      float   Remote ID heading
    -q              Quiet: suppress all script output except final JSON output

Operands:
    n       int     serial number of drone
    x       float   X position of drone in meters
    y       float   Y position of drone in meters
    z       float   Z position of drone in meters
    s       float   speed of drone mobility in meter per second
    h       float   heading of drone mobility in degrees from North
    e       float   elevation of drone mobility in degrees from horizontal
"

usage() {
    echo "$usage_text" >&2
    exit 1
}

if ! OPTIONS=$(getopt -o 'n:,t:,x:,y:,z:,v:,g:,h:,q' -- "$@") ; then
    echo "Failed to parse arguments with getopt" >&2
    usage
fi

eval set -- "$OPTIONS"

rid_n=""
rid_t=""
rid_x=""
rid_y=""
rid_z=""
rid_v=""
rid_g=""
rid_h=""
quiet=false

while true; do
    case "$1" in
        -n) rid_n=$2;   shift 2 ;;
        -t) rid_t=$2;   shift 2 ;;
        -x) rid_x=$2;   shift 2 ;;
        -y) rid_y=$2;   shift 2 ;;
        -z) rid_z=$2;   shift 2 ;;
        -v) rid_v=$2;   shift 2 ;;
        -g) rid_g=$2;   shift 2 ;;
        -h) rid_h=$2;   shift 2 ;;
        -q) quiet=true;    shift ;;
        --) shift; break ;;
        *)  echo "Unrecognized option: $1" >&2; usage ;;
    esac
done

# save original fds
exec 3>&1 4>&2

if [ "$quiet" = true ]; then
    # suppress stdout
    exec 1> /dev/null
fi

# enforce required options
missing=()
[[ -n "$rid_n" ]] || missing+=("-n")
[[ -n "$rid_t" ]] || missing+=("-t")
[[ -n "$rid_x" ]] || missing+=("-x")
[[ -n "$rid_y" ]] || missing+=("-y")
[[ -n "$rid_z" ]] || missing+=("-z")
[[ -n "$rid_v" ]] || missing+=("-v")
[[ -n "$rid_g" ]] || missing+=("-g")
[[ -n "$rid_h" ]] || missing+=("-h")

if (( ${#missing[@]} > 0 )); then
    echo "Missing required options: ${missing[*]}" >&2
    usage
fi

# ensure at least one tuple
if (( $# == 0 )); then
    echo "Provide at least one tuple after --" >&2
    usage
fi

host_count=$#
tx_n=""
rx_count=0
tmp_dir=$(mktemp -d)
vec_out="$tmp_dir/rid-one-off.vec"
run_args+=" --result-dir=$tmp_dir"
run_args+=" --output-vector-file=$vec_out"
run_args+=" --*.numHosts=$host_count"
run_args+=' --sim-time-limit=1s'
run_args+=' --uav_rid.rid_network.BasicUav.hasVisualizer=false'
run_args+=' --*.host[*].wlan[0].mgmt.beaconInterval=900ms'
run_args+=' --*.host[*].mobility.typename="LinearMobility"'

# iterate over each tuple argument
host_num=0
host_map=()
for t in "$@"; do
    # split on commas into an array
    IFS=',' read -r -a fields <<< "$t"

    if (( ${#fields[@]} != 7 )); then
        echo "Invalid tuple (need 7 comma-separated values): $t" >&2
        usage
    fi

    n=${fields[0]}
    x=${fields[1]}
    y=${fields[2]}
    z=${fields[3]}
    s=${fields[4]}
    h=${fields[5]}
    e=${fields[6]}

    host_map+=("$n")

    run_args+=" --*.host[$host_num].wlan[0].mgmt.serialNumber=$n"
    run_args+=" --*.host[$host_num].wlan[0].mgmt.startupJitter=0ms"
    run_args+=" --*.host[$host_num].mobility.initialX=${x}m"
    run_args+=" --*.host[$host_num].mobility.initialY=${y}m"
    run_args+=" --*.host[$host_num].mobility.initialZ=${z}m"
    run_args+=" --*.host[$host_num].mobility.speed=${s}mps"
    run_args+=" --*.host[$host_num].mobility.initialMovementHeading=${h}deg"
    run_args+=" --*.host[$host_num].mobility.initialMovementElevation=${e}deg"

    if [ -z "$tx_n" ] ; then
        tx_n=$s
        run_args+=" --*.host[$host_num].wlan[0].mgmt.transmitBeacon=true"
        run_args+=" --*.host[$host_num].wlan[0].mgmt.oneOff=true"
    else
        rx_count=$((rx_count+1))
        run_args+=" --*.host[$host_num].wlan[0].mgmt.transmitBeacon=false"
    fi

    host_num=$((host_num+1))
done

if [ "$quiet" = false ]; then
    echo "Running simulation with drone $tx_n as transmitter to $rx_count receiver drones and run_args: $run_args"
fi

# Source environment if not already sourced
if [ -z "$INET_ROOT" ]; then
    . "$SCRIPT_DIR/setenv"
fi

# Use container binary
UAV_RID_BIN="$BASE_DIR/container-build/out/clang-release/uav_rid"
if [ ! -f "$UAV_RID_BIN" ]; then
    echo "Error: Container binary not found at $UAV_RID_BIN" >&2
    echo "To build: cd $PROJ_DIR && . container/setenv && ./container/build.sh" >&2
    exit 1
fi

$UAV_RID_BIN -m \
    -f "$PROJ_DIR/simulations/basic_uav/omnetpp.ini" \
    -c General \
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
    -u Cmdenv \
    --cmdenv-express-mode=true \
    --cmdenv-status-frequency=0s \
    --cmdenv-performance-display=false \
    --cmdenv-event-banners=false \
    --**.cmdenv-log-level=off \
    $run_args

opp_scavetool export -F CSV-R -x columnNames=true \
    -f 'type=~"vector" and module=~"BasicUav.host[*].wlan[0].mgmt" and (name=~"Serial Number" or name=~"Reception Power" or name=~"Reception Time")' \
    -o results.csv "$vec_out"

if [ "$quiet" = true ]; then
    # restore fds
    exec 1>&3 2>&4
    # close the saved descriptors
    exec 3>&- 4>&-
fi

"$SCRIPT_DIR/rid-csv-extract.py" results.csv \
    --host-map "${host_map[@]}" \
    --name-pattern "Serial Number" \
    --name-pattern "Reception Power"
