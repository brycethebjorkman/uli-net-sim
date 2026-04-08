#!/usr/bin/env bash
#
# build.sh
#
# Builds the uav_rid project for container execution using out-of-tree builds.
# This keeps container build artifacts separate from IDE build artifacts.
#
# Source:  /usr/uli-net-sim/uav_rid (mounted from host workspace)
# Output:  /usr/uli-net-sim/container-build/
# Binary:  /usr/uli-net-sim/container-build/out/clang-release/uav_rid
#
# Usage:
#   cd /usr/uli-net-sim/uav_rid && ./scripts/build.sh
#

set -e

# Determine script location and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE_DIR="$(cd "$PROJ_DIR/.." && pwd)"

# Directories
SRC_DIR="$PROJ_DIR"
BUILD_DIR="$BASE_DIR/container-build"

# Prefer ULI_PYTHON, else .venv, else system. Reject .venv that exists but cannot run
# (e.g. Linux venv synced to macOS, or wrong CPU arch — "cannot execute binary file").
if [ -n "${ULI_PYTHON:-}" ] && [ -x "$ULI_PYTHON" ] \
        && "$ULI_PYTHON" -c "import sys" 2>/dev/null; then
    PY="$ULI_PYTHON"
elif [ -x "$PROJ_DIR/.venv/bin/python3" ] \
        && "$PROJ_DIR/.venv/bin/python3" -c "import sys" 2>/dev/null; then
    PY="$PROJ_DIR/.venv/bin/python3"
else
    PY=python3
fi
PYBIND11_DIR="$("$PY" -c 'import pybind11; print(pybind11.get_include())')"
PYTHON_INCLUDE="$("$PY" -c 'import sysconfig; print(sysconfig.get_path("include"))')"
PY_BINDIR="$(dirname "$PY")"
if [ -x "$PY_BINDIR/python3-config" ]; then
    PYTHON_LIBDIR="$("$PY_BINDIR/python3-config" --configdir)"
else
    PYTHON_LIBDIR="$(python3-config --configdir)"
fi
PY_SUFFIX="$("$PY" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"

# OMNeT++/INET on PATH (opp_makemake, nedtool, etc.). Pre-set INET_ROOT — e.g. Docker
# ENV — does not load setenv; always source when present.
if [ -f "$PROJ_DIR/scripts/omnetpp-env.sh" ]; then
    # shellcheck source=omnetpp-env.sh
    . "$PROJ_DIR/scripts/omnetpp-env.sh"
fi

# INET / Eigen: same defaults as IDE Makefile (see root Makefile -KINET4_5_PROJ).
# Override with INET4_5_PROJ / EIGEN_DIR. Fallback: sibling dirs of this repo.
if [ -n "${INET4_5_PROJ:-}" ]; then
    INET_DIR="$INET4_5_PROJ"
elif [ -n "${OMNETPP_ROOT:-}" ] && [ -d "$OMNETPP_ROOT/samples/inet4.5" ]; then
    INET_DIR="$OMNETPP_ROOT/samples/inet4.5"
elif [ -d "/Applications/omnetpp-6.3.0/samples/inet4.5" ]; then
    INET_DIR="/Applications/omnetpp-6.3.0/samples/inet4.5"
else
    INET_DIR="$BASE_DIR/inet4.5"
fi

if [ -n "${EIGEN_DIR:-}" ] && [ -d "$EIGEN_DIR" ]; then
    :
elif [ -n "${OMNETPP_ROOT:-}" ] && [ -d "$OMNETPP_ROOT/samples/eigen-5.0.0" ]; then
    EIGEN_DIR="$OMNETPP_ROOT/samples/eigen-5.0.0"
elif [ -d "/Applications/omnetpp-6.3.0/samples/eigen-5.0.0" ]; then
    EIGEN_DIR="/Applications/omnetpp-6.3.0/samples/eigen-5.0.0"
else
    EIGEN_DIR="$BASE_DIR/eigen-5.0.0"
fi

if [ -f "$INET_DIR/setenv" ]; then
    # shellcheck source=/dev/null
    . "$INET_DIR/setenv"
fi

if ! command -v opp_makemake >/dev/null 2>&1; then
    echo "Error: opp_makemake not on PATH." >&2
    echo "Install OMNeT++ or run, for example:" >&2
    echo "  . /Applications/omnetpp-6.3.0/setenv" >&2
    echo "Or: export OMNETPP_ROOT=/path/to/omnetpp && . \"\$OMNETPP_ROOT/setenv\"" >&2
    exit 1
fi

if [ ! -d "$INET_DIR" ]; then
    echo "Error: INET not found at INET_DIR=$INET_DIR" >&2
    echo "Set INET4_5_PROJ to your inet4.5 source tree (see README)." >&2
    exit 1
fi

if [ ! -d "$EIGEN_DIR" ]; then
    echo "Error: Eigen not found at EIGEN_DIR=$EIGEN_DIR" >&2
    exit 1
fi

echo "=========================================="
echo "Container Build (Out-of-Tree)"
echo "=========================================="
echo "Source:     $SRC_DIR"
echo "Build:      $BUILD_DIR"
echo "INET:       $INET_DIR"
echo "Eigen:      $EIGEN_DIR"
echo "=========================================="

# Create build directory
mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

# Create symlinks to source (if not already present)
if [ ! -L "src" ]; then
    ln -sf "$SRC_DIR/src" src
fi
if [ ! -L "simulations" ]; then
    ln -sf "$SRC_DIR/simulations" simulations
fi

# Generate Makefile
echo "Generating Makefile..."
opp_makemake -f --deep \
    -o uav_rid \
    -O out \
    -KINET4_5_PROJ="$INET_DIR" \
    -DINET_IMPORT \
    -DPROJ_DIR="$PROJ_DIR" \
    -Isrc \
    -I'$(INET4_5_PROJ)/src' \
    -I"$EIGEN_DIR" \
    -I"$PYBIND11_DIR" \
    -I"$PYTHON_INCLUDE" \
    -L'$(INET4_5_PROJ)/out/clang-release/src' \
    -L"$PYTHON_LIBDIR" \
    -lINET \
    -lpython${PY_SUFFIX} \
    -losg -losgDB -lOpenThreads

# Build (nproc is Linux; macOS uses sysctl)
echo "Building..."
_NPROC="$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)"
make MODE=release -j"${_NPROC}"

# Check for binary
BINARY="$BUILD_DIR/out/clang-release/uav_rid"
if [ -f "$BINARY" ]; then
    echo ""
    echo "=========================================="
    echo "Build successful!"
    echo "Binary: $BINARY"
    echo "=========================================="
else
    echo "Error: Binary not found at $BINARY"
    exit 1
fi
