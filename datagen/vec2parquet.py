#!/usr/bin/env python3
"""
Extract OMNeT++ .vec vectors to Parquet format with per-vector hashing.

Extracts only vectors from our modules (mobility, beacon management, GCS)
via opp_scavetool, filters by explicit name whitelist, and optionally
writes to Parquet or prints per-vector SHA256 hashes.

Usage:
    python datagen/vec2parquet.py INPUT.vec -o output.parquet
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
from fnmatch import fnmatch
from pathlib import Path

# ---------------------------------------------------------------------------
# Vector specifications: (module_pattern for opp_scavetool, name_pattern for fnmatch)
# ---------------------------------------------------------------------------

DEFAULT_VECTOR_SPECS = [
    # MultirotorMobility signals (explicit — no inherited stats)
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
    """Strip network name prefix: 'BasicUav.host[0].mobility' → 'host[0].mobility'."""
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

    Groups specs by module_pattern, runs one opp_scavetool call per unique
    module pattern, parses CSV-R output, filters by name patterns.

    Returns {(module_short, name): (times[], values[])}.
    module_short has network prefix stripped (e.g. "host[0].mobility").
    """
    if vector_specs is None:
        vector_specs = DEFAULT_VECTOR_SPECS

    # Group name patterns by module pattern
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


def main():
    parser = argparse.ArgumentParser(
        description='Extract OMNeT++ .vec vectors to Parquet with per-vector hashing')
    parser.add_argument('vec_file', help='Input .vec file')
    parser.add_argument('-o', '--output', help='Output Parquet file')
    parser.add_argument('--hash', action='store_true',
                        help='Print per-vector SHA256 hashes')
    args = parser.parse_args()

    if not args.output and not args.hash:
        parser.error('Specify -o OUTPUT.parquet and/or --hash')

    vectors = extract_vectors(args.vec_file)
    print(f"Extracted {len(vectors)} vectors", file=sys.stderr)

    if args.output:
        vectors_to_parquet(vectors, args.output)
        print(f"Written to {args.output}", file=sys.stderr)

    if args.hash:
        import json
        hashes = {}
        for (mod, name), (times, values) in sorted(vectors.items()):
            h = hash_vector_data(times, values)
            hashes[f"{mod}||{name}"] = h
        print(json.dumps(hashes, indent=2))


if __name__ == '__main__':
    main()
