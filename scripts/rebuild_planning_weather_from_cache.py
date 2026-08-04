"""Build a planner weather grid from independent archive components and a fit summary."""

from __future__ import annotations

import argparse
import sys
from dataclasses import fields
from pathlib import Path

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_bwsc2025_fitted_package import (
    MotionFitResult,
    PvFitResult,
    write_nominal_planning_weather_grid_csv,
)


def resolve(base: Path, raw: str | Path) -> Path:
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def dataclass_from_mapping(cls, mapping: dict):
    names = {item.name for item in fields(cls)}
    return cls(**{key: value for key, value in mapping.items() if key in names})


def rebuild(profile_path: Path, cache_csv: Path, fit_summary: Path | None, output_csv: Path | None) -> Path:
    profile_path = profile_path.resolve()
    package_dir = profile_path.parent
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    identification = profile.setdefault("identification", {})
    if fit_summary is None:
        raw_summary = str(identification.get("fit_summary_yaml", "") or "").strip()
        if not raw_summary:
            raise ValueError("fit summary is not configured; pass --fit-summary")
        fit_summary = resolve(package_dir, raw_summary)
    else:
        fit_summary = fit_summary.resolve()
    summary = yaml.safe_load(fit_summary.read_text(encoding="utf-8")) or {}
    pv = dataclass_from_mapping(PvFitResult, summary["pv_fit"])
    motion = dataclass_from_mapping(MotionFitResult, summary["motion_fit"])
    weather = pd.read_csv(cache_csv.resolve(), parse_dates=["time_utc"])
    if output_csv is None:
        output_csv = resolve(package_dir, profile["paths"]["forecast_csv"])
    else:
        output_csv = output_csv.resolve()
    write_nominal_planning_weather_grid_csv(weather, output_csv, pv, motion)
    profile["paths"]["forecast_csv"] = output_csv.relative_to(package_dir).as_posix()
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return output_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--weather-cache", type=Path, required=True)
    parser.add_argument("--fit-summary", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = rebuild(args.profile, args.weather_cache, args.fit_summary, args.output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
