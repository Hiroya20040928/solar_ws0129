import math
from dataclasses import dataclass
from functools import lru_cache
from time import perf_counter
import tkinter as tk
from tkinter import ttk

import matplotlib
import numpy as np

matplotlib.use("TkAgg")

from matplotlib import cm, colors
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from mpl_toolkits.mplot3d.art3d import Line3DCollection

try:
    from scipy.special import ellipk as scipy_ellipk
    from scipy.special import ellipe as scipy_ellipe
except Exception:
    scipy_ellipk = None
    scipy_ellipe = None


MU0 = 4.0e-7 * math.pi
AXIS_EPS = 1.0e-12
RF_ERRTOL = 3.0e-5
RD_ERRTOL = 2.0e-5


@dataclass(frozen=True)
class MagnetParams:
    radius_m: float
    thickness_m: float
    remanence_t: float
    span_m: float
    grid_n: int
    slice_n: int = 81
    integration_nodes: int = 24


@lru_cache(maxsize=16)
def gauss_legendre_rule(count: int):
    nodes, weights = np.polynomial.legendre.leggauss(count)
    return nodes.astype(float), weights.astype(float)


def carlson_rf_positive_real(x, y, z):
    x, y, z = np.broadcast_arrays(
        np.asarray(x, dtype=float),
        np.asarray(y, dtype=float),
        np.asarray(z, dtype=float),
    )

    a0 = (x + y + z) / 3.0
    am = a0.copy()
    xm = x.copy()
    ym = y.copy()
    zm = z.copy()
    q = np.power(3.0 * RF_ERRTOL, -1.0 / 6.0) * np.maximum.reduce(
        [np.abs(a0 - x), np.abs(a0 - y), np.abs(a0 - z)]
    )
    pow4 = np.ones_like(a0)

    while True:
        xs = np.sqrt(xm)
        ys = np.sqrt(ym)
        zs = np.sqrt(zm)
        lam = xs * ys + xs * zs + ys * zs
        am1 = 0.25 * (am + lam)
        xm = 0.25 * (xm + lam)
        ym = 0.25 * (ym + lam)
        zm = 0.25 * (zm + lam)
        if np.all(pow4 * q < np.abs(am)):
            break
        am = am1
        pow4 *= 0.25

    t = pow4 / am
    x_red = (a0 - x) * t
    y_red = (a0 - y) * t
    z_red = -x_red - y_red
    e2 = x_red * y_red - z_red * z_red
    e3 = x_red * y_red * z_red
    return np.power(am, -0.5) * (
        9240.0
        - 924.0 * e2
        + 385.0 * e2 * e2
        + 660.0 * e3
        - 630.0 * e2 * e3
    ) / 9240.0


def carlson_rd_positive_real(x, y, z):
    x, y, z = np.broadcast_arrays(
        np.asarray(x, dtype=float),
        np.asarray(y, dtype=float),
        np.asarray(z, dtype=float),
    )

    xm = x.copy()
    ym = y.copy()
    zm = z.copy()
    accum = np.zeros_like(xm)
    fac = np.ones_like(xm)

    while True:
        mu = (xm + ym + 3.0 * zm) / 5.0
        x_red = (mu - xm) / mu
        y_red = (mu - ym) / mu
        z_red = (mu - zm) / mu
        if np.all(np.maximum.reduce([np.abs(x_red), np.abs(y_red), np.abs(z_red)]) < RD_ERRTOL):
            break
        xs = np.sqrt(xm)
        ys = np.sqrt(ym)
        zs = np.sqrt(zm)
        lam = xs * (ys + zs) + ys * zs
        accum += fac / (zs * (zm + lam))
        fac *= 0.25
        xm = 0.25 * (xm + lam)
        ym = 0.25 * (ym + lam)
        zm = 0.25 * (zm + lam)

    ea = x_red * y_red
    eb = z_red * z_red
    ec = ea - eb
    ed = ea - 6.0 * eb
    ef = ed + 2.0 * ec
    series = (
        1.0
        + ed * (-3.0 / 14.0 + (9.0 / 88.0) * ed - (9.0 / 52.0) * z_red * ef)
        + z_red * (ef / 6.0 + z_red * (-9.0 * ec / 22.0 + z_red * (3.0 * ea / 26.0)))
    )
    return 3.0 * accum + fac * series / (mu * np.sqrt(mu))


def complete_elliptic_k_e(m):
    m = np.clip(np.asarray(m, dtype=float), 0.0, 1.0 - 1.0e-14)
    if scipy_ellipk is not None and scipy_ellipe is not None:
        return scipy_ellipk(m), scipy_ellipe(m)
    k_val = carlson_rf_positive_real(0.0, 1.0 - m, 1.0)
    e_val = k_val - (m / 3.0) * carlson_rd_positive_real(0.0, 1.0 - m, 1.0)
    return k_val, e_val


def loop_field_cylindrical(rho, z, radius_m, current_a):
    rho_arr, z_arr, current_arr = np.broadcast_arrays(
        np.asarray(rho, dtype=float),
        np.asarray(z, dtype=float),
        np.asarray(current_a, dtype=float),
    )
    b_rho = np.zeros_like(rho_arr)
    b_z = np.zeros_like(rho_arr)

    on_axis = rho_arr < AXIS_EPS
    if np.any(on_axis):
        z_axis = z_arr[on_axis]
        i_axis = current_arr[on_axis]
        b_z[on_axis] = (
            MU0 * i_axis * radius_m * radius_m
            / (2.0 * np.power(radius_m * radius_m + z_axis * z_axis, 1.5))
        )

    off_axis = ~on_axis
    if np.any(off_axis):
        rho_off = rho_arr[off_axis]
        z_off = z_arr[off_axis]
        i_off = current_arr[off_axis]
        beta2 = (radius_m + rho_off) ** 2 + z_off * z_off
        beta = np.sqrt(beta2)
        alpha2 = (radius_m - rho_off) ** 2 + z_off * z_off
        m = np.clip(4.0 * radius_m * rho_off / beta2, 0.0, 1.0 - 1.0e-14)
        k_val, e_val = complete_elliptic_k_e(m)
        common = MU0 * i_off / (2.0 * math.pi * beta)
        b_rho[off_axis] = common * (z_off / rho_off) * (
            -k_val + e_val * (radius_m * radius_m + rho_off * rho_off + z_off * z_off) / alpha2
        )
        b_z[off_axis] = common * (
            k_val + e_val * (radius_m * radius_m - rho_off * rho_off - z_off * z_off) / alpha2
        )

    return b_rho, b_z


def cylinder_field_cylindrical(rho, z, params: MagnetParams):
    rho_arr = np.asarray(rho, dtype=float)
    z_arr = np.asarray(z, dtype=float)
    nodes, weights = gauss_legendre_rule(params.integration_nodes)
    half_thickness = 0.5 * params.thickness_m
    z_nodes = half_thickness * nodes
    d_currents = (params.remanence_t / MU0) * half_thickness * weights

    rho_eval = np.broadcast_to(rho_arr[..., None], rho_arr.shape + (params.integration_nodes,))
    z_eval = z_arr[..., None] - z_nodes
    current_eval = d_currents
    b_rho_nodes, b_z_nodes = loop_field_cylindrical(rho_eval, z_eval, params.radius_m, current_eval)
    return np.sum(b_rho_nodes, axis=-1), np.sum(b_z_nodes, axis=-1)


def cylinder_field_cartesian(points, params: MagnetParams):
    points = np.asarray(points, dtype=float)
    rho = np.hypot(points[:, 0], points[:, 1])
    cylindrical_points = np.column_stack((np.round(rho, 15), np.round(points[:, 2], 15)))
    unique_pairs, inverse = np.unique(cylindrical_points, axis=0, return_inverse=True)
    b_rho_unique, b_z_unique = cylinder_field_cylindrical(unique_pairs[:, 0], unique_pairs[:, 1], params)
    b_rho = b_rho_unique[inverse]
    b_z = b_z_unique[inverse]
    cos_phi = np.divide(points[:, 0], rho, out=np.zeros_like(rho), where=rho > AXIS_EPS)
    sin_phi = np.divide(points[:, 1], rho, out=np.zeros_like(rho), where=rho > AXIS_EPS)
    b_x = b_rho * cos_phi
    b_y = b_rho * sin_phi
    return np.column_stack((b_x, b_y, b_z))


def observation_grid(params: MagnetParams):
    axis = np.linspace(-params.span_m, params.span_m, params.grid_n)
    x, y, z = np.meshgrid(axis, axis, axis, indexing="ij")
    points = np.column_stack((x.ravel(), y.ravel(), z.ravel()))
    radial = np.hypot(points[:, 0], points[:, 1])
    inside = (radial <= params.radius_m) & (np.abs(points[:, 2]) <= 0.5 * params.thickness_m)
    return axis, points, inside


def slice_grid(params: MagnetParams):
    x_axis = np.linspace(-params.span_m, params.span_m, params.slice_n)
    z_axis = np.linspace(-params.span_m, params.span_m, params.slice_n)
    x, z = np.meshgrid(x_axis, z_axis, indexing="xy")
    points = np.column_stack((x.ravel(), np.zeros(x.size), z.ravel()))
    inside = (np.abs(points[:, 0]) <= params.radius_m) & (np.abs(points[:, 2]) <= 0.5 * params.thickness_m)
    return x_axis, z_axis, points, inside


def axis_field_closed_form(z, params: MagnetParams):
    z = np.asarray(z, dtype=float)
    zp = z + 0.5 * params.thickness_m
    zm = z - 0.5 * params.thickness_m
    return 0.5 * params.remanence_t * (
        zp / np.sqrt(params.radius_m * params.radius_m + zp * zp)
        - zm / np.sqrt(params.radius_m * params.radius_m + zm * zm)
    )


def estimate_axis_error(params: MagnetParams):
    z_probe = np.linspace(-params.span_m, params.span_m, 17)
    _, b_z = cylinder_field_cylindrical(np.zeros_like(z_probe), z_probe, params)
    exact = axis_field_closed_form(z_probe, params)
    abs_error = float(np.max(np.abs(b_z - exact)))
    denom = max(float(np.max(np.abs(exact))), 1.0e-12)
    return abs_error / denom, abs_error


@lru_cache(maxsize=12)
def sample_field_distribution(params: MagnetParams):
    axis, points_3d, inside_3d = observation_grid(params)
    field_3d = cylinder_field_cartesian(points_3d, params)
    field_3d[inside_3d] = np.nan

    x_axis, z_axis, points_slice, inside_slice = slice_grid(params)
    field_slice = cylinder_field_cartesian(points_slice, params)
    field_slice[inside_slice] = np.nan

    axis_rel_error, axis_abs_error = estimate_axis_error(params)
    return {
        "axis": axis,
        "points_3d": points_3d,
        "field_3d": field_3d,
        "x_axis": x_axis,
        "z_axis": z_axis,
        "field_slice": field_slice.reshape(len(z_axis), len(x_axis), 3),
        "axis_rel_error": axis_rel_error,
        "axis_abs_error": axis_abs_error,
    }


class MagnetFieldViewer(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Disk Magnet Field Viewer")
        self.geometry("1450x860")
        self.minsize(1180, 760)

        self.radius_mm = tk.DoubleVar(value=20.0)
        self.thickness_mm = tk.DoubleVar(value=8.0)
        self.remanence_t = tk.DoubleVar(value=1.2)
        self.span_mm = tk.DoubleVar(value=60.0)
        self.grid_n = tk.IntVar(value=9)
        self.status_var = tk.StringVar(
            value="High-accuracy solver: elliptic integrals + Gauss-Legendre integration."
        )

        self.cbar3d = None
        self.cbar2d = None
        self.default_elev = 25.0
        self.default_azim = -60.0

        self._build_layout()
        self.recompute()

    def _build_layout(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        controls = ttk.Frame(self, padding=14)
        controls.grid(row=0, column=0, sticky="nsw")

        plots = ttk.Frame(self, padding=(0, 12, 12, 12))
        plots.grid(row=0, column=1, sticky="nsew")
        plots.columnconfigure(0, weight=1)
        plots.columnconfigure(1, weight=1)
        plots.rowconfigure(0, weight=1)

        plot3d_frame = ttk.Frame(plots)
        plot3d_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        plot3d_frame.columnconfigure(0, weight=1)
        plot3d_frame.rowconfigure(0, weight=1)

        plot2d_frame = ttk.Frame(plots)
        plot2d_frame.grid(row=0, column=1, sticky="nsew")
        plot2d_frame.columnconfigure(0, weight=1)
        plot2d_frame.rowconfigure(0, weight=1)

        ttk.Label(controls, text="Disk magnet field", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 10)
        )
        ttk.Label(
            controls,
            text=(
                "Model: uniformly magnetized cylinder via equivalent surface current.\n"
                "3D view is mouse-rotatable. Internal solver stays high-accuracy\n"
                "while the displayed arrows are thinned to keep the GUI responsive."
            ),
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, 12))

        fields = [
            ("Radius [mm]", self.radius_mm),
            ("Thickness [mm]", self.thickness_mm),
            ("Remanence Br [T]", self.remanence_t),
            ("View span [mm]", self.span_mm),
            ("3D grid points", self.grid_n),
        ]

        for row_index, (label_text, variable) in enumerate(fields, start=2):
            ttk.Label(controls, text=label_text).grid(row=row_index, column=0, sticky="w")
            entry = ttk.Entry(controls, textvariable=variable, width=14)
            entry.grid(row=row_index, column=0, sticky="w", pady=(2, 10), padx=(160, 0))
            entry.bind("<Return>", lambda _event: self.recompute())

        button_row = ttk.Frame(controls)
        button_row.grid(row=7, column=0, sticky="w", pady=(10, 16))
        ttk.Button(button_row, text="Recompute", command=self.recompute).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(button_row, text="Reset view", command=self.reset_view).grid(row=0, column=1)

        ttk.Separator(controls, orient="horizontal").grid(row=8, column=0, sticky="ew", pady=10)
        ttk.Label(controls, textvariable=self.status_var, wraplength=310, justify="left").grid(
            row=9, column=0, sticky="w"
        )

        self.figure3d = Figure(figsize=(6.2, 6.8), dpi=100)
        self.figure3d.subplots_adjust(left=0.03, right=0.92, bottom=0.05, top=0.95)
        self.ax3d = self.figure3d.add_subplot(111, projection="3d")

        self.figure2d = Figure(figsize=(5.7, 6.8), dpi=100)
        self.figure2d.subplots_adjust(left=0.11, right=0.88, bottom=0.09, top=0.95)
        self.ax2d = self.figure2d.add_subplot(111)

        self.canvas3d = FigureCanvasTkAgg(self.figure3d, master=plot3d_frame)
        self.canvas3d.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        self.canvas2d = FigureCanvasTkAgg(self.figure2d, master=plot2d_frame)
        self.canvas2d.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        self.toolbar3d = NavigationToolbar2Tk(self.canvas3d, plot3d_frame, pack_toolbar=False)
        self.toolbar3d.update()
        self.toolbar3d.grid(row=1, column=0, sticky="ew")

    def current_params(self):
        grid_n = int(self.grid_n.get())
        grid_n = max(5, min(grid_n, 13))
        if grid_n % 2 == 0:
            grid_n += 1

        radius_m = max(float(self.radius_mm.get()), 1.0) * 1.0e-3
        thickness_m = max(float(self.thickness_mm.get()), 1.0) * 1.0e-3
        span_m = max(float(self.span_mm.get()), 5.0) * 1.0e-3
        span_m = max(span_m, 1.3 * max(radius_m, 0.5 * thickness_m))

        return MagnetParams(
            radius_m=radius_m,
            thickness_m=thickness_m,
            remanence_t=max(float(self.remanence_t.get()), 0.05),
            span_m=span_m,
            grid_n=grid_n,
        )

    def recompute(self):
        try:
            params = self.current_params()
            self.status_var.set("Computing high-accuracy field...")
            self.update_idletasks()
            started = perf_counter()
            data = sample_field_distribution(params)
            elapsed_ms = (perf_counter() - started) * 1.0e3
            self._draw_plots(params, data)
            self.status_var.set(
                f"Updated in {elapsed_ms:.1f} ms. "
                f"Axis validation max rel. error {data['axis_rel_error']:.2e}, "
                f"abs. error {data['axis_abs_error'] * 1.0e3:.3e} mT."
            )
        except Exception as exc:
            self.status_var.set(f"Computation failed: {exc}")

    def reset_view(self):
        self.ax3d.view_init(elev=self.default_elev, azim=self.default_azim)
        self.canvas3d.draw_idle()

    def _draw_plots(self, params: MagnetParams, data):
        elev = getattr(self.ax3d, "elev", self.default_elev)
        azim = getattr(self.ax3d, "azim", self.default_azim)

        if self.cbar3d is not None:
            self.cbar3d.remove()
            self.cbar3d = None
        if self.cbar2d is not None:
            self.cbar2d.remove()
            self.cbar2d = None

        self.ax3d.clear()
        self.ax2d.clear()

        points, vectors, magnitude_mt = self._prepare_3d_display_data(params, data)
        if len(points) == 0:
            raise RuntimeError("No points available for plotting.")

        mag_min = max(float(np.nanmin(magnitude_mt)), 1.0e-6)
        mag_max = max(float(np.nanmax(magnitude_mt)), mag_min * 1.01)
        norm = colors.LogNorm(vmin=mag_min, vmax=mag_max)
        segment_colors = cm.viridis(norm(magnitude_mt))

        start_mm = points * 1.0e3
        end_mm = (points + vectors) * 1.0e3
        segments = np.stack((start_mm, end_mm), axis=1)
        self.ax3d.add_collection3d(
            Line3DCollection(segments, colors=segment_colors, linewidths=1.35, alpha=0.96)
        )
        self.ax3d.scatter(
            end_mm[:, 0],
            end_mm[:, 1],
            end_mm[:, 2],
            c=magnitude_mt,
            cmap="viridis",
            norm=norm,
            s=10,
            depthshade=False,
            linewidths=0.0,
        )

        self._draw_cylinder(params)
        self.ax3d.set_title("3D field vectors")
        self.ax3d.set_xlabel("x [mm]")
        self.ax3d.set_ylabel("y [mm]")
        self.ax3d.set_zlabel("z [mm]")
        span_mm = params.span_m * 1.0e3
        self.ax3d.set_xlim(-span_mm, span_mm)
        self.ax3d.set_ylim(-span_mm, span_mm)
        self.ax3d.set_zlim(-span_mm, span_mm)
        self.ax3d.set_box_aspect((1.0, 1.0, 1.0))
        self.ax3d.view_init(elev=elev, azim=azim)

        sm = cm.ScalarMappable(norm=norm, cmap=cm.viridis)
        self.cbar3d = self.figure3d.colorbar(sm, ax=self.ax3d, fraction=0.05, pad=0.02, label="|B| [mT]")

        field_slice = data["field_slice"]
        bx = field_slice[:, :, 0] * 1.0e3
        bz = field_slice[:, :, 2] * 1.0e3
        slice_mag = np.ma.masked_invalid(np.hypot(bx, bz))
        slice_values = slice_mag.compressed()
        if slice_values.size == 0:
            raise RuntimeError("No slice data available for plotting.")

        x_axis = data["x_axis"] * 1.0e3
        z_axis = data["z_axis"] * 1.0e3
        slice_vmin = max(float(np.min(slice_values)), 1.0e-5)
        slice_vmax = max(float(np.max(slice_values)), slice_vmin * 1.01)

        image = self.ax2d.imshow(
            slice_mag,
            origin="lower",
            extent=(x_axis[0], x_axis[-1], z_axis[0], z_axis[-1]),
            cmap="inferno",
            norm=colors.LogNorm(vmin=slice_vmin, vmax=slice_vmax),
            interpolation="bilinear",
            aspect="equal",
        )

        step = max(3, params.slice_n // 19)
        x_sample = x_axis[::step]
        z_sample = z_axis[::step]
        bx_sample = np.ma.array(bx[::step, ::step], mask=~np.isfinite(bx[::step, ::step]))
        bz_sample = np.ma.array(bz[::step, ::step], mask=~np.isfinite(bz[::step, ::step]))
        sample_norm = np.ma.sqrt(bx_sample * bx_sample + bz_sample * bz_sample)
        dx = x_sample[1] - x_sample[0] if len(x_sample) > 1 else 1.0
        scale_mm = 0.75 * dx
        u = np.ma.divide(bx_sample, sample_norm).filled(0.0) * scale_mm
        v = np.ma.divide(bz_sample, sample_norm).filled(0.0) * scale_mm
        x_mesh, z_mesh = np.meshgrid(x_sample, z_sample, indexing="xy")
        self.ax2d.quiver(
            x_mesh,
            z_mesh,
            u,
            v,
            color="white",
            angles="xy",
            scale_units="xy",
            scale=1.0,
            width=0.004,
            alpha=0.85,
        )

        magnet_rect = Rectangle(
            (-params.radius_m * 1.0e3, -0.5 * params.thickness_m * 1.0e3),
            2.0 * params.radius_m * 1.0e3,
            params.thickness_m * 1.0e3,
            facecolor="#7a0019",
            edgecolor="white",
            linewidth=1.0,
            alpha=0.82,
        )
        self.ax2d.add_patch(magnet_rect)

        self.ax2d.set_title("Central x-z slice")
        self.ax2d.set_xlabel("x [mm]")
        self.ax2d.set_ylabel("z [mm]")
        self.ax2d.set_xlim(x_axis[0], x_axis[-1])
        self.ax2d.set_ylim(z_axis[0], z_axis[-1])
        self.cbar2d = self.figure2d.colorbar(image, ax=self.ax2d, fraction=0.05, pad=0.02, label="|B| [mT]")

        self.canvas2d.draw()
        self.canvas3d.draw()

    def _prepare_3d_display_data(self, params: MagnetParams, data):
        grid_n = len(data["axis"])
        points_grid = data["points_3d"].reshape(grid_n, grid_n, grid_n, 3)
        field_grid = data["field_3d"].reshape(grid_n, grid_n, grid_n, 3)

        display_n = min(5, grid_n)
        sample_idx = np.unique(np.linspace(0, grid_n - 1, display_n, dtype=int))
        points = points_grid[np.ix_(sample_idx, sample_idx, sample_idx)].reshape(-1, 3)
        field = field_grid[np.ix_(sample_idx, sample_idx, sample_idx)].reshape(-1, 3)

        valid = np.isfinite(field[:, 0])
        points = points[valid]
        field = field[valid]
        if len(points) == 0:
            return points, field, np.array([], dtype=float)

        magnitude = np.linalg.norm(field, axis=1)
        magnitude_mt = np.maximum(magnitude * 1.0e3, 1.0e-6)
        max_mag = max(float(np.nanmax(magnitude)), 1.0e-12)
        directions = field / np.maximum(magnitude[:, None], 1.0e-12)

        sample_axis = data["axis"][sample_idx]
        if len(sample_axis) > 1:
            display_spacing = float(np.min(np.diff(sample_axis)))
        else:
            display_spacing = (2.0 * params.span_m) / max(params.grid_n - 1, 1)
        vector_length = display_spacing * (0.18 + 0.52 * np.sqrt(magnitude / max_mag))
        vectors = directions * vector_length[:, None]
        return points, vectors, magnitude_mt

    def _draw_cylinder(self, params: MagnetParams):
        theta = np.linspace(0.0, 2.0 * math.pi, 64)
        x_circle = params.radius_m * np.cos(theta) * 1.0e3
        y_circle = params.radius_m * np.sin(theta) * 1.0e3
        z_top = np.full_like(theta, 0.5 * params.thickness_m * 1.0e3)
        z_bottom = np.full_like(theta, -0.5 * params.thickness_m * 1.0e3)

        self.ax3d.plot(x_circle, y_circle, z_top, color="#d6604d", linewidth=1.8, alpha=0.95)
        self.ax3d.plot(x_circle, y_circle, z_bottom, color="#d6604d", linewidth=1.8, alpha=0.95)

        for phi in np.linspace(0.0, 1.5 * math.pi, 4):
            x_edge = params.radius_m * math.cos(phi) * 1.0e3
            y_edge = params.radius_m * math.sin(phi) * 1.0e3
            self.ax3d.plot(
                [x_edge, x_edge],
                [y_edge, y_edge],
                [-0.5 * params.thickness_m * 1.0e3, 0.5 * params.thickness_m * 1.0e3],
                color="#b2182b",
                linewidth=1.4,
                alpha=0.85,
            )


def main():
    app = MagnetFieldViewer()
    app.mainloop()


if __name__ == "__main__":
    main()
