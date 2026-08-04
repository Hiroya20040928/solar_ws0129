from __future__ import annotations

import math
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from mpc_solarcar import magnetic_coupler_hifi as hifi


PAGE_BG = (242, 246, 249, 255)
PANEL_BG = (255, 255, 255, 248)
CORRIDOR_BG = (252, 252, 250, 255)
WALL = (83, 94, 112, 255)
CENTERLINE = (194, 201, 212, 255)
ROBOT_FILL = (176, 234, 221, 235)
ROBOT_EDGE = (18, 104, 97, 255)
CART_FILL = (228, 232, 238, 235)
CART_EDGE = (78, 88, 103, 255)
INNER_RING = (30, 100, 227, 255)
OUTER_RING = (232, 138, 30, 255)
INNER_MAGNET = (17, 65, 160, 255)
OUTER_MAGNET = (180, 83, 9, 255)
INPUT_ARROW = (219, 39, 119, 255)
ROBOT_ARROW = (20, 115, 105, 255)
CART_ARROW = (100, 116, 139, 255)
TEXT_MAIN = (31, 41, 55, 255)
TEXT_SUB = (71, 85, 105, 255)
BADGE_OK = (21, 128, 61, 255)
BADGE_BAD = (185, 28, 28, 255)
ALERT_FILL = (254, 226, 226, 240)
ALERT_EDGE = (220, 38, 38, 255)
PRACTICAL_CLEARANCE_MM = 2.0


def try_load_font(size: int):
    for candidate in (
        Path(r"C:\Windows\Fonts\meiryo.ttc"),
        Path(r"C:\Windows\Fonts\msgothic.ttc"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ):
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def rotmat(yaw_rad: float) -> np.ndarray:
    cos_v = math.cos(float(yaw_rad))
    sin_v = math.sin(float(yaw_rad))
    return np.array([[cos_v, -sin_v], [sin_v, cos_v]], dtype=float)


def body_box_points(width_m: float, length_m: float) -> np.ndarray:
    half_width = 0.5 * float(width_m)
    half_length = 0.5 * float(length_m)
    return np.array(
        [
            [-half_width, -half_length],
            [half_width, -half_length],
            [half_width, half_length],
            [-half_width, half_length],
        ],
        dtype=float,
    )


def transform_points(local_points_xy: np.ndarray, position_world_xy: np.ndarray, yaw_rad: float) -> np.ndarray:
    return np.asarray(local_points_xy, dtype=float) @ rotmat(yaw_rad).T + np.asarray(position_world_xy, dtype=float)


def make_world_mapper(panel_box: tuple[int, int, int, int], xmin: float, xmax: float, ymin: float, ymax: float, padding_px: int = 22):
    x0, y0, x1, y1 = panel_box
    panel_width = x1 - x0
    panel_height = y1 - y0
    span_x = max(float(xmax - xmin), 1.0e-6)
    span_y = max(float(ymax - ymin), 1.0e-6)
    scale = min((panel_width - 2 * padding_px) / span_x, (panel_height - 2 * padding_px) / span_y)

    def mapper(point_xy):
        x_m = float(point_xy[0])
        y_m = float(point_xy[1])
        px = x0 + padding_px + (x_m - xmin) * scale
        py = y1 - padding_px - (y_m - ymin) * scale
        return float(px), float(py)

    return mapper, scale


def draw_closed_polyline(draw: ImageDraw.ImageDraw, points_xy: np.ndarray, mapper, color, width: int):
    pixels = [mapper(point) for point in np.asarray(points_xy, dtype=float)]
    if len(pixels) < 2:
        return
    draw.line(pixels + [pixels[0]], fill=color, width=width, joint="curve")


def draw_polygon(draw: ImageDraw.ImageDraw, points_xy: np.ndarray, mapper, fill, outline, width: int):
    pixels = [mapper(point) for point in np.asarray(points_xy, dtype=float)]
    if len(pixels) < 3:
        return
    draw.polygon(pixels, fill=fill, outline=outline)
    if width > 1:
        draw.line(pixels + [pixels[0]], fill=outline, width=width, joint="curve")


def draw_points(draw: ImageDraw.ImageDraw, points_xy: np.ndarray, mapper, color, radius_px: int):
    for point in np.asarray(points_xy, dtype=float):
        x_px, y_px = mapper(point)
        draw.ellipse(
            [x_px - radius_px, y_px - radius_px, x_px + radius_px, y_px + radius_px],
            fill=color,
            outline=None,
        )


def draw_arrow(draw: ImageDraw.ImageDraw, start_xy, vector_xy, mapper, color, scale_m_per_unit: float, width: int):
    vector = np.asarray(vector_xy, dtype=float)
    if float(np.linalg.norm(vector)) <= 1.0e-9:
        return
    start = np.asarray(start_xy, dtype=float)
    end = start + scale_m_per_unit * vector
    x0, y0 = mapper(start)
    x1, y1 = mapper(end)
    draw.line([(x0, y0), (x1, y1)], fill=color, width=width)
    angle = math.atan2(y1 - y0, x1 - x0)
    head_length_px = 12.0
    left = (x1 - head_length_px * math.cos(angle - 0.46), y1 - head_length_px * math.sin(angle - 0.46))
    right = (x1 - head_length_px * math.cos(angle + 0.46), y1 - head_length_px * math.sin(angle + 0.46))
    draw.polygon([(x1, y1), left, right], fill=color)


def draw_badge(draw: ImageDraw.ImageDraw, box_xy, text: str, is_ok: bool, font):
    x0, y0 = box_xy
    fill = BADGE_OK if is_ok else BADGE_BAD
    draw.rounded_rectangle([x0, y0, x0 + 188, y0 + 34], radius=10, fill=fill)
    draw.text((x0 + 12, y0 + 7), text, fill=(255, 255, 255, 255), font=font)


def history_row(history: dict, index: int) -> dict:
    return {key: values[index] for key, values in history.items()}


def history_bounds(history: dict, corridor_width_m: float) -> tuple[float, float, float, float]:
    robot_x = np.asarray(history["robot_x_m"], dtype=float)
    robot_y = np.asarray(history["robot_y_m"], dtype=float)
    cart_x = np.asarray(history["cart_x_m"], dtype=float)
    cart_y = np.asarray(history["cart_y_m"], dtype=float)
    ring_margin = 0.22
    half_corridor = 0.5 * float(corridor_width_m)
    xmin = min(float(np.min(robot_x)), float(np.min(cart_x)), -half_corridor) - ring_margin
    xmax = max(float(np.max(robot_x)), float(np.max(cart_x)), half_corridor) + ring_margin
    ymin = min(float(np.min(robot_y)), float(np.min(cart_y))) - 0.60
    ymax = max(float(np.max(robot_y)), float(np.max(cart_y))) + 0.90
    return xmin, xmax, ymin, ymax


def draw_corridor_scene(
    draw: ImageDraw.ImageDraw,
    panel_box: tuple[int, int, int, int],
    mapper,
    corridor_width_m: float,
):
    x0, y0, x1, y1 = panel_box
    draw.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=CORRIDOR_BG, outline=None)
    left_wall_px0 = mapper(np.array([-0.5 * corridor_width_m, 0.0]))[0]
    right_wall_px0 = mapper(np.array([0.5 * corridor_width_m, 0.0]))[0]
    draw.line([(left_wall_px0, y0 + 18), (left_wall_px0, y1 - 18)], fill=WALL, width=8)
    draw.line([(right_wall_px0, y0 + 18), (right_wall_px0, y1 - 18)], fill=WALL, width=8)
    center_x_px = mapper(np.array([0.0, 0.0]))[0]
    dash_count = 18
    for dash_index in range(dash_count):
        ya = y0 + 24 + dash_index * (y1 - y0 - 48) / dash_count
        yb = ya + 12
        draw.line([(center_x_px, ya), (center_x_px, yb)], fill=CENTERLINE, width=3)


def coupling_zoom_bounds(inner_world: np.ndarray, outer_world: np.ndarray, robot_pos: np.ndarray, cart_pos: np.ndarray) -> tuple[float, float, float, float]:
    combined = np.vstack((inner_world, outer_world, robot_pos[None, :], cart_pos[None, :]))
    center = np.mean(combined, axis=0)
    half_span = max(0.20, 0.5 * float(np.max(np.ptp(combined, axis=0))) + 0.08)
    return (
        float(center[0] - half_span),
        float(center[0] + half_span),
        float(center[1] - half_span),
        float(center[1] + half_span),
    )


def render_frame(
    assembly,
    scenario,
    outcome,
    row_index: int,
    total_rows: int,
    size_wh: tuple[int, int],
    title_text: str,
    footer_text: str,
):
    history = outcome.history
    row = history_row(history, row_index)
    width, height = size_wh
    image = Image.new("RGBA", (width, height), PAGE_BG)
    draw = ImageDraw.Draw(image)
    title_font = try_load_font(22)
    body_font = try_load_font(18)
    small_font = try_load_font(15)
    tiny_font = try_load_font(13)

    header_box = (18, 18, width - 18, 88)
    main_box = (18, 106, int(width * 0.72), height - 18)
    side_box = (main_box[2] + 18, 106, width - 18, height - 18)
    zoom_box = (main_box[0] + 18, main_box[3] - 255, main_box[0] + 420, main_box[3] - 18)
    draw.rounded_rectangle(header_box, radius=18, fill=PANEL_BG, outline=None)
    draw.rounded_rectangle(side_box, radius=18, fill=PANEL_BG, outline=None)
    draw.text((header_box[0] + 20, header_box[1] + 16), title_text, fill=TEXT_MAIN, font=title_font)
    draw.text((header_box[0] + 20, header_box[1] + 46), footer_text, fill=TEXT_SUB, font=small_font)

    xmin, xmax, ymin, ymax = history_bounds(history, scenario.corridor_width_m)
    mapper, _scale = make_world_mapper(main_box, xmin, xmax, ymin, ymax, padding_px=26)
    draw_corridor_scene(draw, main_box, mapper, scenario.corridor_width_m)

    robot_pos = np.array([float(row["robot_x_m"]), float(row["robot_y_m"])], dtype=float)
    cart_pos = np.array([float(row["cart_x_m"]), float(row["cart_y_m"])], dtype=float)
    robot_yaw = math.radians(float(row["robot_yaw_deg"]))
    cart_yaw = math.radians(float(row["cart_yaw_deg"]))

    robot_box = transform_points(body_box_points(hifi.ROBOT_WIDTH_M, hifi.ROBOT_LENGTH_M), robot_pos, robot_yaw)
    cart_box = transform_points(body_box_points(hifi.CART_WIDTH_M, hifi.CART_LENGTH_M), cart_pos, cart_yaw)
    inner_world = transform_points(assembly.geometry.inner_points, robot_pos, robot_yaw)
    outer_world = transform_points(assembly.geometry.outer_points_local, cart_pos, cart_yaw)
    inner_mount_world = transform_points(assembly.inner_mount_points_xy, robot_pos, robot_yaw)
    outer_mount_world = transform_points(assembly.outer_mount_points_xy, cart_pos, cart_yaw)

    physical_nonpenetration_ok = float(row["clearance_mm"]) > 0.0 and float(row["penetration_mm"]) <= 0.0
    frame_clearance_ok = float(row["clearance_mm"]) >= PRACTICAL_CLEARANCE_MM and float(row["penetration_mm"]) <= 0.0
    robot_corridor_margin_mm = float(row.get("robot_corridor_margin_mm", float("nan")))
    cart_corridor_margin_mm = float(row.get("cart_corridor_margin_mm", float("nan")))
    corridor_breach_mm = float(row.get("corridor_breach_mm", 0.0))
    frame_corridor_ok = corridor_breach_mm <= 0.0
    robot_outline = BADGE_BAD if np.isfinite(robot_corridor_margin_mm) and robot_corridor_margin_mm < 0.0 else ROBOT_EDGE
    cart_outline = BADGE_BAD if np.isfinite(cart_corridor_margin_mm) and cart_corridor_margin_mm < 0.0 else CART_EDGE
    ring_outer_color = BADGE_BAD if not frame_clearance_ok else OUTER_RING
    ring_inner_color = BADGE_BAD if not frame_clearance_ok else INNER_RING

    draw_polygon(draw, cart_box, mapper, CART_FILL, cart_outline, 3 if cart_outline == BADGE_BAD else 2)
    draw_polygon(draw, robot_box, mapper, ROBOT_FILL, robot_outline, 3 if robot_outline == BADGE_BAD else 2)
    draw_closed_polyline(draw, outer_world, mapper, ring_outer_color, 1)
    draw_closed_polyline(draw, inner_world, mapper, ring_inner_color, 1)
    draw_points(draw, outer_mount_world, mapper, OUTER_MAGNET, 3)
    draw_points(draw, inner_mount_world, mapper, INNER_MAGNET, 3)

    draw_arrow(draw, robot_pos, rotmat(robot_yaw) @ np.array([0.0, 0.14], dtype=float), mapper, ROBOT_ARROW, 1.0, 3)
    draw_arrow(draw, cart_pos, rotmat(cart_yaw) @ np.array([0.0, 0.14], dtype=float), mapper, CART_ARROW, 1.0, 3)
    handle_world = cart_pos + rotmat(cart_yaw) @ np.array([0.0, -0.5 * hifi.CART_LENGTH_M], dtype=float)
    human_force_world = np.array([float(row["human_force_x_n"]), float(row["human_force_y_n"])], dtype=float)
    draw_arrow(draw, handle_world, human_force_world, mapper, INPUT_ARROW, 0.018, 4)

    draw.rounded_rectangle(zoom_box, radius=14, fill=(255, 255, 255, 240), outline=(210, 219, 228, 255), width=1)
    draw.text((zoom_box[0] + 14, zoom_box[1] + 10), "Coupling Zoom", fill=TEXT_MAIN, font=small_font)
    zx0, zy0, zx1, zy1 = zoom_box
    inner_xmin, inner_xmax, inner_ymin, inner_ymax = coupling_zoom_bounds(inner_world, outer_world, robot_pos, cart_pos)
    zoom_mapper, _ = make_world_mapper((zx0 + 8, zy0 + 34, zx1 - 8, zy1 - 8), inner_xmin, inner_xmax, inner_ymin, inner_ymax, padding_px=18)
    draw_closed_polyline(draw, outer_world, zoom_mapper, ring_outer_color, 1)
    draw_closed_polyline(draw, inner_world, zoom_mapper, ring_inner_color, 1)
    draw_points(draw, outer_mount_world, zoom_mapper, OUTER_MAGNET, 1)
    draw_points(draw, inner_mount_world, zoom_mapper, INNER_MAGNET, 1)

    alert_messages = []
    if not physical_nonpenetration_ok:
        alert_messages.append("ring overlap")
    elif not frame_clearance_ok:
        alert_messages.append(f"clearance < {PRACTICAL_CLEARANCE_MM:.1f} mm")
    if not frame_corridor_ok:
        alert_messages.append("corridor breach")
    if alert_messages:
        alert_box = (main_box[0] + 16, main_box[1] + 16, main_box[0] + 330, main_box[1] + 56)
        draw.rounded_rectangle(alert_box, radius=12, fill=ALERT_FILL, outline=ALERT_EDGE, width=2)
        draw.text((alert_box[0] + 12, alert_box[1] + 11), "VISUAL FAIL: " + " + ".join(alert_messages), fill=ALERT_EDGE, font=small_font)

    sx0, sy0, sx1, sy1 = side_box
    tx = sx0 + 18
    ty = sy0 + 18
    draw.text((tx, ty), "Generation Replay", fill=TEXT_MAIN, font=title_font)
    ty += 38
    summary_lines = [
        f"frame: {row_index + 1}/{total_rows}",
        f"time: {float(row['time_s']):.2f} s",
        f"phase: {row['segment_label']}",
        f"cart mass: {float(assembly.design.cart_mass_kg):.2f} kg",
        f"clearance: {float(row['clearance_mm']):.3f} mm",
        f"penetration: {float(row['penetration_mm']):.3f} mm",
        f"robot wall margin: {robot_corridor_margin_mm:.2f} mm" if np.isfinite(robot_corridor_margin_mm) else "robot wall margin: --",
        f"cart wall margin: {cart_corridor_margin_mm:.2f} mm" if np.isfinite(cart_corridor_margin_mm) else "cart wall margin: --",
        f"corridor breach: {corridor_breach_mm:.2f} mm",
        f"rel XY: {float(row['relative_translation_mm']):.2f} mm",
        f"rel yaw: {float(row['relative_yaw_deg']):.2f} deg",
        f"human |F|: {float(np.linalg.norm(human_force_world)):.2f} N",
        f"magnetic |F|: {float(row['magnetic_force_n']):.2f} N",
        f"magnetic tau: {float(row['magnetic_torque_nm']):.2f} N m",
        f"cart speed: {float(row['cart_speed_mps']):.3f} m/s",
        f"cart accel: {float(row['cart_accel_mps2']):.3f} m/s^2",
        f"cart yaw accel: {float(row['cart_yaw_accel_radps2']):.3f} rad/s^2",
        f"score: {float(outcome.score):.2f}",
    ]
    for line in summary_lines:
        draw.text((tx, ty), line, fill=TEXT_SUB, font=body_font)
        ty += 28

    ty += 8
    draw.text((tx, ty), "Status", fill=TEXT_MAIN, font=body_font)
    ty += 36
    episode_corridor_ok = getattr(outcome, "corridor_breach_count", 0) == 0 and getattr(outcome, "max_corridor_breach_mm", 0.0) <= 0.0
    episode_clip_ok = getattr(outcome, "dynamic_clip_count", 0) == 0
    episode_contact_ok = (
        getattr(outcome, "contact_events", 0) == 0
        and getattr(outcome, "max_penetration_mm", 0.0) <= 0.0
        and getattr(outcome, "min_clearance_mm", 0.0) >= PRACTICAL_CLEARANCE_MM
    )
    global_ok = episode_contact_ok and episode_corridor_ok and episode_clip_ok
    draw_badge(
        draw,
        (tx, ty),
        f"frame clr>={PRACTICAL_CLEARANCE_MM:.0f}mm {'OK' if frame_clearance_ok else 'NG'}",
        frame_clearance_ok,
        small_font,
    )
    ty += 44
    draw_badge(draw, (tx, ty), f"frame corridor {'OK' if frame_corridor_ok else 'NG'}", frame_corridor_ok, small_font)
    ty += 44
    draw_badge(draw, (tx, ty), f"episode clipfree {'OK' if episode_clip_ok else 'NG'}", episode_clip_ok, small_font)
    ty += 44
    draw_badge(draw, (tx, ty), f"episode pass {'OK' if global_ok else 'NG'}", global_ok, small_font)
    ty += 44
    input_active = float(np.linalg.norm(human_force_world)) >= 0.1
    draw_badge(draw, (tx, ty), f"human input {'ON' if input_active else 'OFF'}", input_active, small_font)
    ty += 56

    legend_lines = [
        (ROBOT_EDGE, "robot / inner ring"),
        (CART_EDGE, "cart / outer ring"),
        (INPUT_ARROW, "human input at cart handle"),
    ]
    draw.text((tx, ty), "Legend", fill=TEXT_MAIN, font=body_font)
    ty += 32
    for color, text in legend_lines:
        draw.rounded_rectangle([tx, ty + 3, tx + 20, ty + 21], radius=5, fill=color)
        draw.text((tx + 30, ty), text, fill=TEXT_SUB, font=small_font)
        ty += 28

    return image.convert("RGB")


def render_fixedheight_corridor_video(
    assembly,
    scenario,
    outcome,
    outpath: Path,
    *,
    title_text: str,
    footer_text: str = "",
    playback_speed: float = 0.35,
    output_fps: int = 12,
    frame_stride: int = 4,
    size_wh: tuple[int, int] = (1280, 760),
):
    if outcome.history is None:
        raise ValueError("Dynamic outcome has no recorded history.")
    outpath.parent.mkdir(parents=True, exist_ok=True)
    poster_path = outpath.with_name(outpath.stem + "_poster.png")
    history = outcome.history
    total_rows = len(history["time_s"])
    sampled_indices = list(range(0, total_rows, max(int(frame_stride), 1)))
    if sampled_indices[-1] != total_rows - 1:
        sampled_indices.append(total_rows - 1)
    dt_s = float(np.mean(np.diff(np.asarray(history["time_s"], dtype=float)))) if total_rows >= 2 else float(scenario.dt_s)
    repeat_count = max(int(round(output_fps * dt_s * max(int(frame_stride), 1) / max(float(playback_speed), 1.0e-3))), 1)
    poster_index = min(
        sampled_indices,
        key=lambda idx: (
            -float(outcome.history.get("corridor_breach_mm", [0.0] * total_rows)[idx]),
            float(outcome.history["clearance_mm"][idx]),
            -float(outcome.history["penetration_mm"][idx]),
            -float(outcome.history["relative_yaw_deg"][idx]),
        ),
    )
    temp_video = outpath.with_name(outpath.stem + ".tmp" + outpath.suffix)
    writer = imageio.get_writer(
        str(temp_video),
        fps=int(output_fps),
        codec="libx264",
        quality=8,
        macro_block_size=None,
    )
    for sample_pos, row_index in enumerate(sampled_indices):
        frame = render_frame(
            assembly=assembly,
            scenario=scenario,
            outcome=outcome,
            row_index=row_index,
            total_rows=total_rows,
            size_wh=size_wh,
            title_text=title_text,
            footer_text=footer_text,
        )
        if row_index == poster_index:
            frame.save(poster_path)
        frame_array = np.asarray(frame, dtype=np.uint8)
        for _ in range(repeat_count):
            writer.append_data(frame_array)
    writer.close()
    temp_video.replace(outpath)
    return {
        "video_path": str(outpath),
        "poster_path": str(poster_path),
        "sampled_frame_count": int(len(sampled_indices)),
        "source_frame_count": int(total_rows),
        "fps": int(output_fps),
        "repeat_count": int(repeat_count),
        "playback_speed": float(playback_speed),
        "frame_stride": int(frame_stride),
    }
