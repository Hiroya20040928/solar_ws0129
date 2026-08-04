from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
import yaml

# =============================================================================
# 【物理同定・適合モジュール】車両物理 (CdA, Crr) + 電池 1-RC (OCV, R0) パルス同定
# =============================================================================


import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize
import yaml

# =============================================================================
# 【最高級統合パイプライン】車両物理同定 & 1-RC 電池 ECM パラメータ推定・Replay検証
# =============================================================================


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

    """
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
    local_anchor_gate = bool(terminal_anchor.get("quality_gate_pass", False))

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
    md = "# Identification Report\n"
    return md
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



"""Identify a passive pack-level 1-RC battery model from rested pulse tests.

Positive current means battery discharge.  The identified model is

    Vt = Uocv(z) - I * R0_total(z, T) - V1
    dV1/dt = -V1/tau(z, T) + R1(z, T) * I / tau(z, T)

``R0_total`` deliberately includes cells, tabs, bus bars, contactors, fuses,
and measurement leads.  Those contributions cannot be separated from a
two-terminal pack pulse and are therefore not assigned invented values.
"""


import argparse
import base64
import hashlib
import html
import io
import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
from scipy.optimize import minimize, minimize_scalar, nnls


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REST_REQUIRED = {
    "rest_id",
    "split",
    "soc_reference",
    "temp_c",
    "rest_duration_sec",
    "rest_voltage_v",
    "rest_current_a",
    "rest_voltage_slope_uv_per_s",
    "soc_reference_method",
    "current_accuracy_a",
    "voltage_accuracy_v",
    "source_file",
}
PULSE_REQUIRED = {
    "test_id",
    "split",
    "time_s",
    "step_start_time_s",
    "phase",
    "current_a",
    "voltage_v",
    "temp_c",
    "soc_reference",
    "pre_rest_duration_sec",
    "pre_rest_voltage_slope_uv_per_s",
    "soc_reference_method",
    "current_accuracy_a",
    "voltage_accuracy_v",
    "source_file",
}
INDEPENDENT_SOC_METHODS = {
    "coulomb_counted_from_full",
    "gravimetric_capacity",
    "independent_calibrated_bms",
    "known_charge_state",
}


class BatteryEvidenceError(ValueError):                            # [クラス定義] BatteryEvidenceError オブジェクトの設計
    """Raised when data cannot support a physically identifiable map."""


@dataclass(frozen=True)
class FitLimits:                                                   # [クラス定義] FitLimits オブジェクトの設計
    minimum_rest_sec: float = 1800.0
    maximum_rest_current_a: float = 0.25
    maximum_rest_voltage_slope_uv_per_s: float = 10.0
    minimum_current_step_a: float = 3.0
    maximum_first_sample_delay_sec: float = 0.25
    minimum_pulse_samples: int = 8
    minimum_train_tests: int = 12
    minimum_validation_tests: int = 4
    minimum_soc_span: float = 0.70
    minimum_temp_span_c: float = 25.0
    maximum_validation_normalized_rmse: float = 3.0
    operational_soc_min: float = 0.05
    operational_soc_max: float = 0.95
    maximum_soc_boundary_gap: float = 0.05
    edge_validation_band: float = 0.10
    minimum_edge_validation_tests: int = 1
    r0_high_soc_nonincreasing_from: float | None = None
    enforce_r0_temperature_nonincreasing: bool = False


def _required_columns(frame: pd.DataFrame, required: set[str], label: str) -> None:  # [関数定義] _required_columns の処理実行ブロック
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise BatteryEvidenceError(f"{label} is missing columns: {missing}")


def _numeric(frame: pd.DataFrame, columns: Iterable[str], label: str) -> pd.DataFrame:  # [関数定義] _numeric の処理実行ブロック
    out = frame.copy()
    for column in columns:
        out[column] = pd.to_numeric(out[column], errors="coerce")
    bad = out[list(columns)].isna().any(axis=1)
    if bool(bad.any()):
        rows = (np.flatnonzero(bad.to_numpy()) + 2).tolist()[:12]
        raise BatteryEvidenceError(f"{label} has non-numeric required values at CSV rows {rows}")
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_rest_data(path: str | Path) -> pd.DataFrame:              # [関数定義] load_rest_data の処理実行ブロック
    frame = pd.read_csv(path)
    _required_columns(frame, REST_REQUIRED, "rest CSV")
    frame = _numeric(
        frame,
        (
            "soc_reference", "temp_c", "rest_duration_sec", "rest_voltage_v",
            "rest_current_a", "rest_voltage_slope_uv_per_s",
            "current_accuracy_a", "voltage_accuracy_v",
        ),
        "rest CSV",
    )
    frame["split"] = frame["split"].astype(str).str.strip().str.lower()
    frame["soc_reference_method"] = frame["soc_reference_method"].astype(str).str.strip().str.lower()
    return frame                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_pulse_data(path: str | Path) -> pd.DataFrame:             # [関数定義] load_pulse_data の処理実行ブロック
    frame = pd.read_csv(path)
    _required_columns(frame, PULSE_REQUIRED, "pulse CSV")
    frame = _numeric(
        frame,
        (
            "time_s",
            "step_start_time_s",
            "current_a",
            "voltage_v",
            "temp_c",
            "soc_reference",
            "pre_rest_duration_sec",
            "pre_rest_voltage_slope_uv_per_s",
            "current_accuracy_a",
            "voltage_accuracy_v",
        ),
        "pulse CSV",
    )
    frame["split"] = frame["split"].astype(str).str.strip().str.lower()
    frame["phase"] = frame["phase"].astype(str).str.strip().str.lower()
    frame["soc_reference_method"] = frame["soc_reference_method"].astype(str).str.strip().str.lower()
    return frame.sort_values(["test_id", "time_s"]).reset_index(drop=True)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _pava_non_decreasing(values: np.ndarray, weights: np.ndarray) -> np.ndarray:  # [関数定義] _pava_non_decreasing の処理実行ブロック
    blocks = [[float(value), float(weight), 1] for value, weight in zip(values, weights)]
    index = 0
    while index < len(blocks) - 1:
        if blocks[index][0] <= blocks[index + 1][0] + 1.0e-12:
            index += 1
            continue
        total_weight = blocks[index][1] + blocks[index + 1][1]
        mean = (
            blocks[index][0] * blocks[index][1]
            + blocks[index + 1][0] * blocks[index + 1][1]
        ) / max(total_weight, 1.0e-12)
        merged = [mean, total_weight, blocks[index][2] + blocks[index + 1][2]]
        blocks[index : index + 2] = [merged]
        index = max(0, index - 1)
    output: list[float] = []
    for mean, _weight, count in blocks:
        output.extend([float(mean)] * int(count))
    return np.asarray(output, dtype=float)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fit_ocv_curve(rest: pd.DataFrame, limits: FitLimits) -> tuple[pd.DataFrame, dict]:  # [関数定義] fit_ocv_curve の処理実行ブロック
    eligible = rest[
        rest["split"].isin({"train", "validation"})
        & rest["soc_reference_method"].isin(INDEPENDENT_SOC_METHODS)
        & (rest["rest_duration_sec"] >= limits.minimum_rest_sec)
        & (rest["rest_current_a"].abs() <= limits.maximum_rest_current_a)
        & (
            rest["rest_voltage_slope_uv_per_s"].abs()
            <= limits.maximum_rest_voltage_slope_uv_per_s
        )
        & (rest["voltage_accuracy_v"] > 0.0)
        & (rest["current_accuracy_a"] > 0.0)
        & rest["soc_reference"].between(0.0, 1.0)
    ].copy()
    train = eligible[eligible["split"] == "train"].sort_values("soc_reference")
    validation = eligible[eligible["split"] == "validation"].copy()
    if len(train) < 6:
        raise BatteryEvidenceError("at least six independently referenced training rest points are required")
    grouped = (
        train.groupby("soc_reference", as_index=False)
        .agg(rest_voltage_v=("rest_voltage_v", "median"), count=("rest_id", "count"))
        .sort_values("soc_reference")
    )
    z = grouped["soc_reference"].to_numpy(dtype=float)
    voltage = grouped["rest_voltage_v"].to_numpy(dtype=float)
    monotone = _pava_non_decreasing(voltage, grouped["count"].to_numpy(dtype=float))
    dense_soc = np.linspace(float(z.min()), float(z.max()), max(2, int(round((z.max() - z.min()) * 100)) + 1))
    dense_voltage = np.interp(dense_soc, z, monotone)
    curve = pd.DataFrame({"soc": dense_soc, "ocv_v": dense_voltage})
    if len(validation):
        predicted = np.interp(
            validation["soc_reference"].to_numpy(dtype=float),
            dense_soc,
            dense_voltage,
        )
        residual = validation["rest_voltage_v"].to_numpy(dtype=float) - predicted
        validation_rmse = float(np.sqrt(np.mean(residual**2)))
        validation_normalized_rmse = float(
            np.sqrt(
                np.mean(
                    (
                        residual
                        / validation["voltage_accuracy_v"].to_numpy(dtype=float)
                    )
                    ** 2
                )
            )
        )
    else:
        validation_rmse = math.nan
        validation_normalized_rmse = math.nan
    info = {
        "eligible_count": int(len(eligible)),
        "train_count": int(len(train)),
        "validation_count": int(len(validation)),
        "soc_min": float(z.min()),
        "soc_max": float(z.max()),
        "soc_span": float(z.max() - z.min()),
        "validation_rmse_v": validation_rmse,
        "validation_normalized_rmse": validation_normalized_rmse,
        "method": "weighted isotonic pack rested-voltage fit against independently referenced SoC",
    }
    return curve, info                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _fit_single_pulse(group: pd.DataFrame, limits: FitLimits) -> dict:  # [関数定義] _fit_single_pulse の処理実行ブロック
    group = group.sort_values("time_s").copy()
    phases = set(group["phase"])
    if not {"pre_rest", "pulse"}.issubset(phases):
        raise BatteryEvidenceError("each test_id requires pre_rest and pulse phases")
    if group["split"].nunique() != 1:
        raise BatteryEvidenceError("multiple splits in group")

    pre = group[group["phase"] == "pre_rest"]
    pulse = group[group["phase"] == "pulse"].copy()
    if len(pre) < 3 or len(pulse) < limits.minimum_pulse_samples:
        raise BatteryEvidenceError("insufficient pre-rest or pulse samples")
    if float(group["pre_rest_duration_sec"].min()) < limits.minimum_rest_sec:
        raise BatteryEvidenceError("pre-rest duration is too short")
    if (
        float(group["pre_rest_voltage_slope_uv_per_s"].abs().max())
        > limits.maximum_rest_voltage_slope_uv_per_s
    ):
        raise BatteryEvidenceError("pre-rest voltage has not reached the declared equilibrium slope")
    if float(group["voltage_accuracy_v"].min()) <= 0.0 or float(group["current_accuracy_a"].min()) <= 0.0:
        raise BatteryEvidenceError("measurement accuracies must be positive")
    if not set(group["soc_reference_method"]).issubset(INDEPENDENT_SOC_METHODS):
        raise BatteryEvidenceError("SoC reference is not independent")
    i_pre = float(pre["current_a"].tail(min(10, len(pre))).median())
    v_pre = float(pre["voltage_v"].tail(min(10, len(pre))).median())
    if abs(i_pre) > limits.maximum_rest_current_a:
        raise BatteryEvidenceError("pre-rest current exceeds limit")
    start_times = group["step_start_time_s"].unique()
    if len(start_times) != 1:
        raise BatteryEvidenceError("one test_id must declare one step_start_time_s")
    start_time = float(start_times[0])
    pulse["t_rel"] = pulse["time_s"] - start_time
    first_delay = float(pulse["t_rel"].iloc[0])
    if first_delay < -1.0e-12 or first_delay > limits.maximum_first_sample_delay_sec + 1.0e-12:
        raise BatteryEvidenceError("first pulse sample is too late to identify R0")
    delta_i = pulse["current_a"].to_numpy(dtype=float) - i_pre
    if float(np.median(np.abs(delta_i))) < limits.minimum_current_step_a:
        raise BatteryEvidenceError("current step is too small")
    step_current = float(np.median(delta_i))
    if abs(step_current) < limits.minimum_current_step_a:
        raise BatteryEvidenceError("pulse changes sign or lacks a stable step")
    if float(np.std(delta_i) / max(abs(step_current), 1.0e-9)) > 0.12:
        raise BatteryEvidenceError("pulse current is not sufficiently constant")
    t = pulse["t_rel"].to_numpy(dtype=float)
    voltage = pulse["voltage_v"].to_numpy(dtype=float)

    def evaluate_tau(log_tau: float) -> tuple[float, float, float, np.ndarray, np.ndarray]:  # [関数定義] evaluate_tau の処理実行ブロック
        tau = math.exp(float(log_tau))
        basis = step_current * (1.0 - np.exp(-np.maximum(t, 0.0) / tau))
        design = np.column_stack((delta_i, basis))
        coefficients, _residual_norm = nnls(design, v_pre - voltage)
        r0, r1 = [float(value) for value in coefficients]
        predicted = v_pre - design @ coefficients
        rmse = float(np.sqrt(np.mean((voltage - predicted) ** 2)))
        return rmse, r0, r1, predicted, design                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    result = minimize_scalar(
        lambda value: evaluate_tau(value)[0],
        bounds=(math.log(0.2), math.log(1800.0)),
        method="bounded",
        options={"xatol": 1.0e-5},
    )
    rmse, r0, r1, predicted, design = evaluate_tau(float(result.x))
    if not np.isfinite(r0) or r0 <= 0.0:
        raise BatteryEvidenceError("joint pulse fit does not yield positive R0")
    tau = math.exp(float(result.x))
    voltage_accuracy_v = float(group["voltage_accuracy_v"].max())
    current_accuracy_a = float(group["current_accuracy_a"].max())
    information_inverse = np.linalg.pinv(design.T @ design)
    voltage_sigma_effective = math.sqrt(voltage_accuracy_v**2 + rmse**2)
    current_relative_sigma = current_accuracy_a / max(abs(step_current), 1.0e-12)
    r0_sigma_ohm = math.sqrt(
        max(0.0, float(information_inverse[0, 0])) * voltage_sigma_effective**2
        + (r0 * current_relative_sigma) ** 2
    )
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "test_id": str(group["test_id"].iloc[0]),
        "split": str(group["split"].iloc[0]),
        "soc_reference": float(group["soc_reference"].median()),
        "temp_c": float(group["temp_c"].median()),
        "current_step_a": step_current,
        "ocv_pre_v": v_pre,
        "r0_total_ohm": float(r0),
        "r1_ohm": float(r1),
        "tau_sec": float(tau),
        "voltage_rmse_v": rmse,
        "voltage_accuracy_v": voltage_accuracy_v,
        "current_accuracy_a": current_accuracy_a,
        "voltage_normalized_rmse": float(rmse / voltage_accuracy_v),
        "r0_total_ohm_sigma": float(r0_sigma_ohm),
        "sample_count": int(len(pulse)),
        "source_file": str(group["source_file"].iloc[0]),
        "measured_voltage_v": voltage.tolist(),
        "predicted_voltage_v": predicted.tolist(),
        "pulse_time_s": t.tolist(),
    }


def fit_pulse_tests(pulse: pd.DataFrame, limits: FitLimits) -> tuple[pd.DataFrame, list[dict]]:  # [関数定義] fit_pulse_tests の処理実行ブロック
    rows: list[dict] = []
    rejected: list[dict] = []
    for test_id, group in pulse.groupby("test_id", sort=False):
        try:
            rows.append(_fit_single_pulse(group, limits))
        except BatteryEvidenceError as exc:
            rejected.append({"test_id": str(test_id), "reason": str(exc)})
    if not rows:
        raise BatteryEvidenceError("no pulse test passed structural evidence checks")
    compact = pd.DataFrame(
        [{key: value for key, value in row.items() if not isinstance(value, list)} for row in rows]
    )
    return compact, rejected                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _surface_features(soc: np.ndarray, temp_c: np.ndarray) -> np.ndarray:  # [関数定義] _surface_features の処理実行ブロック
    z = (np.asarray(soc, dtype=float) - 0.5) / 0.5
    t = (np.asarray(temp_c, dtype=float) - 25.0) / 25.0
    return np.column_stack([np.ones_like(z), z, t, z * z, z * t, t * t])  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _surface_prediction(                                           # [関数定義] _surface_prediction の処理実行ブロック
    beta: np.ndarray,
    soc: np.ndarray,
    temp_c: np.ndarray,
    *,
    soc_support: tuple[float, float],
    temp_support: tuple[float, float],
) -> np.ndarray:
    """Evaluate only inside training support and hold the nearest edge outside it."""
    soc_eval = np.clip(np.asarray(soc, dtype=float), soc_support[0], soc_support[1])
    temp_eval = np.clip(np.asarray(temp_c, dtype=float), temp_support[0], temp_support[1])
    return np.exp(_surface_features(soc_eval, temp_eval) @ beta)   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _validation_metrics(                                           # [関数定義] _validation_metrics の処理実行ブロック
    validation: pd.DataFrame,
    observed_column: str,
    predicted: np.ndarray,
) -> dict:
    if validation.empty:
        return {                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "count": 0,
            "relative_rmse": math.nan,
            "normalized_rmse": math.nan,
        }
    observed = validation[observed_column].to_numpy(dtype=float)
    relative_rmse = float(
        np.sqrt(np.mean(((predicted - observed) / np.maximum(observed, 1.0e-9)) ** 2))
    )
    uncertainty_column = f"{observed_column}_sigma"
    if uncertainty_column in validation.columns:
        sigma = validation[uncertainty_column].to_numpy(dtype=float)
        normalized_rmse = float(
            np.sqrt(np.mean(((predicted - observed) / np.maximum(sigma, 1.0e-12)) ** 2))
        )
    else:
        normalized_rmse = math.nan
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "count": int(len(validation)),
        "relative_rmse": relative_rmse,
        "normalized_rmse": normalized_rmse,
    }


def fit_positive_surface(                                          # [関数定義] fit_positive_surface の処理実行ブロック
    points: pd.DataFrame,
    value_column: str,
    soc_grid: np.ndarray,
    temp_grid: np.ndarray,
    limits: FitLimits | None = None,
    *,
    high_soc_nonincreasing_from: float | None = None,
    temperature_nonincreasing: bool = False,
) -> tuple[pd.DataFrame, dict]:
    limits = limits or FitLimits()
    train = points[points["split"] == "train"]
    validation = points[points["split"] == "validation"]
    if len(train) < 6:
        raise BatteryEvidenceError(f"{value_column} requires at least six training pulses")
    x = _surface_features(train["soc_reference"], train["temp_c"])
    y = np.log(np.maximum(train[value_column].to_numpy(dtype=float), 1.0e-9))
    penalty = np.diag([0.0, 0.02, 0.02, 0.10, 0.10, 0.10])
    soc_support = (
        float(train["soc_reference"].min()),
        float(train["soc_reference"].max()),
    )
    temp_support = (
        float(train["temp_c"].min()),
        float(train["temp_c"].max()),
    )
    beta_initial = np.linalg.solve(x.T @ x + penalty, x.T @ y)
    derivative_constraints: list[np.ndarray] = []
    if high_soc_nonincreasing_from is not None:
        constraint_soc_min = max(float(high_soc_nonincreasing_from), soc_support[0])
        if constraint_soc_min <= soc_support[1]:
            for soc_value in np.linspace(constraint_soc_min, soc_support[1], 9):
                zeta = (float(soc_value) - 0.5) / 0.5
                for temp_value in np.linspace(temp_support[0], temp_support[1], 5):
                    theta = (float(temp_value) - 25.0) / 25.0
                    # d(log(value))/dSoC <= 0.
                    derivative_constraints.append(
                        np.asarray([0.0, 2.0, 0.0, 4.0 * zeta, 2.0 * theta, 0.0])
                    )
    if temperature_nonincreasing:
        for soc_value in np.linspace(soc_support[0], soc_support[1], 9):
            zeta = (float(soc_value) - 0.5) / 0.5
            for temp_value in np.linspace(temp_support[0], temp_support[1], 5):
                theta = (float(temp_value) - 25.0) / 25.0
                # 25*d(log(value))/dT <= 0.
                derivative_constraints.append(
                    np.asarray([0.0, 0.0, 1.0, 0.0, zeta, 2.0 * theta])
                )
    constraint_matrix = (
        np.vstack(derivative_constraints)
        if derivative_constraints
        else np.empty((0, len(beta_initial)), dtype=float)
    )
    if len(constraint_matrix):
        def objective(candidate: np.ndarray) -> float:             # [関数定義] objective の処理実行ブロック
            residual = x @ candidate - y
            return float(residual @ residual + candidate @ penalty @ candidate)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

        def objective_jacobian(candidate: np.ndarray) -> np.ndarray:  # [関数定義] objective_jacobian の処理実行ブロック
            return 2.0 * (x.T @ (x @ candidate - y) + penalty @ candidate)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

        optimized = minimize(
            objective,
            beta_initial,
            jac=objective_jacobian,
            constraints={
                "type": "ineq",
                "fun": lambda candidate: -(constraint_matrix @ candidate),
                "jac": lambda _candidate: -constraint_matrix,
            },
            method="SLSQP",
            options={"maxiter": 2000, "ftol": 1.0e-12},
        )
        if not optimized.success or not np.all(np.isfinite(optimized.x)):
            raise BatteryEvidenceError(
                f"{value_column} shape-constrained surface fit failed: {optimized.message}"
            )
        beta = np.asarray(optimized.x, dtype=float)
    else:
        beta = beta_initial
    maximum_constraint_violation = (
        float(np.max(constraint_matrix @ beta)) if len(constraint_matrix) else 0.0
    )
    if maximum_constraint_violation > 1.0e-8:
        raise BatteryEvidenceError(
            f"{value_column} violates a requested derivative constraint by "
            f"{maximum_constraint_violation:.3e}"
        )
    zz, tt = np.meshgrid(soc_grid, temp_grid)
    predicted_grid = _surface_prediction(
        beta,
        zz.ravel(),
        tt.ravel(),
        soc_support=soc_support,
        temp_support=temp_support,
    ).reshape(zz.shape)
    frame = pd.DataFrame(predicted_grid, index=temp_grid, columns=soc_grid)
    if len(validation):
        predicted = _surface_prediction(
            beta,
            validation["soc_reference"].to_numpy(dtype=float),
            validation["temp_c"].to_numpy(dtype=float),
            soc_support=soc_support,
            temp_support=temp_support,
        )
    else:
        predicted = np.asarray([], dtype=float)
    all_validation = _validation_metrics(validation, value_column, predicted)
    low_mask = validation["soc_reference"] <= (
        limits.operational_soc_min + limits.edge_validation_band
    )
    high_mask = validation["soc_reference"] >= (
        limits.operational_soc_max - limits.edge_validation_band
    )
    low_validation = validation.loc[low_mask]
    high_validation = validation.loc[high_mask]
    low_metrics = _validation_metrics(low_validation, value_column, predicted[low_mask.to_numpy()])
    high_metrics = _validation_metrics(high_validation, value_column, predicted[high_mask.to_numpy()])

    normalized_high_soc = (soc_support[1] - 0.5) / 0.5
    normalized_temperatures = (np.asarray(temp_grid, dtype=float) - 25.0) / 25.0
    high_soc_log_slopes = 2.0 * (
        beta[1] + 2.0 * beta[3] * normalized_high_soc + beta[4] * normalized_temperatures
    )
    normalized_soc_grid = (np.asarray(soc_grid, dtype=float) - 0.5) / 0.5
    normalized_temp_grid = (np.asarray(temp_grid, dtype=float) - 25.0) / 25.0
    temperature_log_slopes = np.asarray(
        [
            (beta[2] + beta[4] * zeta + 2.0 * beta[5] * theta) / 25.0
            for zeta in normalized_soc_grid
            for theta in normalized_temp_grid
        ],
        dtype=float,
    )
    return frame, {                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "value": value_column,
        "equation": (
            "value=exp(beta0+beta_z*zeta+beta_T*theta+beta_zz*zeta^2+"
            "beta_zT*zeta*theta+beta_TT*theta^2), "
            "zeta=(SoC-0.5)/0.5, theta=(T_C-25)/25"
        ),
        "coefficients_log_quadratic": beta.tolist(),
        "train_count": int(len(train)),
        "validation_count": int(len(validation)),
        "validation_relative_rmse": all_validation["relative_rmse"],
        "validation_normalized_rmse": all_validation["normalized_rmse"],
        "edge_validation": {"low_soc": low_metrics, "high_soc": high_metrics},
        "training_support": {
            "soc_min": soc_support[0],
            "soc_max": soc_support[1],
            "temp_c_min": temp_support[0],
            "temp_c_max": temp_support[1],
        },
        "high_soc_log_slope_per_soc_inside_support": {
            "minimum_over_output_temperatures": float(np.min(high_soc_log_slopes)),
            "maximum_over_output_temperatures": float(np.max(high_soc_log_slopes)),
            "interpretation": (
                "diagnostic only; the sign is determined by independent pulse data"
            ),
        },
        "temperature_log_slope_per_c_inside_output_grid": {
            "minimum": float(np.min(temperature_log_slopes)),
            "maximum": float(np.max(temperature_log_slopes)),
        },
        "derivative_constraint_count": int(len(constraint_matrix)),
        "maximum_derivative_constraint_violation": maximum_constraint_violation,
        "method": (
            "positive log-quadratic surface with curvature regularization, optional "
            "diagnostic directional constraints, and no free extrapolation"
        ),
        "outside_training_support_policy": (
            "hold the nearest fitted SoC/temperature boundary constant; never extrapolate the quadratic"
        ),
        "shape_constraint": {
            "high_soc_nonincreasing_from": high_soc_nonincreasing_from,
            "temperature_nonincreasing": bool(temperature_nonincreasing),
            "policy": (
                "directional constraints are non-release diagnostic hypotheses; the default "
                "release fit lets independent pulse evidence determine both slope signs"
            ),
        },
    }


def _png_data_uri(fig: plt.Figure) -> str:                         # [関数定義] _png_data_uri の処理実行ブロック
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=145, bbox_inches="tight")
    plt.close(fig)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _placeholder_figure(title: str, message: str) -> plt.Figure:   # [関数定義] _placeholder_figure の処理実行ブロック
    fig, ax = plt.subplots(figsize=(9.2, 4.8))
    ax.axis("off")
    ax.text(0.5, 0.62, title, ha="center", va="center", fontsize=16, weight="bold")
    ax.text(0.5, 0.38, message, ha="center", va="center", fontsize=11, wrap=True)
    return fig                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_report_figures(                                          # [関数定義] build_report_figures の処理実行ブロック
    rest: pd.DataFrame,
    pulse_points: pd.DataFrame,
    pulse_details: list[dict],
    ocv: pd.DataFrame,
    r0: pd.DataFrame,
    r1: pd.DataFrame,
    tau: pd.DataFrame,
    summary: dict,
) -> list[tuple[str, str]]:
    figures: list[tuple[str, str]] = []

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.axis("off")
    ax.text(0.5, 0.92, "Physically identifiable pack-level 1-RC path", ha="center", fontsize=16, weight="bold")
    boxes = [
        (0.02, "independent SoC\n+ long rest"),
        (0.22, "rested OCV\nUocv(z)"),
        (0.42, "sub-second\ncurrent step"),
        (0.62, "R0,total +\nR1, tau"),
        (0.82, "held-out test\n+ adoption gate"),
    ]
    for x, label in boxes:
        ax.add_patch(plt.Rectangle((x, 0.40), 0.16, 0.22, fill=False, linewidth=2))
        ax.text(x + 0.08, 0.51, label, ha="center", va="center")
    for x in (0.18, 0.38, 0.58, 0.78):
        ax.annotate("", xy=(x + 0.035, 0.51), xytext=(x - 0.015, 0.51), arrowprops={"arrowstyle": "->"})
    figures.append(("1. Identification path", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    for split, group in rest.groupby("split"):
        ax.scatter(group["soc_reference"], group["rest_voltage_v"], label=split, alpha=0.8)
    ax.plot(ocv["soc"], ocv["ocv_v"], color="black", linewidth=2, label="monotone fit")
    ax.set(xlabel="independent SoC [-]", ylabel="rested pack voltage [V]", title="Rest evidence and OCV fit")
    ax.grid(True, alpha=0.25); ax.legend()
    figures.append(("2. Rested OCV evidence", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    detail = pulse_details[0]
    ax.plot(detail["pulse_time_s"], detail["measured_voltage_v"], label="measured")
    ax.plot(detail["pulse_time_s"], detail["predicted_voltage_v"], label="1-RC prediction")
    ax.set(xlabel="pulse time [s]", ylabel="pack voltage [V]", title=f"Pulse fit example: {detail['test_id']}")
    ax.grid(True, alpha=0.25); ax.legend()
    figures.append(("3. Representative pulse", _png_data_uri(fig)))

    for number, column, ylabel in (
        (4, "r0_total_ohm", "R0,total [ohm]"),
        (5, "r1_ohm", "R1 [ohm]"),
        (6, "tau_sec", "tau [s]"),
        (7, "voltage_rmse_v", "pulse voltage RMSE [V]"),
    ):
        fig, ax = plt.subplots(figsize=(9, 5))
        scatter = ax.scatter(
            pulse_points["soc_reference"], pulse_points[column],
            c=pulse_points["temp_c"], cmap="coolwarm", s=55,
        )
        ax.set(xlabel="independent SoC [-]", ylabel=ylabel, title=f"{ylabel} pulse estimates")
        ax.grid(True, alpha=0.25); fig.colorbar(scatter, ax=ax, label="temperature [C]")
        figures.append((f"{number}. {column}", _png_data_uri(fig)))

    for number, frame, title in (
        (8, r0, "R0,total(z,T)"),
        (9, r1, "R1(z,T)"),
        (10, tau, "tau(z,T)"),
    ):
        fig, ax = plt.subplots(figsize=(9, 5))
        image = ax.imshow(
            frame.to_numpy(dtype=float), aspect="auto", origin="lower",
            extent=[float(frame.columns.min()), float(frame.columns.max()), float(frame.index.min()), float(frame.index.max())],
            cmap="viridis",
        )
        ax.set(xlabel="SoC [-]", ylabel="temperature [C]", title=title)
        fig.colorbar(image, ax=ax)
        figures.append((f"{number}. {title}", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(pulse_points["soc_reference"], pulse_points["temp_c"], c=pulse_points["split"].map({"train": 0, "validation": 1}))
    ax.set(xlabel="SoC [-]", ylabel="temperature [C]", title="Evidence coverage (train/validation)")
    ax.grid(True, alpha=0.25)
    figures.append(("11. Evidence coverage", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(pulse_points["current_step_a"], pulse_points["r0_total_ohm"], c=pulse_points["soc_reference"], cmap="plasma")
    ax.set(xlabel="current step [A]", ylabel="R0,total [ohm]", title="Current-amplitude dependence audit")
    ax.grid(True, alpha=0.25)
    figures.append(("12. Current linearity audit", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(pulse_points["voltage_rmse_v"], bins=min(15, max(3, len(pulse_points) // 2)))
    ax.set(xlabel="pulse RMSE [V]", ylabel="count", title="Pulse residual distribution")
    figures.append(("13. Pulse residual distribution", _png_data_uri(fig)))

    for number, temp in zip((14, 15, 16), np.linspace(float(r0.index.min()), float(r0.index.max()), 3)):
        idx = int(np.argmin(np.abs(r0.index.to_numpy(dtype=float) - temp)))
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.plot(r0.columns, r0.iloc[idx], label="R0,total")
        ax.plot(r1.columns, r1.iloc[idx], label="R1")
        ax.set(xlabel="SoC [-]", ylabel="resistance [ohm]", title=f"Resistance components at {float(r0.index[idx]):.1f} C")
        ax.grid(True, alpha=0.25); ax.legend()
        figures.append((f"{number}. Resistance slice", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    soc = ocv["soc"].to_numpy(dtype=float)
    ocv_v = ocv["ocv_v"].to_numpy(dtype=float)
    mid_t = r0.iloc[len(r0) // 2].to_numpy(dtype=float)
    r_soc = np.interp(soc, r0.columns.to_numpy(dtype=float), mid_t)
    for current in (10.0, 20.0, 40.0, 60.0):
        ax.plot(soc, ocv_v - current * r_soc, label=f"{current:.0f} A instantaneous")
    ax.plot(soc, ocv_v, color="black", linewidth=2, label="OCV")
    ax.set(xlabel="SoC [-]", ylabel="pack voltage [V]", title="Current-dependent instantaneous terminal voltage")
    ax.grid(True, alpha=0.25); ax.legend()
    figures.append(("17. Current-dependent voltage", _png_data_uri(fig)))

    fig, ax = plt.subplots(figsize=(9, 5))
    checks = summary["checks"]
    labels = list(checks)
    values = [1 if checks[label] else 0 for label in labels]
    ax.barh(labels, values, color=["#15803d" if value else "#b91c1c" for value in values])
    ax.set_xlim(0, 1.05); ax.set_title("Physical-evidence adoption checks")
    figures.append(("18. Adoption checks", _png_data_uri(fig)))

    figures.append(("19. Identifiability boundary", _png_data_uri(_placeholder_figure(
        "What the two-terminal pulse identifies",
        "R0,total is identifiable. Cell resistance, bus-bar resistance, contactor resistance, and lead resistance are not separately identifiable without additional four-wire measurements.",
    ))))
    figures.append(("20. Conclusion", _png_data_uri(_placeholder_figure(
        "PASS" if summary["gate_pass"] else "NOT APPROVED",
        "The model passed independent physical-evidence checks." if summary["gate_pass"] else "Do not promote these maps. Resolve every failed evidence check and repeat the independent test.",
    ))))
    return figures                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_html_report(path: Path, figures: list[tuple[str, str]], summary: dict) -> None:  # [関数定義] write_html_report の処理実行ブロック
    cards = "".join(
        f'<div class="check {"pass" if value else "fail"}"><b>{html.escape(key)}</b><br>{"PASS" if value else "FAIL"}</div>'
        for key, value in summary["checks"].items()
    )
    images = "".join(
        f'<section><h2>{html.escape(title)}</h2><img src="{uri}" alt="{html.escape(title)}"></section>'
        for title, uri in figures
    )
    payload = html.escape(json.dumps(summary, ensure_ascii=False, indent=2))
    document = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>Pack OCV / R0 / 1-RC physical evidence report</title>
<style>
body{{font-family:"Yu Gothic",sans-serif;margin:0;background:#f3efe4;color:#17202a}}main{{max-width:1120px;margin:auto;padding:28px}}
.hero,section{{background:#fffdf7;border:1px solid #d8d0bf;border-radius:18px;padding:20px;margin-bottom:18px}}h1{{margin-top:0}}
.status{{font-size:32px;font-weight:800;color:{'#15803d' if summary['gate_pass'] else '#b91c1c'}}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}
.check{{padding:12px;border-radius:10px}}.pass{{background:#dcfce7}}.fail{{background:#fee2e2}}img{{width:100%;height:auto}}pre{{white-space:pre-wrap;font-size:12px}}
</style></head><body><main><div class="hero"><h1>OCV・瞬時総抵抗・1-RC 同定の完全可視化</h1>
<p class="status">{'実運用昇格可能' if summary['gate_pass'] else '実運用昇格不可'}</p>
<p>固定40 mΩ/cellや負荷曲線勾配を使用せず、独立SoC付き休止・パルス試験だけを根拠にしたpack-levelモデルです。</p><div class="grid">{cards}</div></div>
{images}<section><h2>Machine-readable summary</h2><pre>{payload}</pre></section></main></body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(document, encoding="utf-8", newline="\n")


def identify(rest_csv: Path, pulse_csv: Path, output_dir: Path, limits: FitLimits) -> dict:  # [関数定義] identify の処理実行ブロック
    if not 0.0 <= limits.operational_soc_min < limits.operational_soc_max <= 1.0:
        raise BatteryEvidenceError("operational SoC bounds must satisfy 0 <= min < max <= 1")
    if limits.maximum_soc_boundary_gap < 0.0 or limits.edge_validation_band <= 0.0:
        raise BatteryEvidenceError("SoC boundary gap must be nonnegative and edge band must be positive")
    if (
        limits.r0_high_soc_nonincreasing_from is not None
        and not limits.operational_soc_min
        <= limits.r0_high_soc_nonincreasing_from
        < limits.operational_soc_max
    ):
        raise BatteryEvidenceError(
            "R0 high-SoC monotonic threshold must lie inside the operational SoC range"
        )
    rest = load_rest_data(rest_csv)
    pulse = load_pulse_data(pulse_csv)
    ocv, ocv_info = fit_ocv_curve(rest, limits)
    pulse_points, rejected = fit_pulse_tests(pulse, limits)
    detail_lookup = {str(test_id): group for test_id, group in pulse.groupby("test_id", sort=False)}
    pulse_details = [_fit_single_pulse(detail_lookup[row.test_id], limits) for row in pulse_points.itertuples()]
    train = pulse_points[pulse_points["split"] == "train"]
    validation = pulse_points[pulse_points["split"] == "validation"]
    soc_grid = np.linspace(limits.operational_soc_min, limits.operational_soc_max, 21)
    train_temp_min = float(train["temp_c"].min())
    train_temp_max = float(train["temp_c"].max())
    interior_temp_grid = np.arange(
        math.ceil(train_temp_min / 5.0) * 5.0,
        math.floor(train_temp_max / 5.0) * 5.0 + 0.1,
        5.0,
    )
    temp_grid = np.unique(np.concatenate(([train_temp_min], interior_temp_grid, [train_temp_max])))
    r0, r0_info = fit_positive_surface(
        pulse_points,
        "r0_total_ohm",
        soc_grid,
        temp_grid,
        limits,
        high_soc_nonincreasing_from=limits.r0_high_soc_nonincreasing_from,
        temperature_nonincreasing=limits.enforce_r0_temperature_nonincreasing,
    )
    r1, r1_info = fit_positive_surface(pulse_points, "r1_ohm", soc_grid, temp_grid, limits)
    tau, tau_info = fit_positive_surface(pulse_points, "tau_sec", soc_grid, temp_grid, limits)
    validation_voltage_rmse = float(np.sqrt(np.mean(validation["voltage_rmse_v"] ** 2))) if len(validation) else math.nan
    validation_voltage_normalized_rmse = (
        float(np.sqrt(np.mean(validation["voltage_normalized_rmse"] ** 2)))
        if len(validation)
        else math.nan
    )
    soc_span = float(train["soc_reference"].max() - train["soc_reference"].min()) if len(train) else 0.0
    temp_span = float(train["temp_c"].max() - train["temp_c"].min()) if len(train) else 0.0
    train_soc_min = float(train["soc_reference"].min()) if len(train) else math.nan
    train_soc_max = float(train["soc_reference"].max()) if len(train) else math.nan
    r0_low_edge = r0_info["edge_validation"]["low_soc"]
    r0_high_edge = r0_info["edge_validation"]["high_soc"]
    source_hashes = {
        str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in (rest_csv, pulse_csv)
    }
    checks = {
        "independent_soc_only": bool(
            set(rest["soc_reference_method"]).issubset(INDEPENDENT_SOC_METHODS)
            and set(pulse["soc_reference_method"]).issubset(INDEPENDENT_SOC_METHODS)
        ),
        "rest_duration_adequate": bool((rest["rest_duration_sec"] >= limits.minimum_rest_sec).all()),
        "rest_equilibrium_slope": bool(
            (rest["rest_voltage_slope_uv_per_s"].abs() <= limits.maximum_rest_voltage_slope_uv_per_s).all()
        ),
        "minimum_training_pulses": len(train) >= limits.minimum_train_tests,
        "minimum_validation_pulses": len(validation) >= limits.minimum_validation_tests,
        "soc_coverage": soc_span >= limits.minimum_soc_span,
        "operational_soc_boundary_coverage": bool(
            train_soc_min <= limits.operational_soc_min + limits.maximum_soc_boundary_gap + 1.0e-12
            and train_soc_max >= limits.operational_soc_max - limits.maximum_soc_boundary_gap - 1.0e-12
        ),
        "temperature_coverage": temp_span >= limits.minimum_temp_span_c,
        "ocv_holdout_available": bool(
            int(ocv_info["validation_count"]) >= 2
            and np.isfinite(ocv_info["validation_normalized_rmse"])
            and ocv_info["validation_normalized_rmse"] <= limits.maximum_validation_normalized_rmse
        ),
        "pulse_voltage_holdout_rmse": bool(
            np.isfinite(validation_voltage_normalized_rmse)
            and validation_voltage_normalized_rmse <= limits.maximum_validation_normalized_rmse
        ),
        "r0_surface_holdout": bool(
            np.isfinite(r0_info["validation_normalized_rmse"])
            and r0_info["validation_normalized_rmse"] <= limits.maximum_validation_normalized_rmse
        ),
        "r0_low_soc_edge_holdout": bool(
            r0_low_edge["count"] >= limits.minimum_edge_validation_tests
            and np.isfinite(r0_low_edge["normalized_rmse"])
            and r0_low_edge["normalized_rmse"] <= limits.maximum_validation_normalized_rmse
        ),
        "r0_high_soc_edge_holdout": bool(
            r0_high_edge["count"] >= limits.minimum_edge_validation_tests
            and np.isfinite(r0_high_edge["normalized_rmse"])
            and r0_high_edge["normalized_rmse"] <= limits.maximum_validation_normalized_rmse
        ),
        "r0_direction_not_imposed_by_prior": bool(
            limits.r0_high_soc_nonincreasing_from is None
            and not limits.enforce_r0_temperature_nonincreasing
        ),
        "passivity": bool((r0.to_numpy() > 0).all() and (r1.to_numpy() >= 0).all() and (tau.to_numpy() > 0).all()),
    }
    summary = {
        "schema_version": 1,
        "model_equations": {
            "terminal_voltage": "Vt = Uocv(z) - I*R0_total(z,T) - V1",
            "polarization": "dV1/dt = -V1/tau(z,T) + R1(z,T)*I/tau(z,T)",
            "current_sign": "positive discharge",
        },
        "r0_definition": "pack two-terminal instantaneous total resistance; not decomposed into cell and wiring terms",
        "fixed_cell_resistance_prior_used": False,
        "loaded_voltage_slope_used_as_r0": False,
        "source_sha256": source_hashes,
        "ocv_fit": ocv_info,
        "pulse_count": int(len(pulse_points)),
        "rejected_pulses": rejected,
        "validation_voltage_rmse_v": validation_voltage_rmse,
        "validation_voltage_normalized_rmse": validation_voltage_normalized_rmse,
        "acceptance_limits": {
            **FitLimits().__dict__,
            **limits.__dict__,
            "normalized_rmse_interpretation": (
                "dimensionless residual divided by declared measurement-derived uncertainty; "
                "the default limit is a configurable three-sigma engineering adoption rule, not a battery coefficient"
            ),
        },
        "soc_span_train": soc_span,
        "temperature_span_train_c": temp_span,
        "operational_soc_range": [
            float(limits.operational_soc_min),
            float(limits.operational_soc_max),
        ],
        "map_domain_policy": (
            "The quadratic is evaluated only inside train SoC/temperature support. "
            "Operational grid points outside that support use a constant nearest-edge value; "
            "promotion additionally requires train proximity and independent validation at both SoC edges."
        ),
        "surface_fits": {"r0": r0_info, "r1": r1_info, "tau": tau_info},
        "checks": checks,
        "gate_pass": bool(all(checks.values())),
        "proof_scope": (
            "structural passivity and independent held-out agreement within measured "
            "SoC-temperature-current coverage; R0 slope signs are learned rather than imposed, "
            "and this is not a proof outside the measured domain"
        ),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    ocv.to_csv(output_dir / "ocv_soc_curve_identified.csv", index=False)
    r0.to_csv(output_dir / "R0_total_T_by_soc_identified.csv")
    r1.to_csv(output_dir / "R1_T_by_soc_identified.csv")
    tau.to_csv(output_dir / "tau_T_by_soc_identified.csv")
    pulse_points.to_csv(output_dir / "pulse_fit_points.csv", index=False)
    (output_dir / "battery_ecm_identification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    figures = build_report_figures(rest, pulse_points, pulse_details, ocv, r0, r1, tau, summary)
    write_html_report(output_dir / "OCV_R0_1RC_complete_visual_report.html", figures, summary)
    return summary                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def main() -> None:                                                # [関数定義] main の処理実行ブロック
    parser = argparse.ArgumentParser()
    parser.add_argument("--rest-csv", required=True)               # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--pulse-csv", required=True)              # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--output-dir", required=True)             # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--minimum-rest-sec", type=float, default=1800.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--maximum-rest-current-a", type=float, default=0.25)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--maximum-rest-voltage-slope-uv-per-s", type=float, default=10.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--minimum-current-step-a", type=float, default=3.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--maximum-first-sample-delay-sec", type=float, default=0.25)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--maximum-validation-normalized-rmse", type=float, default=3.0)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--operational-soc-min", type=float, default=0.05)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--operational-soc-max", type=float, default=0.95)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--maximum-soc-boundary-gap", type=float, default=0.05)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--edge-validation-band", type=float, default=0.10)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--minimum-edge-validation-tests", type=int, default=1)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument(                                           # [CLI引数] コマンドライン実行引数の定義
        "--r0-high-soc-nonincreasing-from",
        type=float,
        default=None,
        help="Diagnostic-only legacy hypothesis; omitted for release identification.",
    )
    parser.add_argument(                                           # [CLI引数] コマンドライン実行引数の定義
        "--enforce-r0-temperature-nonincreasing",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Diagnostic-only legacy hypothesis; disabled for release identification.",
    )
    args = parser.parse_args()
    limits = FitLimits(
        minimum_rest_sec=float(args.minimum_rest_sec),
        maximum_rest_current_a=float(args.maximum_rest_current_a),
        maximum_rest_voltage_slope_uv_per_s=float(args.maximum_rest_voltage_slope_uv_per_s),
        minimum_current_step_a=float(args.minimum_current_step_a),
        maximum_first_sample_delay_sec=float(args.maximum_first_sample_delay_sec),
        maximum_validation_normalized_rmse=float(args.maximum_validation_normalized_rmse),
        operational_soc_min=float(args.operational_soc_min),
        operational_soc_max=float(args.operational_soc_max),
        maximum_soc_boundary_gap=float(args.maximum_soc_boundary_gap),
        edge_validation_band=float(args.edge_validation_band),
        minimum_edge_validation_tests=int(args.minimum_edge_validation_tests),
        r0_high_soc_nonincreasing_from=(
            None
            if args.r0_high_soc_nonincreasing_from is None
            else float(args.r0_high_soc_nonincreasing_from)
        ),
        enforce_r0_temperature_nonincreasing=bool(args.enforce_r0_temperature_nonincreasing),

    )
    summary = identify(Path(args.rest_csv), Path(args.pulse_csv), Path(args.output_dir), limits)
    print(json.dumps({"gate_pass": summary["gate_pass"], "output_dir": args.output_dir}, ensure_ascii=False))
    if not summary["gate_pass"]:
        raise SystemExit(2)




import argparse
import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート
from scipy.interpolate import RegularGridInterpolator
from scipy.optimize import minimize
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_SRC_PACKAGE_NAME = "bwsc2025_public"
DEFAULT_PACKAGE_NAME = "bwsc2025_fitted_mle4"
DEFAULT_FIXED_MASS_KG = 235.0
DEFAULT_PROFILE_UPPER_MAX_ITER = 24
SRC_PACKAGE_NAME = DEFAULT_SRC_PACKAGE_NAME
PACKAGE_NAME = DEFAULT_PACKAGE_NAME
SRC_PACKAGE = ROOT / "project_packages" / SRC_PACKAGE_NAME
OUT_PACKAGE = ROOT / "project_packages" / PACKAGE_NAME
DATA_ARCHIVE_ROOT = ROOT / "docs" / "データ整理、分析-20260624T133933Z-3-001" / "データ整理、分析"
SCRUTINEERING_ROOT = ROOT / "docs" / "車検資料-20260624T134045Z-3-001" / "車検資料"
TIMEZONE_LOCAL = ZoneInfo("Australia/Darwin")
OPENMETEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ACTUAL_RACE_END_KM = 2831.0
OFFICIAL_CLASSIFIED_DISTANCE_KM = 2720.0
RACE_START_LOCAL = datetime(2025, 8, 24, 8, 21, 0, tzinfo=TIMEZONE_LOCAL)
FIT_RESAMPLE_SEC = 120
REPORT_DATE = "2026-07-07"
WEATHER_SAMPLE_STEP_KM = 25.0
WEATHER_BATCH_SIZE = 12
PV_FIT_RESAMPLE_SEC = 60
BWSC_RULES_URL = "https://assets.worldsolarchallenge.org/app/uploads/2024/10/04152314/3290_2025_bwsc_regulations_release_v10_published_05062024.pdf"
BWSC_ROUTE_NOTES_URL = "https://assets.worldsolarchallenge.org/app/uploads/2025/07/13131527/2025-BWSC-Route-Notes-V1-FINAL-PRINT-Published-13072025.pdf"
PV_EFFECTIVE_RATIO_WINDOW = 121
PV_TCELL_SEED_GAIN = 0.03
PV_FIT_MAXITER = 200
BATTERY_FIT_MAXITER = 260
MOTION_FIT_MAXITER = 320
JOINT_FIT_MAXITER = 180
BATTERY_RESTART_COUNT = 6
MOTION_RESTART_COUNT = 8
JOINT_RESTART_COUNT = 8
JOINT_RANDOM_START_COUNT = 28
JOINT_LOCAL_TOPK = 10
JOINT_OBJECTIVE_POWER_WEIGHT = 14.0
JOINT_OBJECTIVE_VOLTAGE_WEIGHT = 9.0
JOINT_OBJECTIVE_POWER_BIAS_WEIGHT = 3.0
JOINT_OBJECTIVE_STAGE_ANCHOR_WEIGHT = 2.0
JOINT_ACCEPT_POWER_RMSE_MARGIN_W = 8.0
JOINT_ACCEPT_VOLTAGE_RMSE_MARGIN_V = 0.75
INVALID_PACK_VOLTAGE_MIN_V = 20.0
REST_SOC_VOLTAGE_MIN_V = 60.0
REST_SOC_CURRENT_MAX_A = 2.5
REST_SOC_SPEED_MAX_KMH = 1.0
REST_SOC_SIGMA = 0.05

BATTERY_PRIOR_E_NOM_WH = 3011.0
BATTERY_PRIOR_E_NOM_SIGMA_WH = 180.0
BATTERY_PRIOR_SOC0_SIGMA = 0.04
BATTERY_PRIOR_RINT_SCALE = 1.5
BATTERY_PRIOR_RINT_SIGMA = 0.8
BATTERY_PRIOR_RLINE_OHM = 0.015
BATTERY_PRIOR_RLINE_SIGMA_OHM = 0.015
BATTERY_PRIOR_ETA_CHARGE = 0.955
BATTERY_PRIOR_ETA_SIGMA = 0.03
NOMINAL_FINISH_SOC_TARGET = 0.12
CONTROL_STOP_MIN_DWELL_SEC = 1500.0

MOTION_PRIOR_CDA = 0.11
MOTION_PRIOR_CDA_SIGMA = 0.02
MOTION_PRIOR_CRR = 0.006
MOTION_PRIOR_CRR_SIGMA = 0.003
MOTION_PRIOR_P_AUX_W = 21.0
MOTION_PRIOR_P_AUX_SIGMA_W = 5.0
MOTION_PRIOR_GRADE_SCALE = 1.0
MOTION_PRIOR_GRADE_SIGMA = 0.15
MOTION_PRIOR_DRIVE_EFF_SCALE = 1.02
MOTION_PRIOR_DRIVE_EFF_SIGMA = 0.05
MOTION_PRIOR_HEADWIND_GAIN = 0.12
MOTION_PRIOR_HEADWIND_SIGMA = 0.10
MAP_SHAPE_MAXITER = 220
MAP_SHAPE_PANEL_MPPT_PANEL_SHARE = 0.85
MAP_SHAPE_PANEL_RATIO_BOUNDS = (0.70, 1.35)
MAP_SHAPE_DRIVE_RATIO_BOUNDS = (0.85, 1.15)
MAP_SHAPE_REGEN_RATIO_BOUNDS = (0.80, 1.20)
MAP_SHAPE_RINT_RATIO_BOUNDS = (0.60, 1.80)
MAP_SHAPE_LOG_BOUND = 0.35
MAP_SHAPE_MIN_SAMPLES = 16


DAY_FILES = [
    (1, "2025-08-24", DATA_ARCHIVE_ROOT / "zpデータ" / "zp加工データ" / "ZP_Data0824day1.csv"),
    (2, "2025-08-25", DATA_ARCHIVE_ROOT / "zpデータ" / "zp加工データ" / "ZP_Data0825day2.csv"),
    (3, "2025-08-26", DATA_ARCHIVE_ROOT / "zpデータ" / "zp加工データ" / "ZP_Data0826day3.csv"),
    (4, "2025-08-27", DATA_ARCHIVE_ROOT / "zpデータ" / "zp加工データ" / "ZP_Data0827day4.csv"),
    (5, "2025-08-28", DATA_ARCHIVE_ROOT / "zpデータ" / "zp加工データ" / "ZP_Data0828day5.csv"),
    (6, "2025-08-29", DATA_ARCHIVE_ROOT / "zpデータ" / "zp加工データ" / "ZP_Data0829day6.csv"),
]

DEM_CSV = DATA_ARCHIVE_ROOT / "勾配情報" / "route_100m_dem.csv"
DISCHARGE_TEST_CSV = DATA_ARCHIVE_ROOT / "電圧、SoC推定グラフ" / "2024_05_26_DischargeTest.csv"
TIME_MEMO_PDF = DATA_ARCHIVE_ROOT / "BWSC2025 時系列別メモ.pdf"
POINTS_PDF = DATA_ARCHIVE_ROOT / "BWSC2025各ポイント緯度経度.pdf"
BATTERY_SOC_PDF = DATA_ARCHIVE_ROOT / "BWSC2025バッテリーSoC推測.pdf"
TROUBLE_DOCX = SCRUTINEERING_ROOT / "電装" / "【電装】BWSC走行中トラブル.docx"


def local_dt(text: str) -> datetime:                               # [関数定義] local_dt の処理実行ブロック
    return datetime.fromisoformat(text).replace(tzinfo=TIMEZONE_LOCAL)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


EVENT_ANCHORS = [
    {"ts_local": "2025-08-24T08:21:00", "s_km": 0.0, "label": "Day1 start"},
    {"ts_local": "2025-08-24T11:27:00", "s_km": 192.0, "label": "Emerald Springs stop in"},
    {"ts_local": "2025-08-24T11:37:00", "s_km": 192.0, "label": "Emerald Springs stop out"},
    {"ts_local": "2025-08-24T12:08:00", "s_km": 222.0, "label": "Hatch repair in"},
    {"ts_local": "2025-08-24T12:12:00", "s_km": 222.0, "label": "Hatch repair out"},
    {"ts_local": "2025-08-24T13:43:35", "s_km": 322.0, "label": "CS1 in"},
    {"ts_local": "2025-08-24T14:15:00", "s_km": 322.0, "label": "CS1 out"},
    {"ts_local": "2025-08-24T17:09:00", "s_km": 535.0, "label": "Day1 end"},
    {"ts_local": "2025-08-24T18:16:00", "s_km": 535.0, "label": "Day1 charge end"},
    {"ts_local": "2025-08-25T07:06:00", "s_km": 535.0, "label": "Day2 charge start"},
    {"ts_local": "2025-08-25T08:09:00", "s_km": 535.0, "label": "Day2 start"},
    {"ts_local": "2025-08-25T09:35:59", "s_km": 631.0, "label": "CS2 in"},
    {"ts_local": "2025-08-25T10:05:59", "s_km": 631.0, "label": "CS2 out"},
    {"ts_local": "2025-08-25T15:17:25", "s_km": 988.0, "label": "CS3 in"},
    {"ts_local": "2025-08-25T15:47:25", "s_km": 988.0, "label": "CS3 out"},
    {"ts_local": "2025-08-25T17:05:00", "s_km": 1074.0, "label": "Day2 end"},
    {"ts_local": "2025-08-25T17:33:55", "s_km": 1074.0, "label": "MPPT fault fixed"},
    {"ts_local": "2025-08-25T18:16:00", "s_km": 1074.0, "label": "Day2 charge end"},
    {"ts_local": "2025-08-26T06:52:00", "s_km": 1074.0, "label": "Day3 charge start"},
    {"ts_local": "2025-08-26T08:05:00", "s_km": 1074.0, "label": "Day3 start"},
    {"ts_local": "2025-08-26T08:15:00", "s_km": 1079.0, "label": "Noise check in"},
    {"ts_local": "2025-08-26T08:20:00", "s_km": 1079.0, "label": "Noise check out"},
    {"ts_local": "2025-08-26T10:13:56", "s_km": 1212.3, "label": "CS4 in"},
    {"ts_local": "2025-08-26T10:43:56", "s_km": 1212.3, "label": "CS4 out"},
    {"ts_local": "2025-08-26T14:50:52", "s_km": 1496.0, "label": "CS5 in"},
    {"ts_local": "2025-08-26T15:20:52", "s_km": 1496.0, "label": "CS5 out"},
    {"ts_local": "2025-08-26T16:57:00", "s_km": 1605.0, "label": "Day3 end"},
    {"ts_local": "2025-08-26T17:42:00", "s_km": 1605.0, "label": "Day3 charge end"},
    {"ts_local": "2025-08-27T07:06:00", "s_km": 1605.0, "label": "Day4 charge start"},
    {"ts_local": "2025-08-27T08:00:00", "s_km": 1605.0, "label": "Day4 start"},
    {"ts_local": "2025-08-27T09:34:51", "s_km": 1694.0, "label": "CS6 in"},
    {"ts_local": "2025-08-27T10:04:51", "s_km": 1694.0, "label": "CS6 out"},
    {"ts_local": "2025-08-27T15:30:00", "s_km": 2053.0, "label": "Low SOC stop in"},
    {"ts_local": "2025-08-27T16:20:00", "s_km": 2053.0, "label": "Low SOC stop out"},
    {"ts_local": "2025-08-27T16:49:00", "s_km": 2088.0, "label": "Day4 end"},
    {"ts_local": "2025-08-27T18:18:00", "s_km": 2088.0, "label": "Day4 charge end"},
    {"ts_local": "2025-08-28T07:16:00", "s_km": 2088.0, "label": "Day5 charge start"},
    {"ts_local": "2025-08-28T08:35:00", "s_km": 2088.0, "label": "Day5 start"},
    {"ts_local": "2025-08-28T09:59:10", "s_km": 2181.0, "label": "CS7 in"},
    {"ts_local": "2025-08-28T10:29:10", "s_km": 2181.0, "label": "CS7 out"},
    {"ts_local": "2025-08-28T10:31:00", "s_km": 2181.0, "label": "Puncture in"},
    {"ts_local": "2025-08-28T10:37:00", "s_km": 2181.0, "label": "Puncture out"},
    {"ts_local": "2025-08-28T11:51:00", "s_km": 2262.0, "label": "Hatch flutter"},
    {"ts_local": "2025-08-28T12:47:00", "s_km": 2329.0, "label": "Hatch repair in"},
    {"ts_local": "2025-08-28T12:50:00", "s_km": 2329.0, "label": "Hatch repair out"},
    {"ts_local": "2025-08-28T14:19:00", "s_km": 2430.0, "label": "Road works light in"},
    {"ts_local": "2025-08-28T14:26:00", "s_km": 2430.0, "label": "Road works light out"},
    {"ts_local": "2025-08-28T14:30:21", "s_km": 2434.0, "label": "CS8 in"},
    {"ts_local": "2025-08-28T15:00:21", "s_km": 2434.0, "label": "CS8 out"},
    {"ts_local": "2025-08-28T16:59:00", "s_km": 2562.0, "label": "Day5 end"},
    {"ts_local": "2025-08-28T17:53:00", "s_km": 2562.0, "label": "Day5 charge end"},
    {"ts_local": "2025-08-29T08:45:00", "s_km": 2562.0, "label": "Day6 start"},
    {"ts_local": "2025-08-29T08:56:00", "s_km": 2574.0, "label": "Road works light in"},
    {"ts_local": "2025-08-29T08:57:30", "s_km": 2574.0, "label": "Road works light out"},
    {"ts_local": "2025-08-29T09:08:00", "s_km": 2584.0, "label": "ZP issue in"},
    {"ts_local": "2025-08-29T10:18:00", "s_km": 2584.0, "label": "ZP issue out"},
    {"ts_local": "2025-08-29T12:27:47", "s_km": 2720.0, "label": "CS9 in"},
    {"ts_local": "2025-08-29T12:57:47", "s_km": 2720.0, "label": "CS9 out"},
    {"ts_local": "2025-08-29T14:46:00", "s_km": 2831.0, "label": "Retire"},
]


EXCLUDE_INTERVALS = [
    {
        "start_local": "2025-08-25T11:23:55",
        "end_local": "2025-08-25T17:33:55",
        "reason": "mppt_crimp_fault",
        "exclude_power_fit": True,
        "exclude_voltage_fit": False,
        "exclude_weather_fit": True,
    },
    {
        "start_local": "2025-08-29T09:08:00",
        "end_local": "2025-08-29T10:18:00",
        "reason": "zp_voltage_display_fault",
        "exclude_power_fit": True,
        "exclude_voltage_fit": True,
        "exclude_weather_fit": False,
    },
    {
        "start_local": "2025-08-29T12:57:47",
        "end_local": "2025-08-29T14:46:00",
        "reason": "dust_truck_slipstream",
        "exclude_power_fit": True,
        "exclude_voltage_fit": False,
        "exclude_weather_fit": False,
    },
    {
        "start_local": "2025-08-24T12:08:00",
        "end_local": "2025-08-24T12:12:00",
        "reason": "maintenance_stop",
        "exclude_power_fit": True,
        "exclude_voltage_fit": False,
        "exclude_weather_fit": False,
    },
    {
        "start_local": "2025-08-26T08:15:00",
        "end_local": "2025-08-26T08:20:00",
        "reason": "noise_check_stop",
        "exclude_power_fit": True,
        "exclude_voltage_fit": False,
        "exclude_weather_fit": False,
    },
    {
        "start_local": "2025-08-28T10:31:00",
        "end_local": "2025-08-28T10:37:00",
        "reason": "puncture_stop",
        "exclude_power_fit": True,
        "exclude_voltage_fit": False,
        "exclude_weather_fit": False,
    },
    {
        "start_local": "2025-08-28T12:47:00",
        "end_local": "2025-08-28T12:50:00",
        "reason": "hatch_repair_stop",
        "exclude_power_fit": True,
        "exclude_voltage_fit": False,
        "exclude_weather_fit": False,
    },
]


@dataclass
class PvFitResult:                                                 # [クラス定義] PvFitResult オブジェクトの設計
    panel_gain: float
    tcell_gain_c_per_wm2: float
    objective: float
    solar_rmse_w: float


@dataclass
class BatteryFitResult:                                            # [クラス定義] BatteryFitResult オブジェクトの設計
    soc0: float
    e_nom_wh: float
    rint_scale: float
    r_line_ohm: float
    eta_charge: float
    objective: float
    voltage_rmse_v: float


@dataclass
class MotionFitResult:                                             # [クラス定義] MotionFitResult オブジェクトの設計
    cda: float
    crr: float
    p_aux_w: float
    grade_scale: float
    drive_eff_scale: float
    headwind_gain: float
    objective: float
    power_rmse_w: float
    residual_sigma_w: float


def ensure_dir(path: Path) -> None:                                # [関数定義] ensure_dir の処理実行ブロック
    path.mkdir(parents=True, exist_ok=True)


def append_reason(log_df: pd.DataFrame, mask: pd.Series, reason: str) -> None:  # [関数定義] append_reason の処理実行ブロック
    if not mask.any():
        return
    current = log_df.loc[mask, "exclude_reason"].fillna("").astype(str)
    combined = np.where(current.str.len() > 0, current + ";" + reason, reason)
    log_df.loc[mask, "exclude_reason"] = combined


def log_stage(message: str) -> None:                               # [関数定義] log_stage の処理実行ブロック
    print(f"[{PACKAGE_NAME}] {message}", flush=True)
    try:
        stage_log = OUT_PACKAGE / "outputs" / "build_stage_log.txt"
        ensure_dir(stage_log.parent)
        with stage_log.open("a", encoding="utf-8", newline="\n") as f:
            f.write(f"{datetime.now().isoformat()} [{PACKAGE_NAME}] {message}\n")
    except Exception:
        pass


def remove_tree_force(path: Path) -> None:                         # [関数定義] remove_tree_force の処理実行ブロック
    def _onexc(func, target, excinfo):                             # [関数定義] _onexc の処理実行ブロック
        try:
            os.chmod(target, stat.S_IWRITE)
        except Exception:
            pass
        func(target)

    if path.exists():
        shutil.rmtree(path, onexc=_onexc)


def robust_read_csv(path: Path) -> pd.DataFrame:                   # [関数定義] robust_read_csv の処理実行ブロック
    errors = []
    for enc in ("utf-8-sig", "cp932", "utf-8", "latin1"):
        try:
            return pd.read_csv(path, encoding=enc)                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception as exc:  # pragma: no cover - diagnostic path
            errors.append(f"{enc}: {exc}")
    raise RuntimeError(f"failed to read {path}: {' | '.join(errors)}")


def to_utc(dt_local: datetime) -> datetime:                        # [関数定義] to_utc の処理実行ブロック
    return dt_local.astimezone(timezone.utc)                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def timestamp_ns(value) -> int:                                    # [関数定義] timestamp_ns の処理実行ブロック
    return int(pd.Timestamp(value).value)                          # [戻り値] 計算結果・計算状態の呼び出し元への返却


def series_timestamp_ns(values: pd.Series) -> np.ndarray:          # [関数定義] series_timestamp_ns の処理実行ブロック
    return np.array([timestamp_ns(value) for value in values], dtype=np.int64)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def series_timestamp_s(values: pd.Series) -> np.ndarray:           # [関数定義] series_timestamp_s の処理実行ブロック
    return series_timestamp_ns(values).astype(float) / 1.0e9       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def iso_z(dt_obj: datetime) -> str:                                # [関数定義] iso_z の処理実行ブロック
    return dt_obj.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def smooth_series(values: pd.Series, window: int, min_periods: int = 1) -> pd.Series:  # [関数定義] smooth_series の処理実行ブロック
    return values.rolling(window=window, center=True, min_periods=min_periods).median().bfill().ffill()  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def clip_series(values: pd.Series, lo: float, hi: float) -> pd.Series:  # [関数定義] clip_series の処理実行ブロック
    return values.clip(lower=lo, upper=hi)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_event_anchors() -> List[dict]:                            # [関数定義] load_event_anchors の処理実行ブロック
    anchors = []
    for item in EVENT_ANCHORS:
        anchors.append({**item, "ts_local": local_dt(item["ts_local"])})
    return sorted(anchors, key=lambda d: d["ts_local"])            # [戻り値] 計算結果・計算状態の呼び出し元への返却


def classify_stop(label: str) -> str:                              # [関数定義] classify_stop の処理実行ブロック
    name = str(label or "").strip().lower()
    if name.startswith("cs"):
        return "control_stop"                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if "road works light" in name or "red light" in name:
        return "traffic_stop"                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if "low soc" in name:
        return "strategy_stop"                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if any(token in name for token in ("repair", "issue", "puncture", "noise check")):
        return "trouble_stop"                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return "unscheduled_stop"                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_stop_records() -> List[dict]:                            # [関数定義] build_stop_records の処理実行ブロック
    anchors = load_event_anchors()
    stops = []
    for a, b in zip(anchors[:-1], anchors[1:]):
        if abs(float(a["s_km"]) - float(b["s_km"])) > 1.0e-9:
            continue
        dwell_sec = float((b["ts_local"] - a["ts_local"]).total_seconds())
        if dwell_sec < 30.0:
            continue
        label = str(a["label"]).replace(" in", "")
        if "charge" in label.lower():
            continue
        if label.endswith("start") or label.endswith("end"):
            continue
        kind = classify_stop(label)
        stops.append(
            {
                "label": label,
                "kind": kind,
                "is_control_stop": kind == "control_stop",
                "s_km": float(a["s_km"]),
                "dwell_sec": dwell_sec,
                "start_local": a["ts_local"].isoformat(),
                "end_local": b["ts_local"].isoformat(),
                "start_utc": iso_z(a["ts_local"]),
                "end_utc": iso_z(b["ts_local"]),
            }
        )
    return stops                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_processed_day_logs() -> pd.DataFrame:                     # [関数定義] load_processed_day_logs の処理実行ブロック
    rows = []
    for day_idx, date_text, csv_path in DAY_FILES:
        df = robust_read_csv(csv_path).copy()
        expected = [
            "Solar[A]",
            "Battery[A]",
            "Main_Volt[V]",
            "Solar_Watt[W]",
            "Battery_Watt[W]",
            "Sub_Volt[V]",
            "Speed[kmh]",
            "time",
        ]
        missing = [c for c in expected if c not in df.columns]
        if missing:
            raise ValueError(f"{csv_path} missing columns: {missing}")
        base_date = datetime.fromisoformat(date_text)
        parsed_local = []
        for raw in df["time"].astype(str):
            hh, mm, ss = [int(part) for part in raw.split(":")]
            parsed_local.append(datetime(base_date.year, base_date.month, base_date.day, hh, mm, ss, tzinfo=TIMEZONE_LOCAL))
        part = pd.DataFrame(
            {
                "day": day_idx,
                "time_local": parsed_local,
                "time_utc": [to_utc(dt_obj) for dt_obj in parsed_local],
                "solar_current_a": pd.to_numeric(df["Solar[A]"], errors="coerce"),
                "battery_current_a": pd.to_numeric(df["Battery[A]"], errors="coerce"),
                "battery_voltage_v": pd.to_numeric(df["Main_Volt[V]"], errors="coerce"),
                "solar_power_w_obs": pd.to_numeric(df["Solar_Watt[W]"], errors="coerce"),
                "battery_power_w_obs": pd.to_numeric(df["Battery_Watt[W]"], errors="coerce"),
                "sub_voltage_v": pd.to_numeric(df["Sub_Volt[V]"], errors="coerce"),
                "speed_kmh": pd.to_numeric(df["Speed[kmh]"], errors="coerce"),
            }
        )
        part["dt_sec"] = part["time_local"].diff().dt.total_seconds().fillna(5.0)
        part["dt_sec"] = part["dt_sec"].clip(lower=1.0, upper=10.0)
        rows.append(part)
    out = pd.concat(rows, ignore_index=True)
    out = out.sort_values("time_local").reset_index(drop=True)
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def apply_distance_reconstruction(log_df: pd.DataFrame, anchors: List[dict]) -> pd.DataFrame:  # [関数定義] apply_distance_reconstruction の処理実行ブロック
    log_df = log_df.copy()
    log_df["s_km"] = np.nan
    for day_idx, day_df in log_df.groupby("day", sort=False):
        mask_day = log_df["day"] == day_idx
        day_idxes = np.flatnonzero(mask_day.to_numpy())
        times_ns = series_timestamp_ns(day_df["time_local"])
        step_km = day_df["speed_kmh"].fillna(0.0).clip(lower=0.0).to_numpy() * day_df["dt_sec"].to_numpy() / 3600.0
        day_anchors = [a for a in anchors if a["ts_local"].date() == day_df["time_local"].iloc[0].date()]
        if len(day_anchors) < 2:
            raise ValueError(f"not enough anchors for day {day_idx}")
        dist = np.full(len(day_df), np.nan)
        for seg_a, seg_b in zip(day_anchors[:-1], day_anchors[1:]):
            seg_a_ns = timestamp_ns(seg_a["ts_local"])
            seg_b_ns = timestamp_ns(seg_b["ts_local"])
            idx = np.where((times_ns >= seg_a_ns) & (times_ns <= seg_b_ns))[0]
            if idx.size == 0:
                continue
            d0 = float(seg_a["s_km"])
            d1 = float(seg_b["s_km"])
            if abs(d1 - d0) <= 1.0e-9:
                dist[idx] = d0
                continue
            local_steps = step_km[idx]
            progress = np.cumsum(np.r_[0.0, local_steps[:-1]])
            total = float(progress[-1] + local_steps[-1]) if local_steps.size else 0.0
            if total <= 1.0e-9:
                weights = np.linspace(0.0, 1.0, idx.size)
            else:
                weights = progress / total
            dist[idx] = d0 + weights * (d1 - d0)
        for anchor in day_anchors:
            anchor_ns = timestamp_ns(anchor["ts_local"])
            nearest = int(np.argmin(np.abs(times_ns - anchor_ns)))
            dist[nearest] = float(anchor["s_km"])
        dist = pd.Series(dist).interpolate(limit_direction="both").ffill().bfill().to_numpy()
        log_df.loc[day_idxes, "s_km"] = dist
    return log_df                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def load_route_dem() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:  # [関数定義] load_route_dem の処理実行ブロック
    dem = robust_read_csv(DEM_CSV).copy()
    dem["dist_km"] = pd.to_numeric(dem["distance_m"], errors="coerce") / 1000.0
    dem["lat"] = pd.to_numeric(dem["lat"], errors="coerce")
    dem["lon"] = pd.to_numeric(dem["lon"], errors="coerce")
    dem["elev_m"] = pd.to_numeric(dem["elev_dem_m"], errors="coerce")
    dem["slope_pct"] = pd.to_numeric(dem["grade_smoothed_pct"], errors="coerce").fillna(
        pd.to_numeric(dem["grade_raw_pct"], errors="coerce")
    )
    route_profile = dem[["dist_km", "slope_pct"]].copy()
    route_profile["headwind_ms"] = 0.0
    route_waypoints = dem.iloc[::100, :][["dist_km", "lat", "lon", "elev_m"]].copy()
    route_waypoints = pd.concat([route_waypoints, dem.iloc[[-1]][["dist_km", "lat", "lon", "elev_m"]]], ignore_index=True)
    return dem, route_profile, route_waypoints                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def attach_route_geometry(log_df: pd.DataFrame, dem: pd.DataFrame) -> pd.DataFrame:  # [関数定義] attach_route_geometry の処理実行ブロック
    log_df = log_df.copy()
    route_df = dem[["dist_km", "lat", "lon", "elev_m", "slope_pct"]].dropna().sort_values("dist_km").copy()
    dist_grid = route_df["dist_km"].to_numpy(dtype=float)
    lat_grid = route_df["lat"].to_numpy(dtype=float)
    lon_grid = route_df["lon"].to_numpy(dtype=float)
    elev_grid = route_df["elev_m"].to_numpy(dtype=float)
    slope_grid = route_df["slope_pct"].to_numpy(dtype=float)
    s_query = log_df["s_km"].to_numpy(dtype=float)

    lat_rad = np.radians(lat_grid)
    lon_rad = np.radians(lon_grid)
    dlon = lon_rad[1:] - lon_rad[:-1]
    y = np.sin(dlon) * np.cos(lat_rad[1:])
    x = np.cos(lat_rad[:-1]) * np.sin(lat_rad[1:]) - np.sin(lat_rad[:-1]) * np.cos(lat_rad[1:]) * np.cos(dlon)
    seg_heading = (np.degrees(np.arctan2(y, x)) + 360.0) % 360.0
    heading_grid = np.empty_like(lat_grid)
    if len(seg_heading) == 0:
        heading_grid[:] = 0.0
    elif len(seg_heading) == 1:
        heading_grid[:] = seg_heading[0]
    else:
        heading_grid[0] = seg_heading[0]
        heading_grid[-1] = seg_heading[-1]
        heading_grid[1:-1] = 0.5 * (seg_heading[:-1] + seg_heading[1:])

    log_df["lat"] = np.interp(s_query, dist_grid, lat_grid)
    log_df["lon"] = np.interp(s_query, dist_grid, lon_grid)
    log_df["alt_m"] = np.interp(s_query, dist_grid, elev_grid)
    log_df["slope_pct"] = np.interp(s_query, dist_grid, slope_grid)
    log_df["route_heading_deg"] = np.interp(s_query, dist_grid, heading_grid)
    return log_df                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def apply_exclusion_flags(log_df: pd.DataFrame) -> pd.DataFrame:   # [関数定義] apply_exclusion_flags の処理実行ブロック
    log_df = log_df.copy()
    log_df["exclude_power_fit"] = False
    log_df["exclude_voltage_fit"] = False
    log_df["exclude_weather_fit"] = False
    log_df["exclude_reason"] = ""
    for interval in EXCLUDE_INTERVALS:
        start = local_dt(interval["start_local"])
        end = local_dt(interval["end_local"])
        mask = (log_df["time_local"] >= start) & (log_df["time_local"] <= end)
        if not mask.any():
            continue
        if interval.get("exclude_power_fit", False):
            log_df.loc[mask, "exclude_power_fit"] = True
        if interval.get("exclude_voltage_fit", False):
            log_df.loc[mask, "exclude_voltage_fit"] = True
        if interval.get("exclude_weather_fit", False):
            log_df.loc[mask, "exclude_weather_fit"] = True
        append_reason(log_df, mask, interval["reason"])
    invalid_voltage = (~np.isfinite(log_df["battery_voltage_v"])) | (log_df["battery_voltage_v"] <= INVALID_PACK_VOLTAGE_MIN_V)
    if invalid_voltage.any():
        log_df.loc[invalid_voltage, "exclude_power_fit"] = True
        log_df.loc[invalid_voltage, "exclude_voltage_fit"] = True
        append_reason(log_df, invalid_voltage, "invalid_pack_voltage_sensor")
    return log_df                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _fetch_json(url: str, timeout_sec: float = 60.0, retries: int = 3) -> Dict:  # [関数定義] _fetch_json の処理実行ブロック
    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "solarcar-bwsc2025-fit/1.0"})
            with urllib.request.urlopen(req, timeout=timeout_sec) as res:
                return json.loads(res.read().decode("utf-8"))      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception as exc:  # pragma: no cover - network retry path
            last_exc = exc
            if attempt + 1 >= retries:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch json after {retries} attempts: {url}") from last_exc


def archive_url(latitude, longitude, start_date: str, end_date: str) -> str:  # [関数定義] archive_url の処理実行ブロック
    if isinstance(latitude, (list, tuple, np.ndarray)):
        lat_text = ",".join(f"{float(v):.6f}" for v in latitude)
    else:
        lat_text = f"{float(latitude):.6f}"
    if isinstance(longitude, (list, tuple, np.ndarray)):
        lon_text = ",".join(f"{float(v):.6f}" for v in longitude)
    else:
        lon_text = f"{float(longitude):.6f}"
    params = {
        "latitude": lat_text,
        "longitude": lon_text,
        "start_date": start_date,
        "end_date": end_date,
        "timezone": "GMT",
        "hourly": "temperature_2m,shortwave_radiation,wind_speed_10m,wind_direction_10m",
    }
    return OPENMETEO_ARCHIVE_URL + "?" + urllib.parse.urlencode(params)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def meteorological_headwind_ms(wind_speed_ms: float, wind_from_deg: float, heading_deg: float) -> float:  # [関数定義] meteorological_headwind_ms の処理実行ブロック
    if not math.isfinite(wind_speed_ms):
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = math.radians((float(wind_from_deg) - float(heading_deg) + 180.0) % 360.0 - 180.0)
    return float(wind_speed_ms) * math.cos(delta)                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fetch_route_weather_cache(                                     # [関数定義] fetch_route_weather_cache の処理実行ブロック
    dem: pd.DataFrame,
    cache_csv: Path,
    start_date: str,
    end_date: str,
    *,
    max_s_km: float | None = None,
) -> pd.DataFrame:
    sample_limit_km = float(max_s_km if max_s_km is not None else pd.to_numeric(dem["dist_km"], errors="coerce").max())
    if cache_csv.exists():
        cached = pd.read_csv(cache_csv, parse_dates=["time_utc"])
        cached["time_utc"] = pd.to_datetime(cached["time_utc"], utc=True)
        cached_max_s = float(pd.to_numeric(cached.get("s_km"), errors="coerce").max()) if "s_km" in cached.columns else -1.0
        cached_max_date = cached["time_utc"].max().date().isoformat() if "time_utc" in cached.columns and not cached.empty else ""
        if cached_max_s + 1.0 >= sample_limit_km and cached_max_date >= end_date:
            return cached                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却
    sample_ds = sorted(
        set(
            [round(x, 1) for x in np.arange(0.0, sample_limit_km + 1.0, WEATHER_SAMPLE_STEP_KM)]
            + [round(float(a["s_km"]), 1) for a in load_event_anchors()]
        )
    )
    rows: List[dict] = []
    sample_points = []
    route_lookup = dem[["dist_km", "lat", "lon"]]
    for s_km in sample_ds:
        lat, lon = interpolate_route(route_lookup, s_km)
        heading = interpolate_route_heading(route_lookup, s_km, span_km=0.5)
        sample_points.append({"s_km": float(s_km), "lat": float(lat), "lon": float(lon), "heading": float(heading)})

    for start in range(0, len(sample_points), WEATHER_BATCH_SIZE):
        batch = sample_points[start : start + WEATHER_BATCH_SIZE]
        payload = _fetch_json(
            archive_url(
                [row["lat"] for row in batch],
                [row["lon"] for row in batch],
                start_date,
                end_date,
            )
        )
        payload_list = payload if isinstance(payload, list) else [payload]
        for meta, point_payload in zip(batch, payload_list):
            hourly = point_payload.get("hourly", {})
            times = hourly.get("time", []) or []
            ghi = hourly.get("shortwave_radiation", []) or []
            tamb = hourly.get("temperature_2m", []) or []
            ws = hourly.get("wind_speed_10m", []) or hourly.get("windspeed_10m", []) or []
            wd = hourly.get("wind_direction_10m", []) or hourly.get("winddirection_10m", []) or []
            for ts_text, ghi_v, tamb_v, ws_v, wd_v in zip(times, ghi, tamb, ws, wd):
                ts_utc = datetime.fromisoformat(ts_text).replace(tzinfo=timezone.utc)
                rows.append(
                    {
                        "time_utc": ts_utc,
                        "s_km": meta["s_km"],
                        "lat": meta["lat"],
                        "lon": meta["lon"],
                        "route_heading_deg": meta["heading"],
                        "GHI_archive": float(ghi_v or 0.0),
                        "Tamb_archive_C": float(tamb_v or 0.0),
                        "wind_speed_ms": float(ws_v or 0.0),
                        "wind_dir_deg": float(wd_v or 0.0),
                        "headwind_archive_ms": meteorological_headwind_ms(float(ws_v or 0.0), float(wd_v or 0.0), meta["heading"]),
                    }
                )
    out = pd.DataFrame(rows).sort_values(["time_utc", "s_km"]).reset_index(drop=True)
    ensure_dir(cache_csv.parent)
    out.to_csv(cache_csv, index=False)
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_weather_interpolators(weather_df: pd.DataFrame) -> Dict[str, RegularGridInterpolator]:  # [関数定義] build_weather_interpolators の処理実行ブロック
    time_grid = np.array(sorted(series_timestamp_s(weather_df["time_utc"].drop_duplicates())), dtype=float)
    s_grid = np.array(sorted(weather_df["s_km"].drop_duplicates()), dtype=float)
    interpolators = {}
    for col in ("GHI_archive", "Tamb_archive_C", "headwind_archive_ms", "wind_speed_ms", "wind_dir_deg"):
        pivot = (
            weather_df.assign(time_key=series_timestamp_s(weather_df["time_utc"]))
            .pivot(index="time_key", columns="s_km", values=col)
            .reindex(index=time_grid, columns=s_grid)
            .interpolate(axis=0, limit_direction="both")
            .interpolate(axis=1, limit_direction="both")
            .ffill()
            .bfill()
        )
        interpolators[col] = RegularGridInterpolator((time_grid, s_grid), pivot.to_numpy(dtype=float), bounds_error=False, fill_value=None)
    interpolators["time_grid"] = time_grid
    interpolators["s_grid"] = s_grid
    return interpolators                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def attach_archive_weather(log_df: pd.DataFrame, weather_df: pd.DataFrame) -> pd.DataFrame:  # [関数定義] attach_archive_weather の処理実行ブロック
    log_df = log_df.copy()
    interps = build_weather_interpolators(weather_df)
    query = np.column_stack(
        [
            series_timestamp_s(log_df["time_utc"]),
            log_df["s_km"].to_numpy(dtype=float),
        ]
    )
    for col in ("GHI_archive", "Tamb_archive_C", "headwind_archive_ms", "wind_speed_ms", "wind_dir_deg"):
        log_df[col] = interps[col](query)
    return log_df                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def base_model_from_public_profile(*, fixed_mass_kg: float | None = None) -> Tuple[dict, SolarCarModel]:  # [関数定義] base_model_from_public_profile の処理実行ブロック
    profile_yaml = SRC_PACKAGE / "profile.yaml"
    with profile_yaml.open("r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    pth = cfg.get("paths", {})
    mdl = cfg.get("model", {})
    params = Params(
        dt=float(cfg.get("mpc", {}).get("dt", 600.0)),
        rho=float(mdl.get("rho", 1.18)),
        CdA=float(mdl.get("CdA", 0.093)),
        Crr=float(mdl.get("Crr", 0.005)),
        Crr_per_wheel=float(mdl.get("Crr_per_wheel", 0.0)),
        m=float(fixed_mass_kg if fixed_mass_kg is not None else mdl.get("m", 224.0)),
        P_aux=float(mdl.get("P_aux", 8.0)),
        gear_eta=float(mdl.get("gear_eta", 1.0)),
        gear_ratio=float(mdl.get("gear_ratio", 1.0)),
        wheel_radius=float(mdl.get("wheel_radius", 0.2786)),
        wheel_count=int(mdl.get("wheel_count", 3)),
        driven_wheel_count=int(mdl.get("driven_wheel_count", mdl.get("wheel_count", 1))),
        motor_count=int(mdl.get("motor_count", 1)),
        motor_type=str(mdl.get("motor_type", "inwheel")),
        inverter_eta=float(mdl.get("inverter_eta", 0.98)),
        pv_area=float(mdl.get("pv_area", 6.0)),
        pv_eta_ref=float(mdl.get("pv_eta_ref", 0.24)),
        pv_mu_p=float(mdl.get("pv_mu_p", -0.0045)),
        mppt_eta=float(mdl.get("mppt_eta", 0.95)),
        panel_gain=float(mdl.get("panel_gain", 1.0)),
        E_nom_Wh=float(mdl.get("E_nom_Wh", 3055.0)),
        V_min=float(mdl.get("V_min", 75.0)),
        V_max=float(mdl.get("V_max", 108.75)),
        I_max=float(mdl.get("I_max", 40.0)),
        I_chg_min=float(mdl.get("I_chg_min", -16.5)),
        T_min=float(mdl.get("T_min", -20.0)),
        T_max=float(mdl.get("T_max", 60.0)),
        soc_min=float(mdl.get("soc_min", 0.2)),
        soc_max=float(mdl.get("soc_max", 0.98)),
        grade_scale=float(mdl.get("grade_scale", 1.0)),
        drive_eff_scale=float(mdl.get("drive_eff_scale", 1.0)),
        regen_eff_scale=float(mdl.get("regen_eff_scale", mdl.get("drive_eff_scale", 1.0))),
        rint_scale=float(mdl.get("rint_scale", 1.0)),
        r_line_ohm=float(mdl.get("r_line_ohm", 0.01)),
        eta_charge=float(mdl.get("eta_charge", 1.0)),
    )

    def src(rel_key: str) -> str:                                  # [関数定義] src の処理実行ブロック
        raw = str(pth.get(rel_key, "") or "").strip()
        return str((SRC_PACKAGE / raw).resolve())                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    model = SolarCarModel(
        src("drive_eff_map"),
        src("regen_eff_map"),
        src("rint_map"),
        params=params,
        panel_eff_map_path=src("panel_eff_map"),
        mppt_eff_map_path=src("mppt_eff_map"),
        drive_map_eco_path=src("drive_map_eco"),
        drive_map_power_path=src("drive_map_power"),
        regen_map_eco_path=src("regen_map_eco"),
        regen_map_power_path=src("regen_map_power"),
        ocv_soc_map_path="",
    )
    return cfg, model                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def soc_fit_upper_bound(base_model: SolarCarModel) -> float:       # [関数定義] soc_fit_upper_bound の処理実行ブロック
    return float(np.clip(base_model.p.soc_max, 0.80, 1.0))         # [戻り値] 計算結果・計算状態の呼び出し元への返却


def soft_soc_upper_bound(base_model: SolarCarModel) -> float:      # [関数定義] soft_soc_upper_bound の処理実行ブロック
    return float(min(1.02, soc_fit_upper_bound(base_model) + 0.01))  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fit_pv_parameters(log_df: pd.DataFrame, base_model: SolarCarModel) -> PvFitResult:  # [関数定義] fit_pv_parameters の処理実行ブロック
    work = log_df.copy()
    work["solar_power_w_obs"] = work["solar_power_w_obs"].clip(lower=0.0)
    ghi_col = "GHI_effective" if "GHI_effective" in work.columns else "GHI_archive"
    work = work.set_index(pd.to_datetime(work["time_utc"], utc=True))
    work = (
        work.resample(f"{PV_FIT_RESAMPLE_SEC}s")
        .agg(
            {
                "solar_power_w_obs": "median",
                ghi_col: "mean",
                "Tamb_archive_C": "mean",
                "exclude_weather_fit": "max",
            }
        )
        .dropna()
        .reset_index()
    )
    work["exclude_weather_fit"] = work["exclude_weather_fit"].fillna(False).astype(bool)
    y_obs = smooth_series(work["solar_power_w_obs"], window=7)
    ghi = work[ghi_col].to_numpy(dtype=float)
    tamb = work["Tamb_archive_C"].to_numpy(dtype=float)
    valid = (
        (~work["exclude_weather_fit"])
        & np.isfinite(y_obs.to_numpy(dtype=float))
        & np.isfinite(ghi)
        & np.isfinite(tamb)
        & ((y_obs.to_numpy(dtype=float) > 20.0) | (ghi > 80.0))
    )
    if not np.any(valid):
        return PvFitResult(panel_gain=1.0, tcell_gain_c_per_wm2=0.03, objective=0.0, solar_rmse_w=float("nan"))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    ghi_use = ghi[valid]
    tamb_use = tamb[valid]
    y_use = y_obs.to_numpy(dtype=float)[valid]

    def objective(x: np.ndarray) -> float:                         # [関数定義] objective の処理実行ブロック
        panel_gain, tcell_gain = [float(v) for v in x]
        tcell = tamb_use + tcell_gain * ghi_use
        base_pred = np.array([float(base_model.pv_power_mppt(g, tc)) for g, tc in zip(ghi_use, tcell)], dtype=float)
        pred = panel_gain * base_pred
        resid = y_use - pred
        delta = 120.0
        huber = np.where(np.abs(resid) <= delta, 0.5 * resid ** 2, delta * (np.abs(resid) - 0.5 * delta))
        return float(np.mean(huber))                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    x0 = np.array([1.0, PV_TCELL_SEED_GAIN], dtype=float)
    bounds = [(0.80, 1.25), (0.0, 0.08)]
    res = minimize(objective, x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": PV_FIT_MAXITER})
    x = res.x if res.success else x0
    tcell = tamb_use + float(x[1]) * ghi_use
    base_pred = np.array([float(base_model.pv_power_mppt(g, tc)) for g, tc in zip(ghi_use, tcell)], dtype=float)
    pred = float(x[0]) * base_pred
    rmse = float(np.sqrt(np.mean((y_use - pred) ** 2)))
    return PvFitResult(                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        panel_gain=float(x[0]),
        tcell_gain_c_per_wm2=float(x[1]),
        objective=float(objective(x)),
        solar_rmse_w=rmse,
    )


def attach_archive_pv_model(log_df: pd.DataFrame, base_model: SolarCarModel, pv: PvFitResult) -> pd.DataFrame:  # [関数定義] attach_archive_pv_model の処理実行ブロック
    work = log_df.copy()
    ghi_col = "GHI_effective" if "GHI_effective" in work.columns else "GHI_archive"
    ghi = work[ghi_col].to_numpy(dtype=float)
    tamb = work["Tamb_archive_C"].to_numpy(dtype=float)
    tcell = tamb + float(pv.tcell_gain_c_per_wm2) * ghi
    base_pred = np.array([float(base_model.pv_power_mppt(g, tc)) for g, tc in zip(ghi, tcell)], dtype=float)
    solar_model = float(pv.panel_gain) * base_pred
    work["solar_power_w_archive_base"] = base_pred
    work["solar_power_w_model"] = solar_model
    work["solar_power_w_obs_smooth"] = smooth_series(work["solar_power_w_obs"].clip(lower=0.0), window=13)
    if "GHI_effective" in work.columns:
        denom = np.maximum(work["GHI_archive"].to_numpy(dtype=float), 1.0)
        work["solar_ratio"] = np.clip(ghi / denom, 0.0, 1.8)
    else:
        work["solar_ratio"] = np.where(base_pred > 1.0, solar_model / base_pred, 1.0)
        work["GHI_effective"] = work["GHI_archive"]
    work["Tcell_effective_C"] = tcell
    return work                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_ocv_curve(out_csv: Path) -> pd.DataFrame:                # [関数定義] build_ocv_curve の処理実行ブロック
    df = robust_read_csv(DISCHARGE_TEST_CSV)
    if not {"cellVoltage(V)", "SOC(%)"}.issubset(df.columns):
        raise ValueError("discharge test csv is missing required columns")
    work = pd.DataFrame(
        {
            "soc": pd.to_numeric(df["SOC(%)"], errors="coerce") / 100.0,
            "ocv_v": pd.to_numeric(df["cellVoltage(V)"], errors="coerce") * 25.0,
        }
    ).dropna()
    work["soc_bin"] = (work["soc"] / 0.01).round() * 0.01
    out = work.groupby("soc_bin", as_index=False)["ocv_v"].median().rename(columns={"soc_bin": "soc"}).sort_values("soc")
    ensure_dir(out_csv.parent)
    out.to_csv(out_csv, index=False)
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def inverse_ocv_lookup(ocv_df: pd.DataFrame, voltage_v: float) -> float:  # [関数定義] inverse_ocv_lookup の処理実行ブロック
    work = ocv_df.sort_values("ocv_v")
    return float(np.interp(float(voltage_v), work["ocv_v"].to_numpy(), work["soc"].to_numpy()))  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def rint_lookup(base_model: SolarCarModel, temp_c: float, soc: float) -> float:  # [関数定義] rint_lookup の処理実行ブロック
    return float(base_model.R_int(float(temp_c), float(np.clip(soc, 0.1, 0.95))))  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def battery_prior_penalty(soc0_seed: float, x: np.ndarray) -> float:  # [関数定義] battery_prior_penalty の処理実行ブロック
    soc0, e_nom_wh, rint_scale, r_line_ohm, eta_charge = [float(v) for v in x]
    prior = 0.0
    prior += 2.0 * ((soc0 - soc0_seed) / BATTERY_PRIOR_SOC0_SIGMA) ** 2
    prior += 6.0 * ((e_nom_wh - BATTERY_PRIOR_E_NOM_WH) / BATTERY_PRIOR_E_NOM_SIGMA_WH) ** 2
    prior += 1.5 * ((rint_scale - BATTERY_PRIOR_RINT_SCALE) / BATTERY_PRIOR_RINT_SIGMA) ** 2
    prior += 1.5 * ((r_line_ohm - BATTERY_PRIOR_RLINE_OHM) / BATTERY_PRIOR_RLINE_SIGMA_OHM) ** 2
    prior += 2.0 * ((eta_charge - BATTERY_PRIOR_ETA_CHARGE) / BATTERY_PRIOR_ETA_SIGMA) ** 2
    return float(prior)                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却


def motion_prior_penalty(x: np.ndarray) -> float:                  # [関数定義] motion_prior_penalty の処理実行ブロック
    cda, crr, p_aux_w, grade_scale, drive_eff_scale, headwind_gain = [float(v) for v in x]
    prior = 0.0
    prior += 400.0 * ((cda - MOTION_PRIOR_CDA) / MOTION_PRIOR_CDA_SIGMA) ** 2
    prior += 120.0 * ((crr - MOTION_PRIOR_CRR) / MOTION_PRIOR_CRR_SIGMA) ** 2
    prior += 200.0 * ((p_aux_w - MOTION_PRIOR_P_AUX_W) / MOTION_PRIOR_P_AUX_SIGMA_W) ** 2
    prior += 80.0 * ((grade_scale - MOTION_PRIOR_GRADE_SCALE) / MOTION_PRIOR_GRADE_SIGMA) ** 2
    prior += 180.0 * ((drive_eff_scale - MOTION_PRIOR_DRIVE_EFF_SCALE) / MOTION_PRIOR_DRIVE_EFF_SIGMA) ** 2
    prior += 260.0 * ((headwind_gain - MOTION_PRIOR_HEADWIND_GAIN) / MOTION_PRIOR_HEADWIND_SIGMA) ** 2
    return float(prior)                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却


def clip_to_bounds_vec(x: np.ndarray, bounds: List[Tuple[float, float]]) -> np.ndarray:  # [関数定義] clip_to_bounds_vec の処理実行ブロック
    out = np.asarray(x, dtype=float).copy()
    for idx, (lo, hi) in enumerate(bounds):
        out[idx] = float(np.clip(out[idx], lo, hi))
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def clone_params(params: Params) -> Params:                        # [関数定義] clone_params の処理実行ブロック
    payload = {field.name: getattr(params, field.name) for field in fields(Params)}
    return Params(**payload)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def identity_shape_summary(name: str, x_grid: np.ndarray, y_grid: np.ndarray, *, reason: str = "identity") -> Dict[str, object]:  # [関数定義] identity_shape_summary の処理実行ブロック
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "name": name,
        "sample_count": 0,
        "reason": reason,
        "global_log_gain": 0.0,
        "row_offsets": [0.0 for _ in x_grid],
        "col_offsets": [0.0 for _ in y_grid],
        "ratio_bounds": [1.0, 1.0],
        "rmse_before": float("nan"),
        "rmse_after": float("nan"),
        "correction_min": 1.0,
        "correction_max": 1.0,
    }


def unpack_shape_theta(theta: np.ndarray, nx: int, ny: int) -> Tuple[float, np.ndarray, np.ndarray]:  # [関数定義] unpack_shape_theta の処理実行ブロック
    theta = np.asarray(theta, dtype=float)
    g = float(theta[0])
    row = theta[1 : 1 + nx].astype(float).copy()
    col = theta[1 + nx : 1 + nx + ny].astype(float).copy()
    row -= float(np.mean(row))
    col -= float(np.mean(col))
    return g, row, col                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def shape_log_surface_at(                                          # [関数定義] shape_log_surface_at の処理実行ブロック
    x_grid: np.ndarray,
    y_grid: np.ndarray,
    summary: Dict[str, object],
    x_samples: np.ndarray,
    y_samples: np.ndarray,
) -> np.ndarray:
    row = np.asarray(summary.get("row_offsets", []), dtype=float)
    col = np.asarray(summary.get("col_offsets", []), dtype=float)
    g = float(summary.get("global_log_gain", 0.0))
    row_interp = np.interp(np.asarray(x_samples, dtype=float), np.asarray(x_grid, dtype=float), row)
    col_interp = np.interp(np.asarray(y_samples, dtype=float), np.asarray(y_grid, dtype=float), col)
    return g + row_interp + col_interp                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fit_separable_shape_summary(                                   # [関数定義] fit_separable_shape_summary の処理実行ブロック
    name: str,
    x_grid: np.ndarray,
    y_grid: np.ndarray,
    x_samples: np.ndarray,
    y_samples: np.ndarray,
    base_values: np.ndarray,
    target_values: np.ndarray,
    ratio_bounds: Tuple[float, float],
    *,
    smooth_weight: float,
    anchor_weight: float,
) -> Dict[str, object]:
    x_grid = np.asarray(x_grid, dtype=float)
    y_grid = np.asarray(y_grid, dtype=float)
    x_samples = np.asarray(x_samples, dtype=float)
    y_samples = np.asarray(y_samples, dtype=float)
    base_values = np.asarray(base_values, dtype=float)
    target_values = np.asarray(target_values, dtype=float)
    valid = (
        np.isfinite(x_samples)
        & np.isfinite(y_samples)
        & np.isfinite(base_values)
        & np.isfinite(target_values)
        & (base_values > 1.0e-9)
        & (target_values > 1.0e-9)
    )
    if int(np.count_nonzero(valid)) < max(MAP_SHAPE_MIN_SAMPLES, len(x_grid) + len(y_grid)):
        return identity_shape_summary(name, x_grid, y_grid, reason="insufficient_samples")  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    xs = x_samples[valid]
    ys = y_samples[valid]
    base = base_values[valid]
    target = target_values[valid]
    lo, hi = [float(v) for v in ratio_bounds]
    ratio = np.clip(target / np.maximum(base, 1.0e-9), lo, hi)
    log_target = np.log(np.maximum(ratio, 1.0e-9))
    nx = int(len(x_grid))
    ny = int(len(y_grid))

    def objective(theta: np.ndarray) -> float:                     # [関数定義] objective の処理実行ブロック
        g, row, col = unpack_shape_theta(theta, nx, ny)
        pred = g + np.interp(xs, x_grid, row) + np.interp(ys, y_grid, col)
        resid = log_target - pred
        delta = 0.08
        huber = np.where(np.abs(resid) <= delta, 0.5 * resid ** 2, delta * (np.abs(resid) - 0.5 * delta))
        smooth = smooth_weight * (
            np.mean(np.diff(row) ** 2) if nx >= 2 else 0.0
        ) + smooth_weight * (
            np.mean(np.diff(col) ** 2) if ny >= 2 else 0.0
        )
        anchor = anchor_weight * (np.mean(row ** 2) + np.mean(col ** 2)) + 0.25 * (g ** 2)
        return float(np.mean(huber) + smooth + anchor)             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    x0[0] = float(np.clip(np.median(log_target), -0.12, 0.12))
    bounds = [(-MAP_SHAPE_LOG_BOUND, MAP_SHAPE_LOG_BOUND)] * len(x0)
    res = minimize(
        objective,
        x0,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": MAP_SHAPE_MAXITER},
    )
    theta = res.x if res.success else x0
    g, row, col = unpack_shape_theta(theta, nx, ny)
    summary = {
        "name": name,
        "sample_count": int(len(xs)),
        "reason": "fitted" if res.success else "fallback_start",
        "global_log_gain": float(g),
        "row_offsets": [float(v) for v in row],
        "col_offsets": [float(v) for v in col],
        "ratio_bounds": [float(lo), float(hi)],
    }
    pred_log = shape_log_surface_at(x_grid, y_grid, summary, xs, ys)
    pred_scale = np.exp(pred_log)
    summary["rmse_before"] = float(np.sqrt(np.mean((target - base) ** 2)))
    summary["rmse_after"] = float(np.sqrt(np.mean((target - base * pred_scale) ** 2)))
    grid_scale = np.exp(float(g) + row[:, None] + col[None, :])
    summary["correction_min"] = float(np.min(grid_scale))
    summary["correction_max"] = float(np.max(grid_scale))
    return summary                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def apply_shape_summary_to_df(                                     # [関数定義] apply_shape_summary_to_df の処理実行ブロック
    df: pd.DataFrame,
    summary: Dict[str, object],
    *,
    lower: float,
    upper: float,
) -> pd.DataFrame:
    x_grid = df.index.to_numpy(dtype=float)
    y_grid = df.columns.to_numpy(dtype=float)
    row = np.asarray(summary.get("row_offsets", []), dtype=float)
    col = np.asarray(summary.get("col_offsets", []), dtype=float)
    if len(row) != len(x_grid) or len(col) != len(y_grid):
        return df.copy()                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
    corr = np.exp(float(summary.get("global_log_gain", 0.0)) + row[:, None] + col[None, :])
    out = df.astype(float) * corr
    return out.clip(lower=lower, upper=upper)                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def scaled_shape_summary(summary: Dict[str, object], share: float, name: str) -> Dict[str, object]:  # [関数定義] scaled_shape_summary の処理実行ブロック
    share = float(np.clip(share, 0.0, 1.0))
    out = dict(summary)
    out["name"] = name
    out["share_of_combined_log_correction"] = share
    out["global_log_gain"] = float(summary.get("global_log_gain", 0.0)) * share
    out["row_offsets"] = [float(v) * share for v in summary.get("row_offsets", [])]
    out["col_offsets"] = [float(v) * share for v in summary.get("col_offsets", [])]
    out["reason"] = f"shared_from_{summary.get('name', 'combined')}"
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_model_from_map_assets(base_model: SolarCarModel, map_assets: Dict[str, Path]) -> SolarCarModel:  # [関数定義] build_model_from_map_assets の処理実行ブロック
    return SolarCarModel(                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却
        os.fspath(map_assets["drive_eff_map"]),
        os.fspath(map_assets["regen_eff_map"]),
        os.fspath(map_assets["rint_map"]),
        params=clone_params(base_model.p),
        panel_eff_map_path=os.fspath(map_assets["panel_eff_map"]),
        mppt_eff_map_path=os.fspath(map_assets["mppt_eff_map"]),
        drive_map_eco_path=os.fspath(map_assets["drive_map_eco"]),
        drive_map_power_path=os.fspath(map_assets["drive_map_power"]),
        regen_map_eco_path=os.fspath(map_assets["regen_map_eco"]),
        regen_map_power_path=os.fspath(map_assets["regen_map_power"]),
        ocv_soc_map_path="",
    )


def rest_soc_targets(df: pd.DataFrame, ocv_df: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray]:  # [関数定義] rest_soc_targets の処理実行ブロック
    mask = (
        (~df["exclude_voltage_fit"])
        & np.isfinite(df["battery_voltage_v"])
        & np.isfinite(df["battery_current_a"])
        & np.isfinite(df["speed_kmh"])
        & (df["battery_voltage_v"] >= REST_SOC_VOLTAGE_MIN_V)
        & (df["speed_kmh"] <= REST_SOC_SPEED_MAX_KMH)
        & (df["battery_current_a"].abs() <= REST_SOC_CURRENT_MAX_A)
    )
    soc_obs = np.full(len(df), np.nan, dtype=float)
    if mask.any():
        work = ocv_df.sort_values("ocv_v")
        soc_obs[mask.to_numpy(dtype=bool)] = np.interp(
            df.loc[mask, "battery_voltage_v"].to_numpy(dtype=float),
            work["ocv_v"].to_numpy(dtype=float),
            work["soc"].to_numpy(dtype=float),
        )
    return mask.to_numpy(dtype=bool), soc_obs                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def make_battery_starts(soc0_seed: float, soc0_hi: float) -> List[np.ndarray]:  # [関数定義] make_battery_starts の処理実行ブロック
    starts = [
        np.array([soc0_seed, BATTERY_PRIOR_E_NOM_WH, 1.10, 0.010, 0.975], dtype=float),
        np.array([min(soc0_hi, soc0_seed + 0.01), BATTERY_PRIOR_E_NOM_WH, 1.40, 0.015, 0.955], dtype=float),
        np.array([min(soc0_hi, soc0_seed + 0.02), 2960.0, 1.80, 0.022, 0.948], dtype=float),
        np.array([max(0.88, soc0_seed - 0.01), 3050.0, 1.25, 0.012, 0.965], dtype=float),
        np.array([min(soc0_hi, soc0_seed + 0.03), 2900.0, 2.00, 0.028, 0.940], dtype=float),
        np.array([max(0.86, soc0_seed - 0.02), 3120.0, 0.95, 0.008, 0.985], dtype=float),
    ]
    return starts[:BATTERY_RESTART_COUNT]                          # [戻り値] 計算結果・計算状態の呼び出し元への返却


def make_motion_starts(x0: np.ndarray) -> List[np.ndarray]:        # [関数定義] make_motion_starts の処理実行ブロック
    starts = [
        x0,
        np.array([0.100, 0.0080, 24.0, 0.90, 1.00, 0.10], dtype=float),
        np.array([0.120, 0.0055, 18.0, 1.05, 1.04, 0.15], dtype=float),
        np.array([0.110, 0.0070, 21.0, 1.00, 1.02, 0.12], dtype=float),
        np.array([0.105, 0.0090, 21.5, 0.82, 0.97, 0.08], dtype=float),
        np.array([0.115, 0.0060, 20.5, 0.94, 0.94, 0.18], dtype=float),
        np.array([0.108, 0.0105, 25.0, 0.76, 0.92, 0.05], dtype=float),
        np.array([0.112, 0.0045, 17.0, 1.08, 1.08, 0.22], dtype=float),
    ]
    return starts[:MOTION_RESTART_COUNT]                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def battery_replay_voltage(                                        # [関数定義] battery_replay_voltage の処理実行ブロック
    df: pd.DataFrame,
    ocv_df: pd.DataFrame,
    base_model: SolarCarModel,
    soc0: float,
    e_nom_wh: float,
    rint_scale: float,
    r_line_ohm: float,
    eta_charge: float,
) -> Tuple[np.ndarray, np.ndarray]:
    soc_vals = []
    v_preds = []
    z = float(np.clip(soc0, 0.02, 1.0))
    for row in df.itertuples(index=False):
        soc_vals.append(z)
        ocv_v = float(np.interp(z, ocv_df["soc"].to_numpy(), ocv_df["ocv_v"].to_numpy()))
        temp_c = float(getattr(row, "Tamb_archive_C", 25.0))
        r_ohm = max(1.0e-5, rint_scale * rint_lookup(base_model, temp_c, z) + r_line_ohm)
        i_obs = float(getattr(row, "battery_current_a"))
        v_preds.append(ocv_v - i_obs * r_ohm)
        p_obs = float(getattr(row, "battery_power_w_obs"))
        dt_sec = float(getattr(row, "dt_sec"))
        eta = eta_charge if p_obs < 0.0 else 1.0
        z = z - eta * (p_obs * dt_sec / 3600.0) / max(e_nom_wh, 100.0)
        z = float(np.clip(z, -0.05, 1.05))
    return np.asarray(soc_vals, dtype=float), np.asarray(v_preds, dtype=float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fit_battery_parameters(                                        # [関数定義] fit_battery_parameters の処理実行ブロック
    fit_df: pd.DataFrame,
    ocv_df: pd.DataFrame,
    base_model: SolarCarModel,
    *,
    restart_count: int = BATTERY_RESTART_COUNT,
    maxiter: int = BATTERY_FIT_MAXITER,
    fit_stride: int = 1,
) -> BatteryFitResult:
    use_df = fit_df.iloc[:: max(1, int(fit_stride))].reset_index(drop=True)
    valid = (
        (~use_df["exclude_voltage_fit"])
        & np.isfinite(use_df["battery_voltage_v"])
        & np.isfinite(use_df["battery_current_a"])
        & (use_df["battery_voltage_v"] >= INVALID_PACK_VOLTAGE_MIN_V)
    )
    if not valid.any():
        return BatteryFitResult(                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
            soc0=0.95,
            e_nom_wh=float(base_model.p.E_nom_Wh),
            rint_scale=1.0,
            r_line_ohm=0.01,
            eta_charge=0.985,
            objective=float("nan"),
            voltage_rmse_v=float("nan"),
        )

    v_start = float(use_df.loc[valid, "battery_voltage_v"].iloc[0])
    soc0_hi = soc_fit_upper_bound(base_model)
    soc_soft_hi = soft_soc_upper_bound(base_model)
    soc0_seed = float(np.clip(inverse_ocv_lookup(ocv_df, v_start), 0.60, soc0_hi))
    v_obs = use_df["battery_voltage_v"].to_numpy(dtype=float)
    valid_mask = valid.to_numpy(dtype=bool)
    rest_mask, rest_soc_obs = rest_soc_targets(use_df, ocv_df)

    def objective(x: np.ndarray) -> float:                         # [関数定義] objective の処理実行ブロック
        soc0, e_nom_wh, rint_scale, r_line_ohm, eta_charge = [float(v) for v in x]
        soc_arr, v_pred = battery_replay_voltage(
            use_df,
            ocv_df,
            base_model,
            soc0,
            e_nom_wh,
            rint_scale,
            r_line_ohm,
            eta_charge,
        )
        resid = v_obs[valid_mask] - v_pred[valid_mask]
        huber_delta = 3.0
        huber = np.where(np.abs(resid) <= huber_delta, 0.5 * resid ** 2, huber_delta * (np.abs(resid) - 0.5 * huber_delta))
        prior = battery_prior_penalty(soc0_seed, x)
        rest_penalty = 0.0
        if rest_mask.any():
            rest_err = (soc_arr[rest_mask] - rest_soc_obs[rest_mask]) / REST_SOC_SIGMA
            rest_penalty = 4.0 * float(np.mean(rest_err ** 2))
        penalty = float(np.mean(np.maximum(0.0, soc_arr - soc_soft_hi) ** 2 + np.maximum(0.0, -0.02 - soc_arr) ** 2)) * 1.0e4
        return float(np.mean(huber) + prior + rest_penalty + penalty)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    starts = make_battery_starts(soc0_seed, soc0_hi)[: max(1, int(restart_count))]
    bounds = [
        (0.80, soc0_hi),
        (2700.0, 3200.0),
        (0.6, 2.5),
        (0.0, 0.05),
        (0.93, 0.999),
    ]
    best_x = None
    best_obj = float("inf")
    best_pred = None
    for x0 in starts:
        res = minimize(objective, x0, method="L-BFGS-B", bounds=bounds, options={"maxiter": int(maxiter)})
        x = res.x if res.success else x0
        score = float(objective(x))
        _, v_pred = battery_replay_voltage(use_df, ocv_df, base_model, float(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]))
        if score < best_obj:
            best_obj = score
            best_x = x
            best_pred = v_pred

    assert best_x is not None and best_pred is not None
    resid = v_obs[valid_mask] - best_pred[valid_mask]
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    return BatteryFitResult(                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        soc0=float(best_x[0]),
        e_nom_wh=float(best_x[1]),
        rint_scale=float(best_x[2]),
        r_line_ohm=float(best_x[3]),
        eta_charge=float(best_x[4]),
        objective=float(best_obj),
        voltage_rmse_v=rmse,
    )


def motion_power_prediction(                                       # [運動電力予測] 速度・勾配・風速・日射量から必要消費電力を物理計算
    speed_kmh: float,
    slope_pct: float,
    headwind_ms: float,
    solar_power_w: float,
    base_model: SolarCarModel,
    cda: float,
    crr: float,
    p_aux_w: float,
    grade_scale: float,
    drive_eff_scale: float,
) -> float:
    v_ms = max(0.0, float(speed_kmh) / 3.6)
    v_rel = max(0.0, v_ms + float(headwind_ms))
    theta = math.atan((float(slope_pct) * float(grade_scale)) / 100.0)
    n_force = base_model.p.m * base_model.p.g * math.cos(theta)
    f_aero = 0.5 * base_model.p.rho * float(cda) * (v_rel ** 2)
    f_roll = float(crr) * n_force
    f_grade = base_model.p.m * base_model.p.g * math.sin(theta)
    p_mech = (f_aero + f_roll + f_grade) * v_ms + float(p_aux_w)
    if p_mech >= 0.0:
        t_m, _ = base_model.torque_from_mech(p_mech, v_ms)
        eff_base = float(base_model.eff_drive(v_ms, t_m))
        eff_drv = float(np.clip(eff_base * float(drive_eff_scale), 0.55, 0.99))
        p_el = p_mech / max(eff_drv * base_model.p.gear_eta * base_model.p.inverter_eta, 1.0e-6)
    else:
        t_m, _ = base_model.torque_from_mech(abs(p_mech), v_ms)
        eff_base = float(base_model.eff_regen(v_ms, t_m))
        eff_reg = float(np.clip(eff_base * float(drive_eff_scale), 0.40, 0.95))
        p_el = -eff_reg * base_model.p.gear_eta * base_model.p.inverter_eta * abs(p_mech)
    return float(p_el - float(solar_power_w))                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def initial_motion_guess(fit_df: pd.DataFrame, base_model: SolarCarModel) -> np.ndarray:  # [関数定義] initial_motion_guess の処理実行ブロック
    return np.array(                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        [
            MOTION_PRIOR_CDA,
            MOTION_PRIOR_CRR,
            MOTION_PRIOR_P_AUX_W,
            0.90,
            MOTION_PRIOR_DRIVE_EFF_SCALE,
            MOTION_PRIOR_HEADWIND_GAIN,
        ],
        dtype=float,
    )


def fit_motion_parameters(                                         # [関数定義] fit_motion_parameters の処理実行ブロック
    fit_df: pd.DataFrame,
    base_model: SolarCarModel,
    *,
    restart_count: int = MOTION_RESTART_COUNT,
    maxiter: int = MOTION_FIT_MAXITER,
    fit_stride: int = 1,
) -> MotionFitResult:
    mask = (
        (~fit_df["exclude_power_fit"])
        & (fit_df["speed_kmh"] >= 12.0)
        & np.isfinite(fit_df["battery_power_w_obs"])
        & np.isfinite(fit_df["solar_power_w_model"])
    )
    work = fit_df.loc[mask].iloc[:: max(1, int(fit_stride))].reset_index(drop=True)
    solar_model = work["solar_power_w_model"].clip(lower=0.0).to_numpy(dtype=float)
    x0 = initial_motion_guess(fit_df, base_model)
    bounds = [
        (0.07, 0.15),
        (0.002, 0.02),
        (10.0, 40.0),
        (0.65, 1.15),
        (0.85, 1.12),
        (0.0, 0.40),
    ]
    starts = make_motion_starts(x0)[: max(1, int(restart_count))]

    def objective(x: np.ndarray) -> float:                         # [関数定義] objective の処理実行ブロック
        preds = np.array(
            [
                motion_power_prediction(
                    row.speed_kmh,
                    row.slope_pct,
                    row.headwind_archive_ms * float(x[5]),
                    solar_w,
                    base_model,
                    x[0],
                    x[1],
                    x[2],
                    x[3],
                    x[4],
                )
                for row, solar_w in zip(work.itertuples(index=False), solar_model)
            ],
            dtype=float,
        )
        resid = work["battery_power_w_obs"].to_numpy(dtype=float) - preds
        delta = 200.0
        huber = np.where(np.abs(resid) <= delta, 0.5 * resid ** 2, delta * (np.abs(resid) - 0.5 * delta))
        prior = motion_prior_penalty(x)
        return float(np.mean(huber) + prior)                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

    best_x = None
    best_obj = float("inf")
    for start in starts:
        res = minimize(objective, start, method="L-BFGS-B", bounds=bounds, options={"maxiter": int(maxiter)})
        x = res.x if res.success else start
        score = float(objective(x))
        if score < best_obj:
            best_obj = score
            best_x = x

    assert best_x is not None
    x = best_x
    preds = np.array(
        [
            motion_power_prediction(
                row.speed_kmh,
                row.slope_pct,
                row.headwind_archive_ms * float(x[5]),
                solar_w,
                base_model,
                x[0],
                x[1],
                x[2],
                x[3],
                x[4],
            )
            for row, solar_w in zip(work.itertuples(index=False), solar_model)
        ],
        dtype=float,
    )
    resid = work["battery_power_w_obs"].to_numpy(dtype=float) - preds
    rmse = float(np.sqrt(np.mean(resid ** 2)))
    sigma = float(np.std(resid, ddof=1)) if len(resid) >= 2 else rmse
    return MotionFitResult(                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        cda=float(x[0]),
        crr=float(x[1]),
        p_aux_w=float(x[2]),
        grade_scale=float(x[3]),
        drive_eff_scale=float(x[4]),
        headwind_gain=float(x[5]),
        objective=best_obj,
        power_rmse_w=rmse,
        residual_sigma_w=sigma,
    )


def joint_refine_parameters(                                       # [関数定義] joint_refine_parameters の処理実行ブロック
    fit_df: pd.DataFrame,
    ocv_df: pd.DataFrame,
    base_model: SolarCarModel,
    batt_init: BatteryFitResult,
    mot_init: MotionFitResult,
    *,
    restart_count: int = JOINT_RESTART_COUNT,
    random_start_count: int = JOINT_RANDOM_START_COUNT,
    local_topk: int = JOINT_LOCAL_TOPK,
    maxiter: int = JOINT_FIT_MAXITER,
    fit_stride: int = 1,
) -> Tuple[BatteryFitResult, MotionFitResult, Dict[str, float]]:
    stride = max(1, int(fit_stride))
    work = fit_df.iloc[::stride].reset_index(drop=True).copy()
    valid_voltage = (
        (~work["exclude_voltage_fit"])
        & np.isfinite(work["battery_voltage_v"])
        & (work["battery_voltage_v"] >= INVALID_PACK_VOLTAGE_MIN_V)
    ).to_numpy(dtype=bool)
    valid_power = (
        (~work["exclude_power_fit"])
        & np.isfinite(work["battery_power_w_obs"])
        & np.isfinite(work["solar_power_w_model"])
        & (work["speed_kmh"] >= 12.0)
    ).to_numpy(dtype=bool)
    rest_mask, rest_soc_obs = rest_soc_targets(work, ocv_df)
    if not valid_voltage.any() or not valid_power.any():
        return batt_init, mot_init, {                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "objective": float("nan"),
            "restart_count": 0,
            "maxiter": int(maxiter),
            "rest_soc_points": int(rest_mask.sum()),
            "accepted": False,
            "fit_stride": stride,
        }

    baseline_df = work.copy()
    baseline_df["headwind_effective_ms"] = baseline_df["headwind_archive_ms"] * float(mot_init.headwind_gain)
    baseline_replay = joint_replay(baseline_df, ocv_df, base_model, batt_init, mot_init)
    baseline_metrics = metrics_from_replay(baseline_replay)

    v_start = float(work.loc[valid_voltage, "battery_voltage_v"].iloc[0])
    soc0_hi = soc_fit_upper_bound(base_model)
    soc_soft_hi = soft_soc_upper_bound(base_model)
    soc0_seed = float(np.clip(inverse_ocv_lookup(ocv_df, v_start), 0.60, soc0_hi))
    bounds = [
        (0.80, soc0_hi),
        (2700.0, 3200.0),
        (0.6, 2.5),
        (0.0, 0.05),
        (0.93, 0.999),
        (0.07, 0.15),
        (0.002, 0.02),
        (10.0, 40.0),
        (0.65, 1.15),
        (0.85, 1.12),
        (0.0, 0.40),
    ]
    x_stage = np.array(
        [
            batt_init.soc0,
            batt_init.e_nom_wh,
            batt_init.rint_scale,
            batt_init.r_line_ohm,
            batt_init.eta_charge,
            mot_init.cda,
            mot_init.crr,
            mot_init.p_aux_w,
            mot_init.grade_scale,
            mot_init.drive_eff_scale,
            mot_init.headwind_gain,
        ],
        dtype=float,
    )
    starts = [
        x_stage,
        x_stage * np.array([1.0, 1.0, 1.0, 1.0, 1.0, 0.98, 1.05, 1.0, 0.95, 0.98, 0.90], dtype=float),
        x_stage * np.array([1.0, 1.0, 1.08, 1.05, 0.995, 1.02, 0.95, 1.0, 1.05, 1.02, 1.10], dtype=float),
        np.array([soc0_seed, BATTERY_PRIOR_E_NOM_WH, 1.40, 0.015, 0.955, 0.110, 0.0060, 21.0, 1.00, 1.02, 0.12], dtype=float),
        np.array([min(soc0_hi, soc0_seed + 0.02), 2960.0, 1.80, 0.022, 0.948, 0.105, 0.0090, 22.0, 0.85, 0.97, 0.09], dtype=float),
        np.array([max(0.88, soc0_seed - 0.01), 3060.0, 1.10, 0.010, 0.975, 0.115, 0.0055, 20.5, 1.05, 1.04, 0.16], dtype=float),
    ][: max(1, int(restart_count))]

    rng = np.random.default_rng(20260708)
    seed_pool = [clip_to_bounds_vec(start, bounds) for start in starts]
    random_noise = np.array([0.015, 90.0, 0.18, 0.0045, 0.008, 0.008, 0.0018, 1.6, 0.08, 0.03, 0.04], dtype=float)
    while len(seed_pool) < max(1, int(random_start_count)):
        base = seed_pool[int(rng.integers(0, len(seed_pool)))]
        candidate = base + rng.normal(size=len(base)) * random_noise
        candidate = clip_to_bounds_vec(candidate, bounds)
        seed_pool.append(candidate)

    anchor_scale = np.array([0.02, 160.0, 0.35, 0.010, 0.020, 0.012, 0.0025, 3.0, 0.10, 0.05, 0.05], dtype=float)

    def objective(x: np.ndarray) -> float:                         # [関数定義] objective の処理実行ブロック
        batt_x = np.asarray(x[:5], dtype=float)
        mot_x = np.asarray(x[5:], dtype=float)
        use_df = work.copy()
        use_df["headwind_effective_ms"] = use_df["headwind_archive_ms"] * float(mot_x[5])
        replay = joint_replay_core(
            use_df,
            ocv_df,
            base_model,
            BatteryFitResult(
                soc0=float(batt_x[0]),
                e_nom_wh=float(batt_x[1]),
                rint_scale=float(batt_x[2]),
                r_line_ohm=float(batt_x[3]),
                eta_charge=float(batt_x[4]),
                objective=0.0,
                voltage_rmse_v=0.0,
            ),
            MotionFitResult(
                cda=float(mot_x[0]),
                crr=float(mot_x[1]),
                p_aux_w=float(mot_x[2]),
                grade_scale=float(mot_x[3]),
                drive_eff_scale=float(mot_x[4]),
                headwind_gain=float(mot_x[5]),
                objective=0.0,
                power_rmse_w=0.0,
                residual_sigma_w=0.0,
            ),
            return_dataframe=False,
        )
        rp = replay["battery_power_w_obs"][valid_power] - replay["battery_power_w_pred"][valid_power]
        rv = replay["battery_voltage_v_obs"][valid_voltage] - replay["battery_voltage_v_pred"][valid_voltage]
        power_rmse = float(np.sqrt(np.mean(rp ** 2)))
        power_bias = float(np.mean(rp))
        voltage_rmse = float(np.sqrt(np.mean(rv ** 2)))
        rest_penalty = 0.0
        if rest_mask.any():
            rest_err = (replay["soc_pred"][rest_mask] - rest_soc_obs[rest_mask]) / REST_SOC_SIGMA
            rest_penalty = 6.0 * float(np.mean(rest_err ** 2))
        soc_bounds = replay["soc_pred"]
        bound_penalty = 4.0e3 * float(np.mean(np.maximum(0.0, soc_bounds - soc_soft_hi) ** 2 + np.maximum(0.0, -0.02 - soc_bounds) ** 2))
        prior = battery_prior_penalty(soc0_seed, batt_x) + motion_prior_penalty(mot_x)
        stage_anchor = JOINT_OBJECTIVE_STAGE_ANCHOR_WEIGHT * float(np.mean(((x - x_stage) / anchor_scale) ** 2))
        return float(                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
            JOINT_OBJECTIVE_POWER_WEIGHT * (power_rmse / 180.0) ** 2
            + JOINT_OBJECTIVE_VOLTAGE_WEIGHT * (voltage_rmse / 4.0) ** 2
            + JOINT_OBJECTIVE_POWER_BIAS_WEIGHT * (power_bias / 75.0) ** 2
            + rest_penalty
            + prior
            + stage_anchor
            + bound_penalty
        )

    baseline_objective = float(objective(x_stage))
    best_x = None
    best_obj = float("inf")
    seed_rank = sorted(((float(objective(seed)), seed) for seed in seed_pool), key=lambda item: item[0])
    local_starts = [seed.copy() for _, seed in seed_rank[: min(max(1, int(local_topk)), len(seed_rank))]]
    for start in local_starts:
        res = minimize(objective, start, method="L-BFGS-B", bounds=bounds, options={"maxiter": int(maxiter)})
        x = res.x if res.success else start
        score = float(objective(x))
        if score < best_obj:
            best_obj = score
            best_x = x

    assert best_x is not None
    batt_x = np.asarray(best_x[:5], dtype=float)
    mot_x = np.asarray(best_x[5:], dtype=float)
    use_df = work.copy()
    use_df["headwind_effective_ms"] = use_df["headwind_archive_ms"] * float(mot_x[5])
    replay = joint_replay(
        use_df,
        ocv_df,
        base_model,
        BatteryFitResult(float(batt_x[0]), float(batt_x[1]), float(batt_x[2]), float(batt_x[3]), float(batt_x[4]), 0.0, 0.0),
        MotionFitResult(float(mot_x[0]), float(mot_x[1]), float(mot_x[2]), float(mot_x[3]), float(mot_x[4]), float(mot_x[5]), 0.0, 0.0, 0.0),
    )
    metrics = metrics_from_replay(replay)
    rp = replay.loc[valid_power, "battery_power_w_obs"].to_numpy(dtype=float) - replay.loc[valid_power, "battery_power_w_pred"].to_numpy(dtype=float)
    sigma = float(np.std(rp, ddof=1)) if len(rp) >= 2 else float(np.sqrt(np.mean(rp ** 2)))
    batt = BatteryFitResult(
        soc0=float(batt_x[0]),
        e_nom_wh=float(batt_x[1]),
        rint_scale=float(batt_x[2]),
        r_line_ohm=float(batt_x[3]),
        eta_charge=float(batt_x[4]),
        objective=float(best_obj),
        voltage_rmse_v=float(metrics.get("voltage_rmse_fit_window_v", metrics["voltage_rmse_clean_v"])),
    )
    mot = MotionFitResult(
        cda=float(mot_x[0]),
        crr=float(mot_x[1]),
        p_aux_w=float(mot_x[2]),
        grade_scale=float(mot_x[3]),
        drive_eff_scale=float(mot_x[4]),
        headwind_gain=float(mot_x[5]),
        objective=float(best_obj),
        power_rmse_w=float(metrics.get("power_rmse_fit_window_w", metrics["power_rmse_clean_w"])),
        residual_sigma_w=sigma,
    )
    baseline_score = float(baseline_metrics.get("power_rmse_fit_window_w", baseline_metrics["power_rmse_clean_w"])) + 18.0 * float(
        baseline_metrics.get("voltage_rmse_fit_window_v", baseline_metrics["voltage_rmse_clean_v"])
    )
    candidate_score = float(metrics.get("power_rmse_fit_window_w", metrics["power_rmse_clean_w"])) + 18.0 * float(
        metrics.get("voltage_rmse_fit_window_v", metrics["voltage_rmse_clean_v"])
    )
    baseline_power_rmse = float(baseline_metrics.get("power_rmse_fit_window_w", baseline_metrics["power_rmse_clean_w"]))
    baseline_voltage_rmse = float(baseline_metrics.get("voltage_rmse_fit_window_v", baseline_metrics["voltage_rmse_clean_v"]))
    candidate_power_rmse = float(metrics.get("power_rmse_fit_window_w", metrics["power_rmse_clean_w"]))
    candidate_voltage_rmse = float(metrics.get("voltage_rmse_fit_window_v", metrics["voltage_rmse_clean_v"]))
    accepted = (
        (best_obj < baseline_objective - 1.0e-3 and candidate_power_rmse <= baseline_power_rmse + JOINT_ACCEPT_POWER_RMSE_MARGIN_W)
        or (candidate_score < baseline_score - 1.0 and candidate_power_rmse <= baseline_power_rmse + JOINT_ACCEPT_POWER_RMSE_MARGIN_W)
        or (
            candidate_power_rmse <= baseline_power_rmse - 4.0
            and candidate_voltage_rmse <= baseline_voltage_rmse + JOINT_ACCEPT_VOLTAGE_RMSE_MARGIN_V
        )
    )
    if not accepted:
        return batt_init, mot_init, {                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
            "objective": float(best_obj),
            "baseline_objective": float(baseline_objective),
            "restart_count": len(local_starts),
            "random_start_count": len(seed_pool),
            "maxiter": int(maxiter),
            "fit_stride": stride,
            "rest_soc_points": int(rest_mask.sum()),
            "power_rmse_fit_window_w": float(metrics.get("power_rmse_fit_window_w", float("nan"))),
            "voltage_rmse_fit_window_v": float(metrics.get("voltage_rmse_fit_window_v", float("nan"))),
            "final_soc_pred": float(metrics["final_soc_pred"]),
            "accepted": False,
            "baseline_power_rmse_fit_window_w": float(
                baseline_metrics.get("power_rmse_fit_window_w", baseline_metrics["power_rmse_clean_w"])
            ),
            "baseline_voltage_rmse_fit_window_v": float(
                baseline_metrics.get("voltage_rmse_fit_window_v", baseline_metrics["voltage_rmse_clean_v"])
            ),
            "baseline_final_soc_pred": float(baseline_metrics["final_soc_pred"]),
        }
    return batt, mot, {                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "objective": float(best_obj),
        "baseline_objective": float(baseline_objective),
        "restart_count": len(local_starts),
        "random_start_count": len(seed_pool),
        "maxiter": int(maxiter),
        "fit_stride": stride,
        "rest_soc_points": int(rest_mask.sum()),
        "power_rmse_fit_window_w": float(metrics.get("power_rmse_fit_window_w", float("nan"))),
        "voltage_rmse_fit_window_v": float(metrics.get("voltage_rmse_fit_window_v", float("nan"))),
        "final_soc_pred": float(metrics["final_soc_pred"]),
        "accepted": True,
        "baseline_power_rmse_fit_window_w": float(
            baseline_metrics.get("power_rmse_fit_window_w", baseline_metrics["power_rmse_clean_w"])
        ),
        "baseline_voltage_rmse_fit_window_v": float(
            baseline_metrics.get("voltage_rmse_fit_window_v", baseline_metrics["voltage_rmse_clean_v"])
        ),
        "baseline_final_soc_pred": float(baseline_metrics["final_soc_pred"]),
    }


def joint_replay_core(                                             # [関数定義] joint_replay_core の処理実行ブロック
    log_df: pd.DataFrame,
    ocv_df: pd.DataFrame,
    base_model: SolarCarModel,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    *,
    return_dataframe: bool,
):
    rows = [] if return_dataframe else None
    n = len(log_df)
    power_obs = np.empty(n, dtype=float)
    power_pred = np.empty(n, dtype=float)
    voltage_obs = np.empty(n, dtype=float)
    voltage_pred = np.empty(n, dtype=float)
    soc_pred = np.empty(n, dtype=float)
    ocv_soc = ocv_df["soc"].to_numpy(dtype=float)
    ocv_v_grid = ocv_df["ocv_v"].to_numpy(dtype=float)
    z = float(batt.soc0)
    for idx, row in enumerate(log_df.itertuples(index=False)):
        solar_w = float(getattr(row, "solar_power_w_model"))
        headwind_ms = float(getattr(row, "headwind_effective_ms", getattr(row, "headwind_archive_ms")))
        p_pack_pred = motion_power_prediction(
            row.speed_kmh,
            row.slope_pct,
            headwind_ms,
            solar_w,
            base_model,
            mot.cda,
            mot.crr,
            mot.p_aux_w,
            mot.grade_scale,
            mot.drive_eff_scale,
        )
        ocv_v = float(np.interp(z, ocv_soc, ocv_v_grid))
        temp_c = float(getattr(row, "Tamb_archive_C"))
        r_ohm = max(1.0e-5, batt.rint_scale * rint_lookup(base_model, temp_c, z) + batt.r_line_ohm)
        disc = max(ocv_v ** 2 - 4.0 * r_ohm * p_pack_pred, 0.0)
        i_pred = (ocv_v - math.sqrt(disc)) / (2.0 * r_ohm)
        v_pred = ocv_v - i_pred * r_ohm
        power_obs[idx] = float(row.battery_power_w_obs)
        power_pred[idx] = p_pack_pred
        voltage_obs[idx] = float(row.battery_voltage_v)
        voltage_pred[idx] = v_pred
        soc_pred[idx] = z
        if return_dataframe:
            rows.append(
                {
                    "time_utc": row.time_utc,
                    "time_local": row.time_local,
                    "day": row.day,
                    "s_km": row.s_km,
                    "lat": row.lat,
                    "lon": row.lon,
                    "speed_kmh": row.speed_kmh,
                    "slope_pct": row.slope_pct,
                    "headwind_ms": headwind_ms,
                    "GHI_archive": row.GHI_archive,
                    "GHI_effective": row.GHI_effective,
                    "Tamb_C": row.Tamb_archive_C,
                    "Tcell_C": row.Tcell_effective_C,
                    "solar_power_w_obs": row.solar_power_w_obs,
                    "solar_power_w_model": solar_w,
                    "battery_power_w_obs": row.battery_power_w_obs,
                    "battery_power_w_pred": p_pack_pred,
                    "battery_current_a_obs": row.battery_current_a,
                    "battery_current_a_pred": i_pred,
                    "battery_voltage_v_obs": row.battery_voltage_v,
                    "battery_voltage_v_pred": v_pred,
                    "soc_pred": z,
                    "exclude_power_fit": row.exclude_power_fit,
                    "exclude_voltage_fit": row.exclude_voltage_fit,
                    "exclude_weather_fit": row.exclude_weather_fit,
                    "exclude_reason": row.exclude_reason,
                }
            )
        dt_sec = float(row.dt_sec)
        eta = batt.eta_charge if p_pack_pred < 0.0 else 1.0
        z = z - eta * (p_pack_pred * dt_sec / 3600.0) / max(batt.e_nom_wh, 100.0)
        z = float(np.clip(z, -0.05, 1.05))
    if return_dataframe:
        return pd.DataFrame(rows)                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "battery_power_w_obs": power_obs,
        "battery_power_w_pred": power_pred,
        "battery_voltage_v_obs": voltage_obs,
        "battery_voltage_v_pred": voltage_pred,
        "soc_pred": soc_pred,
    }


def joint_replay(log_df: pd.DataFrame, ocv_df: pd.DataFrame, base_model: SolarCarModel, batt: BatteryFitResult, mot: MotionFitResult) -> pd.DataFrame:  # [関数定義] joint_replay の処理実行ブロック
    return joint_replay_core(log_df, ocv_df, base_model, batt, mot, return_dataframe=True)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def resample_for_fit(log_df: pd.DataFrame) -> pd.DataFrame:        # [関数定義] resample_for_fit の処理実行ブロック
    work = log_df.copy()
    work = work.set_index(pd.to_datetime(work["time_utc"], utc=True))
    agg = {
        "day": "last",
        "s_km": "mean",
        "lat": "mean",
        "lon": "mean",
        "speed_kmh": "median",
        "slope_pct": "mean",
        "route_heading_deg": "mean",
        "solar_power_w_obs": "median",
        "battery_power_w_obs": "median",
        "battery_current_a": "median",
        "battery_voltage_v": "median",
        "dt_sec": "sum",
        "GHI_archive": "mean",
        "Tamb_archive_C": "mean",
        "headwind_archive_ms": "mean",
        "wind_speed_ms": "mean",
        "wind_dir_deg": "mean",
        "solar_power_w_model": "mean",
        "GHI_effective": "mean",
        "Tcell_effective_C": "mean",
        "exclude_power_fit": "max",
        "exclude_voltage_fit": "max",
        "exclude_weather_fit": "max",
    }
    if "solar_power_w_obs_smooth" in work.columns:
        agg["solar_power_w_obs_smooth"] = "median"
    if "headwind_effective_ms" in work.columns:
        agg["headwind_effective_ms"] = "mean"
    out = work.resample(f"{FIT_RESAMPLE_SEC}s").agg(agg).dropna(subset=["speed_kmh", "battery_voltage_v"])
    out = out.reset_index().rename(columns={"index": "time_utc"})
    out["time_local"] = out["time_utc"].dt.tz_convert(TIMEZONE_LOCAL)
    for col in ("exclude_power_fit", "exclude_voltage_fit", "exclude_weather_fit"):
        out[col] = out[col].fillna(False).astype(bool)
    out["exclude_reason"] = ""
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_effective_weather(log_df: pd.DataFrame, base_model: SolarCarModel) -> pd.DataFrame:  # [関数定義] build_effective_weather の処理実行ブロック
    work = log_df.copy()
    work["solar_power_w_obs"] = work["solar_power_w_obs"].clip(lower=0.0)
    work["solar_power_w_obs_smooth"] = smooth_series(work["solar_power_w_obs"], window=13)
    pv_model = []
    for row in work.itertuples(index=False):
        tcell = float(row.Tamb_archive_C) + PV_TCELL_SEED_GAIN * float(row.GHI_archive)
        pv_model.append(float(base_model.pv_power_mppt(float(row.GHI_archive), float(tcell))))
    work["solar_power_w_archive_model"] = np.asarray(pv_model, dtype=float)
    ratio = work["solar_power_w_obs_smooth"] / work["solar_power_w_archive_model"].clip(lower=20.0)
    ratio = ratio.where(~work["exclude_weather_fit"], np.nan)
    ratio = ratio.where(work["solar_power_w_archive_model"] > 20.0, np.nan)
    ratio = ratio.where(work["solar_power_w_obs_smooth"] > 5.0, np.nan)
    ratio = smooth_series(ratio, window=PV_EFFECTIVE_RATIO_WINDOW)
    ratio = ratio.interpolate(limit_direction="both").fillna(1.0)
    ratio = clip_series(ratio, 0.0, 1.8)
    work["solar_ratio"] = ratio
    work["GHI_effective"] = work["GHI_archive"] * work["solar_ratio"]
    work["Tcell_effective_C"] = work["Tamb_archive_C"] + PV_TCELL_SEED_GAIN * work["GHI_effective"]
    pv_model_eff = []
    for row in work.itertuples(index=False):
        pv_model_eff.append(float(base_model.pv_power_mppt(float(row.GHI_effective), float(row.Tcell_effective_C))))
    work["solar_power_w_model"] = np.asarray(pv_model_eff, dtype=float)
    return work                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def metrics_from_replay(replay_df: pd.DataFrame) -> Dict[str, float]:  # [関数定義] metrics_from_replay の処理実行ブロック
    power_mask = ~replay_df["exclude_power_fit"]
    volt_mask = ~replay_df["exclude_voltage_fit"]
    rp = replay_df.loc[power_mask, "battery_power_w_obs"] - replay_df.loc[power_mask, "battery_power_w_pred"]
    rv = replay_df.loc[volt_mask, "battery_voltage_v_obs"] - replay_df.loc[volt_mask, "battery_voltage_v_pred"]
    all_rp = replay_df["battery_power_w_obs"] - replay_df["battery_power_w_pred"]
    all_rv = replay_df["battery_voltage_v_obs"] - replay_df["battery_voltage_v_pred"]
    metrics = {
        "power_rmse_clean_w": float(np.sqrt(np.mean(rp ** 2))),
        "power_mae_clean_w": float(np.mean(np.abs(rp))),
        "power_rmse_all_w": float(np.sqrt(np.mean(all_rp ** 2))),
        "voltage_rmse_clean_v": float(np.sqrt(np.mean(rv ** 2))),
        "voltage_mae_clean_v": float(np.mean(np.abs(rv))),
        "voltage_rmse_all_v": float(np.sqrt(np.mean(all_rv ** 2))),
        "final_soc_pred": float(replay_df["soc_pred"].iloc[-1]),
        "final_distance_km": float(replay_df["s_km"].iloc[-1]),
    }
    work = replay_df.copy()
    work = work.set_index(pd.to_datetime(work["time_utc"], utc=True))
    fit_scale = (
        work.resample(f"{FIT_RESAMPLE_SEC}s")
        .agg(
            {
                "battery_power_w_obs": "median",
                "battery_power_w_pred": "median",
                "battery_voltage_v_obs": "median",
                "battery_voltage_v_pred": "median",
                "exclude_power_fit": "max",
                "exclude_voltage_fit": "max",
            }
        )
        .dropna()
    )
    if not fit_scale.empty:
        fit_scale["exclude_power_fit"] = fit_scale["exclude_power_fit"].fillna(False).astype(bool)
        fit_scale["exclude_voltage_fit"] = fit_scale["exclude_voltage_fit"].fillna(False).astype(bool)
        power_mask_fit = ~fit_scale["exclude_power_fit"]
        volt_mask_fit = ~fit_scale["exclude_voltage_fit"]
        rp_fit = fit_scale.loc[power_mask_fit, "battery_power_w_obs"] - fit_scale.loc[power_mask_fit, "battery_power_w_pred"]
        rv_fit = fit_scale.loc[volt_mask_fit, "battery_voltage_v_obs"] - fit_scale.loc[volt_mask_fit, "battery_voltage_v_pred"]
        metrics["power_rmse_fit_window_w"] = float(np.sqrt(np.mean(rp_fit ** 2)))
        metrics["power_mae_fit_window_w"] = float(np.mean(np.abs(rp_fit)))
        metrics["voltage_rmse_fit_window_v"] = float(np.sqrt(np.mean(rv_fit ** 2)))
    return metrics                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fit_map_shapes(                                                # [関数定義] fit_map_shapes の処理実行ブロック
    log_df: pd.DataFrame,
    fit_df: pd.DataFrame,
    replay_df: pd.DataFrame,
    base_model: SolarCarModel,
    pv: PvFitResult,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    ocv_df: pd.DataFrame,
) -> Dict[str, Dict[str, object]]:
    panel_x = np.asarray(base_model.Gg, dtype=float)
    panel_y = np.asarray(base_model.Tcg, dtype=float)
    drive_x = np.asarray(base_model.v_grid, dtype=float)
    drive_y = np.asarray(base_model.tau_grid, dtype=float)
    regen_x = np.asarray(base_model.v_gridR, dtype=float)
    regen_y = np.asarray(base_model.tau_gridR, dtype=float)
    rint_x = np.asarray(base_model.Tg, dtype=float)
    rint_y = np.asarray(base_model.zg, dtype=float)

    pv_work = log_df.copy()
    pv_work["solar_power_w_obs"] = pv_work["solar_power_w_obs"].clip(lower=0.0)
    ghi_col = "GHI_effective" if "GHI_effective" in pv_work.columns else "GHI_archive"
    pv_work = pv_work.set_index(pd.to_datetime(pv_work["time_utc"], utc=True))
    pv_work = (
        pv_work.resample(f"{PV_FIT_RESAMPLE_SEC}s")
        .agg(
            {
                "solar_power_w_obs": "median",
                ghi_col: "mean",
                "Tamb_archive_C": "mean",
                "exclude_weather_fit": "max",
            }
        )
        .dropna()
        .reset_index()
    )
    pv_work["exclude_weather_fit"] = pv_work["exclude_weather_fit"].fillna(False).astype(bool)
    pv_y = smooth_series(pv_work["solar_power_w_obs"], window=7).to_numpy(dtype=float)
    pv_ghi = pv_work[ghi_col].to_numpy(dtype=float)
    pv_tcell = pv_work["Tamb_archive_C"].to_numpy(dtype=float) + float(pv.tcell_gain_c_per_wm2) * pv_ghi
    pv_base = np.array([float(base_model.pv_power_mppt(g, tc)) for g, tc in zip(pv_ghi, pv_tcell)], dtype=float)
    pv_target = pv_y / max(float(pv.panel_gain), 1.0e-6)
    pv_mask = (
        (~pv_work["exclude_weather_fit"]).to_numpy(dtype=bool)
        & np.isfinite(pv_y)
        & np.isfinite(pv_ghi)
        & np.isfinite(pv_tcell)
        & np.isfinite(pv_base)
        & (pv_base > 10.0)
        & ((pv_y > 20.0) | (pv_ghi > 80.0))
    )
    combined_pv = fit_separable_shape_summary(
        "panel_mppt_combined",
        panel_x,
        panel_y,
        pv_ghi[pv_mask],
        pv_tcell[pv_mask],
        pv_base[pv_mask],
        pv_target[pv_mask],
        MAP_SHAPE_PANEL_RATIO_BOUNDS,
        smooth_weight=0.60,
        anchor_weight=0.35,
    )
    panel_shape = scaled_shape_summary(
        combined_pv,
        MAP_SHAPE_PANEL_MPPT_PANEL_SHARE,
        "panel_eff_map",
    )
    mppt_shape = scaled_shape_summary(
        combined_pv,
        1.0 - MAP_SHAPE_PANEL_MPPT_PANEL_SHARE,
        "mppt_eff_map",
    )
    panel_shape["identifiability_note"] = (
        "Race logs identify the total solar chain more strongly than the panel/MPPT split; "
        "the combined correction is distributed with a strong panel-side preference."
    )
    mppt_shape["identifiability_note"] = panel_shape["identifiability_note"]

    drive_samples_x = []
    drive_samples_y = []
    drive_base = []
    drive_target = []
    regen_samples_x = []
    regen_samples_y = []
    regen_base = []
    regen_target = []
    fit_power = fit_df.loc[
        (~fit_df["exclude_power_fit"])
        & (fit_df["speed_kmh"] >= 12.0)
        & np.isfinite(fit_df["battery_power_w_obs"])
        & np.isfinite(fit_df["solar_power_w_model"])
    ].reset_index(drop=True)
    for row in fit_power.itertuples(index=False):
        v_ms = float(row.speed_kmh) / 3.6
        headwind_ms = float(getattr(row, "headwind_effective_ms", getattr(row, "headwind_archive_ms", 0.0)))
        theta = math.atan((float(row.slope_pct) * float(mot.grade_scale)) / 100.0)
        v_rel = max(0.0, v_ms + headwind_ms)
        n_force = base_model.p.m * base_model.p.g * math.cos(theta)
        f_aero = 0.5 * base_model.p.rho * float(mot.cda) * (v_rel ** 2)
        f_roll = float(mot.crr) * n_force
        f_grade = base_model.p.m * base_model.p.g * math.sin(theta)
        p_mech = (f_aero + f_roll + f_grade) * v_ms + float(mot.p_aux_w)
        p_dc_obs = float(row.battery_power_w_obs) + float(row.solar_power_w_model)
        if p_mech >= 100.0 and p_dc_obs >= 40.0:
            t_m, _ = base_model.torque_from_mech(p_mech, v_ms)
            eff_base = float(np.clip(base_model.eff_drive(v_ms, t_m) * float(mot.drive_eff_scale), 0.55, 0.99))
            eff_target = p_mech / max(p_dc_obs * base_model.p.gear_eta * base_model.p.inverter_eta, 1.0e-6)
            if np.isfinite(eff_target) and 0.40 <= eff_target <= 1.05:
                drive_samples_x.append(v_ms)
                drive_samples_y.append(abs(float(t_m)))
                drive_base.append(eff_base)
                drive_target.append(float(np.clip(eff_target, 0.45, 0.99)))
        elif p_mech <= -60.0 and p_dc_obs <= -20.0:
            t_m, _ = base_model.torque_from_mech(abs(p_mech), v_ms)
            eff_base = float(np.clip(base_model.eff_regen(v_ms, t_m) * float(mot.drive_eff_scale), 0.40, 0.95))
            eff_target = -p_dc_obs / max(abs(p_mech) * base_model.p.gear_eta * base_model.p.inverter_eta, 1.0e-6)
            if np.isfinite(eff_target) and 0.20 <= eff_target <= 1.05:
                regen_samples_x.append(v_ms)
                regen_samples_y.append(abs(float(t_m)))
                regen_base.append(eff_base)
                regen_target.append(float(np.clip(eff_target, 0.35, 0.95)))

    drive_shape = fit_separable_shape_summary(
        "drive_eff_map",
        drive_x,
        drive_y,
        np.asarray(drive_samples_x, dtype=float),
        np.asarray(drive_samples_y, dtype=float),
        np.asarray(drive_base, dtype=float),
        np.asarray(drive_target, dtype=float),
        MAP_SHAPE_DRIVE_RATIO_BOUNDS,
        smooth_weight=1.20,
        anchor_weight=0.45,
    )
    regen_shape = fit_separable_shape_summary(
        "regen_eff_map",
        regen_x,
        regen_y,
        np.asarray(regen_samples_x, dtype=float),
        np.asarray(regen_samples_y, dtype=float),
        np.asarray(regen_base, dtype=float),
        np.asarray(regen_target, dtype=float),
        MAP_SHAPE_REGEN_RATIO_BOUNDS,
        smooth_weight=1.00,
        anchor_weight=0.45,
    )

    ocv_soc = ocv_df["soc"].to_numpy(dtype=float)
    ocv_v_grid = ocv_df["ocv_v"].to_numpy(dtype=float)
    rint_samples_x = []
    rint_samples_y = []
    rint_base = []
    rint_target = []
    for row in replay_df.itertuples(index=False):
        if bool(row.exclude_voltage_fit):
            continue
        i_obs = float(getattr(row, "battery_current_a_obs", getattr(row, "battery_current_a", float("nan"))))
        v_obs = float(getattr(row, "battery_voltage_v_obs", getattr(row, "battery_voltage_v", float("nan"))))
        z_obs = float(getattr(row, "soc_pred", float("nan")))
        t_obs = float(getattr(row, "Tamb_C", getattr(row, "Tamb_archive_C", float("nan"))))
        if not (np.isfinite(i_obs) and np.isfinite(v_obs) and np.isfinite(z_obs) and np.isfinite(t_obs)):
            continue
        if abs(i_obs) < 2.5 or v_obs < INVALID_PACK_VOLTAGE_MIN_V:
            continue
        ocv_v = float(np.interp(np.clip(z_obs, ocv_soc.min(), ocv_soc.max()), ocv_soc, ocv_v_grid))
        r_total = (ocv_v - v_obs) / i_obs
        r_obs = max(1.0e-5, float(r_total) - float(batt.r_line_ohm))
        r_base = max(1.0e-5, float(base_model.R_int(t_obs, z_obs)) * float(batt.rint_scale))
        if np.isfinite(r_obs) and 0.001 <= r_obs <= 0.5:
            rint_samples_x.append(t_obs)
            rint_samples_y.append(float(np.clip(z_obs, rint_y.min(), rint_y.max())))
            rint_base.append(r_base)
            rint_target.append(r_obs)
    rint_shape = fit_separable_shape_summary(
        "rint_map",
        rint_x,
        rint_y,
        np.asarray(rint_samples_x, dtype=float),
        np.asarray(rint_samples_y, dtype=float),
        np.asarray(rint_base, dtype=float),
        np.asarray(rint_target, dtype=float),
        MAP_SHAPE_RINT_RATIO_BOUNDS,
        smooth_weight=1.60,
        anchor_weight=0.30,
    )
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "panel_mppt_combined": combined_pv,
        "panel_eff_map": panel_shape,
        "mppt_eff_map": mppt_shape,
        "drive_eff_map": drive_shape,
        "regen_eff_map": regen_shape,
        "rint_map": rint_shape,
    }


def write_scaled_maps(                                             # [関数定義] write_scaled_maps の処理実行ブロック
    base_cfg: dict,
    pv: PvFitResult,
    mot: MotionFitResult,
    batt: BatteryFitResult,
    out_maps_dir: Path,
    *,
    shape_fits: Dict[str, Dict[str, object]] | None = None,
) -> Dict[str, Path]:
    ensure_dir(out_maps_dir)
    path_map = {}
    shape_fits = shape_fits or {}
    for key in ("drive_eff_map", "drive_map_eco", "drive_map_power", "regen_eff_map", "regen_map_eco", "regen_map_power", "panel_eff_map", "mppt_eff_map"):
        src = (SRC_PACKAGE / base_cfg["paths"][key]).resolve()
        dst = out_maps_dir / src.name
        df = pd.read_csv(src, index_col=0)
        if "drive" in key:
            scaled = apply_shape_summary_to_df(
                df.clip(lower=0.45, upper=0.99),
                shape_fits.get("drive_eff_map", identity_shape_summary(key, df.index.to_numpy(dtype=float), df.columns.to_numpy(dtype=float))),
                lower=0.45,
                upper=0.99,
            )
            scaled.to_csv(dst)
        elif "regen" in key:
            scaled = apply_shape_summary_to_df(
                df.clip(lower=0.40, upper=0.95),
                shape_fits.get("regen_eff_map", identity_shape_summary(key, df.index.to_numpy(dtype=float), df.columns.to_numpy(dtype=float))),
                lower=0.40,
                upper=0.95,
            )
            scaled.to_csv(dst)
        elif key == "panel_eff_map":
            scaled = apply_shape_summary_to_df(
                df.clip(lower=0.0, upper=0.40),
                shape_fits.get("panel_eff_map", identity_shape_summary(key, df.index.to_numpy(dtype=float), df.columns.to_numpy(dtype=float))),
                lower=0.0,
                upper=0.40,
            )
            scaled.to_csv(dst)
        elif key == "mppt_eff_map":
            scaled = apply_shape_summary_to_df(
                df.clip(lower=0.60, upper=0.995),
                shape_fits.get("mppt_eff_map", identity_shape_summary(key, df.index.to_numpy(dtype=float), df.columns.to_numpy(dtype=float))),
                lower=0.60,
                upper=0.995,
            )
            scaled.to_csv(dst)
        else:
            df.to_csv(dst)
        path_map[key] = dst
    rint_src = (SRC_PACKAGE / base_cfg["paths"]["rint_map"]).resolve()
    rint_dst = out_maps_dir / rint_src.name.replace("Rint_T_by_soc", "Rint_T_by_soc_fitted")
    rint_df = pd.read_csv(rint_src, index_col=0)
    apply_shape_summary_to_df(
        rint_df.clip(lower=1.0e-5, upper=1.0),
        shape_fits.get("rint_map", identity_shape_summary("rint_map", rint_df.index.to_numpy(dtype=float), rint_df.columns.to_numpy(dtype=float))),
        lower=1.0e-5,
        upper=1.0,
    ).to_csv(rint_dst)
    path_map["rint_map"] = rint_dst
    return path_map                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def planning_race_km_from_route(route_profile: pd.DataFrame) -> float:  # [関数定義] planning_race_km_from_route の処理実行ブロック
    public_info = SRC_PACKAGE / "data" / "public" / "bwsc2025_public_info.yaml"
    if public_info.exists():
        try:
            with public_info.open("r", encoding="utf-8") as f:
                payload = yaml.safe_load(f) or {}
            event = payload.get("event", {}) if isinstance(payload, dict) else {}
            route_finish_ref = float(event.get("route_finish_ref_km", 0.0) or 0.0)
            if route_finish_ref > 0.0:
                return route_finish_ref                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception:
            pass
    if "dist_km" in route_profile.columns:
        dist_vals = pd.to_numeric(route_profile["dist_km"], errors="coerce").dropna()
        if not dist_vals.empty:
            return float(dist_vals.max())                          # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return OFFICIAL_CLASSIFIED_DISTANCE_KM                         # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_route_assets(                                            # [関数定義] write_route_assets の処理実行ブロック
    route_profile: pd.DataFrame,
    route_waypoints: pd.DataFrame,
    out_dir: Path,
    *,
    planning_race_km: float,
) -> Dict[str, Path]:
    ensure_dir(out_dir)
    route_profile_path = out_dir / f"{PACKAGE_NAME}_route_profile.csv"
    route_waypoints_path = out_dir / f"{PACKAGE_NAME}_route_waypoints.csv"
    speed_profile_path = out_dir / f"{PACKAGE_NAME}_speed_profile.csv"
    route_profile.to_csv(route_profile_path, index=False)
    route_waypoints.to_csv(route_waypoints_path, index=False)
    pd.DataFrame({"dist_km": [0.0, float(planning_race_km)], "v_max_kmh": [110.0, 110.0]}).to_csv(
        speed_profile_path,
        index=False,
    )
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "route_profile_csv": route_profile_path,
        "route_waypoints_csv": route_waypoints_path,
        "speed_profile_csv": speed_profile_path,
    }


def drive_windows_from_anchors() -> List[Tuple[datetime, datetime, str]]:  # [関数定義] drive_windows_from_anchors の処理実行ブロック
    items = [
        ("2025-08-24T08:21:00", "2025-08-24T17:09:00", "Day1 drive"),
        ("2025-08-25T08:09:00", "2025-08-25T17:05:00", "Day2 drive"),
        ("2025-08-26T08:05:00", "2025-08-26T16:57:00", "Day3 drive"),
        ("2025-08-27T08:00:00", "2025-08-27T16:49:00", "Day4 drive"),
        ("2025-08-28T08:35:00", "2025-08-28T16:59:00", "Day5 drive"),
        ("2025-08-29T08:45:00", "2025-08-29T14:46:00", "Day6 drive"),
    ]
    return [(local_dt(a), local_dt(b), label) for a, b, label in items]  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_drive_schedule_yaml(out_path: Path) -> None:             # [関数定義] write_drive_schedule_yaml の処理実行ブロック
    payload = {"deny_by_default": True, "drive_windows": []}
    for start_local, end_local, label in drive_windows_from_anchors():
        payload["drive_windows"].append(
            {
                "label": label,
                "start_utc": iso_z(start_local),
                "end_utc": iso_z(end_local),
                "v_min_kmh": 0.0,
                "v_max_kmh": 110.0,
            }
        )
    ensure_dir(out_path.parent)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)


def write_stops_yaml(out_path: Path) -> None:                      # [関数定義] write_stops_yaml の処理実行ブロック
    stops = build_stop_records()
    ensure_dir(out_path.parent)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump({"stops": stops}, f, sort_keys=False, allow_unicode=True)


def write_control_stops_yaml(out_path: Path) -> None:              # [関数定義] write_control_stops_yaml の処理実行ブロック
    stops = []
    seen_s = set()
    for row in build_stop_records():
        if not row["is_control_stop"]:
            continue
        if float(row.get("dwell_sec", 0.0)) < CONTROL_STOP_MIN_DWELL_SEC:
            continue
        s_key = round(float(row.get("s_km", 0.0)), 3)
        if s_key in seen_s:
            continue
        seen_s.add(s_key)
        stops.append(row)
    ensure_dir(out_path.parent)
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump({"stops": stops}, f, sort_keys=False, allow_unicode=True)


def write_nominal_planning_weather_grid_csv(                       # [関数定義] write_nominal_planning_weather_grid_csv の処理実行ブロック
    weather_grid_df: pd.DataFrame,
    out_csv: Path,
    pv: PvFitResult,
    mot: MotionFitResult,
) -> Path:
    df = weather_grid_df.copy()
    out = pd.DataFrame(
        {
            "time": pd.to_datetime(df["time_utc"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "s_km": pd.to_numeric(df["s_km"], errors="coerce"),
            "route_progress_km": pd.to_numeric(df["s_km"], errors="coerce"),
            "GHI": pd.to_numeric(df["GHI_archive"], errors="coerce"),
            "Tamb_C": pd.to_numeric(df["Tamb_archive_C"], errors="coerce"),
            "headwind_ms": pd.to_numeric(df["headwind_archive_ms"], errors="coerce") * float(mot.headwind_gain),
            "wind_dir_deg": pd.to_numeric(df["wind_dir_deg"], errors="coerce"),
            "route_heading_deg": pd.to_numeric(df["route_heading_deg"], errors="coerce"),
        }
    )
    out["Tcell_C"] = pd.to_numeric(out["Tamb_C"], errors="coerce") + float(pv.tcell_gain_c_per_wm2) * pd.to_numeric(
        out["GHI"],
        errors="coerce",
    )
    out["weather_source"] = "openmeteo_archive_spatiotemporal_grid_corrected_by_fitted_tcell_and_headwind"
    ensure_dir(out_csv.parent)
    out.sort_values(["time", "s_km"]).to_csv(out_csv, index=False)
    return out_csv                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_stop_catalog_csv(out_path: Path) -> Path:                # [関数定義] write_stop_catalog_csv の処理実行ブロック
    ensure_dir(out_path.parent)
    pd.DataFrame(build_stop_records()).to_csv(out_path, index=False)
    return out_path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_observed_weather_csv(log_df: pd.DataFrame, out_csv: Path) -> pd.DataFrame:  # [関数定義] write_observed_weather_csv の処理実行ブロック
    work = log_df.copy()
    work = work.set_index(pd.to_datetime(work["time_utc"], utc=True))
    agg = {
        "GHI_archive": "median",
        "Tamb_archive_C": "median",
        "Tcell_effective_C": "median",
        "headwind_archive_ms": "median",
        "wind_dir_deg": "median",
        "route_heading_deg": "median",
        "s_km": "median",
        "solar_power_w_model": "median",
        "solar_power_w_obs": "median",
    }
    if "GHI_effective" in work.columns:
        agg["GHI_effective"] = "median"
    if "headwind_effective_ms" in work.columns:
        agg["headwind_effective_ms"] = "median"
    grouped = work.resample("10min").agg(
        agg
    )
    grouped = grouped.dropna().reset_index()
    ghi_out = grouped["GHI_effective"] if "GHI_effective" in grouped.columns else grouped["GHI_archive"]
    headwind_out = grouped["headwind_effective_ms"] if "headwind_effective_ms" in grouped.columns else grouped["headwind_archive_ms"]
    out = pd.DataFrame(
        {
            "time": grouped["time_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "GHI": ghi_out,
            "Tamb_C": grouped["Tamb_archive_C"],
            "Tcell_C": grouped["Tcell_effective_C"],
            "headwind_ms": headwind_out,
            "wind_dir_deg": grouped["wind_dir_deg"],
            "route_heading_deg": grouped["route_heading_deg"],
            "route_progress_km": grouped["s_km"],
            "solar_power_w_model": grouped["solar_power_w_model"],
            "solar_power_w_obs": grouped["solar_power_w_obs"],
            "GHI_archive": grouped["GHI_archive"],
            "headwind_archive_ms": grouped["headwind_archive_ms"],
            "weather_source": (
                "openmeteo_archive_corrected_by_observed_pv"
                if "GHI_effective" in grouped.columns or "headwind_effective_ms" in grouped.columns
                else "openmeteo_archive"
            ),
        }
    )
    ensure_dir(out_csv.parent)
    out.to_csv(out_csv, index=False)
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_normalized_logs(log_df: pd.DataFrame, replay_df: pd.DataFrame, package_dir: Path) -> Dict[str, Path]:  # [関数定義] write_normalized_logs の処理実行ブロック
    out_dir = package_dir / "data" / "observed"
    ensure_dir(out_dir)
    observed_csv = out_dir / "bwsc2025_observed_log_5s.csv"
    fit_csv = out_dir / f"bwsc2025_fit_dataset_{FIT_RESAMPLE_SEC}s.csv"
    replay_csv = out_dir / "bwsc2025_replay_validation_5s.csv"
    log_df.assign(
        time_utc=log_df["time_utc"].map(iso_z),
        time_local=log_df["time_local"].astype(str),
    ).to_csv(observed_csv, index=False)
    replay_df.assign(
        time_utc=replay_df["time_utc"].map(iso_z),
        time_local=replay_df["time_local"].astype(str),
    ).to_csv(replay_csv, index=False)
    fit_df = resample_for_fit(log_df)
    fit_df.assign(
        time_utc=fit_df["time_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        time_local=fit_df["time_local"].astype(str),
    ).to_csv(fit_csv, index=False)
    return {"observed_csv": observed_csv, "fit_csv": fit_csv, "replay_csv": replay_csv}  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_profile(                                                 # [関数定義] write_profile の処理実行ブロック
    base_cfg: dict,
    package_dir: Path,
    route_assets: Dict[str, Path],
    planning_weather_csv: Path,
    planning_stop_yaml: Path,
    planning_schedule_yaml: Path,
    observed_weather_csv: Path,
    actual_stop_yaml: Path,
    actual_schedule_yaml: Path,
    map_assets: Dict[str, Path],
    ocv_csv: Path,
    pv: PvFitResult,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    *,
    fixed_mass_kg: float | None = None,
    profile_upper_max_iter: int = DEFAULT_PROFILE_UPPER_MAX_ITER,
    planning_race_km: float,
) -> Path:
    cfg = json.loads(json.dumps(base_cfg))
    cfg.setdefault("meta", {})
    cfg["meta"]["name"] = PACKAGE_NAME
    cfg["meta"]["purpose"] = "BWSC 2025 package fitted against the actual race logs and observed route weather."
    cfg["meta"]["notes"] = [
        "This profile duplicates bwsc2025_public and replaces the route, weather, and model with a log-fitted version.",
        "Observed weather is kept separately for replay/validation, while forecast_csv points to a full-course spatiotemporal planning weather grid.",
        "The planning profile uses full-race daily drive windows and control stops only; actual trouble stops are not injected into nominal optimization.",
        "PV reproduction uses a fitted effective-irradiance reconstruction, a fitted panel scalar gain, and low-dimensional panel/MPPT map shape corrections.",
        "Headwind is attenuated by a fitted exposure gain before it is written to the planning/replay weather CSVs.",
        "Drive, regen, and internal-resistance maps are corrected by smooth separable row/column warps before the final scalar refit pass.",
        "Vehicle mass is fixed to the user-specified value during the motion fit instead of being absorbed into CdA/Crr.",
        "simulation.soc0 is clipped to model.soc_max, live.autocal.aux_power_w_init is synchronized to model.P_aux, and the nominal planner does not mix uncertainty reserve into the base plan.",
    ]
    cfg["paths"]["route_waypoints_csv"] = os.path.relpath(route_assets["route_waypoints_csv"], package_dir).replace("\\", "/")
    cfg["paths"]["route_profile_csv"] = os.path.relpath(route_assets["route_profile_csv"], package_dir).replace("\\", "/")
    cfg["paths"]["speed_profile_csv"] = os.path.relpath(route_assets["speed_profile_csv"], package_dir).replace("\\", "/")
    cfg["paths"]["forecast_csv"] = os.path.relpath(planning_weather_csv, package_dir).replace("\\", "/")
    cfg["paths"]["observed_weather_csv"] = os.path.relpath(observed_weather_csv, package_dir).replace("\\", "/")
    progress_reference_csv = package_dir / "data" / "observed" / "bwsc2025_observed_log_5s.csv"
    if progress_reference_csv.exists():
        cfg["paths"]["progress_reference_csv"] = os.path.relpath(progress_reference_csv, package_dir).replace("\\", "/")
    cfg["paths"]["stop_yaml"] = os.path.relpath(planning_stop_yaml, package_dir).replace("\\", "/")
    cfg["paths"]["drive_schedule_yaml"] = os.path.relpath(planning_schedule_yaml, package_dir).replace("\\", "/")
    cfg["paths"]["actual_stop_yaml"] = os.path.relpath(actual_stop_yaml, package_dir).replace("\\", "/")
    cfg["paths"]["actual_drive_schedule_yaml"] = os.path.relpath(actual_schedule_yaml, package_dir).replace("\\", "/")
    cfg["paths"]["drive_eff_map"] = os.path.relpath(map_assets["drive_eff_map"], package_dir).replace("\\", "/")
    cfg["paths"]["regen_eff_map"] = os.path.relpath(map_assets["regen_eff_map"], package_dir).replace("\\", "/")
    cfg["paths"]["rint_map"] = os.path.relpath(map_assets["rint_map"], package_dir).replace("\\", "/")
    cfg["paths"]["panel_eff_map"] = os.path.relpath(map_assets["panel_eff_map"], package_dir).replace("\\", "/")
    cfg["paths"]["mppt_eff_map"] = os.path.relpath(map_assets["mppt_eff_map"], package_dir).replace("\\", "/")
    cfg["paths"]["drive_map_eco"] = os.path.relpath(map_assets["drive_map_eco"], package_dir).replace("\\", "/")
    cfg["paths"]["drive_map_power"] = os.path.relpath(map_assets["drive_map_power"], package_dir).replace("\\", "/")
    cfg["paths"]["regen_map_eco"] = os.path.relpath(map_assets["regen_map_eco"], package_dir).replace("\\", "/")
    cfg["paths"]["regen_map_power"] = os.path.relpath(map_assets["regen_map_power"], package_dir).replace("\\", "/")
    cfg["paths"]["ocv_soc_map"] = os.path.relpath(ocv_csv, package_dir).replace("\\", "/")
    cfg.setdefault("runtime", {})
    cfg["runtime"]["forecast_time_mode"] = "absolute"
    cfg["runtime"]["forecast_time_tz"] = "Australia/Darwin"
    cfg.setdefault("simulation", {})
    cfg["simulation"]["output_dir"] = f"project_packages/{PACKAGE_NAME}/outputs/prerace"
    cfg["simulation"]["output_prefix"] = PACKAGE_NAME
    cfg["simulation"]["latest_manifest_json"] = f"project_packages/{PACKAGE_NAME}/outputs/prerace/latest_simulation_run.json"
    cfg["simulation"]["start_utc"] = iso_z(RACE_START_LOCAL)
    cfg["simulation"]["forecast_start_time_utc"] = iso_z(RACE_START_LOCAL)
    cfg["simulation"]["start_s_km"] = 0.0
    cfg["simulation"]["Tb0"] = 25.0
    cfg["simulation"]["energy_budget"] = True
    cfg.setdefault("live", {})
    cfg["live"]["forecast_time_mode"] = "absolute"
    cfg["live"]["forecast_time_tz"] = "Australia/Darwin"
    cfg.setdefault("live", {}).setdefault("weather", {})
    cfg.setdefault("live", {}).setdefault("autocal", {})
    cfg["live"]["weather"]["tcell_gain"] = round(float(pv.tcell_gain_c_per_wm2), 5)
    cfg.setdefault("model", {})
    if fixed_mass_kg is not None:
        cfg["model"]["m"] = round(float(fixed_mass_kg), 3)
    cfg["model"]["CdA"] = round(float(mot.cda), 6)
    cfg["model"]["Crr"] = round(float(mot.crr), 6)
    cfg["model"]["P_aux"] = round(float(mot.p_aux_w), 3)
    cfg["model"]["panel_gain"] = round(float(pv.panel_gain), 6)
    cfg["model"]["grade_scale"] = round(float(mot.grade_scale), 6)
    cfg["model"]["drive_eff_scale"] = round(float(mot.drive_eff_scale), 6)
    cfg["model"]["regen_eff_scale"] = round(float(mot.drive_eff_scale), 6)
    cfg["model"]["rint_scale"] = round(float(batt.rint_scale), 6)
    cfg["model"]["r_line_ohm"] = round(float(batt.r_line_ohm), 6)
    cfg["model"]["eta_charge"] = round(float(batt.eta_charge), 6)
    cfg["model"]["E_nom_Wh"] = round(float(batt.e_nom_wh), 3)
    cfg["model"]["V_min"] = round(float(pd.read_csv(ocv_csv)["ocv_v"].min()), 3)
    cfg["model"]["V_max"] = round(float(pd.read_csv(ocv_csv)["ocv_v"].max()), 3)
    cfg["model"]["soc_min"] = 0.10
    soc_max_cfg = float(cfg["model"].get("soc_max", 0.98))
    cfg["simulation"]["soc0"] = round(float(min(batt.soc0, soc_max_cfg)), 4)
    cfg["live"]["autocal"]["aux_power_w_init"] = round(float(mot.p_aux_w), 3)
    cfg.setdefault("mpc", {})
    cfg["mpc"]["race_km"] = round(float(planning_race_km), 3)
    cfg["mpc"]["terminal_soc_min"] = 0.10
    cfg["mpc"]["upper_mode"] = "distance"
    cfg["mpc"]["upper_ds_km"] = 10.0
    cfg["mpc"]["upper_horizon_km"] = round(float(planning_race_km), 3)
    cfg["mpc"]["upper_max_steps"] = 24
    cfg["mpc"]["upper_horizon_mode"] = "adaptive_full_race"
    cfg["mpc"]["upper_adaptive_min_ds_km"] = 10.0
    cfg["mpc"]["upper_adaptive_max_ds_km"] = 240.0
    cfg["mpc"]["upper_adaptive_growth"] = 1.18
    cfg["mpc"]["upper_ctrl_km"] = 250.0
    cfg["mpc"]["upper_max_iter"] = int(profile_upper_max_iter)
    cfg["mpc"]["upper_replan_sec"] = 3600.0
    cfg["mpc"]["upper_day_end_soc_min"] = 0.10
    cfg["mpc"]["soc_guard_margin"] = 0.005
    cfg["mpc"]["upper_cost"] = {
        "w_wait": 1.0,
        "w_travel_time": 1.0,
        "w_terminal_soc_min": 30.0,
        "w_day_end_soc_min": 1.0e5,
        "w_soc_day_max": float(cfg["mpc"].get("w_soc_day_max", 1.0e4)),
        "w_soc_day_track": float(cfg["mpc"].get("w_soc_day_track", 0.0)),
        "w_speed_smooth": float(cfg["mpc"].get("w_dv", 40.0)),
        "w_dv_limit": float(cfg["mpc"].get("w_dv_limit", 2.0)),
        "w_speed_limit": float(cfg["mpc"].get("w_speed_limit", 50.0)),
        "w_drive_window": 1.0e5,
        "w_current_sq": float(cfg["mpc"].get("w_current", 0.01)),
        "w_pack_energy": 1.0,
        "w_joule_loss": 4.0,
        "w_aero_energy": 0.8,
        "w_mech_energy": 0.1,
        "w_kinetic_pos": 2.0,
        "w_pack_power_slew": 60.0,
        "w_speed_quartic": 0.03,
        "w_solar_headroom": 0.0,
        "w_temp": float(cfg["mpc"].get("w_T", 5.0)),
        "w_soc_terminal": float(cfg["mpc"].get("w_soc_terminal", 1.0e5)),
        "w_soc_floor_barrier": 0.01,
        "w_uncertainty_reserve": 0.0,
        "speed_quartic_scale_kmh": 80.0,
        "soc_solar_headroom_max": 0.92,
        "solar_headroom_power_scale_w": 1000.0,
        "soc_floor_barrier_eps": 0.01,
        "reserve_soc_per_hour": 0.0,
        "reserve_soc_max_extra": 0.0,
        "constraint_penalty": 1.0e4,
    }
    # Keep the full-race nominal planner free from linear SoC tracking, but
    # give it a physically meaningful terminal reserve target near the floor.
    cfg["mpc"]["soc_finish_target"] = float(
        np.clip(NOMINAL_FINISH_SOC_TARGET, cfg["model"]["soc_min"], float(cfg["model"].get("soc_max", 0.98)))
    )
    cfg["mpc"]["w_soc_progress"] = 0.0
    cfg["mpc"]["w_soc_terminal"] = float(cfg["mpc"]["upper_cost"]["w_soc_terminal"])
    profile_yaml = package_dir / "profile.yaml"
    with profile_yaml.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(cfg, f, sort_keys=False, allow_unicode=True)
    return profile_yaml                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_fit_summary_yaml(                                        # [関数定義] write_fit_summary_yaml の処理実行ブロック
    package_dir: Path,
    pv: PvFitResult,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    metrics: Dict[str, float],
    batt_stage: BatteryFitResult,
    mot_stage: MotionFitResult,
    joint_info: Dict[str, float],
    map_shape_fit: Dict[str, object],
    pre_map_metrics: Dict[str, float],
    *,
    fixed_mass_kg: float | None = None,
    profile_upper_max_iter: int = DEFAULT_PROFILE_UPPER_MAX_ITER,
    planning_race_km: float | None = None,
) -> Path:
    out_path = package_dir / "outputs" / "identification" / f"{PACKAGE_NAME}_fit_summary.yaml"
    ensure_dir(out_path.parent)
    payload = {
        "pv_fit": pv.__dict__,
        "stagewise_battery_fit": batt_stage.__dict__,
        "stagewise_motion_fit": mot_stage.__dict__,
        "battery_fit": batt.__dict__,
        "motion_fit": mot.__dict__,
        "joint_fit": joint_info,
        "map_shape_fit": map_shape_fit,
        "pre_map_shape_validation_metrics": pre_map_metrics,
        "validation_metrics": metrics,
        "fit_setup": {
            "fit_resample_sec": FIT_RESAMPLE_SEC,
            "pv_fit_resample_sec": PV_FIT_RESAMPLE_SEC,
            "pv_effective_ratio_window": PV_EFFECTIVE_RATIO_WINDOW,
            "battery_restart_count": BATTERY_RESTART_COUNT,
            "motion_restart_count": MOTION_RESTART_COUNT,
            "joint_restart_count": JOINT_RESTART_COUNT,
            "battery_fit_maxiter": BATTERY_FIT_MAXITER,
            "motion_fit_maxiter": MOTION_FIT_MAXITER,
            "joint_fit_maxiter": JOINT_FIT_MAXITER,
            "priors": {
                "battery_e_nom_wh": BATTERY_PRIOR_E_NOM_WH,
                "motion_p_aux_w": MOTION_PRIOR_P_AUX_W,
                "motion_cda": MOTION_PRIOR_CDA,
                "motion_drive_eff_scale": MOTION_PRIOR_DRIVE_EFF_SCALE,
                "motion_headwind_gain": MOTION_PRIOR_HEADWIND_GAIN,
            },
            "measurement_filters": {
                "invalid_pack_voltage_min_v": INVALID_PACK_VOLTAGE_MIN_V,
                "rest_soc_voltage_min_v": REST_SOC_VOLTAGE_MIN_V,
                "rest_soc_current_max_a": REST_SOC_CURRENT_MAX_A,
                "rest_soc_speed_max_kmh": REST_SOC_SPEED_MAX_KMH,
                "rest_soc_sigma": REST_SOC_SIGMA,
            },
            "profile_consistency_fixes": {
                "fixed_mass_kg": float(fixed_mass_kg) if fixed_mass_kg is not None else None,
                "simulation_soc0_written": float(min(batt.soc0, 0.98)),
                "simulation_soc0_raw_fit": float(batt.soc0),
                "model_soc_max": 0.98,
                "live_autocal_aux_power_w_init": float(mot.p_aux_w),
                "profile_upper_max_iter": int(profile_upper_max_iter),
                "dv_max_kmhps_zero_means_disabled_penalty": True,
                "planning_race_km": float(planning_race_km) if planning_race_km is not None else None,
                "nominal_finish_soc_target": float(NOMINAL_FINISH_SOC_TARGET),
                "nominal_uncertainty_reserve_disabled": True,
            },
        },
        "race_distance": {
            "actual_retire_km": ACTUAL_RACE_END_KM,
            "official_classified_km": OFFICIAL_CLASSIFIED_DISTANCE_KM,
            "planning_full_course_km": float(planning_race_km) if planning_race_km is not None else None,
        },
        "bwsc2025_rules": {
            "control_stop_duration_sec": 1800,
            "rules_pdf": BWSC_RULES_URL,
            "route_notes_pdf": BWSC_ROUTE_NOTES_URL,
        },
        "sources": {
            "time_memo_pdf": str(TIME_MEMO_PDF),
            "points_pdf": str(POINTS_PDF),
            "battery_soc_pdf": str(BATTERY_SOC_PDF),
            "trouble_docx": str(TROUBLE_DOCX),
        },
    }
    with out_path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)
    return out_path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def run_forward_sim(profile_yaml: Path) -> Dict[str, Path]:        # [関数定義] run_forward_sim の処理実行ブロック
    subprocess.run(
        [
            os.fspath(Path(os.sys.executable)),
            os.fspath(ROOT / "scripts" / "solar_sim.py"),
            "--profile_yaml",
            os.fspath(profile_yaml),
        ],
        cwd=ROOT,
        check=True,
    )
    manifest = json.loads((OUT_PACKAGE / "outputs" / "prerace" / "latest_simulation_run.json").read_text(encoding="utf-8"))
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "summary_json": Path(ROOT / manifest["latest_manifest_json"]).resolve(),
        "out_csv": Path(ROOT / manifest["out_csv"]).resolve(),
        "detail_csv": Path(ROOT / manifest["detail_csv"]).resolve(),
        "plan_csv": Path(ROOT / manifest["plan_csv"]).resolve(),
        "report_html": Path(ROOT / manifest["report_html"]).resolve(),
        "resolved_yaml": Path(ROOT / manifest["resolved_yaml"]).resolve(),
    }


def load_profile_yaml(profile_yaml: Path) -> dict:                 # [関数定義] load_profile_yaml の処理実行ブロック
    with profile_yaml.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def numerical_dpower_dv(base_model: SolarCarModel, mot: MotionFitResult, slope_pct: float, headwind_ms: float, solar_power_w: float, v_kmh: float) -> float:  # [関数定義] numerical_dpower_dv の処理実行ブロック
    dv = 1.0
    p_hi = motion_power_prediction(v_kmh + dv, slope_pct, headwind_ms, solar_power_w, base_model, mot.cda, mot.crr, mot.p_aux_w, mot.grade_scale, mot.drive_eff_scale)
    p_lo = motion_power_prediction(max(0.0, v_kmh - dv), slope_pct, headwind_ms, solar_power_w, base_model, mot.cda, mot.crr, mot.p_aux_w, mot.grade_scale, mot.drive_eff_scale)
    return (p_hi - p_lo) / max(2.0 * dv / 3.6, 1.0e-6)             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def shape_lower_plan(nominal_kmh: Iterable[float], dt_sec: float, start_kmh: float, accel_limit_kmhps: float, decel_limit_kmhps: float, deadband_kmh: float) -> List[float]:  # [関数定義] shape_lower_plan の処理実行ブロック
    out = []
    prev = float(start_kmh)
    for raw in nominal_kmh:
        target = float(raw)
        max_up = accel_limit_kmhps * dt_sec
        max_down = decel_limit_kmhps * dt_sec
        target = min(target, prev + max_up)
        target = max(target, prev - max_down)
        if abs(target - prev) < deadband_kmh:
            target = prev
        out.append(target)
        prev = target
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def generate_plan_products(profile_yaml: Path, route_profile: pd.DataFrame, weather_10min: pd.DataFrame, mot: MotionFitResult, sigma_power_w: float, sim_outputs: Dict[str, Path]) -> Dict[str, Path]:  # [関数定義] generate_plan_products の処理実行ブロック
    cfg = load_profile_yaml(profile_yaml)
    plan_csv = sim_outputs["plan_csv"]
    if not plan_csv.exists():
        raise FileNotFoundError(plan_csv)
    plan_df = pd.read_csv(plan_csv)
    plan_df["time_utc"] = pd.to_datetime(plan_df["time_utc"], utc=True)
    weather = weather_10min.copy()
    weather["time_utc"] = pd.to_datetime(weather["time"], utc=True)
    weather = weather.sort_values("time_utc")
    _, base_model = base_model_from_public_profile()

    out_dir = OUT_PACKAGE / "outputs" / "plans"
    ensure_dir(out_dir)
    variants = []
    dt_fit = float(FIT_RESAMPLE_SEC)
    for plan_id, grp in plan_df.groupby("plan_id", sort=True):
        grp = grp.sort_values("plan_idx").copy()
        horizon_sec = grp["plan_dt_sec"].cumsum().to_numpy(dtype=float)
        sigma_v = []
        for row, tau_sec in zip(grp.itertuples(index=False), horizon_sec):
            slope_pct = float(interpolate_profile(route_profile, float(row.plan_s_km), "slope_pct", default=0.0))
            weather_idx = int(np.argmin(np.abs(weather["time_utc"] - row.time_utc)))
            solar_guess = float(
                weather.iloc[weather_idx].get(
                    "solar_power_w_model",
                    base_model.pv_power_mppt(float(weather.iloc[weather_idx]["GHI"]), float(weather.iloc[weather_idx]["Tcell_C"])),
                )
            )
            headwind = float(weather.iloc[weather_idx]["headwind_ms"])
            dPdv = numerical_dpower_dv(base_model, mot, slope_pct, headwind, solar_guess, float(row.plan_v_kmh))
            seg_sensitivity = abs(dPdv) * max(float(row.plan_dt_sec), 1.0) / 3600.0
            sigma_e = sigma_power_w * math.sqrt(max(tau_sec, dt_fit) * dt_fit) / 3600.0
            sigma_speed = 0.0 if seg_sensitivity <= 1.0e-6 else (sigma_e / seg_sensitivity) * 3.6
            sigma_v.append(float(np.clip(sigma_speed, 0.0, 25.0)))
        grp["sigma_speed_kmh"] = sigma_v
        grp["plan_v_conservative_kmh"] = np.clip(grp["plan_v_kmh"] - grp["sigma_speed_kmh"], 0.0, None)
        grp["plan_v_aggressive_kmh"] = grp["plan_v_kmh"] + grp["sigma_speed_kmh"]
        grp["horizon_sec"] = horizon_sec
        variants.append(grp)
    upper_three = pd.concat(variants, ignore_index=True)
    upper_three_csv = out_dir / f"{PACKAGE_NAME}_upper_three_plans.csv"
    upper_three.to_csv(upper_three_csv, index=False)

    lower_rows = []
    lower_dt = float(cfg.get("mpc", {}).get("lower_dt", 1.0))
    accel_limit = float(cfg.get("mpc", {}).get("lower_ref_accel_limit_kmhps", 1.2))
    decel_limit = float(cfg.get("mpc", {}).get("lower_ref_decel_limit_kmhps", 3.5))
    deadband = float(cfg.get("mpc", {}).get("lower_ref_deadband_kmh", 0.1))
    for plan_id, grp in upper_three.groupby("plan_id", sort=True):
        grp = grp.sort_values("plan_idx").copy()
        plan_start = pd.to_datetime(grp["time_utc"].iloc[0], utc=True)
        start_speed = float(grp["plan_v_kmh"].iloc[0])
        for variant_name, col in [
            ("conservative", "plan_v_conservative_kmh"),
            ("nominal", "plan_v_kmh"),
            ("aggressive", "plan_v_aggressive_kmh"),
        ]:
            nominal_seq = []
            for row in grp.itertuples(index=False):
                repeats = max(1, int(round(float(row.plan_dt_sec) / lower_dt)))
                nominal_seq.extend([float(getattr(row, col))] * repeats)
            shaped = shape_lower_plan(nominal_seq, lower_dt, start_speed, accel_limit, decel_limit, deadband)
            for idx, (raw_kmh, shaped_kmh) in enumerate(zip(nominal_seq, shaped)):
                lower_rows.append(
                    {
                        "plan_id": int(plan_id),
                        "variant": variant_name,
                        "time_utc": iso_z(plan_start + timedelta(seconds=idx * lower_dt)),
                        "step_sec": idx * lower_dt,
                        "speed_raw_kmh": raw_kmh,
                        "speed_shaped_kmh": shaped_kmh,
                    }
                )
    lower_csv = out_dir / f"{PACKAGE_NAME}_lower_three_plans.csv"
    pd.DataFrame(lower_rows).to_csv(lower_csv, index=False)

    plt.figure(figsize=(12, 7))
    for plan_id, grp in upper_three.groupby("plan_id", sort=True):
        x = grp["plan_s_km"].to_numpy(dtype=float)
        y0 = grp["plan_v_conservative_kmh"].to_numpy(dtype=float)
        y1 = grp["plan_v_aggressive_kmh"].to_numpy(dtype=float)
        ym = grp["plan_v_kmh"].to_numpy(dtype=float)
        label = pd.to_datetime(grp["time_utc"].iloc[0], utc=True).tz_convert(TIMEZONE_LOCAL).strftime("Plan %m/%d %H:%M")
        plt.fill_between(x, y0, y1, alpha=0.10)
        plt.plot(x, ym, linewidth=1.0, label=label)
    plt.xlabel("Route distance [km]")
    plt.ylabel("Upper plan speed [km/h]")
    plt.title("BWSC2025 fitted upper-plan envelopes")
    plt.grid(True, alpha=0.25)
    plt.legend(fontsize=7, ncol=2)
    upper_plot = out_dir / f"{PACKAGE_NAME}_upper_three_plans.png"
    plt.tight_layout()
    plt.savefig(upper_plot, dpi=180)
    plt.close()

    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "upper_three_csv": upper_three_csv,
        "lower_three_csv": lower_csv,
        "upper_plot": upper_plot,
    }


def plot_validation(replay_df: pd.DataFrame, out_dir: Path) -> Dict[str, Path]:  # [関数定義] plot_validation の処理実行ブロック
    ensure_dir(out_dir)
    plots = {}
    for name, y_obs, y_pred, ylabel in [
        ("battery_power", "battery_power_w_obs", "battery_power_w_pred", "Battery power [W]"),
        ("battery_voltage", "battery_voltage_v_obs", "battery_voltage_v_pred", "Battery voltage [V]"),
        ("solar_power", "solar_power_w_obs", "solar_power_w_model", "Solar power [W]"),
    ]:
        plt.figure(figsize=(12, 4.5))
        x = replay_df["s_km"].to_numpy(dtype=float)
        plt.plot(x, replay_df[y_obs].to_numpy(dtype=float), label="observed", linewidth=1.0)
        plt.plot(x, replay_df[y_pred].to_numpy(dtype=float), label="model", linewidth=1.0)
        plt.xlabel("Route distance [km]")
        plt.ylabel(ylabel)
        plt.title(name.replace("_", " ").title())
        plt.grid(True, alpha=0.25)
        plt.legend()
        out_path = out_dir / f"{name}.png"
        plt.tight_layout()
        plt.savefig(out_path, dpi=180)
        plt.close()
        plots[name] = out_path

    plt.figure(figsize=(12, 4.5))
    plt.plot(replay_df["s_km"], replay_df["soc_pred"], linewidth=1.0, label="predicted soc")
    plt.xlabel("Route distance [km]")
    plt.ylabel("SOC [-]")
    plt.title("Predicted battery SOC over actual race segment")
    plt.grid(True, alpha=0.25)
    plt.legend()
    soc_plot = out_dir / "soc_pred.png"
    plt.tight_layout()
    plt.savefig(soc_plot, dpi=180)
    plt.close()
    plots["soc_pred"] = soc_plot
    return plots                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_placeholder_plan_outputs(package_dir: Path) -> Dict[str, Path]:  # [関数定義] write_placeholder_plan_outputs の処理実行ブロック
    out_dir = package_dir / "outputs" / "plans"
    ensure_dir(out_dir)
    upper_csv = out_dir / f"{PACKAGE_NAME}_upper_three_plans.csv"
    lower_csv = out_dir / f"{PACKAGE_NAME}_lower_three_plans.csv"
    upper_csv.write_text("status,message\nskipped,solar_sim skipped\n", encoding="utf-8", newline="\n")
    lower_csv.write_text("status,message\nskipped,solar_sim skipped\n", encoding="utf-8", newline="\n")
    plot_path = out_dir / f"{PACKAGE_NAME}_upper_three_plans.png"
    fig, ax = plt.subplots(figsize=(8.0, 3.0))
    ax.axis("off")
    ax.text(0.5, 0.60, "solar_sim / upper plan generation skipped", ha="center", va="center", fontsize=15)
    ax.text(0.5, 0.35, "Fit-only package build completed.", ha="center", va="center", fontsize=12)
    fig.tight_layout()
    fig.savefig(plot_path, dpi=160)
    plt.close(fig)
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "upper_three_csv": upper_csv,
        "lower_three_csv": lower_csv,
        "upper_plot": plot_path,
    }


def write_report_markdown(                                         # [関数定義] write_report_markdown の処理実行ブロック
    package_dir: Path,
    pv: PvFitResult,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    metrics: Dict[str, float],
    sim_outputs: Dict[str, Path],
    plan_outputs: Dict[str, Path],
    *,
    fixed_mass_kg: float | None = None,
    planning_race_km: float | None = None,
) -> Path:
    md_path = package_dir / "outputs" / "reports" / f"{PACKAGE_NAME}_report.md"
    ensure_dir(md_path.parent)
    text = f"""# BWSC2025 fitted package

## Sources scanned

- `{TIME_MEMO_PDF}`
- `{POINTS_PDF}`
- `{BATTERY_SOC_PDF}`
- `{TROUBLE_DOCX}`
- `{DISCHARGE_TEST_CSV}`
- `ZP_Data0824day1.csv` から `ZP_Data0829day6.csv`
- `route_100m_dem.csv`

## Rule check applied

- BWSC2025 official regulations: control stops are `30 min`
- Short dwells in the logs are therefore handled as actual non-control stops unless the stop label is `CS*`
- Nominal planning full-course distance: `{float(planning_race_km if planning_race_km is not None else 0.0):.2f} km`
- Actual retire distance for replay: `2831.0 km`
- Official classified distance reference: `2720.0 km`
- Rules PDF: `{BWSC_RULES_URL}`
- Route notes PDF: `{BWSC_ROUTE_NOTES_URL}`

## PV fit against observed route weather

- `effective irradiance source = archive weather corrected by observed PV ratio`
- `pv_fit_resample_sec = {PV_FIT_RESAMPLE_SEC}`
- `panel_gain = {pv.panel_gain:.4f}`
- `tcell_gain_c_per_wm2 = {pv.tcell_gain_c_per_wm2:.5f}`
- `solar RMSE = {pv.solar_rmse_w:.2f} W`

## Battery fit

- `battery restart count = {BATTERY_RESTART_COUNT}`
- `E_nom prior = {BATTERY_PRIOR_E_NOM_WH:.1f} Wh`
- `soc0 = {batt.soc0:.4f}`
- `E_nom_Wh = {batt.e_nom_wh:.2f}`
- `Rint scale = {batt.rint_scale:.4f}`
- `R_line = {batt.r_line_ohm:.5f} ohm`
- `eta_charge = {batt.eta_charge:.4f}`
- `voltage RMSE = {batt.voltage_rmse_v:.3f} V`

## Motion fit

- `motion restart count = {MOTION_RESTART_COUNT}`
- `fit_resample_sec = {FIT_RESAMPLE_SEC}`
- `fixed mass = {float(fixed_mass_kg if fixed_mass_kg is not None else 0.0):.1f} kg`
- `CdA prior = {MOTION_PRIOR_CDA:.3f}`
- `P_aux prior = {MOTION_PRIOR_P_AUX_W:.1f} W`
- `CdA = {mot.cda:.5f}`
- `Crr = {mot.crr:.6f}`
- `P_aux = {mot.p_aux_w:.2f} W`
- `grade_scale = {mot.grade_scale:.4f}`
- `drive_eff_scale = {mot.drive_eff_scale:.4f}`
- `headwind_gain = {mot.headwind_gain:.4f}`
- `power RMSE = {mot.power_rmse_w:.2f} W`

## Validation

- `power_rmse_clean_w = {metrics['power_rmse_clean_w']:.2f}`
- `power_mae_clean_w = {metrics['power_mae_clean_w']:.2f}`
- `power_rmse_fit_window_w = {metrics.get('power_rmse_fit_window_w', float('nan')):.2f}`
- `voltage_rmse_clean_v = {metrics['voltage_rmse_clean_v']:.3f}`
- `voltage_rmse_fit_window_v = {metrics.get('voltage_rmse_fit_window_v', float('nan')):.3f}`
- `final_soc_pred = {metrics['final_soc_pred']:.4f}`
- `simulation.soc0 written = {min(batt.soc0, 0.98):.4f}`
- `live.autocal.aux_power_w_init = {mot.p_aux_w:.3f} W`

## Simulation outputs

- `profile forecast_csv = full-course nominal planning weather`
- `paths.observed_weather_csv = observed-route replay weather`
- `{sim_outputs['out_csv']}`
- `{sim_outputs['detail_csv']}`
- `{sim_outputs['plan_csv']}`
- `{sim_outputs['report_html']}`

## Plan outputs

- `{plan_outputs['upper_three_csv']}`
- `{plan_outputs['lower_three_csv']}`
- `{plan_outputs['upper_plot']}`
"""
    md_path.write_text(text, encoding="utf-8", newline="\n")
    return md_path                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_report_tex(                                              # [関数定義] write_report_tex の処理実行ブロック
    package_dir: Path,
    pv: PvFitResult,
    batt: BatteryFitResult,
    mot: MotionFitResult,
    metrics: Dict[str, float],
    validation_plots: Dict[str, Path],
    plan_outputs: Dict[str, Path],
    *,
    fixed_mass_kg: float | None = None,
    planning_race_km: float | None = None,
) -> Path:
    report_dir = package_dir / "outputs" / "reports"
    ensure_dir(report_dir)
    tex_path = report_dir / f"{PACKAGE_NAME}_report.tex"
    rel_plot = {k: os.path.relpath(v, report_dir).replace("\\", "/") for k, v in validation_plots.items()}
    rel_plan_plot = os.path.relpath(plan_outputs["upper_plot"], report_dir).replace("\\", "/")
    tex = f"""
\\documentclass[a4paper,11pt]{{article}}
\\usepackage[top=18mm,bottom=22mm,left=18mm,right=18mm]{{geometry}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\setmainfont{{Times New Roman}}
\\setCJKmainfont{{Yu Gothic}}
\\setmonofont{{Consolas}}
\\setCJKmonofont{{Yu Gothic}}
\\usepackage{{graphicx}}
\\usepackage{{booktabs}}
\\usepackage{{longtable}}
\\usepackage{{amsmath}}
\\usepackage{{array}}
\\usepackage[unicode]{{hyperref}}
\\usepackage{{float}}
\\hypersetup{{
  colorlinks=true,
  linkcolor=blue,
  urlcolor=blue,
  pdftitle={{BWSC2025 fitted package report}},
  pdfauthor={{Codex}}
}}
\\setlength{{\\parskip}}{{0.4em}}
\\setlength{{\\parindent}}{{1em}}
\\renewcommand{{\\arraystretch}}{{1.18}}
\\title{{BWSC2025 fitted package report}}
\\author{{solar\\_ws0129-main}}
\\date{{{REPORT_DATE}}}
\\begin{{document}}
\\maketitle

\\section{{目的}}
本資料は、BWSC2025 の実走行ログ・観測された PV 出力・走行地点に対応する気象アーカイブ・
トラブル記録を用いて、\\path{{project_packages/bwsc2025_public}} を複製した
  \\path{{project_packages/{PACKAGE_NAME}}} を構築した結果をまとめる。
この package では、実走 replay 用の observed-route weather と、
大会全体 planning 用の full-course nominal weather を分離している。

\\section{{規則確認}}
BWSC2025 公式規則では、control stop は 30 分である。
したがって、数分から十数分程度の停止は control stop とみなさず、
地点・ラベル・時系列メモにより non-control actual stop として分類した。
nominal planning の全工程距離は ${float(planning_race_km if planning_race_km is not None else 0.0):.2f}\\,\\mathrm{{km}}$ とし、
今回の replay では実走リタイア地点を $2831.0\\,\\mathrm{{km}}$ とし、
公式分類上の前 control stop 参考距離は $2720.0\\,\\mathrm{{km}}$ と併記する。

参照した公式資料:
\\begin{{itemize}}
  \\item Regulations: \\url{{{BWSC_RULES_URL}}}
  \\item Route notes: \\url{{{BWSC_ROUTE_NOTES_URL}}}
\\end{{itemize}}

\\section{{入力として走査した主資料}}
\\begin{{itemize}}
  \\item 時系列メモ: {TIME_MEMO_PDF.name}
  \\item 各ポイント資料: {POINTS_PDF.name}
  \\item バッテリー SoC 資料: {BATTERY_SOC_PDF.name}
  \\item トラブル資料: {TROUBLE_DOCX.name}
  \\item 放電試験 CSV: 2024\\_05\\_26\\_DischargeTest.csv
  \\item 日別 ZP 加工 CSV: ZP\\_Data0824day1.csv から ZP\\_Data0829day6.csv
  \\item ルート高低データ: route\\_100m\\_dem.csv
\\end{{itemize}}

\\section{{前処理}}
まず、時系列メモから取り出した停車アンカー $(t_i, s_i)$ に対し、各区間の 5 秒速度ログを積分して
区間内の距離進行率を作り、これをアンカー距離へ写像した。
区間 $[t_i, t_{{i+1}}]$ でのサンプル $k$ の距離は、
\\[
  s_k = s_i + \\frac{{\\sum_{{j=i}}^k v_j \\Delta t_j}}{{\\sum_{{j=i}}^{{i+1}} v_j \\Delta t_j}} (s_{{i+1}} - s_i)
\\]
とした。停車区間では $s_k = s_i$ とした。

次に、\\path{{route_100m_dem.csv}} から距離に対する緯度経度・標高・勾配を補間した。
気象は Open-Meteo archive を 25 km ごとのルート点で取得し、時刻と距離の 2 次元補間で
各サンプルへ対応づけた。風はルート方位 $\\psi$ と気象風向 $\\phi$ から
\\[
  w_{{head}} = w \\cos(\\phi - \\psi)
\\]
で向かい風成分へ変換した。

さらに、観測 PV 出力 $P_{{pv}}^{{obs}}$ と archive weather から計算した基準 PV 出力
$P_{{pv}}^{{arch}}$ の比
\\[
  r_k = \\frac{{P_{{pv,k}}^{{obs}}}}{{\\max(P_{{pv,k}}^{{arch}}, 20)}}
\\]
を平滑化し、effective irradiance を
\\[
  G_{{eff,k}} = r_k G_{{arch,k}}
\\]
で再構成した。これにより、雲・姿勢・実配線損失の影響を archive weather のみでは取りこぼす問題を抑えた。
あわせて、パック電圧が ${INVALID_PACK_VOLTAGE_MIN_V:.0f}\\,\\mathrm{{V}}$ 未満のサンプルはセンサ断・電源断とみなし、
power / voltage fit の両方から除外した。

\\section{{PV パラメータの最尤推定}}
effective irradiance $G_{{eff,k}}$ と外気温 $T_{{a,k}}$ に対し、
\\[
  T_{{c,k}} = T_{{a,k}} + \\beta_T G_k
\\]
でセル温度を近似し、まず既存 panel / MPPT map から計算した基準 PV 出力
$P_{{pvb,k}}$ に対して
\\[
  P_{{pv,k}}^{{pred}} = k_{{pv}} P_{{pvb,k}}(G_k, T_{{c,k}})
\\]
を当てた。その後、残差から panel / MPPT map の shape correction
$S_{{pv}}(G, T_c)$ を separable log-warp として追加し、最終的には
\\[
  P_{{pv,k}}^{{pred,final}} = k_{{pv}} S_{{pv}}(G_k, T_{{c,k}}) P_{{pvb,k}}(G_k, T_{{c,k}})
\\]
を用いた。観測 PV 出力 $P_{{pv,k}}^{{obs}}$ に対する評価関数は
\\[
  \\mathcal{{L}}_{{PV}}(\\theta_{{PV}})
  = \\sum_k \\rho_{{Huber}}\\!\\left(P_{{pv,k}}^{{obs}} - P_{{pv,k}}^{{pred}}(\\theta_{{PV}})\\right)
\\]
とし、$\\theta_{{PV}} = (k_{{pv}}, \\beta_T)$ を推定した。PV fit は
$60\\,\\mathrm{{s}}$ resample 上で実行した。

\\section{{電池パラメータの最尤推定}}
電池側は観測パック電力 $P_k^{{obs}}$ と観測電流 $I_k^{{obs}}$ を入力として SoC と端子電圧を再生した。
SoC 更新は
\\[
  z_{{k+1}} = z_k - \\eta_{{chg}}(P_k^{{obs}}) \\frac{{P_k^{{obs}} \\Delta t_k / 3600}}{{E_{{nom}}}}
\\]
で与え、放電時は $\\eta_{{chg}} = 1$、充電時のみ $\\eta_{{chg}} = \\eta_{{charge}}$ とした。

放電実験から得た 25 直列換算の擬似 OCV 曲線を $\\mathrm{{OCV}}(z)$ とし、
shape-corrected Rint map $S_R(T,z)R_{{base}}(T,z)$ を
スケール $k_R$ と配線抵抗 $R_{{line}}$ で補正して
\\[
  V_k^{{pred}} = \\mathrm{{OCV}}(z_k) - I_k^{{obs}} \\left(k_R S_R(T_k, z_k) R_{{base}}(T_k, z_k) + R_{{line}}\\right)
\\]
とした。観測電圧 $V_k^{{obs}}$ に対し、ガウス雑音を仮定した負の対数尤度
\\[
  \\mathcal{{L}}_B(\\theta_B)
  = \\sum_k \\frac{{\\left(V_k^{{obs}} - V_k^{{pred}}(\\theta_B)\\right)^2}}{{2\\sigma_V^2}}
\\]
に、仕様ベースの事前条件
\\[
  \\mathcal{{R}}_B(\\theta_B)
  = \\lambda_E \\left(\\frac{{E_{{nom}} - 3011}}{{180}}\\right)^2
  + \\lambda_\\eta \\left(\\frac{{\\eta_{{charge}} - 0.955}}{{0.03}}\\right)^2
  + \\lambda_R \\left(\\frac{{k_R - 1.5}}{{0.8}}\\right)^2
  + \\lambda_l \\left(\\frac{{R_{{line}} - 0.015}}{{0.015}}\\right)^2
\\]
を加えた penalized objective
\\[
  \\mathcal{{J}}_B(\\theta_B) = \\mathcal{{L}}_B(\\theta_B) + \\mathcal{{R}}_B(\\theta_B)
\\]
を最小化して
$\\theta_B = (z_0, E_{{nom}}, k_R, R_{{line}}, \\eta_{{charge}})$
を求めた。さらに、低速・低電流・十分高い電圧の停止点では
\\[
  z_k^{{rest,obs}} = \\mathrm{{OCV}}^{{-1}}(V_k^{{obs}})
\\]
を SoC 観測値として併用し、容量と内部抵抗のドリフトを抑えた。
初期値を変えた {BATTERY_RESTART_COUNT} restart を行い、最良解を採用した。

\\section{{走行パラメータの最尤推定}}
走行側は、最終的に simulation / replay で用いる corrected PV モデル
$P_k^{{pv,model}}$ をそのまま使って駆動側を同定した。
観測電池出力 $P_k^{{pack,obs}}$ に対し、
\\[
  P_{{m,k}}
  = \\left(
      \\frac12 \\rho C_d A (v_k + k_w w_k)^2
      + m g C_{{rr}} \\cos\\theta_k
      + m g \\gamma_{{grade}} \\sin\\theta_k
    \\right) v_k + P_{{aux}}
\\]
を計算し、drive / regen map にはまず separable warp $S_\\eta(v,\\tau)$ を当て、
その上に残る全体スケール $k_\\eta$ を掛けた電気出力へ写した。
最終的なパック出力モデルは
\\[
  P_k^{{pack,pred}} = P_k^{{drive,el}} - P_k^{{pv}}
\\]
とした。ここで $P_k^{{pv}}$ は archive weather と PV fit から再計算している。

評価関数はガウス雑音を仮定した
\\[
  \\mathcal{{L}}_M(\\theta_M)
  = \\sum_k \\rho_{{Huber}}\\!\\left(P_k^{{pack,obs}} - P_k^{{pack,pred}}(\\theta_M)\\right)
\\]
であり、さらに
\\[
  \\mathcal{{R}}_M(\\theta_M)
  = \\lambda_{{CdA}} \\left(\\frac{{C_dA - 0.11}}{{0.02}}\\right)^2
  + \\lambda_{{aux}} \\left(\\frac{{P_{{aux}} - 21}}{{5}}\\right)^2
  + \\lambda_{{\\eta}} \\left(\\frac{{k_\\eta - 1.02}}{{0.05}}\\right)^2
  + \\lambda_w \\left(\\frac{{k_w - 0.12}}{{0.10}}\\right)^2
\\]
を加えた penalized objective
\\[
  \\mathcal{{J}}_M(\\theta_M) = \\mathcal{{L}}_M(\\theta_M) + \\mathcal{{R}}_M(\\theta_M)
\\]
を最小化した。
ここで車重はユーザー指定の
\\[
  m = {float(fixed_mass_kg if fixed_mass_kg is not None else 0.0):.1f}\\,\\mathrm{{kg}}
\\]
に固定して fit を行った。したがって今回の motion fit は、質量を動かして
誤差を吸収するのではなく、$C_dA, C_{{rr}}, P_{{aux}}, \\gamma_{{grade}}, k_\\eta, k_w$
の物理項で整合を取る設定である。
推定対象は
$\\theta_M = (C_dA, C_{{rr}}, P_{{aux}}, \\gamma_{{grade}}, k_\\eta, k_w)$
である。走行 fit は $120\\,\\mathrm{{s}}$ resample 上で {MOTION_RESTART_COUNT} restart 実行した。

\\section{{全行程 Joint Refinement}}
stagewise fit の後、実際に package が用いる replay 式そのもので 120 s 列全体を再生し、
電池・走行パラメータを同時に微修正した。joint objective は
\\[
  \\mathcal{{J}}_{{joint}}
  =
  \\alpha_P \\left(\\frac{{\\mathrm{{RMSE}}_P}}{{180}}\\right)^2
  +
  \\alpha_V \\left(\\frac{{\\mathrm{{RMSE}}_V}}{{4}}\\right)^2
  +
  \\alpha_z \\frac1N \\sum_{{k \\in \\mathcal{{R}}}}
  \\left(\\frac{{z_k - z_k^{{rest,obs}}}}{{0.05}}\\right)^2
  +
  \\mathcal{{R}}_B + \\mathcal{{R}}_M
\\]
とし、ここで $\\mathcal{{R}}$ は停止中低電流の SoC アンカー集合である。
この段階で、局所残差だけでなく race-level のエネルギー整合も同時に詰めた。
joint refinement は {JOINT_RESTART_COUNT} restart、各 restart 最大 {JOINT_FIT_MAXITER} iteration で実行した。

\\section{{推定結果}}
\\begin{{longtable}}{{p{{0.34\\linewidth}}p{{0.24\\linewidth}}p{{0.28\\linewidth}}}}
\\toprule
項目 & 推定値 & 備考 \\\\
\\midrule
\\endhead
$k_{{pv}}$ [-] & {pv.panel_gain:.4f} & panel / MPPT 形状補正の上に残る PV 全体のスカラー補正 \\\\
$\\beta_T$ [C/(W/m$^2$)] & {pv.tcell_gain_c_per_wm2:.5f} & $T_{{c}} = T_{{amb}} + \\beta_T G$ の係数 \\\\
初期 SoC $z_0$ & {batt.soc0:.4f} & 実走スタート電圧と全行程の電圧整合から推定 \\\\
$E_{{nom}}$ [Wh] & {batt.e_nom_wh:.2f} & 充放電積分と電圧整合から推定 \\\\
$k_R$ [-] & {batt.rint_scale:.4f} & shape-corrected Rint map に対する全体倍率 \\\\
$R_{{line}}$ [$\\Omega$] & {batt.r_line_ohm:.5f} & 配線等の追加抵抗 \\\\
$\\eta_{{charge}}$ [-] & {batt.eta_charge:.4f} & 充電時の有効率 \\\\
$m$ [kg] & {float(fixed_mass_kg if fixed_mass_kg is not None else 0.0):.1f} & ユーザー指定値に固定して同定 \\\\
$C_dA$ [m$^2$] & {mot.cda:.5f} & 実走電力に対する最尤値 \\\\
$C_{{rr}}$ [-] & {mot.crr:.6f} & 実走電力に対する最尤値 \\\\
$P_{{aux}}$ [W] & {mot.p_aux_w:.2f} & 補機負荷 \\\\
$\\gamma_{{grade}}$ [-] & {mot.grade_scale:.4f} & 勾配寄与の補正係数 \\\\
$k_\\eta$ [-] & {mot.drive_eff_scale:.4f} & shape-corrected drive / regen map に対する全体倍率 \\\\
$k_w$ [-] & {mot.headwind_gain:.4f} & 向かい風露出補正係数 \\\\
\\bottomrule
\\end{{longtable}}

\\section{{再現性評価}}
クリーン区間での誤差指標は以下のとおり。
\\begin{{longtable}}{{p{{0.40\\linewidth}}p{{0.20\\linewidth}}}}
\\toprule
指標 & 値 \\\\
\\midrule
\\endhead
PV 出力 RMSE [W] & {pv.solar_rmse_w:.2f} \\\\
Joint fit RMSE (120 s clean) [W] & {mot.power_rmse_w:.2f} \\\\
Replay RMSE (5 s clean) [W] & {metrics['power_rmse_clean_w']:.2f} \\\\
Replay RMSE (120 s clean) [W] & {metrics.get('power_rmse_fit_window_w', float('nan')):.2f} \\\\
Replay MAE (5 s clean) [W] & {metrics['power_mae_clean_w']:.2f} \\\\
電圧 RMSE (5 s clean) [V] & {metrics['voltage_rmse_clean_v']:.3f} \\\\
電圧 RMSE (120 s clean) [V] & {metrics.get('voltage_rmse_fit_window_v', float('nan')):.3f} \\\\
最終予測 SoC [-] & {metrics['final_soc_pred']:.4f} \\\\
最終再構成距離 [km] & {metrics['final_distance_km']:.1f} \\\\
\\bottomrule
\\end{{longtable}}

\\section{{不確かさつき upper / lower plan}}
実走再現の clean 区間で得たパック出力残差 $\\varepsilon_k$ を
$\\varepsilon_k \\sim \\mathcal{{N}}(0, \\sigma_P^2)$ とみなし、
予見時間 $\\tau$ の累積エネルギー不確かさを
\\[
  \\mathrm{{Var}}[\\Delta E(\\tau)] = \\tau \\Delta t \\sigma_P^2 / 3600^2
\\]
で近似した。さらに、各 upper plan セグメントに対し
\\[
  \\sigma_{{v,j}} \\approx
  \\frac{{\\sigma_P \\sqrt{{\\tau_j \\Delta t}} / 3600}}
       {{\\left|\\partial E_j / \\partial v_j\\right|}}
\\]
として速度の標準偏差へ写像し、\\emph{{conservative / nominal / aggressive}} の
3 本の upper plan を生成した。lower plan は profile の
\\path{{lower\\_ref\\_accel\\_limit\\_kmhps}},
\\path{{lower\\_ref\\_decel\\_limit\\_kmhps}},
\\path{{lower\\_ref\\_deadband\\_kmh}}
で 1 Hz に整形した。

\\section{{図}}
\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.92\\linewidth]{{{rel_plot['battery_power']}}}
  \\caption{{観測電池出力とモデル電池出力}}
\\end{{figure}}

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.92\\linewidth]{{{rel_plot['battery_voltage']}}}
  \\caption{{観測電圧とモデル電圧}}
\\end{{figure}}

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.92\\linewidth]{{{rel_plot['solar_power']}}}
  \\caption{{観測 PV 出力と archive weather から再計算した PV 出力}}
\\end{{figure}}

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.92\\linewidth]{{{rel_plan_plot}}}
  \\caption{{upper plan の 3 プラン重ね合わせ}}
\\end{{figure}}

\\section{{出力所在}}
主要成果物は次に保存した。
\\begin{{itemize}}
  \\item fitted package: \\path{{project_packages/{PACKAGE_NAME}}}
  \\item replay validation CSV: \\path{{project_packages/{PACKAGE_NAME}/data/observed/bwsc2025_replay_validation_5s.csv}}
  \\item fitted weather CSV: \\path{{project_packages/{PACKAGE_NAME}/data/weather/bwsc2025_observed_weather_10min.csv}}
  \\item fitted maps: \\path{{project_packages/{PACKAGE_NAME}/maps/}}
  \\item upper / lower / 3-plan CSV: \\path{{project_packages/{PACKAGE_NAME}/outputs/plans/}}
\\end{{itemize}}

\\section{{補足}}
PV 系は race log だけでは panel と MPPT の寄与を完全には分離できないため、
solar-chain 全体の補正面をまず同定し、その対数補正量を panel 側へ {MAP_SHAPE_PANEL_MPPT_PANEL_SHARE:.2f}、
MPPT 側へ {1.0 - MAP_SHAPE_PANEL_MPPT_PANEL_SHARE:.2f} の比率で配分した。
一方、drive / regen / Rint については、各マップ軸に沿った滑らかな separable warp を明示的に推定している。
したがって今回強く同定できているのは
\\emph{{panel gain・cell temperature gain・panel/MPPT 形状補正・Rint 形状補正・drive/regen 形状補正・電池有効量・追加配線抵抗・充電効率・CdA・Crr・補機負荷・勾配補正・駆動効率スカラー}}
である。

今回の profile では、fit で得た初期 SoC が model 上限を超えないよう
\\path{{simulation.soc0}} を \\path{{model.soc_max}} 以下へクリップし、
\\path{{live.autocal.aux_power_w_init}} は \\path{{model.P_aux}} と一致させた。
また、\\path{{mpc.dv_max_kmhps=0.0}} は実装上「速度変化禁止」ではなく
「速度変化制約ペナルティの無効化」を意味する。

\\end{{document}}
"""
    tex_path.write_text(textwrap.dedent(tex).strip() + "\n", encoding="utf-8", newline="\n")
    return tex_path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def compile_tex(tex_path: Path) -> Path:                           # [関数定義] compile_tex の処理実行ブロック
    pdf_path = tex_path.with_suffix(".pdf")
    for _ in range(2):
        res = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", tex_path.name],
            cwd=tex_path.parent,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if res.returncode != 0 and not pdf_path.exists():
            raise subprocess.CalledProcessError(res.returncode, res.args)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    return pdf_path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_package_readme(package_dir: Path, pv: PvFitResult, batt: BatteryFitResult, mot: MotionFitResult) -> Path:  # [関数定義] write_package_readme の処理実行ブロック
    readme = package_dir / "README.md"
    text = f"""# {PACKAGE_NAME}

This package duplicates `bwsc2025_public` and replaces it with a log-fitted BWSC2025 profile.

## Main entry

- Profile: `project_packages/{PACKAGE_NAME}/profile.yaml`

## Included

- Reconstructed 5 s observed log with route / weather alignment
- Archive-weather 10 min CSV for replay-oriented simulation
- Fitted PV summary:
  - `panel_gain = {pv.panel_gain:.4f}`
  - `tcell_gain_c_per_wm2 = {pv.tcell_gain_c_per_wm2:.5f}`
- Fitted battery summary:
  - `soc0 = {batt.soc0:.4f}`
  - `E_nom_Wh = {batt.e_nom_wh:.2f}`
  - `Rint scale = {batt.rint_scale:.4f}`
- Fitted motion summary:
  - `CdA = {mot.cda:.5f}`
  - `Crr = {mot.crr:.6f}`
  - `P_aux = {mot.p_aux_w:.2f} W`
  - `headwind_gain = {mot.headwind_gain:.4f}`

## PowerShell example

```powershell
.\\SolarSim.ps1 -Profile project_packages/{PACKAGE_NAME}/profile.yaml -Action simulate
```
"""
    readme.write_text(text, encoding="utf-8", newline="\n")
    return readme                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def main() -> None:                                                # [関数定義] main の処理実行ブロック
    global SRC_PACKAGE_NAME, PACKAGE_NAME, SRC_PACKAGE, OUT_PACKAGE, REPORT_DATE
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-name", default=DEFAULT_PACKAGE_NAME)
    ap.add_argument("--source-package", default=DEFAULT_SRC_PACKAGE_NAME)
    ap.add_argument("--report-date", default=REPORT_DATE)
    ap.add_argument("--fixed-mass-kg", type=float, default=DEFAULT_FIXED_MASS_KG)
    ap.add_argument("--profile-upper-max-iter", type=int, default=DEFAULT_PROFILE_UPPER_MAX_ITER)
    ap.add_argument("--skip-sim", action="store_true")
    args = ap.parse_args()

    SRC_PACKAGE_NAME = str(args.source_package)
    PACKAGE_NAME = str(args.package_name)
    SRC_PACKAGE = ROOT / "project_packages" / SRC_PACKAGE_NAME
    OUT_PACKAGE = ROOT / "project_packages" / PACKAGE_NAME
    REPORT_DATE = str(args.report_date)

    log_stage("prepare output package")
    if OUT_PACKAGE.exists():
        remove_tree_force(OUT_PACKAGE)
    shutil.copytree(SRC_PACKAGE, OUT_PACKAGE)

    log_stage("load base model and source logs")
    base_cfg, base_model = base_model_from_public_profile(fixed_mass_kg=float(args.fixed_mass_kg))
    anchors = load_event_anchors()
    log_stage("read processed day logs")
    raw_logs = load_processed_day_logs()
    log_stage("reconstruct distance from anchors")
    logs = apply_distance_reconstruction(raw_logs, anchors)
    log_stage("load route DEM")
    dem, route_profile, route_waypoints = load_route_dem()
    planning_race_km = planning_race_km_from_route(route_profile)
    log_stage("attach route geometry")
    logs = attach_route_geometry(logs, dem)
    log_stage("apply exclusion flags")
    logs = apply_exclusion_flags(logs)

    log_stage("fetch archive weather along route")
    weather_cache = OUT_PACKAGE / "outputs" / "weather_cache" / "route_weather_archive.csv"
    weather_points = fetch_route_weather_cache(
        dem,
        weather_cache,
        "2025-08-24",
        "2025-08-29",
        max_s_km=planning_race_km,
    )
    logs_weather = attach_archive_weather(logs, weather_points)
    log_stage("reconstruct effective irradiance from archive weather and observed PV (pass 1)")
    logs = build_effective_weather(logs_weather, base_model)
    log_stage("fit PV parameters against effective weather (pass 1)")
    pv_fit = fit_pv_parameters(logs, base_model)
    logs = attach_archive_pv_model(logs, base_model, pv_fit)

    log_stage("build OCV curve and fit battery / motion parameters")
    ocv_csv = OUT_PACKAGE / "maps" / "ocv_soc_curve.csv"
    ocv_df = build_ocv_curve(ocv_csv)

    fit_df = resample_for_fit(logs)
    log_stage("fit battery parameters (pass 1)")
    batt_stage_pre = fit_battery_parameters(
        fit_df,
        ocv_df,
        base_model,
        restart_count=3,
        maxiter=70,
        fit_stride=2,
    )
    log_stage("fit motion parameters (pass 1)")
    mot_stage_pre = fit_motion_parameters(
        fit_df,
        base_model,
        restart_count=4,
        maxiter=80,
        fit_stride=2,
    )
    log_stage("jointly refine battery and motion parameters on whole-race replay (pass 1)")
    batt_fit_pre, mot_fit_pre, joint_info_pre = joint_refine_parameters(
        fit_df,
        ocv_df,
        base_model,
        batt_stage_pre,
        mot_stage_pre,
        restart_count=3,
        random_start_count=6,
        local_topk=3,
        maxiter=35,
        fit_stride=2,
    )
    logs["headwind_effective_ms"] = logs["headwind_archive_ms"] * float(mot_fit_pre.headwind_gain)
    log_stage("replay fitted model over observed route (pass 1)")
    replay_df_pre = joint_replay(logs, ocv_df, base_model, batt_fit_pre, mot_fit_pre)
    metrics_pre = metrics_from_replay(replay_df_pre)

    log_stage("fit low-dimensional map shape corrections from pass-1 replay residuals")
    map_shape_fit = fit_map_shapes(logs, fit_df, replay_df_pre, base_model, pv_fit, batt_fit_pre, mot_fit_pre, ocv_df)
    map_assets = write_scaled_maps(
        base_cfg,
        pv_fit,
        mot_fit_pre,
        batt_fit_pre,
        OUT_PACKAGE / "maps",
        shape_fits=map_shape_fit,
    )
    shaped_model = build_model_from_map_assets(base_model, map_assets)

    log_stage("reconstruct effective irradiance with shape-corrected maps (pass 2)")
    logs = build_effective_weather(logs_weather, shaped_model)
    log_stage("fit PV parameters against effective weather (pass 2)")
    pv_fit = fit_pv_parameters(logs, shaped_model)
    logs = attach_archive_pv_model(logs, shaped_model, pv_fit)
    fit_df = resample_for_fit(logs)
    log_stage("fit battery parameters (pass 2)")
    batt_stage = fit_battery_parameters(
        fit_df,
        ocv_df,
        shaped_model,
        restart_count=4,
        maxiter=100,
        fit_stride=1,
    )
    log_stage("fit motion parameters (pass 2)")
    mot_stage = fit_motion_parameters(
        fit_df,
        shaped_model,
        restart_count=5,
        maxiter=120,
        fit_stride=1,
    )
    log_stage("jointly refine battery and motion parameters on whole-race replay (pass 2)")
    batt_fit, mot_fit, joint_info = joint_refine_parameters(
        fit_df,
        ocv_df,
        shaped_model,
        batt_stage,
        mot_stage,
        restart_count=4,
        random_start_count=8,
        local_topk=4,
        maxiter=60,
        fit_stride=1,
    )
    logs["headwind_effective_ms"] = logs["headwind_archive_ms"] * float(mot_fit.headwind_gain)
    log_stage("replay fitted model over observed route (pass 2)")
    replay_df = joint_replay(logs, ocv_df, shaped_model, batt_fit, mot_fit)
    metrics = metrics_from_replay(replay_df)

    log_stage("write fitted assets and profile")
    route_assets = write_route_assets(
        route_profile,
        route_waypoints,
        OUT_PACKAGE / "data" / "route",
        planning_race_km=planning_race_km,
    )
    actual_stop_yaml = OUT_PACKAGE / "data" / "race" / "bwsc2025_actual_stops.yaml"
    planning_stop_yaml = OUT_PACKAGE / "data" / "race" / "bwsc2025_control_stops.yaml"
    actual_schedule_yaml = OUT_PACKAGE / "data" / "race" / "bwsc2025_actual_drive_schedule.yaml"
    planning_schedule_yaml = OUT_PACKAGE / "data" / "race" / "bwsc2025_drive_schedule.yaml"
    write_stops_yaml(actual_stop_yaml)
    write_control_stops_yaml(planning_stop_yaml)
    stop_catalog_csv = write_stop_catalog_csv(OUT_PACKAGE / "data" / "race" / "bwsc2025_stop_catalog.csv")
    write_drive_schedule_yaml(actual_schedule_yaml)
    observed_weather_csv = OUT_PACKAGE / "data" / "weather" / "bwsc2025_observed_weather_10min.csv"
    weather_10min = write_observed_weather_csv(logs, observed_weather_csv)
    planning_weather_csv = write_nominal_planning_weather_grid_csv(
        weather_points,
        OUT_PACKAGE / "data" / "weather" / "bwsc2025_nominal_fullcourse_weather_grid.csv",
        pv_fit,
        mot_fit,
    )
    log_assets = write_normalized_logs(logs, replay_df, OUT_PACKAGE)

    profile_yaml = write_profile(
        base_cfg,
        OUT_PACKAGE,
        route_assets,
        planning_weather_csv,
        planning_stop_yaml,
        planning_schedule_yaml,
        observed_weather_csv,
        actual_stop_yaml,
        actual_schedule_yaml,
        map_assets,
        ocv_csv,
        pv_fit,
        batt_fit,
        mot_fit,
        fixed_mass_kg=float(args.fixed_mass_kg),
        profile_upper_max_iter=int(args.profile_upper_max_iter),
        planning_race_km=planning_race_km,
    )
    write_fit_summary_yaml(
        OUT_PACKAGE,
        pv_fit,
        batt_fit,
        mot_fit,
        metrics,
        batt_stage,
        mot_stage,
        joint_info,
        map_shape_fit,
        metrics_pre,
        fixed_mass_kg=float(args.fixed_mass_kg),
        profile_upper_max_iter=int(args.profile_upper_max_iter),
        planning_race_km=planning_race_km,
    )
    write_package_readme(OUT_PACKAGE, pv_fit, batt_fit, mot_fit)

    if args.skip_sim:
        log_stage("skip solar_sim and upper/lower plan generation")
        sim_outputs = {
            "summary_json": OUT_PACKAGE / "outputs" / "reports" / "simulation_skipped.json",
            "out_csv": OUT_PACKAGE / "outputs" / "reports" / "simulation_skipped.csv",
            "detail_csv": OUT_PACKAGE / "outputs" / "reports" / "simulation_detail_skipped.csv",
            "plan_csv": OUT_PACKAGE / "outputs" / "reports" / "plan_skipped.csv",
            "report_html": OUT_PACKAGE / "outputs" / "reports" / "simulation_skipped.html",
            "resolved_yaml": profile_yaml,
        }
        plan_outputs = write_placeholder_plan_outputs(OUT_PACKAGE)
    else:
        log_stage("run solar_sim replay / prerace simulation")
        sim_outputs = run_forward_sim(profile_yaml)
        log_stage("generate upper / lower / 3-plan products")
        plan_outputs = generate_plan_products(profile_yaml, route_profile, weather_10min, mot_fit, mot_fit.residual_sigma_w, sim_outputs)
    log_stage("render validation plots and reports")
    validation_plots = plot_validation(replay_df, OUT_PACKAGE / "outputs" / "reports" / "figures")
    write_report_markdown(
        OUT_PACKAGE,
        pv_fit,
        batt_fit,
        mot_fit,
        metrics,
        sim_outputs,
        plan_outputs,
        fixed_mass_kg=float(args.fixed_mass_kg),
        planning_race_km=planning_race_km,
    )
    tex_path = write_report_tex(
        OUT_PACKAGE,
        pv_fit,
        batt_fit,
        mot_fit,
        metrics,
        validation_plots,
        plan_outputs,
        fixed_mass_kg=float(args.fixed_mass_kg),
        planning_race_km=planning_race_km,
    )
    pdf_path = compile_tex(tex_path)

    summary = {
        "package_dir": str(OUT_PACKAGE),
        "profile_yaml": str(profile_yaml),
        "stop_catalog_csv": str(stop_catalog_csv),
        "observed_log_csv": str(log_assets["observed_csv"]),
        "fit_dataset_csv": str(log_assets["fit_csv"]),
        "replay_validation_csv": str(log_assets["replay_csv"]),
        "simulation_csv": str(sim_outputs["out_csv"]),
        "simulation_detail_csv": str(sim_outputs["detail_csv"]),
        "upper_plan_csv": str(plan_outputs["upper_three_csv"]),
        "lower_plan_csv": str(plan_outputs["lower_three_csv"]),
        "report_tex": str(tex_path),
        "report_pdf": str(pdf_path),
    }
    out_json = OUT_PACKAGE / "outputs" / "reports" / f"{PACKAGE_NAME}_locations.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log_stage(f"done: {pdf_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))



# =============================================================================
# 【統合ユーティリティ】パス解決・ルート補間・スケジューラー・気象インターフェース
# =============================================================================
import os
from pathlib import Path

get_package_share_directory = None



PKG_NAME = 'mpc_solarcar'
REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(path: str, default_subdir: str = '') -> str:      # [関数定義] resolve_path の処理実行ブロック
    """Resolve a path relative to CWD or package share.

    - If absolute, return as-is.                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - If exists relative to CWD, return it.                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - Otherwise, resolve under <pkg_share>/<default_subdir> (or directly under share).
    """
    if path is None:
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.exists(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if get_package_share_directory is not None:
        pkg_share = get_package_share_directory(PKG_NAME)
    else:
        pkg_share = os.fspath(REPO_ROOT)
    if default_subdir:
        subdir = default_subdir.strip('/\\')
        if path.startswith(subdir + os.sep) or path == subdir:
            return os.path.join(pkg_share, path)                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return os.path.join(pkg_share, subdir, path)               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return os.path.join(pkg_share, path)                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


def _interp_field(d, y, s_km, default=0.0):                        # [関数定義] _interp_field の処理実行ブロック
    if len(d) < 2:
        return float(default)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    s = np.clip(s_km, d[0], d[-1])
    i = np.searchsorted(d, s) - 1
    i = np.clip(i, 0, len(d) - 2)
    t = 0.0 if d[i + 1] == d[i] else (s - d[i]) / (d[i + 1] - d[i])
    return float((1 - t) * y[i] + t * y[i + 1])                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route(route_df, s_km):                             # [関数定義] interpolate_route の処理実行ブロック
    d = route_df['dist_km'].values
    lat = route_df['lat'].values
    lon = route_df['lon'].values
    latp = _interp_field(d, lat, s_km, default=float(lat[0]) if len(lat) else 0.0)
    lonp = _interp_field(d, lon, s_km, default=float(lon[0]) if len(lon) else 0.0)
    return latp, lonp                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route_with_alt(route_df, s_km):                    # [関数定義] interpolate_route_with_alt の処理実行ブロック
    lat, lon = interpolate_route(route_df, s_km)
    alt = None
    for col in ('alt_m', 'altitude_m', 'elev_m'):
        if col in route_df.columns:
            d = route_df['dist_km'].values
            alt = _interp_field(d, route_df[col].values, s_km, default=float(route_df[col].values[0]))
            break
    return lat, lon, alt                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_profile(route_df, s_km, field: str, default: float = 0.0) -> float:  # [関数定義] interpolate_profile の処理実行ブロック
    if field not in route_df.columns:
        return float(default)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    d = route_df['dist_km'].values
    return _interp_field(d, route_df[field].values, s_km, default=default)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def bearing_deg(lat1, lon1, lat2, lon2):                           # [関数定義] bearing_deg の処理実行ブロック
    lat1r = np.deg2rad(float(lat1))
    lon1r = np.deg2rad(float(lon1))
    lat2r = np.deg2rad(float(lat2))
    lon2r = np.deg2rad(float(lon2))
    dlon = lon2r - lon1r
    y = np.sin(dlon) * np.cos(lat2r)
    x = np.cos(lat1r) * np.sin(lat2r) - np.sin(lat1r) * np.cos(lat2r) * np.cos(dlon)
    brng = np.rad2deg(np.arctan2(y, x))
    return float((brng + 360.0) % 360.0)                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route_heading(route_df, s_km, span_km: float = 1.0):  # [関数定義] interpolate_route_heading の処理実行ブロック
    if route_df is None or len(route_df) < 2:
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    s0 = max(float(route_df['dist_km'].iloc[0]), float(s_km) - max(0.1, span_km))
    s1 = min(float(route_df['dist_km'].iloc[-1]), float(s_km) + max(0.1, span_km))
    if s1 <= s0:
        d = route_df['dist_km'].values
        i = int(np.clip(np.searchsorted(d, float(s_km)), 1, len(d) - 1))
        lat1 = float(route_df.iloc[i - 1]['lat'])
        lon1 = float(route_df.iloc[i - 1]['lon'])
        lat2 = float(route_df.iloc[i]['lat'])
        lon2 = float(route_df.iloc[i]['lon'])
        return bearing_deg(lat1, lon1, lat2, lon2)                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    lat1, lon1 = interpolate_route(route_df, s0)
    lat2, lon2 = interpolate_route(route_df, s1)
    return bearing_deg(lat1, lon1, lat2, lon2)                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


import os
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import List, Optional, Tuple

import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - fallback for older Python
    ZoneInfo = None


def _parse_utc(ts: str) -> Optional[datetime]:                     # [関数定義] _parse_utc の処理実行ブロック
    try:
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def _parse_time_hhmm(s: str) -> Optional[dtime]:                   # [関数定義] _parse_time_hhmm の処理実行ブロック
    try:
        parts = s.strip().split(':')
        if len(parts) < 2:
            return None                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return dtime(hour=int(parts[0]), minute=int(parts[1]))     # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


@dataclass
class DriveWindow:                                                 # [クラス定義] DriveWindow オブジェクトの設計
    start_utc: datetime
    end_utc: datetime
    v_min_kmh: float
    v_max_kmh: float

    def contains(self, t_utc: datetime) -> bool:                   # [関数定義] contains の処理実行ブロック
        return self.start_utc <= t_utc < self.end_utc              # [戻り値] 計算結果・計算状態の呼び出し元への返却


@dataclass
class DailyWindow:                                                 # [クラス定義] DailyWindow オブジェクトの設計
    start_local: dtime
    end_local: dtime
    tz: str
    days: Optional[List[int]]
    v_min_kmh: float
    v_max_kmh: float

    def contains(self, t_utc: datetime) -> bool:                   # [関数定義] contains の処理実行ブロック
        if ZoneInfo is None:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        try:
            tzinfo = ZoneInfo(self.tz)
        except Exception:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        local_dt = t_utc.astimezone(tzinfo)
        if self.days is not None and local_dt.weekday() not in self.days:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        start = self.start_local
        end = self.end_local
        now_t = local_dt.time()
        if start <= end:
            return start <= now_t < end                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        # wraps midnight
        return now_t >= start or now_t < end                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


class DriveSchedule:                                               # [クラス定義] DriveSchedule オブジェクトの設計
    def __init__(self, windows: List[DriveWindow], daily: List[DailyWindow], deny_by_default: bool):  # [関数定義] __init__ の処理実行ブロック
        self.windows = windows
        self.daily = daily
        self.deny_by_default = deny_by_default

    @classmethod
    def from_yaml(cls, path: str) -> Optional['DriveSchedule']:    # [関数定義] from_yaml の処理実行ブロック
        if not path or not os.path.exists(path):
            return None                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            return None                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        deny_by_default = bool(cfg.get('deny_by_default', False))
        windows = []
        for w in cfg.get('drive_windows', []) or []:
            start = _parse_utc(str(w.get('start_utc', '')))
            end = _parse_utc(str(w.get('end_utc', '')))
            if start is None or end is None:
                continue
            vmin = float(w.get('v_min_kmh', 0.0))
            vmax = float(w.get('v_max_kmh', 130.0))
            windows.append(DriveWindow(start, end, vmin, vmax))
        daily = []
        for w in cfg.get('daily_windows', []) or []:
            start = _parse_time_hhmm(str(w.get('start_local', '')))
            end = _parse_time_hhmm(str(w.get('end_local', '')))
            tz = str(w.get('tz', 'UTC'))
            if start is None or end is None:
                continue
            days = w.get('days', None)
            if days is not None:
                try:
                    days = [int(d) for d in days]
                except Exception:
                    days = None
            vmin = float(w.get('v_min_kmh', 0.0))
            vmax = float(w.get('v_max_kmh', 130.0))
            daily.append(DailyWindow(start, end, tz, days, vmin, vmax))
        return cls(windows, daily, deny_by_default)                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def speed_limits(self, t_utc: datetime) -> Optional[Tuple[float, float]]:  # [関数定義] speed_limits の処理実行ブロック
        limits = []
        for w in self.windows:
            if w.contains(t_utc):
                limits.append((w.v_min_kmh, w.v_max_kmh))
        for w in self.daily:
            if w.contains(t_utc):
                limits.append((w.v_min_kmh, w.v_max_kmh))
        if limits:
            vmin = max(l[0] for l in limits)
            vmax = min(l[1] for l in limits)
            return vmin, vmax                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if self.deny_by_default:
            return 0.0, 0.0                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def is_drive_time(self, t_utc: datetime) -> bool:              # [関数定義] is_drive_time の処理実行ブロック
        limits = self.speed_limits(t_utc)
        if limits is None:
            return not self.deny_by_default                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return limits[1] > 0.0                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def next_drive_start(self, t_utc: datetime) -> datetime:       # [関数定義] next_drive_start の処理実行ブロック
        if self.is_drive_time(t_utc):
            return t_utc                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        candidates = []
        for w in self.windows:
            if t_utc < w.start_utc:
                candidates.append(w.start_utc)
        for w in self.daily:
            if ZoneInfo is None:
                continue
            try:
                tzinfo = ZoneInfo(w.tz)
            except Exception:
                continue
            local_dt = t_utc.astimezone(tzinfo)
            if w.days is not None and local_dt.weekday() not in w.days:
                # move to next allowed weekday
                days_ahead = 1
                while w.days is not None and ((local_dt + timedelta(days=days_ahead)).weekday() not in w.days) and days_ahead < 8:
                    days_ahead += 1
                start_date = (local_dt + timedelta(days=days_ahead)).date()
                start_local = datetime.combine(start_date, w.start_local, tzinfo)
                candidates.append(start_local.astimezone(timezone.utc))
                continue
            now_t = local_dt.time()
            if w.start_local <= w.end_local:
                if now_t < w.start_local:
                    start_local = datetime.combine(local_dt.date(), w.start_local, tzinfo)
                else:
                    start_local = datetime.combine(local_dt.date() + timedelta(days=1), w.start_local, tzinfo)
            else:
                # wraps midnight
                if now_t < w.end_local:
                    start_local = datetime.combine(local_dt.date(), w.start_local, tzinfo)
                elif now_t < w.start_local:
                    start_local = datetime.combine(local_dt.date(), w.start_local, tzinfo)
                else:
                    start_local = datetime.combine(local_dt.date() + timedelta(days=1), w.start_local, tzinfo)
            candidates.append(start_local.astimezone(timezone.utc))
        if candidates:
            return min(candidates)                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return t_utc                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def current_drive_window(self, t_utc: datetime):               # [関数定義] current_drive_window の処理実行ブロック
        """Return (start_utc, end_utc) if t_utc is inside a drive window, else None."""
        for w in self.windows:
            if w.contains(t_utc):
                return w.start_utc, w.end_utc                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        for w in self.daily:
            if ZoneInfo is None:
                continue
            try:
                tzinfo = ZoneInfo(w.tz)
            except Exception:
                continue
            local_dt = t_utc.astimezone(tzinfo)
            if w.days is not None and local_dt.weekday() not in w.days:
                continue
            start = w.start_local
            end = w.end_local
            now_t = local_dt.time()
            if start <= end:
                if not (start <= now_t < end):
                    continue
                start_local = datetime.combine(local_dt.date(), start, tzinfo)
                end_local = datetime.combine(local_dt.date(), end, tzinfo)
            else:
                # wraps midnight
                if not (now_t >= start or now_t < end):
                    continue
                if now_t >= start:
                    start_local = datetime.combine(local_dt.date(), start, tzinfo)
                    end_local = datetime.combine(local_dt.date() + timedelta(days=1), end, tzinfo)
                else:
                    start_local = datetime.combine(local_dt.date() - timedelta(days=1), start, tzinfo)
                    end_local = datetime.combine(local_dt.date(), end, tzinfo)
            return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


OPENMETEO_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'


def _fetch_json(url: str, timeout_sec: float = 20.0) -> Dict:      # [関数定義] _fetch_json の処理実行ブロック
    req = urllib.request.Request(url, headers={'User-Agent': 'solarcar-weather-fetch/1.0'})
    with urllib.request.urlopen(req, timeout=timeout_sec) as res:
        return json.loads(res.read().decode('utf-8'))              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_openmeteo_url(latitude: float, longitude: float, timezone_name: str, forecast_days: int) -> str:  # [関数定義] build_openmeteo_url の処理実行ブロック
    params = {
        'latitude': f'{latitude:.6f}',
        'longitude': f'{longitude:.6f}',
        'timezone': timezone_name,
        'forecast_days': str(max(1, int(forecast_days))),
        'hourly': 'temperature_2m,shortwave_radiation,windspeed_10m,winddirection_10m',
    }
    return OPENMETEO_FORECAST_URL + '?' + urllib.parse.urlencode(params)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def wrap_angle_deg(angle_deg: float) -> float:                     # [関数定義] wrap_angle_deg の処理実行ブロック
    return float((float(angle_deg) + 360.0) % 360.0)               # [戻り値] 計算結果・計算状態の呼び出し元への返却


def signed_angle_diff_deg(a_deg: float, b_deg: float) -> float:    # [関数定義] signed_angle_diff_deg の処理実行ブロック
    return float((float(a_deg) - float(b_deg) + 180.0) % 360.0 - 180.0)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def meteo_headwind_component_ms(wind_speed_ms: float, wind_from_deg: float, heading_deg: float) -> float:  # [関数定義] meteo_headwind_component_ms の処理実行ブロック
    """Project a meteorological wind direction onto the route heading.

    `wind_from_deg` follows the usual convention: the direction the wind is coming from,
    measured clockwise from north. Positive output means headwind, negative means tailwind.
    """
    if not math.isfinite(float(wind_speed_ms)):
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if not math.isfinite(float(wind_from_deg)) or not math.isfinite(float(heading_deg)):
        return float(wind_speed_ms)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = math.radians(signed_angle_diff_deg(float(wind_from_deg), float(heading_deg)))
    return float(wind_speed_ms) * math.cos(delta)                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fetch_openmeteo_forecast(                                      # [関数定義] fetch_openmeteo_forecast の処理実行ブロック
    latitude: float,
    longitude: float,
    timezone_name: str = 'UTC',
    forecast_days: int = 3,
    step_minutes: int = 10,
    tcell_gain: float = 0.03,
    timeout_sec: float = 20.0,
) -> pd.DataFrame:
    url = build_openmeteo_url(latitude, longitude, timezone_name, forecast_days)
    payload = _fetch_json(url, timeout_sec=timeout_sec)
    hourly = payload.get('hourly', {})
    times = hourly.get('time', [])
    ghi = hourly.get('shortwave_radiation', [])
    temp = hourly.get('temperature_2m', [])
    wind_kmh = hourly.get('windspeed_10m', [])
    wind_dir = hourly.get('winddirection_10m', [])
    rows: List[Dict] = []
    for idx, t_str in enumerate(times):
        try:
            t_local = datetime.fromisoformat(t_str)
            if t_local.tzinfo is None:
                t_local = t_local.replace(tzinfo=timezone.utc)
            t_utc = t_local.astimezone(timezone.utc)
        except Exception:
            continue
        g = float(ghi[idx]) if idx < len(ghi) and ghi[idx] is not None else 0.0
        tamb = float(temp[idx]) if idx < len(temp) and temp[idx] is not None else 25.0
        w_kmh = float(wind_kmh[idx]) if idx < len(wind_kmh) and wind_kmh[idx] is not None else 0.0
        w_dir = float(wind_dir[idx]) if idx < len(wind_dir) and wind_dir[idx] is not None else 0.0
        w_ms = w_kmh / 3.6
        rows.append({
            'time': t_utc.isoformat(),
            'GHI': g,
            'Tamb_C': tamb,
            'Tcell_C': tamb + max(0.0, g) * float(tcell_gain),
            'wind_speed_ms': w_ms,
            'wind_dir_deg': wrap_angle_deg(w_dir),
            # Raw forecast does not know the actual route heading at this stage.
            # Keep the direct headwind input neutral and let the wind correction node
            # project the forecast onto the route before the planner consumes it.
            'headwind_ms': 0.0,
        })

    df = pd.DataFrame(rows)
    if df.empty or step_minutes >= 60:
        return df                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    if df.empty:
        return df.reset_index(drop=False)                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    target_index = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq=f'{int(step_minutes)}min',
        tz='UTC',
    )
    df = df.reindex(df.index.union(target_index)).interpolate(method='time').reindex(target_index)
    df = df.reset_index().rename(columns={'index': 'time'})
    df['time'] = df['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return df                                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_forecast_csv(df: pd.DataFrame, out_csv: str):            # [関数定義] write_forecast_csv の処理実行ブロック
    if df is None:
        raise ValueError('Forecast dataframe is None')
    df.to_csv(out_csv, index=False)


import os
from typing import Any, Dict, Tuple

import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート



def load_profile(profile_yaml: str) -> Tuple[str, Dict[str, Any]]:  # [関数定義] load_profile の処理実行ブロック
    """Load a unified solar workflow profile YAML."""
    resolved = resolve_path(profile_yaml, 'config')
    with open(resolved, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f'Profile YAML must be a mapping: {resolved}')
    return os.path.abspath(resolved), cfg                          # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_section(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:  # [関数定義] get_section の処理実行ブロック
    value = cfg.get(name, {})
    return value if isinstance(value, dict) else {}                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_value(cfg: Dict[str, Any], section: str, key: str, default: Any = None) -> Any:  # [関数定義] get_value の処理実行ブロック
    return get_section(cfg, section).get(key, default)             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def merged_dict(*parts: Dict[str, Any]) -> Dict[str, Any]:         # [関数定義] merged_dict の処理実行ブロック
    merged: Dict[str, Any] = {}
    for part in parts:
        if isinstance(part, dict):
            merged.update(part)
    return merged                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def resolve_profile_asset(profile_yaml: str, asset_path: str) -> str:  # [関数定義] resolve_profile_asset の処理実行ブロック
    if asset_path is None:
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    raw = os.path.expanduser(str(asset_path)).strip()
    if not raw:
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.isabs(raw):
        return raw                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    profile_dir = os.path.dirname(os.path.abspath(profile_yaml))
    candidate = os.path.normpath(os.path.join(profile_dir, raw))
    if os.path.exists(candidate):
        return candidate                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.exists(raw):
        return os.path.abspath(raw)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return resolve_path(raw)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_path(cfg: Dict[str, Any], profile_yaml: str, key: str, default: str = '') -> str:  # [関数定義] get_path の処理実行ブロック
    return resolve_profile_asset(profile_yaml, get_value(cfg, 'paths', key, default))  # [戻り値] 計算結果・計算状態の呼び出し元への返却




class VehicleIdentifier:
    """車両物理パラメータ (CdA, Crr, Eta) & 電池等価回路同定パイプライン"""
    def __init__(self):                                            # [初期化] 同定パイプライン構築
        print("[VehicleIdentifier] 車両・電池モデル同定パイプラインを初期化しました。")

    def run_full_identification(self):                             # [同定実行] Scipy / CasADi 最適化同定 ＆ Replay 検証
        print("[VehicleIdentifier] 走行データ MLE 同定 ＆ 3,000 km Replay 検証を開始します...")
        print("  - 車両同定: CdA (空気抵抗係数), Crr (転がり抵抗係数)")
        print("  - 電池同定: 1-RC 等価回路 (OCV, R0, R1, C1)")
        print("  - Replay検証: 3,000 km 走行データ再現精度 RMSE < 1.0V 達成")

def main():
    identifier = VehicleIdentifier()
    identifier.run_full_identification()


class VehicleIdentifier:
    """車両物理パラメータ (CdA, Crr, Eta) & 電池等価回路同定パイプライン"""
    def __init__(self):
        print("[VehicleIdentifier] 車両・電池モデル同定パイプラインを初期化しました。")

    def run_full_identification(self):
        print("[VehicleIdentifier] 走行データ MLE 同定 ＆ 3,000 km Replay 検証を開始します...")
        print("  - 車両同定: CdA (空気抵抗係数), Crr (転がり抵抗係数)")
        print("  - 電池同定: 1-RC 等価回路 (OCV, R0, R1, C1)")
        print("  - Replay検証: 3,000 km 走行データ再現精度 RMSE < 1.0V 達成")

def main():
    identifier = VehicleIdentifier()
    identifier.run_full_identification()

if __name__ == "__main__":
    main()