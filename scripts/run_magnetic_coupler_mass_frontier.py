import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\user\OneDrive - 和歌山大学\ソーラー\エネマネ\solar_ws0129-main")

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_hifi as hifi


OUTDIR = ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_mass_frontier_20260701"
FIXED_SKU = "DAISO_SUPER_13MM_4P"
DT_S = 0.06
MASS_VALUES_KG = [4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 18.0]
BASE_SEED_LATENTS = [
    np.asarray(
        [
            1.3562196360418264,
            0.1135372863707671,
            0.9012066578026234,
            0.215138952474892,
            0.16136140401487548,
            0.3592073703237301,
            0.07474521738071835,
            -0.03234337390623129,
            -3.0357456129401164,
            2.6658032839587844,
            -0.9303862999219149,
            -0.8819344419027864,
            -1.5859289561895347,
            -0.43612498517740156,
            -0.48531824647520727,
            0.49866488372437945,
            0.5483019542723917,
            0.44067539004549117,
            -3.0916601764587783,
            -0.8512572693148229,
            0.17461269380322428,
            -0.07505444571791536,
        ],
        dtype=float,
    ),
    np.asarray(
        [
            0.012854820034108976,
            1.129779154058152,
            -1.040861605440401,
            3.7355521171454367,
            -3.9145288927007797,
            -4.426172190909862,
            1.620381415480971,
            -2.914651754436672,
            -1.4319574206647787,
            1.6049013373946242,
            -1.3424788586990224,
            1.330108174584337,
            3.845027382287891,
            0.5681941337781141,
            -2.2572944392714227,
            -0.9642526969149667,
            2.737977437848517,
            0.7570258943791741,
            -0.6779635530470121,
            -4.614472484123461,
            3.5105406062366007,
            0.27673703206052563,
        ],
        dtype=float,
    ),
    np.zeros(hifi.design_variable_count("arrow"), dtype=float),
]


def summarize_dynamic_outcomes(dynamic_df: pd.DataFrame):
    return {
        "dynamic_mean_score": float(dynamic_df["score"].mean()),
        "dynamic_worst_score": float(dynamic_df["score"].min()),
        "dynamic_contact_events_total": int(dynamic_df["contact_events"].sum()),
        "dynamic_latched_total": int(dynamic_df["latched"].sum()),
        "worst_clearance_mm": float(dynamic_df["min_clearance_mm"].min()),
        "max_contact_demand_mm": float(dynamic_df["max_contact_demand_mm"].max()),
        "mean_cue_peak_yaw_deg": float(dynamic_df["cue_peak_yaw_deg"].mean()),
        "mean_cue_peak_translation_mm": float(dynamic_df["cue_peak_translation_mm"].mean()),
        "mean_sensor_peak_n": float(dynamic_df["sensor_peak_n"].mean()),
        "mean_height_shift_peak_mm": float(dynamic_df["height_shift_peak_mm"].mean()),
        "mean_height_return_s": float(dynamic_df["height_return_s"].mean()),
        "mean_cruise_translation_rms_mm": float(dynamic_df["cruise_translation_rms_mm"].mean()),
        "mean_cruise_yaw_rms_deg": float(dynamic_df["cruise_yaw_rms_deg"].mean()),
    }


def feasibility_flags(dynamic_summary: dict):
    return {
        "no_contact": int(dynamic_summary["dynamic_contact_events_total"] == 0),
        "no_latch": int(dynamic_summary["dynamic_latched_total"] == 0),
        "clearance_margin_ok": int(dynamic_summary["worst_clearance_mm"] >= 1.0),
        "cruise_translation_ok": int(dynamic_summary["mean_cruise_translation_rms_mm"] <= 5.0),
        "cruise_yaw_ok": int(dynamic_summary["mean_cruise_yaw_rms_deg"] <= 1.8),
        "cue_yaw_ok": int(dynamic_summary["mean_cue_peak_yaw_deg"] >= 0.5),
        "sensor_ok": int(dynamic_summary["mean_sensor_peak_n"] >= 1.0),
    }


def feasibility_score(dynamic_summary: dict):
    flags = feasibility_flags(dynamic_summary)
    return (
        50.0 * flags["no_contact"]
        + 50.0 * flags["no_latch"]
        + 20.0 * flags["clearance_margin_ok"]
        + 20.0 * flags["cruise_translation_ok"]
        + 20.0 * flags["cruise_yaw_ok"]
        + 20.0 * flags["cue_yaw_ok"]
        + 20.0 * flags["sensor_ok"]
        + dynamic_summary["dynamic_mean_score"] / 100.0
    )


def evaluate_full_pipeline(latent_vector: np.ndarray, fixed_cart_mass_kg: float, seed: int):
    catalog = hifi.resolve_catalog(FIXED_SKU)
    design_candidate = hifi.evaluate_design_candidate_validation(
        latent_vector=latent_vector,
        num_samples=128,
        catalog=catalog,
        fixed_cart_mass_kg=fixed_cart_mass_kg,
        shape_family_mode="arrow",
    )
    design = design_candidate["design"]
    geometry = hifi.build_geometry_from_shape(
        design.shape_parameters,
        design.mean_radius_m,
        design.gap_m,
        96,
    )
    policy_candidate, policy_history_df = hifi.optimize_policy(
        design=design,
        geometry=geometry,
        seed=seed,
        generations=6,
        population=6,
        elite_count=2,
        dt_s=DT_S,
        replica_count=hifi.DYNAMIC_SEARCH_ENV_REPLICAS,
        substeps=hifi.DYNAMIC_SEARCH_SUBSTEPS,
    )
    refined_design, refined_geometry, gap_refinement_df = hifi.refine_gap_after_policy(
        design,
        policy_candidate["policy"],
        seed=seed,
        num_samples=96,
    )
    if abs(refined_design.gap_m - design.gap_m) > 1.0e-6:
        design = refined_design
        geometry = refined_geometry
        policy_candidate, policy_history_df = hifi.optimize_policy(
            design=design,
            geometry=geometry,
            seed=seed + 1000,
            generations=6,
            population=6,
            elite_count=2,
            dt_s=DT_S,
            replica_count=hifi.DYNAMIC_SEARCH_ENV_REPLICAS,
            substeps=hifi.DYNAMIC_SEARCH_SUBSTEPS,
        )

    model = hifi.build_array_model(design, geometry, hifi.VALIDATION_DIPOLE_GRID)
    static_assessment = hifi.assess_static_design(
        model,
        directions=np.linspace(0.0, 2.0 * np.pi, 16, endpoint=False),
        displacements_m=hifi.VALIDATION_DISPLACEMENTS_M,
        height_fractions=np.linspace(0.0, 0.95, 6),
        yaw_samples_rad=hifi.VALIDATION_YAW_RAD,
    )
    dynamic_outcomes = []
    scenarios = hifi.filter_validation_scenarios(seed, DT_S)
    for scenario in scenarios:
        environments = hifi.build_episode_environments(
            design,
            scenario.name,
            seed=seed + 14000,
            replica_count=hifi.DYNAMIC_VALIDATION_ENV_REPLICAS,
        )
        for environment in environments:
            dynamic_outcomes.append(
                hifi.simulate_dynamic_episode(
                    model,
                    policy_candidate["policy"],
                    scenario,
                    environment=environment,
                    record=False,
                    substeps=hifi.DYNAMIC_VALIDATION_SUBSTEPS,
                )
            )
    dynamic_df = hifi.report_dynamic_dataframe(dynamic_outcomes)
    summary = summarize_dynamic_outcomes(dynamic_df)
    summary["feasibility_score"] = feasibility_score(summary)
    summary.update(feasibility_flags(summary))
    return {
        "design": design,
        "static_assessment": static_assessment,
        "policy": policy_candidate["policy"],
        "policy_score": float(policy_candidate["score"]),
        "policy_history_rows": int(len(policy_history_df)),
        "gap_refinement_df": gap_refinement_df,
        "dynamic_df": dynamic_df,
        "dynamic_summary": summary,
        "latent_vector": np.asarray(latent_vector, dtype=float).copy(),
    }


def run_mass_case(fixed_cart_mass_kg: float, mass_index: int):
    archives = {}
    best_search = None
    search_rows = []
    for seed_index, initial_mean in enumerate(BASE_SEED_LATENTS):
        candidate, history_df, archive_df, archive_map = hifi.optimize_design(
            seed=81000 + 1000 * mass_index + 50 * seed_index,
            generations=5,
            population=5,
            elite_count=2,
            num_samples=72,
            fixed_sku_id=FIXED_SKU,
            fixed_cart_mass_kg=fixed_cart_mass_kg,
            shape_family_mode="arrow",
            max_evaluations=30,
            min_generations=4,
            stall_generations=4,
            coarse_presearch_trials=0,
            archive_limit=12,
            initial_mean=initial_mean,
            initial_std=np.ones_like(initial_mean) * 0.55,
        )
        search_rows.append(
            {
                "seed_index": seed_index,
                "best_search_score": float(candidate["score"]),
                "history_rows": int(len(history_df)),
                "archive_size": int(len(archive_map)),
            }
        )
        if best_search is None or candidate["score"] > best_search["score"]:
            best_search = candidate
        for signature, payload in archive_map.items():
            existing = archives.get(signature)
            if existing is None or payload["score"] > existing["score"]:
                archives[signature] = payload

    validated_best, validated_df = hifi.refine_design_archive_validation(
        archive_map=archives,
        num_samples=128,
        catalog=hifi.resolve_catalog(FIXED_SKU),
        fixed_cart_mass_kg=fixed_cart_mass_kg,
        shape_family_mode="arrow",
        seed=86000 + 1000 * mass_index,
        refine_generations=3,
        refine_population=5,
        refine_elite_count=2,
    )
    full_result = evaluate_full_pipeline(
        latent_vector=np.asarray(validated_best["latent_vector"], dtype=float),
        fixed_cart_mass_kg=fixed_cart_mass_kg,
        seed=90000 + 1000 * mass_index,
    )
    design = full_result["design"]
    static_assessment = full_result["static_assessment"]
    dynamic_summary = full_result["dynamic_summary"]
    return {
        "mass_case_kg": fixed_cart_mass_kg,
        "search_rows": search_rows,
        "validated_candidate_count": int(len(validated_df)),
        "shape_label": hifi.shape_name(design.shape_parameters),
        "shape_family": design.shape_parameters.family,
        "gap_mm": 1000.0 * float(design.gap_m),
        "mean_radius_mm": 1000.0 * float(design.mean_radius_m),
        "magnets_per_ring": int(design.magnets_per_ring),
        "magnet_layers": int(design.magnet_layers),
        "total_magnets": int(design.total_magnets),
        "cost_jpy": float(design.estimated_total_cost_jpy),
        "static_validation_score": float(static_assessment.score),
        "mean_orthogonal_ratio": float(static_assessment.mean_orthogonal_ratio),
        "mean_forward_torque_ratio": float(static_assessment.mean_forward_torque_ratio),
        "negative_yaw_restore_count": int(static_assessment.negative_yaw_restore_count),
        "negative_towed_yaw_restore_count": int(static_assessment.negative_towed_yaw_restore_count),
        "nominal_tow_offset_proxy_mm": 1000.0 * float(static_assessment.nominal_tow_offset_proxy_m),
        "reduced_tow_offset_proxy_mm": 1000.0 * float(static_assessment.reduced_tow_offset_proxy_m),
        "stiffness_modulation_ratio": float(static_assessment.stiffness_modulation_ratio),
        "policy_score": float(full_result["policy_score"]),
        **dynamic_summary,
        "latent_vector": json.dumps(full_result["latent_vector"].tolist()),
        "policy": json.dumps(asdict(full_result["policy"]), ensure_ascii=False),
    }


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTDIR / "mass_frontier.csv"
    rows = []
    completed_masses = set()
    if csv_path.exists():
        existing_df = pd.read_csv(csv_path)
        rows = existing_df.to_dict("records")
        completed_masses = {float(value) for value in existing_df["mass_case_kg"].tolist()}
    for mass_index, fixed_cart_mass_kg in enumerate(MASS_VALUES_KG):
        if float(fixed_cart_mass_kg) in completed_masses:
            continue
        row = run_mass_case(fixed_cart_mass_kg=fixed_cart_mass_kg, mass_index=mass_index)
        rows.append(row)
        pd.DataFrame(rows).to_csv(csv_path, index=False)

    frontier_df = pd.DataFrame(rows).sort_values(
        by=[
            "no_contact",
            "no_latch",
            "clearance_margin_ok",
            "cue_yaw_ok",
            "sensor_ok",
            "cruise_translation_ok",
            "cruise_yaw_ok",
            "feasibility_score",
        ],
        ascending=[False, False, False, False, False, False, False, False],
    ).reset_index(drop=True)
    frontier_df.to_csv(OUTDIR / "mass_frontier_ranked.csv", index=False)

    feasible_df = frontier_df[
        (frontier_df["no_contact"] == 1)
        & (frontier_df["no_latch"] == 1)
        & (frontier_df["clearance_margin_ok"] == 1)
        & (frontier_df["cruise_translation_ok"] == 1)
        & (frontier_df["cruise_yaw_ok"] == 1)
        & (frontier_df["cue_yaw_ok"] == 1)
        & (frontier_df["sensor_ok"] == 1)
    ].copy()
    feasible_df.to_csv(OUTDIR / "mass_frontier_feasible_only.csv", index=False)

    summary = {
        "fixed_sku": FIXED_SKU,
        "mass_values_kg": MASS_VALUES_KG,
        "feasible_case_count": int(len(feasible_df)),
        "max_feasible_mass_kg": float(feasible_df["mass_case_kg"].max()) if not feasible_df.empty else None,
        "best_ranked_case": frontier_df.iloc[0].to_dict() if not frontier_df.empty else None,
    }
    (OUTDIR / "mass_frontier_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
