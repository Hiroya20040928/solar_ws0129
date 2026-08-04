import argparse
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_freearray_fixedheight as freearray


DEFAULT_COUNT_PAIRS = ((12, 20), (16, 20), (16, 24), (20, 24), (20, 28), (24, 28))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the free-array fixed-height search under the realistic gate: no contact, no attraction, cart mass >= 10 kg."
    )
    parser.add_argument("--outdir", type=Path, default=ROOT / "outputs" / "magnetic_coupler_freearray_fixedheight_realistic_gate_20260705")
    parser.add_argument("--seed", type=int, default=20260705)
    parser.add_argument("--evaluations-per-case", type=int, default=4)
    parser.add_argument("--population", type=int, default=4)
    parser.add_argument("--dynamic-replica-count", type=int, default=1)
    parser.add_argument("--dynamic-candidate-limit", type=int, default=1)
    parser.add_argument("--masses-kg", type=float, nargs="+", default=[10.0, 12.0])
    parser.add_argument("--magnet-layers", type=int, nargs="+", default=[1])
    parser.add_argument("--count-pairs", type=str, nargs="*", default=["12x20", "16x20", "16x24", "20x24", "20x28", "24x28"])
    return parser.parse_args()


def parse_count_pairs(raw_values):
    pairs = []
    for raw in raw_values:
        inner_text, outer_text = raw.lower().replace("in", "").replace("out", "").split("x")
        pairs.append((int(inner_text), int(outer_text)))
    return tuple(pairs)


def load_case_rows(case_summary_path: Path):
    if not case_summary_path.exists():
        return pd.DataFrame()
    return pd.read_csv(case_summary_path)


def build_report(summary_df: pd.DataFrame):
    if summary_df.empty:
        return "\n".join(
            [
                "# Free-Array Fixed-Height Realistic Gate",
                "",
                "No results were produced.",
            ]
        )

    best_row = summary_df.sort_values(["feasible", "ranking_score"], ascending=[False, False]).iloc[0]
    lines = [
        "# Free-Array Fixed-Height Realistic Gate",
        "",
        "## Gate",
        f"- Cart mass must satisfy `>= {freearray.REALISTIC_MIN_CART_MASS_KG:.1f} kg`.",
        "- Any contact event is immediate failure.",
        "- Any attraction / negative restoring sample is immediate failure.",
        "- Any dynamic clipping intervention is counted as failure.",
        "- Any corridor breach (robot or cart body/ring leaving the corridor) is immediate failure.",
        "- Minimum dynamic clearance must stay at or above `2.0 mm`.",
        "",
        "## Best Current Case Under This Gate",
        f"- Inner / outer magnets: `{int(best_row['inner_count'])}` / `{int(best_row['outer_count'])}`",
        f"- Cart mass: `{float(best_row['cart_mass_kg']):.3f} kg`",
        f"- Realistic-mass gate: `{'PASS' if int(best_row['realistic_mass_ok']) else 'FAIL'}`",
        f"- Feasible: `{'YES' if int(best_row['feasible']) else 'NO'}`",
        f"- Ranking score: `{float(best_row['ranking_score']):.3f}`",
        f"- Worst clearance: `{float(best_row['worst_clearance_mm']):.3f} mm`",
        f"- Max penetration: `{float(best_row['max_penetration_mm']):.3f} mm`",
        f"- Minimum robot corridor margin: `{float(best_row['min_robot_corridor_margin_mm']):.3f} mm`",
        f"- Minimum cart corridor margin: `{float(best_row['min_cart_corridor_margin_mm']):.3f} mm`",
        f"- Corridor breach total: `{int(best_row['corridor_breach_total'])}`",
        f"- Worst corridor breach: `{float(best_row['max_corridor_breach_mm']):.3f} mm`",
        f"- Contact events total: `{int(best_row['contact_events_total'])}`",
        f"- Hold-force exceedances total: `{int(best_row['robot_hold_force_exceeded_total'])}`",
        f"- Dynamic clipping total: `{int(best_row['dynamic_clip_total'])}`",
        "",
        "## Interpretation",
        "- If `feasible = NO`, then the current fixed-height free-array mechanism still fails the intended operating principle under realistic minimum cart mass.",
        "- In that situation, any lower-mass screening result should be treated as exploratory only and not as a candidate real mechanism.",
    ]
    return "\n".join(lines)


def main():
    args = parse_args()
    count_pairs = parse_count_pairs(args.count_pairs)
    args.outdir.mkdir(parents=True, exist_ok=True)
    print(
        json.dumps(
            {
                "event": "campaign_start",
                "outdir": str(args.outdir),
                "seed": int(args.seed),
                "evaluations_per_case": int(args.evaluations_per_case),
                "population": int(args.population),
                "dynamic_replica_count": int(args.dynamic_replica_count),
                "dynamic_candidate_limit": int(args.dynamic_candidate_limit),
                "masses_kg": [float(value) for value in args.masses_kg],
                "magnet_layers": [int(value) for value in args.magnet_layers],
                "count_pairs": [[int(inner), int(outer)] for inner, outer in count_pairs],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

    freearray.run_fixedheight_freearray_search(
        outdir=args.outdir,
        seed=args.seed,
        evaluations_per_case=args.evaluations_per_case,
        population=args.population,
        count_pairs=count_pairs,
        cart_mass_values_kg=tuple(float(value) for value in args.masses_kg),
        magnet_layers_values=tuple(int(value) for value in args.magnet_layers),
        dynamic_replica_count=args.dynamic_replica_count,
        dynamic_candidate_limit=args.dynamic_candidate_limit,
        dynamic_scenarios=(freearray.build_avoid_return_scenario(),),
    )

    case_summary_path = args.outdir / "case_summary.csv"
    summary_df = load_case_rows(case_summary_path)
    report_text = build_report(summary_df)
    (args.outdir / "realistic_gate_report_ja.md").write_text(report_text, encoding="utf-8")

    summary_payload = {
        "realistic_min_cart_mass_kg": freearray.REALISTIC_MIN_CART_MASS_KG,
        "evaluations_per_case": int(args.evaluations_per_case),
        "population": int(args.population),
        "dynamic_replica_count": int(args.dynamic_replica_count),
        "dynamic_candidate_limit": int(args.dynamic_candidate_limit),
        "masses_kg": [float(value) for value in args.masses_kg],
        "magnet_layers": [int(value) for value in args.magnet_layers],
        "count_pairs": [[int(inner), int(outer)] for inner, outer in count_pairs],
        "best_case": summary_df.sort_values(["feasible", "ranking_score"], ascending=[False, False]).iloc[0].to_dict()
        if not summary_df.empty
        else None,
        "feasible_case_count": int(summary_df["feasible"].sum()) if not summary_df.empty else 0,
    }
    (args.outdir / "realistic_gate_summary.json").write_text(
        json.dumps(summary_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary_payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
