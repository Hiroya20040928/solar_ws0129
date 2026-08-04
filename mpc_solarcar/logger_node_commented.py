import csv
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import os
from datetime import datetime

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import Float32, Float32MultiArray, String


PASSO_STATUS_FIELDS = [
    'status_fuel_now_lph',
    'status_fuel_pred_lph',
    'status_v_now_kmh',
    'status_v_cmd_kmh',
    'status_s_km',
    'status_id_rmse',
    'status_id_r2',
]

SOLAR_STATUS_FIELDS = [
    'status_soc',
    'status_tb_c',
    'status_s_km',
    'status_forecast_idx',
    'status_sec_to_next',
]

ENV_FIELDS = [
    'env_G_poa',
    'env_Tcell_C',
    'env_Tamb_C',
    'env_slope_pct',
    'env_headwind_ms',
]

METRIC_FIELDS = [
    'metric_pack_voltage_v',
    'metric_pack_current_a',
    'metric_soc',
    'metric_motor_w',
    'metric_motor_a',
    'metric_solar_w',
    'metric_exec_speed_kmh',
    'metric_wheel_w',
    'metric_pack_w',
]

PLAN_FIELDS = [
    'upper_plan_dt_sec',
    'upper_plan_count',
    'upper_plan_first_kmh',
    'lower_plan_dt_sec',
    'lower_plan_count',
    'lower_plan_first_kmh',
]

SUMMARY_FIELDS = [
    'race_progress_pct',
    'next_stop_dist_km',
    'next_stop_eta_min',
    'finish_dist_km',
    'finish_eta_h',
    'avg_plan_speed_kmh',
]

CAL_FIELDS = [
    'cal_solar_gain',
    'cal_drive_gain',
    'cal_aux_power_w',
    'cal_stationary_samples',
    'cal_drive_samples',
]

WIND_FIELDS = [
    'wind_obs_ms',
    'wind_fcst_ms',
    'wind_post_ms',
    'wind_post_std_ms',
    'wind_heading_deg',
    'wind_source_code',
    'wind_mu_ms',
    'wind_sigma_ms',
    'wind_lo95_ms',
    'wind_hi95_ms',
    'wind_plan_ms',
    'wind_weight',
    'vehicle_headwind_obs_ms',
    'chase_headwind_obs_ms',
]

GPS_FIELDS = [
    'gps_lat',
    'gps_lon',
    'gps_alt_m',
    'vehicle_lat',
    'vehicle_lon',
    'vehicle_alt_m',
    'chase_lat',
    'chase_lon',
    'chase_alt_m',
]

STRING_FIELDS = [
    'system_state',
    'system_diag',
    'can_profile',
    'pid_profile',
    'mpc_state',
    'config_yaml',
    'drive_mode',
    'forecast_status',
    'calibration_status',
    'command_status',
    'network_status',
    'wind_model_status',
]


class LoggerNode(Node):                                            # [クラス定義] LoggerNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('logger_node')
        self.declare_parameter('mode', 'solar')
        self.declare_parameter('log_dir', 'outputs/logs')
        self.declare_parameter('file_prefix', 'solar_log')
        self.declare_parameter('log_rate_hz', 2.0)

        self.mode = str(self.get_parameter('mode').value or 'solar').lower()
        if self.mode == 'passo':
            self.status_fields = PASSO_STATUS_FIELDS
        else:
            self.status_fields = SOLAR_STATUS_FIELDS

        log_dir = str(self.get_parameter('log_dir').value)
        file_prefix = str(self.get_parameter('file_prefix').value)
        log_rate_hz = max(0.5, float(self.get_parameter('log_rate_hz').value))

        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_path = os.path.join(log_dir, f'{file_prefix}_{timestamp}.csv')

        self.fields = [
            't_ros_sec',
            'speed_kmh',
            's_km',
            'rpm',
            'throttle_pct',
            'maf_gps',
            'fuel_rate_lph',
            'obd_ok',
            'idle_fuel_lph',
            'grade',
            'batt_soc',
            'batt_temp_c',
            'batt_current_a',
            'batt_voltage_v',
            'speed_cmd',
            'upper_speed_cmd',
            'throttle_cmd_pct',
            'system_health',
        ] + self.status_fields + ENV_FIELDS + METRIC_FIELDS + PLAN_FIELDS + SUMMARY_FIELDS + CAL_FIELDS + WIND_FIELDS + GPS_FIELDS + STRING_FIELDS

        self.latest = {field: math.nan for field in self.fields}
        for field in STRING_FIELDS:
            self.latest[field] = ''

        self.create_subscription(Float32, '/vehicle/speed_kmh', self._set('speed_kmh'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/s_km', self._set('s_km'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/rpm', self._set('rpm'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/throttle_pct', self._set('throttle_pct'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/maf_gps', self._set('maf_gps'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/fuel_rate_lph', self._set('fuel_rate_lph'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/obd_ok', self._set('obd_ok'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/idle_fuel_lph', self._set('idle_fuel_lph'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/grade', self._set('grade'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/batt_soc', self._set('batt_soc'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/batt_temp_c', self._set('batt_temp_c'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/batt_current_a', self._set('batt_current_a'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/batt_voltage_v', self._set('batt_voltage_v'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/planner/speed_cmd', self._set('speed_cmd'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/planner/upper_speed_cmd', self._set('upper_speed_cmd'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/planner/throttle_cmd_pct', self._set('throttle_cmd_pct'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/planner/drive_mode', self._set_str('drive_mode'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/status', self._on_status, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/env', self._on_env, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/metrics', self._on_metrics, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/summary', self._on_summary, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/calibration_state', self._on_calibration_state, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/wind_state', self._on_wind_state, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/upper_plan', self._on_upper_plan, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/lower_plan', self._on_lower_plan, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/system/health', self._set('system_health'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/state', self._set_str('system_state'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/diag', self._set_str('system_diag'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/can_profile', self._set_str('can_profile'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/pid_profile', self._set_str('pid_profile'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/mpc_state', self._set_str('mpc_state'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/config', self._set_str('config_yaml'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/forecast_status', self._set_str('forecast_status'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/calibration_status', self._set_str('calibration_status'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/command_status', self._set_str('command_status'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/network_status', self._set_str('network_status'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/system/wind_model_status', self._set_str('wind_model_status'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/headwind_obs_ms', self._set('vehicle_headwind_obs_ms'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/chase/headwind_obs_ms', self._set('chase_headwind_obs_ms'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(NavSatFix, '/sim/gps', self._on_gps, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(NavSatFix, '/vehicle/gps', self._on_vehicle_gps, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(NavSatFix, '/chase/gps', self._on_chase_gps, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(NavSatFix, '/vehicle/gps', self._on_gps, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        self.csv_file = open(self.log_path, 'w', newline='', encoding='utf-8')
        self.writer = csv.DictWriter(self.csv_file, fieldnames=self.fields)
        self.writer.writeheader()
        self.csv_file.flush()

        self.timer = self.create_timer(1.0 / log_rate_hz, self._write_row)
        self.get_logger().info(f'LoggerNode started: {self.log_path}')

    def _set(self, key):                                           # [関数定義] _set の処理実行ブロック
        def _handler(msg):                                         # [関数定義] _handler の処理実行ブロック
            try:
                self.latest[key] = float(msg.data)
            except Exception:
                self.latest[key] = math.nan
        return _handler                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _set_str(self, key):                                       # [関数定義] _set_str の処理実行ブロック
        def _handler(msg):                                         # [関数定義] _handler の処理実行ブロック
            try:
                self.latest[key] = str(msg.data)
            except Exception:
                self.latest[key] = ''
        return _handler                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _on_status(self, msg: Float32MultiArray):                  # [関数定義] _on_status の処理実行ブロック
        data = list(msg.data)
        for i, field in enumerate(self.status_fields):
            self.latest[field] = float(data[i]) if i < len(data) else math.nan

    def _on_env(self, msg: Float32MultiArray):                     # [関数定義] _on_env の処理実行ブロック
        data = list(msg.data)
        for i, field in enumerate(ENV_FIELDS):
            self.latest[field] = float(data[i]) if i < len(data) else math.nan

    def _on_metrics(self, msg: Float32MultiArray):                 # [関数定義] _on_metrics の処理実行ブロック
        data = list(msg.data)
        for i, field in enumerate(METRIC_FIELDS):
            self.latest[field] = float(data[i]) if i < len(data) else math.nan

    def _on_upper_plan(self, msg: Float32MultiArray):              # [関数定義] _on_upper_plan の処理実行ブロック
        data = list(msg.data)
        self.latest['upper_plan_dt_sec'] = float(data[0]) if len(data) >= 1 else math.nan
        self.latest['upper_plan_count'] = float(max(0, len(data) - 1))
        self.latest['upper_plan_first_kmh'] = float(data[1]) if len(data) >= 2 else math.nan

    def _on_lower_plan(self, msg: Float32MultiArray):              # [関数定義] _on_lower_plan の処理実行ブロック
        data = list(msg.data)
        self.latest['lower_plan_dt_sec'] = float(data[0]) if len(data) >= 1 else math.nan
        self.latest['lower_plan_count'] = float(max(0, len(data) - 1))
        self.latest['lower_plan_first_kmh'] = float(data[1]) if len(data) >= 2 else math.nan

    def _on_summary(self, msg: Float32MultiArray):                 # [関数定義] _on_summary の処理実行ブロック
        data = list(msg.data)
        for i, field in enumerate(SUMMARY_FIELDS):
            self.latest[field] = float(data[i]) if i < len(data) else math.nan

    def _on_calibration_state(self, msg: Float32MultiArray):       # [関数定義] _on_calibration_state の処理実行ブロック
        data = list(msg.data)
        for i, field in enumerate(CAL_FIELDS):
            self.latest[field] = float(data[i]) if i < len(data) else math.nan

    def _on_wind_state(self, msg: Float32MultiArray):              # [関数定義] _on_wind_state の処理実行ブロック
        data = list(msg.data)
        for i, field in enumerate(WIND_FIELDS[:12]):
            self.latest[field] = float(data[i]) if i < len(data) else math.nan

    def _on_gps(self, msg: NavSatFix):                             # [関数定義] _on_gps の処理実行ブロック
        self.latest['gps_lat'] = float(msg.latitude)
        self.latest['gps_lon'] = float(msg.longitude)
        self.latest['gps_alt_m'] = float(msg.altitude) if math.isfinite(msg.altitude) else math.nan

    def _on_vehicle_gps(self, msg: NavSatFix):                     # [関数定義] _on_vehicle_gps の処理実行ブロック
        self.latest['vehicle_lat'] = float(msg.latitude)
        self.latest['vehicle_lon'] = float(msg.longitude)
        self.latest['vehicle_alt_m'] = float(msg.altitude) if math.isfinite(msg.altitude) else math.nan

    def _on_chase_gps(self, msg: NavSatFix):                       # [関数定義] _on_chase_gps の処理実行ブロック
        self.latest['chase_lat'] = float(msg.latitude)
        self.latest['chase_lon'] = float(msg.longitude)
        self.latest['chase_alt_m'] = float(msg.altitude) if math.isfinite(msg.altitude) else math.nan

    def _write_row(self):                                          # [関数定義] _write_row の処理実行ブロック
        self.latest['t_ros_sec'] = self.get_clock().now().nanoseconds / 1e9
        row = {}
        for key in self.fields:
            if key in STRING_FIELDS:
                row[key] = self._clean_str(self.latest.get(key, ''))
            else:
                row[key] = self._clean(self.latest.get(key, math.nan))
        self.writer.writerow(row)
        self.csv_file.flush()

    def _clean(self, value):                                       # [関数定義] _clean の処理実行ブロック
        try:
            if math.isfinite(float(value)):
                return float(value)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception:
            pass
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _clean_str(self, value):                                   # [関数定義] _clean_str の処理実行ブロック
        if value is None:
            return ''                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return str(value).replace('\\n', '\\\\n').replace('\\r', '')  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def destroy_node(self):                                        # [関数定義] destroy_node の処理実行ブロック
        try:
            self.csv_file.close()
        except Exception:
            pass
        super().destroy_node()


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = LoggerNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
