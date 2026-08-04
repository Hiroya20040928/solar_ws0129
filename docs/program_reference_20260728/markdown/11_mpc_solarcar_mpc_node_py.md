# 11. live / sim 共通 MPC 本体

- ファイル: `mpc_solarcar/mpc_node.py`
- 種別: `Python`
- 区分: `runtime core`

## 役割

forecast、route、vehicle telemetry、maps を使って上位速度計画と下位追従指令を出す ROS2 ノード。

## 起動文脈

- 起動文脈: sim/live/live_wifi で中心に動く単一障害点に近いノード。
- 呼び出し元: `live_launch.py`, `solarcar_sim.launch.py`
- 次に読むべきファイル: `mpc_solarcar/model.py`, `mpc_solarcar/upper_cost.py`, `mpc_solarcar/estimator.py`

## 主要ポイント

- SolarCarModel を直接生成する。
- 1 Hz upper timer と lower timer 群を並列 callback group で回す。
- calibration topic で内部係数を上書きする。

## 主要構造

主要クラスは MPCNode。 主要関数は z_next_for, quad_penalty, cost, expand_ctrl, build_balance_seed, integrate_stationary_duration, step_wait, apply_control_stop_at。 ROS パラメータ宣言は 151 件。 ROS I/O は publisher 14 件、subscription 19 件。

## ファイルを上から読んだときの定義順

- L42: クラス MPCNode を定義する。
- L2965: 関数 main を定義する。

## import 群

- L2: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L196, L199, L254, L259, L261, L264, L267, L616, ...。
- L3: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L180, L434。
- L4: `import time`
  - wall/monotonic time に基づく周期制御や freshness 判定を行うため。 このファイル内での主な使用位置は L175, L437, L1070, L1915, L2017, L2374, L2398, L2401, ...。
- L5: `from collections import deque`
  - 固定長の時系列や遅延キューを効率よく保持するため。 このファイル内での主な使用位置は L2676。
- L6: `from datetime import datetime, timezone, timedelta`
  - UTC 時刻や相対時間を扱うため。 このファイル内での主な使用位置は L713, L717, L718, L786, L810, L815, L824, L846, ...。
- L8: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L2966, L2975。
- L9: `from rclpy.callback_groups import MutuallyExclusiveCallbackGroup`
  - 同一ノード内の callback 実行系を分け、upper/lower/telemetry を並列に扱うため。 このファイル内での主な使用位置は L54, L55, L56, L57。
- L10: `from rclpy.executors import MultiThreadedExecutor`
  - 複数 callback group を並列実行する executor を使うため。 このファイル内での主な使用位置は L2968。
- L11: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L42。
- L12: `from rclpy.parameter import Parameter`
  - rclpy.parameter から Parameter を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L166, L2750, L2752, L2754, L2756。
- L14: `import yaml`
  - profile、stop、schedule、summary YAML を読み書きするため。 このファイル内での主な使用位置は L70, L105, L2740。
- L15: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L77, L79, L98, L100, L451, L460, L1904。
- L16: `import numpy as np`
  - 数値配列、clip、補間、統計計算を行うため。 このファイル内での主な使用位置は L221, L230, L265, L268, L272, L278, L542, L545, ...。
- L18: `from std_msgs.msg import Bool, Float32, Float32MultiArray, String`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L192, L208, L216, L225, L234, L242, L270, L276, ...。
- L19: `from nav_msgs.msg import Path`
  - 将来軌跡を dashboard や logger へ出すため。 このファイル内での主な使用位置は L741, L1833, L2701, L2880。
- L20: `from geometry_msgs.msg import PoseStamped`
  - Path を構成する waypoint pose を組み立てるため。 このファイル内での主な使用位置は L1842, L1851, L2886。
- L22: `from scipy.optimize import minimize`
  - 連続最適化や MHE の逆推定を解くため。 このファイル内での主な使用位置は L1278, L2251, L2874。
- L24: `from .model import SolarCarModel, Params`
  - 車体物理・電気モデル本体 から SolarCarModel, Params を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/model.py。 このファイル内での主な使用位置は L509, L513。
- L25: `from .path_utils import resolve_path`
  - ROS share / 相対パス解決 から resolve_path を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/path_utils.py。 このファイル内での主な使用位置は L135, L423, L424, L442, L450, L459, L470, L483, ...。
- L26: `from .route_utils import average_profile, interpolate_profile`
  - route_utils.py から average_profile, interpolate_profile を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/route_utils.py。 このファイル内での主な使用位置は L963, L974, L983。
- L27: `from .schedule_utils import DriveSchedule`
  - schedule_utils.py から DriveSchedule を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/schedule_utils.py。 このファイル内での主な使用位置は L484。
- L28: `from .estimator import BatteryMHE, MheInput, MheMeas`
  - Battery MHE から BatteryMHE, MheInput, MheMeas を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/estimator.py。 このファイル内での主な使用位置は L724, L2493, L2504。
- L29: `from .forecast_grid import build_forecast_grid_payload, interp_forecast_grid`
  - forecast_grid.py から build_forecast_grid_payload, interp_forecast_grid を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/forecast_grid.py。 このファイル内での主な使用位置は L96, L885, L886, L887, L890, L891, L896, L898, ...。
- L30: `from .signal_utils import RobustScalarFilter, finite_float, fresh_enough, slew_limit`
  - signal_utils.py から RobustScalarFilter, finite_float, fresh_enough, slew_limit を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/signal_utils.py。 このファイル内での主な使用位置は L195, L252, L253, L258, L263, L266, L636, L643, ...。
- L31: `from .upper_cost import load_upper_cost_config, upper_stage_cost, upper_terminal_cost, quad_penalty`
  - 上位MPC 目的関数 から load_upper_cost_config, upper_stage_cost, upper_terminal_cost, quad_penalty を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/upper_cost.py。 このファイル内での主な使用位置は L590, L1227, L1231, L1236, L1238, L1242, L1250, L1251, ...。
- L32: `from .upper_horizon import build_upper_distance_horizon, plan_segment_index`
  - 上位MPC 距離メッシュ生成 から build_upper_distance_horizon, plan_segment_index を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/upper_horizon.py。 このファイル内での主な使用位置は L1293, L1953。
- L33: `from .upper_policy import absolute_control_distances, interpolate_upper_policy, load_upper_policy_csv, shift_upper_policy_warm_start`
  - 上位速度計画の補間と warm start から absolute_control_distances, interpolate_upper_policy, load_upper_policy_csv, shift_upper_policy_warm_start を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/upper_policy.py。 このファイル内での主な使用位置は L471, L1335, L1345, L1355。
- L39: `from .upper_solver import hybrid_bounded_minimize`
  - 上位探索ソルバ から hybrid_bounded_minimize を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/upper_solver.py。 このファイル内での主な使用位置は L1719。

## 関数・クラスを上から順に解説

### L42 クラス `MPCNode`

- 定義: `MPCNode(bases=Node)`
- docstring: MPC node with two modes:
  - Default: solarcar MPC (forecast-driven)
  - Passo mode: fuel-minimizing advisory MPC
- このブロックが直接呼ぶ主な関数/メソッド: `BatteryMHE`, `Float32`, `Float32MultiArray`, `Index`, `MheInput`, `MheMeas`, `MutuallyExclusiveCallbackGroup`, `Parameter`, `Params`, `Path`, `PoseStamped`, `RobustScalarFilter`
- 上から順の処理:
  1. docstring または説明文字列を置く。
  2. 関数 __init__ を定義する。
  3. 関数 _load_stops を定義する。
  4. 関数 _load_forecast_file を定義する。
  5. 関数 _apply_params_yaml を定義する。
  6. 関数 _maybe_reload_forecast を定義する。
  7. 関数 _on_s_km_solar を定義する。
  8. 関数 _on_speed_solar を定義する。
  9. 関数 _on_soc_solar を定義する。
  10. 関数 _on_tb_solar を定義する。
  11. 関数 _on_i_solar を定義する。
  12. 関数 _on_v_solar を定義する。

### L2965 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `MPCNode`, `MultiThreadedExecutor`, `add_node`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に MPCNode() の結果を代入する。
  3. executor に MultiThreadedExecutor(num_threads=4) の結果を代入する。
  4. executor.add_node(...) を実行する。
  5. 例外処理を伴う try ブロックを実行する。


## パラメータ

- L58: `passo_mode` (default: `False`)
- L292: `forecast_csv` (default: `inputs/forecast_10min.csv`)
- L293: `maps_dir` (default: `maps`)
- L294: `drive_eff_map`
- L295: `regen_eff_map`
- L296: `rint_map`
- L297: `drive_map_eco`
- L298: `drive_map_power`
- L299: `regen_map_eco`
- L300: `regen_map_power`
- L301: `panel_eff_map`
- L302: `mppt_eff_map`
- L303: `ocv_soc_map`
- L304: `dt` (default: `600.0`)
- L305: `horizon_steps` (default: `9`)
- L306: `v_max_kmh` (default: `110.0`)
- L307: `terminal_soc_min` (default: `0.1`)
- L308: `stop_yaml` (default: `inputs/stop_points.yaml`)
- L309: `forecast_time_mode` (default: `auto`)
- L310: `forecast_time_tz` (default: `UTC`)
- L311: `forecast_start_time_utc`
- L312: `forecast_time_offset_sec` (default: `0.0`)
- L313: `forecast_reload_sec` (default: `60.0`)
- L314: `replan_on_forecast_reload` (default: `False`)
- L315: `params_yaml`
- L316: `profile_runtime_mode`
- L317: `route_profile_csv`
- L318: `speed_profile_csv`
- L319: `drive_schedule_yaml`
- L320: `initial_upper_policy_csv`
- L321: `use_measured_s` (default: `True`)
- L322: `use_measured_speed` (default: `True`)
- L323: `soc0` (default: `0.95`)
- L324: `Tb0` (default: `30.0`)
- L325: `s0_km` (default: `0.0`)
- L326: `speed_meas_timeout_sec` (default: `3.0`)
- L327: `distance_meas_timeout_sec` (default: `5.0`)
- L328: `battery_meas_timeout_sec` (default: `15.0`)
- L329: `speed_meas_filter_tau_sec` (default: `0.6`)
- L330: `speed_meas_max_accel_kmhps` (default: `12.0`)

## ROS topic I/O

- Publisher L737: `/planner/speed_cmd`
- Publisher L738: `/planner/upper_speed_cmd`
- Publisher L739: `/planner/throttle_cmd_pct`
- Publisher L740: `/planner/drive_mode`
- Publisher L741: `/planner/trajectory`
- Publisher L742: `/planner/upper_plan`
- Publisher L743: `/planner/lower_plan`
- Publisher L744: `/planner/env`
- Publisher L745: `/planner/metrics`
- Publisher L746: `/planner/status`
- Publisher L2700: `/planner/speed_cmd`
- Publisher L2701: `/planner/trajectory`
- Publisher L2702: `/planner/status`
- Publisher L2703: `/system/mpc_state`
- Subscription L749: `/vehicle/s_km` -> `self._on_s_km_solar`
- Subscription L750: `/vehicle/speed_kmh` -> `self._on_speed_solar`
- Subscription L751: `/vehicle/batt_soc` -> `self._on_soc_solar`
- Subscription L752: `/vehicle/batt_temp_c` -> `self._on_tb_solar`
- Subscription L753: `/vehicle/batt_current_a` -> `self._on_i_solar`
- Subscription L754: `/vehicle/batt_voltage_v` -> `self._on_v_solar`
- Subscription L755: `/calib/solar_gain` -> `self._on_calib_solar_gain`
- Subscription L756: `/calib/drive_power_gain` -> `self._on_calib_drive_power_gain`
- Subscription L757: `/calib/aux_power_w` -> `self._on_calib_aux_power`
- Subscription L2688: `/vehicle/s_km` -> `self._on_s_km`
- Subscription L2689: `/vehicle/speed_kmh` -> `self._on_speed`
- Subscription L2690: `/vehicle/fuel_rate_lph` -> `self._on_fuel`
- Subscription L2691: `/vehicle/throttle_pct` -> `self._on_throttle`
- Subscription L2692: `/vehicle/obd_ok` -> `self._on_obd_ok`
- Subscription L2693: `/vehicle/grade` -> `self._on_grade`
- Subscription L2694: `/vehicle/idle_fuel_lph` -> `self._on_idle_fuel`
- Subscription L2695: `/system/config` -> `self._on_config`
- Subscription L2696: `/system/config_ready` -> `self._on_config_ready`
- Subscription L2697: `/system/state` -> `self._on_system_state`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
