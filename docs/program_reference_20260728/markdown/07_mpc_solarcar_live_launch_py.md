# 07. live系 node 構成ビルダ

- ファイル: `mpc_solarcar/live_launch.py`
- 種別: `Python`
- 区分: `launch helper`

## 役割

profile を読み、live と live_wifi で共通に使う node 群を Python から組み立てる。

## 起動文脈

- 起動文脈: launch/solar_race_live*.launch.py から呼ばれる。
- 呼び出し元: `launch/solar_race_live.launch.py`, `launch/solar_race_live_wifi.launch.py`
- 次に読むべきファイル: `mpc_solarcar/solar_profile.py`, `mpc_solarcar/mpc_node.py`, `mpc_solarcar/speed_command_bridge_node.py`

## 主要ポイント

- forecast CSV の raw/corrected パスを用意する。
- mpc_node、logger、dashboard、preflight などの Node action を返す。
- use_wifi の有無で planner が読む forecast CSV を切り替える。

## 主要構造

主要関数は cfg_path, live_forecast_paths, build_live_nodes。 launch から起動する Node action は 9 件。

## ファイルを上から読んだときの定義順

- L11: 関数 cfg_path を定義する。
- L15: 関数 _drop_keys を定義する。
- L20: 関数 live_forecast_paths を定義する。
- L39: 関数 build_live_nodes を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `import shutil`
  - shutil モジュールを利用するため。 このファイル内での主な使用位置は L35。
- L4: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L32, L33。
- L6: `from launch_ros.actions import Node`
  - ROS 2 ノード起動 action を launch から記述するため。 このファイル内での主な使用位置は L58, L72, L102, L113, L131, L140, L142, L145, ...。
- L8: `from .solar_profile import get_path, get_section, resolve_relative_path`
  - profile YAML 読込と検証 から get_path, get_section, resolve_relative_path を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L12, L21, L22, L23, L24, L40, L41, L42, ...。

## 関数・クラスを上から順に解説

### L11 関数 `cfg_path`

- 定義: `cfg_path(profile_path, raw)`
- このブロックが直接呼ぶ主な関数/メソッド: `resolve_relative_path`, `str`, `strip`
- 戻り値の要点: `resolve_relative_path(profile_path.parent, raw) if str(raw or '').strip() else ''`
- 上から順の処理:
  1. resolve_relative_path(profile_path.parent, raw) if str(raw or '').strip() else '' を返す。

### L15 関数 `_drop_keys`

- 定義: `_drop_keys(payload, *keys)`
- このブロックが直接呼ぶ主な関数/メソッド: `items`, `set`
- 戻り値の要点: `{key: value for key, value in (payload or {}).items() if key not in blocked}`
- 上から順の処理:
  1. blocked に set(keys) の結果を代入する。
  2. {key: value for key, value in (payload or {}).items() if key not in blocked} を返す。

### L20 関数 `live_forecast_paths`

- 定義: `live_forecast_paths(profile_path, cfg)`
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `cfg_path`, `copy2`, `exists`, `get`, `get_path`, `get_section`, `mkdir`, `str`
- 戻り値の要点: `(base_path, raw_path, corrected_path)`
- 上から順の処理:
  1. live_cfg に get_section(cfg, 'live') の結果を代入する。
  2. weather_cfg に get_section(live_cfg, 'weather') の結果を代入する。
  3. wind_cfg に get_section(live_cfg, 'wind_model') の結果を代入する。
  4. base_path に get_path(cfg, profile_path, 'forecast_csv') の結果を代入する。
  5. raw_path に cfg_path(profile_path, str(weather_cfg.get('raw_forecast_csv', ''))) の結果を代入する。
  6. 条件 not raw_path を判定し、真なら内部処理を行う。
  7. corrected_path に cfg_path(profile_path, str(wind_cfg.get('corrected_forecast_csv', ''))) の結果を代入する。
  8. 条件 not corrected_path を判定し、真なら内部処理を行う。
  9. (raw_path, corrected_path) を順に走査し、各要素を runtime_path に入れて処理する。
  10. (base_path, raw_path, corrected_path) を返す。

### L39 関数 `build_live_nodes`

- 定義: `build_live_nodes(profile_path, cfg, use_wifi)`
- このブロックが直接呼ぶ主な関数/メソッド: `Node`, `_drop_keys`, `append`, `bool`, `cfg_path`, `float`, `get`, `get_path`, `get_section`, `int`, `live_forecast_paths`, `str`
- 戻り値の要点: `nodes`
- 上から順の処理:
  1. runtime_cfg に get_section(cfg, 'runtime') の結果を代入する。
  2. logging_cfg に get_section(cfg, 'logging') の結果を代入する。
  3. live_cfg に get_section(cfg, 'live') の結果を代入する。
  4. weather_cfg に get_section(live_cfg, 'weather') の結果を代入する。
  5. autocal_cfg に get_section(live_cfg, 'autocal') の結果を代入する。
  6. command_cfg に get_section(live_cfg, 'command_bridge') の結果を代入する。
  7. distance_cfg に get_section(live_cfg, 'distance') の結果を代入する。
  8. grade_cfg に get_section(live_cfg, 'grade') の結果を代入する。
  9. wind_cfg に get_section(live_cfg, 'wind_model') の結果を代入する。
  10. live_logging_cfg に get_section(live_cfg, 'logging') の結果を代入する。


## launch から起動するノード

- L58: `solar_preflight_node` (package=mpc_solarcar, name=solar_preflight_node)
- L72: `mpc_node` (package=mpc_solarcar, name=mpc_node)
- L102: `dashboard_node` (package=mpc_solarcar, name=dashboard_node)
- L113: `solar_logger_node` (package=mpc_solarcar, name=solar_logger_node)
- L131: `speed_command_bridge_node` (package=mpc_solarcar, name=speed_command_bridge_node)
- L140: `distance_node` (package=mpc_solarcar, name=distance_node)
- L142: `grade_node` (package=mpc_solarcar, name=grade_node)
- L145: `weather_fetch_node` (package=mpc_solarcar, name=weather_fetch_node)
- L168: `solar_autocal_node` (package=mpc_solarcar, name=solar_autocal_node)

## 処理の流れ

1. ソース中の主要関数を通じて処理を進める。
