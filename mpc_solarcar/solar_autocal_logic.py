"""Pure helpers for bounded online solar-car calibration."""

from __future__ import annotations

import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート


def daytime_stationary_aux_estimate(                               # [関数定義] daytime_stationary_aux_estimate の処理実行ブロック
    *,
    ghi_wm2: float,
    day_ghi_threshold_wm2: float,
    speed_kmh: float,
    stationary_speed_kmh: float,
    pack_power_w: float,
    solar_power_w: float,
) -> float | None:
    values = (ghi_wm2, speed_kmh, pack_power_w, solar_power_w)
    if not all(math.isfinite(float(value)) for value in values):
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if float(ghi_wm2) < float(day_ghi_threshold_wm2):
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if abs(float(speed_kmh)) > float(stationary_speed_kmh):
        return None                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return max(0.0, float(pack_power_w) + float(solar_power_w))    # [戻り値] 計算結果・計算状態の呼び出し元への返却
