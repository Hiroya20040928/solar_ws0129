# 15. 上位速度計画の補間と warm start

- ファイル: `mpc_solarcar/upper_policy.py`
- 種別: `Python`
- 区分: `planner helper`

## 役割

外部 speed policy CSV と前回解を絶対距離基準で現在メッシュへ補間し直す。

## 起動文脈

- 起動文脈: upper planner の初期値品質を決める補助。
- 呼び出し元: `mpc_node.py`, `scripts/solar_sim.py`
- 次に読むべきファイル: `mpc_solarcar/upper_solver.py`

## 主要ポイント

- absolute_control_distances と shift_upper_policy_warm_start が重要。
- 相対距離ではなくルート絶対距離に揃える修正済み箇所。

## 主要構造

主要関数は absolute_control_distances, shift_upper_policy_warm_start, load_upper_policy_csv, interpolate_upper_policy。

## ファイルを上から読んだときの定義順

- L9: 関数 _finite_vector を定義する。
- L16: 関数 absolute_control_distances を定義する。
- L27: 関数 shift_upper_policy_warm_start を定義する。
- L57: 関数 load_upper_policy_csv を定義する。
- L81: 関数 interpolate_upper_policy を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L57, L59。
- L5: `import numpy as np`
  - 数値配列、clip、補間、統計計算を行うため。 このファイル内での主な使用位置は L9, L10, L11, L16, L19, L22, L34, L41, ...。
- L6: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L57, L60, L65, L66, L82, L90, L91。

## 関数・クラスを上から順に解説

### L9 関数 `_finite_vector`

- 定義: `_finite_vector(values, name)`
- このブロックが直接呼ぶ主な関数/メソッド: `ValueError`, `all`, `asarray`, `isfinite`, `len`
- 戻り値の要点: `vector`
- 上から順の処理:
  1. vector に np.asarray(values, dtype=float) の結果を代入する。
  2. 条件 vector.ndim != 1 or len(vector) == 0 or (not np.all(np.isfinite(vector))) を判定し、真なら内部処理を行う。
  3. vector を返す。

### L16 関数 `absolute_control_distances`

- 定義: `absolute_control_distances(start_s_km, relative_control_s_km)`
- docstring: Convert a horizon-relative control mesh to route-absolute distances.
- このブロックが直接呼ぶ主な関数/メソッド: `ValueError`, `_finite_vector`, `any`, `diff`, `float`, `isfinite`
- 戻り値の要点: `start + relative`
- 上から順の処理:
  1. start に float(start_s_km) の結果を代入する。
  2. 条件 not np.isfinite(start) を判定し、真なら内部処理を行う。
  3. relative に _finite_vector(relative_control_s_km, name='relative_control_s_km') の結果を代入する。
  4. 条件 np.any(relative < -1e-09) or np.any(np.diff(relative) < -1e-09) を判定し、真なら内部処理を行う。
  5. start + relative を返す。

### L27 関数 `shift_upper_policy_warm_start`

- 定義: `shift_upper_policy_warm_start(previous_control_s_km, previous_speeds_kmh, current_control_s_km, minimum_speed_kmh, maximum_speed_kmh)`
- docstring: Shift a prior route-indexed policy onto the current absolute control mesh.
- このブロックが直接呼ぶ主な関数/メソッド: `ValueError`, `_finite_vector`, `any`, `argsort`, `clip`, `diff`, `float`, `interp`, `len`, `unique`
- 戻り値の要点: `np.clip(shifted, float(minimum_speed_kmh), float(maximum_speed_kmh))`
- 上から順の処理:
  1. previous_s に _finite_vector(previous_control_s_km, name='previous_control_s_km') の結果を代入する。
  2. previous_v に _finite_vector(previous_speeds_kmh, name='previous_speeds_kmh') の結果を代入する。
  3. current_s に _finite_vector(current_control_s_km, name='current_control_s_km') の結果を代入する。
  4. 条件 len(previous_s) != len(previous_v) を判定し、真なら内部処理を行う。
  5. 条件 np.any(np.diff(current_s) < -1e-09) を判定し、真なら内部処理を行う。
  6. order に np.argsort(previous_s, kind='stable') の結果を代入する。
  7. previous_s に previous_s[order] の結果を代入する。
  8. previous_v に previous_v[order] の結果を代入する。
  9. (unique_s, reverse_index) に np.unique(previous_s[::-1], return_index=True) の結果を代入する。
  10. keep に len(previous_s) - 1 - reverse_index の結果を代入する。

### L57 関数 `load_upper_policy_csv`

- 定義: `load_upper_policy_csv(path)`
- docstring: Load a distance-indexed upper speed policy with strict schema checks.
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `ValueError`, `copy`, `drop_duplicates`, `dropna`, `float`, `issubset`, `len`, `read_csv`, `replace`, `reset_index`, `sort_values`
- 戻り値の要点: `out`
- 上から順の処理:
  1. policy_path に Path(path) の結果を代入する。
  2. frame に pd.read_csv(policy_path) の結果を代入する。
  3. required に {'s_km', 'v_kmh'} の結果を代入する。
  4. 条件 not required.issubset(frame.columns) を判定し、真なら内部処理を行う。
  5. out に frame.loc[:, ['s_km', 'v_kmh']].copy() の結果を代入する。
  6. out['s_km'] に pd.to_numeric(out['s_km'], errors='coerce') の結果を代入する。
  7. out['v_kmh'] に pd.to_numeric(out['v_kmh'], errors='coerce') の結果を代入する。
  8. out に out.replace([np.inf, -np.inf], np.nan).dropna().sort_values('s_km').drop_duplicates('s_km', keep='last').reset_index(drop=True) の結果を代入する。
  9. 条件 len(out) < 2 を判定し、真なら内部処理を行う。
  10. 条件 float(out['s_km'].iloc[-1]) <= float(out['s_km'].iloc[0]) を判定し、真なら内部処理を行う。

### L81 関数 `interpolate_upper_policy`

- 定義: `interpolate_upper_policy(frame, control_s_km, minimum_speed_kmh, maximum_speed_kmh)`
- docstring: Interpolate a learned full-course policy onto the current MPC control mesh.
- このブロックが直接呼ぶ主な関数/メソッド: `ValueError`, `_finite_vector`, `all`, `clip`, `float`, `interp`, `isfinite`, `len`, `to_numeric`, `to_numpy`
- 戻り値の要点: `np.clip(interpolated, float(minimum_speed_kmh), float(maximum_speed_kmh))`
- 上から順の処理:
  1. control_s に _finite_vector(control_s_km, name='control_s_km') の結果を代入する。
  2. source_s に pd.to_numeric(frame['s_km'], errors='coerce').to_numpy(dtype=float) の結果を代入する。
  3. source_v に pd.to_numeric(frame['v_kmh'], errors='coerce').to_numpy(dtype=float) の結果を代入する。
  4. 条件 len(source_s) < 2 or not np.all(np.isfinite(source_s)) or (not np.all(np.isfinite(source_v))) を判定し、真なら内部処理を行う。
  5. interpolated に np.interp(control_s, source_s, source_v) の結果を代入する。
  6. np.clip(interpolated, float(minimum_speed_kmh), float(maximum_speed_kmh)) を返す。


## 処理の流れ

1. ソース中の主要関数を通じて処理を進める。
