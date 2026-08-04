# 06. measure ROS2 launch 入口

- ファイル: `launch/solar_measurement.launch.py`
- 種別: `ROS 2 launch Python`
- 区分: `launch`

## 役割

実測収集用に preflight、distance、grade、logger、dashboard を起動する launch。

## 起動文脈

- 起動文脈: measure モード起動時に ros2 launch される。
- 呼び出し元: `scripts/solar_control.sh`, `SolarSim.ps1`
- 次に読むべきファイル: `mpc_solarcar/distance_node.py`, `mpc_solarcar/grade_node.py`, `mpc_solarcar/solar_logger_node.py`

## 主要ポイント

- planner を起動せず、計測系だけを立てる。
- distance/grade は profile の measurement 設定で可否が決まる。

## 主要構造

主要関数は generate_launch_description。 launch から起動する Node action は 5 件。

## ファイルを上から読んだときの定義順

- L11: 関数 _cfg_path を定義する。
- L15: 関数 _setup を定義する。
- L97: 関数 generate_launch_description を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from launch import LaunchDescription`
  - launch が実行すべき action 群をまとめるため。 このファイル内での主な使用位置は L98。
- L4: `from launch.actions import DeclareLaunchArgument, OpaqueFunction`
  - DeclareLaunchArgument や OpaqueFunction など launch action を使うため。 このファイル内での主な使用位置は L100, L101。
- L5: `from launch.substitutions import LaunchConfiguration`
  - launch 引数の実行時値を参照するため。 このファイル内での主な使用位置は L16。
- L6: `from launch_ros.actions import Node`
  - ROS 2 ノード起動 action を launch から記述するため。 このファイル内での主な使用位置は L26, L39, L50, L65, L79。
- L8: `from mpc_solarcar.solar_profile import get_section, load_profile, resolve_relative_path`
  - profile YAML 読込と検証 から get_section, load_profile, resolve_relative_path を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L12, L17, L18, L19, L20, L21, L22, L23。

## 関数・クラスを上から順に解説

### L11 関数 `_cfg_path`

- 定義: `_cfg_path(profile_path, raw)`
- このブロックが直接呼ぶ主な関数/メソッド: `resolve_relative_path`, `str`, `strip`
- 戻り値の要点: `resolve_relative_path(profile_path.parent, raw) if str(raw or '').strip() else ''`
- 上から順の処理:
  1. resolve_relative_path(profile_path.parent, raw) if str(raw or '').strip() else '' を返す。

### L15 関数 `_setup`

- 定義: `_setup(context)`
- このブロックが直接呼ぶ主な関数/メソッド: `LaunchConfiguration`, `Node`, `_cfg_path`, `append`, `bool`, `float`, `get`, `get_section`, `int`, `load_profile`, `perform`, `str`
- 戻り値の要点: `nodes`
- 上から順の処理:
  1. profile_yaml に LaunchConfiguration('profile_yaml').perform(context) の結果を代入する。
  2. (profile_path, cfg) に load_profile(profile_yaml) の結果を代入する。
  3. runtime_cfg に get_section(cfg, 'runtime') の結果を代入する。
  4. logging_cfg に get_section(cfg, 'logging') の結果を代入する。
  5. measurement_cfg に get_section(cfg, 'measurement') の結果を代入する。
  6. distance_cfg に get_section(measurement_cfg, 'distance') の結果を代入する。
  7. grade_cfg に get_section(measurement_cfg, 'grade') の結果を代入する。
  8. meas_logging_cfg に get_section(measurement_cfg, 'logging') の結果を代入する。
  9. nodes に [Node(package='mpc_solarcar', executable='solar_preflight_node', name='solar_preflight_node', parameters=[{'require_speed': True, 'require_distance': bool(measurement_cfg.get('use_distance_node', True)), 'require_battery': False, 'require_planner': False}]), Node(package='mpc_solarcar', executable='dashboard_node', name='dashboard_node', parameters=[{'host': str(runtime_cfg.get('dashboard_host', '0.0.0.0')), 'port': int(runtime_cfg.get('dashboard_port', 8080))}]), Node(package='mpc_solarcar', executable='solar_logger_node', name='solar_logger_node', parameters=[{'log_dir': _cfg_path(profile_path, str(logging_cfg.get('log_dir', 'outputs/logs'))), 'file_prefix': str(meas_logging_cfg.get('file_prefix', 'solar_measurement')), 'log_rate_hz': float(logging_cfg.get('log_rate_hz', 2.0))}])] の結果を代入する。
  10. 条件 bool(measurement_cfg.get('use_distance_node', True)) を判定し、真なら内部処理を行う。

### L97 関数 `generate_launch_description`

- 定義: `generate_launch_description()`
- このブロックが直接呼ぶ主な関数/メソッド: `DeclareLaunchArgument`, `LaunchDescription`, `OpaqueFunction`
- 戻り値の要点: `LaunchDescription([DeclareLaunchArgument('profile_yaml', default_value='config/solar/bwsc_2027_demo.yaml'), OpaqueFunction(function=_setup)])`
- 上から順の処理:
  1. LaunchDescription([DeclareLaunchArgument('profile_yaml', default_value='config/solar/bwsc_2027_demo.yaml'), OpaqueFunction(function=_setup)]) を返す。


## launch から起動するノード

- L26: `solar_preflight_node` (package=mpc_solarcar, name=solar_preflight_node)
- L39: `dashboard_node` (package=mpc_solarcar, name=dashboard_node)
- L50: `solar_logger_node` (package=mpc_solarcar, name=solar_logger_node)
- L65: `distance_node` (package=mpc_solarcar, name=distance_node)
- L79: `grade_node` (package=mpc_solarcar, name=grade_node)

## 処理の流れ

1. launch 引数を受け取り、profile を読み込む。
2. Node action を動的に組み立てる。
3. LaunchDescription として ROS 2 launch へ返す。
