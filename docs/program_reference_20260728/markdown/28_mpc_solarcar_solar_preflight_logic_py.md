# 28. preflight 判定ロジック

- ファイル: `mpc_solarcar/solar_preflight_logic.py`
- 種別: `Python`
- 区分: `runtime helper`

## 役割

計測鮮度や command gate の純判定を Node 本体から切り出したロジック関数群。

## 起動文脈

- 起動文脈: preflight と speed bridge の共通判定層。
- 呼び出し元: `mpc_solarcar/solar_preflight_node.py`, `mpc_solarcar/speed_command_bridge_node.py`
- 次に読むべきファイル: 特になし

## 主要ポイント

- evaluate_freshness と evaluate_command_gate が中心。

## 主要構造

主要クラスは FreshnessResult, CommandGateResult。 主要関数は evaluate_freshness, evaluate_command_gate。

## ファイルを上から読んだときの定義順

- L7: クラス FreshnessResult を定義する。
- L14: クラス CommandGateResult を定義する。
- L19: 関数 evaluate_freshness を定義する。
- L43: 関数 evaluate_command_gate を定義する。

## import 群

- L1: `from __future__ import annotations`
  - 型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。 このファイル内での使用位置は少ないか、間接利用である。
- L3: `from dataclasses import dataclass`
  - dataclasses から dataclass を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L6, L13。

## 関数・クラスを上から順に解説

### L7 クラス `FreshnessResult`

- 定義: `FreshnessResult(bases=なし)`
- このブロックが直接呼ぶ主な関数/メソッド: `dataclass`
- 上から順の処理:
  1. state に  を代入する。
  2. health に  を代入する。
  3. diagnostic に  を代入する。

### L14 クラス `CommandGateResult`

- 定義: `CommandGateResult(bases=なし)`
- このブロックが直接呼ぶ主な関数/メソッド: `dataclass`
- 上から順の処理:
  1. allowed に  を代入する。
  2. reason に  を代入する。

### L19 関数 `evaluate_freshness`

- 定義: `evaluate_freshness(elapsed_sec, ages_sec, required, timeout_sec, startup_grace_sec)`
- このブロックが直接呼ぶ主な関数/メソッド: `FreshnessResult`, `float`, `get`, `join`
- 戻り値の要点: `FreshnessResult('RUNNING', 1.0, 'solar telemetry and planner inputs are fresh') / FreshnessResult('STARTING', 0.25, 'waiting for required solar telemetry') / FreshnessResult('DEGRADED', 0.2, 'missing: ' + ', '.join(missing)) / FreshnessResult('DEGRADED', 0.4, 'stale: ' + ', '.join(stale))`
- 上から順の処理:
  1. 条件 elapsed_sec < startup_grace_sec を判定し、真なら内部処理を行う。
  2. missing に [name for name in required if ages_sec.get(name) is None] の結果を代入する。
  3. stale に [name for name in required if ages_sec.get(name) is not None and float(ages_sec[name]) > timeout_sec] の結果を代入する。
  4. 条件 missing を判定し、真なら内部処理を行う。
  5. 条件 stale を判定し、真なら内部処理を行う。
  6. FreshnessResult('RUNNING', 1.0, 'solar telemetry and planner inputs are fresh') を返す。

### L43 関数 `evaluate_command_gate`

- 定義: `evaluate_command_gate(elapsed_sec, speed_input_age_sec, system_state, system_state_age_sec, startup_hold_sec, input_timeout_sec, system_state_timeout_sec, require_system_running)`
- このブロックが直接呼ぶ主な関数/メソッド: `CommandGateResult`, `max`, `str`, `strip`, `upper`
- 戻り値の要点: `CommandGateResult(True, 'ok') / CommandGateResult(False, 'startup_hold') / CommandGateResult(False, 'missing_speed_command') / CommandGateResult(False, 'stale_speed_command')`
- 上から順の処理:
  1. 条件 elapsed_sec < max(0.0, startup_hold_sec) を判定し、真なら内部処理を行う。
  2. 条件 speed_input_age_sec is None を判定し、真なら内部処理を行う。
  3. 条件 speed_input_age_sec > max(0.0, input_timeout_sec) を判定し、真なら内部処理を行う。
  4. 条件 not require_system_running を判定し、真なら内部処理を行う。
  5. 条件 system_state_age_sec is None を判定し、真なら内部処理を行う。
  6. 条件 system_state_age_sec > max(0.0, system_state_timeout_sec) を判定し、真なら内部処理を行う。
  7. 条件 str(system_state).strip().upper() != 'RUNNING' を判定し、真なら内部処理を行う。
  8. CommandGateResult(True, 'ok') を返す。


## 処理の流れ

1. ソース中の主要関数を通じて処理を進める。
