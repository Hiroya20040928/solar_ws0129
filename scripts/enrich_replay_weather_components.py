"""Add independent Open-Meteo GHI/DNI/DHI and wind to a replay log."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_bwsc2025_fitted_package import (
    attach_archive_weather,
    fetch_route_weather_cache,
)


WEATHER_COLUMNS = (
    "GHI_archive",
    "DNI_archive",
    "DHI_archive",
    "BHI_archive",
    "Tamb_archive_C",
    "headwind_archive_ms",
    "wind_speed_ms",
    "wind_dir_deg",
)


def route_geometry_from_replay(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"s_km", "lat", "lon"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"replay log is missing route columns: {missing}")
    route = frame[["s_km", "lat", "lon"]].apply(pd.to_numeric, errors="coerce").dropna()
    route = route.sort_values("s_km").groupby("s_km", as_index=False).median()
    if len(route) < 2:
        raise ValueError("at least two valid route positions are required")
    return route.rename(columns={"s_km": "dist_km"})


def enrich_replay(
    input_csv: Path,
    output_csv: Path,
    cache_csv: Path,
) -> dict:
    frame = pd.read_csv(input_csv, low_memory=False)
    if "time_utc" not in frame.columns:
        raise ValueError("replay log must contain time_utc")
    frame["time_utc"] = pd.to_datetime(frame["time_utc"], format="mixed", utc=True)
    frame = frame.sort_values("time_utc").reset_index(drop=True)
    route = route_geometry_from_replay(frame)
    start_date = frame["time_utc"].min().date().isoformat()
    end_date = frame["time_utc"].max().date().isoformat()
    weather = fetch_route_weather_cache(
        route,
        cache_csv,
        start_date,
        end_date,
        max_s_km=float(route["dist_km"].max()),
        include_bwsc2025_event_anchors=False,
    )
    original = frame.copy()
    enriched = attach_archive_weather(frame, weather)
    for column in WEATHER_COLUMNS:
        if column in original.columns:
            enriched[f"{column}_input"] = original[column]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(output_csv, index=False)
    return {
        "input_csv": str(input_csv.resolve()),
        "output_csv": str(output_csv.resolve()),
        "cache_csv": str(cache_csv.resolve()),
        "rows": int(len(enriched)),
        "weather_rows": int(len(weather)),
        "distance_min_km": float(np.nanmin(enriched["s_km"])),
        "distance_max_km": float(np.nanmax(enriched["s_km"])),
        "start_utc": enriched["time_utc"].min().isoformat(),
        "end_utc": enriched["time_utc"].max().isoformat(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = enrich_replay(args.input.resolve(), args.output.resolve(), args.cache.resolve())
    for key, value in summary.items():
        print(f"{key}: {value}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
