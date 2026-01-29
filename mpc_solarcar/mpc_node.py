# -*- coding: utf-8 -*-
import math
import os
import time
from collections import deque
from datetime import datetime, timezone, timedelta

import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter

import yaml
import pandas as pd
import numpy as np

from std_msgs.msg import Bool, Float32, Float32MultiArray, String
from nav_msgs.msg import Path
from geometry_msgs.msg import PoseStamped

from scipy.optimize import minimize

from .model import SolarCarModel, Params
from .path_utils import resolve_path
from .route_utils import interpolate_profile
from .schedule_utils import DriveSchedule
from .estimator import BatteryMHE, MheInput, MheMeas


class MPCNode(Node):
    """
    MPC node with two modes:
      - Default: solarcar MPC (forecast-driven)
      - Passo mode: fuel-minimizing advisory MPC
    """

    def __init__(self):
        super().__init__('mpc_node')
        self.declare_parameter('passo_mode', False)
        self.passo_mode = bool(self.get_parameter('passo_mode').value)
        if self.passo_mode:
            self._init_passo()
        else:
            self._init_solar()

    # -------------------- common helpers --------------------
    def _load_stops(self, stop_yaml: str):
        self.stops = []
        try:
            with open(stop_yaml, 'r', encoding='utf-8') as f:
                y = yaml.safe_load(f) or {}
                self.stops = y.get('stops', [])
                self.get_logger().info(f'Loaded {len(self.stops)} stop points from {stop_yaml}')
        except Exception:
            self.get_logger().info('No stop_points.yaml provided. Running without dwell constraints.')

    def _load_forecast_file(self, path: str):
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
                self.get_logger().warn("forecast 'time' column could not be parsed; falling back to index bins.")
        else:
            self.get_logger().warn("forecast CSV has no 'time' column; falling back to index bins.")

    def _apply_params_yaml(self, path: str):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as exc:
            self.get_logger().warn(f'params_yaml load failed: {exc}')
            return
        model_cfg = cfg.get('model', cfg) if isinstance(cfg, dict) else {}
        if isinstance(model_cfg, dict):
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
                    if not ('gear_ratio' in model_cfg):
                        self.model.p.gear_ratio = 1.0
                    if not ('gear_eta' in model_cfg):
                        self.model.p.gear_eta = 1.0
        mpc_cfg = cfg.get('mpc', {})
        if isinstance(mpc_cfg, dict):
            params = []
            for key, val in mpc_cfg.items():
                params.append(Parameter(key, value=val))
            if params:
                self.set_parameters(params)

    def _maybe_reload_forecast(self):
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
                self.get_logger().info('Forecast CSV reloaded.')
            except Exception as exc:
                self.get_logger().warn(f'Forecast reload failed: {exc}')

    def _on_s_km_solar(self, msg: Float32):
        try:
            self.s_meas = float(msg.data)
            self.s_meas_time = self.get_clock().now().nanoseconds / 1e9
        except Exception:
            pass

    def _on_speed_solar(self, msg: Float32):
        try:
            self.v_now = float(msg.data)
        except Exception:
            pass

    def _on_soc_solar(self, msg: Float32):
        try:
            self.solar_soc_meas = float(msg.data)
        except Exception:
            pass

    def _on_tb_solar(self, msg: Float32):
        try:
            self.solar_tb_meas = float(msg.data)
        except Exception:
            pass

    def _on_i_solar(self, msg: Float32):
        try:
            self.solar_i_meas = float(msg.data)
        except Exception:
            pass

    def _on_v_solar(self, msg: Float32):
        try:
            self.solar_v_meas = float(msg.data)
        except Exception:
            pass

    # -------------------- solarcar mode --------------------
    def _init_solar(self):
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
        self.declare_parameter('soc_finish_target', -1.0)
        self.declare_parameter('soc_finish_tol', 0.02)
        self.declare_parameter('w_soc_progress', 1.0e5)
        self.declare_parameter('w_soc_terminal', 1.0e5)
        self.declare_parameter('race_km', 3035.5)
        self.declare_parameter('upper_mode', 'time')  # time|distance
        self.declare_parameter('upper_ds_km', 20.0)
        self.declare_parameter('upper_horizon_km', 1500.0)
        self.declare_parameter('upper_max_steps', 200)
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

        fcsv = resolve_path(self.get_parameter('forecast_csv').value, 'inputs')
        maps_dir = resolve_path(self.get_parameter('maps_dir').value, 'maps')
        self.dt = float(self.get_parameter('dt').value)
        self.Np = int(self.get_parameter('horizon_steps').value)

        # Load forecast
        self.forecast_path = fcsv
        self.forecast_reload_sec = float(self.get_parameter('forecast_reload_sec').value)
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
                self.get_logger().warn(f'Failed to load route_profile_csv: {exc}')

        self.speed_profile = None
        speed_profile_csv = self.get_parameter('speed_profile_csv').value
        if speed_profile_csv:
            try:
                speed_profile_csv = resolve_path(speed_profile_csv, 'inputs')
                self.speed_profile = pd.read_csv(speed_profile_csv)
            except Exception as exc:
                self.get_logger().warn(f'Failed to load speed_profile_csv: {exc}')

        # Optional driving schedule
        self.drive_schedule = None
        drive_schedule_yaml = self.get_parameter('drive_schedule_yaml').value
        if drive_schedule_yaml:
            drive_schedule_yaml = resolve_path(drive_schedule_yaml, 'inputs')
            self.drive_schedule = DriveSchedule.from_yaml(drive_schedule_yaml)
            if self.drive_schedule is None:
                self.get_logger().warn('drive_schedule_yaml could not be loaded.')

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
        params_yaml = self.get_parameter('params_yaml').value
        if params_yaml:
            params_yaml = resolve_path(params_yaml, 'inputs')
            self._apply_params_yaml(params_yaml)
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
        self.upper_ctrl_km = float(self.get_parameter('upper_ctrl_km').value)
        self.upper_vmin_kmh = float(self.get_parameter('upper_vmin_kmh').value)
        self.upper_replan_km = float(self.get_parameter('upper_replan_km').value)
        self.upper_replan_sec = float(self.get_parameter('upper_replan_sec').value)
        self.upper_max_iter = int(self.get_parameter('upper_max_iter').value)
        self.upper_day_end_soc_min = float(self.get_parameter('upper_day_end_soc_min').value)

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

        # Hierarchical MPC settings
        self.hierarchical = bool(self.get_parameter('hierarchical').value)
        self.lower_dt = float(self.get_parameter('lower_dt').value)
        self.lower_N = int(self.get_parameter('lower_horizon_steps').value)
        self.lower_rate_hz = float(self.get_parameter('lower_rate_hz').value)
        self.w_track = float(self.get_parameter('w_track').value)
        self.w_throttle = float(self.get_parameter('w_throttle').value)
        self.throttle_rate_limit = float(self.get_parameter('throttle_rate_limit').value)
        self._warned_lower_rate = False

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
                self.get_logger().warn('forecast_start_time_utc parse failed; using node start time.')
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
        self.pub_speed = self.create_publisher(Float32, '/planner/speed_cmd', 10)
        self.pub_upper_speed = self.create_publisher(Float32, '/planner/upper_speed_cmd', 10)
        self.pub_throttle = self.create_publisher(Float32, '/planner/throttle_cmd_pct', 10)
        self.pub_drive_mode = self.create_publisher(String, '/planner/drive_mode', 10)
        self.pub_path = self.create_publisher(Path, '/planner/trajectory', 10)
        self.pub_plan = self.create_publisher(Float32MultiArray, '/planner/upper_plan', 10)
        self.pub_lower_plan = self.create_publisher(Float32MultiArray, '/planner/lower_plan', 10)
        self.pub_env = self.create_publisher(Float32MultiArray, '/planner/env', 10)
        self.pub_metrics = self.create_publisher(Float32MultiArray, '/planner/metrics', 10)
        self.pub_status = self.create_publisher(Float32MultiArray, '/planner/status', 10)

        # Subs (optional measurements)
        self.create_subscription(Float32, '/vehicle/s_km', self._on_s_km_solar, 10)
        self.create_subscription(Float32, '/vehicle/speed_kmh', self._on_speed_solar, 10)
        self.create_subscription(Float32, '/vehicle/batt_soc', self._on_soc_solar, 10)
        self.create_subscription(Float32, '/vehicle/batt_temp_c', self._on_tb_solar, 10)
        self.create_subscription(Float32, '/vehicle/batt_current_a', self._on_i_solar, 10)
        self.create_subscription(Float32, '/vehicle/batt_voltage_v', self._on_v_solar, 10)

        # Timer @1Hz (upper layer)
        self.timer = self.create_timer(1.0, self._step_solar)
        # Lower layer timer
        if self.hierarchical and self.lower_rate_hz > 0.0:
            expected_dt = 1.0 / self.lower_rate_hz
            if abs(expected_dt - self.lower_dt) > 1.0e-3 and not self._warned_lower_rate:
                self.get_logger().warn('lower_dt and lower_rate_hz mismatch; using lower_dt for prediction.')
                self._warned_lower_rate = True
            self.timer_lower = self.create_timer(1.0 / self.lower_rate_hz, self._step_lower)
        else:
            self.timer_lower = None
        self.get_logger().info('MPCNode started (solarcar mode).')

    def _current_bin_index(self) -> int:
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
                    self.get_logger().warn('Forecast time out of range; switching to relative indexing.')
                    self._forecast_warned_out_of_range = True
                mode = 'relative'
            else:
                idx = int(np.searchsorted(t_series, np.datetime64(now)) - 1)
                return int(np.clip(idx, 0, len(self.df) - 1))

        if mode in ('relative', 'loop') or not has_time:
            elapsed = (now - self.forecast_start_time).total_seconds()
            elapsed = max(0.0, elapsed)
            idx = int(elapsed / max(self.dt, 1.0e-3))
            if len(self.df) == 0:
                return 0
            if mode == 'loop':
                return int(idx % len(self.df))
            return int(np.clip(idx, 0, len(self.df) - 1))

        return int(np.clip(self.k, 0, len(self.df) - 1))

    def _horizon_data(self, k0: int):
        N = len(self.df)
        data = []
        has_time = ('time' in self.df.columns) and (not self.df['time'].isna().all())
        mode = str(self.forecast_time_mode).lower()
        if mode == 'auto':
            mode = 'absolute' if has_time else 'relative'
        if N <= 0:
            return data
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
            return data

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
        return data

    def _forecast_at_time(self, t_utc: datetime, drive: bool = True) -> dict:
        if len(self.df) == 0:
            return dict(G_poa=0.0, Tcell_C=40.0, Tamb_C=30.0, headwind_ms=0.0)
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
        return dict(
            G_poa=G_raw * gain,
            Tcell_C=float(row.get('Tcell_C', 40.0)),
            Tamb_C=float(row.get('Tamb_C', 30.0)),
            headwind_ms=float(row.get('headwind_ms', 0.0)) if 'headwind_ms' in row else 0.0,
        )

    def _sample_plan_segments(self, dt_sample: float):
        if not self.v_plan_segments:
            return []
        if dt_sample <= 0.0:
            return [float(seg['v_kmh']) for seg in self.v_plan_segments]
        samples = []
        for seg in self.v_plan_segments:
            n = max(1, int(math.ceil(seg['dt_sec'] / dt_sample)))
            samples.extend([float(seg['v_kmh'])] * n)
        return samples

    def _route_value(self, s_km: float, field: str, default: float) -> float:
        if self.route_profile is None:
            return float(default)
        try:
            val = float(interpolate_profile(self.route_profile, s_km, field, default))
            if not np.isfinite(val):
                return float(default)
            return float(val)
        except Exception:
            return float(default)

    def _speed_limit_at(self, s_km: float, default_kmh: float) -> float:
        if self.speed_profile is None:
            return float(default_kmh)
        try:
            return float(interpolate_profile(self.speed_profile, s_km, 'v_max_kmh', default_kmh))
        except Exception:
            return float(default_kmh)

    def _soc_guard_speed(self, v_kmh: float, s_km: float, d0: dict) -> float:
        mode = str(self.get_parameter('soc_guard_mode').value).lower()
        soc_guard = float(self.get_parameter('soc_guard_margin').value)
        target = self.model.p.soc_min + soc_guard

        slope_pct = d0['slope_pct']
        if self.route_profile is not None:
            slope_pct = self._route_value(s_km, 'slope_pct', slope_pct)
        headwind_ms = d0.get('headwind_ms', 0.0)
        if self.route_profile is not None:
            headwind_ms = self._route_value(s_km, 'headwind_ms', headwind_ms)

        def z_next_for(v_kmh_local: float) -> float:
            out = self.model.electrical_balance(v_kmh_local / 3.6, slope_pct, self.z, self.Tb,
                                                d0['G_poa'], d0['Tcell_C'], headwind_ms=headwind_ms)
            P_pack = float(out['P_pack'])
            return self.z - (P_pack * self.model.p.dt / 3600.0) / self.model.p.E_nom_Wh

        # If already below target, apply guard mode
        if self.z <= target:
            if mode == 'stop':
                return 0.0
            if mode != 'pv_only':
                return v_kmh
            # find max speed such that P_pack <= 0
            lo = 0.0
            hi = max(0.0, float(v_kmh))
            for _ in range(20):
                mid = 0.5 * (lo + hi)
                if z_next_for(mid) < self.z:
                    hi = mid
                else:
                    lo = mid
            return float(lo)

        # If next step would violate, limit speed to keep z_next >= target
        if z_next_for(v_kmh) >= target:
            return v_kmh
        lo = 0.0
        hi = max(0.0, float(v_kmh))
        for _ in range(25):
            mid = 0.5 * (lo + hi)
            if z_next_for(mid) < target:
                hi = mid
            else:
                lo = mid
        return float(lo)

    def _dwell_penalty(self, s_km: float, v_ms: float) -> float:
        vmax_kmh = float(self.get_parameter('v_max_kmh').value)
        vmax_ms = vmax_kmh / 3.6
        pen = 0.0
        for st in self.stops:
            s_stop = float(st.get('s_km', 0.0))
            dwell_s = float(st.get('dwell_s', 0.0))
            width_km = max(0.05, (dwell_s * vmax_ms) / 1000.0 * 0.5)
            if abs(s_km - s_stop) <= width_km:
                pen += 1.0e5 * (v_ms ** 2)
        return pen

    def _mpc_solve_solar(self, data):
        p = self.model.p
        Np = len(data)
        if Np <= 0:
            return self.v_cmd, [self.v_cmd]

        v0_guess = self.v_cmd / 3.6
        if bool(self.get_parameter('use_measured_speed').value) and np.isfinite(self.v_now):
            v0_guess = float(self.v_now) / 3.6
        x0 = np.array([v0_guess] * Np, dtype=float)  # m/s
        lb = np.zeros(Np, dtype=float)
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

        def quad_penalty(x, cap=1.0e3):
            if x <= 0.0:
                return 0.0
            if x > cap:
                x = cap
            return x * x

        def cost(v):
            z = float(self.z)
            Tb = float(self.Tb)
            s_km = float(self.s_km)
            if bool(self.get_parameter('use_measured_s').value) and np.isfinite(self.s_meas):
                s_km = float(self.s_meas)
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
                z_next = z - (P_pack * p.dt / 3600.0) / p.E_nom_Wh
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
            return J

        bounds = list(zip(lb, ub))
        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=150))
        v_seq = res.x if res.success else x0
        v_seq_kmh = np.clip(v_seq * 3.6, 0.0, v_max_kmh)
        return float(v_seq_kmh[0]), [float(v) for v in v_seq_kmh]

    def _mpc_solve_solar_distance(self, t0_utc: datetime, s0_km: float, x0=None):
        p = self.model.p
        ds_km = max(1.0, float(self.upper_ds_km))
        horizon_km = max(ds_km, float(self.upper_horizon_km))
        Np = int(math.ceil(horizon_km / ds_km))
        if self.upper_max_steps > 0:
            Np = min(Np, int(self.upper_max_steps))
        if Np <= 0:
            return self.v_cmd, [{'v_kmh': float(self.v_cmd), 'dt_sec': float(p.dt)}]

        v_max_kmh = float(self.get_parameter('v_max_kmh').value)
        v0 = float(self.v_cmd)
        if bool(self.get_parameter('use_measured_speed').value) and np.isfinite(self.v_now):
            v0 = float(self.v_now)

        ctrl_km = float(self.upper_ctrl_km) if self.upper_ctrl_km and self.upper_ctrl_km > 0.0 else ds_km
        ctrl_km = max(ds_km, ctrl_km)
        seg_s = np.arange(Np, dtype=float) * ds_km
        ctrl_s = np.arange(0.0, float(seg_s[-1]) + 1.0e-6, ctrl_km)
        if len(ctrl_s) == 0:
            ctrl_s = np.array([0.0], dtype=float)
        if ctrl_s[-1] < seg_s[-1]:
            ctrl_s = np.append(ctrl_s, seg_s[-1])
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

        def expand_ctrl(u_vec):
            return (1.0 - alpha) * u_vec[idx] + alpha * u_vec[idx_next]

        w_dv = float(self.get_parameter('w_dv').value)
        w_dv_limit = float(self.get_parameter('w_dv_limit').value)
        dv_max_kmhps = float(self.get_parameter('dv_max_kmhps').value)
        w_T = float(self.get_parameter('w_T').value)
        w_speed_limit = float(self.get_parameter('w_speed_limit').value)
        w_drive_window = float(self.get_parameter('w_drive_window').value)
        w_current = float(self.get_parameter('w_current').value)
        term_soc_min = float(self.get_parameter('terminal_soc_min').value)
        day_end_soc_min = float(self.upper_day_end_soc_min)
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

        def step_wait(t_utc, z, Tb, s_km):
            if self.drive_schedule is None:
                return t_utc, z, Tb, 0.0
            if self.drive_schedule.is_drive_time(t_utc):
                return t_utc, z, Tb, 0.0
            t_start = self.drive_schedule.next_drive_start(t_utc)
            dt_wait = max(0.0, (t_start - t_utc).total_seconds())
            if dt_wait <= 0.0:
                return t_start, z, Tb, 0.0
            env = self._forecast_at_time(t_utc, drive=False)
            slope_pct = self._route_value(s_km, 'slope_pct', 0.0)
            headwind_ms = self._route_value(s_km, 'headwind_ms', env.get('headwind_ms', 0.0))
            out = self.model.electrical_balance(0.0, slope_pct, z, Tb, env['G_poa'], env['Tcell_C'], headwind_ms=headwind_ms)
            P_pack = float(out['P_pack'])
            loss_int = float(out['losses_int'])
            z = z - (P_pack * dt_wait / 3600.0) / p.E_nom_Wh
            Tb = Tb + (dt_wait / 1800.0) * (env['Tamb_C'] - Tb) + (loss_int * dt_wait) / 50000.0
            return t_start, float(z), float(Tb), dt_wait

        def quad_penalty(x, cap=1.0e3):
            if x <= 0.0:
                return 0.0
            if x > cap:
                x = cap
            return x * x

        def cost(u_vec):
            z = float(self.z)
            Tb = float(self.Tb)
            s_km = float(s0_km)
            t_utc = t0_utc
            v_prev = v0
            J = 0.0
            v_seq = expand_ctrl(u_vec)
            for k in range(Np):
                t_utc, z, Tb, dt_wait = step_wait(t_utc, z, Tb, s_km)
                if dt_wait > 0.0:
                    J += dt_wait
                v_k = float(v_seq[k])
                vmax_local = self._speed_limit_at(s_km, v_max_kmh)
                if vmax_local >= v_min_solver:
                    v_k = max(v_min_solver, min(v_k, vmax_local))
                else:
                    v_k = max(0.0, min(v_k, vmax_local))
                limits = None
                if self.drive_schedule is not None:
                    limits = self.drive_schedule.speed_limits(t_utc)
                if limits is not None:
                    vmin_kmh, vmax_kmh = limits
                    J += w_drive_window * quad_penalty(vmin_kmh - v_k)
                    J += w_drive_window * quad_penalty(v_k - vmax_kmh)

                dt_travel = ds_km / max(v_k, 1.0e-3) * 3600.0
                env = self._forecast_at_time(t_utc, drive=True)
                slope_pct = self._route_value(s_km, 'slope_pct', 0.0)
                headwind_ms = self._route_value(s_km, 'headwind_ms', env.get('headwind_ms', 0.0))
                out = self.model.electrical_balance(v_k / 3.6, slope_pct, z, Tb, env['G_poa'], env['Tcell_C'], headwind_ms=headwind_ms)
                I = float(out['I'])
                V = float(out['V'])
                P_pack = float(out['P_pack'])
                loss_int = float(out['losses_int'])

                z_next = z - (P_pack * dt_travel / 3600.0) / p.E_nom_Wh
                Tb_next = Tb + (dt_travel / 1800.0) * (env['Tamb_C'] - Tb) + (loss_int * dt_travel) / 50000.0

                J += dt_travel
                J += 30.0 * quad_penalty(term_soc_min - z_next)

                dv = (v_k - v_prev) / max(dt_travel, 1.0e-3)
                if dv_max_kmhps > 0.0:
                    J += w_dv_limit * quad_penalty(abs(dv) - dv_max_kmhps)

                J += w_speed_limit * quad_penalty(v_k - vmax_local)

                J += 1e4 * quad_penalty(I - p.I_max)
                J += 1e4 * quad_penalty(p.I_chg_min - I)
                J += 1e4 * quad_penalty(p.V_min - V)
                J += 1e4 * quad_penalty(V - p.V_max)
                J += w_T * quad_penalty(Tb_next - p.T_max)
                J += w_T * quad_penalty(p.T_min - Tb_next)
                J += 1e4 * quad_penalty(p.soc_min - z_next)
                J += 1e4 * quad_penalty(z_next - p.soc_max)

                t_next = t_utc + timedelta(seconds=dt_travel)
                if self.drive_schedule is not None and self.drive_schedule.is_drive_time(t_utc) and not self.drive_schedule.is_drive_time(t_next):
                    J += 1e5 * quad_penalty(day_end_soc_min - z_next)
                    if soc_day_end_max > 0.0:
                        J += w_soc_day_max * quad_penalty(z_next - soc_day_end_max)

                t_utc = t_next
                s_km += ds_km
                z, Tb = z_next, Tb_next
                v_prev = v_k

            J += 1e4 * quad_penalty(term_soc_min - z)
            if soc_finish_target > 0.0:
                J += w_soc_terminal * quad_penalty(z - soc_finish_target)
            return J

        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=self.upper_max_iter))
        u_seq = res.x if res.success else x0
        v_seq = expand_ctrl(u_seq)

        # Build segments with variable time
        segments = []
        t_utc = t0_utc
        s_km = float(s0_km)
        z = float(self.z)
        Tb = float(self.Tb)
        for v_k in v_seq:
            t_utc, z, Tb, _ = step_wait(t_utc, z, Tb, s_km)
            v_k = float(np.clip(v_k, 0.0, v_max_kmh))
            vmax_local = self._speed_limit_at(s_km, v_max_kmh)
            if vmax_local >= v_min_solver:
                v_k = max(v_min_solver, min(v_k, vmax_local))
            else:
                v_k = max(0.0, min(v_k, vmax_local))
            dt_travel = ds_km / max(v_k, 1.0e-3) * 3600.0
            segments.append({'v_kmh': v_k, 'dt_sec': float(dt_travel)})
            t_utc = t_utc + timedelta(seconds=dt_travel)
            s_km += ds_km

        v0_kmh = float(segments[0]['v_kmh']) if segments else float(self.v_cmd)
        return v0_kmh, segments, u_seq

    def _publish_upper_plan(self):
        if not self.v_plan_kmh:
            return
        msg = Float32MultiArray()
        msg.data = [float(self.plan_dt_sec)] + [float(v) for v in self.v_plan_kmh]
        self.pub_plan.publish(msg)

    def _publish_lower_plan(self, v_seq_ms):
        if not v_seq_ms:
            return
        msg = Float32MultiArray()
        msg.data = [float(self.lower_dt)] + [float(v * 3.6) for v in v_seq_ms]
        self.pub_lower_plan.publish(msg)

    def _publish_plan_path(self, data):
        if len(data) == 0:
            return
        path = Path()
        path.header.stamp = self.get_clock().now().to_msg()
        path.header.frame_id = 'map'
        s_tmp = float(self.s_km)
        if bool(self.get_parameter('use_measured_s').value) and np.isfinite(self.s_meas):
            s_tmp = float(self.s_meas)
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

    def _publish_metrics(self, d0: dict, v_exec_kmh: float, s_for_profile: float):
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

    def _interp_upper_speed(self, t_sec: float) -> float:
        if self.upper_plan_mode == 'distance' and self.v_plan_segments:
            acc = 0.0
            for seg in self.v_plan_segments:
                acc_next = acc + seg['dt_sec']
                if t_sec <= acc_next:
                    return float(seg['v_kmh'])
                acc = acc_next
            return float(self.v_plan_segments[-1]['v_kmh'])
        if not self.v_plan_kmh:
            return float(self.v_upper_cmd)
        dt = float(self.plan_dt_sec)
        if dt <= 0.0:
            return float(self.v_plan_kmh[0])
        idx = t_sec / dt
        i = int(math.floor(idx))
        if i <= 0:
            return float(self.v_plan_kmh[0])
        if i >= len(self.v_plan_kmh) - 1:
            return float(self.v_plan_kmh[-1])
        alpha = idx - i
        return float((1.0 - alpha) * self.v_plan_kmh[i] + alpha * self.v_plan_kmh[i + 1])

    def _tau_max_for_mode(self, maps, mode: str) -> float:
        key = mode if mode in maps else 'default'
        try:
            return float(max(maps[key][1]))
        except Exception:
            return 0.0

    def _tau_limits(self):
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
        return tau_drive, tau_regen

    def _traction_force(self, tau_nm: float) -> float:
        p = self.model.p
        wheel_r = max(1e-3, float(p.wheel_radius))
        motor_count = int(p.motor_count) if int(p.motor_count) > 0 else int(p.driven_wheel_count or 1)
        motor_count = max(1, motor_count)
        return float(tau_nm) * float(p.gear_ratio) * float(p.gear_eta) * motor_count / wheel_r

    def _pack_from_tau(self, v_ms: float, tau_nm: float, z: float, Tb: float, env: dict):
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
        return dict(P_pack=P_pack, I=I, V=V, loss_int=loss_int, eff=eff, P_pv=P_pv, P_elec=P_elec)

    def _build_lower_ref(self, base_time_utc, s_km: float, d0: dict):
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
            ref.append(float(v_ref) / 3.6)
            s_tmp += float(v_ref) * (self.lower_dt / 3600.0)
        return ref

    def _lower_rollout(self, v0_ms: float, u_seq: np.ndarray, env: dict, z0: float, Tb0: float,
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
        return v_seq

    def _lower_mpc_solve(self, v0_ms: float, s0_km: float, z0: float, Tb0: float, env: dict, v_ref_seq):
        N = max(1, min(self.lower_N, len(v_ref_seq)))
        if N <= 0:
            return np.zeros(1), [v0_ms], 'eco'
        v_ref_seq = v_ref_seq[:N]
        tau_drive, tau_regen = self._tau_limits()
        u0 = float(np.clip(self.lower_last_u, -1.0, 1.0))
        x0 = np.array([u0] * N, dtype=float)
        bounds = [(-1.0, 1.0)] * N

        p = self.model.p
        w_track = float(self.w_track)
        w_throttle = float(self.w_throttle)
        w_current = float(self.get_parameter('w_current').value)
        w_T = float(self.get_parameter('w_T').value)
        rate_lim = float(self.throttle_rate_limit) / 100.0 if self.throttle_rate_limit > 0.0 else 0.0

        def cost(u_vec):
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
                z = z - (P_pack * self.lower_dt / 3600.0) / float(p.E_nom_Wh)
                Tb = Tb + (self.lower_dt / 1800.0) * (env['Tamb_C'] - Tb) + (loss_int * self.lower_dt) / 50000.0

                v_ref = float(v_ref_seq[i])
                J += w_track * (v - v_ref) ** 2
                J += w_throttle * (u ** 2)
                du = (u - u_prev) / max(self.lower_dt, 1.0e-3)
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
            return J

        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=80))
        u_seq = res.x if res.success else x0
        v_pred = self._lower_rollout(v0_ms, u_seq, env, z0, Tb0, tau_drive, tau_regen)
        u0_cmd = float(u_seq[0]) if len(u_seq) > 0 else 0.0
        tau0 = u0_cmd * (tau_drive if u0_cmd >= 0.0 else tau_regen)
        mode = self.model.select_drive_mode(v0_ms, tau0)
        return u_seq, v_pred, mode

    def _step_solar(self):
        self._maybe_reload_forecast()
        k_now = self._current_bin_index()
        moved_to_new_bin = (self.last_bin is None) or (k_now != self.last_bin)
        self.k = k_now

        data = self._horizon_data(self.k)
        self.last_data = data
        if len(data) > 0:
            d0 = data[0]
            s_for_profile = self.s_km
            if bool(self.get_parameter('use_measured_s').value) and np.isfinite(self.s_meas):
                s_for_profile = float(self.s_meas)
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
            if bool(self.get_parameter('use_measured_speed').value) and np.isfinite(self.v_now):
                v_exec_kmh = float(self.v_now)
            self._publish_metrics(d0, v_exec_kmh, s_for_profile)
        need_plan = moved_to_new_bin or (self.v_plan_kmh is None) or self.forecast_reloaded
        if self.upper_mode == 'distance':
            if self.v_plan_segments is None:
                need_plan = True
            if self.upper_replan_km > 0.0 and self.upper_plan_s_km is not None:
                if (self.s_km - self.upper_plan_s_km) >= self.upper_replan_km:
                    need_plan = True
            if self.upper_replan_sec > 0.0 and self.upper_plan_time is not None:
                if (data and data[0].get('t_utc') and (data[0]['t_utc'] - self.upper_plan_time).total_seconds() >= self.upper_replan_sec):
                    need_plan = True
        if need_plan and len(data) > 0:
            s_for_profile = self.s_km
            if bool(self.get_parameter('use_measured_s').value) and np.isfinite(self.s_meas):
                s_for_profile = float(self.s_meas)
            t0 = data[0].get('t_utc', datetime.now(timezone.utc))
            if self.upper_mode == 'distance':
                self.v_upper_cmd, self.v_plan_segments, self.upper_plan_seq = self._mpc_solve_solar_distance(
                    t0, s_for_profile, self.upper_plan_seq
                )
                self.upper_plan_mode = 'distance'
                self.plan_dt_sec = float(self.model.p.dt)
                self.v_plan_kmh = self._sample_plan_segments(self.plan_dt_sec)
                self.upper_plan_s_km = float(s_for_profile)
                self.upper_plan_time = t0
                self.upper_plan_id += 1
            else:
                self.v_upper_cmd, self.v_plan_kmh = self._mpc_solve_solar(data)
                self.v_plan_segments = None
                self.upper_plan_mode = 'time'
                self.plan_dt_sec = float(self.model.p.dt)
            self.plan_start_monotonic = time.monotonic()
            self.last_plan_time = time.monotonic()
            self.forecast_reloaded = False
        elif self.v_plan_kmh is None and len(data) > 0:
            self.v_plan_kmh = [float(self.v_upper_cmd)] * len(data)

        if self.upper_plan_mode == 'distance' and self.plan_start_monotonic is not None:
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
                if bool(self.get_parameter('use_measured_s').value) and np.isfinite(self.s_meas):
                    s_for_profile = float(self.s_meas)
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
            if bool(self.get_parameter('use_measured_s').value) and np.isfinite(self.s_meas):
                s_for_profile = float(self.s_meas)
            slope_pct = d0['slope_pct']
            if self.route_profile is not None:
                slope_pct = self._route_value(s_for_profile, 'slope_pct', slope_pct)
            headwind_ms = d0.get('headwind_ms', 0.0)
            if self.route_profile is not None:
                headwind_ms = self._route_value(s_for_profile, 'headwind_ms', headwind_ms)
            v_exec_kmh = self.v_upper_cmd
            if self.hierarchical and self.timer_lower is not None:
                v_exec_kmh = self.v_lower_cmd
            if bool(self.get_parameter('use_measured_speed').value) and np.isfinite(self.v_now):
                v_exec_kmh = float(self.v_now)

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
                soc=self.solar_soc_meas if np.isfinite(self.solar_soc_meas) else None,
                Tb=self.solar_tb_meas if np.isfinite(self.solar_tb_meas) else None,
                I=self.solar_i_meas if np.isfinite(self.solar_i_meas) else None,
                V=self.solar_v_meas if np.isfinite(self.solar_v_meas) else None,
            )
            if self.mhe is not None:
                self.mhe.push(u, meas)
                self.z, self.Tb = self.mhe.estimate(self.z, self.Tb)
            else:
                out = self.model.electrical_balance(u.v_ms, u.slope_pct, self.z, self.Tb, u.G_poa, u.Tcell_C, headwind_ms=u.headwind_ms)
                P_pack = float(out['P_pack'])
                loss_int = float(out['losses_int'])
                self.z = self.z - (P_pack * self.model.p.dt / 3600.0) / self.model.p.E_nom_Wh
                self.Tb = self.Tb + (self.model.p.dt / 1800.0) * (u.Tamb_C - self.Tb) + (loss_int * self.model.p.dt) / 50000.0
            self.z = float(np.clip(self.z, self.model.p.soc_min, self.model.p.soc_max))
            self.Tb = float(np.clip(self.Tb, self.model.p.T_min, self.model.p.T_max))

            if bool(self.get_parameter('use_measured_s').value) and np.isfinite(self.s_meas):
                self.s_km = float(self.s_meas)
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

    def _step_lower(self):
        if not self.hierarchical or self.timer_lower is None:
            return
        if not self.last_data:
            return
        d0 = self.last_data[0]
        s_for_profile = self.s_km
        if bool(self.get_parameter('use_measured_s').value) and np.isfinite(self.s_meas):
            s_for_profile = float(self.s_meas)
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

        if bool(self.get_parameter('use_measured_speed').value) and np.isfinite(self.v_now):
            v0_ms = float(self.v_now) / 3.6
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
        self.lower_last_mode = str(mode)

        self.pub_speed.publish(Float32(data=float(self.v_lower_cmd)))
        throttle_pct = float(np.clip(self.lower_last_u * 100.0, -100.0, 100.0))
        self.pub_throttle.publish(Float32(data=throttle_pct))
        self.pub_drive_mode.publish(String(data=str(self.lower_last_mode)))
        self._publish_lower_plan(v_pred)

    # -------------------- passo mode --------------------
    def _init_passo(self):
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
        self.create_subscription(Float32, '/vehicle/s_km', self._on_s_km, 10)
        self.create_subscription(Float32, '/vehicle/speed_kmh', self._on_speed, 10)
        self.create_subscription(Float32, '/vehicle/fuel_rate_lph', self._on_fuel, 10)
        self.create_subscription(Float32, '/vehicle/throttle_pct', self._on_throttle, 10)
        self.create_subscription(Float32, '/vehicle/obd_ok', self._on_obd_ok, 10)
        self.create_subscription(Float32, '/vehicle/grade', self._on_grade, 10)
        self.create_subscription(Float32, '/vehicle/idle_fuel_lph', self._on_idle_fuel, 10)
        self.create_subscription(String, '/system/config', self._on_config, 10)
        self.create_subscription(Bool, '/system/config_ready', self._on_config_ready, 10)
        self.create_subscription(String, '/system/state', self._on_system_state, 10)

        # Publications
        self.pub_speed = self.create_publisher(Float32, '/planner/speed_cmd', 10)
        self.pub_path = self.create_publisher(Path, '/planner/trajectory', 10)
        self.pub_status = self.create_publisher(Float32MultiArray, '/planner/status', 10)
        self.pub_mpc_state = self.create_publisher(String, '/system/mpc_state', 10)

        # Timer @1Hz
        self.timer = self.create_timer(1.0, self._step_passo)
        self.get_logger().info('MPCNode started (passo mode).')

    def _on_s_km(self, msg: Float32):
        self.s_km = float(msg.data)

    def _on_speed(self, msg: Float32):
        self.v_now = float(msg.data)

    def _on_fuel(self, msg: Float32):
        self.fuel_rate_lph = float(msg.data)

    def _on_throttle(self, msg: Float32):
        self.throttle_pct = float(msg.data)

    def _on_obd_ok(self, msg: Float32):
        self.obd_ok = float(msg.data)

    def _on_grade(self, msg: Float32):
        self.grade = float(msg.data)

    def _on_idle_fuel(self, msg: Float32):
        self.idle_fuel_lph = float(msg.data)
        if np.isfinite(self.idle_fuel_lph):
            self.model_coeffs[0] = float(self.idle_fuel_lph)

    def _on_config_ready(self, msg: Bool):
        self.config_ready = bool(msg.data)

    def _on_system_state(self, msg: String):
        self.system_state = str(msg.data)

    def _on_config(self, msg: String):
        try:
            cfg = yaml.safe_load(msg.data) or {}
        except Exception:
            return
        self._apply_config(cfg)

    def _apply_config(self, cfg: dict):
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

    def _stop_penalty_passo(self, s_km: float, v_kmh: float) -> float:
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
        return pen

    def _fuel_model_lph(self, v_kmh: float, acc_kmhps: float, grade: float) -> float:
        a0, a1, a2, a3, a4 = self.model_coeffs
        a0_eff = a0
        if np.isfinite(self.idle_fuel_lph):
            a0_eff = float(self.idle_fuel_lph)
        fuel = a0_eff + a1 * v_kmh + a2 * (v_kmh ** 2) + a3 * (acc_kmhps ** 2) + a4 * grade * v_kmh
        return max(0.0, float(fuel))

    def _update_identification(self, now_sec: float, acc_kmhps: float):
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

    def _solve_passo_mpc(self, w_fuel_override=None) -> np.ndarray:
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

        def cost(v_vec):
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
            return J

        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=120))
        if not res.success:
            return x0
        return np.array(res.x, dtype=float)

    def _publish_trajectory_passo(self, v_seq: np.ndarray):
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

    def _step_passo(self):
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


def main():
    rclpy.init()
    node = MPCNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
                if soc_finish_target > 0.0:
                    prog = max(0.0, min(1.0, s_km / max(race_km, 1.0)))
                    soc_line = z_start + (soc_finish_target - z_start) * prog
                    if z_next > (soc_line + soc_finish_tol):
                        J += w_soc_progress * quad_penalty(z_next - (soc_line + soc_finish_tol))
                    if z_next < (soc_line - soc_finish_tol):
                        J += w_soc_progress * quad_penalty((soc_line - soc_finish_tol) - z_next)
