#!/usr/bin/env python3
"""
Visualize IMM grid-search results for remote tuning workflows.

Reads the CSV produced by debug/grid_search_imm.py and writes summary plots:
  - Top-K score leaderboard
  - Containment vs RMSE scatter (colored by score)
  - NEES95 vs NIS95 consistency scatter
  - Parameter-to-score Spearman correlation bar chart
  - Pareto front (containment high, RMSE low)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def _apply_style(plt) -> None:
    plt.rcParams.update(
        {
            "figure.dpi": 140,
            "savefig.dpi": 220,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "legend.fontsize": 9,
            "axes.grid": True,
            "grid.alpha": 0.25,
            "grid.linestyle": "-",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def _coerce_numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    out = df.copy()
    for c in cols:
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def _status_ok(df: pd.DataFrame) -> pd.DataFrame:
    if "status" not in df.columns:
        return df.copy()
    return df[df["status"].astype(str).str.lower() == "ok"].copy()


def _has_cols(df: pd.DataFrame, cols: list[str]) -> bool:
    return all(c in df.columns for c in cols)


def _pareto_front(df: pd.DataFrame, maximize: list[str], minimize: list[str]) -> pd.Series:
    n = len(df)
    is_pareto = np.ones(n, dtype=bool)
    vals_max = np.column_stack([df[c].to_numpy() for c in maximize]) if maximize else np.zeros((n, 0))
    vals_min = np.column_stack([df[c].to_numpy() for c in minimize]) if minimize else np.zeros((n, 0))

    for i in range(n):
        if not is_pareto[i]:
            continue
        better_or_equal_max = np.all(vals_max >= vals_max[i], axis=1) if maximize else np.ones(n, dtype=bool)
        better_or_equal_min = np.all(vals_min <= vals_min[i], axis=1) if minimize else np.ones(n, dtype=bool)
        strictly_better_max = np.any(vals_max > vals_max[i], axis=1) if maximize else np.zeros(n, dtype=bool)
        strictly_better_min = np.any(vals_min < vals_min[i], axis=1) if minimize else np.zeros(n, dtype=bool)
        dominates_i = better_or_equal_max & better_or_equal_min & (strictly_better_max | strictly_better_min)
        dominates_i[i] = False
        if np.any(dominates_i):
            is_pareto[i] = False
    return pd.Series(is_pareto, index=df.index)


def main() -> int:
    ap = argparse.ArgumentParser(description="Plot IMM grid-search results CSV.")
    ap.add_argument(
        "--results-csv",
        type=Path,
        required=True,
        help="Path to imm_grid_search_results.csv",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory (default: <csv_dir>/imm_grid_plots)",
    )
    ap.add_argument("--top-k", type=int, default=15)
    args = ap.parse_args()

    if not args.results_csv.is_file():
        raise SystemExit(f"results CSV not found: {args.results_csv}")

    out_dir = args.out_dir or (args.results_csv.parent / "imm_grid_plots")
    out_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(args.results_csv)
    needed_numeric = [
        "score",
        "containment_rate_mean",
        "localization_rmse_mean_m",
        "imm_nees_in_95pct_fraction_mean",
        "imm_nis_in_95pct_fraction_mean",
        "detection_latency_mean_s",
    ]
    df = _coerce_numeric(df, needed_numeric)
    ok = _status_ok(df)
    if ok.empty:
        raise SystemExit("No successful (status=ok) rows to plot.")

    import matplotlib.pyplot as plt

    _apply_style(plt)

    # 1) Top-K leaderboard
    top = ok.sort_values("score", ascending=False).head(max(1, args.top_k)).copy()
    fig, ax = plt.subplots(figsize=(11, 6))
    y = np.arange(len(top))
    labels = [str(r) for r in top["run_name"].tolist()] if "run_name" in top.columns else [str(i) for i in y]
    ax.barh(y, top["score"].to_numpy(), color="#4C78A8")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("Score")
    ax.set_title("Top IMM Configurations by Score")
    fig.tight_layout()
    fig.savefig(out_dir / "leaderboard_top_score.png")
    plt.close(fig)

    # 2) Containment vs RMSE (colored by score)
    if _has_cols(ok, ["localization_rmse_mean_m", "containment_rate_mean", "score"]):
        fig, ax = plt.subplots(figsize=(8, 6))
        sc = ax.scatter(
            ok["localization_rmse_mean_m"],
            ok["containment_rate_mean"],
            c=ok["score"],
            cmap="viridis",
            alpha=0.85,
            s=38,
            edgecolors="none",
        )
        ax.set_xlabel("Localization RMSE mean (m) [lower is better]")
        ax.set_ylabel("Containment rate mean [higher is better]")
        ax.set_title("Containment vs RMSE (color=score)")
        cbar = fig.colorbar(sc, ax=ax)
        cbar.set_label("Score")
        fig.tight_layout()
        fig.savefig(out_dir / "containment_vs_rmse_scatter.png")
        plt.close(fig)
    else:
        print("Skipping containment_vs_rmse_scatter: required columns missing.")

    # 3) Consistency scatter (NEES95 vs NIS95)
    if _has_cols(ok, ["imm_nees_in_95pct_fraction_mean", "imm_nis_in_95pct_fraction_mean", "containment_rate_mean"]):
        fig, ax = plt.subplots(figsize=(8, 6))
        ax.scatter(
            ok["imm_nees_in_95pct_fraction_mean"],
            ok["imm_nis_in_95pct_fraction_mean"],
            c=ok["containment_rate_mean"],
            cmap="plasma",
            alpha=0.85,
            s=38,
            edgecolors="none",
        )
        ax.set_xlabel("NEES in 95% fraction mean")
        ax.set_ylabel("NIS in 95% fraction mean")
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(0.0, 1.0)
        ax.plot([0, 1], [0, 1], "--", linewidth=1.0, color="gray", alpha=0.6)
        ax.set_title("Consistency Diagnostics (color=containment)")
        fig.tight_layout()
        fig.savefig(out_dir / "consistency_nees95_vs_nis95.png")
        plt.close(fig)
    else:
        print("Skipping consistency_nees95_vs_nis95: required columns missing.")

    # 4) Parameter sensitivity via Spearman correlation to score
    param_cols = [c for c in ok.columns if c.startswith("ULI_IMM_")]
    corr_rows: list[tuple[str, float]] = []
    for c in param_cols:
        x = pd.to_numeric(ok[c], errors="coerce")
        yv = ok["score"]
        valid = x.notna() & yv.notna()
        if valid.sum() < 3:
            continue
        rho = x[valid].corr(yv[valid], method="spearman")
        if pd.notna(rho):
            corr_rows.append((c, float(rho)))
    corr_rows.sort(key=lambda kv: abs(kv[1]), reverse=True)
    if corr_rows:
        top_corr = corr_rows[: min(20, len(corr_rows))]
        labels = [k.replace("ULI_IMM_", "") for k, _ in top_corr]
        vals = [v for _, v in top_corr]
        fig, ax = plt.subplots(figsize=(10, max(4, 0.35 * len(top_corr))))
        y = np.arange(len(top_corr))
        colors = ["#2ca02c" if v >= 0 else "#d62728" for v in vals]
        ax.barh(y, vals, color=colors)
        ax.set_yticks(y, labels)
        ax.invert_yaxis()
        ax.set_xlabel("Spearman rho with score")
        ax.set_title("IMM Parameter Sensitivity to Score")
        ax.axvline(0.0, color="black", linewidth=1.0, alpha=0.7)
        fig.tight_layout()
        fig.savefig(out_dir / "parameter_sensitivity_spearman_score.png")
        plt.close(fig)

    # 5) Pareto front: maximize containment, minimize RMSE
    pareto_df = (
        ok.dropna(subset=["containment_rate_mean", "localization_rmse_mean_m"]).copy()
        if _has_cols(ok, ["containment_rate_mean", "localization_rmse_mean_m"])
        else pd.DataFrame()
    )
    if not pareto_df.empty:
        pareto_mask = _pareto_front(
            pareto_df,
            maximize=["containment_rate_mean"],
            minimize=["localization_rmse_mean_m"],
        )
        pareto_df["pareto"] = pareto_mask
        fig, ax = plt.subplots(figsize=(8, 6))
        rest = pareto_df[~pareto_df["pareto"]]
        front = pareto_df[pareto_df["pareto"]].sort_values("localization_rmse_mean_m")
        ax.scatter(
            rest["localization_rmse_mean_m"],
            rest["containment_rate_mean"],
            color="#bdbdbd",
            alpha=0.6,
            s=28,
            label="Other",
        )
        ax.scatter(
            front["localization_rmse_mean_m"],
            front["containment_rate_mean"],
            color="#1f77b4",
            alpha=0.95,
            s=40,
            label="Pareto front",
        )
        if len(front) > 1:
            ax.plot(front["localization_rmse_mean_m"], front["containment_rate_mean"], color="#1f77b4", linewidth=1.2)
        ax.set_xlabel("Localization RMSE mean (m)")
        ax.set_ylabel("Containment rate mean")
        ax.set_title("Pareto Front: Containment vs RMSE")
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(out_dir / "pareto_containment_vs_rmse.png")
        plt.close(fig)

        pareto_cols = ["run_name", "score", "containment_rate_mean", "localization_rmse_mean_m"] + param_cols
        keep_cols = [c for c in pareto_cols if c in pareto_df.columns]
        pareto_df[pareto_df["pareto"]][keep_cols].sort_values(
            ["containment_rate_mean", "localization_rmse_mean_m"],
            ascending=[False, True],
        ).to_csv(out_dir / "pareto_runs.csv", index=False)

    print(f"Wrote IMM grid plots to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

