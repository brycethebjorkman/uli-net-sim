#!/usr/bin/env python3
"""
run_scenario.py

Execute a single urbanenv scenario (simulation + parquet conversion).
Designed to be called by generate_dataset.py or directly.

Usage:
    python3 run_scenario.py <scenario_path> [spoofer_host]
"""

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJ_DIR = SCRIPT_DIR.parent
RUN_SH = PROJ_DIR / "scripts" / "run.sh"
VEC2PQ = SCRIPT_DIR / "vec2parquet.py"


def scenario_hash(scenario_path: Path) -> str:
    """Compute 8-char MD5 hash of the scenario's relative path structure."""
    scenario_name = scenario_path.name
    corridor_path = scenario_path.parent.parent  # past 'scenarios'
    corridor_dir = corridor_path.name
    param_dir = corridor_path.parent.name

    rel_path = f"{param_dir}/{corridor_dir}/scenarios/{scenario_name}"
    return hashlib.md5(rel_path.encode()).hexdigest()[:8]


def run_scenario(scenario_path: Path, spoofer_host: str | None = None,
                 venv_python: str | None = None) -> list[Path]:
    """Run simulation configs and convert results to parquet.

    Returns list of produced parquet file paths.
    """
    scenario_path = Path(scenario_path).resolve()
    scenario_name = scenario_path.name
    ini_file = scenario_path / "omnetpp.ini"
    results_dir = scenario_path / "results"

    if not ini_file.exists():
        raise FileNotFoundError(f"INI file not found: {ini_file}")

    # Determine configs to run
    ini_text = ini_file.read_text()
    configs = ["ScenarioOpenSpace"]
    if "ScenarioWithBuildings" in ini_text:
        configs.append("ScenarioWithBuildings")

    hash_prefix = scenario_hash(scenario_path)
    python = venv_python or sys.executable
    produced = []

    for config in configs:
        print(f"  [{scenario_name}] Running {config}...")

        results_dir.mkdir(parents=True, exist_ok=True)

        # Run simulation from scenario directory (relative paths in ini)
        result = subprocess.run(
            [str(RUN_SH), "-f", "omnetpp.ini", "-c", config,
             "-r", str(results_dir), "-q"],
            cwd=str(scenario_path),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  [{scenario_name}] Simulation failed: {result.stderr[-1000:]}")
            continue

        # Convert .vec to parquet
        vec_file = results_dir / f"{config}-#0.vec"
        if not vec_file.exists():
            print(f"  [{scenario_name}] Warning: Vector file not found: {vec_file}")
            continue

        suffix = "-o" if config == "ScenarioOpenSpace" else "-b"
        pq_file = scenario_path / f"{hash_prefix}{suffix}.parquet"

        print(f"  [{scenario_name}] Converting to Parquet...")
        cmd = [python, str(VEC2PQ), str(vec_file), "-o", str(pq_file)]
        if spoofer_host and spoofer_host != "-":
            cmd.extend(["--spoofer-hosts", spoofer_host])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  [{scenario_name}] Parquet conversion failed: {result.stderr[-1000:]}")
            continue

        print(f"  [{scenario_name}] Created: {pq_file.name}")
        produced.append(pq_file)

    # Clean up intermediate results
    if results_dir.exists():
        shutil.rmtree(results_dir)
        print(f"  [{scenario_name}] Cleaned up intermediate results")

    print(f"  [{scenario_name}] Complete")
    return produced


def main():
    if len(sys.argv) < 2:
        print("Usage: run_scenario.py <scenario_path> [spoofer_host]")
        sys.exit(1)

    scenario_path = Path(sys.argv[1])
    spoofer_host = sys.argv[2] if len(sys.argv) > 2 else None

    run_scenario(scenario_path, spoofer_host)


if __name__ == "__main__":
    main()
