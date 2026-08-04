import time

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート

from std_msgs.msg import Float32, Float32MultiArray, String


class SolarStateNode(Node):                                        # [状態推定ノード] バッテリーSoC・電圧・過渡分極(V1)の状態推定ノード
    """Mirror planner outputs into vehicle/system topics for solar-only simulation."""

    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('solar_state_node')
        self.declare_parameter('publish_rate_hz', 5.0)
        self.declare_parameter('stale_timeout_sec', 5.0)

        self.speed_cmd_kmh = 0.0
        self.speed_meas_kmh = 0.0
        self.throttle_pct = 0.0
        self.drive_mode = 'auto'
        self.soc = 0.80
        self.tb_c = 25.0
        self.s_km = 0.0
        self.status_s_km = 0.0
        self.batt_current_a = 0.0
        self.batt_voltage_v = 0.0
        self.forecast_k = 0.0
        self.sec_to_next = 0.0
        self.has_status = False
        self.has_metrics = False
        self.last_status_time = 0.0
        self.last_metrics_time = 0.0
        self.last_lower_plan_time = 0.0
        self.last_publish_time = time.monotonic()

        self.pub_speed = self.create_publisher(Float32, '/vehicle/speed_kmh', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_s_km = self.create_publisher(Float32, '/vehicle/s_km', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_soc = self.create_publisher(Float32, '/vehicle/batt_soc', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_tb = self.create_publisher(Float32, '/vehicle/batt_temp_c', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_ibatt = self.create_publisher(Float32, '/vehicle/batt_current_a', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vbatt = self.create_publisher(Float32, '/vehicle/batt_voltage_v', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_throttle = self.create_publisher(Float32, '/vehicle/throttle_pct', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_state = self.create_publisher(String, '/system/state', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_diag = self.create_publisher(String, '/system/diag', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_mpc_state = self.create_publisher(String, '/system/mpc_state', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_health = self.create_publisher(Float32, '/system/health', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        self.create_subscription(Float32, '/planner/speed_cmd', self._on_speed_cmd, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/planner/throttle_cmd_pct', self._on_throttle, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/planner/drive_mode', self._on_drive_mode, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/status', self._on_status, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/metrics', self._on_metrics, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/lower_plan', self._on_lower_plan, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        period = 1.0 / max(0.5, float(self.get_parameter('publish_rate_hz').value))
        self.timer = self.create_timer(period, self._publish)
        self.get_logger().info('SolarStateNode started.')

    def _on_speed_cmd(self, msg: Float32):                         # [関数定義] _on_speed_cmd の処理実行ブロック
        self.speed_cmd_kmh = float(msg.data)
        self.speed_meas_kmh = float(msg.data)

    def _on_throttle(self, msg: Float32):                          # [関数定義] _on_throttle の処理実行ブロック
        self.throttle_pct = float(msg.data)

    def _on_drive_mode(self, msg: String):                         # [関数定義] _on_drive_mode の処理実行ブロック
        self.drive_mode = str(msg.data)

    def _on_status(self, msg: Float32MultiArray):                  # [関数定義] _on_status の処理実行ブロック
        data = list(msg.data)
        if len(data) < 5:
            return
        self.soc = float(data[0])
        self.tb_c = float(data[1])
        self.status_s_km = float(data[2])
        if not self.has_status:
            self.s_km = float(data[2])
        self.forecast_k = float(data[3])
        self.sec_to_next = float(data[4])
        self.has_status = True
        self.last_status_time = time.monotonic()

    def _on_metrics(self, msg: Float32MultiArray):                 # [関数定義] _on_metrics の処理実行ブロック
        data = list(msg.data)
        if len(data) < 7:
            return
        self.batt_voltage_v = float(data[0])
        self.batt_current_a = float(data[1])
        self.soc = float(data[2])
        self.speed_cmd_kmh = float(data[6])
        self.speed_meas_kmh = float(data[6])
        self.has_metrics = True
        self.last_metrics_time = time.monotonic()

    def _on_lower_plan(self, msg: Float32MultiArray):              # [関数定義] _on_lower_plan の処理実行ブロック
        if len(msg.data) > 1:
            self.last_lower_plan_time = time.monotonic()

    def _publish(self):                                            # [関数定義] _publish の処理実行ブロック
        now = time.monotonic()
        dt = max(0.0, now - self.last_publish_time)
        self.last_publish_time = now
        stale_timeout = max(1.0, float(self.get_parameter('stale_timeout_sec').value))
        status_age = now - self.last_status_time if self.has_status else float('inf')
        metrics_age = now - self.last_metrics_time if self.has_metrics else float('inf')
        healthy = status_age <= stale_timeout and metrics_age <= stale_timeout

        self.s_km = max(self.s_km, self.status_s_km)
        self.s_km += float(self.speed_meas_kmh) * (dt / 3600.0)

        self.pub_speed.publish(Float32(data=float(self.speed_meas_kmh)))
        self.pub_s_km.publish(Float32(data=float(self.s_km)))
        self.pub_soc.publish(Float32(data=float(self.soc)))
        self.pub_tb.publish(Float32(data=float(self.tb_c)))
        self.pub_ibatt.publish(Float32(data=float(self.batt_current_a)))
        self.pub_vbatt.publish(Float32(data=float(self.batt_voltage_v)))
        self.pub_throttle.publish(Float32(data=float(self.throttle_pct)))

        if not self.has_status:
            state = 'STARTING'
        elif healthy:
            state = 'RUNNING'
        else:
            state = 'STALE'

        if healthy:
            diag = f'forecast_k={self.forecast_k:.0f}, next={self.sec_to_next:.0f}s'
        elif self.has_status or self.has_metrics:
            diag = 'planner topics became stale'
        else:
            diag = 'waiting for planner topics'

        if self.last_lower_plan_time > 0.0 and (now - self.last_lower_plan_time) <= stale_timeout:
            mpc_state = 'HIERARCHICAL'
        else:
            mpc_state = 'UPPER_ONLY'

        health = 1.0 if healthy else (0.5 if self.has_status or self.has_metrics else 0.0)
        self.pub_state.publish(String(data=state))
        self.pub_diag.publish(String(data=diag))
        self.pub_mpc_state.publish(String(data=mpc_state))
        self.pub_health.publish(Float32(data=float(health)))


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = SolarStateNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':                                         # [直接実行スクリプト] スクリプト直接起動時のメイン実行ブロック
    main()
