#!/usr/bin/env python3
"""
Generate batch analysis charts from summary.csv and optional GCS vector exports.

Usage:
    python3 datagen/spoofting_aware_trajectory_planning_datagen/plot_batch.py \
        --batch-root simulations/spoofing_aware_with_planning/batches
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

NMAC_THRESHOLD_M = 50.0
CHI2_3DOF_95_LO = 0.21579528262389785
CHI2_3DOF_95_HI = 9.348403604496148
VARIANT_ORDER = ["SpoofingAware", "SpoofingAwareInstantDetect", "TrustRID"]
VARIANT_COLORS = {
    "SpoofingAware": "#4c78a8",
    "SpoofingAwareInstantDetect": "#54a24b",
    "TrustRID": "#f58518",
}
VARIANT_LINESTYLES = {
    "SpoofingAware": "-",
    "SpoofingAwareInstantDetect": "-.",
    "TrustRID": "--",
}


def _apply_paper_style(plt) -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 140,
            "savefig.dpi": 260,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "xtick.labelsize": 9.5,
            "ytick.labelsize": 9.5,
            "legend.fontsize": 9,
            "axes.grid": True,
            "grid.alpha": 0.22,
            "grid.linestyle": "-",
            "axes.spines.top": False,
            "axes.spines.right": False,
            "lines.linewidth": 1.8,
        }
    )


def _variant_from_name(name: str) -> str:
    if "TrustRid" in name:
        return "TrustRID"
    if "AwareInstantDetect" in name:
        return "SpoofingAwareInstantDetect"
    if "Aware" in name:
        return "SpoofingAware"
    return "Unknown"


_SEED_SUFFIX_RE = re.compile(r"_s\d+$")


def _scenario_group_from_tag(tag: str) -> str:
    return _SEED_SUFFIX_RE.sub("", str(tag))


def _scenario_group_from_source_file(name: str) -> str:
    # e.g. "hub_8x1_s00000-Scenario_Hub_8x1_s00000_Aware-#0-gcs.csv"
    prefix = str(name).split("-", 1)[0]
    return _SEED_SUFFIX_RE.sub("", prefix)


def _safe_std(vals: np.ndarray) -> float:
    vals = np.asarray(vals, dtype=float)
    if vals.size <= 1:
        return 0.0
    return float(np.std(vals, ddof=1))


def _write_distribution_table(df: pd.DataFrame, out_dir: Path) -> Path:
    metric_specs = [
        ("total_nmac_real", "Total NMACs (real-position)", "nmac_total_real_aware", "nmac_total_real_aware_instant_detect", "nmac_total_real_trust_rid"),
        ("benign_benign_nmac", "Benign-Benign NMACs", "nmac_proximity_aware", "nmac_proximity_aware_instant_detect", "nmac_proximity_trust_rid"),
        ("benign_spoofer_nmac", "Benign-Spoofer NMACs", "nmac_benign_spoofer_aware", "nmac_benign_spoofer_aware_instant_detect", "nmac_benign_spoofer_trust_rid"),
        ("min_distance_true_spoofer_m", "Min distance to true spoofer (m)", "min_benign_spoofer_distance_aware_m", "min_benign_spoofer_distance_aware_instant_detect_m", "min_benign_spoofer_distance_trust_rid_m"),
        ("gcs_reports_mean_ms", "GCS report callback mean time (ms)", "gcs_reports_mean_ms_aware", "gcs_reports_mean_ms_aware_instant_detect", "gcs_reports_mean_ms_trust_rid"),
        ("gcs_tick_mean_ms", "GCS tick callback mean time (ms)", "gcs_tick_mean_ms_aware", "gcs_tick_mean_ms_aware_instant_detect", "gcs_tick_mean_ms_trust_rid"),
        ("gcs_compute_total_s", "Total GCS compute time (s)", "gcs_compute_total_s_aware", "gcs_compute_total_s_aware_instant_detect", "gcs_compute_total_s_trust_rid"),
        ("chance_constraint_violations", "SpoofingAware: chance-constraint violations", "nmac_spoofer_unsafe_aware", "nmac_spoofer_unsafe_aware_instant_detect", "nmac_spoofer_unsafe_trust_rid"),
        ("spoofer_containment_percent", "SpoofingAware: spoofer containment percent", "spoofer_containment_rate_aware", "spoofer_containment_rate_aware_instant_detect", "spoofer_containment_rate_trust_rid"),
        ("detection_latency_s", "SpoofingAware: detection latency (s)", "detection_latency_s_aware", "detection_latency_s_aware_instant_detect", None),
        (
            "detection_reports_total",
            "SpoofingAware: detection reports processed",
            "detection_reports_total_aware",
            "detection_reports_total_aware_instant_detect",
            None,
        ),
        (
            "detection_mlat_attempted",
            "SpoofingAware: detection callbacks with MLAT attempted",
            "detection_mlat_attempted_aware",
            "detection_mlat_attempted_aware_instant_detect",
            None,
        ),
        (
            "detection_mlat_skipped_insufficient_receivers",
            "SpoofingAware: detection callbacks skipped (receivers < 4)",
            "detection_mlat_skipped_insufficient_receivers_aware",
            "detection_mlat_skipped_insufficient_receivers_aware_instant_detect",
            None,
        ),
        (
            "detection_mlat_skip_fraction",
            "SpoofingAware: skipped MLAT fraction during detection",
            "detection_mlat_skipped_insufficient_receivers_fraction_aware",
            "detection_mlat_skipped_insufficient_receivers_fraction_aware_instant_detect",
            None,
        ),
        (
            "localization_mlat_raw_rmse_m",
            "SpoofingAware: raw RSSI/NLLS localization RMSE (m)",
            "localization_mlat_raw_rmse_m_aware",
            "localization_mlat_raw_rmse_m_aware_instant_detect",
            None,
        ),
        (
            "localization_mlat_raw_mae_m",
            "SpoofingAware: raw RSSI/NLLS localization MAE (m)",
            "localization_mlat_raw_mae_m_aware",
            "localization_mlat_raw_mae_m_aware_instant_detect",
            None,
        ),
        ("localization_mae_m", "SpoofingAware: localization MAE (m)", "localization_mae_m_aware", "localization_mae_m_aware_instant_detect", None),
        ("localization_rmse_m", "SpoofingAware: localization RMSE (m)", "localization_rmse_m_aware", "localization_rmse_m_aware_instant_detect", None),
    ]
    if "tag" not in df.columns:
        df = df.copy()
        df["tag"] = "all"
    dd = df.copy()
    dd["scenario"] = dd["tag"].apply(_scenario_group_from_tag)
    rows: list[dict] = []
    for scen, g in dd.groupby("scenario"):
        for key, label, aware_col, instant_col, trust_col in metric_specs:
            for variant, col in [
                ("SpoofingAware", aware_col),
                ("SpoofingAwareInstantDetect", instant_col),
                ("TrustRID", trust_col),
            ]:
                if col is None or col not in g.columns:
                    continue
                vals = pd.to_numeric(g[col], errors="coerce").dropna().to_numpy(dtype=float)
                if vals.size == 0:
                    continue
                mu = float(np.mean(vals))
                sd = _safe_std(vals)
                rows.append(
                    {
                        "scenario": scen,
                        "variant": variant,
                        "metric_key": key,
                        "metric_label": label,
                        "n": int(vals.size),
                        "mean": mu,
                        "std": sd,
                    }
                )
    out = out_dir / "summary_distribution_table.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    return out


def _fmt_table_value(v: float | int | str | None) -> str:
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "N/A"
    if isinstance(v, str):
        return v
    fv = float(v)
    if abs(fv - round(fv)) < 1e-9:
        return f"{int(round(fv))}"
    return f"{fv:.3f}"


def _figure_output_paths(out_path: Path) -> tuple[Path, Path]:
    base_dir = out_path.parent
    pdf_dir = base_dir / "pdfs"
    png_dir = base_dir / "pngs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)
    stem = out_path.stem
    return pdf_dir / f"{stem}.pdf", png_dir / f"{stem}.png"


def _save_figure_dual(fig, out_path: Path, dpi: int = 220) -> Path:
    pdf_path, png_path = _figure_output_paths(out_path)
    fig.savefig(pdf_path, dpi=dpi)
    fig.savefig(png_path, dpi=dpi)
    return pdf_path


def _safe_axis_limits(values: list[float], pad_frac: float = 0.06) -> tuple[float, float] | None:
    finite = np.asarray([v for v in values if math.isfinite(v)], dtype=float)
    if finite.size == 0:
        return None
    vmin = float(np.min(finite))
    vmax = float(np.max(finite))
    if abs(vmax - vmin) < 1e-12:
        span = max(abs(vmax), 1.0) * 0.05
        return vmin - span, vmax + span
    pad = (vmax - vmin) * pad_frac
    return vmin - pad, vmax + pad


def _save_table_pdf(
    plt,
    rows: list[list[str]],
    headers: list[str],
    title: str,
    subtitle: str,
    out_path: Path,
) -> Path | None:
    if not rows:
        return None
    n_cols = max(1, len(headers))
    max_text_len = max(
        [len(str(h)) for h in headers] +
        [len(str(cell)) for row in rows for cell in row]
    )
    # Dynamic width prevents rightmost columns (e.g., Std values) from clipping.
    fig_w = max(11.0, 1.55 * n_cols + 0.035 * max_text_len)
    fig_h = max(2.6, 1.6 + 0.42 * len(rows))
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")
    table = ax.table(
        cellText=rows,
        colLabels=headers,
        loc="center",
        cellLoc="center",
        colLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10.0)
    table.scale(1.0, 1.30)
    try:
        table.auto_set_column_width(col=list(range(n_cols)))
    except Exception:
        # Older Matplotlib versions may not expose auto_set_column_width.
        pass
    for (r, c), cell in table.get_celld().items():
        cell.set_text_props(wrap=True)
        if r == 0:
            cell.set_text_props(weight="bold")
            cell.set_facecolor("#eeeeee")
    fig.suptitle(f"{title}\n{subtitle}", y=0.98, fontsize=14)
    fig.tight_layout(rect=[0.02, 0.02, 0.98, 0.93])
    out_pdf = _save_figure_dual(fig, out_path, dpi=260)
    plt.close(fig)
    return out_pdf


def _delta_pct(sa: float, tr: float, lower_is_better: bool = True) -> float:
    if not (math.isfinite(sa) and math.isfinite(tr)):
        return float("nan")
    denom = abs(tr) if abs(tr) > 1e-12 else 1.0
    raw = 100.0 * (sa - tr) / denom
    return raw if not lower_is_better else -raw


def _bootstrap_ci_mean(values: np.ndarray, n_boot: int = 1000, alpha: float = 0.05) -> tuple[float, float]:
    if values.size == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(7)
    means = np.empty(n_boot, dtype=float)
    n = values.size
    for i in range(n_boot):
        sample = rng.choice(values, size=n, replace=True)
        means[i] = float(np.mean(sample))
    return float(np.quantile(means, alpha / 2.0)), float(np.quantile(means, 1.0 - alpha / 2.0))


def _make_summary_charts(summary_csv: Path, out_dir: Path) -> list[Path]:
    import matplotlib.pyplot as plt
    _apply_paper_style(plt)

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
    if (
        "nmac_proximity_aware_instant_detect" in df.columns
        and "nmac_benign_spoofer_aware_instant_detect" in df.columns
    ):
        df["nmac_total_real_aware_instant_detect"] = (
            pd.to_numeric(df["nmac_proximity_aware_instant_detect"], errors="coerce").fillna(0.0)
            + pd.to_numeric(df["nmac_benign_spoofer_aware_instant_detect"], errors="coerce").fillna(0.0)
        )

    metric_specs = [
        (
            "Total NMACs (real-position)\n= benign-benign + benign-spoofer",
            {
                "SpoofingAware": "nmac_total_real_aware",
                "SpoofingAwareInstantDetect": "nmac_total_real_aware_instant_detect",
                "TrustRID": "nmac_total_real_trust_rid",
            },
        ),
        (
            "Benign-Benign NMACs",
            {
                "SpoofingAware": "nmac_proximity_aware",
                "SpoofingAwareInstantDetect": "nmac_proximity_aware_instant_detect",
                "TrustRID": "nmac_proximity_trust_rid",
            },
        ),
        (
            "Benign-Spoofer NMACs\n(true spoofer position)",
            {
                "SpoofingAware": "nmac_benign_spoofer_aware",
                "SpoofingAwareInstantDetect": "nmac_benign_spoofer_aware_instant_detect",
                "TrustRID": "nmac_benign_spoofer_trust_rid",
            },
        ),
        (
            "Min distance to true spoofer (m)",
            {
                "SpoofingAware": "min_benign_spoofer_distance_aware_m",
                "SpoofingAwareInstantDetect": "min_benign_spoofer_distance_aware_instant_detect_m",
                "TrustRID": "min_benign_spoofer_distance_trust_rid_m",
            },
        ),
        (
            "Chance-constraint violations",
            {
                "SpoofingAware": "nmac_spoofer_unsafe_aware",
                "SpoofingAwareInstantDetect": "nmac_spoofer_unsafe_aware_instant_detect",
                "TrustRID": "nmac_spoofer_unsafe_trust_rid",
            },
        ),
        (
            "Spoofer containment percent",
            {
                "SpoofingAware": "spoofer_containment_rate_aware",
                "SpoofingAwareInstantDetect": "spoofer_containment_rate_aware_instant_detect",
                "TrustRID": "spoofer_containment_rate_trust_rid",
            },
        ),
        (
            "Detection reports processed",
            {
                "SpoofingAware": "detection_reports_total_aware",
                "SpoofingAwareInstantDetect": "detection_reports_total_aware_instant_detect",
            },
        ),
        (
            "Detection callbacks with MLAT attempted",
            {
                "SpoofingAware": "detection_mlat_attempted_aware",
                "SpoofingAwareInstantDetect": "detection_mlat_attempted_aware_instant_detect",
            },
        ),
        (
            "Detection callbacks skipped (receivers < 4)",
            {
                "SpoofingAware": "detection_mlat_skipped_insufficient_receivers_aware",
                "SpoofingAwareInstantDetect": "detection_mlat_skipped_insufficient_receivers_aware_instant_detect",
            },
        ),
        (
            "Skipped MLAT fraction during detection",
            {
                "SpoofingAware": "detection_mlat_skipped_insufficient_receivers_fraction_aware",
                "SpoofingAwareInstantDetect": "detection_mlat_skipped_insufficient_receivers_fraction_aware_instant_detect",
            },
        ),
    ]

    # Boxplots across seeds for all available variants on each metric.
    n_plots = len(metric_specs)
    n_cols = 3
    n_rows = max(1, int(math.ceil(float(n_plots) / float(n_cols))))
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5.0 * n_cols, 4.0 * n_rows))
    axes = axes.ravel()
    idx = 0
    for title, variant_cols in metric_specs:
        ax = axes[idx]
        idx += 1
        data: list[np.ndarray] = []
        labels: list[str] = []
        for variant in VARIANT_ORDER:
            col = variant_cols.get(variant)
            if not col or col not in df.columns:
                continue
            vals = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)
            if vals.size == 0:
                continue
            data.append(vals)
            labels.append(variant)
        if not data:
            ax.axis("off")
            ax.set_title(f"{title} (missing data)")
            continue
        means = [float(np.mean(d)) for d in data]
        stds = [_safe_std(d) for d in data]
        xpos = np.arange(len(labels))
        colors_bar = [VARIANT_COLORS.get(lbl, "#888888") for lbl in labels]
        ax.bar(xpos, means, yerr=stds, capsize=3, tick_label=labels, color=colors_bar)
        ax.set_title(title)
    while idx < len(axes):
        axes[idx].axis("off")
        idx += 1
    fig.suptitle("Safety Metrics Across Seeds (mean ± std)")
    fig.tight_layout()
    p = out_dir / "summary_boxplots.pdf"
    p = _save_figure_dual(fig, p, dpi=220)
    plt.close(fig)
    out_paths.append(p)

    # Keep summary_means_table.csv for downstream analysis, but stop generating
    # summary_means.png because it duplicates summary_boxplots.png information.
    mean_specs = [
        (
            "Total NMACs (real-position)",
            "nmac_total_real_aware",
            "nmac_total_real_aware_instant_detect",
            "nmac_total_real_trust_rid",
        ),
        (
            "Benign-Benign NMACs",
            "nmac_proximity_aware",
            "nmac_proximity_aware_instant_detect",
            "nmac_proximity_trust_rid",
        ),
        (
            "Benign-Spoofer NMACs",
            "nmac_benign_spoofer_aware",
            "nmac_benign_spoofer_aware_instant_detect",
            "nmac_benign_spoofer_trust_rid",
        ),
        (
            "Min distance to true spoofer (m)",
            "min_benign_spoofer_distance_aware_m",
            "min_benign_spoofer_distance_aware_instant_detect_m",
            "min_benign_spoofer_distance_trust_rid_m",
        ),
        (
            "SpoofingAware: chance-constraint violations",
            "nmac_spoofer_unsafe_aware",
            "nmac_spoofer_unsafe_aware_instant_detect",
            None,
        ),
        (
            "SpoofingAware: spoofer containment percent",
            "spoofer_containment_rate_aware",
            "spoofer_containment_rate_aware_instant_detect",
            None,
        ),
        (
            "SpoofingAware: detection reports processed",
            "detection_reports_total_aware",
            "detection_reports_total_aware_instant_detect",
            None,
        ),
        (
            "SpoofingAware: detection callbacks with MLAT attempted",
            "detection_mlat_attempted_aware",
            "detection_mlat_attempted_aware_instant_detect",
            None,
        ),
        (
            "SpoofingAware: detection callbacks skipped (receivers < 4)",
            "detection_mlat_skipped_insufficient_receivers_aware",
            "detection_mlat_skipped_insufficient_receivers_aware_instant_detect",
            None,
        ),
        (
            "SpoofingAware: skipped MLAT fraction during detection",
            "detection_mlat_skipped_insufficient_receivers_fraction_aware",
            "detection_mlat_skipped_insufficient_receivers_fraction_aware_instant_detect",
            None,
        ),
        (
            "SpoofingAware: raw RSSI/NLLS localization RMSE (m)",
            "localization_mlat_raw_rmse_m_aware",
            "localization_mlat_raw_rmse_m_aware_instant_detect",
            None,
        ),
        (
            "SpoofingAware: raw RSSI/NLLS localization MAE (m)",
            "localization_mlat_raw_mae_m_aware",
            "localization_mlat_raw_mae_m_aware_instant_detect",
            None,
        ),
    ]
    rows = []
    for label, aware_col, instant_col, trust_col in mean_specs:
        if aware_col not in df.columns:
            continue
        aware_vals = pd.to_numeric(df[aware_col], errors="coerce").dropna().to_numpy(dtype=float)
        if aware_vals.size == 0:
            continue
        aware_mean = float(np.mean(aware_vals))
        aware_std = _safe_std(aware_vals)
        instant_mean = float("nan")
        instant_std = float("nan")
        if instant_col and instant_col in df.columns:
            instant_vals = pd.to_numeric(df[instant_col], errors="coerce").dropna().to_numpy(dtype=float)
            if instant_vals.size > 0:
                instant_mean = float(np.mean(instant_vals))
                instant_std = _safe_std(instant_vals)
        trust_mean = float("nan")
        trust_std = float("nan")
        if trust_col and trust_col in df.columns:
            trust_vals = pd.to_numeric(df[trust_col], errors="coerce").dropna().to_numpy(dtype=float)
            if trust_vals.size > 0:
                trust_mean = float(np.mean(trust_vals))
                trust_std = _safe_std(trust_vals)
        rows.append((
            label,
            aware_mean,
            aware_std,
            instant_mean,
            instant_std,
            trust_mean,
            trust_std,
        ))
    if rows:
        mean_df = pd.DataFrame(
            rows,
            columns=[
                "metric",
                "spoofing_aware_mean",
                "spoofing_aware_std",
                "spoofing_aware_instant_detect_mean",
                "spoofing_aware_instant_detect_std",
                "trust_rid_mean",
                "trust_rid_std",
            ],
        )
        p_csv = out_dir / "summary_means_table.csv"
        mean_df.to_csv(p_csv, index=False)
        out_paths.append(p_csv)

        # Paper-style NMAC summary statistics table figure (Table II style).
        table2_rows: list[list[str]] = []
        for _, rr in mean_df.iterrows():
            table2_rows.append(
                [
                    str(rr["metric"]),
                    _fmt_table_value(rr["spoofing_aware_mean"]),
                    _fmt_table_value(
                        rr["spoofing_aware_instant_detect_mean"]
                        if pd.notna(rr["spoofing_aware_instant_detect_mean"])
                        else float("nan")
                    ),
                    _fmt_table_value(rr["trust_rid_mean"] if pd.notna(rr["trust_rid_mean"]) else float("nan")),
                    _fmt_table_value(rr["spoofing_aware_std"]),
                    _fmt_table_value(
                        rr["spoofing_aware_instant_detect_std"]
                        if pd.notna(rr["spoofing_aware_instant_detect_std"])
                        else float("nan")
                    ),
                    _fmt_table_value(rr["trust_rid_std"] if pd.notna(rr["trust_rid_std"]) else float("nan")),
                ]
            )
        p_table2_csv = out_dir / "table_ii_nmac_summary_statistics.csv"
        pd.DataFrame(
            table2_rows,
            columns=[
                "Metric",
                "Mean (SA)",
                "Mean (SA InstantDetect)",
                "Mean (Trust-RID)",
                "Std (SA)",
                "Std (SA InstantDetect)",
                "Std (Trust-RID)",
            ],
        ).to_csv(p_table2_csv, index=False)
        out_paths.append(p_table2_csv)
        p_table2_pdf = _save_table_pdf(
            plt=plt,
            rows=table2_rows,
            headers=[
                "Metric",
                "Mean\n(SA)",
                "Mean\n(SA-ID)",
                "Mean\n(Trust-RID)",
                "Std\n(SA)",
                "Std\n(SA-ID)",
                "Std\n(Trust-RID)",
            ],
            title="TABLE II",
            subtitle="NMAC (real-position) summary statistics",
            out_path=out_dir / "table_ii_nmac_summary_statistics.pdf",
        )
        if p_table2_pdf is not None:
            out_paths.append(p_table2_pdf)

    stale_summary_means_png = out_dir / "summary_means.png"
    if stale_summary_means_png.exists():
        stale_summary_means_png.unlink()

    # Runtime comparison across scenarios: SpoofingAware vs InstantDetect vs TrustRID.
    # Uses full wall-clock per-variant runtime from run_timing.csv.
    rt = None
    runtime_label = "Wall-clock runtime per run (s)"
    rt_csv = out_dir.parent / "run_timing.csv"
    if rt_csv.is_file():
        try:
            rt_file = pd.read_csv(rt_csv)
            if (
                "scenario" in rt_file.columns
                and "elapsed_aware_seconds" in rt_file.columns
                and "elapsed_aware_instant_detect_seconds" in rt_file.columns
                and "elapsed_trust_rid_seconds" in rt_file.columns
            ):
                rt = rt_file.copy()
        except Exception:
            rt = None

    if rt is not None and "scenario" in rt.columns:
        scenarios = sorted(rt["scenario"].dropna().unique().tolist())
        if scenarios:
            aware_means: list[float] = []
            aware_stds: list[float] = []
            instant_means: list[float] = []
            instant_stds: list[float] = []
            trust_means: list[float] = []
            trust_stds: list[float] = []
            labels: list[str] = []
            for scen in scenarios:
                ss = rt[rt["scenario"] == scen]
                aware_vals = pd.to_numeric(ss["elapsed_aware_seconds"], errors="coerce").dropna().to_numpy(dtype=float)
                instant_vals = pd.to_numeric(
                    ss["elapsed_aware_instant_detect_seconds"], errors="coerce"
                ).dropna().to_numpy(dtype=float)
                trust_vals = pd.to_numeric(ss["elapsed_trust_rid_seconds"], errors="coerce").dropna().to_numpy(dtype=float)
                if aware_vals.size == 0 or instant_vals.size == 0 or trust_vals.size == 0:
                    continue
                a_mu = float(np.mean(aware_vals))
                i_mu = float(np.mean(instant_vals))
                t_mu = float(np.mean(trust_vals))

                labels.append(scen.replace("Scenario_", "").replace("_", " "))
                aware_means.append(a_mu)
                aware_stds.append(_safe_std(aware_vals))
                instant_means.append(i_mu)
                instant_stds.append(_safe_std(instant_vals))
                trust_means.append(t_mu)
                trust_stds.append(_safe_std(trust_vals))

            if labels:
                x = np.arange(len(labels))
                width = 0.25
                fig, ax = plt.subplots(figsize=(12.5, 5.5))
                ax.bar(
                    x - width,
                    aware_means,
                    width=width,
                    yerr=aware_stds,
                    capsize=3,
                    label="SpoofingAware",
                    color=VARIANT_COLORS["SpoofingAware"],
                )
                ax.bar(
                    x,
                    instant_means,
                    width=width,
                    yerr=instant_stds,
                    capsize=3,
                    label="SpoofingAwareInstantDetect",
                    color=VARIANT_COLORS["SpoofingAwareInstantDetect"],
                )
                ax.bar(
                    x + width,
                    trust_means,
                    width=width,
                    yerr=trust_stds,
                    capsize=3,
                    label="TrustRID",
                    color=VARIANT_COLORS["TrustRID"],
                )
                ax.set_xticks(x)
                ax.set_xticklabels(labels, rotation=20, ha="right")
                ax.set_ylabel(runtime_label)
                ax.set_title("Runtime by Scenario: SpoofingAware vs InstantDetect vs TrustRID (mean ± std)")
                ax.grid(axis="y", alpha=0.2)
                ax.legend()
                fig.tight_layout()
                p = out_dir / "runtime_compare_scenarios_aware_vs_trustrid.pdf"
                p = _save_figure_dual(fig, p, dpi=220)
                plt.close(fig)
                out_paths.append(p)

                # Paper-style runtime mean/std table figure (Table III style).
                runtime_rows: list[list[str]] = []
                for i, label in enumerate(labels):
                    runtime_rows.append(
                        [
                            label.replace(" ", "_").lower(),
                            _fmt_table_value(aware_means[i]),
                            _fmt_table_value(aware_stds[i]),
                            _fmt_table_value(instant_means[i]),
                            _fmt_table_value(instant_stds[i]),
                            _fmt_table_value(trust_means[i]),
                            _fmt_table_value(trust_stds[i]),
                        ]
                    )
                p_table3_csv = out_dir / "table_iii_runtime_mean_std_per_scenario_seconds.csv"
                pd.DataFrame(
                    runtime_rows,
                    columns=[
                        "Scenario",
                        "Mean (SA) [s]",
                        "Std (SA) [s]",
                        "Mean (SA InstantDetect) [s]",
                        "Std (SA InstantDetect) [s]",
                        "Mean (Trust-RID) [s]",
                        "Std (Trust-RID) [s]",
                    ],
                ).to_csv(p_table3_csv, index=False)
                out_paths.append(p_table3_csv)
                p_table3_pdf = _save_table_pdf(
                    plt=plt,
                    rows=runtime_rows,
                    headers=[
                        "Scenario",
                        "Mean\n(SA) [s]",
                        "Std\n(SA) [s]",
                        "Mean\n(SA-ID) [s]",
                        "Std\n(SA-ID) [s]",
                        "Mean\n(TR) [s]",
                        "Std\n(TR) [s]",
                    ],
                    title="TABLE III",
                    subtitle="Runtime per scenario: mean ± std (seconds)",
                    out_path=out_dir / "table_iii_runtime_mean_std_per_scenario_seconds.pdf",
                )
                if p_table3_pdf is not None:
                    out_paths.append(p_table3_pdf)

                # Compute-breakdown table (scenario means): runtime + GCS callback costs.
                dd = df.copy()
                if "tag" not in dd.columns:
                    dd["tag"] = "all"
                dd["scenario"] = dd["tag"].apply(_scenario_group_from_tag)
                compute_rows: list[list[str]] = []
                label_to_key = {s.replace("Scenario_", "").replace("_", " "): s for s in scenarios}
                for lbl in labels:
                    scen_key = label_to_key.get(lbl, lbl)
                    scen_df = dd[dd["scenario"] == scen_key]
                    sa_rt = aware_means[labels.index(lbl)]
                    sai_rt = instant_means[labels.index(lbl)]
                    tr_rt = trust_means[labels.index(lbl)]
                    sa_rep = float("nan")
                    sai_rep = float("nan")
                    tr_rep = float("nan")
                    sa_tick = float("nan")
                    sai_tick = float("nan")
                    tr_tick = float("nan")
                    sa_total = float("nan")
                    sai_total = float("nan")
                    tr_total = float("nan")
                    if not scen_df.empty:
                        if "gcs_reports_mean_ms_aware" in scen_df.columns:
                            v = pd.to_numeric(scen_df["gcs_reports_mean_ms_aware"], errors="coerce").dropna().to_numpy(dtype=float)
                            if v.size > 0:
                                sa_rep = float(np.mean(v))
                        if "gcs_reports_mean_ms_aware_instant_detect" in scen_df.columns:
                            v = pd.to_numeric(
                                scen_df["gcs_reports_mean_ms_aware_instant_detect"], errors="coerce"
                            ).dropna().to_numpy(dtype=float)
                            if v.size > 0:
                                sai_rep = float(np.mean(v))
                        if "gcs_reports_mean_ms_trust_rid" in scen_df.columns:
                            v = pd.to_numeric(scen_df["gcs_reports_mean_ms_trust_rid"], errors="coerce").dropna().to_numpy(dtype=float)
                            if v.size > 0:
                                tr_rep = float(np.mean(v))
                        if "gcs_tick_mean_ms_aware" in scen_df.columns:
                            v = pd.to_numeric(scen_df["gcs_tick_mean_ms_aware"], errors="coerce").dropna().to_numpy(dtype=float)
                            if v.size > 0:
                                sa_tick = float(np.mean(v))
                        if "gcs_tick_mean_ms_aware_instant_detect" in scen_df.columns:
                            v = pd.to_numeric(
                                scen_df["gcs_tick_mean_ms_aware_instant_detect"], errors="coerce"
                            ).dropna().to_numpy(dtype=float)
                            if v.size > 0:
                                sai_tick = float(np.mean(v))
                        if "gcs_tick_mean_ms_trust_rid" in scen_df.columns:
                            v = pd.to_numeric(scen_df["gcs_tick_mean_ms_trust_rid"], errors="coerce").dropna().to_numpy(dtype=float)
                            if v.size > 0:
                                tr_tick = float(np.mean(v))
                        if "gcs_compute_total_s_aware" in scen_df.columns:
                            v = pd.to_numeric(scen_df["gcs_compute_total_s_aware"], errors="coerce").dropna().to_numpy(dtype=float)
                            if v.size > 0:
                                sa_total = float(np.mean(v))
                        if "gcs_compute_total_s_aware_instant_detect" in scen_df.columns:
                            v = pd.to_numeric(
                                scen_df["gcs_compute_total_s_aware_instant_detect"], errors="coerce"
                            ).dropna().to_numpy(dtype=float)
                            if v.size > 0:
                                sai_total = float(np.mean(v))
                        if "gcs_compute_total_s_trust_rid" in scen_df.columns:
                            v = pd.to_numeric(scen_df["gcs_compute_total_s_trust_rid"], errors="coerce").dropna().to_numpy(dtype=float)
                            if v.size > 0:
                                tr_total = float(np.mean(v))
                    compute_rows.append(
                        [
                            lbl.replace(" ", "_").lower(),
                            _fmt_table_value(sa_rt),
                            _fmt_table_value(sai_rt),
                            _fmt_table_value(tr_rt),
                            _fmt_table_value(sa_rep),
                            _fmt_table_value(sai_rep),
                            _fmt_table_value(tr_rep),
                            _fmt_table_value(sa_tick),
                            _fmt_table_value(sai_tick),
                            _fmt_table_value(tr_tick),
                            _fmt_table_value(sa_total),
                            _fmt_table_value(sai_total),
                            _fmt_table_value(tr_total),
                        ]
                    )
                if compute_rows:
                    p_cb_csv = out_dir / "table_vi_compute_breakdown_by_scenario.csv"
                    pd.DataFrame(
                        compute_rows,
                        columns=[
                            "Scenario",
                            "Runtime mean SA (s)",
                            "Runtime mean SA-ID (s)",
                            "Runtime mean Trust-RID (s)",
                            "GCS report mean SA (ms)",
                            "GCS report mean SA-ID (ms)",
                            "GCS report mean Trust-RID (ms)",
                            "GCS tick mean SA (ms)",
                            "GCS tick mean SA-ID (ms)",
                            "GCS tick mean Trust-RID (ms)",
                            "GCS total mean SA (s)",
                            "GCS total mean SA-ID (s)",
                            "GCS total mean Trust-RID (s)",
                        ],
                    ).to_csv(p_cb_csv, index=False)
                    out_paths.append(p_cb_csv)
                    p_cb_pdf = _save_table_pdf(
                        plt=plt,
                        rows=compute_rows,
                        headers=[
                            "Scenario",
                            "Runtime\nSA (s)",
                            "Runtime\nSA-ID (s)",
                            "Runtime\nTR (s)",
                            "Report\nSA (ms)",
                            "Report\nSA-ID (ms)",
                            "Report\nTR (ms)",
                            "Tick\nSA (ms)",
                            "Tick\nSA-ID (ms)",
                            "Tick\nTR (ms)",
                            "GCS total\nSA (s)",
                            "GCS total\nSA-ID (s)",
                            "GCS total\nTR (s)",
                        ],
                        title="TABLE VI",
                        subtitle="Compute breakdown by scenario (means)",
                        out_path=out_dir / "table_vi_compute_breakdown_by_scenario.pdf",
                    )
                    if p_cb_pdf is not None:
                        out_paths.append(p_cb_pdf)

    # Retired chart: detection_mlat_skip_fraction_by_scenario.
    # It is intentionally not generated anymore.
    for stale in [
        out_dir / "detection_mlat_skip_fraction_by_scenario.pdf",
        out_dir / "pdfs" / "detection_mlat_skip_fraction_by_scenario.pdf",
        out_dir / "pngs" / "detection_mlat_skip_fraction_by_scenario.png",
        out_dir / "keycharts" / "detection_mlat_skip_fraction_by_scenario.pdf",
        out_dir / "keycharts" / "detection_mlat_skip_fraction_by_scenario.png",
    ]:
        if stale.exists():
            stale.unlink()

    # Cleanup stale runtime chart that is now intentionally removed.
    stale_runtime_scalability = out_dir / "runtime_scalability_hub.png"
    if stale_runtime_scalability.exists():
        stale_runtime_scalability.unlink()

    out_paths.append(_write_distribution_table(df, out_dir))

    # SA / SA-ID / Trust-RID effect sizes for key paired metrics.
    effect_specs = [
        ("Total NMACs (real-position)", "nmac_total_real_aware", "nmac_total_real_aware_instant_detect", "nmac_total_real_trust_rid", True),
        ("Benign-Benign NMACs", "nmac_proximity_aware", "nmac_proximity_aware_instant_detect", "nmac_proximity_trust_rid", True),
        ("Benign-Spoofer NMACs", "nmac_benign_spoofer_aware", "nmac_benign_spoofer_aware_instant_detect", "nmac_benign_spoofer_trust_rid", True),
        (
            "Min distance to true spoofer (m)",
            "min_benign_spoofer_distance_aware_m",
            "min_benign_spoofer_distance_aware_instant_detect_m",
            "min_benign_spoofer_distance_trust_rid_m",
            False,
        ),
        (
            "GCS report callback mean time (ms)",
            "gcs_reports_mean_ms_aware",
            "gcs_reports_mean_ms_aware_instant_detect",
            "gcs_reports_mean_ms_trust_rid",
            True,
        ),
        (
            "GCS tick callback mean time (ms)",
            "gcs_tick_mean_ms_aware",
            "gcs_tick_mean_ms_aware_instant_detect",
            "gcs_tick_mean_ms_trust_rid",
            True,
        ),
        (
            "Total GCS compute time (s)",
            "gcs_compute_total_s_aware",
            "gcs_compute_total_s_aware_instant_detect",
            "gcs_compute_total_s_trust_rid",
            True,
        ),
    ]
    effect_rows: list[list[str]] = []
    for label, sa_col, sai_col, tr_col, lower_better in effect_specs:
        if sa_col not in df.columns or sai_col not in df.columns or tr_col not in df.columns:
            continue
        sa_vals = pd.to_numeric(df[sa_col], errors="coerce").dropna().to_numpy(dtype=float)
        sai_vals = pd.to_numeric(df[sai_col], errors="coerce").dropna().to_numpy(dtype=float)
        tr_vals = pd.to_numeric(df[tr_col], errors="coerce").dropna().to_numpy(dtype=float)
        if sa_vals.size == 0 or sai_vals.size == 0 or tr_vals.size == 0:
            continue
        sa_mean = float(np.mean(sa_vals))
        sai_mean = float(np.mean(sai_vals))
        tr_mean = float(np.mean(tr_vals))
        sa_std = _safe_std(sa_vals)
        sai_std = _safe_std(sai_vals)
        tr_std = _safe_std(tr_vals)
        imp_sa_vs_tr = _delta_pct(sa_mean, tr_mean, lower_is_better=lower_better)
        imp_sai_vs_tr = _delta_pct(sai_mean, tr_mean, lower_is_better=lower_better)
        effect_rows.append(
            [
                label,
                _fmt_table_value(sa_mean),
                _fmt_table_value(sai_mean),
                _fmt_table_value(tr_mean),
                _fmt_table_value(sa_std),
                _fmt_table_value(sai_std),
                _fmt_table_value(tr_std),
                _fmt_table_value(imp_sa_vs_tr),
                _fmt_table_value(imp_sai_vs_tr),
            ]
        )
    if effect_rows:
        p_eff_csv = out_dir / "table_iv_effect_size_sa_vs_trustrid.csv"
        pd.DataFrame(
            effect_rows,
            columns=[
                "Metric",
                "Mean (SA)",
                "Mean (SA-ID)",
                "Mean (Trust-RID)",
                "Std (SA)",
                "Std (SA-ID)",
                "Std (Trust-RID)",
                "Improvement SA vs Trust % (mean-based)",
                "Improvement SA-ID vs Trust % (mean-based)",
            ],
        ).to_csv(p_eff_csv, index=False)
        out_paths.append(p_eff_csv)
        p_eff_pdf = _save_table_pdf(
            plt=plt,
            rows=effect_rows,
            headers=[
                "Metric",
                "Mean\n(SA)",
                "Mean\n(SA-ID)",
                "Mean\n(Trust-RID)",
                "Std\n(SA)",
                "Std\n(SA-ID)",
                "Std\n(Trust-RID)",
                "SA vs TR\nImprovement %",
                "SA-ID vs TR\nImprovement %",
            ],
            title="TABLE IV",
            subtitle="SA / SA-ID / Trust-RID effect-size summary",
            out_path=out_dir / "table_iv_effect_size_sa_vs_trustrid.pdf",
        )
        if p_eff_pdf is not None:
            out_paths.append(p_eff_pdf)

    # Containment calibration summary: expected = 1-alpha (default alpha=0.05).
    if "spoofer_containment_rate_aware" in df.columns:
        expected = 0.95
        dd = df.copy()
        if "tag" not in dd.columns:
            dd["tag"] = "all"
        dd["scenario"] = dd["tag"].apply(_scenario_group_from_tag)
        calib_rows: list[list[str]] = []
        for scen, g in dd.groupby("scenario"):
            vals = pd.to_numeric(g["spoofer_containment_rate_aware"], errors="coerce").dropna().to_numpy(dtype=float)
            if vals.size == 0:
                continue
            obs_mean = float(np.mean(vals))
            obs_std = _safe_std(vals)
            ci_lo, ci_hi = _bootstrap_ci_mean(vals)
            calib_rows.append(
                [
                    str(scen),
                    _fmt_table_value(expected),
                    _fmt_table_value(obs_mean),
                    _fmt_table_value(obs_std),
                    _fmt_table_value(obs_mean - expected),
                    _fmt_table_value(ci_lo),
                    _fmt_table_value(ci_hi),
                ]
            )
        if calib_rows:
            p_cal_csv = out_dir / "table_v_containment_calibration.csv"
            pd.DataFrame(
                calib_rows,
                columns=[
                    "Scenario",
                    "Expected containment",
                    "Observed mean",
                    "Observed std",
                    "Calibration error (mean-expected)",
                    "Observed mean CI95 low",
                    "Observed mean CI95 high",
                ],
            ).to_csv(p_cal_csv, index=False)
            out_paths.append(p_cal_csv)
            p_cal_pdf = _save_table_pdf(
                plt=plt,
                rows=calib_rows,
                headers=[
                    "Scenario",
                    "Expected",
                    "Observed\nmean",
                    "Observed\nstd",
                    "Error",
                    "CI95 low",
                    "CI95 high",
                ],
                title="TABLE V",
                subtitle="Containment calibration by scenario",
                out_path=out_dir / "table_v_containment_calibration.pdf",
            )
            if p_cal_pdf is not None:
                out_paths.append(p_cal_pdf)

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
                            "scenario": _scenario_group_from_source_file(p.name),
                            "variant": _variant_from_name(p.name),
                            "name": name,
                            "time": t,
                            "value": v,
                        }
                    )
                except ValueError:
                    continue
    return pd.DataFrame(rows)


def _make_timeseries_charts(long_df: pd.DataFrame, out_dir: Path, plot_profile: str = "paper") -> list[Path]:
    import matplotlib.pyplot as plt
    _apply_paper_style(plt)

    out_paths: list[Path] = []
    if long_df.empty:
        return out_paths

    long_df.to_csv(out_dir / "gcs_timeseries_long.csv", index=False)
    out_paths.append(out_dir / "gcs_timeseries_long.csv")

    def _clean_imm_sub(df: pd.DataFrame) -> pd.DataFrame:
        sub = df.copy()
        # Filter obviously non-physical IMM states so charts are interpretable.
        lim_xy = 5000.0
        lim_z = 3000.0
        lim_err = 10000.0
        m_xy = sub["name"].isin(["imm_est_x_m", "imm_est_y_m", "imm_true_x_m", "imm_true_y_m"])
        m_z = sub["name"].isin(["imm_est_z_m", "imm_true_z_m"])
        m_err = sub["name"].isin(["imm_error_norm_m"])
        sub = sub[(~m_xy) | (sub["value"].abs() <= lim_xy)]
        sub = sub[(~m_z) | (sub["value"].abs() <= lim_z)]
        sub = sub[(~m_err) | (sub["value"].abs() <= lim_err)]
        return sub

    def _write_imm_diagnostics_table(df: pd.DataFrame) -> Path | None:
        sub = df[(df["variant"] == "SpoofingAware") & (df["name"].str.contains("imm_", na=False))]
        if sub.empty:
            return None
        rows: list[dict] = []
        for scen in sorted(sub["scenario"].dropna().unique().tolist()):
            ss = sub[sub["scenario"] == scen]
            nees = pd.to_numeric(ss.loc[ss["name"] == "imm_nees", "value"], errors="coerce").dropna()
            nis = pd.to_numeric(ss.loc[ss["name"] == "imm_nis_mix", "value"], errors="coerce").dropna()
            err = pd.to_numeric(ss.loc[ss["name"] == "imm_error_norm_m", "value"], errors="coerce").dropna()
            p_cv = pd.to_numeric(ss.loc[ss["name"] == "imm_mode_prob_cv", "value"], errors="coerce").dropna()
            p_ca = pd.to_numeric(ss.loc[ss["name"] == "imm_mode_prob_ca", "value"], errors="coerce").dropna()
            p = pd.concat([p_cv, (1.0 - p_ca)], ignore_index=True) if not p_cv.empty or not p_ca.empty else pd.Series(dtype=float)
            if not p.empty:
                p = p.clip(1e-9, 1.0 - 1e-9)
                mode_entropy = float(np.mean(-(p * np.log(p) + (1.0 - p) * np.log(1.0 - p))))
            else:
                mode_entropy = float("nan")
            rows.append(
                {
                    "scenario": scen,
                    "imm_error_mean_m": float(err.mean()) if not err.empty else float("nan"),
                    "imm_error_std_m": float(err.std(ddof=1)) if len(err) > 1 else 0.0,
                    "imm_nees_mean": float(nees.mean()) if not nees.empty else float("nan"),
                    "imm_nees_std": float(nees.std(ddof=1)) if len(nees) > 1 else 0.0,
                    "imm_nees_in_95pct_fraction": (
                        float(((nees >= CHI2_3DOF_95_LO) & (nees <= CHI2_3DOF_95_HI)).mean())
                        if not nees.empty else float("nan")
                    ),
                    "imm_nis_mean": float(nis.mean()) if not nis.empty else float("nan"),
                    "imm_nis_std": float(nis.std(ddof=1)) if len(nis) > 1 else 0.0,
                    "imm_nis_in_95pct_fraction": (
                        float(((nis >= CHI2_3DOF_95_LO) & (nis <= CHI2_3DOF_95_HI)).mean())
                        if not nis.empty else float("nan")
                    ),
                    "imm_mode_entropy_mean": mode_entropy,
                }
            )
        if not rows:
            return None
        p = out_dir / "imm_diagnostics_summary.csv"
        pd.DataFrame(rows).to_csv(p, index=False)
        return p

    def _plot_by_scenario(
        df: pd.DataFrame,
        metric_pattern: str,
        title: str,
        ylabel: str,
        out_name: str,
        variants: list[str],
        hline: float | None = None,
        hline_label: str | None = None,
        hlines: list[tuple[float, str, str]] | None = None,
    ) -> Path | None:
        sub = df[df["name"].str.contains(metric_pattern, na=False)]
        if sub.empty:
            return None
        scenarios = sorted(sub["scenario"].dropna().unique().tolist())
        if not scenarios:
            return None
        n = len(scenarios)
        fig, axes = plt.subplots(1, n, figsize=(5.0 * n, 4.2), squeeze=False, sharey=True)
        global_y_values: list[float] = []
        for i, scen in enumerate(scenarios):
            ax = axes[0][i]
            ss = sub[sub["scenario"] == scen]
            for variant in variants:
                g = ss[ss["variant"] == variant]
                if g.empty:
                    continue
                agg = g.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                agg["std"] = agg["std"].fillna(0.0)
                color = VARIANT_COLORS.get(variant)
                ax.fill_between(
                    agg["time"],
                    agg["mean"] - agg["std"],
                    agg["mean"] + agg["std"],
                    alpha=0.22,
                    color=color,
                    linewidth=0,
                )
                ax.plot(
                    agg["time"],
                    agg["mean"],
                    label=variant,
                    color=color,
                    linestyle=VARIANT_LINESTYLES.get(variant, "-"),
                    linewidth=1.9,
                )
                global_y_values.extend((agg["mean"] - agg["std"]).tolist())
                global_y_values.extend((agg["mean"] + agg["std"]).tolist())
            if hline is not None:
                ax.axhline(
                    y=hline,
                    color="crimson",
                    linestyle="--",
                    linewidth=1.1,
                    label=hline_label if hline_label else None,
                )
            if hlines:
                for yval, style, label in hlines:
                    ax.axhline(
                        y=float(yval),
                        color="crimson",
                        linestyle=style,
                        linewidth=1.1,
                        label=label,
                    )
            ax.set_title(str(scen))
            ax.set_xlabel("time (s)")
            ax.set_ylabel(ylabel)
            ax.grid(alpha=0.2)
            ax.legend(fontsize=8)
        ylim = _safe_axis_limits(global_y_values)
        if ylim is not None:
            for ax in axes[0]:
                ax.set_ylim(*ylim)
        fig.suptitle(title)
        fig.tight_layout()
        p = out_dir / out_name
        p = _save_figure_dual(fig, p, dpi=220)
        plt.close(fig)
        return p

    def _plot_detection_timing(df: pd.DataFrame) -> Path | None:
        # Compare first detection timing across all variants when available.
        if df.empty:
            return None
        sub_all = df.copy()
        sub_all["name"] = sub_all["name"].astype(str)
        metric = "spoofer_detected" if (sub_all["name"] == "spoofer_detected").any() else "combined_alert"
        if not (sub_all["name"] == metric).any():
            return None
        sub_all = sub_all[sub_all["name"] == metric].copy()
        sub_all["value"] = pd.to_numeric(sub_all["value"], errors="coerce")
        sub_all["time"] = pd.to_numeric(sub_all["time"], errors="coerce")
        sub_all = sub_all.dropna(subset=["value", "time", "source_file", "scenario", "variant"])
        if sub_all.empty:
            return None

        rows: list[dict] = []
        grouped = sub_all.sort_values(["source_file", "time"]).groupby(
            ["scenario", "variant", "source_file"], as_index=False
        )
        for (scen, variant, src), g in grouped:
            detected = g[g["value"] > 0.5]
            rows.append(
                {
                    "scenario": str(scen),
                    "variant": str(variant),
                    "source_file": str(src),
                    "first_detection_time_s": float(detected["time"].iloc[0]) if not detected.empty else float("nan"),
                }
            )
        det_df = pd.DataFrame(rows)
        if det_df.empty:
            return None

        # Save underlying per-run table for traceability.
        det_csv = out_dir / "detection_first_time_by_run.csv"
        det_df.to_csv(det_csv, index=False)
        out_paths.append(det_csv)

        # Plot distribution across runs for each scenario and variant.
        scen_order = sorted(det_df["scenario"].dropna().unique().tolist())
        variants = [v for v in VARIANT_ORDER if v in det_df["variant"].unique().tolist()]
        if not variants:
            return None

        fig, ax = plt.subplots(figsize=(max(8.0, 1.7 * len(scen_order)), 4.6))
        width = 0.22
        positions: list[float] = []
        data: list[np.ndarray] = []
        labels: list[str] = []
        for si, scen in enumerate(scen_order):
            base = float(si)
            for vi, variant in enumerate(variants):
                vals = pd.to_numeric(
                    det_df.loc[
                        (det_df["scenario"] == scen) & (det_df["variant"] == variant),
                        "first_detection_time_s",
                    ],
                    errors="coerce",
                ).dropna().to_numpy(dtype=float)
                if vals.size == 0:
                    continue
                positions.append(base + (vi - (len(variants) - 1) / 2.0) * width)
                data.append(vals)
                labels.append(variant)
        if not data:
            plt.close(fig)
            return None
        means = [float(np.mean(d)) for d in data]
        stds = [_safe_std(d) for d in data]
        colors_bar = [VARIANT_COLORS.get(lbl, "#999999") for lbl in labels]
        ax.bar(
            positions,
            means,
            width=width * 0.85,
            yerr=stds,
            capsize=2,
            color=colors_bar,
            alpha=0.75,
        )
        ax.set_xticks(np.arange(len(scen_order)))
        ax.set_xticklabels(scen_order, rotation=20, ha="right")
        ax.set_title("First Detection Time by Scenario (mean ± std)")
        ax.set_ylabel("first detection time (s)")
        ax.set_xlabel("scenario")
        ax.grid(axis="y", alpha=0.2)
        legend_done: set[str] = set()
        for lbl in labels:
            if lbl in legend_done:
                continue
            ax.plot([], [], color=VARIANT_COLORS.get(lbl, "#999999"), linewidth=8, alpha=0.6, label=lbl)
            legend_done.add(lbl)
        if legend_done:
            ax.legend(fontsize=8, loc="best")
        fig.tight_layout()
        p = out_dir / "detection_first_time_by_scenario.pdf"
        p = _save_figure_dual(fig, p, dpi=220)
        plt.close(fig)
        return p

    def _plot_imm_mode_probabilities(df: pd.DataFrame) -> Path | None:
        sub = df[
            (df["variant"] == "SpoofingAware")
            & (df["name"].str.contains("imm_mode_prob_(cv|ca)", na=False))
        ]
        if sub.empty:
            return None
        scenarios = sorted(sub["scenario"].dropna().unique().tolist())
        if not scenarios:
            return None
        n = len(scenarios)
        fig, axes = plt.subplots(1, n, figsize=(5.0 * n, 4.2), squeeze=False)
        for i, scen in enumerate(scenarios):
            ax = axes[0][i]
            ss = sub[sub["scenario"] == scen]
            for metric_name, label, color in [
                ("imm_mode_prob_cv", "IMM CV mode probability", "#1f77b4"),
                ("imm_mode_prob_ca", "IMM CA mode probability", "#ff7f0e"),
            ]:
                g = ss[ss["name"] == metric_name]
                if g.empty:
                    continue
                agg = g.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                agg["std"] = agg["std"].fillna(0.0)
                ax.fill_between(
                    agg["time"],
                    agg["mean"] - agg["std"],
                    agg["mean"] + agg["std"],
                    alpha=0.22,
                    color=color,
                    linewidth=0,
                )
                ax.plot(agg["time"], agg["mean"], label=label, color=color)
            ax.set_title(str(scen))
            ax.set_xlabel("time (s)")
            ax.set_ylabel("probability")
            ax.set_ylim(-0.02, 1.02)
            ax.grid(alpha=0.2)
            ax.legend(fontsize=8)
        fig.suptitle("SpoofingAware IMM Mode Probabilities Through Time (mean ± std)")
        fig.tight_layout()
        p = out_dir / "timeseries_imm_mode_probabilities_mean_std.pdf"
        p = _save_figure_dual(fig, p, dpi=220)
        plt.close(fig)
        return p

    def _plot_imm_true_vs_estimated_xy(df: pd.DataFrame) -> Path | None:
        sub = df[(df["variant"] == "SpoofingAware") & (df["name"].str.contains("imm_(true|est)_[xy]_m", na=False))]
        sub = _clean_imm_sub(sub)
        if sub.empty:
            return None
        scenarios = sorted(sub["scenario"].dropna().unique().tolist())
        if not scenarios:
            return None
        n = len(scenarios)
        fig, axes = plt.subplots(1, n, figsize=(5.0 * n, 4.5), squeeze=False)
        for i, scen in enumerate(scenarios):
            ax = axes[0][i]
            ss = sub[sub["scenario"] == scen]
            ex = ss[ss["name"] == "imm_est_x_m"].groupby("time", as_index=False)["value"].mean()
            ey = ss[ss["name"] == "imm_est_y_m"].groupby("time", as_index=False)["value"].mean()
            tx = ss[ss["name"] == "imm_true_x_m"].groupby("time", as_index=False)["value"].mean()
            ty = ss[ss["name"] == "imm_true_y_m"].groupby("time", as_index=False)["value"].mean()
            est = pd.merge(ex.rename(columns={"value": "x"}), ey.rename(columns={"value": "y"}), on="time", how="inner")
            tru = pd.merge(tx.rename(columns={"value": "x"}), ty.rename(columns={"value": "y"}), on="time", how="inner")
            if not est.empty:
                ax.plot(est["x"], est["y"], label="Estimated trajectory", color="#1f77b4", linewidth=1.7)
            if not tru.empty:
                ax.plot(tru["x"], tru["y"], label="True trajectory", color="#2ca02c", linewidth=1.7, linestyle="--")
            ax.set_title(str(scen))
            ax.set_xlabel("x (m)")
            ax.set_ylabel("y (m)")
            ax.axis("equal")
            ax.grid(alpha=0.2)
            ax.legend(fontsize=8)
        fig.suptitle("SpoofingAware IMM: True vs Estimated XY Trajectory (mean across seeds)")
        fig.tight_layout()
        p = out_dir / "timeseries_imm_true_vs_estimated_xy_mean.pdf"
        p = _save_figure_dual(fig, p, dpi=220)
        plt.close(fig)
        return p

    def _plot_imm_error_from_trajectory(df: pd.DataFrame) -> Path | None:
        sub = df[(df["variant"] == "SpoofingAware") & (df["name"].str.contains("imm_(true|est)_[xyz]_m", na=False))]
        sub = _clean_imm_sub(sub)
        if sub.empty:
            return None
        scenarios = sorted(sub["scenario"].dropna().unique().tolist())
        if not scenarios:
            return None
        n = len(scenarios)
        fig, axes = plt.subplots(1, n, figsize=(5.2 * n, 4.2), squeeze=False)
        for i, scen in enumerate(scenarios):
            ax = axes[0][i]
            ss = sub[sub["scenario"] == scen]
            err_frames: list[pd.DataFrame] = []
            for src in ss["source_file"].dropna().unique():
                run = ss[ss["source_file"] == src]
                ex = run[run["name"] == "imm_est_x_m"].groupby("time", as_index=False)["value"].mean()
                ey = run[run["name"] == "imm_est_y_m"].groupby("time", as_index=False)["value"].mean()
                ez = run[run["name"] == "imm_est_z_m"].groupby("time", as_index=False)["value"].mean()
                tx = run[run["name"] == "imm_true_x_m"].groupby("time", as_index=False)["value"].mean()
                ty = run[run["name"] == "imm_true_y_m"].groupby("time", as_index=False)["value"].mean()
                tz = run[run["name"] == "imm_true_z_m"].groupby("time", as_index=False)["value"].mean()
                if ex.empty or ey.empty or tx.empty or ty.empty:
                    continue
                est = ex.rename(columns={"value": "ex"}).merge(
                    ey.rename(columns={"value": "ey"}), on="time", how="inner"
                )
                tru = tx.rename(columns={"value": "tx"}).merge(
                    ty.rename(columns={"value": "ty"}), on="time", how="inner"
                )
                merged = est.merge(tru, on="time", how="inner")
                if not ez.empty and not tz.empty:
                    ez2 = ez.rename(columns={"value": "ez"})
                    tz2 = tz.rename(columns={"value": "tz"})
                    merged = merged.merge(ez2, on="time", how="inner").merge(tz2, on="time", how="inner")
                    merged["err"] = np.sqrt(
                        (merged["ex"] - merged["tx"]) ** 2
                        + (merged["ey"] - merged["ty"]) ** 2
                        + (merged["ez"] - merged["tz"]) ** 2
                    )
                else:
                    merged["err"] = np.sqrt(
                        (merged["ex"] - merged["tx"]) ** 2 + (merged["ey"] - merged["ty"]) ** 2
                    )
                if merged.empty:
                    continue
                err_frames.append(merged[["time", "err"]])
            if not err_frames:
                continue
            err_long = pd.concat(err_frames, ignore_index=True)
            agg = err_long.groupby("time", as_index=False).agg(mean=("err", "mean"), std=("err", "std"))
            agg["std"] = agg["std"].fillna(0.0)
            ax.fill_between(
                agg["time"],
                agg["mean"] - agg["std"],
                agg["mean"] + agg["std"],
                alpha=0.22,
                color="#1f77b4",
                linewidth=0,
            )
            ax.plot(agg["time"], agg["mean"], color="#1f77b4", linewidth=1.7, label="IMM trajectory error")
            ax.set_title(str(scen))
            ax.set_xlabel("time (s)")
            ax.set_ylabel("error (m)")
            ax.grid(alpha=0.2)
            ax.legend(fontsize=8)
        fig.suptitle("SpoofingAware IMM Position Error from True vs Estimated Trajectory (mean ± std across seeds)")
        fig.tight_layout()
        p = out_dir / "timeseries_imm_error_norm_mean_std.pdf"
        p = _save_figure_dual(fig, p, dpi=220)
        plt.close(fig)
        return p

    def _plot_localization_and_bubble_by_scenario(df: pd.DataFrame) -> Path | None:
        variants = ["SpoofingAware", "SpoofingAwareInstantDetect"]
        containment = df[
            (df["variant"].isin(variants))
            & (df["name"].str.contains("spoofer_containment_rate", na=False))
        ]
        loc = df[
            (df["variant"].isin(variants))
            & (df["name"].str.contains("localization_rmse_m", na=False))
        ]
        bubble = df[
            (df["variant"].isin(variants))
            & (df["name"].str.contains("unsafe_radius_max_m", na=False))
        ]
        if containment.empty or loc.empty or bubble.empty:
            return None
        scenarios = sorted(
            set(containment["scenario"].dropna())
            & set(loc["scenario"].dropna())
            & set(bubble["scenario"].dropna())
        )
        if not scenarios:
            return None
        n = len(scenarios)
        fig, axes = plt.subplots(3, n, figsize=(5.8 * n, 8.6), squeeze=False, sharex="col")
        row1_vals: list[float] = []
        row2_vals: list[float] = []
        row3_vals: list[float] = []
        for i, scen in enumerate(scenarios):
            ax_cont = axes[0][i]
            ax_loc = axes[1][i]
            ax_bub = axes[2][i]

            containment_s = containment[containment["scenario"] == scen]
            loc_s = loc[loc["scenario"] == scen]
            bubble_s = bubble[bubble["scenario"] == scen]
            if containment_s.empty and loc_s.empty and bubble_s.empty:
                continue

            for variant in variants:
                color = VARIANT_COLORS.get(variant, "#1f77b4")
                style = VARIANT_LINESTYLES.get(variant, "-")

                containment_v = containment_s[containment_s["variant"] == variant]
                if not containment_v.empty:
                    ca = containment_v.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                    ca["std"] = ca["std"].fillna(0.0)
                    ax_cont.fill_between(
                        ca["time"],
                        ca["mean"] - ca["std"],
                        ca["mean"] + ca["std"],
                        alpha=0.22,
                        color=color,
                        linewidth=0,
                    )
                    ax_cont.plot(
                        ca["time"],
                        ca["mean"],
                        color=color,
                        linestyle=style,
                        linewidth=2.0,
                        label=variant,
                    )
                    row1_vals.extend((ca["mean"] - ca["std"]).tolist())
                    row1_vals.extend((ca["mean"] + ca["std"]).tolist())

                loc_v = loc_s[loc_s["variant"] == variant]
                if not loc_v.empty:
                    la = loc_v.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                    la["std"] = la["std"].fillna(0.0)
                    ax_loc.fill_between(
                        la["time"],
                        la["mean"] - la["std"],
                        la["mean"] + la["std"],
                        alpha=0.22,
                        color=color,
                        linewidth=0,
                    )
                    ax_loc.plot(
                        la["time"],
                        la["mean"],
                        color=color,
                        linestyle=style,
                        linewidth=2.0,
                        label=variant,
                    )
                    row2_vals.extend((la["mean"] - la["std"]).tolist())
                    row2_vals.extend((la["mean"] + la["std"]).tolist())

                bubble_v = bubble_s[bubble_s["variant"] == variant]
                if not bubble_v.empty:
                    ba = bubble_v.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                    ba["std"] = ba["std"].fillna(0.0)
                    ax_bub.fill_between(
                        ba["time"],
                        ba["mean"] - ba["std"],
                        ba["mean"] + ba["std"],
                        alpha=0.22,
                        color=color,
                        linewidth=0,
                    )
                    ax_bub.plot(
                        ba["time"],
                        ba["mean"],
                        color=color,
                        linestyle=style,
                        linewidth=2.0,
                        label=variant,
                    )
                    row3_vals.extend((ba["mean"] - ba["std"]).tolist())
                    row3_vals.extend((ba["mean"] + ba["std"]).tolist())

            ax_cont.set_title(str(scen))
            ax_cont.set_ylabel("containment rate")
            ax_cont.set_ylim(-0.02, 1.02)
            ax_cont.grid(alpha=0.25)

            ax_loc.set_ylabel("localization RMSE (m)")
            ax_loc.grid(alpha=0.25)

            ax_bub.set_ylabel("unsafe bubble radius max (m)")
            ax_bub.set_xlabel("time (s)")
            ax_bub.grid(alpha=0.25)

            if i == 0:
                handles, labels = ax_cont.get_legend_handles_labels()
                if handles:
                    ax_cont.legend(handles, labels, fontsize=8, loc="best")

        ylim_loc = _safe_axis_limits(row2_vals)
        ylim_bub = _safe_axis_limits(row3_vals)
        for i in range(n):
            axes[0][i].set_ylim(-0.02, 1.02)
            if ylim_loc is not None:
                axes[1][i].set_ylim(*ylim_loc)
            if ylim_bub is not None:
                axes[2][i].set_ylim(*ylim_bub)

        fig.suptitle(
            "Containment, Localization RMSE, and Unsafe-Bubble Radius Through Time (mean ± std)"
        )
        fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.97])
        p = out_dir / "timeseries_containment_localization_unsafe_bubble_mean_std.pdf"
        p = _save_figure_dual(fig, p, dpi=220)
        plt.close(fig)
        return p

    p = _plot_by_scenario(
        long_df,
        metric_pattern="min_benign_spoofer_distance_now_m",
        title="Min Benign-Spoofer Distance Through Time (mean ± std, by Scenario)",
        ylabel="distance (m)",
        out_name="timeseries_min_distance_mean_std.pdf",
        variants=["SpoofingAware", "SpoofingAwareInstantDetect", "TrustRID"],
        hline=NMAC_THRESHOLD_M,
        hline_label=f"NMAC threshold ({int(NMAC_THRESHOLD_M)} m)",
    )
    if p is not None:
        out_paths.append(p)

    # Detection quality summary (best-effort from available vectors).
    aware = long_df[long_df["variant"] == "SpoofingAware"].copy()
    if not aware.empty:
        det_rows: list[list[str]] = []
        scen_order = sorted(aware["scenario"].dropna().unique().tolist())
        for scen in scen_order:
            ss = aware[aware["scenario"] == scen]
            a = ss[ss["name"] == "combined_alert"][["source_file", "time", "value"]].copy()
            d = ss[ss["name"] == "spoofer_detected"][["source_file", "time", "value"]].copy()
            if a.empty or d.empty:
                continue
            a["time"] = pd.to_numeric(a["time"], errors="coerce")
            a["value"] = pd.to_numeric(a["value"], errors="coerce")
            d["time"] = pd.to_numeric(d["time"], errors="coerce")
            d["value"] = pd.to_numeric(d["value"], errors="coerce")
            a = a.dropna()
            d = d.dropna()
            if a.empty or d.empty:
                continue
            runs = sorted(set(a["source_file"].astype(str).unique().tolist()) & set(d["source_file"].astype(str).unique().tolist()))
            if not runs:
                continue
            detected_runs = 0
            pre_detect_false_fracs: list[float] = []
            first_alert_times: list[float] = []
            for src in runs:
                aa = a[a["source_file"] == src].sort_values("time")
                dd = d[d["source_file"] == src].sort_values("time")
                det_pos = dd[dd["value"] > 0.5]
                alert_pos = aa[aa["value"] > 0.5]
                if not det_pos.empty:
                    detected_runs += 1
                    t_det = float(det_pos["time"].iloc[0])
                    pre = aa[aa["time"] < t_det]
                    if not pre.empty:
                        pre_detect_false_fracs.append(float((pre["value"] > 0.5).mean()))
                if not alert_pos.empty:
                    first_alert_times.append(float(alert_pos["time"].iloc[0]))
            det_rate = float(detected_runs) / float(len(runs))
            pre_false = float(np.mean(pre_detect_false_fracs)) if pre_detect_false_fracs else float("nan")
            first_alert_mean = float(np.mean(first_alert_times)) if first_alert_times else float("nan")
            first_alert_std = _safe_std(np.asarray(first_alert_times, dtype=float)) if len(first_alert_times) > 1 else 0.0
            if not first_alert_times:
                first_alert_std = float("nan")
            det_rows.append(
                [
                    str(scen),
                    _fmt_table_value(len(runs)),
                    _fmt_table_value(det_rate),
                    _fmt_table_value(first_alert_mean),
                    _fmt_table_value(first_alert_std),
                    _fmt_table_value(pre_false),
                    "FP/FN precision/recall require explicit per-report truth labels (not logged).",
                ]
            )
        if det_rows:
            p_det_csv = out_dir / "table_vii_detection_quality_summary.csv"
            pd.DataFrame(
                det_rows,
                columns=[
                    "Scenario",
                    "Runs",
                    "Detection success rate",
                    "First alert mean (s)",
                    "First alert std (s)",
                    "False-alert fraction before detection (proxy)",
                    "Notes",
                ],
            ).to_csv(p_det_csv, index=False)
            out_paths.append(p_det_csv)
            p_det_pdf = _save_table_pdf(
                plt=plt,
                rows=det_rows,
                headers=[
                    "Scenario",
                    "Runs",
                    "Detection\nsuccess",
                    "First alert\nmean (s)",
                    "First alert\nstd (s)",
                    "Pre-detect\nfalse-alert frac",
                    "Notes",
                ],
                title="TABLE VII",
                subtitle="Detection quality summary (SpoofingAware, vector-derived)",
                out_path=out_dir / "table_vii_detection_quality_summary.pdf",
            )
            if p_det_pdf is not None:
                out_paths.append(p_det_pdf)

    # NMAC-by-time charts (cumulative event counts) only in full profile.
    if plot_profile == "full":
        nmac_timeseries_specs = [
            (
                "nmac_proximity_total",
                "Benign-Benign NMACs Through Time (mean ± std, by Scenario)",
                "cumulative benign-benign NMAC count",
                "timeseries_nmac_benign_benign_mean_std.pdf",
                ["SpoofingAware", "SpoofingAwareInstantDetect", "TrustRID"],
            ),
            (
                "nmac_benign_spoofer_total",
                "Benign-Spoofer NMACs Through Time (mean ± std, by Scenario)",
                "cumulative benign-spoofer NMAC count",
                "timeseries_nmac_benign_spoofer_mean_std.pdf",
                ["SpoofingAware", "SpoofingAwareInstantDetect", "TrustRID"],
            ),
            (
                "nmac_spoofer_unsafe_total",
                "SpoofingAware Unsafe-Region NMACs Through Time (mean ± std, by Scenario)",
                "cumulative unsafe-region NMAC count",
                "timeseries_nmac_spoofer_unsafe_mean_std.pdf",
                ["SpoofingAware", "SpoofingAwareInstantDetect", "TrustRID"],
            ),
        ]
        for metric_pattern, title, ylabel, out_name, variants in nmac_timeseries_specs:
            p = _plot_by_scenario(
                long_df,
                metric_pattern=metric_pattern,
                title=title,
                ylabel=ylabel,
                out_name=out_name,
                variants=variants,
            )
            if p is not None:
                out_paths.append(p)

    p = _plot_detection_timing(long_df)
    if p is not None:
        out_paths.append(p)

    if plot_profile == "full":
        p = _plot_imm_true_vs_estimated_xy(long_df)
        if p is not None:
            out_paths.append(p)

        p = _plot_imm_error_from_trajectory(long_df)
        if p is not None:
            out_paths.append(p)

        p = _plot_imm_mode_probabilities(long_df)
        if p is not None:
            out_paths.append(p)

        p = _plot_by_scenario(
            long_df,
            metric_pattern="imm_nis_mix",
            title="SpoofingAware IMM NIS Through Time (mean ± std, by Scenario)",
            ylabel="NIS (3 dof)",
            out_name="timeseries_imm_nis_mean_std.pdf",
            variants=["SpoofingAware"],
            hlines=[
                (CHI2_3DOF_95_LO, "--", "chi2 95% lower"),
                (CHI2_3DOF_95_HI, "--", "chi2 95% upper"),
            ],
        )
        if p is not None:
            out_paths.append(p)

        p = _plot_by_scenario(
            long_df,
            metric_pattern="imm_nees",
            title="SpoofingAware IMM NEES Through Time (mean ± std, by Scenario)",
            ylabel="NEES (3 dof)",
            out_name="timeseries_imm_nees_mean_std.pdf",
            variants=["SpoofingAware"],
            hlines=[
                (CHI2_3DOF_95_LO, "--", "chi2 95% lower"),
                (CHI2_3DOF_95_HI, "--", "chi2 95% upper"),
            ],
        )
        if p is not None:
            out_paths.append(p)

    p = _plot_localization_and_bubble_by_scenario(long_df)
    if p is not None:
        out_paths.append(p)

    if plot_profile == "full":
        p = _write_imm_diagnostics_table(long_df)
        if p is not None:
            out_paths.append(p)

    # Cleanup stale redundant charts that are now intentionally removed.
    for stale_name in [
        "summary_boxplots.png",
        "runtime_compare_scenarios_aware_vs_trustrid.png",
        "timeseries_min_distance_median.png",
        "timeseries_imm_mode_probabilities_median.png",
        "timeseries_imm_true_vs_estimated_xy_median.png",
        "timeseries_imm_error_norm_median.png",
        "timeseries_imm_nis_median.png",
        "timeseries_imm_nees_median.png",
        "timeseries_containment_localization_unsafe_bubble_median.png",
        "timeseries_nmac_benign_benign_median.png",
        "timeseries_nmac_benign_spoofer_median.png",
        "timeseries_nmac_spoofer_unsafe_median.png",
        "timeseries_containment_rate_median.png",
        "timeseries_localization_error_median.png",
        "timeseries_unsafe_bubble_radius_median.png",
        "runtime_scalability_hub.png",
    ]:
        stale = out_dir / stale_name
        if stale.exists():
            stale.unlink()

    return out_paths


PALETTE_3D = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78", "#98df8a", "#ff9896", "#c5b0d5",
]


def _variant_from_parquet_name(name: str) -> str | None:
    if "_AwareInstantDetect" in name:
        return "SpoofingAwareInstantDetect"
    if "_Aware" in name:
        return "SpoofingAware"
    if "_TrustRid" in name:
        return "TrustRID"
    return None


def _load_3d_tx_points(parquet_path: Path, sample_every: int = 3) -> pd.DataFrame:
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
        step_mask = (tx.groupby("serial_number").cumcount() % sample_every) == 0
        tx = tx[step_mask].copy()
    return tx


def _collect_generated_parquets(generated_dir: Path) -> dict[str, dict[str, list[Path]]]:
    groups: dict[str, dict[str, list[Path]]] = defaultdict(
        lambda: {"SpoofingAware": [], "SpoofingAwareInstantDetect": [], "TrustRID": []}
    )
    for scen_dir in sorted(generated_dir.iterdir()):
        if not scen_dir.is_dir() or not (scen_dir / "omnetpp.ini").is_file():
            continue
        group = _scenario_group_from_tag(scen_dir.name)
        for p in sorted(scen_dir.glob("*.parquet")):
            variant = _variant_from_parquet_name(p.name)
            if variant is None:
                continue
            if variant not in groups[group]:
                groups[group][variant] = []
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


def _plot_3d_group(group: str, by_variant: dict[str, list[Path]], out_dir: Path, sample_every: int) -> Path | None:
    import matplotlib.pyplot as plt

    variants = ["SpoofingAware", "SpoofingAwareInstantDetect", "TrustRID"]
    if all(len(by_variant.get(v, [])) == 0 for v in variants):
        return None

    fig = plt.figure(figsize=(21.0, 6.8))
    axs = [fig.add_subplot(1, 3, i + 1, projection="3d") for i in range(3)]
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
                tx = _load_3d_tx_points(pq, sample_every=sample_every)
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
            color_map = {s: PALETTE_3D[i % len(PALETTE_3D)] for i, s in enumerate(serials)}
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
        handles, _labels = ax.get_legend_handles_labels()
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
    out = _save_figure_dual(fig, out, dpi=240)
    plt.close(fig)
    return out


def _make_3d_overlay_charts(generated_dir: Path, out_dir: Path, sample_every: int) -> list[Path]:
    out_paths: list[Path] = []
    if not generated_dir.is_dir():
        return out_paths
    groups = _collect_generated_parquets(generated_dir)
    for group in sorted(groups.keys()):
        p = _plot_3d_group(group, groups[group], out_dir=out_dir, sample_every=sample_every)
        if p is not None:
            out_paths.append(p)
    return out_paths


_MOVETO_RE = re.compile(r"<moveto x=['\"]([^'\"]+)['\"] y=['\"]([^'\"]+)['\"] z=['\"]([^'\"]+)['\"]")


def _extract_run_metadata_from_sca(sca_path: Path) -> tuple[dict[int, np.ndarray], set[int]]:
    """Return goals keyed by serial number, and the set of spoofer serials."""
    goals_by_host: dict[int, np.ndarray] = {}
    serial_by_host: dict[int, int] = {}
    spoofer_hosts: set[int] = set()
    try:
        lines = sca_path.read_text().splitlines()
    except Exception:
        return {}, set()
    for ln in lines:
        s = ln.strip()
        if (
            s.startswith("config *.host[")
            and ".mobility.waypointScript " in s
            and 'xml(\\"' in s
            and s.endswith('\\")"')
        ):
            try:
                host = int(s.split("config *.host[", 1)[1].split("]", 1)[0])
                xml = s.split('xml(\\"', 1)[1].rsplit('\\")"', 1)[0]
            except Exception:
                continue
            movetos = _MOVETO_RE.findall(xml)
            if not movetos:
                continue
            gx, gy, gz = movetos[-1]
            try:
                goals_by_host[host] = np.array([float(gx), float(gy), float(gz)], dtype=float)
            except Exception:
                continue
            continue

        if s.startswith("par BasicUav.host[") and ".wlan[0].mgmt serialNumber " in s:
            try:
                host = int(s.split("par BasicUav.host[", 1)[1].split("]", 1)[0])
                serial = int(s.rsplit(" ", 1)[1])
                serial_by_host[host] = serial
            except Exception:
                pass
            continue

        if s.startswith("par BasicUav.host[") and ".wlan[0].mgmt pyTxClass " in s and "Spoofer" in s:
            try:
                host = int(s.split("par BasicUav.host[", 1)[1].split("]", 1)[0])
                spoofer_hosts.add(host)
            except Exception:
                pass
            continue

    goals_by_serial: dict[int, np.ndarray] = {}
    for host, goal in goals_by_host.items():
        serial = serial_by_host.get(host)
        if serial is None:
            continue
        goals_by_serial[serial] = goal

    spoofer_serials = {serial_by_host[h] for h in spoofer_hosts if h in serial_by_host}
    return goals_by_serial, spoofer_serials


def _variant_from_parquet_basename(name: str) -> str | None:
    if "_AwareInstantDetect" in name:
        return "SpoofingAwareInstantDetect"
    if "_Aware" in name:
        return "SpoofingAware"
    if "_TrustRid" in name:
        return "TrustRID"
    return None


def _make_mission_progress_tables(generated_dir: Path, out_dir: Path, goal_tol_m: float = 10.0) -> list[Path]:
    import matplotlib.pyplot as plt

    out_paths: list[Path] = []
    if not generated_dir.is_dir():
        return out_paths

    run_rows: list[dict] = []
    for scen_dir in sorted(generated_dir.iterdir()):
        if not scen_dir.is_dir():
            continue
        scen_group = _scenario_group_from_tag(scen_dir.name)
        for pq in sorted(scen_dir.glob("*.parquet")):
            variant = _variant_from_parquet_basename(pq.name)
            if variant is None:
                continue
            sca = pq.with_suffix(".sca")
            goals, spoofer_serials = _extract_run_metadata_from_sca(sca)
            if not goals:
                continue
            try:
                df = pd.read_parquet(pq)
            except Exception:
                continue
            need = {"event_type", "time", "serial_number", "pos_x", "pos_y", "pos_z"}
            if not need.issubset(set(df.columns)):
                continue
            tx = df[df["event_type"] == "TX"].copy()
            if tx.empty:
                continue
            tx["serial_number"] = pd.to_numeric(tx["serial_number"], errors="coerce")
            tx["time"] = pd.to_numeric(tx["time"], errors="coerce")
            tx = tx.dropna(subset=["serial_number", "time", "pos_x", "pos_y", "pos_z"])
            if tx.empty:
                continue
            tx["serial_number"] = tx["serial_number"].astype(int)
            serials = sorted(tx["serial_number"].unique().tolist())
            if not serials:
                continue
            benign_serials = [s for s in serials if s not in spoofer_serials]
            if not benign_serials:
                # Fallback for malformed metadata: preserve previous assumption.
                benign_serials = [s for s in serials if s != max(serials)]
            eligible_serials = [s for s in benign_serials if s in goals]
            if not eligible_serials:
                continue
            success_count = 0
            per_host_ttg: list[float] = []
            per_host_final_dist: list[float] = []
            for s in eligible_serials:
                g = tx[tx["serial_number"] == s].sort_values("time")
                if g.empty:
                    continue
                goal = goals[s]
                pxyz = g[["pos_x", "pos_y", "pos_z"]].to_numpy(dtype=float)
                dists = np.linalg.norm(pxyz - goal.reshape(1, 3), axis=1)
                per_host_final_dist.append(float(dists[-1]))
                reached_idx = np.where(dists <= goal_tol_m)[0]
                if reached_idx.size > 0:
                    success_count += 1
                    per_host_ttg.append(float(g["time"].iloc[int(reached_idx[0])]))
            denom = max(1, len(eligible_serials))
            run_rows.append(
                {
                    "scenario": scen_group,
                    "run_tag": scen_dir.name,
                    "variant": variant,
                    "mission_success_rate": float(success_count) / float(denom),
                    "time_to_goal_mean_s": (float(np.mean(per_host_ttg)) if per_host_ttg else float("nan")),
                    "final_goal_distance_mean_m": (
                        float(np.mean(per_host_final_dist)) if per_host_final_dist else float("nan")
                    ),
                }
            )

    if not run_rows:
        return out_paths

    runs_df = pd.DataFrame(run_rows)
    p_runs = out_dir / "mission_progress_by_run.csv"
    runs_df.to_csv(p_runs, index=False)
    out_paths.append(p_runs)

    table_rows: list[list[str]] = []
    for scen in sorted(runs_df["scenario"].dropna().unique().tolist()):
        sa = runs_df[(runs_df["scenario"] == scen) & (runs_df["variant"] == "SpoofingAware")]
        tr = runs_df[(runs_df["scenario"] == scen) & (runs_df["variant"] == "TrustRID")]
        if sa.empty and tr.empty:
            continue
        sa_sr_vals = pd.to_numeric(sa["mission_success_rate"], errors="coerce").dropna().to_numpy(dtype=float)
        tr_sr_vals = pd.to_numeric(tr["mission_success_rate"], errors="coerce").dropna().to_numpy(dtype=float)
        sa_sr = float(np.mean(sa_sr_vals)) if sa_sr_vals.size > 0 else float("nan")
        tr_sr = float(np.mean(tr_sr_vals)) if tr_sr_vals.size > 0 else float("nan")
        sa_sr_std = _safe_std(sa_sr_vals) if sa_sr_vals.size > 0 else float("nan")
        tr_sr_std = _safe_std(tr_sr_vals) if tr_sr_vals.size > 0 else float("nan")
        sa_ttg_vals = pd.to_numeric(sa["time_to_goal_mean_s"], errors="coerce").dropna().to_numpy(dtype=float)
        tr_ttg_vals = pd.to_numeric(tr["time_to_goal_mean_s"], errors="coerce").dropna().to_numpy(dtype=float)
        sa_ttg = float(np.mean(sa_ttg_vals)) if sa_ttg_vals.size > 0 else float("nan")
        tr_ttg = float(np.mean(tr_ttg_vals)) if tr_ttg_vals.size > 0 else float("nan")
        sa_ttg_std = _safe_std(sa_ttg_vals) if sa_ttg_vals.size > 0 else float("nan")
        tr_ttg_std = _safe_std(tr_ttg_vals) if tr_ttg_vals.size > 0 else float("nan")
        sa_fd_vals = pd.to_numeric(sa["final_goal_distance_mean_m"], errors="coerce").dropna().to_numpy(dtype=float)
        tr_fd_vals = pd.to_numeric(tr["final_goal_distance_mean_m"], errors="coerce").dropna().to_numpy(dtype=float)
        sa_fd = float(np.mean(sa_fd_vals)) if sa_fd_vals.size > 0 else float("nan")
        tr_fd = float(np.mean(tr_fd_vals)) if tr_fd_vals.size > 0 else float("nan")
        sa_fd_std = _safe_std(sa_fd_vals) if sa_fd_vals.size > 0 else float("nan")
        tr_fd_std = _safe_std(tr_fd_vals) if tr_fd_vals.size > 0 else float("nan")
        table_rows.append(
            [
                scen,
                _fmt_table_value(sa_sr),
                _fmt_table_value(sa_sr_std),
                _fmt_table_value(tr_sr),
                _fmt_table_value(tr_sr_std),
                _fmt_table_value(sa_ttg),
                _fmt_table_value(sa_ttg_std),
                _fmt_table_value(tr_ttg),
                _fmt_table_value(tr_ttg_std),
                _fmt_table_value(sa_fd),
                _fmt_table_value(sa_fd_std),
                _fmt_table_value(tr_fd),
                _fmt_table_value(tr_fd_std),
            ]
        )
    if table_rows:
        p_csv = out_dir / "table_viii_mission_progress_summary.csv"
        pd.DataFrame(
            table_rows,
            columns=[
                "Scenario",
                "Mission success rate mean (SA)",
                "Mission success rate std (SA)",
                "Mission success rate mean (Trust-RID)",
                "Mission success rate std (Trust-RID)",
                "Time-to-goal mean SA (s)",
                "Time-to-goal std SA (s)",
                "Time-to-goal mean Trust-RID (s)",
                "Time-to-goal std Trust-RID (s)",
                "Final distance-to-goal mean SA (m)",
                "Final distance-to-goal std SA (m)",
                "Final distance-to-goal mean Trust-RID (m)",
                "Final distance-to-goal std Trust-RID (m)",
            ],
        ).to_csv(p_csv, index=False)
        out_paths.append(p_csv)
        p_pdf = _save_table_pdf(
            plt=plt,
            rows=table_rows,
            headers=[
                "Scenario",
                "Success\nmean SA",
                "Success\nstd SA",
                "Success\nmean TR",
                "Success\nstd TR",
                "TTG\nmean SA",
                "TTG\nstd SA",
                "TTG\nmean TR",
                "TTG\nstd TR",
                "Dist\nmean SA",
                "Dist\nstd SA",
                "Dist\nmean TR",
                "Dist\nstd TR",
            ],
            title="TABLE VIII",
            subtitle=f"Mission-progress summary (goal tolerance = {goal_tol_m:g} m)",
            out_path=out_dir / "table_viii_mission_progress_summary.pdf",
        )
        if p_pdf is not None:
            out_paths.append(p_pdf)
    return out_paths


def _export_keycharts(out_dir: Path, written: list[Path]) -> list[Path]:
    """
    Copy core paper artifacts into charts/keycharts for quick access.
    """
    key_dir = out_dir / "keycharts"
    key_dir.mkdir(parents=True, exist_ok=True)

    key_names = {
        "summary_boxplots.pdf",
        "summary_means_table.csv",
        "summary_distribution_table.csv",
        "runtime_compare_scenarios_aware_vs_trustrid.pdf",
        "timeseries_min_distance_mean_std.pdf",
        "timeseries_containment_localization_unsafe_bubble_mean_std.pdf",
        "detection_first_time_by_scenario.pdf",
        "table_ii_nmac_summary_statistics.pdf",
        "table_ii_nmac_summary_statistics.csv",
        "table_iii_runtime_mean_std_per_scenario_seconds.pdf",
        "table_iii_runtime_mean_std_per_scenario_seconds.csv",
        "table_iv_effect_size_sa_vs_trustrid.pdf",
        "table_iv_effect_size_sa_vs_trustrid.csv",
        "table_v_containment_calibration.pdf",
        "table_v_containment_calibration.csv",
        "table_vi_compute_breakdown_by_scenario.pdf",
        "table_vi_compute_breakdown_by_scenario.csv",
        "table_vii_detection_quality_summary.pdf",
        "table_vii_detection_quality_summary.csv",
        "table_viii_mission_progress_summary.pdf",
        "table_viii_mission_progress_summary.csv",
        "mission_progress_by_run.csv",
    }

    copied: list[Path] = []
    for p in written:
        if not p.is_file():
            continue
        if p.name in key_names:
            dst = key_dir / p.name
            shutil.copy2(p, dst)
            copied.append(dst)
            if p.suffix.lower() == ".pdf":
                png_src = p.parent.parent / "pngs" / f"{p.stem}.png"
                if png_src.is_file():
                    png_dst = key_dir / png_src.name
                    shutil.copy2(png_src, png_dst)
                    copied.append(png_dst)

    # Include all generated 3D trajectory overlays as key artifacts.
    for p in sorted((out_dir / "pdfs").glob("trajectory_overlay_3d_*.pdf")):
        dst = key_dir / p.name
        shutil.copy2(p, dst)
        copied.append(dst)
        png_src = out_dir / "pngs" / f"{p.stem}.png"
        if png_src.is_file():
            png_dst = key_dir / png_src.name
            shutil.copy2(png_src, png_dst)
            copied.append(png_dst)

    return copied


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate batch charts from summary and GCS vectors.")
    ap.add_argument(
        "--batch-root",
        type=Path,
        default=Path("simulations/spoofing_aware_with_planning/batches"),
        help="Batch root containing summary.csv and optionally gcs_vectors/",
    )
    ap.add_argument(
        "--summary-csv",
        type=Path,
        default=None,
        help="Override summary CSV path (default: <batch-root>/summary.csv)",
    )
    ap.add_argument(
        "--gcs-vectors-dir",
        type=Path,
        default=None,
        help="Override GCS vector CSV directory (default: <batch-root>/gcs_vectors)",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: <batch-root>/charts)",
    )
    ap.add_argument(
        "--generated-dir",
        type=Path,
        default=None,
        help="Generated run directory for 3D overlays (default: <batch-root>/generated)",
    )
    ap.add_argument(
        "--sample-every-3d",
        type=int,
        default=3,
        help="Downsample TX points per serial in 3D overlays (1=all).",
    )
    ap.add_argument(
        "--no-3d",
        action="store_true",
        help="Disable 3D trajectory overlay generation.",
    )
    ap.add_argument(
        "--plot-profile",
        choices=["paper", "full"],
        default="paper",
        help="paper: concise core figures/tables, full: include all detailed diagnostics.",
    )
    ap.add_argument(
        "--mission-goal-tol-m",
        type=float,
        default=10.0,
        help="Goal distance threshold (m) for mission-progress success summaries.",
    )
    args = ap.parse_args()

    batch_root = args.batch_root.resolve()
    summary_csv = (args.summary_csv or (batch_root / "summary.csv")).resolve()
    gcs_vectors_dir = (args.gcs_vectors_dir or (batch_root / "gcs_vectors")).resolve()
    generated_dir = (args.generated_dir or (batch_root / "generated")).resolve()
    out_dir = (args.out_dir or (batch_root / "charts")).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.sample_every_3d < 1:
        raise ValueError("--sample-every-3d must be >= 1")

    if not summary_csv.is_file():
        raise FileNotFoundError(f"summary CSV not found: {summary_csv}")

    written = []
    written.extend(_make_summary_charts(summary_csv, out_dir))

    if gcs_vectors_dir.is_dir():
        long_df = _load_gcs_vector_long(gcs_vectors_dir)
        written.extend(_make_timeseries_charts(long_df, out_dir, plot_profile=args.plot_profile))
    written.extend(_make_mission_progress_tables(generated_dir, out_dir, goal_tol_m=float(args.mission_goal_tol_m)))
    if not args.no_3d and args.sample_every_3d >= 1:
        written.extend(_make_3d_overlay_charts(generated_dir, out_dir, sample_every=args.sample_every_3d))

    keycharts = _export_keycharts(out_dir, written)
    written.extend(keycharts)

    print("Wrote files:")
    for p in written:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
