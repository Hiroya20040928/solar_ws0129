"""Build a PV-observation-conditioned weather grid for historical counterfactual replay.

This product is intentionally separate from an independent forecast.  It may be
used to replay the weather actually experienced in BWSC 2025, but never to score
forecast generalization or to initialize live operation.
"""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]

PHYSICAL_RADIATION_LIMITS_WM2 = {
    "GHI": 1200.0,
    "DNI": 1400.0,
    "DHI": 800.0,
    "POA_drive": 1200.0,
    "POA_stop_ideal": 1400.0,
}


def _time_column(frame: pd.DataFrame) -> str:
    for column in ("time", "time_utc"):
        if column in frame.columns:
            return column
    raise ValueError("weather grid must contain time or time_utc")


def build_observed_ratio_trace(
    observed: pd.DataFrame,
    *,
    minimum_speed_kmh: float = 12.0,
    minimum_archive_ghi_wm2: float = 50.0,
    resample_minutes: int = 10,
    reference_array_gain: float = 1.0,
) -> pd.DataFrame:
    """Return a robust time trace of effective/API irradiance ratio.

    Only moving, electrically healthy samples are used.  This avoids confusing
    manual stop-array tilt or a declared MPPT fault with atmospheric irradiance.
    """
    required = {
        "time_utc",
        "speed_kmh",
        "GHI_archive",
        "GHI_effective",
        "exclude_weather_fit",
    }
    missing = sorted(required - set(observed.columns))
    if missing:
        raise ValueError(f"observed replay is missing ratio fields: {missing}")
    work = observed.copy()
    work["time_utc"] = pd.to_datetime(work["time_utc"], format="mixed", utc=True, errors="coerce")
    archive = pd.to_numeric(work["GHI_archive"], errors="coerce")
    effective = pd.to_numeric(work["GHI_effective"], errors="coerce")
    speed = pd.to_numeric(work["speed_kmh"], errors="coerce")
    excluded = work["exclude_weather_fit"].fillna(True).astype(bool)
    valid = (
        work["time_utc"].notna()
        & (~excluded)
        & (speed >= float(minimum_speed_kmh))
        & (archive >= float(minimum_archive_ghi_wm2))
        & np.isfinite(effective)
        & (effective >= 0.0)
    )
    use = work.loc[valid, ["time_utc"]].copy()
    array_gain = max(float(reference_array_gain), 1.0e-6)
    # GHI_effective was inverted through the grounded base array.  Remove the
    # separately fitted healthy-array gain here so the historical weather
    # product contains atmospheric mismatch only; runtime applies panel_gain.
    use["ratio"] = np.clip(
        effective.loc[valid].to_numpy(dtype=float)
        / archive.loc[valid].to_numpy(dtype=float)
        / array_gain,
        0.05,
        1.50,
    )
    if len(use) < 20:
        raise ValueError("insufficient healthy moving samples for historical weather correction")
    trace = (
        use.set_index("time_utc")["ratio"]
        .resample(f"{max(1, int(resample_minutes))}min")
        .median()
        .dropna()
        .rolling(3, center=True, min_periods=1)
        .median()
        .rename("irradiance_ratio")
        .reset_index()
    )
    return trace


def ratio_at_grid_times(
    grid_time: pd.Series,
    trace: pd.DataFrame,
    *,
    post_observation_mean_reversion_hours: float = 3.0,
) -> np.ndarray:
    times = pd.to_datetime(grid_time, format="mixed", utc=True, errors="coerce")
    trace_time = pd.to_datetime(trace["time_utc"], format="mixed", utc=True, errors="coerce")
    trace_ratio = pd.to_numeric(trace["irradiance_ratio"], errors="coerce").to_numpy(dtype=float)
    valid_trace = trace_time.notna().to_numpy(dtype=bool) & np.isfinite(trace_ratio)
    if int(valid_trace.sum()) < 2:
        raise ValueError("historical irradiance ratio trace requires at least two timestamps")
    # Integer datetime values follow the array storage unit.  Pandas 2 may keep
    # parsed timestamps as datetime64[us], so dividing those integers by 1e9
    # made a three-hour decay roughly one thousand times too slow.  Normalize
    # explicitly to nanoseconds before constructing the SI-second axis.
    source_sec = (
        pd.DatetimeIndex(trace_time[valid_trace]).as_unit("ns").asi8.astype(float)
        / 1.0e9
    )
    source_ratio = trace_ratio[valid_trace]
    target_sec = pd.DatetimeIndex(times).as_unit("ns").asi8.astype(float) / 1.0e9
    ratio = np.interp(target_sec, source_sec, source_ratio, left=1.0, right=source_ratio[-1])
    after = target_sec > source_sec[-1]
    tau_sec = max(float(post_observation_mean_reversion_hours) * 3600.0, 1.0)
    ratio[after] = 1.0 + (source_ratio[-1] - 1.0) * np.exp(
        -(target_sec[after] - source_sec[-1]) / tau_sec
    )
    ratio[~times.notna().to_numpy(dtype=bool)] = 1.0
    return np.clip(ratio, 0.05, 1.50)


def correct_historical_weather_grid(
    grid: pd.DataFrame,
    trace: pd.DataFrame,
    *,
    tcell_gain_c_per_wm2: float,
    post_observation_mean_reversion_hours: float = 3.0,
) -> pd.DataFrame:
    """Scale irradiance components while retaining API values and provenance."""
    out = grid.copy()
    time_column = _time_column(out)
    ratio = ratio_at_grid_times(
        out[time_column],
        trace,
        post_observation_mean_reversion_hours=post_observation_mean_reversion_hours,
    )
    out["historical_irradiance_ratio"] = ratio
    for column in ("GHI", "DNI", "DHI", "POA_drive", "POA_stop_ideal"):
        if column not in out.columns:
            continue
        raw = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
        out[f"{column}_api_raw"] = raw
        effective_unclipped = np.maximum(0.0, raw.to_numpy(dtype=float) * ratio)
        out[f"{column}_effective_unclipped"] = effective_unclipped
        out[column] = np.minimum(
            effective_unclipped,
            PHYSICAL_RADIATION_LIMITS_WM2[column],
        )
    ambient = pd.to_numeric(out.get("Tamb_C"), errors="coerce").fillna(25.0)
    poa_drive = pd.to_numeric(out.get("POA_drive", out.get("GHI")), errors="coerce").fillna(0.0)
    poa_stop = pd.to_numeric(out.get("POA_stop_ideal", poa_drive), errors="coerce").fillna(0.0)
    out["Tcell_C"] = ambient + float(tcell_gain_c_per_wm2) * poa_drive
    out["Tcell_drive_C"] = out["Tcell_C"]
    out["Tcell_stop_ideal_C"] = ambient + float(tcell_gain_c_per_wm2) * poa_stop
    out["weather_source"] = "openmeteo_archive_instant_conditioned_by_healthy_moving_observed_pv"
    out["weather_product_role"] = "historical_counterfactual_only_not_independent_forecast"
    return out


def relative_to(path: Path, base: Path) -> str:
    return os.path.relpath(path.resolve(), base.resolve()).replace("\\", "/")


def build_summary(
    raw: pd.DataFrame,
    corrected: pd.DataFrame,
    trace: pd.DataFrame,
    *,
    raw_path: Path,
    observed_path: Path,
    corrected_path: Path,
    mean_reversion_hours: float,
    reference_array_gain: float,
) -> dict[str, Any]:
    ratio = pd.to_numeric(corrected["historical_irradiance_ratio"], errors="coerce")
    clip_counts = {
        column: int(
            (
                pd.to_numeric(corrected[f"{column}_effective_unclipped"], errors="coerce")
                > float(limit)
            ).sum()
        )
        for column, limit in PHYSICAL_RADIATION_LIMITS_WM2.items()
        if f"{column}_effective_unclipped" in corrected.columns
    }
    return {
        "method": "healthy-moving observed-PV effective/API irradiance ratio applied by historical UTC time",
        "role": "historical counterfactual replay only",
        "independent_forecast_validation_allowed": False,
        "spatial_assumption": "one route-observation ratio is applied across each simultaneous route grid slice",
        "post_observation_mean_reversion_hours": float(mean_reversion_hours),
        "reference_array_gain_removed_from_weather_ratio": float(reference_array_gain),
        "runtime_array_gain_application_count": 1,
        "raw_weather_grid_csv": str(raw_path),
        "observed_replay_csv": str(observed_path),
        "corrected_weather_grid_csv": str(corrected_path),
        "grid_rows": int(len(corrected)),
        "ratio_trace_rows": int(len(trace)),
        "ratio_min": float(ratio.min()),
        "ratio_median": float(ratio.median()),
        "ratio_max": float(ratio.max()),
        "raw_ghi_mean_wm2": float(pd.to_numeric(raw.get("GHI"), errors="coerce").mean()),
        "corrected_ghi_mean_wm2": float(pd.to_numeric(corrected.get("GHI"), errors="coerce").mean()),
        "physical_radiation_limits_wm2": dict(PHYSICAL_RADIATION_LIMITS_WM2),
        "physical_clip_counts": clip_counts,
        "physical_clip_count_total": int(sum(clip_counts.values())),
        "limitations": [
            "The correction uses vehicle PV telemetry and therefore is not an independent PV-map validation target.",
            "Cloud fields away from the actual vehicle trajectory are not observed; the same-time spatial scaling is an explicit approximation.",
            "After the last observation, the ratio exponentially returns to the independent API value.",
            "Latent effective irradiance is retained in *_effective_unclipped; ordinary radiation columns are clipped to declared physical bounds before simulator use.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--observed-log", type=Path)
    parser.add_argument("--raw-grid", type=Path)
    parser.add_argument("--output-grid", type=Path)
    parser.add_argument("--output-profile", type=Path)
    parser.add_argument("--mean-reversion-hours", type=float, default=3.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile_path = args.profile.resolve()
    package = profile_path.parent
    cfg = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    paths = cfg.get("paths", {}) or {}
    observed_path = (
        args.observed_log.resolve()
        if args.observed_log
        else (package / str(paths["progress_reference_csv"])).resolve()
    )
    raw_path = (
        args.raw_grid.resolve()
        if args.raw_grid
        else (package / str(paths["forecast_csv"])).resolve()
    )
    output_grid = (
        args.output_grid.resolve()
        if args.output_grid
        else package / "data" / "weather" / "bwsc2025_historical_pv_conditioned_weather_grid.csv"
    )
    output_profile = (
        args.output_profile.resolve()
        if args.output_profile
        else package / "profile_historical_counterfactual.yaml"
    )
    observed = pd.read_csv(observed_path, low_memory=False)
    raw = pd.read_csv(raw_path, low_memory=False)
    reference_array_gain = float((cfg.get("model", {}) or {}).get("panel_gain", 1.0))
    trace = build_observed_ratio_trace(
        observed,
        reference_array_gain=reference_array_gain,
    )
    tcell_gain = float(
        ((cfg.get("live", {}) or {}).get("weather", {}) or {}).get("tcell_gain", 0.03)
    )
    corrected = correct_historical_weather_grid(
        raw,
        trace,
        tcell_gain_c_per_wm2=tcell_gain,
        post_observation_mean_reversion_hours=float(args.mean_reversion_hours),
    )
    output_grid.parent.mkdir(parents=True, exist_ok=True)
    corrected.to_csv(output_grid, index=False)
    trace_path = output_grid.with_name(output_grid.stem + "_ratio_trace.csv")
    trace.to_csv(trace_path, index=False)
    summary = build_summary(
        raw,
        corrected,
        trace,
        raw_path=raw_path,
        observed_path=observed_path,
        corrected_path=output_grid,
        mean_reversion_hours=float(args.mean_reversion_hours),
        reference_array_gain=reference_array_gain,
    )
    summary_path = output_grid.with_suffix(".summary.yaml")
    summary_path.write_text(
        yaml.safe_dump(summary, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    cfg.setdefault("paths", {})["forecast_csv"] = relative_to(output_grid, output_profile.parent)
    simulation = cfg.setdefault("simulation", {})
    simulation["historical_weather_conditioned"] = True
    simulation["historical_weather_summary_yaml"] = relative_to(summary_path, output_profile.parent)
    historical_output_dir = package / "outputs" / "historical_counterfactual_prerace"
    simulation["output_dir"] = relative_to(historical_output_dir, ROOT)
    simulation["output_prefix"] = f"{package.name}_historical_counterfactual"
    simulation["latest_manifest_json"] = relative_to(
        historical_output_dir / "latest_simulation_run.json", ROOT
    )
    simulation["scenario_label"] = "observed-weather no-trouble counterfactual"
    notes = list(cfg.setdefault("meta", {}).get("notes", []) or [])
    notes.append(
        "This profile is a historical counterfactual using PV-conditioned effective irradiance; do not use it as independent forecast validation or live input."
    )
    cfg["meta"]["notes"] = list(dict.fromkeys(notes))
    output_profile.write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    print(summary_path)
    print(output_profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
