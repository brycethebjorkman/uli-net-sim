#!/usr/bin/env python3
"""
Generate sweep analysis charts from summary.csv and optional GCS vector exports.

Usage:
    python3 datagen/plot_sweep_charts.py \
        --sweep-root simulations/spoofing_aware_with_planning/sweeps
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import pandas as pd


def _variant_from_name(name: str) -> str:
    return "TrustRID" if "TrustRid" in name else ("SpoofingAware" if "Aware" in name else "Unknown")


def _make_summary_charts(summary_csv: Path, out_dir: Path) -> list[Path]:
    import matplotlib.pyplot as plt

    df = pd.read_csv(summary_csv)
    out_paths: list[Path] = []

    # Derived metric requested for direct safety comparison:
    # total real-position NMAC = benign-benign + benign-spoofer.
    if "nmac_proximity_aware" in df.columns and "nmac_benign_spoofer_aware" in df.columns:
        df["nmac_total_real_aware"] = (
            pd.to_numeric(df["nmac_proximity_aware"], errors="coerce").fillna(0.0)
            + pd.to_numeric(df["nmac_benign_spoofer_aware"], errors="coerce").fillna(0.0)
        )
    if "nmac_proximity_trust_rid" in df.columns and "nmac_benign_spoofer_trust_rid" in df.columns:
        df["nmac_total_real_trust_rid"] = (
            pd.to_numeric(df["nmac_proximity_trust_rid"], errors="coerce").fillna(0.0)
            + pd.to_numeric(df["nmac_benign_spoofer_trust_rid"], errors="coerce").fillna(0.0)
        )

    paired_metrics = [
        (
            "nmac_total_real_aware",
            "nmac_total_real_trust_rid",
            "Total NMACs (real-position)\n= benign-benign + benign-spoofer",
        ),
        ("nmac_proximity_aware", "nmac_proximity_trust_rid", "Benign-Benign NMACs"),
        (
            "nmac_benign_spoofer_aware",
            "nmac_benign_spoofer_trust_rid",
            "Benign-Spoofer NMACs\n(true spoofer position)",
        ),
        (
            "min_benign_spoofer_distance_aware_m",
            "min_benign_spoofer_distance_trust_rid_m",
            "Min distance to true spoofer (m)",
        ),
    ]
    aware_only_metrics = [
        ("nmac_spoofer_unsafe_aware", "SpoofingAware: chance-constraint violations"),
        ("spoofer_containment_rate_aware", "SpoofingAware: spoofer containment percent"),
    ]

    # Boxplots across seeds: 4 paired + 2 SpoofingAware-only.
    fig, axes = plt.subplots(2, 3, figsize=(15, 8))
    axes = axes.ravel()
    idx = 0
    for aware_col, trust_col, title in paired_metrics:
        ax = axes[idx]
        idx += 1
        if aware_col not in df.columns or trust_col not in df.columns:
            ax.axis("off")
            ax.set_title(f"{title} (missing columns)")
            continue
        ax.boxplot(
            [df[aware_col].dropna(), df[trust_col].dropna()],
            labels=["SpoofingAware", "TrustRID"],
        )
        ax.set_title(title)
    for aware_col, title in aware_only_metrics:
        ax = axes[idx]
        idx += 1
        if aware_col not in df.columns:
            ax.axis("off")
            ax.set_title(f"{title} (missing column)")
            continue
        ax.boxplot([df[aware_col].dropna()], labels=["SpoofingAware"])
        ax.set_title(title)
    fig.suptitle("Safety Metrics Across Seeds")
    fig.tight_layout()
    p = out_dir / "summary_boxplots.png"
    fig.savefig(p, dpi=220)
    plt.close(fig)
    out_paths.append(p)

    # Means chart with clearer names and TrustRID/Aware scope.
    mean_specs = [
        (
            "Total NMACs (real-position)",
            "nmac_total_real_aware",
            "nmac_total_real_trust_rid",
        ),
        ("Benign-Benign NMACs", "nmac_proximity_aware", "nmac_proximity_trust_rid"),
        (
            "Benign-Spoofer NMACs",
            "nmac_benign_spoofer_aware",
            "nmac_benign_spoofer_trust_rid",
        ),
        (
            "Min distance to true spoofer (m)",
            "min_benign_spoofer_distance_aware_m",
            "min_benign_spoofer_distance_trust_rid_m",
        ),
        (
            "SpoofingAware: chance-constraint violations",
            "nmac_spoofer_unsafe_aware",
            None,
        ),
        (
            "SpoofingAware: spoofer containment percent",
            "spoofer_containment_rate_aware",
            None,
        ),
    ]
    rows = []
    for label, aware_col, trust_col in mean_specs:
        if aware_col not in df.columns:
            continue
        aware_mean = float(pd.to_numeric(df[aware_col], errors="coerce").mean())
        trust_mean = float(pd.to_numeric(df[trust_col], errors="coerce").mean()) if trust_col and trust_col in df.columns else float("nan")
        rows.append((label, aware_mean, trust_mean))
    if rows:
        labels = [r[0] for r in rows]
        aware_vals = [r[1] for r in rows]
        trust_vals = [r[2] for r in rows]
        x = range(len(labels))
        width = 0.38
        fig, ax = plt.subplots(figsize=(14, 5.5))
        ax.bar([i - width / 2 for i in x], aware_vals, width=width, label="SpoofingAware")
        ax.bar([i + width / 2 for i in x], trust_vals, width=width, label="TrustRID")
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=20, ha="right")
        ax.set_title("Mean Metrics Across Seeds (TrustRID vs SpoofingAware)")
        ax.legend()
        fig.tight_layout()
        p = out_dir / "summary_means.png"
        fig.savefig(p, dpi=220)
        plt.close(fig)
        out_paths.append(p)

        mean_df = pd.DataFrame(rows, columns=["metric", "spoofing_aware_mean", "trust_rid_mean"])
        p_csv = out_dir / "summary_means_table.csv"
        mean_df.to_csv(p_csv, index=False)
        out_paths.append(p_csv)

    return out_paths


def _load_gcs_vector_long(gcs_vectors_dir: Path) -> pd.DataFrame:
    rows: list[dict] = []
    for p in sorted(gcs_vectors_dir.glob("*.csv")):
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        for _, r in df.iterrows():
            # Keep only actual vector rows from CSV-R export.
            if str(r.get("type", "")).strip().lower() != "vector":
                continue
            name = str(r.get("name", ""))
            vectime = str(r.get("vectime", ""))
            vecvalue = str(r.get("vecvalue", ""))
            if not vectime or not vecvalue:
                continue
            if vectime.strip().lower() == "nan" or vecvalue.strip().lower() == "nan":
                continue
            ts = vectime.split()
            vs = vecvalue.split()
            n = min(len(ts), len(vs))
            for i in range(n):
                try:
                    t = float(ts[i])
                    v = float(vs[i])
                    if not math.isfinite(t) or not math.isfinite(v):
                        continue
                    rows.append(
                        {
                            "source_file": p.name,
                            "variant": _variant_from_name(p.name),
                            "name": name,
                            "time": t,
                            "value": v,
                        }
                    )
                except ValueError:
                    continue
    return pd.DataFrame(rows)


def _make_timeseries_charts(long_df: pd.DataFrame, out_dir: Path) -> list[Path]:
    import matplotlib.pyplot as plt

    out_paths: list[Path] = []
    if long_df.empty:
        return out_paths

    long_df.to_csv(out_dir / "gcs_timeseries_long.csv", index=False)
    out_paths.append(out_dir / "gcs_timeseries_long.csv")

    # Median trajectory overlay for min benign-spoofer distance.
    dist_df = long_df[long_df["name"].str.contains("min_benign_spoofer_distance_now_m", na=False)]
    if not dist_df.empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        for variant in ["SpoofingAware", "TrustRID"]:
            g = dist_df[dist_df["variant"] == variant]
            if g.empty:
                continue
            med = g.groupby("time", as_index=False)["value"].median()
            ax.plot(med["time"], med["value"], label=variant)
        nmac_threshold_m = 10.0
        ax.axhline(
            y=nmac_threshold_m,
            color="crimson",
            linestyle="--",
            linewidth=1.2,
            label="NMAC threshold (10 m)",
        )
        ax.set_title("Min Benign-Spoofer Distance Through Time (Median Across Runs)")
        ax.set_xlabel("time (s)")
        ax.set_ylabel("distance (m)")
        ax.legend()
        fig.tight_layout()
        p = out_dir / "timeseries_min_distance_median.png"
        fig.savefig(p, dpi=220)
        plt.close(fig)
        out_paths.append(p)

    # Containment rate trajectory (Aware should dominate here).
    cont_df = long_df[long_df["name"].str.contains("spoofer_containment_rate", na=False)]
    if not cont_df.empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        g = cont_df[cont_df["variant"] == "SpoofingAware"]
        if not g.empty:
            med = g.groupby("time", as_index=False)["value"].median()
            ax.plot(med["time"], med["value"], label="SpoofingAware")
        ax.set_title("SpoofingAware Spoofer Containment Through Time (Median)")
        ax.set_xlabel("time (s)")
        ax.set_ylabel("containment percent")
        if not g.empty:
            ax.legend()
        fig.tight_layout()
        p = out_dir / "timeseries_containment_rate_median.png"
        fig.savefig(p, dpi=220)
        plt.close(fig)
        out_paths.append(p)

    return out_paths


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate sweep charts from summary and GCS vectors.")
    ap.add_argument(
        "--sweep-root",
        type=Path,
        default=Path("simulations/spoofing_aware_with_planning/sweeps"),
        help="Sweep root containing summary.csv and optionally gcs_vectors/",
    )
    ap.add_argument(
        "--summary-csv",
        type=Path,
        default=None,
        help="Override summary CSV path (default: <sweep-root>/summary.csv)",
    )
    ap.add_argument(
        "--gcs-vectors-dir",
        type=Path,
        default=None,
        help="Override GCS vector CSV directory (default: <sweep-root>/gcs_vectors)",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: <sweep-root>/charts)",
    )
    args = ap.parse_args()

    sweep_root = args.sweep_root.resolve()
    summary_csv = (args.summary_csv or (sweep_root / "summary.csv")).resolve()
    gcs_vectors_dir = (args.gcs_vectors_dir or (sweep_root / "gcs_vectors")).resolve()
    out_dir = (args.out_dir or (sweep_root / "charts")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not summary_csv.is_file():
        raise FileNotFoundError(f"summary CSV not found: {summary_csv}")

    written = []
    written.extend(_make_summary_charts(summary_csv, out_dir))

    if gcs_vectors_dir.is_dir():
        long_df = _load_gcs_vector_long(gcs_vectors_dir)
        written.extend(_make_timeseries_charts(long_df, out_dir))

    print("Wrote files:")
    for p in written:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
