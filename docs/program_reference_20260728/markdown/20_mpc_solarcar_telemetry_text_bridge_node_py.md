# 20. WiFi 文字列テレメトリ bridge

- ファイル: `mpc_solarcar/telemetry_text_bridge_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

車両側・伴走車側から届く UDP 文字列を ROS topic に変換し、planner 指令を逆向きに文字列送信する。

## 起動文脈

- 起動文脈: live_wifi のセンサ入口と outbound command bridge を兼ねる。
- 呼び出し元: `launch/solar_race_live_wifi.launch.py`
- 次に読むべきファイル: `mpc_solarcar/telemetry_protocol.py`, `mpc_solarcar/speed_command_bridge_node.py`

## 主要ポイント

- inbound と outbound の両方向を持つ。
- speed、battery、distance、GPS、wind を ROS topic 化する。
- planner command を JSON/テキストで送り返す。

## 主要構造

主要クラスは TelemetryTextBridgeNode。 主要関数は parse_text_payload, headwind_component_ms, main。 ROS パラメータ宣言は 27 件。 ROS I/O は publisher 20 件、subscription 6 件。

## ファイルを上から読んだときの定義順

- L19: 関数 _safe_float を定義する。
- L32: 関数 _parse_key_value_text を定義する。
- L53: 関数 parse_text_payload を定義する。
- L66: 関数 headwind_component_ms を定義する。
- L79: クラス TelemetryTextBridgeNode を定義する。
- L349: 関数 main を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `import json`
  - manifest、checkpoint、UDP payload をやり取りするため。 このファイル内での主な使用位置は L58, L321。
- L4: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L27, L75, L76, L180, L181, L182。
- L5: `import socket`
  - socket モジュールを利用するため。 このファイル内での主な使用位置は L166, L169。
- L6: `import time`
  - wall/monotonic time に基づく周期制御や freshness 判定を行うため。 このファイル内での主な使用位置は L216, L254, L292, L330。
- L7: `from statistics import NormalDist`
  - statistics から NormalDist を読み込み、このファイルの処理を組み立てるため。 このファイル内での使用位置は少ないか、間接利用である。
- L9: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L350, L352, L354。
- L10: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L79。
- L12: `from sensor_msgs.msg import NavSatFix`
  - GPS 緯度経度高度を ROS topic でやり取りするため。 このファイル内での主な使用位置は L153, L154, L241。
- L13: `from std_msgs.msg import Float32, Float64, String`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L143, L144, L145, L146, L147, L148, L149, L150, ...。
- L15: `from .signal_utils import RobustScalarFilter`
  - signal_utils.py から RobustScalarFilter を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/signal_utils.py。 このファイル内での主な使用位置は L124, L132, L133, L134, L135, L136, L137。
- L16: `from .telemetry_protocol import utc_iso_now, validate_source_timestamp`
  - telemetry_protocol.py から utc_iso_now, validate_source_timestamp を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/telemetry_protocol.py。 このファイル内での主な使用位置は L214, L331。

## 関数・クラスを上から順に解説

### L19 関数 `_safe_float`

- 定義: `_safe_float(payload, *keys)`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `isfinite`
- 戻り値の要点: `None / value`
- 上から順の処理:
  1. keys を順に走査し、各要素を key に入れて処理する。
  2. None を返す。

### L32 関数 `_parse_key_value_text`

- 定義: `_parse_key_value_text(text)`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `replace`, `split`, `strip`
- 戻り値の要点: `payload`
- 上から順の処理:
  1. payload に {} を代入する。
  2. text.replace(';', ',').replace('\n', ',').split(',') を順に走査し、各要素を token に入れて処理する。
  3. payload を返す。

### L53 関数 `parse_text_payload`

- 定義: `parse_text_payload(text)`
- このブロックが直接呼ぶ主な関数/メソッド: `_parse_key_value_text`, `isinstance`, `loads`, `str`, `strip`
- 戻り値の要点: `_parse_key_value_text(raw) / {} / parsed`
- 上から順の処理:
  1. raw に str(text or '').strip() の結果を代入する。
  2. 条件 not raw を判定し、真なら内部処理を行う。
  3. 例外処理を伴う try ブロックを実行する。
  4. _parse_key_value_text(raw) を返す。

### L66 関数 `headwind_component_ms`

- 定義: `headwind_component_ms(payload)`
- このブロックが直接呼ぶ主な関数/メソッド: `_safe_float`, `cos`, `float`, `radians`
- 戻り値の要点: `float(wind_speed * math.cos(rel)) / direct / None`
- 上から順の処理:
  1. direct に _safe_float(payload, 'headwind_ms') の結果を代入する。
  2. 条件 direct is not None を判定し、真なら内部処理を行う。
  3. wind_speed に _safe_float(payload, 'wind_speed_ms', 'wind_ms') の結果を代入する。
  4. wind_dir に _safe_float(payload, 'wind_dir_deg') の結果を代入する。
  5. course_deg に _safe_float(payload, 'course_deg', 'heading_deg') の結果を代入する。
  6. 条件 wind_speed is None or wind_dir is None or course_deg is None を判定し、真なら内部処理を行う。
  7. rel に math.radians((wind_dir - course_deg) % 360.0) の結果を代入する。
  8. float(wind_speed * math.cos(rel)) を返す。

### L79 クラス `TelemetryTextBridgeNode`

- 定義: `TelemetryTextBridgeNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `Float32`, `Float64`, `NavSatFix`, `RobustScalarFilter`, `String`, `__init__`, `_handle_chase_payload`, `_handle_vehicle_payload`, `_publish_gps`, `_publish_weather`, `_safe_float`, `_send_payload`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _set_outbound を定義する。
  3. 関数 _poll_socket を定義する。
  4. 関数 _publish_gps を定義する。
  5. 関数 _handle_vehicle_payload を定義する。
  6. 関数 _handle_chase_payload を定義する。
  7. 関数 _publish_weather を定義する。
  8. 関数 _send_payload を定義する。
  9. 関数 _send_outbound を定義する。

### L349 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `TelemetryTextBridgeNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に TelemetryTextBridgeNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。


## パラメータ

- L82: `enable_inbound` (default: `True`)
- L83: `enable_outbound` (default: `True`)
- L84: `bind_host` (default: `0.0.0.0`)
- L85: `bind_port` (default: `52001`)
- L86: `publish_period_sec` (default: `1.0`)
- L87: `solar_remote_host` (default: `192.168.50.21`)
- L88: `solar_remote_port` (default: `52002`)
- L89: `chase_remote_host` (default: `192.168.50.22`)
- L90: `chase_remote_port` (default: `52003`)
- L91: `send_to_solar` (default: `True`)
- L92: `send_to_chase` (default: `True`)
- L93: `prefer_direct_distance` (default: `False`)
- L94: `speed_filter_tau_sec` (default: `0.6`)
- L95: `speed_max_kmh` (default: `130.0`)
- L96: `speed_max_accel_kmhps` (default: `12.0`)
- L97: `speed_max_decel_kmhps` (default: `20.0`)
- L98: `distance_max_rate_kmps` (default: `0.06`)
- L99: `distance_max_backtrack_km` (default: `0.02`)
- L100: `battery_filter_tau_sec` (default: `1.0`)
- L101: `wind_filter_tau_sec` (default: `1.0`)
- L102: `headwind_filter_tau_sec` (default: `0.8`)
- L103: `max_abs_headwind_ms` (default: `25.0`)
- L104: `timestamp_required` (default: `True`)
- L105: `max_packet_age_sec` (default: `5.0`)
- L106: `max_future_skew_sec` (default: `2.0`)
- L107: `max_out_of_order_sec` (default: `0.0`)
- L108: `solar_power_gain_to_pack` (default: `1.0`)

## ROS topic I/O

- Publisher L143: `/telemetry/raw_solar`
- Publisher L144: `/telemetry/raw_chase`
- Publisher L145: `/vehicle/speed_kmh`
- Publisher L146: `/vehicle/batt_soc`
- Publisher L147: `/vehicle/batt_temp_c`
- Publisher L148: `/vehicle/batt_current_a`
- Publisher L149: `/vehicle/batt_voltage_v`
- Publisher L150: `/vehicle/solar_power_w`
- Publisher L151: `/vehicle/altitude_m`
- Publisher L152: `/vehicle/s_km`
- Publisher L153: `/vehicle/gps`
- Publisher L154: `/chase/gps`
- Publisher L155: `/chase/altitude_m`
- Publisher L156: `/weather/headwind_meas_ms`
- Publisher L157: `/weather/wind_speed_ms`
- Publisher L158: `/weather/wind_dir_deg`
- Publisher L159: `/weather/course_deg`
- Publisher L160: `/telemetry/bridge_status`
- Publisher L161: `/telemetry/solar_source_ts_unix`
- Publisher L162: `/telemetry/chase_source_ts_unix`
- Subscription L184: `/planner/speed_cmd` -> `lambda msg: self._set_outbound('speed_cmd_kmh', float(msg.data))`
- Subscription L185: `/planner/upper_speed_cmd` -> `lambda msg: self._set_outbound('upper_speed_cmd_kmh', float(msg.data))`
- Subscription L186: `/planner/drive_mode` -> `lambda msg: self._set_outbound('drive_mode', str(msg.data))`
- Subscription L187: `/vehicle/speed_kmh` -> `lambda msg: self._set_outbound('speed_meas_kmh', float(msg.data))`
- Subscription L188: `/vehicle/batt_soc` -> `lambda msg: self._set_outbound('soc', float(msg.data))`
- Subscription L189: `/vehicle/s_km` -> `lambda msg: self._set_outbound('s_km', float(msg.data))`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
