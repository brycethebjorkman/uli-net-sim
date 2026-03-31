"""
Decentralized MDP-based trajectory planner controller (Sec. VI-B in paper).

Each agent independently computes its next control action using a per-timestep
MDP reward function (Table I):
  - Goal reached:                 R_goal   = +100
  - Progress toward goal:         R_prog   = +5
  - Enter spoofer risk domain:    R_spoof  = -200
  - Near cooperative agent:       R_agents = -150
  - Time step penalty:            R_time   = -1

At each planning step, the agent forward-projects candidate actions over a
short horizon, evaluates cumulative reward, and executes the best action
in a receding-horizon fashion. Low-level control uses cascaded PID
(same gains as CascadedPidController).

Receives GCS commands containing:
  - unsafe_region: {mu, sigma, alpha, threshold} from chance constraint
  - other_positions: {id: [x,y,z]} for cooperative agents
  - agent_radius: pre-detection separation distance (m)
  - goal: [x,y,z] destination
  - host_id: this agent's id

INI usage:
    *.host[*].mobility.pyClass = "pymodules.controllers.mdp_trajectory_planner.MdpTrajectoryPlanner"
"""

import json
import math
import numpy as np

from pymodules.gcs.chance_constraint import is_safe, mahalanobis_squared

GRAVITY = 9.81

# Planning parameters
PLAN_DT = 0.5
PLAN_HORIZON = 5
CRUISE_SPEED = 8.0

# Reward values (Table I)
R_GOAL = 100.0
R_PROGRESS = 5.0
R_SPOOFER = -200.0
R_AGENTS = -150.0
R_TIME = -1.0

# Proximity threshold for cooperative agent penalty
D_MIN_AGENTS = 25.0


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


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
        self.agent_radius = D_MIN_AGENTS
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

    def _parse_gcs_command(self, gcs_cmd):
        if gcs_cmd is None or not isinstance(gcs_cmd, str):
            return
        try:
            cmd = json.loads(gcs_cmd)
            self.unsafe_region = cmd.get("unsafe_region")
            new_others = cmd.get("other_positions", {})
            if new_others:
                self.other_positions = new_others
            self.agent_radius = cmd.get("agent_radius", D_MIN_AGENTS)
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

    def _action_set(self, pos: np.ndarray) -> list[np.ndarray]:
        """Generate discrete velocity action candidates (3D)."""
        actions = []
        step = CRUISE_SPEED * PLAN_DT

        # 16 planar headings at cruise speed
        for k in range(16):
            a = 2.0 * math.pi * k / 16.0
            actions.append(np.array([math.cos(a) * step, math.sin(a) * step, 0.0]))

        # Goal-directed actions
        goal = self._current_goal()
        if goal is not None:
            to_goal = goal - pos
            d = np.linalg.norm(to_goal)
            if d > 1.0:
                direction = to_goal / d
                actions.append(direction * step)
                actions.append(direction * step * 0.5)
                perp = np.array([-direction[1], direction[0], 0.0])
                actions.append(perp * step)
                actions.append(-perp * step)

        # Vertical actions
        actions.append(np.array([0.0, 0.0, step * 0.5]))
        actions.append(np.array([0.0, 0.0, -step * 0.5]))

        # Hover
        actions.append(np.zeros(3))

        return actions

    def _reward_at(self, pos: np.ndarray, prev_goal_dist: float) -> float:
        """Compute MDP reward at a candidate position (Table I)."""
        reward = R_TIME

        goal = self._current_goal()
        if goal is not None:
            goal_dist = np.linalg.norm(goal - pos)
            if goal_dist < 5.0:
                reward += R_GOAL
            elif goal_dist < prev_goal_dist:
                reward += R_PROGRESS

        # Cooperative agent proximity penalty
        for oid, op in self.other_positions.items():
            oid_int = int(oid) if isinstance(oid, str) else oid
            if self.host_id is not None and oid_int == self.host_id:
                continue
            d = np.linalg.norm(pos - np.asarray(op, dtype=float))
            if d < self.agent_radius:
                reward += R_AGENTS * (1.0 + (self.agent_radius - d) / self.agent_radius)
            elif d < self.agent_radius * 2.0:
                reward += R_AGENTS * 0.3 * ((self.agent_radius * 2.0 - d) / self.agent_radius)

        # Spoofer risk domain penalty (chance constraint violation)
        if self.unsafe_region is not None:
            mu = np.asarray(self.unsafe_region["mu"], dtype=float)
            sigma = np.asarray(self.unsafe_region["sigma"], dtype=float)
            alpha = self.unsafe_region.get("alpha", 0.05)
            if not is_safe(pos, mu, sigma, alpha):
                d2 = mahalanobis_squared(pos, mu, sigma)
                thresh = self.unsafe_region.get("threshold", 7.81)
                severity = max(0.0, thresh - d2) / max(thresh, 1.0)
                reward += R_SPOOFER * (1.0 + severity)

        return reward

    def _plan(self, pos: np.ndarray) -> np.ndarray:
        """MDP planning: evaluate actions over finite horizon, pick best."""
        actions = self._action_set(pos)
        goal = self._current_goal()
        init_goal_dist = np.linalg.norm(goal - pos) if goal is not None else 0.0

        best_score = -float("inf")
        best_action = np.zeros(3)

        for action in actions:
            p = pos.copy()
            score = 0.0
            prev_dist = init_goal_dist
            for h in range(PLAN_HORIZON):
                p = p + action
                if goal is not None:
                    cur_dist = np.linalg.norm(goal - p)
                else:
                    cur_dist = prev_dist
                r = self._reward_at(p, prev_dist)
                score += r * (0.95 ** h)
                prev_dist = cur_dist
            if score > best_score:
                best_score = score
                best_action = action

        return pos + best_action

    def on_ctl_tick(self, state: dict) -> dict:
        """Controller entry point: plan + PID control."""
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

        # Waypoint advancement (if using waypoint list as goals)
        if self.goal is None and self.waypoints and self.wp_index < len(self.waypoints):
            wp = self.waypoints[self.wp_index]
            if np.linalg.norm(pos - np.array([wp[0], wp[1], wp[2]])) < 5.0:
                self.wp_index = min(self.wp_index + 1, len(self.waypoints) - 1)

        # MDP planning at PLAN_DT intervals (~2 Hz)
        self.plan_counter += 1
        steps_per_plan = max(1, int(PLAN_DT / max(dt, 0.001)))
        if self.plan_counter >= steps_per_plan:
            self.plan_counter = 0
            self.target_pos = self._plan(pos)

        target = self.target_pos

        # --- Cascaded PID ---
        err_x = target[0] - pos[0]
        err_y = target[1] - pos[1]
        err_z = target[2] - pos[2]

        vel_sp_x = _clamp(self.Kp_xy * err_x, -CRUISE_SPEED, CRUISE_SPEED)
        vel_sp_y = _clamp(self.Kp_xy * err_y, -CRUISE_SPEED, CRUISE_SPEED)
        vel_sp_z = _clamp(self.Kp_z * 0.3 * err_z, -4.0, 4.0)

        vel_err_x = vel_sp_x - vel[0]
        vel_err_y = vel_sp_y - vel[1]
        vel_err_z = vel_sp_z - vel[2]

        self.vel_integral[0] = _clamp(self.vel_integral[0] + vel_err_x * dt, -self.max_integral, self.max_integral)
        self.vel_integral[1] = _clamp(self.vel_integral[1] + vel_err_y * dt, -self.max_integral, self.max_integral)
        self.vel_integral[2] = _clamp(self.vel_integral[2] + vel_err_z * dt, -self.max_integral, self.max_integral)

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
