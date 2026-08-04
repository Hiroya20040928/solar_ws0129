import os
from dataclasses import dataclass
from datetime import datetime, time as dtime, timedelta, timezone
from typing import List, Optional, Tuple

import yaml

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - fallback for older Python
    ZoneInfo = None


def _parse_utc(ts: str) -> Optional[datetime]:
    try:
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_time_hhmm(s: str) -> Optional[dtime]:
    try:
        parts = s.strip().split(':')
        if len(parts) < 2:
            return None
        return dtime(hour=int(parts[0]), minute=int(parts[1]))
    except Exception:
        return None


@dataclass
class DriveWindow:
    start_utc: datetime
    end_utc: datetime
    v_min_kmh: float
    v_max_kmh: float

    def contains(self, t_utc: datetime) -> bool:
        return self.start_utc <= t_utc < self.end_utc


@dataclass
class DailyWindow:
    start_local: dtime
    end_local: dtime
    tz: str
    days: Optional[List[int]]
    v_min_kmh: float
    v_max_kmh: float

    def contains(self, t_utc: datetime) -> bool:
        if ZoneInfo is None:
            return False
        try:
            tzinfo = ZoneInfo(self.tz)
        except Exception:
            return False
        local_dt = t_utc.astimezone(tzinfo)
        if self.days is not None and local_dt.weekday() not in self.days:
            return False
        start = self.start_local
        end = self.end_local
        now_t = local_dt.time()
        if start <= end:
            return start <= now_t < end
        # wraps midnight
        return now_t >= start or now_t < end


class DriveSchedule:
    def __init__(self, windows: List[DriveWindow], daily: List[DailyWindow], deny_by_default: bool):
        self.windows = windows
        self.daily = daily
        self.deny_by_default = deny_by_default

    @classmethod
    def from_yaml(cls, path: str) -> Optional['DriveSchedule']:
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            return None
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
        return cls(windows, daily, deny_by_default)

    def speed_limits(self, t_utc: datetime) -> Optional[Tuple[float, float]]:
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
            return vmin, vmax
        if self.deny_by_default:
            return 0.0, 0.0
        return None

    def is_drive_time(self, t_utc: datetime) -> bool:
        limits = self.speed_limits(t_utc)
        if limits is None:
            return not self.deny_by_default
        return limits[1] > 0.0

    def next_drive_start(self, t_utc: datetime) -> datetime:
        if self.is_drive_time(t_utc):
            return t_utc
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
            return min(candidates)
        return t_utc

    def current_drive_window(self, t_utc: datetime):
        """Return (start_utc, end_utc) if t_utc is inside a drive window, else None."""
        for w in self.windows:
            if w.contains(t_utc):
                return w.start_utc, w.end_utc
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
            return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)
        return None
