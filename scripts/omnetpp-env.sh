#!/usr/bin/env bash
#
# omnetpp-env.sh - OMNeT++ and INET environment setup
#
# Installed to /etc/profile.d/ in the container so that OMNeT++ and INET
# are available globally in every login shell.  Can also be sourced manually:
#
#   . scripts/omnetpp-env.sh
#

. /usr/uli-net-sim/omnetpp-6.2.0/setenv 2>/dev/null
. /usr/uli-net-sim/inet4.5/setenv 2>/dev/null
export EIGEN_DIR=/usr/uli-net-sim/eigen-5.0.0
