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
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

NMAC_THRESHOLD_M = 50.0
CHI2_3DOF_95_LO = 0.21579528262389785
CHI2_3DOF_95_HI = 9.348403604496148


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
    return "TrustRID" if "TrustRid" in name else ("SpoofingAware" if "Aware" in name else "Unknown")


_SEED_SUFFIX_RE = re.compile(r"_s\d+$")


def _scenario_group_from_tag(tag: str) -> str:
    return _SEED_SUFFIX_RE.sub("", str(tag))


def _scenario_group_from_source_file(name: str) -> str:
    # e.g. "hub_8x1_s00000-Scenario_Hub_8x1_s00000_Aware-#0-gcs.csv"
    prefix = str(name).split("-", 1)[0]
    return _SEED_SUFFIX_RE.sub("", prefix)


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
        (
            "detection_reports_total",
            "SpoofingAware: detection reports processed",
            "detection_reports_total_aware",
            None,
        ),
        (
            "detection_mlat_attempted",
            "SpoofingAware: detection callbacks with MLAT attempted",
            "detection_mlat_attempted_aware",
            None,
        ),
        (
            "detection_mlat_skipped_insufficient_receivers",
            "SpoofingAware: detection callbacks skipped (receivers < 4)",
            "detection_mlat_skipped_insufficient_receivers_aware",
            None,
        ),
        (
            "detection_mlat_skip_fraction",
            "SpoofingAware: skipped MLAT fraction during detection",
            "detection_mlat_skipped_insufficient_receivers_fraction_aware",
            None,
        ),
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
        ("detection_reports_total_aware", "SpoofingAware: detection reports processed"),
        ("detection_mlat_attempted_aware", "SpoofingAware: detection callbacks with MLAT attempted"),
        (
            "detection_mlat_skipped_insufficient_receivers_aware",
            "SpoofingAware: detection callbacks skipped (receivers < 4)",
        ),
        (
            "detection_mlat_skipped_insufficient_receivers_fraction_aware",
            "SpoofingAware: skipped MLAT fraction during detection",
        ),
    ]

    # Boxplots across seeds: paired + SpoofingAware-only metrics.
    n_plots = len(paired_metrics) + len(aware_only_metrics)
    n_cols = 3
    n_rows = max(1, int(math.ceil(float(n_plots) / float(n_cols))))
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5.0 * n_cols, 4.0 * n_rows))
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
    while idx < len(axes):
        axes[idx].axis("off")
        idx += 1
    fig.suptitle("Safety Metrics Across Seeds")
    fig.tight_layout()
    p = out_dir / "summary_boxplots.pdf"
    fig.savefig(p, dpi=220)
    plt.close(fig)
    out_paths.append(p)

    # Keep summary_means_table.csv for downstream analysis, but stop generating
    # summary_means.png because it duplicates summary_boxplots.png information.
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
        (
            "SpoofingAware: detection reports processed",
            "detection_reports_total_aware",
            None,
        ),
        (
            "SpoofingAware: detection callbacks with MLAT attempted",
            "detection_mlat_attempted_aware",
            None,
        ),
        (
            "SpoofingAware: detection callbacks skipped (receivers < 4)",
            "detection_mlat_skipped_insufficient_receivers_aware",
            None,
        ),
        (
            "SpoofingAware: skipped MLAT fraction during detection",
            "detection_mlat_skipped_insufficient_receivers_fraction_aware",
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

    stale_summary_means_png = out_dir / "summary_means.png"
    if stale_summary_means_png.exists():
        stale_summary_means_png.unlink()

    # Runtime comparison across scenarios: SpoofingAware vs TrustRID.
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
                and "elapsed_trust_rid_seconds" in rt_file.columns
            ):
                rt = rt_file.copy()
        except Exception:
            rt = None

    if rt is not None and "scenario" in rt.columns:
        scenarios = sorted(rt["scenario"].dropna().unique().tolist())
        if scenarios:
            aware_meds: list[float] = []
            aware_err_lo: list[float] = []
            aware_err_hi: list[float] = []
            trust_meds: list[float] = []
            trust_err_lo: list[float] = []
            trust_err_hi: list[float] = []
            labels: list[str] = []
            for scen in scenarios:
                ss = rt[rt["scenario"] == scen]
                aware_vals = pd.to_numeric(ss["elapsed_aware_seconds"], errors="coerce").dropna().to_numpy(dtype=float)
                trust_vals = pd.to_numeric(ss["elapsed_trust_rid_seconds"], errors="coerce").dropna().to_numpy(dtype=float)
                if aware_vals.size == 0 or trust_vals.size == 0:
                    continue
                a_q1 = float(np.quantile(aware_vals, 0.25))
                a_med = float(np.quantile(aware_vals, 0.5))
                a_q3 = float(np.quantile(aware_vals, 0.75))
                t_q1 = float(np.quantile(trust_vals, 0.25))
                t_med = float(np.quantile(trust_vals, 0.5))
                t_q3 = float(np.quantile(trust_vals, 0.75))

                labels.append(scen.replace("Scenario_", "").replace("_", " "))
                aware_meds.append(a_med)
                aware_err_lo.append(a_med - a_q1)
                aware_err_hi.append(a_q3 - a_med)
                trust_meds.append(t_med)
                trust_err_lo.append(t_med - t_q1)
                trust_err_hi.append(t_q3 - t_med)

            if labels:
                x = np.arange(len(labels))
                width = 0.38
                fig, ax = plt.subplots(figsize=(12.5, 5.5))
                ax.bar(
                    x - width / 2,
                    aware_meds,
                    width=width,
                    yerr=[aware_err_lo, aware_err_hi],
                    capsize=3,
                    label="SpoofingAware",
                    color="#4c78a8",
                )
                ax.bar(
                    x + width / 2,
                    trust_meds,
                    width=width,
                    yerr=[trust_err_lo, trust_err_hi],
                    capsize=3,
                    label="TrustRID",
                    color="#f58518",
                )
                ax.set_xticks(x)
                ax.set_xticklabels(labels, rotation=20, ha="right")
                ax.set_ylabel(runtime_label)
                ax.set_title("Runtime by Scenario: SpoofingAware vs TrustRID (median with IQR)")
                ax.grid(axis="y", alpha=0.2)
                ax.legend()
                fig.tight_layout()
                p = out_dir / "runtime_compare_scenarios_aware_vs_trustrid.pdf"
                fig.savefig(p, dpi=220)
                plt.close(fig)
                out_paths.append(p)

    # Detection MLAT coverage by scenario (aware only): median with IQR.
    if "tag" in df.columns and "detection_mlat_skipped_insufficient_receivers_fraction_aware" in df.columns:
        dd = df.copy()
        dd["scenario"] = dd["tag"].apply(_scenario_group_from_tag)
        scenarios = sorted(dd["scenario"].dropna().unique().tolist())
        labels: list[str] = []
        medians: list[float] = []
        err_lo: list[float] = []
        err_hi: list[float] = []
        for scen in scenarios:
            ss = dd[dd["scenario"] == scen]
            vals = pd.to_numeric(
                ss["detection_mlat_skipped_insufficient_receivers_fraction_aware"],
                errors="coerce",
            ).dropna().to_numpy(dtype=float)
            if vals.size == 0:
                continue
            q1 = float(np.quantile(vals, 0.25))
            med = float(np.quantile(vals, 0.5))
            q3 = float(np.quantile(vals, 0.75))
            labels.append(scen.replace("Scenario_", "").replace("_", " "))
            medians.append(med)
            err_lo.append(max(0.0, med - q1))
            err_hi.append(max(0.0, q3 - med))

        if labels:
            x = np.arange(len(labels))
            fig, ax = plt.subplots(figsize=(max(10.0, 1.5 * len(labels)), 5.0))
            ax.bar(
                x,
                medians,
                yerr=[err_lo, err_hi],
                capsize=3,
                color="#4c78a8",
            )
            ax.set_xticks(x)
            ax.set_xticklabels(labels, rotation=20, ha="right")
            ax.set_ylabel("fraction of detection callbacks skipped")
            ax.set_ylim(0.0, 1.0)
            ax.set_title("Detection MLAT Skip Fraction by Scenario (median with IQR)")
            ax.grid(axis="y", alpha=0.2)
            fig.tight_layout()
            p = out_dir / "detection_mlat_skip_fraction_by_scenario.pdf"
            fig.savefig(p, dpi=220)
            plt.close(fig)
            out_paths.append(p)

    # Cleanup stale runtime chart that is now intentionally removed.
    stale_runtime_scalability = out_dir / "runtime_scalability_hub.png"
    if stale_runtime_scalability.exists():
        stale_runtime_scalability.unlink()

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


def _make_timeseries_charts(long_df: pd.DataFrame, out_dir: Path) -> list[Path]:
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
                    "imm_error_median_m": float(err.median()) if not err.empty else float("nan"),
                    "imm_nees_median": float(nees.median()) if not nees.empty else float("nan"),
                    "imm_nees_in_95pct_fraction": (
                        float(((nees >= CHI2_3DOF_95_LO) & (nees <= CHI2_3DOF_95_HI)).mean())
                        if not nees.empty else float("nan")
                    ),
                    "imm_nis_median": float(nis.median()) if not nis.empty else float("nan"),
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
        fig, axes = plt.subplots(1, n, figsize=(5.0 * n, 4.2), squeeze=False)
        for i, scen in enumerate(scenarios):
            ax = axes[0][i]
            ss = sub[sub["scenario"] == scen]
            for variant in variants:
                g = ss[ss["variant"] == variant]
                if g.empty:
                    continue
                med = g.groupby("time", as_index=False)["value"].median()
                ax.plot(med["time"], med["value"], label=variant)
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
        fig.suptitle(title)
        fig.tight_layout()
        p = out_dir / out_name
        fig.savefig(p, dpi=220)
        plt.close(fig)
        return p

    def _plot_detection_timing(df: pd.DataFrame) -> Path | None:
        # Use spoofing-aware-only vectors to extract first detection time per run.
        # Prefer spoofer_detected; fall back to combined_alert if needed.
        aware = df[df["variant"] == "SpoofingAware"].copy()
        if aware.empty:
            return None
        aware["name"] = aware["name"].astype(str)
        metric = "spoofer_detected"
        if not (aware["name"] == metric).any():
            metric = "combined_alert"
            if not (aware["name"] == metric).any():
                return None

        sub = aware[aware["name"] == metric].copy()
        sub["value"] = pd.to_numeric(sub["value"], errors="coerce")
        sub["time"] = pd.to_numeric(sub["time"], errors="coerce")
        sub = sub.dropna(subset=["value", "time", "source_file", "scenario"])
        if sub.empty:
            return None

        rows: list[dict] = []
        grouped = sub.sort_values(["source_file", "time"]).groupby(["scenario", "source_file"], as_index=False)
        for (scen, src), g in grouped:
            detected = g[g["value"] > 0.5]
            rows.append(
                {
                    "scenario": str(scen),
                    "source_file": str(src),
                    "first_detection_time_s": (
                        float(detected["time"].iloc[0]) if not detected.empty else float("nan")
                    ),
                }
            )
        det_df = pd.DataFrame(rows)
        if det_df.empty:
            return None

        # Save underlying per-run table for traceability.
        det_csv = out_dir / "detection_first_time_by_run.csv"
        det_df.to_csv(det_csv, index=False)
        out_paths.append(det_csv)

        # Plot distribution across runs for each scenario.
        scen_order = sorted(det_df["scenario"].dropna().unique().tolist())
        data = [
            pd.to_numeric(
                det_df.loc[det_df["scenario"] == s, "first_detection_time_s"], errors="coerce"
            ).dropna().to_numpy(dtype=float)
            for s in scen_order
        ]
        if all(len(v) == 0 for v in data):
            return None

        fig, ax = plt.subplots(figsize=(max(8.0, 1.7 * len(scen_order)), 4.6))
        ax.boxplot(data, labels=scen_order)
        ax.set_title("SpoofingAware First Detection Time by Scenario")
        ax.set_ylabel("first detection time (s)")
        ax.set_xlabel("scenario")
        ax.grid(axis="y", alpha=0.2)
        for tick in ax.get_xticklabels():
            tick.set_rotation(20)
            tick.set_ha("right")
        fig.tight_layout()
        p = out_dir / "detection_first_time_by_scenario.pdf"
        fig.savefig(p, dpi=220)
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
                med = g.groupby("time", as_index=False)["value"].median()
                ax.plot(med["time"], med["value"], label=label, color=color)
            ax.set_title(str(scen))
            ax.set_xlabel("time (s)")
            ax.set_ylabel("probability")
            ax.set_ylim(-0.02, 1.02)
            ax.grid(alpha=0.2)
            ax.legend(fontsize=8)
        fig.suptitle("SpoofingAware IMM Mode Probabilities Through Time (Median)")
        fig.tight_layout()
        p = out_dir / "timeseries_imm_mode_probabilities_median.pdf"
        fig.savefig(p, dpi=220)
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
            ex = ss[ss["name"] == "imm_est_x_m"].groupby("time", as_index=False)["value"].median()
            ey = ss[ss["name"] == "imm_est_y_m"].groupby("time", as_index=False)["value"].median()
            tx = ss[ss["name"] == "imm_true_x_m"].groupby("time", as_index=False)["value"].median()
            ty = ss[ss["name"] == "imm_true_y_m"].groupby("time", as_index=False)["value"].median()
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
        fig.suptitle("SpoofingAware IMM: True vs Estimated XY Trajectory (Median)")
        fig.tight_layout()
        p = out_dir / "timeseries_imm_true_vs_estimated_xy_median.pdf"
        fig.savefig(p, dpi=220)
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
            ex = ss[ss["name"] == "imm_est_x_m"].groupby("time", as_index=False)["value"].median()
            ey = ss[ss["name"] == "imm_est_y_m"].groupby("time", as_index=False)["value"].median()
            ez = ss[ss["name"] == "imm_est_z_m"].groupby("time", as_index=False)["value"].median()
            tx = ss[ss["name"] == "imm_true_x_m"].groupby("time", as_index=False)["value"].median()
            ty = ss[ss["name"] == "imm_true_y_m"].groupby("time", as_index=False)["value"].median()
            tz = ss[ss["name"] == "imm_true_z_m"].groupby("time", as_index=False)["value"].median()
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
            ax.plot(merged["time"], merged["err"], color="#1f77b4", linewidth=1.7, label="IMM trajectory error")
            ax.set_title(str(scen))
            ax.set_xlabel("time (s)")
            ax.set_ylabel("error (m)")
            ax.grid(alpha=0.2)
            ax.legend(fontsize=8)
        fig.suptitle("SpoofingAware IMM Position Error from True vs Estimated Trajectory (Median)")
        fig.tight_layout()
        p = out_dir / "timeseries_imm_error_norm_median.pdf"
        fig.savefig(p, dpi=220)
        plt.close(fig)
        return p

    def _plot_localization_and_bubble_by_scenario(df: pd.DataFrame) -> Path | None:
        containment = df[
            (df["variant"] == "SpoofingAware")
            & (df["name"].str.contains("spoofer_containment_rate", na=False))
        ]
        loc = df[
            (df["variant"] == "SpoofingAware")
            & (df["name"].str.contains("localization_rmse_m", na=False))
        ]
        bubble = df[
            (df["variant"] == "SpoofingAware")
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
        fig, axes = plt.subplots(1, n, figsize=(5.6 * n, 4.2), squeeze=False)
        for i, scen in enumerate(scenarios):
            ax = axes[0][i]
            containment_s = containment[containment["scenario"] == scen]
            loc_s = loc[loc["scenario"] == scen]
            bubble_s = bubble[bubble["scenario"] == scen]
            if containment_s.empty or loc_s.empty or bubble_s.empty:
                continue
            containment_med = containment_s.groupby("time", as_index=False)["value"].median()
            loc_med = loc_s.groupby("time", as_index=False)["value"].median()
            bubble_med = bubble_s.groupby("time", as_index=False)["value"].median()

            line1 = ax.plot(
                containment_med["time"],
                containment_med["value"],
                color="#2ca02c",
                linewidth=1.7,
                label="Containment rate median",
            )[0]
            ax.set_xlabel("time (s)")
            ax.set_ylabel("containment rate", color="#2ca02c")
            ax.tick_params(axis="y", labelcolor="#2ca02c")
            ax.set_ylim(-0.02, 1.02)
            ax.grid(alpha=0.2)

            ax2 = ax.twinx()
            line2 = ax2.plot(
                loc_med["time"],
                loc_med["value"],
                color="#1f77b4",
                linewidth=1.7,
                label="Localization RMSE median (m)",
            )[0]
            line3 = ax2.plot(
                bubble_med["time"],
                bubble_med["value"],
                color="#ff7f0e",
                linewidth=1.7,
                label="Unsafe bubble radius max median (m)",
            )[0]
            ax2.set_ylabel("meters", color="#1f77b4")
            ax2.tick_params(axis="y", labelcolor="#1f77b4")

            ax.set_title(str(scen))
            ax.legend(
                [line1, line2, line3],
                [line1.get_label(), line2.get_label(), line3.get_label()],
                fontsize=8,
                loc="best",
            )

        fig.suptitle(
            "SpoofingAware Containment (left) and Localization/Bubble Metrics (right) Through Time (Median)"
        )
        fig.tight_layout()
        p = out_dir / "timeseries_containment_localization_unsafe_bubble_median.pdf"
        fig.savefig(p, dpi=220)
        plt.close(fig)
        return p

    p = _plot_by_scenario(
        long_df,
        metric_pattern="min_benign_spoofer_distance_now_m",
        title="Min Benign-Spoofer Distance Through Time (Median, by Scenario)",
        ylabel="distance (m)",
        out_name="timeseries_min_distance_median.pdf",
        variants=["SpoofingAware", "TrustRID"],
        hline=NMAC_THRESHOLD_M,
        hline_label=f"NMAC threshold ({int(NMAC_THRESHOLD_M)} m)",
    )
    if p is not None:
        out_paths.append(p)

    # NMAC-by-time charts (cumulative event counts).
    nmac_timeseries_specs = [
        (
            "nmac_proximity_total",
            "Benign-Benign NMACs Through Time (Median, by Scenario)",
            "cumulative benign-benign NMAC count",
            "timeseries_nmac_benign_benign_median.pdf",
            ["SpoofingAware", "TrustRID"],
        ),
        (
            "nmac_benign_spoofer_total",
            "Benign-Spoofer NMACs Through Time (Median, by Scenario)",
            "cumulative benign-spoofer NMAC count",
            "timeseries_nmac_benign_spoofer_median.pdf",
            ["SpoofingAware", "TrustRID"],
        ),
        (
            "nmac_spoofer_unsafe_total",
            "SpoofingAware Unsafe-Region NMACs Through Time (Median, by Scenario)",
            "cumulative unsafe-region NMAC count",
            "timeseries_nmac_spoofer_unsafe_median.pdf",
            ["SpoofingAware"],
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

    p = _plot_imm_true_vs_estimated_xy(long_df)
    if p is not None:
        out_paths.append(p)

    p = _plot_detection_timing(long_df)
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
        title="SpoofingAware IMM NIS Through Time (Median, by Scenario)",
        ylabel="NIS (3 dof)",
        out_name="timeseries_imm_nis_median.pdf",
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
        title="SpoofingAware IMM NEES Through Time (Median, by Scenario)",
        ylabel="NEES (3 dof)",
        out_name="timeseries_imm_nees_median.pdf",
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
        tx = tx.groupby("serial_number", group_keys=False).apply(
            lambda g: g.iloc[::sample_every]
        )
    return tx


def _collect_generated_parquets(generated_dir: Path) -> dict[str, dict[str, list[Path]]]:
    groups: dict[str, dict[str, list[Path]]] = defaultdict(
        lambda: {"SpoofingAware": [], "TrustRID": []}
    )
    for scen_dir in sorted(generated_dir.iterdir()):
        if not scen_dir.is_dir() or not (scen_dir / "omnetpp.ini").is_file():
            continue
        group = _scenario_group_from_tag(scen_dir.name)
        for p in sorted(scen_dir.glob("*.parquet")):
            variant = _variant_from_parquet_name(p.name)
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


def _plot_3d_group(group: str, by_variant: dict[str, list[Path]], out_dir: Path, sample_every: int) -> Path | None:
    import matplotlib.pyplot as plt

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
    fig.savefig(out, dpi=240)
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
        written.extend(_make_timeseries_charts(long_df, out_dir))
    if not args.no_3d and args.sample_every_3d >= 1:
        written.extend(_make_3d_overlay_charts(generated_dir, out_dir, sample_every=args.sample_every_3d))

    print("Wrote files:")
    for p in written:
        print(f"  - {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
