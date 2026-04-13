#!/usr/bin/env python3
"""
Grid-search IMM parameters by repeatedly running the batch pipeline.

Each trial:
  1) Sets IMM tuning env vars (ULI_IMM_*)
  2) Runs datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh
  3) Collects summary.csv + charts/imm_diagnostics_summary.csv metrics
  4) Ranks configurations and writes CSV report

Example:
  python3 datagen/spoofting_aware_trajectory_planning_datagen/grid_search_imm.py \
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
import time
import random
import math
from datetime import datetime
from pathlib import Path
from statistics import mean


DEFAULT_BATCH_ROOT = Path(
    "simulations/spoofing_aware_with_planning/batches"
)

PRESET_GRIDS: dict[str, dict[str, list[float]]] = {
    "single": {
        "ULI_IMM_INIT_MODE_CV": [0.6],
        "ULI_IMM_P_CV_STAY": [0.95],
        "ULI_IMM_P_CA_STAY": [0.95],
        "ULI_IMM_CV_POS_NOISE": [2.0],
        "ULI_IMM_CV_VEL_NOISE": [40.0],
        "ULI_IMM_CV_MEAS_NOISE": [100.0],
        "ULI_IMM_CA_POS_NOISE": [2.0],
        "ULI_IMM_CA_VEL_NOISE": [25.0],
        "ULI_IMM_CA_ACC_NOISE": [60.0],
        "ULI_IMM_CA_MEAS_NOISE": [100.0],
    },
    "quick": {
        "ULI_IMM_INIT_MODE_CV": [0.5, 0.6, 0.7],
        "ULI_IMM_P_CV_STAY": [0.9, 0.95, 0.98],
        "ULI_IMM_P_CA_STAY": [0.88, 0.93, 0.97],
        "ULI_IMM_CV_POS_NOISE": [1.0, 2.0],
        "ULI_IMM_CV_VEL_NOISE": [20.0, 40.0, 80.0],
        "ULI_IMM_CV_MEAS_NOISE": [50.0, 100.0, 200.0],
        "ULI_IMM_CA_POS_NOISE": [1.0, 2.0],
        "ULI_IMM_CA_VEL_NOISE": [15.0, 25.0, 40.0],
        "ULI_IMM_CA_ACC_NOISE": [30.0, 60.0, 120.0],
        "ULI_IMM_CA_MEAS_NOISE": [50.0, 100.0, 200.0],
    },
    "overnight": {
        "ULI_IMM_INIT_MODE_CV": [0.45, 0.55, 0.65, 0.75],
        "ULI_IMM_P_CV_STAY": [0.88, 0.92, 0.95, 0.98],
        "ULI_IMM_P_CA_STAY": [0.84, 0.9, 0.95, 0.98],
        "ULI_IMM_CV_POS_NOISE": [0.5, 1.0, 2.0, 4.0],
        "ULI_IMM_CV_VEL_NOISE": [10.0, 20.0, 40.0, 80.0, 120.0],
        "ULI_IMM_CV_MEAS_NOISE": [30.0, 50.0, 100.0, 200.0, 400.0],
        "ULI_IMM_CA_POS_NOISE": [0.5, 1.0, 2.0, 4.0],
        "ULI_IMM_CA_VEL_NOISE": [10.0, 20.0, 30.0, 50.0],
        "ULI_IMM_CA_ACC_NOISE": [20.0, 40.0, 60.0, 100.0, 160.0],
        "ULI_IMM_CA_MEAS_NOISE": [30.0, 50.0, 100.0, 200.0, 400.0],
    },
}

PRESET_MAX_TRIALS_DEFAULT = {
    "single": 0,
    "quick": 80,
    "overnight": 500,
}


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


def _safe_std(vals: list[float]) -> float:
    if len(vals) < 2:
        return float("nan")
    m = mean(vals)
    var = sum((v - m) ** 2 for v in vals) / float(len(vals))
    return float(math.sqrt(max(var, 0.0)))


def _safe_min(vals: list[float]) -> float:
    return float(min(vals)) if vals else float("nan")


def _safe_max(vals: list[float]) -> float:
    return float(max(vals)) if vals else float("nan")


def _safe_median(vals: list[float]) -> float:
    if not vals:
        return float("nan")
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return float(0.5 * (s[mid - 1] + s[mid]))


def _metric(rows: list[dict[str, str]], key: str, agg: str = "mean") -> float:
    vals = _to_floats(rows, key)
    if agg == "mean":
        return _safe_mean(vals)
    if agg == "std":
        return _safe_std(vals)
    if agg == "min":
        return _safe_min(vals)
    if agg == "max":
        return _safe_max(vals)
    if agg == "median":
        return _safe_median(vals)
    raise ValueError(f"Unknown agg: {agg}")


def _score_trial(
    containment_rate_mean: float,
    localization_rmse_mean: float,
    nees_in_95_mean: float,
    nis_in_95_mean: float,
    total_nmac_real_mean: float,
    nmac_spoofer_unsafe_mean: float,
    w_containment: float,
    w_nees95: float,
    w_nis95: float,
    w_rmse: float,
    w_total_nmac_real: float,
    w_nmac_spoofer_unsafe: float,
) -> float:
    # Core terms must be present; IMM consistency terms can be missing and are then ignored.
    if any(
        v != v
        for v in [
            containment_rate_mean,
            localization_rmse_mean,
            total_nmac_real_mean,
            nmac_spoofer_unsafe_mean,
        ]
    ):
        return float("nan")
    nees_term = nees_in_95_mean if nees_in_95_mean == nees_in_95_mean else 0.0
    nis_term = nis_in_95_mean if nis_in_95_mean == nis_in_95_mean else 0.0
    return (
        w_containment * containment_rate_mean
        + w_nees95 * nees_term
        + w_nis95 * nis_term
        - w_rmse * localization_rmse_mean
        - w_total_nmac_real * total_nmac_real_mean
        - w_nmac_spoofer_unsafe * nmac_spoofer_unsafe_mean
    )


def _build_pipeline_args(args: argparse.Namespace) -> list[str]:
    runner = Path("./datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh")
    if not runner.is_file():
        raise FileNotFoundError(f"Batch runner not found: {runner}")
    cmd = [
        "bash",
        str(runner),
        "--batch-root", str(args.batch_root),
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
    else:
        cmd.extend(["--plot-profile", args.plot_profile])

    # Scenario selection (match run_spoofing_aware_trajectory_planning_batch.sh semantics).
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


def _next_batch_run_id(batch_root: Path) -> str:
    max_n = 0
    for child in sorted(batch_root.iterdir()):
        if not child.is_dir():
            continue
        name = child.name
        if len(name) == 4 and name.isdigit():
            max_n = max(max_n, int(name))
    return f"{max_n + 1:04d}"


def _combo_key(keys: list[str], combo: tuple[float, ...]) -> str:
    return "|".join(f"{k}={float(v):.12g}" for k, v in zip(keys, combo))


def _load_done_keys(csv_path: Path, key_col: str = "combo_key") -> set[str]:
    if not csv_path.is_file():
        return set()
    rows = _read_csv_rows(csv_path)
    out: set[str] = set()
    for row in rows:
        k = row.get(key_col, "")
        status = (row.get("status", "") or "").strip().lower()
        if k and status == "ok":
            out.add(k)
    return out


def _append_result_row(csv_path: Path, fieldnames: list[str], row: dict[str, float | str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    need_header = not csv_path.is_file() or csv_path.stat().st_size == 0
    with csv_path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if need_header:
            w.writeheader()
        w.writerow(row)


def _parse_optional_grid(raw: str | None, fallback: list[float]) -> list[float]:
    if raw is None or raw == "":
        return list(fallback)
    return _parse_float_grid(raw)


def main(argv: list[str] | None = None) -> int:
    started_wall = time.perf_counter()
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
    ap.add_argument(
        "--plot-profile",
        type=str,
        choices=["paper", "full"],
        default="full",
        help="Plot profile forwarded to batch runner; use full to retain IMM diagnostics.",
    )

    ap.add_argument("--batch-root", type=Path, default=DEFAULT_BATCH_ROOT)
    ap.add_argument("--run-prefix", type=str, default="imm_grid")
    ap.add_argument("--results-csv", type=Path, default=None,
                    help="Output CSV path (default: <batch-root>/imm_grid_search_results.csv)")
    ap.add_argument("--resume-ok", action="store_true",
                    help="Skip combos already marked status=ok in results CSV")
    ap.add_argument("--fail-fast", action="store_true",
                    help="Stop immediately on first trial failure")
    ap.add_argument("--trial-timeout-sec", type=int, default=0,
                    help="Per-trial timeout in seconds (0 disables timeout)")
    ap.add_argument("--trial-retries", type=int, default=0,
                    help="Retries for failed trial launch/exit")
    ap.add_argument("--heartbeat-sec", type=int, default=60,
                    help="Print trial heartbeat every N seconds (0 disables)")
    ap.add_argument("--shuffle", action="store_true",
                    help="Shuffle trial order before running")
    ap.add_argument("--shuffle-seed", type=int, default=1337)
    ap.add_argument("--max-trials", type=int, default=0,
                    help="Run at most N combos after filtering/shuffling (0 = all)")
    ap.add_argument("--log-dir", type=Path, default=None,
                    help="Directory for per-trial stdout/stderr logs")
    ap.add_argument("--summary-md", type=Path, default=None,
                    help="Optional markdown leaderboard output path")
    ap.add_argument("--top-k", type=int, default=10,
                    help="How many top runs to print/summarize")
    ap.add_argument("--weight-containment", type=float, default=2.0)
    ap.add_argument("--weight-nees95", type=float, default=0.8)
    ap.add_argument("--weight-nis95", type=float, default=0.8)
    ap.add_argument("--weight-rmse", type=float, default=0.02)
    ap.add_argument(
        "--weight-total-nmac-real",
        type=float,
        default=0.03,
        help="Penalty weight for mean (nmac_proximity_aware + nmac_benign_spoofer_aware).",
    )
    ap.add_argument(
        "--weight-nmac-spoofer-unsafe",
        type=float,
        default=0.04,
        help="Penalty weight for mean nmac_spoofer_unsafe_aware.",
    )
    ap.add_argument("--min-containment", type=float, default=0.0,
                    help="If containment mean is below this, mark trial as low_containment")
    ap.add_argument(
        "--preset-grid",
        type=str,
        choices=sorted(PRESET_GRIDS.keys()),
        default="single",
        help="Predefined IMM grid profile; individual --*-noise args can override.",
    )
    ap.add_argument(
        "--estimate-min-per-trial",
        type=float,
        default=25.0,
        help="Used for rough runtime estimate printout.",
    )
    ap.add_argument(
        "--target-runtime-hours",
        type=float,
        default=0.0,
        help="If >0, auto-select max trials to roughly match this wall time.",
    )
    ap.add_argument("--dry-run", action="store_true")

    ap.add_argument("--init-mode-cv", type=str, default=None)
    ap.add_argument("--p-cv-stay", type=str, default=None)
    ap.add_argument("--p-ca-stay", type=str, default=None)
    ap.add_argument("--cv-pos-noise", type=str, default=None)
    ap.add_argument("--cv-vel-noise", type=str, default=None)
    ap.add_argument("--cv-meas-noise", type=str, default=None)
    ap.add_argument("--ca-pos-noise", type=str, default=None)
    ap.add_argument("--ca-vel-noise", type=str, default=None)
    ap.add_argument("--ca-acc-noise", type=str, default=None)
    ap.add_argument("--ca-meas-noise", type=str, default=None)
    args = ap.parse_args(argv)

    base = PRESET_GRIDS.get(args.preset_grid, PRESET_GRIDS["single"])
    grids = {
        "ULI_IMM_INIT_MODE_CV": _parse_optional_grid(args.init_mode_cv, base["ULI_IMM_INIT_MODE_CV"]),
        "ULI_IMM_P_CV_STAY": _parse_optional_grid(args.p_cv_stay, base["ULI_IMM_P_CV_STAY"]),
        "ULI_IMM_P_CA_STAY": _parse_optional_grid(args.p_ca_stay, base["ULI_IMM_P_CA_STAY"]),
        "ULI_IMM_CV_POS_NOISE": _parse_optional_grid(args.cv_pos_noise, base["ULI_IMM_CV_POS_NOISE"]),
        "ULI_IMM_CV_VEL_NOISE": _parse_optional_grid(args.cv_vel_noise, base["ULI_IMM_CV_VEL_NOISE"]),
        "ULI_IMM_CV_MEAS_NOISE": _parse_optional_grid(args.cv_meas_noise, base["ULI_IMM_CV_MEAS_NOISE"]),
        "ULI_IMM_CA_POS_NOISE": _parse_optional_grid(args.ca_pos_noise, base["ULI_IMM_CA_POS_NOISE"]),
        "ULI_IMM_CA_VEL_NOISE": _parse_optional_grid(args.ca_vel_noise, base["ULI_IMM_CA_VEL_NOISE"]),
        "ULI_IMM_CA_ACC_NOISE": _parse_optional_grid(args.ca_acc_noise, base["ULI_IMM_CA_ACC_NOISE"]),
        "ULI_IMM_CA_MEAS_NOISE": _parse_optional_grid(args.ca_meas_noise, base["ULI_IMM_CA_MEAS_NOISE"]),
    }

    keys = list(grids.keys())
    combos = list(itertools.product(*(grids[k] for k in keys)))
    full_combo_count = len(combos)
    if args.max_trials <= 0 and PRESET_MAX_TRIALS_DEFAULT.get(args.preset_grid, 0) > 0:
        args.max_trials = PRESET_MAX_TRIALS_DEFAULT[args.preset_grid]
    if args.target_runtime_hours > 0:
        est_min = float(max(args.estimate_min_per_trial, 0.1))
        derived_max = max(1, int(math.floor((args.target_runtime_hours * 60.0) / est_min)))
        if args.max_trials > 0:
            args.max_trials = min(args.max_trials, derived_max)
        else:
            args.max_trials = derived_max
    args.batch_root.mkdir(parents=True, exist_ok=True)
    if args.shuffle:
        rng = random.Random(args.shuffle_seed)
        rng.shuffle(combos)
    if args.max_trials > 0:
        combos = combos[:args.max_trials]

    out_csv = args.results_csv or (args.batch_root / "imm_grid_search_results.csv")
    done_keys: set[str] = _load_done_keys(out_csv) if args.resume_ok else set()
    if done_keys:
        combos = [c for c in combos if _combo_key(keys, c) not in done_keys]

    log_dir = args.log_dir or (args.batch_root / f"{args.run_prefix}_logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    est_total_min = float(len(combos)) * float(max(args.estimate_min_per_trial, 0.0))
    est_wall_min = est_total_min / float(max(args.parallel, 1))
    print(f"Running {len(combos)} IMM trial(s) under {args.batch_root}")
    print(f"Results CSV: {out_csv}")
    print(f"Log dir: {log_dir}")
    print(
        f"Preset={args.preset_grid} full_grid={full_combo_count} "
        f"planned_trials={len(combos)} parallel={args.parallel} "
        f"est_wall_hours={est_wall_min / 60.0:.2f}"
    )
    total_trials = len(combos)

    results: list[dict[str, float | str]] = []
    fieldnames: list[str] = [
        "trial_index", "combo_key", "status", "error", "elapsed_sec",
        "run_name", "run_root", "score", "containment_rate_mean",
        "localization_rmse_mean_m", "imm_nees_in_95pct_fraction_mean",
        "imm_nis_in_95pct_fraction_mean", "containment_rate_std",
        "containment_rate_min", "containment_rate_max",
        "localization_rmse_median_m", "localization_rmse_std_m",
        "nmac_proximity_mean_aware", "nmac_benign_spoofer_mean_aware",
        "total_nmac_real_mean_aware", "nmac_spoofer_unsafe_mean_aware",
        "detection_latency_mean_s", "localization_mae_mean_m",
        "detection_reports_total_mean_aware",
        "detection_mlat_attempted_mean_aware",
        "detection_mlat_skipped_insufficient_receivers_mean_aware",
        "detection_mlat_skipped_insufficient_receivers_fraction_mean_aware",
        "imm_nees_mean", "imm_nees_std", "imm_nis_mean", "imm_nis_std",
    ] + keys
    for i, combo in enumerate(combos, start=1):
        trial_env = os.environ.copy()
        for k, v in zip(keys, combo):
            trial_env[k] = str(v)

        combo_key = _combo_key(keys, combo)
        run_id = _next_batch_run_id(args.batch_root)
        run_name = f"batch_{run_id}"
        run_root = args.batch_root / run_id
        cmd = _build_pipeline_args(args)

        completed_before = i - 1
        progress_before = (100.0 * float(completed_before) / float(total_trials)) if total_trials > 0 else 100.0
        print(
            f"[{i}/{total_trials}] {run_name} starting... "
            f"overall_progress={completed_before}/{total_trials} ({progress_before:.1f}%)"
        )
        if args.dry_run:
            print("  DRY RUN:", " ".join(cmd), f"combo={combo_key}")
            continue

        trial_started = time.perf_counter()
        status = "ok"
        error_msg = ""
        attempt = 0
        max_attempts = max(1, args.trial_retries + 1)
        while attempt < max_attempts:
            attempt += 1
            try:
                log_path = log_dir / f"{run_name}.log"
                with log_path.open("a", buffering=1) as lf:
                    lf.write(f"=== Trial {run_name} attempt {attempt}/{max_attempts} ===\n")
                    lf.write(f"Command: {' '.join(cmd)}\n")
                    lf.write(f"Combo: {combo_key}\n")
                    lf.flush()

                    proc = subprocess.Popen(
                        cmd,
                        env=trial_env,
                        stdout=lf,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    start_wait = time.monotonic()
                    last_hb = start_wait
                    timeout_s = None if args.trial_timeout_sec <= 0 else float(args.trial_timeout_sec)

                    while True:
                        rc = proc.poll()
                        now = time.monotonic()
                        if rc is not None:
                            if rc == 0:
                                status = "ok"
                                error_msg = ""
                            else:
                                status = "failed"
                                error_msg = f"exit code {rc}"
                                lf.write(f"[grid_search] trial failed rc={rc}\n")
                            break

                        if timeout_s is not None and (now - start_wait) > timeout_s:
                            status = "timeout"
                            error_msg = f"timeout after {args.trial_timeout_sec}s"
                            lf.write(f"[grid_search] timeout reached; terminating trial\n")
                            proc.terminate()
                            try:
                                proc.wait(timeout=20)
                            except subprocess.TimeoutExpired:
                                proc.kill()
                                proc.wait()
                            break

                        hb = int(args.heartbeat_sec)
                        if hb > 0 and (now - last_hb) >= hb:
                            elapsed_hb = int(now - start_wait)
                            lf.write(
                                f"[grid_search] heartbeat run={run_name} "
                                f"attempt={attempt}/{max_attempts} elapsed_s={elapsed_hb}\n"
                            )
                            lf.flush()
                            print(
                                f"[{i}/{total_trials}] {run_name} heartbeat: {elapsed_hb}s elapsed "
                                f"(attempt {attempt}/{max_attempts}) "
                                f"overall_progress={completed_before}/{total_trials} ({progress_before:.1f}%)"
                            )
                            last_hb = now

                        time.sleep(1.0)
                if status == "ok":
                    break
            except subprocess.TimeoutExpired as e:
                status = "timeout"
                error_msg = f"timeout after {args.trial_timeout_sec}s"
                log_path = log_dir / f"{run_name}.log"
                out = (e.stdout or "") if isinstance(e.stdout, str) else ""
                err = (e.stderr or "") if isinstance(e.stderr, str) else ""
                log_path.write_text(out + ("\n" + err if err else ""))
            except subprocess.CalledProcessError as e:
                status = "failed"
                error_msg = f"exit code {e.returncode}"
                log_path = log_dir / f"{run_name}.log"
                out = (e.stdout or "") if isinstance(e.stdout, str) else ""
                err = (e.stderr or "") if isinstance(e.stderr, str) else ""
                log_path.write_text(out + ("\n" + err if err else ""))
            except OSError as e:
                status = "failed"
                error_msg = f"launch error: {e}"
                log_path = log_dir / f"{run_name}.log"
                with log_path.open("a", buffering=1) as lf:
                    lf.write(f"[grid_search] launch error: {e}\n")
            except Exception as e:  # keep long runs alive on unexpected per-trial errors
                status = "failed"
                error_msg = f"unexpected error: {e}"
                log_path = log_dir / f"{run_name}.log"
                with log_path.open("a", buffering=1) as lf:
                    lf.write(f"[grid_search] unexpected error: {e}\n")

            if attempt < max_attempts:
                print(f"  retrying {run_name} ({attempt}/{max_attempts-1} retries used)...")

        summary_rows = _read_csv_rows(run_root / "summary.csv")
        imm_rows = _read_csv_rows(run_root / "charts" / "imm_diagnostics_summary.csv")

        containment = _safe_mean(_to_floats(summary_rows, "spoofer_containment_rate_aware"))
        loc_rmse = _safe_mean(_to_floats(summary_rows, "localization_rmse_m_aware"))
        nees_in95 = _safe_mean(_to_floats(imm_rows, "imm_nees_in_95pct_fraction"))
        nis_in95 = _safe_mean(_to_floats(imm_rows, "imm_nis_in_95pct_fraction"))
        nmac_proximity_mean = _safe_mean(_to_floats(summary_rows, "nmac_proximity_aware"))
        nmac_benign_spoofer_mean = _safe_mean(_to_floats(summary_rows, "nmac_benign_spoofer_aware"))
        nmac_spoofer_unsafe_mean = _safe_mean(_to_floats(summary_rows, "nmac_spoofer_unsafe_aware"))
        total_nmac_real_mean = (
            nmac_proximity_mean + nmac_benign_spoofer_mean
            if (nmac_proximity_mean == nmac_proximity_mean and nmac_benign_spoofer_mean == nmac_benign_spoofer_mean)
            else float("nan")
        )
        score = _score_trial(
            containment,
            loc_rmse,
            nees_in95,
            nis_in95,
            total_nmac_real_mean,
            nmac_spoofer_unsafe_mean,
            args.weight_containment,
            args.weight_nees95,
            args.weight_nis95,
            args.weight_rmse,
            args.weight_total_nmac_real,
            args.weight_nmac_spoofer_unsafe,
        )
        elapsed = time.perf_counter() - trial_started

        containment_std = _metric(summary_rows, "spoofer_containment_rate_aware", "std")
        containment_min = _metric(summary_rows, "spoofer_containment_rate_aware", "min")
        containment_max = _metric(summary_rows, "spoofer_containment_rate_aware", "max")
        loc_rmse_med = _metric(summary_rows, "localization_rmse_m_aware", "median")
        loc_rmse_std = _metric(summary_rows, "localization_rmse_m_aware", "std")
        detection_latency = _metric(summary_rows, "detection_latency_s_aware", "mean")
        localization_mae = _metric(summary_rows, "localization_mae_m_aware", "mean")
        detection_reports_total = _metric(summary_rows, "detection_reports_total_aware", "mean")
        detection_mlat_attempted = _metric(summary_rows, "detection_mlat_attempted_aware", "mean")
        detection_mlat_skipped = _metric(
            summary_rows,
            "detection_mlat_skipped_insufficient_receivers_aware",
            "mean",
        )
        detection_mlat_skip_fraction = _metric(
            summary_rows,
            "detection_mlat_skipped_insufficient_receivers_fraction_aware",
            "mean",
        )
        imm_nees_mean = _metric(imm_rows, "imm_nees_mean", "mean")
        imm_nees_std = _metric(imm_rows, "imm_nees_mean", "std")
        imm_nis_mean = _metric(imm_rows, "imm_nis_mix_mean", "mean")
        imm_nis_std = _metric(imm_rows, "imm_nis_mix_mean", "std")
        if status == "ok" and containment == containment and containment < args.min_containment:
            status = "low_containment"
            error_msg = f"containment<{args.min_containment}"

        row: dict[str, float | str] = {
            "trial_index": i,
            "combo_key": combo_key,
            "status": status,
            "error": error_msg,
            "elapsed_sec": elapsed,
            "run_name": run_name,
            "run_root": str(run_root),
            "score": score,
            "containment_rate_mean": containment,
            "localization_rmse_mean_m": loc_rmse,
            "imm_nees_in_95pct_fraction_mean": nees_in95,
            "imm_nis_in_95pct_fraction_mean": nis_in95,
            "containment_rate_std": containment_std,
            "containment_rate_min": containment_min,
            "containment_rate_max": containment_max,
            "localization_rmse_median_m": loc_rmse_med,
            "localization_rmse_std_m": loc_rmse_std,
            "nmac_proximity_mean_aware": nmac_proximity_mean,
            "nmac_benign_spoofer_mean_aware": nmac_benign_spoofer_mean,
            "total_nmac_real_mean_aware": total_nmac_real_mean,
            "nmac_spoofer_unsafe_mean_aware": nmac_spoofer_unsafe_mean,
            "detection_latency_mean_s": detection_latency,
            "localization_mae_mean_m": localization_mae,
            "detection_reports_total_mean_aware": detection_reports_total,
            "detection_mlat_attempted_mean_aware": detection_mlat_attempted,
            "detection_mlat_skipped_insufficient_receivers_mean_aware": detection_mlat_skipped,
            "detection_mlat_skipped_insufficient_receivers_fraction_mean_aware": detection_mlat_skip_fraction,
            "imm_nees_mean": imm_nees_mean,
            "imm_nees_std": imm_nees_std,
            "imm_nis_mean": imm_nis_mean,
            "imm_nis_std": imm_nis_std,
        }
        for k, v in zip(keys, combo):
            row[k] = v
        results.append(row)
        _append_result_row(out_csv, fieldnames, row)
        completed_after = i
        progress_after = (100.0 * float(completed_after) / float(total_trials)) if total_trials > 0 else 100.0
        print(
            f"[{i}/{total_trials}] {run_name} done: "
            f"status={status} score={score:.4f} containment={containment:.4f} "
            f"rmse={loc_rmse:.4f} nees95={nees_in95:.4f} nis95={nis_in95:.4f} "
            f"nmac_real={total_nmac_real_mean:.2f} nmac_unsafe={nmac_spoofer_unsafe_mean:.2f} "
            f"lat={detection_latency:.3f}s "
            f"overall_progress={completed_after}/{total_trials} ({progress_after:.1f}%)"
        )
        if status != "ok" and args.fail_fast:
            print(f"Fail-fast enabled; stopping at {run_name} ({status}).")
            break

    if args.dry_run:
        elapsed_wall = time.perf_counter() - started_wall
        print(
            f"=== IMM_GRID_SEARCH_FINISHED status=DRY_RUN trials_attempted=0 "
            f"trials_ok=0 elapsed_s={elapsed_wall:.1f} timestamp={datetime.now().astimezone().isoformat()} ==="
        )
        return 0

    ok_results = [r for r in results if str(r.get("status", "")).lower() == "ok"]
    ok_results.sort(
        key=lambda r: (
            float("-inf")
            if isinstance(r["score"], float) and (r["score"] != r["score"])
            else float(r["score"])
        ),
        reverse=True,
    )
    print(f"Updated {out_csv}")
    if ok_results:
        best = ok_results[0]
        print(f"Best run: {best['run_name']} score={best['score']}")
        top_k = ok_results[: max(1, args.top_k)]
        print("Top runs:")
        for r in top_k:
            print(
                f"  {r['run_name']}: score={float(r['score']):.4f} "
                f"contain={float(r['containment_rate_mean']):.4f} "
                f"rmse={float(r['localization_rmse_mean_m']):.4f} "
                f"nees95={float(r['imm_nees_in_95pct_fraction_mean']):.4f} "
                f"nis95={float(r['imm_nis_in_95pct_fraction_mean']):.4f} "
                f"nmac_real={float(r['total_nmac_real_mean_aware']):.2f} "
                f"nmac_unsafe={float(r['nmac_spoofer_unsafe_mean_aware']):.2f}"
            )
        summary_md = args.summary_md or (args.batch_root / "imm_grid_search_summary.md")
        lines = [
            "# IMM Grid Search Summary",
            "",
            f"- Trials attempted: {len(results)}",
            f"- Successful trials: {len(ok_results)}",
            f"- Results CSV: `{out_csv}`",
            "",
            "## Best Run",
            "",
            f"- Run: `{best['run_name']}`",
            f"- Score: `{best['score']}`",
            f"- Containment mean: `{best['containment_rate_mean']}`",
            f"- RMSE mean (m): `{best['localization_rmse_mean_m']}`",
            f"- NEES95 mean: `{best['imm_nees_in_95pct_fraction_mean']}`",
            f"- NIS95 mean: `{best['imm_nis_in_95pct_fraction_mean']}`",
            f"- Total NMAC (real) mean: `{best['total_nmac_real_mean_aware']}`",
            f"- NMAC spoofer-unsafe mean: `{best['nmac_spoofer_unsafe_mean_aware']}`",
            "",
            "## Top Configurations",
            "",
            "| Run | Score | Containment | RMSE m | NEES95 | NIS95 | NMAC real | NMAC unsafe |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in top_k:
            lines.append(
                f"| {r['run_name']} | {float(r['score']):.4f} | "
                f"{float(r['containment_rate_mean']):.4f} | "
                f"{float(r['localization_rmse_mean_m']):.4f} | "
                f"{float(r['imm_nees_in_95pct_fraction_mean']):.4f} | "
                f"{float(r['imm_nis_in_95pct_fraction_mean']):.4f} | "
                f"{float(r['total_nmac_real_mean_aware']):.2f} | "
                f"{float(r['nmac_spoofer_unsafe_mean_aware']):.2f} |"
            )
        summary_md.write_text("\n".join(lines) + "\n")
        print(f"Wrote {summary_md}")
        elapsed_wall = time.perf_counter() - started_wall
        print(
            f"=== IMM_GRID_SEARCH_FINISHED status=OK trials_attempted={len(results)} "
            f"trials_ok={len(ok_results)} best_run={best['run_name']} "
            f"best_score={float(best['score']):.6g} elapsed_s={elapsed_wall:.1f} "
            f"timestamp={datetime.now().astimezone().isoformat()} ==="
        )
    elif results:
        print("No successful trial to rank (all failed/timed out).")
        elapsed_wall = time.perf_counter() - started_wall
        print(
            f"=== IMM_GRID_SEARCH_FINISHED status=FAILED trials_attempted={len(results)} "
            f"trials_ok=0 elapsed_s={elapsed_wall:.1f} "
            f"timestamp={datetime.now().astimezone().isoformat()} ==="
        )
    else:
        elapsed_wall = time.perf_counter() - started_wall
        print(
            f"=== IMM_GRID_SEARCH_FINISHED status=NO_TRIALS trials_attempted=0 "
            f"trials_ok=0 elapsed_s={elapsed_wall:.1f} "
            f"timestamp={datetime.now().astimezone().isoformat()} ==="
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
