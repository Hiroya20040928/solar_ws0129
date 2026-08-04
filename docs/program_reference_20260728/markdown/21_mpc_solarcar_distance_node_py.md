# 21. 速度積分距離ノード

- ファイル: `mpc_solarcar/distance_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

vehicle speed を積分して /vehicle/s_km を生成する最小ノード。

## 起動文脈

- 起動文脈: measure/live 系で direct distance が無い場合の距離供給。
- 呼び出し元: `launch/solar_measurement.launch.py`, `mpc_solarcar/live_launch.py`
- 次に読むべきファイル: 特になし

## 主要ポイント

- reset_odometry service も持つ。
- 入力は /vehicle/speed_kmh だけ。

## 主要構造

主要クラスは DistanceNode。 主要関数は main。 ROS パラメータ宣言は 2 件。 ROS I/O は publisher 1 件、subscription 1 件。

## ファイルを上から読んだときの定義順

- L9: クラス DistanceNode を定義する。
- L54: 関数 main を定義する。

## import 群

- L1: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L20, L32, L43。
- L3: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L55, L57, L59。
- L4: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L9。
- L5: `from std_msgs.msg import Float32`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L22, L23, L29, L49。
- L6: `from std_srvs.srv import Trigger`
  - std_srvs.srv から Trigger を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L24。

## 関数・クラスを上から順に解説

### L9 クラス `DistanceNode`

- 定義: `DistanceNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `Float32`, `__init__`, `create_publisher`, `create_service`, `create_subscription`, `create_timer`, `declare_parameter`, `float`, `get_clock`, `get_logger`, `get_parameter`, `info`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _on_speed を定義する。
  3. 関数 _on_reset を定義する。
  4. 関数 _publish を定義する。

### L54 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `DistanceNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に DistanceNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。


## パラメータ

- L12: `max_dt_sec` (default: `2.5`)
- L13: `publish_rate_hz` (default: `1.0`)

## ROS topic I/O

- Publisher L23: `/vehicle/s_km`
- Subscription L22: `/vehicle/speed_kmh` -> `self._on_speed`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
