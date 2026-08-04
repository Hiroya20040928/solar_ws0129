import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート


def _interp_field(d, y, s_km, default=0.0):                        # [関数定義] _interp_field の処理実行ブロック
    if len(d) < 2:
        return float(default)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    s = np.clip(s_km, d[0], d[-1])
    i = np.searchsorted(d, s) - 1
    i = np.clip(i, 0, len(d) - 2)
    t = 0.0 if d[i + 1] == d[i] else (s - d[i]) / (d[i + 1] - d[i])
    return float((1 - t) * y[i] + t * y[i + 1])                    # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route(route_df, s_km):                             # [関数定義] interpolate_route の処理実行ブロック
    d = route_df['dist_km'].values
    lat = route_df['lat'].values
    lon = route_df['lon'].values
    latp = _interp_field(d, lat, s_km, default=float(lat[0]) if len(lat) else 0.0)
    lonp = _interp_field(d, lon, s_km, default=float(lon[0]) if len(lon) else 0.0)
    return latp, lonp                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route_with_alt(route_df, s_km):                    # [関数定義] interpolate_route_with_alt の処理実行ブロック
    lat, lon = interpolate_route(route_df, s_km)
    alt = None
    for col in ('alt_m', 'altitude_m', 'elev_m'):
        if col in route_df.columns:
            d = route_df['dist_km'].values
            alt = _interp_field(d, route_df[col].values, s_km, default=float(route_df[col].values[0]))
            break
    return lat, lon, alt                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_profile(route_df, s_km, field: str, default: float = 0.0) -> float:  # [関数定義] interpolate_profile の処理実行ブロック
    if field not in route_df.columns:
        return float(default)                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    d = route_df['dist_km'].values
    return _interp_field(d, route_df[field].values, s_km, default=default)  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def bearing_deg(lat1, lon1, lat2, lon2):                           # [関数定義] bearing_deg の処理実行ブロック
    lat1r = np.deg2rad(float(lat1))
    lon1r = np.deg2rad(float(lon1))
    lat2r = np.deg2rad(float(lat2))
    lon2r = np.deg2rad(float(lon2))
    dlon = lon2r - lon1r
    y = np.sin(dlon) * np.cos(lat2r)
    x = np.cos(lat1r) * np.sin(lat2r) - np.sin(lat1r) * np.cos(lat2r) * np.cos(dlon)
    brng = np.rad2deg(np.arctan2(y, x))
    return float((brng + 360.0) % 360.0)                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def interpolate_route_heading(route_df, s_km, span_km: float = 1.0):  # [関数定義] interpolate_route_heading の処理実行ブロック
    if route_df is None or len(route_df) < 2:
        return 0.0                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    s0 = max(float(route_df['dist_km'].iloc[0]), float(s_km) - max(0.1, span_km))
    s1 = min(float(route_df['dist_km'].iloc[-1]), float(s_km) + max(0.1, span_km))
    if s1 <= s0:
        d = route_df['dist_km'].values
        i = int(np.clip(np.searchsorted(d, float(s_km)), 1, len(d) - 1))
        lat1 = float(route_df.iloc[i - 1]['lat'])
        lon1 = float(route_df.iloc[i - 1]['lon'])
        lat2 = float(route_df.iloc[i]['lat'])
        lon2 = float(route_df.iloc[i]['lon'])
        return bearing_deg(lat1, lon1, lat2, lon2)                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    lat1, lon1 = interpolate_route(route_df, s0)
    lat2, lon2 = interpolate_route(route_df, s1)
    return bearing_deg(lat1, lon1, lat2, lon2)                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
