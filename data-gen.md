# Remote ID Spoofing Detection - Data Generation

## Overview

This pipeline generates datasets to evaluate Remote ID spoofing detection methods:

1. **Kalman Filter-based detection** - Threshold on KF state using RSSI to estimate transmission power
2. **Multilateration-based detection** - RSSI triangulation from multiple receivers
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

### Setup

**IMPORTANT:** Edit code in `/workspaces/uli-net-sim`, run simulations from `/usr/uli-net-sim`.

```bash
# 1. Build the project
cd /usr/uli-net-sim && . setenv && cd uav_rid
make clean && make
cd /usr/uli-net-sim

# 2. Copy files from workspace
cp -r /workspaces/uli-net-sim/src /usr/uli-net-sim/uav_rid/
cp -r /workspaces/uli-net-sim/simulations /usr/uli-net-sim/uav_rid/
cp /workspaces/uli-net-sim/container/vec2csv.py /usr/uli-net-sim/
cp /workspaces/uli-net-sim/container/generate_dataset.sh /usr/uli-net-sim/
chmod +x /usr/uli-net-sim/generate_dataset.sh
```

### Generate Datasets

```bash
# Source environment (required!)
cd /usr/uli-net-sim && . setenv

# Test: 3 scenarios with 5 hosts (1 spoofer)
./generate_dataset.sh -n 3 -h 5 -s 1 -o test_dataset

# Baseline: 20 scenarios without spoofers
./generate_dataset.sh -n 20 -c RandomWaypoints5Host -h 5 -s 0 -o datasets/baseline

# Spoofing: 50 scenarios with 1 spoofer
./generate_dataset.sh -n 50 -h 5 -s 1 -o datasets/spoofing_1spoofer
```

### Copy Results to Workspace

```bash
# Copy datasets for analysis
cp -r /usr/uli-net-sim/datasets /workspaces/uli-net-sim/
```

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
- `RandomWaypoints3Host` - 3 hosts, no spoofers
- `RandomWaypoints5Host` - 5 hosts, no spoofers
- `RandomWaypoints5Host1Spoofer` - 5 hosts, 1 spoofer (host[4])
- `RandomWaypoints10Host2Spoofer` - 10 hosts, 2 spoofers (host[8-9])

Randomized parameters:
- Beacon interval: uniform(0.25s, 0.75s)
- Transmission power: uniform(10dBm, 16dBm)
- Startup jitter: uniform(0ms, 100ms)

### 3. Vector to CSV Conversion (`vec2csv.py`)

Converts OMNeT++ .vec files to CSV format with one row per event.

```bash
python3 vec2csv.py results/scenario.vec -o output.csv
```

### 4. End-to-End Pipeline (`generate_dataset.sh`)

Options:
```
-n NUM        Number of scenario repetitions (default: 5)
-c CONFIG     OMNeT++ config name (default: RandomWaypoints5Host1Spoofer)
-h HOSTS      Number of hosts (default: 5)
-s SPOOFERS   Number of spoofer hosts (default: 1)
-w WAYPOINTS  Waypoints per host (default: 15)
-g SIZE       Grid size in meters (default: 1000)
-r RANGE      Speed range as 'min-max' (default: 5-15)
-a RANGE      Altitude range as 'min-max' (default: 30-100)
-o DIR        Output directory (default: datasets)
--seed NUM    Starting seed (default: 42)
```

## CSV Data Schema

```csv
time,event_type,host_id,serial_number,
pos_x,pos_y,pos_z,speed_vertical,speed_horizontal,heading,
rid_pos_x,rid_pos_y,rid_pos_z,rid_speed_vertical,rid_speed_horizontal,rid_heading,
tx_power,rssi,
kf_estimate,kf_covariance,kf_gain,kf_innovation,kf_nis,kf_measurement
```

### Common Fields (both TX and RX)
- `time` - Simulation time (seconds)
- `event_type` - "TX" for transmission, "RX" for reception
- `host_id` - ID of the host logging this event (transmitter for TX, receiver for RX)
- `serial_number` - Remote ID serial number from the message

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

**RidBeaconMgmt.cc/h** - Transmission power, receiver velocity logging

**KalmanFilterDetectMgmt.cc/h** - Per-drone KF state vectors (estimate, covariance, gain, innovation, NIS, measurement)


### File Structure

```
/workspaces/uli-net-sim/          # Edit here
├── src/
│   ├── rid_beacon/RidBeaconMgmt.{cc,h}
│   ├── detectors/kalman_filter/KalmanFilterDetectMgmt.{cc,h}
│   └── utils/random_waypoints.py
├── simulations/random_waypoints/
│   ├── omnetpp.ini
│   └── .gitignore
├── container/
│   ├── generate_dataset.sh
│   └── vec2csv.py
└── DATA_GENERATION_README.md

/usr/uli-net-sim/                 # Run here
├── uav_rid/
│   ├── src/                      # Copied from workspace
│   ├── simulations/              # Copied from workspace
│   └── out/clang-release/uav_rid # Container binary
├── generate_dataset.sh           # Copied from workspace
└── vec2csv.py                    # Copied from workspace
```
