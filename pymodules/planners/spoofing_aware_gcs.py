"""
Spoofing-aware GCS: RSSI multilateration detection → position-only localization.

Two-phase pipeline per the paper (AIAA SciTech '26, Sec. V-B):

  Phase 1 — Detection (runs on EVERY transmitter):
    For every transmission from an unknown serial, jointly estimate position +
    TX power via NLLS. Track raw position error with a consecutive-hit counter.
    When the raw error exceeds the threshold for DETECT_COUNT consecutive
    transmissions, the serial is flagged as a spoofer. TX power is locked as
    the median of all joint estimates accumulated during detection.

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
    - Proximity: any pair of benign agents with 3D separation < 10 m (new
      entry into that condition per pair counts once until they separate).
    - Spoofer unsafe: benign agent inside the chance-constraint ellipsoid
      (same is_safe test as the MDP hard constraint); entry events per serial.
  End-of-run: ``on_gcs_finish`` records scalars ``nmac_proximity_final`` and
  ``nmac_spoofer_unsafe_final`` (cumulative totals) to the .sca file for
  cross-run bar charts; tick ``log`` vectors remain for time series.

INI usage:
    *.gcs[0].pyClass = "pymodules.planners.spoofing_aware_gcs.SpoofingAwareGcs"
    *.gcs[0].tickInterval = 0.25s
    *.gcs[0].sendControlCommands = true
"""

import numpy as np

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

MIN_RECEIVERS = 4
DETECTION_THRESHOLD_M = 30.0
DETECT_COUNT = 3              # consecutive hits to declare spoofer
DEFAULT_AGENT_RADIUS = 60.0

# NMAC: pairwise proximity (m); spoofer unsafe uses chance-constraint ellipsoid (is_safe)
NMAC_PROXIMITY_M = 10.0
TX_EST_EMA = 0.2              # smoothing on dynamic TX estimate
TX_EST_MAX_STEP_DB = 2.0      # max per-update TX change (dB)
TX_LOCK_MIN_DBM = -50.0
TX_LOCK_MAX_DBM = 50.0
DEBUG_USE_GROUND_TRUTH_TX = True   # DEBUG ONLY: use tx_true_pos to estimate TX
FSPL_CONSTANT_DB = 40.04
IMM_DT = 0.25
IMM_MAX_PREDICT_STEPS = 0     # 0 => unlimited predict-only propagation between measurements
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
        self._hit_count: dict[int, int] = {}            # consecutive detections
        self._tx_power_samples: dict[int, list] = {}    # all joint TX estimates
        self._pos_samples: dict[int, list] = {}         # all joint pos estimates

        # Post-detection state: per-spoofer tracking
        self.spoofers: set[int] = set()
        self._imm: dict[int, IMMEstimator] = {}
        self._spoofer_tx_power: dict[int, float] = {}
        self._published_unsafe: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        self._last_primary_unsafe: dict | None = None
        self._ticks_since_spoofer_meas: dict[int, int] = {}
        self._claimed_bias: dict[int, np.ndarray] = {}

        # Latest RID positions for cooperative agents
        self.rid_positions: dict[int, tuple[float, float, float]] = {}
        self.federate_ids: set[int] = set()

        # NMAC: edge-detection state (see module docstring)
        self._nmac_proximity_pairs_active: set[tuple[int, int]] = set()
        self._nmac_serial_inside_unsafe: set[int] = set()
        self.nmac_proximity_count = 0
        self.nmac_spoofer_unsafe_count = 0
        self._spoofer_containment_total = 0
        self._spoofer_containment_hits = 0

    # ------------------------------------------------------------------
    # Per-transmission callback
    # ------------------------------------------------------------------

    def on_gcs_reports(self, data: dict) -> dict | None:
        serial = data["serial_number"]
        claimed_pos = np.array(data["claimed_pos"])
        reports = data["reports"]

        self.rid_positions[serial] = tuple(claimed_pos)

        rx_positions = np.array([r["pos"] for r in reports])
        rssi_values = np.array([r["rssi_dbm"] for r in reports])
        for r in reports:
            self.federate_ids.add(r["host_id"])

        mlat_raw_error = 0.0
        visualization = {}
        tx_oracle_dbm = 0.0

        if serial in self.spoofers:
            # ── Phase 2: localization (dynamic TX estimation) ──
            visualization["claimed_pos"] = [float(c) for c in claimed_pos]

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
                    mlat_init = claimed_pos.copy()
                mlat_init = np.clip(mlat_init,
                                    [-MLAT_INIT_CLIP_XY, -MLAT_INIT_CLIP_XY, -MLAT_INIT_CLIP_Z],
                                    [MLAT_INIT_CLIP_XY, MLAT_INIT_CLIP_XY, MLAT_INIT_CLIP_Z])
                if np.linalg.norm(mlat_init - claimed_pos) > MLAT_INIT_MAX_FROM_CLAIMED:
                    mlat_init = claimed_pos.copy()

                tx_before = self._spoofer_tx_power[serial]
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
                        tx_after = float(np.clip(tx_before + TX_EST_EMA * delta, TX_LOCK_MIN_DBM, TX_LOCK_MAX_DBM))
                        self._spoofer_tx_power[serial] = tx_after
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
                    tx_oracle = float(np.clip(tx_oracle, TX_LOCK_MIN_DBM, TX_LOCK_MAX_DBM))
                    self._spoofer_tx_power[serial] = tx_oracle
                    tx_oracle_dbm = tx_oracle
                    # Re-run position solve with oracle TX for this debug run.
                    est_pos, est_cov = multilaterate_position_with_covariance(
                        rx_positions, rssi_values, mlat_init, self._spoofer_tx_power[serial]
                    )

                if est_pos is None:
                    # Fallback path (3-receiver geometry or joint-solve failure):
                    # use latest TX estimate for position-only solve.
                    est_pos, est_cov = multilaterate_position_with_covariance(
                        rx_positions, rssi_values, mlat_init, self._spoofer_tx_power[serial]
                    )

                used_claimed_fallback = False
                if est_pos is not None and np.all(np.isfinite(est_pos)):
                    est_pos_arr = np.asarray(est_pos, dtype=float).ravel()[:3]
                    # Learn serial-specific claimed->true bias for fallback usage.
                    bias_meas = est_pos_arr - claimed_pos
                    if serial in self._claimed_bias:
                        self._claimed_bias[serial] = (
                            (1.0 - CLAIMED_BIAS_EMA) * self._claimed_bias[serial]
                            + CLAIMED_BIAS_EMA * bias_meas
                        )
                    else:
                        self._claimed_bias[serial] = bias_meas.copy()

                    # Tick path already handles propagation; measurement path only corrects.
                    imm.update(est_pos_arr, meas_cov=est_cov, do_predict=False)
                    self._ticks_since_spoofer_meas[serial] = 0
                elif serial in self._claimed_bias:
                    # When multilateration is unavailable, follow claimed motion with
                    # learned bias and high uncertainty so turn dynamics are retained.
                    pseudo_pos = claimed_pos + self._claimed_bias[serial]
                    pseudo_cov = np.eye(3) * (CLAIMED_FALLBACK_STD_M ** 2)
                    imm.update(pseudo_pos, meas_cov=pseudo_cov, do_predict=False)
                    self._ticks_since_spoofer_meas[serial] = 0
                    used_claimed_fallback = True

                visualization["tx_est"] = float(self._spoofer_tx_power[serial])
                visualization["tx_est_delta"] = float(tx_after - tx_before)
                visualization["used_claimed_fallback"] = bool(used_claimed_fallback)
            else:
                # Fallback even with <3 receivers: keep tracking via claimed motion + learned bias.
                if serial in self._imm and self._imm[serial]._initialized:
                    imm = self._imm[serial]
                    if serial in self._claimed_bias:
                        pseudo_pos = claimed_pos + self._claimed_bias[serial]
                    else:
                        pseudo_pos = claimed_pos.copy()
                    pseudo_cov = np.eye(3) * (CLAIMED_FALLBACK_STD_M ** 2)
                    imm.update(pseudo_pos, meas_cov=pseudo_cov, do_predict=False)
                    self._ticks_since_spoofer_meas[serial] = 0
                    visualization["used_claimed_fallback"] = True
                else:
                    visualization["used_claimed_fallback"] = False
        else:
            # ── Phase 1: detection (runs on every unknown transmitter) ──
            if len(rx_positions) >= MIN_RECEIVERS:
                est_pos, est_tx = multilaterate_with_tx_power(
                    rx_positions, rssi_values, claimed_pos,
                )
                if est_pos is not None and est_tx is not None:
                    mlat_raw_error = float(np.linalg.norm(est_pos - claimed_pos))

                    # Accumulate TX power and position estimates
                    self._tx_power_samples.setdefault(serial, []).append(est_tx)
                    self._pos_samples.setdefault(serial, []).append(est_pos.copy())

                    if mlat_raw_error > DETECTION_THRESHOLD_M:
                        self._hit_count[serial] = self._hit_count.get(serial, 0) + 1
                    else:
                        self._hit_count[serial] = 0

                    if self._hit_count.get(serial, 0) >= DETECT_COUNT:
                        self.spoofers.add(serial)
                        print(
                            f"[DETECT] spoofer serial={serial} detected "
                            f"raw_error_m={mlat_raw_error:.2f} "
                            f"tx_samples={len(self._tx_power_samples.get(serial, []))}",
                            flush=True,
                        )

                        # Lock TX power as median of all accumulated estimates
                        tx_samples = self._tx_power_samples[serial]
                        self._spoofer_tx_power[serial] = float(np.median(tx_samples))

                        # Initialize IMM with all accumulated position estimates
                        self._imm[serial] = IMMEstimator(dt=IMM_DT)
                        for p in self._pos_samples[serial]:
                            self._imm[serial].update(p, do_predict=False)

                        # Clean up detection buffers
                        self._tx_power_samples.pop(serial, None)
                        self._pos_samples.pop(serial, None)
                        self._hit_count.pop(serial, None)

        if serial in self.spoofers:
            self.rid_positions.pop(serial, None)

        result = {
            "log": {
                "mlat_raw_error": mlat_raw_error,
                "spoofer_detected": 1.0 if serial in self.spoofers else 0.0,
                "num_spoofers": float(len(self.spoofers)),
                "hit_count": float(self._hit_count.get(serial, 0)),
                "tx_power_est_dbm": float(self._spoofer_tx_power.get(serial, 0.0)),
                "tx_power_oracle_dbm": float(tx_oracle_dbm),
            },
        }
        if visualization:
            result["visualization"] = visualization
        return result

    def _benign_positions_for_nmac(self, ground_truth: dict | None) -> dict[int, np.ndarray]:
        """Prefer simulation ground truth from GcsModule; fall back to RID."""
        if ground_truth is not None and len(ground_truth) > 0:
            benign: dict[int, np.ndarray] = {}
            for k, v in ground_truth.items():
                hid = int(k)
                if hid in self.spoofers:
                    continue
                benign[hid] = np.asarray(v, dtype=float).ravel()[:3]
            return benign
        return {
            int(s): np.array(p, dtype=float)
            for s, p in self.rid_positions.items()
            if s not in self.spoofers
        }

    def _update_nmac_metrics(
        self,
        sim_time: float,
        unsafe_regions: list[dict],
        ground_truth: dict | None,
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
        host_ids = list(data.get("host_ids", []))
        sim_time = float(data.get("time", 0.0))

        unsafe_regions = []
        for serial in self.spoofers:
            imm = self._imm.get(serial)
            if imm is not None and imm._initialized:
                # Continuous motion between RID updates: propagate IMM on each tick.
                max_steps = None if IMM_MAX_PREDICT_STEPS <= 0 else IMM_MAX_PREDICT_STEPS
                imm.predict_only(max_predict_steps=max_steps)
                self._ticks_since_spoofer_meas[serial] = self._ticks_since_spoofer_meas.get(serial, 0) + 1
                mu, sigma = imm.get_state()
                mu_pub, sigma_pub = self._smoothed_unsafe_state(serial, mu, sigma)
                unsafe_regions.append(unsafe_region_to_dict(mu_pub, sigma_pub, self.alpha))

        # Robustness: if no fresh unsafe region is available this tick, keep
        # broadcasting the last valid one so planner constraints do not drop out.
        stale_unsafe_used = False
        if not unsafe_regions and self._last_primary_unsafe is not None:
            unsafe_regions = [self._last_primary_unsafe]
            stale_unsafe_used = True

        primary_unsafe = unsafe_regions[0] if unsafe_regions else None
        if primary_unsafe is not None:
            self._last_primary_unsafe = primary_unsafe

        # Simulation-only diagnostic: does unsafe ellipsoid contain true spoofer?
        # ground_truth_positions is provided by GcsModule from mobility state.
        gt = data.get("ground_truth_positions") or {}
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

        self._update_nmac_metrics(
            sim_time,
            unsafe_regions,
            data.get("ground_truth_positions"),
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

        return {
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
                "nmac_proximity_total": float(self.nmac_proximity_count),
                "nmac_spoofer_unsafe_total": float(self.nmac_spoofer_unsafe_count),
            },
        }

    def on_gcs_finish(self) -> dict:
        """Simulation end: emit final NMAC totals as OMNeT++ scalars (.sca) for analysis filters."""
        return {
            "scalars": {
                "nmac_proximity_final": float(self.nmac_proximity_count),
                "nmac_spoofer_unsafe_final": float(self.nmac_spoofer_unsafe_count),
                "num_spoofers_final": float(len(self.spoofers)),
                "spoofer_containment_rate_final": (
                    float(self._spoofer_containment_hits) / float(self._spoofer_containment_total)
                    if self._spoofer_containment_total > 0 else 0.0
                ),
            },
        }
