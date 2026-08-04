from __future__ import annotations

from datetime import datetime

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


FORECAST_GRID_COLUMNS = (
    "GHI",
    "DNI",
    "DHI",
    "POA_drive",
    "POA_stop_ideal",
    "Tamb_C",
    "Tcell_C",
    "Tcell_drive_C",
    "Tcell_stop_ideal_C",
    "headwind_ms",
)


def timestamp_ns(value) -> int:                                    # [関数定義] timestamp_ns の処理実行ブロック
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return int(ts.value)                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def forecast_distance_column(df: pd.DataFrame) -> str:             # [関数定義] forecast_distance_column の処理実行ブロック
    if not isinstance(df, pd.DataFrame):
        return ""                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if "s_km" in df.columns:
        return "s_km"                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if "route_progress_km" in df.columns:
        return "route_progress_km"                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return ""                                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_forecast_grid_payload(df: pd.DataFrame) -> dict | None:  # [関数定義] build_forecast_grid_payload の処理実行ブロック
    """Build matrices used for bilinear interpolation over UTC time and route distance."""
    dist_col = forecast_distance_column(df)
    if not dist_col or "time" not in df.columns:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    work = df.copy()
    work[dist_col] = pd.to_numeric(work[dist_col], errors="coerce")
    work = work.dropna(subset=["time", dist_col]).sort_values(["time", dist_col])
    if work.empty:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    time_index = pd.Index(work["time"].drop_duplicates().sort_values())
    s_grid = np.array(sorted(work[dist_col].dropna().unique()), dtype=float)
    if len(time_index) < 2 or len(s_grid) < 2:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if len(work) <= max(len(time_index), len(s_grid)):
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    work = work.drop_duplicates(subset=["time", dist_col], keep="last")
    matrices = {}
    for col in FORECAST_GRID_COLUMNS:
        if col not in work.columns:
            continue
        pivot = (
            work.pivot(index="time", columns=dist_col, values=col)
            .reindex(index=time_index, columns=s_grid)
            .apply(pd.to_numeric, errors="coerce")
            .interpolate(axis=0, limit_direction="both")
            .interpolate(axis=1, limit_direction="both")
            .ffill()
            .bfill()
            .ffill(axis=1)
            .bfill(axis=1)
        )
        matrices[col] = pivot.to_numpy(dtype=float)
    if not matrices:
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "dist_col": dist_col,
        "time_ns": np.array([timestamp_ns(value) for value in time_index], dtype=np.int64),
        "s_grid": s_grid,
        "matrices": matrices,
    }


def interp_forecast_grid(                                          # [関数定義] interp_forecast_grid の処理実行ブロック
    payload: dict | None,
    col: str,
    t_utc: datetime,
    s_km: float | None,
    default: float,
) -> float:
    """Bilinearly interpolate one weather field, clamping only outside grid coverage."""
    if not payload:
        return float(default)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    matrix = payload.get("matrices", {}).get(col)
    tg = payload.get("time_ns")
    sg = payload.get("s_grid")
    if matrix is None or tg is None or sg is None or len(tg) == 0 or len(sg) == 0:
        return float(default)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    t_ns = int(np.clip(timestamp_ns(t_utc), int(tg[0]), int(tg[-1])))
    s_val = float(s_km if s_km is not None else sg[0])
    s_val = float(np.clip(s_val, float(sg[0]), float(sg[-1])))

    i_hi = int(np.searchsorted(tg, t_ns, side="left"))
    if i_hi <= 0:
        i0 = i1 = 0
        wt = 0.0
    elif i_hi >= len(tg):
        i0 = i1 = len(tg) - 1
        wt = 0.0
    else:
        i0 = i_hi - 1
        i1 = i_hi
        wt = float((t_ns - int(tg[i0])) / max(int(tg[i1]) - int(tg[i0]), 1))

    j_hi = int(np.searchsorted(sg, s_val, side="left"))
    if j_hi <= 0:
        j0 = j1 = 0
        ws = 0.0
    elif j_hi >= len(sg):
        j0 = j1 = len(sg) - 1
        ws = 0.0
    else:
        j0 = j_hi - 1
        j1 = j_hi
        ws = float((s_val - float(sg[j0])) / max(float(sg[j1]) - float(sg[j0]), 1.0e-9))

    v0 = (1.0 - ws) * float(matrix[i0, j0]) + ws * float(matrix[i0, j1])
    v1 = (1.0 - ws) * float(matrix[i1, j0]) + ws * float(matrix[i1, j1])
    return float((1.0 - wt) * v0 + wt * v1)                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
