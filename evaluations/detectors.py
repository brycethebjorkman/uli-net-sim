"""
Spoofing detection methods.

Each detector takes RX event data and produces a detection score per event.
Higher scores indicate higher likelihood of spoofing.

Detectors:
1. KalmanFilterDetector - Uses KF NIS (Normalized Innovation Squared) from single receiver
2. MultilatDetector - Uses RSSI multilateration from multiple receivers
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any
import numpy as np
from scipy.optimize import least_squares

from .data import ScenarioData


class Detector(ABC):
    """Base class for spoofing detectors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable detector name."""
        pass

    @property
    @abstractmethod
    def params(self) -> dict[str, Any]:
        """Current detector parameters."""
        pass

    @abstractmethod
    def score(self, scenario: ScenarioData) -> np.ndarray:
        """
        Compute detection scores for all RX events in a scenario.

        Args:
            scenario: ScenarioData with RX events

        Returns:
            Array of detection scores, one per RX event.
            Higher scores indicate higher likelihood of spoofing.
        """
        pass

    def detect(self, scenario: ScenarioData, threshold: float) -> np.ndarray:
        """
        Binary detection using a threshold on scores.

        Args:
            scenario: ScenarioData with RX events
            threshold: Detection threshold

        Returns:
            Boolean array, True where spoofing is detected
        """
        return self.score(scenario) >= threshold


@dataclass
class KalmanFilterDetector(Detector):
    """
    Detect spoofing using Kalman Filter NIS (Normalized Innovation Squared).

    The KF estimates TX power from RSSI measurements. When the claimed position
    doesn't match the actual position (spoofing), the RSSI-based TX power estimate
    will be inconsistent, resulting in high NIS values.

    Parameters:
        None - uses pre-computed KF state from simulation
    """

    @property
    def name(self) -> str:
        return "KalmanFilter"

    @property
    def params(self) -> dict[str, Any]:
        return {}

    def score(self, scenario: ScenarioData) -> np.ndarray:
        """
        Return KF NIS as detection score.

        NaN values (KF not yet initialized) are replaced with 0.
        """
        scores = scenario.kf_nis.copy()
        scores = np.nan_to_num(scores, nan=0.0)
        return scores


class PositionErrorKF:
    """
    Kalman Filter for tracking position error magnitude.

    State: x = [error] (scalar position error)
    Measurement: z = |estimated_pos - claimed_pos|

    Used to smooth noisy multilateration estimates and compute NIS for detection.
    """

    def __init__(
        self,
        process_noise: float = 1.0,
        measurement_noise: float = 100.0,
        initial_estimate: float = 0.0,
        initial_covariance: float = 1000.0,
    ):
        self.Q = process_noise  # Process noise variance
        self.R = measurement_noise  # Measurement noise variance
        self.x = initial_estimate  # State estimate
        self.P = initial_covariance  # State covariance

    def update(self, measurement: float) -> tuple[float, float, float]:
        """
        Process a position error measurement.

        Args:
            measurement: Position error magnitude

        Returns:
            Tuple of (NIS, filtered_error, innovation)
        """
        # Prediction (error can change, but we assume slow dynamics)
        x_pred = self.x
        P_pred = self.P + self.Q

        # Innovation
        innovation = measurement - x_pred
        S = P_pred + self.R  # Innovation covariance

        # NIS (detection statistic)
        nis = (innovation ** 2) / S

        # Kalman gain and update
        K = P_pred / S
        self.x = x_pred + K * innovation
        self.P = (1 - K) * P_pred

        return nis, self.x, innovation


@dataclass
class MultilatDetector(Detector):
    """
    Detect spoofing using RSSI-based multilateration with fixed federate receivers.

    Uses exactly 4 benign hosts as federate receivers. For each transmission
    (uniquely identified by serial number + rid_timestamp), collects RSSI from
    federates, jointly estimates position AND TX power via nonlinear least squares,
    and tracks the position error with a Kalman Filter. Returns filtered error as score.

    The key insight is that we solve for (x, y, z, P_tx) simultaneously using the
    path loss model: RSSI_i = P_tx - 10*n*log10(|pos - receiver_i|)

    This avoids assuming the claimed position is correct when estimating TX power.

    Parameters:
        path_loss_exp: Path loss exponent (default 2.0 for free space)
        min_federates: Minimum federates needed for multilateration (default 4)
        kf_process_noise: KF process noise for error tracking
        kf_measurement_noise: KF measurement noise (based on typical error variance)
        use_filtered_error: If True, return filtered error. If False, return NIS.
    """

    path_loss_exp: float = 2.0
    min_federates: int = 4
    kf_process_noise: float = 100.0  # Error can change moderately between measurements
    kf_measurement_noise: float = 250000.0  # ~500m std dev for position error
    use_filtered_error: bool = True  # Return filtered error instead of NIS

    @property
    def name(self) -> str:
        return "Multilateration"

    @property
    def params(self) -> dict[str, Any]:
        return {
            "path_loss_exp": self.path_loss_exp,
            "min_federates": self.min_federates,
            "kf_process_noise": self.kf_process_noise,
            "kf_measurement_noise": self.kf_measurement_noise,
            "use_filtered_error": self.use_filtered_error,
        }

    def score(self, scenario: ScenarioData) -> np.ndarray:
        """
        Compute filtered position error as detection score.

        For each transmission (uniquely identified by serial number + rid_timestamp),
        collects RSSI from federate receivers, jointly estimates position and TX power
        via nonlinear least squares, and tracks error with a per-transmitter Kalman Filter.

        Events without enough federate receivers get score 0.
        """
        n_events = scenario.n_events
        scores = np.zeros(n_events)

        # Get federate host IDs
        federate_ids = set(scenario.federate_host_ids)

        # Each transmitter gets its own KF for error tracking (keyed by serial number)
        kf_per_transmitter: dict[int, PositionErrorKF] = {}

        # Group RX events by (serial_number, rid_timestamp) - this uniquely identifies a transmission
        # Build a dict mapping (sn, rid_ts) -> list of event indices
        from collections import defaultdict
        transmission_events: dict[tuple[int, int], list[int]] = defaultdict(list)
        for i in range(n_events):
            sn = scenario.serial_number[i]
            rid_ts = scenario.rid_timestamp[i]
            transmission_events[(sn, rid_ts)].append(i)

        # Get unique transmissions sorted by rid_timestamp
        unique_transmissions = sorted(transmission_events.keys(), key=lambda x: x[1])

        for sn, rid_ts in unique_transmissions:
            indices = transmission_events[(sn, rid_ts)]

            # Filter to federate receivers only
            federate_indices = [i for i in indices if scenario.host_id[i] in federate_ids]

            if len(federate_indices) < self.min_federates:
                # Not enough federate receivers for this transmission
                continue

            # Collect federate positions and RSSI values
            rx_positions = scenario.rx_pos[federate_indices]
            rssi_values = scenario.rssi[federate_indices]
            claimed_pos = scenario.rid_pos[federate_indices[0]]  # Same for all RX of this TX

            # Jointly estimate position and TX power
            estimated_pos, estimated_tx_power = self._multilaterate_with_tx_power(
                rx_positions, rssi_values, claimed_pos
            )

            if estimated_pos is None:
                continue

            # Compute raw position error
            raw_error = np.linalg.norm(estimated_pos - claimed_pos)

            # Get or create KF for this transmitter
            if sn not in kf_per_transmitter:
                kf_per_transmitter[sn] = PositionErrorKF(
                    process_noise=self.kf_process_noise,
                    measurement_noise=self.kf_measurement_noise,
                )

            # Update KF and get detection score
            nis, filtered_error, innovation = kf_per_transmitter[sn].update(raw_error)
            score = filtered_error if self.use_filtered_error else nis

            # Apply same score to all RX events from this transmission
            for i in indices:
                scores[i] = score

        return scores

    def _multilaterate_with_tx_power(
        self,
        receivers: np.ndarray,
        rssi_values: np.ndarray,
        initial_pos: np.ndarray,
    ) -> tuple[np.ndarray | None, float | None]:
        """
        Jointly estimate transmitter position and TX power using nonlinear least squares.

        Solves for (x, y, z, P_tx) that minimizes the sum of squared residuals:
            r_i = RSSI_i - (P_tx - 10*n*log10(|pos - receiver_i|))

        Args:
            receivers: (N, 3) array of receiver positions
            rssi_values: (N,) array of RSSI measurements (dBm)
            initial_pos: Initial position guess (e.g., claimed position)

        Returns:
            Tuple of (estimated_pos, estimated_tx_power) or (None, None) if failed
        """
        n = len(rssi_values)
        if n < 4:  # Need at least 4 measurements for 4 unknowns
            return None, None

        n_ple = 10 * self.path_loss_exp

        def residuals(params):
            """Compute residuals for least squares optimization."""
            pos = params[:3]
            tx_power = params[3]

            # Distances from estimated position to each receiver
            distances = np.linalg.norm(receivers - pos, axis=1)
            distances = np.maximum(distances, 0.1)  # Avoid log(0)

            # Expected RSSI at each receiver
            expected_rssi = tx_power - n_ple * np.log10(distances)

            # Residuals
            return rssi_values - expected_rssi

        # Initial guess: claimed position + median TX power estimate
        distances_init = np.linalg.norm(receivers - initial_pos, axis=1)
        distances_init = np.maximum(distances_init, 0.1)
        tx_power_init = np.median(rssi_values + n_ple * np.log10(distances_init))

        x0 = np.concatenate([initial_pos, [tx_power_init]])

        # Bounds: position can be anywhere, TX power -50 to 50 dBm (wide range to handle model mismatch)
        bounds = (
            [-np.inf, -np.inf, -np.inf, -50],  # Lower bounds
            [np.inf, np.inf, np.inf, 50],      # Upper bounds
        )

        try:
            result = least_squares(
                residuals,
                x0,
                bounds=bounds,
                method='trf',  # Trust Region Reflective
                max_nfev=100,  # Limit iterations for speed
            )

            if result.success or result.cost < 100:  # Accept if converged or low cost
                estimated_pos = result.x[:3]
                estimated_tx_power = result.x[3]
                return estimated_pos, estimated_tx_power
            else:
                return None, None

        except Exception:
            return None, None
