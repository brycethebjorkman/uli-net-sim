#!/usr/bin/env python3
"""Create paper-only charts for InstantDetect@5s vs TrustRID.

Formatting is intentionally aligned with plot_batch.py paper plots.
"""

from __future__ import annotations

import argparse
import math
import re
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


NMAC_THRESHOLD_M = 50.0
VARIANTS = ["SpoofingAwareInstantDetect", "TrustRID"]
VARIANT_COLORS = {
    "SpoofingAwareInstantDetect": "#54a24b",
    "TrustRID": "#f58518",
}
VARIANT_LINESTYLES = {
    "SpoofingAwareInstantDetect": "-",
    "TrustRID": "-",
}
VARIANT_DISPLAY_NAMES = {
    "SpoofingAwareInstantDetect": "Spoofing Aware",
    "TrustRID": "TrustRID",
}

# Core table/figure basenames expected for paper packaging.
TABLE_BASENAMES = [
    "table_ii_nmac_summary_statistics",
    "table_iii_runtime_mean_std_per_scenario_seconds",
]
OPTIONAL_TABLE_BASENAMES = [
    "table_iv_effect_size_sa_vs_trustrid",
    "table_v_containment_calibration",
    "table_vi_compute_breakdown_by_scenario",
    "table_vii_detection_quality_summary",
    "table_viii_mission_progress_summary",
]
OPTIONAL_FIGURE_BASENAMES: list[str] = []
_SEED_SUFFIX_RE = re.compile(r"_s\d+$")


def _variant_display_name(name: str) -> str:
    return VARIANT_DISPLAY_NAMES.get(name, name)


def _scenario_group_from_tag(tag: str) -> str:
    return _SEED_SUFFIX_RE.sub("", str(tag))


def _scenario_group_from_source_file(name: str) -> str:
    # e.g. "depotcity_8x1_s00000-Scenario_DepotCity_8x1_s00000_TrustRid-#0-gcs.csv"
    prefix = str(name).split("-", 1)[0]
    return _SEED_SUFFIX_RE.sub("", prefix)


def _variant_from_name(name: str) -> str:
    if "TrustRid" in name:
        return "TrustRID"
    if "AwareInstantDetect" in name:
        return "SpoofingAwareInstantDetect"
    if "Aware" in name:
        return "SpoofingAware"
    return "Unknown"


def _safe_std(vals: np.ndarray) -> float:
    vals = np.asarray(vals, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size <= 1:
        return 0.0
    return float(np.std(vals, ddof=1))


def _fmt_pm(mu: float, sd: float) -> str:
    if not (math.isfinite(mu) and math.isfinite(sd)):
        return "N/A"
    return f"{mu:.3f} ± {sd:.3f}"


def _save_table_df(
    df: pd.DataFrame,
    title: str,
    out_pdf: Path,
    out_png: Path,
    *,
    bold_metric_rows: frozenset[str] | None = None,
) -> None:
    headers = [str(c) for c in df.columns.tolist()]
    rows = df.values.tolist()
    n_cols = max(1, len(headers))
    max_text_len = max(
        [len(h) for h in headers] + [len(str(cell)) for row in rows for cell in row]
    )
    fig_w = max(12.8, 1.6 * n_cols + 0.035 * max_text_len)
    fig_h = max(2.8, 0.42 * len(df) + 1.8)
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
    table.set_fontsize(9.8)
    table.scale(1.0, 1.28)
    try:
        table.auto_set_column_width(col=list(range(n_cols)))
    except Exception:
        pass
    for (r, _c), cell in table.get_celld().items():
        cell.set_text_props(wrap=True)
        if r == 0:
            cell.set_text_props(weight="bold")
            cell.set_facecolor("#eeeeee")
        elif bold_metric_rows is not None and 1 <= r <= len(rows):
            metric = str(rows[r - 1][0]).strip()
            if metric in bold_metric_rows:
                cell.set_text_props(weight="bold")
    fig.suptitle(title, y=0.98, fontsize=13)
    fig.tight_layout(rect=[0.01, 0.01, 0.99, 0.94])
    fig.savefig(out_pdf, dpi=240)
    fig.savefig(out_png, dpi=240)
    plt.close(fig)


def _write_split_agent_count_tables(run_root: Path, out_dir: Path) -> list[str]:
    summary_csv = run_root / "summary.csv"
    if not summary_csv.is_file():
        return []
    s = pd.read_csv(summary_csv)
    if "tag" not in s.columns:
        return []
    s["scenario"] = s["tag"].apply(_scenario_group_from_tag)
    scenarios = sorted(
        s["scenario"].dropna().unique().tolist(),
        key=lambda x: int(str(x).split("_")[2].replace("x1", "")) if "depotcity_" in str(x).lower() else 0,
    )
    if not scenarios:
        return []

    scenario_labels = []
    for scen in scenarios:
        name = str(scen).replace("Scenario_", "").lower()
        if "depotcity_" in name and "x1" in name:
            n = name.split("depotcity_")[1].split("x1")[0]
            scenario_labels.append(f"{n} Agents")
        else:
            scenario_labels.append(name)

    # Table II: safety (SA vs RID per scenario).
    safety_specs = [
        ("Total NMACs", "nmac_proximity_aware_instant_detect", "nmac_benign_spoofer_aware_instant_detect", "nmac_proximity_trust_rid", "nmac_benign_spoofer_trust_rid"),
        ("Benign-Benign", "nmac_proximity_aware_instant_detect", None, "nmac_proximity_trust_rid", None),
        ("Benign-Spoofer", "nmac_benign_spoofer_aware_instant_detect", None, "nmac_benign_spoofer_trust_rid", None),
        ("Unsafe violations", "nmac_spoofer_unsafe_aware_instant_detect", None, None, None),
    ]
    safety_rows: list[dict[str, str]] = []
    for metric, sa_col, sa_col2, tr_col, tr_col2 in safety_specs:
        row: dict[str, str] = {"Metric": metric}
        for scen, slbl in zip(scenarios, scenario_labels):
            ss = s[s["scenario"] == scen]
            sa_v = pd.to_numeric(ss[sa_col], errors="coerce")
            if sa_col2 is not None:
                sa_v = sa_v + pd.to_numeric(ss[sa_col2], errors="coerce")
            sa_vals = sa_v.dropna().to_numpy(dtype=float)
            row[f"{slbl} (SA)"] = _fmt_pm(float(np.mean(sa_vals)) if sa_vals.size else float("nan"), _safe_std(sa_vals))

            if tr_col is None:
                row[f"{slbl} (RID)"] = "N/A"
            else:
                tr_v = pd.to_numeric(ss[tr_col], errors="coerce")
                if tr_col2 is not None:
                    tr_v = tr_v + pd.to_numeric(ss[tr_col2], errors="coerce")
                tr_vals = tr_v.dropna().to_numpy(dtype=float)
                row[f"{slbl} (RID)"] = _fmt_pm(float(np.mean(tr_vals)) if tr_vals.size else float("nan"), _safe_std(tr_vals))
        safety_rows.append(row)
    safety_df = pd.DataFrame(safety_rows)
    safety_base = "table_ii_safety_summary_by_agent_count"
    safety_df.to_csv(out_dir / f"{safety_base}.csv", index=False)
    _save_table_df(
        safety_df,
        "TABLE II\nSafety summary statistics by agent count (mean ± std across 30 seeds).",
        out_dir / "pdfs" / f"{safety_base}.pdf",
        out_dir / "pngs" / f"{safety_base}.png",
        bold_metric_rows=frozenset({"Benign-Spoofer"}),
    )

    # Table III: localization (SA only per scenario).
    localization_specs = [
        ("Spoofer containment rate", "spoofer_containment_rate_aware_instant_detect"),
        ("Raw RSSI NLLS Multilateration spoofer x error vs ground truth (m)", "localization_mlat_raw_mae_m_aware_instant_detect"),
        ("Predicted spoofer $\\mu$ error vs ground truth (RMSE, m)", "localization_rmse_m_aware_instant_detect"),
        ("Predicted spoofer $\\mu$ error vs ground truth (MAE, m)", "localization_mae_m_aware_instant_detect"),
    ]
    loc_rows: list[dict[str, str]] = []
    for metric, col in localization_specs:
        row = {"Metric": metric}
        for scen, slbl in zip(scenarios, scenario_labels):
            ss = s[s["scenario"] == scen]
            vals = pd.to_numeric(ss[col], errors="coerce").dropna().to_numpy(dtype=float) if col in ss.columns else np.array([])
            row[f"{slbl} (SA)"] = _fmt_pm(float(np.mean(vals)) if vals.size else float("nan"), _safe_std(vals))
        loc_rows.append(row)

    # Add unsafe ellipsoid radius from timeseries as per-run mean ± std across seeds.
    long_csv = run_root / "charts" / "gcs_timeseries_long.csv"
    if long_csv.is_file():
        long_df = pd.read_csv(long_csv, usecols=["source_file", "scenario", "variant", "name", "value"])
        long_df["value"] = pd.to_numeric(long_df["value"], errors="coerce")
        unsafe = long_df[
            (long_df["variant"] == "SpoofingAwareInstantDetect")
            & (long_df["name"].astype(str).str.contains("unsafe_radius_max_m", na=False))
        ].dropna(subset=["value"])
        unsafe_row = {"Metric": "Spoofer unsafe ellipsoid radius max (m)"}
        for scen, slbl in zip(scenarios, scenario_labels):
            scen_norm = str(scen).replace("Scenario_", "").lower()
            us = unsafe[unsafe["scenario"].astype(str).str.lower() == scen_norm]
            if us.empty:
                unsafe_row[f"{slbl} (SA)"] = "N/A"
                continue
            per_run_means = us.groupby("source_file", as_index=False)["value"].mean()["value"].to_numpy(dtype=float)
            unsafe_row[f"{slbl} (SA)"] = _fmt_pm(
                float(np.mean(per_run_means)) if per_run_means.size else float("nan"),
                _safe_std(per_run_means),
            )
        loc_rows.append(unsafe_row)
    loc_df = pd.DataFrame(loc_rows)
    loc_base = "table_iii_spoofer_localization_by_agent_count"
    loc_df.to_csv(out_dir / f"{loc_base}.csv", index=False)
    _save_table_df(
        loc_df,
        "TABLE III\nSpoofer localization statistics by agent count for Spoofing-Aware (mean ± std across 30 seeds).",
        out_dir / "pdfs" / f"{loc_base}.pdf",
        out_dir / "pngs" / f"{loc_base}.png",
    )
    return [safety_base, loc_base]


def _apply_paper_style() -> None:
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


def _safe_axis_limits(values: list[float], pad_frac: float = 0.06) -> tuple[float, float] | None:
    vals = [float(v) for v in values if pd.notna(v)]
    if not vals:
        return None
    lo = min(vals)
    hi = max(vals)
    if lo == hi:
        pad = max(1.0, abs(lo) * 0.1)
        return lo - pad, hi + pad
    span = hi - lo
    pad = span * float(pad_frac)
    return lo - pad, hi + pad


def _safe_positive_ylim(
    values: list[float],
    pad_frac: float = 0.18,
    min_top_pad: float = 8.0,
    min_top_mult: float = 1.35,
) -> tuple[float, float] | None:
    vals = [float(v) for v in values if pd.notna(v)]
    if not vals:
        return None
    lo = min(vals)
    hi = max(vals)
    if lo == hi:
        pad = max(float(min_top_pad), abs(hi) * 0.15, 1.0)
        top = max(hi + pad, hi * float(min_top_mult) if hi > 0.0 else hi + pad)
        return max(0.0, lo - 0.1 * pad), top
    span = hi - lo
    pad = max(float(min_top_pad), span * float(pad_frac))
    top = max(hi + pad, hi * float(min_top_mult) if hi > 0.0 else hi + pad)
    return max(0.0, lo - 0.08 * pad), top


def _safe_shared_ylim(
    values: list[float],
    pad_frac: float = 0.30,
    min_pad: float = 8.0,
    top_mult: float = 1.35,
) -> tuple[float, float] | None:
    vals = [float(v) for v in values if pd.notna(v)]
    if not vals:
        return None
    lo = min(vals)
    hi = max(vals)
    if lo == hi:
        pad = max(float(min_pad), abs(hi) * 0.15, 1.0)
        top = max(hi + pad, hi * float(top_mult) if hi > 0.0 else hi + pad)
        return lo - 0.35 * pad, top
    span = hi - lo
    pad = max(float(min_pad), span * float(pad_frac))
    top = max(hi + pad, hi * float(top_mult) if hi > 0.0 else hi + pad)
    return lo - 0.28 * pad, top


def _bounded_band(mean: pd.Series, std: pd.Series, lower: float | None = None, upper: float | None = None) -> tuple[pd.Series, pd.Series]:
    lo = mean - std
    hi = mean + std
    if lower is not None:
        lo = lo.clip(lower=lower)
    if upper is not None:
        hi = hi.clip(upper=upper)
    return lo, hi


def _load_long_csv(run_root: Path) -> pd.DataFrame:
    long_csv = run_root / "charts" / "gcs_timeseries_long.csv"
    if long_csv.exists():
        df = pd.read_csv(long_csv)
    else:
        gcs_vectors_dir = run_root / "gcs_vectors"
        if not gcs_vectors_dir.is_dir():
            raise FileNotFoundError(
                f"Missing expected file: {long_csv} and fallback directory not found: {gcs_vectors_dir}"
            )
        df = _load_long_from_gcs_vectors(gcs_vectors_dir)
        if df.empty:
            raise ValueError(
                "No parseable rows found in gcs_vectors fallback; "
                f"checked directory: {gcs_vectors_dir}"
            )

    required = {"scenario", "variant", "time", "name", "value"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"gcs_timeseries_long.csv missing columns: {missing}")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    nonnegative_patterns = [
        "min_benign_spoofer_distance",
        "localization_rmse_m",
        "unsafe_radius_max_m",
        "nmac_",
        "detection_",
        "receiver_count",
        "mlat_receiver_count",
        "mlat_skipped_insufficient_receivers",
    ]
    nonneg_mask = df["name"].astype(str).str.contains("|".join(nonnegative_patterns), regex=True, na=False)
    df.loc[nonneg_mask & (df["value"] < 0.0), "value"] = float("nan")
    prob_mask = df["name"].astype(str).str.contains(
        "spoofer_containment_rate|combined_alert|spoofer_detected|imm_mode_prob_",
        regex=True,
        na=False,
    )
    df.loc[prob_mask & ((df["value"] < 0.0) | (df["value"] > 1.0)), "value"] = float("nan")
    df = df.dropna(subset=["value"])
    return df


def _load_long_from_gcs_vectors(gcs_vectors_dir: Path) -> pd.DataFrame:
    rows: list[dict] = []
    for p in sorted(gcs_vectors_dir.glob("*.csv")):
        try:
            df = pd.read_csv(p)
        except Exception:
            continue
        for _, r in df.iterrows():
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


def _plot_min_distance(df: pd.DataFrame, out_pdf: Path, out_png: Path) -> None:
    sub = df[
        df["name"].str.contains("min_benign_spoofer_distance_now_m", na=False)
        & df["variant"].isin(VARIANTS)
    ].copy()
    if sub.empty:
        raise ValueError("No rows found for metric: min_benign_spoofer_distance_now_m")

    scenarios = sorted(sub["scenario"].dropna().unique().tolist())
    if not scenarios:
        raise ValueError("No scenarios found in long dataframe.")
    fig, axes = plt.subplots(1, len(scenarios), figsize=(5.0 * len(scenarios), 4.2), squeeze=False, sharey=True)
    all_vals: list[float] = []

    for idx, scen in enumerate(scenarios):
        ax = axes[0][idx]
        scen_df = sub[sub["scenario"] == scen]
        for variant in VARIANTS:
            v = scen_df[scen_df["variant"] == variant]
            if v.empty:
                continue
            agg = v.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
            agg["std"] = agg["std"].fillna(0.0)
            color = VARIANT_COLORS.get(variant, "#777777")
            style = VARIANT_LINESTYLES.get(variant, "-")
            ax.fill_between(
                agg["time"],
                *_bounded_band(agg["mean"], agg["std"], lower=0.0),
                alpha=0.22,
                color=color,
                linewidth=0,
            )
            ax.plot(
                agg["time"],
                agg["mean"],
                linestyle=style,
                color=color,
                linewidth=1.9,
                label=_variant_display_name(variant),
            )
            all_vals.extend((agg["mean"] - agg["std"]).tolist())
            all_vals.extend((agg["mean"] + agg["std"]).tolist())
        ax.axhline(
            y=NMAC_THRESHOLD_M,
            color="crimson",
            linestyle="--",
            linewidth=1.1,
            label=f"NMAC threshold ({int(NMAC_THRESHOLD_M)} m)",
        )
        ax.set_title(str(scen))
        ax.set_xlabel("time (s)")
        ax.set_ylabel("distance (m)")
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8)

    # Keep per-scenario autoscaling for distance panels to avoid clipping
    # large scenario-specific std envelopes in shared paper figures.
    fig.suptitle(
        "Min Benign-Spoofer Distance Through Time (mean ± std, by Scenario)\n"
        "Note: benign hosts are excluded from this metric after reaching goal."
    )
    fig.tight_layout()
    fig.savefig(out_pdf, dpi=220)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def _plot_containment_rmse_unsafe(df: pd.DataFrame, out_pdf: Path, out_png: Path) -> None:
    containment = df[
        df["variant"].isin(VARIANTS)
        & df["name"].str.contains("spoofer_containment_rate", na=False)
    ]
    loc = df[
        df["variant"].isin(VARIANTS)
        & df["name"].str.contains("localization_rmse_m", na=False)
    ]
    bubble = df[
        df["variant"].isin(VARIANTS)
        & df["name"].str.contains("unsafe_radius_max_m", na=False)
    ]
    if containment.empty or loc.empty or bubble.empty:
        raise ValueError("Missing one or more required metrics for containment/RMSE/unsafe-radius plot.")

    scenarios = sorted(
        set(containment["scenario"].dropna())
        & set(loc["scenario"].dropna())
        & set(bubble["scenario"].dropna())
    )
    if not scenarios:
        raise ValueError("No overlapping scenarios for containment/RMSE/unsafe-radius plot.")

    n = len(scenarios)
    fig, axes = plt.subplots(3, n, figsize=(5.8 * n, 8.6), squeeze=False, sharex="col")
    row2_vals_by_scen: dict[str, list[float]] = {}
    row2_vals_all: list[float] = []
    row3_vals_by_scen: dict[str, list[float]] = {}

    for i, scen in enumerate(scenarios):
        ax_cont = axes[0][i]
        ax_loc = axes[1][i]
        ax_bub = axes[2][i]
        containment_s = containment[containment["scenario"] == scen]
        loc_s = loc[loc["scenario"] == scen]
        bubble_s = bubble[bubble["scenario"] == scen]

        for variant in VARIANTS:
            color = VARIANT_COLORS.get(variant, "#777777")
            style = VARIANT_LINESTYLES.get(variant, "-")

            containment_v = containment_s[containment_s["variant"] == variant]
            if not containment_v.empty:
                ca = containment_v.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                ca["std"] = ca["std"].fillna(0.0)
                ax_cont.fill_between(
                    ca["time"],
                    *_bounded_band(ca["mean"], ca["std"]),
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
                    label=_variant_display_name(variant),
                )

            loc_v = loc_s[loc_s["variant"] == variant]
            if not loc_v.empty:
                la = loc_v.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                la["std"] = la["std"].fillna(0.0)
                ax_loc.fill_between(
                    la["time"],
                    *_bounded_band(la["mean"], la["std"]),
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
                    label=_variant_display_name(variant),
                )
                row2_vals_by_scen.setdefault(str(scen), []).extend((la["mean"] - la["std"]).tolist())
                row2_vals_by_scen.setdefault(str(scen), []).extend((la["mean"] + la["std"]).tolist())
                row2_vals_all.extend((la["mean"] - la["std"]).tolist())
                row2_vals_all.extend((la["mean"] + la["std"]).tolist())

            bubble_v = bubble_s[bubble_s["variant"] == variant]
            if not bubble_v.empty:
                ba = bubble_v.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                ba["std"] = ba["std"].fillna(0.0)
                ax_bub.fill_between(
                    ba["time"],
                    *_bounded_band(ba["mean"], ba["std"], lower=0.0),
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
                    label=_variant_display_name(variant),
                )
                row3_vals_by_scen.setdefault(str(scen), []).extend((ba["mean"] - ba["std"]).tolist())
                row3_vals_by_scen.setdefault(str(scen), []).extend((ba["mean"] + ba["std"]).tolist())

        ax_cont.set_title(str(scen))
        ax_cont.set_ylabel("containment rate")
        ax_cont.set_ylim(-0.12, 1.12)
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

    ylim_loc_shared = _safe_shared_ylim(row2_vals_all, pad_frac=0.32, min_pad=16.0, top_mult=1.40)
    for i in range(n):
        axes[0][i].set_ylim(-0.12, 1.12)
        if ylim_loc_shared is not None:
            axes[1][i].set_ylim(ylim_loc_shared[0], ylim_loc_shared[1])
        scen = str(scenarios[i])
        ylim_bub = _safe_positive_ylim(row3_vals_by_scen.get(scen, []), pad_frac=0.20, min_top_pad=6.0)
        if ylim_bub is not None:
            axes[2][i].set_ylim(ylim_bub[0], ylim_bub[1])

    fig.suptitle("Containment, Localization RMSE, and Unsafe-Bubble Radius Through Time (mean ± std)")
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.97])
    fig.savefig(out_pdf, dpi=220)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def _plot_containment_rmse_only(df: pd.DataFrame, out_pdf: Path, out_png: Path) -> None:
    """Containment and RMSE only (no unsafe-radius panel)."""
    containment = df[
        df["variant"].isin(VARIANTS)
        & df["name"].str.contains("spoofer_containment_rate", na=False)
    ]
    loc = df[
        df["variant"].isin(VARIANTS)
        & df["name"].str.contains("localization_rmse_m", na=False)
    ]
    if containment.empty or loc.empty:
        raise ValueError("Missing containment or localization_rmse_m for containment/RMSE plot.")

    scenarios = sorted(set(containment["scenario"].dropna()) & set(loc["scenario"].dropna()))
    if not scenarios:
        raise ValueError("No overlapping scenarios for containment/RMSE plot.")

    n = len(scenarios)
    fig, axes = plt.subplots(2, n, figsize=(5.8 * n, 6.2), squeeze=False, sharex="col")
    row2_vals_by_scen: dict[str, list[float]] = {}
    row2_vals_all: list[float] = []

    for i, scen in enumerate(scenarios):
        ax_cont = axes[0][i]
        ax_loc = axes[1][i]
        containment_s = containment[containment["scenario"] == scen]
        loc_s = loc[loc["scenario"] == scen]

        for variant in VARIANTS:
            color = VARIANT_COLORS.get(variant, "#777777")
            style = VARIANT_LINESTYLES.get(variant, "-")

            containment_v = containment_s[containment_s["variant"] == variant]
            if not containment_v.empty:
                ca = containment_v.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                ca["std"] = ca["std"].fillna(0.0)
                ax_cont.fill_between(
                    ca["time"],
                    *_bounded_band(ca["mean"], ca["std"]),
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
                    label=_variant_display_name(variant),
                )

            loc_v = loc_s[loc_s["variant"] == variant]
            if not loc_v.empty:
                la = loc_v.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                la["std"] = la["std"].fillna(0.0)
                ax_loc.fill_between(
                    la["time"],
                    *_bounded_band(la["mean"], la["std"]),
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
                    label=_variant_display_name(variant),
                )
                row2_vals_by_scen.setdefault(str(scen), []).extend((la["mean"] - la["std"]).tolist())
                row2_vals_by_scen.setdefault(str(scen), []).extend((la["mean"] + la["std"]).tolist())
                row2_vals_all.extend((la["mean"] - la["std"]).tolist())
                row2_vals_all.extend((la["mean"] + la["std"]).tolist())

        ax_cont.set_title(str(scen))
        ax_cont.set_ylabel("containment rate")
        ax_cont.set_ylim(-0.12, 1.12)
        ax_cont.grid(alpha=0.25)
        ax_loc.set_ylabel("localization RMSE (m)")
        ax_loc.set_xlabel("time (s)")
        ax_loc.grid(alpha=0.25)
        if i == 0:
            handles, labels = ax_cont.get_legend_handles_labels()
            if handles:
                ax_cont.legend(handles, labels, fontsize=8, loc="best")

    ylim_loc_shared = _safe_shared_ylim(row2_vals_all, pad_frac=0.32, min_pad=16.0, top_mult=1.40)
    for i in range(n):
        axes[0][i].set_ylim(-0.12, 1.12)
        if ylim_loc_shared is not None:
            axes[1][i].set_ylim(ylim_loc_shared[0], ylim_loc_shared[1])

    fig.suptitle("Containment and Localization RMSE Through Time (mean ± std)")
    fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.97])
    fig.savefig(out_pdf, dpi=220)
    fig.savefig(out_png, dpi=220)
    plt.close(fig)


def _copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _copy_named_assets(run_root: Path, out_dir: Path, basenames: list[str]) -> list[str]:
    src_root = run_root / "charts"
    src_pdf_dirs = [src_root / "pdfs", src_root / "keycharts"]
    src_png_dirs = [src_root / "pngs", src_root / "keycharts"]
    dst_pdf = out_dir / "pdfs"
    dst_png = out_dir / "pngs"
    copied: list[str] = []

    for base in basenames:
        copied_any = False
        copied_any = _copy_if_exists(src_root / f"{base}.csv", out_dir / f"{base}.csv") or copied_any
        for d in src_pdf_dirs:
            copied_any = _copy_if_exists(d / f"{base}.pdf", dst_pdf / f"{base}.pdf") or copied_any
        for d in src_png_dirs:
            copied_any = _copy_if_exists(d / f"{base}.png", dst_png / f"{base}.png") or copied_any
        if copied_any:
            copied.append(base)
    return copied


def _copy_trajectory_overlays(run_root: Path, out_dir: Path) -> int:
    src_root = run_root / "charts"
    dst_pdf = out_dir / "pdfs"
    dst_png = out_dir / "pngs"
    copied = 0
    for p in sorted((src_root / "pdfs").glob("trajectory_overlay_3d_*.pdf")):
        copied += int(_copy_if_exists(p, dst_pdf / p.name))
    for p in sorted((src_root / "pngs").glob("trajectory_overlay_3d_*.png")):
        copied += int(_copy_if_exists(p, dst_png / p.name))
    return copied


def _resolve_run_roots(
    run_root: Path | None,
    paper_result_root: Path | None,
    run_id: str | None,
    process_all_runs: bool,
) -> list[Path]:
    if run_root is not None:
        return [run_root.resolve()]
    if paper_result_root is None:
        raise ValueError("Either --run-root or --paper-result-root must be provided.")
    root = paper_result_root.resolve()
    if process_all_runs:
        runs: list[Path] = []
        for p in sorted(root.iterdir()):
            if p.is_dir() and re.fullmatch(r"\d{4}", p.name):
                runs.append(p.resolve())
        if not runs:
            raise FileNotFoundError(f"No run directories (0001, 0002, ...) found under: {root}")
        return runs
    rid = run_id or "0001"
    candidate = root / rid
    if not candidate.is_dir():
        raise FileNotFoundError(f"Run directory not found: {candidate}")
    return [candidate.resolve()]


def _process_run_root(run_root: Path) -> None:
    out_dir = run_root / "variants" / "paper_instant_detect_vs_trustRID" / "charts"
    pdf_dir = out_dir / "pdfs"
    png_dir = out_dir / "pngs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    png_dir.mkdir(parents=True, exist_ok=True)

    _apply_paper_style()
    df = _load_long_csv(run_root)
    _plot_min_distance(
        df,
        pdf_dir / "timeseries_min_distance_median_instant_detect_vs_trustrid.pdf",
        png_dir / "timeseries_min_distance_median_instant_detect_vs_trustrid.png",
    )
    _plot_containment_rmse_unsafe(
        df,
        pdf_dir / "timeseries_containment_rmse_unsafe_median_instant_detect_vs_trustrid.pdf",
        png_dir / "timeseries_containment_rmse_unsafe_median_instant_detect_vs_trustrid.png",
    )
    _plot_containment_rmse_only(
        df,
        pdf_dir / "timeseries_containment_rmse_only_mean_std_instant_detect_vs_trustrid.pdf",
        png_dir / "timeseries_containment_rmse_only_mean_std_instant_detect_vs_trustrid.png",
    )
    split_tables = _write_split_agent_count_tables(run_root, out_dir)
    copied_required = _copy_named_assets(run_root, out_dir, TABLE_BASENAMES)
    copied_optional_tables: list[str] = []
    copied_optional_figures: list[str] = []
    copied_traj = 0

    manifest = out_dir / "README.txt"
    missing_required = [b for b in TABLE_BASENAMES if b not in copied_required]
    manifest.write_text(
        "Paper-only subset generated from charts/gcs_timeseries_long.csv\n"
        "Generated directly in this folder:\n"
        "- timeseries_min_distance_median_instant_detect_vs_trustrid\n"
        "- timeseries_containment_rmse_unsafe_median_instant_detect_vs_trustrid\n"
        "- timeseries_containment_rmse_only_mean_std_instant_detect_vs_trustrid\n"
        "\n"
        "Copied from run_root/charts when present:\n"
        f"- required tables copied: {', '.join(copied_required) if copied_required else 'none'}\n"
        f"- optional tables copied: {', '.join(copied_optional_tables) if copied_optional_tables else 'none'}\n"
        f"- optional figures copied: {', '.join(copied_optional_figures) if copied_optional_figures else 'none'}\n"
        f"- trajectory overlays copied: {copied_traj}\n"
        f"- split tables generated: {', '.join(split_tables) if split_tables else 'none'}\n"
        f"- required tables missing: {', '.join(missing_required) if missing_required else 'none'}\n"
        "\n"
        "Variants included:\n"
        "- Spoofing Aware (FORCE_DETECT_AT_S=5)\n"
        "- TrustRID\n",
        encoding="utf-8",
    )
    print(f"Wrote paper-only plots under: {out_dir}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=(
            "Generate paper-only variant charts (SpoofingAwareInstantDetect vs TrustRID) "
            "under variants/paper_instant_detect_vs_trustRID/charts."
        )
    )
    p.add_argument(
        "--run-root",
        default=None,
        help="Single run root directory (contains charts/, gcs_vectors/, summary.csv).",
    )
    p.add_argument(
        "--paper-result-root",
        default="simulations/spoofing_aware_with_planning/PAPER-RESULT-2",
        help="Root directory containing run folders (0001, 0002, ...).",
    )
    p.add_argument(
        "--run-id",
        default="0001",
        help="Run folder under --paper-result-root to process (default: 0001).",
    )
    p.add_argument(
        "--all-runs",
        action="store_true",
        help="Process every numeric run directory under --paper-result-root.",
    )
    args = p.parse_args()

    run_root_arg = Path(args.run_root).resolve() if args.run_root else None
    paper_result_root_arg = Path(args.paper_result_root).resolve() if args.paper_result_root else None

    run_roots = _resolve_run_roots(
        run_root=run_root_arg,
        paper_result_root=paper_result_root_arg,
        run_id=str(args.run_id) if args.run_id else None,
        process_all_runs=bool(args.all_runs),
    )
    for rr in run_roots:
        _process_run_root(rr)


if __name__ == "__main__":
    main()
