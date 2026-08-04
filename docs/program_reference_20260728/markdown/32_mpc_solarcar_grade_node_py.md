# 32. 実測勾配推定ノード

- ファイル: `mpc_solarcar/grade_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

distance と altitude/GPS から grade を推定し /vehicle/grade へ publish する。

## 起動文脈

- 起動文脈: measure/live の監視・記録用の grade source。
- 呼び出し元: `launch/solar_measurement.launch.py`, `mpc_solarcar/live_launch.py`
- 次に読むべきファイル: 特になし

## 主要ポイント

- 現在の solar mpc_node は route profile 勾配を主に使い、/vehicle/grade を直接は使わない。
- ただし logger や補助用途では重要。

## 主要構造

主要クラスは GradeNode。 主要関数は main。 ROS パラメータ宣言は 5 件。 ROS I/O は publisher 1 件、subscription 4 件。

## ファイルを上から読んだときの定義順

- L10: クラス GradeNode を定義する。
- L89: 関数 main を定義する。

## import 群

- L1: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L25, L26, L27, L28, L31, L53, L58, L64, ...。
- L2: `import time`
  - wall/monotonic time に基づく周期制御や freshness 判定を行うため。 このファイル内での主な使用位置は L32。
- L4: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L90, L92, L94。
- L5: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L10。
- L6: `from std_msgs.msg import Float32`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L34, L35, L36, L39, L43, L46, L49, L65, ...。
- L7: `from sensor_msgs.msg import NavSatFix`
  - GPS 緯度経度高度を ROS topic でやり取りするため。 このファイル内での主な使用位置は L37, L52。

## 関数・クラスを上から順に解説

### L10 クラス `GradeNode`

- 定義: `GradeNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `Float32`, `__init__`, `_update_altitude`, `create_publisher`, `create_subscription`, `create_timer`, `declare_parameter`, `float`, `get_logger`, `get_parameter`, `info`, `isfinite`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _on_s_km を定義する。
  3. 関数 _on_speed を定義する。
  4. 関数 _on_altitude を定義する。
  5. 関数 _on_gps を定義する。
  6. 関数 _update_altitude を定義する。
  7. 関数 _step を定義する。

### L89 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `GradeNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に GradeNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。


## パラメータ

- L13: `min_speed_kmh` (default: `5.0`)
- L14: `altitude_alpha` (default: `0.2`)
- L15: `min_delta_s_km` (default: `0.01`)
- L16: `gps_topic` (default: `/sim/gps`)
- L17: `altitude_topic` (default: `/vehicle/altitude_m`)

## ROS topic I/O

- Publisher L39: `/vehicle/grade`
- Subscription L34: `/vehicle/s_km` -> `self._on_s_km`
- Subscription L35: `/vehicle/speed_kmh` -> `self._on_speed`
- Subscription L36: `self.altitude_topic` -> `self._on_altitude`
- Subscription L37: `self.gps_topic` -> `self._on_gps`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
