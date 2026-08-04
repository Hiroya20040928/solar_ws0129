import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_hifi as hifi


FIXED_SKU = "DAISO_SUPER_13MM_4P"
DT_S = 0.06

CRITERIA_PROFILES = {
    "strict": {
        "no_contact_total": 0,
        "no_latch_total": 0,
        "min_clearance_mm": 1.0,
        "max_cruise_translation_rms_mm": 5.0,
        "max_cruise_yaw_rms_deg": 1.8,
        "min_turn_signal_ratio": 0.35,
        "min_sensor_peak_n": hifi.SENSOR_MIN_DETECT_FORCE_N,
        "max_mean_orthogonal_ratio": 0.10,
        "max_mean_forward_torque_ratio": 0.055,
        "max_negative_yaw_restore_count": 0,
        "max_negative_towed_yaw_restore_count": 0,
        "max_nominal_tow_offset_proxy_mm": 8.0,
        "max_reduced_tow_offset_proxy_mm": 20.0,
        "min_stiffness_modulation_ratio": 1.20,
        "max_package_violation_mm": 0.0,
    },
    "relaxed_dynamic": {
        "no_contact_total": 0,
        "no_latch_total": 0,
        "min_clearance_mm": 0.0,
        "max_cruise_translation_rms_mm": 12.0,
        "max_cruise_yaw_rms_deg": 5.0,
        "min_turn_signal_ratio": 0.10,
        "min_sensor_peak_n": 0.25,
        "max_package_violation_mm": 0.0,
    },
    "existence": {
        "no_latch_total": 0,
        "min_clearance_mm": 0.0,
        "min_turn_signal_ratio": 0.03,
        "min_sensor_peak_n": 0.15,
        "max_package_violation_mm": 0.0,
    },
}

SCENARIO_PROFILES = {
    "full_validation": {
        "scenario_prefixes": None,
        "replica_count": hifi.DYNAMIC_VALIDATION_ENV_REPLICAS,
        "description": "All validation scenarios with perturbed environments.",
    },
    "nominal_validation": {
        "scenario_prefixes": None,
        "replica_count": 1,
        "description": "All validation scenarios, nominal environment only.",
    },
    "minimal_turn_nominal": {
        "scenario_prefixes": ("gentle_arc_",),
        "replica_count": 1,
        "description": "Only the gentle-arc turn scenario, nominal environment only.",
    },
    "minimal_two_nominal": {
        "scenario_prefixes": ("gentle_arc_", "translation_turn_"),
        "replica_count": 1,
        "description": "Gentle arc and translation-turn only, nominal environment only.",
    },
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run a low-mass feasibility scan for the DAISO 13 mm magnetic coupler design space."
    )
    parser.add_argument(
        "--masses-kg",
        type=float,
        nargs="+",
        default=[0.25, 0.5, 0.75, 1.0],
        help="Fixed cart masses to test [kg].",
    )
    parser.add_argument("--seed", type=int, default=91000)
    parser.add_argument("--outdir", type=Path, default=ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_lowmass_scan_20260701")
    parser.add_argument("--design-population", type=int, default=4)
    parser.add_argument("--design-generations", type=int, default=4)
    parser.add_argument("--design-max-evaluations", type=int, default=20)
    parser.add_argument("--policy-population", type=int, default=4)
    parser.add_argument("--policy-generations", type=int, default=2)
    parser.add_argument("--search-samples", type=int, default=48)
    parser.add_argument("--validation-samples", type=int, default=64)
    parser.add_argument("--coarse-presearch-trials", type=int, default=8)
    parser.add_argument(
        "--criteria-profile",
        type=str,
        choices=tuple(CRITERIA_PROFILES.keys()),
        default="strict",
        help="Acceptance criteria profile.",
    )
    parser.add_argument(
        "--validation-profile",
        type=str,
        choices=tuple(SCENARIO_PROFILES.keys()),
        default="full_validation",
        help="Validation scenario / environment profile.",
    )
    parser.add_argument(
        "--shape-family-mode",
        type=str,
        choices=("both", "flex", "arrow"),
        default="both",
    )
    parser.add_argument(
        "--design-optimizer",
        type=str,
        choices=("cmaes", "cem"),
        default="cmaes",
    )
    parser.add_argument(
        "--stop-on-first-pass",
        action="store_true",
        help="Stop as soon as one case satisfies the selected profile.",
    )
    return parser.parse_args()


def select_validation_scenarios(seed, validation_profile):
    profile = SCENARIO_PROFILES[validation_profile]
    scenarios = hifi.filter_validation_scenarios(seed, DT_S)
    prefixes = profile["scenario_prefixes"]
    if prefixes is None:
        return scenarios
    return [scenario for scenario in scenarios if scenario.name.startswith(prefixes)]


def evaluate_case(
    mass_kg: float,
    mass_index: int,
    args,
):
    candidate, history_df, archive_df, archive_map = hifi.optimize_design(
        seed=args.seed + 100 * mass_index,
        generations=args.design_generations,
        population=args.design_population,
        elite_count=2,
        num_samples=args.search_samples,
        fixed_sku_id=FIXED_SKU,
        fixed_cart_mass_kg=mass_kg,
        shape_family_mode=args.shape_family_mode,
        max_evaluations=args.design_max_evaluations,
        min_generations=2,
        stall_generations=3,
        coarse_presearch_trials=args.coarse_presearch_trials,
        coarse_presearch_samples=24,
        archive_limit=20,
        design_optimizer=args.design_optimizer,
    )
    validated_best, validated_df = hifi.refine_design_archive_validation(
        archive_map=archive_map,
        num_samples=args.validation_samples,
        catalog=hifi.resolve_catalog(FIXED_SKU),
        fixed_cart_mass_kg=mass_kg,
        shape_family_mode=args.shape_family_mode,
        seed=args.seed + 1000 + 100 * mass_index,
        refine_generations=1,
        refine_population=4,
        refine_elite_count=2,
    )
    design = validated_best["design"]
    geometry = hifi.build_geometry_from_shape(
        design.shape_parameters,
        design.mean_radius_m,
        design.gap_m,
        args.validation_samples,
    )
    policy_candidate, policy_history_df = hifi.optimize_policy(
        design=design,
        geometry=geometry,
        seed=args.seed + 2000 + 100 * mass_index,
        generations=args.policy_generations,
        population=args.policy_population,
        elite_count=2,
        dt_s=DT_S,
        replica_count=hifi.DYNAMIC_SEARCH_ENV_REPLICAS,
        substeps=hifi.DYNAMIC_SEARCH_SUBSTEPS,
    )
    refined_design, refined_geometry, gap_refinement_df = hifi.refine_gap_after_policy(
        design,
        policy_candidate["policy"],
        seed=args.seed + 3000 + 100 * mass_index,
        num_samples=args.validation_samples,
    )
    if abs(refined_design.gap_m - design.gap_m) > 1.0e-6:
        design = refined_design
        geometry = refined_geometry
        policy_candidate, policy_history_df = hifi.optimize_policy(
            design=design,
            geometry=geometry,
            seed=args.seed + 4000 + 100 * mass_index,
            generations=args.policy_generations,
            population=args.policy_population,
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
    scenarios = select_validation_scenarios(args.seed + 5000 + 100 * mass_index, args.validation_profile)
    replica_count = SCENARIO_PROFILES[args.validation_profile]["replica_count"]
    dynamic_outcomes = []
    for scenario in scenarios:
        environments = hifi.build_episode_environments(
            design,
            scenario.name,
            seed=args.seed + 6000 + 100 * mass_index,
            replica_count=replica_count,
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
    case = {
        "mass_case_kg": mass_kg,
        "shape_label": hifi.shape_name(design.shape_parameters),
        "shape_family": design.shape_parameters.family,
        "gap_mm": 1000.0 * design.gap_m,
        "mean_radius_mm": 1000.0 * design.mean_radius_m,
        "magnets_per_ring": design.magnets_per_ring,
        "magnet_layers": design.magnet_layers,
        "total_magnets": design.total_magnets,
        "cost_jpy": design.estimated_total_cost_jpy,
        "static_constraint_violation": float(np.sum(np.maximum(hifi.static_constraint_values(static_assessment), 0.0))),
        "mean_orthogonal_ratio": static_assessment.mean_orthogonal_ratio,
        "mean_forward_torque_ratio": static_assessment.mean_forward_torque_ratio,
        "negative_yaw_restore_count": static_assessment.negative_yaw_restore_count,
        "negative_towed_yaw_restore_count": static_assessment.negative_towed_yaw_restore_count,
        "nominal_tow_offset_proxy_mm": 1000.0 * static_assessment.nominal_tow_offset_proxy_m,
        "reduced_tow_offset_proxy_mm": 1000.0 * static_assessment.reduced_tow_offset_proxy_m,
        "stiffness_modulation_ratio": static_assessment.stiffness_modulation_ratio,
        "package_violation_mm": 1000.0 * static_assessment.package_violation_m,
        "dynamic_mean_score": float(dynamic_df["score"].mean()),
        "dynamic_worst_score": float(dynamic_df["score"].min()),
        "dynamic_contact_events_total": int(dynamic_df["contact_events"].sum()),
        "dynamic_latched_total": int(dynamic_df["latched"].sum()),
        "worst_clearance_mm": float(dynamic_df["min_clearance_mm"].min()),
        "max_contact_demand_mm": float(dynamic_df["max_contact_demand_mm"].max()),
        "mean_turn_signal_ratio": float(dynamic_df["turn_signal_ratio"].mean()),
        "mean_turn_latency_s": float(dynamic_df["turn_latency_s"].mean()),
        "mean_recenter_s": float(dynamic_df["recenter_s"].mean()),
        "mean_cue_peak_yaw_deg": float(dynamic_df["cue_peak_yaw_deg"].mean()),
        "mean_cue_peak_translation_mm": float(dynamic_df["cue_peak_translation_mm"].mean()),
        "mean_sensor_peak_n": float(dynamic_df["sensor_peak_n"].mean()),
        "mean_height_return_s": float(dynamic_df["height_return_s"].mean()),
        "mean_cruise_translation_rms_mm": float(dynamic_df["cruise_translation_rms_mm"].mean()),
        "mean_cruise_yaw_rms_deg": float(dynamic_df["cruise_yaw_rms_deg"].mean()),
        "search_history_rows": int(len(history_df)),
        "policy_history_rows": int(len(policy_history_df)),
        "validated_candidate_count": int(len(validated_df)),
        "criteria_profile": args.criteria_profile,
        "validation_profile": args.validation_profile,
        "validation_scenario_count": int(len(scenarios)),
        "validation_environment_count": int(replica_count),
    }
    return case


def evaluate_requirements(case, criteria):
    checks = {}
    if "no_contact_total" in criteria:
        checks["no_contact"] = int(case["dynamic_contact_events_total"] <= criteria["no_contact_total"])
    if "no_latch_total" in criteria:
        checks["no_latch"] = int(case["dynamic_latched_total"] <= criteria["no_latch_total"])
    if "min_clearance_mm" in criteria:
        checks["clearance_margin_ok"] = int(case["worst_clearance_mm"] >= criteria["min_clearance_mm"])
    if "max_cruise_translation_rms_mm" in criteria:
        checks["cruise_translation_ok"] = int(
            case["mean_cruise_translation_rms_mm"] <= criteria["max_cruise_translation_rms_mm"]
        )
    if "max_cruise_yaw_rms_deg" in criteria:
        checks["cruise_yaw_ok"] = int(case["mean_cruise_yaw_rms_deg"] <= criteria["max_cruise_yaw_rms_deg"])
    if "min_turn_signal_ratio" in criteria:
        checks["turn_signal_ok"] = int(case["mean_turn_signal_ratio"] >= criteria["min_turn_signal_ratio"])
    if "min_sensor_peak_n" in criteria:
        checks["sensor_ok"] = int(case["mean_sensor_peak_n"] >= criteria["min_sensor_peak_n"])
    if "max_mean_orthogonal_ratio" in criteria:
        checks["orthogonal_ratio_ok"] = int(case["mean_orthogonal_ratio"] <= criteria["max_mean_orthogonal_ratio"])
    if "max_mean_forward_torque_ratio" in criteria:
        checks["forward_torque_ok"] = int(
            case["mean_forward_torque_ratio"] <= criteria["max_mean_forward_torque_ratio"]
        )
    if "max_negative_yaw_restore_count" in criteria:
        checks["yaw_restore_ok"] = int(
            case["negative_yaw_restore_count"] <= criteria["max_negative_yaw_restore_count"]
        )
    if "max_negative_towed_yaw_restore_count" in criteria:
        checks["towed_yaw_restore_ok"] = int(
            case["negative_towed_yaw_restore_count"] <= criteria["max_negative_towed_yaw_restore_count"]
        )
    if "max_nominal_tow_offset_proxy_mm" in criteria:
        checks["nominal_tow_offset_ok"] = int(
            case["nominal_tow_offset_proxy_mm"] <= criteria["max_nominal_tow_offset_proxy_mm"]
        )
    if "max_reduced_tow_offset_proxy_mm" in criteria:
        checks["reduced_tow_offset_ok"] = int(
            case["reduced_tow_offset_proxy_mm"] <= criteria["max_reduced_tow_offset_proxy_mm"]
        )
    if "min_stiffness_modulation_ratio" in criteria:
        checks["stiffness_modulation_ok"] = int(
            case["stiffness_modulation_ratio"] >= criteria["min_stiffness_modulation_ratio"]
        )
    if "max_package_violation_mm" in criteria:
        checks["package_ok"] = int(case["package_violation_mm"] <= criteria["max_package_violation_mm"])
    checks["profile_pass"] = int(all(checks.values()))
    return checks


def selection_score(case):
    return (
        200.0 * case.get("profile_pass", 0)
        + 20.0 * case.get("no_contact", 0)
        + 20.0 * case.get("no_latch", 0)
        + 10.0 * case.get("clearance_margin_ok", 0)
        + 10.0 * case.get("cruise_translation_ok", 0)
        + 10.0 * case.get("cruise_yaw_ok", 0)
        + 10.0 * case.get("turn_signal_ok", 0)
        + 10.0 * case.get("sensor_ok", 0)
        + case["dynamic_mean_score"] / 100.0
        - case["static_constraint_violation"] / 1000.0
    )


def main():
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    criteria = CRITERIA_PROFILES[args.criteria_profile]
    rows = []

    for mass_index, mass_kg in enumerate(args.masses_kg):
        case = evaluate_case(mass_kg=mass_kg, mass_index=mass_index, args=args)
        case.update(evaluate_requirements(case, criteria))
        case["selection_score"] = selection_score(case)
        rows.append(case)

        pd.DataFrame(rows).sort_values(
            ["profile_pass", "selection_score"],
            ascending=[False, False],
        ).to_csv(args.outdir / "lowmass_scan.csv", index=False)
        (args.outdir / f"case_{str(mass_kg).replace('.', 'p')}kg.json").write_text(
            json.dumps(case, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(json.dumps(case, ensure_ascii=False))
        if args.stop_on_first_pass and case["profile_pass"]:
            break

    results_df = pd.DataFrame(rows).sort_values(
        ["profile_pass", "selection_score"],
        ascending=[False, False],
    )
    summary = {
        "fixed_sku": FIXED_SKU,
        "criteria_profile": args.criteria_profile,
        "criteria": criteria,
        "validation_profile": args.validation_profile,
        "validation_profile_description": SCENARIO_PROFILES[args.validation_profile]["description"],
        "mass_values_kg": list(args.masses_kg),
        "profile_pass_count": int(results_df["profile_pass"].sum()),
        "best_case": results_df.iloc[0].to_dict() if len(results_df) else None,
    }
    (args.outdir / "lowmass_scan_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("SUMMARY")
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
