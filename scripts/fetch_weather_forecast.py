#!/usr/bin/env python3
import argparse
import os

import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート



def main():                                                        # [メイン関数] エントリーポイント関数
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile_yaml', required=True)
    ap.add_argument('--latitude', type=float, default=None)
    ap.add_argument('--longitude', type=float, default=None)
    ap.add_argument('--out_csv', default='')
    ap.add_argument('--forecast_days', type=int, default=None)
    ap.add_argument('--step_minutes', type=int, default=None)
    ap.add_argument('--timezone_name', default=None)
    ap.add_argument('--tcell_gain', type=float, default=None)
    args = ap.parse_args()

    profile_path, cfg = load_profile(args.profile_yaml)
    runtime_cfg = get_section(cfg, 'runtime')
    live_cfg = get_section(cfg, 'live')
    weather_cfg = merged_dict({
        'forecast_days': 3,
        'step_minutes': 10,
        'timezone_name': 'Australia/Darwin',
        'fallback_latitude': live_cfg.get('fallback_latitude', None),
        'fallback_longitude': live_cfg.get('fallback_longitude', None),
        'tcell_gain': 0.03,
    }, get_section(live_cfg, 'weather'))
    if not weather_cfg.get('timezone_name'):
        weather_cfg['timezone_name'] = str(live_cfg.get('forecast_time_tz', runtime_cfg.get('forecast_time_tz', 'Australia/Darwin')))
    if args.forecast_days is not None:
        weather_cfg['forecast_days'] = args.forecast_days
    if args.step_minutes is not None:
        weather_cfg['step_minutes'] = args.step_minutes
    if args.timezone_name is not None:
        weather_cfg['timezone_name'] = args.timezone_name
    if args.tcell_gain is not None:
        weather_cfg['tcell_gain'] = args.tcell_gain

    out_csv = args.out_csv or get_path(cfg, profile_path, 'forecast_csv')
    route_csv = get_path(cfg, profile_path, 'route_waypoints_csv')
    if args.latitude is None or args.longitude is None:
        if route_csv and os.path.exists(route_csv):
            route_df = pd.read_csv(route_csv)
            lat = float(route_df.iloc[0]['lat'])
            lon = float(route_df.iloc[0]['lon'])
        else:
            lat = float(weather_cfg.get('fallback_latitude', -12.4634))
            lon = float(weather_cfg.get('fallback_longitude', 130.8456))
    else:
        lat = float(args.latitude)
        lon = float(args.longitude)

    df = fetch_openmeteo_forecast(
        lat,
        lon,
        timezone_name=str(weather_cfg.get('timezone_name', 'Australia/Darwin')),
        forecast_days=int(weather_cfg.get('forecast_days', 3)),
        step_minutes=int(weather_cfg.get('step_minutes', 10)),
        tcell_gain=float(weather_cfg.get('tcell_gain', 0.03)),
    )
    os.makedirs(os.path.dirname(os.path.abspath(out_csv)), exist_ok=True)
    write_forecast_csv(df, out_csv)
    print(f'forecast saved: {out_csv}')


if __name__ == '__main__':                                         # [直接実行スクリプト] スクリプト直接起動時のメイン実行ブロック
    main()

# =============================================================================
# 【統合ユーティリティ】Open-Meteo 気象取得・風速風向成分計算関数群
# =============================================================================
import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


OPENMETEO_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'


def _fetch_json(url: str, timeout_sec: float = 20.0) -> Dict:      # [関数定義] _fetch_json の処理実行ブロック
    req = urllib.request.Request(url, headers={'User-Agent': 'solarcar-weather-fetch/1.0'})
    with urllib.request.urlopen(req, timeout=timeout_sec) as res:
        return json.loads(res.read().decode('utf-8'))              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_openmeteo_url(latitude: float, longitude: float, timezone_name: str, forecast_days: int) -> str:  # [関数定義] build_openmeteo_url の処理実行ブロック
    params = {
        'latitude': f'{latitude:.6f}',
        'longitude': f'{longitude:.6f}',
        'timezone': timezone_name,
        'forecast_days': str(max(1, int(forecast_days))),
        'hourly': 'temperature_2m,shortwave_radiation,windspeed_10m,winddirection_10m',
    }
    return OPENMETEO_FORECAST_URL + '?' + urllib.parse.urlencode(params)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def wrap_angle_deg(angle_deg: float) -> float:                     # [関数定義] wrap_angle_deg の処理実行ブロック
    return float((float(angle_deg) + 360.0) % 360.0)               # [戻り値] 計算結果・計算状態の呼び出し元への返却


def signed_angle_diff_deg(a_deg: float, b_deg: float) -> float:    # [関数定義] signed_angle_diff_deg の処理実行ブロック
    return float((float(a_deg) - float(b_deg) + 180.0) % 360.0 - 180.0)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def meteo_headwind_component_ms(wind_speed_ms: float, wind_from_deg: float, heading_deg: float) -> float:  # [関数定義] meteo_headwind_component_ms の処理実行ブロック
    """Project a meteorological wind direction onto the route heading.

    `wind_from_deg` follows the usual convention: the direction the wind is coming from,
    measured clockwise from north. Positive output means headwind, negative means tailwind.
    """
    if not math.isfinite(float(wind_speed_ms)):
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if not math.isfinite(float(wind_from_deg)) or not math.isfinite(float(heading_deg)):
        return float(wind_speed_ms)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = math.radians(signed_angle_diff_deg(float(wind_from_deg), float(heading_deg)))
    return float(wind_speed_ms) * math.cos(delta)                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fetch_openmeteo_forecast(                                      # [関数定義] fetch_openmeteo_forecast の処理実行ブロック
    latitude: float,
    longitude: float,
    timezone_name: str = 'UTC',
    forecast_days: int = 3,
    step_minutes: int = 10,
    tcell_gain: float = 0.03,
    timeout_sec: float = 20.0,
) -> pd.DataFrame:
    url = build_openmeteo_url(latitude, longitude, timezone_name, forecast_days)
    payload = _fetch_json(url, timeout_sec=timeout_sec)
    hourly = payload.get('hourly', {})
    times = hourly.get('time', [])
    ghi = hourly.get('shortwave_radiation', [])
    temp = hourly.get('temperature_2m', [])
    wind_kmh = hourly.get('windspeed_10m', [])
    wind_dir = hourly.get('winddirection_10m', [])
    rows: List[Dict] = []
    for idx, t_str in enumerate(times):
        try:
            t_local = datetime.fromisoformat(t_str)
            if t_local.tzinfo is None:
                t_local = t_local.replace(tzinfo=timezone.utc)
            t_utc = t_local.astimezone(timezone.utc)
        except Exception:
            continue
        g = float(ghi[idx]) if idx < len(ghi) and ghi[idx] is not None else 0.0
        tamb = float(temp[idx]) if idx < len(temp) and temp[idx] is not None else 25.0
        w_kmh = float(wind_kmh[idx]) if idx < len(wind_kmh) and wind_kmh[idx] is not None else 0.0
        w_dir = float(wind_dir[idx]) if idx < len(wind_dir) and wind_dir[idx] is not None else 0.0
        w_ms = w_kmh / 3.6
        rows.append({
            'time': t_utc.isoformat(),
            'GHI': g,
            'Tamb_C': tamb,
            'Tcell_C': tamb + max(0.0, g) * float(tcell_gain),
            'wind_speed_ms': w_ms,
            'wind_dir_deg': wrap_angle_deg(w_dir),
            # Raw forecast does not know the actual route heading at this stage.
            # Keep the direct headwind input neutral and let the wind correction node
            # project the forecast onto the route before the planner consumes it.
            'headwind_ms': 0.0,
        })

    df = pd.DataFrame(rows)
    if df.empty or step_minutes >= 60:
        return df                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    if df.empty:
        return df.reset_index(drop=False)                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    target_index = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq=f'{int(step_minutes)}min',
        tz='UTC',
    )
    df = df.reindex(df.index.union(target_index)).interpolate(method='time').reindex(target_index)
    df = df.reset_index().rename(columns={'index': 'time'})
    df['time'] = df['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return df                                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_forecast_csv(df: pd.DataFrame, out_csv: str):            # [関数定義] write_forecast_csv の処理実行ブロック
    if df is None:
        raise ValueError('Forecast dataframe is None')
    df.to_csv(out_csv, index=False)


import os
from pathlib import Path

try:
    from ament_index_python.packages import get_package_share_directory  # type: ignore
except Exception:  # pragma: no cover - non-ROS fallback
    get_package_share_directory = None


PKG_NAME = 'mpc_solarcar'
REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(path: str, default_subdir: str = '') -> str:      # [関数定義] resolve_path の処理実行ブロック
    """Resolve a path relative to CWD or package share.

    - If absolute, return as-is.                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - If exists relative to CWD, return it.                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - Otherwise, resolve under <pkg_share>/<default_subdir> (or directly under share).
    """
    if path is None:
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.exists(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if get_package_share_directory is not None:
        pkg_share = get_package_share_directory(PKG_NAME)
    else:
        pkg_share = os.fspath(REPO_ROOT)
    if default_subdir:
        subdir = default_subdir.strip('/\\')
        if path.startswith(subdir + os.sep) or path == subdir:
            return os.path.join(pkg_share, path)                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return os.path.join(pkg_share, subdir, path)               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return os.path.join(pkg_share, path)                           # [戻り値] 計算結果・計算状態の呼び出し元への返却