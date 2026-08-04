import math
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String
import yaml


class ThrottleAdvisoryNode(Node):
    def __init__(self):
        super().__init__('throttle_advisory_node')
        self.declare_parameter('throttle_kp', 0.8)
        self.declare_parameter('throttle_kff', 0.02)
        self.declare_parameter('throttle_min', 0.0)
        self.declare_parameter('throttle_max', 100.0)
        self.declare_parameter('low_speed_kmh', 2.0)
        self.declare_parameter('rate_limit_pct_per_s', 20.0)

        self.throttle_kp = float(self.get_parameter('throttle_kp').value)
        self.throttle_kff = float(self.get_parameter('throttle_kff').value)
        self.throttle_min = float(self.get_parameter('throttle_min').value)
        self.throttle_max = float(self.get_parameter('throttle_max').value)
        self.low_speed_kmh = float(self.get_parameter('low_speed_kmh').value)
        self.rate_limit = float(self.get_parameter('rate_limit_pct_per_s').value)

        self.v_now = math.nan
        self.v_cmd = math.nan
        self.throttle_now = math.nan
        self.obd_ok = 0.0
        self.last_cmd = math.nan
        self.last_time = time.monotonic()

        self.create_subscription(Float32, '/vehicle/speed_kmh', self._on_speed, 10)
        self.create_subscription(Float32, '/planner/speed_cmd', self._on_speed_cmd, 10)
        self.create_subscription(Float32, '/vehicle/throttle_pct', self._on_throttle, 10)
        self.create_subscription(Float32, '/vehicle/obd_ok', self._on_obd_ok, 10)
        self.create_subscription(String, '/system/config', self._on_config, 10)

        self.pub_throttle = self.create_publisher(Float32, '/planner/throttle_cmd_pct', 10)

        self.timer = self.create_timer(1.0, self._step)
        self.get_logger().info('ThrottleAdvisoryNode started.')

    def _on_speed(self, msg: Float32):
        self.v_now = float(msg.data)

    def _on_speed_cmd(self, msg: Float32):
        self.v_cmd = float(msg.data)

    def _on_throttle(self, msg: Float32):
        self.throttle_now = float(msg.data)

    def _on_obd_ok(self, msg: Float32):
        self.obd_ok = float(msg.data)

    def _on_config(self, msg: String):
        try:
            cfg = yaml.safe_load(msg.data) or {}
        except Exception:
            return
        if 'throttle_kp' in cfg:
            self.throttle_kp = float(cfg['throttle_kp'])
        if 'throttle_kff' in cfg:
            self.throttle_kff = float(cfg['throttle_kff'])

    def _step(self):
        if not math.isfinite(self.v_cmd):
            return
        v_now = self.v_now if math.isfinite(self.v_now) else 0.0
        base = self.throttle_now if math.isfinite(self.throttle_now) else 0.0
        err = self.v_cmd - v_now
        cmd = base + self.throttle_kp * err + self.throttle_kff * self.v_cmd

        if self.v_cmd <= self.low_speed_kmh:
            cmd = min(cmd, 5.0)
        if self.obd_ok < 0.5:
            cmd *= 0.8

        cmd = max(self.throttle_min, min(self.throttle_max, cmd))

        now = time.monotonic()
        dt = max(0.0, now - self.last_time)
        self.last_time = now
        if math.isfinite(self.last_cmd) and self.rate_limit > 0.0 and dt > 0.0:
            max_delta = self.rate_limit * dt
            cmd = max(self.last_cmd - max_delta, min(self.last_cmd + max_delta, cmd))

        self.last_cmd = cmd
        self.pub_throttle.publish(Float32(data=float(cmd)))


def main():
    rclpy.init()
    node = ThrottleAdvisoryNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

