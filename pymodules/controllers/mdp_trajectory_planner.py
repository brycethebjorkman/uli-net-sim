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
  2. Sample 10 future states along each trajectory
  3. Evaluate closed-form value at each sampled state
  4. Select the action yielding the max value at any future state
  5. Execute only the one-step-ahead state (receding horizon)

Low-level control uses cascaded PID (same as CascadedPidController).

INI usage:
    *.host[*].mobility.pyClass = "pymodules.controllers.mdp_trajectory_planner.MdpTrajectoryPlanner"
"""

import json
import math
import numpy as np

from pymodules.gcs.chance_constraint import is_safe

GRAVITY = 9.81

# ── Planning parameters ──────────────────────────────────────────────────────
REPLAN_DT = 0.5
FWD_DT = 0.5
FWD_STEPS = 20          # 20 × 0.5s = 10s lookahead
SAMPLE_COUNT = 10
ONE_STEP_INDEX = 1       # ~1s ahead, used as execution target
CRUISE_SPEED = 8.0
GOAL_REACHED_DIST = 8.0

# ── Value function parameters (Table 1 adapted for ~500m domain) ─────────────
GOAL_REWARD = 200.0
GOAL_DISCOUNT = 0.999    # slow decay → attraction over entire field

AGENT_REWARD = 1000.0
AGENT_DISCOUNT = 0.97    # matches paper's intruder decay factor
AGENT_LIMIT = 80.0       # negative peak radius (meters)

SPOOFER_REWARD = 1000.0
SPOOFER_DISCOUNT = 0.97

MIN_CYCLE = 2            # normalization constant (grid-world minimum distance)

# ── Action space ─────────────────────────────────────────────────────────────
NUM_HEADINGS = 16
SPEED_LEVELS = [CRUISE_SPEED, CRUISE_SPEED * 0.5, 0.0]


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
            new_others = cmd.get("other_positions", {})
            if new_others:
                self.other_positions = new_others
            self.agent_radius = cmd.get("agent_radius", AGENT_LIMIT)
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

    def _build_actions(self, pos: np.ndarray) -> list[tuple[float, float]]:
        """Build (heading, speed) action set. Headings are log-spaced near
        the goal direction for fine control, plus uniform coverage."""
        actions = []

        # Uniform headings at each speed level
        for k in range(NUM_HEADINGS):
            heading = 2.0 * math.pi * k / NUM_HEADINGS
            for speed in SPEED_LEVELS:
                actions.append((heading, speed))

        # Goal-directed actions at multiple speeds
        goal = self._current_goal()
        if goal is not None:
            to_goal = goal[:2] - pos[:2]
            d = np.linalg.norm(to_goal)
            if d > 1.0:
                goal_heading = math.atan2(to_goal[1], to_goal[0])
                for speed in SPEED_LEVELS:
                    actions.append((goal_heading, speed))
                # Flanking: ±15°, ±30° off goal heading
                for offset_deg in [15, 30]:
                    offset = math.radians(offset_deg)
                    for speed in [CRUISE_SPEED, CRUISE_SPEED * 0.5]:
                        actions.append((goal_heading + offset, speed))
                        actions.append((goal_heading - offset, speed))

        return actions

    # ── Forward projection ───────────────────────────────────────────────────

    def _forward_project(self, pos: np.ndarray, heading: float, speed: float) -> list[np.ndarray]:
        """Simplified kinematic forward projection at constant heading/speed."""
        dx = speed * math.cos(heading) * FWD_DT
        dy = speed * math.sin(heading) * FWD_DT
        traj = []
        p = pos.copy()
        for _ in range(FWD_STEPS):
            p = p + np.array([dx, dy, 0.0])
            traj.append(p.copy())
        return traj

    # ── Value function (Eq. 6) ───────────────────────────────────────────────

    def _value_at(self, pos: np.ndarray) -> float:
        """Closed-form value at a state: V = V+ − V−"""

        # ── Positive value: goal attraction ──
        v_pos = 0.0
        goal = self._current_goal()
        if goal is not None:
            d_goal = np.linalg.norm(goal - pos)
            v_pos = self._goal_peak * (GOAL_DISCOUNT ** d_goal)

        # ── Negative value: agent repulsion ──
        v_neg = 0.0
        for oid, op in self.other_positions.items():
            oid_int = int(oid) if isinstance(oid, str) else oid
            if self.host_id is not None and oid_int == self.host_id:
                continue
            d_agent = np.linalg.norm(pos - np.asarray(op, dtype=float))
            if d_agent < self.agent_radius:
                v_neg += self._agent_peak * (AGENT_DISCOUNT ** d_agent)

        # ── Negative value: spoofer unsafe region ──
        if self.unsafe_region is not None:
            mu = np.asarray(self.unsafe_region["mu"], dtype=float)
            sigma = np.asarray(self.unsafe_region["sigma"], dtype=float)
            alpha = self.unsafe_region.get("alpha", 0.05)
            if not is_safe(pos, mu, sigma, alpha):
                d_spoof = np.linalg.norm(pos - mu)
                v_neg += self._spoofer_peak * (SPOOFER_DISCOUNT ** d_spoof)

        return v_pos - v_neg

    # ── MDP planning with action shielding + reward shaping ─────────────────

    def _is_safe_trajectory(self, traj: list[np.ndarray],
                            sample_indices: np.ndarray) -> bool:
        """Action shielding (Sec. IV.B): reject if any sampled state enters
        an intruder zone or spoofer unsafe region."""
        for idx in sample_indices:
            p = traj[idx]
            for oid, op in self.other_positions.items():
                oid_int = int(oid) if isinstance(oid, str) else oid
                if self.host_id is not None and oid_int == self.host_id:
                    continue
                if np.linalg.norm(p - np.asarray(op, dtype=float)) < self.agent_radius * 0.5:
                    return False
            if self.unsafe_region is not None:
                mu = np.asarray(self.unsafe_region["mu"], dtype=float)
                sigma = np.asarray(self.unsafe_region["sigma"], dtype=float)
                alpha = self.unsafe_region.get("alpha", 0.05)
                if not is_safe(p, mu, sigma, alpha):
                    return False
        return True

    def _plan(self, pos: np.ndarray) -> np.ndarray:
        """Forward-project each action, evaluate value with reward shaping,
        apply action shielding, pick best."""
        actions = self._build_actions(pos)
        sample_indices = np.linspace(0, FWD_STEPS - 1, SAMPLE_COUNT, dtype=int)
        v_current = self._value_at(pos)

        best_value = -float("inf")
        best_one_step = pos.copy()
        shielded_best_value = -float("inf")
        shielded_best_one_step = pos.copy()

        for heading, speed in actions:
            traj = self._forward_project(pos, heading, speed)

            # Reward shaping (Sec. IV.C, Eq. 16): accumulate shaped reward
            # F(s,a,s') = κ·V(s') - V(s) along trajectory
            total_shaped = 0.0
            v_prev = v_current
            for idx in sample_indices:
                v_next = self._value_at(traj[idx])
                total_shaped += 0.99 * v_next - v_prev
                v_prev = v_next

            # Also add the terminal value (best state along trajectory)
            total_shaped += v_prev

            # Action shielding: prefer safe actions
            safe = self._is_safe_trajectory(traj, sample_indices)

            step_idx = min(ONE_STEP_INDEX, len(traj) - 1)
            if safe and total_shaped > shielded_best_value:
                shielded_best_value = total_shaped
                shielded_best_one_step = traj[step_idx]

            if total_shaped > best_value:
                best_value = total_shaped
                best_one_step = traj[step_idx]

        # Use shielded action if available, otherwise fall back to unshielded
        if shielded_best_value > -float("inf"):
            return shielded_best_one_step
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

        # Waypoint advancement
        if self.goal is None and self.waypoints and self.wp_index < len(self.waypoints):
            wp = self.waypoints[self.wp_index]
            if np.linalg.norm(pos - np.array([wp[0], wp[1], wp[2]])) < GOAL_REACHED_DIST:
                self.wp_index = min(self.wp_index + 1, len(self.waypoints) - 1)

        # Goal-reached hover
        goal = self._current_goal()
        if goal is not None and np.linalg.norm(goal - pos) < GOAL_REACHED_DIST:
            if not self.goal_reached:
                self.goal_reached = True
                self.target_pos = goal.copy()
                self.vel_integral = [0.0, 0.0, 0.0]
        else:
            self.goal_reached = False

        # MDP planning at REPLAN_DT intervals, skip when at goal
        if not self.goal_reached:
            self.plan_counter += 1
            steps_per_plan = max(1, int(REPLAN_DT / max(dt, 0.001)))
            if self.plan_counter >= steps_per_plan:
                self.plan_counter = 0
                self.target_pos = self._plan(pos)

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

        return {
            "thrust": float(thrust),
            "torque_phi": float(torque_phi),
            "torque_theta": float(torque_theta),
            "torque_psi": float(torque_psi),
        }
