#!/usr/bin/env python3
"""
Generate flyable corridors for urban UAV simulations.

Corridors are defined as rectangular prisms (axis-aligned) that run either
East-West (along X axis) or North-South (along Y axis). All corridors extend
from 0m to the grid size in their primary direction.

Output format: Newline-delimited JSON (NDJSON), one corridor per line.

Each corridor JSON object contains:
  - id: unique identifier
  - direction: "EW" (East-West) or "NS" (North-South)
  - center: perpendicular position of corridor centerline
  - width: width of the corridor (perpendicular to direction)
  - altitude_min: minimum flyable altitude
  - altitude_max: maximum flyable altitude

Example output:
  {"id": 0, "direction": "EW", "center": 50.0, "width": 20.0, "altitude_min": 30.0, "altitude_max": 150.0}
  {"id": 1, "direction": "NS", "center": 150.0, "width": 25.0, "altitude_min": 30.0, "altitude_max": 150.0}
"""

import argparse
import json
import random
import sys
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple


@dataclass
class Corridor:
    """A flyable corridor in urban airspace."""
    id: int
    direction: str  # "EW" or "NS"
    center: float   # perpendicular position of centerline
    width: float    # corridor width
    altitude_min: float
    altitude_max: float


def parse_range(value: str) -> Tuple[float, float]:
    """Parse a range string like '20-30' into (min, max) tuple."""
    if '-' in value:
        parts = value.split('-')
        if len(parts) != 2:
            raise ValueError(f"Invalid range format: {value}")
        return float(parts[0]), float(parts[1])
    else:
        # Single value means constant (min == max)
        v = float(value)
        return v, v


def sample_value(rng: random.Random, min_val: float, max_val: float) -> float:
    """Sample a value from range, or return constant if min == max."""
    if min_val == max_val:
        return min_val
    return rng.uniform(min_val, max_val)


def generate_corridors(
    grid_size: float,
    num_ew: int,
    num_ns: int,
    width_range: Tuple[float, float],
    spacing_range: Tuple[float, float],
    altitude_min: float,
    altitude_max: float,
    seed: Optional[int] = None
) -> List[Corridor]:
    """
    Generate a set of corridors.

    Corridors are placed with the first one at a sampled spacing from 0,
    then subsequent corridors are placed at sampled spacing intervals.

    Args:
        grid_size: Size of the square grid (corridors span 0 to grid_size)
        num_ew: Number of East-West corridors
        num_ns: Number of North-South corridors
        width_range: (min, max) for corridor width
        spacing_range: (min, max) for spacing between corridor centers
        altitude_min: Minimum flyable altitude
        altitude_max: Maximum flyable altitude
        seed: Random seed for reproducibility

    Returns:
        List of Corridor objects
    """
    rng = random.Random(seed)
    corridors = []
    corridor_id = 0

    # Generate East-West corridors (vary in Y position)
    if num_ew > 0:
        # Start with initial offset from Y=0
        current_y = sample_value(rng, spacing_range[0], spacing_range[1])

        for i in range(num_ew):
            width = sample_value(rng, width_range[0], width_range[1])

            # Check if corridor fits within grid
            if current_y + width / 2 > grid_size:
                print(f"Warning: EW corridor {i} at Y={current_y:.1f} exceeds grid, stopping",
                      file=sys.stderr)
                break

            corridors.append(Corridor(
                id=corridor_id,
                direction="EW",
                center=current_y,
                width=width,
                altitude_min=altitude_min,
                altitude_max=altitude_max
            ))
            corridor_id += 1

            # Move to next corridor position
            if i < num_ew - 1:
                spacing = sample_value(rng, spacing_range[0], spacing_range[1])
                current_y += spacing

    # Generate North-South corridors (vary in X position)
    if num_ns > 0:
        # Start with initial offset from X=0
        current_x = sample_value(rng, spacing_range[0], spacing_range[1])

        for i in range(num_ns):
            width = sample_value(rng, width_range[0], width_range[1])

            # Check if corridor fits within grid
            if current_x + width / 2 > grid_size:
                print(f"Warning: NS corridor {i} at X={current_x:.1f} exceeds grid, stopping",
                      file=sys.stderr)
                break

            corridors.append(Corridor(
                id=corridor_id,
                direction="NS",
                center=current_x,
                width=width,
                altitude_min=altitude_min,
                altitude_max=altitude_max
            ))
            corridor_id += 1

            # Move to next corridor position
            if i < num_ns - 1:
                spacing = sample_value(rng, spacing_range[0], spacing_range[1])
                current_x += spacing

    return corridors


def main():
    parser = argparse.ArgumentParser(
        description="Generate flyable corridors for urban UAV simulations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate 3 EW and 2 NS corridors with constant width and spacing
  %(prog)s --num-ew 3 --num-ns 2 --width 20 --spacing 100 --seed 42

  # Generate corridors with randomized width and spacing
  %(prog)s --num-ew 3 --num-ns 2 --width 15-25 --spacing 80-120 --seed 42

  # Output to file
  %(prog)s --num-ew 3 --num-ns 2 --width 20 --spacing 100 -o corridors.ndjson
"""
    )

    parser.add_argument("--grid-size", type=float, default=400.0,
                        help="Size of square grid in meters (default: 400)")
    parser.add_argument("--num-ew", type=int, default=2,
                        help="Number of East-West corridors (default: 2)")
    parser.add_argument("--num-ns", type=int, default=2,
                        help="Number of North-South corridors (default: 2)")
    parser.add_argument("--width", type=str, default="20",
                        help="Corridor width in meters, constant or range 'min-max' (default: 20)")
    parser.add_argument("--spacing", type=str, default="100",
                        help="Spacing between corridor centers in meters, constant or range (default: 100)")
    parser.add_argument("--altitude-min", type=float, default=0.0,
                        help="Minimum flyable altitude in meters (default: 0)")
    parser.add_argument("--altitude-max", type=float, default=400.0,
                        help="Maximum flyable altitude in meters (default: 400)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("-o", "--output", type=str, default=None,
                        help="Output file path (default: stdout)")

    args = parser.parse_args()

    # Parse ranges
    width_range = parse_range(args.width)
    spacing_range = parse_range(args.spacing)

    # Generate corridors
    corridors = generate_corridors(
        grid_size=args.grid_size,
        num_ew=args.num_ew,
        num_ns=args.num_ns,
        width_range=width_range,
        spacing_range=spacing_range,
        altitude_min=args.altitude_min,
        altitude_max=args.altitude_max,
        seed=args.seed
    )

    # Build generation parameters for embedding
    gen_params = {
        "_generator": "generate_corridors.py",
        "_params": {
            "grid_size": args.grid_size,
            "num_ew": args.num_ew,
            "num_ns": args.num_ns,
            "width": args.width,
            "spacing": args.spacing,
            "altitude_min": args.altitude_min,
            "altitude_max": args.altitude_max,
            "seed": args.seed,
        }
    }

    # Output as NDJSON
    output = sys.stdout if args.output is None else open(args.output, 'w')
    try:
        # Write generation parameters as first line (prefixed with #)
        output.write(f"# {json.dumps(gen_params)}\n")
        for corridor in corridors:
            json.dump(asdict(corridor), output)
            output.write('\n')
    finally:
        if args.output is not None:
            output.close()

    # Print summary to stderr
    print(f"Generated {len(corridors)} corridors ({args.num_ew} EW, {args.num_ns} NS)",
          file=sys.stderr)
    if args.seed is not None:
        print(f"Seed: {args.seed}", file=sys.stderr)


if __name__ == "__main__":
    main()
