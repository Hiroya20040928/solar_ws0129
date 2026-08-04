#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import os
import sys
from pathlib import Path
from typing import Iterable

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_bwsc2025_fitted_package import (
    infer_soc_from_loaded_state,
    robust_segment_anchor_soc,
)
from scripts.run_vehicle_identification import (
    build_model_from_profile_cfg,
    resolve_identification_output_layout,
)


def resolve(base: Path, raw: str) -> Path:                         # [関数定義] resolve の処理実行ブロック
    path = Path(raw)
    if path.is_absolute():
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    root_candidate = (ROOT / path).resolve()
    if root_candidate.exists() or (path.parts and path.parts[0] == "project_packages"):
        return root_candidate                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return (base / path).resolve()                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def summarize_channels(values: Iterable[float], max_spread: float) -> dict[str, float | bool]:  # [関数定義] summarize_channels の処理実行ブロック
    finite = np.asarray([float(value) for value in values if np.isfinite(value)], dtype=float)
    if finite.size == 0:
        return {                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "evidence_interval_min": math.nan,
            "evidence_interval_max": math.nan,
            "unweighted_central_estimate": math.nan,
            "spread_percentage_points": math.nan,
            "high_precision_gate_pass": False,
        }
    lo = float(np.min(finite))
    hi = float(np.max(finite))
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "evidence_interval_min": lo,
        "evidence_interval_max": hi,
        "unweighted_central_estimate": float(np.mean(finite)),
        "spread_percentage_points": float(100.0 * (hi - lo)),
        "high_precision_gate_pass": bool((hi - lo) <= float(max_spread)),
    }


def random_effects_fusion(values: Iterable[float], sigmas: Iterable[float]) -> dict[str, float | int]:  # [関数定義] random_effects_fusion の処理実行ブロック
    pairs = [
        (float(value), max(float(sigma), 1.0e-6))
        for value, sigma in zip(values, sigmas)
        if np.isfinite(value) and np.isfinite(sigma) and float(sigma) > 0.0
    ]
    if not pairs:
        return {                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "fusion_channel_count": 0,
            "random_effects_soc": math.nan,
            "random_effects_standard_error": math.nan,
            "random_effects_ci95_min": math.nan,
            "random_effects_ci95_max": math.nan,
            "between_channel_variance_tau2": math.nan,
            "heterogeneity_q": math.nan,
            "heterogeneity_i2_pct": math.nan,
        }
    estimates = np.asarray([pair[0] for pair in pairs], dtype=float)
    variances = np.square(np.asarray([pair[1] for pair in pairs], dtype=float))
    fixed_weights = 1.0 / variances
    fixed_mean = float(np.sum(fixed_weights * estimates) / np.sum(fixed_weights))
    q_value = float(np.sum(fixed_weights * np.square(estimates - fixed_mean)))
    degrees_freedom = max(len(estimates) - 1, 0)
    c_value = float(np.sum(fixed_weights) - np.sum(np.square(fixed_weights)) / np.sum(fixed_weights))
    tau2 = float(max(0.0, (q_value - degrees_freedom) / c_value)) if c_value > 0.0 else 0.0
    random_weights = 1.0 / (variances + tau2)
    fused_soc = float(np.sum(random_weights * estimates) / np.sum(random_weights))
    standard_error = float(math.sqrt(1.0 / np.sum(random_weights)))
    i2_pct = float(100.0 * max(0.0, (q_value - degrees_freedom) / q_value)) if q_value > 0.0 else 0.0
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "fusion_channel_count": int(len(estimates)),
        "random_effects_soc": fused_soc,
        "random_effects_standard_error": standard_error,
        "random_effects_ci95_min": float(max(0.0, fused_soc - 1.96 * standard_error)),
        "random_effects_ci95_max": float(min(1.0, fused_soc + 1.96 * standard_error)),
        "between_channel_variance_tau2": tau2,
        "heterogeneity_q": q_value,
        "heterogeneity_i2_pct": i2_pct,
    }


def terminal_loaded_state_soc(                                     # [関数定義] terminal_loaded_state_soc の処理実行ブロック
    frame: pd.DataFrame,
    model,
    ocv_df: pd.DataFrame,
    terminal_km: float,
) -> tuple[float, dict[str, float | int | str]]:
    distance = pd.to_numeric(frame["s_km"], errors="coerce")
    voltage = pd.to_numeric(frame["battery_voltage_v"], errors="coerce")
    current = pd.to_numeric(frame["battery_current_a"], errors="coerce")
    temp = pd.to_numeric(frame["Tamb_archive_C"], errors="coerce")
    valid = distance.notna() & voltage.notna() & current.notna() & temp.notna() & (voltage >= 20.0)
    window = frame.loc[valid & ((distance - float(terminal_km)).abs() <= 1.5)].tail(6)
    if window.empty:
        window = frame.loc[valid].tail(6)
    estimates = [
        infer_soc_from_loaded_state(
            float(row.battery_voltage_v),
            float(row.battery_current_a),
            float(row.Tamb_archive_C),
            ocv_df,
            model,
            rint_scale=float(model.p.rint_scale),
            r_line_ohm=float(model.p.r_line_ohm),
        )
        for row in window.itertuples(index=False)
    ]
    value = float(np.nanmedian(np.asarray(estimates, dtype=float)))
    observation = {
        "sample_count": int(len(window)),
        "time_utc": str(window["time_utc"].iloc[-1]) if len(window) else "",
        "distance_km": float(pd.to_numeric(window["s_km"], errors="coerce").median()),
        "voltage_v": float(pd.to_numeric(window["battery_voltage_v"], errors="coerce").median()),
        "current_a": float(pd.to_numeric(window["battery_current_a"], errors="coerce").median()),
        "temperature_c": float(pd.to_numeric(window["Tamb_archive_C"], errors="coerce").median()),
    }
    return value, observation                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _soc_from_ocv(ocv_v: float, ocv_df: pd.DataFrame) -> float:    # [関数定義] _soc_from_ocv の処理実行ブロック
    """Invert the monotone pack OCV map without extrapolating beyond its support."""
    soc = pd.to_numeric(ocv_df["soc"], errors="coerce").to_numpy(dtype=float)
    ocv = pd.to_numeric(ocv_df["ocv_v"], errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(soc) & np.isfinite(ocv)
    if np.count_nonzero(valid) < 2:
        return math.nan                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
    order = np.argsort(ocv[valid])
    ocv_sorted = ocv[valid][order]
    soc_sorted = soc[valid][order]
    return float(np.interp(float(ocv_v), ocv_sorted, soc_sorted))  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _fit_terminal_thevenin_arrays(                                 # [関数定義] _fit_terminal_thevenin_arrays の処理実行ブロック
    time_h: np.ndarray,
    current_a: np.ndarray,
    voltage_v: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Fit V = OCV_terminal + drift*time - R*I with a Huber loss."""
    design = np.column_stack(
        [np.ones_like(time_h), np.asarray(time_h, dtype=float), -np.asarray(current_a, dtype=float)]
    )
    initial, *_ = np.linalg.lstsq(design, voltage_v, rcond=None)
    initial = np.clip(initial, [70.0, -10.0, 0.0], [110.0, 10.0, 2.0])
    initial_residual = design @ initial - voltage_v
    median = float(np.median(initial_residual))
    mad_sigma = 1.4826 * float(np.median(np.abs(initial_residual - median)))
    fit = least_squares(
        lambda params: design @ params - voltage_v,
        x0=initial,
        bounds=([70.0, -10.0, 0.0], [110.0, 10.0, 2.0]),
        loss="huber",
        f_scale=max(mad_sigma, 0.05),
        max_nfev=3000,
    )
    return np.asarray(fit.x, dtype=float), design @ fit.x - voltage_v  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fit_terminal_thevenin_window(                                  # [関数定義] fit_terminal_thevenin_window の処理実行ブロック
    frame: pd.DataFrame,
    ocv_df: pd.DataFrame,
    *,
    terminal_km: float,
    window_km: float,
    bootstrap_repetitions: int = 400,
    bootstrap_block_rows: int = 6,
    random_seed: int = 20260715,
    ocv_map_systematic_sigma_v: float = 0.15,
) -> dict[str, float | int | bool | str]:
    """Identify terminal OCV and total series resistance from the final V-I excitation.

    A linear time term absorbs the small OCV drift while the car covers the selected
    distance window. Contiguous residual blocks preserve short-period serial
    correlation better than row-wise resampling.
    """
    distance = pd.to_numeric(frame["s_km"], errors="coerce")
    voltage = pd.to_numeric(frame["battery_voltage_v"], errors="coerce")
    current = pd.to_numeric(frame["battery_current_a"], errors="coerce")
    timestamp = pd.to_datetime(frame["time_utc"], utc=True, errors="coerce")
    valid = (
        distance.notna()
        & voltage.between(70.0, 110.0)
        & current.between(-60.0, 60.0)
        & timestamp.notna()
        & (distance <= float(terminal_km) + 0.05)
        & (distance >= float(terminal_km) - float(window_km))
    )
    work = pd.DataFrame(
        {
            "distance_km": distance.loc[valid],
            "voltage_v": voltage.loc[valid],
            "current_a": current.loc[valid],
            "time_utc": timestamp.loc[valid],
        }
    ).sort_values("time_utc")
    if len(work) < 12:
        raise ValueError(
            f"terminal Thevenin fit needs at least 12 valid rows; got {len(work)} "
            f"inside the final {window_km:g} km"
        )

    terminal_time = work["time_utc"].iloc[-1]
    time_h = (work["time_utc"] - terminal_time).dt.total_seconds().to_numpy(dtype=float) / 3600.0
    current_values = work["current_a"].to_numpy(dtype=float)
    voltage_values = work["voltage_v"].to_numpy(dtype=float)
    params, residual = _fit_terminal_thevenin_arrays(time_h, current_values, voltage_values)
    predicted = voltage_values + residual

    rng = np.random.default_rng(int(random_seed))
    block_rows = max(2, min(int(bootstrap_block_rows), len(work)))
    starts = np.arange(max(1, len(work) - block_rows + 1), dtype=int)
    bootstrap_ocv: list[float] = []
    for _ in range(max(0, int(bootstrap_repetitions))):
        sampled_parts: list[np.ndarray] = []
        while sum(len(part) for part in sampled_parts) < len(work):
            start = int(rng.choice(starts))
            sampled_parts.append(residual[start : start + block_rows])
        sampled_residual = np.concatenate(sampled_parts)[: len(work)]
        try:
            bootstrap_params, _ = _fit_terminal_thevenin_arrays(
                time_h,
                current_values,
                predicted - sampled_residual,
            )
            bootstrap_ocv.append(float(bootstrap_params[0]))
        except (ValueError, np.linalg.LinAlgError):
            continue

    bootstrap_values = np.asarray(bootstrap_ocv, dtype=float)
    bootstrap_sigma_v = (
        float(np.std(bootstrap_values, ddof=1)) if bootstrap_values.size >= 2 else math.nan
    )
    statistical_sigma_v = bootstrap_sigma_v if np.isfinite(bootstrap_sigma_v) else 0.0
    total_ocv_sigma_v = float(math.hypot(statistical_sigma_v, ocv_map_systematic_sigma_v))
    ocv_terminal_v = float(params[0])
    soc = _soc_from_ocv(ocv_terminal_v, ocv_df)
    soc_low = _soc_from_ocv(ocv_terminal_v - 1.96 * total_ocv_sigma_v, ocv_df)
    soc_high = _soc_from_ocv(ocv_terminal_v + 1.96 * total_ocv_sigma_v, ocv_df)
    soc_min, soc_max = sorted((soc_low, soc_high))
    soc_sigma = float((soc_max - soc_min) / (2.0 * 1.96))
    current_span = float(np.ptp(current_values))
    rmse_v = float(math.sqrt(np.mean(np.square(residual))))
    structural_fit_quality_pass = bool(
        len(work) >= 12
        and current_span >= 10.0
        and 0.05 <= float(params[2]) <= 0.50
        and rmse_v <= 0.25
    )
    uncertainty_evaluation_pass = bool(
        int(bootstrap_repetitions) == 0
        or bootstrap_values.size >= max(50, int(0.8 * bootstrap_repetitions))
    )
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "window_km": float(window_km),
        "sample_count": int(len(work)),
        "time_start_utc": str(work["time_utc"].iloc[0]),
        "time_terminal_utc": str(terminal_time),
        "distance_start_km": float(work["distance_km"].min()),
        "distance_terminal_km": float(work["distance_km"].max()),
        "current_min_a": float(np.min(current_values)),
        "current_max_a": float(np.max(current_values)),
        "current_span_a": current_span,
        "terminal_ocv_v": ocv_terminal_v,
        "ocv_drift_v_per_hour": float(params[1]),
        "series_resistance_ohm": float(params[2]),
        "voltage_rmse_v": rmse_v,
        "voltage_residual_median_v": float(np.median(residual)),
        "bootstrap_repetitions_requested": int(bootstrap_repetitions),
        "bootstrap_repetitions_valid": int(bootstrap_values.size),
        "bootstrap_block_rows": int(block_rows),
        "bootstrap_ocv_sigma_v": bootstrap_sigma_v,
        "ocv_map_systematic_sigma_v": float(ocv_map_systematic_sigma_v),
        "total_ocv_sigma_v": total_ocv_sigma_v,
        "terminal_soc": soc,
        "terminal_soc_sigma": soc_sigma,
        "terminal_soc_ci95_min": soc_min,
        "terminal_soc_ci95_max": soc_max,
        "structural_fit_quality_pass": structural_fit_quality_pass,
        "uncertainty_evaluation_pass": uncertainty_evaluation_pass,
        "fit_quality_pass": bool(
            structural_fit_quality_pass
            and len(work) >= 30
            and int(bootstrap_repetitions) > 0
            and uncertainty_evaluation_pass
        ),
        "equation": "V(t) = OCV_terminal + dVdt*(t-t_terminal) - R_series*I(t)",
    }


def day_net_energy_soc(                                            # [関数定義] day_net_energy_soc の処理実行ブロック
    frame: pd.DataFrame,
    model,
    ocv_df: pd.DataFrame,
    day: int,
) -> tuple[float, float, float]:
    day_values = pd.to_numeric(frame["day"], errors="coerce")
    work = frame.loc[day_values == int(day)].reset_index(drop=True)
    if work.empty:
        return math.nan, math.nan, math.nan                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    start_soc = robust_segment_anchor_soc(
        work,
        0,
        ocv_df,
        model,
        float(model.p.rint_scale),
        float(model.p.r_line_ohm),
        float(model.p.soc_max),
    )
    power = pd.to_numeric(work["battery_power_w_obs"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    dt = pd.to_numeric(work["dt_sec"], errors="coerce").fillna(0.0).clip(lower=0.0, upper=10.0).to_numpy(dtype=float)
    eta_charge = float(getattr(model.p, "eta_charge", 1.0))
    effective_power = np.where(power < 0.0, eta_charge * power, power)
    signed_net_wh = float(np.sum(effective_power * dt) / 3600.0)
    end_soc = float(np.clip(
        start_soc - signed_net_wh / max(float(model.p.E_nom_Wh), 100.0),
        float(model.p.soc_min),
        float(model.p.soc_max),
    ))
    return start_soc, signed_net_wh, end_soc                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def main() -> None:                                                # [関数定義] main の処理実行ブロック
    parser = argparse.ArgumentParser(description="Cross-check independent terminal-SoC evidence channels.")
    parser.add_argument("--profile", required=True)                # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--observed-log")                          # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument(                                           # [CLI引数] コマンドライン実行引数の定義
        "--ocv-map",
        help="Explicit grounded OCV map; defaults to paths.ocv_soc_map from the profile.",
    )
    parser.add_argument("--terminal-km", type=float, default=2831.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--team-remaining-energy-wh", type=float, default=1335.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--team-nominal-energy-wh", type=float, default=3011.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--voltage-soc-sigma", type=float, default=0.08)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--team-remaining-energy-sigma-wh", type=float, default=200.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--team-nominal-energy-sigma-wh", type=float, default=100.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--day-integrated-soc-sigma", type=float, default=0.10)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--day", type=int, default=6)              # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--max-spread", type=float, default=0.05)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--pulse-window-km", type=float, default=3.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--pulse-sensitivity-windows-km", default="1,2,3,5,10")  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--bootstrap-repetitions", type=int, default=400)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--bootstrap-block-rows", type=int, default=6)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--ocv-map-systematic-sigma-v", type=float, default=0.15)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--loaded-voltage-sigma-v", type=float, default=0.25)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--anchor-output")                         # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--output")                                # [CLI引数] コマンドライン実行引数の定義
    args = parser.parse_args()

    profile_path = resolve(ROOT, args.profile)
    package_dir = profile_path.parent
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    model = build_model_from_profile_cfg(profile, profile_path)
    observed_raw = args.observed_log or str(
        (profile.get("paths", {}) or {}).get(
            "progress_reference_csv",
            "data/observed/bwsc2025_observed_log_5s.csv",
        )
    )
    observed_path = resolve(package_dir, observed_raw)
    frame = pd.read_csv(observed_path, low_memory=False)
    ocv_raw = args.ocv_map or str((profile.get("paths", {}) or {})["ocv_soc_map"])
    ocv_path = resolve(package_dir, ocv_raw)
    ocv_df = pd.read_csv(ocv_path)

    voltage_soc, observation = terminal_loaded_state_soc(
        frame,
        model,
        ocv_df,
        args.terminal_km,
    )
    energy_soc = float(args.team_remaining_energy_wh / args.team_nominal_energy_wh)
    energy_soc_sigma = float(
        math.sqrt(
            (args.team_remaining_energy_sigma_wh / args.team_nominal_energy_wh) ** 2
            + (
                args.team_remaining_energy_wh
                * args.team_nominal_energy_sigma_wh
                / (args.team_nominal_energy_wh ** 2)
            ) ** 2
        )
    )
    day_start_soc, day_signed_net_wh, day_end_soc = day_net_energy_soc(
        frame,
        model,
        ocv_df,
        args.day,
    )
    summary = summarize_channels([voltage_soc, energy_soc, day_end_soc], args.max_spread)
    cross_channel_gate_pass = bool(summary["high_precision_gate_pass"])
    fusion = random_effects_fusion(
        [voltage_soc, energy_soc, day_end_soc],
        [args.voltage_soc_sigma, energy_soc_sigma, args.day_integrated_soc_sigma],
    )
    summary.update(fusion)

    sensitivity_windows = [
        float(value.strip())
        for value in str(args.pulse_sensitivity_windows_km).split(",")
        if value.strip()
    ]
    if not any(
        math.isclose(value, args.pulse_window_km, rel_tol=0.0, abs_tol=1.0e-9)
        for value in sensitivity_windows
    ):
        sensitivity_windows.append(float(args.pulse_window_km))
        sensitivity_windows.sort()
    pulse_fits = [
        fit_terminal_thevenin_window(
            frame,
            ocv_df,
            terminal_km=args.terminal_km,
            window_km=window_km,
            bootstrap_repetitions=(
                args.bootstrap_repetitions
                if math.isclose(window_km, args.pulse_window_km, rel_tol=0.0, abs_tol=1.0e-9)
                else 0
            ),
            bootstrap_block_rows=args.bootstrap_block_rows,
            random_seed=20260715 + int(round(100.0 * window_km)),
            ocv_map_systematic_sigma_v=args.ocv_map_systematic_sigma_v,
        )
        for window_km in sensitivity_windows
    ]
    selected_pulse = min(
        pulse_fits,
        key=lambda item: abs(float(item["window_km"]) - float(args.pulse_window_km)),
    )
    sensitivity_soc = np.asarray(
        [float(item["terminal_soc"]) for item in pulse_fits], dtype=float
    )
    pulse_window_sensitivity_pp = float(100.0 * np.ptp(sensitivity_soc))
    pulse_ci_width = float(
        selected_pulse["terminal_soc_ci95_max"] - selected_pulse["terminal_soc_ci95_min"]
    )
    pulse_gate_pass = bool(
        selected_pulse["fit_quality_pass"]
        and pulse_window_sensitivity_pp <= 2.0
        and pulse_ci_width <= float(args.max_spread)
    )
    summary["high_precision_gate_pass"] = cross_channel_gate_pass
    summary.update(
        {
            "profile_yaml": os.path.relpath(profile_path, package_dir).replace("\\", "/"),
            "observed_log_csv": os.path.relpath(observed_path, package_dir).replace("\\", "/"),
            "ocv_soc_map_csv": os.path.relpath(ocv_path, package_dir).replace("\\", "/"),
            "terminal_distance_km": float(args.terminal_km),
            "voltage_loaded_state_soc": voltage_soc,
            "terminal_observation": observation,
            "team_report_remaining_energy_wh": float(args.team_remaining_energy_wh),
            "team_report_nominal_energy_wh": float(args.team_nominal_energy_wh),
            "team_report_energy_soc": energy_soc,
            "team_report_energy_soc_sigma": energy_soc_sigma,
            "integrated_day": int(args.day),
            "day_start_soc_from_stationary_voltage": day_start_soc,
            "day_signed_net_pack_energy_wh": day_signed_net_wh,
            "day_integrated_end_soc": day_end_soc,
            "terminal_pulse_thevenin": selected_pulse,
            "terminal_pulse_window_sensitivity": pulse_fits,
            "terminal_pulse_window_sensitivity_percentage_points": pulse_window_sensitivity_pp,
            "terminal_pulse_anchor_gate_pass": pulse_gate_pass,
            "terminal_pulse_anchor_gate_is_conditional": True,
            "independent_cross_channel_gate_pass": cross_channel_gate_pass,
            "positive_power_convention": "battery discharge",
            "channel_estimates": [
                {
                    "name": "loaded_voltage",
                    "soc": voltage_soc,
                    "sigma": float(args.voltage_soc_sigma),
                },
                {
                    "name": "team_remaining_energy",
                    "soc": energy_soc,
                    "sigma": energy_soc_sigma,
                },
                {
                    "name": "day6_signed_energy_integration",
                    "soc": day_end_soc,
                    "sigma": float(args.day_integrated_soc_sigma),
                },
            ],
            "fusion_method": "DerSimonian-Laird method-of-moments random-effects fusion",
            "fusion_caution": (
                "The random-effects center summarizes conflicting channels; it does not override "
                "the evidence-spread high-precision gate."
            ),
            "terminal_pulse_anchor_caution": (
                "The pulse anchor is conditional on the grounded pseudo-OCV map and the configured "
                "OCV-map systematic uncertainty. It is suitable for model conditioning only when "
                "terminal_pulse_anchor_gate_pass is true; it is not an independent rested-OCV validation."
            ),
            "interpretation": (
                "Independent evidence agrees within the configured acceptance spread."
                if summary["high_precision_gate_pass"]
                else "Independent evidence conflicts; do not claim a high-precision terminal SoC or force one channel as exact truth."
            ),
            "required_follow_up": [
                "rested multi-SoC and multi-temperature current-pulse DCIR test",
                "calibrated pack current integration with an independent energy meter",
                "rested terminal OCV measurement after the final drive",
            ],
        }
    )

    pulse_anchor = {
        "terminal_anchor": {
            "s_km": float(args.terminal_km),
            "time_utc": str(selected_pulse["time_terminal_utc"]),
            "voltage_v": float(observation["voltage_v"]),
            "current_a": float(observation["current_a"]),
            "temp_c": float(observation["temperature_c"]),
            "ocv_terminal_v": float(selected_pulse["terminal_ocv_v"]),
            "series_resistance_ohm": float(selected_pulse["series_resistance_ohm"]),
            "ocv_statistical_sigma_v": float(selected_pulse["bootstrap_ocv_sigma_v"]),
            "ocv_systematic_sigma_v": float(selected_pulse["ocv_map_systematic_sigma_v"]),
            "ocv_total_sigma_v": float(selected_pulse["total_ocv_sigma_v"]),
            "soc_target": float(selected_pulse["terminal_soc"]),
            "soc_sigma": float(selected_pulse["terminal_soc_sigma"]),
            "soc_evidence_min": float(selected_pulse["terminal_soc_ci95_min"]),
            "soc_evidence_max": float(selected_pulse["terminal_soc_ci95_max"]),
            "voltage_sigma_v": float(args.loaded_voltage_sigma_v),
            "soc_target_basis": (
                "Robust local Thevenin V-I regression in the final drive window, converted through "
                "the grounded pseudo-OCV map with an explicit map-systematic uncertainty."
            ),
            "method": (
                str(selected_pulse["equation"])
                + "; the MLE voltage term separately uses the measured loaded terminal voltage/current"
            ),
            "source_documents": [
                os.path.relpath(observed_path, package_dir).replace("\\", "/"),
                os.path.relpath(ocv_path, package_dir).replace("\\", "/"),
            ],
            "quality_gate_pass": pulse_gate_pass,
            "conditional_on_grounded_ocv_map": True,
            "weak_channel_cross_consistency_gate_pass": cross_channel_gate_pass,
            "notes": [
                "The local V-I excitation identifies terminal OCV and series resistance without treating one loaded-voltage sample as OCV.",
                "The team remaining-energy and Day6-integral channels remain in the audit output but are not averaged into this local anchor.",
                "A calibrated rested multi-SoC pulse test remains required for independent certification of the pseudo-OCV map.",
            ],
        }
    }

    if args.output:
        output = resolve(package_dir, args.output)
    else:
        layout = resolve_identification_output_layout(package_dir, profile)
        output = Path(layout["run_root"]) / "terminal_soc_consistency.yaml"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump(summary, stream, sort_keys=False, allow_unicode=True)
    if args.anchor_output:
        anchor_output = resolve(package_dir, args.anchor_output)
        anchor_output.parent.mkdir(parents=True, exist_ok=True)
        with anchor_output.open("w", encoding="utf-8", newline="\n") as stream:
            yaml.safe_dump(pulse_anchor, stream, sort_keys=False, allow_unicode=True)
        print(anchor_output)
    print(output)


if __name__ == "__main__":
    main()
