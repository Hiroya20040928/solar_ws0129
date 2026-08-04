"""Pure helpers for bounded online solar-car calibration."""

from __future__ import annotations

import math


def daytime_stationary_aux_estimate(
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
        return None
    if float(ghi_wm2) < float(day_ghi_threshold_wm2):
        return None
    if abs(float(speed_kmh)) > float(stationary_speed_kmh):
        return None
    return max(0.0, float(pack_power_w) + float(solar_power_w))
