from __future__ import annotations

import shutil
from pathlib import Path

from launch_ros.actions import Node

from .solar_profile import (
    ensure_live_release_allowed,
    get_path,
    get_section,
    resolve_relative_path,
)


def cfg_path(profile_path, raw: str) -> str:
    return resolve_relative_path(profile_path.parent, raw) if str(raw or "").strip() else ""


def _drop_keys(payload: dict, *keys: str) -> dict:
    blocked = set(keys)
    return {key: value for key, value in (payload or {}).items() if key not in blocked}


def live_forecast_paths(profile_path, cfg):
    live_cfg = get_section(cfg, "live")
    weather_cfg = get_section(live_cfg, "weather")
    wind_cfg = get_section(live_cfg, "wind_model")
    base_path = get_path(cfg, profile_path, "forecast_csv")
    raw_path = cfg_path(profile_path, str(weather_cfg.get("raw_forecast_csv", "")))
    if not raw_path:
        raw_path = cfg_path(profile_path, "outputs/runtime/live_forecast_raw.csv")
    corrected_path = cfg_path(profile_path, str(wind_cfg.get("corrected_forecast_csv", "")))
    if not corrected_path:
        corrected_path = cfg_path(profile_path, "outputs/runtime/live_forecast_corrected.csv")
    for runtime_path in (raw_path, corrected_path):
        target = Path(runtime_path)
        if not target.exists() and Path(base_path).exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(base_path, target)
    return base_path, raw_path, corrected_path


def build_live_nodes(profile_path, cfg, *, use_wifi: bool):
    ensure_live_release_allowed(cfg, profile_path)
    runtime_cfg = get_section(cfg, "runtime")
    logging_cfg = get_section(cfg, "logging")
    live_cfg = get_section(cfg, "live")
    weather_cfg = get_section(live_cfg, "weather")
    autocal_cfg = get_section(live_cfg, "autocal")
    command_cfg = get_section(live_cfg, "command_bridge")
    distance_cfg = get_section(live_cfg, "distance")
    grade_cfg = get_section(live_cfg, "grade")
    wind_cfg = get_section(live_cfg, "wind_model")
    live_logging_cfg = get_section(live_cfg, "logging")
    preflight_cfg = get_section(live_cfg, "preflight")

    base_forecast_csv, raw_forecast_csv, corrected_forecast_csv = live_forecast_paths(profile_path, cfg)
    mpc_forecast_csv = raw_forecast_csv
    if use_wifi and bool(wind_cfg.get("enabled", True)):
        mpc_forecast_csv = corrected_forecast_csv

    nodes = [
        Node(
            package="mpc_solarcar",
            executable="solar_preflight_node",
            name="solar_preflight_node",
            parameters=[
                {
                    "require_speed": True,
                    "require_distance": True,
                    "require_battery": True,
                    "require_planner": True,
                    **preflight_cfg,
                }
            ],
        ),
        Node(
            package="mpc_solarcar",
            executable="mpc_node",
            name="mpc_node",
            parameters=[
                {
                    "forecast_csv": mpc_forecast_csv,
                    "route_profile_csv": get_path(cfg, profile_path, "route_profile_csv"),
                    "speed_profile_csv": get_path(cfg, profile_path, "speed_profile_csv"),
                    "stop_yaml": get_path(cfg, profile_path, "stop_yaml"),
                    "drive_schedule_yaml": get_path(cfg, profile_path, "drive_schedule_yaml"),
                    "initial_upper_policy_csv": get_path(cfg, profile_path, "initial_upper_policy_csv"),
                    "drive_eff_map": get_path(cfg, profile_path, "drive_eff_map"),
                    "regen_eff_map": get_path(cfg, profile_path, "regen_eff_map"),
                    "rint_map": get_path(cfg, profile_path, "rint_map"),
                    "r1_map": get_path(cfg, profile_path, "r1_map"),
                    "tau_map": get_path(cfg, profile_path, "tau_map"),
                    "panel_eff_map": get_path(cfg, profile_path, "panel_eff_map"),
                    "mppt_eff_map": get_path(cfg, profile_path, "mppt_eff_map"),
                    "drive_map_eco": get_path(cfg, profile_path, "drive_map_eco"),
                    "drive_map_power": get_path(cfg, profile_path, "drive_map_power"),
                    "regen_map_eco": get_path(cfg, profile_path, "regen_map_eco"),
                    "regen_map_power": get_path(cfg, profile_path, "regen_map_power"),
                    "ocv_soc_map": get_path(cfg, profile_path, "ocv_soc_map"),
                    "params_yaml": str(profile_path),
                    "profile_runtime_mode": "live",
                    "forecast_time_mode": str(live_cfg.get("forecast_time_mode", runtime_cfg.get("forecast_time_mode", "absolute"))),
                    "forecast_time_tz": str(live_cfg.get("forecast_time_tz", runtime_cfg.get("forecast_time_tz", "Australia/Darwin"))),
                    "forecast_start_time_utc": str(get_section(cfg, "simulation").get("forecast_start_time_utc", get_section(cfg, "simulation").get("start_utc", ""))),
                }
            ],
        ),
        Node(
            package="mpc_solarcar",
            executable="dashboard_node",
            name="dashboard_node",
            parameters=[
                {
                    "host": str(runtime_cfg.get("dashboard_host", "0.0.0.0")),
                    "port": int(runtime_cfg.get("dashboard_port", 8080)),
                }
            ],
        ),
        Node(
            package="mpc_solarcar",
            executable="solar_logger_node",
            name="solar_logger_node",
            parameters=[
                {
                    "log_dir": cfg_path(profile_path, str(logging_cfg.get("log_dir", "outputs/logs"))),
                    "file_prefix": str(live_logging_cfg.get("file_prefix", "solar_live")),
                    "log_rate_hz": float(logging_cfg.get("log_rate_hz", 2.0)),
                    "output_speed_topic": str(command_cfg.get("output_speed_topic", "/vehicle/speed_cmd_kmh")),
                    "output_drive_mode_topic": str(command_cfg.get("output_drive_mode_topic", "/vehicle/drive_mode_cmd")),
                }
            ],
        ),
    ]

    if bool(command_cfg.get("enabled", True)):
        nodes.append(
            Node(
                package="mpc_solarcar",
                executable="speed_command_bridge_node",
                name="speed_command_bridge_node",
                parameters=[_drop_keys(command_cfg, "enabled")],
            )
        )

    if bool(live_cfg.get("use_distance_node", True)):
        nodes.append(Node(package="mpc_solarcar", executable="distance_node", name="distance_node", parameters=[distance_cfg]))
    if bool(live_cfg.get("use_grade_node", True)):
        nodes.append(Node(package="mpc_solarcar", executable="grade_node", name="grade_node", parameters=[grade_cfg]))
    if bool(weather_cfg.get("enabled", True)):
        nodes.append(
            Node(
                package="mpc_solarcar",
                executable="weather_fetch_node",
                name="weather_fetch_node",
                parameters=[
                    {
                        "profile_yaml": str(profile_path),
                        "output_csv": raw_forecast_csv,
                        "raw_forecast_csv": "",
                        "gps_topic": str(weather_cfg.get("gps_topic", "/chase/gps")),
                        "fetch_period_sec": float(weather_cfg.get("fetch_period_sec", 3600.0)),
                        "forecast_days": int(weather_cfg.get("forecast_days", 3)),
                        "step_minutes": int(weather_cfg.get("step_minutes", 10)),
                        "timezone_name": str(weather_cfg.get("timezone_name", live_cfg.get("forecast_time_tz", "Australia/Darwin"))),
                        "fallback_latitude": float(weather_cfg.get("fallback_latitude", -12.4634)),
                        "fallback_longitude": float(weather_cfg.get("fallback_longitude", 130.8456)),
                        "tcell_gain": float(weather_cfg.get("tcell_gain", 0.03)),
                    }
                ],
            )
        )
    if bool(autocal_cfg.get("enabled", True)):
        nodes.append(
            Node(
                package="mpc_solarcar",
                executable="solar_autocal_node",
                name="solar_autocal_node",
                parameters=[_drop_keys(autocal_cfg, "enabled")],
            )
        )
    return nodes
