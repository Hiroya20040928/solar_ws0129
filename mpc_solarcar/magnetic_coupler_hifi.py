import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, replace
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
    from scipy.spatial.transform import Rotation as SciRotation
except Exception:
    magpy = None
    SciRotation = None

matplotlib.use("Agg")

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_rl as base


MU0 = base.MU0
LIVE_MONITOR_DIR: Path | None = None
LIVE_MONITOR_LOCK = threading.Lock()
SEARCH_DIPOLE_GRID = (1, 1, 1)
VALIDATION_DIPOLE_GRID = (2, 1, 1)
FIELD_DIPOLE_GRID = (2, 2, 2)
SEARCH_HEIGHT_FRACTIONS = np.array([0.0, 0.2, 0.4, 0.65, 0.85, 0.95], dtype=float)
SEARCH_DISPLACEMENTS_M = np.array([0.002, 0.004, 0.006, 0.008, 0.010], dtype=float)
VALIDATION_DISPLACEMENTS_M = np.array([0.002, 0.004, 0.006, 0.008, 0.010], dtype=float)
COARSE_PRESEARCH_DISPLACEMENTS_M = np.array([0.003, 0.006, 0.009], dtype=float)
SEARCH_YAW_RAD = np.radians(
    np.array([1.0, 2.0, 4.0, 8.0, 12.0, 20.0, 35.0, 60.0, 85.0, 100.0, 120.0, 140.0], dtype=float)
)
VALIDATION_YAW_RAD = np.radians(
    np.array([1.0, 2.0, 4.0, 8.0, 12.0, 20.0, 35.0, 60.0, 85.0, 100.0, 120.0, 140.0], dtype=float)
)
COARSE_PRESEARCH_HEIGHT_FRACTIONS = np.array([0.0, 0.45, 0.90], dtype=float)
COARSE_PRESEARCH_YAW_RAD = np.radians(np.array([2.0, 6.0, 15.0, 35.0, 75.0, 110.0], dtype=float))
CONTACT_STIFFNESS_N_PER_M = 70000.0
CONTACT_DAMPING_N_S_PER_M = 280.0
LATCH_PENETRATION_M = 0.0018
LATCH_REL_SPEED_MPS = 0.045
LATCH_TANGENTIAL_SPEED_MPS = 0.08
DYNAMIC_CONTACT_MARGIN_M = 1.0e-5
DYNAMIC_SEARCH_SUBSTEPS = 1
DYNAMIC_VALIDATION_SUBSTEPS = 2
DYNAMIC_SEARCH_ENV_REPLICAS = 1
DYNAMIC_VALIDATION_ENV_REPLICAS = 3
DISK_REMANENCE_UPPER_T = 1.48
DISK_STACK_HEIGHT_LIMIT_M = 0.078
MAX_LINEAR_SPEED_MPS = base.MAX_LINEAR_SPEED_MPS
MAX_YAW_RATE_RADPS = base.MAX_YAW_RATE_RADPS
MAX_RELATIVE_TRANSLATION_M = base.MAX_RELATIVE_TRANSLATION_M
MAX_RELATIVE_YAW_RAD = base.MAX_RELATIVE_YAW_RAD
ROBOT_PLATFORM_NAME = "AgileX LIMO"
ROBOT_LENGTH_M = 0.322
ROBOT_WIDTH_M = 0.220
ROBOT_MASS_KG = 4.2
ROBOT_COMMAND_SPEED_MPS = 0.45
CART_NOMINAL_MASS_KG = 18.0
CART_LENGTH_M = base.CART_LENGTH_M
CART_WIDTH_M = base.CART_WIDTH_M
ROBOT_MOUNT_WIDTH_ALLOWANCE_M = 0.020
ROBOT_MOUNT_LENGTH_ALLOWANCE_M = 0.030
CART_MOUNT_MARGIN_M = 0.020
CART_CASTER_TRAIL_M = 0.028
CART_LATERAL_DAMPING_RATIO = 2.8
CART_ALIGN_GAIN_SCALE = 2.2
CART_ALIGN_DAMPING_SCALE = 1.0
CART_TOW_ALIGN_GAIN_SCALE = 4.4
CART_TOW_ALIGN_DAMPING_SCALE = 0.45
# Use a more conservative indoor-caster baseline than the earlier optimistic values.
# This intentionally biases toward rejecting unrealistically agile cart responses.
CART_SUSTAINED_RESISTANCE_COEFF = 0.060
CART_LATERAL_RESISTANCE_RATIO = 2.6
CART_START_FORCE_MULTIPLIER = 2.80
CART_STATIC_RESISTANCE_SPEED_MPS = 0.025
CART_SWIVEL_STATIC_FACTOR = 0.090
CART_SWIVEL_STATIC_RATE_RADPS = 0.12
ROBOT_CRUISE_ACCEL_GAIN = 7.5
ROBOT_CRUISE_FORCE_LIMIT_N = 18.0
ROBOT_LATERAL_HOLD_GAIN_N_S_M = 6.0
MAX_CART_LINEAR_SPEED_MPS = 0.85
MAX_CART_YAW_RATE_RADPS = math.radians(120.0)
MAX_ROBOT_DYNAMIC_SPEED_MPS = 0.65
MAX_ROBOT_DYNAMIC_YAW_RATE_RADPS = math.radians(140.0)
MAGNET_DIRECTIONAL_SECTOR_FRACTION = 0.18
MAGNET_FORCE_CAP_MARGIN = 1.25
SENSOR_EFFECTIVE_RADIUS_M = 0.060
SENSOR_MIN_DETECT_FORCE_N = 0.5
SENSOR_TARGET_FORCE_N = 3.0
SENSOR_MIN_OBSERVABLE_HEIGHT_SHIFT_M = 0.0012
HUMAN_CUE_FORCE_RANGE_N = (3.0, 18.0)
HUMAN_CUE_TORQUE_RANGE_NM = (0.4, 4.0)


@dataclass(frozen=True)
class ShapeParameters:
    """Parameterized ring-shape family searched by the optimizer."""

    aspect_ratio: float
    superellipse_exponent: float
    polygon_weight: float
    polygon_sides: int
    shape_phase_fraction: float = 0.0
    harmonic3: float = 0.0
    harmonic4: float = 0.0
    harmonic5: float = 0.0
    harmonic6: float = 0.0
    harmonic7: float = 0.0
    harmonic8: float = 0.0
    harmonic9: float = 0.0
    harmonic10: float = 0.0
    harmonic11: float = 0.0
    harmonic12: float = 0.0
    local_feature1_amplitude: float = 0.0
    local_feature1_phase_fraction: float = 0.0
    local_feature1_width_fraction: float = 0.16
    local_feature2_amplitude: float = 0.0
    local_feature2_phase_fraction: float = 0.5
    local_feature2_width_fraction: float = 0.16
    family: str = "flex"
    arrow_head_length_ratio: float = 0.54
    arrow_head_half_width_ratio: float = 0.98
    arrow_shaft_half_width_ratio: float = 0.36
    arrow_neck_fraction: float = 0.48
    arrow_corner_rounding: float = 0.65


@dataclass(frozen=True)
class HifiDesign:
    """Discrete purchasable magnet design used by the high-fidelity simulator."""

    shape_parameters: ShapeParameters
    gap_m: float
    mean_radius_m: float
    magnet_sku_id: str
    magnet_vendor: str
    magnet_tangential_length_m: float
    magnet_axial_height_m: float
    magnet_radial_depth_m: float
    magnets_per_ring: int
    magnet_layers: int
    coverage_ratio: float
    pitch_m: float
    tangential_gap_m: float
    outer_phase_fraction: float
    nominal_overlap_m: float
    max_overlap_reduction_m: float
    cart_mass_kg: float
    total_magnets: int
    estimated_total_cost_jpy: float
    catalog_surface_flux_t: float
    catalog_pull_force_n: float
    effective_flux_t: float


@dataclass(frozen=True)
class HeightPolicy:
    """Overlap-height controller learned after shape optimization."""

    bias: float
    weight_torque: float
    weight_force: float
    weight_yaw: float
    weight_yaw_rate: float
    weight_gap_margin: float
    weight_translation: float
    weight_speed: float

    def target_height_shift(self, design: HifiDesign, features):
        """Maps the current state to a commanded overlap reduction."""

        value = (
            self.bias
            + self.weight_torque * features["torque_intent"]
            + self.weight_force * features["force_intent"]
            + self.weight_yaw * features["yaw_ratio"]
            + self.weight_yaw_rate * features["yaw_rate_ratio"]
            - self.weight_gap_margin * features["gap_margin_ratio"]
            + self.weight_translation * features["translation_ratio"]
            + self.weight_speed * features["speed_ratio"]
        )
        # In nominal transport, full overlap should be preserved for maximum centering stiffness.
        # Height reduction is therefore gated by explicit human intent, with a small safety-only
        # override reserved for near-contact situations.
        intent_gate = float(base.sigmoid(12.0 * (max(features["torque_intent"], features["force_intent"]) - 0.08)))
        safety_gate = float(base.sigmoid(18.0 * ((0.22 - features["gap_margin_ratio"]) + 0.15)))
        activation = max(intent_gate, safety_gate)
        return design.max_overlap_reduction_m * activation * float(base.sigmoid(value))


@dataclass
class ArrayModel:
    """Precomputed dipole clouds and geometry for a discrete ring design."""

    design: HifiDesign
    geometry: base.Geometry
    inner_centers_xyz: np.ndarray
    inner_moments_xyz: np.ndarray
    outer_centers_local_xyz: np.ndarray
    outer_moments_local_xyz: np.ndarray
    inner_magnet_centers_xy: np.ndarray
    inner_normals_xy: np.ndarray
    inner_tangents_xy: np.ndarray
    outer_magnet_centers_local_xy: np.ndarray
    outer_outward_normals_local_xy: np.ndarray
    outer_tangents_local_xy: np.ndarray
    inner_magnet_centers_xyz: np.ndarray
    inner_moment_dirs_xyz: np.ndarray
    outer_magnet_centers_local_xyz: np.ndarray
    outer_moment_dirs_local_xyz: np.ndarray
    dipole_grid: tuple[int, int, int]
    dipoles_per_magnet: int
    dipole_softening_length_m: float
    translational_force_cap_n: float
    yaw_torque_cap_nm: float
    yaw_contact_limit_rad: float
    translation_contact_limit_m: float


@dataclass
class PoseSample:
    """Magnetic force/torque result for one relative pose."""

    force_body_n: np.ndarray
    torque_outer_nm: float
    torque_inner_nm: float
    potential_energy_j: float
    min_gap_m: float
    raw_signed_gap_m: float
    contact_penetration_m: float
    contact_normal_body: np.ndarray
    inner_contact_point_body: np.ndarray
    outer_contact_point_body: np.ndarray


@dataclass
class StaticAssessment:
    """Static restoring-performance metrics used for shape optimization."""

    score: float
    contact_count: int
    negative_restore_count: int
    negative_yaw_restore_count: int
    mean_full_height_stiffness_npm: float
    min_reduced_height_stiffness_npm: float
    mean_orthogonal_ratio: float
    direction_stiffness_cv: float
    displacement_linearity_r2: float
    height_linearity_r2: float
    mean_translation_torque_ratio: float
    mean_forward_torque_ratio: float
    mean_yaw_stiffness_nmp_rad: float
    mean_towed_yaw_stiffness_nmp_rad: float
    min_parallel_force_n: float
    min_yaw_restoring_nm: float
    min_towed_yaw_restoring_nm: float
    negative_towed_yaw_restore_count: int
    nominal_tow_offset_proxy_m: float
    reduced_tow_offset_proxy_m: float
    stiffness_modulation_ratio: float
    inner_width_m: float
    inner_length_m: float
    outer_width_m: float
    outer_length_m: float
    package_violation_m: float


@dataclass
class DynamicOutcome:
    """Dynamic simulation result for one loading scenario."""

    score: float
    contact_events: int
    constraint_activations: int
    latched: bool
    min_gap_m: float
    max_contact_demand_m: float
    translation_rms_m: float
    yaw_rms_rad: float
    turn_signal_ratio: float
    turn_latency_s: float
    recenter_s: float
    height_shift_mean_m: float
    height_shift_peak_m: float
    contact_duration_s: float
    first_contact_time_s: float | None
    input_force_peak_n: float
    input_torque_peak_nm: float
    magnetic_force_peak_n: float
    contact_force_peak_n: float
    cue_peak_yaw_deg: float
    cue_peak_translation_mm: float
    sensor_peak_n: float
    height_return_s: float
    cruise_translation_rms_m: float
    cruise_yaw_rms_rad: float
    scenario_name: str
    environment_label: str
    record: dict | None = None


@dataclass(frozen=True)
class EpisodeEnvironment:
    """Episode-wise disturbance and uncertainty settings for robust validation."""

    magnetic_scale: float
    cart_damping_scale: float
    robot_damping_scale: float
    follow_force_scale: float
    follow_torque_scale: float
    height_tau_scale: float
    height_rate_scale: float
    contact_stiffness_scale: float
    contact_damping_scale: float
    cart_mass_scale: float
    rolling_resistance_scale: float
    swivel_resistance_scale: float
    assembly_translation_bias_body_m: np.ndarray
    assembly_yaw_bias_rad: float
    label: str


def signed(low, high, value):
    """Converts a bounded [0, 1] value into a signed design parameter."""

    return low + (high - low) * value


def live_monitor_enabled():
    """Returns True when live dashboard state publishing is enabled."""

    return LIVE_MONITOR_DIR is not None


def set_live_monitor_dir(outdir: Path | None):
    """Configures the output directory used by the live dashboard state publisher."""

    global LIVE_MONITOR_DIR
    LIVE_MONITOR_DIR = Path(outdir) if outdir is not None else None


def to_live_json(value):
    """Recursively converts runtime objects into JSON-serializable primitives."""

    if isinstance(value, dict):
        return {str(key): to_live_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_live_json(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def update_live_monitor_state(**payload):
    """Merges payload into the live dashboard state file for polling clients."""

    if LIVE_MONITOR_DIR is None:
        return
    path = LIVE_MONITOR_DIR / "live_monitor_state.json"
    with LIVE_MONITOR_LOCK:
        state = {}
        if path.exists():
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                state = {}
        state.update(to_live_json(payload))
        state["updated_at_epoch_s"] = time.time()
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def publish_live_history_csv(filename: str, rows):
    """Writes a live-updating CSV history file for dashboard polling."""

    if LIVE_MONITOR_DIR is None:
        return
    pd.DataFrame(rows).to_csv(LIVE_MONITOR_DIR / filename, index=False)


def append_live_history_rows(filename: str, rows):
    """Appends row dictionaries to a live CSV file without rewriting the full history."""

    if LIVE_MONITOR_DIR is None or not rows:
        return
    path = LIVE_MONITOR_DIR / filename
    normalized_rows = [to_live_json(row) for row in rows]
    fieldnames = list(normalized_rows[0].keys())
    with LIVE_MONITOR_LOCK:
        file_exists = path.exists() and path.stat().st_size > 0
        with path.open("a", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            for row in normalized_rows:
                writer.writerow(row)


def reset_live_monitor_outputs():
    """Clears live monitor artifacts when reusing an output directory."""

    if LIVE_MONITOR_DIR is None:
        return
    for filename in (
        "live_monitor_state.json",
        "live_design_history.csv",
        "live_policy_history.csv",
        "live_design_candidate_history.csv",
        "live_policy_candidate_history.csv",
        "live_shape_and_magnets.png",
        "live_field_distribution.png",
    ):
        path = LIVE_MONITOR_DIR / filename
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass


def design_candidate_trace_row(candidate, optimizer, generation, candidate_index, evaluation_index, generation_rank, restart_index=-1):
    """Serializes one static-search candidate for scatter and raw-trace visualization."""

    design = candidate["design"]
    assessment = candidate["static_assessment"]
    return {
        "optimizer": optimizer,
        "restart_index": int(restart_index),
        "generation": int(generation),
        "candidate_index": int(candidate_index),
        "evaluation_index": int(evaluation_index),
        "generation_rank": int(generation_rank),
        "score": float(candidate["score"]),
        "primary_merit": float(candidate.get("primary_merit", candidate["score"])),
        "constraint_violation": float(candidate.get("constraint_violation", 0.0)),
        "is_feasible": int(candidate.get("is_feasible", True)),
        "shape_family": design.shape_parameters.family,
        "gap_m": float(design.gap_m),
        "mean_radius_m": float(design.mean_radius_m),
        "magnet_sku_id": design.magnet_sku_id,
        "magnets_per_ring": int(design.magnets_per_ring),
        "magnet_layers": int(design.magnet_layers),
        "estimated_total_cost_jpy": float(design.estimated_total_cost_jpy),
        "mean_orthogonal_ratio": float(assessment.mean_orthogonal_ratio),
        "mean_forward_torque_ratio": float(assessment.mean_forward_torque_ratio),
        "package_violation_mm": 1000.0 * float(assessment.package_violation_m),
        "nominal_tow_offset_proxy_mm": 1000.0 * float(assessment.nominal_tow_offset_proxy_m),
        "reduced_tow_offset_proxy_mm": 1000.0 * float(assessment.reduced_tow_offset_proxy_m),
        "stiffness_modulation_ratio": float(assessment.stiffness_modulation_ratio),
    }


def policy_candidate_trace_row(candidate, generation, candidate_index, evaluation_index, generation_rank):
    """Serializes one policy-search candidate for scatter and raw-trace visualization."""

    outcomes = candidate.get("outcomes", [])
    scores = np.array([outcome.score for outcome in outcomes], dtype=float) if outcomes else np.array([], dtype=float)
    return {
        "optimizer": "cem",
        "generation": int(generation),
        "candidate_index": int(candidate_index),
        "evaluation_index": int(evaluation_index),
        "generation_rank": int(generation_rank),
        "score": float(candidate["score"]),
        "mean_outcome_score": float(np.mean(scores)) if scores.size else math.nan,
        "score_std": float(np.std(scores)) if scores.size else math.nan,
        "latched_total": int(sum(outcome.latched for outcome in outcomes)),
        "contact_events_total": int(sum(outcome.contact_events for outcome in outcomes)),
        "constraint_activations_total": int(sum(outcome.constraint_activations for outcome in outcomes)),
        "worst_clearance_mm": 1000.0 * float(min((outcome.min_gap_m for outcome in outcomes), default=math.nan)),
        "worst_contact_demand_mm": 1000.0 * float(max((outcome.max_contact_demand_m for outcome in outcomes), default=math.nan)),
        "mean_turn_signal_ratio": float(np.mean([outcome.turn_signal_ratio for outcome in outcomes])) if outcomes else math.nan,
        "mean_turn_latency_s": float(np.mean([outcome.turn_latency_s for outcome in outcomes])) if outcomes else math.nan,
        "mean_recenter_s": float(np.mean([outcome.recenter_s for outcome in outcomes])) if outcomes else math.nan,
    }


def live_visual_summary_lines(candidate, optimizer_label: str, generation_label: str):
    """Formats compact text shown inside the live geometry snapshots."""

    design = candidate["design"]
    assessment = candidate["static_assessment"]
    return [
        f"optimizer={optimizer_label}",
        f"generation={generation_label}",
        f"shape={shape_name(design.shape_parameters)}",
        f"sku={design.magnet_sku_id}",
        f"score={candidate['score']:.2f}",
        f"primary_merit={candidate.get('primary_merit', candidate['score']):.2f}",
        f"constraint_violation={candidate.get('constraint_violation', 0.0):.4f}",
        f"feasible={int(candidate.get('is_feasible', True))}",
        f"gap={1000.0 * design.gap_m:.2f} mm",
        f"mean_radius={1000.0 * design.mean_radius_m:.2f} mm",
        f"magnets_per_ring={design.magnets_per_ring}",
        f"layers={design.magnet_layers}",
        f"orthogonal_leakage={assessment.mean_orthogonal_ratio:.4f}",
        f"forward_torque_ratio={assessment.mean_forward_torque_ratio:.4f}",
    ]


def plot_live_shape_and_magnets(model: ArrayModel, candidate, outdir: Path, optimizer_label: str, generation_label: str):
    """Draws the current best geometry plus discrete magnet placement for live monitoring."""

    summary_lines = live_visual_summary_lines(candidate, optimizer_label, generation_label)
    figure, axes = plt.subplots(1, 2, figsize=(11.5, 5.2), dpi=150, gridspec_kw={"width_ratios": [1.45, 1.0]})
    geom_axis, text_axis = axes

    geom_axis.fill(
        model.geometry.outer_points_local[:, 0],
        model.geometry.outer_points_local[:, 1],
        color="#dbeafe",
        alpha=0.85,
        zorder=0,
    )
    geom_axis.fill(
        model.geometry.inner_points[:, 0],
        model.geometry.inner_points[:, 1],
        color="white",
        alpha=1.0,
        zorder=1,
    )
    geom_axis.plot(model.geometry.outer_points_local[:, 0], model.geometry.outer_points_local[:, 1], color="#2563eb", linewidth=2.2)
    geom_axis.plot(model.geometry.inner_points[:, 0], model.geometry.inner_points[:, 1], color="#111827", linewidth=2.0)
    geom_axis.scatter(
        model.inner_magnet_centers_xy[:, 0],
        model.inner_magnet_centers_xy[:, 1],
        s=22,
        color="#ef4444",
        edgecolors="white",
        linewidths=0.4,
        label="inner magnets",
        zorder=3,
    )
    geom_axis.scatter(
        model.outer_magnet_centers_local_xy[:, 0],
        model.outer_magnet_centers_local_xy[:, 1],
        s=22,
        color="#0f766e",
        edgecolors="white",
        linewidths=0.4,
        label="outer magnets",
        zorder=3,
    )
    stride = max(1, len(model.inner_magnet_centers_xy) // 18)
    geom_axis.quiver(
        model.inner_magnet_centers_xy[::stride, 0],
        model.inner_magnet_centers_xy[::stride, 1],
        model.inner_normals_xy[::stride, 0],
        model.inner_normals_xy[::stride, 1],
        angles="xy",
        scale_units="xy",
        scale=25.0,
        width=0.003,
        color="#b91c1c",
        alpha=0.85,
        zorder=4,
    )
    geom_axis.quiver(
        model.outer_magnet_centers_local_xy[::stride, 0],
        model.outer_magnet_centers_local_xy[::stride, 1],
        -model.outer_outward_normals_local_xy[::stride, 0],
        -model.outer_outward_normals_local_xy[::stride, 1],
        angles="xy",
        scale_units="xy",
        scale=25.0,
        width=0.003,
        color="#0f766e",
        alpha=0.85,
        zorder=4,
    )
    geom_axis.set_aspect("equal", adjustable="box")
    geom_axis.set_title("Current Best Shape and Magnet Positions")
    geom_axis.set_xlabel("x [m]")
    geom_axis.set_ylabel("y [m]")
    geom_axis.grid(True, alpha=0.18)
    geom_axis.legend(loc="upper right", fontsize=8)

    text_axis.axis("off")
    text_axis.set_title("Live Candidate Summary", loc="left")
    text_axis.text(
        0.0,
        1.0,
        "\n".join(summary_lines),
        va="top",
        ha="left",
        fontsize=10.5,
        family="monospace",
        transform=text_axis.transAxes,
    )

    figure.tight_layout()
    figure.savefig(outdir / "live_shape_and_magnets.png", dpi=160)
    plt.close(figure)


def plot_live_field_distribution(model: ArrayModel, candidate, outdir: Path, optimizer_label: str, generation_label: str):
    """Draws a coarse but fast magnetic-field snapshot for live monitoring."""

    span_xy = model.design.mean_radius_m + model.design.gap_m + model.design.magnet_radial_depth_m + 0.05
    x_values = np.linspace(-span_xy, span_xy, 41)
    y_values = np.linspace(-span_xy, span_xy, 41)
    xx, yy = np.meshgrid(x_values, y_values)
    top_points = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(xx.size)))
    top_field = dipole_field(top_points, model.inner_centers_xyz, model.inner_moments_xyz) + dipole_field(
        top_points,
        model.outer_centers_local_xyz,
        model.outer_moments_local_xyz,
    )
    top_field = top_field.reshape(xx.shape + (3,))
    top_mag_mt = 1000.0 * np.linalg.norm(top_field, axis=2)

    z_values = np.linspace(-0.045, 0.045, 31)
    xx2, zz2 = np.meshgrid(x_values, z_values)
    side_points = np.column_stack((xx2.ravel(), np.zeros(xx2.size), zz2.ravel()))
    side_field = dipole_field(side_points, model.inner_centers_xyz, model.inner_moments_xyz) + dipole_field(
        side_points,
        model.outer_centers_local_xyz,
        model.outer_moments_local_xyz,
    )
    side_field = side_field.reshape(xx2.shape + (3,))
    side_mag_mt = 1000.0 * np.linalg.norm(side_field, axis=2)

    figure, axes = plt.subplots(1, 2, figsize=(12.2, 5.0), dpi=150)
    top_axis, side_axis = axes
    im0 = top_axis.imshow(
        top_mag_mt,
        extent=[x_values.min(), x_values.max(), y_values.min(), y_values.max()],
        origin="lower",
        cmap="magma",
        aspect="equal",
    )
    top_axis.plot(model.geometry.inner_points[:, 0], model.geometry.inner_points[:, 1], color="white", linewidth=1.2)
    top_axis.plot(model.geometry.outer_points_local[:, 0], model.geometry.outer_points_local[:, 1], color="#93c5fd", linewidth=1.1)
    top_axis.scatter(model.inner_magnet_centers_xy[:, 0], model.inner_magnet_centers_xy[:, 1], s=10, color="#ef4444", alpha=0.8)
    top_axis.scatter(model.outer_magnet_centers_local_xy[:, 0], model.outer_magnet_centers_local_xy[:, 1], s=10, color="#34d399", alpha=0.8)
    top_axis.set_title(f"Live Field Top View\n{optimizer_label} {generation_label}")
    top_axis.set_xlabel("x [m]")
    top_axis.set_ylabel("y [m]")
    figure.colorbar(im0, ax=top_axis, shrink=0.82, label="|B| [mT]")

    im1 = side_axis.imshow(
        side_mag_mt,
        extent=[x_values.min(), x_values.max(), z_values.min(), z_values.max()],
        origin="lower",
        cmap="viridis",
        aspect="auto",
    )
    side_axis.set_title("Live Field x-z Slice")
    side_axis.set_xlabel("x [m]")
    side_axis.set_ylabel("z [m]")
    figure.colorbar(im1, ax=side_axis, shrink=0.82, label="|B| [mT]")

    figure.tight_layout()
    figure.savefig(outdir / "live_field_distribution.png", dpi=160)
    plt.close(figure)


def publish_live_candidate_visuals(candidate, optimizer_label: str, generation_label: str):
    """Refreshes dashboard images showing the current best candidate shape and field."""

    if LIVE_MONITOR_DIR is None:
        return
    model = candidate["model"]
    plot_live_shape_and_magnets(model, candidate, LIVE_MONITOR_DIR, optimizer_label, generation_label)
    plot_live_field_distribution(model, candidate, LIVE_MONITOR_DIR, optimizer_label, generation_label)
    update_live_monitor_state(
        live_visuals={
            "shape_image": "live_shape_and_magnets.png",
            "field_image": "live_field_distribution.png",
            "optimizer": optimizer_label,
            "generation": generation_label,
            "score": float(candidate["score"]),
        }
    )


def launch_live_dashboard_process(outputs_root: Path, run_dir: Path, host: str, port: int):
    """Spawns the standalone browser dashboard in the background."""

    command = [
        sys.executable,
        "-m",
        "mpc_solarcar.magnetic_coupler_dashboard",
        "--outputs-root",
        str(outputs_root),
        "--host",
        str(host),
        "--port",
        str(port),
        "--run",
        run_dir.name,
        "--open-browser",
    ]
    popen_kwargs = {
        "cwd": str(ROOT),
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform.startswith("win"):
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(command, **popen_kwargs)


def fit_line(x_values, y_values):
    """Returns slope, intercept, and R^2 for a simple least-squares line."""

    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    if x.size <= 1:
        return 0.0, float(y[0]) if y.size else 0.0, 1.0
    x_mean = float(np.mean(x))
    y_mean = float(np.mean(y))
    denom = float(np.sum((x - x_mean) ** 2))
    if denom <= 1.0e-12:
        return 0.0, y_mean, 1.0
    slope = float(np.sum((x - x_mean) * (y - y_mean)) / denom)
    intercept = y_mean - slope * x_mean
    prediction = slope * x + intercept
    ss_res = float(np.sum((y - prediction) ** 2))
    ss_tot = float(np.sum((y - y_mean) ** 2))
    r2 = 1.0 if ss_tot <= 1.0e-12 else max(0.0, 1.0 - ss_res / ss_tot)
    return slope, intercept, r2


def aspect_axes(aspect_ratio):
    """Builds a/b axes whose product stays near 1 while the aspect changes."""

    a_axis = math.sqrt(aspect_ratio)
    b_axis = 1.0 / max(a_axis, 1.0e-9)
    return a_axis, b_axis


def flex_harmonic_vector(params: ShapeParameters):
    """Returns the active smooth-shape harmonic coefficients as a vector."""

    return np.array(
        [
            params.harmonic3,
            params.harmonic4,
            params.harmonic5,
            params.harmonic6,
            params.harmonic7,
            params.harmonic8,
            params.harmonic9,
            params.harmonic10,
            params.harmonic11,
            params.harmonic12,
        ],
        dtype=float,
    )


def local_feature_vector(params: ShapeParameters):
    """Returns the localized flex-shape feature parameters as a vector."""

    return np.array(
        [
            params.local_feature1_amplitude,
            params.local_feature1_phase_fraction,
            params.local_feature1_width_fraction,
            params.local_feature2_amplitude,
            params.local_feature2_phase_fraction,
            params.local_feature2_width_fraction,
        ],
        dtype=float,
    )


def periodic_gaussian(theta, center_rad, width_rad):
    """Returns a wrapped Gaussian bump on the circle."""

    wrapped = np.angle(np.exp(1j * (theta - center_rad)))
    width_rad = max(float(width_rad), math.radians(6.0))
    return np.exp(-0.5 * (wrapped / width_rad) ** 2)


def polygon_centroid(points_xy):
    """Returns the area centroid of a closed simple polygon."""

    points = np.asarray(points_xy, dtype=float)
    shifted = np.roll(points, -1, axis=0)
    cross = points[:, 0] * shifted[:, 1] - shifted[:, 0] * points[:, 1]
    area2 = float(np.sum(cross))
    if abs(area2) <= 1.0e-12:
        return np.mean(points, axis=0)
    factor = 1.0 / (3.0 * area2)
    cx = factor * float(np.sum((points[:, 0] + shifted[:, 0]) * cross))
    cy = factor * float(np.sum((points[:, 1] + shifted[:, 1]) * cross))
    return np.array([cx, cy], dtype=float)


def chaikin_closed(points_xy, iterations):
    """Rounds a closed polygon without changing its topology."""

    points = np.asarray(points_xy, dtype=float)
    for _ in range(max(0, int(iterations))):
        next_points = np.roll(points, -1, axis=0)
        q_points = 0.75 * points + 0.25 * next_points
        r_points = 0.25 * points + 0.75 * next_points
        refined = np.empty((2 * len(points), 2), dtype=float)
        refined[0::2] = q_points
        refined[1::2] = r_points
        points = refined
    return points


def resample_closed_polyline(points_xy, count):
    """Resamples a closed polyline to equal arc-length spacing."""

    points = np.asarray(points_xy, dtype=float)
    edge_vectors = np.roll(points, -1, axis=0) - points
    edge_lengths = np.linalg.norm(edge_vectors, axis=1)
    perimeter_m = float(np.sum(edge_lengths))
    if perimeter_m <= 1.0e-12:
        return np.repeat(points[:1], count, axis=0)
    cumulative = np.concatenate(([0.0], np.cumsum(edge_lengths)))
    targets = np.linspace(0.0, perimeter_m, count, endpoint=False)
    samples = []
    for target in targets:
        edge_index = int(np.searchsorted(cumulative, target, side="right") - 1)
        edge_index = min(edge_index, len(edge_lengths) - 1)
        local = (target - cumulative[edge_index]) / max(edge_lengths[edge_index], 1.0e-12)
        next_index = (edge_index + 1) % len(points)
        samples.append((1.0 - local) * points[edge_index] + local * points[next_index])
    return np.asarray(samples, dtype=float)


def flexible_radius_profile(theta, params: ShapeParameters):
    """Creates a broad but smooth radius profile for searching better shapes."""

    theta_shifted = theta + 2.0 * math.pi * params.shape_phase_fraction
    a_axis, b_axis = aspect_axes(params.aspect_ratio)
    base_profile = base.superellipse_radius(
        theta_shifted, a_axis=a_axis, b_axis=b_axis, exponent=params.superellipse_exponent
    )
    polygon_profile = base.polygon_radius(
        theta_shifted, sides=params.polygon_sides, rotation_rad=math.pi / params.polygon_sides
    )
    radius = (1.0 - params.polygon_weight) * base_profile + params.polygon_weight * polygon_profile
    radius *= (
        1.0
        + params.harmonic3 * np.cos(3.0 * theta_shifted)
        + params.harmonic4 * np.cos(4.0 * theta_shifted)
        + params.harmonic5 * np.cos(5.0 * theta_shifted)
        + params.harmonic6 * np.cos(6.0 * theta_shifted)
        + params.harmonic7 * np.cos(7.0 * theta_shifted)
        + params.harmonic8 * np.cos(8.0 * theta_shifted)
        + params.harmonic9 * np.cos(9.0 * theta_shifted)
        + params.harmonic10 * np.cos(10.0 * theta_shifted)
        + params.harmonic11 * np.cos(11.0 * theta_shifted)
        + params.harmonic12 * np.cos(12.0 * theta_shifted)
    )
    local_feature1 = params.local_feature1_amplitude * periodic_gaussian(
        theta_shifted,
        2.0 * math.pi * params.local_feature1_phase_fraction,
        2.0 * math.pi * params.local_feature1_width_fraction,
    )
    local_feature2 = params.local_feature2_amplitude * periodic_gaussian(
        theta_shifted,
        2.0 * math.pi * params.local_feature2_phase_fraction,
        2.0 * math.pi * params.local_feature2_width_fraction,
    )
    radius *= 1.0 + local_feature1 + local_feature2
    radius = np.clip(radius, 0.35, None)
    return radius / max(float(np.mean(radius)), 1.0e-12)


def shape_name(params: ShapeParameters):
    """Formats a compact human-readable label for the selected flexible shape."""

    if params.family == "arrow":
        return (
            f"arrow_hl{params.arrow_head_length_ratio:.3f}_"
            f"hw{params.arrow_head_half_width_ratio:.3f}_"
            f"sw{params.arrow_shaft_half_width_ratio:.3f}_"
            f"nk{params.arrow_neck_fraction:.3f}_"
            f"rd{params.arrow_corner_rounding:.3f}"
        )
    signature_payload = np.concatenate((np.round(flex_harmonic_vector(params), 4), np.round(local_feature_vector(params), 4)))
    harmonic_signature = hashlib.md5(signature_payload.tobytes()).hexdigest()[:8]
    return (
        f"flex_ar{params.aspect_ratio:.3f}_n{params.superellipse_exponent:.2f}_"
        f"poly{params.polygon_sides}w{params.polygon_weight:.3f}_"
        f"ph{params.shape_phase_fraction:.3f}_sig{harmonic_signature}"
    )


def build_flexible_geometry(shape_params: ShapeParameters, mean_radius_m, gap_m, num_samples):
    """Builds inner/outer boundaries for the flexible searched shape family."""

    theta = np.linspace(0.0, 2.0 * math.pi, num_samples, endpoint=False)
    radius_profile = flexible_radius_profile(theta, shape_params)
    (
        inner_points,
        inner_normals,
        inner_tangents,
        inner_ds,
        inner_support,
        inner_arc_fraction,
        inner_perimeter_m,
        max_radius_inner,
    ) = base.boundary_from_radius_profile(radius_profile, mean_radius_m)
    (
        outer_points,
        outer_normals,
        outer_tangents,
        _,
        _,
        outer_arc_fraction,
        outer_perimeter_m,
        max_radius_outer,
    ) = boundary_from_points(inner_points + gap_m * inner_normals)
    outer_inward_normals = -outer_normals
    beta = base.SOFTMAX_SHARPNESS / max(mean_radius_m + gap_m, 1.0e-3)
    geometry = base.Geometry(
        shape_name=shape_name(shape_params),
        inner_points=inner_points,
        inner_normals=inner_normals,
        inner_tangents=inner_tangents,
        inner_ds=inner_ds,
        inner_support=inner_support,
        inner_arc_fraction=inner_arc_fraction,
        inner_perimeter_m=inner_perimeter_m,
        outer_points_local=outer_points,
        outer_outward_normals_local=outer_normals,
        outer_inward_normals_local=outer_inward_normals,
        outer_tangents_local=outer_tangents,
        outer_arc_fraction=outer_arc_fraction,
        outer_perimeter_m=outer_perimeter_m,
        max_radius_m=max(max_radius_inner, max_radius_outer),
        yaw_contact_limit_rad=0.0,
        translation_contact_limit_m=0.0,
        base_gap_m=gap_m,
        beta=beta,
    )
    geometry.translation_contact_limit_m = base.estimate_translation_limit_m(geometry)
    geometry.yaw_contact_limit_rad = base.estimate_yaw_limit_rad(geometry)
    return geometry


def build_arrow_geometry(shape_params: ShapeParameters, mean_radius_m, gap_m, num_samples):
    """Builds a concave inverse-arrow ring profile motivated by restoring-torque flanks."""

    head_length_ratio = base.clamp(shape_params.arrow_head_length_ratio, 0.34, 0.82)
    head_half_width = base.clamp(shape_params.arrow_head_half_width_ratio, 0.72, 1.32)
    shaft_half_width = base.clamp(shape_params.arrow_shaft_half_width_ratio, 0.18, head_half_width - 0.08)
    neck_fraction = base.clamp(shape_params.arrow_neck_fraction, 0.10, 0.88)
    rounding = base.clamp(shape_params.arrow_corner_rounding, 0.0, 1.0)

    x_tip = -1.0
    x_tail = 1.0
    x_head_back = x_tip + 2.0 * head_length_ratio
    x_head_back = min(x_head_back, x_tail - 0.24)
    x_neck = x_head_back + neck_fraction * max(x_tail - x_head_back, 0.16)
    x_neck = min(x_neck, x_tail - 0.08)
    flank_knee_x = x_tip + 0.46 * (x_head_back - x_tip)
    flank_knee_y = shaft_half_width + 0.58 * (head_half_width - shaft_half_width)

    polygon = np.array(
        [
            [x_tip, 0.0],
            [flank_knee_x, flank_knee_y],
            [x_head_back, head_half_width],
            [x_neck, shaft_half_width],
            [x_tail, shaft_half_width],
            [x_tail, -shaft_half_width],
            [x_neck, -shaft_half_width],
            [x_head_back, -head_half_width],
            [flank_knee_x, -flank_knee_y],
        ],
        dtype=float,
    )
    polygon -= polygon_centroid(polygon)
    polygon /= max(float(np.mean(np.linalg.norm(polygon, axis=1))), 1.0e-12)
    polygon *= mean_radius_m

    smooth_iterations = 1 + int(round(2.0 * rounding))
    refined = chaikin_closed(polygon, smooth_iterations)
    inner_points_seed = resample_closed_polyline(refined, num_samples)
    (
        inner_points,
        inner_normals,
        inner_tangents,
        inner_ds,
        inner_support,
        inner_arc_fraction,
        inner_perimeter_m,
        max_radius_inner,
    ) = boundary_from_points(inner_points_seed)
    (
        outer_points,
        outer_normals,
        outer_tangents,
        _,
        _,
        outer_arc_fraction,
        outer_perimeter_m,
        max_radius_outer,
    ) = boundary_from_points(inner_points + gap_m * inner_normals)
    outer_inward_normals = -outer_normals
    beta = base.SOFTMAX_SHARPNESS / max(mean_radius_m + gap_m, 1.0e-3)
    geometry = base.Geometry(
        shape_name=shape_name(shape_params),
        inner_points=inner_points,
        inner_normals=inner_normals,
        inner_tangents=inner_tangents,
        inner_ds=inner_ds,
        inner_support=inner_support,
        inner_arc_fraction=inner_arc_fraction,
        inner_perimeter_m=inner_perimeter_m,
        outer_points_local=outer_points,
        outer_outward_normals_local=outer_normals,
        outer_inward_normals_local=outer_inward_normals,
        outer_tangents_local=outer_tangents,
        outer_arc_fraction=outer_arc_fraction,
        outer_perimeter_m=outer_perimeter_m,
        max_radius_m=max(max_radius_inner, max_radius_outer),
        yaw_contact_limit_rad=0.0,
        translation_contact_limit_m=0.0,
        base_gap_m=gap_m,
        beta=beta,
    )
    geometry.translation_contact_limit_m = base.estimate_translation_limit_m(geometry)
    geometry.yaw_contact_limit_rad = base.estimate_yaw_limit_rad(geometry)
    return geometry


def build_geometry_from_shape(shape_params: ShapeParameters, mean_radius_m, gap_m, num_samples):
    """Dispatches between smooth radial and explicit inverse-arrow geometry families."""

    if shape_params.family == "arrow":
        return build_arrow_geometry(shape_params, mean_radius_m, gap_m, num_samples)
    return build_flexible_geometry(shape_params, mean_radius_m, gap_m, num_samples)


def choose_catalog_sku(selector_value):
    """Selects one actual Japan-purchasable magnet SKU from the existing catalog."""

    return choose_catalog_sku_from_list(selector_value, base.MAGNET_CATALOG)


def resolve_catalog(fixed_sku_id=None):
    """Returns either the full product catalog or a single-SKU constrained catalog."""

    if not fixed_sku_id:
        return base.MAGNET_CATALOG
    if fixed_sku_id not in base.MAGNET_CATALOG_BY_ID:
        known = ", ".join(sorted(base.MAGNET_CATALOG_BY_ID))
        raise KeyError(f"Unknown SKU '{fixed_sku_id}'. Known SKUs: {known}")
    return [base.MAGNET_CATALOG_BY_ID[fixed_sku_id]]


def choose_catalog_sku_from_list(selector_value, catalog):
    """Selects one SKU from an arbitrary catalog subset."""

    index = int(base.clamp(round(selector_value * (len(catalog) - 1)), 0, len(catalog) - 1))
    return catalog[index]


def design_variable_manifest(shape_family_mode="flex"):
    """Describes the active latent design variables for audit and reporting."""

    if shape_family_mode == "arrow":
        return [
            {"index": 0, "name": "family_selector", "range": "[0,1]", "description": "Latent family selector; ignored in arrow-only mode."},
            {"index": 1, "name": "aspect_ratio", "range": "0.68..1.60", "description": "Base arrow envelope aspect ratio proxy."},
            {"index": 2, "name": "superellipse_exponent", "range": "2.0..10.5", "description": "Residual smoothness exponent carried for compatibility."},
            {"index": 3, "name": "polygon_weight", "range": "0.00..0.68", "description": "Residual polygon blend carried for compatibility."},
            {"index": 4, "name": "polygon_sides", "range": "3..12", "description": "Residual polygon-side count carried for compatibility."},
            {"index": 5, "name": "harmonic3", "range": "-0.24..0.24", "description": "Third harmonic residual."},
            {"index": 6, "name": "harmonic4", "range": "-0.20..0.20", "description": "Fourth harmonic residual."},
            {"index": 7, "name": "harmonic5", "range": "-0.20..0.20", "description": "Fifth harmonic residual."},
            {"index": 8, "name": "harmonic6", "range": "-0.12..0.12", "description": "Sixth harmonic residual."},
            {"index": 9, "name": "gap_m", "range": "SKU dependent", "description": "Nominal radial air-gap."},
            {"index": 10, "name": "mean_radius_m", "range": "0.060..0.145 or 0.210", "description": "Mean inner-ring radius."},
            {"index": 11, "name": "sku_selector", "range": "catalog index", "description": "Purchasable magnet SKU selector."},
            {"index": 12, "name": "magnet_layers", "range": "1..stack limit", "description": "Vertical stacking layers per pocket."},
            {"index": 13, "name": "target_fill_ratio", "range": "SKU dependent", "description": "Perimeter fill target before integer packing."},
            {"index": 14, "name": "outer_phase_fraction", "range": "-0.48..0.48", "description": "Outer-ring circumferential phase offset."},
            {"index": 15, "name": "overlap_ratio", "range": "0.18..0.78", "description": "Fraction of nominal overlap allowed to reduce."},
            {"index": 16, "name": "cart_mass_kg", "range": "8..35", "description": "Operating cart mass if not fixed."},
            {"index": 17, "name": "arrow_head_length_ratio", "range": "0.34..0.82", "description": "Arrow-head length fraction."},
            {"index": 18, "name": "arrow_head_half_width_ratio", "range": "0.74..1.32", "description": "Arrow-head half-width."},
            {"index": 19, "name": "arrow_shaft_half_width_ratio", "range": "0.18..0.48", "description": "Arrow shaft half-width."},
            {"index": 20, "name": "arrow_neck_fraction", "range": "0.10..0.88", "description": "Arrow neck position fraction."},
            {"index": 21, "name": "arrow_corner_rounding", "range": "0.00..1.00", "description": "Arrow corner rounding."},
        ]
    return [
        {"index": 0, "name": "aspect_ratio", "range": "0.60..1.70", "description": "Global smooth-ring aspect ratio."},
        {"index": 1, "name": "superellipse_exponent", "range": "1.8..11.8", "description": "Base superellipse sharpness."},
        {"index": 2, "name": "polygon_weight", "range": "0.00..0.80", "description": "Blend toward polygonal support function."},
        {"index": 3, "name": "polygon_sides", "range": "3..12", "description": "Polygonal side count in the blended base."},
        {"index": 4, "name": "shape_phase_fraction", "range": "0.00..1.00", "description": "Rotation of the whole smooth shape family."},
        {"index": 5, "name": "harmonic3", "range": "-0.26..0.26", "description": "3rd cosine harmonic amplitude."},
        {"index": 6, "name": "harmonic4", "range": "-0.22..0.22", "description": "4th cosine harmonic amplitude."},
        {"index": 7, "name": "harmonic5", "range": "-0.20..0.20", "description": "5th cosine harmonic amplitude."},
        {"index": 8, "name": "harmonic6", "range": "-0.18..0.18", "description": "6th cosine harmonic amplitude."},
        {"index": 9, "name": "harmonic7", "range": "-0.16..0.16", "description": "7th cosine harmonic amplitude."},
        {"index": 10, "name": "harmonic8", "range": "-0.14..0.14", "description": "8th cosine harmonic amplitude."},
        {"index": 11, "name": "harmonic9", "range": "-0.12..0.12", "description": "9th cosine harmonic amplitude."},
        {"index": 12, "name": "harmonic10", "range": "-0.10..0.10", "description": "10th cosine harmonic amplitude."},
        {"index": 13, "name": "harmonic11", "range": "-0.08..0.08", "description": "11th cosine harmonic amplitude."},
        {"index": 14, "name": "harmonic12", "range": "-0.07..0.07", "description": "12th cosine harmonic amplitude."},
        {"index": 15, "name": "local_feature1_amplitude", "range": "-0.22..0.22", "description": "Localized radius bump/notch amplitude 1."},
        {"index": 16, "name": "local_feature1_phase_fraction", "range": "0.00..1.00", "description": "Localized feature 1 circumferential phase."},
        {"index": 17, "name": "local_feature1_width_fraction", "range": "0.04..0.30", "description": "Localized feature 1 angular width."},
        {"index": 18, "name": "local_feature2_amplitude", "range": "-0.20..0.20", "description": "Localized radius bump/notch amplitude 2."},
        {"index": 19, "name": "local_feature2_phase_fraction", "range": "0.00..1.00", "description": "Localized feature 2 circumferential phase."},
        {"index": 20, "name": "local_feature2_width_fraction", "range": "0.04..0.30", "description": "Localized feature 2 angular width."},
        {"index": 21, "name": "gap_m", "range": "SKU dependent", "description": "Nominal radial air-gap."},
        {"index": 22, "name": "mean_radius_m", "range": "0.060..0.145 or 0.210", "description": "Mean inner-ring radius."},
        {"index": 23, "name": "sku_selector", "range": "catalog index", "description": "Purchasable magnet SKU selector."},
        {"index": 24, "name": "magnet_layers", "range": "1..stack limit", "description": "Vertical stacking layers per pocket."},
        {"index": 25, "name": "target_fill_ratio", "range": "0.55..0.92 or 0.56..0.90", "description": "Perimeter fill target before integer packing."},
        {"index": 26, "name": "outer_phase_fraction", "range": "-0.48..0.48", "description": "Outer-ring circumferential phase offset."},
        {"index": 27, "name": "overlap_ratio", "range": "0.18..0.78", "description": "Fraction of nominal overlap allowed to reduce."},
        {"index": 28, "name": "cart_mass_kg", "range": "8..35", "description": "Operating cart mass if not fixed."},
    ]


def design_variable_count(shape_family_mode="flex"):
    """Returns the active latent dimensionality for the chosen design family mode."""

    if shape_family_mode == "arrow":
        return 22
    if shape_family_mode == "both":
        return max(22, len(design_variable_manifest("flex")))
    return len(design_variable_manifest("flex"))


def write_design_variable_manifest(outdir: Path, shape_family_mode: str):
    """Writes machine-readable design-variable definitions used by the optimizer."""

    rows = design_variable_manifest(shape_family_mode)
    payload = {
        "shape_family_mode": shape_family_mode,
        "design_variable_count": len(rows),
        "variables": rows,
    }
    (outdir / "design_variable_manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    pd.DataFrame(rows).to_csv(outdir / "design_variable_manifest.csv", index=False)


def boundary_from_points(points_xy):
    """Builds boundary differential geometry from an explicit closed polygon."""

    points = np.asarray(points_xy, dtype=float)
    prev_points = np.roll(points, 1, axis=0)
    next_points = np.roll(points, -1, axis=0)
    tangent_vectors = next_points - prev_points
    tangent_norms = np.linalg.norm(tangent_vectors, axis=1, keepdims=True) + 1.0e-12
    tangents = tangent_vectors / tangent_norms
    normals = np.column_stack((tangents[:, 1], -tangents[:, 0]))
    centroid = np.mean(points, axis=0, keepdims=True)
    outward_hint = points - centroid
    normals[np.sum(normals * outward_hint, axis=1) < 0.0] *= -1.0

    edge_vectors = np.roll(points, -1, axis=0) - points
    edge_lengths = np.linalg.norm(edge_vectors, axis=1)
    ds = 0.5 * (edge_lengths + np.roll(edge_lengths, 1))
    perimeter_m = float(np.sum(edge_lengths))
    arc_positions = np.concatenate(([0.0], np.cumsum(edge_lengths[:-1])))
    arc_fraction = arc_positions / max(perimeter_m, 1.0e-9)
    support = np.sum(normals * points, axis=1)
    max_radius = float(np.max(np.linalg.norm(points, axis=1)))
    return points, normals, tangents, ds, support, arc_fraction, perimeter_m, max_radius


def disk_surface_field_to_remanence_t(surface_flux_t, diameter_m, thickness_m):
    """Infers an equivalent remanence from the on-axis surface field of a cylinder."""

    radius_m = 0.5 * diameter_m
    thickness_m = max(thickness_m, 1.0e-6)
    gain = 2.0 * math.sqrt(radius_m**2 + thickness_m**2) / thickness_m
    return min(DISK_REMANENCE_UPPER_T, surface_flux_t * gain)


def effective_flux_density_t(sku):
    """Calibrates a usable effective flux from catalog surface flux and pull force."""

    if getattr(sku, "magnet_shape", "block") == "disk":
        remanence_t = disk_surface_field_to_remanence_t(
            surface_flux_t=sku.surface_flux_t,
            diameter_m=sku.tangential_length_m,
            thickness_m=sku.radial_depth_m,
        )
        if getattr(sku, "pull_force_n", 0.0) and sku.pull_force_n > 0.0:
            pole_area_m2 = math.pi * (0.5 * sku.tangential_length_m) ** 2
            pull_equivalent_flux_t = math.sqrt(max(2.0 * MU0 * sku.pull_force_n / pole_area_m2, 0.0))
            remanence_t = max(remanence_t, 0.78 * pull_equivalent_flux_t)
        return remanence_t
    pole_area_m2 = max(sku.tangential_length_m * sku.axial_height_m, 1.0e-9)
    if getattr(sku, "pull_force_n", 0.0) and sku.pull_force_n > 0.0:
        pull_equivalent_flux_t = math.sqrt(max(2.0 * MU0 * sku.pull_force_n / pole_area_m2, 0.0))
        return max(sku.surface_flux_t, 0.78 * pull_equivalent_flux_t)
    return sku.surface_flux_t


def pole_face_area_m2(design: HifiDesign):
    """Returns the pole-face area of one real magnet that participates across the radial gap."""

    sku = base.MAGNET_CATALOG_BY_ID[design.magnet_sku_id]
    if getattr(sku, "magnet_shape", "block") == "disk":
        return math.pi * (0.5 * design.magnet_tangential_length_m) ** 2
    return max(design.magnet_tangential_length_m * design.magnet_axial_height_m, 1.0e-12)


def per_magnet_force_cap_n(design: HifiDesign):
    """Bounds one magnet's direct-action force using Maxwell stress and catalog pull force."""

    # Force ceilings should be tied to the exposed air-gap surface field, not the internal
    # remanence proxy used for dipole moment synthesis.
    pressure_force_n = (design.catalog_surface_flux_t**2) * pole_face_area_m2(design) / (2.0 * MU0)
    if design.catalog_pull_force_n > 0.0:
        return min(pressure_force_n, design.catalog_pull_force_n)
    return pressure_force_n


def array_level_force_cap_n(design: HifiDesign):
    """Builds a conservative directional net-force ceiling for one ring pair."""

    engaged_pairs = max(2.0, MAGNET_DIRECTIONAL_SECTOR_FRACTION * design.magnets_per_ring)
    cap_n = MAGNET_FORCE_CAP_MARGIN * per_magnet_force_cap_n(design) * engaged_pairs * design.magnet_layers
    return max(cap_n, 1.0)


def array_level_torque_cap_nm(design: HifiDesign):
    """Conservative yaw-torque ceiling from the same directional force budget."""

    return array_level_force_cap_n(design) * max(design.mean_radius_m, 1.0e-3)


def dipole_softening_length_m(design: HifiDesign, dipole_grid):
    """Equivalent-radius softening to avoid point-dipole singularities at short range."""

    tangential_count, radial_count, axial_count = dipole_grid
    sku = base.MAGNET_CATALOG_BY_ID[design.magnet_sku_id]
    if getattr(sku, "magnet_shape", "block") == "disk":
        cell_volume_m3 = (
            math.pi * (0.5 * design.magnet_tangential_length_m) ** 2 * design.magnet_radial_depth_m
        ) / max(tangential_count * radial_count * axial_count, 1)
    else:
        cell_volume_m3 = (
            design.magnet_tangential_length_m * design.magnet_radial_depth_m * design.magnet_axial_height_m
        ) / max(tangential_count * radial_count * axial_count, 1)
    return max((3.0 * cell_volume_m3 / (4.0 * math.pi)) ** (1.0 / 3.0), 2.5e-4)


def gap_decay_factor(min_gap_m: float, design: HifiDesign):
    """Simple finite-size attenuation for force caps across a practical air gap."""

    characteristic_length_m = max(0.5 * design.magnet_tangential_length_m, 1.0e-4)
    ratio = max(min_gap_m, 0.0) / characteristic_length_m
    return 1.0 / ((1.0 + ratio) ** 2)


def sample_ring_sites(points_xy, normals_xy, tangents_xy, perimeter_m, count):
    """Samples equally spaced magnet sites along the perimeter."""

    edge_vectors = np.roll(points_xy, -1, axis=0) - points_xy
    edge_lengths = np.linalg.norm(edge_vectors, axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(edge_lengths)))
    targets = np.linspace(0.0, perimeter_m, count, endpoint=False)
    site_points = []
    site_normals = []
    site_tangents = []
    for target in targets:
        edge_index = int(np.searchsorted(cumulative, target, side="right") - 1)
        edge_index = min(edge_index, len(edge_lengths) - 1)
        local = (target - cumulative[edge_index]) / max(edge_lengths[edge_index], 1.0e-12)
        next_index = (edge_index + 1) % len(points_xy)
        point = (1.0 - local) * points_xy[edge_index] + local * points_xy[next_index]
        normal = (1.0 - local) * normals_xy[edge_index] + local * normals_xy[next_index]
        tangent = (1.0 - local) * tangents_xy[edge_index] + local * tangents_xy[next_index]
        normal /= np.linalg.norm(normal) + 1.0e-12
        tangent /= np.linalg.norm(tangent) + 1.0e-12
        site_points.append(point)
        site_normals.append(normal)
        site_tangents.append(tangent)
    return np.asarray(site_points), np.asarray(site_normals), np.asarray(site_tangents)


def cuboid_dipole_cloud(center_xyz, tangent_xy, normal_xy, dims_m, moment_direction_xyz, effective_flux_t, dipole_grid):
    """Represents one cuboid magnet as a coarse cloud of volume dipoles."""

    tangential_count, radial_count, axial_count = dipole_grid
    tangent_values = (np.arange(tangential_count) - 0.5 * (tangential_count - 1)) * (dims_m[0] / tangential_count)
    radial_values = (np.arange(radial_count) - 0.5 * (radial_count - 1)) * (dims_m[1] / radial_count)
    axial_values = (np.arange(axial_count) - 0.5 * (axial_count - 1)) * (dims_m[2] / axial_count)

    tangent_axis = np.array([tangent_xy[0], tangent_xy[1], 0.0], dtype=float)
    normal_axis = np.array([normal_xy[0], normal_xy[1], 0.0], dtype=float)
    z_axis = np.array([0.0, 0.0, 1.0], dtype=float)

    cell_volume_m3 = (dims_m[0] / tangential_count) * (dims_m[1] / radial_count) * (dims_m[2] / axial_count)
    moment_magnitude = effective_flux_t * cell_volume_m3 / MU0
    centers = []
    moments = []
    for tangential_offset in tangent_values:
        for radial_offset in radial_values:
            for axial_offset in axial_values:
                centers.append(
                    center_xyz
                    + tangential_offset * tangent_axis
                    + radial_offset * normal_axis
                    + axial_offset * z_axis
                )
                moments.append(moment_direction_xyz * moment_magnitude)
    return np.asarray(centers), np.asarray(moments)


def cylindrical_dipole_cloud(center_xyz, tangent_xy, normal_xy, dims_m, moment_direction_xyz, effective_flux_t, dipole_grid):
    """Represents one radially oriented disk magnet as a cloud of equal-weight dipoles."""

    tangential_count, radial_count, axial_count = dipole_grid
    diameter_m = dims_m[0]
    radius_m = 0.5 * diameter_m
    tangent_values = (np.arange(tangential_count) - 0.5 * (tangential_count - 1)) * (diameter_m / tangential_count)
    radial_values = (np.arange(radial_count) - 0.5 * (radial_count - 1)) * (dims_m[1] / radial_count)
    axial_values = (np.arange(axial_count) - 0.5 * (axial_count - 1)) * (dims_m[2] / axial_count)

    tangent_axis = np.array([tangent_xy[0], tangent_xy[1], 0.0], dtype=float)
    normal_axis = np.array([normal_xy[0], normal_xy[1], 0.0], dtype=float)
    z_axis = np.array([0.0, 0.0, 1.0], dtype=float)

    accepted_offsets = []
    for tangential_offset in tangent_values:
        for axial_offset in axial_values:
            if tangential_offset**2 + axial_offset**2 <= radius_m**2 + 1.0e-12:
                accepted_offsets.append((tangential_offset, axial_offset))
    if not accepted_offsets:
        accepted_offsets.append((0.0, 0.0))

    cell_volume_m3 = math.pi * radius_m**2 * dims_m[1] / (len(accepted_offsets) * radial_count)
    moment_magnitude = effective_flux_t * cell_volume_m3 / MU0
    centers = []
    moments = []
    for tangential_offset, axial_offset in accepted_offsets:
        for radial_offset in radial_values:
            centers.append(
                center_xyz
                + tangential_offset * tangent_axis
                + radial_offset * normal_axis
                + axial_offset * z_axis
            )
            moments.append(moment_direction_xyz * moment_magnitude)
    return np.asarray(centers), np.asarray(moments)


def build_design_from_latent(latent_vector, num_samples, catalog=None, fixed_cart_mass_kg=None, shape_family_mode="both"):
    """Materializes a searched design candidate from its latent parameter vector."""

    if catalog is None:
        catalog = base.MAGNET_CATALOG
    bounded = base.sigmoid(latent_vector)
    if shape_family_mode == "flex":
        sku = choose_catalog_sku_from_list(bounded[23], catalog)
        shape_params = ShapeParameters(
            aspect_ratio=0.60 + 1.10 * bounded[0],
            superellipse_exponent=1.8 + 10.0 * bounded[1],
            polygon_weight=0.80 * bounded[2],
            polygon_sides=int(base.clamp(round(3.0 + 9.0 * bounded[3]), 3, 12)),
            shape_phase_fraction=bounded[4] % 1.0,
            harmonic3=signed(-0.26, 0.26, bounded[5]),
            harmonic4=signed(-0.22, 0.22, bounded[6]),
            harmonic5=signed(-0.20, 0.20, bounded[7]),
            harmonic6=signed(-0.18, 0.18, bounded[8]),
            harmonic7=signed(-0.16, 0.16, bounded[9]),
            harmonic8=signed(-0.14, 0.14, bounded[10]),
            harmonic9=signed(-0.12, 0.12, bounded[11]),
            harmonic10=signed(-0.10, 0.10, bounded[12]),
            harmonic11=signed(-0.08, 0.08, bounded[13]),
            harmonic12=signed(-0.07, 0.07, bounded[14]),
            local_feature1_amplitude=signed(-0.22, 0.22, bounded[15]),
            local_feature1_phase_fraction=bounded[16] % 1.0,
            local_feature1_width_fraction=0.04 + 0.26 * bounded[17],
            local_feature2_amplitude=signed(-0.20, 0.20, bounded[18]),
            local_feature2_phase_fraction=bounded[19] % 1.0,
            local_feature2_width_fraction=0.04 + 0.26 * bounded[20],
            family="flex",
        )
        if getattr(sku, "magnet_shape", "block") == "disk":
            min_gap_m = 0.0060
            max_gap_m = min(0.042, 1.85 * sku.tangential_length_m)
        else:
            min_gap_m = max(0.0045, 2.2 * sku.radial_depth_m)
            max_gap_m = min(0.070, min_gap_m + 0.045)
        gap_m = min_gap_m + (max_gap_m - min_gap_m) * bounded[21]
        max_mean_radius_m = 0.145 if getattr(sku, "magnet_shape", "block") == "disk" else 0.210
        mean_radius_m = 0.060 + (max_mean_radius_m - 0.060) * bounded[22]
        geometry = build_flexible_geometry(shape_params, mean_radius_m, gap_m, num_samples)

        max_layers = (
            max(1, int(math.floor(DISK_STACK_HEIGHT_LIMIT_M / max(sku.axial_height_m, 1.0e-6) + 1.0e-9)))
            if getattr(sku, "magnet_shape", "block") == "disk"
            else 6
        )
        magnet_layers = int(base.clamp(round(1.0 + (max_layers - 1.0) * bounded[24]), 1, max_layers))
        if getattr(sku, "magnet_shape", "block") == "disk":
            target_fill_ratio = 0.55 + 0.37 * bounded[25]
        else:
            target_fill_ratio = 0.56 + 0.34 * bounded[25]
        phase_offset_fraction = signed(-0.48, 0.48, bounded[26])
        overlap_ratio = 0.18 + 0.60 * bounded[27]
        if fixed_cart_mass_kg is not None:
            cart_mass_kg = float(fixed_cart_mass_kg)
        elif getattr(sku, "magnet_shape", "block") == "disk":
            cart_mass_kg = 8.0 + 27.0 * bounded[28]
        else:
            cart_mass_kg = 10.0 + 25.0 * bounded[28]

        if getattr(sku, "magnet_shape", "block") == "disk":
            mounting_clearance_m = 0.00045
        else:
            mounting_clearance_m = 0.0014 if "countersunk" in sku.mount_style else 0.0010
        max_count = max(
            8,
            int(geometry.inner_perimeter_m / max(sku.tangential_length_m + mounting_clearance_m, 1.0e-3)),
        )
        target_count = int(round(target_fill_ratio * geometry.inner_perimeter_m / max(sku.tangential_length_m, 1.0e-3)))
        magnets_per_ring = int(base.clamp(target_count, 8, max_count))
        pitch_m = geometry.inner_perimeter_m / magnets_per_ring
        coverage_ratio = min(0.97, sku.tangential_length_m / max(pitch_m, 1.0e-6))
        tangential_gap_m = max(0.0, pitch_m - sku.tangential_length_m)
        nominal_overlap_m = magnet_layers * sku.axial_height_m
        max_overlap_reduction_m = overlap_ratio * nominal_overlap_m
        total_magnets = 2 * magnet_layers * magnets_per_ring
        estimated_total_cost_jpy = total_magnets * sku.unit_price_jpy
        effective_flux_t = effective_flux_density_t(sku)

        design = HifiDesign(
            shape_parameters=shape_params,
            gap_m=gap_m,
            mean_radius_m=mean_radius_m,
            magnet_sku_id=sku.sku_id,
            magnet_vendor=sku.vendor,
            magnet_tangential_length_m=sku.tangential_length_m,
            magnet_axial_height_m=sku.axial_height_m,
            magnet_radial_depth_m=sku.radial_depth_m,
            magnets_per_ring=magnets_per_ring,
            magnet_layers=magnet_layers,
            coverage_ratio=coverage_ratio,
            pitch_m=pitch_m,
            tangential_gap_m=tangential_gap_m,
            outer_phase_fraction=phase_offset_fraction,
            nominal_overlap_m=nominal_overlap_m,
            max_overlap_reduction_m=max_overlap_reduction_m,
            cart_mass_kg=cart_mass_kg,
            total_magnets=total_magnets,
            estimated_total_cost_jpy=estimated_total_cost_jpy,
            catalog_surface_flux_t=sku.surface_flux_t,
            catalog_pull_force_n=sku.pull_force_n,
            effective_flux_t=effective_flux_t,
        )
        return design, geometry
    if shape_family_mode == "arrow":
        family = "arrow"
    elif shape_family_mode == "flex":
        family = "flex"
    else:
        family = "arrow" if bounded[0] >= 0.5 else "flex"
    sku = choose_catalog_sku_from_list(bounded[11], catalog)
    shape_params = ShapeParameters(
        aspect_ratio=0.68 + 0.92 * bounded[1],
        superellipse_exponent=2.0 + 8.5 * bounded[2],
        polygon_weight=0.68 * bounded[3],
        polygon_sides=int(base.clamp(round(3.0 + 9.0 * bounded[4]), 3, 12)),
        harmonic3=signed(-0.24, 0.24, bounded[5]),
        harmonic4=signed(-0.20, 0.20, bounded[6]),
        harmonic5=signed(-0.20, 0.20, bounded[7]),
        harmonic6=signed(-0.12, 0.12, bounded[8]),
        family=family,
        arrow_head_length_ratio=0.34 + 0.48 * bounded[17],
        arrow_head_half_width_ratio=0.74 + 0.58 * bounded[18],
        arrow_shaft_half_width_ratio=0.18 + 0.30 * bounded[19],
        arrow_neck_fraction=0.10 + 0.78 * bounded[20],
        arrow_corner_rounding=bounded[21],
    )
    if getattr(sku, "magnet_shape", "block") == "disk":
        min_gap_m = 0.0060
        max_gap_m = min(0.042, 1.85 * sku.tangential_length_m)
    else:
        min_gap_m = max(0.0045, 2.2 * sku.radial_depth_m)
        max_gap_m = min(0.070, min_gap_m + 0.045)
    gap_m = min_gap_m + (max_gap_m - min_gap_m) * bounded[9]
    max_mean_radius_m = 0.145 if getattr(sku, "magnet_shape", "block") == "disk" else 0.210
    mean_radius_m = 0.060 + (max_mean_radius_m - 0.060) * bounded[10]
    geometry = build_geometry_from_shape(shape_params, mean_radius_m, gap_m, num_samples)

    max_layers = (
        max(1, int(math.floor(DISK_STACK_HEIGHT_LIMIT_M / max(sku.axial_height_m, 1.0e-6) + 1.0e-9)))
        if getattr(sku, "magnet_shape", "block") == "disk"
        else 6
    )
    magnet_layers = int(base.clamp(round(1.0 + (max_layers - 1.0) * bounded[12]), 1, max_layers))
    if getattr(sku, "magnet_shape", "block") == "disk":
        target_fill_ratio = 0.55 + 0.37 * bounded[13]
    else:
        target_fill_ratio = 0.56 + 0.34 * bounded[13]
    phase_offset_fraction = signed(-0.48, 0.48, bounded[14])
    overlap_ratio = 0.18 + 0.60 * bounded[15]
    if fixed_cart_mass_kg is not None:
        cart_mass_kg = float(fixed_cart_mass_kg)
    elif getattr(sku, "magnet_shape", "block") == "disk":
        cart_mass_kg = 8.0 + 27.0 * bounded[16]
    else:
        cart_mass_kg = 10.0 + 25.0 * bounded[16]

    if getattr(sku, "magnet_shape", "block") == "disk":
        mounting_clearance_m = 0.00045
    else:
        mounting_clearance_m = 0.0014 if "countersunk" in sku.mount_style else 0.0010
    max_count = max(8, int(geometry.inner_perimeter_m / max(sku.tangential_length_m + mounting_clearance_m, 1.0e-3)))
    target_count = int(round(target_fill_ratio * geometry.inner_perimeter_m / max(sku.tangential_length_m, 1.0e-3)))
    magnets_per_ring = int(base.clamp(target_count, 8, max_count))
    pitch_m = geometry.inner_perimeter_m / magnets_per_ring
    coverage_ratio = min(0.97, sku.tangential_length_m / max(pitch_m, 1.0e-6))
    tangential_gap_m = max(0.0, pitch_m - sku.tangential_length_m)
    nominal_overlap_m = magnet_layers * sku.axial_height_m
    max_overlap_reduction_m = overlap_ratio * nominal_overlap_m
    total_magnets = 2 * magnet_layers * magnets_per_ring
    estimated_total_cost_jpy = total_magnets * sku.unit_price_jpy
    effective_flux_t = effective_flux_density_t(sku)

    design = HifiDesign(
        shape_parameters=shape_params,
        gap_m=gap_m,
        mean_radius_m=mean_radius_m,
        magnet_sku_id=sku.sku_id,
        magnet_vendor=sku.vendor,
        magnet_tangential_length_m=sku.tangential_length_m,
        magnet_axial_height_m=sku.axial_height_m,
        magnet_radial_depth_m=sku.radial_depth_m,
        magnets_per_ring=magnets_per_ring,
        magnet_layers=magnet_layers,
        coverage_ratio=coverage_ratio,
        pitch_m=pitch_m,
        tangential_gap_m=tangential_gap_m,
        outer_phase_fraction=phase_offset_fraction,
        nominal_overlap_m=nominal_overlap_m,
        max_overlap_reduction_m=max_overlap_reduction_m,
        cart_mass_kg=cart_mass_kg,
        total_magnets=total_magnets,
        estimated_total_cost_jpy=estimated_total_cost_jpy,
        catalog_surface_flux_t=sku.surface_flux_t,
        catalog_pull_force_n=sku.pull_force_n,
        effective_flux_t=effective_flux_t,
    )
    return design, geometry


def build_array_model(design: HifiDesign, geometry: base.Geometry, dipole_grid):
    """Creates the discrete dipole clouds for the searched design."""

    sku = base.MAGNET_CATALOG_BY_ID[design.magnet_sku_id]
    softening_length_m = dipole_softening_length_m(design, dipole_grid)
    translational_force_cap_n = array_level_force_cap_n(design)
    yaw_torque_cap_nm = array_level_torque_cap_nm(design)

    inner_points, inner_normals, inner_tangents = sample_ring_sites(
        geometry.inner_points,
        geometry.inner_normals,
        geometry.inner_tangents,
        geometry.inner_perimeter_m,
        design.magnets_per_ring,
    )
    outer_points, outer_outward_normals, outer_tangents = sample_ring_sites(
        geometry.outer_points_local,
        geometry.outer_outward_normals_local,
        geometry.outer_tangents_local,
        geometry.outer_perimeter_m,
        design.magnets_per_ring,
    )

    phase_offset_sites = int(round(design.outer_phase_fraction * design.magnets_per_ring))
    outer_points = np.roll(outer_points, phase_offset_sites, axis=0)
    outer_outward_normals = np.roll(outer_outward_normals, phase_offset_sites, axis=0)
    outer_tangents = np.roll(outer_tangents, phase_offset_sites, axis=0)

    z_centers = (
        np.arange(design.magnet_layers, dtype=float) - 0.5 * (design.magnet_layers - 1)
    ) * design.magnet_axial_height_m
    dims_m = np.array(
        [
            design.magnet_tangential_length_m,
            design.magnet_radial_depth_m,
            design.magnet_axial_height_m,
        ],
        dtype=float,
    )

    inner_cloud_centers = []
    inner_cloud_moments = []
    outer_cloud_centers = []
    outer_cloud_moments = []
    inner_magnet_centers_xyz = []
    inner_moment_dirs_xyz = []
    outer_magnet_centers_local_xyz = []
    outer_moment_dirs_local_xyz = []

    for z_center in z_centers:
        for point_xy, normal_xy, tangent_xy in zip(inner_points, inner_normals, inner_tangents):
            magnet_center_xyz = np.array(
                [
                    point_xy[0] - 0.5 * design.magnet_radial_depth_m * normal_xy[0],
                    point_xy[1] - 0.5 * design.magnet_radial_depth_m * normal_xy[1],
                    z_center,
                ],
                dtype=float,
            )
            moment_direction_xyz = np.array([normal_xy[0], normal_xy[1], 0.0], dtype=float)
            inner_magnet_centers_xyz.append(magnet_center_xyz)
            inner_moment_dirs_xyz.append(moment_direction_xyz)
            if getattr(sku, "magnet_shape", "block") == "disk":
                centers, moments = cylindrical_dipole_cloud(
                    magnet_center_xyz,
                    tangent_xy,
                    normal_xy,
                    dims_m,
                    moment_direction_xyz,
                    design.effective_flux_t,
                    dipole_grid,
                )
            else:
                centers, moments = cuboid_dipole_cloud(
                    magnet_center_xyz,
                    tangent_xy,
                    normal_xy,
                    dims_m,
                    moment_direction_xyz,
                    design.effective_flux_t,
                    dipole_grid,
                )
            inner_cloud_centers.append(centers)
            inner_cloud_moments.append(moments)

        for point_xy, outward_xy, tangent_xy in zip(outer_points, outer_outward_normals, outer_tangents):
            magnet_center_xyz = np.array(
                [
                    point_xy[0] + 0.5 * design.magnet_radial_depth_m * outward_xy[0],
                    point_xy[1] + 0.5 * design.magnet_radial_depth_m * outward_xy[1],
                    z_center,
                ],
                dtype=float,
            )
            moment_direction_xyz = np.array([-outward_xy[0], -outward_xy[1], 0.0], dtype=float)
            outer_magnet_centers_local_xyz.append(magnet_center_xyz)
            outer_moment_dirs_local_xyz.append(moment_direction_xyz)
            if getattr(sku, "magnet_shape", "block") == "disk":
                centers, moments = cylindrical_dipole_cloud(
                    magnet_center_xyz,
                    tangent_xy,
                    outward_xy,
                    dims_m,
                    moment_direction_xyz,
                    design.effective_flux_t,
                    dipole_grid,
                )
            else:
                centers, moments = cuboid_dipole_cloud(
                    magnet_center_xyz,
                    tangent_xy,
                    outward_xy,
                    dims_m,
                    moment_direction_xyz,
                    design.effective_flux_t,
                    dipole_grid,
                )
            outer_cloud_centers.append(centers)
            outer_cloud_moments.append(moments)

    return ArrayModel(
        design=design,
        geometry=geometry,
        inner_centers_xyz=np.vstack(inner_cloud_centers),
        inner_moments_xyz=np.vstack(inner_cloud_moments),
        outer_centers_local_xyz=np.vstack(outer_cloud_centers),
        outer_moments_local_xyz=np.vstack(outer_cloud_moments),
        inner_magnet_centers_xy=inner_points - 0.5 * design.magnet_radial_depth_m * inner_normals,
        inner_normals_xy=inner_normals,
        inner_tangents_xy=inner_tangents,
        outer_magnet_centers_local_xy=outer_points + 0.5 * design.magnet_radial_depth_m * outer_outward_normals,
        outer_outward_normals_local_xy=outer_outward_normals,
        outer_tangents_local_xy=outer_tangents,
        inner_magnet_centers_xyz=np.asarray(inner_magnet_centers_xyz, dtype=float),
        inner_moment_dirs_xyz=np.asarray(inner_moment_dirs_xyz, dtype=float),
        outer_magnet_centers_local_xyz=np.asarray(outer_magnet_centers_local_xyz, dtype=float),
        outer_moment_dirs_local_xyz=np.asarray(outer_moment_dirs_local_xyz, dtype=float),
        dipole_grid=dipole_grid,
        dipoles_per_magnet=int(np.prod(dipole_grid)),
        dipole_softening_length_m=softening_length_m,
        translational_force_cap_n=translational_force_cap_n,
        yaw_torque_cap_nm=yaw_torque_cap_nm,
        yaw_contact_limit_rad=geometry.yaw_contact_limit_rad,
        translation_contact_limit_m=geometry.translation_contact_limit_m,
    )


def transform_outer_array(model: ArrayModel, relative_translation_body_m, relative_yaw_rad, height_shift_m):
    """Applies rigid-body translation, yaw, and height shift to the outer ring."""

    rotation = base.rotmat(relative_yaw_rad)
    centers_xy = model.outer_centers_local_xyz[:, :2] @ rotation.T + relative_translation_body_m
    moments_xy = model.outer_moments_local_xyz[:, :2] @ rotation.T
    centers_xyz = np.column_stack((centers_xy, model.outer_centers_local_xyz[:, 2] + height_shift_m))
    moments_xyz = np.column_stack((moments_xy, model.outer_moments_local_xyz[:, 2]))
    return centers_xyz, moments_xyz


def dipole_force_torque_energy(
    inner_centers_xyz,
    inner_moments_xyz,
    outer_centers_xyz,
    outer_moments_xyz,
    softening_length_m,
):
    """Computes rigid-body force, torque, and energy from dipole-dipole interactions.

    A finite softening length is used so the point-dipole cloud remains a usable approximation
    to a finite magnet volume even when two cells pass very close to each other.
    """

    inner_count = inner_centers_xyz.shape[0]
    outer_count = outer_centers_xyz.shape[0]
    # Chunk over outer dipoles to keep high-fidelity searches stable under long campaigns.
    chunk_size = max(16, min(128, 65536 // max(inner_count, 1)))
    b_prefactor = MU0 / (4.0 * math.pi)
    f_prefactor = 3.0 * MU0 / (4.0 * math.pi)
    net_field_on_outer = np.zeros_like(outer_centers_xyz, dtype=float)
    force_on_outer_dipoles = np.zeros_like(outer_centers_xyz, dtype=float)
    softening_sq = float(max(softening_length_m, 1.0e-6) ** 2)

    for start in range(0, outer_count, chunk_size):
        stop = min(start + chunk_size, outer_count)
        outer_centers_chunk = outer_centers_xyz[start:stop]
        outer_moments_chunk = outer_moments_xyz[start:stop]
        displacement = outer_centers_chunk[None, :, :] - inner_centers_xyz[:, None, :]
        distance_sq = np.sum(displacement * displacement, axis=2) + softening_sq
        distance = np.sqrt(distance_sq)
        r_hat = displacement / distance[:, :, None]

        m1_dot_r = np.sum(inner_moments_xyz[:, None, :] * r_hat, axis=2)
        m2_dot_r = np.sum(outer_moments_chunk[None, :, :] * r_hat, axis=2)
        m1_dot_m2 = np.einsum("id,jd->ij", inner_moments_xyz, outer_moments_chunk)

        field_from_inner = b_prefactor * (
            (3.0 * m1_dot_r[:, :, None] * r_hat - inner_moments_xyz[:, None, :])
            / (distance_sq * distance)[:, :, None]
        )
        net_field_on_outer[start:stop] = np.sum(field_from_inner, axis=0)

        pair_force = f_prefactor * (
            (
                m1_dot_r[:, :, None] * outer_moments_chunk[None, :, :]
                + m2_dot_r[:, :, None] * inner_moments_xyz[:, None, :]
                + m1_dot_m2[:, :, None] * r_hat
                - 5.0 * m1_dot_r[:, :, None] * m2_dot_r[:, :, None] * r_hat
            )
            / (distance_sq * distance_sq)[:, :, None]
        )
        force_on_outer_dipoles[start:stop] = np.sum(pair_force, axis=0)

    intrinsic_torque = np.cross(outer_moments_xyz, net_field_on_outer)
    torque_z = np.sum(
        outer_centers_xyz[:, 0] * force_on_outer_dipoles[:, 1]
        - outer_centers_xyz[:, 1] * force_on_outer_dipoles[:, 0]
        + intrinsic_torque[:, 2]
    )
    potential_energy = -float(np.sum(outer_moments_xyz * net_field_on_outer))
    return np.sum(force_on_outer_dipoles[:, :2], axis=0), float(torque_z), potential_energy


def evaluate_pose(model: ArrayModel, relative_translation_body_m, relative_yaw_rad, height_shift_m):
    """Evaluates one relative pose using the discrete actual magnet array."""

    sat_gap_m, sat_normal, sat_inner_point, sat_outer_point = base.sat_signed_gap_profile(
        model.geometry,
        relative_translation_body_m,
        relative_yaw_rad,
    )
    penetration_m = max(0.0, -float(sat_gap_m))
    effective_translation_body_m = np.asarray(relative_translation_body_m, dtype=float)
    if penetration_m > 0.0:
        # Never evaluate magnetic forces on an interpenetrating pose; project to the first
        # non-penetrating configuration and let contact handling account for the overlap.
        effective_translation_body_m = effective_translation_body_m + sat_normal * penetration_m

    outer_centers_xyz, outer_moments_xyz = transform_outer_array(
        model,
        relative_translation_body_m=effective_translation_body_m,
        relative_yaw_rad=relative_yaw_rad,
        height_shift_m=height_shift_m,
    )
    force_body_n, torque_outer_nm, potential_energy_j = dipole_force_torque_energy(
        model.inner_centers_xyz,
        model.inner_moments_xyz,
        outer_centers_xyz,
        outer_moments_xyz,
        model.dipole_softening_length_m,
    )
    min_gap_m = max(float(sat_gap_m), 0.0)
    cap_decay = gap_decay_factor(min_gap_m, model.design)
    force_cap_n = max(0.5, model.translational_force_cap_n * cap_decay)
    torque_cap_nm = max(0.05, model.yaw_torque_cap_nm * cap_decay)
    force_body_n = base.clamp_norm(force_body_n, force_cap_n)
    torque_outer_nm = base.clamp(torque_outer_nm, -torque_cap_nm, torque_cap_nm)
    torque_inner_nm = -torque_outer_nm
    return PoseSample(
        force_body_n=force_body_n,
        torque_outer_nm=torque_outer_nm,
        torque_inner_nm=torque_inner_nm,
        potential_energy_j=potential_energy_j,
        min_gap_m=min_gap_m,
        raw_signed_gap_m=float(sat_gap_m),
        contact_penetration_m=penetration_m,
        contact_normal_body=sat_normal,
        inner_contact_point_body=sat_inner_point,
        outer_contact_point_body=sat_outer_point,
    )


def assess_static_design(model: ArrayModel, directions, displacements_m, height_fractions, yaw_samples_rad):
    """Scores restoring linearity, isotropy, and anti-latching behavior."""

    design = model.design
    representative_tow_offsets_m = np.unique(
        np.array(
            [
                displacements_m[min(1, len(displacements_m) - 1)],
                displacements_m[-1],
            ],
            dtype=float,
        )
    )
    full_height_reference = []
    reduced_height_reference = []
    orthogonal_ratios = []
    torque_ratios = []
    forward_torque_ratios = []
    line_r2_values = []
    direction_stiffness = []
    yaw_stiffness_values = []
    towed_yaw_stiffness_values = []
    min_parallel_force_n = float("inf")
    min_yaw_restoring_nm = float("inf")
    min_towed_yaw_restoring_nm = float("inf")
    negative_restore_count = 0
    negative_yaw_restore_count = 0
    negative_towed_yaw_restore_count = 0
    contact_count = 0

    height_series_force = []
    height_series_shift = []

    for height_fraction in height_fractions:
        height_shift_m = height_fraction * design.max_overlap_reduction_m
        baseline = evaluate_pose(model, np.zeros(2, dtype=float), 0.0, height_shift_m)
        reference_forces = []
        for angle in directions:
            direction = np.array([math.cos(angle), math.sin(angle)], dtype=float)
            parallel_force_values = []
            for displacement_m in displacements_m:
                sample = evaluate_pose(model, displacement_m * direction, 0.0, height_shift_m)
                parallel_force_n = -float(np.dot(sample.force_body_n, direction))
                orthogonal_force_n = abs(base.cross2(direction, sample.force_body_n))
                torque_ratio = abs(sample.torque_outer_nm) / max(abs(parallel_force_n) * model.design.mean_radius_m, 1.0e-6)

                min_parallel_force_n = min(min_parallel_force_n, parallel_force_n)
                if parallel_force_n <= 0.0:
                    negative_restore_count += 1
                if sample.contact_penetration_m > 0.0:
                    contact_count += 1

                orthogonal_ratios.append(orthogonal_force_n / max(abs(parallel_force_n), 1.0e-6))
                torque_ratios.append(torque_ratio)
                parallel_force_values.append(parallel_force_n)

            slope, _intercept, r2 = fit_line(displacements_m, parallel_force_values)
            line_r2_values.append(r2)
            reference_forces.append(parallel_force_values[min(1, len(parallel_force_values) - 1)])
            direction_stiffness.append(slope)
            if height_fraction <= 0.05:
                full_height_reference.append(slope)
            else:
                reduced_height_reference.append(slope)

        mean_reference_force = float(np.mean(reference_forces)) if reference_forces else 0.0
        height_series_shift.append(height_shift_m)
        height_series_force.append(mean_reference_force)

        for yaw_rad in yaw_samples_rad:
            sample = evaluate_pose(model, np.zeros(2, dtype=float), yaw_rad, height_shift_m)
            restoring_torque_nm = -sample.torque_outer_nm * math.copysign(1.0, yaw_rad)
            min_yaw_restoring_nm = min(min_yaw_restoring_nm, restoring_torque_nm)
            yaw_failure = restoring_torque_nm <= 0.0 or sample.potential_energy_j < baseline.potential_energy_j - 1.0e-6
            if yaw_failure:
                negative_yaw_restore_count += 1
            if sample.contact_penetration_m > 0.0:
                contact_count += 1
            yaw_stiffness_values.append(restoring_torque_nm / max(abs(yaw_rad), 1.0e-6))

        for tow_offset_m in representative_tow_offsets_m:
            towed_baseline = evaluate_pose(model, np.array([0.0, tow_offset_m], dtype=float), 0.0, height_shift_m)
            forward_force_n = -float(np.dot(towed_baseline.force_body_n, np.array([0.0, 1.0], dtype=float)))
            forward_torque_ratios.append(
                abs(towed_baseline.torque_outer_nm) / max(abs(forward_force_n) * design.mean_radius_m, 1.0e-6)
            )
            if towed_baseline.contact_penetration_m > 0.0:
                contact_count += 1
            for yaw_rad in yaw_samples_rad:
                sample = evaluate_pose(model, np.array([0.0, tow_offset_m], dtype=float), yaw_rad, height_shift_m)
                restoring_torque_nm = -sample.torque_outer_nm * math.copysign(1.0, yaw_rad)
                min_towed_yaw_restoring_nm = min(min_towed_yaw_restoring_nm, restoring_torque_nm)
                yaw_failure = restoring_torque_nm <= 0.0 or sample.potential_energy_j < towed_baseline.potential_energy_j - 1.0e-6
                if yaw_failure:
                    negative_towed_yaw_restore_count += 1
                if sample.contact_penetration_m > 0.0:
                    contact_count += 1
                towed_yaw_stiffness_values.append(restoring_torque_nm / max(abs(yaw_rad), 1.0e-6))

    _height_slope, _height_intercept, height_r2 = fit_line(height_series_shift, height_series_force)
    mean_full_stiffness = float(np.mean(full_height_reference)) if full_height_reference else 0.0
    min_reduced_stiffness = float(np.min(reduced_height_reference)) if reduced_height_reference else mean_full_stiffness
    mean_orthogonal_ratio = float(np.mean(orthogonal_ratios)) if orthogonal_ratios else 1.0
    direction_cv = (
        float(np.std(direction_stiffness) / max(abs(np.mean(direction_stiffness)), 1.0e-6))
        if direction_stiffness
        else 1.0
    )
    mean_r2 = float(np.mean(line_r2_values)) if line_r2_values else 0.0
    mean_torque_ratio = float(np.mean(torque_ratios)) if torque_ratios else 1.0
    mean_forward_torque_ratio = float(np.mean(forward_torque_ratios)) if forward_torque_ratios else mean_torque_ratio
    mean_yaw_stiffness = float(np.mean(yaw_stiffness_values)) if yaw_stiffness_values else 0.0
    mean_towed_yaw_stiffness = (
        float(np.mean(towed_yaw_stiffness_values)) if towed_yaw_stiffness_values else mean_yaw_stiffness
    )
    nominal_tow_force_n = CART_SUSTAINED_RESISTANCE_COEFF * design.cart_mass_kg * 9.81
    nominal_tow_offset_proxy_m = nominal_tow_force_n / max(mean_full_stiffness, 1.0e-6)
    reduced_tow_offset_proxy_m = nominal_tow_force_n / max(min_reduced_stiffness, 1.0e-6)
    stiffness_modulation_ratio = mean_full_stiffness / max(min_reduced_stiffness, 1.0e-6)
    if min_yaw_restoring_nm == float("inf"):
        min_yaw_restoring_nm = 0.0
    if min_towed_yaw_restoring_nm == float("inf"):
        min_towed_yaw_restoring_nm = 0.0

    inner_min = np.min(model.geometry.inner_points, axis=0)
    inner_max = np.max(model.geometry.inner_points, axis=0)
    outer_min = np.min(model.geometry.outer_points_local, axis=0)
    outer_max = np.max(model.geometry.outer_points_local, axis=0)
    inner_width_m = float(inner_max[0] - inner_min[0])
    inner_length_m = float(inner_max[1] - inner_min[1])
    outer_width_m = float(outer_max[0] - outer_min[0])
    outer_length_m = float(outer_max[1] - outer_min[1])
    package_violation_m = (
        max(0.0, inner_width_m - (ROBOT_WIDTH_M + ROBOT_MOUNT_WIDTH_ALLOWANCE_M))
        + max(0.0, inner_length_m - (ROBOT_LENGTH_M + ROBOT_MOUNT_LENGTH_ALLOWANCE_M))
        + max(0.0, outer_width_m - (CART_WIDTH_M - CART_MOUNT_MARGIN_M))
        + max(0.0, outer_length_m - (CART_LENGTH_M - CART_MOUNT_MARGIN_M))
    )

    score = 0.0
    orthogonal_excess = max(0.0, mean_orthogonal_ratio - 0.10)
    forward_torque_excess = max(0.0, mean_forward_torque_ratio - 0.055)
    translation_torque_excess = max(0.0, mean_torque_ratio - 0.080)
    score += 0.07 * mean_full_stiffness
    score += 0.06 * min_reduced_stiffness
    score += 0.18 * mean_yaw_stiffness
    score += 0.22 * mean_towed_yaw_stiffness
    score += 60.0 * min_yaw_restoring_nm
    score += 80.0 * min_towed_yaw_restoring_nm
    score -= 380.0 * mean_orthogonal_ratio
    score -= 160.0 * direction_cv
    score -= 120.0 * (1.0 - mean_r2)
    score -= 75.0 * (1.0 - height_r2)
    score -= 280.0 * mean_torque_ratio
    score -= 360.0 * mean_forward_torque_ratio
    score -= 2200.0 * orthogonal_excess
    score -= 1800.0 * forward_torque_excess
    score -= 1200.0 * translation_torque_excess
    score -= 3600.0 * negative_restore_count
    score -= 14000.0 * negative_yaw_restore_count
    score -= 18000.0 * negative_towed_yaw_restore_count
    score -= 5000.0 * contact_count
    score -= 180000.0 * max(0.0, -min_yaw_restoring_nm)
    score -= 240000.0 * max(0.0, -min_towed_yaw_restoring_nm)
    score -= 2400000.0 * max(0.0, nominal_tow_offset_proxy_m - 0.008)
    score -= 1600000.0 * max(0.0, reduced_tow_offset_proxy_m - 0.020)
    score -= 2400.0 * abs(stiffness_modulation_ratio - 2.0)
    score -= 16000.0 * max(0.0, 1.20 - stiffness_modulation_ratio)
    score -= 800000.0 * package_violation_m
    score -= 0.0028 * design.estimated_total_cost_jpy
    score -= 0.35 * design.total_magnets

    return StaticAssessment(
        score=score,
        contact_count=contact_count,
        negative_restore_count=negative_restore_count,
        negative_yaw_restore_count=negative_yaw_restore_count,
        mean_full_height_stiffness_npm=mean_full_stiffness,
        min_reduced_height_stiffness_npm=min_reduced_stiffness,
        mean_orthogonal_ratio=mean_orthogonal_ratio,
        direction_stiffness_cv=direction_cv,
        displacement_linearity_r2=mean_r2,
        height_linearity_r2=height_r2,
        mean_translation_torque_ratio=mean_torque_ratio,
        mean_forward_torque_ratio=mean_forward_torque_ratio,
        mean_yaw_stiffness_nmp_rad=mean_yaw_stiffness,
        mean_towed_yaw_stiffness_nmp_rad=mean_towed_yaw_stiffness,
        min_parallel_force_n=min_parallel_force_n,
        min_yaw_restoring_nm=min_yaw_restoring_nm,
        min_towed_yaw_restoring_nm=min_towed_yaw_restoring_nm,
        negative_towed_yaw_restore_count=negative_towed_yaw_restore_count,
        nominal_tow_offset_proxy_m=nominal_tow_offset_proxy_m,
        reduced_tow_offset_proxy_m=reduced_tow_offset_proxy_m,
        stiffness_modulation_ratio=stiffness_modulation_ratio,
        inner_width_m=inner_width_m,
        inner_length_m=inner_length_m,
        outer_width_m=outer_width_m,
        outer_length_m=outer_length_m,
        package_violation_m=package_violation_m,
    )


def static_primary_merit(assessment: StaticAssessment, design: HifiDesign):
    """Returns the main feasible-domain merit optimized by the constrained search."""

    merit = 0.0
    merit += 0.12 * assessment.mean_full_height_stiffness_npm
    merit += 0.10 * assessment.min_reduced_height_stiffness_npm
    merit += 0.18 * assessment.mean_yaw_stiffness_nmp_rad
    merit += 0.24 * assessment.mean_towed_yaw_stiffness_nmp_rad
    merit += 85.0 * assessment.min_yaw_restoring_nm
    merit += 120.0 * assessment.min_towed_yaw_restoring_nm
    merit -= 25.0 * assessment.direction_stiffness_cv
    merit -= 22.0 * (1.0 - assessment.displacement_linearity_r2)
    merit -= 18.0 * (1.0 - assessment.height_linearity_r2)
    merit -= 12.0 * abs(assessment.stiffness_modulation_ratio - 2.0)
    merit -= 0.0012 * design.estimated_total_cost_jpy
    merit -= 0.12 * design.total_magnets
    return float(merit)


def static_constraint_values(assessment: StaticAssessment):
    """Builds explicit inequality constraints g(x) <= 0 for feasible-first optimization."""

    return np.array(
        [
            assessment.package_violation_m,
            assessment.mean_orthogonal_ratio - 0.10,
            assessment.mean_forward_torque_ratio - 0.055,
            assessment.direction_stiffness_cv - 0.25,
            0.92 - assessment.displacement_linearity_r2,
            0.88 - assessment.height_linearity_r2,
            assessment.nominal_tow_offset_proxy_m - 0.008,
            assessment.reduced_tow_offset_proxy_m - 0.020,
            1.20 - assessment.stiffness_modulation_ratio,
            -assessment.min_parallel_force_n,
            -assessment.min_yaw_restoring_nm,
            -assessment.min_towed_yaw_restoring_nm,
            float(assessment.contact_count),
        ],
        dtype=float,
    )


def static_objective_vector(assessment: StaticAssessment, design: HifiDesign):
    """Returns a compact multi-objective signature for Pareto-style archive preservation."""

    return np.array(
        [
            -assessment.mean_full_height_stiffness_npm,
            -assessment.min_reduced_height_stiffness_npm,
            assessment.mean_orthogonal_ratio,
            assessment.mean_forward_torque_ratio,
            assessment.nominal_tow_offset_proxy_m,
            design.estimated_total_cost_jpy / 1000.0,
        ],
        dtype=float,
    )


def structured_candidate_payload(design: HifiDesign, geometry: base.Geometry, model: ArrayModel, assessment: StaticAssessment):
    """Decorates a static design evaluation with explicit constraints and objectives."""

    primary_merit = static_primary_merit(assessment, design)
    constraint_values = static_constraint_values(assessment)
    constraint_violation = float(np.sum(np.maximum(constraint_values, 0.0)))
    is_feasible = bool(np.all(constraint_values <= 0.0))
    objective_vector = static_objective_vector(assessment, design)
    score = primary_merit - 1.0e6 * constraint_violation
    return {
        "score": float(score),
        "primary_merit": float(primary_merit),
        "constraint_values": constraint_values,
        "constraint_violation": constraint_violation,
        "is_feasible": is_feasible,
        "objective_vector": objective_vector,
        "design": design,
        "geometry": geometry,
        "model": model,
        "static_assessment": assessment,
    }


def candidate_priority_key(candidate):
    """Returns a feasible-first ranking key aligned with constrained search practice."""

    if candidate["is_feasible"]:
        return (
            0,
            -float(candidate["primary_merit"]),
            float(candidate["static_assessment"].mean_orthogonal_ratio),
            float(candidate["static_assessment"].mean_forward_torque_ratio),
            float(candidate["design"].estimated_total_cost_jpy),
        )
    return (
        1,
        float(candidate["constraint_violation"]),
        -float(candidate["primary_merit"]),
        float(candidate["static_assessment"].mean_orthogonal_ratio),
        float(candidate["design"].estimated_total_cost_jpy),
    )


def archive_payload_priority_key(payload):
    """Returns the feasible-first ranking key for archived candidate payloads."""

    if payload.get("is_feasible", False):
        return (
            0,
            -float(payload["primary_merit"]),
            float(payload.get("mean_orthogonal_ratio", math.inf)),
            float(payload.get("mean_forward_torque_ratio", math.inf)),
            float(payload.get("estimated_total_cost_jpy", math.inf)),
        )
    return (
        1,
        float(payload.get("constraint_violation", math.inf)),
        -float(payload.get("primary_merit", -math.inf)),
        float(payload.get("mean_orthogonal_ratio", math.inf)),
        float(payload.get("estimated_total_cost_jpy", math.inf)),
    )


def candidate_is_better(lhs, rhs):
    """Returns True when lhs should outrank rhs under feasible-first comparison."""

    if rhs is None:
        return True
    return candidate_priority_key(lhs) < candidate_priority_key(rhs)


def pareto_dominates(lhs_objectives, rhs_objectives):
    """Returns True if lhs weakly dominates rhs in the minimization objective vector."""

    lhs = np.asarray(lhs_objectives, dtype=float)
    rhs = np.asarray(rhs_objectives, dtype=float)
    return bool(np.all(lhs <= rhs) and np.any(lhs < rhs))


def update_pareto_archive(pareto_archive, candidates, archive_limit):
    """Maintains a bounded Pareto archive over feasible candidates only."""

    for candidate in candidates:
        if not candidate.get("is_feasible", False):
            continue
        signature = latent_signature(candidate["latent_vector"])
        candidate_payload = {
            "signature": signature,
            "latent_vector": np.asarray(candidate["latent_vector"], dtype=float).copy(),
            "objective_vector": np.asarray(candidate["objective_vector"], dtype=float).copy(),
            "primary_merit": float(candidate["primary_merit"]),
            "score": float(candidate["score"]),
            "shape_family": candidate["design"].shape_parameters.family,
            "gap_m": float(candidate["design"].gap_m),
            "mean_radius_m": float(candidate["design"].mean_radius_m),
            "magnets_per_ring": int(candidate["design"].magnets_per_ring),
            "magnet_layers": int(candidate["design"].magnet_layers),
            "estimated_total_cost_jpy": float(candidate["design"].estimated_total_cost_jpy),
            "mean_orthogonal_ratio": float(candidate["static_assessment"].mean_orthogonal_ratio),
            "mean_forward_torque_ratio": float(candidate["static_assessment"].mean_forward_torque_ratio),
            "nominal_tow_offset_proxy_m": float(candidate["static_assessment"].nominal_tow_offset_proxy_m),
            "reduced_tow_offset_proxy_m": float(candidate["static_assessment"].reduced_tow_offset_proxy_m),
            "stiffness_modulation_ratio": float(candidate["static_assessment"].stiffness_modulation_ratio),
            "pareto_kept": True,
        }
        survivors = []
        is_dominated = False
        duplicate_replaced = False
        for existing in pareto_archive:
            if existing["signature"] == signature:
                duplicate_replaced = True
                if pareto_dominates(existing["objective_vector"], candidate_payload["objective_vector"]):
                    candidate_payload = existing
                continue
            if pareto_dominates(existing["objective_vector"], candidate_payload["objective_vector"]):
                is_dominated = True
            if not pareto_dominates(candidate_payload["objective_vector"], existing["objective_vector"]):
                survivors.append(existing)
        if is_dominated and not duplicate_replaced:
            continue
        survivors.append(candidate_payload)
        survivors.sort(
            key=lambda row: (
                -float(row["primary_merit"]),
                float(row["mean_orthogonal_ratio"]),
                float(row["mean_forward_torque_ratio"]),
                float(row["estimated_total_cost_jpy"]),
            )
        )
        pareto_archive[:] = survivors[:archive_limit]


def evaluate_design_candidate(
    latent_vector,
    num_samples,
    dipole_grid,
    catalog=None,
    fixed_cart_mass_kg=None,
    shape_family_mode="both",
):
    """Evaluates one design candidate with the static high-fidelity objective."""

    design, geometry = build_design_from_latent(
        latent_vector,
        num_samples,
        catalog=catalog,
        fixed_cart_mass_kg=fixed_cart_mass_kg,
        shape_family_mode=shape_family_mode,
    )
    model = build_array_model(design, geometry, dipole_grid)
    assessment = assess_static_design(
        model,
        directions=np.linspace(0.0, 2.0 * math.pi, 12, endpoint=False),
        displacements_m=SEARCH_DISPLACEMENTS_M,
        height_fractions=SEARCH_HEIGHT_FRACTIONS,
        yaw_samples_rad=SEARCH_YAW_RAD,
    )
    return structured_candidate_payload(design, geometry, model, assessment)


def evaluate_design_candidate_quick(
    latent_vector,
    num_samples,
    catalog=None,
    fixed_cart_mass_kg=None,
    shape_family_mode="flex",
):
    """Fast coarse screen used to seed very large searches before full static scoring."""

    design, geometry = build_design_from_latent(
        latent_vector,
        num_samples,
        catalog=catalog,
        fixed_cart_mass_kg=fixed_cart_mass_kg,
        shape_family_mode=shape_family_mode,
    )
    model = build_array_model(design, geometry, SEARCH_DIPOLE_GRID)
    assessment = assess_static_design(
        model,
        directions=np.linspace(0.0, 2.0 * math.pi, 8, endpoint=False),
        displacements_m=COARSE_PRESEARCH_DISPLACEMENTS_M,
        height_fractions=COARSE_PRESEARCH_HEIGHT_FRACTIONS,
        yaw_samples_rad=COARSE_PRESEARCH_YAW_RAD,
    )
    return structured_candidate_payload(design, geometry, model, assessment)


def evaluate_design_candidate_validation(
    latent_vector,
    num_samples,
    catalog=None,
    fixed_cart_mass_kg=None,
    shape_family_mode="flex",
):
    """Runs the full high-resolution static validation objective on one latent design."""

    design, geometry = build_design_from_latent(
        latent_vector,
        num_samples,
        catalog=catalog,
        fixed_cart_mass_kg=fixed_cart_mass_kg,
        shape_family_mode=shape_family_mode,
    )
    model = build_array_model(design, geometry, VALIDATION_DIPOLE_GRID)
    assessment = assess_static_design(
        model,
        directions=np.linspace(0.0, 2.0 * math.pi, 16, endpoint=False),
        displacements_m=VALIDATION_DISPLACEMENTS_M,
        height_fractions=np.linspace(0.0, 0.95, 6),
        yaw_samples_rad=VALIDATION_YAW_RAD,
    )
    return structured_candidate_payload(design, geometry, model, assessment)


def latent_signature(latent_vector):
    """Builds a stable hash for deduplicating searched latent vectors."""

    latent = np.asarray(latent_vector, dtype=float)
    rounded = np.round(latent, 6)
    return hashlib.md5(rounded.tobytes()).hexdigest()


def update_candidate_archive(archive_map, candidates, archive_limit):
    """Stores a bounded set of unique high-scoring latent candidates across generations."""

    for candidate in candidates:
        signature = latent_signature(candidate["latent_vector"])
        existing = archive_map.get(signature)
        candidate_payload = {
            "latent_vector": np.asarray(candidate["latent_vector"], dtype=float).copy(),
            "score": float(candidate["score"]),
            "primary_merit": float(candidate.get("primary_merit", candidate["score"])),
            "constraint_violation": float(candidate.get("constraint_violation", 0.0)),
            "is_feasible": int(candidate.get("is_feasible", True)),
            "shape_family": candidate["design"].shape_parameters.family,
            "gap_m": float(candidate["design"].gap_m),
            "mean_radius_m": float(candidate["design"].mean_radius_m),
            "magnets_per_ring": int(candidate["design"].magnets_per_ring),
            "magnet_layers": int(candidate["design"].magnet_layers),
            "estimated_total_cost_jpy": float(candidate["design"].estimated_total_cost_jpy),
            "mean_orthogonal_ratio": float(candidate["static_assessment"].mean_orthogonal_ratio),
            "mean_forward_torque_ratio": float(candidate["static_assessment"].mean_forward_torque_ratio),
            "negative_yaw_restore_count": int(candidate["static_assessment"].negative_yaw_restore_count),
            "negative_towed_yaw_restore_count": int(candidate["static_assessment"].negative_towed_yaw_restore_count),
            "nominal_tow_offset_proxy_m": float(candidate["static_assessment"].nominal_tow_offset_proxy_m),
            "reduced_tow_offset_proxy_m": float(candidate["static_assessment"].reduced_tow_offset_proxy_m),
            "stiffness_modulation_ratio": float(candidate["static_assessment"].stiffness_modulation_ratio),
            "pareto_kept": int(candidate.get("pareto_kept", False)),
        }
        if existing is None or archive_payload_priority_key(candidate_payload) < archive_payload_priority_key(existing):
            archive_map[signature] = candidate_payload
    if len(archive_map) > archive_limit:
        ranked_items = sorted(archive_map.items(), key=lambda item: archive_payload_priority_key(item[1]))[:archive_limit]
        archive_map.clear()
        archive_map.update(ranked_items)


def archive_to_dataframe(archive_map):
    """Converts the latent archive into a reportable dataframe."""

    if not archive_map:
        return pd.DataFrame()
    rows = []
    for signature, payload in archive_map.items():
        row = dict(payload)
        row["signature"] = signature
        row["latent_vector"] = json.dumps(payload["latent_vector"].tolist())
        rows.append(row)
    rows.sort(key=archive_payload_priority_key)
    return pd.DataFrame(rows)


def refine_design_archive_validation(
    archive_map,
    num_samples,
    catalog=None,
    fixed_cart_mass_kg=None,
    shape_family_mode="flex",
    seed=0,
    refine_generations=0,
    refine_population=0,
    refine_elite_count=2,
):
    """Re-ranks archived candidates on the validation objective and optionally refines locally."""

    if not archive_map:
        raise ValueError("Candidate archive is empty; cannot run validation refinement.")

    rows = []
    validated_candidates = []
    for signature, payload in sorted(archive_map.items(), key=lambda item: item[1]["score"], reverse=True):
        candidate = evaluate_design_candidate_validation(
            payload["latent_vector"],
            num_samples=num_samples,
            catalog=catalog,
            fixed_cart_mass_kg=fixed_cart_mass_kg,
            shape_family_mode=shape_family_mode,
        )
        candidate["latent_vector"] = np.asarray(payload["latent_vector"], dtype=float).copy()
        candidate["signature"] = signature
        validated_candidates.append(candidate)
        assessment = candidate["static_assessment"]
        rows.append(
            {
                "signature": signature,
                "search_score": float(payload["score"]),
                "search_primary_merit": float(payload.get("primary_merit", payload["score"])),
                "search_constraint_violation": float(payload.get("constraint_violation", 0.0)),
                "search_is_feasible": int(payload.get("is_feasible", 1)),
                "validation_score": float(candidate["score"]),
                "validation_primary_merit": float(candidate.get("primary_merit", candidate["score"])),
                "validation_constraint_violation": float(candidate.get("constraint_violation", 0.0)),
                "validation_is_feasible": int(candidate.get("is_feasible", 1)),
                "shape_family": candidate["design"].shape_parameters.family,
                "gap_m": float(candidate["design"].gap_m),
                "mean_radius_m": float(candidate["design"].mean_radius_m),
                "magnets_per_ring": int(candidate["design"].magnets_per_ring),
                "magnet_layers": int(candidate["design"].magnet_layers),
                "estimated_total_cost_jpy": float(candidate["design"].estimated_total_cost_jpy),
                "mean_orthogonal_ratio": float(assessment.mean_orthogonal_ratio),
                "mean_forward_torque_ratio": float(assessment.mean_forward_torque_ratio),
                "nominal_tow_offset_proxy_mm": 1000.0 * float(assessment.nominal_tow_offset_proxy_m),
                "reduced_tow_offset_proxy_mm": 1000.0 * float(assessment.reduced_tow_offset_proxy_m),
                "stiffness_modulation_ratio": float(assessment.stiffness_modulation_ratio),
                "negative_yaw_restore_count": int(assessment.negative_yaw_restore_count),
                "negative_towed_yaw_restore_count": int(assessment.negative_towed_yaw_restore_count),
                "min_yaw_restoring_nm": float(assessment.min_yaw_restoring_nm),
                "min_towed_yaw_restoring_nm": float(assessment.min_towed_yaw_restoring_nm),
                "package_violation_mm": 1000.0 * float(assessment.package_violation_m),
            }
        )

    validated_candidates.sort(key=candidate_priority_key)
    best_candidate = validated_candidates[0]

    if refine_generations > 0 and refine_population > 0:
        rng = np.random.default_rng(seed)
        dimension = design_variable_count(shape_family_mode)
        mean = np.asarray(best_candidate["latent_vector"], dtype=float).copy()
        std = np.ones(dimension, dtype=float) * 0.22
        for _generation in range(refine_generations):
            latent_population = mean + std * rng.standard_normal((refine_population, dimension))
            latent_population[0] = best_candidate["latent_vector"]
            candidates = []
            for index in range(refine_population):
                candidate = evaluate_design_candidate_validation(
                    latent_population[index],
                    num_samples=num_samples,
                    catalog=catalog,
                    fixed_cart_mass_kg=fixed_cart_mass_kg,
                    shape_family_mode=shape_family_mode,
                )
                candidate["latent_vector"] = np.asarray(latent_population[index], dtype=float).copy()
                candidates.append(candidate)
            candidates.sort(key=candidate_priority_key)
            elites = candidates[: max(1, min(refine_elite_count, len(candidates)))]
            elite_vectors = np.stack([item["latent_vector"] for item in elites], axis=0)
            mean = 0.35 * mean + 0.65 * np.mean(elite_vectors, axis=0)
            std = np.maximum(0.55 * std + 0.45 * np.std(elite_vectors, axis=0), 0.04)
            if candidate_is_better(candidates[0], best_candidate):
                best_candidate = candidates[0]

    return best_candidate, pd.DataFrame(rows)


def optimize_design_cem(
    seed,
    generations,
    population,
    elite_count,
    num_samples,
    fixed_sku_id=None,
    fixed_cart_mass_kg=None,
    shape_family_mode="flex",
    max_evaluations=None,
    min_generations=0,
    stall_generations=4,
    coarse_presearch_trials=0,
    coarse_presearch_samples=48,
    coarse_refine_top_k=4,
    archive_limit=64,
    initial_mean=None,
    initial_std=None,
):
    """Runs the legacy CEM search over the flexible shape and actual-magnet geometry design."""

    rng = np.random.default_rng(seed)
    catalog = resolve_catalog(fixed_sku_id)
    dimension = design_variable_count(shape_family_mode)
    if initial_mean is None:
        mean = np.zeros(dimension, dtype=float)
    else:
        mean = np.asarray(initial_mean, dtype=float).copy()
        if mean.shape != (dimension,):
            raise ValueError(
                f"initial_mean has shape {mean.shape}, but expected {(dimension,)} for mode '{shape_family_mode}'."
            )
    if initial_std is None:
        std = np.ones(dimension, dtype=float) * 1.15
    else:
        std = np.asarray(initial_std, dtype=float).copy()
        if std.shape != (dimension,):
            raise ValueError(
                f"initial_std has shape {std.shape}, but expected {(dimension,)} for mode '{shape_family_mode}'."
            )
        std = np.maximum(std, 0.04)
    history_rows = []
    best_candidate = None
    no_improve = 0
    evaluations_used = 0
    archive_map = {}
    candidate_evaluation_index = 0

    if coarse_presearch_trials > 0:
        coarse_latents = rng.standard_normal((coarse_presearch_trials, dimension))
        coarse_candidates = []
        for index in range(coarse_presearch_trials):
            candidate = evaluate_design_candidate_quick(
                coarse_latents[index],
                num_samples=max(24, int(coarse_presearch_samples)),
                catalog=catalog,
                fixed_cart_mass_kg=fixed_cart_mass_kg,
                shape_family_mode=shape_family_mode,
            )
            candidate["latent_vector"] = coarse_latents[index]
            coarse_candidates.append(candidate)
        coarse_candidates.sort(key=candidate_priority_key)
        seed_count = min(max(2, coarse_refine_top_k), len(coarse_candidates))
        seed_vectors = np.stack([item["latent_vector"] for item in coarse_candidates[:seed_count]], axis=0)
        mean = np.mean(seed_vectors, axis=0)
        std = np.maximum(np.std(seed_vectors, axis=0), 0.30)
        evaluations_used += coarse_presearch_trials
        for index in range(seed_count):
            refined = evaluate_design_candidate(
                coarse_candidates[index]["latent_vector"],
                num_samples=num_samples,
                dipole_grid=SEARCH_DIPOLE_GRID,
                catalog=catalog,
                fixed_cart_mass_kg=fixed_cart_mass_kg,
                shape_family_mode=shape_family_mode,
            )
            refined["latent_vector"] = coarse_candidates[index]["latent_vector"]
            if candidate_is_better(refined, best_candidate):
                best_candidate = refined
            update_candidate_archive(archive_map, [refined], archive_limit)
        evaluations_used += seed_count

    generation = 0
    while True:
        latent_population = mean + std * rng.standard_normal((population, dimension))
        candidates = []
        for index in range(population):
            candidate = evaluate_design_candidate(
                latent_population[index],
                num_samples=num_samples,
                dipole_grid=SEARCH_DIPOLE_GRID,
                catalog=catalog,
                fixed_cart_mass_kg=fixed_cart_mass_kg,
                shape_family_mode=shape_family_mode,
            )
            candidate["latent_vector"] = latent_population[index]
            candidates.append(candidate)
        evaluations_used += population
        population_candidates = list(candidates)

        candidates.sort(key=candidate_priority_key)
        elites = candidates[:elite_count]
        update_candidate_archive(archive_map, elites, archive_limit)
        elite_vectors = np.stack([item["latent_vector"] for item in elites], axis=0)
        mean = 0.28 * mean + 0.72 * np.mean(elite_vectors, axis=0)
        std = 0.36 * std + 0.64 * np.std(elite_vectors, axis=0)
        std = np.maximum(std, 0.08)

        generation_best = candidates[0]
        if candidate_is_better(generation_best, best_candidate):
            best_candidate = generation_best
            no_improve = 0
        else:
            no_improve += 1

        assessment = generation_best["static_assessment"]
        feasible_rate = float(np.mean([float(item["is_feasible"]) for item in population_candidates]))
        mean_constraint_violation = float(
            np.mean([float(item["constraint_violation"]) for item in population_candidates])
        )
        history_rows.append(
            {
                "generation": generation,
                "best_score": generation_best["score"],
                "mean_score": float(np.mean([item["score"] for item in population_candidates])),
                "global_best_score": best_candidate["score"],
                "evaluations_used": evaluations_used,
                "optimizer": "cem",
                "sigma": float(np.mean(std)),
                "feasible_rate": feasible_rate,
                "mean_constraint_violation": mean_constraint_violation,
                "shape_family": generation_best["design"].shape_parameters.family,
                "gap_m": generation_best["design"].gap_m,
                "mean_radius_m": generation_best["design"].mean_radius_m,
                "magnet_sku_id": generation_best["design"].magnet_sku_id,
                "magnets_per_ring": generation_best["design"].magnets_per_ring,
                "magnet_layers": generation_best["design"].magnet_layers,
                "coverage_ratio": generation_best["design"].coverage_ratio,
                "max_overlap_reduction_m": generation_best["design"].max_overlap_reduction_m,
                "estimated_total_cost_jpy": generation_best["design"].estimated_total_cost_jpy,
                "mean_full_height_stiffness_npm": assessment.mean_full_height_stiffness_npm,
                "min_reduced_height_stiffness_npm": assessment.min_reduced_height_stiffness_npm,
                "mean_orthogonal_ratio": assessment.mean_orthogonal_ratio,
                "direction_stiffness_cv": assessment.direction_stiffness_cv,
                "displacement_linearity_r2": assessment.displacement_linearity_r2,
                "mean_forward_torque_ratio": assessment.mean_forward_torque_ratio,
                "negative_yaw_restore_count": assessment.negative_yaw_restore_count,
                "negative_towed_yaw_restore_count": assessment.negative_towed_yaw_restore_count,
                "package_violation_mm": 1000.0 * assessment.package_violation_m,
                "nominal_tow_offset_proxy_mm": 1000.0 * assessment.nominal_tow_offset_proxy_m,
                "reduced_tow_offset_proxy_mm": 1000.0 * assessment.reduced_tow_offset_proxy_m,
                "stiffness_modulation_ratio": assessment.stiffness_modulation_ratio,
                "is_feasible": int(generation_best["is_feasible"]),
                "primary_merit": generation_best["primary_merit"],
            }
        )
        generation_rank_by_id = {id(candidate): rank for rank, candidate in enumerate(candidates, start=1)}
        candidate_rows = []
        for candidate_index, candidate in enumerate(population_candidates):
            candidate_evaluation_index += 1
            candidate_rows.append(
                design_candidate_trace_row(
                    candidate,
                    optimizer="cem",
                    generation=generation,
                    candidate_index=candidate_index,
                    evaluation_index=candidate_evaluation_index,
                    generation_rank=generation_rank_by_id[id(candidate)],
                    restart_index=-1,
                )
            )
        append_live_history_rows("live_design_candidate_history.csv", candidate_rows)
        publish_live_history_csv("live_design_history.csv", history_rows)
        update_live_monitor_state(
            stage="design_search",
            design_search={
                "optimizer": "cem",
                "generation": int(generation),
                "evaluations_used": int(evaluations_used),
                "sigma": float(np.mean(std)),
                "feasible_rate": feasible_rate,
                "mean_constraint_violation": mean_constraint_violation,
                "best_score": float(generation_best["score"]),
                "global_best_score": float(best_candidate["score"]),
                "shape_family": generation_best["design"].shape_parameters.family,
                "gap_mm": 1000.0 * float(generation_best["design"].gap_m),
                "mean_radius_mm": 1000.0 * float(generation_best["design"].mean_radius_m),
                "magnet_layers": int(generation_best["design"].magnet_layers),
                "magnets_per_ring": int(generation_best["design"].magnets_per_ring),
                "candidate_history_rows": int(candidate_evaluation_index),
            },
        )
        publish_live_candidate_visuals(generation_best, optimizer_label="cem", generation_label=f"gen {generation}")
        generation += 1
        min_generation_gate = max(int(generations), int(min_generations))
        evaluation_budget_reached = max_evaluations is not None and evaluations_used >= int(max_evaluations)
        converged = no_improve >= int(stall_generations) and float(np.mean(std)) < 0.22
        if generation < min_generation_gate:
            continue
        if evaluation_budget_reached or (max_evaluations is None and generation >= int(generations) and converged):
            break
        if max_evaluations is not None and converged and evaluations_used >= max(population, int(0.35 * max_evaluations)):
            break

    return best_candidate, pd.DataFrame(history_rows), archive_to_dataframe(archive_map), archive_map


def optimize_design_cmaes(
    seed,
    generations,
    population,
    elite_count,
    num_samples,
    fixed_sku_id=None,
    fixed_cart_mass_kg=None,
    shape_family_mode="flex",
    max_evaluations=None,
    min_generations=0,
    stall_generations=4,
    coarse_presearch_trials=0,
    coarse_presearch_samples=48,
    coarse_refine_top_k=4,
    archive_limit=64,
    initial_mean=None,
    initial_std=None,
):
    """Runs constrained CMA-ES with feasible-first handling and Pareto archive retention."""

    if cma is None:
        raise ImportError("The 'cma' package is required for optimize_design_cmaes.")

    rng = np.random.default_rng(seed)
    catalog = resolve_catalog(fixed_sku_id)
    dimension = design_variable_count(shape_family_mode)
    if initial_mean is None:
        base_mean = np.zeros(dimension, dtype=float)
    else:
        base_mean = np.asarray(initial_mean, dtype=float).copy()
        if base_mean.shape != (dimension,):
            raise ValueError(
                f"initial_mean has shape {base_mean.shape}, but expected {(dimension,)} for mode '{shape_family_mode}'."
            )
    if initial_std is None:
        sigma0 = 1.05
    else:
        std = np.asarray(initial_std, dtype=float).copy()
        if std.shape != (dimension,):
            raise ValueError(
                f"initial_std has shape {std.shape}, but expected {(dimension,)} for mode '{shape_family_mode}'."
            )
        sigma0 = max(float(np.mean(np.maximum(std, 0.05))), 0.22)

    seed_vectors = [base_mean.copy()]
    if coarse_presearch_trials > 0:
        coarse_latents = rng.standard_normal((coarse_presearch_trials, dimension))
        coarse_candidates = []
        for index in range(coarse_presearch_trials):
            candidate = evaluate_design_candidate_quick(
                coarse_latents[index],
                num_samples=max(24, int(coarse_presearch_samples)),
                catalog=catalog,
                fixed_cart_mass_kg=fixed_cart_mass_kg,
                shape_family_mode=shape_family_mode,
            )
            candidate["latent_vector"] = np.asarray(coarse_latents[index], dtype=float).copy()
            coarse_candidates.append(candidate)
        coarse_candidates.sort(key=candidate_priority_key)
        for candidate in coarse_candidates[: min(max(2, coarse_refine_top_k), len(coarse_candidates))]:
            seed_vectors.append(np.asarray(candidate["latent_vector"], dtype=float).copy())
    if len(seed_vectors) == 1:
        seed_vectors.append(base_mean + 0.45 * rng.standard_normal(dimension))
        seed_vectors.append(base_mean + 0.90 * rng.standard_normal(dimension))

    evaluation_cache = {}
    archive_map = {}
    pareto_archive = []
    history_rows = []
    best_candidate = None
    base_popsize = max(int(population), 4)
    candidate_evaluation_index = 0
    total_restart_count = max(1, len(seed_vectors))
    if max_evaluations is None:
        effective_budget = base_popsize * max(int(generations), int(min_generations), 4) * sum(
            2**restart_index for restart_index in range(total_restart_count)
        )
    else:
        effective_budget = int(max_evaluations)

    def cached_candidate(latent_vector):
        signature = latent_signature(latent_vector)
        if signature not in evaluation_cache:
            candidate = evaluate_design_candidate(
                latent_vector,
                num_samples=num_samples,
                dipole_grid=SEARCH_DIPOLE_GRID,
                catalog=catalog,
                fixed_cart_mass_kg=fixed_cart_mass_kg,
                shape_family_mode=shape_family_mode,
            )
            candidate["latent_vector"] = np.asarray(latent_vector, dtype=float).copy()
            evaluation_cache[signature] = candidate
        return evaluation_cache[signature]

    def objective_fun(latent_vector):
        return -cached_candidate(latent_vector)["primary_merit"]

    def constraints_fun(latent_vector):
        return cached_candidate(latent_vector)["constraint_values"]

    for restart_index, seed_vector in enumerate(seed_vectors):
        evaluations_used = len(evaluation_cache)
        if evaluations_used >= effective_budget:
            break
        popsize = base_popsize * (2**restart_index)
        remaining_budget = max(effective_budget - evaluations_used, popsize)
        remaining_restarts = max(total_restart_count - restart_index, 1)
        restart_budget = max(popsize * max(int(min_generations), 2), remaining_budget // remaining_restarts)
        maxiter = max(2, int(math.ceil(restart_budget / popsize)))

        cfun = cma.ConstrainedFitnessAL(
            objective_fun,
            constraints_fun,
            dimension=dimension,
            find_feasible_first=True,
        )
        es = cma.CMAEvolutionStrategy(
            seed_vector.tolist(),
            float(sigma0),
            {
                "seed": int(seed + 997 * restart_index),
                "popsize": popsize,
                "maxiter": maxiter,
                "bounds": [[-7.0] * dimension, [7.0] * dimension],
                "verbose": -9,
            },
        )

        restart_best = None
        no_improve = 0
        iteration = 0
        while not es.stop():
            latent_population = es.ask()
            penalized_values = [cfun(latent_vector) for latent_vector in latent_population]
            es.tell(latent_population, penalized_values)
            cfun.update(es)

            candidates = [cached_candidate(latent_vector) for latent_vector in latent_population]
            population_candidates = list(candidates)
            for candidate in candidates:
                candidate["pareto_kept"] = False
            update_candidate_archive(archive_map, candidates, archive_limit)
            update_pareto_archive(pareto_archive, candidates, archive_limit)

            candidates.sort(key=candidate_priority_key)
            generation_best = candidates[0]
            if candidate_is_better(generation_best, best_candidate):
                best_candidate = generation_best
                no_improve = 0
            else:
                no_improve += 1
            if candidate_is_better(generation_best, restart_best):
                restart_best = generation_best
                no_improve = 0

            assessment = generation_best["static_assessment"]
            evaluations_used = len(evaluation_cache)
            feasible_rate = float(np.mean([float(item["is_feasible"]) for item in population_candidates]))
            mean_constraint_violation = float(
                np.mean([float(item["constraint_violation"]) for item in population_candidates])
            )
            history_rows.append(
                {
                    "generation": len(history_rows),
                    "restart_index": restart_index,
                    "optimizer": "cmaes",
                    "best_score": generation_best["score"],
                    "mean_score": float(np.mean([item["score"] for item in population_candidates])),
                    "global_best_score": best_candidate["score"],
                    "evaluations_used": evaluations_used,
                    "sigma": float(es.sigma),
                    "feasible_rate": feasible_rate,
                    "mean_constraint_violation": mean_constraint_violation,
                    "shape_family": generation_best["design"].shape_parameters.family,
                    "gap_m": generation_best["design"].gap_m,
                    "mean_radius_m": generation_best["design"].mean_radius_m,
                    "magnet_sku_id": generation_best["design"].magnet_sku_id,
                    "magnets_per_ring": generation_best["design"].magnets_per_ring,
                    "magnet_layers": generation_best["design"].magnet_layers,
                    "coverage_ratio": generation_best["design"].coverage_ratio,
                    "max_overlap_reduction_m": generation_best["design"].max_overlap_reduction_m,
                    "estimated_total_cost_jpy": generation_best["design"].estimated_total_cost_jpy,
                    "mean_full_height_stiffness_npm": assessment.mean_full_height_stiffness_npm,
                    "min_reduced_height_stiffness_npm": assessment.min_reduced_height_stiffness_npm,
                    "mean_orthogonal_ratio": assessment.mean_orthogonal_ratio,
                    "direction_stiffness_cv": assessment.direction_stiffness_cv,
                    "displacement_linearity_r2": assessment.displacement_linearity_r2,
                    "mean_forward_torque_ratio": assessment.mean_forward_torque_ratio,
                    "negative_yaw_restore_count": assessment.negative_yaw_restore_count,
                    "negative_towed_yaw_restore_count": assessment.negative_towed_yaw_restore_count,
                    "package_violation_mm": 1000.0 * assessment.package_violation_m,
                    "nominal_tow_offset_proxy_mm": 1000.0 * assessment.nominal_tow_offset_proxy_m,
                    "reduced_tow_offset_proxy_mm": 1000.0 * assessment.reduced_tow_offset_proxy_m,
                    "stiffness_modulation_ratio": assessment.stiffness_modulation_ratio,
                    "is_feasible": int(generation_best["is_feasible"]),
                    "primary_merit": generation_best["primary_merit"],
                }
            )
            generation_rank_by_id = {id(candidate): rank for rank, candidate in enumerate(candidates, start=1)}
            candidate_rows = []
            for candidate_index, candidate in enumerate(population_candidates):
                candidate_evaluation_index += 1
                candidate_rows.append(
                    design_candidate_trace_row(
                        candidate,
                        optimizer="cmaes",
                        generation=len(history_rows) - 1,
                        candidate_index=candidate_index,
                        evaluation_index=candidate_evaluation_index,
                        generation_rank=generation_rank_by_id[id(candidate)],
                        restart_index=restart_index,
                    )
                )
            append_live_history_rows("live_design_candidate_history.csv", candidate_rows)
            publish_live_history_csv("live_design_history.csv", history_rows)
            update_live_monitor_state(
                stage="design_search",
                design_search={
                    "optimizer": "cmaes",
                    "restart_index": int(restart_index),
                    "generation": int(len(history_rows) - 1),
                    "evaluations_used": int(evaluations_used),
                    "sigma": float(es.sigma),
                    "feasible_rate": feasible_rate,
                    "mean_constraint_violation": mean_constraint_violation,
                    "best_score": float(generation_best["score"]),
                    "global_best_score": float(best_candidate["score"]),
                    "shape_family": generation_best["design"].shape_parameters.family,
                    "gap_mm": 1000.0 * float(generation_best["design"].gap_m),
                    "mean_radius_mm": 1000.0 * float(generation_best["design"].mean_radius_m),
                    "magnet_layers": int(generation_best["design"].magnet_layers),
                    "magnets_per_ring": int(generation_best["design"].magnets_per_ring),
                    "candidate_history_rows": int(candidate_evaluation_index),
                },
            )
            publish_live_candidate_visuals(
                generation_best,
                optimizer_label="cmaes",
                generation_label=f"restart {restart_index} / gen {len(history_rows) - 1}",
            )
            iteration += 1
            if evaluations_used >= effective_budget:
                break
            if iteration >= max(int(generations), int(min_generations), 2):
                if no_improve >= int(stall_generations) and float(es.sigma) < 0.28:
                    break

    for pareto_row in pareto_archive:
        signature = pareto_row["signature"]
        archive_map[signature] = {
            **archive_map.get(signature, {}),
            **pareto_row,
            "pareto_kept": 1,
        }

    return best_candidate, pd.DataFrame(history_rows), archive_to_dataframe(archive_map), archive_map


def optimize_design(
    seed,
    generations,
    population,
    elite_count,
    num_samples,
    fixed_sku_id=None,
    fixed_cart_mass_kg=None,
    shape_family_mode="flex",
    max_evaluations=None,
    min_generations=0,
    stall_generations=4,
    coarse_presearch_trials=0,
    coarse_presearch_samples=48,
    coarse_refine_top_k=4,
    archive_limit=64,
    initial_mean=None,
    initial_std=None,
    design_optimizer="cmaes",
):
    """Dispatches between the legacy CEM and the redesigned constrained CMA-ES search."""

    if design_optimizer == "cem":
        return optimize_design_cem(
            seed=seed,
            generations=generations,
            population=population,
            elite_count=elite_count,
            num_samples=num_samples,
            fixed_sku_id=fixed_sku_id,
            fixed_cart_mass_kg=fixed_cart_mass_kg,
            shape_family_mode=shape_family_mode,
            max_evaluations=max_evaluations,
            min_generations=min_generations,
            stall_generations=stall_generations,
            coarse_presearch_trials=coarse_presearch_trials,
            coarse_presearch_samples=coarse_presearch_samples,
            coarse_refine_top_k=coarse_refine_top_k,
            archive_limit=archive_limit,
            initial_mean=initial_mean,
            initial_std=initial_std,
        )
    return optimize_design_cmaes(
        seed=seed,
        generations=generations,
        population=population,
        elite_count=elite_count,
        num_samples=num_samples,
        fixed_sku_id=fixed_sku_id,
        fixed_cart_mass_kg=fixed_cart_mass_kg,
        shape_family_mode=shape_family_mode,
        max_evaluations=max_evaluations,
        min_generations=min_generations,
        stall_generations=stall_generations,
        coarse_presearch_trials=coarse_presearch_trials,
        coarse_presearch_samples=coarse_presearch_samples,
        coarse_refine_top_k=coarse_refine_top_k,
        archive_limit=archive_limit,
        initial_mean=initial_mean,
        initial_std=initial_std,
    )


def build_policy_from_latent(latent_vector):
    """Materializes a height-control policy from its latent parameter vector."""

    bounded = base.sigmoid(latent_vector)
    return HeightPolicy(
        bias=signed(-3.8, 1.2, bounded[0]),
        weight_torque=signed(0.4, 6.4, bounded[1]),
        weight_force=signed(-3.2, 1.0, bounded[2]),
        weight_yaw=signed(0.2, 4.2, bounded[3]),
        weight_yaw_rate=signed(0.1, 3.2, bounded[4]),
        weight_gap_margin=signed(0.6, 5.8, bounded[5]),
        weight_translation=signed(-2.8, 1.8, bounded[6]),
        weight_speed=signed(-0.8, 2.4, bounded[7]),
    )


def build_operator_intent_scenario(kind: str, seed: int, dt_s: float):
    """Builds low-force human cue scenarios while the robot cruises at 0.45 m/s."""

    rng = np.random.default_rng(seed)
    duration_s = 6.0
    steps = int(round(duration_s / dt_s))
    force_world = np.zeros((steps, 2), dtype=float)
    torque_nm = np.zeros(steps, dtype=float)
    phase = np.zeros(steps, dtype=int)

    heading = rng.uniform(-0.08, 0.08)
    forward_dir = np.array([math.sin(heading), math.cos(heading)], dtype=float)
    side_dir = np.array([-forward_dir[1], forward_dir[0]], dtype=float)
    cue_force = rng.uniform(*HUMAN_CUE_FORCE_RANGE_N)
    cue_torque = rng.uniform(*HUMAN_CUE_TORQUE_RANGE_NM)
    torque_sign = rng.choice([-1.0, 1.0])
    side_sign = rng.choice([-1.0, 1.0])
    nuisance_forward = rng.uniform(0.0, 1.8)
    nuisance_side = rng.uniform(0.0, 1.2)

    def fill_segment(start_s, end_s, force_xy, torque_value, phase_value):
        start_i = int(round(start_s / dt_s))
        end_i = min(steps, int(round(end_s / dt_s)))
        force_world[start_i:end_i] = force_xy
        torque_nm[start_i:end_i] = torque_value
        phase[start_i:end_i] = phase_value

    if kind == "steady_cruise":
        fill_segment(0.5, 4.9, nuisance_forward * forward_dir + 0.35 * nuisance_side * side_dir, 0.0, 0)
    elif kind == "gentle_turn_cue":
        fill_segment(0.6, 1.2, 0.25 * nuisance_forward * forward_dir, 0.0, 0)
        fill_segment(
            1.3,
            2.1,
            0.30 * nuisance_forward * forward_dir + side_sign * 0.55 * cue_force * side_dir,
            torque_sign * 0.55 * cue_torque,
            1,
        )
        fill_segment(
            2.1,
            2.8,
            0.22 * nuisance_forward * forward_dir + side_sign * 0.38 * cue_force * side_dir,
            torque_sign * 0.30 * cue_torque,
            1,
        )
        fill_segment(2.9, 5.0, 0.0 * forward_dir, 0.0, 3)
    elif kind == "decisive_turn_cue":
        fill_segment(0.6, 1.0, 0.25 * nuisance_forward * forward_dir, 0.0, 0)
        fill_segment(
            1.1,
            2.0,
            0.42 * nuisance_forward * forward_dir + side_sign * 0.95 * cue_force * side_dir,
            torque_sign * cue_torque,
            2,
        )
        fill_segment(
            2.0,
            2.6,
            0.20 * nuisance_forward * forward_dir + side_sign * 0.62 * cue_force * side_dir,
            torque_sign * 0.48 * cue_torque,
            2,
        )
        fill_segment(2.8, 5.0, 0.0 * forward_dir, 0.0, 3)
    elif kind == "lane_change_cue":
        fill_segment(0.7, 1.4, side_sign * 0.72 * cue_force * side_dir, torque_sign * 0.28 * cue_torque, 1)
        fill_segment(1.7, 2.4, -side_sign * 0.55 * cue_force * side_dir, -torque_sign * 0.24 * cue_torque, 1)
        fill_segment(2.6, 4.8, 0.0 * forward_dir, 0.0, 3)
    elif kind == "recenter_after_cue":
        fill_segment(
            0.8,
            2.2,
            0.18 * nuisance_forward * forward_dir + side_sign * 0.78 * cue_force * side_dir,
            torque_sign * 0.82 * cue_torque,
            2,
        )
        fill_segment(2.3, 5.1, 0.0 * forward_dir, 0.0, 3)
    elif kind == "contact_challenge":
        fill_segment(0.7, 1.1, 0.35 * nuisance_forward * forward_dir, 0.0, 0)
        fill_segment(
            1.2,
            2.6,
            0.55 * nuisance_forward * forward_dir + side_sign * 1.18 * cue_force * side_dir,
            torque_sign * 1.10 * cue_torque,
            2,
        )
        fill_segment(
            2.7,
            3.3,
            0.10 * nuisance_forward * forward_dir + side_sign * 0.90 * cue_force * side_dir,
            torque_sign * 0.55 * cue_torque,
            2,
        )
        fill_segment(3.5, 5.2, 0.0 * forward_dir, 0.0, 3)
    else:
        raise ValueError(f"Unsupported hifi scenario kind: {kind}")

    return base.Scenario(
        name=f"{kind}_{seed}",
        dt_s=dt_s,
        force_world_n=force_world,
        torque_nm=torque_nm,
        phase=phase,
    )


def cart_inertia_kgm2(mass_kg):
    """Approximates the cart yaw inertia from a rectangular footprint."""

    return mass_kg * (CART_LENGTH_M**2 + CART_WIDTH_M**2) / 12.0


def robot_inertia_kgm2():
    """Approximates the robot yaw inertia from a rectangular footprint."""

    return ROBOT_MASS_KG * (ROBOT_LENGTH_M**2 + ROBOT_WIDTH_M**2) / 12.0


def filter_training_scenarios(seed, dt_s):
    """Builds training scenarios for user steering cues while the robot supplies propulsion."""

    scenario_plan = [
        ("steady_cruise", 11),
        ("gentle_turn_cue", 29),
        ("decisive_turn_cue", 47),
        ("lane_change_cue", 61),
        ("recenter_after_cue", 79),
        ("contact_challenge", 97),
    ]
    return [build_operator_intent_scenario(name, seed + offset, dt_s) for name, offset in scenario_plan]


def filter_validation_scenarios(seed, dt_s):
    """Builds held-out validation scenarios for cruise, cue, release, and near-contact cases."""

    scenario_plan = [
        ("steady_cruise", 211),
        ("gentle_turn_cue", 227),
        ("decisive_turn_cue", 241),
        ("lane_change_cue", 257),
        ("recenter_after_cue", 271),
        ("contact_challenge", 293),
    ]
    return [build_operator_intent_scenario(name, seed + offset, dt_s) for name, offset in scenario_plan]


def nominal_episode_environment():
    """Returns the nominal assembly and dynamics environment."""

    return EpisodeEnvironment(
        magnetic_scale=1.0,
        cart_damping_scale=1.0,
        robot_damping_scale=1.0,
        follow_force_scale=1.0,
        follow_torque_scale=1.0,
        height_tau_scale=1.0,
        height_rate_scale=1.0,
        contact_stiffness_scale=1.0,
        contact_damping_scale=1.0,
        cart_mass_scale=1.0,
        rolling_resistance_scale=1.0,
        swivel_resistance_scale=1.0,
        assembly_translation_bias_body_m=np.zeros(2, dtype=float),
        assembly_yaw_bias_rad=0.0,
        label="nominal",
    )


def sample_episode_environment(design: HifiDesign, scenario_name: str, seed: int, replica_index: int):
    """Samples one plausible manufacturing and operating perturbation."""

    digest = hashlib.blake2b(
        f"{design.magnet_sku_id}|{scenario_name}|{seed}|{replica_index}".encode("utf-8"),
        digest_size=8,
    ).digest()
    rng = np.random.default_rng(int.from_bytes(digest, "little"))
    is_disk = getattr(base.MAGNET_CATALOG_BY_ID[design.magnet_sku_id], "magnet_shape", "block") == "disk"
    strength_sigma = 0.11 if is_disk else 0.06
    damping_sigma = 0.20 if is_disk else 0.14
    follow_sigma = 0.16 if is_disk else 0.10
    height_sigma = 0.18 if is_disk else 0.10
    contact_sigma = 0.22 if is_disk else 0.15
    translation_sigma_m = 0.00060 if is_disk else 0.00030
    yaw_sigma_rad = math.radians(0.45 if is_disk else 0.20)
    return EpisodeEnvironment(
        magnetic_scale=base.clamp(1.0 + rng.normal(0.0, strength_sigma), 0.72, 1.32),
        cart_damping_scale=base.clamp(1.0 + rng.normal(0.0, damping_sigma), 0.60, 1.55),
        robot_damping_scale=base.clamp(1.0 + rng.normal(0.0, damping_sigma), 0.60, 1.55),
        follow_force_scale=base.clamp(1.0 + rng.normal(0.0, follow_sigma), 0.70, 1.35),
        follow_torque_scale=base.clamp(1.0 + rng.normal(0.0, follow_sigma), 0.70, 1.35),
        height_tau_scale=base.clamp(1.0 + rng.normal(0.0, height_sigma), 0.65, 1.45),
        height_rate_scale=base.clamp(1.0 + rng.normal(0.0, height_sigma), 0.65, 1.45),
        contact_stiffness_scale=base.clamp(1.0 + rng.normal(0.0, contact_sigma), 0.55, 1.55),
        contact_damping_scale=base.clamp(1.0 + rng.normal(0.0, contact_sigma), 0.55, 1.60),
        cart_mass_scale=base.clamp(1.0 + rng.normal(0.0, 0.18 if is_disk else 0.12), 0.70, 1.45),
        rolling_resistance_scale=base.clamp(1.0 + rng.normal(0.0, 0.22 if is_disk else 0.15), 0.65, 1.55),
        swivel_resistance_scale=base.clamp(1.0 + rng.normal(0.0, 0.25 if is_disk else 0.18), 0.60, 1.65),
        assembly_translation_bias_body_m=rng.normal(0.0, translation_sigma_m, size=2),
        assembly_yaw_bias_rad=float(rng.normal(0.0, yaw_sigma_rad)),
        label=f"perturbed_{replica_index + 1}",
    )


def build_episode_environments(design: HifiDesign, scenario_name: str, seed: int, replica_count: int):
    """Builds nominal plus perturbed environments for robust validation."""

    environments = [nominal_episode_environment()]
    for replica_index in range(max(replica_count - 1, 0)):
        environments.append(sample_episode_environment(design, scenario_name, seed, replica_index))
    return environments


def apply_environment_pose_bias(relative_translation_body_m, relative_yaw_rad, environment: EpisodeEnvironment):
    """Applies fixed assembly offsets before the magnetic/contact evaluation."""

    return (
        relative_translation_body_m + environment.assembly_translation_bias_body_m,
        base.wrap_angle(relative_yaw_rad + environment.assembly_yaw_bias_rad),
    )


def contact_point_velocity(linear_velocity_world, yaw_rate_rad_s, contact_point_world, body_position_world):
    """Returns the world velocity at a rigid body's contact point."""

    radius_world = contact_point_world - body_position_world
    tangential = np.array([-yaw_rate_rad_s * radius_world[1], yaw_rate_rad_s * radius_world[0]], dtype=float)
    return linear_velocity_world + tangential


def follower_and_damping_params(model: ArrayModel, environment: EpisodeEnvironment):
    """Builds physically scaled passive and follow-control parameters."""

    reference_linear_speed_mps = ROBOT_COMMAND_SPEED_MPS
    effective_cart_mass_kg = model.design.cart_mass_kg * environment.cart_mass_scale
    cart_normal_load_n = effective_cart_mass_kg * 9.81
    follow_zeta = 1.05
    follow_linear_wn_rad_s = 4.2
    follow_yaw_wn_rad_s = 4.8
    base_height_tau_s = 0.20
    base_height_rate_limit_mps = 0.10

    cart_longitudinal_damping = environment.cart_damping_scale * 0.22 * cart_normal_load_n / reference_linear_speed_mps
    cart_lateral_damping = CART_LATERAL_DAMPING_RATIO * cart_longitudinal_damping
    robot_linear_damping = (
        environment.robot_damping_scale * 0.030 * ROBOT_MASS_KG * 9.81 / reference_linear_speed_mps
    )
    cart_yaw_damping = environment.cart_damping_scale * cart_longitudinal_damping * (
        (CART_LENGTH_M**2 + CART_WIDTH_M**2) / 12.0
    )
    robot_yaw_damping = environment.robot_damping_scale * robot_linear_damping * (
        (ROBOT_LENGTH_M**2 + ROBOT_WIDTH_M**2) / 12.0
    )
    caster_align_gain = (
        environment.cart_damping_scale
        * CART_ALIGN_GAIN_SCALE
        * model.design.cart_mass_kg
        * 9.81
        * CART_CASTER_TRAIL_M
    )
    caster_align_damping = CART_ALIGN_DAMPING_SCALE * cart_yaw_damping
    tow_align_gain = (
        environment.cart_damping_scale
        * CART_TOW_ALIGN_GAIN_SCALE
        * model.design.cart_mass_kg
        * 9.81
        * CART_CASTER_TRAIL_M
    )
    tow_align_damping = CART_TOW_ALIGN_DAMPING_SCALE * cart_yaw_damping
    robot_inertia = robot_inertia_kgm2()
    follow_kp_n_m = environment.follow_force_scale * ROBOT_MASS_KG * follow_linear_wn_rad_s**2
    follow_kd_n_s_m = environment.follow_force_scale * 2.0 * follow_zeta * ROBOT_MASS_KG * follow_linear_wn_rad_s
    follow_kp_yaw = environment.follow_torque_scale * robot_inertia * follow_yaw_wn_rad_s**2
    follow_kd_yaw = environment.follow_torque_scale * 2.0 * follow_zeta * robot_inertia * follow_yaw_wn_rad_s
    follow_force_limit_n = environment.follow_force_scale * 68.0
    follow_torque_limit_nm = environment.follow_torque_scale * 11.5
    cart_sustained_long_force_n = environment.rolling_resistance_scale * CART_SUSTAINED_RESISTANCE_COEFF * cart_normal_load_n
    cart_sustained_lat_force_n = CART_LATERAL_RESISTANCE_RATIO * cart_sustained_long_force_n
    cart_swivel_static_torque_nm = (
        environment.swivel_resistance_scale * CART_SWIVEL_STATIC_FACTOR * cart_normal_load_n * CART_CASTER_TRAIL_M
    )
    return {
        "effective_cart_mass_kg": effective_cart_mass_kg,
        "cart_longitudinal_damping_n_s_m": cart_longitudinal_damping,
        "cart_lateral_damping_n_s_m": cart_lateral_damping,
        "cart_sustained_long_force_n": cart_sustained_long_force_n,
        "cart_sustained_lat_force_n": cart_sustained_lat_force_n,
        "cart_yaw_damping_nms": cart_yaw_damping,
        "caster_align_gain_nm_rad": caster_align_gain,
        "caster_align_damping_nms": caster_align_damping,
        "tow_align_gain_nm_rad": tow_align_gain,
        "tow_align_damping_nms": tow_align_damping,
        "cart_swivel_static_torque_nm": cart_swivel_static_torque_nm,
        "robot_damping_n_s_m": robot_linear_damping,
        "robot_yaw_damping_nms": robot_yaw_damping,
        "follow_kp_n_m": follow_kp_n_m,
        "follow_kd_n_s_m": follow_kd_n_s_m,
        "follow_kp_yaw": follow_kp_yaw,
        "follow_kd_yaw": follow_kd_yaw,
        "follow_force_limit_n": follow_force_limit_n,
        "follow_torque_limit_nm": follow_torque_limit_nm,
        "robot_cruise_accel_gain": ROBOT_CRUISE_ACCEL_GAIN,
        "robot_cruise_force_limit_n": ROBOT_CRUISE_FORCE_LIMIT_N,
        "robot_lateral_hold_gain_n_s_m": ROBOT_LATERAL_HOLD_GAIN_N_S_M,
        "height_tau_s": base_height_tau_s * environment.height_tau_scale,
        "height_rate_limit_mps": base_height_rate_limit_mps * environment.height_rate_scale,
        "contact_stiffness_n_per_m": CONTACT_STIFFNESS_N_PER_M * environment.contact_stiffness_scale,
        "contact_damping_n_s_per_m": CONTACT_DAMPING_N_S_PER_M * environment.contact_damping_scale,
    }


def smooth_coulomb_component(velocity_value, sustained_force_n, start_multiplier, velocity_scale_mps):
    """Approximates starting and rolling resistance with a smooth Coulomb/Stribeck blend."""

    speed = abs(float(velocity_value))
    safe_scale = max(velocity_scale_mps, 1.0e-6)
    direction = math.tanh(float(velocity_value) / safe_scale)
    ratio = speed / safe_scale
    if ratio >= 50.0:
        gain = 1.0
    else:
        gain = 1.0 + (start_multiplier - 1.0) * math.exp(-(ratio * ratio))
    return sustained_force_n * gain * direction


def cart_passive_force_world(velocity_world: np.ndarray, yaw_world_rad: float, dynamics: dict):
    """Returns anisotropic rolling resistance for a caster cart."""

    velocity_body = base.rotmat(-yaw_world_rad) @ velocity_world
    resistance_body = np.array(
        [
            -smooth_coulomb_component(
                velocity_body[0],
                dynamics["cart_sustained_lat_force_n"],
                CART_START_FORCE_MULTIPLIER,
                0.65 * CART_STATIC_RESISTANCE_SPEED_MPS,
            )
            - dynamics["cart_lateral_damping_n_s_m"] * velocity_body[0],
            -smooth_coulomb_component(
                velocity_body[1],
                dynamics["cart_sustained_long_force_n"],
                CART_START_FORCE_MULTIPLIER,
                CART_STATIC_RESISTANCE_SPEED_MPS,
            )
            - dynamics["cart_longitudinal_damping_n_s_m"] * velocity_body[1],
        ],
        dtype=float,
    )
    return base.rotmat(yaw_world_rad) @ resistance_body


def cart_passive_alignment_torque(
    velocity_world: np.ndarray,
    yaw_world_rad: float,
    yaw_rate_rad_s: float,
    dynamics: dict,
    yaw_reference_rad: float | None = None,
    yaw_reference_rate_rad_s: float = 0.0,
):
    """Approximates caster self-alignment from body slip angle and yaw damping."""

    velocity_body = base.rotmat(-yaw_world_rad) @ velocity_world
    slip_angle_rad = base.wrap_angle(math.atan2(velocity_body[0], velocity_body[1] + 0.06))
    torque_nm = (
        -dynamics["caster_align_gain_nm_rad"] * slip_angle_rad
        - dynamics["caster_align_damping_nms"] * yaw_rate_rad_s
        - dynamics["cart_swivel_static_torque_nm"]
        * math.tanh((yaw_rate_rad_s + 0.75 * slip_angle_rad) / CART_SWIVEL_STATIC_RATE_RADPS)
    )
    if yaw_reference_rad is not None:
        torque_nm += (
            -dynamics["tow_align_gain_nm_rad"] * base.wrap_angle(yaw_world_rad - yaw_reference_rad)
            - dynamics["tow_align_damping_nms"] * (yaw_rate_rad_s - yaw_reference_rate_rad_s)
        )
    return torque_nm


def robot_cruise_force_world(velocity_world: np.ndarray, yaw_world_rad: float, dynamics: dict):
    """Applies the robot-side propulsion that maintains 0.45 m/s corridor transport."""

    forward_axis = base.rotmat(yaw_world_rad) @ np.array([0.0, 1.0], dtype=float)
    lateral_axis = base.rotmat(yaw_world_rad) @ np.array([1.0, 0.0], dtype=float)
    forward_speed = float(np.dot(velocity_world, forward_axis))
    lateral_speed = float(np.dot(velocity_world, lateral_axis))
    command_force = (
        forward_axis * (ROBOT_MASS_KG * dynamics["robot_cruise_accel_gain"] * (ROBOT_COMMAND_SPEED_MPS - forward_speed))
        - lateral_axis * (dynamics["robot_lateral_hold_gain_n_s_m"] * lateral_speed)
    )
    return base.clamp_norm(command_force, dynamics["robot_cruise_force_limit_n"])


def project_contact_state(
    coupling: PoseSample,
    yaw_inner: float,
    position_outer: np.ndarray,
    velocity_outer: np.ndarray,
    position_inner: np.ndarray,
    velocity_inner: np.ndarray,
    outer_mass_kg: float,
):
    """Applies a non-penetration position and normal-velocity correction."""

    if coupling.contact_penetration_m <= DYNAMIC_CONTACT_MARGIN_M:
        return
    normal_world = base.rotmat(yaw_inner) @ coupling.contact_normal_body
    normal_world /= np.linalg.norm(normal_world) + 1.0e-12
    inv_outer = 1.0 / max(outer_mass_kg, 1.0e-6)
    inv_inner = 1.0 / max(ROBOT_MASS_KG, 1.0e-6)
    inv_sum = inv_outer + inv_inner
    correction_m = coupling.contact_penetration_m + DYNAMIC_CONTACT_MARGIN_M
    position_outer += normal_world * correction_m * inv_outer / inv_sum
    position_inner -= normal_world * correction_m * inv_inner / inv_sum

    relative_normal_speed = float(np.dot(velocity_outer - velocity_inner, normal_world))
    if relative_normal_speed < 0.0:
        impulse = -relative_normal_speed / inv_sum
        velocity_outer += normal_world * impulse * inv_outer
        velocity_inner -= normal_world * impulse * inv_inner


def settle_nonpenetration(
    model: ArrayModel,
    yaw_outer: float,
    yaw_inner: float,
    height_shift_m: float,
    environment: EpisodeEnvironment,
    position_outer: np.ndarray,
    velocity_outer: np.ndarray,
    position_inner: np.ndarray,
    velocity_inner: np.ndarray,
    outer_mass_kg: float,
    max_iterations: int = 4,
):
    """Projects repeated contact attempts until the physical clearance is nonnegative."""

    residual = None
    coupling = None
    for _iteration in range(max_iterations):
        effective_translation_body_m, effective_yaw_rad = apply_environment_pose_bias(
            base.rotmat(-yaw_inner) @ (position_outer - position_inner),
            base.wrap_angle(yaw_outer - yaw_inner),
            environment,
        )
        coupling = evaluate_pose(model, effective_translation_body_m, effective_yaw_rad, height_shift_m)
        residual = coupling.contact_penetration_m
        if residual <= DYNAMIC_CONTACT_MARGIN_M:
            return coupling, residual, _iteration
        project_contact_state(
            coupling,
            yaw_inner,
            position_outer,
            velocity_outer,
            position_inner,
            velocity_inner,
            outer_mass_kg,
        )
    effective_translation_body_m, effective_yaw_rad = apply_environment_pose_bias(
        base.rotmat(-yaw_inner) @ (position_outer - position_inner),
        base.wrap_angle(yaw_outer - yaw_inner),
        environment,
    )
    coupling = evaluate_pose(model, effective_translation_body_m, effective_yaw_rad, height_shift_m)
    return coupling, coupling.contact_penetration_m, max_iterations


def simulate_dynamic_episode(
    model: ArrayModel,
    policy: HeightPolicy,
    scenario: base.Scenario,
    environment: EpisodeEnvironment | None = None,
    record=False,
    substeps=1,
):
    """Simulates cart motion, overlap control, and contact with robust substepping."""

    environment = environment or nominal_episode_environment()
    dynamics = follower_and_damping_params(model, environment)
    dt_s = scenario.dt_s
    substeps = max(int(substeps), 1)
    sub_dt_s = dt_s / substeps
    steps = scenario.force_world_n.shape[0]
    position_outer = np.zeros(2, dtype=float)
    velocity_outer = np.zeros(2, dtype=float)
    yaw_outer = 0.0
    yaw_rate_outer = 0.0

    position_inner = np.zeros(2, dtype=float)
    velocity_inner = np.zeros(2, dtype=float)
    yaw_inner = 0.0
    yaw_rate_inner = 0.0

    height_shift_m = 0.0
    latched = False
    diverged = False
    contact_events = 0
    constraint_activations = 0
    was_in_contact = False
    min_gap_m = float("inf")
    max_contact_demand_m = 0.0
    contact_duration_s = 0.0
    first_contact_time_s = None
    height_shift_peak_m = 0.0
    input_force_peak_n = float(np.max(np.linalg.norm(scenario.force_world_n, axis=1)))
    input_torque_peak_nm = float(np.max(np.abs(scenario.torque_nm)))
    magnetic_force_peak_n = 0.0
    contact_force_peak_n = 0.0

    rel_translation_samples = []
    rel_yaw_samples = []
    height_shift_samples = []
    phase_samples = []
    sensor_proxy_samples = []

    records = {
        "time_s": [],
        "rel_x_m": [],
        "rel_y_m": [],
        "rel_yaw_rad": [],
        "min_gap_m": [],
        "raw_signed_gap_m": [],
        "height_shift_m": [],
        "input_force_x_n": [],
        "input_force_y_n": [],
        "input_force_mag_n": [],
        "input_torque_nm": [],
        "magnetic_force_mag_n": [],
        "magnetic_torque_mag_nm": [],
        "contact_force_x_n": [],
        "contact_force_y_n": [],
        "contact_force_mag_n": [],
        "contact_outer_torque_nm": [],
        "contact_inner_torque_nm": [],
        "contact_demand_m": [],
        "normal_speed_mps": [],
        "tangential_speed_mps": [],
        "latch_condition_penetration": [],
        "latch_condition_normal_speed": [],
        "latch_condition_tangential_speed": [],
        "constraint_active": [],
        "phase": [],
    } if record else None

    cart_mass_kg = dynamics["effective_cart_mass_kg"]
    cart_inertia = cart_inertia_kgm2(cart_mass_kg)
    robot_inertia = robot_inertia_kgm2()
    yaw_limit_rad = max(model.yaw_contact_limit_rad, 0.08)
    translation_limit_m = max(model.translation_contact_limit_m, 0.004)
    cue_active = scenario.phase > 0
    cue_switch = np.diff(cue_active.astype(int), prepend=0)
    cue_rise_indices = list(np.where(cue_switch == 1)[0])
    cue_fall_indices = list(np.where(cue_switch == -1)[0])
    if cue_active[-1]:
        cue_fall_indices.append(steps - 1)

    target_yaw_deg = min(14.0, max(3.0, 1.4 + 0.65 * input_torque_peak_nm + 0.08 * input_force_peak_n))
    target_yaw_rad = math.radians(target_yaw_deg)
    target_sensor_force_n = min(
        8.0,
        max(SENSOR_TARGET_FORCE_N, SENSOR_MIN_DETECT_FORCE_N + 0.28 * input_torque_peak_nm + 0.05 * input_force_peak_n),
    )
    target_height_shift_m = min(
        max(0.0006, 0.70 * model.design.max_overlap_reduction_m),
        max(
            SENSOR_MIN_OBSERVABLE_HEIGHT_SHIFT_M,
            0.0008 + 0.00022 * input_force_peak_n + 0.00035 * input_torque_peak_nm,
        ),
    )

    for step in range(steps):
        latest_coupling = None
        latest_input_force_world_n = np.array(scenario.force_world_n[step], dtype=float)
        latest_input_torque_nm = float(scenario.torque_nm[step])
        latest_magnetic_force_mag_n = 0.0
        latest_magnetic_torque_mag_nm = 0.0
        latest_contact_force_world_n = np.zeros(2, dtype=float)
        latest_contact_outer_torque_nm = 0.0
        latest_contact_inner_torque_nm = 0.0
        latest_contact_demand_m = 0.0
        latest_normal_speed = 0.0
        latest_tangential_speed = 0.0
        latest_constraint_active = False
        latest_sensor_proxy_n = 0.0

        for substep_index in range(substeps):
            sub_time_s = step * dt_s + substep_index * sub_dt_s
            relative_translation_world_m = position_outer - position_inner
            relative_translation_body_m = base.rotmat(-yaw_inner) @ relative_translation_world_m
            relative_velocity_world = velocity_outer - velocity_inner
            relative_yaw_rad = base.wrap_angle(yaw_outer - yaw_inner)
            relative_yaw_rate = yaw_rate_outer - yaw_rate_inner
            relative_speed = float(np.linalg.norm(relative_velocity_world))
            effective_translation_body_m, effective_yaw_rad = apply_environment_pose_bias(
                relative_translation_body_m,
                relative_yaw_rad,
                environment,
            )

            preview = evaluate_pose(model, effective_translation_body_m, effective_yaw_rad, height_shift_m)
            min_gap_m = min(min_gap_m, preview.min_gap_m)
            max_contact_demand_m = max(max_contact_demand_m, preview.contact_penetration_m)

            features = {
                "torque_intent": base.clamp(abs(scenario.torque_nm[step]) / max(HUMAN_CUE_TORQUE_RANGE_NM[1], 1.0e-6), 0.0, 1.6),
                "force_intent": base.clamp(np.linalg.norm(scenario.force_world_n[step]) / max(HUMAN_CUE_FORCE_RANGE_N[1], 1.0e-6), 0.0, 1.6),
                "yaw_ratio": abs(relative_yaw_rad) / yaw_limit_rad,
                "yaw_rate_ratio": abs(relative_yaw_rate) / 2.8,
                "gap_margin_ratio": preview.min_gap_m / max(model.design.gap_m, 1.0e-4),
                "translation_ratio": np.linalg.norm(relative_translation_body_m) / translation_limit_m,
                "speed_ratio": relative_speed / MAX_LINEAR_SPEED_MPS,
            }
            target_shift_m = policy.target_height_shift(model.design, features)
            shift_error_m = target_shift_m - height_shift_m
            max_change_m = dynamics["height_rate_limit_mps"] * sub_dt_s
            height_shift_m += base.clamp(
                shift_error_m / max(dynamics["height_tau_s"], 1.0e-4) * sub_dt_s,
                -max_change_m,
                max_change_m,
            )
            height_shift_m = base.clamp(height_shift_m, 0.0, model.design.max_overlap_reduction_m)
            height_shift_peak_m = max(height_shift_peak_m, height_shift_m)

            coupling = evaluate_pose(model, effective_translation_body_m, effective_yaw_rad, height_shift_m)
            latest_coupling = coupling
            min_gap_m = min(min_gap_m, coupling.min_gap_m)
            max_contact_demand_m = max(max_contact_demand_m, coupling.contact_penetration_m)

            magnetic_force_world_n = environment.magnetic_scale * (base.rotmat(yaw_inner) @ coupling.force_body_n)
            magnetic_outer_torque_nm = environment.magnetic_scale * coupling.torque_outer_nm
            magnetic_inner_torque_nm = environment.magnetic_scale * coupling.torque_inner_nm
            latest_magnetic_force_mag_n = float(np.linalg.norm(magnetic_force_world_n))
            latest_magnetic_torque_mag_nm = float(abs(magnetic_outer_torque_nm))
            latest_sensor_proxy_n = min(
                latest_magnetic_torque_mag_nm / max(SENSOR_EFFECTIVE_RADIUS_M, 1.0e-6) + 0.5 * latest_magnetic_force_mag_n,
                20.0,
            )
            magnetic_force_peak_n = max(magnetic_force_peak_n, latest_magnetic_force_mag_n)

            contact_force_world_n = np.zeros(2, dtype=float)
            contact_outer_torque_nm = 0.0
            contact_inner_torque_nm = 0.0
            contact_demand_m = coupling.contact_penetration_m
            normal_speed = 0.0
            tangential_speed = 0.0
            constraint_active = False

            if coupling.contact_penetration_m > 0.0:
                constraint_active = True
                normal_world = base.rotmat(yaw_inner) @ coupling.contact_normal_body
                outer_contact_world = position_inner + base.rotmat(yaw_inner) @ coupling.outer_contact_point_body
                inner_contact_world = position_inner + base.rotmat(yaw_inner) @ coupling.inner_contact_point_body
                outer_contact_velocity = contact_point_velocity(
                    velocity_outer,
                    yaw_rate_outer,
                    outer_contact_world,
                    position_outer,
                )
                inner_contact_velocity = contact_point_velocity(
                    velocity_inner,
                    yaw_rate_inner,
                    inner_contact_world,
                    position_inner,
                )
                relative_contact_velocity = outer_contact_velocity - inner_contact_velocity
                normal_speed = float(np.dot(relative_contact_velocity, normal_world))
                tangential_speed = float(np.linalg.norm(relative_contact_velocity - normal_speed * normal_world))
                # Treat collision as a hard-constraint violation handled by projection instead of
                # injecting a large artificial spring force that destabilizes rejected candidates.
                contact_force_world_n = np.zeros(2, dtype=float)
                contact_outer_torque_nm = 0.0
                contact_inner_torque_nm = 0.0

            follow_force_world_n = base.clamp_norm(
                dynamics["follow_kp_n_m"] * (position_outer - position_inner)
                + dynamics["follow_kd_n_s_m"] * (velocity_outer - velocity_inner),
                dynamics["follow_force_limit_n"],
            )
            follow_torque_nm = base.clamp(
                dynamics["follow_kp_yaw"] * base.wrap_angle(yaw_outer - yaw_inner)
                + dynamics["follow_kd_yaw"] * (yaw_rate_outer - yaw_rate_inner),
                -dynamics["follow_torque_limit_nm"],
                dynamics["follow_torque_limit_nm"],
            )
            cruise_force_world_n = robot_cruise_force_world(velocity_inner, yaw_inner, dynamics)
            passive_cart_force_world_n = cart_passive_force_world(velocity_outer, yaw_outer, dynamics)
            passive_cart_align_torque_nm = cart_passive_alignment_torque(
                velocity_outer,
                yaw_outer,
                yaw_rate_outer,
                dynamics,
                yaw_reference_rad=yaw_inner,
                yaw_reference_rate_rad_s=yaw_rate_inner,
            )

            force_outer_world_n = (
                scenario.force_world_n[step]
                + magnetic_force_world_n
                + contact_force_world_n
                + passive_cart_force_world_n
            )
            torque_outer_nm = (
                scenario.torque_nm[step]
                + magnetic_outer_torque_nm
                + contact_outer_torque_nm
                + passive_cart_align_torque_nm
            )
            force_inner_world_n = (
                cruise_force_world_n
                + follow_force_world_n
                - magnetic_force_world_n
                - contact_force_world_n
                - dynamics["robot_damping_n_s_m"] * velocity_inner
            )
            torque_inner_nm = (
                follow_torque_nm
                + magnetic_inner_torque_nm
                + contact_inner_torque_nm
                - dynamics["robot_yaw_damping_nms"] * yaw_rate_inner
            )

            velocity_outer += (force_outer_world_n / cart_mass_kg) * sub_dt_s
            velocity_outer = base.clamp_norm(velocity_outer, MAX_CART_LINEAR_SPEED_MPS)
            position_outer += velocity_outer * sub_dt_s
            yaw_rate_outer += (torque_outer_nm / cart_inertia) * sub_dt_s
            yaw_rate_outer = base.clamp(yaw_rate_outer, -MAX_CART_YAW_RATE_RADPS, MAX_CART_YAW_RATE_RADPS)
            yaw_outer = base.wrap_angle(yaw_outer + yaw_rate_outer * sub_dt_s)

            velocity_inner += (force_inner_world_n / ROBOT_MASS_KG) * sub_dt_s
            velocity_inner = base.clamp_norm(velocity_inner, MAX_ROBOT_DYNAMIC_SPEED_MPS)
            position_inner += velocity_inner * sub_dt_s
            yaw_rate_inner += (torque_inner_nm / robot_inertia) * sub_dt_s
            yaw_rate_inner = base.clamp(
                yaw_rate_inner,
                -MAX_ROBOT_DYNAMIC_YAW_RATE_RADPS,
                MAX_ROBOT_DYNAMIC_YAW_RATE_RADPS,
            )
            yaw_inner = base.wrap_angle(yaw_inner + yaw_rate_inner * sub_dt_s)

            post_coupling, post_residual_m, _projection_iterations = settle_nonpenetration(
                model,
                yaw_outer,
                yaw_inner,
                height_shift_m,
                environment,
                position_outer,
                velocity_outer,
                position_inner,
                velocity_inner,
                cart_mass_kg,
            )
            min_gap_m = min(min_gap_m, post_coupling.min_gap_m)
            max_contact_demand_m = max(max_contact_demand_m, contact_demand_m, post_residual_m)
            latest_coupling = post_coupling
            latest_contact_force_world_n = contact_force_world_n
            latest_contact_outer_torque_nm = float(contact_outer_torque_nm)
            latest_contact_inner_torque_nm = float(contact_inner_torque_nm)
            latest_contact_demand_m = float(max(contact_demand_m, post_residual_m))
            latest_normal_speed = float(normal_speed)
            latest_tangential_speed = float(tangential_speed)
            latest_constraint_active = bool(constraint_active or post_residual_m > DYNAMIC_CONTACT_MARGIN_M)

            if latest_constraint_active:
                if not was_in_contact:
                    contact_events += 1
                    if first_contact_time_s is None:
                        first_contact_time_s = sub_time_s
                constraint_activations += 1
                contact_duration_s += sub_dt_s
            was_in_contact = latest_constraint_active

            if (
                latest_contact_demand_m >= LATCH_PENETRATION_M
                and abs(latest_normal_speed) <= LATCH_REL_SPEED_MPS
                and latest_tangential_speed <= LATCH_TANGENTIAL_SPEED_MPS
            ):
                latched = True
                break
            if post_residual_m > DYNAMIC_CONTACT_MARGIN_M:
                diverged = True
                latched = True
                break

            relative_translation_body_m = base.rotmat(-yaw_inner) @ (position_outer - position_inner)
            relative_yaw_rad = base.wrap_angle(yaw_outer - yaw_inner)
            if (
                np.linalg.norm(relative_translation_body_m) > MAX_RELATIVE_TRANSLATION_M
                or abs(relative_yaw_rad) > MAX_RELATIVE_YAW_RAD
            ):
                diverged = True
                latched = True
                break

        if latched or diverged:
            break

        relative_translation_body_m = base.rotmat(-yaw_inner) @ (position_outer - position_inner)
        relative_yaw_rad = base.wrap_angle(yaw_outer - yaw_inner)
        rel_translation_samples.append(float(np.linalg.norm(relative_translation_body_m)))
        rel_yaw_samples.append(float(relative_yaw_rad))
        height_shift_samples.append(float(height_shift_m))
        phase_samples.append(int(scenario.phase[step]))
        sensor_proxy_samples.append(float(latest_sensor_proxy_n))

        if record and latest_coupling is not None:
            records["time_s"].append((step + 1) * dt_s)
            records["rel_x_m"].append(float(relative_translation_body_m[0]))
            records["rel_y_m"].append(float(relative_translation_body_m[1]))
            records["rel_yaw_rad"].append(float(relative_yaw_rad))
            records["min_gap_m"].append(float(latest_coupling.min_gap_m))
            records["raw_signed_gap_m"].append(float(latest_coupling.raw_signed_gap_m))
            records["height_shift_m"].append(float(height_shift_m))
            records["input_force_x_n"].append(float(latest_input_force_world_n[0]))
            records["input_force_y_n"].append(float(latest_input_force_world_n[1]))
            records["input_force_mag_n"].append(float(np.linalg.norm(latest_input_force_world_n)))
            records["input_torque_nm"].append(float(latest_input_torque_nm))
            records["magnetic_force_mag_n"].append(float(latest_magnetic_force_mag_n))
            records["magnetic_torque_mag_nm"].append(float(latest_magnetic_torque_mag_nm))
            records["contact_force_x_n"].append(float(latest_contact_force_world_n[0]))
            records["contact_force_y_n"].append(float(latest_contact_force_world_n[1]))
            records["contact_force_mag_n"].append(float(np.linalg.norm(latest_contact_force_world_n)))
            records["contact_outer_torque_nm"].append(float(latest_contact_outer_torque_nm))
            records["contact_inner_torque_nm"].append(float(latest_contact_inner_torque_nm))
            records["contact_demand_m"].append(float(latest_contact_demand_m))
            records["normal_speed_mps"].append(float(latest_normal_speed))
            records["tangential_speed_mps"].append(float(latest_tangential_speed))
            records["latch_condition_penetration"].append(int(latest_contact_demand_m >= LATCH_PENETRATION_M))
            records["latch_condition_normal_speed"].append(int(abs(latest_normal_speed) <= LATCH_REL_SPEED_MPS))
            records["latch_condition_tangential_speed"].append(
                int(latest_tangential_speed <= LATCH_TANGENTIAL_SPEED_MPS)
            )
            records["constraint_active"].append(int(latest_constraint_active))
            records["phase"].append(int(scenario.phase[step]))

    rel_translation_array = np.asarray(rel_translation_samples, dtype=float)
    rel_yaw_array = np.asarray(rel_yaw_samples, dtype=float)
    height_shift_array = np.asarray(height_shift_samples, dtype=float)
    phase_array = np.asarray(phase_samples, dtype=int)
    sensor_proxy_array = np.asarray(sensor_proxy_samples, dtype=float)
    sample_count = len(rel_yaw_array)
    translation_rms_m = float(np.sqrt(np.mean(np.square(rel_translation_array)))) if rel_translation_array.size else 0.0
    yaw_rms_rad = float(np.sqrt(np.mean(np.square(rel_yaw_array)))) if rel_yaw_array.size else 0.0
    height_shift_mean_m = float(np.mean(height_shift_array)) if height_shift_array.size else 0.0
    cue_mask = phase_array > 0
    cruise_mask = phase_array == 0
    cue_peak_yaw_deg = 0.0
    cue_peak_translation_mm = 0.0
    cue_height_peak_m = 0.0
    sensor_peak_n = 0.0
    cue_delta_yaw_series = np.zeros_like(rel_yaw_array)
    cue_delta_translation_series = np.zeros_like(rel_translation_array)
    cue_delta_height_series = np.zeros_like(height_shift_array)
    cue_delta_sensor_series = np.zeros_like(sensor_proxy_array)
    if cue_rise_indices:
        aligned_falls = list(cue_fall_indices)
        if len(aligned_falls) < len(cue_rise_indices):
            aligned_falls.extend([sample_count - 1] * (len(cue_rise_indices) - len(aligned_falls)))
        for rise_index, fall_index in zip(cue_rise_indices, aligned_falls):
            if rise_index >= sample_count:
                continue
            stop_index = min(max(fall_index + 1, rise_index + 1), sample_count)
            if stop_index <= rise_index:
                continue
            baseline_start = max(0, rise_index - max(2, int(round(0.30 / dt_s))))
            baseline_stop = max(baseline_start + 1, rise_index)
            baseline_translation_m = float(np.median(rel_translation_array[baseline_start:baseline_stop]))
            baseline_yaw_rad = float(np.median(rel_yaw_array[baseline_start:baseline_stop]))
            baseline_height_m = float(np.median(height_shift_array[baseline_start:baseline_stop]))
            baseline_sensor_n = float(np.median(sensor_proxy_array[baseline_start:baseline_stop]))

            yaw_delta_deg = np.degrees(np.abs(rel_yaw_array[rise_index:stop_index] - baseline_yaw_rad))
            translation_delta_mm = 1000.0 * np.abs(rel_translation_array[rise_index:stop_index] - baseline_translation_m)
            height_delta_m = np.maximum(0.0, height_shift_array[rise_index:stop_index] - baseline_height_m)
            sensor_delta_n = np.maximum(0.0, sensor_proxy_array[rise_index:stop_index] - baseline_sensor_n)

            cue_delta_yaw_series[rise_index:stop_index] = yaw_delta_deg
            cue_delta_translation_series[rise_index:stop_index] = translation_delta_mm
            cue_delta_height_series[rise_index:stop_index] = height_delta_m
            cue_delta_sensor_series[rise_index:stop_index] = sensor_delta_n

            cue_peak_yaw_deg = max(cue_peak_yaw_deg, float(np.max(yaw_delta_deg)))
            cue_peak_translation_mm = max(cue_peak_translation_mm, float(np.max(translation_delta_mm)))
            cue_height_peak_m = max(cue_height_peak_m, float(np.max(height_delta_m)))
            sensor_peak_n = max(sensor_peak_n, float(np.max(sensor_delta_n)))
    cruise_translation_rms_m = (
        float(np.sqrt(np.mean(np.square(rel_translation_array[cruise_mask])))) if np.any(cruise_mask) else translation_rms_m
    )
    cruise_yaw_rms_rad = (
        float(np.sqrt(np.mean(np.square(rel_yaw_array[cruise_mask])))) if np.any(cruise_mask) else yaw_rms_rad
    )
    turn_signal_ratio = cue_peak_yaw_deg / max(target_yaw_deg, 1.0e-6)
    height_signal_ratio = cue_height_peak_m / max(target_height_shift_m, 1.0e-6)
    sensor_signal_ratio = sensor_peak_n / max(target_sensor_force_n, 1.0e-6)

    latency_measurements = []
    for rise_index in cue_rise_indices:
        window_end = min(sample_count, rise_index + int(round(1.6 / dt_s)))
        latency = 1.6
        for idx in range(rise_index, window_end):
            if cue_delta_yaw_series[idx] >= 0.60 * target_yaw_deg:
                latency = (idx - rise_index) * dt_s
                break
        latency_measurements.append(latency)
    turn_latency_s = float(np.mean(latency_measurements)) if latency_measurements else 0.0

    recenter_measurements = []
    height_return_measurements = []
    for fall_index in cue_fall_indices:
        if fall_index >= sample_count:
            continue
        window_end = min(sample_count, fall_index + int(round(1.8 / dt_s)))
        recenter = 1.8
        for idx in range(fall_index, window_end):
            if cue_delta_yaw_series[idx] <= 0.20 * target_yaw_deg:
                recenter = (idx - fall_index) * dt_s
                break
        recenter_measurements.append(recenter)
        height_return = 1.8
        return_threshold_m = max(0.00025, 0.20 * target_height_shift_m)
        for idx in range(fall_index, window_end):
            if cue_delta_height_series[idx] <= return_threshold_m:
                height_return = (idx - fall_index) * dt_s
                break
        height_return_measurements.append(height_return)
    recenter_s = float(np.mean(recenter_measurements)) if recenter_measurements else 0.0
    height_return_s = float(np.mean(height_return_measurements)) if height_return_measurements else 0.0

    cruise_height_mean_m = float(np.mean(height_shift_array[cruise_mask])) if np.any(cruise_mask) else height_shift_mean_m
    cue_translation_target_mm = min(18.0, max(4.0, 1.8 + 1.0 * input_torque_peak_nm + 0.22 * input_force_peak_n))
    turn_signal_quality = math.exp(-((turn_signal_ratio - 1.0) / 0.42) ** 2)
    height_signal_quality = math.exp(-((height_signal_ratio - 1.0) / 0.55) ** 2)
    sensor_signal_quality = math.exp(-((min(sensor_signal_ratio, 1.6) - 1.0) / 0.55) ** 2)
    translation_signal_quality = math.exp(-((cue_peak_translation_mm - cue_translation_target_mm) / 4.0) ** 2)
    score = 0.0
    score += 260.0 * turn_signal_quality
    score += 145.0 * height_signal_quality
    score += 130.0 * sensor_signal_quality
    score += 85.0 * translation_signal_quality
    score -= 165.0 * turn_latency_s
    score -= 72.0 * recenter_s
    score -= 58.0 * height_return_s
    score -= 220.0 * (cruise_translation_rms_m / 0.005) ** 2
    score -= 150.0 * (cruise_yaw_rms_rad / math.radians(1.2)) ** 2
    score -= 42.0 * (cruise_height_mean_m / max(0.00035, 0.08 * target_height_shift_m)) ** 2
    score -= 70.0 * (translation_rms_m / max(0.016, translation_limit_m)) ** 2
    score -= 36.0 * (yaw_rms_rad / max(math.radians(5.0), yaw_limit_rad)) ** 2
    score -= 180.0 * max(0.75 - turn_signal_ratio, 0.0)
    score -= 135.0 * max(0.75 - height_signal_ratio, 0.0)
    score -= 125.0 * max((SENSOR_MIN_DETECT_FORCE_N - sensor_peak_n) / SENSOR_MIN_DETECT_FORCE_N, 0.0)
    score -= 180.0 * max((0.0012 - cue_height_peak_m) / 0.0012, 0.0)
    score -= 120.0 * max((4.0 - cue_peak_translation_mm) / 4.0, 0.0)
    score -= 1450.0 * contact_events
    score -= 95.0 * contact_duration_s
    score -= 4600.0 * float(latched)
    score -= 210000.0 * max_contact_demand_m
    if diverged:
        score -= 2400.0

    return DynamicOutcome(
        score=score,
        contact_events=contact_events,
        constraint_activations=constraint_activations,
        latched=latched,
        min_gap_m=min_gap_m,
        max_contact_demand_m=max_contact_demand_m,
        translation_rms_m=translation_rms_m,
        yaw_rms_rad=yaw_rms_rad,
        turn_signal_ratio=turn_signal_ratio,
        turn_latency_s=turn_latency_s,
        recenter_s=recenter_s,
        height_shift_mean_m=height_shift_mean_m,
        height_shift_peak_m=height_shift_peak_m,
        contact_duration_s=contact_duration_s,
        first_contact_time_s=first_contact_time_s,
        input_force_peak_n=input_force_peak_n,
        input_torque_peak_nm=input_torque_peak_nm,
        magnetic_force_peak_n=magnetic_force_peak_n,
        contact_force_peak_n=contact_force_peak_n,
        cue_peak_yaw_deg=cue_peak_yaw_deg,
        cue_peak_translation_mm=cue_peak_translation_mm,
        sensor_peak_n=sensor_peak_n,
        height_return_s=height_return_s,
        cruise_translation_rms_m=cruise_translation_rms_m,
        cruise_yaw_rms_rad=cruise_yaw_rms_rad,
        scenario_name=scenario.name,
        environment_label=environment.label,
        record=records,
    )


def evaluate_policy_candidate(model: ArrayModel, policy_latent, scenarios, seed, replica_count, substeps):
    """Scores one learned height policy on robust dynamic rollouts."""

    policy = build_policy_from_latent(policy_latent)
    outcomes = []
    for scenario in scenarios:
        for environment in build_episode_environments(model.design, scenario.name, seed, replica_count):
            outcomes.append(
                simulate_dynamic_episode(
                    model,
                    policy,
                    scenario,
                    environment=environment,
                    record=False,
                    substeps=substeps,
                )
            )
    scores = np.array([outcome.score for outcome in outcomes], dtype=float)
    tail_count = max(1, len(scores) // 4)
    tail_mean = float(np.mean(np.sort(scores)[:tail_count]))
    penalties = (
        0.28 * float(np.std(scores))
        + 2200.0 * sum(outcome.latched for outcome in outcomes)
        + 320.0 * sum(outcome.contact_events for outcome in outcomes)
        + 55.0 * sum(outcome.constraint_activations for outcome in outcomes)
        + 90000.0 * sum(outcome.max_contact_demand_m for outcome in outcomes)
    )
    robust_score = 0.72 * float(np.mean(scores)) + 0.28 * tail_mean
    return {
        "score": robust_score - penalties,
        "policy": policy,
        "outcomes": outcomes,
    }


def optimize_policy(
    design: HifiDesign,
    geometry: base.Geometry,
    seed,
    generations,
    population,
    elite_count,
    dt_s,
    replica_count=DYNAMIC_SEARCH_ENV_REPLICAS,
    substeps=DYNAMIC_SEARCH_SUBSTEPS,
):
    """Learns the overlap-height controller after the shape itself is fixed."""

    rng = np.random.default_rng(seed)
    dimension = 8
    mean = np.zeros(dimension, dtype=float)
    std = np.ones(dimension, dtype=float) * 1.2
    training_scenarios = filter_training_scenarios(seed, dt_s)
    model = build_array_model(design, geometry, SEARCH_DIPOLE_GRID)
    history_rows = []
    best_candidate = None
    no_improve = 0
    candidate_evaluation_index = 0

    for generation in range(generations):
        latent_population = mean + std * rng.standard_normal((population, dimension))
        candidates = []
        for index in range(population):
            candidate = evaluate_policy_candidate(
                model,
                latent_population[index],
                training_scenarios,
                seed=seed + 97 * generation + index,
                replica_count=replica_count,
                substeps=substeps,
            )
            candidate["latent_vector"] = latent_population[index]
            candidates.append(candidate)
        population_candidates = list(candidates)

        candidates.sort(key=lambda item: item["score"], reverse=True)
        elites = candidates[:elite_count]
        elite_vectors = np.stack([item["latent_vector"] for item in elites], axis=0)
        mean = 0.28 * mean + 0.72 * np.mean(elite_vectors, axis=0)
        std = 0.36 * std + 0.64 * np.std(elite_vectors, axis=0)
        std = np.maximum(std, 0.08)

        generation_best = candidates[0]
        if best_candidate is None or generation_best["score"] > best_candidate["score"]:
            best_candidate = generation_best
            no_improve = 0
        else:
            no_improve += 1

        generation_rank_by_id = {id(candidate): rank for rank, candidate in enumerate(candidates, start=1)}
        candidate_rows = []
        for candidate_index, candidate in enumerate(population_candidates):
            candidate_evaluation_index += 1
            candidate_rows.append(
                policy_candidate_trace_row(
                    candidate,
                    generation=generation,
                    candidate_index=candidate_index,
                    evaluation_index=candidate_evaluation_index,
                    generation_rank=generation_rank_by_id[id(candidate)],
                )
            )
        append_live_history_rows("live_policy_candidate_history.csv", candidate_rows)
        history_rows.append(
            {
                "generation": generation,
                "best_score": generation_best["score"],
                "mean_score": float(np.mean([item["score"] for item in population_candidates])),
                "global_best_score": best_candidate["score"],
                "optimizer": "cem",
            }
        )
        publish_live_history_csv("live_policy_history.csv", history_rows)
        update_live_monitor_state(
            stage="policy_search",
            policy_search={
                "optimizer": "cem",
                "generation": int(generation),
                "best_score": float(generation_best["score"]),
                "global_best_score": float(best_candidate["score"]),
                "mean_score": float(np.mean([item["score"] for item in population_candidates])),
                "candidate_history_rows": int(candidate_evaluation_index),
            },
        )
        if no_improve >= 4 and float(np.mean(std)) < 0.24:
            break

    return best_candidate, pd.DataFrame(history_rows)


def refine_gap_after_policy(design: HifiDesign, policy: HeightPolicy, seed: int, num_samples: int):
    """Sweeps nearby practical gaps and keeps the best dynamic compromise."""

    max_practical_gap_m = min(0.042, 1.85 * design.magnet_tangential_length_m)
    practical_gap_grid_m = np.array([0.008, 0.010, 0.012, 0.014, 0.016, 0.018, 0.020, 0.024, 0.028, 0.032, 0.036, 0.042], dtype=float)
    local_window_m = np.linspace(design.gap_m - 0.010, design.gap_m + 0.010, 6)
    candidate_gaps = np.unique(
        np.clip(
            np.concatenate((practical_gap_grid_m, local_window_m, np.array([design.gap_m], dtype=float))),
            0.006,
            max_practical_gap_m,
        )
    )
    scenarios = filter_training_scenarios(seed + 19000, 0.06)
    rows = []
    best_result = None
    for gap_m in candidate_gaps:
        candidate_design = replace(design, gap_m=float(gap_m))
        candidate_geometry = build_geometry_from_shape(
            candidate_design.shape_parameters,
            candidate_design.mean_radius_m,
            candidate_design.gap_m,
            num_samples,
        )
        candidate_model = build_array_model(candidate_design, candidate_geometry, SEARCH_DIPOLE_GRID)
        static = assess_static_design(
            candidate_model,
            directions=np.linspace(0.0, 2.0 * math.pi, 10, endpoint=False),
            displacements_m=SEARCH_DISPLACEMENTS_M,
            height_fractions=np.array([0.0, 0.5, 0.95], dtype=float),
            yaw_samples_rad=SEARCH_YAW_RAD,
        )
        outcomes = [
            simulate_dynamic_episode(
                candidate_model,
                policy,
                scenario,
                environment=nominal_episode_environment(),
                record=False,
                substeps=1,
            )
            for scenario in scenarios
        ]
        dynamic_scores = np.array([outcome.score for outcome in outcomes], dtype=float)
        dynamic_contacts = int(sum(outcome.contact_events for outcome in outcomes))
        dynamic_latches = int(sum(outcome.latched for outcome in outcomes))
        worst_gap_mm = float(min(outcome.min_gap_m for outcome in outcomes) * 1000.0)
        worst_contact_demand_mm = float(max(outcome.max_contact_demand_m for outcome in outcomes) * 1000.0)
        screening_score = (
            float(np.mean(dynamic_scores))
            + 0.03 * static.mean_full_height_stiffness_npm
            + 0.05 * static.min_reduced_height_stiffness_npm
            - 1000.0 * static.negative_yaw_restore_count
            - 1300.0 * static.negative_towed_yaw_restore_count
            - 800.0 * max(0.0, static.mean_orthogonal_ratio - 0.10)
            - 140.0 * static.mean_forward_torque_ratio
            - 420.0 * max(0.0, static.mean_forward_torque_ratio - 0.055)
            - 120.0 * dynamic_contacts
            - 1400.0 * dynamic_latches
            - 2200.0 * max(0.0, -static.min_towed_yaw_restoring_nm)
            - 75.0 * worst_contact_demand_mm
            - 50000.0 * static.package_violation_m
        )
        row = {
            "gap_m": float(gap_m),
            "screening_score": screening_score,
            "dynamic_mean_score": float(np.mean(dynamic_scores)),
            "dynamic_contacts": dynamic_contacts,
            "dynamic_latches": dynamic_latches,
            "worst_gap_mm": worst_gap_mm,
            "worst_contact_demand_mm": worst_contact_demand_mm,
            "static_negative_yaw_restore_count": static.negative_yaw_restore_count,
            "static_negative_towed_yaw_restore_count": static.negative_towed_yaw_restore_count,
            "static_mean_full_height_stiffness_npm": static.mean_full_height_stiffness_npm,
            "static_min_reduced_height_stiffness_npm": static.min_reduced_height_stiffness_npm,
            "static_mean_forward_torque_ratio": static.mean_forward_torque_ratio,
            "static_package_violation_mm": 1000.0 * static.package_violation_m,
        }
        rows.append(row)
        if best_result is None or screening_score > best_result["screening_score"]:
            best_result = {
                "screening_score": screening_score,
                "design": candidate_design,
                "geometry": candidate_geometry,
                "rows": rows,
            }
    return best_result["design"], best_result["geometry"], pd.DataFrame(rows)


def report_dynamic_dataframe(outcomes):
    """Converts dynamic scenario outcomes into a report-friendly table."""

    return pd.DataFrame(
        [
            {
                "scenario_name": outcome.scenario_name,
                "environment_label": outcome.environment_label,
                "scenario_label": (
                    outcome.scenario_name
                    if outcome.environment_label == "nominal"
                    else f"{outcome.scenario_name}__{outcome.environment_label}"
                ),
                "score": outcome.score,
                "contact_events": outcome.contact_events,
                "constraint_activations": outcome.constraint_activations,
                "latched": int(outcome.latched),
                "min_clearance_mm": 1000.0 * outcome.min_gap_m,
                "min_gap_mm": 1000.0 * outcome.min_gap_m,
                "max_contact_demand_mm": 1000.0 * outcome.max_contact_demand_m,
                "max_penetration_mm": 1000.0 * outcome.max_contact_demand_m,
                "translation_rms_mm": 1000.0 * outcome.translation_rms_m,
                "yaw_rms_deg": math.degrees(outcome.yaw_rms_rad),
                "turn_signal_ratio": outcome.turn_signal_ratio,
                "turn_latency_s": outcome.turn_latency_s,
                "recenter_s": outcome.recenter_s,
                "height_shift_mean_mm": 1000.0 * outcome.height_shift_mean_m,
                "height_shift_peak_mm": 1000.0 * outcome.height_shift_peak_m,
                "cue_peak_yaw_deg": outcome.cue_peak_yaw_deg,
                "cue_peak_translation_mm": outcome.cue_peak_translation_mm,
                "sensor_peak_n": outcome.sensor_peak_n,
                "height_return_s": outcome.height_return_s,
                "cruise_translation_rms_mm": 1000.0 * outcome.cruise_translation_rms_m,
                "cruise_yaw_rms_deg": math.degrees(outcome.cruise_yaw_rms_rad),
                "contact_duration_s": outcome.contact_duration_s,
                "first_contact_time_s": (
                    float(outcome.first_contact_time_s) if outcome.first_contact_time_s is not None else math.nan
                ),
                "input_force_peak_n": outcome.input_force_peak_n,
                "input_torque_peak_nm": outcome.input_torque_peak_nm,
                "magnetic_force_peak_n": outcome.magnetic_force_peak_n,
                "contact_force_peak_n": outcome.contact_force_peak_n,
            }
            for outcome in outcomes
        ]
    )


def plot_design_convergence(history_df, outdir: Path):
    """Plots static design-search convergence."""

    figure, axis = plt.subplots(figsize=(9.0, 5.0))
    axis.plot(history_df["generation"], history_df["best_score"], linewidth=2.2, label="generation best")
    axis.plot(history_df["generation"], history_df["global_best_score"], linewidth=2.2, label="global best")
    axis.plot(history_df["generation"], history_df["mean_score"], linewidth=1.2, alpha=0.75, label="population mean")
    axis.set_xlabel("Generation")
    axis.set_ylabel("Score")
    axis.set_title("High-Fidelity Shape Search Convergence")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(outdir / "design_convergence.png", dpi=180)
    plt.close(figure)


def plot_policy_convergence(history_df, outdir: Path):
    """Plots height-policy learning convergence."""

    figure, axis = plt.subplots(figsize=(8.6, 4.8))
    axis.plot(history_df["generation"], history_df["best_score"], linewidth=2.2, label="generation best")
    axis.plot(history_df["generation"], history_df["global_best_score"], linewidth=2.2, label="global best")
    axis.plot(history_df["generation"], history_df["mean_score"], linewidth=1.2, alpha=0.75, label="population mean")
    axis.set_xlabel("Generation")
    axis.set_ylabel("Score")
    axis.set_title("Height-Control Policy Search Convergence")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(outdir / "policy_convergence.png", dpi=180)
    plt.close(figure)


def plot_force_polar(model: ArrayModel, outdir: Path):
    """Plots directional restoring force for full and reduced overlap heights."""

    directions = np.linspace(0.0, 2.0 * math.pi, 24, endpoint=False)
    reference_displacement_m = 0.004
    figure, axes = plt.subplots(1, 2, figsize=(12.0, 5.2), subplot_kw={"projection": "polar"})

    for axis, height_fraction, title in zip(
        axes,
        [0.0, 0.90],
        ["Full Overlap", "Large Height Reduction"],
    ):
        height_shift_m = height_fraction * model.design.max_overlap_reduction_m
        restoring = []
        orthogonal = []
        for angle in directions:
            direction = np.array([math.cos(angle), math.sin(angle)], dtype=float)
            sample = evaluate_pose(model, reference_displacement_m * direction, 0.0, height_shift_m)
            parallel_force_n = -float(np.dot(sample.force_body_n, direction))
            orthogonal_force_n = abs(base.cross2(direction, sample.force_body_n))
            restoring.append(max(parallel_force_n, 0.0))
            orthogonal.append(orthogonal_force_n)
        axis.plot(directions, restoring, linewidth=2.0, label="parallel restoring")
        axis.plot(directions, orthogonal, linewidth=1.4, label="orthogonal leakage")
        axis.set_title(title)
        axis.legend(loc="lower left", bbox_to_anchor=(0.0, -0.12), fontsize=8)

    figure.suptitle("Directional Restoring Force at 4 mm Translation")
    figure.tight_layout()
    figure.savefig(outdir / "force_polar.png", dpi=180)
    plt.close(figure)


def plot_force_curves(model: ArrayModel, outdir: Path):
    """Plots restoring-force linearity versus displacement and height shift."""

    directions = np.linspace(0.0, 2.0 * math.pi, 12, endpoint=False)
    figure, axes = plt.subplots(1, 2, figsize=(12.5, 4.8))

    for height_fraction in [0.0, 0.35, 0.70, 0.95]:
        values = []
        for displacement_m in VALIDATION_DISPLACEMENTS_M:
            per_direction = []
            for angle in directions:
                direction = np.array([math.cos(angle), math.sin(angle)], dtype=float)
                sample = evaluate_pose(
                    model,
                    displacement_m * direction,
                    0.0,
                    height_fraction * model.design.max_overlap_reduction_m,
                )
                per_direction.append(-float(np.dot(sample.force_body_n, direction)))
            values.append(float(np.mean(per_direction)))
        axes[0].plot(1000.0 * VALIDATION_DISPLACEMENTS_M, values, linewidth=2.0, label=f"h={height_fraction:.2f}")

    reference_displacement_m = 0.0045
    height_shift_values = np.linspace(0.0, model.design.max_overlap_reduction_m, 10)
    force_values = []
    for height_shift_m in height_shift_values:
        per_direction = []
        for angle in directions:
            direction = np.array([math.cos(angle), math.sin(angle)], dtype=float)
            sample = evaluate_pose(model, reference_displacement_m * direction, 0.0, height_shift_m)
            per_direction.append(-float(np.dot(sample.force_body_n, direction)))
        force_values.append(float(np.mean(per_direction)))

    axes[0].set_xlabel("Translation [mm]")
    axes[0].set_ylabel("Mean Restoring Force [N]")
    axes[0].set_title("Force vs Translation")
    axes[0].grid(True, alpha=0.25)
    axes[0].legend(fontsize=8)

    axes[1].plot(1000.0 * height_shift_values, force_values, linewidth=2.2, color="#1d4ed8")
    axes[1].set_xlabel("Height Shift [mm]")
    axes[1].set_ylabel("Mean Restoring Force [N]")
    axes[1].set_title("Force Scaling vs Height Reduction")
    axes[1].grid(True, alpha=0.25)

    figure.tight_layout()
    figure.savefig(outdir / "force_curves.png", dpi=180)
    plt.close(figure)


def planar_response_map(
    model: ArrayModel,
    yaw_rad: float,
    height_shift_m: float,
    span_m: float | None = None,
    grid_count: int = 21,
):
    """Samples the in-plane restoring field around the aligned pose."""

    span_m = span_m or max(0.012, min(0.022, 1.15 * model.translation_contact_limit_m))
    x_values = np.linspace(-span_m, span_m, grid_count)
    y_values = np.linspace(-span_m, span_m, grid_count)
    xx, yy = np.meshgrid(x_values, y_values)
    force_x = np.zeros_like(xx)
    force_y = np.zeros_like(xx)
    clearance = np.zeros_like(xx)
    contact_demand = np.zeros_like(xx)
    energy = np.zeros_like(xx)
    bad_attraction = np.zeros_like(xx, dtype=bool)

    for row in range(grid_count):
        for col in range(grid_count):
            translation = np.array([xx[row, col], yy[row, col]], dtype=float)
            sample = evaluate_pose(model, translation, yaw_rad, height_shift_m)
            force_x[row, col] = sample.force_body_n[0]
            force_y[row, col] = sample.force_body_n[1]
            clearance[row, col] = sample.min_gap_m
            contact_demand[row, col] = sample.contact_penetration_m
            energy[row, col] = sample.potential_energy_j
            displacement_norm = float(np.linalg.norm(translation))
            if displacement_norm <= 1.0e-9:
                bad_attraction[row, col] = sample.contact_penetration_m > 0.0
            else:
                direction = translation / displacement_norm
                restoring_parallel_n = -float(np.dot(sample.force_body_n, direction))
                bad_attraction[row, col] = restoring_parallel_n <= 0.0 or sample.contact_penetration_m > 0.0

    return {
        "x_values": x_values,
        "y_values": y_values,
        "xx": xx,
        "yy": yy,
        "force_x": force_x,
        "force_y": force_y,
        "clearance": clearance,
        "contact_demand": contact_demand,
        "energy": energy,
        "bad_attraction": bad_attraction,
    }


def plot_planar_response_maps(model: ArrayModel, outdir: Path):
    """Exports vector, clearance, attraction-risk, and energy maps for report inspection."""

    specs = [
        (0.0, "yaw0"),
        (math.radians(20.0), "yaw20"),
    ]
    for yaw_rad, suffix in specs:
        sampled = planar_response_map(model, yaw_rad=yaw_rad, height_shift_m=0.0, grid_count=21)
        xx = sampled["xx"]
        yy = sampled["yy"]
        fx = sampled["force_x"]
        fy = sampled["force_y"]
        stride = 2

        figure, axis = plt.subplots(figsize=(6.4, 6.0))
        mag = np.sqrt(fx * fx + fy * fy)
        image = axis.contourf(xx, yy, mag, levels=16, cmap="viridis")
        axis.quiver(
            xx[::stride, ::stride],
            yy[::stride, ::stride],
            fx[::stride, ::stride],
            fy[::stride, ::stride],
            color="white",
            scale=650.0,
            width=0.004,
        )
        axis.plot(model.geometry.inner_points[:, 0], model.geometry.inner_points[:, 1], color="#111827", linewidth=1.2)
        axis.plot(
            model.geometry.outer_points_local[:, 0],
            model.geometry.outer_points_local[:, 1],
            color="#1d4ed8",
            linewidth=1.1,
        )
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlabel("x [m]")
        axis.set_ylabel("y [m]")
        axis.set_title(f"Planar Force Vector Map ({math.degrees(yaw_rad):.0f} deg)")
        figure.colorbar(image, ax=axis, label="|F| [N]")
        figure.tight_layout()
        figure.savefig(outdir / f"force_vector_map_{suffix}.png", dpi=180)
        plt.close(figure)

        figure, axis = plt.subplots(figsize=(6.4, 6.0))
        image = axis.contourf(xx, yy, 1000.0 * sampled["clearance"], levels=16, cmap="cividis")
        axis.plot(model.geometry.inner_points[:, 0], model.geometry.inner_points[:, 1], color="white", linewidth=1.0)
        axis.plot(model.geometry.outer_points_local[:, 0], model.geometry.outer_points_local[:, 1], color="#93c5fd", linewidth=1.0)
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlabel("x [m]")
        axis.set_ylabel("y [m]")
        axis.set_title(f"Minimum Clearance Map ({math.degrees(yaw_rad):.0f} deg)")
        figure.colorbar(image, ax=axis, label="clearance [mm]")
        figure.tight_layout()
        figure.savefig(outdir / f"minimum_gap_map_{suffix}.png", dpi=180)
        plt.close(figure)

        figure, axis = plt.subplots(figsize=(6.4, 6.0))
        axis.imshow(
            sampled["bad_attraction"].astype(float),
            extent=[sampled["x_values"].min(), sampled["x_values"].max(), sampled["y_values"].min(), sampled["y_values"].max()],
            origin="lower",
            cmap="RdYlGn_r",
            vmin=0.0,
            vmax=1.0,
            aspect="equal",
        )
        axis.plot(model.geometry.inner_points[:, 0], model.geometry.inner_points[:, 1], color="#111827", linewidth=1.0)
        axis.plot(model.geometry.outer_points_local[:, 0], model.geometry.outer_points_local[:, 1], color="#1d4ed8", linewidth=1.0)
        axis.set_xlabel("x [m]")
        axis.set_ylabel("y [m]")
        axis.set_title(f"Bad Attraction Map ({math.degrees(yaw_rad):.0f} deg)")
        figure.tight_layout()
        figure.savefig(outdir / f"bad_attraction_map_{suffix}.png", dpi=180)
        plt.close(figure)

        figure, axis = plt.subplots(figsize=(6.4, 6.0))
        image = axis.contourf(xx, yy, sampled["energy"], levels=16, cmap="magma")
        axis.plot(model.geometry.inner_points[:, 0], model.geometry.inner_points[:, 1], color="white", linewidth=1.0)
        axis.plot(model.geometry.outer_points_local[:, 0], model.geometry.outer_points_local[:, 1], color="#93c5fd", linewidth=1.0)
        axis.set_aspect("equal", adjustable="box")
        axis.set_xlabel("x [m]")
        axis.set_ylabel("y [m]")
        axis.set_title(f"Potential Energy Map ({math.degrees(yaw_rad):.0f} deg)")
        figure.colorbar(image, ax=axis, label="energy [J]")
        figure.tight_layout()
        figure.savefig(outdir / f"potential_energy_map_{suffix}.png", dpi=180)
        plt.close(figure)


def plot_dynamic_rollout(outcome: DynamicOutcome, outdir: Path, prefix: str):
    """Plots one recorded dynamic rollout for the final report."""

    if outcome.record is None:
        return
    record = outcome.record
    time_s = np.array(record["time_s"], dtype=float)
    rel_xy_mm = 1000.0 * np.sqrt(np.square(record["rel_x_m"]) + np.square(record["rel_y_m"]))
    rel_yaw_deg = np.degrees(np.array(record["rel_yaw_rad"], dtype=float))
    min_gap_mm = 1000.0 * np.array(record["min_gap_m"], dtype=float)
    raw_gap_mm = 1000.0 * np.array(record["raw_signed_gap_m"], dtype=float)
    height_shift_mm = 1000.0 * np.array(record["height_shift_m"], dtype=float)
    input_force_mag_n = np.array(record["input_force_mag_n"], dtype=float)
    input_torque_nm = np.array(record["input_torque_nm"], dtype=float)
    magnetic_force_mag_n = np.array(record["magnetic_force_mag_n"], dtype=float)
    magnetic_torque_mag_nm = np.array(record["magnetic_torque_mag_nm"], dtype=float)
    contact_force_mag_n = np.array(record["contact_force_mag_n"], dtype=float)
    contact_demand_mm = 1000.0 * np.array(record["contact_demand_m"], dtype=float)
    constraint_active = np.array(record["constraint_active"], dtype=int)

    figure, axes = plt.subplots(7, 1, figsize=(10.8, 15.0), sharex=True)
    axes[0].plot(time_s, rel_xy_mm, linewidth=2.0, color="#0f766e")
    axes[0].set_ylabel("Rel. XY [mm]")
    axes[0].grid(True, alpha=0.24)

    axes[1].plot(time_s, rel_yaw_deg, linewidth=2.0, color="#1d4ed8")
    axes[1].set_ylabel("Rel. Yaw [deg]")
    axes[1].grid(True, alpha=0.24)

    axes[2].plot(time_s, min_gap_mm, linewidth=2.0, color="#7c3aed")
    axes[2].plot(time_s, raw_gap_mm, linewidth=1.2, color="#ef4444", alpha=0.8, label="raw signed gap")
    axes[2].axhline(0.0, color="#b91c1c", linestyle="--", linewidth=1.0)
    axes[2].set_ylabel("Clearance [mm]")
    axes[2].grid(True, alpha=0.24)
    axes[2].legend(loc="upper right", fontsize=8)

    axes[3].plot(time_s, height_shift_mm, linewidth=2.0, color="#f59e0b")
    axes[3].set_ylabel("Height Shift [mm]")
    axes[3].grid(True, alpha=0.24)

    axes[4].plot(time_s, input_force_mag_n, linewidth=2.0, color="#0f766e")
    axes[4].set_ylabel("Input F [N]")
    axes[4].grid(True, alpha=0.24)

    axes[5].plot(time_s, input_torque_nm, linewidth=2.0, color="#c2410c", label="input")
    axes[5].plot(time_s, magnetic_torque_mag_nm, linewidth=1.5, color="#2563eb", label="magnetic")
    axes[5].set_ylabel("Torque [N m]")
    axes[5].grid(True, alpha=0.24)
    axes[5].legend(loc="upper right", fontsize=8)

    axes[6].plot(time_s, magnetic_force_mag_n, linewidth=1.8, color="#15803d", label="magnetic")
    axes[6].plot(time_s, contact_force_mag_n, linewidth=1.8, color="#b91c1c", label="contact")
    axes[6].plot(time_s, contact_demand_mm, linewidth=1.2, color="#7c2d12", alpha=0.85, label="contact demand [mm]")
    axes[6].set_ylabel("Force")
    axes[6].set_xlabel("Time [s]")
    axes[6].grid(True, alpha=0.24)
    axes[6].legend(loc="upper right", fontsize=8)

    for axis in axes:
        for idx, active in enumerate(constraint_active):
            if active:
                start = time_s[max(idx - 1, 0)] if idx > 0 else time_s[idx]
                end = time_s[idx]
                axis.axvspan(start, end, color="#fecaca", alpha=0.20)

    title = outcome.scenario_name if outcome.environment_label == "nominal" else f"{outcome.scenario_name} ({outcome.environment_label})"
    figure.suptitle(f"Dynamic Validation Rollout: {title}")
    figure.tight_layout()
    figure.savefig(outdir / f"{prefix}_rollout.png", dpi=180)
    plt.close(figure)


def plot_field_distribution(model: ArrayModel, outdir: Path):
    """Plots top-view and vertical-slice field distributions for the selected array."""

    span_xy = model.design.mean_radius_m + model.design.gap_m + model.design.magnet_radial_depth_m + 0.08
    x_values = np.linspace(-span_xy, span_xy, 81)
    y_values = np.linspace(-span_xy, span_xy, 81)
    xx, yy = np.meshgrid(x_values, y_values)
    top_points = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(xx.size)))
    top_field = dipole_field(
        top_points,
        model.inner_centers_xyz,
        model.inner_moments_xyz,
    ) + dipole_field(
        top_points,
        model.outer_centers_local_xyz,
        model.outer_moments_local_xyz,
    )
    top_field = top_field.reshape(xx.shape + (3,))
    top_mag_mt = 1000.0 * np.linalg.norm(top_field, axis=2)

    z_values = np.linspace(-0.06, 0.06, 81)
    xx2, zz2 = np.meshgrid(x_values, z_values)
    side_points = np.column_stack((xx2.ravel(), np.zeros(xx2.size), zz2.ravel()))
    side_field = dipole_field(
        side_points,
        model.inner_centers_xyz,
        model.inner_moments_xyz,
    ) + dipole_field(
        side_points,
        model.outer_centers_local_xyz,
        model.outer_moments_local_xyz,
    )
    side_field = side_field.reshape(xx2.shape + (3,))
    side_mag_mt = 1000.0 * np.linalg.norm(side_field, axis=2)

    figure, axes = plt.subplots(1, 2, figsize=(12.6, 5.8), dpi=160)
    im0 = axes[0].imshow(
        top_mag_mt,
        extent=[x_values.min(), x_values.max(), y_values.min(), y_values.max()],
        origin="lower",
        cmap="magma",
        aspect="equal",
    )
    axes[0].plot(model.geometry.inner_points[:, 0], model.geometry.inner_points[:, 1], color="white", linewidth=1.3)
    axes[0].plot(model.geometry.outer_points_local[:, 0], model.geometry.outer_points_local[:, 1], color="#93c5fd", linewidth=1.2)
    stride = 6
    axes[0].quiver(
        xx[::stride, ::stride],
        yy[::stride, ::stride],
        top_field[::stride, ::stride, 0],
        top_field[::stride, ::stride, 1],
        color="white",
        scale=35.0,
        width=0.0024,
    )
    axes[0].set_title("Selected Array Field\nTop View z = 0 m")
    axes[0].set_xlabel("x [m]")
    axes[0].set_ylabel("y [m]")
    figure.colorbar(im0, ax=axes[0], shrink=0.82, label="|B| [mT]")

    im1 = axes[1].imshow(
        side_mag_mt,
        extent=[x_values.min(), x_values.max(), z_values.min(), z_values.max()],
        origin="lower",
        cmap="viridis",
        aspect="auto",
    )
    axes[1].quiver(
        xx2[::5, ::6],
        zz2[::5, ::6],
        side_field[::5, ::6, 0],
        side_field[::5, ::6, 2],
        color="white",
        scale=40.0,
        width=0.0026,
    )
    axes[1].set_title("Selected Array Field\nx-z Slice at y = 0 m")
    axes[1].set_xlabel("x [m]")
    axes[1].set_ylabel("z [m]")
    figure.colorbar(im1, ax=axes[1], shrink=0.82, label="|B| [mT]")
    figure.tight_layout()
    figure.savefig(outdir / "selected_design_field_distribution.png", dpi=180)
    plt.close(figure)


def dipole_field(points_xyz, centers_xyz, moments_xyz):
    """Computes magnetic flux density at query points from a dipole cloud."""

    field = np.zeros_like(points_xyz, dtype=float)
    for center, moment in zip(centers_xyz, moments_xyz):
        vector = points_xyz - center
        distance_sq = np.sum(vector * vector, axis=1) + 1.0e-12
        distance = np.sqrt(distance_sq)
        r_hat = vector / distance[:, None]
        moment_dot = np.sum(r_hat * moment, axis=1)
        field += (MU0 / (4.0 * math.pi)) * (3.0 * moment_dot[:, None] * r_hat - moment) / (distance_sq * distance)[:, None]
    return field


def magpylib_rotation_from_moment(moment_dir_xyz):
    """Builds a magnet orientation whose local +z follows the requested moment direction."""

    if SciRotation is None:
        raise RuntimeError("SciRotation is unavailable; cannot build Magpylib orientations.")
    normal = np.asarray(moment_dir_xyz, dtype=float)
    normal /= np.linalg.norm(normal) + 1.0e-12
    tangent = np.array([-normal[1], normal[0], 0.0], dtype=float)
    if np.linalg.norm(tangent) <= 1.0e-9:
        tangent = np.array([1.0, 0.0, 0.0], dtype=float)
    tangent /= np.linalg.norm(tangent) + 1.0e-12
    axial = np.cross(normal, tangent)
    axial /= np.linalg.norm(axial) + 1.0e-12
    return SciRotation.from_matrix(np.column_stack((tangent, axial, normal)))


def magpylib_magnet_from_pose(design: HifiDesign, center_xyz, moment_dir_xyz, as_target: bool):
    """Builds one analytical magnet object for cross-checking against the dipole-cloud model."""

    if magpy is None:
        raise RuntimeError("Magpylib is unavailable; cannot run analytical cross-check.")
    rotation = magpylib_rotation_from_moment(moment_dir_xyz)
    polarization = (0.0, 0.0, float(design.effective_flux_t))
    if base.MAGNET_CATALOG_BY_ID[design.magnet_sku_id].magnet_shape == "disk":
        kwargs = {"meshing": 9} if as_target else {}
        return magpy.magnet.Cylinder(
            polarization=polarization,
            dimension=(design.magnet_tangential_length_m, design.magnet_radial_depth_m),
            position=tuple(np.asarray(center_xyz, dtype=float)),
            orientation=rotation,
            **kwargs,
        )
    kwargs = {"meshing": (4, 4, 2)} if as_target else {}
    return magpy.magnet.Cuboid(
        polarization=polarization,
        dimension=(
            design.magnet_tangential_length_m,
            design.magnet_axial_height_m,
            design.magnet_radial_depth_m,
        ),
        position=tuple(np.asarray(center_xyz, dtype=float)),
        orientation=rotation,
        **kwargs,
    )


def magpylib_pose_force_torque(model: ArrayModel, relative_translation_body_m, relative_yaw_rad, height_shift_m):
    """Evaluates one pose with Magpylib analytical magnet objects for final cross-checking."""

    design = model.design
    inner_sources = [
        magpylib_magnet_from_pose(design, center_xyz, moment_dir_xyz, as_target=False)
        for center_xyz, moment_dir_xyz in zip(model.inner_magnet_centers_xyz, model.inner_moment_dirs_xyz)
    ]
    rotation = base.rotmat(relative_yaw_rad)
    outer_centers_xy = model.outer_magnet_centers_local_xyz[:, :2] @ rotation.T + relative_translation_body_m
    outer_dirs_xy = model.outer_moment_dirs_local_xyz[:, :2] @ rotation.T
    outer_centers_xyz = np.column_stack((outer_centers_xy, model.outer_magnet_centers_local_xyz[:, 2] + height_shift_m))
    outer_dirs_xyz = np.column_stack((outer_dirs_xy, model.outer_moment_dirs_local_xyz[:, 2]))
    outer_targets = [
        magpylib_magnet_from_pose(design, center_xyz, moment_dir_xyz, as_target=True)
        for center_xyz, moment_dir_xyz in zip(outer_centers_xyz, outer_dirs_xyz)
    ]
    net_force_body = np.zeros(3, dtype=float)
    net_torque_body = np.zeros(3, dtype=float)
    for target in outer_targets:
        force_xyz, torque_xyz = magpy.getFT(inner_sources, target, pivot="centroid", eps=1.0e-6, squeeze=True)
        net_force_body += np.sum(np.asarray(force_xyz, dtype=float), axis=0)
        net_torque_body += np.sum(np.asarray(torque_xyz, dtype=float), axis=0)
    return net_force_body[:2], float(net_torque_body[2])


def write_magpylib_crosscheck(model: ArrayModel, outdir: Path):
    """Writes a small analytical cross-check set for representative poses."""

    outdir.mkdir(parents=True, exist_ok=True)
    if magpy is None or SciRotation is None:
        payload = {"available": False, "reason": "magpylib or scipy rotation support is unavailable"}
        (outdir / "magpylib_crosscheck.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return
    poses = [
        ("aligned", np.zeros(2, dtype=float), 0.0, 0.0),
        ("x_plus_4mm", np.array([0.004, 0.0], dtype=float), 0.0, 0.0),
        ("y_plus_4mm", np.array([0.0, 0.004], dtype=float), 0.0, 0.0),
        ("yaw_6deg", np.zeros(2, dtype=float), math.radians(6.0), 0.0),
        (
            "cue_combo",
            np.array([0.004, 0.006], dtype=float),
            math.radians(8.0),
            min(0.40 * model.design.max_overlap_reduction_m, 0.0035),
        ),
    ]
    rows = []
    for label, translation_body_m, yaw_rad, height_shift_m in poses:
        approx = evaluate_pose(model, translation_body_m, yaw_rad, height_shift_m)
        magpy_force_body_n, magpy_torque_nm = magpylib_pose_force_torque(
            model,
            translation_body_m,
            yaw_rad,
            height_shift_m,
        )
        rows.append(
            {
                "pose_label": label,
                "translation_x_mm": 1000.0 * float(translation_body_m[0]),
                "translation_y_mm": 1000.0 * float(translation_body_m[1]),
                "yaw_deg": math.degrees(yaw_rad),
                "height_shift_mm": 1000.0 * float(height_shift_m),
                "approx_force_x_n": float(approx.force_body_n[0]),
                "approx_force_y_n": float(approx.force_body_n[1]),
                "magpylib_force_x_n": float(magpy_force_body_n[0]),
                "magpylib_force_y_n": float(magpy_force_body_n[1]),
                "force_error_norm_n": float(np.linalg.norm(approx.force_body_n - magpy_force_body_n)),
                "approx_torque_nm": float(approx.torque_outer_nm),
                "magpylib_torque_nm": float(magpy_torque_nm),
                "torque_error_nm": float(abs(approx.torque_outer_nm - magpy_torque_nm)),
                "min_gap_mm": 1000.0 * float(approx.min_gap_m),
            }
        )
    crosscheck_df = pd.DataFrame(rows)
    crosscheck_df.to_csv(outdir / "magpylib_crosscheck.csv", index=False)
    payload = {
        "available": True,
        "mean_force_error_n": float(crosscheck_df["force_error_norm_n"].mean()),
        "max_force_error_n": float(crosscheck_df["force_error_norm_n"].max()),
        "mean_torque_error_nm": float(crosscheck_df["torque_error_nm"].mean()),
        "max_torque_error_nm": float(crosscheck_df["torque_error_nm"].max()),
    }
    (outdir / "magpylib_crosscheck.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_catalog_snapshot(outdir: Path):
    """Writes the actual product catalog used by the optimizer."""

    catalog_df = pd.DataFrame([asdict(sku) for sku in base.MAGNET_CATALOG])
    catalog_df["tangential_length_mm"] = 1000.0 * catalog_df["tangential_length_m"]
    catalog_df["axial_height_mm"] = 1000.0 * catalog_df["axial_height_m"]
    catalog_df["radial_depth_mm"] = 1000.0 * catalog_df["radial_depth_m"]
    catalog_df["effective_flux_t"] = [effective_flux_density_t(sku) for sku in base.MAGNET_CATALOG]
    catalog_df.to_csv(outdir / "magnet_catalog.csv", index=False)


def write_scenario_input_profiles(scenarios, outdir: Path):
    """Exports the validation input force/torque profiles used in the dynamic report."""

    profiles_dir = outdir / "validation_scenario_inputs"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    for scenario in scenarios:
        steps = scenario.force_world_n.shape[0]
        time_s = scenario.dt_s * (np.arange(steps, dtype=float) + 1.0)
        profile_df = pd.DataFrame(
            {
                "time_s": time_s,
                "force_x_n": scenario.force_world_n[:, 0],
                "force_y_n": scenario.force_world_n[:, 1],
                "force_mag_n": np.linalg.norm(scenario.force_world_n, axis=1),
                "torque_nm": scenario.torque_nm,
                "phase": scenario.phase,
            }
        )
        profile_df.to_csv(profiles_dir / f"{scenario.name}.csv", index=False)


def write_optimizer_literature_note(outdir: Path):
    """Writes the literature basis adopted for the redesigned optimizer."""

    lines = [
        "# Optimizer Literature Basis",
        "",
        "This run uses a literature-guided redesign of the static shape search rather than the older weighted-score-only CEM.",
        "",
        "## Incorporated ideas",
        "- `CMA-ES` for rugged, non-convex, derivative-free continuous search spaces.",
        "- `Augmented Lagrangian` constraint handling with feasible-first search.",
        "- `IPOP` restarts to improve global search by enlarging the population after each restart.",
        "- `Pareto archive retention` so that straight-line stability, reduced-height sensitivity, and cost trade-offs are not collapsed too early.",
        "- `Dimensionless latent variables` and coarse-to-fine screening, consistent with dimensional-analysis-minded magnetic coupler design.",
        "",
        "## Primary sources",
        "- Hansen, N. The CMA Evolution Strategy: official overview and tutorial. https://cma-es.github.io/",
        "- Dufosse, P., Hansen, N. Augmented Lagrangian, penalty techniques and surrogate modeling for constrained optimization with CMA-ES. GECCO 2021. https://doi.org/10.1145/3449639.3459340",
        "- Auger, A., Hansen, N. A Restart CMA Evolution Strategy With Increasing Population Size. CEC 2005. https://cma-es.github.io/cec2005/cec2005ipopcmaes.pdf",
        "- Deb, K., Pratap, A., Agarwal, S., Meyarivan, T. A Fast and Elitist Multiobjective Genetic Algorithm: NSGA-II. IEEE TEC 2002. https://www.cse.unr.edu/~sushil/class/gas/papers/nsga2.pdf",
        "- Igel, C., Hansen, N., Roth, S. Covariance Matrix Adaptation for Multi-objective Optimization. Evolutionary Computation 2007.",
        "- Aman, J. L. B., Abbott, J. J., Roundy, S. Optimal Parametric Design of Radial Magnetic Torque Couplers via Dimensional Analysis. IEEE Transactions on Magnetics 2022. https://iss.mech.utah.edu/wp-content/uploads/sites/103/2023/05/Optimal_Parametric_Design_of_Radial_Magnetic_Torque_Couplers_via_Dimensional_Analysis.pdf",
        "- Ren, Z. H., Mu, W. C., Huang, S. Y. Design and Optimization of a Ring-Pair Permanent Magnet Array for Head Imaging in a Low-Field Portable MRI System. IEEE Transactions on Magnetics 2019. https://ieeexplore.ieee.org/iel7/20/8581524/08532125.pdf",
        "",
        "## What changed in this codebase",
        "- Static search now ranks candidates by feasibility first, not only by a single weighted score.",
        "- Straight-line transport metrics remain explicit constraints: orthogonal leakage, forward-offset parasitic torque, directional stiffness variation, tow-offset proxy, yaw restoration, and zero-contact requirement.",
        "- CMA-ES restarts now follow an increasing-population schedule inspired by IPOP-CMA-ES.",
        "- Feasible candidates are also stored in a Pareto-style archive so that the final choice can preserve multiple useful trade-offs instead of one brittle scalar optimum.",
        "",
    ]
    (outdir / "optimizer_literature_basis.md").write_text("\n".join(lines), encoding="utf-8")


def write_summary(
    design_candidate,
    policy_candidate,
    design_history_df,
    policy_history_df,
    static_assessment: StaticAssessment,
    dynamic_outcomes,
    outdir: Path,
    shape_family_mode="both",
    design_optimizer="cmaes",
):
    """Writes machine-readable and markdown summaries for the final report."""

    design: HifiDesign = design_candidate["design"]
    policy: HeightPolicy = policy_candidate["policy"]
    dynamic_df = report_dynamic_dataframe(dynamic_outcomes)
    payload = {
        "selected_design": asdict(design),
        "shape_label": shape_name(design.shape_parameters),
        "static_assessment": asdict(static_assessment),
        "selected_policy": asdict(policy),
        "dynamic_validation": {
            "mean_score": float(dynamic_df["score"].mean()),
            "worst_score": float(dynamic_df["score"].min()),
            "contact_events_total": int(dynamic_df["contact_events"].sum()),
            "constraint_activations_total": int(dynamic_df["constraint_activations"].sum()),
            "latched_total": int(dynamic_df["latched"].sum()),
            "worst_min_clearance_mm": float(dynamic_df["min_clearance_mm"].min()),
            "max_contact_demand_mm": float(dynamic_df["max_contact_demand_mm"].max()),
            "worst_min_gap_mm": float(dynamic_df["min_clearance_mm"].min()),
            "worst_penetration_mm": float(dynamic_df["max_contact_demand_mm"].max()),
            "mean_turn_latency_s": float(dynamic_df["turn_latency_s"].mean()),
            "mean_recenter_s": float(dynamic_df["recenter_s"].mean()),
            "mean_turn_signal_ratio": float(dynamic_df["turn_signal_ratio"].mean()),
            "mean_contact_duration_s": float(dynamic_df["contact_duration_s"].mean()),
            "mean_cue_peak_yaw_deg": float(dynamic_df["cue_peak_yaw_deg"].mean()),
            "mean_sensor_peak_n": float(dynamic_df["sensor_peak_n"].mean()),
            "mean_height_return_s": float(dynamic_df["height_return_s"].mean()),
        },
        "search": {
            "design_generations": int(design_history_df["generation"].max() + 1),
            "policy_generations": int(policy_history_df["generation"].max() + 1),
            "disk_stack_height_limit_mm": 1000.0 * DISK_STACK_HEIGHT_LIMIT_M,
            "shape_family_mode": shape_family_mode,
            "design_variable_count": design_variable_count(shape_family_mode),
            "design_optimizer": design_optimizer,
        },
        "model_revision": {
            "outer_geometry_method": "inner-boundary normal offset instead of origin-centered similarity scaling",
            "disk_flux_calibration": "surface-field-to-remanence inference for 13 mm x 2.4 mm cylinders",
            "dynamic_contact_method": "substepped integration with contact projection and robust environment perturbations",
            "practical_constraints": "DAISO disk stacks are now allowed up to approximately 78 mm total vertical height per pocket, and the gap is locally re-refined after policy learning",
            "contact_reporting": "physical clearance is clamped to >= 0 and pre-projection overlap is logged separately as contact demand",
            "stability_scoring": "static scoring now penalizes towed yaw-instability, forward-offset parasitic torque, and package violations against AgileX LIMO plus cart envelopes",
            "analytical_crosscheck": "representative poses are cross-checked with Magpylib exact magnet objects and exported separately",
            "optimizer_revision": "static search now supports constrained CMA-ES with feasible-first handling and Pareto archive retention, while the legacy CEM remains available only as a fallback",
        },
    }
    (outdir / "best_design_hifi.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    lines = [
        "# High-Fidelity Magnetic Coupler Optimization Summary",
        "",
        "## Selected Design",
        f"- Shape label: `{shape_name(design.shape_parameters)}`",
        f"- Gap `s`: `{1000.0 * design.gap_m:.2f} mm`",
        f"- Mean radius: `{1000.0 * design.mean_radius_m:.2f} mm`",
        f"- SKU: `{design.magnet_sku_id}`",
        f"- Vendor: `{design.magnet_vendor}`",
        f"- Magnet geometry: `{1000.0 * design.magnet_tangential_length_m:.0f} x {1000.0 * design.magnet_axial_height_m:.0f} x {1000.0 * design.magnet_radial_depth_m:.0f} mm`",
        f"- Magnets per ring: `{design.magnets_per_ring}`",
        f"- Layers per ring: `{design.magnet_layers}`",
        f"- Total magnets: `{design.total_magnets}`",
        f"- Cost estimate: `{design.estimated_total_cost_jpy:.0f} JPY`",
        f"- Effective flux used in simulation: `{design.effective_flux_t:.3f} T`",
        f"- Search family mode: `{shape_family_mode}`",
        f"- Static optimizer: `{design_optimizer}`",
        f"- Design variable count: `{design_variable_count(shape_family_mode)}`",
        "",
        "## Static Assessment",
        f"- Full-height stiffness mean: `{static_assessment.mean_full_height_stiffness_npm:.2f} N/m`",
        f"- Reduced-height stiffness minimum: `{static_assessment.min_reduced_height_stiffness_npm:.2f} N/m`",
        f"- Mean orthogonal leakage ratio: `{static_assessment.mean_orthogonal_ratio:.4f}`",
        f"- Directional stiffness CV: `{static_assessment.direction_stiffness_cv:.4f}`",
        f"- Force-displacement linearity R2: `{static_assessment.displacement_linearity_r2:.4f}`",
        f"- Force-height linearity R2: `{static_assessment.height_linearity_r2:.4f}`",
        f"- Mean forward-offset torque ratio: `{static_assessment.mean_forward_torque_ratio:.4f}`",
        f"- Negative restoring samples: `{static_assessment.negative_restore_count}`",
        f"- Negative yaw restoring samples: `{static_assessment.negative_yaw_restore_count}`",
        f"- Negative towed-yaw restoring samples: `{static_assessment.negative_towed_yaw_restore_count}`",
        f"- Contact samples: `{static_assessment.contact_count}`",
        f"- Packaging violation: `{1000.0 * static_assessment.package_violation_m:.2f} mm`",
        "",
        "## Dynamic Validation",
        f"- Mean score: `{dynamic_df['score'].mean():.2f}`",
        f"- Worst score: `{dynamic_df['score'].min():.2f}`",
        f"- Total contact events: `{int(dynamic_df['contact_events'].sum())}`",
        f"- Total constraint activations: `{int(dynamic_df['constraint_activations'].sum())}`",
        f"- Total latched failures: `{int(dynamic_df['latched'].sum())}`",
        f"- Worst minimum clearance: `{dynamic_df['min_clearance_mm'].min():.3f} mm`",
        f"- Maximum contact demand before projection: `{dynamic_df['max_contact_demand_mm'].max():.3f} mm`",
        f"- Mean cue peak yaw: `{dynamic_df['cue_peak_yaw_deg'].mean():.2f} deg`",
        f"- Mean sensor proxy peak: `{dynamic_df['sensor_peak_n'].mean():.2f} N`",
        f"- Mean height-return time: `{dynamic_df['height_return_s'].mean():.2f} s`",
        "",
        "## Model Revision",
        "- Outer geometry now uses a parallel normal offset from the inner boundary instead of simple origin-centered scaling.",
        "- DAISO disk magnets now convert the catalog 240 mT surface field into an equivalent cylinder remanence before dipole moment synthesis.",
        "- Dynamic validation now includes substepped contact projection, nonnegative physical clearance reporting, and perturbed assembly/damping environments.",
        f"- The DAISO search space now allows vertical disk stacks up to about `{1000.0 * DISK_STACK_HEIGHT_LIMIT_M:.0f} mm` per pocket and performs a post-policy gap rebalancing sweep.",
        "- Static scoring now rejects shapes that only look stable when concentric; it also checks yaw restoration while the robot is already leading the cart and penalizes shapes that exceed the LIMO/cart package envelope.",
        "- Static search is now driven by constrained CMA-ES with explicit inequality constraints and feasible Pareto retention instead of relying only on a single penalty-weighted scalar search score.",
        "- Final representative poses are analytically cross-checked with Magpylib to verify that the dipole-cloud approximation remains close in force and torque.",
        "",
        "## Sources",
        "- MonotaRO product pages and catalog values are reused from the existing discrete magnet optimizer catalog.",
        "- The field/force model uses a volume-dipole discretization of uniformly magnetized cuboids, chosen as a computable approximation to Coulombian surface-charge formulations for permanent magnets.",
    ]
    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args():
    """Parses CLI arguments for the high-fidelity optimization pipeline."""

    parser = argparse.ArgumentParser(
        description="High-fidelity actual-magnet magnetic coupler optimizer with static isotropy and dynamic overlap control."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--design-generations", type=int, default=4)
    parser.add_argument("--design-population", type=int, default=6)
    parser.add_argument("--policy-generations", type=int, default=4)
    parser.add_argument("--policy-population", type=int, default=4)
    parser.add_argument("--elite-count", type=int, default=2)
    parser.add_argument("--search-samples", type=int, default=72)
    parser.add_argument("--validation-samples", type=int, default=128)
    parser.add_argument("--dt", type=float, default=0.06)
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("outputs") / "magnetic_coupler_hifi",
    )
    parser.add_argument(
        "--fixed-sku",
        type=str,
        default=None,
        help="Restrict the optimization to one exact magnet SKU ID from magnetic_coupler_rl.MAGNET_CATALOG.",
    )
    parser.add_argument(
        "--fixed-cart-mass-kg",
        type=float,
        default=None,
        help="If provided, treat the caster-cart mass as a fixed operating condition instead of a design variable.",
    )
    parser.add_argument(
        "--disk-stack-height-limit-m",
        type=float,
        default=DISK_STACK_HEIGHT_LIMIT_M,
        help="Maximum vertical stack height allowed per DAISO-style disk pocket during design search.",
    )
    parser.add_argument(
        "--shape-family-mode",
        type=str,
        choices=("both", "flex", "arrow"),
        default="flex",
        help="Restrict the searched inner-ring geometry family to flexible radial shapes, inverse arrows, or both.",
    )
    parser.add_argument(
        "--max-design-evaluations",
        type=int,
        default=None,
        help="Optional total static design-evaluation budget. Useful for very long runs with convergence-based stopping.",
    )
    parser.add_argument(
        "--min-design-generations",
        type=int,
        default=0,
        help="Minimum number of CEM generations to run before convergence-based early stop is allowed.",
    )
    parser.add_argument(
        "--design-stall-generations",
        type=int,
        default=6,
        help="Stop after this many non-improving generations once the population variance has collapsed enough.",
    )
    parser.add_argument(
        "--coarse-presearch-trials",
        type=int,
        default=0,
        help="Optional number of fast coarse random screens used to seed the main high-fidelity search.",
    )
    parser.add_argument(
        "--coarse-presearch-samples",
        type=int,
        default=48,
        help="Boundary sample count used during coarse presearch only.",
    )
    parser.add_argument(
        "--archive-limit",
        type=int,
        default=64,
        help="Maximum number of unique latent design candidates preserved for post-search validation reranking.",
    )
    parser.add_argument(
        "--validation-refine-generations",
        type=int,
        default=6,
        help="Number of local validation-objective CEM generations run around the best archived candidate.",
    )
    parser.add_argument(
        "--validation-refine-population",
        type=int,
        default=8,
        help="Population used by the local validation-objective CEM refinement.",
    )
    parser.add_argument(
        "--design-optimizer",
        type=str,
        choices=("cmaes", "cem"),
        default="cmaes",
        help="Static design optimizer. 'cmaes' uses constrained CMA-ES with feasible-first handling; 'cem' keeps the legacy search.",
    )
    parser.add_argument(
        "--open-dashboard",
        action="store_true",
        help="Launch the live browser dashboard automatically for this optimization run.",
    )
    parser.add_argument(
        "--dashboard-host",
        type=str,
        default="127.0.0.1",
        help="Host address used by the live browser dashboard when --open-dashboard is enabled.",
    )
    parser.add_argument(
        "--dashboard-port",
        type=int,
        default=8787,
        help="Port used by the live browser dashboard when --open-dashboard is enabled.",
    )
    return parser.parse_args()


def main():
    """Runs shape search, policy learning, high-resolution validation, and asset generation."""

    args = parse_args()
    global DISK_STACK_HEIGHT_LIMIT_M
    DISK_STACK_HEIGHT_LIMIT_M = max(float(args.disk_stack_height_limit_m), 0.0)
    args.outdir.mkdir(parents=True, exist_ok=True)
    set_live_monitor_dir(args.outdir)
    reset_live_monitor_outputs()
    dashboard_url = f"http://{args.dashboard_host}:{args.dashboard_port}/?run={args.outdir.name}"
    update_live_monitor_state(
        stage="initializing",
        run_args=vars(args),
        status="running",
        run_started_epoch_s=time.time(),
        dashboard_url=dashboard_url,
    )
    try:
        if args.open_dashboard:
            try:
                launch_live_dashboard_process(
                    outputs_root=args.outdir.parent,
                    run_dir=args.outdir,
                    host=args.dashboard_host,
                    port=args.dashboard_port,
                )
            except Exception as exc:
                update_live_monitor_state(dashboard_launch_error=str(exc))

        write_catalog_snapshot(args.outdir)
        write_design_variable_manifest(args.outdir, args.shape_family_mode)
        write_optimizer_literature_note(args.outdir)

        catalog = resolve_catalog(args.fixed_sku)
        update_live_monitor_state(stage="design_search", catalog_size=int(len(catalog)))
        design_candidate, design_history_df, archive_df, archive_map = optimize_design(
            seed=args.seed,
            generations=args.design_generations,
            population=args.design_population,
            elite_count=args.elite_count,
            num_samples=args.search_samples,
            fixed_sku_id=args.fixed_sku,
            fixed_cart_mass_kg=args.fixed_cart_mass_kg,
            shape_family_mode=args.shape_family_mode,
            max_evaluations=args.max_design_evaluations,
            min_generations=args.min_design_generations,
            stall_generations=args.design_stall_generations,
            coarse_presearch_trials=args.coarse_presearch_trials,
            coarse_presearch_samples=args.coarse_presearch_samples,
            archive_limit=args.archive_limit,
            design_optimizer=args.design_optimizer,
        )
        design_history_df.to_csv(args.outdir / "design_history.csv", index=False)
        archive_df.to_csv(args.outdir / "design_candidate_archive.csv", index=False)
        plot_design_convergence(design_history_df, args.outdir)
        update_live_monitor_state(
            stage="design_search_complete",
            design_search_complete={
                "history_rows": int(len(design_history_df)),
                "archive_size": int(len(archive_map)),
                "best_score": float(design_candidate["score"]),
            },
        )

        update_live_monitor_state(stage="archive_validation")
        validated_design_candidate, validated_archive_df = refine_design_archive_validation(
            archive_map=archive_map,
            num_samples=args.validation_samples,
            catalog=catalog,
            fixed_cart_mass_kg=args.fixed_cart_mass_kg,
            shape_family_mode=args.shape_family_mode,
            seed=args.seed + 5000,
            refine_generations=args.validation_refine_generations,
            refine_population=args.validation_refine_population,
            refine_elite_count=args.elite_count,
        )
        validated_archive_df.to_csv(args.outdir / "design_candidate_archive_validation.csv", index=False)
        design_candidate = validated_design_candidate

        selected_design: HifiDesign = design_candidate["design"]
        selected_geometry = build_geometry_from_shape(
            selected_design.shape_parameters,
            selected_design.mean_radius_m,
            selected_design.gap_m,
            args.validation_samples,
        )
        static_validation_model = build_array_model(selected_design, selected_geometry, VALIDATION_DIPOLE_GRID)
        static_assessment = assess_static_design(
            static_validation_model,
            directions=np.linspace(0.0, 2.0 * math.pi, 16, endpoint=False),
            displacements_m=VALIDATION_DISPLACEMENTS_M,
            height_fractions=np.linspace(0.0, 0.95, 6),
            yaw_samples_rad=VALIDATION_YAW_RAD,
        )
        update_live_monitor_state(
            stage="policy_search",
            selected_design_pre_policy={
                "shape_label": shape_name(selected_design.shape_parameters),
                "gap_mm": 1000.0 * float(selected_design.gap_m),
                "mean_radius_mm": 1000.0 * float(selected_design.mean_radius_m),
                "magnets_per_ring": int(selected_design.magnets_per_ring),
                "magnet_layers": int(selected_design.magnet_layers),
                "cart_mass_kg": float(selected_design.cart_mass_kg),
            },
        )

        policy_candidate, policy_history_df = optimize_policy(
            design=selected_design,
            geometry=selected_geometry,
            seed=args.seed + 7000,
            generations=args.policy_generations,
            population=args.policy_population,
            elite_count=args.elite_count,
            dt_s=args.dt,
            replica_count=DYNAMIC_SEARCH_ENV_REPLICAS,
            substeps=DYNAMIC_SEARCH_SUBSTEPS,
        )
        policy_history_df.to_csv(args.outdir / "policy_history.csv", index=False)
        plot_policy_convergence(policy_history_df, args.outdir)
        update_live_monitor_state(
            stage="gap_refinement",
            policy_search_complete={
                "history_rows": int(len(policy_history_df)),
                "best_score": float(policy_candidate["score"]),
            },
        )

        refined_design, refined_geometry, gap_refinement_df = refine_gap_after_policy(
            selected_design,
            policy_candidate["policy"],
            seed=args.seed,
            num_samples=args.validation_samples,
        )
        gap_refinement_df.to_csv(args.outdir / "gap_refinement.csv", index=False)
        update_live_monitor_state(
            gap_refinement={
                "candidate_rows": int(len(gap_refinement_df)),
                "selected_gap_mm": 1000.0 * float(refined_design.gap_m),
            },
        )
        if abs(refined_design.gap_m - selected_design.gap_m) > 1.0e-6:
            selected_design = refined_design
            selected_geometry = refined_geometry
            update_live_monitor_state(stage="policy_search_refined_gap")
            policy_candidate, policy_history_df = optimize_policy(
                design=selected_design,
                geometry=selected_geometry,
                seed=args.seed + 9000,
                generations=max(2, args.policy_generations),
                population=max(3, args.policy_population),
                elite_count=args.elite_count,
                dt_s=args.dt,
                replica_count=DYNAMIC_SEARCH_ENV_REPLICAS,
                substeps=DYNAMIC_SEARCH_SUBSTEPS,
            )
            policy_history_df.to_csv(args.outdir / "policy_history.csv", index=False)
            plot_policy_convergence(policy_history_df, args.outdir)

        static_validation_model = build_array_model(selected_design, selected_geometry, VALIDATION_DIPOLE_GRID)
        static_assessment = assess_static_design(
            static_validation_model,
            directions=np.linspace(0.0, 2.0 * math.pi, 16, endpoint=False),
            displacements_m=VALIDATION_DISPLACEMENTS_M,
            height_fractions=np.linspace(0.0, 0.95, 6),
            yaw_samples_rad=VALIDATION_YAW_RAD,
        )
        design_candidate["design"] = selected_design
        design_candidate["geometry"] = selected_geometry
        design_candidate["score"] = float(static_assessment.score)

        update_live_monitor_state(stage="dynamic_validation")
        validation_scenarios = filter_validation_scenarios(args.seed, args.dt)
        write_scenario_input_profiles(validation_scenarios, args.outdir)
        dynamic_validation_model = build_array_model(selected_design, selected_geometry, VALIDATION_DIPOLE_GRID)
        dynamic_outcomes = []
        for scenario in validation_scenarios:
            environments = build_episode_environments(
                selected_design,
                scenario.name,
                seed=args.seed + 14000,
                replica_count=DYNAMIC_VALIDATION_ENV_REPLICAS,
            )
            for environment in environments:
                dynamic_outcomes.append(
                    simulate_dynamic_episode(
                        dynamic_validation_model,
                        policy_candidate["policy"],
                        scenario,
                        environment=environment,
                        record=environment.label == "nominal",
                        substeps=DYNAMIC_VALIDATION_SUBSTEPS,
                    )
                )
        dynamic_df = report_dynamic_dataframe(dynamic_outcomes)
        dynamic_df.to_csv(args.outdir / "dynamic_validation.csv", index=False)
        update_live_monitor_state(
            dynamic_validation={
                "scenario_count": int(len(validation_scenarios)),
                "outcome_count": int(len(dynamic_outcomes)),
                "mean_score": float(dynamic_df["score"].mean()),
                "worst_score": float(dynamic_df["score"].min()),
                "contact_events_total": int(dynamic_df["contact_events"].sum()),
                "latched_total": int(dynamic_df["latched"].sum()),
                "worst_clearance_mm": float(dynamic_df["min_clearance_mm"].min()),
            },
        )

        recorded_outcomes = [outcome for outcome in dynamic_outcomes if outcome.record is not None]
        if recorded_outcomes:
            best_outcome = max(recorded_outcomes, key=lambda outcome: outcome.score)
            worst_outcome = min(recorded_outcomes, key=lambda outcome: outcome.score)
            plot_dynamic_rollout(best_outcome, args.outdir, "best")
            if worst_outcome is not best_outcome:
                plot_dynamic_rollout(worst_outcome, args.outdir, "worst")

        plot_force_polar(static_validation_model, args.outdir)
        plot_force_curves(static_validation_model, args.outdir)
        plot_planar_response_maps(static_validation_model, args.outdir)
        field_model = build_array_model(selected_design, selected_geometry, FIELD_DIPOLE_GRID)
        plot_field_distribution(field_model, args.outdir)
        write_magpylib_crosscheck(field_model, args.outdir)

        write_summary(
            design_candidate=design_candidate,
            policy_candidate=policy_candidate,
            design_history_df=design_history_df,
            policy_history_df=policy_history_df,
            static_assessment=static_assessment,
            dynamic_outcomes=dynamic_outcomes,
            outdir=args.outdir,
            shape_family_mode=args.shape_family_mode,
            design_optimizer=args.design_optimizer,
        )

        final_summary = {
            "shape_label": shape_name(selected_design.shape_parameters),
            "best_sku": selected_design.magnet_sku_id,
            "fixed_sku_constraint": args.fixed_sku,
            "estimated_total_cost_jpy": float(selected_design.estimated_total_cost_jpy),
            "design_search_score": float(design_candidate["score"]),
            "static_validation_score": float(static_assessment.score),
            "dynamic_validation_mean_score": float(dynamic_df["score"].mean()),
            "dynamic_contact_events_total": int(dynamic_df["contact_events"].sum()),
            "dynamic_constraint_activations_total": int(dynamic_df["constraint_activations"].sum()),
            "dynamic_latched_total": int(dynamic_df["latched"].sum()),
            "worst_clearance_mm": float(dynamic_df["min_clearance_mm"].min()),
            "max_contact_demand_mm": float(dynamic_df["max_contact_demand_mm"].max()),
        }
        update_live_monitor_state(
            stage="completed",
            status="completed",
            final_summary=final_summary,
            final_shape_label=shape_name(selected_design.shape_parameters),
            final_design=asdict(selected_design),
            final_static_assessment=asdict(static_assessment),
            run_finished_epoch_s=time.time(),
        )
        print(json.dumps(final_summary, indent=2, ensure_ascii=False))
    except Exception as exc:
        update_live_monitor_state(
            stage="failed",
            status="failed",
            error_message=str(exc),
            run_failed_epoch_s=time.time(),
        )
        raise


if __name__ == "__main__":
    main()
