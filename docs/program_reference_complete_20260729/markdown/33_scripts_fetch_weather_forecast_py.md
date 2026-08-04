# 33. offline forecast 取得 CLI

- ファイル: `scripts/fetch_weather_forecast.py`
- ソースSHA-256: `89625bc3ee8176f508e8917c42d1f594469963010840d1a1dc1b8096627bab19`
- 種別: `Python`
- 区分: `offline tool`

## 役割

profile に基づき計画用 weather forecast CSV を取得・保存する CLI スクリプト。

## 起動文脈

- 起動文脈: forecast action で直接呼ばれる。
- 呼び出し元: `scripts/solar_control.sh`
- 次に読むべきファイル: `mpc_solarcar/weather_utils.py`, `mpc_solarcar/solar_profile.py`

## 主要ポイント

- live node 版より単発実行向け。

## 主要構造

主要関数は main。 CLI 引数宣言は 8 件。

## ファイルを上から読んだときの定義順

- L9: ROOT に Path(__file__).resolve().parents[1] の結果を代入する。
- L10: 条件 str(ROOT) not in sys.path を判定し、真なら内部処理を行う。
- L17: 関数 main を定義する。
- L82: 条件 __name__ == '__main__' を判定し、真なら内部処理を行う。

## import 群

- L2: `import argparse`
  - CLI 引数を宣言し、実行時パラメータを外から受け取るため。 このファイル内での主な使用位置は L18。
- L3: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L54, L77。
- L4: `import sys`
  - sys モジュールを利用するため。 このファイル内での主な使用位置は L10, L11。
- L5: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L9。
- L7: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L55。
- L13: `from mpc_solarcar.solar_profile import get_path, get_section, load_profile, merged_dict`
  - profile YAML 読込と検証 から get_path, get_section, load_profile, merged_dict を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/solar_profile.py。 このファイル内での主な使用位置は L29, L30, L31, L32, L39, L51, L52。
- L14: `from mpc_solarcar.weather_utils import fetch_openmeteo_forecast, write_forecast_csv`
  - weather_utils.py から fetch_openmeteo_forecast, write_forecast_csv を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/weather_utils.py。 このファイル内での主な使用位置は L69, L78。

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

### 天候、route、補間、時刻、単位

予報は時刻だけの系列か、時刻とroute距離の2次元gridになり得る。現在時刻tと距離sがgrid点の間なら、周囲の値から補間して日射、温度、風を求める。

UTC、現地timezone、naive datetimeを混ぜると数時間のずれが発生する。入力でtimezoneを確定し、内部比較はUTC、表示は現地時刻という役割分担が安全である。

route距離のkm、速度のkm/hとm/s、時間の秒、energyのWhとJを跨ぐため、変換係数3.6、3600、1000の意味を各式で確認する。

### freshness、filter、guard、fallback、fail-safe

分散システムでは最後に受け取った値が現在も有効とは限らない。受信時刻とtimeoutからfreshnessを判定し、stale値を計画状態へ無条件に同期しない。

filterはnoiseと一時的な飛び値を抑えるが、遅れを生む。slew limitは指令変化率を制限する。安全guardはsolverのcost罰則とは別に、現在出力へ強制制約を適用する最後の防波堤である。

fallbackは失敗時の代替動作を事前に決める設計である。前回計画保持、物理に基づく決定論的入力、停止、低速制限などから、故障modeごとに選ぶ。fallback発生はstatusとlogへ残し、正常解と区別する。

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

### L17 関数 `main`

- 定義: `main()`
- 行範囲: L17-L79
- このブロックが直接呼ぶ主な関数/メソッド: `ArgumentParser`, `abspath`, `add_argument`, `dirname`, `exists`, `fetch_openmeteo_forecast`, `float`, `get`, `get_path`, `get_section`, `int`, `len`
- この呼出し内で代入する主なローカル名: `ap`, `args`, `cfg`, `df`, `lat`, `live_cfg`, `lon`, `out_csv`, `profile_path`, `route_csv`, `route_df`, `runtime_cfg`, `weather_cfg`
- 制御構造の規模: 条件分岐 8、ループ 0、try 0
- 上から順の処理:
  1. ap に argparse.ArgumentParser() の結果を代入する。
  2. ap.add_argument(...) を実行する。
  3. ap.add_argument(...) を実行する。
  4. ap.add_argument(...) を実行する。
  5. ap.add_argument(...) を実行する。
  6. ap.add_argument(...) を実行する。
  7. ap.add_argument(...) を実行する。
  8. ap.add_argument(...) を実行する。
  9. ap.add_argument(...) を実行する。
  10. args に ap.parse_args() の結果を代入する。
  11. (profile_path, cfg) に load_profile(args.profile_yaml) の結果を代入する。
  12. runtime_cfg に get_section(cfg, 'runtime') の結果を代入する。
  13. live_cfg に get_section(cfg, 'live') の結果を代入する。
  14. weather_cfg に merged_dict({'forecast_days': 3, 'step_minutes': 10, 'timezone_name': 'Australia/Darwin', 'fallback_latitude': live_cfg.get('fallback_latitude', None), 'fallback_longitude': live_cfg.get('fallback_longitude', None), 'tcell_gain': 0.03}, get_section(live_cfg, 'weather')) の結果を代入する。
  15. 条件 not weather_cfg.get('timezone_name') を判定し、真なら内部処理を行う。
  16.   weather_cfg['timezone_name'] に str(live_cfg.get('forecast_time_tz', runtime_cfg.get('forecast_time_tz', 'Australia/Darwin'))) の結果を代入する。
  17. 条件 args.forecast_days is not None を判定し、真なら内部処理を行う。
  18.   weather_cfg['forecast_days'] に args.forecast_days の結果を代入する。
  19. 条件 args.step_minutes is not None を判定し、真なら内部処理を行う。
  20.   weather_cfg['step_minutes'] に args.step_minutes の結果を代入する。
  21. 条件 args.timezone_name is not None を判定し、真なら内部処理を行う。
  22.   weather_cfg['timezone_name'] に args.timezone_name の結果を代入する。
  23. 条件 args.tcell_gain is not None を判定し、真なら内部処理を行う。
  24.   weather_cfg['tcell_gain'] に args.tcell_gain の結果を代入する。
  25. out_csv に args.out_csv or get_path(cfg, profile_path, 'forecast_csv') の結果を代入する。
  26. route_csv に get_path(cfg, profile_path, 'route_waypoints_csv') の結果を代入する。
  27. 条件 args.latitude is None or args.longitude is None を判定し、真なら内部処理を行う。
  28.   条件 route_csv and os.path.exists(route_csv) を判定し、真なら内部処理を行う。
  29.     route_df に pd.read_csv(route_csv) の結果を代入する。
  30.     条件 len(route_df) > 0 and 'lat' in route_df.columns and ('lon' in route_df.columns) を判定し、真なら内部処理を行う。
  31.       lat に float(route_df.iloc[0]['lat']) の結果を代入する。
  32.       lon に float(route_df.iloc[0]['lon']) の結果を代入する。
  33.       上の条件が偽の場合:
  34.       lat に float(weather_cfg.get('fallback_latitude', -12.4634)) の結果を代入する。
  35.       lon に float(weather_cfg.get('fallback_longitude', 130.8456)) の結果を代入する。
  36.     上の条件が偽の場合:
  37.     lat に float(weather_cfg.get('fallback_latitude', -12.4634)) の結果を代入する。
  38.     lon に float(weather_cfg.get('fallback_longitude', 130.8456)) の結果を代入する。
  39.   上の条件が偽の場合:
  40.   lat に float(args.latitude) の結果を代入する。
  41.   lon に float(args.longitude) の結果を代入する。
  42. df に fetch_openmeteo_forecast(lat, lon, timezone_name=str(weather_cfg.get('timezone_name', 'Australia/Darwin')), forecast_days=int(weather_cfg.get('forecast_days', 3)), step_minutes=int(weather_cfg.get('step_minutes', 10)), tcell_gain=float(weather_cfg.get('tcell_gain', 0.03))) の結果を代入する。
  43. os.makedirs(...) を実行する。
  44. write_forecast_csv(...) を実行する。
  45. print(...) を実行する。

代表コード断片:

```python
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--profile_yaml', required=True)
    ap.add_argument('--latitude', type=float, default=None)
    ap.add_argument('--longitude', type=float, default=None)
    ap.add_argument('--out_csv', default='')
    ap.add_argument('--forecast_days', type=int, default=None)
    ap.add_argument('--step_minutes', type=int, default=None)
    ap.add_argument('--timezone_name', default=None)
    ap.add_argument('--tcell_gain', type=float, default=None)
    args = ap.parse_args()

    profile_path, cfg = load_profile(args.profile_yaml)
    runtime_cfg = get_section(cfg, 'runtime')
    live_cfg = get_section(cfg, 'live')
    weather_cfg = merged_dict({
        'forecast_days': 3,
        'step_minutes': 10,
        'timezone_name': 'Australia/Darwin',
        'fallback_latitude': live_cfg.get('fallback_latitude', None),
        'fallback_longitude': live_cfg.get('fallback_longitude', None),
        'tcell_gain': 0.03,
    }, get_section(live_cfg, 'weather'))
    if not weather_cfg.get('timezone_name'):
        weather_cfg['timezone_name'] = str(live_cfg.get('forecast_time_tz', runtime_cfg.get('forecast_time_tz', 'Australia/Darwin')))
    if args.forecast_days is not None:
        weather_cfg['forecast_days'] = args.forecast_days
    if args.step_minutes is not None:
        weather_cfg['step_minutes'] = args.step_minutes
    if args.timezone_name is not None:
        weather_cfg['timezone_name'] = args.timezone_name
    if args.tcell_gain is not None:
        weather_cfg['tcell_gain'] = args.tcell_gain

    out_csv = args.out_csv or get_path(cfg, profile_path, 'forecast_csv')
...
```


## CLI 引数

- L19: `--profile_yaml`
- L20: `--latitude`
- L21: `--longitude`
- L22: `--out_csv`
- L23: `--forecast_days`
- L24: `--step_minutes`
- L25: `--timezone_name`
- L26: `--tcell_gain`

## 処理の流れ

1. CLI 引数を解釈し、main() から処理を起動する。
