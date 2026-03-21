"""
Deterministic trajectory command planner for testing LqrController
gcs_command handling.

Same command sequence as TrajectoryCommandPlanner but with closer targets
appropriate for the LQR controller's softer response.

INI usage:
    *.gcs[0].pyClass = "pymodules.planners.lqr_trajectory_command.LqrTrajectoryCommandPlanner"
    *.gcs[0].tickInterval = 2s
    *.gcs[0].sendControlCommands = true
"""


class LqrTrajectoryCommandPlanner:
    """Issues deterministic trajectory commands scaled for LQR response."""

    def __init__(self):
        self._tick = 0

    def on_gcs_tick(self, data):
        host_ids = data['host_ids']
        self._tick += 1

        commands = {}
        log = {'tick_count': self._tick}

        if self._tick == 1:
            # Tick 1 (t=2s): goto nearby target
            for hid in host_ids:
                commands[hid] = {
                    'task': 'goto',
                    'x': 240.0,
                    'y': 240.0,
                    'z': 55.0,
                    'speed': 5.0,
                }
            log['command'] = 1.0  # goto

        elif self._tick == 3:
            # Tick 3 (t=6s): hold position
            for hid in host_ids:
                commands[hid] = {'task': 'hold'}
            log['command'] = 2.0  # hold

        elif self._tick == 5:
            # Tick 5 (t=10s): short waypoint path
            for hid in host_ids:
                commands[hid] = {
                    'task': 'waypoints',
                    'waypoints': [
                        {'x': 250.0, 'y': 250.0, 'z': 55.0, 'speed': 4.0},
                        {'x': 270.0, 'y': 270.0, 'z': 65.0, 'speed': 4.0},
                        {'x': 290.0, 'y': 250.0, 'z': 60.0, 'speed': 4.0},
                    ],
                }
            log['command'] = 3.0  # waypoints

        else:
            log['command'] = 0.0  # no command

        return {
            'commands': commands,
            'log': log,
        }
