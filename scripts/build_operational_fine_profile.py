#!/usr/bin/env python3
"""Create the non-certified fine-mesh operational MPC profile."""

from __future__ import annotations

import argparse
import copy
import math
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = ROOT / "project_packages" / "bwsc2025_fitted_mle19_energywindow_inertia" / "profile.yaml"


def median_distance_spacing(path: Path) -> float:
    frame = pd.read_csv(path)
    for name in ("s_km", "route_progress_km", "dist_km"):
        if name not in frame.columns:
            continue
        values = pd.to_numeric(frame[name], errors="coerce").dropna().drop_duplicates().sort_values()
        spacing = values.diff().dropna()
        if not spacing.empty:
            return float(spacing.median())
    return math.nan


def resolve_profile_path(profile_path: Path, value: str) -> Path:
    candidate = Path(str(value))
    return candidate if candidate.is_absolute() else (profile_path.parent / candidate).resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    base = args.base.resolve()
    output = args.output.resolve() if args.output else base.with_name("profile_operational_fine.yaml")
    cfg = yaml.safe_load(base.read_text(encoding="utf-8")) or {}
    paths = cfg.get("paths", {})
    route_spacing_km = median_distance_spacing(resolve_profile_path(base, paths["route_profile_csv"]))
    weather_spacing_km = median_distance_spacing(resolve_profile_path(base, paths["forecast_csv"]))
    race_km = float(cfg.get("mpc", {}).get("race_km", 3026.9))

    integration_ds_km = 0.1
    control_ds_km = 5.0
    result = copy.deepcopy(cfg)
    result.setdefault("paths", {})["initial_upper_policy_csv"] = "outputs/gpu_upper_search/latest_policy.csv"
    result.setdefault("meta", {})["name"] = "profile_operational_fine"
    result["meta"]["purpose"] = (
        "Fine-mesh no-trouble full-course MPC for operational simulation; not an exhaustive finite-library certificate."
    )
    notes = list(result["meta"].get("notes", []) or [])
    notes.extend(
        [
            f"Route source spacing is {route_spacing_km:.3f} km and weather-grid spacing is {weather_spacing_km:.3f} km.",
            "The 0.1 km state-integration mesh and 5 km speed-knot mesh must pass the declared integration/control convergence gates before adoption.",
            "The earlier four-variable finite-grid certificate remains a reduced-policy certificate and is not an operational discretization.",
            "Continuous global optimality is not claimed for this high-dimensional profile.",
        ]
    )
    result["meta"]["notes"] = notes

    simulation = result.setdefault("simulation", {})
    simulation.update(
        {
            "output_dir": "outputs/profile_operational_fine",
            "output_prefix": "profile_operational_fine_fullcourse",
            "latest_manifest_json": "outputs/profile_operational_fine/latest_simulation_run.json",
            "detail_rate_hz": 1.0,
            "require_model_validation_gate": True,
        }
    )
    simulation["execution_model"] = {
        "enabled": True,
        "inner_dt_sec": 1.0,
        "tau_sec": 1.0,
        "accel_limit_kmhps": 1.2,
        "decel_limit_kmhps": 3.5,
        "deadband_kmh": 0.1,
        "quantize_step_kmh": 0.1,
        "reaction_delay_sec": 0.2,
    }

    mpc = result.setdefault("mpc", {})
    mpc.update(
        {
            "upper_horizon_mode": "fixed",
            "upper_ds_km": integration_ds_km,
            "upper_horizon_km": race_km,
            "upper_max_steps": int(math.ceil(race_km / integration_ds_km)) + 1,
            "upper_adaptive_min_ds_km": integration_ds_km,
            "upper_adaptive_max_ds_km": integration_ds_km,
            "upper_adaptive_growth": 1.0,
            "upper_ctrl_km": control_ds_km,
            "upper_max_iter": 200,
            "upper_global_search_enabled": True,
            "upper_global_search_mode": "always",
            "upper_cem_generations": 80,
            "upper_cem_population": 256,
            "upper_cem_elite": 32,
            "upper_local_refine_topk": 8,
            "upper_shgo_samples": 0,
            "upper_cert_grid_levels": 0,
            "upper_cert_grid_values_kmh": [],
            "upper_cert_max_evaluations": 0,
            "upper_replan_sec": 0.0,
            "upper_replan_km": 0.0,
        }
    )
    result["mesh_verification"] = {
        "method": "fixed-policy successive h-refinement with independent 1 Hz explicit replay",
        "integration_mesh_candidates_km": [1.0, 0.5, 0.2, 0.1],
        "control_mesh_candidates_km": [25.0, 10.0, 5.0, 2.0, 1.0],
        "selected_integration_mesh_km": integration_ds_km,
        "selected_control_mesh_km": control_ds_km,
        "route_source_spacing_km": route_spacing_km,
        "weather_source_spacing_km": weather_spacing_km,
        "acceptance": {
            "elapsed_time_change_max_sec": 60.0,
            "terminal_soc_change_max": 0.002,
            "speed_profile_rms_change_max_kmh": 0.5,
            "prediction_execution_soc_error_max": 0.002,
        },
        "status": "pending until scripts/run_upper_mesh_convergence.py passes all criteria",
        "references": [
            "Betts and Huffman (1998), Mesh refinement in direct transcription methods for optimal control",
            "Haman and Rao (2024), Adaptive Mesh Refinement and Error Estimation Method for Optimal Control Using Direct Collocation",
        ],
    }

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(yaml.safe_dump(result, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(output)
    print(f"route_spacing_km={route_spacing_km:.6f}")
    print(f"weather_spacing_km={weather_spacing_km:.6f}")
    print(f"integration_ds_km={integration_ds_km:.6f}")
    print(f"control_ds_km={control_ds_km:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
