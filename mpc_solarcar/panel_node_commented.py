import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import os
import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from std_msgs.msg import Float32, Float32MultiArray, String
from nav_msgs.msg import Path
from sensor_msgs.msg import NavSatFix
import matplotlib.pyplot as plt
import threading, collections, time

class PanelNode(Node):                                             # [クラス定義] PanelNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('panel_node')
        self.declare_parameter('headless', False)
        self.declare_parameter('save_dir', '')
        self.declare_parameter('save_interval_sec', 30.0)
        self.headless = bool(self.get_parameter('headless').value) or not bool(os.environ.get('DISPLAY'))
        self.save_dir = str(self.get_parameter('save_dir').value)
        self.save_interval = float(self.get_parameter('save_interval_sec').value)
        if self.headless:
            import matplotlib
            matplotlib.use('Agg')
        self.sub_speed = self.create_subscription(Float32, '/planner/speed_cmd', self.on_speed, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.sub_throttle = self.create_subscription(Float32, '/planner/throttle_cmd_pct', self.on_throttle, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.sub_path = self.create_subscription(Path, '/planner/trajectory', self.on_path, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.sub_gps = self.create_subscription(NavSatFix, '/sim/gps', self.on_gps, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.sub_state = self.create_subscription(String, '/system/state', self.on_state, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.sub_diag = self.create_subscription(String, '/system/diag', self.on_diag, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.sub_idle = self.create_subscription(Float32, '/vehicle/idle_fuel_lph', self.on_idle, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.sub_grade = self.create_subscription(Float32, '/vehicle/grade', self.on_grade, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.sub_status = self.create_subscription(Float32MultiArray, '/planner/status', self.on_status, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.speeds = collections.deque(maxlen=600)
        self.throttles = collections.deque(maxlen=600)
        self.throttle_times = collections.deque(maxlen=600)
        self.times = collections.deque(maxlen=600)
        self.latlon = collections.deque(maxlen=2000)
        self.path_x = []
        self.system_state = 'INIT'
        self.system_diag = ''
        self.idle_fuel = float('nan')
        self.grade = float('nan')
        self.id_rmse = float('nan')
        self.id_r2 = float('nan')
        self.fig, (self.ax1, self.ax2, self.ax3) = plt.subplots(3, 1, figsize=(8, 10))
        self.ax1.set_title('Commanded speed [km/h]'); self.ax1.set_ylabel('km/h')
        self.ax2.set_title('Advisory throttle [%]'); self.ax2.set_ylabel('%')
        self.ax3.set_title('GPS track (lat, lon)'); self.ax3.set_xlabel('lon'); self.ax3.set_ylabel('lat')
        self.line1, = self.ax1.plot([], [])
        self.line2, = self.ax2.plot([], [])
        self.scat, = self.ax3.plot([], [], '.', markersize=2)
        if not self.headless:
            self.thread = threading.Thread(target=self._ui_loop, daemon=True); self.thread.start()
            self.get_logger().info('PanelNode started (Matplotlib UI).')
        else:
            if self.save_dir:
                os.makedirs(self.save_dir, exist_ok=True)
            if self.save_interval > 0:
                self.timer = self.create_timer(self.save_interval, self._save_plot)
            self.get_logger().info('PanelNode started (headless).')
    def _ui_loop(self):                                            # [関数定義] _ui_loop の処理実行ブロック
        plt.ion()
        while rclpy.ok():
            if self.times:
                self.line1.set_data(self.times, self.speeds); self.ax1.relim(); self.ax1.autoscale_view()
            if self.throttle_times:
                self.line2.set_data(self.throttle_times, self.throttles); self.ax2.relim(); self.ax2.autoscale_view()
            if self.latlon:
                xs=[lon for (lat,lon) in self.latlon]; ys=[lat for (lat,lon) in self.latlon]
                self.scat.set_data(xs,ys); self.ax3.relim(); self.ax3.autoscale_view()
            self.fig.suptitle(self._status_text())
            plt.pause(0.05)
    def _save_plot(self):                                          # [関数定義] _save_plot の処理実行ブロック
        if not self.save_dir:
            return
        self._render_plot()
        out = os.path.join(self.save_dir, 'panel_snapshot.png')
        self.fig.savefig(out)

    def _render_plot(self):                                        # [関数定義] _render_plot の処理実行ブロック
        if self.times:
            self.line1.set_data(self.times, self.speeds); self.ax1.relim(); self.ax1.autoscale_view()
        if self.throttle_times:
            self.line2.set_data(self.throttle_times, self.throttles); self.ax2.relim(); self.ax2.autoscale_view()
        if self.latlon:
            xs=[lon for (lat,lon) in self.latlon]; ys=[lat for (lat,lon) in self.latlon]
            self.scat.set_data(xs, ys); self.ax3.relim(); self.ax3.autoscale_view()
        self.fig.suptitle(self._status_text())
    def on_speed(self, msg: Float32):                              # [関数定義] on_speed の処理実行ブロック
        self.speeds.append(float(msg.data)); self.times.append(time.time())
    def on_throttle(self, msg: Float32):                           # [関数定義] on_throttle の処理実行ブロック
        self.throttles.append(float(msg.data)); self.throttle_times.append(time.time())
    def on_path(self, msg: Path):                                  # [関数定義] on_path の処理実行ブロック
        self.path_x = [pose.pose.position.x for pose in msg.poses]
    def on_gps(self, msg: NavSatFix):                              # [関数定義] on_gps の処理実行ブロック
        self.latlon.append((msg.latitude, msg.longitude))
    def on_state(self, msg: String):                               # [関数定義] on_state の処理実行ブロック
        self.system_state = str(msg.data)
    def on_diag(self, msg: String):                                # [関数定義] on_diag の処理実行ブロック
        self.system_diag = str(msg.data)
    def on_idle(self, msg: Float32):                               # [関数定義] on_idle の処理実行ブロック
        self.idle_fuel = float(msg.data)
    def on_grade(self, msg: Float32):                              # [関数定義] on_grade の処理実行ブロック
        self.grade = float(msg.data)
    def on_status(self, msg: Float32MultiArray):                   # [関数定義] on_status の処理実行ブロック
        if len(msg.data) >= 7:
            self.id_rmse = float(msg.data[5])
            self.id_r2 = float(msg.data[6])

    def _status_text(self):                                        # [関数定義] _status_text の処理実行ブロック
        idle_str = f'{self.idle_fuel:.2f}' if math.isfinite(self.idle_fuel) else 'NA'
        grade_str = f'{self.grade:.3f}' if math.isfinite(self.grade) else 'NA'
        rmse_str = f'{self.id_rmse:.2f}' if math.isfinite(self.id_rmse) else 'NA'
        r2_str = f'{self.id_r2:.2f}' if math.isfinite(self.id_r2) else 'NA'
        return (f'State: {self.system_state} | {self.system_diag} | '  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                f'idle_fuel:{idle_str} L/h | grade:{grade_str} | RMSE:{rmse_str} R2:{r2_str}')
def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = PanelNode()
    rclpy.spin(node); node.destroy_node(); rclpy.shutdown()
