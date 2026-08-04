#!/usr/bin/env python3
"""Run isolated MLE comparisons for provisional legacy-R0 replacements.

This is a diagnostic bridge for historical packages that have no independent
rest/pulse data.  It deliberately cannot create release-grade battery evidence.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_bwsc2025_fitted_package import (
    load_reference_loaded_voltage_curve,
    project_rint_map_shape_constraints,
)


DEFAULT_PACKAGE = ROOT / "project_packages" / "bwsc2025_fitted_mle19_energywindow_inertia"
DEFAULT_BASELINE_RUN = (
    DEFAULT_PACKAGE
    / "outputs"
    / "identification"
    / "runs"
    / "mle35_expanded_grade_single_source_ultra_v1"
)


def empirical_soc_resistance_shape(soc) -> np.ndarray:
    """Return the dimensionless shape source used by the 2017 literature audit.

    The published polynomial has resistance units, but this experiment uses
    only ratios.  Its absolute magnitude belongs to a different cell and is
    therefore never transferred to the YATA pack.
    """
    z = np.asarray(soc, dtype=float)
    return 0.002 * z * z - 0.001 * z + 0.002


def build_empirical_high_soc_surrogate(
    source: pd.DataFrame,
    *,
    anchor_soc: float,
) -> tuple[pd.DataFrame, dict]:
    """Replace the legacy high-SoC spike by a continuous empirical-shape branch."""
    work = source.copy()
    work.index = pd.to_numeric(work.index, errors="raise")
    work.columns = pd.to_numeric(work.columns, errors="raise")
    work = work.sort_index().sort_index(axis=1)
    values = work.to_numpy(dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        raise ValueError("Rint map must contain finite positive values")
    soc = work.columns.to_numpy(dtype=float)
    if len(soc) < 3 or not float(soc[0]) < float(anchor_soc) < float(soc[-1]):
        raise ValueError("empirical high-SoC anchor must lie inside the map domain")

    anchor_index = int(np.searchsorted(soc, float(anchor_soc), side="right") - 1)
    anchor_index = int(np.clip(anchor_index, 0, len(soc) - 2))
    anchor_grid_soc = float(soc[anchor_index])
    shape = empirical_soc_resistance_shape(soc)
    shape_anchor = float(empirical_soc_resistance_shape([anchor_grid_soc])[0])
    projected = values.copy()
    projected[:, anchor_index:] = (
        values[:, [anchor_index]] * shape[None, anchor_index:] / shape_anchor
    )
    result = pd.DataFrame(projected, index=work.index, columns=work.columns)
    ratio = projected / values
    high_slice_before = values[:, anchor_index:]
    high_slice_after = projected[:, anchor_index:]
    report = {
        "method": "continuous normalized empirical high-SoC branch",
        "source_equation": "q(z)=0.002*z^2-0.001*z+0.002",
        "source_equation_role": "relative shape only; no absolute resistance transfer",
        "requested_anchor_soc": float(anchor_soc),
        "anchor_grid_soc": anchor_grid_soc,
        "high_soc_relative_gain_at_map_end": float(shape[-1] / shape_anchor),
        "changed_cell_count": int(np.count_nonzero(np.abs(projected - values) > 1.0e-12)),
        "total_cell_count": int(values.size),
        "correction_ratio_min": float(np.min(ratio)),
        "correction_ratio_max": float(np.max(ratio)),
        "legacy_high_soc_min_ohm": float(np.min(high_slice_before)),
        "legacy_high_soc_max_ohm": float(np.max(high_slice_before)),
        "surrogate_high_soc_min_ohm": float(np.min(high_slice_after)),
        "surrogate_high_soc_max_ohm": float(np.max(high_slice_after)),
        "voltage_term_separation": (
            "equilibrium high-SoC slope remains in Uocv(z); temporal voltage lag is refitted "
            "as the 1-RC polarization branch; this proxy is only the instantaneous R0 branch"
        ),
        "physical_evidence_gate_pass": False,
        "release_eligible": False,
    }
    return result, report


def _interp_map_value(frame: pd.DataFrame, temperature_c: float, soc: float) -> float:
    work = frame.copy()
    work.index = pd.to_numeric(work.index, errors="raise")
    work.columns = pd.to_numeric(work.columns, errors="raise")
    work = work.sort_index().sort_index(axis=1)
    by_temperature = np.array(
        [
            np.interp(float(soc), work.columns.to_numpy(dtype=float), row)
            for row in work.to_numpy(dtype=float)
        ],
        dtype=float,
    )
    return float(
        np.interp(float(temperature_c), work.index.to_numpy(dtype=float), by_temperature)
    )


def build_neutral_r0_surrogate(
    source: pd.DataFrame,
    *,
    anchor_soc: float = 0.50,
    anchor_temperature_c: float = 25.0,
) -> tuple[pd.DataFrame, dict]:
    """Remove unsupported SoC/temperature shape while preserving one scale anchor."""
    work = source.copy()
    work.index = pd.to_numeric(work.index, errors="raise")
    work.columns = pd.to_numeric(work.columns, errors="raise")
    work = work.sort_index().sort_index(axis=1)
    values = work.to_numpy(dtype=float)
    if not np.all(np.isfinite(values)) or np.any(values <= 0.0):
        raise ValueError("Rint map must contain finite positive values")
    anchor_ohm = _interp_map_value(work, anchor_temperature_c, anchor_soc)
    projected = np.full_like(values, anchor_ohm, dtype=float)
    result = pd.DataFrame(projected, index=work.index, columns=work.columns)
    ratio = projected / values
    return result, {
        "method": "least-informative constant R0 counterfactual",
        "anchor_soc": float(anchor_soc),
        "anchor_temperature_c": float(anchor_temperature_c),
        "anchor_pack_resistance_ohm": float(anchor_ohm),
        "soc_dependence_assumed": False,
        "temperature_dependence_assumed": False,
        "changed_cell_count": int(np.count_nonzero(np.abs(projected - values) > 1.0e-12)),
        "total_cell_count": int(values.size),
        "correction_ratio_min": float(np.min(ratio)),
        "correction_ratio_max": float(np.max(ratio)),
        "interpretation": (
            "diagnostic removal of unsupported map shape; the retained scale is not an "
            "independently identified instantaneous resistance"
        ),
        "physical_evidence_gate_pass": False,
        "release_eligible": False,
    }


def build_loaded_shape_ocv_surrogate(
    source_ocv: pd.DataFrame,
    loaded_curve: pd.DataFrame,
    *,
    anchor_soc: float = 0.50,
) -> tuple[pd.DataFrame, dict]:
    """Keep the observed voltage shape once, without slope-derived R0 correction."""
    required_ocv = {"soc", "ocv_v"}
    required_loaded = {"soc", "loaded_pack_v"}
    if not required_ocv.issubset(source_ocv.columns):
        raise ValueError("source OCV must contain soc and ocv_v")
    if not required_loaded.issubset(loaded_curve.columns):
        raise ValueError("loaded curve must contain soc and loaded_pack_v")
    source = source_ocv[["soc", "ocv_v"]].apply(pd.to_numeric, errors="coerce").dropna()
    loaded = loaded_curve[["soc", "loaded_pack_v"]].apply(pd.to_numeric, errors="coerce").dropna()
    source = source.sort_values("soc").drop_duplicates("soc")
    loaded = loaded.sort_values("soc").drop_duplicates("soc")
    soc_grid = source["soc"].to_numpy(dtype=float)
    loaded_on_grid = np.interp(
        soc_grid,
        loaded["soc"].to_numpy(dtype=float),
        loaded["loaded_pack_v"].to_numpy(dtype=float),
    )
    source_anchor = float(np.interp(anchor_soc, soc_grid, source["ocv_v"].to_numpy(dtype=float)))
    loaded_anchor = float(
        np.interp(
            anchor_soc,
            loaded["soc"].to_numpy(dtype=float),
            loaded["loaded_pack_v"].to_numpy(dtype=float),
        )
    )
    offset_v = source_anchor - loaded_anchor
    candidate = loaded_on_grid + offset_v
    candidate = np.maximum.accumulate(candidate)
    result = pd.DataFrame({"soc": soc_grid, "ocv_v": candidate})
    return result, {
        "method": "loaded-curve-shape counterfactual with constant voltage alignment",
        "anchor_soc": float(anchor_soc),
        "constant_alignment_offset_v": float(offset_v),
        "loaded_voltage_slope_used_as_r0": False,
        "slope_dependent_voltage_correction_used": False,
        "interpretation": (
            "diagnostic OCV-shape surrogate only; the constant alignment is inherited from the "
            "reference model and is not a rested-OCV measurement"
        ),
        "physical_evidence_gate_pass": False,
        "release_eligible": False,
    }


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )


def relpath(path: Path, base: Path) -> str:
    return os.path.relpath(path.resolve(), base.resolve()).replace("\\", "/")


def rebase_profile_paths(cfg: dict, source_profile: Path, package_dir: Path) -> dict:
    out = copy.deepcopy(cfg)
    for key, raw in list((out.get("paths", {}) or {}).items()):
        if not isinstance(raw, str) or not raw.strip():
            continue
        source = Path(raw)
        if not source.is_absolute():
            source = (source_profile.parent / source).resolve()
        out["paths"][key] = relpath(source, package_dir)
    return out


def plot_maps(
    source: pd.DataFrame,
    projected: pd.DataFrame,
    output: Path,
    *,
    candidate_title: str = "Diagnostic replacement map",
) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
    for temperature in source.index:
        axes[0].plot(
            source.columns.astype(float),
            source.loc[temperature].to_numpy(dtype=float),
            marker="o",
            label=f"{float(temperature):g} C",
        )
        axes[1].plot(
            projected.columns.astype(float),
            projected.loc[temperature].to_numpy(dtype=float),
            marker="o",
            label=f"{float(temperature):g} C",
        )
    axes[0].set_title("Historical MLE35 Rint map")
    axes[1].set_title(candidate_title)
    for axis in axes:
        axis.set_xlabel("SoC [-]")
        axis.set_ylabel("Pack resistance [ohm]")
        axis.grid(True, alpha=0.3)
        axis.legend()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def plot_ocv_curves(source: pd.DataFrame, candidate: pd.DataFrame, output: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(9, 8), constrained_layout=True)
    source_soc = source["soc"].to_numpy(dtype=float)
    source_v = source["ocv_v"].to_numpy(dtype=float)
    candidate_soc = candidate["soc"].to_numpy(dtype=float)
    candidate_v = candidate["ocv_v"].to_numpy(dtype=float)
    axes[0].plot(source_soc, source_v, label="historical pseudo-OCV", linewidth=2)
    axes[0].plot(candidate_soc, candidate_v, label="deconfounded diagnostic shape", linewidth=2)
    axes[0].set(xlabel="SoC [-]", ylabel="pack voltage [V]", title="OCV-map counterfactual")
    axes[0].grid(True, alpha=0.3)
    axes[0].legend()
    common_soc = np.unique(np.concatenate([source_soc, candidate_soc]))
    delta = np.interp(common_soc, candidate_soc, candidate_v) - np.interp(
        common_soc, source_soc, source_v
    )
    axes[1].plot(common_soc, delta, color="#b45309", linewidth=2)
    axes[1].axhline(0.0, color="black", linewidth=1)
    axes[1].set(xlabel="SoC [-]", ylabel="candidate - historical [V]", title="Removed voltage-shape term")
    axes[1].grid(True, alpha=0.3)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180)
    plt.close(fig)


def finite_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def compare_summaries(reference: dict, candidate: dict) -> list[dict]:
    baseline_metrics = reference.get("validation_metrics", {}) or {}
    candidate_metrics = candidate.get("validation_metrics", {}) or {}
    metric_keys = (
        "power_rmse_clean_w",
        "voltage_rmse_clean_v",
        "battery_conditional_voltage_rmse_clean_v",
        "end_to_end_power_rmse_clean_w",
        "end_to_end_voltage_rmse_clean_v",
        "power_residual_mean_120s_rmse_w",
        "energy_error_25km_rmse_wh",
        "end_to_end_energy_error_25km_rmse_wh",
        "retire_anchor_soc_error",
        "retire_anchor_voltage_pred_v",
        "end_to_end_retire_anchor_soc_error",
        "end_to_end_retire_anchor_voltage_pred_v",
    )
    rows = []
    for key in metric_keys:
        old = finite_number(baseline_metrics.get(key))
        new = finite_number(candidate_metrics.get(key))
        delta = None if old is None or new is None else new - old
        percent = None if delta is None or abs(old) < 1.0e-12 else 100.0 * delta / abs(old)
        rows.append(
            {
                "metric": key,
                "reference": old,
                "candidate": new,
                "candidate_minus_reference": delta,
                "change_percent": percent,
            }
        )
    return rows


def compare_fit_parameters(reference: dict, candidate: dict) -> list[dict]:
    rows = []
    for section, keys in {
        "battery_fit": ("soc0", "e_nom_wh", "rint_scale", "r_line_ohm", "eta_charge", "voltage_rmse_v"),
        "battery_dynamic_fit": ("r_polarization_ohm", "tau_sec", "rmse_after_v", "validation_rmse_after_v"),
        "motion_fit": ("cda", "crr", "drive_eff_scale", "grade_scale", "headwind_gain", "p_aux_w"),
        "pv_fit": ("panel_gain", "solar_rmse_w", "stop_solar_rmse_w"),
    }.items():
        old_section = reference.get(section, {}) or {}
        new_section = candidate.get(section, {}) or {}
        for key in keys:
            old = finite_number(old_section.get(key))
            new = finite_number(new_section.get(key))
            rows.append(
                {
                    "parameter": f"{section}.{key}",
                    "reference": old,
                    "candidate": new,
                    "candidate_minus_reference": None if old is None or new is None else new - old,
                }
            )
    return rows


def fit_boundary_diagnostics(candidate: dict) -> list[dict]:
    battery = candidate.get("battery_fit", {}) or {}
    checks = (
        ("battery_fit.rint_scale", battery.get("rint_scale"), 0.90, 0.96),
        ("battery_fit.r_line_ohm", battery.get("r_line_ohm"), 0.005, 0.012),
        ("battery_fit.eta_charge", battery.get("eta_charge"), 0.97, 0.999),
    )
    rows = []
    for parameter, raw_value, lower, upper in checks:
        value = finite_number(raw_value)
        tolerance = 1.0e-6 * max(1.0, abs(lower), abs(upper))
        rows.append(
            {
                "parameter": parameter,
                "value": value,
                "lower_bound": lower,
                "upper_bound": upper,
                "at_lower_bound": bool(value is not None and abs(value - lower) <= tolerance),
                "at_upper_bound": bool(value is not None and abs(value - upper) <= tolerance),
            }
        )
    return rows


def compare_soc_binned_voltage_residuals(
    reference_run: Path,
    candidate_run: Path,
) -> list[dict]:
    """Compare clean voltage residuals without hiding high-SoC regressions."""
    replay_files = {
        "vehicle": "replay_validation.csv",
        "battery_conditioned": "replay_validation_battery_conditioned.csv",
        "end_to_end": "replay_validation_end_to_end.csv",
    }
    bins = (
        ("0.00-0.20", 0.00, 0.20),
        ("0.20-0.50", 0.20, 0.50),
        ("0.50-0.75", 0.50, 0.75),
        ("0.75-0.85", 0.75, 0.85),
        ("0.85-0.90", 0.85, 0.90),
        ("0.90-1.00", 0.90, 1.000001),
    )
    rows = []
    for replay_name, filename in replay_files.items():
        frames = {
            "reference": pd.read_csv(reference_run / filename, low_memory=False),
            "candidate": pd.read_csv(candidate_run / filename, low_memory=False),
        }
        metrics = {}
        for run_name, frame in frames.items():
            soc = pd.to_numeric(frame["soc_pred"], errors="coerce").to_numpy(dtype=float)
            observed = pd.to_numeric(
                frame["battery_voltage_v_obs"], errors="coerce"
            ).to_numpy(dtype=float)
            predicted = pd.to_numeric(
                frame["battery_voltage_v_pred"], errors="coerce"
            ).to_numpy(dtype=float)
            excluded = frame["exclude_voltage_fit"].astype(bool).to_numpy()
            for label, lower, upper in bins:
                mask = (
                    (~excluded)
                    & np.isfinite(soc)
                    & np.isfinite(observed)
                    & np.isfinite(predicted)
                    & (soc >= lower)
                    & (soc < upper)
                )
                residual = predicted[mask] - observed[mask]
                metrics[(run_name, label)] = {
                    "count": int(mask.sum()),
                    "bias_v": float(np.mean(residual)) if len(residual) else None,
                    "mae_v": float(np.mean(np.abs(residual))) if len(residual) else None,
                    "rmse_v": float(np.sqrt(np.mean(residual * residual))) if len(residual) else None,
                }
        for label, _, _ in bins:
            reference = metrics[("reference", label)]
            candidate = metrics[("candidate", label)]
            ref_rmse = reference["rmse_v"]
            new_rmse = candidate["rmse_v"]
            rows.append(
                {
                    "replay": replay_name,
                    "soc_bin": label,
                    "reference_count": reference["count"],
                    "candidate_count": candidate["count"],
                    "reference_bias_v": reference["bias_v"],
                    "candidate_bias_v": candidate["bias_v"],
                    "reference_rmse_v": ref_rmse,
                    "candidate_rmse_v": new_rmse,
                    "candidate_minus_reference_rmse_v": (
                        None if ref_rmse is None or new_rmse is None else new_rmse - ref_rmse
                    ),
                }
            )
    return rows


def write_comparison_report(
    path: Path,
    *,
    tag: str,
    projection: dict,
    rows: list[dict],
    parameter_rows: list[dict],
    boundary_rows: list[dict],
    baseline_quality: str,
    candidate_quality: str,
    validation_gate: dict,
    candidate_summary: Path,
    final_map: Path,
    reference_label: str,
    soc_binned_rows: list[dict],
) -> None:
    lines = [
        f"# Provisional Rint replacement MLE comparison: {tag}",
        "",
        "## Status",
        "",
        "- This run is diagnostic only and is not eligible for operational promotion.",
        "- Independent rested multi-current pulse evidence was not available.",
        "- The R0 base map was the historical MLE35 map processed by the declared diagnostic replacement.",
        "- A lower RMSE does not prove that the projected R0 surface is physically correct.",
        f"- Reference run: `{reference_label}`.",
        f"- Reference fit quality: `{baseline_quality}`; candidate fit quality: `{candidate_quality}`.",
        f"- Independent model-validation gate: `{validation_gate.get('gate_pass', False)}`.",
        "",
        "## Projection",
        "",
    ]
    lines.extend(f"- {key}: `{value}`" for key, value in projection.items())
    lines.extend(
        [
            "",
            "## Residual comparison",
            "",
            "| metric | reference | candidate | delta | change [%] |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for row in rows:
        values = [row[key] for key in ("reference", "candidate", "candidate_minus_reference", "change_percent")]
        formatted = ["--" if value is None else f"{value:.9g}" for value in values]
        lines.append(f"| {row['metric']} | " + " | ".join(formatted) + " |")
    lines.extend(
        [
            "",
            "## Parameter compensation",
            "",
            "| parameter | reference | candidate | delta |",
            "|---|---:|---:|---:|",
        ]
    )
    for row in parameter_rows:
        values = [row[key] for key in ("reference", "candidate", "candidate_minus_reference")]
        formatted = ["--" if value is None else f"{value:.9g}" for value in values]
        lines.append(f"| {row['parameter']} | " + " | ".join(formatted) + " |")
    lines.extend(
        [
            "",
            "## SoC-binned voltage residuals",
            "",
            "| replay | SoC | n | reference RMSE [V] | candidate RMSE [V] | delta [V] |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in soc_binned_rows:
        reference_rmse = row["reference_rmse_v"]
        candidate_rmse = row["candidate_rmse_v"]
        delta_rmse = row["candidate_minus_reference_rmse_v"]
        formatted = [
            "--" if value is None else f"{value:.9g}"
            for value in (reference_rmse, candidate_rmse, delta_rmse)
        ]
        lines.append(
            f"| {row['replay']} | {row['soc_bin']} | {row['candidate_count']} | "
            + " | ".join(formatted)
            + " |"
        )
    lines.extend(["", "## Active-bound diagnostics", ""])
    for row in boundary_rows:
        lines.append(
            f"- `{row['parameter']}` = `{row['value']}` in "
            f"[`{row['lower_bound']}`, `{row['upper_bound']}`]; "
            f"lower={row['at_lower_bound']}, upper={row['at_upper_bound']}"
        )
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- candidate fit summary: `{candidate_summary}`",
            f"- final fitted Rint map: `{final_map}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-dir", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--baseline-run", type=Path, default=DEFAULT_BASELINE_RUN)
    parser.add_argument(
        "--comparison-run",
        type=Path,
        default=None,
        help="Optional same-quality unchanged-map run used as the residual reference.",
    )
    parser.add_argument("--tag", default="mle35_rint_shape_constrained_ultra_20260802")
    parser.add_argument("--quality", choices=("quick", "standard", "full", "ultra"), default="ultra")
    parser.add_argument("--high-soc-from", type=float, default=0.50)
    parser.add_argument(
        "--projection-mode",
        choices=("deconfounded_neutral", "empirical_high_soc", "constrained", "legacy"),
        default="constrained",
        help=(
            "Run the jointly deconfounded OCV/R0 counterfactual, empirical high-SoC proxy, "
            "legacy monotone counterfactual, or unchanged-map control; no mode is release identification."
        ),
    )
    parser.add_argument(
        "--skip-map-shape-fit",
        action="store_true",
        help="Lock every supplied base-map shape so the run isolates scalar refitting.",
    )
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument(
        "--summarize-existing",
        action="store_true",
        help="Do not rerun MLE; rebuild comparison and gate reports for an existing tagged run.",
    )
    args = parser.parse_args()

    package_dir = args.package_dir.resolve()
    baseline_run = args.baseline_run.resolve()
    comparison_run = (
        args.comparison_run.resolve() if args.comparison_run is not None else baseline_run
    )
    baseline_profile = baseline_run / "profile_candidate.yaml"
    comparison_summary = comparison_run / f"{package_dir.name}_generic_fit_summary.yaml"
    baseline_rint = baseline_run / "adopted_maps" / "Rint_T_by_soc_fitted_grounded.csv"
    baseline_ocv = baseline_run / "adopted_maps" / "ocv_soc_curve_fitted_grounded.csv"
    if not baseline_ocv.is_file():
        ocv_candidates = sorted((baseline_run / "adopted_maps").glob("ocv_soc_curve*.csv"))
        if ocv_candidates:
            baseline_ocv = ocv_candidates[0]
    source_manifest = package_dir / "data" / "identification" / "identification_manifest.yaml"
    for required in (baseline_profile, comparison_summary, baseline_rint, baseline_ocv, source_manifest):
        if not required.is_file():
            raise FileNotFoundError(required)

    experiment_dir = package_dir / "outputs" / "identification" / "experiments" / args.tag
    input_dir = experiment_dir / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    candidate_rint = input_dir / f"Rint_T_by_soc_{args.projection_mode}_diagnostic.csv"
    candidate_ocv = input_dir / f"ocv_soc_curve_{args.projection_mode}_diagnostic.csv"

    source_map = pd.read_csv(baseline_rint, index_col=0)
    source_ocv = pd.read_csv(baseline_ocv)
    ocv_projection = {
        "method": "unchanged historical pseudo-OCV control",
        "physical_evidence_gate_pass": False,
        "release_eligible": False,
    }
    if args.projection_mode == "deconfounded_neutral":
        projected_map, projection = build_neutral_r0_surrogate(
            source_map,
            anchor_soc=float(args.high_soc_from),
        )
        projected_ocv, ocv_projection = build_loaded_shape_ocv_surrogate(
            source_ocv,
            load_reference_loaded_voltage_curve(),
            anchor_soc=float(args.high_soc_from),
        )
        candidate_title = "Neutral R0-shape counterfactual"
    elif args.projection_mode == "empirical_high_soc":
        projected_map, projection = build_empirical_high_soc_surrogate(
            source_map,
            anchor_soc=float(args.high_soc_from),
        )
        projected_ocv = source_ocv.copy()
        candidate_title = "OCV/1-RC-separated empirical R0 proxy"
    elif args.projection_mode == "constrained":
        projected_map, projection = project_rint_map_shape_constraints(
            source_map,
            high_soc_from=float(args.high_soc_from),
            enforce_temperature_nonincreasing=True,
        )
        projected_ocv = source_ocv.copy()
        candidate_title = "Legacy monotone counterfactual"
    else:
        projected_map = source_map.copy()
        projected_ocv = source_ocv.copy()
        projection = {
            "method": "unchanged legacy-map control",
            "high_soc_nonincreasing_from": None,
            "temperature_nonincreasing": None,
            "constraint_count": 0,
            "changed_cell_count": 0,
            "total_cell_count": int(source_map.size),
            "correction_ratio_min": 1.0,
            "correction_ratio_max": 1.0,
            "log_rmse_change": 0.0,
            "max_constraint_violation": None,
            "optimizer_success": True,
            "optimizer_message": "projection disabled for controlled baseline",
            "interpretation": "legacy-map control; not release eligible",
        }
        candidate_title = "Unchanged legacy-map control"
    projected_map.to_csv(candidate_rint)
    projected_ocv.to_csv(candidate_ocv, index=False)
    plot_maps(
        source_map,
        projected_map,
        experiment_dir / "rint_before_after.png",
        candidate_title=candidate_title,
    )
    plot_ocv_curves(source_ocv, projected_ocv, experiment_dir / "ocv_before_after.png")

    profile_cfg = rebase_profile_paths(load_yaml(baseline_profile), baseline_profile, package_dir)
    profile_cfg.setdefault("paths", {})["rint_map"] = relpath(candidate_rint, package_dir)
    profile_cfg.setdefault("paths", {})["ocv_soc_map"] = relpath(candidate_ocv, package_dir)
    profile_cfg.setdefault("meta", {})["release_status"] = "research_only_unidentified_battery_maps"
    profile_cfg["meta"]["production_live_allowed"] = False
    profile_cfg.setdefault("meta", {}).setdefault("notes", []).append(
        f"Diagnostic-only Rint {args.projection_mode} MLE experiment; "
        "not release eligible without independent pulse evidence."
    )
    identification_cfg = profile_cfg.setdefault("identification", {})
    identification_cfg["rint_shape_constraint"] = {
        "enabled": args.projection_mode == "constrained",
        "high_soc_nonincreasing_from": float(args.high_soc_from),
        "temperature_nonincreasing": True,
        "physical_evidence_gate_pass": False,
        "release_eligible": False,
    }
    identification_cfg["provisional_battery_term_separation"] = {
        "enabled": args.projection_mode in {"deconfounded_neutral", "empirical_high_soc"},
        "terminal_voltage_equation": "Vt=Uocv(z)-I*R0_proxy(z,T)-Vp",
        "equilibrium_high_soc_voltage_slope_term": "Uocv(z)",
        "instantaneous_voltage_drop_term": "I*R0_proxy(z,T)",
        "temporal_polarization_term": "Vp from refitted 1-RC branch",
        "r0_proxy_shape": projection.get("source_equation", "not applicable"),
        "ocv_projection": ocv_projection,
        "release_eligible": False,
    }
    experiment_profile = package_dir / f"profile_{args.tag}.yaml"
    write_yaml(experiment_profile, profile_cfg)

    manifest = load_yaml(source_manifest)
    manifest.pop("grounded_sources", None)
    manifest.setdefault("options", {})["use_grounded_base_maps"] = False
    manifest["options"]["allow_map_shape_fit"] = not bool(args.skip_map_shape_fit)
    manifest["diagnostic_experiment"] = {
        "kind": "provisional_r0_replacement_then_full_mle",
        "projection_mode": args.projection_mode,
        "map_shape_fit_enabled": not bool(args.skip_map_shape_fit),
        "source_rint_map": relpath(baseline_rint, package_dir),
        "candidate_rint_map": relpath(candidate_rint, package_dir),
        "source_ocv_map": relpath(baseline_ocv, package_dir),
        "candidate_ocv_map": relpath(candidate_ocv, package_dir),
        "independent_pulse_evidence_available": False,
        "release_eligible": False,
    }
    experiment_manifest = input_dir / "identification_manifest.yaml"
    write_yaml(experiment_manifest, manifest)

    preparation = {
        "tag": args.tag,
        "status": "prepared",
        "physical_evidence_gate_pass": False,
        "release_eligible": False,
        "reason": "independent rested multi-current pulse evidence is absent",
        "source_profile": str(baseline_profile),
        "comparison_run": str(comparison_run),
        "comparison_summary": str(comparison_summary),
        "source_manifest": str(source_manifest),
        "source_rint_map": str(baseline_rint),
        "candidate_rint_map": str(candidate_rint),
        "source_ocv_map": str(baseline_ocv),
        "candidate_ocv_map": str(candidate_ocv),
        "experiment_profile": str(experiment_profile),
        "experiment_manifest": str(experiment_manifest),
        "projection": projection,
        "ocv_projection": ocv_projection,
        "projection_mode": args.projection_mode,
        "map_shape_fit_enabled": not bool(args.skip_map_shape_fit),
    }
    preparation_path = experiment_dir / "experiment_status.json"
    preparation_path.write_text(json.dumps(preparation, indent=2), encoding="utf-8")
    print(json.dumps(preparation, indent=2), flush=True)
    if args.prepare_only:
        return

    command = [
        sys.executable,
        str(ROOT / "scripts" / "run_vehicle_identification.py"),
        "--profile",
        str(experiment_profile),
        "--manifest",
        str(experiment_manifest),
        "--quality",
        args.quality,
        "--output-tag",
        args.tag,
    ]
    if args.skip_map_shape_fit:
        command.append("--skip-map-shape-fit")
    preparation["command"] = command
    if not args.summarize_existing:
        preparation["status"] = "mle_running"
        preparation_path.write_text(json.dumps(preparation, indent=2), encoding="utf-8")
        subprocess.run(command, cwd=ROOT, check=True)

    candidate_run = package_dir / "outputs" / "identification" / "runs" / args.tag
    candidate_summary = candidate_run / f"{package_dir.name}_generic_fit_summary.yaml"
    final_map = candidate_run / "adopted_maps" / "Rint_T_by_soc_fitted_shape_constrained_diagnostic.csv"
    if not final_map.is_file():
        candidates = sorted((candidate_run / "adopted_maps").glob("Rint_T_by_soc*.csv"))
        if candidates:
            final_map = candidates[0]
        elif args.skip_map_shape_fit and candidate_rint.is_file():
            # With map-shape fitting disabled, the supplied base map is used
            # directly and is intentionally not duplicated under adopted_maps.
            final_map = candidate_rint
        else:
            raise FileNotFoundError("candidate run did not emit an adopted Rint map")
    baseline_payload = load_yaml(comparison_summary)
    candidate_payload = load_yaml(candidate_summary)
    rows = compare_summaries(baseline_payload, candidate_payload)
    parameter_rows = compare_fit_parameters(baseline_payload, candidate_payload)
    boundary_rows = fit_boundary_diagnostics(candidate_payload)
    soc_binned_rows = compare_soc_binned_voltage_residuals(comparison_run, candidate_run)
    baseline_quality = str((baseline_payload.get("fit_plan", {}) or {}).get("quality", "unknown"))
    candidate_quality = str((candidate_payload.get("fit_plan", {}) or {}).get("quality", "unknown"))
    gate_path = experiment_dir / "model_validation_gate.json"
    gate_process = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_model_validation_gate.py"),
            "--profile",
            str(candidate_run / "profile_candidate.yaml"),
            "--output",
            str(gate_path),
        ],
        cwd=ROOT,
        check=False,
    )
    if not gate_path.is_file():
        raise RuntimeError(
            f"model-validation gate did not produce {gate_path} "
            f"(exit={gate_process.returncode})"
        )
    validation_gate = json.loads(gate_path.read_text(encoding="utf-8"))
    comparison_csv = experiment_dir / "reference_vs_candidate_metrics.csv"
    pd.DataFrame(rows).to_csv(comparison_csv, index=False)
    parameter_csv = experiment_dir / "reference_vs_candidate_parameters.csv"
    pd.DataFrame(parameter_rows).to_csv(parameter_csv, index=False)
    soc_binned_csv = experiment_dir / "reference_vs_candidate_soc_binned_voltage.csv"
    pd.DataFrame(soc_binned_rows).to_csv(soc_binned_csv, index=False)
    report_path = experiment_dir / "comparison_report.md"
    write_comparison_report(
        report_path,
        tag=args.tag,
        projection=projection,
        rows=rows,
        parameter_rows=parameter_rows,
        boundary_rows=boundary_rows,
        baseline_quality=baseline_quality,
        candidate_quality=candidate_quality,
        validation_gate=validation_gate,
        candidate_summary=candidate_summary,
        final_map=final_map,
        reference_label=comparison_run.name,
        soc_binned_rows=soc_binned_rows,
    )
    high_soc_battery_rows = [
        row
        for row in soc_binned_rows
        if row["replay"] == "battery_conditioned" and row["soc_bin"] in {"0.85-0.90", "0.90-1.00"}
    ]
    high_soc_regression_v = max(
        [
            float(row["candidate_minus_reference_rmse_v"])
            for row in high_soc_battery_rows
            if row["candidate_minus_reference_rmse_v"] is not None
        ]
        or [float("nan")]
    )
    if np.isfinite(high_soc_regression_v) and high_soc_regression_v <= 0.0:
        residual_reason = (
            "high-SoC battery-conditioned residual did not regress, but the independent "
            "battery-evidence and model-validation gates failed"
        )
    elif np.isfinite(high_soc_regression_v):
        residual_reason = (
            "high-SoC battery-conditioned residual regressed and the independent "
            "battery-evidence and model-validation gates failed"
        )
    else:
        residual_reason = (
            "high-SoC residual coverage was insufficient and the independent "
            "battery-evidence and model-validation gates failed"
        )
    provisional_decision = {
        "structural_spike_removed": bool(
            args.projection_mode in {"deconfounded_neutral", "empirical_high_soc"}
        ),
        "loaded_curve_slope_removed_from_r0": bool(
            args.projection_mode == "deconfounded_neutral"
        ),
        "capacity_temperature_proxy_removed_from_r0": bool(
            args.projection_mode == "deconfounded_neutral"
        ),
        "same_quality_reference": bool(baseline_quality == candidate_quality),
        "high_soc_battery_conditioned_rmse_regression_v": high_soc_regression_v,
        "model_validation_gate_pass": bool(validation_gate.get("gate_pass", False)),
        "research_candidate_retained": bool(
            args.projection_mode in {"deconfounded_neutral", "empirical_high_soc"}
        ),
        "operational_promotion_allowed": False,
        "reason": (
            "structurally preferable provisional proxy that removes the legacy confounding; "
            + residual_reason
        ),
    }
    preparation.update(
        {
            "status": "complete",
            "candidate_run": str(candidate_run),
            "candidate_summary": str(candidate_summary),
            "final_rint_map": str(final_map),
            "comparison_csv": str(comparison_csv),
            "parameter_comparison_csv": str(parameter_csv),
            "soc_binned_voltage_comparison_csv": str(soc_binned_csv),
            "comparison_report": str(report_path),
            "baseline_fit_quality": baseline_quality,
            "comparison_run": str(comparison_run),
            "candidate_fit_quality": candidate_quality,
            "model_validation_gate_json": str(gate_path),
            "model_validation_gate_pass": bool(validation_gate.get("gate_pass", False)),
            "metrics": rows,
            "parameter_changes": parameter_rows,
            "fit_boundary_diagnostics": boundary_rows,
            "provisional_decision": provisional_decision,
        }
    )
    preparation_path.write_text(json.dumps(preparation, indent=2), encoding="utf-8")
    print(json.dumps(preparation, indent=2), flush=True)


if __name__ == "__main__":
    main()
