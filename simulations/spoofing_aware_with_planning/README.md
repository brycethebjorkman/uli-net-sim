# Spoofing-Aware with Planning

This folder defines and runs the spoofing-aware trajectory-planning simulation.
It combines online detection, spoofer localization/tracking, and decentralized
agent replanning in one pipeline.

## Code-Flow Diagram

```mermaid
flowchart TD
  A["`omnetpp.ini` scenario config"] --> B["OMNeT++ network `uav_rid.rid_network.BasicUav`"]
  B --> C["Benign hosts (`MdpTrajectoryPlanner`)"]
  B --> D["Spoofer host (`CascadedPidController` + `PositionOffsetSpoofer`)"]
  C --> E["RID beacons + RX reports"]
  D --> E
  E --> F["GCS `SpoofingAwareGcs.on_gcs_reports`"]

  F --> G["KF NIS score (`KfNisDetector`)"]
  F --> H["MLAT score (`multilaterate_with_tx_power` + `PositionErrorKF`)"]
  G --> I["Combined rule: KF OR MLAT"]
  H --> I

  I -->|Alert| J["Mark serial as spoofer"]
  J --> K["Initialize tracked TX estimate + IMM state"]
  K --> L["Phase-2 localization (`multilaterate_position_with_covariance`)"]
  L --> M["IMM update (`IMMEstimator`)"]

  M --> N["`on_gcs_tick`: unsafe ellipsoid + coop state broadcast"]
  N --> C

  F --> O["GCS vectors/log metrics"]
  N --> O
  O --> P["`.sca`/vectors in `batches/<run-id>/generated/.../results`"]
  P --> Q["Charts/tables via datagen scripts -> `batches/<run-id>/charts/...`"]
```

## Files Used in the Simulation Pipeline

### Scenario and execution entrypoints

- `simulations/spoofing_aware_with_planning/omnetpp.ini`
  - All scenario configs (Circle, Corners, Hub, SteepZ variants).
  - Binds module classes for GCS, benign controllers, and spoofer hook.
- `datagen/run_spoofing_aware_trajectory_planning_batch.sh`
  - Main batch runner for seeded runs of this simulation.
- `datagen/generate_spoofing_sweep.py`
  - Generates per-seed/per-layout scenario configs for batch runs.
- `datagen/run_batch.py`
  - Batch orchestration utility used by batch workflows.
- `datagen/run_spoofing_aware_trajectory_planning_batch_README.md`
  - Batch script usage and knobs.

### Runtime Python modules (loaded by INI)

- `pymodules/planners/spoofing_aware_gcs.py`
  - Integrated detection -> localization -> unsafe-region publication.
- `pymodules/controllers/mdp_trajectory_planner.py`
  - Benign trajectory planner consuming GCS unsafe/cooperative data.
- `pymodules/controllers/cascaded_pid.py`
  - Spoofer low-level motion controller.
- `pymodules/spoofers/position_offset.py`
  - RID transmit hook that offsets claimed position (attack model).

### Detection and estimation dependencies

- `pymodules/detectors/combined.py`
  - Canonical detection truth rule: `combined_alert = KF OR MLAT`.
- `pymodules/detectors/kf_nis.py`
  - KF NIS extraction from per-receiver reports.
- `pymodules/detectors/rssi_multilateration.py`
  - Standalone MLAT detector module (reference implementation).
- `pymodules/gcs/multilateration.py`
  - Joint and position-only MLAT solvers + covariance estimation.
- `pymodules/gcs/imm_estimator.py`
  - IMM tracker used after spoofing detection.
- `pymodules/gcs/chance_constraint.py`
  - Unsafe-region math and safety tests for planner constraints.

### Post-processing and plotting (pipeline outputs)

- `datagen/plot_sweep_charts.py`
  - Builds summary/time-series charts from batch outputs.
- `datagen/plot_sweep_3d_trajectories.py`
  - Per-batch 3D trajectory visualizations.
- `datagen/plot_batch_3d_trajectories.py`
  - Batch 3D overlays/trajectory figures.
- `pymodules/analysis/spoofing_batch_metrics.py`
  - Aggregation helpers for spoofing/planning metrics.

### Generated artifacts and storage layout

- `simulations/spoofing_aware_with_planning/batches/<run-id>/generated/`
  - Per-seed generated INIs and run result directories.
- `simulations/spoofing_aware_with_planning/batches/<run-id>/gcs_vectors/`
  - Extracted GCS vector CSVs.
- `simulations/spoofing_aware_with_planning/batches/<run-id>/charts/`
  - Persisted chart suites, tables, and PDFs.

## Runtime Pipeline Details

### 1) Report ingestion (`on_gcs_reports`)

- Each transmission provides `serial_number`, claimed position, and RX reports.
- RX reports include receiver position, RSSI, and optional `kf_nis`.

### 2) Detection (Phase 1, combined truth)

- `SpoofingAwareGcs` applies the same rule as `pymodules/detectors/combined.py`:
  - `kf_max_nis > 6.63` OR `mlat_score > 50.0`.
- While detecting, it accumulates MLAT TX/position samples for bootstrap.
- `STOP_DETECTION_AFTER_FIRST_SPOOFER = True`:
  - after first identification, unknown serials skip detection work.

### 3) Detection-to-localization handoff

- On alert:
  - serial is added to `self.spoofers`,
  - tracked TX estimate is initialized from detection-time MLAT TX samples,
  - IMM is initialized from accumulated MLAT positions (fallback to claim).

### 4) Localization/tracking (Phase 2)

- Uses joint or position-only MLAT depending on receiver count/solver success.
- Computes measurement covariance and updates IMM.

### 5) Planner coupling (`on_gcs_tick`)

- Builds unsafe ellipsoid(s) from tracked spoofers.
- Broadcasts unsafe region + cooperative state to benign planners.
- Benign `MdpTrajectoryPlanner` replans accordingly.

### 6) Metrics and outputs

- Per-report and per-tick diagnostics are logged as vectors.
- End-of-run scalars written to `.sca`.
- Plotting scripts consume outputs to generate the chart suites.
