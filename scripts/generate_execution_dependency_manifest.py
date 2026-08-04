#!/usr/bin/env python3
"""Build the source/input manifest for every supported solar-car workflow.

The manifest intentionally excludes runtime products, old identification runs,
logs, reports, caches, and build/install trees.  A file below ``outputs`` is
included only when a current profile consumes it as an adopted model input.
"""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PACKAGE = ROOT / "project_packages" / "bwsc2025_fitted_mle19_energywindow_inertia"
DEFAULT_RESEARCH_RUN = (
    DEFAULT_PACKAGE
    / "outputs"
    / "identification"
    / "runs"
    / "mle35_expanded_grade_single_source_ultra_v1"
)

IGNORED_PARTS = {
    ".git",
    ".run",
    "__pycache__",
    "build",
    "install",
    "log",
    "logs",
    "node_modules",
    "reports",
    "tensorboard",
}
IGNORED_SUFFIXES = {
    ".aux",
    ".bak",
    ".log",
    ".out",
    ".pyc",
    ".pyo",
    ".toc",
}
PATH_SUFFIXES = {
    ".csv",
    ".json",
    ".md",
    ".pdf",
    ".pptx",
    ".txt",
    ".url",
    ".xls",
    ".xlsx",
    ".yaml",
    ".yml",
}


@dataclass
class Record:
    path: Path
    categories: set[str]
    workflows: set[str]
    roles: set[str]
    exception: str = ""


class Manifest:
    def __init__(self) -> None:
        self.records: dict[Path, Record] = {}
        self.missing: list[tuple[str, str]] = []

    def add(
        self,
        raw_path: str | Path,
        category: str,
        workflow: str,
        role: str,
        *,
        required: bool = True,
        exception: str = "",
    ) -> None:
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        path = path.resolve()
        if not path.is_file():
            if required:
                self.missing.append((self.relative(path), workflow))
            return
        if self._globally_excluded(path) and not exception:
            return
        record = self.records.get(path)
        if record is None:
            record = Record(path, set(), set(), set(), exception)
            self.records[path] = record
        record.categories.add(category)
        record.workflows.add(workflow)
        record.roles.add(role)
        if exception:
            record.exception = exception

    def add_tree(
        self,
        raw_dir: str | Path,
        category: str,
        workflow: str,
        role: str,
        *,
        suffixes: set[str] | None = None,
        exception: str = "",
    ) -> None:
        directory = Path(raw_dir)
        if not directory.is_absolute():
            directory = ROOT / directory
        if not directory.is_dir():
            self.missing.append((self.relative(directory), workflow))
            return
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            if suffixes is not None and path.suffix.lower() not in suffixes:
                continue
            self.add(path, category, workflow, role, exception=exception)

    @staticmethod
    def relative(path: Path) -> str:
        try:
            return path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _globally_excluded(path: Path) -> bool:
        rel_parts = set(path.parts)
        if rel_parts & IGNORED_PARTS:
            return True
        return path.suffix.lower() in IGNORED_SUFFIXES


def local_imports(path: Path) -> set[Path]:
    """Return repository-local Python modules imported by *path*."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return set()
    absolute_modules: set[str] = set()
    relative_candidates: set[Path] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            absolute_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                # For a module at package/file.py, one dot means package/.
                # Each additional dot moves one directory upward.
                package_dir = path.parent
                for _ in range(node.level - 1):
                    package_dir = package_dir.parent
                module_base = package_dir.joinpath(*base.split(".")) if base else package_dir
                relative_candidates.add(module_base.with_suffix(".py"))
                relative_candidates.add(module_base / "__init__.py")
                for alias in node.names:
                    relative_candidates.add(module_base / f"{alias.name}.py")
            else:
                if base:
                    absolute_modules.add(base)
                if base in {"mpc_solarcar", "scripts", ""}:
                    absolute_modules.update(
                        f"{base}.{alias.name}".strip(".") for alias in node.names
                    )
    out: set[Path] = set()
    for candidate in relative_candidates:
        if candidate.is_file():
            out.add(candidate.resolve())
    for module in absolute_modules:
        parts = module.split(".")
        candidates = [ROOT.joinpath(*parts).with_suffix(".py")]
        if path.parent.name == "scripts":
            candidates.append(ROOT / "scripts" / f"{parts[-1]}.py")
        for candidate in candidates:
            if candidate.is_file():
                out.add(candidate.resolve())
                break
    return out


def add_python_closure(
    manifest: Manifest,
    seeds: Iterable[str | Path],
    category: str,
    workflow: str,
    role: str,
) -> None:
    queue = deque((ROOT / seed).resolve() for seed in seeds)
    seen: set[Path] = set()
    while queue:
        path = queue.popleft()
        if path in seen:
            continue
        seen.add(path)
        manifest.add(path, category, workflow, role)
        queue.extend(local_imports(path) - seen)


def resolve_declared_path(base_dir: Path, raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    local = (base_dir / candidate).resolve()
    if local.exists():
        return local
    return (ROOT / candidate).resolve()


def iter_declared_paths(value, key: str = ""):
    if isinstance(value, dict):
        for child_key, child_value in value.items():
            yield from iter_declared_paths(child_value, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from iter_declared_paths(child, key)
    elif isinstance(value, str):
        suffix = Path(value).suffix.lower()
        if suffix in PATH_SUFFIXES or "/" in value or "\\" in value:
            yield key, value


def add_profile_assets(
    manifest: Manifest,
    profile: Path,
    category: str,
    workflow: str,
    *,
    research_exception: bool = False,
) -> None:
    exception = "active research input under outputs" if research_exception else ""
    manifest.add(profile, category, workflow, "workflow profile", exception=exception)
    if not profile.is_file():
        return
    doc = yaml.safe_load(profile.read_text(encoding="utf-8")) or {}
    destination_keys = {
        "corrected_forecast_csv",
        "latest_manifest_json",
        "log_dir",
        "output_dir",
        "raw_forecast_csv",
    }
    for key, raw in iter_declared_paths(doc):
        if key in destination_keys:
            continue
        path = resolve_declared_path(profile.parent, raw)
        if not path.is_file():
            if key.endswith(("_csv", "_yaml", "_map")):
                manifest.missing.append((Manifest.relative(path), workflow))
            continue
        in_outputs = "outputs" in path.parts
        active_output = (
            "adopted_maps" in path.parts
            or key in {"fit_summary_yaml", "terminal_consistency_yaml"}
            or (research_exception and DEFAULT_RESEARCH_RUN in path.parents)
        )
        if in_outputs and not active_output:
            continue
        manifest.add(
            path,
            category,
            workflow,
            f"profile reference: {key}",
            exception=(
                "active research input under outputs"
                if in_outputs and research_exception
                else (
                    "current profile consumes adopted model input under outputs"
                    if in_outputs
                    else ""
                )
            ),
        )


def add_manifest_assets(manifest: Manifest, manifest_path: Path) -> None:
    manifest.add(
        manifest_path,
        "identification input",
        "MLE/re-identification",
        "identification schema and source declaration",
    )
    if not manifest_path.is_file():
        return
    doc = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    for key, raw in iter_declared_paths(doc):
        path = resolve_declared_path(manifest_path.parents[2], raw)
        if path.is_dir():
            # Source evidence directories are provenance inputs.  Exclude derived
            # screenshots/scripts and keep only data/specification documents.
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in PATH_SUFFIXES - {".png", ".py"}:
                    manifest.add(
                        child,
                        "identification evidence",
                        "MLE/re-identification",
                        f"declared evidence directory: {key}",
                    )
            continue
        if not path.is_file():
            continue
        if "outputs" in path.parts:
            allowed = "grounded_base_maps" in path.parts
            if not allowed:
                continue
            exception = "grounded base map is an explicit MLE input under outputs"
        else:
            exception = ""
        manifest.add(
            path,
            "identification input",
            "MLE/re-identification",
            f"manifest reference: {key}",
            exception=exception,
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_python_dependency_closure(manifest: Manifest) -> None:
    """Fail if any listed Python source imports an unlisted local module."""
    listed = set(manifest.records)
    missing: dict[Path, list[Path]] = {}
    for path in sorted(listed):
        if path.suffix.lower() != ".py":
            continue
        absent = sorted(dependency for dependency in local_imports(path) if dependency not in listed)
        if absent:
            missing[path] = absent
    if missing:
        details = "; ".join(
            f"{Manifest.relative(importer)} -> "
            + ", ".join(Manifest.relative(dependency) for dependency in dependencies)
            for importer, dependencies in missing.items()
        )
        raise RuntimeError(f"local Python dependency closure is incomplete: {details}")


def build_manifest(package: Path, research_run: Path) -> Manifest:
    manifest = Manifest()

    for path in (
        ".gitignore",
        "Expand-MPC27.ps1",
        "Install-SolarSim.ps1",
        "SolarSim.ps1",
        "package.xml",
        "pytest.ini",
        "requirements-dev.txt",
        "requirements-weather.txt",
        "setup.cfg",
        "setup.py",
        "resource/mpc_solarcar",
    ):
        manifest.add(path, "entry/build", "install and dispatch", "entry point or package metadata")

    core_scripts = [
        "scripts/solar_control.sh",
        "scripts/bootstrap_ubuntu_humble.sh",
        "scripts/export_rqt_graph.py",
        "scripts/solar_sim.py",
        "scripts/build_historical_weather_counterfactual_grid.py",
        "scripts/fetch_weather_forecast.py",
        "scripts/dashboard_demo_server.py",
    ]
    add_python_closure(manifest, core_scripts, "runtime/offline source", "ROS and simulation", "executable source")
    manifest.add("scripts/solar_control.sh", "runtime/offline source", "ROS and simulation", "WSL dispatcher")
    manifest.add("scripts/bootstrap_ubuntu_humble.sh", "entry/build", "install and dispatch", "Ubuntu bootstrap")

    launch_files = [
        "launch/solarcar_sim.launch.py",
        "launch/solar_measurement.launch.py",
        "launch/solar_race_live.launch.py",
        "launch/solar_race_live_wifi.launch.py",
    ]
    add_python_closure(manifest, launch_files, "ROS launch", "sim/measure/live/live_wifi", "launch source")
    active_nodes = [
        "mpc_solarcar/dashboard_node.py",
        "mpc_solarcar/distance_node.py",
        "mpc_solarcar/gps_sim_node.py",
        "mpc_solarcar/grade_node.py",
        "mpc_solarcar/mpc_node.py",
        "mpc_solarcar/solar_autocal_node.py",
        "mpc_solarcar/solar_logger_node.py",
        "mpc_solarcar/solar_preflight_node.py",
        "mpc_solarcar/solar_state_node.py",
        "mpc_solarcar/speed_command_bridge_node.py",
        "mpc_solarcar/telemetry_text_bridge_node.py",
        "mpc_solarcar/weather_fetch_node.py",
        "mpc_solarcar/wind_correction_node.py",
    ]
    add_python_closure(manifest, active_nodes, "ROS runtime source", "sim/measure/live/live_wifi", "node or imported model")
    manifest.add("mpc_solarcar/__init__.py", "ROS runtime source", "sim/measure/live/live_wifi", "Python package marker")

    manifest.add_tree("dashboard", "dashboard", "live/dashboard", "static web application")
    manifest.add_tree(
        "grafana",
        "Grafana",
        "grafana monitoring",
        "provisioning/configuration",
        suffixes={".json", ".yaml", ".yml"},
    )

    simple_identification = [
        "scripts/run_identification_pipeline.py",
        "scripts/build_route_profile_from_gps.py",
        "scripts/build_ocv_curve.py",
        "scripts/build_rint_map_from_timeseries.py",
        "scripts/build_pv_maps_from_csv.py",
        "scripts/fit_vehicle_params.py",
    ]
    generic_identification = [
        "scripts/run_vehicle_identification.py",
        "scripts/audit_identification_residuals.py",
        "scripts/normalize_bwsc2025_field_evidence.py",
        "scripts/build_identification_evidence_bundle.py",
        "scripts/assess_terminal_soc_consistency.py",
        "scripts/promote_identification_run.py",
        "scripts/compare_identification_runs.py",
        "scripts/regenerate_identification_report.py",
        "scripts/check_model_validation_gate.py",
        "scripts/adopt_conditional_identification_candidate.py",
        "scripts/create_operational_fine_profile.py",
        "scripts/build_fastest_certified_profile.py",
    ]
    add_python_closure(manifest, simple_identification, "identification source", "basic identification", "executable source")
    add_python_closure(manifest, generic_identification, "identification source", "MLE/re-identification", "executable source")
    manifest.add("scripts/run_vehicle_identification_cpu.sbatch", "identification source", "MLE/re-identification", "Slurm pipeline")

    learning = ["scripts/tune_upper_planner_weights.py"]
    add_python_closure(manifest, learning, "learning source", "CPU self-learning", "executable source")

    gpu_files = [
        "scripts/setup_gpu_server_env.sh",
        "scripts/submit_solar_gpu_multifidelity_campaign.sh",
        "scripts/resubmit_solar_gpu_refinement_chain.sh",
        "scripts/run_solar_upper_gpu_search.sbatch",
        "scripts/run_solar_gpu_concurrent_campaign.sbatch",
        "scripts/finalize_solar_gpu_campaign.sbatch",
        "scripts/run_solar_gpu_acceptance_pipeline.sbatch",
        "scripts/run_solar_fullsim_cpu.sbatch",
        "scripts/run_solar_mesh_convergence_cpu.sbatch",
        "scripts/check_policy_weather_input.py",
        "scripts/gpu_upper_policy_search.py",
        "scripts/check_gpu_surrogate_feasibility.py",
        "scripts/rank_gpu_upper_policy_candidates.py",
        "scripts/validate_gpu_upper_policy_candidates.py",
        "scripts/merge_exact_candidate_rankings.py",
        "scripts/run_upper_mesh_convergence.py",
        "scripts/generate_gpu_acceptance_report.py",
    ]
    python_gpu = [path for path in gpu_files if path.endswith(".py")]
    add_python_closure(manifest, python_gpu, "GPU/CEM source", "multi-fidelity CEM and exact acceptance", "executable source")
    for path in gpu_files:
        if not path.endswith(".py"):
            manifest.add(path, "GPU/CEM source", "multi-fidelity CEM and exact acceptance", "shell/Slurm entry")

    packaging = [
        "scripts/create_solarcar_only_package.py",
        "scripts/create_solarcar_blank_package.py",
        "scripts/create_project_packages.py",
        "scripts/create_bwsc2027_operational_package.py",
        "scripts/clone_vehicle_identification_package.py",
        "scripts/generate_package_inventory.py",
        "scripts/audit_solar_package.py",
        "scripts/audit_execution_dependency_manifest.py",
        "scripts/generate_execution_dependency_manifest.py",
        "scripts/package_execution_dependencies.py",
    ]
    add_python_closure(manifest, packaging, "packaging/audit source", "package, blank, audit", "executable source")

    solar_tests = [
        path
        for path in (ROOT / "tests").glob("test_*.py")
        if "magnetic" not in path.name
    ]
    add_python_closure(manifest, solar_tests, "validation source", "regression tests", "test source")

    manifest.add_tree("templates", "input template", "blank package and identification", "operator input schema")
    add_profile_assets(
        manifest,
        ROOT / "config" / "solar" / "bwsc_2027_demo.yaml",
        "demo configuration",
        "demo ROS/simulation",
    )
    for profile in sorted(package.glob("profile*.yaml")):
        add_profile_assets(manifest, profile, "current operational input", "current BWSC2025 workflows")

    bwsc2027_package = ROOT / "project_packages" / "bwsc2027_operational"
    if bwsc2027_package.is_dir():
        manifest.add_tree(
            bwsc2027_package,
            "BWSC2027 gated package",
            "2027 pre-season and eventual race operation",
            "2027 package file with per-file rationale",
        )
        for profile in sorted(bwsc2027_package.glob("profile*.yaml")):
            add_profile_assets(
                manifest,
                profile,
                "BWSC2027 gated package",
                "2027 pre-season and eventual race operation",
            )

    ident_dir = package / "data" / "identification"
    for ident_manifest in sorted(ident_dir.glob("identification_manifest*.yaml")):
        add_manifest_assets(manifest, ident_manifest)
    for path in (
        ident_dir / "generation_lineage.yaml",
        ident_dir / "evidence" / "grounded_map_sources.yaml",
    ):
        manifest.add(path, "identification input", "MLE/re-identification", "provenance/model declaration")

    research_profile = research_run / "profile_operational_gpu_research.yaml"
    if research_profile.is_file():
        add_profile_assets(
            manifest,
            research_profile,
            "current research input",
            "active MLE35 GPU campaign",
            research_exception=True,
        )

    validate_python_dependency_closure(manifest)
    return manifest


def write_outputs(manifest: Manifest, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "execution_dependency_manifest.csv"
    md_path = output_dir / "execution_dependency_manifest.md"
    records = sorted(manifest.records.values(), key=lambda item: Manifest.relative(item.path).lower())

    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["path", "category", "workflow", "role", "outputs_exception", "size_bytes", "sha256"]
        )
        for record in records:
            writer.writerow(
                [
                    Manifest.relative(record.path),
                    "; ".join(sorted(record.categories)),
                    "; ".join(sorted(record.workflows)),
                    "; ".join(sorted(record.roles)),
                    record.exception,
                    record.path.stat().st_size,
                    sha256(record.path),
                ]
            )

    grouped: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        for category in record.categories:
            grouped[category].append(record)
    lines = [
        "# Current execution dependency manifest",
        "",
        "This is the complete source/input inventory for the supported solar-car workflows.",
        "Past runs, logs, simulation CSVs, checkpoints, TensorBoard data, reports, QA images,",
        "and build/install artifacts are excluded.",
        "",
        f"- Unique files: **{len(records)}**",
        f"- Missing required files: **{len(manifest.missing)}**",
        "- CSV contains file size and SHA-256 for reproducibility.",
        "- PASSO and magnetic-coupler files are outside this solar-car execution scope.",
        "",
        "## Important outputs exceptions",
        "",
        "Files in `outputs/identification/adopted_maps`, `grounded_base_maps`, and the selected",
        "MLE35 research profile are included only when they are consumed as current model inputs.",
        "Other files below `outputs` are not dependencies and are excluded.",
        "",
    ]
    for category in sorted(grouped):
        unique_by_path = {record.path: record for record in grouped[category]}
        unique = sorted(
            unique_by_path.values(),
            key=lambda item: Manifest.relative(item.path).lower(),
        )
        lines.extend([f"## {category} ({len(unique)})", ""])
        for record in unique:
            rel = Manifest.relative(record.path)
            workflows = ", ".join(sorted(record.workflows))
            suffix = f"; exception: {record.exception}" if record.exception else ""
            lines.append(f"- `{rel}` - {workflows}{suffix}")
        lines.append("")
    lines.extend(
        [
            "## Generated handoff contracts (not source dependencies)",
            "",
            "The GPU pipeline creates `checkpoint.pt`, `latest_policy.csv`, `summary.json`,",
            "completion markers, exact replay CSVs, and acceptance reports. They are outputs of",
            "the listed source/input set, so no existing historical copy is included above.",
            "",
        ]
    )
    if manifest.missing:
        lines.extend(["## Missing required paths", ""])
        for path, workflow in sorted(set(manifest.missing)):
            lines.append(f"- `{path}` - {workflow}")
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--research-run", type=Path, default=DEFAULT_RESEARCH_RUN)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "docs" / "execution_dependencies_complete",
    )
    args = parser.parse_args()
    package = args.package.resolve() if args.package.is_absolute() else (ROOT / args.package).resolve()
    research_run = (
        args.research_run.resolve()
        if args.research_run.is_absolute()
        else (ROOT / args.research_run).resolve()
    )
    output_dir = args.output_dir.resolve() if args.output_dir.is_absolute() else (ROOT / args.output_dir).resolve()
    manifest = build_manifest(package, research_run)
    csv_path, md_path = write_outputs(manifest, output_dir)
    print(f"files={len(manifest.records)} missing={len(manifest.missing)}")
    print(csv_path)
    print(md_path)
    return 1 if manifest.missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
