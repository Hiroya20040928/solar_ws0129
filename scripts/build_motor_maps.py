#!/usr/bin/env python3
import argparse
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
from pathlib import Path

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


def extract_rows(path, sheet):                                     # [関数定義] extract_rows の処理実行ブロック
    df = pd.read_excel(path, sheet_name=sheet, header=None)
    speed_row = 13
    rpm_row = 17
    torque_row = 18
    eff_row = 20
    rows = []
    for c in range(df.shape[1]):
        try:
            speed = float(df.iloc[speed_row, c])
            rpm = float(df.iloc[rpm_row, c])
            torque = float(df.iloc[torque_row, c])
            eff = float(df.iloc[eff_row, c])
        except Exception:
            continue
        if any(map(lambda x: x is None or (isinstance(x, float) and math.isnan(x)), [speed, rpm, torque, eff])):
            continue
        if eff <= 0.0:
            continue
        rows.append((speed, rpm, torque, eff))
    return rows                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_map(rows_low, rows_high, v_grid_kmh, tau_grid):          # [関数定義] build_map の処理実行ブロック
    # interpolate efficiency vs torque for low/high
    def interp_curve(rows, tau_grid):                              # [関数定義] interp_curve の処理実行ブロック
        tau = np.array([r[2] for r in rows], dtype=float)
        eff = np.array([r[3] for r in rows], dtype=float) / 100.0
        # ensure sorted
        idx = np.argsort(tau)
        tau = tau[idx]
        eff = eff[idx]
        return np.interp(tau_grid, tau, eff, left=eff[0], right=eff[-1])  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    speed_low = np.mean([r[0] for r in rows_low])
    speed_high = np.mean([r[0] for r in rows_high])
    eff_low = interp_curve(rows_low, tau_grid)
    eff_high = interp_curve(rows_high, tau_grid)

    Z = np.zeros((len(v_grid_kmh), len(tau_grid)))
    for i, v in enumerate(v_grid_kmh):
        if v <= speed_low:
            w = 0.0
        elif v >= speed_high:
            w = 1.0
        else:
            w = (v - speed_low) / (speed_high - speed_low)
        Z[i, :] = (1 - w) * eff_low + w * eff_high
    return Z                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def main():                                                        # [メイン関数] エントリーポイント関数
    ap = argparse.ArgumentParser()
    ap.add_argument('--excel', required=True)
    ap.add_argument('--out_dir', required=True)
    ap.add_argument('--v_min', type=float, default=20.0)
    ap.add_argument('--v_max', type=float, default=120.0)
    ap.add_argument('--v_step', type=float, default=5.0)
    ap.add_argument('--tau_max', type=float, default=45.0)
    ap.add_argument('--tau_step', type=float, default=1.0)
    args = ap.parse_args()

    v_grid = np.arange(args.v_min, args.v_max + 1e-6, args.v_step)
    tau_grid = np.arange(0.0, args.tau_max + 1e-6, args.tau_step)

    rows_pwm_lo = extract_rows(args.excel, 'PWM_LO')
    rows_pwm_hi = extract_rows(args.excel, 'PWM_HI')
    rows_eco_lo = extract_rows(args.excel, 'ECO_LO')
    rows_eco_hi = extract_rows(args.excel, 'ECO_HI')

    Z_power = build_map(rows_pwm_lo, rows_pwm_hi, v_grid, tau_grid)
    Z_eco = build_map(rows_eco_lo, rows_eco_hi, v_grid, tau_grid)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    drive_power = pd.DataFrame(Z_power, index=v_grid / 3.6, columns=tau_grid)
    drive_eco = pd.DataFrame(Z_eco, index=v_grid / 3.6, columns=tau_grid)
    regen_power = pd.DataFrame(Z_power * 0.85, index=v_grid / 3.6, columns=tau_grid)
    regen_eco = pd.DataFrame(Z_eco * 0.85, index=v_grid / 3.6, columns=tau_grid)

    drive_power.to_csv(out_dir / 'drive_eff_map_power.csv')
    drive_eco.to_csv(out_dir / 'drive_eff_map_eco.csv')
    regen_power.to_csv(out_dir / 'regen_eff_map_power.csv')
    regen_eco.to_csv(out_dir / 'regen_eff_map_eco.csv')

    print('generated maps in', out_dir)


if __name__ == '__main__':                                         # [直接実行スクリプト] スクリプト直接起動時のメイン実行ブロック
    main()