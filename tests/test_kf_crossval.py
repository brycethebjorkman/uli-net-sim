"""
Cross-validation: online KfNisDetector vs offline KF scores.

Re-runs the eval pipeline's test scenarios with a GCS running
KfNisDetector, then verifies the online per-RX-event NIS values
match the offline kf_scores.parquet produced by the evaluation pipeline.

Both paths read from the same C++ KalmanFilterDetectMgmt KF:
- Offline: C++ KF NIS → .vec → vec2parquet.py → Parquet kf_nis column → kf_scores.parquet
- Online:  C++ KF NIS → GcsReport.kfNis → GcsModule → KfNisDetector → kf_nis_host{id}
"""

import json
import re
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from .conftest import TEST_OUT, REPO_ROOT, _run_quiet, extract_our_vectors

RUN_SH = REPO_ROOT / "scripts" / "run.sh"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_scenario_params(ini_path: Path) -> dict:
    with open(ini_path) as f:
        for line in f:
            if line.startswith("# Parameters: "):
                return json.loads(line[len("# Parameters: "):])
    return {}


def _get_num_hosts(ini_path: Path) -> int:
    with open(ini_path) as f:
        for line in f:
            m = re.match(r'\*\.numHosts\s*=\s*(\d+)', line)
            if m:
                return int(m.group(1))
    raise ValueError(f"numHosts not found in {ini_path}")


def _write_gcs_overlay_ini(base_ini: Path, base_config: str,
                           federate_ids: list[int],
                           output_ini: Path) -> str:
    """Write an overlay INI that extends a scenario config with GCS + KfNisDetector."""
    overlay_config = f"{base_config}WithGcs"
    federate_str = " ".join(str(i) for i in federate_ids)

    gcs_lines = [
        f'*.host[{fid}].wlan[0].mgmt.gcsModulePath = "^.^.^.gcs[0]"'
        for fid in federate_ids
    ]

    with open(output_ini, 'w') as f:
        f.write(f'include {base_ini.name}\n\n')
        f.write(f'[Config {overlay_config}]\n')
        f.write(f'extends = {base_config}\n')
        f.write(f'*.numGcs = 1\n')
        f.write(f'*.gcs[0].pyClass = "pymodules.detectors.kf_nis.KfNisDetector"\n')
        f.write(f'*.gcs[0].federateIndices = "{federate_str}"\n')
        for line in gcs_lines:
            f.write(line + '\n')

    return overlay_config


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def kf_crossval_outputs(datagen_outputs, sim_outputs, eval_outputs):
    """Re-run test scenarios with online KfNisDetector and collect GCS NIS vectors."""
    from datagen.vec2parquet import extract_vectors

    out = TEST_OUT / "kf_crossval"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    datagen_dir = datagen_outputs["dir"]
    test_dir = sim_outputs["test"]
    kf_scores = pd.read_parquet(eval_outputs["kf_scores.parquet"])

    results = []
    for csv_path in sorted(test_dir.glob("*.parquet")):
        csv_stem = csv_path.stem
        m = re.match(r'(scenario_seed\d+)_(Scenario\w+)', csv_stem)
        if not m:
            continue
        ini_stem, config = m.group(1), m.group(2)
        ini_path = datagen_dir / f"{ini_stem}.ini"
        if not ini_path.exists():
            continue

        params = _parse_scenario_params(ini_path)
        num_hosts = _get_num_hosts(ini_path)
        ghost = params.get("ghost_host")
        spoofer = params.get("spoofer_host")

        excluded = set()
        if ghost is not None:
            excluded.add(int(ghost))
        if spoofer is not None:
            excluded.add(int(spoofer))
        federate_ids = sorted(set(range(num_hosts)) - excluded)

        overlay_ini = datagen_dir / f"{ini_stem}_gcs_overlay.ini"
        overlay_config = _write_gcs_overlay_ini(
            ini_path, config, federate_ids, overlay_ini)

        result_dir = out / csv_stem / "results"
        result_dir.mkdir(parents=True)

        _run_quiet([str(RUN_SH), "-f", str(overlay_ini), "-c", overlay_config,
                    "-r", str(result_dir), "-q"], cwd=datagen_dir)

        vec_file = result_dir / f"{overlay_config}-#0.vec"
        vectors = extract_vectors(vec_file)

        gcs_nis = {}  # (host_id, serial_number) -> (times, values)
        for (mod, name), (times, vals) in vectors.items():
            if not mod.endswith("gcs[0]"):
                continue
            hm = re.match(r'kf_nis_host(\d+)_sn(\d+)', name)
            if hm:
                key = (int(hm.group(1)), int(hm.group(2)))
                gcs_nis[key] = (np.array(times), np.array(vals))

        offline_scores = kf_scores[kf_scores['scenario_id'] == csv_stem]

        results.append({
            "scenario_id": csv_stem,
            "gcs_nis": gcs_nis,
            "offline_scores": offline_scores,
            "federate_ids": federate_ids,
        })

    return results


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_kf_online_vs_offline_scores(kf_crossval_outputs):
    """Per-RX-event KF NIS from online KfNisDetector must match offline kf_scores.parquet.

    Matches by (host_id, serial_number) to avoid ordering ambiguity when
    multiple transmissions from different serials arrive at the same time.
    Within each (host, serial) group, values are in time order (one KF
    per serial per receiver), so positional comparison is valid.
    """
    total_matched = 0
    total_compared = 0
    max_diff = 0.0
    mismatches = []

    for run in kf_crossval_outputs:
        scenario_id = run["scenario_id"]
        gcs_nis = run["gcs_nis"]
        offline = run["offline_scores"]

        if offline.empty:
            continue

        for host_id in run["federate_ids"]:
            host_offline = offline[offline['host_id'] == host_id]
            if host_offline.empty:
                continue

            for sn in host_offline['serial_number'].unique():
                key = (host_id, int(sn))
                if key not in gcs_nis:
                    continue

                sn_offline = host_offline[host_offline['serial_number'] == sn].sort_values('rid_timestamp')
                gcs_times, gcs_vals = gcs_nis[key]
                offline_vals = sn_offline['kf_score'].values

                n = min(len(gcs_vals), len(offline_vals))
                for i in range(n):
                    total_compared += 1
                    diff = abs(gcs_vals[i] - offline_vals[i])
                    max_diff = max(max_diff, diff)
                    if diff < 1e-4:
                        total_matched += 1
                    else:
                        mismatches.append(
                            f"  {scenario_id} host{host_id} sn{sn}[{i}]: "
                            f"online={gcs_vals[i]:.6f} offline={offline_vals[i]:.6f} "
                            f"diff={diff:.6f}"
                        )

    assert total_compared > 0, "No online/offline KF NIS pairs to compare"
    if mismatches:
        sample = mismatches[:20]
        pytest.fail(
            f"{len(mismatches)}/{total_compared} KF NIS values differ "
            f"(max diff: {max_diff:.6f}):\n" + "\n".join(sample)
        )


def test_kf_crossval_coverage(kf_crossval_outputs):
    """Every test scenario should produce online NIS values for comparison."""
    for run in kf_crossval_outputs:
        scenario_id = run["scenario_id"]
        assert len(run["gcs_nis"]) > 0, f"No GCS NIS vectors for {scenario_id}"
        assert not run["offline_scores"].empty, f"No offline scores for {scenario_id}"
