#!/usr/bin/env python3
import argparse
import os

import numpy as np
import pandas as pd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pulse_csv', required=True)
    ap.add_argument('--ocv_csv', required=True)
    ap.add_argument('--out_csv', required=True)
    ap.add_argument('--soc_bin', type=float, default=0.05)
    ap.add_argument('--temp_bin_c', type=float, default=5.0)
    ap.add_argument('--min_abs_current_a', type=float, default=5.0)
    args = ap.parse_args()

    df = pd.read_csv(args.pulse_csv)
    ocv_df = pd.read_csv(args.ocv_csv)
    required = ['soc', 'batt_temp_c', 'batt_voltage_v', 'batt_current_a']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f'missing columns: {missing}')
    if not {'soc', 'ocv_v'}.issubset(ocv_df.columns):
        raise ValueError('ocv_csv must have soc and ocv_v columns')

    df = df[np.abs(df['batt_current_a']) >= args.min_abs_current_a].copy()
    if df.empty:
        raise ValueError('no high-current rows found for Rint estimation')

    df['ocv_v'] = np.interp(df['soc'].to_numpy(), ocv_df['soc'].to_numpy(), ocv_df['ocv_v'].to_numpy())
    df['r_ohm'] = (df['ocv_v'] - df['batt_voltage_v']) / df['batt_current_a']
    df = df[np.isfinite(df['r_ohm'])].copy()
    df['soc_bin'] = (df['soc'] / max(args.soc_bin, 1.0e-3)).round() * max(args.soc_bin, 1.0e-3)
    df['temp_bin'] = (df['batt_temp_c'] / max(args.temp_bin_c, 0.5)).round() * max(args.temp_bin_c, 0.5)
    pivot = df.pivot_table(index='temp_bin', columns='soc_bin', values='r_ohm', aggfunc='median')
    pivot = pivot.sort_index().sort_index(axis=1)

    os.makedirs(os.path.dirname(os.path.abspath(args.out_csv)), exist_ok=True)
    pivot.to_csv(args.out_csv)
    print(f'rint map saved: {args.out_csv}')


if __name__ == '__main__':
    main()
