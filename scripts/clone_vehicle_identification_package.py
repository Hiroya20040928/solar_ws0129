"""Create a clean vehicle-identification generation from an existing package."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
PROJECT_PACKAGES = (ROOT / "project_packages").resolve()
MAP_KEYS = (
    "drive_eff_map",
    "regen_eff_map",
    "rint_map",
    "panel_eff_map",
    "mppt_eff_map",
    "drive_map_eco",
    "drive_map_power",
    "regen_map_eco",
    "regen_map_power",
    "ocv_soc_map",
)


def assert_package_child(path: Path) -> Path:
    resolved = path.resolve()
    if PROJECT_PACKAGES != resolved and PROJECT_PACKAGES not in resolved.parents:
        raise ValueError(f"package must stay below {PROJECT_PACKAGES}: {resolved}")
    return resolved


def materialize_active_maps(source: Path, destination: Path, profile: dict) -> dict:
    paths = profile.setdefault("paths", {})
    map_dir = destination / "maps"
    map_dir.mkdir(parents=True, exist_ok=True)
    missing = []
    for key in MAP_KEYS:
        raw = str(paths.get(key, "") or "").strip()
        if not raw:
            missing.append(key)
            continue
        source_asset = Path(raw)
        if not source_asset.is_absolute():
            source_asset = source / source_asset
        if not source_asset.is_file():
            copied_asset = destination / raw
            if copied_asset.is_file():
                source_asset = copied_asset
            else:
                missing.append(f"{key}={raw}")
                continue
        suffix = source_asset.suffix or ".csv"
        destination_asset = map_dir / f"active_{key}{suffix}"
        if source_asset.resolve() != destination_asset.resolve():
            shutil.copy2(source_asset, destination_asset)
        paths[key] = destination_asset.relative_to(destination).as_posix()
    if missing:
        raise FileNotFoundError(f"active map assets are missing: {missing}")
    return profile


def clone_package(
    source: Path,
    destination: Path,
    *,
    replay_csv: Path,
    weather_cache_csv: Path | None = None,
) -> Path:
    source = assert_package_child(source)
    destination = assert_package_child(destination)
    if not source.is_dir():
        raise FileNotFoundError(source)
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    replay_csv = replay_csv.resolve()
    if not replay_csv.is_file():
        raise FileNotFoundError(replay_csv)

    def copy_ignore(current_dir: str, names: list[str]) -> set[str]:
        ignored = {"outputs"} if "outputs" in names else set()
        if Path(current_dir).resolve() == source:
            ignored.update(
                name
                for name in names
                if name.startswith("profile_")
                and name.endswith(".yaml")
                and name != "profile_fullsim_selflearned.yaml"
            )
        return ignored

    shutil.copytree(source, destination, ignore=copy_ignore)
    grounded_source = source / "outputs" / "identification" / "grounded_base_maps"
    grounded_destination = destination / "outputs" / "identification" / "grounded_base_maps"
    if grounded_source.is_dir():
        shutil.copytree(grounded_source, grounded_destination)

    replay_destination = destination / "data" / "observed" / "bwsc2025_observed_log_5s.csv"
    replay_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(replay_csv, replay_destination)
    # These files are derived from the canonical replay and must never survive
    # a generation change with stale weather or sensor semantics.
    for stale_name in ("bwsc2025_fit_dataset_120s.csv", "bwsc2025_replay_validation_5s.csv"):
        stale_path = replay_destination.parent / stale_name
        if stale_path.exists():
            stale_path.unlink()
    if weather_cache_csv is not None:
        weather_cache_csv = weather_cache_csv.resolve()
        if not weather_cache_csv.is_file():
            raise FileNotFoundError(weather_cache_csv)
        cache_destination = destination / "outputs" / "weather_cache" / "route_weather_archive_components.csv"
        cache_destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(weather_cache_csv, cache_destination)

    profile_path = destination / "profile.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    profile = materialize_active_maps(source, destination, profile)
    profile.setdefault("meta", {})["name"] = destination.name
    note = (
        "Independent Open-Meteo instantaneous GHI/DNI/DHI with wind explicitly converted "
        "by the API to m/s; observed-PV effective irradiance is diagnostic only."
    )
    notes = [str(item) for item in profile["meta"].setdefault("notes", [])]
    notes = [
        item
        for item in notes
        if "Independent Open-Meteo GHI/DNI/DHI" not in item
        and "Canonical runtime coefficients" not in item
        and not re.search(r"adopted MLE\d+", item, flags=re.IGNORECASE)
    ]
    generation_note = (
        f"Canonical runtime coefficients, maps, and validation references belong to "
        f"{destination.name} and are synchronized after its identification run completes."
    )
    notes.append(generation_note)
    if note not in notes:
        notes.append(note)
    profile["meta"]["notes"] = notes
    simulation = profile.setdefault("simulation", {})
    simulation["output_dir"] = f"project_packages/{destination.name}/outputs/prerace"
    simulation["output_prefix"] = destination.name
    simulation["latest_manifest_json"] = (
        f"project_packages/{destination.name}/outputs/prerace/latest_simulation_run.json"
    )
    simulation["detail_rate_hz"] = 1.0
    execution_model = simulation.setdefault("execution_model", {})
    execution_model["enabled"] = True
    execution_model["inner_dt_sec"] = 1.0
    identification = profile.setdefault("identification", {})
    identification["output_dir"] = "outputs/identification"
    identification.pop("output_tag", None)
    identification.pop("fit_summary_yaml", None)
    identification.pop("terminal_consistency_yaml", None)
    profile_path.write_text(
        yaml.safe_dump(profile, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )

    fullsim_path = destination / "profile_fullsim_selflearned.yaml"
    if fullsim_path.is_file():
        fullsim = yaml.safe_load(fullsim_path.read_text(encoding="utf-8")) or {}
        fullsim = materialize_active_maps(source, destination, fullsim)
        fullsim.setdefault("meta", {})["name"] = f"{destination.name}_fullsim"
        fullsim_notes = [
            str(item)
            for item in fullsim["meta"].setdefault("notes", [])
            if "Canonical runtime coefficients" not in str(item)
        ]
        fullsim_note = (
            f"Canonical no-trouble full-course simulation profile for {destination.name}; "
            "identification artifacts are synchronized only after the new fit completes."
        )
        if fullsim_note not in fullsim_notes:
            fullsim_notes.append(fullsim_note)
        fullsim["meta"]["notes"] = fullsim_notes
        fullsim_simulation = fullsim.setdefault("simulation", {})
        fullsim_simulation["output_dir"] = (
            f"project_packages/{destination.name}/outputs/prerace_fullsim_selflearned"
        )
        fullsim_simulation["output_prefix"] = f"{destination.name}_fullsim"
        fullsim_simulation["latest_manifest_json"] = (
            f"project_packages/{destination.name}/outputs/prerace_fullsim_selflearned/"
            "latest_simulation_run.json"
        )
        fullsim_simulation["detail_rate_hz"] = 1.0
        fullsim_simulation.setdefault("execution_model", {}).update(
            {"enabled": True, "inner_dt_sec": 1.0}
        )
        fullsim_identification = fullsim.setdefault("identification", {})
        fullsim_identification["output_dir"] = "outputs/identification"
        fullsim_identification.pop("output_tag", None)
        fullsim_identification.pop("fit_summary_yaml", None)
        fullsim_identification.pop("terminal_consistency_yaml", None)
        fullsim_path.write_text(
            yaml.safe_dump(fullsim, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
            newline="\n",
        )

    lineage = {
        "source_package": source.name,
        "destination_package": destination.name,
        "normalized_replay_log": "data/observed/bwsc2025_observed_log_5s.csv",
        "replay_source": str(replay_csv),
        "weather_cache_source": str(weather_cache_csv) if weather_cache_csv else "",
        "weather_contract": {
            "irradiance": "independent Open-Meteo archive instantaneous GHI/DNI/DHI",
            "radiation_temporal_semantics": "instant_at_timestamp",
            "weather_cache_schema_version": 3,
            "wind_speed_unit": "m/s",
            "observed_pv_effective_irradiance_usage": "diagnostic_only",
        },
    }
    lineage_path = destination / "data" / "identification" / "generation_lineage.yaml"
    lineage_path.parent.mkdir(parents=True, exist_ok=True)
    lineage_path.write_text(
        yaml.safe_dump(lineage, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--weather-cache", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    destination = clone_package(
        args.source,
        args.destination,
        replay_csv=args.replay,
        weather_cache_csv=args.weather_cache,
    )
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
