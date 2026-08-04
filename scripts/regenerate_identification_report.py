#!/usr/bin/env python3
"""Regenerate an identification report from versioned fit artifacts only."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import fields
from pathlib import Path
from typing import Any, TypeVar

import yaml

ROOT = Path(__file__).resolve().parents[1]
if os.fspath(ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT))

from scripts.build_bwsc2025_fitted_package import (  # noqa: E402
    BatteryFitResult,
    MotionFitResult,
    PostRefineResult,
    PvFitResult,
)
from scripts.run_vehicle_identification import write_generic_report  # noqa: E402


T = TypeVar("T")


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}


def dataclass_from_mapping(cls: type[T], payload: dict[str, Any]) -> T:
    allowed = {field.name for field in fields(cls)}
    return cls(**{key: value for key, value in payload.items() if key in allowed})


def locate_package(path: Path) -> Path:
    for candidate in (path.parent, *path.parents):
        if candidate.parent.name == "project_packages" and (candidate / "data").is_dir():
            return candidate
    raise ValueError(f"fit summary is not inside a project package: {path}")


def resolve_package_path(package: Path, raw: object) -> Path:
    path = Path(str(raw or "").strip())
    if path.is_absolute():
        return path
    return (package / path).resolve()


def default_post_refine(metrics: dict[str, Any]) -> PostRefineResult:
    return PostRefineResult(
        panel_gain_factor=1.0,
        cda_factor=1.0,
        crr_factor=1.0,
        drive_eff_factor=1.0,
        headwind_gain_factor=1.0,
        e_nom_factor=1.0,
        rint_factor=1.0,
        objective=float("nan"),
        accepted=False,
        power_rmse_clean_w=float(metrics.get("power_rmse_clean_w", float("nan"))),
        voltage_rmse_clean_v=float(metrics.get("voltage_rmse_clean_v", float("nan"))),
        retire_anchor_soc_error=float(metrics.get("retire_anchor_soc_error", float("nan"))),
        retire_anchor_voltage_error_v=(
            float(metrics.get("retire_anchor_voltage_pred_v", float("nan")))
            - float(metrics.get("retire_anchor_voltage_obs_v", float("nan")))
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit-summary", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()

    summary_path = args.fit_summary.resolve()
    summary = load_yaml(summary_path)
    package = locate_package(summary_path)
    profile = (
        args.profile.resolve()
        if args.profile
        else resolve_package_path(package, summary.get("profile_yaml"))
    )
    manifest = (
        args.manifest.resolve()
        if args.manifest
        else resolve_package_path(package, summary.get("manifest_yaml"))
    )
    profile_cfg = load_yaml(profile)
    observed_log = resolve_package_path(
        package,
        (profile_cfg.get("paths", {}) or {}).get("progress_reference_csv", ""),
    )
    map_assets = {
        key: resolve_package_path(package, raw)
        for key, raw in (summary.get("active_maps", {}) or {}).items()
    }
    evidence = summary.get("evidence_bundle", {}) or {}
    grounded_summary_path = resolve_package_path(
        package, evidence.get("grounded_map_summary_yaml", "")
    )
    grounded_summary = load_yaml(grounded_summary_path) if grounded_summary_path.is_file() else {}
    grounded_summary["summary_yaml"] = os.fspath(grounded_summary_path)
    terminal_path = summary_path.parent / "terminal_soc_consistency.yaml"
    terminal_consistency = load_yaml(terminal_path) if terminal_path.is_file() else {}
    report_dir = args.report_dir.resolve() if args.report_dir else summary_path.parent / "reports"
    current_maps = report_dir / "current_maps_and_coefficients.md"
    metrics = summary.get("validation_metrics", {}) or {}
    post_payload = summary.get("post_refine", {}) or {}
    post_refine = (
        dataclass_from_mapping(PostRefineResult, post_payload)
        if post_payload
        else default_post_refine(metrics)
    )
    evidence_keys = {
        "actual_event_path": "actual_event_yaml",
        "counterfactual_event_path": "counterfactual_event_yaml",
        "terminal_anchor_path": "terminal_anchor_yaml",
        "grounded_summary_path": "grounded_map_summary_yaml",
        "source_inventory_path": "source_inventory_json",
        "notes_markdown_path": "notes_markdown",
    }
    manifest_context = {
        target: resolve_package_path(package, evidence.get(source, ""))
        for target, source in evidence_keys.items()
        if str(evidence.get(source, "") or "").strip()
    }
    manifest_context["explicit_grounded_assets"] = {
        key: resolve_package_path(package, raw)
        for key, raw in (evidence.get("explicit_grounded_assets", {}) or {}).items()
    }
    manifest_context["external_documents"] = list(evidence.get("external_documents", []) or [])

    report_md, report_pdf = write_generic_report(
        package,
        profile,
        manifest,
        summary_path,
        observed_log,
        dataclass_from_mapping(PvFitResult, summary.get("pv_fit", {}) or {}),
        dataclass_from_mapping(BatteryFitResult, summary.get("battery_fit", {}) or {}),
        dataclass_from_mapping(MotionFitResult, summary.get("motion_fit", {}) or {}),
        metrics,
        post_refine,
        map_assets,
        terminal_anchor=summary.get("terminal_anchor", {}) or {},
        stage_anchors=list(summary.get("stage_anchors", []) or []),
        day_metrics=list(summary.get("day_metrics", []) or []),
        battery_dynamic_fit=summary.get("battery_dynamic_fit", {}) or {},
        fit_plan=summary.get("fit_plan", {}) or {},
        grounded_map_summary=grounded_summary,
        manifest_context=manifest_context,
        terminal_consistency=terminal_consistency,
        report_dir=report_dir,
        current_maps_path=current_maps,
    )
    print(
        json.dumps(
            {"report_md": os.fspath(report_md), "report_pdf": os.fspath(report_pdf)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
