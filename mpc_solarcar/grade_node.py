import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import time

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from std_msgs.msg import Float32
from sensor_msgs.msg import NavSatFix


class GradeNode(Node):                                             # [クラス定義] GradeNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('grade_node')
        self.declare_parameter('min_speed_kmh', 5.0)
        self.declare_parameter('altitude_alpha', 0.2)
        self.declare_parameter('min_delta_s_km', 0.01)
        self.declare_parameter('gps_topic', '/sim/gps')
        self.declare_parameter('altitude_topic', '/vehicle/altitude_m')

        self.min_speed_kmh = float(self.get_parameter('min_speed_kmh').value)
        self.alpha = float(self.get_parameter('altitude_alpha').value)
        self.min_delta_s_km = float(self.get_parameter('min_delta_s_km').value)
        self.gps_topic = self.get_parameter('gps_topic').value
        self.altitude_topic = self.get_parameter('altitude_topic').value

        self.altitude_m = math.nan
        self.altitude_ema = math.nan
        self.s_km = math.nan
        self.speed_kmh = math.nan
        self.last_s_km = None
        self.last_alt_ema = None
        self.grade = math.nan
        self.last_update = time.monotonic()

        self.create_subscription(Float32, '/vehicle/s_km', self._on_s_km, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/speed_kmh', self._on_speed, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, self.altitude_topic, self._on_altitude, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(NavSatFix, self.gps_topic, self._on_gps, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        self.pub_grade = self.create_publisher(Float32, '/vehicle/grade', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.timer = self.create_timer(1.0, self._step)
        self.get_logger().info('GradeNode started.')

    def _on_s_km(self, msg: Float32):                              # [関数定義] _on_s_km の処理実行ブロック
        self.s_km = float(msg.data)

    def _on_speed(self, msg: Float32):                             # [関数定義] _on_speed の処理実行ブロック
        self.speed_kmh = float(msg.data)

    def _on_altitude(self, msg: Float32):                          # [関数定義] _on_altitude の処理実行ブロック
        self._update_altitude(float(msg.data))

    def _on_gps(self, msg: NavSatFix):                             # [関数定義] _on_gps の処理実行ブロック
        if math.isfinite(msg.altitude):
            self._update_altitude(float(msg.altitude))

    def _update_altitude(self, altitude_m: float):                 # [関数定義] _update_altitude の処理実行ブロック
        self.altitude_m = altitude_m
        if not math.isfinite(self.altitude_ema):
            self.altitude_ema = altitude_m
        else:
            self.altitude_ema = self.alpha * altitude_m + (1.0 - self.alpha) * self.altitude_ema

    def _step(self):                                               # [関数定義] _step の処理実行ブロック
        if not math.isfinite(self.s_km) or not math.isfinite(self.altitude_ema):
            self.pub_grade.publish(Float32(data=math.nan))
            return
        if not math.isfinite(self.speed_kmh) or self.speed_kmh < self.min_speed_kmh:
            self.pub_grade.publish(Float32(data=self.grade if math.isfinite(self.grade) else math.nan))
            return
        if self.last_s_km is None or self.last_alt_ema is None:
            self.last_s_km = self.s_km
            self.last_alt_ema = self.altitude_ema
            self.pub_grade.publish(Float32(data=math.nan))
            return

        delta_s_km = self.s_km - self.last_s_km
        if delta_s_km < self.min_delta_s_km:
            self.pub_grade.publish(Float32(data=self.grade if math.isfinite(self.grade) else math.nan))
            return

        delta_alt = self.altitude_ema - self.last_alt_ema
        grade = delta_alt / (delta_s_km * 1000.0)
        self.grade = float(grade)
        self.last_s_km = self.s_km
        self.last_alt_ema = self.altitude_ema
        self.pub_grade.publish(Float32(data=self.grade))


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = GradeNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()