#!/usr/bin/env python3
"""
Containment-only tuner for SpoofingAware InstantDetect@5s on depot scenarios.

This script searches IMM parameter combinations and optimizes:
  mean(spoofer_containment_rate_final)

It runs ONLY SpoofingAware configs with FORCE_DETECT_AT_S fixed to 5 seconds.
TrustRID / baseline Aware are not executed.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import random
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_SCENARIOS = [
    "Scenario_DepotCity_4x1",
    "Scenario_DepotCity_8x1",
    "Scenario_DepotCity_12x1",
    "Scenario_DepotCity_16x1",
]
TUNE_CONFIG_NAME = "TuneInstantDetect"

# Tuned parameter space (all env vars are already consumed by spoofing_aware_gcs.py).
PARAM_GRID = {
    "ULI_IMM_INIT_MODE_CV": [0.25, 0.45, 0.65],
    "ULI_IMM_P_CV_STAY": [0.95, 0.98, 0.995],
    "ULI_IMM_P_CA_STAY": [0.75, 0.84, 0.92],
    "ULI_IMM_CV_POS_NOISE": [1.0, 2.0, 4.0],
    "ULI_IMM_CV_VEL_NOISE": [60.0, 120.0, 200.0],
    "ULI_IMM_CV_MEAS_NOISE": [200.0, 400.0, 800.0],
    "ULI_IMM_CA_POS_NOISE": [2.0, 4.0, 8.0],
    "ULI_IMM_CA_VEL_NOISE": [25.0, 50.0, 80.0],
    "ULI_IMM_CA_ACC_NOISE": [10.0, 20.0, 40.0],
    "ULI_IMM_CA_MEAS_NOISE": [25.0, 50.0, 100.0],
}


@dataclass
class TrialResult:
    trial_id: int
    split: str
    score: float
    n_runs: int
    ok: bool
    params: dict[str, float]
    output_dir: Path
    log_path: Path


def _parse_seeds(spec: str) -> list[int]:
    spec = str(spec).strip()
    if ":" in spec:
        a, b = spec.split(":", 1)
        start = int(a)
        end = int(b)
        if start > end:
            raise ValueError(f"Invalid seed range: {spec}")
        return list(range(start, end + 1))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(int(part))
    if not out:
        raise ValueError(f"No seeds parsed from: {spec}")
    return out


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _scenario_slug(name: str) -> str:
    return re.sub(r"^Scenario_", "", name).lower()


def _write_trial_ini(
    base_ini_text: str,
    ini_out: Path,
    scenario: str,
    seed: int,
    cfg_name: str,
    goal_overrides: str = "",
) -> None:
    # Keep scenario geometry untouched (no goal reassignment) for parity with base depot configs.
    append = f"""

[Config {cfg_name}]
extends = {scenario}
seed-set = {seed}
*.gcs[0].pyClass = "pymodules.planners.spoofing_aware_gcs.SpoofingAwareGcs"
{goal_overrides}
"""
    ini_out.write_text(base_ini_text + append, encoding="utf-8")


def _scenario_block(full_text: str, cfg_name: str) -> str:
    start_re = re.compile(rf"^\[Config {re.escape(cfg_name)}\]\s*$", re.MULTILINE)
    start_m = start_re.search(full_text)
    if not start_m:
        raise ValueError(f"Scenario block not found: {cfg_name}")
    tail = full_text[start_m.end() :]
    next_cfg_m = re.search(r"^\[Config .+\]\s*$", tail, re.MULTILINE)
    if next_cfg_m:
        return tail[: next_cfg_m.start()]
    return tail


def _parse_xyz(tag: str, xml: str) -> tuple[float, float, float]:
    m = re.search(
        rf"<{tag}\s+[^>]*x='([^']+)'\s+[^>]*y='([^']+)'\s+[^>]*z='([^']+)'",
        xml,
    )
    if not m:
        raise ValueError(f"Could not parse <{tag}> xyz from waypointScript: {xml}")
    return (float(m.group(1)), float(m.group(2)), float(m.group(3)))


def _parse_speed(xml: str) -> float:
    m = re.search(r"<set\s+[^>]*speed='([^']+)'", xml)
    if not m:
        raise ValueError(f"Could not parse <set> speed from waypointScript: {xml}")
    return float(m.group(1))


def _format_movement(
    host_id: int,
    start: tuple[float, float, float],
    goal: tuple[float, float, float],
    speed: float,
) -> str:
    sx, sy, sz = start
    gx, gy, gz = goal
    return (
        f"<movement id='{host_id}'><set x='{sx:.6g}' y='{sy:.6g}' z='{sz:.6g}' speed='{speed:.6g}'/>"
        f"<moveto x='{gx:.6g}' y='{gy:.6g}' z='{gz:.6g}'/></movement>"
    )


def _dist_point_to_segment_xy(
    p: tuple[float, float],
    a: tuple[float, float],
    b: tuple[float, float],
) -> float:
    px, py = p
    ax, ay = a
    bx, by = b
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    den = abx * abx + aby * aby
    if den <= 1e-9:
        dx = px - ax
        dy = py - ay
        return (dx * dx + dy * dy) ** 0.5
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / den))
    qx = ax + t * abx
    qy = ay + t * aby
    dx = px - qx
    dy = py - qy
    return (dx * dx + dy * dy) ** 0.5


def _choose_constrained_derangement(
    host_ids: list[int],
    starts: dict[int, tuple[float, float, float]],
    goals: dict[int, tuple[float, float, float]],
    rng: random.Random,
    hotspot_xy: tuple[float, float] | None,
) -> list[int]:
    min_trip_xy = 320.0
    max_trip_xy = 980.0
    corridor_dist_thresh = 260.0
    relax_thresh = 340.0

    def _feasible(hid: int, gid: int, dist_thresh: float) -> bool:
        if hid == gid:
            return False
        s = starts[hid]
        g = goals[gid]
        dx = g[0] - s[0]
        dy = g[1] - s[1]
        dxy = (dx * dx + dy * dy) ** 0.5
        if dxy < min_trip_xy or dxy > max_trip_xy:
            return False
        if hotspot_xy is None:
            return True
        seg_dist = _dist_point_to_segment_xy(hotspot_xy, (s[0], s[1]), (g[0], g[1]))
        return seg_dist <= dist_thresh

    def _search(dist_thresh: float, attempts: int) -> list[int] | None:
        for _ in range(attempts):
            perm = host_ids[:]
            rng.shuffle(perm)
            if all(_feasible(h, g, dist_thresh) for h, g in zip(host_ids, perm)):
                return perm
        return None

    perm = _search(corridor_dist_thresh, attempts=768)
    if perm is not None:
        return perm
    perm = _search(relax_thresh, attempts=768)
    if perm is not None:
        return perm
    for _ in range(256):
        perm = host_ids[:]
        rng.shuffle(perm)
        if all(h != g for h, g in zip(host_ids, perm)):
            return perm
    return host_ids[1:] + host_ids[:1]


def _seeded_goal_overrides(
    *,
    full_text: str,
    scenario_cfg_name: str,
    benign_count: int,
    seed_value: int,
) -> str:
    block = _scenario_block(full_text, scenario_cfg_name)
    wp_re = re.compile(
        r"\*\.host\[(\d+)\]\.mobility\.waypointScript\s*=\s+xml\(\"([^\"]+)\"\)"
    )
    starts: dict[int, tuple[float, float, float]] = {}
    goals: dict[int, tuple[float, float, float]] = {}
    speeds: dict[int, float] = {}
    for host_s, xml in wp_re.findall(block):
        hid = int(host_s)
        if 0 <= hid < benign_count:
            starts[hid] = _parse_xyz("set", xml)
            goals[hid] = _parse_xyz("moveto", xml)
            speeds[hid] = _parse_speed(xml)

    hotspot_xy: tuple[float, float] | None = None
    spoofer_xml: str | None = None
    for host_s, xml in wp_re.findall(block):
        if int(host_s) == benign_count:
            spoofer_xml = xml
            break
    if spoofer_xml is not None:
        s0 = _parse_xyz("set", spoofer_xml)
        s1 = _parse_xyz("moveto", spoofer_xml)
        hotspot_xy = ((s0[0] + s1[0]) * 0.5, (s0[1] + s1[1]) * 0.5)

    host_ids = list(range(benign_count))
    missing = [hid for hid in host_ids if hid not in goals or hid not in starts or hid not in speeds]
    if missing:
        raise ValueError(f"Missing benign waypoint definitions for hosts: {missing}")

    rng = random.Random(f"{scenario_cfg_name}:{seed_value}:goal_shuffle_v2_constrained")
    perm = _choose_constrained_derangement(host_ids, starts, goals, rng, hotspot_xy)

    lines = ["# Seeded benign goal reassignment (same for all variants this seed)"]
    for hid, gid in zip(host_ids, perm):
        mv = _format_movement(hid, starts[hid], goals[gid], speeds[hid])
        lines.append(f"*.host[{hid}].mobility.waypointScript = xml(\"{mv}\")")
    return "\n".join(lines)


def _extract_containment_scores(generated_root: Path) -> list[float]:
    vals: list[float] = []
    for sca in generated_root.glob("**/*.sca"):
        # run_batch leaves a copied scalar at scenario root and another in results/.
        # Keep only copied top-level scalars to avoid double-counting each run.
        if sca.parent.name == "results":
            continue
        try:
            text = sca.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            if " spoofer_containment_rate_final " not in line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            # scalar BasicUav.gcs[0] spoofer_containment_rate_final <value>
            try:
                val = float(parts[-1])
            except ValueError:
                continue
            if val >= 0.0:
                vals.append(val)
    return vals


def _mean(xs: list[float]) -> float:
    if not xs:
        return float("nan")
    return sum(xs) / float(len(xs))


def _make_candidates(max_trials: int, rng_seed: int) -> list[dict[str, float]]:
    keys = list(PARAM_GRID.keys())
    all_combos = list(itertools.product(*(PARAM_GRID[k] for k in keys)))
    rng = random.Random(rng_seed)
    rng.shuffle(all_combos)
    combos = all_combos[: max(1, min(max_trials, len(all_combos)))]

    # Always include baseline/defaults as trial 1.
    baseline = {
        "ULI_IMM_INIT_MODE_CV": 0.45,
        "ULI_IMM_P_CV_STAY": 0.98,
        "ULI_IMM_P_CA_STAY": 0.84,
        "ULI_IMM_CV_POS_NOISE": 2.0,
        "ULI_IMM_CV_VEL_NOISE": 120.0,
        "ULI_IMM_CV_MEAS_NOISE": 400.0,
        "ULI_IMM_CA_POS_NOISE": 4.0,
        "ULI_IMM_CA_VEL_NOISE": 50.0,
        "ULI_IMM_CA_ACC_NOISE": 20.0,
        "ULI_IMM_CA_MEAS_NOISE": 50.0,
    }
    candidates: list[dict[str, float]] = [baseline]
    for combo in combos:
        if len(candidates) >= max_trials:
            break
        cand = {k: float(v) for k, v in zip(keys, combo)}
        if cand == baseline:
            continue
        candidates.append(cand)
    return candidates


def _run_split(
    *,
    repo_root: Path,
    root_dir: Path,
    trial_id: int,
    split_name: str,
    params: dict[str, float],
    scenarios: list[str],
    seeds: list[int],
    base_ini_text: str,
    parallel: int,
    keep_artifacts: bool,
    match_batch0004_setup: bool,
) -> TrialResult:
    trial_dir = root_dir / f"trial_{trial_id:04d}_{split_name}"
    generated_root = trial_dir / "generated"
    generated_root.mkdir(parents=True, exist_ok=True)

    expected_runs = len(scenarios) * len(seeds)
    for scenario in scenarios:
        slug = _scenario_slug(scenario)
        for seed in seeds:
            seed_pad = f"{seed:05d}"
            scen_dir = generated_root / f"{slug}_s{seed_pad}"
            scen_dir.mkdir(parents=True, exist_ok=True)
            cfg_name = TUNE_CONFIG_NAME
            goal_overrides = ""
            if match_batch0004_setup:
                m = re.match(r"^Scenario_DepotCity_(\d+)x1$", scenario)
                if not m:
                    raise ValueError(f"Unsupported scenario for --match-batch0004-setup: {scenario}")
                benign_count = int(m.group(1))
                goal_overrides = _seeded_goal_overrides(
                    full_text=base_ini_text,
                    scenario_cfg_name=scenario,
                    benign_count=benign_count,
                    seed_value=seed,
                )
            _write_trial_ini(
                base_ini_text=base_ini_text,
                ini_out=scen_dir / "omnetpp.ini",
                scenario=scenario,
                seed=seed,
                cfg_name=cfg_name,
                goal_overrides=goal_overrides,
            )

    env = {**{k: str(v) for k, v in params.items()}, "ULI_IMM_FORCE_DETECT_AT_S": "5"}
    generated_arg = str(generated_root.relative_to(repo_root))
    cmd = [
        "./scripts/docker-run.sh",
        "python3",
        "datagen/run_batch.py",
        generated_arg,
        "--configs",
        TUNE_CONFIG_NAME,
        "--parallel",
        str(parallel),
        "--keep-vec",
    ]
    log_path = trial_dir / "run.log"
    with log_path.open("w", encoding="utf-8") as logf:
        logf.write(f"trial_id={trial_id} split={split_name}\n")
        logf.write(f"params={json.dumps(env, sort_keys=True)}\n")
        logf.write(f"expected_runs={expected_runs}\n")
        logf.write(f"cmd={' '.join(cmd)}\n\n")
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            env={**os.environ, **env},
            stdout=logf,
            stderr=subprocess.STDOUT,
            check=False,
            text=True,
        )
    ok = proc.returncode == 0
    scores = _extract_containment_scores(generated_root)
    score = _mean(scores)

    if not keep_artifacts:
        # keep logs + summary, drop heavy sim artifacts
        shutil.rmtree(generated_root, ignore_errors=True)

    return TrialResult(
        trial_id=trial_id,
        split=split_name,
        score=score,
        n_runs=len(scores),
        ok=ok and len(scores) > 0,
        params=params,
        output_dir=trial_dir,
        log_path=log_path,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune SpoofingAware InstantDetect@5s for containment only.")
    parser.add_argument("--base-ini", default="simulations/spoofing_aware_with_planning/omnetpp.ini")
    parser.add_argument("--scenarios", default=",".join(DEFAULT_SCENARIOS))
    parser.add_argument("--train-seeds", default="0:19")
    parser.add_argument("--val-seeds", default="20:29")
    parser.add_argument("--max-trials", type=int, default=16)
    parser.add_argument("--parallel", type=int, default=0, help="run_batch parallel (0=auto)")
    parser.add_argument(
        "--out-root",
        default="simulations/spoofing_aware_with_planning/tuning_instant_detect_containment",
    )
    parser.add_argument("--rng-seed", type=int, default=7)
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep generated heavy trial artifacts.")
    parser.add_argument(
        "--match-batch0004-setup",
        action="store_true",
        help="Apply seeded benign goal reassignment logic used in historical batch 0004.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    base_ini = (repo_root / args.base_ini).resolve()
    if not base_ini.exists():
        raise SystemExit(f"Base INI not found: {base_ini}")
    base_ini_text = base_ini.read_text(encoding="utf-8")

    scenarios = [s.strip() for s in str(args.scenarios).split(",") if s.strip()]
    train_seeds = _parse_seeds(args.train_seeds)
    val_seeds = _parse_seeds(args.val_seeds)
    parallel = args.parallel if args.parallel > 0 else (os.cpu_count() or 4)

    run_root = (repo_root / args.out_root / f"run_{_timestamp()}").resolve()
    run_root.mkdir(parents=True, exist_ok=True)

    candidates = _make_candidates(max_trials=max(1, args.max_trials), rng_seed=args.rng_seed)
    trial_rows: list[dict[str, str]] = []
    best: TrialResult | None = None

    for idx, params in enumerate(candidates, start=1):
        print(
            f"[TUNER] train trial {idx}/{len(candidates)} starting "
            f"(scenarios={len(scenarios)} seeds={len(train_seeds)})",
            flush=True,
        )
        tr = _run_split(
            repo_root=repo_root,
            root_dir=run_root,
            trial_id=idx,
            split_name="train",
            params=params,
            scenarios=scenarios,
            seeds=train_seeds,
            base_ini_text=base_ini_text,
            parallel=parallel,
            keep_artifacts=args.keep_artifacts,
            match_batch0004_setup=args.match_batch0004_setup,
        )
        trial_rows.append(
            {
                "trial_id": str(tr.trial_id),
                "split": tr.split,
                "ok": str(tr.ok),
                "score_mean_containment": f"{tr.score:.8f}" if tr.score == tr.score else "nan",
                "n_runs_scored": str(tr.n_runs),
                **{k: str(v) for k, v in tr.params.items()},
                "log_path": str(tr.log_path),
            }
        )
        print(
            f"[TUNER] train trial {idx}/{len(candidates)} done "
            f"ok={tr.ok} score={tr.score:.6f} n_runs={tr.n_runs}",
            flush=True,
        )
        if tr.ok and (best is None or tr.score > best.score):
            best = tr

    if best is None:
        raise SystemExit("No successful trials produced containment scores.")

    # One validation pass on the best parameter set.
    print(
        f"[TUNER] validation starting for best trial {best.trial_id} "
        f"(scenarios={len(scenarios)} seeds={len(val_seeds)})",
        flush=True,
    )
    val = _run_split(
        repo_root=repo_root,
        root_dir=run_root,
        trial_id=best.trial_id,
        split_name="val",
        params=best.params,
        scenarios=scenarios,
        seeds=val_seeds,
        base_ini_text=base_ini_text,
        parallel=parallel,
        keep_artifacts=args.keep_artifacts,
        match_batch0004_setup=args.match_batch0004_setup,
    )
    trial_rows.append(
        {
            "trial_id": str(val.trial_id),
            "split": val.split,
            "ok": str(val.ok),
            "score_mean_containment": f"{val.score:.8f}" if val.score == val.score else "nan",
            "n_runs_scored": str(val.n_runs),
            **{k: str(v) for k, v in val.params.items()},
            "log_path": str(val.log_path),
        }
    )
    print(
        f"[TUNER] validation done ok={val.ok} score={val.score:.6f} n_runs={val.n_runs}",
        flush=True,
    )

    # Persist artifacts.
    csv_path = run_root / "trial_results.csv"
    fieldnames = list(trial_rows[0].keys())
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in trial_rows:
            w.writerow(row)

    best_json = {
        "objective": "maximize mean spoofer_containment_rate_final",
        "force_detect_at_s": 5.0,
        "best_trial_id": best.trial_id,
        "train_score_mean_containment": best.score,
        "validation_score_mean_containment": val.score,
        "params": best.params,
        "train_n_runs_scored": best.n_runs,
        "validation_n_runs_scored": val.n_runs,
    }
    best_json_path = run_root / "best_params.json"
    best_json_path.write_text(json.dumps(best_json, indent=2, sort_keys=True), encoding="utf-8")

    report = run_root / "report.md"
    report.write_text(
        "\n".join(
            [
                "# InstantDetect@5s Containment Tuning Report",
                "",
                "## Objective",
                "- maximize `spoofer_containment_rate_final` only",
                "- run only `SpoofingAware` with `ULI_IMM_FORCE_DETECT_AT_S=5`",
                "",
                "## Data",
                f"- scenarios: {', '.join(scenarios)}",
                f"- train seeds: {args.train_seeds}",
                f"- validation seeds: {args.val_seeds}",
                f"- match batch0004 setup: {args.match_batch0004_setup}",
                "",
                "## Best Parameters",
                f"- trial id: {best.trial_id}",
                f"- train mean containment: {best.score:.6f}",
                f"- validation mean containment: {val.score:.6f}",
                f"- params: `{json.dumps(best.params, sort_keys=True)}`",
                "",
                "## Files",
                f"- trial results csv: `{csv_path}`",
                f"- best params json: `{best_json_path}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Run root: {run_root}")
    print(f"Best params: {best_json_path}")
    print(f"Report: {report}")


if __name__ == "__main__":
    main()
