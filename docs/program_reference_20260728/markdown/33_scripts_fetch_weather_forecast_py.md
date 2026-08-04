# 33. offline forecast 取得 CLI

- ファイル: `scripts/fetch_weather_forecast.py`
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

## 関数・クラスを上から順に解説

### L17 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `ArgumentParser`, `abspath`, `add_argument`, `dirname`, `exists`, `fetch_openmeteo_forecast`, `float`, `get`, `get_path`, `get_section`, `int`, `len`
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
