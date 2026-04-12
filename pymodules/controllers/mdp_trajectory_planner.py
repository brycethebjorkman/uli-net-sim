"""
Decentralized MDP-based trajectory planner controller.

Based on the value function formulation from Taye et al., "Safe and Scalable
Real-Time Trajectory Planning Framework for Urban Air Mobility" (2024), and
the reference MATLAB implementation in Safe-and-Scalable-UAM-Trajectory-Planner.

Value function (Eq. 6):
    V(s) = κ+^d+ * r+  −  κ-^d- * r-

where κ is the discount factor, d is Euclidean distance to the reward source,
and r is the reward magnitude. Positive peaks attract toward goal; negative
peaks repel from intruder aircraft and spoofer unsafe regions.

Each planning step:
  1. Forward-project candidate actions through simplified kinematics (~10s)
  2. Sample 10 future states along each trajectory (cf. neighboringStates.m + fwdProjectFast)
  3. Evaluate closed-form value at each sampled state (valueFunction.m / valueOptimized.m)
  4. Score each action by the maximum value among its samples; pick the highest-scoring action
     (same as max(totalValues,[],'all') in Ownship.selectBestAction when one-step state is
     per-column — i.e. argmax over actions of max over samples along that rollout)
  5. Execute only the one-step-ahead state (receding horizon)

INI usage:
    *.host[*].mobility.pyClass = "pymodules.controllers.mdp_trajectory_planner.MdpTrajectoryPlanner"
"""

import json
import math
import numpy as np

from pymodules.gcs.chance_constraint import (
    ellipsoid_threshold,
)

GRAVITY = 9.81

# ── Planning parameters ──────────────────────────────────────────────────────
REPLAN_DT = 0.5
FWD_DT = 0.5
FWD_STEPS = 20          # 20 × 0.5s = 10s lookahead
# Fewer samples improves runtime while keeping good trajectory discrimination.
SAMPLE_COUNT = 8
ONE_STEP_INDEX = 1       # ~1s ahead, used as execution target
CRUISE_SPEED = 8.0
VERTICAL_SPEED = 3.0          # m/s climb/descend rate used in forward projection
GOAL_REACHED_DIST = 10

# ── Value function parameters (Table 1, scaled for ~500m domain) ─────────────
# Paper uses κ_goal=0.999 for 15km world. For 500m we need steeper gradient:
# V(0)=166,917  V(200)=91,470  V(500)=37,223 — strong pull across whole field
GOAL_REWARD = 500.0
GOAL_DISCOUNT = 0.997

AGENT_REWARD = 9000.0
AGENT_DISCOUNT = 0.99
AGENT_LIMIT = 150.0       # negative peak radius LIM (meters); GCS may override via agent_radius

SPOOFER_REWARD = 9000.0
SPOOFER_DISCOUNT = 0.99
SPOOFER_LIMIT = 150.0    # repulsion radius around unsafe region center (meters)
ELLIPSOID_MARGIN = 1.0   # Mahalanobis-radius margin outside boundary for soft penalty

MIN_CYCLE = 2

# ── Action space ─────────────────────────────────────────────────────────────
NUM_HEADINGS = 16
SPEED_LEVELS = [CRUISE_SPEED, 6.0, 4.0, 2.0, 0.0]
# Commanded flight-path angle set (deg), following the logarithmic spacing
# used in Taye et al. (Eq. 3), mapped to multirotor kinematic projection.
FLIGHT_PATH_ANGLES_DEG = [
    -19.99, -16.24, -12.66, -9.26, -6.02, -2.94, -0.01,
    0.0,
    0.01, 2.94, 6.02, 9.26, 12.66, 16.24, 19.99,
]
# Allow explicit stop actions only when close enough to goal; otherwise
# the optimizer can prefer early hover over continued goal progress.
STOP_ACTION_GOAL_DIST = GOAL_REACHED_DIST


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _peak_value(reward, discount):
    """Normalized peak value: r / (1 - κ^minCycle)"""
    denom = 1.0 - discount ** MIN_CYCLE
    if denom < 1e-12:
        return reward * 1e6
    return reward / denom


class MdpTrajectoryPlanner:
    """Decentralized MDP trajectory planner with cascaded PID low-level control."""

    def __init__(self):
        self.host_id = None
        self.mass = 5.0
        self.target_pos = None
        self.plan_counter = 0
        self.last_time = None
        self.initialized = False

        # GCS data
        self.unsafe_region = None
        self.unsafe_regions_list = None  # all chance-constraint regions (from GCS)
        self.other_positions = {}
        self.agent_radius = AGENT_LIMIT
        self.goal = None
        self.goal_reached = False

        # Waypoints (from INI, used as initial goal if GCS hasn't sent one)
        self.waypoints = []
        self.wp_index = 0

        # PID gains (matching CascadedPidController)
        self.Kp_z = 10.0
        self.Kd_z = 5.0
        self.Kp_xy = 2.0
        self.Kd_xy = 3.0
        self.Kp_angle = 20.0
        self.Kd_angle = 8.0
        self.max_tilt = 0.5

        # Velocity integral (for smoother tracking)
        self.vel_integral = [0.0, 0.0, 0.0]
        self.Ki_vel = 0.1
        self.max_integral = 3.0

        # Precomputed peak values
        self._goal_peak = _peak_value(GOAL_REWARD, GOAL_DISCOUNT)
        self._agent_peak = _peak_value(AGENT_REWARD, AGENT_DISCOUNT)
        self._spoofer_peak = _peak_value(SPOOFER_REWARD, SPOOFER_DISCOUNT)

    # ── GCS command parsing ──────────────────────────────────────────────────

    def _parse_gcs_command(self, gcs_cmd):
        if gcs_cmd is None or not isinstance(gcs_cmd, str):
            return
        try:
            cmd = json.loads(gcs_cmd)
            self.unsafe_region = cmd.get("unsafe_region")
            self.unsafe_regions_list = cmd.get("unsafe_regions")
            new_others = cmd.get("other_positions", {})
            if new_others:
                self.other_positions = new_others
            # Agent-separation radius is MDP-owned (local constant/tuning), not GCS-overridden.
            if "host_id" in cmd:
                self.host_id = cmd["host_id"]
            if "goal" in cmd:
                self.goal = np.array(cmd["goal"], dtype=float)
        except (json.JSONDecodeError, TypeError):
            pass

    def _current_goal(self) -> np.ndarray | None:
        """Return active goal: GCS-provided goal, or next waypoint."""
        if self.goal is not None:
            return self.goal
        if self.waypoints and self.wp_index < len(self.waypoints):
            wp = self.waypoints[self.wp_index]
            return np.array([wp[0], wp[1], wp[2]], dtype=float)
        return None

    # ── Action set ───────────────────────────────────────────────────────────

    def _build_actions(self, pos: np.ndarray) -> list[tuple[float, float, float]]:
        """Build (heading, speed, flight_path_angle_rad) action set."""
        actions = []
        goal = self._current_goal()
        allow_stop = True
        if goal is not None:
            allow_stop = np.linalg.norm(goal - pos) <= STOP_ACTION_GOAL_DIST
        speed_levels = SPEED_LEVELS if allow_stop else [s for s in SPEED_LEVELS if s > 1e-6]
        gamma_levels = [math.radians(g) for g in FLIGHT_PATH_ANGLES_DEG]

        # Uniform headings at each speed and flight-path angle level
        for k in range(NUM_HEADINGS):
            heading = 2.0 * math.pi * k / NUM_HEADINGS
            for speed in speed_levels:
                if speed <= 1e-6:
                    # Stop action: keep level flight angle to avoid duplicates.
                    actions.append((heading, speed, 0.0))
                else:
                    for gamma in gamma_levels:
                        actions.append((heading, speed, gamma))

        # Goal-directed actions at multiple speeds and flight-path angles
        if goal is not None:
            to_goal = goal[:2] - pos[:2]
            d = np.linalg.norm(to_goal)
            if d > 1.0:
                goal_heading = math.atan2(to_goal[1], to_goal[0])
                for speed in speed_levels:
                    if speed <= 1e-6:
                        actions.append((goal_heading, speed, 0.0))
                    else:
                        for gamma in gamma_levels:
                            actions.append((goal_heading, speed, gamma))
                # Flanking: ±15°, ±30° off goal heading
                for offset_deg in [15, 30]:
                    offset = math.radians(offset_deg)
                    for speed in [CRUISE_SPEED, CRUISE_SPEED * 0.5]:
                        for gamma in gamma_levels:
                            actions.append((goal_heading + offset, speed, gamma))
                            actions.append((goal_heading - offset, speed, gamma))

        return actions

    # ── Forward projection ───────────────────────────────────────────────────

    def _forward_project(
        self, pos: np.ndarray, heading: float, speed: float, flight_path_angle: float
    ) -> list[np.ndarray]:
        """Kinematic forward projection with explicit flight-path angle command.

        Uses the simplified guidance kinematics from Taye et al.:
            xdot = V cos(psi) cos(gamma)
            ydot = V sin(psi) cos(gamma)
            zdot = V sin(gamma)
        """
        action = np.array([[heading, speed, flight_path_angle]], dtype=float)
        traj = self._forward_project_many(pos, action)[0]
        return [p.copy() for p in traj]

    def _forward_project_many(self, pos: np.ndarray, actions: np.ndarray) -> np.ndarray:
        """Vectorized rollout for all actions; returns [A, FWD_STEPS, 3]."""
        actions_arr = np.asarray(actions, dtype=float)
        if actions_arr.size == 0:
            return np.empty((0, FWD_STEPS, 3), dtype=float)

        heading = actions_arr[:, 0]
        speed = actions_arr[:, 1]
        flight_path_angle = actions_arr[:, 2]

        speed_xy = speed * np.cos(flight_path_angle)
        vz = np.clip(speed * np.sin(flight_path_angle), -VERTICAL_SPEED, VERTICAL_SPEED)
        deltas = np.stack(
            [
                speed_xy * np.cos(heading) * FWD_DT,
                speed_xy * np.sin(heading) * FWD_DT,
                vz * FWD_DT,
            ],
            axis=1,
        )
        step_count = np.arange(1, FWD_STEPS + 1, dtype=float).reshape(1, FWD_STEPS, 1)
        return pos.reshape(1, 1, 3) + deltas[:, None, :] * step_count

    # ── Value function (Eq. 6) ───────────────────────────────────────────────

    def _value_many(self, positions: np.ndarray) -> np.ndarray:
        """Closed-form value for N states: V = V+ − V−."""
        pts = np.asarray(positions, dtype=float)
        if pts.ndim == 1:
            pts = pts.reshape(1, -1)
        n = pts.shape[0]

        # ── Positive value: goal attraction ──
        v_pos = np.zeros(n, dtype=float)
        goal = self._current_goal()
        if goal is not None:
            d_goal = np.linalg.norm(pts - goal.reshape(1, 3), axis=1)
            v_pos = self._goal_peak * np.power(GOAL_DISCOUNT, d_goal)

        # ── Negative value: agent repulsion ──
        v_neg = np.zeros(n, dtype=float)
        intruders = []
        for oid, op in self.other_positions.items():
            oid_int = int(oid) if isinstance(oid, str) else oid
            if self.host_id is not None and oid_int == self.host_id:
                continue
            intruders.append(np.asarray(op, dtype=float))
        if intruders:
            intr_arr = np.asarray(intruders, dtype=float)
            d_agent = np.linalg.norm(pts[:, None, :] - intr_arr[None, :, :], axis=2)
            within = d_agent < float(self.agent_radius)
            agent_terms = self._agent_peak * np.power(AGENT_DISCOUNT, d_agent)
            agent_terms = np.where(within, agent_terms, 0.0)
            v_neg += np.max(agent_terms, axis=1)

        # ── Negative value: chance-constraint boundary-aware spoofing risk ──
        regions = self._regions_for_unsafe_test()
        for reg in regions:
            mu = np.asarray(reg["mu"], dtype=float)
            sigma = np.asarray(reg["sigma"], dtype=float)
            alpha = float(reg.get("alpha", 0.05))

            d_spoof = np.linalg.norm(pts - mu.reshape(1, 3), axis=1)
            center_term = 0.35 * self._spoofer_peak * np.power(SPOOFER_DISCOUNT, d_spoof)
            v_neg += np.where(d_spoof < SPOOFER_LIMIT, center_term, 0.0)

            boundary = ellipsoid_threshold(alpha, ndim=3)
            if boundary <= 1e-9:
                continue

            # Vectorized Mahalanobis radius for all sampled states.
            sigma_inv = np.linalg.pinv(sigma)
            diff = pts - mu.reshape(1, 3)
            m2 = np.einsum("ni,ij,nj->n", diff, sigma_inv, diff)
            r = np.sqrt(np.maximum(m2, 0.0))
            rb = math.sqrt(boundary)

            inside = r <= rb
            violation = 1.0 + (rb - r) / max(rb, 1e-6)
            v_neg += np.where(inside, self._spoofer_peak * violation, 0.0)

            dr = r - rb
            near = (~inside) & (dr <= ELLIPSOID_MARGIN)
            near_scale = np.exp(-2.5 * dr / max(ELLIPSOID_MARGIN, 1e-6))
            v_neg += np.where(near, 0.75 * self._spoofer_peak * near_scale, 0.0)

        return v_pos - v_neg

    def _value_at(self, pos: np.ndarray) -> float:
        """Closed-form value at a state: V = V+ − V−"""
        return float(self._value_many(np.asarray(pos, dtype=float))[0])

    # ── MDP planning (Algorithm 2) ──────────────────────────────────────────

    def _regions_for_unsafe_test(self) -> list[dict]:
        """Ellipsoids used for trajectory hard constraint (matches GCS broadcast)."""
        if self.unsafe_regions_list:
            return list(self.unsafe_regions_list)
        if self.unsafe_region is not None:
            return [self.unsafe_region]
        return []

    def _trajectory_enters_unsafe_many(self, trajs: np.ndarray) -> np.ndarray:
        """Vectorized hard constraint over trajectories; returns [A] bool mask."""
        arr = np.asarray(trajs, dtype=float)
        if arr.ndim != 3:
            raise ValueError("Expected trajs shape [A, T, 3]")

        regions = self._regions_for_unsafe_test()
        if not regions or arr.shape[0] == 0:
            return np.zeros(arr.shape[0], dtype=bool)

        n_actions, n_steps, _ = arr.shape
        flat = arr.reshape(-1, 3)
        enters = np.zeros(n_actions, dtype=bool)

        for reg in regions:
            mu = np.asarray(reg["mu"], dtype=float)
            sigma = np.asarray(reg["sigma"], dtype=float)
            alpha = float(reg.get("alpha", 0.05))

            boundary = ellipsoid_threshold(alpha, ndim=3)
            if boundary <= 1e-9:
                continue

            sigma_inv = np.linalg.pinv(sigma)
            diff = flat - mu.reshape(1, 3)
            m2 = np.einsum("ni,ij,nj->n", diff, sigma_inv, diff)
            inside = (m2 <= boundary).reshape(n_actions, n_steps)
            enters |= np.any(inside, axis=1)
            if np.all(enters):
                break

        return enters

    def _trajectory_enters_unsafe(self, traj: list[np.ndarray]) -> bool:
        """Hard constraint: reject trajectories that enter the chance-constraint ellipsoid."""
        arr = np.asarray(traj, dtype=float)
        if arr.ndim == 2:
            arr = arr.reshape(1, arr.shape[0], arr.shape[1])
            return bool(self._trajectory_enters_unsafe_many(arr)[0])
        if arr.ndim == 3:
            return bool(np.any(self._trajectory_enters_unsafe_many(arr)))
        raise ValueError("Expected trajectory shape [T,3] or [A,T,3]")

    def _plan(self, pos: np.ndarray) -> np.ndarray:
        """Forward-project each action, evaluate value at sampled states,
        pick action with max value (Algorithm 2, line 26).
        Actions whose trajectories enter the unsafe ellipsoid are rejected."""
        actions = self._build_actions(pos)
        if not actions:
            return pos.copy()

        actions_arr = np.asarray(actions, dtype=float)
        sample_indices = np.linspace(0, FWD_STEPS - 1, SAMPLE_COUNT, dtype=int)
        goal = self._current_goal()
        d_goal_now = np.linalg.norm(goal - pos) if goal is not None else 0.0

        trajs = self._forward_project_many(pos, actions_arr)
        unsafe_mask = self._trajectory_enters_unsafe_many(trajs)

        # Ownship.selectBestAction: max over trajectory samples × actions.
        sampled_states = trajs[:, sample_indices, :].reshape(-1, 3)
        sampled_values = self._value_many(sampled_states).reshape(actions_arr.shape[0], -1)
        max_vals = np.max(sampled_values, axis=1)

        step_idx = min(ONE_STEP_INDEX, trajs.shape[1] - 1)
        one_steps = trajs[:, step_idx, :]
        if goal is not None:
            one_step_goal_dists = np.linalg.norm(one_steps - goal.reshape(1, 3), axis=1)
        else:
            one_step_goal_dists = np.zeros(actions_arr.shape[0], dtype=float)

        best_idx = int(np.argmax(max_vals))
        best_one_step = one_steps[best_idx]

        safe_mask = ~unsafe_mask

        # Prefer safe trajectories; when not near goal, require at least small
        # progress toward the goal. If best-value safe action stalls, choose the
        # safe action that gets closest in one step.
        if np.any(safe_mask):
            safe_vals = np.where(safe_mask, max_vals, -float("inf"))
            best_safe_idx = int(np.argmax(safe_vals))
            best_safe_one_step = one_steps[best_safe_idx]
            best_safe_goal_dist = one_step_goal_dists[best_safe_idx]

            safe_goal_dists = np.where(safe_mask, one_step_goal_dists, np.inf)
            closest_safe_idx = int(np.argmin(safe_goal_dists))
            closest_safe_step = one_steps[closest_safe_idx]

            if goal is not None and d_goal_now > GOAL_REACHED_DIST and best_safe_goal_dist >= d_goal_now - 0.2:
                return closest_safe_step
            return best_safe_one_step
        return best_one_step

    # ── Controller entry point ───────────────────────────────────────────────

    def on_ctl_tick(self, state: dict) -> dict:
        """Plan + PID control."""
        pos = np.array(state["pos"], dtype=float)
        vel = np.array(state["vel"], dtype=float)
        euler = state["euler"]
        omega = state["omega"]
        t = state["time"]

        if not self.initialized:
            self.initialized = True
            self.last_time = t
            self.target_pos = pos.copy()
            wps = state.get("waypoints", [])
            if wps:
                self.waypoints = [(w["x"], w["y"], w["z"]) for w in wps]
                self.wp_index = len(self.waypoints) - 1
                self.mass = state.get("mass", 5.0)
                arm = state.get("arm_length", 0.5)
                ixx = state.get("Ixx", 0.5)
                if arm > 1e-6:
                    scale = ixx / arm
                    self.Kp_angle = 20.0 * scale
                    self.Kd_angle = 8.0 * scale
            return {"thrust": self.mass * GRAVITY}

        dt = t - self.last_time
        self.last_time = t
        if dt <= 0:
            dt = 0.01

        self._parse_gcs_command(state.get("gcs_command"))

        # Goal-reached hover
        goal = self._current_goal()
        if goal is not None and np.linalg.norm(goal - pos) < GOAL_REACHED_DIST:
            if not self.goal_reached:
                self.goal_reached = True
                self.target_pos = goal.copy()
                self.vel_integral = [0.0, 0.0, 0.0]
                print(f"[MDP] Host {self.host_id} REACHED GOAL at t={t:.1f}s "
                      f"pos=({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f}) "
                      f"goal=({goal[0]:.0f},{goal[1]:.0f},{goal[2]:.0f})")
        else:
            self.goal_reached = False

        # MDP planning at REPLAN_DT intervals, skip when at goal
        if not self.goal_reached:
            self.plan_counter += 1
            steps_per_plan = max(1, int(REPLAN_DT / max(dt, 0.001)))
            if self.plan_counter >= steps_per_plan:
                self.plan_counter = 0
                planned = self._plan(pos)
                self.target_pos = planned

        target = self.target_pos

        # ── Cascaded PID ─────────────────────────────────────────────────────
        err_x = target[0] - pos[0]
        err_y = target[1] - pos[1]
        err_z = target[2] - pos[2]

        vel_sp_x = _clamp(self.Kp_xy * err_x, -CRUISE_SPEED, CRUISE_SPEED)
        vel_sp_y = _clamp(self.Kp_xy * err_y, -CRUISE_SPEED, CRUISE_SPEED)
        vel_sp_z = _clamp(self.Kp_z * 0.3 * err_z, -4.0, 4.0)

        vel_err_x = vel_sp_x - vel[0]
        vel_err_y = vel_sp_y - vel[1]
        vel_err_z = vel_sp_z - vel[2]

        self.vel_integral[0] = _clamp(self.vel_integral[0] + vel_err_x * dt,
                                       -self.max_integral, self.max_integral)
        self.vel_integral[1] = _clamp(self.vel_integral[1] + vel_err_y * dt,
                                       -self.max_integral, self.max_integral)
        self.vel_integral[2] = _clamp(self.vel_integral[2] + vel_err_z * dt,
                                       -self.max_integral, self.max_integral)

        accel_x = 2.0 * vel_err_x + self.Ki_vel * self.vel_integral[0]
        accel_y = 2.0 * vel_err_y + self.Ki_vel * self.vel_integral[1]
        accel_z = 4.0 * vel_err_z + 0.5 * self.vel_integral[2]

        thrust = self.mass * (GRAVITY + accel_z)
        thrust = max(0.0, thrust)

        phi, theta, psi = euler
        p, q, r = omega

        cpsi = math.cos(psi)
        spsi = math.sin(psi)
        ab_x = accel_x * cpsi + accel_y * spsi
        ab_y = -accel_x * spsi + accel_y * cpsi

        theta_des = _clamp(ab_x / GRAVITY, -self.max_tilt, self.max_tilt)
        phi_des = _clamp(-ab_y / GRAVITY, -self.max_tilt, self.max_tilt)

        torque_phi = self.Kp_angle * (phi_des - phi) - self.Kd_angle * p
        torque_theta = self.Kp_angle * (theta_des - theta) - self.Kd_angle * q
        torque_psi = -self.Kd_angle * r

        result = {
            "thrust": float(thrust),
            "torque_phi": float(torque_phi),
            "torque_theta": float(torque_theta),
            "torque_psi": float(torque_psi),
        }
        if self.goal_reached:
            result["goal_reached"] = True
        return result
