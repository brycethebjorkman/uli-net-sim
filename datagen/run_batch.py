#!/usr/bin/env python3
"""
run_batch.py

Generic batch simulation runner.  Works with any OMNeT++ INI files —
urbanenv-generated scenarios, hand-crafted experiment configs, or a mix.

USAGE:
    # Run all scenarios under a dataset directory (discovers omnetpp.ini files)
    python3 datagen/run_batch.py datasets/snowplow26/urbanenv/ --parallel 4

    # Run specific leaf configs from a hand-crafted INI
    python3 datagen/run_batch.py simulations/snow_plow_spoofer/ \
        --configs SnowPlowVsKf SnowPlowVsCombined --parallel 4

    # Run all leaf configs, keep .vec/.sca for online metric extraction
    python3 datagen/run_batch.py simulations/spoofing_aware_with_planning/ \
        --keep-vec --parallel 4

    # Dry run — list what would be executed without running anything
    python3 datagen/run_batch.py simulations/snow_plow_spoofer/ --dry-run
"""

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJ_DIR = SCRIPT_DIR.parent

# Ensure project root is on sys.path so datagen.* imports work when
# invoked as a standalone script.
if str(PROJ_DIR) not in sys.path:
    sys.path.insert(0, str(PROJ_DIR))

from datagen.run_scenario import (
    find_leaf_configs,
    pick_vec2parquet_python,
    run_scenario,
)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_scenarios(root: Path, configs: list[str] | None = None,
                       ) -> list[tuple[Path, list[str]]]:
    """Find (scenario_dir, config_list) pairs under *root*.

    If *root* is a directory containing ``omnetpp.ini``, it is treated as a
    single scenario.  Otherwise every sub-directory containing ``omnetpp.ini``
    is collected.

    When *configs* is given it is used verbatim for every scenario; otherwise
    each INI's leaf configs are auto-detected.
    """
    root = root.resolve()
    ini_at_root = root / "omnetpp.ini"

    if ini_at_root.is_file():
        scenario_dirs = [root]
    else:
        scenario_dirs = sorted(
            p.parent for p in root.rglob("omnetpp.ini"))

    results: list[tuple[Path, list[str]]] = []
    for d in scenario_dirs:
        cfgs = configs or find_leaf_configs(d / "omnetpp.ini")
        if cfgs:
            results.append((d, cfgs))

    return results


# ---------------------------------------------------------------------------
# Parallel execution
# ---------------------------------------------------------------------------

def _worker(item: tuple[str, list[str], str | None, bool]) -> list[str]:
    """Process-pool worker.  Returns list of produced parquet paths (as str)."""
    scenario_path, configs, venv_python, keep_vec = item
    produced = run_scenario(
        Path(scenario_path),
        venv_python=venv_python,
        configs=configs,
        keep_vec=keep_vec,
    )
    return [str(p) for p in produced]


def run_batch(scenarios: list[tuple[Path, list[str]]],
              parallel: int = 1,
              venv_python: str | None = None,
              keep_vec: bool = False) -> list[Path]:
    """Run all scenarios, optionally in parallel.

    Returns list of all produced parquet file paths.
    """
    total_configs = sum(len(cfgs) for _, cfgs in scenarios)
    n_scen = len(scenarios)
    print(
        f"Running {n_scen} scenario(s), {total_configs} config(s), "
        f"parallel={parallel}\n"
        f"(Each scenario = one INI directory; progress prints when that "
        f"directory finishes.)\n",
        flush=True,
    )

    items = [(str(d), cfgs, venv_python, keep_vec) for d, cfgs in scenarios]

    all_produced: list[Path] = []
    if parallel <= 1:
        for i, item in enumerate(items):
            name = Path(item[0]).name
            print(f"[{i + 1}/{n_scen}] {name} ...", flush=True)
            paths = _worker(item)
            all_produced.extend(Path(p) for p in paths)
            print(f"[{i + 1}/{n_scen}] {name} done ({len(paths)} parquet)", flush=True)
    else:
        with ProcessPoolExecutor(max_workers=parallel) as pool:
            futures = {
                pool.submit(_worker, item): Path(item[0]).name
                for item in items
            }
            done = 0
            for fut in as_completed(futures):
                name = futures[fut]
                done += 1
                paths = fut.result()
                all_produced.extend(Path(p) for p in paths)
                print(
                    f"[{done}/{n_scen}] finished {name} "
                    f"({len(paths)} parquet)",
                    flush=True,
                )

    print(f"\nDone — {len(all_produced)} parquet file(s) produced.", flush=True)
    return all_produced


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Batch-run OMNeT++ scenarios (simulation + parquet)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "path", type=Path,
        help="Directory containing omnetpp.ini (single scenario) or parent "
             "directory to search recursively")
    parser.add_argument(
        "--configs", nargs="+", default=None,
        help="Config name(s) to run in each INI (default: auto-detect leaves)")
    parser.add_argument(
        "--keep-vec", action="store_true",
        help="Keep .vec/.sca result files after parquet conversion")
    parser.add_argument(
        "--parallel", type=int, default=1,
        help="Number of parallel jobs (0 = auto-detect cores)")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List what would be run without executing anything")
    args = parser.parse_args(argv)

    if args.parallel == 0:
        args.parallel = os.cpu_count() or 4

    if not args.path.exists():
        parser.error(f"Path does not exist: {args.path}")

    scenarios = discover_scenarios(args.path, configs=args.configs)
    if not scenarios:
        print("No scenarios found.")
        return

    if args.dry_run:
        total = sum(len(cfgs) for _, cfgs in scenarios)
        print(f"Would run {total} config(s) across {len(scenarios)} "
              f"scenario(s):\n")
        for d, cfgs in scenarios:
            for c in cfgs:
                print(f"  {d.name}  →  {c}")
        return

    # vec2parquet needs pyarrow; skip broken/synced .venv (wrong arch)
    venv_python = pick_vec2parquet_python(PROJ_DIR)

    run_batch(scenarios, parallel=args.parallel,
              venv_python=venv_python, keep_vec=args.keep_vec)


if __name__ == "__main__":
    main()
