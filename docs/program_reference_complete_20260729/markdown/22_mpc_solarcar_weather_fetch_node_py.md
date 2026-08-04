# 22. live forecast 取得ノード

- ファイル: `mpc_solarcar/weather_fetch_node.py`
- ソースSHA-256: `bef650eab4797b7c832c841ba7eaa271ab3cccec171f9b270c69172f9835bb50`
- 種別: `Python`
- 区分: `runtime node`

## 役割

chase GPS または fallback 座標から Open-Meteo forecast を取得し、planner が読む CSV を更新する。

## 起動文脈

- 起動文脈: live 系の forecast 更新入口。
- 呼び出し元: `mpc_solarcar/live_launch.py`
- 次に読むべきファイル: `mpc_solarcar/weather_utils.py`, `mpc_solarcar/wind_correction_node.py`

## 主要ポイント

- raw forecast CSV を定期更新する。
- planner 自体は topic ではなく forecast CSV を読む。

## 主要構造

主要クラスは WeatherFetchNode。 主要関数は main。 ROS パラメータ宣言は 11 件。 ROS I/O は publisher 1 件、subscription 1 件。

## ファイルを上から読んだときの定義順

- L15: クラス WeatherFetchNode を定義する。
- L138: 関数 main を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L85, L86。
- L5: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L39, L40, L44, L48, L52, L56, L60, L69, ...。
- L6: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L15。
- L8: `from sensor_msgs.msg import NavSatFix`
  - GPS 緯度経度高度を ROS topic でやり取りするため。 このファイル内での主な使用位置は L99, L104。
- L9: `from std_msgs.msg import String`
  - Float32、Bool、Stringなどの標準ROS messageで値をpublishまたはsubscribeするため。 このファイル内での主な使用位置は L98, L130, L134。
- L11: `from .solar_profile import get_path, get_section, load_profile`
  - profile YAML 読込と検証 から get_path, get_section, load_profile を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L32, L33, L34, L35, L39。
- L12: `from .weather_utils import fetch_openmeteo_forecast, write_forecast_csv`
  - weather_utils.py から fetch_openmeteo_forecast, write_forecast_csv を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/weather_utils.py。 このファイル内での主な使用位置は L115, L123, L128。

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

### freshness、filter、guard、fallback、fail-safe

分散システムでは最後に受け取った値が現在も有効とは限らない。受信時刻とtimeoutからfreshnessを判定し、stale値を計画状態へ無条件に同期しない。

filterはnoiseと一時的な飛び値を抑えるが、遅れを生む。slew limitは指令変化率を制限する。安全guardはsolverのcost罰則とは別に、現在出力へ強制制約を適用する最後の防波堤である。

fallbackは失敗時の代替動作を事前に決める設計である。前回計画保持、物理に基づく決定論的入力、停止、低速制限などから、故障modeごとに選ぶ。fallback発生はstatusとlogへ残し、正常解と区別する。

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

### L15 クラス `WeatherFetchNode`

- 定義: `WeatherFetchNode(bases=Node)`
- 行範囲: L15-L135
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - class文は新しい型を定義する。丸括弧内は継承する基底クラスである。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _on_gps を定義する。
  3. 関数 _fetch_once を定義する。

代表コード断片:

```python
class WeatherFetchNode(Node):
    def __init__(self) -> None:
        super().__init__("weather_fetch_node")
        self.declare_parameter("profile_yaml", "")
        self.declare_parameter("output_csv", "")
        self.declare_parameter("raw_forecast_csv", "")
        self.declare_parameter("gps_topic", "/chase/gps")
        self.declare_parameter("fetch_period_sec", 3600.0)
        self.declare_parameter("forecast_days", 3)
        self.declare_parameter("step_minutes", 10)
        self.declare_parameter("timezone_name", "Australia/Darwin")
        self.declare_parameter("fallback_latitude", -12.4634)
        self.declare_parameter("fallback_longitude", 130.8456)
        self.declare_parameter("tcell_gain", 0.03)

        profile_yaml = str(self.get_parameter("profile_yaml").value or "").strip()
        if profile_yaml:
            profile_path, cfg = load_profile(profile_yaml)
            runtime_cfg = get_section(cfg, "runtime")
            live_cfg = get_section(cfg, "live")
            weather_cfg = get_section(live_cfg, "weather")
            if not self.get_parameter("output_csv").value:
                self.set_parameters(
                    [
                        rclpy.parameter.Parameter("output_csv", value=get_path(cfg, profile_path, "forecast_csv")),
                        rclpy.parameter.Parameter(
                            "raw_forecast_csv",
                            value=str(weather_cfg.get("raw_forecast_csv", "") or ""),
                        ),
                        rclpy.parameter.Parameter(
                            "gps_topic",
                            value=str(weather_cfg.get("gps_topic", "/chase/gps")),
                        ),
                        rclpy.parameter.Parameter(
                            "fetch_period_sec",
...
```

### L16 関数 `WeatherFetchNode.__init__`

- 定義: `__init__(self) -> None`
- 行範囲: L16-L102
- 所属: `WeatherFetchNode`
- このブロックが直接呼ぶ主な関数/メソッド: `Parameter`, `Path`, `__init__`, `_fetch_once`, `create_publisher`, `create_subscription`, `create_timer`, `declare_parameter`, `expanduser`, `float`, `get`, `get_logger`
- この呼出し内で代入する主なローカル名: `cfg`, `live_cfg`, `profile_path`, `profile_yaml`, `raw_out`, `runtime_cfg`, `weather_cfg`
- 読み取る主なインスタンス属性: `self._fetch_once`, `self._on_gps`, `self.create_publisher`, `self.create_subscription`, `self.create_timer`, `self.declare_parameter`, `self.fetch_period_sec`, `self.get_logger`, `self.get_parameter`, `self.gps_topic`, `self.output_csv`, `self.set_parameters`
- 更新する主なインスタンス属性: `self.fallback_lat`, `self.fallback_lon`, `self.fetch_period_sec`, `self.forecast_days`, `self.gps_topic`, `self.latest_lat`, `self.latest_lon`, `self.output_csv`, `self.pub_status`, `self.raw_forecast_csv`, `self.step_minutes`, `self.tcell_gain`, `self.timer`, `self.timezone_name`
- 制御構造の規模: 条件分岐 2、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. super().__init__(...) を実行する。
  2. self.declare_parameter(...) を実行する。
  3. self.declare_parameter(...) を実行する。
  4. self.declare_parameter(...) を実行する。
  5. self.declare_parameter(...) を実行する。
  6. self.declare_parameter(...) を実行する。
  7. self.declare_parameter(...) を実行する。
  8. self.declare_parameter(...) を実行する。
  9. self.declare_parameter(...) を実行する。
  10. self.declare_parameter(...) を実行する。
  11. self.declare_parameter(...) を実行する。
  12. self.declare_parameter(...) を実行する。
  13. profile_yaml に str(self.get_parameter('profile_yaml').value or '').strip() の結果を代入する。
  14. 条件 profile_yaml を判定し、真なら内部処理を行う。
  15.   (profile_path, cfg) に load_profile(profile_yaml) の結果を代入する。
  16.   runtime_cfg に get_section(cfg, 'runtime') の結果を代入する。
  17.   live_cfg に get_section(cfg, 'live') の結果を代入する。
  18.   weather_cfg に get_section(live_cfg, 'weather') の結果を代入する。
  19.   条件 not self.get_parameter('output_csv').value を判定し、真なら内部処理を行う。
  20.     self.set_parameters(...) を実行する。
  21. raw_out に str(self.get_parameter('raw_forecast_csv').value or '').strip() の結果を代入する。
  22. self.output_csv に Path(str(self.get_parameter('output_csv').value or '')).expanduser() の結果を代入する。
  23. self.raw_forecast_csv に Path(raw_out).expanduser() if raw_out else None の結果を代入する。
  24. self.gps_topic に str(self.get_parameter('gps_topic').value) の結果を代入する。
  25. self.fetch_period_sec に max(60.0, float(self.get_parameter('fetch_period_sec').value)) の結果を代入する。
  26. self.forecast_days に max(1, int(self.get_parameter('forecast_days').value)) の結果を代入する。
  27. self.step_minutes に max(1, int(self.get_parameter('step_minutes').value)) の結果を代入する。
  28. self.timezone_name に str(self.get_parameter('timezone_name').value or 'Australia/Darwin') の結果を代入する。
  29. self.fallback_lat に float(self.get_parameter('fallback_latitude').value) の結果を代入する。
  30. self.fallback_lon に float(self.get_parameter('fallback_longitude').value) の結果を代入する。
  31. self.tcell_gain に float(self.get_parameter('tcell_gain').value) の結果を代入する。
  32. self.latest_lat に None の結果を代入する。
  33. self.latest_lon に None の結果を代入する。
  34. self.pub_status に self.create_publisher(String, '/weather/fetch_status', 10) の結果を代入する。
  35. self.create_subscription(...) を実行する。
  36. self.timer に self.create_timer(self.fetch_period_sec, self._fetch_once) の結果を代入する。
  37. self.get_logger().info(...) を実行する。
  38. self._fetch_once(...) を実行する。

代表コード断片:

```python
    def __init__(self) -> None:
        super().__init__("weather_fetch_node")
        self.declare_parameter("profile_yaml", "")
        self.declare_parameter("output_csv", "")
        self.declare_parameter("raw_forecast_csv", "")
        self.declare_parameter("gps_topic", "/chase/gps")
        self.declare_parameter("fetch_period_sec", 3600.0)
        self.declare_parameter("forecast_days", 3)
        self.declare_parameter("step_minutes", 10)
        self.declare_parameter("timezone_name", "Australia/Darwin")
        self.declare_parameter("fallback_latitude", -12.4634)
        self.declare_parameter("fallback_longitude", 130.8456)
        self.declare_parameter("tcell_gain", 0.03)

        profile_yaml = str(self.get_parameter("profile_yaml").value or "").strip()
        if profile_yaml:
            profile_path, cfg = load_profile(profile_yaml)
            runtime_cfg = get_section(cfg, "runtime")
            live_cfg = get_section(cfg, "live")
            weather_cfg = get_section(live_cfg, "weather")
            if not self.get_parameter("output_csv").value:
                self.set_parameters(
                    [
                        rclpy.parameter.Parameter("output_csv", value=get_path(cfg, profile_path, "forecast_csv")),
                        rclpy.parameter.Parameter(
                            "raw_forecast_csv",
                            value=str(weather_cfg.get("raw_forecast_csv", "") or ""),
                        ),
                        rclpy.parameter.Parameter(
                            "gps_topic",
                            value=str(weather_cfg.get("gps_topic", "/chase/gps")),
                        ),
                        rclpy.parameter.Parameter(
                            "fetch_period_sec",
                            value=float(weather_cfg.get("fetch_period_sec", 3600.0)),
...
```

### L104 関数 `WeatherFetchNode._on_gps`

- 定義: `_on_gps(self, msg: NavSatFix) -> None`
- 行範囲: L104-L109
- 所属: `WeatherFetchNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`
- 更新する主なインスタンス属性: `self.latest_lat`, `self.latest_lon`
- 制御構造の規模: 条件分岐 0、ループ 0、try 1
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 例外処理を伴う try ブロックを実行する。
  2.   self.latest_lat に float(msg.latitude) の結果を代入する。
  3.   self.latest_lon に float(msg.longitude) の結果を代入する。
  4.   Exceptionを捕捉した場合:
  5.    を返す。

代表コード断片:

```python
    def _on_gps(self, msg: NavSatFix) -> None:
        try:
            self.latest_lat = float(msg.latitude)
            self.latest_lon = float(msg.longitude)
        except Exception:
            return
```

### L111 関数 `WeatherFetchNode._fetch_once`

- 定義: `_fetch_once(self) -> None`
- 行範囲: L111-L135
- 所属: `WeatherFetchNode`
- このブロックが直接呼ぶ主な関数/メソッド: `String`, `error`, `fetch_openmeteo_forecast`, `get_logger`, `info`, `is_absolute`, `len`, `publish`, `resolve`, `write_forecast_csv`
- この呼出し内で代入する主なローカル名: `df`, `lat`, `lon`, `raw_path`, `status`
- 読み取る主なインスタンス属性: `self.fallback_lat`, `self.fallback_lon`, `self.forecast_days`, `self.get_logger`, `self.latest_lat`, `self.latest_lon`, `self.output_csv`, `self.pub_status`, `self.raw_forecast_csv`, `self.step_minutes`, `self.tcell_gain`, `self.timezone_name`
- 制御構造の規模: 条件分岐 2、ループ 0、try 1
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. lat に self.latest_lat if self.latest_lat is not None else self.fallback_lat の結果を代入する。
  2. lon に self.latest_lon if self.latest_lon is not None else self.fallback_lon の結果を代入する。
  3. 例外処理を伴う try ブロックを実行する。
  4.   df に fetch_openmeteo_forecast(lat, lon, timezone_name=self.timezone_name, forecast_days=self.forecast_days, step_minutes=self.step_minutes, tcell_gain=self.tcell_gain) の結果を代入する。
  5.   write_forecast_csv(...) を実行する。
  6.   条件 self.raw_forecast_csv を判定し、真なら内部処理を行う。
  7.     raw_path に self.raw_forecast_csv の結果を代入する。
  8.     条件 not raw_path.is_absolute() を判定し、真なら内部処理を行う。
  9.       raw_path に (self.output_csv.parent / raw_path).resolve() の結果を代入する。
  10.     write_forecast_csv(...) を実行する。
  11.   status に f'ok lat={lat:.5f} lon={lon:.5f} rows={len(df)} out={self.output_csv}' の結果を代入する。
  12.   self.pub_status.publish(...) を実行する。
  13.   self.get_logger().info(...) を実行する。
  14.   Exceptionを捕捉した場合:
  15.   status に f'error weather fetch failed: {exc}' の結果を代入する。
  16.   self.pub_status.publish(...) を実行する。
  17.   self.get_logger().error(...) を実行する。

代表コード断片:

```python
    def _fetch_once(self) -> None:
        lat = self.latest_lat if self.latest_lat is not None else self.fallback_lat
        lon = self.latest_lon if self.latest_lon is not None else self.fallback_lon
        try:
            df = fetch_openmeteo_forecast(
                lat,
                lon,
                timezone_name=self.timezone_name,
                forecast_days=self.forecast_days,
                step_minutes=self.step_minutes,
                tcell_gain=self.tcell_gain,
            )
            write_forecast_csv(df, self.output_csv)
            if self.raw_forecast_csv:
                raw_path = self.raw_forecast_csv
                if not raw_path.is_absolute():
                    raw_path = (self.output_csv.parent / raw_path).resolve()
                write_forecast_csv(df, raw_path)
            status = f"ok lat={lat:.5f} lon={lon:.5f} rows={len(df)} out={self.output_csv}"
            self.pub_status.publish(String(data=status))
            self.get_logger().info(status)
        except Exception as exc:
            status = f"error weather fetch failed: {exc}"
            self.pub_status.publish(String(data=status))
            self.get_logger().error(status)
```

### L138 関数 `main`

- 定義: `main() -> None`
- 行範囲: L138-L143
- このブロックが直接呼ぶ主な関数/メソッド: `WeatherFetchNode`, `destroy_node`, `init`, `shutdown`, `spin`
- この呼出し内で代入する主なローカル名: `node`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に WeatherFetchNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。

代表コード断片:

```python
def main() -> None:
    rclpy.init()
    node = WeatherFetchNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
```


## パラメータ

- L18: `profile_yaml`
- L19: `output_csv`
- L20: `raw_forecast_csv`
- L21: `gps_topic` (default: `/chase/gps`)
- L22: `fetch_period_sec` (default: `3600.0`)
- L23: `forecast_days` (default: `3`)
- L24: `step_minutes` (default: `10`)
- L25: `timezone_name` (default: `Australia/Darwin`)
- L26: `fallback_latitude` (default: `-12.4634`)
- L27: `fallback_longitude` (default: `130.8456`)
- L28: `tcell_gain` (default: `0.03`)

## ROS topic I/O

- Publisher L98: `/weather/fetch_status`
- Subscription L99: `self.gps_topic` -> `self._on_gps`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
