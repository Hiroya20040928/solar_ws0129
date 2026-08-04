import argparse
import json
import math
from pathlib import Path

import imageio.v2 as imageio
import mujoco
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Render the corridor pedestrian-avoidance magnetic-coupler simulation as a MuJoCo video."
    )
    parser.add_argument("--result-json", type=Path, default=DEFAULT_RESULT_JSON)
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_mujoco_corridor_video_20260706",
    )
    parser.add_argument("--duration-s", type=float, default=14.0)
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--grid", choices=("search", "validation"), default="search")
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--fixed-height", action="store_true")
    parser.add_argument("--fixed-height-shift-mm", type=float, default=0.0)
    parser.add_argument("--corridor-length-m", type=float, default=22.0)
    parser.add_argument("--ring-segments", type=int, default=40)
    parser.add_argument("--video-name", type=str, default="corridor_pedestrian_avoidance_mujoco.mp4")
    return parser.parse_args()


def yaw_to_quat(yaw_rad: float) -> np.ndarray:
    half = 0.5 * float(yaw_rad)
    return np.array([math.cos(half), 0.0, 0.0, math.sin(half)], dtype=float)


def pick_ring_points(points_xy: np.ndarray, segment_count: int) -> np.ndarray:
    count = len(points_xy)
    if count <= segment_count:
        return np.asarray(points_xy, dtype=float)
    indices = np.linspace(0, count, segment_count, endpoint=False, dtype=int)
    return np.asarray(points_xy[indices], dtype=float)


def capsules_from_polyline(points_xy: np.ndarray, z_m: float, radius_m: float, rgba: tuple[float, float, float, float]) -> list[str]:
    points = np.asarray(points_xy, dtype=float)
    if len(points) < 3:
        return []
    geoms = []
    rolled = np.roll(points, -1, axis=0)
    for start, end in zip(points, rolled):
        geoms.append(
            (
                f'<geom type="capsule" fromto="{start[0]:.6f} {start[1]:.6f} {z_m:.6f} '
                f'{end[0]:.6f} {end[1]:.6f} {z_m:.6f}" size="{radius_m:.6f}" '
                f'rgba="{rgba[0]:.3f} {rgba[1]:.3f} {rgba[2]:.3f} {rgba[3]:.3f}"/>'
            )
        )
    return geoms


def build_mjcf_text(model: hifi.ArrayModel, width_px: int, height_px: int, corridor_length_m: float, ring_segments: int) -> str:
    corridor_width_m = corridor_sim.CORRIDOR_WIDTH_M
    wall_half_thickness_m = 0.025
    wall_height_m = 0.35
    floor_half_size_y = 0.5 * corridor_length_m
    inner_points = pick_ring_points(model.geometry.inner_points, ring_segments)
    outer_points = pick_ring_points(model.geometry.outer_points_local, ring_segments)
    inner_ring = "\n        ".join(
        capsules_from_polyline(inner_points, z_m=0.090, radius_m=0.0038, rgba=(0.14, 0.24, 0.95, 0.95))
    )
    outer_ring = "\n        ".join(
        capsules_from_polyline(outer_points, z_m=0.102, radius_m=0.0042, rgba=(0.05, 0.05, 0.08, 0.92))
    )
    lane_markers = []
    marker_y = -2.0
    while marker_y <= corridor_length_m:
        lane_markers.append(
            f'<geom type="box" pos="0 {marker_y:.3f} 0.001" size="0.008 0.250 0.001" rgba="0.92 0.92 0.95 1"/>'
        )
        marker_y += 1.1
    markers_text = "\n      ".join(lane_markers)
    return f"""
<mujoco model="magnetic_coupler_corridor_replay">
  <compiler angle="radian"/>
  <option timestep="0.02" gravity="0 0 -9.81"/>
  <visual>
    <global offwidth="{width_px}" offheight="{height_px}"/>
    <headlight ambient="0.75 0.75 0.75" diffuse="0.55 0.55 0.55" specular="0.05 0.05 0.05"/>
    <rgba haze="1 1 1 1"/>
  </visual>
  <asset>
    <texture name="sky" type="skybox" builtin="flat" rgb1="0.98 0.98 0.99" width="32" height="32"/>
    <material name="floor" rgba="0.95 0.95 0.94 1"/>
    <material name="wall" rgba="0.43 0.47 0.55 1"/>
  </asset>
  <worldbody>
    <light pos="0 0 8" dir="0 0 -1" directional="true" diffuse="0.95 0.95 0.95"/>
    <geom name="floor" type="plane" size="3 {floor_half_size_y + 2.0:.3f} 0.1" material="floor"/>
    <geom name="left_wall" type="box" pos="-{0.5 * corridor_width_m + wall_half_thickness_m:.6f} {floor_half_size_y - 1.0:.6f} {wall_height_m:.6f}" size="{wall_half_thickness_m:.6f} {floor_half_size_y + 2.0:.6f} {wall_height_m:.6f}" material="wall"/>
    <geom name="right_wall" type="box" pos="{0.5 * corridor_width_m + wall_half_thickness_m:.6f} {floor_half_size_y - 1.0:.6f} {wall_height_m:.6f}" size="{wall_half_thickness_m:.6f} {floor_half_size_y + 2.0:.6f} {wall_height_m:.6f}" material="wall"/>
    {markers_text}
    <body name="robot" pos="0 0 0.0">
      <freejoint name="robot_free"/>
      <geom type="box" pos="0 0 {0.5 * 0.070:.6f}" size="{0.5 * hifi.ROBOT_WIDTH_M:.6f} {0.5 * hifi.ROBOT_LENGTH_M:.6f} {0.5 * 0.070:.6f}" rgba="0.25 0.74 0.70 0.96"/>
      <geom type="box" pos="0 {0.5 * hifi.ROBOT_LENGTH_M - 0.025:.6f} {0.5 * 0.078:.6f}" size="{0.5 * hifi.ROBOT_WIDTH_M - 0.015:.6f} 0.025000 {0.5 * 0.078:.6f}" rgba="0.04 0.33 0.31 1"/>
      {inner_ring}
    </body>
    <body name="cart" pos="0 0 0.0">
      <freejoint name="cart_free"/>
      <geom type="box" pos="0 0 {0.5 * 0.082:.6f}" size="{0.5 * hifi.CART_WIDTH_M:.6f} {0.5 * hifi.CART_LENGTH_M:.6f} {0.5 * 0.082:.6f}" rgba="0.82 0.84 0.89 0.84"/>
      <geom type="capsule" fromto="0 {-0.5 * hifi.CART_LENGTH_M + 0.04:.6f} 0.120 0 {0.5 * hifi.CART_LENGTH_M + 0.10:.6f} 0.120" size="0.010" rgba="0.32 0.36 0.45 1"/>
      {outer_ring}
    </body>
    <body name="person" pos="0 0 0.0">
      <freejoint name="person_free"/>
      <geom type="capsule" fromto="0 0 0.05 0 0 0.90" size="0.110" rgba="0.87 0.62 0.27 0.97"/>
      <geom type="sphere" pos="0 0 1.06" size="0.12" rgba="0.94 0.84 0.72 1"/>
    </body>
  </worldbody>
</mujoco>
""".strip()


def try_load_font(size: int):
    candidates = [
        Path(r"C:\Windows\Fonts\meiryo.ttc"),
        Path(r"C:\Windows\Fonts\msgothic.ttc"),
        Path(r"C:\Windows\Fonts\arial.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except Exception:
                pass
    return ImageFont.load_default()


def attach_hud(rgb: np.ndarray, row: dict, summary: dict, frame_index: int, frame_count: int) -> np.ndarray:
    base = Image.fromarray(rgb)
    hud_width = 360
    canvas = Image.new("RGB", (base.width + hud_width, base.height), (246, 246, 244))
    canvas.paste(base, (0, 0))
    draw = ImageDraw.Draw(canvas)
    title_font = try_load_font(28)
    body_font = try_load_font(20)
    small_font = try_load_font(18)

    x0 = base.width + 24
    y = 20
    draw.text((x0, y), "MuJoCo Corridor Replay", fill=(20, 28, 44), font=title_font)
    y += 48
    lines = [
        f"frame: {frame_index + 1}/{frame_count}",
        f"time: {row['time_s']:.2f} s",
        f"phase: {row['phase']}",
        f"ring clearance: {row['ring_clearance_mm']:.2f} mm",
        f"contact demand: {row['contact_demand_mm']:.2f} mm",
        f"relative XY: {row['relative_xy_mm']:.2f} mm",
        f"relative yaw: {row['relative_yaw_deg']:.2f} deg",
        f"height shift: {row['height_shift_mm']:.2f} mm",
        f"human input: {row['input_force_n']:.2f} N",
        f"magnetic force: {row['magnetic_force_n']:.2f} N",
        f"contact force: {row['contact_force_n']:.2f} N",
    ]
    for line in lines:
        draw.text((x0, y), line, fill=(35, 42, 55), font=body_font)
        y += 30

    y += 18
    draw.text((x0, y), "Scenario summary", fill=(20, 28, 44), font=body_font)
    y += 34
    summary_lines = [
        f"all pass: {int(summary['all_pass'])}",
        f"min robot-person clr: {summary['min_robot_person_clearance_mm']:.1f} mm",
        f"min cart-person clr: {summary['min_cart_person_clearance_mm']:.1f} mm",
        f"worst ring clr: {summary['worst_ring_clearance_mm']:.1f} mm",
        f"max ring demand: {summary['max_contact_demand_mm']:.1f} mm",
        f"route return time: {summary['route_return_time_s']}",
    ]
    for line in summary_lines:
        draw.text((x0, y), line, fill=(50, 56, 70), font=small_font)
        y += 28
    return np.asarray(canvas, dtype=np.uint8)


def set_body_pose(data: mujoco.MjData, model: mujoco.MjModel, joint_name: str, x_m: float, y_m: float, z_m: float, yaw_rad: float):
    joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
    qpos_adr = model.jnt_qposadr[joint_id]
    data.qpos[qpos_adr : qpos_adr + 3] = np.array([x_m, y_m, z_m], dtype=float)
    data.qpos[qpos_adr + 3 : qpos_adr + 7] = yaw_to_quat(yaw_rad)


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


def render_video(args, model: hifi.ArrayModel, summary: dict, history_rows: list[dict], outdir: Path):
    mjcf_text = build_mjcf_text(
        model=model,
        width_px=args.width,
        height_px=args.height,
        corridor_length_m=args.corridor_length_m,
        ring_segments=args.ring_segments,
    )
    mjcf_path = outdir / "corridor_scene.xml"
    mjcf_path.write_text(mjcf_text, encoding="utf-8")

    mj_model = mujoco.MjModel.from_xml_string(mjcf_text)
    mj_data = mujoco.MjData(mj_model)
    renderer = mujoco.Renderer(mj_model, args.height, args.width)
    camera = mujoco.MjvCamera()
    mujoco.mjv_defaultFreeCamera(mj_model, camera)
    camera.type = mujoco.mjtCamera.mjCAMERA_FREE
    camera.azimuth = 180.0
    camera.elevation = -88.0
    camera.distance = 8.8
    camera.lookat[:] = np.array([0.0, 3.0, 0.0], dtype=float)

    video_path = outdir / args.video_name
    poster_path = outdir / "corridor_poster.png"
    writer = imageio.get_writer(
        str(video_path),
        fps=args.fps,
        codec="libx264",
        quality=8,
        macro_block_size=None,
    )

    frame_stride = max(int(round((1.0 / corridor_sim.DT_S) / args.fps)), 1)
    sampled_rows = history_rows[::frame_stride]
    frame_count = len(sampled_rows)
    poster_index = max(
        range(frame_count),
        key=lambda idx: (
            float(sampled_rows[idx]["relative_yaw_deg"]),
            float(sampled_rows[idx]["contact_demand_mm"]),
            float(sampled_rows[idx]["relative_xy_mm"]),
        ),
    )

    for frame_index, row in enumerate(sampled_rows):
        set_body_pose(
            mj_data,
            mj_model,
            "robot_free",
            float(row["robot_x_m"]),
            float(row["robot_y_m"]),
            0.0,
            math.radians(float(row["robot_yaw_deg"])),
        )
        set_body_pose(
            mj_data,
            mj_model,
            "cart_free",
            float(row["cart_x_m"]),
            float(row["cart_y_m"]),
            0.0,
            math.radians(float(row["cart_yaw_deg"])),
        )
        set_body_pose(
            mj_data,
            mj_model,
            "person_free",
            float(row["person_x_m"]),
            float(row["person_y_m"]),
            0.0,
            -0.5 * math.pi,
        )
        mujoco.mj_forward(mj_model, mj_data)
        robot_y = float(row["robot_y_m"])
        person_y = float(row["person_y_m"])
        robot_x = float(row["robot_x_m"])
        person_x = float(row["person_x_m"])
        center_y = 0.5 * (robot_y + person_y)
        center_x = 0.5 * (robot_x + person_x)
        relative_person_span = abs(person_y - robot_y)
        camera.distance = min(8.8, max(4.6, 1.8 + 0.78 * relative_person_span))
        camera.lookat[:] = np.array(
            [
                float(np.clip(center_x, -0.15, 0.15)),
                float(np.clip(center_y, 1.2, args.corridor_length_m - 1.2)),
                0.12,
            ],
            dtype=float,
        )
        renderer.update_scene(mj_data, camera=camera)
        rgb = renderer.render()
        rgb = np.flipud(rgb)
        frame = attach_hud(rgb, row, summary, frame_index, frame_count)
        if frame_index == poster_index:
            Image.fromarray(frame).save(poster_path)
        writer.append_data(frame)
    writer.close()
    renderer.close()
    return video_path, poster_path, mjcf_path


def main():
    args = parse_args()
    outdir = args.outdir
    outdir.mkdir(parents=True, exist_ok=True)
    result_json = args.result_json
    model, summary, history_rows = build_history(args, result_json, outdir)
    video_path, poster_path, mjcf_path = render_video(args, model, summary, history_rows, outdir)
    payload = {
        "result_json": str(result_json),
        "video_path": str(video_path),
        "poster_path": str(poster_path),
        "mjcf_path": str(mjcf_path),
        "history_csv": str(outdir / "corridor_history.csv"),
        "summary_json": str(outdir / "corridor_summary.json"),
        "frame_count": len(history_rows),
        "fps": args.fps,
        "duration_s": args.duration_s,
        "used_result_shape": model.design.shape_parameters.family,
        "cart_mass_kg": float(model.design.cart_mass_kg),
        "summary": summary,
    }
    (outdir / "mujoco_video_summary.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
