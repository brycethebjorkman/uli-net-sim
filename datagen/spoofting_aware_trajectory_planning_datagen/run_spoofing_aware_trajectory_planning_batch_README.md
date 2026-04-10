# Spoofing-Aware Trajectory Planning Batch Runbook

This runbook covers the end-to-end workflow for running spoofing-aware trajectory planning batches.

It is centered on:

- `datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh`
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
./datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh \
  --scenario-config Scenario_Corners_4x1 \
  --seeds 0:29 \
  --parallel 0
```

Paper scenario suite:

```bash
./datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh \
  --paper-scenarios \
  --seeds 0:29 \
  --parallel 0
```

Paper suite plus `Scenario_SteepZ_8x1`:

```bash
./datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh \
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
./datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh --paper-scenarios --seeds 0:29 --parallel 0 | tee "logs/batch_run_$(date +%Y%m%d_%H%M%S).log"
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
nohup ./datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh \
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
./datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh --help
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

---

## 9) IMM grid search (remote-ready)

Use the debug grid search tool to sweep IMM parameters with resume/retry/logging support:

`datagen/spoofting_aware_trajectory_planning_datagen/debug/grid_search_imm.py`

Example remote run:

```bash
python3 datagen/spoofting_aware_trajectory_planning_datagen/debug/grid_search_imm.py \
  --paper-scenarios \
  --include-steepz \
  --seeds 0:9 \
  --parallel 4 \
  --resume-ok \
  --trial-timeout-sec 7200 \
  --trial-retries 1 \
  --shuffle \
  --max-trials 200 \
  --run-prefix imm_remote
```

What this writes:

- results CSV (default): `simulations/spoofing_aware_with_planning/batches/imm_grid_search_results.csv`
- per-trial logs (default): `simulations/spoofing_aware_with_planning/batches/<run-prefix>_logs/`
- markdown summary (default): `simulations/spoofing_aware_with_planning/batches/imm_grid_search_summary.md`

Useful options:

- `--results-csv PATH` custom results file
- `--summary-md PATH` custom markdown summary path
- `--top-k N` number of top runs printed/summarized
- `--fail-fast` stop on first failed/timeout trial
- `--min-containment X` mark low-containment trials with status `low_containment`
- `--weight-*` tune objective scoring weights

---

## 10) Plot IMM grid-search results

Use the companion plotting script:

`datagen/spoofting_aware_trajectory_planning_datagen/debug/plot_grid_search_imm.py`

Example:

```bash
python3 datagen/spoofting_aware_trajectory_planning_datagen/debug/plot_grid_search_imm.py \
  --results-csv simulations/spoofing_aware_with_planning/batches/imm_grid_search_results.csv
```

Default output directory:

- `simulations/spoofing_aware_with_planning/batches/imm_grid_plots/`

Key outputs:

- `leaderboard_top_score.png`
- `containment_vs_rmse_scatter.png`
- `consistency_nees95_vs_nis95.png`
- `parameter_sensitivity_spearman_score.png` (when parameter columns exist)
- `pareto_containment_vs_rmse.png`
- `pareto_runs.csv`

---

## 11) Suggested remote workflow

1. Launch grid search in `tmux`.
2. Reattach periodically and monitor latest rows in results CSV.
3. Generate/update plots from the same CSV.
4. Pick candidates from Pareto front + top score list.

Minimal command sequence:

```bash
tmux new -s imm_grid
python3 datagen/spoofting_aware_trajectory_planning_datagen/debug/grid_search_imm.py --paper-scenarios --seeds 0:9 --parallel 4 --resume-ok --shuffle --max-trials 200
python3 datagen/spoofting_aware_trajectory_planning_datagen/debug/plot_grid_search_imm.py --results-csv simulations/spoofing_aware_with_planning/batches/imm_grid_search_results.csv
```
