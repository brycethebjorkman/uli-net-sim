#!/usr/bin/env bash
#
# One-command Aware vs TrustRid comparison runner for a scenario config.
#
# Example:
#   ./datagen/run_compare_pipeline.sh --scenario-config Scenario_Corners_4x1
#
# This script:
#   1) optionally builds Docker image
#   2) creates an isolated scenario folder with *_Aware / *_TrustRid leaf configs
#   3) runs run_batch.py for those two configs
#   4) writes summary.csv
#   5) exports GCS vectors for time-series charts
#   6) runs datagen/plot_sweep_charts.py
#
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./datagen/run_compare_pipeline.sh --scenario-config <ConfigName> [options]

Required:
  --scenario-config NAME      Base config in simulations/.../omnetpp.ini
                              (e.g., Scenario_Corners_4x1)

Optional:
  --base-ini PATH             Source INI (default: simulations/spoofing_aware_with_planning/omnetpp.ini)
  --run-name NAME             Output run folder name (default: derived from scenario)
  --sweep-root PATH           Root for outputs (default: simulations/spoofing_aware_with_planning/sweeps)
  --parallel N                run_batch parallel value (default: 0 = auto)
  --image NAME                Docker image tag (default: uli-net-sim:latest)
  --skip-build                Skip docker build
  --no-clean                  Keep prior run artifacts
  --no-keep-vec               Do not keep results/*.vec (disables vector export)
  --no-export-vectors         Skip GCS vector CSV export
  --no-plot                   Skip chart generation
  -h, --help                  Show this help
EOF
}

SCENARIO_CONFIG=""
BASE_INI="simulations/spoofing_aware_with_planning/omnetpp.ini"
SWEEP_ROOT="simulations/spoofing_aware_with_planning/sweeps"
RUN_NAME=""
PARALLEL="0"
IMAGE="uli-net-sim:latest"
SKIP_BUILD="0"
DO_CLEAN="1"
KEEP_VEC="1"
EXPORT_VECTORS="1"
DO_PLOT="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenario-config)
      SCENARIO_CONFIG="${2:-}"; shift 2 ;;
    --base-ini)
      BASE_INI="${2:-}"; shift 2 ;;
    --run-name)
      RUN_NAME="${2:-}"; shift 2 ;;
    --sweep-root)
      SWEEP_ROOT="${2:-}"; shift 2 ;;
    --parallel)
      PARALLEL="${2:-}"; shift 2 ;;
    --image)
      IMAGE="${2:-}"; shift 2 ;;
    --skip-build)
      SKIP_BUILD="1"; shift ;;
    --no-clean)
      DO_CLEAN="0"; shift ;;
    --no-keep-vec)
      KEEP_VEC="0"; shift ;;
    --no-export-vectors)
      EXPORT_VECTORS="0"; shift ;;
    --no-plot)
      DO_PLOT="0"; shift ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2 ;;
  esac
done

if [[ -z "$SCENARIO_CONFIG" ]]; then
  echo "Missing required argument: --scenario-config" >&2
  usage
  exit 2
fi

if [[ ! -f "$BASE_INI" ]]; then
  echo "Base INI not found: $BASE_INI" >&2
  exit 1
fi

if [[ -z "$RUN_NAME" ]]; then
  # Scenario_Corners_4x1 -> corners_4x1
  RUN_NAME="$(printf '%s' "$SCENARIO_CONFIG" | sed 's/^Scenario_//' | tr '[:upper:]' '[:lower:]')"
fi

RUN_ROOT="$SWEEP_ROOT/$RUN_NAME"
GEN_DIR="$RUN_ROOT/generated"
SCEN_DIR="$GEN_DIR/${RUN_NAME}_s00000"
SUMMARY_CSV="$RUN_ROOT/summary.csv"
GCS_VEC_DIR="$RUN_ROOT/gcs_vectors"

AWARE_CFG="${SCENARIO_CONFIG}_Aware"
TRUST_CFG="${SCENARIO_CONFIG}_TrustRid"

echo "== Config =="
echo "Scenario:      $SCENARIO_CONFIG"
echo "Aware config:  $AWARE_CFG"
echo "Trust config:  $TRUST_CFG"
echo "Run root:      $RUN_ROOT"

if [[ "$SKIP_BUILD" == "0" ]]; then
  echo "== Building Docker image: $IMAGE =="
  docker build -f Containerfile -t "$IMAGE" .
fi

mkdir -p "$SCEN_DIR" "$GCS_VEC_DIR"

echo "== Writing isolated INI: $SCEN_DIR/omnetpp.ini =="
python3 - "$BASE_INI" "$SCEN_DIR/omnetpp.ini" "$SCENARIO_CONFIG" "$AWARE_CFG" "$TRUST_CFG" <<'PY'
from pathlib import Path
import sys

base_ini = Path(sys.argv[1])
out_ini = Path(sys.argv[2])
scenario = sys.argv[3]
aware = sys.argv[4]
trust = sys.argv[5]

text = base_ini.read_text()
append = f"""

# ---- Auto-added by datagen/run_compare_pipeline.sh ----
[Config {aware}]
extends = {scenario}
*.gcs[0].pyClass = "pymodules.planners.spoofing_aware_gcs.SpoofingAwareGcs"

[Config {trust}]
extends = {scenario}
*.gcs[0].pyClass = "pymodules.planners.trust_rid_gcs.TrustRidGcs"
"""
out_ini.write_text(text + append)
print(f"Wrote {out_ini}")
PY

if [[ "$DO_CLEAN" == "1" ]]; then
  echo "== Cleaning prior artifacts for run folder =="
  rm -f "$SCEN_DIR"/*.parquet "$SCEN_DIR"/*.sca || true
  rm -rf "$SCEN_DIR"/results || true
  rm -f "$SUMMARY_CSV" || true
  rm -f "$GCS_VEC_DIR"/*.csv || true
fi

echo "== Running scenario comparison (Aware + TrustRid) =="
RUN_CMD=(./scripts/docker-run.sh python3 datagen/run_batch.py "$SCEN_DIR" --configs "$AWARE_CFG" "$TRUST_CFG" --parallel "$PARALLEL")
if [[ "$KEEP_VEC" == "1" ]]; then
  RUN_CMD+=(--keep-vec)
fi
"${RUN_CMD[@]}"

echo "== Writing scalar summary CSV =="
./scripts/docker-run.sh python3 -m pymodules.analysis.spoofing_batch_metrics \
  "$GEN_DIR" \
  -o "$SUMMARY_CSV"

if [[ "$EXPORT_VECTORS" == "1" && "$KEEP_VEC" == "1" ]]; then
  echo "== Exporting GCS vectors =="
  shopt -s nullglob
  vecs=("$SCEN_DIR"/results/*-#0.vec)
  if [[ ${#vecs[@]} -eq 0 ]]; then
    echo "No .vec files found under $SCEN_DIR/results; skipping vector export."
  else
    for vec in "${vecs[@]}"; do
      runbase="$(basename "$vec" .vec)"
      out="$GCS_VEC_DIR/${runbase}-gcs.csv"
      ./scripts/docker-run.sh opp_scavetool export -F CSV-R -x columnNames=true \
        -f 'type=~"vector" and module=~"*.gcs[*]" and (name=~"*min_benign_spoofer_distance_now_m*" or name=~"*min_benign_spoofer_distance_running_min_m*" or name=~"*spoofer_containment_rate*" or name=~"*nmac_proximity_total*" or name=~"*nmac_benign_spoofer_total*" or name=~"*nmac_spoofer_unsafe_total*")' \
        -o "$out" "$vec"
      echo "Wrote $out"
    done
  fi
fi

if [[ "$DO_PLOT" == "1" ]]; then
  echo "== Generating charts =="
  ./scripts/docker-run.sh python3 datagen/plot_sweep_charts.py \
    --sweep-root "$RUN_ROOT"
fi

echo "== Done =="
echo "Summary:  $SUMMARY_CSV"
echo "Vectors:  $GCS_VEC_DIR"
echo "Charts:   $RUN_ROOT/charts"
