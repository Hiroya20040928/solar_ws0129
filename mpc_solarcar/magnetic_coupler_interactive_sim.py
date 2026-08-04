import argparse
import csv
import json
import math
import time
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from mpc_solarcar import magnetic_coupler_hifi as hifi
from mpc_solarcar import magnetic_coupler_rl as base


ROOT = Path(r"C:\Users\user\OneDrive - 和歌山大学\ソーラー\エネマネ\solar_ws0129-main")
DEFAULT_OUTPUT_CANDIDATES = [
    ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_research_cmaes_20260701" / "best_design_hifi.json",
    ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_limo_stable3" / "best_design_hifi.json",
    ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_contactsafe" / "best_design_hifi.json",
    ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_revised" / "best_design_hifi.json",
    ROOT / "outputs" / "magnetic_coupler_hifi" / "best_design_hifi.json",
]
CANVAS_W = 1320
CANVAS_H = 860
CORRIDOR_WIDTH_M = 1.80
ROBOT_SPEED_MPS = hifi.ROBOT_COMMAND_SPEED_MPS
ROBOT_ACCEL_LIMIT_MPS2 = 0.10
HAND_FORCE_N = 18.0
DT_S = 1.0 / 50.0
PIXELS_PER_METER = 320.0
ROBOT_TURN_RATE_RADPS = math.radians(95.0)
PEDESTRIAN_RADIUS_M = 0.24
PEDESTRIAN_SPEED_MPS = 0.90
ROBOT_BODY_RADIUS_M = 0.5 * math.hypot(hifi.ROBOT_LENGTH_M, hifi.ROBOT_WIDTH_M)
CART_BODY_RADIUS_M = 0.5 * math.hypot(hifi.CART_LENGTH_M, hifi.CART_WIDTH_M)
FIXED_HEIGHT_EPS_M = 1.0e-12


def angle_wrap(value):
    return math.atan2(math.sin(value), math.cos(value))


def clamp(value, low, high):
    return max(low, min(high, value))


def clamp_norm(vector, limit):
    norm = float(np.linalg.norm(vector))
    if norm <= limit or norm <= 1.0e-12:
        return vector
    return vector * (limit / norm)


def normalized_or_default(vector, default):
    norm = float(np.linalg.norm(vector))
    if norm <= 1.0e-12:
        return np.array(default, dtype=float)
    return np.array(vector, dtype=float) / norm


def bounded_force_from_command(command_vector, force_limit_n):
    norm = float(np.linalg.norm(command_vector))
    if norm <= 1.0e-12:
        return np.zeros(2, dtype=float)
    direction = np.array(command_vector, dtype=float) / norm
    return direction * min(norm, 1.0) * force_limit_n


def rotmat(yaw_rad):
    c = math.cos(yaw_rad)
    s = math.sin(yaw_rad)
    return np.array([[c, -s], [s, c]], dtype=float)


def transform_points(local_points, position_world, yaw_rad):
    return (local_points @ rotmat(yaw_rad).T) + position_world


def resolve_default_result_json():
    for candidate in DEFAULT_OUTPUT_CANDIDATES:
        if candidate.exists():
            return candidate
    return DEFAULT_OUTPUT_CANDIDATES[0]


def load_selected_model(result_json: Path, sample_count: int, dipole_grid):
    payload = json.loads(result_json.read_text(encoding="utf-8"))
    design_dict = dict(payload["selected_design"])
    shape_parameters = hifi.ShapeParameters(**design_dict.pop("shape_parameters"))
    design = hifi.HifiDesign(shape_parameters=shape_parameters, **design_dict)
    policy = hifi.HeightPolicy(**payload["selected_policy"])
    geometry = hifi.build_geometry_from_shape(
        shape_parameters,
        design.mean_radius_m,
        design.gap_m,
        sample_count,
    )
    model = hifi.build_array_model(design, geometry, dipole_grid)
    return payload, design, policy, model


@dataclass
class KeyboardVectors:
    robot: np.ndarray = field(default_factory=lambda: np.array([0.0, 1.0], dtype=float))
    left: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))
    right: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))


@dataclass
class SimState:
    time_s: float = 0.0
    robot_pos_world: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0], dtype=float))
    robot_yaw_rad: float = math.pi / 2.0
    robot_yaw_rate_radps: float = 0.0
    robot_speed_mps: float = 0.0
    robot_velocity_world: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))
    cart_pos_world: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))
    cart_yaw_rad: float = math.pi / 2.0
    cart_yaw_rate_radps: float = 0.0
    cart_velocity_world: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))
    height_shift_m: float = 0.0
    min_clearance_m: float = 0.0
    raw_gap_m: float = 0.0
    contact_demand_m: float = 0.0
    contact_force_world_n: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))
    magnetic_force_world_n: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))
    input_force_world_n: np.ndarray = field(default_factory=lambda: np.zeros(2, dtype=float))
    input_torque_nm: float = 0.0
    contact_active: bool = False


@dataclass
class PedestrianState:
    pos_world: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0], dtype=float))
    vel_world: np.ndarray = field(default_factory=lambda: np.array([0.0, -PEDESTRIAN_SPEED_MPS], dtype=float))
    radius_m: float = PEDESTRIAN_RADIUS_M


@dataclass
class CorridorScenarioMetrics:
    min_robot_person_clearance_m: float = float("inf")
    min_cart_person_clearance_m: float = float("inf")
    max_contact_demand_m: float = 0.0
    min_ring_clearance_m: float = float("inf")
    max_relative_xy_m: float = 0.0
    max_relative_yaw_deg: float = 0.0
    max_robot_route_offset_m: float = 0.0
    max_cart_route_offset_m: float = 0.0
    route_return_time_s: float | None = None
    route_avoid_peak_time_s: float | None = None
    contact_active_steps: int = 0


class InteractiveCouplerCore:
    def __init__(
        self,
        model: hifi.ArrayModel,
        policy: hifi.HeightPolicy,
        height_control_enabled: bool = True,
        fixed_height_shift_m: float = 0.0,
    ):
        self.model = model
        self.policy = policy
        self.height_control_enabled = bool(height_control_enabled)
        self.fixed_height_shift_m = float(
            base.clamp(fixed_height_shift_m, 0.0, model.design.max_overlap_reduction_m)
        )
        self.environment = hifi.nominal_episode_environment()
        self.dynamics = hifi.follower_and_damping_params(model, self.environment)
        self.state = SimState()
        self.state.height_shift_m = self.fixed_height_shift_m
        self.keys = KeyboardVectors()
        self.last_step_ms = 0.0
        self.max_contact_demand_m = 0.0
        self.min_clearance_seen_m = float("inf")

    def reset(self):
        self.state = SimState()
        self.state.height_shift_m = self.fixed_height_shift_m
        self.keys = KeyboardVectors()
        self.last_step_ms = 0.0
        self.max_contact_demand_m = 0.0
        self.min_clearance_seen_m = float("inf")

    def step(self, dt_s: float):
        start = time.perf_counter()
        state = self.state
        robot_dir_world = normalized_or_default(self.keys.robot, [0.0, 1.0])
        target_robot_yaw = math.atan2(robot_dir_world[1], robot_dir_world[0])
        yaw_error = angle_wrap(target_robot_yaw - state.robot_yaw_rad)
        state.robot_yaw_rate_radps = clamp(yaw_error / max(dt_s, 1.0e-4), -ROBOT_TURN_RATE_RADPS, ROBOT_TURN_RATE_RADPS)
        state.robot_yaw_rad = angle_wrap(state.robot_yaw_rad + state.robot_yaw_rate_radps * dt_s)
        robot_dir_world = np.array([math.cos(state.robot_yaw_rad), math.sin(state.robot_yaw_rad)], dtype=float)
        state.robot_speed_mps = clamp(state.robot_speed_mps + ROBOT_ACCEL_LIMIT_MPS2 * dt_s, 0.0, ROBOT_SPEED_MPS)
        state.robot_velocity_world = state.robot_speed_mps * robot_dir_world
        state.robot_pos_world = state.robot_pos_world + state.robot_velocity_world * dt_s

        left_handle_local = np.array([-0.14, 0.22], dtype=float)
        right_handle_local = np.array([0.14, 0.22], dtype=float)
        left_handle_world = state.cart_pos_world + rotmat(state.cart_yaw_rad) @ left_handle_local
        right_handle_world = state.cart_pos_world + rotmat(state.cart_yaw_rad) @ right_handle_local

        left_force_world = bounded_force_from_command(self.keys.left, HAND_FORCE_N)
        right_force_world = bounded_force_from_command(self.keys.right, HAND_FORCE_N)

        input_force_world_n = left_force_world + right_force_world
        input_torque_nm = base.cross2(left_handle_world - state.cart_pos_world, left_force_world) + base.cross2(
            right_handle_world - state.cart_pos_world,
            right_force_world,
        )

        relative_translation_world = state.cart_pos_world - state.robot_pos_world
        relative_translation_body = rotmat(-state.robot_yaw_rad) @ relative_translation_world
        relative_yaw_rad = angle_wrap(state.cart_yaw_rad - state.robot_yaw_rad)
        relative_velocity_world = state.cart_velocity_world - state.robot_velocity_world
        relative_yaw_rate = state.cart_yaw_rate_radps - state.robot_yaw_rate_radps
        relative_speed = float(np.linalg.norm(relative_velocity_world))

        preview = hifi.evaluate_pose(self.model, relative_translation_body, relative_yaw_rad, state.height_shift_m)
        if self.height_control_enabled:
            features = {
                "torque_intent": abs(input_torque_nm) / 26.0,
                "force_intent": np.linalg.norm(input_force_world_n) / 65.0,
                "yaw_ratio": abs(relative_yaw_rad) / max(self.model.yaw_contact_limit_rad, 0.08),
                "yaw_rate_ratio": abs(relative_yaw_rate) / 2.8,
                "gap_margin_ratio": preview.min_gap_m / max(self.model.design.gap_m, 1.0e-4),
                "translation_ratio": np.linalg.norm(relative_translation_body)
                / max(self.model.translation_contact_limit_m, 0.004),
                "speed_ratio": relative_speed / hifi.MAX_LINEAR_SPEED_MPS,
            }
            target_shift_m = self.policy.target_height_shift(self.model.design, features)
            shift_error_m = target_shift_m - state.height_shift_m
            max_change_m = self.dynamics["height_rate_limit_mps"] * dt_s
            state.height_shift_m += base.clamp(
                shift_error_m / max(self.dynamics["height_tau_s"], 1.0e-4) * dt_s,
                -max_change_m,
                max_change_m,
            )
            state.height_shift_m = base.clamp(state.height_shift_m, 0.0, self.model.design.max_overlap_reduction_m)
        else:
            state.height_shift_m = self.fixed_height_shift_m

        coupling = hifi.evaluate_pose(self.model, relative_translation_body, relative_yaw_rad, state.height_shift_m)
        magnetic_force_world_n = rotmat(state.robot_yaw_rad) @ coupling.force_body_n
        magnetic_outer_torque_nm = coupling.torque_outer_nm

        contact_force_world_n = np.zeros(2, dtype=float)
        contact_outer_torque_nm = 0.0
        if coupling.contact_penetration_m > 0.0:
            normal_world = rotmat(state.robot_yaw_rad) @ coupling.contact_normal_body
            outer_contact_world = state.robot_pos_world + rotmat(state.robot_yaw_rad) @ coupling.outer_contact_point_body
            inner_contact_world = state.robot_pos_world + rotmat(state.robot_yaw_rad) @ coupling.inner_contact_point_body
            outer_contact_velocity = hifi.contact_point_velocity(
                state.cart_velocity_world,
                state.cart_yaw_rate_radps,
                outer_contact_world,
                state.cart_pos_world,
            )
            inner_contact_velocity = hifi.contact_point_velocity(
                state.robot_velocity_world,
                state.robot_yaw_rate_radps,
                inner_contact_world,
                state.robot_pos_world,
            )
            relative_contact_velocity = outer_contact_velocity - inner_contact_velocity
            normal_speed = float(np.dot(relative_contact_velocity, normal_world))
            # For the corridor replay, keep contact as a hard non-penetration constraint rather than
            # a giant spring that creates visually impossible vibration.
            contact_force_world_n = np.zeros(2, dtype=float)
            contact_outer_torque_nm = 0.0

        force_world_n = (
            input_force_world_n
            + magnetic_force_world_n
            + contact_force_world_n
            + hifi.cart_passive_force_world(state.cart_velocity_world, state.cart_yaw_rad, self.dynamics)
        )
        passive_cart_align_torque_nm = hifi.cart_passive_alignment_torque(
            state.cart_velocity_world,
            state.cart_yaw_rad,
            state.cart_yaw_rate_radps,
            self.dynamics,
            yaw_reference_rad=state.robot_yaw_rad,
            yaw_reference_rate_rad_s=state.robot_yaw_rate_radps,
        )
        torque_outer_nm = (
            input_torque_nm
            + magnetic_outer_torque_nm
            + contact_outer_torque_nm
            + passive_cart_align_torque_nm
        )

        cart_mass = float(self.dynamics.get("effective_cart_mass_kg", self.model.design.cart_mass_kg))
        cart_inertia = hifi.cart_inertia_kgm2(cart_mass)
        state.cart_velocity_world += (force_world_n / cart_mass) * dt_s
        state.cart_velocity_world = clamp_norm(state.cart_velocity_world, hifi.MAX_CART_LINEAR_SPEED_MPS)
        state.cart_pos_world = state.cart_pos_world + state.cart_velocity_world * dt_s
        state.cart_yaw_rate_radps += (torque_outer_nm / cart_inertia) * dt_s
        state.cart_yaw_rate_radps = base.clamp(
            state.cart_yaw_rate_radps,
            -hifi.MAX_CART_YAW_RATE_RADPS,
            hifi.MAX_CART_YAW_RATE_RADPS,
        )
        state.cart_yaw_rad = angle_wrap(state.cart_yaw_rad + state.cart_yaw_rate_radps * dt_s)

        post, _post_residual_m, _iterations = hifi.settle_nonpenetration(
            self.model,
            state.cart_yaw_rad,
            state.robot_yaw_rad,
            state.height_shift_m,
            self.environment,
            state.cart_pos_world,
            state.cart_velocity_world,
            state.robot_pos_world,
            state.robot_velocity_world,
            cart_mass,
        )
        coupling = post

        max_half_width = 0.5 * max(hifi.CART_WIDTH_M, hifi.ROBOT_WIDTH_M)
        for body in ("robot_pos_world", "cart_pos_world"):
            position = getattr(state, body)
            if position[0] < -(0.5 * CORRIDOR_WIDTH_M - max_half_width):
                position[0] = -(0.5 * CORRIDOR_WIDTH_M - max_half_width)
            if position[0] > 0.5 * CORRIDOR_WIDTH_M - max_half_width:
                position[0] = 0.5 * CORRIDOR_WIDTH_M - max_half_width

        relative_translation_body = rotmat(-state.robot_yaw_rad) @ (state.cart_pos_world - state.robot_pos_world)
        relative_yaw_rad = angle_wrap(state.cart_yaw_rad - state.robot_yaw_rad)
        final_sample = hifi.evaluate_pose(self.model, relative_translation_body, relative_yaw_rad, state.height_shift_m)

        state.time_s += dt_s
        state.min_clearance_m = final_sample.min_gap_m
        state.raw_gap_m = final_sample.raw_signed_gap_m
        state.contact_demand_m = max(coupling.contact_penetration_m, final_sample.contact_penetration_m)
        state.contact_force_world_n = contact_force_world_n
        state.magnetic_force_world_n = magnetic_force_world_n
        state.input_force_world_n = input_force_world_n
        state.input_torque_nm = float(input_torque_nm)
        state.contact_active = state.contact_demand_m > hifi.DYNAMIC_CONTACT_MARGIN_M
        self.max_contact_demand_m = max(self.max_contact_demand_m, state.contact_demand_m)
        self.min_clearance_seen_m = min(self.min_clearance_seen_m, state.min_clearance_m)
        self.last_step_ms = (time.perf_counter() - start) * 1000.0

    def scripted_inputs(self, time_s: float):
        robot = np.array([0.0, 1.0], dtype=float)
        left = np.zeros(2, dtype=float)
        right = np.zeros(2, dtype=float)
        if 2.0 <= time_s < 4.0:
            robot = np.array([0.18, 0.98], dtype=float)
            left = np.array([-0.4, 1.0], dtype=float)
            right = np.array([0.4, 1.0], dtype=float)
        elif 4.0 <= time_s < 6.0:
            robot = np.array([-0.18, 0.98], dtype=float)
            left = np.array([0.9, 0.3], dtype=float)
            right = np.array([0.9, 0.3], dtype=float)
        elif 6.0 <= time_s < 8.0:
            robot = np.array([0.0, 1.0], dtype=float)
            left = np.array([-0.8, 0.1], dtype=float)
            right = np.array([0.8, 0.1], dtype=float)
        self.keys = KeyboardVectors(robot=robot, left=left, right=right)


class CorridorPedestrianAvoidanceScenario:
    """Scripted corridor encounter: start pushing, sidestep an oncoming pedestrian, then return."""

    def __init__(
        self,
        core: InteractiveCouplerCore,
        duration_s: float = 14.0,
        person_start_x_m: float = -0.22,
        person_start_y_m: float = 7.00,
        pedestrian_speed_mps: float = PEDESTRIAN_SPEED_MPS,
        target_offset_max_m: float = 0.25,
        target_trigger_far_m: float = 5.20,
        target_hold_entry_m: float = 3.00,
        target_hold_exit_m: float = -1.00,
        target_return_done_m: float = -3.00,
    ):
        self.core = core
        self.duration_s = float(duration_s)
        self.person_start_x_m = float(person_start_x_m)
        self.person_start_y_m = float(person_start_y_m)
        self.pedestrian_speed_mps = float(pedestrian_speed_mps)
        self.target_offset_max_m = float(target_offset_max_m)
        self.target_trigger_far_m = float(target_trigger_far_m)
        self.target_hold_entry_m = float(target_hold_entry_m)
        self.target_hold_exit_m = float(target_hold_exit_m)
        self.target_return_done_m = float(target_return_done_m)
        self.route_center_x_m = 0.0
        self.person = PedestrianState(
            pos_world=np.array([self.person_start_x_m, self.person_start_y_m], dtype=float),
            vel_world=np.array([0.0, -self.pedestrian_speed_mps], dtype=float),
        )
        self.phase = "approach"
        self.metrics = CorridorScenarioMetrics()
        self.history_rows = []
        self.completed = False

    def reset(self):
        self.core.reset()
        self.person = PedestrianState(
            pos_world=np.array([self.person_start_x_m, self.person_start_y_m], dtype=float),
            vel_world=np.array([0.0, -self.pedestrian_speed_mps], dtype=float),
        )
        self.phase = "approach"
        self.metrics = CorridorScenarioMetrics()
        self.history_rows = []
        self.completed = False

    def desired_route_offset_m(self):
        robot_y = self.core.state.robot_pos_world[1]
        relative_y = self.person.pos_world[1] - robot_y
        if relative_y > self.target_trigger_far_m:
            return 0.0
        if relative_y > self.target_hold_entry_m:
            return self.target_offset_max_m * (
                self.target_trigger_far_m - relative_y
            ) / max(self.target_trigger_far_m - self.target_hold_entry_m, 1.0e-6)
        if relative_y > self.target_hold_exit_m:
            return self.target_offset_max_m
        if relative_y > self.target_return_done_m:
            return self.target_offset_max_m * (
                relative_y - self.target_return_done_m
            ) / max(self.target_hold_exit_m - self.target_return_done_m, 1.0e-6)
        return 0.0

    def update_phase(self, target_offset_m: float):
        robot_y = self.core.state.robot_pos_world[1]
        relative_y = self.person.pos_world[1] - robot_y
        if target_offset_m > 0.05 and relative_y > 0.35:
            self.phase = "avoid_right"
        elif target_offset_m > 0.05:
            self.phase = "hold_clearance"
        elif abs(self.core.state.robot_pos_world[0]) > 0.08 or abs(self.core.state.cart_pos_world[0]) > 0.08:
            self.phase = "return_center"
        else:
            self.phase = "cruise"

    def scripted_inputs(self):
        target_offset_m = self.desired_route_offset_m()
        self.update_phase(target_offset_m)
        robot_x_error = target_offset_m - self.core.state.robot_pos_world[0]
        cart_x_error = target_offset_m - self.core.state.cart_pos_world[0]
        relative_yaw_rad = angle_wrap(self.core.state.cart_yaw_rad - self.core.state.robot_yaw_rad)
        relative_xy_x_m = self.core.state.cart_pos_world[0] - self.core.state.robot_pos_world[0]

        robot_dir = normalized_or_default(
            [
                3.2 * robot_x_error + 1.0 * cart_x_error - 0.6 * relative_xy_x_m,
                1.0,
            ],
            [0.0, 1.0],
        )
        desired_fx_n = clamp(46.0 * cart_x_error - 12.0 * relative_xy_x_m, -12.0, 12.0)
        desired_fy_n = 13.5 if abs(target_offset_m) > 0.03 else 8.5
        desired_torque_nm = clamp(
            -5.2 * relative_yaw_rad - 0.9 * self.core.state.cart_yaw_rate_radps,
            -2.2,
            2.2,
        )
        handle_half_span_x_m = 0.14
        handle_forward_y_m = 0.22
        differential_fy_n = -(desired_torque_nm + handle_forward_y_m * desired_fx_n) / max(
            2.0 * handle_half_span_x_m,
            1.0e-6,
        )
        left_force = clamp_norm(
            np.array([0.5 * desired_fx_n, 0.5 * desired_fy_n + differential_fy_n], dtype=float),
            HAND_FORCE_N,
        )
        right_force = clamp_norm(
            np.array([0.5 * desired_fx_n, 0.5 * desired_fy_n - differential_fy_n], dtype=float),
            HAND_FORCE_N,
        )
        self.core.keys = KeyboardVectors(
            robot=np.array(robot_dir, dtype=float),
            left=np.array(left_force / HAND_FORCE_N, dtype=float),
            right=np.array(right_force / HAND_FORCE_N, dtype=float),
        )

    def person_clearance_m(self, body_center_world: np.ndarray, body_radius_m: float):
        return float(np.linalg.norm(self.person.pos_world - body_center_world) - (self.person.radius_m + body_radius_m))

    def step(self, dt_s: float):
        if self.completed:
            return
        self.scripted_inputs()
        self.core.step(dt_s)
        self.person.pos_world = self.person.pos_world + self.person.vel_world * dt_s

        state = self.core.state
        relative_xy_m = float(np.linalg.norm(state.cart_pos_world - state.robot_pos_world))
        relative_yaw_deg = abs(math.degrees(angle_wrap(state.cart_yaw_rad - state.robot_yaw_rad)))
        robot_person_clearance_m = self.person_clearance_m(state.robot_pos_world, ROBOT_BODY_RADIUS_M)
        cart_person_clearance_m = self.person_clearance_m(state.cart_pos_world, CART_BODY_RADIUS_M)

        self.metrics.min_robot_person_clearance_m = min(
            self.metrics.min_robot_person_clearance_m,
            robot_person_clearance_m,
        )
        self.metrics.min_cart_person_clearance_m = min(
            self.metrics.min_cart_person_clearance_m,
            cart_person_clearance_m,
        )
        self.metrics.max_contact_demand_m = max(self.metrics.max_contact_demand_m, state.contact_demand_m)
        self.metrics.min_ring_clearance_m = min(self.metrics.min_ring_clearance_m, state.min_clearance_m)
        self.metrics.max_relative_xy_m = max(self.metrics.max_relative_xy_m, relative_xy_m)
        self.metrics.max_relative_yaw_deg = max(self.metrics.max_relative_yaw_deg, relative_yaw_deg)
        self.metrics.max_robot_route_offset_m = max(
            self.metrics.max_robot_route_offset_m,
            abs(state.robot_pos_world[0] - self.route_center_x_m),
        )
        self.metrics.max_cart_route_offset_m = max(
            self.metrics.max_cart_route_offset_m,
            abs(state.cart_pos_world[0] - self.route_center_x_m),
        )
        if state.contact_active:
            self.metrics.contact_active_steps += 1
        if self.metrics.route_avoid_peak_time_s is None and self.phase in {"avoid_right", "hold_clearance"}:
            self.metrics.route_avoid_peak_time_s = state.time_s
        if (
            self.metrics.route_return_time_s is None
            and state.time_s > 8.0
            and abs(state.robot_pos_world[0]) <= 0.06
            and abs(state.cart_pos_world[0]) <= 0.08
        ):
            self.metrics.route_return_time_s = state.time_s

        self.history_rows.append(
            {
                "time_s": state.time_s,
                "phase": self.phase,
                "person_x_m": float(self.person.pos_world[0]),
                "person_y_m": float(self.person.pos_world[1]),
                "robot_x_m": float(state.robot_pos_world[0]),
                "robot_y_m": float(state.robot_pos_world[1]),
                "robot_yaw_deg": float(math.degrees(state.robot_yaw_rad)),
                "robot_speed_mps": float(np.linalg.norm(state.robot_velocity_world)),
                "cart_x_m": float(state.cart_pos_world[0]),
                "cart_y_m": float(state.cart_pos_world[1]),
                "cart_yaw_deg": float(math.degrees(state.cart_yaw_rad)),
                "cart_speed_mps": float(np.linalg.norm(state.cart_velocity_world)),
                "relative_xy_mm": 1000.0 * relative_xy_m,
                "relative_yaw_deg": relative_yaw_deg,
                "ring_clearance_mm": 1000.0 * state.min_clearance_m,
                "contact_demand_mm": 1000.0 * state.contact_demand_m,
                "height_shift_mm": 1000.0 * state.height_shift_m,
                "robot_person_clearance_mm": 1000.0 * robot_person_clearance_m,
                "cart_person_clearance_mm": 1000.0 * cart_person_clearance_m,
                "input_force_x_n": float(state.input_force_world_n[0]),
                "input_force_y_n": float(state.input_force_world_n[1]),
                "input_force_n": float(np.linalg.norm(state.input_force_world_n)),
                "magnetic_force_x_n": float(state.magnetic_force_world_n[0]),
                "magnetic_force_y_n": float(state.magnetic_force_world_n[1]),
                "magnetic_force_n": float(np.linalg.norm(state.magnetic_force_world_n)),
                "contact_force_x_n": float(state.contact_force_world_n[0]),
                "contact_force_y_n": float(state.contact_force_world_n[1]),
                "contact_force_n": float(np.linalg.norm(state.contact_force_world_n)),
            }
        )
        self.completed = state.time_s >= self.duration_s

    def build_summary(self):
        state = self.core.state
        return {
            "scenario": "corridor_pedestrian_avoidance",
            "fixed_height": not self.core.height_control_enabled,
            "fixed_height_shift_mm": 1000.0 * self.core.fixed_height_shift_m,
            "duration_s": state.time_s,
            "corridor_width_m": CORRIDOR_WIDTH_M,
            "robot_speed_command_mps": ROBOT_SPEED_MPS,
            "pedestrian_speed_mps": self.pedestrian_speed_mps,
            "person_start_x_m": self.person_start_x_m,
            "person_start_y_m": self.person_start_y_m,
            "target_offset_max_m": self.target_offset_max_m,
            "min_robot_person_clearance_mm": 1000.0 * self.metrics.min_robot_person_clearance_m,
            "min_cart_person_clearance_mm": 1000.0 * self.metrics.min_cart_person_clearance_m,
            "worst_ring_clearance_mm": 1000.0 * self.metrics.min_ring_clearance_m,
            "max_contact_demand_mm": 1000.0 * self.metrics.max_contact_demand_m,
            "max_relative_xy_mm": 1000.0 * self.metrics.max_relative_xy_m,
            "max_relative_yaw_deg": self.metrics.max_relative_yaw_deg,
            "max_robot_route_offset_mm": 1000.0 * self.metrics.max_robot_route_offset_m,
            "max_cart_route_offset_mm": 1000.0 * self.metrics.max_cart_route_offset_m,
            "route_return_time_s": self.metrics.route_return_time_s,
            "contact_active_steps": self.metrics.contact_active_steps,
            "final_robot_x_mm": 1000.0 * state.robot_pos_world[0],
            "final_cart_x_mm": 1000.0 * state.cart_pos_world[0],
            "final_relative_xy_mm": 1000.0 * np.linalg.norm(state.cart_pos_world - state.robot_pos_world),
            "final_relative_yaw_deg": abs(math.degrees(angle_wrap(state.cart_yaw_rad - state.robot_yaw_rad))),
            "no_attraction_pass": int(self.metrics.max_contact_demand_m <= FIXED_HEIGHT_EPS_M),
            "ring_clearance_pass": int(self.metrics.min_ring_clearance_m > 0.0),
            "pedestrian_clearance_pass": int(
                min(self.metrics.min_robot_person_clearance_m, self.metrics.min_cart_person_clearance_m) >= 0.10
            ),
            "route_return_pass": int(abs(state.robot_pos_world[0]) <= 0.06 and abs(state.cart_pos_world[0]) <= 0.08),
        }


class InteractiveCouplerApp:
    def __init__(
        self,
        model: hifi.ArrayModel,
        policy: hifi.HeightPolicy,
        result_json: Path,
        height_control_enabled: bool = True,
        fixed_height_shift_m: float = 0.0,
        scripted_scenario: CorridorPedestrianAvoidanceScenario | None = None,
        auto_close_seconds: float = 0.0,
    ):
        self.core = InteractiveCouplerCore(
            model,
            policy,
            height_control_enabled=height_control_enabled,
            fixed_height_shift_m=fixed_height_shift_m,
        )
        self.scripted_scenario = scripted_scenario
        if self.scripted_scenario is not None:
            self.scripted_scenario.core = self.core
            self.scripted_scenario.reset()
        self.auto_close_seconds = float(auto_close_seconds)
        self.root = tk.Tk()
        self.root.title(f"Magnetic Coupler Corridor Simulator - {result_json.name}")
        self.canvas = tk.Canvas(self.root, width=CANVAS_W, height=CANVAS_H, bg="#f7f7f5", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.key_state = set()
        self.root.bind("<KeyPress>", self.on_key_press)
        self.root.bind("<KeyRelease>", self.on_key_release)
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self.last_wall_time = time.perf_counter()
        self.instructions = (
            "Robot dir: Arrow keys | Left hand: WASD | Right hand: IJKL | Space: clear hands | R: reset"
        )

    def on_key_press(self, event):
        self.key_state.add(event.keysym.lower())
        if event.keysym.lower() == "space":
            self.core.keys.left = np.zeros(2, dtype=float)
            self.core.keys.right = np.zeros(2, dtype=float)
        if event.keysym.lower() == "r":
            if self.scripted_scenario is not None:
                self.scripted_scenario.reset()
            else:
                self.core.reset()

    def on_key_release(self, event):
        self.key_state.discard(event.keysym.lower())

    def update_key_vectors(self):
        current_heading = [
            math.cos(self.core.state.robot_yaw_rad),
            math.sin(self.core.state.robot_yaw_rad),
        ]
        self.core.keys.robot = self.vector_from_keys(["left", "right"], ["down", "up"], default=current_heading)
        self.core.keys.left = self.vector_from_keys(["a", "d"], ["s", "w"], default=[0.0, 0.0], zero_allowed=True)
        self.core.keys.right = self.vector_from_keys(["j", "l"], ["k", "i"], default=[0.0, 0.0], zero_allowed=True)

    def vector_from_keys(self, x_keys, y_keys, default, zero_allowed=False):
        vector = np.zeros(2, dtype=float)
        if x_keys[0] in self.key_state:
            vector[0] -= 1.0
        if x_keys[1] in self.key_state:
            vector[0] += 1.0
        if y_keys[0] in self.key_state:
            vector[1] -= 1.0
        if y_keys[1] in self.key_state:
            vector[1] += 1.0
        if float(np.linalg.norm(vector)) <= 1.0e-12:
            return np.zeros(2, dtype=float) if zero_allowed else np.array(default, dtype=float)
        return vector

    def world_to_canvas(self, points_world, camera_center_world):
        shifted = np.asarray(points_world, dtype=float) - camera_center_world
        x = 0.5 * CANVAS_W + PIXELS_PER_METER * shifted[..., 0]
        y = 0.78 * CANVAS_H - PIXELS_PER_METER * shifted[..., 1]
        return np.stack((x, y), axis=-1)

    def rectangle_corners(self, length_m, width_m):
        lx = 0.5 * width_m
        ly = 0.5 * length_m
        return np.array(
            [
                [-lx, -ly],
                [lx, -ly],
                [lx, ly],
                [-lx, ly],
            ],
            dtype=float,
        )

    def draw_arrow(self, origin_world, vector_world, camera_center_world, color, scale_px):
        origin_canvas = self.world_to_canvas(origin_world, camera_center_world)
        end_canvas = origin_canvas + np.array([scale_px * vector_world[0], -scale_px * vector_world[1]], dtype=float)
        self.canvas.create_line(
            origin_canvas[0],
            origin_canvas[1],
            end_canvas[0],
            end_canvas[1],
            fill=color,
            width=4,
            arrow=tk.LAST,
        )

    def draw_polygon(self, points_world, camera_center_world, outline, fill="", width=2):
        points_canvas = self.world_to_canvas(points_world, camera_center_world)
        flat = [coord for point in points_canvas for coord in point]
        self.canvas.create_polygon(*flat, outline=outline, fill=fill, width=width, smooth=False)

    def draw_scene(self):
        self.canvas.delete("all")
        state = self.core.state
        camera_center = np.array([0.0, state.robot_pos_world[1] + 0.35], dtype=float)

        left_wall = -0.5 * CORRIDOR_WIDTH_M
        right_wall = 0.5 * CORRIDOR_WIDTH_M
        wall_y = np.array([state.robot_pos_world[1] - 1.2, state.robot_pos_world[1] + 1.8], dtype=float)
        for wall_x in [left_wall, right_wall]:
            wall_points = np.array([[wall_x, wall_y[0]], [wall_x, wall_y[1]]], dtype=float)
            canvas_points = self.world_to_canvas(wall_points, camera_center)
            self.canvas.create_line(
                canvas_points[0, 0],
                canvas_points[0, 1],
                canvas_points[1, 0],
                canvas_points[1, 1],
                fill="#6b7280",
                width=7,
            )

        route_points = np.array([[0.0, state.robot_pos_world[1] - 1.0], [0.0, state.robot_pos_world[1] + 1.8]], dtype=float)
        route_canvas = self.world_to_canvas(route_points, camera_center)
        self.canvas.create_line(
            route_canvas[0, 0],
            route_canvas[0, 1],
            route_canvas[1, 0],
            route_canvas[1, 1],
            fill="#cbd5e1",
            width=2,
            dash=(8, 8),
        )

        robot_body = transform_points(
            self.rectangle_corners(hifi.ROBOT_LENGTH_M, hifi.ROBOT_WIDTH_M),
            state.robot_pos_world,
            state.robot_yaw_rad,
        )
        cart_body = transform_points(
            self.rectangle_corners(hifi.CART_LENGTH_M, hifi.CART_WIDTH_M),
            state.cart_pos_world,
            state.cart_yaw_rad,
        )
        inner_ring = transform_points(self.core.model.geometry.inner_points, state.robot_pos_world, state.robot_yaw_rad)
        outer_ring = transform_points(
            self.core.model.geometry.outer_points_local,
            state.cart_pos_world,
            state.cart_yaw_rad,
        )
        self.draw_polygon(cart_body, camera_center, outline="#4b5563", fill="#e5e7eb", width=2)
        self.draw_polygon(robot_body, camera_center, outline="#0f766e", fill="#ccfbf1", width=2)
        ring_fill = "#fee2e2" if state.contact_active else ""
        self.draw_polygon(outer_ring, camera_center, outline="#1d4ed8", fill=ring_fill, width=3)
        self.draw_polygon(inner_ring, camera_center, outline="#111827", fill="", width=3)

        if self.scripted_scenario is not None:
            person_center_canvas = self.world_to_canvas(self.scripted_scenario.person.pos_world, camera_center)
            radius_px = PIXELS_PER_METER * self.scripted_scenario.person.radius_m
            self.canvas.create_oval(
                person_center_canvas[0] - radius_px,
                person_center_canvas[1] - radius_px,
                person_center_canvas[0] + radius_px,
                person_center_canvas[1] + radius_px,
                fill="#fca5a5",
                outline="#991b1b",
                width=2,
            )
            self.draw_arrow(
                self.scripted_scenario.person.pos_world,
                normalized_or_default(self.scripted_scenario.person.vel_world, [0.0, -1.0]),
                camera_center,
                "#991b1b",
                55.0,
            )

        left_handle_world = state.cart_pos_world + rotmat(state.cart_yaw_rad) @ np.array([-0.14, 0.22], dtype=float)
        right_handle_world = state.cart_pos_world + rotmat(state.cart_yaw_rad) @ np.array([0.14, 0.22], dtype=float)
        robot_dir = normalized_or_default(self.core.keys.robot, [0.0, 1.0])
        left_dir = normalized_or_default(self.core.keys.left, [0.0, 0.0]) if np.linalg.norm(self.core.keys.left) > 0 else np.zeros(2, dtype=float)
        right_dir = normalized_or_default(self.core.keys.right, [0.0, 0.0]) if np.linalg.norm(self.core.keys.right) > 0 else np.zeros(2, dtype=float)
        self.draw_arrow(state.robot_pos_world, robot_dir, camera_center, "#0f766e", 85.0)
        self.draw_arrow(left_handle_world, left_dir, camera_center, "#dc2626", 60.0)
        self.draw_arrow(right_handle_world, right_dir, camera_center, "#7c3aed", 60.0)

        hud_lines = [
            self.instructions,
            f"time={state.time_s:5.2f} s   robot_speed={state.robot_speed_mps:4.2f} m/s   step={self.core.last_step_ms:5.2f} ms",
            f"clearance={1000.0 * state.min_clearance_m:6.3f} mm   raw_gap={1000.0 * state.raw_gap_m:6.3f} mm   contact_demand={1000.0 * state.contact_demand_m:6.3f} mm",
            f"rel_xy={1000.0 * np.linalg.norm(state.cart_pos_world - state.robot_pos_world):6.2f} mm   rel_yaw={math.degrees(angle_wrap(state.cart_yaw_rad - state.robot_yaw_rad)):6.2f} deg   height_shift={1000.0 * state.height_shift_m:6.2f} mm",
            f"|F_input|={np.linalg.norm(state.input_force_world_n):5.1f} N   torque_input={state.input_torque_nm:5.2f} N m   |F_mag|={np.linalg.norm(state.magnetic_force_world_n):5.1f} N   |F_contact|={np.linalg.norm(state.contact_force_world_n):5.1f} N",
            f"worst_clearance_seen={1000.0 * self.core.min_clearance_seen_m:6.3f} mm   max_contact_demand_seen={1000.0 * self.core.max_contact_demand_m:6.3f} mm",
        ]
        if self.scripted_scenario is not None:
            summary = self.scripted_scenario.build_summary()
            hud_lines.extend(
                [
                    f"scenario={self.scripted_scenario.phase}   fixed_height={int(not self.core.height_control_enabled)}   person_y={self.scripted_scenario.person.pos_world[1]:5.2f} m",
                    f"person_clearance(robot/cart)={summary['min_robot_person_clearance_mm']:6.1f}/{summary['min_cart_person_clearance_mm']:6.1f} mm   route_x(robot/cart)={1000.0 * state.robot_pos_world[0]:6.1f}/{1000.0 * state.cart_pos_world[0]:6.1f} mm",
                ]
            )
        for index, line in enumerate(hud_lines):
            self.canvas.create_text(
                18,
                18 + 24 * index,
                anchor="nw",
                text=line,
                fill="#111827",
                font=("Consolas", 12, "normal"),
            )

    def tick(self):
        now = time.perf_counter()
        dt_s = min(max(now - self.last_wall_time, 0.010), 0.035)
        self.last_wall_time = now
        if self.scripted_scenario is not None:
            self.scripted_scenario.step(dt_s)
        else:
            self.update_key_vectors()
            self.core.step(dt_s)
        self.draw_scene()
        if self.auto_close_seconds > 0.0 and self.core.state.time_s >= self.auto_close_seconds:
            self.root.destroy()
            return
        if self.root.winfo_exists():
            self.root.after(int(DT_S * 1000.0), self.tick)

    def run(self):
        self.tick()
        self.root.mainloop()


def run_headless_smoke(model: hifi.ArrayModel, policy: hifi.HeightPolicy, seconds: float):
    core = InteractiveCouplerCore(model, policy)
    samples = []
    while core.state.time_s < seconds:
        core.scripted_inputs(core.state.time_s)
        core.step(DT_S)
        samples.append(core.last_step_ms)
    summary = {
        "duration_s": seconds,
        "mean_step_ms": float(np.mean(samples)) if samples else 0.0,
        "p95_step_ms": float(np.percentile(samples, 95)) if samples else 0.0,
        "worst_clearance_mm": 1000.0 * core.min_clearance_seen_m,
        "max_contact_demand_mm": 1000.0 * core.max_contact_demand_m,
        "final_height_shift_mm": 1000.0 * core.state.height_shift_m,
        "final_relative_xy_mm": 1000.0 * np.linalg.norm(core.state.cart_pos_world - core.state.robot_pos_world),
        "final_relative_yaw_deg": math.degrees(angle_wrap(core.state.cart_yaw_rad - core.state.robot_yaw_rad)),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def write_history_csv(rows, csv_path: Path):
    if not rows:
        return
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def run_corridor_pedestrian_avoidance(
    model: hifi.ArrayModel,
    policy: hifi.HeightPolicy,
    duration_s: float,
    height_control_enabled: bool = True,
    fixed_height_shift_m: float = 0.0,
    summary_json: Path | None = None,
    history_csv: Path | None = None,
    scenario_kwargs: dict | None = None,
):
    core = InteractiveCouplerCore(
        model,
        policy,
        height_control_enabled=height_control_enabled,
        fixed_height_shift_m=fixed_height_shift_m,
    )
    scenario = CorridorPedestrianAvoidanceScenario(core, duration_s=duration_s, **(scenario_kwargs or {}))
    while not scenario.completed:
        scenario.step(DT_S)
    summary = scenario.build_summary()
    summary["all_pass"] = int(
        summary["no_attraction_pass"]
        and summary["ring_clearance_pass"]
        and summary["pedestrian_clearance_pass"]
        and summary["route_return_pass"]
    )
    if summary_json is not None:
        summary_json.parent.mkdir(parents=True, exist_ok=True)
        summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    if history_csv is not None:
        write_history_csv(scenario.history_rows, history_csv)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return summary, scenario.history_rows


def run_stability_suite(model: hifi.ArrayModel, policy: hifi.HeightPolicy):
    """Runs repeatable robot-leading stability regressions for the GUI dynamics."""

    def straight_no_input():
        core = InteractiveCouplerCore(model, policy)
        max_rel_yaw = 0.0
        max_rel_xy = 0.0
        while core.state.time_s < 60.0:
            core.keys = KeyboardVectors(robot=np.array([0.0, 1.0]), left=np.zeros(2), right=np.zeros(2))
            core.step(DT_S)
            rel_yaw_deg = abs(math.degrees(angle_wrap(core.state.cart_yaw_rad - core.state.robot_yaw_rad)))
            rel_xy_mm = 1000.0 * np.linalg.norm(core.state.cart_pos_world - core.state.robot_pos_world)
            max_rel_yaw = max(max_rel_yaw, rel_yaw_deg)
            max_rel_xy = max(max_rel_xy, rel_xy_mm)
        return {
            "max_rel_yaw_deg": max_rel_yaw,
            "max_rel_xy_mm": max_rel_xy,
            "final_rel_yaw_deg": abs(math.degrees(angle_wrap(core.state.cart_yaw_rad - core.state.robot_yaw_rad))),
            "final_rel_xy_mm": 1000.0 * np.linalg.norm(core.state.cart_pos_world - core.state.robot_pos_world),
            "min_clearance_mm": 1000.0 * core.min_clearance_seen_m,
            "max_contact_demand_mm": 1000.0 * core.max_contact_demand_m,
            "pass": max_rel_yaw <= 8.0 and max_rel_xy <= 35.0 and core.max_contact_demand_m <= 5.0e-5,
        }

    def yaw_recovery():
        core = InteractiveCouplerCore(model, policy)
        core.state.cart_yaw_rad = core.state.robot_yaw_rad + math.radians(85.0)
        min_rel_yaw_deg = 1.0e9
        while core.state.time_s < 35.0:
            core.keys = KeyboardVectors(robot=np.array([0.0, 1.0]), left=np.zeros(2), right=np.zeros(2))
            core.step(DT_S)
            rel_yaw_deg = abs(math.degrees(angle_wrap(core.state.cart_yaw_rad - core.state.robot_yaw_rad)))
            min_rel_yaw_deg = min(min_rel_yaw_deg, rel_yaw_deg)
        final_rel_yaw_deg = abs(math.degrees(angle_wrap(core.state.cart_yaw_rad - core.state.robot_yaw_rad)))
        return {
            "best_rel_yaw_deg": min_rel_yaw_deg,
            "final_rel_yaw_deg": final_rel_yaw_deg,
            "final_rel_xy_mm": 1000.0 * np.linalg.norm(core.state.cart_pos_world - core.state.robot_pos_world),
            "min_clearance_mm": 1000.0 * core.min_clearance_seen_m,
            "max_contact_demand_mm": 1000.0 * core.max_contact_demand_m,
            "pass": final_rel_yaw_deg <= 12.0 and core.max_contact_demand_m <= 5.0e-5,
        }

    def push_release():
        core = InteractiveCouplerCore(model, policy)
        while core.state.time_s < 22.0:
            if core.state.time_s < 4.0:
                core.keys = KeyboardVectors(
                    robot=np.array([0.0, 1.0]),
                    left=np.array([-0.8, 0.9]),
                    right=np.array([0.8, 0.9]),
                )
            elif core.state.time_s < 8.0:
                core.keys = KeyboardVectors(
                    robot=np.array([0.12, 0.99]),
                    left=np.array([0.9, 0.2]),
                    right=np.array([0.9, 0.2]),
                )
            else:
                core.keys = KeyboardVectors(robot=np.array([0.0, 1.0]), left=np.zeros(2), right=np.zeros(2))
            core.step(DT_S)
        final_rel_yaw_deg = abs(math.degrees(angle_wrap(core.state.cart_yaw_rad - core.state.robot_yaw_rad)))
        final_rel_xy_mm = 1000.0 * np.linalg.norm(core.state.cart_pos_world - core.state.robot_pos_world)
        return {
            "final_rel_yaw_deg": final_rel_yaw_deg,
            "final_rel_xy_mm": final_rel_xy_mm,
            "min_clearance_mm": 1000.0 * core.min_clearance_seen_m,
            "max_contact_demand_mm": 1000.0 * core.max_contact_demand_m,
            "pass": final_rel_yaw_deg <= 16.0 and final_rel_xy_mm <= 45.0 and core.max_contact_demand_m <= 5.0e-5,
        }

    suite = {
        "robot_platform": hifi.ROBOT_PLATFORM_NAME,
        "robot_mass_kg": hifi.ROBOT_MASS_KG,
        "robot_length_m": hifi.ROBOT_LENGTH_M,
        "robot_width_m": hifi.ROBOT_WIDTH_M,
        "cart_mass_kg": model.design.cart_mass_kg,
        "tests": {
            "straight_no_input": straight_no_input(),
            "yaw_recovery_from_85deg": yaw_recovery(),
            "push_release": push_release(),
        },
    }
    suite["all_pass"] = all(test["pass"] for test in suite["tests"].values())
    print(json.dumps(suite, indent=2, ensure_ascii=False))


def parse_args():
    parser = argparse.ArgumentParser(description="Interactive corridor simulator for the optimized magnetic coupler.")
    parser.add_argument("--result-json", type=Path, default=resolve_default_result_json())
    parser.add_argument("--samples", type=int, default=128)
    parser.add_argument("--grid", choices=["search", "validation"], default="search")
    parser.add_argument("--headless-smoke-seconds", type=float, default=0.0)
    parser.add_argument("--stability-suite", action="store_true")
    parser.add_argument(
        "--scenario",
        choices=["manual", "corridor_pedestrian_avoidance"],
        default="manual",
        help="GUI scenario preset.",
    )
    parser.add_argument(
        "--fixed-height",
        action="store_true",
        help="Disable the height controller and keep overlap height constant.",
    )
    parser.add_argument(
        "--fixed-height-shift-mm",
        type=float,
        default=0.0,
        help="Constant overlap reduction when --fixed-height is used.",
    )
    parser.add_argument(
        "--scenario-duration-s",
        type=float,
        default=14.0,
        help="Duration for scripted corridor scenarios.",
    )
    parser.add_argument(
        "--corridor-headless-report-json",
        type=Path,
        default=None,
        help="Run the scripted corridor pedestrian avoidance scenario headlessly and save JSON summary.",
    )
    parser.add_argument(
        "--corridor-headless-history-csv",
        type=Path,
        default=None,
        help="Optional CSV path for per-step corridor scenario history.",
    )
    parser.add_argument(
        "--auto-close-seconds",
        type=float,
        default=0.0,
        help="Automatically close the GUI after this many simulated seconds.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    dipole_grid = hifi.SEARCH_DIPOLE_GRID if args.grid == "search" else hifi.VALIDATION_DIPOLE_GRID
    _payload, _design, policy, model = load_selected_model(args.result_json, args.samples, dipole_grid)
    fixed_height_shift_m = 0.001 * args.fixed_height_shift_mm
    if args.headless_smoke_seconds > 0.0:
        run_headless_smoke(model, policy, args.headless_smoke_seconds)
        return
    if args.stability_suite:
        run_stability_suite(model, policy)
        return
    if args.corridor_headless_report_json is not None or args.corridor_headless_history_csv is not None:
        run_corridor_pedestrian_avoidance(
            model,
            policy,
            duration_s=args.scenario_duration_s,
            height_control_enabled=not args.fixed_height,
            fixed_height_shift_m=fixed_height_shift_m if args.fixed_height else 0.0,
            summary_json=args.corridor_headless_report_json,
            history_csv=args.corridor_headless_history_csv,
        )
        return
    scripted_scenario = None
    if args.scenario == "corridor_pedestrian_avoidance":
        scripted_scenario = CorridorPedestrianAvoidanceScenario(
            InteractiveCouplerCore(
                model,
                policy,
                height_control_enabled=not args.fixed_height,
                fixed_height_shift_m=fixed_height_shift_m if args.fixed_height else 0.0,
            ),
            duration_s=args.scenario_duration_s,
        )
    app = InteractiveCouplerApp(
        model,
        policy,
        args.result_json,
        height_control_enabled=not args.fixed_height,
        fixed_height_shift_m=fixed_height_shift_m if args.fixed_height else 0.0,
        scripted_scenario=scripted_scenario,
        auto_close_seconds=args.auto_close_seconds,
    )
    app.run()


if __name__ == "__main__":
    main()
