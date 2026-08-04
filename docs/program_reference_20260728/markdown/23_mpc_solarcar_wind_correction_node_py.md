# 23. live 風補正ノード

- ファイル: `mpc_solarcar/wind_correction_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

観測 headwind と現在距離から raw forecast CSV を補正し、corrected forecast CSV を書き出す。

## 起動文脈

- 起動文脈: live_wifi で planner 入力の風を上書きする前処理。
- 呼び出し元: `launch/solar_race_live_wifi.launch.py`
- 次に読むべきファイル: `mpc_solarcar/mpc_node.py`

## 主要ポイント

- planner は /weather/headwind_corrected_ms を直接読むのではない。
- corrected CSV を mpc_node が再読込して効かせる。

## 主要構造

主要クラスは WindCorrectionNode。 主要関数は main。 ROS パラメータ宣言は 14 件。 ROS I/O は publisher 2 件、subscription 2 件。

## ファイルを上から読んだときの定義順

- L16: 関数 _timestamp_ns を定義する。
- L20: クラス WindCorrectionNode を定義する。
- L154: 関数 main を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L52, L53, L111, L121, L122, L130, L131, L135。
- L4: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L72。
- L5: `from datetime import datetime, timezone`
  - UTC 時刻や相対時間を扱うため。 このファイル内での主な使用位置は L91, L109, L128。
- L6: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L38, L39。
- L7: `from statistics import NormalDist`
  - statistics から NormalDist を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L50。
- L9: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L17, L77, L79, L96, L119, L128, L140, L147。
- L10: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L155, L157, L159。
- L11: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L20。
- L13: `from std_msgs.msg import Float32, String`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L57, L58, L59, L60, L64, L67, L115, L151。

## 関数・クラスを上から順に解説

### L16 関数 `_timestamp_ns`

- 定義: `_timestamp_ns(value)`
- このブロックが直接呼ぶ主な関数/メソッド: `Timestamp`, `int`
- 戻り値の要点: `int(pd.Timestamp(value).value)`
- 上から順の処理:
  1. int(pd.Timestamp(value).value) を返す。

### L20 クラス `WindCorrectionNode`

- 定義: `WindCorrectionNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `Float32`, `NormalDist`, `Path`, `String`, `Timedelta`, `Timestamp`, `__init__`, `_interp_headwind_now`, `_load_base`, `abs`, `any`, `append`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _on_headwind を定義する。
  3. 関数 _on_s を定義する。
  4. 関数 _load_base を定義する。
  5. 関数 _interp_headwind_now を定義する。
  6. 関数 _step を定義する。

### L154 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `WindCorrectionNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に WindCorrectionNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。


## パラメータ

- L23: `forecast_csv`
- L24: `corrected_forecast_csv` (default: `outputs/runtime/live_forecast_corrected.csv`)
- L25: `forecast_time_tz` (default: `Australia/Darwin`)
- L26: `publish_period_sec` (default: `30.0`)
- L27: `measurement_sigma_ms` (default: `1.0`)
- L28: `correlation_distance_km` (default: `300.0`)
- L29: `fallback_correlation_time_h` (default: `3.0`)
- L30: `forecast_sigma0_ms` (default: `1.5`)
- L31: `forecast_variance_growth_per_hour` (default: `0.05`)
- L32: `planning_quantile` (default: `0.5`)
- L33: `confidence_z` (default: `1.96`)
- L34: `min_sigma_ms` (default: `0.2`)
- L35: `preferred_source` (default: `auto`)
- L36: `use_exp_distance_decay` (default: `True`)

## ROS topic I/O

- Publisher L57: `/weather/headwind_corrected_ms`
- Publisher L58: `/weather/wind_correction_status`
- Subscription L59: `/weather/headwind_meas_ms` -> `self._on_headwind`
- Subscription L60: `/vehicle/s_km` -> `self._on_s`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
