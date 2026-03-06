#!/usr/bin/env python3
"""
regenerate_csv.py

Regenerate a specific CSV file from the dataset manifest.

This script:
1. Looks up the CSV in the manifest to find its generation parameters
2. Regenerates artifacts (corridors, buildings, trajectories) if missing
3. Re-runs the simulation to produce the CSV

USAGE:
    python3 regenerate_csv.py <manifest.json> <csv_filename>
    python3 regenerate_csv.py datasets/scitech26/manifest.json 872368be-b.csv

    # Dry run - show what would be done without executing
    python3 regenerate_csv.py datasets/scitech26/manifest.json 872368be-b.csv --dry-run
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def find_script_dir() -> Path:
    """Find the container scripts directory."""
    return Path(__file__).parent


def regenerate_artifacts(manifest_path: Path, corridor_key: str, corridor_path: Path,
                         dry_run: bool = False) -> bool:
    """Regenerate corridors, buildings, trajectories if missing."""
    script_dir = find_script_dir()
    regen_script = script_dir / "urbanenv" / "regenerate_from_manifest.py"

    if not regen_script.exists():
        print(f"Error: regenerate_from_manifest.py not found at {regen_script}")
        return False

    # Check if artifacts exist
    corridors_file = corridor_path / "corridors.ndjson"
    buildings_dir = corridor_path / "buildings"
    trajectories_dir = corridor_path / "trajectories"

    needs_regen = (
        not corridors_file.exists() or
        not buildings_dir.exists() or
        not any(buildings_dir.glob("*.xml")) if buildings_dir.exists() else True or
        not trajectories_dir.exists() or
        not any(trajectories_dir.glob("*.xml")) if trajectories_dir.exists() else True
    )

    if not needs_regen:
        print(f"Artifacts already exist in {corridor_path}")
        return True

    print(f"Regenerating artifacts for {corridor_key}...")

    if dry_run:
        print(f"  [dry-run] Would run: python3 {regen_script} {manifest_path} {corridor_key}")
        return True

    result = subprocess.run(
        [sys.executable, str(regen_script), str(manifest_path), corridor_key],
        capture_output=False
    )

    return result.returncode == 0


def run_scenario(scenario_path: Path, spoofer_host: int, dry_run: bool = False) -> bool:
    """Run the simulation for a specific scenario."""
    script_dir = find_script_dir()
    run_script = script_dir / "run_scenario.sh"

    if not run_script.exists():
        print(f"Error: run_scenario.sh not found at {run_script}")
        return False

    # Set up environment variables
    env = os.environ.copy()

    # Try to set required env vars from known paths
    proj_dir = script_dir.parent
    base_dir = proj_dir.parent

    env.setdefault("PROJ_DIR", str(proj_dir))
    env.setdefault("UAV_RID_BIN", str(base_dir / "container-build" / "out" / "clang-release" / "uav_rid"))
    env.setdefault("INET_ROOT", str(base_dir / "inet4.5"))
    env.setdefault("VEC2CSV", str(script_dir / "vec2csv.py"))
    env.setdefault("ADD_HOST_TYPE", str(script_dir / "add_host_type.py"))

    # Validate binary exists
    if not Path(env["UAV_RID_BIN"]).exists():
        print(f"Error: UAV_RID_BIN not found at {env['UAV_RID_BIN']}")
        print("Please run: ./container/build.sh")
        return False

    # Format spoofer_host (use "-" for None)
    spoofer_arg = str(spoofer_host) if spoofer_host is not None else "-"

    cmd = [
        str(run_script),
        str(scenario_path),
        spoofer_arg
    ]

    print(f"Running scenario: {scenario_path.name}")
    print(f"  spoofer_host={spoofer_arg}")

    if dry_run:
        print(f"  [dry-run] Would run: {' '.join(cmd)}")
        return True

    result = subprocess.run(cmd, env=env)
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(
        description='Regenerate a CSV file from the dataset manifest'
    )
    parser.add_argument('manifest', type=Path, help='Path to manifest.json')
    parser.add_argument('csv_name', help='CSV filename to regenerate (e.g., 872368be-b.csv)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without executing')
    parser.add_argument('--skip-artifacts', action='store_true',
                        help='Skip artifact regeneration (assume they exist)')

    args = parser.parse_args()

    # Load manifest
    if not args.manifest.exists():
        print(f"Error: Manifest not found: {args.manifest}")
        sys.exit(1)

    with open(args.manifest) as f:
        manifest = json.load(f)

    # Look up CSV
    csv_name = args.csv_name
    if csv_name not in manifest.get("scenarios", {}):
        print(f"Error: CSV '{csv_name}' not found in manifest")
        print(f"Available CSVs: {len(manifest.get('scenarios', {}))} entries")
        sys.exit(1)

    scenario_info = manifest["scenarios"][csv_name]
    corridor_key = scenario_info["corridor"]

    if corridor_key not in manifest.get("corridors", {}):
        print(f"Error: Corridor '{corridor_key}' not found in manifest")
        sys.exit(1)

    corridor_info = manifest["corridors"][corridor_key]

    print("=" * 60)
    print(f"Regenerating: {csv_name}")
    print("=" * 60)
    print(f"Corridor: {corridor_key}")
    print(f"Scenario: {scenario_info['scenario_dir']}")
    print(f"Config: {scenario_info['config']}")
    print(f"Building seed: {scenario_info['building_seed']}")
    print(f"Trajectory seed: {scenario_info['trajectory_seed']}")
    print(f"Scenario seed: {scenario_info['scenario_seed']}")
    print(f"Ghost host: {scenario_info['ghost_host']}")
    print(f"Spoofer host: {scenario_info['spoofer_host']}")
    print()

    # Determine paths
    manifest_dir = args.manifest.parent
    urbanenv_dir = manifest_dir / "urbanenv"
    corridor_path = urbanenv_dir / corridor_key
    scenario_path = corridor_path / "scenarios" / scenario_info["scenario_dir"]

    if not scenario_path.exists():
        print(f"Error: Scenario directory not found: {scenario_path}")
        sys.exit(1)

    # Step 1: Regenerate artifacts if needed
    if not args.skip_artifacts:
        print("Step 1: Checking/regenerating artifacts...")
        if not regenerate_artifacts(args.manifest, corridor_key, corridor_path, args.dry_run):
            print("Error: Failed to regenerate artifacts")
            sys.exit(1)
        print()

    # Step 2: Run simulation
    print("Step 2: Running simulation...")

    success = run_scenario(
        scenario_path=scenario_path,
        spoofer_host=scenario_info["spoofer_host"],
        dry_run=args.dry_run
    )

    if not success:
        print("Error: Simulation failed")
        sys.exit(1)

    print()
    print("=" * 60)
    print(f"Regeneration complete!")
    print(f"CSV location: {scenario_path / csv_name}")
    print("=" * 60)


if __name__ == '__main__':
    main()
