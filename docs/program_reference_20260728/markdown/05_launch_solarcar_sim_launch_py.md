# 05. sim ROS2 launch 入口

- ファイル: `launch/solarcar_sim.launch.py`
- 種別: `ROS 2 launch Python`
- 区分: `launch`

## 役割

GPS 模擬、車体状態模擬、MPC、dashboard を立ち上げる simulation launch。

## 起動文脈

- 起動文脈: sim モード起動時に ros2 launch される。
- 呼び出し元: `scripts/solar_control.sh`, `SolarSim.ps1`
- 次に読むべきファイル: `mpc_solarcar/gps_sim_node.py`, `mpc_solarcar/solar_state_node.py`, `mpc_solarcar/mpc_node.py`

## 主要ポイント

- route/forecast/maps の存在確認を先に行う。
- sim 用の common_mpc パラメータ束を構成する。
- planner speed が GPS/state 側へ戻る閉ループを作る。

## 主要構造

主要関数は generate_launch_description。 launch から起動する Node action は 4 件。

## ファイルを上から読んだときの定義順

- L17: 関数 _cfg_path を定義する。
- L21: 関数 _setup を定義する。
- L146: 関数 generate_launch_description を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from launch import LaunchDescription`
  - launch が実行すべき action 群をまとめるため。 このファイル内での主な使用位置は L147。
- L4: `from launch.actions import DeclareLaunchArgument, OpaqueFunction`
  - DeclareLaunchArgument や OpaqueFunction など launch action を使うため。 このファイル内での主な使用位置は L149, L150。
- L5: `from launch.substitutions import LaunchConfiguration`
  - launch 引数の実行時値を参照するため。 このファイル内での主な使用位置は L22。
- L6: `from launch_ros.actions import Node`
  - ROS 2 ノード起動 action を launch から記述するため。 このファイル内での主な使用位置は L83, L95, L126, L132。
- L8: `from mpc_solarcar.solar_profile import get_path, get_section, load_profile, require_csv_data_rows, resolve_relative_path`
  - profile YAML 読込と検証 から get_path, get_section, load_profile, require_csv_data_rows, resolve_relative_path を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L18, L23, L24, L25, L27, L28, L29, L30, ...。

## 関数・クラスを上から順に解説

### L17 関数 `_cfg_path`

- 定義: `_cfg_path(profile_path, raw)`
- このブロックが直接呼ぶ主な関数/メソッド: `resolve_relative_path`, `str`, `strip`
- 戻り値の要点: `resolve_relative_path(profile_path.parent, raw) if str(raw or '').strip() else ''`
- 上から順の処理:
  1. resolve_relative_path(profile_path.parent, raw) if str(raw or '').strip() else '' を返す。

### L21 関数 `_setup`

- 定義: `_setup(context)`
- このブロックが直接呼ぶ主な関数/メソッド: `LaunchConfiguration`, `Node`, `float`, `get`, `get_path`, `get_section`, `int`, `items`, `load_profile`, `perform`, `require_csv_data_rows`, `str`
- 戻り値の要点: `[Node(package='mpc_solarcar', executable='gps_sim_node', name='gps_sim_node', parameters=[{'route_csv': route_waypoints_csv, 'dt': float(sim_cfg.get('gps_rate_hz', 1.0)), 'init_speed_kmh': float(sim_cfg.get('gps_init_speed_kmh', sim_cfg.get('v0_kmh', 45.0)))}]), Node(package='mpc_solarcar', executable='solar_state_node', name='solar_state_node', parameters=[{'profile_yaml': str(profile_path), 'forecast_csv': forecast_csv, 'route_profile_csv': route_profile_csv, 'params_yaml': str(profile_path), 'publish_rate_hz': float(sim_cfg.get('gps_rate_hz', 1.0)), 'init_speed_kmh': float(sim_cfg.get('v0_kmh', sim_cfg.get('gps_init_speed_kmh', 45.0))), 'soc0': float(sim_cfg.get('soc0', 0.95)), 'Tb0': float(sim_cfg.get('Tb0', 30.0)), 's0_km': float(sim_cfg.get('start_s_km', 0.0)), 'forecast_time_mode': str(sim_cfg.get('forecast_time_mode', runtime_cfg.get('forecast_time_mode', 'auto'))), 'forecast_time_tz': str(runtime_cfg.get('forecast_time_tz', 'Australia/Darwin')), 'forecast_start_time_utc': str(sim_cfg.get('forecast_start_time_utc', sim_cfg.get('start_utc', ''))), 'drive_eff_map': common_mpc['drive_eff_map'], 'regen_eff_map': common_mpc['regen_eff_map'], 'rint_map': common_mpc['rint_map'], 'panel_eff_map': common_mpc['panel_eff_map'], 'mppt_eff_map': common_mpc['mppt_eff_map'], 'drive_map_eco': common_mpc['drive_map_eco'], 'drive_map_power': common_mpc['drive_map_power'], 'regen_map_eco': common_mpc['regen_map_eco'], 'regen_map_power': common_mpc['regen_map_power'], 'ocv_soc_map': common_mpc['ocv_soc_map']}]), Node(package='mpc_solarcar', executable='mpc_node', name='mpc_node', parameters=[common_mpc]), Node(package='mpc_solarcar', executable='dashboard_node', name='dashboard_node', parameters=[{'host': str(runtime_cfg.get('dashboard_host', '0.0.0.0')), 'port': int(runtime_cfg.get('dashboard_port', 8080))}])]`
- 上から順の処理:
  1. profile_yaml に LaunchConfiguration('profile_yaml').perform(context) の結果を代入する。
  2. (profile_path, cfg) に load_profile(profile_yaml) の結果を代入する。
  3. runtime_cfg に get_section(cfg, 'runtime') の結果を代入する。
  4. sim_cfg に get_section(cfg, 'simulation') の結果を代入する。
  5. forecast_csv に get_path(cfg, profile_path, 'forecast_csv') の結果を代入する。
  6. route_waypoints_csv に get_path(cfg, profile_path, 'route_waypoints_csv') の結果を代入する。
  7. route_profile_csv に get_path(cfg, profile_path, 'route_profile_csv') の結果を代入する。
  8. speed_profile_csv に get_path(cfg, profile_path, 'speed_profile_csv') の結果を代入する。
  9. stop_yaml に get_path(cfg, profile_path, 'stop_yaml') の結果を代入する。
  10. drive_schedule_yaml に get_path(cfg, profile_path, 'drive_schedule_yaml') の結果を代入する。

### L146 関数 `generate_launch_description`

- 定義: `generate_launch_description()`
- このブロックが直接呼ぶ主な関数/メソッド: `DeclareLaunchArgument`, `LaunchDescription`, `OpaqueFunction`
- 戻り値の要点: `LaunchDescription([DeclareLaunchArgument('profile_yaml', default_value='config/solar/bwsc_2027_demo.yaml'), OpaqueFunction(function=_setup)])`
- 上から順の処理:
  1. LaunchDescription([DeclareLaunchArgument('profile_yaml', default_value='config/solar/bwsc_2027_demo.yaml'), OpaqueFunction(function=_setup)]) を返す。


## launch から起動するノード

- L83: `gps_sim_node` (package=mpc_solarcar, name=gps_sim_node)
- L95: `solar_state_node` (package=mpc_solarcar, name=solar_state_node)
- L126: `mpc_node` (package=mpc_solarcar, name=mpc_node)
- L132: `dashboard_node` (package=mpc_solarcar, name=dashboard_node)

## 処理の流れ

1. launch 引数を受け取り、profile を読み込む。
2. Node action を動的に組み立てる。
3. LaunchDescription として ROS 2 launch へ返す。
