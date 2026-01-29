import numpy as np
import pandas as pd


def _interp_field(d, y, s_km, default=0.0):
    if len(d) < 2:
        return float(default)
    s = np.clip(s_km, d[0], d[-1])
    i = np.searchsorted(d, s) - 1
    i = np.clip(i, 0, len(d) - 2)
    t = 0.0 if d[i + 1] == d[i] else (s - d[i]) / (d[i + 1] - d[i])
    return float((1 - t) * y[i] + t * y[i + 1])


def interpolate_route(route_df, s_km):
    d = route_df['dist_km'].values
    lat = route_df['lat'].values
    lon = route_df['lon'].values
    latp = _interp_field(d, lat, s_km, default=float(lat[0]) if len(lat) else 0.0)
    lonp = _interp_field(d, lon, s_km, default=float(lon[0]) if len(lon) else 0.0)
    return latp, lonp


def interpolate_route_with_alt(route_df, s_km):
    lat, lon = interpolate_route(route_df, s_km)
    alt = None
    for col in ('alt_m', 'altitude_m', 'elev_m'):
        if col in route_df.columns:
            d = route_df['dist_km'].values
            alt = _interp_field(d, route_df[col].values, s_km, default=float(route_df[col].values[0]))
            break
    return lat, lon, alt


def interpolate_profile(route_df, s_km, field: str, default: float = 0.0) -> float:
    if field not in route_df.columns:
        return float(default)
    d = route_df['dist_km'].values
    return _interp_field(d, route_df[field].values, s_km, default=default)
