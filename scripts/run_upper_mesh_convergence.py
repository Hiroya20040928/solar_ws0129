#!/usr/bin/env python3
"""Run fixed-policy integration and independent-policy control convergence gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]


def parse_float_list(value: str) -> list[float]:
    return [float(item) for item in str(value).split(",") if item.strip()]


def parse_control_policies(values: list[str]) -> dict[float, Path]:
    policies: dict[float, Path] = {}
    for raw in values:
        spacing_text, separator, path_text = str(raw).partition("=")
        if not separator or not path_text.strip():
            raise ValueError("--control-policy must use CONTROL_KM=POLICY_CSV")
        spacing = float(spacing_text)
        if spacing <= 0.0:
            raise ValueError("control-policy spacing must be positive")
        path = Path(path_text).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        policies[spacing] = path
    return policies


def assign_finest_control_policy(
    control_meshes: list[float],
    supplied_policies: dict[float, Path],
    finest_policy: Path,
) -> tuple[float, dict[float, Path], list[float]]:
    """Assign --policy to the finest requested control mesh without relabelling it."""
    if not control_meshes:
        raise ValueError("at least one control mesh is required")
    finest_ctrl = min(float(value) for value in control_meshes)
    policies = dict(supplied_policies)
    policies[finest_ctrl] = finest_policy.resolve()
    order = [float(ctrl) for ctrl in control_meshes if float(ctrl) in policies]
    return finest_ctrl, policies, order


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve(profile: Path, value: str) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (profile.parent / path).resolve()


def load_plan(summary: dict) -> pd.DataFrame:
    path = Path(summary["plan_csv"])
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    frame = pd.read_csv(path)
    return frame.sort_values("plan_s_km")


def speed_rms_difference(left: pd.DataFrame, right: pd.DataFrame, race_km: float) -> float:
    grid = np.arange(0.0, race_km + 1.0, 1.0)
    left_v = np.interp(grid, left["plan_s_km"], left["plan_v_kmh"])
    right_v = np.interp(grid, right["plan_s_km"], right["plan_v_kmh"])
    return float(np.sqrt(np.mean((left_v - right_v) ** 2)))


def materialize_profile(base_path: Path, output_path: Path, *, policy_path: Path, ds_km: float, ctrl_km: float) -> dict:
    cfg = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    for key, value in list((cfg.get("paths", {}) or {}).items()):
        if value:
            cfg["paths"][key] = str(resolve(base_path, value))
    for key in ("fit_summary_yaml", "terminal_consistency_yaml"):
        value = cfg.get("identification", {}).get(key, "")
        if value:
            cfg["identification"][key] = str(resolve(base_path, value))
    cfg["paths"]["initial_upper_policy_csv"] = str(policy_path.resolve())
    race_km = float(cfg["mpc"]["race_km"])
    run_dir = output_path.parent
    cfg["meta"]["name"] = f"mesh_ds{ds_km:g}_ctrl{ctrl_km:g}"
    cfg["simulation"].update(
        {
            # Exact acceptance must evaluate the policy itself, not a second
            # energy-budget controller that can silently slow an infeasible plan.
            "energy_budget": False,
            "output_dir": str(run_dir),
            "output_prefix": "simulation",
            "auto_version_outputs": False,
            "latest_manifest_json": str(run_dir / "latest_simulation_run.json"),
            "detail_rate_hz": 1.0,
            "detail_compression": "gzip",
        }
    )
    cfg["mpc"].update(
        {
            "upper_horizon_mode": "fixed",
            "upper_ds_km": ds_km,
            "upper_horizon_km": race_km,
            "upper_max_steps": int(math.ceil(race_km / ds_km)) + 1,
            "upper_ctrl_km": ctrl_km,
            "upper_lock_initial_policy": True,
            "upper_global_search_enabled": False,
            "upper_global_search_mode": "never",
            "upper_max_iter": 0,
            "upper_cert_grid_levels": 0,
            "upper_cert_grid_values_kmh": [],
        }
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--integration-meshes-km", default="")
    parser.add_argument("--control-meshes-km", default="")
    parser.add_argument(
        "--control-policy",
        action="append",
        default=[],
        metavar="CONTROL_KM=POLICY_CSV",
        help=(
            "Independently optimized policy for a control spacing. Supply the coarser "
            "policies; --policy is assigned to the finest spacing."
        ),
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reuse a completed case only when its profile, policy, and simulator signatures still match.",
    )
    args = parser.parse_args()

    profile = args.profile.resolve()
    policy = args.policy.resolve()
    output_dir = args.output_dir.resolve()
    base_cfg = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
    control_policy_paths = parse_control_policies(args.control_policy)
    acceptance = base_cfg.get("mesh_verification", {}).get("acceptance", {})
    verification = base_cfg.get("mesh_verification", {}) or {}
    integration_meshes = parse_float_list(args.integration_meshes_km) or [
        float(value) for value in verification.get("integration_mesh_candidates_km", [1.0, 0.5, 0.2, 0.1])
    ]
    control_meshes = parse_float_list(args.control_meshes_km) or [
        float(value) for value in verification.get("control_mesh_candidates_km", [25.0, 10.0, 5.0, 2.0, 1.0])
    ]
    selected_ds = float(base_cfg["mpc"]["upper_ds_km"])
    selected_ctrl, control_policy_paths, control_order = assign_finest_control_policy(
        control_meshes,
        control_policy_paths,
        policy,
    )
    cases = [(ds, selected_ctrl, "integration", policy) for ds in integration_meshes]
    cases.extend(
        (selected_ds, ctrl, "control", control_policy_paths[ctrl])
        for ctrl in control_order
    )

    summaries = {}
    rows = []
    for ds_km, ctrl_km, phase, case_policy in cases:
        key = (ds_km, ctrl_km)
        if key in summaries:
            continue
        run_dir = output_dir / f"ds_{ds_km:g}_ctrl_{ctrl_km:g}"
        run_profile = run_dir / "profile.yaml"
        materialize_profile(
            profile,
            run_profile,
            policy_path=case_policy,
            ds_km=ds_km,
            ctrl_km=ctrl_km,
        )
        signature = hashlib.sha256(
            (
                file_sha256(run_profile)
                + file_sha256(case_policy)
                + file_sha256(ROOT / "scripts" / "solar_sim.py")
            ).encode("ascii")
        ).hexdigest()
        signature_path = run_dir / "run_signature.txt"
        command = [sys.executable, "-u", str(ROOT / "scripts" / "solar_sim.py"), "--profile_yaml", str(run_profile)]
        log_path = run_dir / "console.log"
        manifest_path = run_dir / "latest_simulation_run.json"
        reusable = bool(
            args.resume
            and manifest_path.is_file()
            and signature_path.is_file()
            and signature_path.read_text(encoding="ascii").strip() == signature
        )
        if reusable:
            cached = json.loads(manifest_path.read_text(encoding="utf-8"))
            detail_path = Path(str(cached.get("detail_csv", "")))
            if not detail_path.is_absolute():
                detail_path = (ROOT / detail_path).resolve()
            reusable = bool(detail_path.is_file() and int(cached.get("detail_rows", 0)) > 0)
        if not reusable:
            with log_path.open("w", encoding="utf-8") as log:
                result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True, check=False)
            if result.returncode != 0 or not manifest_path.exists():
                raise RuntimeError(f"mesh run failed: ds={ds_km} ctrl={ctrl_km}; inspect {log_path}")
            signature_path.write_text(signature + "\n", encoding="ascii")
        summary = json.loads(manifest_path.read_text(encoding="utf-8"))
        summaries[key] = summary
        rows.append(
            {
                "phase": phase,
                "integration_ds_km": ds_km,
                "control_ds_km": ctrl_km,
                "prediction_steps": summary["upper_solver_diagnostics"][0]["prediction_steps"],
                "control_dimensions": summary["upper_solver_diagnostics"][0]["control_dimensions"],
                "elapsed_hours": summary["elapsed_hours"],
                "final_soc": summary["final_soc"],
                "prediction_execution_soc_error": summary["prediction_execution_terminal_soc_error"],
                "finish_reached": summary["finish_reached"],
                "policy_csv": str(case_policy),
                "policy_sha256": file_sha256(case_policy),
                "summary_json": str(manifest_path),
            }
        )

    comparisons = []
    for phase, ordered in (
        ("integration", [(ds, selected_ctrl) for ds in integration_meshes]),
        ("control", [(selected_ds, ctrl) for ctrl in control_order]),
    ):
        for coarse, fine in zip(ordered[:-1], ordered[1:]):
            coarse_summary = summaries[coarse]
            fine_summary = summaries[fine]
            elapsed_change_sec = abs(float(fine_summary["elapsed_hours"]) - float(coarse_summary["elapsed_hours"])) * 3600.0
            soc_change = abs(float(fine_summary["final_soc"]) - float(coarse_summary["final_soc"]))
            speed_rms = speed_rms_difference(load_plan(coarse_summary), load_plan(fine_summary), float(base_cfg["mpc"]["race_km"]))
            sync_error = abs(float(fine_summary["prediction_execution_terminal_soc_error"]))
            checks = {
                "elapsed": elapsed_change_sec <= float(acceptance.get("elapsed_time_change_max_sec", 60.0)),
                "terminal_soc": soc_change <= float(acceptance.get("terminal_soc_change_max", 0.002)),
                "speed_rms": speed_rms <= float(acceptance.get("speed_profile_rms_change_max_kmh", 0.5)),
                "prediction_execution_soc": sync_error <= float(acceptance.get("prediction_execution_soc_error_max", 0.002)),
            }
            comparisons.append(
                {
                    "phase": phase,
                    "coarse_ds_km": coarse[0],
                    "coarse_ctrl_km": coarse[1],
                    "fine_ds_km": fine[0],
                    "fine_ctrl_km": fine[1],
                    "elapsed_change_sec": elapsed_change_sec,
                    "terminal_soc_change": soc_change,
                    "speed_profile_rms_change_kmh": speed_rms,
                    "prediction_execution_soc_error": sync_error,
                    **{f"check_{key}": value for key, value in checks.items()},
                    "pair_pass": bool(all(checks.values())),
                }
            )

    integration_final = [row for row in comparisons if row["phase"] == "integration"][-1:]
    control_final = [row for row in comparisons if row["phase"] == "control"][-1:]
    final_pairs = integration_final + control_final
    gate_pass = bool(len(final_pairs) == 2 and all(row["pair_pass"] for row in final_pairs))
    pd.DataFrame(rows).to_csv(output_dir / "mesh_runs.csv", index=False)
    pd.DataFrame(comparisons).to_csv(output_dir / "mesh_comparisons.csv", index=False)
    result = {
        "method": "fixed-policy successive h-refinement with independent 1 Hz explicit replay",
        "policy_csv": str(policy),
        "acceptance": acceptance,
        "selected_integration_ds_km": selected_ds,
        "selected_control_ds_km": selected_ctrl,
        "control_policy_csvs": {
            str(ctrl): str(control_policy_paths[ctrl]) for ctrl in control_order
        },
        "control_policy_gate_evaluated": len(control_final) == 1,
        "mesh_gate_pass": gate_pass,
        "final_pair_results": final_pairs,
        "caution": (
            "The integration gate uses one fixed policy. The control gate compares independently "
            "optimized policies at successive control spacings. Missing control-policy inputs fail "
            "the combined gate. This is a numerical convergence certificate, not a proof of the "
            "continuous global optimum."
        ),
    }
    (output_dir / "mesh_convergence_summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if gate_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
