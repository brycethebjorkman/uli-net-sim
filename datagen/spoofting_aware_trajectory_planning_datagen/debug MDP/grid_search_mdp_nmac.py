#!/usr/bin/env python3
"""
Grid-search MDP planner constants for lower NMAC in 12x1 scenarios.

This script modifies constants in:
  pymodules/controllers/mdp_trajectory_planner.py

Target constants (default block around lines 52-64):
  GOAL_REWARD, GOAL_DISCOUNT,
  AGENT_REWARD, AGENT_DISCOUNT, AGENT_LIMIT,
  SPOOFER_REWARD, SPOOFER_DISCOUNT, SPOOFER_LIMIT,
  ELLIPSOID_MARGIN

For each parameter combination, it:
  1) writes constants into mdp_trajectory_planner.py
  2) runs run_spoofing_aware_trajectory_planning_batch.sh for Scenario_Hub_12x1
  3) reads <run_root>/summary.csv
  4) computes mean NMAC metrics and objective
  5) writes a results CSV leaderboard

The original MDP file is restored automatically at exit.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import re
import subprocess
import sys
import time
from pathlib import Path
from statistics import mean


DEFAULT_MDP_FILE = Path("pymodules/controllers/mdp_trajectory_planner.py")
DEFAULT_BATCH_ROOT = Path("simulations/spoofing_aware_with_planning/batches_mdp_grid")
DEFAULT_SCENARIO = "Scenario_Hub_12x1"

PARAM_KEYS = [
    "GOAL_REWARD",
    "GOAL_DISCOUNT",
    "AGENT_REWARD",
    "AGENT_DISCOUNT",
    "AGENT_LIMIT",
    "SPOOFER_REWARD",
    "SPOOFER_DISCOUNT",
    "SPOOFER_LIMIT",
    "ELLIPSOID_MARGIN",
]


def parse_float_list(raw: str) -> list[float]:
    vals: list[float] = []
    for tok in raw.split(","):
        t = tok.strip()
        if not t:
            continue
        vals.append(float(t))
    if not vals:
        raise ValueError(f"Empty list: {raw!r}")
    return vals


def format_value(v: float) -> str:
    return f"{float(v):.12g}"


def set_constant(src: str, key: str, value: float) -> str:
    pat = re.compile(rf"^(?P<lhs>{re.escape(key)}\s*=\s*)(?P<rhs>[^\n#]*)(?P<tail>[^\n]*)$", re.MULTILINE)
    m = pat.search(src)
    if not m:
        raise ValueError(f"Constant not found in file: {key}")
    repl = f"{m.group('lhs')}{format_value(value)}{m.group('tail')}"
    return src[: m.start()] + repl + src[m.end() :]


def apply_constants(src: str, params: dict[str, float]) -> str:
    out = src
    for k, v in params.items():
        out = set_constant(out, k, v)
    return out


def next_run_id(batch_root: Path) -> str:
    mx = 0
    if batch_root.exists():
        for child in batch_root.iterdir():
            if not child.is_dir():
                continue
            n = child.name
            if len(n) == 4 and n.isdigit():
                mx = max(mx, int(n))
    return f"{mx + 1:04d}"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def col_mean(rows: list[dict[str, str]], key: str) -> float:
    vals: list[float] = []
    for r in rows:
        raw = r.get(key, "")
        if not raw:
            continue
        try:
            vals.append(float(raw))
        except ValueError:
            continue
    return mean(vals) if vals else float("nan")


def run_trial(
    args: argparse.Namespace,
    run_name: str,
) -> tuple[int, str]:
    runner = Path("datagen/spoofting_aware_trajectory_planning_datagen/run_spoofing_aware_trajectory_planning_batch.sh")
    cmd = [
        "bash",
        str(runner),
        "--scenario-config",
        args.scenario_config,
        "--seeds",
        args.seeds,
        "--parallel",
        str(args.parallel),
        "--batch-root",
        str(args.batch_root),
        "--image",
        args.image,
    ]
    if args.skip_build:
        cmd.append("--skip-build")
    if args.no_plot:
        cmd.append("--no-plot")
    if args.no_export_vectors:
        cmd.append("--no-export-vectors")
    if args.no_keep_vec:
        cmd.append("--no-keep-vec")

    print(f"[{run_name}] running: {' '.join(cmd)}")
    started = time.perf_counter()
    rc = subprocess.run(cmd, check=False).returncode
    elapsed = time.perf_counter() - started
    print(f"[{run_name}] exit={rc} elapsed_s={elapsed:.1f}")
    return rc, f"{elapsed:.3f}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Grid-search MDP constants for NMAC minimization.")
    ap.add_argument("--mdp-file", type=Path, default=DEFAULT_MDP_FILE)
    ap.add_argument("--batch-root", type=Path, default=DEFAULT_BATCH_ROOT)
    ap.add_argument("--results-csv", type=Path, default=None)
    ap.add_argument("--scenario-config", type=str, default=DEFAULT_SCENARIO)
    ap.add_argument("--seeds", type=str, default="0:9")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--image", type=str, default="uli-net-sim:latest")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--no-plot", action="store_true")
    ap.add_argument("--no-export-vectors", action="store_true")
    ap.add_argument("--no-keep-vec", action="store_true")
    ap.add_argument("--max-trials", type=int, default=0, help="0 means all combinations.")
    ap.add_argument("--fail-fast", action="store_true")
    ap.add_argument("--dry-run", action="store_true")

    # Search grids (comma-separated)
    ap.add_argument("--goal-reward", type=str, default="500")
    ap.add_argument("--goal-discount", type=str, default="0.997")
    ap.add_argument("--agent-reward", type=str, default="9000")
    ap.add_argument("--agent-discount", type=str, default="0.99")
    ap.add_argument("--agent-limit", type=str, default="150")
    ap.add_argument("--spoofer-reward", type=str, default="9000")
    ap.add_argument("--spoofer-discount", type=str, default="0.99")
    ap.add_argument("--spoofer-limit", type=str, default="150")
    ap.add_argument("--ellipsoid-margin", type=str, default="1.0")
    args = ap.parse_args(argv)

    grids = {
        "GOAL_REWARD": parse_float_list(args.goal_reward),
        "GOAL_DISCOUNT": parse_float_list(args.goal_discount),
        "AGENT_REWARD": parse_float_list(args.agent_reward),
        "AGENT_DISCOUNT": parse_float_list(args.agent_discount),
        "AGENT_LIMIT": parse_float_list(args.agent_limit),
        "SPOOFER_REWARD": parse_float_list(args.spoofer_reward),
        "SPOOFER_DISCOUNT": parse_float_list(args.spoofer_discount),
        "SPOOFER_LIMIT": parse_float_list(args.spoofer_limit),
        "ELLIPSOID_MARGIN": parse_float_list(args.ellipsoid_margin),
    }

    keys = list(grids.keys())
    combos = list(itertools.product(*(grids[k] for k in keys)))
    if args.max_trials > 0:
        combos = combos[: args.max_trials]

    args.batch_root.mkdir(parents=True, exist_ok=True)
    out_csv = args.results_csv or (args.batch_root / "mdp_grid_search_results.csv")

    mdp_path = args.mdp_file
    if not mdp_path.is_file():
        raise FileNotFoundError(f"MDP file not found: {mdp_path}")
    original = mdp_path.read_text()

    fieldnames = [
        "trial_index",
        "status",
        "run_id",
        "run_root",
        "elapsed_sec",
        "nmac_proximity_aware_mean",
        "nmac_benign_spoofer_aware_mean",
        "nmac_spoofer_unsafe_aware_mean",
        "objective_total_nmac_mean",
    ] + keys

    need_header = not out_csv.exists() or out_csv.stat().st_size == 0
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    print(f"Trials: {len(combos)}")
    print(f"Results CSV: {out_csv}")

    try:
        with out_csv.open("a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if need_header:
                writer.writeheader()

            for i, combo in enumerate(combos, start=1):
                params = {k: float(v) for k, v in zip(keys, combo)}
                run_id = next_run_id(args.batch_root)
                run_root = args.batch_root / run_id
                status = "ok"
                elapsed_s = "0.0"
                nmac_p = float("nan")
                nmac_bs = float("nan")
                nmac_u = float("nan")

                print(f"[{i}/{len(combos)}] run_id={run_id} params={params}")

                trial_src = apply_constants(original, params)
                mdp_path.write_text(trial_src)

                if args.dry_run:
                    status = "dry_run"
                else:
                    rc, elapsed_s = run_trial(args, f"trial_{i}")
                    if rc != 0:
                        status = f"failed_rc_{rc}"
                    else:
                        rows = read_csv_rows(run_root / "summary.csv")
                        nmac_p = col_mean(rows, "nmac_proximity_aware")
                        nmac_bs = col_mean(rows, "nmac_benign_spoofer_aware")
                        nmac_u = col_mean(rows, "nmac_spoofer_unsafe_aware")

                objective = (
                    (nmac_p if nmac_p == nmac_p else 0.0)
                    + (nmac_bs if nmac_bs == nmac_bs else 0.0)
                    + (nmac_u if nmac_u == nmac_u else 0.0)
                ) if status == "ok" else float("nan")

                row = {
                    "trial_index": i,
                    "status": status,
                    "run_id": run_id,
                    "run_root": str(run_root),
                    "elapsed_sec": elapsed_s,
                    "nmac_proximity_aware_mean": nmac_p,
                    "nmac_benign_spoofer_aware_mean": nmac_bs,
                    "nmac_spoofer_unsafe_aware_mean": nmac_u,
                    "objective_total_nmac_mean": objective,
                }
                row.update(params)
                writer.writerow(row)
                f.flush()

                if status != "ok":
                    print(f"  -> status={status}")
                    if args.fail_fast and not args.dry_run:
                        print("Fail-fast enabled; stopping.")
                        break
                else:
                    print(
                        "  -> NMAC means: "
                        f"proximity={nmac_p:.3f}, benign_spoofer={nmac_bs:.3f}, "
                        f"spoofer_unsafe={nmac_u:.3f}, objective={objective:.3f}"
                    )
    finally:
        mdp_path.write_text(original)
        print(f"Restored original constants in {mdp_path}")

    print(f"Done. Results written to {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

