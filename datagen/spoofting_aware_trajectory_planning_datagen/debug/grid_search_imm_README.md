IMM grid search (remote-ready)

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
