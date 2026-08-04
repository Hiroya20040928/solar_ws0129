#!/usr/bin/env python3
"""Import BOM Himawari hourly solar exposure into a route/time weather grid.

The Bureau products IDE02327/IDE02347 contain hourly exposure (energy per
area), not an instantaneous irradiance.  This importer keeps the source
timestamp, converts MJ/m2 to the interval-mean W/m2, and moves the planning
timestamp to the centre of the accumulation interval before interpolation.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import RegularGridInterpolator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar.weather_utils import ideal_tracking_poa_wm2


PRODUCTS = {"IDE02327": 0.02, "IDE02347": 0.05}
TIME_CANDIDATES = ("time", "valid_time", "timestamp")
LAT_CANDIDATES = ("latitude", "lat")
LON_CANDIDATES = ("longitude", "lon")
VALUE_CANDIDATES = (
    "hourly_global_solar_exposure",
    "global_solar_exposure",
    "solar_exposure",
    "exposure",
)


def first_present(candidates: tuple[str, ...], names: set[str], label: str) -> str:
    for candidate in candidates:
        if candidate in names:
            return candidate
    raise ValueError(f"could not identify {label}; available names={sorted(names)}")


def route_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    distance = "s_km" if "s_km" in frame.columns else "dist_km"
    required = {distance, "lat", "lon"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"route CSV is missing columns: {missing}")
    result = frame[[distance, "lat", "lon"]].rename(columns={distance: "s_km"})
    result = result.apply(pd.to_numeric, errors="coerce").dropna()
    result = result.groupby("s_km", as_index=False).median().sort_values("s_km")
    if len(result) < 2:
        raise ValueError("route CSV must contain at least two valid points")
    return result.reset_index(drop=True)


def normalized_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"source_time_utc", "s_km"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"normalized BOM CSV is missing columns: {missing}")
    if "ghi_interval_mean_wm2" in frame.columns:
        ghi = pd.to_numeric(frame["ghi_interval_mean_wm2"], errors="coerce")
    elif "hourly_exposure_mj_m2" in frame.columns:
        ghi = pd.to_numeric(frame["hourly_exposure_mj_m2"], errors="coerce") * 1.0e6 / 3600.0
    else:
        raise ValueError(
            "normalized BOM CSV requires ghi_interval_mean_wm2 or hourly_exposure_mj_m2"
        )
    result = pd.DataFrame(
        {
            "source_time_utc": pd.to_datetime(frame["source_time_utc"], utc=True, errors="coerce"),
            "s_km": pd.to_numeric(frame["s_km"], errors="coerce"),
            "lat": pd.to_numeric(frame.get("lat"), errors="coerce"),
            "lon": pd.to_numeric(frame.get("lon"), errors="coerce"),
            "ghi_interval_mean_wm2": ghi,
            "quality_flag": frame.get("quality_flag", "not_supplied"),
        }
    )
    return result.dropna(subset=["source_time_utc", "s_km", "ghi_interval_mean_wm2"])


def route_sample_netcdf(paths: list[Path], route: pd.DataFrame, variable: str = "") -> pd.DataFrame:
    try:
        import xarray as xr
    except ImportError as exc:
        raise RuntimeError(
            "NetCDF import requires optional packages: pip install xarray netCDF4"
        ) from exc

    datasets = [xr.open_dataset(path) for path in paths]
    try:
        dataset = xr.combine_by_coords(datasets) if len(datasets) > 1 else datasets[0]
        names = set(dataset.variables) | set(dataset.coords)
        time_name = first_present(TIME_CANDIDATES, names, "time coordinate")
        lat_name = first_present(LAT_CANDIDATES, names, "latitude coordinate")
        lon_name = first_present(LON_CANDIDATES, names, "longitude coordinate")
        value_name = variable or first_present(VALUE_CANDIDATES, names, "solar exposure variable")
        point = "route_point"
        sampled = dataset[value_name].sel(
            {
                lat_name: xr.DataArray(route["lat"].to_numpy(), dims=point),
                lon_name: xr.DataArray(route["lon"].to_numpy(), dims=point),
            },
            method="nearest",
        )
        source_times = pd.to_datetime(dataset[time_name].values, utc=True, errors="coerce")
        values = np.asarray(sampled.transpose(time_name, point).values, dtype=float)
        units = str(dataset[value_name].attrs.get("units", "")).lower().replace(" ", "")
        if "mj" in units:
            values = values * 1.0e6 / 3600.0
        elif "kj" in units:
            values = values * 1.0e3 / 3600.0
        elif not any(token in units for token in ("w/m", "wm-2", "wm**-2")):
            raise ValueError(
                f"unsupported or missing units for {value_name}: {dataset[value_name].attrs.get('units')!r}"
            )
        lat_grid = np.asarray(dataset[lat_name].values, dtype=float)
        lon_grid = np.asarray(dataset[lon_name].values, dtype=float)
        nearest_lat = lat_grid[np.abs(lat_grid[:, None] - route["lat"].to_numpy()).argmin(axis=0)]
        nearest_lon = lon_grid[np.abs(lon_grid[:, None] - route["lon"].to_numpy()).argmin(axis=0)]
        rows = []
        for time_index, source_time in enumerate(source_times):
            for point_index, route_row in route.iterrows():
                rows.append(
                    {
                        "source_time_utc": source_time,
                        "s_km": float(route_row["s_km"]),
                        "lat": float(route_row["lat"]),
                        "lon": float(route_row["lon"]),
                        "source_grid_lat": float(nearest_lat[point_index]),
                        "source_grid_lon": float(nearest_lon[point_index]),
                        "ghi_interval_mean_wm2": float(values[time_index, point_index]),
                        "quality_flag": "from_netcdf",
                    }
                )
        return pd.DataFrame(rows)
    finally:
        for dataset in datasets:
            dataset.close()


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    return 6371.0 * 2.0 * np.arctan2(np.sqrt(a), np.sqrt(np.maximum(1.0 - a, 0.0)))


def prepare_observation_grid(frame: pd.DataFrame, centre_offset_minutes: float) -> pd.DataFrame:
    result = frame.copy()
    result["time_utc"] = result["source_time_utc"] + pd.to_timedelta(
        float(centre_offset_minutes), unit="min"
    )
    result["s_km"] = pd.to_numeric(result["s_km"], errors="coerce")
    result["ghi_interval_mean_wm2"] = pd.to_numeric(
        result["ghi_interval_mean_wm2"], errors="coerce"
    )
    return result.dropna(subset=["time_utc", "s_km", "ghi_interval_mean_wm2"])


def unix_seconds(values) -> np.ndarray:
    timestamps = pd.DatetimeIndex(pd.to_datetime(values, utc=True, errors="coerce"))
    return (
        timestamps.tz_convert("UTC")
        .tz_localize(None)
        .to_numpy(dtype="datetime64[s]")
        .astype(np.int64)
        .astype(float)
    )


def interpolate_to_base(observed: pd.DataFrame, base: pd.DataFrame) -> np.ndarray:
    pivot = observed.pivot_table(
        index="time_utc", columns="s_km", values="ghi_interval_mean_wm2", aggfunc="mean"
    ).sort_index().sort_index(axis=1)
    pivot = pivot.interpolate(axis=1, limit_direction="both").interpolate(
        axis=0, limit_direction="both"
    )
    times = unix_seconds(pivot.index)
    distances = pivot.columns.to_numpy(dtype=float)
    if len(times) < 2 or len(distances) < 2:
        raise ValueError("BOM data must contain at least two times and two route distances")
    interpolator = RegularGridInterpolator(
        (times, distances), pivot.to_numpy(dtype=float), bounds_error=False, fill_value=np.nan
    )
    query_time = unix_seconds(base["time"])
    query_distance = pd.to_numeric(base["s_km"], errors="coerce").to_numpy(dtype=float)
    return interpolator(np.column_stack((query_time, query_distance)))


def merge_with_base(observed: pd.DataFrame, base_path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    base = pd.read_csv(base_path, low_memory=False)
    required = {"time", "s_km", "GHI"}
    missing = sorted(required - set(base.columns))
    if missing:
        raise ValueError(f"base weather CSV is missing columns: {missing}")
    result = base.copy()
    result["GHI_openmeteo"] = pd.to_numeric(result["GHI"], errors="coerce")
    result["GHI_bom"] = interpolate_to_base(observed, result)
    source_min = observed["time_utc"].min()
    source_max = observed["time_utc"].max()
    base_time = pd.to_datetime(result["time"], utc=True, errors="coerce")
    within_time = base_time.between(source_min, source_max)
    night = result["GHI_openmeteo"].fillna(0.0) <= 5.0
    result.loc[within_time & night & result["GHI_bom"].isna(), "GHI_bom"] = 0.0
    covered = result["GHI_bom"].notna()
    base_ghi = result["GHI_openmeteo"].clip(lower=0.0)
    bom_ghi = result["GHI_bom"].clip(lower=0.0)
    ratio = np.divide(
        bom_ghi,
        base_ghi,
        out=np.ones(len(result), dtype=float),
        where=base_ghi.to_numpy(dtype=float) > 1.0,
    )
    ratio = np.clip(ratio, 0.0, 5.0)
    for column in ("DNI", "DHI", "BHI"):
        if column in result.columns:
            result[f"{column}_openmeteo"] = pd.to_numeric(result[column], errors="coerce")
            result.loc[covered, column] = (
                result.loc[covered, f"{column}_openmeteo"] * ratio[covered.to_numpy()]
            )
    if "DHI" in result.columns:
        result.loc[covered, "DHI"] = np.minimum(result.loc[covered, "DHI"], bom_ghi[covered])
    if "BHI" in result.columns and "DHI" in result.columns:
        result.loc[covered, "BHI"] = bom_ghi[covered] - result.loc[covered, "DHI"]
    result.loc[covered, "GHI"] = bom_ghi[covered]
    result.loc[covered, "POA_drive"] = bom_ghi[covered]
    if {"DNI", "DHI"}.issubset(result.columns):
        result.loc[covered, "POA_stop_ideal"] = ideal_tracking_poa_wm2(
            result.loc[covered, "GHI"], result.loc[covered, "DNI"], result.loc[covered, "DHI"]
        )
    if "Tamb_C" in result.columns:
        gains = np.divide(
            pd.to_numeric(result.get("Tcell_drive_C", result["Tamb_C"]), errors="coerce")
            - pd.to_numeric(result["Tamb_C"], errors="coerce"),
            base_ghi,
            out=np.full(len(result), np.nan),
            where=base_ghi.to_numpy(dtype=float) > 50.0,
        )
        finite = gains[np.isfinite(gains)]
        tcell_gain = float(np.median(finite)) if len(finite) else 0.015
        result.loc[covered, "Tcell_drive_C"] = (
            result.loc[covered, "Tamb_C"] + tcell_gain * result.loc[covered, "POA_drive"]
        )
        if "POA_stop_ideal" in result.columns:
            result.loc[covered, "Tcell_stop_ideal_C"] = (
                result.loc[covered, "Tamb_C"]
                + tcell_gain * result.loc[covered, "POA_stop_ideal"]
            )
        result.loc[covered, "Tcell_C"] = result.loc[covered, "Tcell_drive_C"]
    result.loc[covered, "weather_source"] = "bom_himawari_hourly_exposure_with_openmeteo_components"
    result.loc[covered, "radiation_temporal_semantics"] = "preceding_hour_integral_at_interval_centre"
    daylight = within_time & (base_ghi > 20.0)
    coverage = float((covered & daylight).sum() / max(int(daylight.sum()), 1))
    summary = {
        "base_rows": int(len(result)),
        "source_time_min_utc": source_min.isoformat(),
        "source_time_max_utc": source_max.isoformat(),
        "daylight_rows_in_source_window": int(daylight.sum()),
        "daylight_coverage_fraction": coverage,
        "interpolated_ghi_min_wm2": float(np.nanmin(result["GHI_bom"])),
        "interpolated_ghi_max_wm2": float(np.nanmax(result["GHI_bom"])),
    }
    return result, summary


def quality_summary(
    observed: pd.DataFrame,
    merge_summary: dict[str, object],
    product: str,
    centre_offset_minutes: float,
) -> dict[str, object]:
    duplicated = observed.duplicated(["time_utc", "s_km"], keep=False)
    invalid = ~observed["ghi_interval_mean_wm2"].between(0.0, 1400.0)
    nearest = pd.Series(dtype=float)
    if {"lat", "lon", "source_grid_lat", "source_grid_lon"}.issubset(observed.columns):
        valid = observed[["lat", "lon", "source_grid_lat", "source_grid_lon"]].notna().all(axis=1)
        nearest = pd.Series(
            haversine_km(
                observed.loc[valid, "lat"],
                observed.loc[valid, "lon"],
                observed.loc[valid, "source_grid_lat"],
                observed.loc[valid, "source_grid_lon"],
            )
        )
    max_grid_distance = float(nearest.max()) if len(nearest) else math.nan
    grid_gate = not np.isfinite(max_grid_distance) or max_grid_distance <= 8.0
    checks = {
        "no_duplicate_time_distance": not bool(duplicated.any()),
        "ghi_range_0_to_1400_wm2": not bool(invalid.any()),
        "daylight_coverage_at_least_98pct": float(
            merge_summary["daylight_coverage_fraction"]
        ) >= 0.98,
        "source_grid_distance_at_most_8km": bool(grid_gate),
    }
    return {
        "product": product,
        "official_nominal_grid_degrees": PRODUCTS[product],
        "source_rows": int(len(observed)),
        "unique_times": int(observed["time_utc"].nunique()),
        "unique_route_distances": int(observed["s_km"].nunique()),
        "duplicate_rows": int(duplicated.sum()),
        "invalid_ghi_rows": int(invalid.sum()),
        "max_source_grid_distance_km": max_grid_distance,
        "interval_centre_offset_minutes": float(centre_offset_minutes),
        "checks": checks,
        "promotion_gate_pass": all(checks.values()),
        "decision": (
            "candidate weather may be evaluated against held-out vehicle PV/energy data"
            if all(checks.values())
            else "do not promote this weather candidate"
        ),
        "merge": merge_summary,
        "provenance": {
            "provider": "Australian Bureau of Meteorology",
            "measurement": "Himawari-8/9 satellite-derived hourly global solar exposure",
            "official_metadata": "https://www.bom.gov.au/climate/how/newproducts/metadata_solarexposure.shtml",
            "access_note": "historical files require NCI rv74 access or a BOM data request",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--normalized-csv", type=Path)
    source.add_argument("--netcdf", type=Path, nargs="+")
    parser.add_argument("--route", type=Path, required=True)
    parser.add_argument("--base-weather", type=Path, required=True)
    parser.add_argument("--output-weather", type=Path, required=True)
    parser.add_argument("--quality-json", type=Path, required=True)
    parser.add_argument("--normalized-output", type=Path)
    parser.add_argument("--product", choices=sorted(PRODUCTS), default="IDE02347")
    parser.add_argument("--variable", default="")
    parser.add_argument(
        "--interval-centre-offset-minutes",
        type=float,
        default=-30.0,
        help="Offset from BOM source timestamp to the centre of its preceding-hour integral.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    route = route_frame(args.route.resolve())
    if args.normalized_csv:
        raw = normalized_csv(args.normalized_csv.resolve())
    else:
        raw = route_sample_netcdf(
            [path.resolve() for path in args.netcdf], route, variable=args.variable
        )
    observed = prepare_observation_grid(raw, args.interval_centre_offset_minutes)
    if args.normalized_output:
        args.normalized_output.parent.mkdir(parents=True, exist_ok=True)
        observed.to_csv(args.normalized_output, index=False)
    merged, merge_summary = merge_with_base(observed, args.base_weather.resolve())
    quality = quality_summary(
        observed, merge_summary, args.product, args.interval_centre_offset_minutes
    )
    args.output_weather.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(args.output_weather, index=False)
    args.quality_json.parent.mkdir(parents=True, exist_ok=True)
    args.quality_json.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(quality, ensure_ascii=False, indent=2))
    return 0 if quality["promotion_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
