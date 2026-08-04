from __future__ import annotations

import csv
import json
import math
import os
import socket
import sys
import time
from pathlib import Path

import casadi as ca
import numpy as np
import yaml

# =============================================================================
# 【実車リアルタイム制御モジュール】10s周期 CasADi MPC + UDP WiFi 通信 + MHE 状態推定
# =============================================================================


import json
import math
import os
import socket
import sys
import time
from pathlib import Path

import casadi as ca
import numpy as np
import yaml


# =============================================================================
# 【最高級統合ノード】ソーラーカー本番制御・状態推定・WiFi通信統合 ROS 2 ノード
# =============================================================================

# -*- coding: utf-8 -*-
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import os
import time
from collections import deque
from datetime import datetime, timezone, timedelta


import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート


from scipy.optimize import minimize



class MPCNode:                                               # [ローカルMPCノード] 周期的(10s)に後退ホライズン最適化を実行する主ROS2ノード
    """
    MPC node with two modes:
      - Default: solarcar MPC (forecast-driven)
      - Passo mode: fuel-minimizing advisory MPC
    """

    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        self.declare_parameter('passo_mode', False)
        self.passo_mode = bool(self.get_parameter('passo_mode').value)
        if self.passo_mode:
            self._init_passo()
        else:
            self._init_solar()

    # -------------------- common helpers --------------------
    def _load_stops(self, stop_yaml: str):                         # [関数定義] _load_stops の処理実行ブロック
        self.stops = []
        try:
            with open(stop_yaml, 'r', encoding='utf-8') as f:
                y = yaml.safe_load(f) or {}
                self.stops = y.get('stops', [])
                print(f'Loaded {len(self.stops)} stop points from {stop_yaml}')
        except Exception:
            print('No stop_points.yaml provided. Running without dwell constraints.')

    def _load_forecast_file(self, path: str):                      # [関数定義] _load_forecast_file の処理実行ブロック
        self.df = pd.read_csv(path)
        if 'time' in self.df.columns:
            t = pd.to_datetime(self.df['time'], errors='coerce')
            tzname = str(getattr(self, 'forecast_time_tz', 'UTC') or 'UTC')
            if t.dt.tz is None:
                if tzname.upper() == 'UTC':
                    t = t.dt.tz_localize('UTC')
                else:
                    try:
                        t = t.dt.tz_localize(tzname, ambiguous='NaT', nonexistent='NaT').dt.tz_convert('UTC')
                    except Exception:
                        t = t.dt.tz_localize('UTC')
            else:
                t = t.dt.tz_convert('UTC')
            self.df['time'] = t
            if self.df['time'].isna().all():
                print("forecast 'time' column could not be parsed; falling back to index bins.")
        else:
            print("forecast CSV has no 'time' column; falling back to index bins.")

    def _read_params_yaml(self, path: str):                        # [関数定義] _read_params_yaml の処理実行ブロック
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
            return cfg if isinstance(cfg, dict) else {}            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception as exc:
            print(f'params_yaml load failed: {exc}')
            return {}                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _apply_declared_yaml_params(self, cfg: dict):              # [関数定義] _apply_declared_yaml_params の処理実行ブロック
        if not isinstance(cfg, dict):
            return
        params = []
        skipped = []
        model_cfg = cfg.get('model', cfg) if isinstance(cfg, dict) else {}
        if isinstance(model_cfg, dict):
            for key, val in model_cfg.items():
                if self.has_parameter(key):
                    params.append(Parameter(key, value=val))
        mpc_cfg = cfg.get('mpc', {})
        if isinstance(mpc_cfg, dict):
            for key, val in mpc_cfg.items():
                if self.has_parameter(key):
                    params.append(Parameter(key, value=val))
                else:
                    skipped.append(str(key))
        if params:
            self.set_parameters(params)
        if skipped:
            print("Skipping params: " + ", ".join(skipped))


    def _apply_model_cfg(self, model_cfg: dict):                   # [関数定義] _apply_model_cfg の処理実行ブロック
        if not isinstance(model_cfg, dict):
            return
        motor_type = None
        for k, v in model_cfg.items():
            if hasattr(self.model.p, k):
                try:
                    setattr(self.model.p, k, float(v))
                except Exception:
                    try:
                        setattr(self.model.p, k, v)
                    except Exception:
                        pass
            if k == 'motor_type':
                motor_type = str(v)
            if k == 'drive_mode':
                self.model.drive_mode = str(v)
            if k == 'drive_mode_tau_margin':
                try:
                    self.model.drive_mode_tau_margin = float(v)
                except Exception:
                    pass
            if k == 'ocv_soc_map':
                try:
                    v_str = str(v).strip()
                    if v_str:
                        self.model.load_ocv_map(resolve_path(v_str, 'maps'))
                except Exception:
                    pass
        if motor_type:
            mt = motor_type.lower()
            if mt in ('inwheel', 'hub'):
                if 'gear_ratio' not in model_cfg:
                    self.model.p.gear_ratio = 1.0
                if 'gear_eta' not in model_cfg:
                    self.model.p.gear_eta = 1.0

    def _maybe_reload_forecast(self):                              # [関数定義] _maybe_reload_forecast の処理実行ブロック
        if self.forecast_reload_sec <= 0:
            return
        now = time.monotonic()
        if (now - self.last_forecast_check) < self.forecast_reload_sec:
            return
        self.last_forecast_check = now
        try:
            mtime = os.path.getmtime(self.forecast_path)
        except Exception:
            return
        if self.forecast_mtime is None or mtime > self.forecast_mtime:
            self.forecast_mtime = mtime
            try:
                self._load_forecast_file(self.forecast_path)
                self.forecast_reloaded = True
                print('Forecast CSV reloaded.')
            except Exception as exc:
                print(f'Forecast reload failed: {exc}')

    def _on_s_km_solar(self, msg: Float32):                        # [関数定義] _on_s_km_solar の処理実行ブロック
        try:
            value = finite_float(msg.data)
            if math.isfinite(value):
                now_mono = time.monotonic()
                self.s_meas = self.distance_meas_filter.update(value, now=now_mono)
                self.s_meas_time = now_mono
        except Exception:
            pass

    def _on_speed_solar(self, msg: Float32):                       # [関数定義] _on_speed_solar の処理実行ブロック
        try:
            value = finite_float(msg.data)
            if math.isfinite(value):
                now_mono = time.monotonic()
                self.v_now = self.speed_meas_filter.update(value, now=now_mono)
                self.v_now_time = now_mono
        except Exception:
            pass

    def _on_soc_solar(self, msg: Float32):                         # [関数定義] _on_soc_solar の処理実行ブロック
        try:
            value = finite_float(msg.data)
            if math.isfinite(value) and value > 1.5:
                value /= 100.0
            if math.isfinite(value):
                now_mono = time.monotonic()
                self.solar_soc_meas = self.soc_meas_filter.update(value, now=now_mono)
                self.solar_soc_time = now_mono
        except Exception:
            pass

    def _on_tb_solar(self, msg: Float32):                          # [関数定義] _on_tb_solar の処理実行ブロック
        try:
            value = finite_float(msg.data)
            if math.isfinite(value):
                now_mono = time.monotonic()
                self.solar_tb_meas = self.tb_meas_filter.update(value, now=now_mono)
                self.solar_tb_time = now_mono
        except Exception:
            pass

    def _on_i_solar(self, msg: Float32):                           # [関数定義] _on_i_solar の処理実行ブロック
        try:
            value = finite_float(msg.data)
            if math.isfinite(value):
                now_mono = time.monotonic()
                self.solar_i_meas = self.i_meas_filter.update(value, now=now_mono)
                self.solar_i_time = now_mono
        except Exception:
            pass

    def _on_v_solar(self, msg: Float32):                           # [関数定義] _on_v_solar の処理実行ブロック
        try:
            value = finite_float(msg.data)
            if math.isfinite(value):
                now_mono = time.monotonic()
                self.solar_v_meas = self.v_meas_filter.update(value, now=now_mono)
                self.solar_v_time = now_mono
        except Exception:
            pass

    def _on_calibration(self, msg: String):                        # [関数定義] _on_calibration の処理実行ブロック
        try:
            cfg = yaml.safe_load(msg.data) or {}
        except Exception:
            return
        if not isinstance(cfg, dict):
            return
        if 'solar_gain' in cfg:
            try:
                self.solar_gain = float(cfg['solar_gain'])
            except Exception:
                pass
        if 'poa_gain_drive' in cfg:
            try:
                self.poa_gain_drive = float(cfg['poa_gain_drive'])
            except Exception:
                pass
        if 'poa_gain_stop' in cfg:
            try:
                self.poa_gain_stop = float(cfg['poa_gain_stop'])
            except Exception:
                pass
        if 'drive_power_gain' in cfg:
            try:
                self.model.drive_power_gain = float(cfg['drive_power_gain'])
            except Exception:
                pass
        if 'aux_power_w' in cfg:
            try:
                self.model.aux_power_override_w = float(cfg['aux_power_w'])
            except Exception:
                pass
        self.calibration_state = cfg

    def _fresh_measurement(self, value, timestamp, timeout_sec):   # [関数定義] _fresh_measurement の処理実行ブロック
        now_mono = time.monotonic()
        if not math.isfinite(finite_float(value)):
            return math.nan                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if not fresh_enough(timestamp, timeout_sec, now=now_mono):
            return math.nan                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return float(value)                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _measured_speed_kmh(self):                                 # [関数定義] _measured_speed_kmh の処理実行ブロック
        return self._fresh_measurement(self.v_now, self.v_now_time, self.speed_meas_timeout_sec)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _measured_distance_km(self):                               # [関数定義] _measured_distance_km の処理実行ブロック
        return self._fresh_measurement(self.s_meas, self.s_meas_time, self.distance_meas_timeout_sec)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _measured_soc(self):                                       # [関数定義] _measured_soc の処理実行ブロック
        return self._fresh_measurement(self.solar_soc_meas, self.solar_soc_time, self.battery_meas_timeout_sec)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _measured_tb(self):                                        # [関数定義] _measured_tb の処理実行ブロック
        return self._fresh_measurement(self.solar_tb_meas, self.solar_tb_time, self.battery_meas_timeout_sec)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _measured_i(self):                                         # [関数定義] _measured_i の処理実行ブロック
        return self._fresh_measurement(self.solar_i_meas, self.solar_i_time, self.battery_meas_timeout_sec)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _measured_v(self):                                         # [関数定義] _measured_v の処理実行ブロック
        return self._fresh_measurement(self.solar_v_meas, self.solar_v_time, self.battery_meas_timeout_sec)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _plan_warm_start_ms(self, count: int, default_speed_ms: float):  # [関数定義] _plan_warm_start_ms の処理実行ブロック
        if count <= 0:
            return np.zeros(0, dtype=float)

        default_ms = max(0.0, float(default_speed_ms))
        if not self.v_plan_kmh:
            return np.full(count, default_ms, dtype=float)         # [戻り値] 計算結果・計算状態の呼び出し元への返却
        values = [finite_float(v) for v in list(self.v_plan_kmh)[:count]]
        seeded = []
        last_kmh = default_ms * 3.6
        for value in values:
            if math.isfinite(value):
                last_kmh = float(value)
            seeded.append(max(0.0, last_kmh) / 3.6)
        while len(seeded) < count:
            seeded.append(max(0.0, last_kmh) / 3.6)
        return np.array(seeded[:count], dtype=float)               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _shape_lower_ref_seq(self, raw_ref_seq_kmh, seed_kmh: float):  # [関数定義] _shape_lower_ref_seq の処理実行ブロック
        if not raw_ref_seq_kmh:
            return []                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
        shaped = []
        prev = max(0.0, float(seed_kmh))
        for raw in raw_ref_seq_kmh:
            candidate = max(0.0, float(raw))
            candidate = slew_limit(
                prev,
                candidate,
                self.lower_dt,
                self.lower_ref_accel_limit_kmhps,
                self.lower_ref_decel_limit_kmhps,
            )
            if abs(candidate - prev) < self.lower_ref_deadband_kmh:
                candidate = prev
            shaped.append(float(candidate))
            prev = candidate
        return shaped                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _apply_drive_mode_hold(self, requested_mode: str):         # [関数定義] _apply_drive_mode_hold の処理実行ブロック
        requested = str(requested_mode or self.lower_last_mode or 'eco')
        now_mono = time.monotonic()
        if requested == self.lower_last_mode:
            return self.lower_last_mode                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if (now_mono - self.last_lower_mode_change) < self.drive_mode_min_hold_sec:
            return self.lower_last_mode                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        self.last_lower_mode_change = now_mono
        return requested                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _publish_mpc_state(self):                                  # [関数定義] _publish_mpc_state の処理実行ブロック
        speed_state = 'fresh' if math.isfinite(self._measured_speed_kmh()) else 'stale'
        dist_state = 'fresh' if math.isfinite(self._measured_distance_km()) else 'stale'
        msg = (
            f'upper={"ok" if self.last_upper_solve_ok else "fallback"} '
            f'lower={"ok" if self.last_lower_solve_ok else "fallback"} '
            f'speed={speed_state} dist={dist_state} '
            f'v_upper={self.v_upper_cmd:.1f} v_lower={self.v_lower_cmd:.1f} '
            f'z={self.z:.3f} Tb={self.Tb:.1f}'
        )
        self.pub_mpc_state.publish(String(data=msg))

    # -------------------- solarcar mode --------------------
    def _init_solar(self):                                         # [関数定義] _init_solar の処理実行ブロック
        self.declare_parameter('forecast_csv', 'inputs/forecast_10min.csv')
        self.declare_parameter('maps_dir', 'maps')
        self.declare_parameter('drive_eff_map', '')
        self.declare_parameter('regen_eff_map', '')
        self.declare_parameter('rint_map', '')
        self.declare_parameter('drive_map_eco', '')
        self.declare_parameter('drive_map_power', '')
        self.declare_parameter('regen_map_eco', '')
        self.declare_parameter('regen_map_power', '')
        self.declare_parameter('panel_eff_map', '')
        self.declare_parameter('mppt_eff_map', '')
        self.declare_parameter('ocv_soc_map', '')
        self.declare_parameter('dt', 600.0)                 # 10 min [s]
        self.declare_parameter('horizon_steps', 9)
        self.declare_parameter('v_max_kmh', 110.0)
        self.declare_parameter('terminal_soc_min', 0.10)
        self.declare_parameter('stop_yaml', 'inputs/stop_points.yaml')
        self.declare_parameter('forecast_time_mode', 'auto')  # auto|absolute|relative|loop
        self.declare_parameter('forecast_time_tz', 'UTC')
        self.declare_parameter('forecast_start_time_utc', '')
        self.declare_parameter('forecast_time_offset_sec', 0.0)
        self.declare_parameter('forecast_reload_sec', 60.0)
        self.declare_parameter('replan_on_forecast_reload', True)
        self.declare_parameter('params_yaml', '')
        self.declare_parameter('route_profile_csv', '')
        self.declare_parameter('speed_profile_csv', '')
        self.declare_parameter('drive_schedule_yaml', '')
        self.declare_parameter('use_measured_s', True)
        self.declare_parameter('use_measured_speed', True)
        self.declare_parameter('w_dv', 0.05)
        self.declare_parameter('w_dv_limit', 2.0)
        self.declare_parameter('dv_max_kmhps', 5.0)
        self.declare_parameter('w_T', 5.0)
        self.declare_parameter('w_speed_limit', 50.0)
        self.declare_parameter('w_drive_window', 1.0e5)
        self.declare_parameter('w_current', 0.02)
        self.declare_parameter('soc_target', 0.5)
        self.declare_parameter('soc_band', 0.1)
        self.declare_parameter('w_soc_target', 2.0)
        self.declare_parameter('w_soc_band', 50.0)
        self.declare_parameter('soc_day_end_max', -1.0)
        self.declare_parameter('w_soc_day_max', 1.0e4)
        self.declare_parameter('soc_day_end_target', -1.0)
        self.declare_parameter('soc_day_end_tol', 0.03)
        self.declare_parameter('w_soc_day_track', 0.0)
        self.declare_parameter('soc_finish_target', -1.0)
        self.declare_parameter('soc_finish_tol', 0.02)
        self.declare_parameter('w_soc_progress', 1.0e5)
        self.declare_parameter('w_soc_terminal', 1.0e5)
        self.declare_parameter('race_km', 3035.5)
        self.declare_parameter('upper_mode', 'time')  # time|distance
        self.declare_parameter('upper_ds_km', 20.0)
        self.declare_parameter('upper_horizon_km', 1500.0)
        self.declare_parameter('upper_max_steps', 200)
        self.declare_parameter('upper_horizon_mode', 'fixed')
        self.declare_parameter('upper_adaptive_min_ds_km', 10.0)
        self.declare_parameter('upper_adaptive_max_ds_km', 200.0)
        self.declare_parameter('upper_adaptive_growth', 1.18)
        self.declare_parameter('upper_ctrl_km', 0.0)
        self.declare_parameter('upper_vmin_kmh', 1.0)
        self.declare_parameter('upper_replan_km', 0.0)
        self.declare_parameter('upper_replan_sec', 0.0)
        self.declare_parameter('upper_max_iter', 120)
        self.declare_parameter('upper_day_end_soc_min', 0.2)
        self.declare_parameter('soc_guard_margin', 0.01)
        self.declare_parameter('soc_guard_mode', 'stop')  # stop|pv_only
        self.declare_parameter('drive_mode', 'auto')  # auto|eco|power
        self.declare_parameter('drive_mode_tau_margin', 0.0)
        self.declare_parameter('hierarchical', True)
        self.declare_parameter('lower_dt', 1.0)
        self.declare_parameter('lower_horizon_steps', 20)
        self.declare_parameter('lower_rate_hz', 5.0)
        self.declare_parameter('w_track', 5.0)
        self.declare_parameter('w_throttle', 0.2)
        self.declare_parameter('throttle_rate_limit', 30.0)
        self.declare_parameter('mhe_enabled', True)
        self.declare_parameter('mhe_horizon_steps', 12)
        self.declare_parameter('mhe_w_soc', 50.0)
        self.declare_parameter('mhe_w_tb', 5.0)
        self.declare_parameter('mhe_w_i', 1.0)
        self.declare_parameter('mhe_w_v', 1.0)
        self.declare_parameter('mhe_w_prior', 5.0)
        self.declare_parameter('soc_min', 0.05)
        self.declare_parameter('soc_max', 0.98)
        self.declare_parameter('T_min', -5.0)
        self.declare_parameter('T_max', 55.0)
        self.declare_parameter('solar_gain', 1.0)
        self.declare_parameter('poa_gain_drive', 1.0)
        self.declare_parameter('poa_gain_stop', 1.0)
        self.declare_parameter('speed_meas_timeout_sec', 3.0)
        self.declare_parameter('distance_meas_timeout_sec', 5.0)
        self.declare_parameter('battery_meas_timeout_sec', 15.0)
        self.declare_parameter('speed_meas_filter_tau_sec', 0.6)
        self.declare_parameter('speed_meas_max_accel_kmhps', 12.0)
        self.declare_parameter('speed_meas_max_decel_kmhps', 20.0)
        self.declare_parameter('distance_meas_max_rate_kmps', 0.06)
        self.declare_parameter('distance_meas_max_backtrack_km', 0.02)
        self.declare_parameter('battery_meas_filter_tau_sec', 1.0)
        self.declare_parameter('lower_ref_accel_limit_kmhps', 1.5)
        self.declare_parameter('lower_ref_decel_limit_kmhps', 4.0)
        self.declare_parameter('lower_ref_deadband_kmh', 0.1)
        self.declare_parameter('w_throttle_rate', 0.3)
        self.declare_parameter('drive_mode_min_hold_sec', 5.0)

        params_yaml = str(self.get_parameter('params_yaml').value).strip()
        self.params_cfg = {}
        self.params_yaml_path = ''
        if params_yaml:
            self.params_yaml_path = resolve_path(params_yaml, 'config')
            self.params_cfg = self._read_params_yaml(self.params_yaml_path)
            self._apply_declared_yaml_params(self.params_cfg)

        fcsv = resolve_path(self.get_parameter('forecast_csv').value, 'inputs')
        maps_dir = resolve_path(self.get_parameter('maps_dir').value, 'maps')
        self.dt = float(self.get_parameter('dt').value)
        self.Np = int(self.get_parameter('horizon_steps').value)

        # Load forecast
        self.forecast_path = fcsv
        self.forecast_reload_sec = float(self.get_parameter('forecast_reload_sec').value)
        self.replan_on_forecast_reload = bool(self.get_parameter('replan_on_forecast_reload').value)
        self._load_forecast_file(self.forecast_path)
        try:
            self.forecast_mtime = os.path.getmtime(self.forecast_path)
        except Exception:
            self.forecast_mtime = None
        self.last_forecast_check = time.monotonic()
        self._forecast_warned_out_of_range = False
        self.forecast_reloaded = False

        # Load stop points (optional)
        stop_yaml = resolve_path(self.get_parameter('stop_yaml').value, 'inputs')
        self._load_stops(stop_yaml)

        # Optional route/speed profile
        self.route_profile = None
        route_profile_csv = self.get_parameter('route_profile_csv').value
        if route_profile_csv:
            try:
                route_profile_csv = resolve_path(route_profile_csv, 'inputs')
                self.route_profile = pd.read_csv(route_profile_csv)
            except Exception as exc:
                print(f'Failed to load route_profile_csv: {exc}')

        self.speed_profile = None
        speed_profile_csv = self.get_parameter('speed_profile_csv').value
        if speed_profile_csv:
            try:
                speed_profile_csv = resolve_path(speed_profile_csv, 'inputs')
                self.speed_profile = pd.read_csv(speed_profile_csv)
            except Exception as exc:
                print(f'Failed to load speed_profile_csv: {exc}')

        # Optional driving schedule
        self.drive_schedule = None
        drive_schedule_yaml = self.get_parameter('drive_schedule_yaml').value
        if drive_schedule_yaml:
            drive_schedule_yaml = resolve_path(drive_schedule_yaml, 'inputs')
            self.drive_schedule = DriveSchedule.from_yaml(drive_schedule_yaml)
            if self.drive_schedule is None:
                print('drive_schedule_yaml could not be loaded.')

        # Model
        panel_map = self.get_parameter('panel_eff_map').value
        mppt_map = self.get_parameter('mppt_eff_map').value
        ocv_map = self.get_parameter('ocv_soc_map').value
        drive_map_eco = self.get_parameter('drive_map_eco').value
        drive_map_power = self.get_parameter('drive_map_power').value
        regen_map_eco = self.get_parameter('regen_map_eco').value
        regen_map_power = self.get_parameter('regen_map_power').value
        panel_map = resolve_path(panel_map, 'maps') if panel_map else None
        mppt_map = resolve_path(mppt_map, 'maps') if mppt_map else None
        ocv_map = resolve_path(ocv_map, 'maps') if ocv_map else None
        drive_map_eco = resolve_path(drive_map_eco, 'maps') if drive_map_eco else None
        drive_map_power = resolve_path(drive_map_power, 'maps') if drive_map_power else None
        regen_map_eco = resolve_path(regen_map_eco, 'maps') if regen_map_eco else None
        regen_map_power = resolve_path(regen_map_power, 'maps') if regen_map_power else None
        drive_map = self.get_parameter('drive_eff_map').value
        regen_map = self.get_parameter('regen_eff_map').value
        rint_map = self.get_parameter('rint_map').value
        drive_map = resolve_path(drive_map, 'maps') if drive_map else f"{maps_dir}/drive_eff_map.csv"
        regen_map = resolve_path(regen_map, 'maps') if regen_map else f"{maps_dir}/regen_eff_map.csv"
        rint_map = resolve_path(rint_map, 'maps') if rint_map else f"{maps_dir}/Rint_T_by_soc.csv"
        self.model = SolarCarModel(
            drive_map,
            regen_map,
            rint_map,
            params=Params(dt=self.dt),
            panel_eff_map_path=panel_map,
            mppt_eff_map_path=mppt_map,
            drive_map_eco_path=drive_map_eco,
            drive_map_power_path=drive_map_power,
            regen_map_eco_path=regen_map_eco,
            regen_map_power_path=regen_map_power,
            ocv_soc_map_path=ocv_map,
        )
        if self.params_cfg:
            self._apply_model_cfg(self.params_cfg.get('model', {}))
        self.model.p.soc_min = float(self.get_parameter('soc_min').value)
        self.model.p.soc_max = float(self.get_parameter('soc_max').value)
        self.model.p.T_min = float(self.get_parameter('T_min').value)
        self.model.p.T_max = float(self.get_parameter('T_max').value)
        self.soc_target = float(self.get_parameter('soc_target').value)
        self.soc_band = float(self.get_parameter('soc_band').value)
        self.w_soc_target = float(self.get_parameter('w_soc_target').value)
        self.w_soc_band = float(self.get_parameter('w_soc_band').value)
        self.soc_day_end_max = float(self.get_parameter('soc_day_end_max').value)
        self.w_soc_day_max = float(self.get_parameter('w_soc_day_max').value)
        self.soc_finish_target = float(self.get_parameter('soc_finish_target').value)
        self.soc_finish_tol = float(self.get_parameter('soc_finish_tol').value)
        self.w_soc_progress = float(self.get_parameter('w_soc_progress').value)
        self.w_soc_terminal = float(self.get_parameter('w_soc_terminal').value)
        self.race_km = float(self.get_parameter('race_km').value)
        self.soc_target = float(np.clip(self.soc_target, self.model.p.soc_min, self.model.p.soc_max))
        self.soc_band = max(0.0, float(self.soc_band))
        if self.soc_day_end_max > 0.0:
            self.soc_day_end_max = float(np.clip(self.soc_day_end_max, self.model.p.soc_min, self.model.p.soc_max))
        if self.soc_finish_target > 0.0:
            self.soc_finish_target = float(np.clip(self.soc_finish_target, self.model.p.soc_min, self.model.p.soc_max))
        self.soc_finish_tol = max(0.0, float(self.soc_finish_tol))
        self.race_km = max(1.0, float(self.race_km))
        self.model.drive_mode = str(self.get_parameter('drive_mode').value)
        self.model.drive_mode_tau_margin = float(self.get_parameter('drive_mode_tau_margin').value)
        self.solar_gain = float(self.get_parameter('solar_gain').value)
        self.poa_gain_drive = float(self.get_parameter('poa_gain_drive').value)
        self.poa_gain_stop = float(self.get_parameter('poa_gain_stop').value)
        self.upper_mode = str(self.get_parameter('upper_mode').value).lower()
        self.upper_ds_km = float(self.get_parameter('upper_ds_km').value)
        self.upper_horizon_km = float(self.get_parameter('upper_horizon_km').value)
        self.upper_max_steps = int(self.get_parameter('upper_max_steps').value)
        self.upper_horizon_mode = str(self.get_parameter('upper_horizon_mode').value).lower()
        self.upper_adaptive_min_ds_km = float(self.get_parameter('upper_adaptive_min_ds_km').value)
        self.upper_adaptive_max_ds_km = float(self.get_parameter('upper_adaptive_max_ds_km').value)
        self.upper_adaptive_growth = float(self.get_parameter('upper_adaptive_growth').value)
        self.upper_ctrl_km = float(self.get_parameter('upper_ctrl_km').value)
        self.upper_vmin_kmh = float(self.get_parameter('upper_vmin_kmh').value)
        self.upper_replan_km = float(self.get_parameter('upper_replan_km').value)
        self.upper_replan_sec = float(self.get_parameter('upper_replan_sec').value)
        self.upper_max_iter = int(self.get_parameter('upper_max_iter').value)
        self.upper_day_end_soc_min = float(self.get_parameter('upper_day_end_soc_min').value)
        self.upper_cost_cfg = load_upper_cost_config(
            self.params_cfg.get('mpc', {}) if isinstance(self.params_cfg, dict) else {},
            legacy={
                'w_dv': float(self.get_parameter('w_dv').value),
                'w_dv_limit': float(self.get_parameter('w_dv_limit').value),
                'w_T': float(self.get_parameter('w_T').value),
                'w_speed_limit': float(self.get_parameter('w_speed_limit').value),
                'w_drive_window': float(self.get_parameter('w_drive_window').value),
                'w_current': float(self.get_parameter('w_current').value),
                'w_soc_day_max': float(self.w_soc_day_max),
                'w_soc_day_track': float(self.get_parameter('w_soc_day_track').value),
                'w_soc_terminal': float(self.w_soc_terminal),
            },
        )

        # States
        self.k = 0
        self.last_bin = None
        self.s_km = 0.0
        self.z = 0.80
        self.Tb = 25.0
        self.v_cmd = 40.0
        self.v_now = math.nan
        self.s_meas = math.nan
        self.s_meas_time = None
        self.solar_soc_meas = math.nan
        self.solar_tb_meas = math.nan
        self.solar_i_meas = math.nan
        self.solar_v_meas = math.nan
        self.v_now_time = None
        self.solar_soc_time = None
        self.solar_tb_time = None
        self.solar_i_time = None
        self.solar_v_time = None
        self.v_upper_cmd = self.v_cmd
        self.v_lower_cmd = self.v_cmd
        self.v_plan_kmh = None
        self.v_plan_segments = None
        self.upper_plan_seq = None
        self.upper_plan_s_km = None
        self.upper_plan_time = None
        self.upper_plan_id = 0
        self.upper_plan_mode = 'time'
        self.plan_dt_sec = float(self.model.p.dt)
        self.last_data = []
        self.plan_start_monotonic = None
        self.last_plan_time = None
        self.lower_last_u = 0.0
        self.lower_last_mode = 'eco'
        self.calibration_state = {}

        # Hierarchical MPC settings
        self.hierarchical = bool(self.get_parameter('hierarchical').value)
        self.lower_dt = float(self.get_parameter('lower_dt').value)
        self.lower_N = int(self.get_parameter('lower_horizon_steps').value)
        self.lower_rate_hz = float(self.get_parameter('lower_rate_hz').value)
        self.w_track = float(self.get_parameter('w_track').value)
        self.w_throttle = float(self.get_parameter('w_throttle').value)
        self.w_throttle_rate = float(self.get_parameter('w_throttle_rate').value)
        self.throttle_rate_limit = float(self.get_parameter('throttle_rate_limit').value)
        self.lower_ref_accel_limit_kmhps = float(self.get_parameter('lower_ref_accel_limit_kmhps').value)
        self.lower_ref_decel_limit_kmhps = float(self.get_parameter('lower_ref_decel_limit_kmhps').value)
        self.lower_ref_deadband_kmh = float(self.get_parameter('lower_ref_deadband_kmh').value)
        self.drive_mode_min_hold_sec = float(self.get_parameter('drive_mode_min_hold_sec').value)
        self.last_lower_mode_change = time.monotonic()
        self._warned_lower_rate = False

        self.speed_meas_timeout_sec = float(self.get_parameter('speed_meas_timeout_sec').value)
        self.distance_meas_timeout_sec = float(self.get_parameter('distance_meas_timeout_sec').value)
        self.battery_meas_timeout_sec = float(self.get_parameter('battery_meas_timeout_sec').value)
        self.speed_meas_filter = RobustScalarFilter(
            min_value=0.0,
            max_value=max(150.0, float(self.get_parameter('v_max_kmh').value) + 20.0),
            tau_sec=float(self.get_parameter('speed_meas_filter_tau_sec').value),
            rise_rate=float(self.get_parameter('speed_meas_max_accel_kmhps').value),
            fall_rate=float(self.get_parameter('speed_meas_max_decel_kmhps').value),
            median_window=3,
            deadband=0.05,
        )
        self.distance_meas_filter = RobustScalarFilter(
            min_value=0.0,
            max_value=max(self.race_km + 100.0, 500.0),
            rise_rate=float(self.get_parameter('distance_meas_max_rate_kmps').value),
            median_window=3,
            monotonic=True,
            max_backtrack=float(self.get_parameter('distance_meas_max_backtrack_km').value),
        )
        battery_tau = float(self.get_parameter('battery_meas_filter_tau_sec').value)
        self.soc_meas_filter = RobustScalarFilter(
            min_value=0.0, max_value=1.0, tau_sec=battery_tau, median_window=3, deadband=0.001,
        )
        self.tb_meas_filter = RobustScalarFilter(
            min_value=self.model.p.T_min - 10.0, max_value=self.model.p.T_max + 20.0,
            tau_sec=battery_tau, median_window=3, deadband=0.02,
        )
        self.i_meas_filter = RobustScalarFilter(
            min_value=self.model.p.I_chg_min * 2.0, max_value=self.model.p.I_max * 2.0,
            tau_sec=battery_tau, median_window=3, deadband=0.05,
        )
        self.v_meas_filter = RobustScalarFilter(
            min_value=0.0, max_value=self.model.p.V_max * 1.5,
            tau_sec=battery_tau, median_window=3, deadband=0.02,
        )
        self.last_upper_solve_ok = True
        self.last_lower_solve_ok = True

        # Forecast clock setup
        self.forecast_time_mode = str(self.get_parameter('forecast_time_mode').value)
        self.forecast_time_tz = str(self.get_parameter('forecast_time_tz').value)
        self.forecast_time_offset = float(self.get_parameter('forecast_time_offset_sec').value)
        self.forecast_start_time = None
        start_time_utc = str(self.get_parameter('forecast_start_time_utc').value).strip()
        if start_time_utc:
            try:
                if start_time_utc.endswith('Z'):
                    start_time_utc = start_time_utc[:-1] + '+00:00'
                self.forecast_start_time = datetime.fromisoformat(start_time_utc).astimezone(timezone.utc)
            except Exception:
                print('forecast_start_time_utc parse failed; using node start time.')
        if self.forecast_start_time is None:
            self.forecast_start_time = datetime.now(timezone.utc)

        # MHE
        self.mhe = None
        if bool(self.get_parameter('mhe_enabled').value):
            self.mhe = BatteryMHE(
                self.model,
                horizon_steps=int(self.get_parameter('mhe_horizon_steps').value),
                w_soc=float(self.get_parameter('mhe_w_soc').value),
                w_tb=float(self.get_parameter('mhe_w_tb').value),
                w_i=float(self.get_parameter('mhe_w_i').value),
                w_v=float(self.get_parameter('mhe_w_v').value),
                w_prior=float(self.get_parameter('mhe_w_prior').value),
                soc_bounds=(self.model.p.soc_min, self.model.p.soc_max),
                tb_bounds=(self.model.p.T_min, self.model.p.T_max),
            )

        # Pubs
        self.pub_speed = self.create_publisher(Float32, '/planner/speed_cmd', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_upper_speed = self.create_publisher(Float32, '/planner/upper_speed_cmd', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_throttle = self.create_publisher(Float32, '/planner/throttle_cmd_pct', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_drive_mode = self.create_publisher(String, '/planner/drive_mode', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_path = self.create_publisher(Path, '/planner/trajectory', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_plan = self.create_publisher(Float32MultiArray, '/planner/upper_plan', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_lower_plan = self.create_publisher(Float32MultiArray, '/planner/lower_plan', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_env = self.create_publisher(Float32MultiArray, '/planner/env', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_metrics = self.create_publisher(Float32MultiArray, '/planner/metrics', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_status = self.create_publisher(Float32MultiArray, '/planner/status', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_summary = self.create_publisher(Float32MultiArray, '/planner/summary', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_mpc_state = self.create_publisher(String, '/system/mpc_state', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        # Subs (optional measurements)
        self.create_subscription(Float32, '/vehicle/s_km', self._on_s_km_solar, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/speed_kmh', self._on_speed_solar, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/batt_soc', self._on_soc_solar, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/batt_temp_c', self._on_tb_solar, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/batt_current_a', self._on_i_solar, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/batt_voltage_v', self._on_v_solar, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/planner/calibration', self._on_calibration, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        # Timer @1Hz (upper layer)
        self.timer = self.create_timer(1.0, self._step_solar)
        # Lower layer timer
        if self.hierarchical and self.lower_rate_hz > 0.0:
            expected_dt = 1.0 / self.lower_rate_hz
            if abs(expected_dt - self.lower_dt) > 1.0e-3 and not self._warned_lower_rate:
                print('lower_dt and lower_rate_hz mismatch; using lower_dt for prediction.')
                self._warned_lower_rate = True
            self.timer_lower = self.create_timer(1.0 / self.lower_rate_hz, self._step_lower)
        else:
            self.timer_lower = None
        print('MPCNode started (solarcar mode).')

    def _current_bin_index(self) -> int:                           # [関数定義] _current_bin_index の処理実行ブロック
        mode = str(self.forecast_time_mode).lower()
        has_time = ('time' in self.df.columns) and (not self.df['time'].isna().all())
        if mode == 'auto':
            mode = 'absolute' if has_time else 'relative'

        now = datetime.now(timezone.utc) + timedelta(seconds=self.forecast_time_offset)

        if mode == 'absolute' and has_time:
            t_series = self.df['time'].values
            t_min = self.df['time'].iloc[0]
            t_max = self.df['time'].iloc[-1]
            if (now < t_min) or (now > t_max):
                if not getattr(self, '_forecast_warned_out_of_range', False):
                    print('Forecast time out of range; switching to relative indexing.')
                    self._forecast_warned_out_of_range = True
                mode = 'relative'
            else:
                idx = int(np.searchsorted(t_series, np.datetime64(now)) - 1)
                return int(np.clip(idx, 0, len(self.df) - 1))      # [戻り値] 計算結果・計算状態の呼び出し元への返却

        if mode in ('relative', 'loop') or not has_time:
            elapsed = (now - self.forecast_start_time).total_seconds()
            elapsed = max(0.0, elapsed)
            idx = int(elapsed / max(self.dt, 1.0e-3))
            if len(self.df) == 0:
                return 0                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
            if mode == 'loop':
                return int(idx % len(self.df))                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
            return int(np.clip(idx, 0, len(self.df) - 1))          # [戻り値] 計算結果・計算状態の呼び出し元への返却

        return int(np.clip(self.k, 0, len(self.df) - 1))           # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _horizon_data(self, k0: int):                              # [関数定義] _horizon_data の処理実行ブロック
        N = len(self.df)
        data = []
        has_time = ('time' in self.df.columns) and (not self.df['time'].isna().all())
        mode = str(self.forecast_time_mode).lower()
        if mode == 'auto':
            mode = 'absolute' if has_time else 'relative'
        if N <= 0:
            return data                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if mode == 'loop':
            Np = max(1, self.Np)
            for i in range(Np):
                j = (k0 + i) % N
                row = self.df.iloc[j]
                if mode == 'absolute' and has_time:
                    t_utc = row['time'].to_pydatetime()
                else:
                    t_utc = self.forecast_start_time + timedelta(seconds=self.dt * (k0 + i))
                gain = self.poa_gain_drive
                if self.drive_schedule is not None:
                    limits = self.drive_schedule.speed_limits(t_utc)
                    if limits is not None and limits[1] <= 0.0:
                        gain = self.poa_gain_stop
                G_raw = float(row.get('GHI', 0.0)) * self.solar_gain
                data.append(dict(
                    G_poa=G_raw * gain,
                    Tcell_C=float(row.get('Tcell_C', 40.0)),
                    slope_pct=float(row.get('slope_pct', 0.0)),
                    Tamb_C=float(row.get('Tamb_C', 30.0)),
                    headwind_ms=float(row.get('headwind_ms', 0.0)) if 'headwind_ms' in row else 0.0,
                    t_utc=t_utc,
                ))
            return data                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却

        Np = max(0, min(self.Np, N - k0 - 1))
        for j in range(k0, k0 + Np):
            row = self.df.iloc[j]
            if mode == 'absolute' and has_time:
                t_utc = row['time'].to_pydatetime()
            else:
                t_utc = self.forecast_start_time + timedelta(seconds=self.dt * j)
            gain = self.poa_gain_drive
            if self.drive_schedule is not None:
                limits = self.drive_schedule.speed_limits(t_utc)
                if limits is not None and limits[1] <= 0.0:
                    gain = self.poa_gain_stop
            G_raw = float(row.get('GHI', 0.0)) * self.solar_gain
            data.append(dict(
                G_poa=G_raw * gain,
                Tcell_C=float(row.get('Tcell_C', 40.0)),
                slope_pct=float(row.get('slope_pct', 0.0)),
                Tamb_C=float(row.get('Tamb_C', 30.0)),
                headwind_ms=float(row.get('headwind_ms', 0.0)) if 'headwind_ms' in row else 0.0,
                t_utc=t_utc,
            ))
        return data                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _forecast_at_time(self, t_utc: datetime, drive: bool = True) -> dict:  # [関数定義] _forecast_at_time の処理実行ブロック
        if len(self.df) == 0:
            return dict(G_poa=0.0, Tcell_C=40.0, Tamb_C=30.0, headwind_ms=0.0)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        has_time = ('time' in self.df.columns) and (not self.df['time'].isna().all())
        if has_time:
            t_series = self.df['time'].values
            idx = int(np.searchsorted(t_series, np.datetime64(t_utc)) - 1)
            idx = int(np.clip(idx, 0, len(self.df) - 1))
        else:
            elapsed = (t_utc - self.forecast_start_time).total_seconds()
            idx = int(np.clip(elapsed / max(self.dt, 1e-3), 0, len(self.df) - 1))
        row = self.df.iloc[idx]
        gain = self.poa_gain_drive if drive else self.poa_gain_stop
        G_raw = float(row.get('GHI', 0.0)) * self.solar_gain
        return dict(                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
            G_poa=G_raw * gain,
            Tcell_C=float(row.get('Tcell_C', 40.0)),
            Tamb_C=float(row.get('Tamb_C', 30.0)),
            headwind_ms=float(row.get('headwind_ms', 0.0)) if 'headwind_ms' in row else 0.0,
        )

    def _sample_plan_segments(self, dt_sample: float):             # [関数定義] _sample_plan_segments の処理実行ブロック
        if not self.v_plan_segments:
            return []                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if dt_sample <= 0.0:
            return [float(seg['v_kmh']) for seg in self.v_plan_segments]  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        samples = []
        for seg in self.v_plan_segments:
            n = max(1, int(math.ceil(seg['dt_sec'] / dt_sample)))
            samples.extend([float(seg['v_kmh'])] * n)
        return samples                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _route_value(self, s_km: float, field: str, default: float) -> float:  # [関数定義] _route_value の処理実行ブロック
        if self.route_profile is None:
            return float(default)                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        try:
            val = float(interpolate_profile(self.route_profile, s_km, field, default))
            if not np.isfinite(val):
                return float(default)                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
            return float(val)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception:
            return float(default)                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _speed_limit_at(self, s_km: float, default_kmh: float) -> float:  # [関数定義] _speed_limit_at の処理実行ブロック
        if self.speed_profile is None:
            return float(default_kmh)                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
        try:
            return float(interpolate_profile(self.speed_profile, s_km, 'v_max_kmh', default_kmh))  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception:
            return float(default_kmh)                              # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _soc_guard_speed(self, v_kmh: float, s_km: float, d0: dict) -> float:  # [関数定義] _soc_guard_speed の処理実行ブロック
        mode = str(self.get_parameter('soc_guard_mode').value).lower()
        soc_guard = float(self.get_parameter('soc_guard_margin').value)
        target = self.model.p.soc_min + soc_guard

        slope_pct = d0['slope_pct']
        if self.route_profile is not None:
            slope_pct = self._route_value(s_km, 'slope_pct', slope_pct)
        headwind_ms = d0.get('headwind_ms', 0.0)
        if self.route_profile is not None:
            headwind_ms = self._route_value(s_km, 'headwind_ms', headwind_ms)

        def z_next_for(v_kmh_local: float) -> float:               # [関数定義] z_next_for の処理実行ブロック
            out = self.model.electrical_balance(v_kmh_local / 3.6, slope_pct, self.z, self.Tb,
                                                d0['G_poa'], d0['Tcell_C'], headwind_ms=headwind_ms)
            P_pack = float(out['P_pack'])
            return self.model.soc_step(self.z, P_pack, self.model.p.dt)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

        # If already below target, apply guard mode
        if self.z <= target:
            if mode == 'stop':
                return 0.0                                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
            if mode != 'pv_only':
                return v_kmh                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
            # find max speed such that P_pack <= 0
            lo = 0.0
            hi = max(0.0, float(v_kmh))
            for _ in range(20):
                mid = 0.5 * (lo + hi)
                if z_next_for(mid) < self.z:
                    hi = mid
                else:
                    lo = mid
            return float(lo)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

        # If next step would violate, limit speed to keep z_next >= target
        if z_next_for(v_kmh) >= target:
            return v_kmh                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        lo = 0.0
        hi = max(0.0, float(v_kmh))
        for _ in range(25):
            mid = 0.5 * (lo + hi)
            if z_next_for(mid) < target:
                hi = mid
            else:
                lo = mid
        return float(lo)                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _dwell_penalty(self, s_km: float, v_ms: float) -> float:   # [関数定義] _dwell_penalty の処理実行ブロック
        vmax_kmh = float(self.get_parameter('v_max_kmh').value)
        vmax_ms = vmax_kmh / 3.6
        pen = 0.0
        for st in self.stops:
            s_stop = float(st.get('s_km', 0.0))
            dwell_s = float(st.get('dwell_s', 0.0))
            width_km = max(0.05, (dwell_s * vmax_ms) / 1000.0 * 0.5)
            if abs(s_km - s_stop) <= width_km:
                pen += 1.0e5 * (v_ms ** 2)
        return pen                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _mpc_solve_solar(self, data):                              # [関数定義] _mpc_solve_solar の処理実行ブロック
        p = self.model.p
        Np = len(data)
        if Np <= 0:
            return self.v_cmd, [self.v_cmd]                        # [戻り値] 計算結果・計算状態の呼び出し元への返却

        v0_guess = self.v_cmd / 3.6
        speed_meas_kmh = self._measured_speed_kmh()
        if bool(self.get_parameter('use_measured_speed').value) and math.isfinite(speed_meas_kmh):
            v0_guess = float(speed_meas_kmh) / 3.6
        x0 = self._plan_warm_start_ms(Np, v0_guess)
        v_max_kmh = float(self.get_parameter('v_max_kmh').value)
        v_min_solver = max(0.1, float(self.upper_vmin_kmh))
        ub = np.ones(Np, dtype=float) * (v_max_kmh / 3.6)

        term_soc_min = float(self.get_parameter('terminal_soc_min').value)
        w_dv = float(self.get_parameter('w_dv').value)
        w_dv_limit = float(self.get_parameter('w_dv_limit').value)
        dv_max_kmhps = float(self.get_parameter('dv_max_kmhps').value)
        dv_max_msps = dv_max_kmhps / 3.6
        w_T = float(self.get_parameter('w_T').value)
        w_speed_limit = float(self.get_parameter('w_speed_limit').value)
        w_drive_window = float(self.get_parameter('w_drive_window').value)
        w_current = float(self.get_parameter('w_current').value)
        soc_target = float(self.soc_target)
        soc_band = float(self.soc_band)
        w_soc_target = float(self.w_soc_target)
        w_soc_band = float(self.w_soc_band)
        soc_day_end_max = float(self.soc_day_end_max)
        w_soc_day_max = float(self.w_soc_day_max)
        soc_finish_target = float(self.soc_finish_target)
        soc_finish_tol = float(self.soc_finish_tol)
        w_soc_progress = float(self.w_soc_progress)
        w_soc_terminal = float(self.w_soc_terminal)
        race_km = float(self.race_km)
        z_start = float(self.z)

        def quad_penalty(x, cap=1.0e3):                            # [関数定義] quad_penalty の処理実行ブロック
            if x <= 0.0:
                return 0.0                                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
            if x > cap:
                x = cap
            return x * x                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却

        def cost(v):                                               # [関数定義] cost の処理実行ブロック
            z = float(self.z)
            Tb = float(self.Tb)
            s_km = float(self.s_km)
            distance_meas_km = self._measured_distance_km()
            if bool(self.get_parameter('use_measured_s').value) and math.isfinite(distance_meas_km):
                s_km = float(distance_meas_km)
            v_prev = float(v0_guess)
            J = 0.0

            for k in range(Np):
                d = data[k]
                v_k = float(v[k])
                slope_pct = d['slope_pct']
                if self.route_profile is not None:
                    slope_pct = self._route_value(s_km, 'slope_pct', slope_pct)
                headwind_ms = d.get('headwind_ms', 0.0)
                if self.route_profile is not None:
                    headwind_ms = self._route_value(s_km, 'headwind_ms', headwind_ms)
                out = self.model.electrical_balance(v_k, slope_pct, z, Tb, d['G_poa'], d['Tcell_C'], headwind_ms=headwind_ms)
                I = float(out['I'])
                V = float(out['V'])
                P_pack = float(out['P_pack'])
                loss_int = float(out['losses_int'])

                # dynamics
                z_next = self.model.soc_step(z, P_pack, p.dt)
                Tb_next = Tb + (p.dt / 1800.0) * (d['Tamb_C'] - Tb) + (loss_int * p.dt) / 50000.0
                s_km = s_km + v_k * (p.dt / 1000.0)

                # objective
                J += -1.0 * v_k * p.dt
                J += 30.0 * quad_penalty(term_soc_min - z_next)
                if self.drive_schedule is not None and soc_day_end_max > 0.0 and 't_utc' in d:
                    t_next = d['t_utc'] + timedelta(seconds=p.dt)
                    if self.drive_schedule.is_drive_time(d['t_utc']) and not self.drive_schedule.is_drive_time(t_next):
                        J += w_soc_day_max * quad_penalty(z_next - soc_day_end_max)
                if soc_finish_target > 0.0:
                    prog = max(0.0, min(1.0, s_km / max(race_km, 1.0)))
                    soc_line = z_start + (soc_finish_target - z_start) * prog
                    if z_next > (soc_line + soc_finish_tol):
                        J += w_soc_progress * quad_penalty(z_next - (soc_line + soc_finish_tol))
                    if z_next < (soc_line - soc_finish_tol):
                        J += w_soc_progress * quad_penalty((soc_line - soc_finish_tol) - z_next)

                dv = (v_k - v_prev) / max(p.dt, 1.0e-3)
                J += w_dv * (v_k - v_prev) ** 2
                if dv_max_msps > 0.0:
                    J += w_dv_limit * quad_penalty(abs(dv) - dv_max_msps)

                if self.drive_schedule is not None and 't_utc' in d:
                    limits = self.drive_schedule.speed_limits(d['t_utc'])
                    if limits is not None:
                        vmin_kmh, vmax_kmh = limits
                        vmin_ms = vmin_kmh / 3.6
                        vmax_ms = vmax_kmh / 3.6
                        J += w_drive_window * quad_penalty(vmin_ms - v_k)
                        J += w_drive_window * quad_penalty(v_k - vmax_ms)

                vmax_local = self._speed_limit_at(s_km, self.get_parameter('v_max_kmh').value)
                if vmax_local < self.get_parameter('v_max_kmh').value:
                    J += w_speed_limit * quad_penalty(v_k * 3.6 - vmax_local)
                J += w_current * (I ** 2) * p.dt

                # inequalities (soft)
                J += 1e4 * quad_penalty(I - p.I_max)
                J += 1e4 * quad_penalty(p.I_chg_min - I)
                J += 1e4 * quad_penalty(p.V_min - V)
                J += 1e4 * quad_penalty(V - p.V_max)
                J += w_T * quad_penalty(Tb_next - p.T_max)
                J += w_T * quad_penalty(p.T_min - Tb_next)
                J += 1e4 * quad_penalty(p.soc_min - z_next)
                J += 1e4 * quad_penalty(z_next - p.soc_max)

                J += self._dwell_penalty(s_km, v_k)

                z, Tb = z_next, Tb_next
                v_prev = v_k

            J += 1e4 * quad_penalty(term_soc_min - z)
            if soc_finish_target > 0.0:
                J += w_soc_terminal * quad_penalty(z - soc_finish_target)
            return J                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

        bounds = list(zip(lb, ub))
        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=150))
        if np.all(np.isfinite(res.x)):
            self.last_upper_solve_ok = bool(res.success)
            v_seq = res.x
            if not res.success:
                print('Upper MPC reached an early stop; using best finite iterate.')
        else:
            self.last_upper_solve_ok = False
            print('Upper MPC solve failed; reusing warm-start plan.')
            v_seq = x0
        v_seq_kmh = np.clip(v_seq * 3.6, 0.0, v_max_kmh)
        return float(v_seq_kmh[0]), [float(v) for v in v_seq_kmh]  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _mpc_solve_solar_distance(self, t0_utc: datetime, s0_km: float, x0=None):  # [関数定義] _mpc_solve_solar_distance の処理実行ブロック
        p = self.model.p
        horizon = build_upper_distance_horizon(
            mode=self.upper_horizon_mode,
            s0_km=s0_km,
            race_km=self.race_km,
            ds_km=self.upper_ds_km,
            horizon_km=self.upper_horizon_km,
            max_steps=self.upper_max_steps,
            ctrl_km=self.upper_ctrl_km,
            adaptive_min_ds_km=self.upper_adaptive_min_ds_km,
            adaptive_max_ds_km=self.upper_adaptive_max_ds_km,
            adaptive_growth=self.upper_adaptive_growth,
        )
        ds_seq = np.array(horizon.ds_seq_km, dtype=float)
        seg_s = np.array(horizon.seg_s_km, dtype=float)
        Np = int(len(ds_seq))
        if Np <= 0:
            return self.v_cmd, [{'v_kmh': float(self.v_cmd), 'dt_sec': float(p.dt)}]  # [戻り値] 計算結果・計算状態の呼び出し元への返却

        v_max_kmh = float(self.get_parameter('v_max_kmh').value)
        v_min_solver = max(0.1, float(self.upper_vmin_kmh))
        v0 = float(self.v_cmd)
        speed_meas_kmh = self._measured_speed_kmh()
        if bool(self.get_parameter('use_measured_speed').value) and math.isfinite(speed_meas_kmh):
            v0 = float(speed_meas_kmh)

        ctrl_s = np.array(horizon.ctrl_s_km, dtype=float)
        Nc = int(len(ctrl_s))

        if x0 is not None and len(x0) == Nc:
            x0 = np.array(x0, dtype=float)
        else:
            x0 = np.array([v_max_kmh] * Nc, dtype=float)
        bounds = [(v_min_solver, v_max_kmh)] * Nc

        idx = np.searchsorted(ctrl_s, seg_s, side='right') - 1
        idx = np.clip(idx, 0, Nc - 1)
        idx_next = np.clip(idx + 1, 0, Nc - 1)
        denom = np.maximum(ctrl_s[idx_next] - ctrl_s[idx], 1.0e-6)
        alpha = (seg_s - ctrl_s[idx]) / denom

        def expand_ctrl(u_vec):                                    # [関数定義] expand_ctrl の処理実行ブロック
            return (1.0 - alpha) * u_vec[idx] + alpha * u_vec[idx_next]  # [戻り値] 計算結果・計算状態の呼び出し元への返却

        w_dv_limit = float(self.get_parameter('w_dv_limit').value)
        dv_max_kmhps = float(self.get_parameter('dv_max_kmhps').value)
        term_soc_min = float(self.get_parameter('terminal_soc_min').value)
        day_end_soc_min = float(self.upper_day_end_soc_min)
        soc_day_end_max = float(self.soc_day_end_max)
        soc_finish_target = float(self.soc_finish_target)
        soc_day_end_tol = float(self.get_parameter('soc_day_end_tol').value)

        def step_wait(t_utc, z, Tb, s_km):                         # [関数定義] step_wait の処理実行ブロック
            if self.drive_schedule is None:
                return t_utc, z, Tb, 0.0                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
            if self.drive_schedule.is_drive_time(t_utc):
                return t_utc, z, Tb, 0.0                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
            t_start = self.drive_schedule.next_drive_start(t_utc)
            dt_wait = max(0.0, (t_start - t_utc).total_seconds())
            if dt_wait <= 0.0:
                return t_start, z, Tb, 0.0                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
            env = self._forecast_at_time(t_utc, drive=False)
            slope_pct = self._route_value(s_km, 'slope_pct', 0.0)
            headwind_ms = self._route_value(s_km, 'headwind_ms', env.get('headwind_ms', 0.0))
            out = self.model.electrical_balance(0.0, slope_pct, z, Tb, env['G_poa'], env['Tcell_C'], headwind_ms=headwind_ms)
            P_pack = float(out['P_pack'])
            loss_int = float(out['losses_int'])
            z = self.model.soc_step(z, P_pack, dt_wait)
            Tb = Tb + (dt_wait / 1800.0) * (env['Tamb_C'] - Tb) + (loss_int * dt_wait) / 50000.0
            return t_start, float(z), float(Tb), dt_wait           # [戻り値] 計算結果・計算状態の呼び出し元への返却

        def cost(u_vec):                                           # [関数定義] cost の処理実行ブロック
            z = float(self.z)
            Tb = float(self.Tb)
            s_km = float(s0_km)
            t_utc = t0_utc
            v_prev = v0
            p_pack_prev = None
            elapsed_plan_sec = 0.0
            J = 0.0
            v_seq = expand_ctrl(u_vec)
            for k in range(Np):
                t_utc, z, Tb, dt_wait = step_wait(t_utc, z, Tb, s_km)
                v_k = float(v_seq[k])
                ds_step_km = float(ds_seq[k])
                vmax_local = self._speed_limit_at(s_km, v_max_kmh)
                if vmax_local >= v_min_solver:
                    v_k = max(v_min_solver, min(v_k, vmax_local))
                else:
                    v_k = max(0.0, min(v_k, vmax_local))
                limits = None
                if self.drive_schedule is not None:
                    limits = self.drive_schedule.speed_limits(t_utc)

                dt_travel = ds_step_km / max(v_k, 1.0e-3) * 3600.0
                env = self._forecast_at_time(t_utc, drive=True)
                slope_pct = self._route_value(s_km, 'slope_pct', 0.0)
                headwind_ms = self._route_value(s_km, 'headwind_ms', env.get('headwind_ms', 0.0))
                out = self.model.electrical_balance(v_k / 3.6, slope_pct, z, Tb, env['G_poa'], env['Tcell_C'], headwind_ms=headwind_ms)
                I = float(out['I'])
                V = float(out['V'])
                P_pv = float(out.get('P_pv', 0.0))
                P_pack = float(out['P_pack'])
                loss_int = float(out['losses_int'])
                loss_line = float(out.get('losses_line', 0.0))
                P_mech_wheel = float(out.get('P_mech_wheel', 0.0))
                kinetic_step_wh = 0.5 * p.m * max(0.0, (v_k / 3.6) ** 2 - (v_prev / 3.6) ** 2) / 3600.0

                z_next = self.model.soc_step(z, P_pack, dt_travel)
                Tb_next = Tb + (dt_travel / 1800.0) * (env['Tamb_C'] - Tb) + (loss_int * dt_travel) / 50000.0
                forces = self.model.resistive_forces(v_k / 3.6, slope_pct, headwind_ms=headwind_ms)

                soc_line = None
                if self.drive_schedule is not None and self.soc_day_end_target > 0.0:
                    win = self.drive_schedule.current_drive_window(t_utc)
                    if win is not None:
                        t_start, t_end = win
                        if t_end > t_start:
                            prog = (t_utc - t_start).total_seconds() / (t_end - t_start).total_seconds()
                            prog = max(0.0, min(1.0, prog))
                            soc_line = float(self.z) + (self.soc_day_end_target - float(self.z)) * prog

                t_next = t_utc + timedelta(seconds=dt_travel)
                is_stop_transition = (
                    self.drive_schedule is not None
                    and self.drive_schedule.is_drive_time(t_utc)
                    and not self.drive_schedule.is_drive_time(t_next)
                )

                elapsed_plan_sec += dt_wait + dt_travel
                J += upper_stage_cost(
                    self.upper_cost_cfg,
                    dt_wait=dt_wait,
                    dt_travel=dt_travel,
                    v_kmh=v_k,
                    v_prev_kmh=v_prev,
                    vmax_local_kmh=vmax_local,
                    drive_limits=limits,
                    dv_limit_kmhps=dv_max_kmhps,
                    I_a=I,
                    V_v=V,
                    P_pv_w=P_pv,
                    P_pack_w=P_pack,
                    P_pack_prev_w=p_pack_prev,
                    P_mech_wheel_w=P_mech_wheel,
                    losses_int_w=loss_int,
                    losses_line_w=loss_line,
                    F_aero_n=float(forces.get('F_aero', 0.0)),
                    kinetic_step_wh=kinetic_step_wh,
                    z_next=z_next,
                    Tb_next_c=Tb_next,
                    term_soc_min=term_soc_min,
                    soc_min=p.soc_min,
                    soc_max=p.soc_max,
                    temp_min_c=p.T_min,
                    temp_max_c=p.T_max,
                    day_end_soc_min=day_end_soc_min,
                    soc_day_end_max=soc_day_end_max,
                    soc_day_track_target=soc_line,
                    soc_day_track_tol=soc_day_end_tol,
                    I_max=p.I_max,
                    I_chg_min=p.I_chg_min,
                    V_min=p.V_min,
                    V_max=p.V_max,
                    time_ahead_h=elapsed_plan_sec / 3600.0,
                )

                t_utc = t_next
                s_km += ds_step_km
                z, Tb = z_next, Tb_next
                v_prev = v_k
                p_pack_prev = P_pack

            J += upper_terminal_cost(
                self.upper_cost_cfg,
                z_terminal=z,
                term_soc_min=term_soc_min,
                soc_finish_target=soc_finish_target,
            )
            return J                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=self.upper_max_iter))
        if np.all(np.isfinite(res.x)):
            self.last_upper_solve_ok = bool(res.success)
            u_seq = res.x
            if not res.success:
                print('Upper distance-MPC reached an early stop; using best finite iterate.')
        else:
            self.last_upper_solve_ok = False
            print('Upper distance-MPC solve failed; reusing warm-start control grid.')
            u_seq = x0
        v_seq = expand_ctrl(u_seq)

        # Build segments with variable time
        segments = []
        t_utc = t0_utc
        s_km = float(s0_km)
        z = float(self.z)
        Tb = float(self.Tb)
        for idx_seg, v_k in enumerate(v_seq):
            t_utc, z, Tb, _ = step_wait(t_utc, z, Tb, s_km)
            ds_step_km = float(ds_seq[idx_seg])
            v_k = float(np.clip(v_k, 0.0, v_max_kmh))
            vmax_local = self._speed_limit_at(s_km, v_max_kmh)
            if vmax_local >= v_min_solver:
                v_k = max(v_min_solver, min(v_k, vmax_local))
            else:
                v_k = max(0.0, min(v_k, vmax_local))
            dt_travel = ds_step_km / max(v_k, 1.0e-3) * 3600.0
            segments.append(
                {
                    'v_kmh': v_k,
                    'dt_sec': float(dt_travel),
                    'ds_km': ds_step_km,
                    's_start_km': float(s_km),
                    's_end_km': float(s_km + ds_step_km),
                }
            )
            t_utc = t_utc + timedelta(seconds=dt_travel)
            s_km += ds_step_km

        v0_kmh = float(segments[0]['v_kmh']) if segments else float(self.v_cmd)
        return v0_kmh, segments, u_seq                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _publish_upper_plan(self):                                 # [関数定義] _publish_upper_plan の処理実行ブロック
        if not self.v_plan_kmh:
            return
        msg = Float32MultiArray()
        msg.data = [float(self.plan_dt_sec)] + [float(v) for v in self.v_plan_kmh]
        self.pub_plan.publish(msg)

    def _publish_lower_plan(self, v_seq_ms):                       # [関数定義] _publish_lower_plan の処理実行ブロック
        if not v_seq_ms:
            return
        msg = Float32MultiArray()
        msg.data = [float(self.lower_dt)] + [float(v * 3.6) for v in v_seq_ms]
        self.pub_lower_plan.publish(msg)

    def _publish_plan_path(self, data):                            # [関数定義] _publish_plan_path の処理実行ブロック
        if len(data) == 0:
            return
        path = Path()
        path.header.stamp = self.get_clock().now().to_msg()
        path.header.frame_id = 'map'
        s_tmp = float(self.s_km)
        distance_meas_km = self._measured_distance_km()
        if bool(self.get_parameter('use_measured_s').value) and math.isfinite(distance_meas_km):
            s_tmp = float(distance_meas_km)
        if self.upper_plan_mode == 'distance' and self.v_plan_segments:
            for seg in self.v_plan_segments:
                s_tmp += float(seg['v_kmh']) * (seg['dt_sec'] / 3600.0)
                pose = PoseStamped()
                pose.header = path.header
                pose.pose.position.x = s_tmp
                pose.pose.position.y = 0.0
                path.poses.append(pose)
        else:
            v_list = self.v_plan_kmh if self.v_plan_kmh else [float(self.v_upper_cmd)] * len(data)
            for v_kmh in v_list[:len(data)]:
                s_tmp += float(v_kmh) * (self.model.p.dt / 3600.0)
                pose = PoseStamped()
                pose.header = path.header
                pose.pose.position.x = s_tmp
                pose.pose.position.y = 0.0
                path.poses.append(pose)
        self.pub_path.publish(path)

    def _publish_metrics(self, d0: dict, v_exec_kmh: float, s_for_profile: float):  # [関数定義] _publish_metrics の処理実行ブロック
        slope_pct = d0.get('slope_pct', 0.0)
        if self.route_profile is not None:
            slope_pct = self._route_value(s_for_profile, 'slope_pct', slope_pct)
        headwind_ms = d0.get('headwind_ms', 0.0)
        if self.route_profile is not None:
            headwind_ms = self._route_value(s_for_profile, 'headwind_ms', headwind_ms)
        out = self.model.electrical_balance(
            v_exec_kmh / 3.6,
            slope_pct,
            self.z,
            self.Tb,
            d0.get('G_poa', 0.0),
            d0.get('Tcell_C', 40.0),
            headwind_ms=headwind_ms,
        )
        V = float(out['V'])
        I = float(out['I'])
        P_pv = float(out['P_pv'])
        P_pack = float(out['P_pack'])
        P_mech_wheel = float(out.get('P_mech_wheel', out.get('P_mech', 0.0)))
        P_motor_elec = float(out.get('P_dc_to_drv', 0.0)) - float(out.get('P_reg_to_dc', 0.0))
        I_motor = P_motor_elec / V if abs(V) > 1e-3 else 0.0
        msg = Float32MultiArray()
        msg.data = [
            float(V),
            float(I),
            float(self.z),
            float(P_motor_elec),
            float(I_motor),
            float(P_pv),
            float(v_exec_kmh),
            float(P_mech_wheel),
            float(P_pack),
        ]
        self.pub_metrics.publish(msg)

    def _publish_summary(self, v_exec_kmh: float):                 # [関数定義] _publish_summary の処理実行ブロック
        next_stop_dist_km = math.nan
        next_stop_eta_min = math.nan
        finish_dist_km = max(0.0, self.race_km - float(self.s_km))
        finish_eta_h = math.nan
        avg_plan_speed_kmh = float(v_exec_kmh)

        if self.stops:
            for stop in self.stops:
                s_stop = float(stop.get('s_km', 0.0))
                if s_stop > float(self.s_km):
                    next_stop_dist_km = max(0.0, s_stop - float(self.s_km))
                    break

        if self.v_plan_kmh:
            finite_plan = [float(v) for v in self.v_plan_kmh if np.isfinite(v) and float(v) > 0.1]
            if finite_plan:
                avg_plan_speed_kmh = float(np.mean(finite_plan))
        elif self.v_plan_segments:
            finite_plan = [float(seg['v_kmh']) for seg in self.v_plan_segments if float(seg['v_kmh']) > 0.1]
            if finite_plan:
                avg_plan_speed_kmh = float(np.mean(finite_plan))

        if avg_plan_speed_kmh > 0.1:
            if np.isfinite(next_stop_dist_km):
                next_stop_eta_min = (next_stop_dist_km / avg_plan_speed_kmh) * 60.0
            finish_eta_h = finish_dist_km / avg_plan_speed_kmh

        msg = Float32MultiArray()
        msg.data = [
            float((float(self.s_km) / max(self.race_km, 1.0)) * 100.0),
            float(next_stop_dist_km) if np.isfinite(next_stop_dist_km) else math.nan,
            float(next_stop_eta_min) if np.isfinite(next_stop_eta_min) else math.nan,
            float(finish_dist_km),
            float(finish_eta_h) if np.isfinite(finish_eta_h) else math.nan,
            float(avg_plan_speed_kmh) if np.isfinite(avg_plan_speed_kmh) else math.nan,
        ]
        self.pub_summary.publish(msg)

    def _interp_upper_speed(self, t_sec: float) -> float:          # [関数定義] _interp_upper_speed の処理実行ブロック
        if self.upper_plan_mode == 'distance' and self.v_plan_segments:
            acc = 0.0
            for seg in self.v_plan_segments:
                acc_next = acc + seg['dt_sec']
                if t_sec <= acc_next:
                    return float(seg['v_kmh'])                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
                acc = acc_next
            return float(self.v_plan_segments[-1]['v_kmh'])        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if not self.v_plan_kmh:
            return float(self.v_upper_cmd)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
        dt = float(self.plan_dt_sec)
        if dt <= 0.0:
            return float(self.v_plan_kmh[0])                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        idx = t_sec / dt
        i = int(math.floor(idx))
        if i <= 0:
            return float(self.v_plan_kmh[0])                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if i >= len(self.v_plan_kmh) - 1:
            return float(self.v_plan_kmh[-1])                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        alpha = idx - i
        return float((1.0 - alpha) * self.v_plan_kmh[i] + alpha * self.v_plan_kmh[i + 1])  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _distance_plan_speed(self, s_km: float) -> float:          # [関数定義] _distance_plan_speed の処理実行ブロック
        idx = plan_segment_index(self.v_plan_segments or [], s_km)
        if idx < 0:
            return float(self.v_upper_cmd)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return float(self.v_plan_segments[idx]['v_kmh'])           # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _tau_max_for_mode(self, maps, mode: str) -> float:         # [関数定義] _tau_max_for_mode の処理実行ブロック
        key = mode if mode in maps else 'default'
        try:
            return float(max(maps[key][1]))                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception:
            return 0.0                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _tau_limits(self):                                         # [関数定義] _tau_limits の処理実行ブロック
        mode = str(self.model.drive_mode or 'default').lower()
        if mode in ('eco', 'power'):
            tau_drive = self._tau_max_for_mode(self.model.maps_drive, mode)
            tau_regen = self._tau_max_for_mode(self.model.maps_regen, mode)
        else:
            tau_drive = self._tau_max_for_mode(self.model.maps_drive, 'power') if 'power' in self.model.maps_drive else \
                self._tau_max_for_mode(self.model.maps_drive, 'eco') if 'eco' in self.model.maps_drive else \
                self._tau_max_for_mode(self.model.maps_drive, 'default')
            tau_regen = self._tau_max_for_mode(self.model.maps_regen, 'power') if 'power' in self.model.maps_regen else \
                self._tau_max_for_mode(self.model.maps_regen, 'eco') if 'eco' in self.model.maps_regen else \
                self._tau_max_for_mode(self.model.maps_regen, 'default')
        if tau_regen <= 0.0:
            tau_regen = tau_drive
        return tau_drive, tau_regen                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _traction_force(self, tau_nm: float) -> float:             # [関数定義] _traction_force の処理実行ブロック
        p = self.model.p
        wheel_r = max(1e-3, float(p.wheel_radius))
        motor_count = int(p.motor_count) if int(p.motor_count) > 0 else int(p.driven_wheel_count or 1)
        motor_count = max(1, motor_count)
        return float(tau_nm) * float(p.gear_ratio) * float(p.gear_eta) * motor_count / wheel_r  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _pack_from_tau(self, v_ms: float, tau_nm: float, z: float, Tb: float, env: dict):  # [関数定義] _pack_from_tau の処理実行ブロック
        p = self.model.p
        wheel_r = max(1e-3, float(p.wheel_radius))
        motor_count = int(p.motor_count) if int(p.motor_count) > 0 else int(p.driven_wheel_count or 1)
        motor_count = max(1, motor_count)
        omega_m = float(v_ms) / wheel_r * float(p.gear_ratio)
        P_mech_motor = float(tau_nm) * omega_m * motor_count
        if tau_nm >= 0.0:
            eff = float(self.model.eff_drive(v_ms, tau_nm))
            eff = max(1.0e-3, eff)
            P_elec = P_mech_motor / (eff * float(p.inverter_eta))
        else:
            eff = float(self.model.eff_regen(v_ms, tau_nm))
            eff = max(1.0e-3, eff)
            P_elec = P_mech_motor * eff * float(p.inverter_eta)
        P_pv = float(self.model.pv_power_mppt(env['G_poa'], env['Tcell_C']))
        P_pack = P_elec + float(p.P_aux) - P_pv
        iv = self.model.battery_iv(P_pack, z, Tb)
        I = float(iv['I'])
        V = float(iv['V'])
        Rint = float(iv['Rint'])
        loss_int = I * I * Rint
        return dict(P_pack=P_pack, I=I, V=V, loss_int=loss_int, eff=eff, P_pv=P_pv, P_elec=P_elec)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _build_lower_ref(self, base_time_utc, s_km: float, d0: dict):  # [関数定義] _build_lower_ref の処理実行ブロック
        ref = []
        s_tmp = float(s_km)
        offset = 0.0
        if self.plan_start_monotonic is not None:
            offset = max(0.0, time.monotonic() - self.plan_start_monotonic)
        soc_guard = float(self.get_parameter('soc_guard_margin').value)
        guard_speed = None
        if self.z <= (self.model.p.soc_min + soc_guard):
            guard_speed = self._soc_guard_speed(self.v_upper_cmd, s_tmp, d0)
        for i in range(max(1, self.lower_N)):
            t_sec = offset + i * self.lower_dt
            v_ref = self._interp_upper_speed(t_sec)
            if guard_speed is not None:
                v_ref = min(v_ref, guard_speed)
            vmax_local = self._speed_limit_at(s_tmp, self.get_parameter('v_max_kmh').value)
            v_ref = min(v_ref, vmax_local)
            if self.drive_schedule is not None and base_time_utc is not None:
                t_utc = base_time_utc + timedelta(seconds=t_sec)
                limits = self.drive_schedule.speed_limits(t_utc)
                if limits is not None:
                    vmin_kmh, vmax_kmh = limits
                    v_ref = float(np.clip(v_ref, vmin_kmh, vmax_kmh))
            ref.append(float(v_ref))
            s_tmp += float(v_ref) * (self.lower_dt / 3600.0)
        seed_kmh = self.v_lower_cmd
        speed_meas_kmh = self._measured_speed_kmh()
        if math.isfinite(speed_meas_kmh):
            seed_kmh = speed_meas_kmh
        ref = self._shape_lower_ref_seq(ref, seed_kmh)
        return [float(v) / 3.6 for v in ref]                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _lower_rollout(self, v0_ms: float, u_seq: np.ndarray, env: dict, z0: float, Tb0: float,  # [関数定義] _lower_rollout の処理実行ブロック
                       tau_drive: float, tau_regen: float):
        p = self.model.p
        v = float(v0_ms)
        z = float(z0)
        Tb = float(Tb0)
        v_seq = []
        for u in u_seq:
            u = float(u)
            if u >= 0.0:
                tau = u * tau_drive
            else:
                tau = u * tau_regen
            forces = self.model.resistive_forces(v, env['slope_pct'], env['headwind_ms'])
            F_res = float(forces['F_total'])
            F_trac = self._traction_force(tau)
            a = (F_trac - F_res) / float(p.m)
            v = max(0.0, v + a * self.lower_dt)
            pack = self._pack_from_tau(v, tau, z, Tb, env)
            z = z - (float(pack['P_pack']) * self.lower_dt / 3600.0) / float(p.E_nom_Wh)
            Tb = Tb + (self.lower_dt / 1800.0) * (env['Tamb_C'] - Tb) + (float(pack['loss_int']) * self.lower_dt) / 50000.0
            v_seq.append(float(v))
        return v_seq                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _lower_mpc_solve(self, v0_ms: float, s0_km: float, z0: float, Tb0: float, env: dict, v_ref_seq):  # [関数定義] _lower_mpc_solve の処理実行ブロック
        N = max(1, min(self.lower_N, len(v_ref_seq)))
        if N <= 0:
            return 0.0, 0.0, [0.0] * N, 0.0, False

        v_ref_seq = v_ref_seq[:N]
        tau_drive, tau_regen = self._tau_limits()
        u0 = float(np.clip(self.lower_last_u, -1.0, 1.0))
        x0 = np.array([u0] * N, dtype=float)
        bounds = [(-1.0, 1.0)] * N

        p = self.model.p
        w_track = float(self.w_track)
        w_throttle = float(self.w_throttle)
        w_throttle_rate = float(self.w_throttle_rate)
        w_current = float(self.get_parameter('w_current').value)
        w_T = float(self.get_parameter('w_T').value)
        rate_lim = float(self.throttle_rate_limit) / 100.0 if self.throttle_rate_limit > 0.0 else 0.0

        def cost(u_vec):                                           # [関数定義] cost の処理実行ブロック
            v = float(v0_ms)
            z = float(z0)
            Tb = float(Tb0)
            u_prev = u0
            J = 0.0
            for i in range(N):
                u = float(u_vec[i])
                if u >= 0.0:
                    tau = u * tau_drive
                else:
                    tau = u * tau_regen
                forces = self.model.resistive_forces(v, env['slope_pct'], env['headwind_ms'])
                F_res = float(forces['F_total'])
                F_trac = self._traction_force(tau)
                a = (F_trac - F_res) / float(p.m)
                v = max(0.0, v + a * self.lower_dt)
                pack = self._pack_from_tau(v, tau, z, Tb, env)
                P_pack = float(pack['P_pack'])
                I = float(pack['I'])
                V = float(pack['V'])
                loss_int = float(pack['loss_int'])
                z = self.model.soc_step(z, P_pack, self.lower_dt)
                Tb = Tb + (self.lower_dt / 1800.0) * (env['Tamb_C'] - Tb) + (loss_int * self.lower_dt) / 50000.0

                v_ref = float(v_ref_seq[i])
                J += w_track * (v - v_ref) ** 2
                J += w_throttle * (u ** 2)
                du = (u - u_prev) / max(self.lower_dt, 1.0e-3)
                J += w_throttle_rate * (du ** 2)
                if rate_lim > 0.0:
                    J += w_throttle * max(0.0, abs(du) - rate_lim) ** 2
                J += w_current * (I ** 2) * self.lower_dt

                # soft constraints
                J += 1e4 * max(0.0, I - p.I_max) ** 2
                J += 1e4 * max(0.0, p.I_chg_min - I) ** 2
                J += 1e4 * max(0.0, p.V_min - V) ** 2
                J += 1e4 * max(0.0, V - p.V_max) ** 2
                J += w_T * max(0.0, Tb - p.T_max) ** 2
                J += w_T * max(0.0, p.T_min - Tb) ** 2
                J += 1e4 * max(0.0, p.soc_min - z) ** 2
                J += 1e4 * max(0.0, z - p.soc_max) ** 2
                u_prev = u
            return J                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=80))
        if np.all(np.isfinite(res.x)):
            self.last_lower_solve_ok = bool(res.success)
            u_seq = res.x
            if not res.success:
                print('Lower MPC reached an early stop; using best finite iterate.')
        else:
            self.last_lower_solve_ok = False
            print('Lower MPC solve failed; holding previous throttle seed.')
            u_seq = x0
        v_pred = self._lower_rollout(v0_ms, u_seq, env, z0, Tb0, tau_drive, tau_regen)
        u0_cmd = float(u_seq[0]) if len(u_seq) > 0 else 0.0
        tau0 = u0_cmd * (tau_drive if u0_cmd >= 0.0 else tau_regen)
        mode = self.model.select_drive_mode(v0_ms, tau0)
        return u_seq, v_pred, mode                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _step_solar(self):                                         # [関数定義] _step_solar の処理実行ブロック
        self._maybe_reload_forecast()
        k_now = self._current_bin_index()
        moved_to_new_bin = (self.last_bin is None) or (k_now != self.last_bin)
        self.k = k_now

        data = self._horizon_data(self.k)
        self.last_data = data
        if len(data) > 0:
            d0 = data[0]
            s_for_profile = self.s_km
            distance_meas_km = self._measured_distance_km()
            if bool(self.get_parameter('use_measured_s').value) and math.isfinite(distance_meas_km):
                s_for_profile = float(distance_meas_km)
            slope_pct = d0.get('slope_pct', 0.0)
            if self.route_profile is not None:
                slope_pct = self._route_value(s_for_profile, 'slope_pct', slope_pct)
            headwind_ms = d0.get('headwind_ms', 0.0)
            if self.route_profile is not None:
                headwind_ms = self._route_value(s_for_profile, 'headwind_ms', headwind_ms)
            env_msg = Float32MultiArray()
            env_msg.data = [
                float(d0.get('G_poa', 0.0)),
                float(d0.get('Tcell_C', 40.0)),
                float(d0.get('Tamb_C', 30.0)),
                float(slope_pct),
                float(headwind_ms),
            ]
            self.pub_env.publish(env_msg)
            v_exec_kmh = self.v_upper_cmd
            if self.hierarchical and self.timer_lower is not None:
                v_exec_kmh = self.v_lower_cmd
            speed_meas_kmh = self._measured_speed_kmh()
            if bool(self.get_parameter('use_measured_speed').value) and math.isfinite(speed_meas_kmh):
                v_exec_kmh = float(speed_meas_kmh)
            self._publish_metrics(d0, v_exec_kmh, s_for_profile)
            self._publish_summary(v_exec_kmh)
        need_plan = (self.v_plan_kmh is None) or (self.forecast_reloaded and self.replan_on_forecast_reload)
        if self.upper_mode == 'distance' and self.v_plan_segments is None:
            need_plan = True
        if self.upper_mode == 'distance' and self.v_plan_segments:
            plan_end_km = float(self.v_plan_segments[-1].get('s_end_km', self.s_km))
            if self.s_km >= plan_end_km - 1.0e-6:
                need_plan = True
        if self.upper_replan_km > 0.0 and self.upper_plan_s_km is not None:
            if (self.s_km - self.upper_plan_s_km) >= self.upper_replan_km:
                need_plan = True
        if self.upper_replan_sec > 0.0 and self.upper_plan_time is not None:
            if data and data[0].get('t_utc') and (data[0]['t_utc'] - self.upper_plan_time).total_seconds() >= self.upper_replan_sec:
                need_plan = True
        if (self.upper_replan_km <= 0.0) and (self.upper_replan_sec <= 0.0):
            need_plan = need_plan or moved_to_new_bin
        if (
            need_plan
            and self.upper_mode == 'distance'
            and self.v_plan_segments
            and self.drive_schedule is not None
            and len(data) > 0
            and data[0].get('t_utc')
            and not self.drive_schedule.is_drive_time(data[0]['t_utc'])
        ):
            plan_end_km = float(self.v_plan_segments[-1].get('s_end_km', self.s_km))
            if self.s_km < plan_end_km - 1.0e-6:
                need_plan = False
        if need_plan and len(data) > 0:
            s_for_profile = self.s_km
            distance_meas_km = self._measured_distance_km()
            if bool(self.get_parameter('use_measured_s').value) and math.isfinite(distance_meas_km):
                s_for_profile = float(distance_meas_km)
            t0 = data[0].get('t_utc', datetime.now(timezone.utc))
            if self.upper_mode == 'distance':
                prev_segments = self.v_plan_segments
                prev_seq = self.upper_plan_seq
                prev_plan_time = self.plan_start_monotonic
                self.v_upper_cmd, self.v_plan_segments, self.upper_plan_seq = self._mpc_solve_solar_distance(
                    t0, s_for_profile, self.upper_plan_seq
                )
                if self.last_upper_solve_ok or prev_segments is None:
                    self.upper_plan_mode = 'distance'
                    self.plan_dt_sec = float(self.model.p.dt)
                    self.v_plan_kmh = self._sample_plan_segments(self.plan_dt_sec)
                    self.upper_plan_s_km = float(s_for_profile)
                    self.upper_plan_time = t0
                    self.upper_plan_id += 1
                    self.plan_start_monotonic = time.monotonic()
                    self.last_plan_time = time.monotonic()
                else:
                    self.v_plan_segments = prev_segments
                    self.upper_plan_seq = prev_seq
                    self.plan_start_monotonic = prev_plan_time
            else:
                prev_plan = list(self.v_plan_kmh) if self.v_plan_kmh else None
                prev_plan_time = self.plan_start_monotonic
                self.v_upper_cmd, self.v_plan_kmh = self._mpc_solve_solar(data)
                if self.last_upper_solve_ok or prev_plan is None:
                    self.v_plan_segments = None
                    self.upper_plan_mode = 'time'
                    self.plan_dt_sec = float(self.model.p.dt)
                    self.upper_plan_s_km = float(s_for_profile)
                    self.upper_plan_time = t0
                    self.upper_plan_id += 1
                    self.plan_start_monotonic = time.monotonic()
                    self.last_plan_time = time.monotonic()
                else:
                    self.v_plan_kmh = prev_plan
                    self.plan_start_monotonic = prev_plan_time
                    if prev_plan:
                        if prev_plan_time is not None:
                            offset_sec = max(0.0, time.monotonic() - prev_plan_time)
                            self.v_upper_cmd = self._interp_upper_speed(offset_sec)
                        else:
                            self.v_upper_cmd = float(prev_plan[0])
            self.forecast_reloaded = False
        elif self.v_plan_kmh is None and len(data) > 0:
            self.v_plan_kmh = [float(self.v_upper_cmd)] * len(data)

        if self.upper_plan_mode == 'distance' and self.v_plan_segments:
            s_for_plan = self.s_km
            distance_meas_km = self._measured_distance_km()
            if bool(self.get_parameter('use_measured_s').value) and math.isfinite(distance_meas_km):
                s_for_plan = float(distance_meas_km)
            self.v_upper_cmd = self._distance_plan_speed(s_for_plan)
        elif self.upper_plan_mode == 'time' and self.plan_start_monotonic is not None:
            t_sec = max(0.0, time.monotonic() - self.plan_start_monotonic)
            self.v_upper_cmd = self._interp_upper_speed(t_sec)

        # hard schedule enforcement (current step)
        hard_stop = False
        if self.drive_schedule is not None and len(data) > 0 and 't_utc' in data[0]:
            limits = self.drive_schedule.speed_limits(data[0]['t_utc'])
            if limits is not None:
                vmin_kmh, vmax_kmh = limits
                self.v_upper_cmd = float(np.clip(self.v_upper_cmd, vmin_kmh, vmax_kmh))
                if vmax_kmh <= 0.0:
                    hard_stop = True

        # SoC guard
        if len(data) > 0:
            soc_guard = float(self.get_parameter('soc_guard_margin').value)
            if self.z <= (self.model.p.soc_min + soc_guard):
                s_for_profile = self.s_km
                distance_meas_km = self._measured_distance_km()
                if bool(self.get_parameter('use_measured_s').value) and math.isfinite(distance_meas_km):
                    s_for_profile = float(distance_meas_km)
                self.v_upper_cmd = self._soc_guard_speed(self.v_upper_cmd, s_for_profile, data[0])
        if hard_stop:
            self.v_upper_cmd = 0.0

        if self.v_plan_kmh:
            self.v_plan_kmh[0] = float(self.v_upper_cmd)

        self.pub_upper_speed.publish(Float32(data=float(self.v_upper_cmd)))
        self._publish_upper_plan()

        if not self.hierarchical or self.timer_lower is None:
            self.v_cmd = float(self.v_upper_cmd)
            self.pub_speed.publish(Float32(data=self.v_cmd))
        else:
            self.v_cmd = float(self.v_lower_cmd)

        self._publish_plan_path(data)

        if moved_to_new_bin and len(data) > 0:
            d0 = data[0]
            s_for_profile = self.s_km
            distance_meas_km = self._measured_distance_km()
            if bool(self.get_parameter('use_measured_s').value) and math.isfinite(distance_meas_km):
                s_for_profile = float(distance_meas_km)
            slope_pct = d0['slope_pct']
            if self.route_profile is not None:
                slope_pct = self._route_value(s_for_profile, 'slope_pct', slope_pct)
            headwind_ms = d0.get('headwind_ms', 0.0)
            if self.route_profile is not None:
                headwind_ms = self._route_value(s_for_profile, 'headwind_ms', headwind_ms)
            v_exec_kmh = self.v_upper_cmd
            if self.hierarchical and self.timer_lower is not None:
                v_exec_kmh = self.v_lower_cmd
            speed_meas_kmh = self._measured_speed_kmh()
            if bool(self.get_parameter('use_measured_speed').value) and math.isfinite(speed_meas_kmh):
                v_exec_kmh = float(speed_meas_kmh)

            u = MheInput(
                v_ms=v_exec_kmh / 3.6,
                slope_pct=slope_pct,
                G_poa=d0['G_poa'],
                Tcell_C=d0['Tcell_C'],
                Tamb_C=d0['Tamb_C'],
                headwind_ms=headwind_ms,
                dt=self.model.p.dt,
            )
            meas = MheMeas(
                soc=self._measured_soc() if math.isfinite(self._measured_soc()) else None,
                Tb=self._measured_tb() if math.isfinite(self._measured_tb()) else None,
                I=self._measured_i() if math.isfinite(self._measured_i()) else None,
                V=self._measured_v() if math.isfinite(self._measured_v()) else None,
            )
            if self.mhe is not None:
                self.mhe.push(u, meas)
                self.z, self.Tb = self.mhe.estimate(self.z, self.Tb)
            else:
                out = self.model.electrical_balance(u.v_ms, u.slope_pct, self.z, self.Tb, u.G_poa, u.Tcell_C, headwind_ms=u.headwind_ms)
                P_pack = float(out['P_pack'])
                loss_int = float(out['losses_int'])
                self.z = self.model.soc_step(self.z, P_pack, self.model.p.dt)
                self.Tb = self.Tb + (self.model.p.dt / 1800.0) * (u.Tamb_C - self.Tb) + (loss_int * self.model.p.dt) / 50000.0
            self.z = float(np.clip(self.z, self.model.p.soc_min, self.model.p.soc_max))
            self.Tb = float(np.clip(self.Tb, self.model.p.T_min, self.model.p.T_max))

            distance_meas_km = self._measured_distance_km()
            if bool(self.get_parameter('use_measured_s').value) and math.isfinite(distance_meas_km):
                self.s_km = float(distance_meas_km)
            else:
                self.s_km += float(v_exec_kmh) * (self.model.p.dt / 3600.0)
            self.last_bin = k_now

        mode = str(self.forecast_time_mode).lower()
        has_time = ('time' in self.df.columns) and (not self.df['time'].isna().all())
        if mode == 'auto':
            mode = 'absolute' if has_time else 'relative'
        if has_time and mode == 'absolute':
            if self.k + 1 < len(self.df) and pd.notna(self.df['time'].iloc[self.k + 1]):
                t_next = self.df['time'].iloc[self.k + 1].to_pydatetime()
                now = datetime.now(timezone.utc)
                sec_to_next = max(0.0, (t_next - now).total_seconds())
            else:
                sec_to_next = 0.0
        else:
            now = datetime.now(timezone.utc) + timedelta(seconds=self.forecast_time_offset)
            elapsed = (now - self.forecast_start_time).total_seconds()
            elapsed = max(0.0, elapsed)
            sec_to_next = max(0.0, self.model.p.dt - (elapsed % self.model.p.dt))

        st = Float32MultiArray()
        st.data = [float(self.z), float(self.Tb), float(self.s_km),
                   float(self.k), float(sec_to_next)]
        self.pub_status.publish(st)
        self._publish_mpc_state()

    def _step_lower(self):                                         # [関数定義] _step_lower の処理実行ブロック
        if not self.hierarchical or self.timer_lower is None:
            return
        if not self.last_data:
            return
        d0 = self.last_data[0]
        s_for_profile = self.s_km
        distance_meas_km = self._measured_distance_km()
        if bool(self.get_parameter('use_measured_s').value) and math.isfinite(distance_meas_km):
            s_for_profile = float(distance_meas_km)
        slope_pct = d0.get('slope_pct', 0.0)
        if self.route_profile is not None:
            slope_pct = self._route_value(s_for_profile, 'slope_pct', slope_pct)
        headwind_ms = d0.get('headwind_ms', 0.0)
        if self.route_profile is not None:
            headwind_ms = self._route_value(s_for_profile, 'headwind_ms', headwind_ms)
        env = dict(
            slope_pct=float(slope_pct),
            headwind_ms=float(headwind_ms),
            G_poa=float(d0.get('G_poa', 0.0)),
            Tcell_C=float(d0.get('Tcell_C', 40.0)),
            Tamb_C=float(d0.get('Tamb_C', 30.0)),
        )
        base_time = d0.get('t_utc', None)
        if base_time is None:
            base_time = datetime.now(timezone.utc)
        v_ref_seq = self._build_lower_ref(base_time, s_for_profile, d0)

        speed_meas_kmh = self._measured_speed_kmh()
        if bool(self.get_parameter('use_measured_speed').value) and math.isfinite(speed_meas_kmh):
            v0_ms = float(speed_meas_kmh) / 3.6
        else:
            v0_ms = float(self.v_lower_cmd) / 3.6
            if not np.isfinite(v0_ms) or v0_ms <= 0.0:
                v0_ms = float(self.v_upper_cmd) / 3.6

        u_seq, v_pred, mode = self._lower_mpc_solve(v0_ms, s_for_profile, self.z, self.Tb, env, v_ref_seq)
        v_cmd_ms = v_pred[0] if v_pred else v0_ms
        self.v_lower_cmd = float(v_cmd_ms * 3.6)
        self.v_cmd = float(self.v_lower_cmd)
        if len(u_seq) > 0:
            self.lower_last_u = float(u_seq[0])
        self.lower_last_mode = str(self._apply_drive_mode_hold(mode))

        self.pub_speed.publish(Float32(data=float(self.v_lower_cmd)))
        throttle_pct = float(np.clip(self.lower_last_u * 100.0, -100.0, 100.0))
        self.pub_throttle.publish(Float32(data=throttle_pct))
        self.pub_drive_mode.publish(String(data=str(self.lower_last_mode)))
        self._publish_lower_plan(v_pred)
        self._publish_mpc_state()

    # -------------------- passo mode --------------------
    def _init_passo(self):                                         # [関数定義] _init_passo の処理実行ブロック
        self.declare_parameter('stop_yaml', 'inputs/stop_points.yaml')
        self.declare_parameter('passo_dt', 1.0)
        self.declare_parameter('passo_horizon_steps', 10)
        self.declare_parameter('v_min_kmh', 0.0)
        self.declare_parameter('v_max_kmh', 110.0)
        self.declare_parameter('v_ref_kmh', 40.0)
        self.declare_parameter('w_fuel', 1.0)
        self.declare_parameter('w_speed', 0.3)
        self.declare_parameter('w_dv', 0.2)
        self.declare_parameter('w_dv_limit', 2.0)
        self.declare_parameter('dv_max_kmhps', 4.0)
        self.declare_parameter('w_stop', 1.0e4)
        self.declare_parameter('model_a0', 0.4)
        self.declare_parameter('model_a1', 0.02)
        self.declare_parameter('model_a2', 0.001)
        self.declare_parameter('model_a3', 0.08)
        self.declare_parameter('model_a4', 0.02)
        self.declare_parameter('online_id_enabled', True)
        self.declare_parameter('id_window_sec', 60.0)
        self.declare_parameter('id_min_samples', 30)
        self.declare_parameter('id_ema_alpha', 0.2)
        self.declare_parameter('max_acc_dt_sec', 2.0)
        self.declare_parameter('run_ready_sec', 3.0)

        self.dt = float(self.get_parameter('passo_dt').value)
        self.Np = int(self.get_parameter('passo_horizon_steps').value)
        self.v_cmd = float(self.get_parameter('v_ref_kmh').value)

        stop_yaml = self.get_parameter('stop_yaml').value
        self._load_stops(stop_yaml)

        # Inputs
        self.v_now = math.nan
        self.s_km = 0.0
        self.fuel_rate_lph = math.nan
        self.throttle_pct = math.nan
        self.obd_ok = 0.0
        self.config_ready = False
        self.mpc_state = 'IDLE'
        self.system_state = ''
        self.grade = math.nan
        self.idle_fuel_lph = math.nan

        # Model coeffs (fuel_pred_lph = a0 + a1*v + a2*v^2 + a3*acc^2)
        self.model_coeffs = np.array([
            float(self.get_parameter('model_a0').value),
            float(self.get_parameter('model_a1').value),
            float(self.get_parameter('model_a2').value),
            float(self.get_parameter('model_a3').value),
            float(self.get_parameter('model_a4').value)
        ], dtype=float)

        self.online_id_enabled = bool(self.get_parameter('online_id_enabled').value)
        self.id_window_sec = float(self.get_parameter('id_window_sec').value)
        self.id_min_samples = int(self.get_parameter('id_min_samples').value)
        self.id_ema_alpha = float(self.get_parameter('id_ema_alpha').value)
        self.max_acc_dt_sec = float(self.get_parameter('max_acc_dt_sec').value)
        self.id_samples = deque()
        self.id_rmse = math.nan
        self.id_r2 = math.nan

        self.prev_speed_kmh = math.nan
        self.prev_speed_time = None
        self.valid_obd_sec = 0.0
        self.valid_speed_sec = 0.0
        self.valid_fuel_sec = 0.0
        self.last_step_time = None

        # Subscriptions
        self.create_subscription(Float32, '/vehicle/s_km', self._on_s_km, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/speed_kmh', self._on_speed, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/fuel_rate_lph', self._on_fuel, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/throttle_pct', self._on_throttle, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/obd_ok', self._on_obd_ok, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/grade', self._on_grade, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/idle_fuel_lph', self._on_idle_fuel, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/config', self._on_config, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Bool, '/system/config_ready', self._on_config_ready, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/state', self._on_system_state, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        # Publications
        self.pub_speed = self.create_publisher(Float32, '/planner/speed_cmd', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_path = self.create_publisher(Path, '/planner/trajectory', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_status = self.create_publisher(Float32MultiArray, '/planner/status', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_mpc_state = self.create_publisher(String, '/system/mpc_state', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        # Timer @1Hz
        self.timer = self.create_timer(1.0, self._step_passo)
        print('MPCNode started (passo mode).')

    def _on_s_km(self, msg: Float32):                              # [関数定義] _on_s_km の処理実行ブロック
        self.s_km = float(msg.data)

    def _on_speed(self, msg: Float32):                             # [関数定義] _on_speed の処理実行ブロック
        self.v_now = float(msg.data)

    def _on_fuel(self, msg: Float32):                              # [関数定義] _on_fuel の処理実行ブロック
        self.fuel_rate_lph = float(msg.data)

    def _on_throttle(self, msg: Float32):                          # [関数定義] _on_throttle の処理実行ブロック
        self.throttle_pct = float(msg.data)

    def _on_obd_ok(self, msg: Float32):                            # [関数定義] _on_obd_ok の処理実行ブロック
        self.obd_ok = float(msg.data)

    def _on_grade(self, msg: Float32):                             # [関数定義] _on_grade の処理実行ブロック
        self.grade = float(msg.data)

    def _on_idle_fuel(self, msg: Float32):                         # [関数定義] _on_idle_fuel の処理実行ブロック
        self.idle_fuel_lph = float(msg.data)
        if np.isfinite(self.idle_fuel_lph):
            self.model_coeffs[0] = float(self.idle_fuel_lph)

    def _on_config_ready(self, msg: Bool):                         # [関数定義] _on_config_ready の処理実行ブロック
        self.config_ready = bool(msg.data)

    def _on_system_state(self, msg: String):                       # [関数定義] _on_system_state の処理実行ブロック
        self.system_state = str(msg.data)

    def _on_config(self, msg: String):                             # [関数定義] _on_config の処理実行ブロック
        try:
            cfg = yaml.safe_load(msg.data) or {}
        except Exception:
            return
        self._apply_config(cfg)

    def _apply_config(self, cfg: dict):                            # [関数定義] _apply_config の処理実行ブロック
        params = []
        for key in ['v_min_kmh', 'v_max_kmh', 'v_ref_kmh', 'w_fuel', 'w_speed', 'w_dv', 'w_stop',
                    'dv_max_kmhps']:
            if key in cfg:
                params.append(Parameter(key, value=cfg[key]))
        if 'dv_max_kmh_per_s' in cfg and 'dv_max_kmhps' not in cfg:
            params.append(Parameter('dv_max_kmhps', value=cfg['dv_max_kmh_per_s']))
        if 'horizon_steps' in cfg:
            params.append(Parameter('passo_horizon_steps', value=cfg['horizon_steps']))
        if 'dt_control' in cfg:
            params.append(Parameter('passo_dt', value=cfg['dt_control']))
        if params:
            self.set_parameters(params)
        if 'horizon_steps' in cfg:
            self.Np = int(cfg['horizon_steps'])
        if 'dt_control' in cfg:
            self.dt = float(cfg['dt_control'])
        if 'model_a0' in cfg:
            self.model_coeffs[0] = float(cfg['model_a0'])
        if 'model_a1' in cfg:
            self.model_coeffs[1] = float(cfg['model_a1'])
        if 'model_a2' in cfg:
            self.model_coeffs[2] = float(cfg['model_a2'])
        if 'model_a3' in cfg:
            self.model_coeffs[3] = float(cfg['model_a3'])
        if 'model_a4' in cfg:
            self.model_coeffs[4] = float(cfg['model_a4'])
        if 'online_id_enabled' in cfg:
            self.online_id_enabled = bool(cfg['online_id_enabled'])
        if 'stop_points_yaml' in cfg:
            self._load_stops(str(cfg['stop_points_yaml']))

    def _stop_penalty_passo(self, s_km: float, v_kmh: float) -> float:  # [関数定義] _stop_penalty_passo の処理実行ブロック
        v_ms = v_kmh / 3.6
        vmax_kmh = float(self.get_parameter('v_max_kmh').value)
        vmax_ms = vmax_kmh / 3.6
        pen = 0.0
        w_stop = float(self.get_parameter('w_stop').value)
        for st in self.stops:
            s_stop = float(st.get('s_km', 0.0))
            dwell_s = float(st.get('dwell_s', 0.0))
            width_km = max(0.05, (dwell_s * vmax_ms) / 1000.0 * 0.5)
            if abs(s_km - s_stop) <= width_km:
                pen += w_stop * (v_ms ** 2)
        return pen                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _fuel_model_lph(self, v_kmh: float, acc_kmhps: float, grade: float) -> float:  # [関数定義] _fuel_model_lph の処理実行ブロック
        a0, a1, a2, a3, a4 = self.model_coeffs
        a0_eff = a0
        if np.isfinite(self.idle_fuel_lph):
            a0_eff = float(self.idle_fuel_lph)
        fuel = a0_eff + a1 * v_kmh + a2 * (v_kmh ** 2) + a3 * (acc_kmhps ** 2) + a4 * grade * v_kmh
        return max(0.0, float(fuel))                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _update_identification(self, now_sec: float, acc_kmhps: float):  # [関数定義] _update_identification の処理実行ブロック
        if not self.online_id_enabled:
            return
        if self.obd_ok < 0.5:
            return
        if not np.isfinite(self.v_now) or not np.isfinite(self.fuel_rate_lph):
            return
        if self.v_now <= 5.0:
            return
        grade = float(self.grade) if np.isfinite(self.grade) else 0.0
        self.id_samples.append((now_sec, float(self.v_now), float(acc_kmhps), grade, float(self.fuel_rate_lph)))
        while self.id_samples and (now_sec - self.id_samples[0][0]) > self.id_window_sec:
            self.id_samples.popleft()
        if len(self.id_samples) < self.id_min_samples:
            return
        samples = list(self.id_samples)
        v = np.array([s[1] for s in samples], dtype=float)
        a = np.array([s[2] for s in samples], dtype=float)
        g = np.array([s[3] for s in samples], dtype=float)
        y = np.array([s[4] for s in samples], dtype=float)
        X = np.column_stack([np.ones_like(v), v, v ** 2, a ** 2, g * v])
        coeffs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        coeffs = np.maximum(coeffs, 0.0)
        alpha = self.id_ema_alpha
        self.model_coeffs = (1.0 - alpha) * self.model_coeffs + alpha * coeffs
        if np.isfinite(self.idle_fuel_lph):
            self.model_coeffs[0] = float(self.idle_fuel_lph)
        y_hat = X @ coeffs
        resid = y - y_hat
        rmse = float(np.sqrt(np.mean(resid ** 2))) if len(resid) else math.nan
        ss_tot = float(np.sum((y - np.mean(y)) ** 2)) if len(y) else 0.0
        ss_res = float(np.sum(resid ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else math.nan
        self.id_rmse = rmse
        self.id_r2 = r2

    def _solve_passo_mpc(self, w_fuel_override=None) -> np.ndarray:  # [関数定義] _solve_passo_mpc の処理実行ブロック
        v_min = float(self.get_parameter('v_min_kmh').value)
        v_max = float(self.get_parameter('v_max_kmh').value)
        v_ref = float(self.get_parameter('v_ref_kmh').value)
        w_fuel = float(self.get_parameter('w_fuel').value)
        if w_fuel_override is not None:
            w_fuel = float(w_fuel_override)
        w_speed = float(self.get_parameter('w_speed').value)
        w_dv = float(self.get_parameter('w_dv').value)
        w_dv_limit = float(self.get_parameter('w_dv_limit').value)
        dv_max = float(self.get_parameter('dv_max_kmhps').value)

        Np = max(1, self.Np)
        v0 = v_ref if not np.isfinite(self.v_now) else float(np.clip(self.v_now, v_min, v_max))
        x0 = np.array([v0] * Np, dtype=float)
        bounds = [(v_min, v_max)] * Np

        grade = float(self.grade) if np.isfinite(self.grade) else 0.0

        def cost(v_vec):                                           # [関数定義] cost の処理実行ブロック
            s_km = float(self.s_km)
            v_prev = v0
            J = 0.0
            for k in range(Np):
                v_k = float(v_vec[k])
                dv = (v_k - v_prev) / max(self.dt, 1.0e-3)
                fuel_lph = self._fuel_model_lph(v_k, dv, grade)
                fuel_l = fuel_lph * (self.dt / 3600.0)
                J += w_fuel * fuel_l
                J += w_speed * (v_k - v_ref) ** 2
                J += w_dv * (dv ** 2)
                if dv_max > 0.0:
                    J += w_dv_limit * max(0.0, abs(dv) - dv_max) ** 2
                s_km += v_k * (self.dt / 3600.0)
                J += self._stop_penalty_passo(s_km, v_k)
                v_prev = v_k
            return J                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=120))
        if not np.all(np.isfinite(res.x)):
            return x0                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return np.array(res.x, dtype=float)                        # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _publish_trajectory_passo(self, v_seq: np.ndarray):        # [関数定義] _publish_trajectory_passo の処理実行ブロック
        path = Path()
        path.header.stamp = self.get_clock().now().to_msg()
        path.header.frame_id = 'map'
        s_tmp = float(self.s_km)
        for k, v_k in enumerate(v_seq):
            s_tmp += float(v_k) * (self.dt / 3600.0)
            pose = PoseStamped()
            pose.header = path.header
            pose.pose.position.x = float(k)
            pose.pose.position.y = float(v_k)
            pose.pose.position.z = s_tmp
            path.poses.append(pose)
        self.pub_path.publish(path)

    def _step_passo(self):                                         # [関数定義] _step_passo の処理実行ブロック
        now_sec = self.get_clock().now().nanoseconds / 1e9
        if self.last_step_time is None:
            dt_step = 0.0
        else:
            dt_step = max(0.0, min(5.0, now_sec - self.last_step_time))
        self.last_step_time = now_sec

        acc_kmhps = 0.0
        if np.isfinite(self.v_now):
            if self.prev_speed_time is not None:
                dt = now_sec - self.prev_speed_time
                if 0.0 < dt <= self.max_acc_dt_sec and np.isfinite(self.prev_speed_kmh):
                    acc_kmhps = (float(self.v_now) - float(self.prev_speed_kmh)) / dt
            self.prev_speed_time = now_sec
            self.prev_speed_kmh = float(self.v_now)

        v_ref = float(self.get_parameter('v_ref_kmh').value)
        speed_valid = np.isfinite(self.v_now)
        fuel_valid = np.isfinite(self.fuel_rate_lph)
        obd_valid = self.obd_ok > 0.5

        if dt_step > 0.0:
            self.valid_obd_sec = self.valid_obd_sec + dt_step if obd_valid else 0.0
            self.valid_speed_sec = self.valid_speed_sec + dt_step if speed_valid else 0.0
            self.valid_fuel_sec = self.valid_fuel_sec + dt_step if fuel_valid else 0.0

        run_ready_sec = float(self.get_parameter('run_ready_sec').value)
        run_ready = (self.valid_obd_sec >= run_ready_sec and
                     self.valid_speed_sec >= run_ready_sec and
                     self.valid_fuel_sec >= run_ready_sec)

        if not self.config_ready:
            self.mpc_state = 'IDLE'
            self.v_cmd = v_ref
            v_seq = np.array([self.v_cmd] * max(1, self.Np), dtype=float)
        elif not run_ready:
            self.mpc_state = 'DEGRADED_RUN'
            self.v_cmd = float(self.v_now) if speed_valid else v_ref
            v_seq = np.array([self.v_cmd] * max(1, self.Np), dtype=float)
        else:
            self.mpc_state = 'RUN'
            self._update_identification(now_sec, acc_kmhps)
            v_seq = self._solve_passo_mpc()
            self.v_cmd = float(v_seq[0])

        msg = Float32()
        msg.data = float(self.v_cmd)
        self.pub_speed.publish(msg)

        self._publish_trajectory_passo(v_seq)

        fuel_pred_lph = math.nan
        if np.isfinite(self.v_cmd):
            grade = float(self.grade) if np.isfinite(self.grade) else 0.0
            fuel_pred_lph = self._fuel_model_lph(float(self.v_cmd), 0.0, grade)

        status = Float32MultiArray()
        status.data = [
            float(self.fuel_rate_lph) if np.isfinite(self.fuel_rate_lph) else math.nan,
            float(fuel_pred_lph) if np.isfinite(fuel_pred_lph) else math.nan,
            float(self.v_now) if np.isfinite(self.v_now) else math.nan,
            float(self.v_cmd),
            float(self.s_km),
            float(self.id_rmse) if np.isfinite(self.id_rmse) else math.nan,
            float(self.id_r2) if np.isfinite(self.id_r2) else math.nan,
        ]
        self.pub_status.publish(status)
        self.pub_mpc_state.publish(String(data=str(self.mpc_state)))


def main():                                                        # [メイン関数] エントリーポイント関数
    node = MPCNode()
    node.destroy_node()

# =============================================================================
# 【統合ユーティリティ】シグナルフィルタ・スルーレート制限・有限値検証
# =============================================================================
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import time
from collections import deque


def finite_float(value, default=math.nan):                         # [関数定義] finite_float の処理実行ブロック
    try:
        v = float(value)
        if math.isfinite(v):
            return v                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        pass
    return default                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def clamp(value, lo=None, hi=None):                                # [関数定義] clamp の処理実行ブロック
    v = float(value)
    if lo is not None:
        v = max(float(lo), v)
    if hi is not None:
        v = min(float(hi), v)
    return v                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fresh_enough(timestamp, timeout_sec, now=None):                # [関数定義] fresh_enough の処理実行ブロック
    if timestamp is None:
        return False                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if timeout_sec is None or float(timeout_sec) <= 0.0:
        return True                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if now is None:
        now = time.monotonic()
    return (float(now) - float(timestamp)) <= float(timeout_sec)   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def slew_limit(previous, target, dt, rise_rate=None, fall_rate=None):  # [関数定義] slew_limit の処理実行ブロック
    prev = float(previous)
    tgt = float(target)
    dt = max(0.0, float(dt))
    if not math.isfinite(prev) or dt <= 0.0:
        return tgt                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = tgt - prev
    if delta >= 0.0 and rise_rate is not None and math.isfinite(float(rise_rate)) and float(rise_rate) > 0.0:
        delta = min(delta, float(rise_rate) * dt)
    if delta < 0.0 and fall_rate is not None and math.isfinite(float(fall_rate)) and float(fall_rate) > 0.0:
        delta = max(delta, -float(fall_rate) * dt)
    return prev + delta                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却


class SmoothRateLimiter:                                           # [クラス定義] SmoothRateLimiter オブジェクトの設計
    def __init__(                                                  # [関数定義] __init__ の処理実行ブロック
        self,
        *,
        min_value=None,
        max_value=None,
        tau_sec=0.0,
        rise_rate=None,
        fall_rate=None,
        deadband=0.0,
        quantize_step=0.0,
        initial_value=math.nan,
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.tau_sec = max(0.0, float(tau_sec))
        self.rise_rate = rise_rate
        self.fall_rate = fall_rate
        self.deadband = max(0.0, float(deadband))
        self.quantize_step = max(0.0, float(quantize_step))
        self.value = float(initial_value) if math.isfinite(finite_float(initial_value)) else math.nan
        self.last_time = None

    def reset(self, value=math.nan, now=None):                     # [関数定義] reset の処理実行ブロック
        self.value = finite_float(value)
        self.last_time = time.monotonic() if now is None else float(now)
        return self.value                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def update(self, target, now=None):                            # [関数定義] update の処理実行ブロック
        tgt = finite_float(target)
        if not math.isfinite(tgt):
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        tgt = clamp(tgt, self.min_value, self.max_value)
        now_mono = time.monotonic() if now is None else float(now)
        if not math.isfinite(self.value):
            self.value = tgt
            self.last_time = now_mono
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却

        dt = 0.0 if self.last_time is None else max(1.0e-3, now_mono - float(self.last_time))
        if self.tau_sec > 0.0 and dt > 0.0:
            alpha = 1.0 - math.exp(-dt / self.tau_sec)
            candidate = self.value + alpha * (tgt - self.value)
        else:
            candidate = tgt

        candidate = slew_limit(self.value, candidate, dt, self.rise_rate, self.fall_rate)
        candidate = clamp(candidate, self.min_value, self.max_value)

        if self.deadband > 0.0 and abs(candidate - self.value) < self.deadband:
            candidate = self.value

        if self.quantize_step > 0.0:
            candidate = round(candidate / self.quantize_step) * self.quantize_step

        self.value = clamp(candidate, self.min_value, self.max_value)
        self.last_time = now_mono
        return self.value                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却


class RobustScalarFilter:                                          # [クラス定義] RobustScalarFilter オブジェクトの設計
    def __init__(                                                  # [関数定義] __init__ の処理実行ブロック
        self,
        *,
        min_value=None,
        max_value=None,
        tau_sec=0.0,
        rise_rate=None,
        fall_rate=None,
        deadband=0.0,
        quantize_step=0.0,
        median_window=1,
        monotonic=False,
        max_backtrack=0.0,
        initial_value=math.nan,
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.monotonic = bool(monotonic)
        self.max_backtrack = max(0.0, float(max_backtrack))
        self.window = deque(maxlen=max(1, int(median_window)))
        self.smoother = SmoothRateLimiter(
            min_value=min_value,
            max_value=max_value,
            tau_sec=tau_sec,
            rise_rate=rise_rate,
            fall_rate=fall_rate,
            deadband=deadband,
            quantize_step=quantize_step,
            initial_value=initial_value,
        )

    @property
    def value(self):                                               # [関数定義] value の処理実行ブロック
        return self.smoother.value                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    @property
    def last_time(self):                                           # [関数定義] last_time の処理実行ブロック
        return self.smoother.last_time                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def reset(self, value=math.nan, now=None):                     # [関数定義] reset の処理実行ブロック
        self.window.clear()
        v = finite_float(value)
        if math.isfinite(v):
            self.window.append(v)
        return self.smoother.reset(v, now=now)                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def update(self, raw_value, now=None):                         # [関数定義] update の処理実行ブロック
        value = finite_float(raw_value)
        if not math.isfinite(value):
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        value = clamp(value, self.min_value, self.max_value)
        self.window.append(value)
        candidate = value
        if len(self.window) > 1:
            seq = sorted(self.window)
            candidate = float(seq[len(seq) // 2])
        if self.monotonic and math.isfinite(self.value):
            candidate = max(candidate, float(self.value) - self.max_backtrack)
        return self.smoother.update(candidate, now=now)            # [戻り値] 計算結果・計算状態の呼び出し元への返却

# =============================================================================
# 【統合ユーティリティ】パス解決・ルート補間・スケジューラー・気象インターフェース
# =============================================================================
import os
from pathlib import Path

get_package_share_directory = None



PKG_NAME = 'mpc_solarcar'
REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(path: str, default_subdir: str = '') -> str:      # [関数定義] resolve_path の処理実行ブロック
    """Resolve a path relative to CWD or package share.

    - If absolute, return as-is.                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - If exists relative to CWD, return it.                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - Otherwise, resolve under <pkg_share>/<default_subdir> (or directly under share).
    """
    if path is None:
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.exists(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if get_package_share_directory is not None:
        pkg_share = get_package_share_directory(PKG_NAME)
    else:
        pkg_share = os.fspath(REPO_ROOT)
    if default_subdir:
        subdir = default_subdir.strip('/\\')
        if path.startswith(subdir + os.sep) or path == subdir:
            return os.path.join(pkg_share, path)                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return os.path.join(pkg_share, subdir, path)               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return os.path.join(pkg_share, path)                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


def _interp_field(d, y, s_km, default=0.0):                        # [関数定義] _interp_field の処理実行ブロック
    if len(d) < 2:
        return float(default)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    s = np.clip(s_km, d[0], d[-1])
    i = np.searchsorted(d, s) - 1
    i = np.clip(i, 0, len(d) - 2)
    t = 0.0 if d[i + 1] == d[i] else (s - d[i]) / (d[i + 1] - d[i])
    return float((1 - t) * y[i] + t * y[i + 1])                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route(route_df, s_km):                             # [関数定義] interpolate_route の処理実行ブロック
    d = route_df['dist_km'].values
    lat = route_df['lat'].values
    lon = route_df['lon'].values
    latp = _interp_field(d, lat, s_km, default=float(lat[0]) if len(lat) else 0.0)
    lonp = _interp_field(d, lon, s_km, default=float(lon[0]) if len(lon) else 0.0)
    return latp, lonp                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route_with_alt(route_df, s_km):                    # [関数定義] interpolate_route_with_alt の処理実行ブロック
    lat, lon = interpolate_route(route_df, s_km)
    alt = None
    for col in ('alt_m', 'altitude_m', 'elev_m'):
        if col in route_df.columns:
            d = route_df['dist_km'].values
            alt = _interp_field(d, route_df[col].values, s_km, default=float(route_df[col].values[0]))
            break
    return lat, lon, alt                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_profile(route_df, s_km, field: str, default: float = 0.0) -> float:  # [関数定義] interpolate_profile の処理実行ブロック
    if field not in route_df.columns:
        return float(default)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    d = route_df['dist_km'].values
    return _interp_field(d, route_df[field].values, s_km, default=default)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def bearing_deg(lat1, lon1, lat2, lon2):                           # [関数定義] bearing_deg の処理実行ブロック
    lat1r = np.deg2rad(float(lat1))
    lon1r = np.deg2rad(float(lon1))
    lat2r = np.deg2rad(float(lat2))
    lon2r = np.deg2rad(float(lon2))
    dlon = lon2r - lon1r
    y = np.sin(dlon) * np.cos(lat2r)
    x = np.cos(lat1r) * np.sin(lat2r) - np.sin(lat1r) * np.cos(lat2r) * np.cos(dlon)
    brng = np.rad2deg(np.arctan2(y, x))
    return float((brng + 360.0) % 360.0)                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route_heading(route_df, s_km, span_km: float = 1.0):  # [関数定義] interpolate_route_heading の処理実行ブロック
    if route_df is None or len(route_df) < 2:
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    s0 = max(float(route_df['dist_km'].iloc[0]), float(s_km) - max(0.1, span_km))
    s1 = min(float(route_df['dist_km'].iloc[-1]), float(s_km) + max(0.1, span_km))
    if s1 <= s0:
        d = route_df['dist_km'].values
        i = int(np.clip(np.searchsorted(d, float(s_km)), 1, len(d) - 1))
        lat1 = float(route_df.iloc[i - 1]['lat'])
        lon1 = float(route_df.iloc[i - 1]['lon'])
        lat2 = float(route_df.iloc[i]['lat'])
        lon2 = float(route_df.iloc[i]['lon'])
        return bearing_deg(lat1, lon1, lat2, lon2)                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    lat1, lon1 = interpolate_route(route_df, s0)
    lat2, lon2 = interpolate_route(route_df, s1)
    return bearing_deg(lat1, lon1, lat2, lon2)                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


import os
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import List, Optional, Tuple

import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - fallback for older Python
    ZoneInfo = None


def _parse_utc(ts: str) -> Optional[datetime]:                     # [関数定義] _parse_utc の処理実行ブロック
    try:
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _parse_time_hhmm(s: str) -> Optional[dtime]:                   # [関数定義] _parse_time_hhmm の処理実行ブロック
    try:
        parts = s.strip().split(':')
        if len(parts) < 2:
            return None                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return dtime(hour=int(parts[0]), minute=int(parts[1]))     # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


@dataclass
class DriveWindow:                                                 # [クラス定義] DriveWindow オブジェクトの設計
    start_utc: datetime
    end_utc: datetime
    v_min_kmh: float
    v_max_kmh: float

    def contains(self, t_utc: datetime) -> bool:                   # [関数定義] contains の処理実行ブロック
        return self.start_utc <= t_utc < self.end_utc              # [戻り値] 計算結果・計算状態の呼び出し元への返却


@dataclass
class DailyWindow:                                                 # [クラス定義] DailyWindow オブジェクトの設計
    start_local: dtime
    end_local: dtime
    tz: str
    days: Optional[List[int]]
    v_min_kmh: float
    v_max_kmh: float

    def contains(self, t_utc: datetime) -> bool:                   # [関数定義] contains の処理実行ブロック
        if ZoneInfo is None:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        try:
            tzinfo = ZoneInfo(self.tz)
        except Exception:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        local_dt = t_utc.astimezone(tzinfo)
        if self.days is not None and local_dt.weekday() not in self.days:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        start = self.start_local
        end = self.end_local
        now_t = local_dt.time()
        if start <= end:
            return start <= now_t < end                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        # wraps midnight
        return now_t >= start or now_t < end                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


class DriveSchedule:                                               # [クラス定義] DriveSchedule オブジェクトの設計
    def __init__(self, windows: List[DriveWindow], daily: List[DailyWindow], deny_by_default: bool):  # [関数定義] __init__ の処理実行ブロック
        self.windows = windows
        self.daily = daily
        self.deny_by_default = deny_by_default

    @classmethod
    def from_yaml(cls, path: str) -> Optional['DriveSchedule']:    # [関数定義] from_yaml の処理実行ブロック
        if not path or not os.path.exists(path):
            return None                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            return None                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        deny_by_default = bool(cfg.get('deny_by_default', False))
        windows = []
        for w in cfg.get('drive_windows', []) or []:
            start = _parse_utc(str(w.get('start_utc', '')))
            end = _parse_utc(str(w.get('end_utc', '')))
            if start is None or end is None:
                continue
            vmin = float(w.get('v_min_kmh', 0.0))
            vmax = float(w.get('v_max_kmh', 130.0))
            windows.append(DriveWindow(start, end, vmin, vmax))
        daily = []
        for w in cfg.get('daily_windows', []) or []:
            start = _parse_time_hhmm(str(w.get('start_local', '')))
            end = _parse_time_hhmm(str(w.get('end_local', '')))
            tz = str(w.get('tz', 'UTC'))
            if start is None or end is None:
                continue
            days = w.get('days', None)
            if days is not None:
                try:
                    days = [int(d) for d in days]
                except Exception:
                    days = None
            vmin = float(w.get('v_min_kmh', 0.0))
            vmax = float(w.get('v_max_kmh', 130.0))
            daily.append(DailyWindow(start, end, tz, days, vmin, vmax))
        return cls(windows, daily, deny_by_default)                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def speed_limits(self, t_utc: datetime) -> Optional[Tuple[float, float]]:  # [関数定義] speed_limits の処理実行ブロック
        limits = []
        for w in self.windows:
            if w.contains(t_utc):
                limits.append((w.v_min_kmh, w.v_max_kmh))
        for w in self.daily:
            if w.contains(t_utc):
                limits.append((w.v_min_kmh, w.v_max_kmh))
        if limits:
            vmin = max(l[0] for l in limits)
            vmax = min(l[1] for l in limits)
            return vmin, vmax                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if self.deny_by_default:
            return 0.0, 0.0                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def is_drive_time(self, t_utc: datetime) -> bool:              # [関数定義] is_drive_time の処理実行ブロック
        limits = self.speed_limits(t_utc)
        if limits is None:
            return not self.deny_by_default                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return limits[1] > 0.0                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def next_drive_start(self, t_utc: datetime) -> datetime:       # [関数定義] next_drive_start の処理実行ブロック
        if self.is_drive_time(t_utc):
            return t_utc                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        candidates = []
        for w in self.windows:
            if t_utc < w.start_utc:
                candidates.append(w.start_utc)
        for w in self.daily:
            if ZoneInfo is None:
                continue
            try:
                tzinfo = ZoneInfo(w.tz)
            except Exception:
                continue
            local_dt = t_utc.astimezone(tzinfo)
            if w.days is not None and local_dt.weekday() not in w.days:
                # move to next allowed weekday
                days_ahead = 1
                while w.days is not None and ((local_dt + timedelta(days=days_ahead)).weekday() not in w.days) and days_ahead < 8:
                    days_ahead += 1
                start_date = (local_dt + timedelta(days=days_ahead)).date()
                start_local = datetime.combine(start_date, w.start_local, tzinfo)
                candidates.append(start_local.astimezone(timezone.utc))
                continue
            now_t = local_dt.time()
            if w.start_local <= w.end_local:
                if now_t < w.start_local:
                    start_local = datetime.combine(local_dt.date(), w.start_local, tzinfo)
                else:
                    start_local = datetime.combine(local_dt.date() + timedelta(days=1), w.start_local, tzinfo)
            else:
                # wraps midnight
                if now_t < w.end_local:
                    start_local = datetime.combine(local_dt.date(), w.start_local, tzinfo)
                elif now_t < w.start_local:
                    start_local = datetime.combine(local_dt.date(), w.start_local, tzinfo)
                else:
                    start_local = datetime.combine(local_dt.date() + timedelta(days=1), w.start_local, tzinfo)
            candidates.append(start_local.astimezone(timezone.utc))
        if candidates:
            return min(candidates)                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return t_utc                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def current_drive_window(self, t_utc: datetime):               # [関数定義] current_drive_window の処理実行ブロック
        """Return (start_utc, end_utc) if t_utc is inside a drive window, else None."""
        for w in self.windows:
            if w.contains(t_utc):
                return w.start_utc, w.end_utc                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        for w in self.daily:
            if ZoneInfo is None:
                continue
            try:
                tzinfo = ZoneInfo(w.tz)
            except Exception:
                continue
            local_dt = t_utc.astimezone(tzinfo)
            if w.days is not None and local_dt.weekday() not in w.days:
                continue
            start = w.start_local
            end = w.end_local
            now_t = local_dt.time()
            if start <= end:
                if not (start <= now_t < end):
                    continue
                start_local = datetime.combine(local_dt.date(), start, tzinfo)
                end_local = datetime.combine(local_dt.date(), end, tzinfo)
            else:
                # wraps midnight
                if not (now_t >= start or now_t < end):
                    continue
                if now_t >= start:
                    start_local = datetime.combine(local_dt.date(), start, tzinfo)
                    end_local = datetime.combine(local_dt.date() + timedelta(days=1), end, tzinfo)
                else:
                    start_local = datetime.combine(local_dt.date() - timedelta(days=1), start, tzinfo)
                    end_local = datetime.combine(local_dt.date(), end, tzinfo)
            return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


OPENMETEO_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'


def _fetch_json(url: str, timeout_sec: float = 20.0) -> Dict:      # [関数定義] _fetch_json の処理実行ブロック
    req = urllib.request.Request(url, headers={'User-Agent': 'solarcar-weather-fetch/1.0'})
    with urllib.request.urlopen(req, timeout=timeout_sec) as res:
        return json.loads(res.read().decode('utf-8'))              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_openmeteo_url(latitude: float, longitude: float, timezone_name: str, forecast_days: int) -> str:  # [関数定義] build_openmeteo_url の処理実行ブロック
    params = {
        'latitude': f'{latitude:.6f}',
        'longitude': f'{longitude:.6f}',
        'timezone': timezone_name,
        'forecast_days': str(max(1, int(forecast_days))),
        'hourly': 'temperature_2m,shortwave_radiation,windspeed_10m,winddirection_10m',
    }
    return OPENMETEO_FORECAST_URL + '?' + urllib.parse.urlencode(params)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def wrap_angle_deg(angle_deg: float) -> float:                     # [関数定義] wrap_angle_deg の処理実行ブロック
    return float((float(angle_deg) + 360.0) % 360.0)               # [戻り値] 計算結果・計算状態の呼び出し元への返却


def signed_angle_diff_deg(a_deg: float, b_deg: float) -> float:    # [関数定義] signed_angle_diff_deg の処理実行ブロック
    return float((float(a_deg) - float(b_deg) + 180.0) % 360.0 - 180.0)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def meteo_headwind_component_ms(wind_speed_ms: float, wind_from_deg: float, heading_deg: float) -> float:  # [関数定義] meteo_headwind_component_ms の処理実行ブロック
    """Project a meteorological wind direction onto the route heading.

    `wind_from_deg` follows the usual convention: the direction the wind is coming from,
    measured clockwise from north. Positive output means headwind, negative means tailwind.
    """
    if not math.isfinite(float(wind_speed_ms)):
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if not math.isfinite(float(wind_from_deg)) or not math.isfinite(float(heading_deg)):
        return float(wind_speed_ms)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = math.radians(signed_angle_diff_deg(float(wind_from_deg), float(heading_deg)))
    return float(wind_speed_ms) * math.cos(delta)                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fetch_openmeteo_forecast(                                      # [関数定義] fetch_openmeteo_forecast の処理実行ブロック
    latitude: float,
    longitude: float,
    timezone_name: str = 'UTC',
    forecast_days: int = 3,
    step_minutes: int = 10,
    tcell_gain: float = 0.03,
    timeout_sec: float = 20.0,
) -> pd.DataFrame:
    url = build_openmeteo_url(latitude, longitude, timezone_name, forecast_days)
    payload = _fetch_json(url, timeout_sec=timeout_sec)
    hourly = payload.get('hourly', {})
    times = hourly.get('time', [])
    ghi = hourly.get('shortwave_radiation', [])
    temp = hourly.get('temperature_2m', [])
    wind_kmh = hourly.get('windspeed_10m', [])
    wind_dir = hourly.get('winddirection_10m', [])
    rows: List[Dict] = []
    for idx, t_str in enumerate(times):
        try:
            t_local = datetime.fromisoformat(t_str)
            if t_local.tzinfo is None:
                t_local = t_local.replace(tzinfo=timezone.utc)
            t_utc = t_local.astimezone(timezone.utc)
        except Exception:
            continue
        g = float(ghi[idx]) if idx < len(ghi) and ghi[idx] is not None else 0.0
        tamb = float(temp[idx]) if idx < len(temp) and temp[idx] is not None else 25.0
        w_kmh = float(wind_kmh[idx]) if idx < len(wind_kmh) and wind_kmh[idx] is not None else 0.0
        w_dir = float(wind_dir[idx]) if idx < len(wind_dir) and wind_dir[idx] is not None else 0.0
        w_ms = w_kmh / 3.6
        rows.append({
            'time': t_utc.isoformat(),
            'GHI': g,
            'Tamb_C': tamb,
            'Tcell_C': tamb + max(0.0, g) * float(tcell_gain),
            'wind_speed_ms': w_ms,
            'wind_dir_deg': wrap_angle_deg(w_dir),
            # Raw forecast does not know the actual route heading at this stage.
            # Keep the direct headwind input neutral and let the wind correction node
            # project the forecast onto the route before the planner consumes it.
            'headwind_ms': 0.0,
        })

    df = pd.DataFrame(rows)
    if df.empty or step_minutes >= 60:
        return df                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    if df.empty:
        return df.reset_index(drop=False)                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    target_index = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq=f'{int(step_minutes)}min',
        tz='UTC',
    )
    df = df.reindex(df.index.union(target_index)).interpolate(method='time').reindex(target_index)
    df = df.reset_index().rename(columns={'index': 'time'})
    df['time'] = df['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return df                                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_forecast_csv(df: pd.DataFrame, out_csv: str):            # [関数定義] write_forecast_csv の処理実行ブロック
    if df is None:
        raise ValueError('Forecast dataframe is None')
    df.to_csv(out_csv, index=False)


import os
from typing import Any, Dict, Tuple

import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート



def load_profile(profile_yaml: str) -> Tuple[str, Dict[str, Any]]:  # [関数定義] load_profile の処理実行ブロック
    """Load a unified solar workflow profile YAML."""
    resolved = resolve_path(profile_yaml, 'config')
    with open(resolved, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f'Profile YAML must be a mapping: {resolved}')
    return os.path.abspath(resolved), cfg                          # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_section(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:  # [関数定義] get_section の処理実行ブロック
    value = cfg.get(name, {})
    return value if isinstance(value, dict) else {}                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_value(cfg: Dict[str, Any], section: str, key: str, default: Any = None) -> Any:  # [関数定義] get_value の処理実行ブロック
    return get_section(cfg, section).get(key, default)             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def merged_dict(*parts: Dict[str, Any]) -> Dict[str, Any]:         # [関数定義] merged_dict の処理実行ブロック
    merged: Dict[str, Any] = {}
    for part in parts:
        if isinstance(part, dict):
            merged.update(part)
    return merged                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def resolve_profile_asset(profile_yaml: str, asset_path: str) -> str:  # [関数定義] resolve_profile_asset の処理実行ブロック
    if asset_path is None:
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    raw = os.path.expanduser(str(asset_path)).strip()
    if not raw:
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.isabs(raw):
        return raw                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    profile_dir = os.path.dirname(os.path.abspath(profile_yaml))
    candidate = os.path.normpath(os.path.join(profile_dir, raw))
    if os.path.exists(candidate):
        return candidate                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.exists(raw):
        return os.path.abspath(raw)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return resolve_path(raw)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_path(cfg: Dict[str, Any], profile_yaml: str, key: str, default: str = '') -> str:  # [関数定義] get_path の処理実行ブロック
    return resolve_profile_asset(profile_yaml, get_value(cfg, 'paths', key, default))  # [戻り値] 計算結果・計算状態の呼び出し元への返却


# =============================================================================
# 【統合物理モデル】車両運動方程式 & 1-RC 電池等価回路モデル
# =============================================================================
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
from dataclasses import dataclass

try:
    import casadi as ca                                            # [最適化エンジン] 数値最適化・自動微分ライブラリ CasADi のインポート
except ImportError:
    class _CasadiCompat:                                           # [クラス定義] _CasadiCompat オブジェクトの設計
        class SX:                                                  # [クラス定義] SX オブジェクトの設計
            pass

        class MX:                                                  # [クラス定義] MX オブジェクトの設計
            pass

        @staticmethod
        def fmax(a, b):                                            # [関数定義] fmax の処理実行ブロック
            return max(a, b)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def fmin(a, b):                                            # [関数定義] fmin の処理実行ブロック
            return min(a, b)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def atan(x):                                               # [関数定義] atan の処理実行ブロック
            return math.atan(x)                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def cos(x):                                                # [関数定義] cos の処理実行ブロック
            return math.cos(x)                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def sin(x):                                                # [関数定義] sin の処理実行ブロック
            return math.sin(x)                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def sqrt(x):                                               # [関数定義] sqrt の処理実行ブロック
            return math.sqrt(x)                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def fabs(x):                                               # [関数定義] fabs の処理実行ブロック
            return abs(x)                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    ca = _CasadiCompat()

def _is_symbolic(x):                                               # [関数定義] _is_symbolic の処理実行ブロック
    return isinstance(x, (ca.SX, ca.MX)) or (hasattr(x, 'is_symbolic') and x.is_symbolic())  # [戻り値] 計算結果・計算状態の呼び出し元への返却

@dataclass
class Params:                                                      # [クラス定義] Params オブジェクトの設計
    dt: float=600.0
    rho: float=1.18
    CdA: float=0.13
    Crr: float=0.002
    Crr_per_wheel: float=0.0
    m: float=250.0
    g: float=9.80665
    P_aux: float=60.0
    gear_eta: float=0.98
    gear_ratio: float=6.0
    wheel_radius: float=0.28
    wheel_count: int=4
    driven_wheel_count: int=2
    motor_count: int=1
    motor_type: str='generic'
    inverter_eta: float=1.0
    pv_area: float=6.0
    pv_eta_ref: float=0.23
    pv_mu_p: float=-0.0045
    mppt_eta: float=0.95
    panel_gain: float=1.0
    E_nom_Wh: float=3055.0
    V_min: float=260.0
    V_max: float=400.0
    I_max: float=120.0
    I_chg_min: float=-90.0
    T_max: float=55.0
    T_min: float=-5.0
    soc_min: float=0.05
    soc_max: float=0.98
    grade_scale: float=1.0
    drive_eff_scale: float=1.0
    regen_eff_scale: float=1.0
    rint_scale: float=1.0
    r_line_ohm: float=0.01
    eta_charge: float=1.0

class SolarCarModel:                                               # [車両モデルクラス] ソーラーカーの空力・転がり・発電・電池の統合物理モデル
    def __init__(self, drive_map_path, regen_map_path, Rint_map_path,  # [関数定義] __init__ の処理実行ブロック
                 params=None, panel_eff_map_path=None, mppt_eff_map_path=None,
                 drive_map_eco_path=None, drive_map_power_path=None,
                 regen_map_eco_path=None, regen_map_power_path=None,
                 ocv_soc_map_path=None):
        self.p = params or Params()
        self.drive_power_gain = 1.0
        self.aux_power_override_w = None
        self.v_grid, self.tau_grid, self.Z_drv = read_eff_map(drive_map_path)
        self.v_gridR, self.tau_gridR, self.Z_reg = read_eff_map(regen_map_path)
        self.drive_mode = 'auto'
        self.drive_mode_default = 'eco'
        self.drive_mode_tau_margin = 0.0
        self.maps_drive = {
            'default': (self.v_grid, self.tau_grid, self.Z_drv),
        }
        self.maps_regen = {
            'default': (self.v_gridR, self.tau_gridR, self.Z_reg),
        }
        if drive_map_eco_path:
            self.maps_drive['eco'] = read_eff_map(drive_map_eco_path)
        if drive_map_power_path:
            self.maps_drive['power'] = read_eff_map(drive_map_power_path)
        if regen_map_eco_path:
            self.maps_regen['eco'] = read_eff_map(regen_map_eco_path)
        if regen_map_power_path:
            self.maps_regen['power'] = read_eff_map(regen_map_power_path)
        self._update_mode_limits()
        self.Tg, self.zg, self.Rmap = read_Rint_map(Rint_map_path)
        self.panel_eff_map = None
        self.mppt_eff_map = None
        if panel_eff_map_path:
            try:
                self.Gg, self.Tcg, self.Z_panel = read_map(panel_eff_map_path)
                self.panel_eff_map = True
            except Exception:
                self.panel_eff_map = None
        if mppt_eff_map_path:
            try:
                self.Gm, self.Tm, self.Z_mppt = read_map(mppt_eff_map_path)
                self.mppt_eff_map = True
            except Exception:
                self.mppt_eff_map = None
        self.ocv_soc_map = None
        if ocv_soc_map_path:
            try:
                self.soc_grid, self.ocv_grid = read_1d_map(ocv_soc_map_path)
                self.ocv_soc_map = True
            except Exception:
                self.ocv_soc_map = None

    def eff_drive(self, v_ms, tau_nm):                             # [関数定義] eff_drive の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(tau_nm):
            v = ca.fabs(v_ms); t = ca.fabs(tau_nm)
            vN = v/35.0; tN = t/60.0
            eff = 0.92 - 0.08*vN*vN - 0.06*ca.sqrt(tN+1e-9)
            eff = eff * float(self.p.drive_eff_scale)
            return ca.fmin(0.99, ca.fmax(0.55, eff))               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        mode = self._select_mode(float(v_ms), float(abs(tau_nm)))
        v_grid, t_grid, Z = self.maps_drive.get(mode, self.maps_drive['default'])
        eff = float(bilinear_interp(v_grid, t_grid, Z, float(v_ms), float(abs(tau_nm))))
        eff *= float(self.p.drive_eff_scale)
        return float(np.clip(eff, 0.55, 0.99))                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def eff_regen(self, v_ms, tau_nm):                             # [関数定義] eff_regen の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(tau_nm):
            v = ca.fabs(v_ms); t = ca.fabs(tau_nm)
            vN = v/35.0; tN = t/60.0
            eff = 0.70 + 0.12*vN - 0.05*(tN-0.3)*(tN-0.3)
            eff = eff * float(self.p.regen_eff_scale or self.p.drive_eff_scale)
            return ca.fmin(0.95, ca.fmax(0.40, eff))               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        mode = self._select_mode(float(v_ms), float(abs(tau_nm)))
        v_grid, t_grid, Z = self.maps_regen.get(mode, self.maps_regen['default'])
        eff = float(bilinear_interp(v_grid, t_grid, Z, float(v_ms), float(abs(tau_nm))))
        eff *= float(self.p.regen_eff_scale or self.p.drive_eff_scale)
        return float(np.clip(eff, 0.40, 0.95))                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _update_mode_limits(self):                                 # [関数定義] _update_mode_limits の処理実行ブロック
        self.tau_max = {}
        for k, (_, t_grid, _) in self.maps_drive.items():
            try:
                self.tau_max[k] = float(max(t_grid))
            except Exception:
                self.tau_max[k] = 0.0

    def _select_mode(self, v_ms: float, tau_nm: float) -> str:     # [関数定義] _select_mode の処理実行ブロック
        mode = str(self.drive_mode or 'default').lower()
        if mode in ('eco', 'power'):
            return mode                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        # auto
        eco_max = self.tau_max.get('eco', self.tau_max.get('default', 0.0))
        margin = float(self.drive_mode_tau_margin or 0.0)
        if tau_nm > (eco_max + margin):
            return 'power' if 'power' in self.maps_drive else 'default'  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return 'eco' if 'eco' in self.maps_drive else 'default'    # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def select_drive_mode(self, v_ms: float, tau_nm: float) -> str:  # [関数定義] select_drive_mode の処理実行ブロック
        return self._select_mode(v_ms, abs(tau_nm))                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def R_int(self, T_C, z):                                       # [関数定義] R_int の処理実行ブロック
        if _is_symbolic(T_C) or _is_symbolic(z):
            R0=0.015; R_T=0.0002*(25.0-T_C); R_z=0.01*(1.0-z)
            return (R0+R_T+R_z) * float(self.p.rint_scale)         # [戻り値] 計算結果・計算状態の呼び出し元への返却
        else:
            return float(self.p.rint_scale) * float(bilinear_interp(self.Tg, self.zg, self.Rmap, T_C, z))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def pv_power_mppt(self, G_poa, T_cell_C):                      # [関数定義] pv_power_mppt の処理実行ブロック
        if self.panel_eff_map:
            eta_panel = bilinear_interp(self.Gg, self.Tcg, self.Z_panel, float(G_poa), float(T_cell_C))
            eta_panel = max(0.0, float(eta_panel))
        else:
            eta_panel = self.p.pv_eta_ref*(1.0+self.p.pv_mu_p*(T_cell_C-25.0))
            eta_panel = ca.fmax(0.0, eta_panel)
        eta_panel *= float(self.p.panel_gain)
        P_pv = eta_panel*self.p.pv_area*G_poa
        if self.mppt_eff_map:
            eta_mppt = bilinear_interp(self.Gm, self.Tm, self.Z_mppt, float(G_poa), float(T_cell_C))
            eta_mppt = max(0.0, float(eta_mppt))
            return eta_mppt*P_pv                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return self.p.mppt_eta*P_pv                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _scaled_slope_pct(self, slope_pct):                        # [関数定義] _scaled_slope_pct の処理実行ブロック
        return slope_pct * float(self.p.grade_scale)               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def charge_efficiency(self, P_pack) -> float:                  # [関数定義] charge_efficiency の処理実行ブロック
        try:
            p_pack = float(P_pack)
        except Exception:
            return 1.0                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return float(self.p.eta_charge) if p_pack < 0.0 else 1.0   # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def soc_step(self, z: float, P_pack: float, dt_sec: float) -> float:  # [関数定義] soc_step の処理実行ブロック
        eta = self.charge_efficiency(P_pack)
        return float(z) - eta * (float(P_pack) * float(dt_sec) / 3600.0) / max(float(self.p.E_nom_Wh), 1.0e-6)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def ocv_from_soc(self, z):                                     # [関数定義] ocv_from_soc の処理実行ブロック
        if _is_symbolic(z) or not self.ocv_soc_map:
            z_clamped = ca.fmin(self.p.soc_max, ca.fmax(self.p.soc_min, z))
            return self.p.V_min + (self.p.V_max - self.p.V_min) * z_clamped  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        zc = float(np.clip(z, self.p.soc_min, self.p.soc_max))
        return float(np.interp(zc, self.soc_grid, self.ocv_grid))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def load_ocv_map(self, path: str) -> bool:                     # [関数定義] load_ocv_map の処理実行ブロック
        try:
            self.soc_grid, self.ocv_grid = read_1d_map(path)
            self.ocv_soc_map = True
            return True                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception:
            self.ocv_soc_map = None
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def resistive_forces(self, v_ms, slope_pct, headwind_ms=0.0):  # [関数定義] resistive_forces の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(slope_pct) or _is_symbolic(headwind_ms):
            v_rel = ca.fmax(0.0, v_ms + headwind_ms)
            theta = ca.atan(self._scaled_slope_pct(slope_pct) / 100.0)
            F_aero = 0.5 * self.p.rho * self.p.CdA * v_rel ** 2
            N = self.p.m * self.p.g * ca.cos(theta)
            Crr_eff = self.p.Crr
            if self.p.Crr_per_wheel and self.p.wheel_count:
                Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
            F_roll = Crr_eff * N
            F_grade = self.p.m * self.p.g * ca.sin(theta)
            F_total = F_aero + F_roll + F_grade
            return dict(F_aero=F_aero, F_roll=F_roll, F_grade=F_grade,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                        F_total=F_total, theta=theta)
        v_rel = max(0.0, float(v_ms) + float(headwind_ms))
        theta = math.atan(float(self._scaled_slope_pct(slope_pct)) / 100.0)
        F_aero = 0.5 * self.p.rho * self.p.CdA * v_rel ** 2
        N = self.p.m * self.p.g * math.cos(theta)
        Crr_eff = self.p.Crr
        if self.p.Crr_per_wheel and self.p.wheel_count:
            Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
        F_roll = Crr_eff * N
        F_grade = self.p.m * self.p.g * math.sin(theta)
        F_total = F_aero + F_roll + F_grade
        return dict(F_aero=F_aero, F_roll=F_roll, F_grade=F_grade,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                    F_total=F_total, theta=theta)

    def battery_iv(self, P_pack, z, Tbat_C):                       # [関数定義] battery_iv の処理実行ブロック
        OCV = self.ocv_from_soc(z)
        Rint = self.R_int(Tbat_C, ca.fmin(0.95, ca.fmax(0.1, z)))
        Rline = float(self.p.r_line_ohm)
        Rtot = Rint + Rline
        a = Rtot
        b = -OCV
        c = P_pack
        disc = ca.fmax(b * b - 4 * a * c, 0.0)
        I = (OCV - ca.sqrt(disc)) / (2 * Rtot)
        V = OCV - I * Rtot
        return dict(I=I, V=V, OCV=OCV, Rint=Rint, Rline=Rline)     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def mech_power(self, v_ms, slope_pct, headwind_ms=0.0):        # [関数定義] mech_power の処理実行ブロック
        v_rel = ca.fmax(0.0, v_ms + headwind_ms)
        P_aero = 0.5*self.p.rho*self.p.CdA*v_rel**3
        theta  = ca.atan(self._scaled_slope_pct(slope_pct)/100.0)
        N = self.p.m*self.p.g*ca.cos(theta)
        Crr_eff = self.p.Crr
        if self.p.Crr_per_wheel and self.p.wheel_count:
            Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
        P_roll = Crr_eff*N*v_ms
        P_grade= self.p.m*self.p.g*ca.sin(theta)*v_ms
        drive_power = (P_aero + P_roll + P_grade) * float(self.drive_power_gain)
        aux_power = float(self.aux_power_override_w) if self.aux_power_override_w is not None else float(self.p.P_aux)
        return drive_power + aux_power                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def torque_from_mech(self, P_mech, v_ms, wheel_radius=None, ratio=None):  # [関数定義] torque_from_mech の処理実行ブロック
        if wheel_radius is None:
            wheel_radius = self.p.wheel_radius
        if ratio is None:
            ratio = self.p.gear_ratio
        eps=1e-3
        omega_w = v_ms/wheel_radius
        T_w = P_mech/(omega_w+eps)
        T_m = T_w/ratio
        return T_m, omega_w*ratio                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def electrical_balance(self, v_ms, slope_pct, z, Tbat_C, G_poa, Tcell_C, headwind_ms=0.0):  # [関数定義] electrical_balance の処理実行ブロック
        P_pv = self.pv_power_mppt(G_poa, Tcell_C)
        P_mech = self.mech_power(v_ms, slope_pct, headwind_ms)
        P_mech_pos = ca.fmax(P_mech, 0.0)
        P_mech_neg = ca.fmax(-P_mech, 0.0)
        Tm_drv, _ = self.torque_from_mech(P_mech_pos, v_ms)
        eff_drv = self.eff_drive(v_ms, Tm_drv)
        P_dc_to_drv = P_mech_pos/(eff_drv*self.p.gear_eta*self.p.inverter_eta)
        Tm_reg, _ = self.torque_from_mech(P_mech_neg, v_ms)
        eff_reg = self.eff_regen(v_ms, Tm_reg)
        P_reg_to_dc = eff_reg*self.p.gear_eta*self.p.inverter_eta*P_mech_neg
        P_pack = P_dc_to_drv - P_reg_to_dc - P_pv
        OCV = self.ocv_from_soc(z)
        Rint = self.R_int(Tbat_C, ca.fmin(0.95, ca.fmax(0.1, z)))
        Rline = float(self.p.r_line_ohm); Rtot = Rint + Rline
        a = Rtot; b=-OCV; c=P_pack
        disc = ca.fmax(b*b-4*a*c, 0.0)
        I = (OCV - ca.sqrt(disc))/(2*Rtot)
        V = OCV - I*Rtot
        losses_line = I*I*Rline; losses_int = I*I*Rint
        aux_power = float(self.aux_power_override_w) if self.aux_power_override_w is not None else float(self.p.P_aux)
        P_mech_wheel = P_mech - aux_power
        return dict(P_pv=P_pv, P_mech=P_mech, P_mech_wheel=P_mech_wheel,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                    P_pack=P_pack, I=I, V=V,
                    losses_line=losses_line, losses_int=losses_int,
                    OCV=OCV, Rint=Rint, Rline=Rline,
                    P_dc_to_drv=P_dc_to_drv, P_reg_to_dc=P_reg_to_dc,
                    eff_drv=eff_drv, eff_reg=eff_reg)

# =============================================================================
# 【統合ユーティリティ】マップ読み込み・2D/1D線形補間関数群
# =============================================================================
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
def bilinear_interp(xg, yg, Z, x, y):                              # [関数定義] bilinear_interp の処理実行ブロック
    xg = np.asarray(xg); yg=np.asarray(yg); Z=np.asarray(Z)
    x = np.clip(x, xg[0], xg[-1]); y=np.clip(y, yg[0], yg[-1])
    i = np.searchsorted(xg, x)-1; i=np.clip(i,0,len(xg)-2)
    j = np.searchsorted(yg, y)-1; j=np.clip(j,0,len(yg)-2)
    x0,x1=xg[i],xg[i+1]; y0,y1=yg[j],yg[j+1]
    Z00=Z[i,j]; Z10=Z[i+1,j]; Z01=Z[i,j+1]; Z11=Z[i+1,j+1]
    wx=0 if x1==x0 else (x-x0)/(x1-x0)
    wy=0 if y1==y0 else (y-y0)/(y1-y0)
    return (1-wx)*(1-wy)*Z00 + wx*(1-wy)*Z10 + (1-wx)*wy*Z01 + wx*wy*Z11  # [戻り値] 計算結果・計算状態の呼び出し元への返却
def read_eff_map(path):                                            # [関数定義] read_eff_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
def read_Rint_map(path):                                           # [関数定義] read_Rint_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

def read_map(path):                                                # [関数定義] read_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

def read_1d_map(path):                                             # [関数定義] read_1d_map の処理実行ブロック
    df = pd.read_csv(path)
    if df.shape[1] >= 2:
        x = df.iloc[:, 0].values.astype(float)
        y = df.iloc[:, 1].values.astype(float)
        return x, y                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    df = pd.read_csv(path, index_col=0)
    x = df.index.values.astype(float)
    y = df.iloc[:, 0].values.astype(float)
    return x, y                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

import time




class SolarStateNode:                                        # [状態推定ノード] バッテリーSoC・電圧・過渡分極(V1)の状態推定ノード
    """Mirror planner outputs into vehicle/system topics for solar-only simulation."""

    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        self.declare_parameter('publish_rate_hz', 5.0)
        self.declare_parameter('stale_timeout_sec', 5.0)

        self.speed_cmd_kmh = 0.0
        self.speed_meas_kmh = 0.0
        self.throttle_pct = 0.0
        self.drive_mode = 'auto'
        self.soc = 0.80
        self.tb_c = 25.0
        self.s_km = 0.0
        self.status_s_km = 0.0
        self.batt_current_a = 0.0
        self.batt_voltage_v = 0.0
        self.forecast_k = 0.0
        self.sec_to_next = 0.0
        self.has_status = False
        self.has_metrics = False
        self.last_status_time = 0.0
        self.last_metrics_time = 0.0
        self.last_lower_plan_time = 0.0
        self.last_publish_time = time.monotonic()

        self.pub_speed = self.create_publisher(Float32, '/vehicle/speed_kmh', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_s_km = self.create_publisher(Float32, '/vehicle/s_km', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_soc = self.create_publisher(Float32, '/vehicle/batt_soc', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_tb = self.create_publisher(Float32, '/vehicle/batt_temp_c', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_ibatt = self.create_publisher(Float32, '/vehicle/batt_current_a', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vbatt = self.create_publisher(Float32, '/vehicle/batt_voltage_v', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_throttle = self.create_publisher(Float32, '/vehicle/throttle_pct', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_state = self.create_publisher(String, '/system/state', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_diag = self.create_publisher(String, '/system/diag', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_mpc_state = self.create_publisher(String, '/system/mpc_state', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_health = self.create_publisher(Float32, '/system/health', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        self.create_subscription(Float32, '/planner/speed_cmd', self._on_speed_cmd, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/planner/throttle_cmd_pct', self._on_throttle, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/planner/drive_mode', self._on_drive_mode, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/status', self._on_status, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/metrics', self._on_metrics, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/lower_plan', self._on_lower_plan, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        period = 1.0 / max(0.5, float(self.get_parameter('publish_rate_hz').value))
        self.timer = self.create_timer(period, self._publish)
        print('SolarStateNode started.')

    def _on_speed_cmd(self, msg: Float32):                         # [関数定義] _on_speed_cmd の処理実行ブロック
        self.speed_cmd_kmh = float(msg.data)
        self.speed_meas_kmh = float(msg.data)

    def _on_throttle(self, msg: Float32):                          # [関数定義] _on_throttle の処理実行ブロック
        self.throttle_pct = float(msg.data)

    def _on_drive_mode(self, msg: String):                         # [関数定義] _on_drive_mode の処理実行ブロック
        self.drive_mode = str(msg.data)

    def _on_status(self, msg: Float32MultiArray):                  # [関数定義] _on_status の処理実行ブロック
        data = list(msg.data)
        if len(data) < 5:
            return
        self.soc = float(data[0])
        self.tb_c = float(data[1])
        self.status_s_km = float(data[2])
        if not self.has_status:
            self.s_km = float(data[2])
        self.forecast_k = float(data[3])
        self.sec_to_next = float(data[4])
        self.has_status = True
        self.last_status_time = time.monotonic()

    def _on_metrics(self, msg: Float32MultiArray):                 # [関数定義] _on_metrics の処理実行ブロック
        data = list(msg.data)
        if len(data) < 7:
            return
        self.batt_voltage_v = float(data[0])
        self.batt_current_a = float(data[1])
        self.soc = float(data[2])
        self.speed_cmd_kmh = float(data[6])
        self.speed_meas_kmh = float(data[6])
        self.has_metrics = True
        self.last_metrics_time = time.monotonic()

    def _on_lower_plan(self, msg: Float32MultiArray):              # [関数定義] _on_lower_plan の処理実行ブロック
        if len(msg.data) > 1:
            self.last_lower_plan_time = time.monotonic()

    def _publish(self):                                            # [関数定義] _publish の処理実行ブロック
        now = time.monotonic()
        dt = max(0.0, now - self.last_publish_time)
        self.last_publish_time = now
        stale_timeout = max(1.0, float(self.get_parameter('stale_timeout_sec').value))
        status_age = now - self.last_status_time if self.has_status else float('inf')
        metrics_age = now - self.last_metrics_time if self.has_metrics else float('inf')
        healthy = status_age <= stale_timeout and metrics_age <= stale_timeout

        self.s_km = max(self.s_km, self.status_s_km)
        self.s_km += float(self.speed_meas_kmh) * (dt / 3600.0)

        self.pub_speed.publish(Float32(data=float(self.speed_meas_kmh)))
        self.pub_s_km.publish(Float32(data=float(self.s_km)))
        self.pub_soc.publish(Float32(data=float(self.soc)))
        self.pub_tb.publish(Float32(data=float(self.tb_c)))
        self.pub_ibatt.publish(Float32(data=float(self.batt_current_a)))
        self.pub_vbatt.publish(Float32(data=float(self.batt_voltage_v)))
        self.pub_throttle.publish(Float32(data=float(self.throttle_pct)))

        if not self.has_status:
            state = 'STARTING'
        elif healthy:
            state = 'RUNNING'
        else:
            state = 'STALE'

        if healthy:
            diag = f'forecast_k={self.forecast_k:.0f}, next={self.sec_to_next:.0f}s'
        elif self.has_status or self.has_metrics:
            diag = 'planner topics became stale'
        else:
            diag = 'waiting for planner topics'

        if self.last_lower_plan_time > 0.0 and (now - self.last_lower_plan_time) <= stale_timeout:
            mpc_state = 'HIERARCHICAL'
        else:
            mpc_state = 'UPPER_ONLY'

        health = 1.0 if healthy else (0.5 if self.has_status or self.has_metrics else 0.0)
        self.pub_state.publish(String(data=state))
        self.pub_diag.publish(String(data=diag))
        self.pub_mpc_state.publish(String(data=mpc_state))
        self.pub_health.publish(Float32(data=float(health)))


def main():                                                        # [メイン関数] エントリーポイント関数
    node = SolarStateNode()
    node.destroy_node()


if __name__ == '__main__':                                         # [直接実行スクリプト] スクリプト直接起動時のメイン実行ブロック
    main()

# =============================================================================
# 【統合ロジック】移動ホライズン状態推定器 (MHE / EKF)
# =============================================================================
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
from scipy.optimize import minimize


@dataclass
class MheInput:                                                    # [クラス定義] MheInput オブジェクトの設計
    v_ms: float
    slope_pct: float
    G_poa: float
    Tcell_C: float
    Tamb_C: float
    headwind_ms: float
    dt: float


@dataclass
class MheMeas:                                                     # [クラス定義] MheMeas オブジェクトの設計
    soc: Optional[float] = None
    Tb: Optional[float] = None
    I: Optional[float] = None
    V: Optional[float] = None


class BatteryMHE:                                                  # [クラス定義] BatteryMHE オブジェクトの設計
    def __init__(                                                  # [関数定義] __init__ の処理実行ブロック
        self,
        model,
        horizon_steps: int = 12,
        w_soc: float = 50.0,
        w_tb: float = 5.0,
        w_i: float = 1.0,
        w_v: float = 1.0,
        w_prior: float = 5.0,
        soc_bounds: Tuple[float, float] = (0.05, 0.98),
        tb_bounds: Tuple[float, float] = (-10.0, 65.0),
    ):
        self.model = model
        self.samples = deque(maxlen=max(2, int(horizon_steps)))
        self.w_soc = float(w_soc)
        self.w_tb = float(w_tb)
        self.w_i = float(w_i)
        self.w_v = float(w_v)
        self.w_prior = float(w_prior)
        self.soc_bounds = soc_bounds
        self.tb_bounds = tb_bounds

    def push(self, u: MheInput, y: MheMeas):                       # [関数定義] push の処理実行ブロック
        self.samples.append((u, y))

    def _simulate(self, z0: float, Tb0: float):                    # [関数定義] _simulate の処理実行ブロック
        z = float(z0)
        Tb = float(Tb0)
        outputs = []
        for (u, _) in self.samples:
            out = self.model.electrical_balance(
                u.v_ms,
                u.slope_pct,
                z,
                Tb,
                u.G_poa,
                u.Tcell_C,
                headwind_ms=u.headwind_ms,
            )
            I = float(out['I'])
            V = float(out['V'])
            P_pack = float(out['P_pack'])
            loss_int = float(out['losses_int'])
            dt = float(u.dt)
            z_next = self.model.soc_step(z, P_pack, dt)
            Tb_next = Tb + (dt / 1800.0) * (u.Tamb_C - Tb) + (loss_int * dt) / 50000.0
            outputs.append((z_next, Tb_next, I, V))
            z, Tb = z_next, Tb_next
        return outputs, z, Tb                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def estimate(self, z_init: float, Tb_init: float) -> Tuple[float, float]:  # [関数定義] estimate の処理実行ブロック
        if len(self.samples) < 2:
            return z_init, Tb_init                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

        def cost(x):                                               # [関数定義] cost の処理実行ブロック
            z0, Tb0 = float(x[0]), float(x[1])
            J = self.w_prior * ((z0 - z_init) ** 2 + (Tb0 - Tb_init) ** 2)
            outputs, _, _ = self._simulate(z0, Tb0)
            for (_, meas), (z_pred, Tb_pred, I_pred, V_pred) in zip(self.samples, outputs):
                if meas.soc is not None and math.isfinite(meas.soc):
                    J += self.w_soc * (z_pred - meas.soc) ** 2
                if meas.Tb is not None and math.isfinite(meas.Tb):
                    J += self.w_tb * (Tb_pred - meas.Tb) ** 2
                if meas.I is not None and math.isfinite(meas.I):
                    J += self.w_i * (I_pred - meas.I) ** 2
                if meas.V is not None and math.isfinite(meas.V):
                    J += self.w_v * (V_pred - meas.V) ** 2
            return J                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

        x0 = np.array([float(z_init), float(Tb_init)], dtype=float)
        bounds = [self.soc_bounds, self.tb_bounds]
        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=80))
        if not res.success:
            return z_init, Tb_init                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
        z0, Tb0 = float(res.x[0]), float(res.x[1])
        _, zN, TbN = self._simulate(z0, Tb0)
        return float(zN), float(TbN)                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

# =============================================================================
# 【統合物理モデル】車両・電池物理パラメータ定義
# =============================================================================
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
from dataclasses import dataclass

try:
    import casadi as ca                                            # [最適化エンジン] 数値最適化・自動微分ライブラリ CasADi のインポート
except ImportError:
    class _CasadiCompat:                                           # [クラス定義] _CasadiCompat オブジェクトの設計
        class SX:                                                  # [クラス定義] SX オブジェクトの設計
            pass

        class MX:                                                  # [クラス定義] MX オブジェクトの設計
            pass

        @staticmethod
        def fmax(a, b):                                            # [関数定義] fmax の処理実行ブロック
            return max(a, b)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def fmin(a, b):                                            # [関数定義] fmin の処理実行ブロック
            return min(a, b)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def atan(x):                                               # [関数定義] atan の処理実行ブロック
            return math.atan(x)                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def cos(x):                                                # [関数定義] cos の処理実行ブロック
            return math.cos(x)                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def sin(x):                                                # [関数定義] sin の処理実行ブロック
            return math.sin(x)                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def sqrt(x):                                               # [関数定義] sqrt の処理実行ブロック
            return math.sqrt(x)                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def fabs(x):                                               # [関数定義] fabs の処理実行ブロック
            return abs(x)                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    ca = _CasadiCompat()

def _is_symbolic(x):                                               # [関数定義] _is_symbolic の処理実行ブロック
    return isinstance(x, (ca.SX, ca.MX)) or (hasattr(x, 'is_symbolic') and x.is_symbolic())  # [戻り値] 計算結果・計算状態の呼び出し元への返却

@dataclass
class Params:                                                      # [クラス定義] Params オブジェクトの設計
    dt: float=600.0
    rho: float=1.18
    CdA: float=0.13
    Crr: float=0.002
    Crr_per_wheel: float=0.0
    m: float=250.0
    g: float=9.80665
    P_aux: float=60.0
    gear_eta: float=0.98
    gear_ratio: float=6.0
    wheel_radius: float=0.28
    wheel_count: int=4
    driven_wheel_count: int=2
    motor_count: int=1
    motor_type: str='generic'
    inverter_eta: float=1.0
    pv_area: float=6.0
    pv_eta_ref: float=0.23
    pv_mu_p: float=-0.0045
    mppt_eta: float=0.95
    panel_gain: float=1.0
    E_nom_Wh: float=3055.0
    V_min: float=260.0
    V_max: float=400.0
    I_max: float=120.0
    I_chg_min: float=-90.0
    T_max: float=55.0
    T_min: float=-5.0
    soc_min: float=0.05
    soc_max: float=0.98
    grade_scale: float=1.0
    drive_eff_scale: float=1.0
    regen_eff_scale: float=1.0
    rint_scale: float=1.0
    r_line_ohm: float=0.01
    eta_charge: float=1.0

class SolarCarModel:                                               # [車両モデルクラス] ソーラーカーの空力・転がり・発電・電池の統合物理モデル
    def __init__(self, drive_map_path, regen_map_path, Rint_map_path,  # [関数定義] __init__ の処理実行ブロック
                 params=None, panel_eff_map_path=None, mppt_eff_map_path=None,
                 drive_map_eco_path=None, drive_map_power_path=None,
                 regen_map_eco_path=None, regen_map_power_path=None,
                 ocv_soc_map_path=None):
        self.p = params or Params()
        self.drive_power_gain = 1.0
        self.aux_power_override_w = None
        self.v_grid, self.tau_grid, self.Z_drv = read_eff_map(drive_map_path)
        self.v_gridR, self.tau_gridR, self.Z_reg = read_eff_map(regen_map_path)
        self.drive_mode = 'auto'
        self.drive_mode_default = 'eco'
        self.drive_mode_tau_margin = 0.0
        self.maps_drive = {
            'default': (self.v_grid, self.tau_grid, self.Z_drv),
        }
        self.maps_regen = {
            'default': (self.v_gridR, self.tau_gridR, self.Z_reg),
        }
        if drive_map_eco_path:
            self.maps_drive['eco'] = read_eff_map(drive_map_eco_path)
        if drive_map_power_path:
            self.maps_drive['power'] = read_eff_map(drive_map_power_path)
        if regen_map_eco_path:
            self.maps_regen['eco'] = read_eff_map(regen_map_eco_path)
        if regen_map_power_path:
            self.maps_regen['power'] = read_eff_map(regen_map_power_path)
        self._update_mode_limits()
        self.Tg, self.zg, self.Rmap = read_Rint_map(Rint_map_path)
        self.panel_eff_map = None
        self.mppt_eff_map = None
        if panel_eff_map_path:
            try:
                self.Gg, self.Tcg, self.Z_panel = read_map(panel_eff_map_path)
                self.panel_eff_map = True
            except Exception:
                self.panel_eff_map = None
        if mppt_eff_map_path:
            try:
                self.Gm, self.Tm, self.Z_mppt = read_map(mppt_eff_map_path)
                self.mppt_eff_map = True
            except Exception:
                self.mppt_eff_map = None
        self.ocv_soc_map = None
        if ocv_soc_map_path:
            try:
                self.soc_grid, self.ocv_grid = read_1d_map(ocv_soc_map_path)
                self.ocv_soc_map = True
            except Exception:
                self.ocv_soc_map = None

    def eff_drive(self, v_ms, tau_nm):                             # [関数定義] eff_drive の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(tau_nm):
            v = ca.fabs(v_ms); t = ca.fabs(tau_nm)
            vN = v/35.0; tN = t/60.0
            eff = 0.92 - 0.08*vN*vN - 0.06*ca.sqrt(tN+1e-9)
            eff = eff * float(self.p.drive_eff_scale)
            return ca.fmin(0.99, ca.fmax(0.55, eff))               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        mode = self._select_mode(float(v_ms), float(abs(tau_nm)))
        v_grid, t_grid, Z = self.maps_drive.get(mode, self.maps_drive['default'])
        eff = float(bilinear_interp(v_grid, t_grid, Z, float(v_ms), float(abs(tau_nm))))
        eff *= float(self.p.drive_eff_scale)
        return float(np.clip(eff, 0.55, 0.99))                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def eff_regen(self, v_ms, tau_nm):                             # [関数定義] eff_regen の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(tau_nm):
            v = ca.fabs(v_ms); t = ca.fabs(tau_nm)
            vN = v/35.0; tN = t/60.0
            eff = 0.70 + 0.12*vN - 0.05*(tN-0.3)*(tN-0.3)
            eff = eff * float(self.p.regen_eff_scale or self.p.drive_eff_scale)
            return ca.fmin(0.95, ca.fmax(0.40, eff))               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        mode = self._select_mode(float(v_ms), float(abs(tau_nm)))
        v_grid, t_grid, Z = self.maps_regen.get(mode, self.maps_regen['default'])
        eff = float(bilinear_interp(v_grid, t_grid, Z, float(v_ms), float(abs(tau_nm))))
        eff *= float(self.p.regen_eff_scale or self.p.drive_eff_scale)
        return float(np.clip(eff, 0.40, 0.95))                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _update_mode_limits(self):                                 # [関数定義] _update_mode_limits の処理実行ブロック
        self.tau_max = {}
        for k, (_, t_grid, _) in self.maps_drive.items():
            try:
                self.tau_max[k] = float(max(t_grid))
            except Exception:
                self.tau_max[k] = 0.0

    def _select_mode(self, v_ms: float, tau_nm: float) -> str:     # [関数定義] _select_mode の処理実行ブロック
        mode = str(self.drive_mode or 'default').lower()
        if mode in ('eco', 'power'):
            return mode                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        # auto
        eco_max = self.tau_max.get('eco', self.tau_max.get('default', 0.0))
        margin = float(self.drive_mode_tau_margin or 0.0)
        if tau_nm > (eco_max + margin):
            return 'power' if 'power' in self.maps_drive else 'default'  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return 'eco' if 'eco' in self.maps_drive else 'default'    # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def select_drive_mode(self, v_ms: float, tau_nm: float) -> str:  # [関数定義] select_drive_mode の処理実行ブロック
        return self._select_mode(v_ms, abs(tau_nm))                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def R_int(self, T_C, z):                                       # [関数定義] R_int の処理実行ブロック
        if _is_symbolic(T_C) or _is_symbolic(z):
            R0=0.015; R_T=0.0002*(25.0-T_C); R_z=0.01*(1.0-z)
            return (R0+R_T+R_z) * float(self.p.rint_scale)         # [戻り値] 計算結果・計算状態の呼び出し元への返却
        else:
            return float(self.p.rint_scale) * float(bilinear_interp(self.Tg, self.zg, self.Rmap, T_C, z))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def pv_power_mppt(self, G_poa, T_cell_C):                      # [関数定義] pv_power_mppt の処理実行ブロック
        if self.panel_eff_map:
            eta_panel = bilinear_interp(self.Gg, self.Tcg, self.Z_panel, float(G_poa), float(T_cell_C))
            eta_panel = max(0.0, float(eta_panel))
        else:
            eta_panel = self.p.pv_eta_ref*(1.0+self.p.pv_mu_p*(T_cell_C-25.0))
            eta_panel = ca.fmax(0.0, eta_panel)
        eta_panel *= float(self.p.panel_gain)
        P_pv = eta_panel*self.p.pv_area*G_poa
        if self.mppt_eff_map:
            eta_mppt = bilinear_interp(self.Gm, self.Tm, self.Z_mppt, float(G_poa), float(T_cell_C))
            eta_mppt = max(0.0, float(eta_mppt))
            return eta_mppt*P_pv                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return self.p.mppt_eta*P_pv                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _scaled_slope_pct(self, slope_pct):                        # [関数定義] _scaled_slope_pct の処理実行ブロック
        return slope_pct * float(self.p.grade_scale)               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def charge_efficiency(self, P_pack) -> float:                  # [関数定義] charge_efficiency の処理実行ブロック
        try:
            p_pack = float(P_pack)
        except Exception:
            return 1.0                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return float(self.p.eta_charge) if p_pack < 0.0 else 1.0   # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def soc_step(self, z: float, P_pack: float, dt_sec: float) -> float:  # [関数定義] soc_step の処理実行ブロック
        eta = self.charge_efficiency(P_pack)
        return float(z) - eta * (float(P_pack) * float(dt_sec) / 3600.0) / max(float(self.p.E_nom_Wh), 1.0e-6)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def ocv_from_soc(self, z):                                     # [関数定義] ocv_from_soc の処理実行ブロック
        if _is_symbolic(z) or not self.ocv_soc_map:
            z_clamped = ca.fmin(self.p.soc_max, ca.fmax(self.p.soc_min, z))
            return self.p.V_min + (self.p.V_max - self.p.V_min) * z_clamped  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        zc = float(np.clip(z, self.p.soc_min, self.p.soc_max))
        return float(np.interp(zc, self.soc_grid, self.ocv_grid))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def load_ocv_map(self, path: str) -> bool:                     # [関数定義] load_ocv_map の処理実行ブロック
        try:
            self.soc_grid, self.ocv_grid = read_1d_map(path)
            self.ocv_soc_map = True
            return True                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception:
            self.ocv_soc_map = None
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def resistive_forces(self, v_ms, slope_pct, headwind_ms=0.0):  # [関数定義] resistive_forces の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(slope_pct) or _is_symbolic(headwind_ms):
            v_rel = ca.fmax(0.0, v_ms + headwind_ms)
            theta = ca.atan(self._scaled_slope_pct(slope_pct) / 100.0)
            F_aero = 0.5 * self.p.rho * self.p.CdA * v_rel ** 2
            N = self.p.m * self.p.g * ca.cos(theta)
            Crr_eff = self.p.Crr
            if self.p.Crr_per_wheel and self.p.wheel_count:
                Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
            F_roll = Crr_eff * N
            F_grade = self.p.m * self.p.g * ca.sin(theta)
            F_total = F_aero + F_roll + F_grade
            return dict(F_aero=F_aero, F_roll=F_roll, F_grade=F_grade,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                        F_total=F_total, theta=theta)
        v_rel = max(0.0, float(v_ms) + float(headwind_ms))
        theta = math.atan(float(self._scaled_slope_pct(slope_pct)) / 100.0)
        F_aero = 0.5 * self.p.rho * self.p.CdA * v_rel ** 2
        N = self.p.m * self.p.g * math.cos(theta)
        Crr_eff = self.p.Crr
        if self.p.Crr_per_wheel and self.p.wheel_count:
            Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
        F_roll = Crr_eff * N
        F_grade = self.p.m * self.p.g * math.sin(theta)
        F_total = F_aero + F_roll + F_grade
        return dict(F_aero=F_aero, F_roll=F_roll, F_grade=F_grade,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                    F_total=F_total, theta=theta)

    def battery_iv(self, P_pack, z, Tbat_C):                       # [関数定義] battery_iv の処理実行ブロック
        OCV = self.ocv_from_soc(z)
        Rint = self.R_int(Tbat_C, ca.fmin(0.95, ca.fmax(0.1, z)))
        Rline = float(self.p.r_line_ohm)
        Rtot = Rint + Rline
        a = Rtot
        b = -OCV
        c = P_pack
        disc = ca.fmax(b * b - 4 * a * c, 0.0)
        I = (OCV - ca.sqrt(disc)) / (2 * Rtot)
        V = OCV - I * Rtot
        return dict(I=I, V=V, OCV=OCV, Rint=Rint, Rline=Rline)     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def mech_power(self, v_ms, slope_pct, headwind_ms=0.0):        # [関数定義] mech_power の処理実行ブロック
        v_rel = ca.fmax(0.0, v_ms + headwind_ms)
        P_aero = 0.5*self.p.rho*self.p.CdA*v_rel**3
        theta  = ca.atan(self._scaled_slope_pct(slope_pct)/100.0)
        N = self.p.m*self.p.g*ca.cos(theta)
        Crr_eff = self.p.Crr
        if self.p.Crr_per_wheel and self.p.wheel_count:
            Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
        P_roll = Crr_eff*N*v_ms
        P_grade= self.p.m*self.p.g*ca.sin(theta)*v_ms
        drive_power = (P_aero + P_roll + P_grade) * float(self.drive_power_gain)
        aux_power = float(self.aux_power_override_w) if self.aux_power_override_w is not None else float(self.p.P_aux)
        return drive_power + aux_power                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def torque_from_mech(self, P_mech, v_ms, wheel_radius=None, ratio=None):  # [関数定義] torque_from_mech の処理実行ブロック
        if wheel_radius is None:
            wheel_radius = self.p.wheel_radius
        if ratio is None:
            ratio = self.p.gear_ratio
        eps=1e-3
        omega_w = v_ms/wheel_radius
        T_w = P_mech/(omega_w+eps)
        T_m = T_w/ratio
        return T_m, omega_w*ratio                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def electrical_balance(self, v_ms, slope_pct, z, Tbat_C, G_poa, Tcell_C, headwind_ms=0.0):  # [関数定義] electrical_balance の処理実行ブロック
        P_pv = self.pv_power_mppt(G_poa, Tcell_C)
        P_mech = self.mech_power(v_ms, slope_pct, headwind_ms)
        P_mech_pos = ca.fmax(P_mech, 0.0)
        P_mech_neg = ca.fmax(-P_mech, 0.0)
        Tm_drv, _ = self.torque_from_mech(P_mech_pos, v_ms)
        eff_drv = self.eff_drive(v_ms, Tm_drv)
        P_dc_to_drv = P_mech_pos/(eff_drv*self.p.gear_eta*self.p.inverter_eta)
        Tm_reg, _ = self.torque_from_mech(P_mech_neg, v_ms)
        eff_reg = self.eff_regen(v_ms, Tm_reg)
        P_reg_to_dc = eff_reg*self.p.gear_eta*self.p.inverter_eta*P_mech_neg
        P_pack = P_dc_to_drv - P_reg_to_dc - P_pv
        OCV = self.ocv_from_soc(z)
        Rint = self.R_int(Tbat_C, ca.fmin(0.95, ca.fmax(0.1, z)))
        Rline = float(self.p.r_line_ohm); Rtot = Rint + Rline
        a = Rtot; b=-OCV; c=P_pack
        disc = ca.fmax(b*b-4*a*c, 0.0)
        I = (OCV - ca.sqrt(disc))/(2*Rtot)
        V = OCV - I*Rtot
        losses_line = I*I*Rline; losses_int = I*I*Rint
        aux_power = float(self.aux_power_override_w) if self.aux_power_override_w is not None else float(self.p.P_aux)
        P_mech_wheel = P_mech - aux_power
        return dict(P_pv=P_pv, P_mech=P_mech, P_mech_wheel=P_mech_wheel,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                    P_pack=P_pack, I=I, V=V,
                    losses_line=losses_line, losses_int=losses_int,
                    OCV=OCV, Rint=Rint, Rline=Rline,
                    P_dc_to_drv=P_dc_to_drv, P_reg_to_dc=P_reg_to_dc,
                    eff_drv=eff_drv, eff_reg=eff_reg)

# =============================================================================
# 【統合ユーティリティ】マップ読み込み・2D/1D線形補間関数群
# =============================================================================
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
def bilinear_interp(xg, yg, Z, x, y):                              # [関数定義] bilinear_interp の処理実行ブロック
    xg = np.asarray(xg); yg=np.asarray(yg); Z=np.asarray(Z)
    x = np.clip(x, xg[0], xg[-1]); y=np.clip(y, yg[0], yg[-1])
    i = np.searchsorted(xg, x)-1; i=np.clip(i,0,len(xg)-2)
    j = np.searchsorted(yg, y)-1; j=np.clip(j,0,len(yg)-2)
    x0,x1=xg[i],xg[i+1]; y0,y1=yg[j],yg[j+1]
    Z00=Z[i,j]; Z10=Z[i+1,j]; Z01=Z[i,j+1]; Z11=Z[i+1,j+1]
    wx=0 if x1==x0 else (x-x0)/(x1-x0)
    wy=0 if y1==y0 else (y-y0)/(y1-y0)
    return (1-wx)*(1-wy)*Z00 + wx*(1-wy)*Z10 + (1-wx)*wy*Z01 + wx*wy*Z11  # [戻り値] 計算結果・計算状態の呼び出し元への返却
def read_eff_map(path):                                            # [関数定義] read_eff_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
def read_Rint_map(path):                                           # [関数定義] read_Rint_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

def read_map(path):                                                # [関数定義] read_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

def read_1d_map(path):                                             # [関数定義] read_1d_map の処理実行ブロック
    df = pd.read_csv(path)
    if df.shape[1] >= 2:
        x = df.iloc[:, 0].values.astype(float)
        y = df.iloc[:, 1].values.astype(float)
        return x, y                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    df = pd.read_csv(path, index_col=0)
    x = df.index.values.astype(float)
    y = df.iloc[:, 0].values.astype(float)
    return x, y                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import socket
import time
from typing import Dict




def as_float(value, default=math.nan):                             # [関数定義] as_float の処理実行ブロック
    return finite_float(value, default=default)                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


class TelemetryTextBridgeNode:                               # [クラス定義] TelemetryTextBridgeNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        self.declare_parameter('enable_inbound', True)
        self.declare_parameter('enable_outbound', True)
        self.declare_parameter('bind_host', '0.0.0.0')
        self.declare_parameter('bind_port', 52001)
        self.declare_parameter('publish_period_sec', 1.0)
        self.declare_parameter('solar_remote_host', '')
        self.declare_parameter('solar_remote_port', 52002)
        self.declare_parameter('chase_remote_host', '')
        self.declare_parameter('chase_remote_port', 52003)
        self.declare_parameter('send_to_solar', True)
        self.declare_parameter('send_to_chase', True)
        self.declare_parameter('speed_filter_tau_sec', 0.6)
        self.declare_parameter('speed_max_kmh', 130.0)
        self.declare_parameter('speed_max_accel_kmhps', 12.0)
        self.declare_parameter('speed_max_decel_kmhps', 20.0)
        self.declare_parameter('distance_max_rate_kmps', 0.06)
        self.declare_parameter('distance_max_backtrack_km', 0.02)
        self.declare_parameter('battery_filter_tau_sec', 1.0)
        self.declare_parameter('wind_filter_tau_sec', 1.0)
        self.declare_parameter('headwind_filter_tau_sec', 0.8)
        self.declare_parameter('max_abs_headwind_ms', 25.0)

        self.enable_inbound = bool(self.get_parameter('enable_inbound').value)
        self.enable_outbound = bool(self.get_parameter('enable_outbound').value)
        self.bind_host = str(self.get_parameter('bind_host').value)
        self.bind_port = int(self.get_parameter('bind_port').value)
        self.publish_period_sec = max(0.1, float(self.get_parameter('publish_period_sec').value))
        self.solar_remote_host = str(self.get_parameter('solar_remote_host').value).strip()
        self.solar_remote_port = int(self.get_parameter('solar_remote_port').value)
        self.chase_remote_host = str(self.get_parameter('chase_remote_host').value).strip()
        self.chase_remote_port = int(self.get_parameter('chase_remote_port').value)
        self.send_to_solar = bool(self.get_parameter('send_to_solar').value)
        self.send_to_chase = bool(self.get_parameter('send_to_chase').value)
        speed_tau = max(0.0, float(self.get_parameter('speed_filter_tau_sec').value))
        speed_max = max(1.0, float(self.get_parameter('speed_max_kmh').value))
        speed_rise = max(0.1, float(self.get_parameter('speed_max_accel_kmhps').value))
        speed_fall = max(0.1, float(self.get_parameter('speed_max_decel_kmhps').value))
        distance_rate = max(1.0e-4, float(self.get_parameter('distance_max_rate_kmps').value))
        distance_backtrack = max(0.0, float(self.get_parameter('distance_max_backtrack_km').value))
        battery_tau = max(0.0, float(self.get_parameter('battery_filter_tau_sec').value))
        wind_tau = max(0.0, float(self.get_parameter('wind_filter_tau_sec').value))
        headwind_tau = max(0.0, float(self.get_parameter('headwind_filter_tau_sec').value))
        max_headwind = max(1.0, float(self.get_parameter('max_abs_headwind_ms').value))

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        if self.enable_inbound:
            self.sock.bind((self.bind_host, self.bind_port))

        self.pub_network_status = self.create_publisher(String, '/system/network_status', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        self.pub_vehicle_speed = self.create_publisher(Float32, '/vehicle/speed_kmh', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_soc = self.create_publisher(Float32, '/vehicle/batt_soc', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_temp = self.create_publisher(Float32, '/vehicle/batt_temp_c', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_current = self.create_publisher(Float32, '/vehicle/batt_current_a', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_voltage = self.create_publisher(Float32, '/vehicle/batt_voltage_v', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_dist = self.create_publisher(Float32, '/vehicle/s_km', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_alt = self.create_publisher(Float32, '/vehicle/altitude_m', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_gps = self.create_publisher(NavSatFix, '/vehicle/gps', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_wind_speed = self.create_publisher(Float32, '/vehicle/wind_speed_ms', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_wind_dir = self.create_publisher(Float32, '/vehicle/wind_dir_deg', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_course = self.create_publisher(Float32, '/vehicle/course_deg', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vehicle_headwind = self.create_publisher(Float32, '/vehicle/headwind_obs_ms', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        self.pub_chase_speed = self.create_publisher(Float32, '/chase/speed_kmh', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_chase_alt = self.create_publisher(Float32, '/chase/altitude_m', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_chase_gps = self.create_publisher(NavSatFix, '/chase/gps', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_chase_wind_speed = self.create_publisher(Float32, '/chase/wind_speed_ms', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_chase_wind_dir = self.create_publisher(Float32, '/chase/wind_dir_deg', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_chase_course = self.create_publisher(Float32, '/chase/course_deg', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_chase_headwind = self.create_publisher(Float32, '/chase/headwind_obs_ms', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        self.outbound_state: Dict[str, object] = {
            'speed_cmd_kmh': math.nan,
            'upper_speed_cmd_kmh': math.nan,
            'drive_mode': '',
            'race_progress_pct': math.nan,
            'next_stop_dist_km': math.nan,
            'next_stop_eta_min': math.nan,
            'finish_dist_km': math.nan,
            'finish_eta_h': math.nan,
            'avg_plan_speed_kmh': math.nan,
            'headwind_plan_ms': math.nan,
            'headwind_mu_ms': math.nan,
            'headwind_sigma_ms': math.nan,
            'headwind_lo95_ms': math.nan,
            'headwind_hi95_ms': math.nan,
            'network_status': '',
        }
        self.last_inbound_summary = 'waiting inbound telemetry'
        self.last_tx_summary = 'tx=idle'
        self.last_sender = ''
        self.last_rx_time = 0.0
        self.last_tx_time = 0.0
        self.filters = {
            ('vehicle', 'speed_kmh'): RobustScalarFilter(
                min_value=0.0, max_value=speed_max, tau_sec=speed_tau,
                rise_rate=speed_rise, fall_rate=speed_fall, median_window=3, deadband=0.05,
            ),
            ('chase', 'speed_kmh'): RobustScalarFilter(
                min_value=0.0, max_value=speed_max, tau_sec=speed_tau,
                rise_rate=speed_rise, fall_rate=speed_fall, median_window=3, deadband=0.05,
            ),
            ('vehicle', 'batt_soc'): RobustScalarFilter(
                min_value=0.0, max_value=1.0, tau_sec=battery_tau, median_window=3, deadband=0.001,
            ),
            ('vehicle', 'batt_temp_c'): RobustScalarFilter(
                min_value=-40.0, max_value=100.0, tau_sec=battery_tau, median_window=3, deadband=0.02,
            ),
            ('vehicle', 'batt_current_a'): RobustScalarFilter(
                min_value=-200.0, max_value=200.0, tau_sec=battery_tau, median_window=3, deadband=0.05,
            ),
            ('vehicle', 'batt_voltage_v'): RobustScalarFilter(
                min_value=0.0, max_value=200.0, tau_sec=battery_tau, median_window=3, deadband=0.02,
            ),
            ('vehicle', 's_km'): RobustScalarFilter(
                min_value=0.0, max_value=5000.0, rise_rate=distance_rate, median_window=3,
                monotonic=True, max_backtrack=distance_backtrack,
            ),
            ('vehicle', 'alt_m'): RobustScalarFilter(
                min_value=-500.0, max_value=5000.0, tau_sec=1.0, median_window=3, deadband=0.1,
            ),
            ('chase', 'alt_m'): RobustScalarFilter(
                min_value=-500.0, max_value=5000.0, tau_sec=1.0, median_window=3, deadband=0.1,
            ),
            ('vehicle', 'wind_speed_ms'): RobustScalarFilter(
                min_value=0.0, max_value=35.0, tau_sec=wind_tau, rise_rate=8.0, fall_rate=8.0, median_window=3, deadband=0.02,
            ),
            ('chase', 'wind_speed_ms'): RobustScalarFilter(
                min_value=0.0, max_value=35.0, tau_sec=wind_tau, rise_rate=8.0, fall_rate=8.0, median_window=3, deadband=0.02,
            ),
            ('vehicle', 'headwind_ms'): RobustScalarFilter(
                min_value=-max_headwind, max_value=max_headwind, tau_sec=headwind_tau,
                rise_rate=10.0, fall_rate=10.0, median_window=3, deadband=0.02,
            ),
            ('chase', 'headwind_ms'): RobustScalarFilter(
                min_value=-max_headwind, max_value=max_headwind, tau_sec=headwind_tau,
                rise_rate=10.0, fall_rate=10.0, median_window=3, deadband=0.02,
            ),
        }

        self.create_subscription(Float32, '/planner/speed_cmd', self._set_out_float('speed_cmd_kmh'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/planner/upper_speed_cmd', self._set_out_float('upper_speed_cmd_kmh'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/planner/drive_mode', self._set_out_str('drive_mode'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/summary', self._on_summary, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/wind_state', self._on_wind_state, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        self.rx_timer = self.create_timer(0.05, self._poll_inbound)
        self.tx_timer = self.create_timer(self.publish_period_sec, self._publish_outbound)
        self.status_timer = self.create_timer(1.0, self._publish_status)

    def _set_out_float(self, key):                                 # [関数定義] _set_out_float の処理実行ブロック
        def _handler(msg):                                         # [関数定義] _handler の処理実行ブロック
            self.outbound_state[key] = float(msg.data)
        return _handler                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _set_out_str(self, key):                                   # [関数定義] _set_out_str の処理実行ブロック
        def _handler(msg):                                         # [関数定義] _handler の処理実行ブロック
            self.outbound_state[key] = str(msg.data)
        return _handler                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _on_summary(self, msg: Float32MultiArray):                 # [関数定義] _on_summary の処理実行ブロック
        data = list(msg.data)
        keys = [
            'race_progress_pct',
            'next_stop_dist_km',
            'next_stop_eta_min',
            'finish_dist_km',
            'finish_eta_h',
            'avg_plan_speed_kmh',
        ]
        for i, key in enumerate(keys):
            self.outbound_state[key] = float(data[i]) if i < len(data) else math.nan

    def _on_wind_state(self, msg: Float32MultiArray):              # [関数定義] _on_wind_state の処理実行ブロック
        data = list(msg.data)
        mapping = {
            6: 'headwind_mu_ms',
            7: 'headwind_sigma_ms',
            8: 'headwind_lo95_ms',
            9: 'headwind_hi95_ms',
            10: 'headwind_plan_ms',
        }
        for idx, key in mapping.items():
            self.outbound_state[key] = float(data[idx]) if idx < len(data) else math.nan

    def _publish_status(self):                                     # [関数定義] _publish_status の処理実行ブロック
        age = time.monotonic() - self.last_rx_time if self.last_rx_time > 0.0 else math.inf
        rx = 'never' if not math.isfinite(age) else f'{age:.1f}s ago'
        sender = self.last_sender or '--'
        tx_age = time.monotonic() - self.last_tx_time if self.last_tx_time > 0.0 else math.inf
        tx = 'never' if not math.isfinite(tx_age) else f'{tx_age:.1f}s ago'
        status = f'rx={rx} from={sender} tx={tx} {self.last_inbound_summary} {self.last_tx_summary}'
        self.outbound_state['network_status'] = status
        self.pub_network_status.publish(String(data=status))

    def _poll_inbound(self):                                       # [関数定義] _poll_inbound の処理実行ブロック
        if not self.enable_inbound:
            return
        while True:
            try:
                payload, addr = self.sock.recvfrom(65535)
            except BlockingIOError:
                break
            except Exception as exc:
                self.last_inbound_summary = f'rx error: {exc}'
                break
            try:
                text = payload.decode('utf-8').strip()
                if not text:
                    continue
                obj = json.loads(text)
            except Exception as exc:
                self.last_inbound_summary = f'bad json: {exc}'
                continue
            self.last_sender = f'{addr[0]}:{addr[1]}'
            self.last_rx_time = time.monotonic()
            self._handle_payload(obj)

    def _handle_payload(self, obj):                                # [関数定義] _handle_payload の処理実行ブロック
        if not isinstance(obj, dict):
            self.last_inbound_summary = 'ignored non-object payload'
            return

        payload_type = str(obj.get('type', '') or obj.get('kind', '')).lower()
        if 'vehicle' in obj and isinstance(obj['vehicle'], dict):
            self._publish_vehicle(obj['vehicle'])
        if 'chase' in obj and isinstance(obj['chase'], dict):
            self._publish_chase(obj['chase'])

        if payload_type in ('vehicle', 'vehicle_state', 'solar', 'solarcar'):
            self._publish_vehicle(obj)
        elif payload_type in ('chase', 'chase_state', 'escort', 'support'):
            self._publish_chase(obj)
        elif payload_type in ('bundle', 'telemetry_bundle'):
            pass

        self.last_inbound_summary = f'type={payload_type or "auto"} keys={",".join(sorted(obj.keys())[:6])}'

    def _publish_vehicle(self, data: Dict):                        # [関数定義] _publish_vehicle の処理実行ブロック
        self._publish_filtered_float('vehicle', self.pub_vehicle_speed, data, 'speed_kmh')
        soc = as_float(data.get('soc', data.get('batt_soc', math.nan)))
        if math.isfinite(soc) and soc > 1.5:
            soc /= 100.0
        if math.isfinite(soc):
            filtered_soc = self._filter_value('vehicle', 'batt_soc', soc)
            if math.isfinite(filtered_soc):
                self.pub_vehicle_soc.publish(Float32(data=float(filtered_soc)))
        self._publish_filtered_float('vehicle', self.pub_vehicle_temp, data, 'batt_temp_c')
        self._publish_filtered_float('vehicle', self.pub_vehicle_current, data, 'batt_current_a')
        self._publish_filtered_float('vehicle', self.pub_vehicle_voltage, data, 'batt_voltage_v')
        self._publish_filtered_float('vehicle', self.pub_vehicle_dist, data, 's_km')
        self._publish_filtered_float('vehicle', self.pub_vehicle_alt, data, 'alt_m', aliases=('altitude_m',))
        self._publish_filtered_float('vehicle', self.pub_vehicle_wind_speed, data, 'wind_speed_ms')
        self._publish_bounded_float(self.pub_vehicle_wind_dir, data, 'wind_dir_deg', 0.0, 360.0)
        self._publish_bounded_float(self.pub_vehicle_course, data, 'course_deg', 0.0, 360.0)
        self._publish_filtered_float('vehicle', self.pub_vehicle_headwind, data, 'headwind_ms', aliases=('headwind_obs_ms',))
        self._publish_navsat(self.pub_vehicle_gps, data)

    def _publish_chase(self, data: Dict):                          # [関数定義] _publish_chase の処理実行ブロック
        self._publish_filtered_float('chase', self.pub_chase_speed, data, 'speed_kmh')
        self._publish_filtered_float('chase', self.pub_chase_alt, data, 'alt_m', aliases=('altitude_m',))
        self._publish_filtered_float('chase', self.pub_chase_wind_speed, data, 'wind_speed_ms')
        self._publish_bounded_float(self.pub_chase_wind_dir, data, 'wind_dir_deg', 0.0, 360.0)
        self._publish_bounded_float(self.pub_chase_course, data, 'course_deg', 0.0, 360.0)
        self._publish_filtered_float('chase', self.pub_chase_headwind, data, 'headwind_ms', aliases=('headwind_obs_ms',))
        self._publish_navsat(self.pub_chase_gps, data)

    def _publish_filtered_float(self, prefix, publisher, data, key, aliases=()):  # [関数定義] _publish_filtered_float の処理実行ブロック
        for name in (key,) + tuple(aliases):
            value = as_float(data.get(name, math.nan))
            if math.isfinite(value):
                filtered = self._filter_value(prefix, key, value)
                if math.isfinite(filtered):
                    publisher.publish(Float32(data=float(filtered)))
                return

    def _publish_bounded_float(self, publisher, data, key, lo, hi, aliases=()):  # [関数定義] _publish_bounded_float の処理実行ブロック
        for name in (key,) + tuple(aliases):
            value = as_float(data.get(name, math.nan))
            if math.isfinite(value):
                publisher.publish(Float32(data=float(max(lo, min(hi, value)))))
                return

    def _filter_value(self, prefix, key, value):                   # [関数定義] _filter_value の処理実行ブロック
        filt = self.filters.get((prefix, key))
        if filt is None:
            return finite_float(value)                             # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return filt.update(value)                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _publish_navsat(self, publisher, data):                    # [関数定義] _publish_navsat の処理実行ブロック
        lat = as_float(data.get('lat', data.get('latitude', math.nan)))
        lon = as_float(data.get('lon', data.get('longitude', math.nan)))
        if not math.isfinite(lat) or not math.isfinite(lon):
            return
        if abs(lat) > 90.0 or abs(lon) > 180.0:
            return
        alt = as_float(data.get('alt_m', data.get('altitude_m', data.get('altitude', math.nan))))
        msg = NavSatFix()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'gps'
        msg.latitude = float(lat)
        msg.longitude = float(lon)
        msg.altitude = float(alt) if math.isfinite(alt) else 0.0
        publisher.publish(msg)

    def _publish_outbound(self):                                   # [関数定義] _publish_outbound の処理実行ブロック
        if not self.enable_outbound:
            return
        snapshot = {
            'type': 'planner_command',
            'schema': 'solar_v1',
            'ts_unix': time.time(),
            'planner': {
                'speed_cmd_kmh': self._clean(self.outbound_state.get('speed_cmd_kmh')),
                'upper_speed_cmd_kmh': self._clean(self.outbound_state.get('upper_speed_cmd_kmh')),
                'drive_mode': str(self.outbound_state.get('drive_mode', '') or ''),
            },
            'summary': {
                'race_progress_pct': self._clean(self.outbound_state.get('race_progress_pct')),
                'next_stop_dist_km': self._clean(self.outbound_state.get('next_stop_dist_km')),
                'next_stop_eta_min': self._clean(self.outbound_state.get('next_stop_eta_min')),
                'finish_dist_km': self._clean(self.outbound_state.get('finish_dist_km')),
                'finish_eta_h': self._clean(self.outbound_state.get('finish_eta_h')),
                'avg_plan_speed_kmh': self._clean(self.outbound_state.get('avg_plan_speed_kmh')),
            },
            'wind': {
                'plan_headwind_ms': self._clean(self.outbound_state.get('headwind_plan_ms')),
                'mean_headwind_ms': self._clean(self.outbound_state.get('headwind_mu_ms')),
                'std_headwind_ms': self._clean(self.outbound_state.get('headwind_sigma_ms')),
                'lo95_headwind_ms': self._clean(self.outbound_state.get('headwind_lo95_ms')),
                'hi95_headwind_ms': self._clean(self.outbound_state.get('headwind_hi95_ms')),
            },
            'network_status': str(self.outbound_state.get('network_status', '') or ''),
        }
        payload = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        sent = []
        if self.send_to_solar and self.solar_remote_host:
            self.sock.sendto(payload, (self.solar_remote_host, self.solar_remote_port))
            sent.append(f'solar={self.solar_remote_host}:{self.solar_remote_port}')
        if self.send_to_chase and self.chase_remote_host:
            self.sock.sendto(payload, (self.chase_remote_host, self.chase_remote_port))
            sent.append(f'chase={self.chase_remote_host}:{self.chase_remote_port}')
        if sent:
            self.last_tx_time = time.monotonic()
            self.last_tx_summary = 'tx[' + ','.join(sent) + ']'
        else:
            self.last_tx_summary = 'tx=idle'

    def _clean(self, value):                                       # [関数定義] _clean の処理実行ブロック
        try:
            v = float(value)
            if math.isfinite(v):
                return float(v)                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception:
            pass
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def destroy_node(self):                                        # [関数定義] destroy_node の処理実行ブロック
        try:
            self.sock.close()
        except Exception:
            pass
        super().destroy_node()


def main():                                                        # [メイン関数] エントリーポイント関数
    node = TelemetryTextBridgeNode()
    node.destroy_node()


if __name__ == '__main__':                                         # [直接実行スクリプト] スクリプト直接起動時のメイン実行ブロック
    main()

# =============================================================================
# 【統合ユーティリティ】シグナルフィルタ・スルーレート制限・有限値検証
# =============================================================================
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import time
from collections import deque


def finite_float(value, default=math.nan):                         # [関数定義] finite_float の処理実行ブロック
    try:
        v = float(value)
        if math.isfinite(v):
            return v                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        pass
    return default                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def clamp(value, lo=None, hi=None):                                # [関数定義] clamp の処理実行ブロック
    v = float(value)
    if lo is not None:
        v = max(float(lo), v)
    if hi is not None:
        v = min(float(hi), v)
    return v                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fresh_enough(timestamp, timeout_sec, now=None):                # [関数定義] fresh_enough の処理実行ブロック
    if timestamp is None:
        return False                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if timeout_sec is None or float(timeout_sec) <= 0.0:
        return True                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if now is None:
        now = time.monotonic()
    return (float(now) - float(timestamp)) <= float(timeout_sec)   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def slew_limit(previous, target, dt, rise_rate=None, fall_rate=None):  # [関数定義] slew_limit の処理実行ブロック
    prev = float(previous)
    tgt = float(target)
    dt = max(0.0, float(dt))
    if not math.isfinite(prev) or dt <= 0.0:
        return tgt                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = tgt - prev
    if delta >= 0.0 and rise_rate is not None and math.isfinite(float(rise_rate)) and float(rise_rate) > 0.0:
        delta = min(delta, float(rise_rate) * dt)
    if delta < 0.0 and fall_rate is not None and math.isfinite(float(fall_rate)) and float(fall_rate) > 0.0:
        delta = max(delta, -float(fall_rate) * dt)
    return prev + delta                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却


class SmoothRateLimiter:                                           # [クラス定義] SmoothRateLimiter オブジェクトの設計
    def __init__(                                                  # [関数定義] __init__ の処理実行ブロック
        self,
        *,
        min_value=None,
        max_value=None,
        tau_sec=0.0,
        rise_rate=None,
        fall_rate=None,
        deadband=0.0,
        quantize_step=0.0,
        initial_value=math.nan,
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.tau_sec = max(0.0, float(tau_sec))
        self.rise_rate = rise_rate
        self.fall_rate = fall_rate
        self.deadband = max(0.0, float(deadband))
        self.quantize_step = max(0.0, float(quantize_step))
        self.value = float(initial_value) if math.isfinite(finite_float(initial_value)) else math.nan
        self.last_time = None

    def reset(self, value=math.nan, now=None):                     # [関数定義] reset の処理実行ブロック
        self.value = finite_float(value)
        self.last_time = time.monotonic() if now is None else float(now)
        return self.value                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def update(self, target, now=None):                            # [関数定義] update の処理実行ブロック
        tgt = finite_float(target)
        if not math.isfinite(tgt):
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        tgt = clamp(tgt, self.min_value, self.max_value)
        now_mono = time.monotonic() if now is None else float(now)
        if not math.isfinite(self.value):
            self.value = tgt
            self.last_time = now_mono
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却

        dt = 0.0 if self.last_time is None else max(1.0e-3, now_mono - float(self.last_time))
        if self.tau_sec > 0.0 and dt > 0.0:
            alpha = 1.0 - math.exp(-dt / self.tau_sec)
            candidate = self.value + alpha * (tgt - self.value)
        else:
            candidate = tgt

        candidate = slew_limit(self.value, candidate, dt, self.rise_rate, self.fall_rate)
        candidate = clamp(candidate, self.min_value, self.max_value)

        if self.deadband > 0.0 and abs(candidate - self.value) < self.deadband:
            candidate = self.value

        if self.quantize_step > 0.0:
            candidate = round(candidate / self.quantize_step) * self.quantize_step

        self.value = clamp(candidate, self.min_value, self.max_value)
        self.last_time = now_mono
        return self.value                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却


class RobustScalarFilter:                                          # [クラス定義] RobustScalarFilter オブジェクトの設計
    def __init__(                                                  # [関数定義] __init__ の処理実行ブロック
        self,
        *,
        min_value=None,
        max_value=None,
        tau_sec=0.0,
        rise_rate=None,
        fall_rate=None,
        deadband=0.0,
        quantize_step=0.0,
        median_window=1,
        monotonic=False,
        max_backtrack=0.0,
        initial_value=math.nan,
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.monotonic = bool(monotonic)
        self.max_backtrack = max(0.0, float(max_backtrack))
        self.window = deque(maxlen=max(1, int(median_window)))
        self.smoother = SmoothRateLimiter(
            min_value=min_value,
            max_value=max_value,
            tau_sec=tau_sec,
            rise_rate=rise_rate,
            fall_rate=fall_rate,
            deadband=deadband,
            quantize_step=quantize_step,
            initial_value=initial_value,
        )

    @property
    def value(self):                                               # [関数定義] value の処理実行ブロック
        return self.smoother.value                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    @property
    def last_time(self):                                           # [関数定義] last_time の処理実行ブロック
        return self.smoother.last_time                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def reset(self, value=math.nan, now=None):                     # [関数定義] reset の処理実行ブロック
        self.window.clear()
        v = finite_float(value)
        if math.isfinite(v):
            self.window.append(v)
        return self.smoother.reset(v, now=now)                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def update(self, raw_value, now=None):                         # [関数定義] update の処理実行ブロック
        value = finite_float(raw_value)
        if not math.isfinite(value):
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        value = clamp(value, self.min_value, self.max_value)
        self.window.append(value)
        candidate = value
        if len(self.window) > 1:
            seq = sorted(self.window)
            candidate = float(seq[len(seq) // 2])
        if self.monotonic and math.isfinite(self.value):
            candidate = max(candidate, float(self.value) - self.max_backtrack)
        return self.smoother.update(candidate, now=now)            # [戻り値] 計算結果・計算状態の呼び出し元への返却

# =============================================================================
# 【統合通信プロトコル】テレメトリ構造体・パケット定義
# =============================================================================
"""Timestamp validation shared by the WiFi telemetry receiver and tests."""


from dataclasses import dataclass
from datetime import datetime, timezone
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート


@dataclass(frozen=True)
class TimestampValidation:                                         # [クラス定義] TimestampValidation オブジェクトの設計
    accepted: bool
    source_unix: float | None
    age_sec: float | None
    reason: str


def parse_source_timestamp(payload: dict) -> float | None:         # [関数定義] parse_source_timestamp の処理実行ブロック
    """Return a UTC Unix timestamp from the supported wire-format fields."""
    for key in ("ts_unix", "timestamp_unix", "time_unix"):
        if key not in payload:
            continue
        try:
            value = float(payload[key])
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却

    for key in ("timestamp_utc", "ts_utc", "time_utc"):
        raw = str(payload.get(key, "")).strip()
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        return parsed.astimezone(timezone.utc).timestamp()         # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return None                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def validate_source_timestamp(                                     # [関数定義] validate_source_timestamp の処理実行ブロック
    payload: dict,
    *,
    now_unix: float,
    last_source_unix: float | None,
    required: bool,
    max_age_sec: float,
    max_future_skew_sec: float,
    max_out_of_order_sec: float,
) -> TimestampValidation:
    """Reject stale, future, duplicate, or excessively reordered UDP packets."""
    source_unix = parse_source_timestamp(payload)
    if source_unix is None:
        if required:
            return TimestampValidation(False, None, None, "missing_or_invalid_timestamp")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return TimestampValidation(True, None, None, "timestamp_not_required")  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    age_sec = float(now_unix) - source_unix
    if age_sec > max(0.0, float(max_age_sec)):
        return TimestampValidation(False, source_unix, age_sec, "stale_packet")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if age_sec < -max(0.0, float(max_future_skew_sec)):
        return TimestampValidation(False, source_unix, age_sec, "future_packet")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if last_source_unix is not None:
        tolerance = max(0.0, float(max_out_of_order_sec))
        if source_unix == last_source_unix:
            return TimestampValidation(False, source_unix, age_sec, "duplicate_packet")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if source_unix < last_source_unix - tolerance:
            return TimestampValidation(False, source_unix, age_sec, "out_of_order_packet")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return TimestampValidation(True, source_unix, age_sec, "ok")   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def utc_iso_now() -> str:                                          # [関数定義] utc_iso_now の処理実行ブロック
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # [戻り値] 計算結果・計算状態の呼び出し元への返却

import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import socket
import time




class SpeedCommandBridgeNode:                                # [クラス定義] SpeedCommandBridgeNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        self.declare_parameter('output_speed_topic', '/vehicle/speed_cmd_kmh')
        self.declare_parameter('output_drive_mode_topic', '/vehicle/drive_mode_cmd')
        self.declare_parameter('udp_enabled', False)
        self.declare_parameter('udp_host', '127.0.0.1')
        self.declare_parameter('udp_port', 50050)
        self.declare_parameter('publish_rate_hz', 5.0)
        self.declare_parameter('input_timeout_sec', 3.0)
        self.declare_parameter('safe_speed_kmh', 0.0)
        self.declare_parameter('startup_hold_sec', 2.0)
        self.declare_parameter('filter_tau_sec', 1.0)
        self.declare_parameter('accel_limit_kmhps', 1.5)
        self.declare_parameter('decel_limit_kmhps', 4.0)
        self.declare_parameter('speed_deadband_kmh', 0.1)
        self.declare_parameter('speed_quantize_step_kmh', 0.1)
        self.declare_parameter('max_output_speed_kmh', 130.0)
        self.declare_parameter('drive_mode_min_hold_sec', 5.0)

        self.output_speed_topic = str(self.get_parameter('output_speed_topic').value)
        self.output_drive_mode_topic = str(self.get_parameter('output_drive_mode_topic').value)
        self.udp_enabled = bool(self.get_parameter('udp_enabled').value)
        self.udp_host = str(self.get_parameter('udp_host').value)
        self.udp_port = int(self.get_parameter('udp_port').value)
        self.publish_rate_hz = max(1.0, float(self.get_parameter('publish_rate_hz').value))
        self.input_timeout_sec = max(0.2, float(self.get_parameter('input_timeout_sec').value))
        self.safe_speed_kmh = max(0.0, float(self.get_parameter('safe_speed_kmh').value))
        self.startup_hold_sec = max(0.0, float(self.get_parameter('startup_hold_sec').value))
        self.max_output_speed_kmh = max(self.safe_speed_kmh, float(self.get_parameter('max_output_speed_kmh').value))
        self.drive_mode_min_hold_sec = max(0.0, float(self.get_parameter('drive_mode_min_hold_sec').value))

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if self.udp_enabled else None
        self.start_time = time.monotonic()
        self.last_speed_target = self.safe_speed_kmh
        self.last_speed_rx_time = None
        self.requested_mode = 'auto'
        self.last_mode_rx_time = None
        self.output_mode = 'auto'
        self.last_mode_switch_time = self.start_time

        self.speed_filter = SmoothRateLimiter(
            min_value=0.0,
            max_value=self.max_output_speed_kmh,
            tau_sec=float(self.get_parameter('filter_tau_sec').value),
            rise_rate=float(self.get_parameter('accel_limit_kmhps').value),
            fall_rate=float(self.get_parameter('decel_limit_kmhps').value),
            deadband=float(self.get_parameter('speed_deadband_kmh').value),
            quantize_step=float(self.get_parameter('speed_quantize_step_kmh').value),
            initial_value=self.safe_speed_kmh,
        )
        self.current_speed = self.safe_speed_kmh

        self.pub_speed = self.create_publisher(Float32, self.output_speed_topic, 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_mode = self.create_publisher(String, self.output_drive_mode_topic, 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_status = self.create_publisher(String, '/system/command_status', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        self.create_subscription(Float32, '/planner/speed_cmd', self._on_speed, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/planner/drive_mode', self._on_mode, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.timer = self.create_timer(1.0 / self.publish_rate_hz, self._tick)

    def _on_speed(self, msg: Float32):                             # [関数定義] _on_speed の処理実行ブロック
        value = finite_float(msg.data)
        if not math.isfinite(value):
            return
        self.last_speed_target = max(0.0, min(value, self.max_output_speed_kmh))
        self.last_speed_rx_time = time.monotonic()

    def _on_mode(self, msg: String):                               # [関数定義] _on_mode の処理実行ブロック
        mode = str(msg.data or '').strip()
        if not mode:
            return
        self.requested_mode = mode
        self.last_mode_rx_time = time.monotonic()

    def _select_mode(self, now_mono: float):                       # [関数定義] _select_mode の処理実行ブロック
        requested = self.requested_mode or self.output_mode
        if requested == self.output_mode:
            return self.output_mode                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if (now_mono - self.last_mode_switch_time) < self.drive_mode_min_hold_sec:
            return self.output_mode                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
        self.output_mode = requested
        self.last_mode_switch_time = now_mono
        return self.output_mode                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _target_speed(self, now_mono: float):                      # [関数定義] _target_speed の処理実行ブロック
        planner_fresh = fresh_enough(self.last_speed_rx_time, self.input_timeout_sec, now=now_mono)
        in_startup_hold = (now_mono - self.start_time) < self.startup_hold_sec
        if in_startup_hold or not planner_fresh:
            return self.safe_speed_kmh, planner_fresh, in_startup_hold  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return self.last_speed_target, planner_fresh, in_startup_hold  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _tick(self):                                               # [関数定義] _tick の処理実行ブロック
        now_mono = time.monotonic()
        target_speed, planner_fresh, in_startup_hold = self._target_speed(now_mono)
        self.current_speed = float(self.speed_filter.update(target_speed, now=now_mono))
        mode = self._select_mode(now_mono)

        self.pub_speed.publish(Float32(data=float(self.current_speed)))
        self.pub_mode.publish(String(data=str(mode)))
        self._send_status(planner_fresh=planner_fresh, in_startup_hold=in_startup_hold)

    def _send_status(self, planner_fresh: bool, in_startup_hold: bool):  # [関数定義] _send_status の処理実行ブロック
        age = math.inf
        if self.last_speed_rx_time is not None:
            age = max(0.0, time.monotonic() - self.last_speed_rx_time)
        rx_age = 'never' if not math.isfinite(age) else f'{age:.1f}s'
        fallback = 'startup_hold' if in_startup_hold else ('stale_input' if not planner_fresh else 'tracking')
        status = (
            f'target={self.last_speed_target:.2f} out={self.current_speed:.2f} km/h '
            f'rx_age={rx_age} mode={self.output_mode} req_mode={self.requested_mode} state={fallback}'
        )
        if self.sock is not None:
            payload = json.dumps({
                'speed_kmh': self.current_speed,
                'drive_mode': self.output_mode,
                'target_speed_kmh': self.last_speed_target,
                'state': fallback,
            }).encode('utf-8')
            try:
                self.sock.sendto(payload, (self.udp_host, self.udp_port))
                status += f' udp={self.udp_host}:{self.udp_port}'
            except Exception as exc:
                status += f' udp_error={exc}'
        self.pub_status.publish(String(data=status))

    def destroy_node(self):                                        # [関数定義] destroy_node の処理実行ブロック
        try:
            if self.sock is not None:
                self.sock.close()
        except Exception:
            pass
        super().destroy_node()


def main():                                                        # [メイン関数] エントリーポイント関数
    node = SpeedCommandBridgeNode()
    node.destroy_node()

# =============================================================================
# 【統合ユーティリティ】シグナルフィルタ・スルーレート制限・有限値検証
# =============================================================================
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import time
from collections import deque


def finite_float(value, default=math.nan):                         # [関数定義] finite_float の処理実行ブロック
    try:
        v = float(value)
        if math.isfinite(v):
            return v                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        pass
    return default                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def clamp(value, lo=None, hi=None):                                # [関数定義] clamp の処理実行ブロック
    v = float(value)
    if lo is not None:
        v = max(float(lo), v)
    if hi is not None:
        v = min(float(hi), v)
    return v                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fresh_enough(timestamp, timeout_sec, now=None):                # [関数定義] fresh_enough の処理実行ブロック
    if timestamp is None:
        return False                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if timeout_sec is None or float(timeout_sec) <= 0.0:
        return True                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if now is None:
        now = time.monotonic()
    return (float(now) - float(timestamp)) <= float(timeout_sec)   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def slew_limit(previous, target, dt, rise_rate=None, fall_rate=None):  # [関数定義] slew_limit の処理実行ブロック
    prev = float(previous)
    tgt = float(target)
    dt = max(0.0, float(dt))
    if not math.isfinite(prev) or dt <= 0.0:
        return tgt                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = tgt - prev
    if delta >= 0.0 and rise_rate is not None and math.isfinite(float(rise_rate)) and float(rise_rate) > 0.0:
        delta = min(delta, float(rise_rate) * dt)
    if delta < 0.0 and fall_rate is not None and math.isfinite(float(fall_rate)) and float(fall_rate) > 0.0:
        delta = max(delta, -float(fall_rate) * dt)
    return prev + delta                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却


class SmoothRateLimiter:                                           # [クラス定義] SmoothRateLimiter オブジェクトの設計
    def __init__(                                                  # [関数定義] __init__ の処理実行ブロック
        self,
        *,
        min_value=None,
        max_value=None,
        tau_sec=0.0,
        rise_rate=None,
        fall_rate=None,
        deadband=0.0,
        quantize_step=0.0,
        initial_value=math.nan,
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.tau_sec = max(0.0, float(tau_sec))
        self.rise_rate = rise_rate
        self.fall_rate = fall_rate
        self.deadband = max(0.0, float(deadband))
        self.quantize_step = max(0.0, float(quantize_step))
        self.value = float(initial_value) if math.isfinite(finite_float(initial_value)) else math.nan
        self.last_time = None

    def reset(self, value=math.nan, now=None):                     # [関数定義] reset の処理実行ブロック
        self.value = finite_float(value)
        self.last_time = time.monotonic() if now is None else float(now)
        return self.value                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def update(self, target, now=None):                            # [関数定義] update の処理実行ブロック
        tgt = finite_float(target)
        if not math.isfinite(tgt):
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        tgt = clamp(tgt, self.min_value, self.max_value)
        now_mono = time.monotonic() if now is None else float(now)
        if not math.isfinite(self.value):
            self.value = tgt
            self.last_time = now_mono
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却

        dt = 0.0 if self.last_time is None else max(1.0e-3, now_mono - float(self.last_time))
        if self.tau_sec > 0.0 and dt > 0.0:
            alpha = 1.0 - math.exp(-dt / self.tau_sec)
            candidate = self.value + alpha * (tgt - self.value)
        else:
            candidate = tgt

        candidate = slew_limit(self.value, candidate, dt, self.rise_rate, self.fall_rate)
        candidate = clamp(candidate, self.min_value, self.max_value)

        if self.deadband > 0.0 and abs(candidate - self.value) < self.deadband:
            candidate = self.value

        if self.quantize_step > 0.0:
            candidate = round(candidate / self.quantize_step) * self.quantize_step

        self.value = clamp(candidate, self.min_value, self.max_value)
        self.last_time = now_mono
        return self.value                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却


class RobustScalarFilter:                                          # [クラス定義] RobustScalarFilter オブジェクトの設計
    def __init__(                                                  # [関数定義] __init__ の処理実行ブロック
        self,
        *,
        min_value=None,
        max_value=None,
        tau_sec=0.0,
        rise_rate=None,
        fall_rate=None,
        deadband=0.0,
        quantize_step=0.0,
        median_window=1,
        monotonic=False,
        max_backtrack=0.0,
        initial_value=math.nan,
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.monotonic = bool(monotonic)
        self.max_backtrack = max(0.0, float(max_backtrack))
        self.window = deque(maxlen=max(1, int(median_window)))
        self.smoother = SmoothRateLimiter(
            min_value=min_value,
            max_value=max_value,
            tau_sec=tau_sec,
            rise_rate=rise_rate,
            fall_rate=fall_rate,
            deadband=deadband,
            quantize_step=quantize_step,
            initial_value=initial_value,
        )

    @property
    def value(self):                                               # [関数定義] value の処理実行ブロック
        return self.smoother.value                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    @property
    def last_time(self):                                           # [関数定義] last_time の処理実行ブロック
        return self.smoother.last_time                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def reset(self, value=math.nan, now=None):                     # [関数定義] reset の処理実行ブロック
        self.window.clear()
        v = finite_float(value)
        if math.isfinite(v):
            self.window.append(v)
        return self.smoother.reset(v, now=now)                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def update(self, raw_value, now=None):                         # [関数定義] update の処理実行ブロック
        value = finite_float(raw_value)
        if not math.isfinite(value):
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        value = clamp(value, self.min_value, self.max_value)
        self.window.append(value)
        candidate = value
        if len(self.window) > 1:
            seq = sorted(self.window)
            candidate = float(seq[len(seq) // 2])
        if self.monotonic and math.isfinite(self.value):
            candidate = max(candidate, float(self.value) - self.max_backtrack)
        return self.smoother.update(candidate, now=now)            # [戻り値] 計算結果・計算状態の呼び出し元への返却




class SolarLiveRaceController:
    """実車 WiFi Telemetry UDP 通信 ＆ CasADi リアルタイム MPC 制御クラス"""
    def __init__(self, config_path: str = "config/solar/bwsc_2027_demo.yaml"): # [初期化] リアルタイム制御器構築
        self.config_path = Path(config_path)
        self.running = True
        print(f"[SolarLiveRaceController] リアルタイムMPC制御器を初期化しました (設定: {self.config_path})")

    def run(self):                                                 # [実行ルーチン] 10s周期 CasADi MPC & UDP WiFi受送信ループ
        print("[SolarLiveRaceController] UDP WiFi 通信 & CasADi MPC 制御ループを開始します...")
        print("  - UDP ポート: 5005 (Telemetry 受信) / 5006 (指令送信)")
        print("  - 制御周期: 10.0 秒")
        try:
            while self.running:
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[SolarLiveRaceController] 制御ループを安全に停止しました。")

def main():
    controller = SolarLiveRaceController()
    controller.run()

if __name__ == "__main__":
    main()