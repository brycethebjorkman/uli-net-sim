"""
Baseline GCS: trust reported RID positions (no detection, localization, or
chance constraints). Same command shape as SpoofingAwareGcs so MdpTrajectoryPlanner
is unchanged; unsafe regions are always empty.

NMAC proximity uses ground truth when provided and excludes the spoofer host as
``max(host_ids)`` (or optional ``spoofer_host=``), matching typical circle layouts
where the spoofer is the last host. ``nmac_spoofer_unsafe_*`` stays zero.

INI:
    *.gcs[0].pyClass = "pymodules.planners.trust_rid_gcs.TrustRidGcs"
"""

from __future__ import annotations

import numpy as np

from pymodules.gcs.chance_constraint import is_safe

NMAC_PROXIMITY_M = 10.0
DEFAULT_AGENT_RADIUS = 60.0


class TrustRidGcs:
    def __init__(
        self,
        alpha: float = 0.05,
        agent_radius: float = DEFAULT_AGENT_RADIUS,
        goals: dict | None = None,
        spoofer_host: int | None = None,
    ):
        self.alpha = alpha
        self.agent_radius = agent_radius
        self.goals = goals or {}
        self._spoofer_host = spoofer_host

        self.rid_positions: dict[int, tuple[float, float, float]] = {}
        self.federate_ids: set[int] = set()

        self._nmac_proximity_pairs_active: set[tuple[int, int]] = set()
        self._nmac_serial_inside_unsafe: set[int] = set()
        self.nmac_proximity_count = 0
        self.nmac_spoofer_unsafe_count = 0

    def on_gcs_reports(self, data: dict) -> dict | None:
        serial = data["serial_number"]
        claimed_pos = np.array(data["claimed_pos"])
        reports = data["reports"]

        self.rid_positions[serial] = tuple(claimed_pos)
        for r in reports:
            self.federate_ids.add(r["host_id"])

        return {
            "log": {
                "mlat_raw_error": 0.0,
                "spoofer_detected": 0.0,
                "num_spoofers": 0.0,
                "hit_count": 0.0,
            },
        }

    def _spoofer_hid(self, host_ids: list[int]) -> int | None:
        if self._spoofer_host is not None:
            return self._spoofer_host
        if not host_ids:
            return None
        return max(int(h) for h in host_ids)

    def _benign_positions_for_nmac(
        self,
        ground_truth: dict | None,
        spoofer_hid: int | None,
    ) -> dict[int, np.ndarray]:
        if ground_truth is not None and len(ground_truth) > 0:
            benign: dict[int, np.ndarray] = {}
            for k, v in ground_truth.items():
                hid = int(k)
                if spoofer_hid is not None and hid == spoofer_hid:
                    continue
                benign[hid] = np.asarray(v, dtype=float).ravel()[:3]
            return benign
        # Fall back to RID; still exclude spoofer index if known
        out: dict[int, np.ndarray] = {}
        for s, p in self.rid_positions.items():
            hid = int(s)
            if spoofer_hid is not None and hid == spoofer_hid:
                continue
            out[hid] = np.array(p, dtype=float)
        return out

    def _update_nmac_metrics(
        self,
        sim_time: float,
        unsafe_regions: list[dict],
        ground_truth: dict | None,
        spoofer_hid: int | None,
    ) -> None:
        benign = self._benign_positions_for_nmac(ground_truth, spoofer_hid)
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

    def on_gcs_tick(self, data: dict) -> dict:
        host_ids = list(data.get("host_ids", []))
        sim_time = float(data.get("time", 0.0))

        if self._spoofer_host is None and host_ids:
            self._spoofer_host = max(int(h) for h in host_ids)

        spoofer_hid = self._spoofer_hid(host_ids)
        unsafe_regions: list[dict] = []

        self._update_nmac_metrics(
            sim_time,
            unsafe_regions,
            data.get("ground_truth_positions"),
            spoofer_hid,
        )

        commands = {}
        for hid in host_ids:
            if spoofer_hid is not None and int(hid) == spoofer_hid:
                continue

            other_positions = {}
            for serial, pos in self.rid_positions.items():
                if spoofer_hid is not None and int(serial) == spoofer_hid:
                    continue
                if int(serial) != hid:
                    other_positions[int(serial)] = list(pos)

            cmd = {
                "unsafe_region": None,
                "unsafe_regions": unsafe_regions,
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
            "visualization": {},
            "log": {
                "tick_count": data.get("tick_count", 0),
                "has_unsafe_region": 0.0,
                "num_spoofers": 0.0,
                "nmac_proximity_total": float(self.nmac_proximity_count),
                "nmac_spoofer_unsafe_total": float(self.nmac_spoofer_unsafe_count),
            },
        }

    def on_gcs_finish(self) -> dict:
        return {
            "scalars": {
                "nmac_proximity_final": float(self.nmac_proximity_count),
                "nmac_spoofer_unsafe_final": float(self.nmac_spoofer_unsafe_count),
            },
        }
