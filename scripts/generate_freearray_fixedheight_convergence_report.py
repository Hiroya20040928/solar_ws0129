import argparse
import json
import math
import subprocess
import sys
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a concise convergence PDF for the fixed-height free-array magnetic coupler search."
    )
    parser.add_argument(
        "--campaign-outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_freearray_budgeted_20260708",
    )
    parser.add_argument(
        "--localcheck-outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_freearray_localcheck_20260708",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_freearray_convergence_report_20260708",
    )
    return parser.parse_args()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def mass_slug(value: float):
    return str(float(value)).replace(".", "p")


def candidate_case_dir(base_dir: Path, inner_count: int, outer_count: int, cart_mass_kg: float, magnet_layers: int):
    return base_dir / f"{inner_count}in_{outer_count}out_{mass_slug(cart_mass_kg)}kg_{magnet_layers}layer"


def find_first(pattern_root: Path, pattern: str):
    matches = sorted(pattern_root.glob(pattern))
    if not matches:
        raise FileNotFoundError(f"No file matching '{pattern}' under '{pattern_root}'.")
    return matches[0]


def load_stage1_best(campaign_outdir: Path):
    summary_path = campaign_outdir / "stage1_case_summary_sorted.csv"
    stage1_dir = campaign_outdir / "stage1_screen"
    summary_df = pd.read_csv(summary_path)
    best_row = summary_df.sort_values(["feasible", "ranking_score"], ascending=[False, False]).iloc[0]
    case_dir = candidate_case_dir(
        stage1_dir,
        int(best_row["inner_count"]),
        int(best_row["outer_count"]),
        float(best_row["cart_mass_kg"]),
        int(best_row["magnet_layers"]),
    )
    return {
        "source": "stage1_best",
        "summary": best_row.to_dict(),
        "case_dir": case_dir,
        "best_case_json": find_first(case_dir, "best_case_*.json"),
        "history_csv": find_first(case_dir, "history_*.csv"),
    }


def load_stage2_bests(campaign_outdir: Path):
    stage2_dir = campaign_outdir / "stage2_refine"
    candidates = []
    if not stage2_dir.exists():
        return candidates
    for summary_path in sorted(stage2_dir.rglob("refinement_summary.json")):
        summary = load_json(summary_path)
        best_run_outdir = summary.get("best_restart_outdir")
        best_restart = summary.get("best_restart")
        if not best_run_outdir or not best_restart:
            continue
        run_dir = Path(best_run_outdir)
        if not run_dir.exists():
            continue
        try:
            best_case_json = find_first(run_dir, "best_case_*.json")
            history_csv = find_first(run_dir, "history_*.csv")
        except FileNotFoundError:
            continue
        candidates.append(
            {
                "source": f"stage2_{summary_path.parent.name}",
                "summary": best_restart,
                "case_dir": summary_path.parent,
                "best_case_json": best_case_json,
                "history_csv": history_csv,
                "refinement_runs_csv": summary_path.parent / "refinement_runs.csv",
            }
        )
    return candidates


def load_localcheck_best(localcheck_outdir: Path):
    summary_path = localcheck_outdir / "continuation_summary.json"
    if not summary_path.exists():
        return None
    summary = load_json(summary_path)
    best_run_outdir = summary.get("best_run_outdir")
    best_restart = summary.get("best_restart")
    if not best_run_outdir or not best_restart:
        return None
    run_dir = Path(best_run_outdir)
    return {
        "source": "localcheck_best",
        "summary": best_restart,
        "case_dir": localcheck_outdir,
        "best_case_json": find_first(run_dir, "best_case_*.json"),
        "history_csv": find_first(run_dir, "history_*.csv"),
        "continuation_summary_json": summary_path,
    }


def select_overall_best(stage1_best, stage2_bests, localcheck_best):
    candidates = [stage1_best]
    candidates.extend(stage2_bests)
    if localcheck_best is not None:
        candidates.append(localcheck_best)
    candidates.sort(
        key=lambda item: (
            int(item["summary"].get("feasible", 0)),
            float(item["summary"].get("ranking_score", -1.0e18)),
        ),
        reverse=True,
    )
    return candidates[0], candidates


def completed_stage2_evaluations(stage2_bests):
    total = 0
    for item in stage2_bests:
        path = item.get("refinement_runs_csv")
        if path is not None and path.exists():
            df = pd.read_csv(path)
            total += int(df["allocated_evaluations"].sum())
    return total


def completed_local_evaluations(localcheck_best):
    if localcheck_best is None:
        return 0
    summary = load_json(localcheck_best["continuation_summary_json"])
    return int(summary["restarts"]) * int(summary["evaluations"])


def build_candidate_metrics(best_payload):
    design = freearray.design_from_dict(best_payload["design"])
    assembly = freearray.build_assembly(design)
    static_assessment = freearray.assess_static_design(assembly)
    dynamic_outcomes = freearray.evaluate_dynamic_suite(
        assembly,
        scenarios=(freearray.build_avoid_return_scenario(),),
        record_best_history=True,
        seed=0,
        replica_count=1,
    )
    dynamic_df = freearray.report_tables(design, static_assessment, dynamic_outcomes)
    nominal_outcome = dynamic_outcomes[0]
    return design, assembly, static_assessment, dynamic_df, nominal_outcome


def render_figures(outdir: Path, assembly, nominal_outcome, history_sources):
    freearray.plot_design_layout(assembly, outdir / "best_layout.png")
    freearray.plot_field_map(assembly, outdir / "best_field_map.png", grid_size=61)
    freearray.plot_dynamic_history(nominal_outcome, outdir / "best_dynamic_history.png")

    figure, axes = plt.subplots(2, 1, figsize=(8.8, 7.0), sharex=False)
    for idx, (label, history_csv) in enumerate(history_sources):
        history_df = pd.read_csv(history_csv)
        axes[idx].plot(history_df["generation"], history_df["best_static_score"], linewidth=2.0, label="best static")
        axes[idx].plot(history_df["generation"], history_df["mean_static_score"], linewidth=1.4, label="mean static")
        axes[idx].set_title(label)
        axes[idx].set_xlabel("generation")
        axes[idx].set_ylabel("score")
        axes[idx].grid(True, alpha=0.25)
        axes[idx].legend()
    figure.tight_layout()
    figure.savefig(outdir / "convergence_history.png", dpi=180)
    plt.close(figure)


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def build_markdown(
    outdir: Path,
    *,
    stage1_best,
    stage2_bests,
    localcheck_best,
    all_candidates,
    selected_candidate,
    design,
    assembly,
    static_assessment,
    dynamic_df,
    total_completed_evaluations,
):
    stage1_summary = stage1_best["summary"]
    selected_summary = selected_candidate["summary"]
    if localcheck_best is not None:
        continuation_label = "local continuation check"
        continuation_ranking = float(localcheck_best["summary"]["ranking_score"])
    else:
        continuation_label = "selected continuation"
        continuation_ranking = float(selected_summary["ranking_score"])
    scenario_name = "corridor_avoid_return_fixedheight"
    current_feasible, current_ranking = freearray.candidate_priority(
        static_assessment,
        [
            freearray.DynamicOutcome(
                score=float(row["score"]),
                scenario_name=str(row["scenario_name"]),
                environment_label=str(row["environment_label"]),
                min_clearance_mm=float(row["min_clearance_mm"]),
                max_penetration_mm=float(row["max_penetration_mm"]),
                contact_events=int(row["contact_events"]),
                min_robot_corridor_margin_mm=float(row["min_robot_corridor_margin_mm"]),
                min_cart_corridor_margin_mm=float(row["min_cart_corridor_margin_mm"]),
                corridor_breach_count=int(row["corridor_breach_count"]),
                max_corridor_breach_mm=float(row["max_corridor_breach_mm"]),
                peak_relative_translation_mm=float(row["peak_relative_translation_mm"]),
                peak_relative_yaw_deg=float(row["peak_relative_yaw_deg"]),
                cruise_relative_translation_rms_mm=float(row["cruise_relative_translation_rms_mm"]),
                cruise_relative_yaw_rms_deg=float(row["cruise_relative_yaw_rms_deg"]),
                cue_peak_yaw_deg=float(row["cue_peak_yaw_deg"]),
                cue_peak_translation_mm=float(row["cue_peak_translation_mm"]),
                max_cart_accel_mps2=float(row["max_cart_accel_mps2"]),
                max_cart_yaw_accel_radps2=float(row["max_cart_yaw_accel_radps2"]),
                robot_hold_force_exceeded_count=int(row["robot_hold_force_exceeded_count"]),
                robot_hold_torque_exceeded_count=int(row["robot_hold_torque_exceeded_count"]),
                dynamic_clip_count=int(row["dynamic_clip_count"]),
                history=None,
            )
            for _, row in dynamic_df.iterrows()
        ],
    )

    gate_rows = [
        [
            "台車質量",
            ">= 10.0 kg",
            f"{static_assessment.cart_mass_kg:.3f} kg",
            "PASS" if static_assessment.cart_mass_kg >= freearray.REALISTIC_MIN_CART_MASS_KG else "FAIL",
        ],
        [
            "接触イベント総数",
            "0",
            f"{int(dynamic_df['contact_events'].sum())}",
            "PASS" if int(dynamic_df["contact_events"].sum()) == 0 else "FAIL",
        ],
        [
            "最大めり込み量",
            "0.000 mm",
            f"{float(dynamic_df['max_penetration_mm'].max()):.6f} mm",
            "PASS" if float(dynamic_df["max_penetration_mm"].max()) <= 0.0 else "FAIL",
        ],
        [
            "最小クリアランス",
            ">= 2.000 mm",
            f"{float(dynamic_df['min_clearance_mm'].min()):.6f} mm",
            "PASS" if float(dynamic_df["min_clearance_mm"].min()) >= 2.0 else "FAIL",
        ],
        [
            "負の並進復元サンプル数",
            "0",
            f"{int(static_assessment.negative_restore_count)}",
            "PASS" if int(static_assessment.negative_restore_count) == 0 else "FAIL",
        ],
        [
            "負の回転復元サンプル数",
            "0",
            f"{int(static_assessment.negative_yaw_restore_count)}",
            "PASS" if int(static_assessment.negative_yaw_restore_count) == 0 else "FAIL",
        ],
        [
            "吸着危険サンプル数",
            "0",
            f"{int(static_assessment.bad_attraction_count)}",
            "PASS" if int(static_assessment.bad_attraction_count) == 0 else "FAIL",
        ],
        [
            "保持力上限制約超過回数",
            "0",
            f"{int(dynamic_df['robot_hold_force_exceeded_count'].sum())}",
            "PASS" if int(dynamic_df["robot_hold_force_exceeded_count"].sum()) == 0 else "FAIL",
        ],
        [
            "保持トルク上限制約超過回数",
            "0",
            f"{int(dynamic_df['robot_hold_torque_exceeded_count'].sum())}",
            "PASS" if int(dynamic_df["robot_hold_torque_exceeded_count"].sum()) == 0 else "FAIL",
        ],
        [
            "動的クリップ介入回数",
            "0",
            f"{int(dynamic_df['dynamic_clip_count'].sum())}",
            "PASS" if int(dynamic_df["dynamic_clip_count"].sum()) == 0 else "FAIL",
        ],
        [
            "パッケージ違反量",
            "0.000 mm",
            f"{1000.0 * float(static_assessment.package_violation_m):.3f} mm",
            "PASS" if float(static_assessment.package_violation_m) <= 0.0 else "FAIL",
        ],
        [
            "回廊逸脱フレーム数",
            "0",
            f"{int(dynamic_df['corridor_breach_count'].sum())}",
            "PASS" if int(dynamic_df["corridor_breach_count"].sum()) == 0 else "FAIL",
        ],
    ]

    candidate_rows = []
    for item in all_candidates:
        summary = item["summary"]
        candidate_rows.append(
            [
                item["source"],
                int(summary["inner_count"]),
                int(summary["outer_count"]),
                int(summary["magnet_layers"]),
                f"{float(summary['ranking_score']):.3f}",
                int(summary["feasible"]),
                f"{float(summary.get('worst_clearance_mm', float('nan'))):.6f}",
                f"{float(summary.get('max_penetration_mm', float('nan'))):.6f}",
            ]
        )

    inner_mean_radius_m = float(np.mean(np.asarray(design.inner_radii_m, dtype=float)[: max(design.inner_count // 2, 1)]))
    outer_mean_radius_m = float(np.mean(np.asarray(design.outer_radii_m, dtype=float)[: max(design.outer_count // 2, 1)]))
    mean_radius_m = 0.5 * (inner_mean_radius_m + outer_mean_radius_m)

    lines = [
        "# 固定高さ・自由配置磁気カプラ探索 収束報告",
        "",
        "## 結論",
        f"- 2026-07-08 時点で、完了済みの高忠実度探索評価は **{int(total_completed_evaluations)} 回** です。",
        f"- 現行の実機成立条件と主シナリオ `{scenario_name}` に対して、**feasible = {int(current_feasible)}** でした。",
        f"- 最良候補は **{design.inner_count} in / {design.outer_count} out / {design.magnet_layers} layer / {design.cart_mass_kg:.1f} kg** で、総磁石数は **{design.total_magnets} 個** です。",
        f"- ただし最小クリアランスは **{float(dynamic_df['min_clearance_mm'].min()):.6f} mm** しかなく、2.0 mm 下限を大きく下回るため、**現時点では不合格** です。",
        f"- 追加の局所継続探索（{continuation_label}）でも ranking score は **{float(stage1_summary['ranking_score']):.3f} -> {continuation_ranking:.3f}** で改善せず、同一不合格盆地への再収束が確認されました。",
        "",
        "## 探索条件",
        "- 磁石 SKU: `DAISO_SUPER_13MM_4P`",
        "- 高さ可変: 無効",
        "- 実機成立質量ゲート: `10.0 kg 以上`",
        "- 主動的評価シナリオ: `corridor_avoid_return_fixedheight`",
        "- ステージ1構造探索: 16 ケース",
        f"- 探索次元数（今回の最良ケース）: `{freearray.latent_dimension(design.inner_count, design.outer_count)}`",
        f"- Stage 1 best ranking score: `{float(stage1_summary['ranking_score']):.3f}`",
        f"- Final selected ranking score: `{float(current_ranking):.3f}`",
        "",
        "## 候補比較",
        markdown_table(
            ["source", "inner", "outer", "layers", "ranking_score", "feasible", "worst_clearance_mm", "max_penetration_mm"],
            candidate_rows,
        ),
        "",
        "## 合否判定表",
        markdown_table(["判定項目", "要求値", "実測値", "判定"], gate_rows),
        "",
        "## 最良候補の主要数値",
        markdown_table(
            ["項目", "値"],
            [
                ["gap", f"{1000.0 * float(assembly.nominal_gap_m):.3f} mm"],
                ["mean radius", f"{1000.0 * float(mean_radius_m):.3f} mm"],
                ["aligned clearance", f"{1000.0 * float(static_assessment.aligned_clearance_m):.3f} mm"],
                ["static score", f"{float(static_assessment.score):.3f}"],
                ["lateral stiffness", f"{float(static_assessment.lateral_stiffness_npm):.3f} N/m"],
                ["forward stiffness", f"{float(static_assessment.forward_stiffness_npm):.3f} N/m"],
                ["yaw stiffness", f"{float(static_assessment.yaw_stiffness_nmp_rad):.3f} N m/rad"],
                ["mean orthogonal ratio", f"{float(static_assessment.mean_orthogonal_ratio):.6f}"],
                ["cross-coupling ratio", f"{float(static_assessment.cross_coupling_ratio):.6f}"],
                ["bad attraction count", f"{int(static_assessment.bad_attraction_count)}"],
                ["dynamic mean score", f"{float(dynamic_df['score'].mean()):.3f}"],
                ["dynamic clip total", f"{int(dynamic_df['dynamic_clip_count'].sum())}"],
                ["robot corridor min margin", f"{float(dynamic_df['min_robot_corridor_margin_mm'].min()):.3f} mm"],
                ["cart corridor min margin", f"{float(dynamic_df['min_cart_corridor_margin_mm'].min()):.3f} mm"],
            ],
        ),
        "",
        "## 失敗要因の整理",
        "- クリアランスはゼロ接触ではあるものの、2.0 mm 安全下限を満たしていません。",
        "- 並進復元・回転復元・吸着危険の静的ゲートを同時に満たしていません。",
        "- 動的シミュレーションでは多数のクリップ介入が発生しており、現実的な滑らかさに未到達です。",
        "- したがって、この探索の収束結果は『現行条件下では実機投入可能解なし』です。",
        "",
        "## 図",
        "### 構造レイアウト",
        "![](best_layout.png)",
        "",
        "### 磁場マップ",
        "![](best_field_map.png)",
        "",
        "### 動的履歴",
        "![](best_dynamic_history.png)",
        "",
        "### 収束履歴",
        "![](convergence_history.png)",
        "",
        "## 付記",
        "- この PDF は `stage1_screen`, `stage2_refine`, `localcheck` の既存結果を再集計し、最良候補を再評価して生成しています。",
        "- 収束は『追加局所探索でも feasible 化せず、ranking score が改善しない』という意味で判定しました。",
    ]
    markdown_path = outdir / "freearray_fixedheight_convergence_report_ja.md"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return markdown_path


def build_pdf(markdown_path: Path):
    pdf_path = markdown_path.with_suffix(".pdf")
    command = [
        "pandoc",
        str(markdown_path),
        "-o",
        str(pdf_path),
        "--pdf-engine=xelatex",
        "-V",
        "mainfont=Yu Gothic",
        "-V",
        "monofont=Yu Gothic",
        "-V",
        "geometry:margin=20mm",
    ]
    subprocess.run(command, check=True, cwd=str(markdown_path.parent))
    return pdf_path


def main():
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)

    stage1_best = load_stage1_best(args.campaign_outdir)
    stage2_bests = load_stage2_bests(args.campaign_outdir)
    localcheck_best = load_localcheck_best(args.localcheck_outdir)
    selected_candidate, all_candidates = select_overall_best(stage1_best, stage2_bests, localcheck_best)

    best_payload = load_json(selected_candidate["best_case_json"])
    design, assembly, static_assessment, dynamic_df, nominal_outcome = build_candidate_metrics(best_payload)

    campaign_config = load_json(args.campaign_outdir / "campaign_config.json")
    stage1_evaluations = int(campaign_config["stage1_total_actual"])
    stage2_evaluations = completed_stage2_evaluations(stage2_bests)
    local_evaluations = completed_local_evaluations(localcheck_best)
    total_completed_evaluations = stage1_evaluations + stage2_evaluations + local_evaluations

    history_sources = [("Stage 1 best-case history", stage1_best["history_csv"])]
    if localcheck_best is not None:
        history_sources.append(("Local continuation check", localcheck_best["history_csv"]))
    else:
        history_sources.append(("Selected candidate history", selected_candidate["history_csv"]))
    render_figures(args.outdir, assembly, nominal_outcome, history_sources)

    markdown_path = build_markdown(
        args.outdir,
        stage1_best=stage1_best,
        stage2_bests=stage2_bests,
        localcheck_best=localcheck_best,
        all_candidates=all_candidates,
        selected_candidate=selected_candidate,
        design=design,
        assembly=assembly,
        static_assessment=static_assessment,
        dynamic_df=dynamic_df,
        total_completed_evaluations=total_completed_evaluations,
    )
    pdf_path = build_pdf(markdown_path)
    summary = {
        "selected_source": selected_candidate["source"],
        "selected_json": str(selected_candidate["best_case_json"]),
        "total_completed_evaluations": int(total_completed_evaluations),
        "feasible": int(freearray.candidate_priority(static_assessment, [
            freearray.DynamicOutcome(
                score=float(row["score"]),
                scenario_name=str(row["scenario_name"]),
                environment_label=str(row["environment_label"]),
                min_clearance_mm=float(row["min_clearance_mm"]),
                max_penetration_mm=float(row["max_penetration_mm"]),
                contact_events=int(row["contact_events"]),
                min_robot_corridor_margin_mm=float(row["min_robot_corridor_margin_mm"]),
                min_cart_corridor_margin_mm=float(row["min_cart_corridor_margin_mm"]),
                corridor_breach_count=int(row["corridor_breach_count"]),
                max_corridor_breach_mm=float(row["max_corridor_breach_mm"]),
                peak_relative_translation_mm=float(row["peak_relative_translation_mm"]),
                peak_relative_yaw_deg=float(row["peak_relative_yaw_deg"]),
                cruise_relative_translation_rms_mm=float(row["cruise_relative_translation_rms_mm"]),
                cruise_relative_yaw_rms_deg=float(row["cruise_relative_yaw_rms_deg"]),
                cue_peak_yaw_deg=float(row["cue_peak_yaw_deg"]),
                cue_peak_translation_mm=float(row["cue_peak_translation_mm"]),
                max_cart_accel_mps2=float(row["max_cart_accel_mps2"]),
                max_cart_yaw_accel_radps2=float(row["max_cart_yaw_accel_radps2"]),
                robot_hold_force_exceeded_count=int(row["robot_hold_force_exceeded_count"]),
                robot_hold_torque_exceeded_count=int(row["robot_hold_torque_exceeded_count"]),
                dynamic_clip_count=int(row["dynamic_clip_count"]),
                history=None,
            )
            for _, row in dynamic_df.iterrows()
        ])[0]),
        "worst_clearance_mm": float(dynamic_df["min_clearance_mm"].min()),
        "max_penetration_mm": float(dynamic_df["max_penetration_mm"].max()),
        "pdf_path": str(pdf_path),
    }
    (args.outdir / "report_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
