#!/usr/bin/env python3
"""
run_scenario.py

Execute a single scenario directory or INI file (simulation + parquet conversion).
Designed to be called by run_batch.py or directly.

Usage:
    # Run all leaf configs in a scenario directory (auto-detect)
    python3 run_scenario.py <scenario_path>

    # Run specific configs
    python3 run_scenario.py <scenario_path> --configs ScenarioOpenSpace ScenarioWithBuildings

    # Keep .vec/.sca files after conversion
    python3 run_scenario.py <scenario_path> --keep-vec

    # Legacy: pass spoofer host explicitly (auto-detected from .vec by default)
    python3 run_scenario.py <scenario_path> --spoofer-host 2
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJ_DIR = SCRIPT_DIR.parent
RUN_SH = PROJ_DIR / "scripts" / "run.sh"
VEC2PQ = SCRIPT_DIR / "vec2parquet.py"

# vec2parquet events_to_parquet needs both (see vec2parquet.events_to_parquet)
_VEC2PQ_DEPS_CHECK = "import pyarrow, pandas"
_HEARTBEAT_SECONDS = 30.0


def _run_with_heartbeat(
    cmd: list[str],
    cwd: str,
    heartbeat_label: str,
    heartbeat_s: float = _HEARTBEAT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run command and emit periodic progress while it is still executing."""
    start = time.monotonic()
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=heartbeat_s)
            break
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            print(f"  [{heartbeat_label}] still running... {elapsed:.0f}s elapsed", flush=True)
    return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)


def pick_vec2parquet_python(proj_dir: Path | None = None) -> str:
    """Interpreter for vec2parquet: ULI_PYTHON, else usable .venv, else sys.executable.

    Skips broken .venv (wrong OS/arch — 'Exec format error' / 'cannot execute').
    """
    proj_dir = proj_dir or PROJ_DIR
    candidates: list[str] = []
    uli = os.environ.get("ULI_PYTHON", "").strip()
    if uli:
        candidates.append(uli)
    vpy = proj_dir / ".venv" / "bin" / "python3"
    if vpy.is_file():
        candidates.append(str(vpy))
    candidates.append(sys.executable)
    seen: set[str] = set()
    for exe in candidates:
        if exe in seen:
            continue
        seen.add(exe)
        try:
            r = subprocess.run(
                [exe, "-c", _VEC2PQ_DEPS_CHECK],
                capture_output=True,
                timeout=60,
            )
            if r.returncode == 0:
                return exe
        except OSError:
            continue
    raise RuntimeError(
        "No Python interpreter has pyarrow + pandas (required for datagen/vec2parquet). "
        "On the host:  python3 -m pip install pandas pyarrow\n"
        "In Docker:     ./scripts/docker-run.sh python3 datagen/run_batch.py …"
    )


def scenario_hash(scenario_path: Path) -> str:
    """Compute 8-char MD5 hash of the scenario path.

    For urbanenv scenarios (…/param/corridor/scenarios/name/) uses the
    canonical relative structure.  For other layouts, hashes the directory
    name directly.
    """
    scenario_name = scenario_path.name
    if scenario_path.parent.name == "scenarios":
        # Urbanenv layout: param_dir/corridor_dir/scenarios/scenario_name
        corridor_path = scenario_path.parent.parent
        corridor_dir = corridor_path.name
        param_dir = corridor_path.parent.name
        rel_path = f"{param_dir}/{corridor_dir}/scenarios/{scenario_name}"
    else:
        rel_path = scenario_name
    return hashlib.md5(rel_path.encode()).hexdigest()[:8]


def find_leaf_configs(ini_path: Path) -> list[str]:
    """Find runnable (leaf) configs in an INI file.

    A leaf config is one that is never extended by another config.
    The [General] section is excluded.
    """
    ini_text = ini_path.read_text()
    all_configs: list[str] = []
    base_configs: set[str] = set()

    for line in ini_text.splitlines():
        m = re.match(r'^\[Config\s+(\S+)\]', line)
        if m:
            all_configs.append(m.group(1))
            continue
        m = re.match(r'^extends\s*=\s*(.+)', line)
        if m:
            for base in m.group(1).split(','):
                base_configs.add(base.strip())

    leaves = [c for c in all_configs if c not in base_configs]
    return leaves


# Short suffixes for well-known urbanenv config names (preserves existing
# dataset filename convention expected by manifest/regeneration tools).
_CONFIG_SUFFIX_MAP = {
    'ScenarioOpenSpace': '-o',
    'ScenarioWithBuildings': '-b',
}


def _config_suffix(config_name: str) -> str:
    """Return the parquet filename suffix for a config name."""
    return _CONFIG_SUFFIX_MAP.get(config_name, f'-{config_name}')


def run_scenario(scenario_path: Path, spoofer_host: str | None = None,
                 venv_python: str | None = None,
                 configs: list[str] | None = None,
                 keep_vec: bool = False) -> list[Path]:
    """Run simulation configs and convert results to parquet.

    Args:
        scenario_path: Directory containing omnetpp.ini
        spoofer_host: Explicit spoofer host index (auto-detected from .vec if None)
        venv_python: Python interpreter for vec2parquet (default: sys.executable)
        configs: Config names to run (default: auto-detect leaf configs)
        keep_vec: Keep .vec/.sca files after parquet conversion

    Returns list of produced parquet file paths.
    """
    scenario_path = Path(scenario_path).resolve()
    scenario_name = scenario_path.name
    ini_file = scenario_path / "omnetpp.ini"
    results_dir = scenario_path / "results"

    if not ini_file.exists():
        raise FileNotFoundError(f"INI file not found: {ini_file}")

    if configs is None:
        configs = find_leaf_configs(ini_file)
        if not configs:
            print(f"  [{scenario_name}] No leaf configs found in {ini_file}")
            return []

    hash_prefix = scenario_hash(scenario_path)
    python = venv_python if venv_python else pick_vec2parquet_python(PROJ_DIR)
    produced = []

    for config in configs:
        suffix = _config_suffix(config)
        pq_file = scenario_path / f"{hash_prefix}{suffix}.parquet"

        if pq_file.exists():
            produced.append(pq_file)
            continue

        print(f"  [{scenario_name}] Running {config}...")

        results_dir.mkdir(parents=True, exist_ok=True)

        # Run simulation from scenario directory (relative paths in ini)
        result = _run_with_heartbeat(
            [str(RUN_SH), "-f", str(ini_file), "-c", config,
             "-r", str(results_dir), "-q"],
            cwd=str(scenario_path),
            heartbeat_label=f"{scenario_name}:{config}:sim",
        )
        if result.returncode != 0:
            err_tail = (result.stderr or "").strip()[-1000:]
            out_tail = (result.stdout or "").strip()[-1000:]
            print(
                f"  [{scenario_name}] Simulation failed (exit={result.returncode}).\n"
                f"    stderr: {err_tail if err_tail else '<empty>'}\n"
                f"    stdout: {out_tail if out_tail else '<empty>'}"
            )
            continue

        # Preserve OMNeT++ scalars (.sca) for analysis regardless of parquet status.
        sca_file = results_dir / f"{config}-#0.sca"
        if sca_file.is_file():
            sca_dest = scenario_path / f"{hash_prefix}{suffix}.sca"
            shutil.copy2(sca_file, sca_dest)
            print(f"  [{scenario_name}] Copied scalars: {sca_dest.name}")

        # Convert .vec to parquet
        vec_file = results_dir / f"{config}-#0.vec"
        if not vec_file.exists():
            print(f"  [{scenario_name}] Warning: Vector file not found: {vec_file}")
            continue

        print(f"  [{scenario_name}] Converting to Parquet...")
        cmd = [python, str(VEC2PQ), str(vec_file), "-o", str(pq_file)]
        if spoofer_host and spoofer_host != "-":
            cmd.extend(["--spoofer-hosts", spoofer_host])

        result = _run_with_heartbeat(
            cmd,
            cwd=str(scenario_path),
            heartbeat_label=f"{scenario_name}:{config}:parquet",
        )
        if result.returncode != 0:
            print(f"  [{scenario_name}] Parquet conversion failed: {result.stderr[-1000:]}")
            continue

        print(f"  [{scenario_name}] Created: {pq_file.name}")
        produced.append(pq_file)

    # Clean up intermediate results (unless keep_vec)
    if not keep_vec and results_dir.exists():
        shutil.rmtree(results_dir)
        print(f"  [{scenario_name}] Cleaned up intermediate results")

    print(f"  [{scenario_name}] Complete")
    return produced


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Run a single scenario (simulation + parquet conversion)")
    parser.add_argument("scenario_path", type=Path,
                        help="Directory containing omnetpp.ini")
    parser.add_argument("--spoofer-host", default=None,
                        help="Spoofer host index (auto-detected from .vec if omitted)")
    parser.add_argument("--configs", nargs="+", default=None,
                        help="Config names to run (default: auto-detect leaf configs)")
    parser.add_argument("--keep-vec", action="store_true",
                        help="Keep .vec/.sca files after parquet conversion")
    args = parser.parse_args()

    run_scenario(args.scenario_path, args.spoofer_host,
                 configs=args.configs, keep_vec=args.keep_vec)


if __name__ == "__main__":
    main()
