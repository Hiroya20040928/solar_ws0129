# 29. solar 運用 CSV logger

- ファイル: `mpc_solarcar/solar_logger_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

vehicle、planner、weather、calib、system、raw telemetry を一つの時刻行へ集約して CSV に書く。

## 起動文脈

- 起動文脈: 運用ログの最終集約点。
- 呼び出し元: `mpc_solarcar/live_launch.py`, `launch/solar_measurement.launch.py`
- 次に読むべきファイル: 特になし

## 主要ポイント

- topic 名と CSV 列名の対応を内部辞書で持つ。
- planner/env、planner/metrics、planner/status も記録する。

## 主要構造

主要クラスは SolarLoggerNode。 主要関数は handler, handler, handler, destroy_node, main。 ROS パラメータ宣言は 6 件。 ROS I/O は publisher 0 件、subscription 6 件。

## ファイルを上から読んだときの定義順

- L11: FLOAT_TOPICS に {'speed_kmh': '/vehicle/speed_kmh', 's_km': '/vehicle/s_km', 'altitude_m': '/vehicle/altitude_m', 'grade_pct': '/vehicle/grade', 'batt_soc': '/vehicle/batt_soc', 'batt_temp_c': '/vehicle/batt_temp_c', 'batt_current_a': '/vehicle/batt_current_a', 'batt_voltage_v': '/vehicle/batt_voltage_v', 'solar_power_w': '/vehicle/solar_power_w', 'headwind_meas_ms': '/weather/headwind_meas_ms', 'headwind_corrected_ms': '/weather/headwind_corrected_ms', 'wind_speed_ms': '/weather/wind_speed_ms', 'wind_dir_deg': '/weather/wind_dir_deg', 'course_deg': '/weather/course_deg', 'speed_cmd_kmh': '/planner/speed_cmd', 'upper_speed_cmd_kmh': '/planner/upper_speed_cmd', 'throttle_cmd_pct': '/planner/throttle_cmd_pct', 'calib_solar_gain': '/calib/solar_gain', 'calib_drive_power_gain': '/calib/drive_power_gain', 'calib_aux_power_w': '/calib/aux_power_w', 'system_health': '/system/health'} の結果を代入する。
- L35: FLOAT64_TOPICS に {'solar_source_ts_unix': '/telemetry/solar_source_ts_unix', 'chase_source_ts_unix': '/telemetry/chase_source_ts_unix'} の結果を代入する。
- L40: STRING_TOPICS に {'drive_mode': '/planner/drive_mode', 'system_state': '/system/state', 'system_diag': '/system/diag', 'mpc_state': '/system/mpc_state', 'telemetry_bridge_status': '/telemetry/bridge_status', 'wind_correction_status': '/weather/wind_correction_status', 'weather_fetch_status': '/weather/fetch_status', 'autocal_status': '/calib/status', 'raw_solar': '/telemetry/raw_solar', 'raw_chase': '/telemetry/raw_chase'} の結果を代入する。
- L53: ARRAY_TOPICS に {'/planner/status': ['planner_soc', 'planner_temp_c', 'planner_s_km', 'planner_step', 'planner_sec_to_next', 'planner_control_stop_hold', 'planner_control_stop_remaining_sec', 'planner_control_stop_completed_count'], '/planner/metrics': ['model_pack_voltage_v', 'model_pack_current_a', 'model_soc', 'model_motor_power_w', 'model_motor_current_a', 'model_pv_power_w', 'model_speed_kmh', 'model_mech_power_w', 'model_pack_power_w'], '/planner/env': ['env_poa_wm2', 'env_cell_temp_c', 'env_ambient_temp_c', 'env_grade_pct', 'env_headwind_ms']} の結果を代入する。
- L85: クラス SolarLoggerNode を定義する。
- L192: 関数 main を定義する。

## import 群

- L1: `import csv`
  - CSV の逐次読込・逐次書込を行うため。 このファイル内での主な使用位置は L133。
- L2: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L109, L144, L158, L168。
- L3: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L95, L101, L103。
- L4: `from datetime import datetime, timezone`
  - UTC 時刻や相対時間を扱うため。 このファイル内での主な使用位置は L102, L172。
- L6: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L193, L196, L199。
- L7: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L85。
- L8: `from std_msgs.msg import Float32, Float32MultiArray, Float64, String`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L115, L117, L119, L121, L126, L129。

## 関数・クラスを上から順に解説

### L85 クラス `SolarLoggerNode`

- 定義: `SolarLoggerNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `DictWriter`, `__init__`, `_clean_float`, `_set_array`, `_set_float`, `_set_string`, `append`, `close`, `create_subscription`, `create_timer`, `declare_parameter`, `destroy_node`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _set_float を定義する。
  3. 関数 _set_string を定義する。
  4. 関数 _set_array を定義する。
  5. 関数 _clean_float を定義する。
  6. 関数 _write_row を定義する。
  7. 関数 destroy_node を定義する。

### L192 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `SolarLoggerNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に SolarLoggerNode() の結果を代入する。
  3. 例外処理を伴う try ブロックを実行する。


## パラメータ

- L88: `log_dir` (default: `outputs/logs`)
- L89: `file_prefix` (default: `solar_live`)
- L90: `log_rate_hz` (default: `2.0`)
- L91: `flush_every_rows` (default: `1`)
- L92: `output_speed_topic` (default: `/vehicle/speed_cmd_kmh`)
- L93: `output_drive_mode_topic` (default: `/vehicle/drive_mode_cmd`)

## ROS topic I/O

- Subscription L115: `topic` -> `self._set_float(field)`
- Subscription L117: `topic` -> `self._set_float(field)`
- Subscription L119: `topic` -> `self._set_string(field)`
- Subscription L121: `topic` -> `self._set_array(fields)`
- Subscription L126: `output_speed_topic` -> `self._set_float('output_speed_cmd_kmh')`
- Subscription L129: `output_mode_topic` -> `self._set_string('output_drive_mode')`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
