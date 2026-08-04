# Solar Live WiFi Manual

## 1. 目的

`live_wifi` モードは、同一 WiFi 上の Raspberry Pi / マイコンから UTF-8 JSON 文字列を UDP で送受信しながら、次を 1 本で回すための本番モードです。

- ソーラーカー状態受信
- 伴走車状態受信
- Open-Meteo 予報自動取得
- 風予報のオンライン補正
- 上位プランナの 1 時間周期更新
- 下位プランナの 1 Hz 速度司令生成
- ソーラーカー側と伴走車側への司令再送
- 1 画面ダッシュボード表示
- ログ保存

起動入口は次です。

```powershell
.\SolarSim.ps1 -Mode live_wifi -Action up
```

停止:

```powershell
.\SolarSim.ps1 -Mode live_wifi -Action stop
```

`rqt_graph` 保存:

```powershell
.\SolarSim.ps1 -Mode live_wifi -Action graph
```

## 2. 構成

```text
Solar car Raspberry Pi ----\
                            > UDP JSON -> telemetry_text_bridge_node -> ROS topics
Chase car Raspberry Pi ----/

Open-Meteo API -> weather_fetch_node -> raw forecast CSV
raw forecast CSV + route + live observation -> wind_correction_node -> corrected forecast CSV
corrected forecast CSV -> mpc_node -> planner commands
planner commands -> telemetry_text_bridge_node -> UDP JSON -> solar / chase
planner topics -> dashboard_node -> http://localhost:8080
planner and telemetry -> logger_node -> outputs/logs/*.csv
```

主 launch:

- [`launch/solar_race_live_wifi.launch.py`](../launch/solar_race_live_wifi.launch.py)

主要ノード:

- `mpc_node`
- `telemetry_text_bridge_node`
- `weather_fetch_node`
- `wind_correction_node`
- `solar_autocal_node`
- `speed_command_bridge_node`
- `dashboard_node`
- `logger_node`
- `distance_node`
- `grade_node`

## 3. 風速予測補正の導入内容

添付資料 `風速予測補正方法.pdf` の考え方は、[`mpc_solarcar/wind_correction_node.py`](../mpc_solarcar/wind_correction_node.py) に次の形で導入しています。

### 3.1 観測値の扱い

- 観測として最優先するのは `headwind_ms`
- `headwind_ms` が無いときは `wind_speed_ms`, `wind_dir_deg`, `course_deg` から進行方向成分へ変換
- `course_deg` も無いときは route waypoint から進行方向を補間

正面風成分は次で計算します。

```text
headwind = wind_speed_ms * cos(wind_from_deg - heading_deg)
```

正なら向かい風、負なら追い風です。

### 3.2 現在時刻での予報補正

現在地・現在時刻に最も近い予報成分 `mu_fcst` と観測 `y_obs` を、予報分散 `sigma_fcst^2` と観測分散 `sigma_obs^2` で融合します。

```text
mu_post = (mu_fcst / sigma_fcst^2 + y_obs / sigma_obs^2)
          / (1 / sigma_fcst^2 + 1 / sigma_obs^2)

sigma_post^2 = 1 / (1 / sigma_fcst^2 + 1 / sigma_obs^2)
```

### 3.3 将来時刻への伝播

現在の補正量 `delta = mu_post - mu_fcst` を、距離減衰付きで将来予報へ伝播します。

```text
w(s) = exp(-ds_km / correlation_distance_km)
mu_corr = mu_fcst_future + w * delta
```

`use_exp_distance_decay: false` のときは、距離ではなく時間減衰へ切り替わります。

### 3.4 不確かさの増加

予報標準偏差は、CSV に既存列が無いとき次で作ります。

```text
sigma_fcst^2(t) = forecast_sigma0_ms^2 + forecast_variance_growth_per_hour * lead_h
```

その上で、現在観測で削れた分だけ近距離で分散を縮め、遠距離では元の予報分布へ戻します。

### 3.5 プランナへ渡す値

`planning_quantile` を使い、MPC に渡す `headwind_ms` を決めます。

- `0.5`: 中央値運用
- `0.84`: 約 `+1 sigma`
- `0.975`: 約 `+2 sigma`

補正済み CSV には次を保存します。

- `headwind_fcst_ms`
- `headwind_corrected_mean_ms`
- `headwind_corrected_std_ms`
- `headwind_corrected_lo95_ms`
- `headwind_corrected_hi95_ms`
- `headwind_plan_ms`
- `headwind_ms`

最終的に `mpc_node` は `headwind_ms` を読みます。

## 4. YAML で触る項目

編集入口:

- [`config/solar/bwsc_2027_demo.yaml`](../config/solar/bwsc_2027_demo.yaml)

### 4.1 必須に近い項目

- `paths.route_waypoints_csv`
- `paths.route_profile_csv`
- `paths.forecast_csv`
- `live.weather.raw_forecast_csv`
- `live.wind_model.corrected_forecast_csv`
- `live.wifi_bridge.bind_host`
- `live.wifi_bridge.bind_port`
- `live.wifi_bridge.solar_remote_host`
- `live.wifi_bridge.solar_remote_port`
- `live.wifi_bridge.chase_remote_host`
- `live.wifi_bridge.chase_remote_port`

### 4.2 風補正パラメータ

| YAML | 意味 |
| --- | --- |
| `live.wind_model.measurement_sigma_ms` | 風観測ノイズ |
| `live.wind_model.correlation_distance_km` | 観測補正がどこまで先に効くか |
| `live.wind_model.fallback_correlation_time_h` | 時間減衰へ切り替えた場合の時定数 |
| `live.wind_model.forecast_sigma0_ms` | 予報の初期標準偏差 |
| `live.wind_model.forecast_variance_growth_per_hour` | 先読み時間で増える分散 |
| `live.wind_model.planning_quantile` | MPC に入れる風の分位点 |
| `live.wind_model.confidence_z` | 表示用 95% 区間係数 |
| `live.wind_model.min_sigma_ms` | 分散の下限 |
| `live.wind_model.preferred_source` | `auto`, `vehicle`, `chase` |
| `live.wind_model.use_exp_distance_decay` | `true` で距離減衰、`false` で時間減衰 |

### 4.3 WiFi ブリッジパラメータ

| YAML | 意味 |
| --- | --- |
| `live.wifi_bridge.enabled` | WiFi ブリッジ全体の有効化 |
| `live.wifi_bridge.enable_inbound` | 受信有効化 |
| `live.wifi_bridge.enable_outbound` | 送信有効化 |
| `live.wifi_bridge.bind_host` | 受信 bind |
| `live.wifi_bridge.bind_port` | 受信 UDP port |
| `live.wifi_bridge.publish_period_sec` | 送信周期 |
| `live.wifi_bridge.send_to_solar` | ソーラーカー向け送信有効化 |
| `live.wifi_bridge.send_to_chase` | 伴走車向け送信有効化 |

### 4.4 実運用安定化のための重要パラメータ

今回の更新で、`live_wifi` は「受信値の整形」「MPC 参照の急変抑制」「最終速度司令の滑らか化」を持つようにしています。まず確認すべき YAML は次です。

| YAML | 役割 |
| --- | --- |
| `mpc.w_dv` | 上位 plan の速度変化そのものを嫌う重み |
| `mpc.w_current` | 電流スパイクを嫌う重み |
| `mpc.w_throttle_rate` | 下位 throttle の変化速度を嫌う重み |
| `mpc.lower_ref_accel_limit_kmhps` | 下位 MPC へ渡す速度参照の立ち上がり上限 |
| `mpc.lower_ref_decel_limit_kmhps` | 下位 MPC へ渡す速度参照の立ち下がり上限 |
| `mpc.lower_ref_deadband_kmh` | 小さな速度揺れを無視する幅 |
| `mpc.speed_meas_timeout_sec` | 速度計測を fresh とみなす時間 |
| `mpc.distance_meas_timeout_sec` | 距離計測を fresh とみなす時間 |
| `mpc.speed_meas_filter_tau_sec` | 速度計測の平滑化時定数 |
| `live.wifi_bridge.speed_filter_tau_sec` | UDP 受信した速度の平滑化時定数 |
| `live.wifi_bridge.distance_max_backtrack_km` | `s_km` の逆戻りをどこまで許すか |
| `live.wifi_bridge.headwind_filter_tau_sec` | 風観測の平滑化時定数 |
| `live.command_bridge.filter_tau_sec` | 車両へ送る最終速度司令の 1 次遅れ |
| `live.command_bridge.accel_limit_kmhps` | 車両へ送る最終速度司令の立ち上がり上限 |
| `live.command_bridge.decel_limit_kmhps` | 車両へ送る最終速度司令の立ち下がり上限 |
| `live.command_bridge.input_timeout_sec` | planner 司令が止まったとき safe speed へ落ちるまでの時間 |
| `live.command_bridge.drive_mode_min_hold_sec` | eco/power 切替の最小保持時間 |

運用判断の目安:

- speed 指令が細かく上下するなら `mpc.w_dv`, `mpc.w_throttle_rate`, `live.command_bridge.filter_tau_sec` を上げる
- 実測速度がガタつくなら `mpc.speed_meas_filter_tau_sec` と `live.wifi_bridge.speed_filter_tau_sec` を上げる
- 立ち上がりが鈍すぎるなら `live.command_bridge.accel_limit_kmhps` を上げる
- 伴走/車両 sender の距離が飛ぶなら `live.wifi_bridge.distance_max_backtrack_km` と sender 側ログを確認する
- drive mode が頻繁に往復するなら `live.command_bridge.drive_mode_min_hold_sec` を伸ばす

## 5. 推奨ネットワーク設定

同一 WiFi に固定 IP を置くことを推奨します。

| 機器 | 推奨 IP | 用途 |
| --- | --- | --- |
| プランナ PC | `192.168.50.10` | 受信サーバ、ダッシュボード |
| ソーラーカー Raspberry Pi | `192.168.50.21` | 車両送信、司令受信 |
| 伴走車 Raspberry Pi | `192.168.50.22` | 伴走車送信、司令受信 |

推奨 port:

| Port | 向き | 用途 |
| --- | --- | --- |
| `52001` | vehicle/chase -> planner | 状態送信 |
| `52002` | planner -> solar | 速度司令受信 |
| `52003` | planner -> chase | 伴走車表示・記録用受信 |

送受信ルール:

- 1 datagram = 1 JSON object
- エンコーディングは `UTF-8`
- 改行は不要
- 周期は `1 Hz` を基本
- 欠損時は値ごとに送らなくてよい
- 単位は `km/h`, `m/s`, `deg`, `km`, `V`, `A`, `degC`

## 6. Planner が受ける JSON 仕様

### 6.1 `vehicle_state`

最小実用セット:

```json
{
  "type": "vehicle_state",
  "ts_unix": 1781700000.0,
  "speed_kmh": 72.4,
  "soc": 0.83,
  "batt_temp_c": 34.1,
  "batt_current_a": 8.6,
  "batt_voltage_v": 97.8,
  "s_km": 412.6,
  "lat": -19.13542,
  "lon": 146.81235,
  "alt_m": 18.4,
  "wind_speed_ms": 6.8,
  "wind_dir_deg": 118.0,
  "course_deg": 176.5
}
```

参照雛形:

- [`templates/network/vehicle_state_example.json`](../templates/network/vehicle_state_example.json)

推奨必須:

- `speed_kmh`
- `soc`
- `batt_temp_c`
- `batt_current_a`
- `batt_voltage_v`
- `lat`
- `lon`
- `course_deg`

強く推奨:

- `s_km`
- `alt_m`

風は次のどちらかで送ります。

1. `headwind_ms` を直接送る
2. `wind_speed_ms`, `wind_dir_deg`, `course_deg` を送る

### 6.2 `chase_state`

```json
{
  "type": "chase_state",
  "ts_unix": 1781700000.0,
  "speed_kmh": 74.0,
  "lat": -19.13580,
  "lon": 146.81210,
  "alt_m": 18.1,
  "wind_speed_ms": 6.5,
  "wind_dir_deg": 121.0,
  "course_deg": 176.0
}
```

参照雛形:

- [`templates/network/chase_state_example.json`](../templates/network/chase_state_example.json)

推奨必須:

- `lat`
- `lon`
- `course_deg`

強く推奨:

- `wind_speed_ms`
- `wind_dir_deg`
- `alt_m`

### 6.3 bundle 形式

1 datagram にまとめたければ、次も受理します。

```json
{
  "type": "bundle",
  "vehicle": { "...": "vehicle_state と同じ" },
  "chase": { "...": "chase_state と同じ" }
}
```

## 7. Planner から送る JSON 仕様

Planner はソーラーカー側と伴走車側へ同じ `planner_command` を送ります。

```json
{
  "type": "planner_command",
  "schema": "solar_v1",
  "ts_unix": 1781700000.0,
  "planner": {
    "speed_cmd_kmh": 71.0,
    "upper_speed_cmd_kmh": 73.5,
    "drive_mode": "eco"
  },
  "summary": {
    "race_progress_pct": 13.6,
    "next_stop_dist_km": 58.2,
    "next_stop_eta_min": 47.0,
    "finish_dist_km": 2622.9,
    "finish_eta_h": 41.5,
    "avg_plan_speed_kmh": 72.1
  },
  "wind": {
    "plan_headwind_ms": 4.8,
    "mean_headwind_ms": 4.2,
    "std_headwind_ms": 1.1,
    "lo95_headwind_ms": 2.0,
    "hi95_headwind_ms": 6.4
  }
}
```

参照雛形:

- [`templates/network/planner_command_example.json`](../templates/network/planner_command_example.json)

マイコン側の最低限の使い方:

- `planner.speed_cmd_kmh`: 実速度司令
- `planner.upper_speed_cmd_kmh`: 上位の参考表示
- `planner.drive_mode`: `eco`, `power`, `stop` などのモード文字列
- `summary.*`: ナビ表示
- `wind.*`: 状況表示と記録

受信 watchdog 推奨:

- 受信が `3.0 s` 途切れたら「通信喪失」表示
- 司令は保持するか、ローカル安全値へ落とす
- 速度司令はローカルで上限 clamp する

## 8. Raspberry Pi 送信側の実装方針

この repo には送信の参考実装を入れています。

- [`scripts/wifi_vehicle_sender_example.py`](../scripts/wifi_vehicle_sender_example.py)
- [`scripts/wifi_chase_sender_example.py`](../scripts/wifi_chase_sender_example.py)
- [`scripts/wifi_planner_receiver_example.py`](../scripts/wifi_planner_receiver_example.py)

動作確認例:

```powershell
python scripts/wifi_vehicle_sender_example.py --host 192.168.50.10 --port 52001
python scripts/wifi_chase_sender_example.py --host 192.168.50.10 --port 52001
python scripts/wifi_planner_receiver_example.py --bind_port 52002
```

Raspberry Pi 本番側では、実センサ値を上の JSON へ埋めて `1 Hz` で送信してください。

### 8.1 自動起動

systemd 雛形:

- [`templates/network/vehicle_sender.service.example`](../templates/network/vehicle_sender.service.example)
- [`templates/network/chase_sender.service.example`](../templates/network/chase_sender.service.example)

## 9. ESP32 / マイコン側の受信仕様

ESP32 側の最小雛形:

- [`templates/network/esp32_planner_receiver_example.ino`](../templates/network/esp32_planner_receiver_example.ino)

マイコン側の固定仕様を次としてください。

- SSID / password はコード内定数ではなく設定領域へ分離
- Planner 受信 port は `52002`
- 受信 JSON は `planner_command`
- `speed_cmd_kmh` を制御ループの目標値へ投入
- `drive_mode` に応じてローカル map を切替
- `ts_unix` と watchdog で古い packet を捨てる
- JSON 不正時は最後の正常 packet を保持

## 10. ダッシュボード

ダッシュボードは、グラフ主体ではなく 1 画面の数値ボックス主体へ変更しています。

主表示:

- 指令速度
- 上位速度
- 実測速度
- SOC
- 電池温度
- パック電圧 / 電流 / 電力
- 太陽電力
- 勾配
- 風の観測 / 予報 / 補正平均 / 標準偏差 / 95% 区間 / 計画値
- 進捗率
- 次 stop
- finish 距離 / ETA
- vehicle / chase GPS
- 予報状態
- 風補正状態
- 通信状態

対象ファイル:

- [`dashboard/index.html`](../dashboard/index.html)
- [`dashboard/app.js`](../dashboard/app.js)
- [`dashboard/style.css`](../dashboard/style.css)

## 11. 起動手順

1. `config/solar/bwsc_2027_demo.yaml` の IP / port / route / weather path を合わせる
2. Raspberry Pi 側の送信プログラムを配置する
3. Planner PC で次を実行する

```powershell
.\SolarSim.ps1 -Mode live_wifi -Action up
```

4. 必要なら graph を保存する

```powershell
.\SolarSim.ps1 -Mode live_wifi -Action graph
```

5. 終了時

```powershell
.\SolarSim.ps1 -Mode live_wifi -Action stop
```

## 12. 確認項目

- ダッシュボードの `network status` が更新される
- `wind model status` に `source=vehicle` または `source=chase` が出る
- `outputs/runtime/live_forecast_raw.csv` が更新される
- `outputs/runtime/live_forecast_corrected.csv` が更新される
- `outputs/logs/solar_live_*.csv` が増える
- `rqt_graph_solar_live_wifi.png` が保存できる

## 13. 関連ファイル

- [`SolarSim.ps1`](../SolarSim.ps1)
- [`scripts/solar_control.sh`](../scripts/solar_control.sh)
- [`launch/solar_race_live_wifi.launch.py`](../launch/solar_race_live_wifi.launch.py)
- [`mpc_solarcar/telemetry_text_bridge_node.py`](../mpc_solarcar/telemetry_text_bridge_node.py)
- [`mpc_solarcar/wind_correction_node.py`](../mpc_solarcar/wind_correction_node.py)
- [`config/solar/bwsc_2027_demo.yaml`](../config/solar/bwsc_2027_demo.yaml)
