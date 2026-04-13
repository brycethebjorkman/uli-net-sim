"""
GP-tracking planner: propagation GP + CUSUM detection + active trajectory planning.

A single detector drone monitors a target transmitter. The propagation GP
learns the geometry-to-RSSI mapping from (log10(distance), altitude_diff)
features.  A CUSUM statistic on the GP's standardized prediction errors
detects spoofing.  An active trajectory planner selects the detector's next
position to maximize the GP's integrated variance reduction, accelerating
detection.

Planning happens in on_gcs_reports (per-transmission): after receiving a
beacon and updating the GP, the planner picks the best position for
receiving the *next* beacon and steers the detector drone there.  The
``steer`` command directs the drone toward the planned position at
cruise speed without decelerating to a stop between replans.

The detector drone must use a controller that accepts ``steer`` commands
(CascadedPidController).

INI usage:
    *.numGcs = 1
    *.gcs[0].pyClass = "pymodules.planners.gp_tracking.GpTrackingPlanner"
    *.gcs[0].federateIndices = "1"        # detector drone host index
    *.gcs[0].sendControlCommands = true
    *.host[1].wlan[0].mgmt.gcsModulePath = "^.^.^.gcs[0]"
"""

import math

import numpy as np

from pymodules.gcs.gaussian_process import PropagationGP, DeclarationGP


def _compute_feature(claimed_pos, detector_pos):
    """Compute propagation GP input feature from positions.

    Returns (log10(distance), altitude_difference) or None if distance < 1m.
    """
    d = np.linalg.norm(np.asarray(claimed_pos) - np.asarray(detector_pos))
    if d < 1.0:
        return None
    dz = claimed_pos[2] - detector_pos[2]
    return np.array([math.log10(d), dz])


class GpTrackingPlanner:
    """GCS class combining GP-CUSUM detection with active trajectory planning."""

    def __init__(
        self,
        beta: float = 2.0,
        h: float = 20.0,
        k_min: int = 8,
        reoptimize_interval: int = 20,
        planner_speed: float = 10.0,
        beacon_interval: float = 1.0,
        grid_log_d_range: tuple[float, float] = (0.5, 2.7),
        grid_dz_range: tuple[float, float] = (-100.0, 100.0),
        grid_resolution: int = 7,
        altitude_offsets: tuple[float, ...] = (0.0, 20.0, -20.0),
        gp_window: int | None = 200,
    ):
        self.beta = beta
        self.h = h
        self.k_min = k_min
        self.reoptimize_interval = reoptimize_interval
        self.planner_speed = planner_speed
        self.beacon_interval = beacon_interval
        self.altitude_offsets = altitude_offsets

        # delta_max: distance the drone can cover between beacons at cruise speed
        self.delta_max = planner_speed * beacon_interval

        # GPs
        self.prop_gp = PropagationGP(window=gp_window)
        self.decl_gp = DeclarationGP()

        # CUSUM state
        self.cusum: float = 0.0
        self.spoofing_declared: bool = False
        self.detection_time: float | None = None

        # Counters
        self.obs_count: int = 0

        # Auto-detected IDs
        self.detector_host_id: int | None = None
        self.target_serial: int | None = None

        # Latest known detector position (from reports)
        self._detector_pos: np.ndarray | None = None

        # Reference grid for integrated variance reduction
        ld = np.linspace(grid_log_d_range[0], grid_log_d_range[1], grid_resolution)
        dz = np.linspace(grid_dz_range[0], grid_dz_range[1], grid_resolution)
        self.reference_grid = np.array([[l, z] for l in ld for z in dz])

    # ------------------------------------------------------------------
    # Per-transmission: detection + GP update + trajectory planning
    # ------------------------------------------------------------------

    def on_gcs_reports(self, data: dict) -> dict:
        serial = data["serial_number"]
        claimed_pos = np.array(data["claimed_pos"])
        reports = data["reports"]
        sim_time = data["time"]

        if not reports:
            return {"log": {}}

        # Auto-detect detector host from the first report
        if self.detector_host_id is None:
            self.detector_host_id = reports[0]["host_id"]

        # Auto-detect target serial from the first unknown serial
        if self.target_serial is None:
            self.target_serial = serial
        if serial != self.target_serial:
            return {"log": {}}

        # Use first report (single detector drone)
        report = reports[0]
        detector_pos = np.array(report["pos"])
        rssi = report["rssi_dbm"]
        self._detector_pos = detector_pos

        # Compute feature
        feat = _compute_feature(claimed_pos, detector_pos)
        if feat is None:
            return {"log": {}}

        # --- Detection (before adding observation) ---
        s_k = 0.0
        gp_pred_mean = 0.0
        gp_pred_var = 0.0

        if self.obs_count >= self.k_min:
            gp_pred_mean, gp_pred_var = self.prop_gp.predict(feat)
            if gp_pred_var > 1e-10:
                s_k = (rssi - gp_pred_mean) ** 2 / gp_pred_var
                self.cusum = max(0.0, self.cusum + s_k - self.beta)
                if self.cusum > self.h and not self.spoofing_declared:
                    self.spoofing_declared = True
                    self.detection_time = sim_time

        # --- GP update ---
        self.prop_gp.add_observation(feat, rssi)
        self.obs_count += 1

        # Periodic hyperparameter reoptimization
        if (self.obs_count % self.reoptimize_interval == 0
                and self.obs_count >= self.reoptimize_interval):
            self.prop_gp.optimize_hyperparameters()

        # --- Declaration GP update ---
        self.decl_gp.add_observation(sim_time, claimed_pos)

        # --- Active trajectory planning ---
        result = {
            "log": {
                "packet_id": float(data.get("packet_id", -1)),
                "cusum_stat": self.cusum,
                "standardized_error": s_k,
                "gp_pred_mean": gp_pred_mean,
                "gp_pred_var": gp_pred_var,
                "spoofing_declared": 1.0 if self.spoofing_declared else 0.0,
                "obs_count": float(self.obs_count),
            },
        }

        planned = self._plan_next_position(sim_time, detector_pos)
        if planned is not None:
            best_pos, best_score = planned
            result["commands"] = {
                self.detector_host_id: {
                    "task": "steer",
                    "x": float(best_pos[0]),
                    "y": float(best_pos[1]),
                    "z": float(best_pos[2]),
                    "speed": self.planner_speed,
                },
            }
            result["log"]["planned_x"] = float(best_pos[0])
            result["log"]["planned_y"] = float(best_pos[1])
            result["log"]["planned_z"] = float(best_pos[2])
            result["log"]["max_variance_reduction"] = best_score

        return result

    # ------------------------------------------------------------------
    # Planning: pick the best position for the next beacon reception
    # ------------------------------------------------------------------

    def _plan_next_position(
        self, sim_time: float, detector_pos: np.ndarray
    ) -> tuple[np.ndarray, float] | None:
        """Select next detector position via integrated variance reduction.

        Returns (best_position, best_score) or None if not enough data yet.
        """
        if self.obs_count < 3:
            return None

        # Predict where the target will declare next (mean of declaration GP)
        t_next = sim_time + self.beacon_interval
        decl_mean, _ = self.decl_gp.predict(t_next)

        # Generate candidate positions within reachable ball
        candidates = self._generate_candidates(detector_pos)

        # Compute GP features for all candidates, filtering out invalid ones
        feats = []
        valid_indices = []
        for i, cand in enumerate(candidates):
            feat = _compute_feature(decl_mean, cand)
            if feat is not None:
                feats.append(feat)
                valid_indices.append(i)

        if not feats:
            return detector_pos.copy(), 0.0

        # Batch variance reduction (shared reference-grid solve computed once)
        scores = self.prop_gp.variance_reduction_batch(
            np.array(feats), self.reference_grid
        )

        best_idx = int(np.argmax(scores))
        return candidates[valid_indices[best_idx]], float(scores[best_idx])

    def _generate_candidates(self, current_pos: np.ndarray) -> list[np.ndarray]:
        """Generate candidate positions within delta_max of current position."""
        candidates = [current_pos.copy()]  # hold option

        # 8 compass directions at delta_max horizontal distance
        for angle_deg in range(0, 360, 45):
            angle_rad = math.radians(angle_deg)
            dx = self.delta_max * math.cos(angle_rad)
            dy = self.delta_max * math.sin(angle_rad)
            for dz in self.altitude_offsets:
                cand = current_pos + np.array([dx, dy, dz])
                cand[2] = max(cand[2], 5.0)
                candidates.append(cand)

        return candidates

    # ------------------------------------------------------------------
    # End-of-simulation callback
    # ------------------------------------------------------------------

    def on_gcs_finish(self) -> dict:
        return {
            "scalars": {
                "detection_time": self.detection_time if self.detection_time is not None else -1.0,
                "cusum_final": self.cusum,
                "total_observations": float(self.obs_count),
                "spoofing_declared": 1.0 if self.spoofing_declared else 0.0,
            },
        }
