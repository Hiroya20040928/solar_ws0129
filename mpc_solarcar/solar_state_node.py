import time

import rclpy                                                       # [ROS 2] ROS 2 Python クライアントライブラリ (rclpy) のインポート
from rclpy.node import Node                                        # [ROS 2] ノード基底クラス Node のインポート

from std_msgs.msg import Float32, Float32MultiArray, String


class SolarStateNode(Node):                                        # [状態推定ノード] バッテリーSoC・電圧・過渡分極(V1)の状態推定ノード
    """Mirror planner outputs into vehicle/system topics for solar-only simulation."""

    def __init__(self):                                            # [関数定義] __init__ の処理実行ブロック
        super().__init__('solar_state_node')
        self.declare_parameter('publish_rate_hz', 5.0)
        self.declare_parameter('stale_timeout_sec', 5.0)

        self.speed_cmd_kmh = 0.0
        self.speed_meas_kmh = 0.0
        self.throttle_pct = 0.0
        self.drive_mode = 'auto'
        self.soc = 0.80
        self.tb_c = 25.0
        self.s_km = 0.0
        self.status_s_km = 0.0
        self.batt_current_a = 0.0
        self.batt_voltage_v = 0.0
        self.forecast_k = 0.0
        self.sec_to_next = 0.0
        self.has_status = False
        self.has_metrics = False
        self.last_status_time = 0.0
        self.last_metrics_time = 0.0
        self.last_lower_plan_time = 0.0
        self.last_publish_time = time.monotonic()

        self.pub_speed = self.create_publisher(Float32, '/vehicle/speed_kmh', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_s_km = self.create_publisher(Float32, '/vehicle/s_km', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_soc = self.create_publisher(Float32, '/vehicle/batt_soc', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_tb = self.create_publisher(Float32, '/vehicle/batt_temp_c', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_ibatt = self.create_publisher(Float32, '/vehicle/batt_current_a', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_vbatt = self.create_publisher(Float32, '/vehicle/batt_voltage_v', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_throttle = self.create_publisher(Float32, '/vehicle/throttle_pct', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_state = self.create_publisher(String, '/system/state', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_diag = self.create_publisher(String, '/system/diag', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_mpc_state = self.create_publisher(String, '/system/mpc_state', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定
        self.pub_health = self.create_publisher(Float32, '/system/health', 10)  # [ROS 2 送信] 制御・指令トピックのパブリッシュ設定

        self.create_subscription(Float32, '/planner/speed_cmd', self._on_speed_cmd, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32, '/planner/throttle_cmd_pct', self._on_throttle, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(String, '/planner/drive_mode', self._on_drive_mode, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/status', self._on_status, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/metrics', self._on_metrics, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定
        self.create_subscription(Float32MultiArray, '/planner/lower_plan', self._on_lower_plan, 10)  # [ROS 2 受信] センサ・状態トピックの受信用コールバック設定

        period = 1.0 / max(0.5, float(self.get_parameter('publish_rate_hz').value))
        self.timer = self.create_timer(period, self._publish)
        self.get_logger().info('SolarStateNode started.')

    def _on_speed_cmd(self, msg: Float32):                         # [関数定義] _on_speed_cmd の処理実行ブロック
        self.speed_cmd_kmh = float(msg.data)
        self.speed_meas_kmh = float(msg.data)

    def _on_throttle(self, msg: Float32):                          # [関数定義] _on_throttle の処理実行ブロック
        self.throttle_pct = float(msg.data)

    def _on_drive_mode(self, msg: String):                         # [関数定義] _on_drive_mode の処理実行ブロック
        self.drive_mode = str(msg.data)

    def _on_status(self, msg: Float32MultiArray):                  # [関数定義] _on_status の処理実行ブロック
        data = list(msg.data)
        if len(data) < 5:
            return
        self.soc = float(data[0])
        self.tb_c = float(data[1])
        self.status_s_km = float(data[2])
        if not self.has_status:
            self.s_km = float(data[2])
        self.forecast_k = float(data[3])
        self.sec_to_next = float(data[4])
        self.has_status = True
        self.last_status_time = time.monotonic()

    def _on_metrics(self, msg: Float32MultiArray):                 # [関数定義] _on_metrics の処理実行ブロック
        data = list(msg.data)
        if len(data) < 7:
            return
        self.batt_voltage_v = float(data[0])
        self.batt_current_a = float(data[1])
        self.soc = float(data[2])
        self.speed_cmd_kmh = float(data[6])
        self.speed_meas_kmh = float(data[6])
        self.has_metrics = True
        self.last_metrics_time = time.monotonic()

    def _on_lower_plan(self, msg: Float32MultiArray):              # [関数定義] _on_lower_plan の処理実行ブロック
        if len(msg.data) > 1:
            self.last_lower_plan_time = time.monotonic()

    def _publish(self):                                            # [関数定義] _publish の処理実行ブロック
        now = time.monotonic()
        dt = max(0.0, now - self.last_publish_time)
        self.last_publish_time = now
        stale_timeout = max(1.0, float(self.get_parameter('stale_timeout_sec').value))
        status_age = now - self.last_status_time if self.has_status else float('inf')
        metrics_age = now - self.last_metrics_time if self.has_metrics else float('inf')
        healthy = status_age <= stale_timeout and metrics_age <= stale_timeout

        self.s_km = max(self.s_km, self.status_s_km)
        self.s_km += float(self.speed_meas_kmh) * (dt / 3600.0)

        self.pub_speed.publish(Float32(data=float(self.speed_meas_kmh)))
        self.pub_s_km.publish(Float32(data=float(self.s_km)))
        self.pub_soc.publish(Float32(data=float(self.soc)))
        self.pub_tb.publish(Float32(data=float(self.tb_c)))
        self.pub_ibatt.publish(Float32(data=float(self.batt_current_a)))
        self.pub_vbatt.publish(Float32(data=float(self.batt_voltage_v)))
        self.pub_throttle.publish(Float32(data=float(self.throttle_pct)))

        if not self.has_status:
            state = 'STARTING'
        elif healthy:
            state = 'RUNNING'
        else:
            state = 'STALE'

        if healthy:
            diag = f'forecast_k={self.forecast_k:.0f}, next={self.sec_to_next:.0f}s'
        elif self.has_status or self.has_metrics:
            diag = 'planner topics became stale'
        else:
            diag = 'waiting for planner topics'

        if self.last_lower_plan_time > 0.0 and (now - self.last_lower_plan_time) <= stale_timeout:
            mpc_state = 'HIERARCHICAL'
        else:
            mpc_state = 'UPPER_ONLY'

        health = 1.0 if healthy else (0.5 if self.has_status or self.has_metrics else 0.0)
        self.pub_state.publish(String(data=state))
        self.pub_diag.publish(String(data=diag))
        self.pub_mpc_state.publish(String(data=mpc_state))
        self.pub_health.publish(Float32(data=float(health)))


def main():                                                        # [メイン関数] エントリーポイント関数
    rclpy.init()
    node = SolarStateNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':                                         # [直接実行スクリプト] スクリプト直接起動時のメイン実行ブロック
    main()

# =============================================================================
# 【統合ロジック】移動ホライズン状態推定器 (MHE / EKF)
# =============================================================================
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
from collections import deque
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
from scipy.optimize import minimize


@dataclass
class MheInput:                                                    # [クラス定義] MheInput オブジェクトの設計
    v_ms: float
    slope_pct: float
    G_poa: float
    Tcell_C: float
    Tamb_C: float
    headwind_ms: float
    dt: float


@dataclass
class MheMeas:                                                     # [クラス定義] MheMeas オブジェクトの設計
    soc: Optional[float] = None
    Tb: Optional[float] = None
    I: Optional[float] = None
    V: Optional[float] = None


class BatteryMHE:                                                  # [クラス定義] BatteryMHE オブジェクトの設計
    def __init__(                                                  # [関数定義] __init__ の処理実行ブロック
        self,
        model,
        horizon_steps: int = 12,
        w_soc: float = 50.0,
        w_tb: float = 5.0,
        w_i: float = 1.0,
        w_v: float = 1.0,
        w_prior: float = 5.0,
        soc_bounds: Tuple[float, float] = (0.05, 0.98),
        tb_bounds: Tuple[float, float] = (-10.0, 65.0),
    ):
        self.model = model
        self.samples = deque(maxlen=max(2, int(horizon_steps)))
        self.w_soc = float(w_soc)
        self.w_tb = float(w_tb)
        self.w_i = float(w_i)
        self.w_v = float(w_v)
        self.w_prior = float(w_prior)
        self.soc_bounds = soc_bounds
        self.tb_bounds = tb_bounds

    def push(self, u: MheInput, y: MheMeas):                       # [関数定義] push の処理実行ブロック
        self.samples.append((u, y))

    def _simulate(self, z0: float, Tb0: float):                    # [関数定義] _simulate の処理実行ブロック
        z = float(z0)
        Tb = float(Tb0)
        outputs = []
        for (u, _) in self.samples:
            out = self.model.electrical_balance(
                u.v_ms,
                u.slope_pct,
                z,
                Tb,
                u.G_poa,
                u.Tcell_C,
                headwind_ms=u.headwind_ms,
            )
            I = float(out['I'])
            V = float(out['V'])
            P_pack = float(out['P_pack'])
            loss_int = float(out['losses_int'])
            dt = float(u.dt)
            z_next = self.model.soc_step(z, P_pack, dt)
            Tb_next = Tb + (dt / 1800.0) * (u.Tamb_C - Tb) + (loss_int * dt) / 50000.0
            outputs.append((z_next, Tb_next, I, V))
            z, Tb = z_next, Tb_next
        return outputs, z, Tb                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def estimate(self, z_init: float, Tb_init: float) -> Tuple[float, float]:  # [関数定義] estimate の処理実行ブロック
        if len(self.samples) < 2:
            return z_init, Tb_init                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

        def cost(x):                                               # [関数定義] cost の処理実行ブロック
            z0, Tb0 = float(x[0]), float(x[1])
            J = self.w_prior * ((z0 - z_init) ** 2 + (Tb0 - Tb_init) ** 2)
            outputs, _, _ = self._simulate(z0, Tb0)
            for (_, meas), (z_pred, Tb_pred, I_pred, V_pred) in zip(self.samples, outputs):
                if meas.soc is not None and math.isfinite(meas.soc):
                    J += self.w_soc * (z_pred - meas.soc) ** 2
                if meas.Tb is not None and math.isfinite(meas.Tb):
                    J += self.w_tb * (Tb_pred - meas.Tb) ** 2
                if meas.I is not None and math.isfinite(meas.I):
                    J += self.w_i * (I_pred - meas.I) ** 2
                if meas.V is not None and math.isfinite(meas.V):
                    J += self.w_v * (V_pred - meas.V) ** 2
            return J                                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

        x0 = np.array([float(z_init), float(Tb_init)], dtype=float)
        bounds = [self.soc_bounds, self.tb_bounds]
        res = minimize(cost, x0, method='L-BFGS-B', bounds=bounds, options=dict(maxiter=80))
        if not res.success:
            return z_init, Tb_init                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
        z0, Tb0 = float(res.x[0]), float(res.x[1])
        _, zN, TbN = self._simulate(z0, Tb0)
        return float(zN), float(TbN)                               # [戻り値] 計算結果・計算状態の呼び出し元への返却

# =============================================================================
# 【統合物理モデル】車両・電池物理パラメータ定義
# =============================================================================
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
from dataclasses import dataclass

try:
    import casadi as ca                                            # [最適化エンジン] 数値最適化・自動微分ライブラリ CasADi のインポート
except ImportError:
    class _CasadiCompat:                                           # [クラス定義] _CasadiCompat オブジェクトの設計
        class SX:                                                  # [クラス定義] SX オブジェクトの設計
            pass

        class MX:                                                  # [クラス定義] MX オブジェクトの設計
            pass

        @staticmethod
        def fmax(a, b):                                            # [関数定義] fmax の処理実行ブロック
            return max(a, b)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def fmin(a, b):                                            # [関数定義] fmin の処理実行ブロック
            return min(a, b)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def atan(x):                                               # [関数定義] atan の処理実行ブロック
            return math.atan(x)                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def cos(x):                                                # [関数定義] cos の処理実行ブロック
            return math.cos(x)                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def sin(x):                                                # [関数定義] sin の処理実行ブロック
            return math.sin(x)                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def sqrt(x):                                               # [関数定義] sqrt の処理実行ブロック
            return math.sqrt(x)                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却

        @staticmethod
        def fabs(x):                                               # [関数定義] fabs の処理実行ブロック
            return abs(x)                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却

    ca = _CasadiCompat()

def _is_symbolic(x):                                               # [関数定義] _is_symbolic の処理実行ブロック
    return isinstance(x, (ca.SX, ca.MX)) or (hasattr(x, 'is_symbolic') and x.is_symbolic())  # [戻り値] 計算結果・計算状態の呼び出し元への返却

@dataclass
class Params:                                                      # [クラス定義] Params オブジェクトの設計
    dt: float=600.0
    rho: float=1.18
    CdA: float=0.13
    Crr: float=0.002
    Crr_per_wheel: float=0.0
    m: float=250.0
    g: float=9.80665
    P_aux: float=60.0
    gear_eta: float=0.98
    gear_ratio: float=6.0
    wheel_radius: float=0.28
    wheel_count: int=4
    driven_wheel_count: int=2
    motor_count: int=1
    motor_type: str='generic'
    inverter_eta: float=1.0
    pv_area: float=6.0
    pv_eta_ref: float=0.23
    pv_mu_p: float=-0.0045
    mppt_eta: float=0.95
    panel_gain: float=1.0
    E_nom_Wh: float=3055.0
    V_min: float=260.0
    V_max: float=400.0
    I_max: float=120.0
    I_chg_min: float=-90.0
    T_max: float=55.0
    T_min: float=-5.0
    soc_min: float=0.05
    soc_max: float=0.98
    grade_scale: float=1.0
    drive_eff_scale: float=1.0
    regen_eff_scale: float=1.0
    rint_scale: float=1.0
    r_line_ohm: float=0.01
    eta_charge: float=1.0

class SolarCarModel:                                               # [車両モデルクラス] ソーラーカーの空力・転がり・発電・電池の統合物理モデル
    def __init__(self, drive_map_path, regen_map_path, Rint_map_path,  # [関数定義] __init__ の処理実行ブロック
                 params=None, panel_eff_map_path=None, mppt_eff_map_path=None,
                 drive_map_eco_path=None, drive_map_power_path=None,
                 regen_map_eco_path=None, regen_map_power_path=None,
                 ocv_soc_map_path=None):
        self.p = params or Params()
        self.drive_power_gain = 1.0
        self.aux_power_override_w = None
        self.v_grid, self.tau_grid, self.Z_drv = read_eff_map(drive_map_path)
        self.v_gridR, self.tau_gridR, self.Z_reg = read_eff_map(regen_map_path)
        self.drive_mode = 'auto'
        self.drive_mode_default = 'eco'
        self.drive_mode_tau_margin = 0.0
        self.maps_drive = {
            'default': (self.v_grid, self.tau_grid, self.Z_drv),
        }
        self.maps_regen = {
            'default': (self.v_gridR, self.tau_gridR, self.Z_reg),
        }
        if drive_map_eco_path:
            self.maps_drive['eco'] = read_eff_map(drive_map_eco_path)
        if drive_map_power_path:
            self.maps_drive['power'] = read_eff_map(drive_map_power_path)
        if regen_map_eco_path:
            self.maps_regen['eco'] = read_eff_map(regen_map_eco_path)
        if regen_map_power_path:
            self.maps_regen['power'] = read_eff_map(regen_map_power_path)
        self._update_mode_limits()
        self.Tg, self.zg, self.Rmap = read_Rint_map(Rint_map_path)
        self.panel_eff_map = None
        self.mppt_eff_map = None
        if panel_eff_map_path:
            try:
                self.Gg, self.Tcg, self.Z_panel = read_map(panel_eff_map_path)
                self.panel_eff_map = True
            except Exception:
                self.panel_eff_map = None
        if mppt_eff_map_path:
            try:
                self.Gm, self.Tm, self.Z_mppt = read_map(mppt_eff_map_path)
                self.mppt_eff_map = True
            except Exception:
                self.mppt_eff_map = None
        self.ocv_soc_map = None
        if ocv_soc_map_path:
            try:
                self.soc_grid, self.ocv_grid = read_1d_map(ocv_soc_map_path)
                self.ocv_soc_map = True
            except Exception:
                self.ocv_soc_map = None

    def eff_drive(self, v_ms, tau_nm):                             # [関数定義] eff_drive の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(tau_nm):
            v = ca.fabs(v_ms); t = ca.fabs(tau_nm)
            vN = v/35.0; tN = t/60.0
            eff = 0.92 - 0.08*vN*vN - 0.06*ca.sqrt(tN+1e-9)
            eff = eff * float(self.p.drive_eff_scale)
            return ca.fmin(0.99, ca.fmax(0.55, eff))               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        mode = self._select_mode(float(v_ms), float(abs(tau_nm)))
        v_grid, t_grid, Z = self.maps_drive.get(mode, self.maps_drive['default'])
        eff = float(bilinear_interp(v_grid, t_grid, Z, float(v_ms), float(abs(tau_nm))))
        eff *= float(self.p.drive_eff_scale)
        return float(np.clip(eff, 0.55, 0.99))                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def eff_regen(self, v_ms, tau_nm):                             # [関数定義] eff_regen の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(tau_nm):
            v = ca.fabs(v_ms); t = ca.fabs(tau_nm)
            vN = v/35.0; tN = t/60.0
            eff = 0.70 + 0.12*vN - 0.05*(tN-0.3)*(tN-0.3)
            eff = eff * float(self.p.regen_eff_scale or self.p.drive_eff_scale)
            return ca.fmin(0.95, ca.fmax(0.40, eff))               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        mode = self._select_mode(float(v_ms), float(abs(tau_nm)))
        v_grid, t_grid, Z = self.maps_regen.get(mode, self.maps_regen['default'])
        eff = float(bilinear_interp(v_grid, t_grid, Z, float(v_ms), float(abs(tau_nm))))
        eff *= float(self.p.regen_eff_scale or self.p.drive_eff_scale)
        return float(np.clip(eff, 0.40, 0.95))                     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _update_mode_limits(self):                                 # [関数定義] _update_mode_limits の処理実行ブロック
        self.tau_max = {}
        for k, (_, t_grid, _) in self.maps_drive.items():
            try:
                self.tau_max[k] = float(max(t_grid))
            except Exception:
                self.tau_max[k] = 0.0

    def _select_mode(self, v_ms: float, tau_nm: float) -> str:     # [関数定義] _select_mode の処理実行ブロック
        mode = str(self.drive_mode or 'default').lower()
        if mode in ('eco', 'power'):
            return mode                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        # auto
        eco_max = self.tau_max.get('eco', self.tau_max.get('default', 0.0))
        margin = float(self.drive_mode_tau_margin or 0.0)
        if tau_nm > (eco_max + margin):
            return 'power' if 'power' in self.maps_drive else 'default'  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return 'eco' if 'eco' in self.maps_drive else 'default'    # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def select_drive_mode(self, v_ms: float, tau_nm: float) -> str:  # [関数定義] select_drive_mode の処理実行ブロック
        return self._select_mode(v_ms, abs(tau_nm))                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def R_int(self, T_C, z):                                       # [関数定義] R_int の処理実行ブロック
        if _is_symbolic(T_C) or _is_symbolic(z):
            R0=0.015; R_T=0.0002*(25.0-T_C); R_z=0.01*(1.0-z)
            return (R0+R_T+R_z) * float(self.p.rint_scale)         # [戻り値] 計算結果・計算状態の呼び出し元への返却
        else:
            return float(self.p.rint_scale) * float(bilinear_interp(self.Tg, self.zg, self.Rmap, T_C, z))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def pv_power_mppt(self, G_poa, T_cell_C):                      # [関数定義] pv_power_mppt の処理実行ブロック
        if self.panel_eff_map:
            eta_panel = bilinear_interp(self.Gg, self.Tcg, self.Z_panel, float(G_poa), float(T_cell_C))
            eta_panel = max(0.0, float(eta_panel))
        else:
            eta_panel = self.p.pv_eta_ref*(1.0+self.p.pv_mu_p*(T_cell_C-25.0))
            eta_panel = ca.fmax(0.0, eta_panel)
        eta_panel *= float(self.p.panel_gain)
        P_pv = eta_panel*self.p.pv_area*G_poa
        if self.mppt_eff_map:
            eta_mppt = bilinear_interp(self.Gm, self.Tm, self.Z_mppt, float(G_poa), float(T_cell_C))
            eta_mppt = max(0.0, float(eta_mppt))
            return eta_mppt*P_pv                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return self.p.mppt_eta*P_pv                                # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def _scaled_slope_pct(self, slope_pct):                        # [関数定義] _scaled_slope_pct の処理実行ブロック
        return slope_pct * float(self.p.grade_scale)               # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def charge_efficiency(self, P_pack) -> float:                  # [関数定義] charge_efficiency の処理実行ブロック
        try:
            p_pack = float(P_pack)
        except Exception:
            return 1.0                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return float(self.p.eta_charge) if p_pack < 0.0 else 1.0   # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def soc_step(self, z: float, P_pack: float, dt_sec: float) -> float:  # [関数定義] soc_step の処理実行ブロック
        eta = self.charge_efficiency(P_pack)
        return float(z) - eta * (float(P_pack) * float(dt_sec) / 3600.0) / max(float(self.p.E_nom_Wh), 1.0e-6)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def ocv_from_soc(self, z):                                     # [関数定義] ocv_from_soc の処理実行ブロック
        if _is_symbolic(z) or not self.ocv_soc_map:
            z_clamped = ca.fmin(self.p.soc_max, ca.fmax(self.p.soc_min, z))
            return self.p.V_min + (self.p.V_max - self.p.V_min) * z_clamped  # [戻り値] 計算結果・計算状態の呼び出し元への返却
        zc = float(np.clip(z, self.p.soc_min, self.p.soc_max))
        return float(np.interp(zc, self.soc_grid, self.ocv_grid))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def load_ocv_map(self, path: str) -> bool:                     # [関数定義] load_ocv_map の処理実行ブロック
        try:
            self.soc_grid, self.ocv_grid = read_1d_map(path)
            self.ocv_soc_map = True
            return True                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        except Exception:
            self.ocv_soc_map = None
            return False                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def resistive_forces(self, v_ms, slope_pct, headwind_ms=0.0):  # [関数定義] resistive_forces の処理実行ブロック
        if _is_symbolic(v_ms) or _is_symbolic(slope_pct) or _is_symbolic(headwind_ms):
            v_rel = ca.fmax(0.0, v_ms + headwind_ms)
            theta = ca.atan(self._scaled_slope_pct(slope_pct) / 100.0)
            F_aero = 0.5 * self.p.rho * self.p.CdA * v_rel ** 2
            N = self.p.m * self.p.g * ca.cos(theta)
            Crr_eff = self.p.Crr
            if self.p.Crr_per_wheel and self.p.wheel_count:
                Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
            F_roll = Crr_eff * N
            F_grade = self.p.m * self.p.g * ca.sin(theta)
            F_total = F_aero + F_roll + F_grade
            return dict(F_aero=F_aero, F_roll=F_roll, F_grade=F_grade,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                        F_total=F_total, theta=theta)
        v_rel = max(0.0, float(v_ms) + float(headwind_ms))
        theta = math.atan(float(self._scaled_slope_pct(slope_pct)) / 100.0)
        F_aero = 0.5 * self.p.rho * self.p.CdA * v_rel ** 2
        N = self.p.m * self.p.g * math.cos(theta)
        Crr_eff = self.p.Crr
        if self.p.Crr_per_wheel and self.p.wheel_count:
            Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
        F_roll = Crr_eff * N
        F_grade = self.p.m * self.p.g * math.sin(theta)
        F_total = F_aero + F_roll + F_grade
        return dict(F_aero=F_aero, F_roll=F_roll, F_grade=F_grade,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                    F_total=F_total, theta=theta)

    def battery_iv(self, P_pack, z, Tbat_C):                       # [関数定義] battery_iv の処理実行ブロック
        OCV = self.ocv_from_soc(z)
        Rint = self.R_int(Tbat_C, ca.fmin(0.95, ca.fmax(0.1, z)))
        Rline = float(self.p.r_line_ohm)
        Rtot = Rint + Rline
        a = Rtot
        b = -OCV
        c = P_pack
        disc = ca.fmax(b * b - 4 * a * c, 0.0)
        I = (OCV - ca.sqrt(disc)) / (2 * Rtot)
        V = OCV - I * Rtot
        return dict(I=I, V=V, OCV=OCV, Rint=Rint, Rline=Rline)     # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def mech_power(self, v_ms, slope_pct, headwind_ms=0.0):        # [関数定義] mech_power の処理実行ブロック
        v_rel = ca.fmax(0.0, v_ms + headwind_ms)
        P_aero = 0.5*self.p.rho*self.p.CdA*v_rel**3
        theta  = ca.atan(self._scaled_slope_pct(slope_pct)/100.0)
        N = self.p.m*self.p.g*ca.cos(theta)
        Crr_eff = self.p.Crr
        if self.p.Crr_per_wheel and self.p.wheel_count:
            Crr_eff = self.p.Crr_per_wheel * float(self.p.wheel_count)
        P_roll = Crr_eff*N*v_ms
        P_grade= self.p.m*self.p.g*ca.sin(theta)*v_ms
        drive_power = (P_aero + P_roll + P_grade) * float(self.drive_power_gain)
        aux_power = float(self.aux_power_override_w) if self.aux_power_override_w is not None else float(self.p.P_aux)
        return drive_power + aux_power                             # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def torque_from_mech(self, P_mech, v_ms, wheel_radius=None, ratio=None):  # [関数定義] torque_from_mech の処理実行ブロック
        if wheel_radius is None:
            wheel_radius = self.p.wheel_radius
        if ratio is None:
            ratio = self.p.gear_ratio
        eps=1e-3
        omega_w = v_ms/wheel_radius
        T_w = P_mech/(omega_w+eps)
        T_m = T_w/ratio
        return T_m, omega_w*ratio                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    def electrical_balance(self, v_ms, slope_pct, z, Tbat_C, G_poa, Tcell_C, headwind_ms=0.0):  # [関数定義] electrical_balance の処理実行ブロック
        P_pv = self.pv_power_mppt(G_poa, Tcell_C)
        P_mech = self.mech_power(v_ms, slope_pct, headwind_ms)
        P_mech_pos = ca.fmax(P_mech, 0.0)
        P_mech_neg = ca.fmax(-P_mech, 0.0)
        Tm_drv, _ = self.torque_from_mech(P_mech_pos, v_ms)
        eff_drv = self.eff_drive(v_ms, Tm_drv)
        P_dc_to_drv = P_mech_pos/(eff_drv*self.p.gear_eta*self.p.inverter_eta)
        Tm_reg, _ = self.torque_from_mech(P_mech_neg, v_ms)
        eff_reg = self.eff_regen(v_ms, Tm_reg)
        P_reg_to_dc = eff_reg*self.p.gear_eta*self.p.inverter_eta*P_mech_neg
        P_pack = P_dc_to_drv - P_reg_to_dc - P_pv
        OCV = self.ocv_from_soc(z)
        Rint = self.R_int(Tbat_C, ca.fmin(0.95, ca.fmax(0.1, z)))
        Rline = float(self.p.r_line_ohm); Rtot = Rint + Rline
        a = Rtot; b=-OCV; c=P_pack
        disc = ca.fmax(b*b-4*a*c, 0.0)
        I = (OCV - ca.sqrt(disc))/(2*Rtot)
        V = OCV - I*Rtot
        losses_line = I*I*Rline; losses_int = I*I*Rint
        aux_power = float(self.aux_power_override_w) if self.aux_power_override_w is not None else float(self.p.P_aux)
        P_mech_wheel = P_mech - aux_power
        return dict(P_pv=P_pv, P_mech=P_mech, P_mech_wheel=P_mech_wheel,  # [戻り値] 計算結果・計算状態の呼び出し元への返却
                    P_pack=P_pack, I=I, V=V,
                    losses_line=losses_line, losses_int=losses_int,
                    OCV=OCV, Rint=Rint, Rline=Rline,
                    P_dc_to_drv=P_dc_to_drv, P_reg_to_dc=P_reg_to_dc,
                    eff_drv=eff_drv, eff_reg=eff_reg)

# =============================================================================
# 【統合ユーティリティ】マップ読み込み・2D/1D線形補間関数群
# =============================================================================
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
def bilinear_interp(xg, yg, Z, x, y):                              # [関数定義] bilinear_interp の処理実行ブロック
    xg = np.asarray(xg); yg=np.asarray(yg); Z=np.asarray(Z)
    x = np.clip(x, xg[0], xg[-1]); y=np.clip(y, yg[0], yg[-1])
    i = np.searchsorted(xg, x)-1; i=np.clip(i,0,len(xg)-2)
    j = np.searchsorted(yg, y)-1; j=np.clip(j,0,len(yg)-2)
    x0,x1=xg[i],xg[i+1]; y0,y1=yg[j],yg[j+1]
    Z00=Z[i,j]; Z10=Z[i+1,j]; Z01=Z[i,j+1]; Z11=Z[i+1,j+1]
    wx=0 if x1==x0 else (x-x0)/(x1-x0)
    wy=0 if y1==y0 else (y-y0)/(y1-y0)
    return (1-wx)*(1-wy)*Z00 + wx*(1-wy)*Z10 + (1-wx)*wy*Z01 + wx*wy*Z11  # [戻り値] 計算結果・計算状態の呼び出し元への返却
def read_eff_map(path):                                            # [関数定義] read_eff_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
def read_Rint_map(path):                                           # [関数定義] read_Rint_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

def read_map(path):                                                # [関数定義] read_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

def read_1d_map(path):                                             # [関数定義] read_1d_map の処理実行ブロック
    df = pd.read_csv(path)
    if df.shape[1] >= 2:
        x = df.iloc[:, 0].values.astype(float)
        y = df.iloc[:, 1].values.astype(float)
        return x, y                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    df = pd.read_csv(path, index_col=0)
    x = df.index.values.astype(float)
    y = df.iloc[:, 0].values.astype(float)
    return x, y                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却