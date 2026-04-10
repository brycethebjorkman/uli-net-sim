# IMM Grid Search Runbook (Remote-Ready)

This guide is for reproducible IMM tuning runs using:

- `datagen/spoofting_aware_trajectory_planning_datagen/debug/grid_search_imm.py`
- `datagen/spoofting_aware_trajectory_planning_datagen/debug/plot_grid_search_imm.py`

---

## 1) Build Docker image (once)

From repo root:

```bash
docker build -f Containerfile -t uli-net-sim:latest .
```

You do not need to rebuild in every terminal tab. Use `--skip-build` after image exists.

---

## 2) Launch grid search in tmux (disconnect-safe)

```bash
cd "/Users/webb/Library/CloudStorage/OneDrive-Vanderbilt/Vanderbilt/Ward_Lab/uli-net-sim"
mkdir -p logs
tmux new -d -s imm_grid "cd ~/uli-net-sim && LOG=logs/imm_grid_\$(date +%Y%m%d_%H%M%S).log && python3 datagen/spoofting_aware_trajectory_planning_datagen/debug/grid_search_imm.py --paper-scenarios --include-steepz --seeds 0:9 --parallel 8 --batch-root simulations/spoofing_aware_with_planning/batches_imm_grid --results-csv simulations/spoofing_aware_with_planning/batches_imm_grid/imm_grid_search_results.csv --run-prefix imm_p8 --resume-ok --trial-timeout-sec 7200 --trial-retries 1 --heartbeat-sec 60 --shuffle --max-trials 200 --skip-build --top-k 20 > \"\$LOG\" 2>&1"
```

### Recommended overnight command (comprehensive)

Use this for an unattended broad IMM search:

```bash
cd "/Users/webb/Library/CloudStorage/OneDrive-Vanderbilt/Vanderbilt/Ward_Lab/uli-net-sim"
mkdir -p logs simulations/spoofing_aware_with_planning/batches_imm_grid
tmux new -d -s imm_grid_overnight "cd ~/uli-net-sim && LOG=logs/imm_grid_overnight_\$(date +%Y%m%d_%H%M%S).log && python3 datagen/spoofting_aware_trajectory_planning_datagen/debug/grid_search_imm.py --paper-scenarios --include-steepz --seeds 0:6 --parallel 8 --batch-root simulations/spoofing_aware_with_planning/batches_imm_grid --results-csv simulations/spoofing_aware_with_planning/batches_imm_grid/imm_grid_search_results.csv --run-prefix imm_overnight_p8 --preset-grid overnight --resume-ok --shuffle --shuffle-seed 20260410 --trial-timeout-sec 5400 --trial-retries 1 --heartbeat-sec 60 --estimate-min-per-trial 25 --max-trials 700 --skip-build --top-k 25 > \"\$LOG\" 2>&1"
```

Notes:

- `--preset-grid overnight` enables a broad search space.
- `--max-trials 700` gives a deeper overnight run (raise/lower for runtime control).
- `--resume-ok` makes reruns safe; successful combos are skipped.

### 12-hour budget command (based on observed pace)

Your recent run showed about 15 minutes/trial, so this targets roughly a 12-hour wall time:

```bash
cd "/Users/webb/Library/CloudStorage/OneDrive-Vanderbilt/Vanderbilt/Ward_Lab/uli-net-sim"
mkdir -p logs simulations/spoofing_aware_with_planning/batches_imm_grid
tmux new -d -s imm_grid_12h "cd ~/uli-net-sim && LOG=logs/imm_grid_12h_\$(date +%Y%m%d_%H%M%S).log && python3 datagen/spoofting_aware_trajectory_planning_datagen/debug/grid_search_imm.py --paper-scenarios --include-steepz --seeds 0:6 --parallel 8 --batch-root simulations/spoofing_aware_with_planning/batches_imm_grid --results-csv simulations/spoofing_aware_with_planning/batches_imm_grid/imm_grid_search_results.csv --run-prefix imm_12h_p8 --preset-grid overnight --resume-ok --shuffle --shuffle-seed 20260410 --trial-timeout-sec 5400 --trial-retries 1 --heartbeat-sec 60 --estimate-min-per-trial 15 --target-runtime-hours 12 --skip-build --top-k 25 > \"\$LOG\" 2>&1"
```

---

## 3) Monitor / reconnect

Check sessions:

```bash
tmux ls
```

Attach:

```bash
tmux attach -t imm_grid
```

Detach without stopping run: `Ctrl+b`, then `d`.

Tail latest log:

```bash
tail -f "$(ls -t logs/imm_grid_*.log | head -n 1)"
```

Progress checks:

```bash
wc -l simulations/spoofing_aware_with_planning/batches_imm_grid/imm_grid_search_results.csv 2>/dev/null
ls -lt simulations/spoofing_aware_with_planning/batches_imm_grid | head
```

Percent-complete checks from log:

```bash
LOG_FILE="$(ls -t logs/imm_grid_*.log | head -n 1)"
rg -n "overall_progress=.*\\([0-9]+\\.[0-9]+%\\)|IMM_GRID_SEARCH_FINISHED" "$LOG_FILE" | tail -n 20
```

---

## 4) What gets written

- Results CSV:
  - `simulations/spoofing_aware_with_planning/batches_imm_grid/imm_grid_search_results.csv`
- Per-trial logs:
  - `simulations/spoofing_aware_with_planning/batches_imm_grid/<run-prefix>_logs/`
- Markdown summary:
  - `simulations/spoofing_aware_with_planning/batches_imm_grid/imm_grid_search_summary.md`

---

## 5) Plot grid-search results

```bash
python3 datagen/spoofting_aware_trajectory_planning_datagen/debug/plot_grid_search_imm.py \
  --results-csv simulations/spoofing_aware_with_planning/batches_imm_grid/imm_grid_search_results.csv
```

Default plot output directory:

- `simulations/spoofing_aware_with_planning/batches_imm_grid/imm_grid_plots/`

Key plot files:

- `leaderboard_top_score.png`
- `containment_vs_rmse_scatter.png`
- `consistency_nees95_vs_nis95.png`
- `parameter_sensitivity_spearman_score.png` (if param columns exist)
- `pareto_containment_vs_rmse.png`
- `pareto_runs.csv`

---

## 6) Useful tuning flags

- `--preset-grid {single,quick,overnight}` select built-in sweep profile
- `--init-mode-cv`, `--p-cv-stay`, `--p-ca-stay`, `--cv-*-noise`, `--ca-*-noise` override preset dimensions with comma-separated values
- `--resume-ok` skip successful combos already in CSV
- `--trial-timeout-sec N` per-trial timeout
- `--trial-retries N` retry failed trials
- `--heartbeat-sec N` periodic heartbeat lines during long trials (`0` disables)
- `--max-trials N` cap sweep size
- `--target-runtime-hours H` auto-size trial count to hit a runtime budget
- `--shuffle --shuffle-seed N` randomize combo order
- `--weight-*` adjust objective weights
- `--min-containment X` mark trials as `low_containment` when below threshold
- `--estimate-min-per-trial N` improve startup wall-time estimate printout

Preset defaults:

- `single`: one baseline combo (smoke test)
- `quick`: medium sweep (auto-capped to 80 unless `--max-trials` is set)
- `overnight`: broad sweep (auto-capped to 500 unless `--max-trials` is set)

