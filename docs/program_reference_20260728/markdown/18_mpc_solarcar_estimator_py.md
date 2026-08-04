# 18. Battery MHE

- ファイル: `mpc_solarcar/estimator.py`
- 種別: `Python`
- 区分: `estimator`

## 役割

観測された I/V/SoC/Tb と model を使って内部 SoC/Tb を短ホライズンで補正する。

## 起動文脈

- 起動文脈: mpc_node 内の状態推定器。
- 呼び出し元: `mpc_node.py`
- 次に読むべきファイル: `mpc_solarcar/model.py`

## 主要ポイント

- BatteryMHE が入力列を保持し、最尤に近い初期状態を逆推定する。
- planner 本体の物理モデルをそのまま使う。

## 主要構造

主要クラスは MheInput, MheMeas, BatteryMHE。 主要関数は push, estimate, cost。

## ファイルを上から読んだときの定義順

- L11: クラス MheInput を定義する。
- L24: クラス MheMeas を定義する。
- L31: クラス BatteryMHE を定義する。

## import 群

- L1: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L94, L96, L98, L100。
- L2: `from collections import deque`
  - 固定長の時系列や遅延キューを効率よく保持するため。 このファイル内での主な使用位置は L45。
- L3: `from dataclasses import dataclass`
  - dataclasses から dataclass を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L10, L23。
- L4: `from typing import Optional, Tuple`
  - typing から Optional, Tuple を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L25, L26, L27, L28, L41, L42, L85。
- L6: `import numpy as np`
  - 数値配列、clip、補間、統計計算を行うため。 このファイル内での主な使用位置は L104。
- L7: `from scipy.optimize import minimize`
  - 連続最適化や MHE の逆推定を解くため。 このファイル内での主な使用位置は L106。

## 関数・クラスを上から順に解説

### L11 クラス `MheInput`

- 定義: `MheInput(bases=なし)`
- 上から順の処理:
  1. v_ms に  を代入する。
  2. slope_pct に  を代入する。
  3. G_poa に  を代入する。
  4. Tcell_C に  を代入する。
  5. Tamb_C に  を代入する。
  6. headwind_ms に  を代入する。
  7. dt に  を代入する。
  8. inertial_power_w に 0.0 を代入する。
  9. elevation_m に 0.0 を代入する。

### L24 クラス `MheMeas`

- 定義: `MheMeas(bases=なし)`
- 上から順の処理:
  1. soc に None を代入する。
  2. Tb に None を代入する。
  3. I に None を代入する。
  4. V に None を代入する。

### L31 クラス `BatteryMHE`

- 定義: `BatteryMHE(bases=なし)`
- このブロックが直接呼ぶ主な関数/メソッド: `_simulate`, `append`, `array`, `deque`, `dict`, `electrical_balance`, `float`, `int`, `isfinite`, `len`, `max`, `minimize`
- 上から順の処理:
  1. 関数 __init__ を定義する。
  2. 関数 push を定義する。
  3. 関数 _simulate を定義する。
  4. 関数 estimate を定義する。


## 処理の流れ

1. ソース中の主要関数を通じて処理を進める。
