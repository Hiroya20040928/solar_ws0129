#!/usr/bin/env python3
"""Build the minimal current solar-car MLE/CEM/race-operation package."""

from __future__ import annotations

import argparse
import ast
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

import yaml


ROOT = Path(__file__).resolve().parents[1]
EXPORTS = ROOT / "exports"
SOURCE_PACKAGE = ROOT / "project_packages" / "bwsc2025_fitted_mle19_energywindow_inertia"
SOURCE_PROFILE = SOURCE_PACKAGE / "profile_mle36_battery_deconfounded_neutral_quick_20260803.yaml"
SOURCE_RUN = SOURCE_PACKAGE / "outputs" / "identification" / "runs" / "mle36_battery_deconfounded_neutral_quick_20260803"
SOURCE_EXPERIMENT = SOURCE_PACKAGE / "outputs" / "identification" / "experiments" / "mle36_battery_deconfounded_neutral_quick_20260803"
SOURCE_SUMMARY = SOURCE_RUN / "bwsc2025_fitted_mle19_energywindow_inertia_generic_fit_summary.yaml"
SOURCE_TERMINAL = SOURCE_RUN / "terminal_soc_consistency.yaml"
SOURCE_IDENTIFICATION_MANIFEST = SOURCE_EXPERIMENT / "inputs" / "identification_manifest.yaml"
SOURCE_EXPERIMENT_STATUS = SOURCE_EXPERIMENT / "experiment_status.json"
SOURCE_MODEL_GATE = SOURCE_EXPERIMENT / "model_validation_gate.json"
ARTIFACT_STEM = "solarcar_minimal_latest_mle36_20260803"
DEFAULT_OUTPUT = EXPORTS / f"{ARTIFACT_STEM}.zip"

RUNTIME_SEEDS = (
    "scripts/solar_sim.py",
    "scripts/fetch_weather_forecast.py",
    "launch/solarcar_sim.launch.py",
    "launch/solar_race_live.launch.py",
    "launch/solar_race_live_wifi.launch.py",
    "mpc_solarcar/gps_sim_node.py",
    "mpc_solarcar/mpc_node.py",
    "mpc_solarcar/dashboard_node.py",
    "mpc_solarcar/distance_node.py",
    "mpc_solarcar/solar_logger_node.py",
    "mpc_solarcar/solar_preflight_node.py",
    "mpc_solarcar/grade_node.py",
    "mpc_solarcar/weather_fetch_node.py",
    "mpc_solarcar/solar_autocal_node.py",
    "mpc_solarcar/speed_command_bridge_node.py",
    "mpc_solarcar/telemetry_text_bridge_node.py",
    "mpc_solarcar/wind_correction_node.py",
    "mpc_solarcar/solar_state_node.py",
)

MLE_SEEDS = (
    "scripts/run_vehicle_identification.py",
    "scripts/run_rint_shape_constrained_mle_experiment.py",
    "scripts/fit_battery_ecm_from_pulses.py",
    "scripts/audit_identification_residuals.py",
    "scripts/check_model_validation_gate.py",
    "scripts/compare_identification_runs.py",
    "scripts/promote_identification_run.py",
    "scripts/regenerate_identification_report.py",
    "scripts/build_identification_evidence_bundle.py",
    "scripts/assess_terminal_soc_consistency.py",
    "scripts/adopt_conditional_identification_candidate.py",
    "scripts/create_operational_fine_profile.py",
    "scripts/build_historical_weather_counterfactual_grid.py",
)

CEM_SEEDS = (
    "scripts/gpu_upper_policy_search.py",
    "scripts/tune_upper_planner_weights.py",
    "scripts/check_gpu_surrogate_feasibility.py",
    "scripts/check_policy_weather_input.py",
    "scripts/rank_gpu_upper_policy_candidates.py",
    "scripts/validate_gpu_upper_policy_candidates.py",
    "scripts/merge_exact_candidate_rankings.py",
    "scripts/run_upper_mesh_convergence.py",
)

STATIC_FILES = (
    "package.xml",
    "setup.cfg",
    "mpc_solarcar/__init__.py",
    "resource/mpc_solarcar",
    "scripts/bootstrap_ubuntu_humble.sh",
    "scripts/setup_gpu_server_env.sh",
    "scripts/run_vehicle_identification_cpu.sbatch",
    "scripts/submit_solar_gpu_multifidelity_campaign.sh",
    "scripts/resubmit_solar_gpu_refinement_chain.sh",
    "scripts/run_solar_upper_gpu_search.sbatch",
    "scripts/run_solar_gpu_concurrent_campaign.sbatch",
    "scripts/finalize_solar_gpu_campaign.sbatch",
    "scripts/run_solar_gpu_acceptance_pipeline.sbatch",
    "scripts/run_solar_fullsim_cpu.sbatch",
    "scripts/run_solar_mesh_convergence_cpu.sbatch",
)

ENTRY_POINTS = (
    "gps_sim_node = mpc_solarcar.gps_sim_node:main",
    "mpc_node = mpc_solarcar.mpc_node:main",
    "dashboard_node = mpc_solarcar.dashboard_node:main",
    "distance_node = mpc_solarcar.distance_node:main",
    "solar_logger_node = mpc_solarcar.solar_logger_node:main",
    "solar_preflight_node = mpc_solarcar.solar_preflight_node:main",
    "grade_node = mpc_solarcar.grade_node:main",
    "weather_fetch_node = mpc_solarcar.weather_fetch_node:main",
    "solar_autocal_node = mpc_solarcar.solar_autocal_node:main",
    "speed_command_bridge_node = mpc_solarcar.speed_command_bridge_node:main",
    "telemetry_text_bridge_node = mpc_solarcar.telemetry_text_bridge_node:main",
    "wind_correction_node = mpc_solarcar.wind_correction_node:main",
    "solar_state_node = mpc_solarcar.solar_state_node:main",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_source(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError(f"Source escapes repository: {path}") from exc
    if not resolved.is_file():
        raise FileNotFoundError(path)
    return resolved


def copy_source(relative: str, stage: Path) -> Path:
    source = ensure_source(ROOT / relative)
    destination = stage / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return destination


def module_candidates(module: str) -> list[Path]:
    relative = Path(*module.split("."))
    candidates = [ROOT / f"{relative}.py", ROOT / relative / "__init__.py"]
    if len(relative.parts) == 1:
        candidates.extend((ROOT / "scripts" / f"{relative}.py", ROOT / "mpc_solarcar" / f"{relative}.py"))
    return candidates


def imported_local_files(path: Path) -> set[Path]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[Path] = set()
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package_dir = path.parent
                for _ in range(max(node.level - 1, 0)):
                    package_dir = package_dir.parent
                if node.module:
                    candidate = package_dir / Path(*node.module.split("."))
                    modules.append(candidate.relative_to(ROOT).as_posix().replace("/", "."))
                else:
                    for alias in node.names:
                        candidate = package_dir / alias.name
                        modules.append(candidate.relative_to(ROOT).as_posix().replace("/", "."))
            elif node.module:
                modules.append(node.module)
        for module in modules:
            for candidate in module_candidates(module):
                if candidate.is_file():
                    found.add(candidate.resolve())
                    break
    return found


def dependency_closure(seeds: tuple[str, ...]) -> set[Path]:
    pending = [ensure_source(ROOT / seed) for seed in seeds]
    selected: set[Path] = set()
    while pending:
        path = pending.pop()
        if path in selected:
            continue
        selected.add(path)
        for dependency in imported_local_files(path):
            if dependency not in selected:
                pending.append(dependency)
    return selected


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_mpc_node(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.find("    # -------------------- passo mode --------------------")
    main = text.find("\ndef main(")
    if start < 0 or main < 0 or start >= main:
        raise RuntimeError("Could not isolate the legacy vehicle branch in mpc_node.py")
    text = text[:start].rstrip() + "\n\n" + text[main:]
    text = re.sub(
        r"(?s)        self\.declare_parameter\('passo_mode', False\)\n"
        r"        self\.passo_mode = bool\(self\.get_parameter\('passo_mode'\)\.value\)\n"
        r"        if self\.passo_mode:\n"
        r"            self\._init_passo\(\)\n"
        r"        else:\n"
        r"            self\._init_solar\(\)",
        "        self._init_solar()",
        text,
        count=1,
    )
    text = re.sub(
        r'(?s)class MPCNode\(Node\):\n    """.*?    """',
        'class MPCNode(Node):\n    """Solar-car MPC node."""',
        text,
        count=1,
    )
    if "_init_passo" in text or "passo_mode" in text.lower():
        raise RuntimeError("Legacy vehicle code remains in staged mpc_node.py")
    write_text(path, text)


def patch_control_script(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'^profile="\$\{3:-[^}]+\}"', 'profile="${3:-project_packages/latest/profile.yaml}"', text, count=1, flags=re.M)
    text = text.replace("sim|measure|live|live_wifi", "sim|live|live_wifi")
    text = text.replace("sim/measure/live/live_wifi", "sim/live/live_wifi")
    text = text.replace("solarcar_sim|solar_measurement|solar_race_live|solar_race_live_wifi", "solarcar_sim|solar_race_live|solar_race_live_wifi")
    text = text.replace("|_measurement", "")
    text = re.sub(r'\n\s*measure\)\s*launch_file="solar_measurement\.launch\.py"\s*;;', "", text)
    validation = """
case "$action" in
  up|build|start|stop|restart|status|simulate|forecast|fit|learn|log) ;;
  *) usage; exit 2 ;;
esac
"""
    anchor = 'profile="${3:-project_packages/latest/profile.yaml}"\n'
    if anchor not in text:
        raise RuntimeError("Could not patch solar_control.sh profile")
    text = text.replace(anchor, anchor + validation, 1)
    write_text(path, text)


def patch_windows_wrapper(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r'\[ValidateSet\([^\]]+\)\]\s*\[string\]\$Action',
        '[ValidateSet("up", "build", "start", "stop", "restart", "status", "simulate", "forecast", "fit", "learn", "log")] [string]$Action',
        text,
        count=1,
    )
    text = re.sub(
        r'\[ValidateSet\("sim",\s*"measure",\s*"live",\s*"live_wifi"\)\]',
        '[ValidateSet("sim", "live", "live_wifi")]',
        text,
        count=1,
    )
    text = text.replace(
        "[ValidateSet('sim', 'measure', 'live', 'live_wifi')]",
        "[ValidateSet('sim', 'live', 'live_wifi')]",
    )
    text = text.replace("@('sim', 'measure', 'live', 'live_wifi')", "@('sim', 'live', 'live_wifi')")
    text = re.sub(
        r'\[string\]\$Profile\s*=\s*"[^"]+"',
        '[string]$Profile = "project_packages/latest/profile.yaml"',
        text,
        count=1,
    )
    text = re.sub(
        r"(?s)    'up' \{.*?\n    \}\n    'build' \{",
        "    'up' {\n        Invoke-SolarControl -ControlAction 'up' -ControlMode $Mode -ControlProfile $Profile\n    }\n    'build' {",
        text,
        count=1,
    )
    text = text.replace("sim / measure / live / live_wifi", "sim / live / live_wifi")
    text = text.replace("sim, measure, live, live_wifi", "sim, live, live_wifi")
    write_text(path, text)


def setup_py_text() -> str:
    entries = "\n".join(f'            "{entry}",' for entry in ENTRY_POINTS)
    return f'''from glob import glob
import os
from setuptools import find_packages, setup


package_name = "mpc_solarcar"


def data_files_under(directory):
    result = []
    if not os.path.isdir(directory):
        return result
    for root, _, files in os.walk(directory):
        if files:
            result.append((os.path.join("share", package_name, root), [os.path.join(root, name) for name in files]))
    return result


data_files = [
    ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
    ("share/" + package_name, ["package.xml"]),
]
for directory in ("launch", "dashboard", "project_packages"):
    data_files.extend(data_files_under(directory))


setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=("test", "tests")),
    data_files=data_files,
    install_requires=["setuptools", "numpy", "scipy", "osqp", "pyyaml", "aiohttp"],
    zip_safe=True,
    maintainer="solarcar team",
    maintainer_email="solarcar@example.com",
    description="Minimal current solar-car MLE, CEM, simulation, and race operation package",
    license="Apache-2.0",
    entry_points={{
        "console_scripts": [
{entries}
        ],
    }},
)
'''


def package_xml_text() -> str:
    return '''<?xml version="1.0"?>
<package format="3">
  <name>mpc_solarcar</name>
  <version>0.1.0</version>
  <description>Minimal current solar-car MLE, CEM, simulation, and race operation package</description>
  <maintainer email="solarcar@example.com">solarcar team</maintainer>
  <license>Apache-2.0</license>
  <buildtool_depend>ament_python</buildtool_depend>
  <exec_depend>rclpy</exec_depend>
  <exec_depend>std_msgs</exec_depend>
  <exec_depend>sensor_msgs</exec_depend>
  <exec_depend>nav_msgs</exec_depend>
  <exec_depend>geometry_msgs</exec_depend>
  <exec_depend>rosgraph_msgs</exec_depend>
  <exec_depend>launch</exec_depend>
  <exec_depend>launch_ros</exec_depend>
  <exec_depend>python3-numpy</exec_depend>
  <exec_depend>python3-scipy</exec_depend>
  <exec_depend>python3-yaml</exec_depend>
  <export><build_type>ament_python</build_type></export>
</package>
'''


def requirements_text() -> str:
    return """setuptools
numpy==2.4.4
scipy==1.18.0
pandas==3.0.3
PyYAML==6.0.3
matplotlib==3.10.9
casadi==3.7.2
osqp
aiohttp
torch==2.5.1
"""


def relative_posix(path: Path, base: Path) -> str:
    return path.relative_to(base).as_posix()


def resolve_profile_path(raw: str) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return ensure_source(candidate)
    for base in (SOURCE_PACKAGE, ROOT):
        path = base / candidate
        if path.is_file():
            return ensure_source(path)
    raise FileNotFoundError(f"Profile asset not found: {raw}")


def materialize_profile(stage: Path) -> tuple[dict, dict[str, dict[str, str | int]]]:
    profile = yaml.safe_load(SOURCE_PROFILE.read_text(encoding="utf-8"))
    source_manifest = yaml.safe_load(SOURCE_IDENTIFICATION_MANIFEST.read_text(encoding="utf-8"))
    source_status = json.loads(SOURCE_EXPERIMENT_STATUS.read_text(encoding="utf-8"))
    source_gate = json.loads(SOURCE_MODEL_GATE.read_text(encoding="utf-8"))
    latest_root = stage / "project_packages" / "latest"
    assets_root = latest_root / "runtime_assets"
    assets_root.mkdir(parents=True, exist_ok=True)
    source_cache: dict[Path, str] = {}
    lineage: dict[str, dict[str, str | int]] = {}

    def copy_asset(source: Path, label: str) -> str:
        source = ensure_source(source)
        if source in source_cache:
            return source_cache[source]
        suffix = "".join(source.suffixes) or ".dat"
        safe_label = re.sub(r"[^a-z0-9_]+", "_", label.lower()).strip("_")
        destination = assets_root / f"{safe_label}{suffix}"
        serial = 2
        while destination.exists():
            destination = assets_root / f"{safe_label}_{serial}{suffix}"
            serial += 1
        shutil.copyfile(source, destination)
        relative = relative_posix(destination, latest_root)
        source_cache[source] = relative
        lineage[relative] = {
            "source": relative_posix(source, ROOT),
            "size": source.stat().st_size,
            "sha256": sha256(source),
        }
        return relative

    required_path_keys = {
        "route_profile_csv",
        "forecast_csv",
        "stop_yaml",
        "drive_schedule_yaml",
        "drive_efficiency_map_csv",
        "regen_efficiency_map_csv",
        "rint_map_csv",
        "panel_efficiency_map_csv",
        "mppt_efficiency_map_csv",
        "ocv_soc_curve_csv",
    }
    missing: list[str] = []
    for key, raw in list(profile.get("paths", {}).items()):
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            source = resolve_profile_path(raw)
        except FileNotFoundError:
            if key in required_path_keys:
                missing.append(key)
            continue
        profile["paths"][key] = copy_asset(source, key)
    if missing:
        raise RuntimeError(f"Required profile assets are missing: {', '.join(sorted(missing))}")

    minimal_identification = {
        "inputs": copy.deepcopy(source_manifest.get("inputs", {})),
        "options": copy.deepcopy(source_manifest.get("options", {})),
        "builder": copy.deepcopy(source_manifest.get("builder", {})),
    }
    for key, raw in list(minimal_identification["inputs"].items()):
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            source = resolve_profile_path(raw)
        except FileNotFoundError:
            candidate = SOURCE_EXPERIMENT / raw
            source = ensure_source(candidate)
        minimal_identification["inputs"][key] = "../" + copy_asset(source, f"identification_input_{key}")

    identification_dir = latest_root / "data" / "identification"
    identification_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = identification_dir / "identification_manifest.yaml"
    write_text(manifest_path, yaml.safe_dump(minimal_identification, sort_keys=False, allow_unicode=True))

    summary_ref = copy_asset(SOURCE_SUMMARY, "identification_fit_summary")
    terminal_ref = copy_asset(SOURCE_TERMINAL, "terminal_soc_consistency")
    source_gate["fit_summary_yaml"] = summary_ref
    source_gate["terminal_consistency_yaml"] = terminal_ref
    gate_path = assets_root / "model_validation_gate.json"
    write_text(gate_path, json.dumps(source_gate, ensure_ascii=False, indent=2) + "\n")
    gate_ref = relative_posix(gate_path, latest_root)
    lineage[gate_ref] = {
        "source": relative_posix(SOURCE_MODEL_GATE, ROOT),
        "size": SOURCE_MODEL_GATE.stat().st_size,
        "sha256": sha256(SOURCE_MODEL_GATE),
    }

    status_keys = (
        "tag",
        "status",
        "physical_evidence_gate_pass",
        "release_eligible",
        "reason",
        "projection",
        "ocv_projection",
        "projection_mode",
        "map_shape_fit_enabled",
        "model_validation_gate_pass",
        "baseline_fit_quality",
        "candidate_fit_quality",
        "metrics",
        "parameter_changes",
    )
    neutral_status = {key: source_status[key] for key in status_keys if key in source_status}
    status_path = assets_root / "candidate_status.json"
    write_text(status_path, json.dumps(neutral_status, ensure_ascii=False, indent=2) + "\n")
    status_ref = relative_posix(status_path, latest_root)
    lineage[status_ref] = {
        "source": relative_posix(SOURCE_EXPERIMENT_STATUS, ROOT),
        "size": SOURCE_EXPERIMENT_STATUS.stat().st_size,
        "sha256": sha256(SOURCE_EXPERIMENT_STATUS),
    }

    profile.setdefault("identification", {})
    profile["identification"]["manifest_yaml"] = "data/identification/identification_manifest.yaml"
    profile["identification"]["fit_summary_yaml"] = summary_ref
    profile["identification"]["terminal_soc_consistency_yaml"] = terminal_ref
    profile["identification"]["candidate_status_json"] = status_ref
    profile["identification"]["model_validation_gate_json"] = gate_ref
    profile["identification"]["input_dir"] = "runtime_assets"
    profile.setdefault("simulation", {})
    profile["simulation"]["output_dir"] = "outputs/prerace"
    profile["simulation"]["latest_manifest_json"] = "outputs/prerace/latest_run.json"
    profile.setdefault("meta", {})
    profile["meta"].update(
        {
            "name": "solarcar_latest_mle36_20260803",
            "selected_candidate": "mle36_battery_deconfounded_neutral_quick_20260803",
            "candidate_experiment_status": "complete",
            "identification_pipeline_completion_marker": False,
            "release_status": "research_only_unidentified_battery_maps",
            "production_live_allowed": False,
        }
    )
    profile_path = latest_root / "profile.yaml"
    write_text(profile_path, yaml.safe_dump(profile, sort_keys=False, allow_unicode=True))
    return profile, lineage


def source_git_state() -> dict[str, str | bool | None]:
    def git(*args: str) -> str | None:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else None

    status = git("status", "--porcelain")
    return {
        "commit": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "worktree_dirty": bool(status),
    }


def compile_python(stage: Path) -> None:
    for path in sorted(stage.rglob("*.py")):
        compile(path.read_text(encoding="utf-8"), str(path), "exec")


def validate_stage(stage: Path, profile: dict) -> None:
    forbidden_path_parts = ("docs", "test", "tests", "magnetic", "passo", "measurement", "__pycache__")
    old_generation = re.compile(r"mle(?:[0-2]?\d|3[0-5])(?:\D|$)", re.I)
    violations: list[str] = []
    for path in sorted(stage.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(stage).as_posix().lower()
        if path.suffix.lower() in {".pyc", ".pyo"}:
            violations.append(relative)
        if any(part in relative.split("/") for part in forbidden_path_parts):
            violations.append(relative)
        if old_generation.search(relative):
            violations.append(relative)
    if violations:
        raise RuntimeError("Forbidden staged paths: " + ", ".join(sorted(set(violations))))

    for key, raw in profile.get("paths", {}).items():
        if isinstance(raw, str) and raw and not raw.startswith(("http://", "https://")):
            target = stage / "project_packages" / "latest" / raw
            if key in {
                "route_profile_csv", "forecast_csv", "stop_yaml", "drive_schedule_yaml",
                "drive_efficiency_map_csv", "regen_efficiency_map_csv", "rint_map_csv",
                "panel_efficiency_map_csv", "mppt_efficiency_map_csv", "ocv_soc_curve_csv",
            } and not target.is_file():
                raise RuntimeError(f"Rewritten profile path is missing: {key} -> {raw}")

    setup_text = (stage / "setup.py").read_text(encoding="utf-8").lower()
    mpc_text = (stage / "mpc_solarcar" / "mpc_node.py").read_text(encoding="utf-8").lower()
    wrapper_text = (stage / "SolarSim.ps1").read_text(encoding="utf-8").lower()
    control_text = (stage / "scripts" / "solar_control.sh").read_text(encoding="utf-8").lower()
    for token, text in (
        ("python-can", setup_text),
        ("passo_mode", mpc_text),
        ("measure", wrapper_text),
        ("measure", control_text),
    ):
        if token in text:
            raise RuntimeError(f"Forbidden capability remains in package: {token}")
    if profile.get("meta", {}).get("production_live_allowed") is not False:
        raise RuntimeError("Latest unpromoted candidate lost its production live safety block")
    compile_python(stage)


def run_smoke_tests(stage: Path) -> list[dict[str, object]]:
    clean_env = os.environ.copy()
    clean_env["PYTHONDONTWRITEBYTECODE"] = "1"
    commands = [
        [sys.executable, "scripts/run_vehicle_identification.py", "--help"],
        [sys.executable, "scripts/tune_upper_planner_weights.py", "--help"],
        [sys.executable, "scripts/solar_sim.py", "--help"],
    ]
    results: list[dict[str, object]] = []
    for command in commands:
        result = subprocess.run(
            command, cwd=stage, text=True, capture_output=True, check=False, timeout=120, env=clean_env
        )
        results.append({"command": command[1:], "status": "passed", "returncode": result.returncode})
        if result.returncode:
            details = (result.stdout + "\n" + result.stderr)[-4000:]
            raise RuntimeError(f"Smoke test failed: {' '.join(command)}\n{details}")
    torch_check = subprocess.run(
        [sys.executable, "-c", "import torch"],
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env=clean_env,
    )
    gpu_command = [sys.executable, "scripts/gpu_upper_policy_search.py", "--help"]
    if torch_check.returncode:
        results.append(
            {
                "command": gpu_command[1:],
                "status": "not_run_missing_host_dependency",
                "dependency": "torch==2.5.1",
                "dependency_installer": "scripts/setup_gpu_server_env.sh",
            }
        )
    else:
        result = subprocess.run(
            gpu_command, cwd=stage, text=True, capture_output=True, check=False, timeout=120, env=clean_env
        )
        if result.returncode:
            details = (result.stdout + "\n" + result.stderr)[-4000:]
            raise RuntimeError(f"Smoke test failed: {' '.join(gpu_command)}\n{details}")
        results.append({"command": gpu_command[1:], "status": "passed", "returncode": 0})
    return results


def inventory(stage: Path) -> list[dict[str, str | int]]:
    records = []
    for path in sorted(stage.rglob("*")):
        if path.is_file() and path.name != "PACKAGE_MANIFEST.json":
            records.append(
                {
                    "path": relative_posix(path, stage),
                    "size": path.stat().st_size,
                    "sha256": sha256(path),
                }
            )
    return records


def create_zip(stage: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                archive.write(path, f"{ARTIFACT_STEM}/{relative_posix(path, stage)}")
    with zipfile.ZipFile(output, "r") as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC validation failed: {bad}")


def build(output: Path, force: bool) -> dict[str, object]:
    output = output.resolve()
    try:
        output.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise RuntimeError("Output must remain inside this repository") from exc
    if output.exists():
        if not force:
            raise FileExistsError(f"Output exists; pass --force to replace it: {output}")
        output.unlink()

    required = (
        SOURCE_PROFILE,
        SOURCE_SUMMARY,
        SOURCE_TERMINAL,
        SOURCE_IDENTIFICATION_MANIFEST,
        SOURCE_EXPERIMENT_STATUS,
        SOURCE_MODEL_GATE,
    )
    for path in required:
        ensure_source(path)

    with tempfile.TemporaryDirectory(prefix="solarcar_minimal_latest_") as temp_dir:
        stage = Path(temp_dir) / ARTIFACT_STEM
        stage.mkdir()
        selected_python = dependency_closure(RUNTIME_SEEDS + MLE_SEEDS + CEM_SEEDS)
        for source in sorted(selected_python):
            copy_source(relative_posix(source, ROOT), stage)
        for relative in STATIC_FILES:
            copy_source(relative, stage)
        for source in sorted((ROOT / "dashboard").rglob("*")):
            if source.is_file():
                copy_source(relative_posix(source, ROOT), stage)
        copy_source("SolarSim.ps1", stage)
        copy_source("scripts/solar_control.sh", stage)

        patch_mpc_node(stage / "mpc_solarcar" / "mpc_node.py")
        patch_control_script(stage / "scripts" / "solar_control.sh")
        patch_windows_wrapper(stage / "SolarSim.ps1")
        write_text(stage / "setup.py", setup_py_text())
        write_text(stage / "package.xml", package_xml_text())
        write_text(stage / "requirements.txt", requirements_text())

        profile, lineage = materialize_profile(stage)
        validate_stage(stage, profile)
        smoke_tests = run_smoke_tests(stage)
        validate_stage(stage, profile)
        manifest = {
            "schema_version": 1,
            "package_name": ARTIFACT_STEM,
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "semantic_version": "0.1.0",
            "source_git": source_git_state(),
            "selected_candidate": "mle36_battery_deconfounded_neutral_quick_20260803",
            "candidate_experiment_status": "complete",
            "candidate_experiment_complete": True,
            "identification_pipeline_completion_marker": False,
            "release_status": profile["meta"]["release_status"],
            "production_live_allowed": False,
            "scope": [
                "latest MLE vehicle fitting and battery-map candidate inputs",
                "CEM upper-policy search and validation",
                "solar-car simulation",
                "ROS 2 live and live_wifi race operation",
                "race dashboard and telemetry bridges",
            ],
            "excluded": [
                "all older MLE generation directory trees and profiles",
                "documentation and reports",
                "measure mode",
                "non-solar vehicle and magnetic-coupler programs",
                "tests, historical replay outputs, and development packaging tools",
            ],
            "runtime_asset_lineage": lineage,
            "smoke_tests": smoke_tests,
            "files": inventory(stage),
        }
        write_text(stage / "PACKAGE_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        create_zip(stage, output)

    return {
        "output": str(output),
        "size": output.stat().st_size,
        "sha256": sha256(output),
        "files": len(manifest["files"]) + 1,
        "selected_candidate": manifest["selected_candidate"],
        "production_live_allowed": manifest["production_live_allowed"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = build(args.output, args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
