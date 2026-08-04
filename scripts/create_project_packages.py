#!/usr/bin/env python3
import csv
import io
import json
import math
import shutil
import urllib.parse
import urllib.request
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / 'project_packages'
CURRENT_PROFILE = ROOT / 'config' / 'solar' / 'bwsc_2027_demo.yaml'
TEMPLATES = ROOT / 'templates'
CURRENT_MAPS = ROOT / 'maps'
IDENT_RAW = ROOT / 'data' / 'identification' / 'raw'
IDENT_OUTPUT = ROOT / 'outputs' / 'identification' / 'vehicle_model_fit.yaml'


PUBLIC_DOCS = [
    {
        'name': '2025_route_notes.pdf',
        'url': 'https://assets.worldsolarchallenge.org/app/uploads/2025/07/13131527/2025-BWSC-Route-Notes-V1-FINAL-PRINT-Published-13072025.pdf',
    },
    {
        'name': '2025_team_managers_guide.pdf',
        'url': 'https://assets.worldsolarchallenge.org/app/uploads/2024/10/04152314/3279_2025_bwsc_team_managers_guide_release_v10_published_05062024_compressed_1.pdf',
    },
    {
        'name': '2025_event_regulations_v2.pdf',
        'url': 'https://assets.worldsolarchallenge.org/app/uploads/2024/12/04154642/3297_2025_bwsc_regulations_release_v20_published_28_october_2024.pdf',
    },
    {
        'name': '2025_official_program.pdf',
        'url': 'https://assets.worldsolarchallenge.org/app/uploads/2025/08/20102713/BWSC-2025-Official-Program-v4.pdf',
    },
]


PUBLIC_WAYPOINTS = [
    {
        'name': 'Darwin',
        'query': 'Darwin, Northern Territory, Australia',
        'fallback_lat': -12.4634,
        'fallback_lon': 130.8456,
        'dist_km': 0.0,
        'anchor_local': '2025-08-24T08:00:00+09:30',
        'source_note': 'BWSC 2025 ceremonial start; anchor for historical weather reconstruction.',
    },
    {
        'name': 'Katherine',
        'query': 'Katherine, Northern Territory, Australia',
        'fallback_lat': -14.4650,
        'fallback_lon': 132.2635,
        'dist_km': 322.0,
        'anchor_local': '2025-08-24T11:00:00+09:30',
        'source_note': 'Control Stop 1 open time and route-note cumulative distance.',
    },
    {
        'name': 'Dunmarra',
        'query': 'Dunmarra, Northern Territory, Australia',
        'fallback_lat': -16.7435,
        'fallback_lon': 133.1240,
        'dist_km': 631.0,
        'anchor_local': '2025-08-24T15:00:00+09:30',
        'source_note': 'Control Stop 2 open time and route-note cumulative distance.',
    },
    {
        'name': 'Tennant Creek',
        'query': 'Tennant Creek, Northern Territory, Australia',
        'fallback_lat': -19.6500,
        'fallback_lon': 134.1916,
        'dist_km': 988.0,
        'anchor_local': '2025-08-25T10:00:00+09:30',
        'source_note': 'Control Stop 3 approximate cumulative distance and official open time.',
    },
    {
        'name': 'Barrow Creek',
        'query': 'Barrow Creek, Northern Territory, Australia',
        'fallback_lat': -21.5343,
        'fallback_lon': 133.8855,
        'dist_km': 1212.3,
        'anchor_local': '2025-08-25T13:00:00+09:30',
        'source_note': 'Control Stop 4 open time and route-note cumulative distance.',
    },
    {
        'name': 'Alice Springs',
        'query': 'Alice Springs, Northern Territory, Australia',
        'fallback_lat': -23.6980,
        'fallback_lon': 133.8807,
        'dist_km': 1496.0,
        'anchor_local': '2025-08-26T08:00:00+09:30',
        'source_note': 'Control Stop 5 open time and route-note cumulative distance.',
    },
    {
        'name': 'Erldunda',
        'query': 'Erldunda, Northern Territory, Australia',
        'fallback_lat': -25.2006,
        'fallback_lon': 133.1990,
        'dist_km': 1694.0,
        'anchor_local': '2025-08-26T11:00:00+09:30',
        'source_note': 'Control Stop 6 open time and route-note cumulative distance.',
    },
    {
        'name': 'Coober Pedy',
        'query': 'Coober Pedy, South Australia, Australia',
        'fallback_lat': -29.0137,
        'fallback_lon': 134.7550,
        'dist_km': 2181.0,
        'anchor_local': '2025-08-26T16:00:00+09:30',
        'source_note': 'Control Stop 7 open time and route-note cumulative distance.',
    },
    {
        'name': 'Glendambo',
        'query': 'Glendambo, South Australia, Australia',
        'fallback_lat': -30.9655,
        'fallback_lon': 135.7491,
        'dist_km': 2434.0,
        'anchor_local': '2025-08-27T10:00:00+09:30',
        'source_note': 'Control Stop 8 open time and route-note cumulative distance.',
    },
    {
        'name': 'Port Augusta',
        'query': 'Port Augusta, South Australia, Australia',
        'fallback_lat': -32.4912,
        'fallback_lon': 137.7650,
        'dist_km': 2720.5,
        'anchor_local': '2025-08-28T15:00:00+09:30',
        'source_note': 'Port Augusta sector handoff reference from route notes; used as a weather anchor.',
    },
    {
        'name': 'Adelaide',
        'query': 'Adelaide, South Australia, Australia',
        'fallback_lat': -34.9285,
        'fallback_lon': 138.6007,
        'dist_km': 3026.9,
        'anchor_local': '2025-08-29T12:00:00+09:30',
        'source_note': 'Victoria Park finish reference from route notes.',
    },
]


PUBLIC_CONTROL_STOPS = [
    {'name': 'Katherine', 's_km': 322.0, 'open_local': '2025-08-24 11:00', 'close_local': '2025-08-24 17:00'},
    {'name': 'Dunmarra', 's_km': 631.0, 'open_local': '2025-08-24 15:00', 'close_local': '2025-08-25 14:00'},
    {'name': 'Tennant Creek', 's_km': 988.0, 'open_local': '2025-08-25 10:00', 'close_local': '2025-08-26 11:00'},
    {'name': 'Barrow Creek', 's_km': 1212.3, 'open_local': '2025-08-25 13:00', 'close_local': '2025-08-26 15:00'},
    {'name': 'Alice Springs', 's_km': 1496.0, 'open_local': '2025-08-26 08:00', 'close_local': '2025-08-27 10:30'},
    {'name': 'Erldunda', 's_km': 1694.0, 'open_local': '2025-08-26 11:00', 'close_local': '2025-08-27 14:00'},
    {'name': 'Coober Pedy', 's_km': 2181.0, 'open_local': '2025-08-26 16:00', 'close_local': '2025-08-28 13:00'},
    {'name': 'Glendambo', 's_km': 2434.0, 'open_local': '2025-08-27 10:00', 'close_local': '2025-08-28 17:00'},
]


WEATHER_HOURLY_VARS = [
    'temperature_2m',
    'shortwave_radiation',
    'wind_speed_10m',
    'wind_direction_10m',
]


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def wipe_and_make(path: Path):
    if path.exists():
        shutil.rmtree(path)
    ensure_dir(path)


def copy_file(src: Path, dst: Path):
    ensure_dir(dst.parent)
    shutil.copy2(src, dst)


def write_text(path: Path, text: str):
    ensure_dir(path.parent)
    path.write_text(text, encoding='utf-8', newline='\n')


def write_yaml(path: Path, payload):
    ensure_dir(path.parent)
    with path.open('w', encoding='utf-8', newline='\n') as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)


def write_csv_rows(path: Path, fieldnames, rows):
    ensure_dir(path.parent)
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def copy_tree_contents(src: Path, dst: Path):
    ensure_dir(dst)
    for item in src.iterdir():
        target = dst / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def fetch_json(url: str):
    req = urllib.request.Request(url, headers={'User-Agent': 'solar-ws-project-builder/1.0'})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def download_binary(url: str, dst: Path):
    ensure_dir(dst.parent)
    req = urllib.request.Request(url, headers={'User-Agent': 'solar-ws-project-builder/1.0'})
    with urllib.request.urlopen(req, timeout=120) as resp:
        dst.write_bytes(resp.read())


def geocode_location(name_query: str, fallback_lat: float, fallback_lon: float):
    params = urllib.parse.urlencode({'name': name_query, 'count': 1, 'language': 'en', 'format': 'json'})
    url = f'https://geocoding-api.open-meteo.com/v1/search?{params}'
    try:
        payload = fetch_json(url)
        results = payload.get('results') or []
        if results:
            result = results[0]
            return float(result['latitude']), float(result['longitude']), result.get('name', name_query)
    except Exception:
        pass
    return float(fallback_lat), float(fallback_lon), name_query


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float):
    lat1r = math.radians(lat1)
    lon1r = math.radians(lon1)
    lat2r = math.radians(lat2)
    lon2r = math.radians(lon2)
    dlon = lon2r - lon1r
    y = math.sin(dlon) * math.cos(lat2r)
    x = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def headwind_component_ms(wind_speed_ms: float, wind_dir_deg: float, course_deg: float):
    # Meteorological direction is where the wind comes from.
    rel = math.radians((wind_dir_deg - course_deg) % 360.0)
    return float(wind_speed_ms * math.cos(rel))


def blend_angle_deg(a_deg: float, b_deg: float, weight_b: float):
    wa = max(0.0, 1.0 - weight_b)
    wb = max(0.0, weight_b)
    ax = wa * math.cos(math.radians(a_deg))
    ay = wa * math.sin(math.radians(a_deg))
    bx = wb * math.cos(math.radians(b_deg))
    by = wb * math.sin(math.radians(b_deg))
    angle = math.degrees(math.atan2(ay + by, ax + bx))
    return (angle + 360.0) % 360.0


def build_template_profile(name: str, purpose: str):
    solar_template = yaml.safe_load((TEMPLATES / 'solar_params_template.yaml').read_text(encoding='utf-8'))
    profile = {
        'meta': {
            'name': name,
            'purpose': purpose,
            'notes': [
                'This package is intentionally blank. Replace route, weather, race, map, model, and network values before operation.',
                'Simulation and live modes are expected to fail until the required CSV and YAML files are filled.',
            ],
        },
        'paths': {
            'route_waypoints_csv': 'data/route/route_waypoints.csv',
            'route_profile_csv': 'data/route/route_profile.csv',
            'speed_profile_csv': 'data/route/speed_profile.csv',
            'forecast_csv': 'data/weather/forecast_10min.csv',
            'stop_yaml': 'data/race/control_stops.yaml',
            'drive_schedule_yaml': 'data/race/drive_schedule.yaml',
            'drive_eff_map': 'maps/drive_eff_map.csv',
            'regen_eff_map': 'maps/regen_eff_map.csv',
            'rint_map': 'maps/rint_map.csv',
            'panel_eff_map': 'maps/panel_eff_map.csv',
            'mppt_eff_map': 'maps/mppt_eff_map.csv',
            'drive_map_eco': 'maps/drive_eff_map_eco.csv',
            'drive_map_power': 'maps/drive_eff_map_power.csv',
            'regen_map_eco': 'maps/regen_eff_map_eco.csv',
            'regen_map_power': 'maps/regen_eff_map_power.csv',
            'ocv_soc_map': 'maps/ocv_soc_curve.csv',
        },
        'runtime': {
            'dashboard_host': '0.0.0.0',
            'dashboard_port': 8080,
            'forecast_time_mode': 'relative',
            'forecast_time_tz': 'Australia/Darwin',
        },
        'logging': {
            'log_dir': 'outputs/logs',
            'log_rate_hz': 2.0,
        },
        'simulation': {
            'gps_rate_hz': 1.0,
            'gps_init_speed_kmh': 45.0,
            'output_dir': 'outputs/prerace',
            'output_prefix': name,
            'auto_version_outputs': True,
            'latest_manifest_json': 'outputs/prerace/latest_simulation_run.json',
            'start_utc': '2027-08-22T22:30:00Z',
            'start_s_km': 0.0,
            'soc0': 0.95,
            'Tb0': 30.0,
            'v0_kmh': 45.0,
            'energy_budget': False,
            'logging': {
                'file_prefix': 'solar_prerace',
            },
        },
        'measurement': {
            'use_distance_node': True,
            'distance': {
                'publish_rate_hz': 2.0,
                'max_dt_sec': 2.5,
            },
            'use_grade_node': True,
            'grade': {
                'gps_topic': '/vehicle/gps',
                'altitude_topic': '/vehicle/altitude_m',
                'min_speed_kmh': 5.0,
                'altitude_alpha': 0.2,
                'min_delta_s_km': 0.01,
            },
            'logging': {
                'file_prefix': 'solar_measurement',
            },
        },
        'identification': {
            'input_dir': 'data/identification/raw',
            'output_dir': 'outputs/identification',
        },
        'live': {
            'use_distance_node': True,
            'distance': {
                'publish_rate_hz': 2.0,
                'max_dt_sec': 2.5,
            },
            'use_grade_node': True,
            'forecast_time_mode': 'absolute',
            'forecast_time_tz': 'Australia/Darwin',
            'grade': {
                'gps_topic': '/vehicle/gps',
                'altitude_topic': '/vehicle/altitude_m',
                'min_speed_kmh': 5.0,
                'altitude_alpha': 0.2,
                'min_delta_s_km': 0.01,
            },
            'weather': {
                'enabled': True,
                'provider': 'openmeteo',
                'gps_topic': '/chase/gps',
                'fetch_period_sec': 3600.0,
                'forecast_days': 3,
                'step_minutes': 10,
                'timezone_name': 'Australia/Darwin',
                'fallback_latitude': -12.4634,
                'fallback_longitude': 130.8456,
                'tcell_gain': 0.03,
                'raw_forecast_csv': 'outputs/runtime/live_forecast_raw.csv',
            },
            'autocal': {
                'enabled': True,
                'publish_period_sec': 30.0,
                'stationary_speed_kmh': 2.0,
                'drive_speed_kmh': 25.0,
                'night_ghi_threshold': 50.0,
                'day_ghi_threshold': 150.0,
                'alpha': 0.2,
                'solar_gain_init': 1.0,
                'drive_power_gain_init': 1.0,
                'aux_power_w_init': 8.0,
                'solar_gain_min': 0.5,
                'solar_gain_max': 1.5,
                'drive_power_gain_min': 0.7,
                'drive_power_gain_max': 1.4,
                'aux_power_w_min': 0.0,
                'aux_power_w_max': 300.0,
            },
            'command_bridge': {
                'enabled': True,
                'output_speed_topic': '/vehicle/speed_cmd_kmh',
                'output_drive_mode_topic': '/vehicle/drive_mode_cmd',
                'udp_enabled': False,
                'udp_host': '127.0.0.1',
                'udp_port': 50050,
                'publish_rate_hz': 5.0,
                'input_timeout_sec': 3.0,
                'safe_speed_kmh': 0.0,
                'startup_hold_sec': 2.0,
                'filter_tau_sec': 1.0,
                'accel_limit_kmhps': 1.2,
                'decel_limit_kmhps': 3.5,
                'speed_deadband_kmh': 0.1,
                'speed_quantize_step_kmh': 0.1,
                'max_output_speed_kmh': 120.0,
                'drive_mode_min_hold_sec': 5.0,
            },
            'wifi_bridge': {
                'enabled': True,
                'enable_inbound': True,
                'enable_outbound': True,
                'bind_host': '0.0.0.0',
                'bind_port': 52001,
                'publish_period_sec': 1.0,
                'solar_remote_host': '192.168.50.21',
                'solar_remote_port': 52002,
                'chase_remote_host': '192.168.50.22',
                'chase_remote_port': 52003,
                'send_to_solar': True,
                'send_to_chase': True,
                'speed_filter_tau_sec': 0.6,
                'speed_max_kmh': 130.0,
                'speed_max_accel_kmhps': 12.0,
                'speed_max_decel_kmhps': 20.0,
                'distance_max_rate_kmps': 0.06,
                'distance_max_backtrack_km': 0.02,
                'battery_filter_tau_sec': 1.0,
                'wind_filter_tau_sec': 1.0,
                'headwind_filter_tau_sec': 0.8,
                'max_abs_headwind_ms': 25.0,
            },
            'wind_model': {
                'enabled': True,
                'corrected_forecast_csv': 'outputs/runtime/live_forecast_corrected.csv',
                'publish_period_sec': 30.0,
                'measurement_sigma_ms': 1.0,
                'correlation_distance_km': 300.0,
                'fallback_correlation_time_h': 3.0,
                'forecast_sigma0_ms': 1.5,
                'forecast_variance_growth_per_hour': 0.05,
                'planning_quantile': 0.5,
                'confidence_z': 1.96,
                'min_sigma_ms': 0.2,
                'preferred_source': 'auto',
                'use_exp_distance_decay': True,
            },
            'logging': {
                'file_prefix': 'solar_live',
            },
        },
        'model': solar_template.get('model', {}),
        'mpc': solar_template.get('mpc', {}),
    }
    profile['mpc'].setdefault('dt', 600.0)
    profile['mpc'].setdefault('horizon_steps', 6)
    profile['mpc'].setdefault('race_km', 3035.5)
    return profile


def blank_bundle_readme(bundle_name: str, profile_rel: str):
    return f"""# {bundle_name}

This package is intentionally blank and is meant to be filled by the team.

## Primary entry point

- Profile: `{profile_rel}`

## What must be replaced

- `data/route/route_waypoints.csv`
- `data/route/route_profile.csv`
- `data/route/speed_profile.csv`
- `data/weather/forecast_10min.csv`
- `data/race/control_stops.yaml`
- `data/race/drive_schedule.yaml`
- `maps/*.csv`
- `model.*` and route-specific `mpc.*` values in `profile.yaml`

## PowerShell examples

```powershell
.\\SolarSim.ps1 -Profile {profile_rel} -Action simulate
.\\SolarSim.ps1 -Profile {profile_rel} -Mode live_wifi -Action up
```

The package is not expected to run successfully until you fill the blank inputs.
"""


def public_bundle_readme(profile_rel: str):
    return f"""# bwsc2025_public

This package is a public-information-filled project bundle for BWSC 2025.

## Included

- Public official PDFs in `docs/official/`
- Public event metadata and control-stop summary in `data/public/bwsc2025_public_info.yaml`
- Historical weather fetched from Open-Meteo archive in `data/weather/`
- A route-weather reconstruction CSV for immediate simulation use
- The current workspace model/MPC defaults frozen into this profile

## Important caveat

The route weather CSV is a public-data reconstruction based on official control-stop anchors and public historical weather. It is useful as a seed, not as ground truth.

## Primary entry point

- Profile: `{profile_rel}`

## PowerShell examples

```powershell
.\\SolarSim.ps1 -Profile {profile_rel} -Action simulate
.\\SolarSim.ps1 -Profile {profile_rel} -Mode live_wifi -Action up
```
"""


def write_blank_inputs(bundle_root: Path):
    route_dir = bundle_root / 'data' / 'route'
    weather_dir = bundle_root / 'data' / 'weather'
    race_dir = bundle_root / 'data' / 'race'
    ident_dir = bundle_root / 'data' / 'identification' / 'raw'
    maps_dir = bundle_root / 'maps'
    ensure_dir(route_dir)
    ensure_dir(weather_dir)
    ensure_dir(race_dir)
    copy_tree_contents(TEMPLATES / 'identification', ident_dir)

    write_text(route_dir / 'route_waypoints.csv', 'lat,lon,dist_km\n')
    write_text(route_dir / 'route_profile.csv', 'dist_km,slope_pct,headwind_ms\n')
    write_text(route_dir / 'speed_profile.csv', 'dist_km,v_max_kmh\n')
    write_text(weather_dir / 'forecast_10min.csv', 'time,GHI,Tamb_C,Tcell_C,headwind_ms,wind_dir_deg\n')
    write_yaml(race_dir / 'control_stops.yaml', {'stops': []})
    write_yaml(race_dir / 'drive_schedule.yaml', {'deny_by_default': False, 'drive_windows': [], 'daily_windows': []})

    copy_file(TEMPLATES / 'drive_eff_map_template.csv', maps_dir / 'drive_eff_map.csv')
    copy_file(TEMPLATES / 'drive_eff_map_template.csv', maps_dir / 'drive_eff_map_eco.csv')
    copy_file(TEMPLATES / 'drive_eff_map_template.csv', maps_dir / 'drive_eff_map_power.csv')
    copy_file(TEMPLATES / 'regen_eff_map_template.csv', maps_dir / 'regen_eff_map.csv')
    copy_file(TEMPLATES / 'regen_eff_map_template.csv', maps_dir / 'regen_eff_map_eco.csv')
    copy_file(TEMPLATES / 'regen_eff_map_template.csv', maps_dir / 'regen_eff_map_power.csv')
    copy_file(TEMPLATES / 'rint_map_template.csv', maps_dir / 'rint_map.csv')
    copy_file(TEMPLATES / 'panel_eff_map_template.csv', maps_dir / 'panel_eff_map.csv')
    copy_file(TEMPLATES / 'mppt_eff_map_template.csv', maps_dir / 'mppt_eff_map.csv')
    copy_file(TEMPLATES / 'ocv_soc_curve_template.csv', maps_dir / 'ocv_soc_curve.csv')


def fetch_waypoint_weather(lat: float, lon: float):
    params = {
        'latitude': lat,
        'longitude': lon,
        'start_date': '2025-08-24',
        'end_date': '2025-08-30',
        'hourly': ','.join(WEATHER_HOURLY_VARS),
        'timezone': 'Australia/Darwin',
    }
    url = 'https://archive-api.open-meteo.com/v1/archive?' + urllib.parse.urlencode(params)
    payload = fetch_json(url)
    hourly = payload['hourly']
    df = pd.DataFrame(hourly)
    df['time_local'] = pd.to_datetime(df['time'])
    df['time_utc'] = df['time_local'].dt.tz_localize('Australia/Darwin').dt.tz_convert('UTC')
    return df


def build_public_route_weather(waypoints):
    expanded = []
    per_waypoint_frames = []
    for item in waypoints:
        df = fetch_waypoint_weather(item['lat'], item['lon'])
        df = df.rename(
            columns={
                'temperature_2m': 'Tamb_C',
                'shortwave_radiation': 'GHI',
                'wind_speed_10m': 'wind_speed_ms',
                'wind_direction_10m': 'wind_dir_deg',
            }
        )
        df['waypoint_name'] = item['name']
        df['dist_km'] = item['dist_km']
        per_waypoint_frames.append(df.copy())
        ten = df.set_index('time_utc')[['Tamb_C', 'GHI', 'wind_speed_ms', 'wind_dir_deg']].resample('10min').interpolate(method='time').ffill().bfill()
        expanded.append((item, ten))

    start = pd.Timestamp(waypoints[0]['anchor_local']).tz_convert('UTC')
    end = pd.Timestamp(waypoints[-1]['anchor_local']).tz_convert('UTC')
    times = pd.date_range(start, end, freq='10min', tz='UTC')
    rows = []
    for ts in times:
        seg_idx = None
        for i in range(len(waypoints) - 1):
            t0 = pd.Timestamp(waypoints[i]['anchor_local']).tz_convert('UTC')
            t1 = pd.Timestamp(waypoints[i + 1]['anchor_local']).tz_convert('UTC')
            if t0 <= ts <= t1:
                seg_idx = i
                break
        if seg_idx is None:
            seg_idx = len(waypoints) - 2
        w0 = waypoints[seg_idx]
        w1 = waypoints[seg_idx + 1]
        t0 = pd.Timestamp(w0['anchor_local']).tz_convert('UTC')
        t1 = pd.Timestamp(w1['anchor_local']).tz_convert('UTC')
        alpha = 0.0 if t1 <= t0 else float((ts - t0) / (t1 - t0))
        alpha = min(1.0, max(0.0, alpha))

        df0 = expanded[seg_idx][1]
        df1 = expanded[seg_idx + 1][1]
        row0 = df0.loc[ts]
        row1 = df1.loc[ts]
        dist_km = (1.0 - alpha) * w0['dist_km'] + alpha * w1['dist_km']
        tamb = (1.0 - alpha) * float(row0['Tamb_C']) + alpha * float(row1['Tamb_C'])
        ghi = (1.0 - alpha) * float(row0['GHI']) + alpha * float(row1['GHI'])
        wind_speed = (1.0 - alpha) * float(row0['wind_speed_ms']) + alpha * float(row1['wind_speed_ms'])
        wind_dir = blend_angle_deg(float(row0['wind_dir_deg']), float(row1['wind_dir_deg']), alpha)
        course = bearing_deg(w0['lat'], w0['lon'], w1['lat'], w1['lon'])
        headwind = headwind_component_ms(wind_speed, wind_dir, course)
        rows.append(
            {
                'time': ts.strftime('%Y-%m-%dT%H:%M:%SZ'),
                'GHI': round(ghi, 6),
                'Tamb_C': round(tamb, 6),
                'Tcell_C': round(tamb + 0.03 * ghi, 6),
                'headwind_ms': round(headwind, 6),
                'wind_dir_deg': round(wind_dir, 6),
                'route_heading_deg': round(course, 6),
                'route_progress_km': round(dist_km, 6),
                'anchor_from': w0['name'],
                'anchor_to': w1['name'],
            }
        )
    weather_long = pd.concat(per_waypoint_frames, ignore_index=True)
    weather_long['time_local'] = weather_long['time_local'].dt.strftime('%Y-%m-%dT%H:%M:%S')
    weather_long['time_utc'] = weather_long['time_utc'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return rows, weather_long


def build_public_profile():
    cfg = yaml.safe_load(CURRENT_PROFILE.read_text(encoding='utf-8'))
    cfg = deepcopy(cfg)
    cfg['meta']['name'] = 'bwsc2025_public'
    cfg['meta']['purpose'] = 'Public-information-filled BWSC 2025 package with official documents and historical weather.'
    cfg['meta']['notes'] = [
        'This package keeps the current workspace model/MPC defaults and augments them with public BWSC 2025 references and historical weather.',
        'Route weather is a reconstruction based on official control-stop anchors and public weather archives; replace with richer route truth if available.',
    ]
    cfg['paths'] = {
        'route_waypoints_csv': 'data/route/bwsc2025_public_major_waypoints.csv',
        'route_profile_csv': 'data/route/bwsc2025_public_route_profile.csv',
        'speed_profile_csv': 'data/route/bwsc2025_public_speed_profile.csv',
        'forecast_csv': 'data/weather/bwsc2025_route_history_10min.csv',
        'stop_yaml': 'data/race/bwsc2025_simulation_stops.yaml',
        'drive_schedule_yaml': 'data/race/bwsc2025_drive_schedule.yaml',
        'drive_eff_map': 'maps/drive_eff_map.csv',
        'regen_eff_map': 'maps/regen_eff_map.csv',
        'rint_map': 'maps/Rint_T_by_soc.csv',
        'panel_eff_map': 'maps/panel_eff_map.csv',
        'mppt_eff_map': 'maps/mppt_eff_map.csv',
        'drive_map_eco': 'maps/drive_eff_map_eco.csv',
        'drive_map_power': 'maps/drive_eff_map_power.csv',
        'regen_map_eco': 'maps/regen_eff_map_eco.csv',
        'regen_map_power': 'maps/regen_eff_map_power.csv',
        'ocv_soc_map': '',
    }
    cfg['simulation']['output_prefix'] = 'bwsc2025_public'
    return cfg


def create_public_bundle(bundle_root: Path):
    ensure_dir(bundle_root)
    ensure_dir(bundle_root / 'docs' / 'official')
    ensure_dir(bundle_root / 'data' / 'public')
    ensure_dir(bundle_root / 'data' / 'route')
    ensure_dir(bundle_root / 'data' / 'weather')
    ensure_dir(bundle_root / 'data' / 'race')
    ensure_dir(bundle_root / 'maps')
    ensure_dir(bundle_root / 'outputs' / 'identification')

    for doc in PUBLIC_DOCS:
        download_binary(doc['url'], bundle_root / 'docs' / 'official' / doc['name'])

    waypoints = []
    for item in PUBLIC_WAYPOINTS:
        lat, lon, geocode_name = geocode_location(item['query'], item['fallback_lat'], item['fallback_lon'])
        built = dict(item)
        built['lat'] = lat
        built['lon'] = lon
        built['geocode_name'] = geocode_name
        waypoints.append(built)

    route_rows = [{'lat': wp['lat'], 'lon': wp['lon'], 'dist_km': wp['dist_km']} for wp in waypoints]
    write_csv_rows(bundle_root / 'data' / 'route' / 'bwsc2025_public_major_waypoints.csv', ['lat', 'lon', 'dist_km'], route_rows)

    route_profile_rows = [{'dist_km': wp['dist_km'], 'slope_pct': 0.0, 'headwind_ms': 0.0} for wp in waypoints]
    write_csv_rows(bundle_root / 'data' / 'route' / 'bwsc2025_public_route_profile.csv', ['dist_km', 'slope_pct', 'headwind_ms'], route_profile_rows)

    speed_rows = [
        {'dist_km': 0.0, 'v_max_kmh': 110.0},
        {'dist_km': route_rows[-1]['dist_km'], 'v_max_kmh': 110.0},
    ]
    write_csv_rows(bundle_root / 'data' / 'route' / 'bwsc2025_public_speed_profile.csv', ['dist_km', 'v_max_kmh'], speed_rows)

    weather_rows, weather_long = build_public_route_weather(waypoints)
    write_csv_rows(
        bundle_root / 'data' / 'weather' / 'bwsc2025_route_history_10min.csv',
        ['time', 'GHI', 'Tamb_C', 'Tcell_C', 'headwind_ms', 'wind_dir_deg', 'route_heading_deg', 'route_progress_km', 'anchor_from', 'anchor_to'],
        weather_rows,
    )
    weather_long.to_csv(bundle_root / 'data' / 'weather' / 'bwsc2025_waypoint_history_hourly.csv', index=False)

    write_yaml(bundle_root / 'data' / 'race' / 'bwsc2025_simulation_stops.yaml', {'stops': []})
    write_yaml(
        bundle_root / 'data' / 'race' / 'bwsc2025_drive_schedule.yaml',
        {
            'deny_by_default': True,
            'daily_windows': [
                {
                    'start_local': '08:00',
                    'end_local': '17:00',
                    'tz': 'Australia/Darwin',
                    'v_min_kmh': 0.0,
                    'v_max_kmh': 110.0,
                }
            ],
        },
    )

    public_info = {
        'event': {
            'name': 'Bridgestone World Solar Challenge 2025',
            'route': 'Darwin to Adelaide',
            'distance_km_public': 3020.0,
            'route_finish_ref_km': 3026.9,
            'timezone_primary': 'Australia/Darwin',
            'notes': [
                'The official route notes were published 13 July 2025.',
                'The route-weather CSV is a reconstruction from public control-stop anchors and Open-Meteo archive data.',
            ],
        },
        'sources': PUBLIC_DOCS + [
            {'name': 'bwsc_route_map', 'url': 'https://worldsolarchallenge.org/about-us/route-map'},
            {'name': 'bwsc_history', 'url': 'https://worldsolarchallenge.org/about-us/history'},
            {'name': 'open_meteo_archive', 'url': 'https://archive-api.open-meteo.com/v1/archive'},
            {'name': 'open_meteo_geocoding', 'url': 'https://geocoding-api.open-meteo.com/v1/search'},
        ],
        'control_stops_public': PUBLIC_CONTROL_STOPS,
        'major_waypoints_public': [
            {
                'name': wp['name'],
                'dist_km': wp['dist_km'],
                'lat': wp['lat'],
                'lon': wp['lon'],
                'anchor_local': wp['anchor_local'],
                'source_note': wp['source_note'],
            }
            for wp in waypoints
        ],
        'generated_utc': datetime.now(timezone.utc).isoformat(),
    }
    write_yaml(bundle_root / 'data' / 'public' / 'bwsc2025_public_info.yaml', public_info)

    public_sources_md = io.StringIO()
    public_sources_md.write('# BWSC 2025 public sources\n\n')
    public_sources_md.write('This bundle stores public documents and machine-readable summaries gathered during package generation.\n\n')
    public_sources_md.write('## Official downloads\n\n')
    for doc in PUBLIC_DOCS:
        public_sources_md.write(f'- `{doc["name"]}`: {doc["url"]}\n')
    public_sources_md.write('\n## Other public references\n\n')
    public_sources_md.write('- Route map: https://worldsolarchallenge.org/about-us/route-map\n')
    public_sources_md.write('- History / results landing page: https://worldsolarchallenge.org/about-us/history\n')
    public_sources_md.write('- Weather archive API: https://archive-api.open-meteo.com/v1/archive\n')
    public_sources_md.write('- Geocoding API: https://geocoding-api.open-meteo.com/v1/search\n')
    write_text(bundle_root / 'docs' / 'public_sources.md', public_sources_md.getvalue())

    for name in [
        'drive_eff_map.csv',
        'drive_eff_map_eco.csv',
        'drive_eff_map_power.csv',
        'regen_eff_map.csv',
        'regen_eff_map_eco.csv',
        'regen_eff_map_power.csv',
        'Rint_T_by_soc.csv',
        'panel_eff_map.csv',
        'mppt_eff_map.csv',
    ]:
        copy_file(CURRENT_MAPS / name, bundle_root / 'maps' / name)

    if IDENT_OUTPUT.exists():
        copy_file(IDENT_OUTPUT, bundle_root / 'outputs' / 'identification' / 'vehicle_model_fit.yaml')

    profile = build_public_profile()
    write_yaml(bundle_root / 'profile.yaml', profile)
    write_text(bundle_root / 'README.md', public_bundle_readme('project_packages/bwsc2025_public/profile.yaml'))


def create_blank_bundle(bundle_root: Path, bundle_name: str, purpose: str):
    ensure_dir(bundle_root)
    write_blank_inputs(bundle_root)
    write_yaml(bundle_root / 'profile.yaml', build_template_profile(bundle_name, purpose))
    write_text(bundle_root / 'README.md', blank_bundle_readme(bundle_name, f'project_packages/{bundle_name}/profile.yaml'))


def write_index():
    text = """# Project packages

This directory contains three self-contained profile bundles:

- `bwsc2027_template`: blank BWSC 2027 template
- `bwsc2025_public`: BWSC 2025 bundle with public documents and historical weather
- `other_template`: blank non-BWSC template

Use them via `-Profile`:

```powershell
.\\SolarSim.ps1 -Profile project_packages/bwsc2027_template/profile.yaml -Action simulate
.\\SolarSim.ps1 -Profile project_packages/bwsc2025_public/profile.yaml -Action simulate
.\\SolarSim.ps1 -Profile project_packages/other_template/profile.yaml -Action simulate
```
"""
    write_text(OUT_ROOT / 'README.md', text)


def main():
    wipe_and_make(OUT_ROOT)
    create_blank_bundle(OUT_ROOT / 'bwsc2027_template', 'bwsc2027_template', 'Blank BWSC 2027 template package.')
    create_public_bundle(OUT_ROOT / 'bwsc2025_public')
    create_blank_bundle(OUT_ROOT / 'other_template', 'other_template', 'Blank generic template package.')
    write_index()
    print(f'created packages under: {OUT_ROOT}')


if __name__ == '__main__':
    main()
