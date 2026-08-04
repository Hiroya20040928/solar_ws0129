import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import time
from collections import deque


def finite_float(value, default=math.nan):                         # [関数定義] finite_float の処理実行ブロック
    try:
        v = float(value)
        if math.isfinite(v):
            return v                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        pass
    return default                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def clamp(value, lo=None, hi=None):                                # [関数定義] clamp の処理実行ブロック
    v = float(value)
    if lo is not None:
        v = max(float(lo), v)
    if hi is not None:
        v = min(float(hi), v)
    return v                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fresh_enough(timestamp, timeout_sec, now=None):                # [関数定義] fresh_enough の処理実行ブロック
    if timestamp is None:
        return False                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if timeout_sec is None or float(timeout_sec) <= 0.0:
        return True                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if now is None:
        now = time.monotonic()
    return (float(now) - float(timestamp)) <= float(timeout_sec)   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def slew_limit(previous, target, dt, rise_rate=None, fall_rate=None):  # [関数定義] slew_limit の処理実行ブロック
    prev = float(previous)
    tgt = float(target)
    dt = max(0.0, float(dt))
    if not math.isfinite(prev) or dt <= 0.0:
        return tgt                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = tgt - prev
    if delta >= 0.0 and rise_rate is not None and math.isfinite(float(rise_rate)) and float(rise_rate) > 0.0:
        delta = min(delta, float(rise_rate) * dt)
    if delta < 0.0 and fall_rate is not None and math.isfinite(float(fall_rate)) and float(fall_rate) > 0.0:
        delta = max(delta, -float(fall_rate) * dt)
    return prev + delta                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却


class SmoothRateLimiter:                                           # [クラス定義] SmoothRateLimiter オブジェクトの設計
    def __init__(                                                  # [関数定義] __init__ の処理実行ブロック
        self,
        *,
        min_value=None,
        max_value=None,
        tau_sec=0.0,
        rise_rate=None,
        fall_rate=None,
        deadband=0.0,
        quantize_step=0.0,
        initial_value=math.nan,
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.tau_sec = max(0.0, float(tau_sec))
        self.rise_rate = rise_rate
        self.fall_rate = fall_rate
        self.deadband = max(0.0, float(deadband))
        self.quantize_step = max(0.0, float(quantize_step))
        self.value = float(initial_value) if math.isfinite(finite_float(initial_value)) else math.nan
        self.last_time = None

    def reset(self, value=math.nan, now=None):                     # [関数定義] reset の処理実行ブロック
        self.value = finite_float(value)
        self.last_time = time.monotonic() if now is None else float(now)
        return self.value                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def update(self, target, now=None):                            # [関数定義] update の処理実行ブロック
        tgt = finite_float(target)
        if not math.isfinite(tgt):
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        tgt = clamp(tgt, self.min_value, self.max_value)
        now_mono = time.monotonic() if now is None else float(now)
        if not math.isfinite(self.value):
            self.value = tgt
            self.last_time = now_mono
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却

        dt = 0.0 if self.last_time is None else max(1.0e-3, now_mono - float(self.last_time))
        if self.tau_sec > 0.0 and dt > 0.0:
            alpha = 1.0 - math.exp(-dt / self.tau_sec)
            candidate = self.value + alpha * (tgt - self.value)
        else:
            candidate = tgt

        candidate = slew_limit(self.value, candidate, dt, self.rise_rate, self.fall_rate)
        candidate = clamp(candidate, self.min_value, self.max_value)

        if self.deadband > 0.0 and abs(candidate - self.value) < self.deadband:
            candidate = self.value

        if self.quantize_step > 0.0:
            candidate = round(candidate / self.quantize_step) * self.quantize_step

        self.value = clamp(candidate, self.min_value, self.max_value)
        self.last_time = now_mono
        return self.value                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却


class RobustScalarFilter:                                          # [クラス定義] RobustScalarFilter オブジェクトの設計
    def __init__(                                                  # [関数定義] __init__ の処理実行ブロック
        self,
        *,
        min_value=None,
        max_value=None,
        tau_sec=0.0,
        rise_rate=None,
        fall_rate=None,
        deadband=0.0,
        quantize_step=0.0,
        median_window=1,
        monotonic=False,
        max_backtrack=0.0,
        initial_value=math.nan,
    ):
        self.min_value = min_value
        self.max_value = max_value
        self.monotonic = bool(monotonic)
        self.max_backtrack = max(0.0, float(max_backtrack))
        self.window = deque(maxlen=max(1, int(median_window)))
        self.smoother = SmoothRateLimiter(
            min_value=min_value,
            max_value=max_value,
            tau_sec=tau_sec,
            rise_rate=rise_rate,
            fall_rate=fall_rate,
            deadband=deadband,
            quantize_step=quantize_step,
            initial_value=initial_value,
        )

    @property
    def value(self):                                               # [関数定義] value の処理実行ブロック
        return self.smoother.value                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    @property
    def last_time(self):                                           # [関数定義] last_time の処理実行ブロック
        return self.smoother.last_time                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def reset(self, value=math.nan, now=None):                     # [関数定義] reset の処理実行ブロック
        self.window.clear()
        v = finite_float(value)
        if math.isfinite(v):
            self.window.append(v)
        return self.smoother.reset(v, now=now)                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def update(self, raw_value, now=None):                         # [関数定義] update の処理実行ブロック
        value = finite_float(raw_value)
        if not math.isfinite(value):
            return self.value                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
        value = clamp(value, self.min_value, self.max_value)
        self.window.append(value)
        candidate = value
        if len(self.window) > 1:
            seq = sorted(self.window)
            candidate = float(seq[len(seq) // 2])
        if self.monotonic and math.isfinite(self.value):
            candidate = max(candidate, float(self.value) - self.max_backtrack)
        return self.smoother.update(candidate, now=now)            # [戻り値] 計算結果・計算状態の呼び出し元への返却
