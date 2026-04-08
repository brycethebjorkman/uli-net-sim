# Datagen Sweep Runbook (Start to Finish)

This runbook captures the end-to-end sweep workflow used in this project:

- Generate seeded spoofing scenarios (`Aware` and `TrustRid`)
- Run all simulations in batch
- Convert vectors to Parquet
- Summarize `.sca` scalar metrics into `summary.csv`

## 1) Build Docker image

From repo root:

```bash
docker build -f Containerfile -t uli-net-sim:latest .
```

This image includes:

- OMNeT++ + INET build
- Python deps (`pandas`, `pyarrow`, etc.)
- `opp_scavetool` available on `PATH` for `vec2parquet`

## 2) Generate sweep directories

Example `circle8` seeds 0..9:

```bash
./scripts/docker-run.sh python3 datagen/generate_spoofing_sweep.py \
  --layout circle8 --seed-range 0 9 \
  --output-dir simulations/spoofing_aware_with_planning/sweeps/generated
```

Expected output structure:

- `simulations/.../sweeps/generated/circle8_s00000/omnetpp.ini`
- `simulations/.../sweeps/generated/circle8_s00000/manifest.json`
- ...

## 3) Run all scenarios (Aware + TrustRid per seed)

```bash
./scripts/docker-run.sh python3 datagen/run_batch.py \
  simulations/spoofing_aware_with_planning/sweeps/generated \
  --parallel 4
```

Notes:

- Use `--parallel 0` to auto-detect CPU count.
- Existing Parquet files are skipped.
- `.sca` files are copied beside Parquet for summary analysis.

## 4) Build scalar summary CSV

```bash
./scripts/docker-run.sh python3 -m pymodules.analysis.spoofing_batch_metrics \
  simulations/spoofing_aware_with_planning/sweeps/generated \
  -o simulations/spoofing_aware_with_planning/sweeps/summary.csv
```

## 5) Interpret the columns correctly

`summary.csv` includes (per seed):

- `nmac_proximity_*`: benign-vs-benign proximity NMAC entry counts (`< 10m`)
- `nmac_benign_spoofer_*`: benign-vs-spoofer proximity NMAC entry counts (`< 10m`)
- `nmac_spoofer_unsafe_*`: benign entries into the published unsafe region
- `min_benign_spoofer_distance_*_m`: minimum benign-to-spoofer distance over run (meters)
- `spoofer_containment_rate_*`: fraction of checks where unsafe region contains true spoofer

Important:

- `TrustRid` intentionally does **not** publish unsafe regions, so
  `nmac_spoofer_unsafe_trust_rid` and `spoofer_containment_rate_trust_rid` are expected
  to be `0`/empty.
- Compare `nmac_proximity_trust_rid` and `nmac_benign_spoofer_trust_rid` for TrustRid
  collision-like proximity behavior.
- For your safety claim, compare:
  - `nmac_benign_spoofer_trust_rid` vs `nmac_benign_spoofer_aware` (higher is worse),
  - `min_benign_spoofer_distance_trust_rid_m` vs `..._aware_m` (lower is worse),
  - `spoofer_containment_rate_aware` (higher is better; TrustRid has no unsafe region).

## 6) Quick rerun loop

After code changes:

```bash
docker build -f Containerfile -t uli-net-sim:latest .
./scripts/docker-run.sh python3 datagen/run_batch.py simulations/spoofing_aware_with_planning/sweeps/generated --parallel 4
./scripts/docker-run.sh python3 -m pymodules.analysis.spoofing_batch_metrics simulations/spoofing_aware_with_planning/sweeps/generated -o simulations/spoofing_aware_with_planning/sweeps/summary.csv
```

## 7) (Optional) quick chart prep

You can quickly inspect averages across seeds:

```bash
./scripts/docker-run.sh python3 - <<'PY'
import pandas as pd
df = pd.read_csv("simulations/spoofing_aware_with_planning/sweeps/summary.csv")
cols = [
    "nmac_proximity_aware", "nmac_proximity_trust_rid",
    "nmac_benign_spoofer_aware", "nmac_benign_spoofer_trust_rid",
    "nmac_spoofer_unsafe_aware", "nmac_spoofer_unsafe_trust_rid",
    "min_benign_spoofer_distance_aware_m", "min_benign_spoofer_distance_trust_rid_m",
    "spoofer_containment_rate_aware",
]
print(df[cols].mean(numeric_only=True))
PY
```

This is a good first step before making publication plots.

## 8) Through-time chart data (per tick)

To chart min benign-to-spoofer distance over time, keep `.vec` files and export
GCS vectors:

```bash
./scripts/docker-run.sh python3 datagen/run_batch.py \
  simulations/spoofing_aware_with_planning/sweeps/generated \
  --parallel 4 --keep-vec
```

Then export one run's GCS time series from OMNeT vectors:

```bash
./scripts/docker-run.sh opp_scavetool export -F CSV-R -x columnNames=true \
  -f 'type=~"vector" and module=~"*.gcs[0]" and (name=~"min_benign_spoofer_distance_now_m" or name=~"min_benign_spoofer_distance_running_min_m")' \
  -o simulations/spoofing_aware_with_planning/sweeps/generated/circle8_s00000/gcs_distance_timeseries.csv \
  simulations/spoofing_aware_with_planning/sweeps/generated/circle8_s00000/results/*-#0.vec
```

This CSV can be plotted directly (time on x-axis, distance on y-axis) for Aware
vs TrustRid runs.

## 9) One-command executable pipeline (scenario input)

Run everything (build optional, compare Aware vs TrustRid, summary, vector export,
charts) with a single script:

```bash
./datagen/run_compare_pipeline.sh --scenario-config Scenario_Corners_4x1
```

Common options:

```bash
# Skip docker build, auto-parallel, keep old artifacts
./datagen/run_compare_pipeline.sh \
  --scenario-config Scenario_Corners_4x1 \
  --skip-build --parallel 0 --no-clean

# Use a different scenario config from the same base INI
./datagen/run_compare_pipeline.sh --scenario-config Scenario_Hub_4x1
```

See help:

```bash
./datagen/run_compare_pipeline.sh --help
```
