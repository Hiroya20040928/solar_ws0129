from __future__ import annotations

import time

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from std_msgs.msg import Float32, Float32MultiArray, String



class SolarPreflightNode(Node):                                    # [クラス定義] SolarPreflightNode オブジェクトの設計
    """Preflight monitor based only on solar-car telemetry freshness."""

    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__("solar_preflight_node")
        self.declare_parameter("startup_grace_sec", 10.0)
        self.declare_parameter("measurement_timeout_sec", 3.0)
        self.declare_parameter("require_speed", True)
        self.declare_parameter("require_distance", True)
        self.declare_parameter("require_battery", True)
        self.declare_parameter("require_planner", True)

        self.start_mono = time.monotonic()
        self.last_seen: dict[str, float] = {}

        self.pub_state = self.create_publisher(String, "/system/state", 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_health = self.create_publisher(Float32, "/system/health", 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_diag = self.create_publisher(String, "/system/diag", 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        self.create_subscription(Float32, "/vehicle/speed_kmh", self._seen("speed"), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, "/vehicle/s_km", self._seen("distance"), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, "/vehicle/batt_soc", self._seen("batt_soc"), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, "/vehicle/batt_voltage_v", self._seen("batt_voltage"), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, "/vehicle/batt_current_a", self._seen("batt_current"), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, "/planner/status", self._seen("planner"), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        self.timer = self.create_timer(1.0, self._step)
        self.get_logger().info("SolarPreflightNode started.")

    def _seen(self, key: str):                                     # [関数定義] _seen の処理実行ブロック
        def callback(_msg):                                        # [関数定義] callback の処理実行ブロック
            self.last_seen[key] = time.monotonic()

        return callback                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _required(self) -> tuple[str, ...]:                        # [関数定義] _required の処理実行ブロック
        required: list[str] = []
        if bool(self.get_parameter("require_speed").value):
            required.append("speed")
        if bool(self.get_parameter("require_distance").value):
            required.append("distance")
        if bool(self.get_parameter("require_battery").value):
            required.extend(("batt_soc", "batt_voltage", "batt_current"))
        if bool(self.get_parameter("require_planner").value):
            required.append("planner")
        return tuple(required)                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _step(self):                                               # [関数定義] _step の処理実行ブロック
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


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = SolarPreflightNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

# =============================================================================
# 【統合ロジック】プリフライト・システム健全性判定アルゴリズム
# =============================================================================

from dataclasses import dataclass


@dataclass(frozen=True)
class FreshnessResult:                                             # [クラス定義] FreshnessResult オブジェクトの設計
    state: str
    health: float
    diagnostic: str


@dataclass(frozen=True)
class CommandGateResult:                                           # [クラス定義] CommandGateResult オブジェクトの設計
    allowed: bool
    reason: str


def evaluate_freshness(                                            # [関数定義] evaluate_freshness の処理実行ブロック
    *,
    elapsed_sec: float,
    ages_sec: dict[str, float | None],
    required: tuple[str, ...],
    timeout_sec: float,
    startup_grace_sec: float,
) -> FreshnessResult:
    if elapsed_sec < startup_grace_sec:
        return FreshnessResult("STARTING", 0.25, "waiting for required solar telemetry")  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    missing = [name for name in required if ages_sec.get(name) is None]
    stale = [
        name
        for name in required
        if ages_sec.get(name) is not None and float(ages_sec[name]) > timeout_sec
    ]
    if missing:
        return FreshnessResult("DEGRADED", 0.2, "missing: " + ", ".join(missing))  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if stale:
        return FreshnessResult("DEGRADED", 0.4, "stale: " + ", ".join(stale))  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return FreshnessResult("RUNNING", 1.0, "solar telemetry and planner inputs are fresh")  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def evaluate_command_gate(                                         # [関数定義] evaluate_command_gate の処理実行ブロック
    *,
    elapsed_sec: float,
    speed_input_age_sec: float | None,
    system_state: str,
    system_state_age_sec: float | None,
    startup_hold_sec: float,
    input_timeout_sec: float,
    system_state_timeout_sec: float,
    require_system_running: bool,
) -> CommandGateResult:
    if elapsed_sec < max(0.0, startup_hold_sec):
        return CommandGateResult(False, "startup_hold")            # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if speed_input_age_sec is None:
        return CommandGateResult(False, "missing_speed_command")   # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if speed_input_age_sec > max(0.0, input_timeout_sec):
        return CommandGateResult(False, "stale_speed_command")     # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if not require_system_running:
        return CommandGateResult(True, "ok_without_system_gate")   # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if system_state_age_sec is None:
        return CommandGateResult(False, "missing_system_state")    # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if system_state_age_sec > max(0.0, system_state_timeout_sec):
        return CommandGateResult(False, "stale_system_state")      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if str(system_state).strip().upper() != "RUNNING":
        return CommandGateResult(False, "system_not_running")      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return CommandGateResult(True, "ok")                           # [戻り値] 計算結果・計算状態の呼び出し元への返却