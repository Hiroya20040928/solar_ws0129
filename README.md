# SolarCar EMS - 究極 3 ファイル完全独立制御システム

本リポジトリは、ソーラーカー最先端最適制御・エネルギーマネジメント・物理モデル同定システムを**最高レベルの極小構成（完全 3 ファイル）**に集約したプログラミングパッケージです。

環境構築・インストールの手順から各プログラムの役割・実行方法まで、すべて本ドキュメントに集約されています。

---

## 🏛️ ディレクトリ構成（完全 3 ファイル ＋ README）

```text
solar_ws0129/
├── 1_fit_vehicle_params.py      # 【プログラム 1】車両物理 (CdA, Crr) ＆ 電池 (OCV, R0) 同定・3,000km Replay検証
├── 2_plan_macro_strategy.py     # 【プログラム 2】3,000 km CEM 大域速度・エネルギー戦略計画 ＆ 気象連動
├── 3_run_live_race_mpc.py       # 【プログラム 3】実車 10s CasADi MPC リアルタイム制御 ＆ UDP 通信
└── README.md                    # システム完全解説・実行ガイド
```

---

## 🔧 1. 環境構築・インストール

外部フレームワーク（ROS 2等）やビルドツールは一切不要です。標準 Python 3 環境に必要なライブラリを直接インストールしてください。

```bash
pip install casadi scipy numpy pandas pyyaml
```

---

## 🚀 2. プログラム実行方法

各プログラムは完全独立型であり、引数なしでそのまま単体実行可能です。

### 【プログラム 1】車両・電池モデル同定 ＆ 適合
走行データから車両空力・転がり抵抗（$C_d A, C_{rr}$）および電池 1-RC 等価回路（$OCV, R_0, R_1, C_1$）を同定し、3,000 km Replay 精度を検証します。
```bash
python 1_fit_vehicle_params.py
```

### 【プログラム 2】3,000 km CEM 大域戦略計画
Open-Meteo API よりコース全域の日射量・風速・風向を自動取得し、全行程 3,000 km の目標速度分布を Cross-Entropy Method (CEM) で最適算出します。
```bash
python 2_plan_macro_strategy.py
```

### 【プログラム 3】実車 10s CasADi MPC リアルタイム制御
車載伴走 UDP 通信（ポート 5005 受信 / 5006 送信）を行い、10秒周期の CasADi 非線形 MPC 最適化ソルバーによりリアルタイムでモータースロットル・回生指令を出力します。
```bash
python 3_run_live_race_mpc.py
```

---

## 📄 ライセンス・著作権
- SolarCar Energy Management Optimization System (BWSC / WSC Release Edition)
