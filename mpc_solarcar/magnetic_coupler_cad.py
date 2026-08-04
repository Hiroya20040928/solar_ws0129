import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import cadquery as cq
from cadquery import exporters
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Circle, Polygon
from matplotlib import font_manager
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_hifi as hifi


MM_PER_M = 1000.0
ISO_VIEW = (-1.75, 1.10, 5.00)
TOP_VIEW = (0.0, 0.0, 1.0)
FRONT_VIEW = (0.0, -1.0, 0.0)


@dataclass(frozen=True)
class CasingParameters:
    """Mechanical parameters for the printable magnet carriers."""

    front_skin_m: float = 0.0008
    rear_flange_m: float = 0.0060
    back_yoke_pocket_m: float = 0.0032
    bottom_floor_m: float = 0.0024
    lid_thickness_m: float = 0.0030
    pocket_clearance_tangential_m: float = 0.00035
    pocket_clearance_radial_m: float = 0.00030
    pocket_clearance_axial_m: float = 0.00045
    screw_hole_diameter_m: float = 0.0034
    screw_count: int = 12


@dataclass
class PartPackage:
    """Geometry and metadata needed for drawing generation."""

    name: str
    body: cq.Workplane
    outer_profile_m: np.ndarray
    inner_profile_m: np.ndarray
    magnet_face_profile_m: np.ndarray
    hole_sites_m: np.ndarray
    pocket_centers_m: np.ndarray
    pocket_normals_m: np.ndarray
    pocket_tangents_m: np.ndarray
    metadata: dict


def mm(value_m):
    """Converts meters to millimeters for CAD generation."""

    return float(value_m) * MM_PER_M


def setup_plot_style():
    """Applies a predictable figure style with a Japanese-capable font if present."""

    available = {font.name for font in font_manager.fontManager.ttflist}
    for candidate in ("Yu Gothic", "Meiryo", "MS Gothic", "DejaVu Sans"):
        if candidate in available:
            plt.rcParams["font.family"] = candidate
            break
    plt.rcParams["axes.titlesize"] = 14
    plt.rcParams["axes.labelsize"] = 11
    plt.rcParams["xtick.labelsize"] = 9
    plt.rcParams["ytick.labelsize"] = 9


def load_selected_design(design_json_path: Path):
    """Loads the selected high-fidelity design and reconstructs its geometry."""

    payload = json.loads(design_json_path.read_text(encoding="utf-8"))
    design = payload["selected_design"]
    shape = hifi.ShapeParameters(**design["shape_parameters"])
    geometry = hifi.build_geometry_from_shape(
        shape_params=shape,
        mean_radius_m=design["mean_radius_m"],
        gap_m=design["gap_m"],
        num_samples=256,
    )
    return payload, design, geometry


def sample_ring_sites(points_xy, normals_xy, tangents_xy, perimeter_m, count, phase_pitch_fraction=0.0):
    """Samples equally spaced points along a perimeter with a continuous phase shift."""

    edge_vectors = np.roll(points_xy, -1, axis=0) - points_xy
    edge_lengths = np.linalg.norm(edge_vectors, axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(edge_lengths)))
    pitch_m = perimeter_m / count
    targets = (np.arange(count, dtype=float) + phase_pitch_fraction) * pitch_m
    targets = np.mod(targets, perimeter_m)

    sampled_points = []
    sampled_normals = []
    sampled_tangents = []
    for target in targets:
        edge_index = int(np.searchsorted(cumulative, target, side="right") - 1)
        edge_index = min(edge_index, len(edge_lengths) - 1)
        local_fraction = (target - cumulative[edge_index]) / max(edge_lengths[edge_index], 1.0e-12)
        next_index = (edge_index + 1) % len(points_xy)
        point = (1.0 - local_fraction) * points_xy[edge_index] + local_fraction * points_xy[next_index]
        normal = (1.0 - local_fraction) * normals_xy[edge_index] + local_fraction * normals_xy[next_index]
        tangent = (1.0 - local_fraction) * tangents_xy[edge_index] + local_fraction * tangents_xy[next_index]
        normal /= np.linalg.norm(normal) + 1.0e-12
        tangent /= np.linalg.norm(tangent) + 1.0e-12
        sampled_points.append(point)
        sampled_normals.append(normal)
        sampled_tangents.append(tangent)
    return np.asarray(sampled_points), np.asarray(sampled_normals), np.asarray(sampled_tangents)


def face_from_profiles(outer_points_xy_m, inner_points_xy_m):
    """Creates a planar CadQuery face from outer and inner closed polylines."""

    outer_points_mm = [(mm(point[0]), mm(point[1])) for point in outer_points_xy_m]
    inner_points_mm = [(mm(point[0]), mm(point[1])) for point in inner_points_xy_m]
    outer_wire = cq.Workplane("XY").polyline(outer_points_mm).close().val()
    inner_wire = cq.Workplane("XY").polyline(inner_points_mm).close().val()
    return cq.Face.makeFromWires(outer_wire, [inner_wire])


def make_box_cut(center_xy_m, tangent_xy, size_t_m, size_r_m, size_z_m, z_bottom_m):
    """Creates one oriented rectangular pocket cut."""

    angle_deg = math.degrees(math.atan2(tangent_xy[1], tangent_xy[0]))
    box = cq.Workplane("XY").box(
        mm(size_t_m),
        mm(size_r_m),
        mm(size_z_m),
        centered=(True, True, True),
    )
    box = box.rotate((0.0, 0.0, 0.0), (0.0, 0.0, 1.0), angle_deg)
    return box.translate(
        (
            mm(center_xy_m[0]),
            mm(center_xy_m[1]),
            mm(z_bottom_m + 0.5 * size_z_m),
        )
    )


def make_cylinder_cut(center_xy_m, diameter_m, height_m, z_bottom_m):
    """Creates one vertical cylindrical hole cut."""

    return (
        cq.Workplane("XY")
        .cylinder(mm(height_m), mm(0.5 * diameter_m))
        .translate((mm(center_xy_m[0]), mm(center_xy_m[1]), mm(z_bottom_m + 0.5 * height_m)))
    )


def combine_solids(solids):
    """Combines many disjoint solids into a single compound."""

    return cq.Workplane("XY").add(cq.Compound.makeCompound([solid.val() for solid in solids]))


def ring_hole_sites(boundary_points_xy, boundary_normals_xy, perimeter_m, count, radial_offset_m):
    """Builds screw-hole positions along a mid-flange path."""

    tangents = np.roll(boundary_points_xy, -1, axis=0) - np.roll(boundary_points_xy, 1, axis=0)
    tangents /= np.linalg.norm(tangents, axis=1, keepdims=True) + 1.0e-12
    points, normals, _ = sample_ring_sites(
        boundary_points_xy,
        boundary_normals_xy,
        tangents,
        perimeter_m,
        count,
        phase_pitch_fraction=0.5,
    )
    return points + radial_offset_m * normals


def rectangle_corners(center_xy_m, tangent_xy, normal_xy, size_t_m, size_r_m):
    """Returns a 2D pocket rectangle for drawing overlays."""

    half_t = 0.5 * size_t_m * tangent_xy
    half_r = 0.5 * size_r_m * normal_xy
    return np.asarray(
        [
            center_xy_m - half_t - half_r,
            center_xy_m + half_t - half_r,
            center_xy_m + half_t + half_r,
            center_xy_m - half_t + half_r,
        ]
    )


def build_inner_base(design, geometry, params: CasingParameters):
    """Creates the robot-side inner carrier base with magnet and yoke pockets."""

    pocket_radial_depth_m = (
        design["magnet_radial_depth_m"] + params.back_yoke_pocket_m + params.pocket_clearance_radial_m
    )
    pocket_height_m = design["nominal_overlap_m"] + params.pocket_clearance_axial_m
    base_height_m = params.bottom_floor_m + pocket_height_m

    magnet_face_profile = geometry.inner_points
    outer_profile = magnet_face_profile + params.front_skin_m * geometry.inner_normals
    inner_profile = magnet_face_profile - (pocket_radial_depth_m + params.rear_flange_m) * geometry.inner_normals
    body = cq.Workplane("XY").add(face_from_profiles(outer_profile, inner_profile)).extrude(mm(base_height_m))

    magnet_points, magnet_normals, magnet_tangents = sample_ring_sites(
        geometry.inner_points,
        geometry.inner_normals,
        geometry.inner_tangents,
        geometry.inner_perimeter_m,
        design["magnets_per_ring"],
        phase_pitch_fraction=0.0,
    )
    pocket_tangential_m = design["magnet_tangential_length_m"] + params.pocket_clearance_tangential_m
    pocket_cuts = []
    pocket_centers = []
    for point_xy, normal_xy, tangent_xy in zip(magnet_points, magnet_normals, magnet_tangents):
        center_xy = point_xy - 0.5 * pocket_radial_depth_m * normal_xy
        pocket_centers.append(center_xy)
        pocket_cuts.append(
            make_box_cut(
                center_xy_m=center_xy,
                tangent_xy=tangent_xy,
                size_t_m=pocket_tangential_m,
                size_r_m=pocket_radial_depth_m,
                size_z_m=pocket_height_m,
                z_bottom_m=params.bottom_floor_m,
            )
        )
    body = body.cut(combine_solids(pocket_cuts))

    hole_offset_m = params.front_skin_m + pocket_radial_depth_m + 0.52 * params.rear_flange_m
    hole_sites = ring_hole_sites(
        geometry.inner_points,
        -geometry.inner_normals,
        geometry.inner_perimeter_m,
        params.screw_count,
        radial_offset_m=-hole_offset_m,
    )
    hole_cuts = [
        make_cylinder_cut(site_xy, params.screw_hole_diameter_m, base_height_m, 0.0) for site_xy in hole_sites
    ]
    body = body.cut(combine_solids(hole_cuts))

    metadata = {
        "band_depth_m": params.front_skin_m + pocket_radial_depth_m + params.rear_flange_m,
        "pocket_radial_depth_m": pocket_radial_depth_m,
        "pocket_height_m": pocket_height_m,
        "base_height_m": base_height_m,
        "pocket_tangential_m": pocket_tangential_m,
    }
    return PartPackage(
        name="inner_carrier",
        body=body,
        outer_profile_m=outer_profile,
        inner_profile_m=inner_profile,
        magnet_face_profile_m=magnet_face_profile,
        hole_sites_m=hole_sites,
        pocket_centers_m=np.asarray(pocket_centers),
        pocket_normals_m=magnet_normals,
        pocket_tangents_m=magnet_tangents,
        metadata=metadata,
    )


def build_outer_base(design, geometry, params: CasingParameters):
    """Creates the cart-side outer carrier base with magnet and yoke pockets."""

    pocket_radial_depth_m = (
        design["magnet_radial_depth_m"] + params.back_yoke_pocket_m + params.pocket_clearance_radial_m
    )
    pocket_height_m = design["nominal_overlap_m"] + params.pocket_clearance_axial_m
    base_height_m = params.bottom_floor_m + pocket_height_m

    magnet_face_profile = geometry.outer_points_local
    inner_profile = magnet_face_profile - params.front_skin_m * geometry.outer_outward_normals_local
    outer_profile = magnet_face_profile + (pocket_radial_depth_m + params.rear_flange_m) * geometry.outer_outward_normals_local
    body = cq.Workplane("XY").add(face_from_profiles(outer_profile, inner_profile)).extrude(mm(base_height_m))

    magnet_points, magnet_normals, magnet_tangents = sample_ring_sites(
        geometry.outer_points_local,
        geometry.outer_outward_normals_local,
        geometry.outer_tangents_local,
        geometry.outer_perimeter_m,
        design["magnets_per_ring"],
        phase_pitch_fraction=design["outer_phase_fraction"],
    )
    pocket_tangential_m = design["magnet_tangential_length_m"] + params.pocket_clearance_tangential_m
    pocket_cuts = []
    pocket_centers = []
    for point_xy, normal_xy, tangent_xy in zip(magnet_points, magnet_normals, magnet_tangents):
        center_xy = point_xy + 0.5 * pocket_radial_depth_m * normal_xy
        pocket_centers.append(center_xy)
        pocket_cuts.append(
            make_box_cut(
                center_xy_m=center_xy,
                tangent_xy=tangent_xy,
                size_t_m=pocket_tangential_m,
                size_r_m=pocket_radial_depth_m,
                size_z_m=pocket_height_m,
                z_bottom_m=params.bottom_floor_m,
            )
        )
    body = body.cut(combine_solids(pocket_cuts))

    hole_offset_m = params.front_skin_m + pocket_radial_depth_m + 0.52 * params.rear_flange_m
    hole_sites = ring_hole_sites(
        geometry.outer_points_local,
        geometry.outer_outward_normals_local,
        geometry.outer_perimeter_m,
        params.screw_count,
        radial_offset_m=hole_offset_m,
    )
    hole_cuts = [
        make_cylinder_cut(site_xy, params.screw_hole_diameter_m, base_height_m, 0.0) for site_xy in hole_sites
    ]
    body = body.cut(combine_solids(hole_cuts))

    metadata = {
        "band_depth_m": params.front_skin_m + pocket_radial_depth_m + params.rear_flange_m,
        "pocket_radial_depth_m": pocket_radial_depth_m,
        "pocket_height_m": pocket_height_m,
        "base_height_m": base_height_m,
        "pocket_tangential_m": pocket_tangential_m,
    }
    return PartPackage(
        name="outer_carrier",
        body=body,
        outer_profile_m=outer_profile,
        inner_profile_m=inner_profile,
        magnet_face_profile_m=magnet_face_profile,
        hole_sites_m=hole_sites,
        pocket_centers_m=np.asarray(pocket_centers),
        pocket_normals_m=magnet_normals,
        pocket_tangents_m=magnet_tangents,
        metadata=metadata,
    )


def build_lid(outer_profile, inner_profile, hole_sites_xy_m, params: CasingParameters):
    """Creates a flat closing lid for one carrier."""

    body = cq.Workplane("XY").add(face_from_profiles(outer_profile, inner_profile)).extrude(mm(params.lid_thickness_m))
    hole_cuts = [
        make_cylinder_cut(site_xy, params.screw_hole_diameter_m, params.lid_thickness_m, 0.0)
        for site_xy in hole_sites_xy_m
    ]
    return body.cut(combine_solids(hole_cuts))


def build_assemblies(inner_pkg: PartPackage, outer_pkg: PartPackage, inner_lid, outer_lid, params: CasingParameters):
    """Builds carrier subassemblies and the full concentric assembly."""

    inner_lid_z = mm(inner_pkg.metadata["base_height_m"])
    outer_lid_z = mm(outer_pkg.metadata["base_height_m"])

    inner_assembly = cq.Workplane("XY").add(
        cq.Compound.makeCompound(
            [
                inner_pkg.body.val(),
                inner_lid.translate((0.0, 0.0, inner_lid_z)).val(),
            ]
        )
    )
    outer_assembly = cq.Workplane("XY").add(
        cq.Compound.makeCompound(
            [
                outer_pkg.body.val(),
                outer_lid.translate((0.0, 0.0, outer_lid_z)).val(),
            ]
        )
    )
    full_assembly = cq.Workplane("XY").add(
        cq.Compound.makeCompound(
            [
                inner_pkg.body.val(),
                inner_lid.translate((0.0, 0.0, inner_lid_z)).val(),
                outer_pkg.body.val(),
                outer_lid.translate((0.0, 0.0, outer_lid_z)).val(),
            ]
        )
    )

    exploded_offset_mm = 0.75 * max(
        float(np.max(np.abs(MM_PER_M * inner_pkg.outer_profile_m[:, 0]))),
        float(np.max(np.abs(MM_PER_M * outer_pkg.outer_profile_m[:, 0]))),
    )
    exploded = cq.Workplane("XY").add(
        cq.Compound.makeCompound(
            [
                inner_pkg.body.translate((-0.5 * exploded_offset_mm, 0.0, 0.0)).val(),
                inner_lid.translate((-0.5 * exploded_offset_mm, 0.0, inner_lid_z)).val(),
                outer_pkg.body.translate((0.5 * exploded_offset_mm, 0.0, 0.0)).val(),
                outer_lid.translate((0.5 * exploded_offset_mm, 0.0, outer_lid_z)).val(),
            ]
        )
    )
    return inner_assembly, outer_assembly, full_assembly, exploded


def export_part(part, path_without_suffix: Path):
    """Exports one solid to STEP and STL."""

    step_path = path_without_suffix.with_suffix(".step")
    stl_path = path_without_suffix.with_suffix(".stl")
    exporters.export(part, str(step_path))
    exporters.export(part, str(stl_path))
    return step_path, stl_path


def export_svg_views(part, outdir: Path, stem: str):
    """Exports vector line-art views for quick inspection."""

    shape = part.val() if hasattr(part, "val") else part
    view_specs = {
        "iso": {"projectionDir": ISO_VIEW, "width": 1400, "height": 1000, "showHidden": False, "showAxes": False},
        "top": {"projectionDir": TOP_VIEW, "width": 1200, "height": 1200, "showHidden": False, "showAxes": False},
        "front": {"projectionDir": FRONT_VIEW, "width": 1400, "height": 700, "showHidden": False, "showAxes": False},
    }
    exported = []
    for suffix, opts in view_specs.items():
        path = outdir / f"{stem}_{suffix}.svg"
        exporters.export(shape, str(path), exportType="SVG", opt=opts)
        exported.append(path)
    return exported


def bounds_mm(*profiles_m):
    """Returns x/y bounds in millimeters for one or more 2D profiles."""

    all_points = np.vstack(profiles_m)
    all_points_mm = MM_PER_M * all_points
    return (
        float(np.min(all_points_mm[:, 0])),
        float(np.max(all_points_mm[:, 0])),
        float(np.min(all_points_mm[:, 1])),
        float(np.max(all_points_mm[:, 1])),
    )


def add_horizontal_dimension(ax, x0, x1, y, text, tick_mm=3.0, color="#111827"):
    """Draws a horizontal dimension arrow."""

    ax.annotate("", xy=(x0, y), xytext=(x1, y), arrowprops=dict(arrowstyle="<->", lw=1.2, color=color))
    ax.plot([x0, x0], [y - tick_mm, y + tick_mm], color=color, linewidth=1.0)
    ax.plot([x1, x1], [y - tick_mm, y + tick_mm], color=color, linewidth=1.0)
    ax.text(0.5 * (x0 + x1), y + 1.6 * tick_mm, text, ha="center", va="bottom", fontsize=9, color=color)


def add_vertical_dimension(ax, x, y0, y1, text, tick_mm=3.0, color="#111827"):
    """Draws a vertical dimension arrow."""

    ax.annotate("", xy=(x, y0), xytext=(x, y1), arrowprops=dict(arrowstyle="<->", lw=1.2, color=color))
    ax.plot([x - tick_mm, x + tick_mm], [y0, y0], color=color, linewidth=1.0)
    ax.plot([x - tick_mm, x + tick_mm], [y1, y1], color=color, linewidth=1.0)
    ax.text(x + 1.6 * tick_mm, 0.5 * (y0 + y1), text, ha="left", va="center", fontsize=9, color=color, rotation=90)


def draw_ring_top_view(ax, pkg: PartPackage, params: CasingParameters, title: str, outline_color: str, fill_color: str):
    """Draws one ring planform with holes and pocket overlays."""

    outer_mm = MM_PER_M * pkg.outer_profile_m
    inner_mm = MM_PER_M * pkg.inner_profile_m
    magnet_face_mm = MM_PER_M * pkg.magnet_face_profile_m
    ax.add_patch(Polygon(outer_mm, closed=True, facecolor=fill_color, edgecolor=outline_color, linewidth=1.6))
    ax.add_patch(Polygon(inner_mm, closed=True, facecolor="white", edgecolor=outline_color, linewidth=1.4))
    ax.plot(magnet_face_mm[:, 0], magnet_face_mm[:, 1], color="#475569", linewidth=1.0, linestyle="--", label="magnet face datum")

    pocket_t = pkg.metadata["pocket_tangential_m"]
    pocket_r = pkg.metadata["pocket_radial_depth_m"]
    sample_stride = max(1, len(pkg.pocket_centers_m) // 16)
    for idx, (center, tangent, normal) in enumerate(
        zip(pkg.pocket_centers_m, pkg.pocket_tangents_m, pkg.pocket_normals_m)
    ):
        if idx % sample_stride != 0:
            continue
        rect_mm = MM_PER_M * rectangle_corners(center, tangent, normal, pocket_t, pocket_r)
        ax.add_patch(
            Polygon(
                rect_mm,
                closed=True,
                facecolor="#bfdbfe",
                edgecolor="#2563eb",
                linewidth=0.7,
                alpha=0.55,
            )
        )
    for site in pkg.hole_sites_m:
        ax.add_patch(
            Circle(
                tuple(MM_PER_M * site),
                radius=0.5 * mm(params.screw_hole_diameter_m),
                facecolor="white",
                edgecolor="#0f172a",
                linewidth=1.0,
            )
        )

    x_min, x_max, y_min, y_max = bounds_mm(pkg.outer_profile_m)
    span_x = x_max - x_min
    span_y = y_max - y_min
    margin = 0.12 * max(span_x, span_y)
    ax.set_xlim(x_min - margin, x_max + margin)
    ax.set_ylim(y_min - margin, y_max + margin)
    ax.set_aspect("equal")
    ax.grid(True, alpha=0.22)
    ax.set_title(title)
    ax.set_xlabel("X [mm]")
    ax.set_ylabel("Y [mm]")

    add_horizontal_dimension(ax, x_min, x_max, y_min - 0.07 * max(span_x, span_y), f"{span_x:.1f} mm")
    add_vertical_dimension(ax, x_min - 0.07 * max(span_x, span_y), y_min, y_max, f"{span_y:.1f} mm")


def draw_single_ring_section(ax, pkg: PartPackage, params: CasingParameters, title: str, color: str):
    """Draws a representative radial section through the +X side of one part."""

    base_height_mm = mm(pkg.metadata["base_height_m"])
    lid_thickness_mm = mm(params.lid_thickness_m)
    pocket_depth_mm = mm(pkg.metadata["pocket_radial_depth_m"])
    pocket_height_mm = mm(pkg.metadata["pocket_height_m"])
    bottom_floor_mm = mm(params.bottom_floor_m)

    if "inner" in pkg.name:
        shell_outer_mm = float(np.max(MM_PER_M * pkg.outer_profile_m[:, 0]))
        magnet_face_mm = float(np.max(MM_PER_M * pkg.magnet_face_profile_m[:, 0]))
        shell_inner_mm = float(np.max(MM_PER_M * pkg.inner_profile_m[:, 0]))
        pocket_back_mm = magnet_face_mm - pocket_depth_mm
        part_color = "#dbeafe"
    else:
        shell_inner_mm = float(np.max(MM_PER_M * pkg.inner_profile_m[:, 0]))
        magnet_face_mm = float(np.max(MM_PER_M * pkg.magnet_face_profile_m[:, 0]))
        shell_outer_mm = float(np.max(MM_PER_M * pkg.outer_profile_m[:, 0]))
        pocket_back_mm = magnet_face_mm + pocket_depth_mm
        part_color = "#ffedd5"

    ax.add_patch(
        Polygon(
            np.array(
                [
                    [shell_inner_mm, 0.0],
                    [shell_outer_mm, 0.0],
                    [shell_outer_mm, base_height_mm],
                    [shell_inner_mm, base_height_mm],
                ]
            ),
            closed=True,
            facecolor=part_color,
            edgecolor=color,
            linewidth=1.5,
        )
    )
    ax.add_patch(
        Polygon(
            np.array(
                [
                    [shell_inner_mm, base_height_mm],
                    [shell_outer_mm, base_height_mm],
                    [shell_outer_mm, base_height_mm + lid_thickness_mm],
                    [shell_inner_mm, base_height_mm + lid_thickness_mm],
                ]
            ),
            closed=True,
            facecolor="#f8fafc",
            edgecolor=color,
            linewidth=1.2,
        )
    )

    cavity_x0 = min(magnet_face_mm, pocket_back_mm)
    cavity_x1 = max(magnet_face_mm, pocket_back_mm)
    ax.add_patch(
        Polygon(
            np.array(
                [
                    [cavity_x0, bottom_floor_mm],
                    [cavity_x1, bottom_floor_mm],
                    [cavity_x1, bottom_floor_mm + pocket_height_mm],
                    [cavity_x0, bottom_floor_mm + pocket_height_mm],
                ]
            ),
            closed=True,
            facecolor="white",
            edgecolor="#2563eb",
            linewidth=1.1,
            linestyle="--",
        )
    )
    ax.axvline(magnet_face_mm, color="#475569", linewidth=1.0, linestyle="--")

    x_min = min(shell_inner_mm, shell_outer_mm)
    x_max = max(shell_inner_mm, shell_outer_mm)
    span_x = x_max - x_min
    span_y = base_height_mm + lid_thickness_mm
    margin_x = 0.25 * max(span_x, 1.0)
    margin_y = 0.18 * max(span_y, 1.0)
    ax.set_xlim(x_min - margin_x, x_max + margin_x)
    ax.set_ylim(-margin_y, span_y + margin_y)
    ax.grid(True, alpha=0.22)
    ax.set_title(title)
    ax.set_xlabel("Radius on +X section [mm]")
    ax.set_ylabel("Z [mm]")

    add_horizontal_dimension(ax, shell_inner_mm, shell_outer_mm, -0.11 * span_y, f"band {span_x:.2f} mm")
    add_vertical_dimension(ax, x_max + 0.11 * max(span_x, 1.0), 0.0, base_height_mm, f"base {base_height_mm:.2f} mm")
    add_vertical_dimension(
        ax,
        x_max + 0.22 * max(span_x, 1.0),
        base_height_mm,
        base_height_mm + lid_thickness_mm,
        f"lid {lid_thickness_mm:.2f} mm",
    )


def set_3d_equal(ax, profiles_m, heights_mm):
    """Applies a balanced view box for 3D wireframe plots."""

    profiles_mm = [MM_PER_M * profile for profile in profiles_m]
    all_points = np.vstack(profiles_mm)
    x_min = float(np.min(all_points[:, 0]))
    x_max = float(np.max(all_points[:, 0]))
    y_min = float(np.min(all_points[:, 1]))
    y_max = float(np.max(all_points[:, 1]))
    z_min = float(min(heights_mm))
    z_max = float(max(heights_mm))
    x_span = x_max - x_min
    y_span = y_max - y_min
    z_span = max(z_max - z_min, 1.0)
    xy_margin = 0.10 * max(x_span, y_span)
    z_margin = max(4.0, 0.18 * z_span)
    ax.set_xlim(x_min - xy_margin, x_max + xy_margin)
    ax.set_ylim(y_min - xy_margin, y_max + xy_margin)
    ax.set_zlim(z_min, z_max + z_margin)
    if hasattr(ax, "set_box_aspect"):
        ax.set_box_aspect((x_span + 2.0 * xy_margin, y_span + 2.0 * xy_margin, max(z_span + z_margin, 0.18 * max(x_span, y_span))))


def plot_wireframe_ring(ax, pkg: PartPackage, params: CasingParameters, color: str):
    """Plots a simple 3D wireframe of one ring assembly."""

    outer_mm = MM_PER_M * pkg.outer_profile_m
    inner_mm = MM_PER_M * pkg.inner_profile_m
    z0 = 0.0
    z1 = mm(pkg.metadata["base_height_m"])
    z2 = z1 + mm(params.lid_thickness_m)
    stride = max(1, len(outer_mm) // 24)

    def draw_loop(points_mm, z, alpha=1.0, linewidth=1.4):
        closed = np.vstack([points_mm, points_mm[:1]])
        ax.plot3D(closed[:, 0], closed[:, 1], np.full(len(closed), z), color=color, alpha=alpha, linewidth=linewidth)

    for z, alpha, lw in ((z0, 0.45, 1.0), (z1, 0.95, 1.5), (z2, 0.95, 1.5)):
        draw_loop(outer_mm, z, alpha=alpha, linewidth=lw)
        draw_loop(inner_mm, z, alpha=alpha, linewidth=lw)

    for idx in range(0, len(outer_mm), stride):
        ax.plot3D(
            [outer_mm[idx, 0], outer_mm[idx, 0]],
            [outer_mm[idx, 1], outer_mm[idx, 1]],
            [z0, z2],
            color=color,
            alpha=0.35,
            linewidth=0.8,
        )
        ax.plot3D(
            [inner_mm[idx, 0], inner_mm[idx, 0]],
            [inner_mm[idx, 1], inner_mm[idx, 1]],
            [z0, z2],
            color=color,
            alpha=0.30,
            linewidth=0.8,
        )


def draw_assembly_section(ax, inner_pkg: PartPackage, outer_pkg: PartPackage, params: CasingParameters):
    """Draws the installed concentric section on the +X side."""

    base_height_mm = mm(inner_pkg.metadata["base_height_m"])
    lid_thickness_mm = mm(params.lid_thickness_m)
    bottom_floor_mm = mm(params.bottom_floor_m)
    pocket_height_mm = mm(inner_pkg.metadata["pocket_height_m"])
    inner_pocket_depth_mm = mm(inner_pkg.metadata["pocket_radial_depth_m"])
    outer_pocket_depth_mm = mm(outer_pkg.metadata["pocket_radial_depth_m"])

    inner_shell_inner = float(np.max(MM_PER_M * inner_pkg.inner_profile_m[:, 0]))
    inner_magnet_face = float(np.max(MM_PER_M * inner_pkg.magnet_face_profile_m[:, 0]))
    inner_shell_outer = float(np.max(MM_PER_M * inner_pkg.outer_profile_m[:, 0]))

    outer_shell_inner = float(np.max(MM_PER_M * outer_pkg.inner_profile_m[:, 0]))
    outer_magnet_face = float(np.max(MM_PER_M * outer_pkg.magnet_face_profile_m[:, 0]))
    outer_shell_outer = float(np.max(MM_PER_M * outer_pkg.outer_profile_m[:, 0]))

    shell_gap_mm = outer_shell_inner - inner_shell_outer
    magnetic_gap_mm = outer_magnet_face - inner_magnet_face

    inner_patch = np.array(
        [
            [inner_shell_inner, 0.0],
            [inner_shell_outer, 0.0],
            [inner_shell_outer, base_height_mm],
            [inner_shell_inner, base_height_mm],
        ]
    )
    outer_patch = np.array(
        [
            [outer_shell_inner, 0.0],
            [outer_shell_outer, 0.0],
            [outer_shell_outer, base_height_mm],
            [outer_shell_inner, base_height_mm],
        ]
    )
    ax.add_patch(Polygon(inner_patch, closed=True, facecolor="#dbeafe", edgecolor="#1d4ed8", linewidth=1.5))
    ax.add_patch(Polygon(outer_patch, closed=True, facecolor="#ffedd5", edgecolor="#ea580c", linewidth=1.5))

    for shell_inner, shell_outer, edge_color in (
        (inner_shell_inner, inner_shell_outer, "#1d4ed8"),
        (outer_shell_inner, outer_shell_outer, "#ea580c"),
    ):
        ax.add_patch(
            Polygon(
                np.array(
                    [
                        [shell_inner, base_height_mm],
                        [shell_outer, base_height_mm],
                        [shell_outer, base_height_mm + lid_thickness_mm],
                        [shell_inner, base_height_mm + lid_thickness_mm],
                    ]
                ),
                closed=True,
                facecolor="#f8fafc",
                edgecolor=edge_color,
                linewidth=1.2,
            )
        )

    ax.add_patch(
        Polygon(
            np.array(
                [
                    [inner_magnet_face - inner_pocket_depth_mm, bottom_floor_mm],
                    [inner_magnet_face, bottom_floor_mm],
                    [inner_magnet_face, bottom_floor_mm + pocket_height_mm],
                    [inner_magnet_face - inner_pocket_depth_mm, bottom_floor_mm + pocket_height_mm],
                ]
            ),
            closed=True,
            facecolor="white",
            edgecolor="#2563eb",
            linewidth=1.1,
            linestyle="--",
        )
    )
    ax.add_patch(
        Polygon(
            np.array(
                [
                    [outer_magnet_face, bottom_floor_mm],
                    [outer_magnet_face + outer_pocket_depth_mm, bottom_floor_mm],
                    [outer_magnet_face + outer_pocket_depth_mm, bottom_floor_mm + pocket_height_mm],
                    [outer_magnet_face, bottom_floor_mm + pocket_height_mm],
                ]
            ),
            closed=True,
            facecolor="white",
            edgecolor="#f97316",
            linewidth=1.1,
            linestyle="--",
        )
    )
    ax.axvline(inner_magnet_face, color="#475569", linewidth=1.0, linestyle="--")
    ax.axvline(outer_magnet_face, color="#475569", linewidth=1.0, linestyle="--")

    x_min = inner_shell_inner - 28.0
    x_max = outer_shell_outer + 28.0
    y_max = base_height_mm + lid_thickness_mm
    ax.set_xlim(x_min, x_max)
    ax.set_ylim(-10.0, y_max + 10.0)
    ax.grid(True, alpha=0.22)
    ax.set_title("Installed +X radial section")
    ax.set_xlabel("Radius [mm]")
    ax.set_ylabel("Z [mm]")

    add_horizontal_dimension(ax, inner_shell_outer, outer_shell_inner, -4.0, f"+X shell gap {shell_gap_mm:.2f} mm")
    add_horizontal_dimension(ax, inner_magnet_face, outer_magnet_face, -8.5, f"+X magnet gap {magnetic_gap_mm:.2f} mm")
    add_vertical_dimension(ax, outer_shell_outer + 8.0, 0.0, base_height_mm, f"base {base_height_mm:.2f} mm")
    add_vertical_dimension(
        ax,
        outer_shell_outer + 16.0,
        base_height_mm,
        base_height_mm + lid_thickness_mm,
        f"lid {lid_thickness_mm:.2f} mm",
    )


def add_text_block(ax, title, lines):
    """Places a formatted text block in an empty axes."""

    ax.axis("off")
    text = "\n".join([title, ""] + lines)
    ax.text(
        0.0,
        1.0,
        text,
        va="top",
        ha="left",
        fontsize=10,
        family=plt.rcParams["font.family"],
        linespacing=1.35,
        transform=ax.transAxes,
    )


def build_text_lines(design, params: CasingParameters, pkg: PartPackage = None):
    """Builds concise manufacturing and design notes."""

    shape_label = design.get("shape_label")
    if not shape_label:
        shape_label = hifi.shape_name(hifi.ShapeParameters(**design["shape_parameters"]))
    lines = [
        f"Shape label: {shape_label}",
        f"Magnet SKU: {design['magnet_sku_id']}",
        f"Magnets per ring: {design['magnets_per_ring']} x {design['magnet_layers']} layers",
        f"Total magnets: {design['total_magnets']}",
        f"Nominal magnet-face gap: {mm(design['gap_m']):.2f} mm",
        f"Nominal overlap: {mm(design['nominal_overlap_m']):.2f} mm",
        f"Front skin: {mm(params.front_skin_m):.2f} mm",
        f"Rear flange: {mm(params.rear_flange_m):.2f} mm",
        f"Bottom floor: {mm(params.bottom_floor_m):.2f} mm",
        f"Lid thickness: {mm(params.lid_thickness_m):.2f} mm",
        f"Screw holes: {params.screw_count} x {mm(params.screw_hole_diameter_m):.2f} mm",
    ]
    if pkg is not None:
        x_min, x_max, y_min, y_max = bounds_mm(pkg.outer_profile_m)
        lines.extend(
            [
                f"Envelope X: {x_max - x_min:.2f} mm",
                f"Envelope Y: {y_max - y_min:.2f} mm",
                f"Band depth: {mm(pkg.metadata['band_depth_m']):.2f} mm",
                f"Pocket tangential length: {mm(pkg.metadata['pocket_tangential_m']):.2f} mm",
                f"Pocket radial depth: {mm(pkg.metadata['pocket_radial_depth_m']):.2f} mm",
                f"Pocket height: {mm(pkg.metadata['pocket_height_m']):.2f} mm",
                f"Base height: {mm(pkg.metadata['base_height_m']):.2f} mm",
            ]
        )
    return lines


def make_page_figure(size=(16, 10)):
    """Creates a clean white page-sized figure."""

    fig = plt.figure(figsize=size, facecolor="white")
    return fig


def save_page(fig, png_path: Path, pdf: PdfPages):
    """Saves one sheet to PNG and the accumulating PDF."""

    fig.tight_layout()
    fig.savefig(png_path, dpi=220, bbox_inches="tight")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


def render_isometric_screenshot(outdir: Path, inner_pkg: PartPackage, outer_pkg: PartPackage, params: CasingParameters):
    """Renders a simple isometric screenshot as a PNG."""

    fig = plt.figure(figsize=(10, 8), facecolor="white")
    ax = fig.add_subplot(111, projection="3d")
    plot_wireframe_ring(ax, inner_pkg, params, "#1d4ed8")
    plot_wireframe_ring(ax, outer_pkg, params, "#ea580c")
    set_3d_equal(
        ax,
        [inner_pkg.outer_profile_m, inner_pkg.inner_profile_m, outer_pkg.outer_profile_m, outer_pkg.inner_profile_m],
        [0.0, mm(inner_pkg.metadata["base_height_m"]) + mm(params.lid_thickness_m)],
    )
    ax.view_init(elev=28, azim=-52)
    ax.set_title("Magnetic coupler assembly isometric view")
    ax.set_xlabel("X [mm]")
    ax.set_ylabel("Y [mm]")
    ax.set_zlabel("Z [mm]")
    fig.tight_layout()
    path = outdir / "coupler_isometric_screenshot.png"
    fig.savefig(path, dpi=220, bbox_inches="tight")
    plt.close(fig)
    return path


def generate_drawing_package(outdir: Path, design, params: CasingParameters, inner_pkg: PartPackage, outer_pkg: PartPackage):
    """Generates PNG sheets and a multi-page PDF drawing package."""

    setup_plot_style()
    pdf_path = outdir / "magnetic_coupler_cad_drawings.pdf"
    png_paths = []
    with PdfPages(pdf_path) as pdf:
        fig = make_page_figure()
        gs = fig.add_gridspec(2, 2, width_ratios=[1.15, 1.0], height_ratios=[1.0, 1.0])
        ax_top = fig.add_subplot(gs[0, 0])
        ax_iso = fig.add_subplot(gs[0, 1], projection="3d")
        ax_section = fig.add_subplot(gs[1, 0])
        ax_text = fig.add_subplot(gs[1, 1])
        draw_ring_top_view(ax_top, outer_pkg, params, "Outer carrier top view", "#ea580c", "#fff7ed")
        draw_ring_top_view(ax_top, inner_pkg, params, "Outer + inner carrier top view", "#1d4ed8", "#eff6ff")
        plot_wireframe_ring(ax_iso, inner_pkg, params, "#1d4ed8")
        plot_wireframe_ring(ax_iso, outer_pkg, params, "#ea580c")
        set_3d_equal(
            ax_iso,
            [inner_pkg.outer_profile_m, inner_pkg.inner_profile_m, outer_pkg.outer_profile_m, outer_pkg.inner_profile_m],
            [0.0, mm(inner_pkg.metadata["base_height_m"]) + mm(params.lid_thickness_m)],
        )
        ax_iso.view_init(elev=28, azim=-52)
        ax_iso.set_title("Isometric overview")
        ax_iso.set_xlabel("X [mm]")
        ax_iso.set_ylabel("Y [mm]")
        ax_iso.set_zlabel("Z [mm]")
        draw_assembly_section(ax_section, inner_pkg, outer_pkg, params)
        add_text_block(ax_text, "Assembly notes", build_text_lines(design, params))
        page = outdir / "01_coupler_assembly_sheet.png"
        save_page(fig, page, pdf)
        png_paths.append(page)

        fig = make_page_figure()
        gs = fig.add_gridspec(2, 2, width_ratios=[1.15, 1.0], height_ratios=[1.0, 1.0])
        ax_top = fig.add_subplot(gs[:, 0])
        ax_sec = fig.add_subplot(gs[0, 1])
        ax_text = fig.add_subplot(gs[1, 1])
        draw_ring_top_view(ax_top, inner_pkg, params, "Inner carrier base planform", "#1d4ed8", "#eff6ff")
        draw_single_ring_section(ax_sec, inner_pkg, params, "Inner carrier radial section", "#1d4ed8")
        add_text_block(ax_text, "Inner carrier specs", build_text_lines(design, params, inner_pkg))
        page = outdir / "02_inner_carrier_sheet.png"
        save_page(fig, page, pdf)
        png_paths.append(page)

        fig = make_page_figure()
        gs = fig.add_gridspec(2, 2, width_ratios=[1.15, 1.0], height_ratios=[1.0, 1.0])
        ax_top = fig.add_subplot(gs[:, 0])
        ax_sec = fig.add_subplot(gs[0, 1])
        ax_text = fig.add_subplot(gs[1, 1])
        draw_ring_top_view(ax_top, outer_pkg, params, "Outer carrier base planform", "#ea580c", "#fff7ed")
        draw_single_ring_section(ax_sec, outer_pkg, params, "Outer carrier radial section", "#ea580c")
        add_text_block(ax_text, "Outer carrier specs", build_text_lines(design, params, outer_pkg))
        page = outdir / "03_outer_carrier_sheet.png"
        save_page(fig, page, pdf)
        png_paths.append(page)

        fig = make_page_figure()
        gs = fig.add_gridspec(2, 2, width_ratios=[1.15, 1.0], height_ratios=[1.0, 1.0])
        ax_inner = fig.add_subplot(gs[0, 0])
        ax_outer = fig.add_subplot(gs[1, 0])
        ax_text = fig.add_subplot(gs[:, 1])
        draw_ring_top_view(ax_inner, inner_pkg, params, "Inner lid profile (same XY as base flange)", "#0f172a", "#f8fafc")
        draw_ring_top_view(ax_outer, outer_pkg, params, "Outer lid profile (same XY as base flange)", "#0f172a", "#f8fafc")
        add_text_block(
            ax_text,
            "Lid and assembly release notes",
            [
                f"Lid thickness: {mm(params.lid_thickness_m):.2f} mm",
                f"Lid hole count: {params.screw_count}",
                f"Hole diameter: {mm(params.screw_hole_diameter_m):.2f} mm",
                "Gap-facing front skins are already compensated in the CAD geometry.",
                "When imported into Fusion 360, the STEP files load as BRep solids.",
                f"Each pocket accepts {design['magnet_layers']} vertically stacked magnets plus an optional steel backer.",
                "Assembly STEP keeps the optimized concentric installed condition.",
            ],
        )
        page = outdir / "04_lid_and_release_sheet.png"
        save_page(fig, page, pdf)
        png_paths.append(page)

    return pdf_path, png_paths


def write_notes(outdir: Path, design_json: Path, payload, params: CasingParameters, inner_pkg: PartPackage, outer_pkg: PartPackage):
    """Writes manufacturing notes for the generated CAD."""

    design = payload["selected_design"]
    inner_bounds = bounds_mm(inner_pkg.outer_profile_m)
    outer_bounds = bounds_mm(outer_pkg.outer_profile_m)
    notes = {
        "design_source": str(design_json),
        "selected_sku": design["magnet_sku_id"],
        "magnet_vendor": design["magnet_vendor"],
        "magnets_per_ring": design["magnets_per_ring"],
        "magnet_layers": design["magnet_layers"],
        "stack_height_mm": mm(design["nominal_overlap_m"]),
        "pocket_clearance_tangential_mm": mm(params.pocket_clearance_tangential_m),
        "pocket_clearance_radial_mm": mm(params.pocket_clearance_radial_m),
        "pocket_clearance_axial_mm": mm(params.pocket_clearance_axial_m),
        "front_skin_mm": mm(params.front_skin_m),
        "back_yoke_pocket_mm": mm(params.back_yoke_pocket_m),
        "rear_flange_mm": mm(params.rear_flange_m),
        "bottom_floor_mm": mm(params.bottom_floor_m),
        "lid_thickness_mm": mm(params.lid_thickness_m),
        "screw_hole_diameter_mm": mm(params.screw_hole_diameter_m),
        "screw_count": params.screw_count,
        "optimized_magnet_face_gap_mm": mm(design["gap_m"]),
        "inner_base_height_mm": mm(inner_pkg.metadata["base_height_m"]),
        "outer_base_height_mm": mm(outer_pkg.metadata["base_height_m"]),
        "inner_pocket_radial_depth_mm": mm(inner_pkg.metadata["pocket_radial_depth_m"]),
        "outer_pocket_radial_depth_mm": mm(outer_pkg.metadata["pocket_radial_depth_m"]),
        "inner_envelope_x_mm": inner_bounds[1] - inner_bounds[0],
        "inner_envelope_y_mm": inner_bounds[3] - inner_bounds[2],
        "outer_envelope_x_mm": outer_bounds[1] - outer_bounds[0],
        "outer_envelope_y_mm": outer_bounds[3] - outer_bounds[2],
        "cad_gap_note": (
            "The gap-facing shell surfaces are offset by the front-skin thickness, so the concentric full assembly "
            "preserves the optimized magnet-face gap from the high-fidelity simulation."
        ),
        "yoke_note": (
            f"Each pocket is dimensioned to accept one vertical stack of {design['magnet_layers']} x {design['magnet_sku_id']} "
            "magnets and an optional low-carbon-steel back-yoke strip behind that stack."
        ),
        "casing_parameters": asdict(params),
    }
    (outdir / "cad_manifest.json").write_text(json.dumps(notes, indent=2, ensure_ascii=False), encoding="utf-8")

    md_lines = [
        "# Magnetic Coupler CAD Notes",
        "",
        "- Primary Fusion 360 import files are the `.step` solids.",
        "- `full_coupler_assembly.step` is the finished concentric installed assembly.",
        "- `full_coupler_exploded_assembly.step` is the separated assembly for inspection and documentation.",
        "- `inner_carrier_assembly.step` and `outer_carrier_assembly.step` each contain two solid bodies: base and lid.",
        "- The CAD shell offsets already include the front-skin compensation needed to preserve the optimized magnet-face gap.",
        f"- Selected magnet SKU: `{design['magnet_sku_id']}` from `{design['magnet_vendor']}`",
        f"- Magnets per ring: `{design['magnets_per_ring']}`",
        f"- Vertical layers per pocket: `{design['magnet_layers']}`",
        f"- Pocket stack height: `{mm(design['nominal_overlap_m']):.2f} mm`",
        f"- Front skin thickness: `{mm(params.front_skin_m):.2f} mm`",
        f"- Rear flange thickness: `{mm(params.rear_flange_m):.2f} mm`",
        f"- Optional back-yoke seat depth: `{mm(params.back_yoke_pocket_m):.2f} mm`",
        "",
        "## Suggested Physical Stack Per Pocket",
        f"- {design['magnet_layers']} x {design['magnet_sku_id']} magnets stacked axially.",
        f"- Total stack height per pocket: `{mm(design['nominal_overlap_m']):.2f} mm`.",
        "- Optional low-carbon steel backer strip behind the stack, occupying the rear yoke pocket.",
        "- Lid fixed with M3-class fasteners through the provided holes.",
    ]
    (outdir / "assembly_notes.md").write_text("\n".join(md_lines), encoding="utf-8")


def write_package_summary(outdir: Path, design_json: Path, pdf_path: Path, screenshot_path: Path, svg_paths):
    """Writes a compact index of the finished deliverables."""

    summary = {
        "design_json": str(design_json),
        "pdf_drawings": str(pdf_path),
        "assembly_screenshot_png": str(screenshot_path),
        "svg_views": [str(path) for path in svg_paths],
        "step_files": sorted(str(path) for path in outdir.glob("*.step")),
        "stl_files": sorted(str(path) for path in outdir.glob("*.stl")),
        "png_sheets": sorted(str(path) for path in outdir.glob("*sheet.png")),
    }
    (outdir / "cad_package_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_args():
    """Parses CLI arguments for solid CAD export."""

    parser = argparse.ArgumentParser(description="Generate solid STEP/STL casings and drawings for the high-fidelity magnetic coupler design.")
    parser.add_argument(
        "--design-json",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_hifi" / "best_design_hifi.json",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_hifi_cad",
    )
    return parser.parse_args()


def main():
    """Loads the selected design and exports finished CAD, screenshots, and drawings."""

    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    payload, design, geometry = load_selected_design(args.design_json)
    params = CasingParameters()

    inner_pkg = build_inner_base(design, geometry, params)
    outer_pkg = build_outer_base(design, geometry, params)
    inner_lid = build_lid(inner_pkg.outer_profile_m, inner_pkg.inner_profile_m, inner_pkg.hole_sites_m, params)
    outer_lid = build_lid(outer_pkg.outer_profile_m, outer_pkg.inner_profile_m, outer_pkg.hole_sites_m, params)
    inner_assembly, outer_assembly, full_assembly, exploded_assembly = build_assemblies(
        inner_pkg,
        outer_pkg,
        inner_lid,
        outer_lid,
        params,
    )

    export_part(inner_pkg.body, args.outdir / "inner_carrier_base")
    export_part(inner_lid, args.outdir / "inner_carrier_lid")
    export_part(inner_assembly, args.outdir / "inner_carrier_assembly")
    export_part(outer_pkg.body, args.outdir / "outer_carrier_base")
    export_part(outer_lid, args.outdir / "outer_carrier_lid")
    export_part(outer_assembly, args.outdir / "outer_carrier_assembly")
    export_part(full_assembly, args.outdir / "full_coupler_assembly")
    export_part(exploded_assembly, args.outdir / "full_coupler_exploded_assembly")

    svg_paths = []
    svg_paths.extend(export_svg_views(full_assembly, args.outdir, "full_coupler_assembly"))
    svg_paths.extend(export_svg_views(exploded_assembly, args.outdir, "full_coupler_exploded_assembly"))
    screenshot_path = render_isometric_screenshot(args.outdir, inner_pkg, outer_pkg, params)
    pdf_path, png_paths = generate_drawing_package(args.outdir, design, params, inner_pkg, outer_pkg)
    write_notes(args.outdir, args.design_json, payload, params, inner_pkg, outer_pkg)
    write_package_summary(args.outdir, args.design_json, pdf_path, screenshot_path, svg_paths)

    summary = {
        "design_json": str(args.design_json),
        "full_assembly_step": str(args.outdir / "full_coupler_assembly.step"),
        "exploded_assembly_step": str(args.outdir / "full_coupler_exploded_assembly.step"),
        "pdf_drawings": str(pdf_path),
        "assembly_screenshot_png": str(screenshot_path),
        "sheet_pngs": [str(path) for path in png_paths],
        "manifest": str(args.outdir / "cad_manifest.json"),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
