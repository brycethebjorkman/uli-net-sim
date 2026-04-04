#!/usr/bin/env python3
"""
Convert OMNeT++ .vec files to CSV format for Remote ID spoofing detection analysis.

Produces a timeseries CSV with one row per event (transmission or reception),
including Remote ID fields, mobility info, transmission power, RSSI, and
Kalman Filter outputs.
"""

import argparse
import csv
import os
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class VectorData:
    """Stores time-value pairs for a vector."""
    times: List[float]
    values: List[float]

    def get_value_at_index(self, idx: int) -> Optional[float]:
        """Get value at a specific index, or None if out of bounds."""
        return self.values[idx] if idx < len(self.values) else None

    def find_closest_value(self, time: float) -> Optional[float]:
        """Find the value at or closest before the given time."""
        if not self.times:
            return None
        # Binary search for closest time
        left, right = 0, len(self.times) - 1
        while left < right:
            mid = (left + right + 1) // 2
            if self.times[mid] <= time:
                left = mid
            else:
                right = mid - 1
        return self.values[left] if self.times[left] <= time else None


@dataclass
class Event:
    """Represents a single TX or RX event."""
    time: float
    event_type: str  # "TX" or "RX"
    host_id: int
    serial_number: Optional[int] = None
    rid_timestamp: Optional[int] = None  # RID message timestamp (ms since sim start)
    # Actual position/velocity of the host (transmitter for TX, receiver for RX)
    pos_x: Optional[float] = None
    pos_y: Optional[float] = None
    pos_z: Optional[float] = None
    speed_vertical: Optional[float] = None
    speed_horizontal: Optional[float] = None
    heading: Optional[float] = None
    # Remote ID message fields (claimed position/velocity from the message)
    rid_pos_x: Optional[float] = None
    rid_pos_y: Optional[float] = None
    rid_pos_z: Optional[float] = None
    rid_speed_vertical: Optional[float] = None
    rid_speed_horizontal: Optional[float] = None
    rid_heading: Optional[float] = None
    # Transmission and detection fields
    tx_power: Optional[float] = None
    rssi: Optional[float] = None
    kf_estimate: Optional[float] = None
    kf_covariance: Optional[float] = None
    kf_gain: Optional[float] = None
    kf_innovation: Optional[float] = None
    kf_nis: Optional[float] = None
    kf_measurement: Optional[float] = None


def export_vectors_to_csv(vec_file: str) -> str:
    """
    Use opp_scavetool to export vectors to CSV.
    Returns path to temporary CSV file.
    """
    tmp_csv = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
    tmp_csv.close()

    # Export all management layer vectors
    cmd = [
        'opp_scavetool', 'export',
        '-F', 'CSV-R',
        '-x', 'columnNames=true',
        '-f', 'type=~"vector" and module=~"*.host[*].wlan[0].mgmt"',
        '-o', tmp_csv.name,
        vec_file
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"opp_scavetool failed: {result.stderr}")

    return tmp_csv.name


def parse_csv_vectors(csv_file: str) -> Dict[int, Dict[str, VectorData]]:
    """
    Parse the CSV output from opp_scavetool.
    Returns: {host_id: {vector_name: VectorData}}
    """
    host_vectors = defaultdict(lambda: defaultdict(lambda: VectorData([], [])))

    with open(csv_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Extract host number from module path (e.g., "BasicUav.host[0].wlan[0].mgmt")
            module = row['module']
            host_match = module.split('.host[')[1].split(']')[0] if '.host[' in module else None
            if host_match is None:
                continue

            host_id = int(host_match)
            vector_name = row['name']

            # Parse times and values (space-separated in CSV-R format)
            times_str = row.get('vectime', '')
            values_str = row.get('vecvalue', '')

            if times_str and values_str:
                times = [float(t) for t in times_str.split()]
                values = [float(v) for v in values_str.split()]
                host_vectors[host_id][vector_name] = VectorData(times, values)

    return host_vectors


def generate_events(host_vectors: Dict[int, Dict[str, VectorData]]) -> List[Event]:
    """
    Generate Event objects from parsed vectors.
    Creates TX events from transmission vectors and RX events from reception vectors.
    """
    events = []

    for host_id, vectors in host_vectors.items():
        # Generate TX events (when this host transmits)
        tx_times = vectors.get('Transmission X Coordinate')
        if tx_times and tx_times.times:
            for i, time in enumerate(tx_times.times):
                # RID timestamp is TX time in milliseconds
                rid_ts = int(time * 1000)
                event = Event(
                    time=time,
                    event_type='TX',
                    host_id=host_id,
                    serial_number=host_id,  # Assume serial_number = host_id for TX
                    rid_timestamp=rid_ts,
                    # Actual transmitter position/velocity (use "My" vectors)
                    pos_x=vectors.get('Transmission My X Coordinate', VectorData([], [])).get_value_at_index(i),
                    pos_y=vectors.get('Transmission My Y Coordinate', VectorData([], [])).get_value_at_index(i),
                    pos_z=vectors.get('Transmission My Z Coordinate', VectorData([], [])).get_value_at_index(i),
                    speed_vertical=vectors.get('Transmission My Vertical Speed', VectorData([], [])).get_value_at_index(i),
                    speed_horizontal=vectors.get('Transmission My Horizontal Speed', VectorData([], [])).get_value_at_index(i),
                    heading=vectors.get('Transmission My Heading', VectorData([], [])).get_value_at_index(i),
                    # Remote ID message fields (claimed position/velocity from RID message)
                    rid_pos_x=vectors['Transmission X Coordinate'].get_value_at_index(i),
                    rid_pos_y=vectors['Transmission Y Coordinate'].get_value_at_index(i),
                    rid_pos_z=vectors['Transmission Z Coordinate'].get_value_at_index(i),
                    rid_speed_vertical=vectors.get('Transmission Vertical Speed', VectorData([], [])).get_value_at_index(i),
                    rid_speed_horizontal=vectors.get('Transmission Horizontal Speed', VectorData([], [])).get_value_at_index(i),
                    rid_heading=vectors.get('Transmission Heading', VectorData([], [])).get_value_at_index(i),
                    tx_power=vectors.get('Transmission Power', VectorData([], [])).get_value_at_index(i),
                )
                events.append(event)

        # Generate RX events (when this host receives)
        rx_times = vectors.get('Reception Power')
        if rx_times and rx_times.times:
            for i, time in enumerate(rx_times.times):
                serial_num = vectors.get('Serial Number', VectorData([], [])).get_value_at_index(i)
                if serial_num is not None:
                    serial_num = int(serial_num)

                # Get RID timestamp from the message (recorded as Reception Timestamp)
                rid_ts_val = vectors.get('Reception Timestamp', VectorData([], [])).get_value_at_index(i)
                rid_ts = int(rid_ts_val) if rid_ts_val is not None else None

                # Find KF vectors for this serial number if they exist
                kf_estimate_vec = vectors.get(f'KF Tx Power Estimate Drone {serial_num}', VectorData([], []))
                kf_covariance_vec = vectors.get(f'KF Covariance Drone {serial_num}', VectorData([], []))
                kf_gain_vec = vectors.get(f'KF Gain Drone {serial_num}', VectorData([], []))
                kf_innovation_vec = vectors.get(f'KF Innovation Drone {serial_num}', VectorData([], []))
                kf_nis_vec = vectors.get(f'KF NIS Drone {serial_num}', VectorData([], []))
                kf_measurement_vec = vectors.get(f'KF Measurement Drone {serial_num}', VectorData([], []))

                event = Event(
                    time=time,
                    event_type='RX',
                    host_id=host_id,
                    serial_number=serial_num,
                    rid_timestamp=rid_ts,
                    # Actual receiver position/velocity
                    pos_x=vectors.get('Reception My X Coordinate', VectorData([], [])).get_value_at_index(i),
                    pos_y=vectors.get('Reception My Y Coordinate', VectorData([], [])).get_value_at_index(i),
                    pos_z=vectors.get('Reception My Z Coordinate', VectorData([], [])).get_value_at_index(i),
                    speed_vertical=vectors.get('Reception My Vertical Speed', VectorData([], [])).get_value_at_index(i),
                    speed_horizontal=vectors.get('Reception My Horizontal Speed', VectorData([], [])).get_value_at_index(i),
                    heading=vectors.get('Reception My Heading', VectorData([], [])).get_value_at_index(i),
                    # Remote ID message fields (claimed position/velocity from transmitter)
                    rid_pos_x=vectors.get('Reception X Coordinate', VectorData([], [])).get_value_at_index(i),
                    rid_pos_y=vectors.get('Reception Y Coordinate', VectorData([], [])).get_value_at_index(i),
                    rid_pos_z=vectors.get('Reception Z Coordinate', VectorData([], [])).get_value_at_index(i),
                    rid_speed_vertical=vectors.get('Reception Vertical Speed', VectorData([], [])).get_value_at_index(i),
                    rid_speed_horizontal=vectors.get('Reception Horizontal Speed', VectorData([], [])).get_value_at_index(i),
                    rid_heading=vectors.get('Reception Heading', VectorData([], [])).get_value_at_index(i),
                    rssi=vectors['Reception Power'].get_value_at_index(i),
                    # KF outputs - find closest value by time since KF updates might not align exactly
                    kf_estimate=kf_estimate_vec.find_closest_value(time),
                    kf_covariance=kf_covariance_vec.find_closest_value(time),
                    kf_gain=kf_gain_vec.find_closest_value(time),
                    kf_innovation=kf_innovation_vec.find_closest_value(time),
                    kf_nis=kf_nis_vec.find_closest_value(time),
                    kf_measurement=kf_measurement_vec.find_closest_value(time),
                )
                events.append(event)

    # Sort by time
    events.sort(key=lambda e: e.time)
    return events


def write_parquet(events: List[Event], output_file: str):
    """Write events to Parquet file."""
    import pandas as pd
    from dataclasses import asdict
    rows = [asdict(e) for e in events]
    df = pd.DataFrame(rows)
    df.to_parquet(output_file, index=False)


def main():
    parser = argparse.ArgumentParser(
        description='Convert OMNeT++ .vec files to Parquet for Remote ID analysis'
    )
    parser.add_argument('vec_file', help='Input .vec file')
    parser.add_argument('-o', '--output', required=True, help='Output Parquet file')
    args = parser.parse_args()

    print(f"Exporting vectors from {args.vec_file}...", file=sys.stderr)
    tmp_csv = export_vectors_to_csv(args.vec_file)

    try:
        print(f"Parsing vectors...", file=sys.stderr)
        host_vectors = parse_csv_vectors(tmp_csv)

        print(f"Generating events...", file=sys.stderr)
        events = generate_events(host_vectors)

        print(f"Writing {len(events)} events to {args.output}...", file=sys.stderr)
        write_parquet(events, args.output)

        print(f"Done!", file=sys.stderr)
    finally:
        # Clean up temp file created by export_vectors_to_csv
        if os.path.exists(tmp_csv):
            os.remove(tmp_csv)


if __name__ == '__main__':
    main()
