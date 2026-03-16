"""
PD position-hold controller for MultirotorMobility.

Records the initial position on first call and uses cascaded PD control
to hold that position:
  - Outer loop: position error → desired acceleration → desired angles
  - Inner loop: angle error → torques

Responds to GCS commands with a target_z key to change altitude setpoint.

INI usage:
    *.host[*].mobility.pyClass = "pymodules.controllers.hover.HoverController"
"""

import json
import math


GRAVITY = 9.81


class HoverController:
    """Cascaded PD position-hold controller."""

    def __init__(self):
        self.target_pos = None
        self.mass = 5.0
        # Altitude gains
        self.Kp_z = 10.0
        self.Kd_z = 5.0
        # Horizontal position → desired acceleration
        self.Kp_xy = 2.0
        self.Kd_xy = 3.0
        # Angle → torque (inner loop)
        self.Kp_angle = 20.0
        self.Kd_angle = 8.0
        # Max tilt angle (radians) — clamp desired angles for safety
        self.max_tilt = 0.5

    def on_ctl_tick(self, state):
        pos = state['pos']
        vel = state['vel']
        euler = state['euler']  # (phi, theta, psi)
        omega = state['omega']  # (p, q, r)

        # Parse GCS command if present
        gcs_cmd = state['gcs_command']
        if gcs_cmd is not None and isinstance(gcs_cmd, str):
            try:
                gcs_cmd = json.loads(gcs_cmd)
            except (json.JSONDecodeError, TypeError):
                gcs_cmd = None

        if self.target_pos is None:
            self.target_pos = list(pos)
            return {'thrust': self.mass * GRAVITY}

        # Update altitude target from GCS command
        if gcs_cmd and 'target_z' in gcs_cmd:
            self.target_pos[2] = gcs_cmd['target_z']

        # --- Altitude PD ---
        ez = self.target_pos[2] - pos[2]
        thrust = self.mass * (GRAVITY + self.Kp_z * ez - self.Kd_z * vel[2])
        thrust = max(0.0, thrust)

        # --- Outer loop: position PD → desired acceleration → desired angles ---
        ax_des = self.Kp_xy * (self.target_pos[0] - pos[0]) - self.Kd_xy * vel[0]
        ay_des = self.Kp_xy * (self.target_pos[1] - pos[1]) - self.Kd_xy * vel[1]

        # Convert desired acceleration to desired angles (heading-aware).
        # Rotate world-frame desired accel into body heading frame so that
        # pitch/roll produce the correct world-frame force regardless of yaw.
        phi, theta, psi = euler
        p, q, r = omega

        cpsi = math.cos(psi)
        spsi = math.sin(psi)
        ab_x = ax_des * cpsi + ay_des * spsi
        ab_y = -ax_des * spsi + ay_des * cpsi

        theta_des = ab_x / GRAVITY
        phi_des = -ab_y / GRAVITY

        # Clamp desired angles
        theta_des = max(-self.max_tilt, min(self.max_tilt, theta_des))
        phi_des = max(-self.max_tilt, min(self.max_tilt, phi_des))

        torque_phi = self.Kp_angle * (phi_des - phi) - self.Kd_angle * p
        torque_theta = self.Kp_angle * (theta_des - theta) - self.Kd_angle * q
        torque_psi = -self.Kd_angle * r  # Just damp yaw rate

        return {
            'thrust': thrust,
            'torque_phi': torque_phi,
            'torque_theta': torque_theta,
            'torque_psi': torque_psi,
        }
