#!/usr/bin/env python3
"""
generate_scenario.py

Materialize filesystem artifacts (corridors, buildings, trajectories, INI
files) from a v2 manifest.  Used for both first-time generation and
regeneration — the code path is identical.

USAGE:
    # Materialize everything described in the manifest
    python3 datagen/generate_scenario.py datasets/snowplow26/manifest.json

    # Materialize only specific scenarios (by parquet filename key)
    python3 datagen/generate_scenario.py datasets/snowplow26/manifest.json \\
        --scenarios 872368be-b.parquet abc123-o.parquet

    # Dry run
    python3 datagen/generate_scenario.py datasets/snowplow26/manifest.json --dry-run
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJ_DIR = SCRIPT_DIR.parent
URBANENV = SCRIPT_DIR / "urbanenv"

if str(PROJ_DIR) not in sys.path:
    sys.path.insert(0, str(PROJ_DIR))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(cmd: list, dry_run: bool = False, label: str = "") -> bool:
    """Run a subprocess. Returns True on success."""
    if dry_run:
        print(f"  [dry-run] {label}")
        return True
    print(f"  {label}")
    r = subprocess.run([str(a) for a in cmd], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  ERROR: {r.stderr[-1000:]}", file=sys.stderr)
        return False
    return True


# ---------------------------------------------------------------------------
# Artifact generation
# ---------------------------------------------------------------------------

def generate_corridor_artifacts(corridor_dir: Path, corridor_info: dict,
                                dry_run: bool = False) -> None:
    """Generate corridors.ndjson, buildings/*.xml, trajectories/*.xml."""
    grid_size = corridor_info["grid_size"]
    num_hosts = corridor_info["num_hosts"]
    sim_time = corridor_info["sim_time"]
    corridor = corridor_info["corridor"]

    corridor_dir.mkdir(parents=True, exist_ok=True)

    # --- corridors.ndjson ---
    corridors_file = corridor_dir / "corridors.ndjson"
    if not corridors_file.exists():
        _run([sys.executable, URBANENV / "generate_corridors.py",
              "--grid-size", str(grid_size),
              "--num-ew", str(corridor["num_ew"]),
              "--num-ns", str(corridor["num_ns"]),
              "--width", str(corridor["width"]),
              "--spacing", str(corridor["spacing"]),
              "--seed", str(corridor["seed"]),
              "-o", str(corridors_file)],
             dry_run=dry_run, label=f"corridors → {corridors_file.name}")

    # --- buildings ---
    buildings_dir = corridor_dir / "buildings"
    buildings_dir.mkdir(exist_ok=True)
    for bldg in corridor_info.get("buildings", []):
        if bldg is None or bldg.get("num", 0) == 0:
            continue
        name = f"n{bldg['num']}_h{bldg['height']}_seed{bldg['seed']}.xml"
        bldg_file = buildings_dir / name
        if not bldg_file.exists():
            _run([sys.executable, URBANENV / "generate_buildings.py",
                  "-c", str(corridors_file),
                  "--num-buildings", str(bldg["num"]),
                  "--grid-size", str(grid_size),
                  "--height", bldg["height"],
                  "--seed", str(bldg["seed"]),
                  "--format", "xml",
                  "-o", str(bldg_file)],
                 dry_run=dry_run, label=f"buildings → {name}")

    # --- trajectories ---
    traj_dir = corridor_dir / "trajectories"
    traj_dir.mkdir(exist_ok=True)
    for traj in corridor_info.get("trajectories", []):
        name = f"spd{traj['speed']}_alt{traj['altitude']}_seed{traj['seed']}.xml"
        traj_file = traj_dir / name
        if not traj_file.exists():
            _run([sys.executable, URBANENV / "generate_trajectories.py",
                  "-c", str(corridors_file),
                  "--hosts", str(num_hosts),
                  "--grid-size", str(grid_size),
                  "--min-duration", str(sim_time),
                  "--speed", traj["speed"],
                  "--altitude", traj["altitude"],
                  "--seed", str(traj["seed"]),
                  "-o", str(traj_file)],
                 dry_run=dry_run, label=f"trajectories → {name}")


def generate_ini(scenario_dir: Path, corridor_dir: Path,
                 corridor_info: dict, scenario_info: dict,
                 defaults: dict, dry_run: bool = False) -> None:
    """Generate omnetpp.ini for a single scenario."""
    ini_file = scenario_dir / "omnetpp.ini"
    if ini_file.exists():
        return

    scenario_dir.mkdir(parents=True, exist_ok=True)

    # Resolve trajectory file
    traj_seed = scenario_info["trajectory_seed"]
    traj_files = list((corridor_dir / "trajectories").glob(f"*_seed{traj_seed}.xml"))
    if not traj_files and not dry_run:
        print(f"  ERROR: no trajectory file for seed {traj_seed}", file=sys.stderr)
        return
    traj_file = traj_files[0] if traj_files else Path(f"trajectories/*_seed{traj_seed}.xml")

    # Resolve building file (may be None)
    bldg_file = None
    bldg_seed = scenario_info.get("building_seed")
    if bldg_seed is not None:
        bldg_files = list((corridor_dir / "buildings").glob(f"*_seed{bldg_seed}.xml"))
        if bldg_files:
            bldg_file = bldg_files[0]

    sim_time = corridor_info.get("sim_time", defaults.get("sim_time", 300))

    cmd = [
        sys.executable, URBANENV / "generate_conf.py",
        "-t", str(traj_file),
        "--tx-power", str(defaults.get("tx_power", "10-16")),
        "--beacon-interval", str(defaults.get("beacon_interval", "0.25-0.75")),
        "--beacon-offset", str(defaults.get("beacon_offset", "0-0.1")),
        "--background-noise", str(defaults.get("background_noise", -90)),
        "--obstacle-loss", str(defaults.get("obstacle_loss", "DielectricObstacleLoss")),
        "--max-bounces", str(defaults.get("max_bounces", 1)),
        "--sim-time-limit", str(sim_time),
        "--config-name", "Scenario",
        "--seed", str(scenario_info["scenario_seed"]),
        "-o", str(ini_file),
    ]

    if bldg_file is not None:
        cmd.extend(["-b", str(bldg_file)])

    # Spoofer configuration (use explicit host indices from manifest)
    ghost_host = scenario_info.get("ghost_host")
    spoofer_host = scenario_info.get("spoofer_host")
    spoofer_type = defaults.get("spoofer_type", "dynamic_trajectory")

    if ghost_host is not None and spoofer_host is not None:
        cmd.extend(["--ghost-host", str(ghost_host),
                     "--spoofer-host", str(spoofer_host),
                     "--spoofer-type", spoofer_type])
    elif spoofer_host is not None:
        cmd.extend(["--spoofer-host", str(spoofer_host),
                     "--spoofer-type", spoofer_type])

    _run(cmd, dry_run=dry_run, label=f"INI → {scenario_dir.name}/omnetpp.ini")


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def materialize(manifest_path: Path, scenario_filter: set[str] | None = None,
                dry_run: bool = False) -> None:
    """Materialize all artifacts and INI files from a manifest."""
    with open(manifest_path) as f:
        manifest = json.load(f)

    defaults = manifest.get("defaults", {})
    corridors = manifest.get("corridors", {})
    scenarios = manifest.get("scenarios", {})

    dataset_dir = manifest_path.parent
    urbanenv_dir = dataset_dir / "urbanenv"

    # Determine which corridors are needed
    if scenario_filter:
        needed_corridors = {
            scenarios[s]["corridor"]
            for s in scenario_filter if s in scenarios
        }
        missing = scenario_filter - set(scenarios)
        if missing:
            print(f"Warning: scenarios not in manifest: {missing}",
                  file=sys.stderr)
    else:
        needed_corridors = set(corridors.keys())

    # Phase 1: corridor artifacts
    print(f"Generating artifacts for {len(needed_corridors)} corridor(s)...\n")
    for corridor_key in sorted(needed_corridors):
        if corridor_key not in corridors:
            print(f"Warning: corridor '{corridor_key}' not in manifest",
                  file=sys.stderr)
            continue
        corridor_dir = urbanenv_dir / corridor_key
        print(f"[{corridor_key}]")
        generate_corridor_artifacts(corridor_dir, corridors[corridor_key],
                                    dry_run=dry_run)

    # Phase 2: scenario INI files
    # Group scenarios by (corridor, scenario_dir) to avoid duplicate INI generation
    # (multiple parquet keys can share the same INI, e.g., -o and -b variants)
    seen_ini: set[str] = set()
    ini_count = 0

    if scenario_filter:
        filtered = {k: v for k, v in scenarios.items() if k in scenario_filter}
    else:
        filtered = scenarios

    print(f"\nGenerating INI files for {len(filtered)} scenario(s)...\n")
    for pq_key, sc_info in sorted(filtered.items()):
        corridor_key = sc_info["corridor"]
        scenario_dir_name = sc_info["scenario_dir"]
        ini_id = f"{corridor_key}/{scenario_dir_name}"

        if ini_id in seen_ini:
            continue
        seen_ini.add(ini_id)

        corridor_dir = urbanenv_dir / corridor_key
        scenario_dir = corridor_dir / "scenarios" / scenario_dir_name

        generate_ini(scenario_dir, corridor_dir, corridors.get(corridor_key, {}),
                     sc_info, defaults, dry_run=dry_run)
        ini_count += 1

    action = "Would generate" if dry_run else "Generated"
    print(f"\n{action} {ini_count} INI file(s) across "
          f"{len(needed_corridors)} corridor(s).")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Materialize scenario artifacts and INI files from a manifest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("manifest", type=Path, help="Path to manifest.json")
    parser.add_argument("--scenarios", nargs="+", default=None,
                        help="Only materialize these scenario keys (parquet filenames)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be generated without executing")
    args = parser.parse_args(argv)

    if not args.manifest.exists():
        print(f"Error: manifest not found: {args.manifest}", file=sys.stderr)
        sys.exit(1)

    scenario_filter = set(args.scenarios) if args.scenarios else None
    materialize(args.manifest, scenario_filter=scenario_filter,
                dry_run=args.dry_run)


if __name__ == "__main__":
    main()
