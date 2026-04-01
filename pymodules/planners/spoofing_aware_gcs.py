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

INI usage:
    *.gcs[0].pyClass = "pymodules.planners.spoofing_aware_gcs.SpoofingAwareGcs"
    *.gcs[0].tickInterval = 0.25s
    *.gcs[0].sendControlCommands = true
"""

import numpy as np

from pymodules.gcs.chance_constraint import unsafe_region_to_dict
from pymodules.gcs.imm_estimator import IMMEstimator
from pymodules.gcs.multilateration import (
    multilaterate_with_tx_power,
    multilaterate_position,
)

MIN_RECEIVERS = 4
DETECTION_THRESHOLD_M = 30.0
DETECT_COUNT = 3              # consecutive hits to declare spoofer
DEFAULT_AGENT_RADIUS = 60.0


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

    # ------------------------------------------------------------------
    # Periodic tick callback
    # ------------------------------------------------------------------

    def on_gcs_tick(self, data: dict) -> dict:
        host_ids = list(data.get("host_ids", []))

        unsafe_regions = []
        for serial in self.spoofers:
            imm = self._imm.get(serial)
            if imm is not None and imm._initialized:
                mu, sigma = imm.get_state()
                unsafe_regions.append(unsafe_region_to_dict(mu, sigma, self.alpha))

        primary_unsafe = unsafe_regions[0] if unsafe_regions else None

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
            },
        }
