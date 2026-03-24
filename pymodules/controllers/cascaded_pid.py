"""
ArduCopter-inspired cascaded PID controller for MultirotorMobility.

Mirrors the ArduCopter control stack (AC_WPNav -> AC_PosControl ->
AC_AttitudeControl) with simplifications for simulation:

  Segment following (WPNav) -> Position(P) -> Velocity(PI) ->
  Accel-to-attitude -> Attitude(PD) -> Torque

See docs/cascaded_pid_control.md for the full algorithm description
and a detailed comparison with the ArduCopter source.

INI usage:
    *.host[*].mobility.pyClass = "pymodules.controllers.cascaded_pid.CascadedPidController"
    *.host[0].mobility.waypointScript = xmldoc("traj.xml", "movements/movement[@id='0']")
"""

import json
import math


GRAVITY = 9.81


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _vec_len(x, y, z=0.0):
    return math.sqrt(x * x + y * y + z * z)


class CascadedPidController:
    """ArduCopter-inspired cascaded PID trajectory controller."""

    def __init__(self):
        self.mass = 5.0
        self.waypoints = []  # list of (x, y, z)
        self.speed = 10.0  # cruise speed (m/s), from <set> element
        self.seg_index = 1  # current segment target
        self.hovering = False

        # Carrot state
        self.carrot_s = 0.0  # along-track position on current segment (meters)
        self.carrot_speed = 0.0  # current carrot speed (m/s), for speed profile
        self.track_dt_scalar = 1.0  # filtered track time scaling

        # Track scaling gain — ArduPilot uses PSC_POSXY_P for both
        # position correction and track scaling. With Kp_pos=1.0 and our
        # drag model, the carrot tracks well without a separate lower gain.
        self.Kp_track = 0.5

        # Position P gain (carrot error -> velocity setpoint)
        # ArduPilot PSC_POSXY_P = 1.0
        self.Kp_pos = 1.0

        # Velocity PI gains
        # ArduPilot PSC_VELXY_P = 1.0, PSC_VELXY_I = 0.5, PSC_VELXY_D = 0.5
        # We use higher P to compensate for no D-term, but not 6x
        self.Kp_vel_xy = 2.0
        self.Ki_vel_xy = 0.2
        self.Kp_vel_z = 4.0
        self.Ki_vel_z = 0.5

        # Attitude PD gains — scaled at runtime by inertia/armLength.
        # These are *desired angular response* gains: the actual torque gains
        # are Kp_angle_base * (Ixx / armLength) etc., so the angular acceleration
        # produced is independent of the airframe's physical parameters.
        self.Kp_angle_base = 20.0  # desired angular accel per rad error (rad/s^2/rad)
        self.Kd_angle_base = 8.0   # desired angular accel per rad/s rate (rad/s^2/(rad/s))
        # Actual gains (set on first call from physical params)
        self.Kp_angle = 20.0
        self.Kd_angle = 8.0

        # Limits
        self.max_accel = 5.0  # m/s^2, trapezoidal speed profile
        self.max_tilt = 0.5  # rad
        self.max_integral = 5.0  # anti-windup
        self.acceptance_radius = 3.0  # meters, for final waypoint reached

        # Integral accumulators
        self.vel_integral = [0.0, 0.0, 0.0]

        # Time tracking
        self.last_time = None
        self.initialized = False

        # Waypoint visualization update flag
        self._waypoints_changed = False

        # Precomputed segment geometry
        self._seg_dir = (1.0, 0.0, 0.0)
        self._seg_len = 0.0

    def _handle_gcs_command(self, pos, cmd_str):
        """Parse and execute a GCS command (JSON string from state['gcs_command'])."""
        if cmd_str is None or not isinstance(cmd_str, str):
            return
        try:
            cmd = json.loads(cmd_str)
        except (json.JSONDecodeError, TypeError):
            return

        task = cmd.get('task')

        if task == 'hold':
            # Hold at current position
            self.hovering = True
            self.waypoints = [pos] if not self.waypoints else self.waypoints
            self.seg_index = max(self.seg_index, len(self.waypoints) - 1)
            # Park the carrot at the hold waypoint
            if self.waypoints:
                self.waypoints[self.seg_index] = pos
            self.vel_integral = [0.0, 0.0, 0.0]
            self._waypoints_changed = True

        elif task == 'goto':
            # Fly from current position to target
            target = (cmd['x'], cmd['y'], cmd['z'])
            speed = cmd.get('speed', self.speed)
            self.waypoints = [pos, target]
            self.speed = speed
            self.seg_index = 1
            self.carrot_s = 0.0
            self.carrot_speed = 0.0
            self.track_dt_scalar = 1.0
            self.vel_integral = [0.0, 0.0, 0.0]
            self.hovering = False
            self._setup_segment()
            self._waypoints_changed = True

        elif task == 'waypoints':
            # Replace entire waypoint list
            wps = cmd['waypoints']
            self.waypoints = [(w['x'], w['y'], w['z']) for w in wps]
            self.speed = wps[0].get('speed', self.speed)
            self.seg_index = 1
            self.carrot_s = 0.0
            self.carrot_speed = 0.0
            self.track_dt_scalar = 1.0
            self.vel_integral = [0.0, 0.0, 0.0]
            if len(self.waypoints) <= 1:
                self.hovering = True
            else:
                self.hovering = False
                self._setup_segment()
            self._waypoints_changed = True

    def _setup_segment(self):
        """Precompute direction and length for the current segment."""
        wp_prev = self.waypoints[self.seg_index - 1]
        wp_curr = self.waypoints[self.seg_index]
        dx = wp_curr[0] - wp_prev[0]
        dy = wp_curr[1] - wp_prev[1]
        dz = wp_curr[2] - wp_prev[2]
        length = _vec_len(dx, dy, dz)
        if length < 1e-6:
            self._seg_dir = (0.0, 0.0, 0.0)
            self._seg_len = 0.0
        else:
            self._seg_dir = (dx / length, dy / length, dz / length)
            self._seg_len = length

    def _advance_carrot(self, pos, vel, dt):
        """Advance carrot along segment. Returns carrot 3D position."""
        tx, ty, tz = self._seg_dir
        seg_len = self._seg_len

        if seg_len < 1e-6:
            self.carrot_s = 0.0
            return self.waypoints[self.seg_index]

        # --- Trapezoidal speed profile ---
        remaining = max(seg_len - self.carrot_s, 0.0)
        v_decel = math.sqrt(2.0 * self.max_accel * remaining) if remaining > 0 else 0.0
        self.carrot_speed = min(
            self.carrot_speed + self.max_accel * dt,
            self.speed,
            v_decel
        )
        self.carrot_speed = max(self.carrot_speed, 0.0)

        # --- Track time scaling (ArduPilot-style) ---
        # Along-track velocity of the drone
        v_track = vel[0] * tx + vel[1] * ty + vel[2] * tz

        # Along-track position of drone on this segment
        wp_prev = self.waypoints[self.seg_index - 1]
        drone_along = ((pos[0] - wp_prev[0]) * tx +
                       (pos[1] - wp_prev[1]) * ty +
                       (pos[2] - wp_prev[2]) * tz)

        # Track error: how far ahead is the carrot vs the drone
        track_error = self.carrot_s - drone_along

        # Compute instantaneous alpha using Kp_track (not Kp_pos).
        if self.carrot_speed > 1e-6:
            alpha = _clamp(
                0.05 + (v_track - self.Kp_track * track_error) / self.carrot_speed,
                0.0, 1.0
            )
        else:
            alpha = 1.0

        # Exponential filter with ~0.5s time constant
        tau = 0.5
        blend = min(dt / tau, 1.0)
        self.track_dt_scalar += (alpha - self.track_dt_scalar) * blend

        # --- Advance carrot ---
        self.carrot_s += self.carrot_speed * self.track_dt_scalar * dt
        self.carrot_s = min(self.carrot_s, seg_len)

        # --- Carrot 3D position (linear interpolation along segment) ---
        frac = self.carrot_s / seg_len
        wp_curr = self.waypoints[self.seg_index]
        cx = wp_prev[0] + frac * (wp_curr[0] - wp_prev[0])
        cy = wp_prev[1] + frac * (wp_curr[1] - wp_prev[1])
        cz = wp_prev[2] + frac * (wp_curr[2] - wp_prev[2])

        return (cx, cy, cz)

    def on_ctl_tick(self, state):
        pos = state['pos']
        vel = state['vel']
        euler = state['euler']
        omega = state['omega']
        t = state['time']

        # --- First call: store waypoints and mass ---
        if not self.initialized:
            self.initialized = True
            self.last_time = t

            wps = state.get('waypoints', [])
            if wps:
                self.waypoints = [(w['x'], w['y'], w['z']) for w in wps]
                self.speed = wps[0].get('speed', 10.0)
                self.mass = state.get('mass', 5.0)

                # Scale attitude gains by physical parameters so that the
                # angular *acceleration* response is consistent across airframes.
                # Torque-to-accel ratio is armLength/I, so we multiply the
                # base gains by I/armLength to cancel it out.
                arm = state.get('arm_length', 0.5)
                ixx = state.get('Ixx', 0.5)
                if arm > 1e-6:
                    scale = ixx / arm  # typical: 0.5/0.5=1, or 0.023/0.175=0.13
                    self.Kp_angle = self.Kp_angle_base * scale
                    self.Kd_angle = self.Kd_angle_base * scale
            else:
                self.hovering = True

            if len(self.waypoints) <= 1:
                self.hovering = True

            if not self.hovering:
                self._setup_segment()

            return {'thrust': self.mass * GRAVITY}

        # --- GCS command handling ---
        self._handle_gcs_command(pos, state['gcs_command'])

        # --- dt ---
        dt = t - self.last_time
        self.last_time = t
        if dt <= 0:
            dt = 0.01

        # --- Segment following ---
        if not self.hovering:
            carrot = self._advance_carrot(pos, vel, dt)

            # Check if carrot reached end of segment
            if self.carrot_s >= self._seg_len - 1e-6:
                wp = self.waypoints[self.seg_index]
                dist = _vec_len(wp[0] - pos[0], wp[1] - pos[1], wp[2] - pos[2])
                if dist < self.acceptance_radius or self.carrot_s >= self._seg_len:
                    self.seg_index += 1
                    if self.seg_index >= len(self.waypoints):
                        self.hovering = True
                        self.seg_index = len(self.waypoints) - 1
                        self.vel_integral = [0.0, 0.0, 0.0]
                    else:
                        self.carrot_s = 0.0
                        self.carrot_speed = 0.0
                        self.track_dt_scalar = 1.0
                        self.vel_integral = [0.0, 0.0, 0.0]
                        self._setup_segment()
                        carrot = self._advance_carrot(pos, vel, dt)
        else:
            carrot = self.waypoints[self.seg_index]

        # --- Velocity setpoint: feedforward + position correction ---
        # ArduPilot sends (pos, vel, accel) to PosControl. The velocity
        # feedforward drives the drone along the track at carrot speed;
        # position P correction handles cross-track and along-track error.
        err_x = carrot[0] - pos[0]
        err_y = carrot[1] - pos[1]
        err_z = carrot[2] - pos[2]

        if not self.hovering:
            tx, ty, tz = self._seg_dir

            # Decompose position error into along-track and cross-track
            err_along = err_x * tx + err_y * ty  # scalar projection
            err_cross_x = err_x - err_along * tx
            err_cross_y = err_y - err_along * ty

            # Feedforward: fly at carrot speed along track direction
            ff_speed = self.carrot_speed * self.track_dt_scalar

            # Along-track velocity: feedforward + P correction
            along_speed = ff_speed + self.Kp_pos * err_along
            along_speed = _clamp(along_speed, 0.0, self.speed)

            # Cross-track velocity: P correction, clamped independently
            # to a fraction of cruise speed to prevent aggressive oscillation
            cross_vel_x = self.Kp_pos * err_cross_x
            cross_vel_y = self.Kp_pos * err_cross_y
            max_cross = self.speed * 0.15
            cross_mag = _vec_len(cross_vel_x, cross_vel_y)
            if cross_mag > max_cross and cross_mag > 1e-6:
                scale = max_cross / cross_mag
                cross_vel_x *= scale
                cross_vel_y *= scale

            # Compose velocity setpoint
            vel_sp_x = along_speed * tx + cross_vel_x
            vel_sp_y = along_speed * ty + cross_vel_y

            # Altitude: feedforward along track Z + P correction
            vel_sp_z = ff_speed * tz + self.Kp_pos * err_z
            vel_sp_z = _clamp(vel_sp_z, -self.speed, self.speed)
        else:
            vel_sp_x = _clamp(self.Kp_pos * err_x, -2.0, 2.0)
            vel_sp_y = _clamp(self.Kp_pos * err_y, -2.0, 2.0)
            vel_sp_z = _clamp(self.Kp_pos * err_z, -2.0, 2.0)

        # --- Velocity PI -> desired acceleration ---
        vel_err_x = vel_sp_x - vel[0]
        vel_err_y = vel_sp_y - vel[1]
        vel_err_z = vel_sp_z - vel[2]

        self.vel_integral[0] += vel_err_x * dt
        self.vel_integral[1] += vel_err_y * dt
        self.vel_integral[2] += vel_err_z * dt

        for i in range(3):
            self.vel_integral[i] = _clamp(
                self.vel_integral[i], -self.max_integral, self.max_integral
            )

        accel_x = self.Kp_vel_xy * vel_err_x + self.Ki_vel_xy * self.vel_integral[0]
        accel_y = self.Kp_vel_xy * vel_err_y + self.Ki_vel_xy * self.vel_integral[1]
        accel_z = self.Kp_vel_z * vel_err_z + self.Ki_vel_z * self.vel_integral[2]

        # --- Altitude: thrust with gravity compensation ---
        thrust = self.mass * (GRAVITY + accel_z)
        thrust = max(0.0, thrust)

        # --- Horizontal accel -> desired attitude (heading-aware) ---
        # Rotate desired world-frame accel into the body heading frame.
        # Without this, the simple theta=ax/g approximation fails when
        # psi != 0, because pitch produces acceleration along the body-X
        # axis which is rotated relative to the world X axis.
        phi, theta, psi = euler
        p, q, r = omega

        cpsi = math.cos(psi)
        spsi = math.sin(psi)
        accel_body_x = accel_x * cpsi + accel_y * spsi
        accel_body_y = -accel_x * spsi + accel_y * cpsi

        theta_des = accel_body_x / GRAVITY
        phi_des = -accel_body_y / GRAVITY
        theta_des = _clamp(theta_des, -self.max_tilt, self.max_tilt)
        phi_des = _clamp(phi_des, -self.max_tilt, self.max_tilt)

        # --- Yaw: track direction of velocity setpoint ---
        if not self.hovering and (abs(vel_sp_x) > 0.5 or abs(vel_sp_y) > 0.5):
            psi_des = math.atan2(vel_sp_y, vel_sp_x)
            psi_err = psi_des - psi
            psi_err = (psi_err + math.pi) % (2 * math.pi) - math.pi
            torque_psi = self.Kp_angle * psi_err - self.Kd_angle * r
        else:
            torque_psi = -self.Kd_angle * r

        # --- Inner attitude PD -> torques ---
        torque_phi = self.Kp_angle * (phi_des - phi) - self.Kd_angle * p
        torque_theta = self.Kp_angle * (theta_des - theta) - self.Kd_angle * q

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
