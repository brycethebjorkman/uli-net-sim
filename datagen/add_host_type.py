#!/usr/bin/env python3
"""
Add host_type and is_spoofed columns to scenario Parquet files.

Adds columns based on the host_id and event_type fields:
- 'host_type': 'spoofer' for hosts specified via --spoofer-hosts, 'benign' otherwise
- 'is_spoofed': 1 if the row is a spoofed transmission (TX from spoofer, or RX with
                serial_number matching a spoofer), 0 otherwise

Usage:
    add_host_type.py input.parquet --in-place [--spoofer-hosts 5]
"""

import argparse
import sys
from pathlib import Path

import pandas as pd


def main():
    parser = argparse.ArgumentParser(
        description="Add host_type and is_spoofed columns to Parquet files",
    )
    parser.add_argument('input', help='Input Parquet file')
    parser.add_argument('-o', '--output', help='Output Parquet file')
    parser.add_argument('--in-place', action='store_true',
                        help='Modify input file in place')
    parser.add_argument('--spoofer-hosts', default='',
                        help='Comma-separated list of spoofer host indices')

    args = parser.parse_args()

    if not args.output and not args.in_place:
        parser.error("Either --output or --in-place must be specified")
    if args.output and args.in_place:
        parser.error("Cannot specify both --output and --in-place")

    spoofer_hosts = set()
    if args.spoofer_hosts:
        for h in args.spoofer_hosts.split(','):
            h = h.strip()
            if h:
                spoofer_hosts.add(int(h))

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    df = pd.read_parquet(input_path)

    df['host_type'] = df['host_id'].apply(
        lambda h: 'spoofer' if int(h) in spoofer_hosts else 'benign')

    is_tx_spoof = (df['event_type'] == 'TX') & df['host_id'].isin(spoofer_hosts)
    is_rx_spoof = (df['event_type'] == 'RX') & df['serial_number'].isin(spoofer_hosts)
    df['is_spoofed'] = (is_tx_spoof | is_rx_spoof).astype(int)

    output_path = input_path if args.in_place else Path(args.output)
    df.to_parquet(output_path, index=False)

    num_spoofer = df['host_type'].eq('spoofer').sum()
    num_benign = len(df) - num_spoofer
    num_spoofed = df['is_spoofed'].sum()
    print(f"Added columns: {num_benign} benign/{num_spoofer} spoofer host events, {num_spoofed} spoofed rows")


if __name__ == '__main__':
    main()
