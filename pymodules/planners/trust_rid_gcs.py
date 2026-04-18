"""
Baseline GCS: trust reported RID positions (no detection, localization, or
chance constraints). Same command shape as SpoofingAwareGcs so MdpTrajectoryPlanner
is unchanged; unsafe regions are always empty.

NMAC proximity uses ground truth when provided and excludes the spoofer host
(``num_hosts - 1`` from GcsModule, else ``max(host_ids)``, else optional
``spoofer_host=``). ``nmac_spoofer_unsafe_*`` stays zero because
TrustRid does not publish unsafe regions, but ``nmac_benign_spoofer_*`` still
captures benign-vs-spoofer proximity events.

INI:
    *.gcs[0].pyClass = "pymodules.planners.trust_rid_gcs.TrustRidGcs"
"""

from __future__ import annotations

import numpy as np
import time

from pymodules.gcs.chance_constraint import is_safe

NMAC_PROXIMITY_M = 50.0
DEFAULT_AGENT_RADIUS = 120.0


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
        self._goals_by_host: dict[int, np.ndarray] = {}
        for k, v in self.goals.items():
            try:
                hid = int(k)
            except (TypeError, ValueError):
                continue
            g = np.asarray(v, dtype=float).ravel()[:3]
            if g.shape[0] < 3:
                g = np.pad(g, (0, 3 - g.shape[0]), mode="constant")
            self._goals_by_host[hid] = g
        self._spoofer_host = spoofer_host

        self.rid_positions: dict[int, tuple[float, float, float]] = {}
        self.federate_ids: set[int] = set()

        self._nmac_proximity_pairs_active: set[tuple[int, int]] = set()
        self._nmac_benign_spoofer_active: set[int] = set()
        self._nmac_serial_inside_unsafe: set[int] = set()
        self.nmac_proximity_count = 0
        self.nmac_benign_spoofer_count = 0
        self.nmac_spoofer_unsafe_count = 0
        self.min_benign_spoofer_distance_now_m = -1.0
        self.min_benign_spoofer_distance_m = float("inf")
        self._reports_time_total_s = 0.0
        self._reports_calls = 0
        self._tick_time_total_s = 0.0
        self._tick_calls = 0
        self._max_host_count = 0
        # OSG claimed-position trail (red spheres): same convention as SpoofingAwareGcs.
        self._visual_spoofer_serial: int | None = None

    def _ingest_host_goals(self, host_goals: dict | None) -> None:
        if not host_goals:
            return
        for k, v in host_goals.items():
            try:
                hid = int(k)
            except (TypeError, ValueError):
                continue
            g = np.asarray(v, dtype=float).ravel()[:3]
            if g.shape[0] < 3:
                g = np.pad(g, (0, 3 - g.shape[0]), mode="constant")
            self._goals_by_host[hid] = g

    def on_gcs_reports(self, data: dict) -> dict | None:
        t0 = time.perf_counter()
        serial = data["serial_number"]
        claimed_pos = np.array(data["claimed_pos"])
        reports = data["reports"]

        self.rid_positions[serial] = tuple(claimed_pos)
        for r in reports:
            self.federate_ids.add(r["host_id"])

        visualization: dict = {}
        report_host_ids = [int(h) for h in data.get("host_ids", [])]
        num_hosts = int(data.get("num_hosts", 0))
        if num_hosts > 0:
            self._visual_spoofer_serial = int(num_hosts - 1)
        elif report_host_ids:
            self._visual_spoofer_serial = max(report_host_ids)
        elif self._spoofer_host is not None:
            self._visual_spoofer_serial = int(self._spoofer_host)
        show_claimed_trail = (
            self._visual_spoofer_serial is not None
            and int(serial) == int(self._visual_spoofer_serial)
        )
        if show_claimed_trail:
            visualization["claimed_pos"] = [float(c) for c in claimed_pos]
            if self._visual_spoofer_serial is not None:
                visualization["track_host_id"] = int(self._visual_spoofer_serial)

        out: dict = {
            "log": {
                "mlat_raw_error": 0.0,
                "spoofer_detected": 0.0,
                "num_spoofers": 0.0,
                "hit_count": 0.0,
            },
        }
        if visualization:
            out["visualization"] = visualization
        self._reports_time_total_s += max(0.0, time.perf_counter() - t0)
        self._reports_calls += 1
        return out

    def _spoofer_hid(self, host_ids: list[int], num_hosts: int = 0) -> int | None:
        if self._spoofer_host is not None:
            return self._spoofer_host
        if num_hosts > 0:
            return int(num_hosts - 1)
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

    def on_gcs_tick(self, data: dict) -> dict:
        t0 = time.perf_counter()
        host_ids = list(data.get("host_ids", []))
        sim_time = float(data.get("time", 0.0))
        num_hosts = int(data.get("num_hosts", 0))
        self._max_host_count = max(self._max_host_count, len(host_ids))
        self._ingest_host_goals(data.get("host_goals"))

        if self._spoofer_host is None:
            if num_hosts > 0:
                self._spoofer_host = int(num_hosts - 1)
            elif host_ids:
                self._spoofer_host = max(int(h) for h in host_ids)

        spoofer_hid = self._spoofer_hid(host_ids, num_hosts)
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

            # TrustRID baseline should still drive cooperative avoidance against
            # all claimed positions (including the spoofer's claimed RID track).
            # MDP controller treats everything in other_positions as intruders.
            other_positions = {}
            for serial, pos in self.rid_positions.items():
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
            goal = self._goals_by_host.get(int(hid))
            if goal is None:
                goal = self.goals.get(int(hid), self.goals.get(str(int(hid))))
            if goal is not None:
                cmd["goal"] = np.asarray(goal, dtype=float).ravel()[:3].tolist()

            commands[hid] = cmd

        out = {
            "commands": commands,
            "visualization": {},
            "log": {
                "tick_count": data.get("tick_count", 0),
                "has_unsafe_region": 0.0,
                "num_spoofers": 0.0,
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
            },
        }
        self._tick_time_total_s += max(0.0, time.perf_counter() - t0)
        self._tick_calls += 1
        return out

    def on_gcs_finish(self) -> dict:
        return {
            "scalars": {
                "nmac_proximity_final": float(self.nmac_proximity_count),
                "nmac_benign_spoofer_final": float(self.nmac_benign_spoofer_count),
                "nmac_spoofer_unsafe_final": float(self.nmac_spoofer_unsafe_count),
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
            },
        }
