from __future__ import annotations
import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import socket
import time
from typing import Dict

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import Float32, Float32MultiArray, String



def as_float(value, default=math.nan):                             # [関数定義] as_float の処理実行ブロック
    return finite_float(value, default=default)                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


class TelemetryTextBridgeNode(Node):                               # [クラス定義] TelemetryTextBridgeNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('telemetry_text_bridge_node')
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
        self.get_logger().info(
            f'TelemetryTextBridgeNode started: inbound={self.enable_inbound} {self.bind_host}:{self.bind_port}, '
            f'outbound={self.enable_outbound}'
        )

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
    rclpy.init()
    node = TelemetryTextBridgeNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


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