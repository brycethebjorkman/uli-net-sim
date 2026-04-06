#!/usr/bin/env python3
"""
generate_dataset.py

End-to-end pipeline for generating Remote ID spoofing detection datasets.
Generates corridor-constrained urban environments with buildings.

USAGE:
    cd /usr/uli-net-sim/uav_rid
    python3 datagen/generate_dataset.py [options]

    # Or via the venv:
    .venv/bin/python datagen/generate_dataset.py --scenario-variants 10
"""

import argparse
import json
import os
import random
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJ_DIR = SCRIPT_DIR.parent

# Ensure project root is on sys.path so datagen.* imports work when
# invoked as a standalone script.
if str(PROJ_DIR) not in sys.path:
    sys.path.insert(0, str(PROJ_DIR))

# Paths to urbanenv generation tools
GEN_CORRIDORS = SCRIPT_DIR / "urbanenv" / "generate_corridors.py"
GEN_BUILDINGS = SCRIPT_DIR / "urbanenv" / "generate_buildings.py"
GEN_TRAJECTORIES = SCRIPT_DIR / "urbanenv" / "generate_trajectories.py"
GEN_SCENARIO = SCRIPT_DIR / "urbanenv" / "generate_conf.py"
GEN_MANIFEST = SCRIPT_DIR / "urbanenv" / "generate_dataset_manifest.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sample_range_int(range_str: str, seed: int) -> int:
    """Sample an integer from a range string like '10-20' or '15'."""
    if "-" in range_str:
        lo, hi = range_str.split("-", 1)
        rng = random.Random(seed)
        return rng.randint(int(lo), int(hi))
    return int(range_str)


def sample_range(range_str: str, seed: int) -> float:
    """Sample a float from a range string like '10.0-20.0' or '15'."""
    if "-" in range_str:
        lo, hi = range_str.split("-", 1)
        rng = random.Random(seed)
        return round(lo_f + rng.random() * (float(hi) - (lo_f := float(lo))), 2)
    return float(range_str)


def run_tool(args: list, cwd: Path | None = None, label: str = "") -> subprocess.CompletedProcess:
    """Run a subprocess, raising on failure."""
    result = subprocess.run(
        [str(a) for a in args],
        capture_output=True, text=True, cwd=str(cwd) if cwd else None,
    )
    if result.returncode != 0:
        tag = f"[{label}] " if label else ""
        raise RuntimeError(
            f"{tag}Command failed (exit {result.returncode}): "
            f"{' '.join(str(a) for a in args)}\n"
            f"stderr: {result.stderr[-2000:]}"
        )
    return result


def source_omnetpp_env():
    """Ensure OMNeT++ environment is available, sourcing omnetpp-env.sh if needed."""
    if os.environ.get("INET_ROOT"):
        return
    env_script = PROJ_DIR / "scripts" / "omnetpp-env.sh"
    if not env_script.exists():
        return
    # Source the script in a subshell and capture the resulting env
    result = subprocess.run(
        ["bash", "-c", f"source {env_script} && env -0"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        for entry in result.stdout.split("\0"):
            if "=" in entry:
                key, _, value = entry.partition("=")
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Phase 1: Generate configurations
# ---------------------------------------------------------------------------

def generate_configs(args) -> list[Path]:
    """Generate all corridor/building/trajectory/ini configurations.

    Returns list of scenario directory paths for simulation.
    """
    urbanenv_dir = Path(args.output) / "urbanenv"
    urbanenv_dir.mkdir(parents=True, exist_ok=True)

    scenarios: list[Path] = []
    scenario_seed_counter = args.seed

    for p in range(args.param_variants):
        param_seed = args.seed + p * 10000

        grid = sample_range_int(args.grid_size, param_seed)
        hosts = sample_range_int(args.num_hosts, param_seed + 1)
        sim_time = sample_range_int(args.sim_time, param_seed + 2)

        param_dir_name = f"grid{grid}_hosts{hosts}_sim{sim_time}"
        print(f"  Parameter set {p + 1}/{args.param_variants}: {param_dir_name}")

        for c in range(args.corridor_variants):
            corridor_seed = param_seed + c * 1000

            num_ew = sample_range_int(args.num_ew, corridor_seed)
            num_ns = sample_range_int(args.num_ns, corridor_seed + 1)
            corr_width = sample_range_int(args.corridor_width, corridor_seed + 2)
            corr_spacing = sample_range_int(args.corridor_spacing, corridor_seed + 3)

            corridor_dir_name = f"ew{num_ew}_ns{num_ns}_w{corr_width}_sp{corr_spacing}"
            corridor_path = urbanenv_dir / param_dir_name / corridor_dir_name
            print(f"    Corridor {c + 1}/{args.corridor_variants}: {corridor_dir_name}")

            corridor_path.mkdir(parents=True, exist_ok=True)
            (corridor_path / "buildings").mkdir(exist_ok=True)
            (corridor_path / "trajectories").mkdir(exist_ok=True)
            (corridor_path / "scenarios").mkdir(exist_ok=True)

            # Generate corridors
            corridors_file = corridor_path / "corridors.ndjson"
            if not corridors_file.exists():
                print("      [corridors] Generating...")
                run_tool([
                    sys.executable, GEN_CORRIDORS,
                    "--grid-size", str(grid),
                    "--num-ew", str(num_ew), "--num-ns", str(num_ns),
                    "--width", str(corr_width), "--spacing", str(corr_spacing),
                    "--seed", str(corridor_seed),
                    "-o", str(corridors_file),
                ])

            # Generate building variants
            building_files = []
            for b in range(args.building_variants):
                building_seed = corridor_seed + b * 100
                num_bldg = sample_range_int(args.num_buildings, building_seed)
                bldg_height = args.building_height

                if num_bldg == 0:
                    building_files.append(None)
                    print(f"      [buildings {b + 1}/{args.building_variants}] No buildings")
                else:
                    bldg_name = f"n{num_bldg}_h{bldg_height}_seed{building_seed}"
                    bldg_file = corridor_path / "buildings" / f"{bldg_name}.xml"
                    building_files.append(bldg_file)

                    if not bldg_file.exists():
                        print(f"      [buildings {b + 1}/{args.building_variants}] Generating {bldg_name}...")
                        run_tool([
                            sys.executable, GEN_BUILDINGS,
                            "-c", str(corridors_file),
                            "--num-buildings", str(num_bldg),
                            "--grid-size", str(grid),
                            "--height", bldg_height,
                            "--seed", str(building_seed),
                            "--format", "xml",
                            "-o", str(bldg_file),
                        ])

            # Generate trajectory variants
            trajectory_files = []
            for t in range(args.trajectory_variants):
                trajectory_seed = corridor_seed + 50 + t * 100

                traj_name = f"spd{args.speed}_alt{args.altitude}_seed{trajectory_seed}"
                traj_file = corridor_path / "trajectories" / f"{traj_name}.xml"
                trajectory_files.append(traj_file)

                if not traj_file.exists():
                    print(f"      [trajectories {t + 1}/{args.trajectory_variants}] Generating {traj_name}...")
                    run_tool([
                        sys.executable, GEN_TRAJECTORIES,
                        "-c", str(corridors_file),
                        "--hosts", str(hosts),
                        "--grid-size", str(grid),
                        "--min-duration", str(sim_time),
                        "--speed", args.speed,
                        "--altitude", args.altitude,
                        "--seed", str(trajectory_seed),
                        "-o", str(traj_file),
                    ])

            # Generate scenario ini files
            for b in range(args.building_variants):
                bldg_file = building_files[b]
                bldg_part = "bldg_none" if bldg_file is None else f"bldg_{bldg_file.stem}"

                for t in range(args.trajectory_variants):
                    traj_file = trajectory_files[t]
                    traj_part = f"traj_{traj_file.stem}"

                    for s in range(args.scenario_variants):
                        scenario_seed = scenario_seed_counter
                        scenario_seed_counter += 1

                        scenario_name = f"{bldg_part}__{traj_part}__seed{scenario_seed}"
                        scenario_path = corridor_path / "scenarios" / scenario_name
                        scenario_path.mkdir(parents=True, exist_ok=True)

                        ini_file = scenario_path / "omnetpp.ini"

                        if not ini_file.exists():
                            print(f"      [{len(scenarios) + 1}] Generating {scenario_name}")
                            cmd = [
                                sys.executable, GEN_SCENARIO,
                                "-t", str(traj_file),
                                "--tx-power", args.tx_power,
                                "--beacon-interval", args.beacon_interval,
                                "--beacon-offset", args.beacon_offset,
                                "--background-noise", str(args.background_noise),
                                "--obstacle-loss", args.obstacle_loss,
                                "--max-bounces", str(args.max_bounces),
                                "--sim-time-limit", str(sim_time),
                                "--config-name", "Scenario",
                                "--seed", str(scenario_seed),
                                "-o", str(ini_file),
                            ]
                            if bldg_file is not None:
                                cmd.extend(["-b", str(bldg_file)])
                            if args.enable_spoofer:
                                cmd.extend(["--enable-spoofer", "--spoofer-type", args.spoofer_type])

                            run_tool(cmd)

                        scenarios.append(scenario_path)

    return scenarios


# ---------------------------------------------------------------------------
# Phase 2: Run simulations
# ---------------------------------------------------------------------------

def _run_one_scenario(item: tuple[str, str | None, list[str]]) -> None:
    """Worker function for parallel scenario execution."""
    from datagen.run_scenario import run_scenario
    scenario_path, venv_python, configs = item
    run_scenario(Path(scenario_path), venv_python=venv_python,
                 configs=configs)


def run_simulations(scenarios: list[Path], parallel: int,
                    venv_python: str | None = None):
    """Run all scenario simulations, optionally in parallel."""
    total = len(scenarios)
    print(f"\nPHASE 2: Running {total} simulations (parallel={parallel})\n")

    # Determine which configs each scenario has (OpenSpace always;
    # WithBuildings only if present in INI).
    items = []
    for sp in scenarios:
        ini_text = (sp / "omnetpp.ini").read_text()
        configs = ["ScenarioOpenSpace"]
        if "ScenarioWithBuildings" in ini_text:
            configs.append("ScenarioWithBuildings")
        items.append((str(sp), venv_python, configs))

    if parallel <= 1:
        for i, item in enumerate(items):
            print(f"[{i + 1}/{total}] Running {Path(item[0]).name}...")
            _run_one_scenario(item)
    else:
        print(f"Running {total} scenarios with {parallel} parallel jobs...\n")
        with ProcessPoolExecutor(max_workers=parallel) as pool:
            list(pool.map(_run_one_scenario, items))


# ---------------------------------------------------------------------------
# Phase 3: Generate manifest
# ---------------------------------------------------------------------------

def generate_manifest(args, urbanenv_dir: Path):
    """Generate top-level dataset manifest."""
    print("\nPHASE 3: Generating dataset manifest\n")

    gen_params = {
        "seed": args.seed,
        "grid_size": args.grid_size,
        "num_hosts": args.num_hosts,
        "sim_time": args.sim_time,
        "num_ew": args.num_ew,
        "num_ns": args.num_ns,
        "corridor_width": args.corridor_width,
        "corridor_spacing": args.corridor_spacing,
        "num_buildings": args.num_buildings,
        "building_height": args.building_height,
        "speed": args.speed,
        "altitude": args.altitude,
        "tx_power": args.tx_power,
        "beacon_interval": args.beacon_interval,
        "beacon_offset": args.beacon_offset,
        "background_noise": args.background_noise,
        "obstacle_loss": args.obstacle_loss,
        "max_bounces": args.max_bounces,
        "enable_spoofer": args.enable_spoofer,
        "spoofer_type": args.spoofer_type,
    }

    branching = {
        "param_variants": args.param_variants,
        "corridor_variants": args.corridor_variants,
        "building_variants": args.building_variants,
        "trajectory_variants": args.trajectory_variants,
        "scenario_variants": args.scenario_variants,
    }

    manifest_path = Path(args.output) / "manifest.json"

    run_tool([
        sys.executable, GEN_MANIFEST, "from-existing", str(urbanenv_dir),
        "-o", str(manifest_path),
        "--generation-params", json.dumps(gen_params),
        "--branching", json.dumps(branching),
    ])

    print(f"Manifest: {manifest_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate Remote ID spoofing detection datasets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    g = parser.add_argument_group("Parameter ranges (use 'min-max' for ranges)")
    g.add_argument("--grid-size", default="400")
    g.add_argument("--num-hosts", default="5")
    g.add_argument("--sim-time", default="300")

    g = parser.add_argument_group("Corridor parameters")
    g.add_argument("--num-ew", default="2")
    g.add_argument("--num-ns", default="2")
    g.add_argument("--corridor-width", default="20")
    g.add_argument("--corridor-spacing", default="120")

    g = parser.add_argument_group("Building parameters")
    g.add_argument("--num-buildings", default="20")
    g.add_argument("--building-height", default="60-150")

    g = parser.add_argument_group("Trajectory parameters")
    g.add_argument("--speed", default="5-15")
    g.add_argument("--altitude", default="30-100")

    g = parser.add_argument_group("Radio parameters")
    g.add_argument("--tx-power", default="10-16")
    g.add_argument("--beacon-interval", default="0.25-0.75")
    g.add_argument("--beacon-offset", default="0-0.1")
    g.add_argument("--background-noise", type=float, default=-90)
    g.add_argument("--obstacle-loss", default="DielectricObstacleLoss",
                   choices=["DielectricObstacleLoss", "ImageMethodObstacleLoss"])
    g.add_argument("--max-bounces", type=int, default=1)

    g = parser.add_argument_group("Spoofer configuration")
    g.add_argument("--enable-spoofer", action="store_true")
    g.add_argument("--spoofer-type", default="dynamic_trajectory",
                   choices=["dynamic_trajectory", "snow_plow"])

    g = parser.add_argument_group("Branching factors")
    g.add_argument("--param-variants", type=int, default=1)
    g.add_argument("--corridor-variants", type=int, default=1)
    g.add_argument("--building-variants", type=int, default=1)
    g.add_argument("--trajectory-variants", type=int, default=1)
    g.add_argument("--scenario-variants", type=int, default=1)

    g = parser.add_argument_group("Execution")
    g.add_argument("--parallel", type=int, default=1,
                   help="Parallel jobs (0 = auto-detect)")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("-o", "--output", default=str(PROJ_DIR / "datasets"))

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # Auto-detect parallelism
    if args.parallel == 0:
        args.parallel = os.cpu_count() or 4

    total = (args.param_variants * args.corridor_variants *
             args.building_variants * args.trajectory_variants *
             args.scenario_variants)

    print("=" * 50)
    print("Remote ID Dataset Generation Pipeline")
    print("=" * 50)
    print(f"Total scenarios: {total}")
    print(f"Parallel jobs:   {args.parallel}")
    print(f"Output:          {args.output}")
    print("=" * 50)

    # Ensure OMNeT++ env is available
    source_omnetpp_env()

    # Check for required tools
    for tool in [GEN_CORRIDORS, GEN_BUILDINGS, GEN_TRAJECTORIES, GEN_SCENARIO]:
        if not tool.exists():
            print(f"Error: Required tool not found: {tool}")
            sys.exit(1)

    # Determine venv python for vec2parquet (needs pyarrow)
    venv_python = str(PROJ_DIR / ".venv" / "bin" / "python3")
    if not Path(venv_python).exists():
        venv_python = None  # Fall back to sys.executable

    # Phase 1
    print("\nPHASE 1: Generating scenario configurations\n")
    scenarios = generate_configs(args)
    print(f"\nPhase 1 complete: {len(scenarios)} scenario configurations generated\n")

    # Phase 2
    run_simulations(scenarios, args.parallel, venv_python)

    # Phase 3
    urbanenv_dir = Path(args.output) / "urbanenv"
    generate_manifest(args, urbanenv_dir)

    print(f"\nDataset generation complete! ({len(scenarios)} scenarios)")


if __name__ == "__main__":
    main()
