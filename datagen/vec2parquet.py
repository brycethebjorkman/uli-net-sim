#!/usr/bin/env python3
"""
Convert OMNeT++ .vec files to Parquet format.

Default mode: event-per-row Parquet with one row per TX/RX event
(canonical scenario dataset format consumed by evaluations/).

Raw mode (--raw): one row per vector with list<float64> columns
(used for regression test hashing).

Usage:
    # Canonical event-per-row format (for datasets)
    python datagen/vec2parquet.py INPUT.vec -o output.parquet

    # Raw vector archive (for hashing)
    python datagen/vec2parquet.py INPUT.vec --raw -o vectors.parquet

    # Print per-vector hashes only
    python datagen/vec2parquet.py INPUT.vec --hash
"""

import argparse
import csv
import hashlib
import os
import struct
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, asdict
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Vector specifications: (module_pattern for opp_scavetool, name_pattern for fnmatch)
# ---------------------------------------------------------------------------

DEFAULT_VECTOR_SPECS = [
    # MultirotorMobility signals (explicit — no inherited stats)
    ("*.host[*].mobility", "posX:vector"),
    ("*.host[*].mobility", "posY:vector"),
    ("*.host[*].mobility", "posZ:vector"),
    ("*.host[*].mobility", "velX:vector"),
    ("*.host[*].mobility", "velY:vector"),
    ("*.host[*].mobility", "velZ:vector"),
    ("*.host[*].mobility", "thrust:vector"),
    ("*.host[*].mobility", "tauPhi:vector"),
    ("*.host[*].mobility", "tauTheta:vector"),
    ("*.host[*].mobility", "tauPsi:vector"),
    ("*.host[*].mobility", "phi:vector"),
    ("*.host[*].mobility", "theta:vector"),
    ("*.host[*].mobility", "psi:vector"),
    ("*.host[*].mobility", "omegaP:vector"),
    ("*.host[*].mobility", "omegaQ:vector"),
    ("*.host[*].mobility", "omegaR:vector"),
    # RidBeaconMgmt vectors (prefix patterns — excludes inherited counters)
    ("*.host[*].wlan[0].mgmt", "Transmission *"),
    ("*.host[*].wlan[0].mgmt", "Reception *"),
    ("*.host[*].wlan[0].mgmt", "Serial Number"),
    ("*.host[*].wlan[0].mgmt", "Packet ID"),
    ("*.host[*].wlan[0].mgmt", "KF *"),
    # GCS vectors (all — only our dynamic cOutVectors live here)
    ("*.gcs[*]", "*"),
]


# ---------------------------------------------------------------------------
# Low-level vector extraction (shared by both modes)
# ---------------------------------------------------------------------------

def _run_scavetool(vec_path, module_pattern):
    """Run opp_scavetool for a single module pattern, return temp CSV path."""
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    cmd = [
        'opp_scavetool', 'export', '-F', 'CSV-R', '-x', 'columnNames=true',
        '-f', f'type=~"vector" and module=~"{module_pattern}"',
        '-o', tmp.name, str(vec_path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        os.unlink(tmp.name)
        raise RuntimeError(f"opp_scavetool failed for {module_pattern}: {r.stderr}")
    return tmp.name


def _strip_network_prefix(module_path):
    """Strip network name prefix: 'BasicUav.host[0].mobility' -> 'host[0].mobility'."""
    dot = module_path.find('.')
    return module_path[dot + 1:] if dot >= 0 else module_path


def _parse_csvr(csv_path, name_patterns):
    """Parse CSV-R file, filter by name patterns, return vectors dict."""
    vectors = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('type') != 'vector':
                continue
            name = row['name']
            if not any(fnmatch(name, pat) for pat in name_patterns):
                continue
            module_short = _strip_network_prefix(row['module'])
            times_str = row.get('vectime', '')
            values_str = row.get('vecvalue', '')
            if times_str and values_str:
                times = [float(t) for t in times_str.split()]
                values = [float(v) for v in values_str.split()]
                vectors[(module_short, name)] = (times, values)
    return vectors


def extract_vectors(vec_path, vector_specs=None):
    """Extract vectors from .vec via opp_scavetool with name filtering.

    Returns {(module_short, name): (times[], values[])}.
    """
    if vector_specs is None:
        vector_specs = DEFAULT_VECTOR_SPECS

    groups = defaultdict(list)
    for mod_pat, name_pat in vector_specs:
        groups[mod_pat].append(name_pat)

    all_vectors = {}
    for mod_pat, name_pats in groups.items():
        tmp_csv = _run_scavetool(vec_path, mod_pat)
        try:
            vectors = _parse_csvr(tmp_csv, name_pats)
            all_vectors.update(vectors)
        finally:
            os.unlink(tmp_csv)

    return all_vectors


def hash_vector_data(times, values):
    """SHA256 of (times, values) data only. Module/name NOT included."""
    h = hashlib.sha256()
    h.update(struct.pack(f'{len(times)}d', *times))
    h.update(struct.pack(f'{len(values)}d', *values))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Raw mode: one row per vector (for hashing/archiving)
# ---------------------------------------------------------------------------

def vectors_to_parquet(vectors, output_path):
    """Write vectors dict to Parquet (row-per-vector, list<float64> columns)."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    modules = []
    names = []
    times_col = []
    values_col = []

    for (mod, name), (times, values) in sorted(vectors.items()):
        modules.append(mod)
        names.append(name)
        times_col.append(times)
        values_col.append(values)

    table = pa.table({
        'module': pa.array(modules, type=pa.string()),
        'name': pa.array(names, type=pa.string()),
        'times': pa.array(times_col, type=pa.list_(pa.float64())),
        'values': pa.array(values_col, type=pa.list_(pa.float64())),
    })
    pq.write_table(table, str(output_path))


# ---------------------------------------------------------------------------
# Canonical mode: one row per TX/RX event (for datasets)
# ---------------------------------------------------------------------------

@dataclass
class VectorData:
    """Stores time-value pairs for a vector."""
    times: List[float]
    values: List[float]

    def get_value_at_index(self, idx: int) -> Optional[float]:
        return self.values[idx] if idx < len(self.values) else None

    def find_closest_value(self, time: float) -> Optional[float]:
        if not self.times:
            return None
        left, right = 0, len(self.times) - 1
        while left < right:
            mid = (left + right + 1) // 2
            if self.times[mid] <= time:
                left = mid
            else:
                right = mid - 1
        if abs(self.times[left] - time) < 0.01:
            return self.values[left]
        return None


def _export_mgmt_vectors(vec_file: str) -> str:
    """Use opp_scavetool to export beacon mgmt vectors to temp CSV."""
    tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp.close()
    cmd = [
        'opp_scavetool', 'export', '-F', 'CSV-R', '-x', 'columnNames=true',
        '-f', 'type=~"vector" and module=~"*.host[*].wlan[0].mgmt"',
        '-o', tmp.name, vec_file,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"opp_scavetool failed: {r.stderr}")
    return tmp.name


def _parse_host_vectors(csv_file: str) -> Dict[int, Dict[str, VectorData]]:
    """Parse CSV-R output into {host_id: {vector_name: VectorData}}."""
    host_vectors = defaultdict(lambda: defaultdict(lambda: VectorData([], [])))
    with open(csv_file) as f:
        reader = csv.DictReader(f)
        for row in reader:
            module = row['module']
            if '.host[' not in module:
                continue
            host_id = int(module.split('.host[')[1].split(']')[0])
            name = row['name']
            times_str = row.get('vectime', '')
            values_str = row.get('vecvalue', '')
            if times_str and values_str:
                times = [float(t) for t in times_str.split()]
                values = [float(v) for v in values_str.split()]
                host_vectors[host_id][name] = VectorData(times, values)
    return host_vectors


def _generate_events(host_vectors):
    """Generate event dicts from parsed vectors."""
    events = []
    empty = VectorData([], [])

    for host_id, vecs in host_vectors.items():
        # TX events
        tx_x = vecs.get('Transmission X Coordinate')
        if tx_x and tx_x.times:
            tx_pkt_id_vec = vecs.get('Transmission Packet ID', empty)
            tx_spoofed_vec = vecs.get('Transmission Is Spoofed', empty)
            for i, time in enumerate(tx_x.times):
                pkt_id = tx_pkt_id_vec.get_value_at_index(i)
                if pkt_id is not None:
                    pkt_id = int(pkt_id)
                spoofed = tx_spoofed_vec.get_value_at_index(i)
                events.append({
                    'time': time,
                    'event_type': 'TX',
                    'host_id': host_id,
                    'packet_id': pkt_id,
                    'serial_number': host_id,
                    'rid_timestamp': int(time * 1000),
                    'pos_x': vecs.get('Transmission My X Coordinate', empty).get_value_at_index(i),
                    'pos_y': vecs.get('Transmission My Y Coordinate', empty).get_value_at_index(i),
                    'pos_z': vecs.get('Transmission My Z Coordinate', empty).get_value_at_index(i),
                    'speed_vertical': vecs.get('Transmission My Vertical Speed', empty).get_value_at_index(i),
                    'speed_horizontal': vecs.get('Transmission My Horizontal Speed', empty).get_value_at_index(i),
                    'heading': vecs.get('Transmission My Heading', empty).get_value_at_index(i),
                    'rid_pos_x': vecs['Transmission X Coordinate'].get_value_at_index(i),
                    'rid_pos_y': vecs['Transmission Y Coordinate'].get_value_at_index(i),
                    'rid_pos_z': vecs['Transmission Z Coordinate'].get_value_at_index(i),
                    'rid_speed_vertical': vecs.get('Transmission Vertical Speed', empty).get_value_at_index(i),
                    'rid_speed_horizontal': vecs.get('Transmission Horizontal Speed', empty).get_value_at_index(i),
                    'rid_heading': vecs.get('Transmission Heading', empty).get_value_at_index(i),
                    'tx_power': vecs.get('Transmission Power', empty).get_value_at_index(i),
                    'is_spoofed': int(spoofed) if spoofed is not None else None,
                    'rssi': None,
                    'kf_nis': None,
                })

        # RX events
        rx_power = vecs.get('Reception Power')
        if rx_power and rx_power.times:
            rx_pkt_id_vec = vecs.get('Packet ID', empty)
            for i, time in enumerate(rx_power.times):
                sn = vecs.get('Serial Number', empty).get_value_at_index(i)
                if sn is not None:
                    sn = int(sn)
                rid_ts_val = vecs.get('Reception Timestamp', empty).get_value_at_index(i)
                rid_ts = int(rid_ts_val) if rid_ts_val is not None else None
                pkt_id = rx_pkt_id_vec.get_value_at_index(i)
                if pkt_id is not None:
                    pkt_id = int(pkt_id)

                kf_nis_vec = vecs.get(f'KF NIS Drone {sn}', empty)

                events.append({
                    'time': time,
                    'event_type': 'RX',
                    'host_id': host_id,
                    'packet_id': pkt_id,
                    'serial_number': sn,
                    'rid_timestamp': rid_ts,
                    'pos_x': vecs.get('Reception My X Coordinate', empty).get_value_at_index(i),
                    'pos_y': vecs.get('Reception My Y Coordinate', empty).get_value_at_index(i),
                    'pos_z': vecs.get('Reception My Z Coordinate', empty).get_value_at_index(i),
                    'speed_vertical': vecs.get('Reception My Vertical Speed', empty).get_value_at_index(i),
                    'speed_horizontal': vecs.get('Reception My Horizontal Speed', empty).get_value_at_index(i),
                    'heading': vecs.get('Reception My Heading', empty).get_value_at_index(i),
                    'rid_pos_x': vecs.get('Reception X Coordinate', empty).get_value_at_index(i),
                    'rid_pos_y': vecs.get('Reception Y Coordinate', empty).get_value_at_index(i),
                    'rid_pos_z': vecs.get('Reception Z Coordinate', empty).get_value_at_index(i),
                    'rid_speed_vertical': vecs.get('Reception Vertical Speed', empty).get_value_at_index(i),
                    'rid_speed_horizontal': vecs.get('Reception Horizontal Speed', empty).get_value_at_index(i),
                    'rid_heading': vecs.get('Reception Heading', empty).get_value_at_index(i),
                    'tx_power': None,
                    'is_spoofed': None,  # filled by packet_id join below
                    'rssi': rx_power.get_value_at_index(i),
                    'kf_nis': kf_nis_vec.find_closest_value(time),
                })

    events.sort(key=lambda e: e['time'])
    return events


def events_to_parquet(vec_file, output_path, spoofer_hosts=None):
    """Convert .vec to canonical event-per-row Parquet.

    Args:
        vec_file: Path to .vec file
        output_path: Path to output .parquet file
        spoofer_hosts: Set of host IDs that are spoofers (for host_type/is_spoofed).
                       If None, host_type and is_spoofed columns are omitted.
    """
    import pandas as pd

    tmp_csv = _export_mgmt_vectors(str(vec_file))
    try:
        host_vectors = _parse_host_vectors(tmp_csv)
    finally:
        os.unlink(tmp_csv)

    events = _generate_events(host_vectors)
    df = pd.DataFrame(events)

    # Join RX is_spoofed from TX via packet_id (shared tree ID).
    tx_spoofed = (df.loc[df['event_type'] == 'TX', ['packet_id', 'is_spoofed']]
                  .dropna(subset=['packet_id'])
                  .drop_duplicates(subset=['packet_id'])
                  .rename(columns={'is_spoofed': '_tx_is_spoofed'}))
    df = df.merge(tx_spoofed, on='packet_id', how='left')
    rx_mask = df['event_type'] == 'RX'
    df.loc[rx_mask, 'is_spoofed'] = df.loc[rx_mask, '_tx_is_spoofed']
    df.drop(columns=['_tx_is_spoofed'], inplace=True)
    df['is_spoofed'] = df['is_spoofed'].fillna(0).astype(int)

    if spoofer_hosts is not None:
        spoofer_hosts = set(int(h) for h in spoofer_hosts)
        df['host_type'] = df['host_id'].apply(
            lambda h: 'spoofer' if int(h) in spoofer_hosts else 'benign')

    df.to_parquet(str(output_path), index=False)
    return len(events)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Convert OMNeT++ .vec to Parquet (event-per-row or raw vectors)')
    parser.add_argument('vec_file', help='Input .vec file')
    parser.add_argument('-o', '--output', help='Output Parquet file')
    parser.add_argument('--raw', action='store_true',
                        help='Raw vector archive (one row per vector with list columns)')
    parser.add_argument('--spoofer-hosts', default='',
                        help='Comma-separated spoofer host indices (adds host_type/is_spoofed columns)')
    parser.add_argument('--hash', action='store_true',
                        help='Print per-vector SHA256 hashes (uses raw vector extraction)')
    args = parser.parse_args(argv)

    if not args.output and not args.hash:
        parser.error('Specify -o OUTPUT.parquet and/or --hash')

    if args.raw or args.hash:
        vectors = extract_vectors(args.vec_file)
        print(f"Extracted {len(vectors)} vectors", file=sys.stderr)

        if args.output and args.raw:
            vectors_to_parquet(vectors, args.output)
            print(f"Written to {args.output}", file=sys.stderr)

        if args.hash:
            import json
            hashes = {}
            for (mod, name), (times, values) in sorted(vectors.items()):
                h = hash_vector_data(times, values)
                hashes[f"{mod}||{name}"] = h
            print(json.dumps(hashes, indent=2))
    else:
        spoofer_hosts = None
        if args.spoofer_hosts:
            spoofer_hosts = set(
                int(h.strip()) for h in args.spoofer_hosts.split(',') if h.strip())
        n = events_to_parquet(args.vec_file, args.output, spoofer_hosts=spoofer_hosts)
        print(f"Written {n} events to {args.output}", file=sys.stderr)


if __name__ == '__main__':
    main()
