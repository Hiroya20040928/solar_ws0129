#!/usr/bin/env python3
"""Promote a versioned identification run only after every validation gate passes."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
MAP_PATH_KEYS = (
    "drive_eff_map",
    "regen_eff_map",
    "rint_map",
    "panel_eff_map",
    "mppt_eff_map",
    "drive_map_eco",
    "drive_map_power",
    "regen_map_eco",
    "regen_map_power",
    "ocv_soc_map",
)
METRIC_GATES = (
    ("power_rmse_clean_w", "vehicle_power_rmse_max_w", 150.0),
    ("voltage_rmse_clean_v", "vehicle_voltage_rmse_max_v", 1.0),
    ("battery_conditional_power_rmse_clean_w", "conditional_power_rmse_max_w", 150.0),
    ("battery_conditional_voltage_rmse_clean_v", "conditional_voltage_rmse_max_v", 1.0),
    ("end_to_end_power_rmse_clean_w", "end_to_end_power_rmse_max_w", 200.0),
    ("end_to_end_voltage_rmse_clean_v", "end_to_end_voltage_rmse_max_v", 2.0),
    ("end_to_end_moving_pv_rmse_w", "moving_pv_rmse_max_w", 150.0),
    ("pv_lodo_moving_rmse_w", "pv_lodo_moving_rmse_max_w", 150.0),
    ("pv_lodo_deployed_stop_rmse_w", "pv_lodo_deployed_stop_rmse_max_w", 200.0),
    ("end_to_end_power_residual_mean_120s_rmse_w", "power_residual_mean_120s_rmse_max_w", 150.0),
    ("end_to_end_energy_error_25km_rmse_wh", "energy_error_25km_rmse_max_wh", 35.0),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_or_absolute(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return os.path.relpath(path.resolve(), base.resolve()).replace("\\", "/")


def resolve_candidate_reference(candidate: Path, package: Path, raw: object) -> Path:
    path = Path(str(raw))
    if path.is_absolute():
        return path.resolve()
    for base in (candidate.parent, package, ROOT):
        resolved = (base / path).resolve()
        if resolved.exists():
            return resolved
    return (candidate.parent / path).resolve()


def evaluate_gates(candidate_cfg: dict, summary: dict, terminal: dict) -> dict:
    thresholds = dict((candidate_cfg.get("identification", {}) or {}).get("validation_gate", {}) or {})
    metrics = dict(summary.get("validation_metrics", {}) or {})
    checks = {}
    values = {}
    for metric_key, threshold_key, default_threshold in METRIC_GATES:
        value = float(metrics.get(metric_key, math.inf))
        threshold = float(thresholds.get(threshold_key, default_threshold))
        values[metric_key] = value
        checks[metric_key] = bool(math.isfinite(value) and value <= threshold)
    lo = float(terminal.get("evidence_interval_min", -math.inf))
    hi = float(terminal.get("evidence_interval_max", math.inf))
    spread = hi - lo
    spread_limit = float(thresholds.get("terminal_soc_evidence_spread_max", 0.05))
    values["terminal_soc_evidence_spread"] = spread
    checks["terminal_soc_evidence_spread"] = bool(
        math.isfinite(spread) and spread <= spread_limit
    )
    terminal_soc_error = abs(
        float(metrics.get("battery_conditional_retire_anchor_soc_error", math.inf))
    )
    terminal_soc_error_limit = float(thresholds.get("terminal_replay_soc_error_max", 0.02))
    terminal_voltage_observed = float(
        metrics.get("battery_conditional_retire_anchor_voltage_obs_v", math.nan)
    )
    terminal_voltage_predicted = float(
        metrics.get("battery_conditional_retire_anchor_voltage_pred_v", math.nan)
    )
    terminal_voltage_error = abs(terminal_voltage_predicted - terminal_voltage_observed)
    terminal_voltage_error_limit = float(
        thresholds.get("terminal_replay_voltage_error_max_v", 0.5)
    )
    values["terminal_replay_soc_error"] = terminal_soc_error
    values["terminal_replay_voltage_error_v"] = terminal_voltage_error
    checks["terminal_replay_soc"] = bool(
        math.isfinite(terminal_soc_error) and terminal_soc_error <= terminal_soc_error_limit
    )
    checks["terminal_replay_voltage"] = bool(
        math.isfinite(terminal_voltage_error)
        and terminal_voltage_error <= terminal_voltage_error_limit
    )
    terminal_variants = (
        ("vehicle", "", 0.02, 0.5),
        ("end_to_end", "end_to_end_", 0.03, 1.0),
    )
    for label, prefix, default_soc_limit, default_voltage_limit in terminal_variants:
        soc_error = abs(float(metrics.get(f"{prefix}retire_anchor_soc_error", math.inf)))
        voltage_observed = float(metrics.get(f"{prefix}retire_anchor_voltage_obs_v", math.nan))
        voltage_predicted = float(metrics.get(f"{prefix}retire_anchor_voltage_pred_v", math.nan))
        voltage_error = abs(voltage_predicted - voltage_observed)
        soc_limit = float(thresholds.get(f"{label}_terminal_soc_error_max", default_soc_limit))
        voltage_limit = float(
            thresholds.get(f"{label}_terminal_voltage_error_max_v", default_voltage_limit)
        )
        values[f"{label}_terminal_soc_error"] = soc_error
        values[f"{label}_terminal_voltage_error_v"] = voltage_error
        checks[f"{label}_terminal_soc"] = bool(
            math.isfinite(soc_error) and soc_error <= soc_limit
        )
        checks[f"{label}_terminal_voltage"] = bool(
            math.isfinite(voltage_error) and voltage_error <= voltage_limit
        )
    checks["terminal_high_precision_evidence"] = bool(
        terminal.get("high_precision_gate_pass", False)
    )
    terminal_anchor_role = str(
        ((summary.get("fit_plan", {}) or {}).get("terminal_anchor_role", "unknown"))
    ).strip().lower()
    values["terminal_anchor_role"] = terminal_anchor_role
    checks["terminal_anchor_role_operational"] = terminal_anchor_role in {
        "independent_consensus",
        "independent_measurement",
    }
    terminal_anchor = dict(summary.get("terminal_anchor", {}) or {})
    if terminal_anchor:
        checks["terminal_local_anchor_quality"] = bool(
            terminal_anchor.get("quality_gate_pass", False)
        )
        checks["terminal_independent_cross_channel_consistency"] = bool(
            terminal_anchor.get("weak_channel_cross_consistency_gate_pass", False)
        )
    acceleration_fit = dict(
        ((summary.get("fit_plan", {}) or {}).get("acceleration_observation_fit", {}) or {})
    )
    if bool(acceleration_fit.get("enabled", False)):
        validation_count = int(acceleration_fit.get("validation_sample_count", 0) or 0)
        validation_ratio = float(acceleration_fit.get("validation_rmse_ratio", math.inf))
        ratio_limit = float(thresholds.get("acceleration_validation_rmse_ratio_max", 1.02))
        minimum_count = int(thresholds.get("acceleration_validation_min_samples", 100))
        values["acceleration_validation_sample_count"] = validation_count
        values["acceleration_validation_rmse_ratio"] = validation_ratio
        lag_boundary_hit = bool(acceleration_fit.get("lag_search_boundary_hit", False))
        values["acceleration_lag_search_boundary_hit"] = lag_boundary_hit
        checks["acceleration_timestamp_holdout"] = bool(
            validation_count >= minimum_count
            and math.isfinite(validation_ratio)
            and validation_ratio <= ratio_limit
        )
        if "lag_search_boundary_hit" in acceleration_fit:
            checks["acceleration_lag_search_interior"] = not lag_boundary_hit
    grade_fit = dict(
        ((summary.get("fit_plan", {}) or {}).get("grade_observation_fit", {}) or {})
    )
    if bool(grade_fit.get("enabled", False)):
        validation_count = int(grade_fit.get("validation_sample_count", 0) or 0)
        validation_ratio = float(grade_fit.get("validation_rmse_ratio", math.inf))
        ratio_limit = float(thresholds.get("grade_validation_rmse_ratio_max", 1.02))
        minimum_count = int(thresholds.get("grade_validation_min_samples", 100))
        values["grade_validation_sample_count"] = validation_count
        values["grade_validation_rmse_ratio"] = validation_ratio
        values["grade_observation_adopted"] = bool(grade_fit.get("adopted", False))
        smoothing_boundary_hit = bool(
            grade_fit.get("smoothing_search_boundary_hit", False)
        )
        values["grade_smoothing_search_boundary_hit"] = smoothing_boundary_hit
        checks["grade_observation_holdout"] = bool(
            validation_count >= minimum_count
            and math.isfinite(validation_ratio)
            and validation_ratio <= ratio_limit
        )
        if "smoothing_search_boundary_hit" in grade_fit:
            checks["grade_smoothing_search_interior"] = not smoothing_boundary_hit
    dynamic_fit = dict(summary.get("battery_dynamic_fit", {}) or {})
    if dynamic_fit:
        adopted = bool(dynamic_fit.get("adopted", False))
        validation_count = int(dynamic_fit.get("validation_sample_count", 0) or 0)
        validation_ratio = float(dynamic_fit.get("validation_rmse_ratio", math.inf))
        ratio_limit = float(thresholds.get("battery_dynamic_validation_rmse_ratio_max", 1.0))
        minimum_count = int(thresholds.get("battery_dynamic_validation_min_samples", 100))
        identity = abs(float(dynamic_fit.get("r_polarization_ohm", 0.0) or 0.0)) <= 1.0e-12
        values["battery_dynamic_adopted"] = adopted
        values["battery_dynamic_validation_sample_count"] = validation_count
        values["battery_dynamic_validation_rmse_ratio"] = validation_ratio
        values["battery_dynamic_identity_when_rejected"] = identity
        checks["battery_dynamic_holdout"] = bool(
            (
                adopted
                and validation_count >= minimum_count
                and math.isfinite(validation_ratio)
                and validation_ratio <= ratio_limit
            )
            or (not adopted and identity)
        )
    map_shape_fit = dict(summary.get("map_shape_fit", {}) or {})
    map_ratio_limit = float(thresholds.get("map_shape_validation_rmse_ratio_max", 1.0))
    map_minimum_count = int(thresholds.get("map_shape_validation_min_samples", 16))
    for map_name in ("panel_mppt_combined", "drive_eff_map", "regen_eff_map", "rint_map"):
        shape = dict(map_shape_fit.get(map_name, {}) or {})
        if not shape:
            continue
        adopted = bool(shape.get("adopted", False))
        validation_count = int(shape.get("validation_sample_count", 0) or 0)
        validation_ratio = float(shape.get("validation_rmse_ratio", math.inf))
        global_gain = abs(float(shape.get("global_log_gain", 0.0) or 0.0))
        offsets = [
            abs(float(value))
            for key in ("row_offsets", "col_offsets")
            for value in (shape.get(key, []) or [])
        ]
        identity = global_gain <= 1.0e-12 and all(value <= 1.0e-12 for value in offsets)
        values[f"{map_name}_adopted"] = adopted
        values[f"{map_name}_validation_sample_count"] = validation_count
        values[f"{map_name}_validation_rmse_ratio"] = validation_ratio
        values[f"{map_name}_identity_when_rejected"] = identity
        checks[f"{map_name}_holdout"] = bool(
            (
                adopted
                and validation_count >= map_minimum_count
                and math.isfinite(validation_ratio)
                and validation_ratio <= map_ratio_limit
            )
            or (not adopted and identity)
        )
    return {
        "gate_pass": bool(checks and all(checks.values())),
        "checks": checks,
        "values": values,
        "thresholds": thresholds,
    }


def canonicalize_candidate_paths(cfg: dict, candidate: Path, package: Path) -> None:
    paths = cfg.setdefault("paths", {})
    for key, raw in list(paths.items()):
        if raw in (None, ""):
            continue
        resolved = resolve_candidate_reference(candidate, package, raw)
        paths[key] = relative_or_absolute(resolved, package)


def synchronize_fullsim(fullsim_path: Path, canonical_cfg: dict, run_label: str) -> None:
    if not fullsim_path.is_file():
        return
    fullsim = yaml.safe_load(fullsim_path.read_text(encoding="utf-8")) or {}
    source_paths = canonical_cfg.get("paths", {}) or {}
    target_paths = fullsim.setdefault("paths", {})
    for key in MAP_PATH_KEYS:
        if source_paths.get(key):
            target_paths[key] = source_paths[key]
    fullsim["model"] = dict(canonical_cfg.get("model", {}) or {})
    source_identification = canonical_cfg.get("identification", {}) or {}
    target_identification = fullsim.setdefault("identification", {})
    for key in ("fit_summary_yaml", "terminal_consistency_yaml", "validation_gate"):
        if key in source_identification:
            target_identification[key] = source_identification[key]
    source_mpc = canonical_cfg.get("mpc", {}) or {}
    target_mpc = fullsim.setdefault("mpc", {})
    for key in (
        "stop_tilt_fraction",
        "control_stop_tilt_fraction",
        "control_stop_arrival_tolerance_km",
        "control_stop_stationary_speed_kmh",
        "control_stop_brake_decel_kmhps",
        "control_stop_brake_margin_km",
    ):
        if key in source_mpc:
            target_mpc[key] = source_mpc[key]
    p_aux = float(fullsim["model"].get("P_aux", 0.0))
    fullsim.setdefault("live", {}).setdefault("autocal", {})["aux_power_w_init"] = p_aux
    notes = list(fullsim.setdefault("meta", {}).get("notes", []) or [])
    notes.append(f"Vehicle model and grounded fitted maps promoted from identification run {run_label}.")
    fullsim["meta"]["notes"] = list(dict.fromkeys(notes))
    fullsim_path.write_text(
        yaml.safe_dump(fullsim, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--gate-json",
        type=Path,
        help="Optional immutable JSON path for the evaluation result.",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Actually replace the canonical profile; without this flag the command is evaluation-only.",
    )
    parser.add_argument(
        "--allow-failed-gate",
        action="store_true",
        help="Research-only override; never use this for an operational package.",
    )
    args = parser.parse_args()

    package = args.package_dir.resolve()
    run_dir = args.run_dir.resolve()
    candidate = run_dir / "profile_candidate.yaml"
    summaries = sorted(run_dir.glob("*_generic_fit_summary.yaml"))
    terminal_path = run_dir / "terminal_soc_consistency.yaml"
    if not candidate.is_file() or len(summaries) != 1 or not terminal_path.is_file():
        raise FileNotFoundError(
            "run must contain profile_candidate.yaml, exactly one generic fit summary, and terminal_soc_consistency.yaml"
        )
    summary_path = summaries[0]
    candidate_cfg = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    summary = yaml.safe_load(summary_path.read_text(encoding="utf-8")) or {}
    terminal = yaml.safe_load(terminal_path.read_text(encoding="utf-8")) or {}
    gate = evaluate_gates(candidate_cfg, summary, terminal)
    if args.gate_json:
        gate_path = args.gate_json.resolve()
        gate_path.parent.mkdir(parents=True, exist_ok=True)
        gate_path.write_text(
            json.dumps(gate, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
    if not gate["gate_pass"] and not args.allow_failed_gate:
        print(json.dumps(gate, ensure_ascii=False, indent=2))
        return 2
    if not args.promote:
        if gate["gate_pass"]:
            message = (
                "All validation gates passed; evaluation only. "
                "Pass --promote to modify canonical files."
            )
        else:
            message = (
                "One or more validation gates failed; research evaluation only. "
                "Canonical files were not modified."
            )
        print(
            json.dumps(
                {
                    **gate,
                    "evaluation_only": True,
                    "promotion_performed": False,
                    "message": message,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    canonicalize_candidate_paths(candidate_cfg, candidate, package)
    identification = candidate_cfg.setdefault("identification", {})
    identification["fit_summary_yaml"] = relative_or_absolute(summary_path, package)
    identification["terminal_consistency_yaml"] = relative_or_absolute(terminal_path, package)
    p_aux = float(candidate_cfg.get("model", {}).get("P_aux", 0.0))
    candidate_cfg.setdefault("live", {}).setdefault("autocal", {})["aux_power_w_init"] = p_aux
    notes = list(candidate_cfg.setdefault("meta", {}).get("notes", []) or [])
    notes.append(f"Canonical model promoted from immutable identification run {run_dir.name} after validation-gate evaluation.")
    candidate_cfg["meta"]["notes"] = list(dict.fromkeys(notes))

    canonical = package / "profile.yaml"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = package / f"profile_before_{run_dir.name}_{stamp}.yaml"
    if canonical.is_file():
        shutil.copy2(canonical, backup)
    canonical.write_text(
        yaml.safe_dump(candidate_cfg, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    fullsim = package / "profile_fullsim_selflearned.yaml"
    synchronize_fullsim(fullsim, candidate_cfg, run_dir.name)

    promotion = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "run_dir": str(run_dir),
        "candidate_profile": str(candidate),
        "candidate_sha256": sha256(candidate),
        "fit_summary": str(summary_path),
        "fit_summary_sha256": sha256(summary_path),
        "terminal_consistency": str(terminal_path),
        "gate": gate,
        "research_override": bool(args.allow_failed_gate and not gate["gate_pass"]),
        "canonical_profile": str(canonical),
        "canonical_sha256": sha256(canonical),
        "canonical_backup": str(backup) if backup.is_file() else "",
        "canonical_fullsim_profile": str(fullsim) if fullsim.is_file() else "",
    }
    output = run_dir / "promotion_manifest.yaml"
    output.write_text(
        yaml.safe_dump(promotion, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(promotion, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
