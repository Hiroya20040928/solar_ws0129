import csv
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import os
from datetime import datetime, timezone

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from std_msgs.msg import Float32, Float32MultiArray, Float64, String


FLOAT_TOPICS = {
    "speed_kmh": "/vehicle/speed_kmh",
    "s_km": "/vehicle/s_km",
    "altitude_m": "/vehicle/altitude_m",
    "grade_pct": "/vehicle/grade",
    "batt_soc": "/vehicle/batt_soc",
    "batt_temp_c": "/vehicle/batt_temp_c",
    "batt_current_a": "/vehicle/batt_current_a",
    "batt_voltage_v": "/vehicle/batt_voltage_v",
    "solar_power_w": "/vehicle/solar_power_w",
    "headwind_meas_ms": "/weather/headwind_meas_ms",
    "headwind_corrected_ms": "/weather/headwind_corrected_ms",
    "wind_speed_ms": "/weather/wind_speed_ms",
    "wind_dir_deg": "/weather/wind_dir_deg",
    "course_deg": "/weather/course_deg",
    "speed_cmd_kmh": "/planner/speed_cmd",
    "upper_speed_cmd_kmh": "/planner/upper_speed_cmd",
    "throttle_cmd_pct": "/planner/throttle_cmd_pct",
    "calib_solar_gain": "/calib/solar_gain",
    "calib_drive_power_gain": "/calib/drive_power_gain",
    "calib_aux_power_w": "/calib/aux_power_w",
    "system_health": "/system/health",
}

FLOAT64_TOPICS = {
    "solar_source_ts_unix": "/telemetry/solar_source_ts_unix",
    "chase_source_ts_unix": "/telemetry/chase_source_ts_unix",
}

STRING_TOPICS = {
    "drive_mode": "/planner/drive_mode",
    "system_state": "/system/state",
    "system_diag": "/system/diag",
    "mpc_state": "/system/mpc_state",
    "telemetry_bridge_status": "/telemetry/bridge_status",
    "wind_correction_status": "/weather/wind_correction_status",
    "weather_fetch_status": "/weather/fetch_status",
    "autocal_status": "/calib/status",
    "raw_solar": "/telemetry/raw_solar",
    "raw_chase": "/telemetry/raw_chase",
}

ARRAY_TOPICS = {
    "/planner/status": [
        "planner_soc",
        "planner_temp_c",
        "planner_s_km",
        "planner_step",
        "planner_sec_to_next",
        "planner_control_stop_hold",
        "planner_control_stop_remaining_sec",
        "planner_control_stop_completed_count",
    ],
    "/planner/metrics": [
        "model_pack_voltage_v",
        "model_pack_current_a",
        "model_soc",
        "model_motor_power_w",
        "model_motor_current_a",
        "model_pv_power_w",
        "model_speed_kmh",
        "model_mech_power_w",
        "model_pack_power_w",
    ],
    "/planner/env": [
        "env_poa_wm2",
        "env_cell_temp_c",
        "env_ambient_temp_c",
        "env_grade_pct",
        "env_headwind_ms",
    ],
}


class SolarLoggerNode(Node):                                       # [クラス定義] SolarLoggerNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__("solar_logger_node")
        self.declare_parameter("log_dir", "outputs/logs")
        self.declare_parameter("file_prefix", "solar_live")
        self.declare_parameter("log_rate_hz", 2.0)
        self.declare_parameter("flush_every_rows", 1)
        self.declare_parameter("output_speed_topic", "/vehicle/speed_cmd_kmh")
        self.declare_parameter("output_drive_mode_topic", "/vehicle/drive_mode_cmd")

        log_dir = os.fspath(self.get_parameter("log_dir").value)
        prefix = str(self.get_parameter("file_prefix").value)
        rate_hz = max(0.1, float(self.get_parameter("log_rate_hz").value))
        self.flush_every_rows = max(1, int(self.get_parameter("flush_every_rows").value))
        self.rows_since_flush = 0

        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(log_dir, f"{prefix}_{stamp}.csv")

        array_fields = [field for fields in ARRAY_TOPICS.values() for field in fields]
        self.fields = ["t_ros_sec", "t_wall_utc"] + list(FLOAT_TOPICS) + list(FLOAT64_TOPICS) + [
            "output_speed_cmd_kmh",
        ] + list(STRING_TOPICS) + ["output_drive_mode"] + array_fields
        self.latest = {field: math.nan for field in self.fields}
        for field in ["t_wall_utc", *STRING_TOPICS, "output_drive_mode"]:
            self.latest[field] = ""

        self._topic_subscriptions = []
        for field, topic in FLOAT_TOPICS.items():
            self._topic_subscriptions.append(self.create_subscription(Float32, topic, self._set_float(field), 10))  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        for field, topic in FLOAT64_TOPICS.items():
            self._topic_subscriptions.append(self.create_subscription(Float64, topic, self._set_float(field), 10))  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        for field, topic in STRING_TOPICS.items():
            self._topic_subscriptions.append(self.create_subscription(String, topic, self._set_string(field), 10))  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        for topic, fields in ARRAY_TOPICS.items():
            self._topic_subscriptions.append(self.create_subscription(Float32MultiArray, topic, self._set_array(fields), 10))  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        output_speed_topic = str(self.get_parameter("output_speed_topic").value)
        output_mode_topic = str(self.get_parameter("output_drive_mode_topic").value)
        self._topic_subscriptions.append(
            self.create_subscription(Float32, output_speed_topic, self._set_float("output_speed_cmd_kmh"), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        )
        self._topic_subscriptions.append(
            self.create_subscription(String, output_mode_topic, self._set_string("output_drive_mode"), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        )

        self.csv_file = open(self.log_path, "w", encoding="utf-8", newline="")
        self.writer = csv.DictWriter(self.csv_file, fieldnames=self.fields)
        self.writer.writeheader()
        self.csv_file.flush()
        self.timer = self.create_timer(1.0 / rate_hz, self._write_row)
        self.get_logger().info(f"Solar logger started: {self.log_path}")

    def _set_float(self, field):                                   # [関数定義] _set_float の処理実行ブロック
        def handler(msg):                                          # [関数定義] handler の処理実行ブロック
            try:
                self.latest[field] = float(msg.data)
            except (TypeError, ValueError):
                self.latest[field] = math.nan

        return handler                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _set_string(self, field):                                  # [関数定義] _set_string の処理実行ブロック
        def handler(msg):                                          # [関数定義] handler の処理実行ブロック
            self.latest[field] = str(msg.data).replace("\r", "").replace("\n", "\\n")

        return handler                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _set_array(self, fields):                                  # [関数定義] _set_array の処理実行ブロック
        def handler(msg):                                          # [関数定義] handler の処理実行ブロック
            values = list(msg.data)
            for idx, field in enumerate(fields):
                self.latest[field] = float(values[idx]) if idx < len(values) else math.nan

        return handler                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    @staticmethod
    def _clean_float(value):                                       # [関数定義] _clean_float の処理実行ブロック
        try:
            value = float(value)
        except (TypeError, ValueError):
            return ""                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return value if math.isfinite(value) else ""               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _write_row(self):                                          # [関数定義] _write_row の処理実行ブロック
        self.latest["t_ros_sec"] = self.get_clock().now().nanoseconds / 1.0e9
        self.latest["t_wall_utc"] = datetime.now(timezone.utc).isoformat()
        row = {}
        string_fields = {"t_wall_utc", *STRING_TOPICS, "output_drive_mode"}
        for field in self.fields:
            row[field] = str(self.latest.get(field, "")) if field in string_fields else self._clean_float(self.latest.get(field))
        self.writer.writerow(row)
        self.rows_since_flush += 1
        if self.rows_since_flush >= self.flush_every_rows:
            self.csv_file.flush()
            self.rows_since_flush = 0

    def destroy_node(self):                                        # [関数定義] destroy_node の処理実行ブロック
        try:
            self.csv_file.flush()
            self.csv_file.close()
        except Exception:
            pass
        super().destroy_node()


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = SolarLoggerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()