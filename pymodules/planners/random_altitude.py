"""
Random altitude planner for GcsModule.

Periodically issues a command to each federate host with a new random
altitude target.  The target is drawn uniformly from [alt_min, alt_max].

Demonstrates the GcsModule on_tick() periodic callback and command
forwarding to MultirotorMobility (via the HoverController's target_z
handling).

INI usage:
    *.gcs[0].pyClass = "pymodules.planners.random_altitude.RandomAltitudePlanner"
    *.gcs[0].tickInterval = 2s
    *.gcs[0].sendControlCommands = true
"""

import json
import random


class RandomAltitudePlanner:
    """Issues random altitude commands to federate hosts on each tick."""

    def __init__(self):
        self.alt_min = 30.0
        self.alt_max = 120.0
        self.rng = random.Random(42)

    def on_tick(self, data):
        host_ids = data['host_ids']
        commands = {}
        for hid in host_ids:
            target_z = self.rng.uniform(self.alt_min, self.alt_max)
            commands[hid] = {'target_z': target_z}

        return {
            'commands': commands,
            'log': {
                'tick_count': data.get('tick_count', 0),
            },
        }
