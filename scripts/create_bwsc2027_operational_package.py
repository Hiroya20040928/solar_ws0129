#!/usr/bin/env python3
"""Create the gated BWSC 2027 pre-season operations package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path

import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "project_packages" / "bwsc2025_fitted_mle19_energywindow_inertia"
MLE35 = SRC / "outputs" / "identification" / "runs" / "mle35_expanded_grade_single_source_ultra_v1"
DEFAULT_OUTPUT = ROOT / "project_packages" / "bwsc2027_operational"
REGULATIONS = ROOT / "inputs" / "regulations" / "bwsc2027" / "2027_BWSC_Event_Regulations_V1.0.pdf"


def sha256(path: Path) -> str:                                     # [関数定義] sha256 の処理実行ブロック
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def copy(source: Path, destination: Path) -> None:                 # [関数定義] copy の処理実行ブロック
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def load_yaml(path: Path) -> dict:                                 # [関数定義] load_yaml の処理実行ブロック
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_yaml(path: Path, payload: dict) -> None:                 # [関数定義] write_yaml の処理実行ブロック
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def local_paths(map_set: str) -> dict[str, str]:                   # [関数定義] local_paths の処理実行ブロック
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "route_waypoints_csv": "route/provisional_2025_waypoints.csv",
        "route_profile_csv": "route/provisional_2025_profile.csv",
        "speed_profile_csv": "route/provisional_2025_speed.csv",
        "forecast_csv": "weather/provisional_2025_grid.csv",
        "stop_yaml": "race/provisional_2025_stops.yaml",
        "drive_schedule_yaml": "race/official_2027_daily_schedule.yaml",
        "drive_eff_map": f"maps/{map_set}/drive.csv",
        "regen_eff_map": f"maps/{map_set}/regen.csv",
        "rint_map": f"maps/{map_set}/rint.csv",
        "panel_eff_map": f"maps/{map_set}/panel.csv",
        "mppt_eff_map": f"maps/{map_set}/mppt.csv",
        "drive_map_eco": f"maps/{map_set}/drive_eco.csv",
        "drive_map_power": f"maps/{map_set}/drive_power.csv",
        "regen_map_eco": f"maps/{map_set}/regen_eco.csv",
        "regen_map_power": f"maps/{map_set}/regen_power.csv",
        "ocv_soc_map": f"maps/{map_set}/ocv.csv",
        "observed_weather_csv": "validation/observed_weather_2025.csv",
        "progress_reference_csv": "validation/observed_log_2025.csv",
        "actual_stop_yaml": "validation/actual_stops_2025.yaml",
        "actual_drive_schedule_yaml": "validation/actual_schedule_2025.yaml",
    }


def configure_profile(base: dict, *, name: str, map_set: str, candidate: bool) -> dict:  # [関数定義] configure_profile の処理実行ブロック
    cfg = json.loads(json.dumps(base))
    meta = cfg.setdefault("meta", {})
    meta["name"] = name
    meta["purpose"] = "BWSC 2027 gated pre-season operation and simulation profile"
    meta["operational_readiness"] = "RESEARCH_ONLY" if candidate else "PRESEASON_ONLY"
    meta["notes"] = [
        "Vehicle coefficients are inherited from MLE35 research candidate."
        if candidate
        else "Vehicle coefficients are inherited from the retained MLE19 operational baseline.",
        "2027 official start is 08:00 ACST on 22 August 2027; daily driving is 08:00-17:00 ACST.",
        "The 2027 Route Notes and control-stop locations are not yet installed; route, stop and weather files are explicitly provisional 2025 stand-ins.",
        "Do not use this profile for the 2027 race until readiness.yaml reports RACE_READY.",
    ]
    cfg["paths"] = local_paths(map_set)
    simulation = cfg.setdefault("simulation", {})
    simulation["start_utc"] = "2027-08-21T22:30:00Z"
    simulation["forecast_start_time_utc"] = "2027-08-21T22:30:00Z"
    simulation.pop("race_deadline_utc", None)
    simulation["output_dir"] = f"outputs/{name}/prerace"
    simulation["latest_manifest_json"] = f"outputs/{name}/prerace/latest_simulation_run.json"
    simulation["output_prefix"] = name
    simulation["require_model_validation_gate"] = not candidate
    simulation["validation_scope"] = "research_only_unvalidated_model" if candidate else "preseason_operational_baseline"
    cfg.setdefault("runtime", {})["forecast_time_tz"] = "Australia/Darwin"
    cfg.setdefault("live", {})["forecast_time_tz"] = "Australia/Darwin"
    cfg["live"]["weather"]["timezone_name"] = "Australia/Darwin"
    cfg["identification"]["fit_summary_yaml"] = f"vehicle/{map_set}_fit_summary.yaml"
    cfg["identification"]["terminal_consistency_yaml"] = f"vehicle/{map_set}_terminal.yaml"
    cfg.setdefault("mpc", {})["race_km"] = 3026.9
    cfg["mpc"]["upper_horizon_km"] = 3026.9
    return cfg                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build(output: Path, *, update_existing: bool = False) -> None:  # [関数定義] build の処理実行ブロック
    if output.exists() and not update_existing:
        raise FileExistsError(f"refusing to overwrite existing package: {output}")
    output.mkdir(parents=True, exist_ok=update_existing)

    active_base = load_yaml(SRC / "profile_operational_fine.yaml")
    candidate_base = load_yaml(MLE35 / "profile_operational_gpu_research.yaml")
    active = configure_profile(active_base, name="bwsc2027_operational_gate_mle19", map_set="m19", candidate=False)
    candidate = configure_profile(candidate_base, name="bwsc2027_research_mle35", map_set="m35", candidate=True)
    active["meta"]["operational_readiness"] = "BLOCKED_MODEL_GATE"
    active["meta"]["notes"].append(
        "MLE19 also fails the current strict independent gate; profile.yaml must remain blocked."
    )
    write_yaml(output / "profile.yaml", active)
    preseason = json.loads(json.dumps(active))
    preseason["meta"]["name"] = "bwsc2027_preseason_mle19_unvalidated"
    preseason["meta"]["operational_readiness"] = "PRESEASON_RESEARCH_ONLY"
    preseason["simulation"]["require_model_validation_gate"] = False
    preseason["simulation"]["validation_scope"] = "preseason_unvalidated_model"
    preseason["simulation"]["output_dir"] = "outputs/bwsc2027_preseason_mle19_unvalidated/prerace"
    preseason["simulation"]["latest_manifest_json"] = "outputs/bwsc2027_preseason_mle19_unvalidated/prerace/latest_simulation_run.json"
    preseason["simulation"]["output_prefix"] = "bwsc2027_preseason_mle19_unvalidated"
    write_yaml(output / "profile_preseason_mle19_unvalidated.yaml", preseason)
    write_yaml(output / "profile_candidate_mle35.yaml", candidate)

    template = load_yaml(ROOT / "project_packages" / "bwsc2027_template" / "profile.yaml")
    template.setdefault("simulation", {})["start_utc"] = "2027-08-21T22:30:00Z"
    template["simulation"]["forecast_start_time_utc"] = "2027-08-21T22:30:00Z"
    template.setdefault("meta", {})["notes"] = list(template["meta"].get("notes") or []) + [
        "Corrected official Day-1 start: 22 August 2027 08:00 ACST = 21 August 2027 22:30 UTC."
    ]
    template["paths"] = {
        key: f"blank/{value}" for key, value in (template.get("paths") or {}).items()
    }
    template.setdefault("identification", {})["input_dir"] = "blank/data/identification/raw"
    template["identification"]["output_dir"] = "outputs/blank_identification"
    write_yaml(output / "profile_2027_blank_input.yaml", template)
    blank_source = ROOT / "project_packages" / "bwsc2027_template"
    shutil.copytree(blank_source / "data", output / "blank" / "data", dirs_exist_ok=True)
    shutil.copytree(blank_source / "maps", output / "blank" / "maps", dirs_exist_ok=True)

    source_maps = SRC / "outputs" / "identification" / "adopted_maps"
    candidate_maps = MLE35 / "adopted_maps"
    map_names = {
        "drive_eff_map.csv": "drive.csv",
        "regen_eff_map.csv": "regen.csv",
        "Rint_T_by_soc_fitted_grounded.csv": "rint.csv",
        "panel_eff_map.csv": "panel.csv",
        "mppt_eff_map.csv": "mppt.csv",
        "drive_eff_map_eco.csv": "drive_eco.csv",
        "drive_eff_map_power.csv": "drive_power.csv",
        "regen_eff_map_eco.csv": "regen_eco.csv",
        "regen_eff_map_power.csv": "regen_power.csv",
        "ocv_soc_curve.csv": "ocv.csv",
    }
    for source_name, short_name in map_names.items():
        copy(source_maps / source_name, output / "maps" / "m19" / short_name)
        copy(candidate_maps / source_name, output / "maps" / "m35" / short_name)

    route_source = SRC / "data" / "route"
    copy(route_source / "bwsc2025_fitted_mle8_mass235_mapfit_route_waypoints.csv", output / "route" / "provisional_2025_waypoints.csv")
    copy(route_source / "bwsc2025_fitted_mle8_mass235_mapfit_route_profile.csv", output / "route" / "provisional_2025_profile.csv")
    copy(route_source / "bwsc2025_fitted_mle8_mass235_mapfit_speed_profile.csv", output / "route" / "provisional_2025_speed.csv")
    (output / "route" / "official_2027_route_PENDING.csv").write_text(
        "dist_km,lat,lon,alt_m,speed_limit_kmh,source\n",
        encoding="utf-8",
    )

    copy(SRC / "data" / "weather" / "bwsc2025_nominal_fullcourse_weather_grid.csv", output / "weather" / "provisional_2025_grid.csv")
    (output / "weather" / "official_2027_forecast_PENDING.csv").write_text(
        "time,s_km,GHI,DNI,DHI,temp_air,wind_speed,wind_dir,source\n",
        encoding="utf-8",
    )
    copy(SRC / "data" / "race" / "bwsc2025_official_control_stops.yaml", output / "race" / "provisional_2025_stops.yaml")
    write_yaml(
        output / "race" / "official_2027_daily_schedule.yaml",
        {
            "deny_by_default": True,
            "daily_windows": [
                {
                    "start_local": "08:00",
                    "end_local": "17:00",
                    "tz": "Australia/Darwin",
                    "v_min_kmh": 60.0,
                    "v_max_kmh": 110.0,
                }
            ],
            "source": "2027 BWSC Event Regulations V1.0, rules 3.21 and 3.29",
            "control_stop_duration_sec": 1800,
            "control_stop_locations_status": "PENDING_OFFICIAL_2027_ROUTE_NOTES",
        },
    )
    write_yaml(
        output / "race" / "official_2027_stops_PENDING.yaml",
        {
            "source": "PENDING official 2027 Route Notes",
            "status": "NOT_RACE_READY",
            "stops": [],
        },
    )

    copy(SRC / "data" / "observed" / "bwsc2025_observed_log_5s.csv", output / "validation" / "observed_log_2025.csv")
    copy(SRC / "data" / "weather" / "bwsc2025_observed_weather_10min.csv", output / "validation" / "observed_weather_2025.csv")
    copy(SRC / "data" / "race" / "bwsc2025_actual_stops.yaml", output / "validation" / "actual_stops_2025.yaml")
    copy(SRC / "data" / "race" / "bwsc2025_actual_drive_schedule.yaml", output / "validation" / "actual_schedule_2025.yaml")
    copy(SRC / "outputs" / "identification" / "bwsc2025_fitted_mle19_energywindow_inertia_generic_fit_summary.yaml", output / "vehicle" / "m19_fit_summary.yaml")
    copy(SRC / "outputs" / "identification" / "terminal_soc_consistency.yaml", output / "vehicle" / "m19_terminal.yaml")
    copy(MLE35 / "bwsc2025_fitted_mle19_energywindow_inertia_generic_fit_summary.yaml", output / "vehicle" / "m35_fit_summary.yaml")
    copy(MLE35 / "terminal_soc_consistency.yaml", output / "vehicle" / "m35_terminal.yaml")
    copy(MLE35 / "reports" / "model_validation_gate_recheck.yaml", output / "vehicle" / "m35_gate.yaml")
    copy(REGULATIONS, output / "regulations" / "bwsc2027_v1.pdf")

    registry = {
        "active": {
            "id": None,
            "status": "NO_MODEL_HAS_PASSED_THE_CURRENT_OPERATIONAL_GATE",
            "reason": "Both MLE19 and MLE35 fail one or more independent validation limits.",
        },
        "fallback_baseline": {
            "id": "mle19",
            "profile": "profile.yaml",
            "preseason_profile": "profile_preseason_mle19_unvalidated.yaml",
            "status": "BLOCKED_FOR_LIVE_PRESEASON_COMPARISON_ONLY",
            "reason": "Retained only as the historical baseline; it is not certified by the current stricter gate.",
        },
        "candidate": {
            "id": "mle35",
            "profile": "profile_candidate_mle35.yaml",
            "status": "RESEARCH_ONLY_REJECTED_FOR_LIVE",
            "gate": "vehicle/m35_gate.yaml",
            "reason": "Independent power, voltage, 25 km energy and terminal-evidence gates failed.",
        },
        "next": {
            "id": "mle36_or_later",
            "status": "NOT_YET_CREATED",
            "reason": "A higher number is not sufficient. Promotion requires new evidence/model structure and all independent gates to pass.",
            "promotion_command": "python scripts/promote_identification_run.py --package project_packages/bwsc2027_operational --run-dir <validated_run>",
        },
    }
    write_yaml(output / "model_registry.yaml", registry)
    write_yaml(
        output / "readiness.yaml",
        {
            "status": "BLOCKED_MODEL_AND_EVENT_INPUT_GATES",
            "confirmed": {
                "event_dates": "2027-08-22..2027-08-29",
                "day1_start": "2027-08-22 08:00 ACST",
                "daily_drive_window": "08:00..17:00 ACST",
                "control_stop_duration_sec": 1800,
                "vehicle_mass_kg": 235.0,
            },
            "blocking_inputs": [
                "official 2027 Route Notes and exact route distance",
                "official 2027 control-stop locations and opening windows",
                "2027 race-week forecast and live API verification",
                "post-maintenance YATA measurement log and independent validation",
                "validated MLE36-or-later model",
                "actual Wi-Fi IP/port and microcontroller end-to-end test",
            ],
        },
    )

    rows = []
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name in {
            "FILE_REASON_CATALOG.csv",
            "README_2027.md",
            "MLE36_AND_LATER_PLAN.md",
        }:
            continue
        rel = path.relative_to(output).as_posix()
        if rel.startswith("maps/m19/") or rel.startswith("vehicle/m19"):
            status, reason, trigger = "ACTIVE_BASELINE", "Current retained vehicle model input", "Replace only after all independent promotion gates pass"
        elif rel.startswith("maps/m35/") or rel.startswith("vehicle/m35") or "candidate_mle35" in rel:
            status, reason, trigger = "RESEARCH_ONLY", "Latest immutable candidate retained for comparison", "Never activate unless a new gate report passes"
        elif "provisional_2025" in rel or rel.startswith("validation/"):
            status, reason, trigger = "PROVISIONAL_OR_VALIDATION", "2025 evidence used for pre-season reproducibility", "Replace operational path when official 2027 data arrive; retain validation evidence"
        elif "PENDING" in rel:
            status, reason, trigger = "REQUIRED_EMPTY_INPUT", "Prevents an unknown 2027 value being silently invented", "Fill from official Route Notes or race-week forecast"
        elif rel.startswith("regulations/"):
            status, reason, trigger = "OFFICIAL_SOURCE", "2027 regulation authority", "Replace when an official bulletin or newer revision is issued"
        else:
            status, reason, trigger = "PACKAGE_CONTROL", "Controls selection, readiness, or reproducibility", "Change only with recorded review reason"
        rows.append([rel, status, reason, trigger, path.stat().st_size, sha256(path)])
    with (output / "FILE_REASON_CATALOG.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["path", "status", "why_included", "change_trigger", "size_bytes", "sha256"])
        writer.writerows(rows)

    (output / "README_2027.md").write_text(
        """# BWSC 2027 gated operations package

This package is intentionally not labelled race-ready. No current model passes the strict operational gate.

- `profile.yaml`: safety-gated MLE19 baseline; expected to reject execution until a model passes.
- `profile_preseason_mle19_unvalidated.yaml`: explicit unvalidated profile for pre-season comparison only.
- `profile_candidate_mle35.yaml`: rejected research candidate; never use for live operation without a passing gate.
- `profile_2027_blank_input.yaml`: clean input profile for the final 2027 route and vehicle evidence.
- `model_registry.yaml`: active/candidate/next-generation decision and reasons.
- `readiness.yaml`: confirmed facts and remaining blockers.
- `FILE_REASON_CATALOG.csv`: every included file, why it exists, and exactly when it may change.

MLE36 is not automatically better than MLE35. Run a new identification only after adding new independent evidence or a justified model correction, then promote it only through `promote_identification_run.py` when every validation gate passes.
""",
        encoding="utf-8",
    )
    (output / "MLE36_AND_LATER_PLAN.md").write_text(
        """# MLE36 and later promotion plan

The next run number is not a quality claim. MLE36 or a later run may become active only after all gates pass on independent data.

1. Resolve the 2831 km SoC evidence spread using calibrated pack-current integration, OCV relaxation points, charge records, and uncertainty bounds.
2. Re-identify battery capacity, line resistance, 1RC polarization, and voltage sensor offset with time-aligned current/voltage/temperature data.
3. Re-identify drive and PV models by regime, while keeping one physical source for each measured power channel to avoid double fitting.
4. Use leave-one-day-out and distance-block holdouts; fitting samples must not also certify the candidate.
5. Inspect residuals by speed, acceleration, grade, irradiance, temperature, SoC, stop/drive state, and day.
6. Require every threshold in the model-validation gate, including terminal local evidence and cross-channel consistency.
7. Promote atomically through `promote_identification_run.py`; never edit the active profile by hand.

More optimizer iterations alone cannot fix missing observability, inconsistent terminal evidence, timestamp error, or a wrong model structure.
""",
        encoding="utf-8",
    )
    with (output / "FILE_REASON_CATALOG.csv").open("a", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        for name, reason in (
            ("README_2027.md", "Explains safe profile selection and package limitations"),
            ("MLE36_AND_LATER_PLAN.md", "Defines evidence, model and independent-gate requirements for the next candidate"),
        ):
            path = output / name
            writer.writerow(
                [
                    name,
                    "PACKAGE_CONTROL",
                    reason,
                    "Update only when the workflow or promotion criteria change",
                    path.stat().st_size,
                    sha256(path),
                ]
            )


def main() -> int:                                                 # [関数定義] main の処理実行ブロック
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--update-existing", action="store_true")  # [CLI引数] コマンドライン実行引数の定義
    args = parser.parse_args()
    output = args.output.resolve() if args.output.is_absolute() else (ROOT / args.output).resolve()
    build(output, update_existing=args.update_existing)
    print(output)
    return 0                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


if __name__ == "__main__":
    raise SystemExit(main())
