#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path
from statistics import mean


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def _safe_float(v: str | None) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Rank IMM grid runs by worst-scenario containment and center error."
    )
    ap.add_argument("--results-csv", type=Path, required=True)
    ap.add_argument("--out-csv", type=Path, required=True)
    args = ap.parse_args()

    rows = _read_rows(args.results_csv)
    out_rows: list[dict[str, str | float]] = []
    for r in rows:
        if (r.get("status", "") or "").lower() != "ok":
            continue
        run_root = Path(r.get("run_root", ""))
        summary = _read_rows(run_root / "summary.csv")
        if not summary:
            continue

        scen_contain: dict[str, list[float]] = {}
        scen_center_err: dict[str, list[float]] = {}
        for rr in summary:
            tag = rr.get("tag", "")
            if "_s" not in tag:
                continue
            scen = tag.replace("Scenario_", "").rsplit("_s", 1)[0].lower()
            c = _safe_float(rr.get("spoofer_containment_rate_aware"))
            e = _safe_float(rr.get("localization_mae_m_aware"))
            if c is not None:
                scen_contain.setdefault(scen, []).append(c)
            if e is not None:
                scen_center_err.setdefault(scen, []).append(e)

        if not scen_contain:
            continue
        contain_means = {k: mean(v) for k, v in scen_contain.items() if v}
        center_means = {k: mean(v) for k, v in scen_center_err.items() if v}
        if not contain_means:
            continue

        worst_scen = min(contain_means, key=contain_means.get)
        best_scen = max(contain_means, key=contain_means.get)
        out_rows.append(
            {
                "run_name": r.get("run_name", ""),
                "score": r.get("score", ""),
                "containment_mean": r.get("containment_rate_mean", ""),
                "center_error_mean_m": r.get("center_error_mean_m", ""),
                "worst_scenario": worst_scen,
                "worst_scenario_containment_mean": contain_means[worst_scen],
                "best_scenario": best_scen,
                "best_scenario_containment_mean": contain_means[best_scen],
                "containment_spread": contain_means[best_scen] - contain_means[worst_scen],
                "worst_scenario_center_error_mean_m": center_means.get(worst_scen, ""),
            }
        )

    out_rows.sort(
        key=lambda x: (
            -float(x["worst_scenario_containment_mean"]),
            float(x["containment_spread"]),
            float(x["worst_scenario_center_error_mean_m"])
            if x["worst_scenario_center_error_mean_m"] != ""
            else float("inf"),
        )
    )

    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="") as f:
        fn = [
            "run_name",
            "score",
            "containment_mean",
            "center_error_mean_m",
            "worst_scenario",
            "worst_scenario_containment_mean",
            "best_scenario",
            "best_scenario_containment_mean",
            "containment_spread",
            "worst_scenario_center_error_mean_m",
        ]
        w = csv.DictWriter(f, fieldnames=fn)
        w.writeheader()
        w.writerows(out_rows)
    print(f"Wrote {args.out_csv} ({len(out_rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
