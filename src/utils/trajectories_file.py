#!/usr/bin/env python3
"""
trajectories.py

Generates INET TurtleMobility XML with four different trajectory patterns:
 - movement id="1": host[0] follows y = ln(x)
 - movement id="2": host[1] follows y = e^x
 - movement id="3": host[2] follows linear trajectory
 - movement id="4": host[3] follows parabolic trajectory y = x^2

This script can be run programmatically to generate all trajectories at once.
"""

import argparse
import math
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


def main():
    p = argparse.ArgumentParser(
        description="Generate INET TurtleMobility XML with 4 different trajectories"
    )
    p.add_argument("--out", default="trajectories.xml",
                   help="output xml path")
    p.add_argument("--points", type=int, default=200,
                   help="points per curve")
    p.add_argument("--xmin", type=float, default=0.1,
                   help="minimum x for curves (log requires x>0)")
    p.add_argument("--xmax", type=float, default=4.0,
                   help="maximum x for curves")
    p.add_argument("--scale-x", type=float, default=20.0,
                   help="scale applied to x values")
    p.add_argument("--scale-y", type=float, default=15.0,
                   help="scale applied to y values")
    p.add_argument("--z", type=float, default=50.0,
                   help="z altitude for all trajectories (meters)")
    p.add_argument("--speed", type=float, default=10.0,
                   help="movement speed (m/s)")
    args = p.parse_args()

    # Generate all 4 trajectories
    all_trajectories = {}

    # Movement 1: logarithmic curve (host[0])
    all_trajectories[1] = generate_log_curve(
        args.xmin, args.xmax, args.points,
        scale_x=args.scale_x, scale_y=args.scale_y,
        x_offset=150.0, y_offset=75.0, z=args.z
    )

    # Movement 2: exponential curve (host[1])
    all_trajectories[2] = generate_exp_curve(
        args.xmin, args.xmax, args.points,
        scale_x=args.scale_x, scale_y=args.scale_y,
        x_offset=150.0, y_offset=250.0, z=args.z
    )

    # Movement 3: linear trajectory (host[2])
    all_trajectories[3] = generate_linear_trajectory(
        args.xmin, args.xmax, args.points,
        scale_x=args.scale_x, scale_y=args.scale_y,
        x_offset=200.0, y_offset=150.0, z=args.z, slope=0.5
    )

    # Movement 4: parabolic trajectory (host[3])
    all_trajectories[4] = generate_parabolic_trajectory(
        args.xmin, args.xmax, args.points,
        scale_x=args.scale_x, scale_y=args.scale_y * 0.3,  # Scale down parabola
        x_offset=250.0, y_offset=100.0, z=args.z
    )

    outpath = Path(args.out)
    write_turtle_xml(outpath, all_trajectories, args.speed)


if __name__ == "__main__":
    main()
