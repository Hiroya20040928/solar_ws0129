#!/usr/bin/env python3
import argparse
import copy
import hashlib
import html
import json
import math
import time
import os
import sys
from collections import deque
from pathlib import Path
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar.model import SolarCarModel, Params
from mpc_solarcar.route_utils import interpolate_profile
from mpc_solarcar.schedule_utils import DriveSchedule
from mpc_solarcar.signal_utils import SmoothRateLimiter
from mpc_solarcar.solar_profile import get_path, get_section, load_profile as load_workflow_profile
from mpc_solarcar.upper_cost import (
    active_upper_cost_terms,
    load_upper_cost_config,
    quad_penalty,
    upper_stage_cost,
    upper_terminal_cost,
)
from mpc_solarcar.upper_horizon import build_upper_distance_horizon, plan_segment_index


def load_yaml(path):
    if not path:
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def sim_log(message: str):
    print(f"[solar_sim] {message}", flush=True)


def timestamp_ns(value) -> int:
    return int(pd.Timestamp(value).value)


def load_stops(path):
    cfg = load_yaml(path)
    raw_stops = cfg.get('stops', []) if isinstance(cfg, dict) else []
    stops = []
    for item in raw_stops or []:
        if isinstance(item, dict):
            try:
                s_km = float(item.get('s_km', item.get('dist_km', 0.0)))
            except Exception:
                continue
            try:
                dwell_sec = float(item.get('dwell_sec', item.get('duration_sec', 1800.0)))
            except Exception:
                dwell_sec = 1800.0
            stops.append({
                's_km': s_km,
                'dwell_sec': max(0.0, dwell_sec),
                'label': str(item.get('label', item.get('name', '')) or ''),
            })
        else:
            try:
                s_km = float(item)
            except Exception:
                continue
            stops.append({'s_km': s_km, 'dwell_sec': 1800.0, 'label': ''})
    return stops


def load_csv_profile(path):
    if not path:
        return None
    try:
        return pd.read_csv(path)
    except Exception:
        return None


def forecast_distance_column(df: pd.DataFrame) -> str:
    if not isinstance(df, pd.DataFrame):
        return ''
    if 's_km' in df.columns:
        return 's_km'
    if 'route_progress_km' in df.columns:
        return 'route_progress_km'
    return ''


def load_forecast_dataframe(path: str, tzname: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if 'time' not in df.columns:
        return df
    t = pd.to_datetime(df['time'], errors='coerce')
    tzname = str(tzname or 'UTC')
    if t.dt.tz is None:
        if tzname.upper() == 'UTC':
            t = t.dt.tz_localize('UTC')
        else:
            t = t.dt.tz_localize(ZoneInfo(tzname), ambiguous='NaT', nonexistent='NaT').dt.tz_convert('UTC')
    else:
        t = t.dt.tz_convert('UTC')
    df = df.copy()
    df['time'] = t
    dist_col = forecast_distance_column(df)
    sort_cols = ['time'] + ([dist_col] if dist_col else [])
    dedup_cols = ['time'] + ([dist_col] if dist_col else [])
    df = (
        df.loc[df['time'].notna()]
        .sort_values(sort_cols)
        .drop_duplicates(subset=dedup_cols, keep='last')
        .reset_index(drop=True)
    )
    return df


def merge_forecast_dataframes(primary: pd.DataFrame, fallback: pd.DataFrame) -> pd.DataFrame:
    if primary is None or len(primary) == 0:
        return fallback.copy() if fallback is not None else pd.DataFrame()
    if fallback is None or len(fallback) == 0:
        return primary.copy()
    if 'time' not in primary.columns or 'time' not in fallback.columns:
        return primary.copy()
    primary_idx = primary.set_index('time')
    fallback_idx = fallback.set_index('time')
    merged = primary_idx.combine_first(fallback_idx).sort_index().reset_index()
    return merged


def build_forecast_grid_payload(df: pd.DataFrame) -> dict | None:
    dist_col = forecast_distance_column(df)
    if not dist_col or 'time' not in df.columns:
        return None
    work = df.copy()
    work[dist_col] = pd.to_numeric(work[dist_col], errors='coerce')
    work = work.dropna(subset=['time', dist_col]).sort_values(['time', dist_col])
    if work.empty:
        return None
    time_index = pd.Index(work['time'].drop_duplicates().sort_values())
    s_grid = np.array(sorted(work[dist_col].dropna().unique()), dtype=float)
    if len(time_index) < 2 or len(s_grid) < 2:
        return None
    if len(work) <= max(len(time_index), len(s_grid)):
        return None
    work = work.drop_duplicates(subset=['time', dist_col], keep='last')
    matrices = {}
    for col in ('GHI', 'Tamb_C', 'Tcell_C', 'headwind_ms'):
        if col not in work.columns:
            continue
        pivot = (
            work.pivot(index='time', columns=dist_col, values=col)
            .reindex(index=time_index, columns=s_grid)
            .apply(pd.to_numeric, errors='coerce')
            .interpolate(axis=0, limit_direction='both')
            .interpolate(axis=1, limit_direction='both')
            .ffill()
            .bfill()
            .ffill(axis=1)
            .bfill(axis=1)
        )
        matrices[col] = pivot.to_numpy(dtype=float)
    if not matrices:
        return None
    return {
        'dist_col': dist_col,
        'time_ns': np.array([timestamp_ns(value) for value in time_index], dtype=np.int64),
        's_grid': s_grid,
        'matrices': matrices,
    }


def interp_forecast_grid(payload: dict | None, col: str, t_utc: datetime, s_km: float | None, default: float) -> float:
    if not payload:
        return float(default)
    matrix = payload.get('matrices', {}).get(col)
    tg = payload.get('time_ns')
    sg = payload.get('s_grid')
    if matrix is None or tg is None or sg is None or len(tg) == 0 or len(sg) == 0:
        return float(default)
    t_ns = int(np.clip(timestamp_ns(t_utc), int(tg[0]), int(tg[-1])))
    s_val = float(s_km if s_km is not None else sg[0])
    s_val = float(np.clip(s_val, float(sg[0]), float(sg[-1])))

    i_hi = int(np.searchsorted(tg, t_ns, side='left'))
    if i_hi <= 0:
        i0 = i1 = 0
        wt = 0.0
    elif i_hi >= len(tg):
        i0 = i1 = len(tg) - 1
        wt = 0.0
    else:
        i0 = i_hi - 1
        i1 = i_hi
        denom_t = max(int(tg[i1]) - int(tg[i0]), 1)
        wt = float((t_ns - int(tg[i0])) / denom_t)

    j_hi = int(np.searchsorted(sg, s_val, side='left'))
    if j_hi <= 0:
        j0 = j1 = 0
        ws = 0.0
    elif j_hi >= len(sg):
        j0 = j1 = len(sg) - 1
        ws = 0.0
    else:
        j0 = j_hi - 1
        j1 = j_hi
        denom_s = max(float(sg[j1]) - float(sg[j0]), 1.0e-9)
        ws = float((s_val - float(sg[j0])) / denom_s)

    v00 = float(matrix[i0, j0])
    v01 = float(matrix[i0, j1])
    v10 = float(matrix[i1, j0])
    v11 = float(matrix[i1, j1])
    v0 = (1.0 - ws) * v00 + ws * v01
    v1 = (1.0 - ws) * v10 + ws * v11
    return float((1.0 - wt) * v0 + wt * v1)


def load_progress_reference_dataframe(path: str) -> pd.DataFrame | None:
    if not path:
        return None
    try:
        df = pd.read_csv(path, low_memory=False)
    except Exception:
        return None
    time_col = 'time_utc' if 'time_utc' in df.columns else ('time' if 'time' in df.columns else '')
    if not time_col or 's_km' not in df.columns:
        return None
    t = pd.to_datetime(df[time_col], utc=True, errors='coerce')
    out = pd.DataFrame({'time_utc': t, 's_km': pd.to_numeric(df['s_km'], errors='coerce')})
    if 'speed_kmh' in df.columns:
        out['speed_kmh'] = pd.to_numeric(df['speed_kmh'], errors='coerce')
    out = out.dropna(subset=['time_utc', 's_km']).sort_values('time_utc').drop_duplicates(subset=['time_utc'], keep='last')
    if out.empty:
        return None
    return out.reset_index(drop=True)


def ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _deep_copy_cfg(cfg):
    return copy.deepcopy(cfg) if isinstance(cfg, dict) else {}


def _set_nested(cfg, dotted_key: str, value):
    parts = [part for part in str(dotted_key).split('.') if part]
    if not parts:
        raise ValueError('override key is empty')
    cur = cfg
    for part in parts[:-1]:
        next_val = cur.get(part)
        if not isinstance(next_val, dict):
            next_val = {}
            cur[part] = next_val
        cur = next_val
    cur[parts[-1]] = value


def apply_overrides(cfg, overrides):
    cfg = _deep_copy_cfg(cfg)
    applied = []
    for raw in overrides or []:
        item = str(raw).strip()
        if not item:
            continue
        if '=' not in item:
            raise ValueError(f'Invalid override: {item}')
        key, raw_value = item.split('=', 1)
        key = key.strip()
        value = yaml.safe_load(raw_value)
        _set_nested(cfg, key, value)
        applied.append({'key': key, 'value': value})
    return cfg, applied


def build_config_tag(profile_path: str, profile_cfg: dict, overrides=None) -> str:
    payload = {
        'profile_cfg': profile_cfg if isinstance(profile_cfg, dict) else {},
        'overrides': overrides or [],
    }
    canonical = yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)
    digest = hashlib.sha1(canonical.encode('utf-8')).hexdigest()[:8]
    try:
        mtime = datetime.fromtimestamp(os.path.getmtime(profile_path), timezone.utc)
    except Exception:
        mtime = datetime.now(timezone.utc)
    stamp = mtime.strftime('%Y%m%d_%H%M%S')
    return f'{stamp}_{digest}'


def tag_output_path(path_value: str, tag: str, default_ext: str = '') -> str:
    raw = str(path_value or '').strip()
    if not raw or not tag:
        return raw
    if '{tag}' in raw:
        return raw.replace('{tag}', tag)
    stem, ext = os.path.splitext(raw)
    if not ext and default_ext:
        ext = default_ext
    return f'{stem}_{tag}{ext}'


def apply_profile_cfg_to_args(profile_path, profile_cfg, args, *, force_output_defaults=False):
    if not profile_cfg:
        return

    sim_cfg = get_section(profile_cfg, 'simulation')
    runtime_cfg = get_section(profile_cfg, 'runtime')
    logging_cfg = get_section(profile_cfg, 'logging')
    auto_version_outputs = bool(sim_cfg.get('auto_version_outputs', True))
    output_tag = build_config_tag(profile_path, profile_cfg, getattr(args, 'override', [])) if auto_version_outputs else ''

    args.params_yaml = profile_path
    args.profile_path_resolved = profile_path
    args.auto_version_outputs = auto_version_outputs
    args.output_tag = output_tag
    args.forecast_csv = get_path(profile_cfg, profile_path, 'forecast_csv', args.forecast_csv)
    args.forecast_fill_csv = get_path(profile_cfg, profile_path, 'forecast_fill_csv', getattr(args, 'forecast_fill_csv', ''))
    args.progress_reference_csv = get_path(profile_cfg, profile_path, 'progress_reference_csv', getattr(args, 'progress_reference_csv', ''))
    args.route_profile_csv = get_path(profile_cfg, profile_path, 'route_profile_csv', args.route_profile_csv)
    args.speed_profile_csv = get_path(profile_cfg, profile_path, 'speed_profile_csv', args.speed_profile_csv)
    args.stop_yaml = get_path(profile_cfg, profile_path, 'stop_yaml', args.stop_yaml)
    args.drive_schedule_yaml = get_path(profile_cfg, profile_path, 'drive_schedule_yaml', args.drive_schedule_yaml)
    args.drive_eff_map = get_path(profile_cfg, profile_path, 'drive_eff_map', args.drive_eff_map)
    args.regen_eff_map = get_path(profile_cfg, profile_path, 'regen_eff_map', args.regen_eff_map)
    args.rint_map = get_path(profile_cfg, profile_path, 'rint_map', args.rint_map)
    args.panel_eff_map = get_path(profile_cfg, profile_path, 'panel_eff_map', args.panel_eff_map)
    args.mppt_eff_map = get_path(profile_cfg, profile_path, 'mppt_eff_map', args.mppt_eff_map)
    args.ocv_soc_map = get_path(profile_cfg, profile_path, 'ocv_soc_map', args.ocv_soc_map)
    args.drive_map_eco = get_path(profile_cfg, profile_path, 'drive_map_eco', args.drive_map_eco)
    args.drive_map_power = get_path(profile_cfg, profile_path, 'drive_map_power', args.drive_map_power)
    args.regen_map_eco = get_path(profile_cfg, profile_path, 'regen_map_eco', args.regen_map_eco)
    args.regen_map_power = get_path(profile_cfg, profile_path, 'regen_map_power', args.regen_map_power)

    args.forecast_time_mode = str(sim_cfg.get('forecast_time_mode', runtime_cfg.get('forecast_time_mode', args.forecast_time_mode)))
    args.forecast_time_tz = str(runtime_cfg.get('forecast_time_tz', args.forecast_time_tz))
    args.dt = float(get_section(profile_cfg, 'mpc').get('dt', args.dt))
    args.horizon_steps = int(get_section(profile_cfg, 'mpc').get('horizon_steps', args.horizon_steps))
    args.soc0 = float(sim_cfg.get('soc0', args.soc0))
    args.Tb0 = float(sim_cfg.get('Tb0', args.Tb0))
    args.v0_kmh = float(sim_cfg.get('v0_kmh', args.v0_kmh))
    args.start_utc = str(sim_cfg.get('start_utc', args.start_utc or '') or '')
    args.forecast_start_time_utc = str(sim_cfg.get('forecast_start_time_utc', args.forecast_start_time_utc or '') or '')
    args.start_s_km = float(sim_cfg.get('start_s_km', args.start_s_km))
    args.energy_budget = bool(sim_cfg.get('energy_budget', args.energy_budget))
    args.solar_gain = float(get_section(profile_cfg, 'mpc').get('solar_gain', args.solar_gain))
    args.poa_gain_drive = float(get_section(profile_cfg, 'mpc').get('poa_gain_drive', args.poa_gain_drive))
    args.poa_gain_stop = float(get_section(profile_cfg, 'mpc').get('poa_gain_stop', args.poa_gain_stop))
    mpc_cfg = get_section(profile_cfg, 'mpc')
    live_cfg = get_section(profile_cfg, 'live')
    command_bridge_cfg = live_cfg.get('command_bridge', {}) if isinstance(live_cfg.get('command_bridge', {}), dict) else {}
    exec_cfg = sim_cfg.get('execution_model', {}) if isinstance(sim_cfg.get('execution_model', {}), dict) else {}
    args.exec_model_enabled = bool(exec_cfg.get('enabled', args.exec_model_enabled))
    args.exec_inner_dt_sec = float(exec_cfg.get('inner_dt_sec', args.exec_inner_dt_sec))
    args.exec_tau_sec = float(
        exec_cfg.get(
            'tau_sec',
            command_bridge_cfg.get('filter_tau_sec', mpc_cfg.get('speed_meas_filter_tau_sec', args.exec_tau_sec)),
        )
    )
    args.exec_accel_limit_kmhps = float(
        exec_cfg.get(
            'accel_limit_kmhps',
            command_bridge_cfg.get('accel_limit_kmhps', mpc_cfg.get('lower_ref_accel_limit_kmhps', args.exec_accel_limit_kmhps)),
        )
    )
    args.exec_decel_limit_kmhps = float(
        exec_cfg.get(
            'decel_limit_kmhps',
            command_bridge_cfg.get('decel_limit_kmhps', mpc_cfg.get('lower_ref_decel_limit_kmhps', args.exec_decel_limit_kmhps)),
        )
    )
    args.exec_deadband_kmh = float(
        exec_cfg.get(
            'deadband_kmh',
            command_bridge_cfg.get('speed_deadband_kmh', mpc_cfg.get('lower_ref_deadband_kmh', args.exec_deadband_kmh)),
        )
    )
    args.exec_quantize_step_kmh = float(
        exec_cfg.get('quantize_step_kmh', command_bridge_cfg.get('speed_quantize_step_kmh', args.exec_quantize_step_kmh))
    )
    args.exec_reaction_delay_sec = float(exec_cfg.get('reaction_delay_sec', args.exec_reaction_delay_sec))

    output_dir = sim_cfg.get('output_dir', os.path.join('outputs', 'prerace'))
    output_prefix = str(sim_cfg.get('output_prefix', logging_cfg.get('file_prefix', 'solar_prerace')))
    if force_output_defaults or not args.out_csv:
        args.out_csv = tag_output_path(os.path.join(output_dir, f'{output_prefix}.csv'), output_tag, '.csv')
    if force_output_defaults or not args.out_detail_csv:
        detail_csv = str(sim_cfg.get('out_detail_csv', '') or '')
        args.out_detail_csv = (
            tag_output_path(detail_csv, output_tag, '.csv')
            if detail_csv else
            tag_output_path(os.path.join(output_dir, f'{output_prefix}_detail.csv'), output_tag, '.csv')
        )
    if force_output_defaults or not args.out_plan_csv:
        plan_csv = str(sim_cfg.get('out_plan_csv', '') or '')
        args.out_plan_csv = (
            tag_output_path(plan_csv, output_tag, '.csv')
            if plan_csv else
            tag_output_path(os.path.join(output_dir, f'{output_prefix}_upper_plan.csv'), output_tag, '.csv')
        )
    if force_output_defaults or not args.report_html:
        report_html = str(sim_cfg.get('report_html', '') or '')
        args.report_html = (
            tag_output_path(report_html, output_tag, '.html')
            if report_html else
            tag_output_path(os.path.join(output_dir, f'{output_prefix}_report.html'), output_tag, '.html')
        )
    if force_output_defaults or not args.summary_json:
        summary_json = str(sim_cfg.get('summary_json', '') or '')
        args.summary_json = (
            tag_output_path(summary_json, output_tag, '.json')
            if summary_json else
            tag_output_path(os.path.join(output_dir, f'{output_prefix}_summary.json'), output_tag, '.json')
        )
    if force_output_defaults or not args.resolved_yaml:
        resolved_yaml = str(sim_cfg.get('resolved_yaml', '') or '')
        args.resolved_yaml = (
            tag_output_path(resolved_yaml, output_tag, '.yaml')
            if resolved_yaml else
            tag_output_path(os.path.join(output_dir, f'{output_prefix}_resolved.yaml'), output_tag, '.yaml')
        )
    latest_manifest_json = str(sim_cfg.get('latest_manifest_json', '') or '')
    if force_output_defaults or not getattr(args, 'latest_manifest_json', ''):
        args.latest_manifest_json = (
            os.path.normpath(latest_manifest_json)
            if latest_manifest_json else
            os.path.normpath(os.path.join(output_dir, 'latest_simulation_run.json'))
        )

    args.out_csv = os.path.normpath(args.out_csv)
    args.out_detail_csv = os.path.normpath(args.out_detail_csv) if args.out_detail_csv else ''
    args.out_plan_csv = os.path.normpath(args.out_plan_csv) if args.out_plan_csv else ''
    args.report_html = os.path.normpath(args.report_html) if args.report_html else ''
    args.summary_json = os.path.normpath(args.summary_json) if args.summary_json else ''
    args.resolved_yaml = os.path.normpath(args.resolved_yaml) if args.resolved_yaml else ''
    args.latest_manifest_json = os.path.normpath(args.latest_manifest_json) if args.latest_manifest_json else ''


def apply_profile_defaults(args):
    if not args.profile_yaml:
        return {}
    profile_path, profile_cfg = load_workflow_profile(args.profile_yaml)
    apply_profile_cfg_to_args(profile_path, profile_cfg, args)
    return profile_cfg


def get_profile_val(df, s_km, field, default=0.0):
    if df is None or field not in df.columns:
        return float(default)
    val = float(interpolate_profile(df, s_km, field, default))
    if not math.isfinite(val):
        return float(default)
    return float(val)


def parse_utc_arg(raw_value: str):
    text = str(raw_value or '').strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def resolve_forecast_mode(mode: str, df: pd.DataFrame) -> str:
    raw = str(mode or 'auto').strip().lower()
    has_time = ('time' in df.columns) and (not df['time'].isna().all())
    if raw == 'auto':
        return 'absolute' if has_time else 'relative'
    if raw not in ('absolute', 'relative', 'loop'):
        return 'relative'
    if raw == 'absolute' and not has_time:
        return 'relative'
    return raw


def forecast_row_index(df: pd.DataFrame, sim_t: datetime, *, dt_sec: float, mode: str, forecast_start_time: datetime) -> int:
    if len(df) == 0:
        return 0
    if mode == 'absolute' and 'time' in df.columns and not df['time'].isna().all():
        t_min = df['time'].iloc[0]
        t_max = df['time'].iloc[-1]
        if t_min <= sim_t <= t_max:
            idx = int(df['time'].searchsorted(pd.Timestamp(sim_t), side='right') - 1)
            return int(np.clip(idx, 0, len(df) - 1))
        mode = 'relative'

    elapsed = max(0.0, (sim_t - forecast_start_time).total_seconds())
    idx = int(elapsed / max(dt_sec, 1.0e-3))
    if mode == 'loop':
        return int(idx % len(df))
    return int(np.clip(idx, 0, len(df) - 1))


def format_metric(value, digits=3, default='--'):
    if value is None:
        return default
    try:
        fval = float(value)
        if math.isfinite(fval):
            return f'{fval:.{digits}f}'
    except Exception:
        pass
    return default


def decimate_xy(xs, ys, max_points=600):
    pts = [(float(x), float(y)) for x, y in zip(xs, ys) if math.isfinite(float(y))]
    if len(pts) <= max_points:
        return pts
    step = max(1, int(math.ceil(len(pts) / max_points)))
    reduced = pts[::step]
    if reduced[-1] != pts[-1]:
        reduced.append(pts[-1])
    return reduced


def build_svg_chart(xs, ys, *, color='#135d66', width=920, height=220, pad=26, label=''):
    pts = decimate_xy(xs, ys, max_points=700)
    if not pts:
        return '<div class="chart-empty">no data</div>'
    x_vals = [p[0] for p in pts]
    y_vals = [p[1] for p in pts]
    x_min = min(x_vals)
    x_max = max(x_vals)
    y_min = min(y_vals)
    y_max = max(y_vals)
    if x_max <= x_min:
        x_max = x_min + 1.0
    if y_max <= y_min:
        span = 1.0 if abs(y_max) < 1.0 else abs(y_max) * 0.1
        y_min -= span
        y_max += span
    inner_w = max(10.0, width - 2 * pad)
    inner_h = max(10.0, height - 2 * pad)
    coords = []
    for x_val, y_val in pts:
        sx = pad + (x_val - x_min) / (x_max - x_min) * inner_w
        sy = height - pad - (y_val - y_min) / (y_max - y_min) * inner_h
        coords.append(f'{sx:.2f},{sy:.2f}')
    polyline = ' '.join(coords)
    y_mid = 0.5 * (y_min + y_max)
    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img" aria-label="{html.escape(label)}">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="18" ry="18" fill="#fffdf8" stroke="#d8d1c4" />'
        f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{height - pad}" stroke="#a9a293" stroke-width="1" />'
        f'<line x1="{pad}" y1="{height - pad}" x2="{width - pad}" y2="{height - pad}" stroke="#a9a293" stroke-width="1" />'
        f'<polyline fill="none" stroke="{color}" stroke-width="2.6" points="{polyline}" />'
        f'<text x="{pad}" y="18" font-size="12" fill="#50483f">{html.escape(label)}</text>'
        f'<text x="{width - pad}" y="18" text-anchor="end" font-size="11" fill="#6f665b">{format_metric(y_max, 2)}</text>'
        f'<text x="{width - pad}" y="{height - 8}" text-anchor="end" font-size="11" fill="#6f665b">{format_metric(x_max, 1)}</text>'
        f'<text x="{pad}" y="{height - 8}" font-size="11" fill="#6f665b">{format_metric(x_min, 1)}</text>'
        f'<text x="{width - pad}" y="{height / 2:.1f}" text-anchor="end" font-size="11" fill="#6f665b">{format_metric(y_mid, 2)}</text>'
        f'<text x="{width - pad}" y="{height - pad + 16}" text-anchor="end" font-size="11" fill="#6f665b">x</text>'
        '</svg>'
    )


def flatten_params_for_report(cfg):
    rows = []

    def visit(prefix, value):
        if isinstance(value, dict):
            for key, child in value.items():
                child_prefix = f'{prefix}.{key}' if prefix else str(key)
                visit(child_prefix, child)
            return
        if isinstance(value, list):
            return
        rows.append((prefix, value))

    if not isinstance(cfg, dict):
        return rows
    for section_name in ('simulation', 'model', 'mpc', 'runtime'):
        visit(section_name, cfg.get(section_name, {}))
    return rows


def write_simulation_report(path, summary, detail_df, params_rows):
    ensure_parent_dir(path)
    x_index = list(range(len(detail_df)))
    speed_exec_present = 'v_exec_kmh' in detail_df.columns
    speed_series = detail_df.get('v_exec_kmh', detail_df.get('v_cmd_kmh', pd.Series(dtype=float)))
    speed_svg = build_svg_chart(
        x_index,
        speed_series,
        color='#0f766e',
        label='speed exec [km/h]' if speed_exec_present else 'speed cmd [km/h]',
    )
    speed_cmd_svg = ''
    if speed_exec_present:
        speed_cmd_svg = build_svg_chart(
            x_index,
            detail_df.get('v_cmd_kmh', pd.Series(dtype=float)),
            color='#475569',
            label='speed cmd [km/h]',
        )
    soc_svg = build_svg_chart(x_index, detail_df.get('soc', pd.Series(dtype=float)), color='#b45309', label='soc [-]')
    pack_svg = build_svg_chart(x_index, detail_df.get('P_pack', pd.Series(dtype=float)), color='#b91c1c', label='pack power [W]')
    solar_svg = build_svg_chart(x_index, detail_df.get('P_pv', pd.Series(dtype=float)), color='#2563eb', label='pv power [W]')
    wind_svg = build_svg_chart(x_index, detail_df.get('headwind_ms', pd.Series(dtype=float)), color='#7c3aed', label='headwind [m/s]')
    slope_svg = build_svg_chart(x_index, detail_df.get('slope_pct', pd.Series(dtype=float)), color='#57534e', label='slope [%]')

    summary_cards = [
        ('Finish reached', 'yes' if summary.get('finish_reached') else 'no'),
        ('Final distance [km]', format_metric(summary.get('final_distance_km'), 1)),
        ('Race progress [%]', format_metric(summary.get('race_progress_pct'), 1)),
        ('Final SoC [-]', format_metric(summary.get('final_soc'), 3)),
        ('Min SoC [-]', format_metric(summary.get('min_soc'), 3)),
        ('Avg speed [km/h]', format_metric(summary.get('avg_speed_kmh'), 1)),
        ('Elapsed [h]', format_metric(summary.get('elapsed_hours'), 2)),
        ('Exec model', 'on' if summary.get('execution_model_enabled') else 'off'),
        ('Mean |v_cmd-v_exec| [km/h]', format_metric(summary.get('mean_tracking_error_kmh'), 2)),
        ('P95 |v_cmd-v_exec| [km/h]', format_metric(summary.get('p95_tracking_error_kmh'), 2)),
        ('Forecast mode', str(summary.get('forecast_mode', '--'))),
        ('Overrides', str(summary.get('override_count', 0))),
    ]
    overrides_html = ''.join(
        f'<tr><td>{html.escape(str(item.get("key")))}</td><td><code>{html.escape(json.dumps(item.get("value"), ensure_ascii=False))}</code></td></tr>'
        for item in summary.get('overrides', [])
    ) or '<tr><td colspan="2">none</td></tr>'
    params_html = ''.join(
        f'<tr><td>{html.escape(str(key))}</td><td>{html.escape(str(value))}</td></tr>'
        for key, value in params_rows
    )
    cards_html = ''.join(
        f'<div class="metric"><div class="metric-label">{html.escape(label)}</div><div class="metric-value">{html.escape(str(value))}</div></div>'
        for label, value in summary_cards
    )
    charts = [speed_svg]
    if speed_cmd_svg:
        charts.append(speed_cmd_svg)
    charts.extend([soc_svg, pack_svg, solar_svg, wind_svg, slope_svg])
    charts_html = ''.join(charts)
    warning_text = html.escape(str(summary.get('warning', '')))
    html_text = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Solar Simulation Report</title>
  <style>
    body {{ margin: 0; font-family: "Segoe UI", sans-serif; background: #f5efe3; color: #1f2933; }}
    .wrap {{ max-width: 1180px; margin: 0 auto; padding: 24px; }}
    .hero {{ background: linear-gradient(135deg, #fffaf0, #efe6d2); border: 1px solid #d9cfbd; border-radius: 24px; padding: 22px; }}
    h1, h2 {{ margin: 0 0 12px; }}
    p {{ margin: 8px 0; }}
    .muted {{ color: #625a4e; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 18px; }}
    .metric {{ background: #fffdf8; border: 1px solid #ddd2be; border-radius: 18px; padding: 14px; }}
    .metric-label {{ font-size: 12px; color: #6f665b; text-transform: uppercase; letter-spacing: 0.06em; }}
    .metric-value {{ margin-top: 6px; font-size: 24px; font-weight: 700; }}
    .section {{ margin-top: 20px; background: #fffaf2; border: 1px solid #ddd2be; border-radius: 24px; padding: 18px; }}
    .charts {{ display: grid; grid-template-columns: 1fr; gap: 16px; }}
    .chart-svg {{ width: 100%; height: auto; display: block; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #e6ddcf; padding: 8px 10px; text-align: left; vertical-align: top; }}
    th {{ font-size: 12px; color: #6f665b; text-transform: uppercase; letter-spacing: 0.06em; }}
    code {{ font-family: Consolas, monospace; font-size: 12px; }}
    .warning {{ margin-top: 10px; padding: 12px; border-radius: 14px; background: #fff0e1; color: #8a3b12; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>Solar Simulation Report</h1>
      <p class="muted">profile: {html.escape(str(summary.get('profile_name', '--')))} | generated: {html.escape(str(summary.get('generated_at_utc', '--')))}</p>
      <p class="muted">csv: {html.escape(str(summary.get('out_csv', '--')))} | detail: {html.escape(str(summary.get('detail_csv', '--')))}</p>
      {f'<div class="warning">{warning_text}</div>' if warning_text else ''}
      <div class="grid">{cards_html}</div>
    </div>

    <div class="section">
      <h2>Key Charts</h2>
      <div class="charts">
        {charts_html}
      </div>
    </div>

    <div class="section">
      <h2>Overrides</h2>
      <table>
        <thead><tr><th>key</th><th>value</th></tr></thead>
        <tbody>{overrides_html}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>Resolved Parameters</h2>
      <table>
        <thead><tr><th>parameter</th><th>value</th></tr></thead>
        <tbody>{params_html}</tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_text)


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

            z_next = model.soc_step(z, P_pack, p.dt)
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
    x_best = res.x if np.all(np.isfinite(res.x)) else x0
    v0_kmh = float(x_best[0]) * 3.6
    return float(np.clip(v0_kmh, 0.0, v_max_kmh))


def soc_guard_speed(model, v_kmh, z, Tb, s_km, d0, route_profile, mode, soc_guard):
    mode = str(mode).lower()
    target = model.p.soc_min + soc_guard
    slope_pct = get_profile_val(route_profile, s_km, 'slope_pct', d0.get('slope_pct', 0.0))
    headwind_ms = d0.get('headwind_ms', 0.0)

    def z_next_for(v_kmh_local):
        out = model.electrical_balance(v_kmh_local / 3.6, slope_pct, z, Tb, d0['G_poa'], d0['Tcell_C'], headwind_ms=headwind_ms)
        P_pack = float(out['P_pack'])
        return model.soc_step(z, P_pack, model.p.dt)

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
        return model.soc_step(z, P_pack, model.p.dt)

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
    ap.add_argument('--profile_yaml', default='')
    ap.add_argument('--forecast_csv', default='')
    ap.add_argument('--forecast_fill_csv', default='')
    ap.add_argument('--progress_reference_csv', default='')
    ap.add_argument('--forecast_time_mode', default='auto')
    ap.add_argument('--forecast_time_tz', default='UTC')
    ap.add_argument('--forecast_start_time_utc', default='')
    ap.add_argument('--route_profile_csv', default='')
    ap.add_argument('--speed_profile_csv', required=False, default='')
    ap.add_argument('--params_yaml', default='')
    ap.add_argument('--stop_yaml', default='')
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
    ap.add_argument('--out_csv', default='')
    ap.add_argument('--out_detail_csv', default='')
    ap.add_argument('--report_html', default='')
    ap.add_argument('--summary_json', default='')
    ap.add_argument('--resolved_yaml', default='')
    ap.add_argument('--latest_manifest_json', default='')
    ap.add_argument('--override', action='append', default=[])
    ap.add_argument('--soc_guard_margin', type=float, default=0.01)
    ap.add_argument('--soc_guard_mode', default='stop')
    ap.add_argument('--solar_gain', type=float, default=1.0)
    ap.add_argument('--poa_gain_drive', type=float, default=1.0)
    ap.add_argument('--poa_gain_stop', type=float, default=1.0)
    ap.add_argument('--energy_budget', action='store_true')
    ap.add_argument('--exec_model_enabled', action='store_true')
    ap.add_argument('--exec_inner_dt_sec', type=float, default=1.0)
    ap.add_argument('--exec_tau_sec', type=float, default=1.0)
    ap.add_argument('--exec_accel_limit_kmhps', type=float, default=1.5)
    ap.add_argument('--exec_decel_limit_kmhps', type=float, default=4.0)
    ap.add_argument('--exec_deadband_kmh', type=float, default=0.0)
    ap.add_argument('--exec_quantize_step_kmh', type=float, default=0.0)
    ap.add_argument('--exec_reaction_delay_sec', type=float, default=0.0)
    ap.add_argument('--upper_mode', default='time')
    ap.add_argument('--upper_ds_km', type=float, default=20.0)
    ap.add_argument('--upper_horizon_km', type=float, default=3000.0)
    ap.add_argument('--upper_max_steps', type=int, default=200)
    ap.add_argument('--upper_horizon_mode', default='fixed')
    ap.add_argument('--upper_adaptive_min_ds_km', type=float, default=10.0)
    ap.add_argument('--upper_adaptive_max_ds_km', type=float, default=200.0)
    ap.add_argument('--upper_adaptive_growth', type=float, default=1.18)
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
    explicit_output_args = {
        'out_csv': args.out_csv,
        'out_detail_csv': args.out_detail_csv,
        'out_plan_csv': args.out_plan_csv,
        'report_html': args.report_html,
        'summary_json': args.summary_json,
        'resolved_yaml': args.resolved_yaml,
        'latest_manifest_json': args.latest_manifest_json,
    }

    profile_cfg = apply_profile_defaults(args)
    resolved_profile_cfg = _deep_copy_cfg(profile_cfg)
    applied_overrides = []
    if resolved_profile_cfg and args.override:
        resolved_profile_cfg, applied_overrides = apply_overrides(resolved_profile_cfg, args.override)
        profile_path, _ = load_workflow_profile(args.profile_yaml)
        apply_profile_cfg_to_args(profile_path, resolved_profile_cfg, args, force_output_defaults=True)
        for key, value in explicit_output_args.items():
            if value:
                setattr(args, key, value)

    if not args.params_yaml:
        raise ValueError('Either --profile_yaml or --params_yaml is required.')
    if not args.forecast_csv or not args.route_profile_csv or not args.stop_yaml:
        raise ValueError('forecast_csv, route_profile_csv, and stop_yaml must be provided.')

    tzname = str(args.forecast_time_tz or 'UTC')
    df = load_forecast_dataframe(args.forecast_csv, tzname)
    if args.forecast_fill_csv:
        try:
            df_fill = load_forecast_dataframe(args.forecast_fill_csv, tzname)
            before_rows = len(df)
            df = merge_forecast_dataframes(df, df_fill)
            sim_log(
                f"forecast fill applied: primary_rows={before_rows} fallback_rows={len(df_fill)} merged_rows={len(df)}"
            )
        except Exception as exc:
            sim_log(f"forecast fill skipped: {exc}")
    forecast_time_ns = None
    forecast_grid = build_forecast_grid_payload(df)
    forecast_native_dt_sec = float(args.dt)
    forecast_start_data_utc = None
    forecast_end_data_utc = None
    forecast_coverage_end_utc = None
    if forecast_grid is not None and len(forecast_grid.get('time_ns', [])) > 0:
        forecast_time_ns = np.array(forecast_grid['time_ns'], dtype=np.int64)
        forecast_start_data_utc = pd.Timestamp(forecast_time_ns[0], unit='ns', tz='UTC').to_pydatetime()
        forecast_end_data_utc = pd.Timestamp(forecast_time_ns[-1], unit='ns', tz='UTC').to_pydatetime()
        if len(forecast_time_ns) >= 2:
            diff_sec = np.diff(forecast_time_ns).astype(np.float64) / 1.0e9
            diff_sec = diff_sec[diff_sec > 0.0]
            if diff_sec.size > 0:
                forecast_native_dt_sec = float(np.median(diff_sec))
        forecast_coverage_end_utc = forecast_end_data_utc + timedelta(seconds=max(forecast_native_dt_sec, 1.0))
        sim_log(
            'forecast grid mode enabled: '
            f'time_samples={len(forecast_time_ns)} '
            f'distance_samples={len(forecast_grid.get("s_grid", []))}'
        )
    elif 'time' in df.columns and df['time'].notna().any():
        forecast_time_ns = np.array([timestamp_ns(value) for value in df['time']], dtype=np.int64)
        forecast_start_data_utc = df['time'].iloc[0].to_pydatetime()
        forecast_end_data_utc = df['time'].iloc[-1].to_pydatetime()
        if len(df) >= 2:
            diff_sec = np.diff(forecast_time_ns).astype(np.float64) / 1.0e9
            diff_sec = diff_sec[diff_sec > 0.0]
            if diff_sec.size > 0:
                forecast_native_dt_sec = float(np.median(diff_sec))
        forecast_coverage_end_utc = forecast_end_data_utc + timedelta(seconds=max(forecast_native_dt_sec, 1.0))
    route_profile = load_csv_profile(args.route_profile_csv)
    speed_profile = load_csv_profile(args.speed_profile_csv)
    stops = load_stops(args.stop_yaml)
    schedule = DriveSchedule.from_yaml(args.drive_schedule_yaml) if args.drive_schedule_yaml else None
    progress_ref_df = load_progress_reference_dataframe(args.progress_reference_csv)
    progress_ref_time_ns = None
    if progress_ref_df is not None and not progress_ref_df.empty:
        progress_ref_time_ns = np.array([timestamp_ns(value) for value in progress_ref_df['time_utc']], dtype=np.int64)
    sim_log(f"loaded inputs: forecast_rows={len(df)} route={args.route_profile_csv}")

    cfg = load_yaml(args.params_yaml)
    if not cfg and resolved_profile_cfg:
        cfg = resolved_profile_cfg
    elif args.override:
        cfg, cfg_override_entries = apply_overrides(cfg, args.override)
        if not applied_overrides:
            applied_overrides = cfg_override_entries
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
    upper_horizon_mode = str(cfg.get('mpc', {}).get('upper_horizon_mode', args.upper_horizon_mode)).lower()
    upper_adaptive_min_ds_km = float(cfg.get('mpc', {}).get('upper_adaptive_min_ds_km', args.upper_adaptive_min_ds_km))
    upper_adaptive_max_ds_km = float(cfg.get('mpc', {}).get('upper_adaptive_max_ds_km', args.upper_adaptive_max_ds_km))
    upper_adaptive_growth = float(cfg.get('mpc', {}).get('upper_adaptive_growth', args.upper_adaptive_growth))
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
    ref_speed_cfg = cfg.get('mpc', {}).get('reference_speed_tracking', {}) if isinstance(cfg.get('mpc', {}).get('reference_speed_tracking', {}), dict) else {}
    ref_speed_tracking_enabled = bool(ref_speed_cfg.get('enabled', False))
    ref_speed_tracking_gain = float(ref_speed_cfg.get('speed_gain', 1.0))
    ref_speed_tracking_lag_gain = float(ref_speed_cfg.get('lag_gain_kmh_per_km', 0.0))
    ref_speed_tracking_lead_gain = float(ref_speed_cfg.get('lead_gain_kmh_per_km', 0.0))
    ref_speed_tracking_max_correction = float(ref_speed_cfg.get('max_correction_kmh', 20.0))
    ref_speed_tracking_lookahead_sec = float(ref_speed_cfg.get('lookahead_sec', max(args.dt, 300.0)))
    upper_cost_cfg = load_upper_cost_config(
        cfg.get('mpc', {}) if isinstance(cfg, dict) else {},
        legacy={
            'w_dv': w_dv,
            'w_dv_limit': w_dv_limit,
            'w_T': w_T,
            'w_speed_limit': w_speed_limit,
            'w_current': w_current,
            'w_soc_day_max': w_soc_day_max,
            'w_soc_day_track': w_soc_day_track,
            'w_soc_terminal': w_soc_terminal,
        },
    )
    if ref_speed_tracking_enabled and (progress_ref_df is None or progress_ref_df.empty):
        ref_speed_tracking_enabled = False
    soc0_raw = float(args.soc0)
    args.soc0 = float(np.clip(soc0_raw, p.soc_min, p.soc_max))
    if abs(args.soc0 - soc0_raw) > 1.0e-9:
        sim_log(f"simulation.soc0 clipped from {soc0_raw:.4f} to {args.soc0:.4f} to satisfy [{p.soc_min:.4f}, {p.soc_max:.4f}]")
    soc_target = float(np.clip(soc_target, p.soc_min, p.soc_max))
    sim_log(f"resolved config: upper_mode={upper_mode} race_km={race_km:.1f} schedule={'yes' if schedule is not None else 'no'}")
    sim_log(f"upper cost active terms: {','.join(sorted(active_upper_cost_terms(upper_cost_cfg).keys()))}")
    if ref_speed_tracking_enabled:
        sim_log("reference speed tracking enabled")
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

    forecast_mode = resolve_forecast_mode(args.forecast_time_mode, df)

    # schedule / start time
    parsed_start_utc = parse_utc_arg(args.start_utc)
    if parsed_start_utc is not None:
        start_utc = parsed_start_utc
    else:
        if 'time' in df.columns and df['time'].notna().any():
            start_utc = df['time'].iloc[0].to_pydatetime()
        else:
            start_utc = datetime.now(timezone.utc)
    parsed_forecast_start_time = parse_utc_arg(args.forecast_start_time_utc)
    forecast_start_time = parsed_forecast_start_time if parsed_forecast_start_time is not None else start_utc
    if forecast_coverage_end_utc is None and len(df) > 0:
        forecast_coverage_end_utc = forecast_start_time + timedelta(seconds=len(df) * max(args.dt, 1.0))

    def integration_step_seconds():
        base_step = float(max(max(args.dt, 1.0), max(forecast_native_dt_sec, 1.0)))
        return max(60.0, base_step)

    def forecast_has_coverage(t_utc: datetime) -> bool:
        if len(df) == 0:
            return False
        if forecast_coverage_end_utc is not None and t_utc > forecast_coverage_end_utc:
            return False
        if forecast_mode == 'absolute' and forecast_start_data_utc is not None:
            return t_utc >= forecast_start_data_utc
        return t_utc >= forecast_start_time

    def integrate_drive_time_between(t_start_utc: datetime, t_end_utc: datetime) -> float:
        if t_end_utc <= t_start_utc:
            return 0.0
        if schedule is None:
            return (t_end_utc - t_start_utc).total_seconds()
        dt_sec = integration_step_seconds()
        total_sec = 0.0
        t_cursor = t_start_utc
        while t_cursor < t_end_utc:
            dt_local = min(dt_sec, max(0.0, (t_end_utc - t_cursor).total_seconds()))
            if dt_local <= 0.0:
                break
            if schedule.is_drive_time(t_cursor):
                total_sec += dt_local
            t_cursor += timedelta(seconds=dt_local)
        return total_sec

    def reference_value_at_time(t_utc: datetime, field: str) -> float | None:
        if progress_ref_df is None or progress_ref_time_ns is None or len(progress_ref_df) == 0:
            return None
        if field not in progress_ref_df.columns:
            return None
        ts_ns = timestamp_ns(t_utc)
        idx_hi = int(np.searchsorted(progress_ref_time_ns, ts_ns, side='left'))
        if idx_hi <= 0:
            return float(progress_ref_df[field].iloc[0])
        if idx_hi >= len(progress_ref_df):
            return float(progress_ref_df[field].iloc[-1])
        idx_lo = idx_hi - 1
        t0_ns = int(progress_ref_time_ns[idx_lo])
        t1_ns = int(progress_ref_time_ns[idx_hi])
        s0 = float(progress_ref_df[field].iloc[idx_lo])
        s1 = float(progress_ref_df[field].iloc[idx_hi])
        if t1_ns <= t0_ns:
            return s1
        alpha = float((ts_ns - t0_ns) / max(t1_ns - t0_ns, 1))
        alpha = max(0.0, min(1.0, alpha))
        return s0 + alpha * (s1 - s0)

    def reference_distance_at_time(t_utc: datetime) -> float | None:
        return reference_value_at_time(t_utc, 's_km')

    z = args.soc0
    Tb = args.Tb0
    s_km = 0.0
    v_cmd = args.v0_kmh
    v_exec = args.v0_kmh
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
                if 'v_exec_kmh' in df_resume.columns:
                    v_exec = float(row['v_exec_kmh'])
                else:
                    v_exec = float(v_cmd)
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
        return forecast_row_index(
            df,
            dt_utc,
            dt_sec=args.dt,
            mode=forecast_mode,
            forecast_start_time=forecast_start_time,
        )

    if args.start_index >= 0:
        k = int(min(max(args.start_index, 0), len(df) - 1))
    else:
        k = time_to_index(sim_t)
    stop_queue = sorted(stops, key=lambda item: float(item.get('s_km', 0.0)))
    next_stop_idx = 0
    for i, stop_item in enumerate(stop_queue):
        if s_km < float(stop_item.get('s_km', 0.0)):
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
    coverage_end_for_progress = forecast_coverage_end_utc if forecast_coverage_end_utc is not None else (start_utc + timedelta(seconds=max(args.dt, 1.0)))
    total_drive_sec = integrate_drive_time_between(start_utc, coverage_end_for_progress)
    if total_drive_sec <= 0.0:
        total_drive_sec = max((coverage_end_for_progress - start_utc).total_seconds(), 1.0)
    drive_time_elapsed = 0.0
    t_start = time.perf_counter()
    exec_model_enabled = bool(args.exec_model_enabled)
    exec_inner_dt_sec = max(0.05, float(args.exec_inner_dt_sec))
    exec_tau_sec = max(0.0, float(args.exec_tau_sec))
    exec_accel_limit_kmhps = float(args.exec_accel_limit_kmhps)
    exec_decel_limit_kmhps = float(args.exec_decel_limit_kmhps)
    exec_deadband_kmh = max(0.0, float(args.exec_deadband_kmh))
    exec_quantize_step_kmh = max(0.0, float(args.exec_quantize_step_kmh))
    exec_reaction_delay_sec = max(0.0, float(args.exec_reaction_delay_sec))
    exec_sim_time_sec = 0.0
    exec_target_kmh = float(v_exec)
    exec_delay_queue = deque()
    exec_limiter = None
    if exec_model_enabled:
        exec_limiter = SmoothRateLimiter(
            min_value=0.0,
            max_value=v_max_kmh,
            tau_sec=exec_tau_sec,
            rise_rate=exec_accel_limit_kmhps if exec_accel_limit_kmhps > 0.0 else None,
            fall_rate=exec_decel_limit_kmhps if exec_decel_limit_kmhps > 0.0 else None,
            deadband=exec_deadband_kmh,
            quantize_step=exec_quantize_step_kmh,
            initial_value=v_exec,
        )
        exec_limiter.reset(v_exec, now=0.0)
        sim_log(
            'execution model enabled: '
            f'dt_inner={exec_inner_dt_sec:.2f}s tau={exec_tau_sec:.2f}s '
            f'accel={exec_accel_limit_kmhps:.2f} decel={exec_decel_limit_kmhps:.2f} '
            f'delay={exec_reaction_delay_sec:.2f}s'
        )
    def remaining_day_budget(sim_t_local, _k_idx):
        if schedule is None or not schedule.is_drive_time(sim_t_local):
            return None, None
        win = schedule.current_drive_window(sim_t_local)
        if win is None:
            return None, None
        _, t_end = win
        dt_sample = integration_step_seconds()
        t = sim_t_local
        E_pv = 0.0
        t_remain = 0.0
        while t < t_end and forecast_has_coverage(t):
            dt_local = min(dt_sample, max(0.0, (t_end - t).total_seconds()))
            if dt_local <= 0.0:
                break
            env = forecast_at_time(t, s_km, drive=True)
            P_pv = float(model.pv_power_mppt(env['G_poa'], env['Tcell_C']))
            E_pv += P_pv * (dt_local / 3600.0)
            t_remain += dt_local
            t += timedelta(seconds=dt_local)
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

    def forecast_at_time(t_utc, s_query_km=None, drive=True):
        if len(df) == 0:
            return dict(G_raw=0.0, G_poa=0.0, Tcell_C=40.0, Tamb_C=30.0, headwind_ms=0.0)
        if forecast_grid is not None:
            gain = args.poa_gain_drive if drive else args.poa_gain_stop
            ghi = interp_forecast_grid(forecast_grid, 'GHI', t_utc, s_query_km, 0.0)
            tamb = interp_forecast_grid(forecast_grid, 'Tamb_C', t_utc, s_query_km, 30.0)
            tcell = interp_forecast_grid(forecast_grid, 'Tcell_C', t_utc, s_query_km, tamb)
            headwind = interp_forecast_grid(forecast_grid, 'headwind_ms', t_utc, s_query_km, 0.0)
            G_raw = float(ghi) * args.solar_gain
            return dict(
                G_raw=G_raw,
                G_poa=G_raw * gain,
                Tcell_C=float(tcell),
                Tamb_C=float(tamb),
                headwind_ms=float(headwind),
            )
        if forecast_time_ns is not None:
            idx = int(np.searchsorted(forecast_time_ns, timestamp_ns(t_utc)) - 1)
            idx = int(np.clip(idx, 0, len(df) - 1))
        else:
            elapsed = (t_utc - start_utc).total_seconds()
            idx = int(np.clip(elapsed / max(args.dt, 1e-3), 0, len(df) - 1))
        row = df.iloc[idx]
        gain = args.poa_gain_drive if drive else args.poa_gain_stop
        G_raw = float(row.get('GHI', 0.0)) * args.solar_gain
        return dict(
            G_raw=G_raw,
            G_poa=G_raw * gain,
            Tcell_C=float(row.get('Tcell_C', 40.0)),
            Tamb_C=float(row.get('Tamb_C', 30.0)),
            headwind_ms=float(row.get('headwind_ms', 0.0)),
        )

    def reference_speed_command(t_utc: datetime, s_now_km: float) -> float | None:
        if not ref_speed_tracking_enabled:
            return None
        ref_s_now = reference_distance_at_time(t_utc)
        if ref_s_now is None:
            return None
        base_speed_kmh = reference_value_at_time(t_utc, 'speed_kmh')
        if base_speed_kmh is None:
            t_future = t_utc + timedelta(seconds=max(ref_speed_tracking_lookahead_sec, 1.0))
            ref_s_future = reference_distance_at_time(t_future)
            if ref_s_future is not None:
                base_speed_kmh = max(0.0, (ref_s_future - ref_s_now) * 3600.0 / max(ref_speed_tracking_lookahead_sec, 1.0))
            else:
                base_speed_kmh = 0.0
        lag_km = max(0.0, float(ref_s_now) - float(s_now_km))
        lead_km = max(0.0, float(s_now_km) - float(ref_s_now))
        correction_kmh = ref_speed_tracking_lag_gain * lag_km - ref_speed_tracking_lead_gain * lead_km
        correction_kmh = float(np.clip(correction_kmh, -ref_speed_tracking_max_correction, ref_speed_tracking_max_correction))
        return max(0.0, float(base_speed_kmh) * ref_speed_tracking_gain + correction_kmh)

    def step_wait(t_utc, z, Tb, s_km):
        if schedule is None:
            return t_utc, z, Tb, 0.0
        if schedule.is_drive_time(t_utc):
            return t_utc, z, Tb, 0.0
        t_start = schedule.next_drive_start(t_utc)
        dt_wait = max(0.0, (t_start - t_utc).total_seconds())
        if dt_wait <= 0.0:
            return t_start, z, Tb, 0.0
        slope_pct = get_profile_val(route_profile, s_km, 'slope_pct', 0.0)
        dt_sample = integration_step_seconds()
        remaining = dt_wait
        t_cursor = t_utc
        z_cur = float(z)
        Tb_cur = float(Tb)
        while remaining > 1.0e-9 and forecast_has_coverage(t_cursor):
            dt_local = min(dt_sample, remaining)
            env = forecast_at_time(t_cursor, s_km, drive=False)
            headwind_ms = get_profile_val(route_profile, s_km, 'headwind_ms', env.get('headwind_ms', 0.0))
            out = model.electrical_balance(0.0, slope_pct, z_cur, Tb_cur, env['G_poa'], env['Tcell_C'], headwind_ms=headwind_ms)
            P_pack = float(out['P_pack'])
            loss_int = float(out['losses_int'])
            z_cur = model.soc_step(z_cur, P_pack, dt_local)
            Tb_cur = Tb_cur + (dt_local / 1800.0) * (env['Tamb_C'] - Tb_cur) + (loss_int * dt_local) / 50000.0
            z_cur = float(np.clip(z_cur, p.soc_min, p.soc_max))
            Tb_cur = float(np.clip(Tb_cur, p.T_min, p.T_max))
            t_cursor += timedelta(seconds=dt_local)
            remaining -= dt_local
        return t_start, float(z_cur), float(Tb_cur), dt_wait

    def mpc_solve_distance(t0_utc, s0_km, z0, Tb0, v0_kmh, v_init=None):
        horizon = build_upper_distance_horizon(
            mode=upper_horizon_mode,
            s0_km=s0_km,
            race_km=race_km,
            ds_km=upper_ds_km,
            horizon_km=upper_horizon_km,
            max_steps=upper_max_steps,
            ctrl_km=upper_ctrl_km,
            adaptive_min_ds_km=upper_adaptive_min_ds_km,
            adaptive_max_ds_km=upper_adaptive_max_ds_km,
            adaptive_growth=upper_adaptive_growth,
        )
        ds_seq = np.array(horizon.ds_seq_km, dtype=float)
        seg_s = np.array(horizon.seg_s_km, dtype=float)
        Np = int(len(ds_seq))
        if Np <= 0:
            return v0_kmh, [{'v_kmh': v0_kmh, 'dt_sec': args.dt}], np.array([v0_kmh], dtype=float)

        v_min_solver = max(0.1, float(upper_vmin_kmh))
        ctrl_s = np.array(horizon.ctrl_s_km, dtype=float)
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

        def cost(u_vec):
            z = float(z0)
            Tb = float(Tb0)
            s_km = float(s0_km)
            t_utc = t0_utc
            v_prev = float(v0_kmh)
            p_pack_prev = None
            elapsed_plan_sec = 0.0
            J = 0.0
            v_seq = expand_ctrl(u_vec)
            for k_i in range(Np):
                t_utc, z, Tb, dt_wait = step_wait(t_utc, z, Tb, s_km)
                v_k = float(v_seq[k_i])
                ds_step_km = float(ds_seq[k_i])
                vmax_local = get_profile_val(speed_profile, s_km, 'v_max_kmh', v_max_kmh)
                if vmax_local >= v_min_solver:
                    v_k = max(v_min_solver, min(v_k, vmax_local))
                else:
                    v_k = max(0.0, min(v_k, vmax_local))
                limits = None
                if schedule is not None:
                    limits = schedule.speed_limits(t_utc)

                dt_travel = ds_step_km / max(v_k, 1.0e-3) * 3600.0
                env = forecast_at_time(t_utc, s_km, drive=True)
                slope_pct = get_profile_val(route_profile, s_km, 'slope_pct', 0.0)
                headwind_ms = get_profile_val(route_profile, s_km, 'headwind_ms', env.get('headwind_ms', 0.0))
                out = model.electrical_balance(v_k / 3.6, slope_pct, z, Tb, env['G_poa'], env['Tcell_C'], headwind_ms=headwind_ms)
                I = float(out['I'])
                V = float(out['V'])
                P_pv = float(out.get('P_pv', 0.0))
                P_pack = float(out['P_pack'])
                loss_int = float(out['losses_int'])
                loss_line = float(out.get('losses_line', 0.0))
                P_mech_wheel = float(out.get('P_mech_wheel', 0.0))
                kinetic_step_wh = 0.5 * p.m * max(0.0, (v_k / 3.6) ** 2 - (v_prev / 3.6) ** 2) / 3600.0
                z_next = model.soc_step(z, P_pack, dt_travel)
                Tb_next = Tb + (dt_travel / 1800.0) * (env['Tamb_C'] - Tb) + (loss_int * dt_travel) / 50000.0
                forces = model.resistive_forces(v_k / 3.6, slope_pct, headwind_ms=headwind_ms)
                if schedule is not None and soc_day_end_target > 0.0:
                    win = schedule.current_drive_window(t_utc)
                    if win is not None:
                        t_start, t_end = win
                        if t_end > t_start:
                            prog = (t_utc - t_start).total_seconds() / (t_end - t_start).total_seconds()
                            prog = max(0.0, min(1.0, prog))
                            soc_line = z0 + (soc_day_end_target - z0) * prog
                        else:
                            soc_line = None
                    else:
                        soc_line = None
                else:
                    soc_line = None

                t_next = t_utc + timedelta(seconds=dt_travel)
                s_next_km = s_km + ds_step_km
                ref_s_next = reference_distance_at_time(t_next)
                progress_lag_km = max(0.0, float(ref_s_next) - s_next_km) if ref_s_next is not None else 0.0
                day_end_crossing = bool(
                    schedule is not None and schedule.is_drive_time(t_utc) and not schedule.is_drive_time(t_next)
                )
                elapsed_plan_sec += dt_wait + dt_travel
                J += upper_stage_cost(
                    upper_cost_cfg,
                    dt_wait=dt_wait,
                    dt_travel=dt_travel,
                    v_kmh=v_k,
                    v_prev_kmh=v_prev,
                    vmax_local_kmh=vmax_local,
                    drive_limits=limits,
                    dv_limit_kmhps=dv_max_kmhps,
                    I_a=I,
                    V_v=V,
                    P_pv_w=P_pv,
                    P_pack_w=P_pack,
                    P_pack_prev_w=p_pack_prev,
                    P_mech_wheel_w=P_mech_wheel,
                    losses_int_w=loss_int,
                    losses_line_w=loss_line,
                    F_aero_n=float(forces.get('F_aero', 0.0)),
                    kinetic_step_wh=kinetic_step_wh,
                    z_next=z_next,
                    Tb_next_c=Tb_next,
                    term_soc_min=term_soc_min,
                    soc_min=p.soc_min,
                    soc_max=p.soc_max,
                    temp_min_c=p.T_min,
                    temp_max_c=p.T_max,
                    day_end_soc_min=upper_day_end_soc_min,
                    day_end_crossing=day_end_crossing,
                    soc_day_end_max=soc_day_end_max,
                    soc_day_track_target=soc_line,
                    soc_day_track_tol=soc_day_end_tol,
                    I_max=p.I_max,
                    I_chg_min=p.I_chg_min,
                    V_min=p.V_min,
                    V_max=p.V_max,
                    time_ahead_h=elapsed_plan_sec / 3600.0,
                    progress_lag_km=progress_lag_km,
                )

                t_utc = t_next
                s_km = s_next_km
                z, Tb = z_next, Tb_next
                v_prev = v_k
                p_pack_prev = P_pack
            ref_s_terminal = reference_distance_at_time(t_utc)
            progress_terminal_lag_km = max(0.0, float(ref_s_terminal) - s_km) if ref_s_terminal is not None else 0.0
            J += upper_terminal_cost(
                upper_cost_cfg,
                z_terminal=z,
                term_soc_min=term_soc_min,
                soc_finish_target=soc_finish_target,
                progress_terminal_lag_km=progress_terminal_lag_km,
            )
            return J

        from scipy.optimize import minimize
        sim_log(f"upper solve start: s_km={s0_km:.1f} Np={Np} Nc={Nc} maxiter={upper_max_iter}")
        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=upper_max_iter))
        sim_log(f"upper solve done: success={bool(res.success)} nit={getattr(res, 'nit', -1)} fun={float(res.fun) if hasattr(res, 'fun') else float('nan'):.2f}")
        u_seq = res.x if np.all(np.isfinite(res.x)) else x0
        v_seq = expand_ctrl(u_seq)

        segments = []
        t_utc = t0_utc
        s_km = float(s0_km)
        z = float(z0)
        Tb = float(Tb0)
        for idx_seg, v_k in enumerate(v_seq):
            t_utc, z, Tb, _ = step_wait(t_utc, z, Tb, s_km)
            ds_step_km = float(ds_seq[idx_seg])
            v_k = float(np.clip(v_k, 0.0, v_max_kmh))
            vmax_local = get_profile_val(speed_profile, s_km, 'v_max_kmh', v_max_kmh)
            if vmax_local >= v_min_solver:
                v_k = max(v_min_solver, min(v_k, vmax_local))
            else:
                v_k = max(0.0, min(v_k, vmax_local))
            dt_travel = ds_step_km / max(v_k, 1.0e-3) * 3600.0
            segments.append(
                {
                    'v_kmh': v_k,
                    'dt_sec': float(dt_travel),
                    'ds_km': ds_step_km,
                    's_start_km': float(s_km),
                    's_end_km': float(s_km + ds_step_km),
                }
            )
            t_utc = t_utc + timedelta(seconds=dt_travel)
            s_km += ds_step_km
        v0 = float(segments[0]['v_kmh']) if segments else v0_kmh
        return v0, segments, u_seq

    def propagate_execution_step(cmd_kmh, z0, Tb0, s0_km, env, *, force_stop=False):
        nonlocal exec_sim_time_sec, exec_target_kmh, v_exec
        slope_pct = float(env['slope_pct'])
        headwind_ms = float(env['headwind_ms'])
        step_sec = max(1.0e-6, float(args.dt))
        cmd_kmh = float(np.clip(cmd_kmh, 0.0, v_max_kmh))
        if not exec_model_enabled:
            v_exec = cmd_kmh
            v_ms = v_exec / 3.6
            out = model.electrical_balance(v_ms, slope_pct, z0, Tb0, env['G_poa'], env['Tcell_C'], headwind_ms=headwind_ms)
            loss_int = float(out['losses_int'])
            z1 = z0 - (float(out['P_pack']) * step_sec / 3600.0) / model.p.E_nom_Wh
            Tb1 = Tb0 + (step_sec / 1800.0) * (env['Tamb_C'] - Tb0) + (loss_int * step_sec) / 50000.0
            z1 = float(np.clip(z1, model.p.soc_min, model.p.soc_max))
            Tb1 = float(np.clip(Tb1, model.p.T_min, model.p.T_max))
            s1 = s0_km + v_exec * (step_sec / 3600.0)
            forces = model.resistive_forces(v_ms, slope_pct, headwind_ms=headwind_ms)
            return z1, Tb1, s1, {
                'v_exec_kmh': float(v_exec),
                'v_exec_target_kmh': float(cmd_kmh),
                'v_exec_ms': float(v_ms),
                'out': out,
                'forces': forces,
            }

        if force_stop or cmd_kmh <= 0.1:
            exec_delay_queue.clear()
            exec_delay_queue.append((exec_sim_time_sec, 0.0))
        else:
            exec_delay_queue.append((exec_sim_time_sec + exec_reaction_delay_sec, cmd_kmh))

        z = float(z0)
        Tb = float(Tb0)
        s = float(s0_km)
        remaining = step_sec
        sum_v_exec_dt = 0.0
        sum_v_target_dt = 0.0
        sum_metrics = {
            'P_pv': 0.0,
            'P_mech': 0.0,
            'P_mech_wheel': 0.0,
            'P_dc_to_drv': 0.0,
            'P_reg_to_dc': 0.0,
            'P_pack': 0.0,
            'I': 0.0,
            'V': 0.0,
            'OCV': 0.0,
            'Rint': 0.0,
            'Rline': 0.0,
            'losses_int': 0.0,
            'losses_line': 0.0,
            'eff_drv': 0.0,
            'eff_reg': 0.0,
            'F_aero': 0.0,
            'F_roll': 0.0,
            'F_grade': 0.0,
            'F_total': 0.0,
        }

        while remaining > 1.0e-9:
            dt_sub = min(exec_inner_dt_sec, remaining)
            while exec_delay_queue and float(exec_delay_queue[0][0]) <= exec_sim_time_sec + 1.0e-9:
                _, delayed_cmd = exec_delay_queue.popleft()
                exec_target_kmh = float(np.clip(delayed_cmd, 0.0, v_max_kmh))
            v_exec = float(exec_limiter.update(exec_target_kmh, now=exec_sim_time_sec))
            v_ms = v_exec / 3.6
            out = model.electrical_balance(v_ms, slope_pct, z, Tb, env['G_poa'], env['Tcell_C'], headwind_ms=headwind_ms)
            loss_int = float(out['losses_int'])
            forces = model.resistive_forces(v_ms, slope_pct, headwind_ms=headwind_ms)
            z = z - (float(out['P_pack']) * dt_sub / 3600.0) / model.p.E_nom_Wh
            Tb = Tb + (dt_sub / 1800.0) * (env['Tamb_C'] - Tb) + (loss_int * dt_sub) / 50000.0
            z = float(np.clip(z, model.p.soc_min, model.p.soc_max))
            Tb = float(np.clip(Tb, model.p.T_min, model.p.T_max))
            s += v_exec * (dt_sub / 3600.0)
            sum_v_exec_dt += v_exec * dt_sub
            sum_v_target_dt += exec_target_kmh * dt_sub
            for key in ('P_pv', 'P_mech', 'P_mech_wheel', 'P_dc_to_drv', 'P_reg_to_dc', 'P_pack', 'I', 'V', 'OCV', 'Rint', 'Rline', 'losses_int', 'losses_line', 'eff_drv', 'eff_reg'):
                sum_metrics[key] += float(out.get(key, 0.0)) * dt_sub
            for key in ('F_aero', 'F_roll', 'F_grade', 'F_total'):
                sum_metrics[key] += float(forces.get(key, 0.0)) * dt_sub
            exec_sim_time_sec += dt_sub
            remaining -= dt_sub

        denom = max(step_sec, 1.0e-9)
        avg_out = {key: float(value / denom) for key, value in sum_metrics.items() if key not in ('F_aero', 'F_roll', 'F_grade', 'F_total')}
        avg_forces = {key: float(sum_metrics[key] / denom) for key in ('F_aero', 'F_roll', 'F_grade', 'F_total')}
        return z, Tb, s, {
            'v_exec_kmh': float(sum_v_exec_dt / denom),
            'v_exec_target_kmh': float(sum_v_target_dt / denom),
            'v_exec_ms': float((sum_v_exec_dt / denom) / 3.6),
            'out': avg_out,
            'forces': avg_forces,
        }

    while s_km < race_km and forecast_has_coverage(sim_t):
        k = time_to_index(sim_t)
        if k % 20 == 0:
            sim_log(f"loop progress: k={k} s_km={s_km:.1f} soc={z:.3f} sim_t={sim_t.isoformat()}")
        v_prev_cmd = float(v_cmd)
        # build horizon data
        data = []
        for j in range(max(1, args.horizon_steps)):
            t_j = sim_t + timedelta(seconds=j * args.dt)
            drive_gain = True
            if schedule is not None:
                limits = schedule.speed_limits(t_j)
                if limits is not None and limits[1] <= 0.0:
                    drive_gain = False
            env_j = forecast_at_time(t_j, s_km, drive=drive_gain)
            data.append(dict(
                G_raw=float(env_j.get('G_raw', 0.0)),
                G_poa=float(env_j.get('G_poa', 0.0)),
                Tcell_C=float(env_j.get('Tcell_C', 40.0)),
                slope_pct=get_profile_val(route_profile, s_km, 'slope_pct', 0.0),
                Tamb_C=float(env_j.get('Tamb_C', 30.0)),
                headwind_ms=float(env_j.get('headwind_ms', 0.0)),
            ))

        ref_v_cmd = reference_speed_command(sim_t, s_km)
        if ref_v_cmd is not None:
            v_cmd = float(ref_v_cmd)
        elif upper_mode == 'distance':
            need_plan = plan_segments is None
            if not need_plan and upper_replan_km > 0.0 and (s_km - last_plan_s_km) >= upper_replan_km:
                need_plan = True
            if not need_plan and upper_replan_sec > 0.0:
                if (sim_t - last_plan_time).total_seconds() >= upper_replan_sec:
                    need_plan = True
            if not need_plan and plan_segments is not None:
                idx = plan_segment_index(plan_segments, s_km)
                if idx < 0 or s_km >= float(plan_segments[-1].get('s_end_km', s_km)):
                    need_plan = True
            if (
                need_plan
                and schedule is not None
                and plan_segments is not None
                and not schedule.is_drive_time(sim_t)
                and s_km < float(plan_segments[-1].get('s_end_km', s_km))
            ):
                need_plan = False
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
                            float(seg.get('s_end_km', s_km)),
                            float(seg['v_kmh']),
                            float(seg['dt_sec']),
                        ])
            if plan_segments is not None:
                idx = plan_segment_index(plan_segments, s_km)
                if idx >= 0:
                    v_cmd = float(plan_segments[idx]['v_kmh'])
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
        if next_stop_idx < len(stop_queue) and s_km >= float(stop_queue[next_stop_idx].get('s_km', 0.0)):
            stop_timer = max(stop_timer, float(stop_queue[next_stop_idx].get('dwell_sec', 1800.0)))
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

        s_step_km = float(s_km)
        z_step = float(z)
        Tb_step = float(Tb)
        z, Tb, s_km, exec_metrics = propagate_execution_step(v_cmd, z, Tb, s_km, data[0], force_stop=hard_stop)
        out = exec_metrics['out']
        forces = exec_metrics['forces']
        v_exec_step_kmh = float(exec_metrics['v_exec_kmh'])
        v_exec_target_step_kmh = float(exec_metrics['v_exec_target_kmh'])
        v_exec_step_ms = float(exec_metrics['v_exec_ms'])
        detail_log.append([
            sim_t.isoformat(),
            s_step_km,
            v_cmd,
            v_exec_step_kmh,
            v_exec_target_step_kmh,
            v_cmd / 3.6,
            v_exec_step_ms,
            z_step,
            Tb_step,
            data[0]['slope_pct'],
            data[0]['headwind_ms'],
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

        log.append([sim_t.isoformat(), s_km, v_cmd, v_exec_step_kmh, z, Tb, data[0]['G_poa'], data[0]['Tamb_C'], data[0]['headwind_ms']])
        # plan_log is appended only when a new plan is generated
        sim_t += timedelta(seconds=args.dt)

        if s_km >= race_km:
            break

    t_end = time.perf_counter()
    ensure_parent_dir(args.out_csv)
    out_df = pd.DataFrame(log, columns=['time_utc', 's_km', 'v_cmd_kmh', 'v_exec_kmh', 'soc', 'Tb_C', 'G_poa', 'Tamb_C', 'headwind_ms'])
    tzname = str(args.forecast_time_tz or 'UTC')
    try:
        local_tz = ZoneInfo(tzname) if tzname.upper() != 'UTC' else ZoneInfo('UTC')
        out_df['time_local'] = pd.to_datetime(out_df['time_utc'], utc=True, errors='coerce').dt.tz_convert(local_tz)
    except Exception:
        pass
    out_df.to_csv(args.out_csv, index=False)
    detail_df = pd.DataFrame()
    if detail_log:
        detail_csv = args.out_detail_csv or args.out_csv.replace('.csv', '_detail.csv')
        ensure_parent_dir(detail_csv)
        detail_df = pd.DataFrame(detail_log, columns=[
            'time_utc', 's_km', 'v_cmd_kmh', 'v_exec_kmh', 'v_exec_target_kmh', 'v_cmd_ms', 'v_exec_ms', 'soc', 'Tb_C',
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
    else:
        detail_csv = args.out_detail_csv or args.out_csv.replace('.csv', '_detail.csv')
    if upper_mode == 'distance':
        plan_csv = args.out_plan_csv or args.out_csv.replace('.csv', '_upper_plan.csv')
        ensure_parent_dir(plan_csv)
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
    else:
        plan_csv = args.out_plan_csv or args.out_csv.replace('.csv', '_upper_plan.csv')

    if args.resolved_yaml:
        ensure_parent_dir(args.resolved_yaml)
        resolved_payload = _deep_copy_cfg(cfg)
        meta_cfg = resolved_payload.setdefault('meta', {})
        if isinstance(meta_cfg, dict):
            meta_cfg['sim_generated_utc'] = datetime.now(timezone.utc).isoformat()
        sim_cfg = resolved_payload.setdefault('simulation', {})
        if isinstance(sim_cfg, dict):
            sim_cfg['resolved_out_csv'] = args.out_csv
            sim_cfg['resolved_out_detail_csv'] = detail_csv
            sim_cfg['resolved_out_plan_csv'] = plan_csv
            sim_cfg['resolved_report_html'] = args.report_html
            sim_cfg['resolved_summary_json'] = args.summary_json
        if applied_overrides:
            resolved_payload['simulation_overrides'] = applied_overrides
        with open(args.resolved_yaml, 'w', encoding='utf-8') as f:
            yaml.safe_dump(resolved_payload, f, sort_keys=False, allow_unicode=True)

    finish_reached = bool(s_km >= race_km)
    elapsed_hours = (len(log) * args.dt) / 3600.0 if log else 0.0
    avg_speed_kmh = (s_km / elapsed_hours) if elapsed_hours > 0.0 else 0.0
    if not detail_df.empty and 'v_exec_kmh' in detail_df.columns and 'v_cmd_kmh' in detail_df.columns:
        tracking_err = (detail_df['v_cmd_kmh'].astype(float) - detail_df['v_exec_kmh'].astype(float)).abs()
        mean_tracking_error_kmh = float(tracking_err.mean()) if len(tracking_err) else 0.0
        p95_tracking_error_kmh = float(tracking_err.quantile(0.95)) if len(tracking_err) else 0.0
    else:
        mean_tracking_error_kmh = 0.0
        p95_tracking_error_kmh = 0.0
    warning = ''
    if not log:
        warning = 'no simulation steps were emitted; check forecast_time_mode, start_utc, and forecast coverage.'
    elif not finish_reached:
        warning = 'finish not reached; the run ended before race_km or forecast coverage was exhausted.'
    summary = {
        'profile_name': str(cfg.get('meta', {}).get('name', 'simulation')) if isinstance(cfg, dict) else 'simulation',
        'profile_path': getattr(args, 'profile_path_resolved', ''),
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'start_utc': start_utc.isoformat(),
        'forecast_start_time_utc': forecast_start_time.isoformat(),
        'forecast_mode': forecast_mode,
        'output_tag': getattr(args, 'output_tag', ''),
        'finish_reached': finish_reached,
        'final_distance_km': float(s_km),
        'race_progress_pct': float(min(100.0, max(0.0, 100.0 * s_km / max(race_km, 1.0)))),
        'final_soc': float(out_df['soc'].iloc[-1]) if not out_df.empty else math.nan,
        'min_soc': float(out_df['soc'].min()) if not out_df.empty else math.nan,
        'final_tb_c': float(out_df['Tb_C'].iloc[-1]) if not out_df.empty else math.nan,
        'avg_speed_kmh': float(avg_speed_kmh),
        'elapsed_hours': float(elapsed_hours),
        'execution_model_enabled': bool(exec_model_enabled),
        'execution_inner_dt_sec': float(exec_inner_dt_sec if exec_model_enabled else args.dt),
        'mean_tracking_error_kmh': float(mean_tracking_error_kmh),
        'p95_tracking_error_kmh': float(p95_tracking_error_kmh),
        'cpu_sec': float(t_end - t_start),
        'rows': int(len(out_df)),
        'detail_rows': int(len(detail_df)),
        'override_count': int(len(applied_overrides)),
        'overrides': applied_overrides,
        'out_csv': args.out_csv,
        'detail_csv': detail_csv,
        'plan_csv': plan_csv,
        'report_html': args.report_html,
        'resolved_yaml': args.resolved_yaml,
        'latest_manifest_json': args.latest_manifest_json,
        'warning': warning,
    }
    if args.summary_json:
        ensure_parent_dir(args.summary_json)
        with open(args.summary_json, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    if args.latest_manifest_json:
        ensure_parent_dir(args.latest_manifest_json)
        with open(args.latest_manifest_json, 'w', encoding='utf-8') as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
    if args.report_html:
        write_simulation_report(args.report_html, summary, detail_df, flatten_params_for_report(cfg))
    print(f'log saved: {args.out_csv}')
    if args.report_html:
        print(f'report saved: {args.report_html}')
    if args.summary_json:
        print(f'summary saved: {args.summary_json}')
    if args.resolved_yaml:
        print(f'resolved config saved: {args.resolved_yaml}')
    if args.latest_manifest_json:
        print(f'latest manifest saved: {args.latest_manifest_json}')
    if log:
        total_time_h = elapsed_hours
        print(f'total_time_h: {total_time_h:.2f}')
        print(f'avg_speed_kmh: {avg_speed_kmh:.2f}')
        print(f'min_soc: {out_df["soc"].min():.3f}')
        print(f'cpu_sec: {t_end - t_start:.2f}')
        if s_km < race_km:
            print('WARN: finish not reached; plan is infeasible under current assumptions.')


if __name__ == '__main__':
    main()
