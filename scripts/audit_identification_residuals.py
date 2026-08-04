"""Audit replay residual structure and long-horizon SoC divergence."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if os.fspath(ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT))

from mpc_solarcar.utils_maps import read_Rint_map

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
        "text.color": "black",
        "axes.labelcolor": "black",
        "axes.edgecolor": "black",
        "xtick.color": "black",
        "ytick.color": "black",
    }
)


REGIMES = {
    "speed_kmh": [-np.inf, 40.0, 55.0, 65.0, 75.0, 90.0, np.inf],
    "slope_pct": [-np.inf, -2.0, -0.5, 0.5, 2.0, np.inf],
    "accel_ms2": [-np.inf, -0.10, -0.03, 0.03, 0.10, np.inf],
    "headwind_ms": [-np.inf, -2.0, 0.0, 2.0, 4.0, np.inf],
}

VOLTAGE_SOC_BINS = [-np.inf, 0.20, 0.40, 0.60, 0.80, 0.85, 0.90, 0.95, np.inf]
VOLTAGE_CURRENT_BINS_A = [-np.inf, -10.0, 0.0, 5.0, 10.0, 20.0, 30.0, 40.0, np.inf]

WEATHER_DAILY_COLUMNS = [
    "day",
    "daylight_sample_count",
    "ghi_mean_wm2",
    "ghi_median_wm2",
    "ghi_p90_wm2",
    "ghi_max_wm2",
    "ambient_mean_c",
    "ambient_min_c",
    "pv_observed_mean_w",
    "pv_predicted_mean_w",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vehicle-replay", type=Path, required=True)
    parser.add_argument("--battery-replay", type=Path, required=True)
    parser.add_argument("--end-to-end-replay", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--rint-map", type=Path)
    parser.add_argument("--rint-scale", type=float)
    parser.add_argument("--r-line-ohm", type=float)
    parser.add_argument("--r-polarization-ohm", type=float)
    parser.add_argument("--high-soc-threshold", type=float, default=0.85)
    return parser.parse_args()


def rmse(values: pd.Series) -> float:
    array = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
    return float(np.sqrt(np.mean(np.square(array)))) if len(array) else float("nan")


def clean_power_rows(frame: pd.DataFrame) -> pd.DataFrame:
    excluded = frame.get("exclude_power_fit", pd.Series(False, index=frame.index))
    if excluded.dtype != bool:
        excluded = excluded.astype(str).str.lower().isin({"true", "1", "yes"})
    speed = pd.to_numeric(frame.get("speed_kmh"), errors="coerce")
    observed = pd.to_numeric(frame.get("battery_power_w_obs"), errors="coerce")
    predicted = pd.to_numeric(frame.get("battery_power_w_pred"), errors="coerce")
    mask = (~excluded.fillna(True)) & (speed >= 12.0) & observed.notna() & predicted.notna()
    out = frame.loc[mask].copy()
    out["power_residual_w"] = observed.loc[mask] - predicted.loc[mask]
    return out.sort_values("time_utc").reset_index(drop=True)


def all_clean_power_residual(frame: pd.DataFrame) -> pd.Series:
    excluded = frame.get("exclude_power_fit", pd.Series(False, index=frame.index))
    if excluded.dtype != bool:
        excluded = excluded.astype(str).str.lower().isin({"true", "1", "yes"})
    observed = pd.to_numeric(frame.get("battery_power_w_obs"), errors="coerce")
    predicted = pd.to_numeric(frame.get("battery_power_w_pred"), errors="coerce")
    mask = (~excluded.fillna(True)) & observed.notna() & predicted.notna()
    return observed.loc[mask] - predicted.loc[mask]


def exclusion_mask(frame: pd.DataFrame, column: str) -> pd.Series:
    excluded = frame.get(column, pd.Series(False, index=frame.index))
    if excluded.dtype != bool:
        excluded = excluded.astype(str).str.lower().isin({"true", "1", "yes"})
    return excluded.fillna(True).astype(bool)


def clean_voltage_rows(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "battery_voltage_v_obs",
        "battery_voltage_v_pred",
        "battery_current_a_obs",
        "soc_pred",
    }
    if not required.issubset(frame.columns):
        return pd.DataFrame()
    work = frame.copy()
    for column in required:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    mask = (
        (~exclusion_mask(work, "exclude_voltage_fit"))
        & work["battery_voltage_v_obs"].notna()
        & work["battery_voltage_v_pred"].notna()
        & work["battery_current_a_obs"].notna()
        & work["soc_pred"].notna()
    )
    work = work.loc[mask].copy()
    work["voltage_residual_v"] = (
        work["battery_voltage_v_obs"] - work["battery_voltage_v_pred"]
    )
    return work.reset_index(drop=True)


def voltage_soc_current_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    """Report voltage error without hiding SoC-current interaction in one RMSE."""
    work = clean_voltage_rows(frame)
    columns = [
        "group",
        "soc_bin",
        "current_bin_a",
        "sample_count",
        "bias_v",
        "mae_v",
        "rmse_v",
    ]
    if work.empty:
        return pd.DataFrame(columns=columns)
    work["soc_bin"] = pd.cut(
        work["soc_pred"], VOLTAGE_SOC_BINS, include_lowest=True
    )
    work["current_bin_a"] = pd.cut(
        work["battery_current_a_obs"], VOLTAGE_CURRENT_BINS_A, include_lowest=True
    )
    rows: list[dict[str, object]] = []

    def append(group: str, soc_bin: str, current_bin: str, values: pd.Series) -> None:
        finite = pd.to_numeric(values, errors="coerce").dropna()
        rows.append(
            {
                "group": group,
                "soc_bin": soc_bin,
                "current_bin_a": current_bin,
                "sample_count": int(len(finite)),
                "bias_v": float(finite.mean()),
                "mae_v": float(finite.abs().mean()),
                "rmse_v": rmse(finite),
            }
        )

    append("all", "all", "all", work["voltage_residual_v"])
    for label, group in work.groupby("soc_bin", observed=True):
        append("soc", str(label), "all", group["voltage_residual_v"])
    for label, group in work.groupby("current_bin_a", observed=True):
        append("current", "all", str(label), group["voltage_residual_v"])
    for (soc_label, current_label), group in work.groupby(
        ["soc_bin", "current_bin_a"], observed=True
    ):
        append(
            "soc_x_current",
            str(soc_label),
            str(current_label),
            group["voltage_residual_v"],
        )
    return pd.DataFrame(rows, columns=columns)


def _bilinear_values(
    x_grid: np.ndarray,
    y_grid: np.ndarray,
    values: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
) -> np.ndarray:
    x_grid = np.asarray(x_grid, dtype=float)
    y_grid = np.asarray(y_grid, dtype=float)
    values = np.asarray(values, dtype=float)
    x = np.clip(np.asarray(x, dtype=float), x_grid[0], x_grid[-1])
    y = np.clip(np.asarray(y, dtype=float), y_grid[0], y_grid[-1])
    i = np.clip(np.searchsorted(x_grid, x, side="right") - 1, 0, len(x_grid) - 2)
    j = np.clip(np.searchsorted(y_grid, y, side="right") - 1, 0, len(y_grid) - 2)
    x0 = x_grid[i]
    x1 = x_grid[i + 1]
    y0 = y_grid[j]
    y1 = y_grid[j + 1]
    wx = np.divide(x - x0, x1 - x0, out=np.zeros_like(x), where=x1 != x0)
    wy = np.divide(y - y0, y1 - y0, out=np.zeros_like(y), where=y1 != y0)
    return (
        (1.0 - wx) * (1.0 - wy) * values[i, j]
        + wx * (1.0 - wy) * values[i + 1, j]
        + (1.0 - wx) * wy * values[i, j + 1]
        + wx * wy * values[i + 1, j + 1]
    )


def high_soc_rint_counterfactual(
    frame: pd.DataFrame,
    rint_map_path: Path,
    *,
    rint_scale: float,
    r_line_ohm: float,
    r_polarization_ohm: float,
    high_soc_threshold: float,
    output_dir: Path,
) -> dict[str, object]:
    """Locally flatten the Rint map above a threshold without refitting states.

    This is a same-current, same-SoC structural diagnostic.  It deliberately
    does not claim the counterfactual is an identified replacement model.
    """
    required = {
        "soc_pred",
        "Tamb_C",
        "battery_current_a_pred",
        "battery_voltage_v_obs",
        "battery_voltage_v_pred",
    }
    if not required.issubset(frame.columns):
        return {
            "available": False,
            "reason": f"missing replay columns: {sorted(required.difference(frame.columns))}",
        }
    map_path = Path(rint_map_path).resolve()
    if not map_path.is_file():
        return {"available": False, "reason": f"Rint map does not exist: {map_path}"}
    temperature_grid, soc_grid, rint_map = read_Rint_map(map_path)
    threshold = float(np.clip(high_soc_threshold, soc_grid[0], soc_grid[-1]))
    work = frame.copy()
    for column in required:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    current = work["battery_current_a_pred"].to_numpy(dtype=float)
    soc = work["soc_pred"].to_numpy(dtype=float)
    temperature = work["Tamb_C"].to_numpy(dtype=float)
    r_map_original = _bilinear_values(
        temperature_grid, soc_grid, rint_map, temperature, soc
    )
    r_map_flat = _bilinear_values(
        temperature_grid,
        soc_grid,
        rint_map,
        temperature,
        np.minimum(soc, threshold),
    )
    r_total_original = float(rint_scale) * r_map_original + float(r_line_ohm)
    r_total_flat = float(rint_scale) * r_map_flat + float(r_line_ohm)
    polarization_v = pd.to_numeric(
        work.get("battery_polarization_v", pd.Series(0.0, index=work.index)),
        errors="coerce",
    ).fillna(0.0).to_numpy(dtype=float)
    static_pred = pd.to_numeric(
        work.get(
            "battery_voltage_v_pred_static",
            work["battery_voltage_v_pred"] + polarization_v,
        ),
        errors="coerce",
    ).to_numpy(dtype=float)
    ocv_reconstructed = static_pred + current * r_total_original
    flat_static_pred = ocv_reconstructed - current * r_total_flat
    flat_pred = flat_static_pred - polarization_v
    work["rint_map_original_ohm"] = r_map_original
    work["rint_map_flat_ohm"] = r_map_flat
    work["r_total_static_original_ohm"] = r_total_original
    work["r_total_static_flat_ohm"] = r_total_flat
    work["battery_voltage_v_pred_high_soc_flat"] = flat_pred
    work["voltage_residual_original_v"] = (
        work["battery_voltage_v_obs"] - work["battery_voltage_v_pred"]
    )
    work["voltage_residual_high_soc_flat_v"] = (
        work["battery_voltage_v_obs"] - work["battery_voltage_v_pred_high_soc_flat"]
    )
    valid = (
        (~exclusion_mask(work, "exclude_voltage_fit"))
        & (work["soc_pred"] >= threshold)
        & np.isfinite(work["voltage_residual_original_v"])
        & np.isfinite(work["voltage_residual_high_soc_flat_v"])
        & np.isfinite(work["battery_current_a_pred"])
    )
    high = work.loc[valid].copy()
    trace_columns = [
        column
        for column in (
            "time_utc",
            "day",
            "s_km",
            "soc_pred",
            "Tamb_C",
            "battery_current_a_obs",
            "battery_current_a_pred",
            "battery_voltage_v_obs",
            "battery_voltage_v_pred",
            "battery_voltage_v_pred_high_soc_flat",
            "rint_map_original_ohm",
            "rint_map_flat_ohm",
            "r_total_static_original_ohm",
            "r_total_static_flat_ohm",
            "voltage_residual_original_v",
            "voltage_residual_high_soc_flat_v",
        )
        if column in high.columns
    ]
    high[trace_columns].to_csv(
        output_dir / "high_soc_rint_counterfactual_trace.csv", index=False
    )
    flat_map = np.array(rint_map, dtype=float, copy=True)
    threshold_values = _bilinear_values(
        temperature_grid,
        soc_grid,
        rint_map,
        temperature_grid,
        np.full(len(temperature_grid), threshold),
    )
    flat_map[:, soc_grid > threshold] = threshold_values[:, None]
    pd.DataFrame(flat_map, index=temperature_grid, columns=soc_grid).to_csv(
        output_dir / "Rint_T_by_soc_high_soc_flat_counterfactual.csv"
    )
    original_residual = high["voltage_residual_original_v"]
    flat_residual = high["voltage_residual_high_soc_flat_v"]
    original_25c_threshold = float(
        _bilinear_values(
            temperature_grid,
            soc_grid,
            rint_map,
            np.asarray([25.0]),
            np.asarray([threshold]),
        )[0]
    )
    original_25c_max_soc = float(
        _bilinear_values(
            temperature_grid,
            soc_grid,
            rint_map,
            np.asarray([25.0]),
            np.asarray([soc_grid[-1]]),
        )[0]
    )
    return {
        "available": True,
        "validation_status": "diagnostic_only_not_an_identified_replacement",
        "method": "same-current and same-SoC local replay counterfactual; Rint map is held flat above the threshold while OCV, line resistance, polarization voltage, and all fitted states remain unchanged",
        "rint_map": str(map_path),
        "high_soc_threshold": threshold,
        "high_soc_sample_count": int(len(high)),
        "rint_scale": float(rint_scale),
        "r_line_ohm": float(r_line_ohm),
        "r_polarization_ohm_reported_only": float(r_polarization_ohm),
        "rint_map_25c_at_threshold_ohm": original_25c_threshold,
        "rint_map_25c_at_max_soc_ohm": original_25c_max_soc,
        "rint_map_25c_edge_ratio": original_25c_max_soc / max(original_25c_threshold, 1.0e-12),
        "original_voltage_bias_v": float(original_residual.mean()),
        "original_voltage_mae_v": float(original_residual.abs().mean()),
        "original_voltage_rmse_v": rmse(original_residual),
        "flat_voltage_bias_v": float(flat_residual.mean()),
        "flat_voltage_mae_v": float(flat_residual.abs().mean()),
        "flat_voltage_rmse_v": rmse(flat_residual),
        "flat_minus_original_rmse_v": rmse(flat_residual) - rmse(original_residual),
        "interpretation_warning": "an RMSE change here cannot validate Rint(z); independent multi-current pulse data and a full refit/replay are required",
    }


def regime_metrics(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def append_group(group_name: str, label: str, values: pd.Series) -> None:
        rows.append(
            {
                "group": group_name,
                "bin": label,
                "sample_count": int(values.notna().sum()),
                "bias_w": float(values.mean()),
                "mae_w": float(values.abs().mean()),
                "rmse_w": rmse(values),
            }
        )

    if "day" in frame:
        for label, group in frame.groupby("day", observed=True):
            append_group("day", str(label), group["power_residual_w"])
    for column, bins in REGIMES.items():
        if column not in frame:
            continue
        categories = pd.cut(
            pd.to_numeric(frame[column], errors="coerce"), bins=bins, include_lowest=True
        )
        for label, group in frame.groupby(categories, observed=True):
            append_group(column, str(label), group["power_residual_w"])
    return pd.DataFrame(rows)


def weather_and_cruise_metrics(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float | int]]:
    """Summarize weather plausibility and gross vehicle load near 70 km/h.

    Battery power in the replay is net of PV.  Adding the synchronized PV
    channel reconstructs the gross vehicle-side electrical demand used for the
    team's approximately 800 W at 70 km/h engineering cross-check.
    """
    daily = pd.DataFrame(columns=WEATHER_DAILY_COLUMNS)
    required_weather = {
        "day",
        "GHI_archive",
        "Tamb_C",
        "solar_power_w_obs",
        "solar_power_w_model",
    }
    if required_weather.issubset(frame.columns):
        work = frame.copy()
        for column in required_weather.difference({"day"}):
            work[column] = pd.to_numeric(work[column], errors="coerce")
        work["day"] = pd.to_numeric(work["day"], errors="coerce")
        daylight = work[work["GHI_archive"] > 20.0].copy()
        rows: list[dict[str, float | int]] = []
        for day, group in daylight.groupby("day", observed=True):
            rows.append(
                {
                    "day": int(day),
                    "daylight_sample_count": int(len(group)),
                    "ghi_mean_wm2": float(group["GHI_archive"].mean()),
                    "ghi_median_wm2": float(group["GHI_archive"].median()),
                    "ghi_p90_wm2": float(group["GHI_archive"].quantile(0.90)),
                    "ghi_max_wm2": float(group["GHI_archive"].max()),
                    "ambient_mean_c": float(group["Tamb_C"].mean()),
                    "ambient_min_c": float(group["Tamb_C"].min()),
                    "pv_observed_mean_w": float(group["solar_power_w_obs"].mean()),
                    "pv_predicted_mean_w": float(group["solar_power_w_model"].mean()),
                }
            )
        daily = pd.DataFrame(rows, columns=WEATHER_DAILY_COLUMNS)

    cruise_summary: dict[str, float | int] = {"cruise_70kmh_sample_count": 0}
    required_cruise = {
        "speed_kmh",
        "battery_power_w_obs",
        "battery_power_w_pred",
        "solar_power_w_obs",
        "solar_power_w_model",
    }
    if required_cruise.issubset(frame.columns):
        speed = pd.to_numeric(frame["speed_kmh"], errors="coerce")
        excluded = frame.get("exclude_power_fit", pd.Series(False, index=frame.index))
        if excluded.dtype != bool:
            excluded = excluded.astype(str).str.lower().isin({"true", "1", "yes"})
        cruise = frame.loc[(~excluded.fillna(True)) & speed.between(68.0, 72.0)].copy()
        for column in required_cruise.difference({"speed_kmh"}):
            cruise[column] = pd.to_numeric(cruise[column], errors="coerce")
        cruise["gross_vehicle_power_w_obs"] = (
            cruise["battery_power_w_obs"] + cruise["solar_power_w_obs"]
        )
        cruise["gross_vehicle_power_w_pred"] = (
            cruise["battery_power_w_pred"] + cruise["solar_power_w_model"]
        )
        cruise = cruise.dropna(
            subset=["gross_vehicle_power_w_obs", "gross_vehicle_power_w_pred"]
        )
        residual = (
            cruise["gross_vehicle_power_w_obs"]
            - cruise["gross_vehicle_power_w_pred"]
        )
        cruise_summary = {
            "cruise_70kmh_sample_count": int(len(cruise)),
            "cruise_70kmh_gross_vehicle_power_obs_mean_w": float(
                cruise["gross_vehicle_power_w_obs"].mean()
            ),
            "cruise_70kmh_gross_vehicle_power_pred_mean_w": float(
                cruise["gross_vehicle_power_w_pred"].mean()
            ),
            "cruise_70kmh_gross_vehicle_power_obs_median_w": float(
                cruise["gross_vehicle_power_w_obs"].median()
            ),
            "cruise_70kmh_gross_vehicle_power_pred_median_w": float(
                cruise["gross_vehicle_power_w_pred"].median()
            ),
            "cruise_70kmh_gross_vehicle_power_rmse_w": rmse(residual),
        }
    return daily, cruise_summary


def align_soc(vehicle: pd.DataFrame, battery: pd.DataFrame, end_to_end: pd.DataFrame | None) -> pd.DataFrame:
    columns = [column for column in ("time_utc", "s_km", "day", "soc_pred") if column in vehicle]
    aligned = vehicle[columns].copy().rename(columns={"soc_pred": "vehicle_soc"})
    aligned["time_utc"] = pd.to_datetime(aligned["time_utc"], format="mixed", utc=True)
    battery_use = battery[["time_utc", "soc_pred"]].copy().rename(columns={"soc_pred": "battery_conditional_soc"})
    battery_use["time_utc"] = pd.to_datetime(battery_use["time_utc"], format="mixed", utc=True)
    aligned = aligned.merge(battery_use, on="time_utc", how="inner", validate="one_to_one")
    if end_to_end is not None:
        end_use = end_to_end[["time_utc", "soc_pred"]].copy().rename(columns={"soc_pred": "end_to_end_soc"})
        end_use["time_utc"] = pd.to_datetime(end_use["time_utc"], format="mixed", utc=True)
        aligned = aligned.merge(end_use, on="time_utc", how="left", validate="one_to_one")
    aligned["vehicle_minus_battery_soc"] = (
        pd.to_numeric(aligned["vehicle_soc"], errors="coerce")
        - pd.to_numeric(aligned["battery_conditional_soc"], errors="coerce")
    )
    if "end_to_end_soc" in aligned:
        aligned["end_to_end_minus_battery_soc"] = (
            pd.to_numeric(aligned["end_to_end_soc"], errors="coerce")
            - pd.to_numeric(aligned["battery_conditional_soc"], errors="coerce")
        )
    return aligned


def threshold_crossings(aligned: pd.DataFrame, column: str) -> dict[str, object]:
    result: dict[str, object] = {}
    absolute = pd.to_numeric(aligned[column], errors="coerce").abs()
    for threshold in (0.02, 0.05, 0.10):
        indices = np.flatnonzero(
            absolute.to_numpy(dtype=float) >= threshold - 1.0e-12
        )
        key = f"first_abs_{int(threshold * 100)}pct"
        if not len(indices):
            result[key] = None
            continue
        row = aligned.iloc[int(indices[0])]
        result[key] = {
            "time_utc": row["time_utc"].isoformat(),
            "s_km": float(row.get("s_km", float("nan"))),
            "day": int(row.get("day", 0)),
            "signed_soc_difference": float(row[column]),
        }
    result["terminal_signed_soc_difference"] = float(aligned[column].dropna().iloc[-1])
    return result


def plot_audit(clean: pd.DataFrame, aligned: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11.0, 7.2), constrained_layout=True)
    axes[0].scatter(clean["s_km"], clean["power_residual_w"], s=2, alpha=0.16, color="#174a5b")
    residual_by_time = pd.Series(
        clean["power_residual_w"].to_numpy(dtype=float),
        index=pd.to_datetime(clean["time_utc"], format="mixed", utc=True),
    )
    rolling = residual_by_time.rolling(
        "120s", center=True, min_periods=4
    ).mean().to_numpy(copy=True)
    time_gap = residual_by_time.index.to_series().diff().dt.total_seconds().to_numpy() > 300.0
    distance_gap = pd.to_numeric(clean["s_km"], errors="coerce").diff().to_numpy() > 10.0
    rolling[time_gap | distance_gap] = np.nan
    axes[0].plot(clean["s_km"], rolling, color="#b23a2b", linewidth=1.2, label="120 s mean")
    axes[0].axhline(0.0, color="black", linewidth=0.7)
    axes[0].set_ylabel("observed - predicted [W]")
    axes[0].set_xlabel("race distance [km]")
    axes[0].legend(loc="upper right")
    first_day = True
    for _, day_frame in aligned.groupby("day", observed=True):
        axes[1].plot(
            day_frame["s_km"],
            day_frame["vehicle_minus_battery_soc"],
            color="#1f77b4",
            label="vehicle - battery conditional" if first_day else None,
        )
        if "end_to_end_minus_battery_soc" in day_frame:
            axes[1].plot(
                day_frame["s_km"],
                day_frame["end_to_end_minus_battery_soc"],
                color="#ff7f0e",
                label="end-to-end - battery conditional" if first_day else None,
            )
        first_day = False
    for threshold in (-0.10, -0.05, -0.02, 0.02, 0.05, 0.10):
        axes[1].axhline(threshold, color="#777777", linewidth=0.4, linestyle="--")
    axes[1].set_ylabel("SoC difference [-]")
    axes[1].set_xlabel("race distance [km]")
    axes[1].legend(loc="best")
    fig.savefig(output, dpi=180)
    plt.close(fig)


def rint_context_from_profile(profile_path: Path) -> dict[str, object]:
    profile_path = Path(profile_path).resolve()
    with profile_path.open("r", encoding="utf-8") as handle:
        cfg = yaml.safe_load(handle) or {}
    raw_map = str((cfg.get("paths", {}) or {}).get("rint_map", "")).strip()
    candidates = []
    if raw_map:
        raw_path = Path(raw_map)
        candidates = (
            [raw_path]
            if raw_path.is_absolute()
            else [(profile_path.parent / raw_path).resolve(), (ROOT / raw_path).resolve()]
        )
    map_path = next((path for path in candidates if path.is_file()), candidates[0] if candidates else None)
    model = cfg.get("model", {}) or {}
    return {
        "rint_map_path": map_path,
        "rint_scale": float(model.get("rint_scale", 1.0)),
        "r_line_ohm": float(model.get("r_line_ohm", 0.0)),
        "r_polarization_ohm": float(model.get("r_polarization_ohm", 0.0)),
    }


def run_audit(
    vehicle_path: Path,
    battery_path: Path,
    end_path: Path | None,
    output_dir: Path,
    *,
    rint_map_path: Path | None = None,
    rint_scale: float = 1.0,
    r_line_ohm: float = 0.0,
    r_polarization_ohm: float = 0.0,
    high_soc_threshold: float = 0.85,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    vehicle = pd.read_csv(vehicle_path, low_memory=False)
    battery = pd.read_csv(battery_path, low_memory=False)
    end_to_end = pd.read_csv(end_path, low_memory=False) if end_path else None
    clean = clean_power_rows(vehicle)
    all_clean_residual = all_clean_power_residual(vehicle)
    regimes = regime_metrics(clean)
    voltage_regimes = voltage_soc_current_metrics(battery)
    # Weather/PV diagnostics must use the independent end-to-end prediction.
    # The battery-conditioned replay intentionally substitutes measured PV and
    # would make observed and predicted solar columns identical by design.
    weather_source = end_to_end if end_to_end is not None else vehicle
    weather_daily, _ = weather_and_cruise_metrics(weather_source)
    _, cruise_summary = weather_and_cruise_metrics(vehicle)
    aligned = align_soc(vehicle, battery, end_to_end)
    regimes.to_csv(output_dir / "residual_regime_metrics.csv", index=False)
    voltage_regimes.to_csv(
        output_dir / "voltage_soc_current_metrics.csv", index=False
    )
    weather_daily.to_csv(output_dir / "weather_daily_metrics.csv", index=False)
    aligned.to_csv(output_dir / "soc_divergence_trace.csv", index=False)
    plot_audit(clean, aligned, output_dir / "residual_soc_audit.png")
    correlations = {}
    for column in REGIMES:
        if column in clean:
            correlations[column] = float(
                clean[["power_residual_w", column]].corr().iloc[0, 1]
            )
    payload: dict[str, object] = {
        "vehicle_replay": str(vehicle_path.resolve()),
        "battery_replay": str(battery_path.resolve()),
        "end_to_end_replay": str(end_path.resolve()) if end_path else None,
        "all_clean_sample_count": int(len(all_clean_residual)),
        "all_clean_power_bias_w": float(all_clean_residual.mean()),
        "all_clean_power_rmse_w": rmse(all_clean_residual),
        "moving_clean_sample_count": int(len(clean)),
        "moving_clean_power_bias_w": float(clean["power_residual_w"].mean()),
        "moving_clean_power_rmse_w": rmse(clean["power_residual_w"]),
        "residual_correlations": correlations,
        "largest_absolute_residual_correlation": (
            max(correlations, key=lambda key: abs(correlations[key])) if correlations else None
        ),
        "weather_daily_metrics": weather_daily.to_dict(orient="records"),
        "vehicle_soc_divergence": threshold_crossings(aligned, "vehicle_minus_battery_soc"),
        "voltage_soc_current_metrics_csv": str(
            (output_dir / "voltage_soc_current_metrics.csv").resolve()
        ),
    }
    if rint_map_path is not None:
        payload["high_soc_rint_counterfactual"] = high_soc_rint_counterfactual(
            battery,
            Path(rint_map_path),
            rint_scale=float(rint_scale),
            r_line_ohm=float(r_line_ohm),
            r_polarization_ohm=float(r_polarization_ohm),
            high_soc_threshold=float(high_soc_threshold),
            output_dir=output_dir,
        )
    else:
        payload["high_soc_rint_counterfactual"] = {
            "available": False,
            "reason": "Rint map was not supplied",
        }
    payload.update(cruise_summary)
    if "end_to_end_minus_battery_soc" in aligned:
        payload["end_to_end_soc_divergence"] = threshold_crossings(
            aligned, "end_to_end_minus_battery_soc"
        )
    (output_dir / "residual_audit.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return payload


def main() -> None:
    args = parse_args()
    context = {
        "rint_map_path": args.rint_map,
        "rint_scale": 1.0,
        "r_line_ohm": 0.0,
        "r_polarization_ohm": 0.0,
    }
    if args.profile is not None:
        context.update(rint_context_from_profile(args.profile))
    if args.rint_map is not None:
        context["rint_map_path"] = args.rint_map
    if args.rint_scale is not None:
        context["rint_scale"] = args.rint_scale
    if args.r_line_ohm is not None:
        context["r_line_ohm"] = args.r_line_ohm
    if args.r_polarization_ohm is not None:
        context["r_polarization_ohm"] = args.r_polarization_ohm
    payload = run_audit(
        args.vehicle_replay,
        args.battery_replay,
        args.end_to_end_replay,
        args.output_dir,
        rint_map_path=context["rint_map_path"],
        rint_scale=float(context["rint_scale"]),
        r_line_ohm=float(context["r_line_ohm"]),
        r_polarization_ohm=float(context["r_polarization_ohm"]),
        high_soc_threshold=float(args.high_soc_threshold),
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
