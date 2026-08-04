#!/usr/bin/env python3
import argparse
import os

import numpy as np
import pandas as pd
import yaml


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--drive_csv', required=True)
    ap.add_argument('--out_yaml', required=True)
    ap.add_argument('--mass_kg', type=float, required=True)
    ap.add_argument('--rho', type=float, default=1.18)
    ap.add_argument('--pv_area_m2', type=float, default=6.0)
    ap.add_argument('--pv_eta_ref', type=float, default=0.24)
    ap.add_argument('--mppt_eta', type=float, default=0.95)
    ap.add_argument('--max_abs_accel_kmhps', type=float, default=0.8)
    ap.add_argument('--min_speed_kmh', type=float, default=20.0)
    args = ap.parse_args()

    df = pd.read_csv(args.drive_csv)
    required = ['speed_kmh', 'batt_voltage_v', 'batt_current_a', 'slope_pct', 'G_poa']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f'missing columns: {missing}')

    if 'accel_kmhps' not in df.columns:
        dt = 1.0
        if 'time_utc' in df.columns:
            ts = pd.to_datetime(df['time_utc'], utc=True, errors='coerce')
            if ts.notna().sum() >= 2:
                dt = float(np.nanmedian(np.diff(ts.astype('int64') / 1e9)))
                dt = max(dt, 1.0e-3)
        df['accel_kmhps'] = df['speed_kmh'].diff().fillna(0.0) / dt

    df['pack_w'] = df['batt_voltage_v'] * df['batt_current_a']
    df['pv_w_est'] = df['G_poa'].clip(lower=0.0) * args.pv_area_m2 * args.pv_eta_ref * args.mppt_eta
    df['v_ms'] = df['speed_kmh'] / 3.6
    df['slope_frac'] = df['slope_pct'] / 100.0
    df['headwind_ms'] = df['headwind_ms'] if 'headwind_ms' in df.columns else 0.0
    df['v_rel_ms'] = (df['v_ms'] + df['headwind_ms']).clip(lower=0.0)
    df['target_w'] = df['pack_w'] + df['pv_w_est']

    mask = (
        df['speed_kmh'].abs() >= args.min_speed_kmh
    ) & (
        df['accel_kmhps'].abs() <= args.max_abs_accel_kmhps
    ) & np.isfinite(df['target_w']) & np.isfinite(df['v_rel_ms']) & np.isfinite(df['slope_frac'])
    fit = df.loc[mask].copy()
    if len(fit) < 20:
        raise ValueError('not enough valid rows for identification')

    X = np.column_stack([
        fit['v_rel_ms'].to_numpy() ** 3,
        fit['v_ms'].to_numpy(),
        fit['slope_frac'].to_numpy() * fit['v_ms'].to_numpy(),
        np.ones(len(fit)),
    ])
    y = fit['target_w'].to_numpy()
    coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    pred = X @ coeffs
    rmse = float(np.sqrt(np.mean((pred - y) ** 2)))

    a_aero, a_roll, a_grade, a_aux = coeffs
    cda = max(0.01, 2.0 * a_aero / max(args.rho, 1.0e-6))
    crr = max(0.0001, a_roll / max(args.mass_kg * 9.80665, 1.0e-6))
    grade_scale = a_grade / max(args.mass_kg * 9.80665, 1.0e-6)
    p_aux = max(0.0, a_aux)

    out = {
        'model_fit': {
            'CdA': round(float(cda), 6),
            'Crr': round(float(crr), 6),
            'P_aux': round(float(p_aux), 3),
            'grade_scale': round(float(grade_scale), 6),
            'fit_rows': int(len(fit)),
            'rmse_w': round(rmse, 3),
        }
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out_yaml)), exist_ok=True)
    with open(args.out_yaml, 'w', encoding='utf-8') as f:
        yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True)
    print(f'identified vehicle params: {args.out_yaml}')


if __name__ == '__main__':
    main()
