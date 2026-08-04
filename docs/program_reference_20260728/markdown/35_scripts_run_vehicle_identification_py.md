# 35. フル MLE 同定本体

- ファイル: `scripts/run_vehicle_identification.py`
- 種別: `Python`
- 区分: `identification`

## 役割

実車ログ、weather、grounded maps、battery/PV/vehicle モデルを用いて MLE 同定を実行する大型スクリプト。

## 起動文脈

- 起動文脈: fit action の本丸。
- 呼び出し元: `scripts/solar_control.sh`
- 次に読むべきファイル: `scripts/generate_fit_fullsim_report.py`, `scripts/tune_upper_planner_weights.py`

## 主要ポイント

- 出力 tag を持つ immutable run を作る。
- adopt までは canonical profile を上書きしない流れに対応する。

## 主要構造

主要関数は neutralize_identification_scalars, resolve_relative, stage, load_manifest, relpath_from, tex_path_fragment, tex_text_fragment, load_yaml_if_exists。 CLI 引数宣言は 9 件。

## ファイルを上から読んだときの定義順

- L20: SCRIPT_DIR に Path(__file__).resolve().parent の結果を代入する。
- L21: ROOT に SCRIPT_DIR.parents[0] の結果を代入する。
- L22: (SCRIPT_DIR, ROOT) を順に走査し、各要素を candidate に入れて処理する。
- L67: FIT_QUALITY_PRESETS に {'quick': {'battery_restart_count': 2, 'battery_maxiter': 50, 'motion_restart_count': 3, 'motion_maxiter': 70, 'joint_restart_count': 2, 'joint_random_start_count': 8, 'joint_local_topk': 2, 'joint_maxiter': 24, 'fit_stride': 3, 'allow_map_shape_fit': False, 'post_refine_enabled': False}, 'standard': {'battery_restart_count': 4, 'battery_maxiter': 80, 'motion_restart_count': 5, 'motion_maxiter': 100, 'joint_restart_count': 4, 'joint_random_start_count': 6, 'joint_local_topk': 3, 'joint_maxiter': 40, 'fit_stride': 2, 'allow_map_shape_fit': True, 'post_refine_enabled': False}, 'full': {'battery_restart_count': 6, 'battery_maxiter': 140, 'motion_restart_count': 8, 'motion_maxiter': 180, 'joint_restart_count': 6, 'joint_random_start_count': 18, 'joint_local_topk': 6, 'joint_maxiter': 80, 'fit_stride': 2, 'allow_map_shape_fit': True, 'post_refine_enabled': False}, 'ultra': {'battery_restart_count': 8, 'battery_maxiter': 220, 'motion_restart_count': 10, 'motion_maxiter': 260, 'joint_restart_count': 8, 'joint_random_start_count': 28, 'joint_local_topk': 8, 'joint_maxiter': 120, 'fit_stride': 1, 'allow_map_shape_fit': True, 'post_refine_enabled': True}} を代入する。
- L123: 関数 neutralize_identification_scalars を定義する。
- L135: 関数 resolve_relative を定義する。
- L144: 関数 stage を定義する。
- L148: 関数 load_manifest を定義する。
- L168: 関数 relpath_from を定義する。
- L177: 関数 tex_path_fragment を定義する。
- L199: 関数 tex_text_fragment を定義する。
- L216: 関数 load_yaml_if_exists を定義する。
- L223: 関数 declared_control_stop_km を定義する。
- L245: 関数 _terminal_anchor_from_payload を定義する。
- L292: 関数 _append_reason_column を定義する。
- L300: 関数 resolve_manifest_context を定義する。
- L413: 関数 hampel_mask を定義する。
- L425: 関数 apply_sensor_quality_annotations を定義する。
- L520: 関数 polarization_current_trace を定義する。
- L544: 関数 fit_battery_polarization を定義する。
- L682: 関数 apply_battery_polarization を定義する。
- L706: 関数 resolve_fit_plan を定義する。
- L750: 関数 resolve_identification_output_layout を定義する。
- L777: 関数 identification_profile_output_path を定義する。
- L789: 関数 load_ocv_df を定義する。
- L797: 関数 build_source_map_assets を定義する。
- L821: 関数 apply_actual_event_annotations を定義する。
- L863: 関数 truncate_at_retire_event を定義する。
- L892: 関数 normalize_generic_log を定義する。
- L994: 関数 build_terminal_anchor を定義する。

## import 群

- L2: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L4: `import argparse`
  - CLI 引数を宣言し、実行時パラメータを外から受け取るため。 このファイル内での主な使用位置は L3076。
- L5: `import json`
  - manifest、checkpoint、UDP payload をやり取りするため。 このファイル内での主な使用位置は L3181, L3841。
- L6: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L539, L1595, L1596, L1834, L3619。
- L7: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L23, L172, L174, L2013, L2014, L2380, L2381, L2382, ...。
- L8: `import re`
  - re モジュールを利用するため。 このファイル内での主な使用位置は L764。
- L9: `import sys`
  - sys モジュールを利用するため。 このファイル内での主な使用位置は L24, L25。
- L10: `import textwrap`
  - textwrap モジュールを利用するため。 このファイル内での主な使用位置は L3070。
- L11: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L20, L135, L136, L148, L151, L158, L168, L216, ...。
- L12: `from typing import Any, Dict, Tuple`
  - typing から Any, Dict, Tuple を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L67, L148, L245, L251, L331, L366, L544, L600, ...。
- L14: `import numpy as np`
  - 数値配列、clip、補間、統計計算を行うため。 このファイル内での主な使用位置は L296, L422, L458, L466, L492, L502, L512, L525, ...。
- L15: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L292, L413, L414, L426, L430, L464, L465, L466, ...。
- L16: `import yaml`
  - profile、stop、schedule、summary YAML を読み書きするため。 このファイル内での主な使用位置は L164, L220, L2154, L2164, L2174, L2311, L2333, L2349, ...。
- L17: `from scipy.optimize import least_squares`
  - scipy.optimize から least_squares を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L1206, L1213, L1232。
- L18: `from scipy.signal import savgol_filter`
  - scipy.signal から savgol_filter を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L1304, L1643。
- L27: `from build_bwsc2025_fitted_package import BATTERY_PACK_MAX_CHARGE_V, BATTERY_NOMINAL_VOLTAGE_V, INVALID_PACK_VOLTAGE_MIN_V, ROOT, TIMEZONE_LOCAL, BatteryFitResult, MotionFitResult, PostRefineResult, PvFitResult, attach_archive_pv_model, build_grounded_map_assets, build_stage_anchors, build_model_from_map_assets, build_model_from_profile_cfg, compile_tex, dcir_observations, ensure_dir, fit_battery_parameters, fit_map_shapes, fit_motion_parameters, fit_pv_parameters, fit_regen_utilization, fit_stop_tilt_fraction, infer_soc_from_loaded_state, joint_refine_parameters, joint_replay, load_profile_yaml, metrics_from_replay, motion_power_prediction, post_refine_replay_scalars, replay_segment_start_mask, resample_for_fit, soc_fit_upper_bound, write_current_maps_and_coefficients, write_scaled_maps`
  - build_bwsc2025_fitted_package から BATTERY_PACK_MAX_CHARGE_V, BATTERY_NOMINAL_VOLTAGE_V, INVALID_PACK_VOLTAGE_MIN_V, ROOT, TIMEZONE_LOCAL, BatteryFitResult, MotionFitResult, PostRefineResult, PvFitResult, attach_archive_pv_model, build_grounded_map_assets, build_stage_anchors, build_model_from_map_assets, build_model_from_profile_cfg, compile_tex, dcir_observations, ensure_dir, fit_battery_parameters, fit_map_shapes, fit_motion_parameters, fit_pv_parameters, fit_regen_utilization, fit_stop_tilt_fraction, infer_soc_from_loaded_state, joint_refine_parameters, joint_replay, load_profile_yaml, metrics_from_replay, motion_power_prediction, post_refine_replay_scalars, replay_segment_start_mask, resample_for_fit, soc_fit_upper_bound, write_current_maps_and_coefficients, write_scaled_maps を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L21, L22, L157, L381, L444, L531, L567, L842, ...。
- L64: `from audit_identification_residuals import run_audit as run_residual_audit`
  - audit_identification_residuals から run_audit as run_residual_audit を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L3671。

## 関数・クラスを上から順に解説

### L123 関数 `neutralize_identification_scalars`

- 定義: `neutralize_identification_scalars(model)`
- docstring: Fit each calibration factor once on top of the declared physical maps.
- 戻り値の要点: `model`
- 上から順の処理:
  1. model.p.panel_gain に 1.0 の結果を代入する。
  2. model.p.drive_eff_scale に 1.0 の結果を代入する。
  3. model.p.regen_eff_scale に 1.0 の結果を代入する。
  4. model.p.regen_utilization に 1.0 の結果を代入する。
  5. model.p.rint_scale に 1.0 の結果を代入する。
  6. model.p.r_polarization_ohm に 0.0 の結果を代入する。
  7. model.aux_power_override_w に None の結果を代入する。
  8. model を返す。

### L135 関数 `resolve_relative`

- 定義: `resolve_relative(base_dir, raw)`
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `is_absolute`, `resolve`, `str`, `strip`
- 戻り値の要点: `(base_dir / path).resolve() / base_dir / path`
- 上から順の処理:
  1. path に Path(str(raw or '').strip()) の結果を代入する。
  2. 条件 not path を判定し、真なら内部処理を行う。
  3. 条件 path.is_absolute() を判定し、真なら内部処理を行う。
  4. (base_dir / path).resolve() を返す。

### L144 関数 `stage`

- 定義: `stage(message)`
- このブロックが直接呼ぶ主な関数/メソッド: `print`
- 上から順の処理:
  1. print(...) を実行する。

### L148 関数 `load_manifest`

- 定義: `load_manifest(package_dir, manifest_arg)`
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `cwd`, `is_absolute`, `is_file`, `next`, `open`, `resolve`, `safe_load`, `str`, `strip`
- 戻り値の要点: `(manifest_path, payload)`
- 上から順の処理:
  1. default_path に package_dir / 'data' / 'identification' / 'identification_manifest.yaml' の結果を代入する。
  2. 条件 manifest_arg を判定し、真なら内部処理を行う。
  3. with 文で manifest_path.open('r', encoding='utf-8') を管理しながら処理する。
  4. (manifest_path, payload) を返す。

### L168 関数 `relpath_from`

- 定義: `relpath_from(base_dir, target)`
- このブロックが直接呼ぶ主な関数/メソッド: `fspath`, `relpath`, `replace`
- 戻り値の要点: `'' / os.path.relpath(target, base_dir).replace('\\', '/') / os.fspath(target)`
- 上から順の処理:
  1. 条件 target is None を判定し、真なら内部処理を行う。
  2. 例外処理を伴う try ブロックを実行する。

### L177 関数 `tex_path_fragment`

- 定義: `tex_path_fragment(value)`
- docstring: Render ASCII and Unicode paths without losing CJK glyphs or TeX syntax.
- このブロックが直接呼ぶ主な関数/メソッド: `get`, `isascii`, `join`, `replace`, `str`
- 戻り値の要点: `f'\\texttt{{{escaped}}}' / f'\\path{{{text}}}'`
- 上から順の処理:
  1. text に str(value) の結果を代入する。
  2. 条件 text.isascii() を判定し、真なら内部処理を行う。
  3. replacements に {'\\': '\\textbackslash{}', '{': '\\{', '}': '\\}', '$': '\\$', '&': '\\&', '#': '\\#', '%': '\\%', '_': '\\_', '^': '\\textasciicircum{}', '~': '\\textasciitilde{}'} の結果を代入する。
  4. escaped に ''.join((replacements.get(char, char) for char in text)) の結果を代入する。
  5. escaped に escaped.replace('/', '/\\allowbreak{}') の結果を代入する。
  6. f'\\texttt{{{escaped}}}' を返す。

### L199 関数 `tex_text_fragment`

- 定義: `tex_text_fragment(value)`
- docstring: Escape arbitrary report prose without path-style whitespace handling.
- このブロックが直接呼ぶ主な関数/メソッド: `get`, `join`, `str`
- 戻り値の要点: `''.join((replacements.get(char, char) for char in str(value)))`
- 上から順の処理:
  1. replacements に {'\\': '\\textbackslash{}', '{': '\\{', '}': '\\}', '$': '\\$', '&': '\\&', '#': '\\#', '%': '\\%', '_': '\\_', '^': '\\textasciicircum{}', '~': '\\textasciitilde{}'} の結果を代入する。
  2. ''.join((replacements.get(char, char) for char in str(value))) を返す。

### L216 関数 `load_yaml_if_exists`

- 定義: `load_yaml_if_exists(path)`
- このブロックが直接呼ぶ主な関数/メソッド: `exists`, `open`, `safe_load`
- 戻り値の要点: `{} / yaml.safe_load(f) or {}`
- 上から順の処理:
  1. 条件 path is None or not path.exists() を判定し、真なら内部処理を行う。
  2. with 文で path.open('r', encoding='utf-8') を管理しながら処理する。

### L223 関数 `declared_control_stop_km`

- 定義: `declared_control_stop_km(profile_cfg, profile_path)`
- docstring: Load control-stop distances declared by the vehicle package.
- このブロックが直接呼ぶ主な関数/メソッド: `append`, `bool`, `float`, `get`, `isinstance`, `load_yaml_if_exists`, `resolve_relative`, `set`, `sorted`, `str`, `strip`
- 戻り値の要点: `[] / sorted(set(distances))`
- 上から順の処理:
  1. paths に profile_cfg.get('paths', {}) if isinstance(profile_cfg, dict) else {} の結果を代入する。
  2. ('actual_stop_yaml', 'stop_yaml') を順に走査し、各要素を key に入れて処理する。
  3. [] を返す。

### L245 関数 `_terminal_anchor_from_payload`

- 定義: `_terminal_anchor_from_payload(payload)`
- このブロックが直接呼ぶ主な関数/メソッド: `bool`, `float`, `get`, `isinstance`, `str`, `strip`
- 戻り値の要点: `out / {} / {}`
- 上から順の処理:
  1. 条件 not isinstance(payload, dict) を判定し、真なら内部処理を行う。
  2. anchor に payload.get('terminal_anchor', payload) の結果を代入する。
  3. 条件 not isinstance(anchor, dict) を判定し、真なら内部処理を行う。
  4. out に {} を代入する。
  5. ('count', 's_km', 'voltage_v', 'current_a', 'temp_c', 'soc_target', 'soc_sigma', 'soc_evidence_min', 'soc_evidence_max', 'voltage_sigma_v', 'ocv_terminal_v', 'series_resistance_ohm', 'ocv_statistical_sigma_v', 'ocv_systematic_sigma_v', 'ocv_total_sigma_v') を順に走査し、各要素を key に入れて処理する。
  6. raw_time に str(anchor.get('time_utc', '') or '').strip() の結果を代入する。
  7. 条件 raw_time を判定し、真なら内部処理を行う。
  8. ('notes', 'source_documents', 'method', 'soc_target_basis') を順に走査し、各要素を key に入れて処理する。
  9. ('quality_gate_pass', 'conditional_on_grounded_ocv_map', 'weak_channel_cross_consistency_gate_pass') を順に走査し、各要素を key に入れて処理する。
  10. out を返す。

### L292 関数 `_append_reason_column`

- 定義: `_append_reason_column(frame, mask, reason)`
- このブロックが直接呼ぶ主な関数/メソッド: `any`, `astype`, `fillna`, `len`, `where`
- 上から順の処理:
  1. 条件 not mask.any() を判定し、真なら内部処理を行う。
  2. current に frame.loc[mask, 'exclude_reason'].fillna('').astype(str) の結果を代入する。
  3. merged に np.where(current.str.len() > 0, current + ';' + reason, reason) の結果を代入する。
  4. frame.loc[mask, 'exclude_reason'] に merged の結果を代入する。

### L300 関数 `resolve_manifest_context`

- 定義: `resolve_manifest_context(package_dir, manifest)`
- このブロックが直接呼ぶ主な関数/メソッド: `FileNotFoundError`, `Path`, `ValueError`, `_terminal_anchor_from_payload`, `append`, `difference`, `exists`, `get`, `is_absolute`, `isinstance`, `items`, `join`
- 戻り値の要点: `{'inputs': inputs, 'options': options, 'grounded_sources': grounded, 'evidence': evidence, 'actual_event_path': actual_event_path, 'counterfactual_event_path': counterfactual_event_path, 'terminal_anchor_path': terminal_anchor_path, 'grounded_summary_path': grounded_summary_path, 'source_inventory_path': source_inventory_path, 'notes_markdown_path': notes_markdown_path, 'explicit_grounded_assets': explicit_grounded_assets, 'grounded_summary_payload': grounded_summary_payload, 'actual_event_payload': actual_event_payload, 'terminal_anchor_override': terminal_anchor_override, 'external_documents': external_documents, 'declared_evidence': declared_evidence} / resolve_relative(package_dir, raw) / None`
- 上から順の処理:
  1. inputs に manifest.get('inputs', {}) if isinstance(manifest, dict) else {} の結果を代入する。
  2. options に manifest.get('options', {}) if isinstance(manifest, dict) else {} の結果を代入する。
  3. grounded に manifest.get('grounded_sources', {}) if isinstance(manifest, dict) else {} の結果を代入する。
  4. evidence に manifest.get('evidence', {}) if isinstance(manifest, dict) else {} の結果を代入する。
  5. 関数 opt_path を定義する。
  6. actual_event_path に opt_path(inputs.get('actual_event_yaml')) の結果を代入する。
  7. counterfactual_event_path に opt_path(inputs.get('counterfactual_event_yaml')) の結果を代入する。
  8. terminal_anchor_path に opt_path(inputs.get('terminal_anchor_yaml')) の結果を代入する。
  9. grounded_summary_path に opt_path(grounded.get('grounded_map_summary_yaml', '') or options.get('grounded_map_summary_yaml', '')) の結果を代入する。
  10. source_inventory_path に opt_path(evidence.get('source_inventory_json')) の結果を代入する。

### L413 関数 `hampel_mask`

- 定義: `hampel_mask(series, window, n_sigma, min_abs)`
- このブロックが直接呼ぶ主な関数/メソッド: `abs`, `astype`, `clip`, `float`, `int`, `max`, `maximum`, `median`, `rolling`, `to_numeric`
- 戻り値の要点: `abs_dev > np.maximum(float(min_abs), float(n_sigma) * scale)`
- 上から順の処理:
  1. x に pd.to_numeric(series, errors='coerce').astype(float) の結果を代入する。
  2. window に max(3, int(window)) の結果を代入する。
  3. 条件 window % 2 == 0 を判定し、真なら内部処理を行う。
  4. med に x.rolling(window, center=True, min_periods=1).median() の結果を代入する。
  5. abs_dev に (x - med).abs() の結果を代入する。
  6. mad に abs_dev.rolling(window, center=True, min_periods=1).median() の結果を代入する。
  7. scale に (1.4826 * mad).clip(lower=max(1e-06, float(min_abs) * 0.25)) の結果を代入する。
  8. abs_dev > np.maximum(float(min_abs), float(n_sigma) * scale) を返す。

### L425 関数 `apply_sensor_quality_annotations`

- 定義: `apply_sensor_quality_annotations(work, base_model, options)`
- このブロックが直接呼ぶ主な関数/メソッド: `_append_reason_column`, `abs`, `any`, `astype`, `copy`, `diff`, `fillna`, `float`, `get`, `getattr`, `hampel_mask`, `int`
- 戻り値の要点: `out / work`
- 上から順の処理:
  1. options に options if isinstance(options, dict) else {} の結果を代入する。
  2. sensor_cfg に options.get('sensor_filter', {}) if isinstance(options.get('sensor_filter', {}), dict) else {} の結果を代入する。
  3. 条件 sensor_cfg.get('enabled', True) is False を判定し、真なら内部処理を行う。
  4. out に work.copy() の結果を代入する。
  5. ('exclude_power_fit', 'exclude_voltage_fit', 'exclude_weather_fit') を順に走査し、各要素を key に入れて処理する。
  6. 条件 'exclude_reason' not in out.columns を判定し、真なら内部処理を行う。
  7. invalid_v_threshold に float(sensor_cfg.get('invalid_voltage_threshold_v', INVALID_PACK_VOLTAGE_MIN_V)) の結果を代入する。
  8. current_limit_margin_a に float(sensor_cfg.get('charge_current_limit_margin_a', 2.0)) の結果を代入する。
  9. current_spike_window に int(sensor_cfg.get('current_spike_window', 9)) の結果を代入する。
  10. current_spike_sigma に float(sensor_cfg.get('current_spike_sigma', 4.0)) の結果を代入する。

### L520 関数 `polarization_current_trace`

- 定義: `polarization_current_trace(replay, current_column, tau_sec)`
- docstring: Return the 1-RC branch current state immediately before each sample.
- このブロックが直接呼ぶ主な関数/メソッド: `diff`, `exp`, `float`, `isfinite`, `len`, `max`, `min`, `range`, `replay_segment_start_mask`, `to_datetime`, `to_numeric`, `to_numpy`
- 戻り値の要点: `state`
- 上から順の処理:
  1. current に pd.to_numeric(replay[current_column], errors='coerce').to_numpy(dtype=float) の結果を代入する。
  2. current に np.where(np.isfinite(current), current, 0.0) の結果を代入する。
  3. time_utc に pd.to_datetime(replay['time_utc'], utc=True, errors='coerce') の結果を代入する。
  4. dt_sec に time_utc.diff().dt.total_seconds().to_numpy(dtype=float) の結果を代入する。
  5. segment_starts に replay_segment_start_mask(replay) の結果を代入する。
  6. state に np.zeros(len(replay), dtype=float) の結果を代入する。
  7. tau に max(float(tau_sec), 1e-06) の結果を代入する。
  8. range(1, len(replay)) を順に走査し、各要素を idx に入れて処理する。
  9. state を返す。

### L544 関数 `fit_battery_polarization`

- 定義: `fit_battery_polarization(replay)`
- docstring: Fit a bounded one-RC branch and gate it on the last independent day.
- このブロックが直接呼ぶ主な関数/メソッド: `Series`, `astype`, `bool`, `clip`, `dot`, `fillna`, `float`, `geomspace`, `get`, `int`, `isfinite`, `len`
- 戻り値の要点: `{'adopted': adopted, 'reason': 'bounded_1rc_improves_training_and_last_day_holdout_rmse' if adopted else 'training_or_last_day_holdout_gate_failed', 'sample_count': int(base_valid.sum()), 'training_sample_count': int(training_valid.sum()), 'validation_sample_count': int(validation_valid.sum()), 'holdout_group': holdout_group, 'r_polarization_ohm': float(best['r_polarization_ohm'] if adopted else 0.0), 'tau_sec': float(best['tau_sec']), 'rmse_before_v': rmse_before, 'rmse_after_v': float(best['rmse_after_v'] if adopted else rmse_before), 'rmse_improvement_v': float(improvement if adopted else 0.0), 'validation_rmse_before_v': validation_before, 'validation_rmse_after_v': validation_after, 'validation_rmse_ratio': validation_ratio, 'validation_rmse_ratio_max': 1.0, 'method': 'bounded deterministic tau grid with closed-form least-squares Rp on earlier race days; last race day is an untouched adoption holdout'} / {'adopted': False, 'reason': 'insufficient_valid_voltage_samples', 'sample_count': int(base_valid.sum()), 'r_polarization_ohm': 0.0, 'tau_sec': 60.0, 'rmse_before_v': float('nan'), 'rmse_after_v': float('nan')} / {'adopted': False, 'reason': 'no_independent_day_holdout', 'sample_count': int(base_valid.sum()), 'training_sample_count': 0, 'validation_sample_count': 0, 'r_polarization_ohm': 0.0, 'tau_sec': 60.0, 'rmse_before_v': float(np.sqrt(np.mean(residual[base_valid] ** 2))), 'rmse_after_v': float(np.sqrt(np.mean(residual[base_valid] ** 2)))} / {'adopted': False, 'reason': 'insufficient_independent_day_holdout_samples', 'sample_count': int(base_valid.sum()), 'training_sample_count': int(training_valid.sum()), 'validation_sample_count': int(validation_valid.sum()), 'holdout_group': holdout_group, 'r_polarization_ohm': 0.0, 'tau_sec': 60.0, 'rmse_before_v': float(np.sqrt(np.mean(residual[base_valid] ** 2))), 'rmse_after_v': float(np.sqrt(np.mean(residual[base_valid] ** 2)))}`
- 上から順の処理:
  1. residual に (pd.to_numeric(replay['battery_voltage_v_obs'], errors='coerce') - pd.to_numeric(replay['battery_voltage_v_pred'], errors='coerce')).to_numpy(dtype=float) の結果を代入する。
  2. excluded に replay.get('exclude_voltage_fit', pd.Series(False, index=replay.index)).fillna(True).astype(bool).to_numpy() の結果を代入する。
  3. base_valid に np.isfinite(residual) & ~excluded の結果を代入する。
  4. 条件 int(base_valid.sum()) < 500 を判定し、真なら内部処理を行う。
  5. 条件 'day' in replay.columns を判定し、真なら内部処理を行う。
  6. unique_groups に sorted((float(value) for value in np.unique(groups[base_valid & np.isfinite(groups)]))) の結果を代入する。
  7. 条件 len(unique_groups) < 2 を判定し、真なら内部処理を行う。
  8. holdout_group に unique_groups[-1] の結果を代入する。
  9. training_valid に base_valid & np.isfinite(groups) & (groups != holdout_group) の結果を代入する。
  10. validation_valid に base_valid & np.isfinite(groups) & (groups == holdout_group) の結果を代入する。

### L682 関数 `apply_battery_polarization`

- 定義: `apply_battery_polarization(replay, dynamic_fit, current_column)`
- このブロックが直接呼ぶ主な関数/メソッド: `bool`, `copy`, `float`, `get`, `polarization_current_trace`, `to_numeric`
- 戻り値の要点: `out / out`
- 上から順の処理:
  1. out に replay.copy() の結果を代入する。
  2. out['battery_voltage_v_pred_static'] に pd.to_numeric(out['battery_voltage_v_pred'], errors='coerce') の結果を代入する。
  3. 条件 not bool(dynamic_fit.get('adopted', False)) を判定し、真なら内部処理を行う。
  4. state に polarization_current_trace(out, current_column=current_column, tau_sec=float(dynamic_fit['tau_sec'])) の結果を代入する。
  5. polarization_v に float(dynamic_fit['r_polarization_ohm']) * state の結果を代入する。
  6. out['battery_polarization_v'] に polarization_v の結果を代入する。
  7. out['battery_voltage_v_pred'] に out['battery_voltage_v_pred_static'] - polarization_v の結果を代入する。
  8. out を返す。

### L706 関数 `resolve_fit_plan`

- 定義: `resolve_fit_plan(options, quality)`
- このブロックが直接呼ぶ主な関数/メソッド: `dict`, `float`, `get`, `isinstance`, `items`, `lower`, `str`, `strip`
- 戻り値の要点: `plan`
- 上から順の処理:
  1. options に options if isinstance(options, dict) else {} の結果を代入する。
  2. quality_norm に str(quality or options.get('fit_quality', 'standard')).strip().lower() の結果を代入する。
  3. 条件 quality_norm not in FIT_QUALITY_PRESETS を判定し、真なら内部処理を行う。
  4. plan に dict(FIT_QUALITY_PRESETS[quality_norm]) の結果を代入する。
  5. key_map に {'battery_restart_count': 'battery_restart_count', 'battery_maxiter': 'battery_maxiter', 'motion_restart_count': 'motion_restart_count', 'motion_maxiter': 'motion_maxiter', 'joint_restart_count': 'joint_restart_count', 'joint_random_start_count': 'joint_random_start_count', 'joint_local_topk': 'joint_local_topk', 'joint_maxiter': 'joint_maxiter', 'fit_stride': 'fit_stride', 'allow_map_shape_fit': 'allow_map_shape_fit', 'post_refine_enabled': 'post_refine_enabled'} の結果を代入する。
  6. key_map.items() を順に走査し、各要素を (out_key, opt_key) に入れて処理する。
  7. plan['panel_deployment_stopped_speed_kmh'] に float(options.get('panel_deployment_stopped_speed_kmh', 2.0)) の結果を代入する。
  8. plan['panel_deployment_min_dwell_sec'] に float(options.get('panel_deployment_min_dwell_sec', 300.0)) の結果を代入する。
  9. plan['panel_deployment_max_sample_gap_sec'] に float(options.get('panel_deployment_max_sample_gap_sec', 60.0)) の結果を代入する。
  10. plan['panel_control_stop_tolerance_km'] に float(options.get('panel_control_stop_tolerance_km', 1.0)) の結果を代入する。

### L750 関数 `resolve_identification_output_layout`

- 定義: `resolve_identification_output_layout(package_dir, profile_cfg, output_tag_override)`
- このブロックが直接呼ぶ主な関数/メソッド: `get`, `resolve_relative`, `str`, `strip`, `sub`
- 戻り値の要点: `{'tag': tag, 'output_root': output_root, 'run_root': run_root, 'report_root': report_root, 'grounded_maps': run_root / 'grounded_base_maps', 'adopted_maps': run_root / 'adopted_maps'}`
- 上から順の処理:
  1. identification_cfg に profile_cfg.get('identification', {}) or {} の結果を代入する。
  2. output_root に resolve_relative(package_dir, str(identification_cfg.get('output_dir', 'outputs/identification') or 'outputs/identification')) の結果を代入する。
  3. raw_tag に output_tag_override の結果を代入する。
  4. 条件 raw_tag is None を判定し、真なら内部処理を行う。
  5. tag に re.sub('[^A-Za-z0-9_.-]+', '_', str(raw_tag).strip()).strip('._') の結果を代入する。
  6. run_root に output_root / 'runs' / tag if tag else output_root の結果を代入する。
  7. report_root に run_root / 'reports' if tag else package_dir / 'outputs' / 'reports' の結果を代入する。
  8. {'tag': tag, 'output_root': output_root, 'run_root': run_root, 'report_root': report_root, 'grounded_maps': run_root / 'grounded_base_maps', 'adopted_maps': run_root / 'adopted_maps'} を返す。

### L777 関数 `identification_profile_output_path`

- 定義: `identification_profile_output_path(canonical_profile, run_output_dir, output_tag, adopt_profile)`
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `str`, `strip`
- 戻り値の要点: `Path(canonical_profile) / Path(run_output_dir) / 'profile_candidate.yaml'`
- 上から順の処理:
  1. 条件 str(output_tag).strip() and (not adopt_profile) を判定し、真なら内部処理を行う。
  2. Path(canonical_profile) を返す。

### L789 関数 `load_ocv_df`

- 定義: `load_ocv_df(profile_cfg, profile_yaml)`
- このブロックが直接呼ぶ主な関数/メソッド: `FileNotFoundError`, `get`, `read_csv`, `resolve_relative`, `str`, `strip`
- 戻り値の要点: `pd.read_csv(ocv_path)`
- 上から順の処理:
  1. raw に str((profile_cfg.get('paths', {}) or {}).get('ocv_soc_map', '') or '').strip() の結果を代入する。
  2. 条件 not raw を判定し、真なら内部処理を行う。
  3. ocv_path に resolve_relative(profile_yaml.parent, raw) の結果を代入する。
  4. pd.read_csv(ocv_path) を返す。

### L797 関数 `build_source_map_assets`

- 定義: `build_source_map_assets(profile_cfg, profile_yaml)`
- このブロックが直接呼ぶ主な関数/メソッド: `FileNotFoundError`, `get`, `rel`, `resolve_relative`, `str`, `strip`
- 戻り値の要点: `{'drive_eff_map': rel('drive_eff_map'), 'drive_map_eco': rel('drive_map_eco', paths.get('drive_eff_map', '')), 'drive_map_power': rel('drive_map_power', paths.get('drive_eff_map', '')), 'regen_eff_map': rel('regen_eff_map'), 'regen_map_eco': rel('regen_map_eco', paths.get('regen_eff_map', '')), 'regen_map_power': rel('regen_map_power', paths.get('regen_eff_map', '')), 'rint_map': rel('rint_map'), 'panel_eff_map': rel('panel_eff_map'), 'mppt_eff_map': rel('mppt_eff_map'), 'ocv_soc_map': rel('ocv_soc_map')} / resolve_relative(base_dir, raw)`
- 上から順の処理:
  1. base_dir に profile_yaml.parent の結果を代入する。
  2. paths に profile_cfg.get('paths', {}) or {} の結果を代入する。
  3. 関数 rel を定義する。
  4. {'drive_eff_map': rel('drive_eff_map'), 'drive_map_eco': rel('drive_map_eco', paths.get('drive_eff_map', '')), 'drive_map_power': rel('drive_map_power', paths.get('drive_eff_map', '')), 'regen_eff_map': rel('regen_eff_map'), 'regen_map_eco': rel('regen_map_eco', paths.get('regen_eff_map', '')), 'regen_map_power': rel('regen_map_power', paths.get('regen_eff_map', '')), 'rint_map': rel('rint_map'), 'panel_eff_map': rel('panel_eff_map'), 'mppt_eff_map': rel('mppt_eff_map'), 'ocv_soc_map': rel('ocv_soc_map')} を返す。

### L821 関数 `apply_actual_event_annotations`

- 定義: `apply_actual_event_annotations(work, payload)`
- このブロックが直接呼ぶ主な関数/メソッド: `Timestamp`, `_append_reason_column`, `any`, `astype`, `bool`, `copy`, `fillna`, `get`, `hasattr`, `isinstance`, `str`, `strip`
- 戻り値の要点: `out / work / work`
- 上から順の処理:
  1. 条件 not isinstance(payload, dict) を判定し、真なら内部処理を行う。
  2. events に payload.get('events', payload) の結果を代入する。
  3. 条件 not isinstance(events, list) or not events を判定し、真なら内部処理を行う。
  4. out に work.copy() の結果を代入する。
  5. ('exclude_power_fit', 'exclude_voltage_fit', 'exclude_weather_fit') を順に走査し、各要素を key に入れて処理する。
  6. 条件 'exclude_reason' not in out.columns を判定し、真なら内部処理を行う。
  7. time_utc に pd.to_datetime(out['time_utc'], format='mixed', utc=True, errors='coerce') の結果を代入する。
  8. events を順に走査し、各要素を event に入れて処理する。
  9. out を返す。

### L863 関数 `truncate_at_retire_event`

- 定義: `truncate_at_retire_event(work, payload)`
- docstring: End historical replay at the first authoritative retirement timestamp.
- このブロックが直接呼ぶ主な関数/メソッド: `Timestamp`, `ValueError`, `append`, `copy`, `get`, `isinstance`, `isoformat`, `lower`, `min`, `reset_index`, `str`, `strip`
- 戻り値の要点: `retained.reset_index(drop=True) / work / work / work`
- 上から順の処理:
  1. 条件 not isinstance(payload, dict) を判定し、真なら内部処理を行う。
  2. events に payload.get('events', payload) の結果を代入する。
  3. 条件 not isinstance(events, list) を判定し、真なら内部処理を行う。
  4. cutoffs に [] を代入する。
  5. events を順に走査し、各要素を event に入れて処理する。
  6. 条件 not cutoffs を判定し、真なら内部処理を行う。
  7. cutoff に min(cutoffs) の結果を代入する。
  8. time_utc に pd.to_datetime(work['time_utc'], format='mixed', utc=True, errors='coerce') の結果を代入する。
  9. retained に work.loc[time_utc <= cutoff].copy() の結果を代入する。
  10. 条件 retained.empty を判定し、真なら内部処理を行う。

### L892 関数 `normalize_generic_log`

- 定義: `normalize_generic_log(log_csv, actual_event_payload, base_model, options)`
- このブロックが直接呼ぶ主な関数/メソッド: `ValueError`, `apply_actual_event_annotations`, `apply_sensor_quality_annotations`, `astype`, `clip`, `copy`, `diff`, `dropna`, `extend`, `fillna`, `float`, `items`
- 戻り値の要点: `work`
- 上から順の処理:
  1. df に pd.read_csv(log_csv, low_memory=False) の結果を代入する。
  2. 条件 'time_utc' not in df.columns を判定し、真なら内部処理を行う。
  3. work に df.copy() の結果を代入する。
  4. work['time_utc'] に pd.to_datetime(work['time_utc'], format='mixed', utc=True) の結果を代入する。
  5. work に work.sort_values('time_utc').reset_index(drop=True) の結果を代入する。
  6. required_defaults に {'s_km': np.nan, 'speed_kmh': 0.0, 'slope_pct': 0.0, 'route_heading_deg': 0.0, 'headwind_archive_ms': 0.0, 'GHI_archive': 0.0, 'Tamb_archive_C': 25.0, 'solar_power_w_obs': 0.0, 'battery_power_w_obs': 0.0, 'battery_current_a': 0.0, 'battery_voltage_v': np.nan, 'lat': np.nan, 'lon': np.nan, 'alt_m': 0.0} の結果を代入する。
  7. required_defaults.items() を順に走査し、各要素を (key, value) に入れて処理する。
  8. 条件 'dt_sec' not in work.columns を判定し、真なら内部処理を行う。
  9. 条件 'time_local' not in work.columns を判定し、真なら内部処理を行う。
  10. 条件 'day' not in work.columns を判定し、真なら内部処理を行う。

### L994 関数 `build_terminal_anchor`

- 定義: `build_terminal_anchor(log_df, ocv_df, base_model, anchor_km)`
- このブロックが直接呼ぶ主な関数/メソッド: `abs`, `asarray`, `astype`, `copy`, `fillna`, `float`, `infer_soc_from_loaded_state`, `int`, `isfinite`, `itertuples`, `len`, `median`
- 戻り値の要点: `{'count': int(len(window)), 's_km': float(window['s_km'].median()), 'time_utc': pd.to_datetime(window['time_utc'].iloc[-1], utc=True).strftime('%Y-%m-%dT%H:%M:%SZ'), 'voltage_v': float(window['battery_voltage_v'].median()), 'current_a': float(window['battery_current_a'].median()), 'temp_c': float(window['Tamb_archive_C'].median()), 'soc_target': float(np.nanmedian(np.asarray(soc_targets, dtype=float)))}`
- 上から順の処理:
  1. valid に np.isfinite(log_df['battery_voltage_v']) & np.isfinite(log_df['battery_current_a']) & np.isfinite(log_df['Tamb_archive_C']) & np.isfinite(log_df['s_km']) & (log_df['battery_voltage_v'] >= INVALID_PACK_VOLTAGE_MIN_V) & ~log_df['exclude_voltage_fit'].fillna(False).astype(bool) の結果を代入する。
  2. window に log_df.loc[valid & (np.abs(log_df['s_km'] - float(anchor_km)) <= 1.5)].copy() の結果を代入する。
  3. 条件 window.empty を判定し、真なら内部処理を行う。
  4. soc_targets に [infer_soc_from_loaded_state(float(row.battery_voltage_v), float(row.battery_current_a), float(row.Tamb_archive_C), ocv_df, base_model) for row in window.itertuples(index=False)] の結果を代入する。
  5. {'count': int(len(window)), 's_km': float(window['s_km'].median()), 'time_utc': pd.to_datetime(window['time_utc'].iloc[-1], utc=True).strftime('%Y-%m-%dT%H:%M:%SZ'), 'voltage_v': float(window['battery_voltage_v'].median()), 'current_a': float(window['battery_current_a'].median()), 'temp_c': float(window['Tamb_archive_C'].median()), 'soc_target': float(np.nanmedian(np.asarray(soc_targets, dtype=float)))} を返す。

### L1029 関数 `terminal_metrics`

- 定義: `terminal_metrics(replay_df, ocv_df, base_model, batt, anchor_km, terminal_anchor)`
- このブロックが直接呼ぶ主な関数/メソッド: `abs`, `asarray`, `astype`, `copy`, `fillna`, `float`, `get`, `infer_soc_from_loaded_state`, `isfinite`, `isinstance`, `itertuples`, `len`
- 戻り値の要点: `{'retire_anchor_s_km': float(window['s_km'].median()), 'retire_anchor_voltage_obs_v': float(window['battery_voltage_v_obs'].median()), 'retire_anchor_voltage_pred_v': float(window['battery_voltage_v_pred'].median()), 'retire_anchor_soc_obs': soc_obs_value, 'retire_anchor_soc_pred': float(window['soc_pred'].median()), 'retire_anchor_soc_error': float(window['soc_pred'].median() - soc_obs_value)}`
- 上から順の処理:
  1. valid に np.isfinite(replay_df['battery_voltage_v_obs']) & np.isfinite(replay_df['battery_current_a_obs']) & np.isfinite(replay_df['Tamb_C']) & np.isfinite(replay_df['s_km']) & (replay_df['battery_voltage_v_obs'] >= INVALID_PACK_VOLTAGE_MIN_V) & ~replay_df['exclude_voltage_fit'].fillna(False).astype(bool) の結果を代入する。
  2. window に replay_df.loc[valid & (np.abs(replay_df['s_km'] - float(anchor_km)) <= 1.5)].copy() の結果を代入する。
  3. 条件 window.empty を判定し、真なら内部処理を行う。
  4. terminal_anchor に terminal_anchor if isinstance(terminal_anchor, dict) else {} の結果を代入する。
  5. 条件 'soc_target' in terminal_anchor and terminal_anchor.get('soc_target') not in (None, '') を判定し、真なら内部処理を行う。
  6. {'retire_anchor_s_km': float(window['s_km'].median()), 'retire_anchor_voltage_obs_v': float(window['battery_voltage_v_obs'].median()), 'retire_anchor_voltage_pred_v': float(window['battery_voltage_v_pred'].median()), 'retire_anchor_soc_obs': soc_obs_value, 'retire_anchor_soc_pred': float(window['soc_pred'].median()), 'retire_anchor_soc_error': float(window['soc_pred'].median() - soc_obs_value)} を返す。

### L1078 関数 `replay_day_metrics`

- 定義: `replay_day_metrics(replay_df)`
- このブロックが直接呼ぶ主な関数/メソッド: `append`, `astype`, `fillna`, `float`, `groupby`, `int`, `len`, `max`, `mean`, `notna`, `sqrt`, `sum`
- 戻り値の要点: `rows`
- 上から順の処理:
  1. rows に [] を代入する。
  2. replay_df.groupby('day', dropna=False) を順に走査し、各要素を (day, group) に入れて処理する。
  3. rows を返す。

### L1099 関数 `identification_selection_score`

- 定義: `identification_selection_score(metrics)`
- このブロックが直接呼ぶ主な関数/メソッド: `abs`, `float`, `get`
- 戻り値の要点: `power_term + energy_term + independent_pv_term + vehicle_voltage_term + battery_voltage_term + battery_terminal_term + vehicle_terminal_term + end_to_end_terminal_term + fit_window_term`
- 上から順の処理:
  1. power_rmse に float(metrics.get('power_rmse_clean_w', float('inf'))) の結果を代入する。
  2. robust_power_rmse に float(metrics.get('power_residual_mean_120s_rmse_w', power_rmse)) の結果を代入する。
  3. energy_rmse_25km に float(metrics.get('energy_error_25km_rmse_wh', float('inf'))) の結果を代入する。
  4. power_term に 0.6 * power_rmse + 0.4 * robust_power_rmse の結果を代入する。
  5. energy_term に 0.5 * energy_rmse_25km の結果を代入する。
  6. independent_pv_term に 0.25 * float(metrics.get('end_to_end_moving_pv_rmse_w', float('inf'))) の結果を代入する。
  7. vehicle_voltage_term に 8.0 * float(metrics.get('voltage_rmse_clean_v', float('inf'))) の結果を代入する。
  8. battery_voltage_term に 4.0 * float(metrics.get('battery_conditional_voltage_rmse_clean_v', float('inf'))) の結果を代入する。
  9. battery_terminal_term に 80.0 * abs(float(metrics.get('battery_conditional_retire_anchor_soc_error', float('inf')))) の結果を代入する。
  10. vehicle_terminal_term に 1000.0 * abs(float(metrics.get('retire_anchor_soc_error', float('inf')))) の結果を代入する。

### L1135 関数 `condition_vehicle_fit_on_measured_pv`

- 定義: `condition_vehicle_fit_on_measured_pv(frame)`
- docstring: Use measured array power when identifying vehicle-side coefficients.

Forecast/PV-map error is validated separately.  Feeding predicted PV into the
vehicle fit otherwise lets a cloudy-day irradiance error masquerade as CdA,
rolling resistance, or drivetrain-efficiency error.
- このブロックが直接呼ぶ主な関数/メソッド: `clip`, `copy`, `get`, `notna`, `to_numeric`, `where`
- 戻り値の要点: `out / out`
- 上から順の処理:
  1. out に frame.copy() の結果を代入する。
  2. predicted に pd.to_numeric(out.get('solar_power_w_model'), errors='coerce') の結果を代入する。
  3. measured に pd.to_numeric(out.get('solar_power_w_obs'), errors='coerce') の結果を代入する。
  4. 条件 predicted is None or measured is None を判定し、真なら内部処理を行う。
  5. measured に measured.clip(lower=0.0) の結果を代入する。
  6. usable に measured.notna() の結果を代入する。
  7. out['solar_power_w_forecast_model'] に predicted の結果を代入する。
  8. out['solar_power_w_model'] に predicted.where(~usable, measured) の結果を代入する。
  9. out['vehicle_fit_solar_source'] に np.where(usable, 'measured', 'forecast_fallback') の結果を代入する。
  10. out を返す。

### L1155 関数 `calibrate_solar_measurement_to_pack`

- 定義: `calibrate_solar_measurement_to_pack(frame, known_aux_power_w, stopped_speed_kmh, minimum_solar_power_w, minimum_samples, gain_bounds)`
- docstring: Calibrate the ZP solar channel from stationary DC-bus power balance.

At zero wheel speed, the independently measured channels satisfy
``P_batt = P_aux - gain * P_solar_raw``.  The known 21 W auxiliary load
anchors the intercept, so the fitted gain cannot absorb vehicle drag or
forecast irradiance error.
- このブロックが直接呼ぶ主な関数/メソッド: `Series`, `abs`, `array`, `asarray`, `astype`, `bool`, `copy`, `fillna`, `float`, `get`, `groupby`, `int`
- 戻り値の要点: `(out, result)`
- 上から順の処理:
  1. out に frame.copy() の結果を代入する。
  2. raw_column に 'solar_power_w_obs_raw' if 'solar_power_w_obs_raw' in out.columns else 'solar_power_w_obs' の結果を代入する。
  3. raw に pd.to_numeric(out.get(raw_column), errors='coerce') の結果を代入する。
  4. battery に pd.to_numeric(out.get('battery_power_w_obs'), errors='coerce') の結果を代入する。
  5. speed に pd.to_numeric(out.get('speed_kmh'), errors='coerce') の結果を代入する。
  6. excluded に pd.Series(False, index=out.index) の結果を代入する。
  7. 条件 'exclude_power_fit' in out.columns を判定し、真なら内部処理を行う。
  8. mask に ~excluded & raw.notna() & battery.notna() & speed.notna() & (speed <= float(stopped_speed_kmh)) & (raw >= float(minimum_solar_power_w)) の結果を代入する。
  9. x に raw.loc[mask].to_numpy(dtype=float) の結果を代入する。
  10. y に battery.loc[mask].to_numpy(dtype=float) の結果を代入する。

### L1271 関数 `_shift_acceleration_within_segments`

- 定義: `_shift_acceleration_within_segments(frame, sample_shift, acceleration)`
- docstring: Shift a derived acceleration trace without leaking across race days or log gaps.
- このブロックが直接呼ぶ主な関数/メソッド: `Series`, `cumsum`, `groupby`, `int`, `replay_segment_start_mask`, `shift`, `to_numeric`
- 戻り値の要点: `acceleration.groupby(segment_id).shift(int(sample_shift))`
- 上から順の処理:
  1. 条件 acceleration is None を判定し、真なら内部処理を行う。
  2. segment_id に pd.Series(replay_segment_start_mask(frame), index=frame.index).cumsum() の結果を代入する。
  3. acceleration.groupby(segment_id).shift(int(sample_shift)) を返す。

### L1283 関数 `_acceleration_trace_from_speed`

- 定義: `_acceleration_trace_from_speed(frame, method, window_samples)`
- このブロックが直接呼ぶ主な関数/メソッド: `Series`, `ValueError`, `clip`, `cumsum`, `diff`, `fillna`, `get`, `groupby`, `int`, `len`, `lower`, `max`
- 戻り値の要点: `smoothed.fillna(0.0).clip(lower=-1.5, upper=1.5)`
- 上から順の処理:
  1. speed_ms に pd.to_numeric(frame['speed_kmh'], errors='coerce').fillna(0.0) / 3.6 の結果を代入する。
  2. dt_sec に pd.to_numeric(frame.get('dt_sec'), errors='coerce').replace(0.0, np.nan) の結果を代入する。
  3. raw に speed_ms.diff() / dt_sec の結果を代入する。
  4. segment_start に pd.Series(replay_segment_start_mask(frame), index=frame.index) の結果を代入する。
  5. raw.loc[segment_start] に 0.0 の結果を代入する。
  6. raw に raw.replace([np.inf, -np.inf], np.nan).fillna(0.0) の結果を代入する。
  7. segment_id に segment_start.cumsum() の結果を代入する。
  8. window に max(1, int(window_samples)) の結果を代入する。
  9. 条件 window % 2 == 0 を判定し、真なら内部処理を行う。
  10. smoothed に pd.Series(index=frame.index, dtype=float) の結果を代入する。

### L1321 関数 `_bilinear_interp_array`

- 定義: `_bilinear_interp_array(x_grid, y_grid, values, x, y)`
- このブロックが直接呼ぶ主な関数/メソッド: `asarray`, `clip`, `divide`, `len`, `searchsorted`, `zeros_like`
- 戻り値の要点: `(1.0 - wx) * (1.0 - wy) * values[ix, iy] + wx * (1.0 - wy) * values[ix + 1, iy] + (1.0 - wx) * wy * values[ix, iy + 1] + wx * wy * values[ix + 1, iy + 1]`
- 上から順の処理:
  1. x_grid に np.asarray(x_grid, dtype=float) の結果を代入する。
  2. y_grid に np.asarray(y_grid, dtype=float) の結果を代入する。
  3. values に np.asarray(values, dtype=float) の結果を代入する。
  4. x に np.clip(np.asarray(x, dtype=float), x_grid[0], x_grid[-1]) の結果を代入する。
  5. y に np.clip(np.asarray(y, dtype=float), y_grid[0], y_grid[-1]) の結果を代入する。
  6. ix に np.clip(np.searchsorted(x_grid, x) - 1, 0, len(x_grid) - 2) の結果を代入する。
  7. iy に np.clip(np.searchsorted(y_grid, y) - 1, 0, len(y_grid) - 2) の結果を代入する。
  8. (x0, x1) に (x_grid[ix], x_grid[ix + 1]) の結果を代入する。
  9. (y0, y1) に (y_grid[iy], y_grid[iy + 1]) の結果を代入する。
  10. wx に np.divide(x - x0, x1 - x0, out=np.zeros_like(x), where=x1 != x0) の結果を代入する。

### L1341 関数 `_map_efficiency_array`

- 定義: `_map_efficiency_array(base_model, maps, speed_ms, torque_nm, regen)`
- このブロックが直接呼ぶ主な関数/メソッド: `_bilinear_interp_array`, `clip`, `empty`, `float`, `full`, `get`, `len`, `lower`, `str`
- 戻り値の要点: `np.clip(result, 0.4 if regen else 0.55, 0.95 if regen else 0.99)`
- 上から順の処理:
  1. mode に str(base_model.drive_mode or 'default').lower() の結果を代入する。
  2. 条件 mode in {'eco', 'power'} を判定し、真なら内部処理を行う。
  3. result に np.empty(len(speed_ms), dtype=float) の結果を代入する。
  4. (False, True) を順に走査し、各要素を use_power に入れて処理する。
  5. np.clip(result, 0.4 if regen else 0.55, 0.95 if regen else 0.99) を返す。

### L1364 関数 `_motion_predictions_for_acceleration`

- 定義: `_motion_predictions_for_acceleration(frame, acceleration, base_model, mot)`
- docstring: Vectorized equivalent of motion_power_prediction for filter/lag search.
- このブロックが直接呼ぶ主な関数/メソッド: `Series`, `_map_efficiency_array`, `abs`, `arctan`, `clip`, `cos`, `empty`, `fillna`, `float`, `full`, `len`, `lower`
- 戻り値の要点: `electrical + float(mot.p_aux_w) - solar`
- 上から順の処理:
  1. speed_ms に pd.to_numeric(frame['speed_kmh'], errors='coerce').fillna(0.0).to_numpy() / 3.6 の結果を代入する。
  2. slope に pd.to_numeric(frame['slope_pct'], errors='coerce').fillna(0.0).to_numpy() の結果を代入する。
  3. headwind に pd.to_numeric(frame['headwind_archive_ms'], errors='coerce').fillna(0.0).to_numpy() * float(mot.headwind_gain) の結果を代入する。
  4. solar に pd.to_numeric(frame['solar_power_w_obs'], errors='coerce').fillna(0.0).to_numpy() の結果を代入する。
  5. theta に np.arctan(slope * float(mot.grade_scale) / 100.0) の結果を代入する。
  6. relative_speed に np.maximum(0.0, speed_ms + headwind) の結果を代入する。
  7. ambient_source に frame['Tamb_archive_C'] if 'Tamb_archive_C' in frame else pd.Series(25.0, index=frame.index) の結果を代入する。
  8. elevation_source に frame['alt_m'] if 'alt_m' in frame else pd.Series(0.0, index=frame.index) の結果を代入する。
  9. ambient に pd.to_numeric(ambient_source, errors='coerce').fillna(25.0).to_numpy() の結果を代入する。
  10. elevation に pd.to_numeric(elevation_source, errors='coerce').fillna(0.0).to_numpy() の結果を代入する。

### L1431 関数 `fit_acceleration_timestamp_alignment`

- 定義: `fit_acceleration_timestamp_alignment(frame, base_model, mot, options)`
- docstring: Identify the filter and timestamp offset of GPS-derived acceleration.

Vehicle mass remains fixed. Candidate observation filters and offsets are
fitted on all but the last race day and adopted only when the held-out last
day does not regress. This models quantized/asynchronous GNSS observations;
it is not a tunable vehicle force or a live-command filter.
- このブロックが直接呼ぶ主な関数/メソッド: `_acceleration_trace_from_speed`, `_motion_predictions_for_acceleration`, `_shift_acceleration_within_segments`, `abs`, `any`, `append`, `astype`, `bool`, `clip`, `copy`, `fillna`, `float`
- 戻り値の要点: `(out, {'enabled': True, 'adopted': adopted, 'method': 'fixed-mass GNSS acceleration filter/lag selection with last-race-day holdout', 'sample_period_sec': sample_period_sec, 'selected_filter_method': selected_method, 'selected_filter_window_samples': selected_window, 'selected_filter_window_sec': selected_window * sample_period_sec, 'selected_lag_sec': selected_lag, 'lag_search_min_sec': lag_search_min, 'lag_search_max_sec': lag_search_max, 'lag_search_boundary_hit': lag_boundary_hit, 'holdout_day': holdout_day, 'training_sample_count': int(train_mask.sum()), 'validation_sample_count': int(validation_mask.sum()), 'baseline_training_rmse_w': float(baseline['training_rmse_w']), 'selected_training_rmse_w': float(selected['training_rmse_w']), 'baseline_validation_rmse_w': float(baseline['validation_rmse_w']), 'selected_validation_rmse_w': float(selected['validation_rmse_w']), 'training_improvement_w': float(float(baseline['training_rmse_w']) - float(selected['training_rmse_w'])), 'validation_rmse_ratio': validation_ratio if adopted else 1.0, 'candidates': records}) / (frame.copy(), {'enabled': enabled, 'adopted': False, 'reason': 'disabled_or_missing_columns'}) / (out, {'enabled': True, 'adopted': False, 'reason': 'insufficient_training_samples', 'training_sample_count': int(train_mask.sum()), 'validation_sample_count': int(validation_mask.sum())}) / float(np.sqrt(np.mean(np.square(observed[use] - predicted[use])))) if use.any() else float('nan')`
- 上から順の処理:
  1. cfg に options if isinstance(options, dict) else {} の結果を代入する。
  2. enabled に bool(cfg.get('enabled', True)) の結果を代入する。
  3. required に {'time_utc', 'day', 'speed_kmh', 'slope_pct', 'headwind_archive_ms', 'solar_power_w_obs', 'battery_power_w_obs', 'exclude_power_fit', 'accel_ms2'} の結果を代入する。
  4. 条件 not enabled or not required.issubset(frame.columns) を判定し、真なら内部処理を行う。
  5. out に frame.copy() の結果を代入する。
  6. out['accel_ms2_previous'] に pd.to_numeric(out['accel_ms2'], errors='coerce') の結果を代入する。
  7. out['accel_ms2_raw'] に _acceleration_trace_from_speed(out, method='median', window_samples=1) の結果を代入する。
  8. dt_sec に pd.to_numeric(out.get('dt_sec'), errors='coerce') の結果を代入する。
  9. usable_dt に dt_sec[np.isfinite(dt_sec) & (dt_sec > 0.0) & (dt_sec <= 60.0)] の結果を代入する。
  10. sample_period_sec に float(np.median(usable_dt)) if len(usable_dt) else 5.0 の結果を代入する。

### L1631 関数 `_grade_from_smoothed_elevation`

- 定義: `_grade_from_smoothed_elevation(distance_km, elevation_m, smoothing_window_km)`
- このブロックが直接呼ぶ主な関数/メソッド: `diff`, `float`, `gradient`, `int`, `len`, `max`, `median`, `min`, `round`, `savgol_filter`
- 戻り値の要点: `np.gradient(smoothed, distance_km) * 0.1 / np.gradient(elevation_m, distance_km) * 0.1`
- 上から順の処理:
  1. spacing に float(np.median(np.diff(distance_km))) の結果を代入する。
  2. samples に max(3, int(round(float(smoothing_window_km) / max(spacing, 1e-09)))) の結果を代入する。
  3. 条件 samples % 2 == 0 を判定し、真なら内部処理を行う。
  4. samples に min(samples, len(elevation_m) if len(elevation_m) % 2 else len(elevation_m) - 1) の結果を代入する。
  5. 条件 samples < 3 を判定し、真なら内部処理を行う。
  6. smoothed に savgol_filter(elevation_m, samples, min(2, samples - 1), mode='interp') の結果を代入する。
  7. np.gradient(smoothed, distance_km) * 0.1 を返す。

### L1653 関数 `fit_grade_observation_alignment`

- 定義: `fit_grade_observation_alignment(frame, route_profile_csv, output_csv, base_model, mot, options)`
- docstring: Cross-validate a DEM smoothing length and distance alignment.

This stage calibrates the route observation, not vehicle mass or resistance.
The selected route stores the unscaled DEM grade. ``grade_scale`` remains a
separately fitted model coefficient in the following motion fit.
- このブロックが直接呼ぶ主な関数/メソッド: `DataFrame`, `MotionFitResult`, `_grade_from_smoothed_elevation`, `_motion_predictions_for_acceleration`, `all`, `append`, `arange`, `astype`, `bool`, `copy`, `diff`, `difference`
- 戻り値の要点: `(out, {'enabled': True, 'adopted': True, 'reason': 'training_improvement_and_last_day_holdout_passed', 'method': 'Savitzky-Golay DEM elevation differentiation with last-day holdout', 'source_route_profile_csv': str(route_profile_csv), 'adopted_route_profile_csv': str(output_csv), 'holdout_day': holdout_day, 'training_sample_count': int(train_mask.sum()), 'validation_sample_count': int(validation_mask.sum()), 'selected_smoothing_window_km': selected_window, 'smoothing_search_max_km': smoothing_search_max, 'smoothing_search_boundary_hit': smoothing_boundary_hit, 'selected_distance_offset_km': selected_offset, 'selected_provisional_grade_scale': float(best['provisional_grade_scale']), 'baseline_training_rmse_w': baseline_training_rmse, 'selected_training_rmse_w': float(best['training_rmse_w']), 'training_improvement_w': training_improvement, 'baseline_validation_rmse_w': baseline_validation_rmse, 'selected_validation_rmse_w': float(best['validation_rmse_w']), 'validation_rmse_ratio': validation_ratio, 'candidate_count': len(records), 'top_candidates': top_candidates}, output_csv) / (frame.copy(), {'enabled': bool(cfg.get('enabled', True)), 'adopted': False, 'reason': 'disabled_or_route_profile_missing'}, None) / (frame.copy(), {'enabled': True, 'adopted': False, 'reason': 'route_profile_requires_distance_and_elevation', 'route_profile_csv': str(route_profile_csv)}, None) / (frame.copy(), {'enabled': True, 'adopted': False, 'reason': 'insufficient_monotonic_route_elevation_samples', 'sample_count': int(len(source))}, None)`
- 上から順の処理:
  1. cfg に options if isinstance(options, dict) else {} の結果を代入する。
  2. 条件 not bool(cfg.get('enabled', True)) or not route_profile_csv.is_file() を判定し、真なら内部処理を行う。
  3. route に pd.read_csv(route_profile_csv) の結果を代入する。
  4. distance_column に next((key for key in ('dist_km', 's_km', 'distance_km') if key in route.columns), None) の結果を代入する。
  5. elevation_column に next((key for key in ('elev_m', 'elev_dem_m', 'alt_m', 'altitude_m') if key in route.columns), None) の結果を代入する。
  6. 条件 distance_column is None or elevation_column is None を判定し、真なら内部処理を行う。
  7. source に pd.DataFrame({'dist_km': pd.to_numeric(route[distance_column], errors='coerce'), 'elev_m': pd.to_numeric(route[elevation_column], errors='coerce')}).dropna() の結果を代入する。
  8. source に source.groupby('dist_km', as_index=False).mean().sort_values('dist_km') の結果を代入する。
  9. 条件 len(source) < 21 or not np.all(np.diff(source['dist_km'].to_numpy()) > 0.0) を判定し、真なら内部処理を行う。
  10. required に {'day', 's_km', 'speed_kmh', 'accel_ms2', 'headwind_archive_ms', 'solar_power_w_obs', 'battery_power_w_obs', 'exclude_power_fit', 'slope_pct'} の結果を代入する。

### L1886 関数 `pv_leave_one_day_out_validation`

- 定義: `pv_leave_one_day_out_validation(frame, model, panel_deployment_options)`
- docstring: Validate the PV chain on days excluded from all PV-scalar fitting.
- このブロックが直接呼ぶ主な関数/メソッド: `ValueError`, `asarray`, `astype`, `attach_archive_pv_model`, `copy`, `dict`, `difference`, `drop`, `drop_duplicates`, `dropna`, `extend`, `fillna`
- 戻り値の要点: `{'pv_lodo_fold_count': int(fold_count), 'pv_lodo_moving_rmse_w': rmse(moving_residuals), 'pv_lodo_moving_sample_count': int(len(moving_residuals)), 'pv_lodo_deployed_stop_rmse_w': rmse(deployed_residuals), 'pv_lodo_deployed_stop_sample_count': int(len(deployed_residuals))} / float(np.sqrt(np.mean(np.square(array)))) if array.size else float('nan')`
- 上から順の処理:
  1. required に {'time_utc', 'speed_kmh', 'GHI_archive', 'DNI_archive', 'DHI_archive', 'Tamb_archive_C', 'solar_power_w_obs', 'exclude_weather_fit'} の結果を代入する。
  2. missing に sorted(required.difference(frame.columns)) の結果を代入する。
  3. 条件 missing を判定し、真なら内部処理を行う。
  4. keep に sorted(required.union({'day', 's_km'}).intersection(frame.columns)) の結果を代入する。
  5. work に frame.loc[:, keep].copy() の結果を代入する。
  6. 条件 'day' in work.columns を判定し、真なら内部処理を行う。
  7. deployment に dict(panel_deployment_options or {}) の結果を代入する。
  8. moving_residuals に [] の結果を代入する。
  9. deployed_residuals に [] の結果を代入する。
  10. fold_count に 0 の結果を代入する。

### L1964 関数 `add_end_to_end_metrics`

- 定義: `add_end_to_end_metrics(primary, end_to_end)`
- このブロックが直接呼ぶ主な関数/メソッド: `dict`, `items`
- 戻り値の要点: `out`
- 上から順の処理:
  1. out に dict(primary) の結果を代入する。
  2. end_to_end.items() を順に走査し、各要素を (key, value) に入れて処理する。
  3. out['vehicle_fit_solar_source'] に 'measured_when_available' の結果を代入する。
  4. out['end_to_end_solar_source'] に 'weather_and_pv_model' の結果を代入する。
  5. out を返す。

### L1973 関数 `add_battery_conditional_metrics`

- 定義: `add_battery_conditional_metrics(primary, conditional)`
- このブロックが直接呼ぶ主な関数/メソッド: `dict`, `items`
- 戻り値の要点: `out`
- 上から順の処理:
  1. out に dict(primary) の結果を代入する。
  2. conditional.items() を順に走査し、各要素を (key, value) に入れて処理する。
  3. out['battery_conditional_source'] に 'observed_pack_power_and_current' の結果を代入する。
  4. out を返す。

### L1981 関数 `write_replay_csv`

- 定義: `write_replay_csv(frame, output_path, chunk_rows)`
- docstring: Write large replay tables without materializing a full string copy.
- このブロックが直接呼ぶ主な関数/メソッド: `copy`, `ensure_dir`, `int`, `len`, `max`, `range`, `strftime`, `to_csv`, `to_datetime`
- 上から順の処理:
  1. ensure_dir(...) を実行する。
  2. rows に max(1, int(chunk_rows)) の結果を代入する。
  3. range(0, len(frame), rows) を順に走査し、各要素を start に入れて処理する。

### L1998 関数 `apply_fit_to_cfg`

- 定義: `apply_fit_to_cfg(cfg, package_dir, map_assets, pv, batt, mot, observed_log_csv, battery_dynamic_fit, solar_measurement_calibration, sync_sim_soc0)`
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `ValueError`, `clip`, `dropna`, `float`, `get`, `items`, `max`, `min`, `read_csv`, `relpath`, `replace`
- 戻り値の要点: `cfg`
- 上から順の処理:
  1. cfg.setdefault(...) を実行する。
  2. map_assets.items() を順に走査し、各要素を (key, path) に入れて処理する。
  3. cfg['paths']['progress_reference_csv'] に os.path.relpath(observed_log_csv, package_dir).replace('\\', '/') の結果を代入する。
  4. model に cfg.setdefault('model', {}) の結果を代入する。
  5. model['CdA'] に round(float(mot.cda), 6) の結果を代入する。
  6. model['Crr'] に round(float(mot.crr), 6) の結果を代入する。
  7. model['P_aux'] に round(float(mot.p_aux_w), 3) の結果を代入する。
  8. model['P_aux_stopped'] に round(float(mot.p_aux_w), 3) の結果を代入する。
  9. model['P_aux_night'] に 0.0 の結果を代入する。
  10. model.setdefault(...) を実行する。

### L2113 関数 `update_profile`

- 定義: `update_profile(profile_yaml, cfg, map_assets, pv, batt, mot, observed_log_csv, battery_dynamic_fit, solar_measurement_calibration, route_profile_asset, package_dir)`
- このブロックが直接呼ぶ主な関数/メソッド: `Path`, `apply_fit_to_cfg`, `exists`, `get`, `is_absolute`, `items`, `list`, `open`, `relpath_from`, `resolve`, `safe_dump`, `setdefault`
- 上から順の処理:
  1. package_dir に profile_yaml.parent if package_dir is None else Path(package_dir) の結果を代入する。
  2. cfg に apply_fit_to_cfg(cfg, package_dir=package_dir, map_assets=map_assets, pv=pv, batt=batt, mot=mot, battery_dynamic_fit=battery_dynamic_fit, solar_measurement_calibration=solar_measurement_calibration, observed_log_csv=observed_log_csv, sync_sim_soc0=False) の結果を代入する。
  3. 条件 route_profile_asset is not None を判定し、真なら内部処理を行う。
  4. 条件 profile_yaml.parent.resolve() != package_dir.resolve() を判定し、真なら内部処理を行う。
  5. with 文で profile_yaml.open('w', encoding='utf-8', newline='\n') を管理しながら処理する。

### L2157 関数 `update_profile_artifact_references`

- 定義: `update_profile_artifact_references(profile_yaml, package_dir, fit_summary_yaml, terminal_consistency_yaml)`
- このブロックが直接呼ぶ主な関数/メソッド: `is_file`, `pop`, `read_text`, `relpath_from`, `safe_dump`, `safe_load`, `setdefault`, `write_text`
- 上から順の処理:
  1. cfg に yaml.safe_load(profile_yaml.read_text(encoding='utf-8')) or {} の結果を代入する。
  2. identification に cfg.setdefault('identification', {}) の結果を代入する。
  3. identification['fit_summary_yaml'] に relpath_from(profile_yaml.parent, fit_summary_yaml) の結果を代入する。
  4. 条件 terminal_consistency_yaml is not None and terminal_consistency_yaml.is_file() を判定し、真なら内部処理を行う。
  5. profile_yaml.write_text(...) を実行する。

### L2180 関数 `write_terminal_consistency_from_anchor`

- 定義: `write_terminal_consistency_from_anchor(output_path, terminal_anchor, max_spread, validation_metrics, replay_soc_error_max, replay_voltage_error_max_v, vehicle_soc_error_max, vehicle_voltage_error_max_v, end_to_end_soc_error_max, end_to_end_voltage_error_max_v)`
- docstring: Always materialize the independent terminal-evidence gate.

Detailed channel reconstruction may later enrich this file, but profile
adoption must never silently drop the gate merely because a separate
reporting command was not run.
- このブロックが直接呼ぶ主な関数/メソッド: `abs`, `bool`, `float`, `get`, `isfinite`, `list`, `max`, `min`, `mkdir`, `safe_dump`, `write_text`
- 戻り値の要点: `output_path`
- 上から順の処理:
  1. lo に float(terminal_anchor.get('soc_evidence_min', float('nan'))) の結果を代入する。
  2. hi に float(terminal_anchor.get('soc_evidence_max', float('nan'))) の結果を代入する。
  3. target に float(terminal_anchor.get('soc_target', float('nan'))) の結果を代入する。
  4. sigma に float(terminal_anchor.get('soc_sigma', float('nan'))) の結果を代入する。
  5. spread に hi - lo if np.isfinite(lo) and np.isfinite(hi) else float('nan') の結果を代入する。
  6. metrics に validation_metrics or {} の結果を代入する。
  7. replay_soc_error に abs(float(metrics.get('battery_conditional_retire_anchor_soc_error', float('nan')))) の結果を代入する。
  8. replay_voltage_observed に float(metrics.get('battery_conditional_retire_anchor_voltage_obs_v', float('nan'))) の結果を代入する。
  9. replay_voltage_predicted に float(metrics.get('battery_conditional_retire_anchor_voltage_pred_v', float('nan'))) の結果を代入する。
  10. replay_voltage_error に abs(replay_voltage_predicted - replay_voltage_observed) の結果を代入する。

### L2318 関数 `sync_canonical_fullsim_profile`

- 定義: `sync_canonical_fullsim_profile(package_dir, map_assets, pv, batt, mot, observed_log_csv, battery_dynamic_fit, solar_measurement_calibration)`
- このブロックが直接呼ぶ主な関数/メソッド: `ValueError`, `apply_fit_to_cfg`, `exists`, `isinstance`, `open`, `safe_dump`, `safe_load`
- 戻り値の要点: `fullsim_yaml / None`
- 上から順の処理:
  1. fullsim_yaml に package_dir / 'profile_fullsim_selflearned.yaml' の結果を代入する。
  2. 条件 not fullsim_yaml.exists() を判定し、真なら内部処理を行う。
  3. with 文で fullsim_yaml.open('r', encoding='utf-8') を管理しながら処理する。
  4. 条件 not isinstance(cfg, dict) を判定し、真なら内部処理を行う。
  5. cfg に apply_fit_to_cfg(cfg, package_dir=package_dir, map_assets=map_assets, pv=pv, batt=batt, mot=mot, battery_dynamic_fit=battery_dynamic_fit, solar_measurement_calibration=solar_measurement_calibration, observed_log_csv=observed_log_csv, sync_sim_soc0=False) の結果を代入する。
  6. with 文で fullsim_yaml.open('w', encoding='utf-8', newline='\n') を管理しながら処理する。
  7. fullsim_yaml を返す。

### L2353 関数 `write_generic_summary`

- 定義: `write_generic_summary(package_dir, manifest_path, profile_yaml, map_assets, pv, batt, mot, metrics, terminal_anchor, stage_anchors, map_shape_fit, post_refine, day_metrics, battery_dynamic_fit, fit_plan, manifest_context, output_dir, replay_csv, battery_conditioned_replay_csv, end_to_end_replay_csv)`
- このブロックが直接呼ぶ主な関数/メソッド: `dict`, `ensure_dir`, `get`, `items`, `list`, `open`, `relpath`, `relpath_from`, `replace`, `safe_dump`
- 戻り値の要点: `out_path`
- 上から順の処理:
  1. output_dir に output_dir or package_dir / 'outputs' / 'identification' の結果を代入する。
  2. out_path に output_dir / f'{package_dir.name}_generic_fit_summary.yaml' の結果を代入する。
  3. ensure_dir(...) を実行する。
  4. payload に {'builder': 'generic_replay_mle', 'manifest_yaml': os.path.relpath(manifest_path, package_dir).replace('\\', '/'), 'profile_yaml': os.path.relpath(profile_yaml, package_dir).replace('\\', '/'), 'active_maps': {key: os.path.relpath(path, package_dir).replace('\\', '/') for key, path in map_assets.items()}, 'pv_fit': pv.__dict__, 'battery_fit': batt.__dict__, 'battery_dynamic_fit': dict(battery_dynamic_fit or {}), 'motion_fit': mot.__dict__, 'validation_metrics': metrics, 'validation_protocol': {'vehicle_conditional_replay_csv': relpath_from(package_dir, replay_csv), 'battery_conditioned_replay_csv': relpath_from(package_dir, battery_conditioned_replay_csv), 'end_to_end_replay_csv': relpath_from(package_dir, end_to_end_replay_csv), 'vehicle_fit_solar_source': 'measured_when_available', 'battery_conditioned_source': 'observed_pack_power_and_current', 'end_to_end_solar_source': 'independent_GHI_archive_and_moving_PV_model', 'restart_soc_anchor': 'median_of_valid_stationary_window'}, 'terminal_anchor': terminal_anchor, 'stage_anchors': stage_anchors, 'day_metrics': day_metrics, 'map_shape_fit': map_shape_fit, 'post_refine': post_refine.__dict__, 'fit_plan': dict(fit_plan or {}), 'evidence_bundle': {'actual_event_yaml': relpath_from(package_dir, (manifest_context or {}).get('actual_event_path')), 'counterfactual_event_yaml': relpath_from(package_dir, (manifest_context or {}).get('counterfactual_event_path')), 'terminal_anchor_yaml': relpath_from(package_dir, (manifest_context or {}).get('terminal_anchor_path')), 'grounded_map_summary_yaml': relpath_from(package_dir, (manifest_context or {}).get('grounded_summary_path')), 'source_inventory_json': relpath_from(package_dir, (manifest_context or {}).get('source_inventory_path')), 'notes_markdown': relpath_from(package_dir, (manifest_context or {}).get('notes_markdown_path')), 'explicit_grounded_assets': {key: relpath_from(package_dir, path) for key, path in ((manifest_context or {}).get('explicit_grounded_assets') or {}).items()}, 'external_documents': list((manifest_context or {}).get('external_documents', []))}} の結果を代入する。
  5. with 文で out_path.open('w', encoding='utf-8', newline='\n') を管理しながら処理する。
  6. out_path を返す。

### L2422 関数 `write_generic_report`

- 定義: `write_generic_report(package_dir, profile_yaml, manifest_path, summary_yaml, observed_log_csv, pv, batt, mot, metrics, post_refine, map_assets, terminal_anchor, stage_anchors, day_metrics, battery_dynamic_fit, fit_plan, grounded_map_summary, manifest_context, terminal_consistency, report_dir, current_maps_path)`
- このブロックが直接呼ぶ主な関数/メソッド: `bool`, `compile_tex`, `dedent`, `ensure_dir`, `enumerate`, `float`, `get`, `int`, `items`, `join`, `len`, `read_text`
- 戻り値の要点: `(md_path, pdf_path)`
- 上から順の処理:
  1. report_dir に report_dir or package_dir / 'outputs' / 'reports' の結果を代入する。
  2. ensure_dir(...) を実行する。
  3. md_path に report_dir / f'{package_dir.name}_generic_identification_report.md' の結果を代入する。
  4. tex_path に report_dir / f'{package_dir.name}_generic_identification_report.tex' の結果を代入する。
  5. pdf_path に tex_path.with_suffix('.pdf') の結果を代入する。
  6. rel_maps に {key: os.path.relpath(path, package_dir).replace('\\', '/') for key, path in map_assets.items()} の結果を代入する。
  7. terminal_anchor に terminal_anchor or {} の結果を代入する。
  8. stage_anchors に stage_anchors or [] の結果を代入する。
  9. day_metrics に day_metrics or [] の結果を代入する。
  10. battery_dynamic_fit に battery_dynamic_fit or {} の結果を代入する。

### L3075 関数 `main`

- 定義: `main()`
- このブロックが直接呼ぶ主な関数/メソッド: `ArgumentParser`, `Path`, `PostRefineResult`, `R_int`, `ValueError`, `add_argument`, `add_battery_conditional_metrics`, `add_end_to_end_metrics`, `apply_battery_polarization`, `attach_archive_pv_model`, `bool`, `build_grounded_map_assets`
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
  10. ap.add_argument(...) を実行する。


## CLI 引数

- L3077: `--profile`
- L3078: `--manifest`
- L3079: `--quality`
- L3085: `--output-tag`
- L3086: `--adopt-profile`
- L3091: `--allow-map-shape-fit`
- L3092: `--skip-map-shape-fit`
- L3093: `--rebuild-grounded-base-maps`
- L3098: `--manifest-only`

## 処理の流れ

1. CLI 引数を解釈し、main() から処理を起動する。
