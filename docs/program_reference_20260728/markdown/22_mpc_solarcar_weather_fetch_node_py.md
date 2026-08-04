# 22. live forecast 取得ノード

- ファイル: `mpc_solarcar/weather_fetch_node.py`
- 種別: `Python`
- 区分: `runtime node`

## 役割

chase GPS または fallback 座標から Open-Meteo forecast を取得し、planner が読む CSV を更新する。

## 起動文脈

- 起動文脈: live 系の forecast 更新入口。
- 呼び出し元: `mpc_solarcar/live_launch.py`
- 次に読むべきファイル: `mpc_solarcar/weather_utils.py`, `mpc_solarcar/wind_correction_node.py`

## 主要ポイント

- raw forecast CSV を定期更新する。
- planner 自体は topic ではなく forecast CSV を読む。

## 主要構造

主要クラスは WeatherFetchNode。 主要関数は main。 ROS パラメータ宣言は 11 件。 ROS I/O は publisher 1 件、subscription 1 件。

## ファイルを上から読んだときの定義順

- L15: クラス WeatherFetchNode を定義する。
- L138: 関数 main を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L85, L86。
- L5: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L39, L40, L44, L48, L52, L56, L60, L69, ...。
- L6: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L15。
- L8: `from sensor_msgs.msg import NavSatFix`
  - GPS 緯度経度高度を ROS topic でやり取りするため。 このファイル内での主な使用位置は L99, L104。
- L9: `from std_msgs.msg import String`
  - Float32 や String など軽量メッセージで planner / vehicle 値を publish するため。 このファイル内での主な使用位置は L98, L130, L134。
- L11: `from .solar_profile import get_path, get_section, load_profile`
  - profile YAML 読込と検証 から get_path, get_section, load_profile を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L32, L33, L34, L35, L39。
- L12: `from .weather_utils import fetch_openmeteo_forecast, write_forecast_csv`
  - weather_utils.py から fetch_openmeteo_forecast, write_forecast_csv を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/weather_utils.py。 このファイル内での主な使用位置は L115, L123, L128。

## 関数・クラスを上から順に解説

### L15 クラス `WeatherFetchNode`

- 定義: `WeatherFetchNode(bases=Node)`
- このブロックが直接呼ぶ主な関数/メソッド: `Parameter`, `Path`, `String`, `__init__`, `_fetch_once`, `create_publisher`, `create_subscription`, `create_timer`, `declare_parameter`, `error`, `expanduser`, `fetch_openmeteo_forecast`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _on_gps を定義する。
  3. 関数 _fetch_once を定義する。

### L138 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `WeatherFetchNode`, `destroy_node`, `init`, `shutdown`, `spin`
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に WeatherFetchNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。


## パラメータ

- L18: `profile_yaml`
- L19: `output_csv`
- L20: `raw_forecast_csv`
- L21: `gps_topic` (default: `/chase/gps`)
- L22: `fetch_period_sec` (default: `3600.0`)
- L23: `forecast_days` (default: `3`)
- L24: `step_minutes` (default: `10`)
- L25: `timezone_name` (default: `Australia/Darwin`)
- L26: `fallback_latitude` (default: `-12.4634`)
- L27: `fallback_longitude` (default: `130.8456`)
- L28: `tcell_gain` (default: `0.03`)

## ROS topic I/O

- Publisher L98: `/weather/fetch_status`
- Subscription L99: `self.gps_topic` -> `self._on_gps`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
