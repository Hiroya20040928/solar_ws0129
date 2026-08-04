from __future__ import annotations

import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
from dataclasses import dataclass
from typing import Iterable, List

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート


@dataclass
class UpperDistanceHorizon:                                        # [クラス定義] UpperDistanceHorizon オブジェクトの設計
    ds_seq_km: np.ndarray
    seg_s_km: np.ndarray
    ctrl_s_km: np.ndarray

    @property
    def total_km(self) -> float:                                   # [関数定義] total_km の処理実行ブロック
        return float(np.sum(self.ds_seq_km)) if len(self.ds_seq_km) else 0.0  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _weighted_extra(count: int, growth: float) -> np.ndarray:      # [関数定義] _weighted_extra の処理実行ブロック
    if count <= 1:
        return np.ones(max(1, count), dtype=float)                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    growth = max(1.0, float(growth))
    if abs(growth - 1.0) <= 1.0e-9:
        return np.ones(count, dtype=float)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return np.power(growth, np.arange(count, dtype=float))         # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _adaptive_ds_sequence(                                         # [関数定義] _adaptive_ds_sequence の処理実行ブロック
    target_km: float,
    *,
    max_steps: int,
    min_ds_km: float,
    max_ds_km: float,
    growth: float,
) -> np.ndarray:
    target_km = max(1.0, float(target_km))
    min_ds_km = max(1.0, float(min_ds_km))
    if max_steps <= 1:
        return np.array([target_km], dtype=float)                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if target_km <= min_ds_km:
        return np.array([target_km], dtype=float)                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    step_count = int(min(max_steps, max(1, math.ceil(target_km / min_ds_km))))
    base = np.full(step_count, min_ds_km, dtype=float)
    base_sum = float(base.sum())
    if target_km <= base_sum + 1.0e-9:
        return np.full(step_count, target_km / step_count, dtype=float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    weights = _weighted_extra(step_count, growth)
    weights = weights / max(float(weights.sum()), 1.0e-9)
    ds = base.copy()
    extra_remaining = float(target_km - base_sum)
    cap_value = max(float(max_ds_km), float(min_ds_km))
    caps = np.maximum(0.0, cap_value - ds)
    active = caps > 1.0e-9
    while extra_remaining > 1.0e-9 and np.any(active):
        active_idx = np.flatnonzero(active)
        alloc_weights = weights[active_idx]
        alloc_weights = alloc_weights / max(float(alloc_weights.sum()), 1.0e-9)
        proposal = extra_remaining * alloc_weights
        used = 0.0
        for j, idx in enumerate(active_idx):
            take = min(float(proposal[j]), float(caps[idx]))
            ds[idx] += take
            caps[idx] -= take
            used += take
        extra_remaining -= used
        active = caps > 1.0e-9
        if used <= 1.0e-9:
            break

    if extra_remaining > 1.0e-9:
        ds[-1] += extra_remaining
    return ds                                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_upper_distance_horizon(                                  # [関数定義] build_upper_distance_horizon の処理実行ブロック
    *,
    mode: str,
    s0_km: float,
    race_km: float,
    ds_km: float,
    horizon_km: float,
    max_steps: int,
    ctrl_km: float,
    adaptive_min_ds_km: float,
    adaptive_max_ds_km: float,
    adaptive_growth: float,
) -> UpperDistanceHorizon:
    ds_km = max(1.0, float(ds_km))
    horizon_km = max(ds_km, float(horizon_km))
    remaining_km = max(0.0, float(race_km) - float(s0_km))
    max_steps = max(1, int(max_steps))
    mode = str(mode or "fixed").strip().lower()

    if mode in {"adaptive_full_race", "remaining_race", "full_race"}:
        target_km = max(ds_km, remaining_km if remaining_km > 0.0 else horizon_km)
        ds_seq = _adaptive_ds_sequence(
            target_km,
            max_steps=max_steps,
            min_ds_km=max(ds_km, float(adaptive_min_ds_km)),
            max_ds_km=max(float(adaptive_max_ds_km), max(ds_km, float(adaptive_min_ds_km))),
            growth=float(adaptive_growth),
        )
    else:
        target_km = max(ds_km, min(horizon_km, remaining_km if remaining_km > 0.0 else horizon_km))
        step_count = int(max(1, math.ceil(target_km / ds_km)))
        step_count = min(step_count, max_steps)
        ds_seq = np.full(step_count, ds_km, dtype=float)
        covered_before_last = float(ds_km * max(0, step_count - 1))
        ds_seq[-1] = max(1.0, target_km - covered_before_last)

    seg_s = np.concatenate(([0.0], np.cumsum(ds_seq[:-1], dtype=float)))
    total_km = float(np.sum(ds_seq))
    control_end_km = float(seg_s[-1]) if len(seg_s) else 0.0
    ctrl_step_km = float(ctrl_km) if ctrl_km and ctrl_km > 0.0 else float(ds_seq[0])
    ctrl_step_km = max(1.0, min(ctrl_step_km, max(control_end_km, 1.0)))
    ctrl_s = np.arange(0.0, control_end_km + 1.0e-9, ctrl_step_km, dtype=float)
    if len(ctrl_s) == 0:
        ctrl_s = np.array([0.0], dtype=float)
    if len(ctrl_s) > len(ds_seq):
        ctrl_s = np.array(seg_s, dtype=float)
    if ctrl_s[-1] < control_end_km - 1.0e-9:
        ctrl_s = np.append(ctrl_s, control_end_km)
    return UpperDistanceHorizon(ds_seq_km=ds_seq, seg_s_km=seg_s, ctrl_s_km=ctrl_s)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def plan_segment_index(plan_segments: Iterable[dict], s_km: float) -> int:  # [関数定義] plan_segment_index の処理実行ブロック
    segments: List[dict] = list(plan_segments)
    if not segments:
        return -1                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    s_km = float(s_km)
    for idx, seg in enumerate(segments):
        s_end_km = float(seg.get("s_end_km", seg.get("s_start_km", 0.0)))
        if s_km < s_end_km - 1.0e-9:
            return idx                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return len(segments) - 1                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
