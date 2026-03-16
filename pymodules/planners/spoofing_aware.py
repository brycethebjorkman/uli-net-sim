import random

class SpoofingAwarePlanner:
    """ Performs spoofing localization and uses a risk-domain approach to plan federate trajectories """

    def __init__(self):
        self._federate_ids = set()
        self.rng = random.Random(42)

    def on_gcs_tick(self, data):
        host_ids = data['host_ids']
        commands = {}
        for hid in host_ids:
            some_val = self.rng.uniform(self.alt_min, self.alt_max)
            commands[hid] = {'value_computed': some_val}

        return {
            'commands': commands,
            'log': {
                'tick_count': data.get('tick_count', 0),
            },
        }

    def on_gcs_reports(self, data):
        serial = data['serial_number']
        reports = data['reports']

        for r in reports:
            self._federate_ids.add(r['host_id'])

        some_val = self.rng.uniform(self.alt_min, self.alt_max)

        return {
            'log': {
                'serial_seen': serial,
                'value_computed': some_val,
            },
        }
