# 30. dashboard + HTTP API

- ファイル: `mpc_solarcar/dashboard_node.py`
- ソースSHA-256: `26286dcb019288a13c2e17be4574c311b8bc2bb5e0268544165d6519a5cba443`
- 種別: `Python`
- 区分: `runtime node`

## 役割

planner と vehicle の現在値を ROS から受け、HTTP サーバと dashboard frontend へ渡す。

## 起動文脈

- 起動文脈: 可視化の中心ノード。
- 呼び出し元: `launch/solarcar_sim.launch.py`, `mpc_solarcar/live_launch.py`, `launch/solar_measurement.launch.py`
- 次に読むべきファイル: 特になし

## 主要ポイント

- /api/state と /metrics を持つ。
- ROS topic を直接 browser へ出すのではなく、Node 内 state に集約する。

## 主要構造

主要クラスは DashboardHandler, DashboardNode。 主要関数は do_GET, log_message, destroy_node, get_state, get_prometheus_metrics, main。 ROS パラメータ宣言は 5 件。 ROS I/O は publisher 0 件、subscription 21 件。

## ファイルを上から読んだときの定義順

- L19: クラス DashboardHandler を定義する。
- L55: クラス DashboardNode を定義する。
- L409: 関数 main を定義する。
- L417: 条件 __name__ == '__main__' を判定し、真なら内部処理を行う。

## import 群

- L1: `import json`
  - manifest、checkpoint、UDP payload をやり取りするため。 このファイル内での主な使用位置は L38。
- L2: `import math`
  - Python標準のスカラー数値関数と定数を使うため。実際に参照する名前と行は使用位置欄で確認する。 このファイル内での主な使用位置は L212。
- L3: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L68, L70, L71。
- L4: `import threading`
  - threading モジュールを利用するため。 このファイル内での主な使用位置は L73, L150。
- L5: `import time`
  - wall/monotonic time に基づく周期制御や freshness 判定を行うため。 このファイル内での主な使用位置は L75, L215, L239, L261, L262, L268, L299, L311, ...。
- L6: `from functools import partial`
  - functools から partial を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L147。
- L7: `from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer`
  - http.server から SimpleHTTPRequestHandler, ThreadingHTTPServer を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L19, L149。
- L9: `import rclpy`
  - ROS 2 Python ノードとして起動・spin するため。 このファイル内での主な使用位置は L410, L412, L414。
- L10: `from rclpy.node import Node`
  - ROS 2 ノード本体の基底クラスとして使うため。 このファイル内での主な使用位置は L55。
- L12: `from std_msgs.msg import Float32, Float32MultiArray, String`
  - Float32、Bool、Stringなどの標準ROS messageで値をpublishまたはsubscribeするため。 このファイル内での主な使用位置は L117, L118, L119, L120, L121, L122, L123, L124, ...。
- L13: `from sensor_msgs.msg import NavSatFix`
  - GPS 緯度経度高度を ROS topic でやり取りするため。 このファイル内での主な使用位置は L136, L367。
- L14: `from nav_msgs.msg import Path`
  - 将来軌跡を dashboard や logger へ出すため。 このファイル内での主な使用位置は L137, L373。
- L16: `from ament_index_python.packages import get_package_share_directory`
  - ament_index_python.packages から get_package_share_directory を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L67。
- L381: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L382。

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

### L19 クラス `DashboardHandler`

- 定義: `DashboardHandler(bases=SimpleHTTPRequestHandler)`
- 行範囲: L19-L52
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - class文は新しい型を定義する。丸括弧内は継承する基底クラスである。
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 do_GET を定義する。
  3. 関数 log_message を定義する。
  4. 関数 _send_json を定義する。
  5. 関数 _send_metrics を定義する。

代表コード断片:

```python
class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, node=None, directory=None, **kwargs):
        self._node = node
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        if self.path.startswith('/api/state'):
            self._send_json(self._node.get_state())
            return
        if self.path.startswith('/metrics'):
            self._send_metrics(self._node.get_prometheus_metrics())
            return
        super().do_GET()

    def log_message(self, format, *args):
        # quiet
        return

    def _send_json(self, data):
        payload = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_metrics(self, payload):
        body = payload.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
```

### L20 関数 `DashboardHandler.__init__`

- 定義: `__init__(self, *args, node = None, directory = None, **kwargs)`
- 行範囲: L20-L22
- 所属: `DashboardHandler`
- このブロックが直接呼ぶ主な関数/メソッド: `__init__`, `super`
- 更新する主なインスタンス属性: `self._node`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._node に node の結果を代入する。
  2. super().__init__(...) を実行する。

代表コード断片:

```python
    def __init__(self, *args, node=None, directory=None, **kwargs):
        self._node = node
        super().__init__(*args, directory=directory, **kwargs)
```

### L24 関数 `DashboardHandler.do_GET`

- 定義: `do_GET(self)`
- 行範囲: L24-L31
- 所属: `DashboardHandler`
- このブロックが直接呼ぶ主な関数/メソッド: `_send_json`, `_send_metrics`, `do_GET`, `get_prometheus_metrics`, `get_state`, `startswith`, `super`
- 読み取る主なインスタンス属性: `self._node`, `self._send_json`, `self._send_metrics`, `self.path`
- 制御構造の規模: 条件分岐 2、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. 条件 self.path.startswith('/api/state') を判定し、真なら内部処理を行う。
  2.   self._send_json(...) を実行する。
  3.    を返す。
  4. 条件 self.path.startswith('/metrics') を判定し、真なら内部処理を行う。
  5.   self._send_metrics(...) を実行する。
  6.    を返す。
  7. super().do_GET(...) を実行する。

代表コード断片:

```python
    def do_GET(self):
        if self.path.startswith('/api/state'):
            self._send_json(self._node.get_state())
            return
        if self.path.startswith('/metrics'):
            self._send_metrics(self._node.get_prometheus_metrics())
            return
        super().do_GET()
```

### L33 関数 `DashboardHandler.log_message`

- 定義: `log_message(self, format, *args)`
- 行範囲: L33-L35
- 所属: `DashboardHandler`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1.  を返す。

代表コード断片:

```python
    def log_message(self, format, *args):
        # quiet
        return
```

### L37 関数 `DashboardHandler._send_json`

- 定義: `_send_json(self, data)`
- 行範囲: L37-L43
- 所属: `DashboardHandler`
- このブロックが直接呼ぶ主な関数/メソッド: `dumps`, `encode`, `end_headers`, `len`, `send_header`, `send_response`, `str`, `write`
- この呼出し内で代入する主なローカル名: `payload`
- 読み取る主なインスタンス属性: `self.end_headers`, `self.send_header`, `self.send_response`, `self.wfile`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. payload に json.dumps(data).encode('utf-8') の結果を代入する。
  2. self.send_response(...) を実行する。
  3. self.send_header(...) を実行する。
  4. self.send_header(...) を実行する。
  5. self.end_headers(...) を実行する。
  6. self.wfile.write(...) を実行する。

代表コード断片:

```python
    def _send_json(self, data):
        payload = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)
```

### L45 関数 `DashboardHandler._send_metrics`

- 定義: `_send_metrics(self, payload)`
- 行範囲: L45-L52
- 所属: `DashboardHandler`
- このブロックが直接呼ぶ主な関数/メソッド: `encode`, `end_headers`, `len`, `send_header`, `send_response`, `str`, `write`
- この呼出し内で代入する主なローカル名: `body`
- 読み取る主なインスタンス属性: `self.end_headers`, `self.send_header`, `self.send_response`, `self.wfile`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. body に payload.encode('utf-8') の結果を代入する。
  2. self.send_response(...) を実行する。
  3. self.send_header(...) を実行する。
  4. self.send_header(...) を実行する。
  5. self.send_header(...) を実行する。
  6. self.end_headers(...) を実行する。
  7. self.wfile.write(...) を実行する。

代表コード断片:

```python
    def _send_metrics(self, payload):
        body = payload.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
```

### L55 クラス `DashboardNode`

- 定義: `DashboardNode(bases=Node)`
- 行範囲: L55-L406
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - class文は新しい型を定義する。丸括弧内は継承する基底クラスである。
  - 内包表記は、反復・条件・値生成を一つの式で記述してcollectionを作る。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 destroy_node を定義する。
  3. 関数 get_state を定義する。
  4. 関数 get_prometheus_metrics を定義する。
  5. 関数 _update を定義する。
  6. 関数 _on_speed_cmd を定義する。
  7. 関数 _on_upper_speed_cmd を定義する。
  8. 関数 _on_speed_meas を定義する。
  9. 関数 _on_throttle_cmd を定義する。
  10. 関数 _on_drive_mode を定義する。
  11. 関数 _on_soc を定義する。
  12. 関数 _set_estimated_soc を定義する。

代表コード断片:

```python
class DashboardNode(Node):
    def __init__(self):
        super().__init__('dashboard_node')
        self.declare_parameter('host', '0.0.0.0')
        self.declare_parameter('port', 8080)
        self.declare_parameter('static_dir', '')
        self.declare_parameter('dummy_csv', '')
        self.declare_parameter('dummy_rate_hz', 5.0)

        static_dir = str(self.get_parameter('static_dir').value).strip()
        if not static_dir:
            try:
                pkg_share = get_package_share_directory('mpc_solarcar')
                static_dir = os.path.join(pkg_share, 'dashboard')
            except Exception:
                static_dir = os.path.join(os.path.dirname(__file__), '..', 'dashboard')
        static_dir = os.path.abspath(static_dir)

        self._lock = threading.Lock()
        self._state = {
            'ts': time.time(),
            'speed_cmd_kmh': None,
            'upper_speed_cmd_kmh': None,
            'speed_meas_kmh': None,
            'model_speed_kmh': None,
            'throttle_cmd_pct': None,
            'drive_mode': None,
            'soc': None,
            'soc_meas': None,
            'soc_est': None,
            'Tb_C': None,
            's_km': None,
            'batt_current_a': None,
            'batt_voltage_v': None,
            'motor_w': None,
...
```

### L56 関数 `DashboardNode.__init__`

- 定義: `__init__(self)`
- 行範囲: L56-L154
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `Lock`, `Thread`, `ThreadingHTTPServer`, `__init__`, `_init_dummy`, `abspath`, `create_subscription`, `declare_parameter`, `dirname`, `error`, `float`, `get_logger`
- この呼出し内で代入する主なローカル名: `dummy_csv`, `handler`, `host`, `pkg_share`, `port`, `static_dir`
- 読み取る主なインスタンス属性: `self._init_dummy`, `self._on_drive_mode`, `self._on_env`, `self._on_gps`, `self._on_health`, `self._on_ibatt`, `self._on_lower_plan`, `self._on_metrics`, `self._on_mpc_state`, `self._on_path`, `self._on_s_km`, `self._on_soc`, `self._on_speed_cmd`, `self._on_speed_meas`, `self._on_status`, `self._on_sys_diag`, `self._on_sys_state`, `self._on_tb`, `self._on_throttle_cmd`, `self._on_upper_plan`, `self._on_upper_speed_cmd`, `self._on_vbatt`, `self._server`, `self._server_thread`
- 更新する主なインスタンス属性: `self._lock`, `self._server`, `self._server_thread`, `self._soc_meas_monotonic`, `self._state`
- 制御構造の規模: 条件分岐 2、ループ 0、try 2
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. super().__init__(...) を実行する。
  2. self.declare_parameter(...) を実行する。
  3. self.declare_parameter(...) を実行する。
  4. self.declare_parameter(...) を実行する。
  5. self.declare_parameter(...) を実行する。
  6. self.declare_parameter(...) を実行する。
  7. static_dir に str(self.get_parameter('static_dir').value).strip() の結果を代入する。
  8. 条件 not static_dir を判定し、真なら内部処理を行う。
  9.   例外処理を伴う try ブロックを実行する。
  10.     pkg_share に get_package_share_directory('mpc_solarcar') の結果を代入する。
  11.     static_dir に os.path.join(pkg_share, 'dashboard') の結果を代入する。
  12.     Exceptionを捕捉した場合:
  13.     static_dir に os.path.join(os.path.dirname(__file__), '..', 'dashboard') の結果を代入する。
  14. static_dir に os.path.abspath(static_dir) の結果を代入する。
  15. self._lock に threading.Lock() の結果を代入する。
  16. self._state に {'ts': time.time(), 'speed_cmd_kmh': None, 'upper_speed_cmd_kmh': None, 'speed_meas_kmh': None, 'model_speed_kmh': None, 'throttle_cmd_pct': None, 'drive_mode': None, 'soc': None, 'soc_meas': None, 'soc_est': None, 'Tb_C': None, 's_km': None, 'batt_current_a': None, 'batt_voltage_v': None, 'motor_w': None, 'motor_a': None, 'solar_w': None, 'wheel_w': None, 'pack_w': None, 'G_poa': None, 'Tcell_C': None, 'Tamb_C': None, 'headwind_ms': None, 'slope_pct': None, 'plan_dt': None, 'lower_dt': None, 'plan_upper': None, 'plan_lower': None, 'forecast_k': None, 'sec_to_next': None, 'control_stop_hold': None, 'control_stop_remaining_sec': None, 'control_stop_completed_count': None, 'system_state': None, 'system_diag': None, 'mpc_state': None, 'system_health': None, 'gps_lat': None, 'gps_lon': None} の結果を代入する。
  17. self._soc_meas_monotonic に None の結果を代入する。
  18. self.create_subscription(...) を実行する。
  19. self.create_subscription(...) を実行する。
  20. self.create_subscription(...) を実行する。
  21. self.create_subscription(...) を実行する。
  22. self.create_subscription(...) を実行する。
  23. self.create_subscription(...) を実行する。
  24. self.create_subscription(...) を実行する。
  25. self.create_subscription(...) を実行する。
  26. self.create_subscription(...) を実行する。
  27. self.create_subscription(...) を実行する。
  28. self.create_subscription(...) を実行する。
  29. self.create_subscription(...) を実行する。
  30. self.create_subscription(...) を実行する。
  31. self.create_subscription(...) を実行する。
  32. self.create_subscription(...) を実行する。
  33. self.create_subscription(...) を実行する。
  34. self.create_subscription(...) を実行する。
  35. self.create_subscription(...) を実行する。
  36. self.create_subscription(...) を実行する。
  37. self.create_subscription(...) を実行する。
  38. self.create_subscription(...) を実行する。
  39. dummy_csv に str(self.get_parameter('dummy_csv').value).strip() の結果を代入する。
  40. 条件 dummy_csv を判定し、真なら内部処理を行う。
  41.   self._init_dummy(...) を実行する。
  42. self._server に None の結果を代入する。
  43. self._server_thread に None の結果を代入する。
  44. host に str(self.get_parameter('host').value) の結果を代入する。
  45. port に int(self.get_parameter('port').value) の結果を代入する。
  46. handler に partial(DashboardHandler, node=self, directory=static_dir) の結果を代入する。
  47. 例外処理を伴う try ブロックを実行する。
  48.   self._server に ThreadingHTTPServer((host, port), handler) の結果を代入する。
  49.   self._server_thread に threading.Thread(target=self._server.serve_forever, daemon=True) の結果を代入する。
  50.   self._server_thread.start(...) を実行する。
  51.   self.get_logger().info(...) を実行する。
  52.   Exceptionを捕捉した場合:
  53.   self.get_logger().error(...) を実行する。

代表コード断片:

```python
    def __init__(self):
        super().__init__('dashboard_node')
        self.declare_parameter('host', '0.0.0.0')
        self.declare_parameter('port', 8080)
        self.declare_parameter('static_dir', '')
        self.declare_parameter('dummy_csv', '')
        self.declare_parameter('dummy_rate_hz', 5.0)

        static_dir = str(self.get_parameter('static_dir').value).strip()
        if not static_dir:
            try:
                pkg_share = get_package_share_directory('mpc_solarcar')
                static_dir = os.path.join(pkg_share, 'dashboard')
            except Exception:
                static_dir = os.path.join(os.path.dirname(__file__), '..', 'dashboard')
        static_dir = os.path.abspath(static_dir)

        self._lock = threading.Lock()
        self._state = {
            'ts': time.time(),
            'speed_cmd_kmh': None,
            'upper_speed_cmd_kmh': None,
            'speed_meas_kmh': None,
            'model_speed_kmh': None,
            'throttle_cmd_pct': None,
            'drive_mode': None,
            'soc': None,
            'soc_meas': None,
            'soc_est': None,
            'Tb_C': None,
            's_km': None,
            'batt_current_a': None,
            'batt_voltage_v': None,
            'motor_w': None,
            'motor_a': None,
...
```

### L156 関数 `DashboardNode.destroy_node`

- 定義: `destroy_node(self)`
- 行範囲: L156-L163
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `destroy_node`, `server_close`, `shutdown`, `super`
- 戻り値の要点: `super().destroy_node()`
- 読み取る主なインスタンス属性: `self._server`
- 制御構造の規模: 条件分岐 1、ループ 0、try 1
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 条件 self._server is not None を判定し、真なら内部処理を行う。
  2.   例外処理を伴う try ブロックを実行する。
  3.     self._server.shutdown(...) を実行する。
  4.     self._server.server_close(...) を実行する。
  5.     Exceptionを捕捉した場合:
  6.     Pass 文を実行する。
  7. super().destroy_node() を返す。

代表コード断片:

```python
    def destroy_node(self):
        if self._server is not None:
            try:
                self._server.shutdown()
                self._server.server_close()
            except Exception:
                pass
        return super().destroy_node()
```

### L165 関数 `DashboardNode.get_state`

- 定義: `get_state(self)`
- 行範囲: L165-L167
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `dict`
- 戻り値の要点: `dict(self._state)`
- 読み取る主なインスタンス属性: `self._lock`, `self._state`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. with 文で self._lock を管理しながら処理する。
  2.   dict(self._state) を返す。

代表コード断片:

```python
    def get_state(self):
        with self._lock:
            return dict(self._state)
```

### L169 関数 `DashboardNode.get_prometheus_metrics`

- 定義: `get_prometheus_metrics(self)`
- 行範囲: L169-L234
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `dict`, `extend`, `float`, `get`, `isfinite`, `items`, `join`, `max`, `replace`, `str`, `time`
- 戻り値の要点: `'\n'.join(lines) + '\n'`
- この呼出し内で代入する主なローカル名: `age_sec`, `help_text`, `key`, `label`, `lines`, `metric_keys`, `metric_name`, `number`, `state`, `state_key`, `value`
- 読み取る主なインスタンス属性: `self._lock`, `self._state`
- 制御構造の規模: 条件分岐 1、ループ 2、try 1
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. metric_keys に {'speed_cmd_kmh': ('solarcar_speed_command_kmh', 'Lower speed command'), 'upper_speed_cmd_kmh': ('solarcar_speed_upper_command_kmh', 'Upper planner speed command'), 'speed_meas_kmh': ('solarcar_speed_measured_kmh', 'Measured vehicle speed'), 'model_speed_kmh': ('solarcar_speed_model_kmh', 'Speed used for planner model metrics'), 'throttle_cmd_pct': ('solarcar_throttle_command_percent', 'Lower controller throttle command'), 'soc': ('solarcar_battery_soc_ratio', 'Selected battery state of charge'), 'soc_meas': ('solarcar_battery_soc_measured_ratio', 'Measured battery state of charge'), 'soc_est': ('solarcar_battery_soc_estimated_ratio', 'Estimated battery state of charge'), 'Tb_C': ('solarcar_battery_temperature_celsius', 'Battery temperature'), 's_km': ('solarcar_distance_km', 'Race distance'), 'batt_current_a': ('solarcar_battery_current_ampere', 'Battery current'), 'batt_voltage_v': ('solarcar_battery_voltage_volt', 'Battery terminal voltage'), 'motor_w': ('solarcar_motor_power_watt', 'Motor electrical power'), 'motor_a': ('solarcar_motor_current_ampere', 'Motor current'), 'solar_w': ('solarcar_pv_power_watt', 'PV power'), 'wheel_w': ('solarcar_wheel_power_watt', 'Wheel mechanical power'), 'pack_w': ('solarcar_pack_power_watt', 'Battery pack power'), 'G_poa': ('solarcar_irradiance_poa_watt_per_m2', 'Plane-of-array irradiance'), 'Tcell_C': ('solarcar_cell_temperature_celsius', 'PV cell temperature'), 'Tamb_C': ('solarcar_ambient_temperature_celsius', 'Ambient temperature'), 'headwind_ms': ('solarcar_headwind_meter_per_second', 'Corrected headwind'), 'slope_pct': ('solarcar_route_slope_percent', 'Route slope'), 'forecast_k': ('solarcar_forecast_index', 'Forecast row index'), 'sec_to_next': ('solarcar_seconds_to_next_update', 'Seconds to next planner update'), 'control_stop_hold': ('solarcar_control_stop_hold', 'Control-stop approach or dwell is active'), 'control_stop_remaining_sec': ('solarcar_control_stop_remaining_seconds', 'Remaining mandatory control-stop dwell'), 'control_stop_completed_count': ('solarcar_control_stop_completed_total', 'Completed mandatory control stops'), 'system_health': ('solarcar_system_health_ratio', 'System health ratio'), 'gps_lat': ('solarcar_gps_latitude_degree', 'GNSS latitude'), 'gps_lon': ('solarcar_gps_longitude_degree', 'GNSS longitude'), 'path_points': ('solarcar_path_points', 'Published trajectory point count')} の結果を代入する。
  2. with 文で self._lock を管理しながら処理する。
  3.   state に dict(self._state) の結果を代入する。
  4. lines に [] の結果を代入する。
  5. metric_keys.items() を順に走査し、各要素を (state_key, (metric_name, help_text)) に入れて処理する。
  6.   value に state.get(state_key) の結果を代入する。
  7.   例外処理を伴う try ブロックを実行する。
  8.     number に float(value) の結果を代入する。
  9.     (TypeError, ValueError)を捕捉した場合:
  10.     Continue 文を実行する。
  11.   条件 not math.isfinite(number) を判定し、真なら内部処理を行う。
  12.     Continue 文を実行する。
  13.   lines.extend(...) を実行する。
  14. age_sec に max(0.0, time.time() - float(state.get('ts', time.time()))) の結果を代入する。
  15. lines.extend(...) を実行する。
  16. (('system_state', 'solarcar_system_state_info'), ('mpc_state', 'solarcar_mpc_state_info'), ('drive_mode', 'solarcar_drive_mode_info')) を順に走査し、各要素を (key, metric_name) に入れて処理する。
  17.   label に str(state.get(key) or 'unknown').replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ') の結果を代入する。
  18.   lines.extend(...) を実行する。
  19. '\n'.join(lines) + '\n' を返す。

代表コード断片:

```python
    def get_prometheus_metrics(self):
        metric_keys = {
            'speed_cmd_kmh': ('solarcar_speed_command_kmh', 'Lower speed command'),
            'upper_speed_cmd_kmh': ('solarcar_speed_upper_command_kmh', 'Upper planner speed command'),
            'speed_meas_kmh': ('solarcar_speed_measured_kmh', 'Measured vehicle speed'),
            'model_speed_kmh': ('solarcar_speed_model_kmh', 'Speed used for planner model metrics'),
            'throttle_cmd_pct': ('solarcar_throttle_command_percent', 'Lower controller throttle command'),
            'soc': ('solarcar_battery_soc_ratio', 'Selected battery state of charge'),
            'soc_meas': ('solarcar_battery_soc_measured_ratio', 'Measured battery state of charge'),
            'soc_est': ('solarcar_battery_soc_estimated_ratio', 'Estimated battery state of charge'),
            'Tb_C': ('solarcar_battery_temperature_celsius', 'Battery temperature'),
            's_km': ('solarcar_distance_km', 'Race distance'),
            'batt_current_a': ('solarcar_battery_current_ampere', 'Battery current'),
            'batt_voltage_v': ('solarcar_battery_voltage_volt', 'Battery terminal voltage'),
            'motor_w': ('solarcar_motor_power_watt', 'Motor electrical power'),
            'motor_a': ('solarcar_motor_current_ampere', 'Motor current'),
            'solar_w': ('solarcar_pv_power_watt', 'PV power'),
            'wheel_w': ('solarcar_wheel_power_watt', 'Wheel mechanical power'),
            'pack_w': ('solarcar_pack_power_watt', 'Battery pack power'),
            'G_poa': ('solarcar_irradiance_poa_watt_per_m2', 'Plane-of-array irradiance'),
            'Tcell_C': ('solarcar_cell_temperature_celsius', 'PV cell temperature'),
            'Tamb_C': ('solarcar_ambient_temperature_celsius', 'Ambient temperature'),
            'headwind_ms': ('solarcar_headwind_meter_per_second', 'Corrected headwind'),
            'slope_pct': ('solarcar_route_slope_percent', 'Route slope'),
            'forecast_k': ('solarcar_forecast_index', 'Forecast row index'),
            'sec_to_next': ('solarcar_seconds_to_next_update', 'Seconds to next planner update'),
            'control_stop_hold': ('solarcar_control_stop_hold', 'Control-stop approach or dwell is active'),
            'control_stop_remaining_sec': ('solarcar_control_stop_remaining_seconds', 'Remaining mandatory control-stop dwell'),
            'control_stop_completed_count': ('solarcar_control_stop_completed_total', 'Completed mandatory control stops'),
            'system_health': ('solarcar_system_health_ratio', 'System health ratio'),
            'gps_lat': ('solarcar_gps_latitude_degree', 'GNSS latitude'),
            'gps_lon': ('solarcar_gps_longitude_degree', 'GNSS longitude'),
            'path_points': ('solarcar_path_points', 'Published trajectory point count'),
        }
        with self._lock:
...
```

### L236 関数 `DashboardNode._update`

- 定義: `_update(self, key, value)`
- 行範囲: L236-L239
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `time`
- 読み取る主なインスタンス属性: `self._lock`, `self._state`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. with 文で self._lock を管理しながら処理する。
  2.   self._state[key] に value の結果を代入する。
  3.   self._state['ts'] に time.time() の結果を代入する。

代表コード断片:

```python
    def _update(self, key, value):
        with self._lock:
            self._state[key] = value
            self._state['ts'] = time.time()
```

### L241 関数 `DashboardNode._on_speed_cmd`

- 定義: `_on_speed_cmd(self, msg: Float32)`
- 行範囲: L241-L242
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `float`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_speed_cmd(self, msg: Float32):
        self._update('speed_cmd_kmh', float(msg.data))
```

### L244 関数 `DashboardNode._on_upper_speed_cmd`

- 定義: `_on_upper_speed_cmd(self, msg: Float32)`
- 行範囲: L244-L245
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `float`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_upper_speed_cmd(self, msg: Float32):
        self._update('upper_speed_cmd_kmh', float(msg.data))
```

### L247 関数 `DashboardNode._on_speed_meas`

- 定義: `_on_speed_meas(self, msg: Float32)`
- 行範囲: L247-L248
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `float`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_speed_meas(self, msg: Float32):
        self._update('speed_meas_kmh', float(msg.data))
```

### L250 関数 `DashboardNode._on_throttle_cmd`

- 定義: `_on_throttle_cmd(self, msg: Float32)`
- 行範囲: L250-L251
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `float`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_throttle_cmd(self, msg: Float32):
        self._update('throttle_cmd_pct', float(msg.data))
```

### L253 関数 `DashboardNode._on_drive_mode`

- 定義: `_on_drive_mode(self, msg: String)`
- 行範囲: L253-L254
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `str`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_drive_mode(self, msg: String):
        self._update('drive_mode', str(msg.data))
```

### L256 関数 `DashboardNode._on_soc`

- 定義: `_on_soc(self, msg: Float32)`
- 行範囲: L256-L262
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `monotonic`, `time`
- この呼出し内で代入する主なローカル名: `value`
- 読み取る主なインスタンス属性: `self._lock`, `self._state`
- 更新する主なインスタンス属性: `self._soc_meas_monotonic`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. value に float(msg.data) の結果を代入する。
  2. with 文で self._lock を管理しながら処理する。
  3.   self._state['soc'] に value の結果を代入する。
  4.   self._state['soc_meas'] に value の結果を代入する。
  5.   self._state['ts'] に time.time() の結果を代入する。
  6.   self._soc_meas_monotonic に time.monotonic() の結果を代入する。

代表コード断片:

```python
    def _on_soc(self, msg: Float32):
        value = float(msg.data)
        with self._lock:
            self._state['soc'] = value
            self._state['soc_meas'] = value
            self._state['ts'] = time.time()
            self._soc_meas_monotonic = time.monotonic()
```

### L264 関数 `DashboardNode._set_estimated_soc`

- 定義: `_set_estimated_soc(self, value)`
- 行範囲: L264-L271
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `monotonic`
- この呼出し内で代入する主なローカル名: `measured_is_fresh`
- 読み取る主なインスタンス属性: `self._soc_meas_monotonic`, `self._state`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._state['soc_est'] に float(value) の結果を代入する。
  2. measured_is_fresh に self._soc_meas_monotonic is not None and time.monotonic() - self._soc_meas_monotonic <= 5.0 の結果を代入する。
  3. 条件 not measured_is_fresh を判定し、真なら内部処理を行う。
  4.   self._state['soc'] に float(value) の結果を代入する。

代表コード断片:

```python
    def _set_estimated_soc(self, value):
        self._state['soc_est'] = float(value)
        measured_is_fresh = (
            self._soc_meas_monotonic is not None
            and (time.monotonic() - self._soc_meas_monotonic) <= 5.0
        )
        if not measured_is_fresh:
            self._state['soc'] = float(value)
```

### L273 関数 `DashboardNode._on_tb`

- 定義: `_on_tb(self, msg: Float32)`
- 行範囲: L273-L274
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `float`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_tb(self, msg: Float32):
        self._update('Tb_C', float(msg.data))
```

### L276 関数 `DashboardNode._on_ibatt`

- 定義: `_on_ibatt(self, msg: Float32)`
- 行範囲: L276-L277
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `float`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_ibatt(self, msg: Float32):
        self._update('batt_current_a', float(msg.data))
```

### L279 関数 `DashboardNode._on_vbatt`

- 定義: `_on_vbatt(self, msg: Float32)`
- 行範囲: L279-L280
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `float`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_vbatt(self, msg: Float32):
        self._update('batt_voltage_v', float(msg.data))
```

### L282 関数 `DashboardNode._on_s_km`

- 定義: `_on_s_km(self, msg: Float32)`
- 行範囲: L282-L283
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `float`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_s_km(self, msg: Float32):
        self._update('s_km', float(msg.data))
```

### L285 関数 `DashboardNode._on_status`

- 定義: `_on_status(self, msg: Float32MultiArray)`
- 行範囲: L285-L299
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_set_estimated_soc`, `float`, `len`, `list`, `time`
- この呼出し内で代入する主なローカル名: `data`
- 読み取る主なインスタンス属性: `self._lock`, `self._set_estimated_soc`, `self._state`
- 制御構造の規模: 条件分岐 2、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. data に list(msg.data) の結果を代入する。
  2. with 文で self._lock を管理しながら処理する。
  3.   条件 len(data) >= 5 を判定し、真なら内部処理を行う。
  4.     self._set_estimated_soc(...) を実行する。
  5.     self._state['Tb_C'] に float(data[1]) の結果を代入する。
  6.     self._state['s_km'] に float(data[2]) の結果を代入する。
  7.     self._state['forecast_k'] に float(data[3]) の結果を代入する。
  8.     self._state['sec_to_next'] に float(data[4]) の結果を代入する。
  9.   条件 len(data) >= 8 を判定し、真なら内部処理を行う。
  10.     self._state['control_stop_hold'] に float(data[5]) の結果を代入する。
  11.     self._state['control_stop_remaining_sec'] に float(data[6]) の結果を代入する。
  12.     self._state['control_stop_completed_count'] に float(data[7]) の結果を代入する。
  13.   self._state['status_raw'] に data の結果を代入する。
  14.   self._state['ts'] に time.time() の結果を代入する。

代表コード断片:

```python
    def _on_status(self, msg: Float32MultiArray):
        data = list(msg.data)
        with self._lock:
            if len(data) >= 5:
                self._set_estimated_soc(data[0])
                self._state['Tb_C'] = float(data[1])
                self._state['s_km'] = float(data[2])
                self._state['forecast_k'] = float(data[3])
                self._state['sec_to_next'] = float(data[4])
            if len(data) >= 8:
                self._state['control_stop_hold'] = float(data[5])
                self._state['control_stop_remaining_sec'] = float(data[6])
                self._state['control_stop_completed_count'] = float(data[7])
            self._state['status_raw'] = data
            self._state['ts'] = time.time()
```

### L301 関数 `DashboardNode._on_env`

- 定義: `_on_env(self, msg: Float32MultiArray)`
- 行範囲: L301-L311
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `len`, `list`, `time`
- この呼出し内で代入する主なローカル名: `data`
- 読み取る主なインスタンス属性: `self._lock`, `self._state`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. data に list(msg.data) の結果を代入する。
  2. 条件 len(data) < 5 を判定し、真なら内部処理を行う。
  3.    を返す。
  4. with 文で self._lock を管理しながら処理する。
  5.   self._state['G_poa'] に float(data[0]) の結果を代入する。
  6.   self._state['Tcell_C'] に float(data[1]) の結果を代入する。
  7.   self._state['Tamb_C'] に float(data[2]) の結果を代入する。
  8.   self._state['slope_pct'] に float(data[3]) の結果を代入する。
  9.   self._state['headwind_ms'] に float(data[4]) の結果を代入する。
  10.   self._state['ts'] に time.time() の結果を代入する。

代表コード断片:

```python
    def _on_env(self, msg: Float32MultiArray):
        data = list(msg.data)
        if len(data) < 5:
            return
        with self._lock:
            self._state['G_poa'] = float(data[0])
            self._state['Tcell_C'] = float(data[1])
            self._state['Tamb_C'] = float(data[2])
            self._state['slope_pct'] = float(data[3])
            self._state['headwind_ms'] = float(data[4])
            self._state['ts'] = time.time()
```

### L313 関数 `DashboardNode._on_metrics`

- 定義: `_on_metrics(self, msg: Float32MultiArray)`
- 行範囲: L313-L331
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_set_estimated_soc`, `float`, `len`, `list`, `time`
- この呼出し内で代入する主なローカル名: `data`
- 読み取る主なインスタンス属性: `self._lock`, `self._set_estimated_soc`, `self._state`
- 制御構造の規模: 条件分岐 2、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. data に list(msg.data) の結果を代入する。
  2. 条件 len(data) < 8 を判定し、真なら内部処理を行う。
  3.    を返す。
  4. with 文で self._lock を管理しながら処理する。
  5.   self._state['batt_voltage_v'] に float(data[0]) の結果を代入する。
  6.   self._state['batt_current_a'] に float(data[1]) の結果を代入する。
  7.   self._set_estimated_soc(...) を実行する。
  8.   self._state['motor_w'] に float(data[3]) の結果を代入する。
  9.   self._state['motor_a'] に float(data[4]) の結果を代入する。
  10.   self._state['solar_w'] に float(data[5]) の結果を代入する。
  11.   self._state['model_speed_kmh'] に float(data[6]) の結果を代入する。
  12.   self._state['wheel_w'] に float(data[7]) の結果を代入する。
  13.   条件 len(data) >= 9 を判定し、真なら内部処理を行う。
  14.     self._state['pack_w'] に float(data[8]) の結果を代入する。
  15.   self._state['ts'] に time.time() の結果を代入する。

代表コード断片:

```python
    def _on_metrics(self, msg: Float32MultiArray):
        data = list(msg.data)
        if len(data) < 8:
            return
        with self._lock:
            self._state['batt_voltage_v'] = float(data[0])
            self._state['batt_current_a'] = float(data[1])
            self._set_estimated_soc(data[2])
            self._state['motor_w'] = float(data[3])
            self._state['motor_a'] = float(data[4])
            self._state['solar_w'] = float(data[5])
            # Metrics carry the speed used for model evaluation, not the lower
            # controller command. Keep it separate so callback ordering cannot
            # overwrite /planner/speed_cmd on the dashboard.
            self._state['model_speed_kmh'] = float(data[6])
            self._state['wheel_w'] = float(data[7])
            if len(data) >= 9:
                self._state['pack_w'] = float(data[8])
            self._state['ts'] = time.time()
```

### L333 関数 `DashboardNode._on_upper_plan`

- 定義: `_on_upper_plan(self, msg: Float32MultiArray)`
- 行範囲: L333-L342
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `len`, `list`, `time`
- この呼出し内で代入する主なローカル名: `data`, `dt`, `speeds`, `v`
- 読み取る主なインスタンス属性: `self._lock`, `self._state`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - 内包表記は、反復・条件・値生成を一つの式で記述してcollectionを作る。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. data に list(msg.data) の結果を代入する。
  2. 条件 len(data) < 2 を判定し、真なら内部処理を行う。
  3.    を返す。
  4. dt に float(data[0]) の結果を代入する。
  5. speeds に [float(v) for v in data[1:]] の結果を代入する。
  6. with 文で self._lock を管理しながら処理する。
  7.   self._state['plan_dt'] に dt の結果を代入する。
  8.   self._state['plan_upper'] に speeds の結果を代入する。
  9.   self._state['ts'] に time.time() の結果を代入する。

代表コード断片:

```python
    def _on_upper_plan(self, msg: Float32MultiArray):
        data = list(msg.data)
        if len(data) < 2:
            return
        dt = float(data[0])
        speeds = [float(v) for v in data[1:]]
        with self._lock:
            self._state['plan_dt'] = dt
            self._state['plan_upper'] = speeds
            self._state['ts'] = time.time()
```

### L344 関数 `DashboardNode._on_lower_plan`

- 定義: `_on_lower_plan(self, msg: Float32MultiArray)`
- 行範囲: L344-L353
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `len`, `list`, `time`
- この呼出し内で代入する主なローカル名: `data`, `dt`, `speeds`, `v`
- 読み取る主なインスタンス属性: `self._lock`, `self._state`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - 内包表記は、反復・条件・値生成を一つの式で記述してcollectionを作る。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. data に list(msg.data) の結果を代入する。
  2. 条件 len(data) < 2 を判定し、真なら内部処理を行う。
  3.    を返す。
  4. dt に float(data[0]) の結果を代入する。
  5. speeds に [float(v) for v in data[1:]] の結果を代入する。
  6. with 文で self._lock を管理しながら処理する。
  7.   self._state['lower_dt'] に dt の結果を代入する。
  8.   self._state['plan_lower'] に speeds の結果を代入する。
  9.   self._state['ts'] に time.time() の結果を代入する。

代表コード断片:

```python
    def _on_lower_plan(self, msg: Float32MultiArray):
        data = list(msg.data)
        if len(data) < 2:
            return
        dt = float(data[0])
        speeds = [float(v) for v in data[1:]]
        with self._lock:
            self._state['lower_dt'] = dt
            self._state['plan_lower'] = speeds
            self._state['ts'] = time.time()
```

### L355 関数 `DashboardNode._on_sys_state`

- 定義: `_on_sys_state(self, msg: String)`
- 行範囲: L355-L356
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `str`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_sys_state(self, msg: String):
        self._update('system_state', str(msg.data))
```

### L358 関数 `DashboardNode._on_sys_diag`

- 定義: `_on_sys_diag(self, msg: String)`
- 行範囲: L358-L359
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `str`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_sys_diag(self, msg: String):
        self._update('system_diag', str(msg.data))
```

### L361 関数 `DashboardNode._on_mpc_state`

- 定義: `_on_mpc_state(self, msg: String)`
- 行範囲: L361-L362
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `str`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_mpc_state(self, msg: String):
        self._update('mpc_state', str(msg.data))
```

### L364 関数 `DashboardNode._on_health`

- 定義: `_on_health(self, msg: Float32)`
- 行範囲: L364-L365
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `_update`, `float`
- 読み取る主なインスタンス属性: `self._update`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
- 上から順の処理:
  1. self._update(...) を実行する。

代表コード断片:

```python
    def _on_health(self, msg: Float32):
        self._update('system_health', float(msg.data))
```

### L367 関数 `DashboardNode._on_gps`

- 定義: `_on_gps(self, msg: NavSatFix)`
- 行範囲: L367-L371
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `time`
- 読み取る主なインスタンス属性: `self._lock`, `self._state`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. with 文で self._lock を管理しながら処理する。
  2.   self._state['gps_lat'] に float(msg.latitude) の結果を代入する。
  3.   self._state['gps_lon'] に float(msg.longitude) の結果を代入する。
  4.   self._state['ts'] に time.time() の結果を代入する。

代表コード断片:

```python
    def _on_gps(self, msg: NavSatFix):
        with self._lock:
            self._state['gps_lat'] = float(msg.latitude)
            self._state['gps_lon'] = float(msg.longitude)
            self._state['ts'] = time.time()
```

### L373 関数 `DashboardNode._on_path`

- 定義: `_on_path(self, msg: Path)`
- 行範囲: L373-L377
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `len`, `time`
- 読み取る主なインスタンス属性: `self._lock`, `self._state`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. with 文で self._lock を管理しながら処理する。
  2.   self._state['path_points'] に len(msg.poses) の結果を代入する。
  3.   self._state['ts'] に time.time() の結果を代入する。

代表コード断片:

```python
    def _on_path(self, msg: Path):
        # Keep last path length as a simple sanity signal
        with self._lock:
            self._state['path_points'] = len(msg.poses)
            self._state['ts'] = time.time()
```

### L379 関数 `DashboardNode._init_dummy`

- 定義: `_init_dummy(self, path: str, rate_hz: float)`
- 行範囲: L379-L393
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `create_timer`, `error`, `get_logger`, `info`, `len`, `max`, `read_csv`, `to_dict`
- この呼出し内で代入する主なローカル名: `df`, `period`
- 読み取る主なインスタンス属性: `self._dummy_rows`, `self._tick_dummy`, `self.create_timer`, `self.get_logger`
- 更新する主なインスタンス属性: `self._dummy_idx`, `self._dummy_rows`, `self._dummy_timer`
- 制御構造の規模: 条件分岐 1、ループ 0、try 1
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 例外処理を伴う try ブロックを実行する。
  2.   Import 文を実行する。
  3.   df に pd.read_csv(path) の結果を代入する。
  4.   Exceptionを捕捉した場合:
  5.   self.get_logger().error(...) を実行する。
  6.    を返す。
  7. 条件 df.empty を判定し、真なら内部処理を行う。
  8.   self.get_logger().error(...) を実行する。
  9.    を返す。
  10. self._dummy_rows に df.to_dict(orient='records') の結果を代入する。
  11. self._dummy_idx に 0 の結果を代入する。
  12. period に 1.0 / max(rate_hz, 0.5) の結果を代入する。
  13. self._dummy_timer に self.create_timer(period, self._tick_dummy) の結果を代入する。
  14. self.get_logger().info(...) を実行する。

代表コード断片:

```python
    def _init_dummy(self, path: str, rate_hz: float):
        try:
            import pandas as pd
            df = pd.read_csv(path)
        except Exception as exc:
            self.get_logger().error(f'Failed to load dummy_csv: {exc}')
            return
        if df.empty:
            self.get_logger().error('dummy_csv is empty.')
            return
        self._dummy_rows = df.to_dict(orient='records')
        self._dummy_idx = 0
        period = 1.0 / max(rate_hz, 0.5)
        self._dummy_timer = self.create_timer(period, self._tick_dummy)
        self.get_logger().info(f'Dummy mode enabled: {path} ({len(self._dummy_rows)} rows)')
```

### L395 関数 `DashboardNode._tick_dummy`

- 定義: `_tick_dummy(self)`
- 行範囲: L395-L406
- 所属: `DashboardNode`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `hasattr`, `items`, `len`, `time`
- この呼出し内で代入する主なローカル名: `key`, `row`, `val`
- 読み取る主なインスタンス属性: `self._dummy_idx`, `self._dummy_rows`, `self._lock`, `self._state`
- 更新する主なインスタンス属性: `self._dummy_idx`
- 制御構造の規模: 条件分岐 1、ループ 1、try 1
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
  - try文は例外が起き得る処理と、異常時または終了時の経路を分ける。
- 上から順の処理:
  1. 条件 not hasattr(self, '_dummy_rows') or not self._dummy_rows を判定し、真なら内部処理を行う。
  2.    を返す。
  3. row に self._dummy_rows[self._dummy_idx] の結果を代入する。
  4. self._dummy_idx に (self._dummy_idx + 1) % len(self._dummy_rows) の結果を代入する。
  5. with 文で self._lock を管理しながら処理する。
  6.   row.items() を順に走査し、各要素を (key, val) に入れて処理する。
  7.     例外処理を伴う try ブロックを実行する。
  8.       self._state[key] に float(val) の結果を代入する。
  9.       Exceptionを捕捉した場合:
  10.       self._state[key] に val の結果を代入する。
  11.   self._state['ts'] に time.time() の結果を代入する。

代表コード断片:

```python
    def _tick_dummy(self):
        if not hasattr(self, '_dummy_rows') or not self._dummy_rows:
            return
        row = self._dummy_rows[self._dummy_idx]
        self._dummy_idx = (self._dummy_idx + 1) % len(self._dummy_rows)
        with self._lock:
            for key, val in row.items():
                try:
                    self._state[key] = float(val)
                except Exception:
                    self._state[key] = val
            self._state['ts'] = time.time()
```

### L409 関数 `main`

- 定義: `main()`
- 行範囲: L409-L414
- このブロックが直接呼ぶ主な関数/メソッド: `DashboardNode`, `destroy_node`, `init`, `shutdown`, `spin`
- この呼出し内で代入する主なローカル名: `node`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- 上から順の処理:
  1. rclpy.init(...) を実行する。
  2. node に DashboardNode() の結果を代入する。
  3. rclpy.spin(...) を実行する。
  4. node.destroy_node(...) を実行する。
  5. rclpy.shutdown(...) を実行する。

代表コード断片:

```python
def main():
    rclpy.init()
    node = DashboardNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
```


## パラメータ

- L58: `host` (default: `0.0.0.0`)
- L59: `port` (default: `8080`)
- L60: `static_dir`
- L61: `dummy_csv`
- L62: `dummy_rate_hz` (default: `5.0`)

## ROS topic I/O

- Subscription L117: `/planner/speed_cmd` -> `self._on_speed_cmd`
- Subscription L118: `/planner/upper_speed_cmd` -> `self._on_upper_speed_cmd`
- Subscription L119: `/vehicle/speed_kmh` -> `self._on_speed_meas`
- Subscription L120: `/planner/throttle_cmd_pct` -> `self._on_throttle_cmd`
- Subscription L121: `/planner/drive_mode` -> `self._on_drive_mode`
- Subscription L122: `/vehicle/batt_soc` -> `self._on_soc`
- Subscription L123: `/vehicle/batt_temp_c` -> `self._on_tb`
- Subscription L124: `/vehicle/batt_current_a` -> `self._on_ibatt`
- Subscription L125: `/vehicle/batt_voltage_v` -> `self._on_vbatt`
- Subscription L126: `/vehicle/s_km` -> `self._on_s_km`
- Subscription L127: `/planner/status` -> `self._on_status`
- Subscription L128: `/planner/env` -> `self._on_env`
- Subscription L129: `/planner/metrics` -> `self._on_metrics`
- Subscription L130: `/planner/upper_plan` -> `self._on_upper_plan`
- Subscription L131: `/planner/lower_plan` -> `self._on_lower_plan`
- Subscription L132: `/system/state` -> `self._on_sys_state`
- Subscription L133: `/system/diag` -> `self._on_sys_diag`
- Subscription L134: `/system/mpc_state` -> `self._on_mpc_state`
- Subscription L135: `/system/health` -> `self._on_health`
- Subscription L136: `/sim/gps` -> `self._on_gps`
- Subscription L137: `/planner/trajectory` -> `self._on_path`

## 処理の流れ

1. 初期化時に設定値や入力パスを読み込む。
2. publisher / subscription / timer を準備する。
3. timer callback 周期で主処理を進める。
