# 38. upper mesh 収束確認

- ファイル: `scripts/run_upper_mesh_convergence.py`
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
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L116。
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

## 関数・クラスを上から順に解説

### L22 関数 `parse_float_list`

- 定義: `parse_float_list(value)`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `split`, `str`, `strip`
- 戻り値の要点: `[float(item) for item in str(value).split(',') if item.strip()]`
- 上から順の処理:
  1. [float(item) for item in str(value).split(',') if item.strip()] を返す。

### L26 関数 `parse_control_policies`

- 定義: `parse_control_policies(values)`
- このブロックが直接呼ぶ主な関数/メソッド: `FileNotFoundError`, `Path`, `ValueError`, `float`, `is_file`, `partition`, `resolve`, `str`, `strip`
- 戻り値の要点: `policies`
- 上から順の処理:
  1. policies に {} を代入する。
  2. values を順に走査し、各要素を raw に入れて処理する。
  3. policies を返す。

### L42 関数 `assign_finest_control_policy`

- 定義: `assign_finest_control_policy(control_meshes, supplied_policies, finest_policy)`
- docstring: Assign --policy to the finest requested control mesh without relabelling it.
- このブロックが直接呼ぶ主な関数/メソッド: `ValueError`, `dict`, `float`, `min`, `resolve`
- 戻り値の要点: `(finest_ctrl, policies, order)`
- 上から順の処理:
  1. 条件 not control_meshes を判定し、真なら内部処理を行う。
  2. finest_ctrl に min((float(value) for value in control_meshes)) の結果を代入する。
  3. policies に dict(supplied_policies) の結果を代入する。
  4. policies[finest_ctrl] に finest_policy.resolve() の結果を代入する。
  5. order に [float(ctrl) for ctrl in control_meshes if float(ctrl) in policies] の結果を代入する。
  6. (finest_ctrl, policies, order) を返す。

### L57 関数 `file_sha256`

- 定義: `file_sha256(path)`
- このブロックが直接呼ぶ主な関数/メソッド: `hexdigest`, `iter`, `open`, `read`, `sha256`, `update`
- 戻り値の要点: `digest.hexdigest()`
- 上から順の処理:
  1. digest に hashlib.sha256() の結果を代入する。
  2. with 文で path.open('rb') を管理しながら処理する。
  3. digest.hexdigest() を返す。

### L65 関数 `resolve`

- 定義: `resolve(profile, value)`
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `is_absolute`, `resolve`, `str`
- 戻り値の要点: `path if path.is_absolute() else (profile.parent / path).resolve()`
- 上から順の処理:
  1. path に Path(str(value)) の結果を代入する。
  2. path if path.is_absolute() else (profile.parent / path).resolve() を返す。

### L70 関数 `load_plan`

- 定義: `load_plan(summary)`
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `is_absolute`, `read_csv`, `resolve`, `sort_values`
- 戻り値の要点: `frame.sort_values('plan_s_km')`
- 上から順の処理:
  1. path に Path(summary['plan_csv']) の結果を代入する。
  2. 条件 not path.is_absolute() を判定し、真なら内部処理を行う。
  3. frame に pd.read_csv(path) の結果を代入する。
  4. frame.sort_values('plan_s_km') を返す。

### L78 関数 `speed_rms_difference`

- 定義: `speed_rms_difference(left, right, race_km)`
- このブロックが直接呼ぶ主な関数/メソッド: `arange`, `float`, `interp`, `mean`, `sqrt`
- 戻り値の要点: `float(np.sqrt(np.mean((left_v - right_v) ** 2)))`
- 上から順の処理:
  1. grid に np.arange(0.0, race_km + 1.0, 1.0) の結果を代入する。
  2. left_v に np.interp(grid, left['plan_s_km'], left['plan_v_kmh']) の結果を代入する。
  3. right_v に np.interp(grid, right['plan_s_km'], right['plan_v_kmh']) の結果を代入する。
  4. float(np.sqrt(np.mean((left_v - right_v) ** 2))) を返す。

### L85 関数 `materialize_profile`

- 定義: `materialize_profile(base_path, output_path, policy_path, ds_km, ctrl_km)`
- このブロックが直接呼ぶ主な関数/メソッド: `ceil`, `float`, `get`, `int`, `items`, `list`, `mkdir`, `read_text`, `resolve`, `safe_dump`, `safe_load`, `str`
- 戻り値の要点: `cfg`
- 上から順の処理:
  1. cfg に yaml.safe_load(base_path.read_text(encoding='utf-8')) or {} の結果を代入する。
  2. list((cfg.get('paths', {}) or {}).items()) を順に走査し、各要素を (key, value) に入れて処理する。
  3. ('fit_summary_yaml', 'terminal_consistency_yaml') を順に走査し、各要素を key に入れて処理する。
  4. cfg['paths']['initial_upper_policy_csv'] に str(policy_path.resolve()) の結果を代入する。
  5. race_km に float(cfg['mpc']['race_km']) の結果を代入する。
  6. run_dir に output_path.parent の結果を代入する。
  7. cfg['meta']['name'] に f'mesh_ds{ds_km:g}_ctrl{ctrl_km:g}' の結果を代入する。
  8. cfg['simulation'].update(...) を実行する。
  9. cfg['mpc'].update(...) を実行する。
  10. output_path.parent.mkdir(...) を実行する。

### L131 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `ArgumentParser`, `DataFrame`, `Path`, `RuntimeError`, `abs`, `add_argument`, `all`, `append`, `assign_finest_control_policy`, `bool`, `dumps`, `encode`
- 戻り値の要点: `0 if gate_pass else 2`
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
