#!/usr/bin/env python3
"""Normalize BWSC2025 panel, stop-charge, and ERA5 field evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, time
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = ROOT / "project_packages" / "bwsc2025_fitted_mle17_instant_weather"


def resolve(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument(
        "--weather-cache",
        type=Path,
        default=ROOT / ".run" / "mle17_weather" / "route_weather_archive_components_v3_instant.csv",
    )
    return parser.parse_args()


def numeric(value: object) -> float:
    parsed = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(parsed) if pd.notna(parsed) else math.nan


def panel_row(
    *,
    source: Path,
    experiment: str,
    run_id: str,
    channel: str,
    irradiance: float,
    power: float,
    area: float,
) -> dict[str, object]:
    efficiency = power / max(irradiance * area, 1.0e-12)
    return {
        "source_file": source.name,
        "experiment": experiment,
        "run_id": run_id,
        "channel_id": channel,
        "irradiance_wm2": irradiance,
        "output_power_w": power,
        "area_m2": area,
        "system_efficiency": efficiency,
        "cell_temperature_c": math.nan,
        "accepted_for_map_shape": False,
        "accepted_for_system_validation": bool(
            irradiance > 50.0 and power >= 0.0 and area > 0.0 and 0.0 < efficiency < 0.35
        ),
        "exclusion_reason": "cell temperature was not recorded; validate the PV chain but do not infer a G-Tcell map",
    }


def append_aggregate(rows: list[dict[str, object]], source: Path, experiment: str, run_id: str) -> None:
    members = [
        row
        for row in rows
        if row["source_file"] == source.name
        and row["experiment"] == experiment
        and row["run_id"] == run_id
        and row["channel_id"] != "full_array"
    ]
    if not members:
        return
    incident_w = sum(float(row["irradiance_wm2"]) * float(row["area_m2"]) for row in members)
    total_area = sum(float(row["area_m2"]) for row in members)
    total_power = sum(float(row["output_power_w"]) for row in members)
    aggregate_irradiance = incident_w / max(total_area, 1.0e-12)
    aggregate = panel_row(
        source=source,
        experiment=experiment,
        run_id=run_id,
        channel="full_array",
        irradiance=aggregate_irradiance,
        power=total_power,
        area=total_area,
    )
    aggregate["exclusion_reason"] = "full-array system validation anchor; cell temperature was not recorded"
    rows.append(aggregate)


def normalize_darwin_panel(path: Path) -> list[dict[str, object]]:
    raw = pd.read_excel(path, sheet_name=0, header=None)
    rows: list[dict[str, object]] = []
    # The workbook has one separator column after run 1 and no fixed stride.
    # Use the actual irradiance header columns rather than positional stepping.
    run_starts = (2, 8, 13, 18, 23)
    area_by_channel = {"mppt1": 1.814227, **{f"mppt{idx}": 0.697780 for idx in range(2, 8)}}
    row_by_channel = {"mppt1": 3, **{f"mppt{idx}": idx + 2 for idx in range(2, 8)}}
    for run_index, start in enumerate(run_starts, start=1):
        run_id = f"darwin_run_{run_index}"
        for channel, row_index in row_by_channel.items():
            irradiance = numeric(raw.iloc[row_index, start])
            power = numeric(raw.iloc[row_index, start + 1])
            if not np.isfinite(irradiance) or not np.isfinite(power):
                continue
            rows.append(
                panel_row(
                    source=path,
                    experiment="darwin_2025-08-18",
                    run_id=run_id,
                    channel=channel,
                    irradiance=irradiance,
                    power=power,
                    area=area_by_channel[channel],
                )
            )
        append_aggregate(rows, path, "darwin_2025-08-18", run_id)
    return rows


def normalize_aug16_panel(path: Path) -> list[dict[str, object]]:
    raw = pd.read_excel(path, sheet_name=0, header=None)
    rows: list[dict[str, object]] = []
    first_areas: list[float] = []
    for block_name, source_rows in (("aug16_block_1", range(12, 19)), ("aug16_block_2", range(20, 27))):
        for channel_index, row_index in enumerate(source_rows, start=1):
            area_raw = numeric(raw.iloc[row_index, 9])
            if block_name == "aug16_block_1":
                first_areas.append(area_raw / 10000.0)
            area = first_areas[channel_index - 1]
            power = numeric(raw.iloc[row_index, 10])
            irradiance = numeric(raw.iloc[row_index, 11])
            if not all(np.isfinite(value) for value in (area, power, irradiance)):
                continue
            rows.append(
                panel_row(
                    source=path,
                    experiment="aug16_2025",
                    run_id=block_name,
                    channel=f"string_{channel_index}",
                    irradiance=irradiance,
                    power=power,
                    area=area,
                )
            )
        append_aggregate(rows, path, "aug16_2025", block_name)
    return rows


def normalize_charge_workbook(path: Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sheet in pd.ExcelFile(path).sheet_names:
        raw = pd.read_excel(path, sheet_name=sheet, header=None)
        match = re.fullmatch(r"(\d{4})_(\d{2})(\d{2})", str(sheet).strip())
        if not match:
            raise ValueError(f"unsupported charge sheet date: {sheet}")
        date_value = datetime(*(int(part) for part in match.groups())).date()
        period = "unknown"
        for _, row in raw.iterrows():
            joined = " ".join(str(value) for value in row.tolist() if pd.notna(value))
            if "朝充電" in joined:
                period = "morning"
            elif "夕方充電" in joined:
                period = "evening"
            value = row.iloc[1] if len(row) > 1 else None
            if not isinstance(value, (time, datetime)):
                continue
            clock = value.time() if isinstance(value, datetime) else value
            current = numeric(row.iloc[2])
            power = numeric(row.iloc[3])
            capacity = numeric(row.iloc[4])
            voltage = numeric(row.iloc[5])
            if not np.isfinite(power):
                continue
            rows.append(
                {
                    "source_file": path.name,
                    "period": period,
                    "time_local": datetime.combine(date_value, clock).isoformat(),
                    "charge_current_a": current,
                    "pv_power_w": power,
                    "cumulative_capacity_ah": capacity,
                    "pack_voltage_v": voltage,
                }
            )
    return pd.DataFrame(rows)


def weather_crosscheck(openmeteo_path: Path, era5_path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    openmeteo = pd.read_csv(openmeteo_path)
    openmeteo["time_utc"] = pd.to_datetime(openmeteo["time_utc"], utc=True, errors="coerce")
    nearest_s = float(
        openmeteo.loc[(pd.to_numeric(openmeteo["s_km"], errors="coerce") - 2830.0).abs().idxmin(), "s_km"]
    )
    openmeteo = openmeteo[
        np.isclose(pd.to_numeric(openmeteo["s_km"], errors="coerce"), nearest_s)
        & (openmeteo["time_utc"].dt.date == pd.Timestamp("2025-08-29").date())
    ][["time_utc", "GHI_archive", "Tamb_archive_C", "radiation_temporal_semantics"]]
    era5 = pd.read_csv(era5_path)
    era5["time_utc"] = pd.to_datetime(era5["valid_time"], utc=True, errors="coerce")
    era5 = era5.groupby("time_utc", as_index=False).agg(
        era5_ghi_mean_wm2=("ghi_Wm2", "mean"),
        era5_ghi_min_wm2=("ghi_Wm2", "min"),
        era5_ghi_max_wm2=("ghi_Wm2", "max"),
    )
    merged = openmeteo.merge(era5, on="time_utc", how="inner")
    merged["difference_wm2"] = merged["GHI_archive"] - merged["era5_ghi_mean_wm2"]
    daylight = merged[(merged["GHI_archive"] > 0.0) | (merged["era5_ghi_mean_wm2"] > 0.0)].copy()
    summary = {
        "route_distance_sample_km": nearest_s,
        "timestamp_alignment": "same declared UTC hour; ERA5 radiation is an hourly accumulation while Open-Meteo uses instant_at_timestamp",
        "daylight_samples": int(len(daylight)),
        "same_timestamp_rmse_wm2": float(np.sqrt(np.mean(daylight["difference_wm2"] ** 2))),
        "same_timestamp_bias_wm2": float(daylight["difference_wm2"].mean()),
        "openmeteo_daylight_mean_wm2": float(daylight["GHI_archive"].mean()),
        "openmeteo_max_wm2": float(daylight["GHI_archive"].max()),
        "era5_daylight_mean_wm2": float(daylight["era5_ghi_mean_wm2"].mean()),
        "era5_max_wm2": float(daylight["era5_ghi_mean_wm2"].max()),
        "high_precision_weather_gate_pass": False,
        "reason": "the independent reanalysis products disagree materially and neither is an onboard POA measurement",
    }
    return merged, summary


def main() -> int:
    args = parse_args()
    package = resolve(args.package)
    evidence_dir = package / "data" / "identification" / "evidence" / "field_tests"
    output_dir = package / "outputs" / "identification" / "field_evidence"
    output_dir.mkdir(parents=True, exist_ok=True)

    aug16 = evidence_dir / "8.16(15.22~15.27)発電実験.xlsx"
    darwin = evidence_dir / "8.18　発電実験　ダーウィン.xlsx"
    charge = evidence_dir / "Day5,6充電記録データ.xlsx"
    era5 = evidence_dir / "ERA5_20250829_2830km.csv"
    for path in (aug16, darwin, charge, era5):
        if not path.is_file():
            raise FileNotFoundError(path)

    panel = pd.DataFrame(normalize_aug16_panel(aug16) + normalize_darwin_panel(darwin))
    panel.to_csv(output_dir / "panel_field_test_normalized.csv", index=False)
    charge_frame = normalize_charge_workbook(charge)
    charge_frame.to_csv(output_dir / "stop_charge_observations.csv", index=False)
    weather, weather_summary = weather_crosscheck(resolve(args.weather_cache), era5)
    weather.to_csv(output_dir / "openmeteo_era5_2830km_crosscheck.csv", index=False)

    aggregates = panel[
        (panel["channel_id"] == "full_array") & panel["accepted_for_system_validation"]
    ].copy()
    payload = {
        "panel": {
            "individual_channel_rows": int((panel["channel_id"] != "full_array").sum()),
            "full_array_rows": int(len(aggregates)),
            "full_array_efficiency_min": float(aggregates["system_efficiency"].min()),
            "full_array_efficiency_median": float(aggregates["system_efficiency"].median()),
            "full_array_efficiency_max": float(aggregates["system_efficiency"].max()),
            "map_shape_gate_pass": False,
            "reason": "cell temperature is absent, so these tests validate combined panel/MPPT output but cannot identify a G-Tcell surface",
        },
        "stop_charge": {
            "rows": int(len(charge_frame)),
            "pv_power_mean_w": float(charge_frame["pv_power_w"].mean()),
            "pv_power_max_w": float(charge_frame["pv_power_w"].max()),
        },
        "weather": weather_summary,
    }
    (output_dir / "field_evidence_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
