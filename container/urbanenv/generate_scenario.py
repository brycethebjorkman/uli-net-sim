#!/usr/bin/env python3
"""
Generate OMNeT++ scenario configuration files for urban environment simulations.

Creates an omnetpp.ini configuration that extends the base UrbanEnvBase config
with trajectory files, optional buildings, and configurable radio parameters.
"""

import argparse
import json
import random
import sys
from pathlib import Path


def parse_range(value: str) -> tuple[float, float]:
    """Parse a range string like '10-16' or a single value like '10'."""
    if '-' in value:
        parts = value.split('-')
        if len(parts) != 2:
            raise ValueError(f"Invalid range format: {value}")
        return float(parts[0]), float(parts[1])
    else:
        v = float(value)
        return v, v


def sample_value(min_val: float, max_val: float) -> float:
    """Sample a value from a range using the current random state."""
    if min_val == max_val:
        return min_val
    return random.uniform(min_val, max_val)


def count_hosts_in_waypoints(waypoints_path: Path) -> int:
    """Count the number of movement entries in a waypoints XML file."""
    import xml.etree.ElementTree as ET
    tree = ET.parse(waypoints_path)
    root = tree.getroot()
    movements = root.findall('movement')
    return len(movements)


def main():
    parser = argparse.ArgumentParser(
        description="Generate OMNeT++ scenario configuration for urban environments",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic scenario without buildings
  %(prog)s -t waypoints.xml -o scenario.ini

  # Scenario with buildings
  %(prog)s -t waypoints.xml -b buildings.xml -o scenario.ini

  # Custom radio parameters
  %(prog)s -t waypoints.xml --tx-power 10-16 --beacon-interval 0.25-0.75 -o scenario.ini

  # Scenario with spoofer (randomly selected ghost and spoofer)
  %(prog)s -t waypoints.xml -b buildings.xml --enable-spoofer --seed 42 -o scenario.ini

  # Scenario with specific spoofer hosts
  %(prog)s -t waypoints.xml -b buildings.xml --ghost-host 4 --spoofer-host 5 -o scenario.ini
"""
    )

    parser.add_argument('-t', '--trajectories', required=True,
                        help='Path to waypoints XML file')
    parser.add_argument('-b', '--buildings', default=None,
                        help='Path to buildings XML file (optional)')
    parser.add_argument('--tx-power', default='10-16',
                        help='Transmission power range in dBm (default: 10-16)')
    parser.add_argument('--beacon-interval', default='0.25-0.75',
                        help='Beacon interval range in seconds (default: 0.25-0.75)')
    parser.add_argument('--beacon-offset', default='0-0',
                        help='Beacon offset range in seconds (default: 0, no offset)')
    parser.add_argument('--background-noise', type=float, default=-90,
                        help='Background noise power in dBm (default: -90, realistic urban)')
    parser.add_argument('--sim-time-limit', type=float, default=300,
                        help='Simulation time limit in seconds (default: 300)')
    parser.add_argument('--ghost-host', type=int, default=None,
                        help='Host index to use as ghost (silent drone)')
    parser.add_argument('--spoofer-host', type=int, default=None,
                        help='Host index to use as spoofer (claims ghost position)')
    parser.add_argument('--enable-spoofer', action='store_true',
                        help='Randomly select ghost and spoofer hosts (requires >= 2 hosts)')
    parser.add_argument('--config-name', default=None,
                        help='Config name (default: derived from output filename)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed for reproducibility')
    parser.add_argument('-o', '--output', required=True,
                        help='Output .ini file path')

    args = parser.parse_args()

    # Validate spoofer/ghost options
    if args.enable_spoofer and (args.ghost_host is not None or args.spoofer_host is not None):
        parser.error("--enable-spoofer cannot be used with --ghost-host or --spoofer-host")

    if (args.ghost_host is None) != (args.spoofer_host is None):
        parser.error("--ghost-host and --spoofer-host must be used together")

    if args.ghost_host is not None and args.ghost_host == args.spoofer_host:
        parser.error("--ghost-host and --spoofer-host must be different hosts")

    # Set seed if provided (before any random operations)
    if args.seed is not None:
        random.seed(args.seed)

    # Parse paths
    trajectories_path = Path(args.trajectories)
    output_path = Path(args.output)

    if not trajectories_path.exists():
        print(f"Error: Trajectories file not found: {trajectories_path}", file=sys.stderr)
        sys.exit(1)

    if args.buildings and not Path(args.buildings).exists():
        print(f"Error: Buildings file not found: {args.buildings}", file=sys.stderr)
        sys.exit(1)

    # Count hosts from waypoints file
    num_hosts = count_hosts_in_waypoints(trajectories_path)
    print(f"Found {num_hosts} hosts in waypoints file")

    # Handle --enable-spoofer: randomly select ghost and spoofer
    ghost_host = args.ghost_host
    spoofer_host = args.spoofer_host

    if args.enable_spoofer:
        if num_hosts < 2:
            print(f"Error: --enable-spoofer requires at least 2 hosts, found {num_hosts}", file=sys.stderr)
            sys.exit(1)
        # Randomly select two different hosts
        selected = random.sample(range(num_hosts), 2)
        ghost_host = selected[0]
        spoofer_host = selected[1]
        print(f"Randomly selected: ghost={ghost_host}, spoofer={spoofer_host}")

    # Validate host indices (only for explicit --ghost-host/--spoofer-host, not --enable-spoofer)
    if ghost_host is not None and not args.enable_spoofer:
        if ghost_host < 0 or ghost_host >= num_hosts:
            print(f"Error: ghost-host index {ghost_host} out of range [0, {num_hosts-1}]", file=sys.stderr)
            sys.exit(1)
        if spoofer_host < 0 or spoofer_host >= num_hosts:
            print(f"Error: spoofer-host index {spoofer_host} out of range [0, {num_hosts-1}]", file=sys.stderr)
            sys.exit(1)

    # Parse ranges
    tx_power_min, tx_power_max = parse_range(args.tx_power)
    beacon_interval_min, beacon_interval_max = parse_range(args.beacon_interval)
    beacon_offset_min, beacon_offset_max = parse_range(args.beacon_offset)

    # Derive config name from output filename if not provided
    config_name = args.config_name
    if config_name is None:
        config_name = output_path.stem
        # Clean up the name to be a valid identifier
        config_name = ''.join(c if c.isalnum() or c == '_' else '_' for c in config_name)
        if config_name[0].isdigit():
            config_name = 'Config_' + config_name

    # Determine relative paths for ini file
    # The ini file will use paths relative to its own location
    output_dir = output_path.parent.resolve()

    # Calculate relative path from output directory to trajectories
    try:
        traj_abs = trajectories_path.resolve()
        traj_rel = traj_abs.relative_to(output_dir)
    except ValueError:
        # If trajectories is not under output_dir, use relative path from output_dir
        import os
        traj_rel = Path(os.path.relpath(trajectories_path.resolve(), output_dir))

    buildings_rel = None
    if args.buildings:
        buildings_path = Path(args.buildings)
        try:
            buildings_abs = buildings_path.resolve()
            buildings_rel = buildings_abs.relative_to(output_dir)
        except ValueError:
            import os
            buildings_rel = Path(os.path.relpath(buildings_path.resolve(), output_dir))

    # Build generation parameters for embedding
    gen_params = {
        "_generator": "generate_scenario.py",
        "_params": {
            "trajectories": str(trajectories_path),
            "buildings": args.buildings,
            "tx_power": args.tx_power,
            "beacon_interval": args.beacon_interval,
            "beacon_offset": args.beacon_offset,
            "background_noise": args.background_noise,
            "sim_time_limit": args.sim_time_limit,
            "ghost_host": ghost_host,
            "spoofer_host": spoofer_host,
            "config_name": config_name,
            "seed": args.seed,
        }
    }

    # Generate the ini file content
    lines = []
    lines.append(f"# Generated by: {gen_params['_generator']}")
    lines.append(f"# Parameters: {json.dumps(gen_params['_params'])}")
    lines.append(f"#")
    lines.append(f"# Trajectories: {trajectories_path}")
    if args.buildings:
        lines.append(f"# Buildings: {args.buildings}")
    lines.append(f"#")
    lines.append(f"# Available configs:")
    lines.append(f"#   - ScenarioOpenSpace: No buildings (open sky)")
    if args.buildings:
        lines.append(f"#   - ScenarioWithBuildings: With buildings (extends ScenarioOpenSpace)")
    lines.append("")

    # Embed the base configuration directly (IDE doesn't support include)
    # Read from simulations/urbanenv/omnetpp.ini relative to this script
    base_ini_path = Path(__file__).parent.parent.parent / "simulations" / "urbanenv" / "omnetpp.ini"
    with open(base_ini_path, 'r') as f:
        base_content = f.read().rstrip()
    lines.append(base_content)
    lines.append("")
    lines.append("")

    # Sample per-host parameters deterministically based on seed
    # This ensures each run of the same config produces identical results
    host_params = []
    for i in range(num_hosts):
        tx_power = sample_value(tx_power_min, tx_power_max)
        beacon_interval = sample_value(beacon_interval_min, beacon_interval_max)
        beacon_offset = sample_value(beacon_offset_min, beacon_offset_max)
        host_params.append({
            'tx_power': tx_power,
            'beacon_interval': beacon_interval,
            'beacon_offset': beacon_offset,
        })

    # ===========================================================================
    # ScenarioOpenSpace - base config without buildings
    # ===========================================================================
    lines.append("# ==============================================================================")
    lines.append("# ScenarioOpenSpace - No buildings (open sky)")
    lines.append("# ==============================================================================")
    lines.append("[Config ScenarioOpenSpace]")
    lines.append("extends = UrbanEnvBase")

    # Description
    desc_parts = [f"{num_hosts} hosts", "open space"]
    if ghost_host is not None:
        desc_parts.append(f"ghost[{ghost_host}]+spoofer[{spoofer_host}]")
    lines.append(f'description = "{", ".join(desc_parts)}"')
    lines.append("")

    # Basic parameters
    lines.append(f"sim-time-limit = {int(args.sim_time_limit)}s")
    lines.append(f"*.numHosts = {num_hosts}")
    lines.append(f"*.radioMedium.backgroundNoise.power = {args.background_noise}dBm")
    lines.append("")

    # No buildings - empty physical environment
    lines.append('*.physicalEnvironment.config = xml("<environment/>")')
    lines.append("")

    # Host types and configurations
    if ghost_host is not None:
        lines.append(f"# Ghost host (silent, no RF)")
        lines.append(f'*.host[{ghost_host}].typename = "GhostHost"')
        lines.append("")
        lines.append(f"# Spoofer host (claims ghost's position)")
        lines.append(f'*.host[{spoofer_host}].typename = "DynamicTrajectorySpooferHost"')
        lines.append(f"*.host[{spoofer_host}].wlan[0].mgmt.targetHostIndex = {ghost_host}")
        lines.append("")

    # Per-host radio and beacon parameters
    lines.append("# Per-host parameters (sampled deterministically from seed)")
    for i in range(num_hosts):
        # Skip radio params for ghost host (no wlan)
        if ghost_host is not None and i == ghost_host:
            continue
        params = host_params[i]
        lines.append(f"*.host[{i}].wlan[0].radio.transmitter.power = {params['tx_power']:.6f}dBm")
        lines.append(f"*.host[{i}].wlan[0].mgmt.beaconInterval = {params['beacon_interval']:.6f}s")
        if beacon_offset_min != 0 or beacon_offset_max != 0:
            lines.append(f"*.host[{i}].wlan[0].mgmt.beaconOffset = {params['beacon_offset']:.6f}s")
    lines.append("")

    # Trajectories for each host
    lines.append("# Trajectories")
    for i in range(num_hosts):
        lines.append(f'*.host[{i}].mobility.turtleScript = xmldoc("{traj_rel}", "movements/movement[@id=\'{i}\']")')
    lines.append("")

    # ===========================================================================
    # ScenarioWithBuildings - extends ScenarioOpenSpace with buildings
    # ===========================================================================
    if args.buildings:
        lines.append("")
        lines.append("# ==============================================================================")
        lines.append("# ScenarioWithBuildings - With buildings (extends ScenarioOpenSpace)")
        lines.append("# ==============================================================================")
        lines.append("[Config ScenarioWithBuildings]")
        lines.append("extends = ScenarioOpenSpace")
        desc_parts = [f"{num_hosts} hosts", "with buildings"]
        if ghost_host is not None:
            desc_parts.append(f"ghost[{ghost_host}]+spoofer[{spoofer_host}]")
        lines.append(f'description = "{", ".join(desc_parts)}"')
        lines.append("")
        lines.append(f'*.physicalEnvironment.config = xmldoc("{buildings_rel}")')
        lines.append("")

    # Write the output file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w') as f:
        f.write('\n'.join(lines))

    print(f"Generated scenario: {output_path}")
    print(f"  Configs: ScenarioOpenSpace" + (", ScenarioWithBuildings" if args.buildings else ""))
    print(f"  Hosts: {num_hosts}")
    print(f"  TX Power: {tx_power_min}-{tx_power_max} dBm (per-host sampled)")
    print(f"  Beacon Interval: {beacon_interval_min}-{beacon_interval_max}s (per-host sampled)")
    if beacon_offset_min != 0 or beacon_offset_max != 0:
        print(f"  Beacon Offset: {beacon_offset_min}-{beacon_offset_max}s (per-host sampled)")
    if ghost_host is not None:
        print(f"  Ghost: host[{ghost_host}], Spoofer: host[{spoofer_host}]")

    # Output machine-readable metadata for downstream tools
    # Format: SPOOFER_HOST=N (only if spoofer is configured)
    if spoofer_host is not None:
        print(f"SPOOFER_HOST={spoofer_host}")


if __name__ == '__main__':
    main()
