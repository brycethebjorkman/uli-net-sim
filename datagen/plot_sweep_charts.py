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
import re
from pathlib import Path

import numpy as np
import pandas as pd


def _variant_from_name(name: str) -> str:
    return "TrustRID" if "TrustRid" in name else ("SpoofingAware" if "Aware" in name else "Unknown")


_SEED_SUFFIX_RE = re.compile(r"_s\d+$")


def _scenario_group_from_tag(tag: str) -> str:
    return _SEED_SUFFIX_RE.sub("", str(tag))


def _bootstrap_ci_median(values: np.ndarray, n_boot: int = 1000, alpha: float = 0.05) -> tuple[float, float]:
    if values.size == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(42)
    meds = np.empty(n_boot, dtype=float)
    n = values.size
    for i in range(n_boot):
        sample = rng.choice(values, size=n, replace=True)
        meds[i] = float(np.median(sample))
    return float(np.quantile(meds, alpha / 2.0)), float(np.quantile(meds, 1.0 - alpha / 2.0))


def _write_distribution_table(df: pd.DataFrame, out_dir: Path) -> Path:
    metric_specs = [
        ("total_nmac_real", "Total NMACs (real-position)", "nmac_total_real_aware", "nmac_total_real_trust_rid"),
        ("benign_benign_nmac", "Benign-Benign NMACs", "nmac_proximity_aware", "nmac_proximity_trust_rid"),
        ("benign_spoofer_nmac", "Benign-Spoofer NMACs", "nmac_benign_spoofer_aware", "nmac_benign_spoofer_trust_rid"),
        ("min_distance_true_spoofer_m", "Min distance to true spoofer (m)", "min_benign_spoofer_distance_aware_m", "min_benign_spoofer_distance_trust_rid_m"),
        ("gcs_reports_mean_ms", "GCS report callback mean time (ms)", "gcs_reports_mean_ms_aware", "gcs_reports_mean_ms_trust_rid"),
        ("gcs_tick_mean_ms", "GCS tick callback mean time (ms)", "gcs_tick_mean_ms_aware", "gcs_tick_mean_ms_trust_rid"),
        ("gcs_compute_total_s", "Total GCS compute time (s)", "gcs_compute_total_s_aware", "gcs_compute_total_s_trust_rid"),
        ("chance_constraint_violations", "SpoofingAware: chance-constraint violations", "nmac_spoofer_unsafe_aware", None),
        ("spoofer_containment_percent", "SpoofingAware: spoofer containment percent", "spoofer_containment_rate_aware", None),
        ("detection_latency_s", "SpoofingAware: detection latency (s)", "detection_latency_s_aware", None),
        ("localization_mae_m", "SpoofingAware: localization MAE (m)", "localization_mae_m_aware", None),
        ("localization_rmse_m", "SpoofingAware: localization RMSE (m)", "localization_rmse_m_aware", None),
    ]
    if "tag" not in df.columns:
        df = df.copy()
        df["tag"] = "all"
    dd = df.copy()
    dd["scenario"] = dd["tag"].apply(_scenario_group_from_tag)
    rows: list[dict] = []
    for scen, g in dd.groupby("scenario"):
        for key, label, aware_col, trust_col in metric_specs:
            for variant, col in [("SpoofingAware", aware_col), ("TrustRID", trust_col)]:
                if col is None or col not in g.columns:
                    continue
                vals = pd.to_numeric(g[col], errors="coerce").dropna().to_numpy(dtype=float)
                if vals.size == 0:
                    continue
                q1 = float(np.quantile(vals, 0.25))
                med = float(np.quantile(vals, 0.5))
                q3 = float(np.quantile(vals, 0.75))
                ci_lo, ci_hi = _bootstrap_ci_median(vals)
                rows.append(
                    {
                        "scenario": scen,
                        "variant": variant,
                        "metric_key": key,
                        "metric_label": label,
                        "n": int(vals.size),
                        "median": med,
                        "q1": q1,
                        "q3": q3,
                        "iqr": float(q3 - q1),
                        "median_ci95_lo": ci_lo,
                        "median_ci95_hi": ci_hi,
                    }
                )
    out = out_dir / "summary_distribution_table.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    return out


def _make_summary_charts(summary_csv: Path, out_dir: Path) -> list[Path]:
    import matplotlib.pyplot as plt

    try:
        df = pd.read_csv(summary_csv)
    except pd.errors.EmptyDataError:
        note = out_dir / "plot_note.txt"
        note.write_text(
            "summary.csv is empty (0 rows). No summary charts generated.\n"
            "Check simulation/parquet conversion logs for failures.\n"
        )
        return [note]
    if df.empty:
        note = out_dir / "plot_note.txt"
        note.write_text(
            "summary.csv has headers but no rows. No summary charts generated.\n"
            "Check simulation/parquet conversion logs for failures.\n"
        )
        return [note]
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

    # Median chart with IQR bars.
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
        aware_vals = pd.to_numeric(df[aware_col], errors="coerce").dropna().to_numpy(dtype=float)
        if aware_vals.size == 0:
            continue
        aware_med = float(np.quantile(aware_vals, 0.5))
        aware_q1 = float(np.quantile(aware_vals, 0.25))
        aware_q3 = float(np.quantile(aware_vals, 0.75))
        trust_med = float("nan")
        trust_q1 = float("nan")
        trust_q3 = float("nan")
        if trust_col and trust_col in df.columns:
            trust_vals = pd.to_numeric(df[trust_col], errors="coerce").dropna().to_numpy(dtype=float)
            if trust_vals.size > 0:
                trust_med = float(np.quantile(trust_vals, 0.5))
                trust_q1 = float(np.quantile(trust_vals, 0.25))
                trust_q3 = float(np.quantile(trust_vals, 0.75))
        rows.append((label, aware_med, aware_q1, aware_q3, trust_med, trust_q1, trust_q3))
    if rows:
        labels = [r[0] for r in rows]
        aware_vals = [r[1] for r in rows]
        aware_err_lo = [r[1] - r[2] for r in rows]
        aware_err_hi = [r[3] - r[1] for r in rows]
        trust_vals = [r[4] for r in rows]
        trust_err_lo = [r[4] - r[5] if np.isfinite(r[4]) and np.isfinite(r[5]) else 0.0 for r in rows]
        trust_err_hi = [r[6] - r[4] if np.isfinite(r[4]) and np.isfinite(r[6]) else 0.0 for r in rows]
        x = range(len(labels))
        width = 0.38
        fig, ax = plt.subplots(figsize=(14, 5.5))
        ax.bar([i - width / 2 for i in x], aware_vals, width=width, label="SpoofingAware", yerr=[aware_err_lo, aware_err_hi], capsize=3)
        ax.bar([i + width / 2 for i in x], trust_vals, width=width, label="TrustRID", yerr=[trust_err_lo, trust_err_hi], capsize=3)
        ax.set_xticks(list(x))
        ax.set_xticklabels(labels, rotation=20, ha="right")
        ax.set_title("Median Metrics Across Seeds with IQR (TrustRID vs SpoofingAware)")
        ax.legend()
        fig.tight_layout()
        p = out_dir / "summary_means.png"
        fig.savefig(p, dpi=220)
        plt.close(fig)
        out_paths.append(p)

        mean_df = pd.DataFrame(
            rows,
            columns=[
                "metric",
                "spoofing_aware_median",
                "spoofing_aware_q1",
                "spoofing_aware_q3",
                "trust_rid_median",
                "trust_rid_q1",
                "trust_rid_q3",
            ],
        )
        p_csv = out_dir / "summary_means_table.csv"
        mean_df.to_csv(p_csv, index=False)
        out_paths.append(p_csv)

    out_paths.append(_write_distribution_table(df, out_dir))

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
        nmac_threshold_m = 50.0
        ax.axhline(
            y=nmac_threshold_m,
            color="crimson",
            linestyle="--",
            linewidth=1.2,
            label="NMAC threshold (50 m)",
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
