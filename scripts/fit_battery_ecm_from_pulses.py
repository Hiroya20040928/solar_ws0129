#!/usr/bin/env python3
"""Identify a passive pack-level 1-RC battery model from rested pulse tests.

Positive current means battery discharge.  The identified model is

    Vt = Uocv(z) - I * R0_total(z, T) - V1
    dV1/dt = -V1/tau(z, T) + R1(z, T) * I / tau(z, T)

``R0_total`` deliberately includes cells, tabs, bus bars, contactors, fuses,
and measurement leads.  Those contributions cannot be separated from a
two-terminal pack pulse and are therefore not assigned invented values.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import io
import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
from scipy.optimize import minimize, minimize_scalar, nnls


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REST_REQUIRED = {
    "rest_id",
    "split",
    "soc_reference",
    "temp_c",
    "rest_duration_sec",
    "rest_voltage_v",
    "rest_current_a",
    "rest_voltage_slope_uv_per_s",
    "soc_reference_method",
    "current_accuracy_a",
    "voltage_accuracy_v",
    "source_file",
}
PULSE_REQUIRED = {
    "test_id",
    "split",
    "time_s",
    "step_start_time_s",
    "phase",
    "current_a",
    "voltage_v",
    "temp_c",
    "soc_reference",
    "pre_rest_duration_sec",
    "pre_rest_voltage_slope_uv_per_s",
    "soc_reference_method",
    "current_accuracy_a",
    "voltage_accuracy_v",
    "source_file",
}
INDEPENDENT_SOC_METHODS = {
    "coulomb_counted_from_full",
    "gravimetric_capacity",
    "independent_calibrated_bms",
    "known_charge_state",
}


class BatteryEvidenceError(ValueError):                            # [クラス定義] BatteryEvidenceError オブジェクトの設計
    """Raised when data cannot support a physically identifiable map."""


@dataclass(frozen=True)
class FitLimits:                                                   # [クラス定義] FitLimits オブジェクトの設計
    minimum_rest_sec: float = 1800.0
    maximum_rest_current_a: float = 0.25
    maximum_rest_voltage_slope_uv_per_s: float = 10.0
    minimum_current_step_a: float = 3.0
    maximum_first_sample_delay_sec: float = 0.25
    minimum_pulse_samples: int = 8
    minimum_train_tests: int = 12
    minimum_validation_tests: int = 4
    minimum_soc_span: float = 0.70
    minimum_temp_span_c: float = 25.0
    maximum_validation_normalized_rmse: float = 3.0
    operational_soc_min: float = 0.05
    operational_soc_max: float = 0.95
    maximum_soc_boundary_gap: float = 0.05
    edge_validation_band: float = 0.10
    minimum_edge_validation_tests: int = 1
    r0_high_soc_nonincreasing_from: float | None = None
    enforce_r0_temperature_nonincreasing: bool = False


def _required_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:  # [関数定義] _required_columns の処理実行ブロック
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise BatteryEvidenceError(f"{label} is missing columns: {missing}")


def _numeric(frame: pd.DataFrame, columns: Iterable[str], label: str) -> pd.DataFrame:  # [関数定義] _numeric の処理実行ブロック
    out = frame.copy()
    for column in columns:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    bad = out[list(columns)].isna().any(axis=1)
    if bool(bad.any()):
        rows = (np.flatnonzero(bad.to_numpy()) + 2).tolist()[:12]
        raise BatteryEvidenceError(f"{label} has non-numeric required values at CSV rows {rows}")
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_rest_data(path: str | Path) -> pd.DataFrame:              # [関数定義] load_rest_data の処理実行ブロック
    frame = pd.read_csv(path)
    _required_columns(frame, REST_REQUIRED, "rest CSV")
    frame = _numeric(
        frame,
        (
            "soc_reference", "temp_c", "rest_duration_sec", "rest_voltage_v",
            "rest_current_a", "rest_voltage_slope_uv_per_s",
            "current_accuracy_a", "voltage_accuracy_v",
        ),
        "rest CSV",
    )
    frame["split"] = frame["split"].astype(str).str.strip().str.lower()
    frame["soc_reference_method"] = frame["soc_reference_method"].astype(str).str.strip().str.lower()
    return frame                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_pulse_data(path: str | Path) -> pd.DataFrame:             # [関数定義] load_pulse_data の処理実行ブロック
    frame = pd.read_csv(path)
    _required_columns(frame, PULSE_REQUIRED, "pulse CSV")
    frame = _numeric(
        frame,
        (
            "time_s",
            "step_start_time_s",
            "current_a",
            "voltage_v",
            "temp_c",
            "soc_reference",
            "pre_rest_duration_sec",
            "pre_rest_voltage_slope_uv_per_s",
            "current_accuracy_a",
            "voltage_accuracy_v",
        ),
        "pulse CSV",
    )
    frame["split"] = frame["split"].astype(str).str.strip().str.lower()
    frame["phase"] = frame["phase"].astype(str).str.strip().str.lower()
    frame["soc_reference_method"] = frame["soc_reference_method"].astype(str).str.strip().str.lower()
    return frame.sort_values(["test_id", "time_s"]).reset_index(drop=True)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _pava_non_decreasing(values: np.ndarray, weights: np.ndarray) -> np.ndarray:  # [関数定義] _pava_non_decreasing の処理実行ブロック
    blocks = [[float(value), float(weight), 1] for value, weight in zip(values, weights)]
    index = 0
    while index < len(blocks) - 1:
        if blocks[index][0] <= blocks[index + 1][0] + 1.0e-12:
            index += 1
            continue
        total_weight = blocks[index][1] + blocks[index + 1][1]
        mean = (
            blocks[index][0] * blocks[index][1]
            + blocks[index + 1][0] * blocks[index + 1][1]
        ) / max(total_weight, 1.0e-12)
        merged = [mean, total_weight, blocks[index][2] + blocks[index + 1][2]]
        blocks[index : index + 2] = [merged]
        index = max(0, index - 1)
    output: list[float] = []
    for mean, _weight, count in blocks:
        output.extend([float(mean)] * int(count))
    return np.asarray(output, dtype=float)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fit_ocv_curve(rest: pd.DataFrame, limits: FitLimits) -> tuple[pd.DataFrame, dict]:  # [関数定義] fit_ocv_curve の処理実行ブロック
    eligible = rest[
        rest["split"].isin({"train", "validation"})
        & rest["soc_reference_method"].isin(INDEPENDENT_SOC_METHODS)
        & (rest["rest_duration_sec"] >= limits.minimum_rest_sec)
        & (rest["rest_current_a"].abs() <= limits.maximum_rest_current_a)
        & (
            rest["rest_voltage_slope_uv_per_s"].abs()
            <= limits.maximum_rest_voltage_slope_uv_per_s
        )
        & (rest["voltage_accuracy_v"] > 0.0)
        & (rest["current_accuracy_a"] > 0.0)
        & rest["soc_reference"].between(0.0, 1.0)
    ].copy()
    train = eligible[eligible["split"] == "train"].sort_values("soc_reference")
    validation = eligible[eligible["split"] == "validation"].copy()
    if len(train) < 6:
        raise BatteryEvidenceError("at least six independently referenced training rest points are required")
    grouped = (
        train.groupby("soc_reference", as_index=False)
        .agg(rest_voltage_v=("rest_voltage_v", "median"), count=("rest_id", "count"))
        .sort_values("soc_reference")
    )
    z = grouped["soc_reference"].to_numpy(dtype=float)
    voltage = grouped["rest_voltage_v"].to_numpy(dtype=float)
    monotone = _pava_non_decreasing(voltage, grouped["count"].to_numpy(dtype=float))
    dense_soc = np.linspace(float(z.min()), float(z.max()), max(2, int(round((z.max() - z.min()) * 100)) + 1))
    dense_voltage = np.interp(dense_soc, z, monotone)
    curve = pd.DataFrame({"soc": dense_soc, "ocv_v": dense_voltage})
    if len(validation):
        predicted = np.interp(
            validation["soc_reference"].to_numpy(dtype=float),
            dense_soc,
            dense_voltage,
        )
        residual = validation["rest_voltage_v"].to_numpy(dtype=float) - predicted
        validation_rmse = float(np.sqrt(np.mean(residual**2)))
        validation_normalized_rmse = float(
            np.sqrt(
                np.mean(
                    (
                        residual
                        / validation["voltage_accuracy_v"].to_numpy(dtype=float)
                    )
                    ** 2
                )
            )
        )
    else:
        validation_rmse = math.nan
        validation_normalized_rmse = math.nan
    info = {
        "eligible_count": int(len(eligible)),
        "train_count": int(len(train)),
        "validation_count": int(len(validation)),
        "soc_min": float(z.min()),
        "soc_max": float(z.max()),
        "soc_span": float(z.max() - z.min()),
        "validation_rmse_v": validation_rmse,
        "validation_normalized_rmse": validation_normalized_rmse,
        "method": "weighted isotonic pack rested-voltage fit against independently referenced SoC",
    }
    return curve, info                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _fit_single_pulse(group: pd.DataFrame, limits: FitLimits) -> dict:  # [関数定義] _fit_single_pulse の処理実行ブロック
    group = group.sort_values("time_s").copy()
    phases = set(group["phase"])
    if not {"pre_rest", "pulse"}.issubset(phases):
        raise BatteryEvidenceError("each test_id requires pre_rest and pulse phases")
    if group["split"].nunique() != 1:
        raise BatteryEvidenceError("one test_id cannot cross train/validation splits")
    pre = group[group["phase"] == "pre_rest"]
    pulse = group[group["phase"] == "pulse"].copy()
    if len(pre) < 3 or len(pulse) < limits.minimum_pulse_samples:
        raise BatteryEvidenceError("insufficient pre-rest or pulse samples")
    if float(group["pre_rest_duration_sec"].min()) < limits.minimum_rest_sec:
        raise BatteryEvidenceError("pre-rest duration is too short")
    if (
        float(group["pre_rest_voltage_slope_uv_per_s"].abs().max())
        > limits.maximum_rest_voltage_slope_uv_per_s
    ):
        raise BatteryEvidenceError("pre-rest voltage has not reached the declared equilibrium slope")
    if float(group["voltage_accuracy_v"].min()) <= 0.0 or float(group["current_accuracy_a"].min()) <= 0.0:
        raise BatteryEvidenceError("measurement accuracies must be positive")
    if not set(group["soc_reference_method"]).issubset(INDEPENDENT_SOC_METHODS):
        raise BatteryEvidenceError("SoC reference is not independent")
    i_pre = float(pre["current_a"].tail(min(10, len(pre))).median())
    v_pre = float(pre["voltage_v"].tail(min(10, len(pre))).median())
    if abs(i_pre) > limits.maximum_rest_current_a:
        raise BatteryEvidenceError("pre-rest current exceeds limit")
    start_times = group["step_start_time_s"].unique()
    if len(start_times) != 1:
        raise BatteryEvidenceError("one test_id must declare one step_start_time_s")
    start_time = float(start_times[0])
    pulse["t_rel"] = pulse["time_s"] - start_time
    first_delay = float(pulse["t_rel"].iloc[0])
    if first_delay < -1.0e-12 or first_delay > limits.maximum_first_sample_delay_sec + 1.0e-12:
        raise BatteryEvidenceError("first pulse sample is too late to identify R0")
    delta_i = pulse["current_a"].to_numpy(dtype=float) - i_pre
    if float(np.median(np.abs(delta_i))) < limits.minimum_current_step_a:
        raise BatteryEvidenceError("current step is too small")
    step_current = float(np.median(delta_i))
    if abs(step_current) < limits.minimum_current_step_a:
        raise BatteryEvidenceError("pulse changes sign or lacks a stable step")
    if float(np.std(delta_i) / max(abs(step_current), 1.0e-9)) > 0.12:
        raise BatteryEvidenceError("pulse current is not sufficiently constant")
    t = pulse["t_rel"].to_numpy(dtype=float)
    voltage = pulse["voltage_v"].to_numpy(dtype=float)

    def evaluate_tau(log_tau: float) -> tuple[float, float, float, np.ndarray, np.ndarray]:  # [関数定義] evaluate_tau の処理実行ブロック
        tau = math.exp(float(log_tau))
        basis = step_current * (1.0 - np.exp(-np.maximum(t, 0.0) / tau))
        design = np.column_stack((delta_i, basis))
        coefficients, _residual_norm = nnls(design, v_pre - voltage)
        r0, r1 = [float(value) for value in coefficients]
        predicted = v_pre - design @ coefficients
        rmse = float(np.sqrt(np.mean((voltage - predicted) ** 2)))
        return rmse, r0, r1, predicted, design                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    result = minimize_scalar(
        lambda value: evaluate_tau(value)[0],
        bounds=(math.log(0.2), math.log(1800.0)),
        method="bounded",
        options={"xatol": 1.0e-5},
    )
    rmse, r0, r1, predicted, design = evaluate_tau(float(result.x))
    if not np.isfinite(r0) or r0 <= 0.0:
        raise BatteryEvidenceError("joint pulse fit does not yield positive R0")
    tau = math.exp(float(result.x))
    voltage_accuracy_v = float(group["voltage_accuracy_v"].max())
    current_accuracy_a = float(group["current_accuracy_a"].max())
    information_inverse = np.linalg.pinv(design.T @ design)
    voltage_sigma_effective = math.sqrt(voltage_accuracy_v**2 + rmse**2)
    current_relative_sigma = current_accuracy_a / max(abs(step_current), 1.0e-12)
    r0_sigma_ohm = math.sqrt(
        max(0.0, float(information_inverse[0, 0])) * voltage_sigma_effective**2
        + (r0 * current_relative_sigma) ** 2
    )
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "test_id": str(group["test_id"].iloc[0]),
        "split": str(group["split"].iloc[0]),
        "soc_reference": float(group["soc_reference"].median()),
        "temp_c": float(group["temp_c"].median()),
        "current_step_a": step_current,
        "ocv_pre_v": v_pre,
        "r0_total_ohm": float(r0),
        "r1_ohm": float(r1),
        "tau_sec": float(tau),
        "voltage_rmse_v": rmse,
        "voltage_accuracy_v": voltage_accuracy_v,
        "current_accuracy_a": current_accuracy_a,
        "voltage_normalized_rmse": float(rmse / voltage_accuracy_v),
        "r0_total_ohm_sigma": float(r0_sigma_ohm),
        "sample_count": int(len(pulse)),
        "source_file": str(group["source_file"].iloc[0]),
        "measured_voltage_v": voltage.tolist(),
        "predicted_voltage_v": predicted.tolist(),
        "pulse_time_s": t.tolist(),
    }


def fit_pulse_tests(pulse: pd.DataFrame, limits: FitLimits) -> tuple[pd.DataFrame, list[dict]]:  # [関数定義] fit_pulse_tests の処理実行ブロック
    rows: list[dict] = []
    rejected: list[dict] = []
    for test_id, group in pulse.groupby("test_id", sort=False):
        try:
            rows.append(_fit_single_pulse(group, limits))
        except BatteryEvidenceError as exc:
            rejected.append({"test_id": str(test_id), "reason": str(exc)})
    if not rows:
        raise BatteryEvidenceError("no pulse test passed structural evidence checks")
    compact = pd.DataFrame(
        [{key: value for key, value in row.items() if not isinstance(value, list)} for row in rows]
    )
    return compact, rejected                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _surface_features(soc: np.ndarray, temp_c: np.ndarray) -> np.ndarray:  # [関数定義] _surface_features の処理実行ブロック
    z = (np.asarray(soc, dtype=float) - 0.5) / 0.5
    t = (np.asarray(temp_c, dtype=float) - 25.0) / 25.0
    return np.column_stack([np.ones_like(z), z, t, z * z, z * t, t * t])  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _surface_prediction(                                           # [関数定義] _surface_prediction の処理実行ブロック
    beta: np.ndarray,
    soc: np.ndarray,
    temp_c: np.ndarray,
    *,
    soc_support: tuple[float, float],
    temp_support: tuple[float, float],
) -> np.ndarray:
    """Evaluate only inside training support and hold the nearest edge outside it."""
    soc_eval = np.clip(np.asarray(soc, dtype=float), soc_support[0], soc_support[1])
    temp_eval = np.clip(np.asarray(temp_c, dtype=float), temp_support[0], temp_support[1])
    return np.exp(_surface_features(soc_eval, temp_eval) @ beta)   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _validation_metrics(                                           # [関数定義] _validation_metrics の処理実行ブロック
    validation: pd.DataFrame,
    observed_column: str,
    predicted: np.ndarray,
) -> dict:
    if validation.empty:
        return {                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "count": 0,
            "relative_rmse": math.nan,
            "normalized_rmse": math.nan,
        }
    observed = validation[observed_column].to_numpy(dtype=float)
    relative_rmse = float(
        np.sqrt(np.mean(((predicted - observed) / np.maximum(observed, 1.0e-9)) ** 2))
    )
    uncertainty_column = f"{observed_column}_sigma"
    if uncertainty_column in validation.columns:
        sigma = validation[uncertainty_column].to_numpy(dtype=float)
        normalized_rmse = float(
            np.sqrt(np.mean(((predicted - observed) / np.maximum(sigma, 1.0e-12)) ** 2))
        )
    else:
        normalized_rmse = math.nan
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "count": int(len(validation)),
        "relative_rmse": relative_rmse,
        "normalized_rmse": normalized_rmse,
    }


def fit_positive_surface(                                          # [関数定義] fit_positive_surface の処理実行ブロック
    points: pd.DataFrame,
    value_column: str,
    soc_grid: np.ndarray,
    temp_grid: np.ndarray,
    limits: FitLimits | None = None,
    *,
    high_soc_nonincreasing_from: float | None = None,
    temperature_nonincreasing: bool = False,
) -> tuple[pd.DataFrame, dict]:
    limits = limits or FitLimits()
    train = points[points["split"] == "train"]
    validation = points[points["split"] == "validation"]
    if len(train) < 6:
        raise BatteryEvidenceError(f"{value_column} requires at least six training pulses")
    x = _surface_features(train["soc_reference"], train["temp_c"])
    y = np.log(np.maximum(train[value_column].to_numpy(dtype=float), 1.0e-9))
    penalty = np.diag([0.0, 0.02, 0.02, 0.10, 0.10, 0.10])
    soc_support = (
        float(train["soc_reference"].min()),
        float(train["soc_reference"].max()),
    )
    temp_support = (
        float(train["temp_c"].min()),
        float(train["temp_c"].max()),
    )
    beta_initial = np.linalg.solve(x.T @ x + penalty, x.T @ y)
    derivative_constraints: list[np.ndarray] = []
    if high_soc_nonincreasing_from is not None:
        constraint_soc_min = max(float(high_soc_nonincreasing_from), soc_support[0])
        if constraint_soc_min <= soc_support[1]:
            for soc_value in np.linspace(constraint_soc_min, soc_support[1], 9):
                zeta = (float(soc_value) - 0.5) / 0.5
                for temp_value in np.linspace(temp_support[0], temp_support[1], 5):
                    theta = (float(temp_value) - 25.0) / 25.0
                    # d(log(value))/dSoC <= 0.
                    derivative_constraints.append(
                        np.asarray([0.0, 2.0, 0.0, 4.0 * zeta, 2.0 * theta, 0.0])
                    )
    if temperature_nonincreasing:
        for soc_value in np.linspace(soc_support[0], soc_support[1], 9):
            zeta = (float(soc_value) - 0.5) / 0.5
            for temp_value in np.linspace(temp_support[0], temp_support[1], 5):
                theta = (float(temp_value) - 25.0) / 25.0
                # 25*d(log(value))/dT <= 0.
                derivative_constraints.append(
                    np.asarray([0.0, 0.0, 1.0, 0.0, zeta, 2.0 * theta])
                )
    constraint_matrix = (
        np.vstack(derivative_constraints)
        if derivative_constraints
        else np.empty((0, len(beta_initial)), dtype=float)
    )
    if len(constraint_matrix):
        def objective(candidate: np.ndarray) -> float:             # [関数定義] objective の処理実行ブロック
            residual = x @ candidate - y
            return float(residual @ residual + candidate @ penalty @ candidate)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

        def objective_jacobian(candidate: np.ndarray) -> np.ndarray:  # [関数定義] objective_jacobian の処理実行ブロック
            return 2.0 * (x.T @ (x @ candidate - y) + penalty @ candidate)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

        optimized = minimize(
            objective,
            beta_initial,
            jac=objective_jacobian,
            constraints={
                "type": "ineq",
                "fun": lambda candidate: -(constraint_matrix @ candidate),
                "jac": lambda _candidate: -constraint_matrix,
            },
            method="SLSQP",
            options={"maxiter": 2000, "ftol": 1.0e-12},
        )
        if not optimized.success or not np.all(np.isfinite(optimized.x)):
            raise BatteryEvidenceError(
                f"{value_column} shape-constrained surface fit failed: {optimized.message}"
            )
        beta = np.asarray(optimized.x, dtype=float)
    else:
        beta = beta_initial
    maximum_constraint_violation = (
        float(np.max(constraint_matrix @ beta)) if len(constraint_matrix) else 0.0
    )
    if maximum_constraint_violation > 1.0e-8:
        raise BatteryEvidenceError(
            f"{value_column} violates a requested derivative constraint by "
            f"{maximum_constraint_violation:.3e}"
        )
    zz, tt = np.meshgrid(soc_grid, temp_grid)
    predicted_grid = _surface_prediction(
        beta,
        zz.ravel(),
        tt.ravel(),
        soc_support=soc_support,
        temp_support=temp_support,
    ).reshape(zz.shape)
    frame = pd.DataFrame(predicted_grid, index=temp_grid, columns=soc_grid)
    if len(validation):
        predicted = _surface_prediction(
            beta,
            validation["soc_reference"].to_numpy(dtype=float),
            validation["temp_c"].to_numpy(dtype=float),
            soc_support=soc_support,
            temp_support=temp_support,
        )
    else:
        predicted = np.asarray([], dtype=float)
    all_validation = _validation_metrics(validation, value_column, predicted)
    low_mask = validation["soc_reference"] <= (
        limits.operational_soc_min + limits.edge_validation_band
    )
    high_mask = validation["soc_reference"] >= (
        limits.operational_soc_max - limits.edge_validation_band
    )
    low_validation = validation.loc[low_mask]
    high_validation = validation.loc[high_mask]
    low_metrics = _validation_metrics(low_validation, value_column, predicted[low_mask.to_numpy()])
    high_metrics = _validation_metrics(high_validation, value_column, predicted[high_mask.to_numpy()])

    normalized_high_soc = (soc_support[1] - 0.5) / 0.5
    normalized_temperatures = (np.asarray(temp_grid, dtype=float) - 25.0) / 25.0
    high_soc_log_slopes = 2.0 * (
        beta[1] + 2.0 * beta[3] * normalized_high_soc + beta[4] * normalized_temperatures
    )
    normalized_soc_grid = (np.asarray(soc_grid, dtype=float) - 0.5) / 0.5
    normalized_temp_grid = (np.asarray(temp_grid, dtype=float) - 25.0) / 25.0
    temperature_log_slopes = np.asarray(
        [
            (beta[2] + beta[4] * zeta + 2.0 * beta[5] * theta) / 25.0
            for zeta in normalized_soc_grid
            for theta in normalized_temp_grid
        ],
        dtype=float,
    )
    return frame, {                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "value": value_column,
        "equation": (
            "value=exp(beta0+beta_z*zeta+beta_T*theta+beta_zz*zeta^2+"
            "beta_zT*zeta*theta+beta_TT*theta^2), "
            "zeta=(SoC-0.5)/0.5, theta=(T_C-25)/25"
        ),
        "coefficients_log_quadratic": beta.tolist(),
        "train_count": int(len(train)),
        "validation_count": int(len(validation)),
        "validation_relative_rmse": all_validation["relative_rmse"],
        "validation_normalized_rmse": all_validation["normalized_rmse"],
        "edge_validation": {"low_soc": low_metrics, "high_soc": high_metrics},
        "training_support": {
            "soc_min": soc_support[0],
            "soc_max": soc_support[1],
            "temp_c_min": temp_support[0],
            "temp_c_max": temp_support[1],
        },
        "high_soc_log_slope_per_soc_inside_support": {
            "minimum_over_output_temperatures": float(np.min(high_soc_log_slopes)),
            "maximum_over_output_temperatures": float(np.max(high_soc_log_slopes)),
            "interpretation": (
                "diagnostic only; the sign is determined by independent pulse data"
            ),
        },
        "temperature_log_slope_per_c_inside_output_grid": {
            "minimum": float(np.min(temperature_log_slopes)),
            "maximum": float(np.max(temperature_log_slopes)),
        },
        "derivative_constraint_count": int(len(constraint_matrix)),
        "maximum_derivative_constraint_violation": maximum_constraint_violation,
        "method": (
            "positive log-quadratic surface with curvature regularization, optional "
            "diagnostic directional constraints, and no free extrapolation"
        ),
        "outside_training_support_policy": (
            "hold the nearest fitted SoC/temperature boundary constant; never extrapolate the quadratic"
        ),
        "shape_constraint": {
            "high_soc_nonincreasing_from": high_soc_nonincreasing_from,
            "temperature_nonincreasing": bool(temperature_nonincreasing),
            "policy": (
                "directional constraints are non-release diagnostic hypotheses; the default "
                "release fit lets independent pulse evidence determine both slope signs"
            ),
        },
    }


def _png_data_uri(fig: plt.Figure) -> str:                         # [関数定義] _png_data_uri の処理実行ブロック
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=145, bbox_inches="tight")
    plt.close(fig)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _placeholder_figure(title: str, message: str) -> plt.Figure:   # [関数定義] _placeholder_figure の処理実行ブロック
    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    ax.axis("off")
    ax.text(0.5, 0.62, title, ha="center", va="center", fontsize=16, weight="bold")
    ax.text(0.5, 0.38, message, ha="center", va="center", fontsize=11, wrap=True)
    return fig                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_report_figures(                                          # [関数定義] build_report_figures の処理実行ブロック
    rest: pd.DataFrame,
    pulse_points: pd.DataFrame,
    pulse_details: list[dict],
    ocv: pd.DataFrame,
    r0: pd.DataFrame,
    r1: pd.DataFrame,
    tau: pd.DataFrame,
    summary: dict,
) -> list[tuple[str, str]]:
    figures: list[tuple[str, str]] = []

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.axis("off")
    ax.text(0.5, 0.92, "Physically identifiable pack-level 1-RC path", ha="center", fontsize=16, weight="bold")
    boxes = [
        (0.02, "independent SoC\n+ long rest"),
        (0.22, "rested OCV\nUocv(z)"),
        (0.42, "sub-second\ncurrent step"),
        (0.62, "R0,total +\nR1, tau"),
        (0.82, "held-out test\n+ adoption gate"),
    ]
    for x, label in boxes:
        ax.add_patch(plt.Rectangle((x, 0.40), 0.16, 0.22, fill=False, linewidth=2))
        ax.text(x + 0.08, 0.51, label, ha="center", va="center")
    for x in (0.18, 0.38, 0.58, 0.78):
        ax.annotate("", xy=(x + 0.035, 0.51), xytext=(x - 0.015, 0.51), arrowprops={"arrowstyle": "->"})
    figures.append(("1. Identification path", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    for split, group in rest.groupby("split"):
        ax.scatter(group["soc_reference"], group["rest_voltage_v"], label=split, alpha=0.8)
    ax.plot(ocv["soc"], ocv["ocv_v"], color="black", linewidth=2, label="monotone fit")
    ax.set(xlabel="independent SoC [-]", ylabel="rested pack voltage [V]", title="Rest evidence and OCV fit")
    ax.grid(True, alpha=0.25); ax.legend()
    figures.append(("2. Rested OCV evidence", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    detail = pulse_details[0]
    ax.plot(detail["pulse_time_s"], detail["measured_voltage_v"], label="measured")
    ax.plot(detail["pulse_time_s"], detail["predicted_voltage_v"], label="1-RC prediction")
    ax.set(xlabel="pulse time [s]", ylabel="pack voltage [V]", title=f"Pulse fit example: {detail['test_id']}")
    ax.grid(True, alpha=0.25); ax.legend()
    figures.append(("3. Representative pulse", _png_data_uri(fig)))

    for number, column, ylabel in (
        (4, "r0_total_ohm", "R0,total [ohm]"),
        (5, "r1_ohm", "R1 [ohm]"),
        (6, "tau_sec", "tau [s]"),
        (7, "voltage_rmse_v", "pulse voltage RMSE [V]"),
    ):
        fig, ax = plt.subplots(figsize=(9, 5))
        scatter = ax.scatter(
            pulse_points["soc_reference"], pulse_points[column],
            c=pulse_points["temp_c"], cmap="coolwarm", s=55,
        )
        ax.set(xlabel="independent SoC [-]", ylabel=ylabel, title=f"{ylabel} pulse estimates")
        ax.grid(True, alpha=0.25); fig.colorbar(scatter, ax=ax, label="temperature [C]")
        figures.append((f"{number}. {column}", _png_data_uri(fig)))

    for number, frame, title in (
        (8, r0, "R0,total(z,T)"),
        (9, r1, "R1(z,T)"),
        (10, tau, "tau(z,T)"),
    ):
        fig, ax = plt.subplots(figsize=(9, 5))
        image = ax.imshow(
            frame.to_numpy(dtype=float), aspect="auto", origin="lower",
            extent=[float(frame.columns.min()), float(frame.columns.max()), float(frame.index.min()), float(frame.index.max())],
            cmap="viridis",
        )
        ax.set(xlabel="SoC [-]", ylabel="temperature [C]", title=title)
        fig.colorbar(image, ax=ax)
        figures.append((f"{number}. {title}", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(pulse_points["soc_reference"], pulse_points["temp_c"], c=pulse_points["split"].map({"train": 0, "validation": 1}))
    ax.set(xlabel="SoC [-]", ylabel="temperature [C]", title="Evidence coverage (train/validation)")
    ax.grid(True, alpha=0.25)
    figures.append(("11. Evidence coverage", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(pulse_points["current_step_a"], pulse_points["r0_total_ohm"], c=pulse_points["soc_reference"], cmap="plasma")
    ax.set(xlabel="current step [A]", ylabel="R0,total [ohm]", title="Current-amplitude dependence audit")
    ax.grid(True, alpha=0.25)
    figures.append(("12. Current linearity audit", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(pulse_points["voltage_rmse_v"], bins=min(15, max(3, len(pulse_points) // 2)))
    ax.set(xlabel="pulse RMSE [V]", ylabel="count", title="Pulse residual distribution")
    figures.append(("13. Pulse residual distribution", _png_data_uri(fig)))

    for number, temp in zip((14, 15, 16), np.linspace(float(r0.index.min()), float(r0.index.max()), 3)):
        idx = int(np.argmin(np.abs(r0.index.to_numpy(dtype=float) - temp)))
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.plot(r0.columns, r0.iloc[idx], label="R0,total")
        ax.plot(r1.columns, r1.iloc[idx], label="R1")
        ax.set(xlabel="SoC [-]", ylabel="resistance [ohm]", title=f"Resistance components at {float(r0.index[idx]):.1f} C")
        ax.grid(True, alpha=0.25); ax.legend()
        figures.append((f"{number}. Resistance slice", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    soc = ocv["soc"].to_numpy(dtype=float)
    ocv_v = ocv["ocv_v"].to_numpy(dtype=float)
    mid_t = r0.iloc[len(r0) // 2].to_numpy(dtype=float)
    r_soc = np.interp(soc, r0.columns.to_numpy(dtype=float), mid_t)
    for current in (10.0, 20.0, 40.0, 60.0):
        ax.plot(soc, ocv_v - current * r_soc, label=f"{current:.0f} A instantaneous")
    ax.plot(soc, ocv_v, color="black", linewidth=2, label="OCV")
    ax.set(xlabel="SoC [-]", ylabel="pack voltage [V]", title="Current-dependent instantaneous terminal voltage")
    ax.grid(True, alpha=0.25); ax.legend()
    figures.append(("17. Current-dependent voltage", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    checks = summary["checks"]
    labels = list(checks)
    values = [1 if checks[label] else 0 for label in labels]
    ax.barh(labels, values, color=["#15803d" if value else "#b91c1c" for value in values])
    ax.set_xlim(0, 1.05); ax.set_title("Physical-evidence adoption checks")
    figures.append(("18. Adoption checks", _png_data_uri(fig)))

    figures.append(("19. Identifiability boundary", _png_data_uri(_placeholder_figure(
        "What the two-terminal pulse identifies",
        "R0,total is identifiable. Cell resistance, bus-bar resistance, contactor resistance, and lead resistance are not separately identifiable without additional four-wire measurements.",
    ))))
    figures.append(("20. Conclusion", _png_data_uri(_placeholder_figure(
        "PASS" if summary["gate_pass"] else "NOT APPROVED",
        "The model passed independent physical-evidence checks." if summary["gate_pass"] else "Do not promote these maps. Resolve every failed evidence check and repeat the independent test.",
    ))))
    return figures                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_html_report(path: Path, figures: list[tuple[str, str]], summary: dict) -> None:  # [関数定義] write_html_report の処理実行ブロック
    cards = "".join(
        f'<div class="check {"pass" if value else "fail"}"><b>{html.escape(key)}</b><br>{"PASS" if value else "FAIL"}</div>'
        for key, value in summary["checks"].items()
    )
    images = "".join(
        f'<section><h2>{html.escape(title)}</h2><img src="{uri}" alt="{html.escape(title)}"></section>'
        for title, uri in figures
    )
    payload = html.escape(json.dumps(summary, ensure_ascii=False, indent=2))
    document = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>Pack OCV / R0 / 1-RC physical evidence report</title>
<style>
body{{font-family:"Yu Gothic",sans-serif;margin:0;background:#f3efe4;color:#17202a}}main{{max-width:1120px;margin:auto;padding:28px}}
.hero,section{{background:#fffdf7;border:1px solid #d8d0bf;border-radius:18px;padding:20px;margin-bottom:18px}}h1{{margin-top:0}}
.status{{font-size:32px;font-weight:800;color:{'#15803d' if summary['gate_pass'] else '#b91c1c'}}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}
.check{{padding:12px;border-radius:10px}}.pass{{background:#dcfce7}}.fail{{background:#fee2e2}}img{{width:100%;height:auto}}pre{{white-space:pre-wrap;font-size:12px}}
</style></head><body><main><div class="hero"><h1>OCV・瞬時総抵抗・1-RC 同定の完全可視化</h1>
<p class="status">{'実運用昇格可能' if summary['gate_pass'] else '実運用昇格不可'}</p>
<p>固定40 mΩ/cellや負荷曲線勾配を使用せず、独立SoC付き休止・パルス試験だけを根拠にしたpack-levelモデルです。</p><div class="grid">{cards}</div></div>
{images}<section><h2>Machine-readable summary</h2><pre>{payload}</pre></section></main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8", newline="\n")


def identify(rest_csv: Path, pulse_csv: Path, output_dir: Path, limits: FitLimits) -> dict:  # [関数定義] identify の処理実行ブロック
    if not 0.0 <= limits.operational_soc_min < limits.operational_soc_max <= 1.0:
        raise BatteryEvidenceError("operational SoC bounds must satisfy 0 <= min < max <= 1")
    if limits.maximum_soc_boundary_gap < 0.0 or limits.edge_validation_band <= 0.0:
        raise BatteryEvidenceError("SoC boundary gap must be nonnegative and edge band must be positive")
    if (
        limits.r0_high_soc_nonincreasing_from is not None
        and not limits.operational_soc_min
        <= limits.r0_high_soc_nonincreasing_from
        < limits.operational_soc_max
    ):
        raise BatteryEvidenceError(
            "R0 high-SoC monotonic threshold must lie inside the operational SoC range"
        )
    rest = load_rest_data(rest_csv)
    pulse = load_pulse_data(pulse_csv)
    ocv, ocv_info = fit_ocv_curve(rest, limits)
    pulse_points, rejected = fit_pulse_tests(pulse, limits)
    detail_lookup = {str(test_id): group for test_id, group in pulse.groupby("test_id", sort=False)}
    pulse_details = [_fit_single_pulse(detail_lookup[row.test_id], limits) for row in pulse_points.itertuples()]
    train = pulse_points[pulse_points["split"] == "train"]
    validation = pulse_points[pulse_points["split"] == "validation"]
    soc_grid = np.linspace(limits.operational_soc_min, limits.operational_soc_max, 21)
    train_temp_min = float(train["temp_c"].min())
    train_temp_max = float(train["temp_c"].max())
    interior_temp_grid = np.arange(
        math.ceil(train_temp_min / 5.0) * 5.0,
        math.floor(train_temp_max / 5.0) * 5.0 + 0.1,
        5.0,
    )
    temp_grid = np.unique(np.concatenate(([train_temp_min], interior_temp_grid, [train_temp_max])))
    r0, r0_info = fit_positive_surface(
        pulse_points,
        "r0_total_ohm",
        soc_grid,
        temp_grid,
        limits,
        high_soc_nonincreasing_from=limits.r0_high_soc_nonincreasing_from,
        temperature_nonincreasing=limits.enforce_r0_temperature_nonincreasing,
    )
    r1, r1_info = fit_positive_surface(pulse_points, "r1_ohm", soc_grid, temp_grid, limits)
    tau, tau_info = fit_positive_surface(pulse_points, "tau_sec", soc_grid, temp_grid, limits)
    validation_voltage_rmse = float(np.sqrt(np.mean(validation["voltage_rmse_v"] ** 2))) if len(validation) else math.nan
    validation_voltage_normalized_rmse = (
        float(np.sqrt(np.mean(validation["voltage_normalized_rmse"] ** 2)))
        if len(validation)
        else math.nan
    )
    soc_span = float(train["soc_reference"].max() - train["soc_reference"].min()) if len(train) else 0.0
    temp_span = float(train["temp_c"].max() - train["temp_c"].min()) if len(train) else 0.0
    train_soc_min = float(train["soc_reference"].min()) if len(train) else math.nan
    train_soc_max = float(train["soc_reference"].max()) if len(train) else math.nan
    r0_low_edge = r0_info["edge_validation"]["low_soc"]
    r0_high_edge = r0_info["edge_validation"]["high_soc"]
    source_hashes = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (rest_csv, pulse_csv)
    }
    checks = {
        "independent_soc_only": bool(
            set(rest["soc_reference_method"]).issubset(INDEPENDENT_SOC_METHODS)
            and set(pulse["soc_reference_method"]).issubset(INDEPENDENT_SOC_METHODS)
        ),
        "rest_duration_adequate": bool((rest["rest_duration_sec"] >= limits.minimum_rest_sec).all()),
        "rest_equilibrium_slope": bool(
            (rest["rest_voltage_slope_uv_per_s"].abs() <= limits.maximum_rest_voltage_slope_uv_per_s).all()
        ),
        "minimum_training_pulses": len(train) >= limits.minimum_train_tests,
        "minimum_validation_pulses": len(validation) >= limits.minimum_validation_tests,
        "soc_coverage": soc_span >= limits.minimum_soc_span,
        "operational_soc_boundary_coverage": bool(
            train_soc_min <= limits.operational_soc_min + limits.maximum_soc_boundary_gap + 1.0e-12
            and train_soc_max >= limits.operational_soc_max - limits.maximum_soc_boundary_gap - 1.0e-12
        ),
        "temperature_coverage": temp_span >= limits.minimum_temp_span_c,
        "ocv_holdout_available": bool(
            int(ocv_info["validation_count"]) >= 2
            and np.isfinite(ocv_info["validation_normalized_rmse"])
            and ocv_info["validation_normalized_rmse"] <= limits.maximum_validation_normalized_rmse
        ),
        "pulse_voltage_holdout_rmse": bool(
            np.isfinite(validation_voltage_normalized_rmse)
            and validation_voltage_normalized_rmse <= limits.maximum_validation_normalized_rmse
        ),
        "r0_surface_holdout": bool(
            np.isfinite(r0_info["validation_normalized_rmse"])
            and r0_info["validation_normalized_rmse"] <= limits.maximum_validation_normalized_rmse
        ),
        "r0_low_soc_edge_holdout": bool(
            r0_low_edge["count"] >= limits.minimum_edge_validation_tests
            and np.isfinite(r0_low_edge["normalized_rmse"])
            and r0_low_edge["normalized_rmse"] <= limits.maximum_validation_normalized_rmse
        ),
        "r0_high_soc_edge_holdout": bool(
            r0_high_edge["count"] >= limits.minimum_edge_validation_tests
            and np.isfinite(r0_high_edge["normalized_rmse"])
            and r0_high_edge["normalized_rmse"] <= limits.maximum_validation_normalized_rmse
        ),
        "r0_direction_not_imposed_by_prior": bool(
            limits.r0_high_soc_nonincreasing_from is None
            and not limits.enforce_r0_temperature_nonincreasing
        ),
        "passivity": bool((r0.to_numpy() > 0).all() and (r1.to_numpy() >= 0).all() and (tau.to_numpy() > 0).all()),
    }
    summary = {
        "schema_version": 1,
        "model_equations": {
            "terminal_voltage": "Vt = Uocv(z) - I*R0_total(z,T) - V1",
            "polarization": "dV1/dt = -V1/tau(z,T) + R1(z,T)*I/tau(z,T)",
            "current_sign": "positive discharge",
        },
        "r0_definition": "pack two-terminal instantaneous total resistance; not decomposed into cell and wiring terms",
        "fixed_cell_resistance_prior_used": False,
        "loaded_voltage_slope_used_as_r0": False,
        "source_sha256": source_hashes,
        "ocv_fit": ocv_info,
        "pulse_count": int(len(pulse_points)),
        "rejected_pulses": rejected,
        "validation_voltage_rmse_v": validation_voltage_rmse,
        "validation_voltage_normalized_rmse": validation_voltage_normalized_rmse,
        "acceptance_limits": {
            **FitLimits().__dict__,
            **limits.__dict__,
            "normalized_rmse_interpretation": (
                "dimensionless residual divided by declared measurement-derived uncertainty; "
                "the default limit is a configurable three-sigma engineering adoption rule, not a battery coefficient"
            ),
        },
        "soc_span_train": soc_span,
        "temperature_span_train_c": temp_span,
        "operational_soc_range": [
            float(limits.operational_soc_min),
            float(limits.operational_soc_max),
        ],
        "map_domain_policy": (
            "The quadratic is evaluated only inside train SoC/temperature support. "
            "Operational grid points outside that support use a constant nearest-edge value; "
            "promotion additionally requires train proximity and independent validation at both SoC edges."
        ),
        "surface_fits": {"r0": r0_info, "r1": r1_info, "tau": tau_info},
        "checks": checks,
        "gate_pass": bool(all(checks.values())),
        "proof_scope": (
            "structural passivity and independent held-out agreement within measured "
            "SoC-temperature-current coverage; R0 slope signs are learned rather than imposed, "
            "and this is not a proof outside the measured domain"
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    ocv.to_csv(output_dir / "ocv_soc_curve_identified.csv", index=False)
    r0.to_csv(output_dir / "R0_total_T_by_soc_identified.csv")
    r1.to_csv(output_dir / "R1_T_by_soc_identified.csv")
    tau.to_csv(output_dir / "tau_T_by_soc_identified.csv")
    pulse_points.to_csv(output_dir / "pulse_fit_points.csv", index=False)
    (output_dir / "battery_ecm_identification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    figures = build_report_figures(rest, pulse_points, pulse_details, ocv, r0, r1, tau, summary)
    write_html_report(output_dir / "OCV_R0_1RC_complete_visual_report.html", figures, summary)
    return summary                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def main() -> None:                                                # [関数定義] main の処理実行ブロック
    parser = argparse.ArgumentParser()
    parser.add_argument("--rest-csv", required=True)               # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--pulse-csv", required=True)              # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--output-dir", required=True)             # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--minimum-rest-sec", type=float, default=1800.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--maximum-rest-current-a", type=float, default=0.25)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--maximum-rest-voltage-slope-uv-per-s", type=float, default=10.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--minimum-current-step-a", type=float, default=3.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--maximum-first-sample-delay-sec", type=float, default=0.25)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--maximum-validation-normalized-rmse", type=float, default=3.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--operational-soc-min", type=float, default=0.05)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--operational-soc-max", type=float, default=0.95)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--maximum-soc-boundary-gap", type=float, default=0.05)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--edge-validation-band", type=float, default=0.10)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--minimum-edge-validation-tests", type=int, default=1)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument(                                           # [CLI引数] コマンドライン実行引数の定義
        "--r0-high-soc-nonincreasing-from",
        type=float,
        default=None,
        help="Diagnostic-only legacy hypothesis; omitted for release identification.",
    )
    parser.add_argument(                                           # [CLI引数] コマンドライン実行引数の定義
        "--enforce-r0-temperature-nonincreasing",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Diagnostic-only legacy hypothesis; disabled for release identification.",
    )
    args = parser.parse_args()
    limits = FitLimits(
        minimum_rest_sec=float(args.minimum_rest_sec),
        maximum_rest_current_a=float(args.maximum_rest_current_a),
        maximum_rest_voltage_slope_uv_per_s=float(args.maximum_rest_voltage_slope_uv_per_s),
        minimum_current_step_a=float(args.minimum_current_step_a),
        maximum_first_sample_delay_sec=float(args.maximum_first_sample_delay_sec),
        maximum_validation_normalized_rmse=float(args.maximum_validation_normalized_rmse),
        operational_soc_min=float(args.operational_soc_min),
        operational_soc_max=float(args.operational_soc_max),
        maximum_soc_boundary_gap=float(args.maximum_soc_boundary_gap),
        edge_validation_band=float(args.edge_validation_band),
        minimum_edge_validation_tests=int(args.minimum_edge_validation_tests),
        r0_high_soc_nonincreasing_from=(
            None
            if args.r0_high_soc_nonincreasing_from is None
            else float(args.r0_high_soc_nonincreasing_from)
        ),
        enforce_r0_temperature_nonincreasing=bool(args.enforce_r0_temperature_nonincreasing),
    )
    summary = identify(Path(args.rest_csv), Path(args.pulse_csv), Path(args.output_dir), limits)
    print(json.dumps({"gate_pass": summary["gate_pass"], "output_dir": args.output_dir}, ensure_ascii=False))
    if not summary["gate_pass"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
