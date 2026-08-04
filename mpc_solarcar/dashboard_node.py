import json
import os
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import rclpy
from rclpy.node import Node

from std_msgs.msg import Float32, Float32MultiArray, String
from sensor_msgs.msg import NavSatFix
from nav_msgs.msg import Path

from ament_index_python.packages import get_package_share_directory


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, node=None, directory=None, **kwargs):
        self._node = node
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        if self.path.startswith('/api/state'):
            self._send_json(self._node.get_state())
            return
        super().do_GET()

    def log_message(self, format, *args):
        # quiet
        return

    def _send_json(self, data):
        payload = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class DashboardNode(Node):
    def __init__(self):
        super().__init__('dashboard_node')
        self.declare_parameter('host', '0.0.0.0')
        self.declare_parameter('port', 8080)
        self.declare_parameter('static_dir', '')
        self.declare_parameter('dummy_csv', '')
        self.declare_parameter('dummy_rate_hz', 5.0)

        static_dir = str(self.get_parameter('static_dir').value).strip()
        if not static_dir:
            try:
                pkg_share = get_package_share_directory('mpc_solarcar')
                static_dir = os.path.join(pkg_share, 'dashboard')
            except Exception:
                static_dir = os.path.join(os.path.dirname(__file__), '..', 'dashboard')
        static_dir = os.path.abspath(static_dir)

        self._lock = threading.Lock()
        self._state = {
            'ts': time.time(),
            'speed_cmd_kmh': None,
            'upper_speed_cmd_kmh': None,
            'speed_meas_kmh': None,
            'throttle_cmd_pct': None,
            'drive_mode': None,
            'soc': None,
            'Tb_C': None,
            's_km': None,
            'batt_current_a': None,
            'batt_voltage_v': None,
            'motor_w': None,
            'motor_a': None,
            'solar_w': None,
            'wheel_w': None,
            'pack_w': None,
            'G_poa': None,
            'Tcell_C': None,
            'Tamb_C': None,
            'headwind_ms': None,
            'slope_pct': None,
            'plan_dt': None,
            'lower_dt': None,
            'plan_upper': None,
            'plan_lower': None,
            'forecast_k': None,
            'sec_to_next': None,
            'system_state': None,
            'system_diag': None,
            'mpc_state': None,
            'system_health': None,
            'gps_lat': None,
            'gps_lon': None,
            'vehicle_lat': None,
            'vehicle_lon': None,
            'chase_lat': None,
            'chase_lon': None,
            'forecast_status': None,
            'calibration_status': None,
            'command_status': None,
            'network_status': None,
            'wind_model_status': None,
            'cal_solar_gain': None,
            'cal_drive_gain': None,
            'cal_aux_power_w': None,
            'race_progress_pct': None,
            'next_stop_dist_km': None,
            'next_stop_eta_min': None,
            'finish_dist_km': None,
            'finish_eta_h': None,
            'avg_plan_speed_kmh': None,
            'wind_obs_ms': None,
            'wind_fcst_ms': None,
            'wind_post_ms': None,
            'wind_post_std_ms': None,
            'wind_heading_deg': None,
            'wind_source_code': None,
            'wind_mu_ms': None,
            'wind_sigma_ms': None,
            'wind_lo95_ms': None,
            'wind_hi95_ms': None,
            'wind_plan_ms': None,
            'wind_weight': None,
            'vehicle_headwind_obs_ms': None,
            'chase_headwind_obs_ms': None,
        }

        self.create_subscription(Float32, '/planner/speed_cmd', self._on_speed_cmd, 10)
        self.create_subscription(Float32, '/planner/upper_speed_cmd', self._on_upper_speed_cmd, 10)
        self.create_subscription(Float32, '/vehicle/speed_kmh', self._on_speed_meas, 10)
        self.create_subscription(Float32, '/planner/throttle_cmd_pct', self._on_throttle_cmd, 10)
        self.create_subscription(String, '/planner/drive_mode', self._on_drive_mode, 10)
        self.create_subscription(Float32, '/vehicle/batt_soc', self._on_soc, 10)
        self.create_subscription(Float32, '/vehicle/batt_temp_c', self._on_tb, 10)
        self.create_subscription(Float32, '/vehicle/batt_current_a', self._on_ibatt, 10)
        self.create_subscription(Float32, '/vehicle/batt_voltage_v', self._on_vbatt, 10)
        self.create_subscription(Float32, '/vehicle/s_km', self._on_s_km, 10)
        self.create_subscription(Float32MultiArray, '/planner/status', self._on_status, 10)
        self.create_subscription(Float32MultiArray, '/planner/env', self._on_env, 10)
        self.create_subscription(Float32MultiArray, '/planner/metrics', self._on_metrics, 10)
        self.create_subscription(Float32MultiArray, '/planner/summary', self._on_summary, 10)
        self.create_subscription(Float32MultiArray, '/planner/calibration_state', self._on_calibration_state, 10)
        self.create_subscription(Float32MultiArray, '/planner/wind_state', self._on_wind_state, 10)
        self.create_subscription(Float32MultiArray, '/planner/upper_plan', self._on_upper_plan, 10)
        self.create_subscription(Float32MultiArray, '/planner/lower_plan', self._on_lower_plan, 10)
        self.create_subscription(String, '/system/state', self._on_sys_state, 10)
        self.create_subscription(String, '/system/diag', self._on_sys_diag, 10)
        self.create_subscription(String, '/system/mpc_state', self._on_mpc_state, 10)
        self.create_subscription(Float32, '/system/health', self._on_health, 10)
        self.create_subscription(String, '/system/forecast_status', self._on_forecast_status, 10)
        self.create_subscription(String, '/system/calibration_status', self._on_calibration_status, 10)
        self.create_subscription(String, '/system/command_status', self._on_command_status, 10)
        self.create_subscription(String, '/system/network_status', self._on_network_status, 10)
        self.create_subscription(String, '/system/wind_model_status', self._on_wind_model_status, 10)
        self.create_subscription(NavSatFix, '/sim/gps', self._on_gps, 10)
        self.create_subscription(NavSatFix, '/vehicle/gps', self._on_vehicle_gps, 10)
        self.create_subscription(NavSatFix, '/chase/gps', self._on_chase_gps, 10)
        self.create_subscription(Float32, '/vehicle/headwind_obs_ms', self._on_vehicle_headwind, 10)
        self.create_subscription(Float32, '/chase/headwind_obs_ms', self._on_chase_headwind, 10)
        self.create_subscription(Path, '/planner/trajectory', self._on_path, 10)

        dummy_csv = str(self.get_parameter('dummy_csv').value).strip()
        if dummy_csv:
            self._init_dummy(dummy_csv, float(self.get_parameter('dummy_rate_hz').value))

        self._server = None
        self._server_thread = None
        host = str(self.get_parameter('host').value)
        port = int(self.get_parameter('port').value)
        handler = partial(DashboardHandler, node=self, directory=static_dir)
        try:
            self._server = ThreadingHTTPServer((host, port), handler)
            self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._server_thread.start()
            self.get_logger().info(f'Dashboard server at http://{host}:{port} (dir={static_dir})')
        except Exception as exc:
            self.get_logger().error(f'Failed to start dashboard server: {exc}')

    def destroy_node(self):
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
        return super().destroy_node()

    def get_state(self):
        with self._lock:
            return dict(self._state)

    def _update(self, key, value):
        with self._lock:
            self._state[key] = value
            self._state['ts'] = time.time()

    def _on_speed_cmd(self, msg: Float32):
        self._update('speed_cmd_kmh', float(msg.data))

    def _on_upper_speed_cmd(self, msg: Float32):
        self._update('upper_speed_cmd_kmh', float(msg.data))

    def _on_speed_meas(self, msg: Float32):
        self._update('speed_meas_kmh', float(msg.data))

    def _on_throttle_cmd(self, msg: Float32):
        self._update('throttle_cmd_pct', float(msg.data))

    def _on_drive_mode(self, msg: String):
        self._update('drive_mode', str(msg.data))

    def _on_soc(self, msg: Float32):
        self._update('soc', float(msg.data))

    def _on_tb(self, msg: Float32):
        self._update('Tb_C', float(msg.data))

    def _on_ibatt(self, msg: Float32):
        self._update('batt_current_a', float(msg.data))

    def _on_vbatt(self, msg: Float32):
        self._update('batt_voltage_v', float(msg.data))

    def _on_s_km(self, msg: Float32):
        self._update('s_km', float(msg.data))

    def _on_status(self, msg: Float32MultiArray):
        data = list(msg.data)
        with self._lock:
            if len(data) >= 5:
                self._state['soc'] = float(data[0])
                self._state['Tb_C'] = float(data[1])
                self._state['s_km'] = float(data[2])
                self._state['forecast_k'] = float(data[3])
                self._state['sec_to_next'] = float(data[4])
            self._state['status_raw'] = data
            self._state['ts'] = time.time()

    def _on_env(self, msg: Float32MultiArray):
        data = list(msg.data)
        if len(data) < 5:
            return
        with self._lock:
            self._state['G_poa'] = float(data[0])
            self._state['Tcell_C'] = float(data[1])
            self._state['Tamb_C'] = float(data[2])
            self._state['slope_pct'] = float(data[3])
            self._state['headwind_ms'] = float(data[4])
            self._state['ts'] = time.time()

    def _on_metrics(self, msg: Float32MultiArray):
        data = list(msg.data)
        if len(data) < 8:
            return
        with self._lock:
            self._state['batt_voltage_v'] = float(data[0])
            self._state['batt_current_a'] = float(data[1])
            self._state['soc'] = float(data[2])
            self._state['motor_w'] = float(data[3])
            self._state['motor_a'] = float(data[4])
            self._state['solar_w'] = float(data[5])
            self._state['speed_cmd_kmh'] = float(data[6])
            self._state['wheel_w'] = float(data[7])
            if len(data) >= 9:
                self._state['pack_w'] = float(data[8])
            self._state['ts'] = time.time()

    def _on_upper_plan(self, msg: Float32MultiArray):
        data = list(msg.data)
        if len(data) < 2:
            return
        dt = float(data[0])
        speeds = [float(v) for v in data[1:]]
        with self._lock:
            self._state['plan_dt'] = dt
            self._state['plan_upper'] = speeds
            self._state['ts'] = time.time()

    def _on_lower_plan(self, msg: Float32MultiArray):
        data = list(msg.data)
        if len(data) < 2:
            return
        dt = float(data[0])
        speeds = [float(v) for v in data[1:]]
        with self._lock:
            self._state['lower_dt'] = dt
            self._state['plan_lower'] = speeds
            self._state['ts'] = time.time()

    def _on_sys_state(self, msg: String):
        self._update('system_state', str(msg.data))

    def _on_sys_diag(self, msg: String):
        self._update('system_diag', str(msg.data))

    def _on_mpc_state(self, msg: String):
        self._update('mpc_state', str(msg.data))

    def _on_health(self, msg: Float32):
        self._update('system_health', float(msg.data))

    def _on_forecast_status(self, msg: String):
        self._update('forecast_status', str(msg.data))

    def _on_calibration_status(self, msg: String):
        self._update('calibration_status', str(msg.data))

    def _on_command_status(self, msg: String):
        self._update('command_status', str(msg.data))

    def _on_network_status(self, msg: String):
        self._update('network_status', str(msg.data))

    def _on_wind_model_status(self, msg: String):
        self._update('wind_model_status', str(msg.data))

    def _on_gps(self, msg: NavSatFix):
        with self._lock:
            self._state['gps_lat'] = float(msg.latitude)
            self._state['gps_lon'] = float(msg.longitude)
            self._state['ts'] = time.time()

    def _on_vehicle_gps(self, msg: NavSatFix):
        with self._lock:
            self._state['vehicle_lat'] = float(msg.latitude)
            self._state['vehicle_lon'] = float(msg.longitude)
            self._state['ts'] = time.time()

    def _on_chase_gps(self, msg: NavSatFix):
        with self._lock:
            self._state['chase_lat'] = float(msg.latitude)
            self._state['chase_lon'] = float(msg.longitude)
            self._state['ts'] = time.time()

    def _on_vehicle_headwind(self, msg: Float32):
        self._update('vehicle_headwind_obs_ms', float(msg.data))

    def _on_chase_headwind(self, msg: Float32):
        self._update('chase_headwind_obs_ms', float(msg.data))

    def _on_path(self, msg: Path):
        # Keep last path length as a simple sanity signal
        with self._lock:
            self._state['path_points'] = len(msg.poses)
            self._state['ts'] = time.time()

    def _on_calibration_state(self, msg: Float32MultiArray):
        data = list(msg.data)
        with self._lock:
            if len(data) >= 3:
                self._state['cal_solar_gain'] = float(data[0])
                self._state['cal_drive_gain'] = float(data[1])
                self._state['cal_aux_power_w'] = float(data[2])
            self._state['ts'] = time.time()

    def _on_wind_state(self, msg: Float32MultiArray):
        data = list(msg.data)
        keys = [
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
        ]
        with self._lock:
            for i, key in enumerate(keys):
                if i < len(data):
                    self._state[key] = float(data[i])
            self._state['ts'] = time.time()

    def _on_summary(self, msg: Float32MultiArray):
        data = list(msg.data)
        with self._lock:
            if len(data) >= 6:
                self._state['race_progress_pct'] = float(data[0])
                self._state['next_stop_dist_km'] = float(data[1])
                self._state['next_stop_eta_min'] = float(data[2])
                self._state['finish_dist_km'] = float(data[3])
                self._state['finish_eta_h'] = float(data[4])
                self._state['avg_plan_speed_kmh'] = float(data[5])
            self._state['ts'] = time.time()

    def _init_dummy(self, path: str, rate_hz: float):
        try:
            import pandas as pd
            df = pd.read_csv(path)
        except Exception as exc:
            self.get_logger().error(f'Failed to load dummy_csv: {exc}')
            return
        if df.empty:
            self.get_logger().error('dummy_csv is empty.')
            return
        self._dummy_rows = df.to_dict(orient='records')
        self._dummy_idx = 0
        period = 1.0 / max(rate_hz, 0.5)
        self._dummy_timer = self.create_timer(period, self._tick_dummy)
        self.get_logger().info(f'Dummy mode enabled: {path} ({len(self._dummy_rows)} rows)')

    def _tick_dummy(self):
        if not hasattr(self, '_dummy_rows') or not self._dummy_rows:
            return
        row = self._dummy_rows[self._dummy_idx]
        self._dummy_idx = (self._dummy_idx + 1) % len(self._dummy_rows)
        with self._lock:
            for key, val in row.items():
                try:
                    self._state[key] = float(val)
                except Exception:
                    self._state[key] = val
            self._state['ts'] = time.time()


def main():
    rclpy.init()
    node = DashboardNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
