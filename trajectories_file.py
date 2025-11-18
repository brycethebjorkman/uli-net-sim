#!/usr/bin/env python3
"""
trajectories_file.py

Generates a turtle_mobility XML with two movements:
 - `host[0]` follows y = ln(x)
 - `host[1]` follows y = e^x

This script is CLI-driven and writes an XML suitable for INET's TurtleMobility.
Defaults place the curves near the coordinates used in the repo; adjust via flags.
"""

import argparse
import math
import xml.etree.ElementTree as ET
from pathlib import Path


def make_movement_element(name, points):
    movement = ET.Element("movement")
    movement.set("name", name)
    # initial position
    x0, y0 = points[0]
    set_el = ET.Element("set")
    set_el.set("x", f"{x0:.6f}")
    set_el.set("y", f"{y0:.6f}")
    movement.append(set_el)
    # subsequent moveto entries
    for x, y in points[1:]:
        mv = ET.Element("moveto")
        mv.set("x", f"{x:.6f}")
        mv.set("y", f"{y:.6f}")
        movement.append(mv)
    return movement


def generate_exp_curve(x_min, x_max, n_points, scale_x=1.0, scale_y=1.0, x_offset=0.0, y_offset=0.0):
    pts = []
    for i in range(n_points):
        x = x_min + (x_max - x_min) * (i / (n_points - 1))
        y = math.exp(x)
        X = x_offset + scale_x * x
        Y = y_offset + scale_y * y
        pts.append((X, Y))
    return pts


def generate_log_curve(x_min, x_max, n_points, scale_x=1.0, scale_y=1.0, x_offset=0.0, y_offset=0.0):
    pts = []
    for i in range(n_points):
        x = x_min + (x_max - x_min) * (i / (n_points - 1))
        # avoid log(0)
        x_for_log = max(x, 1e-6)
        y = math.log(x_for_log)
        X = x_offset + scale_x * x
        Y = y_offset + scale_y * y
        pts.append((X, Y))
    return pts


def write_turtle_xml(outpath: Path, host_pts, spoof_pts, host_name="host[0]", spoof_name="host[1]"):
    root = ET.Element("turtle_mobility")
    root.append(make_movement_element(host_name, host_pts))
    root.append(make_movement_element(spoof_name, spoof_pts))
    tree = ET.ElementTree(root)
    try:
        ET.indent(tree, space="  ")
    except Exception:
        pass
    outpath.parent.mkdir(parents=True, exist_ok=True)
    tree.write(outpath, encoding="utf-8", xml_declaration=True)
    print(f"Wrote {outpath}")


def main():
    p = argparse.ArgumentParser(description="Generate turtle_mobility XML where host follows ln(x) and spoof follows e^x")
    p.add_argument("--out", default="turtles_mobility (0).xml", help="output xml path")
    p.add_argument("--points", type=int, default=200, help="points per curve")
    # domain for x (input to functions)
    p.add_argument("--xmin", type=float, default=0.1, help="minimum x for curves (log requires x>0)")
    p.add_argument("--xmax", type=float, default=4.0, help="maximum x for curves")
    # scaling and offsets to place curves in scene coordinates
    p.add_argument("--scale-x", type=float, default=20.0, help="scale applied to x values")
    p.add_argument("--scale-y", type=float, default=15.0, help="scale applied to y values")
    p.add_argument("--host-offset", nargs=2, type=float, default=[150.0, 75.0], help="x y offset for host (ln) path")
    p.add_argument("--spoof-offset", nargs=2, type=float, default=[150.0, 250.0], help="x y offset for spoof (exp) path")
    args = p.parse_args()

    # generate curves
    host_pts = generate_log_curve(args.xmin, args.xmax, args.points,
                                  scale_x=args.scale_x, scale_y=args.scale_y,
                                  x_offset=args.host_offset[0], y_offset=args.host_offset[1])
    spoof_pts = generate_exp_curve(args.xmin, args.xmax, args.points,
                                   scale_x=args.scale_x, scale_y=args.scale_y,
                                   x_offset=args.spoof_offset[0], y_offset=args.spoof_offset[1])

    outpath = Path(args.out)
    write_turtle_xml(outpath, host_pts, spoof_pts, host_name="host[0]", spoof_name="host[1]")


if __name__ == "__main__":
    main()
# trajectories_file.py