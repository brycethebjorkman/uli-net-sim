"""
GCS-side KF NIS detector.

Reads the per-receiver KF NIS values computed by the C++
KalmanFilterDetectMgmt module (piped through GcsReport.kfNis).
Logs per-RX-event NIS for each (receiver, serial_number) pair
(matching the offline KalmanFilterDetector granularity) and also
the max/mean across receivers for convenience.

Requires federate hosts to use KalmanFilterDetectMgmt (or a subclass)
as their beacon management module. Non-KF hosts will have kf_nis = None.

INI usage:
    *.numGcs = 1
    *.gcs[0].pyClass = "pymodules.detectors.kf_nis.KfNisDetector"
    *.gcs[0].federateIndices = "0 1 2 3"
    # Federates must use KalmanFilterDetectMgmt:
    *.host[0..3].wlan[0].mgmt.typename = "KalmanFilterDetectMgmt"
"""


class KfNisDetector:
    """Online KF NIS spoofing detector using C++ Kalman filter output.

    Logs one ``kf_nis_host{id}_sn{serial}`` value per receiver per
    transmission (same granularity as the offline KalmanFilterDetector),
    plus ``kf_max_nis`` and ``kf_mean_nis`` aggregates.
    """

    def __init__(self):
        pass

    def on_gcs_reports(self, data):
        reports = data['reports']
        serial_number = data['serial_number']

        log = {}
        nis_values = []

        for r in reports:
            nis = r.get('kf_nis')
            if nis is None:
                continue
            nis_values.append(nis)
            host_id = r['host_id']
            log[f'kf_nis_host{host_id}_sn{serial_number}'] = nis

        if nis_values:
            log['kf_max_nis'] = max(nis_values)
            log['kf_mean_nis'] = sum(nis_values) / len(nis_values)
        else:
            log['kf_max_nis'] = 0.0
            log['kf_mean_nis'] = 0.0

        return {'log': log}
