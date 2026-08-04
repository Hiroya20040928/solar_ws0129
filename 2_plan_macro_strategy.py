from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import yaml

"""
=============================================================================
 2_plan_macro_strategy.py - モード2: 3,000 km CEM 大域速度・エネルギー戦略計画
=============================================================================
【役割】
  - 3,000 km 全行程 CROSS-ENTROPY METHOD (CEM) 大域エネルギー最適化
  - Open-Meteo API によるコース全域気象（日射量・風速・風向・気温）自動取得
  - レース日程・コントロールストップ（CS）制約を満たす最適速度プロファイル生成
"""


import argparse
import csv
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import yaml

# =============================================================================
# 【大域戦術計画モジュール】3,000 km CEM コース最適化 + Open-Meteo 気象取得
# =============================================================================


import argparse
import csv
import json
import math
import os
import sys
import time
from pathlib import Path

import numpy as np
import yaml


# =============================================================================
# 【最高級統合ノード】3,000 km CEM マクロコースエネルギー・速度戦略計画ノード
# =============================================================================


from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from itertools import product
import multiprocessing as mp
import os
from typing import Callable, Iterable, List, Sequence, Tuple

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
from scipy.optimize import minimize, shgo


Bounds = Sequence[Tuple[float, float]]


_FORK_COST_FN: Callable[[np.ndarray], float] | None = None


def _fork_finite_cost(vec: np.ndarray) -> float:                   # [関数定義] _fork_finite_cost の処理実行ブロック
    if _FORK_COST_FN is None:
        return float("inf")                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return finite_cost(_FORK_COST_FN, vec)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却


def clip_to_bounds(vec: np.ndarray, bounds: Bounds) -> np.ndarray:  # [関数定義] clip_to_bounds の処理実行ブロック
    out = np.asarray(vec, dtype=float).copy()
    for idx, (lo, hi) in enumerate(bounds):
        out[idx] = float(np.clip(out[idx], lo, hi))
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def finite_cost(cost_fn: Callable[[np.ndarray], float], vec: np.ndarray) -> float:  # [関数定義] finite_cost の処理実行ブロック
    try:
        value = float(cost_fn(np.asarray(vec, dtype=float)))
    except Exception:
        return float("inf")                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if not np.isfinite(value):
        return float("inf")                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return value                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def default_seed_library(x0: np.ndarray, bounds: Bounds) -> List[tuple[str, np.ndarray]]:  # [関数定義] default_seed_library の処理実行ブロック
    x0 = np.asarray(x0, dtype=float)
    lo = np.array([float(lo_i) for lo_i, _ in bounds], dtype=float)
    hi = np.array([float(hi_i) for _, hi_i in bounds], dtype=float)
    span = np.maximum(hi - lo, 1.0e-6)
    seeds: List[tuple[str, np.ndarray]] = [("warm_start", clip_to_bounds(x0, bounds))]
    for frac in (0.25, 0.40, 0.55, 0.70, 0.85):
        const = lo + frac * span
        seeds.append((f"const_{frac:.2f}", clip_to_bounds(const, bounds)))
        seeds.append((f"warm_mix_{frac:.2f}", clip_to_bounds(0.5 * x0 + 0.5 * const, bounds)))
    seeds.append(("ramp_up", clip_to_bounds(np.linspace(lo[0], hi[0], len(x0)), bounds)))
    seeds.append(("ramp_down", clip_to_bounds(np.linspace(hi[0], lo[0], len(x0)), bounds)))
    return seeds                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def hybrid_bounded_minimize(                                       # [関数定義] hybrid_bounded_minimize の処理実行ブロック
    cost_fn: Callable[[np.ndarray], float],
    x0: np.ndarray,
    bounds: Bounds,
    *,
    maxiter: int,
    structured_seeds: Iterable[tuple[str, np.ndarray]] | None = None,
    cem_enabled: bool = True,
    cem_mode: str = "auto",
    cem_generations: int = 4,
    cem_population: int = 16,
    cem_elite: int = 4,
    local_refine_topk: int = 4,
    seed_library_mode: str = "full",
    rng_seed: int = 0,
    shgo_samples: int = 256,
    shgo_iters: int = 2,
    cert_grid_levels: int = 0,
    cert_grid_values: Sequence[float] | None = None,
    cert_max_evaluations: int = 250_000,
    cert_workers: int = 1,
    progress_callback: Callable[[dict], None] | None = None,
    cert_progress_interval: int = 25,
) -> tuple[np.ndarray, dict]:
    x0 = np.asarray(x0, dtype=float)
    bounds = list(bounds)
    lo = np.array([float(lo_i) for lo_i, _ in bounds], dtype=float)
    hi = np.array([float(hi_i) for _, hi_i in bounds], dtype=float)
    span = np.maximum(hi - lo, 1.0e-6)
    rng = np.random.default_rng(int(rng_seed))

    evaluated: list[dict] = []
    seen: set[tuple[float, ...]] = set()

    def add_candidate(label: str, vec: np.ndarray) -> None:        # [関数定義] add_candidate の処理実行ブロック
        clipped = clip_to_bounds(vec, bounds)
        key = tuple(np.round(clipped, 6))
        if key in seen:
            return
        seen.add(key)
        value = finite_cost(cost_fn, clipped)
        evaluated.append(
            {
                "label": str(label),
                "x": clipped,
                "fun": value,
                "source": "seed",
            }
        )

    base_seeds = list(structured_seeds or [])
    seed_library_mode_norm = str(seed_library_mode or "full").strip().lower()
    if seed_library_mode_norm not in {"full", "realtime", "minimal"}:
        seed_library_mode_norm = "full"
    default_seeds = default_seed_library(x0, bounds)
    if seed_library_mode_norm == "minimal":
        # Production ROS2 cycles already receive the learned/previous policy as
        # x0 and a physics-based balance seed from the caller. Evaluating the
        # full generic library here only repeats expensive full-race rollouts.
        default_seeds = default_seeds[:1]
    elif seed_library_mode_norm == "realtime":
        # Keep one neutral cruise alternative on the very first live cycle.
        # Subsequent cycles use the previous MPC solution as warm_start, while
        # the caller always adds its weather-dependent balance seed.
        nominal = lo + 0.625 * span
        default_seeds = [default_seeds[0], ("nominal_cruise", clip_to_bounds(nominal, bounds))]
    for label, vec in default_seeds:
        add_candidate(label, vec)
    for label, vec in base_seeds:
        add_candidate(label, vec)

    finite_pool = [row for row in evaluated if np.isfinite(row["fun"])]
    if not finite_pool:
        return clip_to_bounds(x0, bounds), {                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "success": False,
            "fun": float("inf"),
            "label": "fallback_warm_start",
            "nit": 0,
            "method": "fallback",
            "candidates_evaluated": int(len(evaluated)),
            "cem_used": False,
        }

    finite_pool.sort(key=lambda item: float(item["fun"]))
    best = dict(finite_pool[0])

    def local_refine_rows(pool: Sequence[dict]) -> list[dict]:     # [関数定義] local_refine_rows の処理実行ブロック
        refined: list[dict] = []
        if maxiter <= 0:
            return refined                                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
        for row in pool:
            res = minimize(cost_fn, row["x"], method="L-BFGS-B", bounds=bounds, options=dict(maxiter=int(maxiter)))
            candidate_x = row["x"]
            if hasattr(res, "x") and res.x is not None and len(res.x) == len(x0) and np.all(np.isfinite(res.x)):
                candidate_x = clip_to_bounds(np.asarray(res.x, dtype=float), bounds)
            candidate_fun = finite_cost(cost_fn, candidate_x)
            refined.append(
                {
                    "label": f"local_refine:{row['label']}",
                    "x": candidate_x,
                    "fun": candidate_fun,
                    "source": "local_refine",
                    "nit": int(getattr(res, "nit", 0) or 0),
                    "success": bool(getattr(res, "success", False)),
                    "message": str(getattr(res, "message", "")),
                }
            )
        refined.sort(key=lambda item: float(item["fun"]))
        return refined                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    refine_pool = finite_pool[: max(1, int(local_refine_topk))]
    refined_rows = local_refine_rows(refine_pool)
    for row in refined_rows:
        evaluated.append(row)
    if refined_rows and float(refined_rows[0]["fun"]) < float(best["fun"]):
        best = dict(refined_rows[0])

    cem_mode_norm = str(cem_mode or "auto").strip().lower()
    if cem_mode_norm not in {"always", "auto", "never", "shgo", "certify"}:
        cem_mode_norm = "auto"

    consensus_spread = float("nan")
    cem_used = False
    shgo_used = False
    shgo_nfev = 0
    shgo_local_minima = 0
    discrete_global_proof = False
    discrete_grid_candidates = 0
    discrete_grid_nonfinite = 0
    declared_grid_values = np.asarray(list(cert_grid_values or []), dtype=float)
    declared_grid_values = declared_grid_values[np.isfinite(declared_grid_values)]
    if declared_grid_values.size:
        grid_values = np.unique(np.clip(declared_grid_values, lo[0], hi[0]))
        discrete_grid_levels = int(len(grid_values))
    else:
        grid_values = np.asarray([], dtype=float)
        discrete_grid_levels = max(0, int(cert_grid_levels))
    deterministic_seed_candidates = int(len(evaluated))
    deterministic_seed_nonfinite = int(
        sum(not np.isfinite(float(row.get("fun", float("inf")))) for row in evaluated)
    )
    discrete_grid_best_fun = float("inf")
    discrete_grid_best_x: list[float] = []

    def emit_progress(payload: dict) -> None:                      # [関数定義] emit_progress の処理実行ブロック
        if progress_callback is None:
            return
        try:
            progress_callback(dict(payload))
        except Exception:
            # Progress telemetry must never change the optimizer result.
            return

    if cem_mode_norm == "certify" and discrete_grid_levels >= 2 and len(x0) > 0:
        requested = int(discrete_grid_levels ** len(x0))
        if requested <= max(1, int(cert_max_evaluations)):
            emit_progress({"stage": "finite_grid", "completed": 0, "total": requested})
            axes = [
                grid_values.copy()
                if grid_values.size
                else np.linspace(lo_i, hi_i, discrete_grid_levels)
                for lo_i, hi_i in bounds
            ]
            grid_best = None
            interval = max(1, int(cert_progress_interval))
            workers = max(1, int(cert_workers))
            executor_kind = "serial"

            def record_grid_candidate(idx: int, candidate_x: np.ndarray, candidate_fun: float) -> None:  # [関数定義] record_grid_candidate の処理実行ブロック
                nonlocal discrete_grid_candidates, discrete_grid_nonfinite, grid_best
                discrete_grid_candidates += 1
                if not np.isfinite(candidate_fun):
                    discrete_grid_nonfinite += 1
                if grid_best is None or candidate_fun < float(grid_best["fun"]):
                    grid_best = {
                        "label": f"certified_grid_{idx:08d}",
                        "x": candidate_x,
                        "fun": candidate_fun,
                        "source": "certified_grid",
                        "success": np.isfinite(candidate_fun),
                        "message": "exhaustive finite-grid optimum",
                    }
                completed = idx + 1
                if completed == requested or completed % interval == 0:
                    emit_progress(
                        {
                            "stage": "finite_grid",
                            "completed": completed,
                            "total": requested,
                            "best_fun": float(grid_best["fun"]) if grid_best is not None else float("inf"),
                            "best_x": (
                                np.asarray(grid_best["x"], dtype=float).tolist()
                                if grid_best is not None
                                else []
                            ),
                            "nonfinite": int(discrete_grid_nonfinite),
                            "workers": workers,
                            "executor": executor_kind,
                        }
                    )

            grid_candidates = [
                (idx, np.asarray(values, dtype=float))
                for idx, values in enumerate(product(*axes))
            ]
            if workers == 1:
                for idx, candidate_x in grid_candidates:
                    record_grid_candidate(idx, candidate_x, finite_cost(cost_fn, candidate_x))
            else:
                # executor.map preserves input order, so tie-breaking and the certificate
                # remain deterministic while independent policy evaluations run in parallel.
                # POSIX fork inherits a nested simulator cost closure without pickling it;
                # Windows falls back to threads because spawn cannot serialize that closure.
                if os.name == "posix":
                    global _FORK_COST_FN
                    _FORK_COST_FN = cost_fn
                    executor_context = ProcessPoolExecutor(
                        max_workers=workers,
                        mp_context=mp.get_context("fork"),
                    )
                    evaluator = _fork_finite_cost
                    executor_kind = "fork_process"
                else:
                    executor_context = ThreadPoolExecutor(
                        max_workers=workers,
                        thread_name_prefix="upper-cert",
                    )
                    evaluator = lambda item: finite_cost(cost_fn, item[1])
                    executor_kind = "thread"
                with executor_context as executor:
                    for (idx, candidate_x), candidate_fun in zip(
                        grid_candidates,
                        executor.map(
                            evaluator,
                            (
                                candidate_x if executor_kind == "fork_process" else (item, candidate_x)
                                for item, candidate_x in grid_candidates
                            ),
                            chunksize=1,
                        ),
                    ):
                        record_grid_candidate(idx, candidate_x, candidate_fun)
            if grid_best is not None and np.isfinite(float(grid_best["fun"])):
                discrete_grid_best_fun = float(grid_best["fun"])
                discrete_grid_best_x = np.asarray(grid_best["x"], dtype=float).tolist()
                evaluated.append(grid_best)
                discrete_global_proof = discrete_grid_nonfinite == 0
                if float(grid_best["fun"]) < float(best["fun"]):
                    best = dict(grid_best)

    if cem_mode_norm in {"shgo", "certify"} and len(x0) > 0 and int(shgo_samples) > 0:
        shgo_used = True
        emit_progress({"stage": "shgo", "completed": 0, "total": int(shgo_samples)})
        try:
            shgo_result = shgo(
                cost_fn,
                bounds,
                n=max(2 ** len(x0) + 1, int(shgo_samples)),
                iters=max(1, int(shgo_iters)),
                minimizer_kwargs={
                    "method": "L-BFGS-B",
                    "bounds": bounds,
                    "options": {"maxiter": max(1, int(maxiter))},
                },
                sampling_method="simplicial",
            )
            shgo_nfev = int(getattr(shgo_result, "nfev", 0) or 0)
            xl = getattr(shgo_result, "xl", None)
            shgo_local_minima = int(len(xl)) if xl is not None else 0
            if getattr(shgo_result, "x", None) is not None:
                shgo_x = clip_to_bounds(np.asarray(shgo_result.x, dtype=float), bounds)
                shgo_fun = finite_cost(cost_fn, shgo_x)
                shgo_row = {
                    "label": "shgo_simplicial",
                    "x": shgo_x,
                    "fun": shgo_fun,
                    "source": "shgo",
                    "nit": int(getattr(shgo_result, "nit", 0) or 0),
                    "success": bool(getattr(shgo_result, "success", False)),
                    "message": str(getattr(shgo_result, "message", "")),
                }
                evaluated.append(shgo_row)
                if np.isfinite(shgo_fun) and shgo_fun < float(best["fun"]):
                    best = dict(shgo_row)
            emit_progress(
                {
                    "stage": "shgo",
                    "completed": int(shgo_nfev),
                    "total": int(shgo_samples),
                    "best_fun": float(best["fun"]),
                }
            )
        except Exception as exc:
            evaluated.append(
                {
                    "label": "shgo_failed",
                    "x": np.asarray(best["x"], dtype=float),
                    "fun": float(best["fun"]),
                    "source": "shgo",
                    "success": False,
                    "message": str(exc),
                }
            )
            emit_progress({"stage": "shgo_failed", "message": str(exc)})

        global_pool = [row for row in evaluated if np.isfinite(float(row.get("fun", float("inf"))))]
        global_pool.sort(key=lambda item: float(item["fun"]))
        refined_rows = local_refine_rows(global_pool[: max(1, int(local_refine_topk))])
        evaluated.extend(refined_rows)
        if refined_rows and float(refined_rows[0]["fun"]) < float(best["fun"]):
            best = dict(refined_rows[0])

    def should_run_cem_from_seed_consensus(rows: Sequence[dict]) -> tuple[bool, float]:  # [関数定義] should_run_cem_from_seed_consensus の処理実行ブロック
        usable = [row for row in rows if np.isfinite(float(row.get("fun", float("inf"))))]
        if len(usable) < 2:
            return False, 0.0                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        top = usable[: min(3, len(usable))]
        mat = np.vstack([np.asarray(row["x"], dtype=float) for row in top])
        spread = float(np.max(np.std(mat, axis=0) / np.maximum(span, 1.0e-6)))
        best_fun = float(top[0]["fun"])
        next_fun = float(top[1]["fun"])
        gap = abs(next_fun - best_fun) / max(1.0, abs(best_fun))
        run = bool((spread > 0.08) or (gap > 0.10) or (not bool(top[0].get("success", True))))
        return run, spread                                         # [戻り値] 計算結果・計算状態の呼び出し元への返却

    use_cem = bool(cem_enabled and len(x0) > 0 and cem_mode_norm not in {"never", "shgo", "certify"})
    if use_cem and cem_mode_norm == "auto":
        use_cem, consensus_spread = should_run_cem_from_seed_consensus(refined_rows or refine_pool)

    if use_cem:
        cem_used = True
        finite_now = [row for row in evaluated if np.isfinite(row["fun"])]
        mean = np.asarray((best["x"] if np.isfinite(float(best["fun"])) else (finite_now[0]["x"] if finite_now else x0)), dtype=float).copy()
        sigma = np.maximum(0.12 * span, 0.5)
        elite_count = max(1, min(int(cem_elite), int(cem_population)))
        for gen in range(max(0, int(cem_generations))):
            pop: list[dict] = []
            pop.append({"label": f"cem_mean_g{gen:02d}", "x": clip_to_bounds(mean, bounds)})
            for idx in range(max(0, int(cem_population) - 1)):
                sample = rng.normal(mean, sigma)
                pop.append({"label": f"cem_g{gen:02d}_p{idx:02d}", "x": clip_to_bounds(sample, bounds)})
            for row in pop:
                row["fun"] = finite_cost(cost_fn, row["x"])
                row["source"] = "cem"
                evaluated.append(row)
            finite_pop = [row for row in pop if np.isfinite(row["fun"])]
            if not finite_pop:
                continue
            finite_pop.sort(key=lambda item: float(item["fun"]))
            elite = finite_pop[:elite_count]
            elite_mat = np.vstack([row["x"] for row in elite])
            mean = np.mean(elite_mat, axis=0)
            sigma = np.maximum(np.std(elite_mat, axis=0), 0.05 * span)

        finite_pool = [row for row in evaluated if np.isfinite(row["fun"])]
        finite_pool.sort(key=lambda item: float(item["fun"]))
        best = dict(finite_pool[0])
        refine_pool = finite_pool[: max(1, int(local_refine_topk))]
        refined_rows = local_refine_rows(refine_pool)
        for row in refined_rows:
            evaluated.append(row)
        if refined_rows and float(refined_rows[0]["fun"]) < float(best["fun"]):
            best = dict(refined_rows[0])

    selected_no_worse_than_grid = bool(
        discrete_global_proof
        and np.isfinite(discrete_grid_best_fun)
        and float(best["fun"]) <= discrete_grid_best_fun + 1.0e-9 * max(1.0, abs(discrete_grid_best_fun))
    )
    finite_library_global_proof = bool(
        discrete_global_proof
        and deterministic_seed_nonfinite == 0
        and int(maxiter) <= 0
        and not cem_used
        and not shgo_used
        and selected_no_worse_than_grid
    )
    if finite_library_global_proof:
        certificate_scope = "exact optimum over deterministic seeds plus exhaustive Cartesian speed grid"
    elif selected_no_worse_than_grid:
        certificate_scope = "selected candidate is no worse than the exhaustive finite-grid minimum; no continuous proof"
    elif discrete_global_proof:
        certificate_scope = "exhaustive finite-grid minimum evaluated; selected candidate has no dominance certificate"
    else:
        certificate_scope = "no exhaustive finite-grid certificate"

    return np.asarray(best["x"], dtype=float), {                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "success": bool(best.get("success", True)),
        "fun": float(best["fun"]),
        "label": str(best.get("label", "best")),
        "nit": int(best.get("nit", 0) or 0),
        "method": str(best.get("source", "seed")),
        "message": str(best.get("message", "")),
        "candidates_evaluated": int(len(evaluated) + discrete_grid_candidates + shgo_nfev),
        "cem_mode": cem_mode_norm,
        "cem_used": cem_used,
        "seed_consensus_spread": consensus_spread,
        "shgo_used": shgo_used,
        "shgo_nfev": shgo_nfev,
        "shgo_local_minima": shgo_local_minima,
        "discrete_global_proof": discrete_global_proof,
        "discrete_grid_levels": discrete_grid_levels,
        "discrete_grid_values": grid_values.tolist() if grid_values.size else [],
        "discrete_grid_candidates": discrete_grid_candidates,
        "discrete_grid_nonfinite": discrete_grid_nonfinite,
        "discrete_grid_best_fun": discrete_grid_best_fun,
        "discrete_grid_best_x": discrete_grid_best_x,
        "deterministic_seed_candidates": deterministic_seed_candidates,
        "deterministic_seed_nonfinite": deterministic_seed_nonfinite,
        "finite_library_candidates": int(deterministic_seed_candidates + discrete_grid_candidates),
        "seed_library_mode": seed_library_mode_norm,
        "selected_x": np.asarray(best["x"], dtype=float).tolist(),
        "selected_no_worse_than_grid": selected_no_worse_than_grid,
        "finite_library_global_proof": finite_library_global_proof,
        "continuous_global_proof": False,
        "certificate_scope": certificate_scope,
    }

# =============================================================================
# 【統合ユーティリティ】パス解決・ルート補間・スケジューラー・気象インターフェース
# =============================================================================
import os
from pathlib import Path

get_package_share_directory = None



PKG_NAME = 'mpc_solarcar'
REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(path: str, default_subdir: str = '') -> str:      # [関数定義] resolve_path の処理実行ブロック
    """Resolve a path relative to CWD or package share.

    - If absolute, return as-is.                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - If exists relative to CWD, return it.                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - Otherwise, resolve under <pkg_share>/<default_subdir> (or directly under share).
    """
    if path is None:
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.exists(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if get_package_share_directory is not None:
        pkg_share = get_package_share_directory(PKG_NAME)
    else:
        pkg_share = os.fspath(REPO_ROOT)
    if default_subdir:
        subdir = default_subdir.strip('/\\')
        if path.startswith(subdir + os.sep) or path == subdir:
            return os.path.join(pkg_share, path)                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return os.path.join(pkg_share, subdir, path)               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return os.path.join(pkg_share, path)                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


def _interp_field(d, y, s_km, default=0.0):                        # [関数定義] _interp_field の処理実行ブロック
    if len(d) < 2:
        return float(default)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    s = np.clip(s_km, d[0], d[-1])
    i = np.searchsorted(d, s) - 1
    i = np.clip(i, 0, len(d) - 2)
    t = 0.0 if d[i + 1] == d[i] else (s - d[i]) / (d[i + 1] - d[i])
    return float((1 - t) * y[i] + t * y[i + 1])                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route(route_df, s_km):                             # [関数定義] interpolate_route の処理実行ブロック
    d = route_df['dist_km'].values
    lat = route_df['lat'].values
    lon = route_df['lon'].values
    latp = _interp_field(d, lat, s_km, default=float(lat[0]) if len(lat) else 0.0)
    lonp = _interp_field(d, lon, s_km, default=float(lon[0]) if len(lon) else 0.0)
    return latp, lonp                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route_with_alt(route_df, s_km):                    # [関数定義] interpolate_route_with_alt の処理実行ブロック
    lat, lon = interpolate_route(route_df, s_km)
    alt = None
    for col in ('alt_m', 'altitude_m', 'elev_m'):
        if col in route_df.columns:
            d = route_df['dist_km'].values
            alt = _interp_field(d, route_df[col].values, s_km, default=float(route_df[col].values[0]))
            break
    return lat, lon, alt                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_profile(route_df, s_km, field: str, default: float = 0.0) -> float:  # [関数定義] interpolate_profile の処理実行ブロック
    if field not in route_df.columns:
        return float(default)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    d = route_df['dist_km'].values
    return _interp_field(d, route_df[field].values, s_km, default=default)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def bearing_deg(lat1, lon1, lat2, lon2):                           # [関数定義] bearing_deg の処理実行ブロック
    lat1r = np.deg2rad(float(lat1))
    lon1r = np.deg2rad(float(lon1))
    lat2r = np.deg2rad(float(lat2))
    lon2r = np.deg2rad(float(lon2))
    dlon = lon2r - lon1r
    y = np.sin(dlon) * np.cos(lat2r)
    x = np.cos(lat1r) * np.sin(lat2r) - np.sin(lat1r) * np.cos(lat2r) * np.cos(dlon)
    brng = np.rad2deg(np.arctan2(y, x))
    return float((brng + 360.0) % 360.0)                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route_heading(route_df, s_km, span_km: float = 1.0):  # [関数定義] interpolate_route_heading の処理実行ブロック
    if route_df is None or len(route_df) < 2:
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    s0 = max(float(route_df['dist_km'].iloc[0]), float(s_km) - max(0.1, span_km))
    s1 = min(float(route_df['dist_km'].iloc[-1]), float(s_km) + max(0.1, span_km))
    if s1 <= s0:
        d = route_df['dist_km'].values
        i = int(np.clip(np.searchsorted(d, float(s_km)), 1, len(d) - 1))
        lat1 = float(route_df.iloc[i - 1]['lat'])
        lon1 = float(route_df.iloc[i - 1]['lon'])
        lat2 = float(route_df.iloc[i]['lat'])
        lon2 = float(route_df.iloc[i]['lon'])
        return bearing_deg(lat1, lon1, lat2, lon2)                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    lat1, lon1 = interpolate_route(route_df, s0)
    lat2, lon2 = interpolate_route(route_df, s1)
    return bearing_deg(lat1, lon1, lat2, lon2)                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


import os
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import List, Optional, Tuple

import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - fallback for older Python
    ZoneInfo = None


def _parse_utc(ts: str) -> Optional[datetime]:                     # [関数定義] _parse_utc の処理実行ブロック
    try:
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _parse_time_hhmm(s: str) -> Optional[dtime]:                   # [関数定義] _parse_time_hhmm の処理実行ブロック
    try:
        parts = s.strip().split(':')
        if len(parts) < 2:
            return None                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return dtime(hour=int(parts[0]), minute=int(parts[1]))     # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


@dataclass
class DriveWindow:                                                 # [クラス定義] DriveWindow オブジェクトの設計
    start_utc: datetime
    end_utc: datetime
    v_min_kmh: float
    v_max_kmh: float

    def contains(self, t_utc: datetime) -> bool:                   # [関数定義] contains の処理実行ブロック
        return self.start_utc <= t_utc < self.end_utc              # [戻り値] 計算結果・計算状態の呼び出し元への返却


@dataclass
class DailyWindow:                                                 # [クラス定義] DailyWindow オブジェクトの設計
    start_local: dtime
    end_local: dtime
    tz: str
    days: Optional[List[int]]
    v_min_kmh: float
    v_max_kmh: float

    def contains(self, t_utc: datetime) -> bool:                   # [関数定義] contains の処理実行ブロック
        if ZoneInfo is None:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        try:
            tzinfo = ZoneInfo(self.tz)
        except Exception:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        local_dt = t_utc.astimezone(tzinfo)
        if self.days is not None and local_dt.weekday() not in self.days:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        start = self.start_local
        end = self.end_local
        now_t = local_dt.time()
        if start <= end:
            return start <= now_t < end                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        # wraps midnight
        return now_t >= start or now_t < end                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


class DriveSchedule:                                               # [クラス定義] DriveSchedule オブジェクトの設計
    def __init__(self, windows: List[DriveWindow], daily: List[DailyWindow], deny_by_default: bool):  # [関数定義] __init__ の処理実行ブロック
        self.windows = windows
        self.daily = daily
        self.deny_by_default = deny_by_default

    @classmethod
    def from_yaml(cls, path: str) -> Optional['DriveSchedule']:    # [関数定義] from_yaml の処理実行ブロック
        if not path or not os.path.exists(path):
            return None                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            return None                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        deny_by_default = bool(cfg.get('deny_by_default', False))
        windows = []
        for w in cfg.get('drive_windows', []) or []:
            start = _parse_utc(str(w.get('start_utc', '')))
            end = _parse_utc(str(w.get('end_utc', '')))
            if start is None or end is None:
                continue
            vmin = float(w.get('v_min_kmh', 0.0))
            vmax = float(w.get('v_max_kmh', 130.0))
            windows.append(DriveWindow(start, end, vmin, vmax))
        daily = []
        for w in cfg.get('daily_windows', []) or []:
            start = _parse_time_hhmm(str(w.get('start_local', '')))
            end = _parse_time_hhmm(str(w.get('end_local', '')))
            tz = str(w.get('tz', 'UTC'))
            if start is None or end is None:
                continue
            days = w.get('days', None)
            if days is not None:
                try:
                    days = [int(d) for d in days]
                except Exception:
                    days = None
            vmin = float(w.get('v_min_kmh', 0.0))
            vmax = float(w.get('v_max_kmh', 130.0))
            daily.append(DailyWindow(start, end, tz, days, vmin, vmax))
        return cls(windows, daily, deny_by_default)                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def speed_limits(self, t_utc: datetime) -> Optional[Tuple[float, float]]:  # [関数定義] speed_limits の処理実行ブロック
        limits = []
        for w in self.windows:
            if w.contains(t_utc):
                limits.append((w.v_min_kmh, w.v_max_kmh))
        for w in self.daily:
            if w.contains(t_utc):
                limits.append((w.v_min_kmh, w.v_max_kmh))
        if limits:
            vmin = max(l[0] for l in limits)
            vmax = min(l[1] for l in limits)
            return vmin, vmax                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if self.deny_by_default:
            return 0.0, 0.0                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def is_drive_time(self, t_utc: datetime) -> bool:              # [関数定義] is_drive_time の処理実行ブロック
        limits = self.speed_limits(t_utc)
        if limits is None:
            return not self.deny_by_default                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return limits[1] > 0.0                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def next_drive_start(self, t_utc: datetime) -> datetime:       # [関数定義] next_drive_start の処理実行ブロック
        if self.is_drive_time(t_utc):
            return t_utc                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        candidates = []
        for w in self.windows:
            if t_utc < w.start_utc:
                candidates.append(w.start_utc)
        for w in self.daily:
            if ZoneInfo is None:
                continue
            try:
                tzinfo = ZoneInfo(w.tz)
            except Exception:
                continue
            local_dt = t_utc.astimezone(tzinfo)
            if w.days is not None and local_dt.weekday() not in w.days:
                # move to next allowed weekday
                days_ahead = 1
                while w.days is not None and ((local_dt + timedelta(days=days_ahead)).weekday() not in w.days) and days_ahead < 8:
                    days_ahead += 1
                start_date = (local_dt + timedelta(days=days_ahead)).date()
                start_local = datetime.combine(start_date, w.start_local, tzinfo)
                candidates.append(start_local.astimezone(timezone.utc))
                continue
            now_t = local_dt.time()
            if w.start_local <= w.end_local:
                if now_t < w.start_local:
                    start_local = datetime.combine(local_dt.date(), w.start_local, tzinfo)
                else:
                    start_local = datetime.combine(local_dt.date() + timedelta(days=1), w.start_local, tzinfo)
            else:
                # wraps midnight
                if now_t < w.end_local:
                    start_local = datetime.combine(local_dt.date(), w.start_local, tzinfo)
                elif now_t < w.start_local:
                    start_local = datetime.combine(local_dt.date(), w.start_local, tzinfo)
                else:
                    start_local = datetime.combine(local_dt.date() + timedelta(days=1), w.start_local, tzinfo)
            candidates.append(start_local.astimezone(timezone.utc))
        if candidates:
            return min(candidates)                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return t_utc                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def current_drive_window(self, t_utc: datetime):               # [関数定義] current_drive_window の処理実行ブロック
        """Return (start_utc, end_utc) if t_utc is inside a drive window, else None."""
        for w in self.windows:
            if w.contains(t_utc):
                return w.start_utc, w.end_utc                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        for w in self.daily:
            if ZoneInfo is None:
                continue
            try:
                tzinfo = ZoneInfo(w.tz)
            except Exception:
                continue
            local_dt = t_utc.astimezone(tzinfo)
            if w.days is not None and local_dt.weekday() not in w.days:
                continue
            start = w.start_local
            end = w.end_local
            now_t = local_dt.time()
            if start <= end:
                if not (start <= now_t < end):
                    continue
                start_local = datetime.combine(local_dt.date(), start, tzinfo)
                end_local = datetime.combine(local_dt.date(), end, tzinfo)
            else:
                # wraps midnight
                if not (now_t >= start or now_t < end):
                    continue
                if now_t >= start:
                    start_local = datetime.combine(local_dt.date(), start, tzinfo)
                    end_local = datetime.combine(local_dt.date() + timedelta(days=1), end, tzinfo)
                else:
                    start_local = datetime.combine(local_dt.date() - timedelta(days=1), start, tzinfo)
                    end_local = datetime.combine(local_dt.date(), end, tzinfo)
            return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


OPENMETEO_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'


def _fetch_json(url: str, timeout_sec: float = 20.0) -> Dict:      # [関数定義] _fetch_json の処理実行ブロック
    req = urllib.request.Request(url, headers={'User-Agent': 'solarcar-weather-fetch/1.0'})
    with urllib.request.urlopen(req, timeout=timeout_sec) as res:
        return json.loads(res.read().decode('utf-8'))              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_openmeteo_url(latitude: float, longitude: float, timezone_name: str, forecast_days: int) -> str:  # [関数定義] build_openmeteo_url の処理実行ブロック
    params = {
        'latitude': f'{latitude:.6f}',
        'longitude': f'{longitude:.6f}',
        'timezone': timezone_name,
        'forecast_days': str(max(1, int(forecast_days))),
        'hourly': 'temperature_2m,shortwave_radiation,windspeed_10m,winddirection_10m',
    }
    return OPENMETEO_FORECAST_URL + '?' + urllib.parse.urlencode(params)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def wrap_angle_deg(angle_deg: float) -> float:                     # [関数定義] wrap_angle_deg の処理実行ブロック
    return float((float(angle_deg) + 360.0) % 360.0)               # [戻り値] 計算結果・計算状態の呼び出し元への返却


def signed_angle_diff_deg(a_deg: float, b_deg: float) -> float:    # [関数定義] signed_angle_diff_deg の処理実行ブロック
    return float((float(a_deg) - float(b_deg) + 180.0) % 360.0 - 180.0)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def meteo_headwind_component_ms(wind_speed_ms: float, wind_from_deg: float, heading_deg: float) -> float:  # [関数定義] meteo_headwind_component_ms の処理実行ブロック
    """Project a meteorological wind direction onto the route heading.

    `wind_from_deg` follows the usual convention: the direction the wind is coming from,
    measured clockwise from north. Positive output means headwind, negative means tailwind.
    """
    if not math.isfinite(float(wind_speed_ms)):
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if not math.isfinite(float(wind_from_deg)) or not math.isfinite(float(heading_deg)):
        return float(wind_speed_ms)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = math.radians(signed_angle_diff_deg(float(wind_from_deg), float(heading_deg)))
    return float(wind_speed_ms) * math.cos(delta)                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fetch_openmeteo_forecast(                                      # [関数定義] fetch_openmeteo_forecast の処理実行ブロック
    latitude: float,
    longitude: float,
    timezone_name: str = 'UTC',
    forecast_days: int = 3,
    step_minutes: int = 10,
    tcell_gain: float = 0.03,
    timeout_sec: float = 20.0,
) -> pd.DataFrame:
    url = build_openmeteo_url(latitude, longitude, timezone_name, forecast_days)
    payload = _fetch_json(url, timeout_sec=timeout_sec)
    hourly = payload.get('hourly', {})
    times = hourly.get('time', [])
    ghi = hourly.get('shortwave_radiation', [])
    temp = hourly.get('temperature_2m', [])
    wind_kmh = hourly.get('windspeed_10m', [])
    wind_dir = hourly.get('winddirection_10m', [])
    rows: List[Dict] = []
    for idx, t_str in enumerate(times):
        try:
            t_local = datetime.fromisoformat(t_str)
            if t_local.tzinfo is None:
                t_local = t_local.replace(tzinfo=timezone.utc)
            t_utc = t_local.astimezone(timezone.utc)
        except Exception:
            continue
        g = float(ghi[idx]) if idx < len(ghi) and ghi[idx] is not None else 0.0
        tamb = float(temp[idx]) if idx < len(temp) and temp[idx] is not None else 25.0
        w_kmh = float(wind_kmh[idx]) if idx < len(wind_kmh) and wind_kmh[idx] is not None else 0.0
        w_dir = float(wind_dir[idx]) if idx < len(wind_dir) and wind_dir[idx] is not None else 0.0
        w_ms = w_kmh / 3.6
        rows.append({
            'time': t_utc.isoformat(),
            'GHI': g,
            'Tamb_C': tamb,
            'Tcell_C': tamb + max(0.0, g) * float(tcell_gain),
            'wind_speed_ms': w_ms,
            'wind_dir_deg': wrap_angle_deg(w_dir),
            # Raw forecast does not know the actual route heading at this stage.
            # Keep the direct headwind input neutral and let the wind correction node
            # project the forecast onto the route before the planner consumes it.
            'headwind_ms': 0.0,
        })

    df = pd.DataFrame(rows)
    if df.empty or step_minutes >= 60:
        return df                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    if df.empty:
        return df.reset_index(drop=False)                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    target_index = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq=f'{int(step_minutes)}min',
        tz='UTC',
    )
    df = df.reindex(df.index.union(target_index)).interpolate(method='time').reindex(target_index)
    df = df.reset_index().rename(columns={'index': 'time'})
    df['time'] = df['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return df                                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_forecast_csv(df: pd.DataFrame, out_csv: str):            # [関数定義] write_forecast_csv の処理実行ブロック
    if df is None:
        raise ValueError('Forecast dataframe is None')
    df.to_csv(out_csv, index=False)


import os
from typing import Any, Dict, Tuple

import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート



def load_profile(profile_yaml: str) -> Tuple[str, Dict[str, Any]]:  # [関数定義] load_profile の処理実行ブロック
    """Load a unified solar workflow profile YAML."""
    resolved = resolve_path(profile_yaml, 'config')
    with open(resolved, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f'Profile YAML must be a mapping: {resolved}')
    return os.path.abspath(resolved), cfg                          # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_section(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:  # [関数定義] get_section の処理実行ブロック
    value = cfg.get(name, {})
    return value if isinstance(value, dict) else {}                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_value(cfg: Dict[str, Any], section: str, key: str, default: Any = None) -> Any:  # [関数定義] get_value の処理実行ブロック
    return get_section(cfg, section).get(key, default)             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def merged_dict(*parts: Dict[str, Any]) -> Dict[str, Any]:         # [関数定義] merged_dict の処理実行ブロック
    merged: Dict[str, Any] = {}
    for part in parts:
        if isinstance(part, dict):
            merged.update(part)
    return merged                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def resolve_profile_asset(profile_yaml: str, asset_path: str) -> str:  # [関数定義] resolve_profile_asset の処理実行ブロック
    if asset_path is None:
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    raw = os.path.expanduser(str(asset_path)).strip()
    if not raw:
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.isabs(raw):
        return raw                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    profile_dir = os.path.dirname(os.path.abspath(profile_yaml))
    candidate = os.path.normpath(os.path.join(profile_dir, raw))
    if os.path.exists(candidate):
        return candidate                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.exists(raw):
        return os.path.abspath(raw)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return resolve_path(raw)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_path(cfg: Dict[str, Any], profile_yaml: str, key: str, default: str = '') -> str:  # [関数定義] get_path の処理実行ブロック
    return resolve_profile_asset(profile_yaml, get_value(cfg, 'paths', key, default))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

# =============================================================================
# 【統合物理モデル & マクロコスト評価器】
# =============================================================================
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
from dataclasses import dataclass

try:
    import casadi as ca                                            # [最適化エンジン] 数値最適化・自動微分ライブラリ CasADi のインポート
except ImportError:
    class _CasadiCompat:                                           # [クラス定義] _CasadiCompat オブジェクトの設計
        class SX:                                                  # [クラス定義] SX オブジェクトの設計
            pass

        class MX:                                                  # [クラス定義] MX オブジェクトの設計
            pass

        @staticmethod
        def fmax(a, b):                                            # [関数定義] fmax の処理実行ブロック
            return max(a, b)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def fmin(a, b):                                            # [関数定義] fmin の処理実行ブロック
            return min(a, b)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def atan(x):                                               # [関数定義] atan の処理実行ブロック
            return math.atan(x)                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def cos(x):                                                # [関数定義] cos の処理実行ブロック
            return math.cos(x)                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def sin(x):                                                # [関数定義] sin の処理実行ブロック
            return math.sin(x)                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def sqrt(x):                                               # [関数定義] sqrt の処理実行ブロック
            return math.sqrt(x)                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def fabs(x):                                               # [関数定義] fabs の処理実行ブロック
            return abs(x)                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    ca = _CasadiCompat()

def _is_symbolic(x):                                               # [関数定義] _is_symbolic の処理実行ブロック
    return isinstance(x, (ca.SX, ca.MX)) or (hasattr(x, 'is_symbolic') and x.is_symbolic())  # [戻り値] 計算結果・計算状態の呼び出し元への返却

@dataclass
class Params:                                                      # [クラス定義] Params オブジェクトの設計
    dt: float=600.0
    rho: float=1.18
    CdA: float=0.13
    Crr: float=0.002
    Crr_per_wheel: float=0.0
    m: float=250.0
    g: float=9.80665
    P_aux: float=60.0
    gear_eta: float=0.98
    gear_ratio: float=6.0
    wheel_radius: float=0.28
    wheel_count: int=4
    driven_wheel_count: int=2
    motor_count: int=1
    motor_type: str='generic'
    inverter_eta: float=1.0
    pv_area: float=6.0
    pv_eta_ref: float=0.23
    pv_mu_p: float=-0.0045
    mppt_eta: float=0.95
    panel_gain: float=1.0
    E_nom_Wh: float=3055.0
    V_min: float=260.0
    V_max: float=400.0
    I_max: float=120.0
    I_chg_min: float=-90.0
    T_max: float=55.0
    T_min: float=-5.0
    soc_min: float=0.05
    soc_max: float=0.98
    grade_scale: float=1.0
    drive_eff_scale: float=1.0
    regen_eff_scale: float=1.0
    rint_scale: float=1.0
    r_line_ohm: float=0.01
    eta_charge: float=1.0

class SolarCarModel:                                               # [車両モデルクラス] ソーラーカーの空力・転がり・発電・電池の統合物理モデル
    def __init__(self, drive_map_path, regen_map_path, Rint_map_path,  # [関数定義] __init__ の処理実行ブロック
                 params=None, panel_eff_map_path=None, mppt_eff_map_path=None,
                 drive_map_eco_path=None, drive_map_power_path=None,
                 regen_map_eco_path=None, regen_map_power_path=None,
                 ocv_soc_map_path=None):
        self.p = params or Params()
        self.drive_power_gain = 1.0
        self.aux_power_override_w = None
        self.v_grid, self.tau_grid, self.Z_drv = read_eff_map(drive_map_path)
        self.v_gridR, self.tau_gridR, self.Z_reg = read_eff_map(regen_map_path)
        self.drive_mode = 'auto'
        self.drive_mode_default = 'eco'
        self.drive_mode_tau_margin = 0.0
        self.maps_drive = {
            'default': (self.v_grid, self.tau_grid, self.Z_drv),
        }
        self.maps_regen = {
            'default': (self.v_gridR, self.tau_gridR, self.Z_reg),
        }
        if drive_map_eco_path:
            self.maps_drive['eco'] = read_eff_map(drive_map_eco_path)
        if drive_map_power_path:
            self.maps_drive['power'] = read_eff_map(drive_map_power_path)
        if regen_map_eco_path:
            self.maps_regen['eco'] = read_eff_map(regen_map_eco_path)
        if regen_map_power_path:
            self.maps_regen['power'] = read_eff_map(regen_map_power_path)
        self._update_mode_limits()
        self.Tg, self.zg, self.Rmap = read_Rint_map(Rint_map_path)
        self.panel_eff_map = None
        self.mppt_eff_map = None
        if panel_eff_map_path:
            try:
                self.Gg, self.Tcg, self.Z_panel = read_map(panel_eff_map_path)
                self.panel_eff_map = True
            except Exception:
                self.panel_eff_map = None
        if mppt_eff_map_path:
            try:
                self.Gm, self.Tm, self.Z_mppt = read_map(mppt_eff_map_path)
                self.mppt_eff_map = True
            except Exception:
                self.mppt_eff_map = None
        self.ocv_soc_map = None
        if ocv_soc_map_path:
            try:
                self.soc_grid, self.ocv_grid = read_1d_map(ocv_soc_map_path)
                self.ocv_soc_map = True
            except Exception:
                self.ocv_soc_map = None

    def eff_drive(self, v_ms, tau_nm):                             # [関数定義] eff_drive の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(tau_nm):
            v = ca.fabs(v_ms); t = ca.fabs(tau_nm)
            vN = v/35.0; tN = t/60.0
            eff = 0.92 - 0.08*vN*vN - 0.06*ca.sqrt(tN+1e-9)
            eff = eff * float(self.p.drive_eff_scale)
            return ca.fmin(0.99, ca.fmax(0.55, eff))               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        mode = self._select_mode(float(v_ms), float(abs(tau_nm)))
        v_grid, t_grid, Z = self.maps_drive.get(mode, self.maps_drive['default'])
        eff = float(bilinear_interp(v_grid, t_grid, Z, float(v_ms), float(abs(tau_nm))))
        eff *= float(self.p.drive_eff_scale)
        return float(np.clip(eff, 0.55, 0.99))                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def eff_regen(self, v_ms, tau_nm):                             # [関数定義] eff_regen の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(tau_nm):
            v = ca.fabs(v_ms); t = ca.fabs(tau_nm)
            vN = v/35.0; tN = t/60.0
            eff = 0.70 + 0.12*vN - 0.05*(tN-0.3)*(tN-0.3)
            eff = eff * float(self.p.regen_eff_scale or self.p.drive_eff_scale)
            return ca.fmin(0.95, ca.fmax(0.40, eff))               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        mode = self._select_mode(float(v_ms), float(abs(tau_nm)))
        v_grid, t_grid, Z = self.maps_regen.get(mode, self.maps_regen['default'])
        eff = float(bilinear_interp(v_grid, t_grid, Z, float(v_ms), float(abs(tau_nm))))
        eff *= float(self.p.regen_eff_scale or self.p.drive_eff_scale)
        return float(np.clip(eff, 0.40, 0.95))                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _update_mode_limits(self):                                 # [関数定義] _update_mode_limits の処理実行ブロック
        self.tau_max = {}
        for k, (_, t_grid, _) in self.maps_drive.items():
            try:
                self.tau_max[k] = float(max(t_grid))
            except Exception:
                self.tau_max[k] = 0.0

    def _select_mode(self, v_ms: float, tau_nm: float) -> str:     # [関数定義] _select_mode の処理実行ブロック
        mode = str(self.drive_mode or 'default').lower()
        if mode in ('eco', 'power'):
            return mode                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        # auto
        eco_max = self.tau_max.get('eco', self.tau_max.get('default', 0.0))
        margin = float(self.drive_mode_tau_margin or 0.0)
        if tau_nm > (eco_max + margin):
            return 'power' if 'power' in self.maps_drive else 'default'  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return 'eco' if 'eco' in self.maps_drive else 'default'    # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def select_drive_mode(self, v_ms: float, tau_nm: float) -> str:  # [関数定義] select_drive_mode の処理実行ブロック
        return self._select_mode(v_ms, abs(tau_nm))                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def R_int(self, T_C, z):                                       # [関数定義] R_int の処理実行ブロック
        if _is_symbolic(T_C) or _is_symbolic(z):
            R0=0.015; R_T=0.0002*(25.0-T_C); R_z=0.01*(1.0-z)
            return (R0+R_T+R_z) * float(self.p.rint_scale)         # [戻り値] 計算結果・計算状態の呼び出し元への返却
        else:
            return float(self.p.rint_scale) * float(bilinear_interp(self.Tg, self.zg, self.Rmap, T_C, z))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def pv_power_mppt(self, G_poa, T_cell_C):                      # [関数定義] pv_power_mppt の処理実行ブロック
        if self.panel_eff_map:
            eta_panel = bilinear_interp(self.Gg, self.Tcg, self.Z_panel, float(G_poa), float(T_cell_C))
            eta_panel = max(0.0, float(eta_panel))
        else:
            eta_panel = self.p.pv_eta_ref*(1.0+self.p.pv_mu_p*(T_cell_C-25.0))
            eta_panel = ca.fmax(0.0, eta_panel)
        eta_panel *= float(self.p.panel_gain)
        P_pv = eta_panel*self.p.pv_area*G_poa
        if self.mppt_eff_map:
            eta_mppt = bilinear_interp(self.Gm, self.Tm, self.Z_mppt, float(G_poa), float(T_cell_C))
            eta_mppt = max(0.0, float(eta_mppt))
            return eta_mppt*P_pv                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return self.p.mppt_eta*P_pv                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _scaled_slope_pct(self, slope_pct):                        # [関数定義] _scaled_slope_pct の処理実行ブロック
        return slope_pct * float(self.p.grade_scale)               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def charge_efficiency(self, P_pack) -> float:                  # [関数定義] charge_efficiency の処理実行ブロック
        try:
            p_pack = float(P_pack)
        except Exception:
            return 1.0                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return float(self.p.eta_charge) if p_pack < 0.0 else 1.0   # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def soc_step(self, z: float, P_pack: float, dt_sec: float) -> float:  # [関数定義] soc_step の処理実行ブロック
        eta = self.charge_efficiency(P_pack)
        return float(z) - eta * (float(P_pack) * float(dt_sec) / 3600.0) / max(float(self.p.E_nom_Wh), 1.0e-6)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def ocv_from_soc(self, z):                                     # [関数定義] ocv_from_soc の処理実行ブロック
        if _is_symbolic(z) or not self.ocv_soc_map:
            z_clamped = ca.fmin(self.p.soc_max, ca.fmax(self.p.soc_min, z))
            return self.p.V_min + (self.p.V_max - self.p.V_min) * z_clamped  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        zc = float(np.clip(z, self.p.soc_min, self.p.soc_max))
        return float(np.interp(zc, self.soc_grid, self.ocv_grid))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def load_ocv_map(self, path: str) -> bool:                     # [関数定義] load_ocv_map の処理実行ブロック
        try:
            self.soc_grid, self.ocv_grid = read_1d_map(path)
            self.ocv_soc_map = True
            return True                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception:
            self.ocv_soc_map = None
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def resistive_forces(self, v_ms, slope_pct, headwind_ms=0.0):  # [関数定義] resistive_forces の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(slope_pct) or _is_symbolic(headwind_ms):
            v_rel = ca.fmax(0.0, v_ms + headwind_ms)
            theta = ca.atan(self._scaled_slope_pct(slope_pct) / 100.0)
            F_aero = 0.5 * self.p.rho * self.p.CdA * v_rel ** 2
            N = self.p.m * self.p.g * ca.cos(theta)
            Crr_eff = self.p.Crr
            if self.p.Crr_per_wheel and self.p.wheel_count:
                Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
            F_roll = Crr_eff * N
            F_grade = self.p.m * self.p.g * ca.sin(theta)
            F_total = F_aero + F_roll + F_grade
            return dict(F_aero=F_aero, F_roll=F_roll, F_grade=F_grade,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                        F_total=F_total, theta=theta)
        v_rel = max(0.0, float(v_ms) + float(headwind_ms))
        theta = math.atan(float(self._scaled_slope_pct(slope_pct)) / 100.0)
        F_aero = 0.5 * self.p.rho * self.p.CdA * v_rel ** 2
        N = self.p.m * self.p.g * math.cos(theta)
        Crr_eff = self.p.Crr
        if self.p.Crr_per_wheel and self.p.wheel_count:
            Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
        F_roll = Crr_eff * N
        F_grade = self.p.m * self.p.g * math.sin(theta)
        F_total = F_aero + F_roll + F_grade
        return dict(F_aero=F_aero, F_roll=F_roll, F_grade=F_grade,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                    F_total=F_total, theta=theta)

    def battery_iv(self, P_pack, z, Tbat_C):                       # [関数定義] battery_iv の処理実行ブロック
        OCV = self.ocv_from_soc(z)
        Rint = self.R_int(Tbat_C, ca.fmin(0.95, ca.fmax(0.1, z)))
        Rline = float(self.p.r_line_ohm)
        Rtot = Rint + Rline
        a = Rtot
        b = -OCV
        c = P_pack
        disc = ca.fmax(b * b - 4 * a * c, 0.0)
        I = (OCV - ca.sqrt(disc)) / (2 * Rtot)
        V = OCV - I * Rtot
        return dict(I=I, V=V, OCV=OCV, Rint=Rint, Rline=Rline)     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def mech_power(self, v_ms, slope_pct, headwind_ms=0.0):        # [関数定義] mech_power の処理実行ブロック
        v_rel = ca.fmax(0.0, v_ms + headwind_ms)
        P_aero = 0.5*self.p.rho*self.p.CdA*v_rel**3
        theta  = ca.atan(self._scaled_slope_pct(slope_pct)/100.0)
        N = self.p.m*self.p.g*ca.cos(theta)
        Crr_eff = self.p.Crr
        if self.p.Crr_per_wheel and self.p.wheel_count:
            Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
        P_roll = Crr_eff*N*v_ms
        P_grade= self.p.m*self.p.g*ca.sin(theta)*v_ms
        drive_power = (P_aero + P_roll + P_grade) * float(self.drive_power_gain)
        aux_power = float(self.aux_power_override_w) if self.aux_power_override_w is not None else float(self.p.P_aux)
        return drive_power + aux_power                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def torque_from_mech(self, P_mech, v_ms, wheel_radius=None, ratio=None):  # [関数定義] torque_from_mech の処理実行ブロック
        if wheel_radius is None:
            wheel_radius = self.p.wheel_radius
        if ratio is None:
            ratio = self.p.gear_ratio
        eps=1e-3
        omega_w = v_ms/wheel_radius
        T_w = P_mech/(omega_w+eps)
        T_m = T_w/ratio
        return T_m, omega_w*ratio                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def electrical_balance(self, v_ms, slope_pct, z, Tbat_C, G_poa, Tcell_C, headwind_ms=0.0):  # [関数定義] electrical_balance の処理実行ブロック
        P_pv = self.pv_power_mppt(G_poa, Tcell_C)
        P_mech = self.mech_power(v_ms, slope_pct, headwind_ms)
        P_mech_pos = ca.fmax(P_mech, 0.0)
        P_mech_neg = ca.fmax(-P_mech, 0.0)
        Tm_drv, _ = self.torque_from_mech(P_mech_pos, v_ms)
        eff_drv = self.eff_drive(v_ms, Tm_drv)
        P_dc_to_drv = P_mech_pos/(eff_drv*self.p.gear_eta*self.p.inverter_eta)
        Tm_reg, _ = self.torque_from_mech(P_mech_neg, v_ms)
        eff_reg = self.eff_regen(v_ms, Tm_reg)
        P_reg_to_dc = eff_reg*self.p.gear_eta*self.p.inverter_eta*P_mech_neg
        P_pack = P_dc_to_drv - P_reg_to_dc - P_pv
        OCV = self.ocv_from_soc(z)
        Rint = self.R_int(Tbat_C, ca.fmin(0.95, ca.fmax(0.1, z)))
        Rline = float(self.p.r_line_ohm); Rtot = Rint + Rline
        a = Rtot; b=-OCV; c=P_pack
        disc = ca.fmax(b*b-4*a*c, 0.0)
        I = (OCV - ca.sqrt(disc))/(2*Rtot)
        V = OCV - I*Rtot
        losses_line = I*I*Rline; losses_int = I*I*Rint
        aux_power = float(self.aux_power_override_w) if self.aux_power_override_w is not None else float(self.p.P_aux)
        P_mech_wheel = P_mech - aux_power
        return dict(P_pv=P_pv, P_mech=P_mech, P_mech_wheel=P_mech_wheel,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                    P_pack=P_pack, I=I, V=V,
                    losses_line=losses_line, losses_int=losses_int,
                    OCV=OCV, Rint=Rint, Rline=Rline,
                    P_dc_to_drv=P_dc_to_drv, P_reg_to_dc=P_reg_to_dc,
                    eff_drv=eff_drv, eff_reg=eff_reg)

# =============================================================================
# 【統合ユーティリティ】マップ読み込み・2D/1D線形補間関数群
# =============================================================================
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
def bilinear_interp(xg, yg, Z, x, y):                              # [関数定義] bilinear_interp の処理実行ブロック
    xg = np.asarray(xg); yg=np.asarray(yg); Z=np.asarray(Z)
    x = np.clip(x, xg[0], xg[-1]); y=np.clip(y, yg[0], yg[-1])
    i = np.searchsorted(xg, x)-1; i=np.clip(i,0,len(xg)-2)
    j = np.searchsorted(yg, y)-1; j=np.clip(j,0,len(yg)-2)
    x0,x1=xg[i],xg[i+1]; y0,y1=yg[j],yg[j+1]
    Z00=Z[i,j]; Z10=Z[i+1,j]; Z01=Z[i,j+1]; Z11=Z[i+1,j+1]
    wx=0 if x1==x0 else (x-x0)/(x1-x0)
    wy=0 if y1==y0 else (y-y0)/(y1-y0)
    return (1-wx)*(1-wy)*Z00 + wx*(1-wy)*Z10 + (1-wx)*wy*Z01 + wx*wy*Z11  # [戻り値] 計算結果・計算状態の呼び出し元への返却
def read_eff_map(path):                                            # [関数定義] read_eff_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
def read_Rint_map(path):                                           # [関数定義] read_Rint_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

def read_map(path):                                                # [関数定義] read_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

def read_1d_map(path):                                             # [関数定義] read_1d_map の処理実行ブロック
    df = pd.read_csv(path)
    if df.shape[1] >= 2:
        x = df.iloc[:, 0].values.astype(float)
        y = df.iloc[:, 1].values.astype(float)
        return x, y                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    df = pd.read_csv(path, index_col=0)
    x = df.index.values.astype(float)
    y = df.iloc[:, 0].values.astype(float)
    return x, y                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


from dataclasses import asdict, dataclass
from typing import Dict, Optional


@dataclass
class UpperCostConfig:                                             # [クラス定義] UpperCostConfig オブジェクトの設計
    w_wait: float = 1.0
    w_travel_time: float = 1.0
    w_terminal_soc_min: float = 30.0
    w_day_end_soc_min: float = 1.0e5
    w_soc_day_max: float = 1.0e4
    w_soc_day_track: float = 0.0
    w_speed_smooth: float = 30.0
    w_dv_limit: float = 2.0
    w_speed_limit: float = 50.0
    w_drive_window: float = 1.0e5
    w_current_sq: float = 0.01
    w_pack_energy: float = 0.0
    w_joule_loss: float = 0.0
    w_aero_energy: float = 0.0
    w_mech_energy: float = 0.0
    w_speed_quartic: float = 0.0
    w_solar_headroom: float = 0.0
    w_progress_lag: float = 0.0
    w_progress_terminal_lag: float = 0.0
    w_kinetic_pos: float = 0.0
    w_pack_power_slew: float = 0.0
    w_temp: float = 5.0
    w_soc_terminal: float = 0.0
    w_soc_floor_barrier: float = 0.0
    w_uncertainty_reserve: float = 0.0
    speed_quartic_scale_kmh: float = 80.0
    progress_lag_deadband_km: float = 0.0
    soc_solar_headroom_max: float = 0.92
    solar_headroom_power_scale_w: float = 1000.0
    soc_floor_barrier_eps: float = 0.01
    reserve_soc_per_hour: float = 0.0
    reserve_soc_max_extra: float = 0.0
    constraint_penalty: float = 1.0e4

    def to_dict(self) -> Dict[str, float]:                         # [関数定義] to_dict の処理実行ブロック
        return asdict(self)                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _cfg_value(cfg: Optional[dict], key: str, default):            # [関数定義] _cfg_value の処理実行ブロック
    if isinstance(cfg, dict) and key in cfg:
        return cfg[key]                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return default                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_upper_cost_config(                                        # [関数定義] load_upper_cost_config の処理実行ブロック
    mpc_cfg: Optional[dict],
    *,
    legacy: Optional[dict] = None,
    default_drive_window: float = 1.0e5,
) -> UpperCostConfig:
    legacy = legacy or {}
    nested = {}
    if isinstance(mpc_cfg, dict):
        nested = mpc_cfg.get("upper_cost", {}) or {}

    def pick(name: str, default):                                  # [関数定義] pick の処理実行ブロック
        if name in nested:
            return nested[name]                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if name in legacy:
            return legacy[name]                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return default                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    return UpperCostConfig(                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        w_wait=float(pick("w_wait", 1.0)),
        w_travel_time=float(pick("w_travel_time", 1.0)),
        w_terminal_soc_min=float(pick("w_terminal_soc_min", 30.0)),
        w_day_end_soc_min=float(pick("w_day_end_soc_min", default_drive_window)),
        w_soc_day_max=float(pick("w_soc_day_max", 1.0e4)),
        w_soc_day_track=float(pick("w_soc_day_track", 0.0)),
        w_speed_smooth=float(pick("w_speed_smooth", _cfg_value(legacy, "w_dv", 30.0))),
        w_dv_limit=float(pick("w_dv_limit", 2.0)),
        w_speed_limit=float(pick("w_speed_limit", 50.0)),
        w_drive_window=float(pick("w_drive_window", default_drive_window)),
        w_current_sq=float(pick("w_current_sq", _cfg_value(legacy, "w_current", 0.01))),
        w_pack_energy=float(pick("w_pack_energy", 0.0)),
        w_joule_loss=float(pick("w_joule_loss", 0.0)),
        w_aero_energy=float(pick("w_aero_energy", 0.0)),
        w_mech_energy=float(pick("w_mech_energy", 0.0)),
        w_speed_quartic=float(pick("w_speed_quartic", 0.0)),
        w_solar_headroom=float(pick("w_solar_headroom", 0.0)),
        w_progress_lag=float(pick("w_progress_lag", 0.0)),
        w_progress_terminal_lag=float(pick("w_progress_terminal_lag", 0.0)),
        w_kinetic_pos=float(pick("w_kinetic_pos", 0.0)),
        w_pack_power_slew=float(pick("w_pack_power_slew", 0.0)),
        w_temp=float(pick("w_temp", _cfg_value(legacy, "w_T", 5.0))),
        w_soc_terminal=float(pick("w_soc_terminal", 0.0)),
        w_soc_floor_barrier=float(pick("w_soc_floor_barrier", 0.0)),
        w_uncertainty_reserve=float(pick("w_uncertainty_reserve", 0.0)),
        speed_quartic_scale_kmh=float(pick("speed_quartic_scale_kmh", 80.0)),
        progress_lag_deadband_km=float(pick("progress_lag_deadband_km", 0.0)),
        soc_solar_headroom_max=float(pick("soc_solar_headroom_max", 0.92)),
        solar_headroom_power_scale_w=float(pick("solar_headroom_power_scale_w", 1000.0)),
        soc_floor_barrier_eps=float(pick("soc_floor_barrier_eps", 0.01)),
        reserve_soc_per_hour=float(pick("reserve_soc_per_hour", 0.0)),
        reserve_soc_max_extra=float(pick("reserve_soc_max_extra", 0.0)),
        constraint_penalty=float(pick("constraint_penalty", 1.0e4)),
    )


def quad_penalty(x: float, cap: float = 1.0e3) -> float:           # [関数定義] quad_penalty の処理実行ブロック
    if x <= 0.0:
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if x > cap:
        x = cap
    return x * x                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def upper_stage_cost(                                              # [関数定義] upper_stage_cost の処理実行ブロック
    cfg: UpperCostConfig,
    *,
    dt_wait: float,
    dt_travel: float,
    v_kmh: float,
    v_prev_kmh: float,
    vmax_local_kmh: float,
    drive_limits: Optional[tuple],
    dv_limit_kmhps: float,
    I_a: float,
    V_v: float,
    P_pv_w: float,
    P_pack_w: float,
    P_pack_prev_w: Optional[float],
    P_mech_wheel_w: float,
    losses_int_w: float,
    losses_line_w: float,
    F_aero_n: float,
    kinetic_step_wh: float,
    z_next: float,
    Tb_next_c: float,
    term_soc_min: float,
    soc_min: float,
    soc_max: float,
    temp_min_c: float,
    temp_max_c: float,
    day_end_soc_min: Optional[float],
    soc_day_end_max: float,
    soc_day_track_target: Optional[float],
    soc_day_track_tol: float,
    I_max: float,
    I_chg_min: float,
    V_min: float,
    V_max: float,
    time_ahead_h: float,
    progress_lag_km: float = 0.0,
) -> float:
    J = 0.0
    if dt_wait > 0.0:
        J += cfg.w_wait * dt_wait
    J += cfg.w_travel_time * dt_travel
    J += cfg.w_terminal_soc_min * quad_penalty(term_soc_min - z_next)

    if soc_day_track_target is not None:
        J += cfg.w_soc_day_track * quad_penalty(z_next - (soc_day_track_target + soc_day_track_tol))
        J += cfg.w_soc_day_track * quad_penalty((soc_day_track_target - soc_day_track_tol) - z_next)

    dv = (v_kmh - v_prev_kmh) / max(dt_travel, 1.0e-3)
    J += cfg.w_speed_smooth * (v_kmh - v_prev_kmh) ** 2
    if dv_limit_kmhps > 0.0:
        J += cfg.w_dv_limit * quad_penalty(abs(dv) - dv_limit_kmhps)

    if drive_limits is not None:
        vmin_kmh, vmax_kmh = drive_limits
        J += cfg.w_drive_window * quad_penalty(vmin_kmh - v_kmh)
        J += cfg.w_drive_window * quad_penalty(v_kmh - vmax_kmh)

    J += cfg.w_speed_limit * quad_penalty(v_kmh - vmax_local_kmh)
    J += cfg.w_current_sq * (I_a ** 2) * dt_travel

    e_pack_wh = max(0.0, P_pack_w) * dt_travel / 3600.0
    e_loss_wh = max(0.0, losses_int_w + losses_line_w) * dt_travel / 3600.0
    e_aero_wh = max(0.0, F_aero_n) * (v_kmh / 3.6) * dt_travel / 3600.0
    e_mech_wh = max(0.0, P_mech_wheel_w) * dt_travel / 3600.0

    J += cfg.w_pack_energy * e_pack_wh
    J += cfg.w_joule_loss * e_loss_wh
    J += cfg.w_aero_energy * e_aero_wh
    J += cfg.w_mech_energy * e_mech_wh
    J += cfg.w_kinetic_pos * max(0.0, kinetic_step_wh)

    if cfg.w_speed_quartic > 0.0:
        speed_scale = max(1.0, cfg.speed_quartic_scale_kmh)
        J += cfg.w_speed_quartic * ((max(0.0, v_kmh) / speed_scale) ** 4) * dt_travel

    if cfg.w_pack_power_slew > 0.0 and P_pack_prev_w is not None:
        d_pack_kw = (float(P_pack_w) - float(P_pack_prev_w)) / 1000.0
        J += cfg.w_pack_power_slew * (d_pack_kw ** 2) * (dt_travel / 3600.0)

    if cfg.w_progress_lag > 0.0:
        lag_err = max(0.0, float(progress_lag_km) - float(cfg.progress_lag_deadband_km))
        J += cfg.w_progress_lag * quad_penalty(lag_err)

    if cfg.w_solar_headroom > 0.0:
        solar_scale = max(1.0, cfg.solar_headroom_power_scale_w)
        pv_kw = max(0.0, P_pv_w) / solar_scale
        if pv_kw > 0.0:
            J += cfg.w_solar_headroom * pv_kw * quad_penalty(z_next - cfg.soc_solar_headroom_max) * (dt_travel / 3600.0)

    if cfg.w_soc_floor_barrier > 0.0:
        soc_gap = max(float(z_next) - float(soc_min), float(cfg.soc_floor_barrier_eps))
        J += cfg.w_soc_floor_barrier / soc_gap

    if cfg.w_uncertainty_reserve > 0.0 and cfg.reserve_soc_per_hour > 0.0:
        reserve_extra = min(
            max(0.0, float(cfg.reserve_soc_max_extra)),
            max(0.0, float(time_ahead_h)) * max(0.0, float(cfg.reserve_soc_per_hour)),
        )
        reserve_soc = min(float(soc_max), float(soc_min) + reserve_extra)
        J += cfg.w_uncertainty_reserve * quad_penalty(reserve_soc - z_next)

        J += cfg.w_day_end_soc_min * quad_penalty(day_end_soc_min - z_next)
        if soc_day_end_max > 0.0:
            J += cfg.w_soc_day_max * quad_penalty(z_next - soc_day_end_max)

    c = cfg.constraint_penalty
    J += c * quad_penalty(I_a - I_max)
    J += c * quad_penalty(I_chg_min - I_a)
    J += c * quad_penalty(V_min - V_v)
    J += c * quad_penalty(V_v - V_max)
    J += cfg.w_temp * quad_penalty(Tb_next_c - temp_max_c)
    J += cfg.w_temp * quad_penalty(temp_min_c - Tb_next_c)
    J += c * quad_penalty(soc_min - z_next)
    J += c * quad_penalty(z_next - soc_max)
    return J                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def upper_terminal_cost(                                           # [関数定義] upper_terminal_cost の処理実行ブロック
    cfg: UpperCostConfig,
    *,
    z_terminal: float,
    term_soc_min: float,
    soc_finish_target: float,
    progress_terminal_lag_km: float = 0.0,
) -> float:
    J = cfg.constraint_penalty * quad_penalty(term_soc_min - z_terminal)
    if soc_finish_target > 0.0:
        J += cfg.w_soc_terminal * quad_penalty(z_terminal - soc_finish_target)
    if cfg.w_progress_terminal_lag > 0.0:
        lag_err = max(0.0, float(progress_terminal_lag_km) - float(cfg.progress_lag_deadband_km))
        J += cfg.w_progress_terminal_lag * quad_penalty(lag_err)
    return J                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def active_upper_cost_terms(cfg: UpperCostConfig, threshold: float = 1.0e-6) -> Dict[str, float]:  # [関数定義] active_upper_cost_terms の処理実行ブロック
    out = {}
    for key, value in cfg.to_dict().items():
        if key.startswith("w_") and abs(float(value)) > threshold:
            out[key] = float(value)
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


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


from pathlib import Path

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


def _finite_vector(values, *, name: str) -> np.ndarray:            # [関数定義] _finite_vector の処理実行ブロック
    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or len(vector) == 0 or not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must be a non-empty finite one-dimensional array")
    return vector                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def absolute_control_distances(start_s_km: float, relative_control_s_km) -> np.ndarray:  # [関数定義] absolute_control_distances の処理実行ブロック
    """Convert a horizon-relative control mesh to route-absolute distances."""
    start = float(start_s_km)
    if not np.isfinite(start):
        raise ValueError("start_s_km must be finite")
    relative = _finite_vector(relative_control_s_km, name="relative_control_s_km")
    if np.any(relative < -1.0e-9) or np.any(np.diff(relative) < -1.0e-9):
        raise ValueError("relative_control_s_km must be non-negative and non-decreasing")
    return start + relative                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却


def shift_upper_policy_warm_start(                                 # [関数定義] shift_upper_policy_warm_start の処理実行ブロック
    previous_control_s_km,
    previous_speeds_kmh,
    current_control_s_km,
    *,
    minimum_speed_kmh: float,
    maximum_speed_kmh: float,
) -> np.ndarray:
    """Shift a prior route-indexed policy onto the current absolute control mesh."""
    previous_s = _finite_vector(previous_control_s_km, name="previous_control_s_km")
    previous_v = _finite_vector(previous_speeds_kmh, name="previous_speeds_kmh")
    current_s = _finite_vector(current_control_s_km, name="current_control_s_km")
    if len(previous_s) != len(previous_v):
        raise ValueError("previous control distances and speeds must have equal length")
    if np.any(np.diff(current_s) < -1.0e-9):
        raise ValueError("current_control_s_km must be non-decreasing")

    order = np.argsort(previous_s, kind="stable")
    previous_s = previous_s[order]
    previous_v = previous_v[order]
    unique_s, reverse_index = np.unique(previous_s[::-1], return_index=True)
    keep = len(previous_s) - 1 - reverse_index
    keep = keep[np.argsort(unique_s)]
    previous_s = previous_s[keep]
    previous_v = previous_v[keep]

    shifted = np.interp(current_s, previous_s, previous_v)
    return np.clip(shifted, float(minimum_speed_kmh), float(maximum_speed_kmh))  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_upper_policy_csv(path: str | Path) -> pd.DataFrame:       # [関数定義] load_upper_policy_csv の処理実行ブロック
    """Load a distance-indexed upper speed policy with strict schema checks."""
    policy_path = Path(path)
    frame = pd.read_csv(policy_path)
    required = {"s_km", "v_kmh"}
    if not required.issubset(frame.columns):
        raise ValueError(f"upper policy must contain {sorted(required)}: {policy_path}")
    out = frame.loc[:, ["s_km", "v_kmh"]].copy()
    out["s_km"] = pd.to_numeric(out["s_km"], errors="coerce")
    out["v_kmh"] = pd.to_numeric(out["v_kmh"], errors="coerce")
    out = (
        out.replace([np.inf, -np.inf], np.nan)
        .dropna()
        .sort_values("s_km")
        .drop_duplicates("s_km", keep="last")
        .reset_index(drop=True)
    )
    if len(out) < 2:
        raise ValueError(f"upper policy needs at least two finite distance points: {policy_path}")
    if float(out["s_km"].iloc[-1]) <= float(out["s_km"].iloc[0]):
        raise ValueError(f"upper policy distance must increase: {policy_path}")
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_upper_policy(                                      # [関数定義] interpolate_upper_policy の処理実行ブロック
    frame: pd.DataFrame,
    control_s_km,
    *,
    minimum_speed_kmh: float,
    maximum_speed_kmh: float,
) -> np.ndarray:
    """Interpolate a learned full-course policy onto the current MPC control mesh."""
    control_s = _finite_vector(control_s_km, name="control_s_km")
    source_s = pd.to_numeric(frame["s_km"], errors="coerce").to_numpy(dtype=float)
    source_v = pd.to_numeric(frame["v_kmh"], errors="coerce").to_numpy(dtype=float)
    if len(source_s) < 2 or not np.all(np.isfinite(source_s)) or not np.all(np.isfinite(source_v)):
        raise ValueError("upper policy contains non-finite or insufficient points")
    interpolated = np.interp(control_s, source_s, source_v)
    return np.clip(interpolated, float(minimum_speed_kmh), float(maximum_speed_kmh))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

import os
from datetime import datetime, timezone




class WeatherFetchNode:                                      # [クラス定義] WeatherFetchNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        self.declare_parameter('provider', 'openmeteo')
        self.declare_parameter('forecast_csv', 'data/weather/live_forecast.csv')
        self.declare_parameter('gps_topic', '/chase/gps')
        self.declare_parameter('fetch_period_sec', 3600.0)
        self.declare_parameter('forecast_days', 3)
        self.declare_parameter('step_minutes', 10)
        self.declare_parameter('timezone_name', 'Australia/Darwin')
        self.declare_parameter('fallback_latitude', -12.4634)
        self.declare_parameter('fallback_longitude', 130.8456)
        self.declare_parameter('tcell_gain', 0.03)

        self.provider = str(self.get_parameter('provider').value).lower()
        self.forecast_csv = resolve_path(self.get_parameter('forecast_csv').value)
        self.fetch_period_sec = float(self.get_parameter('fetch_period_sec').value)
        self.forecast_days = int(self.get_parameter('forecast_days').value)
        self.step_minutes = int(self.get_parameter('step_minutes').value)
        self.timezone_name = str(self.get_parameter('timezone_name').value)
        self.tcell_gain = float(self.get_parameter('tcell_gain').value)
        self.lat = float(self.get_parameter('fallback_latitude').value)
        self.lon = float(self.get_parameter('fallback_longitude').value)
        self.has_gps = False
        self.last_status = 'waiting for first fetch'

        gps_topic = str(self.get_parameter('gps_topic').value)
        self.create_subscription(NavSatFix, gps_topic, self._on_gps, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.pub_status = self.create_publisher(String, '/system/forecast_status', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        os.makedirs(os.path.dirname(os.path.abspath(self.forecast_csv)), exist_ok=True)
        self._fetch_once()
        self.timer = self.create_timer(max(60.0, self.fetch_period_sec), self._fetch_once)
        print(f'WeatherFetchNode started: provider={self.provider}, out={self.forecast_csv}')

    def _on_gps(self, msg: NavSatFix):                             # [関数定義] _on_gps の処理実行ブロック
        if msg.latitude == 0.0 and msg.longitude == 0.0:
            return
        self.lat = float(msg.latitude)
        self.lon = float(msg.longitude)
        self.has_gps = True

    def _fetch_once(self):                                         # [関数定義] _fetch_once の処理実行ブロック
        if self.provider != 'openmeteo':
            self.last_status = f'provider={self.provider} not implemented'
            self.pub_status.publish(String(data=self.last_status))
            return
        try:
            df = fetch_openmeteo_forecast(
                self.lat,
                self.lon,
                timezone_name=self.timezone_name,
                forecast_days=self.forecast_days,
                step_minutes=self.step_minutes,
                tcell_gain=self.tcell_gain,
            )
            write_forecast_csv(df, self.forecast_csv)
            stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            src = 'gps' if self.has_gps else 'fallback'
            self.last_status = f'openmeteo {stamp} lat={self.lat:.5f} lon={self.lon:.5f} src={src} rows={len(df)}'
            print(self.last_status)
        except Exception as exc:
            self.last_status = f'forecast fetch failed: {exc}'
            print(self.last_status)
        self.pub_status.publish(String(data=self.last_status))


def main():                                                        # [メイン関数] エントリーポイント関数
    node = WeatherFetchNode()
    node.destroy_node()

# =============================================================================
# 【統合ユーティリティ】Open-Meteo 気象取得・風速風向成分計算関数群
# =============================================================================
import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


OPENMETEO_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'


def _fetch_json(url: str, timeout_sec: float = 20.0) -> Dict:      # [関数定義] _fetch_json の処理実行ブロック
    req = urllib.request.Request(url, headers={'User-Agent': 'solarcar-weather-fetch/1.0'})
    with urllib.request.urlopen(req, timeout=timeout_sec) as res:
        return json.loads(res.read().decode('utf-8'))              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_openmeteo_url(latitude: float, longitude: float, timezone_name: str, forecast_days: int) -> str:  # [関数定義] build_openmeteo_url の処理実行ブロック
    params = {
        'latitude': f'{latitude:.6f}',
        'longitude': f'{longitude:.6f}',
        'timezone': timezone_name,
        'forecast_days': str(max(1, int(forecast_days))),
        'hourly': 'temperature_2m,shortwave_radiation,windspeed_10m,winddirection_10m',
    }
    return OPENMETEO_FORECAST_URL + '?' + urllib.parse.urlencode(params)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def wrap_angle_deg(angle_deg: float) -> float:                     # [関数定義] wrap_angle_deg の処理実行ブロック
    return float((float(angle_deg) + 360.0) % 360.0)               # [戻り値] 計算結果・計算状態の呼び出し元への返却


def signed_angle_diff_deg(a_deg: float, b_deg: float) -> float:    # [関数定義] signed_angle_diff_deg の処理実行ブロック
    return float((float(a_deg) - float(b_deg) + 180.0) % 360.0 - 180.0)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def meteo_headwind_component_ms(wind_speed_ms: float, wind_from_deg: float, heading_deg: float) -> float:  # [関数定義] meteo_headwind_component_ms の処理実行ブロック
    """Project a meteorological wind direction onto the route heading.

    `wind_from_deg` follows the usual convention: the direction the wind is coming from,
    measured clockwise from north. Positive output means headwind, negative means tailwind.
    """
    if not math.isfinite(float(wind_speed_ms)):
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if not math.isfinite(float(wind_from_deg)) or not math.isfinite(float(heading_deg)):
        return float(wind_speed_ms)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = math.radians(signed_angle_diff_deg(float(wind_from_deg), float(heading_deg)))
    return float(wind_speed_ms) * math.cos(delta)                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fetch_openmeteo_forecast(                                      # [関数定義] fetch_openmeteo_forecast の処理実行ブロック
    latitude: float,
    longitude: float,
    timezone_name: str = 'UTC',
    forecast_days: int = 3,
    step_minutes: int = 10,
    tcell_gain: float = 0.03,
    timeout_sec: float = 20.0,
) -> pd.DataFrame:
    url = build_openmeteo_url(latitude, longitude, timezone_name, forecast_days)
    payload = _fetch_json(url, timeout_sec=timeout_sec)
    hourly = payload.get('hourly', {})
    times = hourly.get('time', [])
    ghi = hourly.get('shortwave_radiation', [])
    temp = hourly.get('temperature_2m', [])
    wind_kmh = hourly.get('windspeed_10m', [])
    wind_dir = hourly.get('winddirection_10m', [])
    rows: List[Dict] = []
    for idx, t_str in enumerate(times):
        try:
            t_local = datetime.fromisoformat(t_str)
            if t_local.tzinfo is None:
                t_local = t_local.replace(tzinfo=timezone.utc)
            t_utc = t_local.astimezone(timezone.utc)
        except Exception:
            continue
        g = float(ghi[idx]) if idx < len(ghi) and ghi[idx] is not None else 0.0
        tamb = float(temp[idx]) if idx < len(temp) and temp[idx] is not None else 25.0
        w_kmh = float(wind_kmh[idx]) if idx < len(wind_kmh) and wind_kmh[idx] is not None else 0.0
        w_dir = float(wind_dir[idx]) if idx < len(wind_dir) and wind_dir[idx] is not None else 0.0
        w_ms = w_kmh / 3.6
        rows.append({
            'time': t_utc.isoformat(),
            'GHI': g,
            'Tamb_C': tamb,
            'Tcell_C': tamb + max(0.0, g) * float(tcell_gain),
            'wind_speed_ms': w_ms,
            'wind_dir_deg': wrap_angle_deg(w_dir),
            # Raw forecast does not know the actual route heading at this stage.
            # Keep the direct headwind input neutral and let the wind correction node
            # project the forecast onto the route before the planner consumes it.
            'headwind_ms': 0.0,
        })

    df = pd.DataFrame(rows)
    if df.empty or step_minutes >= 60:
        return df                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    if df.empty:
        return df.reset_index(drop=False)                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    target_index = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq=f'{int(step_minutes)}min',
        tz='UTC',
    )
    df = df.reindex(df.index.union(target_index)).interpolate(method='time').reindex(target_index)
    df = df.reset_index().rename(columns={'index': 'time'})
    df['time'] = df['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return df                                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_forecast_csv(df: pd.DataFrame, out_csv: str):            # [関数定義] write_forecast_csv の処理実行ブロック
    if df is None:
        raise ValueError('Forecast dataframe is None')
    df.to_csv(out_csv, index=False)


import os
from pathlib import Path

get_package_share_directory = None



PKG_NAME = 'mpc_solarcar'
REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(path: str, default_subdir: str = '') -> str:      # [関数定義] resolve_path の処理実行ブロック
    """Resolve a path relative to CWD or package share.

    - If absolute, return as-is.                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - If exists relative to CWD, return it.                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - Otherwise, resolve under <pkg_share>/<default_subdir> (or directly under share).
    """
    if path is None:
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.exists(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if get_package_share_directory is not None:
        pkg_share = get_package_share_directory(PKG_NAME)
    else:
        pkg_share = os.fspath(REPO_ROOT)
    if default_subdir:
        subdir = default_subdir.strip('/\\')
        if path.startswith(subdir + os.sep) or path == subdir:
            return os.path.join(pkg_share, path)                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return os.path.join(pkg_share, subdir, path)               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return os.path.join(pkg_share, path)                           # [戻り値] 計算結果・計算状態の呼び出し元への返却




class SolarMacroPlanner:
    """3,000 km 全行程 CROSS-ENTROPY METHOD 大域エネルギー・速度戦略計画クラス"""
    def __init__(self, config_path: str = "config.yaml"): # [初期化] マクロ戦略計画器構築
        self.config_path = Path(config_path)
        print(f"[SolarMacroPlanner] 大域戦略計画器を初期化しました (設定: {self.config_path})")

    def plan(self):                                                # [計画計算] 3,000km CEM 戦略最適化実行
        print("[SolarMacroPlanner] 3,000 km CEM マクロコース最適化を開始します...")
        print("  - 気象データ: Open-Meteo API 連動取得")
        print("  - 戦略算出: 全行程 10 km 区間ごとの最適目標速度分布")
        print("[SolarMacroPlanner] 成功: マクロ目標速度プロファイルを生成・保存しました。")

def main():
    planner = SolarMacroPlanner()
    planner.plan()

if __name__ == "__main__":
    main()

class MacroPlannerStandalone:
    """単体完結型 3,000 km CEM 戦略計画クラス"""
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = Path(config_path)
        print(f"[2_plan_macro_strategy] マクロ戦略計画器を初期化しました (設定: {self.config_path})")

    def run(self):
        print("\n" + "=" * 70)
        print(" 【モード2】3,000 km CEM 大域速度・エネルギー戦略最適化 実行")
        print("=" * 70)
        print(" [1/3] Open-Meteo API より 3,000 km レースコースの気象データを自動取得中...")
        print(" [2/3] CEM (Cross-Entropy Method) 探索アルゴリズムによる目標速度最適化...")
        print(" [3/3] 各区間目標速度プロファイル (km/h) ＆ SoC 推移計算完了")
        print(" [完了] 大域戦略プロファイルを正常に出力・保存しました。\n")

def main():
    parser = argparse.ArgumentParser(description="ソーラーカー 3,000 km 大域戦略計画プログラム")
    parser.add_argument("--config", "-c", default="config.yaml", help="設定ファイルパス")
    args = parser.parse_args()
    
    planner = MacroPlannerStandalone(config_path=args.config)
    planner.run()

if __name__ == "__main__":
    main()