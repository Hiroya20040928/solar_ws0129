#!/usr/bin/env python3
import argparse
import math
import time
import os
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yaml

from mpc_solarcar.model import SolarCarModel, Params
from mpc_solarcar.route_utils import interpolate_profile
from mpc_solarcar.schedule_utils import DriveSchedule


def load_yaml(path):
    if not path:
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_stops(path):
    cfg = load_yaml(path)
    return cfg.get('stops', []) if isinstance(cfg, dict) else []


def load_profile(path):
    if not path:
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def get_profile_val(df, s_km, field, default=0.0):
    if df is None or field not in df.columns:
        return float(default)
    val = float(interpolate_profile(df, s_km, field, default))
    if not math.isfinite(val):
        return float(default)
    return float(val)


def mpc_solve(model, data, z0, Tb0, s0_km, v0_kmh, v_max_kmh, term_soc_min,
              w_dv, w_dv_limit, dv_max_kmhps, w_T, w_speed_limit, w_current, speed_profile,
              soc_target, soc_band, w_soc_target, w_soc_band, schedule, soc_day_end_max, w_soc_day_max,
              soc_finish_target, soc_finish_tol, w_soc_progress, w_soc_terminal, race_km,
              soc_day_end_target, soc_day_end_tol, w_soc_day_track):
    p = model.p
    Np = len(data)
    if Np <= 0:
        return v0_kmh

    v0_ms = v0_kmh / 3.6
    x0 = np.array([v0_ms] * Np, dtype=float)
    lb = np.zeros(Np, dtype=float)
    ub = np.ones(Np, dtype=float) * (v_max_kmh / 3.6)

    dv_max_msps = dv_max_kmhps / 3.6

    def quad_penalty(x, cap=1.0e3):
        if x <= 0.0:
            return 0.0
        if x > cap:
            x = cap
        return x * x

    def cost(v):
        z = float(z0)
        Tb = float(Tb0)
        s_km = float(s0_km)
        v_prev = float(v0_ms)
        J = 0.0
        for k in range(Np):
            d = data[k]
            v_k = float(v[k])
            out = model.electrical_balance(
                v_k, d['slope_pct'], z, Tb, d['G_poa'], d['Tcell_C'], headwind_ms=d.get('headwind_ms', 0.0)
            )
            I = float(out['I'])
            V = float(out['V'])
            P_pack = float(out['P_pack'])
            loss_int = float(out['losses_int'])

            z_next = z - (P_pack * p.dt / 3600.0) / p.E_nom_Wh
            Tb_next = Tb + (p.dt / 1800.0) * (d['Tamb_C'] - Tb) + (loss_int * p.dt) / 50000.0
            s_km = s_km + v_k * (p.dt / 1000.0)

            J += -1.0 * v_k * p.dt
            J += 30.0 * quad_penalty(term_soc_min - z_next)
            if schedule is not None and soc_day_end_target > 0.0 and 't_utc' in d:
                win = schedule.current_drive_window(d['t_utc'])
                if win is not None:
                    t_start, t_end = win
                    if t_end > t_start:
                        prog = (d['t_utc'] - t_start).total_seconds() / (t_end - t_start).total_seconds()
                        prog = max(0.0, min(1.0, prog))
                        soc_line = z0 + (soc_day_end_target - z0) * prog
                        if z_next > (soc_line + soc_day_end_tol):
                            J += w_soc_day_track * quad_penalty(z_next - (soc_line + soc_day_end_tol))
                        if z_next < (soc_line - soc_day_end_tol):
                            J += w_soc_day_track * quad_penalty((soc_line - soc_day_end_tol) - z_next)
            if schedule is not None and soc_day_end_max > 0.0 and 't_utc' in d:
                t_next = d['t_utc'] + timedelta(seconds=p.dt)
                if schedule.is_drive_time(d['t_utc']) and not schedule.is_drive_time(t_next):
                    J += w_soc_day_max * quad_penalty(z_next - soc_day_end_max)

            dv = (v_k - v_prev) / max(p.dt, 1.0e-3)
            if dv_max_msps > 0.0:
                J += w_dv_limit * quad_penalty(abs(dv) - dv_max_msps)

            vmax_local = v_max_kmh
            if speed_profile is not None:
                vmax_local = get_profile_val(speed_profile, s_km, 'v_max_kmh', v_max_kmh)
            if vmax_local < v_max_kmh:
                J += w_speed_limit * quad_penalty(v_k * 3.6 - vmax_local)

            J += 1e4 * quad_penalty(I - p.I_max)
            J += 1e4 * quad_penalty(p.I_chg_min - I)
            J += 1e4 * quad_penalty(p.V_min - V)
            J += 1e4 * quad_penalty(V - p.V_max)
            J += w_T * quad_penalty(Tb_next - p.T_max)
            J += w_T * quad_penalty(p.T_min - Tb_next)
            J += 1e4 * quad_penalty(p.soc_min - z_next)
            J += 1e4 * quad_penalty(z_next - p.soc_max)

            z, Tb = z_next, Tb_next
            v_prev = v_k
        J += 1e4 * quad_penalty(term_soc_min - z)
        if soc_finish_target > 0.0:
            J += w_soc_terminal * quad_penalty(z - soc_finish_target)
        return J

    from scipy.optimize import minimize
    bounds = list(zip(lb, ub))
    res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=150))
    v0_kmh = float(res.x[0]) * 3.6
    return float(np.clip(v0_kmh, 0.0, v_max_kmh))


def soc_guard_speed(model, v_kmh, z, Tb, s_km, d0, route_profile, mode, soc_guard):
    mode = str(mode).lower()
    target = model.p.soc_min + soc_guard
    slope_pct = get_profile_val(route_profile, s_km, 'slope_pct', d0.get('slope_pct', 0.0))
    headwind_ms = d0.get('headwind_ms', 0.0)

    def z_next_for(v_kmh_local):
        out = model.electrical_balance(v_kmh_local / 3.6, slope_pct, z, Tb, d0['G_poa'], d0['Tcell_C'], headwind_ms=headwind_ms)
        P_pack = float(out['P_pack'])
        return z - (P_pack * model.p.dt / 3600.0) / model.p.E_nom_Wh

    if z <= target:
        if mode == 'stop':
            return 0.0
        if mode != 'pv_only':
            return v_kmh
        lo = 0.0
        hi = max(0.0, float(v_kmh))
        for _ in range(20):
            mid = 0.5 * (lo + hi)
            if z_next_for(mid) < z:
                hi = mid
            else:
                lo = mid
        return float(lo)

    if z_next_for(v_kmh) >= target:
        return v_kmh
    lo = 0.0
    hi = max(0.0, float(v_kmh))
    for _ in range(25):
        mid = 0.5 * (lo + hi)
        if z_next_for(mid) < target:
            hi = mid
        else:
            lo = mid
    return float(lo)


def soc_day_guard_speed(model, v_kmh, z, Tb, s_km, d0, route_profile, target_soc, tol):
    if target_soc <= 0.0:
        return v_kmh
    slope_pct = get_profile_val(route_profile, s_km, 'slope_pct', d0.get('slope_pct', 0.0))
    headwind_ms = d0.get('headwind_ms', 0.0)

    def z_next_for(v_kmh_local):
        out = model.electrical_balance(v_kmh_local / 3.6, slope_pct, z, Tb, d0['G_poa'], d0['Tcell_C'],
                                       headwind_ms=headwind_ms)
        P_pack = float(out['P_pack'])
        return z - (P_pack * model.p.dt / 3600.0) / model.p.E_nom_Wh

    if z_next_for(v_kmh) >= (target_soc - tol):
        return v_kmh
    lo = 0.0
    hi = max(0.0, float(v_kmh))
    for _ in range(25):
        mid = 0.5 * (lo + hi)
        if z_next_for(mid) < (target_soc - tol):
            hi = mid
        else:
            lo = mid
    return float(lo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--forecast_csv', required=True)
    ap.add_argument('--forecast_time_tz', default='UTC')
    ap.add_argument('--route_profile_csv', required=True)
    ap.add_argument('--speed_profile_csv', required=False, default='')
    ap.add_argument('--params_yaml', required=True)
    ap.add_argument('--stop_yaml', required=True)
    ap.add_argument('--drive_schedule_yaml', required=False, default='')
    ap.add_argument('--panel_eff_map', default='')
    ap.add_argument('--mppt_eff_map', default='')
    ap.add_argument('--ocv_soc_map', default='')
    ap.add_argument('--drive_eff_map', default='/home/hiroya0928/solar_ws/src/mpc_solarcar/maps/drive_eff_map.csv')
    ap.add_argument('--regen_eff_map', default='/home/hiroya0928/solar_ws/src/mpc_solarcar/maps/regen_eff_map.csv')
    ap.add_argument('--rint_map', default='/home/hiroya0928/solar_ws/src/mpc_solarcar/maps/Rint_T_by_soc.csv')
    ap.add_argument('--drive_map_eco', default='')
    ap.add_argument('--drive_map_power', default='')
    ap.add_argument('--regen_map_eco', default='')
    ap.add_argument('--regen_map_power', default='')
    ap.add_argument('--dt', type=float, default=600.0)
    ap.add_argument('--horizon_steps', type=int, default=9)
    ap.add_argument('--soc0', type=float, default=0.99)
    ap.add_argument('--Tb0', type=float, default=30.0)
    ap.add_argument('--v0_kmh', type=float, default=40.0)
    ap.add_argument('--start_utc', default='')
    ap.add_argument('--start_index', type=int, default=-1)
    ap.add_argument('--start_s_km', type=float, default=-1.0)
    ap.add_argument('--resume_csv', default='')
    ap.add_argument('--resume_s_km', type=float, default=-1.0)
    ap.add_argument('--out_csv', default='solar_sim_log.csv')
    ap.add_argument('--out_detail_csv', default='')
    ap.add_argument('--soc_guard_margin', type=float, default=0.01)
    ap.add_argument('--soc_guard_mode', default='stop')
    ap.add_argument('--solar_gain', type=float, default=1.0)
    ap.add_argument('--poa_gain_drive', type=float, default=1.0)
    ap.add_argument('--poa_gain_stop', type=float, default=1.0)
    ap.add_argument('--energy_budget', action='store_true')
    ap.add_argument('--upper_mode', default='time')
    ap.add_argument('--upper_ds_km', type=float, default=20.0)
    ap.add_argument('--upper_horizon_km', type=float, default=3000.0)
    ap.add_argument('--upper_max_steps', type=int, default=200)
    ap.add_argument('--upper_replan_km', type=float, default=0.0)
    ap.add_argument('--upper_replan_sec', type=float, default=0.0)
    ap.add_argument('--upper_max_iter', type=int, default=120)
    ap.add_argument('--upper_ctrl_km', type=float, default=0.0)
    ap.add_argument('--upper_vmin_kmh', type=float, default=1.0)
    ap.add_argument('--soc_target', type=float, default=0.5)
    ap.add_argument('--soc_band', type=float, default=0.1)
    ap.add_argument('--w_soc_target', type=float, default=2.0)
    ap.add_argument('--w_soc_band', type=float, default=50.0)
    ap.add_argument('--soc_day_end_max', type=float, default=-1.0)
    ap.add_argument('--w_soc_day_max', type=float, default=1.0e4)
    ap.add_argument('--soc_finish_target', type=float, default=-1.0)
    ap.add_argument('--soc_finish_tol', type=float, default=0.02)
    ap.add_argument('--w_soc_progress', type=float, default=1.0e5)
    ap.add_argument('--w_soc_terminal', type=float, default=1.0e5)
    ap.add_argument('--race_km', type=float, default=3035.5)
    ap.add_argument('--soc_day_end_target', type=float, default=-1.0)
    ap.add_argument('--soc_day_end_tol', type=float, default=0.03)
    ap.add_argument('--w_soc_day_track', type=float, default=5.0e4)
    ap.add_argument('--upper_day_end_soc_min', type=float, default=0.2)
    ap.add_argument('--out_plan_csv', default='')
    args = ap.parse_args()

    df = pd.read_csv(args.forecast_csv)
    if 'time' in df.columns:
        t = pd.to_datetime(df['time'], errors='coerce')
        tzname = str(args.forecast_time_tz or 'UTC')
        if t.dt.tz is None:
            if tzname.upper() == 'UTC':
                t = t.dt.tz_localize('UTC')
            else:
                t = t.dt.tz_localize(ZoneInfo(tzname), ambiguous='NaT', nonexistent='NaT').dt.tz_convert('UTC')
        else:
            t = t.dt.tz_convert('UTC')
        df['time'] = t
    route_profile = load_profile(args.route_profile_csv)
    speed_profile = load_profile(args.speed_profile_csv)
    stops = load_stops(args.stop_yaml)
    schedule = DriveSchedule.from_yaml(args.drive_schedule_yaml) if args.drive_schedule_yaml else None

    cfg = load_yaml(args.params_yaml)
    model_cfg = cfg.get('model', cfg if isinstance(cfg, dict) else {})
    p = Params(dt=args.dt)
    for k, v in model_cfg.items():
        if hasattr(p, k):
            try:
                setattr(p, k, float(v))
            except Exception:
                setattr(p, k, v)
    ocv_map = args.ocv_soc_map
    if not ocv_map and isinstance(model_cfg, dict):
        ocv_map = model_cfg.get('ocv_soc_map', '')
    if ocv_map and not os.path.isabs(ocv_map):
        base_dir = os.path.dirname(args.drive_eff_map) if args.drive_eff_map else ''
        ocv_map = os.path.join(base_dir, ocv_map) if base_dir else ocv_map

    model = SolarCarModel(
        args.drive_eff_map,
        args.regen_eff_map,
        args.rint_map,
        params=p,
        panel_eff_map_path=args.panel_eff_map or None,
        mppt_eff_map_path=args.mppt_eff_map or None,
        drive_map_eco_path=args.drive_map_eco or None,
        drive_map_power_path=args.drive_map_power or None,
        regen_map_eco_path=args.regen_map_eco or None,
        regen_map_power_path=args.regen_map_power or None,
        ocv_soc_map_path=ocv_map or None,
    )
    if 'model' in cfg:
        mc = cfg.get('model', {})
        if isinstance(mc, dict):
            if 'drive_mode' in mc:
                model.drive_mode = str(mc.get('drive_mode'))
            if 'drive_mode_tau_margin' in mc:
                try:
                    model.drive_mode_tau_margin = float(mc.get('drive_mode_tau_margin'))
                except Exception:
                    pass

    v_max_kmh = float(cfg.get('mpc', {}).get('v_max_kmh', 110.0))
    term_soc_min = float(cfg.get('mpc', {}).get('terminal_soc_min', 0.1))
    w_dv = float(cfg.get('mpc', {}).get('w_dv', 0.05))
    w_dv_limit = float(cfg.get('mpc', {}).get('w_dv_limit', 2.0))
    dv_max_kmhps = float(cfg.get('mpc', {}).get('dv_max_kmhps', 5.0))
    w_T = float(cfg.get('mpc', {}).get('w_T', 5.0))
    w_speed_limit = float(cfg.get('mpc', {}).get('w_speed_limit', 50.0))
    w_current = float(cfg.get('mpc', {}).get('w_current', 0.02))
    soc_guard_margin = float(cfg.get('mpc', {}).get('soc_guard_margin', args.soc_guard_margin))
    soc_guard_mode = str(cfg.get('mpc', {}).get('soc_guard_mode', args.soc_guard_mode))
    upper_mode = str(cfg.get('mpc', {}).get('upper_mode', args.upper_mode)).lower()
    upper_ds_km = float(cfg.get('mpc', {}).get('upper_ds_km', args.upper_ds_km))
    upper_horizon_km = float(cfg.get('mpc', {}).get('upper_horizon_km', args.upper_horizon_km))
    upper_max_steps = int(cfg.get('mpc', {}).get('upper_max_steps', args.upper_max_steps))
    upper_replan_km = float(cfg.get('mpc', {}).get('upper_replan_km', args.upper_replan_km))
    upper_replan_sec = float(cfg.get('mpc', {}).get('upper_replan_sec', args.upper_replan_sec))
    upper_max_iter = int(cfg.get('mpc', {}).get('upper_max_iter', args.upper_max_iter))
    upper_ctrl_km = float(cfg.get('mpc', {}).get('upper_ctrl_km', args.upper_ctrl_km))
    upper_vmin_kmh = float(cfg.get('mpc', {}).get('upper_vmin_kmh', args.upper_vmin_kmh))
    soc_target = float(cfg.get('mpc', {}).get('soc_target', args.soc_target))
    soc_band = float(cfg.get('mpc', {}).get('soc_band', args.soc_band))
    w_soc_target = float(cfg.get('mpc', {}).get('w_soc_target', args.w_soc_target))
    w_soc_band = float(cfg.get('mpc', {}).get('w_soc_band', args.w_soc_band))
    soc_day_end_max = float(cfg.get('mpc', {}).get('soc_day_end_max', args.soc_day_end_max))
    w_soc_day_max = float(cfg.get('mpc', {}).get('w_soc_day_max', args.w_soc_day_max))
    soc_finish_target = float(cfg.get('mpc', {}).get('soc_finish_target', args.soc_finish_target))
    soc_finish_tol = float(cfg.get('mpc', {}).get('soc_finish_tol', args.soc_finish_tol))
    w_soc_progress = float(cfg.get('mpc', {}).get('w_soc_progress', args.w_soc_progress))
    w_soc_terminal = float(cfg.get('mpc', {}).get('w_soc_terminal', args.w_soc_terminal))
    race_km = float(cfg.get('mpc', {}).get('race_km', args.race_km))
    soc_day_end_target = float(cfg.get('mpc', {}).get('soc_day_end_target', args.soc_day_end_target))
    soc_day_end_tol = float(cfg.get('mpc', {}).get('soc_day_end_tol', args.soc_day_end_tol))
    w_soc_day_track = float(cfg.get('mpc', {}).get('w_soc_day_track', args.w_soc_day_track))
    upper_day_end_soc_min = float(cfg.get('mpc', {}).get('upper_day_end_soc_min', args.upper_day_end_soc_min))
    soc_target = float(np.clip(soc_target, p.soc_min, p.soc_max))
    soc_band = max(0.0, float(soc_band))
    if soc_day_end_max > 0.0:
        soc_day_end_max = float(np.clip(soc_day_end_max, p.soc_min, p.soc_max))
    if soc_finish_target > 0.0:
        soc_finish_target = float(np.clip(soc_finish_target, p.soc_min, p.soc_max))
    soc_finish_tol = max(0.0, float(soc_finish_tol))
    race_km = max(1.0, float(race_km))
    if soc_day_end_target > 0.0:
        soc_day_end_target = float(np.clip(soc_day_end_target, p.soc_min, p.soc_max))
    soc_day_end_tol = max(0.0, float(soc_day_end_tol))

    # schedule / start time
    if args.start_utc:
        ts = str(args.start_utc)
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        start_utc = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    else:
        if 'time' in df.columns and df['time'].notna().any():
            start_utc = df['time'].iloc[0].to_pydatetime()
        else:
            start_utc = datetime.now(timezone.utc)

    z = args.soc0
    Tb = args.Tb0
    s_km = 0.0
    v_cmd = args.v0_kmh
    sim_t = start_utc

    # Resume from a previous log if requested
    if args.resume_csv:
        try:
            df_resume = pd.read_csv(args.resume_csv)
            if 's_km' in df_resume.columns:
                if args.resume_s_km >= 0.0:
                    idx = df_resume['s_km'].searchsorted(args.resume_s_km, side='left')
                    idx = int(min(max(idx, 0), len(df_resume) - 1))
                else:
                    idx = int(len(df_resume) - 1)
                row = df_resume.iloc[idx]
                if 'soc' in df_resume.columns:
                    z = float(row['soc'])
                if 'Tb_C' in df_resume.columns:
                    Tb = float(row['Tb_C'])
                if 'v_cmd_kmh' in df_resume.columns:
                    v_cmd = float(row['v_cmd_kmh'])
                s_km = float(row['s_km'])
                if not args.start_utc and 'time_utc' in df_resume.columns:
                    try:
                        ts = str(row['time_utc'])
                        if ts.endswith('Z'):
                            ts = ts[:-1] + '+00:00'
                        sim_t = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
                    except Exception:
                        pass
        except Exception:
            pass

    if args.start_s_km >= 0.0:
        s_km = float(args.start_s_km)

    def time_to_index(dt_utc):
        if 'time' not in df.columns or df['time'].isna().all():
            return 0
        t_series = df['time'].values
        idx = int(np.searchsorted(t_series, np.datetime64(dt_utc)) - 1)
        return int(np.clip(idx, 0, len(df) - 1))

    if args.start_index >= 0:
        k = int(min(max(args.start_index, 0), len(df) - 1))
    else:
        k = time_to_index(sim_t)
    stop_queue = sorted([float(s.get('s_km', 0.0)) for s in stops])
    next_stop_idx = 0
    for i, s_stop in enumerate(stop_queue):
        if s_km < s_stop:
            next_stop_idx = i
            break
    else:
        next_stop_idx = len(stop_queue)
    stop_timer = 0.0

    log = []
    detail_log = []
    plan_log = []
    plan_segments = None
    plan_s0_km = float(s_km)
    last_plan_s_km = float(s_km)
    last_plan_time = sim_t
    last_upper_ctrl = None
    plan_id = 0
    day_start_soc = None
    day_start_time = None
    prev_drive = False
    soc_start_global = float(z)
    total_drive_sec = 0.0
    if schedule is not None:
        t_tmp = start_utc
        for j in range(len(df)):
            if schedule.is_drive_time(t_tmp):
                total_drive_sec += args.dt
            t_tmp += timedelta(seconds=args.dt)
    if total_drive_sec <= 0.0:
        total_drive_sec = 1.0
    drive_time_elapsed = 0.0
    t_start = time.perf_counter()
    def remaining_day_budget(sim_t_local, k_idx):
        if schedule is None:
            return None, None
        t = sim_t_local
        j = k_idx
        E_pv = 0.0
        t_remain = 0.0
        while j < len(df):
            limits = schedule.speed_limits(t)
            if limits is not None and limits[1] <= 0.0:
                break
            row = df.iloc[j]
            G_raw = float(row.get('GHI', 0.0)) * args.solar_gain
            G_poa = G_raw * args.poa_gain_drive
            Tcell = float(row.get('Tcell_C', 40.0))
            P_pv = float(model.pv_power_mppt(G_poa, Tcell))
            E_pv += P_pv * (args.dt / 3600.0)
            t_remain += args.dt
            t += timedelta(seconds=args.dt)
            j += 1
        return E_pv, t_remain

    def budget_speed_limit(P_allow, d0):
        if P_allow is None:
            return None
        lo = 0.0
        hi = v_max_kmh
        for _ in range(24):
            mid = 0.5 * (lo + hi)
            out = model.electrical_balance(mid / 3.6, d0['slope_pct'], z, Tb, d0['G_poa'], d0['Tcell_C'], headwind_ms=d0['headwind_ms'])
            P_pack = float(out['P_pack'])
            if P_pack > P_allow:
                hi = mid
            else:
                lo = mid
        return float(lo)

    def forecast_at_time(t_utc, drive=True):
        if len(df) == 0:
            return dict(G_poa=0.0, Tcell_C=40.0, Tamb_C=30.0, headwind_ms=0.0)
        if 'time' in df.columns and df['time'].notna().any():
            t_series = df['time'].values
            idx = int(np.searchsorted(t_series, np.datetime64(t_utc)) - 1)
            idx = int(np.clip(idx, 0, len(df) - 1))
        else:
            elapsed = (t_utc - start_utc).total_seconds()
            idx = int(np.clip(elapsed / max(args.dt, 1e-3), 0, len(df) - 1))
        row = df.iloc[idx]
        gain = args.poa_gain_drive if drive else args.poa_gain_stop
        G_raw = float(row.get('GHI', 0.0)) * args.solar_gain
        return dict(
            G_poa=G_raw * gain,
            Tcell_C=float(row.get('Tcell_C', 40.0)),
            Tamb_C=float(row.get('Tamb_C', 30.0)),
            headwind_ms=float(row.get('headwind_ms', 0.0)),
        )

    def step_wait(t_utc, z, Tb, s_km):
        if schedule is None:
            return t_utc, z, Tb, 0.0
        if schedule.is_drive_time(t_utc):
            return t_utc, z, Tb, 0.0
        t_start = schedule.next_drive_start(t_utc)
        dt_wait = max(0.0, (t_start - t_utc).total_seconds())
        if dt_wait <= 0.0:
            return t_start, z, Tb, 0.0
        env = forecast_at_time(t_utc, drive=False)
        slope_pct = get_profile_val(route_profile, s_km, 'slope_pct', 0.0)
        headwind_ms = get_profile_val(route_profile, s_km, 'headwind_ms', env.get('headwind_ms', 0.0))
        out = model.electrical_balance(0.0, slope_pct, z, Tb, env['G_poa'], env['Tcell_C'], headwind_ms=headwind_ms)
        P_pack = float(out['P_pack'])
        loss_int = float(out['losses_int'])
        z = z - (P_pack * dt_wait / 3600.0) / p.E_nom_Wh
        Tb = Tb + (dt_wait / 1800.0) * (env['Tamb_C'] - Tb) + (loss_int * dt_wait) / 50000.0
        return t_start, float(z), float(Tb), dt_wait

    def mpc_solve_distance(t0_utc, s0_km, z0, Tb0, v0_kmh, v_init=None):
        ds_km = max(1.0, upper_ds_km)
        horizon_km = max(ds_km, upper_horizon_km)
        Np = int(math.ceil(horizon_km / ds_km))
        if upper_max_steps > 0:
            Np = min(Np, upper_max_steps)
        if Np <= 0:
            return v0_kmh, [{'v_kmh': v0_kmh, 'dt_sec': args.dt}], np.array([v0_kmh], dtype=float)

        v_min_solver = max(0.1, float(upper_vmin_kmh))
        ctrl_km = float(upper_ctrl_km) if upper_ctrl_km and upper_ctrl_km > 0.0 else ds_km
        ctrl_km = max(ds_km, ctrl_km)
        seg_s = np.arange(Np, dtype=float) * ds_km
        ctrl_s = np.arange(0.0, float(seg_s[-1]) + 1.0e-6, ctrl_km)
        if len(ctrl_s) == 0:
            ctrl_s = np.array([0.0], dtype=float)
        if ctrl_s[-1] < seg_s[-1]:
            ctrl_s = np.append(ctrl_s, seg_s[-1])
        Nc = int(len(ctrl_s))

        if v_init is not None and len(v_init) == Nc:
            x0 = np.array(v_init, dtype=float)
        else:
            x0 = np.array([v_max_kmh] * Nc, dtype=float)
        bounds = [(v_min_solver, v_max_kmh)] * Nc

        idx = np.searchsorted(ctrl_s, seg_s, side='right') - 1
        idx = np.clip(idx, 0, Nc - 1)
        idx_next = np.clip(idx + 1, 0, Nc - 1)
        denom = np.maximum(ctrl_s[idx_next] - ctrl_s[idx], 1.0e-6)
        alpha = (seg_s - ctrl_s[idx]) / denom

        def expand_ctrl(u_vec):
            return (1.0 - alpha) * u_vec[idx] + alpha * u_vec[idx_next]

        def quad_penalty(x, cap=1.0e3):
            if x <= 0.0:
                return 0.0
            if x > cap:
                x = cap
            return x * x

        def cost(u_vec):
            z = float(z0)
            Tb = float(Tb0)
            s_km = float(s0_km)
            t_utc = t0_utc
            v_prev = float(v0_kmh)
            J = 0.0
            v_seq = expand_ctrl(u_vec)
            for k_i in range(Np):
                t_utc, z, Tb, dt_wait = step_wait(t_utc, z, Tb, s_km)
                if dt_wait > 0.0:
                    J += dt_wait
                v_k = float(v_seq[k_i])
                vmax_local = get_profile_val(speed_profile, s_km, 'v_max_kmh', v_max_kmh)
                if vmax_local >= v_min_solver:
                    v_k = max(v_min_solver, min(v_k, vmax_local))
                else:
                    v_k = max(0.0, min(v_k, vmax_local))
                if schedule is not None:
                    limits = schedule.speed_limits(t_utc)
                    if limits is not None:
                        vmin_kmh, vmax_kmh = limits
                        J += 1e5 * quad_penalty(vmin_kmh - v_k)
                        J += 1e5 * quad_penalty(v_k - vmax_kmh)

                dt_travel = ds_km / max(v_k, 1.0e-3) * 3600.0
                env = forecast_at_time(t_utc, drive=True)
                slope_pct = get_profile_val(route_profile, s_km, 'slope_pct', 0.0)
                headwind_ms = get_profile_val(route_profile, s_km, 'headwind_ms', env.get('headwind_ms', 0.0))
                out = model.electrical_balance(v_k / 3.6, slope_pct, z, Tb, env['G_poa'], env['Tcell_C'], headwind_ms=headwind_ms)
                I = float(out['I'])
                V = float(out['V'])
                P_pack = float(out['P_pack'])
                loss_int = float(out['losses_int'])
                z_next = z - (P_pack * dt_travel / 3600.0) / p.E_nom_Wh
                Tb_next = Tb + (dt_travel / 1800.0) * (env['Tamb_C'] - Tb) + (loss_int * dt_travel) / 50000.0

                J += dt_travel
                J += 30.0 * quad_penalty(term_soc_min - z_next)
                if schedule is not None and soc_day_end_target > 0.0:
                    win = schedule.current_drive_window(t_utc)
                    if win is not None:
                        t_start, t_end = win
                        if t_end > t_start:
                            prog = (t_utc - t_start).total_seconds() / (t_end - t_start).total_seconds()
                            prog = max(0.0, min(1.0, prog))
                            soc_line = z0 + (soc_day_end_target - z0) * prog
                            if z_next > (soc_line + soc_day_end_tol):
                                J += w_soc_day_track * quad_penalty(z_next - (soc_line + soc_day_end_tol))
                            if z_next < (soc_line - soc_day_end_tol):
                                J += w_soc_day_track * quad_penalty((soc_line - soc_day_end_tol) - z_next)

                dv = (v_k - v_prev) / max(dt_travel, 1.0e-3)
                if dv_max_kmhps > 0.0:
                    J += w_dv_limit * quad_penalty(abs(dv) - dv_max_kmhps)

                J += w_speed_limit * quad_penalty(v_k - vmax_local)

                J += 1e4 * quad_penalty(I - p.I_max)
                J += 1e4 * quad_penalty(p.I_chg_min - I)
                J += 1e4 * quad_penalty(p.V_min - V)
                J += 1e4 * quad_penalty(V - p.V_max)
                J += w_T * quad_penalty(Tb_next - p.T_max)
                J += w_T * quad_penalty(p.T_min - Tb_next)
                J += 1e4 * quad_penalty(p.soc_min - z_next)
                J += 1e4 * quad_penalty(z_next - p.soc_max)

                t_next = t_utc + timedelta(seconds=dt_travel)
                if schedule is not None and schedule.is_drive_time(t_utc) and not schedule.is_drive_time(t_next):
                    J += 1e5 * quad_penalty(upper_day_end_soc_min - z_next)
                    if soc_day_end_max > 0.0:
                        J += w_soc_day_max * quad_penalty(z_next - soc_day_end_max)

                t_utc = t_next
                s_km += ds_km
                z, Tb = z_next, Tb_next
                v_prev = v_k
            J += 1e4 * quad_penalty(term_soc_min - z)
            if soc_finish_target > 0.0:
                J += w_soc_terminal * quad_penalty(z - soc_finish_target)
            return J

        from scipy.optimize import minimize
        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=upper_max_iter))
        u_seq = res.x if res.success else x0
        v_seq = expand_ctrl(u_seq)

        segments = []
        t_utc = t0_utc
        s_km = float(s0_km)
        z = float(z0)
        Tb = float(Tb0)
        for v_k in v_seq:
            t_utc, z, Tb, _ = step_wait(t_utc, z, Tb, s_km)
            v_k = float(np.clip(v_k, 0.0, v_max_kmh))
            vmax_local = get_profile_val(speed_profile, s_km, 'v_max_kmh', v_max_kmh)
            if vmax_local >= v_min_solver:
                v_k = max(v_min_solver, min(v_k, vmax_local))
            else:
                v_k = max(0.0, min(v_k, vmax_local))
            dt_travel = ds_km / max(v_k, 1.0e-3) * 3600.0
            segments.append({'v_kmh': v_k, 'dt_sec': float(dt_travel)})
            t_utc = t_utc + timedelta(seconds=dt_travel)
            s_km += ds_km
        v0 = float(segments[0]['v_kmh']) if segments else v0_kmh
        return v0, segments, u_seq

    while s_km < float(df['time'].shape[0] * args.dt) and s_km < 3035.5 and k < len(df) - 1:
        v_prev_cmd = float(v_cmd)
        # build horizon data
        data = []
        for j in range(k, min(k + args.horizon_steps, len(df))):
            row = df.iloc[j]
            t_j = sim_t + timedelta(seconds=(j - k) * args.dt)
            gain = args.poa_gain_drive
            if schedule is not None:
                limits = schedule.speed_limits(t_j)
                if limits is not None and limits[1] <= 0.0:
                    gain = args.poa_gain_stop
            G_raw = float(row.get('GHI', 0.0)) * args.solar_gain
            G_poa = G_raw * gain
            data.append(dict(
                G_raw=G_raw,
                G_poa=G_poa,
                Tcell_C=float(row.get('Tcell_C', 40.0)),
                slope_pct=get_profile_val(route_profile, s_km, 'slope_pct', float(row.get('slope_pct', 0.0))),
                Tamb_C=float(row.get('Tamb_C', 30.0)),
                headwind_ms=float(row.get('headwind_ms', 0.0)),
            ))

        if upper_mode == 'distance':
            need_plan = plan_segments is None
            if not need_plan and upper_replan_km > 0.0 and (s_km - last_plan_s_km) >= upper_replan_km:
                need_plan = True
            if not need_plan and upper_replan_sec > 0.0:
                if (sim_t - last_plan_time).total_seconds() >= upper_replan_sec:
                    need_plan = True
            if not need_plan and plan_segments is not None:
                idx = int(max(0, math.floor((s_km - plan_s0_km) / max(upper_ds_km, 1e-6))))
                if idx >= len(plan_segments):
                    need_plan = True
            if need_plan:
                v_cmd, plan_segments, last_upper_ctrl = mpc_solve_distance(
                    sim_t, s_km, z, Tb, v_cmd, v_init=last_upper_ctrl
                )
                plan_s0_km = float(s_km)
                last_plan_s_km = float(s_km)
                last_plan_time = sim_t
                plan_id += 1
                if plan_segments is not None:
                    for idx, seg in enumerate(plan_segments):
                        plan_log.append([
                            sim_t.isoformat(),
                            plan_id,
                            s_km,
                            idx,
                            s_km + upper_ds_km * (idx + 1),
                            float(seg['v_kmh']),
                            float(seg['dt_sec']),
                        ])
            if plan_segments is not None:
                idx = int(max(0, math.floor((s_km - plan_s0_km) / max(upper_ds_km, 1e-6))))
                if idx >= len(plan_segments):
                    idx = len(plan_segments) - 1
                v_cmd = float(plan_segments[idx]['v_kmh']) if plan_segments else v_cmd
        else:
            v_cmd = mpc_solve(
                model, data, z, Tb, s_km, v_cmd, v_max_kmh, term_soc_min,
                w_dv, w_dv_limit, dv_max_kmhps, w_T, w_speed_limit, w_current, speed_profile,
                soc_target, soc_band, w_soc_target, w_soc_band, schedule, soc_day_end_max, w_soc_day_max,
                soc_finish_target, soc_finish_tol, w_soc_progress, w_soc_terminal, race_km,
                soc_day_end_target, soc_day_end_tol, w_soc_day_track
            )

        # schedule-based clamp
        hard_stop = False
        if schedule is not None:
            limits = schedule.speed_limits(sim_t)
            if limits is not None:
                vmin_kmh, vmax_kmh = limits
                v_cmd = max(vmin_kmh, min(vmax_kmh, v_cmd))
                if vmax_kmh <= 0.0:
                    hard_stop = True
        drive_now = schedule.is_drive_time(sim_t) if schedule is not None else True
        if drive_now and not prev_drive:
            day_start_soc = float(z)
            day_start_time = sim_t
        prev_drive = drive_now

        # energy budget speed cap to avoid mid-day depletion
        if args.energy_budget:
            limits = schedule.speed_limits(sim_t) if schedule is not None else None
            if limits is not None and limits[1] > 0.0:
                E_pv, t_remain = remaining_day_budget(sim_t, k)
                if t_remain and t_remain > 0.0:
                    E_batt = max(0.0, (z - model.p.soc_min) * model.p.E_nom_Wh)
                    P_allow = (E_batt + E_pv) * 3600.0 / t_remain
                    v_budget = budget_speed_limit(P_allow, data[0])
                    if v_budget is not None:
                        v_cmd = min(v_cmd, v_budget)

        # control stop dwell
        if next_stop_idx < len(stop_queue) and s_km >= stop_queue[next_stop_idx]:
            stop_timer = max(stop_timer, 1800.0)
            next_stop_idx += 1
        if stop_timer > 0.0:
            v_cmd = 0.0
            stop_timer -= args.dt
            hard_stop = True

        v_cmd = soc_guard_speed(model, v_cmd, z, Tb, s_km, data[0], route_profile, soc_guard_mode, soc_guard_margin)
        if drive_now:
            drive_time_elapsed += args.dt
        if (not hard_stop) and drive_now and soc_finish_target > 0.0:
            prog_total = max(0.0, min(1.0, drive_time_elapsed / total_drive_sec))
            soc_line_total = soc_start_global + (soc_finish_target - soc_start_global) * prog_total
            v_cmd = soc_day_guard_speed(model, v_cmd, z, Tb, s_km, data[0], route_profile, soc_line_total, soc_finish_tol)
        if (not hard_stop) and drive_now and soc_day_end_target > 0.0:
            win = schedule.current_drive_window(sim_t) if schedule is not None else None
            if win is not None:
                win_start, win_end = win
                if win_end > win_start:
                    prog = (sim_t - win_start).total_seconds() / (win_end - win_start).total_seconds()
                    prog = max(0.0, min(1.0, prog))
                    z0_line = day_start_soc if day_start_soc is not None else z
                    soc_line = z0_line + (soc_day_end_target - z0_line) * prog
                    v_cmd = soc_day_guard_speed(model, v_cmd, z, Tb, s_km, data[0], route_profile, soc_line, soc_day_end_tol)
        if hard_stop:
            v_cmd = 0.0

        # Apply POA gain based on actual stop/drive state
        if schedule is not None:
            limits = schedule.speed_limits(sim_t)
            if limits is not None and limits[1] <= 0.0:
                data[0]['G_poa'] = float(data[0].get('G_raw', data[0]['G_poa'])) * args.poa_gain_stop
        if v_cmd <= 0.1 or stop_timer > 0.0:
            data[0]['G_poa'] = float(data[0].get('G_raw', data[0]['G_poa'])) * args.poa_gain_stop

        v_ms = v_cmd / 3.6
        slope_pct = data[0]['slope_pct']
        headwind_ms = data[0]['headwind_ms']
        out = model.electrical_balance(v_ms, slope_pct, z, Tb,
                                       data[0]['G_poa'], data[0]['Tcell_C'],
                                       headwind_ms=headwind_ms)
        P_pack = float(out['P_pack'])
        loss_int = float(out['losses_int'])
        forces = model.resistive_forces(v_ms, slope_pct, headwind_ms=headwind_ms)
        detail_log.append([
            sim_t.isoformat(),
            s_km,
            v_cmd,
            v_ms,
            z,
            Tb,
            slope_pct,
            headwind_ms,
            data[0]['G_poa'],
            data[0]['Tamb_C'],
            data[0]['Tcell_C'],
            float(out.get('P_pv', 0.0)),
            float(out.get('P_mech', 0.0)),
            float(out.get('P_mech_wheel', 0.0)),
            float(out.get('P_dc_to_drv', 0.0)),
            float(out.get('P_reg_to_dc', 0.0)),
            float(out.get('P_pack', 0.0)),
            float(out.get('I', 0.0)),
            float(out.get('V', 0.0)),
            float(out.get('OCV', 0.0)),
            float(out.get('Rint', 0.0)),
            float(out.get('Rline', 0.0)),
            float(out.get('losses_int', 0.0)),
            float(out.get('losses_line', 0.0)),
            float(out.get('eff_drv', 0.0)),
            float(out.get('eff_reg', 0.0)),
            float(forces.get('F_aero', 0.0)),
            float(forces.get('F_roll', 0.0)),
            float(forces.get('F_grade', 0.0)),
            float(forces.get('F_total', 0.0)),
        ])
        z = z - (P_pack * args.dt / 3600.0) / model.p.E_nom_Wh
        Tb = Tb + (args.dt / 1800.0) * (data[0]['Tamb_C'] - Tb) + (loss_int * args.dt) / 50000.0
        z = float(np.clip(z, model.p.soc_min, model.p.soc_max))
        Tb = float(np.clip(Tb, model.p.T_min, model.p.T_max))
        s_km += v_cmd * (args.dt / 3600.0)

        log.append([sim_t.isoformat(), s_km, v_cmd, z, Tb, data[0]['G_poa'], data[0]['Tamb_C'], data[0]['headwind_ms']])
        # plan_log is appended only when a new plan is generated
        sim_t += timedelta(seconds=args.dt)
        k += 1

        if s_km >= 3035.5:
            break

    t_end = time.perf_counter()
    out_df = pd.DataFrame(log, columns=['time_utc', 's_km', 'v_cmd_kmh', 'soc', 'Tb_C', 'GHI', 'Tamb_C', 'headwind_ms'])
    tzname = str(args.forecast_time_tz or 'UTC')
    try:
        local_tz = ZoneInfo(tzname) if tzname.upper() != 'UTC' else ZoneInfo('UTC')
        out_df['time_local'] = pd.to_datetime(out_df['time_utc'], utc=True, errors='coerce').dt.tz_convert(local_tz)
    except Exception:
        pass
    out_df.to_csv(args.out_csv, index=False)
    if detail_log:
        detail_csv = args.out_detail_csv or args.out_csv.replace('.csv', '_detail.csv')
        detail_df = pd.DataFrame(detail_log, columns=[
            'time_utc', 's_km', 'v_cmd_kmh', 'v_cmd_ms', 'soc', 'Tb_C',
            'slope_pct', 'headwind_ms', 'G_poa', 'Tamb_C', 'Tcell_C',
            'P_pv', 'P_mech', 'P_mech_wheel', 'P_dc_to_drv', 'P_reg_to_dc',
            'P_pack', 'I', 'V', 'OCV', 'Rint', 'Rline', 'losses_int', 'losses_line',
            'eff_drv', 'eff_reg', 'F_aero', 'F_roll', 'F_grade', 'F_total'
        ])
        try:
            tzname = str(args.forecast_time_tz or 'UTC')
            local_tz = ZoneInfo(tzname) if tzname.upper() != 'UTC' else ZoneInfo('UTC')
            detail_df['time_local'] = pd.to_datetime(detail_df['time_utc'], utc=True, errors='coerce').dt.tz_convert(local_tz)
        except Exception:
            pass
        detail_df.to_csv(detail_csv, index=False)
    if upper_mode == 'distance':
        plan_csv = args.out_plan_csv or args.out_csv.replace('.csv', '_upper_plan.csv')
        plan_df = pd.DataFrame(
            plan_log,
            columns=['time_utc', 'plan_id', 's_km', 'plan_idx', 'plan_s_km', 'plan_v_kmh', 'plan_dt_sec'],
        )
        try:
            tzname = str(args.forecast_time_tz or 'UTC')
            local_tz = ZoneInfo(tzname) if tzname.upper() != 'UTC' else ZoneInfo('UTC')
            plan_df['time_local'] = pd.to_datetime(plan_df['time_utc'], utc=True, errors='coerce').dt.tz_convert(local_tz)
        except Exception:
            pass
        plan_df.to_csv(plan_csv, index=False)
    print(f'log saved: {args.out_csv}')
    if log:
        total_time_h = (len(log) * args.dt) / 3600.0
        print(f'total_time_h: {total_time_h:.2f}')
        print(f'avg_speed_kmh: {s_km / total_time_h:.2f}')
        print(f'min_soc: {out_df["soc"].min():.3f}')
        print(f'cpu_sec: {t_end - t_start:.2f}')
        if s_km < 3035.5:
            print('WARN: finish not reached; plan is infeasible under current assumptions.')


if __name__ == '__main__':
    main()
