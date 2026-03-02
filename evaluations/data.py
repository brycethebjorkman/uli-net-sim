"""
Data loading utilities for RX event classification.

Loads CSV files from train/test directories and provides RX events
with ground truth labels for detector evaluation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator
import numpy as np
import pandas as pd


@dataclass
class ScenarioData:
    """RX events from a single scenario CSV."""

    scenario_id: str  # CSV filename without extension

    # RX event data (only RX events, not TX)
    time: np.ndarray  # Event timestamps
    host_id: np.ndarray  # Receiving host ID
    host_type: np.ndarray  # Host type ('benign' or 'spoofer')
    serial_number: np.ndarray  # Transmitting host serial number
    rid_timestamp: np.ndarray  # RID message timestamp (ms) - uniquely identifies transmission with serial_number
    is_spoofed: np.ndarray  # Ground truth: 1 if this RX is from spoofer

    # Receiver position (actual)
    rx_pos: np.ndarray  # Shape (N, 3) - receiver x, y, z

    # Transmitter position (actual) - joined from TX events
    tx_pos: np.ndarray  # Shape (N, 3) - transmitter actual x, y, z

    # Claimed position from RID message
    rid_pos: np.ndarray  # Shape (N, 3) - claimed x, y, z

    # Signal measurements
    rssi: np.ndarray  # Received signal strength (dBm)

    # KF state (may have NaN if not computed)
    kf_nis: np.ndarray  # Normalized Innovation Squared

    # Federate host IDs (first 4 benign hosts, for multilateration)
    federate_host_ids: np.ndarray  # Array of host IDs designated as federates

    @property
    def n_events(self) -> int:
        return len(self.time)

    @property
    def n_spoofed(self) -> int:
        return int(np.sum(self.is_spoofed))

    @property
    def n_benign(self) -> int:
        return self.n_events - self.n_spoofed


def load_scenario(csv_path: Path | str, num_federates: int = 4) -> ScenarioData:
    """
    Load a single scenario CSV file.

    Args:
        csv_path: Path to CSV file
        num_federates: Number of benign hosts to designate as federates (default 4)

    Returns:
        ScenarioData with RX events only, including transmitter actual positions
    """
    csv_path = Path(csv_path)
    df = pd.read_csv(csv_path)

    # Identify federate host IDs (first N benign hosts)
    # Use full dataframe to find benign hosts, not just RX events
    benign_hosts = df[df["host_type"] == "benign"]["host_id"].unique()
    federate_host_ids = np.sort(benign_hosts)[:num_federates]

    # Extract TX events to get transmitter actual positions
    # TX events have pos_x/y/z as the transmitter's actual position
    tx_df = df[df["event_type"] == "TX"][
        ["serial_number", "rid_timestamp", "pos_x", "pos_y", "pos_z"]
    ].copy()
    tx_df = tx_df.rename(columns={
        "pos_x": "tx_pos_x",
        "pos_y": "tx_pos_y",
        "pos_z": "tx_pos_z",
    })
    # Ensure rid_timestamp is int for proper join
    tx_df["rid_timestamp"] = tx_df["rid_timestamp"].astype(int)

    # Filter to RX events only
    rx_df = df[df["event_type"] == "RX"].copy()
    rx_df["rid_timestamp"] = rx_df["rid_timestamp"].astype(int)

    # Join RX events with TX events to get transmitter actual position
    # Each RX event is matched to its corresponding TX by (serial_number, rid_timestamp)
    rx_df = rx_df.merge(
        tx_df,
        on=["serial_number", "rid_timestamp"],
        how="left"
    )

    # Extract scenario ID from filename
    scenario_id = csv_path.stem

    return ScenarioData(
        scenario_id=scenario_id,
        time=rx_df["time"].values,
        host_id=rx_df["host_id"].values,
        host_type=rx_df["host_type"].values,
        serial_number=rx_df["serial_number"].values,
        rid_timestamp=rx_df["rid_timestamp"].values,
        is_spoofed=rx_df["is_spoofed"].values.astype(bool),
        rx_pos=rx_df[["pos_x", "pos_y", "pos_z"]].values,
        tx_pos=rx_df[["tx_pos_x", "tx_pos_y", "tx_pos_z"]].values,
        rid_pos=rx_df[["rid_pos_x", "rid_pos_y", "rid_pos_z"]].values,
        rssi=rx_df["rssi"].values,
        kf_nis=rx_df["kf_nis"].values if "kf_nis" in rx_df.columns else np.full(len(rx_df), np.nan),
        federate_host_ids=federate_host_ids,
    )


def load_dataset(
    data_dir: Path | str,
    limit: int | None = None,
) -> list[ScenarioData]:
    """
    Load all scenario CSVs from a directory.

    Args:
        data_dir: Directory containing CSV files (e.g., datasets/scitech26/train)
        limit: Maximum number of scenarios to load (for testing)

    Returns:
        List of ScenarioData objects
    """
    data_dir = Path(data_dir)
    csv_files = sorted(data_dir.glob("*.csv"))

    if limit is not None:
        csv_files = csv_files[:limit]

    scenarios = []
    for csv_path in csv_files:
        scenarios.append(load_scenario(csv_path))

    return scenarios


def iter_dataset(
    data_dir: Path | str,
    limit: int | None = None,
) -> Iterator[ScenarioData]:
    """
    Iterate over scenario CSVs from a directory (memory-efficient).

    Args:
        data_dir: Directory containing CSV files
        limit: Maximum number of scenarios to yield

    Yields:
        ScenarioData objects one at a time
    """
    data_dir = Path(data_dir)
    csv_files = sorted(data_dir.glob("*.csv"))

    if limit is not None:
        csv_files = csv_files[:limit]

    for csv_path in csv_files:
        yield load_scenario(csv_path)


