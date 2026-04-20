#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def _save_table(
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
        [len(h) for h in headers] +
        [len(str(cell)) for row in rows for cell in row]
    )
    fig_w = max(12.5, 1.65 * n_cols + 0.035 * max_text_len)
    fig, ax = plt.subplots(figsize=(fig_w, max(2.8, 0.42 * len(df) + 1.8)))
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


def _ylim_with_pad(values: list[float]) -> tuple[float, float] | None:
    arr = np.asarray([x for x in values if np.isfinite(x)], dtype=float)
    if arr.size == 0:
        return None
    lo = float(arr.min())
    hi = float(arr.max())
    pad = (hi - lo) * 0.06 if hi > lo else max(abs(hi), 1.0) * 0.05
    return lo - pad, hi + pad


_SEED_SUFFIX_RE = re.compile(r"_s\d+$")


def _scenario_group_from_tag(tag: str) -> str:
    return _SEED_SUFFIX_RE.sub("", str(tag))


def _safe_std(vals: np.ndarray) -> float:
    vals = np.asarray(vals, dtype=float)
    vals = vals[np.isfinite(vals)]
    if vals.size <= 1:
        return 0.0
    return float(np.std(vals, ddof=1))


def _mean_std(df: pd.DataFrame, col: str) -> tuple[float, float]:
    if col not in df.columns:
        return float("nan"), float("nan")
    vals = pd.to_numeric(df[col], errors="coerce").dropna().to_numpy(dtype=float)
    if vals.size == 0:
        return float("nan"), float("nan")
    return float(np.mean(vals)), _safe_std(vals)


def main() -> int:
    run_root = Path("simulations/spoofing_aware_with_planning/batchesPaperExact0005Commit/0002")
    charts = run_root / "charts"
    out = run_root / "variants" / "paper_instant_detect_vs_trustRID" / "charts"
    (out / "pdfs").mkdir(parents=True, exist_ok=True)
    (out / "pngs").mkdir(parents=True, exist_ok=True)

    # Table II: keep SA(detect@5s) vs TrustRID only.
    t2 = pd.read_csv(charts / "table_ii_nmac_summary_statistics.csv")
    t2n = t2[
        [
            "Metric",
            "Mean (SA InstantDetect)",
            "Mean (Trust-RID)",
            "Std (SA InstantDetect)",
            "Std (Trust-RID)",
        ]
    ].rename(
        columns={
            "Mean (SA InstantDetect)": "Mean (SA)",
            "Std (SA InstantDetect)": "Std (SA)",
        }
    )
    summary_csv = run_root / "summary.csv"
    if summary_csv.is_file():
        summary_df = pd.read_csv(summary_csv)
        raw_rmse_mu, raw_rmse_sd = _mean_std(summary_df, "localization_mlat_raw_rmse_m_aware_instant_detect")
        raw_mae_mu, raw_mae_sd = _mean_std(summary_df, "localization_mlat_raw_mae_m_aware_instant_detect")
        t2n = pd.concat(
            [
                t2n,
                pd.DataFrame(
                    [
                        {
                            "Metric": "SpoofingAware: raw RSSI/NLLS localization RMSE (m)",
                            "Mean (SA)": raw_rmse_mu,
                            "Mean (Trust-RID)": np.nan,
                            "Std (SA)": raw_rmse_sd,
                            "Std (Trust-RID)": np.nan,
                        },
                        {
                            "Metric": "SpoofingAware: raw RSSI/NLLS localization MAE (m)",
                            "Mean (SA)": raw_mae_mu,
                            "Mean (Trust-RID)": np.nan,
                            "Std (SA)": raw_mae_sd,
                            "Std (Trust-RID)": np.nan,
                        },
                    ]
                ),
            ],
            ignore_index=True,
        )
    t2n.to_csv(out / "table_ii_nmac_summary_statistics.csv", index=False)
    _save_table(
        t2n,
        "TABLE II\nNMAC (real-position) summary statistics",
        out / "pdfs" / "table_ii_nmac_summary_statistics.pdf",
        out / "pngs" / "table_ii_nmac_summary_statistics.png",
    )

    # Split table format A: Safety summary by agent count.
    if summary_csv.is_file():
        s = pd.read_csv(summary_csv)
        s["scenario"] = s["tag"].apply(_scenario_group_from_tag)
        scenario_order = [
            "Scenario_DepotCity_4x1",
            "Scenario_DepotCity_8x1",
            "Scenario_DepotCity_12x1",
            "Scenario_DepotCity_16x1",
        ]
        scenario_labels = ["4 Agents", "8 Agents", "12 Agents", "16 Agents"]
        safety_specs = [
            ("Total NMACs", "nmac_proximity_aware_instant_detect", "nmac_benign_spoofer_aware_instant_detect", "nmac_proximity_trust_rid", "nmac_benign_spoofer_trust_rid"),
            ("Benign-Benign", "nmac_proximity_aware_instant_detect", None, "nmac_proximity_trust_rid", None),
            ("Benign-Spoofer", "nmac_benign_spoofer_aware_instant_detect", None, "nmac_benign_spoofer_trust_rid", None),
            ("Unsafe violations", "nmac_spoofer_unsafe_aware_instant_detect", None, None, None),
        ]
        rows: list[dict[str, str]] = []
        for metric, sa_col, sa_col2, tr_col, tr_col2 in safety_specs:
            row: dict[str, str] = {"Metric": metric}
            for scen, slbl in zip(scenario_order, scenario_labels):
                ss = s[s["scenario"] == scen]
                sa_v = pd.to_numeric(ss[sa_col], errors="coerce")
                if sa_col2 is not None:
                    sa_v = sa_v + pd.to_numeric(ss[sa_col2], errors="coerce")
                sa_vals = sa_v.dropna().to_numpy(dtype=float)
                sa_mu = float(np.mean(sa_vals)) if sa_vals.size else float("nan")
                sa_sd = _safe_std(sa_vals)
                row[f"{slbl} (SA)"] = f"{sa_mu:.3f} ± {sa_sd:.3f}" if np.isfinite(sa_mu) else "N/A"

                if tr_col is None:
                    row[f"{slbl} (RID)"] = "N/A"
                else:
                    tr_v = pd.to_numeric(ss[tr_col], errors="coerce")
                    if tr_col2 is not None:
                        tr_v = tr_v + pd.to_numeric(ss[tr_col2], errors="coerce")
                    tr_vals = tr_v.dropna().to_numpy(dtype=float)
                    tr_mu = float(np.mean(tr_vals)) if tr_vals.size else float("nan")
                    tr_sd = _safe_std(tr_vals)
                    row[f"{slbl} (RID)"] = f"{tr_mu:.3f} ± {tr_sd:.3f}" if np.isfinite(tr_mu) else "N/A"
            rows.append(row)
        safety_df = pd.DataFrame(rows)
        safety_df.to_csv(out / "table_ii_safety_summary_by_agent_count.csv", index=False)
        _save_table(
            safety_df,
            "TABLE II-A\nSafety summary statistics by agent count (mean ± std)",
            out / "pdfs" / "table_ii_safety_summary_by_agent_count.pdf",
            out / "pngs" / "table_ii_safety_summary_by_agent_count.png",
            bold_metric_rows=frozenset({"Benign-Spoofer"}),
        )

        # Split table format B: Spoofer localization summary by agent count (SA only).
        localization_specs = [
            ("Spoofer containment rate", "spoofer_containment_rate_aware_instant_detect"),
            ("Raw RSSI/NLLS localization RMSE vs ground truth (m)", "localization_mlat_raw_rmse_m_aware_instant_detect"),
            ("Raw RSSI/NLLS localization MAE vs ground truth (m)", "localization_mlat_raw_mae_m_aware_instant_detect"),
            ("Predicted spoofer $\\mu$ error vs ground truth (RMSE, m)", "localization_rmse_m_aware_instant_detect"),
            ("Predicted spoofer $\\mu$ error vs ground truth (MAE, m)", "localization_mae_m_aware_instant_detect"),
        ]
        loc_rows: list[dict[str, str]] = []
        for metric, col in localization_specs:
            row = {"Metric": metric}
            for scen, slbl in zip(scenario_order, scenario_labels):
                ss = s[s["scenario"] == scen]
                mu, sd = _mean_std(ss, col)
                row[f"{slbl} (SA)"] = f"{mu:.3f} ± {sd:.3f}" if np.isfinite(mu) else "N/A"
            loc_rows.append(row)
        loc_df = pd.DataFrame(loc_rows)
        loc_df.to_csv(out / "table_iii_spoofer_localization_by_agent_count.csv", index=False)
        _save_table(
            loc_df,
            "TABLE II-B\nSpoofer localization statistics by agent count (SA, mean ± std)",
            out / "pdfs" / "table_iii_spoofer_localization_by_agent_count.pdf",
            out / "pngs" / "table_iii_spoofer_localization_by_agent_count.png",
        )

    # Table III: keep SA(detect@5s) vs TrustRID only.
    t3 = pd.read_csv(charts / "table_iii_runtime_mean_std_per_scenario_seconds.csv")
    t3n = t3[
        [
            "Scenario",
            "Mean (SA InstantDetect) [s]",
            "Std (SA InstantDetect) [s]",
            "Mean (Trust-RID) [s]",
            "Std (Trust-RID) [s]",
        ]
    ].rename(
        columns={
            "Mean (SA InstantDetect) [s]": "Mean (SA) [s]",
            "Std (SA InstantDetect) [s]": "Std (SA) [s]",
        }
    )
    t3n.to_csv(out / "table_iii_runtime_mean_std_per_scenario_seconds.csv", index=False)
    _save_table(
        t3n,
        "TABLE III\nRuntime per scenario (mean ± std, seconds)",
        out / "pdfs" / "table_iii_runtime_mean_std_per_scenario_seconds.pdf",
        out / "pngs" / "table_iii_runtime_mean_std_per_scenario_seconds.png",
    )

    long_df = pd.read_csv(charts / "gcs_timeseries_long.csv")
    long_df["time"] = pd.to_numeric(long_df["time"], errors="coerce")
    long_df["value"] = pd.to_numeric(long_df["value"], errors="coerce")
    long_df = long_df.dropna(subset=["time", "value", "scenario", "variant", "name"])

    variant_order = ["SpoofingAwareInstantDetect", "TrustRID"]
    labels = {
        "SpoofingAwareInstantDetect": "Spoofing Aware (detect@5s)",
        "TrustRID": "TrustRID",
    }
    colors = {"SpoofingAwareInstantDetect": "#2ca02c", "TrustRID": "#f58518"}
    styles = {"SpoofingAwareInstantDetect": "-", "TrustRID": "--"}

    # Min-distance timeseries: only SA(detect@5s) vs TR.
    sub = long_df[long_df["name"].astype(str).str.contains("min_benign_spoofer_distance_now_m", na=False)].copy()
    sub = sub[sub["variant"].isin(variant_order)]
    if not sub.empty:
        scenarios = sorted(sub["scenario"].dropna().unique().tolist())
        fig, axes = plt.subplots(1, len(scenarios), figsize=(5.0 * len(scenarios), 4.1), squeeze=False, sharey=True)
        yvals: list[float] = []
        for i, scen in enumerate(scenarios):
            ax = axes[0][i]
            ss = sub[sub["scenario"] == scen]
            for v in variant_order:
                g = ss[ss["variant"] == v]
                if g.empty:
                    continue
                agg = g.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                agg["std"] = agg["std"].fillna(0.0)
                lo = agg["mean"] - agg["std"]
                hi = agg["mean"] + agg["std"]
                ax.fill_between(agg["time"], lo, hi, alpha=0.20, color=colors[v], linewidth=0)
                ax.plot(agg["time"], agg["mean"], color=colors[v], linestyle=styles[v], linewidth=1.9, label=labels[v])
                yvals.extend(lo.tolist())
                yvals.extend(hi.tolist())
            ax.set_title(str(scen))
            ax.set_xlabel("time (s)")
            ax.set_ylabel("distance (m)")
            ax.grid(alpha=0.2)
            ax.legend(fontsize=8)
        ylim = _ylim_with_pad(yvals)
        if ylim is not None:
            for ax in axes[0]:
                ax.set_ylim(*ylim)
        fig.suptitle("Min Benign-Spoofer Distance Through Time (mean ± std)\nSpoofing Aware (detect@5s) vs TrustRID")
        fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.95])
        fig.savefig(out / "pdfs" / "timeseries_min_distance_mean_std.pdf", dpi=220)
        fig.savefig(out / "pngs" / "timeseries_min_distance_mean_std.png", dpi=220)
        plt.close(fig)

    # Containment/localization/bubble timeseries: only SA(detect@5s) vs TR.
    contain = long_df[long_df["name"].astype(str).str.contains("spoofer_containment_rate", na=False)]
    loc = long_df[long_df["name"].astype(str).str.contains("localization_rmse_m", na=False)]
    bub = long_df[long_df["name"].astype(str).str.contains("unsafe_radius_max_m", na=False)]
    contain = contain[contain["variant"].isin(variant_order)]
    loc = loc[loc["variant"].isin(variant_order)]
    bub = bub[bub["variant"].isin(variant_order)]
    scenarios = sorted(set(contain["scenario"].dropna()) | set(loc["scenario"].dropna()) | set(bub["scenario"].dropna()))
    if scenarios:
        fig, axes = plt.subplots(3, len(scenarios), figsize=(5.6 * len(scenarios), 8.4), squeeze=False, sharex="col")
        rows: list[list[float]] = [[], [], []]
        for i, scen in enumerate(scenarios):
            ax1, ax2, ax3 = axes[0][i], axes[1][i], axes[2][i]
            for v in variant_order:
                c = contain[(contain["scenario"] == scen) & (contain["variant"] == v)]
                if not c.empty:
                    agg = c.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                    agg["std"] = agg["std"].fillna(0.0)
                    lo = agg["mean"] - agg["std"]
                    hi = agg["mean"] + agg["std"]
                    ax1.fill_between(agg["time"], lo, hi, alpha=0.20, color=colors[v], linewidth=0)
                    ax1.plot(agg["time"], agg["mean"], color=colors[v], linestyle=styles[v], linewidth=1.9, label=labels[v])
                    rows[0].extend(lo.tolist())
                    rows[0].extend(hi.tolist())

                l = loc[(loc["scenario"] == scen) & (loc["variant"] == v)]
                if not l.empty:
                    agg = l.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                    agg["std"] = agg["std"].fillna(0.0)
                    lo = agg["mean"] - agg["std"]
                    hi = agg["mean"] + agg["std"]
                    ax2.fill_between(agg["time"], lo, hi, alpha=0.20, color=colors[v], linewidth=0)
                    ax2.plot(agg["time"], agg["mean"], color=colors[v], linestyle=styles[v], linewidth=1.9)
                    rows[1].extend(lo.tolist())
                    rows[1].extend(hi.tolist())

                b = bub[(bub["scenario"] == scen) & (bub["variant"] == v)]
                if not b.empty:
                    agg = b.groupby("time", as_index=False).agg(mean=("value", "mean"), std=("value", "std"))
                    agg["std"] = agg["std"].fillna(0.0)
                    lo = agg["mean"] - agg["std"]
                    hi = agg["mean"] + agg["std"]
                    ax3.fill_between(agg["time"], lo, hi, alpha=0.20, color=colors[v], linewidth=0)
                    ax3.plot(agg["time"], agg["mean"], color=colors[v], linestyle=styles[v], linewidth=1.9)
                    rows[2].extend(lo.tolist())
                    rows[2].extend(hi.tolist())

            ax1.set_title(str(scen))
            ax1.set_ylabel("containment rate")
            ax1.grid(alpha=0.25)
            ax2.set_ylabel("localization RMSE (m)")
            ax2.grid(alpha=0.25)
            ax3.set_ylabel("unsafe bubble radius max (m)")
            ax3.set_xlabel("time (s)")
            ax3.grid(alpha=0.25)
            if i == 0:
                handles, labs = ax1.get_legend_handles_labels()
                if handles:
                    ax1.legend(handles, labs, fontsize=8, loc="best")

        for ridx in range(3):
            ylim = _ylim_with_pad(rows[ridx])
            if ylim is not None:
                for c in range(len(scenarios)):
                    axes[ridx][c].set_ylim(*ylim)

        fig.suptitle(
            "Containment, Localization RMSE, and Unsafe-Bubble Radius Through Time (mean ± std)\n"
            "Spoofing Aware (detect@5s) vs TrustRID"
        )
        fig.tight_layout(rect=[0.0, 0.0, 1.0, 0.96])
        fig.savefig(out / "pdfs" / "timeseries_containment_localization_unsafe_bubble_mean_std.pdf", dpi=220)
        fig.savefig(out / "pngs" / "timeseries_containment_localization_unsafe_bubble_mean_std.png", dpi=220)
        plt.close(fig)

    (out / "README.txt").write_text(
        "Paper-only subset generated from run_root/charts.\n"
        "Regenerated as strict 2-variant views:\n"
        "- Spoofing Aware (FORCE_DETECT_AT_S=5)\n"
        "- TrustRID\n\n"
        "Included files:\n"
        "- table_ii_nmac_summary_statistics (csv/pdf/png)\n"
        "- table_ii_safety_summary_by_agent_count (csv/pdf/png)\n"
        "- table_iii_spoofer_localization_by_agent_count (csv/pdf/png)\n"
        "- table_iii_runtime_mean_std_per_scenario_seconds (csv/pdf/png)\n"
        "- timeseries_min_distance_mean_std (pdf/png)\n"
        "- timeseries_containment_localization_unsafe_bubble_mean_std (pdf/png)\n"
    )

    print(f"Regenerated: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
