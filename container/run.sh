#!/usr/bin/env bash

. setenv

$PROJ_DIR/out/clang-release/uav_rid -m \
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