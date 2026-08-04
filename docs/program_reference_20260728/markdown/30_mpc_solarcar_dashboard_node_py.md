# 30. dashboard + HTTP API

- ファイル: `mpc_solarcar/dashboard_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

planner と vehicle の現在値を ROS から受け、HTTP サーバと dashboard frontend へ渡す。

## 起動文脈

- 起動文脈: 可視化の中心ノード。
- 呼び出し元: `launch/solarcar_sim.launch.py`, `mpc_solarcar/live_launch.py`, `launch/solar_measurement.launch.py`
- 次に読むべきファイル: 特になし

## 主要ポイント

- /api/state と /metrics を持つ。
- ROS topic を直接 browser へ出すのではなく、Node 内 state に集約する。

## 主要構造

主要クラスは DashboardHandler, DashboardNode。 主要関数は do_GET, log_message, destroy_node, get_state, get_prometheus_metrics, main。 ROS パラメータ宣言は 5 件。 ROS I/O は publisher 0 件、subscription 21 件。

## ファイルを上から読んだときの定義順

- L19: クラス DashboardHandler を定義する。
- L55: クラス DashboardNode を定義する。
- L409: 関数 main を定義する。
- L417: 条件 __name__ == '__main__' を判定し、真なら内部処理を行う。

## import 群

- L1: `import json`
  - manifest、checkpoint、UDP payload をやり取りするため。 このファイル内での主な使用位置は L38。
- L2: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L212。
- L3: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L68, L70, L71。
- L4: `import threading`
  - threading モジュールを利用するため。 このファイル内での主な使用位置は L73, L150。
- L5: `import time`
  - wall/monotonic time に基づく周期制御や freshness 判定を行うため。 このファイル内での主な使用位置は L75, L215, L239, L261, L262, L268, L299, L311, ...。
- L6: `from functools import partial`
  - functools から partial を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L147。
- L7: `from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer`
  - http.server から SimpleHTTPRequestHandler, ThreadingHTTPServer を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L19, L149。
- L9: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L410, L412, L414。
- L10: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L55。
- L12: `from std_msgs.msg import Float32, Float32MultiArray, String`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L117, L118, L119, L120, L121, L122, L123, L124, ...。
- L13: `from sensor_msgs.msg import NavSatFix`
  - GPS 緯度経度高度を ROS topic でやり取りするため。 このファイル内での主な使用位置は L136, L367。
- L14: `from nav_msgs.msg import Path`
  - 将来軌跡を dashboard や logger へ出すため。 このファイル内での主な使用位置は L137, L373。
- L16: `from ament_index_python.packages import get_package_share_directory`
  - ament_index_python.packages から get_package_share_directory を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L67。
- L381: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L382。

## 関数・クラスを上から順に解説

### L19 クラス `DashboardHandler`

- 定義: `DashboardHandler(bases=SimpleHTTPRequestHandler)`
- このブロックが直接呼ぶ主な関数/メソッド: `__init__`, `_send_json`, `_send_metrics`, `do_GET`, `dumps`, `encode`, `end_headers`, `get_prometheus_metrics`, `get_state`, `len`, `send_header`, `send_response`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 do_GET を定義する。
  3. 関数 log_message を定義する。
  4. 関数 _send_json を定義する。
  5. 関数 _send_metrics を定義する。

### L55 クラス `DashboardNode`

- 定義: `DashboardNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `Lock`, `Thread`, `ThreadingHTTPServer`, `__init__`, `_init_dummy`, `_set_estimated_soc`, `_update`, `abspath`, `create_subscription`, `create_timer`, `declare_parameter`, `destroy_node`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 destroy_node を定義する。
  3. 関数 get_state を定義する。
  4. 関数 get_prometheus_metrics を定義する。
  5. 関数 _update を定義する。
  6. 関数 _on_speed_cmd を定義する。
  7. 関数 _on_upper_speed_cmd を定義する。
  8. 関数 _on_speed_meas を定義する。
  9. 関数 _on_throttle_cmd を定義する。
  10. 関数 _on_drive_mode を定義する。
  11. 関数 _on_soc を定義する。
  12. 関数 _set_estimated_soc を定義する。

### L409 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `DashboardNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に DashboardNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。


## パラメータ

- L58: `host` (default: `0.0.0.0`)
- L59: `port` (default: `8080`)
- L60: `static_dir`
- L61: `dummy_csv`
- L62: `dummy_rate_hz` (default: `5.0`)

## ROS topic I/O

- Subscription L117: `/planner/speed_cmd` -> `self._on_speed_cmd`
- Subscription L118: `/planner/upper_speed_cmd` -> `self._on_upper_speed_cmd`
- Subscription L119: `/vehicle/speed_kmh` -> `self._on_speed_meas`
- Subscription L120: `/planner/throttle_cmd_pct` -> `self._on_throttle_cmd`
- Subscription L121: `/planner/drive_mode` -> `self._on_drive_mode`
- Subscription L122: `/vehicle/batt_soc` -> `self._on_soc`
- Subscription L123: `/vehicle/batt_temp_c` -> `self._on_tb`
- Subscription L124: `/vehicle/batt_current_a` -> `self._on_ibatt`
- Subscription L125: `/vehicle/batt_voltage_v` -> `self._on_vbatt`
- Subscription L126: `/vehicle/s_km` -> `self._on_s_km`
- Subscription L127: `/planner/status` -> `self._on_status`
- Subscription L128: `/planner/env` -> `self._on_env`
- Subscription L129: `/planner/metrics` -> `self._on_metrics`
- Subscription L130: `/planner/upper_plan` -> `self._on_upper_plan`
- Subscription L131: `/planner/lower_plan` -> `self._on_lower_plan`
- Subscription L132: `/system/state` -> `self._on_sys_state`
- Subscription L133: `/system/diag` -> `self._on_sys_diag`
- Subscription L134: `/system/mpc_state` -> `self._on_mpc_state`
- Subscription L135: `/system/health` -> `self._on_health`
- Subscription L136: `/sim/gps` -> `self._on_gps`
- Subscription L137: `/planner/trajectory` -> `self._on_path`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
