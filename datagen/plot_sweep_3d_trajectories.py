#!/usr/bin/env python3
"""
Generate per-scenario 3D trajectory overlays (across seeds) using Matplotlib.

For each scenario group under a batch generated/ directory (e.g. hub_8x1), this
script overlays TX trajectories from all runs/seeds and writes one figure with
side-by-side panels:
  - SpoofingAware
  - TrustRID

Usage:
    python3 datagen/plot_sweep_3d_trajectories.py \
        --generated-dir simulations/spoofing_aware_with_planning/batches/0001/generated \
        --out-dir simulations/spoofing_aware_with_planning/batches/0001/charts
"""

from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

try:
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover - runtime guidance
    raise SystemExit(
        "matplotlib is required for 3D trajectory overlays. "
        "Install with: pip install matplotlib"
    ) from exc


_SEED_SUFFIX_RE = re.compile(r"_s\d+$")
PALETTE = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
]


def _scenario_group_from_dirname(dirname: str) -> str:
    return _SEED_SUFFIX_RE.sub("", dirname)


def _variant_from_name(name: str) -> str | None:
    if "_Aware" in name:
        return "SpoofingAware"
    if "_TrustRid" in name:
        return "TrustRID"
    return None


def _load_tx_points(parquet_path: Path, sample_every: int = 3) -> pd.DataFrame:
    df = pd.read_parquet(parquet_path)
    need = {"event_type", "time", "serial_number", "pos_x", "pos_y", "pos_z"}
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"{parquet_path} missing required columns: {missing}")
    tx = df[df["event_type"] == "TX"].copy()
    if tx.empty:
        return tx
    tx = tx.sort_values(["serial_number", "time"])
    if sample_every > 1:
        tx = tx.groupby("serial_number", group_keys=False).apply(
            lambda g: g.iloc[::sample_every]
        )
    return tx


def _collect_parquets(generated_dir: Path) -> dict[str, dict[str, list[Path]]]:
    groups: dict[str, dict[str, list[Path]]] = defaultdict(
        lambda: {"SpoofingAware": [], "TrustRID": []}
    )
    for scen_dir in sorted(generated_dir.iterdir()):
        if not scen_dir.is_dir() or not (scen_dir / "omnetpp.ini").is_file():
            continue
        group = _scenario_group_from_dirname(scen_dir.name)
        for p in sorted(scen_dir.glob("*.parquet")):
            variant = _variant_from_name(p.name)
            if variant is None:
                continue
            groups[group][variant].append(p)
    return groups


def _set_axes_equal(ax, xr, yr, zr) -> None:
    x_mid = 0.5 * (xr[0] + xr[1])
    y_mid = 0.5 * (yr[0] + yr[1])
    z_mid = 0.5 * (zr[0] + zr[1])
    max_half = 0.5 * max(xr[1] - xr[0], yr[1] - yr[0], zr[1] - zr[0], 1.0)
    ax.set_xlim(x_mid - max_half, x_mid + max_half)
    ax.set_ylim(y_mid - max_half, y_mid + max_half)
    ax.set_zlim(z_mid - max_half, z_mid + max_half)
    try:
        ax.set_box_aspect((1, 1, 1))
    except Exception:
        pass


def _plot_group(group: str, by_variant: dict[str, list[Path]], out_dir: Path, sample_every: int) -> Path | None:
    variants = ["SpoofingAware", "TrustRID"]
    if all(len(by_variant.get(v, [])) == 0 for v in variants):
        return None

    fig = plt.figure(figsize=(14.5, 6.8))
    axs = [
        fig.add_subplot(1, 2, 1, projection="3d"),
        fig.add_subplot(1, 2, 2, projection="3d"),
    ]
    fig.suptitle(f"3D Trajectory Overlay Across Seeds: {group}", fontsize=14)

    x_all: list[float] = []
    y_all: list[float] = []
    z_all: list[float] = []

    for ax, variant in zip(axs, variants):
        parquets = by_variant.get(variant, [])
        shown_serial_labels: set[int] = set()
        n_runs = 0
        for pq in parquets:
            try:
                tx = _load_tx_points(pq, sample_every=sample_every)
            except Exception:
                continue
            if tx.empty:
                continue
            n_runs += 1
            x_all.extend(tx["pos_x"].tolist())
            y_all.extend(tx["pos_y"].tolist())
            z_all.extend(tx["pos_z"].tolist())
            serials = sorted(tx["serial_number"].dropna().astype(int).unique().tolist())
            max_serial = max(serials) if serials else None
            color_map = {s: PALETTE[i % len(PALETTE)] for i, s in enumerate(serials)}
            for s in serials:
                g = tx[tx["serial_number"].astype(int) == s].sort_values("time")
                if g.empty:
                    continue
                is_spoofer = max_serial is not None and s == max_serial
                color = "#cc0000" if is_spoofer else color_map[s]
                label = None
                if s not in shown_serial_labels:
                    label = f"UAV {s}" + (" (spoofer)" if is_spoofer else "")
                    shown_serial_labels.add(s)
                ax.plot(
                    g["pos_x"].to_numpy(),
                    g["pos_y"].to_numpy(),
                    g["pos_z"].to_numpy(),
                    color=color,
                    alpha=0.22,
                    linewidth=1.0 if is_spoofer else 0.8,
                    label=label,
                )

        ax.set_title(f"{variant} (runs={n_runs})")
        ax.set_xlabel("X [m]")
        ax.set_ylabel("Y [m]")
        ax.set_zlabel("Altitude [m]")
        ax.grid(True, alpha=0.25)
        handles, labels = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc="upper left", fontsize=8)

    if x_all and y_all and z_all:
        xr = (min(x_all), max(x_all))
        yr = (min(y_all), max(y_all))
        zr = (min(z_all), max(z_all))
        for ax in axs:
            _set_axes_equal(ax, xr, yr, zr)

    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.96])
    out = out_dir / f"trajectory_overlay_3d_{group}.pdf"
    fig.savefig(out, dpi=240)
    plt.close(fig)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate per-scenario 3D trajectory overlays across seeds.")
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
        help="Output directory for PNG charts (default: <generated-dir>/../charts).",
    )
    ap.add_argument(
        "--sample-every",
        type=int,
        default=3,
        help="Downsample TX points per serial to reduce overplotting (1=all).",
    )
    args = ap.parse_args()

    generated_dir = args.generated_dir.resolve()
    if not generated_dir.is_dir():
        raise FileNotFoundError(f"generated dir not found: {generated_dir}")
    if args.sample_every < 1:
        raise ValueError("--sample-every must be >= 1")

    out_dir = (args.out_dir or (generated_dir.parent / "charts")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    groups = _collect_parquets(generated_dir)
    written = 0
    for group in sorted(groups.keys()):
        p = _plot_group(group, groups[group], out_dir=out_dir, sample_every=args.sample_every)
        if p is not None:
            print(f"Wrote {p}")
            written += 1

    print(f"Done. Wrote {written} 3D overlay chart(s) to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
