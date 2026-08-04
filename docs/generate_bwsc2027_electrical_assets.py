# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


DOCS_DIR = Path(__file__).resolve().parent
ASSET_DIR = DOCS_DIR / "assets" / "bwsc2027_electrical_guide"


def configure_matplotlib() -> None:
    plt.rcParams["figure.dpi"] = 160
    plt.rcParams["savefig.dpi"] = 220
    plt.rcParams["font.size"] = 11
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.24
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Yu Gothic", "Meiryo", "MS Gothic", "DejaVu Sans"]


def ensure_output_dir() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)


def save_figure(fig: plt.Figure, name: str) -> None:
    try:
        fig.tight_layout()
    except RuntimeError:
        pass
    fig.savefig(ASSET_DIR / name, bbox_inches="tight")
    plt.close(fig)


def plot_shock_current_chart() -> None:
    voltage = np.linspace(0.0, 120.0, 500)
    resistances = [
        (500.0, "500 Ω: かなり危険な濡れ条件"),
        (2_000.0, "2 kΩ: 汗・濡れ手に近い条件"),
        (10_000.0, "10 kΩ: 乾いた皮膚に近い条件"),
    ]

    fig, ax = plt.subplots(figsize=(8.6, 5.0))
    ax.axhspan(0, 1, color="#d9f0d3", alpha=0.60, label="知覚しにくい領域")
    ax.axhspan(1, 10, color="#fee08b", alpha=0.50, label="知覚・痛みの領域")
    ax.axhspan(10, 30, color="#fdae61", alpha=0.38, label="離脱困難になりうる領域")
    ax.axhspan(30, 150, color="#d73027", alpha=0.18, label="致命的になりうる領域")

    for resistance, label in resistances:
        ax.plot(voltage, 1_000.0 * voltage / resistance, linewidth=2.2, label=label)

    ax.set_xlim(0, 120)
    ax.set_ylim(0, 150)
    ax.set_xlabel("印加電圧 [V]")
    ax.set_ylabel("人体電流 [mA]")
    ax.set_title("人体抵抗が下がると同じ電圧でも流れる電流が急増する")
    ax.legend(loc="upper left", fontsize=9)
    save_figure(fig, "shock_current_vs_voltage.png")


def plot_battery_ocv_concept() -> None:
    soc = np.linspace(0, 1, 500)
    ocv = 3.05 + 0.85 * soc + 0.25 * np.tanh((soc - 0.55) * 5.0)
    rint = 0.020 + 0.014 * (1 - soc) ** 1.4 + 0.006 * np.exp(-((soc - 0.08) / 0.08) ** 2)
    discharge_current = 35.0
    charge_current = -15.0
    v_discharge = ocv - discharge_current * rint
    v_charge = ocv - charge_current * rint

    fig, axes = plt.subplots(1, 2, figsize=(10.2, 4.6))

    axes[0].plot(soc * 100, ocv, linewidth=2.4, label="OCV")
    axes[0].plot(soc * 100, v_discharge, linewidth=2.0, label="放電中端子電圧")
    axes[0].plot(soc * 100, v_charge, linewidth=2.0, label="充電中端子電圧")
    axes[0].set_xlabel("SOC [%]")
    axes[0].set_ylabel("セル電圧 [V]")
    axes[0].set_title("OCV と使用中の端子電圧")
    axes[0].legend(fontsize=9)

    axes[1].plot(soc * 100, 1_000.0 * rint, color="#8c510a", linewidth=2.4)
    axes[1].set_xlabel("SOC [%]")
    axes[1].set_ylabel("内部抵抗 [mΩ / cell]")
    axes[1].set_title("内部抵抗は SOC で変わる")

    save_figure(fig, "battery_ocv_terminal_concept.png")


def plot_solar_iv_pv_curve() -> None:
    voc = 110.0
    mpp_v = 86.0
    irradiances = [
        (400.0, "#1b9e77"),
        (800.0, "#d95f02"),
        (1_000.0, "#7570b3"),
    ]

    fig, axes = plt.subplots(1, 2, figsize=(10.6, 4.6))
    voltage = np.linspace(0, voc, 500)

    for irradiance, color in irradiances:
        isc = 5.7 * irradiance / 1_000.0
        current = isc * np.maximum(0.0, 1.0 - (voltage / voc) ** 4.0)
        power = voltage * current
        idx = int(np.argmax(power))
        axes[0].plot(voltage, current, color=color, linewidth=2.2, label=f"{irradiance:.0f} W/m²")
        axes[0].scatter([voltage[idx]], [current[idx]], color=color, s=24)
        axes[1].plot(voltage, power, color=color, linewidth=2.2, label=f"{irradiance:.0f} W/m²")
        axes[1].scatter([voltage[idx]], [power[idx]], color=color, s=24)

    axes[0].axvline(mpp_v, color="#666666", linestyle="--", linewidth=1.2)
    axes[1].axvline(mpp_v, color="#666666", linestyle="--", linewidth=1.2)
    axes[0].set_xlabel("PV 電圧 [V]")
    axes[0].set_ylabel("PV 電流 [A]")
    axes[0].set_title("太陽電池 I-V 特性")
    axes[0].legend(fontsize=9)
    axes[1].set_xlabel("PV 電圧 [V]")
    axes[1].set_ylabel("PV 電力 [W]")
    axes[1].set_title("太陽電池 P-V 特性と最大電力点")

    save_figure(fig, "solar_iv_pv_curve.png")


def plot_cc_cv_charge_profile() -> None:
    time_min = np.linspace(0, 180, 600)
    current = np.where(time_min <= 105, 16.0, 16.0 * np.exp(-(time_min - 105) / 28.0))
    voltage = np.where(time_min <= 105, 88.0 + 0.20 * time_min, 109.0 - 0.5 * np.exp(-(time_min - 105) / 10.0))
    voltage = np.minimum(voltage, 109.0)

    fig, ax1 = plt.subplots(figsize=(9.2, 4.8))
    ax2 = ax1.twinx()

    ax1.plot(time_min, current, color="#1f78b4", linewidth=2.4, label="充電電流")
    ax2.plot(time_min, voltage, color="#e31a1c", linewidth=2.4, label="パック電圧")
    ax1.axvline(105, color="#666666", linestyle="--", linewidth=1.2)
    ax1.text(32, 17.1, "CC 領域", fontsize=11)
    ax1.text(124, 17.1, "CV 領域", fontsize=11)
    ax1.set_xlabel("充電時間 [min]")
    ax1.set_ylabel("充電電流 [A]", color="#1f78b4")
    ax2.set_ylabel("パック電圧 [V]", color="#e31a1c")
    ax1.set_title("Li 系パックの典型的な CC-CV 充電")

    save_figure(fig, "cc_cv_charge_profile.png")


def plot_motor_torque_speed_power() -> None:
    rpm = np.linspace(0, 2_400, 500)
    base_rpm = 850.0
    max_torque = 36.0
    torque = np.where(rpm <= base_rpm, max_torque, max_torque * base_rpm / np.maximum(rpm, 1.0))
    omega = rpm * 2.0 * np.pi / 60.0
    mech_power = torque * omega

    fig, ax1 = plt.subplots(figsize=(9.2, 4.8))
    ax2 = ax1.twinx()

    ax1.plot(rpm, torque, color="#1b9e77", linewidth=2.4, label="トルク")
    ax2.plot(rpm, mech_power / 1_000.0, color="#d95f02", linewidth=2.4, label="機械出力")
    ax1.axvline(base_rpm, color="#666666", linestyle="--", linewidth=1.2)
    ax1.text(200, 38.5, "定トルク域", fontsize=10)
    ax1.text(1_050, 38.5, "定出力に近い領域", fontsize=10)
    ax1.set_xlabel("回転数 [rpm]")
    ax1.set_ylabel("トルク [N m]", color="#1b9e77")
    ax2.set_ylabel("機械出力 [kW]", color="#d95f02")
    ax1.set_title("モーターのトルク・回転数・機械出力の関係")

    save_figure(fig, "motor_torque_speed_power.png")


def plot_power_breakdown_vs_speed() -> None:
    rho = 1.18
    cda = 0.092
    crr = 0.0048
    mass = 245.0
    g = 9.81
    aux = 80.0
    speed_kmh = np.linspace(30.0, 120.0, 400)
    speed = speed_kmh / 3.6

    aero = 0.5 * rho * cda * speed**3
    rolling = crr * mass * g * speed
    total = aero + rolling + aux

    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    ax.plot(speed_kmh, aero, linewidth=2.4, label="空力損失")
    ax.plot(speed_kmh, rolling, linewidth=2.4, label="転がり損失")
    ax.plot(speed_kmh, np.full_like(speed_kmh, aux), linewidth=2.0, label="補機電力")
    ax.plot(speed_kmh, total, linewidth=2.8, color="#111111", label="総必要電力")
    ax.set_xlabel("車速 [km/h]")
    ax.set_ylabel("必要電力 [W]")
    ax.set_title("空力は車速の三乗で増え、電装設計の要求電力を押し上げる")
    ax.legend(fontsize=9)

    save_figure(fig, "power_breakdown_vs_speed.png")


def plot_bus_voltage_vs_copper_loss() -> None:
    power = 1_600.0
    loop_resistance = 0.025
    voltage = np.linspace(48.0, 140.0, 300)
    current = power / voltage
    copper_loss = current**2 * loop_resistance

    fig, ax1 = plt.subplots(figsize=(9.0, 4.8))
    ax2 = ax1.twinx()

    ax1.plot(voltage, current, color="#377eb8", linewidth=2.4, label="必要電流")
    ax2.plot(voltage, copper_loss, color="#e41a1c", linewidth=2.4, label="配線損失")
    ax1.set_xlabel("DC バス電圧 [V]")
    ax1.set_ylabel("電流 [A]", color="#377eb8")
    ax2.set_ylabel("配線損失 [W]", color="#e41a1c")
    ax1.set_title("同じ電力なら高電圧化で電流と銅損を下げられる")

    save_figure(fig, "bus_voltage_vs_copper_loss.png")


def draw_box(ax, xy: tuple[float, float], text: str, width: float = 1.9, height: float = 0.8, face: str = "#eef6ff") -> None:
    x, y = xy
    box = FancyBboxPatch(
        (x, y),
        width,
        height,
        boxstyle="round,pad=0.04,rounding_size=0.08",
        linewidth=1.2,
        edgecolor="#336699",
        facecolor=face,
    )
    ax.add_patch(box)
    ax.text(x + width / 2, y + height / 2, text, ha="center", va="center", fontsize=10)


def draw_arrow(ax, start: tuple[float, float], end: tuple[float, float], text: str | None = None, color: str = "#444444") -> None:
    arrow = FancyArrowPatch(start, end, arrowstyle="->", mutation_scale=12, linewidth=1.4, color=color)
    ax.add_patch(arrow)
    if text:
        mx = (start[0] + end[0]) / 2
        my = (start[1] + end[1]) / 2
        ax.text(mx, my + 0.12, text, ha="center", va="bottom", fontsize=9, color=color)


def plot_electrical_architecture() -> None:
    fig, ax = plt.subplots(figsize=(11.8, 6.5))
    ax.set_xlim(0, 12.4)
    ax.set_ylim(0, 7.0)
    ax.axis("off")

    draw_box(ax, (0.5, 5.4), "太陽電池アレイ", face="#fff4cc")
    draw_box(ax, (3.1, 5.4), "MPPT", face="#fff4cc")
    draw_box(ax, (5.7, 5.4), "HV バス\n(接触器・ヒューズ・IMD)", width=2.2, face="#ffe5e5")
    draw_box(ax, (8.6, 5.4), "インバータ", face="#ffe5e5")
    draw_box(ax, (10.8, 5.4), "モーター", face="#ffe5e5")

    draw_box(ax, (5.7, 3.6), "バッテリーパック\n+BMS", width=2.2, face="#e7f6e7")
    draw_box(ax, (3.1, 3.6), "プリチャージ", face="#e7f0ff")
    draw_box(ax, (8.6, 3.6), "DC-DC", face="#e7f0ff")
    draw_box(ax, (10.8, 3.6), "低電圧バス\n12 V / 24 V", face="#e7f0ff")

    draw_box(ax, (0.5, 1.5), "ECU / VCU", face="#f5edff")
    draw_box(ax, (3.1, 1.5), "BMS Master\n安全状態判定", face="#f5edff")
    draw_box(ax, (5.7, 1.5), "絶縁・漏電・温度\n監視", width=2.2, face="#f5edff")
    draw_box(ax, (8.6, 1.5), "通信 / ロガー\nCAN / Telemetry", face="#f5edff")
    draw_box(ax, (10.8, 1.5), "灯火 / 計器 /\nカメラ / 無線", face="#f5edff")

    draw_arrow(ax, (2.4, 5.8), (3.1, 5.8), "発電")
    draw_arrow(ax, (5.0, 5.8), (5.7, 5.8), "充電")
    draw_arrow(ax, (7.9, 5.8), (8.6, 5.8), "駆動電力")
    draw_arrow(ax, (10.5, 5.8), (10.8, 5.8), "相電力")
    draw_arrow(ax, (6.8, 4.4), (6.8, 5.4), "放電 / 回生")
    draw_arrow(ax, (5.0, 4.0), (5.7, 4.0), "突入抑制")
    draw_arrow(ax, (7.9, 4.0), (8.6, 4.0), "HV→LV")
    draw_arrow(ax, (10.5, 4.0), (10.8, 4.0), "補機給電")

    draw_arrow(ax, (1.5, 2.3), (3.1, 2.3), "制御")
    draw_arrow(ax, (4.7, 2.3), (5.7, 2.3), "監視")
    draw_arrow(ax, (7.9, 2.3), (8.6, 2.3), "ログ")
    draw_arrow(ax, (10.5, 2.3), (10.8, 2.3), "表示")
    draw_arrow(ax, (2.4, 1.9), (5.7, 5.2), "safe state 指令", color="#aa0000")
    draw_arrow(ax, (4.9, 1.9), (8.6, 5.2), "インターロック", color="#aa0000")

    ax.set_title("BWSC2027 Challenger 向け電装アーキテクチャの基本形", fontsize=14, pad=12)
    save_figure(fig, "electrical_architecture_bwsc2027.png")


def plot_learning_map() -> None:
    fig, ax = plt.subplots(figsize=(10.6, 5.4))
    ax.set_xlim(0, 10.4)
    ax.set_ylim(0, 5.4)
    ax.axis("off")

    stages = [
        ((0.3, 2.2), "電荷・電圧・電流\n回路の成立"),
        ((2.3, 2.2), "電力・熱・配線\n安全"),
        ((4.3, 2.2), "電池化学・BMS\nCC-CV"),
        ((6.3, 2.2), "半導体・DC-DC\nインバータ"),
        ((8.3, 2.2), "実測・同定・\nレース運用"),
    ]

    for xy, text in stages:
        draw_box(ax, xy, text, width=1.6, height=1.0, face="#f4f8fb")

    for idx in range(len(stages) - 1):
        start = (stages[idx][0][0] + 1.6, stages[idx][0][1] + 0.5)
        end = (stages[idx + 1][0][0], stages[idx + 1][0][1] + 0.5)
        draw_arrow(ax, start, end)

    ax.text(5.2, 4.45, "単語を覚えるだけではなく、各段階が次の設計判断へつながるように学ぶ", ha="center", fontsize=12)
    ax.set_title("物理化学未履修者から最高峰電装設計へ進む学習導線", fontsize=14, pad=12)
    save_figure(fig, "learning_map.png")


def main() -> None:
    configure_matplotlib()
    ensure_output_dir()
    plot_shock_current_chart()
    plot_battery_ocv_concept()
    plot_solar_iv_pv_curve()
    plot_cc_cv_charge_profile()
    plot_motor_torque_speed_power()
    plot_power_breakdown_vs_speed()
    plot_bus_voltage_vs_copper_loss()
    plot_electrical_architecture()
    plot_learning_map()


if __name__ == "__main__":
    main()
