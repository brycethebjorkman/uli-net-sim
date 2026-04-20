# Paper Batch Runbook (DepotCity 30-seed)

This is the default paper workflow for:

- `datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh`
- output root: `simulations/spoofing_aware_with_planning/batchesPaperExact0005Commit/`
- scenarios: `Scenario_DepotCity_{4x1,8x1,12x1,16x1}`
- seeds: `0:29`
- variants per run: `Aware`, `AwareInstantDetect@5s`, `TrustRid`

The runner now defaults to this setup when no scenario flags are provided.

## One-command default run

```bash
./datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh --parallel 8 --skip-build
```

This creates the next run directory:

`simulations/spoofing_aware_with_planning/batchesPaperExact0005Commit/0001` (then `0002`, etc.).

## Recommended tmux run (SSH-safe)

### Start detached

```bash
cd ~/uli-net-sim
mkdir -p logs
LOG="logs/paper_batch_$(date +%Y%m%d_%H%M%S).log"
tmux new -d -s paper_batch \
  "cd ~/uli-net-sim && ./datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh --parallel 8 --skip-build --heartbeat-sec 60 | tee \"$LOG\""
echo "tmux session: paper_batch"
echo "log file: $LOG"
```

### Check progress

```bash
tmux attach -t paper_batch
```

Detach without stopping: `Ctrl+b`, then `d`

Quick log tail:

```bash
tail -f logs/paper_batch_*.log
```

## Completion checks

```bash
RUN_ROOT="simulations/spoofing_aware_with_planning/batchesPaperExact0005Commit/<run-id>"
test -f "$RUN_ROOT/summary.csv"
test -f "$RUN_ROOT/run_timing.csv"
test -f "$RUN_ROOT/total_runtime_seconds.txt"
```

Expected paper artifacts:

- `$RUN_ROOT/charts/keycharts/table_ii_nmac_summary_statistics.png`
- `$RUN_ROOT/charts/keycharts/table_iii_runtime_mean_std_per_scenario_seconds.png`
- `$RUN_ROOT/variants/paper_instant_detect_vs_trustRID/charts/pngs/table_ii_safety_summary_by_agent_count.png`
- `$RUN_ROOT/variants/paper_instant_detect_vs_trustRID/charts/pngs/table_iii_spoofer_localization_by_agent_count.png`

## Useful overrides

- Custom batch root: `--batch-root <path>`
- Custom scenarios: `--scenario-config ...` or `--scenario-configs ...`
- Custom seeds: `--seeds 0:9` or `--seeds 0,1,2`
- Full diagnostics plots: `--plot-profile full`
- Skip plots: `--no-plot`

