#!/usr/bin/env python3
"""
generate_dataset_manifest.py

Generate a comprehensive top-level manifest.json for a dataset that traces
all parameters from generation down to individual CSV files.

This manifest allows anyone to:
1. Look up any CSV file to find its generation parameters
2. Regenerate the necessary artifacts (corridors, buildings, trajectories)
3. Re-run the simulation to reproduce the CSV

USAGE:
    # During generation (called by generate_dataset.sh):
    python3 generate_dataset_manifest.py init -o manifest.json \
        --generation-params '{"seed": 42, "grid_size": "500-1000", ...}'

    python3 generate_dataset_manifest.py add-corridor manifest.json \
        --path "grid535_hosts9_sim504/ew4_ns5_w37_sp100" \
        --corridor-params '{"grid_size": 535, ...}'

    python3 generate_dataset_manifest.py add-scenario manifest.json \
        --csv "abc123-o.csv" \
        --scenario-params '{"corridor": "...", "building_seed": 70042, ...}'

    # Retroactive generation from existing dataset:
    python3 generate_dataset_manifest.py from-existing /path/to/urbanenv \
        -o manifest.json --generation-params '...'
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path


def init_manifest(output: Path, generation_params: dict, branching: dict) -> dict:
    """Initialize a new manifest with generation parameters."""
    manifest = {
        "version": "1.0",
        "generated": datetime.utcnow().isoformat() + "Z",
        "generator": "generate_dataset.sh",
        "generation_params": generation_params,
        "branching": branching,
        "corridors": {},
        "scenarios": {}
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"Initialized manifest: {output}")
    return manifest


def load_manifest(path: Path) -> dict:
    """Load existing manifest."""
    with open(path) as f:
        return json.load(f)


def save_manifest(path: Path, manifest: dict):
    """Save manifest to file."""
    with open(path, 'w') as f:
        json.dump(manifest, f, indent=2)


def add_corridor(manifest_path: Path, corridor_path: str, corridor_params: dict):
    """Add or update a corridor entry in the manifest."""
    manifest = load_manifest(manifest_path)
    manifest["corridors"][corridor_path] = corridor_params
    save_manifest(manifest_path, manifest)
    print(f"Added corridor: {corridor_path}")


def add_scenario(manifest_path: Path, csv_name: str, scenario_params: dict):
    """Add a scenario (CSV file) entry to the manifest."""
    manifest = load_manifest(manifest_path)
    manifest["scenarios"][csv_name] = scenario_params
    save_manifest(manifest_path, manifest)


def parse_corridor_dir_name(dir_name: str) -> dict:
    """Parse corridor directory name like 'ew4_ns5_w37_sp100'."""
    match = re.match(r'ew(\d+)_ns(\d+)_w(\d+)_sp(\d+)', dir_name)
    if not match:
        return {}
    return {
        "num_ew": int(match.group(1)),
        "num_ns": int(match.group(2)),
        "width": int(match.group(3)),
        "spacing": int(match.group(4))
    }


def parse_param_dir_name(dir_name: str) -> dict:
    """Parse param directory name like 'grid535_hosts9_sim504'."""
    match = re.match(r'grid(\d+)_hosts(\d+)_sim(\d+)', dir_name)
    if not match:
        return {}
    return {
        "grid_size": int(match.group(1)),
        "num_hosts": int(match.group(2)),
        "sim_time": int(match.group(3))
    }


def parse_building_filename(filename: str) -> dict:
    """Parse building filename like 'n10_h10-100_seed70042.xml'."""
    match = re.match(r'n(\d+)_h([\d-]+)_seed(\d+)\.xml', filename)
    if not match:
        return None
    return {
        "num": int(match.group(1)),
        "height": match.group(2),
        "seed": int(match.group(3))
    }


def parse_trajectory_filename(filename: str) -> dict:
    """Parse trajectory filename like 'spd5-15_alt30-100_seed70092.xml'."""
    match = re.match(r'spd([\d-]+)_alt([\d-]+)_seed(\d+)\.xml', filename)
    if not match:
        return None
    return {
        "speed": match.group(1),
        "altitude": match.group(2),
        "seed": int(match.group(3))
    }


def parse_scenario_dir_name(dir_name: str) -> dict:
    """Parse scenario directory name like 'bldg_n10_h10-100_seed70042__traj_spd5-15_alt30-100_seed70092__seed714'."""
    # Extract building seed
    bldg_match = re.search(r'bldg_n\d+_h[\d-]+_seed(\d+)', dir_name)
    bldg_seed = int(bldg_match.group(1)) if bldg_match else None

    # Handle "bldg_none" case
    if 'bldg_none' in dir_name:
        bldg_seed = None

    # Extract trajectory seed
    traj_match = re.search(r'traj_spd[\d-]+_alt[\d-]+_seed(\d+)', dir_name)
    traj_seed = int(traj_match.group(1)) if traj_match else None

    # Extract scenario seed (the final __seed{N})
    scenario_match = re.search(r'__seed(\d+)$', dir_name)
    scenario_seed = int(scenario_match.group(1)) if scenario_match else None

    return {
        "building_seed": bldg_seed,
        "trajectory_seed": traj_seed,
        "scenario_seed": scenario_seed
    }


def parse_ini_for_spoofer_info(ini_path: Path) -> dict:
    """Extract ghost_host and spoofer_host from omnetpp.ini."""
    info = {"ghost_host": None, "spoofer_host": None}
    try:
        with open(ini_path) as f:
            content = f.read()

        # Look for Parameters JSON in comment
        params_match = re.search(r'# Parameters: ({.*})', content)
        if params_match:
            params = json.loads(params_match.group(1))
            info["ghost_host"] = params.get("ghost_host")
            info["spoofer_host"] = params.get("spoofer_host")
    except Exception:
        pass

    return info


def infer_corridor_seed(building_seeds: list, trajectory_seeds: list) -> int:
    """Infer corridor seed from building/trajectory seeds."""
    # Building seeds follow: corridor_seed + b * 100
    # Trajectory seeds follow: corridor_seed + 50 + t * 100
    # So the minimum building seed should be corridor_seed (when b=0)
    # And minimum trajectory seed should be corridor_seed + 50 (when t=0)

    if building_seeds:
        return min(building_seeds)
    elif trajectory_seeds:
        return min(trajectory_seeds) - 50
    return 0


def generate_from_existing(urbanenv_dir: Path, output: Path, generation_params: dict, branching: dict):
    """Generate manifest from existing dataset directory structure."""

    manifest = {
        "version": "1.0",
        "generated": datetime.utcnow().isoformat() + "Z",
        "generator": "generate_dataset_manifest.py (from-existing)",
        "generation_params": generation_params,
        "branching": branching,
        "corridors": {},
        "scenarios": {}
    }

    # Find all corridor directories (contain scenarios/ subdirectory)
    corridor_count = 0
    scenario_count = 0

    for param_dir in sorted(urbanenv_dir.iterdir()):
        if not param_dir.is_dir():
            continue

        param_info = parse_param_dir_name(param_dir.name)
        if not param_info:
            continue

        for corridor_dir in sorted(param_dir.iterdir()):
            if not corridor_dir.is_dir():
                continue

            scenarios_dir = corridor_dir / "scenarios"
            if not scenarios_dir.exists():
                continue

            corridor_info = parse_corridor_dir_name(corridor_dir.name)
            if not corridor_info:
                continue

            # Relative path for corridor key
            corridor_key = f"{param_dir.name}/{corridor_dir.name}"

            # Collect buildings
            buildings = []
            buildings_dir = corridor_dir / "buildings"
            if buildings_dir.exists():
                for f in sorted(buildings_dir.glob("*.xml")):
                    info = parse_building_filename(f.name)
                    if info:
                        buildings.append(info)

            # Collect trajectories
            trajectories = []
            trajectories_dir = corridor_dir / "trajectories"
            if trajectories_dir.exists():
                for f in sorted(trajectories_dir.glob("*.xml")):
                    info = parse_trajectory_filename(f.name)
                    if info:
                        # Add hosts and min_duration from param_info
                        info["hosts"] = param_info["num_hosts"]
                        info["min_duration"] = param_info["sim_time"]
                        trajectories.append(info)

            # Infer corridor seed
            building_seeds = [b["seed"] for b in buildings]
            trajectory_seeds = [t["seed"] for t in trajectories]
            corridor_seed = infer_corridor_seed(building_seeds, trajectory_seeds)

            # Store corridor info
            manifest["corridors"][corridor_key] = {
                **param_info,
                "corridor": {
                    **corridor_info,
                    "seed": corridor_seed
                },
                "buildings": buildings,
                "trajectories": trajectories
            }
            corridor_count += 1

            # Collect scenarios (CSV files)
            for scenario_dir in sorted(scenarios_dir.iterdir()):
                if not scenario_dir.is_dir():
                    continue

                scenario_info = parse_scenario_dir_name(scenario_dir.name)

                # Get spoofer info from ini
                ini_path = scenario_dir / "omnetpp.ini"
                spoofer_info = parse_ini_for_spoofer_info(ini_path)

                # Find CSV files
                for csv_file in scenario_dir.glob("*.csv"):
                    # Skip federate variants for the main mapping
                    # (they share the same scenario params)
                    if "-f" in csv_file.name:
                        continue

                    # Determine config type from filename suffix
                    if csv_file.name.endswith("-o.csv"):
                        config = "ScenarioOpenSpace"
                    elif csv_file.name.endswith("-b.csv"):
                        config = "ScenarioWithBuildings"
                    else:
                        config = "unknown"

                    manifest["scenarios"][csv_file.name] = {
                        "corridor": corridor_key,
                        "scenario_dir": scenario_dir.name,
                        "building_seed": scenario_info.get("building_seed"),
                        "trajectory_seed": scenario_info.get("trajectory_seed"),
                        "scenario_seed": scenario_info.get("scenario_seed"),
                        "config": config,
                        "ghost_host": spoofer_info.get("ghost_host"),
                        "spoofer_host": spoofer_info.get("spoofer_host")
                    }
                    scenario_count += 1

    # Save manifest
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, 'w') as f:
        json.dump(manifest, f, indent=2)

    print(f"Generated manifest: {output}")
    print(f"  Corridors: {corridor_count}")
    print(f"  Scenarios (CSVs): {scenario_count}")


def main():
    parser = argparse.ArgumentParser(description='Generate dataset manifest')
    subparsers = parser.add_subparsers(dest='command', required=True)

    # init command
    init_parser = subparsers.add_parser('init', help='Initialize new manifest')
    init_parser.add_argument('-o', '--output', type=Path, required=True)
    init_parser.add_argument('--generation-params', type=json.loads, required=True)
    init_parser.add_argument('--branching', type=json.loads, required=True)

    # add-corridor command
    corridor_parser = subparsers.add_parser('add-corridor', help='Add corridor to manifest')
    corridor_parser.add_argument('manifest', type=Path)
    corridor_parser.add_argument('--path', required=True)
    corridor_parser.add_argument('--params', type=json.loads, required=True)

    # add-scenario command
    scenario_parser = subparsers.add_parser('add-scenario', help='Add scenario to manifest')
    scenario_parser.add_argument('manifest', type=Path)
    scenario_parser.add_argument('--csv', required=True)
    scenario_parser.add_argument('--params', type=json.loads, required=True)

    # from-existing command
    existing_parser = subparsers.add_parser('from-existing',
        help='Generate manifest from existing dataset')
    existing_parser.add_argument('urbanenv_dir', type=Path)
    existing_parser.add_argument('-o', '--output', type=Path, required=True)
    existing_parser.add_argument('--generation-params', type=json.loads, default={},
        help='Original generation parameters (optional)')
    existing_parser.add_argument('--branching', type=json.loads, default={},
        help='Branching factors (optional)')

    args = parser.parse_args()

    if args.command == 'init':
        init_manifest(args.output, args.generation_params, args.branching)
    elif args.command == 'add-corridor':
        add_corridor(args.manifest, args.path, args.params)
    elif args.command == 'add-scenario':
        add_scenario(args.manifest, args.csv, args.params)
    elif args.command == 'from-existing':
        generate_from_existing(
            args.urbanenv_dir,
            args.output,
            args.generation_params,
            args.branching
        )


if __name__ == '__main__':
    main()
