#!/usr/bin/env python3
"""
Create interactive 3D trajectory visualizations for batched sweep outputs.

For each scenario directory under a generated/ tree, this script loads paired
Aware/TrustRID parquet files and writes one HTML file with side-by-side 3D
scenes.

Example:
    python3 datagen/plot_batch_3d_trajectories.py \
        --generated-dir simulations/spoofing_aware_with_planning/sweeps/paper_suite_30seeds/generated
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable

import pandas as pd

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError as exc:  # pragma: no cover - runtime guidance
    raise SystemExit(
        "plotly is required for 3D trajectory visualization. "
        "Install with: pip install plotly"
    ) from exc


PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#17becf", "#aec7e8", "#ffbb78", "#98df8a", "#ff9896",
]


def _load_tx_points(parquet_path: Path, sample_every: int = 1) -> pd.DataFrame:
    df = pd.read_parquet(parquet_path)
    need = {"event_type", "time", "host_id", "pos_x", "pos_y", "pos_z", "serial_number"}
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"{parquet_path} missing required columns: {missing}")

    tx = df[df["event_type"] == "TX"].copy()
    tx = tx.sort_values(["serial_number", "time"])
    if sample_every > 1:
        tx = tx.groupby("serial_number", group_keys=False).apply(
            lambda g: g.iloc[::sample_every]
        )
    return tx


def _iter_variant_parquets(scenario_dir: Path) -> tuple[Path | None, Path | None]:
    aware = None
    trust = None
    for p in sorted(scenario_dir.glob("*.parquet")):
        name = p.name
        if "_Aware" in name:
            aware = p
        elif "_TrustRid" in name:
            trust = p
    return aware, trust


def _add_traces(
    fig: go.Figure,
    tx: pd.DataFrame,
    col_idx: int,
    showlegend: bool,
    title_suffix: str,
) -> None:
    if tx.empty:
        return

    serials = sorted(tx["serial_number"].dropna().astype(int).unique().tolist())
    color_map = {s: PALETTE[i % len(PALETTE)] for i, s in enumerate(serials)}
    max_serial = max(serials) if serials else None

    for s in serials:
        g = tx[tx["serial_number"].astype(int) == s].sort_values("time")
        if g.empty:
            continue
        is_spoofer = (max_serial is not None and s == max_serial)
        fig.add_trace(
            go.Scatter3d(
                x=g["pos_x"],
                y=g["pos_y"],
                z=g["pos_z"],
                mode="lines",
                line=dict(
                    color="#cc0000" if is_spoofer else color_map[s],
                    width=7 if is_spoofer else 4,
                    dash="dash" if is_spoofer else "solid",
                ),
                name=f"UAV {s} ({'spoofer' if is_spoofer else 'benign'}) {title_suffix}",
                legendgroup=f"{s}",
                showlegend=showlegend,
            ),
            row=1,
            col=col_idx,
        )


def make_scenario_figure(
    scenario_tag: str,
    aware_parquet: Path | None,
    trust_parquet: Path | None,
    sample_every: int,
) -> go.Figure:
    fig = make_subplots(
        rows=1,
        cols=2,
        specs=[[{"type": "scene"}, {"type": "scene"}]],
        subplot_titles=("SpoofingAware", "TrustRID"),
        horizontal_spacing=0.02,
    )

    x_all: list[float] = []
    y_all: list[float] = []
    z_all: list[float] = []

    if aware_parquet is not None:
        aware_tx = _load_tx_points(aware_parquet, sample_every=sample_every)
        _add_traces(fig, aware_tx, col_idx=1, showlegend=True, title_suffix="Aware")
        x_all.extend(aware_tx["pos_x"].tolist())
        y_all.extend(aware_tx["pos_y"].tolist())
        z_all.extend(aware_tx["pos_z"].tolist())

    if trust_parquet is not None:
        trust_tx = _load_tx_points(trust_parquet, sample_every=sample_every)
        _add_traces(fig, trust_tx, col_idx=2, showlegend=False, title_suffix="TrustRID")
        x_all.extend(trust_tx["pos_x"].tolist())
        y_all.extend(trust_tx["pos_y"].tolist())
        z_all.extend(trust_tx["pos_z"].tolist())

    if x_all:
        xr = [min(x_all), max(x_all)]
        yr = [min(y_all), max(y_all)]
        zr = [min(z_all), max(z_all)]
    else:
        xr, yr, zr = [0, 1], [0, 1], [0, 1]

    scene_common = dict(
        xaxis=dict(title="X [m]", range=xr, backgroundcolor="rgb(240,240,240)"),
        yaxis=dict(title="Y [m]", range=yr, backgroundcolor="rgb(240,240,240)"),
        zaxis=dict(title="Altitude [m]", range=zr, backgroundcolor="rgb(240,240,240)"),
        aspectmode="data",
    )
    fig.update_layout(
        title=f"3D TX Trajectories: {scenario_tag}",
        scene=scene_common,
        scene2=scene_common,
        legend=dict(orientation="v"),
        margin=dict(l=10, r=10, t=60, b=10),
        width=1500,
        height=700,
    )
    return fig


def iter_scenario_dirs(generated_dir: Path) -> Iterable[Path]:
    for d in sorted(generated_dir.iterdir()):
        if d.is_dir() and (d / "omnetpp.ini").is_file():
            yield d


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate per-scenario 3D trajectory HTMLs for batch sweeps.")
    ap.add_argument(
        "--generated-dir",
        type=Path,
        required=True,
        help="Path to generated scenario root (contains scenario dirs with parquet files).",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory for HTML files (default: <generated-dir>/../trajectory_3d).",
    )
    ap.add_argument(
        "--sample-every",
        type=int,
        default=1,
        help="Downsample TX points per serial (1=all, 2=every other point, ...).",
    )
    ap.add_argument(
        "--max-scenarios",
        type=int,
        default=0,
        help="Limit number of scenario files generated (0 = all).",
    )
    args = ap.parse_args()

    generated_dir = args.generated_dir.resolve()
    if not generated_dir.is_dir():
        raise FileNotFoundError(f"generated dir not found: {generated_dir}")
    if args.sample_every < 1:
        raise ValueError("--sample-every must be >= 1")

    out_dir = (args.out_dir or (generated_dir.parent / "trajectory_3d")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    n_written = 0
    for scen_dir in iter_scenario_dirs(generated_dir):
        aware, trust = _iter_variant_parquets(scen_dir)
        if aware is None and trust is None:
            continue
        fig = make_scenario_figure(scen_dir.name, aware, trust, sample_every=args.sample_every)
        out_html = out_dir / f"{scen_dir.name}_3d.html"
        fig.write_html(str(out_html), include_plotlyjs="cdn")
        n_written += 1
        print(f"Wrote {out_html}")
        if args.max_scenarios > 0 and n_written >= args.max_scenarios:
            break

    print(f"Done. Wrote {n_written} trajectory visualization file(s) to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
