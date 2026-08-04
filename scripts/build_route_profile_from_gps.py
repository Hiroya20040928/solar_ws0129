#!/usr/bin/env python3
import argparse
import math
import os

import numpy as np
import pandas as pd


EARTH_R = 6371000.0


def haversine_m(lat1, lon1, lat2, lon2):
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * EARTH_R * math.asin(math.sqrt(max(0.0, a)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--gps_csv', required=True)
    ap.add_argument('--out_waypoints_csv', required=True)
    ap.add_argument('--out_profile_csv', required=True)
    ap.add_argument('--resample_m', type=float, default=1000.0)
    args = ap.parse_args()

    df = pd.read_csv(args.gps_csv)
    required = ['lat', 'lon', 'alt_m']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f'missing columns: {missing}')
    if len(df) < 2:
        raise ValueError('gps_csv requires at least 2 rows')

    dist_m = [0.0]
    for i in range(1, len(df)):
        dist_m.append(dist_m[-1] + haversine_m(df.iloc[i - 1]['lat'], df.iloc[i - 1]['lon'], df.iloc[i]['lat'], df.iloc[i]['lon']))
    df['dist_km'] = np.array(dist_m) / 1000.0
    d_alt = df['alt_m'].diff().fillna(0.0)
    d_dist = np.diff(np.array(dist_m), prepend=dist_m[0])
    slope_pct = np.divide(d_alt.to_numpy(), np.maximum(d_dist, 1.0), out=np.zeros_like(d_alt.to_numpy(), dtype=float), where=np.maximum(d_dist, 1.0) > 0.0) * 100.0
    df['slope_pct'] = slope_pct

    step_m = max(10.0, float(args.resample_m))
    sample_dist_m = np.arange(0.0, dist_m[-1] + step_m, step_m)
    lat_i = np.interp(sample_dist_m, dist_m, df['lat'])
    lon_i = np.interp(sample_dist_m, dist_m, df['lon'])
    alt_i = np.interp(sample_dist_m, dist_m, df['alt_m'])
    slope_i = np.interp(sample_dist_m, dist_m, df['slope_pct'])

    waypoints = pd.DataFrame({
        'lat': lat_i,
        'lon': lon_i,
        'dist_km': sample_dist_m / 1000.0,
        'alt_m': alt_i,
    })
    profile = pd.DataFrame({
        'dist_km': sample_dist_m / 1000.0,
        'slope_pct': slope_i,
        'headwind_ms': np.zeros_like(sample_dist_m, dtype=float),
    })

    os.makedirs(os.path.dirname(os.path.abspath(args.out_waypoints_csv)), exist_ok=True)
    waypoints.to_csv(args.out_waypoints_csv, index=False)
    profile.to_csv(args.out_profile_csv, index=False)
    print(f'route waypoints saved: {args.out_waypoints_csv}')
    print(f'route profile saved: {args.out_profile_csv}')


if __name__ == '__main__':
    main()
