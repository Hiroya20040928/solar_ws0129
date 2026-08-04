from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def _finite_vector(values, *, name: str) -> np.ndarray:
    vector = np.asarray(values, dtype=float)
    if vector.ndim != 1 or len(vector) == 0 or not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} must be a non-empty finite one-dimensional array")
    return vector


def absolute_control_distances(start_s_km: float, relative_control_s_km) -> np.ndarray:
    """Convert a horizon-relative control mesh to route-absolute distances."""
    start = float(start_s_km)
    if not np.isfinite(start):
        raise ValueError("start_s_km must be finite")
    relative = _finite_vector(relative_control_s_km, name="relative_control_s_km")
    if np.any(relative < -1.0e-9) or np.any(np.diff(relative) < -1.0e-9):
        raise ValueError("relative_control_s_km must be non-negative and non-decreasing")
    return start + relative


def shift_upper_policy_warm_start(
    previous_control_s_km,
    previous_speeds_kmh,
    current_control_s_km,
    *,
    minimum_speed_kmh: float,
    maximum_speed_kmh: float,
) -> np.ndarray:
    """Shift a prior route-indexed policy onto the current absolute control mesh."""
    previous_s = _finite_vector(previous_control_s_km, name="previous_control_s_km")
    previous_v = _finite_vector(previous_speeds_kmh, name="previous_speeds_kmh")
    current_s = _finite_vector(current_control_s_km, name="current_control_s_km")
    if len(previous_s) != len(previous_v):
        raise ValueError("previous control distances and speeds must have equal length")
    if np.any(np.diff(current_s) < -1.0e-9):
        raise ValueError("current_control_s_km must be non-decreasing")

    order = np.argsort(previous_s, kind="stable")
    previous_s = previous_s[order]
    previous_v = previous_v[order]
    unique_s, reverse_index = np.unique(previous_s[::-1], return_index=True)
    keep = len(previous_s) - 1 - reverse_index
    keep = keep[np.argsort(unique_s)]
    previous_s = previous_s[keep]
    previous_v = previous_v[keep]

    shifted = np.interp(current_s, previous_s, previous_v)
    return np.clip(shifted, float(minimum_speed_kmh), float(maximum_speed_kmh))


def load_upper_policy_csv(path: str | Path) -> pd.DataFrame:
    """Load a distance-indexed upper speed policy with strict schema checks."""
    policy_path = Path(path)
    frame = pd.read_csv(policy_path)
    required = {"s_km", "v_kmh"}
    if not required.issubset(frame.columns):
        raise ValueError(f"upper policy must contain {sorted(required)}: {policy_path}")
    out = frame.loc[:, ["s_km", "v_kmh"]].copy()
    out["s_km"] = pd.to_numeric(out["s_km"], errors="coerce")
    out["v_kmh"] = pd.to_numeric(out["v_kmh"], errors="coerce")
    out = (
        out.replace([np.inf, -np.inf], np.nan)
        .dropna()
        .sort_values("s_km")
        .drop_duplicates("s_km", keep="last")
        .reset_index(drop=True)
    )
    if len(out) < 2:
        raise ValueError(f"upper policy needs at least two finite distance points: {policy_path}")
    if float(out["s_km"].iloc[-1]) <= float(out["s_km"].iloc[0]):
        raise ValueError(f"upper policy distance must increase: {policy_path}")
    return out


def interpolate_upper_policy(
    frame: pd.DataFrame,
    control_s_km,
    *,
    minimum_speed_kmh: float,
    maximum_speed_kmh: float,
) -> np.ndarray:
    """Interpolate a learned full-course policy onto the current MPC control mesh."""
    control_s = _finite_vector(control_s_km, name="control_s_km")
    source_s = pd.to_numeric(frame["s_km"], errors="coerce").to_numpy(dtype=float)
    source_v = pd.to_numeric(frame["v_kmh"], errors="coerce").to_numpy(dtype=float)
    if len(source_s) < 2 or not np.all(np.isfinite(source_s)) or not np.all(np.isfinite(source_v)):
        raise ValueError("upper policy contains non-finite or insufficient points")
    interpolated = np.interp(control_s, source_s, source_v)
    return np.clip(interpolated, float(minimum_speed_kmh), float(maximum_speed_kmh))
