#!/usr/bin/env bash
#
# One-command SpoofingAware / InstantDetect / TrustRID comparison runner.
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
  ./datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh [scenario selection] [options]

Scenario selection (optional; defaults to --paper-scenarios):
  --scenario-config NAME           Single base config (e.g., Scenario_DepotCity_4x1)
  --scenario-configs CSV           Comma-separated list of configs
  --paper-scenarios                Use default depot set:
                                   Scenario_DepotCity_4x1,Scenario_DepotCity_8x1,
                                   Scenario_DepotCity_12x1,Scenario_DepotCity_16x1
  --include-steepz                 Deprecated; ignored for depot-only runs

Options:
  --seeds SPEC                     Seed spec: "0:29" or "0,1,2" (default: 0:29)
  --base-ini PATH                  Source INI (default: simulations/spoofing_aware_with_planning/omnetpp.ini)
  --batch-root PATH                Root for outputs (default: simulations/spoofing_aware_with_planning/batchesPaperExact0005Commit)
  --parallel N                     run_batch parallel value (default: 0 = auto)
  --image NAME                     Docker image tag (default: uli-net-sim:latest)
  --skip-build                     Skip docker build
  --no-clean                       Keep prior run artifacts
  --no-keep-vec                    Do not keep results/*.vec (disables vector export)
  --no-export-vectors              Skip GCS vector CSV export
  --no-plot                        Skip chart generation
  --plot-profile MODE              Plot set: paper|full (default: paper)
  --mission-goal-tol-m X           Goal tolerance (m) for mission-progress summary (default: 10)
  --heartbeat-sec N                Emit heartbeat every N seconds (0 disables; default: 60)
  --instant-detect-at-sec N        Force spoofing detection at N seconds for instant-detect runs (default: 5)
  --force-detect-at-sec N          Deprecated alias for --instant-detect-at-sec
  -h, --help                       Show this help
EOF
}

BASE_INI="simulations/spoofing_aware_with_planning/omnetpp.ini"
BATCH_ROOT="simulations/spoofing_aware_with_planning/batchesPaperExact0005Commit"
PARALLEL="0"
IMAGE="uli-net-sim:latest"
SEEDS_SPEC="0:29"
SKIP_BUILD="0"
DO_CLEAN="1"
KEEP_VEC="1"
EXPORT_VECTORS="1"
DO_PLOT="1"
HEARTBEAT_SEC="60"
PLOT_PROFILE="paper"
MISSION_GOAL_TOL_M="10"
INSTANT_DETECT_AT_SEC="5"

SINGLE_SCENARIO=""
SCENARIOS_CSV=""
PAPER_SCENARIOS="1"
INCLUDE_STEEPZ="0"

next_batch_run_number() {
  local root="$1"
  local max_n="0"
  mkdir -p "$root"
  for d in "$root"/*; do
    [[ -d "$d" ]] || continue
    local base
    local n
    base="$(basename "$d")"
    if [[ "$base" =~ ^[0-9]{4}$ ]]; then
      n=$((10#$base))
      if (( n > max_n )); then
        max_n="$n"
      fi
    fi
  done
  printf '%04d\n' "$((max_n + 1))"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenario-config)
      SINGLE_SCENARIO="${2:-}"; shift 2 ;;
    --scenario-configs)
      SCENARIOS_CSV="${2:-}"; shift 2 ;;
    --paper-scenarios)
      PAPER_SCENARIOS="1"; shift ;;
    --include-steepz)
      INCLUDE_STEEPZ="1"; shift ;;
    --seeds)
      SEEDS_SPEC="${2:-}"; shift 2 ;;
    --base-ini)
      BASE_INI="${2:-}"; shift 2 ;;
    --batch-root)
      BATCH_ROOT="${2:-}"; shift 2 ;;
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
    --plot-profile)
      PLOT_PROFILE="${2:-}"; shift 2 ;;
    --mission-goal-tol-m)
      MISSION_GOAL_TOL_M="${2:-}"; shift 2 ;;
    --heartbeat-sec)
      HEARTBEAT_SEC="${2:-}"; shift 2 ;;
    --instant-detect-at-sec)
      INSTANT_DETECT_AT_SEC="${2:-}"; shift 2 ;;
    --force-detect-at-sec)
      INSTANT_DETECT_AT_SEC="${2:-}"; shift 2 ;;
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
if [[ -n "$SCENARIOS_CSV" ]]; then
  IFS=',' read -r -a SCENARIOS <<<"$SCENARIOS_CSV"
elif [[ -n "$SINGLE_SCENARIO" ]]; then
  SCENARIOS=("$SINGLE_SCENARIO")
elif [[ "$PAPER_SCENARIOS" == "1" ]]; then
  SCENARIOS=(
    "Scenario_DepotCity_4x1"
    "Scenario_DepotCity_8x1"
    "Scenario_DepotCity_12x1"
    "Scenario_DepotCity_16x1"
  )
else
  echo "No scenario selection provided; defaulting to --paper-scenarios." >&2
  PAPER_SCENARIOS="1"
  SCENARIOS=(
    "Scenario_DepotCity_4x1"
    "Scenario_DepotCity_8x1"
    "Scenario_DepotCity_12x1"
    "Scenario_DepotCity_16x1"
  )
fi

if [[ ${#SCENARIOS[@]} -eq 0 ]]; then
  echo "Failed to resolve scenarios; pass --paper-scenarios or explicit scenario configs." >&2
  usage
  exit 2
fi

if [[ "$INCLUDE_STEEPZ" == "1" ]]; then
  echo "[WARN] --include-steepz is deprecated and ignored in depot-only mode."
fi

for scenario in "${SCENARIOS[@]}"; do
  if [[ ! "$scenario" =~ ^Scenario_DepotCity_(4x1|8x1|12x1|16x1)$ ]]; then
    echo "Only depot scenarios are allowed now. Invalid scenario: $scenario" >&2
    echo "Allowed: Scenario_DepotCity_4x1, Scenario_DepotCity_8x1, Scenario_DepotCity_12x1, Scenario_DepotCity_16x1" >&2
    exit 2
  fi
done

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

RUN_ID="$(next_batch_run_number "$BATCH_ROOT")"
RUN_ROOT="$BATCH_ROOT/$RUN_ID"
GEN_DIR="$RUN_ROOT/generated"
SUMMARY_CSV="$RUN_ROOT/summary.csv"
GCS_VEC_DIR="$RUN_ROOT/gcs_vectors"
RUNTIME_CSV="$RUN_ROOT/run_timing.csv"
VARIANT_ROOT="$RUN_ROOT/variants"
VARIANT_DIR_AWARE="$VARIANT_ROOT/spoofing_aware_trajectory_planning"
VARIANT_DIR_INSTANT="$VARIANT_ROOT/instant_detect"
VARIANT_DIR_TRUST="$VARIANT_ROOT/trustRID"
OVERALL_START_EPOCH="$(date +%s)"
FAILED_RUN_JOBS=0
PIPELINE_FAILED=0

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
if ! [[ "$HEARTBEAT_SEC" =~ ^[0-9]+$ ]] || (( HEARTBEAT_SEC < 0 )); then
  echo "Invalid --heartbeat-sec value: $HEARTBEAT_SEC" >&2
  exit 2
fi
if [[ "$PLOT_PROFILE" != "paper" && "$PLOT_PROFILE" != "full" ]]; then
  echo "Invalid --plot-profile value: $PLOT_PROFILE (expected: paper or full)" >&2
  exit 2
fi
if ! [[ "$INSTANT_DETECT_AT_SEC" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
  echo "Invalid --instant-detect-at-sec value: $INSTANT_DETECT_AT_SEC (expected non-negative number)" >&2
  exit 2
fi

echo "== Config =="
echo "Scenarios:     ${SCENARIOS[*]}"
echo "Seeds:         ${SEEDS[*]}"
echo "Run root:      $RUN_ROOT"
echo "Parallel jobs: $PARALLEL"
echo "Heartbeat sec: $HEARTBEAT_SEC"
echo "Plot profile:  $PLOT_PROFILE"
echo "Goal tol (m):  $MISSION_GOAL_TOL_M"
echo "Instant detect s: $INSTANT_DETECT_AT_SEC"

TOTAL_RUN_JOBS=$(( ${#SCENARIOS[@]} * ${#SEEDS[@]} ))
COMPLETED_RUN_JOBS=0
HEARTBEAT_PID=""
CURRENT_PHASE="startup"

progress_pct_int() {
  if (( TOTAL_RUN_JOBS <= 0 )); then
    echo "100"
    return
  fi
  echo $(( (100 * COMPLETED_RUN_JOBS) / TOTAL_RUN_JOBS ))
}

# `jobs -pr` counts every background job, including the heartbeat loop. Without
# subtracting it, we cap at (PARALLEL-1) run_one workers and --parallel 1
# deadlocks after the first job (only the heartbeat remains and wait -n blocks).
count_running_worker_jobs() {
  local n
  n="$(jobs -pr | wc -l | tr -d ' ')"
  if [[ -n "${HEARTBEAT_PID:-}" ]] && kill -0 "$HEARTBEAT_PID" 2>/dev/null; then
    if (( n > 0 )); then
      n=$((n - 1))
    fi
  fi
  printf '%s\n' "$n"
}

heartbeat_loop() {
  while true; do
    sleep "$HEARTBEAT_SEC" || break
    local now elapsed pct
    now="$(date +%s)"
    elapsed=$(( now - OVERALL_START_EPOCH ))
    pct="$(progress_pct_int)"
    # Forked subshell: phase/completed_jobs/progress_pct/failed_jobs are frozen
    # at fork time; only elapsed_s and run_root stay meaningful. Use [PROGRESS] lines.
    echo "[HEARTBEAT] phase=${CURRENT_PHASE} elapsed_s=${elapsed} completed_jobs=${COMPLETED_RUN_JOBS}/${TOTAL_RUN_JOBS} progress_pct=${pct} failed_jobs=${FAILED_RUN_JOBS} run_root=${RUN_ROOT}"
  done
}

start_heartbeat() {
  if (( HEARTBEAT_SEC > 0 )); then
    heartbeat_loop &
    HEARTBEAT_PID="$!"
  fi
}

stop_heartbeat() {
  if [[ -n "${HEARTBEAT_PID:-}" ]]; then
    kill "$HEARTBEAT_PID" 2>/dev/null || true
    wait "$HEARTBEAT_PID" 2>/dev/null || true
    HEARTBEAT_PID=""
  fi
}

trap stop_heartbeat EXIT
start_heartbeat

if [[ "$SKIP_BUILD" == "0" ]]; then
  echo "== Building Docker image: $IMAGE =="
  docker build -f Containerfile -t "$IMAGE" .
fi

export ULI_NET_SIM_IMAGE="$IMAGE"

mkdir -p "$GEN_DIR" "$GCS_VEC_DIR" "$RUN_ROOT/charts"
mkdir -p "$VARIANT_DIR_AWARE/charts/pdfs" "$VARIANT_DIR_AWARE/charts/pngs"
mkdir -p "$VARIANT_DIR_INSTANT/charts/pdfs" "$VARIANT_DIR_INSTANT/charts/pngs"
mkdir -p "$VARIANT_DIR_TRUST/charts/pdfs" "$VARIANT_DIR_TRUST/charts/pngs"
mkdir -p "$RUN_ROOT"
echo "scenario,seed,scenario_tag,elapsed_seconds,elapsed_aware_seconds,elapsed_aware_instant_detect_seconds,elapsed_trust_rid_seconds" > "$RUNTIME_CSV"

if [[ "$DO_CLEAN" == "1" ]]; then
  echo "== Cleaning prior artifacts for run root =="
  rm -rf "$GEN_DIR" "$RUN_ROOT/charts" "$VARIANT_ROOT" || true
  mkdir -p "$GEN_DIR" "$GCS_VEC_DIR" "$RUN_ROOT/charts"
  mkdir -p "$VARIANT_DIR_AWARE/charts/pdfs" "$VARIANT_DIR_AWARE/charts/pngs"
  mkdir -p "$VARIANT_DIR_INSTANT/charts/pdfs" "$VARIANT_DIR_INSTANT/charts/pngs"
  mkdir -p "$VARIANT_DIR_TRUST/charts/pdfs" "$VARIANT_DIR_TRUST/charts/pngs"
  rm -f "$SUMMARY_CSV" || true
  rm -f "$GCS_VEC_DIR"/*.csv || true
fi

run_one() {
  local scenario="$1"
  local seed="$2"
  local scen_tag="$3"
  local scen_dir="$4"
  local aware_cfg="$5"
  local aware_instant_cfg="$6"
  local trust_cfg="$7"
  local run_start_epoch
  local run_elapsed
  local RUN_CMD_AWARE
  local RUN_CMD_AWARE_INSTANT
  local RUN_CMD_TRUST
  local aware_elapsed
  local aware_instant_elapsed
  local trust_elapsed
  local aware_start
  local aware_instant_start
  local trust_start

  echo "== Running $scen_tag comparison =="
  run_start_epoch="$(date +%s)"
  RUN_CMD_AWARE=(./scripts/docker-run.sh python3 datagen/run_batch.py "$scen_dir" --configs "$aware_cfg" --parallel 1)
  RUN_CMD_AWARE_INSTANT=(env ULI_IMM_FORCE_DETECT_AT_S="$INSTANT_DETECT_AT_SEC" ./scripts/docker-run.sh python3 datagen/run_batch.py "$scen_dir" --configs "$aware_instant_cfg" --parallel 1)
  RUN_CMD_TRUST=(./scripts/docker-run.sh python3 datagen/run_batch.py "$scen_dir" --configs "$trust_cfg" --parallel 1)
  if [[ "$KEEP_VEC" == "1" ]]; then
    RUN_CMD_AWARE+=(--keep-vec)
    RUN_CMD_AWARE_INSTANT+=(--keep-vec)
    RUN_CMD_TRUST+=(--keep-vec)
  fi
  aware_start="$(date +%s)"
  "${RUN_CMD_AWARE[@]}"
  aware_elapsed=$(( $(date +%s) - aware_start ))
  aware_instant_start="$(date +%s)"
  "${RUN_CMD_AWARE_INSTANT[@]}"
  aware_instant_elapsed=$(( $(date +%s) - aware_instant_start ))
  trust_start="$(date +%s)"
  "${RUN_CMD_TRUST[@]}"
  trust_elapsed=$(( $(date +%s) - trust_start ))
  run_elapsed=$(( $(date +%s) - run_start_epoch ))
  echo "$scenario,$seed,$scen_tag,$run_elapsed,$aware_elapsed,$aware_instant_elapsed,$trust_elapsed" >> "$RUNTIME_CSV"
  echo "== Completed $scen_tag in ${run_elapsed}s =="
}

for scenario in "${SCENARIOS[@]}"; do
  CURRENT_PHASE="running_scenarios"
  scen_slug="$(printf '%s' "$scenario" | sed 's/^Scenario_//' | tr '[:upper:]' '[:lower:]')"
  for seed in "${SEEDS[@]}"; do
    seed_pad="$(printf '%05d' "$seed")"
    scen_tag="${scenario}_s${seed_pad}"
    dir_tag="${scen_slug}_s${seed_pad}"
    scen_dir="$GEN_DIR/$dir_tag"
    aware_cfg="${scen_tag}_Aware"
    aware_instant_cfg="${scen_tag}_AwareInstantDetect"
    trust_cfg="${scen_tag}_TrustRid"

    mkdir -p "$scen_dir"
    ini_out="$scen_dir/omnetpp.ini"

    echo "== Writing isolated INI: $ini_out =="
    python3 - "$BASE_INI" "$ini_out" "$scenario" "$aware_cfg" "$aware_instant_cfg" "$trust_cfg" "$seed" <<'PY'
from pathlib import Path
import re
import random
import sys

base_ini = Path(sys.argv[1])
out_ini = Path(sys.argv[2])
scenario = sys.argv[3]
aware = sys.argv[4]
aware_instant = sys.argv[5]
trust = sys.argv[6]
seed = int(sys.argv[7])

text = base_ini.read_text()
match = re.search(r"Scenario_DepotCity_(\d+)x1$", scenario)
if not match:
    raise SystemExit(f"Unsupported scenario format for TrustRid override: {scenario}")
spoofer_host = int(match.group(1))
num_benign = spoofer_host


def _scenario_block(full_text: str, cfg_name: str) -> str:
    start_re = re.compile(rf"^\[Config {re.escape(cfg_name)}\]\s*$", re.MULTILINE)
    start_m = start_re.search(full_text)
    if not start_m:
        raise SystemExit(f"Scenario block not found: {cfg_name}")
    tail = full_text[start_m.end():]
    next_cfg_m = re.search(r"^\[Config .+\]\s*$", tail, re.MULTILINE)
    if next_cfg_m:
        return tail[:next_cfg_m.start()]
    return tail


def _parse_xyz(tag: str, xml: str) -> tuple[float, float, float]:
    m = re.search(
        rf"<{tag}\s+[^>]*x='([^']+)'\s+[^>]*y='([^']+)'\s+[^>]*z='([^']+)'",
        xml,
    )
    if not m:
        raise SystemExit(f"Could not parse <{tag}> xyz from waypointScript: {xml}")
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)))


def _parse_speed(xml: str) -> float:
    m = re.search(r"<set\s+[^>]*speed='([^']+)'", xml)
    if not m:
        raise SystemExit(f"Could not parse <set> speed from waypointScript: {xml}")
    return float(m.group(1))


def _format_movement(host_id: int, start: tuple[float, float, float], goal: tuple[float, float, float], speed: float) -> str:
    sx, sy, sz = start
    gx, gy, gz = goal
    return (
        f"<movement id='{host_id}'><set x='{sx:.6g}' y='{sy:.6g}' z='{sz:.6g}' speed='{speed:.6g}'/>"
        f"<moveto x='{gx:.6g}' y='{gy:.6g}' z='{gz:.6g}'/></movement>"
    )


def _dist_point_to_segment_xy(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    px, py = p
    ax, ay = a
    bx, by = b
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    den = abx * abx + aby * aby
    if den <= 1e-9:
        dx = px - ax
        dy = py - ay
        return (dx * dx + dy * dy) ** 0.5
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / den))
    qx = ax + t * abx
    qy = ay + t * aby
    dx = px - qx
    dy = py - qy
    return (dx * dx + dy * dy) ** 0.5


def _choose_constrained_derangement(
    host_ids: list[int],
    starts: dict[int, tuple[float, float, float]],
    goals: dict[int, tuple[float, float, float]],
    rng: random.Random,
    hotspot_xy: tuple[float, float] | None,
) -> list[int]:
    # Keep flights one-leg only, but avoid pathological goal swaps.
    # We constrain by XY trip length and encourage crossing the central corridor.
    min_trip_xy = 320.0
    max_trip_xy = 980.0
    corridor_dist_thresh = 260.0
    relax_thresh = 340.0

    def _feasible(hid: int, gid: int, dist_thresh: float) -> bool:
        if hid == gid:
            return False
        s = starts[hid]
        g = goals[gid]
        dx = g[0] - s[0]
        dy = g[1] - s[1]
        dxy = (dx * dx + dy * dy) ** 0.5
        if dxy < min_trip_xy or dxy > max_trip_xy:
            return False
        if hotspot_xy is None:
            return True
        seg_dist = _dist_point_to_segment_xy(
            hotspot_xy,
            (s[0], s[1]),
            (g[0], g[1]),
        )
        return seg_dist <= dist_thresh

    def _search(dist_thresh: float, attempts: int) -> list[int] | None:
        for _ in range(attempts):
            perm = host_ids[:]
            rng.shuffle(perm)
            if all(_feasible(h, g, dist_thresh) for h, g in zip(host_ids, perm)):
                return perm
        return None

    # Strict corridor constraint first, then relaxed, then pure derangement.
    perm = _search(corridor_dist_thresh, attempts=768)
    if perm is not None:
        return perm
    perm = _search(relax_thresh, attempts=768)
    if perm is not None:
        return perm
    for _ in range(256):
        perm = host_ids[:]
        rng.shuffle(perm)
        if all(h != g for h, g in zip(host_ids, perm)):
            return perm
    return host_ids[1:] + host_ids[:1]


def _seeded_goal_overrides(full_text: str, cfg_name: str, benign_count: int, seed_value: int) -> str:
    block = _scenario_block(full_text, cfg_name)
    wp_re = re.compile(
        r"\*\.host\[(\d+)\]\.mobility\.waypointScript\s*=\s+xml\(\"([^\"]+)\"\)"
    )
    starts: dict[int, tuple[float, float, float]] = {}
    goals: dict[int, tuple[float, float, float]] = {}
    speeds: dict[int, float] = {}
    for host_s, xml in wp_re.findall(block):
        hid = int(host_s)
        if 0 <= hid < benign_count:
            starts[hid] = _parse_xyz("set", xml)
            goals[hid] = _parse_xyz("moveto", xml)
            speeds[hid] = _parse_speed(xml)
    # Derive hotspot from spoofer path when available (set -> first moveto).
    hotspot_xy: tuple[float, float] | None = None
    spoofer_xml: str | None = None
    for host_s, xml in wp_re.findall(block):
        if int(host_s) == benign_count:
            spoofer_xml = xml
            break
    if spoofer_xml is not None:
        s0 = _parse_xyz("set", spoofer_xml)
        s1 = _parse_xyz("moveto", spoofer_xml)
        hotspot_xy = ((s0[0] + s1[0]) * 0.5, (s0[1] + s1[1]) * 0.5)

    host_ids = list(range(benign_count))
    missing = [hid for hid in host_ids if hid not in goals or hid not in starts or hid not in speeds]
    if missing:
        raise SystemExit(f"Missing benign waypoint definitions for hosts: {missing}")

    rng = random.Random(f"{cfg_name}:{seed_value}:goal_shuffle_v2_constrained")
    perm = _choose_constrained_derangement(host_ids, starts, goals, rng, hotspot_xy)

    lines = ["# Seeded benign goal reassignment (same for all variants this seed)"]
    for hid, gid in zip(host_ids, perm):
        mv = _format_movement(hid, starts[hid], goals[gid], speeds[hid])
        lines.append(f"*.host[{hid}].mobility.waypointScript = xml(\"{mv}\")")
    return "\n".join(lines)


goal_overrides = _seeded_goal_overrides(text, scenario, num_benign, seed)
append = f"""

# ---- Auto-added by datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh ----
[Config {aware}]
extends = {scenario}
seed-set = {seed}
*.gcs[0].pyClass = "pymodules.planners.spoofing_aware_gcs.SpoofingAwareGcs"
{goal_overrides}

[Config {aware_instant}]
extends = {scenario}
seed-set = {seed}
*.gcs[0].pyClass = "pymodules.planners.spoofing_aware_gcs.SpoofingAwareGcs"
{goal_overrides}

[Config {trust}]
extends = {scenario}
seed-set = {seed}
*.gcs[0].pyClass = "pymodules.planners.trust_rid_gcs.TrustRidGcs"
*.host[{spoofer_host}].wlan[0].mgmt.pyTxClass = "pymodules.spoofers.position_offset.PositionOffsetSpooferTrustRidCollisionBias"
{goal_overrides}
"""
out_ini.write_text(text + append)
print(f"Wrote {out_ini}")
PY

    if [[ "$DO_CLEAN" == "1" ]]; then
      rm -f "$scen_dir"/*.parquet "$scen_dir"/*.sca || true
      rm -rf "$scen_dir"/results || true
    fi

    run_one "$scenario" "$seed" "$scen_tag" "$scen_dir" "$aware_cfg" "$aware_instant_cfg" "$trust_cfg" &
    while (( $(count_running_worker_jobs) >= PARALLEL )); do
      if ! wait -n; then
        FAILED_RUN_JOBS=$((FAILED_RUN_JOBS + 1))
        PIPELINE_FAILED=1
        echo "[WARN] A background scenario run failed (running total failures: $FAILED_RUN_JOBS). Continuing..."
      fi
      COMPLETED_RUN_JOBS=$((COMPLETED_RUN_JOBS + 1))
      echo "[PROGRESS] phase=running_scenarios completed_jobs=${COMPLETED_RUN_JOBS}/${TOTAL_RUN_JOBS} progress_pct=$(progress_pct_int)"
    done
  done
done

# Heartbeat runs as a background job too; `jobs -pr` includes it, so a naive
# drain loop would block forever on `wait -n` after the last run_one exits.
stop_heartbeat
while (( $(jobs -pr | wc -l) > 0 )); do
  if ! wait -n; then
    FAILED_RUN_JOBS=$((FAILED_RUN_JOBS + 1))
    PIPELINE_FAILED=1
    echo "[WARN] A background scenario run failed (running total failures: $FAILED_RUN_JOBS). Continuing..."
  fi
  COMPLETED_RUN_JOBS=$((COMPLETED_RUN_JOBS + 1))
  echo "[PROGRESS] phase=running_scenarios completed_jobs=${COMPLETED_RUN_JOBS}/${TOTAL_RUN_JOBS} progress_pct=$(progress_pct_int)"
done
start_heartbeat

echo "== Writing combined scalar summary CSV =="
CURRENT_PHASE="summary_csv"
if ! ./scripts/docker-run.sh python3 -m pymodules.analysis.spoofing_batch_metrics \
  "$GEN_DIR" \
  -o "$SUMMARY_CSV"; then
  PIPELINE_FAILED=1
  echo "[WARN] Summary CSV generation failed."
fi

if [[ "$EXPORT_VECTORS" == "1" && "$KEEP_VEC" == "1" ]]; then
  echo "== Exporting GCS vectors (all runs) =="
  CURRENT_PHASE="export_vectors"
  shopt -s nullglob
  vecs=("$GEN_DIR"/*/results/*-#0.vec)
  if [[ ${#vecs[@]} -eq 0 ]]; then
    echo "No .vec files found under $GEN_DIR/*/results; skipping vector export."
  else
    for vec in "${vecs[@]}"; do
      scenedir="$(basename "$(dirname "$(dirname "$vec")")")"
      runbase="$(basename "$vec" .vec)"
      out="$GCS_VEC_DIR/${scenedir}-${runbase}-gcs.csv"
      if ! ./scripts/docker-run.sh opp_scavetool export -F CSV-R -x columnNames=true \
        -f 'type=~"vector" and module=~"*.gcs[*]" and (name=~"*min_benign_spoofer_distance_now_m*" or name=~"*min_benign_spoofer_distance_running_min_m*" or name=~"*spoofer_containment_rate*" or name=~"*nmac_proximity_total*" or name=~"*nmac_benign_spoofer_total*" or name=~"*nmac_spoofer_unsafe_total*" or name=~"*combined_alert*" or name=~"*spoofer_detected*" or name=~"*kf_max_nis*" or name=~"*kf_mean_nis*" or name=~"*kf_nis_host*" or name=~"*mlat_score*" or name=~"*mlat_raw_error*" or name=~"*receiver_count*" or name=~"*mlat_receiver_count*" or name=~"*mlat_skipped_insufficient_receivers*" or name=~"*localization_rmse_m*" or name=~"*unsafe_radius_max_m*" or name=~"*imm_mode_prob_cv*" or name=~"*imm_mode_prob_ca*" or name=~"*imm_nis_cv*" or name=~"*imm_nis_ca*" or name=~"*imm_nis_mix*" or name=~"*imm_est_x_m*" or name=~"*imm_est_y_m*" or name=~"*imm_true_x_m*" or name=~"*imm_true_y_m*" or name=~"*imm_error_norm_m*" or name=~"*imm_nees*")' \
        -o "$out" "$vec"; then
        PIPELINE_FAILED=1
        echo "[WARN] Vector export failed for $vec"
        continue
      fi
      echo "Wrote $out"
    done
  fi
fi

if [[ "$DO_PLOT" == "1" ]]; then
  echo "== Generating charts and distribution tables =="
  CURRENT_PHASE="plotting"
  if ! ./scripts/docker-run.sh python3 datagen/spoofting_aware_trajectory_planning_datagen/plot_batch.py \
    --batch-root "$RUN_ROOT" \
    --plot-profile "$PLOT_PROFILE" \
    --mission-goal-tol-m "$MISSION_GOAL_TOL_M"; then
    PIPELINE_FAILED=1
    echo "[WARN] Chart generation failed."
  else
    echo "== Organizing per-variant chart views =="
    python3 - "$RUN_ROOT/charts" "$VARIANT_DIR_AWARE/charts" "$VARIANT_DIR_INSTANT/charts" "$VARIANT_DIR_TRUST/charts" <<'PY'
from pathlib import Path
import shutil
import sys

charts_root = Path(sys.argv[1])
variant_chart_roots = [Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])]

src_pdfs = charts_root / "pdfs"
src_pngs = charts_root / "pngs"
for vr in variant_chart_roots:
    (vr / "pdfs").mkdir(parents=True, exist_ok=True)
    (vr / "pngs").mkdir(parents=True, exist_ok=True)

if src_pdfs.is_dir():
    for src in sorted(src_pdfs.glob("*.pdf")):
        for vr in variant_chart_roots:
            shutil.copy2(src, vr / "pdfs" / src.name)

if src_pngs.is_dir():
    for src in sorted(src_pngs.glob("*.png")):
        for vr in variant_chart_roots:
            shutil.copy2(src, vr / "pngs" / src.name)
PY
  fi
fi

echo "== Done =="
CURRENT_PHASE="done"
total_elapsed=$(( $(date +%s) - OVERALL_START_EPOCH ))
echo "Total runtime: ${total_elapsed}s"
echo "$total_elapsed" > "$RUN_ROOT/total_runtime_seconds.txt"
echo "Summary:  $SUMMARY_CSV"
echo "Vectors:  $GCS_VEC_DIR"
echo "Charts:   $RUN_ROOT/charts"
echo "Variant folders: $VARIANT_ROOT/{spoofing_aware_trajectory_planning,instant_detect,trustRID}"
echo "Run timing CSV: $RUNTIME_CSV"
if (( FAILED_RUN_JOBS > 0 )); then
  echo "Background run failures: $FAILED_RUN_JOBS"
fi
if (( PIPELINE_FAILED != 0 )); then
  echo "[WARN] Pipeline completed with one or more failures."
  echo "=== BATCH_RUN_FINISHED status=FAILED run_root=${RUN_ROOT} total_elapsed_s=${total_elapsed} failed_jobs=${FAILED_RUN_JOBS} timestamp=$(date -Iseconds) ==="
  exit 1
fi
echo "=== BATCH_RUN_FINISHED status=OK run_root=${RUN_ROOT} total_elapsed_s=${total_elapsed} failed_jobs=${FAILED_RUN_JOBS} timestamp=$(date -Iseconds) ==="
