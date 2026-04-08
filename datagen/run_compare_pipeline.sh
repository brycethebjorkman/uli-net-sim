#!/usr/bin/env bash
#
# One-command SpoofingAware vs TrustRID comparison runner.
#
# Supports:
#   - one scenario or many scenarios
#   - multiple seeds (e.g., --seeds 0:29)
#   - combined summary + vector export + charts for paper figures
#
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  ./datagen/run_compare_pipeline.sh [scenario selection] [options]

Scenario selection (choose one):
  --scenario-config NAME           Single base config (e.g., Scenario_Corners_4x1)
  --scenario-configs CSV           Comma-separated list of configs
  --paper-scenarios                Use paper default set:
                                   Scenario_Corners_4x1,Scenario_Hub_4x1,
                                   Scenario_Circle_8x1,Scenario_Hub_8x1

Options:
  --seeds SPEC                     Seed spec: "0:29" or "0,1,2" (default: 0)
  --base-ini PATH                  Source INI (default: simulations/spoofing_aware_with_planning/omnetpp.ini)
  --run-name NAME                  Output folder under sweep root (default: derived)
  --sweep-root PATH                Root for outputs (default: simulations/spoofing_aware_with_planning/sweeps)
  --parallel N                     run_batch parallel value (default: 0 = auto)
  --image NAME                     Docker image tag (default: uli-net-sim:latest)
  --skip-build                     Skip docker build
  --no-clean                       Keep prior run artifacts
  --no-keep-vec                    Do not keep results/*.vec (disables vector export)
  --no-export-vectors              Skip GCS vector CSV export
  --no-plot                        Skip chart generation
  -h, --help                       Show this help
EOF
}

BASE_INI="simulations/spoofing_aware_with_planning/omnetpp.ini"
SWEEP_ROOT="simulations/spoofing_aware_with_planning/sweeps"
RUN_NAME=""
PARALLEL="0"
IMAGE="uli-net-sim:latest"
SEEDS_SPEC="0"
SKIP_BUILD="0"
DO_CLEAN="1"
KEEP_VEC="1"
EXPORT_VECTORS="1"
DO_PLOT="1"

SINGLE_SCENARIO=""
SCENARIOS_CSV=""
PAPER_SCENARIOS="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenario-config)
      SINGLE_SCENARIO="${2:-}"; shift 2 ;;
    --scenario-configs)
      SCENARIOS_CSV="${2:-}"; shift 2 ;;
    --paper-scenarios)
      PAPER_SCENARIOS="1"; shift ;;
    --seeds)
      SEEDS_SPEC="${2:-}"; shift 2 ;;
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

if [[ ! -f "$BASE_INI" ]]; then
  echo "Base INI not found: $BASE_INI" >&2
  exit 1
fi

declare -a SCENARIOS=()
if [[ "$PAPER_SCENARIOS" == "1" ]]; then
  SCENARIOS=(
    "Scenario_Corners_4x1"
    "Scenario_Hub_4x1"
    "Scenario_Circle_8x1"
    "Scenario_Hub_8x1"
  )
elif [[ -n "$SCENARIOS_CSV" ]]; then
  IFS=',' read -r -a SCENARIOS <<<"$SCENARIOS_CSV"
elif [[ -n "$SINGLE_SCENARIO" ]]; then
  SCENARIOS=("$SINGLE_SCENARIO")
else
  echo "Choose one scenario selection: --scenario-config, --scenario-configs, or --paper-scenarios" >&2
  usage
  exit 2
fi

declare -a SEEDS=()
if [[ "$SEEDS_SPEC" == *:* ]]; then
  start="${SEEDS_SPEC%%:*}"
  end="${SEEDS_SPEC##*:}"
  if ! [[ "$start" =~ ^[0-9]+$ && "$end" =~ ^[0-9]+$ ]]; then
    echo "Invalid --seeds range: $SEEDS_SPEC (expected like 0:29)" >&2
    exit 2
  fi
  if (( start > end )); then
    echo "Invalid --seeds range: start > end" >&2
    exit 2
  fi
  for ((s=start; s<=end; s++)); do
    SEEDS+=("$s")
  done
else
  IFS=',' read -r -a raw_seeds <<<"$SEEDS_SPEC"
  for s in "${raw_seeds[@]}"; do
    if ! [[ "$s" =~ ^[0-9]+$ ]]; then
      echo "Invalid seed in --seeds: $s" >&2
      exit 2
    fi
    SEEDS+=("$s")
  done
fi

if [[ ${#SEEDS[@]} -eq 0 ]]; then
  echo "No seeds resolved from --seeds $SEEDS_SPEC" >&2
  exit 2
fi

if [[ -z "$RUN_NAME" ]]; then
  if [[ ${#SCENARIOS[@]} -eq 1 ]]; then
    RUN_NAME="$(printf '%s' "${SCENARIOS[0]}" | sed 's/^Scenario_//' | tr '[:upper:]' '[:lower:]')_sweep"
  else
    RUN_NAME="paper_suite"
  fi
fi

RUN_ROOT="$SWEEP_ROOT/$RUN_NAME"
GEN_DIR="$RUN_ROOT/generated"
SUMMARY_CSV="$RUN_ROOT/summary.csv"
GCS_VEC_DIR="$RUN_ROOT/gcs_vectors"
RUNTIME_CSV="$RUN_ROOT/run_timing.csv"
OVERALL_START_EPOCH="$(date +%s)"

if [[ "$PARALLEL" == "0" ]]; then
  if command -v nproc >/dev/null 2>&1; then
    PARALLEL="$(nproc)"
  else
    PARALLEL="4"
  fi
fi
if ! [[ "$PARALLEL" =~ ^[0-9]+$ ]] || (( PARALLEL < 1 )); then
  echo "Invalid --parallel value: $PARALLEL" >&2
  exit 2
fi

echo "== Config =="
echo "Scenarios:     ${SCENARIOS[*]}"
echo "Seeds:         ${SEEDS[*]}"
echo "Run root:      $RUN_ROOT"
echo "Parallel jobs: $PARALLEL"

if [[ "$SKIP_BUILD" == "0" ]]; then
  echo "== Building Docker image: $IMAGE =="
  docker build -f Containerfile -t "$IMAGE" .
fi

export ULI_NET_SIM_IMAGE="$IMAGE"

mkdir -p "$GEN_DIR" "$GCS_VEC_DIR"
mkdir -p "$RUN_ROOT"
echo "scenario,seed,scenario_tag,elapsed_seconds" > "$RUNTIME_CSV"

if [[ "$DO_CLEAN" == "1" ]]; then
  echo "== Cleaning prior artifacts for run root =="
  rm -rf "$GEN_DIR" "$RUN_ROOT/charts" || true
  mkdir -p "$GEN_DIR" "$GCS_VEC_DIR"
  rm -f "$SUMMARY_CSV" || true
  rm -f "$GCS_VEC_DIR"/*.csv || true
fi

run_one() {
  local scenario="$1"
  local seed="$2"
  local scen_tag="$3"
  local scen_dir="$4"
  local aware_cfg="$5"
  local trust_cfg="$6"
  local run_start_epoch
  local run_elapsed
  local RUN_CMD

  echo "== Running $scen_tag comparison =="
  run_start_epoch="$(date +%s)"
  RUN_CMD=(./scripts/docker-run.sh python3 datagen/run_batch.py "$scen_dir" --configs "$aware_cfg" "$trust_cfg" --parallel 1)
  if [[ "$KEEP_VEC" == "1" ]]; then
    RUN_CMD+=(--keep-vec)
  fi
  "${RUN_CMD[@]}"
  run_elapsed=$(( $(date +%s) - run_start_epoch ))
  echo "$scenario,$seed,$scen_tag,$run_elapsed" >> "$RUNTIME_CSV"
  echo "== Completed $scen_tag in ${run_elapsed}s =="
}

for scenario in "${SCENARIOS[@]}"; do
  scen_slug="$(printf '%s' "$scenario" | sed 's/^Scenario_//' | tr '[:upper:]' '[:lower:]')"
  for seed in "${SEEDS[@]}"; do
    seed_pad="$(printf '%05d' "$seed")"
    scen_tag="${scenario}_s${seed_pad}"
    dir_tag="${scen_slug}_s${seed_pad}"
    scen_dir="$GEN_DIR/$dir_tag"
    aware_cfg="${scen_tag}_Aware"
    trust_cfg="${scen_tag}_TrustRid"

    mkdir -p "$scen_dir"
    ini_out="$scen_dir/omnetpp.ini"

    echo "== Writing isolated INI: $ini_out =="
    python3 - "$BASE_INI" "$ini_out" "$scenario" "$aware_cfg" "$trust_cfg" "$seed" <<'PY'
from pathlib import Path
import sys

base_ini = Path(sys.argv[1])
out_ini = Path(sys.argv[2])
scenario = sys.argv[3]
aware = sys.argv[4]
trust = sys.argv[5]
seed = int(sys.argv[6])

text = base_ini.read_text()
append = f"""

# ---- Auto-added by datagen/run_compare_pipeline.sh ----
[Config {aware}]
extends = {scenario}
seed-set = {seed}
*.gcs[0].pyClass = "pymodules.planners.spoofing_aware_gcs.SpoofingAwareGcs"

[Config {trust}]
extends = {scenario}
seed-set = {seed}
*.gcs[0].pyClass = "pymodules.planners.trust_rid_gcs.TrustRidGcs"
"""
out_ini.write_text(text + append)
print(f"Wrote {out_ini}")
PY

    if [[ "$DO_CLEAN" == "1" ]]; then
      rm -f "$scen_dir"/*.parquet "$scen_dir"/*.sca || true
      rm -rf "$scen_dir"/results || true
    fi

    run_one "$scenario" "$seed" "$scen_tag" "$scen_dir" "$aware_cfg" "$trust_cfg" &
    while (( $(jobs -pr | wc -l) >= PARALLEL )); do
      wait -n
    done
  done
done

wait

echo "== Writing combined scalar summary CSV =="
./scripts/docker-run.sh python3 -m pymodules.analysis.spoofing_batch_metrics \
  "$GEN_DIR" \
  -o "$SUMMARY_CSV"

if [[ "$EXPORT_VECTORS" == "1" && "$KEEP_VEC" == "1" ]]; then
  echo "== Exporting GCS vectors (all runs) =="
  shopt -s nullglob
  vecs=("$GEN_DIR"/*/results/*-#0.vec)
  if [[ ${#vecs[@]} -eq 0 ]]; then
    echo "No .vec files found under $GEN_DIR/*/results; skipping vector export."
  else
    for vec in "${vecs[@]}"; do
      scenedir="$(basename "$(dirname "$(dirname "$vec")")")"
      runbase="$(basename "$vec" .vec)"
      out="$GCS_VEC_DIR/${scenedir}-${runbase}-gcs.csv"
      ./scripts/docker-run.sh opp_scavetool export -F CSV-R -x columnNames=true \
        -f 'type=~"vector" and module=~"*.gcs[*]" and (name=~"*min_benign_spoofer_distance_now_m*" or name=~"*min_benign_spoofer_distance_running_min_m*" or name=~"*spoofer_containment_rate*" or name=~"*nmac_proximity_total*" or name=~"*nmac_benign_spoofer_total*" or name=~"*nmac_spoofer_unsafe_total*")' \
        -o "$out" "$vec"
      echo "Wrote $out"
    done
  fi
fi

if [[ "$DO_PLOT" == "1" ]]; then
  echo "== Generating charts and distribution tables =="
  ./scripts/docker-run.sh python3 datagen/plot_sweep_charts.py \
    --sweep-root "$RUN_ROOT"
fi

echo "== Done =="
total_elapsed=$(( $(date +%s) - OVERALL_START_EPOCH ))
echo "Total runtime: ${total_elapsed}s"
echo "$total_elapsed" > "$RUN_ROOT/total_runtime_seconds.txt"
echo "Summary:  $SUMMARY_CSV"
echo "Vectors:  $GCS_VEC_DIR"
echo "Charts:   $RUN_ROOT/charts"
echo "Run timing CSV: $RUNTIME_CSV"
