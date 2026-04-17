"""
Load OMNeT++ ``.sca`` scalars and summarize Aware / AwareInstantDetect / TrustRid sweep outputs.

Expects filenames produced by ``datagen/run_scenario.py``::
    {scenario_hash}-{ConfigName}.sca

Example::

    python3 -m pymodules.analysis.spoofing_batch_metrics \\
        simulations/spoofing_aware_with_planning/batches/0001/generated/ -o summary.csv
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


def load_sca_scalars(sca_path: Path) -> dict[str, float]:
    """Parse scalar lines from an OMNeT++ ``.sca`` file."""
    text = sca_path.read_text(errors="replace")
    out: dict[str, float] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("scalar"):
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        try:
            val = float(parts[-1])
            name = parts[-2]
            out[name] = val
        except ValueError:
            continue
    return out


# {hash}-{tag}_{Aware|AwareInstantDetect|TrustRid}.sca
_SCA_PAIR_RE = re.compile(
    r"^([0-9a-f]{8})-(.+)_(Aware|AwareInstantDetect|TrustRid)\.sca$",
    re.IGNORECASE,
)


def summarize_sweep_directory(
    root: Path,
    csv_path: Path | None = None,
) -> list[dict[str, str | float | None]]:
    """
    Group ``*_Aware.sca`` / ``*_AwareInstantDetect.sca`` / ``*_TrustRid.sca``
    by (hash, tag prefix) and emit rows.

    Columns include:
      - nmac_proximity_*: benign-vs-benign proximity NMAC edge counts
      - nmac_benign_spoofer_*: benign-vs-spoofer proximity NMAC edge counts
      - nmac_spoofer_unsafe_*: benign entries into published unsafe region
      - min_benign_spoofer_distance_*: minimum benign-to-spoofer distance (m)
      - spoofer_containment_rate_*: fraction of ticks where unsafe region
        contains true spoofer (available in Aware runs)
    """
    root = root.resolve()
    pairs: dict[tuple[str, str], dict[str, Path]] = {}

    for sca in sorted(root.rglob("*.sca")):
        m = _SCA_PAIR_RE.match(sca.name)
        if not m:
            continue
        h, tag_base, variant = m.groups()
        vlow = variant.lower()
        if vlow == "aware":
            vk = "aware"
        elif vlow == "awareinstantdetect":
            vk = "aware_instant_detect"
        else:
            vk = "trust_rid"
        key = (h, tag_base)
        pairs.setdefault(key, {})
        pairs[key][vk] = sca

    rows: list[dict[str, str | float | None]] = []
    for (h, tag_base) in sorted(pairs.keys()):
        g = pairs[(h, tag_base)]
        pa = g.get("aware")
        pai = g.get("aware_instant_detect")
        pt = g.get("trust_rid")
        sa: dict[str, float] = load_sca_scalars(pa) if pa else {}
        sai: dict[str, float] = load_sca_scalars(pai) if pai else {}
        st: dict[str, float] = load_sca_scalars(pt) if pt else {}

        rows.append({
            "hash": h,
            "tag": tag_base,
            "nmac_proximity_aware": sa.get("nmac_proximity_final"),
            "nmac_proximity_aware_instant_detect": sai.get("nmac_proximity_final"),
            "nmac_proximity_trust_rid": st.get("nmac_proximity_final"),
            "nmac_benign_spoofer_aware": sa.get("nmac_benign_spoofer_final"),
            "nmac_benign_spoofer_aware_instant_detect": sai.get("nmac_benign_spoofer_final"),
            "nmac_benign_spoofer_trust_rid": st.get("nmac_benign_spoofer_final"),
            "nmac_spoofer_unsafe_aware": sa.get("nmac_spoofer_unsafe_final"),
            "nmac_spoofer_unsafe_aware_instant_detect": sai.get("nmac_spoofer_unsafe_final"),
            "nmac_spoofer_unsafe_trust_rid": st.get("nmac_spoofer_unsafe_final"),
            "min_benign_spoofer_distance_aware_m": sa.get("min_benign_spoofer_distance_final_m"),
            "min_benign_spoofer_distance_aware_instant_detect_m": sai.get("min_benign_spoofer_distance_final_m"),
            "min_benign_spoofer_distance_trust_rid_m": st.get("min_benign_spoofer_distance_final_m"),
            "spoofer_containment_rate_aware": sa.get("spoofer_containment_rate_final"),
            "spoofer_containment_rate_aware_instant_detect": sai.get("spoofer_containment_rate_final"),
            "spoofer_containment_rate_trust_rid": st.get("spoofer_containment_rate_final"),
            "gcs_reports_mean_ms_aware": sa.get("gcs_reports_mean_ms_final"),
            "gcs_reports_mean_ms_aware_instant_detect": sai.get("gcs_reports_mean_ms_final"),
            "gcs_reports_mean_ms_trust_rid": st.get("gcs_reports_mean_ms_final"),
            "gcs_tick_mean_ms_aware": sa.get("gcs_tick_mean_ms_final"),
            "gcs_tick_mean_ms_aware_instant_detect": sai.get("gcs_tick_mean_ms_final"),
            "gcs_tick_mean_ms_trust_rid": st.get("gcs_tick_mean_ms_final"),
            "gcs_compute_total_s_aware": sa.get("gcs_compute_total_s_final"),
            "gcs_compute_total_s_aware_instant_detect": sai.get("gcs_compute_total_s_final"),
            "gcs_compute_total_s_trust_rid": st.get("gcs_compute_total_s_final"),
            "num_hosts_observed_aware": sa.get("num_hosts_observed_final"),
            "num_hosts_observed_aware_instant_detect": sai.get("num_hosts_observed_final"),
            "num_hosts_observed_trust_rid": st.get("num_hosts_observed_final"),
            "first_detection_time_s_aware": sa.get("first_detection_time_s_final"),
            "first_detection_time_s_aware_instant_detect": sai.get("first_detection_time_s_final"),
            "detection_latency_s_aware": sa.get("detection_latency_s_final"),
            "detection_latency_s_aware_instant_detect": sai.get("detection_latency_s_final"),
            "detection_reports_total_aware": sa.get("detection_reports_total_final"),
            "detection_reports_total_aware_instant_detect": sai.get("detection_reports_total_final"),
            "detection_mlat_attempted_aware": sa.get("detection_mlat_attempted_final"),
            "detection_mlat_attempted_aware_instant_detect": sai.get("detection_mlat_attempted_final"),
            "detection_mlat_skipped_insufficient_receivers_aware": sa.get(
                "detection_mlat_skipped_insufficient_receivers_final"
            ),
            "detection_mlat_skipped_insufficient_receivers_aware_instant_detect": sai.get(
                "detection_mlat_skipped_insufficient_receivers_final"
            ),
            "detection_mlat_skipped_insufficient_receivers_fraction_aware": sa.get(
                "detection_mlat_skipped_insufficient_receivers_fraction_final"
            ),
            "detection_mlat_skipped_insufficient_receivers_fraction_aware_instant_detect": sai.get(
                "detection_mlat_skipped_insufficient_receivers_fraction_final"
            ),
            "localization_mae_m_aware": sa.get("localization_mae_m_final"),
            "localization_mae_m_aware_instant_detect": sai.get("localization_mae_m_final"),
            "localization_rmse_m_aware": sa.get("localization_rmse_m_final"),
            "localization_rmse_m_aware_instant_detect": sai.get("localization_rmse_m_final"),
            "localization_samples_aware": sa.get("localization_samples_final"),
            "localization_samples_aware_instant_detect": sai.get("localization_samples_final"),
            "aware_sca": str(pa) if pa else None,
            "aware_instant_detect_sca": str(pai) if pai else None,
            "trust_rid_sca": str(pt) if pt else None,
        })

    if csv_path is not None:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        if rows:
            fieldnames = list(rows[0].keys())
            with csv_path.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fieldnames)
                w.writeheader()
                w.writerows(rows)
        else:
            csv_path.write_text("")

    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Summarize Aware/AwareInstantDetect/TrustRid .sca metrics under a directory",
    )
    p.add_argument(
        "sweep_root",
        type=Path,
        help="Directory tree containing copied ``{hash}-{Config}.sca`` files",
    )
    p.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Write CSV summary to this path",
    )
    args = p.parse_args(argv)

    rows = summarize_sweep_directory(args.sweep_root, csv_path=args.output)
    if args.output:
        print(f"Wrote {len(rows)} row(s) to {args.output}")
    else:
        for r in rows:
            print(r)
    return 0


if __name__ == "__main__":
    sys.exit(main())
