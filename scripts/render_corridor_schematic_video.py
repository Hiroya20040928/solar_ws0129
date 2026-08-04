import argparse
import json
import math
from pathlib import Path

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_hifi as hifi
from mpc_solarcar import magnetic_coupler_interactive_sim as corridor_sim


DEFAULT_RESULT_JSON = (
    ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_research_cmaes_20260701" / "best_design_hifi.json"
)

PANEL_BG = (248, 247, 243, 255)
CORRIDOR_BG = (251, 250, 247, 255)
HEADER_BG = (238, 242, 248, 255)
CARD_BG = (255, 255, 255, 245)
WALL = (81, 93, 113, 255)
CENTERLINE = (196, 203, 215, 255)
ROBOT_FILL = (147, 226, 214, 235)
ROBOT_EDGE = (20, 92, 86, 255)
INNER_RING = (43, 104, 237, 255)
INNER_MAGNET = (25, 60, 180, 255)
CART_FILL = (219, 224, 232, 235)
CART_EDGE = (69, 79, 94, 255)
OUTER_RING = (242, 148, 36, 255)
OUTER_MAGNET = (193, 101, 12, 255)
PERSON_FILL = (233, 178, 81, 255)
PERSON_EDGE = (140, 92, 26, 255)
INPUT_ARROW = (204, 41, 122, 255)
MAGNETIC_ARROW = (34, 139, 94, 255)
CONTACT_ARROW = (216, 59, 59, 255)
TEXT_MAIN = (31, 41, 55, 255)
TEXT_SUB = (71, 85, 105, 255)
PASS = (22, 163, 74, 255)
FAIL = (220, 38, 38, 255)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Render a clear top-view schematic video of the corridor magnetic-coupler simulation."
    )
    parser.add_argument("--result-json", type=Path, default=DEFAULT_RESULT_JSON)
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_corridor_schematic_video_20260706",
    )
    parser.add_argument("--duration-s", type=float, default=14.0)
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--grid", choices=("search", "validation"), default="search")
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--width", type=int, default=1440)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--fixed-height", action="store_true")
    parser.add_argument("--fixed-height-shift-mm", type=float, default=0.0)
    parser.add_argument("--corridor-margin-m", type=float, default=0.18)
    parser.add_argument("--y-span-min-m", type=float, default=4.8)
    parser.add_argument("--y-span-max-m", type=float, default=8.2)
    parser.add_argument(
        "--playback-speed",
        type=float,
        default=0.25,
        help="Playback speed relative to real simulated time. 0.25 means 4x slow motion.",
    )
    parser.add_argument("--video-name", type=str, default="corridor_pedestrian_avoidance_schematic2d.mp4")
    return parser.parse_args()


def try_load_font(size: int):
    for candidate in [
        Path(r"C:\Windows\Fonts\meiryo.ttc"),
        Path(r"C:\Windows\Fonts\msgothic.ttc"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ]:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def rotmat(yaw_rad: float) -> np.ndarray:
    c = math.cos(float(yaw_rad))
    s = math.sin(float(yaw_rad))
    return np.array([[c, -s], [s, c]], dtype=float)


def transform_points(local_points_xy: np.ndarray, pos_world_xy: np.ndarray, yaw_rad: float) -> np.ndarray:
    return np.asarray(local_points_xy, dtype=float) @ rotmat(yaw_rad).T + np.asarray(pos_world_xy, dtype=float)


def body_box_points(width_m: float, length_m: float) -> np.ndarray:
    hw = 0.5 * float(width_m)
    hl = 0.5 * float(length_m)
    return np.array(
        [
            [-hw, -hl],
            [hw, -hl],
            [hw, hl],
            [-hw, hl],
        ],
        dtype=float,
    )


def make_world_mapper(panel_box: tuple[int, int, int, int], xmin: float, xmax: float, ymin: float, ymax: float, padding_px: int = 28):
    x0, y0, x1, y1 = panel_box
    panel_w = x1 - x0
    panel_h = y1 - y0
    span_x = max(xmax - xmin, 1.0e-6)
    span_y = max(ymax - ymin, 1.0e-6)
    scale = min((panel_w - 2 * padding_px) / span_x, (panel_h - 2 * padding_px) / span_y)

    def map_point(point_xy: np.ndarray | list[float] | tuple[float, float]):
        x_m, y_m = float(point_xy[0]), float(point_xy[1])
        px = x0 + padding_px + (x_m - xmin) * scale
        py = y1 - padding_px - (y_m - ymin) * scale
        return (float(px), float(py))

    return map_point, scale


def world_to_canvas_fn(panel_box: tuple[int, int, int, int], history_row: dict, args):
    robot_y = float(history_row["robot_y_m"])
    person_y = float(history_row["person_y_m"])
    center_y = 0.5 * (robot_y + person_y)
    span_y = min(args.y_span_max_m, max(args.y_span_min_m, abs(person_y - robot_y) + 2.6))
    half_width_m = 0.5 * corridor_sim.CORRIDOR_WIDTH_M + args.corridor_margin_m
    xmin = -half_width_m
    xmax = half_width_m
    ymin = center_y - 0.5 * span_y
    ymax = center_y + 0.5 * span_y
    map_point, scale = make_world_mapper(panel_box, xmin, xmax, ymin, ymax, padding_px=34)
    return map_point, scale, xmin, xmax, ymin, ymax


def draw_polygon(draw: ImageDraw.ImageDraw, points_xy: np.ndarray, mapper, fill, outline, width: int):
    pts = [mapper(point) for point in points_xy]
    draw.polygon(pts, fill=fill, outline=outline)
    if width > 1:
        closed = pts + [pts[0]]
        draw.line(closed, fill=outline, width=width, joint="curve")


def draw_polyline(draw: ImageDraw.ImageDraw, points_xy: np.ndarray, mapper, color, width: int):
    pts = [mapper(point) for point in points_xy]
    if len(pts) >= 2:
        draw.line(pts + [pts[0]], fill=color, width=width, joint="curve")


def draw_points(draw: ImageDraw.ImageDraw, points_xy: np.ndarray, mapper, color, radius_px: int):
    for point in np.asarray(points_xy, dtype=float):
        x_px, y_px = mapper(point)
        draw.ellipse(
            [x_px - radius_px, y_px - radius_px, x_px + radius_px, y_px + radius_px],
            fill=color,
            outline=None,
        )


def draw_arrow(draw: ImageDraw.ImageDraw, start_xy, vector_xy, mapper, color, scale_px_per_unit: float, width: int, label: str | None = None, font=None):
    start = np.asarray(start_xy, dtype=float)
    vector = np.asarray(vector_xy, dtype=float)
    norm = float(np.linalg.norm(vector))
    if norm <= 1.0e-9:
        return
    end = start + vector * scale_px_per_unit
    x0, y0 = mapper(start)
    x1, y1 = mapper(end)
    draw.line([(x0, y0), (x1, y1)], fill=color, width=width)
    angle = math.atan2(y1 - y0, x1 - x0)
    head_len = 12.0
    left = (x1 - head_len * math.cos(angle - 0.45), y1 - head_len * math.sin(angle - 0.45))
    right = (x1 - head_len * math.cos(angle + 0.45), y1 - head_len * math.sin(angle + 0.45))
    draw.polygon([(x1, y1), left, right], fill=color)
    if label and font is not None:
        draw.text((x1 + 8, y1 - 10), label, fill=color, font=font)


def draw_badge(draw, xy, text: str, ok: bool, font):
    x, y = xy
    fill = PASS if ok else FAIL
    draw.rounded_rectangle([x, y, x + 180, y + 34], radius=10, fill=fill)
    draw.text((x + 12, y + 6), text, fill=(255, 255, 255, 255), font=font)


def clamp_box_position(anchor_xy, box_w: int, box_h: int, panel_box: tuple[int, int, int, int], padding: int = 8):
    x0, y0, x1, y1 = panel_box
    x = min(max(float(anchor_xy[0]), x0 + padding), x1 - box_w - padding)
    y = min(max(float(anchor_xy[1]), y0 + padding), y1 - box_h - padding)
    return x, y


def history_metrics(history_rows: list[dict]):
    times = np.array([float(row["time_s"]) for row in history_rows], dtype=float)
    cart_speed = np.array([float(row["cart_speed_mps"]) for row in history_rows], dtype=float)
    robot_speed = np.array([float(row["robot_speed_mps"]) for row in history_rows], dtype=float)
    cart_yaw_deg = np.array([float(row["cart_yaw_deg"]) for row in history_rows], dtype=float)
    ring_clearance_mm = np.array([float(row["ring_clearance_mm"]) for row in history_rows], dtype=float)
    contact_demand_mm = np.array([float(row["contact_demand_mm"]) for row in history_rows], dtype=float)
    input_force_n = np.array([float(row["input_force_n"]) for row in history_rows], dtype=float)
    magnetic_force_n = np.array([float(row["magnetic_force_n"]) for row in history_rows], dtype=float)
    contact_force_n = np.array([float(row["contact_force_n"]) for row in history_rows], dtype=float)
    rel_yaw_deg = np.array([float(row["relative_yaw_deg"]) for row in history_rows], dtype=float)
    dt = np.diff(times)
    dt = dt[dt > 1.0e-9]
    mean_dt = float(np.mean(dt)) if dt.size else corridor_sim.DT_S
    cart_accel = np.diff(cart_speed) / np.maximum(np.diff(times), 1.0e-9)
    robot_accel = np.diff(robot_speed) / np.maximum(np.diff(times), 1.0e-9)
    cart_yaw_rate_degps = np.diff(np.unwrap(np.deg2rad(cart_yaw_deg))) / np.maximum(np.diff(times), 1.0e-9)
    return {
        "sample_hz": 1.0 / mean_dt,
        "duration_s": float(times[-1]) if len(times) else 0.0,
        "cart_speed_max_mps": float(np.max(cart_speed)) if len(cart_speed) else 0.0,
        "robot_speed_max_mps": float(np.max(robot_speed)) if len(robot_speed) else 0.0,
        "cart_accel_abs_max_mps2": float(np.max(np.abs(cart_accel))) if len(cart_accel) else 0.0,
        "robot_accel_abs_max_mps2": float(np.max(np.abs(robot_accel))) if len(robot_accel) else 0.0,
        "cart_yaw_rate_abs_max_degps": float(np.max(np.abs(np.rad2deg(cart_yaw_rate_degps)))) if len(cart_yaw_rate_degps) else 0.0,
        "relative_yaw_abs_max_deg": float(np.max(np.abs(rel_yaw_deg))) if len(rel_yaw_deg) else 0.0,
        "ring_clearance_min_mm": float(np.min(ring_clearance_mm)) if len(ring_clearance_mm) else 0.0,
        "contact_demand_max_mm": float(np.max(contact_demand_mm)) if len(contact_demand_mm) else 0.0,
        "input_force_max_n": float(np.max(input_force_n)) if len(input_force_n) else 0.0,
        "magnetic_force_max_n": float(np.max(magnetic_force_n)) if len(magnetic_force_n) else 0.0,
        "contact_force_max_n": float(np.max(contact_force_n)) if len(contact_force_n) else 0.0,
    }


def write_fidelity_report(outdir: Path, model: hifi.ArrayModel, summary: dict, history_rows: list[dict]):
    metrics = history_metrics(history_rows)
    nominal = hifi.follower_and_damping_params(model, hifi.nominal_episode_environment())
    coverage_items = [
        ("実SKU寸法の離散磁石", True),
        ("磁石間相互作用の3D体積双極子近似", True),
        ("ロボット・台車の質量と矩形慣性", True),
        ("縦横異方性ローリング抵抗", True),
        ("静止抵抗を含むStribeck風抵抗", True),
        ("キャスターの自己整列トルク近似", True),
        ("接触違反の位置・速度投影拘束", True),
        ("組付け・減衰ばらつきの環境摂動", True),
        ("キャスター4輪の個別接触と首振り", False),
        ("床面摩擦分布・段差・不陸", False),
        ("構造たわみ・バックラッシュ", False),
        ("センサ遅れ・ノイズ・量子化", False),
        ("モータのトルク速度特性と電流制限", False),
        ("実機ログで同定した台車抵抗パラメータ", False),
        ("実機対シミュレータの対応検証", False),
    ]
    modeled_count = sum(1 for _, ok in coverage_items if ok)
    total_count = len(coverage_items)
    md_lines = [
        "# Corridor Simulator Fidelity Report",
        "",
        "## 結論",
        f"- 現在のシミュレータは **高精度デジタルツインとは言えません**。理由は、実機同定・実機対比検証が未導入のまま、接触時に台車へ非常に大きい力が入り、現実離れした速度・角速度が出ているためです。",
        f"- 現在の現象カバレッジ指標: `{modeled_count}/{total_count} = {100.0 * modeled_count / total_count:.1f}%`",
        f"- ただしこれは **精度百分率ではなく、何をモデル化しているかの網羅率** です。実機一致率そのものは、対になる実測ログがないため未同定です。",
        "",
        "## 今回の定量結果",
        f"- サンプリング: `{metrics['sample_hz']:.1f} Hz`",
        f"- 記録時間: `{metrics['duration_s']:.2f} s`",
        f"- ロボット最大速度: `{metrics['robot_speed_max_mps']:.3f} m/s`",
        f"- 台車最大速度: `{metrics['cart_speed_max_mps']:.3f} m/s`",
        f"- 台車最大加速度: `{metrics['cart_accel_abs_max_mps2']:.2f} m/s^2`",
        f"- 台車最大ヨーレート: `{metrics['cart_yaw_rate_abs_max_degps']:.1f} deg/s`",
        f"- 最大相対ヨー: `{metrics['relative_yaw_abs_max_deg']:.2f} deg`",
        f"- 最小リング隙間: `{metrics['ring_clearance_min_mm']:.2f} mm`",
        f"- 最大接触要求量: `{metrics['contact_demand_max_mm']:.2f} mm`",
        f"- 人入力最大: `{metrics['input_force_max_n']:.2f} N`",
        f"- 磁気力最大: `{metrics['magnetic_force_max_n']:.2f} N`",
        f"- 接触力最大: `{metrics['contact_force_max_n']:.2f} N`",
        "",
        "## 現在の抵抗・接触モデル",
        f"- 台車質量: `{model.design.cart_mass_kg:.3f} kg`",
        f"- 進行方向の定常抵抗: `{nominal['cart_sustained_long_force_n']:.3f} N`",
        f"- 横方向の定常抵抗: `{nominal['cart_sustained_lat_force_n']:.3f} N`",
        f"- 進行方向の立ち上がり抵抗: `{hifi.CART_START_FORCE_MULTIPLIER * nominal['cart_sustained_long_force_n']:.3f} N`",
        f"- 横方向の立ち上がり抵抗: `{hifi.CART_START_FORCE_MULTIPLIER * nominal['cart_sustained_lat_force_n']:.3f} N`",
        f"- 縦ダンピング係数: `{nominal['cart_longitudinal_damping_n_s_m']:.3f} N·s/m`",
        f"- 横ダンピング係数: `{nominal['cart_lateral_damping_n_s_m']:.3f} N·s/m`",
        f"- キャスター静止首振り抵抗: `{nominal['cart_swivel_static_torque_nm']:.3f} N·m`",
        f"- 接触剛性パラメータ（ログ用参照値）: `{nominal['contact_stiffness_n_per_m']:.1f} N/m`",
        f"- 接触減衰パラメータ（ログ用参照値）: `{nominal['contact_damping_n_s_per_m']:.1f} N·s/m`",
        "",
        "## 何が現実離れしているか",
        f"- 台車最大速度 `{metrics['cart_speed_max_mps']:.3f} m/s` は、ロボットの巡航 `{metrics['robot_speed_max_mps']:.3f} m/s` の `{metrics['cart_speed_max_mps'] / max(metrics['robot_speed_max_mps'], 1.0e-9):.2f}` 倍です。",
        f"- 台車最大加速度 `{metrics['cart_accel_abs_max_mps2']:.2f} m/s^2` は、ロボット加速上限 `0.10 m/s^2` の `{metrics['cart_accel_abs_max_mps2'] / 0.10:.1f}` 倍です。",
        f"- 磁気力最大 `{metrics['magnetic_force_max_n']:.2f} N` は、台車の定常進行抵抗 `{nominal['cart_sustained_long_force_n']:.2f} N` の `{metrics['magnetic_force_max_n'] / max(nominal['cart_sustained_long_force_n'], 1.0e-9):.1f}` 倍です。",
        f"- 接触力最大 `{metrics['contact_force_max_n']:.2f} N` は、台車の定常進行抵抗 `{nominal['cart_sustained_long_force_n']:.2f} N` の `{metrics['contact_force_max_n'] / max(nominal['cart_sustained_long_force_n'], 1.0e-9):.1f}` 倍です。",
        f"- シナリオ要約でも `all_pass = {summary.get('all_pass', 0)}`、`min_cart_person_clearance_mm = {summary['min_cart_person_clearance_mm']:.2f}`、`worst_ring_clearance_mm = {summary['worst_ring_clearance_mm']:.2f}` で、現時点では安全にも成功していません。",
        "",
        "## カバレッジ一覧",
    ]
    for name, ok in coverage_items:
        md_lines.append(f"- {'OK' if ok else 'NG'}: {name}")
    md_lines += [
        "",
        "## 判定",
        "- 現時点のモデルは『探索用の近似モデル』としては有用ですが、『実機を高精度に再現できている』とはまだ言えません。",
        "- 次に必要なのは、実機の押し試験ログから台車抵抗・首振り抵抗・応答遅れを同定し、その同定値でこのモデルを置き換えることです。",
    ]
    report_path = outdir / "corridor_fidelity_report_ja.md"
    report_path.write_text("\n".join(md_lines), encoding="utf-8")
    payload = {
        "summary": summary,
        "metrics": metrics,
        "nominal_dynamics": {
            "cart_mass_kg": float(model.design.cart_mass_kg),
            "cart_sustained_long_force_n": float(nominal["cart_sustained_long_force_n"]),
            "cart_sustained_lat_force_n": float(nominal["cart_sustained_lat_force_n"]),
            "cart_longitudinal_damping_n_s_m": float(nominal["cart_longitudinal_damping_n_s_m"]),
            "cart_lateral_damping_n_s_m": float(nominal["cart_lateral_damping_n_s_m"]),
            "cart_swivel_static_torque_nm": float(nominal["cart_swivel_static_torque_nm"]),
            "contact_stiffness_n_per_m": float(nominal["contact_stiffness_n_per_m"]),
            "contact_damping_n_s_per_m": float(nominal["contact_damping_n_s_per_m"]),
        },
        "coverage_items": [{"name": name, "modeled": ok} for name, ok in coverage_items],
        "modeled_coverage_ratio": modeled_count / max(total_count, 1),
        "accuracy_ratio_claimable": None,
        "notes": [
            "coverage ratio is not a sim-to-real accuracy percentage",
            "paired real-vs-sim logs are not yet integrated for this corridor simulator",
        ],
    }
    (outdir / "corridor_fidelity_report.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return report_path


def build_history(args, result_json: Path, outdir: Path):
    dipole_grid = hifi.SEARCH_DIPOLE_GRID if args.grid == "search" else hifi.VALIDATION_DIPOLE_GRID
    _payload, _design, policy, model = corridor_sim.load_selected_model(result_json, args.samples, dipole_grid)
    summary_json = outdir / "corridor_summary.json"
    history_csv = outdir / "corridor_history.csv"
    summary, history_rows = corridor_sim.run_corridor_pedestrian_avoidance(
        model,
        policy,
        duration_s=args.duration_s,
        height_control_enabled=not args.fixed_height,
        fixed_height_shift_m=0.001 * args.fixed_height_shift_mm if args.fixed_height else 0.0,
        summary_json=summary_json,
        history_csv=history_csv,
    )
    return model, summary, history_rows


def attach_schematic_frame(model: hifi.ArrayModel, history_row: dict, summary: dict, frame_index: int, frame_count: int, size_wh: tuple[int, int], args):
    width_px, height_px = size_wh
    right_panel_w = 410
    header_h = 98
    left_panel = (0, 0, width_px - right_panel_w, height_px)
    overview_h = int(0.56 * (height_px - header_h))
    scene_panel = (0, header_h, width_px - right_panel_w, header_h + overview_h)
    zoom_panel = (18, scene_panel[3] + 16, width_px - right_panel_w - 18, height_px - 18)
    image = Image.new("RGBA", (width_px, height_px), PANEL_BG)
    draw = ImageDraw.Draw(image)

    title_font = try_load_font(30)
    body_font = try_load_font(22)
    small_font = try_load_font(18)

    map_point, scale, xmin, xmax, ymin, ymax = world_to_canvas_fn(scene_panel, history_row, args)
    lx0, ly0, lx1, ly1 = left_panel
    sx0, sy0, sx1, sy1 = scene_panel
    draw.rectangle(left_panel, fill=CORRIDOR_BG)
    draw.rectangle([lx0, ly0, lx1, header_h], fill=HEADER_BG)
    draw.rounded_rectangle(zoom_panel, radius=22, fill=CARD_BG, outline=(208, 213, 221, 255), width=2)

    wall_half_thickness_m = 0.05
    left_wall = np.array(
        [
            [-(0.5 * corridor_sim.CORRIDOR_WIDTH_M + wall_half_thickness_m), ymin],
            [-(0.5 * corridor_sim.CORRIDOR_WIDTH_M), ymin],
            [-(0.5 * corridor_sim.CORRIDOR_WIDTH_M), ymax],
            [-(0.5 * corridor_sim.CORRIDOR_WIDTH_M + wall_half_thickness_m), ymax],
        ],
        dtype=float,
    )
    right_wall = np.array(
        [
            [(0.5 * corridor_sim.CORRIDOR_WIDTH_M), ymin],
            [(0.5 * corridor_sim.CORRIDOR_WIDTH_M + wall_half_thickness_m), ymin],
            [(0.5 * corridor_sim.CORRIDOR_WIDTH_M + wall_half_thickness_m), ymax],
            [(0.5 * corridor_sim.CORRIDOR_WIDTH_M), ymax],
        ],
        dtype=float,
    )
    draw_polygon(draw, left_wall, map_point, WALL, WALL, width=1)
    draw_polygon(draw, right_wall, map_point, WALL, WALL, width=1)

    dash_y = ymin
    while dash_y < ymax:
        p0 = map_point((0.0, dash_y))
        p1 = map_point((0.0, min(dash_y + 0.35, ymax)))
        draw.line([p0, p1], fill=CENTERLINE, width=3)
        dash_y += 0.70

    robot_pos = np.array([float(history_row["robot_x_m"]), float(history_row["robot_y_m"])], dtype=float)
    cart_pos = np.array([float(history_row["cart_x_m"]), float(history_row["cart_y_m"])], dtype=float)
    person_pos = np.array([float(history_row["person_x_m"]), float(history_row["person_y_m"])], dtype=float)
    robot_yaw = math.radians(float(history_row["robot_yaw_deg"]))
    cart_yaw = math.radians(float(history_row["cart_yaw_deg"]))

    robot_box = transform_points(body_box_points(hifi.ROBOT_WIDTH_M, hifi.ROBOT_LENGTH_M), robot_pos, robot_yaw)
    cart_box = transform_points(body_box_points(hifi.CART_WIDTH_M, hifi.CART_LENGTH_M), cart_pos, cart_yaw)
    inner_ring = transform_points(model.geometry.inner_points, robot_pos, robot_yaw)
    outer_ring = transform_points(model.geometry.outer_points_local, cart_pos, cart_yaw)
    inner_magnets = transform_points(model.inner_magnet_centers_xy, robot_pos, robot_yaw)
    outer_magnets = transform_points(model.outer_magnet_centers_local_xy, cart_pos, cart_yaw)

    draw_polygon(draw, cart_box, map_point, CART_FILL, CART_EDGE, width=4)
    draw_polyline(draw, outer_ring, map_point, OUTER_RING, width=7)
    draw_points(draw, outer_magnets, map_point, OUTER_MAGNET, radius_px=4)

    draw_polygon(draw, robot_box, map_point, ROBOT_FILL, ROBOT_EDGE, width=4)
    draw_polyline(draw, inner_ring, map_point, INNER_RING, width=7)
    draw_points(draw, inner_magnets, map_point, INNER_MAGNET, radius_px=4)

    person_px = map_point(person_pos)
    person_radius_px = max(12, int(0.14 * scale))
    draw.ellipse(
        [
            person_px[0] - person_radius_px,
            person_px[1] - person_radius_px,
            person_px[0] + person_radius_px,
            person_px[1] + person_radius_px,
        ],
        fill=PERSON_FILL,
        outline=PERSON_EDGE,
        width=4,
    )

    draw_arrow(draw, robot_pos, 0.18 * np.array([math.cos(robot_yaw), math.sin(robot_yaw)]), map_point, ROBOT_EDGE, 1.0, 4)
    draw_arrow(draw, cart_pos, 0.18 * np.array([math.cos(cart_yaw), math.sin(cart_yaw)]), map_point, CART_EDGE, 1.0, 4)

    input_force_world = np.array(
        [
            float(history_row.get("input_force_x_n", 0.0)),
            float(history_row.get("input_force_y_n", 0.0)),
        ],
        dtype=float,
    )
    magnetic_force_world = np.array(
        [
            float(history_row.get("magnetic_force_x_n", 0.0)),
            float(history_row.get("magnetic_force_y_n", 0.0)),
        ],
        dtype=float,
    )
    contact_force_world = np.array(
        [
            float(history_row.get("contact_force_x_n", 0.0)),
            float(history_row.get("contact_force_y_n", 0.0)),
        ],
        dtype=float,
    )
    draw_arrow(draw, cart_pos, input_force_world, map_point, INPUT_ARROW, 0.012, 5, label="入力", font=small_font)
    draw_arrow(draw, cart_pos, magnetic_force_world, map_point, MAGNETIC_ARROW, 0.004, 5, label="磁気", font=small_font)
    if float(history_row["contact_force_n"]) > 1.0e-3:
        draw_arrow(draw, cart_pos, contact_force_world, map_point, CONTACT_ARROW, 0.0016, 5, label="接触", font=small_font)

    def label_box(anchor_xy, text, fill, outline, panel_box):
        bbox = draw.textbbox((0, 0), text, font=small_font)
        w = max(84, int(bbox[2] - bbox[0]) + 20)
        h = 34
        x, y = clamp_box_position(anchor_xy, w, h, panel_box, padding=10)
        draw.rounded_rectangle([x, y, x + w, y + h], radius=9, fill=fill, outline=outline, width=2)
        draw.text((x + 10, y + 6), text, fill=TEXT_MAIN, font=small_font)

    robot_label_xy = map_point(robot_pos + np.array([0.16, 0.20]))
    cart_label_xy = map_point(cart_pos + np.array([0.16, -0.26]))
    person_label_xy = map_point(person_pos + np.array([0.12, 0.18]))
    label_box(robot_label_xy, "LIMO", (233, 245, 243, 245), ROBOT_EDGE, scene_panel)
    label_box(cart_label_xy, "台車", (247, 240, 230, 245), OUTER_RING, scene_panel)
    label_box(person_label_xy, "歩行者", (249, 237, 217, 245), PERSON_EDGE, scene_panel)

    draw.text((24, 18), "Corridor Magnetic-Coupler Schematic Replay", fill=TEXT_MAIN, font=title_font)
    draw.text((24, 56), "上段は廊下全景、下段はジョイント超拡大。力の向きと相対位置を低速で確認", fill=TEXT_SUB, font=body_font)

    inset_scene = (zoom_panel[0] + 16, zoom_panel[1] + 54, zoom_panel[2] - 16, zoom_panel[3] - 16)
    draw.text((zoom_panel[0] + 18, zoom_panel[1] + 12), "ジョイント超拡大", fill=TEXT_MAIN, font=body_font)
    draw.text((zoom_panel[0] + 18, zoom_panel[1] + 38), "内外リング・磁石配置・入力/磁気/接触力", fill=TEXT_SUB, font=small_font)
    coupling_center = 0.5 * (robot_pos + cart_pos)
    local_span = max(
        0.36,
        1.05 * max(model.design.mean_radius_m + model.design.gap_m + model.design.magnet_radial_depth_m, 0.18),
    )
    inset_mapper, inset_scale = make_world_mapper(
        inset_scene,
        coupling_center[0] - local_span,
        coupling_center[0] + local_span,
        coupling_center[1] - local_span,
        coupling_center[1] + local_span,
        padding_px=20,
    )

    center_line_left = inset_mapper((coupling_center[0] - local_span, coupling_center[1]))
    center_line_right = inset_mapper((coupling_center[0] + local_span, coupling_center[1]))
    center_line_bottom = inset_mapper((coupling_center[0], coupling_center[1] - local_span))
    center_line_top = inset_mapper((coupling_center[0], coupling_center[1] + local_span))
    draw.line([center_line_left, center_line_right], fill=CENTERLINE, width=2)
    draw.line([center_line_bottom, center_line_top], fill=CENTERLINE, width=2)

    # Keep the zoom view intentionally minimal: rings + force arrows only.
    draw_polyline(draw, outer_ring, inset_mapper, OUTER_RING, width=3)
    draw_polyline(draw, inner_ring, inset_mapper, INNER_RING, width=3)
    draw_arrow(draw, cart_pos, input_force_world, inset_mapper, INPUT_ARROW, 0.012, 5, label="入力", font=small_font)
    draw_arrow(draw, cart_pos, magnetic_force_world, inset_mapper, MAGNETIC_ARROW, 0.004, 5, label="磁気", font=small_font)
    if float(history_row["contact_force_n"]) > 1.0e-3:
        draw_arrow(draw, cart_pos, contact_force_world, inset_mapper, CONTACT_ARROW, 0.0016, 5, label="接触", font=small_font)
    label_box(inset_mapper(robot_pos + np.array([0.10, 0.10])), "内リング", (233, 245, 243, 245), INNER_RING, zoom_panel)
    label_box(inset_mapper(cart_pos + np.array([0.10, -0.12])), "外リング", (247, 240, 230, 245), OUTER_RING, zoom_panel)

    rx0 = width_px - right_panel_w + 24
    y = 24
    draw.text((rx0, y), "状態", fill=TEXT_MAIN, font=title_font)
    y += 44
    live_lines = [
        f"frame: {frame_index + 1}/{frame_count}",
        f"time: {float(history_row['time_s']):.2f} s",
        f"phase: {history_row['phase']}",
        f"リング隙間: {float(history_row['ring_clearance_mm']):.2f} mm",
        f"接触要求: {float(history_row['contact_demand_mm']):.2f} mm",
        f"相対変位: {float(history_row['relative_xy_mm']):.2f} mm",
        f"相対ヨー: {float(history_row['relative_yaw_deg']):.2f} deg",
        f"高さシフト: {float(history_row['height_shift_mm']):.2f} mm",
        f"人入力: {float(history_row['input_force_n']):.2f} N",
        f"磁気力: {float(history_row['magnetic_force_n']):.2f} N",
        f"接触力: {float(history_row['contact_force_n']):.2f} N",
    ]
    for line in live_lines:
        draw.text((rx0, y), line, fill=TEXT_SUB, font=body_font)
        y += 31

    y += 12
    draw.text((rx0, y), "凡例", fill=TEXT_MAIN, font=body_font)
    y += 36
    legend = [
        (ROBOT_FILL, "ロボット本体"),
        (INNER_RING, "内側リング"),
        (INNER_MAGNET, "内側磁石"),
        (CART_FILL, "台車本体"),
        (OUTER_RING, "外側リング"),
        (OUTER_MAGNET, "外側磁石"),
        (PERSON_FILL, "対向歩行者"),
        (INPUT_ARROW, "人入力矢印"),
        (MAGNETIC_ARROW, "磁気力矢印"),
        (CONTACT_ARROW, "接触力矢印"),
    ]
    for color, text in legend:
        draw.rounded_rectangle([rx0, y + 4, rx0 + 22, y + 22], radius=5, fill=color)
        draw.text((rx0 + 34, y), text, fill=TEXT_SUB, font=small_font)
        y += 28

    y += 16
    draw.text((rx0, y), "判定", fill=TEXT_MAIN, font=body_font)
    y += 36
    draw_badge(draw, (rx0, y), f"リング非接触 {'OK' if summary['ring_clearance_pass'] else 'NG'}", bool(summary["ring_clearance_pass"]), small_font)
    y += 42
    draw_badge(draw, (rx0, y), f"吸着なし {'OK' if summary['no_attraction_pass'] else 'NG'}", bool(summary["no_attraction_pass"]), small_font)
    y += 42
    draw_badge(draw, (rx0, y), f"歩行者余裕 {'OK' if summary['pedestrian_clearance_pass'] else 'NG'}", bool(summary["pedestrian_clearance_pass"]), small_font)
    y += 42
    draw_badge(draw, (rx0, y), f"復帰 {'OK' if summary['route_return_pass'] else 'NG'}", bool(summary["route_return_pass"]), small_font)
    y += 52

    summary_lines = [
        f"min robot-person: {summary['min_robot_person_clearance_mm']:.1f} mm",
        f"min cart-person: {summary['min_cart_person_clearance_mm']:.1f} mm",
        f"worst ring clr: {summary['worst_ring_clearance_mm']:.1f} mm",
        f"max ring demand: {summary['max_contact_demand_mm']:.1f} mm",
        f"return time: {summary['route_return_time_s']}",
    ]
    for line in summary_lines:
        draw.text((rx0, y), line, fill=TEXT_SUB, font=small_font)
        y += 26

    return image.convert("RGB")


def render_video(args, model: hifi.ArrayModel, summary: dict, history_rows: list[dict], outdir: Path):
    video_path = outdir / args.video_name
    poster_path = outdir / "corridor_schematic_poster.png"
    source_fps = 1.0 / corridor_sim.DT_S
    desired_speed = max(float(args.playback_speed), 1.0e-3)
    raw_stride = math.floor(source_fps * desired_speed / max(args.fps, 1))
    frame_stride = max(int(raw_stride), 1)
    repeat_count = max(int(round(args.fps * corridor_sim.DT_S * frame_stride / desired_speed)), 1)
    sampled_rows = history_rows[::frame_stride]
    frame_count = len(sampled_rows)
    poster_index = min(
        range(frame_count),
        key=lambda idx: (
            abs(float(sampled_rows[idx].get("cart_person_clearance_mm", 1.0e9))),
            -float(sampled_rows[idx]["relative_yaw_deg"]),
            -float(sampled_rows[idx]["contact_demand_mm"]),
        ),
    )
    writer = imageio.get_writer(
        str(video_path),
        fps=args.fps,
        codec="libx264",
        quality=8,
        macro_block_size=None,
    )
    for frame_index, row in enumerate(sampled_rows):
        frame = attach_schematic_frame(
            model=model,
            history_row=row,
            summary=summary,
            frame_index=frame_index,
            frame_count=frame_count,
            size_wh=(args.width, args.height),
            args=args,
        )
        if frame_index == poster_index:
            frame.save(poster_path)
        frame_array = np.asarray(frame, dtype=np.uint8)
        for _ in range(repeat_count):
            writer.append_data(frame_array)
    writer.close()
    return video_path, poster_path


def main():
    args = parse_args()
    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    model, summary, history_rows = build_history(args, args.result_json, outdir)
    fidelity_report_path = write_fidelity_report(outdir, model, summary, history_rows)
    video_path, poster_path = render_video(args, model, summary, history_rows, outdir)
    payload = {
        "result_json": str(args.result_json),
        "video_path": str(video_path),
        "poster_path": str(poster_path),
        "history_csv": str(outdir / "corridor_history.csv"),
        "summary_json": str(outdir / "corridor_summary.json"),
        "frame_count_raw": len(history_rows),
        "fps": args.fps,
        "playback_speed": float(args.playback_speed),
        "duration_s": args.duration_s,
        "cart_mass_kg": float(model.design.cart_mass_kg),
        "fidelity_report_path": str(fidelity_report_path),
        "summary": summary,
    }
    (outdir / "schematic_video_summary.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
