#!/bin/bash
set -euo pipefail
export PYTHONUNBUFFERED=1
cd /usr/uli-net-sim/uav_rid

echo "=== Step 1/7: Generate manifest ==="
python3 datagen/generate_manifest.py \
    --grid-size "500-1000" --num-hosts "6-12" --sim-time "300-570" \
    --num-ew "4-6" --num-ns "4-6" \
    --corridor-width "10-50" --corridor-spacing "60-120" \
    --num-buildings "10-20" --building-height "10-100" \
    --speed "5-15" --altitude "30-100" \
    --tx-power "10-25" --beacon-interval "0.75-1.0" --beacon-offset "0-0.5" \
    --param-variants 25 --corridor-variants 2 \
    --building-variants 2 --trajectory-variants 4 \
    --scenario-variants 6 \
    --enable-spoofer --spoofer-type snow_plow \
    --seed 42 \
    -o datasets/snowplow26/manifest.json

echo "=== Step 2/7: Materialize artifacts + INIs ==="
python3 datagen/generate_scenario.py datasets/snowplow26/manifest.json

echo "=== Step 3/7: Run simulations (parallel) ==="
python3 datagen/run_batch.py datasets/snowplow26/urbanenv/ \
    --configs ScenarioOpenSpace ScenarioWithBuildings --parallel 0

echo "=== Step 4/7: Split train/test ==="
python3 datagen/split_dataset.py datasets/snowplow26

echo "=== Step 5/7: Train ==="
.venv/bin/python -m evaluations.unified_eval train \
    --train-dir datasets/snowplow26/train \
    -o evaluations/results/snowplow26/

echo "=== Step 6/7: Score ==="
.venv/bin/python -m evaluations.unified_eval score \
    --train-dir datasets/snowplow26/train \
    --test-dir datasets/snowplow26/test \
    -o evaluations/results/snowplow26/

echo "=== Step 7/7: Analyze ==="
.venv/bin/python -m evaluations.unified_eval analyze \
    --scores-dir evaluations/results/snowplow26/ \
    -o evaluations/results/snowplow26/

echo "=== Done ==="
