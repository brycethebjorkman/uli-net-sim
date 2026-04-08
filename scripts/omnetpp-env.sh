#!/usr/bin/env bash
#
# omnetpp-env.sh - OMNeT++ and INET environment setup
#
# Usage: . scripts/omnetpp-env.sh
#
# Picks the first available OMNeT++ install:
#   1. $OMNETPP_ROOT/setenv (if OMNETPP_ROOT is set)
#   2. macOS default app bundle
#   3. Docker image layout under /usr/uli-net-sim
#
# INET setenv is applied only for the Docker tree (fixed path). On macOS, INET
# lives under \$OMNETPP_ROOT/samples/inet4.5 — build.sh resolves paths.
#

if [ -n "${OMNETPP_ROOT:-}" ] && [ -f "$OMNETPP_ROOT/setenv" ]; then
    # shellcheck source=/dev/null
    . "$OMNETPP_ROOT/setenv"
elif [ -f /Applications/omnetpp-6.3.0/setenv ]; then
    # shellcheck source=/dev/null
    . /Applications/omnetpp-6.3.0/setenv
elif [ -f /Applications/omnetpp-6.2.0/setenv ]; then
    # shellcheck source=/dev/null
    . /Applications/omnetpp-6.2.0/setenv
elif [ -f /usr/uli-net-sim/omnetpp-6.3.0/setenv ]; then
    # shellcheck source=/dev/null
    . /usr/uli-net-sim/omnetpp-6.3.0/setenv
fi

if [ -f /usr/uli-net-sim/inet4.5/setenv ]; then
    # shellcheck source=/dev/null
    . /usr/uli-net-sim/inet4.5/setenv
fi

if [ -d /usr/uli-net-sim/eigen-5.0.0 ]; then
    export EIGEN_DIR=/usr/uli-net-sim/eigen-5.0.0
fi
