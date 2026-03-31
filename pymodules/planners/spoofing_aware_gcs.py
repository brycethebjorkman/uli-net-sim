"""
Spoofing-aware GCS: detection, IMM localization, chance constraint, broadcast.

Full pipeline per the paper (Sec. IV-VI):
  on_gcs_reports: RSSI multilateration + TX-power KF detection, IMM update
  on_gcs_tick:    IMM predict, chance constraint, broadcast unsafe_region
                  + other_positions + goals to benign agents

All agents (including spoofer) report RSSI to this GCS.
Detection combines:
  1. Multilateration: |est_pos - claimed_pos| > threshold (Sec. V-A)
  2. TX-power Kalman filter: NIS > 6.63 or correction > 6 dB (Sec. V-A)
Localization uses IMM with CV+CA hypotheses (Sec. V-B).
Unsafe region via chance constraint (Sec. VI-A, Eq. 24-25).

INI usage:
    *.gcs[0].pyClass = "pymodules.planners.spoofing_aware_gcs.SpoofingAwareGcs"
    *.gcs[0].tickInterval = 0.25s
    *.gcs[0].sendControlCommands = true
"""


import numpy as np

from pymodules.gcs.chance_constraint import unsafe_region_to_dict
from pymodules.gcs.imm_estimator import IMMEstimator
from pymodules.gcs.multilateration import multilaterate_with_tx
from pymodules.gcs.tx_power_kf import TxPowerKFDetector

DETECTION_THRESHOLD_M = 30.0
KF_NIS_THRESHOLD = 6.63
KF_CORRECTION_THRESHOLD_DB = 6.0
MIN_FEDERATES = 4
DEFAULT_AGENT_RADIUS = 25.0


class SpoofingAwareGcs:
    """
    GCS that detects spoofers, localizes them with IMM, and broadcasts
    unsafe region + other agent positions + goals to all benign hosts.
    """

    def __init__(
        self,
        alpha: float = 0.05,
        agent_radius: float = DEFAULT_AGENT_RADIUS,
        goals: dict | None = None,
    ):
        self.alpha = alpha
        self.agent_radius = agent_radius
        self.goals = goals or {}

        self.spoofers: set[int] = set()
        self.rid_positions: dict[int, tuple[float, float, float]] = {}
        self.imm: IMMEstimator | None = None
        self.spoofer_serial: int | None = None
        self.federate_ids: set[int] = set()
        self.kf_detector = TxPowerKFDetector(
            nis_threshold=KF_NIS_THRESHOLD,
            correction_threshold=KF_CORRECTION_THRESHOLD_DB,
        )

    def on_gcs_reports(self, data: dict) -> dict | None:
        """Per-transmission: multilateration + KF detection, IMM update."""
        serial = data["serial_number"]
        claimed_pos = np.array(data["claimed_pos"])
        reports = data["reports"]

        self.rid_positions[serial] = tuple(claimed_pos)

        rx_positions = []
        rssi_values = []
        report_list = []
        for r in reports:
            self.federate_ids.add(r["host_id"])
            rx_positions.append(r["pos"])
            rssi_values.append(r["rssi_dbm"])
            report_list.append({
                "host_id": r["host_id"], "pos": r["pos"], "rssi_dbm": r["rssi_dbm"]
            })
        rx_positions = np.array(rx_positions)
        rssi_values = np.array(rssi_values)

        kf_nis, kf_spoofer = self.kf_detector.process_report(serial, claimed_pos, report_list)

        position_error = 0.0
        mlat_spoofer = False
        est_pos = None
        if len(rx_positions) >= MIN_FEDERATES:
            est_pos, _ = multilaterate_with_tx(rx_positions, rssi_values, claimed_pos)
            if est_pos is not None:
                position_error = float(np.linalg.norm(est_pos - claimed_pos))
                mlat_spoofer = position_error > DETECTION_THRESHOLD_M

        is_spoofer = mlat_spoofer or kf_spoofer
        if is_spoofer:
            self.spoofers.add(serial)
            self.spoofer_serial = serial
            if self.imm is None:
                self.imm = IMMEstimator(dt=0.25)
            if est_pos is not None:
                self.imm.update(est_pos)

        if serial in self.spoofers:
            self.rid_positions.pop(serial, None)

        return {
            "log": {
                "position_error": position_error,
                "kf_nis": kf_nis,
                "spoofer_detected": 1.0 if is_spoofer else 0.0,
                "num_spoofers": float(len(self.spoofers)),
            },
        }

    def on_gcs_tick(self, data: dict) -> dict:
        """Periodic: IMM predict, chance constraint, broadcast to agents."""
        host_ids = list(data.get("host_ids", []))
        time = data.get("time", 0.0)

        if self.imm is not None:
            self.imm.predict()

        unsafe_region = None
        if self.imm is not None and self.spoofer_serial is not None:
            mu, sigma = self.imm.get_state()
            unsafe_region = unsafe_region_to_dict(mu, sigma, self.alpha)

        commands = {}
        for hid in host_ids:
            if hid in self.spoofers:
                continue

            other_positions = {}
            for serial, pos in self.rid_positions.items():
                if serial not in self.spoofers and int(serial) != hid:
                    other_positions[int(serial)] = list(pos)

            cmd = {
                "unsafe_region": unsafe_region,
                "other_positions": other_positions,
                "agent_radius": self.agent_radius,
                "alpha": self.alpha,
                "host_id": hid,
            }
            if hid in self.goals:
                cmd["goal"] = self.goals[hid]

            commands[hid] = cmd

        return {
            "commands": commands,
            "log": {
                "tick_count": data.get("tick_count", 0),
                "has_unsafe_region": 1.0 if unsafe_region else 0.0,
            },
        }
