#!/usr/bin/env python3
"""
regenerate_from_manifest.py

Regenerate corridors, buildings, and trajectories from a top-level manifest.json.
This allows regeneration after cleanup_generated.sh has removed these artifacts.

USAGE:
    # Regenerate artifacts for a specific corridor
    python3 regenerate_from_manifest.py <manifest.json> <corridor_key>
    python3 regenerate_from_manifest.py datasets/scitech26/manifest.json grid535_hosts9_sim504/ew4_ns5_w37_sp100

    # Regenerate artifacts for all corridors
    python3 regenerate_from_manifest.py <manifest.json> --all

    # Dry run
    python3 regenerate_from_manifest.py <manifest.json> --all --dry-run

The script reads the top-level manifest.json and regenerates:
- corridors.ndjson
- buildings/*.xml
- trajectories/*.xml
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def find_tool(name: str) -> Path:
    """Find a tool in the same directory as this script."""
    script_dir = Path(__file__).parent
    tool_path = script_dir / name
    if not tool_path.exists():
        raise FileNotFoundError(f"Tool not found: {tool_path}")
    return tool_path


def regenerate_corridor(corridor_dir: Path, corridor_info: dict, dry_run: bool = False) -> bool:
    """Regenerate artifacts for a single corridor from manifest info."""
    corridor = corridor_info.get("corridor", {})
    grid_size = corridor_info.get("grid_size", corridor.get("grid_size"))
    buildings = corridor_info.get("buildings", [])
    trajectories = corridor_info.get("trajectories", [])

    # Find generation tools
    gen_corridors = find_tool("generate_corridors.py")
    gen_buildings = find_tool("generate_buildings.py")
    gen_trajectories = find_tool("generate_trajectories.py")

    # Track what was regenerated
    regenerated = []

    # Create directory structure
    corridor_dir.mkdir(parents=True, exist_ok=True)

    # Regenerate corridors.ndjson if missing
    corridors_file = corridor_dir / "corridors.ndjson"
    if not corridors_file.exists():
        cmd = [
            sys.executable, str(gen_corridors),
            "--grid-size", str(grid_size),
            "--num-ew", str(corridor["num_ew"]),
            "--num-ns", str(corridor["num_ns"]),
            "--width", str(corridor["width"]),
            "--spacing", str(corridor["spacing"]),
            "--seed", str(corridor["seed"]),
            "-o", str(corridors_file)
        ]
        if dry_run:
            print(f"  [dry-run] Would generate: {corridors_file}")
        else:
            print(f"  Generating: {corridors_file}")
            subprocess.run(cmd, check=True)
        regenerated.append("corridors.ndjson")
    else:
        print(f"  Exists: {corridors_file}")

    # Regenerate buildings
    buildings_dir = corridor_dir / "buildings"
    buildings_dir.mkdir(exist_ok=True)
    for bldg in buildings:
        if bldg.get("num", 0) == 0:
            continue  # No buildings for this variant
        bldg_name = f"n{bldg['num']}_h{bldg['height']}_seed{bldg['seed']}.xml"
        bldg_file = buildings_dir / bldg_name
        if not bldg_file.exists():
            cmd = [
                sys.executable, str(gen_buildings),
                "-c", str(corridors_file),
                "--num-buildings", str(bldg["num"]),
                "--grid-size", str(grid_size),
                "--height", bldg["height"],
                "--seed", str(bldg["seed"]),
                "--format", "xml",
                "-o", str(bldg_file)
            ]
            if dry_run:
                print(f"  [dry-run] Would generate: {bldg_file}")
            else:
                print(f"  Generating: {bldg_file}")
                subprocess.run(cmd, check=True)
            regenerated.append(f"buildings/{bldg_name}")
        else:
            print(f"  Exists: {bldg_file}")

    # Regenerate trajectories
    trajectories_dir = corridor_dir / "trajectories"
    trajectories_dir.mkdir(exist_ok=True)
    for traj in trajectories:
        traj_name = f"spd{traj['speed']}_alt{traj['altitude']}_seed{traj['seed']}.xml"
        traj_file = trajectories_dir / traj_name
        if not traj_file.exists():
            cmd = [
                sys.executable, str(gen_trajectories),
                "-c", str(corridors_file),
                "--hosts", str(traj["hosts"]),
                "--grid-size", str(grid_size),
                "--min-duration", str(traj["min_duration"]),
                "--speed", traj["speed"],
                "--altitude", traj["altitude"],
                "--seed", str(traj["seed"]),
                "-o", str(traj_file)
            ]
            if dry_run:
                print(f"  [dry-run] Would generate: {traj_file}")
            else:
                print(f"  Generating: {traj_file}")
                subprocess.run(cmd, check=True)
            regenerated.append(f"trajectories/{traj_name}")
        else:
            print(f"  Exists: {traj_file}")

    return len(regenerated) > 0


def main():
    parser = argparse.ArgumentParser(
        description='Regenerate artifacts from top-level manifest.json'
    )
    parser.add_argument('manifest', type=Path,
                        help='Path to top-level manifest.json')
    parser.add_argument('corridor', nargs='?',
                        help='Corridor key (e.g., grid535_hosts9_sim504/ew4_ns5_w37_sp100)')
    parser.add_argument('--all', action='store_true',
                        help='Regenerate all corridors')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be regenerated without doing it')

    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"Error: Manifest not found: {args.manifest}")
        sys.exit(1)

    if not args.corridor and not args.all:
        print("Error: Must specify either a corridor key or --all")
        sys.exit(1)

    # Load manifest
    with open(args.manifest) as f:
        manifest = json.load(f)

    corridors = manifest.get("corridors", {})
    if not corridors:
        print("Error: No corridors found in manifest")
        sys.exit(1)

    # Determine base directory (urbanenv is sibling to manifest.json)
    base_dir = args.manifest.parent / "urbanenv"

    if args.all:
        # Regenerate all corridors
        print(f"Regenerating {len(corridors)} corridors...")
        regenerated_count = 0
        for corridor_key, corridor_info in sorted(corridors.items()):
            corridor_dir = base_dir / corridor_key
            print(f"\n{corridor_key}:")
            if regenerate_corridor(corridor_dir, corridor_info, args.dry_run):
                regenerated_count += 1

        print(f"\nRegenerated artifacts in {regenerated_count}/{len(corridors)} corridors")
    else:
        # Single corridor
        if args.corridor not in corridors:
            print(f"Error: Corridor '{args.corridor}' not found in manifest")
            print(f"Available corridors: {list(corridors.keys())[:5]}...")
            sys.exit(1)

        corridor_dir = base_dir / args.corridor
        print(f"Regenerating: {args.corridor}")
        regenerate_corridor(corridor_dir, corridors[args.corridor], args.dry_run)


if __name__ == '__main__':
    main()
