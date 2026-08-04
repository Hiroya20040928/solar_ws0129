# 04. live ROS2 launch 入口

- ファイル: `launch/solar_race_live.launch.py`
- 種別: `ROS 2 launch Python`
- 区分: `launch`

## 役割

WiFi 文字列 bridge を使わない live 運用の基本 launch。

## 起動文脈

- 起動文脈: live モード起動時に ros2 launch される。
- 呼び出し元: `scripts/solar_control.sh`, `SolarSim.ps1`
- 次に読むべきファイル: `mpc_solarcar/live_launch.py`, `mpc_solarcar/mpc_node.py`

## 主要ポイント

- profile を読み build_live_nodes に委譲する。
- ノード構成の本体は live_launch.py にある。

## 主要構造

主要関数は generate_launch_description。

## ファイルを上から読んだときの定義順

- L10: 関数 _setup を定義する。
- L16: 関数 generate_launch_description を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from launch import LaunchDescription`
  - launch が実行すべき action 群をまとめるため。 このファイル内での主な使用位置は L17。
- L4: `from launch.actions import DeclareLaunchArgument, OpaqueFunction`
  - DeclareLaunchArgument や OpaqueFunction など launch action を使うため。 このファイル内での主な使用位置は L19, L20。
- L5: `from launch.substitutions import LaunchConfiguration`
  - launch 引数の実行時値を参照するため。 このファイル内での主な使用位置は L11。
- L6: `from mpc_solarcar.live_launch import build_live_nodes`
  - live系 node 構成ビルダ から build_live_nodes を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/live_launch.py。 このファイル内での主な使用位置は L13。
- L7: `from mpc_solarcar.solar_profile import load_profile`
  - profile YAML 読込と検証 から load_profile を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L12。

## 関数・クラスを上から順に解説

### L10 関数 `_setup`

- 定義: `_setup(context)`
- このブロックが直接呼ぶ主な関数/メソッド: `LaunchConfiguration`, `build_live_nodes`, `load_profile`, `perform`
- 戻り値の要点: `build_live_nodes(profile_path, cfg, use_wifi=False)`
- 上から順の処理:
  1. profile_yaml に LaunchConfiguration('profile_yaml').perform(context) の結果を代入する。
  2. (profile_path, cfg) に load_profile(profile_yaml) の結果を代入する。
  3. build_live_nodes(profile_path, cfg, use_wifi=False) を返す。

### L16 関数 `generate_launch_description`

- 定義: `generate_launch_description()`
- このブロックが直接呼ぶ主な関数/メソッド: `DeclareLaunchArgument`, `LaunchDescription`, `OpaqueFunction`
- 戻り値の要点: `LaunchDescription([DeclareLaunchArgument('profile_yaml', default_value='config/solar/bwsc_2027_demo.yaml'), OpaqueFunction(function=_setup)])`
- 上から順の処理:
  1. LaunchDescription([DeclareLaunchArgument('profile_yaml', default_value='config/solar/bwsc_2027_demo.yaml'), OpaqueFunction(function=_setup)]) を返す。


## 処理の流れ

1. launch 引数を受け取り、profile を読み込む。
