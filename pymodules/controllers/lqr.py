"""
LQR hover/trajectory controller for MultirotorMobility.

Uses analytical linearization of 6-DoF dynamics at hover equilibrium
and scipy's continuous algebraic Riccati equation (CARE) solver to
compute the optimal gain matrix K.  More robust across airframe
parameters than CascadedPidController — no manual tuning needed.

State vector: [x, y, z, vx, vy, vz, phi, theta, psi, p, q, r]  (12)
Control:      [T, tau_phi, tau_theta, tau_psi]                    (4)

See docs/multirotor_dynamics.md for the dynamics equations.

INI usage:
    *.host[*].mobility.pyClass = "pymodules.controllers.lqr.LqrController"
    *.host[0].mobility.waypointScript = xmldoc("traj.xml", ...)
"""

import math
import numpy as np
from scipy.linalg import solve_continuous_are

GRAVITY = 9.81


class LqrController:
    """LQR controller with hover-point linearization and trajectory tracking."""

    def __init__(self):
        self.mass = 5.0
        self.arm_length = 0.5
        self.Ixx = 0.5
        self.Iyy = 0.5
        self.Izz = 0.8
        self.rot_drag = 3.0

        self.waypoints = []  # list of (x, y, z)
        self.speed = 10.0
        self.target = None   # current hover/goto target (x, y, z)
        self.K = None         # gain matrix (4x12)
        self.initialized = False
        self.last_time = None

        # Trajectory tracking state
        self.ref_trajectory = None  # list of (t, px, py, pz, vx, vy, vz)
        self.hovering = False

    def _compute_gain(self):
        """Compute LQR gain K by linearizing dynamics at hover and solving CARE.

        At hover equilibrium:
          x_eq: all zeros except position = target
          u_eq: [m*g, 0, 0, 0]

        Linearized: dx/dt = A*(x - x_eq) + B*(u - u_eq)

        The A matrix (Jacobian of f w.r.t. x at hover):
          Position rows: d(pos)/d(vel) = I
          Velocity rows:
            d(vx_dot)/d(theta) = g   (from T/m * sin(theta) at hover where T=mg)
            d(vy_dot)/d(phi)   = -g  (from T/m * sin(phi) at hover)
            d(vz_dot)/d(phi)   = 0, d(vz_dot)/d(theta) = 0  (cos terms vanish)
          Euler angle rows:
            d(phi_dot)/d(p) = 1  (at hover, sin/cos/tan terms vanish)
            d(theta_dot)/d(q) = 1
            d(psi_dot)/d(r) = 1
          Angular rate rows:
            d(p_dot)/d(p) = -rot_drag  (rotational damping)
            d(q_dot)/d(q) = -rot_drag
            d(r_dot)/d(r) = -rot_drag
            (cross-coupling qr, pr terms vanish at hover since q=r=p=0)

        The B matrix (Jacobian of f w.r.t. u at hover):
          d(vz_dot)/d(T) = 1/m  (from T/m * cos(phi)*cos(theta), at hover = T/m)
          d(p_dot)/d(tau_phi) = arm_length / Ixx
          d(q_dot)/d(tau_theta) = arm_length / Iyy
          d(r_dot)/d(tau_psi) = arm_length / Izz
        """
        m = self.mass
        L = self.arm_length
        Ixx, Iyy, Izz = self.Ixx, self.Iyy, self.Izz
        krot = self.rot_drag
        g = GRAVITY

        A = np.zeros((12, 12))
        B = np.zeros((12, 4))

        # Position derivatives w.r.t. velocity: dx/dvx = 1, etc.
        A[0, 3] = 1.0  # dx/dvx
        A[1, 4] = 1.0  # dy/dvy
        A[2, 5] = 1.0  # dz/dvz

        # Velocity derivatives w.r.t. Euler angles (at hover, T=mg):
        # vx_dot = (T/m)(sin(theta)*cos(psi)*cos(phi) + sin(phi)*sin(psi))
        # At hover (phi=theta=psi=0): d(vx_dot)/d(theta) = (mg/m)*cos(0)*cos(0)*cos(0) = g
        A[3, 7] = g     # d(vx_dot)/d(theta)
        # vy_dot = (T/m)(sin(theta)*sin(psi)*cos(phi) - sin(phi)*cos(psi))
        # At hover: d(vy_dot)/d(phi) = (mg/m)*(0 - cos(0)*cos(0)) = -g
        A[4, 6] = -g    # d(vy_dot)/d(phi)
        # vz_dot = -g + (T/m)*cos(phi)*cos(theta)
        # At hover: d(vz_dot)/d(phi) = -(mg/m)*sin(0)*cos(0) = 0
        # d(vz_dot)/d(theta) = -(mg/m)*cos(0)*sin(0) = 0

        # Euler angle kinematics w.r.t. angular rates (at hover):
        # phi_dot = p + q*sin(phi)*tan(theta) + r*cos(phi)*tan(theta)
        # At hover: d(phi_dot)/d(p) = 1
        A[6, 9] = 1.0   # d(phi_dot)/d(p)
        # theta_dot = q*cos(phi) - r*sin(phi)
        # At hover: d(theta_dot)/d(q) = 1
        A[7, 10] = 1.0  # d(theta_dot)/d(q)
        # psi_dot = (q*sin(phi) + r*cos(phi))/cos(theta)
        # At hover: d(psi_dot)/d(r) = 1
        A[8, 11] = 1.0  # d(psi_dot)/d(r)

        # Angular rate dynamics w.r.t. angular rates (rotational damping):
        A[9, 9] = -krot    # d(p_dot)/d(p)
        A[10, 10] = -krot  # d(q_dot)/d(q)
        A[11, 11] = -krot  # d(r_dot)/d(r)

        # B matrix: control input effects
        B[5, 0] = 1.0 / m          # d(vz_dot)/d(T)
        B[9, 1] = L / Ixx          # d(p_dot)/d(tau_phi)
        B[10, 2] = L / Iyy         # d(q_dot)/d(tau_theta)
        B[11, 3] = L / Izz         # d(r_dot)/d(tau_psi)

        # Q matrix: state error penalty
        # Position: high weight; velocity: high (to avoid overshoot); angles: medium; rates: medium
        Q = np.diag([
            40.0, 40.0, 60.0,    # x, y, z position
            20.0, 20.0, 30.0,    # vx, vy, vz velocity (high to damp oscillation)
            15.0, 15.0, 5.0,     # phi, theta, psi angles
            5.0,  5.0,  3.0,     # p, q, r angular rates
        ])

        # R matrix: control effort penalty
        R = np.diag([
            0.5,   # thrust (lower = more responsive altitude)
            20.0,  # tau_phi  (penalize torques to avoid aggressive tilting)
            20.0,  # tau_theta
            20.0,  # tau_psi
        ])

        # Solve continuous algebraic Riccati equation: A'P + PA - PBR^{-1}B'P + Q = 0
        P = solve_continuous_are(A, B, Q, R)
        self.K = np.linalg.solve(R, B.T @ P)  # K = R^{-1} B' P

    def _build_reference_trajectory(self, t0):
        """Pre-compute reference trajectory from waypoints.

        Generates (time, px, py, pz, vx, vy, vz) samples at 0.01s intervals
        along straight-line segments between waypoints. Uses a trapezoidal
        speed profile that decelerates before each waypoint to avoid
        instantaneous velocity discontinuities at corners.
        """
        if len(self.waypoints) <= 1:
            return None

        ref = []
        t = t0
        dt_ref = 0.01
        max_accel = 5.0  # m/s^2 deceleration rate

        for seg_idx in range(1, len(self.waypoints)):
            wp_prev = self.waypoints[seg_idx - 1]
            wp_curr = self.waypoints[seg_idx]
            dx = wp_curr[0] - wp_prev[0]
            dy = wp_curr[1] - wp_prev[1]
            dz = wp_curr[2] - wp_prev[2]
            seg_len = math.sqrt(dx * dx + dy * dy + dz * dz)
            if seg_len < 1e-6:
                continue

            ux, uy, uz = dx / seg_len, dy / seg_len, dz / seg_len
            is_last = (seg_idx == len(self.waypoints) - 1)

            # Walk along segment with trapezoidal speed profile
            s = 0.0  # distance traveled along segment
            v = 0.0  # current speed (start from rest on first segment)
            if ref:
                # Continue from previous segment's ending speed
                prev = ref[-1]
                v = math.sqrt(prev[4]**2 + prev[5]**2 + prev[6]**2)

            while s < seg_len:
                remaining = seg_len - s
                # Deceleration speed limit: v_decel = sqrt(2*a*remaining)
                # Only decelerate toward zero on the last segment
                if is_last:
                    v_decel = math.sqrt(2.0 * max_accel * remaining) if remaining > 0 else 0.0
                else:
                    # At non-final waypoints, decelerate to a turning speed
                    turn_speed = self.speed * 0.5
                    v_decel = max(turn_speed,
                                  math.sqrt(2.0 * max_accel * remaining) if remaining > 0 else 0.0)

                # Accelerate toward cruise, limited by decel constraint
                v = min(v + max_accel * dt_ref, self.speed, v_decel)
                v = max(v, 0.0)

                frac = s / seg_len
                px = wp_prev[0] + frac * dx
                py = wp_prev[1] + frac * dy
                pz = wp_prev[2] + frac * dz
                ref.append((t, px, py, pz, v * ux, v * uy, v * uz))

                s += v * dt_ref
                t += dt_ref

        # Final waypoint: hover
        wp_final = self.waypoints[-1]
        ref.append((t, wp_final[0], wp_final[1], wp_final[2], 0.0, 0.0, 0.0))
        return ref

    def _lookup_reference(self, t):
        """Find reference state at time t via binary search."""
        ref = self.ref_trajectory
        if not ref:
            return self.target + (0.0, 0.0, 0.0)

        # Clamp to trajectory bounds
        if t <= ref[0][0]:
            return ref[0][1:]  # (px, py, pz, vx, vy, vz)
        if t >= ref[-1][0]:
            self.hovering = True
            return ref[-1][1:]

        # Binary search
        lo, hi = 0, len(ref) - 1
        while lo < hi - 1:
            mid = (lo + hi) // 2
            if ref[mid][0] <= t:
                lo = mid
            else:
                hi = mid

        # Linear interpolation between lo and hi
        t0, t1 = ref[lo][0], ref[hi][0]
        if t1 - t0 < 1e-9:
            return ref[lo][1:]
        alpha = (t - t0) / (t1 - t0)
        return tuple(
            ref[lo][i + 1] + alpha * (ref[hi][i + 1] - ref[lo][i + 1])
            for i in range(6)
        )

    def on_ctl_tick(self, state):
        pos = state['pos']
        vel = state['vel']
        euler = state['euler']
        omega = state['omega']
        t = state['time']

        # --- First call: extract params and compute gain ---
        if not self.initialized:
            self.initialized = True
            self.last_time = t
            self.mass = state.get('mass', 5.0)
            self.arm_length = state.get('arm_length', 0.5)
            self.Ixx = state.get('Ixx', 0.5)
            self.Iyy = state.get('Iyy', 0.5)
            self.Izz = state.get('Izz', 0.8)

            wps = state.get('waypoints', [])
            if wps:
                self.waypoints = [(w['x'], w['y'], w['z']) for w in wps]
                self.speed = wps[0].get('speed', 10.0)
                self.target = self.waypoints[0]
            else:
                self.target = pos

            self._compute_gain()

            # Build reference trajectory if we have multiple waypoints
            if len(self.waypoints) > 1:
                self.ref_trajectory = self._build_reference_trajectory(t)
                self.hovering = False
            else:
                self.hovering = True

            return {'thrust': self.mass * GRAVITY}

        # --- Look up reference state ---
        if self.ref_trajectory and not self.hovering:
            px, py, pz, vx_ref, vy_ref, vz_ref = self._lookup_reference(t)
        else:
            px, py, pz = self.target
            vx_ref, vy_ref, vz_ref = 0.0, 0.0, 0.0

        # --- Build state error vector (tracking error) ---
        x_err = np.array([
            pos[0] - px, pos[1] - py, pos[2] - pz,
            vel[0] - vx_ref, vel[1] - vy_ref, vel[2] - vz_ref,
            euler[0], euler[1], euler[2],
            omega[0], omega[1], omega[2],
        ])

        # --- LQR control: u = u_hover - K * x_err ---
        u_correction = self.K @ x_err

        mg = self.mass * GRAVITY
        thrust = mg - u_correction[0]

        # Tilt compensation: during tilted flight, effective vertical thrust
        # is T*cos(phi)*cos(theta). Scale up to maintain vertical authority.
        phi, theta = euler[0], euler[1]
        cos_tilt = math.cos(phi) * math.cos(theta)
        if cos_tilt > 0.3:  # don't compensate at extreme tilt (>~73°)
            thrust /= cos_tilt

        thrust = max(0.0, min(thrust, 4.0 * mg))  # clamp to [0, 4*mg]

        # Clamp torques. Scale limits by inertia/arm so angular acceleration
        # stays bounded regardless of airframe.
        L = self.arm_length
        max_torque_phi = 5.0 * self.Ixx / L if L > 1e-6 else 50.0
        max_torque_theta = 5.0 * self.Iyy / L if L > 1e-6 else 50.0
        max_torque_psi = 5.0 * self.Izz / L if L > 1e-6 else 50.0
        torque_phi = max(-max_torque_phi, min(max_torque_phi, -u_correction[1]))
        torque_theta = max(-max_torque_theta, min(max_torque_theta, -u_correction[2]))
        torque_psi = max(-max_torque_psi, min(max_torque_psi, -u_correction[3]))

        return {
            'thrust': thrust,
            'torque_phi': torque_phi,
            'torque_theta': torque_theta,
            'torque_psi': torque_psi,
        }
