# 12. 車体物理・電気モデル本体

- ファイル: `mpc_solarcar/model.py`
- 種別: `Python`
- 区分: `model`

## 役割

空力、転がり、坂、PV、MPPT、drive/regen 効率、battery IV、SoC 更新を統合した vehicle model。

## 起動文脈

- 起動文脈: planner と simulation の数理コア。
- 呼び出し元: `mpc_node.py`, `solar_state_node.py`, `scripts/solar_sim.py`, `estimator.py`
- 次に読むべきファイル: `mpc_solarcar/utils_maps.py`

## 主要ポイント

- SolarCarModel と Params が中心。
- electrical_balance が planner 側で最も多く呼ばれる。
- resistive_forces、battery_iv、soc_step が各所から再利用される。

## 主要構造

主要クラスは Params, SolarCarModel。 主要関数は eff_drive, eff_regen, select_drive_mode, R_int, pv_balance, pv_power_mppt, charge_efficiency, soc_step。

## ファイルを上から読んだときの定義順

- L3: 例外処理を伴う try ブロックを実行する。
- L10: 関数 _is_symbolic を定義する。
- L17: クラス Params を定義する。
- L73: クラス SolarCarModel を定義する。

## import 群

- L1: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L329, L331, L336, L362。
- L2: `import numpy as np`
  - 数値配列、clip、補間、統計計算を行うため。 このファイル内での主な使用位置は L135, L148, L266, L269, L292, L347, L447。
- L4: `import casadi as ca`
  - casadi モジュールを利用するため。 このファイル内での主な使用位置は L6, L11, L12, L126, L128, L130, L139, L143, ...。
- L7: `from dataclasses import dataclass`
  - dataclasses から dataclass を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L16。
- L8: `from .utils_maps import read_eff_map, read_Rint_map, read_map, bilinear_interp, read_1d_map`
  - 効率マップ・抵抗マップ読込補間 から read_eff_map, read_Rint_map, read_map, bilinear_interp, read_1d_map を読み込み、このファイルの内部処理を分担させるため。 実体ファイルは mpc_solarcar/utils_maps.py。 このファイル内での主な使用位置は L81, L82, L93, L95, L97, L99, L101, L106, ...。

## 関数・クラスを上から順に解説

### L10 関数 `_is_symbolic`

- 定義: `_is_symbolic(x)`
- このブロックが直接呼ぶ主な関数/メソッド: `hasattr`, `is_symbolic`, `isinstance`
- 戻り値の要点: `ca is not None and (isinstance(x, (ca.SX, ca.MX)) or (hasattr(x, 'is_symbolic') and x.is_symbolic()))`
- 上から順の処理:
  1. ca is not None and (isinstance(x, (ca.SX, ca.MX)) or (hasattr(x, 'is_symbolic') and x.is_symbolic())) を返す。

### L17 クラス `Params`

- 定義: `Params(bases=なし)`
- 上から順の処理:
  1. dt に 600.0 を代入する。
  2. rho に 1.18 を代入する。
  3. air_density_mode に 'constant' を代入する。
  4. air_density_reference_pressure_pa に 101325.0 を代入する。
  5. CdA に 0.13 を代入する。
  6. Crr に 0.002 を代入する。
  7. Crr_per_wheel に 0.0 を代入する。
  8. m に 250.0 を代入する。
  9. g に 9.80665 を代入する。
  10. P_aux に 60.0 を代入する。
  11. P_aux_stopped に 60.0 を代入する。
  12. P_aux_night に 0.0 を代入する。

### L73 クラス `SolarCarModel`

- 定義: `SolarCarModel(bases=なし)`
- このブロックが直接呼ぶ主な関数/メソッド: `Params`, `R_int`, `_is_symbolic`, `_scaled_slope_pct`, `_select_mode`, `_update_mode_limits`, `abs`, `air_density`, `atan`, `auxiliary_power`, `battery_iv`, `bilinear_interp`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 eff_drive を定義する。
  3. 関数 eff_regen を定義する。
  4. 関数 _update_mode_limits を定義する。
  5. 関数 _select_mode を定義する。
  6. 関数 select_drive_mode を定義する。
  7. 関数 R_int を定義する。
  8. 関数 pv_balance を定義する。
  9. 関数 pv_power_mppt を定義する。
  10. 関数 _scaled_slope_pct を定義する。
  11. 関数 charge_efficiency を定義する。
  12. 関数 soc_step を定義する。


## 処理の流れ

1. ソース中の主要関数を通じて処理を進める。
