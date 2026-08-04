# ソーラーカーMPCプログラムを読むための基礎知識

- 生成日: 2026-07-29
- 対象: Python、OS、ROS 2、数値最適化、MPC、車両・電池モデル

この総論は、各プログラム解説で前提になる言葉を、プログラム経験を仮定せずに説明する。各個別PDFにも、そのファイルで必要な章を再掲する。

## プログラム、プロセス、メモリ、オブジェクトを区別する

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

## 名前、代入、型、参照

Pythonの代入文は、右辺を先に評価し、その結果のオブジェクトへ左辺の名前を結び付ける。`x = f()`では、まずfを呼び、その戻り値が得られてからxが更新される。

`float(...)`、`int(...)`、`bool(...)`は型名を呼び出して値を変換する。外部CSV、YAML、ROS parameterから来た値は型が期待どおりとは限らないため、このリポジトリでは明示変換が多い。

`None`は値が無いことを示す単一のオブジェクト、`math.nan`は浮動小数点値ではあるが有効な数値ではないことを示す。両者は用途が異なるため、`is None`と`math.isfinite`を使い分ける。

根拠資料:

- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

## 関数、引数、戻り値、スコープ

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

## class、独自クラス、インスタンス、self、継承

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

## 先頭アンダースコア、__init__、名前付けの作法

`self._step_solar`の先頭1個のアンダースコアは「クラス内部で使う実装詳細」という慣習であり、アクセスを強制禁止する機構ではない。外部コードから呼べるが、公開APIとして依存しない意思表示である。

`__init__`の前後2個のアンダースコアはPythonが定めた特殊メソッド名である。クラス生成時に自動で呼ばれる。任意の名前に前後2個を付けて独自仕様を作ることは避ける。

`_`で始まるローカル変数は、未使用または外部へ見せない意図を示す場合がある。例えば`_base_csv`は戻り値として受け取る必要はあるが、その後の処理では使わないことを読者へ示す。

根拠資料:

- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

## デコレータと@dataclass

`@名前`は、直後に定義した関数またはクラスを別の関数へ渡し、その結果で定義名を置き換えるデコレータ構文である。`@Class`という一般構文があるのではなく、`@dataclass`など実際のデコレータ名を書く。

`@dataclass`は型注釈付きフィールドから`__init__`、`__repr__`、比較処理などを自動生成する。物理パラメータや解析結果のように、名前付きデータを一まとまりで運ぶ用途に向く。

```python
from dataclasses import dataclass

@dataclass
class State:
    soc: float
    temperature_c: float

state = State(soc=0.8, temperature_c=30.0)
```

自動生成は検証を自動で保証しない。単位、許容範囲、相互依存制約は`__post_init__`や別の検証関数で確認する必要がある。

根拠資料:

- [Python公式ライブラリ: dataclasses](https://docs.python.org/3/library/dataclasses.html)
- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

## module、package、import、console_scripts

Pythonファイルはmoduleとして読み込める。複数moduleをディレクトリにまとめたものがpackageである。`from .model import SolarCarModel`の先頭の点は、現在と同じpackage内のmodel moduleを指す相対importである。

import時にはファイルのトップレベル文が上から一度実行される。`def`や`class`は関数・クラスを登録するが、その本体の通常処理は呼び出すまで走らない。

setuptoolsの`console_scripts`は、端末で使う実行可能名と`package.module:function`を対応付けるインストール時メタデータである。生成される実行用ラッパーはmoduleをimportし、指定関数を呼び、戻り値を終了コードとして扱う小さな入口である。

```text
ROS launchのexecutable名 -> install済みconsole script -> mpc_solarcar.mpc_nodeをimport -> main()を呼ぶ
```

根拠資料:

- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)
- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

## 例外、try/finally、with、資源解放

例外は通常の戻り値とは別経路で異常を呼出元へ伝える。`try/except`は想定した異常を処理し、`finally`は成功・失敗にかかわらず後始末を行う。

`with open(...) as f:`はcontext managerを使い、ブロックを出るとファイルを閉じる。CSVやログの破損を避けるため、開いた資源の所有者と閉じる場所を明確にする。

`except Exception: pass`はノードを止めない利点がある一方、入力異常を隠して原因追跡を難しくする。安全に関係する値では、少なくとも頻度制限付き警告、異常カウンタ、fallback状態のpublishを検討する。

## list、dict、deque、NumPy配列、pandas DataFrame

listは順序付き可変列、tupleは順序付きで通常変更しない列、dictはキーから値を引く対応表、dequeは両端追加・削除が効率的なキューである。どの構造を選ぶかはアクセス方法と更新方法で決まる。

NumPy配列は同種数値を連続的に扱い、要素ごとの演算、clip、補間、線形代数を簡潔に書く。shapeは各次元の要素数であり、速度系列なら通常`(N,)`、候補集団なら`(population, N)`となる。

pandas DataFrameは列名を持つ表である。CSV読込後は列型、欠損、単位、timezone、並び順、重複を明示的に処理しなければ、数値計算が動いても意味が誤る。

## CLI、PowerShell、Bash、環境変数、終了コード

CLIは端末からプログラム名と引数を渡す操作界面である。`argparse`は文字列として届く引数を名前、型、既定値、必須性に従って解析する。

PowerShellとBashは別のshellであり、変数記法、改行継続、引用、パス表記が異なる。このプロジェクトではWindows側のSolarSim.ps1がWSL側のsolar_control.shへ処理を渡す。

環境変数は親プロセスから子プロセスへ受け渡される名前付き文字列である。ROS_DOMAIN_ID、RMW_IMPLEMENTATION、Pythonの数値スレッド数などはコード外から動作を変えるため、実行記録へ残す必要がある。

終了コード0は一般に成功、0以外は失敗を示す。shellルータは子プロセスの終了コードを握り潰さず上位へ返すことで、自動運用が失敗を検知できる。

根拠資料:

- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)

## rclpy、rcl、rmw、DDS/RTPSの層

rclpyはPython利用者向けROS 2 client libraryである。利用者のNode、publisher、subscriptionなどをPython APIとして提供し、その下で共通C層のrclを利用する。

```text
本プロジェクトのPythonコード -> rclpy -> rcl -> rmw -> DDS/RTPS実装 -> ネットワークまたは同一PC内通信
```

rclは言語に依存しない共通ROS機能を提供するC API、rmwはROS 2と具体的middleware実装の境界である。DDS/RTPS側が探索、serialize、publish/subscribe、request/replyなどを担う。executorの実行モデルはrclだけで完結せずclient library側にも実装される。

根拠資料:

- [ROS 2 Humble公式: Internal ROS 2 interfaces](https://docs.ros.org/en/humble/Concepts/About-Internal-Interfaces.html)

## ROS graph、Node、topic、service、action、parameter

ROS graphは、実行中Nodeと、それらが持つpublisher、subscription、service、actionなどの接続関係である。Pythonクラス、プロセス、ROS graph上のNode名は関連するが同一物ではない。

topicは継続データ向けの非同期一方向publish/subscribe、serviceは短いrequest/response、actionは時間のかかる目標へfeedback、cancel、resultを持たせる。parameterはNodeごとの設定値である。

publisherが送った時点とsubscription callbackが実行される時点は同じとは限らない。通信遅延、QoS queue、executor待ちを挟むため、センサ値にはtimestampとfreshness判定が必要になる。

根拠資料:

- [ROS 2 Humble公式: Understanding nodes](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html)
- [ROS 2 Humble公式: Topics, Services, Actions](https://docs.ros.org/en/humble/Concepts/Basic/Interfaces-Topics-Services-Actions.html)
- [ROS 2 Humble公式: Parameters](https://docs.ros.org/en/humble/Concepts/Basic/About-Parameters.html)

## callback、timer、Executor、spin、Callback Group

callbackは、メッセージ受信、timer満了、service requestなどのイベントが成立した後でExecutorから呼ばれる関数である。登録時に`self._on_speed`と括弧なしで渡すのは、今実行せず後で呼ぶ関数オブジェクトを渡すためである。

Executorは実行可能になったcallbackを見つけ、Callback Groupの条件を確認して実行する。`spin()`は終了要求まで待機・dispatchを続けるため、通常運転中はmainの次の行へ戻らない。

MutuallyExclusiveCallbackGroupは同じgroup内のcallbackを同時実行させない。別group間はMultiThreadedExecutorで並行実行し得る。groupを分けただけでは共有属性への完全な排他にはならないため、複数groupが同じ状態を読む・書く場合は設計確認が必要である。

```text
DDS受信またはtimer満了 -> wait setでready -> Executorが選択 -> Callback Groupが許可 -> worker threadがcallback実行 -> 終了後Executorへ戻る
```

根拠資料:

- [ROS 2公式: Executors](https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Executors.html)
- [ROS 2 Humble公式: Internal ROS 2 interfaces](https://docs.ros.org/en/humble/Concepts/About-Internal-Interfaces.html)

## launch Action、Node Action、実行可能名、remapping

`launch_ros.actions.Node(...)`はrclpyのNode基底クラスではなく、指定したpackageのexecutableをプロセスとして起動するlaunch Actionである。

`DeclareLaunchArgument`はlaunch実行時に受け取る入力欄を宣言し、`LaunchConfiguration`はその値を後で解決するsubstitutionを表す。`perform(context)`は実行時contextから確定文字列を取り出す。

launchの`name`はNode名override、`parameters`は起動時parameter、`remappings`はNodeやtopicの既定名を別名へ対応付ける。launchはPythonファイルからmainという名前を推測せず、executableとしてインストールされたconsole scriptを起動する。

根拠資料:

- [ROS 2 Humble公式: Understanding nodes](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html)
- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)

## rqt_graph、ros2 CLI、rosbag2をいつ使うか

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

## 制御、状態、入力、モデル予測制御MPC

制御対象の内部を表す状態をx、操作入力をu、外乱・予報をwとすると、離散モデルは`x[k+1] = f(x[k], u[k], w[k])`と書ける。ソーラーカーではSoC、電池温度、距離、速度などが状態候補、速度目標や駆動トルクが入力候補になる。

$$
\min_{u_0,\ldots,u_{N-1}} \sum_{k=0}^{N-1}\ell(x_k,u_k,w_k)+V_f(x_N)
$$

MPCは現在状態からNステップ先まで予測し、目的関数と制約を満たす入力系列を求める。ただし実際に適用するのは通常先頭入力だけで、次回は新しい実測状態から再び解く。これがreceding horizonである。

予測モデル、目的関数、制約、ホライズン、solver、初期値のどれかが変わると答えも変わる。「MPCを使う」だけでは仕様は決まらず、これらを単位付きで追う必要がある。

根拠資料:

- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)

## 上位MPCと下位MPCの役割

上位層は長い距離または時間を見て、エネルギー、到着、停止、速度制限、終端SoCを考えた速度計画を出す。下位層は短い周期で実測速度を見て、上位速度へ追従する駆動・回生入力を求める。

```text
予報・route・SoC -> 上位MPC -> 将来速度列 -> 下位MPC -> throttle/回生/drive mode -> driverまたはvehicle -> 新しいtelemetry
```

上位解が遅い間も下位出力を止めないこと、古い計画を安全に保持すること、上位と下位で単位と時刻基準を一致させることが実装上重要である。

## 目的関数、制約、L-BFGS-B、SHGO、有限grid証明

数値最適化器は、利用者が与えた目的関数を複数の候補点で評価し、より小さい値を持つ候補を探す。solverが物理を理解するのではなく、物理と運用価値はcost関数へ書かれる。

L-BFGS-Bは変数ごとの上下限を扱える局所最適化法である。初期値の近くの谷へ収束し得るため、非凸問題では複数seedや大域探索と組み合わせる。successがFalseでも有限な候補が返る場合があるため、採用条件をコード側で決める。

SHGOは定めたsamplingと局所最適化を組み合わせる大域最適化法である。有限Cartesian gridの全列挙は、そのgrid上の最良を証明できるが、連続領域全体の最良を自動的に証明しない。資料ではこの証明範囲を区別する。

根拠資料:

- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)
- [SciPy公式: scipy.optimize.shgo](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.shgo.html)

## Cross-Entropy Methodを式と実装で理解する

CEMは候補を生成する確率分布を持ち、良かったelite候補から分布を更新する反復的な確率最適化である。このリポジトリのupper_solver.pyは各制御点速度を独立正規分布で生成し、上下限へclipする。

$$
u_i^{(j)} \sim \mathcal{N}(\mu_i^{(g)},(\sigma_i^{(g)})^2),\qquad u_i^{(j)}\leftarrow\operatorname{clip}(u_i^{(j)},l_i,h_i)
$$

$$
\mu_i^{(g+1)}=\frac{1}{K}\sum_{j\in\mathcal{E}_g}u_i^{(j)},\qquad \sigma_i^{(g+1)}=\max\left(\operatorname{Std}_{j\in\mathcal{E}_g}u_i^{(j)},0.05(h_i-l_i)\right)
$$

ここでE_gはcostが小さい上位K候補である。平均は良い領域へ移り、標準偏差は探索幅を表す。標準偏差の下限は探索が完全に潰れることを避ける。

現行hybrid_bounded_minimizeは、deterministic seedを評価し、上位候補をL-BFGS-Bで局所refineし、設定とseed間不一致に応じてCEMを実行し、最後に再度局所refineする。したがってCEM単独ではなくhybrid solverである。

CEMで落とした候補を永久保存しないこと自体は通常の最適化として自然だが、off-nominal状態からの再利用には別のpolicy library設計が必要である。状態を無制限に全組合せ保存する代わりに、SoC、進捗、時刻、予報誤差、停止状態などのscenarioを設計し、近傍policyを検索してMPCで再最適化する。

根拠資料:

- [Rubinstein and Kroese: The Cross-Entropy Method](https://link.springer.com/book/10.1007/978-1-4757-4321-0)
- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)

## warm startは何を保存し、どう効くか

warm startは前回またはoffline探索で得た入力系列を、次の最適化の初期候補として渡すことである。答えを固定するのではなく、探索開始点と候補libraryの一員を与える。

$$
u^{0,\mathrm{new}}_i=\operatorname{interp}\left(s_i^{\mathrm{new}};\,s_j^{\mathrm{old}},u_j^{\ast,\mathrm{old}}\right)
$$

距離基準計画では、現在より後ろの旧制御点を捨て、新しい絶対距離制御点へ補間してshiftする。初期状態や天候が変わればcost評価は新条件で行われるので、warm startが不適切でも他seed、CEM、安全fallbackが補う設計が必要である。

warm startの効き方は、局所法なら収束先と反復数、CEMなら初期meanまたは候補pool、receding horizonなら前回解の時間・距離shiftとして現れる。どの位置に渡しているかを呼出引数まで追う。

根拠資料:

- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)
- [Rubinstein and Kroese: The Cross-Entropy Method](https://link.springer.com/book/10.1007/978-1-4757-4321-0)

## 車両力学、電力収支、効率map

$$
F_{\mathrm{aero}}=\frac{1}{2}\rho C_dA(v+v_{\mathrm{wind}})^2,\quad F_{\mathrm{roll}}\approx mgC_{rr}\cos\theta,\quad F_{\mathrm{grade}}=mg\sin\theta
$$

車輪機械powerは概ね`P_mech = F_total * v + P_inertia`で、駆動時と回生時で異なる効率mapを通してDC側powerへ変換する。mapは速度・torqueなどを軸にした実測または同定tableであり、範囲外の補間・clip規則もモデルの一部である。

$$
P_{\mathrm{pack}}=P_{\mathrm{drive,dc}}-P_{\mathrm{regen,dc}}+P_{\mathrm{aux}}-P_{\mathrm{pv}}
$$

符号規約は必ずコードで確認する。本プロジェクトでは正のpack powerを放電側としてSoCを減らす処理が中心であり、発電と回生はpack負荷を下げる方向に働く。

## SoC、内部抵抗、端子電圧、温度、MHE

$$
V=V_{\mathrm{oc}}(z,T)-IR_{\mathrm{total}}(z,T,I),\qquad z_{k+1}=z_k-\frac{\eta(I,T)I\Delta t}{Q_{\mathrm{eff}}}
$$

SoCは直接完全には観測できないため、電流積算、OCV、端子電圧、温度、容量、効率を組み合わせる。内部抵抗はSoC、温度、電流方向で変わり、発熱と電圧制約の両方へ影響する。

MHEは有限時間窓の状態と観測誤差をまとめて最適化し、SoCや温度を推定する。古い測定や欠損値を同じ重みで使うと推定が壊れるため、timestamp freshnessと観測可用性を入口で確認する。

根拠資料:

- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)

## 天候、route、補間、時刻、単位

予報は時刻だけの系列か、時刻とroute距離の2次元gridになり得る。現在時刻tと距離sがgrid点の間なら、周囲の値から補間して日射、温度、風を求める。

UTC、現地timezone、naive datetimeを混ぜると数時間のずれが発生する。入力でtimezoneを確定し、内部比較はUTC、表示は現地時刻という役割分担が安全である。

route距離のkm、速度のkm/hとm/s、時間の秒、energyのWhとJを跨ぐため、変換係数3.6、3600、1000の意味を各式で確認する。

## freshness、filter、guard、fallback、fail-safe

分散システムでは最後に受け取った値が現在も有効とは限らない。受信時刻とtimeoutからfreshnessを判定し、stale値を計画状態へ無条件に同期しない。

filterはnoiseと一時的な飛び値を抑えるが、遅れを生む。slew limitは指令変化率を制限する。安全guardはsolverのcost罰則とは別に、現在出力へ強制制約を適用する最後の防波堤である。

fallbackは失敗時の代替動作を事前に決める設計である。前回計画保持、物理に基づく決定論的入力、停止、低速制限などから、故障modeごとに選ぶ。fallback発生はstatusとlogへ残し、正常解と区別する。

## CSV/YAMLのdata contractと検証

data contractは列名、型、単位、timezone、欠損可否、並び順、重複、許容範囲、先頭行、encodingを事前に決めた仕様である。単にCSVとして読めることは、モデル入力として正しいことを意味しない。

同定用実測、map、route、forecast、stop、scheduleはそれぞれgrainが異なる。生成時にschema validation、物理範囲、時間単調性、route範囲、coverageを検査し、検査結果をartifactとして残す。

学習用データと独立検証データを分離し、RMSEだけでなくbias、時系列残差、energy積算誤差、終端SoC、温度・電圧制約、外挿領域を評価する。

## 単体試験、SILS、replay、観測可能性

単体試験は関数やモデル項の局所契約、SILSは複数Nodeと時間進行を含む閉ループ、historical replayは実測入力への再現性、本番preflightは実機通信と停止動作を確認する。目的が異なるため一つで代用しない。

再現可能な診断には、入力、出力、内部状態、solver成否、候補数、計算時間、fallback、source revision、profile hashを同じrun IDで記録する。

非同期不具合は最終値だけでは追えない。topic周期、message age、callback所要時間、queue遅延、Node生存、publisher数を同時に観測する。

根拠資料:

- [ROS 2 Humble公式: rqt_graph](https://docs.ros.org/en/ros2_packages/humble/api/rqt_graph/index.html)
- [ROS 2 Humble公式: Recording and playing back data](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Recording-And-Playing-Back-Data/Recording-And-Playing-Back-Data.html)
- [ROS 2公式: Executors](https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Executors.html)
