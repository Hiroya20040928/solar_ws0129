from __future__ import annotations
#!/usr/bin/env python3

import argparse
import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート
from scipy.optimize import least_squares
from scipy.signal import savgol_filter

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[0]
for candidate in (SCRIPT_DIR, ROOT):
    raw = os.fspath(candidate)
    if raw not in sys.path:
        sys.path.insert(0, raw)

from build_bwsc2025_fitted_package import (
    BATTERY_PACK_MAX_CHARGE_V,
    BATTERY_NOMINAL_VOLTAGE_V,
    INVALID_PACK_VOLTAGE_MIN_V,
    ROOT,
    TIMEZONE_LOCAL,
    BatteryFitResult,
    MotionFitResult,
    PostRefineResult,
    PvFitResult,
    attach_archive_pv_model,
    build_grounded_map_assets,
    build_stage_anchors,
    build_model_from_map_assets,
    build_model_from_profile_cfg,
    compile_tex,
    dcir_observations,
    ensure_dir,
    fit_battery_parameters,
    fit_map_shapes,
    fit_motion_parameters,
    fit_pv_parameters,
    fit_regen_utilization,
    fit_stop_tilt_fraction,
    has_identified_polarization_maps,
    infer_soc_from_loaded_state,
    joint_refine_parameters,
    joint_replay,
    load_profile_yaml,
    metrics_from_replay,
    motion_power_prediction,
    post_refine_replay_scalars,
    replay_segment_start_mask,
    resample_for_fit,
    soc_fit_upper_bound,
    write_current_maps_and_coefficients,
    write_scaled_maps,
)
from audit_identification_residuals import run_audit as run_residual_audit


FIT_QUALITY_PRESETS: Dict[str, Dict[str, Any]] = {
    "quick": {
        "battery_restart_count": 2,
        "battery_maxiter": 50,
        "motion_restart_count": 3,
        "motion_maxiter": 70,
        "joint_restart_count": 2,
        "joint_random_start_count": 8,
        "joint_local_topk": 2,
        "joint_maxiter": 24,
        "fit_stride": 3,
        "allow_map_shape_fit": False,
        "post_refine_enabled": False,
    },
    "standard": {
        "battery_restart_count": 4,
        "battery_maxiter": 80,
        "motion_restart_count": 5,
        "motion_maxiter": 100,
        "joint_restart_count": 4,
        "joint_random_start_count": 6,
        "joint_local_topk": 3,
        "joint_maxiter": 40,
        "fit_stride": 2,
        "allow_map_shape_fit": True,
        "post_refine_enabled": False,
    },
    "full": {
        "battery_restart_count": 6,
        "battery_maxiter": 140,
        "motion_restart_count": 8,
        "motion_maxiter": 180,
        "joint_restart_count": 6,
        "joint_random_start_count": 18,
        "joint_local_topk": 6,
        "joint_maxiter": 80,
        "fit_stride": 2,
        "allow_map_shape_fit": True,
        "post_refine_enabled": False,
    },
    "ultra": {
        "battery_restart_count": 8,
        "battery_maxiter": 220,
        "motion_restart_count": 10,
        "motion_maxiter": 260,
        "joint_restart_count": 8,
        "joint_random_start_count": 28,
        "joint_local_topk": 8,
        "joint_maxiter": 120,
        "fit_stride": 1,
        "allow_map_shape_fit": True,
        "post_refine_enabled": True,
    },
}


def neutralize_identification_scalars(model):                      # [関数定義] neutralize_identification_scalars の処理実行ブロック
    """Fit each calibration factor once on top of the declared physical maps."""
    model.p.panel_gain = 1.0
    model.p.drive_eff_scale = 1.0
    model.p.regen_eff_scale = 1.0
    model.p.regen_utilization = 1.0
    model.p.rint_scale = 1.0
    model.p.r_polarization_ohm = 0.0
    model.aux_power_override_w = None
    return model                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def resolve_relative(base_dir: Path, raw: str) -> Path:            # [関数定義] resolve_relative の処理実行ブロック
    path = Path(str(raw or "").strip())
    if not path:
        return base_dir                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if path.is_absolute():
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return (base_dir / path).resolve()                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def stage(message: str) -> None:                                   # [関数定義] stage の処理実行ブロック
    print(f"[generic-id] {message}", flush=True)


def load_manifest(package_dir: Path, manifest_arg: str | None) -> Tuple[Path, dict]:  # [関数定義] load_manifest の処理実行ブロック
    default_path = package_dir / "data" / "identification" / "identification_manifest.yaml"
    if manifest_arg:
        raw_path = Path(str(manifest_arg).strip())
        if raw_path.is_absolute():
            manifest_path = raw_path
        else:
            candidates = [
                (package_dir / raw_path).resolve(),
                (ROOT / raw_path).resolve(),
                (Path.cwd() / raw_path).resolve(),
            ]
            manifest_path = next((path for path in candidates if path.is_file()), candidates[0])
    else:
        manifest_path = default_path
    with manifest_path.open("r", encoding="utf-8") as f:
        payload = yaml.safe_load(f) or {}
    return manifest_path, payload                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def relpath_from(base_dir: Path, target: Path | None) -> str:      # [関数定義] relpath_from の処理実行ブロック
    if target is None:
        return ""                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    try:
        return os.path.relpath(target, base_dir).replace("\\", "/")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        return os.fspath(target)                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def tex_path_fragment(value: object) -> str:                       # [関数定義] tex_path_fragment の処理実行ブロック
    """Render ASCII and Unicode paths without losing CJK glyphs or TeX syntax."""
    text = str(value)
    if text.isascii():
        return rf"\path{{{text}}}"                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
    }
    escaped = "".join(replacements.get(char, char) for char in text)
    escaped = escaped.replace("/", r"/\allowbreak{}")
    return rf"\texttt{{{escaped}}}"                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def tex_text_fragment(value: object) -> str:                       # [関数定義] tex_text_fragment の処理実行ブロック
    """Escape arbitrary report prose without path-style whitespace handling."""
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "^": r"\textasciicircum{}",
        "~": r"\textasciitilde{}",
    }
    return "".join(replacements.get(char, char) for char in str(value))  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_yaml_if_exists(path: Path | None) -> dict:                # [関数定義] load_yaml_if_exists の処理実行ブロック
    if path is None or not path.exists():
        return {}                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def declared_control_stop_km(profile_cfg: dict, profile_path: Path) -> list[float]:  # [関数定義] declared_control_stop_km の処理実行ブロック
    """Load control-stop distances declared by the vehicle package."""
    paths = profile_cfg.get("paths", {}) if isinstance(profile_cfg, dict) else {}
    for key in ("actual_stop_yaml", "stop_yaml"):
        raw = str(paths.get(key, "") or "").strip()
        if not raw:
            continue
        payload = load_yaml_if_exists(resolve_relative(profile_path.parent, raw))
        stops = payload.get("stops", []) if isinstance(payload, dict) else []
        distances = []
        for item in stops:
            if not isinstance(item, dict) or not bool(item.get("is_control_stop", False)):
                continue
            try:
                distances.append(float(item["s_km"]))
            except (KeyError, TypeError, ValueError):
                continue
        if distances:
            return sorted(set(distances))                          # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return []                                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _terminal_anchor_from_payload(payload: dict) -> Dict[str, Any]:  # [関数定義] _terminal_anchor_from_payload の処理実行ブロック
    if not isinstance(payload, dict):
        return {}                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    anchor = payload.get("terminal_anchor", payload)
    if not isinstance(anchor, dict):
        return {}                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    out: Dict[str, Any] = {}
    for key in (
        "count",
        "s_km",
        "voltage_v",
        "current_a",
        "temp_c",
        "soc_target",
        "soc_sigma",
        "soc_evidence_min",
        "soc_evidence_max",
        "voltage_sigma_v",
        "ocv_terminal_v",
        "series_resistance_ohm",
        "ocv_statistical_sigma_v",
        "ocv_systematic_sigma_v",
        "ocv_total_sigma_v",
    ):
        raw = anchor.get(key, None)
        if raw in (None, ""):
            continue
        try:
            out[key] = float(raw)
        except Exception:
            pass
    raw_time = str(anchor.get("time_utc", "") or "").strip()
    if raw_time:
        out["time_utc"] = raw_time
    for key in ("notes", "source_documents", "method", "soc_target_basis"):
        if key in anchor:
            out[key] = anchor[key]
    for key in (
        "quality_gate_pass",
        "conditional_on_grounded_ocv_map",
        "weak_channel_cross_consistency_gate_pass",
    ):
        if key in anchor:
            out[key] = bool(anchor[key])
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _append_reason_column(frame: pd.DataFrame, mask: pd.Series, reason: str) -> None:  # [関数定義] _append_reason_column の処理実行ブロック
    if not mask.any():
        return
    current = frame.loc[mask, "exclude_reason"].fillna("").astype(str)
    merged = np.where(current.str.len() > 0, current + ";" + reason, reason)
    frame.loc[mask, "exclude_reason"] = merged


def resolve_manifest_context(package_dir: Path, manifest: dict) -> dict:  # [関数定義] resolve_manifest_context の処理実行ブロック
    inputs = manifest.get("inputs", {}) if isinstance(manifest, dict) else {}
    options = manifest.get("options", {}) if isinstance(manifest, dict) else {}
    grounded = manifest.get("grounded_sources", {}) if isinstance(manifest, dict) else {}
    evidence = manifest.get("evidence", {}) if isinstance(manifest, dict) else {}

    def opt_path(raw_value) -> Path | None:                        # [関数定義] opt_path の処理実行ブロック
        raw = str(raw_value or "").strip()
        if not raw:
            return None                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return resolve_relative(package_dir, raw)                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    actual_event_path = opt_path(inputs.get("actual_event_yaml"))
    counterfactual_event_path = opt_path(inputs.get("counterfactual_event_yaml"))
    terminal_anchor_path = opt_path(inputs.get("terminal_anchor_yaml"))
    grounded_summary_path = opt_path(grounded.get("grounded_map_summary_yaml", "") or options.get("grounded_map_summary_yaml", ""))
    source_inventory_path = opt_path(evidence.get("source_inventory_json"))
    notes_markdown_path = opt_path(evidence.get("notes_markdown"))

    path_key_map = {
        "drive_eff_map": "drive_eff_map_csv",
        "drive_map_eco": "drive_map_eco_csv",
        "drive_map_power": "drive_map_power_csv",
        "regen_eff_map": "regen_eff_map_csv",
        "regen_map_eco": "regen_map_eco_csv",
        "regen_map_power": "regen_map_power_csv",
        "rint_map": "rint_map_csv",
        "r1_map": "r1_map_csv",
        "tau_map": "tau_map_csv",
        "panel_eff_map": "panel_eff_map_csv",
        "mppt_eff_map": "mppt_eff_map_csv",
        "ocv_soc_map": "ocv_soc_map_csv",
    }
    explicit_grounded_assets: Dict[str, Path] = {}
    for model_key, manifest_key in path_key_map.items():
        raw = str(grounded.get(manifest_key, "") or "").strip()
        if raw:
            explicit_grounded_assets[model_key] = resolve_relative(package_dir, raw)

    if explicit_grounded_assets:
        if "drive_map_eco" not in explicit_grounded_assets and "drive_eff_map" in explicit_grounded_assets:
            explicit_grounded_assets["drive_map_eco"] = explicit_grounded_assets["drive_eff_map"]
        if "drive_map_power" not in explicit_grounded_assets and "drive_eff_map" in explicit_grounded_assets:
            explicit_grounded_assets["drive_map_power"] = explicit_grounded_assets["drive_eff_map"]
        if "regen_map_eco" not in explicit_grounded_assets and "regen_eff_map" in explicit_grounded_assets:
            explicit_grounded_assets["regen_map_eco"] = explicit_grounded_assets["regen_eff_map"]
        if "regen_map_power" not in explicit_grounded_assets and "regen_eff_map" in explicit_grounded_assets:
            explicit_grounded_assets["regen_map_power"] = explicit_grounded_assets["regen_eff_map"]
        required = {
            "drive_eff_map", "regen_eff_map", "rint_map",
            "panel_eff_map", "mppt_eff_map", "ocv_soc_map",
        }
        missing = sorted(required.difference(explicit_grounded_assets))
        if missing:
            raise ValueError(
                "grounded_sources declares explicit maps but is missing required entries: "
                + ", ".join(missing)
            )

    grounded_summary_payload = load_yaml_if_exists(grounded_summary_path)
    if grounded_summary_path is not None:
        grounded_summary_payload["summary_yaml"] = relpath_from(package_dir, grounded_summary_path)

    actual_event_payload = load_yaml_if_exists(actual_event_path)
    terminal_anchor_payload = load_yaml_if_exists(terminal_anchor_path)
    terminal_anchor_override = _terminal_anchor_from_payload(terminal_anchor_payload)

    external_documents = evidence.get("external_documents", [])
    if not isinstance(external_documents, list):
        external_documents = [external_documents]

    declared_evidence: Dict[str, list[Path]] = {}
    missing_evidence: list[str] = []
    for group_key in ("field_tests", "normalized_field_outputs", "external_documents"):
        raw_values = evidence.get(group_key, [])
        if not isinstance(raw_values, list):
            raw_values = [raw_values]
        resolved_group: list[Path] = []
        for raw_value in raw_values:
            raw = str(raw_value or "").strip()
            if not raw:
                continue
            raw_path = Path(raw)
            if raw_path.is_absolute():
                resolved = raw_path
            else:
                candidates = [(package_dir / raw_path).resolve(), (ROOT / raw_path).resolve()]
                resolved = next((path for path in candidates if path.exists()), candidates[0])
            resolved_group.append(resolved)
            if not resolved.exists():
                missing_evidence.append(f"{group_key}: {raw}")
        declared_evidence[group_key] = resolved_group
    if missing_evidence:
        raise FileNotFoundError(
            "identification evidence manifest contains missing artifacts:\n- "
            + "\n- ".join(missing_evidence)
        )

    assets = {
        "inputs": inputs,
        "options": options,
        "grounded_sources": grounded,
        "evidence": evidence,
        "actual_event_path": actual_event_path,
        "counterfactual_event_path": counterfactual_event_path,
        "terminal_anchor_path": terminal_anchor_path,
        "grounded_summary_path": grounded_summary_path,
        "source_inventory_path": source_inventory_path,
        "notes_markdown_path": notes_markdown_path,
        "explicit_grounded_assets": explicit_grounded_assets,
        "grounded_summary_payload": grounded_summary_payload,
        "actual_event_payload": actual_event_payload,
        "terminal_anchor_override": terminal_anchor_override,
        "external_documents": external_documents,
        "declared_evidence": declared_evidence,
    }
    return assets                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def hampel_mask(series: pd.Series, *, window: int, n_sigma: float, min_abs: float) -> pd.Series:  # [関数定義] hampel_mask の処理実行ブロック
    x = pd.to_numeric(series, errors="coerce").astype(float)
    window = max(3, int(window))
    if window % 2 == 0:
        window += 1
    med = x.rolling(window, center=True, min_periods=1).median()
    abs_dev = (x - med).abs()
    mad = abs_dev.rolling(window, center=True, min_periods=1).median()
    scale = (1.4826 * mad).clip(lower=max(1.0e-6, float(min_abs) * 0.25))
    return abs_dev > np.maximum(float(min_abs), float(n_sigma) * scale)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def apply_sensor_quality_annotations(                              # [関数定義] apply_sensor_quality_annotations の処理実行ブロック
    work: pd.DataFrame,
    *,
    base_model,
    options: dict | None = None,
) -> pd.DataFrame:
    options = options if isinstance(options, dict) else {}
    sensor_cfg = options.get("sensor_filter", {}) if isinstance(options.get("sensor_filter", {}), dict) else {}
    if sensor_cfg.get("enabled", True) is False:
        return work                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    out = work.copy()
    for key in ("exclude_power_fit", "exclude_voltage_fit", "exclude_weather_fit"):
        if key not in out.columns:
            out[key] = False
        out[key] = out[key].fillna(False).astype(bool)
    if "exclude_reason" not in out.columns:
        out["exclude_reason"] = ""

    invalid_v_threshold = float(sensor_cfg.get("invalid_voltage_threshold_v", INVALID_PACK_VOLTAGE_MIN_V))
    current_limit_margin_a = float(sensor_cfg.get("charge_current_limit_margin_a", 2.0))
    current_spike_window = int(sensor_cfg.get("current_spike_window", 9))
    current_spike_sigma = float(sensor_cfg.get("current_spike_sigma", 4.0))
    current_spike_min_abs_a = float(sensor_cfg.get("current_spike_min_abs_a", 4.0))
    power_spike_window = int(sensor_cfg.get("power_spike_window", 9))
    power_spike_sigma = float(sensor_cfg.get("power_spike_sigma", 4.0))
    power_spike_min_abs_w = float(sensor_cfg.get("power_spike_min_abs_w", 400.0))
    voltage_slew_max_vps = float(sensor_cfg.get("voltage_slew_max_vps", 0.20))
    voltage_slew_low_current_a = float(sensor_cfg.get("voltage_slew_low_current_a", 2.5))
    voltage_spike_window = int(sensor_cfg.get("voltage_spike_window", 9))
    voltage_spike_sigma = float(sensor_cfg.get("voltage_spike_sigma", 4.0))
    voltage_spike_min_abs_v = float(sensor_cfg.get("voltage_spike_min_abs_v", 2.0))

    invalid_v = np.isfinite(out["battery_voltage_v"]) & (out["battery_voltage_v"] < invalid_v_threshold)
    if invalid_v.any():
        out.loc[invalid_v, "exclude_voltage_fit"] = True
        out.loc[invalid_v, "exclude_power_fit"] = True
        _append_reason_column(out, invalid_v, "invalid_pack_voltage_sensor")

    voltage = pd.to_numeric(out["battery_voltage_v"], errors="coerce")
    current = pd.to_numeric(out["battery_current_a"], errors="coerce")
    dt_sec = pd.to_numeric(out["dt_sec"], errors="coerce").replace(0.0, np.nan)
    voltage_slew_vps = voltage.diff().abs() / dt_sec
    low_current_pair = (
        (current.abs() <= voltage_slew_low_current_a)
        & (current.shift(1).abs() <= voltage_slew_low_current_a)
    )
    impossible_voltage_slew = (
        voltage_slew_vps > voltage_slew_max_vps
    ) & low_current_pair & (~invalid_v) & (~invalid_v.shift(1, fill_value=True))
    if impossible_voltage_slew.any():
        out.loc[impossible_voltage_slew, "exclude_voltage_fit"] = True
        out.loc[impossible_voltage_slew, "exclude_power_fit"] = True
        _append_reason_column(out, impossible_voltage_slew, "impossible_pack_voltage_slew")

    voltage_spike = hampel_mask(
        voltage,
        window=voltage_spike_window,
        n_sigma=voltage_spike_sigma,
        min_abs=voltage_spike_min_abs_v,
    ) & (current.abs() <= voltage_slew_low_current_a) & (~invalid_v)
    if voltage_spike.any():
        out.loc[voltage_spike, "exclude_voltage_fit"] = True
        out.loc[voltage_spike, "exclude_power_fit"] = True
        _append_reason_column(out, voltage_spike, "battery_voltage_hampel_spike")

    charge_floor_a = float(getattr(base_model.p, "I_chg_min", -16.5)) - current_limit_margin_a
    impossible_charge = np.isfinite(out["battery_current_a"]) & (out["battery_current_a"] < charge_floor_a)
    if impossible_charge.any():
        out.loc[impossible_charge, "exclude_power_fit"] = True
        _append_reason_column(out, impossible_charge, "charge_current_limit_exceeded")

    current_spike = hampel_mask(
        out["battery_current_a"],
        window=current_spike_window,
        n_sigma=current_spike_sigma,
        min_abs=current_spike_min_abs_a,
    ) & np.isfinite(out["battery_current_a"])
    if current_spike.any():
        out.loc[current_spike, "exclude_power_fit"] = True
        _append_reason_column(out, current_spike, "battery_current_hampel_spike")

    power_spike = hampel_mask(
        out["battery_power_w_obs"],
        window=power_spike_window,
        n_sigma=power_spike_sigma,
        min_abs=power_spike_min_abs_w,
    ) & np.isfinite(out["battery_power_w_obs"])
    if power_spike.any():
        out.loc[power_spike, "exclude_power_fit"] = True
        _append_reason_column(out, power_spike, "battery_power_hampel_spike")

    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def polarization_current_trace(                                    # [関数定義] polarization_current_trace の処理実行ブロック
    replay: pd.DataFrame,
    *,
    current_column: str,
    tau_sec: float,
) -> np.ndarray:
    """Return the 1-RC branch current state immediately before each sample."""
    current = pd.to_numeric(replay[current_column], errors="coerce").to_numpy(dtype=float)
    current = np.where(np.isfinite(current), current, 0.0)
    time_utc = pd.to_datetime(replay["time_utc"], utc=True, errors="coerce")
    dt_sec = time_utc.diff().dt.total_seconds().to_numpy(dtype=float)
    segment_starts = replay_segment_start_mask(replay)
    state = np.zeros(len(replay), dtype=float)
    tau = max(float(tau_sec), 1.0e-6)
    for idx in range(1, len(replay)):
        if segment_starts[idx] or not np.isfinite(dt_sec[idx]) or dt_sec[idx] <= 0.0:
            state[idx] = 0.0
            continue
        dt = min(float(dt_sec[idx]), 60.0)
        alpha = math.exp(-dt / tau)
        state[idx] = alpha * state[idx - 1] + (1.0 - alpha) * current[idx - 1]
    return state                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fit_battery_polarization(replay: pd.DataFrame) -> Dict[str, Any]:  # [関数定義] fit_battery_polarization の処理実行ブロック
    """Fit a bounded one-RC branch and gate it on the last independent day."""
    residual = (
        pd.to_numeric(replay["battery_voltage_v_obs"], errors="coerce")
        - pd.to_numeric(replay["battery_voltage_v_pred"], errors="coerce")
    ).to_numpy(dtype=float)
    excluded = replay.get("exclude_voltage_fit", pd.Series(False, index=replay.index)).fillna(True).astype(bool).to_numpy()
    base_valid = np.isfinite(residual) & ~excluded
    if int(base_valid.sum()) < 500:
        return {                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "adopted": False,
            "reason": "insufficient_valid_voltage_samples",
            "sample_count": int(base_valid.sum()),
            "r_polarization_ohm": 0.0,
            "tau_sec": 60.0,
            "rmse_before_v": float("nan"),
            "rmse_after_v": float("nan"),
        }

    if "day" in replay.columns:
        groups = pd.to_numeric(replay["day"], errors="coerce").to_numpy(dtype=float)
    else:
        time_local = pd.to_datetime(replay["time_utc"], utc=True, errors="coerce").dt.tz_convert(
            TIMEZONE_LOCAL
        )
        groups = time_local.dt.strftime("%Y%m%d").astype(float).to_numpy()
    unique_groups = sorted(float(value) for value in np.unique(groups[base_valid & np.isfinite(groups)]))
    if len(unique_groups) < 2:
        return {                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "adopted": False,
            "reason": "no_independent_day_holdout",
            "sample_count": int(base_valid.sum()),
            "training_sample_count": 0,
            "validation_sample_count": 0,
            "r_polarization_ohm": 0.0,
            "tau_sec": 60.0,
            "rmse_before_v": float(np.sqrt(np.mean(residual[base_valid] ** 2))),
            "rmse_after_v": float(np.sqrt(np.mean(residual[base_valid] ** 2))),
        }
    holdout_group = unique_groups[-1]
    training_valid = base_valid & np.isfinite(groups) & (groups != holdout_group)
    validation_valid = base_valid & np.isfinite(groups) & (groups == holdout_group)
    if int(training_valid.sum()) < 500 or int(validation_valid.sum()) < 100:
        return {                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "adopted": False,
            "reason": "insufficient_independent_day_holdout_samples",
            "sample_count": int(base_valid.sum()),
            "training_sample_count": int(training_valid.sum()),
            "validation_sample_count": int(validation_valid.sum()),
            "holdout_group": holdout_group,
            "r_polarization_ohm": 0.0,
            "tau_sec": 60.0,
            "rmse_before_v": float(np.sqrt(np.mean(residual[base_valid] ** 2))),
            "rmse_after_v": float(np.sqrt(np.mean(residual[base_valid] ** 2))),
        }

    best: Dict[str, float] | None = None
    for tau_sec in np.geomspace(10.0, 600.0, 81):
        state = polarization_current_trace(
            replay,
            current_column="battery_current_a_obs",
            tau_sec=float(tau_sec),
        )
        valid = training_valid & np.isfinite(state)
        denom = float(np.dot(state[valid], state[valid]))
        if denom <= 1.0e-12:
            continue
        # V_dynamic = V_static - Rp*x, hence residual_dynamic = residual + Rp*x.
        rp_ohm = float(np.clip(-np.dot(residual[valid], state[valid]) / denom, 0.0, 0.12))
        corrected = residual[valid] + rp_ohm * state[valid]
        rmse = float(np.sqrt(np.mean(corrected ** 2)))
        if best is None or rmse < best["rmse_after_v"]:
            best = {
                "r_polarization_ohm": rp_ohm,
                "tau_sec": float(tau_sec),
                "rmse_after_v": rmse,
            }

    rmse_before = float(np.sqrt(np.mean(residual[training_valid] ** 2)))
    if best is None:
        return {                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "adopted": False,
            "reason": "no_finite_candidate",
            "sample_count": int(base_valid.sum()),
            "training_sample_count": int(training_valid.sum()),
            "validation_sample_count": int(validation_valid.sum()),
            "holdout_group": holdout_group,
            "r_polarization_ohm": 0.0,
            "tau_sec": 60.0,
            "rmse_before_v": rmse_before,
            "rmse_after_v": rmse_before,
        }
    validation_before = float(np.sqrt(np.mean(residual[validation_valid] ** 2)))
    best_state = polarization_current_trace(
        replay,
        current_column="battery_current_a_obs",
        tau_sec=float(best["tau_sec"]),
    )
    validation_corrected = (
        residual[validation_valid]
        + float(best["r_polarization_ohm"]) * best_state[validation_valid]
    )
    validation_after = float(np.sqrt(np.mean(validation_corrected ** 2)))
    validation_ratio = validation_after / max(validation_before, 1.0e-12)
    improvement = rmse_before - float(best["rmse_after_v"])
    adopted = bool(
        best["r_polarization_ohm"] >= 0.001
        and improvement >= 0.005
        and np.isfinite(validation_ratio)
        and validation_ratio <= 1.0
    )
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "adopted": adopted,
        "reason": (
            "bounded_1rc_improves_training_and_last_day_holdout_rmse"
            if adopted
            else "training_or_last_day_holdout_gate_failed"
        ),
        "sample_count": int(base_valid.sum()),
        "training_sample_count": int(training_valid.sum()),
        "validation_sample_count": int(validation_valid.sum()),
        "holdout_group": holdout_group,
        "r_polarization_ohm": float(best["r_polarization_ohm"] if adopted else 0.0),
        "tau_sec": float(best["tau_sec"]),
        "rmse_before_v": rmse_before,
        "rmse_after_v": float(best["rmse_after_v"] if adopted else rmse_before),
        "rmse_improvement_v": float(improvement if adopted else 0.0),
        "validation_rmse_before_v": validation_before,
        "validation_rmse_after_v": validation_after,
        "validation_rmse_ratio": validation_ratio,
        "validation_rmse_ratio_max": 1.0,
        "method": (
            "bounded deterministic tau grid with closed-form least-squares Rp on earlier race days; "
            "last race day is an untouched adoption holdout"
        ),
    }


def apply_battery_polarization(                                    # [関数定義] apply_battery_polarization の処理実行ブロック
    replay: pd.DataFrame,
    dynamic_fit: Dict[str, Any],
    *,
    current_column: str,
) -> pd.DataFrame:
    out = replay.copy()
    out["battery_voltage_v_pred_static"] = pd.to_numeric(
        out["battery_voltage_v_pred"], errors="coerce"
    )
    if not bool(dynamic_fit.get("adopted", False)):
        out["battery_polarization_v"] = 0.0
        return out                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    state = polarization_current_trace(
        out,
        current_column=current_column,
        tau_sec=float(dynamic_fit["tau_sec"]),
    )
    polarization_v = float(dynamic_fit["r_polarization_ohm"]) * state
    out["battery_polarization_v"] = polarization_v
    out["battery_voltage_v_pred"] = out["battery_voltage_v_pred_static"] - polarization_v
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def resolve_fit_plan(options: dict | None, *, quality: str) -> Dict[str, Any]:  # [関数定義] resolve_fit_plan の処理実行ブロック
    options = options if isinstance(options, dict) else {}
    quality_norm = str(quality or options.get("fit_quality", "standard")).strip().lower()
    if quality_norm not in FIT_QUALITY_PRESETS:
        quality_norm = "standard"
    plan = dict(FIT_QUALITY_PRESETS[quality_norm])
    key_map = {
        "battery_restart_count": "battery_restart_count",
        "battery_maxiter": "battery_maxiter",
        "motion_restart_count": "motion_restart_count",
        "motion_maxiter": "motion_maxiter",
        "joint_restart_count": "joint_restart_count",
        "joint_random_start_count": "joint_random_start_count",
        "joint_local_topk": "joint_local_topk",
        "joint_maxiter": "joint_maxiter",
        "fit_stride": "fit_stride",
        "allow_map_shape_fit": "allow_map_shape_fit",
        "post_refine_enabled": "post_refine_enabled",
    }
    for out_key, opt_key in key_map.items():
        if opt_key in options:
            plan[out_key] = options[opt_key]
    plan["panel_deployment_stopped_speed_kmh"] = float(
        options.get("panel_deployment_stopped_speed_kmh", 2.0)
    )
    plan["panel_deployment_min_dwell_sec"] = float(
        options.get("panel_deployment_min_dwell_sec", 300.0)
    )
    plan["panel_deployment_max_sample_gap_sec"] = float(
        options.get("panel_deployment_max_sample_gap_sec", 60.0)
    )
    plan["panel_control_stop_tolerance_km"] = float(
        options.get("panel_control_stop_tolerance_km", 1.0)
    )
    plan["quality"] = quality_norm
    plan["terminal_anchor_role"] = str(
        options.get("terminal_anchor_role", "independent_consensus")
    )
    plan["sensor_filter"] = options.get("sensor_filter", {})
    plan["acceleration_observation"] = options.get("acceleration_observation", {})
    plan["grade_observation"] = options.get("grade_observation", {})
    return plan                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def resolve_identification_output_layout(                          # [関数定義] resolve_identification_output_layout の処理実行ブロック
    package_dir: Path,
    profile_cfg: dict,
    *,
    output_tag_override: str | None = None,
) -> Dict[str, Path | str]:
    identification_cfg = profile_cfg.get("identification", {}) or {}
    output_root = resolve_relative(
        package_dir,
        str(identification_cfg.get("output_dir", "outputs/identification") or "outputs/identification"),
    )
    raw_tag = output_tag_override
    if raw_tag is None:
        raw_tag = str(identification_cfg.get("output_tag", "") or "")
    tag = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(raw_tag).strip()).strip("._")
    run_root = output_root / "runs" / tag if tag else output_root
    report_root = run_root / "reports" if tag else package_dir / "outputs" / "reports"
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "tag": tag,
        "output_root": output_root,
        "run_root": run_root,
        "report_root": report_root,
        "grounded_maps": run_root / "grounded_base_maps",
        "adopted_maps": run_root / "adopted_maps",
    }


def identification_profile_output_path(                            # [関数定義] identification_profile_output_path の処理実行ブロック
    canonical_profile: Path,
    run_output_dir: Path,
    *,
    output_tag: str,
    adopt_profile: bool,
) -> Path:
    if str(output_tag).strip() and not adopt_profile:
        return Path(run_output_dir) / "profile_candidate.yaml"     # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return Path(canonical_profile)                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_ocv_df(profile_cfg: dict, profile_yaml: Path) -> pd.DataFrame:  # [関数定義] load_ocv_df の処理実行ブロック
    raw = str((profile_cfg.get("paths", {}) or {}).get("ocv_soc_map", "") or "").strip()
    if not raw:
        raise FileNotFoundError("profile.paths.ocv_soc_map is required")
    ocv_path = resolve_relative(profile_yaml.parent, raw)
    return pd.read_csv(ocv_path)                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_source_map_assets(profile_cfg: dict, profile_yaml: Path) -> Dict[str, Path]:  # [関数定義] build_source_map_assets の処理実行ブロック
    base_dir = profile_yaml.parent
    paths = profile_cfg.get("paths", {}) or {}

    def rel(key: str, fallback: str | None = None) -> Path:        # [関数定義] rel の処理実行ブロック
        raw = str(paths.get(key, fallback or "") or "").strip()
        if not raw:
            raise FileNotFoundError(f"profile.paths.{key} is required")
        return resolve_relative(base_dir, raw)                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "drive_eff_map": rel("drive_eff_map"),
        "drive_map_eco": rel("drive_map_eco", paths.get("drive_eff_map", "")),
        "drive_map_power": rel("drive_map_power", paths.get("drive_eff_map", "")),
        "regen_eff_map": rel("regen_eff_map"),
        "regen_map_eco": rel("regen_map_eco", paths.get("regen_eff_map", "")),
        "regen_map_power": rel("regen_map_power", paths.get("regen_eff_map", "")),
        "rint_map": rel("rint_map"),
        "panel_eff_map": rel("panel_eff_map"),
        "mppt_eff_map": rel("mppt_eff_map"),
        "ocv_soc_map": rel("ocv_soc_map"),
    }
    for key in ("r1_map", "tau_map"):
        raw = str(paths.get(key, "") or "").strip()
        if raw:
            assets[key] = resolve_relative(base_dir, raw)
    return assets                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def apply_actual_event_annotations(work: pd.DataFrame, payload: dict | None) -> pd.DataFrame:  # [関数定義] apply_actual_event_annotations の処理実行ブロック
    if not isinstance(payload, dict):
        return work                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    events = payload.get("events", payload)
    if not isinstance(events, list) or not events:
        return work                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    out = work.copy()
    for key in ("exclude_power_fit", "exclude_voltage_fit", "exclude_weather_fit"):
        if key not in out.columns:
            out[key] = False
        out[key] = out[key].fillna(False).astype(bool)
    if "exclude_reason" not in out.columns:
        out["exclude_reason"] = ""
    time_utc = pd.to_datetime(out["time_utc"], format="mixed", utc=True, errors="coerce")
    for event in events:
        if not isinstance(event, dict):
            continue
        raw_start = str(event.get("start_local", "") or "").strip()
        raw_end = str(event.get("end_local", "") or "").strip()
        if not raw_start or not raw_end:
            continue
        tz_name = str(event.get("timezone", TIMEZONE_LOCAL.key if hasattr(TIMEZONE_LOCAL, "key") else "Australia/Darwin") or "Australia/Darwin")
        try:
            start_utc = pd.Timestamp(raw_start).tz_localize(tz_name).tz_convert("UTC")
            end_utc = pd.Timestamp(raw_end).tz_localize(tz_name).tz_convert("UTC")
        except Exception:
            continue
        mask = (time_utc >= start_utc) & (time_utc <= end_utc)
        if not mask.any():
            continue
        fit_flags = event.get("fit_flags", {}) if isinstance(event.get("fit_flags", {}), dict) else {}
        reason = str(event.get("label", event.get("kind", "actual_event")) or "actual_event")
        touched = False
        for key in ("exclude_power_fit", "exclude_voltage_fit", "exclude_weather_fit"):
            if bool(fit_flags.get(key, False)):
                out.loc[mask, key] = True
                touched = True
        if touched:
            _append_reason_column(out, mask, reason)
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def truncate_at_retire_event(work: pd.DataFrame, payload: dict | None) -> pd.DataFrame:  # [関数定義] truncate_at_retire_event の処理実行ブロック
    """End historical replay at the first authoritative retirement timestamp."""
    if not isinstance(payload, dict):
        return work                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    events = payload.get("events", payload)
    if not isinstance(events, list):
        return work                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    cutoffs: list[pd.Timestamp] = []
    for event in events:
        if not isinstance(event, dict) or str(event.get("kind", "")).strip().lower() != "retire_event":
            continue
        raw_start = str(event.get("start_local", "") or "").strip()
        if not raw_start:
            continue
        tz_name = str(event.get("timezone", "Australia/Darwin") or "Australia/Darwin")
        try:
            cutoffs.append(pd.Timestamp(raw_start).tz_localize(tz_name).tz_convert("UTC"))
        except Exception:
            continue
    if not cutoffs:
        return work                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    cutoff = min(cutoffs)
    time_utc = pd.to_datetime(work["time_utc"], format="mixed", utc=True, errors="coerce")
    retained = work.loc[time_utc <= cutoff].copy()
    if retained.empty:
        raise ValueError(f"retire-event cutoff {cutoff.isoformat()} removed the complete replay")
    return retained.reset_index(drop=True)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却


def normalize_generic_log(                                         # [関数定義] normalize_generic_log の処理実行ブロック
    log_csv: Path,
    *,
    actual_event_payload: dict | None = None,
    base_model=None,
    options: dict | None = None,
) -> pd.DataFrame:
    df = pd.read_csv(log_csv, low_memory=False)
    if "time_utc" not in df.columns:
        raise ValueError("normalized replay log must contain time_utc")
    work = df.copy()
    work["time_utc"] = pd.to_datetime(work["time_utc"], format="mixed", utc=True)
    work = work.sort_values("time_utc").reset_index(drop=True)

    required_defaults = {
        "s_km": np.nan,
        "speed_kmh": 0.0,
        "slope_pct": 0.0,
        "route_heading_deg": 0.0,
        "headwind_archive_ms": 0.0,
        "GHI_archive": 0.0,
        "Tamb_archive_C": 25.0,
        "solar_power_w_obs": 0.0,
        "battery_power_w_obs": 0.0,
        "battery_current_a": 0.0,
        "battery_voltage_v": np.nan,
        "lat": np.nan,
        "lon": np.nan,
        "alt_m": 0.0,
    }
    for key, value in required_defaults.items():
        if key not in work.columns:
            work[key] = value

    if "dt_sec" not in work.columns:
        dt = work["time_utc"].diff().dt.total_seconds().fillna(0.0)
        if len(dt) >= 2 and dt.iloc[0] <= 0.0:
            dt.iloc[0] = float(np.nanmedian(dt.iloc[1:].replace(0.0, np.nan).dropna())) if len(dt.iloc[1:].dropna()) else 5.0
        work["dt_sec"] = dt.clip(lower=0.0).fillna(5.0)
    if "time_local" not in work.columns:
        work["time_local"] = work["time_utc"].dt.tz_convert(TIMEZONE_LOCAL).astype(str)
    if "day" not in work.columns:
        work["day"] = (work["time_utc"].dt.normalize() - work["time_utc"].dt.normalize().min()).dt.days + 1
    for key in ("exclude_power_fit", "exclude_voltage_fit", "exclude_weather_fit"):
        if key not in work.columns:
            work[key] = False
        work[key] = work[key].fillna(False).astype(bool)
    if "exclude_reason" not in work.columns:
        work["exclude_reason"] = ""
    if "GHI_effective" not in work.columns:
        work["GHI_effective"] = work["GHI_archive"]
    if "Tcell_effective_C" not in work.columns:
        work["Tcell_effective_C"] = work["Tamb_archive_C"] + 0.03 * pd.to_numeric(work["GHI_effective"], errors="coerce").fillna(0.0)
    if "headwind_effective_ms" not in work.columns:
        work["headwind_effective_ms"] = work["headwind_archive_ms"]
    numeric_cols = [
        "s_km",
        "speed_kmh",
        "slope_pct",
        "route_heading_deg",
        "headwind_archive_ms",
        "headwind_effective_ms",
        "GHI_archive",
        "GHI_effective",
        "Tamb_archive_C",
        "Tcell_effective_C",
        "solar_power_w_obs",
        "battery_power_w_obs",
        "battery_current_a",
        "battery_voltage_v",
        "dt_sec",
        "lat",
        "lon",
        "alt_m",
    ]
    numeric_cols.extend(
        column
        for column in ("DNI_archive", "DHI_archive", "BHI_archive")
        if column in work.columns
    )
    for key in numeric_cols:
        work[key] = pd.to_numeric(work[key], errors="coerce")
    speed_ms = work["speed_kmh"].fillna(0.0) / 3.6
    dt = work["dt_sec"].replace(0.0, np.nan)
    accel = speed_ms.diff() / dt
    segment_start = work["day"].ne(work["day"].shift(1))
    time_gap = work["time_utc"].diff().dt.total_seconds().fillna(0.0) > 7200.0
    accel.loc[segment_start | time_gap] = 0.0
    work["accel_ms2"] = (
        accel.replace([np.inf, -np.inf], np.nan)
        .rolling(5, center=True, min_periods=1)
        .median()
        .fillna(0.0)
        .clip(lower=-1.5, upper=1.5)
    )
    work = apply_actual_event_annotations(work, actual_event_payload)
    work = truncate_at_retire_event(work, actual_event_payload)
    if base_model is not None:
        work = apply_sensor_quality_annotations(work, base_model=base_model, options=options)
    return work                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_terminal_anchor(log_df: pd.DataFrame, ocv_df: pd.DataFrame, base_model, anchor_km: float) -> Dict[str, float]:  # [関数定義] build_terminal_anchor の処理実行ブロック
    valid = (
        np.isfinite(log_df["battery_voltage_v"])
        & np.isfinite(log_df["battery_current_a"])
        & np.isfinite(log_df["Tamb_archive_C"])
        & np.isfinite(log_df["s_km"])
        & (log_df["battery_voltage_v"] >= INVALID_PACK_VOLTAGE_MIN_V)
        & (~log_df["exclude_voltage_fit"].fillna(False).astype(bool))
    )
    window = log_df.loc[valid & (np.abs(log_df["s_km"] - float(anchor_km)) <= 1.5)].copy()
    if window.empty:
        window = log_df.loc[valid].tail(6).copy()
    else:
        window = window.tail(min(6, len(window))).copy()
    soc_targets = [
        infer_soc_from_loaded_state(
            float(row.battery_voltage_v),
            float(row.battery_current_a),
            float(row.Tamb_archive_C),
            ocv_df,
            base_model,
        )
        for row in window.itertuples(index=False)
    ]
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "count": int(len(window)),
        "s_km": float(window["s_km"].median()),
        "time_utc": pd.to_datetime(window["time_utc"].iloc[-1], utc=True).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "voltage_v": float(window["battery_voltage_v"].median()),
        "current_a": float(window["battery_current_a"].median()),
        "temp_c": float(window["Tamb_archive_C"].median()),
        "soc_target": float(np.nanmedian(np.asarray(soc_targets, dtype=float))),
    }


def terminal_metrics(                                              # [関数定義] terminal_metrics の処理実行ブロック
    replay_df: pd.DataFrame,
    ocv_df: pd.DataFrame,
    base_model,
    batt: BatteryFitResult,
    anchor_km: float,
    *,
    terminal_anchor: dict | None = None,
) -> Dict[str, float]:
    valid = (
        np.isfinite(replay_df["battery_voltage_v_obs"])
        & np.isfinite(replay_df["battery_current_a_obs"])
        & np.isfinite(replay_df["Tamb_C"])
        & np.isfinite(replay_df["s_km"])
        & (replay_df["battery_voltage_v_obs"] >= INVALID_PACK_VOLTAGE_MIN_V)
        & (~replay_df["exclude_voltage_fit"].fillna(False).astype(bool))
    )
    window = replay_df.loc[valid & (np.abs(replay_df["s_km"] - float(anchor_km)) <= 1.5)].copy()
    if window.empty:
        window = replay_df.loc[valid].tail(6).copy()
    else:
        window = window.tail(min(6, len(window))).copy()
    terminal_anchor = terminal_anchor if isinstance(terminal_anchor, dict) else {}
    if "soc_target" in terminal_anchor and terminal_anchor.get("soc_target") not in (None, ""):
        soc_obs_value = float(terminal_anchor["soc_target"])
    else:
        soc_obs = [
            infer_soc_from_loaded_state(
                float(row.battery_voltage_v_obs),
                float(row.battery_current_a_obs),
                float(row.Tamb_C),
                ocv_df,
                base_model,
                rint_scale=float(batt.rint_scale),
                r_line_ohm=float(batt.r_line_ohm),
            )
            for row in window.itertuples(index=False)
        ]
        soc_obs_value = float(np.nanmedian(np.asarray(soc_obs, dtype=float)))
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "retire_anchor_s_km": float(window["s_km"].median()),
        "retire_anchor_voltage_obs_v": float(window["battery_voltage_v_obs"].median()),
        "retire_anchor_voltage_pred_v": float(window["battery_voltage_v_pred"].median()),
        "retire_anchor_soc_obs": soc_obs_value,
        "retire_anchor_soc_pred": float(window["soc_pred"].median()),
        "retire_anchor_soc_error": float(window["soc_pred"].median() - soc_obs_value),
    }


def replay_day_metrics(replay_df: pd.DataFrame) -> list[dict]:     # [関数定義] replay_day_metrics の処理実行ブロック
    rows: list[dict] = []
    for day, group in replay_df.groupby("day", dropna=False):
        power_mask = ~group["exclude_power_fit"]
        volt_mask = ~group["exclude_voltage_fit"]
        power_resid = group.loc[power_mask, "battery_power_w_obs"] - group.loc[power_mask, "battery_power_w_pred"]
        volt_resid = group.loc[volt_mask, "battery_voltage_v_obs"] - group.loc[volt_mask, "battery_voltage_v_pred"]
        rows.append(
            {
                "day": int(day) if pd.notna(day) else -1,
                "distance_end_km": float(pd.to_numeric(group["s_km"], errors="coerce").max()),
                "final_soc_pred": float(pd.to_numeric(group["soc_pred"], errors="coerce").iloc[-1]),
                "power_rmse_clean_w": float(np.sqrt(np.mean(power_resid.to_numpy(dtype=float) ** 2))) if len(power_resid) else float("nan"),
                "voltage_rmse_clean_v": float(np.sqrt(np.mean(volt_resid.to_numpy(dtype=float) ** 2))) if len(volt_resid) else float("nan"),
                "excluded_power_points": int(pd.to_numeric(group["exclude_power_fit"], errors="coerce").fillna(False).astype(bool).sum()),
                "excluded_voltage_points": int(pd.to_numeric(group["exclude_voltage_fit"], errors="coerce").fillna(False).astype(bool).sum()),
            }
        )
    return rows                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def identification_selection_score(metrics: Dict[str, float]) -> float:  # [関数定義] identification_selection_score の処理実行ブロック
    power_rmse = float(metrics.get("power_rmse_clean_w", float("inf")))
    robust_power_rmse = float(metrics.get("power_residual_mean_120s_rmse_w", power_rmse))
    energy_rmse_25km = float(metrics.get("energy_error_25km_rmse_wh", float("inf")))
    power_term = 0.60 * power_rmse + 0.40 * robust_power_rmse
    energy_term = 0.50 * energy_rmse_25km
    independent_pv_term = 0.25 * float(
        metrics.get("end_to_end_moving_pv_rmse_w", float("inf"))
    )
    vehicle_voltage_term = 8.0 * float(metrics.get("voltage_rmse_clean_v", float("inf")))
    battery_voltage_term = 4.0 * float(
        metrics.get("battery_conditional_voltage_rmse_clean_v", float("inf"))
    )
    battery_terminal_term = 80.0 * abs(
        float(metrics.get("battery_conditional_retire_anchor_soc_error", float("inf")))
    )
    vehicle_terminal_term = 1000.0 * abs(
        float(metrics.get("retire_anchor_soc_error", float("inf")))
    )
    end_to_end_terminal_term = 300.0 * abs(
        float(metrics.get("end_to_end_retire_anchor_soc_error", float("inf")))
    )
    fit_window_term = 0.35 * float(metrics.get("power_rmse_fit_window_w", power_term))
    return (                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        power_term
        + energy_term
        + independent_pv_term
        + vehicle_voltage_term
        + battery_voltage_term
        + battery_terminal_term
        + vehicle_terminal_term
        + end_to_end_terminal_term
        + fit_window_term
    )


def condition_vehicle_fit_on_measured_pv(frame: pd.DataFrame) -> pd.DataFrame:  # [関数定義] condition_vehicle_fit_on_measured_pv の処理実行ブロック
    """Use measured array power when identifying vehicle-side coefficients.

    Forecast/PV-map error is validated separately.  Feeding predicted PV into the
    vehicle fit otherwise lets a cloudy-day irradiance error masquerade as CdA,
    rolling resistance, or drivetrain-efficiency error.
    """
    out = frame.copy()
    predicted = pd.to_numeric(out.get("solar_power_w_model"), errors="coerce")
    measured = pd.to_numeric(out.get("solar_power_w_obs"), errors="coerce")
    if predicted is None or measured is None:
        return out                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    measured = measured.clip(lower=0.0)
    usable = measured.notna()
    out["solar_power_w_forecast_model"] = predicted
    out["solar_power_w_model"] = predicted.where(~usable, measured)
    out["vehicle_fit_solar_source"] = np.where(usable, "measured", "forecast_fallback")
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def calibrate_solar_measurement_to_pack(                           # [関数定義] calibrate_solar_measurement_to_pack の処理実行ブロック
    frame: pd.DataFrame,
    *,
    known_aux_power_w: float,
    stopped_speed_kmh: float = 1.0,
    minimum_solar_power_w: float = 50.0,
    minimum_samples: int = 500,
    gain_bounds: tuple[float, float] = (0.70, 1.05),
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """Calibrate the ZP solar channel from stationary DC-bus power balance.

    At zero wheel speed, the independently measured channels satisfy
    ``P_batt = P_aux - gain * P_solar_raw``.  The known 21 W auxiliary load
    anchors the intercept, so the fitted gain cannot absorb vehicle drag or
    forecast irradiance error.
    """
    out = frame.copy()
    raw_column = (
        "solar_power_w_obs_raw"
        if "solar_power_w_obs_raw" in out.columns
        else "solar_power_w_obs"
    )
    raw = pd.to_numeric(out.get(raw_column), errors="coerce")
    battery = pd.to_numeric(out.get("battery_power_w_obs"), errors="coerce")
    speed = pd.to_numeric(out.get("speed_kmh"), errors="coerce")
    excluded = pd.Series(False, index=out.index)
    if "exclude_power_fit" in out.columns:
        excluded = out["exclude_power_fit"].fillna(False).astype(bool)
    mask = (
        (~excluded)
        & raw.notna()
        & battery.notna()
        & speed.notna()
        & (speed <= float(stopped_speed_kmh))
        & (raw >= float(minimum_solar_power_w))
    )
    x = raw.loc[mask].to_numpy(dtype=float)
    y = battery.loc[mask].to_numpy(dtype=float)
    result: Dict[str, Any] = {
        "method": "stationary DC-bus balance P_batt=P_aux-gain*P_solar_raw with robust Huber loss",
        "known_aux_power_w": float(known_aux_power_w),
        "sample_count": int(len(x)),
        "minimum_samples": int(minimum_samples),
        "gain_bounds": [float(gain_bounds[0]), float(gain_bounds[1])],
        "accepted": False,
        "gain_to_pack": 1.0,
        "raw_column": raw_column,
        "corrected_column": "solar_power_w_obs",
    }
    gain = 1.0
    if len(x) >= int(minimum_samples):
        fixed = least_squares(
            lambda theta: y - (float(known_aux_power_w) - float(theta[0]) * x),
            x0=np.array([0.93], dtype=float),
            bounds=(np.array([gain_bounds[0]]), np.array([gain_bounds[1]])),
            loss="huber",
            f_scale=20.0,
        )
        diagnostic = least_squares(
            lambda theta: y - (float(theta[0]) - float(theta[1]) * x),
            x0=np.array([float(known_aux_power_w), float(fixed.x[0])], dtype=float),
            bounds=(
                np.array([0.0, gain_bounds[0]], dtype=float),
                np.array([100.0, gain_bounds[1]], dtype=float),
            ),
            loss="huber",
            f_scale=20.0,
        )
        candidate_gain = float(fixed.x[0])
        residual = y - (float(known_aux_power_w) - candidate_gain * x)
        daily_gains: Dict[str, float] = {}
        if "day" in out.columns:
            for day_value, group in out.loc[mask].groupby("day", dropna=False):
                gx = pd.to_numeric(group[raw_column], errors="coerce").to_numpy(dtype=float)
                gy = pd.to_numeric(group["battery_power_w_obs"], errors="coerce").to_numpy(dtype=float)
                if len(gx) < 50:
                    continue
                day_fit = least_squares(
                    lambda theta: gy - (float(known_aux_power_w) - float(theta[0]) * gx),
                    x0=np.array([candidate_gain], dtype=float),
                    bounds=(np.array([gain_bounds[0]]), np.array([gain_bounds[1]])),
                    loss="huber",
                    f_scale=20.0,
                )
                daily_gains[str(day_value)] = float(day_fit.x[0])
        daily_values = np.asarray(list(daily_gains.values()), dtype=float)
        daily_std = float(np.std(daily_values, ddof=1)) if len(daily_values) >= 2 else float("nan")
        free_intercept = float(diagnostic.x[0])
        accepted = bool(
            np.isfinite(candidate_gain)
            and float(gain_bounds[0]) < candidate_gain < float(gain_bounds[1])
            and abs(free_intercept - float(known_aux_power_w)) <= 5.0
            and (not np.isfinite(daily_std) or daily_std <= 0.02)
        )
        result.update(
            {
                "accepted": accepted,
                "gain_to_pack": candidate_gain if accepted else 1.0,
                "free_intercept_w": free_intercept,
                "free_intercept_error_w": free_intercept - float(known_aux_power_w),
                "residual_rmse_w": float(np.sqrt(np.mean(np.square(residual)))),
                "residual_mae_w": float(np.mean(np.abs(residual))),
                "residual_median_w": float(np.median(residual)),
                "daily_gain_to_pack": daily_gains,
                "daily_gain_std": daily_std,
                "physical_basis": "independent ZP solar-current and battery-current channels at zero traction power",
            }
        )
        if accepted:
            gain = candidate_gain
    out["solar_power_w_obs_raw"] = raw
    out["solar_measurement_gain_to_pack"] = float(gain)
    out["solar_power_w_obs"] = raw * float(gain)
    return out, result                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _shift_acceleration_within_segments(                           # [関数定義] _shift_acceleration_within_segments の処理実行ブロック
    frame: pd.DataFrame,
    sample_shift: int,
    acceleration: pd.Series | None = None,
) -> pd.Series:
    """Shift a derived acceleration trace without leaking across race days or log gaps."""
    if acceleration is None:
        acceleration = pd.to_numeric(frame["accel_ms2"], errors="coerce")
    segment_id = pd.Series(replay_segment_start_mask(frame), index=frame.index).cumsum()
    return acceleration.groupby(segment_id).shift(int(sample_shift))  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _acceleration_trace_from_speed(                                # [関数定義] _acceleration_trace_from_speed の処理実行ブロック
    frame: pd.DataFrame,
    *,
    method: str,
    window_samples: int,
) -> pd.Series:
    speed_ms = pd.to_numeric(frame["speed_kmh"], errors="coerce").fillna(0.0) / 3.6
    dt_sec = pd.to_numeric(frame.get("dt_sec"), errors="coerce").replace(0.0, np.nan)
    raw = speed_ms.diff() / dt_sec
    segment_start = pd.Series(replay_segment_start_mask(frame), index=frame.index)
    raw.loc[segment_start] = 0.0
    raw = raw.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    segment_id = segment_start.cumsum()
    window = max(1, int(window_samples))
    if window % 2 == 0:
        window += 1
    smoothed = pd.Series(index=frame.index, dtype=float)
    for _, group in raw.groupby(segment_id):
        if str(method).lower() == "savgol":
            usable_window = min(window, len(group) if len(group) % 2 else len(group) - 1)
            if usable_window >= 5:
                smoothed.loc[group.index] = savgol_filter(
                    group.to_numpy(dtype=float),
                    usable_window,
                    min(2, usable_window - 1),
                    mode="interp",
                )
            else:
                smoothed.loc[group.index] = group
        elif str(method).lower() == "median":
            smoothed.loc[group.index] = group.rolling(
                window, center=True, min_periods=1
            ).median()
        else:
            raise ValueError(f"unsupported acceleration filter method: {method}")
    return smoothed.fillna(0.0).clip(lower=-1.5, upper=1.5)        # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _bilinear_interp_array(x_grid, y_grid, values, x, y) -> np.ndarray:  # [関数定義] _bilinear_interp_array の処理実行ブロック
    x_grid = np.asarray(x_grid, dtype=float)
    y_grid = np.asarray(y_grid, dtype=float)
    values = np.asarray(values, dtype=float)
    x = np.clip(np.asarray(x, dtype=float), x_grid[0], x_grid[-1])
    y = np.clip(np.asarray(y, dtype=float), y_grid[0], y_grid[-1])
    ix = np.clip(np.searchsorted(x_grid, x) - 1, 0, len(x_grid) - 2)
    iy = np.clip(np.searchsorted(y_grid, y) - 1, 0, len(y_grid) - 2)
    x0, x1 = x_grid[ix], x_grid[ix + 1]
    y0, y1 = y_grid[iy], y_grid[iy + 1]
    wx = np.divide(x - x0, x1 - x0, out=np.zeros_like(x), where=x1 != x0)
    wy = np.divide(y - y0, y1 - y0, out=np.zeros_like(y), where=y1 != y0)
    return (                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        (1.0 - wx) * (1.0 - wy) * values[ix, iy]
        + wx * (1.0 - wy) * values[ix + 1, iy]
        + (1.0 - wx) * wy * values[ix, iy + 1]
        + wx * wy * values[ix + 1, iy + 1]
    )


def _map_efficiency_array(base_model, maps, speed_ms, torque_nm, *, regen: bool) -> np.ndarray:  # [関数定義] _map_efficiency_array の処理実行ブロック
    mode = str(base_model.drive_mode or "default").lower()
    if mode in {"eco", "power"}:
        selected_power = np.full(len(speed_ms), mode == "power", dtype=bool)
    else:
        eco_max = base_model.tau_max.get("eco", base_model.tau_max.get("default", 0.0))
        selected_power = torque_nm > (
            float(eco_max) + float(base_model.drive_mode_tau_margin)
        )
    result = np.empty(len(speed_ms), dtype=float)
    for use_power in (False, True):
        selected = selected_power == use_power
        key = "power" if use_power else "eco"
        grid = maps.get(key, maps["default"])
        result[selected] = _bilinear_interp_array(
            *grid, speed_ms[selected], torque_nm[selected]
        )
    # The candidate scale is applied by the caller. Inheriting the scale from
    # the input profile here would apply old_scale * candidate_scale during
    # fitting, while the generated profile contains candidate_scale only.
    return np.clip(result, 0.40 if regen else 0.55, 0.95 if regen else 0.99)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _motion_predictions_for_acceleration(                          # [関数定義] _motion_predictions_for_acceleration の処理実行ブロック
    frame: pd.DataFrame,
    acceleration: pd.Series,
    base_model,
    mot: MotionFitResult,
) -> np.ndarray:
    """Vectorized equivalent of motion_power_prediction for filter/lag search."""
    speed_ms = (
        pd.to_numeric(frame["speed_kmh"], errors="coerce").fillna(0.0).to_numpy()
        / 3.6
    )
    slope = pd.to_numeric(frame["slope_pct"], errors="coerce").fillna(0.0).to_numpy()
    headwind = (
        pd.to_numeric(frame["headwind_archive_ms"], errors="coerce").fillna(0.0).to_numpy()
        * float(mot.headwind_gain)
    )
    solar = (
        pd.to_numeric(frame["solar_power_w_obs"], errors="coerce").fillna(0.0).to_numpy()
    )
    theta = np.arctan((slope * float(mot.grade_scale)) / 100.0)
    relative_speed = np.maximum(0.0, speed_ms + headwind)
    ambient_source = frame["Tamb_archive_C"] if "Tamb_archive_C" in frame else pd.Series(25.0, index=frame.index)
    elevation_source = frame["alt_m"] if "alt_m" in frame else pd.Series(0.0, index=frame.index)
    ambient = pd.to_numeric(ambient_source, errors="coerce").fillna(25.0).to_numpy()
    elevation = pd.to_numeric(elevation_source, errors="coerce").fillna(0.0).to_numpy()
    if str(base_model.p.air_density_mode or "constant").lower() == "ideal_gas_altitude":
        altitude = np.clip(elevation, -500.0, 11000.0)
        pressure_ratio = np.maximum(0.05, 1.0 - 0.0065 * altitude / 288.15) ** 5.255877
        pressure = float(base_model.p.air_density_reference_pressure_pa) * pressure_ratio
        air_density = pressure / (287.05 * np.maximum(180.0, ambient + 273.15))
    else:
        air_density = np.full(len(frame), float(base_model.p.rho), dtype=float)
    normal_force = base_model.p.m * base_model.p.g * np.cos(theta)
    force = (
        0.5 * air_density * float(mot.cda) * relative_speed**2
        + float(mot.crr) * normal_force
        + base_model.p.m * base_model.p.g * np.sin(theta)
    )
    p_mech = force * speed_ms + (
        base_model.p.m * acceleration.fillna(0.0).to_numpy(dtype=float) * speed_ms
    )
    omega_wheel = speed_ms / float(base_model.p.wheel_radius)
    torque = np.abs(p_mech) / (omega_wheel + 1.0e-3) / float(base_model.p.gear_ratio)
    drive_eff = _map_efficiency_array(
        base_model, base_model.maps_drive, speed_ms, torque, regen=False
    )
    drive_eff = np.clip(drive_eff * float(mot.drive_eff_scale), 0.55, 0.99)
    regen_eff = _map_efficiency_array(
        base_model, base_model.maps_regen, speed_ms, torque, regen=True
    )
    regen_eff = np.clip(regen_eff * float(mot.drive_eff_scale), 0.40, 0.95)
    positive = p_mech >= 0.0
    electrical = np.empty(len(frame), dtype=float)
    electrical[positive] = p_mech[positive] / np.maximum(
        drive_eff[positive] * base_model.p.gear_eta * base_model.p.inverter_eta,
        1.0e-6,
    )
    electrical[~positive] = (
        -float(np.clip(mot.regen_utilization, 0.0, 1.0))
        * regen_eff[~positive]
        * base_model.p.gear_eta
        * base_model.p.inverter_eta
        * np.abs(p_mech[~positive])
    )
    return electrical + float(mot.p_aux_w) - solar                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fit_acceleration_timestamp_alignment(                          # [関数定義] fit_acceleration_timestamp_alignment の処理実行ブロック
    frame: pd.DataFrame,
    base_model,
    mot: MotionFitResult,
    options: dict | None = None,
) -> tuple[pd.DataFrame, Dict[str, Any]]:
    """Identify the filter and timestamp offset of GPS-derived acceleration.

    Vehicle mass remains fixed. Candidate observation filters and offsets are
    fitted on all but the last race day and adopted only when the held-out last
    day does not regress. This models quantized/asynchronous GNSS observations;
    it is not a tunable vehicle force or a live-command filter.
    """
    cfg = options if isinstance(options, dict) else {}
    enabled = bool(cfg.get("enabled", True))
    required = {
        "time_utc",
        "day",
        "speed_kmh",
        "slope_pct",
        "headwind_archive_ms",
        "solar_power_w_obs",
        "battery_power_w_obs",
        "exclude_power_fit",
        "accel_ms2",
    }
    if not enabled or not required.issubset(frame.columns):
        return frame.copy(), {                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "enabled": enabled,
            "adopted": False,
            "reason": "disabled_or_missing_columns",
        }

    out = frame.copy()
    out["accel_ms2_previous"] = pd.to_numeric(out["accel_ms2"], errors="coerce")
    out["accel_ms2_raw"] = _acceleration_trace_from_speed(
        out, method="median", window_samples=1
    )
    dt_sec = pd.to_numeric(out.get("dt_sec"), errors="coerce")
    usable_dt = dt_sec[np.isfinite(dt_sec) & (dt_sec > 0.0) & (dt_sec <= 60.0)]
    sample_period_sec = float(np.median(usable_dt)) if len(usable_dt) else 5.0
    raw_candidates = cfg.get(
        "candidate_lag_sec",
        [-30.0, -20.0, -15.0, -10.0, -5.0, 0.0, 5.0, 10.0, 15.0, 20.0, 30.0],
    )
    candidate_lag_sec = sorted(
        set(float(value) for value in raw_candidates if np.isfinite(float(value))) | {0.0}
    )
    raw_filters = cfg.get(
        "candidate_filters",
        [
            {"method": "median", "window_samples": 5},
            {"method": "median", "window_samples": 9},
            {"method": "median", "window_samples": 15},
            {"method": "savgol", "window_samples": 11},
            {"method": "savgol", "window_samples": 15},
            {"method": "savgol", "window_samples": 21},
        ],
    )
    candidate_filters: list[tuple[str, int]] = []
    for item in raw_filters:
        if isinstance(item, dict):
            method = str(item.get("method", "median")).strip().lower()
            window = int(item.get("window_samples", 5))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            method, window = str(item[0]).strip().lower(), int(item[1])
        else:
            continue
        if method in {"median", "savgol"}:
            candidate_filters.append((method, max(1, window)))
    candidate_filters = list(dict.fromkeys(candidate_filters + [("median", 5)]))

    day_values = pd.to_numeric(out["day"], errors="coerce")
    finite_days = sorted(set(int(value) for value in day_values[np.isfinite(day_values)]))
    configured_holdout_day = int(cfg.get("holdout_day", 0) or 0)
    holdout_day = configured_holdout_day if configured_holdout_day > 0 else int(finite_days[-1] if finite_days else 0)
    base_valid = (
        (~out["exclude_power_fit"].fillna(True).astype(bool))
        & (pd.to_numeric(out["speed_kmh"], errors="coerce") >= float(cfg.get("min_speed_kmh", 12.0)))
        & np.isfinite(pd.to_numeric(out["battery_power_w_obs"], errors="coerce"))
        & np.isfinite(pd.to_numeric(out["solar_power_w_obs"], errors="coerce"))
    )
    train_mask = base_valid & (day_values != holdout_day)
    validation_mask = base_valid & (day_values == holdout_day)
    if int(train_mask.sum()) < int(cfg.get("minimum_train_samples", 500)):
        return out, {                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "enabled": True,
            "adopted": False,
            "reason": "insufficient_training_samples",
            "training_sample_count": int(train_mask.sum()),
            "validation_sample_count": int(validation_mask.sum()),
        }

    observed = pd.to_numeric(out["battery_power_w_obs"], errors="coerce").to_numpy(dtype=float)
    records: list[Dict[str, float | int | str]] = []
    traces: Dict[tuple[str, int, float], pd.Series] = {}
    for filter_method, filter_window in candidate_filters:
        filtered = _acceleration_trace_from_speed(
            out, method=filter_method, window_samples=filter_window
        )
        for lag_sec in candidate_lag_sec:
            sample_shift = int(round(float(lag_sec) / sample_period_sec))
            actual_lag_sec = float(sample_shift * sample_period_sec)
            aligned = _shift_acceleration_within_segments(
                out, sample_shift, acceleration=filtered
            )
            predicted = _motion_predictions_for_acceleration(
                out, aligned, base_model, mot
            )

            def rmse(mask: pd.Series) -> float:                    # [関数定義] rmse の処理実行ブロック
                use = mask.to_numpy(dtype=bool) & np.isfinite(predicted) & np.isfinite(observed)
                return (                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
                    float(np.sqrt(np.mean(np.square(observed[use] - predicted[use]))))
                    if use.any()
                    else float("nan")
                )

            records.append(
                {
                    "filter_method": filter_method,
                    "filter_window_samples": int(filter_window),
                    "lag_sec": actual_lag_sec,
                    "sample_shift": int(sample_shift),
                    "training_rmse_w": rmse(train_mask),
                    "validation_rmse_w": rmse(validation_mask),
                }
            )
            traces[(filter_method, int(filter_window), actual_lag_sec)] = aligned

    baseline = next(
        (
            row
            for row in records
            if row["filter_method"] == "median"
            and int(row["filter_window_samples"]) == 5
            and abs(float(row["lag_sec"])) < 0.5 * sample_period_sec
        ),
        min(records, key=lambda row: abs(float(row["lag_sec"]))),
    )
    finite_records = [row for row in records if np.isfinite(float(row["training_rmse_w"]))]
    best = min(finite_records, key=lambda row: float(row["training_rmse_w"]))
    train_improvement = float(baseline["training_rmse_w"]) - float(best["training_rmse_w"])
    validation_ratio = (
        float(best["validation_rmse_w"]) / max(float(baseline["validation_rmse_w"]), 1.0e-9)
        if np.isfinite(float(best["validation_rmse_w"]))
        and np.isfinite(float(baseline["validation_rmse_w"]))
        else float("nan")
    )
    enough_validation = int(validation_mask.sum()) >= int(cfg.get("minimum_validation_samples", 100))
    adopted = bool(
        train_improvement >= float(cfg.get("minimum_training_improvement_w", 2.0))
        and (
            not enough_validation
            or (np.isfinite(validation_ratio) and validation_ratio <= float(cfg.get("maximum_validation_rmse_ratio", 1.02)))
        )
    )
    selected = best if adopted else baseline
    selected_lag = float(selected["lag_sec"])
    selected_method = str(selected["filter_method"])
    selected_window = int(selected["filter_window_samples"])
    lag_search_min = float(min(candidate_lag_sec))
    lag_search_max = float(max(candidate_lag_sec))
    lag_boundary_hit = bool(
        math.isclose(selected_lag, lag_search_min, abs_tol=0.5 * sample_period_sec)
        or math.isclose(selected_lag, lag_search_max, abs_tol=0.5 * sample_period_sec)
    )
    out["accel_ms2"] = traces[(selected_method, selected_window, selected_lag)].fillna(
        0.0
    ).clip(lower=-1.5, upper=1.5)
    out["acceleration_timestamp_lag_sec"] = selected_lag
    out["acceleration_filter_method"] = selected_method
    out["acceleration_filter_window_samples"] = selected_window
    return out, {                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "enabled": True,
        "adopted": adopted,
        "method": "fixed-mass GNSS acceleration filter/lag selection with last-race-day holdout",
        "sample_period_sec": sample_period_sec,
        "selected_filter_method": selected_method,
        "selected_filter_window_samples": selected_window,
        "selected_filter_window_sec": selected_window * sample_period_sec,
        "selected_lag_sec": selected_lag,
        "lag_search_min_sec": lag_search_min,
        "lag_search_max_sec": lag_search_max,
        "lag_search_boundary_hit": lag_boundary_hit,
        "holdout_day": holdout_day,
        "training_sample_count": int(train_mask.sum()),
        "validation_sample_count": int(validation_mask.sum()),
        "baseline_training_rmse_w": float(baseline["training_rmse_w"]),
        "selected_training_rmse_w": float(selected["training_rmse_w"]),
        "baseline_validation_rmse_w": float(baseline["validation_rmse_w"]),
        "selected_validation_rmse_w": float(selected["validation_rmse_w"]),
        "training_improvement_w": float(
            float(baseline["training_rmse_w"]) - float(selected["training_rmse_w"])
        ),
        "validation_rmse_ratio": validation_ratio if adopted else 1.0,
        "candidates": records,
    }


def _grade_from_smoothed_elevation(                                # [関数定義] _grade_from_smoothed_elevation の処理実行ブロック
    distance_km: np.ndarray,
    elevation_m: np.ndarray,
    smoothing_window_km: float,
) -> np.ndarray:
    spacing = float(np.median(np.diff(distance_km)))
    samples = max(3, int(round(float(smoothing_window_km) / max(spacing, 1.0e-9))))
    if samples % 2 == 0:
        samples += 1
    samples = min(samples, len(elevation_m) if len(elevation_m) % 2 else len(elevation_m) - 1)
    if samples < 3:
        return np.gradient(elevation_m, distance_km) * 0.1         # [戻り値] 計算結果・計算状態の呼び出し元への返却
    smoothed = savgol_filter(
        elevation_m,
        samples,
        min(2, samples - 1),
        mode="interp",
    )
    # elevation [m] / distance [km] * 0.1 converts to percent grade.
    return np.gradient(smoothed, distance_km) * 0.1                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fit_grade_observation_alignment(                               # [関数定義] fit_grade_observation_alignment の処理実行ブロック
    frame: pd.DataFrame,
    route_profile_csv: Path,
    output_csv: Path,
    base_model,
    mot: MotionFitResult,
    options: dict | None = None,
) -> tuple[pd.DataFrame, Dict[str, Any], Path | None]:
    """Cross-validate a DEM smoothing length and distance alignment.

    This stage calibrates the route observation, not vehicle mass or resistance.
    The selected route stores the unscaled DEM grade. ``grade_scale`` remains a
    separately fitted model coefficient in the following motion fit.
    """
    cfg = options if isinstance(options, dict) else {}
    if not bool(cfg.get("enabled", True)) or not route_profile_csv.is_file():
        return frame.copy(), {                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "enabled": bool(cfg.get("enabled", True)),
            "adopted": False,
            "reason": "disabled_or_route_profile_missing",
        }, None

    route = pd.read_csv(route_profile_csv)
    distance_column = next(
        (key for key in ("dist_km", "s_km", "distance_km") if key in route.columns),
        None,
    )
    elevation_column = next(
        (key for key in ("elev_m", "elev_dem_m", "alt_m", "altitude_m") if key in route.columns),
        None,
    )
    if distance_column is None or elevation_column is None:
        return frame.copy(), {                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "enabled": True,
            "adopted": False,
            "reason": "route_profile_requires_distance_and_elevation",
            "route_profile_csv": str(route_profile_csv),
        }, None

    source = pd.DataFrame(
        {
            "dist_km": pd.to_numeric(route[distance_column], errors="coerce"),
            "elev_m": pd.to_numeric(route[elevation_column], errors="coerce"),
        }
    ).dropna()
    source = source.groupby("dist_km", as_index=False).mean().sort_values("dist_km")
    if len(source) < 21 or not np.all(np.diff(source["dist_km"].to_numpy()) > 0.0):
        return frame.copy(), {                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "enabled": True,
            "adopted": False,
            "reason": "insufficient_monotonic_route_elevation_samples",
            "sample_count": int(len(source)),
        }, None

    required = {
        "day",
        "s_km",
        "speed_kmh",
        "accel_ms2",
        "headwind_archive_ms",
        "solar_power_w_obs",
        "battery_power_w_obs",
        "exclude_power_fit",
        "slope_pct",
    }
    if not required.issubset(frame.columns):
        return frame.copy(), {                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "enabled": True,
            "adopted": False,
            "reason": "replay_missing_grade_validation_columns",
            "missing_columns": sorted(required.difference(frame.columns)),
        }, None

    out = frame.copy()
    observed = pd.to_numeric(out["battery_power_w_obs"], errors="coerce").to_numpy(dtype=float)
    common = (
        (~out["exclude_power_fit"].fillna(False).astype(bool))
        & pd.to_numeric(out["speed_kmh"], errors="coerce").ge(12.0)
        & np.isfinite(observed)
        & np.isfinite(pd.to_numeric(out["s_km"], errors="coerce"))
    )
    holdout_day = int(cfg.get("holdout_day", pd.to_numeric(out["day"], errors="coerce").max()))
    train_mask = (common & pd.to_numeric(out["day"], errors="coerce").ne(holdout_day)).to_numpy(dtype=bool)
    validation_mask = (common & pd.to_numeric(out["day"], errors="coerce").eq(holdout_day)).to_numpy(dtype=bool)
    min_train = int(cfg.get("minimum_train_samples", 500))
    min_validation = int(cfg.get("minimum_validation_samples", 100))
    if int(train_mask.sum()) < min_train or int(validation_mask.sum()) < min_validation:
        return out, {                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "enabled": True,
            "adopted": False,
            "reason": "insufficient_train_or_validation_samples",
            "training_sample_count": int(train_mask.sum()),
            "validation_sample_count": int(validation_mask.sum()),
        }, None

    acceleration = pd.to_numeric(out["accel_ms2"], errors="coerce").fillna(0.0)

    def rmse(predicted: np.ndarray, mask: np.ndarray) -> float:    # [関数定義] rmse の処理実行ブロック
        usable = mask & np.isfinite(predicted) & np.isfinite(observed)
        return float(np.sqrt(np.mean(np.square(observed[usable] - predicted[usable]))))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    baseline_predicted = _motion_predictions_for_acceleration(
        out, acceleration, base_model, mot
    )
    baseline_training_rmse = rmse(baseline_predicted, train_mask)
    baseline_validation_rmse = rmse(baseline_predicted, validation_mask)

    windows = [float(value) for value in cfg.get(
        "smoothing_windows_km", [0.5, 1.1, 2.1, 3.1, 5.1]
    )]
    offsets = [float(value) for value in cfg.get(
        "distance_offsets_km", np.round(np.arange(-0.5, 0.5001, 0.1), 6).tolist()
    )]
    grade_scales = [float(value) for value in cfg.get(
        "grade_scales", np.round(np.arange(0.50, 1.0001, 0.05), 6).tolist()
    )]
    distance = source["dist_km"].to_numpy(dtype=float)
    elevation = source["elev_m"].to_numpy(dtype=float)
    replay_distance = pd.to_numeric(out["s_km"], errors="coerce").to_numpy(dtype=float)
    records: list[Dict[str, float]] = []
    route_slopes: Dict[tuple[float, float], np.ndarray] = {}
    for window_km in windows:
        source_slope = _grade_from_smoothed_elevation(distance, elevation, window_km)
        for offset_km in offsets:
            aligned_route_slope = np.interp(
                distance + offset_km,
                distance,
                source_slope,
                left=source_slope[0],
                right=source_slope[-1],
            )
            route_slopes[(window_km, offset_km)] = aligned_route_slope
            candidate_frame = out.copy()
            candidate_frame["slope_pct"] = np.interp(
                replay_distance,
                distance,
                aligned_route_slope,
                left=aligned_route_slope[0],
                right=aligned_route_slope[-1],
            )
            for grade_scale in grade_scales:
                candidate_mot = MotionFitResult(
                    **{**mot.__dict__, "grade_scale": float(grade_scale)}
                )
                predicted = _motion_predictions_for_acceleration(
                    candidate_frame, acceleration, base_model, candidate_mot
                )
                records.append(
                    {
                        "smoothing_window_km": window_km,
                        "distance_offset_km": offset_km,
                        "provisional_grade_scale": grade_scale,
                        "training_rmse_w": rmse(predicted, train_mask),
                        "validation_rmse_w": rmse(predicted, validation_mask),
                    }
                )

    best = min(records, key=lambda row: float(row["training_rmse_w"]))
    training_improvement = baseline_training_rmse - float(best["training_rmse_w"])
    validation_ratio = float(best["validation_rmse_w"]) / max(baseline_validation_rmse, 1.0e-9)
    adopted = bool(
        training_improvement >= float(cfg.get("minimum_training_improvement_w", 5.0))
        and validation_ratio <= float(cfg.get("maximum_validation_rmse_ratio", 1.02))
    )
    if not adopted:
        return out, {                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "enabled": True,
            "adopted": False,
            "reason": "training_gain_or_holdout_gate_failed",
            "method": "Savitzky-Golay DEM elevation differentiation with last-day holdout",
            "baseline_training_rmse_w": baseline_training_rmse,
            "selected_training_rmse_w": float(best["training_rmse_w"]),
            "baseline_validation_rmse_w": baseline_validation_rmse,
            "selected_validation_rmse_w": float(best["validation_rmse_w"]),
            "validation_rmse_ratio": validation_ratio,
            "candidate_count": len(records),
        }, None

    selected_window = float(best["smoothing_window_km"])
    selected_offset = float(best["distance_offset_km"])
    smoothing_search_max = float(max(windows))
    smoothing_boundary_hit = math.isclose(
        selected_window,
        smoothing_search_max,
        rel_tol=0.0,
        abs_tol=1.0e-9,
    )
    selected_route_slope = route_slopes[(selected_window, selected_offset)]
    out["slope_pct_previous"] = pd.to_numeric(out["slope_pct"], errors="coerce")
    out["slope_pct"] = np.interp(
        replay_distance,
        distance,
        selected_route_slope,
        left=selected_route_slope[0],
        right=selected_route_slope[-1],
    )
    adopted_route = pd.DataFrame(
        {
            "dist_km": distance,
            "elev_m": elevation,
            "slope_pct": selected_route_slope,
            "headwind_ms": np.zeros(len(distance), dtype=float),
        }
    )
    ensure_dir(output_csv.parent)
    adopted_route.to_csv(output_csv, index=False)
    top_candidates = sorted(records, key=lambda row: float(row["training_rmse_w"]))[:25]
    return out, {                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "enabled": True,
        "adopted": True,
        "reason": "training_improvement_and_last_day_holdout_passed",
        "method": "Savitzky-Golay DEM elevation differentiation with last-day holdout",
        "source_route_profile_csv": str(route_profile_csv),
        "adopted_route_profile_csv": str(output_csv),
        "holdout_day": holdout_day,
        "training_sample_count": int(train_mask.sum()),
        "validation_sample_count": int(validation_mask.sum()),
        "selected_smoothing_window_km": selected_window,
        "smoothing_search_max_km": smoothing_search_max,
        "smoothing_search_boundary_hit": smoothing_boundary_hit,
        "selected_distance_offset_km": selected_offset,
        "selected_provisional_grade_scale": float(best["provisional_grade_scale"]),
        "baseline_training_rmse_w": baseline_training_rmse,
        "selected_training_rmse_w": float(best["training_rmse_w"]),
        "training_improvement_w": training_improvement,
        "baseline_validation_rmse_w": baseline_validation_rmse,
        "selected_validation_rmse_w": float(best["validation_rmse_w"]),
        "validation_rmse_ratio": validation_ratio,
        "candidate_count": len(records),
        "top_candidates": top_candidates,
    }, output_csv


def pv_leave_one_day_out_validation(                               # [関数定義] pv_leave_one_day_out_validation の処理実行ブロック
    frame: pd.DataFrame,
    model,
    *,
    panel_deployment_options: Dict[str, float] | None = None,
) -> Dict[str, float]:
    """Validate the PV chain on days excluded from all PV-scalar fitting."""
    required = {
        "time_utc",
        "speed_kmh",
        "GHI_archive",
        "DNI_archive",
        "DHI_archive",
        "Tamb_archive_C",
        "solar_power_w_obs",
        "exclude_weather_fit",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ValueError(f"PV leave-one-day-out validation is missing columns: {missing}")
    keep = sorted(required.union({"day", "s_km"}).intersection(frame.columns))
    work = frame.loc[:, keep].copy()
    if "day" in work.columns:
        work["_pv_cv_day"] = pd.to_numeric(work["day"], errors="coerce")
    else:
        local_time = pd.to_datetime(work["time_utc"], format="mixed", utc=True).dt.tz_convert(TIMEZONE_LOCAL)
        work["_pv_cv_day"] = local_time.dt.date.astype(str)
    deployment = dict(panel_deployment_options or {})
    moving_residuals = []
    deployed_residuals = []
    fold_count = 0
    for day_value in work["_pv_cv_day"].dropna().drop_duplicates().tolist():
        holdout = work.loc[work["_pv_cv_day"] == day_value].drop(columns="_pv_cv_day")
        train = work.loc[work["_pv_cv_day"] != day_value].drop(columns="_pv_cv_day")
        if len(train) < 100 or len(holdout) < 20:
            continue
        try:
            fold_fit = fit_pv_parameters(
                train,
                model,
                irradiance_source="GHI_archive",
                operating_state="moving",
            )
            fold_fit = fit_stop_tilt_fraction(train, model, fold_fit, **deployment)
            predicted = attach_archive_pv_model(
                holdout,
                model,
                fold_fit,
                irradiance_source="GHI_archive",
                **deployment,
            )
        except (KeyError, ValueError, RuntimeError):
            continue
        observed = pd.to_numeric(predicted["solar_power_w_obs"], errors="coerce")
        modeled = pd.to_numeric(predicted["solar_power_w_model"], errors="coerce")
        valid = observed.notna() & modeled.notna()
        if "exclude_weather_fit" in predicted.columns:
            valid &= ~predicted["exclude_weather_fit"].fillna(False).astype(bool)
        moving = valid & pd.to_numeric(predicted["speed_kmh"], errors="coerce").ge(12.0)
        deployed = valid & predicted["panel_deployed_model"].fillna(False).astype(bool)
        moving_residuals.extend((observed.loc[moving] - modeled.loc[moving]).tolist())
        deployed_residuals.extend((observed.loc[deployed] - modeled.loc[deployed]).tolist())
        fold_count += 1

    def rmse(values) -> float:                                     # [関数定義] rmse の処理実行ブロック
        array = np.asarray(values, dtype=float)
        array = array[np.isfinite(array)]
        return float(np.sqrt(np.mean(np.square(array)))) if array.size else float("nan")  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "pv_lodo_fold_count": int(fold_count),
        "pv_lodo_moving_rmse_w": rmse(moving_residuals),
        "pv_lodo_moving_sample_count": int(len(moving_residuals)),
        "pv_lodo_deployed_stop_rmse_w": rmse(deployed_residuals),
        "pv_lodo_deployed_stop_sample_count": int(len(deployed_residuals)),
    }


def add_end_to_end_metrics(primary: Dict[str, float], end_to_end: Dict[str, float]) -> Dict[str, float]:  # [関数定義] add_end_to_end_metrics の処理実行ブロック
    out = dict(primary)
    for key, value in end_to_end.items():
        out[f"end_to_end_{key}"] = value
    out["vehicle_fit_solar_source"] = "measured_when_available"
    out["end_to_end_solar_source"] = "weather_and_pv_model"
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def add_battery_conditional_metrics(primary: Dict[str, float], conditional: Dict[str, float]) -> Dict[str, float]:  # [関数定義] add_battery_conditional_metrics の処理実行ブロック
    out = dict(primary)
    for key, value in conditional.items():
        out[f"battery_conditional_{key}"] = value
    out["battery_conditional_source"] = "observed_pack_power_and_current"
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_replay_csv(frame: pd.DataFrame, output_path: Path, *, chunk_rows: int = 5000) -> None:  # [関数定義] write_replay_csv の処理実行ブロック
    """Write large replay tables without materializing a full string copy."""
    ensure_dir(output_path.parent)
    rows = max(1, int(chunk_rows))
    for start in range(0, len(frame), rows):
        chunk = frame.iloc[start : start + rows].copy()
        chunk["time_utc"] = pd.to_datetime(
            chunk["time_utc"], format="mixed", utc=True
        ).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        chunk.to_csv(
            output_path,
            index=False,
            mode="w" if start == 0 else "a",
            header=start == 0,
        )


def apply_fit_to_cfg(                                              # [関数定義] apply_fit_to_cfg の処理実行ブロック
    cfg: dict,
    *,
    package_dir: Path,
    map_assets: Dict[str, Path],
    pv: PvFitResult,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    observed_log_csv: Path,
    battery_dynamic_fit: Dict[str, Any] | None = None,
    solar_measurement_calibration: Dict[str, Any] | None = None,
    sync_sim_soc0: bool = False,
) -> dict:
    cfg.setdefault("paths", {})
    for key, path in map_assets.items():
        cfg["paths"][key] = os.path.relpath(path, package_dir).replace("\\", "/")
    cfg["paths"]["progress_reference_csv"] = os.path.relpath(observed_log_csv, package_dir).replace("\\", "/")

    model = cfg.setdefault("model", {})
    model["CdA"] = round(float(mot.cda), 6)
    model["Crr"] = round(float(mot.crr), 6)
    model["P_aux"] = round(float(mot.p_aux_w), 3)
    model["P_aux_stopped"] = round(float(mot.p_aux_w), 3)
    model["P_aux_night"] = 0.0
    model.setdefault("aux_night_ghi_threshold_wm2", 20.0)
    model["air_density_mode"] = "ideal_gas_altitude"
    model.setdefault("air_density_reference_pressure_pa", 101325.0)
    solar_calibration = solar_measurement_calibration or {}
    model["solar_measurement_gain_to_pack"] = round(
        float(solar_calibration.get("gain_to_pack", 1.0)), 8
    )
    model["panel_gain"] = round(float(pv.panel_gain), 6)
    model["grade_scale"] = round(float(mot.grade_scale), 6)
    model["drive_eff_scale"] = round(float(mot.drive_eff_scale), 6)
    model["regen_eff_scale"] = round(float(mot.drive_eff_scale), 6)
    model["regen_utilization"] = round(float(mot.regen_utilization), 6)
    model["rint_scale"] = round(float(batt.rint_scale), 6)
    model.setdefault("rint_physical_min_ohm", 0.0)
    model.setdefault("rint_physical_max_ohm", 0.0)
    model["r_line_ohm"] = round(float(batt.r_line_ohm), 6)
    model["eta_charge"] = round(float(batt.eta_charge), 6)
    model["E_nom_Wh"] = round(float(batt.e_nom_wh), 3)
    model["Q_nom_Ah"] = round(float(batt.e_nom_wh) / BATTERY_NOMINAL_VOLTAGE_V, 6)
    # 4.35 V/cell is the product-sheet racing maximum. The old profile used
    # the maximum of a loaded discharge table (103.231 V) as a safety limit,
    # which was below the reconstructed OCV and forced the controller to
    # accelerate merely to pull terminal voltage down.
    ocv_asset = map_assets.get("ocv_soc_map")
    ocv_max_v = float("-inf")
    if ocv_asset is not None:
        ocv_path = Path(ocv_asset)
        ocv_frame = pd.read_csv(ocv_path)
        if "ocv_v" not in ocv_frame.columns:
            raise ValueError(f"adopted OCV map is missing ocv_v: {ocv_path}")
        ocv_values = pd.to_numeric(ocv_frame["ocv_v"], errors="coerce").dropna()
        if ocv_values.empty:
            raise ValueError(f"adopted OCV map has no finite ocv_v values: {ocv_path}")
        ocv_max_v = float(ocv_values.max())
        ocv_min_v = float(ocv_values.min())
        if ocv_max_v > BATTERY_PACK_MAX_CHARGE_V + 1.0e-6:
            raise ValueError(
                f"adopted OCV maximum {ocv_max_v:.6f} V exceeds the grounded "
                f"25S pack limit {BATTERY_PACK_MAX_CHARGE_V:.6f} V"
            )
        model["V_min"] = round(min(float(model.get("V_min", ocv_min_v)), ocv_min_v), 3)
    model["V_max"] = round(BATTERY_PACK_MAX_CHARGE_V, 3)
    dynamic = battery_dynamic_fit or {}
    model["r_polarization_ohm"] = round(float(dynamic.get("r_polarization_ohm", 0.0)), 6)
    model["polarization_tau_sec"] = round(float(dynamic.get("tau_sec", 60.0)), 6)
    model["headwind_gain"] = round(float(mot.headwind_gain), 6)

    # The fitted SoC is the latent initial state of the historical replay.  It is
    # not the initial charge selected for a future race simulation.  Keep both
    # quantities explicit so identification cannot silently change operations.
    identification = cfg.setdefault("identification", {})
    identification["fitted_replay_soc0"] = round(float(batt.soc0), 6)
    validation_gate = identification.setdefault("validation_gate", {})
    validation_gate.setdefault("vehicle_power_rmse_max_w", 150.0)
    validation_gate.setdefault("vehicle_voltage_rmse_max_v", 1.0)
    validation_gate.setdefault("conditional_power_rmse_max_w", 150.0)
    validation_gate.setdefault("conditional_voltage_rmse_max_v", 1.0)
    validation_gate.setdefault("end_to_end_power_rmse_max_w", 200.0)
    validation_gate.setdefault("end_to_end_voltage_rmse_max_v", 2.0)
    validation_gate.setdefault("moving_pv_rmse_max_w", 150.0)
    validation_gate.setdefault("pv_lodo_moving_rmse_max_w", 150.0)
    validation_gate.setdefault("pv_lodo_deployed_stop_rmse_max_w", 200.0)
    validation_gate.setdefault("power_residual_mean_120s_rmse_max_w", 150.0)
    validation_gate.setdefault("energy_error_25km_rmse_max_wh", 35.0)
    validation_gate.setdefault("vehicle_terminal_soc_error_max", 0.02)
    validation_gate.setdefault("vehicle_terminal_voltage_error_max_v", 0.5)
    validation_gate.setdefault("end_to_end_terminal_soc_error_max", 0.03)
    validation_gate.setdefault("end_to_end_terminal_voltage_error_max_v", 1.0)
    validation_gate.setdefault("terminal_soc_evidence_spread_max", 0.05)
    validation_gate.setdefault("acceleration_validation_rmse_ratio_max", 1.02)
    validation_gate.setdefault("acceleration_validation_min_samples", 100)
    validation_gate.setdefault("grade_validation_rmse_ratio_max", 1.02)
    validation_gate.setdefault("grade_validation_min_samples", 100)

    sim = cfg.setdefault("simulation", {})
    soc_max = float(model.get("soc_max", 0.98))
    if sync_sim_soc0:
        sim["soc0"] = round(float(np.clip(batt.soc0, 0.80, soc_max)), 4)
    live = cfg.setdefault("live", {})
    autocal = live.setdefault("autocal", {})
    autocal["aux_power_w_init"] = round(float(mot.p_aux_w), 3)
    weather = live.setdefault("weather", {})
    weather["tcell_gain"] = round(float(pv.tcell_gain_c_per_wm2), 6)
    mpc = cfg.setdefault("mpc", {})
    mpc["stop_tilt_fraction"] = round(float(np.clip(pv.stop_tilt_fraction, 0.0, 1.0)), 6)
    mpc.setdefault("control_stop_tilt_fraction", 0.0)
    mpc.setdefault("control_stop_arrival_tolerance_km", 0.2)
    mpc.setdefault("control_stop_stationary_speed_kmh", 2.0)
    mpc.setdefault("control_stop_brake_decel_kmhps", 3.5)
    mpc.setdefault("control_stop_brake_margin_km", 0.03)
    return cfg                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def update_profile(                                                # [関数定義] update_profile の処理実行ブロック
    profile_yaml: Path,
    cfg: dict,
    map_assets: Dict[str, Path],
    pv: PvFitResult,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    observed_log_csv: Path,
    battery_dynamic_fit: Dict[str, Any] | None = None,
    solar_measurement_calibration: Dict[str, Any] | None = None,
    route_profile_asset: Path | None = None,
    package_dir: Path | None = None,
) -> None:
    package_dir = profile_yaml.parent if package_dir is None else Path(package_dir)
    cfg = apply_fit_to_cfg(
        cfg,
        package_dir=package_dir,
        map_assets=map_assets,
        pv=pv,
        batt=batt,
        mot=mot,
        battery_dynamic_fit=battery_dynamic_fit,
        solar_measurement_calibration=solar_measurement_calibration,
        observed_log_csv=observed_log_csv,
        sync_sim_soc0=False,
    )
    if route_profile_asset is not None:
        cfg.setdefault("paths", {})["route_profile_csv"] = relpath_from(
            package_dir, route_profile_asset
        )
    if profile_yaml.parent.resolve() != package_dir.resolve():
        for key, raw in list((cfg.get("paths", {}) or {}).items()):
            if raw in (None, ""):
                continue
            path = Path(str(raw))
            if path.is_absolute():
                continue
            package_path = (package_dir / path).resolve()
            if package_path.exists():
                cfg["paths"][key] = relpath_from(profile_yaml.parent, package_path)
    with profile_yaml.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)


def update_profile_artifact_references(                            # [関数定義] update_profile_artifact_references の処理実行ブロック
    profile_yaml: Path,
    package_dir: Path,
    *,
    fit_summary_yaml: Path,
    terminal_consistency_yaml: Path | None = None,
) -> None:
    cfg = yaml.safe_load(profile_yaml.read_text(encoding="utf-8")) or {}
    identification = cfg.setdefault("identification", {})
    identification["fit_summary_yaml"] = relpath_from(profile_yaml.parent, fit_summary_yaml)
    if terminal_consistency_yaml is not None and terminal_consistency_yaml.is_file():
        identification["terminal_consistency_yaml"] = relpath_from(
            profile_yaml.parent, terminal_consistency_yaml
        )
    else:
        identification.pop("terminal_consistency_yaml", None)
    profile_yaml.write_text(
        yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )


def write_terminal_consistency_from_anchor(                        # [関数定義] write_terminal_consistency_from_anchor の処理実行ブロック
    output_path: Path,
    terminal_anchor: Dict[str, Any],
    *,
    max_spread: float,
    validation_metrics: Dict[str, Any] | None = None,
    replay_soc_error_max: float = 0.02,
    replay_voltage_error_max_v: float = 0.5,
    vehicle_soc_error_max: float = 0.02,
    vehicle_voltage_error_max_v: float = 0.5,
    end_to_end_soc_error_max: float = 0.03,
    end_to_end_voltage_error_max_v: float = 1.0,
) -> Path:
    """Always materialize the independent terminal-evidence gate.

    Detailed channel reconstruction may later enrich this file, but profile
    adoption must never silently drop the gate merely because a separate
    reporting command was not run.
    """
    lo = float(terminal_anchor.get("soc_evidence_min", float("nan")))
    hi = float(terminal_anchor.get("soc_evidence_max", float("nan")))
    target = float(terminal_anchor.get("soc_target", float("nan")))
    sigma = float(terminal_anchor.get("soc_sigma", float("nan")))
    spread = hi - lo if np.isfinite(lo) and np.isfinite(hi) else float("nan")
    metrics = validation_metrics or {}
    replay_soc_error = abs(
        float(metrics.get("battery_conditional_retire_anchor_soc_error", float("nan")))
    )
    replay_voltage_observed = float(
        metrics.get("battery_conditional_retire_anchor_voltage_obs_v", float("nan"))
    )
    replay_voltage_predicted = float(
        metrics.get("battery_conditional_retire_anchor_voltage_pred_v", float("nan"))
    )
    replay_voltage_error = abs(replay_voltage_predicted - replay_voltage_observed)
    vehicle_soc_error = abs(float(metrics.get("retire_anchor_soc_error", float("nan"))))
    vehicle_voltage_error = abs(
        float(metrics.get("retire_anchor_voltage_pred_v", float("nan")))
        - float(metrics.get("retire_anchor_voltage_obs_v", float("nan")))
    )
    end_to_end_soc_error = abs(
        float(metrics.get("end_to_end_retire_anchor_soc_error", float("nan")))
    )
    end_to_end_voltage_error = abs(
        float(metrics.get("end_to_end_retire_anchor_voltage_pred_v", float("nan")))
        - float(metrics.get("end_to_end_retire_anchor_voltage_obs_v", float("nan")))
    )
    evidence_spread_gate = bool(np.isfinite(spread) and spread <= float(max_spread))
    local_anchor_gate = bool(terminal_anchor.get("quality_gate_pass", False))
    cross_channel_gate = bool(
        terminal_anchor.get("weak_channel_cross_consistency_gate_pass", False)
    )
    replay_gate = bool(
        np.isfinite(replay_soc_error)
        and replay_soc_error <= float(replay_soc_error_max)
        and np.isfinite(replay_voltage_error)
        and replay_voltage_error <= float(replay_voltage_error_max_v)
    )
    vehicle_gate = bool(
        np.isfinite(vehicle_soc_error)
        and vehicle_soc_error <= float(vehicle_soc_error_max)
        and np.isfinite(vehicle_voltage_error)
        and vehicle_voltage_error <= float(vehicle_voltage_error_max_v)
    )
    end_to_end_gate = bool(
        np.isfinite(end_to_end_soc_error)
        and end_to_end_soc_error <= float(end_to_end_soc_error_max)
        and np.isfinite(end_to_end_voltage_error)
        and end_to_end_voltage_error <= float(end_to_end_voltage_error_max_v)
    )
    high_precision_gate = bool(
        evidence_spread_gate
        and local_anchor_gate
        and cross_channel_gate
        and replay_gate
        and vehicle_gate
        and end_to_end_gate
    )
    payload = {
        "source": "terminal_anchor evidence envelope",
        "terminal_distance_km": float(terminal_anchor.get("s_km", float("nan"))),
        "evidence_interval_min": lo,
        "evidence_interval_max": hi,
        "unweighted_central_estimate": target,
        "spread_percentage_points": 100.0 * spread if np.isfinite(spread) else float("nan"),
        "high_precision_gate_pass": high_precision_gate,
        "high_precision_checks": {
            "terminal_evidence_spread": evidence_spread_gate,
            "local_terminal_anchor_quality": local_anchor_gate,
            "independent_cross_channel_consistency": cross_channel_gate,
            "conditional_replay_terminal_soc": bool(
                np.isfinite(replay_soc_error)
                and replay_soc_error <= float(replay_soc_error_max)
            ),
            "conditional_replay_terminal_voltage": bool(
                np.isfinite(replay_voltage_error)
                and replay_voltage_error <= float(replay_voltage_error_max_v)
            ),
            "vehicle_replay_terminal": vehicle_gate,
            "end_to_end_replay_terminal": end_to_end_gate,
        },
        "conditional_replay_terminal_soc_error": replay_soc_error,
        "conditional_replay_terminal_soc_error_max": float(replay_soc_error_max),
        "conditional_replay_terminal_voltage_error_v": replay_voltage_error,
        "conditional_replay_terminal_voltage_error_max_v": float(replay_voltage_error_max_v),
        "vehicle_replay_terminal_soc_error": vehicle_soc_error,
        "vehicle_replay_terminal_soc_error_max": float(vehicle_soc_error_max),
        "vehicle_replay_terminal_voltage_error_v": vehicle_voltage_error,
        "vehicle_replay_terminal_voltage_error_max_v": float(vehicle_voltage_error_max_v),
        "end_to_end_replay_terminal_soc_error": end_to_end_soc_error,
        "end_to_end_replay_terminal_soc_error_max": float(end_to_end_soc_error_max),
        "end_to_end_replay_terminal_voltage_error_v": end_to_end_voltage_error,
        "end_to_end_replay_terminal_voltage_error_max_v": float(end_to_end_voltage_error_max_v),
        "random_effects_soc": target,
        "random_effects_standard_error": sigma,
        "random_effects_ci95_min": max(0.0, target - 1.96 * sigma) if np.isfinite(target) and np.isfinite(sigma) else float("nan"),
        "random_effects_ci95_max": min(1.0, target + 1.96 * sigma) if np.isfinite(target) and np.isfinite(sigma) else float("nan"),
        "method": terminal_anchor.get("method", ""),
        "source_documents": list(terminal_anchor.get("source_documents", []) or []),
        "fusion_caution": (
            "The center summarizes the declared evidence envelope. A narrow conditional pulse "
            "interval cannot override cross-channel disagreement or replay mismatch."
        ),
        "interpretation": (
            "Independent evidence and the battery-only, vehicle, and end-to-end replays satisfy every configured terminal limit."
            if high_precision_gate
            else "One or more independent-evidence or replay checks failed; do not claim high-precision terminal SoC."
        ),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return output_path                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def sync_canonical_fullsim_profile(                                # [関数定義] sync_canonical_fullsim_profile の処理実行ブロック
    package_dir: Path,
    *,
    map_assets: Dict[str, Path],
    pv: PvFitResult,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    observed_log_csv: Path,
    battery_dynamic_fit: Dict[str, Any] | None = None,
    solar_measurement_calibration: Dict[str, Any] | None = None,
) -> Path | None:
    fullsim_yaml = package_dir / "profile_fullsim_selflearned.yaml"
    if not fullsim_yaml.exists():
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    with fullsim_yaml.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f"fullsim profile must be a mapping: {fullsim_yaml}")
    cfg = apply_fit_to_cfg(
        cfg,
        package_dir=package_dir,
        map_assets=map_assets,
        pv=pv,
        batt=batt,
        mot=mot,
        battery_dynamic_fit=battery_dynamic_fit,
        solar_measurement_calibration=solar_measurement_calibration,
        observed_log_csv=observed_log_csv,
        sync_sim_soc0=False,
    )
    with fullsim_yaml.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
    return fullsim_yaml                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_generic_summary(                                         # [関数定義] write_generic_summary の処理実行ブロック
    package_dir: Path,
    manifest_path: Path,
    profile_yaml: Path,
    map_assets: Dict[str, Path],
    pv: PvFitResult,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    metrics: Dict[str, float],
    terminal_anchor: Dict[str, float],
    stage_anchors: list[dict],
    map_shape_fit: Dict[str, object],
    post_refine: PostRefineResult,
    day_metrics: list[dict],
    battery_dynamic_fit: Dict[str, Any] | None = None,
    fit_plan: dict | None = None,
    manifest_context: dict | None = None,
    output_dir: Path | None = None,
    replay_csv: Path | None = None,
    battery_conditioned_replay_csv: Path | None = None,
    end_to_end_replay_csv: Path | None = None,
) -> Path:
    output_dir = output_dir or package_dir / "outputs" / "identification"
    out_path = output_dir / f"{package_dir.name}_generic_fit_summary.yaml"
    ensure_dir(out_path.parent)
    payload = {
        "builder": "generic_replay_mle",
        "manifest_yaml": os.path.relpath(manifest_path, package_dir).replace("\\", "/"),
        "profile_yaml": os.path.relpath(profile_yaml, package_dir).replace("\\", "/"),
        "active_maps": {key: os.path.relpath(path, package_dir).replace("\\", "/") for key, path in map_assets.items()},
        "pv_fit": pv.__dict__,
        "battery_fit": batt.__dict__,
        "battery_dynamic_fit": dict(battery_dynamic_fit or {}),
        "motion_fit": mot.__dict__,
        "validation_metrics": metrics,
        "validation_protocol": {
            "vehicle_conditional_replay_csv": relpath_from(package_dir, replay_csv),
            "battery_conditioned_replay_csv": relpath_from(package_dir, battery_conditioned_replay_csv),
            "end_to_end_replay_csv": relpath_from(package_dir, end_to_end_replay_csv),
            "vehicle_fit_solar_source": "measured_when_available",
            "battery_conditioned_source": "observed_pack_power_and_current",
            "end_to_end_solar_source": "independent_GHI_archive_and_moving_PV_model",
            "restart_soc_anchor": "median_of_valid_stationary_window",
        },
        "terminal_anchor": terminal_anchor,
        "stage_anchors": stage_anchors,
        "day_metrics": day_metrics,
        "map_shape_fit": map_shape_fit,
        "post_refine": post_refine.__dict__,
        "fit_plan": dict(fit_plan or {}),
        "evidence_bundle": {
            "actual_event_yaml": relpath_from(package_dir, (manifest_context or {}).get("actual_event_path")),
            "counterfactual_event_yaml": relpath_from(package_dir, (manifest_context or {}).get("counterfactual_event_path")),
            "terminal_anchor_yaml": relpath_from(package_dir, (manifest_context or {}).get("terminal_anchor_path")),
            "grounded_map_summary_yaml": relpath_from(package_dir, (manifest_context or {}).get("grounded_summary_path")),
            "source_inventory_json": relpath_from(package_dir, (manifest_context or {}).get("source_inventory_path")),
            "notes_markdown": relpath_from(package_dir, (manifest_context or {}).get("notes_markdown_path")),
            "explicit_grounded_assets": {
                key: relpath_from(package_dir, path)
                for key, path in ((manifest_context or {}).get("explicit_grounded_assets") or {}).items()
            },
            "external_documents": list((manifest_context or {}).get("external_documents", [])),
        },
    }
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
    return out_path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_generic_report(                                          # [関数定義] write_generic_report の処理実行ブロック
    package_dir: Path,
    profile_yaml: Path,
    manifest_path: Path,
    summary_yaml: Path,
    observed_log_csv: Path,
    pv: PvFitResult,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    metrics: Dict[str, float],
    post_refine: PostRefineResult,
    map_assets: Dict[str, Path],
    *,
    terminal_anchor: Dict[str, float] | None = None,
    stage_anchors: list[dict] | None = None,
    day_metrics: list[dict] | None = None,
    battery_dynamic_fit: Dict[str, Any] | None = None,
    fit_plan: dict | None = None,
    grounded_map_summary: Dict[str, object] | None = None,
    manifest_context: dict | None = None,
    terminal_consistency: Dict[str, Any] | None = None,
    report_dir: Path | None = None,
    current_maps_path: Path | None = None,
) -> Tuple[Path, Path]:
    report_dir = report_dir or package_dir / "outputs" / "reports"
    ensure_dir(report_dir)
    md_path = report_dir / f"{package_dir.name}_generic_identification_report.md"
    tex_path = report_dir / f"{package_dir.name}_generic_identification_report.tex"
    pdf_path = tex_path.with_suffix(".pdf")
    rel_maps = {key: os.path.relpath(path, package_dir).replace("\\", "/") for key, path in map_assets.items()}
    terminal_anchor = terminal_anchor or {}
    stage_anchors = stage_anchors or []
    day_metrics = day_metrics or []
    battery_dynamic_fit = battery_dynamic_fit or {}
    fit_plan = fit_plan or {}
    solar_calibration = fit_plan.get("solar_measurement_calibration", {}) or {}
    grade_observation_fit = fit_plan.get("grade_observation_fit", {}) or {}
    solar_gain_to_pack = float(solar_calibration.get("gain_to_pack", 1.0))
    solar_calibration_samples = int(solar_calibration.get("sample_count", 0) or 0)
    solar_calibration_accepted = bool(solar_calibration.get("accepted", False))
    solar_calibration_intercept_w = float(
        solar_calibration.get("free_intercept_w", float("nan"))
    )
    solar_calibration_intercept_error_w = float(
        solar_calibration.get("free_intercept_error_w", float("nan"))
    )
    solar_calibration_daily_std = float(
        solar_calibration.get("daily_gain_std", float("nan"))
    )
    profile_cfg = yaml.safe_load(profile_yaml.read_text(encoding="utf-8-sig")) or {}
    profile_model = profile_cfg.get("model", {}) or {}
    pack_voltage_limit_v = float(profile_model.get("V_max", BATTERY_PACK_MAX_CHARGE_V))
    grounded_yaml = str((grounded_map_summary or {}).get("summary_yaml", "") or "")
    manifest_context = manifest_context or {}
    terminal_consistency = terminal_consistency or {}
    terminal_checks = terminal_consistency.get("high_precision_checks", {}) or {}
    terminal_gate_pass = bool(terminal_consistency.get("high_precision_gate_pass", False))
    terminal_evidence_min = float(
        terminal_consistency.get("evidence_interval_min", float("nan"))
    )
    terminal_evidence_max = float(
        terminal_consistency.get("evidence_interval_max", float("nan"))
    )
    terminal_evidence_spread_pp = float(
        terminal_consistency.get("spread_percentage_points", float("nan"))
    )
    terminal_interpretation = str(terminal_consistency.get("interpretation", "") or "")
    evidence_rows = [
        ("actual_event_yaml", relpath_from(package_dir, manifest_context.get("actual_event_path"))),
        ("counterfactual_event_yaml", relpath_from(package_dir, manifest_context.get("counterfactual_event_path"))),
        ("terminal_anchor_yaml", relpath_from(package_dir, manifest_context.get("terminal_anchor_path"))),
        ("grounded_map_summary_yaml", relpath_from(package_dir, manifest_context.get("grounded_summary_path")) or grounded_yaml),
        ("source_inventory_json", relpath_from(package_dir, manifest_context.get("source_inventory_path"))),
        ("notes_markdown", relpath_from(package_dir, manifest_context.get("notes_markdown_path"))),
    ]
    explicit_grounded_assets = {
        key: relpath_from(package_dir, path)
        for key, path in (manifest_context.get("explicit_grounded_assets") or {}).items()
    }
    external_documents = [str(item) for item in manifest_context.get("external_documents", []) if str(item).strip()]
    current_maps_path = current_maps_path or report_dir / "current_maps_and_coefficients.md"
    profile_rel = os.path.relpath(profile_yaml, package_dir).replace("\\", "/")
    current_maps_rel_package = os.path.relpath(current_maps_path, package_dir).replace("\\", "/")
    current_maps_rel_report = os.path.relpath(current_maps_path, report_dir).replace("\\", "/")
    md = f"""# {package_dir.name} generic identification report

## Inputs

- profile: `{profile_rel}`
- manifest: `{os.path.relpath(manifest_path, package_dir).replace("\\", "/")}`
- normalized replay log: `{os.path.relpath(observed_log_csv, package_dir).replace("\\", "/")}`

## Adopted coefficients

- panel_gain: `{pv.panel_gain:.6f}`
- tcell_gain_c_per_wm2: `{pv.tcell_gain_c_per_wm2:.6f}`
- pv_irradiance_source: `{pv.irradiance_source}`
- pv_operating_state: `{pv.operating_state}`
- pv_sample_count: `{pv.sample_count}`
- stop_tilt_fraction: `{pv.stop_tilt_fraction:.6f}`
- stop_solar_rmse_w: `{pv.stop_solar_rmse_w:.3f}`
- solar_measurement_gain_to_pack: `{solar_gain_to_pack:.8f}`
- solar_measurement_calibration_accepted: `{solar_calibration_accepted}`
- solar_measurement_calibration_samples: `{solar_calibration_samples}`
- solar_measurement_free_intercept_w: `{solar_calibration_intercept_w:.6f}`
- solar_measurement_intercept_error_w: `{solar_calibration_intercept_error_w:.6f}`
- solar_measurement_daily_gain_std: `{solar_calibration_daily_std:.8f}`
- soc0: `{batt.soc0:.6f}`
- E_nom_Wh: `{batt.e_nom_wh:.3f}`
- Q_nom_Ah: `{batt.e_nom_wh / BATTERY_NOMINAL_VOLTAGE_V:.6f}`
- rint_scale: `{batt.rint_scale:.6f}`
- r_line_ohm: `{batt.r_line_ohm:.6f}`
- r_polarization_ohm: `{float(battery_dynamic_fit.get('r_polarization_ohm', 0.0)):.6f}`
- polarization_tau_sec: `{float(battery_dynamic_fit.get('tau_sec', 60.0)):.3f}`
- eta_charge: `{batt.eta_charge:.6f}`
- CdA: `{mot.cda:.6f}`
- Crr: `{mot.crr:.6f}`
- P_aux_w: `{mot.p_aux_w:.3f}`
- grade_scale: `{mot.grade_scale:.6f}`
- drive_eff_scale: `{mot.drive_eff_scale:.6f}`
- regen_utilization: `{mot.regen_utilization:.6f}`
- regen_sample_count: `{mot.regen_sample_count}`
- regen_fit_rmse_w: `{mot.regen_fit_rmse_w:.3f}`
- headwind_gain: `{mot.headwind_gain:.6f}`
- V_max_v: `{pack_voltage_limit_v:.3f}`

## Solar measurement calibration

The ZP solar channel is calibrated against the stationary DC-bus balance before
vehicle or PV fitting. For samples with zero traction power, the fitted model is
`P_batt,k = P_aux - g_solar * P_solar,raw,k + epsilon_k`. The adopted gain is
the bounded Huber M-estimator
`argmin_(0.70 <= g_solar <= 1.05) sum_k rho_H(P_batt,k - P_aux + g_solar * P_solar,raw,k)`.
The known 21 W auxiliary load fixes the intercept; a separate free-intercept fit
is retained only as a consistency diagnostic. Daily gain spread checks whether a
single gain is defensible across the race.

The telemetry contract is deliberately one-way: the sender transmits the raw ZP
`solar_power_w` value, and the receiving WiFi bridge multiplies it by the active
profile's `solar_measurement_gain_to_pack` exactly once. Corrected values must not
be sent through that raw field, which prevents double calibration.

The battery terminal-voltage ceiling is a hardware constraint, not a value fitted
from a loaded discharge trace. For YATA the adopted `{pack_voltage_limit_v:.3f} V`
must equal the product limit `25 series cells * 4.35 V/cell = 108.75 V`, and the
active OCV map must not exceed it. The package audit checks both directions.

## Validation

Vehicle coefficients are identified conditionally on measured array power so
forecast/PV error cannot be absorbed into CdA, Crr, or drivetrain efficiency.
The unprefixed metrics below are that conditional vehicle replay.  Keys beginning
with `end_to_end_` use independent archive GHI plus the moving-PV model and
therefore include forecast/PV error. `GHI_effective` is target-derived diagnostic
data and is prohibited from both fitting and end-to-end validation. Both datasets
are retained; neither is substituted for the other.

Keys beginning with `battery_conditional_` reuse observed pack power/current.
They validate the battery submodel only and cannot certify vehicle energy use or
the 2831 km vehicle-model terminal SoC. Promotion therefore requires separate
terminal gates for the unprefixed vehicle replay and the end-to-end replay.

The field-analysis source states that the ZP logger start time was not recorded
and was reconstructed backward from control-stop times. Therefore 5 s samples
do not provide a traceable pointwise synchronization certificate among power,
speed, and DEM grade. Parameter fitting uses the configured resampling window;
the 10 km and 25 km energy residuals are the primary route-energy checks. A low
pointwise RMSE must not be manufactured by fitting a time shift to this unknown.

The 5 s RMSE, 120 s mean-residual RMSE, and distance-window energy RMSE answer
different questions. The 5 s value includes unresolved channel synchronization
and transient noise. The 120 s value tests local mean power after aggregation.
The 10/25 km values test the accumulated energy that drives long-horizon SoC.
None may be relabelled as another metric, and operational promotion requires all
configured gates rather than choosing only the smallest number.

DEM grade is treated as an observation model rather than a vehicle constant.
Candidate Savitzky-Golay elevation smoothing lengths and route-distance offsets
are selected on race days other than the held-out final day. The adopted route
stores the unscaled differentiated elevation; `grade_scale` is fitted only
after that route is locked. This prevents DEM vertical noise from being hidden
inside CdA, Crr, or drivetrain efficiency.

Regeneration is separated into conversion efficiency and use:
`P_reg,dc = u_regen * eta_reg * eta_gear * eta_inv * max(-P_mech, 0)`.
The bounded scalar `u_regen` is fitted only where negative mechanical power is
observable and is never folded into the motor efficiency map.

- power_rmse_clean_w: `{metrics.get('power_rmse_clean_w', float('nan')):.3f}`
- power_rmse_fit_window_w: `{metrics.get('power_rmse_fit_window_w', float('nan')):.3f}`
- voltage_rmse_clean_v: `{metrics.get('voltage_rmse_clean_v', float('nan')):.3f}`
- final_soc_pred: `{metrics.get('final_soc_pred', float('nan')):.6f}`
- retire_anchor_soc_obs: `{metrics.get('retire_anchor_soc_obs', float('nan')):.6f}`
- retire_anchor_soc_pred: `{metrics.get('retire_anchor_soc_pred', float('nan')):.6f}`
- retire_anchor_soc_error: `{metrics.get('retire_anchor_soc_error', float('nan')):.6f}`
- battery_conditional_power_rmse_clean_w: `{metrics.get('battery_conditional_power_rmse_clean_w', float('nan')):.3f}`
- battery_conditional_voltage_rmse_clean_v: `{metrics.get('battery_conditional_voltage_rmse_clean_v', float('nan')):.3f}`
- battery_conditional_retire_anchor_soc_error: `{metrics.get('battery_conditional_retire_anchor_soc_error', float('nan')):.6f}`
- end_to_end_power_rmse_clean_w: `{metrics.get('end_to_end_power_rmse_clean_w', float('nan')):.3f}`
- end_to_end_voltage_rmse_clean_v: `{metrics.get('end_to_end_voltage_rmse_clean_v', float('nan')):.3f}`
- end_to_end_final_soc_pred: `{metrics.get('end_to_end_final_soc_pred', float('nan')):.6f}`
- end_to_end_retire_anchor_soc_error: `{metrics.get('end_to_end_retire_anchor_soc_error', float('nan')):.6f}`
- end_to_end_moving_pv_rmse_w: `{metrics.get('end_to_end_moving_pv_rmse_w', float('nan')):.3f}`
- end_to_end_deployed_stop_pv_rmse_w: `{metrics.get('end_to_end_deployed_stop_pv_rmse_w', float('nan')):.3f}`
- pv_lodo_moving_rmse_w: `{metrics.get('pv_lodo_moving_rmse_w', float('nan')):.3f}`
- pv_lodo_deployed_stop_rmse_w: `{metrics.get('pv_lodo_deployed_stop_rmse_w', float('nan')):.3f}`
- pv_lodo_fold_count: `{metrics.get('pv_lodo_fold_count', 0)}`
- power_residual_mean_120s_rmse_w: `{metrics.get('power_residual_mean_120s_rmse_w', float('nan')):.3f}`
- energy_error_10km_rmse_wh: `{metrics.get('energy_error_10km_rmse_wh', float('nan')):.3f}`
- energy_error_25km_rmse_wh: `{metrics.get('energy_error_25km_rmse_wh', float('nan')):.3f}`

## Terminal-SoC evidence and certification

- evidence_interval: `[{terminal_evidence_min:.6f}, {terminal_evidence_max:.6f}]`
- evidence_spread_percentage_points: `{terminal_evidence_spread_pp:.3f}`
- high_precision_gate_pass: `{terminal_gate_pass}`
""" + (
        "\n".join(
            f"- high_precision_check_{key}: `{bool(value)}`"
            for key, value in terminal_checks.items()
        )
        if terminal_checks
        else "- high_precision_checks: `(not evaluated)`"
    ) + f"""
- interpretation: `{terminal_interpretation}`

The central terminal-SoC estimate is not a direct coulomb-counter measurement.
If the evidence spread or any replay check fails, the value is retained as an
engineering anchor only; this report does not certify a high-precision actual
2831 km SoC and the candidate must not replace the operational profile.

## Method references

- Open-Meteo Historical Weather API: https://open-meteo.com/en/docs/historical-weather-api
- Sandia PVPMC plane-of-array irradiance guidance: https://pvpmc.sandia.gov/modeling-guide/1-weather-design-inputs/plane-of-array-poa-irradiance/
- pvlib total-irradiance transposition API: https://pvlib-python.readthedocs.io/en/latest/reference/generated/pvlib.irradiance.get_total_irradiance.html
- Byrd et al. (1995), L-BFGS-B: https://doi.org/10.1137/0916069
- Liu et al. (2014), GPS road-grade quantification: https://doi.org/10.1016/j.atmosenv.2013.12.025
- Wang et al. (2018), synchronized link-level EV energy data: https://escholarship.org/uc/item/2bp8x04q

## Terminal anchor

- anchor_s_km: `{terminal_anchor.get('s_km', float('nan'))}`
- anchor_time_utc: `{terminal_anchor.get('time_utc', '')}`
- anchor_voltage_v: `{terminal_anchor.get('voltage_v', float('nan'))}`
- anchor_current_a: `{terminal_anchor.get('current_a', float('nan'))}`
- anchor_temp_c: `{terminal_anchor.get('temp_c', float('nan'))}`
- anchor_soc_target: `{terminal_anchor.get('soc_target', float('nan'))}`

## Fit plan

- quality: `{fit_plan.get('quality', '')}`
- battery_restart_count: `{fit_plan.get('battery_restart_count', '')}`
- battery_maxiter: `{fit_plan.get('battery_maxiter', '')}`
- motion_restart_count: `{fit_plan.get('motion_restart_count', '')}`
- motion_maxiter: `{fit_plan.get('motion_maxiter', '')}`
- joint_restart_count: `{fit_plan.get('joint_restart_count', '')}`
- joint_random_start_count: `{fit_plan.get('joint_random_start_count', '')}`
- joint_local_topk: `{fit_plan.get('joint_local_topk', '')}`
- joint_maxiter: `{fit_plan.get('joint_maxiter', '')}`
- fit_stride: `{fit_plan.get('fit_stride', '')}`
- allow_map_shape_fit: `{fit_plan.get('allow_map_shape_fit', '')}`
- post_refine_enabled: `{fit_plan.get('post_refine_enabled', '')}`
- terminal_anchor_role: `{fit_plan.get('terminal_anchor_role', '')}`
- panel_deployment_stopped_speed_kmh: `{fit_plan.get('panel_deployment_stopped_speed_kmh', '')}`
- panel_deployment_min_dwell_sec: `{fit_plan.get('panel_deployment_min_dwell_sec', '')}`
- panel_deployment_max_sample_gap_sec: `{fit_plan.get('panel_deployment_max_sample_gap_sec', '')}`
- grade_observation_adopted: `{bool(grade_observation_fit.get('adopted', False))}`
- grade_smoothing_window_km: `{grade_observation_fit.get('selected_smoothing_window_km', '')}`
- grade_distance_offset_km: `{grade_observation_fit.get('selected_distance_offset_km', '')}`
- grade_training_rmse_w: `{grade_observation_fit.get('baseline_training_rmse_w', float('nan'))}` -> `{grade_observation_fit.get('selected_training_rmse_w', float('nan'))}`
- grade_holdout_rmse_w: `{grade_observation_fit.get('baseline_validation_rmse_w', float('nan'))}` -> `{grade_observation_fit.get('selected_validation_rmse_w', float('nan'))}`

## Stage anchors

- stage_anchor_count: `{len(stage_anchors)}`
""" + (
        "\n".join(
            f"- stage_anchor_{idx:02d}: `time={anchor.get('time_utc', '')}, s_km={anchor.get('s_km', float('nan'))}, V={anchor.get('voltage_v', float('nan'))}, I={anchor.get('current_a', float('nan'))}, SoC={anchor.get('soc_target', float('nan'))}, dwell_sec={anchor.get('dwell_sec', float('nan'))}`"
            for idx, anchor in enumerate(stage_anchors, start=1)
        )
        if stage_anchors
        else "- (none)"
    ) + f"""

## Day metrics

""" + (
        "\n".join(
            f"- day {row.get('day', '')}: dist_end={row.get('distance_end_km', float('nan')):.1f} km, final_soc={row.get('final_soc_pred', float('nan')):.4f}, power_rmse={row.get('power_rmse_clean_w', float('nan')):.2f} W, voltage_rmse={row.get('voltage_rmse_clean_v', float('nan')):.3f} V, excluded_power={row.get('excluded_power_points', 0)}, excluded_voltage={row.get('excluded_voltage_points', 0)}"
            for row in day_metrics
        )
        if day_metrics
        else "- (none)"
    ) + f"""

## Evidence bundle

""" + "\n".join(f"- {key}: `{value}`" for key, value in evidence_rows if value) + (
        ("\n" + "\n".join(f"- explicit_{key}: `{value}`" for key, value in explicit_grounded_assets.items())) if explicit_grounded_assets else ""
    ) + (
        ("\n" + "\n".join(f"- external_document: `{value}`" for value in external_documents)) if external_documents else ""
    ) + f"""

## Active maps

""" + "\n".join(f"- {key}: `{value}`" for key, value in rel_maps.items()) + f"""

## Grounded map provenance

- grounded_map_summary_yaml: `{grounded_yaml}`

## Post refinement

- accepted: `{post_refine.accepted}`
- panel_gain_factor: `{post_refine.panel_gain_factor:.5f}`
- cda_factor: `{post_refine.cda_factor:.5f}`
- crr_factor: `{post_refine.crr_factor:.5f}`
- drive_eff_factor: `{post_refine.drive_eff_factor:.5f}`
- headwind_gain_factor: `{post_refine.headwind_gain_factor:.5f}`
- e_nom_factor: `{post_refine.e_nom_factor:.5f}`
- rint_factor: `{post_refine.rint_factor:.5f}`

## Outputs

- fit summary: `{os.path.relpath(summary_yaml, package_dir).replace("\\", "/")}`
- current maps and coefficients: `{current_maps_rel_package}`
"""
    md_path.write_text(md, encoding="utf-8", newline="\n")

    tex = f"""
\\documentclass[a4paper,11pt]{{article}}
\\usepackage[top=18mm,bottom=22mm,left=18mm,right=18mm]{{geometry}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\setmainfont{{Times New Roman}}
\\setCJKmainfont{{Yu Gothic}}
\\setCJKmonofont{{Yu Gothic}}
\\usepackage{{booktabs}}
\\usepackage{{longtable}}
\\usepackage{{array}}
\\usepackage{{xurl}}
\\usepackage[unicode,hidelinks]{{hyperref}}
\\title{{Generic Vehicle Identification Report}}
\\author{{solar\\_ws0129-main}}
\\date{{}}
\\begin{{document}}
\\raggedbottom
\\maketitle

\\section{{Inputs}}
\\begin{{itemize}}
  \\item profile: \\path{{project_packages/{package_dir.name}/profile.yaml}}
  \\item manifest: \\path{{{os.path.relpath(manifest_path, report_dir).replace("\\", "/")}}}
  \\item normalized replay log: \\path{{{os.path.relpath(observed_log_csv, report_dir).replace("\\", "/")}}}
\\end{{itemize}}

\\section{{Adopted coefficients}}
\\begin{{longtable}}{{p{{0.48\\linewidth}}p{{0.22\\linewidth}}}}
\\toprule
項目 & 値 \\\\
\\midrule
\\endhead
panel gain & {pv.panel_gain:.6f} \\\\
tcell gain [C/(W m$^{{-2}}$)] & {pv.tcell_gain_c_per_wm2:.6f} \\\\
stop tilt fraction [-] & {pv.stop_tilt_fraction:.6f} \\\\
stop solar RMSE [W] & {pv.stop_solar_rmse_w:.3f} \\\\
solar measurement gain to pack & {solar_gain_to_pack:.8f} \\\\
solar calibration samples & {solar_calibration_samples} \\\\
solar free-intercept diagnostic [W] & {solar_calibration_intercept_w:.6f} \\\\
solar daily gain standard deviation & {solar_calibration_daily_std:.8f} \\\\
soc0 & {batt.soc0:.6f} \\\\
$E_{{nom}}$ [Wh] & {batt.e_nom_wh:.3f} \\\\
$Q_{{nom}}$ [Ah] & {batt.e_nom_wh / BATTERY_NOMINAL_VOLTAGE_V:.6f} \\\\
$k_{{Rint}}$ & {batt.rint_scale:.6f} \\\\
$R_{{line}}$ [ohm] & {batt.r_line_ohm:.6f} \\\\
$R_{{p}}$ [ohm] & {float(battery_dynamic_fit.get('r_polarization_ohm', 0.0)):.6f} \\\\
$\\tau_{{p}}$ [s] & {float(battery_dynamic_fit.get('tau_sec', 60.0)):.3f} \\\\
$\\eta_{{charge}}$ & {batt.eta_charge:.6f} \\\\
CdA & {mot.cda:.6f} \\\\
Crr & {mot.crr:.6f} \\\\
$P_{{aux}}$ [W] & {mot.p_aux_w:.3f} \\\\
grade scale & {mot.grade_scale:.6f} \\\\
drive efficiency scale & {mot.drive_eff_scale:.6f} \\\\
regen utilization & {mot.regen_utilization:.6f} \\\\
regen fit samples & {mot.regen_sample_count} \\\\
regen subset RMSE [W] & {mot.regen_fit_rmse_w:.3f} \\\\
headwind gain & {mot.headwind_gain:.6f} \\\\
pack terminal voltage limit [V] & {pack_voltage_limit_v:.3f} \\\\
\\bottomrule
\\end{{longtable}}

\\section{{Solar measurement calibration}}
Before vehicle and PV fitting, stationary samples identify the ZP solar-power
channel against the DC-bus balance,
\\[
P_{{batt,k}}=P_{{aux}}-g_{{solar}}P_{{solar,raw,k}}+\\varepsilon_k.
\\]
With the independently observed 21 W auxiliary load fixed, the bounded robust
estimate is
\\[
\\hat g_{{solar}}=\\mathop{{\\arg\\min}}_{{0.70\\le g\\le1.05}}
\\sum_k\\rho_H\\!\\left(P_{{batt,k}}-P_{{aux}}+gP_{{solar,raw,k}}\\right).
\\]
The adopted gain is {solar_gain_to_pack:.8f} from {solar_calibration_samples}
samples (accepted={solar_calibration_accepted}). A free-intercept fit is reported
only as a physical-consistency diagnostic; its intercept is
{solar_calibration_intercept_w:.6f} W and its error relative to the fixed
auxiliary load is {solar_calibration_intercept_error_w:.6f} W. The day-to-day
gain standard deviation is {solar_calibration_daily_std:.8f}.

The sender places the uncorrected ZP value in \\texttt{{solar\\_power\\_w}}. The
receiving WiFi bridge applies the profile gain exactly once. A corrected sender
value must not be placed in that raw field because it would be calibrated twice.

The terminal-voltage limit is grounded in the 25-series product limit of
$4.35$ V/cell, or $108.75$ V/pack, rather than the maximum voltage seen in a
loaded discharge trace. The adopted YATA profile limit is
{pack_voltage_limit_v:.3f} V and must equal that value; the active OCV map must
remain below it.

\\section{{Validation}}
Unprefixed values are vehicle-model validation conditioned on measured array
power. The end-to-end values use independent archive GHI and the moving-PV
model. Target-derived effective irradiance is excluded from both fitting and
end-to-end validation. This separation prevents irradiance forecast error from
being fitted as vehicle resistance.

The field-analysis source states that the ZP logger start time was not recorded
and was reconstructed backward from control-stop times. Consequently the 5 s
power, speed and DEM-grade records do not constitute a pointwise synchronization
certificate. The configured resampling window is used for parameter fitting,
while 10 km and 25 km energy residuals are the primary route-energy checks.

The 5 s point RMSE includes unresolved channel synchronization and transient
noise. The 120 s mean-residual RMSE tests local mean power, while the 10 km and
25 km metrics test accumulated route energy. They are intentionally reported as
separate quantities; no smaller aggregated number is presented as the 5 s RMSE.

Conversion efficiency and actual regeneration use are separated as
\\[
P_{{reg,dc}}=u_{{regen}}\\eta_{{reg}}\\eta_{{gear}}\\eta_{{inv}}
\\max(-P_{{mech}},0),\\qquad 0\\le u_{{regen}}\\le 1.
\\]
Only samples with observable negative mechanical power identify $u_{{regen}}$.

\\begin{{longtable}}{{p{{0.48\\linewidth}}p{{0.22\\linewidth}}}}
\\toprule
指標 & 値 \\\\
\\midrule
\\endhead
vehicle replay power RMSE [W] & {float(metrics.get('power_rmse_clean_w', float('nan'))):.3f} \\\\
fit-window power RMSE [W] & {float(metrics.get('power_rmse_fit_window_w', float('nan'))):.3f} \\\\
vehicle replay voltage RMSE [V] & {float(metrics.get('voltage_rmse_clean_v', float('nan'))):.3f} \\\\
vehicle replay final SoC [-] & {float(metrics.get('final_soc_pred', float('nan'))):.6f} \\\\
vehicle terminal SoC observed [-] & {float(metrics.get('retire_anchor_soc_obs', float('nan'))):.6f} \\\\
vehicle terminal SoC predicted [-] & {float(metrics.get('retire_anchor_soc_pred', float('nan'))):.6f} \\\\
vehicle terminal SoC error [-] & {float(metrics.get('retire_anchor_soc_error', float('nan'))):.6f} \\\\
battery-only power RMSE [W] & {float(metrics.get('battery_conditional_power_rmse_clean_w', float('nan'))):.3f} \\\\
battery-only voltage RMSE [V] & {float(metrics.get('battery_conditional_voltage_rmse_clean_v', float('nan'))):.3f} \\\\
battery-only terminal SoC error [-] & {float(metrics.get('battery_conditional_retire_anchor_soc_error', float('nan'))):.6f} \\\\
end-to-end power RMSE [W] & {float(metrics.get('end_to_end_power_rmse_clean_w', float('nan'))):.3f} \\\\
end-to-end voltage RMSE [V] & {float(metrics.get('end_to_end_voltage_rmse_clean_v', float('nan'))):.3f} \\\\
end-to-end final SoC [-] & {float(metrics.get('end_to_end_final_soc_pred', float('nan'))):.6f} \\\\
end-to-end terminal SoC error [-] & {float(metrics.get('end_to_end_retire_anchor_soc_error', float('nan'))):.6f} \\\\
end-to-end moving PV RMSE [W] & {float(metrics.get('end_to_end_moving_pv_rmse_w', float('nan'))):.3f} \\\\
end-to-end deployed-stop PV RMSE [W] & {float(metrics.get('end_to_end_deployed_stop_pv_rmse_w', float('nan'))):.3f} \\\\
PV leave-one-day-out moving RMSE [W] & {float(metrics.get('pv_lodo_moving_rmse_w', float('nan'))):.3f} \\\\
PV leave-one-day-out deployed-stop RMSE [W] & {float(metrics.get('pv_lodo_deployed_stop_rmse_w', float('nan'))):.3f} \\\\
PV leave-one-day-out folds [-] & {int(metrics.get('pv_lodo_fold_count', 0))} \\\\
120 s mean-residual RMSE [W] & {float(metrics.get('power_residual_mean_120s_rmse_w', float('nan'))):.3f} \\\\
10 km energy-error RMSE [Wh] & {float(metrics.get('energy_error_10km_rmse_wh', float('nan'))):.3f} \\\\
25 km energy-error RMSE [Wh] & {float(metrics.get('energy_error_25km_rmse_wh', float('nan'))):.3f} \\\\
\\bottomrule
\\end{{longtable}}

\\section{{Terminal-SoC evidence and certification}}
The independent evidence interval is
$[{terminal_evidence_min:.6f},\\,{terminal_evidence_max:.6f}]$, with width
{terminal_evidence_spread_pp:.3f} percentage points. The complete
high-precision gate result is \\textbf{{{terminal_gate_pass}}}.

\\begin{{longtable}}{{p{{0.58\\linewidth}}p{{0.18\\linewidth}}}}
\\toprule
check & pass \\\\
\\midrule
\\endhead
""" + "\n".join(
        f"{tex_path_fragment(str(key))} & {bool(value)} \\\\"
        for key, value in terminal_checks.items()
    ) + f"""
\\bottomrule
\\end{{longtable}}

{tex_text_fragment(terminal_interpretation)} The central estimate is not a
direct coulomb-counter observation. If this gate is false, it remains an
engineering anchor only; neither a high-precision actual 2831 km SoC nor
operational model certification is claimed.

\\section{{Method references}}
\\begin{{itemize}}
  \\item Open-Meteo Historical Weather API: \\url{{https://open-meteo.com/en/docs/historical-weather-api}}
  \\item Sandia PVPMC plane-of-array irradiance guidance: \\url{{https://pvpmc.sandia.gov/modeling-guide/1-weather-design-inputs/plane-of-array-poa-irradiance/}}
  \\item pvlib total-irradiance transposition API: \\url{{https://pvlib-python.readthedocs.io/en/latest/reference/generated/pvlib.irradiance.get_total_irradiance.html}}
  \\item Byrd et al. (1995), L-BFGS-B: \\url{{https://doi.org/10.1137/0916069}}
  \\item Liu et al. (2014), GPS road-grade quantification: \\url{{https://doi.org/10.1016/j.atmosenv.2013.12.025}}
  \\item Wang et al. (2018), synchronized link-level EV energy data: \\url{{https://escholarship.org/uc/item/2bp8x04q}}
\\end{{itemize}}

\\section{{Terminal anchor}}
\\begin{{longtable}}{{p{{0.48\\linewidth}}p{{0.32\\linewidth}}}}
\\toprule
項目 & 値 \\\\
\\midrule
\\endhead
anchor distance [km] & {float(terminal_anchor.get('s_km', float('nan'))):.3f} \\\\
anchor time UTC & \\path{{{str(terminal_anchor.get('time_utc', ''))}}} \\\\
anchor voltage [V] & {float(terminal_anchor.get('voltage_v', float('nan'))):.3f} \\\\
anchor current [A] & {float(terminal_anchor.get('current_a', float('nan'))):.3f} \\\\
anchor temperature [C] & {float(terminal_anchor.get('temp_c', float('nan'))):.3f} \\\\
anchor SoC target [-] & {float(terminal_anchor.get('soc_target', float('nan'))):.6f} \\\\
\\bottomrule
\\end{{longtable}}

\\section{{Fit plan}}
\\begin{{itemize}}
  \\item quality: {str(fit_plan.get('quality', ''))}
  \\item battery restart count: {fit_plan.get('battery_restart_count', '')}
  \\item battery maxiter: {fit_plan.get('battery_maxiter', '')}
  \\item motion restart count: {fit_plan.get('motion_restart_count', '')}
  \\item motion maxiter: {fit_plan.get('motion_maxiter', '')}
  \\item joint restart count: {fit_plan.get('joint_restart_count', '')}
  \\item joint random start count: {fit_plan.get('joint_random_start_count', '')}
  \\item joint local topk: {fit_plan.get('joint_local_topk', '')}
  \\item joint maxiter: {fit_plan.get('joint_maxiter', '')}
  \\item fit stride: {fit_plan.get('fit_stride', '')}
  \\item allow map-shape fit: {fit_plan.get('allow_map_shape_fit', '')}
  \\item post-refine enabled: {fit_plan.get('post_refine_enabled', '')}
  \\item terminal anchor role: \\path{{{str(fit_plan.get('terminal_anchor_role', ''))}}}
  \\item panel deployment stopped speed: {fit_plan.get('panel_deployment_stopped_speed_kmh', '')} km/h
  \\item panel deployment minimum dwell: {fit_plan.get('panel_deployment_min_dwell_sec', '')} s
  \\item panel deployment maximum sample gap: {fit_plan.get('panel_deployment_max_sample_gap_sec', '')} s
  \\item acceleration observation filter/alignment adopted: {bool((fit_plan.get('acceleration_observation_fit', {}) or {}).get('adopted', False))}
  \\item acceleration selected filter: \\path{{{str((fit_plan.get('acceleration_observation_fit', {}) or {}).get('selected_filter_method', 'legacy'))}}}, window={(fit_plan.get('acceleration_observation_fit', {}) or {}).get('selected_filter_window_samples', '')} samples / {(fit_plan.get('acceleration_observation_fit', {}) or {}).get('selected_filter_window_sec', '')} s
  \\item acceleration timestamp selected lag: {float((fit_plan.get('acceleration_observation_fit', {}) or {}).get('selected_lag_sec', float('nan'))):.3f} s
  \\item acceleration alignment train RMSE: {float((fit_plan.get('acceleration_observation_fit', {}) or {}).get('baseline_training_rmse_w', float('nan'))):.3f} $\\rightarrow$ {float((fit_plan.get('acceleration_observation_fit', {}) or {}).get('selected_training_rmse_w', float('nan'))):.3f} W
  \\item acceleration alignment held-out RMSE: {float((fit_plan.get('acceleration_observation_fit', {}) or {}).get('baseline_validation_rmse_w', float('nan'))):.3f} $\\rightarrow$ {float((fit_plan.get('acceleration_observation_fit', {}) or {}).get('selected_validation_rmse_w', float('nan'))):.3f} W
  \\item acceleration held-out RMSE ratio: {float((fit_plan.get('acceleration_observation_fit', {}) or {}).get('validation_rmse_ratio', float('nan'))):.6f}
  \\item DEM grade observation adopted: {bool(grade_observation_fit.get('adopted', False))}
  \\item DEM grade smoothing window: {grade_observation_fit.get('selected_smoothing_window_km', '')} km
  \\item DEM grade distance offset: {grade_observation_fit.get('selected_distance_offset_km', '')} km
  \\item DEM grade train RMSE: {float(grade_observation_fit.get('baseline_training_rmse_w', float('nan'))):.3f} $\\rightarrow$ {float(grade_observation_fit.get('selected_training_rmse_w', float('nan'))):.3f} W
  \\item DEM grade held-out RMSE: {float(grade_observation_fit.get('baseline_validation_rmse_w', float('nan'))):.3f} $\\rightarrow$ {float(grade_observation_fit.get('selected_validation_rmse_w', float('nan'))):.3f} W
\\end{{itemize}}

\\section{{Stage anchors}}
\\begin{{itemize}}
  \\item stage anchor count: {len(stage_anchors)}
""" + (
        ("\n" + "\n".join(
            f"  \\item anchor {idx:02d}: time=\\path{{{str(anchor.get('time_utc', ''))}}}, s={float(anchor.get('s_km', float('nan'))):.3f} km, V={float(anchor.get('voltage_v', float('nan'))):.3f} V, I={float(anchor.get('current_a', float('nan'))):.3f} A, SoC={float(anchor.get('soc_target', float('nan'))):.6f}, dwell={float(anchor.get('dwell_sec', float('nan'))):.1f} s"
            for idx, anchor in enumerate(stage_anchors, start=1)
        ))
        if stage_anchors
        else "\n  \\item (none)"
    ) + f"""
\\end{{itemize}}

\\section{{Day metrics}}
\\begin{{longtable}}{{>{{\\raggedright\\arraybackslash}}p{{0.10\\linewidth}}>{{\\raggedright\\arraybackslash}}p{{0.16\\linewidth}}>{{\\raggedright\\arraybackslash}}p{{0.16\\linewidth}}>{{\\raggedright\\arraybackslash}}p{{0.16\\linewidth}}>{{\\raggedright\\arraybackslash}}p{{0.16\\linewidth}}>{{\\raggedright\\arraybackslash}}p{{0.10\\linewidth}}}}
\\toprule
day & dist end [km] & final SoC & power RMSE [W] & voltage RMSE [V] & excl. power \\\\
\\midrule
\\endhead
""" + "\n".join(
        f"{int(row.get('day', -1))} & {float(row.get('distance_end_km', float('nan'))):.1f} & {float(row.get('final_soc_pred', float('nan'))):.4f} & {float(row.get('power_rmse_clean_w', float('nan'))):.2f} & {float(row.get('voltage_rmse_clean_v', float('nan'))):.3f} & {int(row.get('excluded_power_points', 0))} \\\\"
        for row in day_metrics
    ) + f"""
\\bottomrule
\\end{{longtable}}

\\section{{Evidence bundle}}
\\begin{{itemize}}
""" + "\n".join(
        f"  \\item {tex_path_fragment(key)}: {tex_path_fragment(value)}"
        for key, value in evidence_rows
        if value
    ) + (
        (
            "\n"
            + "\n".join(
                f"  \\item explicit {tex_path_fragment(key)}: {tex_path_fragment(value)}"
                for key, value in explicit_grounded_assets.items()
            )
        )
        if explicit_grounded_assets
        else ""
    ) + (
        (
            "\n"
            + "\n".join(
                f"  \\item external document: {tex_path_fragment(value)}"
                for value in external_documents
            )
        )
        if external_documents
        else ""
    ) + f"""
\\end{{itemize}}

\\section{{Active maps}}
\\begin{{itemize}}
""" + "\n".join(
        f"  \\item {tex_path_fragment(key)}: {tex_path_fragment(value)}"
        for key, value in rel_maps.items()
    ) + f"""
\\end{{itemize}}

\\section{{Grounded map provenance}}
\\begin{{itemize}}
  \\item grounded map summary yaml: \\path{{{grounded_yaml}}}
\\end{{itemize}}

\\section{{Post refinement}}
\\begin{{longtable}}{{p{{0.48\\linewidth}}p{{0.22\\linewidth}}}}
\\toprule
項目 & 値 \\\\
\\midrule
\\endhead
accepted & {post_refine.accepted} \\\\
panel gain factor & {post_refine.panel_gain_factor:.5f} \\\\
CdA factor & {post_refine.cda_factor:.5f} \\\\
Crr factor & {post_refine.crr_factor:.5f} \\\\
drive efficiency factor & {post_refine.drive_eff_factor:.5f} \\\\
headwind factor & {post_refine.headwind_gain_factor:.5f} \\\\
$E_{{nom}}$ factor & {post_refine.e_nom_factor:.5f} \\\\
$R_{{int}}$ factor & {post_refine.rint_factor:.5f} \\\\
\\bottomrule
\\end{{longtable}}

\\section{{Outputs}}
\\begin{{itemize}}
  \\item summary YAML: \\path{{{os.path.relpath(summary_yaml, report_dir).replace("\\", "/")}}}
  \\item current maps and coefficients: \\path{{{current_maps_rel_report}}}
\\end{{itemize}}

\\end{{document}}
"""
    tex_path.write_text(textwrap.dedent(tex).strip() + "\n", encoding="utf-8", newline="\n")
    compile_tex(tex_path)
    return md_path, pdf_path                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def main() -> None:                                                # [関数定義] main の処理実行ブロック
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--manifest")
    ap.add_argument(
        "--quality",
        choices=sorted(FIT_QUALITY_PRESETS.keys()),
        default=None,
        help="Override identification.fit_quality; omit to use the profile/manifest YAML value.",
    )
    ap.add_argument("--output-tag", help="Override identification.output_tag for versioned artifacts.")
    ap.add_argument(
        "--adopt-profile",
        action="store_true",
        help="Allow a tagged run to update the canonical profile.yaml; otherwise write a candidate profile in the run directory.",
    )
    ap.add_argument("--allow-map-shape-fit", action="store_true")
    ap.add_argument("--skip-map-shape-fit", action="store_true")
    ap.add_argument(
        "--rebuild-grounded-base-maps",
        action="store_true",
        help="Rebuild product/theory grounded maps before fitting instead of reusing manifest assets.",
    )
    ap.add_argument("--manifest-only", action="store_true")
    args = ap.parse_args()

    profile_yaml = resolve_relative(ROOT, args.profile)
    package_dir = profile_yaml.parent
    stage(f"loading profile: {profile_yaml}")
    profile_cfg = load_profile_yaml(profile_yaml)
    manifest_path, manifest = load_manifest(package_dir, args.manifest)
    manifest_context = resolve_manifest_context(package_dir, manifest)
    inputs = manifest_context["inputs"]
    options = dict(manifest_context["options"])
    identification_cfg = profile_cfg.get("identification", {}) or {}
    option_override_keys = (
        "fit_quality",
        "rebuild_grounded_base_maps",
        "use_grounded_base_maps",
        "allow_map_shape_fit",
        "post_refine_enabled",
        "sensor_filter",
        "acceleration_observation",
        "grade_observation",
        "panel_deployment_stopped_speed_kmh",
        "panel_deployment_min_dwell_sec",
        "panel_deployment_max_sample_gap_sec",
        "panel_control_stop_tolerance_km",
        "battery_restart_count",
        "battery_maxiter",
        "motion_restart_count",
        "motion_maxiter",
        "joint_restart_count",
        "joint_random_start_count",
        "joint_local_topk",
        "joint_maxiter",
        "fit_stride",
    )
    conflicting_options = [
        key
        for key in option_override_keys
        if key in identification_cfg
        and key in options
        and identification_cfg[key] != options[key]
    ]
    if conflicting_options:
        names = ", ".join(conflicting_options)
        raise ValueError(
            "identification options disagree between profile and manifest: "
            f"{names}. Keep duplicate YAML values identical or define each option in only one file."
        )
    for key in option_override_keys:
        if key in identification_cfg:
            options[key] = identification_cfg[key]
    fit_plan = resolve_fit_plan(options, quality=args.quality)
    panel_deployment_options = {
        "stopped_speed_kmh": float(fit_plan["panel_deployment_stopped_speed_kmh"]),
        "deployment_min_dwell_sec": float(fit_plan["panel_deployment_min_dwell_sec"]),
        "deployment_max_sample_gap_sec": float(fit_plan["panel_deployment_max_sample_gap_sec"]),
        "horizontal_control_stop_km": declared_control_stop_km(profile_cfg, profile_yaml),
        "control_stop_tolerance_km": float(fit_plan["panel_control_stop_tolerance_km"]),
    }
    output_layout = resolve_identification_output_layout(
        package_dir,
        profile_cfg,
        output_tag_override=args.output_tag,
    )
    run_output_dir = Path(output_layout["run_root"])
    report_output_dir = Path(output_layout["report_root"])

    if args.manifest_only:
        payload = {
            "profile_yaml": relpath_from(ROOT, profile_yaml),
            "manifest_yaml": relpath_from(ROOT, manifest_path),
            "actual_event_yaml": relpath_from(package_dir, manifest_context.get("actual_event_path")),
            "counterfactual_event_yaml": relpath_from(package_dir, manifest_context.get("counterfactual_event_path")),
            "terminal_anchor_yaml": relpath_from(package_dir, manifest_context.get("terminal_anchor_path")),
            "grounded_map_summary_yaml": relpath_from(package_dir, manifest_context.get("grounded_summary_path")),
            "source_inventory_json": relpath_from(package_dir, manifest_context.get("source_inventory_path")),
            "notes_markdown": relpath_from(package_dir, manifest_context.get("notes_markdown_path")),
            "explicit_grounded_assets": {
                key: relpath_from(package_dir, path)
                for key, path in manifest_context.get("explicit_grounded_assets", {}).items()
            },
            "external_documents": list(manifest_context.get("external_documents", [])),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    base_model = build_model_from_profile_cfg(profile_cfg, profile_yaml)
    source_map_assets = build_source_map_assets(profile_cfg, profile_yaml)
    grounded_map_summary: Dict[str, object] = dict(manifest_context.get("grounded_summary_payload", {}) or {})
    explicit_grounded_assets = manifest_context.get("explicit_grounded_assets", {})
    rebuild_grounded = bool(
        args.rebuild_grounded_base_maps
        or options.get("rebuild_grounded_base_maps", False)
    )
    if rebuild_grounded:
        stage("rebuilding grounded base maps from declared product/test evidence")
        source_map_assets, grounded_map_summary = build_grounded_map_assets(
            profile_cfg,
            Path(output_layout["grounded_maps"]),
            pv_area_m2=float((profile_cfg.get("model", {}) or {}).get("pv_area", 6.0)),
            base_dir=package_dir,
        )
        grounded_summary_file = Path(str(grounded_map_summary.get("summary_yaml", "") or "")).resolve()
        grounded_map_summary["summary_yaml"] = relpath_from(package_dir, grounded_summary_file)
        evidence_summary_path = manifest_context.get("grounded_summary_path")
        if evidence_summary_path is not None and not str(output_layout["tag"]):
            payload = dict(grounded_map_summary)
            payload.pop("summary_yaml", None)
            with Path(evidence_summary_path).open("w", encoding="utf-8", newline="\n") as f:
                yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
            manifest_context["grounded_summary_payload"] = payload
        base_model = build_model_from_map_assets(base_model, source_map_assets)
        ocv_df = pd.read_csv(source_map_assets["ocv_soc_map"])
    elif explicit_grounded_assets:
        stage("using grounded base maps declared in manifest")
        source_map_assets = explicit_grounded_assets
        base_model = build_model_from_map_assets(base_model, source_map_assets)
        ocv_df = pd.read_csv(source_map_assets["ocv_soc_map"])
    elif bool(options.get("use_grounded_base_maps", False)):
        stage("building grounded base maps")
        source_map_assets, grounded_map_summary = build_grounded_map_assets(
            profile_cfg,
            Path(output_layout["grounded_maps"]),
            pv_area_m2=float((profile_cfg.get("model", {}) or {}).get("pv_area", 6.0)),
            base_dir=package_dir,
        )
        grounded_summary_file = Path(str(grounded_map_summary.get("summary_yaml", "") or "")).resolve()
        grounded_map_summary["summary_yaml"] = relpath_from(package_dir, grounded_summary_file)
        base_model = build_model_from_map_assets(base_model, source_map_assets)
        ocv_df = pd.read_csv(source_map_assets["ocv_soc_map"])
    else:
        ocv_df = load_ocv_df(profile_cfg, profile_yaml)

    base_model = neutralize_identification_scalars(base_model)

    raw_log = str(inputs.get("normalized_replay_log_csv", "data/identification/raw/observed_replay_log.csv") or "").strip()
    observed_log_csv = resolve_relative(package_dir, raw_log)
    stage(f"loading observed replay log: {observed_log_csv}")
    logs = normalize_generic_log(
        observed_log_csv,
        actual_event_payload=manifest_context.get("actual_event_payload", {}),
        base_model=base_model,
        options=fit_plan,
    )
    stage("calibrating ZP solar-power measurement against stationary DC-bus balance")
    logs, solar_measurement_calibration = calibrate_solar_measurement_to_pack(
        logs,
        known_aux_power_w=float((profile_cfg.get("model", {}) or {}).get("P_aux", 21.0)),
    )
    fit_plan["solar_measurement_calibration"] = solar_measurement_calibration
    terminal_anchor_km = float(options.get("terminal_anchor_km", logs["s_km"].dropna().iloc[-1] if logs["s_km"].dropna().size else 0.0))
    terminal_anchor = build_terminal_anchor(logs, ocv_df, base_model, terminal_anchor_km)
    terminal_anchor.update(manifest_context.get("terminal_anchor_override", {}))
    stage_anchors = build_stage_anchors(logs, ocv_df, base_model)

    stage("fitting moving PV scalars from independent archive GHI")
    pv_fit = fit_pv_parameters(logs, base_model, irradiance_source="GHI_archive", operating_state="moving")
    pv_fit = fit_stop_tilt_fraction(logs, base_model, pv_fit, **panel_deployment_options)
    logs = attach_archive_pv_model(
        logs,
        base_model,
        pv_fit,
        irradiance_source="GHI_archive",
        **panel_deployment_options,
    )
    fit_df = resample_for_fit(logs)
    vehicle_fit_df = condition_vehicle_fit_on_measured_pv(fit_df)
    stage("fitting battery parameters")
    batt_stage = fit_battery_parameters(
        fit_df,
        ocv_df,
        base_model,
        terminal_anchor=terminal_anchor,
        stage_anchors=stage_anchors,
        restart_count=int(fit_plan["battery_restart_count"]),
        maxiter=int(fit_plan["battery_maxiter"]),
        fit_stride=int(fit_plan.get("fit_stride", 1)),
    )
    stage("fitting motion parameters")
    mot_stage = fit_motion_parameters(
        vehicle_fit_df,
        base_model,
        restart_count=int(fit_plan["motion_restart_count"]),
        maxiter=int(fit_plan["motion_maxiter"]),
        fit_stride=int(fit_plan.get("fit_stride", 1)),
    )
    stage("cross-validating GPS acceleration timestamp alignment")
    logs, acceleration_observation_fit = fit_acceleration_timestamp_alignment(
        logs,
        base_model,
        mot_stage,
        fit_plan.get("acceleration_observation", {}),
    )
    fit_plan["acceleration_observation_fit"] = acceleration_observation_fit
    if bool(acceleration_observation_fit.get("adopted", False)):
        fit_df = resample_for_fit(logs)
        vehicle_fit_df = condition_vehicle_fit_on_measured_pv(fit_df)
    route_profile_csv = resolve_relative(
        package_dir,
        str((profile_cfg.get("paths", {}) or {}).get("route_profile_csv", "")),
    )
    stage("cross-validating DEM grade smoothing and route-distance alignment")
    logs, grade_observation_fit, adopted_route_profile = fit_grade_observation_alignment(
        logs,
        route_profile_csv,
        run_output_dir / "adopted_route_profile.csv",
        base_model,
        mot_stage,
        fit_plan.get("grade_observation", {}),
    )
    fit_plan["grade_observation_fit"] = grade_observation_fit
    if bool(grade_observation_fit.get("adopted", False)):
        fit_df = resample_for_fit(logs)
        vehicle_fit_df = condition_vehicle_fit_on_measured_pv(fit_df)
        stage("refitting motion parameters on the cross-validated DEM grade")
        mot_stage = fit_motion_parameters(
            vehicle_fit_df,
            base_model,
            restart_count=int(fit_plan["motion_restart_count"]),
            maxiter=int(fit_plan["motion_maxiter"]),
            fit_stride=int(fit_plan.get("fit_stride", 1)),
        )
    stage("running joint battery-motion refinement")
    batt_fit, mot_fit, _ = joint_refine_parameters(
        vehicle_fit_df,
        ocv_df,
        base_model,
        batt_stage,
        mot_stage,
        terminal_anchor=terminal_anchor,
        stage_anchors=stage_anchors,
        restart_count=int(fit_plan["joint_restart_count"]),
        random_start_count=int(fit_plan["joint_random_start_count"]),
        local_topk=int(fit_plan["joint_local_topk"]),
        maxiter=int(fit_plan["joint_maxiter"]),
        fit_stride=int(fit_plan.get("fit_stride", 1)),
    )
    vehicle_logs = condition_vehicle_fit_on_measured_pv(logs)
    mot_fit = fit_regen_utilization(vehicle_logs, base_model, mot_fit)
    logs["headwind_effective_ms"] = logs["headwind_archive_ms"] * float(mot_fit.headwind_gain)
    end_to_end_replay_df = joint_replay(logs, ocv_df, base_model, batt_fit, mot_fit)
    vehicle_logs = condition_vehicle_fit_on_measured_pv(logs)
    replay_df = joint_replay(vehicle_logs, ocv_df, base_model, batt_fit, mot_fit)
    battery_conditioned_replay_df = joint_replay(
        vehicle_logs,
        ocv_df,
        base_model,
        batt_fit,
        mot_fit,
        battery_source="observed",
    )
    metrics = metrics_from_replay(replay_df)
    metrics.update(
        terminal_metrics(
            replay_df,
            ocv_df,
            base_model,
            batt_fit,
            terminal_anchor_km,
            terminal_anchor=terminal_anchor,
        )
    )
    battery_conditional_metrics = metrics_from_replay(battery_conditioned_replay_df)
    battery_conditional_metrics.update(
        terminal_metrics(
            battery_conditioned_replay_df,
            ocv_df,
            base_model,
            batt_fit,
            terminal_anchor_km,
            terminal_anchor=terminal_anchor,
        )
    )
    metrics = add_battery_conditional_metrics(metrics, battery_conditional_metrics)
    end_to_end_metrics = metrics_from_replay(end_to_end_replay_df)
    end_to_end_metrics.update(
        terminal_metrics(
            end_to_end_replay_df,
            ocv_df,
            base_model,
            batt_fit,
            terminal_anchor_km,
            terminal_anchor=terminal_anchor,
        )
    )
    metrics = add_end_to_end_metrics(metrics, end_to_end_metrics)

    allow_map_shape_fit = bool(fit_plan.get("allow_map_shape_fit", bool(options.get("allow_map_shape_fit", True))))
    if args.allow_map_shape_fit:
        allow_map_shape_fit = True
    if args.skip_map_shape_fit:
        allow_map_shape_fit = False

    map_shape_fit: Dict[str, object] = {}
    adopted_map_assets = source_map_assets
    adopted_model = base_model
    base_cycle_pv_fit = pv_fit
    base_cycle_batt_fit = batt_fit
    base_cycle_mot_fit = mot_fit
    base_cycle_logs = logs
    base_cycle_replay_df = replay_df
    base_cycle_battery_conditioned_replay_df = battery_conditioned_replay_df
    base_cycle_end_to_end_replay_df = end_to_end_replay_df
    base_cycle_metrics = dict(metrics)
    base_cycle_ocv_df = ocv_df
    base_cycle_stage_anchors = stage_anchors
    if allow_map_shape_fit:
        stage("fitting local map-shape corrections")
        map_shape_fit = fit_map_shapes(
            logs,
            vehicle_fit_df,
            battery_conditioned_replay_df,
            base_model,
            pv_fit,
            batt_fit,
            mot_fit,
            ocv_df,
        )
        adopted_map_assets = write_scaled_maps(
            source_map_assets,
            Path(output_layout["adopted_maps"]),
            shape_fits=map_shape_fit,
        )
        adopted_model = build_model_from_map_assets(base_model, adopted_map_assets)
        adopted_ocv_df = pd.read_csv(adopted_map_assets["ocv_soc_map"])
        adopted_stage_anchors = build_stage_anchors(logs, adopted_ocv_df, adopted_model)
        stage("refitting scalars on adopted maps")
        pv_fit = fit_pv_parameters(logs, adopted_model, irradiance_source="GHI_archive", operating_state="moving")
        pv_fit = fit_stop_tilt_fraction(logs, adopted_model, pv_fit, **panel_deployment_options)
        logs = attach_archive_pv_model(
            logs,
            adopted_model,
            pv_fit,
            irradiance_source="GHI_archive",
            **panel_deployment_options,
        )
        fit_df = resample_for_fit(logs)
        vehicle_fit_df = condition_vehicle_fit_on_measured_pv(fit_df)
        batt_stage = fit_battery_parameters(
            fit_df,
            adopted_ocv_df,
            adopted_model,
            terminal_anchor=terminal_anchor,
            stage_anchors=adopted_stage_anchors,
            restart_count=int(fit_plan["battery_restart_count"]),
            maxiter=int(fit_plan["battery_maxiter"]),
            fit_stride=int(fit_plan.get("fit_stride", 1)),
        )
        mot_stage = fit_motion_parameters(
            vehicle_fit_df,
            adopted_model,
            restart_count=int(fit_plan["motion_restart_count"]),
            maxiter=int(fit_plan["motion_maxiter"]),
            fit_stride=int(fit_plan.get("fit_stride", 1)),
        )
        stage("running joint refinement on adopted maps")
        batt_fit, mot_fit, _ = joint_refine_parameters(
            vehicle_fit_df,
            adopted_ocv_df,
            adopted_model,
            batt_stage,
            mot_stage,
            terminal_anchor=terminal_anchor,
            stage_anchors=adopted_stage_anchors,
            restart_count=int(fit_plan["joint_restart_count"]),
            random_start_count=int(fit_plan["joint_random_start_count"]),
            local_topk=int(fit_plan["joint_local_topk"]),
            maxiter=int(fit_plan["joint_maxiter"]),
            fit_stride=int(fit_plan.get("fit_stride", 1)),
        )
        vehicle_logs = condition_vehicle_fit_on_measured_pv(logs)
        mot_fit = fit_regen_utilization(vehicle_logs, adopted_model, mot_fit)
        logs["headwind_effective_ms"] = logs["headwind_archive_ms"] * float(mot_fit.headwind_gain)
        end_to_end_replay_df = joint_replay(logs, adopted_ocv_df, adopted_model, batt_fit, mot_fit)
        vehicle_logs = condition_vehicle_fit_on_measured_pv(logs)
        replay_df = joint_replay(vehicle_logs, adopted_ocv_df, adopted_model, batt_fit, mot_fit)
        battery_conditioned_replay_df = joint_replay(
            vehicle_logs,
            adopted_ocv_df,
            adopted_model,
            batt_fit,
            mot_fit,
            battery_source="observed",
        )
        metrics = metrics_from_replay(replay_df)
        metrics.update(
            terminal_metrics(
                replay_df,
                adopted_ocv_df,
                adopted_model,
                batt_fit,
                terminal_anchor_km,
                terminal_anchor=terminal_anchor,
            )
        )
        battery_conditional_metrics = metrics_from_replay(battery_conditioned_replay_df)
        battery_conditional_metrics.update(
            terminal_metrics(
                battery_conditioned_replay_df,
                adopted_ocv_df,
                adopted_model,
                batt_fit,
                terminal_anchor_km,
                terminal_anchor=terminal_anchor,
            )
        )
        metrics = add_battery_conditional_metrics(metrics, battery_conditional_metrics)
        end_to_end_metrics = metrics_from_replay(end_to_end_replay_df)
        end_to_end_metrics.update(
            terminal_metrics(
                end_to_end_replay_df,
                adopted_ocv_df,
                adopted_model,
                batt_fit,
                terminal_anchor_km,
                terminal_anchor=terminal_anchor,
            )
        )
        metrics = add_end_to_end_metrics(metrics, end_to_end_metrics)
        adopted_score = identification_selection_score(metrics)
        baseline_score = identification_selection_score(base_cycle_metrics)
        if not np.isfinite(adopted_score) or adopted_score > baseline_score + 1.0e-6:
            stage(
                f"rejecting adopted map set because replay score worsened: adopted={adopted_score:.3f} baseline={baseline_score:.3f}"
            )
            adopted_map_assets = source_map_assets
            adopted_model = base_model
            pv_fit = base_cycle_pv_fit
            batt_fit = base_cycle_batt_fit
            mot_fit = base_cycle_mot_fit
            logs = base_cycle_logs
            replay_df = base_cycle_replay_df
            battery_conditioned_replay_df = base_cycle_battery_conditioned_replay_df
            end_to_end_replay_df = base_cycle_end_to_end_replay_df
            metrics = dict(base_cycle_metrics)
            ocv_df = base_cycle_ocv_df
            stage_anchors = base_cycle_stage_anchors
            if isinstance(map_shape_fit, dict):
                map_shape_fit["adoption_status"] = "rejected"
                map_shape_fit["baseline_score"] = baseline_score
                map_shape_fit["adopted_score"] = adopted_score
        else:
            ocv_df = adopted_ocv_df
            stage_anchors = adopted_stage_anchors
            if isinstance(map_shape_fit, dict):
                map_shape_fit["adoption_status"] = "accepted"
                map_shape_fit["baseline_score"] = baseline_score
                map_shape_fit["adopted_score"] = adopted_score

    if has_identified_polarization_maps(adopted_model):
        stage("locking independently pulse-identified R1/tau maps")
        r1_values = np.asarray(adopted_model.R1map, dtype=float)
        tau_values = np.asarray(adopted_model.tau_map_values, dtype=float)
        battery_dynamic_fit = {
            "adopted": True,
            "reason": "independent_pulse_identified_maps_locked",
            "method": (
                "R1(z,T) and tau(z,T) were identified from declared train/validation pulse tests; "
                "race telemetry is evaluation-only and cannot overwrite either map"
            ),
            "road_log_refit_performed": False,
            "r_polarization_ohm": float(adopted_model.R_polarization(25.0, 0.5)),
            "tau_sec": float(adopted_model.polarization_tau(25.0, 0.5)),
            "r1_min_ohm": float(np.min(r1_values)),
            "r1_max_ohm": float(np.max(r1_values)),
            "tau_min_sec": float(np.min(tau_values)),
            "tau_max_sec": float(np.max(tau_values)),
            "dynamic_replay_already_applied": True,
        }
    else:
        stage("fitting legacy research-only battery 1-RC branch from race telemetry")
        battery_dynamic_fit = fit_battery_polarization(battery_conditioned_replay_df)
        replay_df = apply_battery_polarization(
            replay_df,
            battery_dynamic_fit,
            current_column="battery_current_a_pred",
        )
        battery_conditioned_replay_df = apply_battery_polarization(
            battery_conditioned_replay_df,
            battery_dynamic_fit,
            current_column="battery_current_a_obs",
        )
        end_to_end_replay_df = apply_battery_polarization(
            end_to_end_replay_df,
            battery_dynamic_fit,
            current_column="battery_current_a_pred",
        )
    metrics = metrics_from_replay(replay_df)
    metrics.update(
        terminal_metrics(
            replay_df,
            ocv_df,
            adopted_model,
            batt_fit,
            terminal_anchor_km,
            terminal_anchor=terminal_anchor,
        )
    )
    battery_conditional_metrics = metrics_from_replay(battery_conditioned_replay_df)
    battery_conditional_metrics.update(
        terminal_metrics(
            battery_conditioned_replay_df,
            ocv_df,
            adopted_model,
            batt_fit,
            terminal_anchor_km,
            terminal_anchor=terminal_anchor,
        )
    )
    metrics = add_battery_conditional_metrics(metrics, battery_conditional_metrics)
    end_to_end_metrics = metrics_from_replay(end_to_end_replay_df)
    end_to_end_metrics.update(
        terminal_metrics(
            end_to_end_replay_df,
            ocv_df,
            adopted_model,
            batt_fit,
            terminal_anchor_km,
            terminal_anchor=terminal_anchor,
        )
    )
    metrics = add_end_to_end_metrics(metrics, end_to_end_metrics)
    metrics["battery_polarization_r_ohm"] = float(battery_dynamic_fit.get("r_polarization_ohm", 0.0))
    metrics["battery_polarization_tau_sec"] = float(battery_dynamic_fit.get("tau_sec", 60.0))

    dcir_indices, dcir_observed_ohm = dcir_observations(logs)
    metrics["dcir_observation_count"] = int(len(dcir_indices))
    metrics["dcir_observed_median_ohm"] = (
        float(np.nanmedian(dcir_observed_ohm)) if len(dcir_observed_ohm) else float("nan")
    )
    metrics["dcir_observed_q10_ohm"] = (
        float(np.nanquantile(dcir_observed_ohm, 0.10)) if len(dcir_observed_ohm) else float("nan")
    )
    metrics["dcir_observed_q90_ohm"] = (
        float(np.nanquantile(dcir_observed_ohm, 0.90)) if len(dcir_observed_ohm) else float("nan")
    )
    metrics["dcir_fitted_25c_mid_soc_ohm"] = float(
        batt_fit.rint_scale * adopted_model.R_int(25.0, 0.50) + batt_fit.r_line_ohm
    )
    metrics["dcir_fitted_5s_with_polarization_ohm"] = float(
        metrics["dcir_fitted_25c_mid_soc_ohm"]
        + float(battery_dynamic_fit.get("r_polarization_ohm", 0.0))
        * (1.0 - math.exp(-5.0 / max(float(battery_dynamic_fit.get("tau_sec", 60.0)), 1.0e-6)))
    )
    metrics["solar_measurement_gain_to_pack"] = float(
        solar_measurement_calibration.get("gain_to_pack", 1.0)
    )
    metrics["solar_measurement_calibration_sample_count"] = int(
        solar_measurement_calibration.get("sample_count", 0)
    )
    metrics["solar_measurement_calibration_accepted"] = bool(
        solar_measurement_calibration.get("accepted", False)
    )
    stage("running leave-one-day-out PV validation")
    metrics.update(
        pv_leave_one_day_out_validation(
            logs,
            adopted_model,
            panel_deployment_options=panel_deployment_options,
        )
    )

    if bool(fit_plan.get("post_refine_enabled", False)):
        stage("skipping legacy post-refinement because it mixes forecast-PV error into vehicle coefficients")
    else:
        stage("skipping post-refinement scalar sweep for current fit quality preset")
    post_refine = PostRefineResult(
        panel_gain_factor=1.0,
        cda_factor=1.0,
        crr_factor=1.0,
        drive_eff_factor=1.0,
        headwind_gain_factor=1.0,
        e_nom_factor=1.0,
        rint_factor=1.0,
        objective=float("nan"),
        accepted=False,
        power_rmse_clean_w=float(metrics.get("power_rmse_clean_w", float("nan"))),
        voltage_rmse_clean_v=float(metrics.get("voltage_rmse_clean_v", float("nan"))),
        retire_anchor_soc_error=float(metrics.get("retire_anchor_soc_error", float("nan"))),
        retire_anchor_voltage_error_v=float(
            float(metrics.get("retire_anchor_voltage_pred_v", float("nan")))
            - float(metrics.get("retire_anchor_voltage_obs_v", float("nan")))
        ),
    )

    replay_out = run_output_dir / "replay_validation.csv"
    replay_battery_conditioned_out = run_output_dir / "replay_validation_battery_conditioned.csv"
    replay_end_to_end_out = run_output_dir / "replay_validation_end_to_end.csv"
    ensure_dir(replay_out.parent)
    write_replay_csv(replay_df, replay_out)
    write_replay_csv(battery_conditioned_replay_df, replay_battery_conditioned_out)
    write_replay_csv(end_to_end_replay_df, replay_end_to_end_out)
    residual_audit_dir = report_output_dir / "residual_audit"
    stage("auditing residual regimes and long-horizon SoC divergence")
    run_residual_audit(
        replay_out,
        replay_battery_conditioned_out,
        replay_end_to_end_out,
        residual_audit_dir,
        rint_map_path=Path(adopted_map_assets["rint_map"]),
        rint_scale=float(batt_fit.rint_scale),
        r_line_ohm=float(batt_fit.r_line_ohm),
        r_polarization_ohm=float(
            battery_dynamic_fit.get("r_polarization_ohm", 0.0)
        ),
        high_soc_threshold=float(
            identification_cfg.get("rint_high_soc_audit_threshold", 0.85)
        ),
    )
    day_metrics = replay_day_metrics(replay_df)

    stage("writing profile, summary, and report")
    profile_output_yaml = identification_profile_output_path(
        profile_yaml,
        run_output_dir,
        output_tag=str(output_layout["tag"]),
        adopt_profile=bool(args.adopt_profile),
    )
    update_profile(
        profile_output_yaml,
        profile_cfg,
        adopted_map_assets,
        pv_fit,
        batt_fit,
        mot_fit,
        observed_log_csv,
        battery_dynamic_fit=battery_dynamic_fit,
        solar_measurement_calibration=solar_measurement_calibration,
        route_profile_asset=adopted_route_profile,
        package_dir=package_dir,
    )
    synced_fullsim_yaml = None
    canonical_adoption_allowed = not str(output_layout["tag"]) or bool(args.adopt_profile)
    if canonical_adoption_allowed and bool(
        identification_cfg.get("sync_canonical_fullsim_profile", not str(output_layout["tag"]))
    ):
        synced_fullsim_yaml = sync_canonical_fullsim_profile(
            package_dir,
            map_assets=adopted_map_assets,
            pv=pv_fit,
            batt=batt_fit,
            mot=mot_fit,
            battery_dynamic_fit=battery_dynamic_fit,
            solar_measurement_calibration=solar_measurement_calibration,
            observed_log_csv=observed_log_csv,
        )
    if synced_fullsim_yaml is not None:
        stage(f"synchronized canonical fullsim profile: {relpath_from(package_dir, synced_fullsim_yaml)}")
    summary_yaml = write_generic_summary(
        package_dir,
        manifest_path,
        profile_output_yaml,
        adopted_map_assets,
        pv_fit,
        batt_fit,
        mot_fit,
        metrics,
        terminal_anchor,
        stage_anchors,
        map_shape_fit,
        post_refine,
        day_metrics,
        battery_dynamic_fit=battery_dynamic_fit,
        fit_plan=fit_plan,
        manifest_context=manifest_context,
        output_dir=run_output_dir,
        replay_csv=replay_out,
        battery_conditioned_replay_csv=replay_battery_conditioned_out,
        end_to_end_replay_csv=replay_end_to_end_out,
    )
    terminal_consistency_path = run_output_dir / "terminal_soc_consistency.yaml"
    gate_cfg = (profile_cfg.get("identification", {}) or {}).get("validation_gate", {}) or {}
    write_terminal_consistency_from_anchor(
        terminal_consistency_path,
        terminal_anchor,
        max_spread=float(gate_cfg.get("terminal_soc_evidence_spread_max", 0.05)),
        validation_metrics=metrics,
        replay_soc_error_max=float(gate_cfg.get("terminal_replay_soc_error_max", 0.02)),
        replay_voltage_error_max_v=float(
            gate_cfg.get("terminal_replay_voltage_error_max_v", 0.5)
        ),
        vehicle_soc_error_max=float(gate_cfg.get("vehicle_terminal_soc_error_max", 0.02)),
        vehicle_voltage_error_max_v=float(
            gate_cfg.get("vehicle_terminal_voltage_error_max_v", 0.5)
        ),
        end_to_end_soc_error_max=float(
            gate_cfg.get("end_to_end_terminal_soc_error_max", 0.03)
        ),
        end_to_end_voltage_error_max_v=float(
            gate_cfg.get("end_to_end_terminal_voltage_error_max_v", 1.0)
        ),
    )
    update_profile_artifact_references(
        profile_output_yaml,
        package_dir,
        fit_summary_yaml=summary_yaml,
        terminal_consistency_yaml=terminal_consistency_path,
    )
    if synced_fullsim_yaml is not None:
        update_profile_artifact_references(
            synced_fullsim_yaml,
            package_dir,
            fit_summary_yaml=summary_yaml,
            terminal_consistency_yaml=terminal_consistency_path,
        )
    current_md = write_current_maps_and_coefficients(
        package_dir,
        profile_output_yaml,
        adopted_map_assets,
        pv_fit,
        batt_fit,
        mot_fit,
        metrics,
        grounded_map_summary=grounded_map_summary,
        map_shape_fit=map_shape_fit,
        post_refine=post_refine,
        fit_plan=fit_plan,
        output_path=report_output_dir / "current_maps_and_coefficients.md",
        terminal_consistency_path=terminal_consistency_path,
        fit_summary_path=summary_yaml,
        report_path=report_output_dir / f"{package_dir.name}_generic_identification_report.pdf",
    )
    report_md, report_pdf = write_generic_report(
        package_dir,
        profile_output_yaml,
        manifest_path,
        summary_yaml,
        observed_log_csv,
        pv_fit,
        batt_fit,
        mot_fit,
        metrics,
        post_refine,
        adopted_map_assets,
        terminal_anchor=terminal_anchor,
        stage_anchors=stage_anchors,
        day_metrics=day_metrics,
        battery_dynamic_fit=battery_dynamic_fit,
        fit_plan=fit_plan,
        grounded_map_summary=grounded_map_summary,
        manifest_context=manifest_context,
        terminal_consistency=(
            yaml.safe_load(terminal_consistency_path.read_text(encoding="utf-8")) or {}
        ),
        report_dir=report_output_dir,
        current_maps_path=current_md,
    )

    payload = {
        "profile_yaml": str(profile_yaml),
        "manifest_yaml": str(manifest_path),
        "summary_yaml": str(summary_yaml),
        "current_maps_md": str(current_md),
        "replay_validation_csv": str(replay_out),
        "replay_validation_battery_conditioned_csv": str(replay_battery_conditioned_out),
        "replay_validation_end_to_end_csv": str(replay_end_to_end_out),
        "residual_audit_json": str(residual_audit_dir / "residual_audit.json"),
        "residual_regime_metrics_csv": str(
            residual_audit_dir / "residual_regime_metrics.csv"
        ),
        "voltage_soc_current_metrics_csv": str(
            residual_audit_dir / "voltage_soc_current_metrics.csv"
        ),
        "high_soc_rint_counterfactual_trace_csv": str(
            residual_audit_dir / "high_soc_rint_counterfactual_trace.csv"
        ),
        "high_soc_rint_counterfactual_map_csv": str(
            residual_audit_dir / "Rint_T_by_soc_high_soc_flat_counterfactual.csv"
        ),
        "weather_daily_metrics_csv": str(
            residual_audit_dir / "weather_daily_metrics.csv"
        ),
        "soc_divergence_trace_csv": str(
            residual_audit_dir / "soc_divergence_trace.csv"
        ),
        "residual_soc_audit_png": str(
            residual_audit_dir / "residual_soc_audit.png"
        ),
        "report_md": str(report_md),
        "report_pdf": str(report_pdf),
    }
    stage("completed")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()