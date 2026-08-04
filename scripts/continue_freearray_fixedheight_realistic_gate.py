import argparse
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_freearray_fixedheight as freearray


def parse_args():
    parser = argparse.ArgumentParser(
        description="Continue the fixed-height free-array realistic-gate search from an existing best-case JSON."
    )
    parser.add_argument("--source-json", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260705)
    parser.add_argument("--restarts", type=int, default=4)
    parser.add_argument("--evaluations", type=int, default=24)
    parser.add_argument("--population", type=int, default=6)
    parser.add_argument("--dynamic-replica-count", type=int, default=1)
    parser.add_argument("--dynamic-candidate-limit", type=int, default=1)
    parser.add_argument("--sigma-list", type=float, nargs="+", default=[0.18, 0.12, 0.08])
    return parser.parse_args()


def load_initial_latent(payload):
    latent = payload.get("latent_vector")
    if latent is not None:
        return np.asarray(latent, dtype=float)
    design = freearray.design_from_dict(payload["design"])
    return freearray.latent_from_design(design)


def row_from_result(restart_index, sigma0, candidate, outcomes):
    feasible, ranking_score = freearray.candidate_priority(candidate["static"], outcomes)
    return {
        "restart_index": int(restart_index),
        "sigma0": float(sigma0),
        "inner_count": int(candidate["design"].inner_count),
        "outer_count": int(candidate["design"].outer_count),
        "cart_mass_kg": float(candidate["design"].cart_mass_kg),
        "magnet_layers": int(candidate["design"].magnet_layers),
        "static_score": float(candidate["static"].score),
        "scaled_min_eigenvalue": float(np.min(candidate["static"].scaled_eigenvalues)),
        "mean_orthogonal_ratio": float(candidate["static"].mean_orthogonal_ratio),
        "negative_restore_count": int(candidate["static"].negative_restore_count),
        "negative_yaw_restore_count": int(candidate["static"].negative_yaw_restore_count),
        "bad_attraction_count": int(candidate["static"].bad_attraction_count),
        "feasible": int(feasible),
        "ranking_score": float(ranking_score),
        "worst_clearance_mm": float(min(outcome.min_clearance_mm for outcome in outcomes)),
        "max_penetration_mm": float(max(outcome.max_penetration_mm for outcome in outcomes)),
        "contact_events_total": int(sum(outcome.contact_events for outcome in outcomes)),
        "robot_hold_force_exceeded_total": int(sum(outcome.robot_hold_force_exceeded_count for outcome in outcomes)),
        "robot_hold_torque_exceeded_total": int(sum(outcome.robot_hold_torque_exceeded_count for outcome in outcomes)),
        "dynamic_clip_total": int(sum(outcome.dynamic_clip_count for outcome in outcomes)),
    }


def main():
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(args.source_json.read_text(encoding="utf-8"))
    initial_latent = load_initial_latent(payload)
    source_design = freearray.design_from_dict(payload["design"])

    rows = []
    best_bundle = None

    for restart_index in range(int(args.restarts)):
        sigma0 = float(args.sigma_list[restart_index % len(args.sigma_list)])
        run_outdir = args.outdir / f"restart_{restart_index:02d}"
        run_outdir.mkdir(parents=True, exist_ok=True)
        candidate, outcomes, history_df, case_df = freearray.optimize_case(
            outdir=run_outdir,
            inner_count=source_design.inner_count,
            outer_count=source_design.outer_count,
            cart_mass_kg=source_design.cart_mass_kg,
            magnet_layers=source_design.magnet_layers,
            seed=int(args.seed + 101 * restart_index),
            evaluations=int(args.evaluations),
            population=int(args.population),
            dynamic_replica_count=int(args.dynamic_replica_count),
            dynamic_scenarios=(freearray.build_avoid_return_scenario(),),
            dynamic_candidate_limit=int(args.dynamic_candidate_limit),
            initial_mean=initial_latent,
            sigma0=sigma0,
        )
        row = row_from_result(restart_index, sigma0, candidate, outcomes)
        rows.append(row)
        if best_bundle is None or (row["feasible"], row["ranking_score"]) > (
            best_bundle["row"]["feasible"],
            best_bundle["row"]["ranking_score"],
        ):
            best_bundle = {
                "row": row,
                "candidate": candidate,
                "outcomes": outcomes,
                "history_df": history_df,
                "case_df": case_df,
                "run_outdir": run_outdir,
            }

    results_df = pd.DataFrame(rows).sort_values(["feasible", "ranking_score"], ascending=[False, False])
    results_df.to_csv(args.outdir / "continuation_runs.csv", index=False)

    summary = {
        "source_json": str(args.source_json),
        "source_inner_count": int(source_design.inner_count),
        "source_outer_count": int(source_design.outer_count),
        "source_cart_mass_kg": float(source_design.cart_mass_kg),
        "source_magnet_layers": int(source_design.magnet_layers),
        "realistic_min_cart_mass_kg": float(freearray.REALISTIC_MIN_CART_MASS_KG),
        "restarts": int(args.restarts),
        "evaluations": int(args.evaluations),
        "population": int(args.population),
        "dynamic_replica_count": int(args.dynamic_replica_count),
        "dynamic_candidate_limit": int(args.dynamic_candidate_limit),
        "sigma_list": [float(value) for value in args.sigma_list],
        "best_restart": best_bundle["row"] if best_bundle is not None else None,
        "best_run_outdir": str(best_bundle["run_outdir"]) if best_bundle is not None else None,
    }
    (args.outdir / "continuation_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
