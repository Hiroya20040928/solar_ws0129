#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import subprocess
import textwrap
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "outputs" / "reports" / "mpc_refinement_20260706"

CASES = [
    {
        "key": "recommended",
        "label": "Recommended",
        "profile": ROOT / "project_packages" / "bwsc2025_fitted_mle3" / "profile_mpc_refined_recommended_20260706.yaml",
        "summary": ROOT / "outputs" / "tmp_mpc_orig_validation" / "summary.json",
        "sim": ROOT / "outputs" / "tmp_mpc_orig_validation" / "sim.csv",
        "detail": ROOT / "outputs" / "tmp_mpc_orig_validation" / "sim_detail.csv",
        "note": "現行重みを保ちつつ、上位プランナだけ全レース視界化した推奨案。",
    },
    {
        "key": "balanced",
        "label": "Balanced",
        "profile": ROOT / "project_packages" / "bwsc2025_fitted_mle3" / "profile_mpc_refined_balanced_20260706.yaml",
        "summary": ROOT / "outputs" / "tmp_mpc_balanced_validation" / "summary.json",
        "sim": ROOT / "outputs" / "tmp_mpc_balanced_validation" / "sim.csv",
        "detail": ROOT / "outputs" / "tmp_mpc_balanced_validation" / "sim_detail.csv",
        "note": "距離優先で軽い物理項を追加した案。到達距離は伸びたが振動抑制は弱い。",
    },
    {
        "key": "seed",
        "label": "Seed-heavy",
        "profile": ROOT / "project_packages" / "bwsc2025_fitted_mle3" / "profile_mpc_refined_seed_20260706.yaml",
        "summary": ROOT / "outputs" / "tmp_mpc_seed_validation" / "summary.json",
        "sim": ROOT / "outputs" / "tmp_mpc_seed_validation" / "sim.csv",
        "detail": ROOT / "outputs" / "tmp_mpc_seed_validation" / "sim_detail.csv",
        "note": "予備SOCとエネルギー項を強く入れた案。2025 replay では過度に保守的。",
    },
    {
        "key": "light",
        "label": "Light-smooth",
        "profile": ROOT / "project_packages" / "bwsc2025_fitted_mle3" / "profile_mpc_refined_light_20260706.yaml",
        "summary": ROOT / "outputs" / "tmp_mpc_light_validation" / "summary.json",
        "sim": ROOT / "outputs" / "tmp_mpc_light_validation" / "sim.csv",
        "detail": ROOT / "outputs" / "tmp_mpc_light_validation" / "sim_detail.csv",
        "note": "滑らか化だけを弱く足した案。距離低下が残った。",
    },
]

REFERENCE_URLS = [
    ("Howlett et al. 1997", "https://doi.org/10.1093/imaman/8.1.59"),
    ("Pudney and Howlett 2002", "https://link.springer.com/article/10.1023/A:1020907101234"),
    ("Merino and Duarte-Mermoud 2016", "https://repositorio.uchile.cl/handle/2250/140895"),
    ("Atmaca 2015", "https://doi.org/10.3906/elk-1212-37"),
    ("Oosthuizen et al. 2019", "https://ieeexplore.ieee.org/document/8918287"),
]


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


def compile_tex(tex_path: Path) -> Path:
    pdf_path = tex_path.with_suffix(".pdf")
    for _ in range(2):
        subprocess.run(
            ["xelatex", "-interaction=nonstopmode", tex_path.name],
            cwd=tex_path.parent,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return pdf_path


def repo_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except Exception:
        return path.as_posix()


def speed_series(df: pd.DataFrame) -> pd.Series:
    if "v_exec_kmh" in df.columns:
        return df["v_exec_kmh"].astype(float)
    if "v_cmd_kmh" in df.columns:
        return df["v_cmd_kmh"].astype(float)
    return pd.Series([0.0] * len(df), dtype=float)


def load_case(case: dict) -> dict:
    summary = json.loads(case["summary"].read_text(encoding="utf-8"))
    sim = pd.read_csv(case["sim"])
    detail = pd.read_csv(case["detail"])
    sim_speed = speed_series(sim)
    dv = sim_speed.diff().abs().dropna()
    current_rms_a = math.sqrt(float((detail["I"] ** 2).mean())) if len(detail) else 0.0
    pack_slew_rms_kw = math.sqrt(float(((detail["P_pack"].diff().dropna() / 1000.0) ** 2).mean())) if len(detail) >= 2 else 0.0
    high_speed_h = float((sim_speed >= 85.0).sum()) * (900.0 / 3600.0)
    return {
        **case,
        "summary_payload": summary,
        "sim_df": sim,
        "detail_df": detail,
        "final_distance_km": float(summary["final_distance_km"]),
        "mean_abs_dv_kmh": float(dv.mean()) if len(dv) else 0.0,
        "p95_abs_dv_kmh": float(dv.quantile(0.95)) if len(dv) else 0.0,
        "current_rms_a": current_rms_a,
        "pack_slew_rms_kw": pack_slew_rms_kw,
        "high_speed_h": high_speed_h,
        "min_soc": float(summary["min_soc"]),
        "final_soc": float(summary["final_soc"]),
        "cpu_sec": float(summary["cpu_sec"]),
    }


def render_plots(cases: list[dict]) -> dict[str, Path]:
    ensure_dir(OUT_DIR)
    labels = [case["label"] for case in cases]
    distance_vals = [case["final_distance_km"] for case in cases]
    p95_vals = [case["p95_abs_dv_kmh"] for case in cases]

    plt.figure(figsize=(8, 4.5))
    plt.bar(labels, distance_vals, color=["#0f766e", "#2563eb", "#b45309", "#7c3aed"])
    plt.ylabel("final distance [km]")
    plt.title("Whole-race replay distance")
    for idx, val in enumerate(distance_vals):
        plt.text(idx, val + 15.0, f"{val:.0f}", ha="center", va="bottom", fontsize=9)
    distance_png = OUT_DIR / "distance_compare.png"
    plt.tight_layout()
    plt.savefig(distance_png, dpi=160)
    plt.close()

    plt.figure(figsize=(8, 4.5))
    plt.scatter(p95_vals, distance_vals, s=80, color="#0f766e")
    for case in cases:
        plt.annotate(case["label"], (case["p95_abs_dv_kmh"], case["final_distance_km"]), xytext=(6, 4), textcoords="offset points")
    plt.xlabel("p95 abs speed-step [km/h]")
    plt.ylabel("final distance [km]")
    plt.title("Distance vs oscillation")
    plt.grid(True, alpha=0.25)
    distance_vs_osc_png = OUT_DIR / "distance_vs_oscillation.png"
    plt.tight_layout()
    plt.savefig(distance_vs_osc_png, dpi=160)
    plt.close()

    any_exec = any("v_exec_kmh" in case["sim_df"].columns for case in cases)
    plt.figure(figsize=(9, 4.8))
    for case in cases:
        sim = case["sim_df"]
        plt.plot(sim.index, speed_series(sim), linewidth=1.0, label=case["label"])
    plt.xlabel("simulation step")
    plt.ylabel("executed speed [km/h]" if any_exec else "speed command [km/h]")
    plt.title("Speed execution history" if any_exec else "Speed command history")
    plt.grid(True, alpha=0.25)
    plt.legend()
    speed_png = OUT_DIR / "speed_history_compare.png"
    plt.tight_layout()
    plt.savefig(speed_png, dpi=160)
    plt.close()

    return {
        "distance_png": distance_png,
        "distance_vs_osc_png": distance_vs_osc_png,
        "speed_png": speed_png,
    }


def write_markdown(cases: list[dict], plots: dict[str, Path]) -> Path:
    md_path = OUT_DIR / "mpc_refinement_report.md"
    rows = [
        "| Case | Final distance [km] | Mean |dv| [km/h] | p95 |dv| [km/h] | Current RMS [A] | High-speed [h] | Note |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for case in cases:
        rows.append(
            f"| {case['label']} | {case['final_distance_km']:.1f} | {case['mean_abs_dv_kmh']:.2f} | {case['p95_abs_dv_kmh']:.2f} | "
            f"{case['current_rms_a']:.2f} | {case['high_speed_h']:.2f} | {case['note']} |"
        )
    refs = "\n".join(f"- [{name}]({url})" for name, url in REFERENCE_URLS)
    text = f"""# MPC Refinement Report

## Summary

The recommended profile is `{repo_rel(cases[0]['profile'])}`.

The strongest improvement actually adopted in the recommended setup is:

- Accept the best finite L-BFGS-B iterate even when the solver stops at `maxiter`.
- Switch the upper planner from a 200 km fixed horizon to an `adaptive_full_race` horizon over the remaining race.
- Keep the original cost weights for the recommended profile, because the heavier energy-reserve terms reduced replay distance too much on BWSC2025.

## Validation Table

{chr(10).join(rows)}

## Literature-Grounded Additions Implemented in Code

- Optional kinetic-energy penalty `w_kinetic_pos`
- Optional pack-power slew penalty `w_pack_power_slew`
- Optional uncertainty reserve penalty `w_uncertainty_reserve`

These are implemented in `mpc_solarcar/upper_cost.py` and are fully YAML-configurable, but the BWSC2025 replay suggests they must be kept weak unless the weather/stop model is improved further.

## References

{refs}

## Output Files

- PDF: `{repo_rel(OUT_DIR / 'mpc_refinement_report.pdf')}`
- TeX: `{repo_rel(OUT_DIR / 'mpc_refinement_report.tex')}`
- Distance plot: `{repo_rel(plots['distance_png'])}`
- Speed plot: `{repo_rel(plots['speed_png'])}`
"""
    md_path.write_text(text, encoding="utf-8", newline="\n")
    return md_path


def write_tex(cases: list[dict], plots: dict[str, Path]) -> Path:
    table_rows = []
    for case in cases:
        table_rows.append(
            f"{latex_escape(case['label'])} & {case['final_distance_km']:.1f} & {case['mean_abs_dv_kmh']:.2f} & "
            f"{case['p95_abs_dv_kmh']:.2f} & {case['current_rms_a']:.2f} & {case['high_speed_h']:.2f} \\\\"
        )
    refs = "\n".join(
        f"  \\item {latex_escape(name)}: \\url{{{url}}}" for name, url in REFERENCE_URLS
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
\\title{{BWSC2025 MPC Refinement Report}}
\\author{{solar\\_ws0129-main}}
\\date{{{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}}
\\begin{{document}}
\\maketitle

\\section{{Executive Summary}}
The recommended profile is \\path{{{repo_rel(cases[0]['profile'])}}}.
This recommendation keeps the original 2025 fitted weight set, but changes the upper planner horizon to
\\texttt{{adaptive\\_full\\_race}} and relies on the code-level solver fix that now keeps the best finite iterate
even when L-BFGS-B stops at \\texttt{{maxiter}}.

\\section{{Implemented Controller Changes}}
The codebase now supports the following optional upper-cost terms:
\\[
J=\\sum_k \\left(
w_t\\Delta t_k +
w_I I_k^2\\Delta t_k +
w_{{kin}} E^{{kin,+}}_k +
w_{{slew}}\\Delta P_{{pack,k}}^2 +
w_{{quartic}} (v_k/v_s)^4\\Delta t_k +
w_{{unc}}\\phi(z^{{res}}_k-z_{{k+1}})
\\right) + J_{{constraint}}
\\]
where $E^{{kin,+}}_k=\\max\\{{0, \\tfrac{{1}}{{2}}m(v_k^2-v_{{k-1}}^2)\\}}/3600$ and
$\\phi(x)=\\max(x,0)^2$.

These terms were added because the literature consistently points to three needs:
first, long-horizon solar-car planners must avoid unnecessary speed variation;
second, acceleration-related energy should not be ignored;
third, the optimizer should be re-run in closed loop while acknowledging growing forecast uncertainty.

\\section{{Replay Comparison}}
\\begin{{table}}[H]
\\centering
\\begin{{tabular}}{{lrrrrr}}
\\toprule
case & distance [km] & mean $|\\Delta v|$ & p95 $|\\Delta v|$ & $I_{{rms}}$ [A] & high-speed [h] \\\\
\\midrule
{chr(10).join(table_rows)}
\\bottomrule
\\end{{tabular}}
\\end{{table}}

The replay results show that the heavier energy-reserve variants were too conservative for the current BWSC2025 weather/stop replay model.
The best practical tradeoff was therefore to adopt the full-race horizon and solver fix first, while leaving the original fitted weight set in place for the recommended profile.

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.82\\linewidth]{{{latex_escape(plots['distance_png'].name)}}}
  \\caption{{whole-race replay distance comparison}}
\\end{{figure}}

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.82\\linewidth]{{{latex_escape(plots['distance_vs_osc_png'].name)}}}
  \\caption{{distance versus oscillation tradeoff}}
\\end{{figure}}

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.9\\linewidth]{{{latex_escape(plots['speed_png'].name)}}}
  \\caption{{speed command histories for the tested profiles}}
\\end{{figure}}

\\section{{Adopted Files}}
\\begin{{itemize}}
  \\item recommended profile: \\path{{{repo_rel(cases[0]['profile'])}}}
  \\item balanced profile: \\path{{{repo_rel(cases[1]['profile'])}}}
  \\item seed-heavy profile: \\path{{{repo_rel(cases[2]['profile'])}}}
  \\item light-smooth profile: \\path{{{repo_rel(cases[3]['profile'])}}}
  \\item core implementation: \\path{{{repo_rel(ROOT / 'mpc_solarcar' / 'upper_cost.py')}}}
  \\item upper planner node: \\path{{{repo_rel(ROOT / 'mpc_solarcar' / 'mpc_node.py')}}}
  \\item simulator: \\path{{{repo_rel(ROOT / 'scripts' / 'solar_sim.py')}}}
\\end{{itemize}}

\\section{{References}}
\\begin{{enumerate}}
{refs}
\\end{{enumerate}}

\\end{{document}}
"""
    tex_path = OUT_DIR / "mpc_refinement_report.tex"
    tex_path.write_text(textwrap.dedent(tex).strip() + "\n", encoding="utf-8", newline="\n")
    return tex_path


def main() -> None:
    ensure_dir(OUT_DIR)
    cases = [load_case(case) for case in CASES]
    plots = render_plots(cases)
    write_markdown(cases, plots)
    tex_path = write_tex(cases, plots)
    compile_tex(tex_path)
    print(json.dumps({
        "report_dir": str(OUT_DIR),
        "report_tex": str(tex_path),
        "report_pdf": str(tex_path.with_suffix(".pdf")),
        "report_md": str(OUT_DIR / "mpc_refinement_report.md"),
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
