# 38. upper mesh 収束確認

- ファイル: `scripts/run_upper_mesh_convergence.py`
- ソースSHA-256: `52a2c44e4c72d4aebd68c9c33a56a72fad541cea857920fcb3932d7e684325e1`
- 種別: `Python`
- 区分: `planning validation`

## 役割

候補 policy や exact replay を距離分解能違いで再計算し、結果が十分収束しているか確認する。

## 起動文脈

- 起動文脈: GPU/learned policy の acceptance 前検証。
- 呼び出し元: `validation pipeline`, `手動検証`
- 次に読むべきファイル: `scripts/validate_gpu_upper_policy_candidates.py`

## 主要ポイント

- 細かい距離メッシュが本当に必要十分かを調べる。

## 主要構造

主要関数は parse_float_list, parse_control_policies, assign_finest_control_policy, file_sha256, resolve, load_plan, speed_rms_difference, materialize_profile。 CLI 引数宣言は 7 件。

## ファイルを上から読んだときの定義順

- L19: ROOT に Path(__file__).resolve().parents[1] の結果を代入する。
- L22: 関数 parse_float_list を定義する。
- L26: 関数 parse_control_policies を定義する。
- L42: 関数 assign_finest_control_policy を定義する。
- L57: 関数 file_sha256 を定義する。
- L65: 関数 resolve を定義する。
- L70: 関数 load_plan を定義する。
- L78: 関数 speed_rms_difference を定義する。
- L85: 関数 materialize_profile を定義する。
- L131: 関数 main を定義する。
- L308: 条件 __name__ == '__main__' を判定し、真なら内部処理を行う。

## import 群

- L4: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L6: `import argparse`
  - CLI 引数を宣言し、実行時パラメータを外から受け取るため。 このファイル内での主な使用位置は L132, L150。
- L7: `import hashlib`
  - snapshot ID や入力資産の digest を作るため。 このファイル内での主な使用位置は L58, L196。
- L8: `import json`
  - manifest、checkpoint、UDP payload をやり取りするため。 このファイル内での主な使用位置は L214, L225, L303, L304。
- L9: `import math`
  - Python標準のスカラー数値関数と定数を使うため。実際に参照する名前と行は使用位置欄で確認する。 このファイル内での主な使用位置は L116。
- L10: `import subprocess`
  - git 情報取得や外部コマンド実行を行うため。 このファイル内での主な使用位置は L221。
- L11: `import sys`
  - sys モジュールを利用するため。 このファイル内での主な使用位置は L204。
- L12: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L19, L26, L27, L35, L44, L45, L46, L57, ...。
- L14: `import numpy as np`
  - 数値配列、clip、補間、統計計算を行うため。 このファイル内での主な使用位置は L79, L80, L81, L82。
- L15: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L70, L74, L78, L282, L283。
- L16: `import yaml`
  - profile、stop、schedule、summary YAML を読み書きするため。 このファイル内での主な使用位置は L86, L127, L159。

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

### list、dict、deque、NumPy配列、pandas DataFrame

listは順序付き可変列、tupleは順序付きで通常変更しない列、dictはキーから値を引く対応表、dequeは両端追加・削除が効率的なキューである。どの構造を選ぶかはアクセス方法と更新方法で決まる。

NumPy配列は同種数値を連続的に扱い、要素ごとの演算、clip、補間、線形代数を簡潔に書く。shapeは各次元の要素数であり、速度系列なら通常`(N,)`、候補集団なら`(population, N)`となる。

pandas DataFrameは列名を持つ表である。CSV読込後は列型、欠損、単位、timezone、並び順、重複を明示的に処理しなければ、数値計算が動いても意味が誤る。

### CLI、PowerShell、Bash、環境変数、終了コード

CLIは端末からプログラム名と引数を渡す操作界面である。`argparse`は文字列として届く引数を名前、型、既定値、必須性に従って解析する。

PowerShellとBashは別のshellであり、変数記法、改行継続、引用、パス表記が異なる。このプロジェクトではWindows側のSolarSim.ps1がWSL側のsolar_control.shへ処理を渡す。

環境変数は親プロセスから子プロセスへ受け渡される名前付き文字列である。ROS_DOMAIN_ID、RMW_IMPLEMENTATION、Pythonの数値スレッド数などはコード外から動作を変えるため、実行記録へ残す必要がある。

終了コード0は一般に成功、0以外は失敗を示す。shellルータは子プロセスの終了コードを握り潰さず上位へ返すことで、自動運用が失敗を検知できる。

根拠資料:

- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)

### 目的関数、制約、L-BFGS-B、SHGO、有限grid証明

数値最適化器は、利用者が与えた目的関数を複数の候補点で評価し、より小さい値を持つ候補を探す。solverが物理を理解するのではなく、物理と運用価値はcost関数へ書かれる。

L-BFGS-Bは変数ごとの上下限を扱える局所最適化法である。初期値の近くの谷へ収束し得るため、非凸問題では複数seedや大域探索と組み合わせる。successがFalseでも有限な候補が返る場合があるため、採用条件をコード側で決める。

SHGOは定めたsamplingと局所最適化を組み合わせる大域最適化法である。有限Cartesian gridの全列挙は、そのgrid上の最良を証明できるが、連続領域全体の最良を自動的に証明しない。資料ではこの証明範囲を区別する。

根拠資料:

- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)
- [SciPy公式: scipy.optimize.shgo](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.shgo.html)

### warm startは何を保存し、どう効くか

warm startは前回またはoffline探索で得た入力系列を、次の最適化の初期候補として渡すことである。答えを固定するのではなく、探索開始点と候補libraryの一員を与える。

$$
u^{0,\mathrm{new}}_i=\operatorname{interp}\left(s_i^{\mathrm{new}};\,s_j^{\mathrm{old}},u_j^{\ast,\mathrm{old}}\right)
$$

距離基準計画では、現在より後ろの旧制御点を捨て、新しい絶対距離制御点へ補間してshiftする。初期状態や天候が変わればcost評価は新条件で行われるので、warm startが不適切でも他seed、CEM、安全fallbackが補う設計が必要である。

warm startの効き方は、局所法なら収束先と反復数、CEMなら初期meanまたは候補pool、receding horizonなら前回解の時間・距離shiftとして現れる。どの位置に渡しているかを呼出引数まで追う。

根拠資料:

- [SciPy公式: scipy.optimize.minimize](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize.html)
- [Rubinstein and Kroese: The Cross-Entropy Method](https://link.springer.com/book/10.1007/978-1-4757-4321-0)

### CSV/YAMLのdata contractと検証

data contractは列名、型、単位、timezone、欠損可否、並び順、重複、許容範囲、先頭行、encodingを事前に決めた仕様である。単にCSVとして読めることは、モデル入力として正しいことを意味しない。

同定用実測、map、route、forecast、stop、scheduleはそれぞれgrainが異なる。生成時にschema validation、物理範囲、時間単調性、route範囲、coverageを検査し、検査結果をartifactとして残す。

学習用データと独立検証データを分離し、RMSEだけでなくbias、時系列残差、energy積算誤差、終端SoC、温度・電圧制約、外挿領域を評価する。

### 単体試験、SILS、replay、観測可能性

単体試験は関数やモデル項の局所契約、SILSは複数Nodeと時間進行を含む閉ループ、historical replayは実測入力への再現性、本番preflightは実機通信と停止動作を確認する。目的が異なるため一つで代用しない。

再現可能な診断には、入力、出力、内部状態、solver成否、候補数、計算時間、fallback、source revision、profile hashを同じrun IDで記録する。

非同期不具合は最終値だけでは追えない。topic周期、message age、callback所要時間、queue遅延、Node生存、publisher数を同時に観測する。

根拠資料:

- [ROS 2 Humble公式: rqt_graph](https://docs.ros.org/en/ros2_packages/humble/api/rqt_graph/index.html)
- [ROS 2 Humble公式: Recording and playing back data](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Recording-And-Playing-Back-Data/Recording-And-Playing-Back-Data.html)
- [ROS 2公式: Executors](https://docs.ros.org/en/rolling/Concepts/Intermediate/About-Executors.html)


## 関数・クラスを上から順に解説

### L22 関数 `parse_float_list`

- 定義: `parse_float_list(value: str) -> list[float]`
- 行範囲: L22-L23
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `split`, `str`, `strip`
- 戻り値の要点: `[float(item) for item in str(value).split(',') if item.strip()]`
- この呼出し内で代入する主なローカル名: `item`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
  - 内包表記は、反復・条件・値生成を一つの式で記述してcollectionを作る。
- 上から順の処理:
  1. [float(item) for item in str(value).split(',') if item.strip()] を返す。

代表コード断片:

```python
def parse_float_list(value: str) -> list[float]:
    return [float(item) for item in str(value).split(",") if item.strip()]
```

### L26 関数 `parse_control_policies`

- 定義: `parse_control_policies(values: list[str]) -> dict[float, Path]`
- 行範囲: L26-L39
- このブロックが直接呼ぶ主な関数/メソッド: `FileNotFoundError`, `Path`, `ValueError`, `float`, `is_file`, `partition`, `resolve`, `str`, `strip`
- 戻り値の要点: `policies`
- この呼出し内で代入する主なローカル名: `path`, `path_text`, `policies`, `raw`, `separator`, `spacing`, `spacing_text`
- 明示的に送出する例外: `FileNotFoundError(path)`, `ValueError('--control-policy must use CONTROL_KM=POLICY_CSV')`, `ValueError('control-policy spacing must be positive')`
- 制御構造の規模: 条件分岐 3、ループ 1、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. policies に {} を代入する。
  2. values を順に走査し、各要素を raw に入れて処理する。
  3.   (spacing_text, separator, path_text) に str(raw).partition('=') の結果を代入する。
  4.   条件 not separator or not path_text.strip() を判定し、真なら内部処理を行う。
  5.     ValueError('--control-policy must use CONTROL_KM=POLICY_CSV') を送出する。
  6.   spacing に float(spacing_text) の結果を代入する。
  7.   条件 spacing <= 0.0 を判定し、真なら内部処理を行う。
  8.     ValueError('control-policy spacing must be positive') を送出する。
  9.   path に Path(path_text).resolve() の結果を代入する。
  10.   条件 not path.is_file() を判定し、真なら内部処理を行う。
  11.     FileNotFoundError(path) を送出する。
  12.   policies[spacing] に path の結果を代入する。
  13. policies を返す。

代表コード断片:

```python
def parse_control_policies(values: list[str]) -> dict[float, Path]:
    policies: dict[float, Path] = {}
    for raw in values:
        spacing_text, separator, path_text = str(raw).partition("=")
        if not separator or not path_text.strip():
            raise ValueError("--control-policy must use CONTROL_KM=POLICY_CSV")
        spacing = float(spacing_text)
        if spacing <= 0.0:
            raise ValueError("control-policy spacing must be positive")
        path = Path(path_text).resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        policies[spacing] = path
    return policies
```

### L42 関数 `assign_finest_control_policy`

- 定義: `assign_finest_control_policy(control_meshes: list[float], supplied_policies: dict[float, Path], finest_policy: Path) -> tuple[float, dict[float, Path], list[float]]`
- 行範囲: L42-L54
- docstring: Assign --policy to the finest requested control mesh without relabelling it.
- このブロックが直接呼ぶ主な関数/メソッド: `ValueError`, `dict`, `float`, `min`, `resolve`
- 戻り値の要点: `(finest_ctrl, policies, order)`
- この呼出し内で代入する主なローカル名: `ctrl`, `finest_ctrl`, `order`, `policies`, `value`
- 明示的に送出する例外: `ValueError('at least one control mesh is required')`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
  - 内包表記は、反復・条件・値生成を一つの式で記述してcollectionを作る。
- 上から順の処理:
  1. 条件 not control_meshes を判定し、真なら内部処理を行う。
  2.   ValueError('at least one control mesh is required') を送出する。
  3. finest_ctrl に min((float(value) for value in control_meshes)) の結果を代入する。
  4. policies に dict(supplied_policies) の結果を代入する。
  5. policies[finest_ctrl] に finest_policy.resolve() の結果を代入する。
  6. order に [float(ctrl) for ctrl in control_meshes if float(ctrl) in policies] の結果を代入する。
  7. (finest_ctrl, policies, order) を返す。

代表コード断片:

```python
def assign_finest_control_policy(
    control_meshes: list[float],
    supplied_policies: dict[float, Path],
    finest_policy: Path,
) -> tuple[float, dict[float, Path], list[float]]:
    """Assign --policy to the finest requested control mesh without relabelling it."""
    if not control_meshes:
        raise ValueError("at least one control mesh is required")
    finest_ctrl = min(float(value) for value in control_meshes)
    policies = dict(supplied_policies)
    policies[finest_ctrl] = finest_policy.resolve()
    order = [float(ctrl) for ctrl in control_meshes if float(ctrl) in policies]
    return finest_ctrl, policies, order
```

### L57 関数 `file_sha256`

- 定義: `file_sha256(path: Path) -> str`
- 行範囲: L57-L62
- このブロックが直接呼ぶ主な関数/メソッド: `hexdigest`, `iter`, `open`, `read`, `sha256`, `update`
- 戻り値の要点: `digest.hexdigest()`
- この呼出し内で代入する主なローカル名: `chunk`, `digest`, `handle`
- 制御構造の規模: 条件分岐 0、ループ 1、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
  - lambdaは名前を付けずに短い関数オブジェクトを作る構文である。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. digest に hashlib.sha256() の結果を代入する。
  2. with 文で path.open('rb') を管理しながら処理する。
  3.   iter(lambda: handle.read(1024 * 1024), b'') を順に走査し、各要素を chunk に入れて処理する。
  4.     digest.update(...) を実行する。
  5. digest.hexdigest() を返す。

代表コード断片:

```python
def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
```

### L65 関数 `resolve`

- 定義: `resolve(profile: Path, value: str) -> Path`
- 行範囲: L65-L67
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `is_absolute`, `resolve`, `str`
- 戻り値の要点: `path if path.is_absolute() else (profile.parent / path).resolve()`
- この呼出し内で代入する主なローカル名: `path`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. path に Path(str(value)) の結果を代入する。
  2. path if path.is_absolute() else (profile.parent / path).resolve() を返す。

代表コード断片:

```python
def resolve(profile: Path, value: str) -> Path:
    path = Path(str(value))
    return path if path.is_absolute() else (profile.parent / path).resolve()
```

### L70 関数 `load_plan`

- 定義: `load_plan(summary: dict) -> pd.DataFrame`
- 行範囲: L70-L75
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `is_absolute`, `read_csv`, `resolve`, `sort_values`
- 戻り値の要点: `frame.sort_values('plan_s_km')`
- この呼出し内で代入する主なローカル名: `frame`, `path`
- 制御構造の規模: 条件分岐 1、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. path に Path(summary['plan_csv']) の結果を代入する。
  2. 条件 not path.is_absolute() を判定し、真なら内部処理を行う。
  3.   path に (ROOT / path).resolve() の結果を代入する。
  4. frame に pd.read_csv(path) の結果を代入する。
  5. frame.sort_values('plan_s_km') を返す。

代表コード断片:

```python
def load_plan(summary: dict) -> pd.DataFrame:
    path = Path(summary["plan_csv"])
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    frame = pd.read_csv(path)
    return frame.sort_values("plan_s_km")
```

### L78 関数 `speed_rms_difference`

- 定義: `speed_rms_difference(left: pd.DataFrame, right: pd.DataFrame, race_km: float) -> float`
- 行範囲: L78-L82
- このブロックが直接呼ぶ主な関数/メソッド: `arange`, `float`, `interp`, `mean`, `sqrt`
- 戻り値の要点: `float(np.sqrt(np.mean((left_v - right_v) ** 2)))`
- この呼出し内で代入する主なローカル名: `grid`, `left_v`, `right_v`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. grid に np.arange(0.0, race_km + 1.0, 1.0) の結果を代入する。
  2. left_v に np.interp(grid, left['plan_s_km'], left['plan_v_kmh']) の結果を代入する。
  3. right_v に np.interp(grid, right['plan_s_km'], right['plan_v_kmh']) の結果を代入する。
  4. float(np.sqrt(np.mean((left_v - right_v) ** 2))) を返す。

代表コード断片:

```python
def speed_rms_difference(left: pd.DataFrame, right: pd.DataFrame, race_km: float) -> float:
    grid = np.arange(0.0, race_km + 1.0, 1.0)
    left_v = np.interp(grid, left["plan_s_km"], left["plan_v_kmh"])
    right_v = np.interp(grid, right["plan_s_km"], right["plan_v_kmh"])
    return float(np.sqrt(np.mean((left_v - right_v) ** 2)))
```

### L85 関数 `materialize_profile`

- 定義: `materialize_profile(base_path: Path, output_path: Path, *, policy_path: Path, ds_km: float, ctrl_km: float) -> dict`
- 行範囲: L85-L128
- このブロックが直接呼ぶ主な関数/メソッド: `ceil`, `float`, `get`, `int`, `items`, `list`, `mkdir`, `read_text`, `resolve`, `safe_dump`, `safe_load`, `str`
- 戻り値の要点: `cfg`
- この呼出し内で代入する主なローカル名: `cfg`, `key`, `race_km`, `run_dir`, `value`
- 制御構造の規模: 条件分岐 2、ループ 2、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
- 上から順の処理:
  1. cfg に yaml.safe_load(base_path.read_text(encoding='utf-8')) or {} の結果を代入する。
  2. list((cfg.get('paths', {}) or {}).items()) を順に走査し、各要素を (key, value) に入れて処理する。
  3.   条件 value を判定し、真なら内部処理を行う。
  4.     cfg['paths'][key] に str(resolve(base_path, value)) の結果を代入する。
  5. ('fit_summary_yaml', 'terminal_consistency_yaml') を順に走査し、各要素を key に入れて処理する。
  6.   value に cfg.get('identification', {}).get(key, '') の結果を代入する。
  7.   条件 value を判定し、真なら内部処理を行う。
  8.     cfg['identification'][key] に str(resolve(base_path, value)) の結果を代入する。
  9. cfg['paths']['initial_upper_policy_csv'] に str(policy_path.resolve()) の結果を代入する。
  10. race_km に float(cfg['mpc']['race_km']) の結果を代入する。
  11. run_dir に output_path.parent の結果を代入する。
  12. cfg['meta']['name'] に f'mesh_ds{ds_km:g}_ctrl{ctrl_km:g}' の結果を代入する。
  13. cfg['simulation'].update(...) を実行する。
  14. cfg['mpc'].update(...) を実行する。
  15. output_path.parent.mkdir(...) を実行する。
  16. output_path.write_text(...) を実行する。
  17. cfg を返す。

代表コード断片:

```python
def materialize_profile(base_path: Path, output_path: Path, *, policy_path: Path, ds_km: float, ctrl_km: float) -> dict:
    cfg = yaml.safe_load(base_path.read_text(encoding="utf-8")) or {}
    for key, value in list((cfg.get("paths", {}) or {}).items()):
        if value:
            cfg["paths"][key] = str(resolve(base_path, value))
    for key in ("fit_summary_yaml", "terminal_consistency_yaml"):
        value = cfg.get("identification", {}).get(key, "")
        if value:
            cfg["identification"][key] = str(resolve(base_path, value))
    cfg["paths"]["initial_upper_policy_csv"] = str(policy_path.resolve())
    race_km = float(cfg["mpc"]["race_km"])
    run_dir = output_path.parent
    cfg["meta"]["name"] = f"mesh_ds{ds_km:g}_ctrl{ctrl_km:g}"
    cfg["simulation"].update(
        {
            # Exact acceptance must evaluate the policy itself, not a second
            # energy-budget controller that can silently slow an infeasible plan.
            "energy_budget": False,
            "output_dir": str(run_dir),
            "output_prefix": "simulation",
            "auto_version_outputs": False,
            "latest_manifest_json": str(run_dir / "latest_simulation_run.json"),
            "detail_rate_hz": 1.0,
            "detail_compression": "gzip",
        }
    )
    cfg["mpc"].update(
        {
            "upper_horizon_mode": "fixed",
            "upper_ds_km": ds_km,
            "upper_horizon_km": race_km,
            "upper_max_steps": int(math.ceil(race_km / ds_km)) + 1,
            "upper_ctrl_km": ctrl_km,
            "upper_lock_initial_policy": True,
            "upper_global_search_enabled": False,
...
```

### L131 関数 `main`

- 定義: `main() -> int`
- 行範囲: L131-L305
- このブロックが直接呼ぶ主な関数/メソッド: `ArgumentParser`, `DataFrame`, `Path`, `RuntimeError`, `abs`, `add_argument`, `all`, `append`, `assign_finest_control_policy`, `bool`, `dumps`, `encode`
- 戻り値の要点: `0 if gate_pass else 2`
- この呼出し内で代入する主なローカル名: `acceptance`, `args`, `base_cfg`, `cached`, `case_policy`, `cases`, `checks`, `coarse`, `coarse_summary`, `command`, `comparisons`, `control_final`, `control_meshes`, `control_order`, `control_policy_paths`, `ctrl`, `ctrl_km`, `detail_path`, `ds`, `ds_km`
- 明示的に送出する例外: `RuntimeError(f'mesh run failed: ds={ds_km} ctrl={ctrl_km}; inspect {log_path}')`
- 制御構造の規模: 条件分岐 5、ループ 3、try 0
- この定義を読むためのPython構文:
  - `->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。
  - 内包表記は、反復・条件・値生成を一つの式で記述してcollectionを作る。
  - with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。
- 上から順の処理:
  1. parser に argparse.ArgumentParser(description=__doc__) の結果を代入する。
  2. parser.add_argument(...) を実行する。
  3. parser.add_argument(...) を実行する。
  4. parser.add_argument(...) を実行する。
  5. parser.add_argument(...) を実行する。
  6. parser.add_argument(...) を実行する。
  7. parser.add_argument(...) を実行する。
  8. parser.add_argument(...) を実行する。
  9. args に parser.parse_args() の結果を代入する。
  10. profile に args.profile.resolve() の結果を代入する。
  11. policy に args.policy.resolve() の結果を代入する。
  12. output_dir に args.output_dir.resolve() の結果を代入する。
  13. base_cfg に yaml.safe_load(profile.read_text(encoding='utf-8')) or {} の結果を代入する。
  14. control_policy_paths に parse_control_policies(args.control_policy) の結果を代入する。
  15. acceptance に base_cfg.get('mesh_verification', {}).get('acceptance', {}) の結果を代入する。
  16. verification に base_cfg.get('mesh_verification', {}) or {} の結果を代入する。
  17. integration_meshes に parse_float_list(args.integration_meshes_km) or [float(value) for value in verification.get('integration_mesh_candidates_km', [1.0, 0.5, 0.2, 0.1])] の結果を代入する。
  18. control_meshes に parse_float_list(args.control_meshes_km) or [float(value) for value in verification.get('control_mesh_candidates_km', [25.0, 10.0, 5.0, 2.0, 1.0])] の結果を代入する。
  19. selected_ds に float(base_cfg['mpc']['upper_ds_km']) の結果を代入する。
  20. (selected_ctrl, control_policy_paths, control_order) に assign_finest_control_policy(control_meshes, control_policy_paths, policy) の結果を代入する。
  21. cases に [(ds, selected_ctrl, 'integration', policy) for ds in integration_meshes] の結果を代入する。
  22. cases.extend(...) を実行する。
  23. summaries に {} の結果を代入する。
  24. rows に [] の結果を代入する。
  25. cases を順に走査し、各要素を (ds_km, ctrl_km, phase, case_policy) に入れて処理する。
  26.   key に (ds_km, ctrl_km) の結果を代入する。
  27.   条件 key in summaries を判定し、真なら内部処理を行う。
  28.     Continue 文を実行する。
  29.   run_dir に output_dir / f'ds_{ds_km:g}_ctrl_{ctrl_km:g}' の結果を代入する。
  30.   run_profile に run_dir / 'profile.yaml' の結果を代入する。
  31.   materialize_profile(...) を実行する。
  32.   signature に hashlib.sha256((file_sha256(run_profile) + file_sha256(case_policy) + file_sha256(ROOT / 'scripts' / 'solar_sim.py')).encode('ascii')).hexdigest() の結果を代入する。
  33.   signature_path に run_dir / 'run_signature.txt' の結果を代入する。
  34.   command に [sys.executable, '-u', str(ROOT / 'scripts' / 'solar_sim.py'), '--profile_yaml', str(run_profile)] の結果を代入する。
  35.   log_path に run_dir / 'console.log' の結果を代入する。
  36.   manifest_path に run_dir / 'latest_simulation_run.json' の結果を代入する。
  37.   reusable に bool(args.resume and manifest_path.is_file() and signature_path.is_file() and (signature_path.read_text(encoding='ascii').strip() == signature)) の結果を代入する。
  38.   条件 reusable を判定し、真なら内部処理を行う。
  39.     cached に json.loads(manifest_path.read_text(encoding='utf-8')) の結果を代入する。
  40.     detail_path に Path(str(cached.get('detail_csv', ''))) の結果を代入する。
  41.     条件 not detail_path.is_absolute() を判定し、真なら内部処理を行う。
  42.       detail_path に (ROOT / detail_path).resolve() の結果を代入する。
  43.     reusable に bool(detail_path.is_file() and int(cached.get('detail_rows', 0)) > 0) の結果を代入する。
  44.   条件 not reusable を判定し、真なら内部処理を行う。
  45.     with 文で log_path.open('w', encoding='utf-8') を管理しながら処理する。
  46.       result に subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, text=True, check=False) の結果を代入する。
  47.     条件 result.returncode != 0 or not manifest_path.exists() を判定し、真なら内部処理を行う。
  48.       RuntimeError(f'mesh run failed: ds={ds_km} ctrl={ctrl_km}; inspect {log_path}') を送出する。
  49.     signature_path.write_text(...) を実行する。
  50.   summary に json.loads(manifest_path.read_text(encoding='utf-8')) の結果を代入する。
  51.   summaries[key] に summary の結果を代入する。
  52.   rows.append(...) を実行する。
  53. comparisons に [] の結果を代入する。
  54. (('integration', [(ds, selected_ctrl) for ds in integration_meshes]), ('control', [(selected_ds, ctrl) for ctrl in control_order])) を順に走査し、各要素を (phase, ordered) に入れて処理する。
  55.   zip(ordered[:-1], ordered[1:]) を順に走査し、各要素を (coarse, fine) に入れて処理する。
  56.     coarse_summary に summaries[coarse] の結果を代入する。
  57.     fine_summary に summaries[fine] の結果を代入する。
  58.     elapsed_change_sec に abs(float(fine_summary['elapsed_hours']) - float(coarse_summary['elapsed_hours'])) * 3600.0 の結果を代入する。
  59.     soc_change に abs(float(fine_summary['final_soc']) - float(coarse_summary['final_soc'])) の結果を代入する。
  60.     speed_rms に speed_rms_difference(load_plan(coarse_summary), load_plan(fine_summary), float(base_cfg['mpc']['race_km'])) の結果を代入する。
  61.     sync_error に abs(float(fine_summary['prediction_execution_terminal_soc_error'])) の結果を代入する。
  62.     checks に {'elapsed': elapsed_change_sec <= float(acceptance.get('elapsed_time_change_max_sec', 60.0)), 'terminal_soc': soc_change <= float(acceptance.get('terminal_soc_change_max', 0.002)), 'speed_rms': speed_rms <= float(acceptance.get('speed_profile_rms_change_max_kmh', 0.5)), 'prediction_execution_soc': sync_error <= float(acceptance.get('prediction_execution_soc_error_max', 0.002))} の結果を代入する。
  63.     comparisons.append(...) を実行する。
  64. integration_final に [row for row in comparisons if row['phase'] == 'integration'][-1:] の結果を代入する。
  65. control_final に [row for row in comparisons if row['phase'] == 'control'][-1:] の結果を代入する。
  66. final_pairs に integration_final + control_final の結果を代入する。
  67. gate_pass に bool(len(final_pairs) == 2 and all((row['pair_pass'] for row in final_pairs))) の結果を代入する。
  68. pd.DataFrame(rows).to_csv(...) を実行する。
  69. pd.DataFrame(comparisons).to_csv(...) を実行する。
  70. result に {'method': 'fixed-policy successive h-refinement with independent 1 Hz explicit replay', 'policy_csv': str(policy), 'acceptance': acceptance, 'selected_integration_ds_km': selected_ds, 'selected_control_ds_km': selected_ctrl, 'control_policy_csvs': {str(ctrl): str(control_policy_paths[ctrl]) for ctrl in control_order}, 'control_policy_gate_evaluated': len(control_final) == 1, 'mesh_gate_pass': gate_pass, 'final_pair_results': final_pairs, 'caution': 'The integration gate uses one fixed policy. The control gate compares independently optimized policies at successive control spacings. Missing control-policy inputs fail the combined gate. This is a numerical convergence certificate, not a proof of the continuous global optimum.'} の結果を代入する。
  71. (output_dir / 'mesh_convergence_summary.json').write_text(...) を実行する。
  72. print(...) を実行する。
  73. 0 if gate_pass else 2 を返す。

代表コード断片:

```python
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--integration-meshes-km", default="")
    parser.add_argument("--control-meshes-km", default="")
    parser.add_argument(
        "--control-policy",
        action="append",
        default=[],
        metavar="CONTROL_KM=POLICY_CSV",
        help=(
            "Independently optimized policy for a control spacing. Supply the coarser "
            "policies; --policy is assigned to the finest spacing."
        ),
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Reuse a completed case only when its profile, policy, and simulator signatures still match.",
    )
    args = parser.parse_args()

    profile = args.profile.resolve()
    policy = args.policy.resolve()
    output_dir = args.output_dir.resolve()
    base_cfg = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
    control_policy_paths = parse_control_policies(args.control_policy)
    acceptance = base_cfg.get("mesh_verification", {}).get("acceptance", {})
    verification = base_cfg.get("mesh_verification", {}) or {}
    integration_meshes = parse_float_list(args.integration_meshes_km) or [
        float(value) for value in verification.get("integration_mesh_candidates_km", [1.0, 0.5, 0.2, 0.1])
    ]
...
```


## CLI 引数

- L133: `--profile`
- L134: `--policy`
- L135: `--output-dir`
- L136: `--integration-meshes-km`
- L137: `--control-meshes-km`
- L138: `--control-policy`
- L148: `--resume`

## 処理の流れ

1. CLI 引数を解釈し、main() から処理を起動する。
