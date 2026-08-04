# 34. テンプレ識別パイプライン入口

- ファイル: `scripts/run_identification_pipeline.py`
- ソースSHA-256: `28ea90f2cfb526907c9e1cbe38255e1633eddf96050b196f794e257c942a4bf0`
- 種別: `Python`
- 区分: `identification`

## 役割

template package の raw データから地図生成・基礎整備・識別処理を繋ぐ入口。

## 起動文脈

- 起動文脈: identify action で呼ばれる。
- 呼び出し元: `scripts/solar_control.sh`
- 次に読むべきファイル: `scripts/run_vehicle_identification.py`

## 主要ポイント

- template/package 初期整備向きの高位入口。

## 主要構造

主要関数は run, main。 CLI 引数宣言は 3 件。

## ファイルを上から読んだときの定義順

- L8: ROOT に Path(__file__).resolve().parents[1] の結果を代入する。
- L9: 条件 str(ROOT) not in sys.path を判定し、真なら内部処理を行う。
- L15: 関数 run を定義する。
- L20: 関数 main を定義する。
- L88: 条件 __name__ == '__main__' を判定し、真なら内部処理を行う。

## import 群

- L2: `import argparse`
  - CLI 引数を宣言し、実行時パラメータを外から受け取るため。 このファイル内での主な使用位置は L21。
- L3: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L29, L30, L31, L35, L36, L40, L41, L44, ...。
- L4: `import subprocess`
  - git 情報取得や外部コマンド実行を行うため。 このファイル内での主な使用位置は L17。
- L5: `import sys`
  - sys モジュールを利用するため。 このファイル内での主な使用位置は L9, L10, L33。
- L6: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L8。
- L12: `from mpc_solarcar.solar_profile import get_section, load_profile`
  - profile YAML 読込と検証 から get_section, load_profile を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L27, L28, L72。

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

### CLI、PowerShell、Bash、環境変数、終了コード

CLIは端末からプログラム名と引数を渡す操作界面である。`argparse`は文字列として届く引数を名前、型、既定値、必須性に従って解析する。

PowerShellとBashは別のshellであり、変数記法、改行継続、引用、パス表記が異なる。このプロジェクトではWindows側のSolarSim.ps1がWSL側のsolar_control.shへ処理を渡す。

環境変数は親プロセスから子プロセスへ受け渡される名前付き文字列である。ROS_DOMAIN_ID、RMW_IMPLEMENTATION、Pythonの数値スレッド数などはコード外から動作を変えるため、実行記録へ残す必要がある。

終了コード0は一般に成功、0以外は失敗を示す。shellルータは子プロセスの終了コードを握り潰さず上位へ返すことで、自動運用が失敗を検知できる。

根拠資料:

- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)

### 天候、route、補間、時刻、単位

予報は時刻だけの系列か、時刻とroute距離の2次元gridになり得る。現在時刻tと距離sがgrid点の間なら、周囲の値から補間して日射、温度、風を求める。

UTC、現地timezone、naive datetimeを混ぜると数時間のずれが発生する。入力でtimezoneを確定し、内部比較はUTC、表示は現地時刻という役割分担が安全である。

route距離のkm、速度のkm/hとm/s、時間の秒、energyのWhとJを跨ぐため、変換係数3.6、3600、1000の意味を各式で確認する。

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

### L15 関数 `run`

- 定義: `run(cmd)`
- 行範囲: L15-L17
- このブロックが直接呼ぶ主な関数/メソッド: `join`, `print`, `run`
- 制御構造の規模: 条件分岐 0、ループ 0、try 0
- 上から順の処理:
  1. print(...) を実行する。
  2. subprocess.run(...) を実行する。

代表コード断片:

```python
def run(cmd):
    print('RUN', ' '.join(cmd))
    subprocess.run(cmd, check=True)
```

### L20 関数 `main`

- 定義: `main()`
- 行範囲: L20-L85
- このブロックが直接呼ぶ主な関数/メソッド: `ArgumentParser`, `abspath`, `add_argument`, `exists`, `get`, `get_section`, `join`, `load_profile`, `makedirs`, `parse_args`, `print`, `run`
- この呼出し内で代入する主なローカル名: `ap`, `args`, `cfg`, `drive_csv`, `gps_csv`, `ident_cfg`, `input_dir`, `model_cfg`, `ocv_csv`, `output_dir`, `panel_csv`, `profile_path`, `pulse_csv`, `python`, `rest_csv`
- 制御構造の規模: 条件分岐 5、ループ 0、try 0
- 上から順の処理:
  1. ap に argparse.ArgumentParser() の結果を代入する。
  2. ap.add_argument(...) を実行する。
  3. ap.add_argument(...) を実行する。
  4. ap.add_argument(...) を実行する。
  5. args に ap.parse_args() の結果を代入する。
  6. (profile_path, cfg) に load_profile(args.profile_yaml) の結果を代入する。
  7. ident_cfg に get_section(cfg, 'identification') の結果を代入する。
  8. input_dir に os.path.abspath(args.input_dir or ident_cfg.get('input_dir', 'data/identification/raw')) の結果を代入する。
  9. output_dir に os.path.abspath(args.output_dir or ident_cfg.get('output_dir', 'outputs/identification')) の結果を代入する。
  10. os.makedirs(...) を実行する。
  11. python に sys.executable の結果を代入する。
  12. gps_csv に os.path.join(input_dir, 'gps_track.csv') の結果を代入する。
  13. 条件 os.path.exists(gps_csv) を判定し、真なら内部処理を行う。
  14.   run(...) を実行する。
  15. rest_csv に os.path.join(input_dir, 'battery_rest.csv') の結果を代入する。
  16. ocv_csv に os.path.join(output_dir, 'ocv_soc_curve_identified.csv') の結果を代入する。
  17. 条件 os.path.exists(rest_csv) を判定し、真なら内部処理を行う。
  18.   run(...) を実行する。
  19. pulse_csv に os.path.join(input_dir, 'battery_pulse.csv') の結果を代入する。
  20. 条件 os.path.exists(pulse_csv) and os.path.exists(ocv_csv) を判定し、真なら内部処理を行う。
  21.   run(...) を実行する。
  22. panel_csv に os.path.join(input_dir, 'panel_sweep.csv') の結果を代入する。
  23. 条件 os.path.exists(panel_csv) を判定し、真なら内部処理を行う。
  24.   run(...) を実行する。
  25. drive_csv に os.path.join(input_dir, 'drive_timeseries.csv') の結果を代入する。
  26. model_cfg に get_section(cfg, 'model') の結果を代入する。
  27. 条件 os.path.exists(drive_csv) を判定し、真なら内部処理を行う。
  28.   run(...) を実行する。
  29. print(...) を実行する。

代表コード断片:

```python
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile_yaml', required=True)
    ap.add_argument('--input_dir', default='')
    ap.add_argument('--output_dir', default='')
    args = ap.parse_args()

    profile_path, cfg = load_profile(args.profile_yaml)
    ident_cfg = get_section(cfg, 'identification')
    input_dir = os.path.abspath(args.input_dir or ident_cfg.get('input_dir', 'data/identification/raw'))
    output_dir = os.path.abspath(args.output_dir or ident_cfg.get('output_dir', 'outputs/identification'))
    os.makedirs(output_dir, exist_ok=True)

    python = sys.executable

    gps_csv = os.path.join(input_dir, 'gps_track.csv')
    if os.path.exists(gps_csv):
        run([
            python, 'scripts/build_route_profile_from_gps.py',
            '--gps_csv', gps_csv,
            '--out_waypoints_csv', os.path.join(output_dir, 'route_waypoints_identified.csv'),
            '--out_profile_csv', os.path.join(output_dir, 'route_profile_identified.csv'),
        ])

    rest_csv = os.path.join(input_dir, 'battery_rest.csv')
    pulse_csv = os.path.join(input_dir, 'battery_pulse.csv')
    if os.path.exists(rest_csv) != os.path.exists(pulse_csv):
        raise ValueError('battery identification requires both rest and pulse evidence')
    if os.path.exists(rest_csv) and os.path.exists(pulse_csv):
        run([
            python, 'scripts/fit_battery_ecm_from_pulses.py',
            '--rest-csv', rest_csv,
            '--pulse-csv', pulse_csv,
            '--output-dir', os.path.join(output_dir, 'battery_ecm'),
        ])
...
```

旧版の`build_ocv_curve.py`と`build_rint_map_from_timeseries.py`による分離処理は廃止された。OCV、R0,total、R1、tauは、独立SoC付き休止試験とsub-second pulse試験を同時に満たす場合だけ一括同定する。


## CLI 引数

- L22: `--profile_yaml`
- L23: `--input_dir`
- L24: `--output_dir`

## 処理の流れ

1. CLI 引数を解釈し、main() から処理を起動する。
