#!/usr/bin/env python3
import argparse
import os

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


def main():                                                        # [メイン関数] エントリーポイント関数
    ap = argparse.ArgumentParser()
    ap.add_argument('--rest_csv', required=True)
    ap.add_argument('--out_csv', required=True)
    ap.add_argument('--soc_bin', type=float, default=0.02)
    ap.add_argument('--max_abs_current_a', type=float, default=2.0)
    args = ap.parse_args()

    df = pd.read_csv(args.rest_csv)
    required = ['soc', 'batt_voltage_v', 'batt_current_a']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f'missing columns: {missing}')

    df = df[np.abs(df['batt_current_a']) <= args.max_abs_current_a].copy()
    if df.empty:
        raise ValueError('no low-current rows found for OCV estimation')

    soc_bin = max(0.001, float(args.soc_bin))
    df['soc_bin'] = (df['soc'] / soc_bin).round() * soc_bin
    out = df.groupby('soc_bin', as_index=False)['batt_voltage_v'].median()
    out = out.rename(columns={'soc_bin': 'soc', 'batt_voltage_v': 'ocv_v'}).sort_values('soc')

    os.makedirs(os.path.dirname(os.path.abspath(args.out_csv)), exist_ok=True)
    out.to_csv(args.out_csv, index=False)
    print(f'ocv curve saved: {args.out_csv}')


if __name__ == '__main__':                                         # [直接実行スクリプト] スクリプト直接起動時のメイン実行ブロック
    main()
