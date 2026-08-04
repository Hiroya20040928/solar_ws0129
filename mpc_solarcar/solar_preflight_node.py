from __future__ import annotations

import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, Float32MultiArray, String

from .solar_preflight_logic import evaluate_freshness


class SolarPreflightNode(Node):
    """Preflight monitor based only on solar-car telemetry freshness."""

    def __init__(self):
        super().__init__("solar_preflight_node")
        self.declare_parameter("startup_grace_sec", 10.0)
        self.declare_parameter("measurement_timeout_sec", 3.0)
        self.declare_parameter("require_speed", True)
        self.declare_parameter("require_distance", True)
        self.declare_parameter("require_battery", True)
        self.declare_parameter("require_planner", True)

        self.start_mono = time.monotonic()
        self.last_seen: dict[str, float] = {}

        self.pub_state = self.create_publisher(String, "/system/state", 10)
        self.pub_health = self.create_publisher(Float32, "/system/health", 10)
        self.pub_diag = self.create_publisher(String, "/system/diag", 10)

        self.create_subscription(Float32, "/vehicle/speed_kmh", self._seen("speed"), 10)
        self.create_subscription(Float32, "/vehicle/s_km", self._seen("distance"), 10)
        self.create_subscription(Float32, "/vehicle/batt_soc", self._seen("batt_soc"), 10)
        self.create_subscription(Float32, "/vehicle/batt_voltage_v", self._seen("batt_voltage"), 10)
        self.create_subscription(Float32, "/vehicle/batt_current_a", self._seen("batt_current"), 10)
        self.create_subscription(Float32MultiArray, "/planner/status", self._seen("planner"), 10)

        self.timer = self.create_timer(1.0, self._step)
        self.get_logger().info("SolarPreflightNode started.")

    def _seen(self, key: str):
        def callback(_msg):
            self.last_seen[key] = time.monotonic()

        return callback

    def _required(self) -> tuple[str, ...]:
        required: list[str] = []
        if bool(self.get_parameter("require_speed").value):
            required.append("speed")
        if bool(self.get_parameter("require_distance").value):
            required.append("distance")
        if bool(self.get_parameter("require_battery").value):
            required.extend(("batt_soc", "batt_voltage", "batt_current"))
        if bool(self.get_parameter("require_planner").value):
            required.append("planner")
        return tuple(required)

    def _step(self):
        now = time.monotonic()
        required = self._required()
        ages = {
            key: (now - self.last_seen[key]) if key in self.last_seen else None
            for key in required
        }
        result = evaluate_freshness(
            elapsed_sec=now - self.start_mono,
            ages_sec=ages,
            required=required,
            timeout_sec=float(self.get_parameter("measurement_timeout_sec").value),
            startup_grace_sec=float(self.get_parameter("startup_grace_sec").value),
        )
        self.pub_state.publish(String(data=result.state))
        self.pub_health.publish(Float32(data=float(result.health)))
        self.pub_diag.publish(String(data=result.diagnostic))


def main():
    rclpy.init()
    node = SolarPreflightNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
