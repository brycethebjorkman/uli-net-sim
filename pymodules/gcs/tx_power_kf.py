"""
TX-power Kalman filter for spoofing detection (mirrors C++ KalmanFilterDetectMgmt).

Tracks estimated transmit power per (serial, receiver). When claimed position
is wrong (spoofing), the RSSI-based TX power estimate is inconsistent -> high NIS.

Uses FSPL (Eq. 9): P_tx_hat = RSSI + 20*log10(d_claimed) + 40.04
"""

import numpy as np

PATH_LOSS_EXP = 2.0
FSPL_CONSTANT_DB = 40.04


def compute_tx_power(rx_pos: np.ndarray, claimed_pos: np.ndarray, rssi_dbm: float) -> float:
    d = max(np.linalg.norm(np.asarray(claimed_pos) - np.asarray(rx_pos)), 1e-3)
    return rssi_dbm + FSPL_CONSTANT_DB + 10.0 * PATH_LOSS_EXP * np.log10(d / 1000.0)


class TxPowerKF:
    """1D Kalman filter for TX power (matches C++ TxPowerKF)."""

    def __init__(self, Q: float = 0.01, R: float = 4.0):
        self.Q = Q
        self.R = R
        self.x = None
        self.P = None
        self.initialized = False

    def predict(self) -> None:
        if not self.initialized:
            return
        self.P = self.P + self.Q

    def update(self, z: float) -> tuple[float, float]:
        if not self.initialized:
            self.x = z
            self.P = 10.0
            self.initialized = True
            return 0.0, 0.0

        self.predict()
        y = z - self.x
        S = self.P + self.R
        K = self.P / S
        correction = abs(K * y)
        NIS = (y * y) / S
        self.x = self.x + K * y
        self.P = (1.0 - K) * self.P
        return NIS, correction


class TxPowerKFDetector:
    """Per-(serial, receiver) TX power KF for spoofing detection."""

    def __init__(self, nis_threshold: float = 6.63, correction_threshold: float = 6.0):
        self.nis_threshold = nis_threshold
        self.correction_threshold = correction_threshold
        self._filters: dict[tuple[int, int], TxPowerKF] = {}

    def process_report(
        self,
        serial: int,
        claimed_pos: np.ndarray,
        reports: list[dict],
    ) -> tuple[float, bool]:
        max_nis = 0.0
        max_correction = 0.0
        for r in reports:
            rx_id = r["host_id"]
            rx_pos = np.array(r["pos"])
            rssi = r["rssi_dbm"]
            z = compute_tx_power(rx_pos, claimed_pos, rssi)
            key = (serial, rx_id)
            if key not in self._filters:
                self._filters[key] = TxPowerKF()
            kf = self._filters[key]
            nis, correction = kf.update(z)
            max_nis = max(max_nis, nis)
            max_correction = max(max_correction, correction)
        is_spoofer = max_nis > self.nis_threshold or max_correction > self.correction_threshold
        return max_nis, is_spoofer
