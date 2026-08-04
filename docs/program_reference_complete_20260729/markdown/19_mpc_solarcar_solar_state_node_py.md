# 19. sim 用 車体状態 publisher

- ファイル: `mpc_solarcar/solar_state_node.py`
- ソースSHA-256: `d9c72bcecf7b5d6f0594d4c9029ba3837a9f3b0222e47e693729d581d99e4024`
- 種別: `Python`
- 区分: `runtime node`

## 役割

sim モードで planner 指令速度から速度、距離、電池、PV、altitude を模擬 publish する。

## 起動文脈

- 起動文脈: simulation launch における擬似車両。
- 呼び出し元: `launch/solarcar_sim.launch.py`
- 次に読むべきファイル: `mpc_solarcar/model.py`, `mpc_solarcar/mpc_node.py`

## 主要ポイント

- SolarCarModel を直接生成する。
- /planner/speed_cmd を受けて /vehicle/* を出す。

## 主要構造

主要クラスは SolarStateNode。 主要関数は main。 ROS パラメータ宣言は 26 件。 ROS I/O は publisher 8 件、subscription 1 件。

## ファイルを上から読んだときの定義順

- L22: クラス SolarStateNode を定義する。
- L265: 関数 main を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `import math`
  - Python標準のスカラー数値関数と定数を使うため。実際に参照する名前と行は使用位置欄で確認する。 このファイル内での使用位置は少ないか、間接利用である。
- L4: `import time`
  - wall/monotonic time に基づく周期制御や freshness 判定を行うため。 このファイル内での使用位置は少ないか、間接利用である。
- L5: `from datetime import datetime, timedelta, timezone`
  - UTC 時刻や相対時間を扱うため。 このファイル内での主な使用位置は L118, L122, L183, L209。
- L7: `import numpy as np`
  - 数値配列、clip、補間、統計計算を行うため。 このファイル内での主な使用位置は L185, L186, L188, L240。
- L8: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L99, L105, L107。
- L9: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L59, L60, L61, L62, L63, L64, L65, L66, ...。
- L10: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L22。
- L12: `from std_msgs.msg import Float32`
  - Float32、Bool、Stringなどの標準ROS messageで値をpublishまたはsubscribeするため。 このファイル内での主な使用位置は L168, L169, L170, L171, L172, L173, L174, L175, ...。
- L14: `from .model import Params, SolarCarModel`
  - 車体物理・電気モデル本体 から Params, SolarCarModel を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/model.py。 このファイル内での主な使用位置は L128, L132。
- L15: `from .path_utils import resolve_path`
  - ROS share / 相対パス解決 から resolve_path を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/path_utils.py。 このファイル内での主な使用位置は L87, L95, L103, L129, L130, L131, L133, L134, ...。
- L16: `from .route_utils import interpolate_profile`
  - route_utils.py から interpolate_profile を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/route_utils.py。 このファイル内での主な使用位置は L195。
- L17: `from .schedule_utils import DriveSchedule`
  - schedule_utils.py から DriveSchedule を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/schedule_utils.py。 このファイル内での主な使用位置は L103。
- L18: `from .signal_utils import SmoothRateLimiter`
  - signal_utils.py から SmoothRateLimiter を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/signal_utils.py。 このファイル内での主な使用位置は L158。
- L19: `from .solar_profile import get_path, get_section, load_profile, require_csv_data_rows`
  - profile YAML 読込と検証 から get_path, get_section, load_profile, require_csv_data_rows を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L54, L55, L56, L59, L60, L61, L62, L63, ...。

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

### list、dict、deque、NumPy配列、pandas DataFrame

listは順序付き可変列、tupleは順序付きで通常変更しない列、dictはキーから値を引く対応表、dequeは両端追加・削除が効率的なキューである。どの構造を選ぶかはアクセス方法と更新方法で決まる。

NumPy配列は同種数値を連続的に扱い、要素ごとの演算、clip、補間、線形代数を簡潔に書く。shapeは各次元の要素数であり、速度系列なら通常`(N,)`、候補集団なら`(population, N)`となる。

pandas DataFrameは列名を持つ表である。CSV読込後は列型、欠損、単位、timezone、並び順、重複を明示的に処理しなければ、数値計算が動いても意味が誤る。

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

### 車両力学、電力収支、効率map

$$
F_{\mathrm{aero}}=\frac{1}{2}\rho C_dA(v+v_{\mathrm{wind}})^2,\quad F_{\mathrm{roll}}\approx mgC_{rr}\cos\theta,\quad F_{\mathrm{grade}}=mg\sin\theta
$$

車輪機械powerは概ね`P_mech = F_total * v + P_inertia`で、駆動時と回生時で異なる効率mapを通してDC側powerへ変換する。mapは速度・torqueなどを軸にした実測または同定tableであり、範囲外の補間・clip規則もモデルの一部である。

$$
P_{\mathrm{pack}}=P_{\mathrm{drive,dc}}-P_{\mathrm{regen,dc}}+P_{\mathrm{aux}}-P_{\mathrm{pv}}
$$

符号規約は必ずコードで確認する。本プロジェクトでは正のpack powerを放電側としてSoCを減らす処理が中心であり、発電と回生はpack負荷を下げる方向に働く。

### SoC、内部抵抗、端子電圧、温度、MHE

$$
V=V_{\mathrm{oc}}(z,T)-IR_{\mathrm{total}}(z,T,I),\qquad z_{k+1}=z_k-\frac{\eta(I,T)I\Delta t}{Q_{\mathrm{eff}}}
$$

SoCは直接完全には観測できないため、電流積算、OCV、端子電圧、温度、容量、効率を組み合わせる。内部抵抗はSoC、温度、電流方向で変わり、発熱と電圧制約の両方へ影響する。

MHEは有限時間窓の状態と観測誤差をまとめて最適化し、SoCや温度を推定する。古い測定や欠損値を同じ重みで使うと推定が壊れるため、timestamp freshnessと観測可用性を入口で確認する。

根拠資料:

- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)

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

### L22 クラス `SolarStateNode`

- 定義: `SolarStateNode(bases=Node)`
- 行範囲: L22-L262
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - class文は新しい型を定義する。丸括弧内は継承する基底クラスである。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 _on_speed_cmd を定義する。
  3. 関数 _forecast_row を定義する。
  4. 関数 _route_value を定義する。
  5. 関数 _step を定義する。

代表コード断片:

```python
class SolarStateNode(Node):
    def __init__(self) -> None:
        super().__init__("solar_state_node")
        self.declare_parameter("profile_yaml", "")
        self.declare_parameter("forecast_csv", "inputs/forecast_10min.csv")
        self.declare_parameter("route_profile_csv", "")
        self.declare_parameter("drive_schedule_yaml", "")
        self.declare_parameter("drive_eff_map", "")
        self.declare_parameter("regen_eff_map", "")
        self.declare_parameter("rint_map", "")
        self.declare_parameter("panel_eff_map", "")
        self.declare_parameter("mppt_eff_map", "")
        self.declare_parameter("drive_map_eco", "")
        self.declare_parameter("drive_map_power", "")
        self.declare_parameter("regen_map_eco", "")
        self.declare_parameter("regen_map_power", "")
        self.declare_parameter("ocv_soc_map", "")
        self.declare_parameter("params_yaml", "")
        self.declare_parameter("forecast_time_mode", "auto")
        self.declare_parameter("forecast_time_tz", "UTC")
        self.declare_parameter("forecast_start_time_utc", "")
        self.declare_parameter("publish_rate_hz", 2.0)
        self.declare_parameter("init_speed_kmh", 45.0)
        self.declare_parameter("soc0", 0.95)
        self.declare_parameter("Tb0", 30.0)
        self.declare_parameter("s0_km", 0.0)
        self.declare_parameter("filter_tau_sec", 1.0)
        self.declare_parameter("accel_limit_kmhps", 1.2)
        self.declare_parameter("decel_limit_kmhps", 3.5)

        profile_yaml = str(self.get_parameter("profile_yaml").value or "").strip()
        if profile_yaml:
            profile_path, cfg = load_profile(profile_yaml)
            sim_cfg = get_section(cfg, "simulation")
            runtime_cfg = get_section(cfg, "runtime")
...
```

### L23 関数 `SolarStateNode.__init__`

- 定義: `__init__(self) -> None`
- 行範囲: L23-L178
- 所属: `SolarStateNode`
- このブロックが直接呼ぶ主な関数/メソッド: `Parameter`, `Params`, `SmoothRateLimiter`, `SolarCarModel`, `__init__`, `astimezone`, `create_publisher`, `create_subscription`, `create_timer`, `declare_parameter`, `float`, `from_yaml`
- この呼出し内で代入する主なローカル名: `_profile_path`, `cfg`, `drive_schedule_yaml`, `key`, `model_cfg`, `params_yaml`, `profile_path`, `profile_yaml`, `raw_start`, `route_profile_csv`, `route_profile_path`, `runtime_cfg`, `sim_cfg`, `t`, `tzname`, `value`
- 読み取る主なインスタンス属性: `self._on_speed_cmd`, `self._step`, `self.create_publisher`, `self.create_subscription`, `self.create_timer`, `self.declare_parameter`, `self.df`, `self.forecast_csv`, `self.get_logger`, `self.get_parameter`, `self.limiter`, `self.model`, `self.publish_rate_hz`, `self.set_parameters`, `self.v_exec_kmh`
- 更新する主なインスタンス属性: `self.Tb`, `self.df`, `self.drive_schedule`, `self.exec_time_sec`, `self.forecast_csv`, `self.last_step`, `self.limiter`, `self.model`, `self.pub_alt`, `self.pub_i`, `self.pub_s`, `self.pub_soc`, `self.pub_solar`, `self.pub_speed`, `self.pub_tb`, `self.pub_v`, `self.publish_rate_hz`, `self.route_profile`, `self.s_km`, `self.start_time_utc`, `self.timer`, `self.v_cmd_kmh`, `self.v_exec_kmh`, `self.z`
- 制御構造の規模: 条件分岐 8、ループ 1、try 2
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
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
  16. self.declare_parameter(...) を実行する。
  17. self.declare_parameter(...) を実行する。
  18. self.declare_parameter(...) を実行する。
  19. self.declare_parameter(...) を実行する。
  20. self.declare_parameter(...) を実行する。
  21. self.declare_parameter(...) を実行する。
  22. self.declare_parameter(...) を実行する。
  23. self.declare_parameter(...) を実行する。
  24. self.declare_parameter(...) を実行する。
  25. self.declare_parameter(...) を実行する。
  26. self.declare_parameter(...) を実行する。
  27. self.declare_parameter(...) を実行する。
  28. profile_yaml に str(self.get_parameter('profile_yaml').value or '').strip() の結果を代入する。
  29. 条件 profile_yaml を判定し、真なら内部処理を行う。
  30.   (profile_path, cfg) に load_profile(profile_yaml) の結果を代入する。
  31.   sim_cfg に get_section(cfg, 'simulation') の結果を代入する。
  32.   runtime_cfg に get_section(cfg, 'runtime') の結果を代入する。
  33.   self.set_parameters(...) を実行する。
  34. self.publish_rate_hz に max(0.2, float(self.get_parameter('publish_rate_hz').value)) の結果を代入する。
  35. self.forecast_csv に str(require_csv_data_rows(resolve_path(str(self.get_parameter('forecast_csv').value), 'inputs'), label='forecast', required_columns=('GHI',))) の結果を代入する。
  36. route_profile_csv に str(self.get_parameter('route_profile_csv').value or '').strip() の結果を代入する。
  37. 条件 route_profile_csv を判定し、真なら内部処理を行う。
  38.   route_profile_path に require_csv_data_rows(resolve_path(route_profile_csv, 'inputs'), label='route profile', required_columns=('dist_km',)) の結果を代入する。
  39.   self.route_profile に pd.read_csv(route_profile_path) の結果を代入する。
  40.   上の条件が偽の場合:
  41.   self.route_profile に None の結果を代入する。
  42. drive_schedule_yaml に str(self.get_parameter('drive_schedule_yaml').value or '').strip() の結果を代入する。
  43. self.drive_schedule に DriveSchedule.from_yaml(resolve_path(drive_schedule_yaml, 'inputs')) if drive_schedule_yaml else None の結果を代入する。
  44. self.df に pd.read_csv(self.forecast_csv) の結果を代入する。
  45. 条件 'time' in self.df.columns を判定し、真なら内部処理を行う。
  46.   t に pd.to_datetime(self.df['time'], format='mixed', errors='coerce') の結果を代入する。
  47.   tzname に str(self.get_parameter('forecast_time_tz').value or 'UTC') の結果を代入する。
  48.   条件 t.dt.tz is None を判定し、真なら内部処理を行う。
  49.     条件 tzname.upper() == 'UTC' を判定し、真なら内部処理を行う。
  50.       t に t.dt.tz_localize('UTC') の結果を代入する。
  51.       上の条件が偽の場合:
  52.       t に t.dt.tz_localize(tzname, ambiguous='NaT', nonexistent='NaT').dt.tz_convert('UTC') の結果を代入する。
  53.     上の条件が偽の場合:
  54.     t に t.dt.tz_convert('UTC') の結果を代入する。
  55.   self.df['time'] に t の結果を代入する。
  56. self.start_time_utc に datetime.now(timezone.utc) の結果を代入する。
  57. raw_start に str(self.get_parameter('forecast_start_time_utc').value or '').strip() の結果を代入する。
  58. 条件 raw_start を判定し、真なら内部処理を行う。
  59.   例外処理を伴う try ブロックを実行する。
  60.     self.start_time_utc に datetime.fromisoformat(raw_start.replace('Z', '+00:00')).astimezone(timezone.utc) の結果を代入する。
  61.     ValueErrorを捕捉した場合:
  62.     self.get_logger().warning(...) を実行する。
  63. self.model に SolarCarModel(resolve_path(str(self.get_parameter('drive_eff_map').value), 'maps'), resolve_path(str(self.get_parameter('regen_eff_map').value), 'maps'), resolve_path(str(self.get_parameter('rint_map').value), 'maps'), params=Params(dt=1.0 / self.publish_rate_hz), panel_eff_map_path=resolve_path(str(self.get_parameter('panel_eff_map').value), 'maps') if str(self.get_parameter('panel_eff_map').value) else None, mppt_eff_map_path=resolve_path(str(self.get_parameter('mppt_eff_map').value), 'maps') if str(self.get_parameter('mppt_eff_map').value) else None, drive_map_eco_path=resolve_path(str(self.get_parameter('drive_map_eco').value), 'maps') if str(self.get_parameter('drive_map_eco').value) else None, drive_map_power_path=resolve_path(str(self.get_parameter('drive_map_power').value), 'maps') if str(self.get_parameter('drive_map_power').value) else None, regen_map_eco_path=resolve_path(str(self.get_parameter('regen_map_eco').value), 'maps') if str(self.get_parameter('regen_map_eco').value) else None, regen_map_power_path=resolve_path(str(self.get_parameter('regen_map_power').value), 'maps') if str(self.get_parameter('regen_map_power').value) else None, ocv_soc_map_path=resolve_path(str(self.get_parameter('ocv_soc_map').value), 'maps') if str(self.get_parameter('ocv_soc_map').value) else None) の結果を代入する。
  64. params_yaml に str(self.get_parameter('params_yaml').value or '').strip() の結果を代入する。
  65. 条件 params_yaml を判定し、真なら内部処理を行う。
  66.   (_profile_path, cfg) に load_profile(params_yaml) の結果を代入する。
  67.   model_cfg に get_section(cfg, 'model') の結果を代入する。
  68.   model_cfg.items() を順に走査し、各要素を (key, value) に入れて処理する。
  69.     条件 hasattr(self.model.p, key) を判定し、真なら内部処理を行う。
  70.       例外処理を伴う try ブロックを実行する。
  71. self.v_cmd_kmh に float(self.get_parameter('init_speed_kmh').value) の結果を代入する。
  72. self.v_exec_kmh に float(self.get_parameter('init_speed_kmh').value) の結果を代入する。
  73. self.s_km に float(self.get_parameter('s0_km').value) の結果を代入する。
  74. self.z に float(self.get_parameter('soc0').value) の結果を代入する。
  75. self.Tb に float(self.get_parameter('Tb0').value) の結果を代入する。
  76. self.last_step に None の結果を代入する。
  77. self.exec_time_sec に 0.0 の結果を代入する。
  78. self.limiter に SmoothRateLimiter(min_value=0.0, max_value=140.0, tau_sec=float(self.get_parameter('filter_tau_sec').value), rise_rate=float(self.get_parameter('accel_limit_kmhps').value), fall_rate=float(self.get_parameter('decel_limit_kmhps').value), initial_value=self.v_exec_kmh) の結果を代入する。
  79. self.limiter.reset(...) を実行する。
  80. self.pub_speed に self.create_publisher(Float32, '/vehicle/speed_kmh', 10) の結果を代入する。

代表コード断片:

```python
    def __init__(self) -> None:
        super().__init__("solar_state_node")
        self.declare_parameter("profile_yaml", "")
        self.declare_parameter("forecast_csv", "inputs/forecast_10min.csv")
        self.declare_parameter("route_profile_csv", "")
        self.declare_parameter("drive_schedule_yaml", "")
        self.declare_parameter("drive_eff_map", "")
        self.declare_parameter("regen_eff_map", "")
        self.declare_parameter("rint_map", "")
        self.declare_parameter("panel_eff_map", "")
        self.declare_parameter("mppt_eff_map", "")
        self.declare_parameter("drive_map_eco", "")
        self.declare_parameter("drive_map_power", "")
        self.declare_parameter("regen_map_eco", "")
        self.declare_parameter("regen_map_power", "")
        self.declare_parameter("ocv_soc_map", "")
        self.declare_parameter("params_yaml", "")
        self.declare_parameter("forecast_time_mode", "auto")
        self.declare_parameter("forecast_time_tz", "UTC")
        self.declare_parameter("forecast_start_time_utc", "")
        self.declare_parameter("publish_rate_hz", 2.0)
        self.declare_parameter("init_speed_kmh", 45.0)
        self.declare_parameter("soc0", 0.95)
        self.declare_parameter("Tb0", 30.0)
        self.declare_parameter("s0_km", 0.0)
        self.declare_parameter("filter_tau_sec", 1.0)
        self.declare_parameter("accel_limit_kmhps", 1.2)
        self.declare_parameter("decel_limit_kmhps", 3.5)

        profile_yaml = str(self.get_parameter("profile_yaml").value or "").strip()
        if profile_yaml:
            profile_path, cfg = load_profile(profile_yaml)
            sim_cfg = get_section(cfg, "simulation")
            runtime_cfg = get_section(cfg, "runtime")
            self.set_parameters(
...
```

### L180 関数 `SolarStateNode._on_speed_cmd`

- 定義: `_on_speed_cmd(self, msg: Float32) -> None`
- 行範囲: L180-L181
- 所属: `SolarStateNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`
- 更新する主なインスタンス属性: `self.v_cmd_kmh`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. self.v_cmd_kmh に float(msg.data) の結果を代入する。

代表コード断片:

```python
    def _on_speed_cmd(self, msg: Float32) -> None:
        self.v_cmd_kmh = float(msg.data)
```

### L183 関数 `SolarStateNode._forecast_row`

- 定義: `_forecast_row(self, now_utc: datetime)`
- 行範囲: L183-L189
- 所属: `SolarStateNode`
- このブロックが直接呼ぶ主な関数/メソッド: `any`, `clip`, `datetime64`, `int`, `len`, `max`, `notna`, `searchsorted`
- 戻り値の要点: `self.df.iloc[idx] / self.df.iloc[idx]`
- この呼出し内で代入する主なローカル名: `idx`
- 読み取る主なインスタンス属性: `self.df`, `self.exec_time_sec`, `self.publish_rate_hz`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. 条件 'time' in self.df.columns and self.df['time'].notna().any() を判定し、真なら内部処理を行う。
  2.   idx に int(np.searchsorted(self.df['time'].values, np.datetime64(now_utc)) - 1) の結果を代入する。
  3.   idx に int(np.clip(idx, 0, len(self.df) - 1)) の結果を代入する。
  4.   self.df.iloc[idx] を返す。
  5. idx に int(np.clip(int(self.exec_time_sec / max(1.0, 3600.0 / self.publish_rate_hz)), 0, len(self.df) - 1)) の結果を代入する。
  6. self.df.iloc[idx] を返す。

代表コード断片:

```python
    def _forecast_row(self, now_utc: datetime):
        if "time" in self.df.columns and self.df["time"].notna().any():
            idx = int(np.searchsorted(self.df["time"].values, np.datetime64(now_utc)) - 1)
            idx = int(np.clip(idx, 0, len(self.df) - 1))
            return self.df.iloc[idx]
        idx = int(np.clip(int(self.exec_time_sec / max(1.0, 3600.0 / self.publish_rate_hz)), 0, len(self.df) - 1))
        return self.df.iloc[idx]
```

### L191 関数 `SolarStateNode._route_value`

- 定義: `_route_value(self, field: str, default: float) -> float`
- 行範囲: L191-L197
- 所属: `SolarStateNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `interpolate_profile`
- 戻り値の要点: `float(default) / float(interpolate_profile(self.route_profile, self.s_km, field, default)) / float(default)`
- 読み取る主なインスタンス属性: `self.route_profile`, `self.s_km`
- 制御構造の規模: 条件分岐 1、ループ 0、try 1
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 条件 self.route_profile is None を判定し、真なら内部処理を行う。
  2.   float(default) を返す。
  3. 例外処理を伴う try ブロックを実行する。
  4.   float(interpolate_profile(self.route_profile, self.s_km, field, default)) を返す。
  5.   Exceptionを捕捉した場合:
  6.   float(default) を返す。

代表コード断片:

```python
    def _route_value(self, field: str, default: float) -> float:
        if self.route_profile is None:
            return float(default)
        try:
            return float(interpolate_profile(self.route_profile, self.s_km, field, default))
        except Exception:
            return float(default)
```

### L199 関数 `SolarStateNode._step`

- 定義: `_step(self) -> None`
- 行範囲: L199-L262
- 所属: `SolarStateNode`
- このブロックが直接呼ぶ主な関数/メソッド: `Float32`, `_forecast_row`, `_route_value`, `abs`, `clip`, `electrical_balance`, `float`, `get`, `get_clock`, `is_drive_time`, `max`, `now`
- この呼出し内で代入する主なローカル名: `alt_m`, `aux_power_w`, `current_a`, `drive_now`, `dt`, `ghi`, `headwind`, `heat_gain`, `now_sec`, `now_utc`, `out`, `p_pack`, `row`, `slope_pct`, `solar_w`, `tamb`, `tcell`, `voltage_v`
- 読み取る主なインスタンス属性: `self.Tb`, `self._forecast_row`, `self._route_value`, `self.drive_schedule`, `self.exec_time_sec`, `self.get_clock`, `self.last_step`, `self.limiter`, `self.model`, `self.pub_alt`, `self.pub_i`, `self.pub_s`, `self.pub_soc`, `self.pub_solar`, `self.pub_speed`, `self.pub_tb`, `self.pub_v`, `self.publish_rate_hz`, `self.s_km`, `self.start_time_utc`, `self.v_cmd_kmh`, `self.v_exec_kmh`, `self.z`
- 更新する主なインスタンス属性: `self.Tb`, `self.exec_time_sec`, `self.last_step`, `self.s_km`, `self.v_exec_kmh`, `self.z`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. now_sec に self.get_clock().now().nanoseconds / 1000000000.0 の結果を代入する。
  2. 条件 self.last_step is None を判定し、真なら内部処理を行う。
  3.   self.last_step に now_sec の結果を代入する。
  4. dt に max(1.0 / self.publish_rate_hz, now_sec - self.last_step) の結果を代入する。
  5. self.last_step に now_sec の結果を代入する。
  6. self.exec_time_sec を Add で更新する。
  7. self.v_exec_kmh に float(self.limiter.update(self.v_cmd_kmh, now=self.exec_time_sec)) の結果を代入する。
  8. self.s_km を Add で更新する。
  9. now_utc に self.start_time_utc + timedelta(seconds=self.exec_time_sec) の結果を代入する。
  10. row に self._forecast_row(now_utc) の結果を代入する。
  11. ghi に float(row.get('GHI', 0.0)) の結果を代入する。
  12. tcell に float(row.get('Tcell_C', 40.0)) の結果を代入する。
  13. tamb に float(row.get('Tamb_C', 30.0)) の結果を代入する。
  14. headwind に float(row.get('headwind_ms', self._route_value('headwind_ms', 0.0))) の結果を代入する。
  15. slope_pct に self._route_value('slope_pct', float(row.get('slope_pct', 0.0))) の結果を代入する。
  16. alt_m に self._route_value('alt_m', self._route_value('altitude_m', 0.0)) の結果を代入する。
  17. drive_now に self.drive_schedule.is_drive_time(now_utc) if self.drive_schedule is not None else True の結果を代入する。
  18. aux_power_w に self.model.scheduled_auxiliary_power(is_driving=drive_now, irradiance_wm2=ghi) の結果を代入する。
  19. out に self.model.electrical_balance(self.v_exec_kmh / 3.6, slope_pct, self.z, self.Tb, ghi, tcell, headwind_ms=headwind, aux_power_w=aux_power_w, ambient_temp_c=tamb, elevation_m=alt_m) の結果を代入する。
  20. p_pack に float(out['P_pack']) の結果を代入する。
  21. current_a に float(out['I']) の結果を代入する。
  22. voltage_v に float(out['V']) の結果を代入する。
  23. solar_w に float(out['P_pv']) の結果を代入する。
  24. self.z に float(np.clip(self.model.soc_step(self.z, p_pack, dt, current_a=current_a, Tbat_C=self.Tb), self.model.p.soc_min, self.model.p.soc_max)) の結果を代入する。
  25. heat_gain に 0.015 * abs(current_a) + 0.002 * max(0.0, p_pack / 100.0) の結果を代入する。
  26. self.Tb を Add で更新する。
  27. self.pub_speed.publish(...) を実行する。
  28. self.pub_s.publish(...) を実行する。
  29. self.pub_soc.publish(...) を実行する。
  30. self.pub_tb.publish(...) を実行する。
  31. self.pub_i.publish(...) を実行する。
  32. self.pub_v.publish(...) を実行する。
  33. self.pub_solar.publish(...) を実行する。
  34. self.pub_alt.publish(...) を実行する。

代表コード断片:

```python
    def _step(self) -> None:
        now_sec = self.get_clock().now().nanoseconds / 1e9
        if self.last_step is None:
            self.last_step = now_sec
        dt = max(1.0 / self.publish_rate_hz, now_sec - self.last_step)
        self.last_step = now_sec
        self.exec_time_sec += dt
        self.v_exec_kmh = float(self.limiter.update(self.v_cmd_kmh, now=self.exec_time_sec))
        self.s_km += self.v_exec_kmh * (dt / 3600.0)

        now_utc = self.start_time_utc + timedelta(seconds=self.exec_time_sec)
        row = self._forecast_row(now_utc)
        ghi = float(row.get("GHI", 0.0))
        tcell = float(row.get("Tcell_C", 40.0))
        tamb = float(row.get("Tamb_C", 30.0))
        headwind = float(row.get("headwind_ms", self._route_value("headwind_ms", 0.0)))
        slope_pct = self._route_value("slope_pct", float(row.get("slope_pct", 0.0)))
        alt_m = self._route_value("alt_m", self._route_value("altitude_m", 0.0))

        drive_now = self.drive_schedule.is_drive_time(now_utc) if self.drive_schedule is not None else True
        aux_power_w = self.model.scheduled_auxiliary_power(
            is_driving=drive_now,
            irradiance_wm2=ghi,
        )
        out = self.model.electrical_balance(
            self.v_exec_kmh / 3.6,
            slope_pct,
            self.z,
            self.Tb,
            ghi,
            tcell,
            headwind_ms=headwind,
            aux_power_w=aux_power_w,
            ambient_temp_c=tamb,
            elevation_m=alt_m,
...
```

### L265 関数 `main`

- 定義: `main() -> None`
- 行範囲: L265-L270
- このブロックが直接呼ぶ主な関数/メソッド: `SolarStateNode`, `destroy_node`, `init`, `shutdown`, `spin`
- この呼出し内で代入する主なローカル名: `node`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に SolarStateNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。

代表コード断片:

```python
def main() -> None:
    rclpy.init()
    node = SolarStateNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
```


## パラメータ

- L25: `profile_yaml`
- L26: `forecast_csv` (default: `inputs/forecast_10min.csv`)
- L27: `route_profile_csv`
- L28: `drive_schedule_yaml`
- L29: `drive_eff_map`
- L30: `regen_eff_map`
- L31: `rint_map`
- L32: `panel_eff_map`
- L33: `mppt_eff_map`
- L34: `drive_map_eco`
- L35: `drive_map_power`
- L36: `regen_map_eco`
- L37: `regen_map_power`
- L38: `ocv_soc_map`
- L39: `params_yaml`
- L40: `forecast_time_mode` (default: `auto`)
- L41: `forecast_time_tz` (default: `UTC`)
- L42: `forecast_start_time_utc`
- L43: `publish_rate_hz` (default: `2.0`)
- L44: `init_speed_kmh` (default: `45.0`)
- L45: `soc0` (default: `0.95`)
- L46: `Tb0` (default: `30.0`)
- L47: `s0_km` (default: `0.0`)
- L48: `filter_tau_sec` (default: `1.0`)
- L49: `accel_limit_kmhps` (default: `1.2`)
- L50: `decel_limit_kmhps` (default: `3.5`)

## ROS topic I/O

- Publisher L168: `/vehicle/speed_kmh`
- Publisher L169: `/vehicle/s_km`
- Publisher L170: `/vehicle/batt_soc`
- Publisher L171: `/vehicle/batt_temp_c`
- Publisher L172: `/vehicle/batt_current_a`
- Publisher L173: `/vehicle/batt_voltage_v`
- Publisher L174: `/vehicle/solar_power_w`
- Publisher L175: `/vehicle/altitude_m`
- Subscription L176: `/planner/speed_cmd` -> `self._on_speed_cmd`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
