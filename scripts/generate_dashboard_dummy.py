#!/usr/bin/env python3
import argparse
import math
import csv
from datetime import datetime, timedelta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out_csv', default='dashboard_dummy.csv')
    ap.add_argument('--seconds', type=int, default=600)
    ap.add_argument('--rate_hz', type=float, default=5.0)
    args = ap.parse_args()

    dt = 1.0 / max(args.rate_hz, 0.5)
    steps = int(args.seconds / dt)
    t0 = datetime.utcnow()

    fieldnames = [
        'time_utc',
        'speed_cmd_kmh',
        'upper_speed_cmd_kmh',
        'speed_meas_kmh',
        'throttle_cmd_pct',
        'drive_mode',
        'soc',
        'Tb_C',
        'batt_current_a',
        'batt_voltage_v',
        'motor_w',
        'motor_a',
        'solar_w',
        'wheel_w',
        'pack_w',
        'G_poa',
        'Tcell_C',
        'Tamb_C',
        'headwind_ms',
        'slope_pct',
        's_km',
        'system_state',
        'system_diag',
        'mpc_state',
        'system_health',
        'forecast_status',
        'calibration_status',
        'command_status',
        'cal_solar_gain',
        'cal_drive_gain',
        'cal_aux_power_w',
        'race_progress_pct',
        'next_stop_dist_km',
        'next_stop_eta_min',
        'finish_dist_km',
        'finish_eta_h',
        'vehicle_lat',
        'vehicle_lon',
        'chase_lat',
        'chase_lon',
    ]

    with open(args.out_csv, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        s_km = 0.0
        soc = 0.95
        for i in range(steps):
            t = t0 + timedelta(seconds=i * dt)
            phase = i * dt
            speed_cmd = 70 + 15 * math.sin(phase / 30.0)
            upper_speed = speed_cmd + 5 * math.sin(phase / 60.0)
            speed_meas = speed_cmd + 2 * math.sin(phase / 10.0)
            throttle = 20 + 15 * math.sin(phase / 15.0)
            drive_mode = 'eco' if math.sin(phase / 40.0) < 0 else 'power'
            batt_v = 95 + 5 * math.sin(phase / 50.0)
            batt_i = 10 + 8 * math.sin(phase / 20.0)
            motor_w = 1200 + 800 * math.sin(phase / 18.0)
            motor_a = motor_w / max(batt_v, 1.0)
            solar_w = max(0.0, 900 + 500 * math.sin(phase / 120.0))
            wheel_w = 1000 + 600 * math.sin(phase / 22.0)
            pack_w = motor_w - solar_w
            G_poa = max(0.0, 900 + 400 * math.sin(phase / 120.0))
            Tcell = 45 + 3 * math.sin(phase / 90.0)
            Tamb = 33 + 2 * math.sin(phase / 110.0)
            headwind = 1.5 * math.sin(phase / 70.0)
            slope = 0.5 * math.sin(phase / 80.0)
            soc = max(0.05, soc - 0.00002 * motor_w + 0.000015 * solar_w)
            s_km += speed_meas * (dt / 3600.0)

            writer.writerow({
                'time_utc': t.isoformat() + 'Z',
                'speed_cmd_kmh': round(speed_cmd, 2),
                'upper_speed_cmd_kmh': round(upper_speed, 2),
                'speed_meas_kmh': round(speed_meas, 2),
                'throttle_cmd_pct': round(throttle, 2),
                'drive_mode': drive_mode,
                'soc': round(soc, 4),
                'Tb_C': round(35 + 2 * math.sin(phase / 100.0), 2),
                'batt_current_a': round(batt_i, 2),
                'batt_voltage_v': round(batt_v, 2),
                'motor_w': round(motor_w, 1),
                'motor_a': round(motor_a, 2),
                'solar_w': round(solar_w, 1),
                'wheel_w': round(wheel_w, 1),
                'pack_w': round(pack_w, 1),
                'G_poa': round(G_poa, 1),
                'Tcell_C': round(Tcell, 2),
                'Tamb_C': round(Tamb, 2),
                'headwind_ms': round(headwind, 2),
                'slope_pct': round(slope, 2),
                's_km': round(s_km, 3),
                'system_state': 'RUN',
                'system_diag': 'OK',
                'mpc_state': 'RUN',
                'system_health': 0.98,
                'forecast_status': 'openmeteo synced',
                'calibration_status': 'drive gain recalibrated',
                'command_status': 'speed=70.0 km/h mode=eco',
                'cal_solar_gain': 1.02,
                'cal_drive_gain': 0.97,
                'cal_aux_power_w': 8.5,
                'race_progress_pct': min(100.0, s_km / 30.355),
                'next_stop_dist_km': max(0.0, 300.0 - s_km),
                'next_stop_eta_min': max(0.0, (300.0 - s_km) / max(speed_meas, 1.0) * 60.0),
                'finish_dist_km': max(0.0, 3035.5 - s_km),
                'finish_eta_h': max(0.0, (3035.5 - s_km) / max(speed_meas, 1.0)),
                'vehicle_lat': -12.4634 + 0.001 * math.sin(phase / 100.0),
                'vehicle_lon': 130.8456 + 0.001 * math.cos(phase / 100.0),
                'chase_lat': -12.4630 + 0.001 * math.sin(phase / 100.0),
                'chase_lon': 130.8452 + 0.001 * math.cos(phase / 100.0),
            })


if __name__ == '__main__':
    main()
