#!/usr/bin/env python3

import argparse
import csv
import re
import sys

def parse_args():
    p = argparse.ArgumentParser(description="Collect CSV columns by name.")
    p.add_argument("input", help="Path to CSV file or '-' for stdin")
    p.add_argument("-c", "--column", action="append", dest="columns",
                   help="Column name to collect (repeatable). If omitted, collect all.")
    return p.parse_args()

def collect_columns(fp, fieldname_patterns):
    reader = csv.DictReader(fp)

    fieldnames = reader.fieldnames
    if not fieldnames:
        raise ValueError("No header row found in CSV")

    columns = []
    if fieldname_patterns is None:
        columns = fieldnames
    else:
        for fn_p in fieldname_patterns:
            pattern = re.compile(fn_p)
            matches = [fn for fn in fieldnames if pattern.search(fn)]
            if len(matches) > 0:
                columns.extend(matches)

    data = {c : [] for c in columns}

    for row in reader:
        for c in columns:
            val = row.get(c, "")
            data[c].append(val)
    return data

def main():
    args = parse_args()
    with open(args.input, "r") as fp:
        cols = collect_columns(fp, args.columns)
    for name, values in cols.items():
        print(f"{name}: {len(values)} rows")
        print(values)

if __name__ == "__main__":
    main()
