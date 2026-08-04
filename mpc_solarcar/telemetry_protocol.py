"""Timestamp validation shared by the WiFi telemetry receiver and tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math


@dataclass(frozen=True)
class TimestampValidation:
    accepted: bool
    source_unix: float | None
    age_sec: float | None
    reason: str


def parse_source_timestamp(payload: dict) -> float | None:
    """Return a UTC Unix timestamp from the supported wire-format fields."""
    for key in ("ts_unix", "timestamp_unix", "time_unix"):
        if key not in payload:
            continue
        try:
            value = float(payload[key])
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value

    for key in ("timestamp_utc", "ts_utc", "time_utc"):
        raw = str(payload.get(key, "")).strip()
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            continue
        return parsed.astimezone(timezone.utc).timestamp()
    return None


def validate_source_timestamp(
    payload: dict,
    *,
    now_unix: float,
    last_source_unix: float | None,
    required: bool,
    max_age_sec: float,
    max_future_skew_sec: float,
    max_out_of_order_sec: float,
) -> TimestampValidation:
    """Reject stale, future, duplicate, or excessively reordered UDP packets."""
    source_unix = parse_source_timestamp(payload)
    if source_unix is None:
        if required:
            return TimestampValidation(False, None, None, "missing_or_invalid_timestamp")
        return TimestampValidation(True, None, None, "timestamp_not_required")

    age_sec = float(now_unix) - source_unix
    if age_sec > max(0.0, float(max_age_sec)):
        return TimestampValidation(False, source_unix, age_sec, "stale_packet")
    if age_sec < -max(0.0, float(max_future_skew_sec)):
        return TimestampValidation(False, source_unix, age_sec, "future_packet")
    if last_source_unix is not None:
        tolerance = max(0.0, float(max_out_of_order_sec))
        if source_unix == last_source_unix:
            return TimestampValidation(False, source_unix, age_sec, "duplicate_packet")
        if source_unix < last_source_unix - tolerance:
            return TimestampValidation(False, source_unix, age_sec, "out_of_order_packet")
    return TimestampValidation(True, source_unix, age_sec, "ok")


def utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
