#!/usr/bin/env python3
"""Reject circular or non-instant weather before policy optimization."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import yaml


CONTAMINATION_TOKENS = (
    "observed_pv",
    "pv_conditioned",
    "conditioned_by_healthy_moving_observed_pv",
)


def evaluate_policy_weather(profile_path: Path) -> dict:
    profile_path = profile_path.resolve()
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8-sig")) or {}
    paths = profile.get("paths", {}) or {}
    simulation = profile.get("simulation", {}) or {}
    weather_raw = str(paths.get("forecast_csv", "") or "").strip()
    weather_path = Path(weather_raw)
    if weather_raw and not weather_path.is_absolute():
        weather_path = (profile_path.parent / weather_path).resolve()

    sources: set[str] = set()
    roles: set[str] = set()
    semantics: set[str] = set()
    row_count = 0
    error = ""
    if not weather_raw:
        error = "paths.forecast_csv is empty"
    elif not weather_path.is_file():
        error = f"weather CSV is missing: {weather_path}"
    else:
        with weather_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            for row in reader:
                row_count += 1
                if row.get("weather_source"):
                    sources.add(str(row["weather_source"]).strip())
                if row.get("weather_product_role"):
                    roles.add(str(row["weather_product_role"]).strip())
                if row.get("radiation_temporal_semantics"):
                    semantics.add(str(row["radiation_temporal_semantics"]).strip())

    searchable = " ".join(
        [weather_path.name.lower()]
        + [value.lower() for value in sorted(sources)]
        + [value.lower() for value in sorted(roles)]
    )
    circular = bool(
        bool(simulation.get("historical_weather_conditioned", False))
        or any(token in searchable for token in CONTAMINATION_TOKENS)
    )
    checks = {
        "weather_path_present": not bool(error),
        "rows_present": row_count > 0,
        "independent_of_vehicle_pv": not circular,
        "instant_timestamp_semantics": semantics == {"instant_at_timestamp"},
    }
    return {
        "scope": "policy-search weather independence preflight",
        "passed": bool(all(checks.values())),
        "checks": checks,
        "profile": str(profile_path),
        "weather_csv": str(weather_path),
        "row_count": row_count,
        "weather_sources": sorted(sources),
        "weather_product_roles": sorted(roles),
        "radiation_temporal_semantics": sorted(semantics),
        "error": error,
        "reason": (
            "independent instant weather input"
            if all(checks.values())
            else "policy search must not use vehicle-PV-conditioned or non-instant weather"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = evaluate_policy_weather(args.profile)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
