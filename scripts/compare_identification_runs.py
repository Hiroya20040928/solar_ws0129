#!/usr/bin/env python3
"""Compare immutable identification runs with the current validation gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from promote_identification_run import evaluate_gates


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_assignments(values: list[str], *, require_path: bool) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw in values:
        label, separator, value = str(raw).partition("=")
        if not separator or not label.strip() or not value.strip():
            raise ValueError("assignment must use LABEL=VALUE")
        if require_path and not Path(value).resolve().is_dir():
            raise FileNotFoundError(Path(value).resolve())
        parsed[label.strip()] = value.strip()
    return parsed


def finite(value: object) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return math.nan
    return result if math.isfinite(result) else math.nan


def load_run(label: str, run_dir: Path, role_override: str | None) -> tuple[dict, list[dict]]:
    summaries = sorted(run_dir.glob("*_generic_fit_summary.yaml"))
    if len(summaries) != 1:
        raise FileNotFoundError(f"{run_dir}: expected exactly one generic fit summary")
    summary_path = summaries[0]
    profile_path = run_dir / "profile_candidate.yaml"
    terminal_path = run_dir / "terminal_soc_consistency.yaml"
    if not profile_path.is_file() or not terminal_path.is_file():
        raise FileNotFoundError(f"{run_dir}: candidate profile or terminal consistency is missing")
    summary = yaml.safe_load(summary_path.read_text(encoding="utf-8")) or {}
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    terminal = yaml.safe_load(terminal_path.read_text(encoding="utf-8")) or {}
    if role_override:
        summary.setdefault("fit_plan", {})["terminal_anchor_role"] = role_override
    gate = evaluate_gates(profile, summary, terminal)
    metrics = summary.get("validation_metrics", {}) or {}
    battery = summary.get("battery_fit", {}) or {}
    motion = summary.get("motion_fit", {}) or {}
    pv = summary.get("pv_fit", {}) or {}
    acceleration = ((summary.get("fit_plan", {}) or {}).get("acceleration_observation_fit", {}) or {})
    row = {
        "label": label,
        "run_dir": str(run_dir),
        "summary_sha256": sha256(summary_path),
        "profile_sha256": sha256(profile_path),
        "terminal_sha256": sha256(terminal_path),
        "terminal_anchor_role": str((summary.get("fit_plan", {}) or {}).get("terminal_anchor_role", "unknown")),
        "gate_pass": bool(gate["gate_pass"]),
        "failed_gate_count": sum(not bool(value) for value in gate["checks"].values()),
        "vehicle_power_rmse_w": finite(metrics.get("power_rmse_clean_w")),
        "vehicle_voltage_rmse_v": finite(metrics.get("voltage_rmse_clean_v")),
        "vehicle_terminal_soc_error": abs(finite(metrics.get("retire_anchor_soc_error"))),
        "vehicle_terminal_voltage_error_v": abs(
            finite(metrics.get("retire_anchor_voltage_pred_v"))
            - finite(metrics.get("retire_anchor_voltage_obs_v"))
        ),
        "conditional_power_rmse_w": finite(metrics.get("battery_conditional_power_rmse_clean_w")),
        "conditional_voltage_rmse_v": finite(metrics.get("battery_conditional_voltage_rmse_clean_v")),
        "end_to_end_power_rmse_w": finite(metrics.get("end_to_end_power_rmse_clean_w")),
        "end_to_end_voltage_rmse_v": finite(metrics.get("end_to_end_voltage_rmse_clean_v")),
        "end_to_end_power_rmse_120s_w": finite(metrics.get("end_to_end_power_residual_mean_120s_rmse_w")),
        "end_to_end_energy_rmse_25km_wh": finite(metrics.get("end_to_end_energy_error_25km_rmse_wh")),
        "terminal_soc_error": finite(metrics.get("battery_conditional_retire_anchor_soc_error")),
        "terminal_voltage_error_v": abs(
            finite(metrics.get("battery_conditional_retire_anchor_voltage_pred_v"))
            - finite(metrics.get("battery_conditional_retire_anchor_voltage_obs_v"))
        ),
        "end_to_end_terminal_soc_error": abs(
            finite(metrics.get("end_to_end_retire_anchor_soc_error"))
        ),
        "end_to_end_terminal_voltage_error_v": abs(
            finite(metrics.get("end_to_end_retire_anchor_voltage_pred_v"))
            - finite(metrics.get("end_to_end_retire_anchor_voltage_obs_v"))
        ),
        "terminal_evidence_spread": finite(terminal.get("evidence_interval_max"))
        - finite(terminal.get("evidence_interval_min")),
        "acceleration_holdout_rmse_ratio": finite(acceleration.get("validation_rmse_ratio")),
        "mass_kg": finite((profile.get("model", {}) or {}).get("m")),
        "cda_m2": finite(motion.get("cda")),
        "crr": finite(motion.get("crr")),
        "p_aux_w": finite(motion.get("p_aux_w")),
        "panel_gain": finite(pv.get("panel_gain")),
        "e_nom_wh": finite(battery.get("e_nom_wh")),
        "q_nom_ah": finite((profile.get("model", {}) or {}).get("Q_nom_Ah")),
        "rint_scale": finite(battery.get("rint_scale")),
        "r_line_ohm": finite(battery.get("r_line_ohm")),
        "grade_scale": finite(motion.get("grade_scale")),
        "drive_eff_scale": finite(motion.get("drive_eff_scale")),
        "headwind_gain": finite(motion.get("headwind_gain")),
    }
    checks = [
        {
            "label": label,
            "check": key,
            "passed": bool(value),
            "value": gate["values"].get(key, gate["values"].get(key.removesuffix("_w"), "")),
        }
        for key, value in gate["checks"].items()
    ]
    return row, checks


def write_plot(frame: pd.DataFrame, output: Path) -> None:
    metrics = [
        ("vehicle_power_rmse_w", "vehicle replay power [W]"),
        ("end_to_end_power_rmse_w", "end-to-end power [W]"),
        ("end_to_end_power_rmse_120s_w", "120 s power [W]"),
        ("end_to_end_energy_rmse_25km_wh", "25 km energy [Wh]"),
    ]
    figure, axes = plt.subplots(2, 2, figsize=(9.0, 6.2), constrained_layout=True)
    styles = ["white", "0.75", "0.45", "0.2"]
    for axis, (column, title) in zip(axes.flat, metrics):
        bars = axis.bar(frame["label"], frame[column], color=styles[: len(frame)], edgecolor="black")
        axis.set_title(title)
        axis.grid(axis="y", color="0.85", linewidth=0.6)
        axis.tick_params(axis="x", rotation=20)
        for bar, value in zip(bars, frame[column]):
            if math.isfinite(float(value)):
                axis.text(bar.get_x() + bar.get_width() / 2.0, bar.get_height(), f"{value:.2f}", ha="center", va="bottom", fontsize=8)
    figure.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(figure)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True, metavar="LABEL=RUN_DIR")
    parser.add_argument("--role", action="append", default=[], metavar="LABEL=ROLE")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    runs = parse_assignments(args.run, require_path=True)
    roles = parse_assignments(args.role, require_path=False)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    checks: list[dict] = []
    for label, raw_path in runs.items():
        row, run_checks = load_run(label, Path(raw_path).resolve(), roles.get(label))
        rows.append(row)
        checks.extend(run_checks)
    frame = pd.DataFrame(rows)
    frame.to_csv(output / "identification_run_comparison.csv", index=False)
    pd.DataFrame(checks).to_csv(output / "identification_gate_checks.csv", index=False)
    write_plot(frame, output / "identification_rmse_comparison.png")
    payload = {
        "scope": "current-code reassessment of immutable identification outputs",
        "role_overrides": roles,
        "runs": rows,
        "all_runs_pass": bool(rows and all(row["gate_pass"] for row in rows)),
        "caution": "A role override classifies evidence provenance; it does not alter fitted values or turn a failed numerical gate into a pass.",
    }
    (output / "identification_run_comparison.yaml").write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
