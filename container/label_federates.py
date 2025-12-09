#!/usr/bin/env python3
"""
Generate federate variant CSV files from a base CSV with host_type labels.

Takes a CSV that already has host_type (benign/spoofer) labels and creates
variant files where different combinations of benign hosts are relabeled
as 'federate'.

For RSSI-based multilateration, 4 federates are the minimum needed for
3D positioning.

Usage:
    label_federates.py input.csv --num-federates 4
    label_federates.py input.csv --num-federates 4 --max-variants 8 --seed 42
"""

import argparse
import csv
import itertools
import random
import sys
from pathlib import Path


def get_benign_hosts(csv_path: Path) -> list[int]:
    """Extract unique benign host IDs from CSV."""
    benign_hosts = set()
    with open(csv_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('host_type') == 'benign':
                benign_hosts.add(int(row['host_id']))
    return sorted(benign_hosts)


def generate_variant(input_path: Path, output_path: Path, federate_hosts: set[int]):
    """Generate a variant CSV with specified hosts labeled as federate."""
    with open(input_path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for row in rows:
            host_id = int(row['host_id'])
            if host_id in federate_hosts:
                row['host_type'] = 'federate'
            writer.writerow(row)


def format_federate_suffix(federate_hosts: list[int]) -> str:
    """Format federate host IDs as suffix string, e.g., 'f0-1-3-12'."""
    return 'f' + '-'.join(str(h) for h in sorted(federate_hosts))


def main():
    parser = argparse.ArgumentParser(
        description="Generate federate variant CSV files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate all federate combinations (up to max-variants)
    %(prog)s scenario.csv --num-federates 4

    # Limit to 8 variants with reproducible seed
    %(prog)s scenario.csv --num-federates 4 --max-variants 8 --seed 42

    # Specify output directory
    %(prog)s scenario.csv --num-federates 4 -o ./variants/
"""
    )

    parser.add_argument('input', help='Input CSV file with host_type column')
    parser.add_argument('--num-federates', type=int, default=4,
                        help='Number of benign hosts to label as federate (default: 4)')
    parser.add_argument('--max-variants', type=int, default=8,
                        help='Maximum number of variants to generate (default: 8)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed for reproducible variant selection')
    parser.add_argument('-o', '--output-dir', default=None,
                        help='Output directory (default: same as input file)')

    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: Input file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Determine output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = input_path.parent

    # Set seed early for reproducibility
    if args.seed is not None:
        random.seed(args.seed)

    # Get benign hosts
    benign_hosts = get_benign_hosts(input_path)
    num_benign = len(benign_hosts)

    if num_benign < args.num_federates:
        print(f"Error: Not enough benign hosts ({num_benign}) for {args.num_federates} federates",
              file=sys.stderr)
        sys.exit(1)

    # Generate all possible combinations (sorted for determinism)
    all_combinations = list(itertools.combinations(sorted(benign_hosts), args.num_federates))
    total_combinations = len(all_combinations)

    # Sample if needed
    if total_combinations <= args.max_variants:
        selected_combinations = all_combinations
        print(f"Generating all {total_combinations} federate combinations")
    else:
        selected_combinations = random.sample(all_combinations, args.max_variants)
        print(f"Randomly sampling {args.max_variants} of {total_combinations} combinations (seed={args.seed})")

    # Determine base filename (strip existing suffix like -o or -b)
    stem = input_path.stem
    # Output files go in output_dir with federate suffix added before extension

    generated_files = []
    for combo in selected_combinations:
        federate_set = set(combo)
        suffix = format_federate_suffix(combo)
        output_filename = f"{stem}-{suffix}.csv"
        output_path = output_dir / output_filename

        generate_variant(input_path, output_path, federate_set)
        generated_files.append(output_path)

    print(f"Generated {len(generated_files)} variant files:")
    for f in generated_files:
        print(f"  {f}")

    # Output machine-readable list of generated files
    print(f"VARIANT_COUNT={len(generated_files)}")


if __name__ == '__main__':
    main()
