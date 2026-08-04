# 40. 同定後 fullsim レポート生成

- ファイル: `scripts/generate_fit_fullsim_report.py`
- 種別: `Python`
- 区分: `report`

## 役割

identification run と replay/fullsim の結果をまとめ、説明用レポートへ整形する。

## 起動文脈

- 起動文脈: fit の結果説明と評価集約に使う。
- 呼び出し元: `手動レポート生成`, `後処理パイプライン`
- 次に読むべきファイル: 特になし

## 主要ポイント

- 同定結果と full simulation を一つの説明資料へまとめる。

## 主要構造

主要関数は resolve_path, latex_escape, rel_display, locate_package_dir, locate_fit_summary, rms, day_block_bootstrap_rmse, load_replay_diagnostics。 CLI 引数宣言は 4 件。

## ファイルを上から読んだときの定義順

- L18: matplotlib.use(...) を実行する。
- L21: ROOT に Path(__file__).resolve().parents[1] の結果を代入する。
- L22: 条件 str(ROOT) not in sys.path を判定し、真なら内部処理を行う。
- L38: 関数 resolve_path を定義する。
- L50: 関数 latex_escape を定義する。
- L71: 関数 rel_display を定義する。
- L77: 関数 locate_package_dir を定義する。
- L88: 関数 locate_fit_summary を定義する。
- L119: 関数 rms を定義する。
- L127: 関数 day_block_bootstrap_rmse を定義する。
- L175: 関数 load_replay_diagnostics を定義する。
- L238: 関数 locate_fullsim_manifest を定義する。
- L266: 関数 resolve_manifest_artifact を定義する。
- L277: 関数 load_fullsim_summary を定義する。
- L356: DETAIL_REQUIRED_COLUMNS に {'lower_command_index', 'time_utc', 'step_dt_sec', 'detail_target_dt_sec', 'outer_step_requested_dt_sec', 'outer_step_actual_dt_sec', 'outer_step_boundary_reason', 's_km', 'upper_speed_cmd_kmh', 'lower_speed_cmd_kmh', 'v_exec_kmh', 'soc', 'G_poa', 'Tamb_C', 'Tcell_C', 'P_pv', 'P_aux', 'P_vehicle_load_w', 'P_pack', 'I', 'V', 'OCV', 'Rint', 'Rline', 'eff_drv', 'eff_reg', 'F_aero', 'F_roll', 'F_grade', 'P_inertia', 'param_m', 'param_CdA', 'param_Crr', 'param_P_aux', 'param_E_nom_Wh', 'map_drive_eff_map', 'map_regen_eff_map', 'map_rint_map', 'map_panel_eff_map', 'map_mppt_eff_map', 'map_ocv_soc_map'} の結果を代入する。
- L401: 関数 audit_fullsim_detail を定義する。
- L477: 関数 interpolate_at_distance を定義する。
- L496: 関数 moving_speed_in_interval を定義する。
- L511: 関数 build_human_mpc_distance_comparison を定義する。
- L549: 関数 build_daily_progress_comparison を定義する。
- L570: 関数 write_human_mpc_distance_plot を定義する。
- L627: 関数 md_table を定義する。
- L645: 関数 tex_kv_table を定義する。
- L661: 関数 tex_df_table を定義する。
- L698: 関数 build_report を定義する。
- L1560: 関数 main を定義する。
- L1604: 条件 __name__ == '__main__' を判定し、真なら内部処理を行う。

## import 群

- L2: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L4: `import argparse`
  - CLI 引数を宣言し、実行時パラメータを外から受け取るため。 このファイル内での主な使用位置は L1561。
- L5: `import json`
  - manifest、checkpoint、UDP payload をやり取りするため。 このファイル内での主な使用位置は L290, L1592。
- L6: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での使用位置は少ないか、間接利用である。
- L7: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L74。
- L8: `import sys`
  - sys モジュールを利用するため。 このファイル内での主な使用位置は L22, L23。
- L9: `import textwrap`
  - textwrap モジュールを利用するため。 このファイル内での主な使用位置は L647, L675, L688, L1555。
- L10: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L21, L38, L39, L71, L77, L88, L175, L238, ...。
- L11: `from typing import Dict, Iterable`
  - typing から Dict, Iterable を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L133, L175, L281, L326, L405, L645。
- L13: `import matplotlib`
  - matplotlib モジュールを利用するため。 このファイル内での主な使用位置は L18。
- L14: `import numpy as np`
  - 数値配列、clip、補間、統計計算を行うため。 このファイル内での主な使用位置は L121, L124, L163, L165, L167, L168, L169, L216, ...。
- L15: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L119, L120, L128, L142, L145, L180, L181, L182, ...。
- L16: `import yaml`
  - profile、stop、schedule、summary YAML を読み書きするため。 このファイル内での主な使用位置は L90, L239, L707, L708, L750, L847, L958, L988。
- L19: `import matplotlib.pyplot as plt`
  - matplotlib.pyplot モジュールを利用するため。 このファイル内での主な使用位置は L579, L623。
- L25: `from scripts.build_bwsc2025_fitted_package import BATTERY_E_NOM_MAX_WH, BATTERY_E_NOM_MIN_WH, BATTERY_ETA_CHARGE_MAX, BATTERY_ETA_CHARGE_MIN, BATTERY_RINT_SCALE_MAX, BATTERY_RINT_SCALE_MIN, compile_tex, ensure_dir`
  - build_bwsc2025_fitted_package.py から BATTERY_E_NOM_MAX_WH, BATTERY_E_NOM_MIN_WH, BATTERY_ETA_CHARGE_MAX, BATTERY_ETA_CHARGE_MIN, BATTERY_RINT_SCALE_MAX, BATTERY_RINT_SCALE_MIN, compile_tex, ensure_dir を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは scripts/build_bwsc2025_fitted_package.py。 このファイル内での主な使用位置は L756, L796, L798, L800, L806, L807, L808, L809, ...。
- L35: `from scripts.audit_identification_residuals import weather_and_cruise_metrics`
  - audit_identification_residuals.py から weather_and_cruise_metrics を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは scripts/audit_identification_residuals.py。 このファイル内での主な使用位置は L720, L721。

## 関数・クラスを上から順に解説

### L38 関数 `resolve_path`

- 定義: `resolve_path(base_dir, raw)`
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `exists`, `is_absolute`, `resolve`, `str`, `strip`
- 戻り値の要点: `(base_dir / path).resolve() / base_dir / path / rooted`
- 上から順の処理:
  1. path に Path(str(raw or '').strip()) の結果を代入する。
  2. 条件 not path を判定し、真なら内部処理を行う。
  3. 条件 path.is_absolute() を判定し、真なら内部処理を行う。
  4. rooted に (ROOT / path).resolve() の結果を代入する。
  5. 条件 rooted.exists() を判定し、真なら内部処理を行う。
  6. (base_dir / path).resolve() を返す。

### L50 関数 `latex_escape`

- 定義: `latex_escape(text)`
- このブロックが直接呼ぶ主な関数/メソッド: `items`, `replace`, `str`
- 戻り値の要点: `value`
- 上から順の処理:
  1. value に str(text) の結果を代入する。
  2. repl に {'\\': '\\textbackslash{}', '&': '\\&', '%': '\\%', '$': '\\$', '#': '\\#', '_': '\\_', '{': '\\{', '}': '\\}', '~': '\\textasciitilde{}', '^': '\\textasciicircum{}'} の結果を代入する。
  3. repl.items() を順に走査し、各要素を (src, dst) に入れて処理する。
  4. value に value.replace('/', '/\\allowbreak{}') の結果を代入する。
  5. value に value.replace('\\_', '\\_\\allowbreak{}') の結果を代入する。
  6. value を返す。

### L71 関数 `rel_display`

- 定義: `rel_display(path, base_dir)`
- このブロックが直接呼ぶ主な関数/メソッド: `relpath`, `replace`
- 戻り値の要点: `os.path.relpath(path, base_dir).replace('\\', '/') / 'not found'`
- 上から順の処理:
  1. 条件 path is None を判定し、真なら内部処理を行う。
  2. os.path.relpath(path, base_dir).replace('\\', '/') を返す。

### L77 関数 `locate_package_dir`

- 定義: `locate_package_dir(profile_yaml)`
- docstring: Return the owning project package even for versioned run profiles.
- このブロックが直接呼ぶ主な関数/メソッド: `is_dir`, `resolve`
- 戻り値の要点: `profile_yaml.parent / candidate`
- 上から順の処理:
  1. profile_yaml に profile_yaml.resolve() の結果を代入する。
  2. (profile_yaml.parent, *profile_yaml.parents) を順に走査し、各要素を candidate に入れて処理する。
  3. profile_yaml.parent を返す。

### L88 関数 `locate_fit_summary`

- 定義: `locate_fit_summary(package_dir, profile_yaml)`
- このブロックが直接呼ぶ主な関数/メソッド: `FileNotFoundError`, `exists`, `get`, `glob`, `read_text`, `safe_load`, `sorted`, `stat`, `str`, `strip`
- 戻り値の要点: `candidates[0] / preferred / tagged`
- 上から順の処理:
  1. 条件 profile_yaml is not None and profile_yaml.exists() を判定し、真なら内部処理を行う。
  2. preferred に package_dir / 'outputs' / 'identification' / f'{package_dir.name}_generic_fit_summary.yaml' の結果を代入する。
  3. 条件 preferred.exists() を判定し、真なら内部処理を行う。
  4. candidates に sorted((package_dir / 'outputs' / 'identification').glob('*_generic_fit_summary.yaml'), key=lambda p: p.stat().st_mtime, reverse=True) の結果を代入する。
  5. 条件 not candidates を判定し、真なら内部処理を行う。
  6. candidates[0] を返す。

### L119 関数 `rms`

- 定義: `rms(values)`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `isfinite`, `mean`, `sqrt`, `to_numeric`, `to_numpy`
- 戻り値の要点: `float(np.sqrt(np.mean(arr ** 2))) / float('nan')`
- 上から順の処理:
  1. arr に pd.to_numeric(values, errors='coerce').to_numpy(dtype=float) の結果を代入する。
  2. arr に arr[np.isfinite(arr)] の結果を代入する。
  3. 条件 arr.size == 0 を判定し、真なら内部処理を行う。
  4. float(np.sqrt(np.mean(arr ** 2))) を返す。

### L127 関数 `day_block_bootstrap_rmse`

- 定義: `day_block_bootstrap_rmse(df, residual_column, draws, seed)`
- このブロックが直接呼ぶ主な関数/メソッド: `DataFrame`, `agg`, `assign`, `astype`, `default_rng`, `dropna`, `float`, `groupby`, `int`, `integers`, `len`, `quantile`
- 戻り値の要点: `{'rmse': float(np.sqrt(sse.sum() / count.sum())), 'ci95_min': float(np.quantile(sampled_rmse, 0.025)), 'ci95_max': float(np.quantile(sampled_rmse, 0.975)), 'day_blocks': int(len(blocks)), 'draws': int(draws)} / {'rmse': float('nan'), 'ci95_min': float('nan'), 'ci95_max': float('nan'), 'day_blocks': 0, 'draws': 0} / {'rmse': float('nan'), 'ci95_min': float('nan'), 'ci95_max': float('nan'), 'day_blocks': 0, 'draws': 0}`
- 上から順の処理:
  1. 条件 df.empty or 'local_date' not in df.columns or residual_column not in df.columns を判定し、真なら内部処理を行う。
  2. work に pd.DataFrame({'local_date': df['local_date'].astype(str), 'residual': pd.to_numeric(df[residual_column], errors='coerce')}).dropna() の結果を代入する。
  3. 条件 work.empty を判定し、真なら内部処理を行う。
  4. blocks に work.assign(sq=lambda frame: frame['residual'] ** 2).groupby('local_date').agg(sse=('sq', 'sum'), count=('sq', 'size')) の結果を代入する。
  5. sse に blocks['sse'].to_numpy(dtype=float) の結果を代入する。
  6. count に blocks['count'].to_numpy(dtype=float) の結果を代入する。
  7. rng に np.random.default_rng(seed) の結果を代入する。
  8. samples に rng.integers(0, len(blocks), size=(int(draws), len(blocks))) の結果を代入する。
  9. sampled_rmse に np.sqrt(sse[samples].sum(axis=1) / count[samples].sum(axis=1)) の結果を代入する。
  10. {'rmse': float(np.sqrt(sse.sum() / count.sum())), 'ci95_min': float(np.quantile(sampled_rmse, 0.025)), 'ci95_max': float(np.quantile(sampled_rmse, 0.975)), 'day_blocks': int(len(blocks)), 'draws': int(draws)} を返す。

### L175 関数 `load_replay_diagnostics`

- 定義: `load_replay_diagnostics(package_dir, replay_csv)`
- このブロックが直接呼ぶ主な関数/メソッド: `DataFrame`, `abs`, `agg`, `astype`, `copy`, `exists`, `fillna`, `float`, `getattr`, `groupby`, `mean`, `nlargest`
- 戻り値の要点: `{'replay_csv': replay_csv, 'frame': df, 'clean_frame': clean, 'daily': daily, 'worst_power': worst_power, 'worst_voltage': worst_voltage} / {'replay_csv': replay_csv, 'frame': pd.DataFrame(), 'clean_frame': pd.DataFrame(), 'daily': pd.DataFrame(), 'worst_power': pd.DataFrame(), 'worst_voltage': pd.DataFrame()}`
- 上から順の処理:
  1. replay_csv に replay_csv or package_dir / 'outputs' / 'identification' / 'replay_validation.csv' の結果を代入する。
  2. 条件 not replay_csv.exists() を判定し、真なら内部処理を行う。
  3. df に pd.read_csv(replay_csv, low_memory=False) の結果を代入する。
  4. fallback_ts に pd.to_datetime(df['time_utc'], format='mixed', utc=True, errors='coerce').dt.tz_convert('Australia/Darwin').dt.tz_localize(None) の結果を代入する。
  5. 条件 'time_local' in df.columns を判定し、真なら内部処理を行う。
  6. df['local_date'] に ts.dt.strftime('%Y-%m-%d') の結果を代入する。
  7. df['power_resid_w'] に pd.to_numeric(df['battery_power_w_obs'], errors='coerce') - pd.to_numeric(df['battery_power_w_pred'], errors='coerce') の結果を代入する。
  8. df['voltage_resid_v'] に pd.to_numeric(df['battery_voltage_v_obs'], errors='coerce') - pd.to_numeric(df['battery_voltage_v_pred'], errors='coerce') の結果を代入する。
  9. 条件 'exclude_power_fit' in df.columns を判定し、真なら内部処理を行う。
  10. 条件 'exclude_voltage_fit' in df.columns を判定し、真なら内部処理を行う。

### L238 関数 `locate_fullsim_manifest`

- 定義: `locate_fullsim_manifest(package_dir, profile_yaml)`
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `exists`, `get`, `is_absolute`, `read_text`, `resolve`, `safe_load`, `str`, `strip`
- 戻り値の要点: `None / configured if configured.exists() else None / path`
- 上から順の処理:
  1. profile_cfg に yaml.safe_load(profile_yaml.read_text(encoding='utf-8')) or {} の結果を代入する。
  2. sim に profile_cfg.get('simulation', {}) or {} の結果を代入する。
  3. raw に str(sim.get('latest_manifest_json', '') or '').strip() の結果を代入する。
  4. 条件 raw を判定し、真なら内部処理を行う。
  5. candidates に [package_dir / 'outputs' / 'prerace_fullsim_selflearned' / 'latest_simulation_run.json', package_dir / 'outputs' / 'prerace_final_selflearned' / 'latest_simulation_run.json', package_dir / 'outputs' / 'prerace' / 'latest_simulation_run.json'] の結果を代入する。
  6. candidates を順に走査し、各要素を path に入れて処理する。
  7. None を返す。

### L266 関数 `resolve_manifest_artifact`

- 定義: `resolve_manifest_artifact(manifest_path, raw, package_dir)`
- docstring: Resolve copied manifests whose original absolute path belongs to another host.
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `is_file`, `resolve_path`, `str`, `strip`
- 戻り値の要点: `resolve_path(package_dir, str(raw or '')) / path / local_sibling`
- 上から順の処理:
  1. path に Path(str(raw or '').strip()) の結果を代入する。
  2. 条件 path.is_file() を判定し、真なら内部処理を行う。
  3. local_sibling に manifest_path.parent / path.name の結果を代入する。
  4. 条件 local_sibling.is_file() を判定し、真なら内部処理を行う。
  5. resolve_path(package_dir, str(raw or '')) を返す。

### L277 関数 `load_fullsim_summary`

- 定義: `load_fullsim_summary(package_dir, profile_yaml, manifest_path)`
- このブロックが直接呼ぶ主な関数/メソッド: `DataFrame`, `agg`, `clip`, `exists`, `fillna`, `get`, `getattr`, `groupby`, `issubset`, `items`, `loads`, `locate_fullsim_manifest`
- 戻り値の要点: `{'manifest_path': manifest_path, 'manifest': manifest, 'frame': df, 'daily': daily} / {'manifest_path': None, 'manifest': {}, 'frame': pd.DataFrame(), 'daily': pd.DataFrame()}`
- 上から順の処理:
  1. manifest_path に manifest_path or locate_fullsim_manifest(package_dir, profile_yaml) の結果を代入する。
  2. 条件 manifest_path is None を判定し、真なら内部処理を行う。
  3. manifest に json.loads(manifest_path.read_text(encoding='utf-8')) の結果を代入する。
  4. out_csv に resolve_manifest_artifact(manifest_path, manifest.get('out_csv', ''), package_dir) の結果を代入する。
  5. df に pd.DataFrame() の結果を代入する。
  6. daily に pd.DataFrame() の結果を代入する。
  7. 条件 out_csv.exists() を判定し、真なら内部処理を行う。
  8. {'manifest_path': manifest_path, 'manifest': manifest, 'frame': df, 'daily': daily} を返す。

### L401 関数 `audit_fullsim_detail`

- 定義: `audit_fullsim_detail(package_dir, manifest_path, manifest)`
- このブロックが直接呼ぶ主な関数/メソッド: `bool`, `count_nonzero`, `difference`, `float`, `get`, `int`, `is_file`, `isclose`, `isfinite`, `len`, `list`, `max`
- 戻り値の要点: `{'available': True, 'detail_csv': str(detail_path), 'row_count': rows, 'column_count': len(header), 'required_column_count': len(DETAIL_REQUIRED_COLUMNS), 'missing_required_columns': missing, 'min_step_dt_sec': min_dt if np.isfinite(min_dt) else float('nan'), 'max_step_dt_sec': max_dt if np.isfinite(max_dt) else float('nan'), 'nominal_one_second_rows': nominal_rows, 'boundary_partial_rows': boundary_partial_rows, 'nonfinite_step_rows': nonfinite_step_rows, 'nonpositive_step_rows': nonpositive_rows, 'over_one_second_rows': over_one_second_rows, 'target_not_one_second_rows': target_not_one_second_rows, 'contract_pass': bool(not missing and rows > 0 and (nonfinite_step_rows == 0) and (nonpositive_rows == 0) and (over_one_second_rows == 0) and (target_not_one_second_rows == 0))} / {'available': False, 'reason': 'detail_csv_not_declared'} / {'available': False, 'reason': 'detail_csv_missing', 'detail_csv': str(detail_path)}`
- 上から順の処理:
  1. raw に str(manifest.get('detail_csv', '') or '').strip() の結果を代入する。
  2. 条件 not raw or manifest_path is None を判定し、真なら内部処理を行う。
  3. detail_path に resolve_manifest_artifact(manifest_path, raw, package_dir) の結果を代入する。
  4. 条件 not detail_path.is_file() を判定し、真なら内部処理を行う。
  5. header に list(pd.read_csv(detail_path, nrows=0).columns) の結果を代入する。
  6. missing に sorted(DETAIL_REQUIRED_COLUMNS.difference(header)) の結果を代入する。
  7. rows に 0 の結果を代入する。
  8. nominal_rows に 0 の結果を代入する。
  9. boundary_partial_rows に 0 の結果を代入する。
  10. nonfinite_step_rows に 0 の結果を代入する。

### L477 関数 `interpolate_at_distance`

- 定義: `interpolate_at_distance(df, column, distance_km)`
- このブロックが直接呼ぶ主な関数/メソッド: `DataFrame`, `dropna`, `float`, `groupby`, `interp`, `last`, `sort_values`, `to_numeric`, `to_numpy`
- 戻り値の要点: `float(np.interp(float(distance_km), x, y)) / float('nan') / float('nan') / float('nan')`
- 上から順の処理:
  1. 条件 df.empty or 's_km' not in df.columns or column not in df.columns を判定し、真なら内部処理を行う。
  2. work に pd.DataFrame({'s_km': pd.to_numeric(df['s_km'], errors='coerce'), 'value': pd.to_numeric(df[column], errors='coerce')}).dropna() の結果を代入する。
  3. 条件 work.empty を判定し、真なら内部処理を行う。
  4. work に work.groupby('s_km', as_index=False)['value'].last().sort_values('s_km') の結果を代入する。
  5. x に work['s_km'].to_numpy(dtype=float) の結果を代入する。
  6. y に work['value'].to_numpy(dtype=float) の結果を代入する。
  7. 条件 distance_km < x[0] or distance_km > x[-1] を判定し、真なら内部処理を行う。
  8. float(np.interp(float(distance_km), x, y)) を返す。

### L496 関数 `moving_speed_in_interval`

- 定義: `moving_speed_in_interval(df, column, start_km, end_km)`
- このブロックが直接呼ぶ主な関数/メソッド: `dropna`, `float`, `mean`, `to_numeric`
- 戻り値の要点: `float(values.mean()) if not values.empty else float('nan') / float('nan')`
- 上から順の処理:
  1. 条件 df.empty or 's_km' not in df.columns or column not in df.columns を判定し、真なら内部処理を行う。
  2. distance に pd.to_numeric(df['s_km'], errors='coerce') の結果を代入する。
  3. speed に pd.to_numeric(df[column], errors='coerce') の結果を代入する。
  4. mask に (distance > start_km) & (distance <= end_km) & (speed > 5.0) の結果を代入する。
  5. values に speed.loc[mask].dropna() の結果を代入する。
  6. float(values.mean()) if not values.empty else float('nan') を返す。

### L511 関数 `build_human_mpc_distance_comparison`

- 定義: `build_human_mpc_distance_comparison(replay_df, fullsim_df, retire_distance_km)`
- このブロックが直接呼ぶ主な関数/メソッド: `DataFrame`, `append`, `dropna`, `float`, `get`, `interpolate_at_distance`, `moving_speed_in_interval`, `sorted`, `to_numeric`
- 戻り値の要点: `pd.DataFrame(rows) / pd.DataFrame() / pd.DataFrame()`
- 上から順の処理:
  1. 条件 replay_df.empty or fullsim_df.empty を判定し、真なら内部処理を行う。
  2. endpoints に [500.0, 1000.0, 1500.0, 2000.0, 2500.0, float(retire_distance_km)] の結果を代入する。
  3. endpoints に sorted({value for value in endpoints if 0.0 < value <= retire_distance_km}) の結果を代入する。
  4. human_soc_series に pd.to_numeric(replay_df.get('soc_pred'), errors='coerce').dropna() の結果を代入する。
  5. mpc_soc_series に pd.to_numeric(fullsim_df.get('soc'), errors='coerce').dropna() の結果を代入する。
  6. 条件 human_soc_series.empty or mpc_soc_series.empty を判定し、真なら内部処理を行う。
  7. rows に [] の結果を代入する。
  8. start_km に 0.0 の結果を代入する。
  9. endpoints を順に走査し、各要素を end_km に入れて処理する。
  10. pd.DataFrame(rows) を返す。

### L549 関数 `build_daily_progress_comparison`

- 定義: `build_daily_progress_comparison(replay_df, fullsim_df)`
- このブロックが直接呼ぶ主な関数/メソッド: `DataFrame`, `groupby`, `max`, `merge`, `rename`, `reset_index`, `sort_values`
- 戻り値の要点: `out.reset_index(drop=True) / pd.DataFrame()`
- 上から順の処理:
  1. 条件 replay_df.empty or fullsim_df.empty or 'local_date' not in replay_df or ('local_date' not in fullsim_df) を判定し、真なら内部処理を行う。
  2. human に replay_df.groupby('local_date', as_index=False)['s_km'].max().rename(columns={'s_km': 'human_end_s_km'}) の結果を代入する。
  3. mpc に fullsim_df.groupby('local_date', as_index=False)['s_km'].max().rename(columns={'s_km': 'mpc_end_s_km'}) の結果を代入する。
  4. out に human.merge(mpc, on='local_date', how='outer').sort_values('local_date') の結果を代入する。
  5. out['mpc_progress_lead_km'] に out['mpc_end_s_km'] - out['human_end_s_km'] の結果を代入する。
  6. out.reset_index(drop=True) を返す。

### L570 関数 `write_human_mpc_distance_plot`

- 定義: `write_human_mpc_distance_plot(replay_df, fullsim_df, comparison, output_path, retire_distance_km)`
- このブロックが直接呼ぶ主な関数/メソッド: `apply`, `axvline`, `close`, `dropna`, `grid`, `groupby`, `last`, `legend`, `plot`, `savefig`, `set_xlabel`, `set_ylabel`
- 戻り値の要点: `output_path / None`
- 上から順の処理:
  1. 条件 comparison.empty を判定し、真なら内部処理を行う。
  2. (fig, axes) に plt.subplots(2, 1, figsize=(10.0, 7.0), sharex=True) の結果を代入する。
  3. ((replay_df, 'soc_pred', 'Historical replay reconstruction', 'black', '-'), (fullsim_df, 'soc', 'MPC no-trouble fullsim', '0.35', '--')) を順に走査し、各要素を (df, value_col, label, color, linestyle) に入れて処理する。
  4. axes[0].axvline(...) を実行する。
  5. axes[0].set_ylabel(...) を実行する。
  6. axes[0].grid(...) を実行する。
  7. axes[0].legend(...) を実行する。
  8. axes[1].plot(...) を実行する。
  9. axes[1].plot(...) を実行する。
  10. axes[1].axvline(...) を実行する。

### L627 関数 `md_table`

- 定義: `md_table(df)`
- このブロックが直接呼ぶ主な関数/メソッド: `copy`, `extend`, `is_float_dtype`, `itertuples`, `join`, `len`, `map`, `notna`, `str`
- 戻り値の要点: `'\n'.join(lines) / '_no data_'`
- 上から順の処理:
  1. 条件 df.empty を判定し、真なら内部処理を行う。
  2. data に df.copy() の結果を代入する。
  3. data.columns を順に走査し、各要素を col に入れて処理する。
  4. headers に [str(c) for c in data.columns] の結果を代入する。
  5. rows に [[str(v) for v in row] for row in data.itertuples(index=False, name=None)] の結果を代入する。
  6. sep に ['---'] * len(headers) の結果を代入する。
  7. lines に ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(sep) + ' |'] の結果を代入する。
  8. lines.extend(...) を実行する。
  9. '\n'.join(lines) を返す。

### L645 関数 `tex_kv_table`

- 定義: `tex_kv_table(items)`
- このブロックが直接呼ぶ主な関数/メソッド: `dedent`, `join`, `latex_escape`, `strip`
- 戻り値の要点: `textwrap.dedent(f'\n        \\begin{{longtable}}{{p{{0.46\\linewidth}}p{{0.36\\linewidth}}}}\n        \\toprule\n        項目 & 値 \\\\\n        \\midrule\n        \\endhead\n        {rows}\n        \\bottomrule\n        \\end{{longtable}}\n        ').strip()`
- 上から順の処理:
  1. rows に '\n'.join((f'{latex_escape(k)} & {latex_escape(v)} \\\\' for k, v in items)) の結果を代入する。
  2. textwrap.dedent(f'\n        \\begin{{longtable}}{{p{{0.46\\linewidth}}p{{0.36\\linewidth}}}}\n        \\toprule\n        項目 & 値 \\\\\n        \\midrule\n        \\endhead\n        {rows}\n        \\bottomrule\n        \\end{{longtable}}\n        ').strip() を返す。

### L661 関数 `tex_df_table`

- 定義: `tex_df_table(df, title)`
- このブロックが直接呼ぶ主な関数/メソッド: `astype`, `copy`, `dedent`, `is_float_dtype`, `isna`, `itertuples`, `join`, `latex_escape`, `len`, `map`, `max`, `ravel`
- 戻り値の要点: `textwrap.dedent(f'\n        \\paragraph{{{latex_escape(title)}}}\n        \\begin{{center}}\n        {table}\n        \\end{{center}}\n        ').strip() / f'\\paragraph{{{latex_escape(title)}}} no data available.'`
- 上から順の処理:
  1. 条件 df.empty を判定し、真なら内部処理を行う。
  2. data に df.copy() の結果を代入する。
  3. data.columns を順に走査し、各要素を col に入れて処理する。
  4. headers に ' & '.join((latex_escape(c) for c in data.columns)) + ' \\\\' の結果を代入する。
  5. rows に '\n'.join((' & '.join((latex_escape(v) for v in row)) + ' \\\\' for row in data.astype(str).itertuples(index=False, name=None))) の結果を代入する。
  6. max_cell_len に max((len(str(value)) for value in data.to_numpy().ravel()), default=0) の結果を代入する。
  7. 条件 len(data.columns) == 2 and max_cell_len > 48 を判定し、真なら内部処理を行う。
  8. table に textwrap.dedent(f'\n        \\begin{{tabular}}{{{colspec}}}\n        \\toprule\n        {headers}\n        \\midrule\n        {rows}\n        \\bottomrule\n        \\end{{tabular}}\n        ').strip() の結果を代入する。
  9. 条件 len(data.columns) >= 4 を判定し、真なら内部処理を行う。
  10. textwrap.dedent(f'\n        \\paragraph{{{latex_escape(title)}}}\n        \\begin{{center}}\n        {table}\n        \\end{{center}}\n        ').strip() を返す。

### L698 関数 `build_report`

- 定義: `build_report(package_dir, profile_yaml, fit_summary_path, replay_csv, fullsim_manifest)`
- このブロックが直接呼ぶ主な関数/メソッド: `DataFrame`, `Path`, `Series`, `abs`, `any`, `append`, `audit_fullsim_detail`, `bool`, `build_daily_progress_comparison`, `build_human_mpc_distance_comparison`, `compile_tex`, `day_block_bootstrap_rmse`
- 戻り値の要点: `(md_path, tex_path.with_suffix('.pdf'))`
- 上から順の処理:
  1. fit_summary_path に fit_summary_path or locate_fit_summary(package_dir, profile_yaml) の結果を代入する。
  2. fit_summary に yaml.safe_load(fit_summary_path.read_text(encoding='utf-8')) or {} の結果を代入する。
  3. profile に yaml.safe_load(profile_yaml.read_text(encoding='utf-8')) or {} の結果を代入する。
  4. 条件 replay_csv is None を判定し、真なら内部処理を行う。
  5. replay に load_replay_diagnostics(package_dir, replay_csv) の結果を代入する。
  6. end_to_end_replay_path に fit_summary_path.parent / 'replay_validation_end_to_end.csv' の結果を代入する。
  7. end_to_end_replay に pd.read_csv(end_to_end_replay_path, low_memory=False) if end_to_end_replay_path.is_file() else replay.get('frame', pd.DataFrame()) の結果を代入する。
  8. (weather_daily, _) に weather_and_cruise_metrics(end_to_end_replay) の結果を代入する。
  9. (_, cruise_70kmh) に weather_and_cruise_metrics(replay.get('frame', pd.DataFrame())) の結果を代入する。
  10. cruise_70kmh_rows に pd.DataFrame([{'metric': key, 'value': value} for key, value in cruise_70kmh.items()]) の結果を代入する。

### L1560 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `ArgumentParser`, `add_argument`, `build_report`, `dumps`, `locate_package_dir`, `parse_args`, `print`, `resolve_path`, `str`
- 上から順の処理:
  1. ap に argparse.ArgumentParser() の結果を代入する。
  2. ap.add_argument(...) を実行する。
  3. ap.add_argument(...) を実行する。
  4. ap.add_argument(...) を実行する。
  5. ap.add_argument(...) を実行する。
  6. args に ap.parse_args() の結果を代入する。
  7. profile_yaml に resolve_path(ROOT, args.profile) の結果を代入する。
  8. package_dir に locate_package_dir(profile_yaml) の結果を代入する。
  9. fit_summary_path に resolve_path(ROOT, args.fit_summary) if args.fit_summary else None の結果を代入する。
  10. replay_csv に resolve_path(ROOT, args.replay_csv) if args.replay_csv else None の結果を代入する。


## CLI 引数

- L1562: `--profile`
- L1563: `--fit-summary`
- L1568: `--replay-csv`
- L1573: `--fullsim-manifest`

## 処理の流れ

1. CLI 引数を解釈し、main() から処理を起動する。
