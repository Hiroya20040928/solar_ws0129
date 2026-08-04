"""Sweep magnet layers for one exact free-array candidate and apply hard gates."""

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_freearray_fixedheight as freearray


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-json",
        type=Path,
        default=ROOT
        / "outputs"
        / "magnetic_coupler_gpu_exact_continuation_16in16_20260714"
        / "practical_surrogate_result.json",
    )
    parser.add_argument("--layers", type=int, nargs="+", default=[1, 2, 3, 4, 5, 6])
    parser.add_argument("--seed", type=int, default=20260714)
    parser.add_argument(
        "--skip-dynamic",
        action="store_true",
        help="Run the exact static layer screen only; use its result to select full dynamic layers.",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_bestshape_layer_sweep_20260714",
    )
    return parser.parse_args()


def ready(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if isinstance(value, dict):
        return {key: ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [ready(item) for item in value]
    return value


def main():
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(args.source_json.read_text(encoding="utf-8"))
    source = payload["best_exact_static"]
    base_design = freearray.design_from_dict(source["design"])
    scenarios = [freearray.build_avoid_return_scenario(), freearray.build_straight_lateral_pulse_scenario()]
    records = []
    rows = []

    for layer_count in args.layers:
        if layer_count < 1:
            raise ValueError("Layer counts must be positive.")
        design = replace(base_design, magnet_layers=int(layer_count))
        assembly = freearray.build_assembly(design)
        static = freearray.assess_static_design(assembly)
        outcomes = []
        feasible = 0
        ranking_score = float(static.score)
        if not args.skip_dynamic:
            outcomes = freearray.evaluate_dynamic_suite(
                assembly,
                scenarios=scenarios,
                record_best_history=False,
                seed=args.seed + 100 * layer_count,
                replica_count=1,
            )
            feasible, ranking_score = freearray.candidate_priority(static, outcomes)
        row = {
            "layers": layer_count,
            "stack_height_mm": 13.0 * layer_count,
            "total_magnets": design.total_magnets,
            "static_score": static.score,
            "min_scaled_eig": float(np.min(static.scaled_eigenvalues)),
            "cross_coupling_ratio": static.cross_coupling_ratio,
            "mean_orthogonal_ratio": static.mean_orthogonal_ratio,
            "mean_linearity_r2": static.mean_linearity_r2,
            "negative_restore_count": static.negative_restore_count,
            "negative_yaw_restore_count": static.negative_yaw_restore_count,
            "bad_attraction_count": static.bad_attraction_count,
            "static_contact_count": static.contact_count,
            "aligned_clearance_mm": 1000.0 * static.aligned_clearance_m,
            "nominal_tow_offset_proxy_mm": 1000.0 * static.nominal_tow_offset_proxy_m,
            "dynamic_feasible": int(feasible),
            "dynamic_ranking_score": ranking_score,
            "contact_total": int(sum(outcome.contact_events for outcome in outcomes)) if outcomes else np.nan,
            "max_penetration_mm": float(max(outcome.max_penetration_mm for outcome in outcomes)) if outcomes else np.nan,
            "corridor_breach_total": int(sum(outcome.corridor_breach_count for outcome in outcomes)) if outcomes else np.nan,
            "max_corridor_breach_mm": float(max(outcome.max_corridor_breach_mm for outcome in outcomes)) if outcomes else np.nan,
            "dynamic_clip_total": int(sum(outcome.dynamic_clip_count for outcome in outcomes)) if outcomes else np.nan,
            "worst_clearance_mm": float(min(outcome.min_clearance_mm for outcome in outcomes)) if outcomes else np.nan,
            "hold_force_total": int(sum(outcome.robot_hold_force_exceeded_count for outcome in outcomes)) if outcomes else np.nan,
            "hold_torque_total": int(sum(outcome.robot_hold_torque_exceeded_count for outcome in outcomes)) if outcomes else np.nan,
        }
        rows.append(row)
        records.append(
            {
                "design": freearray.design_to_dict(design),
                "static": freearray.static_assessment_to_dict(static),
                "dynamic": [freearray.outcome_to_dict(outcome) for outcome in outcomes],
                "feasible": int(feasible),
                "ranking_score": float(ranking_score),
            }
        )
        pd.DataFrame(rows).to_csv(args.outdir / "layer_sweep_summary.csv", index=False)
        (args.outdir / "layer_sweep_records.json").write_text(
            json.dumps(ready(records), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    frame = pd.DataFrame(rows)
    best = frame.sort_values(["dynamic_feasible", "dynamic_ranking_score"], ascending=[False, False]).iloc[0]
    lines = [
        "# 最良静的形状の磁石層数スイープ",
        "",
        f"入力候補: `{args.source_json}`",
        "",
        "| layers | height mm | magnets | min eig | tow offset mm | clearance mm | breach | clips | feasible |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in frame.iterrows():
        clearance = "-" if pd.isna(row["worst_clearance_mm"]) else f"{row['worst_clearance_mm']:.3f}"
        breach = "-" if pd.isna(row["corridor_breach_total"]) else str(int(row["corridor_breach_total"]))
        clips = "-" if pd.isna(row["dynamic_clip_total"]) else str(int(row["dynamic_clip_total"]))
        lines.append(
            f"| {int(row['layers'])} | {row['stack_height_mm']:.1f} | {int(row['total_magnets'])} | "
            f"{row['min_scaled_eig']:.6g} | {row['nominal_tow_offset_proxy_mm']:.2f} | "
            f"{clearance} | {breach} | {clips} | {int(row['dynamic_feasible'])} |"
        )
    lines.extend(
        [
            "",
            "## 判定",
            "",
            f"- model hard gate合格数: {int(frame['dynamic_feasible'].sum())}/{len(frame)}",
            f"- 最良順位: {int(best['layers'])}層、score={best['dynamic_ranking_score']:.3f}",
            "- 合格してもFEM・実測前のモデル内成立に限る。",
        ]
    )
    (args.outdir / "layer_sweep_report_ja.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(ready({"pass_count": int(frame["dynamic_feasible"].sum()), "best": best.to_dict()}), indent=2))


if __name__ == "__main__":
    main()
