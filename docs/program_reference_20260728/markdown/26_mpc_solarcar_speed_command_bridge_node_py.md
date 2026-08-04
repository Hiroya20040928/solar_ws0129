# 26. planner 指令の安全橋渡し

- ファイル: `mpc_solarcar/speed_command_bridge_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

planner/speed_cmd と drive_mode を受け、起動直後や system state を見ながら安全な出力 topic/UDP に整形する。

## 起動文脈

- 起動文脈: 実機へ出る直前のガード層。
- 呼び出し元: `mpc_solarcar/live_launch.py`
- 次に読むべきファイル: `mpc_solarcar/solar_preflight_logic.py`

## 主要ポイント

- rate limiter と command gate を持つ。
- planner の生指令をそのまま実車へは出さない。

## 主要構造

主要クラスは SpeedCommandBridgeNode。 主要関数は main。 ROS パラメータ宣言は 18 件。 ROS I/O は publisher 2 件、subscription 4 件。

## ファイルを上から読んだときの定義順

- L17: クラス SpeedCommandBridgeNode を定義する。
- L162: 関数 main を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `import json`
  - manifest、checkpoint、UDP payload をやり取りするため。 このファイル内での主な使用位置は L153。
- L4: `import socket`
  - socket モジュールを利用するため。 このファイル内での主な使用位置は L73。
- L5: `import time`
  - wall/monotonic time に基づく周期制御や freshness 判定を行うため。 このファイル内での主な使用位置は L74, L91, L98, L102, L105, L143。
- L7: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L163, L165, L167。
- L8: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L17。
- L10: `from std_msgs.msg import Float32, String`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L66, L67, L68, L69, L70, L71, L89, L93, ...。
- L12: `from .signal_utils import SmoothRateLimiter`
  - signal_utils.py から SmoothRateLimiter を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/signal_utils.py。 このファイル内での主な使用位置は L54。
- L13: `from .solar_preflight_logic import evaluate_command_gate`
  - preflight 判定ロジック から evaluate_command_gate を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_preflight_logic.py。 このファイル内での主な使用位置は L107。
- L14: `from .telemetry_protocol import utc_iso_now`
  - telemetry_protocol.py から utc_iso_now を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/telemetry_protocol.py。 このファイル内での主な使用位置は L144。

## 関数・クラスを上から順に解説

### L17 クラス `SpeedCommandBridgeNode`

- 定義: `SpeedCommandBridgeNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `Float32`, `SmoothRateLimiter`, `String`, `__init__`, `bool`, `create_publisher`, `create_subscription`, `create_timer`, `declare_parameter`, `dumps`, `encode`, `error`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _on_speed_cmd を定義する。
  3. 関数 _on_upper_speed_cmd を定義する。
  4. 関数 _on_drive_mode を定義する。
  5. 関数 _on_system_state を定義する。
  6. 関数 _step を定義する。

### L162 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `SpeedCommandBridgeNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に SpeedCommandBridgeNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。


## パラメータ

- L20: `output_speed_topic` (default: `/vehicle/speed_cmd_kmh`)
- L21: `output_drive_mode_topic` (default: `/vehicle/drive_mode_cmd`)
- L22: `udp_enabled` (default: `False`)
- L23: `udp_host` (default: `127.0.0.1`)
- L24: `udp_port` (default: `50050`)
- L25: `publish_rate_hz` (default: `5.0`)
- L26: `input_timeout_sec` (default: `3.0`)
- L27: `safe_speed_kmh` (default: `0.0`)
- L28: `startup_hold_sec` (default: `2.0`)
- L29: `filter_tau_sec` (default: `1.0`)
- L30: `accel_limit_kmhps` (default: `1.2`)
- L31: `decel_limit_kmhps` (default: `3.5`)
- L32: `speed_deadband_kmh` (default: `0.1`)
- L33: `speed_quantize_step_kmh` (default: `0.1`)
- L34: `max_output_speed_kmh` (default: `120.0`)
- L35: `drive_mode_min_hold_sec` (default: `5.0`)
- L36: `require_system_running` (default: `True`)
- L37: `system_state_timeout_sec` (default: `2.5`)

## ROS topic I/O

- Publisher L66: `self.output_speed_topic`
- Publisher L67: `self.output_drive_mode_topic`
- Subscription L68: `/planner/speed_cmd` -> `self._on_speed_cmd`
- Subscription L69: `/planner/upper_speed_cmd` -> `self._on_upper_speed_cmd`
- Subscription L70: `/planner/drive_mode` -> `self._on_drive_mode`
- Subscription L71: `/system/state` -> `self._on_system_state`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
