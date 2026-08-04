# 03. live_wifi ROS2 launch 入口

- ファイル: `launch/solar_race_live_wifi.launch.py`
- 種別: `ROS 2 launch Python`
- 区分: `launch`

## 役割

WiFi テレメトリ、風補正、live MPC 運用をまとめて起動する launch 入口。

## 起動文脈

- 起動文脈: live_wifi モード起動時に ros2 launch される。
- 呼び出し元: `scripts/solar_control.sh`, `SolarSim.ps1`
- 次に読むべきファイル: `mpc_solarcar/live_launch.py`, `mpc_solarcar/telemetry_text_bridge_node.py`, `mpc_solarcar/wind_correction_node.py`

## 主要ポイント

- profile_yaml を launch 引数として受ける。
- 共通 live node 群に WiFi bridge と wind correction を追加する。
- live forecast の raw/corrected CSV の入口でもある。

## 主要構造

主要関数は generate_launch_description。 launch から起動する Node action は 2 件。

## ファイルを上から読んだときの定義順

- L12: 関数 _setup を定義する。
- L62: 関数 generate_launch_description を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from launch import LaunchDescription`
  - launch が実行すべき action 群をまとめるため。 このファイル内での主な使用位置は L63。
- L4: `from launch.actions import DeclareLaunchArgument, OpaqueFunction`
  - DeclareLaunchArgument や OpaqueFunction など launch action を使うため。 このファイル内での主な使用位置は L65, L66。
- L5: `from launch.substitutions import LaunchConfiguration`
  - launch 引数の実行時値を参照するため。 このファイル内での主な使用位置は L13。
- L6: `from launch_ros.actions import Node`
  - ROS 2 ノード起動 action を launch から記述するため。 このファイル内での主な使用位置は L25, L41。
- L8: `from mpc_solarcar.live_launch import build_live_nodes, live_forecast_paths`
  - live系 node 構成ビルダ から build_live_nodes, live_forecast_paths を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/live_launch.py。 このファイル内での主な使用位置は L20, L22。
- L9: `from mpc_solarcar.solar_profile import get_section, load_profile`
  - profile YAML 読込と検証 から get_section, load_profile を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L14, L15, L16, L17, L18。

## 関数・クラスを上から順に解説

### L12 関数 `_setup`

- 定義: `_setup(context)`
- このブロックが直接呼ぶ主な関数/メソッド: `LaunchConfiguration`, `Node`, `append`, `bool`, `build_live_nodes`, `float`, `get`, `get_section`, `items`, `live_forecast_paths`, `load_profile`, `perform`
- 戻り値の要点: `nodes`
- 上から順の処理:
  1. profile_yaml に LaunchConfiguration('profile_yaml').perform(context) の結果を代入する。
  2. (profile_path, cfg) に load_profile(profile_yaml) の結果を代入する。
  3. live_cfg に get_section(cfg, 'live') の結果を代入する。
  4. wifi_cfg に get_section(live_cfg, 'wifi_bridge') の結果を代入する。
  5. wind_cfg に get_section(live_cfg, 'wind_model') の結果を代入する。
  6. model_cfg に get_section(cfg, 'model') の結果を代入する。
  7. (_base_csv, raw_forecast_csv, corrected_csv) に live_forecast_paths(profile_path, cfg) の結果を代入する。
  8. nodes に build_live_nodes(profile_path, cfg, use_wifi=True) の結果を代入する。
  9. 条件 bool(wifi_cfg.get('enabled', True)) を判定し、真なら内部処理を行う。
  10. 条件 bool(wind_cfg.get('enabled', True)) を判定し、真なら内部処理を行う。

### L62 関数 `generate_launch_description`

- 定義: `generate_launch_description()`
- このブロックが直接呼ぶ主な関数/メソッド: `DeclareLaunchArgument`, `LaunchDescription`, `OpaqueFunction`
- 戻り値の要点: `LaunchDescription([DeclareLaunchArgument('profile_yaml', default_value='config/solar/bwsc_2027_demo.yaml'), OpaqueFunction(function=_setup)])`
- 上から順の処理:
  1. LaunchDescription([DeclareLaunchArgument('profile_yaml', default_value='config/solar/bwsc_2027_demo.yaml'), OpaqueFunction(function=_setup)]) を返す。


## launch から起動するノード

- L25: `telemetry_text_bridge_node` (package=mpc_solarcar, name=telemetry_text_bridge_node)
- L41: `wind_correction_node` (package=mpc_solarcar, name=wind_correction_node)

## 処理の流れ

1. launch 引数を受け取り、profile を読み込む。
2. Node action を動的に組み立てる。
3. LaunchDescription として ROS 2 launch へ返す。
