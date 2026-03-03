"""
Scoring functions for spoofing detection evaluation.

Runs detectors on test scenarios and produces per-sample score CSVs
(kf_scores.csv, mlat_scores.csv) for downstream analysis.
"""

from pathlib import Path
import json

import numpy as np
import pandas as pd

from .data import load_scenario, ScenarioData
from .detectors import MultilatDetector, MLPDetector
from .optimize import train_thresholds


def compute_sample_distances(scenario: ScenarioData) -> tuple[np.ndarray, np.ndarray]:
    """
    Compute distance metrics for each RX event in a scenario.

    Returns:
        Tuple of (spoofing_dist, distance_discrepancy) arrays, same length as scenario.n_events.
        - spoofing_dist: ||tx_pos - rid_pos|| (distance between actual and claimed TX position)
        - distance_discrepancy: ||tx_pos - rx_pos|| - ||rid_pos - rx_pos||
          (difference between actual and claimed distance to receiver)

        Values are NaN for events where tx_pos is not available.
    """
    # Compute spoofing distance: ||tx_pos - rid_pos||
    spoofing_dist = np.linalg.norm(scenario.tx_pos - scenario.rid_pos, axis=1)

    # Compute distance discrepancy:
    # actual_dist = ||tx_pos - rx_pos|| (true distance from transmitter to receiver)
    # claimed_dist = ||rid_pos - rx_pos|| (distance receiver would calculate from RID)
    # discrepancy = actual_dist - claimed_dist
    actual_dist = np.linalg.norm(scenario.tx_pos - scenario.rx_pos, axis=1)
    claimed_dist = np.linalg.norm(scenario.rid_pos - scenario.rx_pos, axis=1)
    distance_discrepancy = actual_dist - claimed_dist

    return spoofing_dist, distance_discrepancy


def collect_kf_scores_per_rx_event(
    scenario: ScenarioData,
    federate_ids: set[int],
) -> dict[str, list]:
    """
    Collect KF scores at the per-RX-event level using only federate receivers.

    Each federate's reception is treated as an independent detection trial.
    No aggregation across receivers.

    Args:
        scenario: ScenarioData with RX events
        federate_ids: Set of host IDs designated as federates

    Returns:
        Dict with keys: host_id, serial_number, rid_timestamp, kf_score,
        is_spoofed, spoofing_dist, distance_discrepancy
    """
    result = {
        'host_id': [],
        'serial_number': [],
        'rid_timestamp': [],
        'kf_score': [],
        'is_spoofed': [],
        'spoofing_dist': [],
        'distance_discrepancy': [],
    }

    # Pre-compute distances for all events
    all_spoofing_dist, all_dist_discrepancy = compute_sample_distances(scenario)

    for i in range(scenario.n_events):
        # Only use federate receivers
        if scenario.host_id[i] not in federate_ids:
            continue

        nis = scenario.kf_nis[i]
        if not np.isnan(nis):
            result['host_id'].append(int(scenario.host_id[i]))
            result['serial_number'].append(int(scenario.serial_number[i]))
            result['rid_timestamp'].append(int(scenario.rid_timestamp[i]))
            result['kf_score'].append(nis)
            result['is_spoofed'].append(int(scenario.is_spoofed[i]))
            result['spoofing_dist'].append(all_spoofing_dist[i])
            result['distance_discrepancy'].append(all_dist_discrepancy[i])

    return result


def train_detectors(
    train_dir: Path,
    output_dir: Path,
    detectors: set[str] | None = None,
    train_limit: int | None = None,
) -> None:
    """
    Train detectors on training data and save artifacts to output_dir.

    KF and MLAT thresholds are trained together (single pass over training data).
    MLP is trained independently.

    Args:
        train_dir: Directory containing training CSV files
        output_dir: Where to write thresholds.json, mlp_weights.pth, mlp_scaler.pkl
        detectors: Detector names to train: any subset of {'kf', 'mlat', 'mlp'}.
                   Defaults to all three.
        train_limit: Limit number of training scenarios
    """
    if detectors is None:
        detectors = {'kf', 'mlat', 'mlp'}

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    train_csvs = sorted(Path(train_dir).glob("*.csv"))
    if train_limit:
        train_csvs = train_csvs[:train_limit]
    n_train = len(train_csvs)

    print(f"Training on {n_train} scenarios from {train_dir}")
    print(f"Detectors: {sorted(detectors)}")

    # KF + MLAT thresholds (always trained together in a single pass)
    if 'kf' in detectors or 'mlat' in detectors:
        kf_threshold, mlat_threshold = train_thresholds(
            train_dir, train_limit=train_limit
        )
        thresholds_data = {
            'kf_threshold': float(kf_threshold),
            'mlat_threshold': float(mlat_threshold),
            'train_dir': str(train_dir),
            'n_train_scenarios': n_train,
        }
        thresholds_path = output_dir / "thresholds.json"
        with open(thresholds_path, 'w') as f:
            json.dump(thresholds_data, f, indent=2)
        print(f"\nThresholds saved to {thresholds_path}")
        print(f"  KF threshold:   {kf_threshold}")
        print(f"  MLAT threshold: {mlat_threshold}")

    # MLP
    if 'mlp' in detectors:
        mlp_detector = MLPDetector()
        mlp_weights_path = output_dir / "mlp_weights.pth"
        mlp_scaler_path = output_dir / "mlp_scaler.pkl"
        mlp_detector.train(train_csvs)
        mlp_detector.save(mlp_weights_path, mlp_scaler_path)
        print(f"\nMLP model saved to {mlp_weights_path}")


def score_test_set(
    test_dir: Path,
    output_dir: Path,
    train_dir: Path | None = None,
    test_limit: int | None = None,
    train_limit: int | None = None,
    kf_threshold: float | None = None,
    mlat_threshold: float | None = None,
    detectors: set[str] | None = None,
) -> tuple[float | None, float | None]:
    """
    Run detectors on test set, write per-sample score CSVs.

    If train_dir is given (and thresholds not provided), trains thresholds
    first and writes thresholds.json.  Also trains and runs MLPDetector,
    writing mlp_scores.csv.  If mlp_weights.pth and mlp_scaler.pkl already
    exist in output_dir the saved model is loaded instead of retraining.

    Args:
        test_dir: Directory containing test CSV files
        output_dir: Where to write kf_scores.csv, mlat_scores.csv,
                    mlp_scores.csv, thresholds.json
        train_dir: Training data directory (optional, for threshold optimization)
        test_limit: Limit number of test scenarios
        train_limit: Limit number of training scenarios
        kf_threshold: Pre-computed KF threshold (skips training for KF)
        mlat_threshold: Pre-computed MLAT threshold (skips training for MLAT)
        detectors: Detectors to run: any subset of {'kf', 'mlat', 'mlp'}.
                   Defaults to all three.

    Returns:
        Tuple of (kf_threshold, mlat_threshold); values are None when the
        corresponding detector was not scored.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if detectors is None:
        detectors = {'kf', 'mlat', 'mlp'}

    # Train thresholds if needed (KF and MLAT only)
    if 'kf' in detectors or 'mlat' in detectors:
        n_train_scenarios = 0
        if kf_threshold is not None and mlat_threshold is not None:
            print(f"Using provided thresholds: KF={kf_threshold}, MLAT={mlat_threshold}")
        elif train_dir is not None:
            kf_threshold, mlat_threshold = train_thresholds(
                train_dir, train_limit=train_limit
            )
            n_train_scenarios = len(sorted(Path(train_dir).glob("*.csv")))
            if train_limit:
                n_train_scenarios = min(n_train_scenarios, train_limit)
        else:
            raise ValueError(
                "Either --train-dir or both --kf-threshold and --mlat-threshold "
                "required when scoring kf or mlat"
            )

        # Write thresholds to JSON
        thresholds_data = {
            'kf_threshold': float(kf_threshold),
            'mlat_threshold': float(mlat_threshold),
        }
        if train_dir is not None:
            thresholds_data['train_dir'] = str(train_dir)
            thresholds_data['n_train_scenarios'] = n_train_scenarios
        thresholds_path = output_dir / "thresholds.json"
        with open(thresholds_path, 'w') as f:
            json.dump(thresholds_data, f, indent=2)
        print(f"\nThresholds saved to {thresholds_path}")

    # Initialize MLAT detector
    mlat_detector = MultilatDetector() if 'mlat' in detectors else None

    # Initialize and train (or load) MLP detector
    if 'mlp' in detectors:
        mlp_detector = MLPDetector()
        mlp_weights_path = output_dir / "mlp_weights.pth"
        mlp_scaler_path = output_dir / "mlp_scaler.pkl"

        if mlp_weights_path.exists() and mlp_scaler_path.exists():
            print(f"\nLoading saved MLP model from {mlp_weights_path} ...")
            mlp_detector.load(mlp_weights_path, mlp_scaler_path)
        elif train_dir is not None:
            train_csvs = sorted(Path(train_dir).glob("*.csv"))
            if train_limit:
                train_csvs = train_csvs[:train_limit]
            mlp_detector.train(train_csvs)
            mlp_detector.save(mlp_weights_path, mlp_scaler_path)
            print(f"\n  MLP model saved to {mlp_weights_path}")
        else:
            print("\nWarning: no train_dir and no saved MLP model — skipping MLP scoring")
            mlp_detector = None
    else:
        mlp_detector = None

    # Collect scores into DataFrames
    kf_rows = []
    mlat_rows = []
    mlp_frames = []

    print(f"\nScoring test scenarios from {test_dir}...")

    csv_files = sorted(Path(test_dir).glob("*.csv"))
    if test_limit:
        csv_files = csv_files[:test_limit]

    n_processed = 0
    for csv_path in csv_files:
        scenario_id = csv_path.stem
        scenario = load_scenario(csv_path)
        federate_ids = set(scenario.federate_host_ids)

        # KF: Collect per-RX-event scores from federates
        if 'kf' in detectors:
            kf_data = collect_kf_scores_per_rx_event(scenario, federate_ids)
            for j in range(len(kf_data['kf_score'])):
                kf_rows.append({
                    'scenario_id': scenario_id,
                    'host_id': kf_data['host_id'][j],
                    'serial_number': kf_data['serial_number'][j],
                    'rid_timestamp': kf_data['rid_timestamp'][j],
                    'kf_score': kf_data['kf_score'][j],
                    'is_spoofed': kf_data['is_spoofed'][j],
                    'spoofing_dist': kf_data['spoofing_dist'][j],
                    'distance_discrepancy': kf_data['distance_discrepancy'][j],
                })

        # MLAT: Collect per-transmission scores
        if 'mlat' in detectors:
            all_spoofing_dist, all_dist_discrepancy = compute_sample_distances(scenario)
            mlat_scores_array = mlat_detector.score(scenario)

            # Group MLAT scores by transmission (take first occurrence)
            mlat_transmission_data = {}
            for i in range(scenario.n_events):
                if mlat_scores_array[i] > 0:
                    key = (scenario.serial_number[i], scenario.rid_timestamp[i])
                    if key not in mlat_transmission_data:
                        mlat_transmission_data[key] = {
                            'serial_number': int(scenario.serial_number[i]),
                            'rid_timestamp': int(scenario.rid_timestamp[i]),
                            'score': mlat_scores_array[i],
                            'label': int(scenario.is_spoofed[i]),
                            'spoofing_dist': all_spoofing_dist[i],
                            'dist_discrepancy': all_dist_discrepancy[i],
                        }

            for data in mlat_transmission_data.values():
                mlat_rows.append({
                    'scenario_id': scenario_id,
                    'serial_number': data['serial_number'],
                    'rid_timestamp': data['rid_timestamp'],
                    'mlat_score': data['score'],
                    'is_spoofed': data['label'],
                    'spoofing_dist': data['spoofing_dist'],
                    'distance_discrepancy': data['dist_discrepancy'],
                })

        # MLP: per-transmission scores
        if mlp_detector is not None:
            mlp_result = mlp_detector.score_file(csv_path, scenario_id)
            if len(mlp_result) > 0:
                mlp_frames.append(mlp_result)

        n_processed += 1
        if n_processed % 100 == 0:
            print(f"  Processed {n_processed} scenarios...")

    print(f"  Total scenarios processed: {n_processed}")

    # Write CSVs
    if 'kf' in detectors:
        kf_columns = ['scenario_id', 'host_id', 'serial_number', 'rid_timestamp',
                       'kf_score', 'is_spoofed', 'spoofing_dist', 'distance_discrepancy']
        kf_df = pd.DataFrame(kf_rows, columns=kf_columns)
        kf_path = output_dir / "kf_scores.csv"
        kf_df.to_csv(kf_path, index=False)
        print(f"\n  KF: {len(kf_df)} RX events ({kf_df['is_spoofed'].sum()} spoofed)")
        print(f"  Written to {kf_path}")

    if 'mlat' in detectors:
        mlat_columns = ['scenario_id', 'serial_number', 'rid_timestamp',
                         'mlat_score', 'is_spoofed', 'spoofing_dist', 'distance_discrepancy']
        mlat_df = pd.DataFrame(mlat_rows, columns=mlat_columns)
        mlat_path = output_dir / "mlat_scores.csv"
        mlat_df.to_csv(mlat_path, index=False)
        print(f"  MLAT: {len(mlat_df)} transmissions ({mlat_df['is_spoofed'].sum()} spoofed)")
        print(f"  Written to {mlat_path}")

    if mlp_frames:
        mlp_columns = ['scenario_id', 'serial_number', 'rid_timestamp',
                       'mlp_score', 'is_spoofed', 'spoofing_dist', 'distance_discrepancy']
        mlp_df = pd.concat(mlp_frames, ignore_index=True)[mlp_columns]
        mlp_path = output_dir / "mlp_scores.csv"
        mlp_df.to_csv(mlp_path, index=False)
        print(f"  MLP:  {len(mlp_df)} transmissions ({mlp_df['is_spoofed'].sum()} spoofed)")
        print(f"  Written to {mlp_path}")

    return kf_threshold, mlat_threshold
