"""Render the current best parametric magnetic-coupler candidate from checkpoints."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon, Rectangle


MAGNET_DIAMETER_M = 0.013
MAGNET_THICKNESS_M = 0.0024
PACKAGE_HALF_WIDTH_M = 0.22
PACKAGE_HALF_LENGTH_M = 0.30


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_best(checkpoint_dir: Path):
    candidates = []
    for path in checkpoint_dir.glob("parametric_checkpoint_*.json"):
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            row["_source"] = str(path)
            candidates.append(row)
    if not candidates:
        raise FileNotFoundError(f"No parametric checkpoints found in {checkpoint_dir}")
    return max(candidates, key=lambda row: float(row["finite_search_utility"]))


def close_curve(points):
    return np.vstack((points, points[0]))


def magnet_footprint(face_xy, direction_angle):
    direction = np.array([math.cos(direction_angle), math.sin(direction_angle)])
    tangent = np.array([-direction[1], direction[0]])
    center = face_xy - 0.5 * MAGNET_THICKNESS_M * direction
    return np.array(
        [
            center - 0.5 * MAGNET_THICKNESS_M * direction - 0.5 * MAGNET_DIAMETER_M * tangent,
            center + 0.5 * MAGNET_THICKNESS_M * direction - 0.5 * MAGNET_DIAMETER_M * tangent,
            center + 0.5 * MAGNET_THICKNESS_M * direction + 0.5 * MAGNET_DIAMETER_M * tangent,
            center - 0.5 * MAGNET_THICKNESS_M * direction + 0.5 * MAGNET_DIAMETER_M * tangent,
        ]
    )


def draw_magnets(axis, angles, radii, tilts, inner):
    face_positions = np.column_stack((radii * np.cos(angles), radii * np.sin(angles)))
    direction_angles = angles + tilts if inner else angles + math.pi + tilts
    fill = "#1565c0" if inner else "#e65100"
    edge = "#073b76" if inner else "#8c2c00"
    for index, (face, direction_angle) in enumerate(zip(face_positions, direction_angles)):
        footprint = magnet_footprint(face, direction_angle)
        axis.add_patch(Polygon(footprint, closed=True, facecolor=fill, edgecolor=edge, linewidth=0.45))
        if index % 4 == 0:
            direction = np.array([math.cos(direction_angle), math.sin(direction_angle)])
            axis.arrow(
                face[0] - 0.005 * direction[0],
                face[1] - 0.005 * direction[1],
                0.010 * direction[0],
                0.010 * direction[1],
                width=0.00035,
                head_width=0.0026,
                head_length=0.0030,
                color="#f7f7f2",
                length_includes_head=True,
                zorder=5,
            )
    return face_positions


def render(candidate, output: Path):
    design = candidate["decoded_design"]
    inner_curve = np.asarray(design["inner_support_points_xy_m"], dtype=float)
    outer_curve = np.asarray(design["outer_support_points_xy_m"], dtype=float)
    inner_angles = np.asarray(design["inner_angles_rad"], dtype=float)
    inner_radii = np.asarray(design["inner_radii_m"], dtype=float)
    inner_tilts = np.asarray(design["inner_tilt_rad"], dtype=float)
    outer_angles = np.asarray(design["outer_angles_rad"], dtype=float)
    outer_radii = np.asarray(design["outer_radii_m"], dtype=float)
    outer_tilts = np.asarray(design["outer_tilt_rad"], dtype=float)

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "axes.titleweight": "bold",
            "axes.edgecolor": "#263238",
            "axes.labelcolor": "#263238",
        }
    )
    figure = plt.figure(figsize=(17.2, 8.8), facecolor="#f1f3f2")
    grid = figure.add_gridspec(1, 3, width_ratios=(1.15, 0.92, 0.63), wspace=0.17)
    top = figure.add_subplot(grid[0, 0])
    detail = figure.add_subplot(grid[0, 1])
    info = figure.add_subplot(grid[0, 2])

    package = Rectangle(
        (-PACKAGE_HALF_WIDTH_M, -PACKAGE_HALF_LENGTH_M),
        2.0 * PACKAGE_HALF_WIDTH_M,
        2.0 * PACKAGE_HALF_LENGTH_M,
        facecolor="#ffffff",
        edgecolor="#546e7a",
        linewidth=1.8,
        linestyle=(0, (5, 4)),
    )
    top.add_patch(package)
    top.fill(close_curve(inner_curve)[:, 0], close_curve(inner_curve)[:, 1], color="#dbeafe", alpha=0.55)
    top.fill(close_curve(outer_curve)[:, 0], close_curve(outer_curve)[:, 1], color="#ffedd5", alpha=0.28)
    top.plot(*close_curve(inner_curve).T, color="#0d47a1", linewidth=1.2, label="inner fixture centerline")
    top.plot(*close_curve(outer_curve).T, color="#bf360c", linewidth=1.2, label="outer fixture centerline")
    draw_magnets(top, inner_angles, inner_radii, inner_tilts, True)
    draw_magnets(top, outer_angles, outer_radii, outer_tilts, False)
    top.scatter([0.0], [0.0], marker="+", s=80, color="#172b36", linewidth=1.5, zorder=8)
    top.annotate(
        "440 mm",
        xy=(-PACKAGE_HALF_WIDTH_M, -0.286),
        xytext=(PACKAGE_HALF_WIDTH_M, -0.286),
        arrowprops={"arrowstyle": "<->", "color": "#37474f"},
        ha="center",
        va="bottom",
        color="#37474f",
    )
    top.annotate(
        "600 mm",
        xy=(0.207, -PACKAGE_HALF_LENGTH_M),
        xytext=(0.207, PACKAGE_HALF_LENGTH_M),
        arrowprops={"arrowstyle": "<->", "color": "#37474f"},
        ha="left",
        va="center",
        rotation=90,
        color="#37474f",
    )
    top.set_xlim(-0.245, 0.245)
    top.set_ylim(-0.325, 0.325)
    top.set_aspect("equal")
    top.set_xlabel("x [m]")
    top.set_ylabel("y [m]")
    top.set_title("Exact saved geometry and magnet footprints")
    top.grid(True, alpha=0.15)
    top.legend(loc="upper left", fontsize=8)

    detail.plot(*close_curve(inner_curve).T, color="#0d47a1", linewidth=1.0)
    detail.plot(*close_curve(outer_curve).T, color="#bf360c", linewidth=1.0)
    draw_magnets(detail, inner_angles, inner_radii, inner_tilts, True)
    draw_magnets(detail, outer_angles, outer_radii, outer_tilts, False)
    detail.set_aspect("equal")
    extent = 1.12 * max(np.max(np.abs(inner_curve)), np.max(np.abs(outer_curve)))
    detail.set_xlim(-extent, extent)
    detail.set_ylim(-extent, extent)
    detail.grid(True, alpha=0.15)
    detail.set_xlabel("x [m]")
    detail.set_ylabel("y [m]")
    detail.set_title("Coupler close-up, top view")

    metrics = (
        f"Current best surrogate candidate\n"
        f"{candidate['config']}\n\n"
        f"Inner / outer sites: {candidate['inner_count']} / {candidate['outer_count']}\n"
        f"Vertical layers: {candidate['layers']} (39 mm nominal stack)\n"
        f"Disk magnet: 13 mm dia. x 2.4 mm thick\n"
        f"Gate result: {candidate['finite_gate_count']:.0f} / 16\n"
        f"Minimum 6 mm force: {candidate['finite_min_force_6mm_n']:.3f} N\n"
        f"Minimum directional stiffness: {candidate['finite_min_directional_stiffness_npm']:.1f} N/m\n"
        f"Minimum pose clearance: {1000*candidate['finite_min_pose_clearance_m']:.2f} mm\n"
        f"Minimum same-ring spacing: {1000*candidate['finite_min_site_spacing_m']:.2f} mm\n\n"
        "White arrows: modeled magnetization direction\n"
        "Blue: robot-side inner ring\n"
        "Orange: cart-side outer ring\n"
        "Footprints overlap vertically because all 3 layers\n"
        "share the same x-y site.\n\n"
        "Fixture rail width, pocket wall thickness,\n"
        "fasteners, and structural material are not\n"
        "optimization variables yet; only their center\n"
        "curves are shown."
    )
    info.axis("off")
    info.text(
        0.02,
        0.94,
        metrics,
        transform=info.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        linespacing=1.4,
        color="#263238",
        bbox={"boxstyle": "round,pad=0.7", "facecolor": "#ffffff", "edgecolor": "#b0bec5"},
    )
    figure.suptitle("Current Best Magnetic Coupler: Physical-Scale Layout", fontsize=17, y=0.97)
    figure.text(
        0.5,
        0.025,
        "Surrogate result only: not yet Magpylib-exact, FEM, tolerance Monte Carlo, or 10 kg dynamic validated.",
        ha="center",
        fontsize=10,
        color="#b23c17",
        weight="bold",
    )
    figure.subplots_adjust(left=0.045, right=0.98, bottom=0.08, top=0.91)
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=220, facecolor=figure.get_facecolor())
    figure.savefig(output.with_suffix(".svg"), facecolor=figure.get_facecolor())
    plt.close(figure)
    output.with_suffix(".json").write_text(json.dumps(candidate, indent=2), encoding="utf-8")


def main():
    args = parse_args()
    render(load_best(args.checkpoint_dir), args.output)


if __name__ == "__main__":
    main()
