#!/usr/bin/env python3
import argparse
import os

import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート

from mpc_solarcar.solar_profile import get_path, get_section, load_profile, merged_dict
from mpc_solarcar.weather_utils import fetch_openmeteo_forecast, write_forecast_csv


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
