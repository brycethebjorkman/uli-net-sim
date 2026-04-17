#!/usr/bin/env python3
"""
generate_batch.py

Materialize seeded random scenarios for batch comparison under
simulations/spoofing_aware_with_planning-style geometry.

Each output directory contains omnetpp.ini with four configs:
  - <tag>_Base   — shared mobility / radio (not a leaf; extended only)
  - <tag>_Aware  — extends Base (SpoofingAwareGcs)
  - <tag>_AwareInstantDetect — extends Base (SpoofingAwareGcs; force detect via runner env)
  - <tag>_TrustRid — extends Base (TrustRidGcs)

Leaf configs are *_Aware, *_AwareInstantDetect, and *_TrustRid.

Example:
    python3 datagen/spoofting_aware_trajectory_planning_datagen/generate_batch.py \\
        --layout circle8 --seeds 0 1 2 \\
        --output-dir simulations/spoofing_aware_with_planning/batches/0001/generated
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Circle8Params:
    """Layout: N benign agents on a circle through hub (Cx, Cy), one spoofer."""

    cx: float = 250.0
    cy: float = 250.0
    cz: float = 70.0
    radius_m: float = 200.0
    radius_jitter_m: float = 0.0
    z_jitter_m: float = 0.0
    benign_speed: float = 8.0
    spoofer_speed: float = 6.0
    sim_time_s: float = 120.0
    num_benign: int = 8


def _movement_xml(start: tuple[float, float, float], goal: tuple[float, float, float],
                  speed: float, mid: int) -> str:
    x0, y0, z0 = start
    x1, y1, z1 = goal
    return (
        f"<movement id='{mid}'><set x='{x0:.6g}' y='{y0:.6g}' z='{z0:.6g}' "
        f"speed='{speed}'/><moveto x='{x1:.6g}' y='{y1:.6g}' z='{z1:.6g}'/></movement>"
    )


def _spoofer_waypoints_xml(
    rng: random.Random,
    speed: float,
    n_waypoints: int = 4,
) -> tuple[str, tuple[float, float, float]]:
    pts: list[tuple[float, float, float]] = []
    for _ in range(n_waypoints):
        x = rng.uniform(80.0, 420.0)
        y = rng.uniform(80.0, 420.0)
        z = rng.uniform(60.0, 85.0)
        pts.append((x, y, z))
    x0, y0, z0 = pts[0]
    parts = [
        f"<set x='{x0:.6g}' y='{y0:.6g}' z='{z0:.6g}' speed='{speed}'/>",
    ]
    for p in pts[1:]:
        parts.append(f"<moveto x='{p[0]:.6g}' y='{p[1]:.6g}' z='{p[2]:.6g}'/>")
    xml = "<movement id='spoofer'>" + "".join(parts) + "</movement>"
    return xml, (x0, y0, z0)


def generate_circle8_ini(
    rng: random.Random,
    p: Circle8Params,
    tag: str,
) -> str:
    """Return full omnetpp.ini text for circle8 + spoofer."""
    n = p.num_benign
    spoofer_host = n
    theta0 = rng.uniform(0.0, 2.0 * math.pi)

    lines: list[str] = [
        "[General]",
        "network = uav_rid.rid_network.BasicUav",
        'scheduler-class = "omnetpp::cRealTimeScheduler"',
        "",
        '*.radioMedium.obstacleLoss.typename = "DielectricObstacleLoss"',
        "",
        f"# Generated batch {tag} — circle {n}x1 + spoofer, seed-driven geometry",
        "",
        f"[Config {tag}_Base]",
        f"description = \"circle8 batch base (extended by Aware / TrustRid)\"",
        (
            f"sim-time-limit = {int(p.sim_time_s)}s"
            if float(p.sim_time_s).is_integer()
            else f"sim-time-limit = {p.sim_time_s}s"
        ),
        f"*.numHosts = {n + 1}",
        "*.numGcs = 1",
        "",
        "*.host[*].typename = DroneHost",
        "*.host[*].mobility.typename = MultirotorMobility",
        "*.host[*].mobility.initFromDisplayString = false",
        "*.host[*].mobility.updateInterval = 50ms",
        "*.host[*].mobility.dynamicsDt = 0.001s",
        "*.host[*].mobility.controlDt = 0.01s",
        "",
        "*.host[*].mobility.mass = 5kg",
        "*.host[*].mobility.armLength = 0.5m",
        "*.host[*].mobility.Ixx = 0.5",
        "*.host[*].mobility.Iyy = 0.5",
        "*.host[*].mobility.Izz = 0.8",
        "",
        "*.host[*].mobility.constraintAreaMinX = -100m",
        "*.host[*].mobility.constraintAreaMaxX = 600m",
        "*.host[*].mobility.constraintAreaMinY = -100m",
        "*.host[*].mobility.constraintAreaMaxY = 600m",
        "*.host[*].mobility.constraintAreaMinZ = 0m",
        "*.host[*].mobility.constraintAreaMaxZ = 200m",
        "",
        f"*.host[0..{n - 1}].mobility.pyClass = "
        '"pymodules.controllers.mdp_trajectory_planner.MdpTrajectoryPlanner"',
        "",
    ]

    for k in range(n):
        theta = theta0 + (2.0 * math.pi * k / n)
        theta_opp = theta + math.pi
        r = p.radius_m + rng.uniform(-p.radius_jitter_m, p.radius_jitter_m)
        z0 = p.cz + rng.uniform(-p.z_jitter_m, p.z_jitter_m)
        z1 = p.cz + rng.uniform(-p.z_jitter_m, p.z_jitter_m)
        x0 = p.cx + r * math.cos(theta)
        y0 = p.cy + r * math.sin(theta)
        x1 = p.cx + r * math.cos(theta_opp)
        y1 = p.cy + r * math.sin(theta_opp)
        mv = _movement_xml((x0, y0, z0), (x1, y1, z1), p.benign_speed, k)
        lines.append(f"*.host[{k}].mobility.initialX = {x0}m")
        lines.append(f"*.host[{k}].mobility.initialY = {y0}m")
        lines.append(f"*.host[{k}].mobility.initialZ = {z0}m")
        lines.append(f"*.host[{k}].mobility.waypointScript = xml(\"{mv}\")")
        lines.append("")

    spoofer_xml, sp0 = _spoofer_waypoints_xml(rng, p.spoofer_speed)
    sx, sy, sz = sp0
    lines.extend([
        f"*.host[{spoofer_host}].mobility.pyClass = "
        '"pymodules.controllers.cascaded_pid.CascadedPidController"',
        f"*.host[{spoofer_host}].wlan[0].mgmt.pyTxClass = "
        '"pymodules.spoofers.position_offset.PositionOffsetSpoofer"',
        f"*.host[{spoofer_host}].mobility.initialX = {sx}m",
        f"*.host[{spoofer_host}].mobility.initialY = {sy}m",
        f"*.host[{spoofer_host}].mobility.initialZ = {sz}m",
        f"*.host[{spoofer_host}].mobility.waypointScript = xml(\"{spoofer_xml}\")",
        "",
        "*.host[*].wlan[0].mgmt.transmitBeacon = true",
        "*.host[*].wlan[0].mgmt.beaconInterval = 1s",
        "*.host[*].wlan[0].mgmt.startupJitter = 0ms",
        f"*.host[{spoofer_host}].wlan[0].mgmt.beaconOffset = 0.5s",
        "",
        "*.host[*].wlan[0].mgmt.gcsModulePath = \"^.^.^.gcs[0]\"",
        "",
        f'*.gcs[0].federateIndices = "{" ".join(str(i) for i in range(n + 1))}"',
        "*.gcs[0].pyClass = \"pymodules.planners.spoofing_aware_gcs.SpoofingAwareGcs\"",
        "*.gcs[0].tickInterval = 0.25s",
        "*.gcs[0].sendControlCommands = true",
        "",
        "*.host[*].mobility.statistic-recording = true",
        "*.host[*].wlan[0].mgmt.statistic-recording = true",
        "",
        f"[Config {tag}_Aware]",
        f"extends = {tag}_Base",
        f'description = "SpoofingAwareGcs — {tag}"',
        "",
        f"[Config {tag}_AwareInstantDetect]",
        f"extends = {tag}_Base",
        f'description = "SpoofingAwareGcs instant-detect variant (set ULI_IMM_FORCE_DETECT_AT_S in runner) — {tag}"',
        "",
        f"[Config {tag}_TrustRid]",
        f"extends = {tag}_Base",
        f'description = "TrustRidGcs baseline — {tag}"',
        "*.gcs[0].pyClass = \"pymodules.planners.trust_rid_gcs.TrustRidGcs\"",
        "",
    ])
    return "\n".join(lines) + "\n"


def write_bundle(
    output_dir: Path,
    layout: str,
    seed: int,
    params: Circle8Params | None = None,
) -> Path:
    """Write omnetpp.ini + manifest.json; return scenario directory."""
    rng = random.Random(seed)
    p = params or Circle8Params()
    tag = f"{layout}_s{seed:05d}"
    out = output_dir / tag
    out.mkdir(parents=True, exist_ok=True)

    if layout == "circle8":
        ini_text = generate_circle8_ini(rng, p, tag)
    else:
        raise ValueError(f"Unknown layout: {layout}")

    (out / "omnetpp.ini").write_text(ini_text)
    manifest = {
        "version": "1.0",
        "layout": layout,
        "seed": seed,
        "tag": tag,
        "params": asdict(p),
        "configs": {
            "aware": f"{tag}_Aware",
            "aware_instant_detect": f"{tag}_AwareInstantDetect",
            "trust_rid": f"{tag}_TrustRid",
        },
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate spoofing batch scenarios")
    parser.add_argument(
        "--layout", default="circle8",
        help="Layout name (default: circle8)",
    )
    parser.add_argument(
        "--seeds", nargs="*", type=int, default=None,
        help="Integer seeds (each produces one scenario directory)",
    )
    parser.add_argument(
        "--seed-range", nargs=2, type=int, metavar=("LO", "HI"),
        help="Inclusive seed range (alternative to --seeds)",
    )
    parser.add_argument(
        "--output-dir", type=Path, required=True,
        help="Parent directory for generated scenario folders",
    )
    parser.add_argument("--cx", type=float, default=250.0)
    parser.add_argument("--cy", type=float, default=250.0)
    parser.add_argument("--cz", type=float, default=70.0)
    parser.add_argument("--radius", type=float, default=200.0)
    parser.add_argument("--radius-jitter", type=float, default=0.0)
    parser.add_argument("--z-jitter", type=float, default=0.0)
    parser.add_argument("--sim-time", type=float, default=120.0)
    args = parser.parse_args(argv)

    if args.seed_range is not None:
        lo, hi = args.seed_range
        seeds = list(range(lo, hi + 1))
    elif args.seeds:
        seeds = args.seeds
    else:
        parser.error("Provide --seeds and/or --seed-range LO HI")

    params = Circle8Params(
        cx=args.cx,
        cy=args.cy,
        cz=args.cz,
        radius_m=args.radius,
        radius_jitter_m=args.radius_jitter,
        z_jitter_m=args.z_jitter,
        sim_time_s=args.sim_time,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for seed in seeds:
        p = write_bundle(args.output_dir, args.layout, seed, params)
        written.append(p)
        print(p)

    print(f"Wrote {len(written)} scenario(s) under {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
