# Drone Remote ID Network Simulator
This repository contains an [OMNeT++](https://omnetpp.org/) project for discrete event simulation of drone [Remote ID](https://www.ecfr.gov/current/title-14/part-89) networks.
The project makes use of [INET Framework](https://inet.omnetpp.org/) for realistic radio propagation, interference, and MAC-layer dynamics.

## Getting Started
First, install the following dependencies:
- [OMNeT++](https://omnetpp.org/download/)
    - note: follow the instructions to build from source with OSG 3D graphics support, do not use the opp_env installer
- [INET Framework](https://inet.omnetpp.org/Installation.html)
    - note: do not use the opp_env installer, go through the OMNeT++ IDE
- [eigen library](https://gitlab.com/libeigen/eigen/-/releases)
    - download version 5.0.0 and place in OMNeT++ workspace alongside INET Framework

Your OMNeT++ workspace should now contain these directories:
- eigen-5.0.0
- inet4.5

Next, clone this repository and import the contained project into the OMNeT++ IDE:
1. Open the OMNeT++ IDE and choose a workspace directory
    - The default is fine, do not use the directory of this repository as a workspace
2. Open the Import dialog
    - File > Import or right-click in the Project Explorer view
3. Select the "Existing Projects into Workspace" import wizard
3. Select the directory of this repository as the root directory
5. The wizard should indicate that it found just a `uav-rid` project, which should be selected for import
    - Leave all other options unselected
6. After clicking "Finish", a `uav-rid` folder should appear in the Project Explorer view
7. Click on the `uav-rid` folder and navigate to its Properties dialog
    - Project > Properties or right-click it in Project Explorer and select Properties
8. Under "Project References" ensure there is a reference to INET such as `inet4.5`
9. Click into the inet project Properties > OMNeT++ > Project Features and enable `Visualization OSG (3D)`
10. Check that things are working by clicking the play button to "Run basic_uav"
11. In the OMNeT++ Qtenv window that pops up, select the `RandomMobility` config in the "Set Up Inifile Configuration" dialog and click OK
12. The visualization panel should show some UAVs and the simulation should be runnable via the toolbar buttons

## Detection Methods

| Method | Granularity | Description |
|--------|------------|-------------|
| **Kalman Filter (KF)** | Per-RX-event | RSSI-based Tx power estimation; threshold on NIS |
| **Multilateration (MLAT)** | Per-transmission | RSSI triangulation from multiple receivers |
| **MLP** | Per-transmission | Supervised neural network on per-transmission features |

## Quick Start (Docker)

Paths inside the image use **`/usr/uli-net-sim/uav_rid`** as the project root.

### Build the image

```bash
docker build -f Containerfile -t uli-net-sim:latest .
# or: docker compose build
```

### Run with the repo bind-mounted

Python packages come from the image’s **`/opt/uli-venv`** (on `PATH`); you do **not** need a host `.venv` inside the clone.

```bash
# Interactive shell
docker compose run --rm uli-net-sim
# or: ./scripts/docker-run.sh bash

# Rebuild the simulator after C++ changes (inside the container)
./scripts/docker-run.sh ./scripts/build.sh
```

### Batch: spoofing sweep + simulations

Use **`./scripts/docker-run.sh …`** so **`pandas`**, **`pyarrow`**, and OMNeT-related paths match the image. If you run **`python3 datagen/run_batch.py` directly on the host**, install **`pip install pandas pyarrow`** first (and use a working OMNeT env for **`scripts/run.sh`**).

```bash
# 1) Generate seeded INI bundles (writes under simulations/.../sweeps/generated/)
./scripts/docker-run.sh python3 datagen/generate_spoofing_sweep.py \
    --layout circle8 --seed-range 0 9 \
    --output-dir simulations/spoofing_aware_with_planning/sweeps/generated

# 2) Run all leaf configs under that tree (Aware + TrustRid per seed)
./scripts/docker-run.sh python3 datagen/run_batch.py \
    simulations/spoofing_aware_with_planning/sweeps/generated/ \
    --parallel 4

# 3) Summarize NMAC scalars from copied *.sca next to parquet
./scripts/docker-run.sh python3 -m pymodules.analysis.spoofing_batch_metrics \
    simulations/spoofing_aware_with_planning/sweeps/generated/ \
    -o simulations/spoofing_aware_with_planning/sweeps/summary.csv
```

### In-container paths (no Docker)

```bash
cd /usr/uli-net-sim/uav_rid
./scripts/build.sh

# Generate a small dataset
./datagen/generate_dataset.sh --num-hosts 5 --scenario-variants 10 --enable-spoofer

# Train detectors and score test set
.venv/bin/python -m evaluations.unified_eval train \
    --train-dir datasets/my_dataset/train -o evaluations/results/

.venv/bin/python -m evaluations.unified_eval score \
    --train-dir datasets/my_dataset/train \
    --test-dir datasets/my_dataset/test -o evaluations/results/

# Analyze results (iterate on thresholds/plots)
.venv/bin/python -m evaluations.unified_eval analyze \
    --scores-dir evaluations/results/ -o evaluations/results/

# Run regression tests
.venv/bin/pytest tests/ -v
```

## Project Structure

- **`src/`** - C++ simulation modules (detectors, spoofers, beacon management)
- **`simulations/`** - OMNeT++ scenario configurations (.ned, .ini, .anf)
- **`datagen/`** - Dataset generation pipeline (corridor/building/trajectory generators)
- **`scripts/`** - Build, environment, and utility scripts
- **`evaluations/`** - Detection evaluation framework (train/score/analyze CLI)
- **`tests/`** - Regression tests (pytest, hash-based)
