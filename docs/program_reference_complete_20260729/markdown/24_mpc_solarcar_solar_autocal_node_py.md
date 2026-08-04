# 24. live 自動校正ノード

- ファイル: `mpc_solarcar/solar_autocal_node.py`
- ソースSHA-256: `a98336e789670e85549bcedbb19c1a90b49d293dba6f193a6d91c053ef9abc51`
- 種別: `Python`
- 区分: `runtime node`

## 役割

観測 solar/pack power と planner 予測との差から solar_gain、drive_power_gain、aux_power_w を推定 publish する。

## 起動文脈

- 起動文脈: 運用中に mpc_node の係数を微調整する補助ノード。
- 呼び出し元: `mpc_solarcar/live_launch.py`
- 次に読むべきファイル: `mpc_solarcar/solar_autocal_logic.py`, `mpc_solarcar/mpc_node.py`

## 主要ポイント

- /calib/* topic を publish する。
- mpc_node がそれを購読して内部 gain を更新する。

## 主要構造

主要クラスは SolarAutocalNode。 主要関数は main。 ROS パラメータ宣言は 14 件。 ROS I/O は publisher 4 件、subscription 6 件。

## ファイルを上から読んだときの定義順

- L13: 関数 _clamp を定義する。
- L17: クラス SolarAutocalNode を定義する。
- L153: 関数 main を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `import math`
  - Python標準のスカラー数値関数と定数を使うため。実際に参照する名前と行は使用位置欄で確認する。 このファイル内での主な使用位置は L50, L51, L52, L53, L54, L55, L69, L70, ...。
- L5: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L154, L156, L158。
- L6: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L17。
- L8: `from std_msgs.msg import Float32, Float32MultiArray, String`
  - Float32、Bool、Stringなどの標準ROS messageで値をpublishまたはsubscribeするため。 このファイル内での主な使用位置は L57, L58, L59, L60, L62, L63, L64, L65, ...。
- L10: `from .solar_autocal_logic import daytime_stationary_aux_estimate`
  - 自動校正ロジック関数群 から daytime_stationary_aux_estimate を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_autocal_logic.py。 このファイル内での主な使用位置は L110。

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

### L13 関数 `_clamp`

- 定義: `_clamp(value: float, lo: float, hi: float) -> float`
- 行範囲: L13-L14
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `max`, `min`
- 戻り値の要点: `max(float(lo), min(float(hi), float(value)))`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. max(float(lo), min(float(hi), float(value))) を返す。

代表コード断片:

```python
def _clamp(value: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(value)))
```

### L17 クラス `SolarAutocalNode`

- 定義: `SolarAutocalNode(bases=Node)`
- 行範囲: L17-L150
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - class文は新しい型を定義する。丸括弧内は継承する基底クラスである。
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _on_speed を定義する。
  3. 関数 _on_current を定義する。
  4. 関数 _on_voltage を定義する。
  5. 関数 _on_solar を定義する。
  6. 関数 _on_env を定義する。
  7. 関数 _on_metrics を定義する。
  8. 関数 _ema を定義する。
  9. 関数 _step を定義する。

代表コード断片:

```python
class SolarAutocalNode(Node):
    def __init__(self) -> None:
        super().__init__("solar_autocal_node")
        self.declare_parameter("publish_period_sec", 30.0)
        self.declare_parameter("stationary_speed_kmh", 2.0)
        self.declare_parameter("drive_speed_kmh", 25.0)
        self.declare_parameter("day_ghi_threshold", 150.0)
        self.declare_parameter("alpha", 0.2)
        self.declare_parameter("solar_gain_init", 1.0)
        self.declare_parameter("drive_power_gain_init", 1.0)
        self.declare_parameter("aux_power_w_init", 8.0)
        self.declare_parameter("solar_gain_min", 0.5)
        self.declare_parameter("solar_gain_max", 1.5)
        self.declare_parameter("drive_power_gain_min", 0.7)
        self.declare_parameter("drive_power_gain_max", 1.4)
        self.declare_parameter("aux_power_w_min", 0.0)
        self.declare_parameter("aux_power_w_max", 300.0)

        self.period = max(1.0, float(self.get_parameter("publish_period_sec").value))
        self.stationary_speed = float(self.get_parameter("stationary_speed_kmh").value)
        self.drive_speed = float(self.get_parameter("drive_speed_kmh").value)
        self.day_ghi = float(self.get_parameter("day_ghi_threshold").value)
        self.alpha = _clamp(float(self.get_parameter("alpha").value), 0.01, 1.0)
        self.solar_gain = float(self.get_parameter("solar_gain_init").value)
        self.drive_gain = float(self.get_parameter("drive_power_gain_init").value)
        self.aux_power = float(self.get_parameter("aux_power_w_init").value)
        self.solar_gain_min = float(self.get_parameter("solar_gain_min").value)
        self.solar_gain_max = float(self.get_parameter("solar_gain_max").value)
        self.drive_gain_min = float(self.get_parameter("drive_power_gain_min").value)
        self.drive_gain_max = float(self.get_parameter("drive_power_gain_max").value)
        self.aux_min = float(self.get_parameter("aux_power_w_min").value)
        self.aux_max = float(self.get_parameter("aux_power_w_max").value)

        self.speed_kmh = math.nan
        self.pack_power_w = math.nan
...
```

### L18 関数 `SolarAutocalNode.__init__`

- 定義: `__init__(self) -> None`
- 行範囲: L18-L72
- 所属: `SolarAutocalNode`
- このブロックが直接呼ぶ主な関数/メソッド: `__init__`, `_clamp`, `create_publisher`, `create_subscription`, `create_timer`, `declare_parameter`, `float`, `get_logger`, `get_parameter`, `info`, `max`, `super`
- 読み取る主なインスタンス属性: `self._on_current`, `self._on_env`, `self._on_metrics`, `self._on_solar`, `self._on_speed`, `self._on_voltage`, `self._step`, `self.create_publisher`, `self.create_subscription`, `self.create_timer`, `self.declare_parameter`, `self.get_logger`, `self.get_parameter`, `self.period`
- 更新する主なインスタンス属性: `self._latest_current_a`, `self._latest_voltage_v`, `self.alpha`, `self.aux_max`, `self.aux_min`, `self.aux_power`, `self.day_ghi`, `self.drive_gain`, `self.drive_gain_max`, `self.drive_gain_min`, `self.drive_speed`, `self.ghi`, `self.pack_power_w`, `self.period`, `self.pred_pack_w`, `self.pred_solar_w`, `self.pub_aux`, `self.pub_drive`, `self.pub_solar`, `self.pub_status`, `self.solar_gain`, `self.solar_gain_max`, `self.solar_gain_min`, `self.solar_obs_w`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
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
  13. self.declare_parameter(...) を実行する。
  14. self.declare_parameter(...) を実行する。
  15. self.declare_parameter(...) を実行する。
  16. self.period に max(1.0, float(self.get_parameter('publish_period_sec').value)) の結果を代入する。
  17. self.stationary_speed に float(self.get_parameter('stationary_speed_kmh').value) の結果を代入する。
  18. self.drive_speed に float(self.get_parameter('drive_speed_kmh').value) の結果を代入する。
  19. self.day_ghi に float(self.get_parameter('day_ghi_threshold').value) の結果を代入する。
  20. self.alpha に _clamp(float(self.get_parameter('alpha').value), 0.01, 1.0) の結果を代入する。
  21. self.solar_gain に float(self.get_parameter('solar_gain_init').value) の結果を代入する。
  22. self.drive_gain に float(self.get_parameter('drive_power_gain_init').value) の結果を代入する。
  23. self.aux_power に float(self.get_parameter('aux_power_w_init').value) の結果を代入する。
  24. self.solar_gain_min に float(self.get_parameter('solar_gain_min').value) の結果を代入する。
  25. self.solar_gain_max に float(self.get_parameter('solar_gain_max').value) の結果を代入する。
  26. self.drive_gain_min に float(self.get_parameter('drive_power_gain_min').value) の結果を代入する。
  27. self.drive_gain_max に float(self.get_parameter('drive_power_gain_max').value) の結果を代入する。
  28. self.aux_min に float(self.get_parameter('aux_power_w_min').value) の結果を代入する。
  29. self.aux_max に float(self.get_parameter('aux_power_w_max').value) の結果を代入する。
  30. self.speed_kmh に math.nan の結果を代入する。
  31. self.pack_power_w に math.nan の結果を代入する。
  32. self.solar_obs_w に math.nan の結果を代入する。
  33. self.ghi に math.nan の結果を代入する。
  34. self.pred_solar_w に math.nan の結果を代入する。
  35. self.pred_pack_w に math.nan の結果を代入する。
  36. self.pub_solar に self.create_publisher(Float32, '/calib/solar_gain', 10) の結果を代入する。
  37. self.pub_drive に self.create_publisher(Float32, '/calib/drive_power_gain', 10) の結果を代入する。
  38. self.pub_aux に self.create_publisher(Float32, '/calib/aux_power_w', 10) の結果を代入する。
  39. self.pub_status に self.create_publisher(String, '/calib/status', 10) の結果を代入する。
  40. self.create_subscription(...) を実行する。
  41. self.create_subscription(...) を実行する。
  42. self.create_subscription(...) を実行する。
  43. self.create_subscription(...) を実行する。
  44. self.create_subscription(...) を実行する。
  45. self.create_subscription(...) を実行する。
  46. self._latest_current_a に math.nan の結果を代入する。
  47. self._latest_voltage_v に math.nan の結果を代入する。
  48. self.timer に self.create_timer(self.period, self._step) の結果を代入する。
  49. self.get_logger().info(...) を実行する。

代表コード断片:

```python
    def __init__(self) -> None:
        super().__init__("solar_autocal_node")
        self.declare_parameter("publish_period_sec", 30.0)
        self.declare_parameter("stationary_speed_kmh", 2.0)
        self.declare_parameter("drive_speed_kmh", 25.0)
        self.declare_parameter("day_ghi_threshold", 150.0)
        self.declare_parameter("alpha", 0.2)
        self.declare_parameter("solar_gain_init", 1.0)
        self.declare_parameter("drive_power_gain_init", 1.0)
        self.declare_parameter("aux_power_w_init", 8.0)
        self.declare_parameter("solar_gain_min", 0.5)
        self.declare_parameter("solar_gain_max", 1.5)
        self.declare_parameter("drive_power_gain_min", 0.7)
        self.declare_parameter("drive_power_gain_max", 1.4)
        self.declare_parameter("aux_power_w_min", 0.0)
        self.declare_parameter("aux_power_w_max", 300.0)

        self.period = max(1.0, float(self.get_parameter("publish_period_sec").value))
        self.stationary_speed = float(self.get_parameter("stationary_speed_kmh").value)
        self.drive_speed = float(self.get_parameter("drive_speed_kmh").value)
        self.day_ghi = float(self.get_parameter("day_ghi_threshold").value)
        self.alpha = _clamp(float(self.get_parameter("alpha").value), 0.01, 1.0)
        self.solar_gain = float(self.get_parameter("solar_gain_init").value)
        self.drive_gain = float(self.get_parameter("drive_power_gain_init").value)
        self.aux_power = float(self.get_parameter("aux_power_w_init").value)
        self.solar_gain_min = float(self.get_parameter("solar_gain_min").value)
        self.solar_gain_max = float(self.get_parameter("solar_gain_max").value)
        self.drive_gain_min = float(self.get_parameter("drive_power_gain_min").value)
        self.drive_gain_max = float(self.get_parameter("drive_power_gain_max").value)
        self.aux_min = float(self.get_parameter("aux_power_w_min").value)
        self.aux_max = float(self.get_parameter("aux_power_w_max").value)

        self.speed_kmh = math.nan
        self.pack_power_w = math.nan
        self.solar_obs_w = math.nan
...
```

### L74 関数 `SolarAutocalNode._on_speed`

- 定義: `_on_speed(self, msg: Float32) -> None`
- 行範囲: L74-L75
- 所属: `SolarAutocalNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`
- 更新する主なインスタンス属性: `self.speed_kmh`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. self.speed_kmh に float(msg.data) の結果を代入する。

代表コード断片:

```python
    def _on_speed(self, msg: Float32) -> None:
        self.speed_kmh = float(msg.data)
```

### L77 関数 `SolarAutocalNode._on_current`

- 定義: `_on_current(self, msg: Float32) -> None`
- 行範囲: L77-L80
- 所属: `SolarAutocalNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `isfinite`
- 読み取る主なインスタンス属性: `self._latest_current_a`, `self._latest_voltage_v`
- 更新する主なインスタンス属性: `self._latest_current_a`, `self.pack_power_w`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. self._latest_current_a に float(msg.data) の結果を代入する。
  2. 条件 math.isfinite(self._latest_voltage_v) を判定し、真なら内部処理を行う。
  3.   self.pack_power_w に self._latest_current_a * self._latest_voltage_v の結果を代入する。

代表コード断片:

```python
    def _on_current(self, msg: Float32) -> None:
        self._latest_current_a = float(msg.data)
        if math.isfinite(self._latest_voltage_v):
            self.pack_power_w = self._latest_current_a * self._latest_voltage_v
```

### L82 関数 `SolarAutocalNode._on_voltage`

- 定義: `_on_voltage(self, msg: Float32) -> None`
- 行範囲: L82-L85
- 所属: `SolarAutocalNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `isfinite`
- 読み取る主なインスタンス属性: `self._latest_current_a`, `self._latest_voltage_v`
- 更新する主なインスタンス属性: `self._latest_voltage_v`, `self.pack_power_w`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. self._latest_voltage_v に float(msg.data) の結果を代入する。
  2. 条件 math.isfinite(self._latest_current_a) を判定し、真なら内部処理を行う。
  3.   self.pack_power_w に self._latest_current_a * self._latest_voltage_v の結果を代入する。

代表コード断片:

```python
    def _on_voltage(self, msg: Float32) -> None:
        self._latest_voltage_v = float(msg.data)
        if math.isfinite(self._latest_current_a):
            self.pack_power_w = self._latest_current_a * self._latest_voltage_v
```

### L87 関数 `SolarAutocalNode._on_solar`

- 定義: `_on_solar(self, msg: Float32) -> None`
- 行範囲: L87-L88
- 所属: `SolarAutocalNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`
- 更新する主なインスタンス属性: `self.solar_obs_w`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. self.solar_obs_w に float(msg.data) の結果を代入する。

代表コード断片:

```python
    def _on_solar(self, msg: Float32) -> None:
        self.solar_obs_w = float(msg.data)
```

### L90 関数 `SolarAutocalNode._on_env`

- 定義: `_on_env(self, msg: Float32MultiArray) -> None`
- 行範囲: L90-L93
- 所属: `SolarAutocalNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `len`, `list`
- この呼出し内で代入する主なローカル名: `data`
- 更新する主なインスタンス属性: `self.ghi`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. data に list(msg.data) の結果を代入する。
  2. 条件 len(data) >= 1 を判定し、真なら内部処理を行う。
  3.   self.ghi に float(data[0]) の結果を代入する。

代表コード断片:

```python
    def _on_env(self, msg: Float32MultiArray) -> None:
        data = list(msg.data)
        if len(data) >= 1:
            self.ghi = float(data[0])
```

### L95 関数 `SolarAutocalNode._on_metrics`

- 定義: `_on_metrics(self, msg: Float32MultiArray) -> None`
- 行範囲: L95-L100
- 所属: `SolarAutocalNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `len`, `list`
- この呼出し内で代入する主なローカル名: `data`
- 更新する主なインスタンス属性: `self.pred_pack_w`, `self.pred_solar_w`
- 制御構造の規模: 条件分岐 2、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. data に list(msg.data) の結果を代入する。
  2. 条件 len(data) >= 6 を判定し、真なら内部処理を行う。
  3.   self.pred_solar_w に float(data[5]) の結果を代入する。
  4. 条件 len(data) >= 9 を判定し、真なら内部処理を行う。
  5.   self.pred_pack_w に float(data[8]) の結果を代入する。

代表コード断片:

```python
    def _on_metrics(self, msg: Float32MultiArray) -> None:
        data = list(msg.data)
        if len(data) >= 6:
            self.pred_solar_w = float(data[5])
        if len(data) >= 9:
            self.pred_pack_w = float(data[8])
```

### L102 関数 `SolarAutocalNode._ema`

- 定義: `_ema(self, current: float, estimate: float, lo: float, hi: float) -> float`
- 行範囲: L102-L104
- 所属: `SolarAutocalNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_clamp`, `float`
- 戻り値の要点: `_clamp(blended, lo, hi)`
- この呼出し内で代入する主なローカル名: `blended`
- 読み取る主なインスタンス属性: `self.alpha`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. blended に (1.0 - self.alpha) * float(current) + self.alpha * float(estimate) の結果を代入する。
  2. _clamp(blended, lo, hi) を返す。

代表コード断片:

```python
    def _ema(self, current: float, estimate: float, lo: float, hi: float) -> float:
        blended = (1.0 - self.alpha) * float(current) + self.alpha * float(estimate)
        return _clamp(blended, lo, hi)
```

### L106 関数 `SolarAutocalNode._step`

- 定義: `_step(self) -> None`
- 行範囲: L106-L150
- 所属: `SolarAutocalNode`
- このブロックが直接呼ぶ主な関数/メソッド: `Float32`, `String`, `_ema`, `abs`, `daytime_stationary_aux_estimate`, `float`, `isfinite`, `max`, `publish`
- この呼出し内で代入する主なローカル名: `aux_estimate`, `gain_est`, `status`
- 読み取る主なインスタンス属性: `self._ema`, `self.aux_max`, `self.aux_min`, `self.aux_power`, `self.day_ghi`, `self.drive_gain`, `self.drive_gain_max`, `self.drive_gain_min`, `self.drive_speed`, `self.ghi`, `self.pack_power_w`, `self.pred_pack_w`, `self.pred_solar_w`, `self.pub_aux`, `self.pub_drive`, `self.pub_solar`, `self.pub_status`, `self.solar_gain`, `self.solar_gain_max`, `self.solar_gain_min`, `self.solar_obs_w`, `self.speed_kmh`, `self.stationary_speed`
- 更新する主なインスタンス属性: `self.aux_power`, `self.drive_gain`, `self.solar_gain`
- 制御構造の規模: 条件分岐 3、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. aux_estimate に daytime_stationary_aux_estimate(ghi_wm2=self.ghi, day_ghi_threshold_wm2=self.day_ghi, speed_kmh=self.speed_kmh, stationary_speed_kmh=self.stationary_speed, pack_power_w=self.pack_power_w, solar_power_w=self.solar_obs_w) の結果を代入する。
  2. 条件 aux_estimate is not None を判定し、真なら内部処理を行う。
  3.   self.aux_power に self._ema(self.aux_power, aux_estimate, self.aux_min, self.aux_max) の結果を代入する。
  4. 条件 math.isfinite(self.ghi) and self.ghi >= self.day_ghi and math.isfinite(self.solar_obs_w) and math.isfinite(self.pred_solar_w) and (abs(self.pred_solar_w) >= 20.0) を判定し、真なら内部処理を行う。
  5.   gain_est に self.solar_obs_w / self.pred_solar_w の結果を代入する。
  6.   self.solar_gain に self._ema(self.solar_gain, gain_est, self.solar_gain_min, self.solar_gain_max) の結果を代入する。
  7. 条件 math.isfinite(self.speed_kmh) and self.speed_kmh >= self.drive_speed and math.isfinite(self.pack_power_w) and math.isfinite(self.pred_pack_w) and (abs(self.pred_pack_w) >= 50.0) and (self.pack_power_w > 0.0) を判定し、真なら内部処理を行う。
  8.   gain_est に self.pack_power_w / max(1.0, self.pred_pack_w) の結果を代入する。
  9.   self.drive_gain に self._ema(self.drive_gain, gain_est, self.drive_gain_min, self.drive_gain_max) の結果を代入する。
  10. self.pub_solar.publish(...) を実行する。
  11. self.pub_drive.publish(...) を実行する。
  12. self.pub_aux.publish(...) を実行する。
  13. status に f'solar_gain={self.solar_gain:.3f} drive_power_gain={self.drive_gain:.3f} aux_power_w={self.aux_power:.1f}' の結果を代入する。
  14. self.pub_status.publish(...) を実行する。

代表コード断片:

```python
    def _step(self) -> None:
        # The team switches auxiliaries off at night, so a night stationary
        # sample is not an estimate of the daytime auxiliary load.  At a
        # daytime stop P_pack = P_aux - P_pv, hence P_aux = P_pack + P_pv.
        aux_estimate = daytime_stationary_aux_estimate(
            ghi_wm2=self.ghi,
            day_ghi_threshold_wm2=self.day_ghi,
            speed_kmh=self.speed_kmh,
            stationary_speed_kmh=self.stationary_speed,
            pack_power_w=self.pack_power_w,
            solar_power_w=self.solar_obs_w,
        )
        if aux_estimate is not None:
            self.aux_power = self._ema(self.aux_power, aux_estimate, self.aux_min, self.aux_max)

        if (
            math.isfinite(self.ghi)
            and self.ghi >= self.day_ghi
            and math.isfinite(self.solar_obs_w)
            and math.isfinite(self.pred_solar_w)
            and abs(self.pred_solar_w) >= 20.0
        ):
            gain_est = self.solar_obs_w / self.pred_solar_w
            self.solar_gain = self._ema(self.solar_gain, gain_est, self.solar_gain_min, self.solar_gain_max)

        if (
            math.isfinite(self.speed_kmh)
            and self.speed_kmh >= self.drive_speed
            and math.isfinite(self.pack_power_w)
            and math.isfinite(self.pred_pack_w)
            and abs(self.pred_pack_w) >= 50.0
            and self.pack_power_w > 0.0
        ):
            gain_est = self.pack_power_w / max(1.0, self.pred_pack_w)
            self.drive_gain = self._ema(self.drive_gain, gain_est, self.drive_gain_min, self.drive_gain_max)
...
```

### L153 関数 `main`

- 定義: `main() -> None`
- 行範囲: L153-L158
- このブロックが直接呼ぶ主な関数/メソッド: `SolarAutocalNode`, `destroy_node`, `init`, `shutdown`, `spin`
- この呼出し内で代入する主なローカル名: `node`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に SolarAutocalNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。

代表コード断片:

```python
def main() -> None:
    rclpy.init()
    node = SolarAutocalNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
```


## パラメータ

- L20: `publish_period_sec` (default: `30.0`)
- L21: `stationary_speed_kmh` (default: `2.0`)
- L22: `drive_speed_kmh` (default: `25.0`)
- L23: `day_ghi_threshold` (default: `150.0`)
- L24: `alpha` (default: `0.2`)
- L25: `solar_gain_init` (default: `1.0`)
- L26: `drive_power_gain_init` (default: `1.0`)
- L27: `aux_power_w_init` (default: `8.0`)
- L28: `solar_gain_min` (default: `0.5`)
- L29: `solar_gain_max` (default: `1.5`)
- L30: `drive_power_gain_min` (default: `0.7`)
- L31: `drive_power_gain_max` (default: `1.4`)
- L32: `aux_power_w_min` (default: `0.0`)
- L33: `aux_power_w_max` (default: `300.0`)

## ROS topic I/O

- Publisher L57: `/calib/solar_gain`
- Publisher L58: `/calib/drive_power_gain`
- Publisher L59: `/calib/aux_power_w`
- Publisher L60: `/calib/status`
- Subscription L62: `/vehicle/speed_kmh` -> `self._on_speed`
- Subscription L63: `/vehicle/batt_current_a` -> `self._on_current`
- Subscription L64: `/vehicle/batt_voltage_v` -> `self._on_voltage`
- Subscription L65: `/vehicle/solar_power_w` -> `self._on_solar`
- Subscription L66: `/planner/env` -> `self._on_env`
- Subscription L67: `/planner/metrics` -> `self._on_metrics`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
