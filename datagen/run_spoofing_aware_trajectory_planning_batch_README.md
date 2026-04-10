# Spoofing-Aware Trajectory Planning Batch Runbook

This runbook covers the end-to-end workflow for running spoofing-aware trajectory planning batches.

It is centered on:

- `datagen/run_spoofing_aware_trajectory_planning_batch.sh`
- output root `simulations/spoofing_aware_with_planning/batches/`
- log files under `logs/`

---

## 1) Build Docker image

From repo root:

```bash
docker build -f Containerfile -t uli-net-sim:latest .
```

---

## 2) Start a batch run (single command)

Single scenario:

```bash
./datagen/run_spoofing_aware_trajectory_planning_batch.sh \
  --scenario-config Scenario_Corners_4x1 \
  --seeds 0:29 \
  --parallel 0
```

Paper scenario suite:

```bash
./datagen/run_spoofing_aware_trajectory_planning_batch.sh \
  --paper-scenarios \
  --seeds 0:29 \
  --parallel 0
```

Paper suite plus `Scenario_SteepZ_8x1`:

```bash
./datagen/run_spoofing_aware_trajectory_planning_batch.sh \
  --paper-scenarios \
  --include-steepz \
  --seeds 0:29 \
  --parallel 0
```

Notes:

- Batch runs are auto-numbered (for example `0001`, `0002`, ...).
- Output is written under `simulations/spoofing_aware_with_planning/batches/<run-id>/`.

---

## 3) Output structure

Each run writes:

- `generated/` - per scenario-seed generated INI + simulation artifacts
- `summary.csv` - paired Aware vs TrustRID scalar summary
- `gcs_vectors/` - exported vector CSVs (if enabled)
- `charts/` - summary and timeseries plots/tables
- `run_timing.csv` - wall-clock timings per scenario-seed pair
- `total_runtime_seconds.txt` - total batch runtime

---

## 4) Continue after SSH disconnect

Use one of these approaches.

### Option A: `tmux` (recommended)

```bash
tmux new -s spoof_batch
./datagen/run_spoofing_aware_trajectory_planning_batch.sh --paper-scenarios --seeds 0:29 --parallel 0 | tee "logs/batch_run_$(date +%Y%m%d_%H%M%S).log"
```

Detach without stopping run: `Ctrl+b`, then `d`

Reattach later:

```bash
tmux attach -t spoof_batch
```

### Option B: `nohup` + background

```bash
mkdir -p logs
LOG_FILE="logs/batch_run_$(date +%Y%m%d_%H%M%S).log"
nohup ./datagen/run_spoofing_aware_trajectory_planning_batch.sh \
  --paper-scenarios --seeds 0:29 --parallel 0 \
  > "$LOG_FILE" 2>&1 &
echo "PID=$! LOG=$LOG_FILE"
```

Follow progress:

```bash
tail -f "$LOG_FILE"
```

---

## 5) Resume and rerun behavior

- Each invocation creates the next numbered run directory (`0001`, `0002`, ...).
- To continue long runs after SSH disconnect, use `tmux` or `nohup` (Section 4).
- If a run is interrupted and not running in a persistent session, start again to create a new run ID.

---

## 6) Logs reporting (`logs/`)

Create structured report snippets from a batch log:

```bash
LOG_FILE="logs/<your-log-file>.log"
```

Errors and warnings:

```bash
rg -n "ERROR|Error|\\[WARN\\]|Traceback" "$LOG_FILE"
```

Run-level completion lines:

```bash
rg -n "^== Completed .* in [0-9]+s ==" "$LOG_FILE"
```

Final summary block:

```bash
rg -n "^== Done ==|^Total runtime:|^Summary:|^Vectors:|^Charts:|^Run timing CSV:" "$LOG_FILE"
```

Count failed background runs:

```bash
rg -n "^Background run failures:" "$LOG_FILE"
```

---

## 7) Useful options

```bash
./datagen/run_spoofing_aware_trajectory_planning_batch.sh --help
```

Common toggles:

- `--skip-build` skip Docker rebuild
- `--no-export-vectors` skip GCS vector export
- `--no-plot` skip chart generation
- `--no-keep-vec` do not retain `.vec` files

---

## 8) Quick sanity checks after completion

```bash
RUN_ROOT="simulations/spoofing_aware_with_planning/batches/<run-id>"
test -f "$RUN_ROOT/summary.csv"
test -f "$RUN_ROOT/run_timing.csv"
test -f "$RUN_ROOT/total_runtime_seconds.txt"
```

Optional quick data check:

```bash
python3 - <<'PY'
import pandas as pd
from pathlib import Path
run_root = Path("simulations/spoofing_aware_with_planning/batches/<run-id>")
df = pd.read_csv(run_root / "summary.csv")
print(df.shape)
print(df.columns[:8].tolist())
PY
```
