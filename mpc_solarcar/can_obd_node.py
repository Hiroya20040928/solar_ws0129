import math
import threading
import time

import can
import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import SetParametersResult
from std_msgs.msg import Float32
import numpy as np


OBD_RESPONSE_IDS = range(0x7E8, 0x7F0)
PID_SUPPORT_BASES = {0x00, 0x20, 0x40, 0x60, 0x80}
EXTENDED_RESP_MASK = 0x1FFFFF00
EXTENDED_RESP_VALUE = 0x18DAF100


class CanObdNode(Node):
    def __init__(self):
        super().__init__('can_obd_node')
        self.declare_parameter('can_interface', 'can0')
        self.declare_parameter('request_rate_hz', 10.0)
        self.declare_parameter('publish_rate_hz', 1.0)
        self.declare_parameter('enable_pid_5e', True)
        self.declare_parameter('use_extended_id', False)
        self.declare_parameter('request_id', 0x7DF)
        self.declare_parameter('response_id_mask', 0)
        self.declare_parameter('response_id_value', 0)
        self.declare_parameter('pid_allowlist', [])
        self.declare_parameter('enabled', True)
        self.declare_parameter('idle_speed_threshold_kmh', 1.0)
        self.declare_parameter('idle_calib_sec', 15.0)
        self.declare_parameter('idle_recalib_enabled', False)
        self.declare_parameter('afr_stoich', 14.7)
        self.declare_parameter('fuel_density_kg_per_l', 0.74)
        self.declare_parameter('max_no_response_sec', 3.0)

        self.can_interface = self.get_parameter('can_interface').value
        self.request_rate_hz = float(self.get_parameter('request_rate_hz').value)
        self.publish_rate_hz = float(self.get_parameter('publish_rate_hz').value)
        self.use_extended_id = bool(self.get_parameter('use_extended_id').value)
        self.request_id = int(self.get_parameter('request_id').value)
        self.response_id_mask = int(self.get_parameter('response_id_mask').value)
        self.response_id_value = int(self.get_parameter('response_id_value').value)
        self.enabled = bool(self.get_parameter('enabled').value)

        self.pub_speed = self.create_publisher(Float32, '/vehicle/speed_kmh', 10)
        self.pub_rpm = self.create_publisher(Float32, '/vehicle/rpm', 10)
        self.pub_throttle = self.create_publisher(Float32, '/vehicle/throttle_pct', 10)
        self.pub_maf = self.create_publisher(Float32, '/vehicle/maf_gps', 10)
        self.pub_fuel = self.create_publisher(Float32, '/vehicle/fuel_rate_lph', 10)
        self.pub_obd_ok = self.create_publisher(Float32, '/vehicle/obd_ok', 10)
        self.pub_idle = self.create_publisher(Float32, '/vehicle/idle_fuel_lph', 10)

        self.values = {
            'speed_kmh': math.nan,
            'rpm': math.nan,
            'throttle_pct': math.nan,
            'maf_gps': math.nan,
            'fuel_rate_lph': math.nan,
        }

        self.supported_pids = set()
        self.pending_caps = []
        self.request_pids = []
        self.request_index = 0
        self._update_pid_lists()

        self.last_response_time = None
        self.last_warn_time = 0.0
        self.last_open_attempt = 0.0
        self.idle_fuel_lph = math.nan
        self.idle_samples = []
        self.idle_start_time = None

        self.bus = None
        self.bus_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.rx_thread = threading.Thread(target=self._rx_loop, daemon=True)
        self.rx_thread.start()

        self.request_timer = self.create_timer(1.0 / self.request_rate_hz, self._send_request)
        self.publish_timer = self.create_timer(1.0 / self.publish_rate_hz, self._publish)

        self.add_on_set_parameters_callback(self._on_parameters)

        self.get_logger().info('CanObdNode started.')

    def _on_parameters(self, params):
        for param in params:
            if param.name == 'use_extended_id':
                self.use_extended_id = bool(param.value)
            elif param.name == 'request_id':
                self.request_id = int(param.value)
            elif param.name == 'response_id_mask':
                self.response_id_mask = int(param.value)
            elif param.name == 'response_id_value':
                self.response_id_value = int(param.value)
            elif param.name == 'pid_allowlist':
                self._update_pid_lists(pid_allowlist=param.value)
            elif param.name == 'enabled':
                self.enabled = bool(param.value)
        return SetParametersResult(successful=True)

    def _update_pid_lists(self, pid_allowlist=None):
        if pid_allowlist is None:
            pid_allowlist = self.get_parameter('pid_allowlist').value
        allowlist = [int(pid) for pid in pid_allowlist] if pid_allowlist else []
        base_pids = [0x0D, 0x0C, 0x11, 0x10]
        if bool(self.get_parameter('enable_pid_5e').value):
            base_pids.append(0x5E)
        if allowlist:
            self.supported_pids = set(allowlist)
            self.request_pids = [pid for pid in base_pids if pid in self.supported_pids]
            if not self.request_pids:
                self.request_pids = base_pids
            self.pending_caps = []
        else:
            self.supported_pids = set()
            self.request_pids = base_pids
            self.pending_caps = [0x00, 0x20, 0x40, 0x60, 0x80]
        self.request_index = 0

    def _open_bus(self):
        try:
            bus = can.interface.Bus(channel=self.can_interface, bustype='socketcan')
            self.get_logger().info(f'Opened CAN interface {self.can_interface}')
            return bus
        except Exception as exc:
            self._warn_throttle(f'Failed to open CAN {self.can_interface}: {exc}')
            return None

    def _warn_throttle(self, msg: str, interval_sec: float = 5.0):
        now = time.monotonic()
        if now - self.last_warn_time >= interval_sec:
            self.get_logger().warn(msg)
            self.last_warn_time = now

    def _rx_loop(self):
        while rclpy.ok() and not self.stop_event.is_set():
            if self.bus is None:
                now = time.monotonic()
                if now - self.last_open_attempt >= 5.0:
                    self.last_open_attempt = now
                    with self.bus_lock:
                        self.bus = self._open_bus()
                time.sleep(0.2)
                continue
            try:
                msg = self.bus.recv(timeout=0.2)
            except Exception as exc:
                self._warn_throttle(f'CAN recv error: {exc}')
                with self.bus_lock:
                    try:
                        self.bus.shutdown()
                    except Exception:
                        pass
                    self.bus = None
                continue
            if msg is None:
                continue
            self._handle_message(msg)

    def _handle_message(self, msg):
        if msg.is_extended_id != self.use_extended_id:
            return
        if not self._match_response_id(msg.arbitration_id):
            return
        data = list(msg.data)
        if len(data) < 3:
            return
        mode = data[1]
        pid = data[2]
        if mode != 0x41:
            return
        self.last_response_time = time.monotonic()

        if pid in PID_SUPPORT_BASES:
            if len(data) < 7:
                return
            mask = (data[3] << 24) | (data[4] << 16) | (data[5] << 8) | data[6]
            base = pid
            for i in range(32):
                if mask & (1 << (31 - i)):
                    self.supported_pids.add(base + i + 1)
            return

        if pid == 0x0D and len(data) >= 4:
            self.values['speed_kmh'] = float(data[3])
        elif pid == 0x0C and len(data) >= 5:
            self.values['rpm'] = float((data[3] * 256 + data[4]) / 4.0)
        elif pid == 0x11 and len(data) >= 4:
            self.values['throttle_pct'] = float(data[3]) * 100.0 / 255.0
        elif pid == 0x10 and len(data) >= 5:
            self.values['maf_gps'] = float((data[3] * 256 + data[4]) / 100.0)
        elif pid == 0x5E and len(data) >= 5:
            self.values['fuel_rate_lph'] = float((data[3] * 256 + data[4]) / 20.0)

    def _send_request(self):
        if self.bus is None or not self.enabled:
            return
        pid = None
        if self.pending_caps:
            pid = self.pending_caps.pop(0)
        else:
            pid = self.request_pids[self.request_index]
            self.request_index = (self.request_index + 1) % len(self.request_pids)
        if self.supported_pids and pid in self.request_pids and pid not in self.supported_pids:
            return
        msg = can.Message(
            arbitration_id=self.request_id,
            data=[0x02, 0x01, pid, 0, 0, 0, 0, 0],
            is_extended_id=self.use_extended_id,
        )
        try:
            with self.bus_lock:
                if self.bus is None:
                    return
                self.bus.send(msg)
        except Exception as exc:
            self._warn_throttle(f'CAN send error: {exc}')

    def _match_response_id(self, arb_id: int) -> bool:
        if self.response_id_mask != 0:
            return (arb_id & self.response_id_mask) == self.response_id_value
        if self.use_extended_id:
            return (arb_id & EXTENDED_RESP_MASK) == EXTENDED_RESP_VALUE
        return arb_id in OBD_RESPONSE_IDS

    def _update_idle_calibration(self, speed_kmh, fuel_rate_lph):
        allow_recalib = bool(self.get_parameter('idle_recalib_enabled').value)
        if np_isfinite(self.idle_fuel_lph) and not allow_recalib:
            return
        speed_thresh = float(self.get_parameter('idle_speed_threshold_kmh').value)
        idle_sec = float(self.get_parameter('idle_calib_sec').value)
        now = time.monotonic()

        if not np_isfinite(speed_kmh) or not np_isfinite(fuel_rate_lph):
            self.idle_start_time = None
            self.idle_samples = []
            return

        if speed_kmh < speed_thresh:
            if self.idle_start_time is None:
                self.idle_start_time = now
            self.idle_samples.append(float(fuel_rate_lph))
            if (now - self.idle_start_time) >= idle_sec:
                self.idle_fuel_lph = self._robust_median(self.idle_samples)
                if not allow_recalib:
                    self.idle_start_time = None
                    self.idle_samples = []
        else:
            self.idle_start_time = None
            self.idle_samples = []

    def _robust_median(self, samples):
        if not samples:
            return math.nan
        arr = np.array([s for s in samples if np_isfinite(s)], dtype=float)
        if arr.size == 0:
            return math.nan
        q1 = np.percentile(arr, 25)
        q3 = np.percentile(arr, 75)
        iqr = q3 - q1
        if iqr <= 0.0:
            return float(np.median(arr))
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        filtered = arr[(arr >= lower) & (arr <= upper)]
        if filtered.size == 0:
            filtered = arr
        return float(np.median(filtered))

    def _publish(self):
        now = time.monotonic()
        max_no_response = float(self.get_parameter('max_no_response_sec').value)
        if self.last_response_time is None or (now - self.last_response_time) > max_no_response:
            obd_ok = 0.0
        else:
            obd_ok = 1.0

        if obd_ok < 0.5:
            speed = math.nan
            rpm = math.nan
            throttle = math.nan
            maf_gps = math.nan
            fuel_rate = math.nan
        else:
            speed = self.values['speed_kmh']
            rpm = self.values['rpm']
            throttle = self.values['throttle_pct']
            maf_gps = self.values['maf_gps']
            fuel_rate = self.values['fuel_rate_lph']

        if not np_isfinite(fuel_rate):
            if np_isfinite(maf_gps):
                afr = float(self.get_parameter('afr_stoich').value)
                fuel_density = float(self.get_parameter('fuel_density_kg_per_l').value)
                maf_kg_per_s = maf_gps / 1000.0
                # MAF -> fuel: fuel_kg/s = maf_kg/s / AFR, then convert to L/h
                fuel_rate = (maf_kg_per_s / afr) / fuel_density * 3600.0
            else:
                fuel_rate = math.nan

        self._update_idle_calibration(speed, fuel_rate)

        self._pub_float(self.pub_speed, speed)
        self._pub_float(self.pub_rpm, rpm)
        self._pub_float(self.pub_throttle, throttle)
        self._pub_float(self.pub_maf, maf_gps)
        self._pub_float(self.pub_fuel, fuel_rate)
        self._pub_float(self.pub_obd_ok, obd_ok)
        self._pub_float(self.pub_idle, self.idle_fuel_lph)

    def _pub_float(self, pub, value):
        msg = Float32()
        msg.data = float(value) if np_isfinite(value) else math.nan
        pub.publish(msg)

    def destroy_node(self):
        self.stop_event.set()
        with self.bus_lock:
            if self.bus is not None:
                try:
                    self.bus.shutdown()
                except Exception:
                    pass
                self.bus = None
        super().destroy_node()


def np_isfinite(val) -> bool:
    try:
        return math.isfinite(float(val))
    except Exception:
        return False


def main():
    rclpy.init()
    node = CanObdNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
