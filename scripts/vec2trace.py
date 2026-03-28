#!/usr/bin/env python3
"""
Convert OMNeT++ .vec position data to BonnMotion trace format for replay.

Extracts per-host (x, y, z) positions from mobility vectors and writes a
single .movements file compatible with INET's BonnMotionMobility (3D).

BonnMotion 3D format (one line per node, space-separated):
    t1 x1 y1 z1 t2 x2 y2 z2 ...

Usage:
    # Run headless simulation
    scripts/run.sh -f simulations/controller_test/omnetpp.ini \\
        -c CascadedPidStress -r /tmp/results -q

    # Convert .vec to BonnMotion trace
    python3 scripts/vec2trace.py /tmp/results/CascadedPidStress-#0.vec \\
        -o simulations/trajectory_replay/

    # Open simulations/trajectory_replay/omnetpp.ini in Qtenv for replay
"""

import argparse
import csv
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path


def extract_positions(vec_path: Path) -> dict[int, list[tuple[float, float, float, float]]]:
    """Extract per-host (time, x, y, z) from mobility position vectors.

    Reads posX:vector, posY:vector, posZ:vector from MultirotorMobility.

    Returns dict mapping host_id -> sorted list of (t, x, y, z).
    """
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    tmp_path = Path(tmp.name)

    try:
        subprocess.run(
            ['opp_scavetool', 'export', '-o', str(tmp_path), '-F', 'CSV-R',
             '-f', 'type=~"vector" AND module=~"*.host[*].mobility" '
                   'AND name=~"pos*:vector"',
             str(vec_path)],
            check=True, capture_output=True, text=True
        )

        # Parse CSV-R: each row has module, name, vectime, vecvalue
        vectors = {}
        with open(tmp_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['type'] != 'vector' or not row.get('vectime'):
                    continue
                module = row['module']
                name = row['name']
                times = [float(t) for t in row['vectime'].split()]
                values = [float(v) for v in row['vecvalue'].split()]
                vectors[(module, name)] = (times, values)

        # Group by host index
        hosts = defaultdict(lambda: {'x': {}, 'y': {}, 'z': {}})

        for (module, name), (times, values) in vectors.items():
            m = re.search(r'host\[(\d+)\]', module)
            if not m:
                continue
            host_id = int(m.group(1))

            if name == 'posX:vector':
                hosts[host_id]['x'] = dict(zip(times, values))
            elif name == 'posY:vector':
                hosts[host_id]['y'] = dict(zip(times, values))
            elif name == 'posZ:vector':
                hosts[host_id]['z'] = dict(zip(times, values))

        # Merge x/y/z by time for each host
        result = {}
        for host_id in sorted(hosts):
            h = hosts[host_id]
            if not h['x'] or not h['y'] or not h['z']:
                continue
            common_times = sorted(
                set(h['x'].keys()) & set(h['y'].keys()) & set(h['z'].keys()))
            if not common_times:
                continue
            result[host_id] = [
                (t, h['x'][t], h['y'][t], h['z'][t])
                for t in common_times
            ]

        return result

    finally:
        tmp_path.unlink(missing_ok=True)


def _resample(pts: list[tuple], dt: float) -> list[tuple]:
    """Resample position timeseries at fixed interval dt via linear interpolation."""
    if len(pts) < 2:
        return pts

    t_start, t_end = pts[0][0], pts[-1][0]
    result = []
    idx = 0
    t = t_start

    while t <= t_end + 1e-9:
        while idx < len(pts) - 1 and pts[idx + 1][0] < t:
            idx += 1

        if idx >= len(pts) - 1:
            result.append((t, pts[-1][1], pts[-1][2], pts[-1][3]))
        else:
            t0, x0, y0, z0 = pts[idx]
            t1, x1, y1, z1 = pts[idx + 1]
            if t1 - t0 < 1e-9:
                result.append((t, x0, y0, z0))
            else:
                a = (t - t0) / (t1 - t0)
                result.append((t, x0 + a * (x1 - x0),
                                   y0 + a * (y1 - y0),
                                   z0 + a * (z1 - z0)))
        t += dt

    return result


def write_bonnmotion(positions: dict[int, list], output_path: Path,
                     sample_dt: float | None = None) -> None:
    """Write BonnMotion 3D trace file (.movements).

    Args:
        positions: host_id -> [(t, x, y, z), ...]
        output_path: Path to write .movements file
        sample_dt: If set, resample at this interval (seconds).
                   If None, write all recorded samples.
    """
    if not positions:
        print("Warning: no position data found", file=sys.stderr)
        return

    max_host = max(positions.keys())
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        for host_id in range(max_host + 1):
            if host_id not in positions:
                f.write('0 0 0 0\n')
                continue

            pts = positions[host_id]
            if sample_dt is not None and len(pts) > 2:
                pts = _resample(pts, sample_dt)

            parts = []
            for t, x, y, z in pts:
                parts.extend([f'{t:.3f}', f'{x:.2f}', f'{y:.2f}', f'{z:.2f}'])
            f.write(' '.join(parts) + '\n')

    n_hosts = max_host + 1
    n_points = sum(len(v) for v in positions.values())
    print(f"Wrote {output_path}: {n_hosts} hosts, {n_points} samples")


def main():
    parser = argparse.ArgumentParser(
        description='Convert .vec mobility positions to BonnMotion trace')
    parser.add_argument('vec_file', type=Path, help='Input .vec file')
    parser.add_argument('-o', '--output-dir', type=Path, default=Path('.'),
                        help='Output directory (default: current dir)')
    parser.add_argument('--dt', type=float, default=0.1,
                        help='Resample interval in seconds (default: 0.1). '
                             'Use 0 to write all recorded samples.')
    args = parser.parse_args()

    positions = extract_positions(args.vec_file)
    if not positions:
        print(f"Error: no position data found in {args.vec_file}",
              file=sys.stderr)
        sys.exit(1)

    stem = args.vec_file.stem.replace('-#0', '')
    output_path = args.output_dir / f'{stem}.movements'
    sample_dt = args.dt if args.dt > 0 else None
    write_bonnmotion(positions, output_path, sample_dt=sample_dt)


if __name__ == '__main__':
    main()
