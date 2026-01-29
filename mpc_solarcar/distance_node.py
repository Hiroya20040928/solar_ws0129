import math

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32
from std_srvs.srv import Trigger


class DistanceNode(Node):
    def __init__(self):
        super().__init__('distance_node')
        self.declare_parameter('max_dt_sec', 2.5)
        self.declare_parameter('publish_rate_hz', 1.0)

        self.max_dt_sec = float(self.get_parameter('max_dt_sec').value)
        publish_rate_hz = float(self.get_parameter('publish_rate_hz').value)

        self.s_km = 0.0
        self.last_time = None
        self.last_speed = math.nan

        self.sub_speed = self.create_subscription(Float32, '/vehicle/speed_kmh', self._on_speed, 10)
        self.pub_s = self.create_publisher(Float32, '/vehicle/s_km', 10)
        self.srv_reset = self.create_service(Trigger, '/vehicle/reset_odometry', self._on_reset)

        self.timer = self.create_timer(1.0 / publish_rate_hz, self._publish)
        self.get_logger().info('DistanceNode started.')

    def _on_speed(self, msg: Float32):
        v_kmh = float(msg.data)
        now_sec = self.get_clock().now().nanoseconds / 1e9
        if self.last_time is not None and math.isfinite(self.last_speed) and math.isfinite(v_kmh):
            dt = now_sec - self.last_time
            if 0.0 < dt <= self.max_dt_sec:
                v_avg = 0.5 * (self.last_speed + v_kmh)
                self.s_km += v_avg * (dt / 3600.0)
        self.last_time = now_sec
        self.last_speed = v_kmh

    def _on_reset(self, request, response):
        self.s_km = 0.0
        self.last_time = None
        self.last_speed = math.nan
        response.success = True
        response.message = 'odometry reset'
        return response

    def _publish(self):
        msg = Float32()
        msg.data = float(self.s_km)
        self.pub_s.publish(msg)


def main():
    rclpy.init()
    node = DistanceNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

