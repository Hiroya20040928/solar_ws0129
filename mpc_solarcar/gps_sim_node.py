import rclpy
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import Float32
import pandas as pd

from .route_utils import interpolate_route_with_alt
from .path_utils import resolve_path

class GPSSimNode(Node):
    def __init__(self):
        super().__init__('gps_sim_node')
        self.declare_parameter('route_csv', 'inputs/route_waypoints.csv')
        self.declare_parameter('dt', 1.0)  # Hz
        self.declare_parameter('init_speed_kmh', 40.0)
        route_csv = self.get_parameter('route_csv').value
        route_csv = resolve_path(route_csv, 'inputs')
        self.route = pd.read_csv(route_csv)
        self.dt = float(self.get_parameter('dt').value)
        self.speed_kmh = float(self.get_parameter('init_speed_kmh').value)
        self.s_km = float(self.route['dist_km'].iloc[0])
        self.pub_gps = self.create_publisher(NavSatFix, '/sim/gps', 10)
        self.sub_speed = self.create_subscription(Float32, '/planner/speed_cmd', self.on_speed, 10)
        self.timer = self.create_timer(1.0/self.dt, self.step)
        self.get_logger().info('GPSSimNode started.')
    def on_speed(self, msg: Float32):
        self.speed_kmh = float(msg.data)
    def step(self):
        # advance along route based on commanded speed
        self.s_km += (self.speed_kmh/3.6)*(1.0/self.dt)/1000.0  # km
        lat, lon, alt = interpolate_route_with_alt(self.route, self.s_km)
        msg = NavSatFix()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.latitude = lat
        msg.longitude = lon
        if alt is not None:
            msg.altitude = float(alt)
        else:
            msg.altitude = 0.0
        self.pub_gps.publish(msg)
def main():
    rclpy.init()
    node = GPSSimNode()
    rclpy.spin(node); node.destroy_node(); rclpy.shutdown()
