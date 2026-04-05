#!/usr/bin/env python3
"""
regenerate_scenario.py

Regenerate simulation artifacts and re-run simulations for specific scenarios
from a dataset manifest.

Given a manifest and one or more per-scenario parquet file paths, this script
deterministically regenerates all intermediate artifacts (corridors, buildings,
trajectories, scenario INI) and re-runs the OMNeT++ simulation to reproduce
the parquet output.

USAGE:
    python3 regenerate_scenario.py <manifest.json> <file.parquet> [file2.parquet ...]

    # Dry run - show what would be done
    python3 regenerate_scenario.py <manifest.json> <file.parquet> --dry-run

    # Skip artifact regeneration (assume corridors/buildings/trajectories exist)
    python3 regenerate_scenario.py <manifest.json> <file.parquet> --skip-artifacts
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def find_script_dir() -> Path:
    """Find the datagen scripts directory."""
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
        not corridors_file.exists()
        or not buildings_dir.exists()
        or (buildings_dir.exists() and not any(buildings_dir.glob("*.xml")))
        or not trajectories_dir.exists()
        or (trajectories_dir.exists() and not any(trajectories_dir.glob("*.xml")))
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


def regenerate_ini(scenario_path: Path, corridor_path: Path, corridor_info: dict,
                   scenario_info: dict, generation_params: dict,
                   dry_run: bool = False) -> bool:
    """Regenerate the scenario omnetpp.ini from manifest parameters."""
    script_dir = find_script_dir()
    gen_scenario = script_dir / "urbanenv" / "generate_scenario.py"

    ini_path = scenario_path / "omnetpp.ini"
    if ini_path.exists():
        print(f"  INI already exists: {ini_path}")
        return True

    # Find trajectory file from seed
    traj_seed = scenario_info["trajectory_seed"]
    traj_dir = corridor_path / "trajectories"
    traj_files = list(traj_dir.glob(f"*_seed{traj_seed}.xml"))
    if not traj_files:
        print(f"Error: No trajectory file found for seed {traj_seed} in {traj_dir}")
        return False
    traj_file = traj_files[0]

    # Find building file from seed (may be None)
    bldg_file = None
    bldg_seed = scenario_info.get("building_seed")
    if bldg_seed is not None:
        bldg_dir = corridor_path / "buildings"
        bldg_files = list(bldg_dir.glob(f"*_seed{bldg_seed}.xml"))
        if bldg_files:
            bldg_file = bldg_files[0]

    # Build generate_scenario.py arguments
    sim_time = corridor_info.get("sim_time", generation_params.get("sim_time", 300))
    cmd = [
        sys.executable, str(gen_scenario),
        "-t", str(traj_file),
        "--tx-power", str(generation_params.get("tx_power", "10-16")),
        "--beacon-interval", str(generation_params.get("beacon_interval", "0.25-0.75")),
        "--beacon-offset", str(generation_params.get("beacon_offset", "0-0.1")),
        "--background-noise", str(generation_params.get("background_noise", -90)),
        "--obstacle-loss", str(generation_params.get("obstacle_loss", "DielectricObstacleLoss")),
        "--max-bounces", str(generation_params.get("max_bounces", 1)),
        "--sim-time-limit", str(sim_time),
        "--config-name", "Scenario",
        "--seed", str(scenario_info["scenario_seed"]),
        "-o", str(ini_path),
    ]

    if bldg_file:
        cmd.extend(["-b", str(bldg_file)])

    # Use explicit ghost/spoofer hosts to avoid re-randomization
    ghost_host = scenario_info.get("ghost_host")
    spoofer_host = scenario_info.get("spoofer_host")
    spoofer_type = generation_params.get("spoofer_type", "dynamic_trajectory")

    if ghost_host is not None and spoofer_host is not None:
        cmd.extend(["--ghost-host", str(ghost_host),
                     "--spoofer-host", str(spoofer_host),
                     "--spoofer-type", spoofer_type])
    elif spoofer_host is not None:
        # snow_plow spoofer (no ghost host)
        cmd.extend(["--spoofer-host", str(spoofer_host),
                     "--spoofer-type", spoofer_type])

    scenario_path.mkdir(parents=True, exist_ok=True)

    if dry_run:
        print(f"  [dry-run] Would generate INI: {ini_path}")
        return True

    print(f"  Generating INI: {ini_path}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error generating INI: {result.stderr}")
        return False

    return True


def run_scenario(scenario_path: Path, spoofer_host, config: str,
                 parquet_name: str, dry_run: bool = False) -> bool:
    """Run the simulation for a specific scenario and config."""
    script_dir = find_script_dir()
    proj_dir = script_dir.parent
    run_sh = proj_dir / "scripts" / "run.sh"
    vec2pq = script_dir / "vec2parquet.py"

    if not run_sh.exists():
        print(f"Error: run.sh not found at {run_sh}")
        return False

    ini_path = scenario_path / "omnetpp.ini"
    result_dir = scenario_path / "results"

    cmd_desc = f"{scenario_path.name}/{config}"

    if dry_run:
        print(f"  [dry-run] Would run simulation: {cmd_desc}")
        print(f"  [dry-run] Would produce: {parquet_name}")
        return True

    # Run simulation
    print(f"  Running simulation: {cmd_desc}")
    result_dir.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [str(run_sh), "-f", "omnetpp.ini", "-c", config, "-r", str(result_dir), "-q"],
        cwd=str(scenario_path), capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"Error running simulation: {result.stderr[-2000:]}")
        return False

    # Convert to parquet
    vec_file = result_dir / f"{config}-#0.vec"
    if not vec_file.exists():
        print(f"Error: Vector file not found: {vec_file}")
        return False

    pq_path = scenario_path / parquet_name
    print(f"  Converting to parquet: {parquet_name}")

    vec2pq_args = [sys.executable, str(vec2pq), str(vec_file), "-o", str(pq_path)]
    if spoofer_host is not None:
        vec2pq_args.extend(["--spoofer-hosts", str(spoofer_host)])

    result = subprocess.run(vec2pq_args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error converting to parquet: {result.stderr[-2000:]}")
        return False

    # Clean up intermediate results
    import shutil
    shutil.rmtree(result_dir, ignore_errors=True)

    return True


def regenerate_one(manifest: dict, manifest_path: Path, parquet_name: str,
                   dry_run: bool = False, skip_artifacts: bool = False) -> bool:
    """Regenerate a single scenario parquet from the manifest."""
    scenarios = manifest.get("scenarios", {})
    if parquet_name not in scenarios:
        print(f"Error: '{parquet_name}' not found in manifest")
        available = sorted(scenarios.keys())[:5]
        print(f"Available scenarios ({len(scenarios)} total): {available}...")
        return False

    scenario_info = scenarios[parquet_name]
    corridor_key = scenario_info["corridor"]

    corridors = manifest.get("corridors", {})
    if corridor_key not in corridors:
        print(f"Error: Corridor '{corridor_key}' not found in manifest")
        return False

    corridor_info = corridors[corridor_key]
    generation_params = manifest.get("generation_params", {})

    print(f"Corridor: {corridor_key}")
    print(f"Scenario: {scenario_info['scenario_dir']}")
    print(f"Config: {scenario_info['config']}")

    # Determine paths
    manifest_dir = manifest_path.parent
    urbanenv_dir = manifest_dir / "urbanenv"
    corridor_path = urbanenv_dir / corridor_key
    scenario_path = corridor_path / "scenarios" / scenario_info["scenario_dir"]

    # Step 1: Regenerate artifacts if needed
    if not skip_artifacts:
        print("\nStep 1: Checking/regenerating artifacts...")
        if not regenerate_artifacts(manifest_path, corridor_key, corridor_path, dry_run):
            print("Error: Failed to regenerate artifacts")
            return False

    # Step 2: Regenerate INI if needed
    print("\nStep 2: Checking/regenerating scenario INI...")
    if not regenerate_ini(scenario_path, corridor_path, corridor_info,
                          scenario_info, generation_params, dry_run):
        print("Error: Failed to regenerate INI")
        return False

    # Step 3: Run simulation
    print("\nStep 3: Running simulation...")
    spoofer_host = scenario_info.get("spoofer_host")
    config = scenario_info["config"]

    if not run_scenario(scenario_path, spoofer_host, config, parquet_name, dry_run):
        print("Error: Simulation failed")
        return False

    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Regenerate scenario simulations from a dataset manifest',
        epilog="""
Examples:
  # Regenerate one scenario
  %(prog)s datasets/scitech26/manifest.json abc123-o.parquet

  # Regenerate multiple scenarios
  %(prog)s datasets/scitech26/manifest.json abc-o.parquet def-b.parquet

  # Dry run
  %(prog)s datasets/scitech26/manifest.json abc-o.parquet --dry-run
"""
    )
    parser.add_argument('manifest', type=Path, help='Path to manifest.json')
    parser.add_argument('parquet_files', nargs='+',
                        help='Parquet file paths (basenames used for manifest lookup)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without executing')
    parser.add_argument('--skip-artifacts', action='store_true',
                        help='Skip artifact regeneration (assume they exist)')

    args = parser.parse_args(argv)

    # Load manifest
    if not args.manifest.exists():
        print(f"Error: Manifest not found: {args.manifest}")
        sys.exit(1)

    with open(args.manifest) as f:
        manifest = json.load(f)

    # Process each parquet file
    failed = []
    for pq_path in args.parquet_files:
        parquet_name = Path(pq_path).name

        print("=" * 60)
        print(f"Regenerating: {parquet_name}")
        print("=" * 60)

        success = regenerate_one(manifest, args.manifest, parquet_name,
                                 dry_run=args.dry_run,
                                 skip_artifacts=args.skip_artifacts)
        if not success:
            failed.append(parquet_name)

        print()

    # Summary
    total = len(args.parquet_files)
    ok = total - len(failed)
    print("=" * 60)
    print(f"Regeneration complete: {ok}/{total} succeeded")
    if failed:
        print(f"Failed: {failed}")
        sys.exit(1)
    print("=" * 60)


if __name__ == '__main__':
    main()
