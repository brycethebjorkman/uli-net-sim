#!/usr/bin/env python3
"""
random_waypoints.py

Generate random waypoint-based trajectories on a grid for INET TurtleMobility.
Useful for creating randomized simulation scenarios for Remote ID spoofing detection.

Example usage:
    python random_waypoints.py \\
        --out waypoints.xml \\
        --hosts 5 \\
        --grid-size 1000 \\
        --waypoints 10 \\
        --speed 5-15 \\
        --altitude 30-100 \\
        --seed 42
"""

import argparse
import random
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Tuple


def generate_random_waypoints(
    host_id: int,
    grid_size: float,
    num_waypoints: int,
    speed_range: Tuple[float, float],
    altitude_range: Tuple[float, float],
    start_pos: Tuple[float, float, float] = None,
) -> List[Tuple[float, float, float]]:
    """
    Generate random waypoints on a grid.

    Args:
        host_id: Unique identifier for this host
        grid_size: Size of the square grid (meters)
        num_waypoints: Number of waypoints to generate
        speed_range: (min_speed, max_speed) in m/s
        altitude_range: (min_alt, max_alt) in meters
        start_pos: Starting position (x, y, z), or None for random

    Returns:
        List of (x, y, z) waypoint coordinates
    """
    waypoints = []

    # Generate starting position
    if start_pos is None:
        x0 = random.uniform(0, grid_size)
        y0 = random.uniform(0, grid_size)
        z0 = random.uniform(altitude_range[0], altitude_range[1])
        start_pos = (x0, y0, z0)

    waypoints.append(start_pos)

    # Generate subsequent waypoints
    for _ in range(num_waypoints - 1):
        x = random.uniform(0, grid_size)
        y = random.uniform(0, grid_size)
        z = random.uniform(altitude_range[0], altitude_range[1])
        waypoints.append((x, y, z))

    return waypoints


def make_movement_element(movement_id: int, points: List[Tuple[float, float, float]], speed: float):
    """Create a TurtleMobility movement element."""
    movement = ET.Element("movement")
    movement.set("id", str(movement_id))

    # Set initial position and speed
    x0, y0, z0 = points[0]
    set_el = ET.Element("set")
    set_el.set("x", f"{x0:.6f}")
    set_el.set("y", f"{y0:.6f}")
    set_el.set("z", f"{z0:.6f}")
    set_el.set("speed", f"{speed:.6f}")
    movement.append(set_el)

    # Add moveto elements for subsequent waypoints
    for x, y, z in points[1:]:
        mv = ET.Element("moveto")
        mv.set("x", f"{x:.6f}")
        mv.set("y", f"{y:.6f}")
        mv.set("z", f"{z:.6f}")
        movement.append(mv)

    return movement


def write_turtle_xml(outpath: Path, all_trajectories: dict, speeds: dict):
    """Write all trajectories to a TurtleMobility XML file."""
    root = ET.Element("movements")

    for movement_id, points in all_trajectories.items():
        speed = speeds[movement_id]
        root.append(make_movement_element(movement_id, points, speed))

    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass

    outpath.parent.mkdir(parents=True, exist_ok=True)
    tree.write(outpath, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {len(all_trajectories)} trajectories to {outpath}")


def parse_range(range_str: str) -> Tuple[float, float]:
    """Parse a range string like '5-15' into (min, max) tuple."""
    parts = range_str.split('-')
    if len(parts) != 2:
        raise ValueError(f"Invalid range format: {range_str}. Expected 'min-max'")
    return float(parts[0]), float(parts[1])


def main():
    p = argparse.ArgumentParser(
        description="Generate random waypoint-based trajectories on a grid",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Generate 5 hosts with random waypoints:
    %(prog)s --out waypoints.xml --hosts 5 --waypoints 10 --seed 42

  Custom grid and speed ranges:
    %(prog)s --out waypoints.xml --hosts 10 \\
        --grid-size 2000 --waypoints 15 \\
        --speed 10-20 --altitude 40-150 --seed 123

  Generate with one spoofer (last host uses different movement):
    %(prog)s --out waypoints.xml --hosts 6 --waypoints 10 \\
        --spoofer-hosts 1 --spoofer-waypoints 5 --seed 42
"""
    )

    # Required arguments
    p.add_argument("--out", required=True, help="Output XML path")
    p.add_argument("--hosts", type=int, required=True, help="Number of hosts to generate")

    # Grid and waypoint parameters
    p.add_argument("--grid-size", type=float, default=1000.0,
                   help="Size of square grid in meters (default: 1000)")
    p.add_argument("--waypoints", type=int, default=10,
                   help="Number of waypoints per host (default: 10)")

    # Randomization ranges
    p.add_argument("--speed", type=str, default="5-15",
                   help="Speed range in m/s as 'min-max' (default: 5-15)")
    p.add_argument("--altitude", type=str, default="30-100",
                   help="Altitude range in meters as 'min-max' (default: 30-100)")

    # Spoofer configuration
    p.add_argument("--spoofer-hosts", type=int, default=0,
                   help="Number of spoofer hosts (last N hosts) (default: 0)")
    p.add_argument("--spoofer-waypoints", type=int, default=None,
                   help="Number of waypoints for spoofers (default: same as --waypoints)")
    p.add_argument("--spoofer-speed", type=str, default=None,
                   help="Speed range for spoofers (default: same as --speed)")

    # Reproducibility
    p.add_argument("--seed", type=int, default=None,
                   help="Random seed for reproducibility")

    args = p.parse_args()

    # Set random seed if provided
    if args.seed is not None:
        random.seed(args.seed)
        print(f"Using random seed: {args.seed}")

    # Parse ranges
    speed_range = parse_range(args.speed)
    altitude_range = parse_range(args.altitude)

    spoofer_speed_range = speed_range
    if args.spoofer_speed:
        spoofer_speed_range = parse_range(args.spoofer_speed)

    spoofer_waypoints = args.waypoints
    if args.spoofer_waypoints is not None:
        spoofer_waypoints = args.spoofer_waypoints

    # Validate parameters
    if args.spoofer_hosts > args.hosts:
        p.error(f"--spoofer-hosts ({args.spoofer_hosts}) cannot exceed --hosts ({args.hosts})")

    # Generate trajectories
    all_trajectories = {}
    speeds = {}

    num_normal = args.hosts - args.spoofer_hosts

    # Generate normal host trajectories
    for host_id in range(num_normal):
        waypoints = generate_random_waypoints(
            host_id=host_id,
            grid_size=args.grid_size,
            num_waypoints=args.waypoints,
            speed_range=speed_range,
            altitude_range=altitude_range,
        )
        speed = random.uniform(*speed_range)
        all_trajectories[host_id] = waypoints
        speeds[host_id] = speed
        print(f"Host {host_id}: {len(waypoints)} waypoints, speed={speed:.2f} m/s")

    # Generate spoofer trajectories
    for i in range(args.spoofer_hosts):
        host_id = num_normal + i
        waypoints = generate_random_waypoints(
            host_id=host_id,
            grid_size=args.grid_size,
            num_waypoints=spoofer_waypoints,
            speed_range=spoofer_speed_range,
            altitude_range=altitude_range,
        )
        speed = random.uniform(*spoofer_speed_range)
        all_trajectories[host_id] = waypoints
        speeds[host_id] = speed
        print(f"Host {host_id} (spoofer): {len(waypoints)} waypoints, speed={speed:.2f} m/s")

    # Write output
    outpath = Path(args.out)
    write_turtle_xml(outpath, all_trajectories, speeds)


if __name__ == "__main__":
    main()
