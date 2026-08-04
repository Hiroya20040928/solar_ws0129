# 34. テンプレ識別パイプライン入口

- ファイル: `scripts/run_identification_pipeline.py`
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

## 関数・クラスを上から順に解説

### L15 関数 `run`

- 定義: `run(cmd)`
- このブロックが直接呼ぶ主な関数/メソッド: `join`, `print`, `run`
- 上から順の処理:
  1. print(...) を実行する。
  2. subprocess.run(...) を実行する。

### L20 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `ArgumentParser`, `abspath`, `add_argument`, `exists`, `get`, `get_section`, `join`, `load_profile`, `makedirs`, `parse_args`, `print`, `run`
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


## CLI 引数

- L22: `--profile_yaml`
- L23: `--input_dir`
- L24: `--output_dir`

## 処理の流れ

1. CLI 引数を解釈し、main() から処理を起動する。
