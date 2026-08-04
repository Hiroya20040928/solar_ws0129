# Solar Workflow Manual

## 1. 目的

この workspace は、**PASSO 系を使わず**、BWSC 系ソーラーカー運用だけに集中できるように次の 3 モードへ整理しています。

1. `大会全体シミュレーション`
2. `本番ライブ運用`
3. `CSV ベース同定`

通常の入口は次の 2 つです。

- 実行入口: `.\SolarSim.ps1`
- 設定入口: [`config/solar/bwsc_2027_demo.yaml`](../config/solar/bwsc_2027_demo.yaml)

この profile を変えるだけで、気象入力、地図入力、同定入力、実車運用の各モードを切り替えられます。  
launch 側の主要パラメータは profile YAML から変更可能です。

## 2. 現在の構成でできること

- `forecast` で天候 API から予報 CSV を生成
- `simulate` で大会全体の上位プラン CSV を生成
- `measure up` で実測ログ取得
- `identify` で CSV 群から route / OCV / Rint / PV / 車両パラメータを再構築
- `live up` で実車トピック受信、予報更新、自動校正、上位再計画、下位速度指令、車両側速度司令再配信、統合ダッシュボード表示
- `live_wifi up` で WiFi/UDP 文字列受信送信付きの本番ライブ運用
- `graph` で `rqt_graph` を PNG / SVG / DOT 保存

## 3. 重要な前提

この repo の既定値は BWSC 向けに寄せてありますが、次のものは**必ず実測・公式値へ置換**してください。

- `data/route/*sample.csv`
- `data/weather/bwsc_forecast_sample_10min.csv`
- `data/race/bwsc_control_stops_sample.yaml`
- `maps/*.csv` の効率・内部抵抗マップ
- `config/solar/bwsc_2027_demo.yaml` の `model.*`

特に control stop と route sample は、最終的には大会年の official route note / measured route に置き換える前提です。

## 4. ディレクトリ

```text
config/solar/
  bwsc_2027_demo.yaml            # 触る入口

data/route/
  bwsc_route_waypoints_sample.csv
  bwsc_route_profile_sample.csv
  bwsc_speed_profile_sample.csv

data/weather/
  bwsc_forecast_sample_10min.csv

data/race/
  bwsc_drive_schedule_2027.yaml
  bwsc_control_stops_sample.yaml

data/identification/raw/
  drive_timeseries.csv
  battery_rest.csv
  battery_pulse.csv
  panel_sweep.csv
  gps_track.csv

templates/identification/
  *_template.csv                 # 生データ記入用の雛形

maps/
  drive_eff_map.csv
  regen_eff_map.csv
  Rint_T_by_soc.csv
  panel_eff_map.csv
  mppt_eff_map.csv

launch/
  solarcar_sim.launch.py
  solar_measurement.launch.py
  solar_race_live.launch.py
  solar_race_live_wifi.launch.py

scripts/
  solar_sim.py
  fetch_weather_forecast.py
  run_identification_pipeline.py
  build_route_profile_from_gps.py
  build_ocv_curve.py
  build_rint_map_from_timeseries.py
  build_pv_maps_from_csv.py
  fit_vehicle_params.py

outputs/
  prerace/
  logs/
  identification/
```

## 5. PowerShell コマンド一覧

### 5.1 もっともよく使うもの

```powershell
.\SolarSim.ps1 -Action simulate
.\SolarSim.ps1 -Action forecast
.\SolarSim.ps1 -Action identify
.\SolarSim.ps1 -Mode measure -Action up
.\SolarSim.ps1 -Mode live -Action up
.\SolarSim.ps1 -Mode live_wifi -Action up
.\SolarSim.ps1 -Mode sim -Action up
.\SolarSim.ps1 -Mode live -Action graph
.\SolarSim.ps1 -Mode live -Action stop
```

### 5.2 Action の意味

| Action | 用途 | 主な出力 |
| --- | --- | --- |
| `build` | ROS パッケージ再ビルド | `install/`, `build/`, `log/` |
| `simulate` | 大会全体シミュレーション | `outputs/prerace/*.csv`, `*_report.html`, `*_summary.json`, `*_resolved.yaml` |
| `forecast` | 天候 API 取得 | `paths.forecast_csv` |
| `identify` | 同定パイプライン実行 | `outputs/identification/*` |
| `up` | build + stop + start | ダッシュボード + ROS ノード群 |
| `start` | 起動のみ | 同上 |
| `stop` | 停止 | 同上停止 |
| `status` | 起動状態確認 | 端末表示 |
| `graph` | `rqt_graph` 保存 | `rqt_graph_solar_<mode>.*` |
| `log` | 実行ログ表示 | `.run/solar_<mode>.log` |

### 5.3 Mode の意味

| Mode | launch | 用途 |
| --- | --- | --- |
| `sim` | `solarcar_sim.launch.py` | 画面付きシミュレーション確認 |
| `measure` | `solar_measurement.launch.py` | 実測ログ・地図取得 |
| `live` | `solar_race_live.launch.py` | 本番自動運用 |
| `live_wifi` | `solar_race_live_wifi.launch.py` | WiFi/UDP 文字列連携付き本番自動運用 |

## 6. Mode 1: 大会全体シミュレーション

### 6.1 目的

- ルート、予報、停止点、速度上限、車両パラメータを変えながら大会全体の速度計画を見る
- 上位プランナの CSV を大会全区間について出力する

### 6.2 実行コマンド

```powershell
.\SolarSim.ps1 -Action simulate
```

必要に応じて profile を差し替えます。

```powershell
.\SolarSim.ps1 -Profile config/solar/bwsc_2027_demo.yaml -Action simulate
```

`simulate` 実行後は、既定で `outputs/prerace/<prefix>_report.html` が生成され、`PowerShell` 実行時は自動で開きます。

### 6.2.1 すぐ比較したいときの上書き例

`solar_sim.py` には `section.key=value` 形式の上書きがあります。profile 本体を書き換えず、その場限りの比較ができます。

```powershell
wsl -d Ubuntu-22.04 bash -lc "cd '/mnt/c/Users/user/OneDrive - 和歌山大学/ソーラー/エネマネ/solar_ws0129-main' && source /opt/ros/humble/setup.bash && source install/setup.bash && python3 scripts/solar_sim.py --profile_yaml config/solar/bwsc_2027_demo.yaml --override simulation.output_prefix=bwsc_try_fast --override mpc.race_km=50 --override model.CdA=0.10"
```

### 6.3 主な入力

`paths.route_waypoints_csv`
: `dist_km, lat, lon` が必須です。`alt_m` があると実測系に流用しやすくなります。

`paths.route_profile_csv`
: `dist_km, slope_pct` を推奨します。`headwind_ms` があればそのまま使います。

`paths.speed_profile_csv`
: `dist_km, v_max_kmh`。区間制限速度を入れます。

`paths.forecast_csv`
: `time, GHI, Tamb_C, Tcell_C` を推奨します。`headwind_ms, wind_dir_deg` があれば保持されます。

`paths.stop_yaml`
: `stops[].s_km` と `stops[].dwell_s` を入れます。

`paths.drive_schedule_yaml`
: 日毎の走行可能時間帯を入れます。

### 6.4 主な出力

`outputs/prerace/<prefix>.csv`
: 時系列の代表結果。

`outputs/prerace/<prefix>_detail.csv`
: バッテリ、太陽電力、損失などの詳細。

`outputs/prerace/<prefix>_upper_plan.csv`
: 上位プランナの距離・速度・ SOC 計画。

`outputs/prerace/<prefix>_report.html`
: 主要結果をブラウザで即確認するためのレポート。

`outputs/prerace/<prefix>_summary.json`
: 完走可否、最小 SoC、平均速度などの要約。

`outputs/prerace/<prefix>_resolved.yaml`
: その run で実際に使った設定の確定版。

既定では `simulation.auto_version_outputs: true` なので、profile を保存して値が変わると、出力名に `保存時刻_内容ハッシュ` が付き、既存結果を上書きしません。直近実行の場所は `outputs/prerace/latest_simulation_run.json` でも追えます。

### 6.5 最小限で触るべきパラメータ

通常は次だけで十分です。

- `paths.route_waypoints_csv`
- `paths.route_profile_csv`
- `paths.speed_profile_csv`
- `paths.forecast_csv`
- `paths.stop_yaml`
- `simulation.start_utc`
- `simulation.soc0`
- `simulation.Tb0`
- `model.CdA`
- `model.Crr`
- `model.P_aux`
- `model.pv_area`
- `model.E_nom_Wh`
- `mpc.race_km`

`mpc` の重みをむやみに増やすより、まずは入力 CSV と `model.*` を実測値へ寄せてください。

## 7. Mode 2: 本番ライブ運用

### 7.1 目的

ライブ運用モードでは次を自動化します。

- 実車トピック受信
- 後方伴走車 GNSS 受信
- 予報 API 自動取得
- 走行中ログ保存
- 太陽入力量と駆動消費の自動校正
- 上位プランナの 1 時間毎再計画
- 下位プランナの 1 Hz 速度司令生成
- 車両側コマンドトピックへの再配信
- 伴走車側ダッシュボード表示

### 7.2 実行コマンド

```powershell
.\SolarSim.ps1 -Mode live -Action up
```

WiFi/UDP 文字列連携を含む本番モード:

```powershell
.\SolarSim.ps1 -Mode live_wifi -Action up
```

停止:

```powershell
.\SolarSim.ps1 -Mode live -Action stop
```

`rqt_graph` だけ更新したいとき:

```powershell
.\SolarSim.ps1 -Mode live -Action graph
```

### 7.3 ライブモードで起動する主ノード

- `mpc_node`
- `dashboard_node`
- `logger_node`
- `weather_fetch_node`
- `solar_autocal_node`
- `speed_command_bridge_node`
- `distance_node`
- `grade_node`

`live_wifi` ではさらに次が加わります。

- `telemetry_text_bridge_node`
- `wind_correction_node`

### 7.4 実車側から欲しいトピック

最低限:

- `/vehicle/speed_kmh`
- `/vehicle/batt_soc`
- `/vehicle/batt_temp_c`
- `/vehicle/batt_current_a`
- `/vehicle/batt_voltage_v`

あるとよい:

- `/vehicle/s_km`
- `/vehicle/gps`
- `/vehicle/altitude_m`
- `/chase/gps`

`/vehicle/s_km` が無い場合は `distance_node` が速度から積分します。  
`/vehicle/gps` と `/vehicle/altitude_m` があれば `grade_node` が勾配を推定します。

### 7.5 ライブモードの主要出力

- `/planner/speed_cmd`
- `/planner/drive_mode`
- `/vehicle/speed_cmd_kmh`
- `/vehicle/drive_mode_cmd`
- `/planner/calibration`
- `/planner/calibration_state`
- `/planner/summary`
- `/system/forecast_status`
- `/system/calibration_status`
- `/system/command_status`

### 7.6 ダッシュボード

ダッシュボードは**デスクトップでは 1 画面に収める**前提で CSS を詰めています。表示内容は次です。

- 現在速度、 SOC、温度、距離
- 上位プラン / 進捗率 / 次 stop / ゴール残距離 / ETA
- 予報取得状態
- 自動校正状態
- 速度司令ブリッジ状態
- 車両 GPS / 伴走車 GPS
- 予測太陽電力、パック電力、風、勾配

### 7.7 ライブ用 profile の触りどころ

`live.weather.*`
: API 取得周期、気象ステップ、fallback 座標。

`live.autocal.*`
: 自動校正の閾値と gain 上下限。

`live.command_bridge.*`
: 実車側への出力トピック、 UDP 出力先。

`live.distance.*`
: 擬似オドメトリ積分設定。

`live.grade.*`
: 勾配推定の平滑と最小移動量。

`mpc.upper_replan_sec`
: 上位プランナ再計画周期。既定は `3600.0` 秒です。

`mpc.lower_rate_hz`
: 下位速度司令生成周期。既定は `1.0` Hz です。

WiFi/UDP 文字列運用の詳細は [`docs/solar_live_wifi_manual.md`](./solar_live_wifi_manual.md) と `docs/solar_live_wifi_manual.pdf` を参照してください。

## 8. Mode 3: CSV ベース同定

### 8.1 目的

大量の実走時系列 CSV から、シミュレーションと本番に使う map / model を再構築します。

### 8.2 実行コマンド

```powershell
.\SolarSim.ps1 -Action identify
```

入力雛形は `templates/identification/` に置いてあります。  
作業用の初期配置例は `data/identification/raw/` です。

### 8.3 必須ではないが推奨する入力群

#### `drive_timeseries.csv`

最低限ほしい列:

- `time`
- `speed_kmh`
- `batt_voltage_v`
- `batt_current_a`
- `slope_pct`
- `G_poa`

推奨追加列:

- `soc`
- `batt_temp_c`
- `wind_ms`
- `headwind_ms`
- `alt_m`

用途:

- `fit_vehicle_params.py`
- 消費モデル、 `CdA`, `Crr`, `P_aux` の再同定

#### `battery_rest.csv`

列:

- `soc`
- `temperature_c`
- `voltage_v`
- `rest_time_s`

用途:

- `build_ocv_curve.py`
- OCV-SOC カーブ生成

#### `battery_pulse.csv`

列:

- `soc`
- `temperature_c`
- `current_a`
- `voltage_v`

用途:

- `build_rint_map_from_timeseries.py`
- 内部抵抗 map 生成

#### `panel_sweep.csv`

列:

- `irradiance_w_m2`
- `cell_temp_c`
- `panel_power_w`
- `panel_area_m2`
- `mppt_power_w`

用途:

- `build_pv_maps_from_csv.py`
- `panel_eff_map`, `mppt_eff_map` 生成

#### `gps_track.csv`

列:

- `lat`
- `lon`
- `alt_m`

用途:

- `build_route_profile_from_gps.py`
- route waypoint / profile 生成

### 8.4 主な出力

`outputs/identification/route_waypoints_identified.csv`
: route waypoint 再生成結果。

`outputs/identification/route_profile_identified.csv`
: route profile 再生成結果。

`outputs/identification/ocv_soc_curve_identified.csv`
: OCV カーブ。

`outputs/identification/Rint_T_by_soc_identified.csv`
: Rint map。

`outputs/identification/panel_eff_map_identified.csv`
: panel 効率 map。

`outputs/identification/mppt_eff_map_identified.csv`
: MPPT 効率 map。

`outputs/identification/vehicle_model_fit.yaml`
: 車両パラメータ推定結果。

## 9. YAML の見方

`config/solar/bwsc_2027_demo.yaml` は次の 8 ブロックに絞っています。

- `paths`
- `runtime`
- `logging`
- `simulation`
- `measurement`
- `identification`
- `live`
- `model`
- `mpc`

### 9.1 ふだん触るのはここだけ

`paths.*`
: 入力 CSV / YAML / maps の差し替え。

`simulation.*`
: 事前シミュレーションの開始条件。

`measurement.distance.*`, `measurement.grade.*`
: 実測補助設定。

`live.weather.*`, `live.autocal.*`, `live.command_bridge.*`
: 本番自動化設定。

`model.*`
: 車両そのものの実測値。

`mpc.*`
: 計画周期、速度制御周期、 SOC 制約。

### 9.2 不確かさを増やさないための運用指針

- まず `paths.*` と `model.*` を実測へ寄せる
- 次に `mpc.race_km`, `mpc.upper_replan_sec`, `mpc.lower_rate_hz` を調整する
- 重み係数は最後に触る
- 測れていない値を増やすより、 map / route / weather の品質を上げる

## 10. 推奨運用手順

### 10.1 大会前

1. `templates/identification/` を使って実測 CSV を整理する
2. `.\SolarSim.ps1 -Action identify`
3. `outputs/identification/*` を `maps/` と `data/route/` に反映する
4. `.\SolarSim.ps1 -Action forecast`
5. `.\SolarSim.ps1 -Action simulate`
6. `outputs/prerace/*_upper_plan.csv` を確認する

### 10.2 計測日

1. `.\SolarSim.ps1 -Mode measure -Action up`
2. 実車と伴走車からトピック受信
3. `outputs/logs/solar_measurement_*.csv` を保存
4. 必要なら再度 `identify`

### 10.3 本番日

1. `.\SolarSim.ps1 -Action forecast`
2. `.\SolarSim.ps1 -Mode live -Action up`
3. WiFi 文字列運用時は `.\SolarSim.ps1 -Mode live_wifi -Action up`
4. ダッシュボード、 `rqt_graph`, `outputs/logs/solar_live_*.csv` を監視
5. 大会終了後に `outputs/logs/` を同定入力へ戻す

## 11. 生成される graph

`graph` 実行時には次が保存されます。

- `rqt_graph_solar_sim.png`
- `rqt_graph_solar_measure.png`
- `rqt_graph_solar_live.png`
- 同名の `.svg`, `.dot`

## 12. PDF 化

この md と同内容の TeX 版を `docs/solar_workflow.tex` に用意しています。  
Windows からの PDF 生成例:

```powershell
xelatex -interaction=nonstopmode -output-directory=docs docs/solar_workflow.tex
xelatex -interaction=nonstopmode -output-directory=docs docs/solar_workflow.tex
```

出力:

- `docs/solar_workflow.pdf`

## 13. 外部資料

既定値整理の際に参照した主な外部資料:

- 2027 BWSC Regulations v1.0
- BWSC route map
- 2025 BWSC route notes
- 2025 BWSC official program
- Online energy management for solar race cars
- WUR 2024 solar strategy model paper

大会固有値は、必ず最新版の公式資料で再確認してください。
