import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from std_msgs.msg import Float32
from std_srvs.srv import Trigger


class DistanceNode(Node):                                          # [クラス定義] DistanceNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('distance_node')
        self.declare_parameter('max_dt_sec', 2.5)
        self.declare_parameter('publish_rate_hz', 1.0)

        self.max_dt_sec = float(self.get_parameter('max_dt_sec').value)
        publish_rate_hz = float(self.get_parameter('publish_rate_hz').value)

        self.s_km = 0.0
        self.last_time = None
        self.last_speed = math.nan

        self.sub_speed = self.create_subscription(Float32, '/vehicle/speed_kmh', self._on_speed, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.pub_s = self.create_publisher(Float32, '/vehicle/s_km', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.srv_reset = self.create_service(Trigger, '/vehicle/reset_odometry', self._on_reset)

        self.timer = self.create_timer(1.0 / publish_rate_hz, self._publish)
        self.get_logger().info('DistanceNode started.')

    def _on_speed(self, msg: Float32):                             # [関数定義] _on_speed の処理実行ブロック
        v_kmh = float(msg.data)
        now_sec = self.get_clock().now().nanoseconds / 1e9
        if self.last_time is not None and math.isfinite(self.last_speed) and math.isfinite(v_kmh):
            dt = now_sec - self.last_time
            if 0.0 < dt <= self.max_dt_sec:
                v_avg = 0.5 * (self.last_speed + v_kmh)
                self.s_km += v_avg * (dt / 3600.0)
        self.last_time = now_sec
        self.last_speed = v_kmh

    def _on_reset(self, request, response):                        # [関数定義] _on_reset の処理実行ブロック
        self.s_km = 0.0
        self.last_time = None
        self.last_speed = math.nan
        response.success = True
        response.message = 'odometry reset'
        return response                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _publish(self):                                            # [関数定義] _publish の処理実行ブロック
        msg = Float32()
        msg.data = float(self.s_km)
        self.pub_s.publish(msg)


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = DistanceNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()