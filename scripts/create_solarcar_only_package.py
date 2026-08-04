from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "exports" / f"solarcar_only_package_{datetime.now().strftime('%Y%m%d')}"

TOP_LEVEL_FILES = [
    ".gitignore",
    "Install-SolarSim.ps1",
    "README.md",
    "SolarSim.ps1",
    "package.xml",
    "pytest.ini",
    "requirements-dev.txt",
    "requirements-weather.txt",
    "setup.cfg",
    "setup.py",
]

TOP_LEVEL_DIRS = [
    "config",
    "dashboard",
    "grafana",
    "inputs",
    "launch",
    "maps",
    "mpc_solarcar",
    "resource",
    "scripts",
    "templates",
    "tests",
]

DOC_DIRS = [
    "docs/solar_all_in_one_manual",
    "docs/flow_workbook",
    "docs/complete_flow_workbook",
    "docs/mle_hand_calculation_workbook",
    "docs/deployment_operation_manual",
    "docs/execution_dependencies",
    "docs/package_inventory",
    "docs/live_low_level_reference",
]

PROJECT_PACKAGES = [
    "bwsc2027_template",
    "other_template",
    "bwsc2025_public",
    "bwsc2025_fitted_mle19_energywindow_inertia",
    "bwsc2027_operational",
]

CURRENT_FITTED_PACKAGE = "bwsc2025_fitted_mle19_energywindow_inertia"

REMOVE_FILES = [
    "passo_run.sh",
    "launch/passo_autostart.launch.py",
    "launch/passo_live.launch.py",
    "mpc_solarcar/magnet_field_viewer.py",
    "mpc_solarcar/preflight_node.py",
    "mpc_solarcar/logger_node.py",
    "mpc_solarcar/can_obd_node.py",
    "mpc_solarcar/config_wizard_node.py",
    "mpc_solarcar/throttle_advisory_node.py",
    "mpc_solarcar/panel_node.py",
    "scripts/setup_can.sh",
    "scripts/can_smoke_test.sh",
    "scripts/obd_scan.py",
    "scripts/postprocess_fuel.py",
    "scripts/build_mle13_completion_report.py",
    "docs/solar_all_in_one_manual/solar_all_in_one_manual.aux",
    "docs/solar_all_in_one_manual/solar_all_in_one_manual.log",
    "docs/solar_all_in_one_manual/solar_all_in_one_manual.out",
    "docs/solar_all_in_one_manual/solar_all_in_one_manual.toc",
    "docs/solar_all_in_one_manual/dashboard_demo.png",
    "docs/solar_all_in_one_manual/dashboard_demo_1920.png",
]

REMOVE_DIRS = [
    "dashboard_magnetic_coupler",
    "inputs/external_docs",
    "docs/solar_all_in_one_manual/preview_pages",
    "docs/solar_all_in_one_manual/preview_pages_fitz",
    "docs/flow_workbook/preview_pages",
    "docs/flow_workbook/qa_all",
    "docs/complete_flow_workbook/preview",
]

REMOVE_PATTERNS = [
    re.compile(r"(^|[/\\])magnetic_"),
    re.compile(r"(^|[/\\])[^/\\]*magnetic[^/\\]*", re.IGNORECASE),
    re.compile(r"(^|[/\\])find_existing_magnetic_coupler_solution\.py$"),
    re.compile(r"(^|[/\\])generate_bachelor_thesis_magnetic_coupler\.py$"),
    re.compile(r"(^|[/\\])generate_freearray_"),
    re.compile(r"(^|[/\\])generate_magnetic_coupler_"),
    re.compile(r"(^|[/\\])export_.+(?:fourier|parametric)_coupler"),
    re.compile(r"(^|[/\\])reevaluate_fourier_gpu_candidates\.py$"),
    re.compile(r"(^|[/\\])render_current_best_parametric_coupler\.py$"),
    re.compile(r"(^|[/\\])rerank_parametric_coupler_physical_scenarios\.py$"),
    re.compile(r"(^|[/\\])run_global_magnetic_coupler_campaign\.py$"),
    re.compile(r"(^|[/\\])run_magnetic_coupler_"),
    re.compile(r"(^|[/\\])run_freearray_"),
    re.compile(r"(^|[/\\])run_linear_restore_"),
    re.compile(r"(^|[/\\])build_linear_restore_"),
    re.compile(r"(^|[/\\])run_structured_root_redesign_search\.py$"),
    re.compile(r"(^|[/\\])continue_freearray_"),
    re.compile(r"(^|[/\\])continue_linear_restore_"),
    re.compile(r"(^|[/\\])render_mujoco_"),
    re.compile(r"(^|[/\\])render_corridor_schematic_video\.py$"),
    re.compile(r"(^|[/\\])[^/\\]+\.(aux|log|out|toc)$"),
    re.compile(r"(^|[/\\])(?:build_date_pass\d+|[^/\\]+\.(?:build|pass)\d+|[^/\\]+\.tex\.build)\.txt$"),
    re.compile(r"^docs/.+updated_.+\.png$"),
    re.compile(r"(^|[/\\])qa_.+\.png$"),
]


def copy_path(src: Path, dst: Path, *, ignore=None) -> None:       # [関数定義] copy_path の処理実行ブロック
    if src.is_dir():
        shutil.copytree(
            src,
            dst,
            dirs_exist_ok=True,
            ignore=ignore,
            copy_function=shutil.copy,
        )
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        # copy2 propagates OneDrive cloud-placeholder attributes and can create
        # destination files that have a length but cannot be opened.
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        shutil.copy(src, dst)


def _newest_completed_directory(root: Path, marker_name: str) -> Path | None:  # [関数定義] _newest_completed_directory の処理実行ブロック
    if not root.is_dir():
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    completed = [
        path
        for path in root.iterdir()
        if path.is_dir() and (path / marker_name).is_file()
    ]
    if not completed:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return max(completed, key=lambda path: (path / marker_name).stat().st_mtime_ns)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def current_fitted_copy_ignore(package_root: Path):                # [関数定義] current_fitted_copy_ignore の処理実行ブロック
    """Avoid copying superseded multi-GB histories into the release staging tree."""
    package_root = package_root.resolve()
    outputs_root = package_root / "outputs"
    runs_root = outputs_root / "identification" / "runs"
    keep_run = _newest_completed_directory(runs_root, "IDENTIFICATION_PIPELINE_COMPLETE")
    self_learning_root = outputs_root / "self_learning_upper"
    keep_self_learning = _newest_completed_directory(
        self_learning_root,
        "self_learning_upper_planner_summary.json",
    )

    def _ignore(directory: str, names: list[str]) -> set[str]:     # [関数定義] _ignore の処理実行ブロック
        current = Path(directory).resolve()
        ignored: set[str] = set()
        if current == runs_root.resolve() and keep_run is not None:
            ignored.update(name for name in names if name != keep_run.name)
        if current == self_learning_root.resolve() and keep_self_learning is not None:
            ignored.update(name for name in names if name != keep_self_learning.name)
        if keep_self_learning is not None and current == keep_self_learning.resolve():
            if "candidates" in names:
                ignored.add("candidates")
        if current == outputs_root.resolve():
            for name in names:
                candidate = current / name
                if name == "gpu_checkpoint_validation" or name.startswith(("gpu_debug", "gpu_sync_")):
                    ignored.add(name)
                elif name.startswith("gpu_multifidelity_") and not (
                    (candidate / "CAMPAIGN_COMPLETE").is_file()
                    or (candidate / "PIPELINE_COMPLETE").is_file()
                ):
                    ignored.add(name)
        return ignored                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    return _ignore                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def copy_lightweight_fullsim_evidence(src: Path, dst: Path) -> list[str]:  # [関数定義] copy_lightweight_fullsim_evidence の処理実行ブロック
    """Retain exact-run evidence without copying multi-GB 1 Hz detail traces."""
    source_root = src / "outputs" / "gpu_checkpoint_validation"
    if not source_root.is_dir():
        return []                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    copied: list[str] = []
    for manifest in sorted(source_root.rglob("latest_simulation_run.json")):
        for source in sorted(path for path in manifest.parent.iterdir() if path.is_file()):
            if "detail" in source.name.lower() or source.stat().st_size > 50 * 1024 * 1024:
                continue
            destination = dst / source.relative_to(src)
            copy_path(source, destination)
            copied.append(
                f"project_packages/{CURRENT_FITTED_PACKAGE}/"
                f"{source.relative_to(src).as_posix()}"
            )
    return copied                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def copy_current_fitted_package(src: Path, dst: Path) -> list[str]:  # [関数定義] copy_current_fitted_package の処理実行ブロック
    shutil.copytree(
        src,
        dst,
        dirs_exist_ok=True,
        ignore=current_fitted_copy_ignore(src),
        copy_function=shutil.copy,
    )
    return copy_lightweight_fullsim_evidence(src, dst)             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def safe_rmtree(path: Path, *, allowed_root: Path, allow_root: bool = False) -> None:  # [関数定義] safe_rmtree の処理実行ブロック
    target = path.resolve()
    root = allowed_root.resolve()
    if target == root:
        if not allow_root:
            raise ValueError(f"refusing to remove protected root: {target}")
    elif root not in target.parents:
        raise ValueError(f"refusing to remove path outside export root: {target}")

    def _onerror(func, target, exc_info):                          # [関数定義] _onerror の処理実行ブロック
        os.chmod(target, 0o666)
        func(target)

    shutil.rmtree(target, onerror=_onerror)


def prepare_output_dir(output_dir: Path, *, source_root: Path, force: bool) -> None:  # [関数定義] prepare_output_dir の処理実行ブロック
    if output_dir.exists():
        if not force:
            raise FileExistsError(f"{output_dir} already exists. Use --force to replace it.")
        resolved_output = output_dir.resolve()
        resolved_source = source_root.resolve()
        if resolved_output == Path(resolved_output.anchor) or resolved_output == resolved_source:
            raise ValueError(f"refusing unsafe export replacement target: {resolved_output}")
        if resolved_output in resolved_source.parents:
            raise ValueError(f"refusing to replace an ancestor of the source repository: {resolved_output}")
        safe_rmtree(output_dir, allowed_root=output_dir, allow_root=True)
    output_dir.mkdir(parents=True, exist_ok=True)


def rel(path: Path, root: Path) -> str:                            # [関数定義] rel の処理実行ブロック
    return path.relative_to(root).as_posix()                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def should_remove(path: Path, root: Path) -> bool:                 # [関数定義] should_remove の処理実行ブロック
    relpath = rel(path, root)
    if relpath in {p.replace("\\", "/") for p in REMOVE_FILES}:
        return True                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return any(pattern.search(relpath) for pattern in REMOVE_PATTERNS)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def prune_paths(dst_root: Path) -> list[str]:                      # [関数定義] prune_paths の処理実行ブロック
    removed: list[str] = []

    cache_dirs = [
        path
        for path in dst_root.rglob("*")
        if path.is_dir() and path.name in {"__pycache__", ".pytest_cache"}
    ]
    for path in sorted(cache_dirs, key=lambda item: len(item.parts), reverse=True):
        safe_rmtree(path, allowed_root=dst_root)
        removed.append(rel(path, dst_root))

    for raw in REMOVE_DIRS:
        target = dst_root / raw
        if target.exists():
            safe_rmtree(target, allowed_root=dst_root)
            removed.append(raw.replace("\\", "/"))

    for raw in REMOVE_FILES:
        target = dst_root / raw
        if target.exists():
            target.unlink()
            removed.append(raw.replace("\\", "/"))

    candidates = sorted(
        [path for path in dst_root.rglob("*") if path.is_file()],
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for path in candidates:
        if should_remove(path, dst_root):
            path.unlink()
            removed.append(rel(path, dst_root))

    for path in sorted([p for p in dst_root.rglob("*") if p.is_dir()], key=lambda item: len(item.parts), reverse=True):
        try:
            next(path.iterdir())
        except StopIteration:
            safe_rmtree(path, allowed_root=dst_root)

    return sorted(set(removed))                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def prune_current_fitted_history(dst_root: Path) -> list[str]:     # [関数定義] prune_current_fitted_history の処理実行ブロック
    """Keep the newest completed immutable fit while preserving canonical assets."""
    package = dst_root / "project_packages" / CURRENT_FITTED_PACKAGE
    runs_root = package / "outputs" / "identification" / "runs"
    if not runs_root.is_dir():
        return []                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    completed = [
        path
        for path in runs_root.iterdir()
        if path.is_dir() and (path / "IDENTIFICATION_PIPELINE_COMPLETE").is_file()
    ]
    if not completed:
        return []                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    keep = max(
        completed,
        key=lambda path: (path / "IDENTIFICATION_PIPELINE_COMPLETE").stat().st_mtime_ns,
    )
    removed: list[str] = []
    for path in sorted(runs_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or path == keep:
            continue
        safe_rmtree(path, allowed_root=dst_root)
        removed.append(rel(path, dst_root))

    reports_root = package / "outputs" / "reports"
    if reports_root.is_dir():
        for path in sorted(reports_root.glob("identification_comparison_*")):
            if path.is_dir() and not path.name.endswith(keep.name):
                safe_rmtree(path, allowed_root=dst_root)
                removed.append(rel(path, dst_root))
        for path in sorted(reports_root.glob("residual_audit_mle*")):
            if path.is_dir():
                safe_rmtree(path, allowed_root=dst_root)
                removed.append(rel(path, dst_root))
    return removed                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def prune_self_learning_history(dst_root: Path) -> list[str]:      # [関数定義] prune_self_learning_history の処理実行ブロック
    root = dst_root / "project_packages" / CURRENT_FITTED_PACKAGE / "outputs" / "self_learning_upper"
    if not root.exists():
        return []                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    removed: list[str] = []
    completed = sorted(
        path
        for path in root.iterdir()
        if path.is_dir() and (path / "self_learning_upper_planner_summary.json").is_file()
    )
    keep = completed[-1] if completed else None
    for path in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda item: item.name):
        if keep is not None and path == keep:
            candidates = path / "candidates"
            if candidates.exists():
                safe_rmtree(candidates, allowed_root=dst_root)
                removed.append(rel(candidates, dst_root))
            continue
        safe_rmtree(path, allowed_root=dst_root)
        removed.append(rel(path, dst_root))
    return removed                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _resolve_source_document(dst_root: Path, raw: str) -> Path | None:  # [関数定義] _resolve_source_document の処理実行ブロック
    candidate = Path(raw)
    candidates = [candidate] if candidate.is_absolute() else [dst_root / candidate, ROOT / candidate]
    for path in candidates:
        if path.is_file():
            return path.resolve()                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return None                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _bundle_yaml_source_fields(                                    # [関数定義] _bundle_yaml_source_fields の処理実行ブロック
    payload: object,
    *,
    dst_root: Path,
    package_root: Path,
    bundle_dir: Path,
    key_path: tuple[str, ...] = (),
) -> list[str]:
    bundled: list[str] = []
    if isinstance(payload, dict):
        for key, value in list(payload.items()):
            path = key_path + (str(key),)
            if str(key).startswith("source_") and isinstance(value, str):
                source = _resolve_source_document(dst_root, value)
                if source is None:
                    continue
                prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", "_".join(path))
                destination = bundle_dir / f"{prefix}__{source.name}"
                if source == destination.resolve():
                    continue
                copy_path(source, destination)
                payload[key] = destination.relative_to(package_root).as_posix()
                bundled.append(destination.relative_to(dst_root).as_posix())
            else:
                bundled.extend(
                    _bundle_yaml_source_fields(
                        value,
                        dst_root=dst_root,
                        package_root=package_root,
                        bundle_dir=bundle_dir,
                        key_path=path,
                    )
                )
    elif isinstance(payload, list):
        for index, value in enumerate(list(payload)):
            if key_path and key_path[-1] == "source_documents" and isinstance(value, str):
                source = _resolve_source_document(dst_root, value)
                if source is None:
                    continue
                destination = bundle_dir / f"terminal_source_{index:02d}__{source.name}"
                if source == destination.resolve():
                    continue
                copy_path(source, destination)
                payload[index] = destination.relative_to(package_root).as_posix()
                bundled.append(destination.relative_to(dst_root).as_posix())
            else:
                bundled.extend(
                    _bundle_yaml_source_fields(
                        value,
                        dst_root=dst_root,
                        package_root=package_root,
                        bundle_dir=bundle_dir,
                        key_path=key_path + (str(index),),
                    )
                )
    return bundled                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def bundle_current_fitted_evidence(dst_root: Path) -> list[str]:   # [関数定義] bundle_current_fitted_evidence の処理実行ブロック
    package_root = dst_root / "project_packages" / CURRENT_FITTED_PACKAGE
    bundle_dir = package_root / "data" / "identification" / "evidence" / "source_documents"
    bundled: list[str] = []
    source_yamls = sorted(package_root.rglob("grounded_map_sources.yaml"))
    terminal_yaml = package_root / "data" / "identification" / "evidence" / "terminal_anchor.yaml"
    if terminal_yaml.exists():
        source_yamls.append(terminal_yaml)

    for yaml_path in source_yamls:
        payload = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
        bundled.extend(
            _bundle_yaml_source_fields(
                payload,
                dst_root=dst_root,
                package_root=package_root,
                bundle_dir=bundle_dir,
            )
        )
        yaml_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
            newline="\n",
        )
    return sorted(set(bundled))                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _declared_source_values(payload: object, key_path: tuple[str, ...] = ()):  # [関数定義] _declared_source_values の処理実行ブロック
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = key_path + (str(key),)
            if str(key).startswith("source_") and isinstance(value, str):
                yield ".".join(path), value
            else:
                yield from _declared_source_values(value, path)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            path = key_path + (str(index),)
            if key_path and key_path[-1] == "source_documents" and isinstance(value, str):
                yield ".".join(path), value
            else:
                yield from _declared_source_values(value, path)


def validate_current_fitted_release(                               # [関数定義] validate_current_fitted_release の処理実行ブロック
    dst_root: Path,
    *,
    require_operational_acceptance: bool,
) -> dict:
    pkg_root = dst_root / "project_packages" / CURRENT_FITTED_PACKAGE
    if not (pkg_root / "profile.yaml").is_file():
        raise RuntimeError(f"Selected fitted package has no profile.yaml: {CURRENT_FITTED_PACKAGE}")
    profiles = sorted(pkg_root.glob("profile*.yaml"))
    missing_references = []
    for profile_path in profiles:
        profile_name = profile_path.name
        profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
        referenced = profile.get("paths", {}) or {}
        for key, raw in sorted(referenced.items()):
            if not isinstance(raw, str) or not raw.strip():
                continue
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = pkg_root / candidate
            if not candidate.is_file():
                missing_references.append(f"{profile_name}:paths.{key}={raw}")
        for key in ("fit_summary_yaml", "terminal_consistency_yaml"):
            raw = (profile.get("identification", {}) or {}).get(key, "")
            if not isinstance(raw, str) or not raw.strip():
                continue
            candidate = Path(raw)
            if not candidate.is_absolute():
                candidate = pkg_root / candidate
            if not candidate.is_file():
                missing_references.append(f"{profile_name}:identification.{key}={raw}")
    if missing_references:
        joined = "\n  - ".join(missing_references)
        raise RuntimeError(f"Selected fitted package contains unresolved paths:\n  - {joined}")

    full_course_profiles = [
        path
        for path in profiles
        if float((yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("mpc", {}).get("race_km", 0.0))
        >= 3000.0
    ]
    if not full_course_profiles:
        raise RuntimeError("Selected fitted package has no profile covering the complete BWSC course")

    reports = list((pkg_root / "outputs" / "reports").glob("*.pdf"))
    manifests = list((pkg_root / "outputs").rglob("latest_simulation_run.json"))
    if not reports or not manifests:
        raise RuntimeError(
            "Selected fitted package is not evidence-complete: a PDF report and a "
            "full-simulation manifest are required"
        )
    acceptance_files = sorted((pkg_root / "outputs" / "reports").glob("*model_acceptance.yaml"))
    accepted = False
    acceptance_results = []
    for acceptance_path in acceptance_files:
        acceptance = yaml.safe_load(acceptance_path.read_text(encoding="utf-8-sig")) or {}
        fullsim_pass = bool(acceptance.get("fullsim_adoption_gate_pass"))
        precision_pass = bool(acceptance.get("high_precision_claim_allowed"))
        accepted = accepted or (fullsim_pass and precision_pass)
        acceptance_results.append(
            {
                "path": acceptance_path.relative_to(dst_root).as_posix(),
                "fullsim_adoption_gate_pass": fullsim_pass,
                "high_precision_claim_allowed": precision_pass,
            }
        )
    if require_operational_acceptance and not accepted:
        raise RuntimeError(
            "Selected fitted package is not live-adoptable: acceptance YAML must set both "
            "fullsim_adoption_gate_pass=true and high_precision_claim_allowed=true"
        )

    unresolved_evidence = []
    evidence_yamls = sorted(pkg_root.rglob("grounded_map_sources.yaml"))
    terminal_yaml = pkg_root / "data" / "identification" / "evidence" / "terminal_anchor.yaml"
    if terminal_yaml.exists():
        evidence_yamls.append(terminal_yaml)
    for evidence_yaml in evidence_yamls:
        payload = yaml.safe_load(evidence_yaml.read_text(encoding="utf-8")) or {}
        for key, raw in _declared_source_values(payload):
            path = Path(raw)
            if path.is_absolute() or not (pkg_root / path).is_file():
                unresolved_evidence.append(
                    f"{evidence_yaml.relative_to(pkg_root).as_posix()}:{key}={raw}"
                )
    if unresolved_evidence:
        joined = "\n  - ".join(unresolved_evidence)
        raise RuntimeError(f"Selected fitted evidence is not self-contained:\n  - {joined}")

    runs_root = pkg_root / "outputs" / "identification" / "runs"
    selected_run = _newest_completed_directory(runs_root, "IDENTIFICATION_PIPELINE_COMPLETE")
    operational_profile = (
        dst_root / "project_packages" / "bwsc2027_operational" / "profile.yaml"
    )
    operational_readiness = "NOT_INCLUDED"
    if operational_profile.is_file():
        operational_payload = (
            yaml.safe_load(operational_profile.read_text(encoding="utf-8")) or {}
        )
        operational_readiness = str(
            (operational_payload.get("meta", {}) or {}).get(
                "operational_readiness",
                "UNDECLARED",
            )
        )
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "fitted_package": CURRENT_FITTED_PACKAGE,
        "selected_identification_run": selected_run.name if selected_run else "",
        "operational_acceptance_required": bool(require_operational_acceptance),
        "operational_acceptance_pass": bool(accepted),
        "operational_release_status": (
            "OPERATIONAL_ACCEPTED" if accepted else "BLOCKED_MODEL_GATE"
        ),
        "bwsc2027_operational_readiness": operational_readiness,
        "acceptance_results": acceptance_results,
        "full_simulation_manifests": [
            path.relative_to(dst_root).as_posix() for path in sorted(manifests)
        ],
    }


def repair_unreadable_files(dst_root: Path) -> list[str]:          # [関数定義] repair_unreadable_files の処理実行ブロック
    """Repair OneDrive placeholders accidentally propagated by older exports."""
    repaired: list[str] = []
    failures: list[str] = []
    evidence_search_roots = (
        ROOT / "inputs" / "external_docs",
        ROOT / "docs",
    )
    for target in sorted(path for path in dst_root.rglob("*") if path.is_file()):
        try:
            with target.open("rb") as stream:
                stream.read(1)
            continue
        except OSError:
            pass
        relative = target.relative_to(dst_root)
        source = ROOT / relative
        if not source.is_file() and "__" in target.name:
            original_name = target.name.split("__", 1)[1]
            source = next(
                (
                    match
                    for search_root in evidence_search_roots
                    if search_root.is_dir()
                    for match in search_root.rglob(original_name)
                ),
                source,
            )
        if not source.is_file():
            failures.append(relative.as_posix())
            continue
        try:
            copy_path(source, target)
            with target.open("rb") as stream:
                stream.read(1)
            repaired.append(relative.as_posix())
        except OSError:
            failures.append(relative.as_posix())
    if failures:
        joined = "\n  - ".join(failures)
        raise RuntimeError(f"Export contains unreadable files that could not be repaired:\n  - {joined}")
    return repaired                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def patch_setup_py(dst_root: Path) -> None:                        # [関数定義] patch_setup_py の処理実行ブロック
    path = dst_root / "setup.py"
    text = path.read_text(encoding="utf-8")
    filtered_lines = []
    blocked = (
        "magnetic_coupler",
        "magnet_field_viewer",
        '"python-can"',
        '"can_obd_node =',
        '"preflight_node =',
        '"logger_node =',
        '"config_wizard_node =',
        '"throttle_advisory_node =',
        '"panel_node =',
    )
    for line in text.splitlines():
        if any(token in line for token in blocked):
            continue
        filtered_lines.append(line)
    path.write_text("\n".join(filtered_lines) + "\n", encoding="utf-8")

    package_xml = dst_root / "package.xml"
    xml_text = package_xml.read_text(encoding="utf-8")
    xml_text = xml_text.replace("  <exec_depend>python3-can</exec_depend>\n", "")
    package_xml.write_text(xml_text, encoding="utf-8")


def patch_mpc_node(dst_root: Path) -> None:                        # [関数定義] patch_mpc_node の処理実行ブロック
    path = dst_root / "mpc_solarcar" / "mpc_node.py"
    text = path.read_text(encoding="utf-8")

    text = text.replace(
        """    \"\"\"\n    MPC node with two modes:\n      - Default: solarcar MPC (forecast-driven)\n      - Passo mode: fuel-minimizing advisory MPC\n    \"\"\"\n""",
        '    """Forecast-driven solarcar MPC node."""\n',
        1,
    )
    mode_dispatch = """        self.declare_parameter('passo_mode', False)\n        self.passo_mode = bool(self.get_parameter('passo_mode').value)\n        if self.passo_mode:\n            self._init_passo()\n        else:\n            self._init_solar()\n"""
    if mode_dispatch in text:
        text = text.replace(mode_dispatch, "        self._init_solar()\n", 1)
    elif "        self._init_solar()\n" not in text:
        raise RuntimeError(
            "Neither the original nor the solar-only MPC initialization block was found"
        )

    marker = "    # -------------------- passo mode --------------------\n"
    main_marker = "\ndef main():\n"                                # [メイン関数] エントリーポイント関数
    if marker in text and main_marker in text:
        start = text.index(marker)
        end = text.index(main_marker)
        text = text[:start].rstrip() + "\n\n" + text[end + 1 :]

    path.write_text(text, encoding="utf-8")


def patch_release_builder(dst_root: Path) -> None:                 # [関数定義] patch_release_builder の処理実行ブロック
    """Make the copied release builder describe the fitted package it contains."""
    path = dst_root / "scripts" / "create_solarcar_only_package.py"
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(
        r'^CURRENT_FITTED_PACKAGE = "[^"]+"$',
        f'CURRENT_FITTED_PACKAGE = "{CURRENT_FITTED_PACKAGE}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"PROJECT_PACKAGES = \[\n.*?\n\]\n",
        "PROJECT_PACKAGES = [\n"
        '    "bwsc2027_template",\n'
        '    "other_template",\n'
        '    "bwsc2025_public",\n'
        f'    "{CURRENT_FITTED_PACKAGE}",\n'
        '    "bwsc2027_operational",\n'
        "]\n",
        text,
        count=1,
        flags=re.DOTALL,
    )
    path.write_text(text, encoding="utf-8")


def write_readme(dst_root: Path, removed: list[str], release_status: dict) -> None:  # [関数定義] write_readme の処理実行ブロック
    pkg_root = dst_root / "project_packages" / CURRENT_FITTED_PACKAGE
    profile_names = [path.name for path in sorted(pkg_root.glob("profile*.yaml"))]
    report_paths = [path.relative_to(dst_root).as_posix() for path in sorted((pkg_root / "outputs" / "reports").glob("*.pdf"))]
    release_label = str(release_status.get("operational_release_status", "UNKNOWN"))
    selected_run = str(release_status.get("selected_identification_run", ""))
    lines = [
        "# ソーラーカー専用パッケージ",
        "",
        "元ワークスペースからソーラーカーEMSに必要なものだけを抽出した、独立コピーです。PASSO、燃料計、磁気カプラ、ビルド生成物、仮想環境、旧同定履歴、未完了GPU探索、巨大な一時出力は含みません。",
        "",
        "## 本番投入可否",
        f"- 現在の判定: **{release_label}**",
        f"- 選択同定run: `{selected_run or 'なし'}`",
        "- `BLOCKED_MODEL_GATE`の場合、このコピーは同定、SILS、CEM、厳密再現、live通信試験まで使用できますが、実車への速度指令採用は禁止です。",
        "- 本番投入には、独立holdout、終端SoC、full simulation、mesh convergence、GPU候補のCPU一致検証をすべて再実行し、acceptance YAMLの両ゲートをtrueにする必要があります。",
        "",
        "## 最初に読むもの",
        "- 全モード・構造・数式: `docs/solar_all_in_one_manual/solar_all_in_one_manual.pdf`",
        "- live/live_wifi低層実装・全計算・全ソース: `docs/live_low_level_reference/solarcar_live_low_level_reference.pdf`",
        "- Windows/Ubuntu導入と運用手順: `docs/deployment_operation_manual/solar_mpc_deployment_operation_manual.pdf`",
        "- MPC手計算問題・解答用紙・解答: `docs/complete_flow_workbook/`",
        "- MLE手計算問題・解答用紙・解答: `docs/mle_hand_calculation_workbook/`",
        "- 全ファイル一覧と役割: `docs/package_inventory/package_source_inventory.md`",
        "",
        "## 同梱プロジェクト",
        "- 新規車両用の空雛形: `project_packages/other_template/`",
        "- BWSC2027用の空雛形: `project_packages/bwsc2027_template/`",
        "- BWSC2025公開ログ再現・チュートリアル: `project_packages/bwsc2025_public/`",
        f"- 同定済み世代: `project_packages/{CURRENT_FITTED_PACKAGE}`",
        f"- 標準入口: `project_packages/{CURRENT_FITTED_PACKAGE}/profile.yaml`",
        *(f"- プロファイル: `project_packages/{CURRENT_FITTED_PACKAGE}/{name}`" for name in profile_names if name != "profile.yaml"),
        *(f"- 報告書: `{path}`" for path in report_paths),
        "- BWSC2027運用骨格: `project_packages/bwsc2027_operational/`（予報、route note、実車同定値が未確定のため現在はBLOCKED）",
        "- 注意: 2831 kmの終端SoCは複数の観測チャネルを統合した推定値です。同期済みBMS coulomb countがない限り狭い誤差幅を断定せず、報告書の95%区間を運用上の不確かさとして扱ってください。",
        "",
        "## 基本コマンド",
        "- 同定: `python scripts/run_vehicle_identification.py --profile project_packages/<vehicle>/profile.yaml`",
        "- 事前シミュレーション: `powershell -ExecutionPolicy Bypass -File .\\SolarSim.ps1 -Action simulate -Profile project_packages/<vehicle>/profile.yaml`",
        "- SILS/live通信試験: `powershell -ExecutionPolicy Bypass -File .\\SolarSim.ps1 -Mode live_wifi -Action up -Profile project_packages/<vehicle>/profile.yaml`",
        "- 監査: `python scripts/audit_solar_package.py`",
        "- テスト: `python -m pytest -q`",
        "",
        "## 同梱範囲",
        "- 上位/下位MPC、offline simulation、GPU CEM、厳密候補検証、live/live_wifi、logger、dashboard、天候生成、同定パイプライン、空テンプレート、BWSC2025再現資産、取扱資料を含みます。",
        "- GPU探索のソースと再開機構は含みますが、未完了キャンペーンの巨大checkpointは含みません。",
        "- Python仮想環境、ROS 2の`build/install/log`は環境依存なので同梱せず、導入コマンドで再生成します。",
        "",
        "## 元ワークスペースから除外したもの",
        "- PASSO、燃料計、磁気カプラ、旧世代の同定パッケージ、build/install/log、一時成果物、巨大な原資料アーカイブを除外しています。",
        "",
        "## 除外パス一覧",
    ]
    lines.extend(f"- `{item}`" for item in removed)
    payload = "\n".join(lines) + "\n"
    (dst_root / "README.md").write_text(payload, encoding="utf-8")
    (dst_root / "README_SOLAR_ONLY.md").write_text(payload, encoding="utf-8")


def write_manifest(                                                # [関数定義] write_manifest の処理実行ブロック
    dst_root: Path,
    removed: list[str],
    copied: list[str],
    release_status: dict,
) -> None:
    files = [path for path in dst_root.rglob("*") if path.is_file()]
    payload = {
        "generated_at": datetime.now().isoformat(),
        "source_root": "repository-export-source",
        "output_root": ".",
        "copied_items": sorted(set(copied)),
        "removed_items": sorted(set(removed)),
        "project_packages": PROJECT_PACKAGES,
        "release_status": release_status,
        "inventory": {
            "file_count": len(files),
            "total_size_bytes": int(sum(path.stat().st_size for path in files)),
        },
    }
    (dst_root / "solarcar_only_manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def refresh_quality_artifacts(dst_root: Path) -> None:             # [関数定義] refresh_quality_artifacts の処理実行ブロック
    commands = (
        [sys.executable, "scripts/generate_package_inventory.py"],
        [sys.executable, "scripts/audit_solar_package.py"],
    )
    for command in commands:
        subprocess.run(command, cwd=dst_root, check=True)


def finalize_clean_copy(                                           # [関数定義] finalize_clean_copy の処理実行ブロック
    output_dir: Path,
    *,
    copied: list[str],
    removed: list[str],
    require_operational_acceptance: bool,
) -> Path:
    copied.extend(bundle_current_fitted_evidence(output_dir))
    repaired = repair_unreadable_files(output_dir)
    copied.extend(f"repaired:{path}" for path in repaired)
    release_status = validate_current_fitted_release(
        output_dir,
        require_operational_acceptance=require_operational_acceptance,
    )
    patch_setup_py(output_dir)
    patch_mpc_node(output_dir)
    patch_release_builder(output_dir)
    write_readme(output_dir, removed, release_status)
    write_manifest(output_dir, removed, copied, release_status)
    refresh_quality_artifacts(output_dir)
    write_manifest(output_dir, removed, copied, release_status)
    return output_dir                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_clean_copy(                                              # [関数定義] build_clean_copy の処理実行ブロック
    output_dir: Path,
    force: bool,
    *,
    require_operational_acceptance: bool = False,
) -> Path:
    prepare_output_dir(output_dir, source_root=ROOT, force=force)

    copied: list[str] = []
    for raw in TOP_LEVEL_FILES:
        src = ROOT / raw
        if src.exists():
            copy_path(src, output_dir / raw)
            copied.append(raw)
    for raw in TOP_LEVEL_DIRS:
        src = ROOT / raw
        if src.exists():
            ignore = shutil.ignore_patterns("external_docs") if raw == "inputs" else None
            copy_path(src, output_dir / raw, ignore=ignore)
            copied.append(raw)
    for raw in DOC_DIRS:
        src = ROOT / raw
        if src.exists():
            copy_path(src, output_dir / raw)
            copied.append(raw)

    project_root = output_dir / "project_packages"
    project_root.mkdir(parents=True, exist_ok=True)
    for name in PROJECT_PACKAGES:
        src = ROOT / "project_packages" / name
        if src.exists():
            if name == CURRENT_FITTED_PACKAGE:
                copied.extend(copy_current_fitted_package(src, project_root / name))
            else:
                copy_path(src, project_root / name)
            copied.append(f"project_packages/{name}")

    removed = prune_paths(output_dir)
    removed.extend(prune_current_fitted_history(output_dir))
    removed.extend(prune_self_learning_history(output_dir))
    return finalize_clean_copy(                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
        output_dir,
        copied=copied,
        removed=removed,
        require_operational_acceptance=require_operational_acceptance,
    )


def finalize_existing_copy(                                        # [関数定義] finalize_existing_copy の処理実行ブロック
    output_dir: Path,
    *,
    require_operational_acceptance: bool = False,
) -> Path:
    """Resume final validation after an interrupted or previously failed export."""
    if not output_dir.is_dir():
        raise FileNotFoundError(f"Existing export directory not found: {output_dir}")
    creator = ROOT / "scripts" / "create_solarcar_only_package.py"
    copy_path(creator, output_dir / "scripts" / creator.name)
    src_package = ROOT / "project_packages" / CURRENT_FITTED_PACKAGE
    dst_package = output_dir / "project_packages" / CURRENT_FITTED_PACKAGE
    copied = [
        raw
        for raw in (*TOP_LEVEL_FILES, *TOP_LEVEL_DIRS, *DOC_DIRS)
        if (output_dir / raw).exists()
    ]
    copied.extend(
        f"project_packages/{name}"
        for name in PROJECT_PACKAGES
        if (output_dir / "project_packages" / name).exists()
    )
    copied.extend(copy_lightweight_fullsim_evidence(src_package, dst_package))
    removed = prune_paths(output_dir)
    removed.extend(prune_current_fitted_history(output_dir))
    removed.extend(prune_self_learning_history(output_dir))
    return finalize_clean_copy(                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
        output_dir,
        copied=copied,
        removed=removed,
        require_operational_acceptance=require_operational_acceptance,
    )


def parse_args() -> argparse.Namespace:                            # [関数定義] parse_args の処理実行ブロック
    parser = argparse.ArgumentParser(description="Create a solar-car-only distribution copy.")
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument(                                           # [CLI引数] コマンドライン実行引数の定義
        "--fitted-package",
        default=CURRENT_FITTED_PACKAGE,
        help="Project-package directory to include as the current fitted vehicle.",
    )
    parser.add_argument(                                           # [CLI引数] コマンドライン実行引数の定義
        "--require-operational-acceptance",
        action="store_true",
        help="Fail unless the selected fitted package passes both operational acceptance gates.",
    )
    parser.add_argument(                                           # [CLI引数] コマンドライン実行引数の定義
        "--finalize-existing",
        action="store_true",
        help="Resume pruning, evidence checks, patching, and audits in an existing output directory.",
    )
    parser.add_argument("--force", action="store_true", help="Replace the output directory if it already exists.")  # [CLI引数] コマンドライン実行引数の定義
    return parser.parse_args()                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def main() -> None:                                                # [関数定義] main の処理実行ブロック
    global CURRENT_FITTED_PACKAGE, PROJECT_PACKAGES
    args = parse_args()
    CURRENT_FITTED_PACKAGE = str(args.fitted_package)
    PROJECT_PACKAGES = [
        "bwsc2027_template",
        "other_template",
        "bwsc2025_public",
        CURRENT_FITTED_PACKAGE,
        "bwsc2027_operational",
    ]
    if args.finalize_existing:
        output_dir = finalize_existing_copy(
            args.output_dir.resolve(),
            require_operational_acceptance=bool(args.require_operational_acceptance),
        )
    else:
        output_dir = build_clean_copy(
            args.output_dir.resolve(),
            force=args.force,
            require_operational_acceptance=bool(args.require_operational_acceptance),
        )
    print(output_dir)


if __name__ == "__main__":
    main()