#!/usr/bin/env python3
import argparse
import os
import subprocess
import sys

from mpc_solarcar.solar_profile import get_section, load_profile


def run(cmd):                                                      # [関数定義] run の処理実行ブロック
    print('RUN', ' '.join(cmd))
    subprocess.run(cmd, check=True)


def main():                                                        # [メイン関数] エントリーポイント関数
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile_yaml', required=True)
    ap.add_argument('--input_dir', default='')
    ap.add_argument('--output_dir', default='')
    args = ap.parse_args()

    profile_path, cfg = load_profile(args.profile_yaml)
    ident_cfg = get_section(cfg, 'identification')
    input_dir = os.path.abspath(args.input_dir or ident_cfg.get('input_dir', 'data/identification/raw'))
    output_dir = os.path.abspath(args.output_dir or ident_cfg.get('output_dir', 'outputs/identification'))
    os.makedirs(output_dir, exist_ok=True)

    python = sys.executable

    gps_csv = os.path.join(input_dir, 'gps_track.csv')
    if os.path.exists(gps_csv):
        run([
            python, 'scripts/build_route_profile_from_gps.py',
            '--gps_csv', gps_csv,
            '--out_waypoints_csv', os.path.join(output_dir, 'route_waypoints_identified.csv'),
            '--out_profile_csv', os.path.join(output_dir, 'route_profile_identified.csv'),
        ])

    rest_csv = os.path.join(input_dir, 'battery_rest.csv')
    ocv_csv = os.path.join(output_dir, 'ocv_soc_curve_identified.csv')
    if os.path.exists(rest_csv):
        run([
            python, 'scripts/build_ocv_curve.py',
            '--rest_csv', rest_csv,
            '--out_csv', ocv_csv,
        ])

    pulse_csv = os.path.join(input_dir, 'battery_pulse.csv')
    if os.path.exists(pulse_csv) and os.path.exists(ocv_csv):
        run([
            python, 'scripts/build_rint_map_from_timeseries.py',
            '--pulse_csv', pulse_csv,
            '--ocv_csv', ocv_csv,
            '--out_csv', os.path.join(output_dir, 'Rint_T_by_soc_identified.csv'),
        ])

    panel_csv = os.path.join(input_dir, 'panel_sweep.csv')
    if os.path.exists(panel_csv):
        run([
            python, 'scripts/build_pv_maps_from_csv.py',
            '--panel_csv', panel_csv,
            '--out_panel_csv', os.path.join(output_dir, 'panel_eff_map_identified.csv'),
            '--out_mppt_csv', os.path.join(output_dir, 'mppt_eff_map_identified.csv'),
        ])

    drive_csv = os.path.join(input_dir, 'drive_timeseries.csv')
    model_cfg = get_section(cfg, 'model')
    if os.path.exists(drive_csv):
        run([
            python, 'scripts/fit_vehicle_params.py',
            '--drive_csv', drive_csv,
            '--out_yaml', os.path.join(output_dir, 'vehicle_model_fit.yaml'),
            '--mass_kg', str(model_cfg.get('m', 224.0)),
            '--rho', str(model_cfg.get('rho', 1.18)),
            '--pv_area_m2', str(model_cfg.get('pv_area', 6.0)),
            '--pv_eta_ref', str(model_cfg.get('pv_eta_ref', 0.24)),
            '--mppt_eta', str(model_cfg.get('mppt_eta', 0.95)),
        ])

    print(f'identification outputs saved under: {output_dir}')


if __name__ == '__main__':                                         # [直接実行スクリプト] スクリプト直接起動時のメイン実行ブロック
    main()
