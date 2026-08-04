import os
import subprocess
import time
from typing import List, Optional, Tuple

import can
import rclpy
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.parameter_client import AsyncParametersClient
from std_msgs.msg import Bool, Float32, String


PID_SPEED = 0x0D
PID_SUPPORT_00 = 0x00
PID_SUPPORT_20 = 0x20
PID_FUEL_RATE = 0x5E
PID_MAF = 0x10

STANDARD_REQ_ID = 0x7DF
EXTENDED_REQ_ID = 0x18DB33F1
EXTENDED_RESP_MASK = 0x1FFFFF00
EXTENDED_RESP_VALUE = 0x18DAF100


class PreflightNode(Node):
    def __init__(self):
        super().__init__('preflight_node')
        self.declare_parameter('can_interface', 'can0')
        self.declare_parameter('bitrate_candidates', [500000, 250000])
        self.declare_parameter('probe_interval_sec', 2.0)
        self.declare_parameter('obd_timeout_sec', 1.0)
        self.declare_parameter('max_no_response_sec', 3.0)
        self.declare_parameter('can_obd_node_name', 'can_obd_node')
        self.declare_parameter('manage_can_interface', False)

        self.can_interface = self.get_parameter('can_interface').value
        self.bitrates = [int(b) for b in self.get_parameter('bitrate_candidates').value]
        self.probe_interval_sec = float(self.get_parameter('probe_interval_sec').value)
        self.obd_timeout_sec = float(self.get_parameter('obd_timeout_sec').value)
        self.max_no_response_sec = float(self.get_parameter('max_no_response_sec').value)
        self.manage_can = bool(self.get_parameter('manage_can_interface').value)

        self.state = 'DISCONNECTED'
        self.diag = 'waiting for CAN interface'
        self.health = 0.0
        self.can_profile = 'unknown'
        self.pid_profile = 'unknown'

        self.config_ready = False
        self.config_required = False
        self.last_obd_time = None
        self.profile_confirmed = False
        self.use_extended_id = False
        self.request_id = STANDARD_REQ_ID
        self.supported_pids = set()
        self.last_probe_time = 0.0
        self.mpc_state = 'IDLE'
        self.params_pushed = False

        self.pub_state = self.create_publisher(String, '/system/state', 10)
        self.pub_health = self.create_publisher(Float32, '/system/health', 10)
        self.pub_diag = self.create_publisher(String, '/system/diag', 10)
        self.pub_can_profile = self.create_publisher(String, '/system/can_profile', 10)
        self.pub_pid_profile = self.create_publisher(String, '/system/pid_profile', 10)

        self.create_subscription(Bool, '/system/config_ready', self._on_config_ready, 10)
        self.create_subscription(Bool, '/system/config_required', self._on_config_required, 10)
        self.create_subscription(Float32, '/vehicle/obd_ok', self._on_obd_ok, 10)
        self.create_subscription(String, '/system/mpc_state', self._on_mpc_state, 10)

        self.param_client = AsyncParametersClient(
            self,
            self.get_parameter('can_obd_node_name').value
        )

        self.timer = self.create_timer(1.0, self._step)
        self.get_logger().info('PreflightNode started.')

    def _on_config_ready(self, msg: Bool):
        self.config_ready = bool(msg.data)

    def _on_config_required(self, msg: Bool):
        self.config_required = bool(msg.data)

    def _on_obd_ok(self, msg: Float32):
        if float(msg.data) > 0.5:
            self.last_obd_time = time.monotonic()

    def _on_mpc_state(self, msg: String):
        self.mpc_state = str(msg.data)

    def _step(self):
        now = time.monotonic()
        iface_exists = os.path.exists(f'/sys/class/net/{self.can_interface}')
        if not iface_exists:
            self._update_state('DISCONNECTED', 'CAN interface not found', 0.0)
            self._publish()
            return

        if not self._is_iface_up():
            if self.manage_can and self._can_manage_iface():
                self._update_state('DISCONNECTED', 'CAN interface down (trying to configure)', 0.1)
                if now - self.last_probe_time > self.probe_interval_sec:
                    self.last_probe_time = now
                    self._try_bitrates()
            else:
                self._update_state('DISCONNECTED', 'CAN interface down (run setup_can.sh or enable manage_can_interface)', 0.1)
            self._publish()
            return

        if not self.profile_confirmed and (now - self.last_probe_time > self.probe_interval_sec):
            self.last_probe_time = now
            if self.manage_can and self._can_manage_iface():
                self._probe_obd_profile()
            else:
                self._probe_obd_profile(passive_only=True)
        if self.profile_confirmed and not self.params_pushed:
            self._push_can_profile()

        obd_ok = self._obd_ok()
        fuel_ok = (PID_FUEL_RATE in self.supported_pids) or (PID_MAF in self.supported_pids)

        if not self.profile_confirmed:
            self._update_state('CAN_OK', 'probing OBD profile', 0.2)
        elif not obd_ok:
            self._update_state('CAN_OK', 'no OBD response yet', 0.3)
        elif self.config_required or not self.config_ready:
            self._update_state('CONFIG_REQUIRED', 'wizard input required', 0.5)
        elif self.mpc_state == 'DEGRADED_RUN' or not fuel_ok:
            self._update_state('DEGRADED', 'fuel input degraded', 0.6)
        elif self.mpc_state == 'RUN':
            self._update_state('RUNNING', 'mpc running', 1.0)
        else:
            self._update_state('READY', 'inputs ready', 0.8)

        self._publish()

    def _update_state(self, state: str, diag: str, health: float):
        self.state = state
        self.diag = diag
        self.health = float(health)

    def _publish(self):
        self.pub_state.publish(String(data=str(self.state)))
        self.pub_health.publish(Float32(data=float(self.health)))
        self.pub_diag.publish(String(data=str(self.diag)))
        self.pub_can_profile.publish(String(data=str(self.can_profile)))
        self.pub_pid_profile.publish(String(data=str(self.pid_profile)))

    def _is_iface_up(self) -> bool:
        try:
            with open(f'/sys/class/net/{self.can_interface}/operstate', 'r', encoding='utf-8') as f:
                return f.read().strip() == 'up'
        except Exception:
            return False

    def _try_bitrates(self):
        for bitrate in self.bitrates:
            if self._set_bitrate(bitrate):
                self.can_profile = f'{self.can_interface}@{bitrate}'
                return

    def _set_bitrate(self, bitrate: int) -> bool:
        if not self.manage_can or not self._can_manage_iface():
            return False
        cmds = [
            ['ip', 'link', 'set', self.can_interface, 'down'],
            ['ip', 'link', 'set', self.can_interface, 'type', 'can', 'bitrate', str(bitrate), 'restart-ms', '100'],
            ['ip', 'link', 'set', self.can_interface, 'up'],
        ]
        for cmd in cmds:
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                return False
        return True

    def _probe_obd_profile(self, passive_only: bool = False):
        bitrates = self.bitrates if not passive_only else [None]
        for bitrate in bitrates:
            if bitrate is not None and not self._set_bitrate(bitrate):
                continue
            for use_ext, req_id in self._request_candidates():
                ok = self._test_obd(req_id, use_ext)
                if ok:
                    self.profile_confirmed = True
                    self.use_extended_id = use_ext
                    self.request_id = req_id
                    if bitrate is not None:
                        self.can_profile = f'{self.can_interface}@{bitrate},' + ('29bit' if use_ext else '11bit')
                    else:
                        self.can_profile = f'{self.can_interface}@unknown,' + ('29bit' if use_ext else '11bit')
                    self.supported_pids = self._scan_supported_pids(req_id, use_ext)
                    self.pid_profile = self._pid_profile_string()
                    self._push_can_profile()
                    return

    def _request_candidates(self) -> List[Tuple[bool, int]]:
        return [
            (False, STANDARD_REQ_ID),
            (True, EXTENDED_REQ_ID),
        ]

    def _test_obd(self, request_id: int, use_extended: bool) -> bool:
        try:
            bus = can.interface.Bus(channel=self.can_interface, bustype='socketcan')
        except Exception:
            return False
        msg = can.Message(
            arbitration_id=request_id,
            data=[0x02, 0x01, PID_SPEED, 0, 0, 0, 0, 0],
            is_extended_id=use_extended,
        )
        try:
            bus.send(msg)
        except Exception:
            bus.shutdown()
            return False

        deadline = time.time() + self.obd_timeout_sec
        ok = False
        while time.time() < deadline:
            resp = bus.recv(timeout=0.1)
            if resp is None:
                continue
            if resp.is_extended_id != use_extended:
                continue
            if not self._match_response_id(resp.arbitration_id, use_extended):
                continue
            data = list(resp.data)
            if len(data) >= 4 and data[1] == 0x41 and data[2] == PID_SPEED:
                ok = True
                self.last_obd_time = time.monotonic()
                break
        bus.shutdown()
        return ok

    def _scan_supported_pids(self, request_id: int, use_extended: bool):
        supported = set()
        for base in (PID_SUPPORT_00, PID_SUPPORT_20):
            mask = self._request_pid_mask(request_id, use_extended, base)
            if mask:
                supported |= self._decode_pid_mask(base, mask)
        return supported

    def _request_pid_mask(self, request_id: int, use_extended: bool, base: int) -> Optional[List[int]]:
        try:
            bus = can.interface.Bus(channel=self.can_interface, bustype='socketcan')
        except Exception:
            return None
        msg = can.Message(
            arbitration_id=request_id,
            data=[0x02, 0x01, base, 0, 0, 0, 0, 0],
            is_extended_id=use_extended,
        )
        try:
            bus.send(msg)
        except Exception:
            bus.shutdown()
            return None
        deadline = time.time() + self.obd_timeout_sec
        while time.time() < deadline:
            resp = bus.recv(timeout=0.1)
            if resp is None:
                continue
            if resp.is_extended_id != use_extended:
                continue
            if not self._match_response_id(resp.arbitration_id, use_extended):
                continue
            data = list(resp.data)
            if len(data) >= 7 and data[1] == 0x41 and data[2] == base:
                bus.shutdown()
                return data[3:7]
        bus.shutdown()
        return None

    def _decode_pid_mask(self, base: int, mask_bytes: List[int]):
        mask = (mask_bytes[0] << 24) | (mask_bytes[1] << 16) | (mask_bytes[2] << 8) | mask_bytes[3]
        pids = set()
        for i in range(32):
            if mask & (1 << (31 - i)):
                pids.add(base + i + 1)
        return pids

    def _pid_profile_string(self) -> str:
        speed_ok = PID_SPEED in self.supported_pids
        maf_ok = PID_MAF in self.supported_pids
        fuel_ok = PID_FUEL_RATE in self.supported_pids
        return f'0x0D:{int(speed_ok)} 0x10:{int(maf_ok)} 0x5E:{int(fuel_ok)}'

    def _match_response_id(self, arb_id: int, use_extended: bool) -> bool:
        if use_extended:
            return (arb_id & EXTENDED_RESP_MASK) == EXTENDED_RESP_VALUE
        return 0x7E8 <= arb_id <= 0x7EF

    def _can_manage_iface(self) -> bool:
        try:
            return os.geteuid() == 0
        except Exception:
            return False

    def _push_can_profile(self):
        if not self.param_client.service_is_ready():
            return
        params = [
            Parameter('use_extended_id', Parameter.Type.BOOL, self.use_extended_id),
            Parameter('request_id', Parameter.Type.INTEGER, int(self.request_id)),
            Parameter('pid_allowlist', Parameter.Type.INTEGER_ARRAY, sorted(list(self.supported_pids))),
            Parameter('enabled', Parameter.Type.BOOL, True),
        ]
        self.param_client.set_parameters(params)
        self.params_pushed = True

    def _obd_ok(self) -> bool:
        if self.last_obd_time is None:
            return False
        return (time.monotonic() - self.last_obd_time) <= self.max_no_response_sec


def main():
    rclpy.init()
    node = PreflightNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
