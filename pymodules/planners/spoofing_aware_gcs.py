"""
Spoofing-aware GCS: RSSI multilateration detection → position-only localization.

Two-phase pipeline per the paper (AIAA SciTech '26, Sec. V-B):

  Phase 1 — Detection (runs on every transmitter until first detection):
    Uses the same combined decision rule as ``pymodules.detectors.combined``:
    alert when either KF-NIS exceeds threshold or MLAT filtered-error exceeds
    threshold. While in detection, accumulate joint MLAT position/TX estimates
    so localization can be initialized immediately after alert.

  Phase 2 — Localization (per detected spoofer, rest of sim):
    Dynamically estimate TX power during localization using joint
    position+TX-power multilateration whenever >=4 receivers are available.
    When only 3 receivers are available, fall back to position-only
    multilateration using the latest TX estimate. Feed measurements to
    per-spoofer IMM for state estimation and chance-constraint computation.

  on_gcs_tick: broadcast IMM-based chance constraint + cooperative agent
               positions + goals to benign agents.

  NMAC metrics (evaluated on GCS ticks; uses ``ground_truth_positions`` from
  GcsModule when present — true mobility from OMNeT++ — else RID positions):
    - Proximity: any pair of benign agents with 3D separation < 50 m (new
      entry into that condition per pair counts once until they separate).
    - Benign-vs-spoofer proximity: any benign agent within 50 m of the true
      spoofer host (edge-counted per benign agent).
    - Spoofer unsafe: benign agent inside the chance-constraint ellipsoid
      (same is_safe test as the MDP hard constraint); entry events per serial.
  End-of-run: ``on_gcs_finish`` records scalars ``nmac_proximity_final`` and
  ``nmac_benign_spoofer_final`` / ``nmac_spoofer_unsafe_final`` (cumulative totals)
  to the .sca file for
  cross-run bar charts; tick ``log`` vectors remain for time series.

INI usage:
    *.gcs[0].pyClass = "pymodules.planners.spoofing_aware_gcs.SpoofingAwareGcs"
    *.gcs[0].tickInterval = 0.25s
    *.gcs[0].sendControlCommands = true
"""

import numpy as np
import os
import time

from pymodules.gcs.chance_constraint import (
    is_safe,
    unsafe_region_to_dict,
    mahalanobis_squared,
    ellipsoid_threshold,
)
from pymodules.gcs.imm_estimator import IMMEstimator
from pymodules.gcs.multilateration import (
    multilaterate_with_tx_power,
    multilaterate_position_with_covariance,
)
from pymodules.detectors.combined import CombinedDetector

MIN_RECEIVERS = 4
COMBINED_KF_THRESHOLD = 6.63
COMBINED_MLAT_THRESHOLD = 50.0
STOP_DETECTION_AFTER_FIRST_SPOOFER = True
DEFAULT_AGENT_RADIUS = 120.0

# NMAC: pairwise proximity (m); spoofer unsafe uses chance-constraint ellipsoid (is_safe)
NMAC_PROXIMITY_M = 50.0
TX_EST_EMA = 0.2              # smoothing on dynamic TX estimate
TX_EST_MAX_STEP_DB = 2.0      # max per-update TX change (dB)
TX_EST_MIN_DBM = -50.0
TX_EST_MAX_DBM = 50.0
DEBUG_USE_GROUND_TRUTH_TX = False  # DEBUG ONLY: use tx_true_pos to estimate TX
FSPL_CONSTANT_DB = 40.04
IMM_DT = 0.25
IMM_MAX_PREDICT_STEPS = 0     # 0 => unlimited predict-only propagation between measurements
IMM_INIT_MODE_CV = 0.6
IMM_P_CV_STAY = 0.95
IMM_P_CA_STAY = 0.95
IMM_CV_POS_NOISE = 2.0
IMM_CV_VEL_NOISE = 40.0
IMM_CV_MEAS_NOISE = 100.0
IMM_CA_POS_NOISE = 2.0
IMM_CA_VEL_NOISE = 25.0
IMM_CA_ACC_NOISE = 60.0
IMM_CA_MEAS_NOISE = 100.0
UNSAFE_MU_SMOOTH = 0.35       # EMA gain for published unsafe-region center
UNSAFE_SIGMA_SMOOTH = 0.25    # EMA gain for published unsafe covariance
UNSAFE_STD_MIN_M = 4.0        # floor for visual/planning stability (avoid vanish)
UNSAFE_STD_MAX_M = 35.0       # cap to avoid late-run blow-up / mass NMAC spikes
UNSAFE_MAX_CENTER_STEP_M = 30.0   # max center motion per tick in published region
UNSAFE_MAX_TRACE_GROWTH = 1.8      # max covariance trace growth per tick
CLAIMED_BIAS_EMA = 0.2            # learn offset between claimed and localized position
CLAIMED_FALLBACK_STD_M = 30.0     # pseudo-measurement std when falling back to claimed+bias
MLAT_INIT_CLIP_XY = 2000.0
MLAT_INIT_CLIP_Z = 1000.0
MLAT_INIT_MAX_FROM_CLAIMED = 600.0

# Keep IMM keys present in report logs so OMNeT++ vector files always include them.
_IMM_LOG_DEFAULTS = {
    "imm_mode_prob_cv": float("nan"),
    "imm_mode_prob_ca": float("nan"),
    "imm_nis_cv": float("nan"),
    "imm_nis_ca": float("nan"),
    "imm_nis_mix": float("nan"),
    "imm_last_measurement_time_s": float("nan"),
    "imm_est_x_m": float("nan"),
    "imm_est_y_m": float("nan"),
    "imm_est_z_m": float("nan"),
    "imm_true_x_m": float("nan"),
    "imm_true_y_m": float("nan"),
    "imm_true_z_m": float("nan"),
    "imm_error_norm_m": float("nan"),
    "imm_cov_trace_m2": float("nan"),
    "imm_nees": float("nan"),
}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return float(default)
    try:
        return float(raw)
    except ValueError:
        return float(default)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return int(default)
    try:
        return int(raw)
    except ValueError:
        return int(default)


NMAC_PROXIMITY_M = _env_float("ULI_IMM_NMAC_PROXIMITY_M", NMAC_PROXIMITY_M)
IMM_DT = _env_float("ULI_IMM_DT", IMM_DT)
IMM_MAX_PREDICT_STEPS = _env_int("ULI_IMM_MAX_PREDICT_STEPS", IMM_MAX_PREDICT_STEPS)
IMM_INIT_MODE_CV = _env_float("ULI_IMM_INIT_MODE_CV", IMM_INIT_MODE_CV)
IMM_P_CV_STAY = _env_float("ULI_IMM_P_CV_STAY", IMM_P_CV_STAY)
IMM_P_CA_STAY = _env_float("ULI_IMM_P_CA_STAY", IMM_P_CA_STAY)
IMM_CV_POS_NOISE = _env_float("ULI_IMM_CV_POS_NOISE", IMM_CV_POS_NOISE)
IMM_CV_VEL_NOISE = _env_float("ULI_IMM_CV_VEL_NOISE", IMM_CV_VEL_NOISE)
IMM_CV_MEAS_NOISE = _env_float("ULI_IMM_CV_MEAS_NOISE", IMM_CV_MEAS_NOISE)
IMM_CA_POS_NOISE = _env_float("ULI_IMM_CA_POS_NOISE", IMM_CA_POS_NOISE)
IMM_CA_VEL_NOISE = _env_float("ULI_IMM_CA_VEL_NOISE", IMM_CA_VEL_NOISE)
IMM_CA_ACC_NOISE = _env_float("ULI_IMM_CA_ACC_NOISE", IMM_CA_ACC_NOISE)
IMM_CA_MEAS_NOISE = _env_float("ULI_IMM_CA_MEAS_NOISE", IMM_CA_MEAS_NOISE)


class SpoofingAwareGcs:

    def __init__(
        self,
        alpha: float = 0.05,
        agent_radius: float = DEFAULT_AGENT_RADIUS,
        goals: dict | None = None,
    ):
        self.alpha = alpha
        self.agent_radius = agent_radius
        self.goals = goals or {}

        # Detection state: per-transmitter
        self._tx_power_samples: dict[int, list] = {}    # all joint TX estimates
        self._pos_samples: dict[int, list] = {}         # (time_s, joint pos estimate)
        self._combined_detector = CombinedDetector()
        # Keep runtime thresholds aligned with planner constants.
        self._combined_detector.kf_threshold = float(COMBINED_KF_THRESHOLD)
        self._combined_detector.mlat_threshold = float(COMBINED_MLAT_THRESHOLD)

        # Post-detection state: per-spoofer tracking
        self.spoofers: set[int] = set()
        self._imm: dict[int, IMMEstimator] = {}
        self._spoofer_tx_estimate_dbm: dict[int, float] = {}
        self._published_unsafe: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._last_primary_unsafe: dict | None = None
        self._ticks_since_spoofer_meas: dict[int, int] = {}
        self._claimed_bias: dict[int, np.ndarray] = {}

        # Latest RID positions for cooperative agents
        self.rid_positions: dict[int, tuple[float, float, float]] = {}
        self.federate_ids: set[int] = set()

        # NMAC: edge-detection state (see module docstring)
        self._nmac_proximity_pairs_active: set[tuple[int, int]] = set()
        self._nmac_benign_spoofer_active: set[int] = set()
        self._nmac_serial_inside_unsafe: set[int] = set()
        self.nmac_proximity_count = 0
        self.nmac_benign_spoofer_count = 0
        self.nmac_spoofer_unsafe_count = 0
        self.min_benign_spoofer_distance_now_m = -1.0
        self.min_benign_spoofer_distance_m = float("inf")
        self._spoofer_containment_total = 0
        self._spoofer_containment_hits = 0
        self._spoofer_host: int | None = None
        self._visual_spoofer_serial: int | None = None
        self._reports_time_total_s = 0.0
        self._reports_calls = 0
        self._tick_time_total_s = 0.0
        self._tick_calls = 0
        self._max_host_count = 0
        self._first_seen_time_s: dict[int, float] = {}
        self._first_detection_time_s: float | None = None
        self._detection_latency_s: float | None = None
        self._loc_err_sq_sum = 0.0
        self._loc_err_abs_sum = 0.0
        self._loc_samples = 0
        # Detection diagnostics: track when MLAT is skipped due to too few reports.
        self._detection_reports_total = 0
        self._detection_mlat_attempted = 0
        self._detection_mlat_skipped_insufficient_receivers = 0

    def _combined_detection_step(
        self,
        data: dict,
        report_time: float,
        serial: int,
        rx_positions: np.ndarray,
        rssi_values: np.ndarray,
        claimed_pos: np.ndarray,
    ) -> dict[str, float]:
        """Apply combined detector logic and return detection diagnostics."""
        combined_result = self._combined_detector.on_gcs_reports(data)
        combined_log = combined_result.get("log", {})
        kf_max_nis = float(combined_log.get("kf_max_nis", 0.0))
        kf_has_data = bool(any(r.get("kf_nis") is not None for r in data.get("reports", [])))
        mlat_raw_error = float(combined_log.get("mlat_raw_error", 0.0))
        mlat_score = float(combined_log.get("mlat_score", 0.0))
        receiver_count = int(combined_log.get("mlat_receiver_count", len(rx_positions)))
        mlat_skipped_insufficient_receivers = bool(
            float(combined_log.get("mlat_skipped_insufficient_receivers", 0.0)) > 0.5
        )
        est_x = combined_log.get("mlat_est_x_m")
        est_y = combined_log.get("mlat_est_y_m")
        est_z = combined_log.get("mlat_est_z_m")
        est_tx = combined_log.get("mlat_est_tx_dbm")
        if est_x is not None and est_y is not None and est_z is not None and est_tx is not None:
            est_pos = np.array([float(est_x), float(est_y), float(est_z)], dtype=float)
            self._tx_power_samples.setdefault(serial, []).append(float(est_tx))
            self._pos_samples.setdefault(serial, []).append(
                (float(report_time), est_pos.copy())
            )

        combined_alert = float(combined_log.get("combined_alert", 0.0)) > 0.5
        return {
            "kf_max_nis": kf_max_nis,
            "kf_has_data": 1.0 if kf_has_data else 0.0,
            "mlat_score": float(mlat_score),
            "mlat_raw_error": float(mlat_raw_error),
            "combined_alert": 1.0 if combined_alert else 0.0,
            "receiver_count": float(receiver_count),
            "mlat_skipped_insufficient_receivers": 1.0 if mlat_skipped_insufficient_receivers else 0.0,
        }

    # ------------------------------------------------------------------
    # Per-transmission callback
    # ------------------------------------------------------------------

    def on_gcs_reports(self, data: dict) -> dict | None:
        t0 = time.perf_counter()
        report_time = float(data.get("time", data.get("sim_time", 0.0)))
        serial = data["serial_number"]
        claimed_pos = np.array(data["claimed_pos"])
        reports = data["reports"]
        self._first_seen_time_s.setdefault(int(serial), report_time)

        # Once identified as spoofed, claimed positions are ignored for control.
        if serial not in self.spoofers:
            self.rid_positions[serial] = tuple(claimed_pos)
        else:
            self.rid_positions.pop(serial, None)

        rx_positions = np.array([r["pos"] for r in reports])
        rssi_values = np.array([r["rssi_dbm"] for r in reports])
        for r in reports:
            self.federate_ids.add(r["host_id"])

        mlat_raw_error = 0.0
        mlat_score = 0.0
        kf_max_nis = 0.0
        combined_alert = 0.0
        kf_has_data = 0.0
        receiver_count = float(len(reports))
        mlat_skipped_insufficient_receivers = 0.0
        visualization = {}
        tx_oracle_dbm = 0.0

        # Keep exactly one claimed RID trail (red) for visual clarity.
        # Use scenario convention: spoofer is max host id. host_ids are provided
        # with each report so trail source is stable from the start.
        report_host_ids = [int(h) for h in data.get("host_ids", [])]
        if report_host_ids:
            self._visual_spoofer_serial = max(report_host_ids)
        elif self._spoofer_host is not None:
            self._visual_spoofer_serial = int(self._spoofer_host)
        show_claimed_trail = (
            self._visual_spoofer_serial is not None
            and int(serial) == int(self._visual_spoofer_serial)
        )
        if show_claimed_trail:
            visualization["claimed_pos"] = [float(c) for c in claimed_pos]

        if serial in self.spoofers:
            # ── Phase 2: localization (dynamic TX estimation) ──
            if len(rx_positions) >= 3:
                imm = self._imm[serial]
                if imm._initialized:
                    mlat_init, _ = imm.get_state()
                else:
                    mlat_init = np.mean(rx_positions, axis=0)
                mlat_init = np.asarray(mlat_init, dtype=float).ravel()[:3]
                if mlat_init.shape[0] < 3:
                    mlat_init = np.pad(mlat_init, (0, 3 - mlat_init.shape[0]), mode="constant")
                # Guard against non-finite / runaway IMM priors destabilizing NLLS.
                if not np.all(np.isfinite(mlat_init)):
                    mlat_init = np.mean(rx_positions, axis=0)
                mlat_init = np.clip(mlat_init,
                                    [-MLAT_INIT_CLIP_XY, -MLAT_INIT_CLIP_XY, -MLAT_INIT_CLIP_Z],
                                    [MLAT_INIT_CLIP_XY, MLAT_INIT_CLIP_XY, MLAT_INIT_CLIP_Z])

                tx_before = self._spoofer_tx_estimate_dbm[serial]
                tx_after = tx_before
                est_pos = None
                est_cov = None

                if len(rx_positions) >= MIN_RECEIVERS:
                    # Primary path: joint solve for [x, y, z, tx].
                    joint_pos, joint_tx = multilaterate_with_tx_power(
                        rx_positions, rssi_values, mlat_init,
                    )
                    if joint_pos is not None and joint_tx is not None:
                        delta = float(joint_tx - tx_before)
                        delta = float(np.clip(delta, -TX_EST_MAX_STEP_DB, TX_EST_MAX_STEP_DB))
                        tx_after = float(np.clip(tx_before + TX_EST_EMA * delta, TX_EST_MIN_DBM, TX_EST_MAX_DBM))
                        self._spoofer_tx_estimate_dbm[serial] = tx_after
                        # Covariance from position-only local geometry at updated TX.
                        est_pos, est_cov = multilaterate_position_with_covariance(
                            rx_positions, rssi_values, joint_pos, tx_after
                        )

                # Optional oracle debug mode: estimate TX from true spoofer
                # position and overwrite the current TX estimate.
                if DEBUG_USE_GROUND_TRUTH_TX and data.get("tx_true_pos") is not None:
                    true_pos = np.asarray(data["tx_true_pos"], dtype=float).ravel()[:3]
                    d = np.linalg.norm(rx_positions - true_pos, axis=1)
                    d = np.maximum(d, 0.1)
                    tx_samples = rssi_values + 20.0 * np.log10(d) + FSPL_CONSTANT_DB
                    tx_oracle = float(np.median(tx_samples))
                    tx_oracle = float(np.clip(tx_oracle, TX_EST_MIN_DBM, TX_EST_MAX_DBM))
                    self._spoofer_tx_estimate_dbm[serial] = tx_oracle
                    tx_oracle_dbm = tx_oracle
                    # Re-run position solve with oracle TX for this debug run.
                    est_pos, est_cov = multilaterate_position_with_covariance(
                        rx_positions, rssi_values, mlat_init, self._spoofer_tx_estimate_dbm[serial]
                    )

                if est_pos is None:
                    # Fallback path (3-receiver geometry or joint-solve failure):
                    # use latest TX estimate for position-only solve.
                    est_pos, est_cov = multilaterate_position_with_covariance(
                        rx_positions, rssi_values, mlat_init, self._spoofer_tx_estimate_dbm[serial]
                    )

                used_claimed_fallback = False
                if est_pos is not None and np.all(np.isfinite(est_pos)):
                    est_pos_arr = np.asarray(est_pos, dtype=float).ravel()[:3]
                    est_cov_arr = None if est_cov is None else np.asarray(est_cov, dtype=float)
                    if est_cov_arr is None or est_cov_arr.shape != (3, 3):
                        est_cov_arr = np.eye(3) * (CLAIMED_FALLBACK_STD_M ** 2)

                    # Tick path already handles propagation; measurement path only corrects.
                    imm.update(
                        est_pos_arr,
                        meas_cov=est_cov_arr,
                        do_predict=False,
                        measurement_time_s=report_time,
                    )
                    self._ticks_since_spoofer_meas[serial] = 0

                visualization["tx_est"] = float(self._spoofer_tx_estimate_dbm[serial])
                visualization["tx_est_delta"] = float(tx_after - tx_before)
                visualization["used_claimed_fallback"] = bool(used_claimed_fallback)
            else:
                # With <3 receivers, skip measurement correction and rely on IMM prediction.
                visualization["used_claimed_fallback"] = False
        else:
            # ── Phase 1: detection (optionally disabled after first detection) ──
            detection_enabled = (not STOP_DETECTION_AFTER_FIRST_SPOOFER) or (len(self.spoofers) == 0)
            if detection_enabled:
                detect_diag = self._combined_detection_step(
                    data=data,
                    report_time=report_time,
                    serial=serial,
                    rx_positions=rx_positions,
                    rssi_values=rssi_values,
                    claimed_pos=claimed_pos,
                )
                mlat_raw_error = float(detect_diag["mlat_raw_error"])
                mlat_score = float(detect_diag["mlat_score"])
                kf_max_nis = float(detect_diag["kf_max_nis"])
                kf_has_data = float(detect_diag["kf_has_data"])
                combined_alert = float(detect_diag["combined_alert"])
                receiver_count = float(detect_diag.get("receiver_count", float(len(reports))))
                mlat_skipped_insufficient_receivers = float(
                    detect_diag.get("mlat_skipped_insufficient_receivers", 0.0)
                )
                self._detection_reports_total += 1
                if mlat_skipped_insufficient_receivers > 0.5:
                    self._detection_mlat_skipped_insufficient_receivers += 1
                else:
                    self._detection_mlat_attempted += 1

                if combined_alert > 0.5:
                    self.spoofers.add(serial)
                    if self._first_detection_time_s is None:
                        self._first_detection_time_s = report_time
                    if self._detection_latency_s is None:
                        t_first = self._first_seen_time_s.get(int(serial), report_time)
                        self._detection_latency_s = max(0.0, report_time - t_first)
                    print(
                        f"[DETECT] spoofer serial={serial} detected "
                        f"kf_max_nis={kf_max_nis:.2f} mlat_score={mlat_score:.2f} "
                        f"tx_samples={len(self._tx_power_samples.get(serial, []))}",
                        flush=True,
                    )

                    # Initialize tracked TX estimate from detection-time MLAT samples.
                    tx_samples = self._tx_power_samples.get(serial, [])
                    if tx_samples:
                        self._spoofer_tx_estimate_dbm[serial] = float(np.median(tx_samples))
                    else:
                        self._spoofer_tx_estimate_dbm[serial] = 0.0

                    # Initialize IMM with accumulated MLAT estimates if available.
                    self._imm[serial] = IMMEstimator(
                        dt=IMM_DT,
                        cv_pos_noise=IMM_CV_POS_NOISE,
                        cv_vel_noise=IMM_CV_VEL_NOISE,
                        cv_measurement_noise=IMM_CV_MEAS_NOISE,
                        ca_pos_noise=IMM_CA_POS_NOISE,
                        ca_vel_noise=IMM_CA_VEL_NOISE,
                        ca_acc_noise=IMM_CA_ACC_NOISE,
                        ca_measurement_noise=IMM_CA_MEAS_NOISE,
                        init_mode_cv=IMM_INIT_MODE_CV,
                        p_cv_stay=IMM_P_CV_STAY,
                        p_ca_stay=IMM_P_CA_STAY,
                    )
                    pos_samples = self._pos_samples.get(serial, [])
                    if pos_samples:
                        for sample in pos_samples:
                            if (
                                isinstance(sample, (tuple, list))
                                and len(sample) == 2
                                and np.isscalar(sample[0])
                            ):
                                p_time, p = float(sample[0]), np.asarray(sample[1], dtype=float)
                            else:
                                p_time, p = report_time, np.asarray(sample, dtype=float)
                            self._imm[serial].update(
                                p,
                                do_predict=False,
                                measurement_time_s=p_time,
                            )
                    else:
                        self._imm[serial].update(
                            claimed_pos,
                            do_predict=False,
                            measurement_time_s=report_time,
                        )

                    # Clean up detection buffers
                    self._tx_power_samples.pop(serial, None)
                    self._pos_samples.pop(serial, None)
            elif not detection_enabled:
                # Simulation policy: after first spoofer is identified, stop
                # running detection for unknown serials to avoid extra NLLS work.
                self._tx_power_samples.pop(serial, None)
                self._pos_samples.pop(serial, None)

        if serial in self.spoofers:
            self.rid_positions.pop(serial, None)

        result = {
            "log": {
                "mlat_raw_error": mlat_raw_error,
                "spoofer_detected": 1.0 if serial in self.spoofers else 0.0,
                "num_spoofers": float(len(self.spoofers)),
                "kf_max_nis": float(kf_max_nis),
                "kf_has_data": float(kf_has_data),
                "receiver_count": float(receiver_count),
                "mlat_skipped_insufficient_receivers": float(mlat_skipped_insufficient_receivers),
                "mlat_score": float(mlat_score),
                "combined_alert": float(combined_alert),
                "tx_power_est_dbm": float(self._spoofer_tx_estimate_dbm.get(serial, 0.0)),
                "tx_power_oracle_dbm": float(tx_oracle_dbm),
                **_IMM_LOG_DEFAULTS,
            },
        }
        if "claimed_pos" in visualization:
            # Visualization cue: once spoofing is detected for this serial,
            # claimed RID points switch color (handled by C++ OSG renderer).
            visualization["claimed_detected"] = bool(serial in self.spoofers)
        if visualization:
            result["visualization"] = visualization
        self._reports_time_total_s += max(0.0, time.perf_counter() - t0)
        self._reports_calls += 1
        return result

    def _benign_positions_for_nmac(self, ground_truth: dict | None) -> dict[int, np.ndarray]:
        """Prefer simulation ground truth from GcsModule; fall back to RID."""
        if ground_truth is not None and len(ground_truth) > 0:
            benign: dict[int, np.ndarray] = {}
            for k, v in ground_truth.items():
                hid = int(k)
                # Exclude true spoofer host from benign metrics even before
                # spoofing detection declares the serial.
                if self._spoofer_host is not None and hid == self._spoofer_host:
                    continue
                if hid in self.spoofers:
                    continue
                benign[hid] = np.asarray(v, dtype=float).ravel()[:3]
            return benign
        return {
            int(s): np.array(p, dtype=float)
            for s, p in self.rid_positions.items()
            if (self._spoofer_host is None or int(s) != self._spoofer_host)
            if s not in self.spoofers
        }

    def _update_nmac_metrics(
        self,
        sim_time: float,
        unsafe_regions: list[dict],
        ground_truth: dict | None,
        spoofer_hid: int | None,
    ) -> None:
        """Proximity NMAC (< NMAC_PROXIMITY_M) and spoofer-unsafe ellipsoid NMAC."""
        benign = self._benign_positions_for_nmac(ground_truth)
        serials = sorted(benign.keys())

        active_pairs: set[tuple[int, int]] = set()
        for i in range(len(serials)):
            for j in range(i + 1, len(serials)):
                a, b = serials[i], serials[j]
                pa, pb = benign[a], benign[b]
                d = float(np.linalg.norm(pa - pb))
                if d < NMAC_PROXIMITY_M:
                    pair = (a, b) if a < b else (b, a)
                    active_pairs.add(pair)
                    if pair not in self._nmac_proximity_pairs_active:
                        self.nmac_proximity_count += 1
                        print(
                            f"[NMAC] proximity serial_a={a} serial_b={b} dist_m={d:.2f} "
                            f"t={sim_time:.3f}s total_proximity_nmac={self.nmac_proximity_count}",
                            flush=True,
                        )
        self._nmac_proximity_pairs_active = active_pairs

        spoofer_pos: np.ndarray | None = None
        if spoofer_hid is not None:
            if ground_truth is not None and len(ground_truth) > 0:
                gt_pos = ground_truth.get(spoofer_hid)
                if gt_pos is None:
                    gt_pos = ground_truth.get(str(spoofer_hid))
                if gt_pos is not None:
                    spoofer_pos = np.asarray(gt_pos, dtype=float).ravel()[:3]
            if spoofer_pos is None:
                rid_pos = self.rid_positions.get(int(spoofer_hid))
                if rid_pos is not None:
                    spoofer_pos = np.asarray(rid_pos, dtype=float).ravel()[:3]

        active_benign_spoofer: set[int] = set()
        min_dist_now: float | None = None
        if spoofer_pos is not None:
            for s, pos in benign.items():
                d = float(np.linalg.norm(pos - spoofer_pos))
                if min_dist_now is None or d < min_dist_now:
                    min_dist_now = d
                if d < NMAC_PROXIMITY_M:
                    active_benign_spoofer.add(s)
                    if s not in self._nmac_benign_spoofer_active:
                        self.nmac_benign_spoofer_count += 1
                        print(
                            f"[NMAC] benign_spoofer serial={s} spoofer={spoofer_hid} "
                            f"dist_m={d:.2f} t={sim_time:.3f}s "
                            f"total_benign_spoofer_nmac={self.nmac_benign_spoofer_count}",
                            flush=True,
                        )
        self._nmac_benign_spoofer_active = active_benign_spoofer
        if min_dist_now is not None:
            self.min_benign_spoofer_distance_now_m = float(min_dist_now)
            if min_dist_now < self.min_benign_spoofer_distance_m:
                self.min_benign_spoofer_distance_m = float(min_dist_now)
        else:
            self.min_benign_spoofer_distance_now_m = -1.0

        inside_now: set[int] = set()
        for s, pos in benign.items():
            inside = False
            for reg in unsafe_regions:
                mu = np.asarray(reg["mu"], dtype=float)
                sigma = np.asarray(reg["sigma"], dtype=float)
                alpha = float(reg.get("alpha", self.alpha))
                if not is_safe(pos, mu, sigma, alpha):
                    inside = True
                    break
            if inside:
                inside_now.add(s)
                if s not in self._nmac_serial_inside_unsafe:
                    self.nmac_spoofer_unsafe_count += 1
                    print(
                        f"[NMAC] spoofer_unsafe serial={s} t={sim_time:.3f}s "
                        f"pos=({pos[0]:.1f},{pos[1]:.1f},{pos[2]:.1f}) "
                        f"total_spoofer_unsafe_nmac={self.nmac_spoofer_unsafe_count}",
                        flush=True,
                    )
        self._nmac_serial_inside_unsafe = inside_now

    @staticmethod
    def _clamp_covariance_sigma(
        sigma: np.ndarray,
        std_min: float = UNSAFE_STD_MIN_M,
        std_max: float = UNSAFE_STD_MAX_M,
    ) -> np.ndarray:
        """Symmetrize and clamp covariance eigenvalues for stable unsafe region."""
        vmin = max(std_min * std_min, 1e-3)
        vmax = max(vmin, std_max * std_max)
        fallback = np.eye(3) * ((vmin + vmax) * 0.5)

        S = np.asarray(sigma, dtype=float)
        if S.shape != (3, 3):
            return fallback

        # Clean non-finite values before decomposition.
        S = np.nan_to_num(S, nan=0.0, posinf=vmax, neginf=-vmax)
        S = 0.5 * (S + S.T)

        # Robust eigen-decomposition with progressive jitter.
        for k in range(6):
            jitter = (10.0 ** k) * 1e-9
            try:
                vals, vecs = np.linalg.eigh(S + np.eye(3) * jitter)
                vals = np.clip(vals, vmin, vmax)
                Sout = vecs @ np.diag(vals) @ vecs.T
                Sout = 0.5 * (Sout + Sout.T)
                if np.all(np.isfinite(Sout)):
                    return Sout
            except np.linalg.LinAlgError:
                continue

        # Last-resort diagonal approximation if eigh keeps failing.
        d = np.diag(S) if S.shape == (3, 3) else np.array([vmin, vmin, vmin], dtype=float)
        d = np.nan_to_num(d, nan=vmin, posinf=vmax, neginf=vmin)
        d = np.clip(d, vmin, vmax)
        return np.diag(d)

    def _smoothed_unsafe_state(
        self,
        serial: int,
        mu_now: np.ndarray,
        sigma_now: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Smooth unsafe region over time to reduce frame-to-frame flicker and
        disappearing tiny ellipsoids while preserving motion tracking.
        """
        prev = self._published_unsafe.get(serial)
        mu_now = np.asarray(mu_now, dtype=float).ravel()[:3]
        if mu_now.shape[0] < 3:
            mu_now = np.pad(mu_now, (0, 3 - mu_now.shape[0]), mode="constant")
        sigma_now = self._clamp_covariance_sigma(np.asarray(sigma_now, dtype=float))

        # If current estimate is non-finite, keep previous region if available.
        if not np.all(np.isfinite(mu_now)):
            if prev is not None:
                return prev
            mu_now = np.zeros(3, dtype=float)
        mu_now = np.nan_to_num(mu_now, nan=0.0, posinf=0.0, neginf=0.0)

        if prev is None:
            self._published_unsafe[serial] = (mu_now.copy(), sigma_now.copy())
            return mu_now, sigma_now

        mu_prev, sigma_prev = prev
        mu_prev = np.nan_to_num(np.asarray(mu_prev, dtype=float).ravel()[:3], nan=0.0, posinf=0.0, neginf=0.0)
        sigma_prev = self._clamp_covariance_sigma(np.asarray(sigma_prev, dtype=float))

        # Reject/limit implausible center teleportation in one tick.
        dmu = mu_now - mu_prev
        dmu_norm = float(np.linalg.norm(dmu))
        if dmu_norm > UNSAFE_MAX_CENTER_STEP_M and dmu_norm > 1e-6:
            mu_now = mu_prev + dmu * (UNSAFE_MAX_CENTER_STEP_M / dmu_norm)

        # Limit one-tick covariance growth to avoid "all agents inside at once".
        tr_prev = float(np.trace(sigma_prev))
        tr_now = float(np.trace(sigma_now))
        if tr_prev > 1e-9 and tr_now > tr_prev * UNSAFE_MAX_TRACE_GROWTH:
            sigma_now = sigma_now * ((tr_prev * UNSAFE_MAX_TRACE_GROWTH) / tr_now)
            sigma_now = self._clamp_covariance_sigma(sigma_now)

        a_mu = float(np.clip(UNSAFE_MU_SMOOTH, 0.0, 1.0))
        a_sig = float(np.clip(UNSAFE_SIGMA_SMOOTH, 0.0, 1.0))
        mu_pub = (1.0 - a_mu) * mu_prev + a_mu * mu_now
        sigma_pub = (1.0 - a_sig) * sigma_prev + a_sig * sigma_now
        sigma_pub = self._clamp_covariance_sigma(sigma_pub)

        self._published_unsafe[serial] = (mu_pub.copy(), sigma_pub.copy())
        return mu_pub, sigma_pub

    # ------------------------------------------------------------------
    # Periodic tick callback
    # ------------------------------------------------------------------

    def on_gcs_tick(self, data: dict) -> dict:
        t0 = time.perf_counter()
        host_ids = list(data.get("host_ids", []))
        sim_time = float(data.get("time", 0.0))
        self._max_host_count = max(self._max_host_count, len(host_ids))
        if self._spoofer_host is None and host_ids:
            # Sweep layouts convention: spoofer is last host index.
            self._spoofer_host = max(int(h) for h in host_ids)
        if self._spoofer_host is not None:
            self._visual_spoofer_serial = int(self._spoofer_host)

        unsafe_regions = []
        gt = data.get("ground_truth_positions") or {}
        primary_serial = sorted(self.spoofers)[0] if self.spoofers else None
        primary_diag: dict[str, float] = {
            "mode_prob_cv": float("nan"),
            "mode_prob_ca": float("nan"),
            "nis_cv": float("nan"),
            "nis_ca": float("nan"),
            "nis_mix": float("nan"),
            "last_measurement_time_s": float("nan"),
        }
        primary_est = np.array([float("nan"), float("nan"), float("nan")], dtype=float)
        primary_cov = np.full((3, 3), np.nan, dtype=float)
        primary_true = np.array([float("nan"), float("nan"), float("nan")], dtype=float)

        for serial in self.spoofers:
            imm = self._imm.get(serial)
            if imm is not None and imm._initialized:
                # Continuous motion between RID updates: propagate IMM on each tick.
                max_steps = None if IMM_MAX_PREDICT_STEPS <= 0 else IMM_MAX_PREDICT_STEPS
                imm.predict_only(max_predict_steps=max_steps, do_interaction=False)
                self._ticks_since_spoofer_meas[serial] = self._ticks_since_spoofer_meas.get(serial, 0) + 1
                mu, sigma = imm.get_state()
                mu_pub, sigma_pub = self._smoothed_unsafe_state(serial, mu, sigma)
                unsafe_regions.append(unsafe_region_to_dict(mu_pub, sigma_pub, self.alpha))
                if primary_serial is not None and int(serial) == int(primary_serial):
                    primary_diag = imm.get_diagnostics()
                    primary_est = np.asarray(mu, dtype=float).ravel()[:3]
                    if primary_est.shape[0] < 3:
                        primary_est = np.pad(primary_est, (0, 3 - primary_est.shape[0]), mode="constant")
                    primary_cov = np.asarray(sigma, dtype=float)
                    if primary_cov.shape != (3, 3):
                        primary_cov = np.full((3, 3), np.nan, dtype=float)
                    gt_pos = gt.get(int(serial))
                    if gt_pos is None:
                        gt_pos = gt.get(str(serial))
                    if gt_pos is not None:
                        primary_true = np.asarray(gt_pos, dtype=float).ravel()[:3]
                        if primary_true.shape[0] < 3:
                            primary_true = np.pad(primary_true, (0, 3 - primary_true.shape[0]), mode="constant")

        # Robustness: if no fresh unsafe region is available this tick, keep
        # broadcasting the last valid one so planner constraints do not drop out.
        stale_unsafe_used = False
        if not unsafe_regions and self._last_primary_unsafe is not None:
            unsafe_regions = [self._last_primary_unsafe]
            stale_unsafe_used = True

        primary_unsafe = unsafe_regions[0] if unsafe_regions else None
        if primary_unsafe is not None:
            self._last_primary_unsafe = primary_unsafe

        # Approximate unsafe-bubble "radius" for charting/scalability diagnostics:
        # max principal-axis radius of the 3D ellipsoid at the chosen alpha level.
        unsafe_radius_max_now = 0.0
        if primary_unsafe is not None:
            sigma = np.asarray(primary_unsafe.get("sigma"), dtype=float)
            try:
                lam_max = float(np.max(np.linalg.eigvalsh(sigma)))
                lam_max = max(lam_max, 0.0)
                boundary = float(ellipsoid_threshold(float(primary_unsafe.get("alpha", self.alpha)), ndim=3))
                unsafe_radius_max_now = float(np.sqrt(boundary * lam_max))
            except Exception:
                unsafe_radius_max_now = 0.0

        # Simulation-only diagnostic: does unsafe ellipsoid contain true spoofer?
        # ground_truth_positions is provided by GcsModule from mobility state.
        containment_now = 0.0
        containment_miss_now = 0.0
        containment_margin_now = 0.0
        if primary_unsafe is not None and gt:
            mu = np.asarray(primary_unsafe["mu"], dtype=float)
            sigma = np.asarray(primary_unsafe["sigma"], dtype=float)
            alpha = float(primary_unsafe.get("alpha", self.alpha))
            boundary = float(ellipsoid_threshold(alpha, ndim=3))
            for serial in self.spoofers:
                pos = gt.get(int(serial))
                if pos is None:
                    pos = gt.get(str(serial))
                if pos is None:
                    continue
                self._spoofer_containment_total += 1
                pos_arr = np.asarray(pos, dtype=float)
                m2 = float(mahalanobis_squared(pos_arr, mu, sigma))
                containment_margin_now = boundary - m2
                inside = m2 <= boundary
                if inside:
                    self._spoofer_containment_hits += 1
                    containment_now = 1.0
                    containment_miss_now = 0.0
                else:
                    containment_miss_now = 1.0
                # Localization accuracy: unsafe-region center vs true spoofer position.
                loc_err = float(np.linalg.norm(pos_arr - mu))
                self._loc_err_abs_sum += loc_err
                self._loc_err_sq_sum += loc_err * loc_err
                self._loc_samples += 1

        self._update_nmac_metrics(
            sim_time,
            unsafe_regions,
            data.get("ground_truth_positions"),
            self._spoofer_host,
        )

        commands = {}
        for hid in host_ids:
            if hid in self.spoofers:
                continue

            other_positions = {}
            for serial, pos in self.rid_positions.items():
                if serial not in self.spoofers and int(serial) != hid:
                    other_positions[int(serial)] = list(pos)

            cmd = {
                "unsafe_region": primary_unsafe,
                "unsafe_regions": unsafe_regions,
                "other_positions": other_positions,
                "agent_radius": self.agent_radius,
                "alpha": self.alpha,
                "host_id": hid,
            }
            if hid in self.goals:
                cmd["goal"] = self.goals[hid]

            commands[hid] = cmd

        visualization = {}
        if primary_unsafe is not None:
            visualization["ellipsoid"] = primary_unsafe
            visualization["detected"] = True

        out = {
            "commands": commands,
            "visualization": visualization,
            "log": {
                "tick_count": data.get("tick_count", 0),
                "has_unsafe_region": 1.0 if primary_unsafe else 0.0,
                "using_stale_unsafe_region": 1.0 if stale_unsafe_used else 0.0,
                "num_spoofers": float(len(self.spoofers)),
                "spoofer_ticks_since_measurement": float(
                    max([self._ticks_since_spoofer_meas.get(s, 0) for s in self.spoofers], default=0)
                ),
                "spoofer_inside_unsafe_now": containment_now,
                "spoofer_not_contained_now": containment_miss_now,
                # Positive => contained, negative => outside by that margin.
                "spoofer_containment_margin": containment_margin_now,
                "spoofer_containment_rate": (
                    float(self._spoofer_containment_hits) / float(self._spoofer_containment_total)
                    if self._spoofer_containment_total > 0 else 0.0
                ),
                "unsafe_radius_max_m": float(unsafe_radius_max_now),
                "nmac_proximity_total": float(self.nmac_proximity_count),
                "nmac_benign_spoofer_total": float(self.nmac_benign_spoofer_count),
                "nmac_spoofer_unsafe_total": float(self.nmac_spoofer_unsafe_count),
                "min_benign_spoofer_distance_now_m": float(self.min_benign_spoofer_distance_now_m),
                "min_benign_spoofer_distance_running_min_m": (
                    float(self.min_benign_spoofer_distance_m)
                    if np.isfinite(self.min_benign_spoofer_distance_m) else -1.0
                ),
                "gcs_reports_mean_ms": (
                    1000.0 * self._reports_time_total_s / float(self._reports_calls)
                    if self._reports_calls > 0 else 0.0
                ),
                "gcs_tick_mean_ms": (
                    1000.0 * self._tick_time_total_s / float(self._tick_calls)
                    if self._tick_calls > 0 else 0.0
                ),
                "detection_latency_s": float(self._detection_latency_s) if self._detection_latency_s is not None else -1.0,
                "localization_rmse_m": (
                    float(np.sqrt(self._loc_err_sq_sum / float(self._loc_samples)))
                    if self._loc_samples > 0 else -1.0
                ),
                "imm_mode_prob_cv": float(primary_diag.get("mode_prob_cv", float("nan"))),
                "imm_mode_prob_ca": float(primary_diag.get("mode_prob_ca", float("nan"))),
                "imm_nis_cv": float(primary_diag.get("nis_cv", float("nan"))),
                "imm_nis_ca": float(primary_diag.get("nis_ca", float("nan"))),
                "imm_nis_mix": float(primary_diag.get("nis_mix", float("nan"))),
                "imm_last_measurement_time_s": float(primary_diag.get("last_measurement_time_s", float("nan"))),
                "imm_est_x_m": float(primary_est[0]),
                "imm_est_y_m": float(primary_est[1]),
                "imm_est_z_m": float(primary_est[2]),
                "imm_true_x_m": float(primary_true[0]),
                "imm_true_y_m": float(primary_true[1]),
                "imm_true_z_m": float(primary_true[2]),
                "imm_error_norm_m": (
                    float(np.linalg.norm(primary_true - primary_est))
                    if np.all(np.isfinite(primary_true)) and np.all(np.isfinite(primary_est))
                    else float("nan")
                ),
                "imm_cov_trace_m2": (
                    float(np.trace(primary_cov)) if np.all(np.isfinite(primary_cov)) else float("nan")
                ),
                "imm_nees": (
                    float(mahalanobis_squared(primary_true, primary_est, primary_cov))
                    if np.all(np.isfinite(primary_true))
                    and np.all(np.isfinite(primary_est))
                    and np.all(np.isfinite(primary_cov))
                    else float("nan")
                ),
            },
        }
        self._tick_time_total_s += max(0.0, time.perf_counter() - t0)
        self._tick_calls += 1
        return out

    def on_gcs_finish(self) -> dict:
        """Simulation end: emit final NMAC totals as OMNeT++ scalars (.sca) for analysis filters."""
        return {
            "scalars": {
                "nmac_proximity_final": float(self.nmac_proximity_count),
                "nmac_benign_spoofer_final": float(self.nmac_benign_spoofer_count),
                "nmac_spoofer_unsafe_final": float(self.nmac_spoofer_unsafe_count),
                "num_spoofers_final": float(len(self.spoofers)),
                "spoofer_containment_rate_final": (
                    float(self._spoofer_containment_hits) / float(self._spoofer_containment_total)
                    if self._spoofer_containment_total > 0 else 0.0
                ),
                "min_benign_spoofer_distance_final_m": (
                    float(self.min_benign_spoofer_distance_m)
                    if np.isfinite(self.min_benign_spoofer_distance_m) else -1.0
                ),
                "gcs_reports_mean_ms_final": (
                    1000.0 * self._reports_time_total_s / float(self._reports_calls)
                    if self._reports_calls > 0 else 0.0
                ),
                "gcs_tick_mean_ms_final": (
                    1000.0 * self._tick_time_total_s / float(self._tick_calls)
                    if self._tick_calls > 0 else 0.0
                ),
                "gcs_compute_total_s_final": float(self._reports_time_total_s + self._tick_time_total_s),
                "num_hosts_observed_final": float(self._max_host_count),
                "first_detection_time_s_final": float(self._first_detection_time_s) if self._first_detection_time_s is not None else -1.0,
                "detection_latency_s_final": float(self._detection_latency_s) if self._detection_latency_s is not None else -1.0,
                "detection_reports_total_final": float(self._detection_reports_total),
                "detection_mlat_attempted_final": float(self._detection_mlat_attempted),
                "detection_mlat_skipped_insufficient_receivers_final": float(
                    self._detection_mlat_skipped_insufficient_receivers
                ),
                "detection_mlat_skipped_insufficient_receivers_fraction_final": (
                    float(self._detection_mlat_skipped_insufficient_receivers)
                    / float(self._detection_reports_total)
                    if self._detection_reports_total > 0 else 0.0
                ),
                "localization_mae_m_final": (
                    float(self._loc_err_abs_sum / float(self._loc_samples))
                    if self._loc_samples > 0 else -1.0
                ),
                "localization_rmse_m_final": (
                    float(np.sqrt(self._loc_err_sq_sum / float(self._loc_samples)))
                    if self._loc_samples > 0 else -1.0
                ),
                "localization_samples_final": float(self._loc_samples),
                "imm_dt_s_final": float(IMM_DT),
                "imm_init_mode_cv_final": float(IMM_INIT_MODE_CV),
                "imm_p_cv_stay_final": float(IMM_P_CV_STAY),
                "imm_p_ca_stay_final": float(IMM_P_CA_STAY),
                "imm_cv_pos_noise_final": float(IMM_CV_POS_NOISE),
                "imm_cv_vel_noise_final": float(IMM_CV_VEL_NOISE),
                "imm_cv_meas_noise_final": float(IMM_CV_MEAS_NOISE),
                "imm_ca_pos_noise_final": float(IMM_CA_POS_NOISE),
                "imm_ca_vel_noise_final": float(IMM_CA_VEL_NOISE),
                "imm_ca_acc_noise_final": float(IMM_CA_ACC_NOISE),
                "imm_ca_meas_noise_final": float(IMM_CA_MEAS_NOISE),
            },
        }
