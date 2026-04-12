# MDP Grid Search (12x1) Quick Run

This folder contains:

- `datagen/spoofting_aware_trajectory_planning_datagen/debug MDP/grid_search_mdp_nmac.py`

The script grid-searches MDP constants in `pymodules/controllers/mdp_trajectory_planner.py` and runs spoofing-aware batch simulations against `Scenario_Hub_12x1`.

## Build image (once)

From repo root:

```bash
docker build -f Containerfile -t uli-net-sim:latest .
```

## Quick run: 12x1 smoke test (single trial)

Use this first to verify the full pipeline end-to-end with minimal runtime.

```bash
python3 "datagen/spoofting_aware_trajectory_planning_datagen/debug MDP/grid_search_mdp_nmac.py" \
  --scenario-config Scenario_Hub_12x1 \
  --seeds 0 \
  --parallel 1 \
  --batch-root simulations/spoofing_aware_with_planning/batches_mdp_grid_12x1_smoke \
  --results-csv simulations/spoofing_aware_with_planning/batches_mdp_grid_12x1_smoke/mdp_grid_search_results.csv \
  --max-trials 1 \
  --skip-build
```

## Quick run: 12x1 small sweep

This is still quick, but explores a few combinations.

```bash
python3 "datagen/spoofting_aware_trajectory_planning_datagen/debug MDP/grid_search_mdp_nmac.py" \
  --scenario-config Scenario_Hub_12x1 \
  --seeds 0:2 \
  --parallel 4 \
  --batch-root simulations/spoofing_aware_with_planning/batches_mdp_grid_12x1_quick \
  --results-csv simulations/spoofing_aware_with_planning/batches_mdp_grid_12x1_quick/mdp_grid_search_results.csv \
  --goal-reward 300,500 \
  --agent-reward 6000,9000 \
  --spoofer-reward 6000,9000 \
  --ellipsoid-margin 0.8,1.0 \
  --max-trials 12 \
  --skip-build
```

## Outputs

- Results CSV:
  - `simulations/spoofing_aware_with_planning/batches_mdp_grid_12x1_*/mdp_grid_search_results.csv`
- Per-run batch outputs:
  - `simulations/spoofing_aware_with_planning/batches_mdp_grid_12x1_*/0001/`, `0002/`, ...

## Notes

- The script restores the original `mdp_trajectory_planner.py` constants automatically at exit.
- Add `--dry-run` to verify parameter combinations without launching simulation runs.
- Add `--fail-fast` to stop immediately on first failed trial.
