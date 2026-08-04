import os
from datetime import datetime, timezone

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import String



class WeatherFetchNode(Node):                                      # [クラス定義] WeatherFetchNode オブジェクトの設計
    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('weather_fetch_node')
        self.declare_parameter('provider', 'openmeteo')
        self.declare_parameter('forecast_csv', 'data/weather/live_forecast.csv')
        self.declare_parameter('gps_topic', '/chase/gps')
        self.declare_parameter('fetch_period_sec', 3600.0)
        self.declare_parameter('forecast_days', 3)
        self.declare_parameter('step_minutes', 10)
        self.declare_parameter('timezone_name', 'Australia/Darwin')
        self.declare_parameter('fallback_latitude', -12.4634)
        self.declare_parameter('fallback_longitude', 130.8456)
        self.declare_parameter('tcell_gain', 0.03)

        self.provider = str(self.get_parameter('provider').value).lower()
        self.forecast_csv = resolve_path(self.get_parameter('forecast_csv').value)
        self.fetch_period_sec = float(self.get_parameter('fetch_period_sec').value)
        self.forecast_days = int(self.get_parameter('forecast_days').value)
        self.step_minutes = int(self.get_parameter('step_minutes').value)
        self.timezone_name = str(self.get_parameter('timezone_name').value)
        self.tcell_gain = float(self.get_parameter('tcell_gain').value)
        self.lat = float(self.get_parameter('fallback_latitude').value)
        self.lon = float(self.get_parameter('fallback_longitude').value)
        self.has_gps = False
        self.last_status = 'waiting for first fetch'

        gps_topic = str(self.get_parameter('gps_topic').value)
        self.create_subscription(NavSatFix, gps_topic, self._on_gps, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.pub_status = self.create_publisher(String, '/system/forecast_status', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        os.makedirs(os.path.dirname(os.path.abspath(self.forecast_csv)), exist_ok=True)
        self._fetch_once()
        self.timer = self.create_timer(max(60.0, self.fetch_period_sec), self._fetch_once)
        self.get_logger().info(f'WeatherFetchNode started: provider={self.provider}, out={self.forecast_csv}')

    def _on_gps(self, msg: NavSatFix):                             # [関数定義] _on_gps の処理実行ブロック
        if msg.latitude == 0.0 and msg.longitude == 0.0:
            return
        self.lat = float(msg.latitude)
        self.lon = float(msg.longitude)
        self.has_gps = True

    def _fetch_once(self):                                         # [関数定義] _fetch_once の処理実行ブロック
        if self.provider != 'openmeteo':
            self.last_status = f'provider={self.provider} not implemented'
            self.pub_status.publish(String(data=self.last_status))
            return
        try:
            df = fetch_openmeteo_forecast(
                self.lat,
                self.lon,
                timezone_name=self.timezone_name,
                forecast_days=self.forecast_days,
                step_minutes=self.step_minutes,
                tcell_gain=self.tcell_gain,
            )
            write_forecast_csv(df, self.forecast_csv)
            stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            src = 'gps' if self.has_gps else 'fallback'
            self.last_status = f'openmeteo {stamp} lat={self.lat:.5f} lon={self.lon:.5f} src={src} rows={len(df)}'
            self.get_logger().info(self.last_status)
        except Exception as exc:
            self.last_status = f'forecast fetch failed: {exc}'
            self.get_logger().warn(self.last_status)
        self.pub_status.publish(String(data=self.last_status))


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = WeatherFetchNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

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