# Spoofing-Aware with Planning

This folder defines and runs the spoofing-aware trajectory planning simulation.
The implemented pipeline combines:

- online spoofing detection from GCS report callbacks,
- post-detection spoofer localization/tracking with IMM,
- chance-constrained unsafe-region publication,
- decentralized benign-agent replanning.

This README documents what the code currently does.

## Scenario families (spoofer path shape)

In `omnetpp.ini`, benign traffic and GCS logic are shared; **spoofer waypoint scripts** are grouped by intent:

- **`Scenario_Hub_*` (Hub_4x1, Hub_8x1, Hub_12x1):** spoofer follows a **straight** east–west leg at **y = 250 m** (consistent across all Hub configs).
- **`Scenario_Circle_8x1`, `Scenario_SteepZ_8x1`, `Scenario_Corners_4x1`:** spoofer follows a **diagonal, piecewise (zig-zag)** path. **`Scenario_Corners_4x1_SmoothSpoofer`** uses the same corner geometry with a **smoothed** spoofer trajectory (more waypoints, gentler turns).

TrustRid configs (`Scenario_*_TrustRid`) use the **same** spoofer and benign geometry as the matching base scenario; only the GCS class differs.

## End-to-End Flow (As Implemented)

```mermaid
flowchart TD
  A["`omnetpp.ini` scenario config"] --> B["OMNeT++ `uav_rid.rid_network.BasicUav`"]
  B --> C["Benign hosts: `MdpTrajectoryPlanner`"]
  B --> D["Spoofer host: `CascadedPidController` + `PositionOffsetSpoofer`"]
  C --> E["RID beacons + RX reports"]
  D --> E
  E --> F["GCS `SpoofingAwareGcs.on_gcs_reports`"]

  F --> G["KF branch: `KfNisDetector`"]
  F --> H["MLAT branch: `multilaterate_with_tx_power` + `PositionErrorKF`"]
  G --> I["Combined decision: `kf_max_nis > 6.63 OR mlat_score > 50`"]
  H --> I

  I -->|Alert| J["Mark serial as spoofer + init IMM/TX state"]
  J --> K["Phase 2 localization (>=4 RX: joint x,tx; >=3 RX: position-only)"]
  K --> L["IMM correction (`IMMEstimator.update`)"]
  L --> M["`on_gcs_tick`: IMM predict-only + unsafe ellipsoid publish"]
  M --> C

  F --> N["Per-report vectors/log metrics"]
  M --> N
  N --> O["`.sca` and `.vec` under `batches/<run-id>/generated/.../results`"]
  O --> P["Batch CSVs/charts via datagen scripts"]
```

## Runtime Behavior Details

### 1) Report ingestion (`SpoofingAwareGcs.on_gcs_reports`)

- Each transmission includes `serial_number`, `claimed_pos`, and RX `reports`.
- Each RX report carries receiver `pos`, `rssi_dbm`, and optional `kf_nis`.
- Detection runs for unknown serials until first spoofer is declared (`STOP_DETECTION_AFTER_FIRST_SPOOFER = True` by default).

### 2) Detection phase (before serial is marked spoofing)

- Combined trigger rule is immediate and per-report:
  - `kf_max_nis > 6.63` OR `mlat_score > 50.0`.
- MLAT score path:
  - requires at least 4 receivers,
  - performs joint NLLS over `(x,y,z,tx_power)`,
  - computes raw claim-vs-MLAT position error,
  - smooths that error with `PositionErrorKF` to produce `mlat_score`.
- During this phase, code accumulates TX and position samples for handoff initialization.

### 3) Detection-to-localization handoff

- When combined alert is true:
  - serial is inserted into `self.spoofers`,
  - initial tracked TX estimate is set from median detection-time TX samples,
  - `IMMEstimator` is constructed and seeded from accumulated MLAT positions when available.

### 4) Localization/tracking phase (after serial is marked spoofing)

- Receiver-count dependent solve:
  - `>=4` receivers: joint solve for position and TX each report, then smooth TX estimate (EMA + per-step clamp),
  - `>=3` receivers: position-only solve using latest TX estimate.
- Measurement covariance is estimated from local NLLS geometry and residual-driven inflation.
- IMM update is measurement-correction only in `on_gcs_reports`; between reports, IMM is propagated in `on_gcs_tick`.
- If MLAT is unavailable, code can fall back to claimed-position plus learned bias with high covariance so tracking remains continuous.

### 5) Unsafe-region publication (`SpoofingAwareGcs.on_gcs_tick`)

- Each tracked spoofer contributes a chance-constraint ellipsoid from IMM `(mu, Sigma, alpha)`.
- Published ellipsoid state is smoothed/clamped for stability before broadcast.
- If no fresh region exists, last valid unsafe region can be rebroadcast as stale fallback.
- Command payload to benign agents includes:
  - `unsafe_region` (primary),
  - `unsafe_regions` (list),
  - `other_positions` (non-spoofer cooperative RID states),
  - planning metadata (`alpha`, `agent_radius`, optional goals).

### 6) Benign planner coupling (`MdpTrajectoryPlanner`)

- Planner uses both:
  - soft penalties around unsafe ellipsoid center/boundary in value evaluation,
  - hard trajectory rejection when projected states enter unsafe ellipsoid.
- If all candidate trajectories violate hard constraint, planner falls back to best-value action.

### 7) Chance-constraint math

- Implemented in `pymodules/gcs/chance_constraint.py`.
- Threshold uses chi-square inverse CDF:
  - `F^{-1}_{chi^2_3}(1 - alpha)`.
- Safety test is Mahalanobis-distance based and shared between GCS metrics and planner hard constraint.

## Files in This Pipeline

### Scenario and execution entry points

- `simulations/spoofing_aware_with_planning/omnetpp.ini`
  - Scenario definitions and class bindings (Aware and TrustRid variants).
- `datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh`
  - Primary batch driver: generates run-local INIs, executes paired Aware/TrustRid runs, exports vectors, creates plots.
- `datagen/run_batch.py`
  - Generic multi-scenario batch executor.
- `datagen/run_scenario.py`
  - Per-scenario simulation + `.vec` to parquet conversion + `.sca` copy.
- `datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch_README.md`
  - Batch usage and operational runbook.

### Runtime modules loaded by INI

- `pymodules/planners/spoofing_aware_gcs.py`
  - Detection, localization, IMM tracking, unsafe-region publication, diagnostics.
- `pymodules/controllers/mdp_trajectory_planner.py`
  - Benign decentralized planner consuming GCS broadcasts.
- `pymodules/controllers/cascaded_pid.py`
  - Spoofer low-level motion controller.
- `pymodules/spoofers/position_offset.py`
  - Attack hook that offsets claimed RID position.

### Detection and estimation dependencies

- `pymodules/detectors/kf_nis.py`
  - KF NIS extraction from RX reports.
- `pymodules/detectors/combined.py`
  - Reference implementation of the same OR-rule used in GCS detection.
- `pymodules/detectors/rssi_multilateration.py`
  - Standalone detector module (not the main simulation GCS path).
- `pymodules/gcs/multilateration.py`
  - Joint and position-only RSSI multilateration + covariance estimation.
- `pymodules/gcs/imm_estimator.py`
  - CV/CA IMM tracker.
- `pymodules/gcs/chance_constraint.py`
  - Chance-constraint thresholding and safety tests.

### Post-processing and plotting

- `pymodules/analysis/spoofing_batch_metrics.py`
  - Builds paired Aware/TrustRid scalar summary CSV from `.sca`.
- `datagen/spoofting_aware_trajectory_planning_datagen/plot_batch.py`
  - Generates summary and timeseries charts/tables from summary/vector data.

## Output Layout

Batch outputs are written under:

- `simulations/spoofing_aware_with_planning/batches/<run-id>/generated/`
  - Scenario-seed directories, generated INIs, results, copied `.sca`, produced parquet.
- `simulations/spoofing_aware_with_planning/batches/<run-id>/summary.csv`
  - Paired scalar metrics (Aware vs TrustRid).
- `simulations/spoofing_aware_with_planning/batches/<run-id>/gcs_vectors/`
  - Exported GCS vector CSVs.
- `simulations/spoofing_aware_with_planning/batches/<run-id>/charts/`
  - Chart PDFs and summary tables.
- `simulations/spoofing_aware_with_planning/batches/<run-id>/run_timing.csv`
  - Per-run wall-clock timing.
