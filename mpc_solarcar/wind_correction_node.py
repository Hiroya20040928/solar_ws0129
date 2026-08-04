import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import os
import tempfile
import time
from typing import Optional

import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from scipy.stats import norm
from std_msgs.msg import Float32, Float32MultiArray, String



def finite(value, default=math.nan):                               # [関数定義] finite の処理実行ブロック
    try:
        v = float(value)
        if math.isfinite(v):
            return v                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        pass
    return default                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


class WindCorrectionNode(Node):                                    # [クラス定義] WindCorrectionNode オブジェクトの設計
    WIND_STATE_KEYS = [
        'obs_headwind_ms',
        'forecast_now_ms',
        'posterior_now_ms',
        'posterior_now_std_ms',
        'route_heading_now_deg',
        'obs_source_code',
        'corrected_mean_now_ms',
        'corrected_std_now_ms',
        'corrected_lo95_now_ms',
        'corrected_hi95_now_ms',
        'planning_headwind_now_ms',
        'distance_weight_now',
    ]

    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('wind_correction_node')
        self.declare_parameter('forecast_csv_in', 'data/weather/live_forecast_raw.csv')
        self.declare_parameter('forecast_csv_out', 'data/weather/live_forecast_corrected.csv')
        self.declare_parameter('route_waypoints_csv', '')
        self.declare_parameter('publish_period_sec', 30.0)
        self.declare_parameter('measurement_sigma_ms', 1.0)
        self.declare_parameter('correlation_distance_km', 300.0)
        self.declare_parameter('fallback_correlation_time_h', 3.0)
        self.declare_parameter('forecast_sigma0_ms', 1.5)
        self.declare_parameter('forecast_variance_growth_per_hour', 0.05)
        self.declare_parameter('planning_quantile', 0.5)
        self.declare_parameter('confidence_z', 1.96)
        self.declare_parameter('min_sigma_ms', 0.2)
        self.declare_parameter('preferred_source', 'auto')
        self.declare_parameter('use_exp_distance_decay', True)

        self.forecast_csv_in = resolve_path(str(self.get_parameter('forecast_csv_in').value))
        self.forecast_csv_out = resolve_path(str(self.get_parameter('forecast_csv_out').value))
        self.route_waypoints_csv = resolve_path(str(self.get_parameter('route_waypoints_csv').value)) if str(self.get_parameter('route_waypoints_csv').value).strip() else ''
        self.measurement_sigma_ms = max(0.05, float(self.get_parameter('measurement_sigma_ms').value))
        self.correlation_distance_km = max(1.0, float(self.get_parameter('correlation_distance_km').value))
        self.fallback_correlation_time_h = max(0.1, float(self.get_parameter('fallback_correlation_time_h').value))
        self.forecast_sigma0_ms = max(0.1, float(self.get_parameter('forecast_sigma0_ms').value))
        self.forecast_variance_growth_per_hour = max(0.0, float(self.get_parameter('forecast_variance_growth_per_hour').value))
        self.planning_quantile = float(self.get_parameter('planning_quantile').value)
        self.confidence_z = max(0.1, float(self.get_parameter('confidence_z').value))
        self.min_sigma_ms = max(0.01, float(self.get_parameter('min_sigma_ms').value))
        self.preferred_source = str(self.get_parameter('preferred_source').value or 'auto').lower()
        self.use_exp_distance_decay = bool(self.get_parameter('use_exp_distance_decay').value)

        self.route_df = None
        if self.route_waypoints_csv and os.path.exists(self.route_waypoints_csv):
            try:
                self.route_df = pd.read_csv(self.route_waypoints_csv)
            except Exception as exc:
                self.get_logger().warn(f'Failed to load route waypoints: {exc}')

        self.forecast_df = pd.DataFrame()
        self.forecast_mtime = None

        self.s_km = math.nan
        self.speed_kmh = math.nan
        self.plan_dt_sec = math.nan
        self.plan_upper = []

        self.vehicle = {
            'wind_speed_ms': math.nan,
            'wind_dir_deg': math.nan,
            'course_deg': math.nan,
            'headwind_ms': math.nan,
        }
        self.chase = {
            'wind_speed_ms': math.nan,
            'wind_dir_deg': math.nan,
            'course_deg': math.nan,
            'headwind_ms': math.nan,
        }

        self.pub_wind_state = self.create_publisher(Float32MultiArray, '/planner/wind_state', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_status = self.create_publisher(String, '/system/wind_model_status', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        self.create_subscription(Float32, '/vehicle/s_km', self._set_scalar('s_km'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/speed_kmh', self._set_scalar('speed_kmh'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/upper_plan', self._on_upper_plan, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/wind_speed_ms', self._set_dict(self.vehicle, 'wind_speed_ms'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/wind_dir_deg', self._set_dict(self.vehicle, 'wind_dir_deg'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/course_deg', self._set_dict(self.vehicle, 'course_deg'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/vehicle/headwind_obs_ms', self._set_dict(self.vehicle, 'headwind_ms'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/chase/wind_speed_ms', self._set_dict(self.chase, 'wind_speed_ms'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/chase/wind_dir_deg', self._set_dict(self.chase, 'wind_dir_deg'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/chase/course_deg', self._set_dict(self.chase, 'course_deg'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/chase/headwind_obs_ms', self._set_dict(self.chase, 'headwind_ms'), 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        period = max(5.0, float(self.get_parameter('publish_period_sec').value))
        self.timer = self.create_timer(period, self._tick)
        self.get_logger().info(
            f'WindCorrectionNode started: in={self.forecast_csv_in}, out={self.forecast_csv_out}, '
            f'source={self.preferred_source}'
        )

    def _set_scalar(self, key):                                    # [関数定義] _set_scalar の処理実行ブロック
        def _handler(msg):                                         # [関数定義] _handler の処理実行ブロック
            setattr(self, key, finite(msg.data))
        return _handler                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _set_dict(self, target, key):                              # [関数定義] _set_dict の処理実行ブロック
        def _handler(msg):                                         # [関数定義] _handler の処理実行ブロック
            target[key] = finite(msg.data)
        return _handler                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _on_upper_plan(self, msg: Float32MultiArray):              # [関数定義] _on_upper_plan の処理実行ブロック
        data = list(msg.data)
        self.plan_dt_sec = float(data[0]) if len(data) >= 1 else math.nan
        self.plan_upper = [float(v) for v in data[1:]] if len(data) >= 2 else []

    def _reload_forecast_if_needed(self):                          # [関数定義] _reload_forecast_if_needed の処理実行ブロック
        try:
            mtime = os.path.getmtime(self.forecast_csv_in)
        except Exception:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if self.forecast_mtime is not None and mtime <= self.forecast_mtime:
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
        df = pd.read_csv(self.forecast_csv_in)
        if 'time' in df.columns:
            df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
            df = df.dropna(subset=['time']).sort_values('time').reset_index(drop=True)
        self.forecast_df = df
        self.forecast_mtime = mtime
        return True                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _pick_observation(self):                                   # [関数定義] _pick_observation の処理実行ブロック
        candidates = []
        for code, name, state in (
            (1.0, 'vehicle', self.vehicle),
            (2.0, 'chase', self.chase),
        ):
            direct = finite(state.get('headwind_ms', math.nan))
            course = finite(state.get('course_deg', math.nan))
            if not math.isfinite(course):
                course = self._route_heading_now()
            if math.isfinite(direct):
                candidates.append((code, name, direct, course))
                continue
            wind_speed = finite(state.get('wind_speed_ms', math.nan))
            wind_dir = finite(state.get('wind_dir_deg', math.nan))
            if math.isfinite(wind_speed) and math.isfinite(wind_dir) and math.isfinite(course):
                comp = meteo_headwind_component_ms(wind_speed, wind_dir, course)
                candidates.append((code, name, comp, course))
        if not candidates:
            return 0.0, '', math.nan, math.nan                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if self.preferred_source == 'vehicle':
            for cand in candidates:
                if cand[1] == 'vehicle':
                    return cand                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if self.preferred_source == 'chase':
            for cand in candidates:
                if cand[1] == 'chase':
                    return cand                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return candidates[0]                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _route_heading_now(self):                                  # [関数定義] _route_heading_now の処理実行ブロック
        if self.route_df is None or not math.isfinite(self.s_km):
            return math.nan                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return interpolate_route_heading(self.route_df, self.s_km)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _forecast_sigma_ms(self, row, lead_h: float):              # [関数定義] _forecast_sigma_ms の処理実行ブロック
        for key in ('headwind_std_ms', 'wind_std_ms', 'headwind_sigma_ms'):
            value = finite(row.get(key, math.nan)) if isinstance(row, pd.Series) else math.nan
            if math.isfinite(value):
                return max(self.min_sigma_ms, value)               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        var = self.forecast_sigma0_ms ** 2 + self.forecast_variance_growth_per_hour * max(0.0, lead_h)
        return max(self.min_sigma_ms, math.sqrt(max(var, self.min_sigma_ms ** 2)))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _estimate_future_s_km(self, lead_sec: float):              # [関数定義] _estimate_future_s_km の処理実行ブロック
        if not math.isfinite(self.s_km):
            return math.nan                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if lead_sec <= 0.0:
            return float(self.s_km)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
        dist_km = 0.0
        remaining = float(lead_sec)
        if math.isfinite(self.plan_dt_sec) and self.plan_dt_sec > 0.0 and self.plan_upper:
            dt = float(self.plan_dt_sec)
            for speed in self.plan_upper:
                if remaining <= 0.0:
                    break
                step = min(dt, remaining)
                dist_km += max(0.0, float(speed)) * (step / 3600.0)
                remaining -= step
        if remaining > 0.0 and math.isfinite(self.speed_kmh):
            dist_km += max(0.0, self.speed_kmh) * (remaining / 3600.0)
        return float(self.s_km) + dist_km                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _weight(self, ds_km: float, lead_h: float):                # [関数定義] _weight の処理実行ブロック
        if self.use_exp_distance_decay and math.isfinite(ds_km):
            return math.exp(-max(0.0, ds_km) / self.correlation_distance_km)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return math.exp(-max(0.0, lead_h) / self.fallback_correlation_time_h)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _compute_fcst_component(self, row, heading_deg: float):    # [関数定義] _compute_fcst_component の処理実行ブロック
        wind_speed = finite(row.get('wind_speed_ms', math.nan)) if isinstance(row, pd.Series) else math.nan
        wind_dir = finite(row.get('wind_dir_deg', math.nan)) if isinstance(row, pd.Series) else math.nan
        if math.isfinite(wind_speed) and math.isfinite(wind_dir) and math.isfinite(heading_deg):
            return meteo_headwind_component_ms(wind_speed, wind_dir, heading_deg)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return finite(row.get('headwind_ms', math.nan))            # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _tick(self):                                               # [関数定義] _tick の処理実行ブロック
        reloaded = self._reload_forecast_if_needed()
        if self.forecast_df.empty:
            self.pub_status.publish(String(data='wind model waiting forecast'))
            return

        source_code, source_name, obs_headwind, obs_course = self._pick_observation()
        if not math.isfinite(obs_headwind):
            self.pub_status.publish(String(data='wind model waiting observation'))
            return

        now_utc = pd.Timestamp.now(tz='UTC')
        df = self.forecast_df.copy()
        if 'time' in df.columns and not df['time'].isna().all():
            time_series = df['time']
            current_idx = int((time_series - now_utc).abs().idxmin())
        else:
            current_idx = 0

        current_row = df.iloc[current_idx].copy()
        route_heading_now = obs_course if math.isfinite(obs_course) else self._route_heading_now()
        fcst_now = self._compute_fcst_component(current_row, route_heading_now)
        sigma_fcst_now = self._forecast_sigma_ms(current_row, 0.0)

        var_fcst_now = max(self.min_sigma_ms ** 2, sigma_fcst_now ** 2)
        var_obs = max(self.min_sigma_ms ** 2, self.measurement_sigma_ms ** 2)
        posterior_now = (fcst_now / var_fcst_now + obs_headwind / var_obs) / (1.0 / var_fcst_now + 1.0 / var_obs)
        posterior_std_now = math.sqrt(1.0 / (1.0 / var_fcst_now + 1.0 / var_obs))
        correction_delta = posterior_now - fcst_now
        variance_shrink = max(0.0, var_fcst_now - posterior_std_now ** 2)

        zq = 0.0 if abs(self.planning_quantile - 0.5) < 1.0e-6 else float(norm.ppf(min(0.999, max(0.001, self.planning_quantile))))
        rows = []
        corrected_now = None

        for idx, row in df.iterrows():
            row = row.copy()
            lead_h = 0.0
            lead_sec = 0.0
            if 'time' in row and pd.notna(row['time']):
                lead_sec = max(0.0, float((row['time'] - now_utc).total_seconds()))
                lead_h = lead_sec / 3600.0
            s_future = self._estimate_future_s_km(lead_sec)
            ds_km = s_future - self.s_km if math.isfinite(s_future) and math.isfinite(self.s_km) else math.nan
            heading_future = route_heading_now
            if self.route_df is not None and math.isfinite(s_future):
                heading_future = interpolate_route_heading(self.route_df, s_future)
            fcst_component = self._compute_fcst_component(row, heading_future)
            sigma_fcst = self._forecast_sigma_ms(row, lead_h)
            w = self._weight(ds_km, lead_h)
            mu_corr = fcst_component + w * correction_delta
            sigma_corr2 = max(self.min_sigma_ms ** 2, sigma_fcst ** 2 - (w ** 2) * variance_shrink)
            sigma_corr = math.sqrt(sigma_corr2)
            lo95 = mu_corr - self.confidence_z * sigma_corr
            hi95 = mu_corr + self.confidence_z * sigma_corr
            plan_value = mu_corr + zq * sigma_corr

            row['route_heading_deg'] = heading_future if math.isfinite(heading_future) else math.nan
            row['headwind_fcst_ms'] = fcst_component
            row['headwind_corrected_mean_ms'] = mu_corr
            row['headwind_corrected_std_ms'] = sigma_corr
            row['headwind_corrected_lo95_ms'] = lo95
            row['headwind_corrected_hi95_ms'] = hi95
            row['headwind_plan_ms'] = plan_value
            row['headwind_ms'] = plan_value
            rows.append(row)

            if idx == current_idx:
                corrected_now = {
                    'mu': mu_corr,
                    'sigma': sigma_corr,
                    'lo95': lo95,
                    'hi95': hi95,
                    'plan': plan_value,
                    'weight': w,
                }

        out_df = pd.DataFrame(rows)
        self._atomic_write_csv(out_df, self.forecast_csv_out)

        corrected_now = corrected_now or {
            'mu': posterior_now,
            'sigma': posterior_std_now,
            'lo95': posterior_now - self.confidence_z * posterior_std_now,
            'hi95': posterior_now + self.confidence_z * posterior_std_now,
            'plan': posterior_now + zq * posterior_std_now,
            'weight': 1.0,
        }
        state = Float32MultiArray()
        state.data = [
            float(obs_headwind),
            float(fcst_now),
            float(posterior_now),
            float(posterior_std_now),
            float(route_heading_now if math.isfinite(route_heading_now) else math.nan),
            float(source_code),
            float(corrected_now['mu']),
            float(corrected_now['sigma']),
            float(corrected_now['lo95']),
            float(corrected_now['hi95']),
            float(corrected_now['plan']),
            float(corrected_now['weight']),
        ]
        self.pub_wind_state.publish(state)
        status = (
            f'source={source_name or "none"} obs={obs_headwind:.2f}m/s fcst={fcst_now:.2f} '
            f'post={posterior_now:.2f} sigma={corrected_now["sigma"]:.2f} '
            f'plan={corrected_now["plan"]:.2f} reloaded={reloaded}'
        )
        self.pub_status.publish(String(data=status))

    def _atomic_write_csv(self, df: pd.DataFrame, path: str):      # [関数定義] _atomic_write_csv の処理実行ブロック
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix='windcorr_', suffix='.csv', dir=os.path.dirname(os.path.abspath(path)))
        os.close(fd)
        try:
            out_df = df.copy()
            if 'time' in out_df.columns and pd.api.types.is_datetime64_any_dtype(out_df['time']):
                out_df['time'] = out_df['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
            out_df.to_csv(tmp_path, index=False)
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = WindCorrectionNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':                                         # [直接実行スクリプト] スクリプト直接起動時のメイン実行ブロック
    main()

# =============================================================================
# 【統合ユーティリティ】Open-Meteo 気象取得・風速風向成分計算関数群
# =============================================================================
import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


OPENMETEO_FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'


def _fetch_json(url: str, timeout_sec: float = 20.0) -> Dict:      # [関数定義] _fetch_json の処理実行ブロック
    req = urllib.request.Request(url, headers={'User-Agent': 'solarcar-weather-fetch/1.0'})
    with urllib.request.urlopen(req, timeout=timeout_sec) as res:
        return json.loads(res.read().decode('utf-8'))              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def build_openmeteo_url(latitude: float, longitude: float, timezone_name: str, forecast_days: int) -> str:  # [関数定義] build_openmeteo_url の処理実行ブロック
    params = {
        'latitude': f'{latitude:.6f}',
        'longitude': f'{longitude:.6f}',
        'timezone': timezone_name,
        'forecast_days': str(max(1, int(forecast_days))),
        'hourly': 'temperature_2m,shortwave_radiation,windspeed_10m,winddirection_10m',
    }
    return OPENMETEO_FORECAST_URL + '?' + urllib.parse.urlencode(params)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def wrap_angle_deg(angle_deg: float) -> float:                     # [関数定義] wrap_angle_deg の処理実行ブロック
    return float((float(angle_deg) + 360.0) % 360.0)               # [戻り値] 計算結果・計算状態の呼び出し元への返却


def signed_angle_diff_deg(a_deg: float, b_deg: float) -> float:    # [関数定義] signed_angle_diff_deg の処理実行ブロック
    return float((float(a_deg) - float(b_deg) + 180.0) % 360.0 - 180.0)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def meteo_headwind_component_ms(wind_speed_ms: float, wind_from_deg: float, heading_deg: float) -> float:  # [関数定義] meteo_headwind_component_ms の処理実行ブロック
    """Project a meteorological wind direction onto the route heading.

    `wind_from_deg` follows the usual convention: the direction the wind is coming from,
    measured clockwise from north. Positive output means headwind, negative means tailwind.
    """
    if not math.isfinite(float(wind_speed_ms)):
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if not math.isfinite(float(wind_from_deg)) or not math.isfinite(float(heading_deg)):
        return float(wind_speed_ms)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    delta = math.radians(signed_angle_diff_deg(float(wind_from_deg), float(heading_deg)))
    return float(wind_speed_ms) * math.cos(delta)                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def fetch_openmeteo_forecast(                                      # [関数定義] fetch_openmeteo_forecast の処理実行ブロック
    latitude: float,
    longitude: float,
    timezone_name: str = 'UTC',
    forecast_days: int = 3,
    step_minutes: int = 10,
    tcell_gain: float = 0.03,
    timeout_sec: float = 20.0,
) -> pd.DataFrame:
    url = build_openmeteo_url(latitude, longitude, timezone_name, forecast_days)
    payload = _fetch_json(url, timeout_sec=timeout_sec)
    hourly = payload.get('hourly', {})
    times = hourly.get('time', [])
    ghi = hourly.get('shortwave_radiation', [])
    temp = hourly.get('temperature_2m', [])
    wind_kmh = hourly.get('windspeed_10m', [])
    wind_dir = hourly.get('winddirection_10m', [])
    rows: List[Dict] = []
    for idx, t_str in enumerate(times):
        try:
            t_local = datetime.fromisoformat(t_str)
            if t_local.tzinfo is None:
                t_local = t_local.replace(tzinfo=timezone.utc)
            t_utc = t_local.astimezone(timezone.utc)
        except Exception:
            continue
        g = float(ghi[idx]) if idx < len(ghi) and ghi[idx] is not None else 0.0
        tamb = float(temp[idx]) if idx < len(temp) and temp[idx] is not None else 25.0
        w_kmh = float(wind_kmh[idx]) if idx < len(wind_kmh) and wind_kmh[idx] is not None else 0.0
        w_dir = float(wind_dir[idx]) if idx < len(wind_dir) and wind_dir[idx] is not None else 0.0
        w_ms = w_kmh / 3.6
        rows.append({
            'time': t_utc.isoformat(),
            'GHI': g,
            'Tamb_C': tamb,
            'Tcell_C': tamb + max(0.0, g) * float(tcell_gain),
            'wind_speed_ms': w_ms,
            'wind_dir_deg': wrap_angle_deg(w_dir),
            # Raw forecast does not know the actual route heading at this stage.
            # Keep the direct headwind input neutral and let the wind correction node
            # project the forecast onto the route before the planner consumes it.
            'headwind_ms': 0.0,
        })

    df = pd.DataFrame(rows)
    if df.empty or step_minutes >= 60:
        return df                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    df['time'] = pd.to_datetime(df['time'], utc=True, errors='coerce')
    df = df.dropna(subset=['time']).set_index('time').sort_index()
    if df.empty:
        return df.reset_index(drop=False)                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    target_index = pd.date_range(
        start=df.index[0],
        end=df.index[-1],
        freq=f'{int(step_minutes)}min',
        tz='UTC',
    )
    df = df.reindex(df.index.union(target_index)).interpolate(method='time').reindex(target_index)
    df = df.reset_index().rename(columns={'index': 'time'})
    df['time'] = df['time'].dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return df                                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_forecast_csv(df: pd.DataFrame, out_csv: str):            # [関数定義] write_forecast_csv の処理実行ブロック
    if df is None:
        raise ValueError('Forecast dataframe is None')
    df.to_csv(out_csv, index=False)


import os
from pathlib import Path

try:
    from ament_index_python.packages import get_package_share_directory  # type: ignore
except Exception:  # pragma: no cover - non-ROS fallback
    get_package_share_directory = None


PKG_NAME = 'mpc_solarcar'
REPO_ROOT = Path(__file__).resolve().parents[1]


def resolve_path(path: str, default_subdir: str = '') -> str:      # [関数定義] resolve_path の処理実行ブロック
    """Resolve a path relative to CWD or package share.

    - If absolute, return as-is.                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - If exists relative to CWD, return it.                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    - Otherwise, resolve under <pkg_share>/<default_subdir> (or directly under share).
    """
    if path is None:
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.exists(path):
        return path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if get_package_share_directory is not None:
        pkg_share = get_package_share_directory(PKG_NAME)
    else:
        pkg_share = os.fspath(REPO_ROOT)
    if default_subdir:
        subdir = default_subdir.strip('/\\')
        if path.startswith(subdir + os.sep) or path == subdir:
            return os.path.join(pkg_share, path)                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return os.path.join(pkg_share, subdir, path)               # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return os.path.join(pkg_share, path)                           # [戻り値] 計算結果・計算状態の呼び出し元への返却