#!/usr/bin/env python3
"""
generate_manifest.py

Create a dataset manifest (the recipe) that fully specifies every scenario
to generate.  The manifest is the source of truth — both first-time generation
and regeneration use the same file.

USAGE:
    # Generate from parameter ranges (standard workflow)
    python3 datagen/generate_manifest.py \\
        --grid-size "500-1000" --num-hosts "6-12" --sim-time "300-570" \\
        --enable-spoofer --spoofer-type snow_plow \\
        --param-variants 25 --corridor-variants 2 \\
        --scenario-variants 6 \\
        -o datasets/snowplow26/manifest.json

    # Migrate an existing (v1) dataset directory into a v2 manifest
    python3 datagen/generate_manifest.py --from-existing datasets/old/urbanenv \\
        -o datasets/old/manifest.json
"""

import argparse
import hashlib
import json
import random
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJ_DIR = SCRIPT_DIR.parent

if str(PROJ_DIR) not in sys.path:
    sys.path.insert(0, str(PROJ_DIR))


# ---------------------------------------------------------------------------
# Helpers (same deterministic sampling as old generate_dataset.py)
# ---------------------------------------------------------------------------

def sample_range_int(range_str: str, seed: int) -> int:
    if "-" in range_str:
        lo, hi = range_str.split("-", 1)
        return random.Random(seed).randint(int(lo), int(hi))
    return int(range_str)


def _scenario_hash(param_dir: str, corridor_dir: str, scenario_name: str) -> str:
    """8-char MD5 hash matching run_scenario.scenario_hash for urbanenv layout."""
    rel = f"{param_dir}/{corridor_dir}/scenarios/{scenario_name}"
    return hashlib.md5(rel.encode()).hexdigest()[:8]


def _select_spoofer(num_hosts: int, spoofer_type: str,
                    seed: int) -> tuple[int | None, int | None]:
    """Replicate generate_conf.py's random spoofer selection for a given seed.

    Returns (ghost_host, spoofer_host).
    """
    rng = random.Random(seed)
    if spoofer_type == "snow_plow":
        return None, rng.randrange(num_hosts)
    else:
        selected = rng.sample(range(num_hosts), 2)
        return selected[0], selected[1]


# ---------------------------------------------------------------------------
# Core: build manifest dict from parameter ranges
# ---------------------------------------------------------------------------

def build_manifest(args) -> dict:
    """Build a v2 manifest dict from CLI args (parameter ranges + branching)."""
    manifest = {
        "version": "2.0",
        "generator": "generate_manifest.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "defaults": {
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
            "conf_generator": "urbanenv",
        },
        "branching": {
            "seed": args.seed,
            "param_variants": args.param_variants,
            "corridor_variants": args.corridor_variants,
            "building_variants": args.building_variants,
            "trajectory_variants": args.trajectory_variants,
            "scenario_variants": args.scenario_variants,
        },
        "corridors": {},
        "scenarios": {},
    }

    scenario_seed_counter = args.seed

    for p in range(args.param_variants):
        param_seed = args.seed + p * 10000

        grid = sample_range_int(args.grid_size, param_seed)
        hosts = sample_range_int(args.num_hosts, param_seed + 1)
        sim_time = sample_range_int(args.sim_time, param_seed + 2)

        param_dir_name = f"grid{grid}_hosts{hosts}_sim{sim_time}"

        for c in range(args.corridor_variants):
            corridor_seed = param_seed + c * 1000

            num_ew = sample_range_int(args.num_ew, corridor_seed)
            num_ns = sample_range_int(args.num_ns, corridor_seed + 1)
            corr_width = sample_range_int(args.corridor_width, corridor_seed + 2)
            corr_spacing = sample_range_int(args.corridor_spacing, corridor_seed + 3)

            corridor_dir_name = f"ew{num_ew}_ns{num_ns}_w{corr_width}_sp{corr_spacing}"
            corridor_key = f"{param_dir_name}/{corridor_dir_name}"

            # Building variants
            buildings = []
            for b in range(args.building_variants):
                building_seed = corridor_seed + b * 100
                num_bldg = sample_range_int(args.num_buildings, building_seed)
                if num_bldg == 0:
                    buildings.append(None)
                else:
                    buildings.append({
                        "num": num_bldg,
                        "height": args.building_height,
                        "seed": building_seed,
                    })

            # Trajectory variants
            trajectories = []
            for t in range(args.trajectory_variants):
                trajectory_seed = corridor_seed + 50 + t * 100
                trajectories.append({
                    "speed": args.speed,
                    "altitude": args.altitude,
                    "seed": trajectory_seed,
                })

            manifest["corridors"][corridor_key] = {
                "grid_size": grid,
                "num_hosts": hosts,
                "sim_time": sim_time,
                "corridor": {
                    "num_ew": num_ew, "num_ns": num_ns,
                    "width": corr_width, "spacing": corr_spacing,
                    "seed": corridor_seed,
                },
                "buildings": buildings,
                "trajectories": trajectories,
            }

            # Scenarios: cross-product of building × trajectory × seed
            for b_idx, bldg in enumerate(buildings):
                bldg_part = "bldg_none" if bldg is None else (
                    f"bldg_n{bldg['num']}_h{bldg['height']}_seed{bldg['seed']}")

                for t_idx, traj in enumerate(trajectories):
                    traj_part = (
                        f"traj_spd{traj['speed']}_alt{traj['altitude']}"
                        f"_seed{traj['seed']}")

                    for s in range(args.scenario_variants):
                        scenario_seed = scenario_seed_counter
                        scenario_seed_counter += 1

                        scenario_name = (
                            f"{bldg_part}__{traj_part}__seed{scenario_seed}")
                        h = _scenario_hash(param_dir_name, corridor_dir_name,
                                           scenario_name)

                        # Determine spoofer hosts (replicates generate_conf.py)
                        ghost_host = spoofer_host = None
                        if args.enable_spoofer:
                            ghost_host, spoofer_host = _select_spoofer(
                                hosts, args.spoofer_type, scenario_seed)

                        # Base scenario entry
                        entry = {
                            "corridor": corridor_key,
                            "scenario_dir": scenario_name,
                            "building_seed": bldg["seed"] if bldg else None,
                            "trajectory_seed": traj["seed"],
                            "scenario_seed": scenario_seed,
                            "ghost_host": ghost_host,
                            "spoofer_host": spoofer_host,
                        }

                        # OpenSpace config (always)
                        manifest["scenarios"][f"{h}-o.parquet"] = {
                            **entry, "config": "ScenarioOpenSpace"}

                        # WithBuildings config (only if buildings present)
                        if bldg is not None:
                            manifest["scenarios"][f"{h}-b.parquet"] = {
                                **entry, "config": "ScenarioWithBuildings"}

    return manifest


# ---------------------------------------------------------------------------
# Migration: build manifest from existing dataset directory (v1 → v2)
# ---------------------------------------------------------------------------

def build_manifest_from_existing(urbanenv_dir: Path) -> dict:
    """Scan an existing urbanenv directory and produce a v2 manifest."""
    manifest = {
        "version": "2.0",
        "generator": "generate_manifest.py (from-existing)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "defaults": {},
        "branching": {},
        "corridors": {},
        "scenarios": {},
    }

    re_param = re.compile(r"grid(\d+)_hosts(\d+)_sim(\d+)")
    re_corridor = re.compile(r"ew(\d+)_ns(\d+)_w(\d+)_sp(\d+)")
    re_building = re.compile(r"n(\d+)_h([\d-]+)_seed(\d+)\.xml")
    re_trajectory = re.compile(r"spd([\d-]+)_alt([\d-]+)_seed(\d+)\.xml")
    re_scenario_dir = re.compile(
        r"bldg_(?:none|n\d+_h[\d-]+_seed(\d+))"
        r"__traj_spd[\d-]+_alt[\d-]+_seed(\d+)"
        r"__seed(\d+)$")

    for param_dir in sorted(urbanenv_dir.iterdir()):
        if not param_dir.is_dir():
            continue
        m_param = re_param.match(param_dir.name)
        if not m_param:
            continue
        grid = int(m_param.group(1))
        hosts = int(m_param.group(2))
        sim_time = int(m_param.group(3))

        for corridor_dir in sorted(param_dir.iterdir()):
            if not corridor_dir.is_dir():
                continue
            m_corr = re_corridor.match(corridor_dir.name)
            if not m_corr:
                continue

            corridor_key = f"{param_dir.name}/{corridor_dir.name}"

            # Collect buildings
            buildings = []
            bldg_dir = corridor_dir / "buildings"
            if bldg_dir.exists():
                for f in sorted(bldg_dir.glob("*.xml")):
                    m = re_building.match(f.name)
                    if m:
                        buildings.append({
                            "num": int(m.group(1)),
                            "height": m.group(2),
                            "seed": int(m.group(3)),
                        })

            # Collect trajectories
            trajectories = []
            traj_dir = corridor_dir / "trajectories"
            if traj_dir.exists():
                for f in sorted(traj_dir.glob("*.xml")):
                    m = re_trajectory.match(f.name)
                    if m:
                        trajectories.append({
                            "speed": m.group(1),
                            "altitude": m.group(2),
                            "seed": int(m.group(3)),
                        })

            # Infer corridor seed
            all_seeds = [b["seed"] for b in buildings] + [t["seed"] for t in trajectories]
            corridor_seed = min(all_seeds) if all_seeds else 0

            manifest["corridors"][corridor_key] = {
                "grid_size": grid,
                "num_hosts": hosts,
                "sim_time": sim_time,
                "corridor": {
                    "num_ew": int(m_corr.group(1)),
                    "num_ns": int(m_corr.group(2)),
                    "width": int(m_corr.group(3)),
                    "spacing": int(m_corr.group(4)),
                    "seed": corridor_seed,
                },
                "buildings": buildings,
                "trajectories": trajectories,
            }

            # Collect scenarios
            scenarios_dir = corridor_dir / "scenarios"
            if not scenarios_dir.exists():
                continue
            for sc_dir in sorted(scenarios_dir.iterdir()):
                if not sc_dir.is_dir():
                    continue
                m_sc = re_scenario_dir.match(sc_dir.name)
                if not m_sc:
                    continue
                bldg_seed = int(m_sc.group(1)) if m_sc.group(1) else None
                traj_seed = int(m_sc.group(2))
                sc_seed = int(m_sc.group(3))

                # Extract spoofer info from INI
                ghost_host = spoofer_host = None
                ini_path = sc_dir / "omnetpp.ini"
                if ini_path.exists():
                    try:
                        params_m = re.search(
                            r"# Parameters: ({.*})", ini_path.read_text())
                        if params_m:
                            params = json.loads(params_m.group(1))
                            ghost_host = params.get("ghost_host")
                            spoofer_host = params.get("spoofer_host")
                    except Exception:
                        pass

                entry = {
                    "corridor": corridor_key,
                    "scenario_dir": sc_dir.name,
                    "building_seed": bldg_seed,
                    "trajectory_seed": traj_seed,
                    "scenario_seed": sc_seed,
                    "ghost_host": ghost_host,
                    "spoofer_host": spoofer_host,
                }

                for pq in sorted(sc_dir.glob("*.parquet")):
                    name = pq.name
                    if name.endswith("-o.parquet"):
                        config = "ScenarioOpenSpace"
                    elif name.endswith("-b.parquet"):
                        config = "ScenarioWithBuildings"
                    else:
                        config = "unknown"
                    manifest["scenarios"][name] = {**entry, "config": config}

                # Also check for CSV files (old format)
                for csv in sorted(sc_dir.glob("*.csv")):
                    name = csv.name
                    if name.endswith("-o.csv"):
                        config = "ScenarioOpenSpace"
                    elif name.endswith("-b.csv"):
                        config = "ScenarioWithBuildings"
                    else:
                        continue
                    # Use csv name as key (old datasets)
                    manifest["scenarios"][name] = {**entry, "config": config}

    return manifest


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Generate a dataset manifest (recipe for scenario generation)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Migration mode
    parser.add_argument("--from-existing", type=Path, default=None, metavar="DIR",
                        help="Build manifest from existing urbanenv directory (v1 → v2)")

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

    g = parser.add_argument_group("Output")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("-o", "--output", required=True, type=Path,
                   help="Output manifest.json path")

    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.from_existing:
        manifest = build_manifest_from_existing(args.from_existing)
    else:
        manifest = build_manifest(args)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(manifest, f, indent=2)

    n_corridors = len(manifest["corridors"])
    n_scenarios = len(manifest["scenarios"])
    print(f"Manifest: {args.output}")
    print(f"  Corridors: {n_corridors}")
    print(f"  Scenarios: {n_scenarios}")


if __name__ == "__main__":
    main()
