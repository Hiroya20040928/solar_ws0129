# 27. live 計測鮮度監視

- ファイル: `mpc_solarcar/solar_preflight_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

speed、distance、battery、planner status の鮮度を見て system/state と health を publish する。

## 起動文脈

- 起動文脈: 起動可否と運用中の健全性の監視役。
- 呼び出し元: `mpc_solarcar/live_launch.py`, `launch/solar_measurement.launch.py`
- 次に読むべきファイル: `mpc_solarcar/solar_preflight_logic.py`, `mpc_solarcar/speed_command_bridge_node.py`

## 主要ポイント

- planner 自体は止めずに、system/state と health を出す。

## 主要構造

主要クラスは SolarPreflightNode。 主要関数は callback, main。 ROS パラメータ宣言は 6 件。 ROS I/O は publisher 3 件、subscription 6 件。

## ファイルを上から読んだときの定義順

- L12: クラス SolarPreflightNode を定義する。
- L78: 関数 main を定義する。
- L88: 条件 __name__ == '__main__' を判定し、真なら内部処理を行う。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `import time`
  - wall/monotonic time に基づく周期制御や freshness 判定を行うため。 このファイル内での主な使用位置は L24, L43, L60。
- L5: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L79, L82, L85。
- L6: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L12。
- L7: `from std_msgs.msg import Float32, Float32MultiArray, String`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L27, L28, L29, L31, L32, L33, L34, L35, ...。
- L9: `from .solar_preflight_logic import evaluate_freshness`
  - preflight 判定ロジック から evaluate_freshness を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_preflight_logic.py。 このファイル内での主な使用位置は L66。

## 関数・クラスを上から順に解説

### L12 クラス `SolarPreflightNode`

- 定義: `SolarPreflightNode(bases=Node)`
- docstring: Preflight monitor based only on solar-car telemetry freshness.
- このブロックが直接呼ぶ主な関数/メソッド: `Float32`, `String`, `__init__`, `_required`, `_seen`, `append`, `bool`, `create_publisher`, `create_subscription`, `create_timer`, `declare_parameter`, `evaluate_freshness`
- 上から順の処理:
  1. docstring または説明文字列を置く。
  2. 関数 __init__ を定義する。
  3. 関数 _seen を定義する。
  4. 関数 _required を定義する。
  5. 関数 _step を定義する。

### L78 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `SolarPreflightNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に SolarPreflightNode() の結果を代入する。
  3. 例外処理を伴う try ブロックを実行する。


## パラメータ

- L17: `startup_grace_sec` (default: `10.0`)
- L18: `measurement_timeout_sec` (default: `3.0`)
- L19: `require_speed` (default: `True`)
- L20: `require_distance` (default: `True`)
- L21: `require_battery` (default: `True`)
- L22: `require_planner` (default: `True`)

## ROS topic I/O

- Publisher L27: `/system/state`
- Publisher L28: `/system/health`
- Publisher L29: `/system/diag`
- Subscription L31: `/vehicle/speed_kmh` -> `self._seen('speed')`
- Subscription L32: `/vehicle/s_km` -> `self._seen('distance')`
- Subscription L33: `/vehicle/batt_soc` -> `self._seen('batt_soc')`
- Subscription L34: `/vehicle/batt_voltage_v` -> `self._seen('batt_voltage')`
- Subscription L35: `/vehicle/batt_current_a` -> `self._seen('batt_current')`
- Subscription L36: `/planner/status` -> `self._seen('planner')`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
