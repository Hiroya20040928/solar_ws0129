#!/usr/bin/env python3
import argparse
import math
import os

import pandas as pd


def load_and_clip(path, s_range=None, obd_ok_only=False):
    df = pd.read_csv(path)
    df = df.sort_values('t_ros_sec')
    if s_range is not None:
        s_min, s_max = s_range
        df = df[(df['s_km'] >= s_min) & (df['s_km'] <= s_max)]
    if obd_ok_only and 'obd_ok' in df.columns:
        df = df[df['obd_ok'] >= 0.5]
    return df


def integrate_fuel(df):
    if df.empty:
        return math.nan, math.nan, math.nan, math.nan, math.nan, math.nan, math.nan
    t = df['t_ros_sec'].to_numpy()
    fuel = df['fuel_rate_lph'].to_numpy()
    speed = df['speed_kmh'].to_numpy()
    s_km = df['s_km'].to_numpy()

    total_fuel = 0.0
    idle_fuel = 0.0
    total_time = 0.0

    for i in range(1, len(df)):
        if not (math.isfinite(t[i]) and math.isfinite(t[i - 1])):
            continue
        dt = t[i] - t[i - 1]
        if dt <= 0.0 or dt > 5.0:
            continue
        if math.isfinite(fuel[i]) and math.isfinite(fuel[i - 1]):
            fuel_avg = 0.5 * (fuel[i] + fuel[i - 1])
            fuel_inc = fuel_avg * (dt / 3600.0)
            total_fuel += fuel_inc
            if math.isfinite(speed[i]) and speed[i] < 1.0:
                idle_fuel += fuel_inc
        total_time += dt

    s_series = pd.Series(s_km).dropna()
    if len(s_series) >= 2 and math.isfinite(float(s_series.iloc[0])) and math.isfinite(float(s_series.iloc[-1])):
        distance = float(s_series.iloc[-1] - s_series.iloc[0])
    else:
        distance = math.nan
    avg_speed = float(pd.Series(speed).mean()) if len(speed) else math.nan
    std_speed = float(pd.Series(speed).std()) if len(speed) else math.nan
    avg_fuel_lph = float(pd.Series(fuel).mean()) if len(fuel) else math.nan
    fuel_per_100 = (total_fuel / distance * 100.0) if distance > 0.0 else math.nan

    driving_fuel = total_fuel - idle_fuel if math.isfinite(total_fuel) else math.nan
    return distance, total_fuel, idle_fuel, driving_fuel, fuel_per_100, avg_speed, std_speed, avg_fuel_lph


def summarize(label, stats):
    distance, total_fuel, idle_fuel, driving_fuel, fuel_per_100, avg_speed, std_speed, avg_fuel_lph = stats
    print(f'[{label}]')
    print(f'- distance_km: {distance:.3f}' if math.isfinite(distance) else '- distance_km: NaN')
    print(f'- fuel_L: {total_fuel:.3f}' if math.isfinite(total_fuel) else '- fuel_L: NaN')
    print(f'- idle_fuel_L: {idle_fuel:.3f}' if math.isfinite(idle_fuel) else '- idle_fuel_L: NaN')
    print(f'- driving_fuel_L: {driving_fuel:.3f}' if math.isfinite(driving_fuel) else '- driving_fuel_L: NaN')
    print(f'- L_per_100km: {fuel_per_100:.3f}' if math.isfinite(fuel_per_100) else '- L_per_100km: NaN')
    print(f'- avg_speed_kmh: {avg_speed:.2f}' if math.isfinite(avg_speed) else '- avg_speed_kmh: NaN')
    print(f'- std_speed_kmh: {std_speed:.2f}' if math.isfinite(std_speed) else '- std_speed_kmh: NaN')
    print(f'- avg_fuel_lph: {avg_fuel_lph:.3f}' if math.isfinite(avg_fuel_lph) else '- avg_fuel_lph: NaN')


def maybe_plot(df, out_path, title):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    t = df['t_ros_sec'].to_numpy()
    v_now = df['speed_kmh'].to_numpy()
    v_cmd = df['speed_cmd'].to_numpy() if 'speed_cmd' in df.columns else None
    fuel = df['fuel_rate_lph'].to_numpy()

    cumulative_fuel = [0.0]
    for i in range(1, len(df)):
        dt = t[i] - t[i - 1]
        if dt <= 0.0 or dt > 5.0:
            cumulative_fuel.append(cumulative_fuel[-1])
            continue
        if math.isfinite(fuel[i]) and math.isfinite(fuel[i - 1]):
            fuel_avg = 0.5 * (fuel[i] + fuel[i - 1])
            cumulative_fuel.append(cumulative_fuel[-1] + fuel_avg * (dt / 3600.0))
        else:
            cumulative_fuel.append(cumulative_fuel[-1])

    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    axes[0].plot(t, v_now, label='v_now')
    if v_cmd is not None:
        axes[0].plot(t, v_cmd, label='v_cmd')
    axes[0].set_ylabel('km/h')
    axes[0].legend()

    axes[1].plot(t, fuel, label='fuel_rate_lph')
    axes[1].set_ylabel('L/h')
    axes[1].legend()

    axes[2].plot(t, cumulative_fuel, label='cumulative_fuel_L')
    axes[2].set_ylabel('L')
    axes[2].set_xlabel('t [s]')
    axes[2].legend()

    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(out_path)


def main():
    parser = argparse.ArgumentParser(description='Compare fuel consumption logs')
    parser.add_argument('mpc_on_csv', help='CSV log with MPC enabled')
    parser.add_argument('mpc_off_csv', help='CSV log with MPC disabled')
    parser.add_argument('--s-range', nargs=2, type=float, metavar=('S_MIN', 'S_MAX'), help='clip by s_km range')
    parser.add_argument('--obd-ok-only', action='store_true', help='exclude obd_ok=0 rows')
    parser.add_argument('--plot', action='store_true', help='save plots')
    parser.add_argument('--out-dir', default='.', help='plot output directory')
    args = parser.parse_args()

    s_range = tuple(args.s_range) if args.s_range else None

    df_on = load_and_clip(args.mpc_on_csv, s_range, args.obd_ok_only)
    df_off = load_and_clip(args.mpc_off_csv, s_range, args.obd_ok_only)

    stats_on = integrate_fuel(df_on)
    stats_off = integrate_fuel(df_off)

    summarize('MPC_ON', stats_on)
    summarize('MPC_OFF', stats_off)

    if math.isfinite(stats_on[4]) and math.isfinite(stats_off[4]) and stats_off[4] > 0:
        improve = (stats_off[4] - stats_on[4]) / stats_off[4] * 100.0
        print(f'Improvement (L/100km): {improve:.2f}%')
    else:
        print('Improvement (L/100km): NaN')

    if math.isfinite(stats_on[1]) and math.isfinite(stats_off[1]) and stats_off[1] > 0:
        improve_fuel = (stats_off[1] - stats_on[1]) / stats_off[1] * 100.0
        print(f'Improvement (total fuel): {improve_fuel:.2f}%')
    else:
        print('Improvement (total fuel): NaN')

    if math.isfinite(stats_on[3]) and math.isfinite(stats_off[3]) and stats_off[3] > 0:
        improve_driving = (stats_off[3] - stats_on[3]) / stats_off[3] * 100.0
        print(f'Improvement (driving fuel): {improve_driving:.2f}%')
    else:
        print('Improvement (driving fuel): NaN')

    if args.plot:
        os.makedirs(args.out_dir, exist_ok=True)
        maybe_plot(df_on, os.path.join(args.out_dir, 'mpc_on.png'), 'MPC ON')
        maybe_plot(df_off, os.path.join(args.out_dir, 'mpc_off.png'), 'MPC OFF')
        print(f'Plots saved in {args.out_dir}')


if __name__ == '__main__':
    main()
