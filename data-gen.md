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

```bash
# Test: 3 scenarios with 5 hosts (1 spoofer)
./container/generate_dataset.sh -n 3 -h 5 -s 1

# Baseline: 20 scenarios without spoofers
./container/generate_dataset.sh -n 20 -c RandomWaypoints5Host -h 5 -s 0 -o datasets/baseline

# Spoofing: 50 scenarios with 1 spoofer
./container/generate_dataset.sh -n 50 -h 5 -s 1 -o datasets/spoofing_1spoofer

# Dynamic trajectory spoofing (spoofer claims ghost's position)
./container/generate_dataset.sh -n 50 -c RandomWaypoints4Host1Ghost1DynSpoofer -h 6 -s 1 -o datasets/dynamic_spoofer
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
-o DIR        Output directory (default: $PROJ_DIR/datasets)
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
│   ├── simulations/random_waypoints/
│   │   └── omnetpp.ini
│   ├── container/
│   │   ├── setenv                # Environment setup script
│   │   ├── build.sh              # Out-of-tree build script
│   │   ├── generate_dataset.sh   # End-to-end pipeline
│   │   └── vec2csv.py            # Vector to CSV converter
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
