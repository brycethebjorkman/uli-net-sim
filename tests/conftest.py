"""
Regression test fixtures for the datagen → simulation → evaluation pipeline.

Mirrors the scitech26 production pipeline. Session-scoped fixtures ensure
each stage runs once and feeds into the next.
"""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from datagen.vec2parquet import extract_vectors, hash_vector_data

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).parent.parent
TEST_OUT = Path(__file__).parent / "out"

RUN_SH = REPO_ROOT / "scripts" / "run.sh"
URBANENV = REPO_ROOT / "datagen" / "urbanenv"
VEC2CSV = REPO_ROOT / "datagen" / "vec2parquet.py"
ADD_HOST_TYPE = REPO_ROOT / "datagen" / "add_host_type.py"
PYTHON = sys.executable

# Datagen parameters
DATAGEN_PARAMS = dict(
    corridors=["--num-ew", "3", "--num-ns", "3",
               "--width", "20", "--spacing", "100",
               "--grid-size", "400", "--seed", "1"],
    buildings=["-n", "10", "--height", "50-150",
               "--seed", "1", "--format", "xml"],
    trajectories=["--hosts", "8", "--speed", "5-15",
                  "--altitude", "30-100", "--min-duration", "120",
                  "--seed", "1"],
    scenario=["--tx-power", "10-16", "--beacon-interval", "0.25-0.75",
              "--sim-time-limit", "50", "--enable-spoofer"],
)

NUM_SCENARIO_VARIANTS = 4   # 4 INIs × 2 configs = 8 CSVs
TRAIN_COUNT = 6
EVAL_SEED = 42


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_dir(path: Path) -> Path:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def _run(args, cwd):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, cwd=str(cwd))
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(str(a) for a in args)}\n"
                           f"stdout: {r.stdout[-2000:]}\nstderr: {r.stderr[-2000:]}")


def _run_quiet(args, cwd):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, cwd=str(cwd))
    if r.returncode != 0:
        raise RuntimeError(f"Command failed (exit {r.returncode}): "
                           f"{' '.join(str(a) for a in args)}\nstderr: {r.stderr[-2000:]}")


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_our_vectors(vec_path: Path) -> dict:
    """Extract our module vectors from a .vec file using default specs."""
    return extract_vectors(vec_path)


def diff_vector_hashes(expected: dict, actual: dict) -> str:
    """Compare per-label hash dicts and return a human-readable diff."""
    lines = []
    changed = []
    added = sorted(set(actual) - set(expected))
    removed = sorted(set(expected) - set(actual))
    unchanged = 0

    for label in sorted(set(expected) & set(actual)):
        if expected[label] != actual[label]:
            changed.append(label)
        else:
            unchanged += 1

    if changed:
        lines.append(f"  CHANGED ({len(changed)}):")
        for label in changed:
            lines.append(f"    {label}: expected {expected[label][:16]}... got {actual[label][:16]}...")
    if added:
        lines.append(f"  ADDED ({len(added)}):")
        for label in added:
            lines.append(f"    {label}")
    if removed:
        lines.append(f"  REMOVED ({len(removed)}):")
        for label in removed:
            lines.append(f"    {label}")
    lines.append(f"  UNCHANGED: {unchanged}")
    return "\n".join(lines)


def _extract_spoofer_host(ini_path: Path) -> str | None:
    with open(ini_path) as f:
        for line in f:
            if line.startswith("# Parameters: "):
                params = json.loads(line[len("# Parameters: "):])
                host = params.get("spoofer_host")
                return str(host) if host is not None else None
    return None


# ---------------------------------------------------------------------------
# Fixtures: datagen → simulation → evaluation
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def datagen_outputs():
    """Generate corridors, buildings, trajectories, and scenario INIs."""
    out = _clean_dir(TEST_OUT / "datagen")

    _run([PYTHON, URBANENV / "generate_corridors.py",
          *DATAGEN_PARAMS["corridors"], "-o", "corridors.ndjson"], cwd=out)

    _run([PYTHON, URBANENV / "generate_buildings.py",
          "-c", "corridors.ndjson", *DATAGEN_PARAMS["buildings"],
          "-o", "buildings.xml"], cwd=out)

    _run([PYTHON, URBANENV / "generate_trajectories.py",
          "-c", "corridors.ndjson", *DATAGEN_PARAMS["trajectories"],
          "-o", "trajectories.xml"], cwd=out)

    scenario_inis = {}
    for i in range(NUM_SCENARIO_VARIANTS):
        seed = str(i + 1)
        name = f"scenario_seed{seed}.ini"
        _run([PYTHON, URBANENV / "generate_scenario.py",
              "-t", "trajectories.xml", "-b", "buildings.xml",
              *DATAGEN_PARAMS["scenario"], "--seed", seed, "-o", name], cwd=out)
        scenario_inis[name] = out / name

    return {"corridors.ndjson": out / "corridors.ndjson",
            "buildings.xml": out / "buildings.xml",
            "trajectories.xml": out / "trajectories.xml",
            "scenario_inis": scenario_inis,
            "dir": out}


@pytest.fixture(scope="session")
def sim_outputs(datagen_outputs):
    """Run OMNeT++ on each scenario INI, produce CSVs, split train/test."""
    out = _clean_dir(TEST_OUT / "sim")
    datagen_dir = datagen_outputs["dir"]

    all_pqs = []
    first_vec = first_raw_pq = None

    for ini_name in sorted(datagen_outputs["scenario_inis"]):
        ini_path = datagen_outputs["scenario_inis"][ini_name]
        spoofer_host = _extract_spoofer_host(ini_path)
        stem = ini_path.stem

        configs = ["ScenarioOpenSpace"]
        if "ScenarioWithBuildings" in ini_path.read_text():
            configs.append("ScenarioWithBuildings")

        for config in configs:
            run_name = f"{stem}_{config}"
            result_dir = out / run_name / "results"
            result_dir.mkdir(parents=True)

            _run_quiet([str(RUN_SH), "-f", ini_name, "-c", config,
                        "-r", str(result_dir), "-q"], cwd=datagen_dir)

            vec_file = result_dir / f"{config}-#0.vec"
            raw_pq = out / run_name / "raw.parquet"
            _run([PYTHON, str(VEC2CSV), str(vec_file), "-o", str(raw_pq)], cwd=out)

            if first_vec is None:
                first_vec = vec_file
                first_raw_pq = raw_pq

            final_pq = out / f"{run_name}.parquet"
            shutil.copy(raw_pq, final_pq)
            add_args = [PYTHON, str(ADD_HOST_TYPE), str(final_pq), "--in-place"]
            if spoofer_host is not None:
                add_args.extend(["--spoofer-hosts", spoofer_host])
            _run(add_args, cwd=out)
            all_pqs.append(final_pq)

    # Deterministic train/test split
    sorted_pqs = sorted(all_pqs, key=lambda p: p.name)
    train_dir, test_dir = out / "train", out / "test"
    train_dir.mkdir()
    test_dir.mkdir()
    for i, pq in enumerate(sorted_pqs):
        dest = train_dir if i < TRAIN_COUNT else test_dir
        shutil.copy(pq, dest / pq.name)

    return {"scenario.vec": first_vec, "raw.parquet": first_raw_pq,
            "train": train_dir, "test": test_dir}


@pytest.fixture(scope="session")
def eval_outputs(sim_outputs):
    """Run train → score → analyze on simulation CSVs."""
    from evaluations.scoring import train_detectors, score_test_set
    from evaluations.analysis import analyze_scores

    train_out = _clean_dir(TEST_OUT / "train")
    score_out = _clean_dir(TEST_OUT / "score")

    train_detectors(sim_outputs["train"], train_out, seed=EVAL_SEED)

    shutil.copy(train_out / "mlp_weights.pth", score_out / "mlp_weights.pth")
    shutil.copy(train_out / "mlp_scaler.pkl", score_out / "mlp_scaler.pkl")

    with open(train_out / "thresholds.json") as f:
        thresholds = json.load(f)

    score_test_set(test_dir=sim_outputs["test"], output_dir=score_out,
                   kf_threshold=thresholds["kf_threshold"],
                   mlat_threshold=thresholds["mlat_threshold"], seed=EVAL_SEED)

    analyze_scores(scores_dir=score_out, output_dir=score_out)

    return {"thresholds.json": train_out / "thresholds.json",
            "kf_scores.parquet": score_out / "kf_scores.parquet",
            "mlat_scores.parquet": score_out / "mlat_scores.parquet",
            "mlp_scores.parquet": score_out / "mlp_scores.parquet",
            "unified_results.json": score_out / "unified_results.json"}
