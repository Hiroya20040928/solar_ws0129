from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from itertools import product
import multiprocessing as mp
import os
from typing import Callable, Iterable, List, Sequence, Tuple

import numpy as np
from scipy.optimize import minimize, shgo


Bounds = Sequence[Tuple[float, float]]


_FORK_COST_FN: Callable[[np.ndarray], float] | None = None


def _fork_finite_cost(vec: np.ndarray) -> float:
    if _FORK_COST_FN is None:
        return float("inf")
    return finite_cost(_FORK_COST_FN, vec)


def clip_to_bounds(vec: np.ndarray, bounds: Bounds) -> np.ndarray:
    out = np.asarray(vec, dtype=float).copy()
    for idx, (lo, hi) in enumerate(bounds):
        out[idx] = float(np.clip(out[idx], lo, hi))
    return out


def finite_cost(cost_fn: Callable[[np.ndarray], float], vec: np.ndarray) -> float:
    try:
        value = float(cost_fn(np.asarray(vec, dtype=float)))
    except Exception:
        return float("inf")
    if not np.isfinite(value):
        return float("inf")
    return value


def default_seed_library(x0: np.ndarray, bounds: Bounds) -> List[tuple[str, np.ndarray]]:
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
    return seeds


def hybrid_bounded_minimize(
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

    def add_candidate(label: str, vec: np.ndarray) -> None:
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
        return clip_to_bounds(x0, bounds), {
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

    def local_refine_rows(pool: Sequence[dict]) -> list[dict]:
        refined: list[dict] = []
        if maxiter <= 0:
            return refined
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
        return refined

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

    def emit_progress(payload: dict) -> None:
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

            def record_grid_candidate(idx: int, candidate_x: np.ndarray, candidate_fun: float) -> None:
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

    def should_run_cem_from_seed_consensus(rows: Sequence[dict]) -> tuple[bool, float]:
        usable = [row for row in rows if np.isfinite(float(row.get("fun", float("inf"))))]
        if len(usable) < 2:
            return False, 0.0
        top = usable[: min(3, len(usable))]
        mat = np.vstack([np.asarray(row["x"], dtype=float) for row in top])
        spread = float(np.max(np.std(mat, axis=0) / np.maximum(span, 1.0e-6)))
        best_fun = float(top[0]["fun"])
        next_fun = float(top[1]["fun"])
        gap = abs(next_fun - best_fun) / max(1.0, abs(best_fun))
        run = bool((spread > 0.08) or (gap > 0.10) or (not bool(top[0].get("success", True))))
        return run, spread

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

    return np.asarray(best["x"], dtype=float), {
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
