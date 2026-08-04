# 25. 自動校正ロジック関数群

- ファイル: `mpc_solarcar/solar_autocal_logic.py`
- 種別: `Python`
- 区分: `runtime helper`

## 役割

solar_autocal_node が使う昼間停止時 aux 推定などの純ロジック関数をまとめる。

## 起動文脈

- 起動文脈: Node から切り出された小さな判定ロジック。
- 呼び出し元: `mpc_solarcar/solar_autocal_node.py`
- 次に読むべきファイル: 特になし

## 主要ポイント

- Node 依存を持たないので単体試験しやすい。

## 主要構造

主要関数は daytime_stationary_aux_estimate。

## ファイルを上から読んだときの定義順

- L8: 関数 daytime_stationary_aux_estimate を定義する。

## import 群

- L3: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L5: `import math`
  - clip、sqrt、sin/cos、有限判定など数値ロジックに使うため。 このファイル内での主な使用位置は L18。

## 関数・クラスを上から順に解説

### L8 関数 `daytime_stationary_aux_estimate`

- 定義: `daytime_stationary_aux_estimate(ghi_wm2, day_ghi_threshold_wm2, speed_kmh, stationary_speed_kmh, pack_power_w, solar_power_w)`
- このブロックが直接呼ぶ主な関数/メソッド: `abs`, `all`, `float`, `isfinite`, `max`
- 戻り値の要点: `max(0.0, float(pack_power_w) + float(solar_power_w)) / None / None / None`
- 上から順の処理:
  1. values に (ghi_wm2, speed_kmh, pack_power_w, solar_power_w) の結果を代入する。
  2. 条件 not all((math.isfinite(float(value)) for value in values)) を判定し、真なら内部処理を行う。
  3. 条件 float(ghi_wm2) < float(day_ghi_threshold_wm2) を判定し、真なら内部処理を行う。
  4. 条件 abs(float(speed_kmh)) > float(stationary_speed_kmh) を判定し、真なら内部処理を行う。
  5. max(0.0, float(pack_power_w) + float(solar_power_w)) を返す。


## 処理の流れ

1. ソース中の主要関数を通じて処理を進める。
