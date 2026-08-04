"""Export printable prototype CAD for the current best parametric coupler."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import math
from pathlib import Path

import cadquery as cq
import numpy as np
from cadquery import exporters


MAGNET_DIAMETER_MM = 13.0
MAGNET_THICKNESS_MM = 2.4


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        type=Path,
        default=Path("outputs")
        / "magnetic_coupler_parametric_local_20260724"
        / "current_best_physical_layout.json",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path("outputs")
        / "magnetic_coupler_parametric_local_20260724"
        / "current_best_printable_cad",
    )
    parser.add_argument("--pocket-diameter-mm", type=float, default=13.2)
    parser.add_argument("--pocket-depth-mm", type=float, default=2.5)
    parser.add_argument("--pocket-radial-wall-mm", type=float, default=1.2)
    parser.add_argument("--pocket-boss-depth-mm", type=float, default=5.5)
    parser.add_argument("--pocket-face-setback-mm", type=float, default=1.0)
    parser.add_argument("--wall-depth-mm", type=float, default=8.0)
    parser.add_argument("--flange-width-mm", type=float, default=14.0)
    parser.add_argument("--flange-thickness-mm", type=float, default=4.0)
    parser.add_argument("--axial-wall-mm", type=float, default=3.0)
    return parser.parse_args()


def signed_area(points_xy):
    shifted = np.roll(points_xy, -1, axis=0)
    return 0.5 * float(
        np.sum(points_xy[:, 0] * shifted[:, 1] - shifted[:, 0] * points_xy[:, 1])
    )


def normalized_profile(points_xy):
    points = np.asarray(points_xy, dtype=float)
    if np.linalg.norm(points[0] - points[-1]) <= 1.0e-9:
        points = points[:-1]
    if signed_area(points) < 0.0:
        points = points[::-1]
    return points


def radial_offset(points_xy, offset_mm):
    radius = np.linalg.norm(points_xy, axis=1)
    if np.any(radius <= abs(offset_mm) + 1.0e-6):
        raise ValueError("The requested radial offset collapses the carrier profile.")
    return points_xy * ((radius + offset_mm) / radius)[:, None]


def profile_face(outer_points_mm, inner_points_mm):
    outer = cq.Workplane("XY").polyline([tuple(point) for point in outer_points_mm]).close().val()
    inner = cq.Workplane("XY").polyline([tuple(point) for point in inner_points_mm]).close().val()
    return cq.Face.makeFromWires(outer, [inner])


def annular_body(face_points_mm, body_offset_mm, height_mm):
    back_points_mm = radial_offset(face_points_mm, body_offset_mm)
    if body_offset_mm < 0.0:
        face = profile_face(face_points_mm, back_points_mm)
    else:
        face = profile_face(back_points_mm, face_points_mm)
    return (
        cq.Workplane("XY")
        .add(face)
        .extrude(height_mm)
        .translate((0.0, 0.0, -0.5 * height_mm))
    )


def annular_body_between_offsets(
    face_points_mm, front_offset_mm, back_offset_mm, height_mm
):
    front_points_mm = radial_offset(face_points_mm, front_offset_mm)
    back_points_mm = radial_offset(face_points_mm, back_offset_mm)
    if front_offset_mm > back_offset_mm:
        face = profile_face(front_points_mm, back_points_mm)
    else:
        face = profile_face(back_points_mm, front_points_mm)
    return (
        cq.Workplane("XY")
        .add(face)
        .extrude(height_mm)
        .translate((0.0, 0.0, -0.5 * height_mm))
    )


def pocket_cylinder(face_xyz_mm, axis_to_gap_xyz, radius_mm, depth_mm, overshoot_mm=0.35):
    into_body = -np.asarray(axis_to_gap_xyz, dtype=float)
    into_body /= np.linalg.norm(into_body) + 1.0e-12
    start = np.asarray(face_xyz_mm, dtype=float) - overshoot_mm * into_body
    return cq.Solid.makeCylinder(
        radius_mm,
        depth_mm + overshoot_mm,
        cq.Vector(*start.tolist()),
        cq.Vector(*into_body.tolist()),
    )


def capsule_prism(
    face_xyz_mm,
    axis_to_gap_xyz,
    radius_mm,
    layer_half_span_mm,
    depth_mm,
    overshoot_mm=0.0,
):
    """Builds one vertical stack pocket with a planar face normal to its axis."""

    axis_to_gap = np.asarray(axis_to_gap_xyz, dtype=float)
    axis_to_gap /= np.linalg.norm(axis_to_gap) + 1.0e-12
    into_body = -axis_to_gap
    origin = np.asarray(face_xyz_mm, dtype=float) + overshoot_mm * axis_to_gap
    total_depth_mm = depth_mm + overshoot_mm
    if layer_half_span_mm <= 1.0e-9:
        return cq.Solid.makeCylinder(
            radius_mm,
            total_depth_mm,
            cq.Vector(*origin.tolist()),
            cq.Vector(*into_body.tolist()),
        )

    plane = cq.Plane(
        origin=tuple(origin.tolist()),
        xDir=(0.0, 0.0, 1.0),
        normal=tuple(into_body.tolist()),
    )
    return (
        cq.Workplane(plane)
        .moveTo(-layer_half_span_mm, -radius_mm)
        .lineTo(layer_half_span_mm, -radius_mm)
        .threePointArc(
            (layer_half_span_mm + radius_mm, 0.0),
            (layer_half_span_mm, radius_mm),
        )
        .lineTo(-layer_half_span_mm, radius_mm)
        .threePointArc(
            (-layer_half_span_mm - radius_mm, 0.0),
            (-layer_half_span_mm, -radius_mm),
        )
        .close()
        .extrude(total_depth_mm)
        .val()
    )


def direction_vectors(angles, tilts, inner):
    direction_angles = angles + tilts if inner else angles + math.pi + tilts
    return np.column_stack((np.cos(direction_angles), np.sin(direction_angles)))


def build_ring(
    design,
    ring_name,
    layers,
    pocket_diameter_mm,
    pocket_depth_mm,
    pocket_radial_wall_mm,
    pocket_boss_depth_mm,
    pocket_face_setback_mm,
    wall_depth_mm,
    flange_width_mm,
    flange_thickness_mm,
    axial_wall_mm,
):
    inner = ring_name == "inner"
    if not inner and ring_name != "outer":
        raise ValueError(f"Unknown ring name: {ring_name}")

    prefix = "inner" if inner else "outer"
    face_points_mm = normalized_profile(
        1000.0 * np.asarray(design[f"{prefix}_support_points_xy_m"], dtype=float)
    )
    angles = np.asarray(design[f"{prefix}_angles_rad"], dtype=float)
    radii_mm = 1000.0 * np.asarray(design[f"{prefix}_radii_m"], dtype=float)
    tilts = np.asarray(design[f"{prefix}_tilt_rad"], dtype=float)
    directions_xy = direction_vectors(angles, tilts, inner)

    carrier_height_mm = layers * MAGNET_DIAMETER_MM + 2.0 * axial_wall_mm
    body_offset_mm = -wall_depth_mm if inner else wall_depth_mm
    front_offset_mm = -pocket_face_setback_mm if inner else pocket_face_setback_mm
    flange_offset_mm = -flange_width_mm if inner else flange_width_mm
    body = annular_body_between_offsets(
        face_points_mm,
        front_offset_mm,
        body_offset_mm,
        carrier_height_mm,
    )
    flange = annular_body(face_points_mm, flange_offset_mm, flange_thickness_mm).translate(
        (0.0, 0.0, -0.5 * carrier_height_mm - 0.5 * flange_thickness_mm)
    )
    body = body.union(flange)

    layer_z_mm = (
        np.arange(layers, dtype=float) - 0.5 * (layers - 1)
    ) * MAGNET_DIAMETER_MM
    pocket_rows = []
    cuts = []
    bosses = []
    for site_index, (angle, radius_mm, direction_xy) in enumerate(
        zip(angles, radii_mm, directions_xy)
    ):
        face_xy_mm = radius_mm * np.array([math.cos(angle), math.sin(angle)], dtype=float)
        axis_xyz = np.array([direction_xy[0], direction_xy[1], 0.0], dtype=float)
        for layer_index, z_mm in enumerate(layer_z_mm):
            face_xyz_mm = np.array([face_xy_mm[0], face_xy_mm[1], z_mm], dtype=float)
            pocket_rows.append(
                {
                    "ring": ring_name,
                    "site_index": site_index,
                    "layer_index": layer_index,
                    "face_x_mm": float(face_xyz_mm[0]),
                    "face_y_mm": float(face_xyz_mm[1]),
                    "face_z_mm": float(face_xyz_mm[2]),
                    "axis_to_gap_x": float(axis_xyz[0]),
                    "axis_to_gap_y": float(axis_xyz[1]),
                    "axis_to_gap_z": 0.0,
                    "pocket_diameter_mm": pocket_diameter_mm,
                    "pocket_depth_mm": pocket_depth_mm,
                    "boss_diameter_mm": pocket_diameter_mm
                    + 2.0 * pocket_radial_wall_mm,
                    "boss_depth_mm": pocket_boss_depth_mm,
                }
            )
        stack_face_xyz_mm = np.array([face_xy_mm[0], face_xy_mm[1], 0.0], dtype=float)
        layer_half_span_mm = 0.5 * (layers - 1) * MAGNET_DIAMETER_MM
        bosses.append(
            capsule_prism(
                stack_face_xyz_mm,
                axis_xyz,
                0.5 * pocket_diameter_mm + pocket_radial_wall_mm,
                layer_half_span_mm,
                pocket_boss_depth_mm,
            )
        )
        cuts.append(
            capsule_prism(
                stack_face_xyz_mm,
                axis_xyz,
                0.5 * pocket_diameter_mm,
                layer_half_span_mm,
                pocket_depth_mm,
                overshoot_mm=0.35,
            )
        )

    body_shape = body.val().fuse(*bosses)
    if body_shape.isNull() or not body_shape.isValid():
        raise RuntimeError(f"{ring_name} carrier is invalid after adding pocket bosses.")
    body = cq.Workplane("XY").add(body_shape)
    uncut_volume_mm3 = float(body.val().Volume())
    shape = body.val()
    for site_index, cut_tool in enumerate(cuts):
        try:
            shape = shape.cut(cut_tool, tol=1.0e-4).clean()
        except Exception as exc:
            raise RuntimeError(
                f"{ring_name} carrier boolean failed while cutting site {site_index}."
            ) from exc
        if not shape.isNull() and not shape.isValid():
            shape = shape.fix()
        if shape.isNull() or not shape.isValid():
            raise RuntimeError(
                f"{ring_name} carrier became invalid while cutting site {site_index}."
            )
    body = cq.Workplane("XY").add(shape)
    if not shape.isValid():
        raise RuntimeError(f"{ring_name} carrier is not a valid BRep after pocket cutting.")

    removed_volume_mm3 = uncut_volume_mm3 - float(shape.Volume())
    nominal_pocket_volume_mm3 = (
        len(pocket_rows) * math.pi * (0.5 * pocket_diameter_mm) ** 2 * pocket_depth_mm
    )
    removal_fraction = removed_volume_mm3 / max(nominal_pocket_volume_mm3, 1.0e-9)
    if removal_fraction < 0.70:
        raise RuntimeError(
            f"{ring_name} pocket cuts removed only {removal_fraction:.1%} of the "
            "nominal cavity volume."
        )
    bounding_box = shape.BoundingBox()
    metadata = {
        "ring": ring_name,
        "site_count": len(angles),
        "layer_count": layers,
        "pocket_count": len(pocket_rows),
        "carrier_height_mm": carrier_height_mm,
        "wall_depth_mm": wall_depth_mm,
        "flange_width_mm": flange_width_mm,
        "flange_thickness_mm": flange_thickness_mm,
        "pocket_diameter_mm": pocket_diameter_mm,
        "pocket_depth_mm": pocket_depth_mm,
        "pocket_radial_wall_mm": pocket_radial_wall_mm,
        "pocket_boss_depth_mm": pocket_boss_depth_mm,
        "pocket_face_setback_mm": pocket_face_setback_mm,
        "magnet_protrusion_mm": max(MAGNET_THICKNESS_MM - pocket_depth_mm, 0.0),
        "magnet_recess_mm": max(pocket_depth_mm - MAGNET_THICKNESS_MM, 0.0),
        "solid_volume_mm3": float(shape.Volume()),
        "removed_pocket_volume_mm3": removed_volume_mm3,
        "nominal_pocket_volume_mm3": nominal_pocket_volume_mm3,
        "pocket_volume_removal_fraction": removal_fraction,
        "bounding_box_mm": {
            "x": bounding_box.xlen,
            "y": bounding_box.ylen,
            "z": bounding_box.zlen,
        },
        "brep_valid": True,
    }
    return body, pocket_rows, metadata


def minimum_site_spacing_mm(rows, ring_name):
    points = np.asarray(
        [
            [row["face_x_mm"], row["face_y_mm"]]
            for row in rows
            if row["ring"] == ring_name and row["layer_index"] == 0
        ],
        dtype=float,
    )
    distance = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)
    distance += np.eye(len(points)) * 1.0e9
    return float(np.min(distance))


def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def export_shape(shape, step_path, stl_path):
    exporters.export(shape, str(step_path))
    exporters.export(shape, str(stl_path), tolerance=0.08, angularTolerance=0.08)


def magnet_placeholders(pocket_rows, pocket_depth_mm):
    recess_mm = max(pocket_depth_mm - MAGNET_THICKNESS_MM, 0.0)
    magnets = []
    for row in pocket_rows:
        face = np.array(
            [row["face_x_mm"], row["face_y_mm"], row["face_z_mm"]], dtype=float
        )
        axis_to_gap = np.array(
            [
                row["axis_to_gap_x"],
                row["axis_to_gap_y"],
                row["axis_to_gap_z"],
            ],
            dtype=float,
        )
        into_body = -axis_to_gap
        start = face + recess_mm * into_body
        magnets.append(
            cq.Solid.makeCylinder(
                0.5 * MAGNET_DIAMETER_MM,
                MAGNET_THICKNESS_MM,
                cq.Vector(*start.tolist()),
                cq.Vector(*into_body.tolist()),
            )
        )
    return magnets


def opposing_axis_alignment(inner_rows, outer_rows):
    inner = [row for row in inner_rows if row["layer_index"] == 0]
    outer = [row for row in outer_rows if row["layer_index"] == 0]
    inner_points = np.asarray(
        [[row["face_x_mm"], row["face_y_mm"]] for row in inner], dtype=float
    )
    outer_points = np.asarray(
        [[row["face_x_mm"], row["face_y_mm"]] for row in outer], dtype=float
    )
    inner_axes = np.asarray(
        [[row["axis_to_gap_x"], row["axis_to_gap_y"]] for row in inner], dtype=float
    )
    outer_axes = np.asarray(
        [[row["axis_to_gap_x"], row["axis_to_gap_y"]] for row in outer], dtype=float
    )
    distance = np.linalg.norm(
        inner_points[:, None, :] - outer_points[None, :, :], axis=2
    )
    nearest_outer = np.argmin(distance, axis=1)
    nearest_inner = np.argmin(distance, axis=0)
    inner_target = outer_points[nearest_outer] - inner_points
    outer_target = inner_points[nearest_inner] - outer_points
    inner_target /= np.linalg.norm(inner_target, axis=1, keepdims=True)
    outer_target /= np.linalg.norm(outer_target, axis=1, keepdims=True)
    inner_dot = np.sum(inner_axes * inner_target, axis=1)
    outer_dot = np.sum(outer_axes * outer_target, axis=1)
    combined = np.concatenate((inner_dot, outer_dot))
    return {
        "minimum_toward_opposing_ring_dot": float(np.min(combined)),
        "mean_toward_opposing_ring_dot": float(np.mean(combined)),
        "maximum_axis_misalignment_deg": float(
            np.degrees(np.arccos(np.clip(np.min(combined), -1.0, 1.0)))
        ),
        "minimum_face_center_distance_mm": float(np.min(distance)),
    }


def write_readme(path, candidate, validation):
    metadata = validation["inner"]
    lines = [
        "# Current-best parametric coupler prototype CAD",
        "",
        "This directory reproduces the saved current-best surrogate geometry. It is printable prototype CAD, not a validated production release.",
        "",
        "## Candidate",
        f"- Configuration: `{candidate['config']}`",
        f"- Search generation/evaluation: `{candidate['generation']}` / `{candidate['evaluation']}`",
        f"- Static surrogate gates: `{candidate['finite_gate_count']:.0f}/16`",
        f"- Inner/outer sites: `{candidate['inner_count']}` / `{candidate['outer_count']}`",
        f"- Layers: `{candidate['layers']}`",
        "",
        "## Pocket and carrier assumptions",
        f"- Pocket: diameter `{metadata['pocket_diameter_mm']:.2f} mm`, depth `{metadata['pocket_depth_mm']:.2f} mm`.",
        f"- Assumed magnet: diameter `{MAGNET_DIAMETER_MM:.2f} mm`, thickness `{MAGNET_THICKNESS_MM:.2f} mm`.",
        f"- Magnet protrusion from the pocket: `{metadata['magnet_protrusion_mm']:.2f} mm`.",
        f"- Magnet recess from the pocket entrance: `{metadata['magnet_recess_mm']:.2f} mm`.",
        f"- Local pocket boss wall/depth: `{metadata['pocket_radial_wall_mm']:.2f}` / `{metadata['pocket_boss_depth_mm']:.2f} mm`.",
        f"- Carrier setback behind pocket faces: `{metadata['pocket_face_setback_mm']:.2f} mm`.",
        f"- Carrier wall depth: `{metadata['wall_depth_mm']:.2f} mm`.",
        f"- Base flange width/thickness: `{metadata['flange_width_mm']:.2f}` / `{metadata['flange_thickness_mm']:.2f} mm`.",
        "",
        "## Files",
        "- `inner_ring_current_best.step` and `.stl`: robot-side carrier.",
        "- `outer_ring_current_best.step` and `.stl`: cart-side carrier.",
        "- `assembly_current_best.step`: concentric nominal holder assembly.",
        "- `assembly_with_magnet_placeholders.step`: holder assembly with all nominal magnets.",
        "- `magnet_pockets.csv`: every pocket center, layer, and gap-facing axis.",
        "- `cad_validation.json`: exact export dimensions and BRep validation.",
        "",
        "## Required before machine use",
        "- Confirm printer build volume; the outer carrier is intentionally exported as one monolithic part.",
        "- Add the actual LIMO/cart mounting-hole pattern after measuring both interfaces.",
        "- Select material, layer direction, adhesive or retaining cap, and safety factor.",
        "- Revalidate the magnetic model using measured force maps, FEM, tolerance Monte Carlo, and no-contact 10 kg dynamics.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    design = candidate["decoded_design"]
    args.outdir.mkdir(parents=True, exist_ok=True)

    inner_body, inner_rows, inner_meta = build_ring(
        design,
        "inner",
        int(candidate["layers"]),
        args.pocket_diameter_mm,
        args.pocket_depth_mm,
        args.pocket_radial_wall_mm,
        args.pocket_boss_depth_mm,
        args.pocket_face_setback_mm,
        args.wall_depth_mm,
        args.flange_width_mm,
        args.flange_thickness_mm,
        args.axial_wall_mm,
    )
    outer_body, outer_rows, outer_meta = build_ring(
        design,
        "outer",
        int(candidate["layers"]),
        args.pocket_diameter_mm,
        args.pocket_depth_mm,
        args.pocket_radial_wall_mm,
        args.pocket_boss_depth_mm,
        args.pocket_face_setback_mm,
        args.wall_depth_mm,
        args.flange_width_mm,
        args.flange_thickness_mm,
        args.axial_wall_mm,
    )

    export_shape(
        inner_body,
        args.outdir / "inner_ring_current_best.step",
        args.outdir / "inner_ring_current_best.stl",
    )
    export_shape(
        outer_body,
        args.outdir / "outer_ring_current_best.step",
        args.outdir / "outer_ring_current_best.stl",
    )
    assembly = cq.Compound.makeCompound([inner_body.val(), outer_body.val()])
    exporters.export(assembly, str(args.outdir / "assembly_current_best.step"))

    pocket_rows = inner_rows + outer_rows
    magnets = magnet_placeholders(pocket_rows, args.pocket_depth_mm)
    assembly_with_magnets = cq.Compound.makeCompound(
        [inner_body.val(), outer_body.val(), *magnets]
    )
    exporters.export(
        assembly_with_magnets,
        str(args.outdir / "assembly_with_magnet_placeholders.step"),
    )
    write_csv(args.outdir / "magnet_pockets.csv", pocket_rows)
    validation = {
        "source_candidate": str(args.candidate),
        "candidate_config": candidate["config"],
        "surrogate_gate_count": candidate["finite_gate_count"],
        "surrogate_candidate_only": True,
        "inner": inner_meta,
        "outer": outer_meta,
        "minimum_site_spacing_mm": {
            "inner": minimum_site_spacing_mm(pocket_rows, "inner"),
            "outer": minimum_site_spacing_mm(pocket_rows, "outer"),
        },
        "total_pocket_count": len(pocket_rows),
        "pocket_diameter_mm": args.pocket_diameter_mm,
        "pocket_depth_mm": args.pocket_depth_mm,
        "magnet_diameter_mm": MAGNET_DIAMETER_MM,
        "magnet_thickness_mm": MAGNET_THICKNESS_MM,
        "magnet_protrusion_mm": max(
            MAGNET_THICKNESS_MM - args.pocket_depth_mm, 0.0
        ),
        "magnet_recess_mm": max(args.pocket_depth_mm - MAGNET_THICKNESS_MM, 0.0),
        "opposing_axis_alignment": opposing_axis_alignment(inner_rows, outer_rows),
        "reference_holder_basis": {
            "source": "magnet_holder_casterside (~recovered).step",
            "measured_pocket_diameter_mm": 13.2,
            "dominant_measured_pocket_depth_mm": 2.5,
            "construction": "local planar seat normal to each pocket axis",
        },
        "cad_kernel": f"CadQuery {importlib.metadata.version('cadquery')}",
    }
    (args.outdir / "cad_validation.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    write_readme(args.outdir / "README.md", candidate, validation)
    print(json.dumps(validation, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
