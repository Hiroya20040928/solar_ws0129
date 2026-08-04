#!/usr/bin/env python3
"""Generate the release OCV/Rint audit report for fitted or blank packages."""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]


def _display_path(path: Path | None) -> str:
    if path is None:
        return ""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def _finite(value, default=math.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _resolve(profile_path: Path, raw_path: str | Path | None) -> Path | None:
    text = str(raw_path or "").strip()
    if not text:
        return None
    path = Path(text)
    return path.resolve() if path.is_absolute() else (profile_path.parent / path).resolve()


def _read_wide_map(path: Path | None) -> pd.DataFrame | None:
    if path is None or not path.is_file():
        return None
    try:
        frame = pd.read_csv(path, index_col=0)
    except Exception:
        return None
    if frame.empty or frame.shape[1] == 0:
        return None
    frame.index = pd.to_numeric(frame.index, errors="coerce")
    frame.columns = pd.to_numeric(frame.columns, errors="coerce")
    frame = frame.loc[frame.index.notna(), frame.columns.notna()].apply(
        pd.to_numeric, errors="coerce"
    )
    if frame.empty or not np.isfinite(frame.to_numpy(dtype=float)).any():
        return None
    return frame.sort_index().sort_index(axis=1)


def _read_ocv(path: Path | None) -> pd.DataFrame | None:
    if path is None or not path.is_file():
        return None
    try:
        frame = pd.read_csv(path)
    except Exception:
        return None
    if not {"soc", "ocv_v"}.issubset(frame.columns):
        return None
    frame = frame[["soc", "ocv_v"]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(frame) < 2:
        return None
    return frame.sort_values("soc").drop_duplicates("soc", keep="last")


def _read_yaml(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _read_replay(path: Path | None) -> pd.DataFrame | None:
    if path is None or not path.is_file():
        return None
    try:
        frame = pd.read_csv(path, low_memory=False)
    except Exception:
        return None
    for column in (
        "soc_pred",
        "battery_current_a_obs",
        "battery_voltage_v_obs",
        "battery_voltage_v_pred",
        "Tamb_C",
        "day",
    ):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _voltage_residual_audit(
    replay: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Separate clean residual evidence from rows excluded by the fit contract."""
    required = {"soc_pred", "battery_voltage_v_obs", "battery_voltage_v_pred"}
    if not required.issubset(replay.columns):
        return pd.DataFrame(), pd.DataFrame(), {}

    work = replay.copy()
    work["voltage_residual_v"] = (
        pd.to_numeric(work["battery_voltage_v_obs"], errors="coerce")
        - pd.to_numeric(work["battery_voltage_v_pred"], errors="coerce")
    )
    work["soc_pred"] = pd.to_numeric(work["soc_pred"], errors="coerce")
    if "battery_current_a_obs" in work:
        work["battery_current_a_obs"] = pd.to_numeric(
            work["battery_current_a_obs"], errors="coerce"
        )
    else:
        work["battery_current_a_obs"] = math.nan

    valid = work[["soc_pred", "voltage_residual_v"]].notna().all(axis=1)
    if "exclude_voltage_fit" in work:
        excluded_flag = (
            work["exclude_voltage_fit"]
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"true", "1", "yes"})
        )
    else:
        excluded_flag = pd.Series(False, index=work.index)
    clean = work.loc[valid & ~excluded_flag].copy()
    excluded = work.loc[valid & excluded_flag].copy()

    def region(low: float, high: float) -> dict:
        group = clean.loc[clean["soc_pred"].between(low, high, inclusive="both")]
        residual = group["voltage_residual_v"].to_numpy(dtype=float)
        current = group["battery_current_a_obs"]
        near_zero = group.loc[current.abs() < 1.0, "voltage_residual_v"]
        charge = group.loc[current < -5.0, "voltage_residual_v"]
        discharge = group.loc[current > 5.0, "voltage_residual_v"]
        return {
            "soc_min": low,
            "soc_max": high,
            "rows": int(len(group)),
            "residual_median_v": float(np.median(residual)) if residual.size else math.nan,
            "residual_rmse_v": (
                float(np.sqrt(np.mean(residual**2))) if residual.size else math.nan
            ),
            "residual_p05_v": (
                float(np.quantile(residual, 0.05)) if residual.size else math.nan
            ),
            "residual_p95_v": (
                float(np.quantile(residual, 0.95)) if residual.size else math.nan
            ),
            "near_zero_current_rows": int(len(near_zero)),
            "near_zero_current_residual_median_v": (
                float(near_zero.median()) if len(near_zero) else math.nan
            ),
            "charge_current_rows": int(len(charge)),
            "charge_residual_median_v": float(charge.median()) if len(charge) else math.nan,
            "discharge_current_rows": int(len(discharge)),
            "discharge_residual_median_v": (
                float(discharge.median()) if len(discharge) else math.nan
            ),
        }

    if clean.empty:
        zoom_limits = [math.nan, math.nan]
    else:
        low, high = clean["voltage_residual_v"].quantile([0.005, 0.995]).to_numpy()
        span = max(float(high - low), 0.5)
        zoom_limits = [
            float(min(low - 0.08 * span, -0.25)),
            float(max(high + 0.08 * span, 0.25)),
        ]
    audit = {
        "residual_definition": "battery_voltage_v_obs - battery_voltage_v_pred",
        "valid_rows": int(valid.sum()),
        "excluded_rows": int((valid & excluded_flag).sum()),
        "clean_rows": int(len(clean)),
        "zoom_limits_v": zoom_limits,
        "regions": {
            "mid_soc_0p40_to_0p70": region(0.40, 0.70),
            "high_soc_0p85_to_0p98": region(0.85, 0.98),
            "very_high_soc_0p90_to_0p98": region(0.90, 0.98),
        },
        "rint_identification_equation": (
            "e_V = delta_OCV - I * delta_R - delta_V_polarization + sensor_error"
        ),
        "warning": (
            "A voltage residual is not a supervised Rint label. Near-zero-current "
            "residuals cannot be removed by changing Rint."
        ),
    }
    return clean, excluded, audit


def _png(fig: plt.Figure) -> str:
    stream = io.BytesIO()
    fig.savefig(stream, format="png", dpi=135, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def _message(title: str, lines: list[str], *, color: str = "#7f1d1d") -> plt.Figure:
    fig, ax = plt.subplots(figsize=(9.6, 5.0))
    ax.axis("off")
    ax.text(0.5, 0.82, title, ha="center", fontsize=17, weight="bold", color=color)
    ax.text(0.5, 0.43, "\n".join(lines), ha="center", va="center", fontsize=11)
    return fig


def _slice(frame: pd.DataFrame, temperature_c: float = 25.0) -> tuple[np.ndarray, np.ndarray]:
    index = frame.index.to_numpy(dtype=float)
    row = frame.iloc[int(np.argmin(np.abs(index - temperature_c)))]
    return frame.columns.to_numpy(dtype=float), row.to_numpy(dtype=float)


def _interp_surface(frame: pd.DataFrame, temperature_c: float, soc: np.ndarray) -> np.ndarray:
    temperatures = frame.index.to_numpy(dtype=float)
    lower = int(np.searchsorted(temperatures, temperature_c, side="right") - 1)
    lower = int(np.clip(lower, 0, len(temperatures) - 1))
    upper = min(lower + 1, len(temperatures) - 1)
    if upper == lower:
        weight = 0.0
    else:
        weight = (temperature_c - temperatures[lower]) / (
            temperatures[upper] - temperatures[lower]
        )
    columns = frame.columns.to_numpy(dtype=float)
    low_values = np.interp(soc, columns, frame.iloc[lower].to_numpy(dtype=float))
    high_values = np.interp(soc, columns, frame.iloc[upper].to_numpy(dtype=float))
    return (1.0 - weight) * low_values + weight * high_values


def _surface_figure(frame: pd.DataFrame | None, title: str) -> plt.Figure:
    if frame is None:
        return _message(title, ["No numerical map is installed.", "Identification is required."])
    fig, ax = plt.subplots(figsize=(9.4, 5.2))
    image = ax.imshow(
        frame.to_numpy(dtype=float),
        origin="lower",
        aspect="auto",
        extent=[frame.columns.min(), frame.columns.max(), frame.index.min(), frame.index.max()],
        cmap="viridis",
    )
    ax.set(xlabel="SoC [-]", ylabel="temperature [C]", title=title)
    fig.colorbar(image, ax=ax, label="resistance [ohm]")
    return fig


def _add(items: list[tuple[str, str]], title: str, figure: plt.Figure) -> None:
    items.append((title, _png(figure)))


def generate(
    *,
    profile_path: Path,
    output_html: Path,
    base_rint_csv: Path | None = None,
    fit_summary_yaml: Path | None = None,
    replay_csv: Path | None = None,
    package_label: str = "",
) -> dict:
    profile_path = profile_path.resolve()
    profile = _read_yaml(profile_path)
    paths = dict(profile.get("paths", {}) or {})
    model = dict(profile.get("model", {}) or {})
    identification = dict(profile.get("identification", {}) or {})

    adopted_rint_path = _resolve(profile_path, paths.get("rint_map"))
    ocv_path = _resolve(profile_path, paths.get("ocv_soc_map"))
    if fit_summary_yaml is None:
        fit_summary_yaml = _resolve(profile_path, identification.get("fit_summary_yaml"))
    if replay_csv is None and fit_summary_yaml is not None:
        candidate = fit_summary_yaml.parent / "replay_validation_battery_conditioned.csv"
        replay_csv = candidate if candidate.is_file() else None

    base_rint = _read_wide_map(base_rint_csv)
    adopted_rint = _read_wide_map(adopted_rint_path)
    ocv = _read_ocv(ocv_path)
    fit_summary = _read_yaml(fit_summary_yaml)
    replay = _read_replay(replay_csv)
    battery_fit = dict(fit_summary.get("battery_fit", {}) or {})
    dynamic_fit = dict(fit_summary.get("battery_dynamic_fit", {}) or {})
    validation = dict(fit_summary.get("validation_metrics", {}) or {})
    rint_shape = dict((fit_summary.get("map_shape_fit", {}) or {}).get("rint_map", {}) or {})

    label = package_label or str((profile.get("meta", {}) or {}).get("name", profile_path.stem))
    rint_scale = _finite(model.get("rint_scale", battery_fit.get("rint_scale", 1.0)), 1.0)
    r_line = _finite(model.get("r_line_ohm", battery_fit.get("r_line_ohm", 0.0)), 0.0)
    r_polarization = _finite(
        model.get("r_polarization_ohm", dynamic_fit.get("r_polarization_ohm", 0.0)), 0.0
    )
    tau_sec = _finite(model.get("polarization_tau_sec", dynamic_fit.get("tau_sec", 0.0)), 0.0)
    template_unidentified = adopted_rint is None or ocv is None or _finite(model.get("E_nom_Wh"), 0.0) <= 0.0
    physical_summary = dict(identification.get("battery_ecm", {}) or {})
    physical_gate = bool(
        physical_summary.get(
            "physical_gate_pass", physical_summary.get("gate_pass", False)
        )
    )
    release_status = (
        "template_unidentified"
        if template_unidentified
        else "pulse_certified"
        if physical_gate
        else "research_only_not_pulse_certified"
    )

    figures: list[tuple[str, str]] = []

    fig, ax = plt.subplots(figsize=(10.0, 5.2))
    ax.axis("off")
    boxes = [
        (0.12, "rested OCV\nindependent SoC"),
        (0.37, "sub-second pulse\nR0, R1, tau"),
        (0.62, "untouched holdout\nphysical gate"),
        (0.87, "profile promotion\nMPC / replay"),
    ]
    for x_value, text_value in boxes:
        ax.text(x_value, 0.52, text_value, ha="center", va="center", bbox={"boxstyle": "round", "fc": "#ecfccb", "ec": "#3f6212"})
    for left, right in zip(boxes[:-1], boxes[1:]):
        ax.annotate("", xy=(right[0] - 0.09, 0.52), xytext=(left[0] + 0.09, 0.52), arrowprops={"arrowstyle": "->"})
    ax.set_title("Current identifiable battery-map workflow", fontsize=17, weight="bold")
    _add(figures, "1．処理全体", fig)

    if ocv is None:
        _add(figures, "2．現行OCV", _message("OCV is not identified", ["Fill the rest-test CSV and run the ECM fitter."]))
        _add(figures, "3．OCV勾配", _message("OCV slope is unavailable", ["Loaded-voltage slope must not be converted into R0."]))
    else:
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        ax.plot(ocv["soc"], ocv["ocv_v"], linewidth=2.2)
        ax.set(xlabel="SoC [-]", ylabel="pack OCV [V]", title="Current profile OCV artifact")
        ax.grid(True, alpha=0.25)
        _add(figures, "2．現行OCV", fig)
        gradient = np.gradient(ocv["ocv_v"].to_numpy(dtype=float), ocv["soc"].to_numpy(dtype=float))
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        ax.plot(ocv["soc"], gradient, linewidth=2.0)
        ax.axhline(0.0, color="black", linewidth=0.8)
        ax.set(xlabel="SoC [-]", ylabel="dOCV/dSoC [V]", title="OCV slope is diagnostic, not an R0 estimator")
        ax.grid(True, alpha=0.25)
        _add(figures, "3．OCV勾配", fig)

    _add(
        figures,
        "4．旧固定値式の扱い",
        _message(
            "Fixed 0.040 ohm/cell formula is prohibited",
            [
                "Loaded voltage = OCV + ohmic drop + polarization + measurement error.",
                "The old slope-power formula is retained only as provenance/audit evidence.",
            ],
            color="#1d4ed8",
        ),
    )
    _add(figures, "5．基礎Rint面", _surface_figure(base_rint, "Grounded/legacy base Rint surface"))
    _add(figures, "6．現行採用Rint面", _surface_figure(adopted_rint, "Current profile Rint surface"))

    if base_rint is not None and adopted_rint is not None:
        common_soc = np.linspace(
            max(base_rint.columns.min(), adopted_rint.columns.min()),
            min(base_rint.columns.max(), adopted_rint.columns.max()),
            250,
        )
        base_25 = _interp_surface(base_rint, 25.0, common_soc)
        adopted_25 = _interp_surface(adopted_rint, 25.0, common_soc)
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        ax.plot(common_soc, base_25, label="base", linewidth=2.0)
        ax.plot(common_soc, adopted_25, label="current", linewidth=2.0)
        ax.set(xlabel="SoC [-]", ylabel="R [ohm]", title="Base/current comparison at 25 C")
        ax.grid(True, alpha=0.25); ax.legend()
        _add(figures, "7．25℃基礎・採用比較", fig)
        ratio = adopted_25 / np.maximum(base_25, 1.0e-12)
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        ax.plot(common_soc, ratio, linewidth=2.0)
        ax.axhline(1.0, color="black", linewidth=0.8)
        ax.set(xlabel="SoC [-]", ylabel="current/base [-]", title="Map correction ratio at 25 C")
        ax.grid(True, alpha=0.25)
        _add(figures, "8．マップ補正倍率", fig)
    else:
        _add(figures, "7．25℃基礎・採用比較", _message("Comparison unavailable", ["Both base and current maps are required."]))
        _add(figures, "8．マップ補正倍率", _message("Correction ratio unavailable", ["No fitted map has been promoted."]))

    fig, ax = plt.subplots(figsize=(9.2, 5.0))
    ax.bar(["Rint scale", "Rline [ohm]", "R1 [ohm]"], [rint_scale, r_line, r_polarization], color=["#2563eb", "#b45309", "#0f766e"])
    ax.set_title("Current scalar battery parameters")
    for index, value in enumerate((rint_scale, r_line, r_polarization)):
        ax.text(index, value, f"{value:.6g}", ha="center", va="bottom")
    _add(figures, "9．スカラー係数", fig)

    if adopted_rint is None:
        for title in ("10．最終R0経路", "11．1-RC分極枝", "12．定常総抵抗"):
            _add(figures, title, _message("Battery model is not identified", ["No numerical release values are available."]))
        soc_grid = np.linspace(0.1, 0.95, 200)
        r0_path = np.full_like(soc_grid, np.nan)
    else:
        soc_grid = np.linspace(adopted_rint.columns.min(), adopted_rint.columns.max(), 250)
        map_25 = _interp_surface(adopted_rint, 25.0, soc_grid)
        r0_path = rint_scale * map_25 + r_line
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        ax.plot(soc_grid, r0_path, linewidth=2.2)
        ax.set(xlabel="SoC [-]", ylabel="R0 path [ohm]", title="Rint scale * map + Rline")
        ax.grid(True, alpha=0.25)
        _add(figures, "10．最終R0経路", fig)
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        time_grid = np.linspace(0.0, max(300.0, 5.0 * max(tau_sec, 1.0)), 300)
        response = r_polarization * (1.0 - np.exp(-time_grid / max(tau_sec, 1.0e-9)))
        ax.plot(time_grid, response, linewidth=2.2)
        ax.set(xlabel="time after current step [s]", ylabel="apparent R1 contribution [ohm]", title=f"1-RC branch: R1={r_polarization:.6f} ohm, tau={tau_sec:.3f} s")
        ax.grid(True, alpha=0.25)
        _add(figures, "11．1-RC分極枝", fig)
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        ax.plot(soc_grid, r0_path, label="R0 path", linewidth=2.0)
        ax.plot(soc_grid, r0_path + r_polarization, label="steady R0+R1", linewidth=2.0)
        ax.set(xlabel="SoC [-]", ylabel="resistance [ohm]", title="Instantaneous and steady resistance")
        ax.grid(True, alpha=0.25); ax.legend()
        _add(figures, "12．定常総抵抗", fig)

    if np.isfinite(r0_path).any():
        reference_r = float(np.interp(0.5, soc_grid, r0_path))
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        currents = np.asarray([0.0, 5.0, 10.0, 20.0, 30.0])
        ax.plot(currents, currents * reference_r, marker="o", label="instantaneous R0")
        ax.plot(currents, currents * (reference_r + r_polarization), marker="o", label="steady R0+R1")
        ax.set(xlabel="current [A]", ylabel="voltage drop [V]", title="Voltage-drop sensitivity at SoC=0.5, 25 C")
        ax.grid(True, alpha=0.25); ax.legend()
        _add(figures, "13．電流別電圧降下", fig)
        if ocv is not None:
            ocv_ref = float(np.interp(0.5, ocv["soc"], ocv["ocv_v"]))
            fig, ax = plt.subplots(figsize=(9.4, 5.0))
            ax.plot(currents, ocv_ref - currents * reference_r, marker="o", label="instantaneous")
            ax.plot(currents, ocv_ref - currents * (reference_r + r_polarization), marker="o", label="steady")
            ax.set(xlabel="current [A]", ylabel="terminal voltage [V]", title="Reference terminal-voltage sensitivity")
            ax.grid(True, alpha=0.25); ax.legend()
            _add(figures, "14．端子電圧感度", fig)
        else:
            _add(figures, "14．端子電圧感度", _message("Terminal-voltage plot unavailable", ["OCV has not been identified."]))
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        mask = soc_grid >= max(0.75, float(np.nanmin(soc_grid)))
        ax.plot(soc_grid[mask], r0_path[mask], linewidth=2.2)
        ax.set(xlabel="SoC [-]", ylabel="R0 path [ohm]", title="High-SoC audit region")
        ax.grid(True, alpha=0.25)
        _add(figures, "15．高SoC領域", fig)
    else:
        for title in ("13．電流別電圧降下", "14．端子電圧感度", "15．高SoC領域"):
            _add(figures, title, _message("Plot unavailable", ["The blank package contains no fitted battery map."]))

    if replay is not None and "soc_pred" in replay:
        soc_values = replay["soc_pred"].dropna().to_numpy(dtype=float)
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        ax.hist(soc_values, bins=30, color="#2563eb", alpha=0.82)
        ax.set(xlabel="fitted SoC [-]", ylabel="sample count", title="Replay SoC coverage")
        _add(figures, "16．実測SoCカバレッジ", fig)
    else:
        _add(figures, "16．実測SoCカバレッジ", _message("No replay evidence", ["Coverage cannot be checked in this package."]))

    residual_audit = {}
    if replay is not None and {"soc_pred", "battery_voltage_v_obs", "battery_voltage_v_pred"}.issubset(replay.columns):
        clean_residual, excluded_residual, residual_audit = _voltage_residual_audit(replay)
        if clean_residual.empty:
            _add(figures, "17．電圧残差構造", _message("No clean replay residual", ["Every voltage row was invalid or excluded."]))
        else:
            reduced = clean_residual.iloc[::max(1, len(clean_residual) // 7000)]
            fig, (ax_zoom, ax_full) = plt.subplots(
                2,
                1,
                figsize=(10.2, 9.0),
                sharex=True,
                gridspec_kw={"height_ratios": [2.2, 1.0]},
            )
            current = reduced["battery_current_a_obs"]
            finite_current = current[np.isfinite(current)]
            if len(finite_current):
                current_limit = max(1.0, float(finite_current.abs().quantile(0.98)))
                points = ax_zoom.scatter(
                    reduced["soc_pred"],
                    reduced["voltage_residual_v"],
                    c=current.clip(-current_limit, current_limit),
                    cmap="coolwarm",
                    vmin=-current_limit,
                    vmax=current_limit,
                    s=7,
                    alpha=0.28,
                )
                fig.colorbar(points, ax=ax_zoom, label="observed current [A]")
            else:
                ax_zoom.scatter(
                    reduced["soc_pred"], reduced["voltage_residual_v"], s=7, alpha=0.28
                )

            bin_edges = np.linspace(
                float(clean_residual["soc_pred"].min()),
                float(clean_residual["soc_pred"].max()),
                14,
            )
            centers = []
            medians = []
            lower_errors = []
            upper_errors = []
            for left, right in zip(bin_edges[:-1], bin_edges[1:]):
                group = clean_residual.loc[
                    clean_residual["soc_pred"].between(left, right, inclusive="left"),
                    "voltage_residual_v",
                ]
                if len(group) < 20:
                    continue
                median = float(group.median())
                p05 = float(group.quantile(0.05))
                p95 = float(group.quantile(0.95))
                centers.append(0.5 * (left + right))
                medians.append(median)
                lower_errors.append(median - p05)
                upper_errors.append(p95 - median)
            if centers:
                ax_zoom.errorbar(
                    centers,
                    medians,
                    yerr=[lower_errors, upper_errors],
                    color="black",
                    marker="o",
                    markersize=4,
                    linewidth=1.3,
                    capsize=2,
                    label="SoC-bin median and 5-95%",
                )
            ax_zoom.axhline(0.0, color="black", linewidth=0.8)
            ax_zoom.set_ylim(*residual_audit["zoom_limits_v"])
            ax_zoom.set(
                ylabel="observed-predicted [V]",
                title="Clean voltage residual by fitted SoC (robust zoom)",
            )
            ax_zoom.grid(True, alpha=0.25)
            ax_zoom.legend(loc="best")

            ax_full.scatter(
                reduced["soc_pred"],
                reduced["voltage_residual_v"],
                s=5,
                alpha=0.18,
                color="#2563eb",
                label="clean rows",
            )
            if not excluded_residual.empty:
                excluded_reduced = excluded_residual.iloc[
                    ::max(1, len(excluded_residual) // 1500)
                ]
                ax_full.scatter(
                    excluded_reduced["soc_pred"],
                    excluded_reduced["voltage_residual_v"],
                    s=18,
                    alpha=0.65,
                    marker="x",
                    color="#b91c1c",
                    label=f"excluded sensor rows ({len(excluded_residual)})",
                )
            ax_full.axhline(0.0, color="black", linewidth=0.8)
            ax_full.set(
                xlabel="fitted SoC [-]",
                ylabel="residual [V]",
                title="Full range retained for exclusion audit",
            )
            ax_full.grid(True, alpha=0.25)
            ax_full.legend(loc="best")
            fig.tight_layout()
            _add(figures, "17．電圧残差構造", fig)
    else:
        _add(figures, "17．電圧残差構造", _message("No replay residual", ["Fit and replay must complete before residual evaluation."]))

    metric_names = [
        "voltage_rmse_clean_v",
        "battery_conditional_voltage_rmse_clean_v",
        "end_to_end_voltage_rmse_clean_v",
    ]
    metric_values = [_finite(validation.get(key)) for key in metric_names]
    if any(math.isfinite(value) for value in metric_values):
        fig, ax = plt.subplots(figsize=(9.4, 5.0))
        labels = ["vehicle", "battery-conditioned", "end-to-end"]
        values = [value if math.isfinite(value) else 0.0 for value in metric_values]
        ax.bar(labels, values, color=["#475569", "#2563eb", "#b45309"])
        ax.axhline(1.0, color="#b91c1c", linestyle="--", label="1 V strict gate")
        ax.set(ylabel="voltage RMSE [V]", title="Current replay validation metrics")
        ax.legend()
        _add(figures, "18．RMSE評価", fig)
    else:
        _add(figures, "18．RMSE評価", _message("No validation metrics", ["The template is intentionally unfitted."]))

    checks = {
        "numerical OCV map": ocv is not None,
        "numerical Rint map": adopted_rint is not None,
        "fit summary": bool(fit_summary),
        "replay evidence": replay is not None,
        "independent rested OCV": bool(physical_summary.get("rest_gate_pass", False)),
        "sub-second pulse grid": bool(physical_summary.get("pulse_gate_pass", False)),
        "independent pulse holdout": physical_gate,
    }
    fig, ax = plt.subplots(figsize=(9.4, 5.2))
    ax.barh(list(checks), [int(value) for value in checks.values()], color=["#15803d" if value else "#b91c1c" for value in checks.values()])
    ax.set_xlim(0.0, 1.05); ax.set_title("Release evidence gate")
    _add(figures, "19．物理証拠ゲート", fig)

    conclusion = {
        "template_unidentified": ["BLANK TEMPLATE", "Insert the required rest/pulse data before fitting.", "Simulation/live promotion remains blocked."],
        "pulse_certified": ["PULSE-CERTIFIED MODEL", "Independent rest/pulse and holdout gates passed.", "Review all other vehicle-model gates before live use."],
        "research_only_not_pulse_certified": ["RESEARCH-ONLY CONDITIONAL MODEL", "MLE/replay artifacts are installed, but R0 is not pulse-certified.", "Do not treat aggregate RMSE as physical proof."],
    }[release_status]
    _add(figures, "20．現行判定", _message(conclusion[0], conclusion[1:], color="#166534" if physical_gate else "#7f1d1d"))

    summary = {
        "schema_version": 1,
        "package_label": label,
        "profile": _display_path(profile_path),
        "release_status": release_status,
        "physical_gate_pass": physical_gate,
        "template_unidentified": template_unidentified,
        "paths": {
            "ocv_soc_map": _display_path(ocv_path),
            "base_rint_map": _display_path(base_rint_csv),
            "adopted_rint_map": _display_path(adopted_rint_path),
            "fit_summary_yaml": _display_path(fit_summary_yaml),
            "replay_csv": _display_path(replay_csv),
        },
        "model": {
            "rint_scale": rint_scale,
            "r_line_ohm": r_line,
            "r_polarization_ohm": r_polarization,
            "polarization_tau_sec": tau_sec,
        },
        "rint_shape_adopted": bool(rint_shape.get("adopted", False)),
        "rint_shape_reason": str(rint_shape.get("reason", rint_shape.get("adoption_reason", ""))),
        "validation_metrics": {key: validation.get(key) for key in metric_names},
        "voltage_residual_audit": residual_audit,
        "checks": checks,
        "figure_count": len(figures),
    }

    cards = "".join(
        f'<div class="metric"><b>{html.escape(name)}</b><span>{"PASS" if value else "FAIL"}</span></div>'
        for name, value in checks.items()
    )
    sections = "".join(
        f'<section><h2>{html.escape(title)}</h2><img src="{uri}" alt="{html.escape(title)}"></section>'
        for title, uri in figures
    )
    output_html.parent.mkdir(parents=True, exist_ok=True)
    body = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>OCV・Rint基礎マップとMLE補正の完全可視化（現行版）</title>
<style>
:root{{--ink:#16202a;--paper:#fffdf7;--sand:#eee7d8;--line:#d5cbb8;--red:#991b1b;--green:#166534}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(135deg,#e9dfcb,#f8f4ea);font-family:"Yu Gothic","Hiragino Kaku Gothic ProN",sans-serif;color:var(--ink)}}
main{{max-width:1160px;margin:auto;padding:30px}}header,section{{background:var(--paper);border:1px solid var(--line);border-radius:22px;padding:22px;margin:0 0 18px;box-shadow:0 12px 35px rgba(59,45,24,.07)}}
h1{{margin:0 0 10px;font-size:30px}}h2{{margin:0 0 14px}}.status{{display:inline-block;padding:8px 13px;border-radius:999px;background:#fee2e2;color:var(--red);font-weight:800}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px;margin-top:16px}}.metric{{display:flex;justify-content:space-between;gap:10px;padding:11px;border-radius:12px;background:#f5efe3}}img{{display:block;width:100%;height:auto}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5efe3;padding:14px;border-radius:12px}}
</style></head><body><main>
<header><h1>OCV・Rint基礎マップとMLE補正の完全可視化（現行版）</h1><p><b>{html.escape(label)}</b></p><div class="status">{html.escape(release_status)}</div>
<p>旧レポートの20項目構成を保ちつつ、負荷時電圧勾配をR0へ変換する旧式を廃止し、OCV・R0・1-RC分極・独立証拠ゲートを分離して表示します。</p><div class="grid">{cards}</div></header>
{sections}<section><h2>コード対応・数値検証JSON</h2><pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre></section>
</main></body></html>"""
    output_html.write_text(body, encoding="utf-8", newline="\n")
    output_html.with_suffix(".json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output-html", type=Path, required=True)
    parser.add_argument("--base-rint-csv", type=Path)
    parser.add_argument("--fit-summary-yaml", type=Path)
    parser.add_argument("--replay-csv", type=Path)
    parser.add_argument("--package-label", default="")
    args = parser.parse_args()
    result = generate(
        profile_path=args.profile,
        output_html=args.output_html,
        base_rint_csv=args.base_rint_csv,
        fit_summary_yaml=args.fit_summary_yaml,
        replay_csv=args.replay_csv,
        package_label=args.package_label,
    )
    print(json.dumps({"output_html": str(args.output_html), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
