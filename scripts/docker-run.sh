#!/usr/bin/env bash
#
# Run a command in the uli-net-sim image with the repo bind-mounted.
# Uses /opt/uli-venv from the image (no host .venv required).
#
# Usage:
#   ./scripts/docker-run.sh python3 datagen/generate_spoofing_sweep.py --help
#   ./scripts/docker-run.sh python3 datagen/run_batch.py simulations/foo/ --parallel 4
#
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE="${ULI_NET_SIM_IMAGE:-uli-net-sim:latest}"
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"

exec docker run --rm \
  --user "${HOST_UID}:${HOST_GID}" \
  -e HOME=/tmp \
  -v "$ROOT:/usr/uli-net-sim/uav_rid" \
  -w /usr/uli-net-sim/uav_rid \
  "$IMAGE" \
  "$@"
