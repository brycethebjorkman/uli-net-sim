"""
GCS-side combined KF + MLAT spoofing detector.

Runs both the KF NIS detector (from C++ Kalman filter) and the RSSI
multilateration detector on each transmission, logging scores from both.
Declares spoofing if either detector exceeds its threshold.

INI usage:
    *.numGcs = 1
    *.gcs[0].pyClass = "pymodules.detectors.combined.CombinedDetector"
    *.gcs[0].federateIndices = "0 1 2 3"
    # Federates should use KalmanFilterDetectMgmt for KF NIS:
    *.host[0..3].wlan[0].mgmt.typename = "KalmanFilterDetectMgmt"
"""

from pymodules.detectors.kf_nis import KfNisDetector
from pymodules.detectors.rssi_multilateration import RssiMultilaterationDetector


class CombinedDetector:
    """Composes KF NIS and MLAT detectors, logs both scores."""

    def __init__(self):
        self._kf = KfNisDetector()
        self._mlat = RssiMultilaterationDetector()

        # Default thresholds (can be overridden by loading from thresholds.json)
        self.kf_threshold = 6.63    # 99% chi-square, 1 DOF
        self.mlat_threshold = 50.0  # meters filtered position error

    def on_gcs_reports(self, data):
        kf_result = self._kf.on_gcs_reports(data)
        mlat_result = self._mlat.on_gcs_reports(data)

        kf_max_nis = kf_result['log'].get('kf_max_nis', 0.0)
        mlat_score = mlat_result['log'].get('mlat_score', 0.0)

        is_spoofed = (kf_max_nis > self.kf_threshold) or (mlat_score > self.mlat_threshold)

        log = {}
        log.update(kf_result['log'])
        log.update(mlat_result['log'])
        log['combined_alert'] = 1.0 if is_spoofed else 0.0

        return {'log': log}
