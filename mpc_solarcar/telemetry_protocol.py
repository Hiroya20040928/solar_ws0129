"""Timestamp validation shared by the WiFi telemetry receiver and tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート


@dataclass(frozen=True)
class TimestampValidation:                                         # [クラス定義] TimestampValidation オブジェクトの設計
    accepted: bool
    source_unix: float | None
    age_sec: float | None
    reason: str


def parse_source_timestamp(payload: dict) -> float | None:         # [関数定義] parse_source_timestamp の処理実行ブロック
    """Return a UTC Unix timestamp from the supported wire-format fields."""
    for key in ("ts_unix", "timestamp_unix", "time_unix"):
        if key not in payload:
            continue
        try:
            value = float(payload[key])
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return value                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却

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
        return parsed.astimezone(timezone.utc).timestamp()         # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return None                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def validate_source_timestamp(                                     # [関数定義] validate_source_timestamp の処理実行ブロック
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
            return TimestampValidation(False, None, None, "missing_or_invalid_timestamp")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return TimestampValidation(True, None, None, "timestamp_not_required")  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    age_sec = float(now_unix) - source_unix
    if age_sec > max(0.0, float(max_age_sec)):
        return TimestampValidation(False, source_unix, age_sec, "stale_packet")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if age_sec < -max(0.0, float(max_future_skew_sec)):
        return TimestampValidation(False, source_unix, age_sec, "future_packet")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if last_source_unix is not None:
        tolerance = max(0.0, float(max_out_of_order_sec))
        if source_unix == last_source_unix:
            return TimestampValidation(False, source_unix, age_sec, "duplicate_packet")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if source_unix < last_source_unix - tolerance:
            return TimestampValidation(False, source_unix, age_sec, "out_of_order_packet")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return TimestampValidation(True, source_unix, age_sec, "ok")   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def utc_iso_now() -> str:                                          # [関数定義] utc_iso_now の処理実行ブロック
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
