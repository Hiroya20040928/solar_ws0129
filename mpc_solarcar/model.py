import math
import numpy as np
from dataclasses import dataclass
from .utils_maps import read_eff_map, read_Rint_map, read_map, bilinear_interp, read_1d_map

try:
    import casadi as ca
except ImportError:
    class _CasadiCompat:
        class SX:
            pass

        class MX:
            pass

        @staticmethod
        def fmax(a, b):
            return max(a, b)

        @staticmethod
        def fmin(a, b):
            return min(a, b)

        @staticmethod
        def atan(x):
            return math.atan(x)

        @staticmethod
        def cos(x):
            return math.cos(x)

        @staticmethod
        def sin(x):
            return math.sin(x)

        @staticmethod
        def sqrt(x):
            return math.sqrt(x)

        @staticmethod
        def fabs(x):
            return abs(x)

    ca = _CasadiCompat()

def _is_symbolic(x):
    return isinstance(x, (ca.SX, ca.MX)) or (hasattr(x, 'is_symbolic') and x.is_symbolic())

@dataclass
class Params:
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

class SolarCarModel:
    def __init__(self, drive_map_path, regen_map_path, Rint_map_path,
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

    def eff_drive(self, v_ms, tau_nm):
        if _is_symbolic(v_ms) or _is_symbolic(tau_nm):
            v = ca.fabs(v_ms); t = ca.fabs(tau_nm)
            vN = v/35.0; tN = t/60.0
            eff = 0.92 - 0.08*vN*vN - 0.06*ca.sqrt(tN+1e-9)
            eff = eff * float(self.p.drive_eff_scale)
            return ca.fmin(0.99, ca.fmax(0.55, eff))
        mode = self._select_mode(float(v_ms), float(abs(tau_nm)))
        v_grid, t_grid, Z = self.maps_drive.get(mode, self.maps_drive['default'])
        eff = float(bilinear_interp(v_grid, t_grid, Z, float(v_ms), float(abs(tau_nm))))
        eff *= float(self.p.drive_eff_scale)
        return float(np.clip(eff, 0.55, 0.99))

    def eff_regen(self, v_ms, tau_nm):
        if _is_symbolic(v_ms) or _is_symbolic(tau_nm):
            v = ca.fabs(v_ms); t = ca.fabs(tau_nm)
            vN = v/35.0; tN = t/60.0
            eff = 0.70 + 0.12*vN - 0.05*(tN-0.3)*(tN-0.3)
            eff = eff * float(self.p.regen_eff_scale or self.p.drive_eff_scale)
            return ca.fmin(0.95, ca.fmax(0.40, eff))
        mode = self._select_mode(float(v_ms), float(abs(tau_nm)))
        v_grid, t_grid, Z = self.maps_regen.get(mode, self.maps_regen['default'])
        eff = float(bilinear_interp(v_grid, t_grid, Z, float(v_ms), float(abs(tau_nm))))
        eff *= float(self.p.regen_eff_scale or self.p.drive_eff_scale)
        return float(np.clip(eff, 0.40, 0.95))

    def _update_mode_limits(self):
        self.tau_max = {}
        for k, (_, t_grid, _) in self.maps_drive.items():
            try:
                self.tau_max[k] = float(max(t_grid))
            except Exception:
                self.tau_max[k] = 0.0

    def _select_mode(self, v_ms: float, tau_nm: float) -> str:
        mode = str(self.drive_mode or 'default').lower()
        if mode in ('eco', 'power'):
            return mode
        # auto
        eco_max = self.tau_max.get('eco', self.tau_max.get('default', 0.0))
        margin = float(self.drive_mode_tau_margin or 0.0)
        if tau_nm > (eco_max + margin):
            return 'power' if 'power' in self.maps_drive else 'default'
        return 'eco' if 'eco' in self.maps_drive else 'default'

    def select_drive_mode(self, v_ms: float, tau_nm: float) -> str:
        return self._select_mode(v_ms, abs(tau_nm))

    def R_int(self, T_C, z):
        if _is_symbolic(T_C) or _is_symbolic(z):
            R0=0.015; R_T=0.0002*(25.0-T_C); R_z=0.01*(1.0-z)
            return (R0+R_T+R_z) * float(self.p.rint_scale)
        else:
            return float(self.p.rint_scale) * float(bilinear_interp(self.Tg, self.zg, self.Rmap, T_C, z))

    def pv_power_mppt(self, G_poa, T_cell_C):
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
            return eta_mppt*P_pv
        return self.p.mppt_eta*P_pv

    def _scaled_slope_pct(self, slope_pct):
        return slope_pct * float(self.p.grade_scale)

    def charge_efficiency(self, P_pack) -> float:
        try:
            p_pack = float(P_pack)
        except Exception:
            return 1.0
        return float(self.p.eta_charge) if p_pack < 0.0 else 1.0

    def soc_step(self, z: float, P_pack: float, dt_sec: float) -> float:
        eta = self.charge_efficiency(P_pack)
        return float(z) - eta * (float(P_pack) * float(dt_sec) / 3600.0) / max(float(self.p.E_nom_Wh), 1.0e-6)

    def ocv_from_soc(self, z):
        if _is_symbolic(z) or not self.ocv_soc_map:
            z_clamped = ca.fmin(self.p.soc_max, ca.fmax(self.p.soc_min, z))
            return self.p.V_min + (self.p.V_max - self.p.V_min) * z_clamped
        zc = float(np.clip(z, self.p.soc_min, self.p.soc_max))
        return float(np.interp(zc, self.soc_grid, self.ocv_grid))

    def load_ocv_map(self, path: str) -> bool:
        try:
            self.soc_grid, self.ocv_grid = read_1d_map(path)
            self.ocv_soc_map = True
            return True
        except Exception:
            self.ocv_soc_map = None
            return False

    def resistive_forces(self, v_ms, slope_pct, headwind_ms=0.0):
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
            return dict(F_aero=F_aero, F_roll=F_roll, F_grade=F_grade,
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
        return dict(F_aero=F_aero, F_roll=F_roll, F_grade=F_grade,
                    F_total=F_total, theta=theta)

    def battery_iv(self, P_pack, z, Tbat_C):
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
        return dict(I=I, V=V, OCV=OCV, Rint=Rint, Rline=Rline)

    def mech_power(self, v_ms, slope_pct, headwind_ms=0.0):
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
        return drive_power + aux_power

    def torque_from_mech(self, P_mech, v_ms, wheel_radius=None, ratio=None):
        if wheel_radius is None:
            wheel_radius = self.p.wheel_radius
        if ratio is None:
            ratio = self.p.gear_ratio
        eps=1e-3
        omega_w = v_ms/wheel_radius
        T_w = P_mech/(omega_w+eps)
        T_m = T_w/ratio
        return T_m, omega_w*ratio

    def electrical_balance(self, v_ms, slope_pct, z, Tbat_C, G_poa, Tcell_C, headwind_ms=0.0):
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
        return dict(P_pv=P_pv, P_mech=P_mech, P_mech_wheel=P_mech_wheel,
                    P_pack=P_pack, I=I, V=V,
                    losses_line=losses_line, losses_int=losses_int,
                    OCV=OCV, Rint=Rint, Rline=Rline,
                    P_dc_to_drv=P_dc_to_drv, P_reg_to_dc=P_reg_to_dc,
                    eff_drv=eff_drv, eff_reg=eff_reg)
