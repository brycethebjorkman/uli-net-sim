"""
TX hook that claims to be a fixed distance further along the waypoint path.

The spoofed position is projected forward from the drone's actual position
along the pre-planned waypoint path segments. At turns, the projected
position follows the path rather than cutting corners.

INI usage:
    *.host[1].wlan[0].mgmt.pyTxClass = "pymodules.spoofers.snow_plow.SnowPlowSpoofer"
"""

import math


class SnowPlowSpoofer:
    """Claims a position offset_m further along the waypoint path."""

    def __init__(self):
        self.offset_m = 50.0
        self.waypoints = None  # [(x, y, z), ...]

    def on_rid_tx(self, state):
        if 'waypoints' in state:
            wps = state['waypoints']
            if wps:
                self.waypoints = [(w['x'], w['y'], w['z']) for w in wps]

        if not self.waypoints or len(self.waypoints) < 2:
            return None

        pos = state['pos']
        spoofed = self._project_along_path(pos[0], pos[1], pos[2])
        return {'pos': spoofed}

    def _project_along_path(self, px, py, pz):
        """Find the nearest point on the path, then advance offset_m forward."""
        wps = self.waypoints

        # Find the closest segment and the projection onto it
        best_seg = 0
        best_t = 0.0
        best_dist2 = float('inf')

        for i in range(len(wps) - 1):
            ax, ay, az = wps[i]
            bx, by, bz = wps[i + 1]
            dx, dy, dz = bx - ax, by - ay, bz - az
            seg_len2 = dx * dx + dy * dy + dz * dz
            if seg_len2 < 1e-9:
                continue
            t = ((px - ax) * dx + (py - ay) * dy + (pz - az) * dz) / seg_len2
            t = max(0.0, min(1.0, t))
            cx = ax + t * dx
            cy = ay + t * dy
            cz = az + t * dz
            d2 = (px - cx) ** 2 + (py - cy) ** 2 + (pz - cz) ** 2
            if d2 < best_dist2:
                best_dist2 = d2
                best_seg = i
                best_t = t

        # Walk forward along the path by offset_m from the projected point
        remaining = self.offset_m

        # Distance remaining on the current segment
        ax, ay, az = wps[best_seg]
        bx, by, bz = wps[best_seg + 1]
        dx, dy, dz = bx - ax, by - ay, bz - az
        seg_len = math.sqrt(dx * dx + dy * dy + dz * dz)
        dist_to_end = (1.0 - best_t) * seg_len

        if dist_to_end >= remaining:
            frac = best_t + remaining / seg_len
            return (ax + frac * dx, ay + frac * dy, az + frac * dz)

        remaining -= dist_to_end

        # Advance through subsequent segments
        for i in range(best_seg + 1, len(wps) - 1):
            ax, ay, az = wps[i]
            bx, by, bz = wps[i + 1]
            dx, dy, dz = bx - ax, by - ay, bz - az
            seg_len = math.sqrt(dx * dx + dy * dy + dz * dz)
            if seg_len < 1e-9:
                continue
            if seg_len >= remaining:
                frac = remaining / seg_len
                return (ax + frac * dx, ay + frac * dy, az + frac * dz)
            remaining -= seg_len

        # Past the end of the path — clamp to last waypoint
        return wps[-1]
