"""
Load and prepare scenario parquet data for visualization.

Handles TX/RX/GCS event types, host classification, score auto-detection,
and per-host trajectory building.  Detector-agnostic: works with any
scenario that produces the standard event parquet format.
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Score descriptor
# ---------------------------------------------------------------------------

@dataclass
class ScoreColumn:
    """A detected score column available for visualization."""
    column: str         # DataFrame column name (e.g. 'kf_max_nis', 'gcs_cusum_stat')
    label: str          # Human-readable label for plots
    event_type: str     # Which event type carries this score ('TX', 'RX', 'GCS')
    higher_is_worse: bool = True  # Score direction (for colorscale orientation)
    threshold: float | None = None  # Detection threshold for diverging colorscale


# ---------------------------------------------------------------------------
# Scenario data container
# ---------------------------------------------------------------------------

@dataclass
class ScenarioData:
    """Parsed scenario data ready for visualization."""
    scenario_id: str
    df: pd.DataFrame

    tx: pd.DataFrame = field(repr=False)
    rx: pd.DataFrame = field(repr=False)
    gcs: pd.DataFrame = field(repr=False)

    host_ids: list[int] = field(default_factory=list)
    spoofer_ids: set[int] = field(default_factory=set)
    benign_ids: list[int] = field(default_factory=list)

    # Per-host TX events sorted by time (for trajectory interpolation)
    host_tx: dict[int, pd.DataFrame] = field(default_factory=dict, repr=False)

    # Spoofed TX events with scores merged in
    spoof_tx: pd.DataFrame = field(default=None, repr=False)

    # Auto-detected score columns
    scores: list[ScoreColumn] = field(default_factory=list)

    # Primary score column for colorscale (first available score, or None)
    primary_score: ScoreColumn | None = None

    t_min: float = 0.0
    t_max: float = 0.0


# ---------------------------------------------------------------------------
# Score auto-detection
# ---------------------------------------------------------------------------

# Known score patterns: (column_name, label, event_type, higher_is_worse)
# Checked in priority order — first match becomes primary score for colorscale.
_KNOWN_SCORES = [
    # GCS log scores (from on_gcs_reports)
    ('gcs_cusum_stat',          'CUSUM',                'GCS', True),
    ('gcs_standardized_error',  'Standardized Error',   'GCS', True),
    ('gcs_mlat_score',          'MLAT Score',           'GCS', True),
    ('gcs_kf_max_nis',          'KF NIS (GCS)',         'GCS', True),
    ('gcs_combined_alert',      'Combined Alert',       'GCS', True),
    # Per-RX KF NIS (from C++ KalmanFilterDetectMgmt, aggregated to per-TX)
    ('kf_max_nis',              'KF NIS',               'TX',  True),
    # External score files (merged onto TX by old pipeline)
    ('mlat_score',              'MLAT Score',           'TX',  True),
]


def _detect_threshold(gcs: pd.DataFrame, score_col: str) -> float | None:
    """Estimate detection threshold from gcs_spoofing_declared transition.

    Returns the midpoint between the last pre-detection and first post-detection
    score values, or None if no detection occurred.
    """
    if 'gcs_spoofing_declared' not in gcs.columns or score_col not in gcs.columns:
        return None
    gcs_sorted = gcs.sort_values('time')
    declared = gcs_sorted[gcs_sorted['gcs_spoofing_declared'] == 1]
    if declared.empty:
        return None
    det_time = declared.iloc[0]['time']
    det_score = float(declared.iloc[0][score_col])
    before = gcs_sorted[
        (gcs_sorted['time'] < det_time) & (gcs_sorted['gcs_spoofing_declared'] != 1)
    ]
    if before.empty:
        return det_score
    prev_score = float(before.iloc[-1][score_col])
    return (prev_score + det_score) / 2


def _detect_scores(df: pd.DataFrame, gcs: pd.DataFrame) -> list[ScoreColumn]:
    """Auto-detect available score columns from the data."""
    scores = []
    for col, label, event_type, higher_is_worse in _KNOWN_SCORES:
        source = gcs if event_type == 'GCS' else df
        if col in source.columns and source[col].notna().any():
            threshold = _detect_threshold(gcs, col) if event_type == 'GCS' else None
            scores.append(ScoreColumn(col, label, event_type, higher_is_worse, threshold))

    # Discover unknown gcs_* columns not in the known list
    known_cols = {col for col, _, _, _ in _KNOWN_SCORES}
    for col in sorted(gcs.columns):
        if col.startswith('gcs_') and col not in known_cols and gcs[col].notna().any():
            # Skip non-score metadata columns
            if col in ('gcs_packet_id', 'gcs_obs_count', 'gcs_spoofing_declared',
                       'gcs_planned_x', 'gcs_planned_y', 'gcs_planned_z',
                       'gcs_gp_pred_mean', 'gcs_gp_pred_var',
                       'gcs_max_variance_reduction'):
                continue
            label = col.replace('gcs_', '').replace('_', ' ').title()
            threshold = _detect_threshold(gcs, col)
            scores.append(ScoreColumn(col, label, 'GCS', True, threshold))

    return scores


# ---------------------------------------------------------------------------
# KF NIS aggregation (per-RX → per-TX)
# ---------------------------------------------------------------------------

def _aggregate_kf_nis(tx: pd.DataFrame, rx: pd.DataFrame) -> pd.DataFrame:
    """Aggregate per-RX kf_nis to per-TX kf_max_nis via max across receivers."""
    if 'kf_nis' not in rx.columns or not rx['kf_nis'].notna().any():
        return tx
    kf_per_tx = (
        rx.dropna(subset=['kf_nis'])
        .groupby(['serial_number', 'rid_timestamp'])['kf_nis']
        .max()
        .reset_index()
        .rename(columns={'kf_nis': 'kf_max_nis'})
    )
    return tx.merge(kf_per_tx, on=['serial_number', 'rid_timestamp'], how='left')


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_scenario(parquet_path: str | Path) -> ScenarioData:
    """Load a scenario parquet and prepare data for visualization.

    Works with any scenario type — auto-detects available scores from
    whatever columns are present (KF NIS, MLAT, GCS CUSUM, etc.).
    """
    parquet_path = Path(parquet_path)
    df = pd.read_parquet(parquet_path)
    scenario_id = parquet_path.stem

    # Split by event type
    tx = df[df['event_type'] == 'TX'].copy()
    rx = df[df['event_type'] == 'RX'].copy()
    gcs = df[df['event_type'] == 'GCS'].copy() if 'event_type' in df.columns else pd.DataFrame()

    # Identify hosts
    host_ids = sorted(df['host_id'].dropna().unique().astype(int))
    spoofer_ids = set()
    if 'host_type' in df.columns:
        spoofer_ids = set(df[df['host_type'] == 'spoofer']['host_id'].dropna().unique().astype(int))
    benign_ids = [h for h in host_ids if h not in spoofer_ids]

    # Aggregate per-RX KF NIS onto TX events
    tx = _aggregate_kf_nis(tx, rx)

    # Build per-host TX timeseries
    host_tx = {}
    for hid in host_ids:
        host_tx[hid] = tx[tx['host_id'] == hid].sort_values('time')

    # Spoofed TX events
    spoof_tx = tx[tx['is_spoofed'] == 1].copy() if 'is_spoofed' in tx.columns else pd.DataFrame()

    # Merge GCS scores onto spoof_tx via packet_id (for hover text on spoofed markers)
    if not gcs.empty and not spoof_tx.empty and 'packet_id' in gcs.columns:
        gcs_score_cols = [c for c in gcs.columns if c.startswith('gcs_')]
        if gcs_score_cols:
            # Drop pre-existing gcs_* columns from spoof_tx (all NaN for TX events)
            # to prevent pandas merge creating _x/_y suffixed duplicates
            existing = [c for c in spoof_tx.columns if c.startswith('gcs_')]
            if existing:
                spoof_tx = spoof_tx.drop(columns=existing)
            gcs_for_merge = gcs[['packet_id'] + gcs_score_cols].copy()
            spoof_tx = spoof_tx.merge(gcs_for_merge, on='packet_id', how='left')

    # Auto-detect scores
    scores = _detect_scores(spoof_tx, gcs)
    primary_score = scores[0] if scores else None

    t_min = tx['time'].min() if len(tx) > 0 else 0.0
    t_max = tx['time'].max() if len(tx) > 0 else 0.0

    return ScenarioData(
        scenario_id=scenario_id,
        df=df, tx=tx, rx=rx, gcs=gcs,
        host_ids=host_ids, spoofer_ids=spoofer_ids, benign_ids=benign_ids,
        host_tx=host_tx, spoof_tx=spoof_tx,
        scores=scores, primary_score=primary_score,
        t_min=t_min, t_max=t_max,
    )


def interp_pos(ht: pd.DataFrame, t: float) -> tuple[float, float, float] | None:
    """Interpolate host position at time t from TX events."""
    times = ht['time'].values
    if len(times) == 0 or t < times[0]:
        return None
    if t >= times[-1]:
        return (ht['pos_x'].iloc[-1], ht['pos_y'].iloc[-1], ht['pos_z'].iloc[-1])
    idx = np.searchsorted(times, t, side='right') - 1
    idx = max(0, min(idx, len(times) - 2))
    t0, t1 = times[idx], times[idx + 1]
    a = (t - t0) / (t1 - t0) if (t1 - t0) > 1e-9 else 0.0
    x = ht['pos_x'].iloc[idx] + a * (ht['pos_x'].iloc[idx + 1] - ht['pos_x'].iloc[idx])
    y = ht['pos_y'].iloc[idx] + a * (ht['pos_y'].iloc[idx + 1] - ht['pos_y'].iloc[idx])
    z = ht['pos_z'].iloc[idx] + a * (ht['pos_z'].iloc[idx + 1] - ht['pos_z'].iloc[idx])
    return (x, y, z)
