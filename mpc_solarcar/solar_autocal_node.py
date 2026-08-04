from __future__ import annotations
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import time

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from std_msgs.msg import Float32, Float32MultiArray, String


def finite(value, default=math.nan):                               # [関数定義] finite の処理実行ブロック
    try:
        v = float(value)
        if math.isfinite(v):
            return v                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        pass
    return default                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


class SolarAutoCalNode(Node):                                      # [クラス定義] SolarAutoCalNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('solar_autocal_node')
        self.declare_parameter('publish_period_sec', 30.0)
        self.declare_parameter('stationary_speed_kmh', 2.0)
        self.declare_parameter('drive_speed_kmh', 25.0)
        self.declare_parameter('night_ghi_threshold', 50.0)
        self.declare_parameter('day_ghi_threshold', 150.0)
        self.declare_parameter('alpha', 0.2)
        self.declare_parameter('solar_gain_init', 1.0)
        self.declare_parameter('drive_power_gain_init', 1.0)
        self.declare_parameter('aux_power_w_init', 8.0)
        self.declare_parameter('solar_gain_min', 0.5)
        self.declare_parameter('solar_gain_max', 1.5)
        self.declare_parameter('drive_power_gain_min', 0.7)
        self.declare_parameter('drive_power_gain_max', 1.4)
        self.declare_parameter('aux_power_w_min', 0.0)
        self.declare_parameter('aux_power_w_max', 300.0)
        self.declare_parameter('measurement_timeout_sec', 10.0)
        self.declare_parameter('max_speed_change_kmhps', 0.5)
        self.declare_parameter('max_stationary_slope_pct', 1.0)
        self.declare_parameter('max_drive_slope_pct', 0.6)
        self.declare_parameter('min_solar_pred_w', 80.0)
        self.declare_parameter('min_drive_pred_w', 120.0)

        self.alpha = float(self.get_parameter('alpha').value)
        self.stationary_speed_kmh = float(self.get_parameter('stationary_speed_kmh').value)
        self.drive_speed_kmh = float(self.get_parameter('drive_speed_kmh').value)
        self.night_ghi_threshold = float(self.get_parameter('night_ghi_threshold').value)
        self.day_ghi_threshold = float(self.get_parameter('day_ghi_threshold').value)
        self.solar_gain = float(self.get_parameter('solar_gain_init').value)
        self.drive_power_gain = float(self.get_parameter('drive_power_gain_init').value)
        self.aux_power_w = float(self.get_parameter('aux_power_w_init').value)
        self.solar_gain_min = float(self.get_parameter('solar_gain_min').value)
        self.solar_gain_max = float(self.get_parameter('solar_gain_max').value)
        self.drive_power_gain_min = float(self.get_parameter('drive_power_gain_min').value)
        self.drive_power_gain_max = float(self.get_parameter('drive_power_gain_max').value)
        self.aux_power_w_min = float(self.get_parameter('aux_power_w_min').value)
        self.aux_power_w_max = float(self.get_parameter('aux_power_w_max').value)
        self.measurement_timeout_sec = max(1.0, float(self.get_parameter('measurement_timeout_sec').value))
        self.max_speed_change_kmhps = max(0.0, float(self.get_parameter('max_speed_change_kmhps').value))
        self.max_stationary_slope_pct = max(0.0, float(self.get_parameter('max_stationary_slope_pct').value))
        self.max_drive_slope_pct = max(0.0, float(self.get_parameter('max_drive_slope_pct').value))
        self.min_solar_pred_w = max(0.0, float(self.get_parameter('min_solar_pred_w').value))
        self.min_drive_pred_w = max(0.0, float(self.get_parameter('min_drive_pred_w').value))

        self.speed_kmh = math.nan
        self.meas_pack_w = math.nan
        self.pred_pack_w = math.nan
        self.pred_solar_w = math.nan
        self.ghi = math.nan
        self.slope_pct = math.nan
        self.last_update = 0.0
        self.stationary_samples = 0
        self.drive_samples = 0
        self.speed_change_kmhps = math.nan
        self.last_speed_time = None
        self.last_pack_time = None
        self.last_env_time = None
        self.last_metrics_time = None
        self._prev_speed = math.nan
        self._prev_speed_time = None

        self.create_subscription(Float32, '/vehicle/speed_kmh', self._on_speed, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/batt_voltage_v', self._on_v, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/batt_current_a', self._on_i, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/env', self._on_env, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/metrics', self._on_metrics, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        self.pub_cal = self.create_publisher(String, '/planner/calibration', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_state = self.create_publisher(Float32MultiArray, '/planner/calibration_state', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_status = self.create_publisher(String, '/system/calibration_status', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        period = max(5.0, float(self.get_parameter('publish_period_sec').value))
        self.timer = self.create_timer(period, self._tick)
        self.get_logger().info('SolarAutoCalNode started.')

    def _on_speed(self, msg: Float32):                             # [関数定義] _on_speed の処理実行ブロック
        now = time.monotonic()
        speed = finite(msg.data)
        if math.isfinite(speed) and self._prev_speed_time is not None and math.isfinite(self._prev_speed):
            dt = max(1.0e-3, now - self._prev_speed_time)
            self.speed_change_kmhps = abs(speed - self._prev_speed) / dt
        self.speed_kmh = speed
        self.last_speed_time = now
        self._prev_speed = speed
        self._prev_speed_time = now

    def _on_v(self, msg: Float32):                                 # [関数定義] _on_v の処理実行ブロック
        v = finite(msg.data)
        i = finite(self._last_current if hasattr(self, '_last_current') else math.nan)
        if math.isfinite(v) and math.isfinite(i):
            self.meas_pack_w = v * i
            self.last_pack_time = time.monotonic()
        self._last_voltage = v

    def _on_i(self, msg: Float32):                                 # [関数定義] _on_i の処理実行ブロック
        i = finite(msg.data)
        v = finite(self._last_voltage if hasattr(self, '_last_voltage') else math.nan)
        if math.isfinite(v) and math.isfinite(i):
            self.meas_pack_w = v * i
            self.last_pack_time = time.monotonic()
        self._last_current = i

    def _on_env(self, msg: Float32MultiArray):                     # [関数定義] _on_env の処理実行ブロック
        data = list(msg.data)
        if len(data) >= 4:
            self.ghi = finite(data[0], 0.0)
            self.slope_pct = finite(data[3], 0.0)
            self.last_env_time = time.monotonic()

    def _on_metrics(self, msg: Float32MultiArray):                 # [関数定義] _on_metrics の処理実行ブロック
        data = list(msg.data)
        if len(data) >= 9:
            self.pred_solar_w = finite(data[5], 0.0)
            self.pred_pack_w = finite(data[8], math.nan)
            self.last_metrics_time = time.monotonic()

    def _ema(self, old, new):                                      # [関数定義] _ema の処理実行ブロック
        if not math.isfinite(new):
            return old                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if not math.isfinite(old):
            return new                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return (1.0 - self.alpha) * old + self.alpha * new         # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _clamp(self, val, lo, hi):                                 # [関数定義] _clamp の処理実行ブロック
        return max(lo, min(hi, val))                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _fresh(self, timestamp, now):                              # [関数定義] _fresh の処理実行ブロック
        return timestamp is not None and (now - timestamp) <= self.measurement_timeout_sec  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _tick(self):                                               # [関数定義] _tick の処理実行ブロック
        now = time.monotonic()
        status = 'collecting'

        data_fresh = (
            self._fresh(self.last_speed_time, now) and
            self._fresh(self.last_pack_time, now) and
            self._fresh(self.last_env_time, now) and
            self._fresh(self.last_metrics_time, now)
        )
        stable_speed = (not math.isfinite(self.speed_change_kmhps)) or (self.speed_change_kmhps <= self.max_speed_change_kmhps)
        slope_now = abs(finite(self.slope_pct, 0.0))

        if not data_fresh:
            status = 'waiting fresh data'
        elif not stable_speed:
            status = 'waiting stable speed'
        elif math.isfinite(self.meas_pack_w) and math.isfinite(self.pred_pack_w):
            if math.isfinite(self.speed_kmh) and self.speed_kmh <= self.stationary_speed_kmh:
                if slope_now > self.max_stationary_slope_pct:
                    status = 'stationary slope too large'
                elif math.isfinite(self.ghi) and self.ghi <= self.night_ghi_threshold:
                    self.aux_power_w = self._clamp(self._ema(self.aux_power_w, self.meas_pack_w), self.aux_power_w_min, self.aux_power_w_max)
                    status = 'aux recalibrated'
                elif math.isfinite(self.ghi) and self.ghi >= self.day_ghi_threshold and math.isfinite(self.pred_solar_w):
                    solar_base = self.pred_solar_w / max(self.solar_gain, 1.0e-6)
                    if abs(solar_base) > self.min_solar_pred_w:
                        solar_candidate = (self.aux_power_w - self.meas_pack_w) / solar_base
                        self.solar_gain = self._clamp(self._ema(self.solar_gain, solar_candidate), self.solar_gain_min, self.solar_gain_max)
                        self.stationary_samples += 1
                        status = 'solar gain recalibrated'
                    else:
                        status = 'waiting stronger solar signal'
            elif math.isfinite(self.speed_kmh) and self.speed_kmh >= self.drive_speed_kmh:
                if slope_now > self.max_drive_slope_pct:
                    status = 'drive slope too large'
                elif math.isfinite(self.ghi) and self.ghi <= self.day_ghi_threshold:
                    pred_drive = self.pred_pack_w + self.pred_solar_w - self.aux_power_w
                    meas_drive = self.meas_pack_w + self.pred_solar_w - self.aux_power_w
                    drive_base = pred_drive / max(self.drive_power_gain, 1.0e-6)
                    if abs(drive_base) > self.min_drive_pred_w:
                        drive_candidate = meas_drive / drive_base
                        self.drive_power_gain = self._clamp(
                            self._ema(self.drive_power_gain, drive_candidate),
                            self.drive_power_gain_min,
                            self.drive_power_gain_max,
                        )
                        self.drive_samples += 1
                        status = 'drive gain recalibrated'
                    else:
                        status = 'waiting stronger drive load'
            else:
                status = 'waiting valid operating point'

        payload = {
            'solar_gain': round(self.solar_gain, 5),
            'drive_power_gain': round(self.drive_power_gain, 5),
            'aux_power_w': round(self.aux_power_w, 3),
            'stationary_samples': int(self.stationary_samples),
            'drive_samples': int(self.drive_samples),
            'speed_change_kmhps': round(finite(self.speed_change_kmhps, math.nan), 4),
            'updated_at_monotonic': round(now, 3),
        }
        self.pub_cal.publish(String(data=yaml.safe_dump(payload, sort_keys=False)))
        msg = Float32MultiArray()
        msg.data = [
            float(self.solar_gain),
            float(self.drive_power_gain),
            float(self.aux_power_w),
            float(self.stationary_samples),
            float(self.drive_samples),
        ]
        self.pub_state.publish(msg)
        self.pub_status.publish(String(data=status))


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = SolarAutoCalNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

# =============================================================================
# 【統合ロジック】太陽電池自動校正アルゴリズム
# =============================================================================
"""Pure helpers for bounded online solar-car calibration."""


import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート


def daytime_stationary_aux_estimate(                               # [関数定義] daytime_stationary_aux_estimate の処理実行ブロック
    *,
    ghi_wm2: float,
    day_ghi_threshold_wm2: float,
    speed_kmh: float,
    stationary_speed_kmh: float,
    pack_power_w: float,
    solar_power_w: float,
) -> float | None:
    values = (ghi_wm2, speed_kmh, pack_power_w, solar_power_w)
    if not all(math.isfinite(float(value)) for value in values):
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if float(ghi_wm2) < float(day_ghi_threshold_wm2):
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if abs(float(speed_kmh)) > float(stationary_speed_kmh):
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return max(0.0, float(pack_power_w) + float(solar_power_w))    # [戻り値] 計算結果・計算状態の呼び出し元への返却