#!/usr/bin/env python3
"""Curated beginner curriculum used by generate_program_reference_docs.py.

The generator obtains file names, line numbers, functions, calls, and ROS I/O
from the repository itself.  This module supplies the background explanations
that cannot be inferred safely from syntax alone.
"""

from __future__ import annotations


REFERENCE_SOURCES = {
    "python_classes": {
        "label": "Python公式チュートリアル: Classes",
        "url": "https://docs.python.org/3/tutorial/classes.html",
    },
    "python_dataclasses": {
        "label": "Python公式ライブラリ: dataclasses",
        "url": "https://docs.python.org/3/library/dataclasses.html",
    },
    "setuptools_entry_points": {
        "label": "setuptools公式: Entry Points / Console Scripts",
        "url": "https://setuptools.pypa.io/en/latest/userguide/entry_point.html",
    },
    "ros_nodes": {
        "label": "ROS 2 Humble公式: Understanding nodes",
        "url": "https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html",
    },
    "ros_interfaces": {
        "label": "ROS 2 Humble公式: Topics, Services, Actions",
        "url": "https://docs.ros.org/en/humble/Concepts/Basic/Interfaces-Topics-Services-Actions.html",
    },
    "ros_internal": {
        "label": "ROS 2 Humble公式: Internal ROS 2 interfaces",
        "url": "https://docs.ros.org/en/humble/Concepts/About-Internal-Interfaces.html",
    },
    "ros_parameters": {
        "label": "ROS 2 Humble公式: Parameters",
        "url": "https://docs.ros.org/en/humble/Concepts/Basic/About-Parameters.html",
    },
    "ros_executors": {
        "label": "ROS 2公式: Executors",
        "url": "https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Executors.html",
    },
    "ros_rqt_graph": {
        "label": "ROS 2 Humble公式: rqt_graph",
        "url": "https://docs.ros.org/en/ros2_packages/humble/api/rqt_graph/index.html",
    },
    "ros_bag": {
        "label": "ROS 2 Humble公式: Recording and playing back data",
        "url": "https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Recording-And-Playing-Back-Data/Recording-And-Playing-Back-Data.html",
    },
    "scipy_minimize": {
        "label": "SciPy公式: scipy.optimize.minimize",
        "url": "https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html",
    },
    "scipy_shgo": {
        "label": "SciPy公式: scipy.optimize.shgo",
        "url": "https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.shgo.html",
    },
    "cem_book": {
        "label": "Rubinstein and Kroese: The Cross-Entropy Method",
        "url": "https://link.springer.com/book/10.1007/978-1-4757-4321-0",
    },
}


FOUNDATION_CHAPTERS = [
    {
        "key": "program_process_memory",
        "title": "プログラム、プロセス、メモリ、オブジェクトを区別する",
        "items": [
            {
                "kind": "p",
                "text": "ソースファイルはディスク上の文字列であり、それ自体は走っていない。Python実行可能プログラムがソースを読み、OSがその実行を一つのプロセスとして管理する。プロセスには仮想メモリ、開いているファイル、スレッド、終了コードなどが対応する。",
            },
            {
                "kind": "flow",
                "text": "ソースファイル -> Pythonインタプリタが読み込む -> OS上のプロセス -> Pythonオブジェクトをメモリに生成 -> 関数やcallbackを実行",
            },
            {
                "kind": "p",
                "text": "「メモリ上に生成する」とは、実行中プロセスが使う記憶領域に、その値の型、属性、参照関係を表す実体を用意することである。変数は実体そのものというより、そのオブジェクトを指す名前として理解するとPythonの代入が読みやすい。",
            },
            {
                "kind": "code",
                "language": "python",
                "text": "node = MPCNode()\nalias = node\n# nodeとaliasは同じオブジェクトを参照する。",
            },
            {
                "kind": "p",
                "text": "一つのプロセスには複数スレッドを持たせられる。スレッドは同じプロセスのメモリを共有するため、受信callbackと最適化callbackが同じself.zを書き換える場合は実行順と排他を検討する必要がある。",
            },
        ],
        "sources": ["python_classes"],
    },
    {
        "key": "names_assignment_types",
        "title": "名前、代入、型、参照",
        "items": [
            {
                "kind": "p",
                "text": "Pythonの代入文は、右辺を先に評価し、その結果のオブジェクトへ左辺の名前を結び付ける。`x = f()`では、まずfを呼び、その戻り値が得られてからxが更新される。",
            },
            {
                "kind": "p",
                "text": "`float(...)`、`int(...)`、`bool(...)`は型名を呼び出して値を変換する。外部CSV、YAML、ROS parameterから来た値は型が期待どおりとは限らないため、このリポジトリでは明示変換が多い。",
            },
            {
                "kind": "p",
                "text": "`None`は値が無いことを示す単一のオブジェクト、`math.nan`は浮動小数点値ではあるが有効な数値ではないことを示す。両者は用途が異なるため、`is None`と`math.isfinite`を使い分ける。",
            },
        ],
        "sources": ["python_classes"],
    },
    {
        "key": "functions_arguments_scope",
        "title": "関数、引数、戻り値、スコープ",
        "items": [
            {
                "kind": "p",
                "text": "`def`は関数本体をその場で実行する文ではない。関数オブジェクトを作り、その名前を現在の名前空間へ登録する。`f`は関数そのもの、`f()`はその関数を呼んだ結果である。",
            },
            {
                "kind": "p",
                "text": "仮引数は関数定義側の受け取り名、実引数は呼出側から渡す値である。位置引数、キーワード引数、既定値付き引数、`*args`、`**kwargs`は渡し方が異なる。",
            },
            {
                "kind": "code",
                "language": "python",
                "text": "def clip_speed(value, minimum=0.0, maximum=110.0):\n    return min(maximum, max(minimum, value))\n\nv = clip_speed(120.0, maximum=90.0)",
            },
            {
                "kind": "p",
                "text": "関数内で作った通常の名前はローカルスコープに属する。メソッドが`self.z`を更新すればオブジェクトの状態が残るが、単に`z`を更新しただけならその呼出しのローカル値である。",
            },
        ],
        "sources": ["python_classes"],
    },
    {
        "key": "classes_objects_self",
        "title": "class、独自クラス、インスタンス、self、継承",
        "items": [
            {
                "kind": "p",
                "text": "クラスは、保持するデータと、そのデータを扱う関数を一つの型としてまとめる設計単位である。「独自クラス」とはPythonやROS 2が最初から用意した型ではなく、このプロジェクトが目的に合わせて定義した新しい型を指す。",
            },
            {
                "kind": "p",
                "text": "`class MPCNode(Node)`は、rclpyのNodeを基底クラスとして継承し、Nodeが持つpublisher、subscription、timer、parameterなどの機能にMPC固有機能を追加する。丸括弧内は関数引数ではなく基底クラス指定である。",
            },
            {
                "kind": "p",
                "text": "`MPCNode()`はクラスオブジェクトを呼び出して新しいインスタンスを作る。Pythonは新しい実体を用意し、その実体を第1引数selfとして`__init__`へ渡す。`self`は予約語ではなく慣習的な名前だが、この慣習を守ることでコードの意味が共有される。",
            },
            {
                "kind": "code",
                "language": "python",
                "text": "class Counter:\n    def __init__(self):\n        self.value = 0\n\n    def increment(self):\n        self.value += 1\n\ncounter = Counter()\ncounter.increment()",
            },
            {
                "kind": "p",
                "text": "`super().__init__(...)`は継承元の初期化処理を呼ぶ。MPCNodeではこれを省くとROSノードとして必要な内部実体が作られず、`create_publisher`などを正しく使えない。",
            },
        ],
        "sources": ["python_classes", "ros_nodes"],
    },
    {
        "key": "underscore_dunder",
        "title": "先頭アンダースコア、__init__、名前付けの作法",
        "items": [
            {
                "kind": "p",
                "text": "`self._step_solar`の先頭1個のアンダースコアは「クラス内部で使う実装詳細」という慣習であり、アクセスを強制禁止する機構ではない。外部コードから呼べるが、公開APIとして依存しない意思表示である。",
            },
            {
                "kind": "p",
                "text": "`__init__`の前後2個のアンダースコアはPythonが定めた特殊メソッド名である。クラス生成時に自動で呼ばれる。任意の名前に前後2個を付けて独自仕様を作ることは避ける。",
            },
            {
                "kind": "p",
                "text": "`_`で始まるローカル変数は、未使用または外部へ見せない意図を示す場合がある。例えば`_base_csv`は戻り値として受け取る必要はあるが、その後の処理では使わないことを読者へ示す。",
            },
        ],
        "sources": ["python_classes"],
    },
    {
        "key": "decorators_dataclass",
        "title": "デコレータと@dataclass",
        "items": [
            {
                "kind": "p",
                "text": "`@名前`は、直後に定義した関数またはクラスを別の関数へ渡し、その結果で定義名を置き換えるデコレータ構文である。`@Class`という一般構文があるのではなく、`@dataclass`など実際のデコレータ名を書く。",
            },
            {
                "kind": "p",
                "text": "`@dataclass`は型注釈付きフィールドから`__init__`、`__repr__`、比較処理などを自動生成する。物理パラメータや解析結果のように、名前付きデータを一まとまりで運ぶ用途に向く。",
            },
            {
                "kind": "code",
                "language": "python",
                "text": "from dataclasses import dataclass\n\n@dataclass\nclass State:\n    soc: float\n    temperature_c: float\n\nstate = State(soc=0.8, temperature_c=30.0)",
            },
            {
                "kind": "p",
                "text": "自動生成は検証を自動で保証しない。単位、許容範囲、相互依存制約は`__post_init__`や別の検証関数で確認する必要がある。",
            },
        ],
        "sources": ["python_dataclasses", "python_classes"],
    },
    {
        "key": "imports_packages_entrypoints",
        "title": "module、package、import、console_scripts",
        "items": [
            {
                "kind": "p",
                "text": "Pythonファイルはmoduleとして読み込める。複数moduleをディレクトリにまとめたものがpackageである。`from .model import SolarCarModel`の先頭の点は、現在と同じpackage内のmodel moduleを指す相対importである。",
            },
            {
                "kind": "p",
                "text": "import時にはファイルのトップレベル文が上から一度実行される。`def`や`class`は関数・クラスを登録するが、その本体の通常処理は呼び出すまで走らない。",
            },
            {
                "kind": "p",
                "text": "setuptoolsの`console_scripts`は、端末で使う実行可能名と`package.module:function`を対応付けるインストール時メタデータである。生成される実行用ラッパーはmoduleをimportし、指定関数を呼び、戻り値を終了コードとして扱う小さな入口である。",
            },
            {
                "kind": "flow",
                "text": "ROS launchのexecutable名 -> install済みconsole script -> mpc_solarcar.mpc_nodeをimport -> main()を呼ぶ",
            },
        ],
        "sources": ["setuptools_entry_points", "python_classes"],
    },
    {
        "key": "exceptions_context_resources",
        "title": "例外、try/finally、with、資源解放",
        "items": [
            {
                "kind": "p",
                "text": "例外は通常の戻り値とは別経路で異常を呼出元へ伝える。`try/except`は想定した異常を処理し、`finally`は成功・失敗にかかわらず後始末を行う。",
            },
            {
                "kind": "p",
                "text": "`with open(...) as f:`はcontext managerを使い、ブロックを出るとファイルを閉じる。CSVやログの破損を避けるため、開いた資源の所有者と閉じる場所を明確にする。",
            },
            {
                "kind": "p",
                "text": "`except Exception: pass`はノードを止めない利点がある一方、入力異常を隠して原因追跡を難しくする。安全に関係する値では、少なくとも頻度制限付き警告、異常カウンタ、fallback状態のpublishを検討する。",
            },
        ],
        "sources": [],
    },
    {
        "key": "collections_numpy_pandas",
        "title": "list、dict、deque、NumPy配列、pandas DataFrame",
        "items": [
            {
                "kind": "p",
                "text": "listは順序付き可変列、tupleは順序付きで通常変更しない列、dictはキーから値を引く対応表、dequeは両端追加・削除が効率的なキューである。どの構造を選ぶかはアクセス方法と更新方法で決まる。",
            },
            {
                "kind": "p",
                "text": "NumPy配列は同種数値を連続的に扱い、要素ごとの演算、clip、補間、線形代数を簡潔に書く。shapeは各次元の要素数であり、速度系列なら通常`(N,)`、候補集団なら`(population, N)`となる。",
            },
            {
                "kind": "p",
                "text": "pandas DataFrameは列名を持つ表である。CSV読込後は列型、欠損、単位、timezone、並び順、重複を明示的に処理しなければ、数値計算が動いても意味が誤る。",
            },
        ],
        "sources": [],
    },
    {
        "key": "cli_shell_environment",
        "title": "CLI、PowerShell、Bash、環境変数、終了コード",
        "items": [
            {
                "kind": "p",
                "text": "CLIは端末からプログラム名と引数を渡す操作界面である。`argparse`は文字列として届く引数を名前、型、既定値、必須性に従って解析する。",
            },
            {
                "kind": "p",
                "text": "PowerShellとBashは別のshellであり、変数記法、改行継続、引用、パス表記が異なる。このプロジェクトではWindows側のSolarSim.ps1がWSL側のsolar_control.shへ処理を渡す。",
            },
            {
                "kind": "p",
                "text": "環境変数は親プロセスから子プロセスへ受け渡される名前付き文字列である。ROS_DOMAIN_ID、RMW_IMPLEMENTATION、Pythonの数値スレッド数などはコード外から動作を変えるため、実行記録へ残す必要がある。",
            },
            {
                "kind": "p",
                "text": "終了コード0は一般に成功、0以外は失敗を示す。shellルータは子プロセスの終了コードを握り潰さず上位へ返すことで、自動運用が失敗を検知できる。",
            },
        ],
        "sources": ["setuptools_entry_points"],
    },
    {
        "key": "ros_stack",
        "title": "rclpy、rcl、rmw、DDS/RTPSの層",
        "items": [
            {
                "kind": "p",
                "text": "rclpyはPython利用者向けROS 2 client libraryである。利用者のNode、publisher、subscriptionなどをPython APIとして提供し、その下で共通C層のrclを利用する。",
            },
            {
                "kind": "flow",
                "text": "本プロジェクトのPythonコード -> rclpy -> rcl -> rmw -> DDS/RTPS実装 -> ネットワークまたは同一PC内通信",
            },
            {
                "kind": "p",
                "text": "rclは言語に依存しない共通ROS機能を提供するC API、rmwはROS 2と具体的middleware実装の境界である。DDS/RTPS側が探索、serialize、publish/subscribe、request/replyなどを担う。executorの実行モデルはrclだけで完結せずclient library側にも実装される。",
            },
        ],
        "sources": ["ros_internal"],
    },
    {
        "key": "ros_graph_interfaces",
        "title": "ROS graph、Node、topic、service、action、parameter",
        "items": [
            {
                "kind": "p",
                "text": "ROS graphは、実行中Nodeと、それらが持つpublisher、subscription、service、actionなどの接続関係である。Pythonクラス、プロセス、ROS graph上のNode名は関連するが同一物ではない。",
            },
            {
                "kind": "p",
                "text": "topicは継続データ向けの非同期一方向publish/subscribe、serviceは短いrequest/response、actionは時間のかかる目標へfeedback、cancel、resultを持たせる。parameterはNodeごとの設定値である。",
            },
            {
                "kind": "p",
                "text": "publisherが送った時点とsubscription callbackが実行される時点は同じとは限らない。通信遅延、QoS queue、executor待ちを挟むため、センサ値にはtimestampとfreshness判定が必要になる。",
            },
        ],
        "sources": ["ros_nodes", "ros_interfaces", "ros_parameters"],
    },
    {
        "key": "ros_executor_callbacks",
        "title": "callback、timer、Executor、spin、Callback Group",
        "items": [
            {
                "kind": "p",
                "text": "callbackは、メッセージ受信、timer満了、service requestなどのイベントが成立した後でExecutorから呼ばれる関数である。登録時に`self._on_speed`と括弧なしで渡すのは、今実行せず後で呼ぶ関数オブジェクトを渡すためである。",
            },
            {
                "kind": "p",
                "text": "Executorは実行可能になったcallbackを見つけ、Callback Groupの条件を確認して実行する。`spin()`は終了要求まで待機・dispatchを続けるため、通常運転中はmainの次の行へ戻らない。",
            },
            {
                "kind": "p",
                "text": "MutuallyExclusiveCallbackGroupは同じgroup内のcallbackを同時実行させない。別group間はMultiThreadedExecutorで並行実行し得る。groupを分けただけでは共有属性への完全な排他にはならないため、複数groupが同じ状態を読む・書く場合は設計確認が必要である。",
            },
            {
                "kind": "flow",
                "text": "DDS受信またはtimer満了 -> wait setでready -> Executorが選択 -> Callback Groupが許可 -> worker threadがcallback実行 -> 終了後Executorへ戻る",
            },
        ],
        "sources": ["ros_executors", "ros_internal"],
    },
    {
        "key": "ros_launch_runtime",
        "title": "launch Action、Node Action、実行可能名、remapping",
        "items": [
            {
                "kind": "p",
                "text": "`launch_ros.actions.Node(...)`はrclpyのNode基底クラスではなく、指定したpackageのexecutableをプロセスとして起動するlaunch Actionである。",
            },
            {
                "kind": "p",
                "text": "`DeclareLaunchArgument`はlaunch実行時に受け取る入力欄を宣言し、`LaunchConfiguration`はその値を後で解決するsubstitutionを表す。`perform(context)`は実行時contextから確定文字列を取り出す。",
            },
            {
                "kind": "p",
                "text": "launchの`name`はNode名override、`parameters`は起動時parameter、`remappings`はNodeやtopicの既定名を別名へ対応付ける。launchはPythonファイルからmainという名前を推測せず、executableとしてインストールされたconsole scriptを起動する。",
            },
        ],
        "sources": ["ros_nodes", "setuptools_entry_points"],
    },
    {
        "key": "ros_debug_tools",
        "title": "rqt_graph、ros2 CLI、rosbag2をいつ使うか",
        "items": [
            {
                "kind": "p",
                "text": "rqt_graphは接続関係を見る道具であり、数値の正しさや更新周期までは保証しない。起動直後、topic名変更後、publisherが複数存在する疑いがある時に使う。",
            },
            {
                "kind": "code",
                "language": "bash",
                "text": "ros2 node list\nros2 node info /mpc_node\nros2 topic list -t\nros2 topic info -v /planner/speed_cmd\nros2 topic hz /planner/speed_cmd\nros2 topic echo /planner/status\nrqt_graph",
            },
            {
                "kind": "p",
                "text": "rosbag2はtopicメッセージを時系列のまま記録・再生する。通信不具合、freshness、再計画trigger、実車とSILSの差を再現可能にするため、本番前試験では制御入力だけでなく原因となる全telemetry、status、parameter情報を記録する。",
            },
            {
                "kind": "code",
                "language": "bash",
                "text": "ros2 bag record -o outputs/bags/preflight \\\n  /vehicle/s_km /vehicle/speed_kmh /vehicle/batt_soc \\\n  /vehicle/batt_temp_c /vehicle/batt_current_a /vehicle/batt_voltage_v \\\n  /planner/upper_speed_cmd /planner/speed_cmd /planner/status\n\nros2 bag info outputs/bags/preflight\nros2 bag play outputs/bags/preflight --clock",
            },
            {
                "kind": "p",
                "text": "bag再生時はQoS互換性、simulation time、外部publisherとの二重入力に注意する。実車Nodeを同時に動かす場合はnamespaceまたはremappingで入力源を明確に分離する。",
            },
        ],
        "sources": ["ros_rqt_graph", "ros_bag", "ros_nodes"],
    },
    {
        "key": "control_mpc",
        "title": "制御、状態、入力、モデル予測制御MPC",
        "items": [
            {
                "kind": "p",
                "text": "制御対象の内部を表す状態をx、操作入力をu、外乱・予報をwとすると、離散モデルは`x[k+1] = f(x[k], u[k], w[k])`と書ける。ソーラーカーではSoC、電池温度、距離、速度などが状態候補、速度目標や駆動トルクが入力候補になる。",
            },
            {
                "kind": "equation",
                "text": r"\min_{u_0,\ldots,u_{N-1}} \sum_{k=0}^{N-1}\ell(x_k,u_k,w_k)+V_f(x_N)",
            },
            {
                "kind": "p",
                "text": "MPCは現在状態からNステップ先まで予測し、目的関数と制約を満たす入力系列を求める。ただし実際に適用するのは通常先頭入力だけで、次回は新しい実測状態から再び解く。これがreceding horizonである。",
            },
            {
                "kind": "p",
                "text": "予測モデル、目的関数、制約、ホライズン、solver、初期値のどれかが変わると答えも変わる。「MPCを使う」だけでは仕様は決まらず、これらを単位付きで追う必要がある。",
            },
        ],
        "sources": ["scipy_minimize"],
    },
    {
        "key": "hierarchical_mpc",
        "title": "上位MPCと下位MPCの役割",
        "items": [
            {
                "kind": "p",
                "text": "上位層は長い距離または時間を見て、エネルギー、到着、停止、速度制限、終端SoCを考えた速度計画を出す。下位層は短い周期で実測速度を見て、上位速度へ追従する駆動・回生入力を求める。",
            },
            {
                "kind": "flow",
                "text": "予報・route・SoC -> 上位MPC -> 将来速度列 -> 下位MPC -> throttle/回生/drive mode -> driverまたはvehicle -> 新しいtelemetry",
            },
            {
                "kind": "p",
                "text": "上位解が遅い間も下位出力を止めないこと、古い計画を安全に保持すること、上位と下位で単位と時刻基準を一致させることが実装上重要である。",
            },
        ],
        "sources": [],
    },
    {
        "key": "numerical_optimization",
        "title": "目的関数、制約、L-BFGS-B、SHGO、有限grid証明",
        "items": [
            {
                "kind": "p",
                "text": "数値最適化器は、利用者が与えた目的関数を複数の候補点で評価し、より小さい値を持つ候補を探す。solverが物理を理解するのではなく、物理と運用価値はcost関数へ書かれる。",
            },
            {
                "kind": "p",
                "text": "L-BFGS-Bは変数ごとの上下限を扱える局所最適化法である。初期値の近くの谷へ収束し得るため、非凸問題では複数seedや大域探索と組み合わせる。successがFalseでも有限な候補が返る場合があるため、採用条件をコード側で決める。",
            },
            {
                "kind": "p",
                "text": "SHGOは定めたsamplingと局所最適化を組み合わせる大域最適化法である。有限Cartesian gridの全列挙は、そのgrid上の最良を証明できるが、連続領域全体の最良を自動的に証明しない。資料ではこの証明範囲を区別する。",
            },
        ],
        "sources": ["scipy_minimize", "scipy_shgo"],
    },
    {
        "key": "cem",
        "title": "Cross-Entropy Methodを式と実装で理解する",
        "items": [
            {
                "kind": "p",
                "text": "CEMは候補を生成する確率分布を持ち、良かったelite候補から分布を更新する反復的な確率最適化である。このリポジトリのupper_solver.pyは各制御点速度を独立正規分布で生成し、上下限へclipする。",
            },
            {
                "kind": "equation",
                "text": r"u_i^{(j)} \sim \mathcal{N}(\mu_i^{(g)},(\sigma_i^{(g)})^2),\qquad u_i^{(j)}\leftarrow\operatorname{clip}(u_i^{(j)},l_i,h_i)",
            },
            {
                "kind": "equation",
                "text": r"\mu_i^{(g+1)}=\frac{1}{K}\sum_{j\in\mathcal{E}_g}u_i^{(j)},\qquad \sigma_i^{(g+1)}=\max\left(\operatorname{Std}_{j\in\mathcal{E}_g}u_i^{(j)},0.05(h_i-l_i)\right)",
            },
            {
                "kind": "p",
                "text": "ここでE_gはcostが小さい上位K候補である。平均は良い領域へ移り、標準偏差は探索幅を表す。標準偏差の下限は探索が完全に潰れることを避ける。",
            },
            {
                "kind": "p",
                "text": "現行hybrid_bounded_minimizeは、deterministic seedを評価し、上位候補をL-BFGS-Bで局所refineし、設定とseed間不一致に応じてCEMを実行し、最後に再度局所refineする。したがってCEM単独ではなくhybrid solverである。",
            },
            {
                "kind": "p",
                "text": "CEMで落とした候補を永久保存しないこと自体は通常の最適化として自然だが、off-nominal状態からの再利用には別のpolicy library設計が必要である。状態を無制限に全組合せ保存する代わりに、SoC、進捗、時刻、予報誤差、停止状態などのscenarioを設計し、近傍policyを検索してMPCで再最適化する。",
            },
        ],
        "sources": ["cem_book", "scipy_minimize"],
    },
    {
        "key": "warm_start",
        "title": "warm startは何を保存し、どう効くか",
        "items": [
            {
                "kind": "p",
                "text": "warm startは前回またはoffline探索で得た入力系列を、次の最適化の初期候補として渡すことである。答えを固定するのではなく、探索開始点と候補libraryの一員を与える。",
            },
            {
                "kind": "equation",
                "text": r"u^{0,\mathrm{new}}_i=\operatorname{interp}\left(s_i^{\mathrm{new}};\,s_j^{\mathrm{old}},u_j^{\ast,\mathrm{old}}\right)",
            },
            {
                "kind": "p",
                "text": "距離基準計画では、現在より後ろの旧制御点を捨て、新しい絶対距離制御点へ補間してshiftする。初期状態や天候が変わればcost評価は新条件で行われるので、warm startが不適切でも他seed、CEM、安全fallbackが補う設計が必要である。",
            },
            {
                "kind": "p",
                "text": "warm startの効き方は、局所法なら収束先と反復数、CEMなら初期meanまたは候補pool、receding horizonなら前回解の時間・距離shiftとして現れる。どの位置に渡しているかを呼出引数まで追う。",
            },
        ],
        "sources": ["scipy_minimize", "cem_book"],
    },
    {
        "key": "vehicle_energy_model",
        "title": "車両力学、電力収支、効率map",
        "items": [
            {
                "kind": "equation",
                "text": r"F_{\mathrm{aero}}=\frac{1}{2}\rho C_dA(v+v_{\mathrm{wind}})^2,\quad F_{\mathrm{roll}}\approx mgC_{rr}\cos\theta,\quad F_{\mathrm{grade}}=mg\sin\theta",
            },
            {
                "kind": "p",
                "text": "車輪機械powerは概ね`P_mech = F_total * v + P_inertia`で、駆動時と回生時で異なる効率mapを通してDC側powerへ変換する。mapは速度・torqueなどを軸にした実測または同定tableであり、範囲外の補間・clip規則もモデルの一部である。",
            },
            {
                "kind": "equation",
                "text": r"P_{\mathrm{pack}}=P_{\mathrm{drive,dc}}-P_{\mathrm{regen,dc}}+P_{\mathrm{aux}}-P_{\mathrm{pv}}",
            },
            {
                "kind": "p",
                "text": "符号規約は必ずコードで確認する。本プロジェクトでは正のpack powerを放電側としてSoCを減らす処理が中心であり、発電と回生はpack負荷を下げる方向に働く。",
            },
        ],
        "sources": [],
    },
    {
        "key": "battery_model_mhe",
        "title": "SoC、内部抵抗、端子電圧、温度、MHE",
        "items": [
            {
                "kind": "equation",
                "text": r"V=V_{\mathrm{oc}}(z,T)-IR_{\mathrm{total}}(z,T,I),\qquad z_{k+1}=z_k-\frac{\eta(I,T)I\Delta t}{Q_{\mathrm{eff}}}",
            },
            {
                "kind": "p",
                "text": "SoCは直接完全には観測できないため、電流積算、OCV、端子電圧、温度、容量、効率を組み合わせる。内部抵抗はSoC、温度、電流方向で変わり、発熱と電圧制約の両方へ影響する。",
            },
            {
                "kind": "p",
                "text": "MHEは有限時間窓の状態と観測誤差をまとめて最適化し、SoCや温度を推定する。古い測定や欠損値を同じ重みで使うと推定が壊れるため、timestamp freshnessと観測可用性を入口で確認する。",
            },
        ],
        "sources": ["scipy_minimize"],
    },
    {
        "key": "forecast_route_time",
        "title": "天候、route、補間、時刻、単位",
        "items": [
            {
                "kind": "p",
                "text": "予報は時刻だけの系列か、時刻とroute距離の2次元gridになり得る。現在時刻tと距離sがgrid点の間なら、周囲の値から補間して日射、温度、風を求める。",
            },
            {
                "kind": "p",
                "text": "UTC、現地timezone、naive datetimeを混ぜると数時間のずれが発生する。入力でtimezoneを確定し、内部比較はUTC、表示は現地時刻という役割分担が安全である。",
            },
            {
                "kind": "p",
                "text": "route距離のkm、速度のkm/hとm/s、時間の秒、energyのWhとJを跨ぐため、変換係数3.6、3600、1000の意味を各式で確認する。",
            },
        ],
        "sources": [],
    },
    {
        "key": "freshness_safety_fallback",
        "title": "freshness、filter、guard、fallback、fail-safe",
        "items": [
            {
                "kind": "p",
                "text": "分散システムでは最後に受け取った値が現在も有効とは限らない。受信時刻とtimeoutからfreshnessを判定し、stale値を計画状態へ無条件に同期しない。",
            },
            {
                "kind": "p",
                "text": "filterはnoiseと一時的な飛び値を抑えるが、遅れを生む。slew limitは指令変化率を制限する。安全guardはsolverのcost罰則とは別に、現在出力へ強制制約を適用する最後の防波堤である。",
            },
            {
                "kind": "p",
                "text": "fallbackは失敗時の代替動作を事前に決める設計である。前回計画保持、物理に基づく決定論的入力、停止、低速制限などから、故障modeごとに選ぶ。fallback発生はstatusとlogへ残し、正常解と区別する。",
            },
        ],
        "sources": [],
    },
    {
        "key": "data_contract_validation",
        "title": "CSV/YAMLのdata contractと検証",
        "items": [
            {
                "kind": "p",
                "text": "data contractは列名、型、単位、timezone、欠損可否、並び順、重複、許容範囲、先頭行、encodingを事前に決めた仕様である。単にCSVとして読めることは、モデル入力として正しいことを意味しない。",
            },
            {
                "kind": "p",
                "text": "同定用実測、map、route、forecast、stop、scheduleはそれぞれgrainが異なる。生成時にschema validation、物理範囲、時間単調性、route範囲、coverageを検査し、検査結果をartifactとして残す。",
            },
            {
                "kind": "p",
                "text": "学習用データと独立検証データを分離し、RMSEだけでなくbias、時系列残差、energy積算誤差、終端SoC、温度・電圧制約、外挿領域を評価する。",
            },
        ],
        "sources": [],
    },
    {
        "key": "testing_observability",
        "title": "単体試験、SILS、replay、観測可能性",
        "items": [
            {
                "kind": "p",
                "text": "単体試験は関数やモデル項の局所契約、SILSは複数Nodeと時間進行を含む閉ループ、historical replayは実測入力への再現性、本番preflightは実機通信と停止動作を確認する。目的が異なるため一つで代用しない。",
            },
            {
                "kind": "p",
                "text": "再現可能な診断には、入力、出力、内部状態、solver成否、候補数、計算時間、fallback、source revision、profile hashを同じrun IDで記録する。",
            },
            {
                "kind": "p",
                "text": "非同期不具合は最終値だけでは追えない。topic周期、message age、callback所要時間、queue遅延、Node生存、publisher数を同時に観測する。",
            },
        ],
        "sources": ["ros_rqt_graph", "ros_bag", "ros_executors"],
    },
]


CONCEPTS_BY_KEY = {chapter["key"]: chapter for chapter in FOUNDATION_CHAPTERS}


PROGRAM_EXTRA_CONCEPTS = {
    "SolarSim.ps1": [
        "program_process_memory",
        "cli_shell_environment",
        "ros_launch_runtime",
        "testing_observability",
    ],
    "scripts/solar_control.sh": [
        "program_process_memory",
        "cli_shell_environment",
        "ros_launch_runtime",
        "ros_debug_tools",
    ],
    "launch/solar_race_live_wifi.launch.py": [
        "classes_objects_self",
        "imports_packages_entrypoints",
        "ros_stack",
        "ros_graph_interfaces",
        "ros_launch_runtime",
        "ros_debug_tools",
    ],
    "launch/solar_race_live.launch.py": [
        "classes_objects_self",
        "imports_packages_entrypoints",
        "ros_launch_runtime",
    ],
    "launch/solarcar_sim.launch.py": [
        "ros_graph_interfaces",
        "ros_launch_runtime",
        "ros_debug_tools",
        "testing_observability",
    ],
    "launch/solar_measurement.launch.py": [
        "ros_graph_interfaces",
        "ros_launch_runtime",
        "ros_debug_tools",
    ],
    "mpc_solarcar/live_launch.py": [
        "functions_arguments_scope",
        "ros_graph_interfaces",
        "ros_launch_runtime",
    ],
    "mpc_solarcar/mpc_node.py": [
        "program_process_memory",
        "names_assignment_types",
        "functions_arguments_scope",
        "classes_objects_self",
        "underscore_dunder",
        "imports_packages_entrypoints",
        "exceptions_context_resources",
        "collections_numpy_pandas",
        "ros_stack",
        "ros_graph_interfaces",
        "ros_executor_callbacks",
        "ros_launch_runtime",
        "ros_debug_tools",
        "control_mpc",
        "hierarchical_mpc",
        "numerical_optimization",
        "cem",
        "warm_start",
        "vehicle_energy_model",
        "battery_model_mhe",
        "forecast_route_time",
        "freshness_safety_fallback",
        "testing_observability",
    ],
    "mpc_solarcar/model.py": [
        "decorators_dataclass",
        "vehicle_energy_model",
        "battery_model_mhe",
        "data_contract_validation",
    ],
    "mpc_solarcar/upper_solver.py": [
        "program_process_memory",
        "collections_numpy_pandas",
        "numerical_optimization",
        "cem",
        "warm_start",
        "testing_observability",
    ],
    "mpc_solarcar/upper_policy.py": ["warm_start", "collections_numpy_pandas"],
    "mpc_solarcar/upper_horizon.py": ["control_mpc", "forecast_route_time"],
    "mpc_solarcar/upper_cost.py": [
        "control_mpc",
        "numerical_optimization",
        "vehicle_energy_model",
    ],
    "mpc_solarcar/estimator.py": [
        "battery_model_mhe",
        "numerical_optimization",
        "freshness_safety_fallback",
    ],
    "scripts/solar_sim.py": [
        "control_mpc",
        "hierarchical_mpc",
        "numerical_optimization",
        "cem",
        "warm_start",
        "vehicle_energy_model",
        "battery_model_mhe",
        "forecast_route_time",
        "data_contract_validation",
        "testing_observability",
    ],
    "scripts/gpu_upper_policy_search.py": [
        "program_process_memory",
        "control_mpc",
        "cem",
        "warm_start",
        "testing_observability",
    ],
    "scripts/run_upper_mesh_convergence.py": [
        "numerical_optimization",
        "testing_observability",
        "data_contract_validation",
    ],
    "scripts/validate_gpu_upper_policy_candidates.py": [
        "numerical_optimization",
        "testing_observability",
        "data_contract_validation",
    ],
}


MPC_NODE_DEEP_DIVE = [
    {
        "title": "起動経路を大本から一本につなぐ",
        "items": [
            {
                "kind": "flow",
                "text": "SolarSim.ps1 -> scripts/solar_control.sh -> ROS 2 launch -> launch_ros.actions.Node -> setup.pyのconsole_scripts -> mpc_solarcar.mpc_node:main -> rclpy.init -> MPCNode() -> __init__ -> _init_solar -> Executor.add_node -> spin",
            },
            {
                "kind": "p",
                "text": "この対応は推測ではない。setup.pyのconsole_scriptsには`mpc_node = mpc_solarcar.mpc_node:main`が登録され、live_launch.pyとsolarcar_sim.launch.pyはexecutableとしてmpc_nodeを指定する。launchがmainという名前を探索するのではない。",
            },
            {
                "kind": "p",
                "text": "launch側のNodeはプロセス起動指示、rclpy.node.Nodeは基底クラス、MPCNodeはこのリポジトリが定義した派生クラス、`node = MPCNode()`のnodeは実行中メモリに作られたインスタンス、`/mpc_node`はROS graph上の名前である。",
            },
        ],
    },
    {
        "title": "mainとspinの前後で実行方式が変わる",
        "items": [
            {
                "kind": "code",
                "language": "python",
                "text": "def main():\n    rclpy.init()\n    node = MPCNode()\n    executor = MultiThreadedExecutor(num_threads=4)\n    executor.add_node(node)\n    try:\n        executor.spin()\n    finally:\n        executor.shutdown()\n        node.destroy_node()\n        rclpy.shutdown()",
            },
            {
                "kind": "p",
                "text": "spinまでは通常のPythonとして上から一度だけ進む。spin後はExecutorのevent loopへ入り、timerと受信がreadyになった時にcallbackが呼ばれる。callback終了後はmainの次行ではなくExecutorへ戻る。",
            },
            {
                "kind": "p",
                "text": "finallyはCtrl+C、launch停止、例外などでspinを抜けた後の後始末である。Executor、Node、rclpy contextの順に明示終了する。",
            },
        ],
    },
    {
        "title": "MPCNode.__init__とselfの正確な意味",
        "items": [
            {
                "kind": "p",
                "text": "`MPCNode()`を評価すると、新しいインスタンスが作られ、その参照がselfとして`MPCNode.__init__`へ入る。`super().__init__('mpc_node')`が基底Nodeを初期化して初めてROS Node機能を持つ。",
            },
            {
                "kind": "p",
                "text": "`self.z`、`self.Tb`、`self.model`は同じMPCNodeインスタンスに保存される状態である。callbackが別時刻に呼ばれても同じ属性を参照する。`z`のような局所変数はその関数呼出し内だけである。",
            },
            {
                "kind": "p",
                "text": "先頭アンダースコア付きメソッドは内部実装という慣習、`__init__`はPython特殊メソッドである。`@Class`という一般構文はなく、このファイルのMPCNode自体にはdataclass decoratorは使われていない。",
            },
        ],
    },
    {
        "title": "四つのCallback Groupと共有状態",
        "items": [
            {
                "kind": "p",
                "text": "telemetry、upper、lower、commandの四つを別MutuallyExclusiveCallbackGroupへ置く。同じgroup内は同時実行しないが、別groupは四workerで並行実行し得る。長い上位solve中にもtelemetry受信と下位出力を続ける意図である。",
            },
            {
                "kind": "p",
                "text": "別groupはself.z、self.Tb、self.v_now、self.last_dataなどを共有する。コードは上位solve後に`_sync_measured_state()`を再実行して長時間solve中に受けた最新値を反映するが、明示lockですべてを原子的snapshot化しているわけではない。",
            },
            {
                "kind": "p",
                "text": "PythonのGILは複数文にまたがる状態整合性を保証しない。診断時はcallback開始終了時刻、plan ID、telemetry timestampを併記し、どの状態snapshotで解いたか確認する。",
            },
        ],
    },
    {
        "title": "時間基準上位MPC",
        "items": [
            {
                "kind": "p",
                "text": "`_mpc_solve_solar(data)`は将来速度列を最適化変数とし、各予測stepで慣性power、electrical balance、SoC、温度、距離、制約penaltyを順に計算する。",
            },
            {
                "kind": "equation",
                "text": r"P_{\mathrm{inertia},k}=\frac{\frac12m(v_k^2-v_{k-1}^2)}{\Delta t},\quad s_{k+1}=s_k+\frac{v_k\Delta t}{1000}",
            },
            {
                "kind": "p",
                "text": "`model.electrical_balance`が電流、電圧、pack power、損失を返し、`model.soc_step`がSoCを進める。温度更新とcost蓄積は呼出側にもある。最後にSciPy L-BFGS-Bへcost、初期値、boundsを渡す。",
            },
        ],
    },
    {
        "title": "距離基準上位MPCとCEM",
        "items": [
            {
                "kind": "p",
                "text": "`_mpc_solve_solar_distance`はrouteを距離区間へ分け、制御点速度uを区間速度へ線形補間する。停止座標をmesh edgeへ追加し、到着、dwell発電、再出発を同じ座標で評価する。",
            },
            {
                "kind": "p",
                "text": "初期候補は、前回planの距離shift、offline initial policyの補間、現在速度一定の順で選ぶ。別途balance seedを作り、`hybrid_bounded_minimize`へ渡す。",
            },
            {
                "kind": "p",
                "text": "solverはseed評価、上位seedのL-BFGS-B、条件付きCEM、再L-BFGS-Bを行う。CEMの各世代ではmean候補を1個必ず含め、残りを正規乱数で生成し、elite平均と標準偏差で次世代分布を更新する。",
            },
            {
                "kind": "p",
                "text": "finite grid全列挙の証明は宣言grid上に限る。CEMや局所候補を含む連続領域の大域最適性を意味しないため、solve_infoの`discrete_global_proof`、`finite_library_global_proof`、`certificate_scope`を区別する。",
            },
        ],
    },
    {
        "title": "warm startとoff-nominal状態",
        "items": [
            {
                "kind": "p",
                "text": "前回速度列を新しい絶対距離制御点へ補間するため、予定より遅い・速い場合でも過去区間を除いた残り計画を初期値にできる。これはplanを固定せず、現在SoC、温度、天候でcostを再評価する。",
            },
            {
                "kind": "p",
                "text": "offline CEMで理想軌道だけを残すと大きな逸脱時のseed品質は落ちる。対策は全連続状態の全組合せ保存ではなく、SoC偏差、進捗偏差、時刻、予報scale、停止継続、温度などのscenario libraryを設計し、近傍policyとphysics seedを併用してlive MPCで修正することである。",
            },
            {
                "kind": "p",
                "text": "この現行ノードは前回plan、initial_upper_policy、balance seed、generic seed、CEMを併用するが、多次元scenario library検索を完全実装したものではない。この境界を資料上で保証と将来拡張に分ける。",
            },
        ],
    },
    {
        "title": "下位MPCと指令継続",
        "items": [
            {
                "kind": "p",
                "text": "`_build_lower_ref`が上位planから短期参照速度列を作り、`_lower_mpc_solve`が駆動・回生入力uを求める。逆動力学seedを必ず作り、設定した場合だけL-BFGS-Bでrefineする。",
            },
            {
                "kind": "p",
                "text": "上位solve中はoptionにより下位refineを省略し、決定論的入力を使う。`_publish_lower_command_cycle`は独立timerから保存済み指令を出すため、optimizer完了を待たず出力を継続する。",
            },
            {
                "kind": "p",
                "text": "ただしdocstringは`1 Hz output path`と書く一方、実際のtimer周期は`1/lower_rate_hz`で、既定lower_rate_hzが5なら5 Hzである。説明では実装値を正とし、この不一致を既知の文書上問題として記す。",
            },
        ],
    },
    {
        "title": "実測同期、freshness、MHE、fallback",
        "items": [
            {
                "kind": "p",
                "text": "各telemetry callbackは受信時刻とfilter済み値を保存する。`_sync_measured_state`はtimeout内の値だけを状態へ反映し、古い速度はNaNに戻す。距離には大きな後退値を捨てるguardがある。",
            },
            {
                "kind": "p",
                "text": "MHE有効時は観測可能なSoC、温度、電流、電圧を窓へpushして状態を推定する。無効時は車両モデルで状態を進めるが、新鮮なSoCまたは温度実測がある項目はモデル上書きを避ける。",
            },
            {
                "kind": "p",
                "text": "solver失敗時はwarm-start planまたは決定論的入力へfallbackする。さらにschedule、速度制限、SoC guard、control stop holdをoptimizer後段で強制するため、soft penaltyだけに安全を依存しない。",
            },
        ],
    },
    {
        "title": "実機で使う診断順",
        "items": [
            {
                "kind": "code",
                "language": "bash",
                "text": "ros2 node list\nros2 node info /mpc_node\nros2 topic info -v /vehicle/speed_kmh\nros2 topic info -v /planner/speed_cmd\nros2 topic hz /vehicle/speed_kmh\nros2 topic hz /planner/speed_cmd\nros2 topic echo /planner/status\nrqt_graph",
            },
            {
                "kind": "p",
                "text": "Nodeが無い場合はlaunch・console script・process、topicが無い場合はpublisher、周期が遅い場合は通信またはExecutor、値が古い場合はtimestamp/freshness、指令が0ならschedule/stop/SoC guard、solver失敗ならstatusとlog、という順で範囲を狭める。",
            },
            {
                "kind": "p",
                "text": "空転試験では距離を進めない入力sourceを使い、実GPSとreplay publisherを同時に接続しない。bagへtelemetry、upper/lower指令、statusを同時記録し、停止後に同じprofileとsource revisionで再生する。",
            },
        ],
    },
    {
        "title": "現行改修の設計意図と残る注意点",
        "items": [
            {
                "kind": "p",
                "text": "現行コードのコメントと差分から、長時間full-race solve中の応答維持、2次元forecast補間、実測freshness、runtime profile override、offline policy warm start、control stopの正確なmesh分割、決定論的lower fallback、solve時間logを目的とした改修を確認できる。",
            },
            {
                "kind": "p",
                "text": "一方、異なるCallback Group間の共有状態snapshot、広い`except Exception`、commandの二経路publish、1 Hzというdocstringと実timerの不一致は、利用者が挙動を理解するうえで注意が必要である。これらは機能説明と保証範囲を分けて記載する。",
            },
            {
                "kind": "p",
                "text": "Git index上ではmpc_node.pyが競合未解決状態であるため、本資料は2026-07-29時点のワークツリー内容を根拠とし、merge完了後はmanifestのsource hashを更新して再生成する必要がある。",
            },
        ],
    },
]

