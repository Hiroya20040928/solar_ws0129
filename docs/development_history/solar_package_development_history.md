---
title: "MPCEMS YATA 改良・改変の全履歴"
subtitle: "初期試作から車両同定・大会全体MPC・ライブ運用・独立受入まで"
date: "2026-07-18"
lang: ja-JP
---

更新基準日: 2026-07-18  
対象: `solar_ws0129-main` のうち、ソーラーカーEMSを中心とする実質的な改良  
用途: GitHubリリースノート、後任者への引継ぎ、設計変更理由の保存

## 1. この資料の読み方

この資料は、作業中の確認、同じ試験の繰り返し、進捗監視、入力ミスの修正などを省き、パッケージの機能・精度・安全性・使い方を変えた改良だけを時系列で記録したものです。

各段階を次の4点で説明します。

- **以前の問題**: なぜ変更が必要だったか。
- **変更内容**: 何を実装または再設計したか。
- **利用者への効果**: 初めて使う人から見て何が変わったか。
- **残る制限**: 現時点で保証していないこと。

ここでいう「同定」は、実測データに最もよく合う車両パラメータを推定する処理です。「MPC」は、将来の天候・道路・電池状態を予測し、一定時間または距離ごとに計画を解き直す制御です。「CEM」は、多数の候補を試し、良かった候補の分布へ探索範囲を寄せていく最適化です。

## 2. 一文で表す全体の変化

当初のリポジトリは、ソーラーカー用試作MPCとPASSO用機能が混在し、起動入口、時刻、相対パス、YAML反映、実測同定、ライブ通信、長距離シミュレーションが十分に統合されていませんでした。現在は、**実測データ準備 → 車両同定 → 大会環境投入 → 全行程MPCシミュレーション → ライブWiFi運用 → 記録・表示 → 独立検証 → 配布**を同じprofile構造でつなぐROS 2パッケージへ発展しています。

## 3. 変更の時系列

### Phase 0: 初期試作版

**以前の状態**

- ソーラーカーMPCとPASSO燃費支援が同じパッケージに混在していました。
- `mpc_node.py` と `scripts/solar_sim.py` に似た計算が別々にあり、片側だけを修正すると結果がずれる危険がありました。
- launchから渡す相対パスが実行ディレクトリに依存し、データを読めない場合がありました。
- 2025年の絶対時刻スケジュールと、起動時刻を基準にする相対予報が混在していました。
- ROS 2のresource登録や配布ファイルが不足し、`colcon build`後の起動が不安定でした。

**この段階の位置付け**

物理モデルとMPCの骨格はありましたが、「大会で第三者が再現可能に運用する製品」ではなく、研究用コードの集合に近い状態でした。

### Phase 1: ROS 2パッケージとして起動可能に再構成

**変更内容**

- `resource/mpc_solarcar`、`setup.cfg`、`setup.py`の配布定義を整えました。
- パス解決を共通化し、source tree、install tree、WSLのどこから起動してもprofile・map・dataを解決できる構造へ変更しました。
- `solar_state_node.py`を追加し、シミュレーション時に車速、距離、SoC、電圧、電流などの車両状態を自己完結して生成できるようにしました。
- ROSノードが生存している状態でrqt graphを出力する専用処理を追加しました。graph取得専用ノードだけが写る誤った画像を避け、実際のMPC・GPS・logger・dashboardの接続を保存できるようにしました。

**利用者への効果**

ROS 2の内部構造を知らない利用者でも、同じ入口からビルド・起動・停止・状態確認・graph保存を行える土台ができました。

### Phase 2: PowerShell一括入口と3つの主要モード

**変更内容**

- Windows側に`SolarSim.ps1`、WSL/Ubuntu側に`scripts/solar_control.sh`を設けました。
- `sim`、`measure`、`live`を別launchへ分離しました。
- さらに、オフライン大会全体計算を`simulate`、車両同定を`fit`/`identify`、気象取得を`forecast`として同じ入口へ統合しました。
- 全入力をprofile YAMLから参照する構造へ変更し、コード中の大会距離、開始時刻、保存先、車両係数の固定値を削減しました。
- YAML値がノード初期化後に上書きされて効かない問題を修正し、`dt`、horizon、drive mode、SoC上下限などを初期化前に確定するようにしました。
- シミュレーション結果を上書きせず、日時・run名付きの別ディレクトリへ保存し、最新版を指すmanifest JSONから追跡できるようにしました。

**利用者への効果**

利用者は主にprofile YAMLと入力CSVを編集し、PowerShellコマンドを選ぶだけで、実測、同定、事前計算、本番運用を切り替えられます。過去結果も自動的に残ります。

### Phase 3: ライブ運用を自動化

**変更内容**

- `weather_fetch_node.py`を追加し、GNSS位置に応じてOpen-Meteoから予報を定期取得するようにしました。
- `solar_autocal_node.py`を追加し、発電倍率、走行電力倍率、補機電力を範囲制約付きで更新できるようにしました。
- `speed_command_bridge_node.py`を追加し、MPCの速度指令に起動待ち、timeout、加減速率制限、deadband、量子化、上限制限を適用してから車両へ渡すようにしました。
- `distance_node.py`と`grade_node.py`をソーラー運用へ統合し、伴走車GNSS・高度・車速から距離と勾配を更新できるようにしました。
- `solar_preflight_node.py`を追加し、テレメトリ、planner、時刻、予報の鮮度を起動前と走行中に判定するようにしました。
- `solar_logger_node.py`を追加し、車両、伴走車、上位計画、下位指令、天候、校正値、通信状態、安全状態を同じ時系列で保存するようにしました。

**利用者への効果**

大会開始前から起動しておけば、データ取得、再計画、1 Hz速度指令、保存、表示が連続して動く構成になりました。センサが途絶えた場合は古い値を無期限に使わず、安全側へ移行します。

### Phase 4: WiFi文字列通信と風予測補正

**変更内容**

- `telemetry_protocol.py`で、UDP文字列の形式、時刻、送信元、フィールド名、単位を定義しました。
- `telemetry_text_bridge_node.py`で、ソーラーカーと伴走車から届く文字列を検査し、外れ値除去、低域フィルタ、変化率制限を通してROS topicへ変換するようにしました。
- 車速、距離、電池、風、GNSSなどについて、上限、逆行許容量、timeoutを個別設定できるようにしました。
- 車両側・伴走車側・planner側の送受信サンプルを追加し、Raspberry Piやマイコン側の実装見本を用意しました。
- `wind_correction_node.py`を追加し、実測風と予報風の差を距離・時間相関で将来へ伝搬し、補正予報と信頼区間を生成するようにしました。

**利用者への効果**

同一WiFi内のRaspberry Piは、決められた1行文字列をUDPで送るだけでROS 2へ接続できます。ROS 2を車両側へ入れなくても、伴走車PCが全情報を統合できます。

### Phase 5: 一画面dashboardとGrafana

**変更内容**

- 初期dashboardを、数値カード中心の一画面表示へ圧縮しました。
- 車速指令、実車速、SoC、距離、発電、消費、電圧、電流、風、勾配、温度、通信鮮度、安全状態をスクロールなしで確認できる配置へ整理しました。
- `dashboard_node.py`へJSON APIに加えてPrometheus形式の`/metrics`を追加しました。
- `grafana/`へPrometheusとGrafanaのprovisioningを追加し、`SolarSim.ps1 -Action grafana`で同じ画面を再現できるようにしました。

**利用者への効果**

ブラウザを開くだけで運転判断に必要な値を一画面で確認でき、表示設定を各PCで手作業再構築する必要がなくなりました。

### Phase 6: 汎用の実測データ入力・車両同定パイプライン

**変更内容**

- raw CSV雛形とsampleデータを追加し、必要な列、単位、時刻形式、欠損時の扱いを定義しました。
- GPSからroute profileを作る処理、OCV-SoC曲線、Rint温度/SoCマップ、PV/MPPTマップ、駆動/回生マップを作る処理を追加しました。
- `run_identification_pipeline.py`を簡易入口、`run_vehicle_identification.py`をセグメント分割・multi-start・joint refinementを含む本格入口として整備しました。
- 係数だけでなく、mapの形状補正、温度依存、SoC依存、ライン抵抗、分極抵抗・時定数、grade scale、headwind exposureも推定対象へ拡張しました。
- 同定結果から候補profile、map、fit summary、replay CSV、図、TeX/PDFを自動生成し、手作業の転記をなくしました。
- 同定候補は自動で本番profileへ昇格させず、独立validation gateを通った場合だけpromoteできる構造へ変更しました。

**利用者への効果**

別車両でも、決められたCSVへ実測ログを入れて同じコマンドを実行すれば、その車両用のmodel/maps/profile一式を作成できます。どの値が実測、仕様書、理論、推定かも追跡できます。

### Phase 7: 根拠のある物理mapへ再設計

**以前の問題**

初期mapには、製品仕様書や実測値との対応が弱い仮置き形状があり、map全体へ倍率を掛けるだけでは実車再現性を説明できませんでした。

**変更内容**

- モーター/コントローラは回転数、トルク、銅損、鉄損、インバータ損失を基礎にeco/power mapを分離しました。
- 回生は駆動mapの単純コピーをやめ、回生可能電流、低速域、充電効率を別に扱いました。
- 電池はOCV-SoC、Rint温度/SoC、配線抵抗、分極抵抗と時定数をThevenin形で分離しました。
- パネルは面積、基準効率、温度係数、入射日射、panel map、MPPT mapを分離しました。
- 仕様書・試験結果・チーム観測・推定値をevidence bundleに保存し、根拠のない自由度を増やさない方針へ変更しました。

**利用者への効果**

同じRMSEでも「たまたま係数が相殺したモデル」と「部品の物理に沿ったモデル」を区別できます。将来部品を交換した場合も、該当mapだけを差し替えやすくなりました。

### Phase 8: BWSC 2025実ログによる再同定の世代更新

**変更内容**

- `day1`から`day6`の大会ログだけを本戦ログとして扱い、サーキット試走などを分離しました。
- 公式control stop、短いトラブル停車、日跨ぎ、最終事故を別イベントとして扱いました。
- 車重を235 kg、走行中補機を約21 W、夜間補機を0 W、新品電池を3011 Wh、CdAを設計値0.093より悪化した約0.11近傍という物理事前条件で再同定しました。
- 70 km/h巡航で約800 Wというチーム分析を独立のsanity checkとして使いました。
- MLE世代を進める中で、瞬時気象、回生同期、距離窓エネルギー、慣性電力、区間別grade、停止中充電、終端SoCアンカーを順に追加しました。
- 現在のパッケージ世代は`bwsc2025_fitted_mle19_energywindow_inertia`、その内部の最新研究同定runは`mle35_expanded_grade_single_source_ultra_v1`です。番号は「パッケージ世代」と「内部実験run」で役割が異なります。

**現在の研究候補値**

- mass: 235 kg
- CdA: 約0.1112 m2
- Crr: 約0.00626
- driving auxiliary: 約21.02 W
- nominal energy: 3011 Wh
- panel gain: 約0.7127
- conditional clean power RMSE: 約201.34 W
- end-to-end clean power RMSE: 約246.09 W
- battery-conditioned voltage RMSE: 約0.968 V

**残る制限**

70 km/h巡航中央値は実測約800.05 Wに対してモデル約818.05 Wで近い一方、加減速、低速、Day 1/4/6、終端電圧に残差があります。終端SoCの独立根拠は約19.64 percentage pointsの幅を持つため、MLE35は研究候補であり、本番canonical profileへ自動昇格していません。

### Phase 9: 天候データの時刻・地点・独立性を修正

**変更内容**

- 予報CSVの値が「その時刻の瞬時値」か「前1時間平均」かをmetadataで明示しました。
- 走行地点と時刻に対応するOpen-Meteo archiveのGHI/DNI/DHI、気温、風をroute-time gridへ変換しました。
- GHIからパネル面へのPOAへ変換する経路を追加しました。
- 実測PVから逆算したeffective irradianceは同定診断専用とし、将来方策の性能評価には使用禁止としました。
- 通常の日射列へ物理上限を設け、補正前の有効値は別列として保存しました。
- `check_policy_weather_input.py`を追加し、ファイル名だけでなく全行のsource、product role、時刻意味を検査し、PV由来の循環天候をGPU探索・厳密受入へ入れられないようにしました。

**利用者への効果**

「車両の発電実績で補正した晴天」を同じ車両の最適化に再利用して、性能を楽観的に見せる循環評価を防げます。Day 5/6の600から700 W/m2は日平均ではなく瞬時上位値であり、日平均はそれぞれ約433、417 W/m2として区別されます。

### Phase 10: 大会全行程・公式規則をモデルへ統合

**変更内容**

- リタイア地点2831 kmで計算を打ち切る方式をやめ、BWSC 2025の全3026.9 kmを最適化対象にしました。
- 公式programに基づく9か所のcontrol stop、各30分、opening/closing時刻を入力しました。
- Adelaideの最終締切を2025-08-29 17:30 local、すなわち08:00 UTCとして絶対制約にしました。
- 早着時はopeningまで待機、closing後到着またはfinish deadline超過は非可行としました。
- no-trouble実験では公式停車だけを残し、実走行時の故障停車と2831 kmの車体破損を除外しました。
- 停車中・夜間は走行用補機を0 Wとし、朝夕の静止充電とパネル傾斜条件を別に扱いました。

**利用者への効果**

「実ログを再現するシミュレーション」と「故障がなかった場合の反実仮想MPC」を混同せず比較できます。完走判定は距離だけでなく、全control stopと最終締切を含みます。

### Phase 11: 階層MPCと実運用向け平滑化

**変更内容**

- 上位plannerを大会残距離のdistance-domain MPCとして整理し、速度、時間、SoC、電池温度を予測するようにしました。
- 下位plannerを1 Hzで動かし、上位速度参照への追従と指令変化を同時に最小化するようにしました。
- 指令には加減速率、slew、deadband、measurement timeout、low-pass filterを追加しました。
- 上位目的関数を待ち時間、走行時間、終端/日末SoC、速度平滑性、電流二乗、Joule損、空力/機械エネルギー、電力slew、温度、制約barrierへ分解しました。
- `upper_policy.py`を追加し、offline学習済み方策はlive MPCを固定するのではなく、初回のwarm startとして利用するようにしました。以後は最新の計測と予報でreceding-horizon再計画します。

**利用者への効果**

ノイズで速度指令が上下する問題を抑えつつ、予報やSoCが変わった場合は計画を更新できます。認証用の固定方策と本番用の再計画MPCを別profileに分離しました。

### Phase 12: 自己学習とGPU多段方策探索

**変更内容**

- `tune_upper_planner_weights.py`で、人間の速度計画を正解として模倣せず、完走時間、制約、終端エネルギーから目的関数重みをCEMで探索できるようにしました。
- TensorBoardへ世代、候補分布、best score、制約を保存するようにしました。
- `gpu_upper_policy_search.py`で、距離ごとの速度方策をCUDA上で一括評価できるようにしました。
- 全3026.9 kmを、粗探索5 km積分/25 km制御、fine 1 km/5 km、ultra 0.1 km/5 km、さらに2 kmと1 km制御へ段階的に細分化しました。
- 制御変数の次元は123、607、1515、3028へ増えます。物理積分は最終的に約30,269個の100 m遷移を持ちます。
- 4独立seed、8400世代、合計32,993,280候補をSlurm dependency chainで処理し、checkpointとprofile SHAを各段に固定しました。
- 100 m段の過大populationを実測所要時間に基づいて256へ修正し、24時間job limit内で完走可能な構成にしました。

**利用者への効果**

旧4点速度計画では表現できなかった地点別速度差を、道路・天候・control stopに合わせて探索できます。GPU探索はMPCの代替ではなく、live MPCの高品質な初期解を作る役割です。

### Phase 13: 厳密1 Hz受入とmesh convergence

**変更内容**

- GPU surrogateの結果をそのまま採用せず、`solar_sim.py`で固定方策を100 m予測・1 Hz実行として再生する受入段を追加しました。
- 固定方策評価が同じ30,269区間を2回計算していた冗長処理を1回へ削減しました。
- 5 km、2 km、1 km制御方策を別々に最適化し、同じ方策を補間しただけの偽のmesh比較を禁止しました。
- 3格子 x 4 seedを最大12 CPUで並列評価し、各seedの結果を独立保存した後、最速の可行候補だけをmergeするようにしました。
- 時間差、終端SoC差、速度RMS、prediction/execution SoC差に受入閾値を設けました。
- 数値方策合格を`POLICY_ACCEPTANCE_COMPLETE`、車両modelも含む本番昇格を`ACCEPTANCE_COMPLETE`として分離しました。

**利用者への効果**

CUDA上の近似計算が速いだけでは本番採用されません。離散化を細かくしても結果が変わらず、1秒刻みで電圧・電流・SoC・時刻制約を守ることを確認して初めて方策を採用できます。

### Phase 14: 出力CSV・追跡可能性・安全gate

**変更内容**

- summary CSV、detail CSV、upper plan、1 Hz lower command、HTML report、manifest JSONをrunごとに保存するようにしました。
- detail CSVへGHI/DNI/DHI/POA、panel/MPPT効率、PV電力、走行/回生/補機電力、OCV、Rint、電圧、電流、SoC、温度、勾配、風、速度制限、計画/実行速度を追加しました。
- `step_dt`が600秒から端数へ変化する理由を、区間末端、stop境界、日末、control stop境界へ正確に合わせる可変最終stepとして明示しました。
- model validation、weather independence、surrogate feasibility、exact replay、mesh convergenceを別gateにしました。
- profile、map、入力CSV、出力成果物へSHA-256とmanifestを付け、異なる世代を混ぜないようにしました。

**利用者への効果**

結果の数字だけでなく、「どの入力とmodelで、各秒に何W発電し、何W使い、なぜそのSoCになったか」を後から追跡できます。

### Phase 15: 教材・運用資料・配布パッケージ

**変更内容**

- READMEを、入口、各mode、入力、保存先、内部処理、model世代、安全gateまで含む体系へ拡張しました。
- オールインワン解説書、導入運用書、全フローワークブック、MLE手計算ワークブックをTeX/PDFで作成しました。
- 問題編、解答用紙、完全解答を分離し、map補間、車両抵抗、PV、電池IV、上位CEM/L-BFGS-B、下位MPC、UDP、MLE、保存先を手計算できるようにしました。
- PDFは文字重なり、切れ、空白ページ、未解決参照を修正し、主要ページの画像確認用成果物を保存しました。
- `create_solarcar_only_package.py`でPASSO、磁力、build/install/log、旧MLE世代を除いたソーラーカー専用配布物を生成できるようにしました。
- `create_solarcar_blank_package.py`で、同じ機能と資料を保ちながら車両・大会データだけを空にした新車両用templateを生成できるようにしました。

**利用者への効果**

研究者本人以外のチームメンバーが、GitHub ZIPの取得から、Windows/Ubuntu設定、実測、同定、sim、live、マイコン通信、障害復旧まで学べる形になりました。

### Phase 16: 磁気カプラ研究を別系統として高度化

この変更はソーラーカーEMSの本番配布には含めませんが、root repository内の別研究系統として実施されました。

**変更内容**

- 単純磁場表示から、円柱磁石、固定高さ自由配列、有限変位復元力、yaw復元、clearance、package、site spacingを扱う高忠実度モデルへ拡張しました。
- GPU dipole screening、有限モデル再評価、Fourier topology、adaptive random、CEMを段階分離しました。
- 正定値剛性、並進復元、yaw復元、負復元なし、clearance、package、線形性、直交漏れ、条件数、中心釣合いなど16 gateを設けました。
- surrogate合格後に円柱磁石のexact static評価を行い、gate通過候補だけをSTEPへ出力する構成にしました。
- `reevaluate_fourier_gpu_candidates.py`の`inner_support_points_mm`は、exact評価で最小内側支持半径を計算するための正式な設計保存値です。

**分離理由**

磁気カプラは車両EMSのROS runtimeに不要です。root研究repositoryでは保持しますが、solar-only releaseでは削除し、運用者が誤って起動しないようにしています。

## 4. 現在、結局何をしているのか

2026-07-18時点で行っているのは、**MLE35研究候補modelを使った、故障なしBWSC 2025全3026.9 km方策のGPU多段探索**です。

処理順は次のとおりです。

1. 25 kmごと123変数の粗い速度方策を、5 km物理積分で1800世代探索する。
2. 5 kmごと607変数へ増やし、1 km物理積分で200世代改善する。
3. 同じ607変数を100 m物理積分で60世代再調整する。
4. 制御間隔を2 km、次に1 kmへ細かくし、それぞれ20世代調整する。
5. 4つの独立seedが全部終わったら、最良候補を統合する。
6. GPU近似とは別の`solar_sim.py`で、100 m予測と1 Hz実行のfull simulationを行う。
7. 5/2/1 km方策のmesh convergence、公式時刻、電流、電圧、SoCを判定する。
8. 方策gateと車両model gateの両方を通った場合だけlive用profileへ昇格する。

### 2026-07-18 18:52 JSTの状態

- seed 0: coarse、fine、100 m、2 km control、1 km controlを完了。
- seed 1: coarseとfineを完了し、100 m段を実行中。
- seed 2、seed 3: GPU割当待ち。
- campaign finalizer: 4 seed完了待ち。
- exact 1 Hz acceptance: campaign finalizer待ち。
- エラー: なし。GPU使用枠が1枚のため直列進行。

seed 0の暫定値は、1 km control方策で約125.4452時間、終端SoC約10.549%、公式時刻違反0秒です。ただし、これはGPU surrogate値であり、厳密1 Hz合格値ではありません。

## 5. 完了済みと未完了の境界

### 完了済み

- ROS 2のsim、measure、live、live WiFi入口。
- profile YAMLによる入力・出力管理。
- WiFi文字列protocol、filter、timeout、安全指令bridge。
- Open-Meteo取得、風補正、online bounded calibration。
- logger、preflight、one-screen dashboard、Grafana。
- 汎用CSV同定、map生成、候補profile、報告書生成。
- BWSC 2025全3026.9 km、9 control stops、finish deadlineのモデル化。
- MLE35研究候補と独立model gate。
- GPU多段探索、checkpoint、weather gate、exact acceptance pipelineの実装。
- solar-only releaseとblank releaseの生成器。
- README、運用書、ワークブック群。

### 未完了

- 現在の4-seed GPU campaignの全完走。
- その結果に対する100 m/1 Hz厳密full simulation。
- mesh convergence後の最終方策PDF。
- MLE35の本番canonical profileへの昇格。
- 終端SoC証拠幅19.64 pointsを縮める新しい独立実測データの取得。

## 6. 現在の品質をどう解釈するか

現在のplanner探索が長時間かかっている理由は、単に「数千世代だから」だけではありません。1候補の中で、全3026.9 km、日跨ぎ、9停車、天候、map、電池IV、温度を順番に計算するためです。さらに4 seedと複数meshを使い、偶然良かった1回を採用しない設計にしています。

一方、世代数を増やしても実測データの不足は解消しません。plannerの最適化誤差とvehicle modelの同定誤差を分離するため、次の3段階を守ります。

1. GPUで良い方策候補を探す。
2. exact 1 Hz replayで数値方策を検証する。
3. 独立ログでvehicle modelを検証する。

第2段まで通っても第3段が落ちた場合、その方策は研究用であり、本番採用しません。

## 7. GitHubへ掲載するときの短い要約例

> YATAソーラーカーEMSを、試作ROS 2ノード群から、車両同定・大会全体MPC・ライブWiFi運用・記録・Grafana表示・独立検証・配布まで一貫したprofile駆動パッケージへ再構成しました。BWSC 2025の全3026.9 km、公式9 control stops、最終締切、夜間補機0 Wを実装し、実ログと独立気象から物理mapを再同定しました。上位方策は4 seed、8400世代、約3300万候補のmulti-fidelity CUDA探索を行い、100 m予測・1 Hz full replay・mesh convergence・vehicle-model gateを通った結果だけをlive MPCのwarm startへ昇格します。PASSO/磁力/旧成果物を除いたsolar-only releaseと、データ空のbase template、初心者向け運用書・手計算教材も追加しました。

## 8. 重要な成果物

- 主要README: `README.md`
- PowerShell入口: `SolarSim.ps1`
- ROSノード: `mpc_solarcar/`
- simulation launch: `launch/solarcar_sim.launch.py`
- measurement launch: `launch/solar_measurement.launch.py`
- live launch: `launch/solar_race_live.launch.py`
- live WiFi launch: `launch/solar_race_live_wifi.launch.py`
- 本格同定: `scripts/run_vehicle_identification.py`
- full simulation: `scripts/solar_sim.py`
- GPU探索: `scripts/gpu_upper_policy_search.py`
- multi-fidelity投入: `scripts/submit_solar_gpu_multifidelity_campaign.sh`
- exact受入: `scripts/run_solar_gpu_acceptance_pipeline.sbatch`
- Grafana: `grafana/`
- 現行研究package: `project_packages/`下の`bwsc2025_fitted_mle19_energywindow_inertia/`
- 新車両template: `project_packages/bwsc2027_template/`
- 統合資料: `docs/solar_all_in_one_manual/`
- 全フロー手計算教材: `docs/complete_flow_workbook/`
- MLE手計算教材: `docs/mle_hand_calculation_workbook/`
- 同定済み版の配布生成: `scripts/create_solarcar_only_package.py`
- 空版の配布生成: `scripts/create_solarcar_blank_package.py`

## 9. 最後に

最大の改良は、単にMPCの係数を変えたことではありません。入力データの根拠、物理model、最適化、1 Hz実行、独立validation、保存先、資料、配布物を一つの追跡可能な流れへつないだことです。

現在のGPU結果が良好でも、それだけで「YATAが必ず完走する」「連続問題の大域最適解が証明された」「vehicle modelが高精度」とは扱いません。定義した有限候補集合での探索、mesh convergence、exact replay、独立model gateを順に通し、合格範囲を明示して初めて運用へ移します。
