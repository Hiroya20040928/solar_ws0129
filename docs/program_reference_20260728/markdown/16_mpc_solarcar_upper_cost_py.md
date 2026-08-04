# 16. 上位MPC 目的関数

- ファイル: `mpc_solarcar/upper_cost.py`
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

## 関数・クラスを上から順に解説

### L8 クラス `UpperCostConfig`

- 定義: `UpperCostConfig(bases=なし)`
- このブロックが直接呼ぶ主な関数/メソッド: `asdict`
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

### L48 関数 `_cfg_value`

- 定義: `_cfg_value(cfg, key, default)`
- このブロックが直接呼ぶ主な関数/メソッド: `isinstance`
- 戻り値の要点: `default / cfg[key]`
- 上から順の処理:
  1. 条件 isinstance(cfg, dict) and key in cfg を判定し、真なら内部処理を行う。
  2. default を返す。

### L54 関数 `load_upper_cost_config`

- 定義: `load_upper_cost_config(mpc_cfg, legacy, default_drive_window)`
- このブロックが直接呼ぶ主な関数/メソッド: `UpperCostConfig`, `_cfg_value`, `float`, `get`, `isinstance`, `lower`, `pick`, `str`, `strip`
- 戻り値の要点: `UpperCostConfig(objective_mode=str(pick('objective_mode', 'weighted')).strip().lower(), w_wait=float(pick('w_wait', 1.0)), w_travel_time=float(pick('w_travel_time', 1.0)), w_terminal_soc_min=float(pick('w_terminal_soc_min', 30.0)), w_day_end_soc_min=float(pick('w_day_end_soc_min', default_drive_window)), w_soc_day_max=float(pick('w_soc_day_max', 10000.0)), w_soc_day_track=float(pick('w_soc_day_track', 0.0)), w_speed_smooth=float(pick('w_speed_smooth', _cfg_value(legacy, 'w_dv', 30.0))), w_dv_limit=float(pick('w_dv_limit', 2.0)), w_speed_limit=float(pick('w_speed_limit', 50.0)), w_drive_window=float(pick('w_drive_window', default_drive_window)), w_current_sq=float(pick('w_current_sq', _cfg_value(legacy, 'w_current', 0.01))), w_pack_energy=float(pick('w_pack_energy', 0.0)), w_joule_loss=float(pick('w_joule_loss', 0.0)), w_aero_energy=float(pick('w_aero_energy', 0.0)), w_mech_energy=float(pick('w_mech_energy', 0.0)), w_speed_quartic=float(pick('w_speed_quartic', 0.0)), w_solar_headroom=float(pick('w_solar_headroom', 0.0)), w_progress_lag=float(pick('w_progress_lag', 0.0)), w_progress_terminal_lag=float(pick('w_progress_terminal_lag', 0.0)), w_kinetic_pos=float(pick('w_kinetic_pos', 0.0)), w_pack_power_slew=float(pick('w_pack_power_slew', 0.0)), w_temp=float(pick('w_temp', _cfg_value(legacy, 'w_T', 5.0))), w_soc_terminal=float(pick('w_soc_terminal', 0.0)), w_soc_floor_barrier=float(pick('w_soc_floor_barrier', 0.0)), w_uncertainty_reserve=float(pick('w_uncertainty_reserve', 0.0)), speed_quartic_scale_kmh=float(pick('speed_quartic_scale_kmh', 80.0)), progress_lag_deadband_km=float(pick('progress_lag_deadband_km', 0.0)), soc_solar_headroom_max=float(pick('soc_solar_headroom_max', 0.92)), solar_headroom_power_scale_w=float(pick('solar_headroom_power_scale_w', 1000.0)), soc_floor_barrier_eps=float(pick('soc_floor_barrier_eps', 0.01)), reserve_soc_per_hour=float(pick('reserve_soc_per_hour', 0.0)), reserve_soc_max_extra=float(pick('reserve_soc_max_extra', 0.0)), constraint_penalty=float(pick('constraint_penalty', 10000.0))) / default / nested[name] / legacy[name]`
- 上から順の処理:
  1. legacy に legacy or {} の結果を代入する。
  2. nested に {} の結果を代入する。
  3. 条件 isinstance(mpc_cfg, dict) を判定し、真なら内部処理を行う。
  4. 関数 pick を定義する。
  5. UpperCostConfig(objective_mode=str(pick('objective_mode', 'weighted')).strip().lower(), w_wait=float(pick('w_wait', 1.0)), w_travel_time=float(pick('w_travel_time', 1.0)), w_terminal_soc_min=float(pick('w_terminal_soc_min', 30.0)), w_day_end_soc_min=float(pick('w_day_end_soc_min', default_drive_window)), w_soc_day_max=float(pick('w_soc_day_max', 10000.0)), w_soc_day_track=float(pick('w_soc_day_track', 0.0)), w_speed_smooth=float(pick('w_speed_smooth', _cfg_value(legacy, 'w_dv', 30.0))), w_dv_limit=float(pick('w_dv_limit', 2.0)), w_speed_limit=float(pick('w_speed_limit', 50.0)), w_drive_window=float(pick('w_drive_window', default_drive_window)), w_current_sq=float(pick('w_current_sq', _cfg_value(legacy, 'w_current', 0.01))), w_pack_energy=float(pick('w_pack_energy', 0.0)), w_joule_loss=float(pick('w_joule_loss', 0.0)), w_aero_energy=float(pick('w_aero_energy', 0.0)), w_mech_energy=float(pick('w_mech_energy', 0.0)), w_speed_quartic=float(pick('w_speed_quartic', 0.0)), w_solar_headroom=float(pick('w_solar_headroom', 0.0)), w_progress_lag=float(pick('w_progress_lag', 0.0)), w_progress_terminal_lag=float(pick('w_progress_terminal_lag', 0.0)), w_kinetic_pos=float(pick('w_kinetic_pos', 0.0)), w_pack_power_slew=float(pick('w_pack_power_slew', 0.0)), w_temp=float(pick('w_temp', _cfg_value(legacy, 'w_T', 5.0))), w_soc_terminal=float(pick('w_soc_terminal', 0.0)), w_soc_floor_barrier=float(pick('w_soc_floor_barrier', 0.0)), w_uncertainty_reserve=float(pick('w_uncertainty_reserve', 0.0)), speed_quartic_scale_kmh=float(pick('speed_quartic_scale_kmh', 80.0)), progress_lag_deadband_km=float(pick('progress_lag_deadband_km', 0.0)), soc_solar_headroom_max=float(pick('soc_solar_headroom_max', 0.92)), solar_headroom_power_scale_w=float(pick('solar_headroom_power_scale_w', 1000.0)), soc_floor_barrier_eps=float(pick('soc_floor_barrier_eps', 0.01)), reserve_soc_per_hour=float(pick('reserve_soc_per_hour', 0.0)), reserve_soc_max_extra=float(pick('reserve_soc_max_extra', 0.0)), constraint_penalty=float(pick('constraint_penalty', 10000.0))) を返す。

### L110 関数 `quad_penalty`

- 定義: `quad_penalty(x, cap)`
- 戻り値の要点: `x * x / 0.0`
- 上から順の処理:
  1. 条件 x <= 0.0 を判定し、真なら内部処理を行う。
  2. 条件 x > cap を判定し、真なら内部処理を行う。
  3. x * x を返す。

### L118 関数 `upper_stage_cost`

- 定義: `upper_stage_cost(cfg, dt_wait, dt_travel, v_kmh, v_prev_kmh, vmax_local_kmh, drive_limits, dv_limit_kmhps, I_a, V_v, P_pv_w, P_pack_w, P_pack_prev_w, P_mech_wheel_w, losses_int_w, losses_line_w, F_aero_n, kinetic_step_wh, z_next, Tb_next_c, term_soc_min, soc_min, soc_max, temp_min_c, temp_max_c, day_end_soc_min, day_end_crossing, soc_day_end_max, soc_day_track_target, soc_day_track_tol, I_max, I_chg_min, V_min, V_max, time_ahead_h, progress_lag_km)`
- このブロックが直接呼ぶ主な関数/メソッド: `abs`, `float`, `max`, `min`, `quad_penalty`
- 戻り値の要点: `J / J`
- 上から順の処理:
  1. J に 0.0 の結果を代入する。
  2. 条件 dt_wait > 0.0 を判定し、真なら内部処理を行う。
  3. J を Add で更新する。
  4. 条件 cfg.objective_mode in {'fastest', 'fastest_feasible', 'minimum_time'} を判定し、真なら内部処理を行う。
  5. J を Add で更新する。
  6. 条件 soc_day_track_target is not None を判定し、真なら内部処理を行う。
  7. dv に (v_kmh - v_prev_kmh) / max(dt_travel, 0.001) の結果を代入する。
  8. J を Add で更新する。
  9. 条件 dv_limit_kmhps > 0.0 を判定し、真なら内部処理を行う。
  10. 条件 drive_limits is not None を判定し、真なら内部処理を行う。

### L263 関数 `upper_terminal_cost`

- 定義: `upper_terminal_cost(cfg, z_terminal, term_soc_min, soc_finish_target, soc_finish_tol, progress_terminal_lag_km)`
- このブロックが直接呼ぶ主な関数/メソッド: `float`, `max`, `quad_penalty`
- 戻り値の要点: `J`
- 上から順の処理:
  1. J に cfg.constraint_penalty * quad_penalty(term_soc_min - z_terminal) の結果を代入する。
  2. 条件 soc_finish_target > 0.0 を判定し、真なら内部処理を行う。
  3. 条件 cfg.w_progress_terminal_lag > 0.0 を判定し、真なら内部処理を行う。
  4. J を返す。

### L283 関数 `active_upper_cost_terms`

- 定義: `active_upper_cost_terms(cfg, threshold)`
- このブロックが直接呼ぶ主な関数/メソッド: `abs`, `float`, `items`, `startswith`, `to_dict`
- 戻り値の要点: `out`
- 上から順の処理:
  1. out に {} の結果を代入する。
  2. cfg.to_dict().items() を順に走査し、各要素を (key, value) に入れて処理する。
  3. out を返す。


## 処理の流れ

1. ソース中の主要関数を通じて処理を進める。
