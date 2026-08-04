import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image

matplotlib.use("Agg")

import matplotlib.pyplot as plt


ROOT = Path(r"C:\Users\user\OneDrive - 和歌山大学\ソーラー\エネマネ\solar_ws0129-main")
OUTDIR = ROOT / "outputs" / "magnetic_coupler_rl_discrete"
BEST_JSON = OUTDIR / "best_design.json"
SOURCE_FILE = ROOT / "mpc_solarcar" / "magnetic_coupler_rl.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_rl as mcrl


def load_selected_design():
    payload = json.loads(BEST_JSON.read_text(encoding="utf-8"))
    design = mcrl.Design(**payload["design"])
    policy = mcrl.Policy(**payload["policy"])
    return payload, design, policy


def rerun_validation_records(design, policy, seed=42):
    validation_scenarios = mcrl.build_validation_suite(seed, 0.03)
    geometry = mcrl.build_geometry(design.shape_name, design.mean_radius_m, design.gap_m, 56)
    rng = np.random.default_rng(seed + 8000)
    results = []
    for scenario in validation_scenarios:
        leakage_factor = rng.uniform(0.095, 0.145)
        drag_scale = rng.uniform(0.88, 1.14)
        phase_shift = rng.normal(0.0, 0.016)
        scenario_design = mcrl.Design(
            shape_name=design.shape_name,
            gap_m=design.gap_m,
            mean_radius_m=design.mean_radius_m,
            radial_depth_m=design.radial_depth_m,
            nominal_overlap_m=design.nominal_overlap_m,
            max_overlap_reduction_m=design.max_overlap_reduction_m,
            cart_mass_kg=design.cart_mass_kg,
            actuator_tau_s=design.actuator_tau_s,
            actuator_rate_limit_mps=design.actuator_rate_limit_mps,
            leakage_factor=leakage_factor,
            magnet_sku_id=design.magnet_sku_id,
            magnet_vendor=design.magnet_vendor,
            unit_price_jpy=design.unit_price_jpy,
            magnet_tangential_length_m=design.magnet_tangential_length_m,
            magnet_axial_height_m=design.magnet_axial_height_m,
            magnets_per_ring=design.magnets_per_ring,
            magnet_layers=design.magnet_layers,
            coverage_ratio=max(0.48, min(0.95, design.coverage_ratio + rng.normal(0.0, 0.02))),
            pitch_m=design.pitch_m,
            tangential_gap_m=max(0.0, design.tangential_gap_m + rng.normal(0.0, 0.00035)),
            outer_phase_fraction=design.outer_phase_fraction + phase_shift,
            edge_cogging_gain=max(0.05, design.edge_cogging_gain * rng.uniform(0.92, 1.08)),
            total_magnets=design.total_magnets,
            estimated_total_cost_jpy=design.estimated_total_cost_jpy,
            surface_flux_t=design.surface_flux_t,
            pull_force_n=design.pull_force_n,
        )
        result = mcrl.simulate_episode(
            design=scenario_design,
            policy=policy,
            geometry=geometry,
            scenario=scenario,
            drag_scale=drag_scale,
            record=True,
        )
        results.append((scenario_design, scenario, result))
    return geometry, results


def sample_curve_points(points, count):
    indices = np.linspace(0, len(points) - 1, count, endpoint=False).astype(int)
    return points[indices]


def transform_points(points, translation_xy, yaw_rad):
    rotation = mcrl.rotmat(yaw_rad)
    return points @ rotation.T + translation_xy


def build_magnet_markers(geometry, design):
    inner_indices = np.linspace(0, len(geometry.inner_points) - 1, design.magnets_per_ring, endpoint=False).astype(int)
    outer_indices = (
        np.linspace(0, len(geometry.outer_points_local) - 1, design.magnets_per_ring, endpoint=False)
        + design.outer_phase_fraction * len(geometry.outer_points_local) / design.magnets_per_ring
    )
    outer_indices = np.round(outer_indices).astype(int) % len(geometry.outer_points_local)

    inner_points = geometry.inner_points[inner_indices]
    inner_normals = geometry.inner_normals[inner_indices]
    outer_points = geometry.outer_points_local[outer_indices]
    outer_normals = geometry.outer_outward_normals_local[outer_indices]

    inner_centers = inner_points - 0.5 * design.radial_depth_m * inner_normals
    outer_centers = outer_points + 0.5 * design.radial_depth_m * outer_normals
    return inner_centers, inner_normals, outer_centers, outer_normals


def render_gui_frame(geometry, design, scenario_name, record, index):
    time_s = record["time_s"][index]
    rel_xy = np.array([record["rel_x_m"][index], record["rel_y_m"][index]], dtype=float)
    rel_yaw = record["rel_yaw_rad"][index]
    min_gap = record["min_gap_m"][index]
    overlap = record["overlap_m"][index]
    reduction = record["overlap_reduction_m"][index]
    coverage = record["coverage_match"][index]
    cogging = record["cogging_ratio"][index]
    phase = int(record["phase"][index])

    figure = plt.figure(figsize=(8.8, 5.9), dpi=100)
    grid = figure.add_gridspec(2, 2, height_ratios=[3.0, 2.1], width_ratios=[2.1, 1.4], hspace=0.28, wspace=0.22)
    ax_pose = figure.add_subplot(grid[:, 0])
    ax_gap = figure.add_subplot(grid[0, 1])
    ax_status = figure.add_subplot(grid[1, 1])

    inner_outline = geometry.inner_points
    outer_outline = transform_points(geometry.outer_points_local, rel_xy, rel_yaw)
    ax_pose.fill(inner_outline[:, 0], inner_outline[:, 1], color="#c7d2fe", alpha=0.75, label="robot side")
    ax_pose.plot(inner_outline[:, 0], inner_outline[:, 1], color="#1d4ed8", linewidth=2.0)
    ax_pose.fill(outer_outline[:, 0], outer_outline[:, 1], color="#fecaca", alpha=0.52, label="cart side")
    ax_pose.plot(outer_outline[:, 0], outer_outline[:, 1], color="#b91c1c", linewidth=2.0)

    inner_magnets, inner_normals, outer_magnets, outer_normals = build_magnet_markers(geometry, design)
    outer_magnets_t = transform_points(outer_magnets, rel_xy, rel_yaw)
    outer_normals_t = outer_normals @ mcrl.rotmat(rel_yaw).T
    ax_pose.quiver(
        inner_magnets[:, 0],
        inner_magnets[:, 1],
        inner_normals[:, 0],
        inner_normals[:, 1],
        color="#1e40af",
        width=0.004,
        scale=20.0,
    )
    ax_pose.quiver(
        outer_magnets_t[:, 0],
        outer_magnets_t[:, 1],
        -outer_normals_t[:, 0],
        -outer_normals_t[:, 1],
        color="#991b1b",
        width=0.004,
        scale=20.0,
    )

    phase_labels = {
        0: "idle",
        1: "translation intent",
        2: "turn intent",
        3: "combined intent",
    }
    ax_pose.set_title(f"Selected Design GUI Playback\n{scenario_name}  t={time_s:4.2f} s  phase={phase_labels.get(phase, 'n/a')}")
    ax_pose.set_aspect("equal", adjustable="box")
    span = max(geometry.max_radius_m + design.gap_m + 0.07, 0.26)
    ax_pose.set_xlim(-span, span)
    ax_pose.set_ylim(-span, span)
    ax_pose.grid(True, alpha=0.25)
    ax_pose.legend(loc="upper right", fontsize=8)

    timeline = np.array(record["time_s"], dtype=float)
    min_gap_mm = 1000.0 * np.array(record["min_gap_m"], dtype=float)
    rel_yaw_deg = np.degrees(np.array(record["rel_yaw_rad"], dtype=float))
    overlap_mm = 1000.0 * np.array(record["overlap_m"], dtype=float)
    ax_gap.plot(timeline, min_gap_mm, color="#7c3aed", linewidth=1.8, label="min gap [mm]")
    ax_gap.plot(timeline, rel_yaw_deg, color="#0f766e", linewidth=1.6, label="relative yaw [deg]")
    ax_gap.plot(timeline, overlap_mm, color="#f59e0b", linewidth=1.4, label="overlap [mm]")
    ax_gap.axvline(time_s, color="#111827", linestyle="--", linewidth=1.2)
    ax_gap.axhline(0.0, color="#dc2626", linestyle=":", linewidth=1.0)
    ax_gap.set_title("Telemetry Trends")
    ax_gap.set_xlabel("time [s]")
    ax_gap.grid(True, alpha=0.25)
    ax_gap.legend(loc="best", fontsize=8)

    ax_status.axis("off")
    status_lines = [
        "Selected design",
        f"shape = {design.shape_name}",
        f"SKU = {design.magnet_sku_id}",
        f"magnets/ring = {design.magnets_per_ring}",
        f"layers = {design.magnet_layers}",
        f"total cost ~= {design.estimated_total_cost_jpy:,.0f} JPY",
        "",
        "Instant state",
        f"rel x = {1000.0 * rel_xy[0]:6.2f} mm",
        f"rel y = {1000.0 * rel_xy[1]:6.2f} mm",
        f"rel yaw = {math.degrees(rel_yaw):6.2f} deg",
        f"min gap = {1000.0 * min_gap:6.2f} mm",
        f"overlap = {1000.0 * overlap:6.2f} mm",
        f"height reduction = {1000.0 * reduction:6.2f} mm",
        f"coverage match = {coverage:5.3f}",
        f"edge cogging = {cogging:5.3f}",
    ]
    ax_status.text(
        0.02,
        0.98,
        "\n".join(status_lines),
        va="top",
        ha="left",
        family="monospace",
        fontsize=9,
    )
    return figure


def save_gui_animation(geometry, design, results):
    chosen_names = {"translation_turn_253", "gentle_arc_299", "contact_challenge_335"}
    selected = [(scenario_name, record) for _, scenario, result in results for scenario_name, record in [(scenario.name, result.record)] if scenario.name in chosen_names]
    if not selected:
        selected = [(scenario.name, result.record) for _, scenario, result in results[:3]]

    frames = []
    storyboard = plt.figure(figsize=(12.0, 6.8), dpi=140)
    storyboard_axes = storyboard.subplots(2, 3)
    storyboard_axes = storyboard_axes.flatten()
    storyboard_slot = 0

    for scenario_name, record in selected:
        total = len(record["time_s"])
        for idx in range(0, total, 8):
            fig = render_gui_frame(geometry, design, scenario_name, record, idx)
            fig.canvas.draw()
            image = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
            image = image.reshape(fig.canvas.get_width_height()[::-1] + (4,))
            pil_image = Image.fromarray(image[:, :, :3]).convert("P", palette=Image.ADAPTIVE)
            frames.append(pil_image)
            if idx in {0, total // 2, total - 1} and storyboard_slot < len(storyboard_axes):
                ax = storyboard_axes[storyboard_slot]
                ax.imshow(image[:, :, :3])
                ax.set_title(f"{scenario_name}\nframe {idx}", fontsize=8)
                ax.axis("off")
                storyboard_slot += 1
            plt.close(fig)

    for ax in storyboard_axes[storyboard_slot:]:
        ax.axis("off")
    storyboard.tight_layout()
    storyboard_path = OUTDIR / "selected_design_gui_storyboard.png"
    storyboard.savefig(storyboard_path, dpi=180)
    plt.close(storyboard)

    gif_path = OUTDIR / "selected_design_gui.gif"
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=140,
        loop=0,
        disposal=2,
        optimize=True,
    )
    return gif_path, storyboard_path


def discrete_magnet_centers_and_moments(geometry, design, layers=None):
    if layers is None:
        layers = design.magnet_layers
    dense = 512
    dense_geom = mcrl.build_geometry(design.shape_name, design.mean_radius_m, design.gap_m, dense)
    inner_indices = np.linspace(0, len(dense_geom.inner_points) - 1, design.magnets_per_ring, endpoint=False).astype(int)
    outer_indices = (
        np.linspace(0, len(dense_geom.outer_points_local) - 1, design.magnets_per_ring, endpoint=False)
        + design.outer_phase_fraction * len(dense_geom.outer_points_local) / design.magnets_per_ring
    )
    outer_indices = np.round(outer_indices).astype(int) % len(dense_geom.outer_points_local)

    inner_points = dense_geom.inner_points[inner_indices]
    inner_normals = dense_geom.inner_normals[inner_indices]
    outer_points = dense_geom.outer_points_local[outer_indices]
    outer_normals = dense_geom.outer_outward_normals_local[outer_indices]

    layer_offsets = (np.arange(layers) - 0.5 * (layers - 1)) * design.magnet_axial_height_m
    magnet_volume = (
        design.magnet_tangential_length_m * design.magnet_axial_height_m * design.radial_depth_m
    )
    dipole_moment_mag = design.surface_flux_t * magnet_volume / mcrl.MU0

    centers = []
    moments = []
    for z_center in layer_offsets:
        for point, normal in zip(inner_points, inner_normals):
            center = np.array([point[0] - 0.5 * design.radial_depth_m * normal[0], point[1] - 0.5 * design.radial_depth_m * normal[1], z_center])
            moment = np.array([normal[0], normal[1], 0.0]) * dipole_moment_mag
            centers.append(center)
            moments.append(moment)
        for point, normal in zip(outer_points, outer_normals):
            center = np.array([point[0] + 0.5 * design.radial_depth_m * normal[0], point[1] + 0.5 * design.radial_depth_m * normal[1], z_center])
            moment = np.array([-normal[0], -normal[1], 0.0]) * dipole_moment_mag
            centers.append(center)
            moments.append(moment)
    return np.asarray(centers), np.asarray(moments), dense_geom


def dipole_field(points_xyz, centers_xyz, moments_xyz):
    field = np.zeros_like(points_xyz, dtype=float)
    constant = mcrl.MU0 / (4.0 * math.pi)
    for center, moment in zip(centers_xyz, moments_xyz):
        vector = points_xyz - center
        distance_sq = np.sum(vector * vector, axis=1) + 1.0e-10
        distance = np.sqrt(distance_sq)
        r_hat = vector / distance[:, None]
        moment_dot = np.sum(r_hat * moment, axis=1)
        contribution = constant * (3.0 * moment_dot[:, None] * r_hat - moment) / (distance_sq * distance)[:, None]
        field += contribution
    return field


def save_field_distribution(design):
    centers, moments, dense_geom = discrete_magnet_centers_and_moments(None, design)
    span_xy = design.mean_radius_m + design.gap_m + design.radial_depth_m + 0.07
    x = np.linspace(-span_xy, span_xy, 91)
    y = np.linspace(-span_xy, span_xy, 91)
    xx, yy = np.meshgrid(x, y)
    top_points = np.column_stack((xx.ravel(), yy.ravel(), np.zeros(xx.size)))
    top_field = dipole_field(top_points, centers, moments).reshape(xx.shape + (3,))
    top_mag_mt = 1000.0 * np.linalg.norm(top_field, axis=2)

    z = np.linspace(-0.05, 0.05, 71)
    xx2, zz2 = np.meshgrid(x, z)
    side_points = np.column_stack((xx2.ravel(), np.zeros(xx2.size), zz2.ravel()))
    side_field = dipole_field(side_points, centers, moments).reshape(xx2.shape + (3,))
    side_mag_mt = 1000.0 * np.linalg.norm(side_field, axis=2)

    figure, axes = plt.subplots(1, 2, figsize=(12.5, 5.8), dpi=160)
    im0 = axes[0].imshow(
        top_mag_mt,
        extent=[x.min(), x.max(), y.min(), y.max()],
        origin="lower",
        cmap="magma",
        aspect="equal",
    )
    axes[0].plot(dense_geom.inner_points[:, 0], dense_geom.inner_points[:, 1], color="white", linewidth=1.5)
    axes[0].plot(dense_geom.outer_points_local[:, 0], dense_geom.outer_points_local[:, 1], color="#93c5fd", linewidth=1.4)
    stride = 7
    axes[0].quiver(
        xx[::stride, ::stride],
        yy[::stride, ::stride],
        top_field[::stride, ::stride, 0],
        top_field[::stride, ::stride, 1],
        color="white",
        scale=30.0,
        width=0.0025,
    )
    axes[0].set_title("Selected Finite-Array Field\nTop View z = 0 m")
    axes[0].set_xlabel("x [m]")
    axes[0].set_ylabel("y [m]")
    figure.colorbar(im0, ax=axes[0], shrink=0.82, label="|B| [mT]")

    im1 = axes[1].imshow(
        side_mag_mt,
        extent=[x.min(), x.max(), z.min(), z.max()],
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
        scale=35.0,
        width=0.0028,
    )
    layer_heights = (np.arange(design.magnet_layers) - 0.5 * (design.magnet_layers - 1)) * design.magnet_axial_height_m
    for z_center in layer_heights:
        axes[1].axhspan(
            z_center - 0.5 * design.magnet_axial_height_m,
            z_center + 0.5 * design.magnet_axial_height_m,
            xmin=0.02,
            xmax=0.08,
            color="#ef4444",
            alpha=0.18,
        )
        axes[1].axhspan(
            z_center - 0.5 * design.magnet_axial_height_m,
            z_center + 0.5 * design.magnet_axial_height_m,
            xmin=0.92,
            xmax=0.98,
            color="#1d4ed8",
            alpha=0.18,
        )
    axes[1].set_title("Selected Finite-Array Field\nx-z Slice at y = 0 m")
    axes[1].set_xlabel("x [m]")
    axes[1].set_ylabel("z [m]")
    figure.colorbar(im1, ax=axes[1], shrink=0.82, label="|B| [mT]")
    figure.tight_layout()
    field_path = OUTDIR / "selected_design_field_distribution.png"
    figure.savefig(field_path, dpi=180)
    plt.close(figure)
    return field_path


def choose_text(lang, en_text, ja_text):
    return ja_text if lang == "ja" else en_text


def explain_line(line, lang="en"):
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("import "):
        return choose_text(
            lang,
            "Imports a Python module used later in the simulation or reporting pipeline.",
            "後続のシミュレーション、最適化、または報告書生成で使う Python モジュールを読み込む。",
        )
    if stripped.startswith("from "):
        return choose_text(
            lang,
            "Imports a specific symbol from another module so this file can call it directly.",
            "別モジュールから必要なシンボルを直接読み込み、このファイル内でそのまま呼び出せるようにする。",
        )
    if stripped.startswith("@dataclass"):
        return choose_text(
            lang,
            "Marks the next class as a dataclass so field definitions become structured data containers.",
            "次のクラスを dataclass として扱い、フィールド定義を構造化データとして使えるようにする。",
        )
    if stripped.startswith("class "):
        match = re.match(r"class\s+([A-Za-z0-9_]+)", stripped)
        if match:
            return choose_text(
                lang,
                f"Declares the `{match.group(1)}` class.",
                f"`{match.group(1)}` クラスを定義する。",
            )
        return choose_text(lang, "Declares a class.", "クラスを定義する。")
    if stripped.startswith("def "):
        match = re.match(r"def\s+([A-Za-z0-9_]+)", stripped)
        if match:
            return choose_text(
                lang,
                f"Defines the `{match.group(1)}` function.",
                f"`{match.group(1)}` 関数を定義する。",
            )
        return choose_text(lang, "Defines a function.", "関数を定義する。")
    if stripped.startswith(("return ", "return(")) or stripped == "return":
        return choose_text(
            lang,
            "Returns the value assembled in the current function.",
            "現在の関数内で組み立てた値を呼び出し元へ返す。",
        )
    if stripped.startswith("if "):
        return choose_text(
            lang,
            "Starts a conditional branch that executes only when its condition is true.",
            "条件が真のときだけ実行される条件分岐を開始する。",
        )
    if stripped.startswith("elif "):
        return choose_text(
            lang,
            "Adds another conditional case after the previous `if` / `elif` branches.",
            "直前の `if` / `elif` に続く追加条件の分岐を定義する。",
        )
    if stripped == "else:":
        return choose_text(
            lang,
            "Defines the fallback branch when earlier conditions are not met.",
            "前の条件に当てはまらない場合の分岐を定義する。",
        )
    if stripped.startswith("for "):
        return choose_text(
            lang,
            "Starts a loop that iterates through a sequence of states, scenarios, magnets, or samples.",
            "状態、シナリオ、磁石、サンプルなどを順に走査するループを開始する。",
        )
    if stripped.startswith("while "):
        return choose_text(
            lang,
            "Starts a loop that continues until a stopping condition is met.",
            "停止条件が満たされるまで継続するループを開始する。",
        )
    if stripped.startswith("break"):
        return choose_text(lang, "Stops the current loop immediately.", "現在のループをその場で終了する。")
    if stripped.startswith("continue"):
        return choose_text(
            lang,
            "Skips the rest of the current loop body and moves to the next iteration.",
            "現在のループ本体の残りを飛ばし、次の反復へ進む。",
        )
    if stripped.startswith("try:"):
        return choose_text(
            lang,
            "Starts a protected block that may raise an exception.",
            "例外が発生し得る処理を保護付きで実行するブロックを開始する。",
        )
    if stripped.startswith("except "):
        return choose_text(
            lang,
            "Handles an exception from the preceding `try` block.",
            "直前の `try` ブロックで発生した例外を処理する。",
        )
    if stripped.startswith("with "):
        return choose_text(
            lang,
            "Opens a managed context, usually for files or resources.",
            "主にファイルや外部資源を安全に扱うための管理コンテキストを開く。",
        )
    if stripped.startswith("#"):
        return choose_text(lang, "Adds a source comment for human readers.", "人が読むためのソースコメントを追加する。")
    if re.match(r"[A-Za-z_][A-Za-z0-9_]*\s*:\s*", stripped):
        return choose_text(
            lang,
            "Declares a typed dataclass or local field.",
            "型付きの dataclass フィールドまたはローカル変数を宣言する。",
        )
    if "=" in stripped and "==" not in stripped and not stripped.startswith(("if ", "elif ", "while ", "for ")):
        lhs = stripped.split("=", 1)[0].strip()
        return choose_text(
            lang,
            f"Computes or updates `{lhs}` from the expression on the right-hand side.",
            f"右辺の式から `{lhs}` を計算または更新する。",
        )
    if stripped.endswith(")"):
        return choose_text(
            lang,
            "Calls a function or method to perform the requested operation.",
            "必要な処理を実行するために関数またはメソッドを呼び出す。",
        )
    return choose_text(
        lang,
        "Participates in the current calculation, control flow, or data assembly step.",
        "現在の計算、制御フロー、またはデータ構築の一部として機能する。",
    )


def tex_escape(text):
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in text)


def build_line_explanations(lang="en"):
    rows = []
    for line_number, line in enumerate(SOURCE_FILE.read_text(encoding="utf-8").splitlines(), start=1):
        explanation = explain_line(line, lang=lang)
        if explanation is None:
            continue
        rows.append((line_number, explanation))
    return rows


def write_ascii_safe_listing():
    listing_path = OUTDIR / "magnetic_coupler_rl_ascii_listing.py"
    source_text = SOURCE_FILE.read_text(encoding="utf-8")
    safe_text = source_text.encode("ascii", "backslashreplace").decode("ascii")
    listing_path.write_text(safe_text, encoding="utf-8")
    return listing_path


def write_tex_report(payload, gui_storyboard_path, field_path, lang="en"):
    line_rows = build_line_explanations(lang=lang)
    listing_path = write_ascii_safe_listing()
    source_rel = SOURCE_FILE.relative_to(ROOT).as_posix()
    listing_rel_from_outdir = Path(os.path.relpath(listing_path, OUTDIR)).as_posix()
    report_name = "magnetic_coupler_rl_review_ja.tex" if lang == "ja" else "magnetic_coupler_rl_review.tex"
    report_path = OUTDIR / report_name

    if lang == "ja":
        documentclass = r"\documentclass[a4paper,11pt]{ltjsarticle}"
        language_preamble = [
            r"\usepackage{luatexja-fontspec}",
            r"\setmainjfont{Yu Mincho}",
            r"\setsansjfont{Yu Gothic}",
            r"\setmonofont{Consolas}",
        ]
        title = r"{\LARGE 離散磁気カプラ設計レビュー報告書}\\[4mm]"
        subtitle = r"{\large コード・グラフ・GUI再生・磁場根拠}"
        selected_design_title = r"\section{選定設計}"
        selected_rows = [
            ("選定形状", tex_escape(payload["selected_shape"])),
            ("選定 SKU", tex_escape(payload["design"]["magnet_sku_id"])),
            ("販売元", tex_escape(payload["design"]["magnet_vendor"])),
            ("空隙 $s$", f"{1000.0 * payload['design']['gap_m']:.2f} mm"),
            ("平均半径", f"{1000.0 * payload['design']['mean_radius_m']:.2f} mm"),
            ("1周あたり磁石数", f"{payload['design']['magnets_per_ring']}"),
            ("1周あたり層数", f"{payload['design']['magnet_layers']}"),
            ("磁石総数", f"{payload['design']['total_magnets']}"),
            ("推定磁石コスト", f"{payload['design']['estimated_total_cost_jpy']:.0f} JPY"),
            ("最悪最小ギャップ", f"{payload['validation']['worst_min_gap_mm']:.2f} mm"),
            ("最悪貫入量", f"{payload['validation']['worst_penetration_mm']:.3f} mm"),
            ("平均旋回指示比", f"{payload['validation']['mean_turn_signal_ratio']:.3f}"),
        ]
        figures_title = r"\section{図とその意味}"
        convergence_subsection = r"\subsection{収束グラフ}"
        convergence_caption = r"\caption{離散磁石配列の設計探索における CEM-RL の収束。}"
        convergence_text = (
            r"\noindent このグラフは、各形状ファミリが最適化の世代更新に従ってどのように改善したかを示す。"
            r" 横軸は世代番号、縦軸は総合スコアであり、旋回意図の出しやすさ、再センタリング遅れの小ささ、"
            r" 接触リスクの低さ、ラッチングリスクの低さ、そしてコストの低さを総合的に評価している。"
            r" 太線は各形状のその時点までの最良値、淡色線は世代平均である。最良線が平坦化しているほど、"
            r" その形状について探索が収束に近づいていることを意味する。"
        )
        gui_subsection = r"\subsection{選定設計の GUI ストーリーボード}"
        gui_caption = r"\caption{選定設計について生成した GUI 風アニメーションのストーリーボード。}"
        gui_text = (
            r"\noindent 各フレームは上面視の GUI 再生画面である。青の塗りつぶし形状がロボット側の内側ボディ、"
            r" 赤の塗りつぶし形状が台車側の外側ボディを表す。短い矢印は有限個磁石配列の磁化向きを表す。"
            r" 右上のグラフは最小ギャップ、相対ヨー角、オーバーラップを追跡し、右下の領域はその時刻の数値状態を示す。"
            r" ギャップ曲線が 0 mm を下回る場合、シミュレータ内で幾何学的接触が発生したことを意味する。"
        )
        field_subsection = r"\subsection{選定された有限配列の磁場分布}"
        field_caption = r"\caption{選定された有限個磁石配列の磁場分布。計算は選定 SKU の寸法に基づく双極子重ね合わせモデルによる。}"
        field_text = (
            r"\noindent 左図は $z=0$ m における上面図であり、色は磁束密度の大きさを mT で示す。"
            r" 白矢印は面内磁場方向を表す。右図は $y=0$ m における $x$-$z$ 断面であり、"
            r" 着色された水平帯は選定された積層磁石層の位置を示す。"
            r" これは完全な 3 次元有限要素解析ではなく、実際に選ばれた SKU の寸法、層数、"
            r" 半径方向厚み、周方向配置に基づく双極子重ね合わせ近似である。"
        )
        program_scope_title = r"\section{対象プログラム}"
        program_scope_text = (
            r"\noindent 本報告書で対象とするコードは \texttt{"
            + tex_escape(source_rel)
            + r"} である。次の付録 A では行番号付きの完全ソースコードを掲載し、"
            r" その後の付録 B では空行を除く各行番号に対して、その役割を 1 行ずつ対応付けて説明する。"
            r" 空行は可読性向上のみを目的とするため、説明表からは省略している。"
        )
        appendix_a = r"\section{付録A: 完全ソースコード}"
        appendix_b = r"\section{付録B: 1行ごとの説明}"
        line_header = r"行 & 説明 \\"
    else:
        documentclass = r"\documentclass[a4paper,11pt]{article}"
        language_preamble = []
        title = r"{\LARGE Discrete Magnetic Coupler Review Report}\\[4mm]"
        subtitle = r"{\large Code, Figures, GUI Playback, and Field Evidence}"
        selected_design_title = r"\section{Selected Design}"
        selected_rows = [
            ("Selected shape", tex_escape(payload["selected_shape"])),
            ("Selected SKU", tex_escape(payload["design"]["magnet_sku_id"])),
            ("Vendor", tex_escape(payload["design"]["magnet_vendor"])),
            (r"Gap $s$", f"{1000.0 * payload['design']['gap_m']:.2f} mm"),
            ("Mean radius", f"{1000.0 * payload['design']['mean_radius_m']:.2f} mm"),
            ("Magnets per ring", f"{payload['design']['magnets_per_ring']}"),
            ("Layers per ring", f"{payload['design']['magnet_layers']}"),
            ("Total magnets", f"{payload['design']['total_magnets']}"),
            ("Estimated magnet cost", f"{payload['design']['estimated_total_cost_jpy']:.0f} JPY"),
            ("Worst minimum gap", f"{payload['validation']['worst_min_gap_mm']:.2f} mm"),
            ("Worst penetration", f"{payload['validation']['worst_penetration_mm']:.3f} mm"),
            ("Mean turn signal ratio", f"{payload['validation']['mean_turn_signal_ratio']:.3f}"),
        ]
        figures_title = r"\section{Figures and What They Mean}"
        convergence_subsection = r"\subsection{Convergence Plot}"
        convergence_caption = r"\caption{CEM-RL convergence over the discrete magnet array design search.}"
        convergence_text = (
            r"\noindent This graph shows how each shape family improved during optimization. The horizontal axis is generation count. The vertical axis is the aggregate score, which rewards usable turning indication, small recenter delay, low contact risk, low latching risk, and low cost. The thick lines are the best-so-far scores for each shape. The lighter lines are generation means. A flatter best line means the search has largely converged for that shape."
        )
        gui_subsection = r"\subsection{Selected-Design GUI Storyboard}"
        gui_caption = r"\caption{Storyboard from the generated GUI-style animation of the selected design.}"
        gui_text = (
            r"\noindent Each frame shows a top-view GUI playback. The blue filled shape is the robot-side inner body. The red filled shape is the cart-side outer body. Short arrows indicate magnet facing directions for the finite magnet array. The right-top plot tracks minimum gap, relative yaw, and overlap. The right-bottom panel shows the instantaneous numeric state. When the gap curve crosses below zero, geometric contact has occurred in the simulator."
        )
        field_subsection = r"\subsection{Selected Finite-Array Magnetic Field}"
        field_caption = r"\caption{Magnetic field of the selected finite magnet array using dipole superposition rooted in the chosen SKU geometry.}"
        field_text = (
            r"\noindent The left panel is the top view at $z=0$ m. The colormap is magnetic flux-density magnitude in mT. White arrows show in-plane field direction. The right panel is an $x$-$z$ slice at $y=0$ m. The colored horizontal bands indicate the selected stacked magnet layers. This figure is not a full 3D finite-element solution; it is a dipole-superposition model built from the actually selected SKU dimensions, layer count, radial depth, and perimeter placement."
        )
        program_scope_title = r"\section{Program Scope}"
        program_scope_text = (
            r"\noindent The code reviewed here is \texttt{"
            + tex_escape(source_rel)
            + r"}. The next appendix first prints the exact source with line numbers. After that, a line-by-line explanation table maps each non-empty line number to its role. Blank lines are omitted from the explanation table because they only improve readability."
        )
        appendix_a = r"\section{Appendix A: Full Source Listing}"
        appendix_b = r"\section{Appendix B: Line-by-Line Explanation}"
        line_header = r"Line & Explanation \\"

    lines = [
        documentclass,
        r"\usepackage[margin=18mm]{geometry}",
        r"\usepackage{graphicx}",
        r"\usepackage{booktabs}",
        r"\usepackage{longtable}",
        r"\usepackage{array}",
        r"\usepackage{hyperref}",
        r"\usepackage{xcolor}",
        r"\usepackage{listings}",
        r"\usepackage{caption}",
        r"\usepackage{float}",
        r"\usepackage{titlesec}",
        r"\hypersetup{unicode=true}",
        r"\titleformat{\section}{\large\bfseries}{\thesection}{0.6em}{}",
        r"\titleformat{\subsection}{\normalsize\bfseries}{\thesubsection}{0.6em}{}",
        r"\lstset{basicstyle=\ttfamily\scriptsize,breaklines=true,columns=fullflexible,frame=single,numbers=left,numberstyle=\tiny,stepnumber=1,tabsize=4}",
        r"\begin{document}",
        r"\begin{center}",
        title,
        subtitle,
        r"\end{center}",
        r"\vspace{4mm}",
    ]
    lines[9:9] = language_preamble
    lines.extend(
        [
        selected_design_title,
        r"\begin{tabular}{p{0.32\linewidth}p{0.60\linewidth}}",
        r"\end{tabular}",
        figures_title,
        convergence_subsection,
        r"\begin{figure}[H]\centering",
        r"\includegraphics[width=0.92\linewidth]{convergence.png}",
        convergence_caption,
        r"\end{figure}",
        convergence_text,
        gui_subsection,
        r"\begin{figure}[H]\centering",
        rf"\includegraphics[width=0.98\linewidth]{{{tex_escape(gui_storyboard_path.name)}}}",
        gui_caption,
        r"\end{figure}",
        gui_text,
        field_subsection,
        r"\begin{figure}[H]\centering",
        rf"\includegraphics[width=0.98\linewidth]{{{tex_escape(field_path.name)}}}",
        field_caption,
        r"\end{figure}",
        field_text,
        program_scope_title,
        program_scope_text,
        r"\clearpage",
        appendix_a,
        r"\lstinputlisting{" + tex_escape(listing_rel_from_outdir) + r"}",
        r"\clearpage",
        appendix_b,
        r"\setlength{\LTpre}{0pt}",
        r"\setlength{\LTpost}{0pt}",
        r"\begin{longtable}{>{\raggedright\arraybackslash}p{0.10\linewidth}>{\raggedright\arraybackslash}p{0.82\linewidth}}",
        r"\toprule",
        line_header,
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        line_header,
        r"\midrule",
        r"\endhead",
        ]
    )

    for left_label, right_value in selected_rows:
        lines.insert(lines.index(r"\end{tabular}"), f"{left_label} & {right_value} \\\\")

    for line_number, explanation in line_rows:
        lines.append(f"{line_number} & {tex_escape(explanation)} \\\\")

    lines.extend(
        [
            r"\bottomrule",
            r"\end{longtable}",
            r"\end{document}",
        ]
    )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def compile_pdf(tex_path):
    if tex_path.name.endswith("_ja.tex"):
        lualatex_command = [
            "lualatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            tex_path.name,
        ]
        subprocess.run(lualatex_command, cwd=tex_path.parent, check=True)
        subprocess.run(lualatex_command, cwd=tex_path.parent, check=True)
        return tex_path.with_suffix(".pdf")

    latexmk_command = [
        "latexmk",
        "-pdf",
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]
    try:
        subprocess.run(latexmk_command, cwd=tex_path.parent, check=True)
    except subprocess.CalledProcessError:
        pdflatex_command = [
            "pdflatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            tex_path.name,
        ]
        subprocess.run(pdflatex_command, cwd=tex_path.parent, check=True)
        try:
            subprocess.run(pdflatex_command, cwd=tex_path.parent, check=True)
        except subprocess.CalledProcessError:
            if not tex_path.with_suffix(".pdf").exists():
                raise
    return tex_path.with_suffix(".pdf")


def main():
    payload, design, policy = load_selected_design()
    geometry, results = rerun_validation_records(design, policy, seed=42)
    _, gui_storyboard_path = save_gui_animation(geometry, design, results)
    field_path = save_field_distribution(design)
    tex_path = write_tex_report(payload, gui_storyboard_path, field_path, lang="en")
    pdf_path = compile_pdf(tex_path)
    tex_path_ja = write_tex_report(payload, gui_storyboard_path, field_path, lang="ja")
    pdf_path_ja = compile_pdf(tex_path_ja)
    summary = {
        "gif": str(OUTDIR / "selected_design_gui.gif"),
        "storyboard": str(gui_storyboard_path),
        "field_figure": str(field_path),
        "tex_report": str(tex_path),
        "pdf_report": str(pdf_path),
        "tex_report_ja": str(tex_path_ja),
        "pdf_report_ja": str(pdf_path_ja),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
