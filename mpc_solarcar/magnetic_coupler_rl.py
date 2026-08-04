import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")

import matplotlib.pyplot as plt


MU0 = 4.0e-7 * math.pi
CATALOG_DATE = "2026-06-24"
CART_LENGTH_M = 0.62
CART_WIDTH_M = 0.46
ROBOT_LENGTH_M = 0.54
ROBOT_WIDTH_M = 0.42
ROBOT_MASS_KG = 42.0
SOFTMAX_SHARPNESS = 48.0
CONTACT_STIFFNESS_N_PER_M = 65000.0
CONTACT_DAMPING_N_S_PER_M = 260.0
LATCH_PENETRATION_M = 0.0020
LATCH_REL_SPEED_MPS = 0.05
LATCH_TANGENTIAL_SPEED_MPS = 0.09
MIN_EFFECTIVE_OVERLAP_M = 0.004
MAX_GAP_FLUX_T = 0.23
MAX_LINEAR_SPEED_MPS = 3.2
MAX_YAW_RATE_RADPS = 5.2
MAX_RELATIVE_TRANSLATION_M = 0.35
MAX_RELATIVE_YAW_RAD = 1.45
DEFAULT_SHAPES = [
    "ellipse_soft",
    "ellipse_wide",
    "squircle",
    "rounded_rect",
    "hexagon",
    "octagon",
]


@dataclass(frozen=True)
class MagnetSKU:
    sku_id: str
    vendor: str
    product_name: str
    source_url: str
    source_date: str
    tangential_length_m: float
    axial_height_m: float
    radial_depth_m: float
    unit_price_jpy: float
    surface_flux_t: float
    pull_force_n: float
    mount_style: str
    edge_reluctance: float
    magnet_shape: str = "block"
    source_note: str = ""


@dataclass(frozen=True)
class Design:
    shape_name: str
    gap_m: float
    mean_radius_m: float
    radial_depth_m: float
    nominal_overlap_m: float
    max_overlap_reduction_m: float
    cart_mass_kg: float
    actuator_tau_s: float
    actuator_rate_limit_mps: float
    leakage_factor: float
    magnet_sku_id: str
    magnet_vendor: str
    unit_price_jpy: float
    magnet_tangential_length_m: float
    magnet_axial_height_m: float
    magnets_per_ring: int
    magnet_layers: int
    coverage_ratio: float
    pitch_m: float
    tangential_gap_m: float
    outer_phase_fraction: float
    edge_cogging_gain: float
    total_magnets: int
    estimated_total_cost_jpy: float
    surface_flux_t: float
    pull_force_n: float


@dataclass(frozen=True)
class Policy:
    bias: float
    weight_torque: float
    weight_force: float
    weight_yaw: float
    weight_yaw_rate: float
    weight_gap_margin: float
    weight_translation: float

    def target_overlap_reduction(self, design: Design, features):
        value = (
            self.bias
            + self.weight_torque * features["torque_intent"]
            + self.weight_force * features["force_intent"]
            + self.weight_yaw * features["yaw_ratio"]
            + self.weight_yaw_rate * features["yaw_rate_ratio"]
            - self.weight_gap_margin * features["gap_margin_ratio"]
            + self.weight_translation * features["translation_ratio"]
        )
        return design.max_overlap_reduction_m * float(sigmoid(value))


@dataclass(frozen=True)
class Scenario:
    name: str
    dt_s: float
    force_world_n: np.ndarray
    torque_nm: np.ndarray
    phase: np.ndarray


@dataclass
class Geometry:
    shape_name: str
    inner_points: np.ndarray
    inner_normals: np.ndarray
    inner_tangents: np.ndarray
    inner_ds: np.ndarray
    inner_support: np.ndarray
    inner_arc_fraction: np.ndarray
    inner_perimeter_m: float
    outer_points_local: np.ndarray
    outer_outward_normals_local: np.ndarray
    outer_inward_normals_local: np.ndarray
    outer_tangents_local: np.ndarray
    outer_arc_fraction: np.ndarray
    outer_perimeter_m: float
    max_radius_m: float
    yaw_contact_limit_rad: float
    translation_contact_limit_m: float
    base_gap_m: float
    beta: float


@dataclass
class CouplingSample:
    magnetic_force_body_n: np.ndarray
    outer_torque_nm: float
    inner_torque_nm: float
    min_gap_m: float
    contact_penetration_m: float
    contact_normal_body: np.ndarray
    inner_contact_point_body: np.ndarray
    outer_contact_point_body: np.ndarray
    mean_coverage_match: float
    mean_edge_overlap: float
    mean_cogging_ratio: float


@dataclass
class EpisodeResult:
    score: float
    contact_events: int
    latched: bool
    min_gap_m: float
    max_penetration_m: float
    translation_rms_m: float
    yaw_rms_rad: float
    turn_signal_ratio: float
    turn_latency_s: float
    recenter_s: float
    overlap_mean_m: float
    overlap_reduction_mean_m: float
    scenario_name: str
    leakage_factor: float
    drag_scale: float
    record: dict | None = None


MAGNET_CATALOG = [
    MagnetSKU(
        sku_id="DAISO_SUPER_13MM_4P",
        vendor="DAISO",
        product_name="超強力マグネット 4コ入 13 mm",
        source_url="https://jp.daisonet.com/products/4549131230475",
        source_date=CATALOG_DATE,
        tangential_length_m=0.013,
        axial_height_m=0.013,
        radial_depth_m=0.0024,
        unit_price_jpy=27.5,
        surface_flux_t=0.24,
        pull_force_n=0.0,
        mount_style="plain_disk",
        edge_reluctance=1.24,
        magnet_shape="disk",
        source_note=(
            "寸法・入数・販売価格は DAISO 公式通販ページを使用した。"
            "0.24 T の表面磁束密度は公開されているパッケージ表記（240 mT）を根拠に固定し、"
            "公式Web掲載に吸着力がないため pull force は未設定とした。"
        ),
    ),
    MagnetSKU(
        sku_id="MONO_NC103LTR",
        vendor="MonotaRO / MAGNA",
        product_name="ネオジム磁石 プレートキャッチ(角型) 1-NC103LTR",
        source_url="https://www.monotaro.com/g/08212606/",
        source_date=CATALOG_DATE,
        tangential_length_m=0.010,
        axial_height_m=0.010,
        radial_depth_m=0.003,
        unit_price_jpy=419.0,
        surface_flux_t=0.36,
        pull_force_n=19.03,
        mount_style="countersunk_plate",
        edge_reluctance=1.18,
    ),
    MagnetSKU(
        sku_id="MONO_NC104LTR",
        vendor="MonotaRO / MAGNA",
        product_name="ネオジム磁石 プレートキャッチ(角型) 1-NC104LTR",
        source_url="https://www.monotaro.com/g/08212606/",
        source_date=CATALOG_DATE,
        tangential_length_m=0.010,
        axial_height_m=0.010,
        radial_depth_m=0.004,
        unit_price_jpy=439.0,
        surface_flux_t=0.46,
        pull_force_n=21.38,
        mount_style="countersunk_plate",
        edge_reluctance=1.16,
    ),
    MagnetSKU(
        sku_id="MONO_NC15105LTR",
        vendor="MonotaRO / MAGNA",
        product_name="ネオジム磁石 プレートキャッチ(角型) 1-NC15105LTR",
        source_url="https://www.monotaro.com/g/08212606/",
        source_date=CATALOG_DATE,
        tangential_length_m=0.015,
        axial_height_m=0.010,
        radial_depth_m=0.005,
        unit_price_jpy=499.0,
        surface_flux_t=0.43,
        pull_force_n=33.34,
        mount_style="countersunk_plate",
        edge_reluctance=1.14,
    ),
    MagnetSKU(
        sku_id="MISUMI_1-4012104",
        vendor="MISUMI / MAGNA",
        product_name="ネオジム磁石 角型 1-4012104",
        source_url="https://jp.misumi-ec.com/vona2/detail/221000763876/",
        source_date=CATALOG_DATE,
        tangential_length_m=0.012,
        axial_height_m=0.010,
        radial_depth_m=0.004,
        unit_price_jpy=1400.0,
        surface_flux_t=0.33,
        pull_force_n=22.68,
        mount_style="plain_block",
        edge_reluctance=1.08,
    ),
    MagnetSKU(
        sku_id="MISUMI_1-4015105",
        vendor="MISUMI / MAGNA",
        product_name="ネオジム磁石 角型 1-4015105",
        source_url="https://jp.misumi-ec.com/vona2/detail/221000763876/",
        source_date=CATALOG_DATE,
        tangential_length_m=0.015,
        axial_height_m=0.010,
        radial_depth_m=0.005,
        unit_price_jpy=1310.0,
        surface_flux_t=0.35,
        pull_force_n=32.53,
        mount_style="plain_block",
        edge_reluctance=1.05,
    ),
    MagnetSKU(
        sku_id="MISUMI_1-4020105",
        vendor="MISUMI / MAGNA",
        product_name="ネオジム磁石 角型 1-4020105",
        source_url="https://jp.misumi-ec.com/vona2/detail/221000763876/",
        source_date=CATALOG_DATE,
        tangential_length_m=0.020,
        axial_height_m=0.010,
        radial_depth_m=0.005,
        unit_price_jpy=1730.0,
        surface_flux_t=0.32,
        pull_force_n=40.28,
        mount_style="plain_block",
        edge_reluctance=1.02,
    ),
    MagnetSKU(
        sku_id="MISUMI_1-40201010",
        vendor="MISUMI / MAGNA",
        product_name="ネオジム磁石 角型 1-40201010",
        source_url="https://jp.misumi-ec.com/vona2/detail/221000763876/",
        source_date=CATALOG_DATE,
        tangential_length_m=0.020,
        axial_height_m=0.010,
        radial_depth_m=0.010,
        unit_price_jpy=1834.0,
        surface_flux_t=0.46,
        pull_force_n=75.29,
        mount_style="plain_block",
        edge_reluctance=1.00,
    ),
]
MAGNET_CATALOG_BY_ID = {sku.sku_id: sku for sku in MAGNET_CATALOG}


def sigmoid(value):
    value = np.clip(value, -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-value))


def clamp(value, low, high):
    return max(low, min(high, value))


def clamp_norm(vector, limit):
    norm = np.linalg.norm(vector)
    if norm <= limit or norm <= 1.0e-12:
        return vector
    return vector * (limit / norm)


def rotmat(angle_rad):
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    return np.array([[c, -s], [s, c]], dtype=float)


def cross2(vector_a, vector_b):
    return vector_a[0] * vector_b[1] - vector_a[1] * vector_b[0]


def cross2_batch(vectors_a, vectors_b):
    return vectors_a[:, 0] * vectors_b[:, 1] - vectors_a[:, 1] * vectors_b[:, 0]


def wrap_angle(angle_rad):
    return math.atan2(math.sin(angle_rad), math.cos(angle_rad))


def periodic_centered_unit(value):
    return ((value + 0.5) % 1.0) - 0.5


def mean_phase_fraction(weights, phase_fraction):
    phase = 2.0 * math.pi * phase_fraction
    phase_complex = np.exp(1j * phase)
    averaged = weights @ phase_complex
    return (np.angle(averaged) / (2.0 * math.pi)) % 1.0


def superellipse_radius(theta, a_axis, b_axis, exponent):
    return (np.abs(np.cos(theta) / a_axis) ** exponent + np.abs(np.sin(theta) / b_axis) ** exponent) ** (
        -1.0 / exponent
    )


def polygon_radius(theta, sides, rotation_rad=0.0):
    wrapped = (theta + rotation_rad + math.pi / sides) % (2.0 * math.pi / sides) - math.pi / sides
    return math.cos(math.pi / sides) / np.cos(wrapped)


def shape_radius_profile(shape_name, theta):
    if shape_name == "ellipse_soft":
        radius = superellipse_radius(theta, a_axis=1.18, b_axis=0.86, exponent=2.0)
    elif shape_name == "ellipse_wide":
        radius = superellipse_radius(theta, a_axis=1.32, b_axis=0.78, exponent=2.0)
    elif shape_name == "squircle":
        radius = superellipse_radius(theta, a_axis=1.12, b_axis=0.90, exponent=4.8)
    elif shape_name == "rounded_rect":
        radius = superellipse_radius(theta, a_axis=1.30, b_axis=0.80, exponent=8.5)
    elif shape_name == "hexagon":
        radius = polygon_radius(theta, sides=6, rotation_rad=math.pi / 6.0)
    elif shape_name == "octagon":
        radius = polygon_radius(theta, sides=8, rotation_rad=math.pi / 8.0)
    else:
        raise ValueError(f"Unsupported shape: {shape_name}")

    mean_radius = float(np.mean(radius))
    return radius / mean_radius


def boundary_from_radius_profile(radius_profile, mean_radius_m):
    theta = np.linspace(0.0, 2.0 * math.pi, radius_profile.shape[0], endpoint=False)
    radius = mean_radius_m * radius_profile
    points = np.column_stack((radius * np.cos(theta), radius * np.sin(theta)))

    prev_points = np.roll(points, 1, axis=0)
    next_points = np.roll(points, -1, axis=0)
    tangent_vectors = next_points - prev_points
    tangent_norms = np.linalg.norm(tangent_vectors, axis=1, keepdims=True) + 1.0e-12
    tangents = tangent_vectors / tangent_norms
    normals = np.column_stack((tangents[:, 1], -tangents[:, 0]))
    radial_sign = np.sum(normals * points, axis=1)
    normals[radial_sign < 0.0] *= -1.0

    edge_vectors = np.roll(points, -1, axis=0) - points
    edge_lengths = np.linalg.norm(edge_vectors, axis=1)
    ds = 0.5 * (edge_lengths + np.roll(edge_lengths, 1))
    perimeter_m = float(np.sum(edge_lengths))
    arc_positions = np.concatenate(([0.0], np.cumsum(edge_lengths[:-1])))
    arc_fraction = arc_positions / max(perimeter_m, 1.0e-9)
    support = np.sum(normals * points, axis=1)

    return (
        points,
        normals,
        tangents,
        ds,
        support,
        arc_fraction,
        perimeter_m,
        float(np.max(np.linalg.norm(points, axis=1))),
    )


def build_geometry(shape_name, mean_radius_m, gap_m, num_samples):
    theta = np.linspace(0.0, 2.0 * math.pi, num_samples, endpoint=False)
    radius_profile = shape_radius_profile(shape_name, theta)
    (
        inner_points,
        inner_normals,
        inner_tangents,
        inner_ds,
        inner_support,
        inner_arc_fraction,
        inner_perimeter_m,
        max_radius_inner,
    ) = boundary_from_radius_profile(radius_profile, mean_radius_m)
    (
        outer_points,
        outer_normals,
        outer_tangents,
        _,
        _,
        outer_arc_fraction,
        outer_perimeter_m,
        max_radius_outer,
    ) = boundary_from_radius_profile(radius_profile, mean_radius_m + gap_m)
    outer_inward_normals = -outer_normals
    beta = SOFTMAX_SHARPNESS / max(mean_radius_m + gap_m, 1.0e-3)

    geometry = Geometry(
        shape_name=shape_name,
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
    geometry.translation_contact_limit_m = estimate_translation_limit_m(geometry)
    geometry.yaw_contact_limit_rad = estimate_yaw_limit_rad(geometry)
    return geometry


def soft_support_gap_profile(geometry: Geometry, relative_translation_body_m, relative_yaw_rad):
    rotation = rotmat(relative_yaw_rad)
    outer_points_world = geometry.outer_points_local @ rotation.T + relative_translation_body_m
    outer_normals_world = geometry.outer_inward_normals_local @ rotation.T
    outer_tangents_world = geometry.outer_tangents_local @ rotation.T

    dot_products = geometry.inner_normals @ outer_points_world.T
    scaled = geometry.beta * dot_products
    scaled -= np.max(scaled, axis=1, keepdims=True)
    weights = np.exp(scaled)
    weights /= np.sum(weights, axis=1, keepdims=True)

    support = np.sum(weights * dot_products, axis=1)
    contact_points = weights @ outer_points_world
    inward_normals = weights @ outer_normals_world
    inward_normals /= np.linalg.norm(inward_normals, axis=1, keepdims=True) + 1.0e-12
    contact_tangents = weights @ outer_tangents_world
    contact_tangents /= np.linalg.norm(contact_tangents, axis=1, keepdims=True) + 1.0e-12
    contact_arc_fraction = mean_phase_fraction(weights, geometry.outer_arc_fraction)
    gaps = support - geometry.inner_support
    alignment = np.clip(np.sum(geometry.inner_normals * inward_normals, axis=1), 0.0, 1.0)
    return gaps, alignment, contact_points, contact_arc_fraction, contact_tangents


def sat_signed_gap_profile(geometry: Geometry, relative_translation_body_m, relative_yaw_rad):
    rotation = rotmat(relative_yaw_rad)
    outer_points_world = geometry.outer_points_local @ rotation.T + relative_translation_body_m
    outer_outward_normals_world = geometry.outer_outward_normals_local @ rotation.T
    axes = np.vstack((geometry.inner_normals, outer_outward_normals_world))

    inner_projection = geometry.inner_points @ axes.T
    outer_projection = outer_points_world @ axes.T
    inner_max = np.max(inner_projection, axis=0)
    inner_min = np.min(inner_projection, axis=0)
    outer_max = np.max(outer_projection, axis=0)
    outer_min = np.min(outer_projection, axis=0)
    gap_positive = outer_max - inner_max
    gap_negative = inner_min - outer_min

    choose_positive = gap_positive <= gap_negative
    gap_axis = np.where(choose_positive, gap_positive, gap_negative)
    best_axis_index = int(np.argmin(gap_axis))
    best_gap_m = float(gap_axis[best_axis_index])

    if bool(choose_positive[best_axis_index]):
        best_normal = axes[best_axis_index]
        inner_index = int(np.argmax(inner_projection[:, best_axis_index]))
        outer_index = int(np.argmax(outer_projection[:, best_axis_index]))
    else:
        best_normal = -axes[best_axis_index]
        inner_index = int(np.argmin(inner_projection[:, best_axis_index]))
        outer_index = int(np.argmin(outer_projection[:, best_axis_index]))

    best_inner_point = geometry.inner_points[inner_index]
    best_outer_point = outer_points_world[outer_index]
    return best_gap_m, best_normal, best_inner_point, best_outer_point


def estimate_translation_limit_m(geometry: Geometry):
    low = 0.0
    high = geometry.base_gap_m * 1.6
    for _ in range(8):
        gap_value, _, _, _ = sat_signed_gap_profile(geometry, np.array([high, 0.0], dtype=float), 0.0)
        if gap_value <= 0.0:
            break
        high *= 1.45
    else:
        return high

    for _ in range(34):
        mid = 0.5 * (low + high)
        gap_value, _, _, _ = sat_signed_gap_profile(geometry, np.array([mid, 0.0], dtype=float), 0.0)
        if gap_value > 0.0:
            low = mid
        else:
            high = mid
    return low


def estimate_yaw_limit_rad(geometry: Geometry):
    low = 0.0
    high = 0.10
    for _ in range(12):
        gap_value, _, _, _ = sat_signed_gap_profile(geometry, np.zeros(2, dtype=float), high)
        if gap_value <= 0.0:
            break
        high *= 1.45
    else:
        return high

    for _ in range(34):
        mid = 0.5 * (low + high)
        gap_value, _, _, _ = sat_signed_gap_profile(geometry, np.zeros(2, dtype=float), mid)
        if gap_value > 0.0:
            low = mid
        else:
            high = mid
    return low


def magnet_coverage_profile(arc_fraction, design: Design, phase_offset_fraction):
    pitch_phase = (design.magnets_per_ring * arc_fraction + phase_offset_fraction) % 1.0
    centered = periodic_centered_unit(pitch_phase - 0.5)
    half_fill = 0.5 * design.coverage_ratio
    transition = max(0.015, 0.20 * (1.0 - design.coverage_ratio) + 0.008)
    distance = np.abs(centered)
    coverage = sigmoid((half_fill - distance) / transition)
    edge_strength = np.exp(-((distance - half_fill) / (2.2 * transition)) ** 2)
    return coverage, edge_strength, centered


def discrete_array_modulation(geometry: Geometry, design: Design, outer_contact_arc_fraction):
    inner_cov, inner_edge, inner_centered = magnet_coverage_profile(
        geometry.inner_arc_fraction,
        design,
        phase_offset_fraction=0.0,
    )
    outer_cov, outer_edge, outer_centered = magnet_coverage_profile(
        outer_contact_arc_fraction,
        design,
        phase_offset_fraction=design.outer_phase_fraction,
    )

    coverage_match = np.sqrt(np.clip(inner_cov * outer_cov, 0.0, 1.0))
    edge_overlap = np.sqrt(np.clip(inner_edge * outer_edge, 0.0, 1.0))
    phase_error = periodic_centered_unit(outer_centered - inner_centered)
    cogging_ratio = design.edge_cogging_gain * edge_overlap * np.sin(2.0 * math.pi * phase_error)
    return coverage_match, edge_overlap, cogging_ratio


def evaluate_coupling(geometry: Geometry, design: Design, relative_translation_body_m, relative_yaw_rad, overlap_m):
    (
        gaps,
        alignment,
        outer_contact_points,
        outer_contact_arc_fraction,
        _outer_contact_tangents,
    ) = soft_support_gap_profile(geometry, relative_translation_body_m, relative_yaw_rad)
    sat_gap_m, sat_normal, sat_inner_point, sat_outer_point = sat_signed_gap_profile(
        geometry, relative_translation_body_m, relative_yaw_rad
    )
    coverage_match, edge_overlap, cogging_ratio = discrete_array_modulation(
        geometry,
        design,
        outer_contact_arc_fraction,
    )

    effective_overlap_m = max(overlap_m, MIN_EFFECTIVE_OVERLAP_M)
    clipped_gap_m = np.maximum(gaps, 2.0e-4)
    magnetic_length_m = 1.65 * design.radial_depth_m
    base_flux_t = design.surface_flux_t * magnetic_length_m / (magnetic_length_m + clipped_gap_m)
    base_flux_t *= design.leakage_factor
    base_flux_t = np.minimum(base_flux_t, MAX_GAP_FLUX_T)

    coverage_floor = 0.07
    pressure_pa = (base_flux_t**2) / (2.0 * MU0)
    pressure_pa *= alignment**1.55
    pressure_pa *= coverage_floor + (1.0 - coverage_floor) * coverage_match
    pressure_pa *= 1.0 - 0.26 * (design.coverage_ratio < 0.75) * edge_overlap
    pressure_pa *= 1.0 / MAGNET_CATALOG_BY_ID[design.magnet_sku_id].edge_reluctance

    area_strip_m2 = effective_overlap_m * geometry.inner_ds
    normal_force_n = pressure_pa * area_strip_m2
    tangent_force_n = pressure_pa * area_strip_m2 * cogging_ratio
    force_vectors_body_n = (
        normal_force_n[:, None] * geometry.inner_normals + tangent_force_n[:, None] * geometry.inner_tangents
    )
    total_force_body_n = np.sum(force_vectors_body_n, axis=0)

    outer_torque_nm = float(
        np.sum(cross2_batch(outer_contact_points - relative_translation_body_m, force_vectors_body_n))
    )
    inner_torque_nm = float(np.sum(cross2_batch(geometry.inner_points, -force_vectors_body_n)))
    min_gap_m = float(min(np.min(gaps), sat_gap_m))
    contact_penetration_m = max(0.0, -sat_gap_m)

    return CouplingSample(
        magnetic_force_body_n=total_force_body_n,
        outer_torque_nm=outer_torque_nm,
        inner_torque_nm=inner_torque_nm,
        min_gap_m=min_gap_m,
        contact_penetration_m=contact_penetration_m,
        contact_normal_body=sat_normal,
        inner_contact_point_body=sat_inner_point,
        outer_contact_point_body=sat_outer_point,
        mean_coverage_match=float(np.mean(coverage_match)),
        mean_edge_overlap=float(np.mean(edge_overlap)),
        mean_cogging_ratio=float(np.mean(np.abs(cogging_ratio))),
    )


def cart_inertia_kgm2(mass_kg):
    return mass_kg * (CART_LENGTH_M**2 + CART_WIDTH_M**2) / 12.0


def robot_inertia_kgm2():
    return ROBOT_MASS_KG * (ROBOT_LENGTH_M**2 + ROBOT_WIDTH_M**2) / 12.0


def build_scenario(kind, seed, dt_s, duration_s=6.0):
    rng = np.random.default_rng(seed)
    steps = int(round(duration_s / dt_s))
    force_world = np.zeros((steps, 2), dtype=float)
    torque_nm = np.zeros(steps, dtype=float)
    phase = np.zeros(steps, dtype=int)

    def fill_segment(start_s, end_s, force_xy, torque_value, phase_value):
        start_i = int(round(start_s / dt_s))
        end_i = min(steps, int(round(end_s / dt_s)))
        force_world[start_i:end_i] = force_xy
        torque_nm[start_i:end_i] = torque_value
        phase[start_i:end_i] = phase_value

    forward_force = rng.uniform(18.0, 42.0)
    lateral_force = rng.uniform(8.0, 22.0)
    turn_torque = rng.uniform(7.0, 18.0)
    second_turn = rng.uniform(5.0, 14.0)
    heading = rng.uniform(-0.24, 0.24)
    force_dir = np.array([math.cos(heading), math.sin(heading)], dtype=float)
    side_dir = np.array([-force_dir[1], force_dir[0]], dtype=float)
    torque_sign = rng.choice([-1.0, 1.0])

    if kind == "translation_turn":
        fill_segment(0.5, 1.8, forward_force * force_dir, 0.0, 1)
        fill_segment(2.0, 3.3, np.zeros(2, dtype=float), torque_sign * turn_torque, 2)
        fill_segment(3.7, 4.9, 0.62 * forward_force * side_dir, 0.52 * torque_sign * second_turn, 3)
        fill_segment(5.2, 5.8, -0.18 * forward_force * force_dir, 0.0, 1)
    elif kind == "aggressive_turn":
        fill_segment(0.4, 1.2, 0.52 * forward_force * force_dir, 0.0, 1)
        fill_segment(1.3, 2.7, np.zeros(2, dtype=float), torque_sign * 1.18 * turn_torque, 2)
        fill_segment(3.0, 4.0, np.zeros(2, dtype=float), -torque_sign * second_turn, 2)
        fill_segment(4.2, 5.2, 0.40 * forward_force * force_dir, 0.44 * torque_sign * second_turn, 3)
    elif kind == "mixed_slalom":
        fill_segment(0.5, 1.5, forward_force * force_dir, 0.30 * torque_sign * turn_torque, 3)
        fill_segment(1.8, 2.7, 0.78 * forward_force * side_dir, -0.68 * torque_sign * turn_torque, 3)
        fill_segment(3.0, 3.9, 0.74 * forward_force * force_dir, 0.60 * torque_sign * second_turn, 3)
        fill_segment(4.3, 5.5, 0.50 * lateral_force * side_dir, -0.48 * torque_sign * second_turn, 3)
    elif kind == "contact_challenge":
        fill_segment(0.35, 1.05, 0.75 * forward_force * force_dir, 0.0, 1)
        fill_segment(1.1, 2.6, 0.40 * forward_force * force_dir, torque_sign * 1.30 * turn_torque, 3)
        fill_segment(2.7, 3.8, 1.05 * lateral_force * side_dir, torque_sign * 1.10 * second_turn, 3)
        fill_segment(4.1, 5.6, np.zeros(2, dtype=float), -torque_sign * 1.15 * turn_torque, 2)
    elif kind == "gentle_arc":
        fill_segment(0.4, 2.3, 0.85 * forward_force * force_dir, 0.55 * torque_sign * turn_torque, 3)
        fill_segment(2.6, 4.6, 0.75 * forward_force * force_dir, 0.30 * torque_sign * second_turn, 3)
        fill_segment(4.8, 5.6, 0.20 * forward_force * force_dir, 0.0, 1)
    elif kind == "reverse_correction":
        fill_segment(0.4, 1.4, -0.30 * forward_force * force_dir, -0.28 * torque_sign * second_turn, 1)
        fill_segment(1.8, 3.0, 0.50 * forward_force * force_dir, torque_sign * turn_torque, 2)
        fill_segment(3.2, 4.8, 0.32 * forward_force * side_dir, -0.72 * torque_sign * second_turn, 3)
    elif kind == "lateral_retarget":
        fill_segment(0.4, 1.3, 0.75 * lateral_force * side_dir, 0.0, 1)
        fill_segment(1.5, 2.8, 0.55 * forward_force * force_dir, torque_sign * 0.72 * turn_torque, 3)
        fill_segment(3.2, 4.4, 0.28 * forward_force * force_dir, -0.85 * torque_sign * second_turn, 2)
        fill_segment(4.7, 5.7, 0.45 * lateral_force * side_dir, 0.24 * torque_sign * second_turn, 3)
    elif kind == "stop_and_go_turn":
        fill_segment(0.3, 1.0, 0.60 * forward_force * force_dir, 0.0, 1)
        fill_segment(1.2, 2.6, np.zeros(2, dtype=float), torque_sign * 0.95 * turn_torque, 2)
        fill_segment(2.9, 4.0, 0.65 * forward_force * force_dir, torque_sign * 0.36 * second_turn, 3)
        fill_segment(4.2, 5.2, 0.35 * forward_force * side_dir, -0.42 * torque_sign * second_turn, 3)
    else:
        raise ValueError(f"Unsupported scenario kind: {kind}")

    return Scenario(
        name=f"{kind}_{seed}",
        dt_s=dt_s,
        force_world_n=force_world,
        torque_nm=torque_nm,
        phase=phase,
    )


def build_training_suite(base_seed, dt_s):
    scenario_plan = [
        ("translation_turn", 11),
        ("aggressive_turn", 29),
        ("mixed_slalom", 47),
        ("gentle_arc", 61),
        ("reverse_correction", 79),
        ("lateral_retarget", 97),
        ("stop_and_go_turn", 113),
        ("contact_challenge", 131),
    ]
    return [build_scenario(name, base_seed + offset, dt_s) for name, offset in scenario_plan]


def build_validation_suite(base_seed, dt_s):
    scenario_plan = [
        ("translation_turn", 211),
        ("aggressive_turn", 227),
        ("mixed_slalom", 241),
        ("gentle_arc", 257),
        ("lateral_retarget", 271),
        ("contact_challenge", 293),
    ]
    return [build_scenario(name, base_seed + offset, dt_s) for name, offset in scenario_plan]


def simulate_episode(design: Design, policy: Policy, geometry: Geometry, scenario: Scenario, drag_scale, record=False):
    dt_s = scenario.dt_s
    steps = scenario.force_world_n.shape[0]
    position_outer = np.zeros(2, dtype=float)
    velocity_outer = np.zeros(2, dtype=float)
    yaw_outer = 0.0
    yaw_rate_outer = 0.0

    position_inner = np.zeros(2, dtype=float)
    velocity_inner = np.zeros(2, dtype=float)
    yaw_inner = 0.0
    yaw_rate_inner = 0.0

    overlap_reduction_m = 0.0
    latched = False
    diverged = False
    contact_events = 0
    was_in_contact = False
    min_gap_m = float("inf")
    max_penetration_m = 0.0

    turn_signal_samples = []
    overlap_samples = []
    overlap_reduction_samples = []
    rel_translation_samples = []
    rel_yaw_samples = []
    coverage_samples = []
    cogging_samples = []

    records = {
        "time_s": [],
        "rel_x_m": [],
        "rel_y_m": [],
        "rel_yaw_rad": [],
        "min_gap_m": [],
        "overlap_m": [],
        "overlap_reduction_m": [],
        "force_mag_n": [],
        "torque_mag_nm": [],
        "coverage_match": [],
        "cogging_ratio": [],
        "phase": [],
    } if record else None

    cart_damping_n_s_m = 9.8 * drag_scale
    cart_yaw_damping_nms = 4.0 * drag_scale
    robot_damping_n_s_m = 10.5
    robot_yaw_damping_nms = 4.1
    follow_kp_n_m = 540.0
    follow_kd_n_s_m = 92.0
    follow_kp_yaw = 78.0
    follow_kd_yaw = 16.0
    follow_force_limit_n = 680.0
    follow_torque_limit_nm = 115.0

    cart_inertia = cart_inertia_kgm2(design.cart_mass_kg)
    robot_inertia = robot_inertia_kgm2()
    yaw_limit_rad = max(geometry.yaw_contact_limit_rad, 0.08)
    translation_limit_m = max(geometry.translation_contact_limit_m, 0.004)

    turn_active = np.abs(scenario.torque_nm) > 0.20 * max(1.0, float(np.max(np.abs(scenario.torque_nm))))
    turn_switch = np.diff(turn_active.astype(int), prepend=0)
    turn_rise_indices = list(np.where(turn_switch == 1)[0])
    turn_fall_indices = list(np.where(turn_switch == -1)[0])
    if turn_active[-1]:
        turn_fall_indices.append(steps - 1)

    for step in range(steps):
        if not all(
            np.isfinite(value)
            for value in (
                position_outer[0],
                position_outer[1],
                velocity_outer[0],
                velocity_outer[1],
                yaw_outer,
                yaw_rate_outer,
                position_inner[0],
                position_inner[1],
                velocity_inner[0],
                velocity_inner[1],
                yaw_inner,
                yaw_rate_inner,
                overlap_reduction_m,
            )
        ):
            diverged = True
            latched = True
            break

        relative_translation_world_m = position_outer - position_inner
        relative_rotation_world = rotmat(-yaw_inner)
        relative_translation_body_m = relative_rotation_world @ relative_translation_world_m
        relative_velocity_world = velocity_outer - velocity_inner
        relative_yaw_rad = wrap_angle(yaw_outer - yaw_inner)
        relative_yaw_rate = yaw_rate_outer - yaw_rate_inner

        coupling_preview = evaluate_coupling(
            geometry,
            design,
            relative_translation_body_m,
            relative_yaw_rad,
            design.nominal_overlap_m - overlap_reduction_m,
        )
        min_gap_m = min(min_gap_m, coupling_preview.min_gap_m)
        max_penetration_m = max(max_penetration_m, coupling_preview.contact_penetration_m)

        features = {
            "torque_intent": abs(scenario.torque_nm[step]) / 26.0,
            "force_intent": np.linalg.norm(scenario.force_world_n[step]) / 60.0,
            "yaw_ratio": abs(relative_yaw_rad) / yaw_limit_rad,
            "yaw_rate_ratio": abs(relative_yaw_rate) / 2.6,
            "gap_margin_ratio": coupling_preview.min_gap_m / max(design.gap_m, 1.0e-4),
            "translation_ratio": np.linalg.norm(relative_translation_body_m) / translation_limit_m,
        }

        h_target_m = policy.target_overlap_reduction(design, features)
        h_error_m = h_target_m - overlap_reduction_m
        max_change_m = design.actuator_rate_limit_mps * dt_s
        overlap_reduction_m += clamp(h_error_m / max(design.actuator_tau_s, 1.0e-3) * dt_s, -max_change_m, max_change_m)
        overlap_reduction_m = clamp(overlap_reduction_m, 0.0, design.max_overlap_reduction_m)
        overlap_m = max(design.nominal_overlap_m - overlap_reduction_m, MIN_EFFECTIVE_OVERLAP_M)

        coupling = evaluate_coupling(
            geometry,
            design,
            relative_translation_body_m,
            relative_yaw_rad,
            overlap_m,
        )
        min_gap_m = min(min_gap_m, coupling.min_gap_m)
        max_penetration_m = max(max_penetration_m, coupling.contact_penetration_m)

        magnetic_force_world_n = rotmat(yaw_inner) @ coupling.magnetic_force_body_n
        contact_force_world_n = np.zeros(2, dtype=float)
        contact_outer_torque_nm = 0.0
        contact_inner_torque_nm = 0.0
        if coupling.contact_penetration_m > 0.0:
            if not was_in_contact:
                contact_events += 1
            was_in_contact = True

            normal_world = rotmat(yaw_inner) @ coupling.contact_normal_body
            outer_contact_world = position_inner + rotmat(yaw_inner) @ coupling.outer_contact_point_body
            inner_contact_world = position_inner + rotmat(yaw_inner) @ coupling.inner_contact_point_body

            outer_radius_world = outer_contact_world - position_outer
            inner_radius_world = inner_contact_world - position_inner
            tangential_outer = np.array([-yaw_rate_outer * outer_radius_world[1], yaw_rate_outer * outer_radius_world[0]])
            tangential_inner = np.array([-yaw_rate_inner * inner_radius_world[1], yaw_rate_inner * inner_radius_world[0]])
            outer_contact_velocity = velocity_outer + tangential_outer
            inner_contact_velocity = velocity_inner + tangential_inner
            relative_contact_velocity = outer_contact_velocity - inner_contact_velocity
            normal_speed = float(np.dot(relative_contact_velocity, normal_world))
            tangential_speed = float(
                np.linalg.norm(relative_contact_velocity - normal_speed * normal_world)
            )

            normal_force_mag_n = (
                CONTACT_STIFFNESS_N_PER_M * coupling.contact_penetration_m
                + CONTACT_DAMPING_N_S_PER_M * max(-normal_speed, 0.0)
            )
            contact_force_world_n = normal_force_mag_n * normal_world
            contact_outer_torque_nm = cross2(outer_contact_world - position_outer, contact_force_world_n)
            contact_inner_torque_nm = cross2(inner_contact_world - position_inner, -contact_force_world_n)

            if (
                coupling.contact_penetration_m >= LATCH_PENETRATION_M
                and abs(normal_speed) <= LATCH_REL_SPEED_MPS
                and tangential_speed <= LATCH_TANGENTIAL_SPEED_MPS
            ):
                latched = True
                break
        else:
            was_in_contact = False

        follow_force_world_n = clamp_norm(
            follow_kp_n_m * (position_outer - position_inner) + follow_kd_n_s_m * (velocity_outer - velocity_inner),
            follow_force_limit_n,
        )
        follow_torque_nm = clamp(
            follow_kp_yaw * wrap_angle(yaw_outer - yaw_inner) + follow_kd_yaw * (yaw_rate_outer - yaw_rate_inner),
            -follow_torque_limit_nm,
            follow_torque_limit_nm,
        )

        force_outer_world_n = (
            scenario.force_world_n[step]
            + magnetic_force_world_n
            + contact_force_world_n
            - cart_damping_n_s_m * velocity_outer
        )
        torque_outer_nm = (
            scenario.torque_nm[step]
            + coupling.outer_torque_nm
            + contact_outer_torque_nm
            - cart_yaw_damping_nms * yaw_rate_outer
        )

        force_inner_world_n = (
            follow_force_world_n
            - magnetic_force_world_n
            - contact_force_world_n
            - robot_damping_n_s_m * velocity_inner
        )
        torque_inner_nm = (
            follow_torque_nm
            + coupling.inner_torque_nm
            + contact_inner_torque_nm
            - robot_yaw_damping_nms * yaw_rate_inner
        )

        acceleration_outer = force_outer_world_n / design.cart_mass_kg
        yaw_acc_outer = torque_outer_nm / cart_inertia
        acceleration_inner = force_inner_world_n / ROBOT_MASS_KG
        yaw_acc_inner = torque_inner_nm / robot_inertia

        velocity_outer += acceleration_outer * dt_s
        velocity_outer = clamp_norm(velocity_outer, MAX_LINEAR_SPEED_MPS)
        position_outer += velocity_outer * dt_s
        yaw_rate_outer += yaw_acc_outer * dt_s
        yaw_rate_outer = clamp(yaw_rate_outer, -MAX_YAW_RATE_RADPS, MAX_YAW_RATE_RADPS)
        yaw_outer = wrap_angle(yaw_outer + yaw_rate_outer * dt_s)

        velocity_inner += acceleration_inner * dt_s
        velocity_inner = clamp_norm(velocity_inner, MAX_LINEAR_SPEED_MPS)
        position_inner += velocity_inner * dt_s
        yaw_rate_inner += yaw_acc_inner * dt_s
        yaw_rate_inner = clamp(yaw_rate_inner, -MAX_YAW_RATE_RADPS, MAX_YAW_RATE_RADPS)
        yaw_inner = wrap_angle(yaw_inner + yaw_rate_inner * dt_s)

        relative_translation_body_m = rotmat(-yaw_inner) @ (position_outer - position_inner)
        relative_yaw_rad = wrap_angle(yaw_outer - yaw_inner)
        if (
            np.linalg.norm(relative_translation_body_m) > MAX_RELATIVE_TRANSLATION_M
            or abs(relative_yaw_rad) > MAX_RELATIVE_YAW_RAD
        ):
            diverged = True
            latched = True
            break

        rel_translation_samples.append(float(np.linalg.norm(relative_translation_body_m)))
        rel_yaw_samples.append(float(relative_yaw_rad))
        overlap_samples.append(float(overlap_m))
        overlap_reduction_samples.append(float(overlap_reduction_m))
        coverage_samples.append(coupling.mean_coverage_match)
        cogging_samples.append(coupling.mean_cogging_ratio)

        if turn_active[step]:
            signal_ratio = abs(relative_yaw_rad) / max(0.52 * yaw_limit_rad, 1.0e-6)
            turn_signal_samples.append(min(signal_ratio, 1.40))

        if record:
            records["time_s"].append(step * dt_s)
            records["rel_x_m"].append(float(relative_translation_body_m[0]))
            records["rel_y_m"].append(float(relative_translation_body_m[1]))
            records["rel_yaw_rad"].append(float(relative_yaw_rad))
            records["min_gap_m"].append(float(coupling.min_gap_m))
            records["overlap_m"].append(float(overlap_m))
            records["overlap_reduction_m"].append(float(overlap_reduction_m))
            records["force_mag_n"].append(float(np.linalg.norm(coupling.magnetic_force_body_n)))
            records["torque_mag_nm"].append(float(abs(coupling.outer_torque_nm)))
            records["coverage_match"].append(float(coupling.mean_coverage_match))
            records["cogging_ratio"].append(float(coupling.mean_cogging_ratio))
            records["phase"].append(int(scenario.phase[step]))

    translation_rms_m = float(np.sqrt(np.mean(np.square(rel_translation_samples)))) if rel_translation_samples else 0.0
    yaw_rms_rad = float(np.sqrt(np.mean(np.square(rel_yaw_samples)))) if rel_yaw_samples else 0.0
    turn_signal_ratio = float(np.mean(turn_signal_samples)) if turn_signal_samples else 0.0
    overlap_mean_m = float(np.mean(overlap_samples)) if overlap_samples else design.nominal_overlap_m
    overlap_reduction_mean_m = float(np.mean(overlap_reduction_samples)) if overlap_reduction_samples else 0.0
    coverage_mean = float(np.mean(coverage_samples)) if coverage_samples else 0.0
    cogging_mean = float(np.mean(cogging_samples)) if cogging_samples else 0.0

    target_turn_ratio = 0.63
    turn_signal_quality = math.exp(-((turn_signal_ratio - target_turn_ratio) / 0.20) ** 2)

    latency_measurements = []
    for rise_index in turn_rise_indices:
        window_end = min(steps, rise_index + int(round(1.6 / dt_s)))
        latency = 1.6
        for idx in range(rise_index, window_end):
            if idx < len(rel_yaw_samples) and abs(rel_yaw_samples[idx]) >= 0.55 * yaw_limit_rad:
                latency = (idx - rise_index) * dt_s
                break
        latency_measurements.append(latency)
    turn_latency_s = float(np.mean(latency_measurements)) if latency_measurements else 0.0

    recenter_measurements = []
    for fall_index in turn_fall_indices:
        window_end = min(len(rel_yaw_samples), fall_index + int(round(1.8 / dt_s)))
        recenter = 1.8
        for idx in range(fall_index, window_end):
            if abs(rel_yaw_samples[idx]) <= 0.16 * yaw_limit_rad:
                recenter = (idx - fall_index) * dt_s
                break
        recenter_measurements.append(recenter)
    recenter_s = float(np.mean(recenter_measurements)) if recenter_measurements else 0.0

    margin_ratio = min_gap_m / max(design.gap_m, 1.0e-4)
    score = 0.0
    score += 520.0 * turn_signal_quality
    score -= 420.0 * max(0.30 - turn_signal_ratio, 0.0)
    score -= 95.0 * turn_latency_s
    score -= 42.0 * recenter_s
    score -= 78.0 * (translation_rms_m / translation_limit_m) ** 2
    score -= 36.0 * (yaw_rms_rad / yaw_limit_rad) ** 2
    score -= 22.0 * (overlap_reduction_mean_m / max(design.max_overlap_reduction_m, 1.0e-4))
    score -= 32.0 * max(0.24 - margin_ratio, 0.0) ** 2
    score -= 44.0 * max(0.32 - coverage_mean, 0.0)
    score -= 24.0 * cogging_mean
    score -= 840.0 * contact_events
    score -= 2600.0 * float(latched)
    score -= 120000.0 * max_penetration_m
    if latched:
        score -= 1100.0
    if diverged:
        score -= 1500.0

    return EpisodeResult(
        score=score,
        contact_events=contact_events,
        latched=latched,
        min_gap_m=min_gap_m,
        max_penetration_m=max_penetration_m,
        translation_rms_m=translation_rms_m,
        yaw_rms_rad=yaw_rms_rad,
        turn_signal_ratio=turn_signal_ratio,
        turn_latency_s=turn_latency_s,
        recenter_s=recenter_s,
        overlap_mean_m=overlap_mean_m,
        overlap_reduction_mean_m=overlap_reduction_mean_m,
        scenario_name=scenario.name,
        leakage_factor=design.leakage_factor,
        drag_scale=drag_scale,
        record=records,
    )


def choose_catalog_sku(selector_value):
    index = int(clamp(round(selector_value * (len(MAGNET_CATALOG) - 1)), 0, len(MAGNET_CATALOG) - 1))
    return MAGNET_CATALOG[index]


def signed(low, high, value):
    return low + (high - low) * value


def materialize_design(shape_name, latent_vector, num_samples):
    bounded = sigmoid(latent_vector)
    gap_m = 0.010 + 0.026 * bounded[0]
    mean_radius_m = 0.090 + 0.100 * bounded[1]
    geometry = build_geometry(shape_name, mean_radius_m, gap_m, num_samples)

    sku = choose_catalog_sku(bounded[2])
    magnet_layers = int(clamp(round(2.0 + 6.0 * bounded[3]), 2, 8))
    nominal_overlap_m = magnet_layers * sku.axial_height_m
    max_overlap_ratio = 0.12 + 0.42 * bounded[4]
    cart_mass_kg = 24.0 + 96.0 * bounded[5]
    actuator_tau_s = 0.08 + 0.28 * bounded[6]
    actuator_rate_limit_mps = 0.015 + 0.110 * bounded[7]
    target_fill_ratio = 0.58 + 0.28 * bounded[8]
    outer_phase_fraction = signed(-0.32, 0.32, bounded[9])
    edge_cogging_gain = 0.18 + 0.92 * bounded[10]

    mounting_clearance_m = 0.0014 if "countersunk" in sku.mount_style else 0.0010
    max_count = max(6, int(geometry.inner_perimeter_m / max(sku.tangential_length_m + mounting_clearance_m, 1.0e-3)))
    target_count = int(round(target_fill_ratio * geometry.inner_perimeter_m / max(sku.tangential_length_m, 1.0e-3)))
    magnets_per_ring = int(clamp(target_count, 6, max_count))
    pitch_m = geometry.inner_perimeter_m / magnets_per_ring
    actual_fill_ratio = min(0.94, sku.tangential_length_m / max(pitch_m, 1.0e-6))
    tangential_gap_m = max(0.0, pitch_m - sku.tangential_length_m)
    total_magnets = 2 * magnet_layers * magnets_per_ring
    estimated_total_cost_jpy = total_magnets * sku.unit_price_jpy

    design = Design(
        shape_name=shape_name,
        gap_m=gap_m,
        mean_radius_m=mean_radius_m,
        radial_depth_m=sku.radial_depth_m,
        nominal_overlap_m=nominal_overlap_m,
        max_overlap_reduction_m=nominal_overlap_m * max_overlap_ratio,
        cart_mass_kg=cart_mass_kg,
        actuator_tau_s=actuator_tau_s,
        actuator_rate_limit_mps=actuator_rate_limit_mps,
        leakage_factor=0.12,
        magnet_sku_id=sku.sku_id,
        magnet_vendor=sku.vendor,
        unit_price_jpy=sku.unit_price_jpy,
        magnet_tangential_length_m=sku.tangential_length_m,
        magnet_axial_height_m=sku.axial_height_m,
        magnets_per_ring=magnets_per_ring,
        magnet_layers=magnet_layers,
        coverage_ratio=actual_fill_ratio,
        pitch_m=pitch_m,
        tangential_gap_m=tangential_gap_m,
        outer_phase_fraction=outer_phase_fraction,
        edge_cogging_gain=edge_cogging_gain,
        total_magnets=total_magnets,
        estimated_total_cost_jpy=estimated_total_cost_jpy,
        surface_flux_t=sku.surface_flux_t,
        pull_force_n=sku.pull_force_n,
    )

    policy = Policy(
        bias=signed(-3.2, 1.4, bounded[11]),
        weight_torque=signed(0.8, 7.0, bounded[12]),
        weight_force=signed(-4.2, 1.2, bounded[13]),
        weight_yaw=signed(0.2, 4.8, bounded[14]),
        weight_yaw_rate=signed(0.2, 3.6, bounded[15]),
        weight_gap_margin=signed(0.6, 5.8, bounded[16]),
        weight_translation=signed(-3.2, 1.6, bounded[17]),
    )
    return design, policy, geometry


def evaluate_candidate(shape_name, latent_vector, scenarios, num_samples, robust_seed):
    base_design, policy, geometry = materialize_design(shape_name, latent_vector, num_samples)
    robust_rng = np.random.default_rng(robust_seed)

    episode_results = []
    for scenario in scenarios:
        leakage_factor = robust_rng.uniform(0.095, 0.145)
        drag_scale = robust_rng.uniform(0.88, 1.14)
        phase_shift = robust_rng.normal(0.0, 0.016)
        design = Design(
            shape_name=base_design.shape_name,
            gap_m=base_design.gap_m,
            mean_radius_m=base_design.mean_radius_m,
            radial_depth_m=base_design.radial_depth_m,
            nominal_overlap_m=base_design.nominal_overlap_m,
            max_overlap_reduction_m=base_design.max_overlap_reduction_m,
            cart_mass_kg=base_design.cart_mass_kg,
            actuator_tau_s=base_design.actuator_tau_s,
            actuator_rate_limit_mps=base_design.actuator_rate_limit_mps,
            leakage_factor=leakage_factor,
            magnet_sku_id=base_design.magnet_sku_id,
            magnet_vendor=base_design.magnet_vendor,
            unit_price_jpy=base_design.unit_price_jpy,
            magnet_tangential_length_m=base_design.magnet_tangential_length_m,
            magnet_axial_height_m=base_design.magnet_axial_height_m,
            magnets_per_ring=base_design.magnets_per_ring,
            magnet_layers=base_design.magnet_layers,
            coverage_ratio=clamp(base_design.coverage_ratio + robust_rng.normal(0.0, 0.02), 0.48, 0.95),
            pitch_m=base_design.pitch_m,
            tangential_gap_m=max(0.0, base_design.tangential_gap_m + robust_rng.normal(0.0, 0.00035)),
            outer_phase_fraction=base_design.outer_phase_fraction + phase_shift,
            edge_cogging_gain=max(0.05, base_design.edge_cogging_gain * robust_rng.uniform(0.92, 1.08)),
            total_magnets=base_design.total_magnets,
            estimated_total_cost_jpy=base_design.estimated_total_cost_jpy,
            surface_flux_t=base_design.surface_flux_t,
            pull_force_n=base_design.pull_force_n,
        )
        episode_results.append(
            simulate_episode(
                design=design,
                policy=policy,
                geometry=geometry,
                scenario=scenario,
                drag_scale=drag_scale,
                record=False,
            )
        )

    scores = np.array([episode.score for episode in episode_results], dtype=float)
    yaw_limit_target_rad = math.radians(26.0)
    yaw_limit_ratio = max(geometry.yaw_contact_limit_rad, 1.0e-3) / yaw_limit_target_rad
    yaw_window_penalty = 540.0 * (math.log(yaw_limit_ratio) ** 2)
    cost_penalty = 0.020 * base_design.estimated_total_cost_jpy
    assembly_penalty = 2.2 * math.sqrt(base_design.total_magnets)
    gap_density_penalty = 480.0 * max(0.0016 - base_design.tangential_gap_m, 0.0) / 0.0016

    penalties = (
        0.35 * np.std(scores)
        + 1400.0 * sum(episode.latched for episode in episode_results)
        + 220.0 * sum(episode.contact_events for episode in episode_results)
        + yaw_window_penalty
        + cost_penalty
        + assembly_penalty
        + gap_density_penalty
    )
    aggregate_score = float(np.mean(scores) - penalties)
    return {
        "shape_name": shape_name,
        "score": aggregate_score,
        "geometry": geometry,
        "design": base_design,
        "policy": policy,
        "episodes": episode_results,
    }


def optimize_shape(shape_name, scenarios, seed, generations, population, elite_count, num_samples):
    rng = np.random.default_rng(seed)
    dimension = 18
    mean = np.zeros(dimension, dtype=float)
    std = np.ones(dimension, dtype=float) * 1.20
    history_rows = []
    best_aggregate = None
    no_improve = 0

    for generation in range(generations):
        latent_population = mean + std * rng.standard_normal((population, dimension))
        aggregates = []
        for index in range(population):
            aggregate = evaluate_candidate(
                shape_name=shape_name,
                latent_vector=latent_population[index],
                scenarios=scenarios,
                num_samples=num_samples,
                robust_seed=seed + generation * 409 + index * 17,
            )
            aggregate["latent_vector"] = latent_population[index]
            aggregates.append(aggregate)

        aggregates.sort(key=lambda item: item["score"], reverse=True)
        elites = aggregates[:elite_count]
        elite_vectors = np.stack([item["latent_vector"] for item in elites], axis=0)

        mean = 0.28 * mean + 0.72 * np.mean(elite_vectors, axis=0)
        std = 0.34 * std + 0.66 * np.std(elite_vectors, axis=0)
        std = np.maximum(std, 0.085)

        generation_best = aggregates[0]
        if best_aggregate is None or generation_best["score"] > best_aggregate["score"]:
            best_aggregate = generation_best
            no_improve = 0
        else:
            no_improve += 1

        history_rows.append(
            {
                "shape_name": shape_name,
                "generation": generation,
                "best_score": generation_best["score"],
                "mean_score": float(np.mean([item["score"] for item in aggregates])),
                "std_score": float(np.std([item["score"] for item in aggregates])),
                "global_best_score": best_aggregate["score"],
                "gap_m": generation_best["design"].gap_m,
                "mean_radius_m": generation_best["design"].mean_radius_m,
                "nominal_overlap_m": generation_best["design"].nominal_overlap_m,
                "max_overlap_reduction_m": generation_best["design"].max_overlap_reduction_m,
                "cart_mass_kg": generation_best["design"].cart_mass_kg,
                "magnet_sku_id": generation_best["design"].magnet_sku_id,
                "magnets_per_ring": generation_best["design"].magnets_per_ring,
                "magnet_layers": generation_best["design"].magnet_layers,
                "estimated_total_cost_jpy": generation_best["design"].estimated_total_cost_jpy,
            }
        )

        if no_improve >= 4 and float(np.mean(std)) < 0.22:
            break

    return best_aggregate, pd.DataFrame(history_rows)


def validate_design(best_aggregate, validation_scenarios, coarse_samples, refined_samples, seed):
    base_design = best_aggregate["design"]
    policy = best_aggregate["policy"]
    coarse_geometry = build_geometry(base_design.shape_name, base_design.mean_radius_m, base_design.gap_m, coarse_samples)
    refined_geometry = build_geometry(
        base_design.shape_name,
        base_design.mean_radius_m,
        base_design.gap_m,
        refined_samples,
    )

    rng = np.random.default_rng(seed)
    coarse_results = []
    refined_results = []
    for scenario in validation_scenarios:
        leakage_factor = rng.uniform(0.095, 0.145)
        drag_scale = rng.uniform(0.88, 1.14)
        phase_shift = rng.normal(0.0, 0.016)
        design = Design(
            shape_name=base_design.shape_name,
            gap_m=base_design.gap_m,
            mean_radius_m=base_design.mean_radius_m,
            radial_depth_m=base_design.radial_depth_m,
            nominal_overlap_m=base_design.nominal_overlap_m,
            max_overlap_reduction_m=base_design.max_overlap_reduction_m,
            cart_mass_kg=base_design.cart_mass_kg,
            actuator_tau_s=base_design.actuator_tau_s,
            actuator_rate_limit_mps=base_design.actuator_rate_limit_mps,
            leakage_factor=leakage_factor,
            magnet_sku_id=base_design.magnet_sku_id,
            magnet_vendor=base_design.magnet_vendor,
            unit_price_jpy=base_design.unit_price_jpy,
            magnet_tangential_length_m=base_design.magnet_tangential_length_m,
            magnet_axial_height_m=base_design.magnet_axial_height_m,
            magnets_per_ring=base_design.magnets_per_ring,
            magnet_layers=base_design.magnet_layers,
            coverage_ratio=clamp(base_design.coverage_ratio + rng.normal(0.0, 0.02), 0.48, 0.95),
            pitch_m=base_design.pitch_m,
            tangential_gap_m=max(0.0, base_design.tangential_gap_m + rng.normal(0.0, 0.00035)),
            outer_phase_fraction=base_design.outer_phase_fraction + phase_shift,
            edge_cogging_gain=max(0.05, base_design.edge_cogging_gain * rng.uniform(0.92, 1.08)),
            total_magnets=base_design.total_magnets,
            estimated_total_cost_jpy=base_design.estimated_total_cost_jpy,
            surface_flux_t=base_design.surface_flux_t,
            pull_force_n=base_design.pull_force_n,
        )
        coarse_results.append(
            simulate_episode(design, policy, coarse_geometry, scenario, drag_scale, record=False)
        )
        refined_results.append(
            simulate_episode(design, policy, refined_geometry, scenario, drag_scale, record=True)
        )
    return coarse_geometry, refined_geometry, coarse_results, refined_results


def report_dataframe(results):
    return pd.DataFrame(
        [
            {
                "scenario_name": result.scenario_name,
                "score": result.score,
                "contact_events": result.contact_events,
                "latched": int(result.latched),
                "min_gap_mm": 1000.0 * result.min_gap_m,
                "max_penetration_mm": 1000.0 * result.max_penetration_m,
                "translation_rms_mm": 1000.0 * result.translation_rms_m,
                "yaw_rms_deg": math.degrees(result.yaw_rms_rad),
                "turn_signal_ratio": result.turn_signal_ratio,
                "turn_latency_s": result.turn_latency_s,
                "recenter_s": result.recenter_s,
                "overlap_mean_mm": 1000.0 * result.overlap_mean_m,
                "overlap_reduction_mean_mm": 1000.0 * result.overlap_reduction_mean_m,
                "leakage_factor": result.leakage_factor,
                "drag_scale": result.drag_scale,
            }
            for result in results
        ]
    )


def plot_convergence(history_df, outdir: Path):
    figure, axis = plt.subplots(figsize=(9.0, 5.0))
    for shape_name, group in history_df.groupby("shape_name"):
        axis.plot(group["generation"], group["global_best_score"], label=f"{shape_name} best", linewidth=2.1)
        axis.plot(group["generation"], group["mean_score"], label=f"{shape_name} mean", linewidth=1.0, alpha=0.55)
    axis.set_xlabel("Generation")
    axis.set_ylabel("Score")
    axis.set_title("Discrete Magnet Array CEM-RL Convergence")
    axis.grid(True, alpha=0.25)
    axis.legend(ncol=2, fontsize=8)
    figure.tight_layout()
    figure.savefig(outdir / "convergence.png", dpi=180)
    plt.close(figure)


def plot_rollout(best_result: EpisodeResult, yaw_limit_rad, translation_limit_m, outdir: Path):
    record = best_result.record
    if record is None:
        return

    time_s = np.array(record["time_s"], dtype=float)
    rel_xy = np.sqrt(np.square(record["rel_x_m"]) + np.square(record["rel_y_m"]))
    rel_yaw_deg = np.degrees(record["rel_yaw_rad"])
    min_gap_mm = 1000.0 * np.array(record["min_gap_m"], dtype=float)
    overlap_mm = 1000.0 * np.array(record["overlap_m"], dtype=float)
    reduction_mm = 1000.0 * np.array(record["overlap_reduction_m"], dtype=float)
    coverage = np.array(record["coverage_match"], dtype=float)
    cogging = np.array(record["cogging_ratio"], dtype=float)

    figure, axes = plt.subplots(5, 1, figsize=(10.2, 12.1), sharex=True)
    axes[0].plot(time_s, 1000.0 * rel_xy, color="#0f766e", linewidth=2.0)
    axes[0].axhline(1000.0 * translation_limit_m, color="#b91c1c", linestyle="--", linewidth=1.2)
    axes[0].set_ylabel("Rel. XY [mm]")
    axes[0].grid(True, alpha=0.24)

    axes[1].plot(time_s, rel_yaw_deg, color="#1d4ed8", linewidth=2.0)
    axes[1].axhline(math.degrees(yaw_limit_rad), color="#b91c1c", linestyle="--", linewidth=1.2)
    axes[1].axhline(-math.degrees(yaw_limit_rad), color="#b91c1c", linestyle="--", linewidth=1.2)
    axes[1].set_ylabel("Rel. Yaw [deg]")
    axes[1].grid(True, alpha=0.24)

    axes[2].plot(time_s, min_gap_mm, color="#9333ea", linewidth=2.0)
    axes[2].axhline(0.0, color="#b91c1c", linestyle="--", linewidth=1.2)
    axes[2].set_ylabel("Min Gap [mm]")
    axes[2].grid(True, alpha=0.24)

    axes[3].plot(time_s, overlap_mm, color="#f59e0b", linewidth=2.0, label="effective overlap")
    axes[3].plot(time_s, reduction_mm, color="#475569", linewidth=1.4, label="height reduction")
    axes[3].set_ylabel("Overlap [mm]")
    axes[3].grid(True, alpha=0.24)
    axes[3].legend(loc="upper right", fontsize=8)

    axes[4].plot(time_s, coverage, color="#15803d", linewidth=2.0, label="coverage match")
    axes[4].plot(time_s, cogging, color="#c2410c", linewidth=1.6, label="edge cogging")
    axes[4].set_ylabel("Discrete Effects")
    axes[4].set_xlabel("Time [s]")
    axes[4].grid(True, alpha=0.24)
    axes[4].legend(loc="upper right", fontsize=8)

    figure.suptitle(f"Best Validation Rollout: {best_result.scenario_name}")
    figure.tight_layout()
    figure.savefig(outdir / "best_rollout.png", dpi=180)
    plt.close(figure)


def write_catalog(outdir: Path):
    catalog_df = pd.DataFrame([asdict(sku) for sku in MAGNET_CATALOG])
    catalog_df["tangential_length_mm"] = 1000.0 * catalog_df["tangential_length_m"]
    catalog_df["axial_height_mm"] = 1000.0 * catalog_df["axial_height_m"]
    catalog_df["radial_depth_mm"] = 1000.0 * catalog_df["radial_depth_m"]
    catalog_df.to_csv(outdir / "magnet_catalog.csv", index=False)

    lines = [
        "# Japan-Available Magnet Catalog Snapshot",
        "",
        f"- Snapshot date: `{CATALOG_DATE}`",
        "- Catalog is intentionally restricted to low-cost, Japan-purchasable neodymium products that can plausibly be arrayed around a perimeter.",
        "",
    ]
    for sku in MAGNET_CATALOG:
        lines.append(f"## {sku.sku_id}")
        lines.append(f"- Vendor: `{sku.vendor}`")
        lines.append(f"- Product: `{sku.product_name}`")
        lines.append(
            f"- Geometry: `{1000.0 * sku.tangential_length_m:.0f} x {1000.0 * sku.axial_height_m:.0f} x {1000.0 * sku.radial_depth_m:.0f} mm`"
        )
        lines.append(f"- Unit price: `{sku.unit_price_jpy:.0f} JPY`")
        lines.append(f"- Surface flux: `{sku.surface_flux_t:.2f} T`")
        lines.append(f"- Pull force: `{sku.pull_force_n:.2f} N`")
        lines.append(f"- Source: {sku.source_url}")
        lines.append("")
    (outdir / "catalog_sources.md").write_text("\n".join(lines), encoding="utf-8")


def write_summary(best_shape, best_aggregate, refined_geometry, coarse_results, refined_results, outdir: Path):
    best_design = best_aggregate["design"]
    best_policy = best_aggregate["policy"]
    best_sku = MAGNET_CATALOG_BY_ID[best_design.magnet_sku_id]
    coarse_df = report_dataframe(coarse_results)
    refined_df = report_dataframe(refined_results)

    summary = {
        "selected_shape": best_shape,
        "design": asdict(best_design),
        "policy": asdict(best_policy),
        "selected_sku": asdict(best_sku),
        "geometry": {
            "yaw_contact_limit_deg": math.degrees(refined_geometry.yaw_contact_limit_rad),
            "translation_contact_limit_mm": 1000.0 * refined_geometry.translation_contact_limit_m,
            "inner_perimeter_mm": 1000.0 * refined_geometry.inner_perimeter_m,
        },
        "validation": {
            "mean_score": float(refined_df["score"].mean()),
            "worst_score": float(refined_df["score"].min()),
            "contact_events_total": int(refined_df["contact_events"].sum()),
            "latched_total": int(refined_df["latched"].sum()),
            "worst_min_gap_mm": float(refined_df["min_gap_mm"].min()),
            "worst_penetration_mm": float(refined_df["max_penetration_mm"].max()),
            "mean_turn_latency_s": float(refined_df["turn_latency_s"].mean()),
            "mean_recenter_s": float(refined_df["recenter_s"].mean()),
            "mean_turn_signal_ratio": float(refined_df["turn_signal_ratio"].mean()),
        },
    }
    (outdir / "best_design.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# Discrete Magnetic Coupler RL Optimization Report",
        "",
        "## Selected Design",
        f"- Shape: `{best_shape}`",
        f"- Selected SKU: `{best_design.magnet_sku_id}`",
        f"- Vendor: `{best_design.magnet_vendor}`",
        f"- Gap `s`: `{1000.0 * best_design.gap_m:.2f} mm`",
        f"- Mean radius: `{1000.0 * best_design.mean_radius_m:.1f} mm`",
        f"- Magnet dimensions (tangential x axial x radial): `{1000.0 * best_design.magnet_tangential_length_m:.0f} x {1000.0 * best_design.magnet_axial_height_m:.0f} x {1000.0 * best_design.radial_depth_m:.0f} mm`",
        f"- Magnets per ring: `{best_design.magnets_per_ring}`",
        f"- Vertical layers per ring: `{best_design.magnet_layers}`",
        f"- Total magnets: `{best_design.total_magnets}`",
        f"- Estimated magnet-only cost: `{best_design.estimated_total_cost_jpy:.0f} JPY`",
        f"- Tangential gap between magnets: `{1000.0 * best_design.tangential_gap_m:.2f} mm`",
        f"- Coverage ratio: `{best_design.coverage_ratio:.3f}`",
        f"- Outer array phase offset: `{best_design.outer_phase_fraction:.3f}` pitch",
        f"- Nominal overlap height: `{1000.0 * best_design.nominal_overlap_m:.1f} mm`",
        f"- Max overlap reduction: `{1000.0 * best_design.max_overlap_reduction_m:.1f} mm`",
        f"- Cart mass `m`: `{best_design.cart_mass_kg:.1f} kg`",
        f"- Estimated yaw contact limit: `{math.degrees(refined_geometry.yaw_contact_limit_rad):.2f} deg`",
        f"- Estimated translation contact limit: `{1000.0 * refined_geometry.translation_contact_limit_m:.2f} mm`",
        "",
        "## Validation",
        f"- Mean validation score: `{refined_df['score'].mean():.2f}`",
        f"- Worst-case score: `{refined_df['score'].min():.2f}`",
        f"- Total contact events: `{int(refined_df['contact_events'].sum())}`",
        f"- Total latched failures: `{int(refined_df['latched'].sum())}`",
        f"- Worst minimum clearance: `{refined_df['min_gap_mm'].min():.2f} mm`",
        f"- Worst penetration: `{refined_df['max_penetration_mm'].max():.3f} mm`",
        f"- Mean turn latency: `{refined_df['turn_latency_s'].mean():.3f} s`",
        f"- Mean recenter time: `{refined_df['recenter_s'].mean():.3f} s`",
        f"- Mean turn signal ratio: `{refined_df['turn_signal_ratio'].mean():.3f}`",
        "",
        "## Model Notes",
        "- Continuous ring magnets were replaced by finite, purchasable rectangular/countersunk neodymium modules.",
        "- Local magnetic pressure now depends on discrete magnet coverage, finite inter-magnet gaps, and an edge-cogging term.",
        "- The optimizer jointly chooses shape, magnet SKU, count per ring, vertical stack layers, phase offset, gap, mass, and height-control law.",
        "- Training uses only common-sense human push/turn inputs, but spans forward push, slalom, lateral correction, hesitation, reverse correction, and contact-challenge cases.",
        "- This remains a reduced-order design simulator rather than full 3D FEA, so the outputs should be treated as screening guidance.",
    ]
    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Discrete Japanese-market magnet array simulator and CEM-RL design optimizer."
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--generations", type=int, default=10)
    parser.add_argument("--population", type=int, default=12)
    parser.add_argument("--elite-count", type=int, default=4)
    parser.add_argument("--dt", type=float, default=0.03)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--refined-samples", type=int, default=96)
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("outputs") / "magnetic_coupler_rl",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    write_catalog(args.outdir)

    training_scenarios = build_training_suite(args.seed, args.dt)
    validation_scenarios = build_validation_suite(args.seed, args.dt)

    shape_results = []
    history_frames = []
    for index, shape_name in enumerate(DEFAULT_SHAPES):
        best_aggregate, history_df = optimize_shape(
            shape_name=shape_name,
            scenarios=training_scenarios,
            seed=args.seed + 1000 * (index + 1),
            generations=args.generations,
            population=args.population,
            elite_count=args.elite_count,
            num_samples=args.samples,
        )
        history_frames.append(history_df)
        shape_results.append(best_aggregate)

    history_all = pd.concat(history_frames, ignore_index=True)
    history_all.to_csv(args.outdir / "history.csv", index=False)
    plot_convergence(history_all, args.outdir)

    best_aggregate = max(shape_results, key=lambda item: item["score"])
    coarse_geometry, refined_geometry, coarse_results, refined_results = validate_design(
        best_aggregate=best_aggregate,
        validation_scenarios=validation_scenarios,
        coarse_samples=args.samples,
        refined_samples=args.refined_samples,
        seed=args.seed + 8000,
    )

    coarse_df = report_dataframe(coarse_results)
    refined_df = report_dataframe(refined_results)
    coarse_df.to_csv(args.outdir / "validation_coarse.csv", index=False)
    refined_df.to_csv(args.outdir / "validation_refined.csv", index=False)

    representative = max(refined_results, key=lambda result: result.score)
    plot_rollout(
        representative,
        yaw_limit_rad=refined_geometry.yaw_contact_limit_rad,
        translation_limit_m=refined_geometry.translation_contact_limit_m,
        outdir=args.outdir,
    )
    write_summary(
        best_shape=best_aggregate["shape_name"],
        best_aggregate=best_aggregate,
        refined_geometry=refined_geometry,
        coarse_results=coarse_results,
        refined_results=refined_results,
        outdir=args.outdir,
    )

    final_summary = {
        "best_shape": best_aggregate["shape_name"],
        "best_sku": best_aggregate["design"].magnet_sku_id,
        "estimated_total_cost_jpy": float(best_aggregate["design"].estimated_total_cost_jpy),
        "training_score": float(best_aggregate["score"]),
        "validation_mean_score": float(refined_df["score"].mean()),
        "validation_contact_events": int(refined_df["contact_events"].sum()),
        "validation_latched": int(refined_df["latched"].sum()),
        "worst_gap_mm": float(refined_df["min_gap_mm"].min()),
    }
    print(json.dumps(final_summary, indent=2))


if __name__ == "__main__":
    main()
