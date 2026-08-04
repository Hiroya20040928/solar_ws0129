#!/usr/bin/env python3
import argparse
import os

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


def build_pivot(df, value_col, row_col='G_poa', col_col='Tcell_C'):  # [関数定義] build_pivot の処理実行ブロック
    pivot = df.pivot_table(index=row_col, columns=col_col, values=value_col, aggfunc='median')
    return pivot.sort_index().sort_index(axis=1)                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def main():                                                        # [メイン関数] エントリーポイント関数
    ap = argparse.ArgumentParser()
    ap.add_argument('--panel_csv', required=True)
    ap.add_argument('--out_panel_csv', required=True)
    ap.add_argument('--out_mppt_csv', required=True)
    args = ap.parse_args()

    df = pd.read_csv(args.panel_csv)
    required = ['G_poa', 'Tcell_C', 'panel_voltage_v', 'panel_current_a']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f'missing columns: {missing}')
    if 'panel_area_m2' not in df.columns:
        raise ValueError('panel_area_m2 column is required')

    df['panel_power_w'] = df['panel_voltage_v'] * df['panel_current_a']
    df['panel_efficiency'] = df['panel_power_w'] / (df['G_poa'].clip(lower=1.0) * df['panel_area_m2'])
    df['panel_efficiency'] = df['panel_efficiency'].clip(lower=0.0, upper=1.0)

    if {'mppt_voltage_v', 'mppt_current_a'}.issubset(df.columns):
        df['mppt_power_w'] = df['mppt_voltage_v'] * df['mppt_current_a']
        df['mppt_efficiency'] = (df['mppt_power_w'] / df['panel_power_w'].clip(lower=1.0)).clip(lower=0.0, upper=1.0)
    else:
        df['mppt_efficiency'] = 0.95

    panel_map = build_pivot(df, 'panel_efficiency')
    mppt_map = build_pivot(df, 'mppt_efficiency')

    os.makedirs(os.path.dirname(os.path.abspath(args.out_panel_csv)), exist_ok=True)
    panel_map.to_csv(args.out_panel_csv)
    mppt_map.to_csv(args.out_mppt_csv)
    print(f'panel map saved: {args.out_panel_csv}')
    print(f'mppt map saved: {args.out_mppt_csv}')


if __name__ == '__main__':                                         # [直接実行スクリプト] スクリプト直接起動時のメイン実行ブロック
    main()
