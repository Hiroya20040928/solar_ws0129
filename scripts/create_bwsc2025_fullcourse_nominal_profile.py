#!/usr/bin/env python3
import argparse
import copy
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PACKAGE = ROOT / "project_packages" / "bwsc2025_public"
DEFAULT_FINISH_SOC_TARGET = 0.12
DEFAULT_TERMINAL_WEIGHT = 100000.0
CONTROL_STOP_DWELL_SEC = 1800.0


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML must be a mapping: {path}")
    return data


def dump_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)


def resolve_profile_asset(profile_path: Path, asset_path: str) -> Path:
    raw = str(asset_path or "").strip()
    if not raw:
        raise ValueError(f"empty asset path from {profile_path}")
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    rel = (profile_path.parent / candidate).resolve()
    if rel.exists():
        return rel
    repo = (ROOT / candidate).resolve()
    if repo.exists():
        return repo
    raise FileNotFoundError(f"asset not found: {asset_path}")


def clip(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def build_planning_weather(source_csv: Path, out_csv: Path, tcell_gain: float, headwind_gain: float) -> None:
    df = pd.read_csv(source_csv)
    out = df.copy()
    ghi_col = "GHI" if "GHI" in out.columns else ("ghi" if "ghi" in out.columns else "")
    tamb_col = "Tamb_C" if "Tamb_C" in out.columns else ("temperature_2m_C" if "temperature_2m_C" in out.columns else "")
    tcell_col = "Tcell_C" if "Tcell_C" in out.columns else ""
    headwind_col = "headwind_ms" if "headwind_ms" in out.columns else ""
    if ghi_col and tamb_col:
        out["Tcell_C"] = pd.to_numeric(out[tamb_col], errors="coerce").ffill().bfill()
        out["Tcell_C"] = out["Tcell_C"] + tcell_gain * pd.to_numeric(out[ ghi_col ], errors="coerce").fillna(0.0)
    elif tcell_col:
        out["Tcell_C"] = pd.to_numeric(out[tcell_col], errors="coerce").ffill().bfill()
    if headwind_col:
        out["headwind_ms"] = pd.to_numeric(out[headwind_col], errors="coerce").fillna(0.0) * headwind_gain
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_csv, index=False)


def build_public_control_stops(public_info_yaml: Path, out_yaml: Path) -> None:
    info = load_yaml(public_info_yaml)
    rows = info.get("control_stops_public", [])
    stops = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        s_km = float(row.get("s_km", 0.0) or 0.0)
        if s_km <= 0.0:
            continue
        stops.append(
            {
                "label": str(row.get("name", "") or ""),
                "s_km": round(s_km, 3),
                "dwell_sec": CONTROL_STOP_DWELL_SEC,
            }
        )
    dump_yaml(out_yaml, {"stops": stops})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-profile", required=True)
    ap.add_argument("--output-profile", default="")
    ap.add_argument("--finish-soc-target", type=float, default=DEFAULT_FINISH_SOC_TARGET)
    args = ap.parse_args()

    src_profile = Path(args.source_profile).resolve()
    cfg = load_yaml(src_profile)
    out_profile = Path(args.output_profile).resolve() if args.output_profile else src_profile.with_name(src_profile.stem + "_fullcourse_nominal.yaml")

    out_cfg = copy.deepcopy(cfg)
    package_dir = out_profile.parent
    public_info_yaml = PUBLIC_PACKAGE / "data" / "public" / "bwsc2025_public_info.yaml"
    public_info = load_yaml(public_info_yaml)
    planning_race_km = float(public_info.get("event", {}).get("route_finish_ref_km", 0.0) or 0.0)
    if planning_race_km <= 0.0:
        route_csv = resolve_profile_asset(src_profile, out_cfg["paths"]["route_profile_csv"])
        route_df = pd.read_csv(route_csv)
        planning_race_km = float(pd.to_numeric(route_df["dist_km"], errors="coerce").max())

    fit_summary_yaml = package_dir / "outputs" / "identification" / f"{package_dir.name}_fit_summary.yaml"
    fit_summary = load_yaml(fit_summary_yaml) if fit_summary_yaml.exists() else {}
    pv_fit = fit_summary.get("pv_fit", {}) if isinstance(fit_summary.get("pv_fit"), dict) else {}
    motion_fit = fit_summary.get("motion_fit", {}) if isinstance(fit_summary.get("motion_fit"), dict) else {}
    tcell_gain = float(pv_fit.get("tcell_gain_c_per_wm2", out_cfg.get("live", {}).get("weather", {}).get("tcell_gain", 0.03)) or 0.03)
    headwind_gain = float(motion_fit.get("headwind_gain", 1.0) or 1.0)

    source_weather = resolve_profile_asset(src_profile, out_cfg["paths"].get("forecast_fill_csv", out_cfg["paths"]["forecast_csv"]))
    planning_weather_rel = Path("data") / "weather" / f"{package_dir.name}_nominal_fullcourse_weather_10min.csv"
    planning_weather_abs = (package_dir / planning_weather_rel).resolve()
    build_planning_weather(source_weather, planning_weather_abs, tcell_gain=tcell_gain, headwind_gain=headwind_gain)

    control_stop_rel = Path("data") / "race" / f"{package_dir.name}_control_stops_public.yaml"
    control_stop_abs = (package_dir / control_stop_rel).resolve()
    build_public_control_stops(public_info_yaml, control_stop_abs)

    schedule_rel = Path("data") / "race" / "bwsc2025_drive_schedule.yaml"
    public_schedule_abs = PUBLIC_PACKAGE / schedule_rel
    local_schedule_abs = (package_dir / schedule_rel).resolve()
    if not local_schedule_abs.exists():
        local_schedule_abs.parent.mkdir(parents=True, exist_ok=True)
        local_schedule_abs.write_text(public_schedule_abs.read_text(encoding="utf-8"), encoding="utf-8")

    out_cfg.setdefault("meta", {})
    out_cfg["meta"]["name"] = out_profile.stem
    notes = out_cfg["meta"].setdefault("notes", [])
    if isinstance(notes, list):
        additions = [
            "Nominal full-course planning profile generated from the fitted replay package.",
            "Planner weather uses the public full-course route history with fitted Tcell gain and fitted headwind exposure gain.",
            "Planner schedule uses the public full-race daily windows and public control stops, not the actual retirement-day drive log.",
            "Nominal planner disables uncertainty reserve so the base plan represents the most likely weather trajectory.",
        ]
        for item in additions:
            if item not in notes:
                notes.append(item)

    out_cfg.setdefault("paths", {})
    old_forecast_csv = str(out_cfg["paths"].get("forecast_csv", "") or "")
    old_stop_yaml = str(out_cfg["paths"].get("stop_yaml", "") or "")
    old_drive_schedule_yaml = str(out_cfg["paths"].get("drive_schedule_yaml", "") or "")
    out_cfg["paths"]["forecast_csv"] = str(planning_weather_rel).replace("\\", "/")
    out_cfg["paths"]["observed_weather_csv"] = old_forecast_csv
    out_cfg["paths"]["stop_yaml"] = str(control_stop_rel).replace("\\", "/")
    out_cfg["paths"]["actual_stop_yaml"] = old_stop_yaml
    out_cfg["paths"]["drive_schedule_yaml"] = str(schedule_rel).replace("\\", "/")
    out_cfg["paths"]["actual_drive_schedule_yaml"] = old_drive_schedule_yaml

    out_cfg.setdefault("simulation", {})
    out_cfg["simulation"]["output_dir"] = str((Path("project_packages") / package_dir.name / "outputs" / "prerace_fullcourse_nominal").as_posix())
    out_cfg["simulation"]["output_prefix"] = out_profile.stem
    out_cfg["simulation"]["latest_manifest_json"] = str((Path("project_packages") / package_dir.name / "outputs" / "prerace_fullcourse_nominal" / "latest_simulation_run.json").as_posix())

    model = out_cfg.setdefault("model", {})
    soc_min = float(model.get("soc_min", 0.1) or 0.1)
    soc_max = float(model.get("soc_max", 0.98) or 0.98)
    out_cfg["simulation"]["soc0"] = round(clip(float(out_cfg["simulation"].get("soc0", soc_max) or soc_max), soc_min, soc_max), 6)

    live = out_cfg.setdefault("live", {})
    autocal = live.setdefault("autocal", {})
    autocal["aux_power_w_init"] = round(float(model.get("P_aux", autocal.get("aux_power_w_init", 0.0)) or 0.0), 6)
    weather = live.setdefault("weather", {})
    weather["tcell_gain"] = round(tcell_gain, 6)

    mpc = out_cfg.setdefault("mpc", {})
    upper_cost = mpc.setdefault("upper_cost", {})
    finish_soc = clip(float(args.finish_soc_target), soc_min, soc_max)
    terminal_weight = float(upper_cost.get("w_soc_terminal", mpc.get("w_soc_terminal", 0.0)) or 0.0)
    if terminal_weight <= 0.0:
        terminal_weight = DEFAULT_TERMINAL_WEIGHT
    mpc["race_km"] = round(planning_race_km, 3)
    mpc["upper_horizon_km"] = round(planning_race_km, 3)
    mpc["soc_finish_target"] = round(finish_soc, 6)
    mpc["w_soc_progress"] = 0.0
    mpc["w_soc_terminal"] = terminal_weight
    upper_cost["w_soc_terminal"] = terminal_weight
    upper_cost["w_uncertainty_reserve"] = 0.0
    upper_cost["reserve_soc_per_hour"] = 0.0
    upper_cost["reserve_soc_max_extra"] = 0.0

    dump_yaml(out_profile, out_cfg)
    print(
        yaml.safe_dump(
            {
                "output_profile": str(out_profile),
                "planning_race_km": planning_race_km,
                "planning_weather_csv": str(planning_weather_abs),
                "control_stop_yaml": str(control_stop_abs),
                "drive_schedule_yaml": str(local_schedule_abs),
                "tcell_gain": tcell_gain,
                "headwind_gain": headwind_gain,
            },
            sort_keys=False,
            allow_unicode=True,
        )
    )


if __name__ == "__main__":
    main()
