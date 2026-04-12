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
INET_DIR="$BASE_DIR/inet4.5"
EIGEN_DIR="$BASE_DIR/eigen-5.0.0"
# Source OMNeT++/INET env for opp_makemake on PATH
. "$PROJ_DIR/scripts/omnetpp-env.sh"

# Use the project venv's Python for pybind11 headers and libpython.
# This ensures the simulation binary links against the same Python version
# that the venv packages are compiled for (e.g. 3.12 via uv).
VENV_PYTHON="$PROJ_DIR/.venv/bin/python3"
if [ ! -x "$VENV_PYTHON" ]; then
    echo "Error: project venv not found at $PROJ_DIR/.venv/"
    echo "Run 'uv sync' in the project directory first."
    exit 1
fi

PYBIND11_DIR="$($VENV_PYTHON -c 'import pybind11; print(pybind11.get_include())')"
PYTHON_INCLUDE="$($VENV_PYTHON -c 'import sysconfig; print(sysconfig.get_path("include"))')"
PYTHON_LIBDIR="$($VENV_PYTHON -c 'import sysconfig; print(sysconfig.get_config_var("LIBDIR"))')"
PYTHON_LDLIB="$($VENV_PYTHON -c 'import sysconfig; v=sysconfig.get_config_var("VERSION"); print(f"python{v}")')"

echo "=========================================="
echo "Container Build (Out-of-Tree)"
echo "=========================================="
echo "Source:     $SRC_DIR"
echo "Build:      $BUILD_DIR"
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
    -l"$PYTHON_LDLIB" \
    -losg -losgDB -lOpenThreads

# Build
echo "Building..."
make MODE=release -j$(nproc)

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
