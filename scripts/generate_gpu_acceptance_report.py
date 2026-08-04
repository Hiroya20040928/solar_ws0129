#!/usr/bin/env python3
"""Build the auditable GPU-search, exact-replay, and mesh-convergence report."""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import textwrap
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]


STAGES = ("coarse_5km", "fine_1km", "ultra_100m", "control_2km", "control_1km")
EXACT_STAGES = ("exact_5km", "exact_2km", "exact_1km")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def read_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.is_file() else {}


def finite(value: object, default: float = float("nan")) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def tex_escape(value: object) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for source, replacement in replacements.items():
        text = text.replace(source, replacement)
    return text


def format_cell(value: object) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "true" if bool(value) else "false"
    if isinstance(value, (float, np.floating)):
        return "" if not np.isfinite(value) else f"{float(value):.6g}"
    return str(value)


def tex_table(frame: pd.DataFrame, *, resize: bool = True) -> str:
    if frame.empty:
        return "データなし。"
    display = frame.copy()
    display = display.map(format_cell)
    headers = " & ".join(tex_escape(column) for column in display.columns) + r" \\"
    rows = "\n".join(
        " & ".join(tex_escape(value) for value in row) + r" \\"
        for row in display.itertuples(index=False, name=None)
    )
    body = textwrap.dedent(
        f"""
        \\begin{{tabular}}{{{'l' * len(display.columns)}}}
        \\toprule
        {headers}
        \\midrule
        {rows}
        \\bottomrule
        \\end{{tabular}}
        """
    ).strip()
    if resize:
        return f"\\par\\medskip\\noindent\\resizebox{{\\textwidth}}{{!}}{{%\n{body}\n}}\\par\\medskip"
    return f"\\par\\medskip\\noindent\n{body}\n\\par\\medskip"


def collect_surrogate_summaries(campaign_dir: Path) -> pd.DataFrame:
    rows: list[dict] = []
    for seed_dir in sorted(campaign_dir.glob("seed_*")):
        for stage in STAGES:
            payload = read_json(seed_dir / stage / "summary.json")
            if not payload:
                continue
            rows.append(
                {
                    "seed": seed_dir.name,
                    "stage": stage,
                    "ds_km": finite(payload.get("integration_ds_km")),
                    "ctrl_km": finite(payload.get("control_ds_km")),
                    "dimension": int(payload.get("control_dimensions", 0) or 0),
                    "generations": int(payload.get("generations", 0) or 0),
                    "population": int(payload.get("population", 0) or 0),
                    "candidates": int(payload.get("candidates_evaluated", 0) or 0),
                    "cost": finite(payload.get("surrogate_cost")),
                    "elapsed_h": finite(payload.get("surrogate_elapsed_h")),
                    "final_soc": finite(payload.get("surrogate_final_soc")),
                    "min_soc": finite(payload.get("surrogate_min_soc")),
                    "max_discharge_a": finite(payload.get("surrogate_max_current_a")),
                    "max_charge_a": finite(payload.get("surrogate_max_charge_current_a")),
                    "max_timing_violation_sec": finite(
                        payload.get("surrogate_max_timing_violation_sec")
                    ),
                    "finish_deadline_violation_sec": finite(
                        payload.get("surrogate_finish_deadline_violation_sec")
                    ),
                }
            )
    return pd.DataFrame(rows)


def load_progress(campaign_dir: Path) -> pd.DataFrame:
    rows: list[dict] = []
    for path in sorted(campaign_dir.glob("seed_*/*/progress.jsonl")):
        seed = path.parents[1].name
        stage = path.parent.name
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(
                {
                    "seed": seed,
                    "stage": stage,
                    "generation": int(payload.get("generation", 0) or 0),
                    "best_cost": finite(payload.get("best_cost")),
                    "elapsed_h": finite(payload.get("cumulative_best_elapsed_h")),
                }
            )
    return pd.DataFrame(rows)


def collect_exact_rankings(acceptance_dir: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for stage in EXACT_STAGES:
        path = acceptance_dir / stage / "exact_1hz_candidate_ranking.csv"
        if not path.is_file():
            continue
        frame = pd.read_csv(path)
        frame.insert(0, "exact_stage", stage)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def local_selected_manifest(acceptance_dir: Path) -> tuple[Path | None, dict]:
    selection = read_json(acceptance_dir / "exact_1km" / "exact_selection.json")
    seed = str(selection.get("selected_seed", "")).strip()
    candidate = acceptance_dir / "exact_1km" / seed / "latest_simulation_run.json"
    return (candidate if candidate.is_file() else None), selection


def resolve_sibling(manifest_path: Path, raw: object) -> Path:
    source = Path(str(raw or ""))
    if source.is_file():
        return source
    return manifest_path.parent / source.name


def make_convergence_plot(progress: pd.DataFrame, output: Path) -> Path | None:
    if progress.empty:
        return None
    stages = [stage for stage in STAGES if stage in set(progress["stage"])]
    fig, axes = plt.subplots(len(stages), 1, figsize=(9.0, max(3.0, 2.1 * len(stages))), squeeze=False)
    for axis, stage in zip(axes[:, 0], stages):
        subset = progress.loc[progress["stage"] == stage]
        for seed, seed_frame in subset.groupby("seed"):
            axis.plot(seed_frame["generation"], seed_frame["elapsed_h"], label=seed, linewidth=1.0)
        axis.set_title(stage)
        axis.set_ylabel("best elapsed [h]")
        axis.grid(alpha=0.25)
    axes[-1, 0].set_xlabel("generation")
    axes[0, 0].legend(ncol=4, fontsize=8)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output


def make_fullsim_plot(manifest_path: Path | None, output: Path) -> tuple[Path | None, pd.DataFrame]:
    if manifest_path is None:
        return None, pd.DataFrame()
    manifest = read_json(manifest_path)
    detail_path = resolve_sibling(manifest_path, manifest.get("detail_csv", ""))
    if not detail_path.is_file():
        return None, pd.DataFrame()
    frame = pd.read_csv(detail_path, low_memory=False)
    distance = pd.to_numeric(frame.get("s_km"), errors="coerce")
    soc = pd.to_numeric(frame.get("soc"), errors="coerce")
    speed_column = "v_exec_kmh" if "v_exec_kmh" in frame else "lower_speed_cmd_kmh"
    speed = pd.to_numeric(frame.get(speed_column), errors="coerce")
    pv = pd.to_numeric(frame.get("P_pv"), errors="coerce")
    pack = pd.to_numeric(frame.get("P_pack"), errors="coerce")
    fig, axes = plt.subplots(3, 1, figsize=(10.0, 7.5), sharex=True)
    axes[0].plot(distance, speed, color="black", linewidth=0.6)
    axes[0].set_ylabel("speed [km/h]")
    axes[1].plot(distance, soc, color="0.2", linewidth=0.8)
    axes[1].set_ylabel("SoC [-]")
    axes[2].plot(distance, pv, color="0.55", linewidth=0.5, label="PV")
    axes[2].plot(distance, pack, color="black", linewidth=0.5, label="pack")
    axes[2].set_ylabel("power [W]")
    axes[2].set_xlabel("route distance [km]")
    axes[2].legend()
    for axis in axes:
        axis.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(output, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output, frame


def build_report(
    profile_path: Path,
    campaign_dir: Path,
    acceptance_dir: Path,
    fit_summary_path: Path,
    promotion_gate_path: Path,
    output_dir: Path,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    profile = read_yaml(profile_path)
    fit_summary = read_yaml(fit_summary_path)
    promotion_gate = read_json(promotion_gate_path)
    fit_label = fit_summary_path.parent.name
    residual_dir = fit_summary_path.parent / "reports" / "residual_audit"
    residual_json = read_json(residual_dir / "residual_audit.json")
    residual_metrics_path = residual_dir / "residual_regime_metrics.csv"
    residual_metrics = (
        pd.read_csv(residual_metrics_path)
        if residual_metrics_path.is_file()
        else pd.DataFrame()
    )
    residual_plot_source = residual_dir / "residual_soc_audit.png"
    residual_plot = None
    if residual_plot_source.is_file():
        residual_plot = output_dir / "identification_residual_soc_audit.png"
        shutil.copy2(residual_plot_source, residual_plot)
    surrogate = collect_surrogate_summaries(campaign_dir)
    progress = load_progress(campaign_dir)
    exact = collect_exact_rankings(acceptance_dir)
    mesh_runs_path = acceptance_dir / "mesh_convergence" / "mesh_runs.csv"
    mesh_comparisons_path = acceptance_dir / "mesh_convergence" / "mesh_comparisons.csv"
    mesh_summary = read_json(acceptance_dir / "mesh_convergence" / "mesh_convergence_summary.json")
    weather_gate = read_json(acceptance_dir / "policy_weather_input_gate.json")
    if not weather_gate:
        weather_gate = read_json(campaign_dir / "policy_weather_input_gate.json")
    weather_csv_name = Path(str(weather_gate.get("weather_csv", ""))).name
    mesh_runs = pd.read_csv(mesh_runs_path) if mesh_runs_path.is_file() else pd.DataFrame()
    mesh_comparisons = pd.read_csv(mesh_comparisons_path) if mesh_comparisons_path.is_file() else pd.DataFrame()
    selected_manifest_path, exact_selection = local_selected_manifest(acceptance_dir)
    selected_manifest = read_json(selected_manifest_path) if selected_manifest_path else {}

    convergence_plot = make_convergence_plot(progress, output_dir / "gpu_search_convergence.png")
    fullsim_plot, detail = make_fullsim_plot(selected_manifest_path, output_dir / "exact_1hz_fullsim.png")
    campaign_complete = (campaign_dir / "CAMPAIGN_COMPLETE").is_file()
    policy_acceptance_complete = (
        acceptance_dir / "POLICY_ACCEPTANCE_COMPLETE"
    ).is_file()
    operational_acceptance_complete = (
        acceptance_dir / "ACCEPTANCE_COMPLETE"
    ).is_file()
    acceptance_failed = (acceptance_dir / "ACCEPTANCE_FAILED").is_file()
    model_gate_pass = bool(promotion_gate.get("gate_pass", False))
    planner_gate_pass = bool(
        policy_acceptance_complete and mesh_summary.get("mesh_gate_pass", False)
    )
    weather_gate_pass = bool(weather_gate.get("passed", False))
    operational_adoption = bool(
        operational_acceptance_complete
        and model_gate_pass
        and planner_gate_pass
        and weather_gate_pass
    )

    exact_display_columns = [
        "exact_stage", "seed_label", "feasible", "elapsed_hours", "final_soc", "min_soc",
        "prediction_execution_soc_error", "max_discharge_current_a",
        "max_charge_current_a_signed", "min_voltage_v", "max_voltage_v",
        "max_control_stop_late_sec", "finish_deadline_late_sec",
    ]
    exact_display = exact[[column for column in exact_display_columns if column in exact]].copy()
    surrogate_display = surrogate[
        [
            "seed", "stage", "dimension", "generations", "population", "candidates",
            "elapsed_h", "final_soc", "min_soc", "max_timing_violation_sec",
        ]
    ].copy() if not surrogate.empty else pd.DataFrame()
    mesh_display_columns = [
        "phase", "coarse_ds_km", "coarse_ctrl_km", "fine_ds_km", "fine_ctrl_km",
        "elapsed_change_sec", "terminal_soc_change", "speed_profile_rms_change_kmh", "pair_pass",
    ]
    mesh_display = mesh_comparisons[
        [column for column in mesh_display_columns if column in mesh_comparisons]
    ].copy() if not mesh_comparisons.empty else pd.DataFrame()
    gate_checks = promotion_gate.get("checks", {}) or {}
    gate_values = promotion_gate.get("values", {}) or {}
    gate_thresholds = promotion_gate.get("thresholds", {}) or {}
    promotion_display = pd.DataFrame(
        [
            {
                "check": name,
                "pass": bool(passed),
                "value": gate_values.get(name, "see gate JSON"),
            }
            for name, passed in gate_checks.items()
        ]
    )
    threshold_display = pd.DataFrame(
        [{"threshold": name, "value": value} for name, value in gate_thresholds.items()]
    )
    residual_display = residual_metrics.loc[
        residual_metrics.get("group", pd.Series(dtype=str)).isin(
            ["day", "slope_pct", "speed_kmh"]
        )
    ].copy()
    if len(residual_display) > 24:
        residual_display = residual_display.head(24)

    metrics = fit_summary.get("validation_metrics", {}) or {}
    fit_plan = fit_summary.get("fit_plan", {}) or {}
    acceleration_fit = fit_plan.get("acceleration_observation_fit", {}) or {}
    grade_fit = fit_plan.get("grade_observation_fit", {}) or {}
    model = profile.get("model", {}) or {}
    mpc = profile.get("mpc", {}) or {}
    simulation = profile.get("simulation", {}) or {}
    profile_paths = profile.get("paths", {}) or {}
    detail_rows = int(selected_manifest.get("detail_rows", len(detail)) or len(detail))
    total_candidates = int(surrogate["candidates"].sum()) if not surrogate.empty else 0
    dimensions = sorted(set(int(value) for value in surrogate.get("dimension", []) if int(value) > 0))
    selected_soc_2831 = float("nan")
    selected_finish_utc = ""
    selected_elapsed_h = finite(selected_manifest.get("elapsed_hours"))
    start_utc_raw = str(simulation.get("start_utc", "") or "")
    if start_utc_raw and math.isfinite(selected_elapsed_h):
        selected_finish_utc = (
            pd.Timestamp(start_utc_raw)
            + pd.to_timedelta(selected_elapsed_h, unit="h")
        ).isoformat()
    if not detail.empty and {"s_km", "soc"}.issubset(detail):
        work = detail[["s_km", "soc"]].apply(pd.to_numeric, errors="coerce").dropna().sort_values("s_km")
        if not work.empty and work["s_km"].min() <= 2831.0 <= work["s_km"].max():
            selected_soc_2831 = float(np.interp(2831.0, work["s_km"], work["soc"]))

    summary = {
        "campaign_complete": campaign_complete,
        # Retain the old key as an operational-release alias for downstream readers.
        "acceptance_complete": operational_acceptance_complete,
        "policy_acceptance_complete": policy_acceptance_complete,
        "operational_acceptance_complete": operational_acceptance_complete,
        "acceptance_failed": acceptance_failed,
        "model_gate_pass": model_gate_pass,
        "planner_mesh_gate_pass": planner_gate_pass,
        "policy_weather_input_gate_pass": weather_gate_pass,
        "policy_weather_csv": weather_gate.get("weather_csv", ""),
        "policy_weather_sources": weather_gate.get("weather_sources", []),
        "policy_weather_temporal_semantics": weather_gate.get(
            "radiation_temporal_semantics", []
        ),
        "operational_adoption_allowed": operational_adoption,
        "total_surrogate_candidates": total_candidates,
        "optimization_dimensions": dimensions,
        "exact_candidate_count": int(len(exact)),
        "exact_feasible_count": int(exact.get("feasible", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()),
        "selected_elapsed_h": selected_elapsed_h,
        "selected_finish_utc": selected_finish_utc,
        "race_deadline_utc": simulation.get("race_deadline_utc", ""),
        "official_stop_yaml": profile_paths.get("stop_yaml", ""),
        "selected_final_soc": finite(selected_manifest.get("final_soc")),
        "selected_soc_at_2831km": selected_soc_2831,
        "selected_detail_rows": detail_rows,
        "race_km": finite(mpc.get("race_km")),
        "vehicle_mass_kg": finite(model.get("m")),
        "identification_run": fit_label,
        "residual_audit_available": bool(residual_json),
        "vehicle_soc_divergence": residual_json.get("vehicle_soc_divergence", {}),
        "end_to_end_soc_divergence": residual_json.get("end_to_end_soc_divergence", {}),
        "acceleration_observation_fit": {
            "enabled": bool(acceleration_fit.get("enabled", False)),
            "adopted": bool(acceleration_fit.get("adopted", False)),
            "filter_method": acceleration_fit.get("selected_filter_method"),
            "filter_window_sec": acceleration_fit.get("selected_filter_window_sec"),
            "lag_sec": acceleration_fit.get("selected_lag_sec"),
            "holdout_day": acceleration_fit.get("holdout_day"),
            "validation_rmse_ratio": acceleration_fit.get("validation_rmse_ratio"),
        },
        "grade_observation_fit": {
            "enabled": bool(grade_fit.get("enabled", False)),
            "adopted": bool(grade_fit.get("adopted", False)),
            "smoothing_window_km": grade_fit.get("selected_smoothing_window_km"),
            "distance_offset_km": grade_fit.get("selected_distance_offset_km"),
            "provisional_grade_scale": grade_fit.get("selected_provisional_grade_scale"),
            "holdout_day": grade_fit.get("holdout_day"),
            "validation_rmse_ratio": grade_fit.get("validation_rmse_ratio"),
        },
    }
    (output_dir / "gpu_acceptance_report_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    md_path = output_dir / "gpu_acceptance_and_fullsim_report.md"
    md_path.write_text(
        "# GPU自己学習・厳密1 Hz全行程・メッシュ収束報告書\n\n"
        + "## 技術結論\n\n"
        + f"- GPU campaign complete: `{campaign_complete}`\n"
        + f"- exact 1 Hz/mesh policy acceptance complete: `{policy_acceptance_complete}`\n"
        + f"- operational acceptance complete: `{operational_acceptance_complete}`\n"
        + f"- independent model gate pass: `{model_gate_pass}`\n"
        + f"- planner numerical gate pass: `{planner_gate_pass}`\n"
        + f"- independent instant weather gate pass: `{weather_gate_pass}`\n"
        + f"- policy weather CSV: `{weather_gate.get('weather_csv', '')}`\n"
        + f"- policy weather sources: `{weather_gate.get('weather_sources', [])}`\n"
        + f"- operational adoption allowed: `{operational_adoption}`\n"
        + f"- surrogate candidates: `{total_candidates}`\n"
        + f"- optimization dimensions: `{dimensions}`\n"
        + f"- exact selected elapsed: `{summary['selected_elapsed_h']}` h\n"
        + f"- exact selected finish UTC: `{selected_finish_utc}`\n"
        + f"- official race deadline UTC: `{simulation.get('race_deadline_utc', '')}`\n"
        + f"- official control-stop YAML: `{profile_paths.get('stop_yaml', '')}`\n"
        + f"- exact selected final SoC: `{summary['selected_final_soc']}`\n"
        + f"- exact SoC at 2831 km: `{selected_soc_2831}`\n"
        + f"- acceleration observation: adopted=`{bool(acceleration_fit.get('adopted', False))}`, "
        + f"filter=`{acceleration_fit.get('selected_filter_method')}`, "
        + f"window=`{acceleration_fit.get('selected_filter_window_sec')}` s, "
        + f"lag=`{acceleration_fit.get('selected_lag_sec')}` s, "
        + f"holdout ratio=`{acceleration_fit.get('validation_rmse_ratio')}`\n"
        + f"- DEM grade observation: adopted=`{bool(grade_fit.get('adopted', False))}`, "
        + f"window=`{grade_fit.get('selected_smoothing_window_km')}` km, "
        + f"offset=`{grade_fit.get('selected_distance_offset_km')}` km, "
        + f"holdout ratio=`{grade_fit.get('validation_rmse_ratio')}`\n\n"
        + f"モデル、planner、気象独立性の3ゲートは独立である。メッシュ収束しても、{fit_label}の実測再現または気象独立性が失敗している限り本番採用しない。\n",
        encoding="utf-8",
    )

    figure_convergence = (
        r"\begin{figure}[htbp]\centering\includegraphics[width=0.96\linewidth]{gpu_search_convergence.png}"
        r"\caption{4 seed・各fidelityのbest elapsed収束履歴}\end{figure}"
        if convergence_plot else "収束履歴は未生成である。"
    )
    figure_fullsim = (
        r"\begin{figure}[htbp]\centering\includegraphics[width=0.96\linewidth]{exact_1hz_fullsim.png}"
        r"\caption{選択policyの厳密1 Hz全行程出力}\end{figure}"
        if fullsim_plot else "厳密1 Hz図は未生成である。"
    )
    figure_residual = (
        r"\begin{figure}[htbp]\centering\includegraphics[width=0.96\linewidth]{identification_residual_soc_audit.png}"
        r"\caption{実測条件付き電池リプレイに対する車両・end-to-end SoC乖離と電力残差}\end{figure}"
        if residual_plot else "残差監査図は未生成である。"
    )
    vehicle_divergence = residual_json.get("vehicle_soc_divergence", {}) or {}
    end_divergence = residual_json.get("end_to_end_soc_divergence", {}) or {}
    vehicle_first_2pct_km = finite(
        (vehicle_divergence.get("first_abs_2pct") or {}).get("s_km")
    )
    end_first_2pct_km = finite(
        (end_divergence.get("first_abs_2pct") or {}).get("s_km")
    )
    tex = f"""
    \\documentclass[a4paper,10pt]{{article}}
    \\usepackage[top=17mm,bottom=20mm,left=17mm,right=17mm]{{geometry}}
    \\usepackage{{fontspec}}
    \\usepackage{{xeCJK}}
    \\setmainfont{{Times New Roman}}
    \\setCJKmainfont{{Yu Gothic}}
    \\setCJKmonofont{{Yu Gothic}}
    \\usepackage{{amsmath,amssymb,booktabs,longtable,graphicx,xurl}}
    \\usepackage[unicode,hidelinks]{{hyperref}}
    \\title{{GPU自己学習・厳密1 Hz全行程・メッシュ収束報告書}}
    \\author{{MPCEMS YATA}}
    \\date{{2026年7月17日}}
    \\begin{{document}}
    \\maketitle

    \\section{{技術結論}}
    campaign完了={str(campaign_complete).lower()}、policy厳密受入完了={str(policy_acceptance_complete).lower()}、
    本番受入完了={str(operational_acceptance_complete).lower()}、
    planner数値ゲート={str(planner_gate_pass).lower()}、独立モデルゲート={str(model_gate_pass).lower()}、
    独立・瞬時気象ゲート={str(weather_gate_pass).lower()}である。
    したがって本番採用可否は \\textbf{{{str(operational_adoption).lower()}}} である。
    plannerが収束しても、\texttt{{{tex_escape(fit_label)}}}の実測再現ゲートが失敗している限り、車両モデルの高精度性や本番安全性は証明されない。

    \\section{{問題設定}}
    大会全長は $S_f={finite(mpc.get('race_km')):.1f}\\,\\mathrm{{km}}$、車重は
    $m={finite(model.get('m')):.1f}\\,\\mathrm{{kg}}$ とする。最適化変数は距離制御点の速度
    $u=[v_0,\\ldots,v_{{N_c-1}}]$ であり、確認された次元は
    \\texttt{{{tex_escape(dimensions)}}} である。GPU surrogateで評価した候補総数は
    {total_candidates:,}、厳密1 Hz候補数は {len(exact)} である。
    目的は制約を満たしつつ到着時間を最小化し、終端SoCを
    $z_f={finite(mpc.get('soc_finish_target')):.4f}\\pm{finite(mpc.get('soc_finish_tol')):.4f}$へ入れることである。
    公式stop定義は\\texttt{{{tex_escape(Path(str(profile_paths.get('stop_yaml', ''))).name)}}}、
    finish絶対締切は\\texttt{{{tex_escape(simulation.get('race_deadline_utc', ''))}}}である。

    \\section{{物理モデルと制約}}
    \\[
    P_{{road}}=\\left[\\tfrac12\\rho C_dA(v+w)^2+mgC_{{rr}}\\cos\\theta+mg\\sin\\theta\\right]v,
    \\quad P_{{pack}}=P_{{drive}}-P_{{regen}}+P_{{aux}}-P_{{pv}}.
    \\]
    \\[
    z_{{k+1}}=z_k-\\eta(I_k)\\frac{{I_k\\Delta t_k}}{{3600Q_{{nom}}}},
    \\qquad V_k=OCV(z_k)-I_kR_{{tot}}(T_k,z_k)-V_{{p,k}}.
    \\]
    受入は完走、SoC下限、終端帯、充放電電流、上下限電圧、予測実行SoC同期を同時に要求する。

    \\section{{GPU multi-fidelity探索}}
    CEMは各世代でelite集合から
    \\[
    \\mu_{{g+1}}=\\operatorname{{mean}}(U_{{elite}}),\\qquad
    \\sigma_{{g+1}}=\\max(\\operatorname{{std}}(U_{{elite}}),\\sigma_{{min}})
    \\]
    と更新する。5 km粗探索、1 km積分、0.1 km積分、2 km制御、1 km制御を独立seedで評価する。
    {tex_table(surrogate_display)}
    {figure_convergence}

    \\section{{政策評価に用いた気象の独立性}}
    政策探索の気象CSVは \\texttt{{{tex_escape(weather_csv_name)}}} であり、
    sourceは \\texttt{{{tex_escape(weather_gate.get('weather_sources', []))}}}、時刻意味は
    \\texttt{{{tex_escape(weather_gate.get('radiation_temporal_semantics', []))}}} である。
    独立気象ゲートは \\textbf{{{str(weather_gate_pass).lower()}}} である。
    実車PVから逆算・補正した日射は車両同定には使用できるが、同じPVを良く見せる政策評価へ再利用すると
    循環評価になる。このため政策探索には車両PVと独立した瞬時値だけを許可し、ゲート失敗時は
    plannerとモデルの他ゲートが通っても本番採用を禁止する。

    \\clearpage
    \\section{{厳密1 Hz候補検証}}
    GPU値は候補提案であり、採用権限は \\texttt{{scripts/solar\\_sim.py}} の固定policy・1 Hz replayにのみ置く。
    {tex_table(exact_display)}
    選択seedは \\texttt{{{tex_escape(exact_selection.get('selected_seed', ''))}}}、
    到着時間は {finite(selected_manifest.get('elapsed_hours')):.6f} h、終端SoCは
    {finite(selected_manifest.get('final_soc')):.6f}、2831 km SoCは {selected_soc_2831:.6f}、
    detail行数は {detail_rows:,} である。
    推定finish UTCは\\texttt{{{tex_escape(selected_finish_utc)}}}であり、各control stop閉鎖と
    finish締切の遅着秒数が0でなければ候補を不成立とする。
    {figure_fullsim}

    \\clearpage
    \\section{{メッシュ収束}}
    積分刻みは $1,0.5,0.2,0.1$ km、独立最適化した制御刻みは $5,2,1$ kmを比較する。
    最細分対で到着時刻差、終端SoC差、速度RMS差、予測実行同期の全条件を満たした場合のみ通過とする。
    {tex_table(mesh_display)}
    combined mesh gateは \\textbf{{{str(mesh_summary.get('mesh_gate_pass', False)).lower()}}} である。
    これは離散化収束の証明であり、連続非凸問題の数学的大域最適性証明ではない。

    \\section{{実測モデル再現ゲート}}
    conditional power RMSE={finite(metrics.get('battery_conditional_power_rmse_clean_w')):.3f} W、
    conditional voltage RMSE={finite(metrics.get('battery_conditional_voltage_rmse_clean_v')):.3f} V、
    end-to-end power RMSE={finite(metrics.get('end_to_end_power_rmse_clean_w')):.3f} W、
    end-to-end voltage RMSE={finite(metrics.get('end_to_end_voltage_rmse_clean_v')):.3f} V、
    25 km energy RMSE={finite(metrics.get('end_to_end_energy_error_25km_rmse_wh')):.3f} Whである。
    promotion gateは \\textbf{{{str(model_gate_pass).lower()}}} である。
    この値がfalseの場合、planner比較は研究用反実仮想であって運用保証ではない。
    {tex_table(promotion_display)}
    {tex_table(threshold_display)}

    \\subsection{{観測同期・DEM勾配の独立検証}}
    GNSS加速度はfilter=\\texttt{{{tex_escape(acceleration_fit.get('selected_filter_method', 'not selected'))}}}、
    window={finite(acceleration_fit.get('selected_filter_window_sec')):.3f} s、
    lag={finite(acceleration_fit.get('selected_lag_sec')):.3f} sを採択し、
    held-out day={acceleration_fit.get('holdout_day', 'N/A')}、検証RMSE比は
    {finite(acceleration_fit.get('validation_rmse_ratio')):.6f} である。
    DEM勾配はSavitzky--Golay平滑化幅
    {finite(grade_fit.get('selected_smoothing_window_km')):.3f} km、距離offset
    {finite(grade_fit.get('selected_distance_offset_km')):.3f} km、仮grade scale
    {finite(grade_fit.get('selected_provisional_grade_scale')):.6f}を候補探索し、
    held-out day={grade_fit.get('holdout_day', 'N/A')}、検証RMSE比は
    {finite(grade_fit.get('validation_rmse_ratio')):.6f} である。
    各補正は訓練RMSEだけでなく、未使用日のRMSEが設定上限を超えない場合にのみ採択する。

    \\subsection{{残差構造とSoC乖離開始地点}}
    battery-conditionalは観測パック電力を使う電池単体比較であり、車両モデルの正解ではない。
    ただしvehicleとの差は、車両負荷予測が長期積算へ与えた寄与を切り分ける診断になる。
    vehicle終端差は {finite(vehicle_divergence.get('terminal_signed_soc_difference')):.6f}、
    end-to-end終端差は {finite(end_divergence.get('terminal_signed_soc_difference')):.6f} である。
    初回2\\%乖離のvehicle距離は
    {vehicle_first_2pct_km:.3f} km、
    end-to-end距離は
    {end_first_2pct_km:.3f} kmである。
    {tex_table(residual_display)}
    {figure_residual}

    \\section{{再現性と限界}}
    すべてのseed、世代履歴、policy CSV、厳密ranking、1 Hz detail CSV、manifest、mesh比較CSVを保存する。
    複数seed一致とh-refinementは数値的信頼性を高めるが、有限回CEMから連続大域最適性は導けない。
    また外部気象と実車PV、GNSS勾配、非同期電力計測の誤差は車両固有係数と分離して扱う必要がある。

    \\section{{根拠文献}}
    \\begin{{thebibliography}}{{9}}
    \\bibitem{{cem}} P.-T. de Boer et al., A Tutorial on the Cross-Entropy Method,
    \\textit{{Annals of Operations Research}}, 2005, doi:10.1007/s10479-005-5724-z.
    \\bibitem{{mpc}} J. B. Rawlings, D. Q. Mayne, M. Diehl,
    \\textit{{Model Predictive Control: Theory, Computation, and Design}}, 2nd ed., 2020.
    \\bibitem{{mesh}} J. T. Betts, W. P. Huffman, Mesh refinement in direct transcription methods,
    \\textit{{Optimal Control Applications and Methods}}, 1998.
    \\bibitem{{solar}} D. Pudney, Critical Speed Control of a Solar Car,
    \\textit{{Optimization and Engineering}}, 2002.
    \\end{{thebibliography}}
    \\end{{document}}
    """
    tex_path = output_dir / "gpu_acceptance_and_fullsim_report.tex"
    tex_path.write_text(textwrap.dedent(tex).strip() + "\n", encoding="utf-8", newline="\n")
    for _ in range(2):
        import subprocess

        result = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", tex_path.name],
            cwd=output_dir,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"xelatex failed; inspect {tex_path.with_suffix('.log')}")
    return md_path, tex_path.with_suffix(".pdf")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--campaign-dir", type=Path, required=True)
    parser.add_argument("--acceptance-dir", type=Path, required=True)
    parser.add_argument("--fit-summary", type=Path, required=True)
    parser.add_argument("--promotion-gate", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    md_path, pdf_path = build_report(
        args.profile.resolve(),
        args.campaign_dir.resolve(),
        args.acceptance_dir.resolve(),
        args.fit_summary.resolve(),
        args.promotion_gate.resolve(),
        args.output_dir.resolve(),
    )
    print(json.dumps({"report_md": os.fspath(md_path), "report_pdf": os.fspath(pdf_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
