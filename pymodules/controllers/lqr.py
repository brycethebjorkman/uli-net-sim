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
    """LQR controller with hover-point linearization."""

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
        # Position: high weight; velocity: medium; angles: medium; rates: low
        Q = np.diag([
            20.0, 20.0, 30.0,    # x, y, z position
            5.0,  5.0,  8.0,     # vx, vy, vz velocity
            10.0, 10.0, 5.0,     # phi, theta, psi angles
            1.0,  1.0,  1.0,     # p, q, r angular rates
        ])

        # R matrix: control effort penalty
        R = np.diag([
            1.0,   # thrust
            10.0,  # tau_phi  (penalize torques more to avoid aggressive tilting)
            10.0,  # tau_theta
            10.0,  # tau_psi
        ])

        # Solve continuous algebraic Riccati equation: A'P + PA - PBR^{-1}B'P + Q = 0
        P = solve_continuous_are(A, B, Q, R)
        self.K = np.linalg.solve(R, B.T @ P)  # K = R^{-1} B' P

    def on_ctl_tick(self, state):
        pos = state['pos']
        vel = state['vel']
        euler = state['euler']
        omega = state['omega']

        # --- First call: extract params and compute gain ---
        if not self.initialized:
            self.initialized = True
            self.mass = state.get('mass', 5.0)
            self.arm_length = state.get('arm_length', 0.5)
            self.Ixx = state.get('Ixx', 0.5)
            self.Iyy = state.get('Iyy', 0.5)
            self.Izz = state.get('Izz', 0.8)

            wps = state.get('waypoints', [])
            if wps:
                self.waypoints = [(w['x'], w['y'], w['z']) for w in wps]
                self.speed = wps[0].get('speed', 10.0)
                # Start by hovering at first waypoint
                self.target = self.waypoints[0]
            else:
                self.target = pos

            self._compute_gain()
            return {'thrust': self.mass * GRAVITY}

        # --- Build state error vector ---
        tx, ty, tz = self.target
        x_err = np.array([
            pos[0] - tx, pos[1] - ty, pos[2] - tz,
            vel[0], vel[1], vel[2],
            euler[0], euler[1], euler[2],
            omega[0], omega[1], omega[2],
        ])

        # --- LQR control: u = u_hover - K * x_err ---
        u_correction = self.K @ x_err
        thrust = self.mass * GRAVITY - u_correction[0]
        thrust = max(0.0, thrust)

        return {
            'thrust': thrust,
            'torque_phi': -u_correction[1],
            'torque_theta': -u_correction[2],
            'torque_psi': -u_correction[3],
        }
