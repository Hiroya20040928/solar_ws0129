#!/usr/bin/env python3
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import yaml


def load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a versioned profile from a measured-PV-conditioned identification candidate."
    )
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--fit-summary", type=Path, required=True)
    parser.add_argument("--output-profile", type=Path, required=True)
    parser.add_argument("--output-summary", type=Path, required=True)
    parser.add_argument("--end-to-end-metrics", type=Path)
    args = parser.parse_args()

    profile = load_yaml(args.profile)
    candidate = load_yaml(args.candidate)
    summary = load_yaml(args.fit_summary)
    motion = candidate.get("motion_fit", {}) or {}
    metrics = candidate.get("validation_metrics", {}) or {}
    if not isinstance(motion, dict) or not isinstance(metrics, dict):
        raise ValueError("candidate.motion_fit and candidate.validation_metrics must be mappings")

    old_metrics = summary.get("validation_metrics", {}) or {}
    old_power = float(old_metrics.get("power_rmse_clean_w", float("inf")))
    new_power = float(metrics.get("power_rmse_clean_w", float("inf")))
    if not (new_power < old_power):
        raise ValueError(f"candidate is not a power-RMSE improvement: {new_power} >= {old_power}")

    out_profile = deepcopy(profile)
    model = out_profile.setdefault("model", {})
    for source_key, profile_key in (
        ("cda", "CdA"),
        ("crr", "Crr"),
        ("p_aux_w", "P_aux"),
        ("grade_scale", "grade_scale"),
        ("drive_eff_scale", "drive_eff_scale"),
        ("headwind_gain", "headwind_gain"),
    ):
        if source_key in motion:
            model[profile_key] = float(motion[source_key])
    model["P_aux_stopped"] = float(model.get("P_aux", 21.0))
    model["P_aux_night"] = 0.0
    model["regen_eff_scale"] = float(model.get("drive_eff_scale", 1.0))

    simulation = out_profile.setdefault("simulation", {})
    simulation["soc0"] = float(model.get("soc_max", 0.98))
    live = out_profile.setdefault("live", {})
    live.setdefault("autocal", {})["aux_power_w_init"] = float(model.get("P_aux", 21.0))
    wifi = live.setdefault("wifi_bridge", {})
    wifi.setdefault("timestamp_required", True)
    wifi.setdefault("max_packet_age_sec", 5.0)
    wifi.setdefault("max_future_skew_sec", 2.0)
    wifi.setdefault("max_out_of_order_sec", 0.0)
    meta = out_profile.setdefault("meta", {})
    meta["name"] = args.output_profile.stem
    notes = meta.setdefault("notes", [])
    if not isinstance(notes, list):
        notes = [str(notes)]
        meta["notes"] = notes
    notes.extend(
        [
            "Vehicle-side motion coefficients were refitted with measured PV as a conditional input.",
            "Weather/PV-model replay remains a separate end-to-end validation and is not absorbed into CdA/Crr/efficiency.",
            "Restart SoC uses a robust stationary valid-voltage window; stale zero-voltage rows are ignored.",
            "The historical 2831 km terminal SoC evidence is internally inconsistent and is reported as an uncertainty interval, not an exact training label.",
        ]
    )

    out_summary = deepcopy(summary)
    out_summary["profile_yaml"] = args.output_profile.name
    out_summary["motion_fit"] = motion
    out_summary["validation_metrics"] = dict(metrics)
    if args.end_to_end_metrics and args.end_to_end_metrics.exists():
        end_metrics = load_yaml(args.end_to_end_metrics)
        for key, value in (end_metrics.get("validation_metrics", end_metrics) or {}).items():
            out_summary["validation_metrics"][f"end_to_end_{key}"] = value
    out_summary["validation_protocol"] = {
        "vehicle_fit_solar_source": "measured_when_available",
        "end_to_end_solar_source": "weather_and_pv_model",
        "restart_soc_anchor": "median_of_valid_stationary_window",
        "terminal_anchor_policy": "report_conflicting_voltage_energy_and_coulomb_estimates_without_forcing",
    }
    out_summary["candidate_adoption"] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_profile": str(args.profile),
        "source_summary": str(args.fit_summary),
        "candidate": str(args.candidate),
        "old_power_rmse_clean_w": old_power,
        "new_power_rmse_clean_w": new_power,
        "accepted": True,
    }

    args.output_profile.parent.mkdir(parents=True, exist_ok=True)
    args.output_summary.parent.mkdir(parents=True, exist_ok=True)
    args.output_profile.write_text(
        yaml.safe_dump(out_profile, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n"
    )
    args.output_summary.write_text(
        yaml.safe_dump(out_summary, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n"
    )
    print(args.output_profile)
    print(args.output_summary)


if __name__ == "__main__":
    main()
