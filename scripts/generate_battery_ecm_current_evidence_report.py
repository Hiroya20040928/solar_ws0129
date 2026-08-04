#!/usr/bin/env python3
"""Visual audit of legacy battery artifacts against the physical ECM gate."""

from __future__ import annotations

import argparse
import base64
import hashlib
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


ROOT = Path(__file__).resolve().parents[1]


def png(fig: plt.Figure) -> str:
    stream = io.BytesIO()
    fig.savefig(stream, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode("ascii")


def message_figure(title: str, lines: list[str], *, color: str = "#7f1d1d") -> plt.Figure:
    fig, ax = plt.subplots(figsize=(9.4, 4.8))
    ax.axis("off")
    ax.text(0.5, 0.82, title, ha="center", fontsize=17, weight="bold", color=color)
    ax.text(0.5, 0.42, "\n".join(lines), ha="center", va="center", fontsize=11, wrap=True)
    return fig


def read_map(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, index_col=0)
    frame.index = pd.to_numeric(frame.index, errors="coerce")
    frame.columns = pd.to_numeric(frame.columns, errors="coerce")
    return frame.sort_index().sort_index(axis=1)


def add_figure(items: list[tuple[str, str]], title: str, fig: plt.Figure) -> None:
    items.append((title, png(fig)))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(replay_csv: Path, ocv_csv: Path, rint_csv: Path, fit_summary_yaml: Path, output_html: Path) -> dict:
    replay = pd.read_csv(replay_csv, low_memory=False)
    ocv = pd.read_csv(ocv_csv)
    rint = read_map(rint_csv)
    fit_summary = yaml.safe_load(fit_summary_yaml.read_text(encoding="utf-8")) or {}
    dynamic = dict(fit_summary.get("battery_dynamic_fit", {}) or {})
    battery = dict(fit_summary.get("battery_fit", {}) or {})
    validation = dict(fit_summary.get("validation_metrics", {}) or {})
    builder_source = (ROOT / "scripts" / "build_bwsc2025_fitted_package.py").read_text(encoding="utf-8")
    model_source = (ROOT / "mpc_solarcar" / "model.py").read_text(encoding="utf-8")
    fitter_source = (ROOT / "scripts" / "fit_battery_ecm_from_pulses.py").read_text(encoding="utf-8")
    execution_source = (ROOT / "scripts" / "solar_sim.py").read_text(encoding="utf-8")
    fixed_prior_removed = bool(
        "BATTERY_CELL_DC_RESISTANCE_OHM_REF" not in builder_source
        and "0.040 *" not in builder_source
    )
    passive_1rc_implemented = bool(
        "def battery_iv(self, P_pack, z, Tbat_C, polarization_v=None)" in model_source
        and "polarization_drop_v" in model_source
        and "dV1/dt = -V1/tau" in fitter_source
        and "alpha_polarization * exec_polarization_v" in execution_source
    )
    for column in (
        "s_km", "day", "soc_pred", "Tamb_C", "battery_current_a_obs",
        "battery_voltage_v_obs", "battery_voltage_v_pred", "battery_voltage_v_pred_static",
        "battery_polarization_v",
    ):
        if column in replay:
            replay[column] = pd.to_numeric(replay[column], errors="coerce")
    replay["voltage_residual_v"] = replay["battery_voltage_v_obs"] - replay["battery_voltage_v_pred"]
    figures: list[tuple[str, str]] = []

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.axis("off")
    ax.text(0.5, 0.91, "Legacy path versus identifiable path", ha="center", fontsize=17, weight="bold")
    ax.text(0.25, 0.70, "legacy", ha="center", weight="bold", color="#b91c1c")
    ax.text(0.25, 0.48, "loaded V curve\n+ fixed 40 mOhm/cell\n+ road-log map warp", ha="center", va="center", bbox={"boxstyle": "round", "fc": "#fee2e2"})
    ax.text(0.75, 0.70, "required", ha="center", weight="bold", color="#166534")
    ax.text(0.75, 0.48, "independent SoC + long rest\n+ sub-second pulse\n+ untouched holdout", ha="center", va="center", bbox={"boxstyle": "round", "fc": "#dcfce7"})
    ax.annotate("not equivalent", xy=(0.57, 0.48), xytext=(0.43, 0.48), ha="center", arrowprops={"arrowstyle": "<->"})
    add_figure(figures, "1. Evidence path", fig)

    step = max(1, len(replay) // 2500)
    sample = replay.iloc[::step]
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(sample["s_km"], sample["battery_current_a_obs"], linewidth=0.7)
    axes[0].set_ylabel("current [A]"); axes[0].grid(True, alpha=0.25)
    axes[1].plot(sample["s_km"], sample["battery_voltage_v_obs"], label="observed", linewidth=0.7)
    axes[1].plot(sample["s_km"], sample["battery_voltage_v_pred"], label="MLE35", linewidth=0.7)
    axes[1].set(xlabel="distance [km]", ylabel="voltage [V]"); axes[1].grid(True, alpha=0.25); axes[1].legend()
    add_figure(figures, "2. BWSC2025 road-log channels", fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(ocv["soc"], ocv["ocv_v"], linewidth=2)
    ax.set(xlabel="model SoC [-]", ylabel="pack voltage [V]", title="Current adopted pseudo-OCV artifact")
    ax.grid(True, alpha=0.25)
    add_figure(figures, "3. Existing OCV artifact", fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    image = ax.imshow(rint.to_numpy(), origin="lower", aspect="auto", extent=[rint.columns.min(), rint.columns.max(), rint.index.min(), rint.index.max()])
    ax.set(
        xlabel="legacy model SoC [-]",
        ylabel="temperature [C]",
        title="REJECTED LEGACY MLE35 Rint artifact - diagnostic only",
    )
    ax.text(
        0.5,
        0.5,
        "REJECTED\nNOT A PULSE-IDENTIFIED MAP",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=24,
        weight="bold",
        color="#7f1d1d",
        alpha=0.72,
        bbox={"boxstyle": "round", "fc": "white", "ec": "#b91c1c", "alpha": 0.78},
    )
    fig.colorbar(image, ax=ax, label="ohm")
    add_figure(figures, "4. Rejected legacy Rint surface", fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    for target in (0.0, 10.0, 25.0, 40.0):
        idx = int(np.argmin(np.abs(rint.index.to_numpy(dtype=float) - target)))
        ax.plot(
            rint.columns,
            rint.iloc[idx],
            linestyle="--",
            alpha=0.62,
            label=f"legacy {float(rint.index[idx]):.0f} C",
        )
    ax.set(
        xlabel="legacy model SoC [-]",
        ylabel="Rint [ohm]",
        title="REJECTED LEGACY SLICES - high-SoC spike has no independent pulse evidence",
    )
    ax.text(
        0.5,
        0.5,
        "DO NOT USE\nNo pulse-certified replacement exists yet",
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=21,
        weight="bold",
        color="#991b1b",
        alpha=0.82,
        bbox={"boxstyle": "round", "fc": "#fff7ed", "ec": "#b91c1c", "alpha": 0.88},
    )
    ax.grid(True, alpha=0.25); ax.legend()
    add_figure(figures, "5. Rejected legacy map slices", fig)

    current = replay["battery_current_a_obs"].to_numpy(dtype=float)
    voltage = replay["battery_voltage_v_obs"].to_numpy(dtype=float)
    delta_i = np.diff(current, prepend=np.nan)
    delta_v = np.diff(voltage, prepend=np.nan)
    apparent = np.divide(
        -delta_v,
        delta_i,
        out=np.full_like(delta_v, np.nan, dtype=float),
        where=np.abs(delta_i) > 1.0e-12,
    )
    valid_step = np.isfinite(apparent) & (np.abs(delta_i) >= 1.0) & (np.abs(delta_i) <= 15.0) & (apparent > 0.05) & (apparent < 0.5)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(apparent[valid_step], bins=50, color="#1d4ed8", alpha=0.8)
    ax.set(xlabel="-deltaV/deltaI [ohm]", ylabel="count", title="5 s road-step apparent resistance")
    add_figure(figures, "6. Apparent road-step resistance", fig)

    for number, x_column, xlabel in ((7, "soc_pred", "fitted SoC [-]"), (8, "Tamb_C", "ambient temperature [C]")):
        fig, ax = plt.subplots(figsize=(9, 5))
        ax.scatter(replay.loc[valid_step, x_column], apparent[valid_step], s=5, alpha=0.25)
        ax.set(xlabel=xlabel, ylabel="apparent resistance [ohm]", title="Confounded road-step diagnostic")
        ax.grid(True, alpha=0.25)
        add_figure(figures, f"{number}. Apparent resistance diagnostic", fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(sample["s_km"], sample["battery_polarization_v"], linewidth=0.8)
    ax.set(xlabel="distance [km]", ylabel="fitted polarization [V]", title="Road-log 1-RC correction")
    ax.grid(True, alpha=0.25)
    add_figure(figures, "9. Fitted road-log polarization", fig)

    clean = replay[np.isfinite(replay["voltage_residual_v"])].copy()
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(clean["voltage_residual_v"], bins=80, color="#b45309")
    ax.set(xlabel="observed - predicted [V]", ylabel="count", title="Conditioned voltage residual")
    add_figure(figures, "10. Voltage residual distribution", fig)

    for number, x_column, xlabel in ((11, "soc_pred", "fitted SoC [-]"), (12, "battery_current_a_obs", "current [A]")):
        fig, ax = plt.subplots(figsize=(9, 5))
        reduced = clean.iloc[::max(1, len(clean) // 5000)]
        ax.scatter(reduced[x_column], reduced["voltage_residual_v"], s=4, alpha=0.2)
        ax.axhline(0.0, color="black", linewidth=1)
        ax.set(xlabel=xlabel, ylabel="voltage residual [V]", title="Residual structure")
        ax.grid(True, alpha=0.25)
        add_figure(figures, f"{number}. Voltage residual structure", fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    heat = ax.hist2d(clean["soc_pred"], clean["battery_current_a_obs"], bins=(20, 20), weights=np.abs(clean["voltage_residual_v"]), cmap="magma")
    ax.set(xlabel="fitted SoC [-]", ylabel="current [A]", title="Absolute residual mass by SoC/current")
    fig.colorbar(heat[3], ax=ax)
    add_figure(figures, "13. SoC-current residual interaction", fig)

    day_metrics = clean.groupby("day")["voltage_residual_v"].apply(lambda x: float(np.sqrt(np.mean(x**2))))
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(day_metrics.index.astype(str), day_metrics.values)
    ax.set(xlabel="race day", ylabel="voltage RMSE [V]", title="Day-wise conditioned voltage RMSE")
    add_figure(figures, "14. Day holdout non-stationarity", fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    labels = ["train before", "train after", "day6 before", "day6 after"]
    values = [dynamic.get("rmse_before_v", math.nan), dynamic.get("rmse_after_v", math.nan), dynamic.get("validation_rmse_before_v", math.nan), dynamic.get("validation_rmse_after_v", math.nan)]
    ax.bar(labels, values, color=["#94a3b8", "#2563eb", "#fca5a5", "#b91c1c"])
    ax.set(ylabel="RMSE [V]", title="Road-log 1-RC training/holdout result")
    add_figure(figures, "15. Conditional 1-RC holdout", fig)

    terminal = replay[replay["s_km"] >= float(replay["s_km"].max()) - 3.0].dropna(subset=["battery_current_a_obs", "battery_voltage_v_obs"]).copy()
    t = np.arange(len(terminal), dtype=float) * 5.0
    design = np.column_stack([np.ones(len(terminal)), t - t[-1], -terminal["battery_current_a_obs"].to_numpy(dtype=float)])
    beta, *_ = np.linalg.lstsq(design, terminal["battery_voltage_v_obs"].to_numpy(dtype=float), rcond=None)
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.scatter(terminal["battery_current_a_obs"], terminal["battery_voltage_v_obs"], s=18, alpha=0.7)
    grid_i = np.linspace(terminal["battery_current_a_obs"].min(), terminal["battery_current_a_obs"].max(), 100)
    ax.plot(grid_i, beta[0] - beta[2] * grid_i, color="#b91c1c", label=f"conditional Rseries={beta[2]:.4f} ohm")
    ax.set(xlabel="current [A]", ylabel="voltage [V]", title="Terminal 3 km V-I regression")
    ax.grid(True, alpha=0.25); ax.legend()
    add_figure(figures, "16. Conditional terminal V-I fit", fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hexbin(clean["soc_pred"], clean["Tamb_C"], gridsize=25, mincnt=1)
    ax.set(xlabel="fitted SoC [-]", ylabel="ambient temperature [C]", title="Road-log coverage is not independent lab coverage")
    add_figure(figures, "17. Road-log coverage", fig)

    checks = {
        "independent SoC reference": False,
        "long rested OCV grid": False,
        "sub-second pulse sampling": False,
        "multi-SoC pulse grid": False,
        "multi-temperature pulse grid": False,
        "independent pulse holdout": False,
        "passive 1-RC equation implemented": passive_1rc_implemented,
        "road-day residual holdout": bool(dynamic.get("adopted", False)),
    }
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(list(checks), [int(value) for value in checks.values()], color=["#15803d" if value else "#b91c1c" for value in checks.values()])
    ax.set_xlim(0, 1.05); ax.set_title("Current physical-evidence gate")
    add_figure(figures, "18. Physical-evidence checks", fig)

    add_figure(figures, "19. Correct model and proof boundary", message_figure(
        "Correct structural model",
        [
            "Vt = Uocv(z) - I R0,total(z,T) - V1",
            "dV1/dt = -V1/tau + R1 I/tau",
            "Road logs can condition this model, but cannot independently certify Uocv, R0, R1 and tau.",
        ],
        color="#1d4ed8",
    ))
    add_figure(figures, "20. Audit conclusion", message_figure(
        "NOT PHYSICALLY CERTIFIED",
        [
            "The fixed 0.040 ohm/cell premise has been removed from new builds.",
            "Existing MLE35 artifacts remain historical conditional results, not promoted physical maps.",
            "Acquire the specified rest/pulse matrix and run fit_battery_ecm_from_pulses.py.",
        ],
    ))

    summary = {
        "gate_pass": False,
        "checks": checks,
        "legacy_artifact": str(rint_csv),
        "legacy_map_adoption_status": "rejected_diagnostic_only",
        "legacy_high_soc_spike_supported_by_independent_pulses": False,
        "new_pulse_certified_map_available": False,
        "new_fitting_equation": (
            "R0_total=exp(beta0+beta_z*zeta+beta_T*theta+beta_zz*zeta^2+"
            "beta_zT*zeta*theta+beta_TT*theta^2), zeta=(SoC-0.5)/0.5, "
            "theta=(T_C-25)/25; evaluated only inside training support and held "
            "constant at the nearest boundary outside it"
        ),
        "new_fitting_shape_policy": (
            "R0 is positive and learned without a default SoC/temperature direction prior; "
            "both SoC edges require independent pulse holdout evidence before promotion, and "
            "optional directional constraints are diagnostic hypotheses rather than release defaults"
        ),
        "fixed_0p040_removed_from_new_builder": fixed_prior_removed,
        "implementation_audit": {
            "builder_source": str(ROOT / "scripts" / "build_bwsc2025_fitted_package.py"),
            "builder_source_sha256": sha256(ROOT / "scripts" / "build_bwsc2025_fitted_package.py"),
            "model_source": str(ROOT / "mpc_solarcar" / "model.py"),
            "model_source_sha256": sha256(ROOT / "mpc_solarcar" / "model.py"),
            "fitter_source": str(ROOT / "scripts" / "fit_battery_ecm_from_pulses.py"),
            "fitter_source_sha256": sha256(ROOT / "scripts" / "fit_battery_ecm_from_pulses.py"),
            "execution_source": str(ROOT / "scripts" / "solar_sim.py"),
            "execution_source_sha256": sha256(ROOT / "scripts" / "solar_sim.py"),
            "fixed_prior_removed": fixed_prior_removed,
            "passive_1rc_implemented": passive_1rc_implemented,
        },
        "evidence_sha256": {
            str(replay_csv): sha256(replay_csv),
            str(ocv_csv): sha256(ocv_csv),
            str(rint_csv): sha256(rint_csv),
            str(fit_summary_yaml): sha256(fit_summary_yaml),
        },
        "existing_artifact_rewritten": False,
        "conditional_terminal_series_resistance_ohm": float(beta[2]),
        "road_log_dynamic_fit": dynamic,
        "battery_fit": battery,
        "conditioned_voltage_rmse_v": validation.get("battery_conditional_voltage_rmse_clean_v"),
        "reason": "no independent long-rest multi-SoC/multi-temperature sub-second pulse dataset exists in the workspace",
    }
    cards = "".join(
        f'<div class="card {"pass" if value else "fail"}"><b>{html.escape(key)}</b><br>{"PASS" if value else "FAIL"}</div>'
        for key, value in checks.items()
    )
    sections = "".join(f'<section><h2>{html.escape(title)}</h2><img src="{uri}"></section>' for title, uri in figures)
    body = f"""<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>BWSC2025 battery ECM evidence audit</title>
<style>body{{margin:0;background:#eee8dc;font-family:"Yu Gothic",sans-serif;color:#18212b}}main{{max-width:1120px;margin:auto;padding:28px}}header,section{{background:#fffdf8;border:1px solid #d6cebd;border-radius:18px;padding:20px;margin-bottom:18px}}h1{{margin-top:0}}.status{{font-size:30px;color:#b91c1c;font-weight:800}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}.card{{padding:12px;border-radius:10px}}.pass{{background:#dcfce7}}.fail{{background:#fee2e2}}img{{width:100%;height:auto}}pre{{white-space:pre-wrap}}</style></head>
<body><main><header><h1>BWSC2025 OCV・R0・1-RC 物理証拠監査</h1><div class="status">実運用昇格不可</div><p><b>図4・図5は新しいフィッティング結果ではありません。</b> 現存MLE35の問題を可視化するためだけに残した不採用の旧成果物です。高SoC側の急上昇を支持する独立パルス証拠はなく、実運用mapには昇格しません。</p><p>新同定器は正値のpack-level 1-RC式を独立休止・パルス試験へ適合します。SoC・温度方向を既定で決め打ちせず、実測が示す上昇・下降を保持する一方、二次式を学習範囲外へ外挿せず、SoC上下端の独立holdoutを必須にします。方向制約は診断仮説として明示指定できるだけで、release既定値ではありません。現在は必要な実測CSVがないため、新mapはまだ生成されていません。</p><div class="grid">{cards}</div></header>{sections}<section><h2>監査JSON</h2><pre>{html.escape(json.dumps(summary, ensure_ascii=False, indent=2))}</pre></section></main></body></html>"""
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(body, encoding="utf-8", newline="\n")
    output_html.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay-csv", type=Path, required=True)
    parser.add_argument("--ocv-csv", type=Path, required=True)
    parser.add_argument("--rint-csv", type=Path, required=True)
    parser.add_argument("--fit-summary-yaml", type=Path, required=True)
    parser.add_argument("--output-html", type=Path, required=True)
    args = parser.parse_args()
    summary = generate(args.replay_csv, args.ocv_csv, args.rint_csv, args.fit_summary_yaml, args.output_html)
    print(json.dumps({"gate_pass": summary["gate_pass"], "output_html": str(args.output_html)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
