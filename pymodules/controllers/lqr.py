"""
LQR controller for MultirotorMobility, adapted from NASA ProgPy's UAV LQR.

Uses full-state linearization of 6-DoF dynamics with yaw-scheduled gain
lookup, following the approach in ProgPy's SmallRotorcraft + LQR controller.
The system is linearized at (phi=0, theta=0, psi_k, p=q=r=0, T=mg) for a grid of yaw angles,
and the nearest gain K is selected at runtime based on the current heading.

Key adaptations from ProgPy:
  - State ordering: [pos, vel, angles, rates] vs ProgPy's [pos, angles, vel, rates]
  - Rotational damping term in A matrix (our dynamics include -krot*omega)
  - Yaw torque scaled by arm_length (our convention) vs ProgPy's direct 1/Izz
  - CARE solver (scipy) instead of Hamiltonian eigenvalue decomposition
  - Trajectory tracking with trapezoidal speed profile
  - GCS command handling (hold/goto/waypoints)

State vector: [x, y, z, vx, vy, vz, phi, theta, psi, p, q, r]  (12)
Control:      [T, tau_phi, tau_theta, tau_psi]                    (4)

See docs/multirotor_dynamics.md for the dynamics equations.

INI usage:
    *.host[*].mobility.pyClass = "pymodules.controllers.lqr.LqrController"
    *.host[0].mobility.waypointScript = xmldoc("traj.xml", ...)
"""

import json
import math
import numpy as np
from scipy.linalg import solve_continuous_are

GRAVITY = 9.81

# Number of yaw grid points for gain scheduling (ProgPy uses 721 = 360*2+1)
N_PSI_GRID = 721


class LqrController:
    """LQR controller with yaw-scheduled gains and trajectory tracking."""

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
        self.initialized = False
        self.last_time = None

        # Gain schedule: array of K matrices indexed by yaw grid
        self.gain_schedule = None  # (N_PSI_GRID, 4, 12)
        self.psi_grid = None       # (N_PSI_GRID,)

        # Trajectory tracking state
        self.ref_trajectory = None  # list of (t, px, py, pz, vx, vy, vz)
        self.hovering = False

        # Waypoint visualization update flag
        self._waypoints_changed = False

    # -- Linearization (adapted from ProgPy SmallRotorcraft.linear_model) ------

    def _linearize(self, phi, theta, psi, p, q, r, T):
        """Compute linearized A, B matrices at an arbitrary operating point.

        This is the Jacobian of our 6-DoF dynamics (see MultirotorMobility.cc)
        with respect to state and control, evaluated at the given attitude,
        angular rates, and thrust.

        Adapted from ProgPy SmallRotorcraft.linear_model() with:
          - Our state ordering: [pos, vel, angles, rates] (indices 0-11)
          - Rotational damping: -krot * [p, q, r] (our dynamics, not in ProgPy)
          - Yaw torque: arm_length / Izz (our convention, ProgPy uses 1/Izz)
        """
        m = self.mass
        L = self.arm_length
        Ixx, Iyy, Izz = self.Ixx, self.Iyy, self.Izz
        krot = self.rot_drag

        sp, cp = math.sin(phi), math.cos(phi)
        st, ct = math.sin(theta), math.cos(theta)
        tt = math.tan(theta)
        ss, cs = math.sin(psi), math.cos(psi)

        A = np.zeros((12, 12))

        # Position derivatives w.r.t. velocity
        A[0, 3] = 1.0  # dx/dvx
        A[1, 4] = 1.0  # dy/dvy
        A[2, 5] = 1.0  # dz/dvz

        # Velocity derivatives w.r.t. Euler angles
        # vx_dot = T/m * (sin(theta)*cos(psi)*cos(phi) + sin(phi)*sin(psi))
        A[3, 6] = T / m * (-sp * st * cs + cp * ss)       # d(vx_dot)/d(phi)
        A[3, 7] = T / m * ct * cs * cp                     # d(vx_dot)/d(theta)
        A[3, 8] = T / m * (-st * ss * cp + sp * cs)        # d(vx_dot)/d(psi)

        # vy_dot = T/m * (sin(theta)*sin(psi)*cos(phi) - sin(phi)*cos(psi))
        A[4, 6] = T / m * (-sp * st * ss - cp * cs)        # d(vy_dot)/d(phi)
        A[4, 7] = T / m * ct * ss * cp                     # d(vy_dot)/d(theta)
        A[4, 8] = T / m * (st * cs * cp + sp * ss)         # d(vy_dot)/d(psi)

        # vz_dot = -g + T/m * cos(phi)*cos(theta)
        A[5, 6] = -T / m * sp * ct                         # d(vz_dot)/d(phi)
        A[5, 7] = -T / m * cp * st                         # d(vz_dot)/d(theta)

        # Euler angle kinematics
        # phi_dot = p + q*sin(phi)*tan(theta) + r*cos(phi)*tan(theta)
        A[6, 6] = q * cp * tt - r * sp * tt                # d(phi_dot)/d(phi)
        A[6, 7] = q * sp * (tt**2 + 1) + r * cp * (tt**2 + 1)  # d(phi_dot)/d(theta)
        A[6, 9] = 1.0                                      # d(phi_dot)/d(p)
        A[6, 10] = sp * tt                                  # d(phi_dot)/d(q)
        A[6, 11] = cp * tt                                  # d(phi_dot)/d(r)

        # theta_dot = q*cos(phi) - r*sin(phi)
        A[7, 6] = -q * sp - r * cp                         # d(theta_dot)/d(phi)
        A[7, 10] = cp                                       # d(theta_dot)/d(q)
        A[7, 11] = -sp                                      # d(theta_dot)/d(r)

        # psi_dot = (q*sin(phi) + r*cos(phi)) / cos(theta)
        if abs(ct) > 1e-6:
            A[8, 6] = (q * cp - r * sp) / ct               # d(psi_dot)/d(phi)
            A[8, 7] = (q * sp * st + r * cp * st) / ct**2  # d(psi_dot)/d(theta)
            A[8, 10] = sp / ct                               # d(psi_dot)/d(q)
            A[8, 11] = cp / ct                               # d(psi_dot)/d(r)

        # Angular rate dynamics (with gyroscopic coupling + rotational damping)
        # p_dot = (Iyy-Izz)/Ixx * q*r + L/Ixx * tau_phi - krot*p
        A[9, 9] = -krot                                     # d(p_dot)/d(p)
        A[9, 10] = (Iyy - Izz) / Ixx * r                   # d(p_dot)/d(q)
        A[9, 11] = (Iyy - Izz) / Ixx * q                   # d(p_dot)/d(r)

        # q_dot = (Izz-Ixx)/Iyy * p*r + L/Iyy * tau_theta - krot*q
        A[10, 9] = (Izz - Ixx) / Iyy * r                   # d(q_dot)/d(p)
        A[10, 10] = -krot                                    # d(q_dot)/d(q)
        A[10, 11] = (Izz - Ixx) / Iyy * p                   # d(q_dot)/d(r)

        # r_dot = (Ixx-Iyy)/Izz * p*q + L/Izz * tau_psi - krot*r
        A[11, 9] = (Ixx - Iyy) / Izz * q                   # d(r_dot)/d(p)
        A[11, 10] = (Ixx - Iyy) / Izz * p                   # d(r_dot)/d(q)
        A[11, 11] = -krot                                    # d(r_dot)/d(r)

        # B matrix: control input effects
        B = np.zeros((12, 4))
        # Thrust direction depends on attitude (not just 1/m for vz)
        B[3, 0] = (sp * ss + st * cp * cs) / m              # d(vx_dot)/d(T)
        B[4, 0] = (-sp * cs + st * cp * ss) / m             # d(vy_dot)/d(T)
        B[5, 0] = cp * ct / m                               # d(vz_dot)/d(T)
        B[9, 1] = L / Ixx                                   # d(p_dot)/d(tau_phi)
        B[10, 2] = L / Iyy                                   # d(q_dot)/d(tau_theta)
        B[11, 3] = L / Izz                                   # d(r_dot)/d(tau_psi)

        return A, B

    # -- Gain scheduling (adapted from ProgPy LQR.build_scheduled_control) -----

    def _build_gain_schedule(self):
        """Pre-compute LQR gains over a yaw-angle grid.

        Following ProgPy's approach: linearize at (phi=0, theta=0, psi_k,
        p=q=r=0, T=mg) for 721 evenly-spaced yaw angles in [-2pi, 2pi],
        then solve CARE for each to get K_k.  At runtime, look up the
        nearest K by current psi.
        """
        mg = self.mass * GRAVITY

        # Q matrix: state error penalty
        Q = np.diag([
            10.0, 10.0, 20.0,    # x, y, z position
            10.0, 10.0, 15.0,    # vx, vy, vz velocity
            80.0, 80.0, 20.0,    # phi, theta, psi angles
            20.0, 20.0, 10.0,    # p, q, r angular rates
        ])

        # R matrix: control effort penalty
        R = np.diag([
            0.5,   # thrust
            10.0,  # tau_phi
            10.0,  # tau_theta
            15.0,  # tau_psi
        ])

        self.psi_grid = np.linspace(-2.0 * np.pi, 2.0 * np.pi, N_PSI_GRID)
        self.gain_schedule = np.zeros((N_PSI_GRID, 4, 12))

        for i, psi_k in enumerate(self.psi_grid):
            A, B = self._linearize(0.0, 0.0, psi_k, 0.0, 0.0, 0.0, mg)
            P = solve_continuous_are(A, B, Q, R)
            self.gain_schedule[i] = np.linalg.solve(R, B.T @ P)

    def _lookup_gain(self, psi):
        """Find the pre-computed gain matrix nearest to current yaw angle."""
        idx = np.argmin(np.abs(self.psi_grid - psi))
        return self.gain_schedule[idx]

    # -- Reference trajectory --------------------------------------------------

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

    # -- GCS command handling --------------------------------------------------

    def _handle_gcs_command(self, pos, t, cmd_str):
        """Parse and execute a GCS command (JSON string from state['gcs_command'])."""
        if cmd_str is None or not isinstance(cmd_str, str):
            return
        try:
            cmd = json.loads(cmd_str)
        except (json.JSONDecodeError, TypeError):
            return

        task = cmd.get('task')

        if task == 'hold':
            self.target = pos
            self.ref_trajectory = None
            self.hovering = True
            self._waypoints_changed = True

        elif task == 'goto':
            target = (cmd['x'], cmd['y'], cmd['z'])
            self.speed = cmd.get('speed', self.speed)
            self.waypoints = [pos, target]
            self.target = target
            self.ref_trajectory = self._build_reference_trajectory(t)
            self.hovering = False
            self._waypoints_changed = True

        elif task == 'waypoints':
            wps = cmd['waypoints']
            self.waypoints = [pos] + [(w['x'], w['y'], w['z']) for w in wps]
            self.speed = wps[0].get('speed', self.speed)
            self.target = self.waypoints[-1]
            self.ref_trajectory = self._build_reference_trajectory(t)
            self._waypoints_changed = True
            if len(self.waypoints) <= 1:
                self.hovering = True
            else:
                self.hovering = False

    # -- Main control loop -----------------------------------------------------

    def on_ctl_tick(self, state):
        pos = state['pos']
        vel = state['vel']
        euler = state['euler']
        omega = state['omega']
        t = state['time']

        # --- First call: extract params and build gain schedule ---
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
                self.target = self.waypoints[-1]
            else:
                self.target = pos

            self._build_gain_schedule()

            # Build reference trajectory if we have multiple waypoints
            if len(self.waypoints) > 1:
                self.ref_trajectory = self._build_reference_trajectory(t)
                self.hovering = False
            else:
                self.hovering = True

            return {'thrust': self.mass * GRAVITY}

        # --- GCS command handling ---
        self._handle_gcs_command(pos, t, state['gcs_command'])

        # --- Look up reference state ---
        if self.ref_trajectory and not self.hovering:
            px, py, pz, vx_ref, vy_ref, vz_ref = self._lookup_reference(t)
        else:
            px, py, pz = self.target
            vx_ref, vy_ref, vz_ref = 0.0, 0.0, 0.0

        # --- Build state error vector (tracking error) ---
        # Clamp position and velocity errors to prevent the controller from
        # commanding extreme corrections when far off-track.
        MAX_POS_ERR = 15.0   # meters
        MAX_VEL_ERR = 8.0    # m/s

        pos_err = [pos[0] - px, pos[1] - py, pos[2] - pz]
        vel_err = [vel[0] - vx_ref, vel[1] - vy_ref, vel[2] - vz_ref]
        for i in range(3):
            pos_err[i] = max(-MAX_POS_ERR, min(MAX_POS_ERR, pos_err[i]))
            vel_err[i] = max(-MAX_VEL_ERR, min(MAX_VEL_ERR, vel_err[i]))

        x_err = np.array([
            pos_err[0], pos_err[1], pos_err[2],
            vel_err[0], vel_err[1], vel_err[2],
            euler[0], euler[1], euler[2],
            omega[0], omega[1], omega[2],
        ])

        # --- LQR control: u = u_hover - K(psi) * x_err ---
        # Look up the gain matrix scheduled on current yaw angle
        psi = euler[2]
        K = self._lookup_gain(psi)
        u_correction = K @ x_err

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

        result = {
            'thrust': thrust,
            'torque_phi': torque_phi,
            'torque_theta': torque_theta,
            'torque_psi': torque_psi,
        }

        if self._waypoints_changed:
            self._waypoints_changed = False
            result['waypoints'] = [
                {'x': wp[0], 'y': wp[1], 'z': wp[2], 'speed': self.speed}
                for wp in self.waypoints
            ]

        return result