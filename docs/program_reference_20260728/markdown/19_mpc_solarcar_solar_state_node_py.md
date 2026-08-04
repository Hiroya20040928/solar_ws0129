# 19. sim 用 車体状態 publisher

- ファイル: `mpc_solarcar/solar_state_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

sim モードで planner 指令速度から速度、距離、電池、PV、altitude を模擬 publish する。

## 起動文脈

- 起動文脈: simulation launch における擬似車両。
- 呼び出し元: `launch/solarcar_sim.launch.py`
- 次に読むべきファイル: `mpc_solarcar/model.py`, `mpc_solarcar/mpc_node.py`

## 主要ポイント

- SolarCarModel を直接生成する。
- /planner/speed_cmd を受けて /vehicle/* を出す。

## 主要構造

主要クラスは SolarStateNode。 主要関数は main。 ROS パラメータ宣言は 26 件。 ROS I/O は publisher 8 件、subscription 1 件。

## ファイルを上から読んだときの定義順

- L22: クラス SolarStateNode を定義する。
- L265: 関数 main を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での使用位置は少ないか、間接利用である。
- L4: `import time`
  - wall/monotonic time に基づく周期制御や freshness 判定を行うため。 このファイル内での使用位置は少ないか、間接利用である。
- L5: `from datetime import datetime, timedelta, timezone`
  - UTC 時刻や相対時間を扱うため。 このファイル内での主な使用位置は L118, L122, L183, L209。
- L7: `import numpy as np`
  - 数値配列、clip、補間、統計計算を行うため。 このファイル内での主な使用位置は L185, L186, L188, L240。
- L8: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L99, L105, L107。
- L9: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L59, L60, L61, L62, L63, L64, L65, L66, ...。
- L10: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L22。
- L12: `from std_msgs.msg import Float32`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L168, L169, L170, L171, L172, L173, L174, L175, ...。
- L14: `from .model import Params, SolarCarModel`
  - 車体物理・電気モデル本体 から Params, SolarCarModel を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/model.py。 このファイル内での主な使用位置は L128, L132。
- L15: `from .path_utils import resolve_path`
  - ROS share / 相対パス解決 から resolve_path を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/path_utils.py。 このファイル内での主な使用位置は L87, L95, L103, L129, L130, L131, L133, L134, ...。
- L16: `from .route_utils import interpolate_profile`
  - route_utils.py から interpolate_profile を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/route_utils.py。 このファイル内での主な使用位置は L195。
- L17: `from .schedule_utils import DriveSchedule`
  - schedule_utils.py から DriveSchedule を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/schedule_utils.py。 このファイル内での主な使用位置は L103。
- L18: `from .signal_utils import SmoothRateLimiter`
  - signal_utils.py から SmoothRateLimiter を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/signal_utils.py。 このファイル内での主な使用位置は L158。
- L19: `from .solar_profile import get_path, get_section, load_profile, require_csv_data_rows`
  - profile YAML 読込と検証 から get_path, get_section, load_profile, require_csv_data_rows を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L54, L55, L56, L59, L60, L61, L62, L63, ...。

## 関数・クラスを上から順に解説

### L22 クラス `SolarStateNode`

- 定義: `SolarStateNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `Float32`, `Parameter`, `Params`, `SmoothRateLimiter`, `SolarCarModel`, `__init__`, `_forecast_row`, `_route_value`, `abs`, `any`, `astimezone`, `clip`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _on_speed_cmd を定義する。
  3. 関数 _forecast_row を定義する。
  4. 関数 _route_value を定義する。
  5. 関数 _step を定義する。

### L265 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `SolarStateNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に SolarStateNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。


## パラメータ

- L25: `profile_yaml`
- L26: `forecast_csv` (default: `inputs/forecast_10min.csv`)
- L27: `route_profile_csv`
- L28: `drive_schedule_yaml`
- L29: `drive_eff_map`
- L30: `regen_eff_map`
- L31: `rint_map`
- L32: `panel_eff_map`
- L33: `mppt_eff_map`
- L34: `drive_map_eco`
- L35: `drive_map_power`
- L36: `regen_map_eco`
- L37: `regen_map_power`
- L38: `ocv_soc_map`
- L39: `params_yaml`
- L40: `forecast_time_mode` (default: `auto`)
- L41: `forecast_time_tz` (default: `UTC`)
- L42: `forecast_start_time_utc`
- L43: `publish_rate_hz` (default: `2.0`)
- L44: `init_speed_kmh` (default: `45.0`)
- L45: `soc0` (default: `0.95`)
- L46: `Tb0` (default: `30.0`)
- L47: `s0_km` (default: `0.0`)
- L48: `filter_tau_sec` (default: `1.0`)
- L49: `accel_limit_kmhps` (default: `1.2`)
- L50: `decel_limit_kmhps` (default: `3.5`)

## ROS topic I/O

- Publisher L168: `/vehicle/speed_kmh`
- Publisher L169: `/vehicle/s_km`
- Publisher L170: `/vehicle/batt_soc`
- Publisher L171: `/vehicle/batt_temp_c`
- Publisher L172: `/vehicle/batt_current_a`
- Publisher L173: `/vehicle/batt_voltage_v`
- Publisher L174: `/vehicle/solar_power_w`
- Publisher L175: `/vehicle/altitude_m`
- Subscription L176: `/planner/speed_cmd` -> `self._on_speed_cmd`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
