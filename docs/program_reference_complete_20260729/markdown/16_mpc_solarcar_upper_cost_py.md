# 16. 上位MPC 目的関数

- ファイル: `mpc_solarcar/upper_cost.py`
- ソースSHA-256: `b69065249298ad089d085bcb06d9277c10dae6b61ec0d334d69a13ffef56a3bb`
- 種別: `Python`
- 区分: `planner helper`

## 役割

速度、SoC、温度、電流、進捗、day-end、terminal 条件を penalty として定義する。

## 起動文脈

- 起動文脈: upper planner の良し悪しを数式化する場所。
- 呼び出し元: `mpc_node.py`, `scripts/solar_sim.py`, `tune_upper_planner_weights.py`
- 次に読むべきファイル: `scripts/tune_upper_planner_weights.py`

## 主要ポイント

- upper_stage_cost と upper_terminal_cost が中心。
- load_upper_cost_config が profile の重み束を解く。

## 主要構造

主要クラスは UpperCostConfig。 主要関数は to_dict, load_upper_cost_config, pick, quad_penalty, upper_stage_cost, upper_terminal_cost, active_upper_cost_terms。

## ファイルを上から読んだときの定義順

- L8: クラス UpperCostConfig を定義する。
- L48: 関数 _cfg_value を定義する。
- L54: 関数 load_upper_cost_config を定義する。
- L110: 関数 quad_penalty を定義する。
- L118: 関数 upper_stage_cost を定義する。
- L263: 関数 upper_terminal_cost を定義する。
- L283: 関数 active_upper_cost_terms を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from dataclasses import asdict, dataclass`
  - dataclasses から asdict, dataclass を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L7, L45。
- L4: `from typing import Any, Dict, Optional`
  - typing から Any, Dict, Optional を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L44, L48, L55, L57, L126, L132, L145, L148, ...。

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

### デコレータと@dataclass

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

### 制御、状態、入力、モデル予測制御MPC

制御対象の内部を表す状態をx、操作入力をu、外乱・予報をwとすると、離散モデルは`x[k+1] = f(x[k], u[k], w[k])`と書ける。ソーラーカーではSoC、電池温度、距離、速度などが状態候補、速度目標や駆動トルクが入力候補になる。

$$
\min_{u_0,\ldots,u_{N-1}} \sum_{k=0}^{N-1}\ell(x_k,u_k,w_k)+V_f(x_N)
$$

MPCは現在状態からNステップ先まで予測し、目的関数と制約を満たす入力系列を求める。ただし実際に適用するのは通常先頭入力だけで、次回は新しい実測状態から再び解く。これがreceding horizonである。

予測モデル、目的関数、制約、ホライズン、solver、初期値のどれかが変わると答えも変わる。「MPCを使う」だけでは仕様は決まらず、これらを単位付きで追う必要がある。

根拠資料:

- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)

### 目的関数、制約、L-BFGS-B、SHGO、有限grid証明

数値最適化器は、利用者が与えた目的関数を複数の候補点で評価し、より小さい値を持つ候補を探す。solverが物理を理解するのではなく、物理と運用価値はcost関数へ書かれる。

L-BFGS-Bは変数ごとの上下限を扱える局所最適化法である。初期値の近くの谷へ収束し得るため、非凸問題では複数seedや大域探索と組み合わせる。successがFalseでも有限な候補が返る場合があるため、採用条件をコード側で決める。

SHGOは定めたsamplingと局所最適化を組み合わせる大域最適化法である。有限Cartesian gridの全列挙は、そのgrid上の最良を証明できるが、連続領域全体の最良を自動的に証明しない。資料ではこの証明範囲を区別する。

根拠資料:

- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)
- [SciPy公式: scipy.optimize.shgo](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.shgo.html)

### 車両力学、電力収支、効率map

$$
F_{\mathrm{aero}}=\frac{1}{2}\rho C_dA(v+v_{\mathrm{wind}})^2,\quad F_{\mathrm{roll}}\approx mgC_{rr}\cos\theta,\quad F_{\mathrm{grade}}=mg\sin\theta
$$

車輪機械powerは概ね`P_mech = F_total * v + P_inertia`で、駆動時と回生時で異なる効率mapを通してDC側powerへ変換する。mapは速度・torqueなどを軸にした実測または同定tableであり、範囲外の補間・clip規則もモデルの一部である。

$$
P_{\mathrm{pack}}=P_{\mathrm{drive,dc}}-P_{\mathrm{regen,dc}}+P_{\mathrm{aux}}-P_{\mathrm{pv}}
$$

符号規約は必ずコードで確認する。本プロジェクトでは正のpack powerを放電側としてSoCを減らす処理が中心であり、発電と回生はpack負荷を下げる方向に働く。


## 関数・クラスを上から順に解説

### L8 クラス `UpperCostConfig`

- 定義: `UpperCostConfig(bases=none)`
- 行範囲: L8-L45
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - class文は新しい型を定義する。丸括弧内は継承する基底クラスである。
  - @で始まる行は、定義したクラスを加工するdecoratorである。
- 上から順の処理:
  1. objective_mode に 'weighted' を代入する。
  2. w_wait に 1.0 を代入する。
  3. w_travel_time に 1.0 を代入する。
  4. w_terminal_soc_min に 30.0 を代入する。
  5. w_day_end_soc_min に 100000.0 を代入する。
  6. w_soc_day_max に 10000.0 を代入する。
  7. w_soc_day_track に 0.0 を代入する。
  8. w_speed_smooth に 30.0 を代入する。
  9. w_dv_limit に 2.0 を代入する。
  10. w_speed_limit に 50.0 を代入する。
  11. w_drive_window に 100000.0 を代入する。
  12. w_current_sq に 0.01 を代入する。

代表コード断片:

```python
class UpperCostConfig:
    objective_mode: str = "weighted"
    w_wait: float = 1.0
    w_travel_time: float = 1.0
    w_terminal_soc_min: float = 30.0
    w_day_end_soc_min: float = 1.0e5
    w_soc_day_max: float = 1.0e4
    w_soc_day_track: float = 0.0
    w_speed_smooth: float = 30.0
    w_dv_limit: float = 2.0
    w_speed_limit: float = 50.0
    w_drive_window: float = 1.0e5
    w_current_sq: float = 0.01
    w_pack_energy: float = 0.0
    w_joule_loss: float = 0.0
    w_aero_energy: float = 0.0
    w_mech_energy: float = 0.0
    w_speed_quartic: float = 0.0
    w_solar_headroom: float = 0.0
    w_progress_lag: float = 0.0
    w_progress_terminal_lag: float = 0.0
    w_kinetic_pos: float = 0.0
    w_pack_power_slew: float = 0.0
    w_temp: float = 5.0
    w_soc_terminal: float = 0.0
    w_soc_floor_barrier: float = 0.0
    w_uncertainty_reserve: float = 0.0
    speed_quartic_scale_kmh: float = 80.0
    progress_lag_deadband_km: float = 0.0
    soc_solar_headroom_max: float = 0.92
    solar_headroom_power_scale_w: float = 1000.0
    soc_floor_barrier_eps: float = 0.01
    reserve_soc_per_hour: float = 0.0
    reserve_soc_max_extra: float = 0.0
    constraint_penalty: float = 1.0e4
...
```

### L44 関数 `UpperCostConfig.to_dict`

- 定義: `to_dict(self) -> Dict[str, Any]`
- 行範囲: L44-L45
- 所属: `UpperCostConfig`
- このブロックが直接呼ぶ主な関数/メソッド: `asdict`
- 戻り値の要点: `asdict(self)`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - 第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. asdict(self) を返す。

代表コード断片:

```python
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

### L48 関数 `_cfg_value`

- 定義: `_cfg_value(cfg: Optional[dict], key: str, default)`
- 行範囲: L48-L51
- このブロックが直接呼ぶ主な関数/メソッド: `isinstance`
- 戻り値の要点: `default / cfg[key]`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- 上から順の処理:
  1. 条件 isinstance(cfg, dict) and key in cfg を判定し、真なら内部処理を行う。
  2.   cfg[key] を返す。
  3. default を返す。

代表コード断片:

```python
def _cfg_value(cfg: Optional[dict], key: str, default):
    if isinstance(cfg, dict) and key in cfg:
        return cfg[key]
    return default
```

### L54 関数 `load_upper_cost_config`

- 定義: `load_upper_cost_config(mpc_cfg: Optional[dict], *, legacy: Optional[dict] = None, default_drive_window: float = 100000.0) -> UpperCostConfig`
- 行範囲: L54-L107
- このブロックが直接呼ぶ主な関数/メソッド: `UpperCostConfig`, `_cfg_value`, `float`, `get`, `isinstance`, `lower`, `pick`, `str`, `strip`
- 戻り値の要点: `UpperCostConfig(objective_mode=str(pick('objective_mode', 'weighted')).strip().lower(), w_wait=float(pick('w_wait', 1.0)), w_travel_time=float(pick('w_travel_time', 1.0)), w_terminal_soc_min=float(pick('w_terminal_soc_min', 30.0)), w_day_end_soc_min=float(pick('w_day_end_soc_min', default_drive_window)), w_soc_day_max=float(pick('w_soc_day_max', 10000.0)), w_soc_day_track=float(pick('w_soc_day_track', 0.0)), w_speed_smooth=float(pick('w_speed_smooth', _cfg_value(legacy, 'w_dv', 30.0))), w_dv_limit=float(pick('w_dv_limit', 2.0)), w_speed_limit=float(pick('w_speed_limit', 50.0)), w_drive_window=float(pick('w_drive_window', default_drive_window)), w_current_sq=float(pick('w_current_sq', _cfg_value(legacy, 'w_current', 0.01))), w_pack_energy=float(pick('w_pack_energy', 0.0)), w_joule_loss=float(pick('w_joule_loss', 0.0)), w_aero_energy=float(pick('w_aero_energy', 0.0)), w_mech_energy=float(pick('w_mech_energy', 0.0)), w_speed_quartic=float(pick('w_speed_quartic', 0.0)), w_solar_headroom=float(pick('w_solar_headroom', 0.0)), w_progress_lag=float(pick('w_progress_lag', 0.0)), w_progress_terminal_lag=float(pick('w_progress_terminal_lag', 0.0)), w_kinetic_pos=float(pick('w_kinetic_pos', 0.0)), w_pack_power_slew=float(pick('w_pack_power_slew', 0.0)), w_temp=float(pick('w_temp', _cfg_value(legacy, 'w_T', 5.0))), w_soc_terminal=float(pick('w_soc_terminal', 0.0)), w_soc_floor_barrier=float(pick('w_soc_floor_barrier', 0.0)), w_uncertainty_reserve=float(pick('w_uncertainty_reserve', 0.0)), speed_quartic_scale_kmh=float(pick('speed_quartic_scale_kmh', 80.0)), progress_lag_deadband_km=float(pick('progress_lag_deadband_km', 0.0)), soc_solar_headroom_max=float(pick('soc_solar_headroom_max', 0.92)), solar_headroom_power_scale_w=float(pick('solar_headroom_power_scale_w', 1000.0)), soc_floor_barrier_eps=float(pick('soc_floor_barrier_eps', 0.01)), reserve_soc_per_hour=float(pick('reserve_soc_per_hour', 0.0)), reserve_soc_max_extra=float(pick('reserve_soc_max_extra', 0.0)), constraint_penalty=float(pick('constraint_penalty', 10000.0))) / default / nested[name] / legacy[name]`
- この呼出し内で代入する主なローカル名: `legacy`, `nested`
- 制御構造の規模: 条件分岐 3、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. legacy に legacy or {} の結果を代入する。
  2. nested に {} の結果を代入する。
  3. 条件 isinstance(mpc_cfg, dict) を判定し、真なら内部処理を行う。
  4.   nested に mpc_cfg.get('upper_cost', {}) or {} の結果を代入する。
  5. 関数 pick を定義する。
  6. UpperCostConfig(objective_mode=str(pick('objective_mode', 'weighted')).strip().lower(), w_wait=float(pick('w_wait', 1.0)), w_travel_time=float(pick('w_travel_time', 1.0)), w_terminal_soc_min=float(pick('w_terminal_soc_min', 30.0)), w_day_end_soc_min=float(pick('w_day_end_soc_min', default_drive_window)), w_soc_day_max=float(pick('w_soc_day_max', 10000.0)), w_soc_day_track=float(pick('w_soc_day_track', 0.0)), w_speed_smooth=float(pick('w_speed_smooth', _cfg_value(legacy, 'w_dv', 30.0))), w_dv_limit=float(pick('w_dv_limit', 2.0)), w_speed_limit=float(pick('w_speed_limit', 50.0)), w_drive_window=float(pick('w_drive_window', default_drive_window)), w_current_sq=float(pick('w_current_sq', _cfg_value(legacy, 'w_current', 0.01))), w_pack_energy=float(pick('w_pack_energy', 0.0)), w_joule_loss=float(pick('w_joule_loss', 0.0)), w_aero_energy=float(pick('w_aero_energy', 0.0)), w_mech_energy=float(pick('w_mech_energy', 0.0)), w_speed_quartic=float(pick('w_speed_quartic', 0.0)), w_solar_headroom=float(pick('w_solar_headroom', 0.0)), w_progress_lag=float(pick('w_progress_lag', 0.0)), w_progress_terminal_lag=float(pick('w_progress_terminal_lag', 0.0)), w_kinetic_pos=float(pick('w_kinetic_pos', 0.0)), w_pack_power_slew=float(pick('w_pack_power_slew', 0.0)), w_temp=float(pick('w_temp', _cfg_value(legacy, 'w_T', 5.0))), w_soc_terminal=float(pick('w_soc_terminal', 0.0)), w_soc_floor_barrier=float(pick('w_soc_floor_barrier', 0.0)), w_uncertainty_reserve=float(pick('w_uncertainty_reserve', 0.0)), speed_quartic_scale_kmh=float(pick('speed_quartic_scale_kmh', 80.0)), progress_lag_deadband_km=float(pick('progress_lag_deadband_km', 0.0)), soc_solar_headroom_max=float(pick('soc_solar_headroom_max', 0.92)), solar_headroom_power_scale_w=float(pick('solar_headroom_power_scale_w', 1000.0)), soc_floor_barrier_eps=float(pick('soc_floor_barrier_eps', 0.01)), reserve_soc_per_hour=float(pick('reserve_soc_per_hour', 0.0)), reserve_soc_max_extra=float(pick('reserve_soc_max_extra', 0.0)), constraint_penalty=float(pick('constraint_penalty', 10000.0))) を返す。

代表コード断片:

```python
def load_upper_cost_config(
    mpc_cfg: Optional[dict],
    *,
    legacy: Optional[dict] = None,
    default_drive_window: float = 1.0e5,
) -> UpperCostConfig:
    legacy = legacy or {}
    nested = {}
    if isinstance(mpc_cfg, dict):
        nested = mpc_cfg.get("upper_cost", {}) or {}

    def pick(name: str, default):
        if name in nested:
            return nested[name]
        if name in legacy:
            return legacy[name]
        return default

    return UpperCostConfig(
        objective_mode=str(pick("objective_mode", "weighted")).strip().lower(),
        w_wait=float(pick("w_wait", 1.0)),
        w_travel_time=float(pick("w_travel_time", 1.0)),
        w_terminal_soc_min=float(pick("w_terminal_soc_min", 30.0)),
        w_day_end_soc_min=float(pick("w_day_end_soc_min", default_drive_window)),
        w_soc_day_max=float(pick("w_soc_day_max", 1.0e4)),
        w_soc_day_track=float(pick("w_soc_day_track", 0.0)),
        w_speed_smooth=float(pick("w_speed_smooth", _cfg_value(legacy, "w_dv", 30.0))),
        w_dv_limit=float(pick("w_dv_limit", 2.0)),
        w_speed_limit=float(pick("w_speed_limit", 50.0)),
        w_drive_window=float(pick("w_drive_window", default_drive_window)),
        w_current_sq=float(pick("w_current_sq", _cfg_value(legacy, "w_current", 0.01))),
        w_pack_energy=float(pick("w_pack_energy", 0.0)),
        w_joule_loss=float(pick("w_joule_loss", 0.0)),
        w_aero_energy=float(pick("w_aero_energy", 0.0)),
        w_mech_energy=float(pick("w_mech_energy", 0.0)),
...
```

### L65 関数 `load_upper_cost_config.pick`

- 定義: `pick(name: str, default)`
- 行範囲: L65-L70
- 所属: `load_upper_cost_config`
- 戻り値の要点: `default / nested[name] / legacy[name]`
- 制御構造の規模: 条件分岐 2、ループ 0、try 0
- 上から順の処理:
  1. 条件 name in nested を判定し、真なら内部処理を行う。
  2.   nested[name] を返す。
  3. 条件 name in legacy を判定し、真なら内部処理を行う。
  4.   legacy[name] を返す。
  5. default を返す。

代表コード断片:

```python
    def pick(name: str, default):
        if name in nested:
            return nested[name]
        if name in legacy:
            return legacy[name]
        return default
```

### L110 関数 `quad_penalty`

- 定義: `quad_penalty(x: float, cap: float = 1000.0) -> float`
- 行範囲: L110-L115
- 戻り値の要点: `x * x / 0.0`
- この呼出し内で代入する主なローカル名: `x`
- 制御構造の規模: 条件分岐 2、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. 条件 x <= 0.0 を判定し、真なら内部処理を行う。
  2.   0.0 を返す。
  3. 条件 x > cap を判定し、真なら内部処理を行う。
  4.   x に cap の結果を代入する。
  5. x * x を返す。

代表コード断片:

```python
def quad_penalty(x: float, cap: float = 1.0e3) -> float:
    if x <= 0.0:
        return 0.0
    if x > cap:
        x = cap
    return x * x
```

### L118 関数 `upper_stage_cost`

- 定義: `upper_stage_cost(cfg: UpperCostConfig, *, dt_wait: float, dt_travel: float, v_kmh: float, v_prev_kmh: float, vmax_local_kmh: float, drive_limits: Optional[tuple], dv_limit_kmhps: float, I_a: float, V_v: float, P_pv_w: float, P_pack_w: float, P_pack_prev_w: Optional[float], P_mech_wheel_w: float, losses_int_w: float, losses_line_w: float, F_aero_n: float, kinetic_step_wh: float, z_next: float, Tb_next_c: float, term_soc_min: float, soc_min: float, soc_max: float, temp_min_c: float, temp_max_c: float, day_end_soc_min: Optional[float], day_end_crossing: bool, soc_day_end_max: float, soc_day_track_target: Optional[float], soc_day_track_tol: float, I_max: float, I_chg_min: float, V_min: float, V_max: float, time_ahead_h: float, progress_lag_km: float = 0.0) -> float`
- 行範囲: L118-L260
- このブロックが直接呼ぶ主な関数/メソッド: `abs`, `float`, `max`, `min`, `quad_penalty`
- 戻り値の要点: `J / J`
- この呼出し内で代入する主なローカル名: `J`, `c`, `d_pack_kw`, `dv`, `e_aero_wh`, `e_loss_wh`, `e_mech_wh`, `e_pack_wh`, `lag_err`, `pv_kw`, `reserve_extra`, `reserve_soc`, `soc_gap`, `solar_scale`, `speed_scale`, `vmax_kmh`, `vmin_kmh`
- 制御構造の規模: 条件分岐 18、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. J に 0.0 の結果を代入する。
  2. 条件 dt_wait > 0.0 を判定し、真なら内部処理を行う。
  3.   J を Add で更新する。
  4. J を Add で更新する。
  5. 条件 cfg.objective_mode in {'fastest', 'fastest_feasible', 'minimum_time'} を判定し、真なら内部処理を行う。
  6.   c に cfg.constraint_penalty の結果を代入する。
  7.   dv に (v_kmh - v_prev_kmh) / max(dt_travel, 0.001) の結果を代入する。
  8.   条件 dv_limit_kmhps > 0.0 を判定し、真なら内部処理を行う。
  9.     J を Add で更新する。
  10.   条件 drive_limits is not None を判定し、真なら内部処理を行う。
  11.     (vmin_kmh, vmax_kmh) に drive_limits の結果を代入する。
  12.     J を Add で更新する。
  13.     J を Add で更新する。
  14.   J を Add で更新する。
  15.   条件 day_end_crossing and day_end_soc_min is not None を判定し、真なら内部処理を行う。
  16.     J を Add で更新する。
  17.     条件 soc_day_end_max > 0.0 を判定し、真なら内部処理を行う。
  18.       J を Add で更新する。
  19.   J を Add で更新する。
  20.   J を Add で更新する。
  21.   J を Add で更新する。
  22.   J を Add で更新する。
  23.   J を Add で更新する。
  24.   J を Add で更新する。
  25.   J を Add で更新する。
  26.   J を Add で更新する。
  27.   J を返す。
  28. J を Add で更新する。
  29. 条件 soc_day_track_target is not None を判定し、真なら内部処理を行う。
  30.   J を Add で更新する。
  31.   J を Add で更新する。
  32. dv に (v_kmh - v_prev_kmh) / max(dt_travel, 0.001) の結果を代入する。
  33. J を Add で更新する。
  34. 条件 dv_limit_kmhps > 0.0 を判定し、真なら内部処理を行う。
  35.   J を Add で更新する。
  36. 条件 drive_limits is not None を判定し、真なら内部処理を行う。
  37.   (vmin_kmh, vmax_kmh) に drive_limits の結果を代入する。
  38.   J を Add で更新する。
  39.   J を Add で更新する。
  40. J を Add で更新する。
  41. J を Add で更新する。
  42. e_pack_wh に max(0.0, P_pack_w) * dt_travel / 3600.0 の結果を代入する。
  43. e_loss_wh に max(0.0, losses_int_w + losses_line_w) * dt_travel / 3600.0 の結果を代入する。
  44. e_aero_wh に max(0.0, F_aero_n) * (v_kmh / 3.6) * dt_travel / 3600.0 の結果を代入する。
  45. e_mech_wh に max(0.0, P_mech_wheel_w) * dt_travel / 3600.0 の結果を代入する。
  46. J を Add で更新する。
  47. J を Add で更新する。
  48. J を Add で更新する。
  49. J を Add で更新する。
  50. J を Add で更新する。
  51. 条件 cfg.w_speed_quartic > 0.0 を判定し、真なら内部処理を行う。
  52.   speed_scale に max(1.0, cfg.speed_quartic_scale_kmh) の結果を代入する。
  53.   J を Add で更新する。
  54. 条件 cfg.w_pack_power_slew > 0.0 and P_pack_prev_w is not None を判定し、真なら内部処理を行う。
  55.   d_pack_kw に (float(P_pack_w) - float(P_pack_prev_w)) / 1000.0 の結果を代入する。
  56.   J を Add で更新する。
  57. 条件 cfg.w_progress_lag > 0.0 を判定し、真なら内部処理を行う。
  58.   lag_err に max(0.0, float(progress_lag_km) - float(cfg.progress_lag_deadband_km)) の結果を代入する。
  59.   J を Add で更新する。
  60. 条件 cfg.w_solar_headroom > 0.0 を判定し、真なら内部処理を行う。
  61.   solar_scale に max(1.0, cfg.solar_headroom_power_scale_w) の結果を代入する。
  62.   pv_kw に max(0.0, P_pv_w) / solar_scale の結果を代入する。
  63.   条件 pv_kw > 0.0 を判定し、真なら内部処理を行う。
  64.     J を Add で更新する。
  65. 条件 cfg.w_soc_floor_barrier > 0.0 を判定し、真なら内部処理を行う。
  66.   soc_gap に max(float(z_next) - float(soc_min), float(cfg.soc_floor_barrier_eps)) の結果を代入する。
  67.   J を Add で更新する。
  68. 条件 cfg.w_uncertainty_reserve > 0.0 and cfg.reserve_soc_per_hour > 0.0 を判定し、真なら内部処理を行う。
  69.   reserve_extra に min(max(0.0, float(cfg.reserve_soc_max_extra)), max(0.0, float(time_ahead_h)) * max(0.0, float(cfg.reserve_soc_per_hour))) の結果を代入する。
  70.   reserve_soc に min(float(soc_max), float(soc_min) + reserve_extra) の結果を代入する。
  71.   J を Add で更新する。
  72. 条件 day_end_crossing and day_end_soc_min is not None を判定し、真なら内部処理を行う。
  73.   J を Add で更新する。
  74.   条件 soc_day_end_max > 0.0 を判定し、真なら内部処理を行う。
  75.     J を Add で更新する。
  76. c に cfg.constraint_penalty の結果を代入する。
  77. J を Add で更新する。
  78. J を Add で更新する。
  79. J を Add で更新する。
  80. J を Add で更新する。

代表コード断片:

```python
def upper_stage_cost(
    cfg: UpperCostConfig,
    *,
    dt_wait: float,
    dt_travel: float,
    v_kmh: float,
    v_prev_kmh: float,
    vmax_local_kmh: float,
    drive_limits: Optional[tuple],
    dv_limit_kmhps: float,
    I_a: float,
    V_v: float,
    P_pv_w: float,
    P_pack_w: float,
    P_pack_prev_w: Optional[float],
    P_mech_wheel_w: float,
    losses_int_w: float,
    losses_line_w: float,
    F_aero_n: float,
    kinetic_step_wh: float,
    z_next: float,
    Tb_next_c: float,
    term_soc_min: float,
    soc_min: float,
    soc_max: float,
    temp_min_c: float,
    temp_max_c: float,
    day_end_soc_min: Optional[float],
    day_end_crossing: bool,
    soc_day_end_max: float,
    soc_day_track_target: Optional[float],
    soc_day_track_tol: float,
    I_max: float,
    I_chg_min: float,
    V_min: float,
...
```

### L263 関数 `upper_terminal_cost`

- 定義: `upper_terminal_cost(cfg: UpperCostConfig, *, z_terminal: float, term_soc_min: float, soc_finish_target: float, soc_finish_tol: float = 0.0, progress_terminal_lag_km: float = 0.0) -> float`
- 行範囲: L263-L280
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `max`, `quad_penalty`
- 戻り値の要点: `J`
- この呼出し内で代入する主なローカル名: `J`, `lag_err`
- 制御構造の規模: 条件分岐 2、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. J に cfg.constraint_penalty * quad_penalty(term_soc_min - z_terminal) の結果を代入する。
  2. 条件 soc_finish_target > 0.0 を判定し、真なら内部処理を行う。
  3.   J を Add で更新する。
  4. 条件 cfg.w_progress_terminal_lag > 0.0 を判定し、真なら内部処理を行う。
  5.   lag_err に max(0.0, float(progress_terminal_lag_km) - float(cfg.progress_lag_deadband_km)) の結果を代入する。
  6.   J を Add で更新する。
  7. J を返す。

代表コード断片:

```python
def upper_terminal_cost(
    cfg: UpperCostConfig,
    *,
    z_terminal: float,
    term_soc_min: float,
    soc_finish_target: float,
    soc_finish_tol: float = 0.0,
    progress_terminal_lag_km: float = 0.0,
) -> float:
    J = cfg.constraint_penalty * quad_penalty(term_soc_min - z_terminal)
    if soc_finish_target > 0.0:
        J += cfg.w_soc_terminal * quad_penalty(
            z_terminal - (soc_finish_target + max(0.0, soc_finish_tol))
        )
    if cfg.w_progress_terminal_lag > 0.0:
        lag_err = max(0.0, float(progress_terminal_lag_km) - float(cfg.progress_lag_deadband_km))
        J += cfg.w_progress_terminal_lag * quad_penalty(lag_err)
    return J
```

### L283 関数 `active_upper_cost_terms`

- 定義: `active_upper_cost_terms(cfg: UpperCostConfig, threshold: float = 1e-06) -> Dict[str, float]`
- 行範囲: L283-L288
- このブロックが直接呼ぶ主な関数/メソッド: `abs`, `float`, `items`, `startswith`, `to_dict`
- 戻り値の要点: `out`
- この呼出し内で代入する主なローカル名: `key`, `out`, `value`
- 制御構造の規模: 条件分岐 1、ループ 1、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. out に {} の結果を代入する。
  2. cfg.to_dict().items() を順に走査し、各要素を (key, value) に入れて処理する。
  3.   条件 key.startswith('w_') and abs(float(value)) > threshold を判定し、真なら内部処理を行う。
  4.     out[key] に float(value) の結果を代入する。
  5. out を返す。

代表コード断片:

```python
def active_upper_cost_terms(cfg: UpperCostConfig, threshold: float = 1.0e-6) -> Dict[str, float]:
    out = {}
    for key, value in cfg.to_dict().items():
        if key.startswith("w_") and abs(float(value)) > threshold:
            out[key] = float(value)
    return out
```


## 処理の流れ

1. ソース中の主要関数を通じて処理を進める。
