#!/usr/bin/env python3
"""
trajectories.py

Generic CLI utility for generating INET TurtleMobility XML files.
Supports multiple trajectory types: logarithmic, exponential, linear, and parabolic.

Example usage:
    python trajectories.py --out trajectories.xml \\
        --add-log 1 150 75 \\
        --add-exp 2 150 250 \\
        --add-linear 3 200 150 0.5 \\
        --add-parabolic 4 250 100 0.3
"""

import argparse
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def make_movement_element(movement_id, points, speed=10.0):
    """Create a movement element with the given ID and trajectory points."""
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

    # Add moveto elements for subsequent points
    for x, y, z in points[1:]:
        mv = ET.Element("moveto")
        mv.set("x", f"{x:.6f}")
        mv.set("y", f"{y:.6f}")
        mv.set("z", f"{z:.6f}")
        movement.append(mv)

    return movement


def generate_log_curve(x_min, x_max, n_points, scale_x=1.0, scale_y=1.0,
                       x_offset=0.0, y_offset=0.0, z=50.0):
    """Generate points following y = ln(x) curve."""
    pts = []
    for i in range(n_points):
        x = x_min + (x_max - x_min) * (i / (n_points - 1))
        x_for_log = max(x, 1e-6)  # avoid log(0)
        y = math.log(x_for_log)
        X = x_offset + scale_x * x
        Y = y_offset + scale_y * y
        pts.append((X, Y, z))
    return pts


def generate_exp_curve(x_min, x_max, n_points, scale_x=1.0, scale_y=1.0,
                       x_offset=0.0, y_offset=0.0, z=50.0):
    """Generate points following y = e^x curve."""
    pts = []
    for i in range(n_points):
        x = x_min + (x_max - x_min) * (i / (n_points - 1))
        y = math.exp(x)
        X = x_offset + scale_x * x
        Y = y_offset + scale_y * y
        pts.append((X, Y, z))
    return pts


def generate_linear_trajectory(x_min, x_max, n_points, scale_x=1.0, scale_y=1.0,
                               x_offset=0.0, y_offset=0.0, z=50.0, slope=1.0):
    """Generate points following y = slope * x linear trajectory."""
    pts = []
    for i in range(n_points):
        x = x_min + (x_max - x_min) * (i / (n_points - 1))
        y = slope * x
        X = x_offset + scale_x * x
        Y = y_offset + scale_y * y
        pts.append((X, Y, z))
    return pts


def generate_parabolic_trajectory(x_min, x_max, n_points, scale_x=1.0, scale_y=1.0,
                                  x_offset=0.0, y_offset=0.0, z=50.0):
    """Generate points following y = x^2 parabolic trajectory."""
    pts = []
    for i in range(n_points):
        x = x_min + (x_max - x_min) * (i / (n_points - 1))
        y = x * x
        X = x_offset + scale_x * x
        Y = y_offset + scale_y * y
        pts.append((X, Y, z))
    return pts


def write_turtle_xml(outpath: Path, all_trajectories, speed=10.0):
    """Write all trajectories to a TurtleMobility XML file."""
    root = ET.Element("movements")

    for movement_id, points in all_trajectories.items():
        root.append(make_movement_element(movement_id, points, speed))

    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass

    outpath.parent.mkdir(parents=True, exist_ok=True)
    tree.write(outpath, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {outpath}")


class TrajectoryAction(argparse.Action):
    """Custom action to collect trajectory specifications."""
    def __call__(self, parser, namespace, values, option_string=None):
        trajectories = getattr(namespace, 'trajectories', None)
        if trajectories is None:
            trajectories = []
            setattr(namespace, 'trajectories', trajectories)

        traj_type = option_string.replace('--add-', '')
        trajectories.append({
            'type': traj_type,
            'values': values
        })


def main():
    p = argparse.ArgumentParser(
        description="Generate INET TurtleMobility XML with custom trajectories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Generate a single logarithmic trajectory:
    %(prog)s --out traj.xml --add-log 1 150 75

  Generate multiple trajectories:
    %(prog)s --out traj.xml \\
        --add-log 1 150 75 \\
        --add-exp 2 150 250 \\
        --add-linear 3 200 150 0.5 \\
        --add-parabolic 4 250 100 0.3

Trajectory types:
  --add-log ID X_OFFSET Y_OFFSET
      Logarithmic curve: y = ln(x)

  --add-exp ID X_OFFSET Y_OFFSET
      Exponential curve: y = e^x

  --add-linear ID X_OFFSET Y_OFFSET SLOPE
      Linear trajectory: y = slope * x

  --add-parabolic ID X_OFFSET Y_OFFSET SCALE_Y_FACTOR
      Parabolic curve: y = x^2 (scale_y multiplied by SCALE_Y_FACTOR)
"""
    )

    # Output and global parameters
    p.add_argument("--out", default="trajectories.xml",
                   help="output xml path")
    p.add_argument("--points", type=int, default=200,
                   help="points per curve (default: 200)")
    p.add_argument("--xmin", type=float, default=0.1,
                   help="minimum x for curves, log requires x>0 (default: 0.1)")
    p.add_argument("--xmax", type=float, default=4.0,
                   help="maximum x for curves (default: 4.0)")
    p.add_argument("--scale-x", type=float, default=20.0,
                   help="scale applied to x values (default: 20.0)")
    p.add_argument("--scale-y", type=float, default=15.0,
                   help="scale applied to y values (default: 15.0)")
    p.add_argument("--z", type=float, default=50.0,
                   help="z altitude for all trajectories in meters (default: 50.0)")
    p.add_argument("--speed", type=float, default=10.0,
                   help="movement speed in m/s (default: 10.0)")

    # Trajectory type arguments
    p.add_argument("--add-log", nargs=3, type=float, metavar=('ID', 'X_OFFSET', 'Y_OFFSET'),
                   action=TrajectoryAction, dest='trajectories',
                   help="add logarithmic trajectory")
    p.add_argument("--add-exp", nargs=3, type=float, metavar=('ID', 'X_OFFSET', 'Y_OFFSET'),
                   action=TrajectoryAction, dest='trajectories',
                   help="add exponential trajectory")
    p.add_argument("--add-linear", nargs=4, type=float, metavar=('ID', 'X_OFFSET', 'Y_OFFSET', 'SLOPE'),
                   action=TrajectoryAction, dest='trajectories',
                   help="add linear trajectory")
    p.add_argument("--add-parabolic", nargs=4, type=float, metavar=('ID', 'X_OFFSET', 'Y_OFFSET', 'SCALE_Y_FACTOR'),
                   action=TrajectoryAction, dest='trajectories',
                   help="add parabolic trajectory")

    args = p.parse_args()

    # Check if any trajectories were specified
    if not hasattr(args, 'trajectories') or not args.trajectories:
        p.error("No trajectories specified. Use --add-log, --add-exp, --add-linear, or --add-parabolic")

    # Generate all trajectories
    all_trajectories = {}

    for traj in args.trajectories:
        traj_type = traj['type']
        values = traj['values']
        traj_id = int(values[0])
        x_offset = values[1]
        y_offset = values[2]

        if traj_type == 'log':
            all_trajectories[traj_id] = generate_log_curve(
                args.xmin, args.xmax, args.points,
                scale_x=args.scale_x, scale_y=args.scale_y,
                x_offset=x_offset, y_offset=y_offset, z=args.z
            )
        elif traj_type == 'exp':
            all_trajectories[traj_id] = generate_exp_curve(
                args.xmin, args.xmax, args.points,
                scale_x=args.scale_x, scale_y=args.scale_y,
                x_offset=x_offset, y_offset=y_offset, z=args.z
            )
        elif traj_type == 'linear':
            slope = values[3]
            all_trajectories[traj_id] = generate_linear_trajectory(
                args.xmin, args.xmax, args.points,
                scale_x=args.scale_x, scale_y=args.scale_y,
                x_offset=x_offset, y_offset=y_offset, z=args.z, slope=slope
            )
        elif traj_type == 'parabolic':
            scale_y_factor = values[3]
            all_trajectories[traj_id] = generate_parabolic_trajectory(
                args.xmin, args.xmax, args.points,
                scale_x=args.scale_x, scale_y=args.scale_y * scale_y_factor,
                x_offset=x_offset, y_offset=y_offset, z=args.z
            )

    if not all_trajectories:
        print("Error: No trajectories generated", file=sys.stderr)
        sys.exit(1)

    outpath = Path(args.out)
    write_turtle_xml(outpath, all_trajectories, args.speed)


if __name__ == "__main__":
    main()
