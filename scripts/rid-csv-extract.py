#!/usr/bin/env python3

import argparse
import csv
import json
import re

def parse_args():
    p = argparse.ArgumentParser(description="Collect uav_rid time series data from CSV by name.")
    p.add_argument("input", help="Path to CSV file or '-' for stdin")
    p.add_argument("--name-pattern", action="append", dest="name_patterns")
    p.add_argument("--host-map", nargs="+", type=int)
    return p.parse_args()

def collect_time_series(fp, name_patterns, host_map):
    reader = csv.DictReader(fp)

    fieldnames = reader.fieldnames
    if not fieldnames:
        raise ValueError("No header row found in CSV")
    
    rows = list(reader)

    # csv will have no rows if no hosts received the transmission
    if len(rows) == 0:
        return {}

    # csv should have fieldnames: run,type,module,name,attrname,attrvalue,vectime,vecvalue
    expected_csv_fields = ["module","name","vectime","vecvalue"]
    if not set(expected_csv_fields).issubset(fieldnames):
        raise ValueError(f"Expected CSV fields {expected_csv_fields} missing from {fieldnames}")

    names = [row["name"] for row in rows]
    selected = set()
    for fn_p in name_patterns:
        pattern = re.compile(fn_p)
        matches = [name for name in names if pattern.search(name)]
        if len(matches) == 0:
            raise ValueError(f"No time series data with name matching pattern '{pattern}'")
        selected.update(matches)

    rows = [row for row in rows if row["name"] in selected]
    data = {name : {} for name in selected}

    host_num_pattern = re.compile(r'\bhost\[(\d+)\]')
    for row in rows:
        host_num = int(host_num_pattern.search(row.get("module")).group(1))
        name = row.get("name")
        time = row.get("vectime")
        value = row.get("vecvalue")
        data[name][host_map[host_num]] = {
            "times" : time.split(),
            "values" : value.split(),
        }
    return data

def main():
    args = parse_args()
    with open(args.input, "r") as fp:
        data = collect_time_series(fp, args.name_patterns, args.host_map)
    print(json.dumps(data))

if __name__ == "__main__":
    main()
