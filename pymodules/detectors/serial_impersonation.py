"""
GCS-side serial number impersonation detector.

Detects when a transmitter uses a serial number belonging to one of
this GCS's own federate hosts. Since a host cannot receive its own
transmissions, any beacon received by a federate with the federate's
own serial number must be from an impersonator.

The detector is configured with a set of "protected" serial numbers
(the serial numbers of the hosts it monitors). On each transmission
report, it checks whether the claimed serial number matches any
protected serial. If so, it logs a detection event.

INI usage:
    *.numGcs = 1
    *.gcs[0].pyClass = "pymodules.detectors.serial_impersonation.SerialImpersonationDetector"
    *.gcs[0].federateIndices = "0"  # only host 0 reports to this GCS

The protected serial numbers are learned from the first report of each
federate host (host_id == serial_number for default configurations).
"""


class SerialImpersonationDetector:
    """Detects serial number impersonation via self-reception."""

    def __init__(self):
        # Set of federate host IDs seen so far.
        # In default configs, host_id == serialNumber, so any report
        # where serial_number == a known federate host_id is suspicious.
        self._federate_ids = set()
        self._detections = 0

    def on_reports(self, data):
        serial = data['serial_number']
        reports = data['reports']

        # Learn federate host IDs from incoming reports
        for r in reports:
            self._federate_ids.add(r['host_id'])

        # Check: is the claimed serial number one of our own federates?
        # If so, the transmitter is impersonating a federate host.
        is_impersonation = serial in self._federate_ids

        if is_impersonation:
            self._detections += 1

        return {
            'log': {
                'is_impersonation': 1.0 if is_impersonation else 0.0,
                'total_detections': float(self._detections),
            },
        }
