import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
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

try:
    import cma
except Exception:
    cma = None


@dataclass
class StructuredCaseResult:
    case_label: str
    inner_count: int
    outer_count: int
    cart_mass_kg: float
    magnet_layers: int
    latent_dimension: int
    search_score: float
    static_score: float
    ranking_score: float
    feasible: int
    worst_clearance_mm: float
    max_penetration_mm: float
    dynamic_clip_total: int
    corridor_breach_total: int
    robot_hold_force_exceeded_total: int
    robot_hold_torque_exceeded_total: int
    negative_restore_count: int
    negative_yaw_restore_count: int
    bad_attraction_count: int
    mean_orthogonal_ratio: float
    cross_coupling_ratio: float
    aligned_clearance_mm: float
    source_json: str


def parse_args():
    parser = argparse.ArgumentParser(
        description="Literature-informed structured redesign search for the fixed-height magnetic coupler."
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_structured_root_redesign_20260709",
    )
    parser.add_argument("--seed", type=int, default=20260709)
    parser.add_argument("--population", type=int, default=10)
    parser.add_argument("--evaluations", type=int, default=120)
    parser.add_argument("--replica-count", type=int, default=1)
    parser.add_argument(
        "--dynamic-candidate-limit",
        type=int,
        default=1,
        help="How many top static candidates receive expensive dynamic validation.",
    )
    parser.add_argument(
        "--dynamic-profile",
        type=str,
        choices=("both", "corridor_only", "pulse_only"),
        default="both",
        help="Dynamic validation scenario set used after the static search.",
    )
    parser.add_argument(
        "--cases",
        nargs="*",
        default=["20x24x1", "16x20x2"],
        help="Format: INNERxOUTERxLAYERS, e.g. 20x24x1",
    )
    parser.add_argument("--cart-mass-kg", type=float, default=10.0)
    return parser.parse_args()


def parse_case(text):
    inner_text, outer_text, layers_text = text.lower().split("x")
    return int(inner_text), int(outer_text), int(layers_text)


def bounded_logit(value):
    clipped = float(np.clip(value, 1.0e-6, 1.0 - 1.0e-6))
    return math.log(clipped / (1.0 - clipped))


def harmonic_angle_offsets(half_count, raw_values, max_offset_rad):
    phase = 2.0 * math.pi * (np.arange(half_count, dtype=float) + 0.5) / max(half_count, 1)
    offset = (
        raw_values[0] * np.sin(phase)
        + raw_values[1] * np.cos(phase)
        + raw_values[2] * np.sin(2.0 * phase)
        + raw_values[3] * np.cos(2.0 * phase)
    )
    offset = np.clip(offset, -1.0, 1.0)
    return max_offset_rad * offset


def harmonic_radius_profile(half_count, raw_values, amplitude_m):
    phase = 2.0 * math.pi * (np.arange(half_count, dtype=float) + 0.5) / max(half_count, 1)
    profile = (
        raw_values[0] * np.sin(phase)
        + raw_values[1] * np.cos(phase)
        + raw_values[2] * np.sin(2.0 * phase)
        + raw_values[3] * np.cos(2.0 * phase)
    )
    return amplitude_m * np.clip(profile, -1.0, 1.0)


def harmonic_tilt_profile(half_count, raw_values, max_tilt_rad):
    phase = 2.0 * math.pi * (np.arange(half_count, dtype=float) + 0.5) / max(half_count, 1)
    offset = raw_values[0]
    shaped = (
        offset
        + raw_values[1] * np.sin(phase)
        + raw_values[2] * np.cos(phase)
        + raw_values[3] * np.sin(2.0 * phase)
        + raw_values[4] * np.cos(2.0 * phase)
    )
    return max_tilt_rad * np.clip(shaped, -1.0, 1.0)


def structured_latent_dimension():
    return 30


def select_dynamic_scenarios(profile: str):
    if profile == "corridor_only":
        return (freearray.build_avoid_return_scenario(),)
    if profile == "pulse_only":
        return (freearray.build_straight_lateral_pulse_scenario(),)
    return (freearray.build_avoid_return_scenario(), freearray.build_straight_lateral_pulse_scenario())


def build_structured_design_from_latent(latent_vector, inner_count, outer_count, cart_mass_kg, magnet_layers):
    if inner_count % 2 or outer_count % 2:
        raise ValueError("Structured search expects even inner and outer counts.")
    bounded = freearray.base.sigmoid(np.asarray(latent_vector, dtype=float))
    signed = 2.0 * bounded - 1.0
    index = 0

    inner_phase_rad = math.radians(8.0) * signed[index]
    index += 1
    outer_phase_rad = math.radians(8.0) * signed[index]
    index += 1
    inner_base_radius_m = freearray.INNER_BASE_RADIUS_RANGE_M[0] + (
        freearray.INNER_BASE_RADIUS_RANGE_M[1] - freearray.INNER_BASE_RADIUS_RANGE_M[0]
    ) * bounded[index]
    index += 1
    base_gap_m = 0.009 + (0.020 - 0.009) * bounded[index]
    index += 1

    inner_angle_raw = signed[index : index + 4]
    index += 4
    outer_angle_raw = signed[index : index + 4]
    index += 4
    inner_radius_raw = signed[index : index + 4]
    index += 4
    outer_radius_raw = signed[index : index + 4]
    index += 4
    inner_tilt_raw = signed[index : index + 5]
    index += 5
    outer_tilt_raw = signed[index : index + 5]

    inner_half = inner_count // 2
    outer_half = outer_count // 2
    inner_anchor = freearray.equispaced_half_angles(inner_half)
    outer_anchor = freearray.equispaced_half_angles(outer_half)
    inner_slot_pitch = math.pi / max(inner_half, 1)
    outer_slot_pitch = math.pi / max(outer_half, 1)

    inner_half_angles = inner_anchor + harmonic_angle_offsets(inner_half, inner_angle_raw, 0.10 * inner_slot_pitch)
    outer_half_angles = outer_anchor + harmonic_angle_offsets(outer_half, outer_angle_raw, 0.10 * outer_slot_pitch)
    inner_half_angles = np.sort(np.mod(inner_half_angles, math.pi))
    outer_half_angles = np.sort(np.mod(outer_half_angles, math.pi))

    inner_half_radii_m = inner_base_radius_m + harmonic_radius_profile(inner_half, inner_radius_raw, 0.0018)
    inner_half_radii_m = np.clip(
        inner_half_radii_m,
        freearray.INNER_BASE_RADIUS_RANGE_M[0],
        freearray.INNER_BASE_RADIUS_RANGE_M[1],
    )
    outer_base_radius_m = inner_base_radius_m + base_gap_m
    outer_half_radii_m = outer_base_radius_m + harmonic_radius_profile(outer_half, outer_radius_raw, 0.0015)
    outer_half_radii_m = np.maximum(outer_half_radii_m, inner_half_radii_m.mean() + 0.92 * base_gap_m)

    inner_half_tilt_rad = harmonic_tilt_profile(inner_half, inner_tilt_raw, math.radians(18.0))
    outer_half_tilt_rad = harmonic_tilt_profile(outer_half, outer_tilt_raw, math.radians(18.0))

    inner_angles_rad, inner_radii_m, inner_tilt_rad = freearray.mirrored_ring_parameters(
        inner_half_angles,
        inner_half_radii_m,
        inner_half_tilt_rad,
        phase_rad=inner_phase_rad,
    )
    outer_angles_rad, outer_radii_m, outer_tilt_rad = freearray.mirrored_ring_parameters(
        outer_half_angles,
        outer_half_radii_m,
        outer_half_tilt_rad,
        phase_rad=outer_phase_rad,
    )

    sku = freearray.base.MAGNET_CATALOG_BY_ID[freearray.FIXED_SKU_ID]
    return freearray.FreeArrayDesign(
        magnet_sku_id=sku.sku_id,
        cart_mass_kg=float(cart_mass_kg),
        magnet_layers=int(magnet_layers),
        inner_angles_rad=inner_angles_rad,
        inner_radii_m=inner_radii_m,
        inner_tilt_rad=inner_tilt_rad,
        outer_angles_rad=outer_angles_rad,
        outer_radii_m=outer_radii_m,
        outer_tilt_rad=outer_tilt_rad,
        effective_flux_t=float(freearray.hifi.effective_flux_density_t(sku)),
    )


def structured_shape_regularization(design):
    inner_r = np.asarray(design.inner_radii_m[: design.inner_count // 2], dtype=float)
    outer_r = np.asarray(design.outer_radii_m[: design.outer_count // 2], dtype=float)
    inner_t = np.asarray(design.inner_tilt_rad[: design.inner_count // 2], dtype=float)
    outer_t = np.asarray(design.outer_tilt_rad[: design.outer_count // 2], dtype=float)
    inner_a = np.asarray(design.inner_angles_rad[: design.inner_count // 2], dtype=float)
    outer_a = np.asarray(design.outer_angles_rad[: design.outer_count // 2], dtype=float)
    inner_gaps = np.diff(np.concatenate((inner_a, inner_a[:1] + math.pi)))
    outer_gaps = np.diff(np.concatenate((outer_a, outer_a[:1] + math.pi)))
    return float(
        1000.0 * np.std(inner_r)
        + 1000.0 * np.std(outer_r)
        + 0.6 * np.degrees(np.std(inner_t))
        + 0.6 * np.degrees(np.std(outer_t))
        + 0.35 * np.degrees(np.mean(np.abs(inner_t)))
        + 0.35 * np.degrees(np.mean(np.abs(outer_t)))
        + 180.0 * np.std(inner_gaps) / math.pi
        + 180.0 * np.std(outer_gaps) / math.pi
    )


def literature_informed_search_score(design, assessment):
    min_eig = float(np.min(np.asarray(assessment.scaled_eigenvalues, dtype=float)))
    aligned_gap_mm = 1000.0 * float(assessment.aligned_clearance_m)
    regularity_penalty = structured_shape_regularization(design)
    score = 0.0
    score += 1800.0 * min(min_eig, 0.08)
    score += 0.16 * max(assessment.forward_stiffness_npm, 0.0)
    score += 0.12 * max(assessment.lateral_stiffness_npm, 0.0)
    score += 0.30 * max(assessment.yaw_stiffness_nmp_rad, 0.0)
    score -= 1400.0 * assessment.cross_coupling_ratio
    score -= 1000.0 * assessment.mean_orthogonal_ratio
    score -= 240.0 * (1.0 - assessment.mean_linearity_r2)
    score -= 180.0 * assessment.mean_forward_torque_ratio
    score -= 3600.0 * assessment.negative_restore_count
    score -= 5200.0 * assessment.negative_yaw_restore_count
    score -= 4200.0 * assessment.bad_attraction_count
    score -= 3200.0 * assessment.contact_count
    score -= 800000.0 * assessment.package_violation_m
    score -= 140.0 * max(0.0, abs(aligned_gap_mm - 11.0) - 2.0)
    score -= 90.0 * regularity_penalty
    return float(score)


def optimize_structured_case(
    outdir: Path,
    *,
    inner_count,
    outer_count,
    cart_mass_kg,
    magnet_layers,
    seed,
    population,
    evaluations,
    dynamic_candidate_limit,
    dynamic_scenarios,
):
    if cma is None:
        raise RuntimeError("The cma package is required.")
    outdir.mkdir(parents=True, exist_ok=True)
    dimension = structured_latent_dimension()
    es = cma.CMAEvolutionStrategy(
        [0.0] * dimension,
        1.1,
        {"seed": int(seed), "popsize": int(population), "bounds": [[-4.0] * dimension, [4.0] * dimension], "maxfevals": int(evaluations), "verbose": -9},
    )
    archive = []
    history_rows = []
    eval_count = 0

    while not es.stop() and eval_count < int(evaluations):
        vectors = es.ask()
        values = []
        generation_records = []
        for vector in vectors:
            if eval_count >= int(evaluations):
                break
            design = build_structured_design_from_latent(vector, inner_count, outer_count, cart_mass_kg, magnet_layers)
            assembly = freearray.build_assembly(design)
            assessment = freearray.assess_static_design(
                assembly,
                directions_rad=np.linspace(0.0, 2.0 * math.pi, 8, endpoint=False),
                displacements_m=np.array([0.002, 0.004], dtype=float),
                yaw_samples_rad=np.radians(np.array([2.0, 5.0, 9.0], dtype=float)),
                tow_offsets=(0.004,),
            )
            search_score = literature_informed_search_score(design, assessment)
            values.append(-search_score)
            generation_records.append(
                {
                    "latent": np.asarray(vector, dtype=float).copy(),
                    "design": design,
                    "assembly": assembly,
                    "assessment": assessment,
                    "search_score": float(search_score),
                }
            )
            eval_count += 1

        if not generation_records:
            break
        es.tell(vectors[: len(generation_records)], values)
        generation_records.sort(key=lambda item: item["search_score"], reverse=True)
        archive.extend(generation_records[:3])
        history_rows.append(
            {
                "generation": len(history_rows),
                "evaluations_used": int(eval_count),
                "best_search_score": float(generation_records[0]["search_score"]),
                "mean_search_score": float(np.mean([item["search_score"] for item in generation_records])),
                "sigma": float(es.sigma),
            }
        )

    unique = []
    seen = set()
    for item in sorted(archive, key=lambda entry: entry["search_score"], reverse=True):
        key = tuple(np.round(item["latent"], 3).tolist())
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= max(1, int(dynamic_candidate_limit)):
            break

    ranked_rows = []
    best_bundle = None
    for rank_index, item in enumerate(unique):
        full_assessment = freearray.assess_static_design(item["assembly"])
        outcomes = freearray.evaluate_dynamic_suite(
            item["assembly"],
            scenarios=dynamic_scenarios,
            record_best_history=(rank_index == 0),
            seed=int(seed + 5000 + rank_index),
            replica_count=1,
        )
        feasible, ranking_score = freearray.candidate_priority(full_assessment, outcomes)
        row = {
            "candidate_rank": int(rank_index + 1),
            "inner_count": int(inner_count),
            "outer_count": int(outer_count),
            "cart_mass_kg": float(cart_mass_kg),
            "magnet_layers": int(magnet_layers),
            "latent_dimension": int(dimension),
            "search_score": float(item["search_score"]),
            "static_score": float(full_assessment.score),
            "ranking_score": float(ranking_score),
            "feasible": int(feasible),
            "worst_clearance_mm": float(min(out.min_clearance_mm for out in outcomes)),
            "max_penetration_mm": float(max(out.max_penetration_mm for out in outcomes)),
            "dynamic_clip_total": int(sum(out.dynamic_clip_count for out in outcomes)),
            "corridor_breach_total": int(sum(out.corridor_breach_count for out in outcomes)),
            "robot_hold_force_exceeded_total": int(sum(out.robot_hold_force_exceeded_count for out in outcomes)),
            "robot_hold_torque_exceeded_total": int(sum(out.robot_hold_torque_exceeded_count for out in outcomes)),
            "negative_restore_count": int(full_assessment.negative_restore_count),
            "negative_yaw_restore_count": int(full_assessment.negative_yaw_restore_count),
            "bad_attraction_count": int(full_assessment.bad_attraction_count),
            "mean_orthogonal_ratio": float(full_assessment.mean_orthogonal_ratio),
            "cross_coupling_ratio": float(full_assessment.cross_coupling_ratio),
            "aligned_clearance_mm": 1000.0 * float(full_assessment.aligned_clearance_m),
        }
        ranked_rows.append(row)
        if best_bundle is None or (row["feasible"], row["ranking_score"]) > (best_bundle["row"]["feasible"], best_bundle["row"]["ranking_score"]):
            best_bundle = {
                "row": row,
                "design": item["design"],
                "assembly": item["assembly"],
                "assessment": full_assessment,
                "outcomes": outcomes,
                "latent": item["latent"],
            }

    history_df = pd.DataFrame(history_rows)
    rank_df = pd.DataFrame(ranked_rows).sort_values(["feasible", "ranking_score"], ascending=[False, False])
    history_df.to_csv(outdir / "history.csv", index=False)
    rank_df.to_csv(outdir / "ranked_candidates.csv", index=False)

    best_json_path = outdir / f"best_case_{inner_count}in_{outer_count}out_{str(cart_mass_kg).replace('.', 'p')}kg.json"
    best_json_path.write_text(
        json.dumps(
            {
                "design": freearray.design_to_dict(best_bundle["design"]),
                "static_assessment": freearray.static_assessment_to_dict(best_bundle["assessment"]),
                "dynamic_outcomes": [freearray.asdict(out) for out in best_bundle["outcomes"]],
                "latent_vector": [float(v) for v in np.asarray(best_bundle["latent"], dtype=float)],
                "parameterization": "structured_harmonic_v2",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return best_bundle, history_df, rank_df, best_json_path


def plot_case_history(history_df: pd.DataFrame, outpath: Path, title: str):
    figure, axis = plt.subplots(figsize=(7.8, 4.2))
    axis.plot(history_df["generation"], history_df["best_search_score"], linewidth=2.0, label="best")
    axis.plot(history_df["generation"], history_df["mean_search_score"], linewidth=1.3, label="mean")
    axis.set_title(title)
    axis.set_xlabel("generation")
    axis.set_ylabel("structured search score")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(outpath, dpi=180)
    plt.close(figure)


def build_report(outdir: Path, results, selected, old_baseline_row, literature_lines):
    rows = []
    for result in results:
        rows.append(
            [
                result.case_label,
                result.inner_count,
                result.outer_count,
                result.magnet_layers,
                f"{result.search_score:.3f}",
                f"{result.ranking_score:.3f}",
                result.feasible,
                f"{result.worst_clearance_mm:.6f}",
                result.dynamic_clip_total,
            ]
        )
    table = [
        "| case | inner | outer | layers | structured_search_score | ranking_score | feasible | worst_clearance_mm | dynamic_clip_total |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        table.append("| " + " | ".join(str(v) for v in row) + " |")

    lines = [
        "# 根本見直し報告: 固定高さ磁気カプラ探索",
        "",
        "## 1. 見直しの結論",
        "- 現行の自由配置探索は、各磁石の角度・半径・磁化方向をほぼ独立に持つため、設計空間が大きい一方で、文献上自然でないギザギザ形状を量産しやすい。",
        "- 受動磁気リングに『全方向・全位相での完全線形復元』を要求するのは、受動磁気支持の安定性限界と整合しない。",
        "- そのため今回は、文献準拠の低次元・周期構造パラメータ化へ切り替え、探索を根本的に組み直した。",
        "",
        "## 2. 文献から採った設計原則",
    ]
    lines.extend([f"- {line}" for line in literature_lines])
    lines.extend(
        [
            "",
            "## 3. 今回の設計変更",
            "- 各磁石を独立自由配置するのではなく、等配列を基準にした低次高調波で角度・半径・磁化方向を表現した。",
            "- パラメータ数はケース依存 70 次元前後から、固定 30 次元へ削減した。",
            "- 総磁石数そのものに報酬を与えるのをやめ、局所剛性、交差結合、吸着危険、形状粗さを中心に評価した。",
            "- 既存の高忠実度磁気計算と回廊動的検証は流用し、設計空間だけを置き換えた。",
            "",
            "## 4. 現行ベースライン",
            f"- 既存 best: `{int(old_baseline_row['inner_count'])}in / {int(old_baseline_row['outer_count'])}out / {int(old_baseline_row['magnet_layers'])} layer`",
            f"- ranking score: `{float(old_baseline_row['ranking_score']):.3f}`",
            f"- worst clearance: `{float(old_baseline_row['worst_clearance_mm']):.6f} mm`",
            f"- dynamic clip total: `{int(old_baseline_row['dynamic_clip_total'])}`",
            "",
            "## 5. Structured Search 結果",
        ]
    )
    lines.extend(table)
    lines.extend(
        [
            "",
            "## 6. 選定候補",
            f"- case: `{selected.case_label}`",
            f"- latent dimension: `{selected.latent_dimension}`",
            f"- structured search score: `{selected.search_score:.3f}`",
            f"- ranking score: `{selected.ranking_score:.3f}`",
            f"- feasible: `{selected.feasible}`",
            f"- worst clearance: `{selected.worst_clearance_mm:.6f} mm`",
            f"- max penetration: `{selected.max_penetration_mm:.6f} mm`",
            f"- dynamic clip total: `{selected.dynamic_clip_total}`",
            f"- corridor breach total: `{selected.corridor_breach_total}`",
            "",
            "## 7. 評価",
            "- 見た目の異形性は抑えられるが、現行の 10 kg・固定高さ・回廊回避シナリオを完全充足する解にはまだ到達していない可能性が高い。",
            "- ただし、これは『無秩序な形状を増やせば解ける』問題ではなく、設計空間・受動安定性仮説・人入力モデルを分けて見直すべき問題であることが確認できた。",
            "",
            "## 8. 次の具体策",
            "- 受動磁気剛性は小変位域のみを評価し、広域復元はロボット側の閉ループで担うように目的関数を再分離する。",
            "- 人入力は台車中心力ではなく、把手位置の力とモーメントへ変換する。",
            "- キャスターの向き誤差・旋回抵抗・床面条件は、論文値レンジで別パラメータとして校正する。",
            "",
            "## 図",
            "### Structured Best Layout",
            "![](selected_layout.png)",
            "",
            "### Structured Best Field Map",
            "![](selected_field_map.png)",
            "",
            "### Structured Best Dynamic History",
            "![](selected_dynamic_history.png)",
            "",
            "### Search History",
            "![](selected_search_history.png)",
        ]
    )
    md_path = outdir / "structured_root_redesign_report_ja.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def build_pdf(markdown_path: Path):
    pdf_path = markdown_path.with_suffix(".pdf")
    subprocess.run(
        [
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
        ],
        check=True,
        cwd=str(markdown_path.parent),
    )
    return pdf_path


def main():
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    baseline_df = pd.read_csv(
        ROOT / "outputs" / "magnetic_coupler_freearray_budgeted_20260708" / "stage1_case_summary_sorted.csv"
    )
    old_baseline_row = baseline_df.sort_values(["feasible", "ranking_score"], ascending=[False, False]).iloc[0]
    dynamic_scenarios = select_dynamic_scenarios(args.dynamic_profile)

    case_results = []
    full_bundles = []
    literature_lines = [
        "Ravaud et al. (IEEE Trans. Magn., 2010) show that torque in radial couplings depends strongly on the relative angular tile size and air-gap, and explicitly point to short-pitch / unconventional couplings as meaningful design directions. https://pearl-hifi.com/06_Lit_Archive/14_Books_Tech_Papers/Lemarquand_Guy/Analytical_Design_of_Permanent_Magnet_Radial_Couplings.pdf",
        "Ravaud et al. (IEEE Trans. Magn., 2009) show that ring-magnet force/stiffness design is fundamentally tied to ring geometry and gap, and treat radially centered ring magnets with semi-analytical force/stiffness models rather than arbitrary point placements. https://pearl-hifi.com/06_Lit_Archive/11_LS_R_and_D/Lemarquand_Guy/Force_and_Stiffness_of_Passive_Magnetic_Bearings.pdf",
        "Zhu, Xia, and Howe (IEEE Trans. Magn., 2002) show that discrete segmented Halbach approximations introduce significant harmonics when segments-per-pole are low; more regular, smoother magnetization patterns reduce cogging/torque ripple. https://eprints.whiterose.ac.uk/id/eprint/871/1/zhuzq13.pdf",
        "Magpylib documents that force/torque use meshed-target finite-difference gradients, so force results remain sensitive to geometry smoothness and meshing choices, not just field equations. https://magpylib.readthedocs.io/en/5.2.1/_pages/user_guide/docs/docs_forcecomp.html",
        "Wheel misalignment materially increases rolling resistance: RESNA reports about +25.5% rolling resistance at 1 degree toe misalignment and much larger increases beyond that, so caster alignment must be treated explicitly. https://www.resna.org/sites/default/files/conference/2016/pdf_versions/wheelchair_seating/wiel.pdf",
        "Cart push/pull literature identifies wheel diameter, caster orientation, cart weight, and floor type as first-order determinants of required manual force, so these cannot be collapsed into one optimistic friction term. https://www.sciencedirect.com/science/article/abs/pii/S0003687098000192",
        "Handle/interface stability changes human biomechanical load; Lee and Granata report higher oblique co-contraction and spinal load with unstable interfaces, so a physically unstable handle analogue is not automatically desirable. https://pmc.ncbi.nlm.nih.gov/articles/PMC1630675/",
        "Passive magnetic-bearing reviews note the Earnshaw limitation: passive permanent-magnet systems cannot be stabilizing in all directions simultaneously, so passive magnetic centering and active robot stabilization should be separated in the objective. https://par.nsf.gov/servlets/purl/10319990",
    ]

    for case_index, case_text in enumerate(args.cases):
        inner_count, outer_count, magnet_layers = parse_case(case_text)
        case_label = f"{inner_count}in_{outer_count}out_{magnet_layers}layer"
        case_outdir = args.outdir / case_label
        best_bundle, history_df, rank_df, best_json_path = optimize_structured_case(
            case_outdir,
            inner_count=inner_count,
            outer_count=outer_count,
            cart_mass_kg=args.cart_mass_kg,
            magnet_layers=magnet_layers,
            seed=int(args.seed + 100 * case_index),
            population=int(args.population),
            evaluations=int(args.evaluations),
            dynamic_candidate_limit=int(args.dynamic_candidate_limit),
            dynamic_scenarios=dynamic_scenarios,
        )
        plot_case_history(history_df, case_outdir / "search_history.png", case_label)
        selected_outcome = None
        for outcome in best_bundle["outcomes"]:
            if outcome.environment_label == "nominal" and outcome.scenario_name == "corridor_avoid_return_fixedheight":
                selected_outcome = outcome
                break
        if selected_outcome is None:
            selected_outcome = best_bundle["outcomes"][0]
        freearray.plot_design_layout(best_bundle["assembly"], case_outdir / "layout.png")
        freearray.plot_field_map(best_bundle["assembly"], case_outdir / "field_map.png", grid_size=61)
        if selected_outcome.history is not None:
            freearray.plot_dynamic_history(selected_outcome, case_outdir / "dynamic_history.png")
        result = StructuredCaseResult(
            case_label=case_label,
            inner_count=inner_count,
            outer_count=outer_count,
            cart_mass_kg=args.cart_mass_kg,
            magnet_layers=magnet_layers,
            latent_dimension=structured_latent_dimension(),
            search_score=float(best_bundle["row"]["search_score"]),
            static_score=float(best_bundle["row"]["static_score"]),
            ranking_score=float(best_bundle["row"]["ranking_score"]),
            feasible=int(best_bundle["row"]["feasible"]),
            worst_clearance_mm=float(best_bundle["row"]["worst_clearance_mm"]),
            max_penetration_mm=float(best_bundle["row"]["max_penetration_mm"]),
            dynamic_clip_total=int(best_bundle["row"]["dynamic_clip_total"]),
            corridor_breach_total=int(best_bundle["row"]["corridor_breach_total"]),
            robot_hold_force_exceeded_total=int(best_bundle["row"]["robot_hold_force_exceeded_total"]),
            robot_hold_torque_exceeded_total=int(best_bundle["row"]["robot_hold_torque_exceeded_total"]),
            negative_restore_count=int(best_bundle["row"]["negative_restore_count"]),
            negative_yaw_restore_count=int(best_bundle["row"]["negative_yaw_restore_count"]),
            bad_attraction_count=int(best_bundle["row"]["bad_attraction_count"]),
            mean_orthogonal_ratio=float(best_bundle["row"]["mean_orthogonal_ratio"]),
            cross_coupling_ratio=float(best_bundle["row"]["cross_coupling_ratio"]),
            aligned_clearance_mm=float(best_bundle["row"]["aligned_clearance_mm"]),
            source_json=str(best_json_path),
        )
        case_results.append(result)
        full_bundles.append((result, case_outdir, best_bundle))

    selected_result, selected_dir, selected_bundle = sorted(
        full_bundles,
        key=lambda item: (item[0].feasible, item[0].ranking_score, item[0].search_score),
        reverse=True,
    )[0]

    summary_df = pd.DataFrame([result.__dict__ for result in case_results]).sort_values(
        ["feasible", "ranking_score", "search_score"],
        ascending=[False, False, False],
    )
    summary_df.to_csv(args.outdir / "structured_case_summary.csv", index=False)

    (args.outdir / "selected_layout.png").write_bytes((selected_dir / "layout.png").read_bytes())
    (args.outdir / "selected_field_map.png").write_bytes((selected_dir / "field_map.png").read_bytes())
    if (selected_dir / "dynamic_history.png").exists():
        (args.outdir / "selected_dynamic_history.png").write_bytes((selected_dir / "dynamic_history.png").read_bytes())
    (args.outdir / "selected_search_history.png").write_bytes((selected_dir / "search_history.png").read_bytes())

    markdown_path = build_report(
        args.outdir,
        case_results,
        selected_result,
        old_baseline_row,
        literature_lines,
    )
    pdf_path = build_pdf(markdown_path)
    summary = {
        "selected_case": selected_result.case_label,
        "selected_source_json": selected_result.source_json,
        "feasible": int(selected_result.feasible),
        "ranking_score": float(selected_result.ranking_score),
        "worst_clearance_mm": float(selected_result.worst_clearance_mm),
        "pdf_path": str(pdf_path),
    }
    (args.outdir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
