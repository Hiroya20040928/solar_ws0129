#!/usr/bin/env python3
from __future__ import annotations

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

from mpc_solarcar.model import Params, SolarCarModel
from mpc_solarcar.route_utils import interpolate_profile, interpolate_route, interpolate_route_heading
from mpc_solarcar.utils_maps import bilinear_interp

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

    x0 = np.zeros(1 + nx + ny, dtype=float)
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


if __name__ == "__main__":
    main()
