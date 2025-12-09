# Remote ID Spoofing Detection - Data Generation

## Overview

This pipeline generates datasets to evaluate Remote ID spoofing detection methods:

1. **Kalman Filter-based detection** - Threshold on KF state using RSSI to estimate transmission power
2. **Multilateration-based detection** - Multilateration using RSSI from multiple receivers
3. **Machine learning approaches** - Supervised learning on timeseries features

The pipeline produces CSV files containing timeseries data from OMNeT++ simulations with:
- **Transmission events**: Position, velocity, transmission power
- **Reception events**: Position, velocity, RSSI, Kalman Filter state estimates

### Scenario Parameters

Varied per scenario:
- Number of hosts and spoofers
- Velocity and trajectories (random waypoints on grid)
- Transmission power
- Beacon interval
- Physical environment (with/without buildings)

## Quick Start

The data generation pipeline needs to run inside a container built from the `Containerfile`.

### Build the Container

```bash
# From your host workspace directory containing the Containerfile
docker build -t uav-rid -f Containerfile .
```

### Run the Container

```bash
# Mount workspace into the container
docker run -it --rm -v .:/usr/uli-net-sim/uav_rid uav-rid /bin/bash
```

### Build the Project (Inside Container)

```bash
cd /usr/uli-net-sim/uav_rid
. container/setenv
./container/build.sh
```

### Generate Datasets (Inside Container)

The `generate_dataset.sh` script supports two modes: `random_waypoints` and `urbanenv`.

#### Random Waypoints Mode (original)

```bash
# Test: 3 scenarios with 5 hosts (1 spoofer)
./container/generate_dataset.sh random_waypoints -n 3 -h 5 -s 1

# Baseline: 20 scenarios without spoofers
./container/generate_dataset.sh random_waypoints -n 20 -c RandomWaypoints5Host -h 5 -s 0 -o datasets/baseline

# Spoofing: 50 scenarios with 1 spoofer
./container/generate_dataset.sh random_waypoints -n 50 -h 5 -s 1 -o datasets/spoofing_1spoofer

# Dynamic trajectory spoofing (spoofer claims ghost's position)
./container/generate_dataset.sh random_waypoints -n 50 -c RandomWaypoints4Host1Ghost1DynSpoofer -h 6 -s 1 -o datasets/dynamic_spoofer
```

#### Urban Environment Mode (new)

Generates corridor-constrained scenarios with buildings. Supports hierarchical branching for diverse datasets.

```bash
# Simple: 4 scenarios varying radio params
./container/generate_dataset.sh urbanenv --num-hosts 5 --scenario-variants 4

# With buildings
./container/generate_dataset.sh urbanenv --num-hosts 5 --num-buildings 20 --sim-time 300 --scenario-variants 10

# Maximum diversity with branching
./container/generate_dataset.sh urbanenv \
    --grid-size "400-800" \
    --num-hosts "3-8" \
    --param-variants 2 \
    --corridor-variants 3 \
    --building-variants 2 \
    --trajectory-variants 2 \
    --scenario-variants 5

# With spoofer (1 ghost + 1 dynamic trajectory spoofer)
./container/generate_dataset.sh urbanenv \
    --num-hosts 6 \
    --enable-spoofer \
    --scenario-variants 10
```

Output files are written to `datasets/` which is visible on the host via the mount.

## Pipeline Components

### 1. Trajectory Generation (`src/utils/random_waypoints.py`)

Generates random waypoint-based trajectories on a grid for TurtleMobility.

```bash
python3 src/utils/random_waypoints.py \
    --out waypoints.xml \
    --hosts 5 \
    --spoofer-hosts 1 \
    --waypoints 10 \
    --grid-size 1000 \
    --speed 5-15 \
    --altitude 30-100 \
    --seed 42
```

### 2. Simulation Configuration (`simulations/random_waypoints/omnetpp.ini`)

Available configs:
- `RandomWaypoints3Host` - 3 honest drones
- `RandomWaypoints5Host` - 5 honest drones
- `RandomWaypoints5Host1Spoofer` - 4 honest + 1 static location spoofer
- `RandomWaypoints10Host2Spoofer` - 8 honest + 2 static location spoofers
- `RandomWaypoints4Host1Ghost1DynSpoofer` - 4 honest + 1 ghost (silent) + 1 dynamic trajectory spoofer

Randomized parameters:
- Beacon interval: uniform(0.25s, 0.75s)
- Transmission power: uniform(10dBm, 16dBm)
- Startup jitter: uniform(0ms, 100ms)

### 3. Vector to CSV Conversion (`container/vec2csv.py`)

Converts OMNeT++ .vec files to CSV format with one row per event.

```bash
python3 vec2csv.py results/scenario.vec -o output.csv
```

### 4. End-to-End Pipeline (`container/generate_dataset.sh`)

Supports two modes: `random_waypoints` and `urbanenv`.

#### Random Waypoints Mode Options
```
-n NUM        Number of scenario repetitions (default: 5)
-c CONFIG     OMNeT++ config name (default: RandomWaypoints5Host1Spoofer)
-h HOSTS      Number of hosts (default: 5)
-s SPOOFERS   Number of spoofer hosts (default: 1)
-w WAYPOINTS  Waypoints per host (default: 15)
-g SIZE       Grid size in meters (default: 1000)
-r RANGE      Speed range as 'min-max' (default: 5-15)
-a RANGE      Altitude range as 'min-max' (default: 30-100)
-o DIR        Output directory (default: $PROJ_DIR/datasets)
--seed NUM    Starting seed (default: 42)
```

#### Urban Environment Mode Options
```
Parameter Ranges (use 'min-max' for ranges, or single value):
--grid-size RANGE         Grid size in meters (default: 400)
--num-hosts RANGE         Number of hosts (default: 5)
--sim-time RANGE          Simulation time in seconds (default: 300)

Corridor Parameters:
--num-ew RANGE            Number of east-west corridors (default: 2)
--num-ns RANGE            Number of north-south corridors (default: 2)
--corridor-width RANGE    Corridor width in meters (default: 20)
--corridor-spacing RANGE  Corridor spacing in meters (default: 120)

Building Parameters:
--num-buildings RANGE     Number of buildings, 0 for none (default: 20)
--building-height RANGE   Building height range (default: 60-150)

Trajectory Parameters:
--speed RANGE             UAV speed in m/s (default: 5-15)
--altitude RANGE          UAV altitude in m (default: 30-100)

Radio Parameters:
--tx-power RANGE          TX power in dBm (default: 10-16)
--beacon-interval RANGE   Beacon interval in s (default: 0.25-0.75)
--beacon-offset RANGE     Beacon offset in s (default: 0-0.1)
--background-noise dBm    Background noise power (default: -90)

Spoofer Configuration:
--enable-spoofer          Enable spoofer (randomly selects ghost and spoofer hosts)

Branching Factors:
--param-variants N        Number of top-level parameter sets (default: 1)
--corridor-variants N     Corridor layouts per param set (default: 1)
--building-variants N     Building layouts per corridor (default: 1)
--trajectory-variants N   Trajectory sets per corridor (default: 1)
--scenario-variants N     Scenarios per building+trajectory combo (default: 1)

Parallelization:
--parallel N              Run N scenarios in parallel (default: 1)
                          Use --parallel 0 for auto-detect (nproc)

General Options:
--seed NUM                Starting seed (default: 42)
-o DIR                    Output directory (default: $PROJ_DIR/datasets)
```

#### Urbanenv Output Structure
```
datasets/
├── manifest.json                 ← Top-level manifest for regeneration
└── urbanenv/
    └── grid{G}_hosts{H}_sim{T}/
        └── ew{E}_ns{N}_w{W}_sp{S}/
            ├── corridors.ndjson
            ├── buildings/
            │   └── n{B}_h{H}_seed{S}.xml
            ├── trajectories/
            │   └── spd{V}_alt{A}_seed{S}.xml
            └── scenarios/
                └── bldg_...__traj_...__seed{S}/
                    ├── omnetpp.ini
                    ├── {hash}-o.csv      ← Open-space scenario
                    └── {hash}-b.csv      ← With-buildings scenario
```

#### Dataset Manifest

Each dataset includes a `manifest.json` that traces all generation parameters down to individual CSV files. This enables regenerating any CSV after cleanup (e.g., after removing intermediate artifacts to save space).

```bash
# Regenerate a specific CSV from manifest
python3 container/regenerate_csv.py datasets/scitech26/manifest.json 872368be-b.csv

# Skip artifact regeneration if they already exist
python3 container/regenerate_csv.py datasets/scitech26/manifest.json 872368be-b.csv --skip-artifacts

# Regenerate corridors/buildings/trajectories only
python3 container/urbanenv/regenerate_from_manifest.py datasets/scitech26/manifest.json --all
```

## CSV Data Schema

```csv
time,event_type,host_id,host_type,is_spoofed,serial_number,rid_timestamp,
pos_x,pos_y,pos_z,speed_vertical,speed_horizontal,heading,
rid_pos_x,rid_pos_y,rid_pos_z,rid_speed_vertical,rid_speed_horizontal,rid_heading,
tx_power,rssi,
kf_estimate,kf_covariance,kf_gain,kf_innovation,kf_nis,kf_measurement
```

### Event Identification
- `time` - Event time (RX time for receptions, TX time for transmissions)
- `event_type` - "TX" for transmission, "RX" for reception
- `host_id` - ID of the host logging this event (transmitter for TX, receiver for RX)
- `serial_number` - Remote ID serial number from the message
- `rid_timestamp` - RID message timestamp in milliseconds (uniquely identifies a transmission with serial_number)
- `host_type` - "benign" or "spoofer" (added by post-processing)
- `is_spoofed` - 1 if this event is from a spoofer, 0 otherwise (added by post-processing)

**Transmission grouping:** To identify all RX events from a single transmission, group by `(serial_number, rid_timestamp)`.

**Actual host position/velocity** (transmitter for TX, receiver for RX):
- `pos_x, pos_y, pos_z` - Actual position (meters)
- `speed_vertical` - Actual vertical speed (m/s)
- `speed_horizontal` - Actual horizontal ground speed (m/s)
- `heading` - Actual heading angle (degrees from North)

**Remote ID message fields** (claimed values in the transmitted message):
- `rid_pos_x, rid_pos_y, rid_pos_z` - Claimed position from Remote ID message (meters)
- `rid_speed_vertical` - Claimed vertical speed from message (m/s)
- `rid_speed_horizontal` - Claimed horizontal speed from message (m/s)
- `rid_heading` - Claimed heading from message (degrees)

### Transmission Events (event_type = TX)
For TX events, actual position equals Remote ID claimed position for honest nodes, but differs for spoofers.
- `tx_power` - Transmission power (dBm)

### Reception Events (event_type = RX)
For RX events, actual position is the receiver's location, Remote ID fields show transmitter's claimed location.
- `rssi` - Received signal strength (dBm)
- `kf_estimate` - Kalman Filter Tx power estimate (dBm)
- `kf_covariance` - KF state covariance
- `kf_gain` - Kalman gain
- `kf_innovation` - Innovation (residual)
- `kf_nis` - Normalized Innovation Squared
- `kf_measurement` - Measured Tx power (dBm)

## Implementation Details

### Data Logging

**RidBeaconMgmt** - TX/RX event logging

**KalmanFilterDetectMgmt** - Per-drone KF state vectors


### File Structure

The project uses out-of-tree builds to keep container build artifacts separate from IDE builds.

```
/usr/uli-net-sim/
├── uav_rid/                      # Mounted from host workspace (or copied at container build time)
│   ├── src/
│   │   ├── rid_beacon/RidBeaconMgmt.{cc,h}
│   │   ├── detectors/kalman_filter/KalmanFilterDetectMgmt.{cc,h}
│   │   ├── spoofers/
│   │   │   ├── static_location/      # Static location spoofer
│   │   │   └── dynamic_trajectory/   # Dynamic trajectory spoofer
│   │   └── utils/random_waypoints.py
│   ├── simulations/
│   │   ├── random_waypoints/omnetpp.ini
│   │   ├── urbanenv/omnetpp.ini      # Urban environment base config
│   │   └── urbanenv_testing/         # Test scenarios (generated)
│   ├── container/
│   │   ├── setenv                # Environment setup script
│   │   ├── build.sh              # Out-of-tree build script
│   │   ├── generate_dataset.sh   # End-to-end pipeline (random_waypoints + urbanenv)
│   │   ├── run_scenario.sh       # Run single scenario (used by generate_dataset.sh)
│   │   ├── vec2csv.py            # Vector to CSV converter
│   │   ├── add_host_type.py      # Add host_type column to CSV
│   │   ├── regenerate_csv.py     # Regenerate specific CSV from manifest
│   │   └── urbanenv/             # Urban environment generation tools
│   │       ├── generate_corridors.py       # Corridor generator
│   │       ├── generate_buildings.py       # Building generator
│   │       ├── generate_trajectories.py    # Trajectory generator
│   │       ├── generate_scenario.py        # Scenario ini generator
│   │       ├── generate_dataset_manifest.py # Top-level manifest generator
│   │       ├── regenerate_from_manifest.py  # Regenerate artifacts from manifest
│   │       └── generate_test_scenarios.sh
│   ├── datasets/                 # Generated output (visible on host)
│   ├── out/                      # IDE build output (not used by container)
│   └── Containerfile             # Container build definition
│
├── container-build/              # Container build output (separate from IDE)
│   ├── src -> ../uav_rid/src     # Symlink to source
│   ├── simulations -> ...        # Symlink to simulations
│   ├── Makefile                  # Container-specific Makefile
│   └── out/clang-release/uav_rid # Container binary
│
├── omnetpp-6.2.0/                # OMNeT++ installation
├── inet4.5/                      # INET framework
└── eigen-5.0.0/                  # Eigen library
```
