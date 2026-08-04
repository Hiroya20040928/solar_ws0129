# 05. sim ROS2 launch 入口

- ファイル: `launch/solarcar_sim.launch.py`
- ソースSHA-256: `b674b3680c605030b54de4c2667bfa8ca8e409fbce6f6a970953bfa63f954da2`
- 種別: `ROS 2 launch Python`
- 区分: `launch`

## 役割

GPS 模擬、車体状態模擬、MPC、dashboard を立ち上げる simulation launch。

## 起動文脈

- 起動文脈: sim モード起動時に ros2 launch される。
- 呼び出し元: `scripts/solar_control.sh`, `SolarSim.ps1`
- 次に読むべきファイル: `mpc_solarcar/gps_sim_node.py`, `mpc_solarcar/solar_state_node.py`, `mpc_solarcar/mpc_node.py`

## 主要ポイント

- route/forecast/maps の存在確認を先に行う。
- sim 用の common_mpc パラメータ束を構成する。
- planner speed が GPS/state 側へ戻る閉ループを作る。

## 主要構造

主要関数は generate_launch_description。 launch から起動する Node action は 4 件。

## ファイルを上から読んだときの定義順

- L17: 関数 _cfg_path を定義する。
- L21: 関数 _setup を定義する。
- L146: 関数 generate_launch_description を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from launch import LaunchDescription`
  - launch が実行すべき action 群をまとめるため。 このファイル内での主な使用位置は L147。
- L4: `from launch.actions import DeclareLaunchArgument, OpaqueFunction`
  - DeclareLaunchArgument や OpaqueFunction など launch action を使うため。 このファイル内での主な使用位置は L149, L150。
- L5: `from launch.substitutions import LaunchConfiguration`
  - launch 引数の実行時値を参照するため。 このファイル内での主な使用位置は L22。
- L6: `from launch_ros.actions import Node`
  - ROS 2 ノード起動 action を launch から記述するため。 このファイル内での主な使用位置は L83, L95, L126, L132。
- L8: `from mpc_solarcar.solar_profile import get_path, get_section, load_profile, require_csv_data_rows, resolve_relative_path`
  - profile YAML 読込と検証 から get_path, get_section, load_profile, require_csv_data_rows, resolve_relative_path を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L18, L23, L24, L25, L27, L28, L29, L30, ...。

## このファイルを読む前に必要な基礎知識

次の章は、構文やROS用語を既知と仮定しないための説明である。

### プログラム、プロセス、メモリ、オブジェクトを区別する

ソースファイルはディスク上の文字列であり、それ自体は走っていない。Python実行可能プログラムがソースを読み、OSがその実行を一つのプロセスとして管理する。プロセスには仮想メモリ、開いているファイル、スレッド、終了コードなどが対応する。

```text
ソースファイル -> Pythonインタプリタが読み込む -> OS上のプロセス -> Pythonオブジェクトをメモリに生成 -> 関数やcallbackを実行
```

「メモリ上に生成する」とは、実行中プロセスが使う記憶領域に、その値の型、属性、参照関係を表す実体を用意することである。変数は実体そのものというより、そのオブジェクトを指す名前として理解するとPythonの代入が読みやすい。

```python
node = MPCNode()
alias = node
# nodeとaliasは同じオブジェクトを参照する。
```

一つのプロセスには複数スレッドを持たせられる。スレッドは同じプロセスのメモリを共有するため、受信callbackと最適化callbackが同じself.zを書き換える場合は実行順と排他を検討する必要がある。

根拠資料:

- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

### 名前、代入、型、参照

Pythonの代入文は、右辺を先に評価し、その結果のオブジェクトへ左辺の名前を結び付ける。`x = f()`では、まずfを呼び、その戻り値が得られてからxが更新される。

`float(...)`、`int(...)`、`bool(...)`は型名を呼び出して値を変換する。外部CSV、YAML、ROS parameterから来た値は型が期待どおりとは限らないため、このリポジトリでは明示変換が多い。

`None`は値が無いことを示す単一のオブジェクト、`math.nan`は浮動小数点値ではあるが有効な数値ではないことを示す。両者は用途が異なるため、`is None`と`math.isfinite`を使い分ける。

根拠資料:

- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

### 関数、引数、戻り値、スコープ

`def`は関数本体をその場で実行する文ではない。関数オブジェクトを作り、その名前を現在の名前空間へ登録する。`f`は関数そのもの、`f()`はその関数を呼んだ結果である。

仮引数は関数定義側の受け取り名、実引数は呼出側から渡す値である。位置引数、キーワード引数、既定値付き引数、`*args`、`**kwargs`は渡し方が異なる。

```python
def clip_speed(value, minimum=0.0, maximum=110.0):
    return min(maximum, max(minimum, value))

v = clip_speed(120.0, maximum=90.0)
```

関数内で作った通常の名前はローカルスコープに属する。メソッドが`self.z`を更新すればオブジェクトの状態が残るが、単に`z`を更新しただけならその呼出しのローカル値である。

根拠資料:

- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

### module、package、import、console_scripts

Pythonファイルはmoduleとして読み込める。複数moduleをディレクトリにまとめたものがpackageである。`from .model import SolarCarModel`の先頭の点は、現在と同じpackage内のmodel moduleを指す相対importである。

import時にはファイルのトップレベル文が上から一度実行される。`def`や`class`は関数・クラスを登録するが、その本体の通常処理は呼び出すまで走らない。

setuptoolsの`console_scripts`は、端末で使う実行可能名と`package.module:function`を対応付けるインストール時メタデータである。生成される実行用ラッパーはmoduleをimportし、指定関数を呼び、戻り値を終了コードとして扱う小さな入口である。

```text
ROS launchのexecutable名 -> install済みconsole script -> mpc_solarcar.mpc_nodeをimport -> main()を呼ぶ
```

根拠資料:

- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)
- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

### 例外、try/finally、with、資源解放

例外は通常の戻り値とは別経路で異常を呼出元へ伝える。`try/except`は想定した異常を処理し、`finally`は成功・失敗にかかわらず後始末を行う。

`with open(...) as f:`はcontext managerを使い、ブロックを出るとファイルを閉じる。CSVやログの破損を避けるため、開いた資源の所有者と閉じる場所を明確にする。

`except Exception: pass`はノードを止めない利点がある一方、入力異常を隠して原因追跡を難しくする。安全に関係する値では、少なくとも頻度制限付き警告、異常カウンタ、fallback状態のpublishを検討する。

### launch Action、Node Action、実行可能名、remapping

`launch_ros.actions.Node(...)`はrclpyのNode基底クラスではなく、指定したpackageのexecutableをプロセスとして起動するlaunch Actionである。

`DeclareLaunchArgument`はlaunch実行時に受け取る入力欄を宣言し、`LaunchConfiguration`はその値を後で解決するsubstitutionを表す。`perform(context)`は実行時contextから確定文字列を取り出す。

launchの`name`はNode名override、`parameters`は起動時parameter、`remappings`はNodeやtopicの既定名を別名へ対応付ける。launchはPythonファイルからmainという名前を推測せず、executableとしてインストールされたconsole scriptを起動する。

根拠資料:

- [ROS 2 Humble公式: Understanding nodes](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html)
- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)

### 天候、route、補間、時刻、単位

予報は時刻だけの系列か、時刻とroute距離の2次元gridになり得る。現在時刻tと距離sがgrid点の間なら、周囲の値から補間して日射、温度、風を求める。

UTC、現地timezone、naive datetimeを混ぜると数時間のずれが発生する。入力でtimezoneを確定し、内部比較はUTC、表示は現地時刻という役割分担が安全である。

route距離のkm、速度のkm/hとm/s、時間の秒、energyのWhとJを跨ぐため、変換係数3.6、3600、1000の意味を各式で確認する。

### 制御、状態、入力、モデル予測制御MPC

制御対象の内部を表す状態をx、操作入力をu、外乱・予報をwとすると、離散モデルは`x[k+1] = f(x[k], u[k], w[k])`と書ける。ソーラーカーではSoC、電池温度、距離、速度などが状態候補、速度目標や駆動トルクが入力候補になる。

$$
\min_{u_0,\ldots,u_{N-1}} \sum_{k=0}^{N-1}\ell(x_k,u_k,w_k)+V_f(x_N)
$$

MPCは現在状態からNステップ先まで予測し、目的関数と制約を満たす入力系列を求める。ただし実際に適用するのは通常先頭入力だけで、次回は新しい実測状態から再び解く。これがreceding horizonである。

予測モデル、目的関数、制約、ホライズン、solver、初期値のどれかが変わると答えも変わる。「MPCを使う」だけでは仕様は決まらず、これらを単位付きで追う必要がある。

根拠資料:

- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)

### ROS graph、Node、topic、service、action、parameter

ROS graphは、実行中Nodeと、それらが持つpublisher、subscription、service、actionなどの接続関係である。Pythonクラス、プロセス、ROS graph上のNode名は関連するが同一物ではない。

topicは継続データ向けの非同期一方向publish/subscribe、serviceは短いrequest/response、actionは時間のかかる目標へfeedback、cancel、resultを持たせる。parameterはNodeごとの設定値である。

publisherが送った時点とsubscription callbackが実行される時点は同じとは限らない。通信遅延、QoS queue、executor待ちを挟むため、センサ値にはtimestampとfreshness判定が必要になる。

根拠資料:

- [ROS 2 Humble公式: Understanding nodes](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html)
- [ROS 2 Humble公式: Topics, Services, Actions](https://docs.ros.org/en/humble/Concepts/Basic/Interfaces-Topics-Services-Actions.html)
- [ROS 2 Humble公式: Parameters](https://docs.ros.org/en/humble/Concepts/Basic/About-Parameters.html)

### rqt_graph、ros2 CLI、rosbag2をいつ使うか

rqt_graphは接続関係を見る道具であり、数値の正しさや更新周期までは保証しない。起動直後、topic名変更後、publisherが複数存在する疑いがある時に使う。

```bash
ros2 node list
ros2 node info /mpc_node
ros2 topic list -t
ros2 topic info -v /planner/speed_cmd
ros2 topic hz /planner/speed_cmd
ros2 topic echo /planner/status
rqt_graph
```

rosbag2はtopicメッセージを時系列のまま記録・再生する。通信不具合、freshness、再計画trigger、実車とSILSの差を再現可能にするため、本番前試験では制御入力だけでなく原因となる全telemetry、status、parameter情報を記録する。

```bash
ros2 bag record -o outputs/bags/preflight \
  /vehicle/s_km /vehicle/speed_kmh /vehicle/batt_soc \
  /vehicle/batt_temp_c /vehicle/batt_current_a /vehicle/batt_voltage_v \
  /planner/upper_speed_cmd /planner/speed_cmd /planner/status

ros2 bag info outputs/bags/preflight
ros2 bag play outputs/bags/preflight --clock
```

bag再生時はQoS互換性、simulation time、外部publisherとの二重入力に注意する。実車Nodeを同時に動かす場合はnamespaceまたはremappingで入力源を明確に分離する。

根拠資料:

- [ROS 2 Humble公式: rqt_graph](https://docs.ros.org/en/ros2_packages/humble/api/rqt_graph/index.html)
- [ROS 2 Humble公式: Recording and playing back data](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Recording-And-Playing-Back-Data/Recording-And-Playing-Back-Data.html)
- [ROS 2 Humble公式: Understanding nodes](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html)

### 単体試験、SILS、replay、観測可能性

単体試験は関数やモデル項の局所契約、SILSは複数Nodeと時間進行を含む閉ループ、historical replayは実測入力への再現性、本番preflightは実機通信と停止動作を確認する。目的が異なるため一つで代用しない。

再現可能な診断には、入力、出力、内部状態、solver成否、候補数、計算時間、fallback、source revision、profile hashを同じrun IDで記録する。

非同期不具合は最終値だけでは追えない。topic周期、message age、callback所要時間、queue遅延、Node生存、publisher数を同時に観測する。

根拠資料:

- [ROS 2 Humble公式: rqt_graph](https://docs.ros.org/en/ros2_packages/humble/api/rqt_graph/index.html)
- [ROS 2 Humble公式: Recording and playing back data](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Recording-And-Playing-Back-Data/Recording-And-Playing-Back-Data.html)
- [ROS 2公式: Executors](https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Executors.html)


## 関数・クラスを上から順に解説

### L17 関数 `_cfg_path`

- 定義: `_cfg_path(profile_path, raw: str) -> str`
- 行範囲: L17-L18
- このブロックが直接呼ぶ主な関数/メソッド: `resolve_relative_path`, `str`, `strip`
- 戻り値の要点: `resolve_relative_path(profile_path.parent, raw) if str(raw or '').strip() else ''`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. resolve_relative_path(profile_path.parent, raw) if str(raw or '').strip() else '' を返す。

代表コード断片:

```python
def _cfg_path(profile_path, raw: str) -> str:
    return resolve_relative_path(profile_path.parent, raw) if str(raw or "").strip() else ""
```

### L21 関数 `_setup`

- 定義: `_setup(context)`
- 行範囲: L21-L143
- このブロックが直接呼ぶ主な関数/メソッド: `LaunchConfiguration`, `Node`, `float`, `get`, `get_path`, `get_section`, `int`, `items`, `load_profile`, `perform`, `require_csv_data_rows`, `str`
- 戻り値の要点: `[Node(package='mpc_solarcar', executable='gps_sim_node', name='gps_sim_node', parameters=[{'route_csv': route_waypoints_csv, 'dt': float(sim_cfg.get('gps_rate_hz', 1.0)), 'init_speed_kmh': float(sim_cfg.get('gps_init_speed_kmh', sim_cfg.get('v0_kmh', 45.0)))}]), Node(package='mpc_solarcar', executable='solar_state_node', name='solar_state_node', parameters=[{'profile_yaml': str(profile_path), 'forecast_csv': forecast_csv, 'route_profile_csv': route_profile_csv, 'params_yaml': str(profile_path), 'publish_rate_hz': float(sim_cfg.get('gps_rate_hz', 1.0)), 'init_speed_kmh': float(sim_cfg.get('v0_kmh', sim_cfg.get('gps_init_speed_kmh', 45.0))), 'soc0': float(sim_cfg.get('soc0', 0.95)), 'Tb0': float(sim_cfg.get('Tb0', 30.0)), 's0_km': float(sim_cfg.get('start_s_km', 0.0)), 'forecast_time_mode': str(sim_cfg.get('forecast_time_mode', runtime_cfg.get('forecast_time_mode', 'auto'))), 'forecast_time_tz': str(runtime_cfg.get('forecast_time_tz', 'Australia/Darwin')), 'forecast_start_time_utc': str(sim_cfg.get('forecast_start_time_utc', sim_cfg.get('start_utc', ''))), 'drive_eff_map': common_mpc['drive_eff_map'], 'regen_eff_map': common_mpc['regen_eff_map'], 'rint_map': common_mpc['rint_map'], 'panel_eff_map': common_mpc['panel_eff_map'], 'mppt_eff_map': common_mpc['mppt_eff_map'], 'drive_map_eco': common_mpc['drive_map_eco'], 'drive_map_power': common_mpc['drive_map_power'], 'regen_map_eco': common_mpc['regen_map_eco'], 'regen_map_power': common_mpc['regen_map_power'], 'ocv_soc_map': common_mpc['ocv_soc_map']}]), Node(package='mpc_solarcar', executable='mpc_node', name='mpc_node', parameters=[common_mpc]), Node(package='mpc_solarcar', executable='dashboard_node', name='dashboard_node', parameters=[{'host': str(runtime_cfg.get('dashboard_host', '0.0.0.0')), 'port': int(runtime_cfg.get('dashboard_port', 8080))}])]`
- この呼出し内で代入する主なローカル名: `cfg`, `columns`, `common_mpc`, `drive_schedule_yaml`, `forecast_csv`, `key`, `label`, `path`, `profile_path`, `profile_yaml`, `required_csvs`, `route_profile_csv`, `route_waypoints_csv`, `runtime_cfg`, `sim_cfg`, `speed_profile_csv`, `stop_yaml`
- 制御構造の規模: 条件分岐 0、ループ 2、try 0
- 上から順の処理:
  1. profile_yaml に LaunchConfiguration('profile_yaml').perform(context) の結果を代入する。
  2. (profile_path, cfg) に load_profile(profile_yaml) の結果を代入する。
  3. runtime_cfg に get_section(cfg, 'runtime') の結果を代入する。
  4. sim_cfg に get_section(cfg, 'simulation') の結果を代入する。
  5. forecast_csv に get_path(cfg, profile_path, 'forecast_csv') の結果を代入する。
  6. route_waypoints_csv に get_path(cfg, profile_path, 'route_waypoints_csv') の結果を代入する。
  7. route_profile_csv に get_path(cfg, profile_path, 'route_profile_csv') の結果を代入する。
  8. speed_profile_csv に get_path(cfg, profile_path, 'speed_profile_csv') の結果を代入する。
  9. stop_yaml に get_path(cfg, profile_path, 'stop_yaml') の結果を代入する。
  10. drive_schedule_yaml に get_path(cfg, profile_path, 'drive_schedule_yaml') の結果を代入する。
  11. required_csvs に {'route waypoints': (route_waypoints_csv, ('dist_km',)), 'route profile': (route_profile_csv, ('dist_km',)), 'speed profile': (speed_profile_csv, ()), 'forecast': (forecast_csv, ('GHI',))} の結果を代入する。
  12. ('drive_eff_map', 'regen_eff_map', 'rint_map', 'panel_eff_map', 'mppt_eff_map', 'drive_map_eco', 'drive_map_power', 'regen_map_eco', 'regen_map_power', 'ocv_soc_map') を順に走査し、各要素を key に入れて処理する。
  13.   required_csvs[key] に (get_path(cfg, profile_path, key), ()) の結果を代入する。
  14. required_csvs.items() を順に走査し、各要素を (label, (path, columns)) に入れて処理する。
  15.   require_csv_data_rows(...) を実行する。
  16. common_mpc に {'forecast_csv': forecast_csv, 'route_profile_csv': route_profile_csv, 'speed_profile_csv': speed_profile_csv, 'stop_yaml': stop_yaml, 'drive_schedule_yaml': drive_schedule_yaml, 'drive_eff_map': get_path(cfg, profile_path, 'drive_eff_map'), 'regen_eff_map': get_path(cfg, profile_path, 'regen_eff_map'), 'rint_map': get_path(cfg, profile_path, 'rint_map'), 'panel_eff_map': get_path(cfg, profile_path, 'panel_eff_map'), 'mppt_eff_map': get_path(cfg, profile_path, 'mppt_eff_map'), 'drive_map_eco': get_path(cfg, profile_path, 'drive_map_eco'), 'drive_map_power': get_path(cfg, profile_path, 'drive_map_power'), 'regen_map_eco': get_path(cfg, profile_path, 'regen_map_eco'), 'regen_map_power': get_path(cfg, profile_path, 'regen_map_power'), 'ocv_soc_map': get_path(cfg, profile_path, 'ocv_soc_map'), 'params_yaml': str(profile_path), 'profile_runtime_mode': 'simulation', 'forecast_time_mode': str(sim_cfg.get('forecast_time_mode', runtime_cfg.get('forecast_time_mode', 'auto'))), 'forecast_time_tz': str(runtime_cfg.get('forecast_time_tz', 'Australia/Darwin')), 'forecast_start_time_utc': str(sim_cfg.get('forecast_start_time_utc', sim_cfg.get('start_utc', ''))), 'soc0': float(sim_cfg.get('soc0', 0.95)), 'Tb0': float(sim_cfg.get('Tb0', 30.0)), 's0_km': float(sim_cfg.get('start_s_km', 0.0))} の結果を代入する。
  17. [Node(package='mpc_solarcar', executable='gps_sim_node', name='gps_sim_node', parameters=[{'route_csv': route_waypoints_csv, 'dt': float(sim_cfg.get('gps_rate_hz', 1.0)), 'init_speed_kmh': float(sim_cfg.get('gps_init_speed_kmh', sim_cfg.get('v0_kmh', 45.0)))}]), Node(package='mpc_solarcar', executable='solar_state_node', name='solar_state_node', parameters=[{'profile_yaml': str(profile_path), 'forecast_csv': forecast_csv, 'route_profile_csv': route_profile_csv, 'params_yaml': str(profile_path), 'publish_rate_hz': float(sim_cfg.get('gps_rate_hz', 1.0)), 'init_speed_kmh': float(sim_cfg.get('v0_kmh', sim_cfg.get('gps_init_speed_kmh', 45.0))), 'soc0': float(sim_cfg.get('soc0', 0.95)), 'Tb0': float(sim_cfg.get('Tb0', 30.0)), 's0_km': float(sim_cfg.get('start_s_km', 0.0)), 'forecast_time_mode': str(sim_cfg.get('forecast_time_mode', runtime_cfg.get('forecast_time_mode', 'auto'))), 'forecast_time_tz': str(runtime_cfg.get('forecast_time_tz', 'Australia/Darwin')), 'forecast_start_time_utc': str(sim_cfg.get('forecast_start_time_utc', sim_cfg.get('start_utc', ''))), 'drive_eff_map': common_mpc['drive_eff_map'], 'regen_eff_map': common_mpc['regen_eff_map'], 'rint_map': common_mpc['rint_map'], 'panel_eff_map': common_mpc['panel_eff_map'], 'mppt_eff_map': common_mpc['mppt_eff_map'], 'drive_map_eco': common_mpc['drive_map_eco'], 'drive_map_power': common_mpc['drive_map_power'], 'regen_map_eco': common_mpc['regen_map_eco'], 'regen_map_power': common_mpc['regen_map_power'], 'ocv_soc_map': common_mpc['ocv_soc_map']}]), Node(package='mpc_solarcar', executable='mpc_node', name='mpc_node', parameters=[common_mpc]), Node(package='mpc_solarcar', executable='dashboard_node', name='dashboard_node', parameters=[{'host': str(runtime_cfg.get('dashboard_host', '0.0.0.0')), 'port': int(runtime_cfg.get('dashboard_port', 8080))}])] を返す。

代表コード断片:

```python
def _setup(context):
    profile_yaml = LaunchConfiguration("profile_yaml").perform(context)
    profile_path, cfg = load_profile(profile_yaml)
    runtime_cfg = get_section(cfg, "runtime")
    sim_cfg = get_section(cfg, "simulation")

    forecast_csv = get_path(cfg, profile_path, "forecast_csv")
    route_waypoints_csv = get_path(cfg, profile_path, "route_waypoints_csv")
    route_profile_csv = get_path(cfg, profile_path, "route_profile_csv")
    speed_profile_csv = get_path(cfg, profile_path, "speed_profile_csv")
    stop_yaml = get_path(cfg, profile_path, "stop_yaml")
    drive_schedule_yaml = get_path(cfg, profile_path, "drive_schedule_yaml")

    required_csvs = {
        "route waypoints": (route_waypoints_csv, ("dist_km",)),
        "route profile": (route_profile_csv, ("dist_km",)),
        "speed profile": (speed_profile_csv, ()),
        "forecast": (forecast_csv, ("GHI",)),
    }
    for key in (
        "drive_eff_map",
        "regen_eff_map",
        "rint_map",
        "panel_eff_map",
        "mppt_eff_map",
        "drive_map_eco",
        "drive_map_power",
        "regen_map_eco",
        "regen_map_power",
        "ocv_soc_map",
    ):
        required_csvs[key] = (get_path(cfg, profile_path, key), ())
    for label, (path, columns) in required_csvs.items():
        require_csv_data_rows(path, label=label, required_columns=columns)

...
```

### L146 関数 `generate_launch_description`

- 定義: `generate_launch_description()`
- 行範囲: L146-L152
- このブロックが直接呼ぶ主な関数/メソッド: `DeclareLaunchArgument`, `LaunchDescription`, `OpaqueFunction`
- 戻り値の要点: `LaunchDescription([DeclareLaunchArgument('profile_yaml', default_value='config/solar/bwsc_2027_demo.yaml'), OpaqueFunction(function=_setup)])`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- 上から順の処理:
  1. LaunchDescription([DeclareLaunchArgument('profile_yaml', default_value='config/solar/bwsc_2027_demo.yaml'), OpaqueFunction(function=_setup)]) を返す。

代表コード断片:

```python
def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("profile_yaml", default_value="config/solar/bwsc_2027_demo.yaml"),
            OpaqueFunction(function=_setup),
        ]
    )
```


## launch から起動するノード

- L83: `gps_sim_node` (package=mpc_solarcar, name=gps_sim_node)
- L95: `solar_state_node` (package=mpc_solarcar, name=solar_state_node)
- L126: `mpc_node` (package=mpc_solarcar, name=mpc_node)
- L132: `dashboard_node` (package=mpc_solarcar, name=dashboard_node)

## 処理の流れ

1. launch 引数を受け取り、profile を読み込む。
2. Node action を動的に組み立てる。
3. LaunchDescription として ROS 2 launch へ返す。
