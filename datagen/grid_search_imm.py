#!/usr/bin/env python3
"""
Grid-search IMM parameters by repeatedly running the compare pipeline.

Each trial:
  1) Sets IMM tuning env vars (ULI_IMM_*)
  2) Runs datagen/run_compare_pipeline.sh
  3) Collects summary.csv + charts/imm_diagnostics_summary.csv metrics
  4) Ranks configurations and writes CSV report

Example:
  python3 datagen/grid_search_imm.py \
      --paper-scenarios --include-steepz --seeds 0:4 --parallel 4 \
      --p-cv-stay 0.9,0.95,0.98 \
      --p-ca-stay 0.9,0.95,0.98 \
      --cv-vel-noise 20,40,80 \
      --ca-acc-noise 30,60,120
"""

from __future__ import annotations

import argparse
import csv
import itertools
import os
import subprocess
import sys
from pathlib import Path
from statistics import mean


DEFAULT_SWEEP_ROOT = Path(
    "simulations/spoofing_aware_with_planning/sweeps/charts_store"
)


def _parse_float_grid(raw: str) -> list[float]:
    vals = []
    for tok in (raw or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        vals.append(float(tok))
    if not vals:
        raise ValueError("Empty grid list")
    return vals


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="") as f:
        r = csv.DictReader(f)
        return list(r)


def _to_floats(rows: list[dict[str, str]], key: str) -> list[float]:
    out: list[float] = []
    for row in rows:
        raw = row.get(key, "")
        if raw is None or raw == "":
            continue
        try:
            out.append(float(raw))
        except ValueError:
            continue
    return out


def _safe_mean(vals: list[float]) -> float:
    return mean(vals) if vals else float("nan")


def _score_trial(
    containment_rate_mean: float,
    localization_rmse_mean: float,
    nees_in_95_mean: float,
    nis_in_95_mean: float,
) -> float:
    # Higher is better:
    # - reward containment and consistency (NEES/NIS in 95% bounds)
    # - penalize localization error in meters
    if any(v != v for v in [containment_rate_mean, localization_rmse_mean, nees_in_95_mean, nis_in_95_mean]):
        return float("nan")
    return (
        2.0 * containment_rate_mean
        + 0.8 * nees_in_95_mean
        + 0.8 * nis_in_95_mean
        - 0.02 * localization_rmse_mean
    )


def _build_pipeline_args(args: argparse.Namespace, run_name: str) -> list[str]:
    cmd = [
        "./datagen/run_compare_pipeline.sh",
        "--run-name", run_name,
        "--sweep-root", str(args.sweep_root),
        "--seeds", args.seeds,
        "--parallel", str(args.parallel),
        "--image", args.image,
    ]
    if args.skip_build:
        cmd.append("--skip-build")
    if args.no_keep_vec:
        cmd.append("--no-keep-vec")
    if args.no_export_vectors:
        cmd.append("--no-export-vectors")
    if args.no_plot:
        cmd.append("--no-plot")

    # Scenario selection (match run_compare_pipeline.sh semantics).
    if args.paper_scenarios:
        cmd.append("--paper-scenarios")
    elif args.scenario_configs:
        cmd.extend(["--scenario-configs", args.scenario_configs])
    elif args.scenario_config:
        cmd.extend(["--scenario-config", args.scenario_config])
    else:
        raise ValueError("Provide one of --paper-scenarios, --scenario-configs, --scenario-config")

    if args.include_steepz:
        cmd.append("--include-steepz")
    return cmd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Grid-search IMM tuning via compare pipeline")
    scenario_group = ap.add_mutually_exclusive_group(required=True)
    scenario_group.add_argument("--scenario-config", type=str, default=None)
    scenario_group.add_argument("--scenario-configs", type=str, default=None)
    scenario_group.add_argument("--paper-scenarios", action="store_true")
    ap.add_argument("--include-steepz", action="store_true")

    ap.add_argument("--seeds", type=str, default="0:4")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--image", type=str, default="uli-net-sim:latest")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--no-keep-vec", action="store_true")
    ap.add_argument("--no-export-vectors", action="store_true")
    ap.add_argument("--no-plot", action="store_true")

    ap.add_argument("--sweep-root", type=Path, default=DEFAULT_SWEEP_ROOT)
    ap.add_argument("--run-prefix", type=str, default="imm_grid")
    ap.add_argument("--dry-run", action="store_true")

    ap.add_argument("--init-mode-cv", type=str, default="0.6")
    ap.add_argument("--p-cv-stay", type=str, default="0.95")
    ap.add_argument("--p-ca-stay", type=str, default="0.95")
    ap.add_argument("--cv-pos-noise", type=str, default="2.0")
    ap.add_argument("--cv-vel-noise", type=str, default="40.0")
    ap.add_argument("--cv-meas-noise", type=str, default="100.0")
    ap.add_argument("--ca-pos-noise", type=str, default="2.0")
    ap.add_argument("--ca-vel-noise", type=str, default="25.0")
    ap.add_argument("--ca-acc-noise", type=str, default="60.0")
    ap.add_argument("--ca-meas-noise", type=str, default="100.0")
    args = ap.parse_args(argv)

    grids = {
        "ULI_IMM_INIT_MODE_CV": _parse_float_grid(args.init_mode_cv),
        "ULI_IMM_P_CV_STAY": _parse_float_grid(args.p_cv_stay),
        "ULI_IMM_P_CA_STAY": _parse_float_grid(args.p_ca_stay),
        "ULI_IMM_CV_POS_NOISE": _parse_float_grid(args.cv_pos_noise),
        "ULI_IMM_CV_VEL_NOISE": _parse_float_grid(args.cv_vel_noise),
        "ULI_IMM_CV_MEAS_NOISE": _parse_float_grid(args.cv_meas_noise),
        "ULI_IMM_CA_POS_NOISE": _parse_float_grid(args.ca_pos_noise),
        "ULI_IMM_CA_VEL_NOISE": _parse_float_grid(args.ca_vel_noise),
        "ULI_IMM_CA_ACC_NOISE": _parse_float_grid(args.ca_acc_noise),
        "ULI_IMM_CA_MEAS_NOISE": _parse_float_grid(args.ca_meas_noise),
    }

    keys = list(grids.keys())
    combos = list(itertools.product(*(grids[k] for k in keys)))
    args.sweep_root.mkdir(parents=True, exist_ok=True)
    print(f"Running {len(combos)} IMM trial(s) under {args.sweep_root}")

    results: list[dict[str, float | str]] = []
    for i, combo in enumerate(combos, start=1):
        trial_env = os.environ.copy()
        for k, v in zip(keys, combo):
            trial_env[k] = str(v)

        run_name = f"{args.run_prefix}_{i:03d}"
        run_root = args.sweep_root / run_name
        cmd = _build_pipeline_args(args, run_name=run_name)

        print(f"[{i}/{len(combos)}] {run_name} starting...")
        if args.dry_run:
            print("  DRY RUN:", " ".join(cmd))
            continue
        subprocess.run(cmd, check=True, env=trial_env)

        summary_rows = _read_csv_rows(run_root / "summary.csv")
        imm_rows = _read_csv_rows(run_root / "charts" / "imm_diagnostics_summary.csv")

        containment = _safe_mean(_to_floats(summary_rows, "spoofer_containment_rate_aware"))
        loc_rmse = _safe_mean(_to_floats(summary_rows, "localization_rmse_m_aware"))
        nees_in95 = _safe_mean(_to_floats(imm_rows, "imm_nees_in_95pct_fraction"))
        nis_in95 = _safe_mean(_to_floats(imm_rows, "imm_nis_in_95pct_fraction"))
        score = _score_trial(containment, loc_rmse, nees_in95, nis_in95)

        row: dict[str, float | str] = {
            "run_name": run_name,
            "run_root": str(run_root),
            "score": score,
            "containment_rate_mean": containment,
            "localization_rmse_mean_m": loc_rmse,
            "imm_nees_in_95pct_fraction_mean": nees_in95,
            "imm_nis_in_95pct_fraction_mean": nis_in95,
        }
        for k, v in zip(keys, combo):
            row[k] = v
        results.append(row)
        print(
            f"[{i}/{len(combos)}] {run_name} done: "
            f"score={score:.4f} containment={containment:.4f} "
            f"rmse={loc_rmse:.4f} nees95={nees_in95:.4f} nis95={nis_in95:.4f}"
        )

    if args.dry_run:
        return 0

    results.sort(
        key=lambda r: (
            float("-inf")
            if isinstance(r["score"], float) and (r["score"] != r["score"])
            else float(r["score"])
        ),
        reverse=True,
    )

    out_csv = args.sweep_root / "imm_grid_search_results.csv"
    if results:
        fieldnames = list(results[0].keys())
        with out_csv.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(results)
    else:
        out_csv.write_text("")

    print(f"Wrote {out_csv}")
    if results:
        best = results[0]
        print(f"Best run: {best['run_name']} score={best['score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
