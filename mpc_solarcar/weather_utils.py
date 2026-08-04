import json
import math
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd


OPENMETEO_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'


def _fetch_json(url: str, timeout_sec: float = 20.0) -> Dict:
    req = urllib.request.Request(url, headers={'User-Agent': 'solarcar-weather-fetch/1.0'})
    with urllib.request.urlopen(req, timeout=timeout_sec) as res:
        return json.loads(res.read().decode('utf-8'))


def build_openmeteo_url(latitude: float, longitude: float, timezone_name: str, forecast_days: int) -> str:
    params = {
        'latitude': f'{latitude:.6f}',
        'longitude': f'{longitude:.6f}',
        'timezone': timezone_name,
        'forecast_days': str(max(1, int(forecast_days))),
        'hourly': 'temperature_2m,shortwave_radiation,windspeed_10m,winddirection_10m',
    }
    return OPENMETEO_FORECAST_URL + '?' + urllib.parse.urlencode(params)


def wrap_angle_deg(angle_deg: float) -> float:
    return float((float(angle_deg) + 360.0) % 360.0)


def signed_angle_diff_deg(a_deg: float, b_deg: float) -> float:
    return float((float(a_deg) - float(b_deg) + 180.0) % 360.0 - 180.0)


def meteo_headwind_component_ms(wind_speed_ms: float, wind_from_deg: float, heading_deg: float) -> float:
    """Project a meteorological wind direction onto the route heading.

    `wind_from_deg` follows the usual convention: the direction the wind is coming from,
    measured clockwise from north. Positive output means headwind, negative means tailwind.
    """
    if not math.isfinite(float(wind_speed_ms)):
        return 0.0
    if not math.isfinite(float(wind_from_deg)) or not math.isfinite(float(heading_deg)):
        return float(wind_speed_ms)
    delta = math.radians(signed_angle_diff_deg(float(wind_from_deg), float(heading_deg)))
    return float(wind_speed_ms) * math.cos(delta)


def fetch_openmeteo_forecast(
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
        return df

    df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    if df.empty:
        return df.reset_index(drop=False)

    target_index = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq=f'{int(step_minutes)}min',
        tz='UTC',
    )
    df = df.reindex(df.index.union(target_index)).interpolate(method='time').reindex(target_index)
    df = df.reset_index().rename(columns={'index': 'time'})
    df['time'] = df['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return df


def write_forecast_csv(df: pd.DataFrame, out_csv: str):
    if df is None:
        raise ValueError('Forecast dataframe is None')
    df.to_csv(out_csv, index=False)
