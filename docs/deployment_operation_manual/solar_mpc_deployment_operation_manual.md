---
title: ソーラーカーMPC-EMS 完全導入・運用手順書
subtitle: Windows 11 / WSL2 / Ubuntu 22.04 / ROS 2 Humble
date: 2026-07-16
lang: ja-JP
papersize: a4
geometry: margin=18mm
CJKmonofont: Yu Gothic
---

本書は、GitHubから初めてZIPを取得する時点から、車両同定、天候取得、
大会全体シミュレーション、実測、live WiFi、結果保存、障害復旧までを、
初見のチーム員だけで再現するための手順書である。

## 対象、配布物、安全境界

動作保証対象は Ubuntu 22.04 + ROS 2 Humble である。Windows 11ではWSL2上の
Ubuntu 22.04を使う。Native Windows ROS、Ubuntu 24.04/Jazzyは、このreleaseの
検証対象ではない。

配布物は次の二つである。

- `MPCEMS_YATA_2027`: YATAの同定例、採用map、報告書を含む全機能版。
- `MPCEMS_base`: 同じ実行機能を持つが、車両・大会データが空の雛形版。

本システムが送るものは速度**助言値**であり、直接のトルク指令ではない。
運転者、車両側速度上限、電装保護、非常停止が常に優先する。未同定の空packageを
live送信へ使ってはならない。

公式参照先は [WSL導入](https://learn.microsoft.com/windows/wsl/install)、
[ROS 2 Humble Ubuntu導入](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debians.html)、
[GitHub ZIP取得](https://docs.github.com/repositories/working-with-files/using-files/downloading-source-code-archives)
である。

## Windows 11への初回導入

### ZIP取得

GitHubの **Code > Download ZIP** を選び、`C:\solar\MPCEMS_YATA_2027` のような
短いローカルパスへ展開する。OneDrive上でも動くが、大量のCSV、build、PDF生成では
同期負荷が増えるため、運用PCでは短いローカルパスを推奨する。

### WSL2導入

管理者PowerShellで一度だけ実行する。

```powershell
wsl --install -d Ubuntu-22.04
```

再起動を要求されたら再起動し、Ubuntuを一度起動してLinuxユーザーを作る。
展開先で通常のPowerShellを開き、次を実行する。

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\Install-SolarSim.ps1
.\SolarSim.ps1 -Action audit
```

`Install-SolarSim.ps1` はWindowsのパスをWSLパスへ変換し、Ubuntu側の
`scripts/bootstrap_ubuntu_humble.sh`へ渡す。途中でsudo passwordを求められる。

### 導入成功判定

次がすべて成功しなければ先へ進まない。

```powershell
wsl -d Ubuntu-22.04 bash -lc "source /opt/ros/humble/setup.bash; ros2 --help >/dev/null"
.\SolarSim.ps1 -Action build
.\SolarSim.ps1 -Action audit
```

`build`が`install/setup.bash`を作り、`audit`がinventory、静的監査、pytestを通す。
失敗時は最後の80行を保存し、依存を無視して起動しない。

## Ubuntu 22.04への初回導入

ZIPを展開するかcloneし、repository rootで次を実行する。

```bash
cd ~/solar/MPCEMS_YATA_2027
bash scripts/bootstrap_ubuntu_humble.sh
bash scripts/solar_control.sh audit sim config/solar/bwsc_2027_demo.yaml
```

bootstrapはROS公式repository、Humble Desktop、科学計算Python、Graphviz、
rqt-graph、chronyを導入し、rosdep、colcon build、pytestまで行う。CasADiだけは
Jammyのrosdep key差を避けてpip user領域へ入れる。再実行しても既存ROS設定を壊さない。

通常のshellから直接ROS commandを使う場合は、そのterminalごとに次を読む。

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
```

## package構造と一つの正本

全actionは一つの`profile.yaml`を受け取る。相対pathはprofileの所在directoryを
基準に解決され、実行時には解決済みprofileが結果と一緒に保存される。

| profile block | 内容 |
|---|---|
| `paths` | route、weather、schedule、全採用map |
| `runtime` | timezone、dashboard host/port |
| `logging` | live/measurement保存先とrate |
| `simulation` | 開始UTC、初期状態、version出力先 |
| `measurement` | distance/grade実測条件 |
| `identification` | raw/evidence/fit出力先 |
| `live` | weather API、autocal、command/WiFi bridge |
| `model` | 質量、CdA、Crr、補機、電池、電流・温度上限 |
| `mpc` | 上位/下位horizon、終端帯、目的関数、solver |

主要sourceの責務は次の通りである。

| source | 責務 |
|---|---|
| `model.py` | 力、効率map、PV、pack、IV、SoC、熱状態 |
| `upper_cost.py` / `upper_solver.py` | 上位目的・制約とglobal/local探索 |
| `mpc_node.py` | remaining-course上位MPCと1 Hz下位MPC |
| `solar_sim.py` | offline全コース最適化、replay、全CSV/manifest |
| `telemetry_text_bridge_node.py` | UDP解釈、時刻gate、filter、ROS topic化 |
| `speed_command_bridge_node.py` | timeout、平滑化、変化率、量子化、安全送信 |
| `solar_logger_node.py` | 同期済みlive/measurement CSV |
| `dashboard_node.py` | 一画面dashboardとAPI |

生成済み結果を上書き編集しない。profileを説明的な別名で保存し、
`latest_simulation_run.json`と解決済みprofileで結果を特定する。

## 全actionと4 mode

Windows形式は次である。

```powershell
.\SolarSim.ps1 -Action <action> -Mode <mode> -Profile <profile.yaml>
```

Ubuntu形式は次である。

```bash
bash scripts/solar_control.sh <action> <mode> <profile.yaml>
```

actionは`up/build/start/stop/restart/status/graph/simulate/forecast/identify/fit/
learn/audit/package/blank/log`、modeは`sim/measure/live/live_wifi`である。

| mode | launch | 実際に起動する機能 |
|---|---|---|
| `sim` | `solarcar_sim.launch.py` | GPS模擬、状態伝播、階層MPC、dashboard |
| `measure` | `solar_measurement.launch.py` | preflight、distance、grade、logger、dashboard |
| `live` | `solar_race_live.launch.py` | weather、autocal、MPC、安全command、logger |
| `live_wifi` | `solar_race_live_wifi.launch.py` | live全部、UDP telemetry、風補正 |

`up`はbuild、古い同package node停止、選択launch起動を順に行う。PowerShell入口は
dashboard応答を待ち、実nodeが生きている間にrqt graphを採取する。

```powershell
.\SolarSim.ps1 -Mode live_wifi -Action status
.\SolarSim.ps1 -Mode live_wifi -Action log
.\SolarSim.ps1 -Mode live_wifi -Action graph
.\SolarSim.ps1 -Mode live_wifi -Action stop
```

停止中にgraph exporterだけが表示されるのは正常である。必ず`up`後に`graph`を取る。

## 空packageから車両モデルを完成させる

### 入れる根拠資料

`project_packages/<vehicle>/data/identification/evidence`へ、motor/controllerの
公式試験、eco/power/regen効率、panel/MPPT仕様、cell放電・OCV曲線、
Rint対SoC/温度、補機実測、車体諸元を置く。根拠のない滑らかなmapを最初から
fitしてはならない。まず商品・試験・物理式からgrounded base mapを作り、その後に
小さいscale/shape補正だけを許す。

### 入れる時系列

`data/identification/raw`へ最低限、UTC時刻、速度、距離またはGNSS、pack電圧・
電流・温度、PV電力を置く。battery pulse/rest、panel sweep、coast-down、
定速、勾配、独立SoC/容量anchor、イベント記録を別sessionとして残す。

電流符号は放電正、充電負に統一する。停止、control stop、事故、センサ異常を
同じflagにせず、event YAMLで理由と時刻・地点を明示する。

### MLE実行

```powershell
.\SolarSim.ps1 -Action fit -Profile project_packages\<vehicle>\profile.yaml
```

順序は、入力QA、grounded map、segment分割、PV fit、battery OCV/Rint/capacity fit、
motion fit、11次元joint refinement、bounded map shape fit、historical replay、
day別hold-out、終端anchor、採否判定である。

確認対象は`*_generic_fit_summary.yaml`、`replay_validation.csv`、adopted maps、
PDF報告書である。training RMSEだけが低くても、時刻ずれ、同一日の過適合、
2831 km終端、独立日、物理boundが不合格なら採用しない。採用時だけcanonical
profileのmodel/map pathが更新され、simとliveが同じ車両を読む。

YATAでは25直列、race-use上限4.35 V/cellなので、`model.V_max`は
`25 * 4.35 = 108.75 V`である。OCV map最大値は108.75 V以下、YATA profileの
`V_max`は108.75 Vに一致しなければならない。`audit`は上下どちらの不整合もエラーにする。

手計算は`docs/mle_hand_calculation_workbook`の問題編、解答用紙、解答編を使う。

## route、schedule、weatherの投入

route waypoints/profile、区間速度上限、公式drive window、control stop、timezone、
全コース距離、開始UTC、`soc0`をprofileへ入れる。historical replayでは同時刻・
同地点のarchive観測を使い、将来simでは選択forecastを使う。

```powershell
.\SolarSim.ps1 -Action forecast -Profile project_packages\<vehicle>\profile.yaml
```

forecast CSVはsimの全UTC範囲を覆う必要がある。liveではchase GNSS地点で取得した
raw forecastを保存してから、観測風補正を別CSVへ書く。nominal planは最尤天候を
そのまま用い、日数とともに増える不確かさはupper/lower risk planへ分離する。

## 大会全体offline simulation

```powershell
.\SolarSim.ps1 -Action simulate -Profile project_packages\<vehicle>\profile.yaml
```

名目目的は制約付き最短時間である。

$$
\min_u T(u),\qquad
z_{\min}\le z_k\le z_{\max},\quad
z_{\min}\le z_N\le z_{\min}+\varepsilon.
$$

さらに速度、drive window、停止、電圧、放電/充電電流、温度を守る。
「使用可能energyを残さない」は物理SoC 0ではなく、終端SoCを安全下限から
`soc_finish_tol`以内へ入れる意味である。

detail CSVは各stepについて、時刻・地点、route/weather、全抵抗、map補間効率、
PV raw/MPPT、wheel/DC/regen/aux/pack power、OCV/Rint/Rline、判別式、I/V、
SoC/温度、step/cumulative energy、全scalar parameter、全map pathを持つ。
exact/fine profileでは全列を保ったままgzip圧縮し、拡張子は`*.csv.gz`となる。
`pandas.read_csv(path)`で直接読めるため、展開用の数GB空き容量は不要である。

manifestで次を確認する。

- `finish_reached=true`で、公式全コース距離へ到達した。
- `terminal_energy_band_met=true`である。
- 電圧、電流、温度、SoC、schedule違反がない。
- `power_balance_residual_w`が丸め誤差程度である。
- solver statusと証明範囲が明記される。

有限grid全列挙は、宣言した離散速度集合内では数学的な大域証明になる。SHGOと
局所改善は連続boundを探索するが、有限回の結果だけを無条件の連続大域証明とは
呼ばない。両者のstatusをmanifestで分離する。

## 実測mode

```powershell
.\SolarSim.ps1 -Mode measure -Action up -Profile project_packages\<vehicle>\profile.yaml
.\SolarSim.ps1 -Mode measure -Action status
.\SolarSim.ps1 -Mode measure -Action graph
.\SolarSim.ps1 -Mode measure -Action stop
```

動き出す前に、UTC同期、GNSS fix、停止速度、電流符号、pack電圧、loggerの新CSVを
確認する。定速、coast-down、勾配、pulse/rest、panel sweepを別runにし、run中の
人為操作、停止理由、機器切替をevent manifestへ記録する。

終了後はCSV、event、resolved profile、rqt graph、時刻同期結果を同じrun directoryへ
保存する。Excelで原本を直接編集せず、修正版を別名にする。

## WiFi、Raspberry Pi、マイコン設定

推奨固定IPは制御PC `192.168.50.10`、solar Pi `192.168.50.21`、chase Pi
`192.168.50.22`である。PCはUDP `52001`で受信し、solar/chase Piはcommandを
`52002`/`52003`で受信する。private race LANのこのUDPだけをfirewall許可する。

全機器でchrony/NTPを有効化し、開始前にUTC差が1秒未満であることを確認する。
vehicle PiはUTF-8 JSONを1--10 HzでPCへ送る。

```json
{
  "type": "vehicle_state",
  "timestamp_utc": "2027-08-28T01:23:45.120Z",
  "speed_kmh": 72.3,
  "soc": 0.83,
  "batt_temp_c": 34.2,
  "batt_current_a": 8.5,
  "batt_voltage_v": 97.6,
  "solar_power_w": 410.0,
  "lat": -22.0,
  "lon": 133.0,
  "alt_m": 612.4,
  "course_deg": 176.0
}
```

chase Piは次を送る。

```json
{
  "type": "chase_state",
  "timestamp_utc": "2027-08-28T01:23:45.120Z",
  "lat": -22.0,
  "lon": 133.0,
  "alt_m": 610.2,
  "wind_speed_ms": 6.5,
  "wind_dir_deg": 121.0,
  "course_deg": 176.0
}
```

単位はSoC 0--1、km/h、W、A、deg、WGS84で、放電電流が正である。PCは時刻なし、
5秒超の古いpacket、2秒超の未来、重複、順序逆転をfilter前に拒否する。

PCから両Piへ返る形式は次である。

```json
{
  "type": "planner_command",
  "timestamp_utc": "2027-08-28T01:23:46Z",
  "planner": {
    "speed_cmd_kmh": 71.2,
    "upper_speed_cmd_kmh": 72.0,
    "drive_mode": "eco"
  },
  "vehicle": {
    "speed_kmh": 70.9,
    "soc": 0.829,
    "s_km": 1200.02
  }
}
```

`solar_power_w`にはマイコン側で係数を掛けない。送る値はDC busの未補正実測値で、
PC側bridgeがprofileで同定済みの`solar_measurement_gain`を一度だけ適用する。
送信側と受信側の両方で補正すると、PVを過小または過大評価してSoC計画を壊す。

マイコンはUDP欠落時に過去commandを保持して加速してはならない。独立timeout、
速度上限、電流/電圧保護、driver overrideを持たせ、UDPを直接torqueへ変換しない。
実装例は`scripts/wifi_vehicle_sender_example.py`、`wifi_chase_sender_example.py`、
`templates/network`にある。

## live WiFiの起動と1周期

release gate通過後に起動する。

```powershell
.\SolarSim.ps1 -Mode live_wifi -Action up -Profile project_packages\<vehicle>\profile.yaml
```

1周期では、UDP受信、UTF-8/JSON解釈、UTC gate、range/rate filter、ROS publish、
distance/grade/wind更新、状態予測、下位1 Hz MPC、安全command bridge、UDP送信、
logger/dashboard更新を同じ時系列で行う。上位remaining-course MPCは設定周期または
forecast更新triggerで再計画する。

command bridgeはstartup hold、input timeout、low-pass、加減速上限、deadband、
0.1 km/h量子化、drive mode最低保持時間を順に適用する。weather/autocalはversioned
rawを保存し、grounded modelをboundなしで上書きしない。

dashboardで最低限、実速度、上下位command、距離、SoC、V/I、PV、wind、通信age、
planner status、警告が一画面にあることを確認する。loggerの時刻が増えない、
bridge statusがrejected、plannerがinfeasibleの場合は出発しない。

## race-day release gate

| 区分 | 合格条件 |
|---|---|
| source | audit/pytest成功、release commit/hash固定 |
| model | evidence、hold-out、終端anchor、物理bound合格 |
| race | 全距離、schedule、timezone、stop、speed limit確認 |
| simulation | finish、終端energy帯、全制約、detail balance合格 |
| ROS | 4 mode起動、実node rqt graph、重複nodeなし |
| network | 2 Pi、NTP、fresh/stale/future/duplicate UDP試験 |
| operation | dashboard/logger、disk、電源、shadow road test合格 |

開始直前にprofile hash、soc0、route/weather coverage、map provenance、remote IP/portを
二人で読み合わせる。出発後にcanonical profileを編集しない。

## 異常時の復旧

- telemetry欠落: bridgeのsafe speedへ遷移させ、time/networkを直す。gateを無効にしない。
- forecast失敗: 最後のvalid versionを保持し、ageを表示する。空CSVへ差し替えない。
- planner infeasible: 安全速度または停止へ移り、制約をその場で緩めない。
- node終了: `log`保存、`stop`、原因修正、`up`。launchを二重起動しない。
- disk逼迫: 新runを止めてarchiveする。loggerだけ無効にして走らない。
- 時刻逆転: NTP再同期後、新しいrunとして再開する。古いCSVへ追記しない。

各日終了後、clean stop、logs、manifest、resolved profile、event、manual overrideを
archiveしhashを残す。翌日のparameter更新前にその日のreplayを行う。

## 出力の所在と追跡

| path | 内容 |
|---|---|
| `outputs/logs` | measurement/live同期CSV |
| `outputs/runtime` | live raw/corrected weather、runtime state |
| `outputs/identification` | fit summary、residual、map、報告書 |
| `simulation.output_dir` | summary/detail/plan CSV、HTML、図、manifest |
| `.run/solar_<mode>.log` | launch stdout/stderr |
| `rqt_graph_solar_<mode>.png` | 実node graph |

結果を人へ渡すときは、CSV単体ではなく、manifest、resolved profile、map/evidence hash、
solver status、警告を一組にする。`latest_simulation_run.json`は最新runへの安定pointerで、
generic filenameの中身を推測してはならない。

## 教材と最終確認

- `docs/complete_flow_workbook`: live 1周期から上位MPCの有限差分、L-BFGS、有限grid証明まで。
- `docs/mle_hand_calculation_workbook`: Gaussian/Huber、PV、motion、battery、joint MLE、採否まで。
- `docs/solar_all_in_one_manual`: 物理モデル、全体構成、同定・運用の統合解説。
- `docs/package_inventory`: source/config/ROS topicの機械生成inventory。

unit testやoptimizer成功だけを、実車安全または高精度の保証にしてはならない。
採用条件は、独立data、制約付き全コースsim、実ROS起動、通信異常試験、shadow road testを
すべて通すことである。
