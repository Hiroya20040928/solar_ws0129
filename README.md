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
