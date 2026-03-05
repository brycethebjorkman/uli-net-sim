"""
Spoofing detection methods.

Each detector takes RX event data and produces a detection score per event.
Higher scores indicate higher likelihood of spoofing.

Detectors:
1. KalmanFilterDetector - Uses KF NIS (Normalized Innovation Squared) from single receiver
2. MultilatDetector - Uses RSSI multilateration from multiple receivers
3. MLPDetector - MLP trained on per-transmission RSSI + receiver-to-claimed-TX features
"""

import pickle
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
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


# Free space path loss constant for 2.4 GHz (matches KalmanFilterDetectMgmt.cc)
# Derived from: 32.44 + 20*log10(2400 MHz) - 60 = 40.04
FSPL_CONSTANT_DB = 40.04


@dataclass
class MultilatDetector(Detector):
    """
    Detect spoofing using RSSI-based multilateration with fixed federate receivers.

    Uses exactly 4 benign hosts as federate receivers. For each transmission
    (uniquely identified by serial number + rid_timestamp), collects RSSI from
    federates, jointly estimates position AND TX power via nonlinear least squares,
    and tracks the position error with a Kalman Filter. Returns filtered error as score.

    Uses the same 2.4 GHz free space path loss model as the KF detector:
        RSSI = P_tx - 20*log10(d) - 40.04

    This avoids assuming the claimed position is correct when estimating TX power.

    Detection pipeline:
        1. NLLS estimates transmitter position (x, y, z) and TX power
        2. Compute position error = |estimated_pos - claimed_pos|
        3. Feed error to per-transmitter Kalman filter for smoothing
        4. Return filtered error as detection score (large error = likely spoofing)

    Parameters:
        min_federates: Minimum federates needed for multilateration (default 4)
        kf_process_noise: KF process noise for error tracking
        kf_measurement_noise: KF measurement noise (based on typical error variance)
    """

    min_federates: int = 4
    kf_process_noise: float = 100.0  # Error can change moderately between measurements
    kf_measurement_noise: float = 250000.0  # ~500m std dev for position error

    @property
    def name(self) -> str:
        return "Multilateration"

    @property
    def params(self) -> dict[str, Any]:
        return {
            "min_federates": self.min_federates,
            "kf_process_noise": self.kf_process_noise,
            "kf_measurement_noise": self.kf_measurement_noise,
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

            # Update KF and get detection score (always use filtered error)
            nis, filtered_error, innovation = kf_per_transmitter[sn].update(raw_error)

            # Apply same score to all RX events from this transmission
            for i in indices:
                scores[i] = filtered_error

        return scores

    def _multilaterate_with_tx_power(
        self,
        receivers: np.ndarray,
        rssi_values: np.ndarray,
        initial_pos: np.ndarray,
    ) -> tuple[np.ndarray | None, float | None]:
        """
        Jointly estimate transmitter position and TX power using nonlinear least squares.

        Uses the 2.4 GHz free space path loss model (matching KF detector):
            RSSI = P_tx - 20*log10(d) - 40.04

        Solves for (x, y, z, P_tx) that minimizes the sum of squared residuals.

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

        def residuals(params):
            """Compute residuals for least squares optimization."""
            pos = params[:3]
            tx_power = params[3]

            # Distances from estimated position to each receiver
            distances = np.linalg.norm(receivers - pos, axis=1)
            distances = np.maximum(distances, 0.1)  # Avoid log(0)

            # Expected RSSI using 2.4 GHz FSPL model: RSSI = P_tx - 20*log10(d) - 40.04
            expected_rssi = tx_power - 20.0 * np.log10(distances) - FSPL_CONSTANT_DB

            # Residuals
            return rssi_values - expected_rssi

        # Initial guess: claimed position + median TX power estimate
        distances_init = np.linalg.norm(receivers - initial_pos, axis=1)
        distances_init = np.maximum(distances_init, 0.1)
        # P_tx = RSSI + 20*log10(d) + 40.04
        tx_power_init = np.median(rssi_values + 20.0 * np.log10(distances_init) + FSPL_CONSTANT_DB)

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


def _make_mlp(input_dim: int, hidden_dims: list[int]):
    """
    Build an MLP nn.Module with architecture matching the original SciTech26 paper.
    """
    import torch.nn as nn

    layers = []
    prev = input_dim
    for h in hidden_dims:
        layers.extend([nn.Linear(prev, h), nn.ReLU()])
        prev = h
    layers.append(nn.Linear(prev, 1))
    seq = nn.Sequential(*layers)

    class _MLP(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = seq

        def forward(self, x):
            return self.net(x)

    return _MLP()


class MLPDetector:
    """
    MLP-based spoofing detector.

    Trains a multilayer perceptron on per-transmission features derived from up to 4
    benign receivers: the receiver-to-claimed-TX position vectors (x, y, z per axis)
    and RSSI for each receiver.  The MLP learns to detect when RSSI values are
    inconsistent with the claimed transmitter position.

    Output granularity: one score per transmission (same as MultilatDetector).

    Requires PyTorch and scikit-learn.
    """

    # Feature columns in the wide per-transmission DataFrame
    FEATURE_COLS = [
        'rx_to_claimed_x_0', 'rx_to_claimed_y_0', 'rx_to_claimed_z_0',
        'rx_to_claimed_x_1', 'rx_to_claimed_y_1', 'rx_to_claimed_z_1',
        'rx_to_claimed_x_2', 'rx_to_claimed_y_2', 'rx_to_claimed_z_2',
        'rx_to_claimed_x_3', 'rx_to_claimed_y_3', 'rx_to_claimed_z_3',
        'rssi_0', 'rssi_1', 'rssi_2', 'rssi_3',
    ]
    HIDDEN_DIMS = [128, 64]
    LR = 1e-3
    BATCH_SIZE = 32
    EPOCHS = 10

    def __init__(self):
        self.model = None
        self.scaler = None
        self._feature_means: pd.Series | None = None  # For NaN-filling test data

    # ------------------------------------------------------------------
    # Preprocessing
    # ------------------------------------------------------------------

    def _preprocess(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Preprocess a raw scenario DataFrame into per-transmission wide format.

        Keeps only RX events from benign receivers, computes per-axis
        receiver-to-claimed-TX position vectors, takes first 4 benign receivers
        per (serial_number, rid_timestamp), then pivots to wide format.

        Returns DataFrame with FEATURE_COLS + serial_number + rid_timestamp +
        is_spoofed.  Transmissions with no benign receivers are dropped.
        """
        rx = df[(df['event_type'] == 'RX') & (df['host_type'] == 'benign')].copy()
        rx['rid_timestamp'] = rx['rid_timestamp'].astype(int)

        if len(rx) == 0:
            return pd.DataFrame()

        # Per-axis vectors from receiver position to claimed TX position
        rx['rx_to_claimed_x'] = rx['pos_x'] - rx['rid_pos_x']
        rx['rx_to_claimed_y'] = rx['pos_y'] - rx['rid_pos_y']
        rx['rx_to_claimed_z'] = rx['pos_z'] - rx['rid_pos_z']

        # Select first 4 benign receivers per transmission (deterministic by host_id)
        rx = rx.sort_values(['serial_number', 'rid_timestamp', 'host_id'])
        rx['host_rank'] = rx.groupby(['serial_number', 'rid_timestamp']).cumcount()
        rx = rx[rx['host_rank'] < 4].copy()

        value_cols = ['rx_to_claimed_x', 'rx_to_claimed_y', 'rx_to_claimed_z', 'rssi', 'is_spoofed']
        wide = rx.pivot_table(
            index=['serial_number', 'rid_timestamp'],
            columns='host_rank',
            values=value_cols,
            aggfunc='first',
        )
        wide.columns = [f"{col}_{rank}" for col, rank in wide.columns]
        wide = wide.reset_index()

        # Collapse per-receiver is_spoofed flags into a single column
        spoof_cols = [f'is_spoofed_{i}' for i in range(4) if f'is_spoofed_{i}' in wide.columns]
        if spoof_cols:
            wide['is_spoofed'] = wide[spoof_cols].any(axis=1).astype(int)
            wide.drop(columns=spoof_cols, inplace=True)

        return wide

    def _compute_transmission_distances(
        self, df: pd.DataFrame, wide: pd.DataFrame
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Compute per-transmission spoofing_dist and distance_discrepancy.

        spoofing_dist       = ||tx_actual - rid_claimed||
        distance_discrepancy = ||tx_actual - rx|| - ||rid_claimed - rx||  (first benign RX)
        """
        tx_df = df[df['event_type'] == 'TX'][[
            'serial_number', 'rid_timestamp',
            'pos_x', 'pos_y', 'pos_z',
            'rid_pos_x', 'rid_pos_y', 'rid_pos_z',
        ]].copy()
        tx_df['rid_timestamp'] = tx_df['rid_timestamp'].astype(int)

        tx_actual = tx_df[['pos_x', 'pos_y', 'pos_z']].values
        rid_claimed = tx_df[['rid_pos_x', 'rid_pos_y', 'rid_pos_z']].values
        tx_df['spoofing_dist'] = np.linalg.norm(tx_actual - rid_claimed, axis=1)

        # First benign RX per transmission for distance_discrepancy
        rx_df = df[(df['event_type'] == 'RX') & (df['host_type'] == 'benign')].copy()
        rx_df['rid_timestamp'] = rx_df['rid_timestamp'].astype(int)
        rx_first = rx_df.drop_duplicates(subset=['serial_number', 'rid_timestamp']).copy()

        rx_first = rx_first.merge(
            tx_df[['serial_number', 'rid_timestamp', 'pos_x', 'pos_y', 'pos_z']].rename(
                columns={'pos_x': 'tx_x', 'pos_y': 'tx_y', 'pos_z': 'tx_z'}
            ),
            on=['serial_number', 'rid_timestamp'],
            how='left',
        )
        actual_dist = np.linalg.norm(
            rx_first[['tx_x', 'tx_y', 'tx_z']].values
            - rx_first[['pos_x', 'pos_y', 'pos_z']].values,
            axis=1,
        )
        claimed_dist = np.linalg.norm(
            rx_first[['rid_pos_x', 'rid_pos_y', 'rid_pos_z']].values
            - rx_first[['pos_x', 'pos_y', 'pos_z']].values,
            axis=1,
        )
        rx_first['distance_discrepancy'] = actual_dist - claimed_dist

        merged = wide[['serial_number', 'rid_timestamp']].merge(
            tx_df[['serial_number', 'rid_timestamp', 'spoofing_dist']],
            on=['serial_number', 'rid_timestamp'],
            how='left',
        ).merge(
            rx_first[['serial_number', 'rid_timestamp', 'distance_discrepancy']],
            on=['serial_number', 'rid_timestamp'],
            how='left',
        )
        return merged['spoofing_dist'].values, merged['distance_discrepancy'].values

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------

    def train(self, train_csv_paths: list, seed: int = 42) -> None:
        """
        Train MLP on all training CSV files.

        Args:
            train_csv_paths: Iterable of Path/str objects pointing to training CSVs.
            seed: Random seed for reproducibility (default 42).
        """
        import torch
        import torch.nn as nn
        import torch.optim as optim
        from torch.utils.data import DataLoader, TensorDataset
        from sklearn.preprocessing import StandardScaler

        torch.manual_seed(seed)
        np.random.seed(seed)

        train_csv_paths = list(train_csv_paths)
        print(f"Preprocessing {len(train_csv_paths)} training scenarios for MLP...")

        dfs = []
        for i, csv_path in enumerate(sorted(train_csv_paths)):
            wide = self._preprocess(pd.read_csv(csv_path))
            if len(wide) > 0:
                dfs.append(wide)
            if (i + 1) % 100 == 0:
                print(f"  Preprocessed {i + 1}/{len(train_csv_paths)} scenarios...")

        if not dfs:
            raise ValueError("No training data found after preprocessing")

        train_df = pd.concat(dfs, ignore_index=True)

        X = train_df[self.FEATURE_COLS].copy()
        self._feature_means = X.mean()
        X = X.fillna(self._feature_means)
        y = train_df['is_spoofed'].values.astype(float)

        n_pos = int(y.sum())
        n_neg = int(len(y) - n_pos)
        print(f"  Training on {len(train_df)} transmissions "
              f"({n_pos} spoofed, {n_neg} benign)")

        self.scaler = StandardScaler()
        X_np = self.scaler.fit_transform(X.values)

        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.model = _make_mlp(len(self.FEATURE_COLS), self.HIDDEN_DIMS).to(device)

        pos_weight = torch.tensor(n_neg / n_pos, dtype=torch.float32).to(device)
        criterion = nn.BCEWithLogitsLoss(pos_weight=pos_weight)
        optimizer = optim.Adam(self.model.parameters(), lr=self.LR)

        X_tensor = torch.FloatTensor(X_np).to(device)
        y_tensor = torch.FloatTensor(y).unsqueeze(1).to(device)
        loader = DataLoader(
            TensorDataset(X_tensor, y_tensor),
            batch_size=self.BATCH_SIZE,
            shuffle=True,
        )

        print(f"  Training MLP ({device})...")
        for epoch in range(self.EPOCHS):
            self.model.train()
            total_loss = 0.0
            for xb, yb in loader:
                optimizer.zero_grad()
                loss = criterion(self.model(xb), yb)
                loss.backward()
                optimizer.step()
                total_loss += loss.item()
            print(f"  Epoch {epoch + 1}/{self.EPOCHS} - Loss: {total_loss / len(loader):.4f}")

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def score_file(self, csv_path, scenario_id: str) -> pd.DataFrame:
        """
        Score all transmissions in a scenario CSV file.

        Args:
            csv_path: Path to scenario CSV file (or pre-loaded DataFrame).
            scenario_id: Scenario identifier (typically the CSV stem).

        Returns:
            DataFrame with columns:
                scenario_id, serial_number, rid_timestamp,
                mlp_score, is_spoofed, spoofing_dist, distance_discrepancy
        """
        import torch

        empty = pd.DataFrame(columns=[
            'scenario_id', 'serial_number', 'rid_timestamp',
            'mlp_score', 'is_spoofed', 'spoofing_dist', 'distance_discrepancy',
        ])

        df = pd.read_csv(csv_path) if not isinstance(csv_path, pd.DataFrame) else csv_path
        wide = self._preprocess(df)

        if len(wide) == 0:
            return empty

        X = wide[self.FEATURE_COLS].copy().fillna(self._feature_means)
        X_np = self.scaler.transform(X.values)

        device = next(self.model.parameters()).device
        self.model.eval()
        with torch.no_grad():
            proba = torch.sigmoid(
                self.model(torch.FloatTensor(X_np).to(device))
            ).cpu().numpy().flatten()

        spoofing_dists, dist_discrepancies = self._compute_transmission_distances(df, wide)

        return pd.DataFrame({
            'scenario_id': scenario_id,
            'serial_number': wide['serial_number'].astype(int).values,
            'rid_timestamp': wide['rid_timestamp'].astype(int).values,
            'mlp_score': proba,
            'is_spoofed': wide['is_spoofed'].values,
            'spoofing_dist': spoofing_dists,
            'distance_discrepancy': dist_discrepancies,
        })

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, weights_path, scaler_path) -> None:
        """Save model weights (.pth) and scaler + feature means (.pkl)."""
        import torch
        torch.save(self.model.state_dict(), weights_path)
        with open(scaler_path, 'wb') as f:
            pickle.dump({'scaler': self.scaler, 'feature_means': self._feature_means}, f)

    def load(self, weights_path, scaler_path) -> None:
        """Load model weights and scaler from disk."""
        import torch
        with open(scaler_path, 'rb') as f:
            data = pickle.load(f)
        self.scaler = data['scaler']
        self._feature_means = data['feature_means']
        self.model = _make_mlp(len(self.FEATURE_COLS), self.HIDDEN_DIMS)
        self.model.load_state_dict(torch.load(weights_path, map_location='cpu'))
        self.model.eval()
