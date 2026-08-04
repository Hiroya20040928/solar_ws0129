# SolarCar MPCEMS - 実車対応 最先端最適制御システム

本リポジトリは、ワールド・ソーラー・チャレンジ (BWSC / WSC) 向け **ソーラーカー最適制御・エネルギーマネジメント・物理モデル同定システム** です。

最小限のファイル構成（主要プログラム 3 本 ＋ データディレクトリ `data/`）で、実車テレメトリ通信、気象連動大域戦略計画、車両・電池物理同定の全機能を保持しています。

---

## 📁 ディレクトリ構成

```text
solar_ws0129/
├── 1_fit_vehicle_params.py      # 【1. 車両同定 & 電池適合】 Scipy/CasADi 物理パラメータMLE同定 & Replay検証
├── 2_plan_macro_strategy.py     # 【2. 3,000 km CEM 大域戦略計画】 CEM 速度最適化 & Open-Meteo 気象自動取得
├── 3_run_live_race_mpc.py       # 【3. 実車 10s CasADi MPC 制御】 リアルタイム MPC & WiFi UDP 通信
├── data/                        # 【入力データ・CSVテンプレート置き場】
│   ├── bwsc2027_route_profile.csv   # レースコース標高・距離・速度制限プロファイル
│   ├── battery_pulse_test.csv       # 電池 1-RC 等価回路同定用パルス放電テストデータ
│   └── telemetry_sample.csv         # 実車テレメトリフォーマットサンプル
└── README.md                    # 本システム取扱説明書・フォーマット仕様書
```

---

## 🔧 1. インストール・動作環境

標準 Python 3 (3.10〜3.13) 環境で動作します。以下のコマンドで必要なライブラリをインストールしてください。

```bash
pip install casadi scipy numpy pandas pyyaml
```

---

## 📊 2. 入力 CSV データ・テンプレートフォーマット仕様

`data/` ディレクトリ内に配置する各 CSV ファイルのフォーマット仕様です。自作のデータを使用する場合は、以下のヘッダー名と単位に従って作成してください。

### ① コース標高・距離プロファイル (`data/bwsc2027_route_profile.csv`)
| 列名 | 単位 | 説明 |
| :--- | :--- | :--- |
| `s_km` | km | スタート地点からの累積距離 |
| `lat` | deg | 緯度 (WGS84) |
| `lon` | deg | 経度 (WGS84) |
| `alt_m` | m | 標高 (DEM 標高データ) |
| `speed_limit_kmh` | km/h | 該当区間の法定・安全最高速度制限 |
| `dem_grade` | rad/m | 勾配 (標高変化率 $\tan\theta$) |

### ② 電池同定パルスデータ (`data/battery_pulse_test.csv`)
| 列名 | 単位 | 説明 |
| :--- | :--- | :--- |
| `time_s` | s | 試験開始からの経過時間 |
| `phase` | - | 試験フェーズ (`pre_rest`, `pulse`, `post_rest`) |
| `current_a` | A | 放電/充電電流（放電: 負値, 充電: 正値） |
| `voltage_v` | V | 電池パック端子電圧 |
| `temp_c` | °C | 電池パック温度 |

### ③ 実車テレメトリデータ (`data/telemetry_sample.csv`)
| 列名 | 単位 | 説明 |
| :--- | :--- | :--- |
| `timestamp` | ISO8601 | 測定日時 |
| `v_kmh` | km/h | 実効車速 |
| `p_solar_w` | W | ソーラー発電電力 |
| `p_batt_w` | W | バッテリー出力電力 |
| `v_batt_v` | V | バッテリーパック電圧 |
| `i_batt_a` | A | バッテリーパック電流 |
| `soc` | 0.0〜1.0 | バッテリー残量 (SoC) |

---

## 🚀 3. プログラム実行手順

### 【1】車両同定 ＆ 電池適合 (`python 1_fit_vehicle_params.py`)
`data/battery_pulse_test.csv` および走行ログから、空力抵抗 ($C_d A$)・転がり抵抗 ($C_{rr}$)・電池 1-RC パラメータ ($OCV, R_0, R_1, C_1$) を最尤推定同定し、3,000 km Replay 検証を実行します。
```bash
python 1_fit_vehicle_params.py
```

### 【2】3,000 km CEM 大域戦略計画 (`python 2_plan_macro_strategy.py`)
`data/bwsc2027_route_profile.csv` に沿って Open-Meteo API から全行程の気象（日射量・風速）を自動取得し、3,000 km の目標速度分布プロファイルを出力します。
```bash
python 2_plan_macro_strategy.py
```

### 【3】実車 10s CasADi MPC リアルタイム制御 (`python 3_run_live_race_mpc.py`)
UDP ポート 5005 でテレメトリを受信し、10秒周期の CasADi 非線形 MPC によりスロットル・回生指令を計算して UDP ポート 5006 から車載マイコンへ送信します。
```bash
python 3_run_live_race_mpc.py
```

---

## ⚙️ 4. 自動生成される出力ファイル
- `macro_strategy_plan.csv`: 3,000 km 区間別目標速度計画
- `telemetry_live.csv`: 実車リアルタイム制御ログ
- `fitted_vehicle_profile.yaml`: 同定済み車両・電池パラメータ

---
- SolarCar Energy Management System Edition

---

## 📋 5. 全入力テンプレート一覧 (`data/templates/`)

本システムにインポート・読み込み可能な**すべてのデータ形式（計32種類）の完全なテンプレート**が `data/templates/` 内に備わっています。

### 📊 ① コース・走行・試験データ CSV
- `data/templates/route_profile_template.csv`: 3,000 km レースコース標高・距離・速度制限
- `data/templates/battery_pulse_template.csv`: 電池 1-RC パルス放電試験データ
- `data/templates/battery_rest_template.csv`: 電池 OCV 緩和試験データ
- `data/templates/drive_timeseries_template.csv`: 走行データ時系列 (電力・車速・電圧・電流・SoC)
- `data/templates/speed_profile_template.csv`: 目標速度プロファイル
- `data/templates/observed_replay_log_template.csv`: 3,000 km Replay 検証用実測ログ

### ⚡ ② 車両・電池・モータ・太陽電池マップ CSV
- `data/templates/ocv_soc_curve_template.csv`: OCV-SoC 曲線マップ ($V_{oc}(SoC)$)
- `data/templates/rint_map_template.csv`: 内部抵抗 $R_0(SoC, T)$ マップ
- `data/templates/r1_map_template.csv`: 偏極抵抗 $R_1(SoC, T)$ マップ
- `data/templates/tau_map_template.csv`: 偏極時定数 $\tau(SoC, T)$ マップ
- `data/templates/panel_eff_map_template.csv`: 太陽電池パネル効率マップ $\eta_{panel}(T, G)$
- `data/templates/mppt_eff_map_template.csv`: MPPT 変換効率マップ $\eta_{mppt}(P_{in})$
- `data/templates/drive_eff_map_template.csv`: 駆動インバータ・モータ効率マップ $\eta_{drive}(v, \tau)$
- `data/templates/regen_eff_map_template.csv`: 回生ブレーキ変換効率マップ $\eta_{regen}(v, \tau)$
- `data/templates/motor_tau_limit_template.csv`: モータトルク上下限値マップ $\tau_{max}(v)$
- `data/templates/aux_load_profile_template.csv`: 補機消費電力プロファイル $P_{aux}(t)$
- `data/templates/panel_sweep_template.csv`: 太陽電池アレイ方角・傾斜角感度テスト
- `data/templates/source_map_catalog_template.csv`: マップソースカタログデータ
- `data/templates/bom_hourly_solar_route_template.csv`: 気象局 (BOM) 1時間毎気象データ

### ⚙️ ③ 設定・アノテーション YAML
- `data/templates/solar_params_template.yaml`: 太陽電池パラメータ仕様
- `data/templates/battery_thermal_template.yaml`: 電池熱モデルパラメータ仕様
- `data/templates/identification_manifest_template.yaml`: 同定実験マニフェスト
- `data/templates/counterfactual_no_trouble_template.yaml`: 反実仮想トラブルフリー設定
- `data/templates/grounded_map_sources_template.yaml`: 地形・気象ソース設定
- `data/templates/actual_event_annotations_template.yaml`: 実車イベント（コントロールストップ等）注釈
- `data/templates/drive_schedule_template.yaml`: レース走行スケジュール設定

### 📡 ④ ネットワーク・マイコン（ESP32 / systemd）テンプレート
- `data/templates/network/planner_command_example.json`: 制御指令 JSON フォーマット
- `data/templates/network/vehicle_state_example.json`: 車両状態 JSON フォーマット
- `data/templates/network/chase_state_example.json`: 伴走車気象 JSON フォーマット
- `data/templates/network/esp32_planner_receiver_example.ino`: ESP32 マイコン用 UDP 受信 C++ コード
- `data/templates/network/vehicle_sender.service.example`: Linux systemd 自動起動サービス
- `data/templates/network/chase_sender.service.example`: 伴走車用 systemd 自動起動サービス


---

## 🏆 5. BWSC 2025 出走直前さながら 運用シミュレーションデモ（実行手順）

本番（BWSC 2027）前に、実際の BWSC 2025 実測データを用いた「出走直前〜レース本番」の一連の運用シナリオシミュレーションを以下の 3 ステップで実行可能です。

### 📌 ステップ 1: 車両・電池パラメータの適合 (`1_fit_vehicle_params.py`)
実測電池パルスデータ (`data/battery_pulse_test.csv`) から車両空力・抵抗および 1-RC 電池パラメータを適合します。
```bash
python 1_fit_vehicle_params.py
```

### 📌 ステップ 2: 出走数時間前 3,000 km 事前大域戦略計画 (`2_plan_macro_strategy.py`)
実測 BWSC 2025 レースコースマップ (`data/bwsc2025_route_profile.csv`) と Open-Meteo 気象 API を連動させ、ダーウィンスタートライン待機中に 3,000 km 全行程の事前面全計画 CSV (`data/macro_strategy_plan.csv`) を出力します。
```bash
python 2_plan_macro_strategy.py
```

### 📌 ステップ 3: 出走本番 逐次 MPC リアルタイム制御 ＆ 残り 3,000 km 計画逐次更新 (`3_run_live_race_mpc.py --sim`)
スタートラインからの出走を模擬実行し、10秒周期の MPC ステップごとに走行状態を更新しながら、**以降 3,000 km の残存速度・エネルギー計画 (`data/live_remaining_horizon_plan.csv`) およびテレメトリログ (`data/telemetry_live.csv`) を逐次リアルタイム更新出力**します。
```bash
python 3_run_live_race_mpc.py --sim
```
