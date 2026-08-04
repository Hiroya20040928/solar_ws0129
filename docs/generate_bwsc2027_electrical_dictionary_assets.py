# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


DOCS_DIR = Path(__file__).resolve().parent
REPO_ROOT = DOCS_DIR.parent
ASSET_DIR = DOCS_DIR / "assets" / "bwsc2027_electrical_dictionary"
IDENT_DIR = REPO_ROOT / "outputs" / "identification"


def configure_matplotlib() -> None:
    plt.rcParams["figure.dpi"] = 160
    plt.rcParams["savefig.dpi"] = 220
    plt.rcParams["font.size"] = 10
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.alpha"] = 0.22
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Yu Gothic", "Meiryo", "MS Gothic", "DejaVu Sans"]


def ensure_output_dir() -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)


def save_figure(fig: plt.Figure, name: str) -> None:
    fig.savefig(ASSET_DIR / name, bbox_inches="tight")
    plt.close(fig)


def plot_battery_ocv_soc() -> None:
    path = IDENT_DIR / "ocv_soc_curve_identified.csv"
    df = pd.read_csv(path)

    fig, ax = plt.subplots(figsize=(7.0, 4.2), constrained_layout=True)
    ax.plot(df["soc"] * 100.0, df["ocv_v"], color="black", linewidth=1.8, marker="o", markersize=3.5)
    ax.set_xlabel("SOC [%]")
    ax.set_ylabel("開放電圧 [V]")
    ax.set_title("識別結果によるバッテリーパックの OCV-SOC 特性")
    save_figure(fig, "battery_ocv_soc_identified.png")


def plot_battery_rint() -> None:
    path = IDENT_DIR / "Rint_T_by_soc_identified.csv"
    df = pd.read_csv(path)

    soc_cols = [c for c in df.columns if c != "temp_bin"]
    fig, ax = plt.subplots(figsize=(7.0, 4.4), constrained_layout=True)
    for _, row in df.iterrows():
        soc = np.array([float(c) for c in soc_cols]) * 100.0
        rint = row[soc_cols].to_numpy(dtype=float)
        mask = np.isfinite(rint)
        if mask.sum() == 0:
            continue
        ax.plot(
            soc[mask],
            1_000.0 * rint[mask],
            linewidth=1.6,
            marker="o",
            markersize=3.5,
            label=f"{row['temp_bin']:.0f} °C",
        )
    ax.set_xlabel("SOC [%]")
    ax.set_ylabel("内部抵抗 [mΩ]")
    ax.set_title("識別結果によるパック内部抵抗")
    ax.legend(title="温度 bin", fontsize=8, title_fontsize=8, loc="best")
    save_figure(fig, "battery_rint_identified.png")


def plot_panel_efficiency() -> None:
    path = IDENT_DIR / "panel_eff_map_identified.csv"
    df = pd.read_csv(path)

    fig, ax = plt.subplots(figsize=(7.0, 4.3), constrained_layout=True)
    temp_cols = [c for c in df.columns if c != "G_poa"]
    for col in temp_cols:
        ax.plot(
            df["G_poa"],
            df[col],
            linewidth=1.6,
            marker="o",
            markersize=3.2,
            label=f"{col} °C",
        )
    ax.set_xlabel("POA 日射 [W/m²]")
    ax.set_ylabel("パネル効率 [-]")
    ax.set_title("識別結果によるパネル効率")
    ax.legend(title="温度", fontsize=8, title_fontsize=8, loc="best")
    save_figure(fig, "panel_efficiency_identified.png")


def plot_mppt_efficiency() -> None:
    path = IDENT_DIR / "mppt_eff_map_identified.csv"
    df = pd.read_csv(path)

    fig, ax = plt.subplots(figsize=(7.0, 4.3), constrained_layout=True)
    temp_cols = [c for c in df.columns if c != "G_poa"]
    for col in temp_cols:
        ax.plot(
            df["G_poa"],
            df[col],
            linewidth=1.6,
            marker="o",
            markersize=3.2,
            label=f"{col} °C",
        )
    ax.set_xlabel("POA 日射 [W/m²]")
    ax.set_ylabel("MPPT 効率 [-]")
    ax.set_ylim(0.94, 0.98)
    ax.set_title("識別結果による MPPT 効率")
    ax.legend(title="温度", fontsize=8, title_fontsize=8, loc="best")
    save_figure(fig, "mppt_efficiency_identified.png")


def main() -> None:
    configure_matplotlib()
    ensure_output_dir()
    plot_battery_ocv_soc()
    plot_battery_rint()
    plot_panel_efficiency()
    plot_mppt_efficiency()


if __name__ == "__main__":
    main()
