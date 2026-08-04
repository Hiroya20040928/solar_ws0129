from __future__ import annotations
#!/usr/bin/env python3
"""Perform a reproducible static and profile-contract audit of solar code."""


import argparse
import ast
import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
from pathlib import Path
import re

import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート


ROOT = Path(__file__).resolve().parents[1]
CODE_DIRS = ("mpc_solarcar", "launch", "scripts")
SOLAR_LAUNCHES = (
    "launch/solarcar_sim.launch.py",
    "launch/solar_measurement.launch.py",
    "launch/solar_race_live.launch.py",
    "launch/solar_race_live_wifi.launch.py",
    "mpc_solarcar/live_launch.py",
)
BASE_PRIMARY_PROFILES = (
    "config/solar/bwsc_2027_demo.yaml",
    "project_packages/bwsc2027_template/profile.yaml",
    "project_packages/other_template/profile.yaml",
)
FORBIDDEN_SOLAR_TERMS = re.compile(r"\b(passo|magnetic|obd|maf|fuel)\b", re.IGNORECASE)
ENTRY_RE = re.compile(
    r"""["'](?P<name>[A-Za-z0-9_]+)\s*=\s*(?P<module>[A-Za-z0-9_.]+):(?P<function>[A-Za-z0-9_]+)["']"""
)
EXECUTABLE_RE = re.compile(r"""executable\s*=\s*["']([^"']+)["']""")
MLE_PACKAGE_RE = re.compile(r"^bwsc2025_fitted_mle(?P<generation>\d+)(?:_|$)")


@dataclass
class Finding:                                                     # [クラス定義] Finding オブジェクトの設計
    severity: str
    check: str
    path: str
    detail: str


def add(findings: list[Finding], severity: str, check: str, path: Path | str, detail: str) -> None:  # [関数定義] add の処理実行ブロック
    raw = Path(path)
    try:
        display = raw.resolve().relative_to(ROOT).as_posix()
    except (OSError, ValueError):
        display = str(path).replace("\\", "/")
    findings.append(Finding(severity, check, display, detail))


def python_files() -> list[Path]:                                  # [関数定義] python_files の処理実行ブロック
    files: list[Path] = []
    for dirname in CODE_DIRS:
        files.extend(
            path
            for path in (ROOT / dirname).rglob("*.py")
            if "__pycache__" not in path.parts
        )
    return sorted(set(files))                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def audit_python(findings: list[Finding]) -> tuple[int, dict[str, ast.Module]]:  # [関数定義] audit_python の処理実行ブロック
    trees: dict[str, ast.Module] = {}
    for path in python_files():
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8-sig")
            trees[rel] = ast.parse(text, filename=rel)
        except (OSError, UnicodeError, SyntaxError) as exc:
            add(findings, "ERROR", "python_parse", path, str(exc))
    add(findings, "PASS", "python_parse", ".", f"{len(trees)} Python files parsed")
    return len(trees), trees                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _local_module_path(parts: tuple[str, ...]) -> Path | None:     # [関数定義] _local_module_path の処理実行ブロック
    if not parts:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    module_path = ROOT.joinpath(*parts)
    file_path = module_path.with_suffix(".py")
    if file_path.is_file():
        return file_path                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
    init_path = module_path / "__init__.py"
    if init_path.is_file():
        return init_path                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return None                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def audit_local_import_closure(findings: list[Finding], trees: dict[str, ast.Module]) -> None:  # [関数定義] audit_local_import_closure の処理実行ブロック
    """Require every package-local Python import to resolve inside the distribution."""
    checked: set[tuple[str, tuple[str, ...]]] = set()
    missing: list[tuple[Path, int, str]] = []
    local_roots = {
        path.name
        for path in ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }

    for rel, tree in trees.items():
        source_path = ROOT / rel
        package_parts = tuple(source_path.relative_to(ROOT).parent.parts)
        for node in ast.walk(tree):
            candidates: list[tuple[str, ...]] = []
            label = ""
            if isinstance(node, ast.Import):
                for alias in node.names:
                    parts = tuple(alias.name.split("."))
                    if parts and parts[0] in local_roots:
                        candidates.append(parts)
                label = ", ".join(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module_parts = tuple((node.module or "").split(".")) if node.module else ()
                if node.level:
                    if not (source_path.parent / "__init__.py").is_file():
                        # Utility scripts use a try/except relative-import fallback
                        # and are not importable package modules themselves.
                        continue
                    keep = len(package_parts) - (node.level - 1)
                    base = package_parts[:max(0, keep)] + module_parts
                    candidates.append(base)
                    if not module_parts:
                        candidates.extend(base + (alias.name,) for alias in node.names if alias.name != "*")
                elif module_parts and module_parts[0] in local_roots:
                    candidates.append(module_parts)
                label = f"from {'.' * node.level}{node.module or ''} import " + ", ".join(
                    alias.name for alias in node.names
                )
            else:
                continue

            for parts in candidates:
                key = (rel, parts)
                if key in checked or not parts:
                    continue
                checked.add(key)
                if _local_module_path(parts) is None:
                    missing.append((source_path, int(getattr(node, "lineno", 0)), label))

    if missing:
        for path, line, label in missing:
            add(findings, "ERROR", "local_import_closure", path, f"line {line}: unresolved {label}")
    else:
        add(findings, "PASS", "local_import_closure", ".", f"{len(checked)} local imports resolved")


def setup_entries() -> dict[str, tuple[str, str]]:                 # [関数定義] setup_entries の処理実行ブロック
    text = (ROOT / "setup.py").read_text(encoding="utf-8")
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        match.group("name"): (match.group("module"), match.group("function"))
        for match in ENTRY_RE.finditer(text)
    }


def audit_launch_contracts(findings: list[Finding], trees: dict[str, ast.Module]) -> None:  # [関数定義] audit_launch_contracts の処理実行ブロック
    entries = setup_entries()
    used: set[str] = set()
    for raw in SOLAR_LAUNCHES:
        path = ROOT / raw
        if not path.is_file():
            add(findings, "ERROR", "solar_launch_exists", path, "missing launch source")
            continue
        text = path.read_text(encoding="utf-8")
        used.update(EXECUTABLE_RE.findall(text))
        match = FORBIDDEN_SOLAR_TERMS.search(text)
        if match:
            add(findings, "ERROR", "solar_scope", path, f"forbidden solar dependency: {match.group(0)}")

    for name in sorted(used):
        entry = entries.get(name)
        if entry is None:
            add(findings, "ERROR", "launch_entrypoint", "setup.py", f"{name} is launched but has no console entry")
            continue
        module, function = entry
        module_path = ROOT / (module.replace(".", "/") + ".py")
        rel = module_path.relative_to(ROOT).as_posix() if module_path.is_file() else ""
        tree = trees.get(rel)
        functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        } if tree is not None else set()
        if tree is None or function not in functions:
            add(findings, "ERROR", "launch_entrypoint", module_path, f"{name} target {function} is missing")
        else:
            add(findings, "PASS", "launch_entrypoint", module_path, f"{name} -> {module}:{function}")

    solar_runtime = [
        ROOT / "mpc_solarcar" / "telemetry_text_bridge_node.py",
        ROOT / "mpc_solarcar" / "speed_command_bridge_node.py",
        ROOT / "mpc_solarcar" / "solar_logger_node.py",
        ROOT / "mpc_solarcar" / "solar_preflight_node.py",
    ]
    for path in solar_runtime:
        text = path.read_text(encoding="utf-8")
        match = FORBIDDEN_SOLAR_TERMS.search(text)
        if match:
            add(findings, "ERROR", "solar_scope", path, f"forbidden solar dependency: {match.group(0)}")
    add(findings, "PASS", "solar_scope", ".", "solar launch/runtime sources contain no PASSO, magnetic, OBD, MAF, or fuel dependency")


def nested(cfg: dict, *keys: str, default=None):                   # [関数定義] nested の処理実行ブロック
    value = cfg
    for key in keys:
        if not isinstance(value, dict):
            return default                                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
        value = value.get(key, default)
    return value                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def primary_profile_paths() -> list[Path]:                         # [関数定義] primary_profile_paths の処理実行ブロック
    profiles = [ROOT / raw for raw in BASE_PRIMARY_PROFILES]
    packages_root = ROOT / "project_packages"
    candidates: list[tuple[int, Path]] = []
    if packages_root.is_dir():
        for package in packages_root.iterdir():
            if not package.is_dir():
                continue
            match = MLE_PACKAGE_RE.match(package.name)
            if match:
                candidates.append((int(match.group("generation")), package))
    if candidates:
        _, latest = max(candidates, key=lambda item: (item[0], item[1].name))
        names = {
            "profile.yaml",
            "profile_fullsim_selflearned.yaml",
            "profile_historical_counterfactual.yaml",
            "profile_operational_fine.yaml",
        }
        names.update(path.name for path in latest.glob("profile_mle*_operational_fine.yaml"))
        profiles.extend(latest / name for name in sorted(names) if (latest / name).is_file())
    return list(dict.fromkeys(profiles))                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fitted_package_high_precision_allowed(package: Path) -> bool:  # [関数定義] fitted_package_high_precision_allowed の処理実行ブロック
    reports = package / "outputs" / "reports"
    for path in reports.glob("*model_acceptance.yaml") if reports.is_dir() else ():
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
        except Exception:
            continue
        if bool(payload.get("fullsim_adoption_gate_pass")) and bool(payload.get("high_precision_claim_allowed")):
            return True                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return False                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def audit_profile(findings: list[Finding], path: Path) -> None:    # [関数定義] audit_profile の処理実行ブロック
    if not path.is_file():
        add(findings, "ERROR", "profile_exists", path, "missing")
        return
    try:
        cfg = yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}
    except Exception as exc:
        add(findings, "ERROR", "profile_parse", path, str(exc))
        return

    soc0 = float(nested(cfg, "simulation", "soc0", default=0.0))
    soc_max = float(nested(cfg, "model", "soc_max", default=1.0))
    if soc0 > soc_max + 1.0e-12:
        add(findings, "ERROR", "soc_contract", path, f"simulation.soc0={soc0} > model.soc_max={soc_max}")
    else:
        add(findings, "PASS", "soc_contract", path, f"soc0={soc0} <= soc_max={soc_max}")

    p_aux = float(nested(cfg, "model", "P_aux", default=0.0))
    p_stopped = float(nested(cfg, "model", "P_aux_stopped", default=p_aux))
    p_night = float(nested(cfg, "model", "P_aux_night", default=0.0))
    aux_init = float(nested(cfg, "live", "autocal", "aux_power_w_init", default=p_aux))
    if abs(aux_init - p_aux) > 0.25:
        add(findings, "ERROR", "aux_contract", path, f"autocal={aux_init} W differs from model={p_aux} W")
    elif abs(p_stopped - p_aux) > 0.25:
        add(findings, "ERROR", "aux_contract", path, f"daytime stop={p_stopped} W differs from active={p_aux} W")
    elif abs(p_night) > 1.0e-9:
        add(findings, "ERROR", "aux_contract", path, f"night auxiliary is not zero: {p_night} W")
    else:
        add(findings, "PASS", "aux_contract", path, f"driving/day-stop={p_aux} W, night=0 W")

    wifi = nested(cfg, "live", "wifi_bridge", default={}) or {}
    expected = {
        "timestamp_required": True,
        "max_packet_age_sec": 5.0,
        "max_future_skew_sec": 2.0,
        "max_out_of_order_sec": 0.0,
    }
    mismatches = [f"{key}={wifi.get(key)!r}" for key, value in expected.items() if wifi.get(key) != value]
    if mismatches:
        add(findings, "ERROR", "wifi_time_contract", path, ", ".join(mismatches))
    else:
        add(findings, "PASS", "wifi_time_contract", path, "UTC required; age/future/order gates enabled")

    if MLE_PACKAGE_RE.match(path.parent.name):
        map_basis = str(
            nested(cfg, "model", "drive_eff_map_basis", default="") or ""
        ).strip()
        inverter_eta = float(nested(cfg, "model", "inverter_eta", default=math.nan))
        expected_basis = "controller_dc_input_to_motor_mechanical_output"
        if map_basis != expected_basis or abs(inverter_eta - 1.0) > 1.0e-12:
            add(
                findings,
                "ERROR",
                "drive_efficiency_basis_contract",
                path,
                f"basis={map_basis!r}, inverter_eta={inverter_eta}; M2096 eta_t already includes controller loss",
            )
        else:
            add(
                findings,
                "PASS",
                "drive_efficiency_basis_contract",
                path,
                "M2096 Pm/Pin total-efficiency map active; no duplicate inverter loss",
            )
        air_density_mode = str(nested(cfg, "model", "air_density_mode", default="constant") or "constant")
        reference_pressure_pa = float(
            nested(cfg, "model", "air_density_reference_pressure_pa", default=0.0)
        )
        if air_density_mode != "ideal_gas_altitude" or not (80000.0 <= reference_pressure_pa <= 110000.0):
            add(
                findings,
                "ERROR",
                "air_density_contract",
                path,
                f"mode={air_density_mode}, reference_pressure_pa={reference_pressure_pa}",
            )
        else:
            add(
                findings,
                "PASS",
                "air_density_contract",
                path,
                "temperature/elevation-dependent ideal-gas density enabled",
            )
        q_nom_ah = float(nested(cfg, "model", "Q_nom_Ah", default=0.0))
        if q_nom_ah <= 0.0:
            add(findings, "ERROR", "soc_state_contract", path, "fitted OCV-SoC profile requires model.Q_nom_Ah > 0")
        else:
            add(findings, "PASS", "soc_state_contract", path, f"charge SoC with Q_nom_Ah={q_nom_ah}")
        race_km = float(nested(cfg, "mpc", "race_km", default=0.0))
        horizon_km = float(nested(cfg, "mpc", "upper_horizon_km", default=0.0))
        if abs(race_km - 3026.9) > 1.0e-6 or horizon_km + 1.0e-6 < race_km:
            add(findings, "ERROR", "full_course_contract", path, f"race={race_km}, horizon={horizon_km}")
        else:
            add(findings, "PASS", "full_course_contract", path, f"full course={race_km} km")

        stop_raw = str(nested(cfg, "paths", "stop_yaml", default="") or "").strip()
        stop_path = Path(stop_raw)
        if not stop_path.is_absolute():
            stop_path = path.parent / stop_path
        deadline_raw = str(
            nested(cfg, "simulation", "race_deadline_utc", default="") or ""
        ).strip()
        if not stop_path.is_file() or not deadline_raw:
            add(
                findings,
                "ERROR",
                "official_event_timing_contract",
                path,
                f"official stop file exists={stop_path.is_file()}, race_deadline_utc={deadline_raw!r}",
            )
        else:
            stop_cfg = yaml.safe_load(stop_path.read_text(encoding="utf-8-sig")) or {}
            timing_stops = stop_cfg.get("stops", []) or []
            finish = stop_cfg.get("finish", {}) or {}
            valid_stops = bool(len(timing_stops) == 9)
            for stop in timing_stops:
                valid_stops = bool(
                    valid_stops
                    and abs(float(stop.get("dwell_sec", 0.0)) - 1800.0) <= 1.0e-9
                    and str(stop.get("window_open_utc", "") or "")
                    and str(stop.get("window_close_utc", "") or "")
                )
            finish_close = str(finish.get("window_close_utc", "") or "")
            if not valid_stops or finish_close != deadline_raw:
                add(
                    findings,
                    "ERROR",
                    "official_event_timing_contract",
                    stop_path,
                    f"stops={len(timing_stops)}, all_1800s_with_windows={valid_stops}, finish_close={finish_close!r}, deadline={deadline_raw!r}",
                )
            else:
                add(
                    findings,
                    "PASS",
                    "official_event_timing_contract",
                    stop_path,
                    f"9 official 1800 s stops and finish deadline {deadline_raw}",
                )

        ocv_raw = str(nested(cfg, "paths", "ocv_soc_map", default="") or "").strip()
        ocv_path = Path(ocv_raw)
        if not ocv_path.is_absolute():
            ocv_path = path.parent / ocv_path
        v_max = float(nested(cfg, "model", "V_max", default=0.0))
        if not ocv_raw or not ocv_path.is_file():
            add(findings, "ERROR", "ocv_voltage_contract", ocv_path, "active OCV-SoC CSV is missing")
        else:
            ocv_max = float("-inf")
            with ocv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                for row in csv.DictReader(stream):
                    try:
                        ocv_max = max(ocv_max, float(row.get("ocv_v", "nan")))
                    except (TypeError, ValueError):
                        pass
            if not (ocv_max < float("inf")):
                add(findings, "ERROR", "ocv_voltage_contract", ocv_path, "no finite ocv_v values")
            elif v_max + 1.0e-9 < ocv_max:
                add(
                    findings,
                    "ERROR",
                    "ocv_voltage_contract",
                    path,
                    f"model.V_max={v_max:.3f} V < active OCV maximum={ocv_max:.3f} V",
                )
            elif v_max + 1.0e-9 < 108.75:
                add(
                    findings,
                    "ERROR",
                    "ocv_voltage_contract",
                    path,
                    f"model.V_max={v_max:.3f} V < grounded 25S product limit=108.750 V",
                )
            elif v_max > 108.75 + 1.0e-9:
                add(
                    findings,
                    "ERROR",
                    "ocv_voltage_contract",
                    path,
                    f"model.V_max={v_max:.3f} V > grounded 25S product limit=108.750 V",
                )
            else:
                add(
                    findings,
                    "PASS",
                    "ocv_voltage_contract",
                    path,
                    f"OCV max={ocv_max:.3f} V <= V_max={v_max:.3f} V; product limit grounded at 108.750 V",
                )

        if bool(nested(cfg, "identification", "grade_observation", "enabled", default=False)):
            route_raw = str(nested(cfg, "paths", "route_profile_csv", default="") or "").strip()
            route_path = Path(route_raw)
            if not route_path.is_absolute():
                route_path = path.parent / route_path
            if not route_raw or not route_path.is_file():
                add(findings, "ERROR", "grade_observation_contract", route_path, "route profile CSV is missing")
            else:
                route_rows = 0
                finite_elevation_rows = 0
                monotonic = True
                previous_distance = None
                with route_path.open("r", encoding="utf-8-sig", newline="") as stream:
                    reader = csv.DictReader(stream)
                    route_fields = set(reader.fieldnames or [])
                    for row in reader:
                        route_rows += 1
                        try:
                            distance = float(row.get("dist_km", "nan"))
                            elevation = float(row.get("elev_m", "nan"))
                        except (TypeError, ValueError):
                            monotonic = False
                            continue
                        if elevation == elevation and abs(elevation) < float("inf"):
                            finite_elevation_rows += 1
                        if previous_distance is not None and distance <= previous_distance:
                            monotonic = False
                        previous_distance = distance
                required_route_fields = {"dist_km", "elev_m", "slope_pct"}
                if not required_route_fields.issubset(route_fields):
                    add(
                        findings,
                        "ERROR",
                        "grade_observation_contract",
                        route_path,
                        f"missing columns: {sorted(required_route_fields - route_fields)}",
                    )
                elif route_rows < 21 or finite_elevation_rows != route_rows or not monotonic:
                    add(
                        findings,
                        "ERROR",
                        "grade_observation_contract",
                        route_path,
                        f"rows={route_rows}, finite_elevation={finite_elevation_rows}, strictly_monotonic={monotonic}",
                    )
                else:
                    add(
                        findings,
                        "PASS",
                        "grade_observation_contract",
                        route_path,
                        f"{route_rows} elevation-backed route rows; strictly monotonic distance",
                    )

        forecast_raw = str(nested(cfg, "paths", "forecast_csv", default="") or "").strip()
        forecast_path = Path(forecast_raw)
        if not forecast_path.is_absolute():
            forecast_path = path.parent / forecast_path
        if not forecast_path.is_file():
            add(findings, "ERROR", "weather_grid_contract", forecast_path, "planning weather CSV is missing")
        else:
            max_weather_km = float("-inf")
            sources: set[str] = set()
            semantics: set[str] = set()
            fieldnames: set[str] = set()
            seen_weather_keys: set[tuple[str, str]] = set()
            duplicate_weather_keys = 0
            weather_ranges = {
                "GHI": [float("inf"), float("-inf")],
                "DNI": [float("inf"), float("-inf")],
                "DHI": [float("inf"), float("-inf")],
                "Tamb_C": [float("inf"), float("-inf")],
            }
            with forecast_path.open("r", encoding="utf-8-sig", newline="") as stream:
                reader = csv.DictReader(stream)
                fieldnames = set(reader.fieldnames or [])
                distance_key = "s_km" if "s_km" in fieldnames else "route_progress_km"
                for row in reader:
                    try:
                        max_weather_km = max(max_weather_km, float(row.get(distance_key, "nan")))
                    except (TypeError, ValueError):
                        pass
                    if row.get("weather_source"):
                        sources.add(str(row["weather_source"]))
                    if row.get("radiation_temporal_semantics"):
                        semantics.add(str(row["radiation_temporal_semantics"]))
                    key = (str(row.get("time", "")), str(row.get(distance_key, "")))
                    if key in seen_weather_keys:
                        duplicate_weather_keys += 1
                    else:
                        seen_weather_keys.add(key)
                    for column, limits in weather_ranges.items():
                        try:
                            value = float(row.get(column, "nan"))
                        except (TypeError, ValueError):
                            continue
                        if value == value and abs(value) < float("inf"):
                            limits[0] = min(limits[0], value)
                            limits[1] = max(limits[1], value)
            required = {"GHI", "DNI", "DHI"}
            contaminated = any("observed_pv" in source.lower() for source in sources)
            historical_conditioned = bool(
                nested(cfg, "simulation", "historical_weather_conditioned", default=False)
            )
            historical_output = str(nested(cfg, "simulation", "output_dir", default="") or "")
            historical_manifest = str(
                nested(cfg, "simulation", "latest_manifest_json", default="") or ""
            )
            scenario_label = str(
                nested(cfg, "simulation", "scenario_label", default="") or ""
            ).lower()
            historical_separated = bool(
                "historical_counterfactual" in historical_output
                and "historical_counterfactual" in historical_manifest
                and "counterfactual" in scenario_label
            )
            if not required.issubset(fieldnames):
                add(findings, "ERROR", "weather_grid_contract", forecast_path, f"missing columns: {sorted(required - fieldnames)}")
            elif max_weather_km + 1.0e-6 < race_km:
                add(findings, "ERROR", "weather_grid_contract", forecast_path, f"weather ends at {max_weather_km} km < race {race_km} km")
            elif contaminated and not historical_conditioned:
                add(findings, "ERROR", "weather_grid_contract", forecast_path, f"planning source contains observed-PV feedback: {sorted(sources)}")
            elif contaminated and not historical_separated:
                add(
                    findings,
                    "ERROR",
                    "historical_weather_separation_contract",
                    path,
                    "PV-conditioned weather must use a dedicated output directory, manifest, and scenario label",
                )
            elif contaminated:
                add(
                    findings,
                    "PASS",
                    "historical_weather_separation_contract",
                    path,
                    "PV-conditioned replay is explicitly labeled and isolated from nominal/live outputs",
                )
            elif semantics != {"instant_at_timestamp"}:
                add(findings, "ERROR", "weather_grid_contract", forecast_path, f"radiation semantics={sorted(semantics)}")
            else:
                add(findings, "PASS", "weather_grid_contract", forecast_path, f"independent instant GHI/DNI/DHI through {max_weather_km} km")

            physical_bounds = {
                "GHI": (0.0, 1200.0),
                "DNI": (0.0, 1400.0),
                "DHI": (0.0, 800.0),
                "Tamb_C": (-20.0, 55.0),
            }
            bad_ranges = []
            for column, (lower, upper) in physical_bounds.items():
                observed_min, observed_max = weather_ranges[column]
                if observed_min == float("inf") or observed_min < lower or observed_max > upper:
                    bad_ranges.append(
                        f"{column}=[{observed_min:.3f},{observed_max:.3f}] expected [{lower},{upper}]"
                    )
            if duplicate_weather_keys:
                add(
                    findings,
                    "ERROR",
                    "weather_grid_key_contract",
                    forecast_path,
                    f"duplicate (time,{distance_key}) rows={duplicate_weather_keys}",
                )
            else:
                add(
                    findings,
                    "PASS",
                    "weather_grid_key_contract",
                    forecast_path,
                    f"{len(seen_weather_keys)} unique (time,{distance_key}) rows",
                )
            if bad_ranges:
                add(findings, "ERROR", "weather_grid_range_contract", forecast_path, "; ".join(bad_ranges))
            else:
                range_text = ", ".join(
                    f"{column}=[{limits[0]:.1f},{limits[1]:.1f}]"
                    for column, limits in weather_ranges.items()
                )
                add(findings, "PASS", "weather_grid_range_contract", forecast_path, range_text)

        pv_limit_w = float(nested(cfg, "model", "pv_power_limit_w", default=0.0))
        declared_limit_w = float(
            nested(cfg, "identification", "pv_system_evidence", "aggregate_power_limit_w", default=0.0)
        )
        if pv_limit_w <= 0.0 or abs(pv_limit_w - declared_limit_w) > 1.0e-6:
            add(
                findings,
                "ERROR",
                "pv_hardware_limit_contract",
                path,
                f"model limit={pv_limit_w} W, evidence limit={declared_limit_w} W",
            )
        else:
            add(findings, "PASS", "pv_hardware_limit_contract", path, f"declared aggregate MPPT limit={pv_limit_w} W")


def audit_blank_templates(findings: list[Finding]) -> None:        # [関数定義] audit_blank_templates の処理実行ブロック
    strict_blank_distribution = (ROOT / "solarcar_blank_manifest.json").is_file()
    for name in ("bwsc2027_template", "other_template"):
        root = ROOT / "project_packages" / name
        files = [
            *(root / "data" / "route").glob("*.csv"),
            *(root / "data" / "weather").glob("*.csv"),
            *(root / "maps").glob("*.csv"),
        ]
        if strict_blank_distribution:
            files.extend((root / "data" / "identification" / "raw").glob("*.csv"))
        populated: list[str] = []
        for path in files:
            if not path.is_file():
                populated.append(f"missing:{path.name}")
                continue
            nonempty = [line for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
            if len(nonempty) > 1:
                populated.append(f"{path.name}:{len(nonempty)} lines")
        if populated:
            add(findings, "ERROR", "blank_template", root, ", ".join(populated))
        else:
            add(findings, "PASS", "blank_template", root, f"{len(files)} route/weather/map/replay files are schema-only")


def write_report(output_dir: Path, python_count: int, findings: list[Finding]) -> None:  # [関数定義] write_report の処理実行ブロック
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    counts = {level: sum(item.severity == level for item in findings) for level in ("PASS", "WARN", "ERROR")}
    payload = {
        "generated_utc": now,
        "python_files_parsed": python_count,
        "counts": counts,
        "findings": [asdict(item) for item in findings],
    }
    (output_dir / "solar_package_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Solar package static audit",
        "",
        f"- Generated UTC: {now}",
        f"- Python files parsed: {python_count}",
        f"- PASS/WARN/ERROR: {counts['PASS']}/{counts['WARN']}/{counts['ERROR']}",
        "",
        "| Result | Check | Path | Detail |",
        "|---|---|---|---|",
    ]
    for item in findings:
        detail = item.detail.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {item.severity} | {item.check} | {item.path} | {detail} |")
    (output_dir / "solar_package_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:                                                 # [関数定義] main の処理実行ブロック
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs" / "package_inventory")  # [CLI引数] コマンドライン実行引数の定義
    args = parser.parse_args()
    output_dir = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    findings: list[Finding] = []
    count, trees = audit_python(findings)
    audit_local_import_closure(findings, trees)
    audit_launch_contracts(findings, trees)
    blank_distribution = (ROOT / "solarcar_blank_manifest.json").is_file()
    warned_fitted_packages: set[Path] = set()
    for path in primary_profile_paths():
        if blank_distribution and MLE_PACKAGE_RE.match(path.parent.name):
            add(findings, "PASS", "profile_absent_by_design", path, "blank distribution excludes fitted history")
            continue
        fitted_match = MLE_PACKAGE_RE.match(path.parent.name)
        if fitted_match and not fitted_package_high_precision_allowed(path.parent):
            profile_findings: list[Finding] = []
            audit_profile(profile_findings, path)
            for item in profile_findings:
                if item.severity == "ERROR":
                    item.severity = "WARN"
                    item.detail = f"non-adopted historical profile: {item.detail}"
            findings.extend(profile_findings)
            if path.parent not in warned_fitted_packages:
                add(
                    findings,
                    "WARN",
                    "fitted_profile_adoption",
                    path.parent,
                    "no acceptance report permits a high-precision claim; do not use this fitted history as a live vehicle model",
                )
                warned_fitted_packages.add(path.parent)
            continue
        audit_profile(findings, path)
    audit_blank_templates(findings)
    write_report(output_dir, count, findings)
    errors = sum(item.severity == "ERROR" for item in findings)
    print(f"python_files={count} errors={errors} output={output_dir}")
    return 1 if errors else 0                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


if __name__ == "__main__":
    raise SystemExit(main())