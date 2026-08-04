#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Dict

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_bwsc2025_fitted_package as fitpkg
import tune_upper_planner_weights as tuner


DEFAULT_SUFFIX = datetime.now().strftime("%Y%m%d")


def repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def latex_escape(text: str) -> str:
    repl = {
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
    out = str(text)
    for src, dst in repl.items():
        out = out.replace(src, dst)
    return out


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_repo_path(base: Path, raw: str) -> Path:
    candidate = Path(str(raw))
    if candidate.is_absolute():
        return candidate
    if str(candidate).startswith("project_packages/") or str(candidate).startswith("outputs/"):
        return (ROOT / candidate).resolve()
    return (base / candidate).resolve()


def set_nested(cfg: dict, dotted_key: str, value) -> None:
    parts = [part for part in str(dotted_key).split(".") if part]
    cur = cfg
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def mirror_and_write_profile(
    package_dir: Path,
    base_profile_yaml: Path,
    best_upper_cost_yaml: Path,
    tuned_cfg_overrides: Dict[str, object],
    output_suffix: str,
) -> tuple[Path, Dict[str, float]]:
    cfg = tuner.read_yaml(base_profile_yaml)
    best_payload = tuner.read_yaml(best_upper_cost_yaml)
    upper_cost = best_payload.get("upper_cost", best_payload)
    if not isinstance(upper_cost, dict) or not upper_cost:
        raise ValueError(f"upper_cost not found in {best_upper_cost_yaml}")

    tuner.mirror_legacy_weights(cfg, upper_cost)
    meta = cfg.setdefault("meta", {})
    meta["name"] = f"{package_dir.name}_final_selflearned"
    notes = meta.setdefault("notes", [])
    if isinstance(notes, list):
        notes.append(
            f"Final profile generated on {datetime.now().strftime('%Y-%m-%d')} by reusing the best upper-cost weights from autonomous self-learning."
        )

    sim_cfg = cfg.setdefault("simulation", {})
    sim_cfg["output_dir"] = f"project_packages/{package_dir.name}/outputs/prerace_final_selflearned"
    sim_cfg["output_prefix"] = f"{package_dir.name}_final_selflearned"
    sim_cfg["latest_manifest_json"] = f"project_packages/{package_dir.name}/outputs/prerace_final_selflearned/latest_simulation_run.json"
    for key, value in (tuned_cfg_overrides or {}).items():
        if str(key).startswith("mpc.") or str(key).startswith("model.") or str(key).startswith("simulation.") or str(key).startswith("runtime."):
            set_nested(cfg, str(key), value)

    output_profile_yaml = package_dir / f"profile_final_selflearned_{output_suffix}.yaml"
    tuner.write_yaml(output_profile_yaml, cfg)
    return output_profile_yaml, upper_cost


def run_solar_sim(profile_yaml: Path) -> dict:
    subprocess.run(
        [sys.executable, os_fspath(ROOT / "scripts" / "solar_sim.py"), "--profile_yaml", os_fspath(profile_yaml)],
        cwd=ROOT,
        check=True,
    )
    cfg = tuner.read_yaml(profile_yaml)
    sim_cfg = cfg.get("simulation", {}) if isinstance(cfg, dict) else {}
    manifest_path = resolve_repo_path(ROOT, str(sim_cfg.get("latest_manifest_json", "")))
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    return read_json(manifest_path)


def os_fspath(path: Path) -> str:
    return path.resolve().as_posix()


def load_motion_fit(fit_summary: dict) -> fitpkg.MotionFitResult:
    motion = fit_summary.get("motion_fit", {}) or {}
    return fitpkg.MotionFitResult(
        cda=float(motion["cda"]),
        crr=float(motion["crr"]),
        p_aux_w=float(motion["p_aux_w"]),
        grade_scale=float(motion["grade_scale"]),
        drive_eff_scale=float(motion["drive_eff_scale"]),
        headwind_gain=float(motion["headwind_gain"]),
        objective=float(motion.get("objective", 0.0)),
        power_rmse_w=float(motion.get("power_rmse_w", 0.0)),
        residual_sigma_w=float(motion.get("residual_sigma_w", 0.0)),
    )


def race_distance_info(fit_summary: dict) -> tuple[float, float]:
    payload = fit_summary.get("race_distance", {}) if isinstance(fit_summary, dict) else {}
    actual_retire_km = float(payload.get("actual_retire_km", 2831.0) or 2831.0)
    planning_full_course_km = float(payload.get("planning_full_course_km", fitpkg.OFFICIAL_CLASSIFIED_DISTANCE_KM) or fitpkg.OFFICIAL_CLASSIFIED_DISTANCE_KM)
    return actual_retire_km, planning_full_course_km


def regenerate_plan_products(package_dir: Path, profile_yaml: Path, fit_summary: dict, sim_manifest: dict) -> Dict[str, Path]:
    cfg = tuner.read_yaml(profile_yaml)
    paths = cfg.get("paths", {}) if isinstance(cfg, dict) else {}
    route_profile_csv = resolve_repo_path(package_dir, str(paths.get("route_profile_csv", "")))
    weather_csv = resolve_repo_path(package_dir, str(paths.get("observed_weather_csv", paths.get("forecast_csv", ""))))
    route_profile = pd.read_csv(route_profile_csv)
    weather_10min = pd.read_csv(weather_csv)
    motion_fit = load_motion_fit(fit_summary)
    sim_outputs = {
        "summary_json": resolve_repo_path(ROOT, str(sim_manifest["latest_manifest_json"])),
        "out_csv": resolve_repo_path(ROOT, str(sim_manifest["out_csv"])),
        "detail_csv": resolve_repo_path(ROOT, str(sim_manifest["detail_csv"])),
        "plan_csv": resolve_repo_path(ROOT, str(sim_manifest["plan_csv"])),
        "report_html": resolve_repo_path(ROOT, str(sim_manifest["report_html"])),
        "resolved_yaml": resolve_repo_path(ROOT, str(sim_manifest["resolved_yaml"])),
    }
    fitpkg.OUT_PACKAGE = package_dir
    fitpkg.PACKAGE_NAME = f"{package_dir.name}_final_selflearned"
    return fitpkg.generate_plan_products(profile_yaml, route_profile, weather_10min, motion_fit, motion_fit.residual_sigma_w, sim_outputs)


def render_plots(
    report_dir: Path,
    old_fit: dict,
    new_fit: dict,
    selflearn_summary: dict,
    final_summary: dict,
    *,
    actual_retire_km: float,
    planning_race_km: float,
    old_label: str,
    new_label: str,
) -> Dict[str, Path]:
    ensure_dir(report_dir)

    fit_compare_png = report_dir / "fit_metric_compare.png"
    fit_labels = ["power RMSE\nfit window [W]", "voltage RMSE\nfit window [V]", "replay final SoC\n[-]"]
    old_vals = [
        float(old_fit["validation_metrics"]["power_rmse_fit_window_w"]),
        float(old_fit["validation_metrics"]["voltage_rmse_fit_window_v"]),
        float(old_fit["validation_metrics"]["final_soc_pred"]),
    ]
    new_vals = [
        float(new_fit["validation_metrics"]["power_rmse_fit_window_w"]),
        float(new_fit["validation_metrics"]["voltage_rmse_fit_window_v"]),
        float(new_fit["validation_metrics"]["final_soc_pred"]),
    ]
    x = range(len(fit_labels))
    plt.figure(figsize=(8.8, 4.6))
    plt.bar([idx - 0.18 for idx in x], old_vals, width=0.36, label=f"{old_label} before refit", color="#94a3b8")
    plt.bar([idx + 0.18 for idx in x], new_vals, width=0.36, label=f"{new_label} reidentified", color="#0f766e")
    plt.xticks(list(x), fit_labels)
    plt.title("Model-fit metric comparison")
    plt.grid(True, axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(fit_compare_png, dpi=180)
    plt.close()

    planner_compare_png = report_dir / "planner_distance_compare.png"
    baseline = selflearn_summary["baseline_validation"]
    tuned = selflearn_summary["tuned_validation"]
    labels = ["baseline", "self-learned\n(old model)", "self-learned\n(new model)", "actual retire", "official finish"]
    vals = [
        float(baseline["final_distance_km"]),
        float(tuned["final_distance_km"]),
        float(final_summary["final_distance_km"]),
        float(actual_retire_km),
        float(planning_race_km),
    ]
    colors = ["#94a3b8", "#2563eb", "#0f766e", "#b45309", "#6b7280"]
    plt.figure(figsize=(8.8, 4.8))
    plt.bar(labels, vals, color=colors)
    plt.ylabel("distance [km]")
    plt.title("Whole-race distance comparison")
    for idx, val in enumerate(vals):
        plt.text(idx, val + 18.0, f"{val:.1f}", ha="center", va="bottom", fontsize=9)
    plt.tight_layout()
    plt.savefig(planner_compare_png, dpi=180)
    plt.close()

    return {
        "fit_compare_png": fit_compare_png,
        "planner_compare_png": planner_compare_png,
    }


def write_report(
    report_dir: Path,
    package_dir: Path,
    final_profile_yaml: Path,
    old_fit_summary_yaml: Path,
    new_fit_summary_yaml: Path,
    old_fit: dict,
    new_fit: dict,
    selflearn_summary: dict,
    final_summary: dict,
    best_upper_cost_yaml: Path,
    final_plan_outputs: Dict[str, Path],
    manifest_paths: Dict[str, Path],
    plots: Dict[str, Path],
) -> tuple[Path, Path]:
    ensure_dir(report_dir)
    md_path = report_dir / "bwsc2025_reidentified_final_report.md"
    tex_path = report_dir / "bwsc2025_reidentified_final_report.tex"

    baseline = selflearn_summary["baseline_validation"]
    tuned = selflearn_summary["tuned_validation"]
    actual_retire_km, planning_race_km = race_distance_info(new_fit)
    final_gap_retire = actual_retire_km - float(final_summary["final_distance_km"])
    final_gap_finish = planning_race_km - float(final_summary["final_distance_km"])
    distance_gain_vs_baseline = float(final_summary["final_distance_km"]) - float(baseline["final_distance_km"])
    distance_gain_vs_old_tuned = float(final_summary["final_distance_km"]) - float(tuned["final_distance_km"])
    old_label = old_fit_summary_yaml.parent.parent.parent.name
    new_label = package_dir.name

    current_maps_md = manifest_paths["markdown"]
    current_scalars_csv = manifest_paths["scalars_csv"]

    md_text = f"""# BWSC2025 Reidentified Final Report

## Summary

- final profile: `{repo_relative(final_profile_yaml)}`
- best upper-cost YAML reused from self-learning: `{repo_relative(best_upper_cost_yaml)}`
- final whole-race distance: `{float(final_summary['final_distance_km']):.3f} km`
- final SoC: `{float(final_summary['final_soc']):.4f}`
- gap to actual retire point {actual_retire_km:.1f} km: `{final_gap_retire:.3f} km`
- gap to official finish {planning_race_km:.1f} km: `{final_gap_finish:.3f} km`
- gain vs baseline planner: `{distance_gain_vs_baseline:.3f} km`
- gain vs self-learned old-model planner: `{distance_gain_vs_old_tuned:.3f} km`

## Key fit comparison

- old fitted package summary: `{repo_relative(old_fit_summary_yaml)}`
- reidentified package summary: `{repo_relative(new_fit_summary_yaml)}`
- old replay power RMSE (fit window): `{float(old_fit['validation_metrics']['power_rmse_fit_window_w']):.3f} W`
- new replay power RMSE (fit window): `{float(new_fit['validation_metrics']['power_rmse_fit_window_w']):.3f} W`
- old replay voltage RMSE (fit window): `{float(old_fit['validation_metrics']['voltage_rmse_fit_window_v']):.3f} V`
- new replay voltage RMSE (fit window): `{float(new_fit['validation_metrics']['voltage_rmse_fit_window_v']):.3f} V`

## Final outputs

- final simulation manifest: `{repo_relative(resolve_repo_path(ROOT, str(final_summary['latest_manifest_json'])))}`
- final simulation CSV: `{repo_relative(resolve_repo_path(ROOT, str(final_summary['out_csv'])))}`
- final simulation detail CSV: `{repo_relative(resolve_repo_path(ROOT, str(final_summary['detail_csv'])))}`
- final upper/lower plan CSVs: `{repo_relative(final_plan_outputs['upper_three_csv'])}`, `{repo_relative(final_plan_outputs['lower_three_csv'])}`
- current maps and coefficients: `{repo_relative(current_maps_md)}`
- current scalar coefficients CSV: `{repo_relative(current_scalars_csv)}`
- report PDF: `{repo_relative(tex_path.with_suffix('.pdf'))}`
"""
    md_path.write_text(md_text, encoding="utf-8", newline="\n")

    refs = "\n".join(
        f"  \\item {latex_escape(item['label'])}: \\url{{{item['url']}}}"
        for item in tuner.LITERATURE
    )
    tex = f"""
\\documentclass[a4paper,11pt]{{article}}
\\usepackage[top=16mm,bottom=20mm,left=16mm,right=16mm]{{geometry}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\setmainfont{{Times New Roman}}
\\setCJKmainfont{{Yu Gothic}}
\\setmonofont{{Consolas}}
\\usepackage{{graphicx}}
\\usepackage{{booktabs}}
\\usepackage{{amsmath}}
\\usepackage{{float}}
\\usepackage[unicode]{{hyperref}}
\\hypersetup{{colorlinks=true,linkcolor=blue,urlcolor=blue}}
\\title{{BWSC2025 Model Re-identification and Final Simulation Report}}
\\author{{solar\\_ws0129-main}}
\\date{{{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}}
\\begin{{document}}
\\maketitle

\\section{{結論}}
最終 profile は \\path{{{repo_relative(final_profile_yaml)}}} である。
これは \\path{{{repo_relative(best_upper_cost_yaml)}}} の self-learning 最良上位重みを、
再同定後 package にそのまま移植して再 simulation したものである。

最終 whole-race simulation の到達距離は {float(final_summary['final_distance_km']):.3f} km、
終端 SoC は {float(final_summary['final_soc']):.4f}、最小 SoC は {float(final_summary['min_soc']):.4f}、
実走リタイア地点 2831 km に対する残差は {final_gap:.3f} km である。

\\section{{今回の再同定で何を変えたか}}
今回の主変更点は、whole-race replay 上の joint refine が voltage 側だけを優先して
motion 側 power fit を壊してしまうことを防ぐため、以下を導入した点である。
\\begin{{itemize}}
  \\item random multi-start による粗い global seed 探索
  \\item stagewise 解からの逸脱に対する弱い anchor penalty
  \\item power RMSE と power bias を含む joint objective への再重み付け
  \\item power RMSE を悪化させる候補を reject する acceptance 条件
\\end{{itemize}}

その結果、{latex_escape(new_label)} では joint candidate は採用されず、stagewise 側
$(CdA, Crr, P_{{aux}}, E_{{nom}})$ がそのまま残った。すなわち、
power side を壊して保守化するモデルを package に書き込まないようにした。

\\section{{fit 指標比較}}
\\begin{{table}}[H]
\\centering
\\begin{{tabular}}{{lrr}}
\\toprule
metric & {latex_escape(old_label)} & {latex_escape(new_label)} \\\\
\\midrule
power RMSE fit-window [W] & {float(old_fit['validation_metrics']['power_rmse_fit_window_w']):.3f} & {float(new_fit['validation_metrics']['power_rmse_fit_window_w']):.3f} \\\\
voltage RMSE fit-window [V] & {float(old_fit['validation_metrics']['voltage_rmse_fit_window_v']):.3f} & {float(new_fit['validation_metrics']['voltage_rmse_fit_window_v']):.3f} \\\\
replay final SoC [-] & {float(old_fit['validation_metrics']['final_soc_pred']):.4f} & {float(new_fit['validation_metrics']['final_soc_pred']):.4f} \\\\
CdA [-] & {float(old_fit['motion_fit']['cda']):.6f} & {float(new_fit['motion_fit']['cda']):.6f} \\\\
Crr [-] & {float(old_fit['motion_fit']['crr']):.6f} & {float(new_fit['motion_fit']['crr']):.6f} \\\\
P\\_aux [W] & {float(old_fit['motion_fit']['p_aux_w']):.3f} & {float(new_fit['motion_fit']['p_aux_w']):.3f} \\\\
E\\_nom [Wh] & {float(old_fit['battery_fit']['e_nom_wh']):.3f} & {float(new_fit['battery_fit']['e_nom_wh']):.3f} \\\\
\\bottomrule
\\end{{tabular}}
\\end{{table}}

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.92\\linewidth]{{{latex_escape(plots['fit_compare_png'].name)}}}
  \\caption{{旧モデルと再同定モデルの fit 指標比較}}
\\end{{figure}}

\\section{{planner 改善量}}
baseline planner は {float(baseline['final_distance_km']):.3f} km、
旧モデル上の self-learning 最良候補は {float(tuned['final_distance_km']):.3f} km、
再同定後モデルに同重みを適用した最終 simulation は {float(final_summary['final_distance_km']):.3f} km である。
従って、baseline に対しては {distance_gain_vs_baseline:.3f} km の改善、
旧 self-learned 結果に対しては {distance_gain_vs_old_tuned:.3f} km の改善である。

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.92\\linewidth]{{{latex_escape(plots['planner_compare_png'].name)}}}
  \\caption{{baseline, 旧 self-learning, 再同定後最終 simulation の距離比較}}
\\end{{figure}}

\\section{{現在使用している主マップ・係数}}
現在使用中の一覧は \\path{{{repo_relative(current_maps_md)}}} と
\\path{{{repo_relative(current_scalars_csv)}}} に保存した。
主 scalar は以下である。
\\begin{{itemize}}
  \\item mass $m = {float(new_fit['fit_setup']['profile_consistency_fixes']['fixed_mass_kg']):.1f}$ kg
  \\item $CdA = {float(new_fit['motion_fit']['cda']):.6f}$
  \\item $Crr = {float(new_fit['motion_fit']['crr']):.6f}$
  \\item $P_{{aux}} = {float(new_fit['motion_fit']['p_aux_w']):.3f}$ W
  \\item $panel\\_gain = {float(new_fit['pv_fit']['panel_gain']):.6f}$
  \\item $E_{{nom}} = {float(new_fit['battery_fit']['e_nom_wh']):.3f}$ Wh
  \\item $rint\\_scale = {float(new_fit['battery_fit']['rint_scale']):.6f}$
  \\item $rline = {float(new_fit['battery_fit']['r_line_ohm']):.6f}$ $\\Omega$
  \\item $eta\\_charge = {float(new_fit['battery_fit']['eta_charge']):.6f}$
  \\item $grade\\_scale = {float(new_fit['motion_fit']['grade_scale']):.6f}$
  \\item $drive\\_eff\\_scale = {float(new_fit['motion_fit']['drive_eff_scale']):.6f}$
  \\item $headwind\\_gain = {float(new_fit['motion_fit']['headwind_gain']):.6f}$
\\end{{itemize}}

\\section{{出力ファイル}}
\\begin{{itemize}}
  \\item final profile: \\path{{{repo_relative(final_profile_yaml)}}}
  \\item fit summary: \\path{{{repo_relative(new_fit_summary_yaml)}}}
  \\item final simulation csv: \\path{{{repo_relative(resolve_repo_path(ROOT, str(final_summary['out_csv'])) )}}}
  \\item final detail csv: \\path{{{repo_relative(resolve_repo_path(ROOT, str(final_summary['detail_csv'])) )}}}
  \\item final upper three plans: \\path{{{repo_relative(final_plan_outputs['upper_three_csv'])}}}
  \\item final lower three plans: \\path{{{repo_relative(final_plan_outputs['lower_three_csv'])}}}
  \\item current maps and coefficients: \\path{{{repo_relative(current_maps_md)}}}
\\end{{itemize}}

\\section{{参考}}
この self-learning 側設計と MPC cost tuning の根拠として、今回 package に同梱したレポートと
以下の literature を参照した。
\\begin{{itemize}}
{refs}
\\end{{itemize}}

\\end{{document}}
"""
    tex_path.write_text(textwrap.dedent(tex).strip() + "\n", encoding="utf-8", newline="\n")
    return md_path, tex_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-name", required=True)
    ap.add_argument("--selflearn-summary-json", required=True)
    ap.add_argument("--old-fit-summary-yaml", required=True)
    ap.add_argument("--output-suffix", default=DEFAULT_SUFFIX)
    args = ap.parse_args()

    package_dir = (ROOT / "project_packages" / str(args.package_name)).resolve()
    if not package_dir.exists():
        raise FileNotFoundError(package_dir)
    base_profile_yaml = package_dir / "profile.yaml"
    new_fit_summary_yaml = package_dir / "outputs" / "identification" / f"{package_dir.name}_fit_summary.yaml"
    selflearn_summary_json = Path(args.selflearn_summary_json).resolve()
    old_fit_summary_yaml = Path(args.old_fit_summary_yaml).resolve()
    old_label = old_fit_summary_yaml.parent.parent.parent.name
    new_label = package_dir.name

    new_fit = tuner.read_yaml(new_fit_summary_yaml)
    old_fit = tuner.read_yaml(old_fit_summary_yaml)
    selflearn_summary = read_json(selflearn_summary_json)
    best_upper_cost_yaml = Path(selflearn_summary["best_upper_cost_yaml"]).resolve()
    tuned_cfg_overrides = {}
    tuned_validation = selflearn_summary.get("tuned_validation", {}) or {}
    scenario_results = tuned_validation.get("scenario_results", []) if isinstance(tuned_validation, dict) else []
    if scenario_results:
        tuned_cfg_overrides = scenario_results[0].get("cfg_overrides", {}) or {}

    final_profile_yaml, upper_cost = mirror_and_write_profile(
        package_dir,
        base_profile_yaml,
        best_upper_cost_yaml,
        tuned_cfg_overrides,
        str(args.output_suffix),
    )
    final_summary = run_solar_sim(final_profile_yaml)
    final_plan_outputs = regenerate_plan_products(package_dir, final_profile_yaml, new_fit, final_summary)

    report_dir = package_dir / "outputs" / "final_reidentified_report" / str(args.output_suffix)
    ensure_dir(report_dir)
    manifest_paths = tuner.build_current_asset_manifests(final_profile_yaml, new_fit, report_dir)
    actual_retire_km, planning_race_km = race_distance_info(new_fit)
    plots = render_plots(
        report_dir,
        old_fit,
        new_fit,
        selflearn_summary,
        final_summary,
        actual_retire_km=actual_retire_km,
        planning_race_km=planning_race_km,
        old_label=old_label,
        new_label=new_label,
    )
    md_path, tex_path = write_report(
        report_dir,
        package_dir,
        final_profile_yaml,
        old_fit_summary_yaml,
        new_fit_summary_yaml,
        old_fit,
        new_fit,
        selflearn_summary,
        final_summary,
        best_upper_cost_yaml,
        final_plan_outputs,
        manifest_paths,
        plots,
    )
    pdf_path = fitpkg.compile_tex(tex_path)

    summary_payload = {
        "package_dir": os_fspath(package_dir),
        "final_profile_yaml": os_fspath(final_profile_yaml),
        "best_upper_cost_yaml": os_fspath(best_upper_cost_yaml),
        "final_sim_manifest_json": os_fspath(resolve_repo_path(ROOT, str(final_summary["latest_manifest_json"]))),
        "final_sim_csv": os_fspath(resolve_repo_path(ROOT, str(final_summary["out_csv"]))),
        "final_sim_detail_csv": os_fspath(resolve_repo_path(ROOT, str(final_summary["detail_csv"]))),
        "final_upper_three_csv": os_fspath(final_plan_outputs["upper_three_csv"]),
        "final_lower_three_csv": os_fspath(final_plan_outputs["lower_three_csv"]),
        "current_maps_and_coefficients_md": os_fspath(manifest_paths["markdown"]),
        "current_scalar_coefficients_csv": os_fspath(manifest_paths["scalars_csv"]),
        "report_md": os_fspath(md_path),
        "report_tex": os_fspath(tex_path),
        "report_pdf": os_fspath(pdf_path),
        "final_distance_km": float(final_summary["final_distance_km"]),
        "final_soc": float(final_summary["final_soc"]),
        "upper_cost": upper_cost,
    }
    out_json = report_dir / "finalized_locations.json"
    out_json.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary_payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
