# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


DOCS_DIR = Path(__file__).resolve().parent
REPO_ROOT = DOCS_DIR.parent
ASSET_DIR = DOCS_DIR / "assets" / "bwsc2027_master_guide"


def configure_matplotlib() -> None:
    plt.rcParams["figure.dpi"] = 160
    plt.rcParams["savefig.dpi"] = 200
    plt.rcParams["font.size"] = 11
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.25
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Yu Gothic", "Meiryo", "MS Gothic", "DejaVu Sans"]


def ensure_output_dir() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)


def load_profile() -> dict:
    profile_path = REPO_ROOT / "config" / "solar" / "bwsc_2027_demo.yaml"
    with profile_path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def save_figure(fig: plt.Figure, name: str) -> None:
    try:
        fig.tight_layout()
    except RuntimeError:
        pass
    fig.savefig(ASSET_DIR / name, bbox_inches="tight")
    plt.close(fig)


def plot_shock_current_chart() -> None:
    voltage = np.linspace(0.0, 60.0, 400)
    resistances = [
        (500.0, "500 Ω (wet / severe contact)"),
        (2_000.0, "2 kΩ (sweaty skin)"),
        (10_000.0, "10 kΩ (dry skin)"),
    ]

    fig, ax = plt.subplots(figsize=(8.4, 4.8))
    ax.axhspan(0, 1, color="#d9f0d3", alpha=0.6, label="Below perception (~1 mA)")
    ax.axhspan(1, 10, color="#fee08b", alpha=0.5, label="Perception to let-go region")
    ax.axhspan(10, 30, color="#fdae61", alpha=0.35, label="Painful / loss-of-control region")
    ax.axhspan(30, 120, color="#d73027", alpha=0.18, label="Potentially fatal region")

    for resistance, label in resistances:
        current_ma = 1000.0 * voltage / resistance
        ax.plot(voltage, current_ma, linewidth=2.0, label=label)

    ax.set_xlim(0, 60)
    ax.set_ylim(0, 120)
    ax.set_xlabel("Applied voltage [V]")
    ax.set_ylabel("Body current [mA]")
    ax.set_title("Why moisture makes the same voltage more dangerous")
    ax.legend(loc="upper left", fontsize=8)
    save_figure(fig, "shock_current_vs_voltage.png")


def plot_battery_voltage_concept() -> None:
    soc = np.linspace(0.02, 1.0, 300)
    ocv = 3.05 + 0.85 * soc + 0.32 / (1.0 + np.exp(-12.0 * (soc - 0.18)))
    ocv = np.clip(ocv, 2.7, 4.2)
    r_int = 0.025
    capacity_ah = 5.0
    current_half_c = 0.5 * capacity_ah
    current_one_c = 1.0 * capacity_ah
    current_two_c = 2.0 * capacity_ah
    v_half_c = ocv - current_half_c * r_int
    v_one_c = ocv - current_one_c * r_int
    v_two_c = ocv - current_two_c * r_int

    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.plot(soc * 100.0, ocv, linewidth=2.5, label="OCV")
    ax.plot(soc * 100.0, v_half_c, linewidth=2.0, label="Terminal voltage at 0.5C discharge")
    ax.plot(soc * 100.0, v_one_c, linewidth=2.0, label="Terminal voltage at 1C discharge")
    ax.plot(soc * 100.0, v_two_c, linewidth=2.0, label="Terminal voltage at 2C discharge")
    ax.axhline(4.2, color="#b2182b", linestyle="--", linewidth=1.2, label="Typical Li-ion upper limit")
    ax.axhline(2.7, color="#2166ac", linestyle="--", linewidth=1.2, label="Typical Li-ion lower limit")
    ax.set_xlim(0, 100)
    ax.set_ylim(2.6, 4.3)
    ax.set_xlabel("State of charge [%]")
    ax.set_ylabel("Cell voltage [V]")
    ax.set_title("OCV is not the same as terminal voltage while current is flowing")
    ax.legend(loc="lower left", fontsize=8)
    save_figure(fig, "battery_ocv_terminal_concept.png")


def plot_vehicle_power_components(profile: dict) -> None:
    model = profile["model"]
    speed_kmh = np.linspace(20.0, 120.0, 250)
    speed_ms = speed_kmh / 3.6

    rho = float(model["rho"])
    cda = float(model["CdA"])
    crr = float(model["Crr"])
    mass = float(model["m"])
    p_aux = float(model["P_aux"])
    inverter_eta = float(model["inverter_eta"])
    gear_eta = float(model["gear_eta"])
    drive_eta = max(0.65, min(0.99, inverter_eta * gear_eta * 0.95))
    g = 9.80665

    f_air = 0.5 * rho * cda * speed_ms**2
    f_roll = crr * mass * g * np.ones_like(speed_ms)
    f_grade_1 = mass * g * 0.01 * np.ones_like(speed_ms)
    f_grade_2 = mass * g * 0.02 * np.ones_like(speed_ms)

    p_air = f_air * speed_ms
    p_roll = f_roll * speed_ms
    p_total_flat = (f_air + f_roll) * speed_ms
    p_total_grade_1 = (f_air + f_roll + f_grade_1) * speed_ms
    p_total_grade_2 = (f_air + f_roll + f_grade_2) * speed_ms
    p_pack_flat = p_total_flat / drive_eta + p_aux

    fig, ax = plt.subplots(figsize=(8.4, 5.0))
    ax.plot(speed_kmh, p_air / 1000.0, linewidth=2.5, label="Aerodynamic power")
    ax.plot(speed_kmh, p_roll / 1000.0, linewidth=2.0, label="Rolling-loss power")
    ax.plot(speed_kmh, p_total_flat / 1000.0, linewidth=2.0, label="Wheel power at 0% grade")
    ax.plot(speed_kmh, p_total_grade_1 / 1000.0, linewidth=2.0, label="Wheel power at 1% grade")
    ax.plot(speed_kmh, p_total_grade_2 / 1000.0, linewidth=2.0, label="Wheel power at 2% grade")
    ax.plot(speed_kmh, p_pack_flat / 1000.0, linewidth=2.2, linestyle="--", label="Pack power at 0% grade")
    ax.set_xlabel("Vehicle speed [km/h]")
    ax.set_ylabel("Power [kW]")
    ax.set_title("Speed hurts because aerodynamic power grows approximately with $v^3$")
    ax.legend(loc="upper left", fontsize=8)
    save_figure(fig, "vehicle_power_components.png")


def _read_map(csv_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    frame = pd.read_csv(csv_path, index_col=0)
    x = frame.columns.astype(float).to_numpy()
    y = frame.index.astype(float).to_numpy()
    z = frame.to_numpy(dtype=float)
    return x, y, z


def plot_drive_efficiency_maps() -> None:
    drive_path = REPO_ROOT / "maps" / "drive_eff_map_eco.csv"
    regen_path = REPO_ROOT / "maps" / "regen_eff_map_eco.csv"
    torque_drive, speed_drive, eta_drive = _read_map(drive_path)
    torque_regen, speed_regen, eta_regen = _read_map(regen_path)

    fig, axes = plt.subplots(1, 2, figsize=(11.2, 4.8), constrained_layout=True)
    pcm0 = axes[0].pcolormesh(torque_drive, speed_drive, eta_drive, shading="auto", cmap="viridis", vmin=0.7, vmax=1.0)
    axes[0].set_title("Drive efficiency map (eco)")
    axes[0].set_xlabel("Torque [Nm]")
    axes[0].set_ylabel("Speed [m/s]")
    fig.colorbar(pcm0, ax=axes[0], label="Efficiency [-]")

    pcm1 = axes[1].pcolormesh(torque_regen, speed_regen, eta_regen, shading="auto", cmap="magma", vmin=0.5, vmax=1.0)
    axes[1].set_title("Regen efficiency map (eco)")
    axes[1].set_xlabel("Torque [Nm]")
    axes[1].set_ylabel("Speed [m/s]")
    fig.colorbar(pcm1, ax=axes[1], label="Efficiency [-]")
    fig.suptitle("Current repository maps used by the strategy model", fontsize=13)
    save_figure(fig, "drive_and_regen_efficiency_maps.png")


def plot_rint_map() -> None:
    rint_path = REPO_ROOT / "maps" / "Rint_T_by_soc.csv"
    soc, temp, rint = _read_map(rint_path)

    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    pcm = ax.pcolormesh(soc, temp, rint * 1000.0, shading="auto", cmap="plasma")
    fig.colorbar(pcm, ax=ax, label="Internal resistance [mΩ]")
    ax.set_xlabel("SOC [-]")
    ax.set_ylabel("Cell temperature [°C]")
    ax.set_title("Internal resistance map used by the current pack model")
    save_figure(fig, "battery_rint_map.png")


def draw_box(ax, xy, width, height, text, fc, ec="#1f1f1f") -> None:
    box = FancyBboxPatch(
        xy,
        width,
        height,
        boxstyle="round,pad=0.02,rounding_size=0.02",
        linewidth=1.3,
        facecolor=fc,
        edgecolor=ec,
    )
    ax.add_patch(box)
    ax.text(
        xy[0] + width / 2.0,
        xy[1] + height / 2.0,
        text,
        ha="center",
        va="center",
        fontsize=11,
        wrap=True,
    )


def draw_arrow(ax, start, end) -> None:
    arrow = FancyArrowPatch(start, end, arrowstyle="-|>", mutation_scale=14, linewidth=1.4, color="#2c3e50")
    ax.add_patch(arrow)


def plot_system_architecture() -> None:
    fig, ax = plt.subplots(figsize=(11.5, 6.4))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    draw_box(ax, (0.05, 0.68), 0.16, 0.14, "太陽電池アレイ", "#fef3c7")
    draw_box(ax, (0.27, 0.68), 0.16, 0.14, "MPPT", "#fde68a")
    draw_box(ax, (0.49, 0.64), 0.18, 0.18, "高電圧バッテリーパック\nBMS / ヒューズ / 接触器", "#fecaca")
    draw_box(ax, (0.73, 0.68), 0.16, 0.14, "インバータ", "#dbeafe")
    draw_box(ax, (0.73, 0.44), 0.16, 0.14, "モーター", "#bfdbfe")
    draw_box(ax, (0.49, 0.26), 0.18, 0.14, "DC-DC / 12V-5V-3.3V", "#dcfce7")
    draw_box(ax, (0.27, 0.22), 0.16, 0.14, "ECU / マイコン\nsafe state 制御", "#bbf7d0")
    draw_box(ax, (0.05, 0.22), 0.16, 0.14, "センサ群\nV/I/T/GPS/風/日射", "#cffafe")
    draw_box(ax, (0.73, 0.20), 0.16, 0.18, "ドライバ表示\nロガー\nテレメトリ", "#e9d5ff")

    draw_arrow(ax, (0.21, 0.75), (0.27, 0.75))
    draw_arrow(ax, (0.43, 0.75), (0.49, 0.75))
    draw_arrow(ax, (0.67, 0.75), (0.73, 0.75))
    draw_arrow(ax, (0.81, 0.68), (0.81, 0.58))
    draw_arrow(ax, (0.73, 0.51), (0.67, 0.51))
    draw_arrow(ax, (0.49, 0.51), (0.43, 0.51))
    draw_arrow(ax, (0.36, 0.36), (0.36, 0.40))
    draw_arrow(ax, (0.21, 0.29), (0.27, 0.29))
    draw_arrow(ax, (0.43, 0.29), (0.49, 0.29))
    draw_arrow(ax, (0.67, 0.33), (0.73, 0.33))
    draw_arrow(ax, (0.21, 0.26), (0.73, 0.26))

    ax.text(0.50, 0.92, "BWSC2027 Challenger の推奨アーキテクチャ", ha="center", va="center", fontsize=15, weight="bold")
    ax.text(
        0.50,
        0.08,
        "高電圧系・低電圧系・計測系・安全系・戦略系は分離して設計し、safe state で必ず物理遮断する。",
        ha="center",
        va="center",
        fontsize=10,
    )
    save_figure(fig, "system_architecture.png")


def plot_validation_flow() -> None:
    fig, ax = plt.subplots(figsize=(11.5, 3.2))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    stages = [
        (0.02, "要求仕様\n公式規則・目標KPI"),
        (0.19, "ベンチ試験\nセル・MPPT・DC-DC"),
        (0.36, "シャシダイ\n無負荷損失・効率同定"),
        (0.53, "実路試験\ncoastdown・GPS・風"),
        (0.70, "モデル更新\nmaps / route / SOC"),
        (0.87, "本番運用\nMPC・dashboard"),
    ]

    for x0, label in stages:
        draw_box(ax, (x0, 0.32), 0.11, 0.34, label, "#f3f4f6")

    for idx in range(len(stages) - 1):
        x_start = stages[idx][0] + 0.11
        x_end = stages[idx + 1][0]
        draw_arrow(ax, (x_start, 0.49), (x_end, 0.49))

    draw_arrow(ax, (0.925, 0.28), (0.075, 0.28))
    ax.text(0.50, 0.17, "ログを同定へ戻し、次の試験条件と速度計画へ反映する", ha="center", va="center", fontsize=10)
    ax.text(0.50, 0.83, "最高峰車体は、設計よりも「検証ループの速さ」で育つ", ha="center", va="center", fontsize=15, weight="bold")
    save_figure(fig, "validation_flow.png")


def main() -> None:
    configure_matplotlib()
    ensure_output_dir()
    profile = load_profile()
    plot_shock_current_chart()
    plot_battery_voltage_concept()
    plot_vehicle_power_components(profile)
    plot_drive_efficiency_maps()
    plot_rint_map()
    plot_system_architecture()
    plot_validation_flow()


if __name__ == "__main__":
    main()
