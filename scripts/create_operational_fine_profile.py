"""Create a fine-mesh operational profile from the latest canonical fit profile."""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def resolve(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def materialize_relative_references(cfg: dict, source_profile: Path) -> None:
    """Keep references valid when the generated YAML is written outside its package root."""
    package_dir = source_profile.parent
    for key, raw in list((cfg.get("paths", {}) or {}).items()):
        if raw in (None, ""):
            continue
        path = Path(str(raw))
        if not path.is_absolute():
            package_candidate = (package_dir / path).resolve()
            root_candidate = (ROOT / path).resolve()
            path = package_candidate if package_candidate.exists() else root_candidate
        cfg["paths"][key] = path.as_posix()
    identification = cfg.get("identification", {}) or {}
    for key in ("fit_summary_yaml", "terminal_consistency_yaml"):
        raw = identification.get(key, "")
        if not raw:
            continue
        path = Path(str(raw))
        if not path.is_absolute():
            path = (package_dir / path).resolve()
        identification[key] = path.as_posix()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--integration-ds-km", type=float, default=0.1)
    parser.add_argument("--control-ds-km", type=float, default=5.0)
    parser.add_argument("--policy", type=Path, help="Optional GPU policy CSV to lock for exact replay.")
    parser.add_argument(
        "--forecast-csv",
        type=Path,
        help="Optional weather grid override, for example the PV-conditioned historical counterfactual grid.",
    )
    parser.add_argument(
        "--scenario-label",
        default="",
        help="Human-readable scenario label recorded in profile metadata.",
    )
    parser.add_argument(
        "--mode",
        choices=("exact_replay", "live_mpc"),
        default="exact_replay",
        help="Create a locked certification replay or an hourly re-optimizing live MPC profile.",
    )
    parser.add_argument(
        "--lock-policy",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Bypass the CPU optimizer and replay --policy exactly (default: true when policy is given).",
    )
    parser.add_argument(
        "--require-model-validation-gate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Block simulation unless all independent model-validation gates pass.",
    )
    parser.add_argument("--simulation-output-dir", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile_path = resolve(args.profile)
    package_dir = profile_path.parent
    output = resolve(args.output) if args.output else package_dir / "profile_operational_fine.yaml"
    cfg = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    if args.forecast_csv is not None:
        forecast_path = resolve(args.forecast_csv)
        if not forecast_path.is_file():
            raise FileNotFoundError(forecast_path)
        forecast_value = os.path.relpath(forecast_path, package_dir).replace("\\", "/")
        cfg.setdefault("paths", {})["forecast_csv"] = forecast_value
    race_km = float(cfg["mpc"]["race_km"])
    ds_km = float(args.integration_ds_km)
    ctrl_km = float(args.control_ds_km)
    if ds_km <= 0.0 or ctrl_km <= 0.0:
        raise ValueError("mesh spacing must be positive")

    cfg.setdefault("meta", {})["name"] = f"{package_dir.name}_operational_fine"
    if str(args.scenario_label).strip():
        cfg["meta"]["scenario"] = str(args.scenario_label).strip()
    notes = list(cfg["meta"].get("notes", []) or [])
    notes.append(
        "Fine profile generated from the canonical fitted profile; CUDA search is a proposer and fixed-policy 1 Hz replay is the acceptance authority."
    )
    if args.mode == "live_mpc":
        notes.append(
            "The accepted CUDA policy is a warm start only; live upper MPC re-optimizes it hourly from measured SoC and refreshed weather."
        )
    if not args.require_model_validation_gate:
        notes.append(
            "Research-only replay override: the independent model-validation gate is recorded but does not block execution; this result is not operationally certified."
        )
    cfg["meta"]["notes"] = list(dict.fromkeys(notes))

    simulation = cfg.setdefault("simulation", {})
    output_dir = args.simulation_output_dir
    if output_dir is None:
        output_dir = Path(
            f"project_packages/{package_dir.name}/outputs/prerace_operational_fine"
        )
    output_prefix = output.stem
    simulation.update(
        {
            "output_dir": output_dir.as_posix(),
            "output_prefix": output_prefix,
            "latest_manifest_json": (output_dir / "latest_simulation_run.json").as_posix(),
            "detail_rate_hz": 1.0,
            "detail_compression": "gzip",
            "require_model_validation_gate": bool(args.require_model_validation_gate),
            "validation_scope": (
                "operational_gate_required"
                if args.require_model_validation_gate
                else "research_only_unvalidated_model"
            ),
        }
    )
    simulation.setdefault("execution_model", {}).update({"enabled": True, "inner_dt_sec": 1.0})

    model = cfg["model"]
    soc_floor = float(model.get("soc_min", 0.1)) + 0.005
    mpc = cfg["mpc"]
    common_mpc = {
        "terminal_soc_min": soc_floor,
        "soc_finish_target": soc_floor,
        "soc_finish_tol": 0.005,
        "execution_soc_trajectory_guard_enabled": False,
        "prediction_execution_soc_tolerance": 0.002,
    }
    mpc.update(common_mpc)
    if args.mode == "exact_replay":
        mpc.update(
            {
                "upper_horizon_mode": "fixed",
                "upper_ds_km": ds_km,
                "upper_horizon_km": race_km,
                "upper_max_steps": int(math.ceil(race_km / ds_km)) + 1,
                "upper_ctrl_km": ctrl_km,
                "upper_adaptive_min_ds_km": ds_km,
                "upper_adaptive_max_ds_km": ds_km,
                "upper_adaptive_growth": 1.0,
                "upper_replan_sec": 0.0,
                "upper_replan_km": 0.0,
                "upper_global_search_enabled": False,
                "upper_global_search_mode": "never",
                "upper_cert_grid_levels": 0,
                "upper_cert_grid_values_kmh": [],
                "upper_cert_max_evaluations": 0,
            }
        )
    else:
        mpc["upper_replan_sec"] = max(60.0, float(mpc.get("upper_replan_sec", 3600.0) or 3600.0))
        mpc["upper_replan_km"] = 0.0
        mpc["upper_lock_initial_policy"] = False
        mpc["upper_global_search_enabled"] = True
        if str(mpc.get("upper_global_search_mode", "auto") or "auto").lower() == "never":
            mpc["upper_global_search_mode"] = "auto"
    if args.policy is not None:
        policy = resolve(args.policy)
        if not policy.is_file():
            raise FileNotFoundError(policy)
        try:
            policy_value = policy.relative_to(package_dir).as_posix()
        except ValueError:
            policy_value = policy.as_posix()
        cfg.setdefault("paths", {})["initial_upper_policy_csv"] = policy_value
        lock_policy = bool(args.lock_policy) and args.mode == "exact_replay"
        mpc["upper_lock_initial_policy"] = lock_policy
        if lock_policy:
            mpc["upper_max_iter"] = 0
    upper_cost = mpc.setdefault("upper_cost", {})
    upper_cost.update(
        {
            "objective_mode": "fastest_feasible",
            "w_uncertainty_reserve": 0.0,
            "reserve_soc_per_hour": 0.0,
            "reserve_soc_max_extra": 0.0,
        }
    )
    mpc["w_soc_terminal"] = max(float(mpc.get("w_soc_terminal", 0.0)), 1.0e12)
    upper_cost["w_soc_terminal"] = max(float(upper_cost.get("w_soc_terminal", 0.0)), 1.0e12)
    upper_cost["constraint_penalty"] = max(float(upper_cost.get("constraint_penalty", 0.0)), 1.0e12)

    route_path = Path(str(cfg["paths"]["route_profile_csv"]))
    route_path = route_path if route_path.is_absolute() else package_dir / route_path
    weather_path = Path(str(cfg["paths"]["forecast_csv"]))
    weather_path = weather_path if weather_path.is_absolute() else package_dir / weather_path
    route_spacing = 0.1
    weather_spacing = 25.0
    try:
        import pandas as pd

        route = pd.read_csv(route_path)
        route_s = sorted(set(pd.to_numeric(route.get("dist_km", route.get("s_km")), errors="coerce").dropna()))
        if len(route_s) > 1:
            route_spacing = float(min(b - a for a, b in zip(route_s[:-1], route_s[1:]) if b > a))
        weather = pd.read_csv(weather_path, usecols=["s_km"])
        weather_s = sorted(set(pd.to_numeric(weather["s_km"], errors="coerce").dropna()))
        if len(weather_s) > 1:
            weather_spacing = float(min(b - a for a, b in zip(weather_s[:-1], weather_s[1:]) if b > a))
    except (FileNotFoundError, ValueError, TypeError):
        pass

    cfg["mesh_verification"] = {
        "method": "fixed-policy successive h-refinement with independent 1 Hz explicit replay",
        "integration_mesh_candidates_km": [1.0, 0.5, 0.2, 0.1],
        "control_mesh_candidates_km": [25.0, 10.0, 5.0, 2.0, 1.0],
        "selected_integration_mesh_km": ds_km if args.mode == "exact_replay" else float(mpc.get("upper_ds_km", ds_km)),
        "selected_control_mesh_km": ctrl_km if args.mode == "exact_replay" else float(mpc.get("upper_ctrl_km", ctrl_km)),
        "route_source_spacing_km": route_spacing,
        "weather_source_spacing_km": weather_spacing,
        "acceptance": {
            "elapsed_time_change_max_sec": 60.0,
            "terminal_soc_change_max": 0.002,
            "speed_profile_rms_change_max_kmh": 0.5,
            "prediction_execution_soc_error_max": 0.002,
        },
        "status": (
            "pending until scripts/run_upper_mesh_convergence.py passes all criteria"
            if args.mode == "exact_replay"
            else "live warm-start profile; authority remains the sibling exact-replay mesh certificate"
        ),
        "references": [
            "Betts and Huffman (1998), Mesh refinement in direct transcription methods for optimal control",
            "Haman and Rao (2024), Adaptive Mesh Refinement and Error Estimation Method for Optimal Control Using Direct Collocation",
        ],
    }
    if output.parent.resolve() != package_dir.resolve():
        materialize_relative_references(cfg, profile_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
