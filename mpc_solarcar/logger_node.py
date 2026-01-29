import csv
import math
import os
from datetime import datetime

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, Float32MultiArray, String


STATUS_FIELDS = [
    'status_fuel_now_lph',
    'status_fuel_pred_lph',
    'status_v_now_kmh',
    'status_v_cmd_kmh',
    'status_s_km',
    'status_id_rmse',
    'status_id_r2',
]

STRING_FIELDS = [
    'system_state',
    'system_diag',
    'can_profile',
    'pid_profile',
    'mpc_state',
    'config_yaml',
]


class LoggerNode(Node):
    def __init__(self):
        super().__init__('logger_node')
        self.declare_parameter('log_dir', 'logs')
        self.declare_parameter('file_prefix', 'passo_log')
        self.declare_parameter('log_rate_hz', 1.0)

        log_dir = self.get_parameter('log_dir').value
        file_prefix = self.get_parameter('file_prefix').value
        log_rate_hz = float(self.get_parameter('log_rate_hz').value)

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
            'throttle_cmd_pct',
            'system_health',
        ] + STATUS_FIELDS + STRING_FIELDS

        self.latest = {field: math.nan for field in self.fields}
        for field in STRING_FIELDS:
            self.latest[field] = ''

        self.sub_speed = self.create_subscription(Float32, '/vehicle/speed_kmh', self._set('speed_kmh'), 10)
        self.sub_s = self.create_subscription(Float32, '/vehicle/s_km', self._set('s_km'), 10)
        self.sub_rpm = self.create_subscription(Float32, '/vehicle/rpm', self._set('rpm'), 10)
        self.sub_throttle = self.create_subscription(Float32, '/vehicle/throttle_pct', self._set('throttle_pct'), 10)
        self.sub_maf = self.create_subscription(Float32, '/vehicle/maf_gps', self._set('maf_gps'), 10)
        self.sub_fuel = self.create_subscription(Float32, '/vehicle/fuel_rate_lph', self._set('fuel_rate_lph'), 10)
        self.sub_obd = self.create_subscription(Float32, '/vehicle/obd_ok', self._set('obd_ok'), 10)
        self.sub_idle = self.create_subscription(Float32, '/vehicle/idle_fuel_lph', self._set('idle_fuel_lph'), 10)
        self.sub_grade = self.create_subscription(Float32, '/vehicle/grade', self._set('grade'), 10)
        self.sub_soc = self.create_subscription(Float32, '/vehicle/batt_soc', self._set('batt_soc'), 10)
        self.sub_batt_temp = self.create_subscription(Float32, '/vehicle/batt_temp_c', self._set('batt_temp_c'), 10)
        self.sub_batt_i = self.create_subscription(Float32, '/vehicle/batt_current_a', self._set('batt_current_a'), 10)
        self.sub_batt_v = self.create_subscription(Float32, '/vehicle/batt_voltage_v', self._set('batt_voltage_v'), 10)
        self.sub_cmd = self.create_subscription(Float32, '/planner/speed_cmd', self._set('speed_cmd'), 10)
        self.sub_throttle_cmd = self.create_subscription(Float32, '/planner/throttle_cmd_pct', self._set('throttle_cmd_pct'), 10)
        self.sub_status = self.create_subscription(Float32MultiArray, '/planner/status', self._on_status, 10)
        self.sub_health = self.create_subscription(Float32, '/system/health', self._set('system_health'), 10)
        self.sub_state = self.create_subscription(String, '/system/state', self._set_str('system_state'), 10)
        self.sub_diag = self.create_subscription(String, '/system/diag', self._set_str('system_diag'), 10)
        self.sub_can = self.create_subscription(String, '/system/can_profile', self._set_str('can_profile'), 10)
        self.sub_pid = self.create_subscription(String, '/system/pid_profile', self._set_str('pid_profile'), 10)
        self.sub_mpc = self.create_subscription(String, '/system/mpc_state', self._set_str('mpc_state'), 10)
        self.sub_cfg = self.create_subscription(String, '/system/config', self._set_str('config_yaml'), 10)

        self.csv_file = open(self.log_path, 'w', newline='')
        self.writer = csv.DictWriter(self.csv_file, fieldnames=self.fields)
        self.writer.writeheader()
        self.csv_file.flush()

        self.timer = self.create_timer(1.0 / log_rate_hz, self._write_row)
        self.get_logger().info(f'LoggerNode started: {self.log_path}')

    def _set(self, key):
        def _handler(msg):
            try:
                self.latest[key] = float(msg.data)
            except Exception:
                self.latest[key] = math.nan
        return _handler

    def _set_str(self, key):
        def _handler(msg):
            try:
                self.latest[key] = str(msg.data)
            except Exception:
                self.latest[key] = ''
        return _handler

    def _on_status(self, msg: Float32MultiArray):
        data = list(msg.data)
        for i, field in enumerate(STATUS_FIELDS):
            self.latest[field] = float(data[i]) if i < len(data) else math.nan

    def _write_row(self):
        self.latest['t_ros_sec'] = self.get_clock().now().nanoseconds / 1e9
        row = {}
        for k in self.fields:
            if k in STRING_FIELDS:
                row[k] = self._clean_str(self.latest.get(k, ''))
            else:
                row[k] = self._clean(self.latest.get(k, math.nan))
        self.writer.writerow(row)
        self.csv_file.flush()

    def _clean(self, value):
        try:
            if math.isfinite(float(value)):
                return float(value)
        except Exception:
            pass
        return ''

    def _clean_str(self, value):
        if value is None:
            return ''
        val = str(value)
        return val.replace('\\n', '\\\\n').replace('\\r', '')

    def destroy_node(self):
        try:
            self.csv_file.close()
        except Exception:
            pass
        super().destroy_node()


def main():
    rclpy.init()
    node = LoggerNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
