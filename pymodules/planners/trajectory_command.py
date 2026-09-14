"""
Deterministic trajectory command planner for testing CascadedPidController
gcs_command handling.

Sends a sequence of goto/hold/waypoints commands at specific ticks to
exercise all three command types.

INI usage:
    *.gcs[0].pyClass = "pymodules.planners.trajectory_command.TrajectoryCommandPlanner"
    *.gcs[0].tickInterval = 2s
    *.gcs[0].sendControlCommands = true
"""


class TrajectoryCommandPlanner:
    """Issues deterministic trajectory commands to test gcs_command handling."""

    def __init__(self):
        self._tick = 0

    def on_gcs_tick(self, data):
        host_ids = data['host_ids']
        self._tick += 1

        commands = {}
        log = {'tick_count': self._tick}

        if self._tick == 1:
            # Tick 1 (t=2s): send goto command to all hosts
            for hid in host_ids:
                commands[hid] = {
                    'task': 'goto',
                    'x': 250.0,
                    'y': 250.0,
                    'z': 60.0,
                    'speed': 8.0,
                }
            log['command'] = 1.0  # goto

        elif self._tick == 3:
            # Tick 3 (t=6s): hold position
            for hid in host_ids:
                commands[hid] = {'task': 'hold'}
            log['command'] = 2.0  # hold

        elif self._tick == 5:
            # Tick 5 (t=10s): new waypoint path
            for hid in host_ids:
                commands[hid] = {
                    'task': 'waypoints',
                    'waypoints': [
                        {'x': 250.0, 'y': 250.0, 'z': 60.0, 'speed': 6.0},
                        {'x': 300.0, 'y': 300.0, 'z': 80.0, 'speed': 6.0},
                        {'x': 350.0, 'y': 250.0, 'z': 70.0, 'speed': 6.0},
                    ],
                }
            log['command'] = 3.0  # waypoints

        else:
            log['command'] = 0.0  # no command

        return {
            'commands': commands,
            'log': log,
        }
