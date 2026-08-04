# 24. live 自動校正ノード

- ファイル: `mpc_solarcar/solar_autocal_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

観測 solar/pack power と planner 予測との差から solar_gain、drive_power_gain、aux_power_w を推定 publish する。

## 起動文脈

- 起動文脈: 運用中に mpc_node の係数を微調整する補助ノード。
- 呼び出し元: `mpc_solarcar/live_launch.py`
- 次に読むべきファイル: `mpc_solarcar/solar_autocal_logic.py`, `mpc_solarcar/mpc_node.py`

## 主要ポイント

- /calib/* topic を publish する。
- mpc_node がそれを購読して内部 gain を更新する。

## 主要構造

主要クラスは SolarAutocalNode。 主要関数は main。 ROS パラメータ宣言は 14 件。 ROS I/O は publisher 4 件、subscription 6 件。

## ファイルを上から読んだときの定義順

- L13: 関数 _clamp を定義する。
- L17: クラス SolarAutocalNode を定義する。
- L153: 関数 main を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L50, L51, L52, L53, L54, L55, L69, L70, ...。
- L5: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L154, L156, L158。
- L6: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L17。
- L8: `from std_msgs.msg import Float32, Float32MultiArray, String`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L57, L58, L59, L60, L62, L63, L64, L65, ...。
- L10: `from .solar_autocal_logic import daytime_stationary_aux_estimate`
  - 自動校正ロジック関数群 から daytime_stationary_aux_estimate を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_autocal_logic.py。 このファイル内での主な使用位置は L110。

## 関数・クラスを上から順に解説

### L13 関数 `_clamp`

- 定義: `_clamp(value, lo, hi)`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `max`, `min`
- 戻り値の要点: `max(float(lo), min(float(hi), float(value)))`
- 上から順の処理:
  1. max(float(lo), min(float(hi), float(value))) を返す。

### L17 クラス `SolarAutocalNode`

- 定義: `SolarAutocalNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `Float32`, `String`, `__init__`, `_clamp`, `_ema`, `abs`, `create_publisher`, `create_subscription`, `create_timer`, `daytime_stationary_aux_estimate`, `declare_parameter`, `float`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _on_speed を定義する。
  3. 関数 _on_current を定義する。
  4. 関数 _on_voltage を定義する。
  5. 関数 _on_solar を定義する。
  6. 関数 _on_env を定義する。
  7. 関数 _on_metrics を定義する。
  8. 関数 _ema を定義する。
  9. 関数 _step を定義する。

### L153 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `SolarAutocalNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に SolarAutocalNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。


## パラメータ

- L20: `publish_period_sec` (default: `30.0`)
- L21: `stationary_speed_kmh` (default: `2.0`)
- L22: `drive_speed_kmh` (default: `25.0`)
- L23: `day_ghi_threshold` (default: `150.0`)
- L24: `alpha` (default: `0.2`)
- L25: `solar_gain_init` (default: `1.0`)
- L26: `drive_power_gain_init` (default: `1.0`)
- L27: `aux_power_w_init` (default: `8.0`)
- L28: `solar_gain_min` (default: `0.5`)
- L29: `solar_gain_max` (default: `1.5`)
- L30: `drive_power_gain_min` (default: `0.7`)
- L31: `drive_power_gain_max` (default: `1.4`)
- L32: `aux_power_w_min` (default: `0.0`)
- L33: `aux_power_w_max` (default: `300.0`)

## ROS topic I/O

- Publisher L57: `/calib/solar_gain`
- Publisher L58: `/calib/drive_power_gain`
- Publisher L59: `/calib/aux_power_w`
- Publisher L60: `/calib/status`
- Subscription L62: `/vehicle/speed_kmh` -> `self._on_speed`
- Subscription L63: `/vehicle/batt_current_a` -> `self._on_current`
- Subscription L64: `/vehicle/batt_voltage_v` -> `self._on_voltage`
- Subscription L65: `/vehicle/solar_power_w` -> `self._on_solar`
- Subscription L66: `/planner/env` -> `self._on_env`
- Subscription L67: `/planner/metrics` -> `self._on_metrics`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
