from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Dict, Optional


@dataclass
class UpperCostConfig:
    w_wait: float = 1.0
    w_travel_time: float = 1.0
    w_terminal_soc_min: float = 30.0
    w_day_end_soc_min: float = 1.0e5
    w_soc_day_max: float = 1.0e4
    w_soc_day_track: float = 0.0
    w_speed_smooth: float = 30.0
    w_dv_limit: float = 2.0
    w_speed_limit: float = 50.0
    w_drive_window: float = 1.0e5
    w_current_sq: float = 0.01
    w_pack_energy: float = 0.0
    w_joule_loss: float = 0.0
    w_aero_energy: float = 0.0
    w_mech_energy: float = 0.0
    w_speed_quartic: float = 0.0
    w_solar_headroom: float = 0.0
    w_progress_lag: float = 0.0
    w_progress_terminal_lag: float = 0.0
    w_kinetic_pos: float = 0.0
    w_pack_power_slew: float = 0.0
    w_temp: float = 5.0
    w_soc_terminal: float = 0.0
    w_soc_floor_barrier: float = 0.0
    w_uncertainty_reserve: float = 0.0
    speed_quartic_scale_kmh: float = 80.0
    progress_lag_deadband_km: float = 0.0
    soc_solar_headroom_max: float = 0.92
    solar_headroom_power_scale_w: float = 1000.0
    soc_floor_barrier_eps: float = 0.01
    reserve_soc_per_hour: float = 0.0
    reserve_soc_max_extra: float = 0.0
    constraint_penalty: float = 1.0e4

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


def _cfg_value(cfg: Optional[dict], key: str, default):
    if isinstance(cfg, dict) and key in cfg:
        return cfg[key]
    return default


def load_upper_cost_config(
    mpc_cfg: Optional[dict],
    *,
    legacy: Optional[dict] = None,
    default_drive_window: float = 1.0e5,
) -> UpperCostConfig:
    legacy = legacy or {}
    nested = {}
    if isinstance(mpc_cfg, dict):
        nested = mpc_cfg.get("upper_cost", {}) or {}

    def pick(name: str, default):
        if name in nested:
            return nested[name]
        if name in legacy:
            return legacy[name]
        return default

    return UpperCostConfig(
        w_wait=float(pick("w_wait", 1.0)),
        w_travel_time=float(pick("w_travel_time", 1.0)),
        w_terminal_soc_min=float(pick("w_terminal_soc_min", 30.0)),
        w_day_end_soc_min=float(pick("w_day_end_soc_min", default_drive_window)),
        w_soc_day_max=float(pick("w_soc_day_max", 1.0e4)),
        w_soc_day_track=float(pick("w_soc_day_track", 0.0)),
        w_speed_smooth=float(pick("w_speed_smooth", _cfg_value(legacy, "w_dv", 30.0))),
        w_dv_limit=float(pick("w_dv_limit", 2.0)),
        w_speed_limit=float(pick("w_speed_limit", 50.0)),
        w_drive_window=float(pick("w_drive_window", default_drive_window)),
        w_current_sq=float(pick("w_current_sq", _cfg_value(legacy, "w_current", 0.01))),
        w_pack_energy=float(pick("w_pack_energy", 0.0)),
        w_joule_loss=float(pick("w_joule_loss", 0.0)),
        w_aero_energy=float(pick("w_aero_energy", 0.0)),
        w_mech_energy=float(pick("w_mech_energy", 0.0)),
        w_speed_quartic=float(pick("w_speed_quartic", 0.0)),
        w_solar_headroom=float(pick("w_solar_headroom", 0.0)),
        w_progress_lag=float(pick("w_progress_lag", 0.0)),
        w_progress_terminal_lag=float(pick("w_progress_terminal_lag", 0.0)),
        w_kinetic_pos=float(pick("w_kinetic_pos", 0.0)),
        w_pack_power_slew=float(pick("w_pack_power_slew", 0.0)),
        w_temp=float(pick("w_temp", _cfg_value(legacy, "w_T", 5.0))),
        w_soc_terminal=float(pick("w_soc_terminal", 0.0)),
        w_soc_floor_barrier=float(pick("w_soc_floor_barrier", 0.0)),
        w_uncertainty_reserve=float(pick("w_uncertainty_reserve", 0.0)),
        speed_quartic_scale_kmh=float(pick("speed_quartic_scale_kmh", 80.0)),
        progress_lag_deadband_km=float(pick("progress_lag_deadband_km", 0.0)),
        soc_solar_headroom_max=float(pick("soc_solar_headroom_max", 0.92)),
        solar_headroom_power_scale_w=float(pick("solar_headroom_power_scale_w", 1000.0)),
        soc_floor_barrier_eps=float(pick("soc_floor_barrier_eps", 0.01)),
        reserve_soc_per_hour=float(pick("reserve_soc_per_hour", 0.0)),
        reserve_soc_max_extra=float(pick("reserve_soc_max_extra", 0.0)),
        constraint_penalty=float(pick("constraint_penalty", 1.0e4)),
    )


def quad_penalty(x: float, cap: float = 1.0e3) -> float:
    if x <= 0.0:
        return 0.0
    if x > cap:
        x = cap
    return x * x


def upper_stage_cost(
    cfg: UpperCostConfig,
    *,
    dt_wait: float,
    dt_travel: float,
    v_kmh: float,
    v_prev_kmh: float,
    vmax_local_kmh: float,
    drive_limits: Optional[tuple],
    dv_limit_kmhps: float,
    I_a: float,
    V_v: float,
    P_pv_w: float,
    P_pack_w: float,
    P_pack_prev_w: Optional[float],
    P_mech_wheel_w: float,
    losses_int_w: float,
    losses_line_w: float,
    F_aero_n: float,
    kinetic_step_wh: float,
    z_next: float,
    Tb_next_c: float,
    term_soc_min: float,
    soc_min: float,
    soc_max: float,
    temp_min_c: float,
    temp_max_c: float,
    day_end_soc_min: Optional[float],
    day_end_crossing: bool,
    soc_day_end_max: float,
    soc_day_track_target: Optional[float],
    soc_day_track_tol: float,
    I_max: float,
    I_chg_min: float,
    V_min: float,
    V_max: float,
    time_ahead_h: float,
    progress_lag_km: float = 0.0,
) -> float:
    J = 0.0
    if dt_wait > 0.0:
        J += cfg.w_wait * dt_wait
    J += cfg.w_travel_time * dt_travel
    J += cfg.w_terminal_soc_min * quad_penalty(term_soc_min - z_next)

    if soc_day_track_target is not None:
        J += cfg.w_soc_day_track * quad_penalty(z_next - (soc_day_track_target + soc_day_track_tol))
        J += cfg.w_soc_day_track * quad_penalty((soc_day_track_target - soc_day_track_tol) - z_next)

    dv = (v_kmh - v_prev_kmh) / max(dt_travel, 1.0e-3)
    J += cfg.w_speed_smooth * (v_kmh - v_prev_kmh) ** 2
    if dv_limit_kmhps > 0.0:
        J += cfg.w_dv_limit * quad_penalty(abs(dv) - dv_limit_kmhps)

    if drive_limits is not None:
        vmin_kmh, vmax_kmh = drive_limits
        J += cfg.w_drive_window * quad_penalty(vmin_kmh - v_kmh)
        J += cfg.w_drive_window * quad_penalty(v_kmh - vmax_kmh)

    J += cfg.w_speed_limit * quad_penalty(v_kmh - vmax_local_kmh)
    J += cfg.w_current_sq * (I_a ** 2) * dt_travel

    e_pack_wh = max(0.0, P_pack_w) * dt_travel / 3600.0
    e_loss_wh = max(0.0, losses_int_w + losses_line_w) * dt_travel / 3600.0
    e_aero_wh = max(0.0, F_aero_n) * (v_kmh / 3.6) * dt_travel / 3600.0
    e_mech_wh = max(0.0, P_mech_wheel_w) * dt_travel / 3600.0

    J += cfg.w_pack_energy * e_pack_wh
    J += cfg.w_joule_loss * e_loss_wh
    J += cfg.w_aero_energy * e_aero_wh
    J += cfg.w_mech_energy * e_mech_wh
    J += cfg.w_kinetic_pos * max(0.0, kinetic_step_wh)

    if cfg.w_speed_quartic > 0.0:
        speed_scale = max(1.0, cfg.speed_quartic_scale_kmh)
        J += cfg.w_speed_quartic * ((max(0.0, v_kmh) / speed_scale) ** 4) * dt_travel

    if cfg.w_pack_power_slew > 0.0 and P_pack_prev_w is not None:
        d_pack_kw = (float(P_pack_w) - float(P_pack_prev_w)) / 1000.0
        J += cfg.w_pack_power_slew * (d_pack_kw ** 2) * (dt_travel / 3600.0)

    if cfg.w_progress_lag > 0.0:
        lag_err = max(0.0, float(progress_lag_km) - float(cfg.progress_lag_deadband_km))
        J += cfg.w_progress_lag * quad_penalty(lag_err)

    if cfg.w_solar_headroom > 0.0:
        solar_scale = max(1.0, cfg.solar_headroom_power_scale_w)
        pv_kw = max(0.0, P_pv_w) / solar_scale
        if pv_kw > 0.0:
            J += cfg.w_solar_headroom * pv_kw * quad_penalty(z_next - cfg.soc_solar_headroom_max) * (dt_travel / 3600.0)

    if cfg.w_soc_floor_barrier > 0.0:
        soc_gap = max(float(z_next) - float(soc_min), float(cfg.soc_floor_barrier_eps))
        J += cfg.w_soc_floor_barrier / soc_gap

    if cfg.w_uncertainty_reserve > 0.0 and cfg.reserve_soc_per_hour > 0.0:
        reserve_extra = min(
            max(0.0, float(cfg.reserve_soc_max_extra)),
            max(0.0, float(time_ahead_h)) * max(0.0, float(cfg.reserve_soc_per_hour)),
        )
        reserve_soc = min(float(soc_max), float(soc_min) + reserve_extra)
        J += cfg.w_uncertainty_reserve * quad_penalty(reserve_soc - z_next)

    if day_end_crossing and day_end_soc_min is not None:
        J += cfg.w_day_end_soc_min * quad_penalty(day_end_soc_min - z_next)
        if soc_day_end_max > 0.0:
            J += cfg.w_soc_day_max * quad_penalty(z_next - soc_day_end_max)

    c = cfg.constraint_penalty
    J += c * quad_penalty(I_a - I_max)
    J += c * quad_penalty(I_chg_min - I_a)
    J += c * quad_penalty(V_min - V_v)
    J += c * quad_penalty(V_v - V_max)
    J += cfg.w_temp * quad_penalty(Tb_next_c - temp_max_c)
    J += cfg.w_temp * quad_penalty(temp_min_c - Tb_next_c)
    J += c * quad_penalty(soc_min - z_next)
    J += c * quad_penalty(z_next - soc_max)
    return J


def upper_terminal_cost(
    cfg: UpperCostConfig,
    *,
    z_terminal: float,
    term_soc_min: float,
    soc_finish_target: float,
    progress_terminal_lag_km: float = 0.0,
) -> float:
    J = cfg.constraint_penalty * quad_penalty(term_soc_min - z_terminal)
    if soc_finish_target > 0.0:
        J += cfg.w_soc_terminal * quad_penalty(z_terminal - soc_finish_target)
    if cfg.w_progress_terminal_lag > 0.0:
        lag_err = max(0.0, float(progress_terminal_lag_km) - float(cfg.progress_lag_deadband_km))
        J += cfg.w_progress_terminal_lag * quad_penalty(lag_err)
    return J


def active_upper_cost_terms(cfg: UpperCostConfig, threshold: float = 1.0e-6) -> Dict[str, float]:
    out = {}
    for key, value in cfg.to_dict().items():
        if key.startswith("w_") and abs(float(value)) > threshold:
            out[key] = float(value)
    return out
