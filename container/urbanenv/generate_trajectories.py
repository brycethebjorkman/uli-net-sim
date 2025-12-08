#!/usr/bin/env python3
"""
Generate corridor-constrained trajectories for urban UAV simulations.

Trajectories are constrained to flyable corridors, navigating through the
corridor network via intersections. Drones move along corridors and can
change direction at intersection points.

Input: Corridor definitions from generate_corridors.py (NDJSON format)
Output: TurtleMobility XML for OMNeT++/INET simulations

Example usage:
    python generate_trajectories.py \\
        -c corridors.ndjson \\
        --hosts 5 \\
        --min-duration 500 \\
        --speed 5-15 \\
        --altitude 30-100 \\
        --seed 42 \\
        -o waypoints.xml
"""

import argparse
import json
import math
import random
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set


@dataclass
class Corridor:
    """A flyable corridor."""
    id: int
    direction: str  # "EW" or "NS"
    center: float
    width: float
    altitude_min: float
    altitude_max: float


@dataclass
class Intersection:
    """An intersection point between two corridors."""
    x: float
    y: float
    ew_corridor_id: int
    ns_corridor_id: int


def parse_range(value: str) -> Tuple[float, float]:
    """Parse a range string like '20-30' into (min, max) tuple."""
    if '-' in value:
        parts = value.split('-')
        if len(parts) != 2:
            raise ValueError(f"Invalid range format: {value}")
        return float(parts[0]), float(parts[1])
    else:
        v = float(value)
        return v, v


def sample_value(rng: random.Random, min_val: float, max_val: float) -> float:
    """Sample a value from range, or return constant if min == max."""
    if min_val == max_val:
        return min_val
    return rng.uniform(min_val, max_val)


def load_corridors(filepath: str) -> List[Corridor]:
    """Load corridors from NDJSON file."""
    corridors = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                data = json.loads(line)
                corridors.append(Corridor(**data))
    return corridors


def find_intersections(corridors: List[Corridor]) -> List[Intersection]:
    """Find all intersection points between EW and NS corridors."""
    ew_corridors = [c for c in corridors if c.direction == "EW"]
    ns_corridors = [c for c in corridors if c.direction == "NS"]

    intersections = []
    for ew in ew_corridors:
        for ns in ns_corridors:
            # EW corridor is at Y = ew.center, NS corridor is at X = ns.center
            intersections.append(Intersection(
                x=ns.center,
                y=ew.center,
                ew_corridor_id=ew.id,
                ns_corridor_id=ns.id
            ))
    return intersections


def get_corridor_endpoints(corridor: Corridor, grid_size: float) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Get the two endpoints of a corridor."""
    if corridor.direction == "EW":
        # Runs along X axis at Y = center
        return ((0, corridor.center), (grid_size, corridor.center))
    else:  # NS
        # Runs along Y axis at X = center
        return ((corridor.center, 0), (corridor.center, grid_size))


def get_points_on_corridor(corridor: Corridor, grid_size: float,
                           intersections: List[Intersection]) -> List[Tuple[float, float]]:
    """Get all navigable points on a corridor (endpoints + intersections)."""
    points = []

    # Add endpoints
    ep1, ep2 = get_corridor_endpoints(corridor, grid_size)
    points.append(ep1)
    points.append(ep2)

    # Add intersections on this corridor
    for inter in intersections:
        if corridor.direction == "EW" and inter.ew_corridor_id == corridor.id:
            points.append((inter.x, inter.y))
        elif corridor.direction == "NS" and inter.ns_corridor_id == corridor.id:
            points.append((inter.x, inter.y))

    # Sort by position along corridor
    if corridor.direction == "EW":
        points.sort(key=lambda p: p[0])  # Sort by X
    else:
        points.sort(key=lambda p: p[1])  # Sort by Y

    return points


def find_corridor_at_point(x: float, y: float, corridors: List[Corridor],
                           tolerance: float = 0.1) -> List[Corridor]:
    """Find corridors that pass through or near a point."""
    result = []
    for c in corridors:
        if c.direction == "EW":
            if abs(y - c.center) < c.width / 2 + tolerance:
                result.append(c)
        else:  # NS
            if abs(x - c.center) < c.width / 2 + tolerance:
                result.append(c)
    return result


def generate_corridor_trajectory(
    rng: random.Random,
    corridors: List[Corridor],
    intersections: List[Intersection],
    grid_size: float,
    min_duration: float,
    speed: float,
    altitude_range: Tuple[float, float],
    waypoint_interval_range: Tuple[float, float]
) -> Tuple[List[Tuple[float, float, float]], float]:
    """
    Generate a trajectory that stays within the corridor network.

    Returns:
        Tuple of (waypoints list, actual speed used)
    """
    if not corridors:
        raise ValueError("No corridors provided")

    if not intersections:
        # No intersections - just use a single corridor
        corridor = rng.choice(corridors)
        return generate_single_corridor_trajectory(
            rng, corridor, grid_size, min_duration, speed,
            altitude_range, waypoint_interval_range
        )

    # Calculate minimum distance needed
    min_distance = min_duration * speed

    waypoints = []
    total_distance = 0.0

    # Start at a random intersection
    current_intersection = rng.choice(intersections)
    current_x, current_y = current_intersection.x, current_intersection.y
    current_z = sample_value(rng, altitude_range[0], altitude_range[1])

    waypoints.append((current_x, current_y, current_z))

    # Track which corridor we're on and recent history to avoid immediate backtracking
    available_corridors = [current_intersection.ew_corridor_id, current_intersection.ns_corridor_id]
    current_corridor_id = rng.choice(available_corridors)
    current_corridor = next(c for c in corridors if c.id == current_corridor_id)

    last_intersection = current_intersection
    visited_recently: List[Tuple[float, float]] = [(current_x, current_y)]

    while total_distance < min_distance:
        # Get points along current corridor
        corridor_points = get_points_on_corridor(current_corridor, grid_size, intersections)

        # Find current position in corridor points
        current_pos = (current_x, current_y)

        # Find valid next targets (intersections or endpoints we haven't just visited)
        valid_targets = []
        for px, py in corridor_points:
            if (px, py) != current_pos:
                # Avoid immediate backtracking
                if len(visited_recently) < 2 or (px, py) != visited_recently[-2]:
                    valid_targets.append((px, py))

        if not valid_targets:
            # Stuck - allow backtracking
            valid_targets = [(px, py) for px, py in corridor_points if (px, py) != current_pos]

        if not valid_targets:
            break  # Shouldn't happen, but safety check

        # Choose next target
        next_target = rng.choice(valid_targets)
        next_x, next_y = next_target

        # Generate waypoints along this segment
        segment_distance = math.sqrt((next_x - current_x)**2 + (next_y - current_y)**2)

        if segment_distance > 0:
            # Add intermediate waypoints based on interval
            interval = sample_value(rng, waypoint_interval_range[0], waypoint_interval_range[1])
            num_intermediate = max(0, int(segment_distance / interval) - 1)

            for i in range(1, num_intermediate + 1):
                t = i / (num_intermediate + 1)
                wx = current_x + t * (next_x - current_x)
                wy = current_y + t * (next_y - current_y)
                wz = sample_value(rng, altitude_range[0], altitude_range[1])
                waypoints.append((wx, wy, wz))

            # Add the target point
            next_z = sample_value(rng, altitude_range[0], altitude_range[1])
            waypoints.append((next_x, next_y, next_z))

            total_distance += segment_distance

        # Update current position
        current_x, current_y = next_x, next_y
        visited_recently.append((current_x, current_y))
        if len(visited_recently) > 3:
            visited_recently.pop(0)

        # Check if we're at an intersection - if so, maybe switch corridors
        at_intersection = None
        for inter in intersections:
            if abs(inter.x - current_x) < 0.1 and abs(inter.y - current_y) < 0.1:
                at_intersection = inter
                break

        if at_intersection:
            # Choose whether to continue or turn
            available = [at_intersection.ew_corridor_id, at_intersection.ns_corridor_id]
            # Bias toward turning (switching corridors) for more interesting paths
            if rng.random() < 0.6:  # 60% chance to turn
                other_corridors = [cid for cid in available if cid != current_corridor.id]
                if other_corridors:
                    current_corridor_id = rng.choice(other_corridors)
                    current_corridor = next(c for c in corridors if c.id == current_corridor_id)
            last_intersection = at_intersection

    return waypoints, speed


def generate_single_corridor_trajectory(
    rng: random.Random,
    corridor: Corridor,
    grid_size: float,
    min_duration: float,
    speed: float,
    altitude_range: Tuple[float, float],
    waypoint_interval_range: Tuple[float, float]
) -> Tuple[List[Tuple[float, float, float]], float]:
    """Generate a back-and-forth trajectory along a single corridor."""
    min_distance = min_duration * speed

    ep1, ep2 = get_corridor_endpoints(corridor, grid_size)
    corridor_length = math.sqrt((ep2[0] - ep1[0])**2 + (ep2[1] - ep1[1])**2)

    waypoints = []
    total_distance = 0.0

    # Start at random position along corridor
    t = rng.random()
    current_x = ep1[0] + t * (ep2[0] - ep1[0])
    current_y = ep1[1] + t * (ep2[1] - ep1[1])
    current_z = sample_value(rng, altitude_range[0], altitude_range[1])

    waypoints.append((current_x, current_y, current_z))

    # Alternate between endpoints
    going_to_ep2 = rng.choice([True, False])

    while total_distance < min_distance:
        target = ep2 if going_to_ep2 else ep1
        target_x, target_y = target

        segment_distance = math.sqrt((target_x - current_x)**2 + (target_y - current_y)**2)

        if segment_distance > 0:
            interval = sample_value(rng, waypoint_interval_range[0], waypoint_interval_range[1])
            num_intermediate = max(0, int(segment_distance / interval) - 1)

            for i in range(1, num_intermediate + 1):
                t = i / (num_intermediate + 1)
                wx = current_x + t * (target_x - current_x)
                wy = current_y + t * (target_y - current_y)
                wz = sample_value(rng, altitude_range[0], altitude_range[1])
                waypoints.append((wx, wy, wz))

            target_z = sample_value(rng, altitude_range[0], altitude_range[1])
            waypoints.append((target_x, target_y, target_z))

            total_distance += segment_distance

        current_x, current_y = target_x, target_y
        going_to_ep2 = not going_to_ep2

    return waypoints, speed


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


def write_turtle_xml(outpath: Path, all_trajectories: Dict[int, List[Tuple[float, float, float]]],
                     speeds: Dict[int, float]):
    """Write all trajectories to a TurtleMobility XML file."""
    root = ET.Element("movements")

    for movement_id in sorted(all_trajectories.keys()):
        points = all_trajectories[movement_id]
        speed = speeds[movement_id]
        root.append(make_movement_element(movement_id, points, speed))

    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass

    outpath.parent.mkdir(parents=True, exist_ok=True)
    tree.write(outpath, encoding="utf-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser(
        description="Generate corridor-constrained trajectories for urban UAV simulations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 5 hosts with trajectories lasting at least 500s
  %(prog)s -c corridors.ndjson --hosts 5 --min-duration 500 --seed 42 -o waypoints.xml

  # Custom speed and altitude ranges
  %(prog)s -c corridors.ndjson --hosts 5 --min-duration 300 \\
      --speed 8-12 --altitude 40-80 --seed 42 -o waypoints.xml

  # Control waypoint density with interval
  %(prog)s -c corridors.ndjson --hosts 5 --min-duration 500 \\
      --waypoint-interval 20-40 --seed 42 -o waypoints.xml
"""
    )

    parser.add_argument("-c", "--corridors", type=str, required=True,
                        help="Input corridors file (NDJSON format)")
    parser.add_argument("--hosts", type=int, required=True,
                        help="Number of host trajectories to generate")
    parser.add_argument("--grid-size", type=float, default=400.0,
                        help="Size of square grid in meters (default: 400)")
    parser.add_argument("--min-duration", type=float, default=500.0,
                        help="Minimum trajectory duration in seconds (default: 500)")
    parser.add_argument("--speed", type=str, default="5-15",
                        help="Speed range in m/s as 'min-max' (default: 5-15)")
    parser.add_argument("--altitude", type=str, default="30-100",
                        help="Altitude range in meters as 'min-max' (default: 30-100)")
    parser.add_argument("--waypoint-interval", type=str, default="30-60",
                        help="Distance between waypoints in meters as 'min-max' (default: 30-60)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("-o", "--output", type=str, required=True,
                        help="Output XML file path")

    args = parser.parse_args()

    # Set up RNG
    rng = random.Random(args.seed)
    if args.seed is not None:
        print(f"Using random seed: {args.seed}", file=sys.stderr)

    # Load corridors
    corridors = load_corridors(args.corridors)
    print(f"Loaded {len(corridors)} corridors", file=sys.stderr)

    # Find intersections
    intersections = find_intersections(corridors)
    print(f"Found {len(intersections)} intersections", file=sys.stderr)

    # Parse ranges
    speed_range = parse_range(args.speed)
    altitude_range = parse_range(args.altitude)
    waypoint_interval_range = parse_range(args.waypoint_interval)

    # Generate trajectories
    all_trajectories = {}
    speeds = {}

    for host_id in range(args.hosts):
        speed = sample_value(rng, speed_range[0], speed_range[1])

        waypoints, actual_speed = generate_corridor_trajectory(
            rng=rng,
            corridors=corridors,
            intersections=intersections,
            grid_size=args.grid_size,
            min_duration=args.min_duration,
            speed=speed,
            altitude_range=altitude_range,
            waypoint_interval_range=waypoint_interval_range
        )

        all_trajectories[host_id] = waypoints
        speeds[host_id] = actual_speed

        # Estimate actual duration
        total_dist = sum(
            math.sqrt((waypoints[i+1][0] - waypoints[i][0])**2 +
                     (waypoints[i+1][1] - waypoints[i][1])**2)
            for i in range(len(waypoints) - 1)
        )
        estimated_duration = total_dist / actual_speed if actual_speed > 0 else 0

        print(f"Host {host_id}: {len(waypoints)} waypoints, speed={actual_speed:.2f} m/s, "
              f"~{estimated_duration:.0f}s duration", file=sys.stderr)

    # Write output
    outpath = Path(args.output)
    write_turtle_xml(outpath, all_trajectories, speeds)
    print(f"Wrote {len(all_trajectories)} trajectories to {outpath}", file=sys.stderr)


if __name__ == "__main__":
    main()
