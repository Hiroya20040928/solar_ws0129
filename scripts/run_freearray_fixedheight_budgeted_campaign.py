import argparse
import json
import math
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_freearray_fixedheight as freearray


DEFAULT_COUNT_PAIRS = (
    "12x20",
    "12x24",
    "16x20",
    "16x24",
    "16x28",
    "20x24",
    "20x28",
    "24x28",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Budgeted fixed-height free-array campaign: low-overhead search during optimization, "
            "then high-fidelity rendering only for top candidates."
        )
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_freearray_budgeted_20260708",
    )
    parser.add_argument("--seed", type=int, default=20260708)
    parser.add_argument("--total-evaluations", type=int, default=2400)
    parser.add_argument("--stage1-fraction", type=float, default=0.40)
    parser.add_argument("--population", type=int, default=12)
    parser.add_argument("--dynamic-replica-count", type=int, default=1)
    parser.add_argument("--dynamic-candidate-limit", type=int, default=3)
    parser.add_argument("--shortlist-k", type=int, default=4)
    parser.add_argument("--restarts-per-case", type=int, default=3)
    parser.add_argument("--render-top-k", type=int, default=3)
    parser.add_argument("--masses-kg", type=float, nargs="+", default=[10.0])
    parser.add_argument("--magnet-layers", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--count-pairs", type=str, nargs="*", default=list(DEFAULT_COUNT_PAIRS))
    parser.add_argument("--sigma-list", type=float, nargs="+", default=[0.20, 0.12, 0.07])
    parser.add_argument("--live-dynamic-stride", type=int, default=10)
    parser.add_argument("--live-shape-stride", type=int, default=10)
    parser.add_argument("--live-field-stride", type=int, default=0)
    parser.add_argument("--live-video-stride", type=int, default=0)
    return parser.parse_args()


def parse_count_pairs(raw_values):
    pairs = []
    for raw in raw_values:
        inner_text, outer_text = raw.lower().replace("in", "").replace("out", "").split("x")
        pairs.append((int(inner_text), int(outer_text)))
    return tuple(pairs)


def round_up_to_population(value, population):
    population = max(int(population), 1)
    return int(math.ceil(max(float(value), float(population)) / population) * population)


def format_mass_slug(mass_kg):
    return str(float(mass_kg)).replace(".", "p")


def case_dir_name(inner_count, outer_count, mass_kg, magnet_layers):
    return f"{inner_count}in_{outer_count}out_{format_mass_slug(mass_kg)}kg_{magnet_layers}layer"


def best_case_json_path(base_outdir: Path, inner_count, outer_count, mass_kg, magnet_layers):
    case_dir = base_outdir / case_dir_name(inner_count, outer_count, mass_kg, magnet_layers)
    filename = f"best_case_{inner_count}in_{outer_count}out_{format_mass_slug(mass_kg)}kg.json"
    return case_dir / filename


def load_best_case_payload(json_path: Path):
    return json.loads(json_path.read_text(encoding="utf-8"))


def load_initial_latent(payload):
    latent = payload.get("latent_vector")
    if latent is not None:
        return np.asarray(latent, dtype=float)
    design = freearray.design_from_dict(payload["design"])
    return freearray.latent_from_design(design)


def summarize_candidate(candidate, outcomes, restart_index, sigma0, case_budget):
    feasible, ranking_score = freearray.candidate_priority(candidate["static"], outcomes)
    return {
        "restart_index": int(restart_index),
        "sigma0": float(sigma0),
        "allocated_evaluations": int(case_budget),
        "inner_count": int(candidate["design"].inner_count),
        "outer_count": int(candidate["design"].outer_count),
        "cart_mass_kg": float(candidate["design"].cart_mass_kg),
        "magnet_layers": int(candidate["design"].magnet_layers),
        "realistic_mass_ok": int(candidate["static"].cart_mass_kg >= freearray.REALISTIC_MIN_CART_MASS_KG),
        "static_score": float(candidate["static"].score),
        "scaled_min_eigenvalue": float(np.min(candidate["static"].scaled_eigenvalues)),
        "mean_orthogonal_ratio": float(candidate["static"].mean_orthogonal_ratio),
        "cross_coupling_ratio": float(candidate["static"].cross_coupling_ratio),
        "aligned_clearance_mm": 1000.0 * float(candidate["static"].aligned_clearance_m),
        "mean_dynamic_score": float(np.mean([outcome.score for outcome in outcomes])),
        "worst_clearance_mm": float(min(outcome.min_clearance_mm for outcome in outcomes)),
        "max_penetration_mm": float(max(outcome.max_penetration_mm for outcome in outcomes)),
        "contact_events_total": int(sum(outcome.contact_events for outcome in outcomes)),
        "min_robot_corridor_margin_mm": float(min(outcome.min_robot_corridor_margin_mm for outcome in outcomes)),
        "min_cart_corridor_margin_mm": float(min(outcome.min_cart_corridor_margin_mm for outcome in outcomes)),
        "corridor_breach_total": int(sum(outcome.corridor_breach_count for outcome in outcomes)),
        "max_corridor_breach_mm": float(max(outcome.max_corridor_breach_mm for outcome in outcomes)),
        "robot_hold_force_exceeded_total": int(sum(outcome.robot_hold_force_exceeded_count for outcome in outcomes)),
        "robot_hold_torque_exceeded_total": int(sum(outcome.robot_hold_torque_exceeded_count for outcome in outcomes)),
        "dynamic_clip_total": int(sum(outcome.dynamic_clip_count for outcome in outcomes)),
        "ranking_score": float(ranking_score),
        "feasible": int(feasible),
    }


def refine_case_from_payload(
    source_payload,
    refine_outdir: Path,
    *,
    seed: int,
    total_case_evaluations: int,
    population: int,
    restarts_per_case: int,
    dynamic_replica_count: int,
    dynamic_candidate_limit: int,
    sigma_list,
    scenarios,
):
    refine_outdir.mkdir(parents=True, exist_ok=True)
    source_design = freearray.design_from_dict(source_payload["design"])
    initial_latent = load_initial_latent(source_payload)
    evals_per_restart = round_up_to_population(
        float(total_case_evaluations) / max(int(restarts_per_case), 1),
        population,
    )
    rows = []
    best_bundle = None

    for restart_index in range(int(restarts_per_case)):
        sigma0 = float(sigma_list[restart_index % len(sigma_list)])
        restart_outdir = refine_outdir / f"restart_{restart_index:02d}"
        restart_outdir.mkdir(parents=True, exist_ok=True)
        candidate, outcomes, history_df, case_df = freearray.optimize_case(
            outdir=restart_outdir,
            inner_count=source_design.inner_count,
            outer_count=source_design.outer_count,
            cart_mass_kg=source_design.cart_mass_kg,
            magnet_layers=source_design.magnet_layers,
            seed=int(seed + 101 * restart_index),
            evaluations=int(evals_per_restart),
            population=int(population),
            dynamic_replica_count=int(dynamic_replica_count),
            dynamic_scenarios=scenarios,
            dynamic_candidate_limit=int(dynamic_candidate_limit),
            initial_mean=initial_latent,
            sigma0=sigma0,
        )
        row = summarize_candidate(candidate, outcomes, restart_index, sigma0, int(evals_per_restart))
        rows.append(row)
        if best_bundle is None or (row["feasible"], row["ranking_score"]) > (
            best_bundle["summary"]["feasible"],
            best_bundle["summary"]["ranking_score"],
        ):
            best_bundle = {
                "summary": row,
                "candidate": candidate,
                "outcomes": outcomes,
                "history_df": history_df,
                "case_df": case_df,
                "restart_outdir": restart_outdir,
            }

    summary_df = pd.DataFrame(rows).sort_values(["feasible", "ranking_score"], ascending=[False, False])
    summary_df.to_csv(refine_outdir / "refinement_runs.csv", index=False)
    summary_payload = {
        "source_design": source_payload["design"],
        "restarts_per_case": int(restarts_per_case),
        "evals_per_restart": int(evals_per_restart),
        "sigma_list": [float(value) for value in sigma_list],
        "best_restart": best_bundle["summary"] if best_bundle is not None else None,
        "best_restart_outdir": str(best_bundle["restart_outdir"]) if best_bundle is not None else None,
    }
    (refine_outdir / "refinement_summary.json").write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return best_bundle


def render_ranked_candidates(candidate_records, render_outdir: Path, *, top_k: int, scenarios, dynamic_replica_count: int):
    render_outdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for rank, record in enumerate(candidate_records[: max(int(top_k), 0)], start=1):
        label = (
            f"rank{rank:02d}_"
            f"{record['inner_count']}in_{record['outer_count']}out_"
            f"{format_mass_slug(record['cart_mass_kg'])}kg_{record['magnet_layers']}layer"
        )
        candidate_dir = render_outdir / label
        artifacts = freearray.render_candidate_artifacts(
            record["design"],
            candidate_dir,
            scenarios=scenarios,
            dynamic_replica_count=dynamic_replica_count,
            field_grid_size=81,
            video_stem=label,
        )
        dynamic_df = artifacts["dynamic_df"]
        rows.append(
            {
                "rank": int(rank),
                "label": label,
                "source": record["source"],
                "inner_count": int(record["inner_count"]),
                "outer_count": int(record["outer_count"]),
                "cart_mass_kg": float(record["cart_mass_kg"]),
                "magnet_layers": int(record["magnet_layers"]),
                "feasible": int(record["feasible"]),
                "ranking_score": float(record["ranking_score"]),
                "static_score": float(record["static_score"]),
                "rendered_mean_dynamic_score": float(dynamic_df["score"].mean()),
                "rendered_worst_clearance_mm": float(dynamic_df["min_clearance_mm"].min()),
                "rendered_max_penetration_mm": float(dynamic_df["max_penetration_mm"].max()),
                "rendered_corridor_breach_total": int(dynamic_df["corridor_breach_count"].sum()),
                "rendered_max_corridor_breach_mm": float(dynamic_df["max_corridor_breach_mm"].max()),
                "asset_dir": str(candidate_dir),
            }
        )
    render_df = pd.DataFrame(rows)
    render_df.to_csv(render_outdir / "rendered_top_candidates.csv", index=False)
    return render_df


def build_report(outdir: Path, config: dict, stage1_df: pd.DataFrame, refined_df: pd.DataFrame | None, rendered_df: pd.DataFrame | None):
    lines = [
        "# Budgeted Free-Array Fixed-Height Campaign",
        "",
        "## Configuration",
        f"- Total evaluation budget: `{config['total_evaluations']}`",
        f"- Stage-1 fraction: `{config['stage1_fraction']:.2f}`",
        f"- Stage-1 evaluations per case: `{config['stage1_evaluations_per_case']}`",
        f"- Population: `{config['population']}`",
        f"- Count pairs: `{', '.join(config['count_pair_labels'])}`",
        f"- Magnet layers: `{', '.join(str(v) for v in config['magnet_layers'])}`",
        f"- Cart masses [kg]: `{', '.join(f'{v:.1f}' for v in config['masses_kg'])}`",
        "",
        "## Stage-1 Best",
    ]
    if not stage1_df.empty:
        best_stage1 = stage1_df.sort_values(["feasible", "ranking_score"], ascending=[False, False]).iloc[0]
        lines.extend(
            [
                f"- Best case: `{int(best_stage1['inner_count'])}in / {int(best_stage1['outer_count'])}out / {float(best_stage1['cart_mass_kg']):.1f} kg / {int(best_stage1['magnet_layers'])} layer`",
                f"- Feasible: `{'YES' if int(best_stage1['feasible']) else 'NO'}`",
                f"- Ranking score: `{float(best_stage1['ranking_score']):.3f}`",
                f"- Worst clearance: `{float(best_stage1['worst_clearance_mm']):.3f} mm`",
                f"- Max penetration: `{float(best_stage1['max_penetration_mm']):.3f} mm`",
                f"- Max corridor breach: `{float(best_stage1['max_corridor_breach_mm']):.3f} mm`",
            ]
        )
    else:
        lines.append("- No stage-1 results.")

    lines.extend(["", "## Refinement Best"])
    if refined_df is not None and not refined_df.empty:
        best_refined = refined_df.sort_values(["feasible", "ranking_score"], ascending=[False, False]).iloc[0]
        lines.extend(
            [
                f"- Best refined case: `{int(best_refined['inner_count'])}in / {int(best_refined['outer_count'])}out / {float(best_refined['cart_mass_kg']):.1f} kg / {int(best_refined['magnet_layers'])} layer`",
                f"- Source: `{best_refined['source']}`",
                f"- Feasible: `{'YES' if int(best_refined['feasible']) else 'NO'}`",
                f"- Ranking score: `{float(best_refined['ranking_score']):.3f}`",
                f"- Worst clearance: `{float(best_refined['worst_clearance_mm']):.3f} mm`",
                f"- Max penetration: `{float(best_refined['max_penetration_mm']):.3f} mm`",
                f"- Max corridor breach: `{float(best_refined['max_corridor_breach_mm']):.3f} mm`",
            ]
        )
    else:
        lines.append("- No refinement results.")

    lines.extend(["", "## Rendered Top Candidates"])
    if rendered_df is not None and not rendered_df.empty:
        for _, row in rendered_df.iterrows():
            lines.append(
                f"- Rank {int(row['rank'])}: `{row['label']}` | mean score `{float(row['rendered_mean_dynamic_score']):.3f}` | "
                f"worst clearance `{float(row['rendered_worst_clearance_mm']):.3f} mm` | "
                f"max breach `{float(row['rendered_max_corridor_breach_mm']):.3f} mm`"
            )
    else:
        lines.append("- No rendered candidate assets.")

    (outdir / "budgeted_campaign_report_ja.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    args = parse_args()
    count_pairs = parse_count_pairs(args.count_pairs)
    args.outdir.mkdir(parents=True, exist_ok=True)
    stage1_outdir = args.outdir / "stage1_screen"
    refine_outdir = args.outdir / "stage2_refine"
    render_outdir = args.outdir / "top_candidate_assets"

    total_cases = len(count_pairs) * len(args.masses_kg) * len(args.magnet_layers)
    stage1_total_target = max(int(round(args.total_evaluations * args.stage1_fraction)), args.population * total_cases)
    stage1_evaluations_per_case = round_up_to_population(
        float(stage1_total_target) / max(total_cases, 1),
        args.population,
    )
    stage1_total_actual = stage1_evaluations_per_case * total_cases

    config_payload = {
        "seed": int(args.seed),
        "total_evaluations": int(args.total_evaluations),
        "stage1_fraction": float(args.stage1_fraction),
        "population": int(args.population),
        "dynamic_replica_count": int(args.dynamic_replica_count),
        "dynamic_candidate_limit": int(args.dynamic_candidate_limit),
        "count_pair_labels": [f"{inner}x{outer}" for inner, outer in count_pairs],
        "masses_kg": [float(v) for v in args.masses_kg],
        "magnet_layers": [int(v) for v in args.magnet_layers],
        "stage1_evaluations_per_case": int(stage1_evaluations_per_case),
        "stage1_total_actual": int(stage1_total_actual),
        "shortlist_k": int(args.shortlist_k),
        "restarts_per_case": int(args.restarts_per_case),
        "render_top_k": int(args.render_top_k),
    }
    (args.outdir / "campaign_config.json").write_text(
        json.dumps(config_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(config_payload, ensure_ascii=False), flush=True)

    scenarios = (freearray.build_avoid_return_scenario(),)
    freearray.run_fixedheight_freearray_search(
        outdir=stage1_outdir,
        seed=args.seed,
        evaluations_per_case=int(stage1_evaluations_per_case),
        population=int(args.population),
        count_pairs=count_pairs,
        cart_mass_values_kg=tuple(float(v) for v in args.masses_kg),
        magnet_layers_values=tuple(int(v) for v in args.magnet_layers),
        dynamic_replica_count=int(args.dynamic_replica_count),
        dynamic_scenarios=scenarios,
        dynamic_candidate_limit=int(args.dynamic_candidate_limit),
        live_dynamic_stride_generations=int(args.live_dynamic_stride),
        live_shape_stride_generations=int(args.live_shape_stride),
        live_field_stride_generations=int(args.live_field_stride),
        live_video_stride_generations=int(args.live_video_stride),
        live_field_grid_size=41,
    )

    stage1_df = pd.read_csv(stage1_outdir / "case_summary.csv")
    stage1_df = stage1_df.sort_values(["feasible", "ranking_score"], ascending=[False, False]).reset_index(drop=True)
    stage1_df.to_csv(args.outdir / "stage1_case_summary_sorted.csv", index=False)
    shortlist_df = stage1_df.head(max(int(args.shortlist_k), 1)).copy()
    shortlist_df.to_csv(args.outdir / "stage1_shortlist.csv", index=False)

    stage2_total_target = max(int(args.total_evaluations) - int(stage1_total_actual), args.population)
    refine_case_evaluations = round_up_to_population(
        float(stage2_total_target) / max(len(shortlist_df), 1),
        args.population,
    )

    refined_rows = []
    candidate_records = []
    for shortlist_index, row in shortlist_df.iterrows():
        best_case_path = best_case_json_path(
            stage1_outdir,
            int(row["inner_count"]),
            int(row["outer_count"]),
            float(row["cart_mass_kg"]),
            int(row["magnet_layers"]),
        )
        payload = load_best_case_payload(best_case_path)
        case_label = case_dir_name(
            int(row["inner_count"]),
            int(row["outer_count"]),
            float(row["cart_mass_kg"]),
            int(row["magnet_layers"]),
        )
        bundle = refine_case_from_payload(
            payload,
            refine_outdir / case_label,
            seed=int(args.seed + 5000 + 100 * shortlist_index),
            total_case_evaluations=int(refine_case_evaluations),
            population=int(args.population),
            restarts_per_case=int(args.restarts_per_case),
            dynamic_replica_count=int(args.dynamic_replica_count),
            dynamic_candidate_limit=int(args.dynamic_candidate_limit),
            sigma_list=tuple(float(value) for value in args.sigma_list),
            scenarios=scenarios,
        )
        summary_row = dict(bundle["summary"])
        summary_row["source"] = case_label
        refined_rows.append(summary_row)
        candidate_records.append(
            {
                "source": case_label,
                "inner_count": int(summary_row["inner_count"]),
                "outer_count": int(summary_row["outer_count"]),
                "cart_mass_kg": float(summary_row["cart_mass_kg"]),
                "magnet_layers": int(summary_row["magnet_layers"]),
                "feasible": int(summary_row["feasible"]),
                "ranking_score": float(summary_row["ranking_score"]),
                "static_score": float(summary_row["static_score"]),
                "worst_clearance_mm": float(summary_row["worst_clearance_mm"]),
                "max_penetration_mm": float(summary_row["max_penetration_mm"]),
                "max_corridor_breach_mm": float(summary_row["max_corridor_breach_mm"]),
                "design": bundle["candidate"]["design"],
            }
        )

    refined_df = pd.DataFrame(refined_rows).sort_values(["feasible", "ranking_score"], ascending=[False, False])
    refined_df.to_csv(args.outdir / "stage2_refinement_summary.csv", index=False)
    rendered_df = render_ranked_candidates(
        sorted(candidate_records, key=lambda item: (item["feasible"], item["ranking_score"]), reverse=True),
        render_outdir,
        top_k=int(args.render_top_k),
        scenarios=scenarios,
        dynamic_replica_count=int(args.dynamic_replica_count),
    )

    final_summary = {
        **config_payload,
        "stage2_total_target": int(stage2_total_target),
        "stage2_evaluations_per_shortlisted_case": int(refine_case_evaluations),
        "stage1_best_case": stage1_df.iloc[0].to_dict() if not stage1_df.empty else None,
        "stage2_best_case": refined_df.iloc[0].to_dict() if not refined_df.empty else None,
    }
    (args.outdir / "campaign_summary.json").write_text(
        json.dumps(final_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    build_report(args.outdir, final_summary, stage1_df, refined_df, rendered_df)
    print(json.dumps(final_summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
