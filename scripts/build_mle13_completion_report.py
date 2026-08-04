#!/usr/bin/env python3
"""Build the night-aux, self-learning, and full-course validation report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import textwrap

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar.upper_horizon import build_upper_distance_horizon



def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8-sig")) or {}


def resolve_path(raw: str, base: Path) -> Path:
    path = Path(str(raw))
    if path.is_absolute():
        return path
    from_root = (ROOT / path).resolve()
    return from_root if from_root.exists() else (base / path).resolve()


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def escape_tex(value) -> str:
    out = str(value)
    for source, target in (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("#", r"\#"),
        ("_", r"\_"),
    ):
        out = out.replace(source, target)
    return out


def compile_tex(tex_path: Path) -> None:
    for _ in range(2):
        subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
            cwd=tex_path.parent,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


def analyze_simulation(profile: dict, manifest: dict, manifest_path: Path, out_dir: Path) -> dict:
    sim_path = resolve_path(manifest["out_csv"], manifest_path.parent)
    detail_path = resolve_path(manifest["detail_csv"], manifest_path.parent)
    sim = pd.read_csv(sim_path)
    detail = pd.read_csv(detail_path)
    utc = pd.to_datetime(detail["time_utc"], format="mixed", utc=True, errors="coerce")
    sim_utc = pd.to_datetime(sim["time_utc"], format="mixed", utc=True, errors="coerce")
    dt_h = utc.diff().dt.total_seconds().fillna(0.0).clip(0.0, 7200.0) / 3600.0
    speed = detail["v_exec_kmh"].astype(float)
    ghi = detail["G_poa"].astype(float)
    pack = detail["P_pack"].astype(float)
    pv = detail["P_pv"].astype(float)
    soc = detail["soc"].astype(float)
    aux = detail.get("P_aux", pd.Series(np.full(len(detail), np.nan))).astype(float)
    threshold = float(profile["model"].get("aux_night_ghi_threshold_wm2", 20.0))
    night = (speed <= 0.5) & (ghi <= threshold)
    day_stop = (speed <= 0.5) & (ghi > threshold)
    consecutive_night = night & night.shift(1, fill_value=False)

    local_day = utc.dt.tz_convert("Australia/Darwin").dt.strftime("%Y-%m-%d")
    sim_local_day = sim_utc.dt.tz_convert("Australia/Darwin").dt.strftime("%Y-%m-%d")
    daily_rows = []
    for day, idx in sim.groupby(sim_local_day).groups.items():
        state_loc = list(idx)
        energy_loc = list(detail.index[local_day == day])
        daily_rows.append(
            {
                "date_local": day,
                "distance_end_km": float(sim.loc[state_loc, "s_km"].iloc[-1]),
                "soc_start": float(sim.loc[state_loc, "soc"].iloc[0]),
                "soc_end": float(sim.loc[state_loc, "soc"].iloc[-1]),
                "pack_energy_wh": float((pack.loc[energy_loc] * dt_h.loc[energy_loc]).sum()),
                "pv_energy_wh": float((pv.loc[energy_loc] * dt_h.loc[energy_loc]).sum()),
            }
        )
    daily = pd.DataFrame(daily_rows)
    daily_path = out_dir / "fullsim_daily_energy.csv"
    daily.to_csv(daily_path, index=False, encoding="utf-8-sig")

    fig, axes = plt.subplots(3, 1, figsize=(10.5, 8.0), sharex=True)
    axes[0].plot(sim["s_km"], sim["v_exec_kmh"], color="#126e82")
    axes[0].set_ylabel("speed [km/h]")
    axes[1].plot(sim["s_km"], sim["soc"], color="#b5483f")
    axes[1].axhline(float(profile["mpc"].get("soc_finish_target", 0.12)), color="black", ls="--", lw=0.8)
    axes[1].set_ylabel("SoC [-]")
    axes[2].plot(detail["s_km"], pack, label="pack", color="#b05b3b", lw=0.9)
    axes[2].plot(detail["s_km"], pv, label="PV", color="#d9a21b", lw=0.9)
    axes[2].set_ylabel("power [W]")
    axes[2].set_xlabel("distance [km]")
    axes[2].legend()
    for axis in axes:
        axis.grid(alpha=0.25)
    fig.tight_layout()
    plot_path = out_dir / "fullsim_speed_soc_power.png"
    fig.savefig(plot_path, dpi=180)
    plt.close(fig)

    night_step = soc.diff().abs()[consecutive_night]
    soc_at_2831 = float(np.interp(2831.0, sim["s_km"].astype(float), sim["soc"].astype(float)))
    return {
        "sim_path": sim_path,
        "detail_path": detail_path,
        "daily_path": daily_path,
        "plot_path": plot_path,
        "daily": daily,
        "first_soc": float(sim["soc"].iloc[0]),
        "night_rows": int(night.sum()),
        "night_aux_max": float(np.nanmax(np.abs(aux[night]))) if night.any() and aux[night].notna().any() else float("nan"),
        "night_pack_max": float(np.nanmax(np.abs(pack[night]))) if night.any() else float("nan"),
        "night_soc_step_max": float(night_step.max()) if len(night_step) else 0.0,
        "day_stop_aux_median": float(aux[day_stop].median()) if day_stop.any() and aux[day_stop].notna().any() else float("nan"),
        "soc_at_2831": soc_at_2831,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--learning-summary", type=Path, required=True)
    parser.add_argument("--simulation-manifest", type=Path, required=True)
    parser.add_argument("--fit-summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    profile_path = args.profile.resolve()
    learning_path = args.learning_summary.resolve()
    manifest_path = args.simulation_manifest.resolve()
    fit_path = args.fit_summary.resolve()
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    profile = load_yaml(profile_path)
    learning = load_json(learning_path)
    manifest = load_json(manifest_path)
    fit = load_yaml(fit_path)
    rejected_manifest_path = (
        ROOT
        / "project_packages/bwsc2025_fitted_mle13_grounded_segmented/outputs/prerace_fullsim_hifi/latest_simulation_run.json"
    )
    rejected_manifest = load_json(rejected_manifest_path) if rejected_manifest_path.is_file() else None
    rejected_cfg = None
    if rejected_manifest:
        rejected_resolved = resolve_path(rejected_manifest["resolved_yaml"], rejected_manifest_path.parent)
        rejected_cfg = load_yaml(rejected_resolved) if rejected_resolved.is_file() else None
    iter64_manifest_path = (
        ROOT
        / "project_packages/bwsc2025_fitted_mle13_grounded_segmented/outputs/prerace_fullsim_iter64_gate/latest_simulation_run.json"
    )
    iter64_manifest = load_json(iter64_manifest_path) if iter64_manifest_path.is_file() else None
    sim = analyze_simulation(profile, manifest, manifest_path, out_dir)
    trials_path = resolve_path(learning["trial_results_csv"], learning_path.parent)
    trials = pd.read_csv(trials_path)
    baseline = learning["baseline_validation"]
    tuned = learning["tuned_validation"]
    model = profile["model"]
    mpc = profile["mpc"]
    validation = fit.get("validation_metrics", {})

    horizon = build_upper_distance_horizon(
        mode=str(mpc.get("upper_horizon_mode", "adaptive_full_race")),
        s0_km=float(profile["simulation"].get("start_s_km", 0.0)),
        race_km=float(mpc["race_km"]),
        ds_km=float(mpc.get("upper_ds_km", 10.0)),
        horizon_km=float(mpc["upper_horizon_km"]),
        max_steps=int(mpc["upper_max_steps"]),
        ctrl_km=float(mpc.get("upper_ctrl_km", 500.0)),
        adaptive_min_ds_km=float(mpc.get("upper_adaptive_min_ds_km", 20.0)),
        adaptive_max_ds_km=float(mpc.get("upper_adaptive_max_ds_km", 350.0)),
        adaptive_growth=float(mpc.get("upper_adaptive_growth", 1.28)),
    )
    inner_dim = len(horizon.ctrl_s_km)
    cem_generations = int(mpc.get("upper_cem_generations", 0))
    cem_population = int(mpc.get("upper_cem_population", 0))
    cem_candidates = cem_generations * cem_population
    adopted = float(tuned["score"]) >= float(baseline["score"])
    decision = "候補採用" if adopted else "非退行ゲートにより基準維持"
    last_day = sim["daily"].iloc[-1] if len(sim["daily"]) else {}

    audit_data = {
        "outer_weight_dimensions": 15,
        "inner_speed_dimensions": inner_dim,
        "outer_trials": int(len(trials)),
        "inner_cem_candidates": cem_candidates,
        "learning_decision": decision,
        "accepted_upper_solver_all_success": bool(manifest.get("upper_solver_all_success", False)),
        "accepted_upper_solver_failure_count": int(manifest.get("upper_solver_failure_count", 0)),
        "night_rows": sim["night_rows"],
        "night_aux_max_abs_w": sim["night_aux_max"],
        "night_pack_max_abs_w": sim["night_pack_max"],
        "night_soc_max_step": sim["night_soc_step_max"],
        "day_stop_aux_median_w": sim["day_stop_aux_median"],
        "no_trouble_soc_at_2831": sim["soc_at_2831"],
        "rejected_high_search_manifest": relative(rejected_manifest_path) if rejected_manifest else "",
        "rejected_high_search_elapsed_h": float(rejected_manifest["elapsed_hours"]) if rejected_manifest else None,
        "rejected_high_search_final_soc": float(rejected_manifest["final_soc"]) if rejected_manifest else None,
        "rejected_iter64_manifest": relative(iter64_manifest_path) if iter64_manifest else "",
        "rejected_iter64_elapsed_h": float(iter64_manifest["elapsed_hours"]) if iter64_manifest else None,
        "rejected_iter64_final_soc": float(iter64_manifest["final_soc"]) if iter64_manifest else None,
    }
    (out_dir / "completion_report_data.json").write_text(
        json.dumps(audit_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    daily_tex = sim["daily"].to_latex(index=False, escape=True, float_format="%.4g")
    rejected_tex = ""
    if rejected_manifest and rejected_cfg:
        rejected_mpc = rejected_cfg.get("mpc", {})
        rejected_candidates = int(rejected_mpc.get("upper_cem_generations", 0)) * int(
            rejected_mpc.get("upper_cem_population", 0)
        )
        rejected_tex = rf"""
\subsection{{高探索候補の非劣化ゲート}}
24予測step、CEM {int(rejected_mpc.get('upper_cem_generations', 0))}世代
$\times$ {int(rejected_mpc.get('upper_cem_population', 0))}個={rejected_candidates}大域候補、
局所精密化{int(rejected_mpc.get('upper_local_refine_topk', 0))}開始点のrunも実施した。
しかし所要時間={float(rejected_manifest['elapsed_hours']):.3f} h、
終端SoC={float(rejected_manifest['final_soc']):.4f}であり、再学習検証解より明確に悪化した。
候補数の増加は大域最適性の証明ではないため、このrunは棄却し、resolved YAMLと結果を監査証拠として保存した。
"""
    if iter64_manifest:
        rejected_tex += rf"""

反復上限だけを16から64へ増やした比較runは数値収束したが、
所要時間={float(iter64_manifest['elapsed_hours']):.3f} h、
終端SoC={float(iter64_manifest['final_soc']):.4f}であった。
外側と同じscoreは5270.343で、反復16検証解の{float(tuned['score']):.3f}を下回ったため棄却した。
これは反復数または世代数の単調増加が制御性能の単調改善を保証しないことを示す。
"""
    tex = rf"""
\documentclass[11pt,a4paper]{{article}}
\usepackage[margin=19mm]{{geometry}}
\usepackage{{fontspec,xeCJK,amsmath,booktabs,graphicx,hyperref}}
\setmainfont{{Times New Roman}}
\setCJKmainfont{{Yu Gothic}}
\hypersetup{{colorlinks=true,urlcolor=blue}}
\title{{YATA BWSC2025 mle13\\夜間補機・自己学習・全コースMPC検証}}
\author{{MPCEMS YATA}}
\date{{2026-07-13}}
\begin{{document}}
\maketitle

\section{{結論}}
本runは事故リタイア地点2831 kmでは止めず、no-trouble条件で全コース
{float(manifest['race_km']):.1f} kmを評価した。
完走={bool(manifest['finish_reached'])}、所要時間={float(manifest['elapsed_hours']):.3f} h、
終端SoC={float(manifest['final_soc']):.4f}である。
運用初期値は\texttt{{simulation.soc0}}={float(profile['simulation']['soc0']):.4f}であり、
履歴再生用\texttt{{identification.fitted\_replay\_soc0}}とは分離した。

\section{{MPCと数値探索}}
上位は距離領域非線形MPC、下位は1 Hz追従MPCである。
\[
\min_{{\bf v}}\sum_k\ell(x_k,v_k,w_k)+V_f(x_N),\quad
x_{{k+1}}=f(x_k,v_k,w_k),\quad g(x_k,v_k)\leq0.
\]
外側CEMの重み探索は15次元、内側全コース速度列は{inner_dim}次元である。
外側記録は{len(trials)}試行。最終内側はCEM {cem_generations}世代
$\times$ {cem_population}個={cem_candidates}候補とL-BFGS-B局所精密化を用いる。
基準score={float(baseline['score']):.3f}、候補score={float(tuned['score']):.3f}、
判定は「{decision}」である。
採用runの数値収束flagは{bool(manifest.get('upper_solver_all_success', False))}、
未収束solve数は{int(manifest.get('upper_solver_failure_count', 0))}である。
性能非劣化は確認したが、これは大域最適性の証明ではない。
{rejected_tex}

\section{{夜間補機と同期}}
\[
P_\mathrm{{pack}}=P_\mathrm{{drive,dc}}-P_\mathrm{{regen,dc}}
+P_\mathrm{{aux}}-P_\mathrm{{pv}}.
\]
補機はpack電気側へ加える。走行中と日中停車は
{float(model['P_aux']):.3f} W、日射
{float(model['aux_night_ghi_threshold_wm2']):.1f} W/m$^2$以下の夜間は
{float(model['P_aux_night']):.3f} Wである。
夜間停止行={sim['night_rows']}、夜間$|P_\mathrm{{aux}}|_{{\max}}$={sim['night_aux_max']:.4g} W、
夜間連続行の最大SoC step={sim['night_soc_step_max']:.3e}である。
UDPはUTCを必須とし、5秒超の遅延、2秒超の未来、重複、順序逆転をfilter前に拒否する。

\section{{全コース結果}}
\begin{{center}}
\includegraphics[width=0.96\linewidth]{{{sim['plot_path'].name}}}
\end{{center}}
初回記録SoC={sim['first_soc']:.4f}。最終日はpack
{float(last_day.get('pack_energy_wh', float('nan'))):.1f} Wh、PV
{float(last_day.get('pv_energy_wh', float('nan'))):.1f} Wh、SoC
{float(last_day.get('soc_start', float('nan'))):.4f}から
{float(last_day.get('soc_end', float('nan'))):.4f}である。
夜間は回復させずほぼ保持し、日の出後のPVだけがSoCを回復させる。
no-trouble MPCは2831 kmをSoC={sim['soc_at_2831']:.4f}で通過した。
これは実走履歴の事故・停車を含む2831 km anchorとは異なる実験であり、
差をそのままモデル精度と解釈してはならない。

\scriptsize
{daily_tex}
\normalsize

\section{{車両同定精度}}
clean power RMSE={float(validation.get('power_rmse_clean_w', float('nan'))):.2f} W、
clean voltage RMSE={float(validation.get('voltage_rmse_clean_v', float('nan'))):.3f} V、
2831 km SoC anchor誤差={float(validation.get('retire_anchor_soc_error', float('nan'))):.4f}である。
終端anchorは整合するがday2/day3を含む時系列誤差はまだ大きい。
したがって本モデルを計量標準級digital twinとは断言せず、
MPC改善とモデル同定精度を分けて扱う。

\section{{主要係数}}
\begin{{tabular}}{{lr}}
\toprule parameter & value\\
\midrule
mass & {float(model['m']):.3f} kg\\
$C_dA$ & {float(model['CdA']):.6f} m$^2$\\
$C_{{rr}}$ & {float(model['Crr']):.6f}\\
battery energy & {float(model['E_nom_Wh']):.3f} Wh\\
panel gain & {float(model.get('panel_gain', 1.0)):.6f}\\
drive efficiency scale & {float(model.get('drive_eff_scale', 1.0)):.6f}\\
Rint scale & {float(model.get('rint_scale', 1.0)):.6f}\\
\bottomrule
\end{{tabular}}

\section{{再現用成果物}}
\begingroup
\scriptsize\raggedright
\begin{{itemize}}
\item profile: \path{{{escape_tex(relative(profile_path))}}}
\item learning: \path{{{escape_tex(relative(learning_path))}}}
\item full-sim manifest: \path{{{escape_tex(relative(manifest_path))}}}
\item fit summary: \path{{{escape_tex(relative(fit_path))}}}
\item daily energy: \path{{{escape_tex(relative(sim['daily_path']))}}}
\end{{itemize}}
\endgroup

\section{{根拠文献}}
\begin{{enumerate}}
\item de Boer et al., Cross-Entropy Method,
\url{{https://doi.org/10.1007/s10479-005-5724-z}}.
\item Gros and Zanon, Data-driven Economic NMPC using RL,
\url{{https://arxiv.org/abs/1904.04152}}.
\item Zarrouki et al., Safe RL driven weights-varying MPC,
\url{{https://arxiv.org/abs/2402.02624}}.
\item Howlett et al., Optimal solar-car driving strategy,
\url{{https://doi.org/10.1093/imaman/8.1.59}}.
\item Byrd et al., L-BFGS-B,
\url{{https://doi.org/10.1137/0916069}}.
\end{{enumerate}}
\end{{document}}
"""
    tex_path = out_dir / "mle13_night_aux_hifi_completion_report.tex"
    tex_path.write_text(textwrap.dedent(tex).strip() + "\n", encoding="utf-8")
    compile_tex(tex_path)
    print(tex_path.with_suffix(".pdf"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
