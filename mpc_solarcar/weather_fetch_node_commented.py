import os
from datetime import datetime, timezone

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import String

from .path_utils import resolve_path
from .weather_utils import fetch_openmeteo_forecast, write_forecast_csv


class WeatherFetchNode(Node):                                      # [クラス定義] WeatherFetchNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('weather_fetch_node')
        self.declare_parameter('provider', 'openmeteo')
        self.declare_parameter('forecast_csv', 'data/weather/live_forecast.csv')
        self.declare_parameter('gps_topic', '/chase/gps')
        self.declare_parameter('fetch_period_sec', 3600.0)
        self.declare_parameter('forecast_days', 3)
        self.declare_parameter('step_minutes', 10)
        self.declare_parameter('timezone_name', 'Australia/Darwin')
        self.declare_parameter('fallback_latitude', -12.4634)
        self.declare_parameter('fallback_longitude', 130.8456)
        self.declare_parameter('tcell_gain', 0.03)

        self.provider = str(self.get_parameter('provider').value).lower()
        self.forecast_csv = resolve_path(self.get_parameter('forecast_csv').value)
        self.fetch_period_sec = float(self.get_parameter('fetch_period_sec').value)
        self.forecast_days = int(self.get_parameter('forecast_days').value)
        self.step_minutes = int(self.get_parameter('step_minutes').value)
        self.timezone_name = str(self.get_parameter('timezone_name').value)
        self.tcell_gain = float(self.get_parameter('tcell_gain').value)
        self.lat = float(self.get_parameter('fallback_latitude').value)
        self.lon = float(self.get_parameter('fallback_longitude').value)
        self.has_gps = False
        self.last_status = 'waiting for first fetch'

        gps_topic = str(self.get_parameter('gps_topic').value)
        self.create_subscription(NavSatFix, gps_topic, self._on_gps, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.pub_status = self.create_publisher(String, '/system/forecast_status', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        os.makedirs(os.path.dirname(os.path.abspath(self.forecast_csv)), exist_ok=True)
        self._fetch_once()
        self.timer = self.create_timer(max(60.0, self.fetch_period_sec), self._fetch_once)
        self.get_logger().info(f'WeatherFetchNode started: provider={self.provider}, out={self.forecast_csv}')

    def _on_gps(self, msg: NavSatFix):                             # [関数定義] _on_gps の処理実行ブロック
        if msg.latitude == 0.0 and msg.longitude == 0.0:
            return
        self.lat = float(msg.latitude)
        self.lon = float(msg.longitude)
        self.has_gps = True

    def _fetch_once(self):                                         # [関数定義] _fetch_once の処理実行ブロック
        if self.provider != 'openmeteo':
            self.last_status = f'provider={self.provider} not implemented'
            self.pub_status.publish(String(data=self.last_status))
            return
        try:
            df = fetch_openmeteo_forecast(
                self.lat,
                self.lon,
                timezone_name=self.timezone_name,
                forecast_days=self.forecast_days,
                step_minutes=self.step_minutes,
                tcell_gain=self.tcell_gain,
            )
            write_forecast_csv(df, self.forecast_csv)
            stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            src = 'gps' if self.has_gps else 'fallback'
            self.last_status = f'openmeteo {stamp} lat={self.lat:.5f} lon={self.lon:.5f} src={src} rows={len(df)}'
            self.get_logger().info(self.last_status)
        except Exception as exc:
            self.last_status = f'forecast fetch failed: {exc}'
            self.get_logger().warn(self.last_status)
        self.pub_status.publish(String(data=self.last_status))


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = WeatherFetchNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
