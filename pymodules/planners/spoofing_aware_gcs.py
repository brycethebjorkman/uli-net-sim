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
    Position-only multilateration (3 unknowns) with locked TX power →
    overdetermined (N eqs / 3 unknowns). Feed measurements to per-spoofer
    IMM for state estimation and chance-constraint computation.

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

from pymodules.gcs.chance_constraint import is_safe, unsafe_region_to_dict
from pymodules.gcs.imm_estimator import IMMEstimator
from pymodules.gcs.multilateration import (
    multilaterate_with_tx_power,
    multilaterate_position,
)

MIN_RECEIVERS = 4
DETECTION_THRESHOLD_M = 30.0
DETECT_COUNT = 3              # consecutive hits to declare spoofer
DEFAULT_AGENT_RADIUS = 60.0

# NMAC: pairwise proximity (m); spoofer unsafe uses chance-constraint ellipsoid (is_safe)
NMAC_PROXIMITY_M = 10.0


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

        # Latest RID positions for cooperative agents
        self.rid_positions: dict[int, tuple[float, float, float]] = {}
        self.federate_ids: set[int] = set()

        # NMAC: edge-detection state (see module docstring)
        self._nmac_proximity_pairs_active: set[tuple[int, int]] = set()
        self._nmac_serial_inside_unsafe: set[int] = set()
        self.nmac_proximity_count = 0
        self.nmac_spoofer_unsafe_count = 0

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

        if serial in self.spoofers:
            # ── Phase 2: localization (position-only, TX power locked) ──
            visualization["claimed_pos"] = [float(c) for c in claimed_pos]

            if len(rx_positions) >= 3:
                imm = self._imm[serial]
                if imm._initialized:
                    mlat_init, _ = imm.get_state()
                else:
                    mlat_init = np.mean(rx_positions, axis=0)

                est_pos = multilaterate_position(
                    rx_positions, rssi_values, mlat_init,
                    self._spoofer_tx_power[serial],
                )
                if est_pos is not None:
                    imm.update(est_pos)
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

                        # Lock TX power as median of all accumulated estimates
                        tx_samples = self._tx_power_samples[serial]
                        self._spoofer_tx_power[serial] = float(np.median(tx_samples))

                        # Initialize IMM with all accumulated position estimates
                        self._imm[serial] = IMMEstimator(dt=1.0)
                        for p in self._pos_samples[serial]:
                            self._imm[serial].update(p)

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
                mu, sigma = imm.get_state()
                unsafe_regions.append(unsafe_region_to_dict(mu, sigma, self.alpha))

        primary_unsafe = unsafe_regions[0] if unsafe_regions else None

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
                "num_spoofers": float(len(self.spoofers)),
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
            },
        }
