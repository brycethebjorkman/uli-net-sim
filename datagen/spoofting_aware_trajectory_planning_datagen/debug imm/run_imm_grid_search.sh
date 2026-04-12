#!/usr/bin/env bash
#
# IMM grid-search pipeline: runs grid_search_imm.py from the repo root.
# Each trial executes run_spoofing_aware_trajectory_planning_batch.sh with IMM env vars.
#
# Usage:
#   From repo root (or any cwd):
#     ./datagen/spoofting_aware_trajectory_planning_datagen/debug/run_imm_grid_search.sh
#
#   With full control (passes all args to grid_search_imm.py):
#     ./datagen/.../debug/run_imm_grid_search.sh --paper-scenarios --preset-grid single --help
#
#   Log to a file (optional):
#     IMM_GRID_LOG=logs/imm_grid_$(date +%Y%m%d_%H%M%S).log \
#       ./datagen/.../debug/run_imm_grid_search.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
GRID_IMM_PY="${SCRIPT_DIR}/grid_search_imm.py"

usage() {
  cat <<EOF
IMM grid-search pipeline (wrapper around grid_search_imm.py).

Usage:
  $0                 # default: balanced quick grid (see script source)
  $0 ARGS...         # forward ARGS to grid_search_imm.py

Optional env:
  IMM_GRID_LOG=path  append stdout/stderr to path (mkdir -p parent)

Python driver help:
  python3 "${GRID_IMM_PY}" --help
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--" ]]; then
  shift
fi

if [[ ! -f "$GRID_IMM_PY" ]]; then
  echo "grid_search_imm.py not found at: $GRID_IMM_PY" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required but not found in PATH" >&2
  exit 1
fi

cd "$REPO_ROOT"

if [[ -n "${IMM_GRID_LOG:-}" ]]; then
  mkdir -p "$(dirname "$IMM_GRID_LOG")"
  exec >>"$IMM_GRID_LOG" 2>&1
  echo "== IMM grid search log: ${IMM_GRID_LOG} (started $(date -Iseconds)) =="
fi

if [[ $# -eq 0 ]]; then
  set -- \
    --paper-scenarios \
    --include-steepz \
    --seeds 0:2 \
    --parallel 4 \
    --batch-root simulations/spoofing_aware_with_planning/batches_imm_grid_balanced \
    --results-csv simulations/spoofing_aware_with_planning/batches_imm_grid_balanced/imm_grid_search_results.csv \
    --run-prefix imm_balanced_p4 \
    --preset-grid quick \
    --resume-ok \
    --shuffle \
    --shuffle-seed 20260410 \
    --trial-timeout-sec 5400 \
    --trial-retries 1 \
    --heartbeat-sec 60 \
    --estimate-min-per-trial 15 \
    --skip-build \
    --top-k 25
fi

exec python3 "$GRID_IMM_PY" "$@"
