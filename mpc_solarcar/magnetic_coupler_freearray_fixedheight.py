import json
import math
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

try:
    import cma
except Exception:
    cma = None

try:
    import magpylib as magpy
except Exception:
    magpy = None

try:
    from tensorboardX import SummaryWriter
except Exception:
    SummaryWriter = None

matplotlib.use("Agg")

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_hifi as hifi
from mpc_solarcar import magnetic_coupler_rl as base

try:
    from mpc_solarcar.magnetic_coupler_freearray_video import render_fixedheight_corridor_video
except Exception:
    render_fixedheight_corridor_video = None


MU0 = base.MU0
REFERENCE_TRANSLATION_M = 0.005
REFERENCE_YAW_RAD = math.radians(10.0)
DEFAULT_SEARCH_DISPLACEMENTS_M = np.array([0.002, 0.004, 0.006], dtype=float)
DEFAULT_SEARCH_YAW_RAD = np.radians(np.array([2.0, 4.0, 8.0, 12.0, 18.0], dtype=float))
DEFAULT_DIRECTIONS_RAD = np.linspace(0.0, 2.0 * math.pi, 16, endpoint=False)
FAST_SEARCH_DISPLACEMENTS_M = np.array([0.003, 0.006], dtype=float)
FAST_SEARCH_YAW_RAD = np.radians(np.array([4.0, 10.0], dtype=float))
FAST_DIRECTIONS_RAD = np.linspace(0.0, 2.0 * math.pi, 8, endpoint=False)
CONTACT_MARGIN_M = 1.0e-5
FIXED_HEIGHT_SHIFT_M = 0.0
FIXED_SKU_ID = "DAISO_SUPER_13MM_4P"
MAX_CART_SPEED_MPS = 0.85
MAX_CART_YAW_RATE_RADPS = math.radians(90.0)
MAX_CART_ACCEL_MPS2 = 2.40
MAX_CART_YAW_ACCEL_RADPS2 = 4.00
MAX_RELATIVE_TRANSLATION_M = 0.080
MAX_RELATIVE_YAW_RAD = math.radians(45.0)
REALISTIC_MIN_CART_MASS_KG = 10.0
CONTACT_PROJECTION_ITERATIONS = 6
MAGNET_DIRECTIONAL_SECTOR_FRACTION = 0.18
MAGNET_FORCE_CAP_MARGIN = 1.25
LIVE_CORRIDOR_PLAYBACK_SPEED = 0.35
LIVE_CORRIDOR_OUTPUT_FPS = 12
LIVE_CORRIDOR_FRAME_STRIDE = 4
INNER_BASE_RADIUS_RANGE_M = (0.056, 0.082)
BASE_GAP_RANGE_M = (0.008, 0.026)
INNER_RADIUS_DEVIATION_M = 0.009
OUTER_RADIUS_DEVIATION_M = 0.010
INNER_ANGLE_JITTER_RAD = math.radians(10.0)
OUTER_ANGLE_JITTER_RAD = math.radians(8.0)


@dataclass(frozen=True)
class FreeArrayDesign:
    magnet_sku_id: str
    cart_mass_kg: float
    magnet_layers: int
    inner_angles_rad: np.ndarray
    inner_radii_m: np.ndarray
    inner_tilt_rad: np.ndarray
    outer_angles_rad: np.ndarray
    outer_radii_m: np.ndarray
    outer_tilt_rad: np.ndarray
    effective_flux_t: float

    @property
    def inner_count(self) -> int:
        return int(self.inner_angles_rad.size)

    @property
    def outer_count(self) -> int:
        return int(self.outer_angles_rad.size)

    @property
    def total_magnets(self) -> int:
        return int((self.inner_count + self.outer_count) * self.magnet_layers)


@dataclass
class FreeArrayAssembly:
    design: FreeArrayDesign
    geometry: base.Geometry
    inner_mount_points_xy: np.ndarray
    outer_mount_points_xy: np.ndarray
    inner_centers_xyz: np.ndarray
    inner_dirs_xyz: np.ndarray
    outer_centers_local_xyz: np.ndarray
    outer_dirs_local_xyz: np.ndarray
    inner_sources: list
    outer_targets: list
    nominal_gap_m: float
    pitch_descriptor: str


@dataclass
class ExactPoseSample:
    force_body_n: np.ndarray
    torque_outer_nm: float
    min_gap_m: float
    contact_penetration_m: float
    contact_normal_body: np.ndarray
    inner_contact_point_body: np.ndarray
    outer_contact_point_body: np.ndarray


@dataclass
class StaticAssessment:
    score: float
    stiffness_matrix_raw: np.ndarray
    stiffness_matrix_scaled: np.ndarray
    scaled_eigenvalues: np.ndarray
    cart_mass_kg: float
    lateral_stiffness_npm: float
    forward_stiffness_npm: float
    yaw_stiffness_nmp_rad: float
    cross_coupling_ratio: float
    mean_orthogonal_ratio: float
    mean_linearity_r2: float
    negative_restore_count: int
    negative_yaw_restore_count: int
    bad_attraction_count: int
    contact_count: int
    package_violation_m: float
    aligned_clearance_m: float
    mean_forward_torque_ratio: float
    nominal_tow_offset_proxy_m: float


@dataclass(frozen=True)
class ScenarioSegment:
    label: str
    start_s: float
    end_s: float
    robot_longitudinal_accel_mps2: float
    human_force_robot_x_n: float
    human_force_robot_y_n: float
    human_torque_nm: float
    phase_id: int


@dataclass(frozen=True)
class FixedHeightScenario:
    name: str
    dt_s: float
    duration_s: float
    segments: tuple[ScenarioSegment, ...]
    corridor_width_m: float
    target_speed_mps: float
    robot_heading_feedback_gain_rad_per_rad: float
    robot_lateral_feedback_gain_rad_per_m: float
    robot_torque_feedback_gain_rad_per_nm: float
    robot_heading_time_constant_s: float
    robot_max_accel_mps2: float
    robot_max_yaw_rate_radps: float
    robot_max_yaw_accel_radps2: float
    robot_force_hold_limit_n: float
    robot_torque_hold_limit_nm: float


@dataclass(frozen=True)
class UncertaintyEnvironment:
    magnetic_scale: float
    cart_mass_scale: float
    rolling_resistance_scale: float
    swivel_resistance_scale: float
    caster_tau_scale: float
    robot_accel_scale: float
    label: str


@dataclass
class DynamicOutcome:
    score: float
    scenario_name: str
    environment_label: str
    min_clearance_mm: float
    max_penetration_mm: float
    contact_events: int
    min_robot_corridor_margin_mm: float
    min_cart_corridor_margin_mm: float
    corridor_breach_count: int
    max_corridor_breach_mm: float
    peak_relative_translation_mm: float
    peak_relative_yaw_deg: float
    cruise_relative_translation_rms_mm: float
    cruise_relative_yaw_rms_deg: float
    cue_peak_yaw_deg: float
    cue_peak_translation_mm: float
    max_cart_accel_mps2: float
    max_cart_yaw_accel_radps2: float
    robot_hold_force_exceeded_count: int
    robot_hold_torque_exceeded_count: int
    dynamic_clip_count: int
    history: dict | None = None


def serializable_array(values):
    return [float(v) for v in np.asarray(values, dtype=float).ravel()]


def bounded_logit(value):
    clipped = float(np.clip(value, 1.0e-6, 1.0 - 1.0e-6))
    return math.log(clipped / (1.0 - clipped))


def design_to_dict(design: FreeArrayDesign):
    return {
        "magnet_sku_id": design.magnet_sku_id,
        "cart_mass_kg": float(design.cart_mass_kg),
        "magnet_layers": int(design.magnet_layers),
        "inner_angles_deg": [float(math.degrees(v)) for v in design.inner_angles_rad],
        "inner_radii_mm": [1000.0 * float(v) for v in design.inner_radii_m],
        "inner_tilt_deg": [float(math.degrees(v)) for v in design.inner_tilt_rad],
        "outer_angles_deg": [float(math.degrees(v)) for v in design.outer_angles_rad],
        "outer_radii_mm": [1000.0 * float(v) for v in design.outer_radii_m],
        "outer_tilt_deg": [float(math.degrees(v)) for v in design.outer_tilt_rad],
        "effective_flux_t": float(design.effective_flux_t),
        "inner_count": int(design.inner_count),
        "outer_count": int(design.outer_count),
        "total_magnets": int(design.total_magnets),
    }


def design_from_dict(payload):
    return FreeArrayDesign(
        magnet_sku_id=str(payload["magnet_sku_id"]),
        cart_mass_kg=float(payload["cart_mass_kg"]),
        magnet_layers=int(payload["magnet_layers"]),
        inner_angles_rad=np.radians(np.asarray(payload["inner_angles_deg"], dtype=float)),
        inner_radii_m=0.001 * np.asarray(payload["inner_radii_mm"], dtype=float),
        inner_tilt_rad=np.radians(np.asarray(payload["inner_tilt_deg"], dtype=float)),
        outer_angles_rad=np.radians(np.asarray(payload["outer_angles_deg"], dtype=float)),
        outer_radii_m=0.001 * np.asarray(payload["outer_radii_mm"], dtype=float),
        outer_tilt_rad=np.radians(np.asarray(payload["outer_tilt_deg"], dtype=float)),
        effective_flux_t=float(payload["effective_flux_t"]),
    )


def static_assessment_to_dict(assessment: StaticAssessment):
    payload = asdict(assessment)
    payload["stiffness_matrix_raw"] = np.asarray(assessment.stiffness_matrix_raw, dtype=float).tolist()
    payload["stiffness_matrix_scaled"] = np.asarray(assessment.stiffness_matrix_scaled, dtype=float).tolist()
    payload["scaled_eigenvalues"] = serializable_array(assessment.scaled_eigenvalues)
    return payload


def outcome_to_dict(outcome: DynamicOutcome):
    payload = asdict(outcome)
    if outcome.history is None:
        payload["history"] = None
    return payload


def write_json_atomic(path: Path, payload: dict):
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def copy_artifact_atomic(source: Path, destination: Path):
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copyfile(source, temp_path)
    temp_path.replace(destination)


def static_constraint_violation_proxy(assessment: StaticAssessment):
    scaled_eigenvalues = np.asarray(assessment.scaled_eigenvalues, dtype=float)
    min_eigen_deficit = max(0.0, -float(np.min(scaled_eigenvalues))) if scaled_eigenvalues.size else 0.0
    return float(
        min_eigen_deficit
        + assessment.mean_orthogonal_ratio
        + 0.2 * assessment.cross_coupling_ratio
        + 0.05 * max(0.0, 1.0 - assessment.mean_linearity_r2)
        + float(assessment.negative_restore_count)
        + float(assessment.negative_yaw_restore_count)
        + float(assessment.bad_attraction_count)
        + float(assessment.contact_count)
        + 1000.0 * float(assessment.package_violation_m)
    )


def static_feasible_proxy(assessment: StaticAssessment):
    scaled_eigenvalues = np.asarray(assessment.scaled_eigenvalues, dtype=float)
    min_eigenvalue = float(np.min(scaled_eigenvalues)) if scaled_eigenvalues.size else -1.0
    return int(
        min_eigenvalue > 0.0
        and assessment.negative_restore_count == 0
        and assessment.negative_yaw_restore_count == 0
        and assessment.bad_attraction_count == 0
        and assessment.contact_count == 0
        and assessment.package_violation_m <= 0.0
    )


def design_monitor_summary(design: FreeArrayDesign, assembly: FreeArrayAssembly):
    inner_radius_m = float(np.mean(np.linalg.norm(assembly.inner_mount_points_xy, axis=1)))
    outer_radius_m = float(np.mean(np.linalg.norm(assembly.outer_mount_points_xy, axis=1)))
    return {
        "shape_label": assembly.pitch_descriptor,
        "inner_count": int(design.inner_count),
        "outer_count": int(design.outer_count),
        "magnet_layers": int(design.magnet_layers),
        "cart_mass_kg": float(design.cart_mass_kg),
        "gap_mm": 1000.0 * float(assembly.nominal_gap_m),
        "mean_radius_mm": 1000.0 * float(0.5 * (inner_radius_m + outer_radius_m)),
        "inner_mean_radius_mm": 1000.0 * inner_radius_m,
        "outer_mean_radius_mm": 1000.0 * outer_radius_m,
        "total_magnets": int(design.total_magnets),
        "magnet_sku_id": str(design.magnet_sku_id),
    }


def smooth_positive_gaps(raw_values, total_span_rad, min_gap_rad):
    raw = np.asarray(raw_values, dtype=float)
    weights = np.exp(np.clip(raw - float(np.max(raw)), -30.0, 30.0))
    free_span = max(total_span_rad - raw.size * min_gap_rad, raw.size * math.radians(1.0))
    gaps = min_gap_rad + free_span * weights / max(float(np.sum(weights)), 1.0e-12)
    centers = np.cumsum(gaps) - 0.5 * gaps
    return centers


def mirrored_ring_parameters(angles_half_rad, radii_half_m, tilt_half_rad, phase_rad):
    angles_half = (np.asarray(angles_half_rad, dtype=float) + phase_rad) % math.pi
    full_angles = np.concatenate((angles_half, (angles_half + math.pi) % (2.0 * math.pi)))
    full_radii = np.concatenate((np.asarray(radii_half_m, dtype=float), np.asarray(radii_half_m, dtype=float)))
    full_tilts = np.concatenate((np.asarray(tilt_half_rad, dtype=float), np.asarray(tilt_half_rad, dtype=float)))
    order = np.argsort(full_angles)
    return full_angles[order], full_radii[order], full_tilts[order]


def latent_dimension(inner_count, outer_count):
    return 4 + 3 * (inner_count // 2) + 3 * (outer_count // 2)


def latent_variable_manifest(inner_count, outer_count):
    inner_half = int(inner_count // 2)
    outer_half = int(outer_count // 2)
    rows = [
        {
            "index": 0,
            "name": "inner_phase_bounded",
            "description": "Global phase offset of the inner ring half-pattern before central mirroring.",
        },
        {
            "index": 1,
            "name": "outer_phase_bounded",
            "description": "Global phase offset of the outer ring half-pattern before central mirroring.",
        },
        {
            "index": 2,
            "name": "inner_base_radius_bounded",
            "description": "Base radius of the inner half-pattern.",
        },
        {
            "index": 3,
            "name": "base_gap_bounded",
            "description": "Base radial separation between the inner and outer half-pattern radii.",
        },
    ]
    index = 4
    for magnet_index in range(inner_half):
        rows.append(
            {
                "index": index,
                "name": f"inner_angle_raw_{magnet_index + 1:02d}",
                "description": f"Angular residual of mirrored inner magnet pair {magnet_index + 1} relative to the equispaced half-ring anchor.",
            }
        )
        index += 1
    for magnet_index in range(inner_half):
        rows.append(
            {
                "index": index,
                "name": f"inner_radius_bounded_{magnet_index + 1:02d}",
                "description": f"Radius offset of mirrored inner magnet pair {magnet_index + 1}.",
            }
        )
        index += 1
    for magnet_index in range(inner_half):
        rows.append(
            {
                "index": index,
                "name": f"inner_tilt_bounded_{magnet_index + 1:02d}",
                "description": f"In-plane magnetization tilt of mirrored inner magnet pair {magnet_index + 1}.",
            }
        )
        index += 1
    for magnet_index in range(outer_half):
        rows.append(
            {
                "index": index,
                "name": f"outer_angle_raw_{magnet_index + 1:02d}",
                "description": f"Angular residual of mirrored outer magnet pair {magnet_index + 1} relative to the equispaced half-ring anchor.",
            }
        )
        index += 1
    for magnet_index in range(outer_half):
        rows.append(
            {
                "index": index,
                "name": f"outer_radius_bounded_{magnet_index + 1:02d}",
                "description": f"Radius offset of mirrored outer magnet pair {magnet_index + 1}.",
            }
        )
        index += 1
    for magnet_index in range(outer_half):
        rows.append(
            {
                "index": index,
                "name": f"outer_tilt_bounded_{magnet_index + 1:02d}",
                "description": f"In-plane magnetization tilt of mirrored outer magnet pair {magnet_index + 1}.",
            }
        )
        index += 1
    return rows


def write_latent_variable_manifest(outpath: Path, inner_count: int, outer_count: int):
    rows = latent_variable_manifest(inner_count, outer_count)
    payload = {
        "inner_count": int(inner_count),
        "outer_count": int(outer_count),
        "latent_dimension": int(latent_dimension(inner_count, outer_count)),
        "variables": rows,
    }
    outpath.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def equispaced_half_angles(count_half):
    return (np.arange(count_half, dtype=float) + 0.5) * (math.pi / count_half)


def wrap_half_difference(angle_rad):
    return ((float(angle_rad) + 0.5 * math.pi) % math.pi) - 0.5 * math.pi


def infer_ring_latent_components(full_angles_rad, full_radii_m, full_tilt_rad, base_radius_range_m, radius_deviation_m, angle_jitter_rad):
    half_count = int(len(full_angles_rad) // 2)
    half_angles = np.asarray(full_angles_rad, dtype=float)[:half_count]
    half_radii = np.asarray(full_radii_m, dtype=float)[:half_count]
    half_tilt = np.asarray(full_tilt_rad, dtype=float)[:half_count]
    anchors = equispaced_half_angles(half_count)
    differences = np.array([wrap_half_difference(angle - anchor) for angle, anchor in zip(half_angles, anchors)], dtype=float)
    phase_rad = float(base.clamp(np.mean(differences), -0.20 * math.pi, 0.20 * math.pi))
    residual_rad = np.array([wrap_half_difference(value - phase_rad) for value in differences], dtype=float)
    angle_raw = np.arctanh(np.clip(residual_rad / max(angle_jitter_rad, 1.0e-6), -0.999999, 0.999999))

    base_radius_m = float(np.mean(half_radii))
    base_radius_bounded = (base_radius_m - base_radius_range_m[0]) / max(base_radius_range_m[1] - base_radius_range_m[0], 1.0e-9)
    radius_bounded = 0.5 + 0.5 * (half_radii - base_radius_m) / max(radius_deviation_m, 1.0e-9)
    tilt_bounded = (np.degrees(half_tilt) + 80.0) / 160.0
    return {
        "phase_bounded": float(np.clip(phase_rad / (0.40 * math.pi) + 0.5, 1.0e-6, 1.0 - 1.0e-6)),
        "base_radius_bounded": float(np.clip(base_radius_bounded, 1.0e-6, 1.0 - 1.0e-6)),
        "angle_raw": np.asarray(angle_raw, dtype=float),
        "radius_bounded": np.clip(np.asarray(radius_bounded, dtype=float), 1.0e-6, 1.0 - 1.0e-6),
        "tilt_bounded": np.clip(np.asarray(tilt_bounded, dtype=float), 1.0e-6, 1.0 - 1.0e-6),
    }


def latent_from_design(design: FreeArrayDesign):
    inner_components = infer_ring_latent_components(
        design.inner_angles_rad,
        design.inner_radii_m,
        design.inner_tilt_rad,
        INNER_BASE_RADIUS_RANGE_M,
        INNER_RADIUS_DEVIATION_M,
        INNER_ANGLE_JITTER_RAD,
    )
    outer_mean_radius_m = float(np.mean(np.asarray(design.outer_radii_m, dtype=float)[: design.outer_count // 2]))
    base_gap_m = outer_mean_radius_m - float(np.mean(np.asarray(design.inner_radii_m, dtype=float)[: design.inner_count // 2]))
    base_gap_bounded = (base_gap_m - BASE_GAP_RANGE_M[0]) / max(BASE_GAP_RANGE_M[1] - BASE_GAP_RANGE_M[0], 1.0e-9)
    outer_components = infer_ring_latent_components(
        design.outer_angles_rad,
        design.outer_radii_m,
        design.outer_tilt_rad,
        (outer_mean_radius_m - OUTER_RADIUS_DEVIATION_M, outer_mean_radius_m + OUTER_RADIUS_DEVIATION_M),
        OUTER_RADIUS_DEVIATION_M,
        OUTER_ANGLE_JITTER_RAD,
    )
    outer_base_radius_m = float(np.mean(np.asarray(design.outer_radii_m, dtype=float)[: design.outer_count // 2]))
    outer_radius_bounded = 0.5 + 0.5 * (
        np.asarray(design.outer_radii_m, dtype=float)[: design.outer_count // 2] - outer_base_radius_m
    ) / max(OUTER_RADIUS_DEVIATION_M, 1.0e-9)

    latent = [
        bounded_logit(inner_components["phase_bounded"]),
        bounded_logit(outer_components["phase_bounded"]),
        bounded_logit(inner_components["base_radius_bounded"]),
        bounded_logit(np.clip(base_gap_bounded, 1.0e-6, 1.0 - 1.0e-6)),
    ]
    latent.extend(inner_components["angle_raw"].tolist())
    latent.extend([bounded_logit(value) for value in inner_components["radius_bounded"]])
    latent.extend([bounded_logit(value) for value in inner_components["tilt_bounded"]])
    latent.extend(outer_components["angle_raw"].tolist())
    latent.extend([bounded_logit(value) for value in np.clip(outer_radius_bounded, 1.0e-6, 1.0 - 1.0e-6)])
    latent.extend([bounded_logit(value) for value in outer_components["tilt_bounded"]])
    return np.asarray(latent, dtype=float)


def build_design_from_latent(latent_vector, inner_count, outer_count, cart_mass_kg, magnet_layers):
    if inner_count % 2 or outer_count % 2:
        raise ValueError("This implementation expects even inner/outer magnet counts for central symmetry.")
    sku = base.MAGNET_CATALOG_BY_ID[FIXED_SKU_ID]
    bounded = base.sigmoid(np.asarray(latent_vector, dtype=float))
    index = 0
    inner_phase_rad = 0.40 * math.pi * (bounded[index] - 0.5)
    index += 1
    outer_phase_rad = 0.40 * math.pi * (bounded[index] - 0.5)
    index += 1
    inner_base_radius_m = INNER_BASE_RADIUS_RANGE_M[0] + (INNER_BASE_RADIUS_RANGE_M[1] - INNER_BASE_RADIUS_RANGE_M[0]) * bounded[index]
    index += 1
    base_gap_m = BASE_GAP_RANGE_M[0] + (BASE_GAP_RANGE_M[1] - BASE_GAP_RANGE_M[0]) * bounded[index]
    index += 1

    inner_half = inner_count // 2
    outer_half = outer_count // 2
    inner_angle_raw = latent_vector[index : index + inner_half]
    index += inner_half
    inner_radius_raw = bounded[index : index + inner_half]
    index += inner_half
    inner_tilt_raw = bounded[index : index + inner_half]
    index += inner_half
    outer_angle_raw = latent_vector[index : index + outer_half]
    index += outer_half
    outer_radius_raw = bounded[index : index + outer_half]
    index += outer_half
    outer_tilt_raw = bounded[index : index + outer_half]

    inner_half_angles = equispaced_half_angles(inner_half) + INNER_ANGLE_JITTER_RAD * np.tanh(inner_angle_raw)
    outer_half_angles = equispaced_half_angles(outer_half) + OUTER_ANGLE_JITTER_RAD * np.tanh(outer_angle_raw)
    inner_half_angles = np.sort(np.mod(inner_half_angles, math.pi))
    outer_half_angles = np.sort(np.mod(outer_half_angles, math.pi))

    inner_half_radii_m = inner_base_radius_m + (2.0 * inner_radius_raw - 1.0) * INNER_RADIUS_DEVIATION_M
    inner_half_radii_m = np.clip(inner_half_radii_m, INNER_BASE_RADIUS_RANGE_M[0], INNER_BASE_RADIUS_RANGE_M[1])
    outer_base_radius_m = inner_base_radius_m + base_gap_m
    outer_half_radii_m = outer_base_radius_m + (2.0 * outer_radius_raw - 1.0) * OUTER_RADIUS_DEVIATION_M
    outer_half_radii_m = np.maximum(outer_half_radii_m, inner_base_radius_m + 0.75 * base_gap_m)
    inner_half_tilt_rad = np.radians(-80.0 + 160.0 * inner_tilt_raw)
    outer_half_tilt_rad = np.radians(-80.0 + 160.0 * outer_tilt_raw)

    inner_angles_rad, inner_radii_m, inner_tilt_rad = mirrored_ring_parameters(
        inner_half_angles,
        inner_half_radii_m,
        inner_half_tilt_rad,
        phase_rad=inner_phase_rad,
    )
    outer_angles_rad, outer_radii_m, outer_tilt_rad = mirrored_ring_parameters(
        outer_half_angles,
        outer_half_radii_m,
        outer_half_tilt_rad,
        phase_rad=outer_phase_rad,
    )

    design = FreeArrayDesign(
        magnet_sku_id=sku.sku_id,
        cart_mass_kg=float(cart_mass_kg),
        magnet_layers=int(magnet_layers),
        inner_angles_rad=inner_angles_rad,
        inner_radii_m=inner_radii_m,
        inner_tilt_rad=inner_tilt_rad,
        outer_angles_rad=outer_angles_rad,
        outer_radii_m=outer_radii_m,
        outer_tilt_rad=outer_tilt_rad,
        effective_flux_t=float(hifi.effective_flux_density_t(sku)),
    )
    return design


def ring_points_from_polar(angles_rad, radii_m):
    angles = np.asarray(angles_rad, dtype=float)
    radii = np.asarray(radii_m, dtype=float)
    return np.column_stack((radii * np.cos(angles), radii * np.sin(angles)))


def build_support_geometry(inner_points_seed, outer_points_seed):
    inner_smooth = hifi.chaikin_closed(inner_points_seed, 2)
    outer_smooth = hifi.chaikin_closed(outer_points_seed, 2)
    inner_points = hifi.resample_closed_polyline(inner_smooth, 192)
    outer_points = hifi.resample_closed_polyline(outer_smooth, 192)
    (
        inner_points,
        inner_normals,
        inner_tangents,
        inner_ds,
        inner_support,
        inner_arc_fraction,
        inner_perimeter_m,
        inner_max_radius,
    ) = hifi.boundary_from_points(inner_points)
    (
        outer_points,
        outer_normals,
        outer_tangents,
        _,
        _,
        outer_arc_fraction,
        outer_perimeter_m,
        outer_max_radius,
    ) = hifi.boundary_from_points(outer_points)
    geometry = base.Geometry(
        shape_name="free_array_fixedheight",
        inner_points=inner_points,
        inner_normals=inner_normals,
        inner_tangents=inner_tangents,
        inner_ds=inner_ds,
        inner_support=inner_support,
        inner_arc_fraction=inner_arc_fraction,
        inner_perimeter_m=float(inner_perimeter_m),
        outer_points_local=outer_points,
        outer_outward_normals_local=outer_normals,
        outer_inward_normals_local=-outer_normals,
        outer_tangents_local=outer_tangents,
        outer_arc_fraction=outer_arc_fraction,
        outer_perimeter_m=float(outer_perimeter_m),
        max_radius_m=float(max(inner_max_radius, outer_max_radius)),
        yaw_contact_limit_rad=0.0,
        translation_contact_limit_m=0.0,
        base_gap_m=0.0,
        beta=base.SOFTMAX_SHARPNESS / max(float(0.5 * (inner_max_radius + outer_max_radius)), 1.0e-3),
    )
    aligned_gap_m, _, _, _ = base.sat_signed_gap_profile(geometry, np.zeros(2, dtype=float), 0.0)
    geometry.base_gap_m = float(max(aligned_gap_m, 1.0e-4))
    geometry.translation_contact_limit_m = base.estimate_translation_limit_m(geometry)
    geometry.yaw_contact_limit_rad = base.estimate_yaw_limit_rad(geometry)
    return geometry, float(aligned_gap_m)


def moment_directions_from_angles(angles_rad, tilt_rad, inner_side):
    directions = []
    for angle_rad, tilt_value in zip(np.asarray(angles_rad, dtype=float), np.asarray(tilt_rad, dtype=float)):
        radial = np.array([math.cos(angle_rad), math.sin(angle_rad)], dtype=float)
        nominal = radial if inner_side else -radial
        directions.append(base.rotmat(float(tilt_value)) @ nominal)
    return np.asarray(directions, dtype=float)


def layer_z_centers(magnet_layers, diameter_m):
    if magnet_layers <= 1:
        return np.array([0.0], dtype=float)
    return (np.arange(magnet_layers, dtype=float) - 0.5 * (magnet_layers - 1)) * diameter_m


def cylinder_object(center_xyz, moment_dir_xyz, flux_t, diameter_m, thickness_m, as_target):
    if magpy is None:
        raise RuntimeError("magpylib is not available.")
    rotation = hifi.magpylib_rotation_from_moment(moment_dir_xyz)
    kwargs = {"meshing": 9} if as_target else {}
    return magpy.magnet.Cylinder(
        polarization=(0.0, 0.0, float(flux_t)),
        dimension=(float(diameter_m), float(thickness_m)),
        position=tuple(np.asarray(center_xyz, dtype=float)),
        orientation=rotation,
        **kwargs,
    )


def build_assembly(design: FreeArrayDesign):
    sku = base.MAGNET_CATALOG_BY_ID[design.magnet_sku_id]
    diameter_m = float(sku.tangential_length_m)
    thickness_m = float(sku.radial_depth_m)
    inner_mount_points_xy = ring_points_from_polar(design.inner_angles_rad, design.inner_radii_m)
    outer_mount_points_xy = ring_points_from_polar(design.outer_angles_rad, design.outer_radii_m)
    geometry, nominal_gap_m = build_support_geometry(inner_mount_points_xy, outer_mount_points_xy)
    inner_dirs_xy = moment_directions_from_angles(design.inner_angles_rad, design.inner_tilt_rad, inner_side=True)
    outer_dirs_xy = moment_directions_from_angles(design.outer_angles_rad, design.outer_tilt_rad, inner_side=False)
    z_values = layer_z_centers(design.magnet_layers, diameter_m)

    inner_centers_xyz = []
    inner_dirs_xyz = []
    outer_centers_xyz = []
    outer_dirs_xyz = []
    for z_center in z_values:
        for mount_xy, direction_xy in zip(inner_mount_points_xy, inner_dirs_xy):
            center_xyz = np.array(
                [
                    mount_xy[0] - 0.5 * thickness_m * direction_xy[0],
                    mount_xy[1] - 0.5 * thickness_m * direction_xy[1],
                    z_center,
                ],
                dtype=float,
            )
            inner_centers_xyz.append(center_xyz)
            inner_dirs_xyz.append(np.array([direction_xy[0], direction_xy[1], 0.0], dtype=float))
        for mount_xy, direction_xy in zip(outer_mount_points_xy, outer_dirs_xy):
            center_xyz = np.array(
                [
                    mount_xy[0] + 0.5 * thickness_m * direction_xy[0],
                    mount_xy[1] + 0.5 * thickness_m * direction_xy[1],
                    z_center,
                ],
                dtype=float,
            )
            outer_centers_xyz.append(center_xyz)
            outer_dirs_xyz.append(np.array([direction_xy[0], direction_xy[1], 0.0], dtype=float))

    inner_centers_xyz = np.asarray(inner_centers_xyz, dtype=float)
    inner_dirs_xyz = np.asarray(inner_dirs_xyz, dtype=float)
    outer_centers_xyz = np.asarray(outer_centers_xyz, dtype=float)
    outer_dirs_xyz = np.asarray(outer_dirs_xyz, dtype=float)
    inner_sources = [
        cylinder_object(center_xyz, dir_xyz, design.effective_flux_t, diameter_m, thickness_m, as_target=False)
        for center_xyz, dir_xyz in zip(inner_centers_xyz, inner_dirs_xyz)
    ]
    outer_targets = [
        cylinder_object(center_xyz, dir_xyz, design.effective_flux_t, diameter_m, thickness_m, as_target=True)
        for center_xyz, dir_xyz in zip(outer_centers_xyz, outer_dirs_xyz)
    ]
    return FreeArrayAssembly(
        design=design,
        geometry=geometry,
        inner_mount_points_xy=inner_mount_points_xy,
        outer_mount_points_xy=outer_mount_points_xy,
        inner_centers_xyz=inner_centers_xyz,
        inner_dirs_xyz=inner_dirs_xyz,
        outer_centers_local_xyz=outer_centers_xyz,
        outer_dirs_local_xyz=outer_dirs_xyz,
        inner_sources=inner_sources,
        outer_targets=outer_targets,
        nominal_gap_m=float(max(nominal_gap_m, 0.0)),
        pitch_descriptor=f"{design.inner_count}in_{design.outer_count}out_{design.magnet_layers}layer",
    )


def freearray_pole_face_area_m2(assembly: FreeArrayAssembly):
    sku = base.MAGNET_CATALOG_BY_ID[assembly.design.magnet_sku_id]
    return math.pi * (0.5 * float(sku.tangential_length_m)) ** 2


def freearray_per_magnet_force_cap_n(assembly: FreeArrayAssembly):
    sku = base.MAGNET_CATALOG_BY_ID[assembly.design.magnet_sku_id]
    pressure_force_n = (float(sku.surface_flux_t) ** 2) * freearray_pole_face_area_m2(assembly) / (2.0 * MU0)
    if float(getattr(sku, "pull_force_n", 0.0)) > 0.0:
        return min(pressure_force_n, float(sku.pull_force_n))
    return pressure_force_n


def freearray_array_force_cap_n(assembly: FreeArrayAssembly):
    engaged_pairs = max(
        2.0,
        MAGNET_DIRECTIONAL_SECTOR_FRACTION * float(min(assembly.design.inner_count, assembly.design.outer_count)),
    )
    cap_n = MAGNET_FORCE_CAP_MARGIN * freearray_per_magnet_force_cap_n(assembly) * engaged_pairs * assembly.design.magnet_layers
    return max(cap_n, 1.0)


def freearray_array_torque_cap_nm(assembly: FreeArrayAssembly):
    mean_radius_m = 0.5 * (
        float(np.mean(np.linalg.norm(assembly.inner_mount_points_xy, axis=1)))
        + float(np.mean(np.linalg.norm(assembly.outer_mount_points_xy, axis=1)))
    )
    return freearray_array_force_cap_n(assembly) * max(mean_radius_m, 1.0e-3)


def freearray_gap_decay_factor(min_gap_m: float, assembly: FreeArrayAssembly):
    sku = base.MAGNET_CATALOG_BY_ID[assembly.design.magnet_sku_id]
    characteristic_length_m = max(0.5 * float(sku.tangential_length_m), 1.0e-4)
    ratio = max(float(min_gap_m), 0.0) / characteristic_length_m
    return 1.0 / ((1.0 + ratio) ** 2)


def transform_outer_ring(assembly: FreeArrayAssembly, relative_translation_body_m, relative_yaw_rad):
    rotation = base.rotmat(relative_yaw_rad)
    centers_xy = assembly.outer_centers_local_xyz[:, :2] @ rotation.T + relative_translation_body_m
    dirs_xy = assembly.outer_dirs_local_xyz[:, :2] @ rotation.T
    centers_xyz = np.column_stack((centers_xy, assembly.outer_centers_local_xyz[:, 2]))
    dirs_xyz = np.column_stack((dirs_xy, assembly.outer_dirs_local_xyz[:, 2]))
    return centers_xyz, dirs_xyz


def evaluate_pose_exact(assembly: FreeArrayAssembly, relative_translation_body_m, relative_yaw_rad):
    sat_gap_m, sat_normal, sat_inner_point, sat_outer_point = base.sat_signed_gap_profile(
        assembly.geometry,
        np.asarray(relative_translation_body_m, dtype=float),
        float(relative_yaw_rad),
    )
    penetration_m = max(0.0, -float(sat_gap_m))
    effective_translation_body_m = np.asarray(relative_translation_body_m, dtype=float)
    if penetration_m > 0.0:
        # Never evaluate magnetic force on an interpenetrating pose.
        effective_translation_body_m = effective_translation_body_m + sat_normal * penetration_m
    centers_xyz, dirs_xyz = transform_outer_ring(assembly, effective_translation_body_m, relative_yaw_rad)
    targets = assembly.outer_targets
    for target, center_xyz, dir_xyz in zip(targets, centers_xyz, dirs_xyz):
        target.position = tuple(np.asarray(center_xyz, dtype=float))
        target.orientation = hifi.magpylib_rotation_from_moment(dir_xyz)
    force_xyz, torque_xyz = magpy.getFT(
        assembly.inner_sources,
        targets,
        pivot="centroid",
        squeeze=True,
        eps=1.0e-6,
    )
    total_force_xyz = np.asarray(force_xyz, dtype=float).reshape(-1, 3).sum(axis=0)
    total_torque_xyz = np.asarray(torque_xyz, dtype=float).reshape(-1, 3).sum(axis=0)
    min_gap_m = max(float(sat_gap_m), 0.0)
    decay = freearray_gap_decay_factor(min_gap_m, assembly)
    total_force_xy = base.clamp_norm(total_force_xyz[:2].copy(), max(0.35, freearray_array_force_cap_n(assembly) * decay))
    torque_outer_nm = base.clamp(
        float(total_torque_xyz[2]),
        -max(0.03, freearray_array_torque_cap_nm(assembly) * decay),
        max(0.03, freearray_array_torque_cap_nm(assembly) * decay),
    )
    return ExactPoseSample(
        force_body_n=total_force_xy,
        torque_outer_nm=torque_outer_nm,
        min_gap_m=min_gap_m,
        contact_penetration_m=penetration_m,
        contact_normal_body=np.asarray(sat_normal, dtype=float),
        inner_contact_point_body=np.asarray(sat_inner_point, dtype=float),
        outer_contact_point_body=np.asarray(sat_outer_point, dtype=float),
    )


def generalized_response(sample: ExactPoseSample):
    return np.array([sample.force_body_n[0], sample.force_body_n[1], sample.torque_outer_nm], dtype=float)


def estimate_stiffness_matrices(assembly: FreeArrayAssembly):
    raw_matrix = np.zeros((3, 3), dtype=float)
    deltas = np.array([0.0015, 0.0015, math.radians(2.5)], dtype=float)
    for column, delta in enumerate(deltas):
        q_plus = np.zeros(3, dtype=float)
        q_minus = np.zeros(3, dtype=float)
        q_plus[column] = delta
        q_minus[column] = -delta
        sample_plus = evaluate_pose_exact(assembly, q_plus[:2], q_plus[2])
        sample_minus = evaluate_pose_exact(assembly, q_minus[:2], q_minus[2])
        raw_matrix[:, column] = -(generalized_response(sample_plus) - generalized_response(sample_minus)) / (2.0 * delta)
    scaling = np.diag([REFERENCE_TRANSLATION_M, REFERENCE_TRANSLATION_M, REFERENCE_YAW_RAD])
    scaled_matrix = scaling.T @ raw_matrix @ scaling
    return raw_matrix, 0.5 * (scaled_matrix + scaled_matrix.T)


def package_violation_m(assembly: FreeArrayAssembly):
    inner_min = np.min(assembly.geometry.inner_points, axis=0)
    inner_max = np.max(assembly.geometry.inner_points, axis=0)
    outer_min = np.min(assembly.geometry.outer_points_local, axis=0)
    outer_max = np.max(assembly.geometry.outer_points_local, axis=0)
    inner_width = float(inner_max[0] - inner_min[0])
    inner_length = float(inner_max[1] - inner_min[1])
    outer_width = float(outer_max[0] - outer_min[0])
    outer_length = float(outer_max[1] - outer_min[1])
    violation = (
        max(0.0, inner_width - (hifi.ROBOT_WIDTH_M + hifi.ROBOT_MOUNT_WIDTH_ALLOWANCE_M))
        + max(0.0, inner_length - (hifi.ROBOT_LENGTH_M + hifi.ROBOT_MOUNT_LENGTH_ALLOWANCE_M))
        + max(0.0, outer_width - (hifi.CART_WIDTH_M - hifi.CART_MOUNT_MARGIN_M))
        + max(0.0, outer_length - (hifi.CART_LENGTH_M - hifi.CART_MOUNT_MARGIN_M))
    )
    return float(violation)


def assess_static_design(
    assembly: FreeArrayAssembly,
    directions_rad=DEFAULT_DIRECTIONS_RAD,
    displacements_m=DEFAULT_SEARCH_DISPLACEMENTS_M,
    yaw_samples_rad=DEFAULT_SEARCH_YAW_RAD,
    tow_offsets=(0.004, 0.008),
):
    raw_matrix, scaled_matrix = estimate_stiffness_matrices(assembly)
    eigenvalues = np.linalg.eigvalsh(scaled_matrix)
    orthogonal_ratios = []
    r2_values = []
    forward_torque_ratios = []
    negative_restore_count = 0
    negative_yaw_restore_count = 0
    bad_attraction_count = 0
    contact_count = 0
    directional_stiffness = []

    for angle_rad in np.asarray(directions_rad, dtype=float):
        direction = np.array([math.cos(angle_rad), math.sin(angle_rad)], dtype=float)
        force_values = []
        for displacement_m in np.asarray(displacements_m, dtype=float):
            sample = evaluate_pose_exact(assembly, displacement_m * direction, 0.0)
            parallel_force_n = -float(np.dot(sample.force_body_n, direction))
            orthogonal_force_n = abs(base.cross2(direction, sample.force_body_n))
            orthogonal_ratios.append(orthogonal_force_n / max(abs(parallel_force_n), 1.0e-6))
            force_values.append(parallel_force_n)
            if parallel_force_n <= 0.0:
                negative_restore_count += 1
                bad_attraction_count += 1
            if sample.contact_penetration_m > 0.0:
                contact_count += 1
                bad_attraction_count += 1
        slope, _intercept, r2 = hifi.fit_line(displacements_m, force_values)
        directional_stiffness.append(slope)
        r2_values.append(r2)

    for yaw_rad in np.asarray(yaw_samples_rad, dtype=float):
        sample = evaluate_pose_exact(assembly, np.zeros(2, dtype=float), yaw_rad)
        restoring_torque_nm = -sample.torque_outer_nm * math.copysign(1.0, yaw_rad)
        if restoring_torque_nm <= 0.0:
            negative_yaw_restore_count += 1
            bad_attraction_count += 1
        if sample.contact_penetration_m > 0.0:
            contact_count += 1
            bad_attraction_count += 1

    for tow_offset_m in tow_offsets:
        sample = evaluate_pose_exact(assembly, np.array([0.0, tow_offset_m], dtype=float), 0.0)
        forward_force_n = -float(np.dot(sample.force_body_n, np.array([0.0, 1.0], dtype=float)))
        forward_torque_ratios.append(abs(sample.torque_outer_nm) / max(abs(forward_force_n) * 0.08, 1.0e-6))

    cross_matrix = scaled_matrix - np.diag(np.diag(scaled_matrix))
    diagonal_norm = max(float(np.linalg.norm(np.diag(np.diag(scaled_matrix)))), 1.0e-9)
    cross_coupling_ratio = float(np.linalg.norm(cross_matrix) / diagonal_norm)
    lateral_stiffness_npm = float(raw_matrix[0, 0])
    forward_stiffness_npm = float(raw_matrix[1, 1])
    yaw_stiffness_nmp_rad = float(raw_matrix[2, 2])
    mean_orthogonal_ratio = float(np.mean(orthogonal_ratios)) if orthogonal_ratios else 1.0
    mean_linearity_r2 = float(np.mean(r2_values)) if r2_values else 0.0
    mean_forward_torque_ratio = float(np.mean(forward_torque_ratios)) if forward_torque_ratios else 1.0
    package_violation = package_violation_m(assembly)
    nominal_tow_force_n = hifi.CART_SUSTAINED_RESISTANCE_COEFF * assembly.design.cart_mass_kg * 9.81
    nominal_tow_offset_proxy_m = nominal_tow_force_n / max(forward_stiffness_npm, 1.0e-6)
    aligned_gap_mm = 1000.0 * float(assembly.nominal_gap_m)

    score = 0.0
    score += 2200.0 * min(float(np.min(eigenvalues)), 0.20)
    score += 0.12 * max(forward_stiffness_npm, 0.0)
    score += 0.08 * max(lateral_stiffness_npm, 0.0)
    score += 0.18 * max(yaw_stiffness_nmp_rad, 0.0)
    score += 24.0 * assembly.design.total_magnets
    score -= 900.0 * cross_coupling_ratio
    score -= 500.0 * mean_orthogonal_ratio
    score -= 220.0 * (1.0 - mean_linearity_r2)
    score -= 180.0 * mean_forward_torque_ratio
    score -= 2600.0 * negative_restore_count
    score -= 4200.0 * negative_yaw_restore_count
    score -= 2200.0 * bad_attraction_count
    score -= 2500.0 * contact_count
    score -= 700000.0 * package_violation
    score -= 180000.0 * max(0.0, nominal_tow_offset_proxy_m - 0.015)
    score -= 2200.0 * max(0.0, aligned_gap_mm - 28.0)
    score -= 1800.0 * max(0.0, 8.0 - aligned_gap_mm)

    return StaticAssessment(
        score=float(score),
        stiffness_matrix_raw=raw_matrix,
        stiffness_matrix_scaled=scaled_matrix,
        scaled_eigenvalues=eigenvalues,
        cart_mass_kg=float(assembly.design.cart_mass_kg),
        lateral_stiffness_npm=lateral_stiffness_npm,
        forward_stiffness_npm=forward_stiffness_npm,
        yaw_stiffness_nmp_rad=yaw_stiffness_nmp_rad,
        cross_coupling_ratio=cross_coupling_ratio,
        mean_orthogonal_ratio=mean_orthogonal_ratio,
        mean_linearity_r2=mean_linearity_r2,
        negative_restore_count=int(negative_restore_count),
        negative_yaw_restore_count=int(negative_yaw_restore_count),
        bad_attraction_count=int(bad_attraction_count),
        contact_count=int(contact_count),
        package_violation_m=package_violation,
        aligned_clearance_m=float(assembly.nominal_gap_m),
        mean_forward_torque_ratio=mean_forward_torque_ratio,
        nominal_tow_offset_proxy_m=float(nominal_tow_offset_proxy_m),
    )


def build_nominal_environment():
    return UncertaintyEnvironment(
        magnetic_scale=1.0,
        cart_mass_scale=1.0,
        rolling_resistance_scale=1.0,
        swivel_resistance_scale=1.0,
        caster_tau_scale=1.0,
        robot_accel_scale=1.0,
        label="nominal",
    )


def sample_environment(seed, replica_index):
    rng = np.random.default_rng(seed + 7919 * replica_index)
    return UncertaintyEnvironment(
        magnetic_scale=float(base.clamp(1.0 + rng.normal(0.0, 0.07), 0.82, 1.18)),
        cart_mass_scale=float(base.clamp(1.0 + rng.normal(0.0, 0.10), 0.80, 1.25)),
        rolling_resistance_scale=float(base.clamp(1.0 + rng.normal(0.0, 0.18), 0.70, 1.35)),
        swivel_resistance_scale=float(base.clamp(1.0 + rng.normal(0.0, 0.20), 0.65, 1.40)),
        caster_tau_scale=float(base.clamp(1.0 + rng.normal(0.0, 0.15), 0.70, 1.40)),
        robot_accel_scale=float(base.clamp(1.0 + rng.normal(0.0, 0.10), 0.80, 1.20)),
        label=f"perturbed_{replica_index}",
    )


def build_avoid_return_scenario():
    return FixedHeightScenario(
        name="corridor_avoid_return_fixedheight",
        dt_s=0.02,
        duration_s=8.0,
        segments=(
            ScenarioSegment("accel", 0.0, 1.0, 0.45, 0.0, 0.0, 0.0, 1),
            ScenarioSegment("cruise", 1.0, 2.4, 0.0, 0.0, 0.0, 0.0, 2),
            ScenarioSegment("avoid_rise", 2.4, 3.1, 0.0, 6.0, 2.0, -1.40, 3),
            ScenarioSegment("avoid_hold", 3.1, 4.2, 0.0, 3.5, 1.2, -0.80, 3),
            ScenarioSegment("release", 4.2, 6.0, 0.0, 0.0, 0.0, 0.0, 4),
            ScenarioSegment("settle", 6.0, 8.0, 0.0, 0.0, 0.0, 0.0, 5),
        ),
        corridor_width_m=1.80,
        target_speed_mps=0.45,
        robot_heading_feedback_gain_rad_per_rad=1.45,
        robot_lateral_feedback_gain_rad_per_m=7.5,
        robot_torque_feedback_gain_rad_per_nm=0.065,
        robot_heading_time_constant_s=0.35,
        robot_max_accel_mps2=0.80,
        robot_max_yaw_rate_radps=0.80,
        robot_max_yaw_accel_radps2=2.20,
        robot_force_hold_limit_n=18.0,
        robot_torque_hold_limit_nm=4.5,
    )


def build_straight_lateral_pulse_scenario():
    return FixedHeightScenario(
        name="corridor_straight_lateral_pulse_fixedheight",
        dt_s=0.02,
        duration_s=6.0,
        segments=(
            ScenarioSegment("accel", 0.0, 1.0, 0.45, 0.0, 0.0, 0.0, 1),
            ScenarioSegment("cruise", 1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 2),
            ScenarioSegment("pulse", 2.0, 2.5, 0.0, 4.5, 0.5, -0.35, 3),
            ScenarioSegment("recover", 2.5, 6.0, 0.0, 0.0, 0.0, 0.0, 4),
        ),
        corridor_width_m=1.80,
        target_speed_mps=0.45,
        robot_heading_feedback_gain_rad_per_rad=1.35,
        robot_lateral_feedback_gain_rad_per_m=6.8,
        robot_torque_feedback_gain_rad_per_nm=0.055,
        robot_heading_time_constant_s=0.30,
        robot_max_accel_mps2=0.80,
        robot_max_yaw_rate_radps=0.60,
        robot_max_yaw_accel_radps2=2.00,
        robot_force_hold_limit_n=18.0,
        robot_torque_hold_limit_nm=4.5,
    )


def scenario_arrays(scenario: FixedHeightScenario):
    steps = int(round(scenario.duration_s / scenario.dt_s))
    time_s = scenario.dt_s * np.arange(steps, dtype=float)
    longitudinal_accel = np.zeros(steps, dtype=float)
    human_force_robot = np.zeros((steps, 2), dtype=float)
    human_torque = np.zeros(steps, dtype=float)
    phase = np.zeros(steps, dtype=int)
    labels = np.empty(steps, dtype=object)
    labels[:] = ""
    for segment in scenario.segments:
        start_i = int(round(segment.start_s / scenario.dt_s))
        end_i = min(steps, int(round(segment.end_s / scenario.dt_s)))
        longitudinal_accel[start_i:end_i] = segment.robot_longitudinal_accel_mps2
        human_force_robot[start_i:end_i, 0] = segment.human_force_robot_x_n
        human_force_robot[start_i:end_i, 1] = segment.human_force_robot_y_n
        human_torque[start_i:end_i] = segment.human_torque_nm
        phase[start_i:end_i] = segment.phase_id
        labels[start_i:end_i] = segment.label
    return {
        "time_s": time_s,
        "robot_longitudinal_accel_mps2": longitudinal_accel,
        "human_force_robot_n": human_force_robot,
        "human_torque_nm": human_torque,
        "phase": phase,
        "segment_label": labels,
    }


def body_to_world(yaw_rad, vector_body):
    return base.rotmat(yaw_rad) @ np.asarray(vector_body, dtype=float)


def rigid_box_world_points(width_m, length_m, position_world_xy, yaw_rad):
    half_width = 0.5 * float(width_m)
    half_length = 0.5 * float(length_m)
    local_points = np.array(
        [
            [-half_width, -half_length],
            [half_width, -half_length],
            [half_width, half_length],
            [-half_width, half_length],
        ],
        dtype=float,
    )
    return local_points @ base.rotmat(yaw_rad).T + np.asarray(position_world_xy, dtype=float)


def corridor_margin_and_breach_mm(points_world_xy, corridor_width_m):
    half_corridor_m = 0.5 * float(corridor_width_m)
    x_values = np.asarray(points_world_xy, dtype=float)[:, 0]
    left_margin_m = x_values + half_corridor_m
    right_margin_m = half_corridor_m - x_values
    min_margin_m = float(min(np.min(left_margin_m), np.min(right_margin_m)))
    return 1000.0 * min_margin_m, 1000.0 * max(0.0, -min_margin_m)


def wrap_difference(target, current):
    return base.wrap_angle(float(target) - float(current))


def apply_cart_axis_stiction(force_body_n, velocity_body_mps, threshold_body_n, speed_eps_mps):
    adjusted = np.asarray(force_body_n, dtype=float).copy()
    for axis_index in range(2):
        if abs(float(velocity_body_mps[axis_index])) <= speed_eps_mps and abs(float(adjusted[axis_index])) <= threshold_body_n[axis_index]:
            adjusted[axis_index] = 0.0
    return adjusted


def settle_nonpenetration_exact(
    assembly: FreeArrayAssembly,
    robot_yaw_rad: float,
    cart_yaw_rad: float,
    robot_position_world: np.ndarray,
    robot_velocity_world: np.ndarray,
    cart_position_world: np.ndarray,
    cart_velocity_world: np.ndarray,
    effective_cart_mass_kg: float,
    max_iterations: int = CONTACT_PROJECTION_ITERATIONS,
):
    residual = None
    sample = None
    for _iteration in range(max_iterations):
        relative_translation_body_m = base.rotmat(-robot_yaw_rad) @ (cart_position_world - robot_position_world)
        relative_yaw_rad = base.wrap_angle(cart_yaw_rad - robot_yaw_rad)
        sample = evaluate_pose_exact(assembly, relative_translation_body_m, relative_yaw_rad)
        residual = sample.contact_penetration_m
        if residual <= CONTACT_MARGIN_M:
            return sample, residual
        hifi.project_contact_state(
            sample,
            robot_yaw_rad,
            cart_position_world,
            cart_velocity_world,
            robot_position_world,
            robot_velocity_world,
            effective_cart_mass_kg,
        )
    relative_translation_body_m = base.rotmat(-robot_yaw_rad) @ (cart_position_world - robot_position_world)
    relative_yaw_rad = base.wrap_angle(cart_yaw_rad - robot_yaw_rad)
    sample = evaluate_pose_exact(assembly, relative_translation_body_m, relative_yaw_rad)
    return sample, sample.contact_penetration_m


def simulate_fixedheight_episode(assembly: FreeArrayAssembly, scenario: FixedHeightScenario, environment: UncertaintyEnvironment, record=False):
    arrays = scenario_arrays(scenario)
    dt_s = scenario.dt_s
    steps = len(arrays["time_s"])
    effective_cart_mass_kg = assembly.design.cart_mass_kg * environment.cart_mass_scale
    cart_inertia = hifi.cart_inertia_kgm2(effective_cart_mass_kg)
    cart_normal_load_n = effective_cart_mass_kg * 9.81
    robot_position_world = np.zeros(2, dtype=float)
    robot_yaw_rad = 0.0
    robot_speed_mps = 0.0
    robot_yaw_rate_radps = 0.0
    robot_velocity_world = np.zeros(2, dtype=float)
    cart_position_world = np.zeros(2, dtype=float)
    cart_velocity_world = np.zeros(2, dtype=float)
    cart_yaw_rad = 0.0
    cart_yaw_rate_radps = 0.0
    caster_angle_rad = 0.0
    min_gap_m = float("inf")
    max_penetration_m = 0.0
    contact_events = 0
    in_contact = False
    peak_relative_translation_mm = 0.0
    peak_relative_yaw_deg = 0.0
    max_cart_accel_mps2 = 0.0
    max_cart_yaw_accel_radps2 = 0.0
    robot_hold_force_exceeded_count = 0
    robot_hold_torque_exceeded_count = 0
    dynamic_clip_count = 0
    min_robot_corridor_margin_mm = float("inf")
    min_cart_corridor_margin_mm = float("inf")
    corridor_breach_count = 0
    max_corridor_breach_mm = 0.0
    cue_peak_yaw_deg = 0.0
    cue_peak_translation_mm = 0.0
    cruise_translation_samples = []
    cruise_yaw_samples = []

    rolling_long_n = environment.rolling_resistance_scale * hifi.CART_SUSTAINED_RESISTANCE_COEFF * cart_normal_load_n
    rolling_lat_n = hifi.CART_LATERAL_RESISTANCE_RATIO * rolling_long_n
    breakaway_body_n = np.array([hifi.CART_START_FORCE_MULTIPLIER * rolling_lat_n, hifi.CART_START_FORCE_MULTIPLIER * rolling_long_n], dtype=float)
    damping_long = 0.30 * cart_normal_load_n / max(scenario.target_speed_mps, 1.0e-6)
    damping_lat = hifi.CART_LATERAL_DAMPING_RATIO * damping_long
    yaw_damping = damping_long * ((hifi.CART_LENGTH_M**2 + hifi.CART_WIDTH_M**2) / 12.0)
    caster_align_gain_n = environment.swivel_resistance_scale * 0.090 * cart_normal_load_n
    caster_static_torque_nm = environment.swivel_resistance_scale * hifi.CART_SWIVEL_STATIC_FACTOR * cart_normal_load_n * hifi.CART_CASTER_TRAIL_M
    caster_tau_s = 0.18 * environment.caster_tau_scale
    robot_accel_limit = scenario.robot_max_accel_mps2 * environment.robot_accel_scale
    robot_force_hold_limit_n = scenario.robot_force_hold_limit_n
    robot_torque_hold_limit_nm = scenario.robot_torque_hold_limit_nm

    history = {
        "time_s": [],
        "phase": [],
        "segment_label": [],
        "robot_x_m": [],
        "robot_y_m": [],
        "robot_yaw_deg": [],
        "robot_speed_mps": [],
        "cart_x_m": [],
        "cart_y_m": [],
        "cart_yaw_deg": [],
        "cart_speed_mps": [],
        "relative_translation_mm": [],
        "relative_yaw_deg": [],
        "clearance_mm": [],
        "penetration_mm": [],
        "human_force_x_n": [],
        "human_force_y_n": [],
        "human_torque_nm": [],
        "magnetic_force_n": [],
        "magnetic_torque_nm": [],
        "cart_accel_mps2": [],
        "cart_yaw_accel_radps2": [],
        "caster_angle_deg": [],
        "robot_corridor_margin_mm": [],
        "cart_corridor_margin_mm": [],
        "corridor_breach_mm": [],
        "corridor_breach_active": [],
    } if record else None

    for step in range(steps):
        human_force_robot = arrays["human_force_robot_n"][step]
        human_force_world = body_to_world(robot_yaw_rad, human_force_robot)
        human_torque_nm = float(arrays["human_torque_nm"][step])

        relative_translation_body_m = base.rotmat(-robot_yaw_rad) @ (cart_position_world - robot_position_world)
        relative_yaw_rad = base.wrap_angle(cart_yaw_rad - robot_yaw_rad)
        sample = evaluate_pose_exact(assembly, relative_translation_body_m, relative_yaw_rad)
        min_gap_m = min(min_gap_m, sample.min_gap_m)
        max_penetration_m = max(max_penetration_m, sample.contact_penetration_m)

        magnetic_force_world = environment.magnetic_scale * body_to_world(robot_yaw_rad, sample.force_body_n)
        magnetic_torque_nm = environment.magnetic_scale * sample.torque_outer_nm
        robot_force_hold_n = float(np.linalg.norm(magnetic_force_world))
        if robot_force_hold_n > robot_force_hold_limit_n:
            robot_hold_force_exceeded_count += 1
        if abs(magnetic_torque_nm) > robot_torque_hold_limit_nm:
            robot_hold_torque_exceeded_count += 1

        desired_speed_mps = float(base.clamp(robot_speed_mps + arrays["robot_longitudinal_accel_mps2"][step] * dt_s, 0.0, scenario.target_speed_mps))
        robot_speed_mps += base.clamp(desired_speed_mps - robot_speed_mps, -robot_accel_limit * dt_s, robot_accel_limit * dt_s)
        yaw_target_rad = base.clamp(
            scenario.robot_heading_feedback_gain_rad_per_rad * relative_yaw_rad
            + scenario.robot_lateral_feedback_gain_rad_per_m * relative_translation_body_m[0]
            + scenario.robot_torque_feedback_gain_rad_per_nm * magnetic_torque_nm,
            -math.radians(28.0),
            math.radians(28.0),
        )
        desired_yaw_rate_radps = base.clamp(
            wrap_difference(yaw_target_rad, 0.0) / max(scenario.robot_heading_time_constant_s, 1.0e-4),
            -scenario.robot_max_yaw_rate_radps,
            scenario.robot_max_yaw_rate_radps,
        )
        robot_yaw_rate_radps += base.clamp(
            desired_yaw_rate_radps - robot_yaw_rate_radps,
            -scenario.robot_max_yaw_accel_radps2 * environment.robot_accel_scale * dt_s,
            scenario.robot_max_yaw_accel_radps2 * environment.robot_accel_scale * dt_s,
        )
        robot_yaw_rate_radps = base.clamp(robot_yaw_rate_radps, -scenario.robot_max_yaw_rate_radps, scenario.robot_max_yaw_rate_radps)
        robot_yaw_rad = base.wrap_angle(robot_yaw_rad + robot_yaw_rate_radps * dt_s)
        robot_velocity_world = body_to_world(robot_yaw_rad, np.array([0.0, robot_speed_mps], dtype=float))
        robot_position_world += robot_velocity_world * dt_s

        cart_velocity_body = base.rotmat(-cart_yaw_rad) @ cart_velocity_world
        cart_velocity_body = np.clip(
            np.nan_to_num(cart_velocity_body, nan=0.0, posinf=MAX_CART_SPEED_MPS, neginf=-MAX_CART_SPEED_MPS),
            -MAX_CART_SPEED_MPS,
            MAX_CART_SPEED_MPS,
        )
        caster_target_angle_rad = math.atan2(float(cart_velocity_body[0]), float(cart_velocity_body[1]) + 0.05)
        caster_angle_rad = base.wrap_angle(
            caster_angle_rad + wrap_difference(caster_target_angle_rad, caster_angle_rad) * dt_s / max(caster_tau_s, 1.0e-4)
        )
        caster_misalignment_rad = base.wrap_angle(caster_target_angle_rad - caster_angle_rad)
        passive_force_body = np.array(
            [
                -hifi.smooth_coulomb_component(cart_velocity_body[0], rolling_lat_n, hifi.CART_START_FORCE_MULTIPLIER, 0.65 * hifi.CART_STATIC_RESISTANCE_SPEED_MPS)
                - damping_lat * cart_velocity_body[0]
                - caster_align_gain_n * math.sin(caster_misalignment_rad),
                -hifi.smooth_coulomb_component(cart_velocity_body[1], rolling_long_n, hifi.CART_START_FORCE_MULTIPLIER, hifi.CART_STATIC_RESISTANCE_SPEED_MPS)
                - damping_long * cart_velocity_body[1],
            ],
            dtype=float,
        )
        net_force_world = human_force_world + magnetic_force_world + body_to_world(cart_yaw_rad, passive_force_body)
        net_torque_nm = (
            human_torque_nm
            + magnetic_torque_nm
            - yaw_damping * cart_yaw_rate_radps
            - caster_static_torque_nm * math.tanh((cart_yaw_rate_radps + 0.75 * caster_misalignment_rad) / hifi.CART_SWIVEL_STATIC_RATE_RADPS)
            - 0.55 * caster_align_gain_n * hifi.CART_CASTER_TRAIL_M * math.sin(caster_misalignment_rad)
        )

        net_force_body = base.rotmat(-cart_yaw_rad) @ net_force_world
        net_force_body = apply_cart_axis_stiction(net_force_body, cart_velocity_body, breakaway_body_n, 0.004)
        if abs(cart_yaw_rate_radps) <= 0.02 and abs(net_torque_nm) <= caster_static_torque_nm:
            net_torque_nm = 0.0
            cart_yaw_rate_radps = 0.0

        cart_accel_body = net_force_body / max(effective_cart_mass_kg, 1.0e-6)
        cart_accel_body = np.nan_to_num(cart_accel_body, nan=0.0, posinf=MAX_CART_ACCEL_MPS2, neginf=-MAX_CART_ACCEL_MPS2)
        cart_accel_world = body_to_world(cart_yaw_rad, cart_accel_body)
        cart_accel_norm = float(np.linalg.norm(cart_accel_world))
        if cart_accel_norm > MAX_CART_ACCEL_MPS2:
            cart_accel_world *= MAX_CART_ACCEL_MPS2 / max(cart_accel_norm, 1.0e-9)
            cart_accel_body = base.rotmat(-cart_yaw_rad) @ cart_accel_world
            dynamic_clip_count += 1
        cart_yaw_accel_radps2 = float(net_torque_nm / max(cart_inertia, 1.0e-6))
        if not math.isfinite(cart_yaw_accel_radps2):
            cart_yaw_accel_radps2 = 0.0
            dynamic_clip_count += 1
        elif abs(cart_yaw_accel_radps2) > MAX_CART_YAW_ACCEL_RADPS2:
            cart_yaw_accel_radps2 = math.copysign(MAX_CART_YAW_ACCEL_RADPS2, cart_yaw_accel_radps2)
            dynamic_clip_count += 1
        cart_velocity_world += cart_accel_world * dt_s
        clipped_speed = base.clamp_norm(cart_velocity_world, MAX_CART_SPEED_MPS)
        if float(np.linalg.norm(clipped_speed - cart_velocity_world)) > 1.0e-9:
            dynamic_clip_count += 1
        cart_velocity_world = clipped_speed
        cart_position_world += cart_velocity_world * dt_s
        cart_yaw_rate_radps += cart_yaw_accel_radps2 * dt_s
        if not math.isfinite(cart_yaw_rate_radps):
            cart_yaw_rate_radps = 0.0
            dynamic_clip_count += 1
        elif abs(cart_yaw_rate_radps) > MAX_CART_YAW_RATE_RADPS:
            cart_yaw_rate_radps = math.copysign(MAX_CART_YAW_RATE_RADPS, cart_yaw_rate_radps)
            dynamic_clip_count += 1
        cart_yaw_rad = base.wrap_angle(cart_yaw_rad + cart_yaw_rate_radps * dt_s)

        post_sample, post_residual_m = settle_nonpenetration_exact(
            assembly,
            robot_yaw_rad,
            cart_yaw_rad,
            robot_position_world,
            robot_velocity_world,
            cart_position_world,
            cart_velocity_world,
            effective_cart_mass_kg,
        )
        min_gap_m = min(min_gap_m, post_sample.min_gap_m)
        max_penetration_m = max(max_penetration_m, sample.contact_penetration_m, post_residual_m)

        if sample.contact_penetration_m > CONTACT_MARGIN_M or post_residual_m > CONTACT_MARGIN_M:
            if not in_contact:
                contact_events += 1
            in_contact = True
        else:
            in_contact = False

        relative_translation_body_m = base.rotmat(-robot_yaw_rad) @ (cart_position_world - robot_position_world)
        relative_yaw_rad = base.wrap_angle(cart_yaw_rad - robot_yaw_rad)
        if np.linalg.norm(relative_translation_body_m) > MAX_RELATIVE_TRANSLATION_M:
            relative_translation_body_m = (
                relative_translation_body_m / max(float(np.linalg.norm(relative_translation_body_m)), 1.0e-9)
            ) * MAX_RELATIVE_TRANSLATION_M
            cart_position_world = robot_position_world + body_to_world(robot_yaw_rad, relative_translation_body_m)
            dynamic_clip_count += 1
        if abs(relative_yaw_rad) > MAX_RELATIVE_YAW_RAD:
            relative_yaw_rad = math.copysign(MAX_RELATIVE_YAW_RAD, relative_yaw_rad)
            cart_yaw_rad = base.wrap_angle(robot_yaw_rad + relative_yaw_rad)
            cart_yaw_rate_radps = base.clamp(cart_yaw_rate_radps, -MAX_CART_YAW_RATE_RADPS, MAX_CART_YAW_RATE_RADPS)
            dynamic_clip_count += 1

        robot_box_world = rigid_box_world_points(
            hifi.ROBOT_WIDTH_M,
            hifi.ROBOT_LENGTH_M,
            robot_position_world,
            robot_yaw_rad,
        )
        cart_box_world = rigid_box_world_points(
            hifi.CART_WIDTH_M,
            hifi.CART_LENGTH_M,
            cart_position_world,
            cart_yaw_rad,
        )
        inner_ring_world = assembly.geometry.inner_points @ base.rotmat(robot_yaw_rad).T + robot_position_world
        outer_ring_world = assembly.geometry.outer_points_local @ base.rotmat(cart_yaw_rad).T + cart_position_world
        robot_envelope_world = np.vstack((robot_box_world, inner_ring_world))
        cart_envelope_world = np.vstack((cart_box_world, outer_ring_world))
        robot_corridor_margin_mm, robot_corridor_breach_mm = corridor_margin_and_breach_mm(
            robot_envelope_world,
            scenario.corridor_width_m,
        )
        cart_corridor_margin_mm, cart_corridor_breach_mm = corridor_margin_and_breach_mm(
            cart_envelope_world,
            scenario.corridor_width_m,
        )
        combined_corridor_breach_mm = max(robot_corridor_breach_mm, cart_corridor_breach_mm)
        if combined_corridor_breach_mm > 0.0:
            corridor_breach_count += 1
        min_robot_corridor_margin_mm = min(min_robot_corridor_margin_mm, robot_corridor_margin_mm)
        min_cart_corridor_margin_mm = min(min_cart_corridor_margin_mm, cart_corridor_margin_mm)
        max_corridor_breach_mm = max(max_corridor_breach_mm, combined_corridor_breach_mm)

        relative_translation_mm = 1000.0 * float(np.linalg.norm(relative_translation_body_m))
        relative_yaw_deg = abs(math.degrees(relative_yaw_rad))
        peak_relative_translation_mm = max(peak_relative_translation_mm, relative_translation_mm)
        peak_relative_yaw_deg = max(peak_relative_yaw_deg, relative_yaw_deg)
        max_cart_accel_mps2 = max(max_cart_accel_mps2, float(np.linalg.norm(cart_accel_world)))
        max_cart_yaw_accel_radps2 = max(max_cart_yaw_accel_radps2, abs(float(cart_yaw_accel_radps2)))

        phase_id = int(arrays["phase"][step])
        if phase_id >= 3:
            cue_peak_yaw_deg = max(cue_peak_yaw_deg, relative_yaw_deg)
            cue_peak_translation_mm = max(cue_peak_translation_mm, relative_translation_mm)
        if phase_id <= 2:
            cruise_translation_samples.append(relative_translation_mm)
            cruise_yaw_samples.append(relative_yaw_deg)

        if record:
            history["time_s"].append(float(arrays["time_s"][step]))
            history["phase"].append(phase_id)
            history["segment_label"].append(str(arrays["segment_label"][step]))
            history["robot_x_m"].append(float(robot_position_world[0]))
            history["robot_y_m"].append(float(robot_position_world[1]))
            history["robot_yaw_deg"].append(float(math.degrees(robot_yaw_rad)))
            history["robot_speed_mps"].append(float(robot_speed_mps))
            history["cart_x_m"].append(float(cart_position_world[0]))
            history["cart_y_m"].append(float(cart_position_world[1]))
            history["cart_yaw_deg"].append(float(math.degrees(cart_yaw_rad)))
            history["cart_speed_mps"].append(float(np.linalg.norm(cart_velocity_world)))
            history["relative_translation_mm"].append(relative_translation_mm)
            history["relative_yaw_deg"].append(relative_yaw_deg)
            history["clearance_mm"].append(1000.0 * float(post_sample.min_gap_m))
            history["penetration_mm"].append(1000.0 * float(max(sample.contact_penetration_m, post_residual_m)))
            history["human_force_x_n"].append(float(human_force_world[0]))
            history["human_force_y_n"].append(float(human_force_world[1]))
            history["human_torque_nm"].append(human_torque_nm)
            history["magnetic_force_n"].append(float(np.linalg.norm(magnetic_force_world)))
            history["magnetic_torque_nm"].append(float(magnetic_torque_nm))
            history["cart_accel_mps2"].append(float(np.linalg.norm(cart_accel_world)))
            history["cart_yaw_accel_radps2"].append(float(cart_yaw_accel_radps2))
            history["caster_angle_deg"].append(float(math.degrees(caster_angle_rad)))
            history["robot_corridor_margin_mm"].append(float(robot_corridor_margin_mm))
            history["cart_corridor_margin_mm"].append(float(cart_corridor_margin_mm))
            history["corridor_breach_mm"].append(float(combined_corridor_breach_mm))
            history["corridor_breach_active"].append(int(combined_corridor_breach_mm > 0.0))

    cruise_translation_rms_mm = float(np.sqrt(np.mean(np.square(cruise_translation_samples)))) if cruise_translation_samples else 0.0
    cruise_yaw_rms_deg = float(np.sqrt(np.mean(np.square(cruise_yaw_samples)))) if cruise_yaw_samples else 0.0
    score = 0.0
    score += 160.0 * min(cue_peak_yaw_deg / 6.0, 1.6)
    score -= 90.0 * max(max_penetration_m * 1000.0, 0.0)
    score -= 60.0 * contact_events
    score -= 90.0 * corridor_breach_count
    score -= 70.0 * max_corridor_breach_mm
    score -= 12.0 * cruise_translation_rms_mm
    score -= 18.0 * cruise_yaw_rms_deg
    score -= 10.0 * max(0.0, max_cart_accel_mps2 - 1.8)
    score -= 18.0 * max(0.0, max_cart_yaw_accel_radps2 - 3.2)
    score -= 20.0 * robot_hold_force_exceeded_count
    score -= 20.0 * robot_hold_torque_exceeded_count
    score -= 8.0 * dynamic_clip_count

    return DynamicOutcome(
        score=float(score),
        scenario_name=scenario.name,
        environment_label=environment.label,
        min_clearance_mm=1000.0 * float(min_gap_m),
        max_penetration_mm=1000.0 * float(max_penetration_m),
        contact_events=int(contact_events),
        min_robot_corridor_margin_mm=float(min_robot_corridor_margin_mm),
        min_cart_corridor_margin_mm=float(min_cart_corridor_margin_mm),
        corridor_breach_count=int(corridor_breach_count),
        max_corridor_breach_mm=float(max_corridor_breach_mm),
        peak_relative_translation_mm=float(peak_relative_translation_mm),
        peak_relative_yaw_deg=float(peak_relative_yaw_deg),
        cruise_relative_translation_rms_mm=float(cruise_translation_rms_mm),
        cruise_relative_yaw_rms_deg=float(cruise_yaw_rms_deg),
        cue_peak_yaw_deg=float(cue_peak_yaw_deg),
        cue_peak_translation_mm=float(cue_peak_translation_mm),
        max_cart_accel_mps2=float(max_cart_accel_mps2),
        max_cart_yaw_accel_radps2=float(max_cart_yaw_accel_radps2),
        robot_hold_force_exceeded_count=int(robot_hold_force_exceeded_count),
        robot_hold_torque_exceeded_count=int(robot_hold_torque_exceeded_count),
        dynamic_clip_count=int(dynamic_clip_count),
        history=history,
    )


def candidate_priority(static_assessment: StaticAssessment, dynamic_outcomes):
    total_contact = sum(outcome.contact_events for outcome in dynamic_outcomes)
    max_penetration_mm = max(outcome.max_penetration_mm for outcome in dynamic_outcomes)
    hold_force_exceeded = sum(outcome.robot_hold_force_exceeded_count for outcome in dynamic_outcomes)
    hold_torque_exceeded = sum(outcome.robot_hold_torque_exceeded_count for outcome in dynamic_outcomes)
    dynamic_clip_total = sum(outcome.dynamic_clip_count for outcome in dynamic_outcomes)
    corridor_breach_total = sum(outcome.corridor_breach_count for outcome in dynamic_outcomes)
    max_corridor_breach_mm = max(outcome.max_corridor_breach_mm for outcome in dynamic_outcomes)
    worst_clearance_mm = min(outcome.min_clearance_mm for outcome in dynamic_outcomes)
    mean_dynamic_score = float(np.mean([outcome.score for outcome in dynamic_outcomes]))
    realistic_mass_ok = int(static_assessment.cart_mass_kg >= REALISTIC_MIN_CART_MASS_KG)
    feasible = int(
        realistic_mass_ok
        and static_assessment.package_violation_m <= 0.0
        and static_assessment.bad_attraction_count == 0
        and static_assessment.negative_restore_count == 0
        and static_assessment.negative_yaw_restore_count == 0
        and total_contact == 0
        and max_penetration_mm <= 0.0
        and hold_force_exceeded == 0
        and hold_torque_exceeded == 0
        and dynamic_clip_total == 0
        and corridor_breach_total == 0
        and max_corridor_breach_mm <= 0.0
        and worst_clearance_mm >= 2.0
    )
    ranking_score = (
        300.0 * feasible
        + 0.03 * static_assessment.score
        + mean_dynamic_score
        - 45.0 * total_contact
        - 400.0 * max_penetration_mm
        - 15.0 * hold_force_exceeded
        - 15.0 * hold_torque_exceeded
        - 6.0 * dynamic_clip_total
        - 45.0 * corridor_breach_total
        - 500.0 * max_corridor_breach_mm
        - 20000.0 * (1 - realistic_mass_ok)
    )
    return feasible, ranking_score


def evaluate_dynamic_suite(
    assembly: FreeArrayAssembly,
    scenarios=None,
    record_best_history=False,
    seed=0,
    replica_count=3,
):
    if scenarios is None:
        scenarios = [build_avoid_return_scenario(), build_straight_lateral_pulse_scenario()]
    outcomes = []
    for scenario in scenarios:
        nominal = simulate_fixedheight_episode(assembly, scenario, build_nominal_environment(), record=record_best_history)
        outcomes.append(nominal)
        for replica_index in range(1, replica_count):
            outcomes.append(
                simulate_fixedheight_episode(
                    assembly,
                    scenario,
                    sample_environment(seed + 1000 * hash(scenario.name) % 100000, replica_index),
                    record=False,
                )
            )
    return outcomes


def optimize_case(
    outdir: Path,
    inner_count,
    outer_count,
    cart_mass_kg,
    magnet_layers,
    seed,
    evaluations,
    population,
    dynamic_replica_count=3,
    dynamic_scenarios=None,
    dynamic_candidate_limit=3,
    initial_mean=None,
    sigma0=1.0,
    tensorboard_writer=None,
    tensorboard_case_prefix=None,
    on_generation_update=None,
):
    if cma is None:
        raise RuntimeError("The 'cma' package is required for this optimizer.")
    dimension = latent_dimension(inner_count, outer_count)
    rng = np.random.default_rng(seed)
    archive = []
    evaluated = []

    def evaluate_latent(latent_vector):
        design = build_design_from_latent(latent_vector, inner_count, outer_count, cart_mass_kg, magnet_layers)
        assembly = build_assembly(design)
        static_assessment = assess_static_design(
            assembly,
            directions_rad=FAST_DIRECTIONS_RAD,
            displacements_m=FAST_SEARCH_DISPLACEMENTS_M,
            yaw_samples_rad=FAST_SEARCH_YAW_RAD,
            tow_offsets=(0.004,),
        )
        evaluated.append(
            {
                "design": design,
                "assembly": assembly,
                "static": static_assessment,
                "latent": np.asarray(latent_vector, dtype=float).copy(),
            }
        )
        return -static_assessment.score

    if initial_mean is None:
        cma_mean = np.zeros(dimension, dtype=float)
    else:
        cma_mean = np.asarray(initial_mean, dtype=float).copy()
        if cma_mean.shape != (dimension,):
            raise ValueError(f"initial_mean shape {cma_mean.shape} does not match expected {(dimension,)}")
        cma_mean = np.clip(cma_mean, -3.9, 3.9)
    es = cma.CMAEvolutionStrategy(
        cma_mean.tolist(),
        float(sigma0),
        {
            "seed": int(seed),
            "popsize": max(4, int(population)),
            "bounds": [[-4.0] * dimension, [4.0] * dimension],
            "verbose": -9,
            "maxfevals": int(evaluations),
        },
    )
    history_rows = []
    while not es.stop():
        population_vectors = es.ask()
        values = [evaluate_latent(vector) for vector in population_vectors]
        es.tell(population_vectors, values)
        ranked = sorted(evaluated[-len(population_vectors) :], key=lambda item: item["static"].score, reverse=True)
        best_static = ranked[0]
        archive.extend(ranked[: min(3, len(ranked))])
        history_rows.append(
            {
                "generation": len(history_rows),
                "best_static_score": float(best_static["static"].score),
                "mean_static_score": float(np.mean([-value for value in values])),
                "inner_count": int(inner_count),
                "outer_count": int(outer_count),
                "cart_mass_kg": float(cart_mass_kg),
                "sigma": float(es.sigma),
            }
        )
        if tensorboard_writer is not None and tensorboard_case_prefix:
            generation_index = len(history_rows) - 1
            tensorboard_writer.add_scalar(
                f"{tensorboard_case_prefix}/static/best_score",
                float(best_static["static"].score),
                generation_index,
            )
            tensorboard_writer.add_scalar(
                f"{tensorboard_case_prefix}/static/mean_score",
                float(np.mean([-value for value in values])),
                generation_index,
            )
            tensorboard_writer.add_scalar(
                f"{tensorboard_case_prefix}/optimizer/sigma",
                float(es.sigma),
                generation_index,
            )
        if on_generation_update is not None:
            on_generation_update(
                {
                    "generation": int(len(history_rows) - 1),
                    "evaluations_used": int(len(evaluated)),
                    "sigma": float(es.sigma),
                    "best_static_score": float(best_static["static"].score),
                    "mean_static_score": float(np.mean([-value for value in values])),
                    "design": best_static["design"],
                    "assembly": best_static["assembly"],
                    "static": best_static["static"],
                }
            )
        if len(evaluated) >= evaluations:
            break

    unique_candidates = []
    seen = set()
    for candidate in sorted(archive, key=lambda item: item["static"].score, reverse=True):
        signature = (
            tuple(np.round(candidate["design"].inner_angles_rad, 5)),
            tuple(np.round(candidate["design"].outer_angles_rad, 5)),
            tuple(np.round(candidate["design"].inner_radii_m, 5)),
            tuple(np.round(candidate["design"].outer_radii_m, 5)),
            tuple(np.round(candidate["design"].inner_tilt_rad, 5)),
            tuple(np.round(candidate["design"].outer_tilt_rad, 5)),
        )
        if signature in seen:
            continue
        seen.add(signature)
        candidate = dict(candidate)
        candidate["static"] = assess_static_design(candidate["assembly"])
        unique_candidates.append(candidate)
        if len(unique_candidates) >= max(1, int(dynamic_candidate_limit)):
            break

    case_rows = []
    champion = None
    champion_outcomes = None
    for rank, candidate in enumerate(unique_candidates, start=1):
        outcomes = evaluate_dynamic_suite(
            candidate["assembly"],
            scenarios=dynamic_scenarios,
            record_best_history=False,
            seed=seed + 5000 + rank,
            replica_count=dynamic_replica_count,
        )
        feasible, ranking_score = candidate_priority(candidate["static"], outcomes)
        row = {
            "candidate_rank": rank,
            "inner_count": inner_count,
            "outer_count": outer_count,
            "cart_mass_kg": float(cart_mass_kg),
            "magnet_layers": magnet_layers,
            "realistic_mass_ok": int(candidate["static"].cart_mass_kg >= REALISTIC_MIN_CART_MASS_KG),
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
            "ranking_score": float(ranking_score),
            "feasible": int(feasible),
        }
        case_rows.append(row)
        if tensorboard_writer is not None and tensorboard_case_prefix:
            tensorboard_writer.add_scalar(
                f"{tensorboard_case_prefix}/dynamic/ranking_score",
                float(ranking_score),
                rank - 1,
            )
            tensorboard_writer.add_scalar(
                f"{tensorboard_case_prefix}/dynamic/worst_clearance_mm",
                float(row["worst_clearance_mm"]),
                rank - 1,
            )
            tensorboard_writer.add_scalar(
                f"{tensorboard_case_prefix}/dynamic/max_penetration_mm",
                float(row["max_penetration_mm"]),
                rank - 1,
            )
            tensorboard_writer.add_scalar(
                f"{tensorboard_case_prefix}/dynamic/contact_events_total",
                int(row["contact_events_total"]),
                rank - 1,
            )
        if champion is None or (row["feasible"], row["ranking_score"]) > (
            int(candidate_priority(champion["static"], champion_outcomes)[0]),
            float(candidate_priority(champion["static"], champion_outcomes)[1]),
        ):
            champion = candidate
            champion_outcomes = outcomes

    history_df = pd.DataFrame(history_rows)
    case_df = pd.DataFrame(case_rows).sort_values(["feasible", "ranking_score"], ascending=[False, False])
    history_df.to_csv(outdir / f"history_{inner_count}in_{outer_count}out_{str(cart_mass_kg).replace('.', 'p')}kg.csv", index=False)
    case_df.to_csv(outdir / f"dynamic_rank_{inner_count}in_{outer_count}out_{str(cart_mass_kg).replace('.', 'p')}kg.csv", index=False)
    (outdir / f"best_case_{inner_count}in_{outer_count}out_{str(cart_mass_kg).replace('.', 'p')}kg.json").write_text(
        json.dumps(
            {
                "design": design_to_dict(champion["design"]),
                "latent_vector": serializable_array(champion["latent"]),
                "static_assessment": static_assessment_to_dict(champion["static"]),
                "dynamic_outcomes": [outcome_to_dict(outcome) for outcome in champion_outcomes],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return champion, champion_outcomes, history_df, case_df


def plot_design_layout(assembly: FreeArrayAssembly, outpath: Path):
    figure, axis = plt.subplots(figsize=(6.6, 6.6))
    axis.plot(
        np.append(assembly.geometry.inner_points[:, 0], assembly.geometry.inner_points[0, 0]),
        np.append(assembly.geometry.inner_points[:, 1], assembly.geometry.inner_points[0, 1]),
        color="#111827",
        linewidth=1.5,
        label="inner support",
    )
    axis.plot(
        np.append(assembly.geometry.outer_points_local[:, 0], assembly.geometry.outer_points_local[0, 0]),
        np.append(assembly.geometry.outer_points_local[:, 1], assembly.geometry.outer_points_local[0, 1]),
        color="#2563eb",
        linewidth=1.5,
        label="outer support",
    )
    axis.scatter(assembly.inner_mount_points_xy[:, 0], assembly.inner_mount_points_xy[:, 1], color="#111827", s=28)
    axis.scatter(assembly.outer_mount_points_xy[:, 0], assembly.outer_mount_points_xy[:, 1], color="#2563eb", s=28)
    axis.quiver(
        assembly.inner_centers_xyz[:, 0],
        assembly.inner_centers_xyz[:, 1],
        assembly.inner_dirs_xyz[:, 0],
        assembly.inner_dirs_xyz[:, 1],
        color="#111827",
        scale=24.0,
        width=0.004,
    )
    axis.quiver(
        assembly.outer_centers_local_xyz[:, 0],
        assembly.outer_centers_local_xyz[:, 1],
        assembly.outer_dirs_local_xyz[:, 0],
        assembly.outer_dirs_local_xyz[:, 1],
        color="#2563eb",
        scale=24.0,
        width=0.004,
    )
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("x [m]")
    axis.set_ylabel("y [m]")
    axis.set_title("Free Magnet Array Layout (Fixed Height)")
    axis.legend(loc="upper right")
    axis.grid(True, alpha=0.22)
    figure.tight_layout()
    figure.savefig(outpath, dpi=180)
    plt.close(figure)


def plot_field_map(assembly: FreeArrayAssembly, outpath: Path, grid_size: int = 81):
    if magpy is None:
        return
    sku = base.MAGNET_CATALOG_BY_ID[assembly.design.magnet_sku_id]
    sources = list(assembly.inner_sources)
    for center_xyz, dir_xyz in zip(assembly.outer_centers_local_xyz, assembly.outer_dirs_local_xyz):
        sources.append(
            cylinder_object(
                center_xyz,
                dir_xyz,
                assembly.design.effective_flux_t,
                sku.tangential_length_m,
                sku.radial_depth_m,
                as_target=False,
            )
        )
    span = max(
        float(np.max(np.linalg.norm(assembly.geometry.outer_points_local, axis=1))),
        float(np.max(np.linalg.norm(assembly.geometry.inner_points, axis=1))),
    ) + 0.05
    grid = np.linspace(-span, span, max(21, int(grid_size)))
    xx, yy = np.meshgrid(grid, grid)
    points = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(xx.size)))
    field = np.asarray(magpy.getB(magpy.Collection(*sources), points, squeeze=True), dtype=float)
    magnitude_mt = 1000.0 * np.linalg.norm(field.reshape(-1, 3), axis=1).reshape(xx.shape)
    figure, axis = plt.subplots(figsize=(6.6, 6.2))
    image = axis.contourf(xx, yy, magnitude_mt, levels=18, cmap="magma")
    axis.plot(assembly.geometry.inner_points[:, 0], assembly.geometry.inner_points[:, 1], color="white", linewidth=1.0)
    axis.plot(assembly.geometry.outer_points_local[:, 0], assembly.geometry.outer_points_local[:, 1], color="#93c5fd", linewidth=1.0)
    axis.set_aspect("equal", adjustable="box")
    axis.set_xlabel("x [m]")
    axis.set_ylabel("y [m]")
    axis.set_title("Magnetic Flux Density Magnitude at z = 0")
    figure.colorbar(image, ax=axis, label="|B| [mT]")
    figure.tight_layout()
    figure.savefig(outpath, dpi=180)
    plt.close(figure)


def plot_dynamic_history(outcome: DynamicOutcome, outpath: Path):
    if outcome.history is None:
        return
    history = outcome.history
    time_s = np.asarray(history["time_s"], dtype=float)
    figure, axes = plt.subplots(5, 1, figsize=(10.4, 11.6), sharex=True)
    axes[0].plot(time_s, history["relative_translation_mm"], linewidth=2.0, color="#0f766e")
    axes[0].set_ylabel("Rel XY [mm]")
    axes[0].grid(True, alpha=0.24)
    axes[1].plot(time_s, history["relative_yaw_deg"], linewidth=2.0, color="#2563eb")
    axes[1].set_ylabel("Rel yaw [deg]")
    axes[1].grid(True, alpha=0.24)
    axes[2].plot(time_s, history["clearance_mm"], linewidth=2.0, color="#7c3aed")
    axes[2].plot(time_s, history["penetration_mm"], linewidth=1.2, color="#dc2626")
    axes[2].set_ylabel("Gap [mm]")
    axes[2].grid(True, alpha=0.24)
    axes[3].plot(time_s, history["human_force_x_n"], linewidth=1.8, color="#dc2626", label="human Fx")
    axes[3].plot(time_s, history["human_force_y_n"], linewidth=1.8, color="#ea580c", label="human Fy")
    axes[3].plot(time_s, history["magnetic_force_n"], linewidth=1.5, color="#15803d", label="magnetic |F|")
    axes[3].set_ylabel("Force [N]")
    axes[3].grid(True, alpha=0.24)
    axes[3].legend(loc="upper right", fontsize=8)
    axes[4].plot(time_s, history["magnetic_torque_nm"], linewidth=1.8, color="#1d4ed8", label="mag torque")
    axes[4].plot(time_s, history["cart_accel_mps2"], linewidth=1.4, color="#b45309", label="cart accel")
    axes[4].set_ylabel("Torque/Accel")
    axes[4].set_xlabel("Time [s]")
    axes[4].grid(True, alpha=0.24)
    axes[4].legend(loc="upper right", fontsize=8)
    figure.suptitle(outcome.scenario_name)
    figure.tight_layout()
    figure.savefig(outpath, dpi=180)
    plt.close(figure)


def render_candidate_artifacts(
    design: FreeArrayDesign,
    outdir: Path,
    *,
    scenarios=None,
    dynamic_replica_count: int = 1,
    field_grid_size: int = 81,
    video_stem: str = "candidate",
):
    """Rebuilds one candidate and exports its heavy visual assets after optimization."""

    outdir.mkdir(parents=True, exist_ok=True)
    assembly = build_assembly(design)
    scenario_list = tuple(scenarios) if scenarios is not None else (build_avoid_return_scenario(),)
    dynamic_outcomes = evaluate_dynamic_suite(
        assembly,
        scenarios=scenario_list,
        record_best_history=False,
        seed=0,
        replica_count=max(1, int(dynamic_replica_count)),
    )
    nominal_outcome = None
    for outcome in dynamic_outcomes:
        if outcome.environment_label == "nominal" and outcome.scenario_name == scenario_list[0].name:
            nominal_outcome = outcome
            break
    if nominal_outcome is None:
        nominal_outcome = dynamic_outcomes[0]
    if nominal_outcome.history is None:
        nominal_outcome = simulate_fixedheight_episode(
            assembly,
            scenario_list[0],
            build_nominal_environment(),
            record=True,
        )

    plot_design_layout(assembly, outdir / f"{video_stem}_layout.png")
    plot_field_map(assembly, outdir / f"{video_stem}_field_map.png", grid_size=field_grid_size)
    plot_dynamic_history(nominal_outcome, outdir / f"{video_stem}_dynamic.png")
    if render_fixedheight_corridor_video is not None:
        render_fixedheight_corridor_video(
            assembly=assembly,
            scenario=scenario_list[0],
            outcome=nominal_outcome,
            outpath=outdir / f"{video_stem}.mp4",
            title_text=f"{video_stem} | {assembly.pitch_descriptor}",
            footer_text=scenario_list[0].name,
            playback_speed=LIVE_CORRIDOR_PLAYBACK_SPEED,
            output_fps=LIVE_CORRIDOR_OUTPUT_FPS,
            frame_stride=LIVE_CORRIDOR_FRAME_STRIDE,
        )

    dynamic_df = report_tables(design, assess_static_design(assembly), dynamic_outcomes)
    dynamic_df.to_csv(outdir / f"{video_stem}_dynamic_summary.csv", index=False)
    return {
        "assembly": assembly,
        "dynamic_outcomes": dynamic_outcomes,
        "dynamic_df": dynamic_df,
        "nominal_outcome": nominal_outcome,
    }


def report_tables(best_design, static_assessment, dynamic_outcomes):
    dynamic_rows = []
    for outcome in dynamic_outcomes:
        dynamic_rows.append(
            {
                "scenario_name": outcome.scenario_name,
                "environment_label": outcome.environment_label,
                "min_clearance_mm": outcome.min_clearance_mm,
                "max_penetration_mm": outcome.max_penetration_mm,
                "contact_events": outcome.contact_events,
                "min_robot_corridor_margin_mm": outcome.min_robot_corridor_margin_mm,
                "min_cart_corridor_margin_mm": outcome.min_cart_corridor_margin_mm,
                "corridor_breach_count": outcome.corridor_breach_count,
                "max_corridor_breach_mm": outcome.max_corridor_breach_mm,
                "peak_relative_translation_mm": outcome.peak_relative_translation_mm,
                "peak_relative_yaw_deg": outcome.peak_relative_yaw_deg,
                "cruise_relative_translation_rms_mm": outcome.cruise_relative_translation_rms_mm,
                "cruise_relative_yaw_rms_deg": outcome.cruise_relative_yaw_rms_deg,
                "cue_peak_yaw_deg": outcome.cue_peak_yaw_deg,
                "cue_peak_translation_mm": outcome.cue_peak_translation_mm,
                "max_cart_accel_mps2": outcome.max_cart_accel_mps2,
                "max_cart_yaw_accel_radps2": outcome.max_cart_yaw_accel_radps2,
                "robot_hold_force_exceeded_count": outcome.robot_hold_force_exceeded_count,
                "robot_hold_torque_exceeded_count": outcome.robot_hold_torque_exceeded_count,
                "dynamic_clip_count": outcome.dynamic_clip_count,
                "score": outcome.score,
            }
        )
    return pd.DataFrame(dynamic_rows)


def scenario_description_lines(scenarios):
    lines = []
    for scenario in scenarios:
        segment_desc = []
        for segment in scenario.segments:
            segment_desc.append(
                (
                    f"{segment.start_s:.1f}-{segment.end_s:.1f} s "
                    f"{segment.label}: ax={segment.robot_longitudinal_accel_mps2:+.2f} m/s^2, "
                    f"Fx={segment.human_force_robot_x_n:+.2f} N, "
                    f"Fy={segment.human_force_robot_y_n:+.2f} N, "
                    f"Tau={segment.human_torque_nm:+.2f} N m"
                )
            )
        lines.append(
            f"- Scenario `{scenario.name}`: target speed {scenario.target_speed_mps:.2f} m/s; "
            + " | ".join(segment_desc)
        )
    return lines


def build_report_markdown(
    outdir: Path,
    design: FreeArrayDesign,
    static_assessment: StaticAssessment,
    dynamic_df: pd.DataFrame,
    scenarios=None,
):
    scenarios = scenarios or [build_avoid_return_scenario(), build_straight_lateral_pulse_scenario()]
    worst_row = dynamic_df.loc[dynamic_df["score"].idxmin()]
    best_row = dynamic_df.loc[dynamic_df["score"].idxmax()]
    lines = [
        "# Free-Array Fixed-Height Magnetic Coupler Study",
        "",
        "## Summary",
        f"- Magnet model in optimization loop: `Magpylib 5.2.3 getFT()` exact force/torque with analytical permanent-magnet fields and meshed target bodies.",
        f"- Magnet SKU: `{design.magnet_sku_id}`",
        f"- Inner/outer magnet counts: `{design.inner_count}` / `{design.outer_count}`",
        f"- Magnet layers: `{design.magnet_layers}`",
        f"- Cart mass used for optimization: `{design.cart_mass_kg:.3f} kg`",
        f"- Realistic payload gate (`>= {REALISTIC_MIN_CART_MASS_KG:.1f} kg`): `{'PASS' if design.cart_mass_kg >= REALISTIC_MIN_CART_MASS_KG else 'FAIL (screening only)'}`",
        f"- Static score: `{static_assessment.score:.3f}`",
        f"- Aligned physical clearance: `{1000.0 * static_assessment.aligned_clearance_m:.3f} mm`",
        f"- Worst dynamic clearance: `{dynamic_df['min_clearance_mm'].min():.3f} mm`",
        f"- Worst dynamic penetration: `{dynamic_df['max_penetration_mm'].max():.3f} mm`",
        f"- Total dynamic contact events: `{int(dynamic_df['contact_events'].sum())}`",
        f"- Total corridor-breach frames: `{int(dynamic_df['corridor_breach_count'].sum())}`",
        f"- Worst corridor breach: `{dynamic_df['max_corridor_breach_mm'].max():.3f} mm`",
        "",
        "## Why This Differs From The Previous Model",
        "- Height modulation is disabled; the study is fixed-height only.",
        "- Inner and outer rings are independent: unequal counts, unequal spacing, unequal radii, and independent mounting angles are all allowed.",
        "- The force model is no longer optimized only with the dipole-cloud approximation; Magpylib exact force/torque evaluation is used directly inside the free-array study.",
        "- The robot is no longer treated as a freely dragged point mass during normal transport; it follows a bounded-speed, bounded-acceleration command, and hold-limit exceedance is tracked explicitly.",
        "- The cart includes Coulomb-like rolling resistance, breakaway thresholds, viscous damping, and a first-order caster reorientation lag.",
        "",
        "## Selected Design",
        f"- Inner angles [deg]: `{', '.join(f'{v:.1f}' for v in [math.degrees(x) for x in design.inner_angles_rad])}`",
        f"- Inner radii [mm]: `{', '.join(f'{1000.0 * x:.1f}' for x in design.inner_radii_m)}`",
        f"- Inner tilt [deg]: `{', '.join(f'{math.degrees(x):.1f}' for x in design.inner_tilt_rad)}`",
        f"- Outer angles [deg]: `{', '.join(f'{v:.1f}' for v in [math.degrees(x) for x in design.outer_angles_rad])}`",
        f"- Outer radii [mm]: `{', '.join(f'{1000.0 * x:.1f}' for x in design.outer_radii_m)}`",
        f"- Outer tilt [deg]: `{', '.join(f'{math.degrees(x):.1f}' for x in design.outer_tilt_rad)}`",
        "",
        "## Static Metrics",
        f"- Scaled Hessian eigenvalues: `{', '.join(f'{v:.4f}' for v in static_assessment.scaled_eigenvalues)}`",
        f"- Lateral stiffness Kxx: `{static_assessment.lateral_stiffness_npm:.3f} N/m`",
        f"- Forward stiffness Kyy: `{static_assessment.forward_stiffness_npm:.3f} N/m`",
        f"- Yaw stiffness Kpp: `{static_assessment.yaw_stiffness_nmp_rad:.3f} N m/rad`",
        f"- Cross-coupling ratio: `{static_assessment.cross_coupling_ratio:.4f}`",
        f"- Mean orthogonal leakage ratio: `{static_assessment.mean_orthogonal_ratio:.4f}`",
        f"- Mean force linearity R2: `{static_assessment.mean_linearity_r2:.4f}`",
        f"- Negative restoring samples: `{static_assessment.negative_restore_count}`",
        f"- Negative yaw restoring samples: `{static_assessment.negative_yaw_restore_count}`",
        f"- Bad-attraction samples: `{static_assessment.bad_attraction_count}`",
        f"- Packaging violation: `{1000.0 * static_assessment.package_violation_m:.3f} mm`",
        f"- Realistic-mass requirement: `{static_assessment.cart_mass_kg:.3f} kg >= {REALISTIC_MIN_CART_MASS_KG:.1f} kg` is `{'true' if static_assessment.cart_mass_kg >= REALISTIC_MIN_CART_MASS_KG else 'false'}`",
        "",
        "## Explicit Dynamic Test Conditions",
        "- Robot: AgileX LIMO-compatible surrogate, mass 4.2 kg, target speed 0.45 m/s, acceleration limit 0.80 m/s^2, yaw-rate limit 0.80 rad/s, yaw-acceleration limit 2.20 rad/s^2.",
        f"- Cart: mass as optimized above, rolling-resistance baseline coefficient {hifi.CART_SUSTAINED_RESISTANCE_COEFF:.3f}, lateral resistance ratio {hifi.CART_LATERAL_RESISTANCE_RATIO:.1f}, caster trail {1000.0 * hifi.CART_CASTER_TRAIL_M:.0f} mm.",
        "- Contact model: non-penetration projection constraint. Interpenetrating poses are not passed to the magnetic solver, and any predicted overlap is counted as a failure demand.",
        "- Uncertainty envelopes: magnetic scale +/-7%, cart mass +/-10%, rolling resistance +/-18%, swivel resistance +/-20%, caster time constant +/-15%, robot acceleration +/-10%.",
        *scenario_description_lines(scenarios),
        "",
        "## Dynamic Highlights",
        f"- Best dynamic case: `{best_row['scenario_name']} / {best_row['environment_label']}` score `{best_row['score']:.3f}`",
        f"- Worst dynamic case: `{worst_row['scenario_name']} / {worst_row['environment_label']}` score `{worst_row['score']:.3f}`",
        f"- Worst clearance: `{dynamic_df['min_clearance_mm'].min():.3f} mm`",
        f"- Worst penetration: `{dynamic_df['max_penetration_mm'].max():.3f} mm`",
        f"- Minimum robot corridor margin: `{dynamic_df['min_robot_corridor_margin_mm'].min():.3f} mm`",
        f"- Minimum cart corridor margin: `{dynamic_df['min_cart_corridor_margin_mm'].min():.3f} mm`",
        f"- Total corridor-breach frames: `{int(dynamic_df['corridor_breach_count'].sum())}`",
        f"- Worst corridor breach: `{dynamic_df['max_corridor_breach_mm'].max():.3f} mm`",
        f"- Peak relative translation: `{dynamic_df['peak_relative_translation_mm'].max():.3f} mm`",
        f"- Peak relative yaw: `{dynamic_df['peak_relative_yaw_deg'].max():.3f} deg`",
        f"- Peak cue yaw: `{dynamic_df['cue_peak_yaw_deg'].max():.3f} deg`",
        f"- Max cart acceleration: `{dynamic_df['max_cart_accel_mps2'].max():.3f} m/s^2`",
        f"- Max cart yaw acceleration: `{dynamic_df['max_cart_yaw_accel_radps2'].max():.3f} rad/s^2`",
        f"- Robot hold-force exceedances total: `{int(dynamic_df['robot_hold_force_exceeded_count'].sum())}`",
        f"- Robot hold-torque exceedances total: `{int(dynamic_df['robot_hold_torque_exceeded_count'].sum())}`",
        f"- Dynamic clipping interventions total: `{int(dynamic_df['dynamic_clip_count'].sum())}`",
        "",
        "## Sources",
        "- Magpylib physics and analytical-solution notes: https://magpylib.readthedocs.io/en/latest/_pages/user_guide/guide_resources_01_physics.html",
        "- Magpylib force/torque interface: https://magpylib.readthedocs.io/en/5.2.1/_pages/user_guide/docs/docs_forcecomp.html",
        "- AgileX LIMO specifications: https://docs.trossenrobotics.com/agilex_limo_docs/specifications/limo.html",
        "- Caster-wheel transient model with first-order transfer function: https://www.iieta.org/download/file/fid/53900",
        "- Rolling resistance and scrub torque measurement abstract: https://pubmed.ncbi.nlm.nih.gov/31891276/",
        "- Domain randomization for sim-to-real transfer: https://arxiv.org/abs/2110.03239",
        "- Static-friction sensitivity in sim-to-real RL: https://arxiv.org/abs/2503.01255",
        "",
        "## Current Main-Branch Model Fidelity Check",
        "- The previous selected solution used a dipole-cloud optimizer and only cross-checked representative poses against Magpylib afterwards.",
        "- Existing cross-check numbers were mean force error 0.0775 N, max force error 0.2752 N, mean torque error 0.1448 N m, max torque error 0.5241 N m.",
        "- Therefore the old model was not physically meaningless, but it still did not use the exact analytical magnet model inside the search loop itself.",
    ]
    (outdir / "freearray_fixedheight_report_ja.md").write_text("\n".join(lines), encoding="utf-8")


def build_report_tex(outdir: Path):
    import re

    report_md = (outdir / "freearray_fixedheight_report_ja.md").read_text(encoding="utf-8")

    def escape_tex(text: str) -> str:
        return (
            text.replace("\\", "\\textbackslash{}")
            .replace("&", "\\&")
            .replace("%", "\\%")
            .replace("#", "\\#")
            .replace("_", "\\_")
            .replace("^", "\\^{}")
            .replace("~", "\\~{}")
            .replace("{", "\\{")
            .replace("}", "\\}")
        )

    def inline_tex(text: str) -> str:
        parts = re.split(r"(`[^`]*`)", text)
        rendered = []
        for part in parts:
            if part.startswith("`") and part.endswith("`") and len(part) >= 2:
                rendered.append("\\texttt{" + escape_tex(part[1:-1]) + "}")
            else:
                rendered.append(escape_tex(part))
        return "".join(rendered)

    lines = []
    for raw_line in report_md.splitlines():
        if raw_line.startswith("# "):
            lines.append(f"\\section*{{{escape_tex(raw_line[2:])}}}")
        elif raw_line.startswith("## "):
            lines.append(f"\\subsection*{{{escape_tex(raw_line[3:])}}}")
        elif raw_line.startswith("- "):
            lines.append("\\begin{itemize}" if not lines or lines[-1] != "\\begin{itemize}" else "")
            lines.append(f"\\item {inline_tex(raw_line[2:])}")
        else:
            if lines and lines[-1] == "\\begin{itemize}" and raw_line == "":
                continue
            if lines and lines[-1].startswith("\\item") and raw_line == "":
                lines.append("\\end{itemize}")
            elif raw_line:
                lines.append(inline_tex(raw_line) + "\\\\")
            else:
                lines.append("")
    compact_lines = []
    itemize_open = False
    for line in lines:
        if line == "\\begin{itemize}":
            if not itemize_open:
                compact_lines.append(line)
                itemize_open = True
            continue
        if line == "\\end{itemize}":
            if itemize_open:
                compact_lines.append(line)
                itemize_open = False
            continue
        if line.startswith("\\section") or line.startswith("\\subsection"):
            if itemize_open:
                compact_lines.append("\\end{itemize}")
                itemize_open = False
            compact_lines.append(line)
            continue
        compact_lines.append(line)
    if itemize_open:
        compact_lines.append("\\end{itemize}")

    tex = "\n".join(
        [
            "\\documentclass[a4paper,11pt]{article}",
            "\\usepackage[margin=20mm]{geometry}",
            "\\usepackage{fontspec}",
            "\\usepackage{xeCJK}",
            "\\setmainfont{Times New Roman}",
            "\\setmonofont{Consolas}",
            "\\setCJKmainfont{Yu Mincho}",
            "\\setCJKmonofont{Yu Gothic UI}",
            "\\usepackage{graphicx}",
            "\\usepackage{amsmath}",
            "\\setlength{\\parskip}{0.4em}",
            "\\setlength{\\parindent}{1em}",
            "\\begin{document}",
            "\\section*{Figures}",
            "\\begin{figure}[h]",
            "\\centering",
            "\\includegraphics[width=0.72\\linewidth]{selected_layout.png}",
            "\\caption{Selected free-array geometry and magnet orientations.}",
            "\\end{figure}",
            "\\begin{figure}[h]",
            "\\centering",
            "\\includegraphics[width=0.72\\linewidth]{selected_field_map.png}",
            "\\caption{Magnetic flux density magnitude map at z = 0.}",
            "\\end{figure}",
            "\\begin{figure}[h]",
            "\\centering",
            "\\includegraphics[width=0.88\\linewidth]{selected_dynamic_nominal.png}",
            "\\caption{Nominal avoid/return dynamic history of the selected design.}",
            "\\end{figure}",
            "\\clearpage",
            *compact_lines,
            "\\end{document}",
        ]
    )
    tex_path = outdir / "freearray_fixedheight_report_ja.tex"
    tex_path.write_text(tex, encoding="utf-8")
    return tex_path


def compile_report_pdf(tex_path: Path):
    import subprocess

    subprocess.run(
        ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
        cwd=str(tex_path.parent),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    subprocess.run(
        ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
        cwd=str(tex_path.parent),
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_fixedheight_freearray_search(
    outdir: Path,
    seed: int = 20260705,
    evaluations_per_case: int = 24,
    population: int = 6,
    count_pairs: tuple[tuple[int, int], ...] = ((6, 8), (8, 8), (4, 8)),
    cart_mass_values_kg: tuple[float, ...] = (10.0, 12.0, 15.0),
    magnet_layers_values: tuple[int, ...] = (1,),
    dynamic_replica_count: int = 3,
    dynamic_scenarios=None,
    dynamic_candidate_limit: int = 3,
    live_dynamic_stride_generations: int = 5,
    live_shape_stride_generations: int = 10,
    live_field_stride_generations: int = 0,
    live_video_stride_generations: int = 0,
    live_field_grid_size: int = 41,
):
    if magpy is None:
        raise RuntimeError("magpylib is required for the free-array fixed-height study.")
    outdir.mkdir(parents=True, exist_ok=True)
    generation_video_dir = outdir / "generation_videos"
    generation_video_dir.mkdir(parents=True, exist_ok=True)
    for live_name in (
        "live_monitor_state.json",
        "live_design_history.csv",
        "live_shape_and_magnets.png",
        "live_field_distribution.png",
        "live_corridor_generation_latest.mp4",
        "live_corridor_generation_latest_poster.png",
    ):
        live_path = outdir / live_name
        if live_path.exists():
            live_path.unlink()
    for child in generation_video_dir.iterdir():
        if child.is_file():
            child.unlink()
    dynamic_scenario_list = tuple(dynamic_scenarios) if dynamic_scenarios is not None else (
        build_avoid_return_scenario(),
        build_straight_lateral_pulse_scenario(),
    )
    tensorboard_writer = SummaryWriter(logdir=str(outdir / "tensorboard")) if SummaryWriter is not None else None
    all_case_rows = []
    champion = None
    champion_outcomes = None
    champion_static = None
    champion_assembly = None
    champion_latent = None
    total_cases = len(magnet_layers_values) * len(cart_mass_values_kg) * len(count_pairs)
    case_index = 0
    campaign_live_history_rows = []
    campaign_generation_counter = 0
    campaign_best_static_score = -float("inf")
    campaign_best_design = None
    campaign_best_static = None
    campaign_best_assembly = None
    last_live_dynamic_monitor = None
    last_live_video_meta = None

    def write_live_state(payload: dict):
        payload = dict(payload)
        payload["updated_at_epoch_s"] = float(time.time())
        write_json_atomic(outdir / "live_monitor_state.json", payload)

    def refresh_live_history():
        if campaign_live_history_rows:
            pd.DataFrame(campaign_live_history_rows).to_csv(outdir / "live_design_history.csv", index=False)

    write_live_state(
        {
            "stage": "design_search",
            "status": "running",
            "run_args": {
                "design_optimizer": "cmaes",
                "evaluations_per_case": int(evaluations_per_case),
                "population": int(population),
                "dynamic_replica_count": int(dynamic_replica_count),
                "dynamic_candidate_limit": int(dynamic_candidate_limit),
                "dynamic_scenario_names": [scenario.name for scenario in dynamic_scenario_list],
                "live_dynamic_stride_generations": int(live_dynamic_stride_generations),
                "live_shape_stride_generations": int(live_shape_stride_generations),
                "live_field_stride_generations": int(live_field_stride_generations),
                "live_video_stride_generations": int(live_video_stride_generations),
            },
            "campaign": {
                "total_cases": int(total_cases),
                "completed_cases": 0,
            },
        }
    )

    for magnet_layers in magnet_layers_values:
        for cart_mass_kg in cart_mass_values_kg:
            for inner_count, outer_count in count_pairs:
                case_index += 1
                case_outdir = outdir / f"{inner_count}in_{outer_count}out_{str(cart_mass_kg).replace('.', 'p')}kg_{magnet_layers}layer"
                case_outdir.mkdir(parents=True, exist_ok=True)
                manifest_payload = write_latent_variable_manifest(
                    case_outdir / "latent_variable_manifest.json",
                    inner_count=inner_count,
                    outer_count=outer_count,
                )
                tensorboard_case_prefix = (
                    f"case_{case_index:02d}/"
                    f"{inner_count}in_{outer_count}out_{str(cart_mass_kg).replace('.', 'p')}kg_{magnet_layers}layer"
                )
                print(
                    f"[case {case_index}/{total_cases}] start inner={inner_count} outer={outer_count} "
                    f"mass={cart_mass_kg:.3f}kg layers={magnet_layers}",
                    flush=True,
                )
                if tensorboard_writer is not None:
                    tensorboard_writer.add_text(
                        f"{tensorboard_case_prefix}/manifest",
                        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
                        0,
                    )
                write_live_state(
                    {
                        "stage": "design_search",
                        "status": "running",
                        "run_args": {
                            "design_optimizer": "cmaes",
                            "evaluations_per_case": int(evaluations_per_case),
                            "population": int(population),
                            "dynamic_replica_count": int(dynamic_replica_count),
                            "dynamic_candidate_limit": int(dynamic_candidate_limit),
                            "dynamic_scenario_names": [scenario.name for scenario in dynamic_scenario_list],
                            "live_dynamic_stride_generations": int(live_dynamic_stride_generations),
                            "live_shape_stride_generations": int(live_shape_stride_generations),
                            "live_field_stride_generations": int(live_field_stride_generations),
                            "live_video_stride_generations": int(live_video_stride_generations),
                        },
                        "campaign": {
                            "total_cases": int(total_cases),
                            "completed_cases": int(case_index - 1),
                        },
                        "current_case": {
                            "index": int(case_index),
                            "total": int(total_cases),
                            "inner_count": int(inner_count),
                            "outer_count": int(outer_count),
                            "cart_mass_kg": float(cart_mass_kg),
                            "magnet_layers": int(magnet_layers),
                            "label": case_outdir.name,
                        },
                        "design_search_complete": {
                            "best_score": float(campaign_best_static_score) if math.isfinite(campaign_best_static_score) else None,
                        },
                        "final_shape_label": campaign_best_assembly.pitch_descriptor if campaign_best_assembly is not None else None,
                        "selected_design_pre_policy": (
                            design_monitor_summary(campaign_best_design, campaign_best_assembly)
                            if campaign_best_design is not None and campaign_best_assembly is not None
                            else None
                        ),
                        "final_design": design_to_dict(campaign_best_design) if campaign_best_design is not None else None,
                        "final_static_assessment": static_assessment_to_dict(campaign_best_static) if campaign_best_static is not None else None,
                    }
                )

                def on_generation_update(event: dict, _case_index=case_index, _case_name=case_outdir.name):
                    nonlocal campaign_generation_counter
                    nonlocal campaign_best_static_score
                    nonlocal campaign_best_design
                    nonlocal campaign_best_static
                    nonlocal campaign_best_assembly
                    nonlocal last_live_dynamic_monitor
                    nonlocal last_live_video_meta
                    campaign_generation_counter += 1
                    static_assessment = event["static"]
                    current_best_score = float(event["best_static_score"])
                    current_design_summary = design_monitor_summary(event["design"], event["assembly"])
                    nominal_live_outcome = None
                    live_dynamic_monitor = None
                    live_video_meta = None
                    generation_index_local = int(event["generation"])
                    should_update_dynamic = int(live_dynamic_stride_generations) > 0 and (
                        generation_index_local % int(live_dynamic_stride_generations) == 0
                    )
                    should_update_shape = int(live_shape_stride_generations) > 0 and (
                        generation_index_local % int(live_shape_stride_generations) == 0
                    )
                    should_update_field = int(live_field_stride_generations) > 0 and (
                        generation_index_local % int(live_field_stride_generations) == 0
                    )
                    should_update_video = int(live_video_stride_generations) > 0 and (
                        generation_index_local % int(live_video_stride_generations) == 0
                    )
                    try:
                        if dynamic_scenario_list and should_update_dynamic:
                            nominal_live_outcome = simulate_fixedheight_episode(
                                event["assembly"],
                                dynamic_scenario_list[0],
                                build_nominal_environment(),
                                record=bool(should_update_video),
                            )
                            live_dynamic_monitor = {
                                "scenario_name": nominal_live_outcome.scenario_name,
                                "environment_label": nominal_live_outcome.environment_label,
                                "score": float(nominal_live_outcome.score),
                                "min_clearance_mm": float(nominal_live_outcome.min_clearance_mm),
                                "max_penetration_mm": float(nominal_live_outcome.max_penetration_mm),
                                "contact_events": int(nominal_live_outcome.contact_events),
                                "min_robot_corridor_margin_mm": float(nominal_live_outcome.min_robot_corridor_margin_mm),
                                "min_cart_corridor_margin_mm": float(nominal_live_outcome.min_cart_corridor_margin_mm),
                                "corridor_breach_count": int(nominal_live_outcome.corridor_breach_count),
                                "max_corridor_breach_mm": float(nominal_live_outcome.max_corridor_breach_mm),
                                "cue_peak_yaw_deg": float(nominal_live_outcome.cue_peak_yaw_deg),
                                "cue_peak_translation_mm": float(nominal_live_outcome.cue_peak_translation_mm),
                                "cruise_translation_rms_mm": float(nominal_live_outcome.cruise_relative_translation_rms_mm),
                                "cruise_yaw_rms_deg": float(nominal_live_outcome.cruise_relative_yaw_rms_deg),
                                "dynamic_clip_count": int(nominal_live_outcome.dynamic_clip_count),
                            }
                    except Exception as error:
                        live_dynamic_monitor = {
                            "scenario_name": dynamic_scenario_list[0].name if dynamic_scenario_list else None,
                            "error": str(error),
                        }
                    if live_dynamic_monitor is not None and "score" in live_dynamic_monitor:
                        last_live_dynamic_monitor = dict(live_dynamic_monitor)
                    campaign_best_static_score = max(campaign_best_static_score, current_best_score)
                    live_row = {
                        "generation": int(campaign_generation_counter),
                        "case_generation": int(event["generation"]),
                        "case_index": int(_case_index),
                        "case_label": str(_case_name),
                        "evaluations_used": int(event["evaluations_used"]),
                        "optimizer": "cmaes",
                        "best_score": current_best_score,
                        "global_best_score": float(campaign_best_static_score),
                        "mean_score": float(event["mean_static_score"]),
                        "sigma": float(event["sigma"]),
                        "mean_constraint_violation": float(static_constraint_violation_proxy(static_assessment)),
                        "feasible_rate": float(static_feasible_proxy(static_assessment)),
                    }
                    if live_dynamic_monitor is not None and "score" in live_dynamic_monitor:
                        live_row.update(
                            {
                                "corridor_score": float(live_dynamic_monitor["score"]),
                                "corridor_min_clearance_mm": float(live_dynamic_monitor["min_clearance_mm"]),
                                "corridor_max_penetration_mm": float(live_dynamic_monitor["max_penetration_mm"]),
                                "corridor_contact_events": int(live_dynamic_monitor["contact_events"]),
                                "corridor_min_robot_margin_mm": float(live_dynamic_monitor["min_robot_corridor_margin_mm"]),
                                "corridor_min_cart_margin_mm": float(live_dynamic_monitor["min_cart_corridor_margin_mm"]),
                                "corridor_breach_count": int(live_dynamic_monitor["corridor_breach_count"]),
                                "corridor_max_breach_mm": float(live_dynamic_monitor["max_corridor_breach_mm"]),
                                "corridor_cue_peak_yaw_deg": float(live_dynamic_monitor["cue_peak_yaw_deg"]),
                                "corridor_cue_peak_translation_mm": float(live_dynamic_monitor["cue_peak_translation_mm"]),
                            }
                        )
                    campaign_live_history_rows.append(live_row)
                    refresh_live_history()
                    if should_update_shape:
                        try:
                            plot_design_layout(event["assembly"], outdir / "live_shape_and_magnets.png")
                        except Exception as error:
                            if live_dynamic_monitor is None:
                                live_dynamic_monitor = {"scenario_name": dynamic_scenario_list[0].name if dynamic_scenario_list else None}
                            live_dynamic_monitor["shape_error"] = str(error)
                    if should_update_field:
                        try:
                            plot_field_map(
                                event["assembly"],
                                outdir / "live_field_distribution.png",
                                grid_size=live_field_grid_size,
                            )
                        except Exception as error:
                            if live_dynamic_monitor is None:
                                live_dynamic_monitor = {"scenario_name": dynamic_scenario_list[0].name if dynamic_scenario_list else None}
                            live_dynamic_monitor["field_error"] = str(error)
                    if (
                        nominal_live_outcome is not None
                        and nominal_live_outcome.history is not None
                        and should_update_video
                        and render_fixedheight_corridor_video is not None
                    ):
                        try:
                            generation_video_path = generation_video_dir / (
                                f"{_case_name}_gen{int(event['generation']):04d}_corridor.mp4"
                            )
                            live_video_meta = render_fixedheight_corridor_video(
                                assembly=event["assembly"],
                                scenario=dynamic_scenario_list[0],
                                outcome=nominal_live_outcome,
                                outpath=generation_video_path,
                                title_text=f"{_case_name} | generation {int(event['generation']):03d}",
                                footer_text=(
                                    f"{dynamic_scenario_list[0].name} | evals {int(event['evaluations_used'])} | "
                                    f"sigma {float(event['sigma']):.4f}"
                                ),
                                playback_speed=LIVE_CORRIDOR_PLAYBACK_SPEED,
                                output_fps=LIVE_CORRIDOR_OUTPUT_FPS,
                                frame_stride=LIVE_CORRIDOR_FRAME_STRIDE,
                            )
                            copy_artifact_atomic(generation_video_path, outdir / "live_corridor_generation_latest.mp4")
                            poster_source = Path(live_video_meta["poster_path"])
                            if poster_source.exists():
                                copy_artifact_atomic(poster_source, outdir / "live_corridor_generation_latest_poster.png")
                            last_live_video_meta = dict(live_video_meta)
                        except Exception as error:
                            if live_dynamic_monitor is None:
                                live_dynamic_monitor = {"scenario_name": dynamic_scenario_list[0].name if dynamic_scenario_list else None}
                            live_dynamic_monitor["video_error"] = str(error)
                    if live_dynamic_monitor is not None and "score" in live_dynamic_monitor:
                        last_live_dynamic_monitor = dict(live_dynamic_monitor)
                    if tensorboard_writer is not None and tensorboard_case_prefix and live_dynamic_monitor is not None and "score" in live_dynamic_monitor:
                        generation_index = len(campaign_live_history_rows) - 1
                        tensorboard_writer.add_scalar(
                            f"{tensorboard_case_prefix}/corridor_nominal/score",
                            float(live_dynamic_monitor["score"]),
                            generation_index,
                        )
                        tensorboard_writer.add_scalar(
                            f"{tensorboard_case_prefix}/corridor_nominal/min_clearance_mm",
                            float(live_dynamic_monitor["min_clearance_mm"]),
                            generation_index,
                        )
                        tensorboard_writer.add_scalar(
                            f"{tensorboard_case_prefix}/corridor_nominal/max_penetration_mm",
                            float(live_dynamic_monitor["max_penetration_mm"]),
                            generation_index,
                        )
                        tensorboard_writer.add_scalar(
                            f"{tensorboard_case_prefix}/corridor_nominal/min_robot_corridor_margin_mm",
                            float(live_dynamic_monitor["min_robot_corridor_margin_mm"]),
                            generation_index,
                        )
                        tensorboard_writer.add_scalar(
                            f"{tensorboard_case_prefix}/corridor_nominal/min_cart_corridor_margin_mm",
                            float(live_dynamic_monitor["min_cart_corridor_margin_mm"]),
                            generation_index,
                        )
                        tensorboard_writer.add_scalar(
                            f"{tensorboard_case_prefix}/corridor_nominal/max_corridor_breach_mm",
                            float(live_dynamic_monitor["max_corridor_breach_mm"]),
                            generation_index,
                        )
                        tensorboard_writer.add_scalar(
                            f"{tensorboard_case_prefix}/corridor_nominal/cue_peak_yaw_deg",
                            float(live_dynamic_monitor["cue_peak_yaw_deg"]),
                            generation_index,
                        )
                    if current_best_score >= campaign_best_static_score - 1.0e-12:
                        campaign_best_design = event["design"]
                        campaign_best_static = static_assessment
                        campaign_best_assembly = event["assembly"]
                    write_live_state(
                        {
                            "stage": "design_search",
                            "status": "running",
                            "run_args": {
                                "design_optimizer": "cmaes",
                                "evaluations_per_case": int(evaluations_per_case),
                                "population": int(population),
                                "dynamic_replica_count": int(dynamic_replica_count),
                                "dynamic_candidate_limit": int(dynamic_candidate_limit),
                                "dynamic_scenario_names": [scenario.name for scenario in dynamic_scenario_list],
                                "live_dynamic_stride_generations": int(live_dynamic_stride_generations),
                                "live_shape_stride_generations": int(live_shape_stride_generations),
                                "live_field_stride_generations": int(live_field_stride_generations),
                                "live_video_stride_generations": int(live_video_stride_generations),
                            },
                            "campaign": {
                                "total_cases": int(total_cases),
                                "completed_cases": int(_case_index - 1),
                            },
                            "current_case": {
                                "index": int(_case_index),
                                "total": int(total_cases),
                                "label": str(_case_name),
                                "generation": int(event["generation"]),
                                "evaluations_used": int(event["evaluations_used"]),
                                "sigma": float(event["sigma"]),
                            },
                            "design_search_complete": {
                                "best_score": float(campaign_best_static_score),
                            },
                            "final_shape_label": event["assembly"].pitch_descriptor,
                            "selected_design_pre_policy": current_design_summary,
                            "campaign_best_shape_label": campaign_best_assembly.pitch_descriptor if campaign_best_assembly is not None else None,
                            "campaign_best_pre_policy": (
                                design_monitor_summary(campaign_best_design, campaign_best_assembly)
                                if campaign_best_design is not None and campaign_best_assembly is not None
                                else None
                            ),
                            "primary_corridor_monitor": last_live_dynamic_monitor,
                            "latest_video": last_live_video_meta,
                            "final_design": design_to_dict(campaign_best_design) if campaign_best_design is not None else None,
                            "final_static_assessment": static_assessment_to_dict(campaign_best_static) if campaign_best_static is not None else None,
                        }
                    )

                candidate, candidate_outcomes, history_df, case_df = optimize_case(
                    outdir=case_outdir,
                    inner_count=inner_count,
                    outer_count=outer_count,
                    cart_mass_kg=cart_mass_kg,
                    magnet_layers=magnet_layers,
                    seed=seed + 97 * len(all_case_rows),
                    evaluations=evaluations_per_case,
                    population=population,
                    dynamic_replica_count=dynamic_replica_count,
                    dynamic_scenarios=dynamic_scenario_list,
                    dynamic_candidate_limit=dynamic_candidate_limit,
                    tensorboard_writer=tensorboard_writer,
                    tensorboard_case_prefix=tensorboard_case_prefix,
                    on_generation_update=on_generation_update,
                )
                candidate["outcomes"] = candidate_outcomes
                feasible, ranking_score = candidate_priority(candidate["static"], candidate_outcomes)
                dynamic_summary = {
                    "mean_score": float(np.mean([outcome.score for outcome in candidate_outcomes])),
                    "worst_score": float(np.min([outcome.score for outcome in candidate_outcomes])),
                    "contact_events_total": int(sum(outcome.contact_events for outcome in candidate_outcomes)),
                    "worst_clearance_mm": float(min(outcome.min_clearance_mm for outcome in candidate_outcomes)),
                    "max_penetration_mm": float(max(outcome.max_penetration_mm for outcome in candidate_outcomes)),
                    "min_robot_corridor_margin_mm": float(
                        min(outcome.min_robot_corridor_margin_mm for outcome in candidate_outcomes)
                    ),
                    "min_cart_corridor_margin_mm": float(
                        min(outcome.min_cart_corridor_margin_mm for outcome in candidate_outcomes)
                    ),
                    "corridor_breach_total": int(sum(outcome.corridor_breach_count for outcome in candidate_outcomes)),
                    "max_corridor_breach_mm": float(max(outcome.max_corridor_breach_mm for outcome in candidate_outcomes)),
                }
                all_case_rows.append(
                    {
                        "inner_count": inner_count,
                        "outer_count": outer_count,
                        "cart_mass_kg": cart_mass_kg,
                        "magnet_layers": magnet_layers,
                        "realistic_mass_ok": int(candidate["static"].cart_mass_kg >= REALISTIC_MIN_CART_MASS_KG),
                        "static_score": candidate["static"].score,
                        "ranking_score": ranking_score,
                        "feasible": int(feasible),
                        "worst_clearance_mm": min(outcome.min_clearance_mm for outcome in candidate_outcomes),
                        "max_penetration_mm": max(outcome.max_penetration_mm for outcome in candidate_outcomes),
                        "contact_events_total": int(sum(outcome.contact_events for outcome in candidate_outcomes)),
                        "min_robot_corridor_margin_mm": min(
                            outcome.min_robot_corridor_margin_mm for outcome in candidate_outcomes
                        ),
                        "min_cart_corridor_margin_mm": min(
                            outcome.min_cart_corridor_margin_mm for outcome in candidate_outcomes
                        ),
                        "corridor_breach_total": int(sum(outcome.corridor_breach_count for outcome in candidate_outcomes)),
                        "max_corridor_breach_mm": max(outcome.max_corridor_breach_mm for outcome in candidate_outcomes),
                        "robot_hold_force_exceeded_total": int(sum(outcome.robot_hold_force_exceeded_count for outcome in candidate_outcomes)),
                        "robot_hold_torque_exceeded_total": int(sum(outcome.robot_hold_torque_exceeded_count for outcome in candidate_outcomes)),
                        "dynamic_clip_total": int(sum(outcome.dynamic_clip_count for outcome in candidate_outcomes)),
                    }
                )
                print(
                    f"[case {case_index}/{total_cases}] done "
                    f"feasible={int(feasible)} ranking={ranking_score:.3f} "
                    f"worst_clearance_mm={min(outcome.min_clearance_mm for outcome in candidate_outcomes):.3f} "
                    f"max_penetration_mm={max(outcome.max_penetration_mm for outcome in candidate_outcomes):.3f} "
                    f"max_corridor_breach_mm={max(outcome.max_corridor_breach_mm for outcome in candidate_outcomes):.3f}",
                    flush=True,
                )
                if tensorboard_writer is not None:
                    tensorboard_writer.add_scalar(f"{tensorboard_case_prefix}/summary/feasible", int(feasible), 0)
                    tensorboard_writer.add_scalar(f"{tensorboard_case_prefix}/summary/ranking_score", float(ranking_score), 0)
                    tensorboard_writer.add_scalar(
                        f"{tensorboard_case_prefix}/summary/worst_clearance_mm",
                        float(min(outcome.min_clearance_mm for outcome in candidate_outcomes)),
                        0,
                    )
                    tensorboard_writer.add_scalar(
                        f"{tensorboard_case_prefix}/summary/max_penetration_mm",
                        float(max(outcome.max_penetration_mm for outcome in candidate_outcomes)),
                        0,
                    )
                if champion is None or (int(feasible), float(ranking_score)) > (
                    int(candidate_priority(champion_static, champion_outcomes)[0]),
                    float(candidate_priority(champion_static, champion_outcomes)[1]),
                ):
                    champion = candidate["design"]
                    champion_outcomes = candidate_outcomes
                    champion_static = candidate["static"]
                    champion_assembly = candidate["assembly"]
                    champion_latent = np.asarray(candidate["latent"], dtype=float).copy()
                write_live_state(
                    {
                        "stage": "design_search",
                        "status": "running",
                        "run_args": {
                            "design_optimizer": "cmaes",
                            "evaluations_per_case": int(evaluations_per_case),
                            "population": int(population),
                            "dynamic_replica_count": int(dynamic_replica_count),
                            "dynamic_candidate_limit": int(dynamic_candidate_limit),
                            "dynamic_scenario_names": [scenario.name for scenario in dynamic_scenario_list],
                            "live_dynamic_stride_generations": int(live_dynamic_stride_generations),
                            "live_shape_stride_generations": int(live_shape_stride_generations),
                            "live_field_stride_generations": int(live_field_stride_generations),
                            "live_video_stride_generations": int(live_video_stride_generations),
                        },
                        "campaign": {
                            "total_cases": int(total_cases),
                            "completed_cases": int(case_index),
                        },
                        "current_case": {
                            "index": int(case_index),
                            "total": int(total_cases),
                            "inner_count": int(inner_count),
                            "outer_count": int(outer_count),
                            "cart_mass_kg": float(cart_mass_kg),
                            "magnet_layers": int(magnet_layers),
                            "label": case_outdir.name,
                        },
                        "latest_case_result": {
                            "feasible": int(feasible),
                            "ranking_score": float(ranking_score),
                            "worst_clearance_mm": dynamic_summary["worst_clearance_mm"],
                            "max_penetration_mm": dynamic_summary["max_penetration_mm"],
                            "min_robot_corridor_margin_mm": dynamic_summary["min_robot_corridor_margin_mm"],
                            "min_cart_corridor_margin_mm": dynamic_summary["min_cart_corridor_margin_mm"],
                            "corridor_breach_total": dynamic_summary["corridor_breach_total"],
                            "max_corridor_breach_mm": dynamic_summary["max_corridor_breach_mm"],
                        },
                        "dynamic_validation": dynamic_summary,
                        "final_summary": {
                            "static_validation_score": float(campaign_best_static_score) if math.isfinite(campaign_best_static_score) else None,
                            "dynamic_validation_mean_score": dynamic_summary["mean_score"],
                            "worst_clearance_mm": dynamic_summary["worst_clearance_mm"],
                            "max_contact_demand_mm": dynamic_summary["max_penetration_mm"],
                            "dynamic_contact_events_total": dynamic_summary["contact_events_total"],
                            "min_robot_corridor_margin_mm": dynamic_summary["min_robot_corridor_margin_mm"],
                            "min_cart_corridor_margin_mm": dynamic_summary["min_cart_corridor_margin_mm"],
                            "corridor_breach_total": dynamic_summary["corridor_breach_total"],
                            "max_corridor_breach_mm": dynamic_summary["max_corridor_breach_mm"],
                        },
                        "final_shape_label": campaign_best_assembly.pitch_descriptor if campaign_best_assembly is not None else None,
                        "selected_design_pre_policy": (
                            design_monitor_summary(campaign_best_design, campaign_best_assembly)
                            if campaign_best_design is not None and campaign_best_assembly is not None
                            else None
                        ),
                        "final_design": design_to_dict(campaign_best_design) if campaign_best_design is not None else None,
                        "final_static_assessment": static_assessment_to_dict(campaign_best_static) if campaign_best_static is not None else None,
                    }
                )

    case_df = pd.DataFrame(all_case_rows).sort_values(["feasible", "ranking_score"], ascending=[False, False])
    case_df.to_csv(outdir / "case_summary.csv", index=False)

    nominal_dynamic = None
    for outcome in champion_outcomes:
        if outcome.environment_label == "nominal" and outcome.scenario_name == dynamic_scenario_list[0].name:
            nominal_dynamic = outcome
            break
    if nominal_dynamic is None:
        nominal_dynamic = champion_outcomes[0]
    if nominal_dynamic.history is None:
        nominal_dynamic = simulate_fixedheight_episode(
            champion_assembly,
            dynamic_scenario_list[0],
            build_nominal_environment(),
            record=True,
        )
        refreshed = []
        replaced = False
        for outcome in champion_outcomes:
            if outcome.environment_label == "nominal" and outcome.scenario_name == nominal_dynamic.scenario_name and not replaced:
                refreshed.append(nominal_dynamic)
                replaced = True
            else:
                refreshed.append(outcome)
        champion_outcomes = refreshed

    final_render_errors = []
    try:
        plot_design_layout(champion_assembly, outdir / "selected_layout.png")
    except Exception as error:
        final_render_errors.append(f"layout: {error}")
    try:
        plot_field_map(champion_assembly, outdir / "selected_field_map.png")
    except Exception as error:
        final_render_errors.append(f"field: {error}")
    try:
        plot_dynamic_history(nominal_dynamic, outdir / "selected_dynamic_nominal.png")
    except Exception as error:
        final_render_errors.append(f"dynamic_plot: {error}")
    if render_fixedheight_corridor_video is not None:
        try:
            render_fixedheight_corridor_video(
                assembly=champion_assembly,
                scenario=dynamic_scenario_list[0],
                outcome=nominal_dynamic,
                outpath=outdir / "selected_dynamic_nominal.mp4",
                title_text=f"selected design | {champion_assembly.pitch_descriptor}",
                footer_text=dynamic_scenario_list[0].name,
                playback_speed=LIVE_CORRIDOR_PLAYBACK_SPEED,
                output_fps=LIVE_CORRIDOR_OUTPUT_FPS,
                frame_stride=LIVE_CORRIDOR_FRAME_STRIDE,
            )
        except Exception as error:
            final_render_errors.append(f"video: {error}")
    dynamic_df = report_tables(champion, champion_static, champion_outcomes)
    dynamic_df.to_csv(outdir / "selected_dynamic_summary.csv", index=False)
    (outdir / "selected_design.json").write_text(
        json.dumps(
            {
                "design": design_to_dict(champion),
                "latent_vector": serializable_array(champion_latent),
                "static_assessment": static_assessment_to_dict(champion_static),
                "dynamic_outcomes": [outcome_to_dict(outcome) for outcome in champion_outcomes],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        build_report_markdown(outdir, champion, champion_static, dynamic_df, scenarios=dynamic_scenario_list)
    except Exception as error:
        final_render_errors.append(f"report_md: {error}")
    try:
        tex_path = build_report_tex(outdir)
        compile_report_pdf(tex_path)
    except Exception as error:
        final_render_errors.append(f"report_pdf: {error}")
    write_live_state(
        {
            "stage": "completed",
            "status": "completed",
            "run_args": {
                "design_optimizer": "cmaes",
                "evaluations_per_case": int(evaluations_per_case),
                "population": int(population),
                "dynamic_replica_count": int(dynamic_replica_count),
                "dynamic_candidate_limit": int(dynamic_candidate_limit),
                "dynamic_scenario_names": [scenario.name for scenario in dynamic_scenario_list],
                "live_dynamic_stride_generations": int(live_dynamic_stride_generations),
                "live_shape_stride_generations": int(live_shape_stride_generations),
                "live_field_stride_generations": int(live_field_stride_generations),
                "live_video_stride_generations": int(live_video_stride_generations),
            },
            "campaign": {
                "total_cases": int(total_cases),
                "completed_cases": int(total_cases),
            },
            "final_shape_label": champion_assembly.pitch_descriptor,
            "selected_design_pre_policy": design_monitor_summary(champion, champion_assembly),
            "final_design": design_to_dict(champion),
            "final_static_assessment": static_assessment_to_dict(champion_static),
            "dynamic_validation": {
                "mean_score": float(dynamic_df["score"].mean()),
                "worst_score": float(dynamic_df["score"].min()),
                "contact_events_total": int(dynamic_df["contact_events"].sum()),
                "worst_clearance_mm": float(dynamic_df["min_clearance_mm"].min()),
                "max_penetration_mm": float(dynamic_df["max_penetration_mm"].max()),
            },
            "final_render_errors": final_render_errors,
            "final_summary": {
                "static_validation_score": float(champion_static.score),
                "dynamic_validation_mean_score": float(dynamic_df["score"].mean()),
                "worst_clearance_mm": float(dynamic_df["min_clearance_mm"].min()),
                "max_contact_demand_mm": float(dynamic_df["max_penetration_mm"].max()),
                "dynamic_contact_events_total": int(dynamic_df["contact_events"].sum()),
            },
        }
    )
    if tensorboard_writer is not None:
        tensorboard_writer.flush()
        tensorboard_writer.close()
    return {
        "design": champion,
        "static_assessment": champion_static,
        "dynamic_df": dynamic_df,
        "case_df": case_df,
        "outdir": outdir,
    }
