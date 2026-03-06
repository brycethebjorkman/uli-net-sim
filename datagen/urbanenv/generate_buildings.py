#!/usr/bin/env python3
"""
Generate buildings for urban UAV simulations.

Buildings are axis-aligned cuboids that:
- Do not intersect any flyable corridors
- Do not intersect each other
- Are oriented along EW/NS axes

Input: Corridor definitions from generate_corridors.py (NDJSON format)
Output: Newline-delimited JSON (NDJSON) with building definitions, or OMNeT++ XML

Each building JSON object contains:
  - id: unique identifier
  - x: X position of building center
  - y: Y position of building center
  - width_x: building dimension along X axis
  - width_y: building dimension along Y axis
  - height: building height

Example output (NDJSON):
  {"id": 0, "x": 50.0, "y": 50.0, "width_x": 40.0, "width_y": 45.0, "height": 100.0}
  {"id": 1, "x": 250.0, "y": 150.0, "width_x": 35.0, "width_y": 40.0, "height": 85.0}
"""

import argparse
import json
import random
import sys
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple


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
class Building:
    """A building in the urban environment."""
    id: int
    x: float       # center X position
    y: float       # center Y position
    width_x: float # dimension along X axis
    width_y: float # dimension along Y axis
    height: float


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
            if line and not line.startswith('#'):
                data = json.loads(line)
                corridors.append(Corridor(**data))
    return corridors


def get_corridor_bounds(corridor: Corridor, grid_size: float) -> Tuple[float, float, float, float]:
    """Get (x_min, x_max, y_min, y_max) bounds for a corridor."""
    half_width = corridor.width / 2
    if corridor.direction == "EW":
        # Runs along X, varies in Y
        return (0, grid_size, corridor.center - half_width, corridor.center + half_width)
    else:  # NS
        # Runs along Y, varies in X
        return (corridor.center - half_width, corridor.center + half_width, 0, grid_size)


def rectangles_overlap(r1: Tuple[float, float, float, float],
                       r2: Tuple[float, float, float, float]) -> bool:
    """Check if two rectangles overlap. Each is (x_min, x_max, y_min, y_max)."""
    x1_min, x1_max, y1_min, y1_max = r1
    x2_min, x2_max, y2_min, y2_max = r2

    # No overlap if one is entirely to the left/right/above/below the other
    if x1_max <= x2_min or x2_max <= x1_min:
        return False
    if y1_max <= y2_min or y2_max <= y1_min:
        return False
    return True


def building_bounds(b: Building) -> Tuple[float, float, float, float]:
    """Get (x_min, x_max, y_min, y_max) bounds for a building."""
    half_x = b.width_x / 2
    half_y = b.width_y / 2
    return (b.x - half_x, b.x + half_x, b.y - half_y, b.y + half_y)


def building_overlaps_corridor(building: Building, corridors: List[Corridor],
                                grid_size: float) -> bool:
    """Check if a building overlaps any corridor."""
    b_bounds = building_bounds(building)
    for corridor in corridors:
        c_bounds = get_corridor_bounds(corridor, grid_size)
        if rectangles_overlap(b_bounds, c_bounds):
            return True
    return False


def building_overlaps_buildings(building: Building, buildings: List[Building]) -> bool:
    """Check if a building overlaps any existing building."""
    b_bounds = building_bounds(building)
    for existing in buildings:
        if rectangles_overlap(b_bounds, building_bounds(existing)):
            return True
    return False


def building_in_grid(building: Building, grid_size: float) -> bool:
    """Check if building is fully within grid bounds."""
    half_x = building.width_x / 2
    half_y = building.width_y / 2
    return (building.x - half_x >= 0 and building.x + half_x <= grid_size and
            building.y - half_y >= 0 and building.y + half_y <= grid_size)


def generate_buildings(
    corridors: List[Corridor],
    grid_size: float,
    num_buildings: int,
    width_x_range: Tuple[float, float],
    width_y_range: Tuple[float, float],
    height_range: Tuple[float, float],
    seed: Optional[int] = None,
    max_attempts_per_building: int = 100
) -> List[Building]:
    """
    Generate buildings that don't overlap corridors or each other.

    Uses rejection sampling: randomly place buildings and reject those
    that violate constraints.
    """
    rng = random.Random(seed)
    buildings = []

    # Precompute corridor bounds
    corridor_bounds = [get_corridor_bounds(c, grid_size) for c in corridors]

    for i in range(num_buildings):
        placed = False

        for attempt in range(max_attempts_per_building):
            # Sample building dimensions
            width_x = sample_value(rng, width_x_range[0], width_x_range[1])
            width_y = sample_value(rng, width_y_range[0], width_y_range[1])
            height = sample_value(rng, height_range[0], height_range[1])

            # Sample position (ensure building can fit in grid)
            margin_x = width_x / 2
            margin_y = width_y / 2

            if margin_x >= grid_size / 2 or margin_y >= grid_size / 2:
                continue  # Building too large for grid

            x = rng.uniform(margin_x, grid_size - margin_x)
            y = rng.uniform(margin_y, grid_size - margin_y)

            candidate = Building(
                id=len(buildings),
                x=x,
                y=y,
                width_x=width_x,
                width_y=width_y,
                height=height
            )

            # Check constraints
            if not building_in_grid(candidate, grid_size):
                continue
            if building_overlaps_corridor(candidate, corridors, grid_size):
                continue
            if building_overlaps_buildings(candidate, buildings):
                continue

            # Valid placement found
            buildings.append(candidate)
            placed = True
            break

        if not placed:
            print(f"Warning: Could not place building {i} after {max_attempts_per_building} attempts",
                  file=sys.stderr)

    return buildings


def buildings_to_xml(buildings: List[Building], gen_params: dict) -> str:
    """Convert buildings to OMNeT++ physical environment XML format."""
    lines = ['<environment>']
    lines.append(f'  <!-- Generated by: {gen_params["_generator"]} -->')
    lines.append(f'  <!-- Parameters: {json.dumps(gen_params["_params"])} -->')
    lines.append('')
    lines.append('  <!-- Materials: concrete/brick simulation -->')
    lines.append('  <material id="1" resistivity="1000" relativePermittivity="5" relativePermeability="1"/>')
    lines.append('')
    lines.append('  <!-- Buildings -->')

    for b in buildings:
        # Shape definition
        lines.append(f'  <shape id="{b.id + 1}" type="cuboid" size="{b.width_x:.1f} {b.width_y:.1f} {b.height:.1f}"/>')

        # Object placement (position is center, z is height/2 for ground-based)
        # Gray color with slight variation
        gray = 150 + (b.id % 4) * 5
        lines.append(f'  <object position="center {b.x:.1f} {b.y:.1f} {b.height/2:.1f}" '
                    f'orientation="0 0 0" shape="{b.id + 1}" material="1"')
        lines.append(f'          fill-color="{gray} {gray} {gray}" line-color="0 0 0" opacity="1"/>')
        lines.append('')

    lines.append('</environment>')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Generate buildings for urban UAV simulations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 20 buildings using corridors from file
  %(prog)s -c corridors.ndjson -n 20 --seed 42

  # Custom building sizes
  %(prog)s -c corridors.ndjson -n 30 --width-x 30-50 --width-y 30-50 --height 50-150

  # Output as OMNeT++ XML
  %(prog)s -c corridors.ndjson -n 20 --format xml -o buildings.xml
"""
    )

    parser.add_argument("-c", "--corridors", type=str, required=True,
                        help="Input corridors file (NDJSON format)")
    parser.add_argument("-n", "--num-buildings", type=int, default=20,
                        help="Number of buildings to generate (default: 20)")
    parser.add_argument("--grid-size", type=float, default=400.0,
                        help="Size of square grid in meters (default: 400)")
    parser.add_argument("--width-x", type=str, default="30-50",
                        help="Building X dimension range in meters (default: 30-50)")
    parser.add_argument("--width-y", type=str, default="30-50",
                        help="Building Y dimension range in meters (default: 30-50)")
    parser.add_argument("--height", type=str, default="50-150",
                        help="Building height range in meters (default: 50-150)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("--format", type=str, choices=["ndjson", "xml"], default="ndjson",
                        help="Output format (default: ndjson)")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output file path (default: stdout)")
    parser.add_argument("--max-attempts", type=int, default=100,
                        help="Max placement attempts per building (default: 100)")

    args = parser.parse_args()

    # Load corridors
    corridors = load_corridors(args.corridors)
    print(f"Loaded {len(corridors)} corridors", file=sys.stderr)

    # Parse ranges
    width_x_range = parse_range(args.width_x)
    width_y_range = parse_range(args.width_y)
    height_range = parse_range(args.height)

    # Generate buildings
    buildings = generate_buildings(
        corridors=corridors,
        grid_size=args.grid_size,
        num_buildings=args.num_buildings,
        width_x_range=width_x_range,
        width_y_range=width_y_range,
        height_range=height_range,
        seed=args.seed,
        max_attempts_per_building=args.max_attempts
    )

    # Build generation parameters for embedding
    gen_params = {
        "_generator": "generate_buildings.py",
        "_params": {
            "corridors": args.corridors,
            "num_buildings": args.num_buildings,
            "grid_size": args.grid_size,
            "width_x": args.width_x,
            "width_y": args.width_y,
            "height": args.height,
            "seed": args.seed,
            "max_attempts": args.max_attempts,
        }
    }

    # Output
    output = sys.stdout if args.output is None else open(args.output, 'w')
    try:
        if args.format == "xml":
            output.write(buildings_to_xml(buildings, gen_params))
            output.write('\n')
        else:
            # Write generation parameters as first line (prefixed with #)
            output.write(f"# {json.dumps(gen_params)}\n")
            for building in buildings:
                json.dump(asdict(building), output)
                output.write('\n')
    finally:
        if args.output is not None:
            output.close()

    # Print summary
    print(f"Generated {len(buildings)} buildings", file=sys.stderr)
    if args.seed is not None:
        print(f"Seed: {args.seed}", file=sys.stderr)


if __name__ == "__main__":
    main()
