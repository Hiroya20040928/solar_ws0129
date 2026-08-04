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
