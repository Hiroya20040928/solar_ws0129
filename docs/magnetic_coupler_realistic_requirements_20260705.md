# Magnetic Coupler Realistic Requirements

最終更新日: 2026-07-05

## 目的

固定高さの自由配置リング機構について、実機成立性を満たす候補だけを採用する。

## 現在の要求条件

以下をすべて同時に満たした場合のみ `feasible = 1` とみなす。

1. 台車質量は `10.0 kg` 以上。
2. 動的シミュレーション全体で接触イベント総数 `0`。
3. 動的シミュレーション全体で最大めり込み量 `0.0 mm`。
4. 動的シミュレーション全体で最小クリアランス `>= 2.0 mm`。
5. 静的評価で負の並進復元サンプル数 `0`。
6. 静的評価で負の回転復元サンプル数 `0`。
7. 静的評価で吸着危険サンプル数 `0`。
8. 動的シミュレーションでロボット保持力上限制約の超過回数 `0`。
9. 動的シミュレーションでロボット保持トルク上限制約の超過回数 `0`。
10. 動的シミュレーションでクリップ介入回数 `0`。
11. パッケージ違反量 `0.0 mm`。

## いまの評価シナリオ

- 主シナリオ: `corridor_avoid_return_fixedheight`
- 意味: 廊下搬送中に回避して元ルートへ戻る
- 目的: 接触なしで、吸着せず、復元し、ロボット保持限界を超えないことを確認する

## 実装上の支配箇所

- 要求質量下限:
  - `mpc_solarcar/magnetic_coupler_freearray_fixedheight.py`
  - 定数 `REALISTIC_MIN_CART_MASS_KG = 10.0`
- 可否判定:
  - `mpc_solarcar/magnetic_coupler_freearray_fixedheight.py`
  - 関数 `candidate_priority(...)`
- ユーザー向け realistic gate 実行入口:
  - `scripts/run_freearray_fixedheight_realistic_gate.py`

## 現時点の扱い

- これらの条件を満たさない候補は、探索上の途中経過に過ぎず、実機候補とはみなさない。
- したがって、`ranking_score` が改善していても、上記条件のいずれかを破っていれば不合格である。
