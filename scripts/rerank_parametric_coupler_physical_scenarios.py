"""Rerank parametric coupler checkpoints using physically derived force scenarios."""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np


GRAVITY_MPS2 = 9.80665
OPERATING_DISPLACEMENT_M = 0.006


@dataclass(frozen=True)
class ForceScenario:
    name: str
    cart_mass_kg: float
    desired_acceleration_mps2: float
    rolling_resistance_length_mm: float
    wheel_radius_mm: float
    slope_deg: float
    caster_swivel_force_n: float
    disturbance_force_n: float
    safety_factor: float
    evidence_scope: str

    def resistance_force_n(self):
        rolling = (
            self.cart_mass_kg
            * GRAVITY_MPS2
            * (self.rolling_resistance_length_mm / self.wheel_radius_mm)
        )
        grade = self.cart_mass_kg * GRAVITY_MPS2 * math.sin(math.radians(self.slope_deg))
        acceleration = self.cart_mass_kg * self.desired_acceleration_mps2
        subtotal = (
            rolling
            + grade
            + acceleration
            + self.caster_swivel_force_n
            + self.disturbance_force_n
        )
        return {
            "rolling_force_n": rolling,
            "grade_force_n": grade,
            "acceleration_force_n": acceleration,
            "required_force_n": self.safety_factor * subtotal,
            "required_stiffness_npm": self.safety_factor
            * subtotal
            / OPERATING_DISPLACEMENT_M,
        }


SCENARIOS = (
    ForceScenario(
        name="principle_demo_aligned_best_case",
        cart_mass_kg=10.0,
        desired_acceleration_mps2=0.0,
        rolling_resistance_length_mm=2.2,
        wheel_radius_mm=76.5,
        slope_deg=0.0,
        caster_swivel_force_n=0.0,
        disturbance_force_n=0.0,
        safety_factor=1.0,
        evidence_scope=(
            "Best reported hard-rubber/smooth-concrete rolling-resistance length, "
            "153 mm wheel diameter, aligned constant-speed lower bound."
        ),
    ),
    ForceScenario(
        name="smooth_corridor_aligned",
        cart_mass_kg=10.0,
        desired_acceleration_mps2=0.10,
        rolling_resistance_length_mm=2.4,
        wheel_radius_mm=50.0,
        slope_deg=0.0,
        caster_swivel_force_n=0.0,
        disturbance_force_n=0.0,
        safety_factor=1.20,
        evidence_scope=(
            "Reported tile rolling-resistance length and 100 mm wheel diameter; "
            "acceleration and safety factor are explicit engineering assumptions."
        ),
    ),
    ForceScenario(
        name="facility_robust_without_swivel",
        cart_mass_kg=10.0,
        desired_acceleration_mps2=0.20,
        rolling_resistance_length_mm=4.5,
        wheel_radius_mm=50.0,
        slope_deg=1.0,
        caster_swivel_force_n=0.0,
        disturbance_force_n=0.0,
        safety_factor=1.25,
        evidence_scope=(
            "Reported industrial-carpet rolling-resistance length and 100 mm wheel "
            "diameter. This still excludes unmeasured caster swivel resistance."
        ),
    ),
)


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    return parser.parse_args()


def load_candidates(checkpoint_dir):
    candidates = []
    for path in checkpoint_dir.glob("parametric_checkpoint_*.json"):
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            row = dict(row)
            row["source_checkpoint"] = str(path)
            candidates.append(row)
    if not candidates:
        raise FileNotFoundError(f"No checkpoint candidates found in {checkpoint_dir}")
    return candidates


def minimum_inner_radius_m(candidate):
    points = np.asarray(
        candidate["decoded_design"]["inner_support_points_xy_m"], dtype=float
    )
    return float(np.min(np.linalg.norm(points, axis=1)))


def base_gate_checks(candidate):
    return {
        "positive_definite": float(candidate["finite_min_scaled_eig"]) >= 1.0e-4,
        "minimum_translation_force": float(candidate["finite_min_translation_force_n"])
        >= 0.5,
        "minimum_yaw_torque": float(candidate["finite_min_yaw_torque_nm"]) >= 0.005,
        "no_negative_translation_restore": int(candidate["finite_negative_restore_count"])
        == 0,
        "no_negative_yaw_restore": int(candidate["finite_negative_yaw_count"]) == 0,
        "minimum_clearance": float(candidate["finite_min_pose_clearance_m"]) >= 0.003,
        "package_fit": float(candidate["finite_package_violation_m"]) <= 0.0,
        "minimum_inner_radius": minimum_inner_radius_m(candidate) >= 0.024,
        "minimum_site_spacing": float(candidate["finite_min_site_spacing_m"]) >= 0.0145,
        "linearity": float(candidate["finite_worst_linearity_r2"]) >= 0.75,
        "orthogonal_leakage": float(candidate["finite_mean_orthogonal_ratio"]) <= 0.10,
        "conditioning": float(candidate["finite_condition_number"]) <= 80.0,
        "center_bias": float(candidate["finite_center_scaled_wrench_norm"]) <= 8.0e-5,
        "yaw_torque_at_18deg": float(candidate["finite_min_yaw_torque_18deg_nm"])
        >= 0.18,
    }


def rerank(candidates, scenario):
    requirement = scenario.resistance_force_n()
    rows = []
    for candidate in candidates:
        base_checks = base_gate_checks(candidate)
        force_ratio = float(candidate["finite_min_force_6mm_n"]) / requirement[
            "required_force_n"
        ]
        stiffness_ratio = float(
            candidate["finite_min_directional_stiffness_npm"]
        ) / requirement["required_stiffness_npm"]
        checks = {
            **base_checks,
            "scenario_force": force_ratio >= 1.0,
            "scenario_stiffness": stiffness_ratio >= 1.0,
        }
        row = {
            "scenario": scenario.name,
            "config": candidate["config"],
            "generation": int(candidate["generation"]),
            "evaluation": int(candidate["evaluation"]),
            "inner_count": int(candidate["inner_count"]),
            "outer_count": int(candidate["outer_count"]),
            "layers": int(candidate["layers"]),
            "base_gate_count": int(sum(base_checks.values())),
            "scenario_gate_count": int(sum(checks.values())),
            "scenario_feasible": int(all(checks.values())),
            "required_force_n": requirement["required_force_n"],
            "candidate_force_6mm_n": float(candidate["finite_min_force_6mm_n"]),
            "force_margin_n": float(candidate["finite_min_force_6mm_n"])
            - requirement["required_force_n"],
            "force_ratio": force_ratio,
            "required_stiffness_npm": requirement["required_stiffness_npm"],
            "candidate_stiffness_npm": float(
                candidate["finite_min_directional_stiffness_npm"]
            ),
            "stiffness_margin_npm": float(
                candidate["finite_min_directional_stiffness_npm"]
            )
            - requirement["required_stiffness_npm"],
            "stiffness_ratio": stiffness_ratio,
            "minimum_clearance_mm": 1000.0
            * float(candidate["finite_min_pose_clearance_m"]),
            "minimum_eigenvalue": float(candidate["finite_min_scaled_eig"]),
            "finite_search_utility": float(candidate["finite_search_utility"]),
            "source_checkpoint": candidate["source_checkpoint"],
        }
        rows.append(row)
    rows.sort(
        key=lambda row: (
            row["scenario_feasible"],
            row["scenario_gate_count"],
            min(row["force_ratio"], row["stiffness_ratio"]),
            row["finite_search_utility"],
        ),
        reverse=True,
    )
    return requirement, rows


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main():
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    candidates = load_candidates(args.checkpoint_dir)
    summary = {
        "candidate_count": len(candidates),
        "operating_displacement_mm": 1000.0 * OPERATING_DISPLACEMENT_M,
        "formula": (
            "F_req = safety_factor * (m*a + m*g*b/r + m*g*sin(slope) "
            "+ caster_swivel_force + disturbance_force)"
        ),
        "scenarios": [],
        "source": (
            "Al-Eisawi et al., Factors affecting minimum push and pull forces "
            "of manual carts, Applied Ergonomics 30 (1999) 235-245."
        ),
    }
    for scenario in SCENARIOS:
        requirement, rows = rerank(candidates, scenario)
        write_csv(args.outdir / f"{scenario.name}.csv", rows)
        summary["scenarios"].append(
            {
                "inputs": asdict(scenario),
                "derived": requirement,
                "feasible_candidate_count": int(
                    sum(row["scenario_feasible"] for row in rows)
                ),
                "best_candidate": rows[0],
            }
        )
    (args.outdir / "physical_scenario_rerank_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
