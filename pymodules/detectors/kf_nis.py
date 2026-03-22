"""
GCS-side KF NIS detector.

Reads the per-receiver KF NIS values computed by the C++
KalmanFilterDetectMgmt module (piped through GcsReport.kfNis).
Reports the maximum NIS across all receivers for each transmission.

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
    """Online KF NIS spoofing detector using C++ Kalman filter output."""

    def __init__(self):
        self._detections = 0

    def on_gcs_reports(self, data):
        reports = data['reports']

        # Collect all non-None KF NIS values from this transmission
        nis_values = [r['kf_nis'] for r in reports if r.get('kf_nis') is not None]

        if not nis_values:
            return {'log': {'kf_max_nis': 0.0, 'kf_mean_nis': 0.0}}

        max_nis = max(nis_values)
        mean_nis = sum(nis_values) / len(nis_values)

        return {
            'log': {
                'kf_max_nis': max_nis,
                'kf_mean_nis': mean_nis,
            },
        }
