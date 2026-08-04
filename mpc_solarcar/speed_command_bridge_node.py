import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import socket
import time

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from std_msgs.msg import Float32, String



class SpeedCommandBridgeNode(Node):                                # [クラス定義] SpeedCommandBridgeNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('speed_command_bridge_node')
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
        self.get_logger().info(
            f'SpeedCommandBridgeNode started: topic={self.output_speed_topic}, rate={self.publish_rate_hz:.1f}Hz, '
            f'udp={self.udp_enabled}'
        )

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
    rclpy.init()
    node = SpeedCommandBridgeNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

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