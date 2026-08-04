# 06. measure ROS2 launch 入口

- ファイル: `launch/solar_measurement.launch.py`
- ソースSHA-256: `070ba41b225288b85a317c3c102783d85d9df6fe189953a54ec69bf327569752`
- 種別: `ROS 2 launch Python`
- 区分: `launch`

## 役割

実測収集用に preflight、distance、grade、logger、dashboard を起動する launch。

## 起動文脈

- 起動文脈: measure モード起動時に ros2 launch される。
- 呼び出し元: `scripts/solar_control.sh`, `SolarSim.ps1`
- 次に読むべきファイル: `mpc_solarcar/distance_node.py`, `mpc_solarcar/grade_node.py`, `mpc_solarcar/solar_logger_node.py`

## 主要ポイント

- planner を起動せず、計測系だけを立てる。
- distance/grade は profile の measurement 設定で可否が決まる。

## 主要構造

主要関数は generate_launch_description。 launch から起動する Node action は 5 件。

## ファイルを上から読んだときの定義順

- L11: 関数 _cfg_path を定義する。
- L15: 関数 _setup を定義する。
- L97: 関数 generate_launch_description を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from launch import LaunchDescription`
  - launch が実行すべき action 群をまとめるため。 このファイル内での主な使用位置は L98。
- L4: `from launch.actions import DeclareLaunchArgument, OpaqueFunction`
  - DeclareLaunchArgument や OpaqueFunction など launch action を使うため。 このファイル内での主な使用位置は L100, L101。
- L5: `from launch.substitutions import LaunchConfiguration`
  - launch 引数の実行時値を参照するため。 このファイル内での主な使用位置は L16。
- L6: `from launch_ros.actions import Node`
  - ROS 2 ノード起動 action を launch から記述するため。 このファイル内での主な使用位置は L26, L39, L50, L65, L79。
- L8: `from mpc_solarcar.solar_profile import get_section, load_profile, resolve_relative_path`
  - profile YAML 読込と検証 から get_section, load_profile, resolve_relative_path を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L12, L17, L18, L19, L20, L21, L22, L23。

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


## 関数・クラスを上から順に解説

### L11 関数 `_cfg_path`

- 定義: `_cfg_path(profile_path, raw: str) -> str`
- 行範囲: L11-L12
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

### L15 関数 `_setup`

- 定義: `_setup(context)`
- 行範囲: L15-L94
- このブロックが直接呼ぶ主な関数/メソッド: `LaunchConfiguration`, `Node`, `_cfg_path`, `append`, `bool`, `float`, `get`, `get_section`, `int`, `load_profile`, `perform`, `str`
- 戻り値の要点: `nodes`
- この呼出し内で代入する主なローカル名: `cfg`, `distance_cfg`, `grade_cfg`, `logging_cfg`, `meas_logging_cfg`, `measurement_cfg`, `nodes`, `profile_path`, `profile_yaml`, `runtime_cfg`
- 制御構造の規模: 条件分岐 2、ループ 0、try 0
- 上から順の処理:
  1. profile_yaml に LaunchConfiguration('profile_yaml').perform(context) の結果を代入する。
  2. (profile_path, cfg) に load_profile(profile_yaml) の結果を代入する。
  3. runtime_cfg に get_section(cfg, 'runtime') の結果を代入する。
  4. logging_cfg に get_section(cfg, 'logging') の結果を代入する。
  5. measurement_cfg に get_section(cfg, 'measurement') の結果を代入する。
  6. distance_cfg に get_section(measurement_cfg, 'distance') の結果を代入する。
  7. grade_cfg に get_section(measurement_cfg, 'grade') の結果を代入する。
  8. meas_logging_cfg に get_section(measurement_cfg, 'logging') の結果を代入する。
  9. nodes に [Node(package='mpc_solarcar', executable='solar_preflight_node', name='solar_preflight_node', parameters=[{'require_speed': True, 'require_distance': bool(measurement_cfg.get('use_distance_node', True)), 'require_battery': False, 'require_planner': False}]), Node(package='mpc_solarcar', executable='dashboard_node', name='dashboard_node', parameters=[{'host': str(runtime_cfg.get('dashboard_host', '0.0.0.0')), 'port': int(runtime_cfg.get('dashboard_port', 8080))}]), Node(package='mpc_solarcar', executable='solar_logger_node', name='solar_logger_node', parameters=[{'log_dir': _cfg_path(profile_path, str(logging_cfg.get('log_dir', 'outputs/logs'))), 'file_prefix': str(meas_logging_cfg.get('file_prefix', 'solar_measurement')), 'log_rate_hz': float(logging_cfg.get('log_rate_hz', 2.0))}])] の結果を代入する。
  10. 条件 bool(measurement_cfg.get('use_distance_node', True)) を判定し、真なら内部処理を行う。
  11.   nodes.append(...) を実行する。
  12. 条件 bool(measurement_cfg.get('use_grade_node', True)) を判定し、真なら内部処理を行う。
  13.   nodes.append(...) を実行する。
  14. nodes を返す。

代表コード断片:

```python
def _setup(context):
    profile_yaml = LaunchConfiguration("profile_yaml").perform(context)
    profile_path, cfg = load_profile(profile_yaml)
    runtime_cfg = get_section(cfg, "runtime")
    logging_cfg = get_section(cfg, "logging")
    measurement_cfg = get_section(cfg, "measurement")
    distance_cfg = get_section(measurement_cfg, "distance")
    grade_cfg = get_section(measurement_cfg, "grade")
    meas_logging_cfg = get_section(measurement_cfg, "logging")

    nodes = [
        Node(
            package="mpc_solarcar",
            executable="solar_preflight_node",
            name="solar_preflight_node",
            parameters=[
                {
                    "require_speed": True,
                    "require_distance": bool(measurement_cfg.get("use_distance_node", True)),
                    "require_battery": False,
                    "require_planner": False,
                }
            ],
        ),
        Node(
            package="mpc_solarcar",
            executable="dashboard_node",
            name="dashboard_node",
            parameters=[
                {
                    "host": str(runtime_cfg.get("dashboard_host", "0.0.0.0")),
                    "port": int(runtime_cfg.get("dashboard_port", 8080)),
                }
            ],
        ),
...
```

### L97 関数 `generate_launch_description`

- 定義: `generate_launch_description()`
- 行範囲: L97-L103
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

- L26: `solar_preflight_node` (package=mpc_solarcar, name=solar_preflight_node)
- L39: `dashboard_node` (package=mpc_solarcar, name=dashboard_node)
- L50: `solar_logger_node` (package=mpc_solarcar, name=solar_logger_node)
- L65: `distance_node` (package=mpc_solarcar, name=distance_node)
- L79: `grade_node` (package=mpc_solarcar, name=grade_node)

## 処理の流れ

1. launch 引数を受け取り、profile を読み込む。
2. Node action を動的に組み立てる。
3. LaunchDescription として ROS 2 launch へ返す。
