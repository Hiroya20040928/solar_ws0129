"""Re-evaluate GPU dipole-screen candidates with Magpylib and dynamic hard gates."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import asdict
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_freearray_fixedheight as freearray


EXPANDED_BOUNDS = {
    "INNER_BASE_RADIUS_RANGE_M": (0.048, 0.090),
    "BASE_GAP_RANGE_M": (0.004, 0.040),
    "INNER_RADIUS_DEVIATION_M": 0.018,
    "OUTER_RADIUS_DEVIATION_M": 0.020,
    "INNER_ANGLE_JITTER_RAD": math.radians(22.0),
    "OUTER_ANGLE_JITTER_RAD": math.radians(22.0),
}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gpu-candidates",
        type=Path,
        default=ROOT
        / "outputs"
        / "magnetic_coupler_gpu_screen_100k_20260714"
        / "gpu_top_candidates.json",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_gpu_exact_reevaluation_20260714",
    )
    parser.add_argument("--top-per-config", type=int, default=2)
    parser.add_argument("--full-linear-top-k", type=int, default=4)
    parser.add_argument("--dynamic-top-k", type=int, default=3)
    parser.add_argument("--cart-mass-kg", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=20260714)
    return parser.parse_args()


def json_ready(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def apply_expanded_bounds():
    for name, value in EXPANDED_BOUNDS.items():
        setattr(freearray, name, value)


def select_candidates(rows, top_per_config):
    selected = []
    groups = {}
    for row in rows:
        groups.setdefault(row["config"], []).append(row)
    for label, group in sorted(groups.items()):
        ranked = sorted(
            group,
            key=lambda row: (int(row["surrogate_feasible"]), float(row["score"])),
            reverse=True,
        )
        selected.extend(ranked[:top_per_config])
    return selected


def static_priority(record):
    static = record["static"]
    return (
        int(static["package_violation_m"] > 0.0),
        int(static["contact_count"]),
        int(static["bad_attraction_count"]),
        int(static["negative_restore_count"]),
        int(static["negative_yaw_restore_count"]),
        max(0.0, -min(static["scaled_eigenvalues"])),
        max(0.0, 0.003 - static["aligned_clearance_m"]),
        -static["score"],
    )


def summarize_static(candidate, index, args):
    latent = np.asarray(candidate["latent_vector"], dtype=float)
    design = freearray.build_design_from_latent(
        latent,
        int(candidate["inner_count"]),
        int(candidate["outer_count"]),
        args.cart_mass_kg,
        int(candidate["layers"]),
    )
    assembly = freearray.build_assembly(design)
    assessment = freearray.assess_static_design(
        assembly,
        directions_rad=np.linspace(0.0, 2.0 * math.pi, 8, endpoint=False),
        displacements_m=np.array([0.002, 0.004, 0.006], dtype=float),
        yaw_samples_rad=np.radians(np.array([2.0, 4.0, 8.0, 12.0, 18.0], dtype=float)),
    )
    return {
        "candidate_index": index,
        "config": candidate["config"],
        "latent_vector": latent.tolist(),
        "gpu_surrogate": {key: value for key, value in candidate.items() if key != "latent_vector"},
        "design": json_ready(asdict(design)),
        "static": json_ready(asdict(assessment)),
        "assembly": {
            "nominal_gap_m": float(assembly.nominal_gap_m),
            "pitch_descriptor": assembly.pitch_descriptor,
        },
        "elapsed_s": None,
    }, assembly


def dynamic_summary(outcomes):
    return {
        "outcomes": [json_ready(asdict(outcome)) for outcome in outcomes],
        "contact_total": int(sum(outcome.contact_events for outcome in outcomes)),
        "penetration_max_mm": float(max(outcome.max_penetration_mm for outcome in outcomes)),
        "corridor_breach_total": int(sum(outcome.corridor_breach_count for outcome in outcomes)),
        "corridor_breach_max_mm": float(max(outcome.max_corridor_breach_mm for outcome in outcomes)),
        "dynamic_clip_total": int(sum(outcome.dynamic_clip_count for outcome in outcomes)),
        "worst_clearance_mm": float(min(outcome.min_clearance_mm for outcome in outcomes)),
        "hold_force_total": int(sum(outcome.robot_hold_force_exceeded_count for outcome in outcomes)),
        "hold_torque_total": int(sum(outcome.robot_hold_torque_exceeded_count for outcome in outcomes)),
    }


def write_status(outdir, payload):
    (outdir / "exact_reevaluation_status.json").write_text(
        json.dumps(json_ready(payload), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def flatten_records(records):
    rows = []
    for record in records:
        static = record["static"]
        linear = record.get("linear") or {}
        dynamic = record.get("dynamic") or {}
        rows.append(
            {
                "candidate_index": record["candidate_index"],
                "config": record["config"],
                "gpu_score": record["gpu_surrogate"]["score"],
                "gpu_feasible": int(record["gpu_surrogate"]["surrogate_feasible"]),
                "exact_score": static["score"],
                "exact_min_scaled_eig": min(static["scaled_eigenvalues"]),
                "exact_mean_linearity_r2": static["mean_linearity_r2"],
                "exact_mean_orthogonal_ratio": static["mean_orthogonal_ratio"],
                "exact_negative_restore": static["negative_restore_count"],
                "exact_negative_yaw_restore": static["negative_yaw_restore_count"],
                "exact_bad_attraction": static["bad_attraction_count"],
                "exact_contact": static["contact_count"],
                "exact_clearance_mm": 1000.0 * static["aligned_clearance_m"],
                "exact_package_violation_mm": 1000.0 * static["package_violation_m"],
                "linear_min_eig": min(linear["scaled_symmetric_eigenvalues"]) if linear else math.nan,
                "linear_mean_r2": linear.get("mean_linearity_r2", math.nan),
                "linear_mean_leakage": linear.get("mean_leakage_ratio", math.nan),
                "dynamic_feasible": record.get("dynamic_feasible", math.nan),
                "dynamic_contact_total": dynamic.get("contact_total", math.nan),
                "dynamic_corridor_breach_total": dynamic.get("corridor_breach_total", math.nan),
                "dynamic_clip_total": dynamic.get("dynamic_clip_total", math.nan),
                "dynamic_worst_clearance_mm": dynamic.get("worst_clearance_mm", math.nan),
                "elapsed_s": record["elapsed_s"],
            }
        )
    return pd.DataFrame(rows)


def plot_results(frame, outdir):
    figure, axes = plt.subplots(1, 2, figsize=(11.8, 4.8))
    colors = np.where(frame["exact_min_scaled_eig"] > 0.0, "#0f766e", "#dc2626")
    axes[0].scatter(frame["gpu_score"], frame["exact_min_scaled_eig"], c=colors, alpha=0.85)
    axes[0].axhline(0.0, color="#111827", linestyle="--", linewidth=1.0)
    axes[0].set_xlabel("GPU point-dipole surrogate score")
    axes[0].set_ylabel("Magpylib minimum scaled eigenvalue")
    axes[0].set_title("Surrogate-to-exact transfer")
    axes[1].bar(frame["config"], frame["exact_clearance_mm"], color="#1d4ed8")
    axes[1].axhline(3.0, color="#b91c1c", linestyle="--", linewidth=1.0)
    axes[1].tick_params(axis="x", rotation=55)
    axes[1].set_ylabel("Aligned clearance [mm]")
    axes[1].set_title("Exact geometric clearance")
    for axis in axes:
        axis.grid(True, alpha=0.22)
    figure.tight_layout()
    figure.savefig(outdir / "gpu_to_exact_evidence.png", dpi=180)
    plt.close(figure)


def write_report(records, frame, args):
    exact_spd = int((frame["exact_min_scaled_eig"] > 0.0).sum())
    static_safe = int(
        (
            (frame["exact_min_scaled_eig"] > 0.0)
            & (frame["exact_negative_restore"] == 0)
            & (frame["exact_negative_yaw_restore"] == 0)
            & (frame["exact_contact"] == 0)
            & (frame["exact_package_violation_mm"] <= 0.0)
        ).sum()
    )
    dynamic_rows = frame[frame["dynamic_feasible"].notna()]
    dynamic_pass = int(dynamic_rows["dynamic_feasible"].sum()) if len(dynamic_rows) else 0
    lines = [
        "# GPU候補のMagpylib・動的hard gate再評価",
        "",
        "## 判定",
        "",
        f"- GPU近似上位からMagpylib再評価した候補: {len(frame)}件",
        f"- Magpylib最小剛性固有値が正: {exact_spd}件",
        f"- 正固有値・全静的復元・非接触・取付領域を同時充足: {static_safe}件",
        f"- 動的hard gate評価: {len(dynamic_rows)}件、合格: {dynamic_pass}件",
        "",
        "GPU点双極子は候補生成器であり、近接円盤磁石の最終物理証拠ではない。"
        "本表のMagpylib結果もFEM・実測前の数値仮説である。",
        "",
        "## 候補表",
        "",
        "| config | GPU score | exact min eig | R2 | leakage | clearance mm | static failures | dynamic pass |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row in frame.sort_values("exact_min_scaled_eig", ascending=False).iterrows():
        static_failures = int(row["exact_negative_restore"] + row["exact_negative_yaw_restore"] + row["exact_contact"])
        dynamic_value = "-" if pd.isna(row["dynamic_feasible"]) else str(int(row["dynamic_feasible"]))
        lines.append(
            f"| {row['config']} | {row['gpu_score']:.3g} | {row['exact_min_scaled_eig']:.6g} | "
            f"{row['exact_mean_linearity_r2']:.3f} | {row['exact_mean_orthogonal_ratio']:.3f} | "
            f"{row['exact_clearance_mm']:.3f} | {static_failures} | {dynamic_value} |"
        )
    lines.extend(
        [
            "",
            "## 再現条件",
            "",
            f"- 台車質量: {args.cart_mass_kg:g} kg",
            f"- GPU候補ファイル: `{args.gpu_candidates}`",
            f"- 各配置からの厳密再評価数: {args.top_per_config}",
            "- 展開設計範囲は `exact_reevaluation_metadata.json` に数値保存した。",
        ]
    )
    (args.outdir / "gpu_exact_reevaluation_report_ja.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    apply_expanded_bounds()
    rows = json.loads(args.gpu_candidates.read_text(encoding="utf-8"))
    selected = select_candidates(rows, args.top_per_config)
    metadata = {
        "source": str(args.gpu_candidates),
        "selected_count": len(selected),
        "expanded_bounds": EXPANDED_BOUNDS,
        "cart_mass_kg": args.cart_mass_kg,
        "model_chain": ["GPU point dipole", "Magpylib cylinder", "fixed-height dynamic hard gate"],
        "not_yet_completed": ["FEM", "bench force map", "hardware corridor test"],
    }
    (args.outdir / "exact_reevaluation_metadata.json").write_text(
        json.dumps(json_ready(metadata), indent=2, ensure_ascii=False), encoding="utf-8"
    )

    records = []
    assemblies = {}
    for index, candidate in enumerate(selected):
        started = time.time()
        record, assembly = summarize_static(candidate, index, args)
        record["elapsed_s"] = time.time() - started
        records.append(record)
        assemblies[index] = assembly
        write_status(
            args.outdir,
            {"phase": "static", "completed": len(records), "total": len(selected), "latest": record},
        )
        (args.outdir / "exact_reevaluation_records.json").write_text(
            json.dumps(json_ready(records), indent=2, ensure_ascii=False), encoding="utf-8"
        )

    ranked = sorted(records, key=static_priority)
    for record in ranked[: args.full_linear_top_k]:
        linear = freearray.assess_linear_restore_objective(assemblies[record["candidate_index"]])
        record["linear"] = json_ready(asdict(linear))
        write_status(args.outdir, {"phase": "linear", "candidate_index": record["candidate_index"]})

    for record in ranked[: args.dynamic_top_k]:
        assembly = assemblies[record["candidate_index"]]
        outcomes = freearray.evaluate_dynamic_suite(
            assembly,
            scenarios=[freearray.build_avoid_return_scenario(), freearray.build_straight_lateral_pulse_scenario()],
            record_best_history=False,
            seed=args.seed + record["candidate_index"],
            replica_count=1,
        )
        feasible, ranking_score = freearray.candidate_priority(
            freearray.StaticAssessment(**{
                key: np.asarray(value, dtype=float) if key in {"stiffness_matrix_raw", "stiffness_matrix_scaled", "scaled_eigenvalues"} else value
                for key, value in record["static"].items()
            }),
            outcomes,
        )
        record["dynamic"] = dynamic_summary(outcomes)
        record["dynamic_feasible"] = int(feasible)
        record["dynamic_ranking_score"] = float(ranking_score)
        write_status(args.outdir, {"phase": "dynamic", "candidate_index": record["candidate_index"]})

    (args.outdir / "exact_reevaluation_records.json").write_text(
        json.dumps(json_ready(records), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    frame = flatten_records(records)
    frame.to_csv(args.outdir / "exact_reevaluation_summary.csv", index=False)
    plot_results(frame, args.outdir)
    write_report(records, frame, args)
    summary = {
        "selected_count": len(frame),
        "exact_positive_spd_count": int((frame["exact_min_scaled_eig"] > 0.0).sum()),
        "dynamic_evaluated_count": int(frame["dynamic_feasible"].notna().sum()),
        "dynamic_feasible_count": int(frame["dynamic_feasible"].fillna(0).sum()),
        "best_exact_min_scaled_eig": float(frame["exact_min_scaled_eig"].max()),
    }
    (args.outdir / "exact_reevaluation_result.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_status(args.outdir, {"phase": "complete", **summary})
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
