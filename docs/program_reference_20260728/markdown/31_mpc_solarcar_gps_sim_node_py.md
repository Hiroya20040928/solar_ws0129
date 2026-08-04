# 31. sim GPS 軌跡ノード

- ファイル: `mpc_solarcar/gps_sim_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

planner/speed_cmd を積分して route waypoints 上の現在位置を求め、/sim/gps を publish する。

## 起動文脈

- 起動文脈: sim モードの地図上位置源。
- 呼び出し元: `launch/solarcar_sim.launch.py`
- 次に読むべきファイル: `mpc_solarcar/solar_state_node.py`

## 主要ポイント

- 純粋に速度指令から位置を進める。

## 主要構造

主要クラスは GPSSimNode。 主要関数は on_speed, step, main。 ROS パラメータ宣言は 3 件。 ROS I/O は publisher 1 件、subscription 1 件。

## ファイルを上から読んだときの定義順

- L11: クラス GPSSimNode を定義する。
- L47: 関数 main を定義する。

## import 群

- L1: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L48, L50。
- L2: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L11。
- L3: `from sensor_msgs.msg import NavSatFix`
  - GPS 緯度経度高度を ROS topic でやり取りするため。 このファイル内での主な使用位置は L28, L38。
- L4: `from std_msgs.msg import Float32`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L29, L32。
- L5: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L24。
- L7: `from .route_utils import interpolate_route_with_alt`
  - route_utils.py から interpolate_route_with_alt を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/route_utils.py。 このファイル内での主な使用位置は L37。
- L8: `from .path_utils import resolve_path`
  - ROS share / 相対パス解決 から resolve_path を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/path_utils.py。 このファイル内での主な使用位置は L18。
- L9: `from .solar_profile import require_csv_data_rows`
  - profile YAML 読込と検証 から require_csv_data_rows を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L19。

## 関数・クラスを上から順に解説

### L11 クラス `GPSSimNode`

- 定義: `GPSSimNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `NavSatFix`, `__init__`, `create_publisher`, `create_subscription`, `create_timer`, `declare_parameter`, `float`, `get_clock`, `get_logger`, `get_parameter`, `info`, `interpolate_route_with_alt`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 on_speed を定義する。
  3. 関数 step を定義する。

### L47 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `GPSSimNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に GPSSimNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。


## パラメータ

- L14: `route_csv` (default: `inputs/route_waypoints.csv`)
- L15: `dt` (default: `1.0`)
- L16: `init_speed_kmh` (default: `40.0`)

## ROS topic I/O

- Publisher L28: `/sim/gps`
- Subscription L29: `/planner/speed_cmd` -> `self.on_speed`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
