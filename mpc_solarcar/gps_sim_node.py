import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import Float32
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


class GPSSimNode(Node):                                            # [クラス定義] GPSSimNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
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
        self.pub_gps = self.create_publisher(NavSatFix, '/sim/gps', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.sub_speed = self.create_subscription(Float32, '/planner/speed_cmd', self.on_speed, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.timer = self.create_timer(1.0/self.dt, self.step)
        self.get_logger().info('GPSSimNode started.')
    def on_speed(self, msg: Float32):                              # [関数定義] on_speed の処理実行ブロック
        self.speed_kmh = float(msg.data)
    def step(self):                                                # [関数定義] step の処理実行ブロック
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
def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = GPSSimNode()
    rclpy.spin(node); node.destroy_node(); rclpy.shutdown()