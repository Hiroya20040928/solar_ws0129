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
