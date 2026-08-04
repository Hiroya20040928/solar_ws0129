# 29. solar 運用 CSV logger

- ファイル: `mpc_solarcar/solar_logger_node.py`
- ソースSHA-256: `6ad5861c795593dc8a6cbd661335f2d379ddf42987433a40f1805c49884b5e2e`
- 種別: `Python`
- 区分: `runtime node`

## 役割

vehicle、planner、weather、calib、system、raw telemetry を一つの時刻行へ集約して CSV に書く。

## 起動文脈

- 起動文脈: 運用ログの最終集約点。
- 呼び出し元: `mpc_solarcar/live_launch.py`, `launch/solar_measurement.launch.py`
- 次に読むべきファイル: 特になし

## 主要ポイント

- topic 名と CSV 列名の対応を内部辞書で持つ。
- planner/env、planner/metrics、planner/status も記録する。

## 主要構造

主要クラスは SolarLoggerNode。 主要関数は handler, handler, handler, destroy_node, main。 ROS パラメータ宣言は 6 件。 ROS I/O は publisher 0 件、subscription 6 件。

## ファイルを上から読んだときの定義順

- L11: FLOAT_TOPICS に {'speed_kmh': '/vehicle/speed_kmh', 's_km': '/vehicle/s_km', 'altitude_m': '/vehicle/altitude_m', 'grade_pct': '/vehicle/grade', 'batt_soc': '/vehicle/batt_soc', 'batt_temp_c': '/vehicle/batt_temp_c', 'batt_current_a': '/vehicle/batt_current_a', 'batt_voltage_v': '/vehicle/batt_voltage_v', 'solar_power_w': '/vehicle/solar_power_w', 'headwind_meas_ms': '/weather/headwind_meas_ms', 'headwind_corrected_ms': '/weather/headwind_corrected_ms', 'wind_speed_ms': '/weather/wind_speed_ms', 'wind_dir_deg': '/weather/wind_dir_deg', 'course_deg': '/weather/course_deg', 'speed_cmd_kmh': '/planner/speed_cmd', 'upper_speed_cmd_kmh': '/planner/upper_speed_cmd', 'throttle_cmd_pct': '/planner/throttle_cmd_pct', 'calib_solar_gain': '/calib/solar_gain', 'calib_drive_power_gain': '/calib/drive_power_gain', 'calib_aux_power_w': '/calib/aux_power_w', 'system_health': '/system/health'} の結果を代入する。
- L35: FLOAT64_TOPICS に {'solar_source_ts_unix': '/telemetry/solar_source_ts_unix', 'chase_source_ts_unix': '/telemetry/chase_source_ts_unix'} の結果を代入する。
- L40: STRING_TOPICS に {'drive_mode': '/planner/drive_mode', 'system_state': '/system/state', 'system_diag': '/system/diag', 'mpc_state': '/system/mpc_state', 'telemetry_bridge_status': '/telemetry/bridge_status', 'wind_correction_status': '/weather/wind_correction_status', 'weather_fetch_status': '/weather/fetch_status', 'autocal_status': '/calib/status', 'raw_solar': '/telemetry/raw_solar', 'raw_chase': '/telemetry/raw_chase'} の結果を代入する。
- L53: ARRAY_TOPICS に {'/planner/status': ['planner_soc', 'planner_temp_c', 'planner_s_km', 'planner_step', 'planner_sec_to_next', 'planner_control_stop_hold', 'planner_control_stop_remaining_sec', 'planner_control_stop_completed_count'], '/planner/metrics': ['model_pack_voltage_v', 'model_pack_current_a', 'model_soc', 'model_motor_power_w', 'model_motor_current_a', 'model_pv_power_w', 'model_speed_kmh', 'model_mech_power_w', 'model_pack_power_w'], '/planner/env': ['env_poa_wm2', 'env_cell_temp_c', 'env_ambient_temp_c', 'env_grade_pct', 'env_headwind_ms']} の結果を代入する。
- L85: クラス SolarLoggerNode を定義する。
- L192: 関数 main を定義する。

## import 群

- L1: `import csv`
  - CSV の逐次読込・逐次書込を行うため。 このファイル内での主な使用位置は L133。
- L2: `import math`
  - Python標準のスカラー数値関数と定数を使うため。実際に参照する名前と行は使用位置欄で確認する。 このファイル内での主な使用位置は L109, L144, L158, L168。
- L3: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L95, L101, L103。
- L4: `from datetime import datetime, timezone`
  - UTC 時刻や相対時間を扱うため。 このファイル内での主な使用位置は L102, L172。
- L6: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L193, L196, L199。
- L7: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L85。
- L8: `from std_msgs.msg import Float32, Float32MultiArray, Float64, String`
  - Float32、Bool、Stringなどの標準ROS messageで値をpublishまたはsubscribeするため。 このファイル内での主な使用位置は L115, L117, L119, L121, L126, L129。

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

### class、独自クラス、インスタンス、self、継承

クラスは、保持するデータと、そのデータを扱う関数を一つの型としてまとめる設計単位である。「独自クラス」とはPythonやROS 2が最初から用意した型ではなく、このプロジェクトが目的に合わせて定義した新しい型を指す。

`class MPCNode(Node)`は、rclpyのNodeを基底クラスとして継承し、Nodeが持つpublisher、subscription、timer、parameterなどの機能にMPC固有機能を追加する。丸括弧内は関数引数ではなく基底クラス指定である。

`MPCNode()`はクラスオブジェクトを呼び出して新しいインスタンスを作る。Pythonは新しい実体を用意し、その実体を第1引数selfとして`__init__`へ渡す。`self`は予約語ではなく慣習的な名前だが、この慣習を守ることでコードの意味が共有される。

```python
class Counter:
    def __init__(self):
        self.value = 0

    def increment(self):
        self.value += 1

counter = Counter()
counter.increment()
```

`super().__init__(...)`は継承元の初期化処理を呼ぶ。MPCNodeではこれを省くとROSノードとして必要な内部実体が作られず、`create_publisher`などを正しく使えない。

根拠資料:

- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)
- [ROS 2 Humble公式: Understanding nodes](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html)

### 先頭アンダースコア、__init__、名前付けの作法

`self._step_solar`の先頭1個のアンダースコアは「クラス内部で使う実装詳細」という慣習であり、アクセスを強制禁止する機構ではない。外部コードから呼べるが、公開APIとして依存しない意思表示である。

`__init__`の前後2個のアンダースコアはPythonが定めた特殊メソッド名である。クラス生成時に自動で呼ばれる。任意の名前に前後2個を付けて独自仕様を作ることは避ける。

`_`で始まるローカル変数は、未使用または外部へ見せない意図を示す場合がある。例えば`_base_csv`は戻り値として受け取る必要はあるが、その後の処理では使わないことを読者へ示す。

根拠資料:

- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

### rclpy、rcl、rmw、DDS/RTPSの層

rclpyはPython利用者向けROS 2 client libraryである。利用者のNode、publisher、subscriptionなどをPython APIとして提供し、その下で共通C層のrclを利用する。

```text
本プロジェクトのPythonコード -> rclpy -> rcl -> rmw -> DDS/RTPS実装 -> ネットワークまたは同一PC内通信
```

rclは言語に依存しない共通ROS機能を提供するC API、rmwはROS 2と具体的middleware実装の境界である。DDS/RTPS側が探索、serialize、publish/subscribe、request/replyなどを担う。executorの実行モデルはrclだけで完結せずclient library側にも実装される。

根拠資料:

- [ROS 2 Humble公式: Internal ROS 2 interfaces](https://docs.ros.org/en/humble/Concepts/About-Internal-Interfaces.html)

### ROS graph、Node、topic、service、action、parameter

ROS graphは、実行中Nodeと、それらが持つpublisher、subscription、service、actionなどの接続関係である。Pythonクラス、プロセス、ROS graph上のNode名は関連するが同一物ではない。

topicは継続データ向けの非同期一方向publish/subscribe、serviceは短いrequest/response、actionは時間のかかる目標へfeedback、cancel、resultを持たせる。parameterはNodeごとの設定値である。

publisherが送った時点とsubscription callbackが実行される時点は同じとは限らない。通信遅延、QoS queue、executor待ちを挟むため、センサ値にはtimestampとfreshness判定が必要になる。

根拠資料:

- [ROS 2 Humble公式: Understanding nodes](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html)
- [ROS 2 Humble公式: Topics, Services, Actions](https://docs.ros.org/en/humble/Concepts/Basic/Interfaces-Topics-Services-Actions.html)
- [ROS 2 Humble公式: Parameters](https://docs.ros.org/en/humble/Concepts/Basic/About-Parameters.html)

### callback、timer、Executor、spin、Callback Group

callbackは、メッセージ受信、timer満了、service requestなどのイベントが成立した後でExecutorから呼ばれる関数である。登録時に`self._on_speed`と括弧なしで渡すのは、今実行せず後で呼ぶ関数オブジェクトを渡すためである。

Executorは実行可能になったcallbackを見つけ、Callback Groupの条件を確認して実行する。`spin()`は終了要求まで待機・dispatchを続けるため、通常運転中はmainの次の行へ戻らない。

MutuallyExclusiveCallbackGroupは同じgroup内のcallbackを同時実行させない。別group間はMultiThreadedExecutorで並行実行し得る。groupを分けただけでは共有属性への完全な排他にはならないため、複数groupが同じ状態を読む・書く場合は設計確認が必要である。

```text
DDS受信またはtimer満了 -> wait setでready -> Executorが選択 -> Callback Groupが許可 -> worker threadがcallback実行 -> 終了後Executorへ戻る
```

根拠資料:

- [ROS 2公式: Executors](https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Executors.html)
- [ROS 2 Humble公式: Internal ROS 2 interfaces](https://docs.ros.org/en/humble/Concepts/About-Internal-Interfaces.html)

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


## 関数・クラスを上から順に解説

### L85 クラス `SolarLoggerNode`

- 定義: `SolarLoggerNode(bases=Node)`
- 行範囲: L85-L189
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - class文は新しい型を定義する。丸括弧内は継承する基底クラスである。
  - 内包表記は、反復・条件・値生成を一つの式で記述してcollectionを作る。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _set_float を定義する。
  3. 関数 _set_string を定義する。
  4. 関数 _set_array を定義する。
  5. 関数 _clean_float を定義する。
  6. 関数 _write_row を定義する。
  7. 関数 destroy_node を定義する。

代表コード断片:

```python
class SolarLoggerNode(Node):
    def __init__(self):
        super().__init__("solar_logger_node")
        self.declare_parameter("log_dir", "outputs/logs")
        self.declare_parameter("file_prefix", "solar_live")
        self.declare_parameter("log_rate_hz", 2.0)
        self.declare_parameter("flush_every_rows", 1)
        self.declare_parameter("output_speed_topic", "/vehicle/speed_cmd_kmh")
        self.declare_parameter("output_drive_mode_topic", "/vehicle/drive_mode_cmd")

        log_dir = os.fspath(self.get_parameter("log_dir").value)
        prefix = str(self.get_parameter("file_prefix").value)
        rate_hz = max(0.1, float(self.get_parameter("log_rate_hz").value))
        self.flush_every_rows = max(1, int(self.get_parameter("flush_every_rows").value))
        self.rows_since_flush = 0

        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(log_dir, f"{prefix}_{stamp}.csv")

        array_fields = [field for fields in ARRAY_TOPICS.values() for field in fields]
        self.fields = ["t_ros_sec", "t_wall_utc"] + list(FLOAT_TOPICS) + list(FLOAT64_TOPICS) + [
            "output_speed_cmd_kmh",
        ] + list(STRING_TOPICS) + ["output_drive_mode"] + array_fields
        self.latest = {field: math.nan for field in self.fields}
        for field in ["t_wall_utc", *STRING_TOPICS, "output_drive_mode"]:
            self.latest[field] = ""

        self._topic_subscriptions = []
        for field, topic in FLOAT_TOPICS.items():
            self._topic_subscriptions.append(self.create_subscription(Float32, topic, self._set_float(field), 10))
        for field, topic in FLOAT64_TOPICS.items():
            self._topic_subscriptions.append(self.create_subscription(Float64, topic, self._set_float(field), 10))
        for field, topic in STRING_TOPICS.items():
            self._topic_subscriptions.append(self.create_subscription(String, topic, self._set_string(field), 10))
...
```

### L86 関数 `SolarLoggerNode.__init__`

- 定義: `__init__(self)`
- 行範囲: L86-L137
- 所属: `SolarLoggerNode`
- このブロックが直接呼ぶ主な関数/メソッド: `DictWriter`, `__init__`, `_set_array`, `_set_float`, `_set_string`, `append`, `create_subscription`, `create_timer`, `declare_parameter`, `float`, `flush`, `fspath`
- この呼出し内で代入する主なローカル名: `array_fields`, `field`, `fields`, `log_dir`, `output_mode_topic`, `output_speed_topic`, `prefix`, `rate_hz`, `stamp`, `topic`
- 読み取る主なインスタンス属性: `self._set_array`, `self._set_float`, `self._set_string`, `self._topic_subscriptions`, `self._write_row`, `self.create_subscription`, `self.create_timer`, `self.csv_file`, `self.declare_parameter`, `self.fields`, `self.get_logger`, `self.get_parameter`, `self.latest`, `self.log_path`, `self.writer`
- 更新する主なインスタンス属性: `self._topic_subscriptions`, `self.csv_file`, `self.fields`, `self.flush_every_rows`, `self.latest`, `self.log_path`, `self.rows_since_flush`, `self.timer`, `self.writer`
- 制御構造の規模: 条件分岐 0、ループ 5、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - 内包表記は、反復・条件・値生成を一つの式で記述してcollectionを作る。
- 上から順の処理:
  1. super().__init__(...) を実行する。
  2. self.declare_parameter(...) を実行する。
  3. self.declare_parameter(...) を実行する。
  4. self.declare_parameter(...) を実行する。
  5. self.declare_parameter(...) を実行する。
  6. self.declare_parameter(...) を実行する。
  7. self.declare_parameter(...) を実行する。
  8. log_dir に os.fspath(self.get_parameter('log_dir').value) の結果を代入する。
  9. prefix に str(self.get_parameter('file_prefix').value) の結果を代入する。
  10. rate_hz に max(0.1, float(self.get_parameter('log_rate_hz').value)) の結果を代入する。
  11. self.flush_every_rows に max(1, int(self.get_parameter('flush_every_rows').value)) の結果を代入する。
  12. self.rows_since_flush に 0 の結果を代入する。
  13. os.makedirs(...) を実行する。
  14. stamp に datetime.now().strftime('%Y%m%d_%H%M%S') の結果を代入する。
  15. self.log_path に os.path.join(log_dir, f'{prefix}_{stamp}.csv') の結果を代入する。
  16. array_fields に [field for fields in ARRAY_TOPICS.values() for field in fields] の結果を代入する。
  17. self.fields に ['t_ros_sec', 't_wall_utc'] + list(FLOAT_TOPICS) + list(FLOAT64_TOPICS) + ['output_speed_cmd_kmh'] + list(STRING_TOPICS) + ['output_drive_mode'] + array_fields の結果を代入する。
  18. self.latest に {field: math.nan for field in self.fields} の結果を代入する。
  19. ['t_wall_utc', *STRING_TOPICS, 'output_drive_mode'] を順に走査し、各要素を field に入れて処理する。
  20.   self.latest[field] に '' の結果を代入する。
  21. self._topic_subscriptions に [] の結果を代入する。
  22. FLOAT_TOPICS.items() を順に走査し、各要素を (field, topic) に入れて処理する。
  23.   self._topic_subscriptions.append(...) を実行する。
  24. FLOAT64_TOPICS.items() を順に走査し、各要素を (field, topic) に入れて処理する。
  25.   self._topic_subscriptions.append(...) を実行する。
  26. STRING_TOPICS.items() を順に走査し、各要素を (field, topic) に入れて処理する。
  27.   self._topic_subscriptions.append(...) を実行する。
  28. ARRAY_TOPICS.items() を順に走査し、各要素を (topic, fields) に入れて処理する。
  29.   self._topic_subscriptions.append(...) を実行する。
  30. output_speed_topic に str(self.get_parameter('output_speed_topic').value) の結果を代入する。
  31. output_mode_topic に str(self.get_parameter('output_drive_mode_topic').value) の結果を代入する。
  32. self._topic_subscriptions.append(...) を実行する。
  33. self._topic_subscriptions.append(...) を実行する。
  34. self.csv_file に open(self.log_path, 'w', encoding='utf-8', newline='') の結果を代入する。
  35. self.writer に csv.DictWriter(self.csv_file, fieldnames=self.fields) の結果を代入する。
  36. self.writer.writeheader(...) を実行する。
  37. self.csv_file.flush(...) を実行する。
  38. self.timer に self.create_timer(1.0 / rate_hz, self._write_row) の結果を代入する。
  39. self.get_logger().info(...) を実行する。

代表コード断片:

```python
    def __init__(self):
        super().__init__("solar_logger_node")
        self.declare_parameter("log_dir", "outputs/logs")
        self.declare_parameter("file_prefix", "solar_live")
        self.declare_parameter("log_rate_hz", 2.0)
        self.declare_parameter("flush_every_rows", 1)
        self.declare_parameter("output_speed_topic", "/vehicle/speed_cmd_kmh")
        self.declare_parameter("output_drive_mode_topic", "/vehicle/drive_mode_cmd")

        log_dir = os.fspath(self.get_parameter("log_dir").value)
        prefix = str(self.get_parameter("file_prefix").value)
        rate_hz = max(0.1, float(self.get_parameter("log_rate_hz").value))
        self.flush_every_rows = max(1, int(self.get_parameter("flush_every_rows").value))
        self.rows_since_flush = 0

        os.makedirs(log_dir, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(log_dir, f"{prefix}_{stamp}.csv")

        array_fields = [field for fields in ARRAY_TOPICS.values() for field in fields]
        self.fields = ["t_ros_sec", "t_wall_utc"] + list(FLOAT_TOPICS) + list(FLOAT64_TOPICS) + [
            "output_speed_cmd_kmh",
        ] + list(STRING_TOPICS) + ["output_drive_mode"] + array_fields
        self.latest = {field: math.nan for field in self.fields}
        for field in ["t_wall_utc", *STRING_TOPICS, "output_drive_mode"]:
            self.latest[field] = ""

        self._topic_subscriptions = []
        for field, topic in FLOAT_TOPICS.items():
            self._topic_subscriptions.append(self.create_subscription(Float32, topic, self._set_float(field), 10))
        for field, topic in FLOAT64_TOPICS.items():
            self._topic_subscriptions.append(self.create_subscription(Float64, topic, self._set_float(field), 10))
        for field, topic in STRING_TOPICS.items():
            self._topic_subscriptions.append(self.create_subscription(String, topic, self._set_string(field), 10))
        for topic, fields in ARRAY_TOPICS.items():
...
```

### L139 関数 `SolarLoggerNode._set_float`

- 定義: `_set_float(self, field)`
- 行範囲: L139-L146
- 所属: `SolarLoggerNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`
- 戻り値の要点: `handler`
- 読み取る主なインスタンス属性: `self.latest`
- 制御構造の規模: 条件分岐 0、ループ 0、try 1
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 関数 handler を定義する。
  2. handler を返す。

代表コード断片:

```python
    def _set_float(self, field):
        def handler(msg):
            try:
                self.latest[field] = float(msg.data)
            except (TypeError, ValueError):
                self.latest[field] = math.nan

        return handler
```

### L140 関数 `SolarLoggerNode._set_float.handler`

- 定義: `handler(msg)`
- 行範囲: L140-L144
- 所属: `SolarLoggerNode._set_float`
- このブロックが直接呼ぶ主な関数/メソッド: `float`
- 読み取る主なインスタンス属性: `self.latest`
- 制御構造の規模: 条件分岐 0、ループ 0、try 1
- この定義を読むためのPython構文:
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 例外処理を伴う try ブロックを実行する。
  2.   self.latest[field] に float(msg.data) の結果を代入する。
  3.   (TypeError, ValueError)を捕捉した場合:
  4.   self.latest[field] に math.nan の結果を代入する。

代表コード断片:

```python
        def handler(msg):
            try:
                self.latest[field] = float(msg.data)
            except (TypeError, ValueError):
                self.latest[field] = math.nan
```

### L148 関数 `SolarLoggerNode._set_string`

- 定義: `_set_string(self, field)`
- 行範囲: L148-L152
- 所属: `SolarLoggerNode`
- このブロックが直接呼ぶ主な関数/メソッド: `replace`, `str`
- 戻り値の要点: `handler`
- 読み取る主なインスタンス属性: `self.latest`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. 関数 handler を定義する。
  2. handler を返す。

代表コード断片:

```python
    def _set_string(self, field):
        def handler(msg):
            self.latest[field] = str(msg.data).replace("\r", "").replace("\n", "\\n")

        return handler
```

### L149 関数 `SolarLoggerNode._set_string.handler`

- 定義: `handler(msg)`
- 行範囲: L149-L150
- 所属: `SolarLoggerNode._set_string`
- このブロックが直接呼ぶ主な関数/メソッド: `replace`, `str`
- 読み取る主なインスタンス属性: `self.latest`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- 上から順の処理:
  1. self.latest[field] に str(msg.data).replace('\r', '').replace('\n', '\\n') の結果を代入する。

代表コード断片:

```python
        def handler(msg):
            self.latest[field] = str(msg.data).replace("\r", "").replace("\n", "\\n")
```

### L154 関数 `SolarLoggerNode._set_array`

- 定義: `_set_array(self, fields)`
- 行範囲: L154-L160
- 所属: `SolarLoggerNode`
- このブロックが直接呼ぶ主な関数/メソッド: `enumerate`, `float`, `len`, `list`
- 戻り値の要点: `handler`
- この呼出し内で代入する主なローカル名: `field`, `idx`, `values`
- 読み取る主なインスタンス属性: `self.latest`
- 制御構造の規模: 条件分岐 0、ループ 1、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. 関数 handler を定義する。
  2. handler を返す。

代表コード断片:

```python
    def _set_array(self, fields):
        def handler(msg):
            values = list(msg.data)
            for idx, field in enumerate(fields):
                self.latest[field] = float(values[idx]) if idx < len(values) else math.nan

        return handler
```

### L155 関数 `SolarLoggerNode._set_array.handler`

- 定義: `handler(msg)`
- 行範囲: L155-L158
- 所属: `SolarLoggerNode._set_array`
- このブロックが直接呼ぶ主な関数/メソッド: `enumerate`, `float`, `len`, `list`
- この呼出し内で代入する主なローカル名: `field`, `idx`, `values`
- 読み取る主なインスタンス属性: `self.latest`
- 制御構造の規模: 条件分岐 0、ループ 1、try 0
- 上から順の処理:
  1. values に list(msg.data) の結果を代入する。
  2. enumerate(fields) を順に走査し、各要素を (idx, field) に入れて処理する。
  3.   self.latest[field] に float(values[idx]) if idx < len(values) else math.nan の結果を代入する。

代表コード断片:

```python
        def handler(msg):
            values = list(msg.data)
            for idx, field in enumerate(fields):
                self.latest[field] = float(values[idx]) if idx < len(values) else math.nan
```

### L163 関数 `SolarLoggerNode._clean_float`

- 定義: `_clean_float(value)`
- 行範囲: L163-L168
- 所属: `SolarLoggerNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `isfinite`
- 戻り値の要点: `value if math.isfinite(value) else '' / ''`
- この呼出し内で代入する主なローカル名: `value`
- 制御構造の規模: 条件分岐 0、ループ 0、try 1
- この定義を読むためのPython構文:
  - @で始まる行は、定義した関数を別の関数へ渡して加工するdecoratorである。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 例外処理を伴う try ブロックを実行する。
  2.   value に float(value) の結果を代入する。
  3.   (TypeError, ValueError)を捕捉した場合:
  4.   '' を返す。
  5. value if math.isfinite(value) else '' を返す。

代表コード断片:

```python
    def _clean_float(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return ""
        return value if math.isfinite(value) else ""
```

### L170 関数 `SolarLoggerNode._write_row`

- 定義: `_write_row(self)`
- 行範囲: L170-L181
- 所属: `SolarLoggerNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_clean_float`, `flush`, `get`, `get_clock`, `isoformat`, `now`, `str`, `writerow`
- この呼出し内で代入する主なローカル名: `field`, `row`, `string_fields`
- 読み取る主なインスタンス属性: `self._clean_float`, `self.csv_file`, `self.fields`, `self.flush_every_rows`, `self.get_clock`, `self.latest`, `self.rows_since_flush`, `self.writer`
- 更新する主なインスタンス属性: `self.rows_since_flush`
- 制御構造の規模: 条件分岐 1、ループ 1、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self.latest['t_ros_sec'] に self.get_clock().now().nanoseconds / 1000000000.0 の結果を代入する。
  2. self.latest['t_wall_utc'] に datetime.now(timezone.utc).isoformat() の結果を代入する。
  3. row に {} の結果を代入する。
  4. string_fields に {'t_wall_utc', *STRING_TOPICS, 'output_drive_mode'} の結果を代入する。
  5. self.fields を順に走査し、各要素を field に入れて処理する。
  6.   row[field] に str(self.latest.get(field, '')) if field in string_fields else self._clean_float(self.latest.get(field)) の結果を代入する。
  7. self.writer.writerow(...) を実行する。
  8. self.rows_since_flush を Add で更新する。
  9. 条件 self.rows_since_flush >= self.flush_every_rows を判定し、真なら内部処理を行う。
  10.   self.csv_file.flush(...) を実行する。
  11.   self.rows_since_flush に 0 の結果を代入する。

代表コード断片:

```python
    def _write_row(self):
        self.latest["t_ros_sec"] = self.get_clock().now().nanoseconds / 1.0e9
        self.latest["t_wall_utc"] = datetime.now(timezone.utc).isoformat()
        row = {}
        string_fields = {"t_wall_utc", *STRING_TOPICS, "output_drive_mode"}
        for field in self.fields:
            row[field] = str(self.latest.get(field, "")) if field in string_fields else self._clean_float(self.latest.get(field))
        self.writer.writerow(row)
        self.rows_since_flush += 1
        if self.rows_since_flush >= self.flush_every_rows:
            self.csv_file.flush()
            self.rows_since_flush = 0
```

### L183 関数 `SolarLoggerNode.destroy_node`

- 定義: `destroy_node(self)`
- 行範囲: L183-L189
- 所属: `SolarLoggerNode`
- このブロックが直接呼ぶ主な関数/メソッド: `close`, `destroy_node`, `flush`, `super`
- 読み取る主なインスタンス属性: `self.csv_file`
- 制御構造の規模: 条件分岐 0、ループ 0、try 1
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 例外処理を伴う try ブロックを実行する。
  2.   self.csv_file.flush(...) を実行する。
  3.   self.csv_file.close(...) を実行する。
  4.   Exceptionを捕捉した場合:
  5.   Pass 文を実行する。
  6. super().destroy_node(...) を実行する。

代表コード断片:

```python
    def destroy_node(self):
        try:
            self.csv_file.flush()
            self.csv_file.close()
        except Exception:
            pass
        super().destroy_node()
```

### L192 関数 `main`

- 定義: `main()`
- 行範囲: L192-L199
- このブロックが直接呼ぶ主な関数/メソッド: `SolarLoggerNode`, `destroy_node`, `init`, `shutdown`, `spin`
- この呼出し内で代入する主なローカル名: `node`
- 制御構造の規模: 条件分岐 0、ループ 0、try 1
- この定義を読むためのPython構文:
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に SolarLoggerNode() の結果を代入する。
  3. 例外処理を伴う try ブロックを実行する。
  4.   rclpy.spin(...) を実行する。
  5.   成否にかかわらずfinallyで:
  6.   node.destroy_node(...) を実行する。
  7.   rclpy.shutdown(...) を実行する。

代表コード断片:

```python
def main():
    rclpy.init()
    node = SolarLoggerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
```


## パラメータ

- L88: `log_dir` (default: `outputs/logs`)
- L89: `file_prefix` (default: `solar_live`)
- L90: `log_rate_hz` (default: `2.0`)
- L91: `flush_every_rows` (default: `1`)
- L92: `output_speed_topic` (default: `/vehicle/speed_cmd_kmh`)
- L93: `output_drive_mode_topic` (default: `/vehicle/drive_mode_cmd`)

## ROS topic I/O

- Subscription L115: `topic` -> `self._set_float(field)`
- Subscription L117: `topic` -> `self._set_float(field)`
- Subscription L119: `topic` -> `self._set_string(field)`
- Subscription L121: `topic` -> `self._set_array(fields)`
- Subscription L126: `output_speed_topic` -> `self._set_float('output_speed_cmd_kmh')`
- Subscription L129: `output_mode_topic` -> `self._set_string('output_drive_mode')`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
