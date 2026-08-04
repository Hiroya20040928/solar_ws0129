#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if os.fspath(ROOT) not in sys.path:
    sys.path.insert(0, os.fspath(ROOT))

from mpc_solarcar.upper_cost import active_upper_cost_terms, load_upper_cost_config
from mpc_solarcar.upper_horizon import build_upper_distance_horizon
from tune_upper_planner_weights import upper_cost_specs

DEFAULT_PROFILE = ROOT / "project_packages" / "bwsc2025_fitted_mle19_energywindow_inertia" / "profile.yaml"

LITERATURE = [
    {
        "label": "Howlett, Pudney, Tarnopolskaya, Gates (1997)",
        "title": "Optimal driving strategy for a solar car on a level road",
        "url": "https://academic.oup.com/imaman/article-abstract/8/1/59/711668",
        "reason": "太陽電力と蓄電効率を考慮したとき、最適戦略は不要な速度上下ではなく、基本的に速度保持型になることを示す。",
    },
    {
        "label": "Pudney (2002)",
        "title": "Critical Speed Control of a Solar Car",
        "url": "https://link.springer.com/article/10.1023/A%3A1020907101234",
        "reason": "有限距離でも、ほとんどの区間では critical speed 近傍のゆっくり変わる速度が望ましいことを示す。",
    },
    {
        "label": "de Boer et al. (2005)",
        "title": "A Tutorial on the Cross-Entropy Method",
        "url": "https://people.smp.uq.edu.au/DirkKroese/ps/aortut.pdf",
        "reason": "非凸・微分不親和な探索空間に対して、elite 集団から分布を更新する CEM の標準的整理。",
    },
    {
        "label": "Bertsekas (2024)",
        "title": "Model Predictive Control and Reinforcement Learning: A Unified Framework Based on Dynamic Programming",
        "url": "https://web.mit.edu/dimitrib/www/IFAC_Overview_Paper_2024.pdf",
        "reason": "MPC と offline learning の役割分担を、offline training と online play の統合構造として整理。",
    },
    {
        "label": "Zarrouki, Spanakakis, Betz (2024)",
        "title": "A Safe Reinforcement Learning driven Weights-varying Model Predictive Control for Autonomous Vehicle Motion Control",
        "url": "https://ieeexplore.ieee.org/document/10588747/",
        "reason": "MPC 重みを RL 的に調整する際、自由連続空間よりも安全な制限空間で学習させるべきことを示す。",
    },
]


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def repo_rel(path: Path) -> str:
    return os.path.relpath(path, ROOT).replace("\\", "/")


def compile_tex(tex_path: Path) -> Path:
    pdf_path = tex_path.with_suffix(".pdf")
    for _ in range(2):
        subprocess.run(
            ["xelatex", "-interaction=nonstopmode", tex_path.name],
            cwd=tex_path.parent,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    return pdf_path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.fspath(DEFAULT_PROFILE))
    args = ap.parse_args()

    profile_yaml = Path(args.profile).resolve()
    package_dir = profile_yaml.parent
    report_dir = package_dir / "outputs" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)

    profile = read_yaml(profile_yaml)
    manifest = read_yaml(package_dir / "data" / "identification" / "identification_manifest.yaml")
    fit_summary = read_yaml(package_dir / "outputs" / "identification" / f"{package_dir.name}_generic_fit_summary.yaml")

    mpc = profile.get("mpc", {})
    model = profile.get("model", {})
    evidence = manifest.get("evidence", {})
    grounded = manifest.get("grounded_sources", {})
    upper_cost_cfg = load_upper_cost_config(mpc, legacy=mpc)
    active_terms = active_upper_cost_terms(upper_cost_cfg, threshold=1.0e-4)
    active_terms_label = ", ".join(sorted(active_terms.keys()))
    active_terms_tex = r",\allowbreak{} ".join(
        term.replace("_", r"\_") for term in sorted(active_terms.keys())
    )
    tune_specs = upper_cost_specs(
        upper_cost_cfg,
        include_progress_terms=bool((mpc.get("upper_cost", {}) or {}).get("w_progress_lag", 0.0)) or bool((mpc.get("upper_cost", {}) or {}).get("w_progress_terminal_lag", 0.0)),
        include_uncertainty_term=bool((mpc.get("upper_cost", {}) or {}).get("w_uncertainty_reserve", 0.0)),
        include_terminal_term=float(mpc.get("soc_finish_target", -1.0) or -1.0) > 0.0,
    )
    horizon = build_upper_distance_horizon(
        mode=str(mpc.get("upper_horizon_mode", mpc.get("upper_mode", "adaptive_full_race"))),
        s0_km=float((profile.get("simulation", {}) or {}).get("start_s_km", 0.0)),
        race_km=float(mpc.get("race_km", 0.0) or 0.0),
        ds_km=float(mpc.get("upper_ds_km", 10.0) or 10.0),
        horizon_km=float(mpc.get("upper_horizon_km", mpc.get("race_km", 0.0)) or 10.0),
        max_steps=int(mpc.get("upper_max_steps", 1) or 1),
        ctrl_km=float(mpc.get("upper_ctrl_km", mpc.get("upper_ds_km", 10.0)) or 10.0),
        adaptive_min_ds_km=float(mpc.get("upper_adaptive_min_ds_km", mpc.get("upper_ds_km", 10.0)) or 10.0),
        adaptive_max_ds_km=float(mpc.get("upper_adaptive_max_ds_km", mpc.get("upper_horizon_km", 10.0)) or 10.0),
        adaptive_growth=float(mpc.get("upper_adaptive_growth", 1.2) or 1.2),
    )
    upper_prediction_dim = int(len(horizon.ds_seq_km))
    upper_control_dim = int(len(horizon.ctrl_s_km))
    actual_event_yaml = package_dir / str((manifest.get("inputs", {}) or {}).get("actual_event_yaml", ""))
    actual_event_payload = read_yaml(actual_event_yaml) if actual_event_yaml.exists() else {}
    actual_event_count = len(actual_event_payload.get("events", [])) if isinstance(actual_event_payload.get("events", []), list) else 0

    md_lines = [
        "# Controller Upgrade Worksheet",
        "",
        f"- profile: `{repo_rel(profile_yaml)}`",
        f"- manifest: `{repo_rel(package_dir / 'data' / 'identification' / 'identification_manifest.yaml')}`",
        "",
        "## 1. 何を直したか",
        "",
        "- 上位 planner の 1 発 L-BFGS-B を、`seed 群 + balance-speed seed + CEM 粗探索 + L-BFGS-B 局所仕上げ` のハイブリッドに変更した。",
        "- `upper_global_search_mode=auto` では、まず seed 群の局所解一致度を見て、怪しいときだけ CEM を動かすようにした。",
        "- 速度計画の初期候補として、critical-speed 的な `|P_pack(v)|` 最小化 seed を導入した。",
        "- `upper_global_search_enabled`, `upper_cem_generations`, `upper_cem_population`, `upper_cem_elite`, `upper_local_refine_topk` を YAML パラメータ化した。",
        "- fit 側は `data/identification/evidence/` を manifest から直接参照できるようにし、actual events / terminal anchor / grounded provenance をまとめて保持できるようにした。",
        "",
        "## 2. 文献根拠",
        "",
    ]
    for item in LITERATURE:
        md_lines.append(f"- {item['label']}: [{item['title']}]({item['url']})")
        md_lines.append(f"  - {item['reason']}")
    md_lines.extend(
        [
            "",
            "## 3. 上位 cost の内部式",
            "",
            "上位 stage cost は概ね次で構成される。",
            "",
            "```text",
            "J_stage = w_wait dt_wait + w_travel_time dt_travel",
            "        + w_terminal_soc_min [z_min_term - z_next]_+^2",
            "        + w_speed_smooth (v_k - v_{k-1})^2",
            "        + w_dv_limit [|dv/dt| - dv_max]_+^2",
            "        + w_speed_limit [v_k - v_limit]_+^2",
            "        + w_current_sq I_k^2 dt_travel",
            "        + w_pack_energy E_pack",
            "        + w_joule_loss E_loss",
            "        + w_aero_energy E_aero",
            "        + w_mech_energy E_mech",
            "        + w_kinetic_pos E_kin,+",
            "        + w_pack_power_slew (ΔP_pack)^2",
            "        + barrier / (z_next - z_min + eps)",
            "        + constraint penalties",
            "```",
            "",
            "terminal cost は概ね次である。",
            "",
            "```text",
            "J_term = penalty [z_min_term - z_terminal]_+^2",
            "       + w_soc_terminal [z_terminal - z_finish_target]_+^2",
            "```",
            "",
            "## 4. balance-speed seed",
            "",
            "各 control 点で速度候補集合 `v ∈ grid` を走査し、",
            "",
            "```text",
            "v_seed = argmin_v  |P_pack(v)| + λ (v - v_prev)^2",
            "```",
            "",
            "を選ぶ。ここで `P_pack(v)` はその地点・時刻の予測環境での pack power である。",
            "これは solar-car の critical-speed 系文献に沿って、不要な速度上下よりも、エネルギー収支に近い緩やかな速度保持を seed として与えるための近似である。",
            "",
            "## 5. hybrid upper solve",
            "",
            "```text",
            "1. warm start / constant seeds / ramp seeds / balance-speed seed を作る",
            "2. CEM で elite 分布更新",
            "   μ_{g+1} = mean(elite_g)",
            "   σ_{g+1} = max(std(elite_g), σ_floor)",
            "3. 上位候補を L-BFGS-B で局所仕上げ",
            "4. 最良有限解を採用",
            "```",
            "",
            "## 6. 現在の主要 YAML 値",
            "",
            f"- mass m: `{float(model.get('m', 0.0)):.3f}` kg",
            f"- CdA: `{float(model.get('CdA', 0.0)):.6f}`",
            f"- Crr: `{float(model.get('Crr', 0.0)):.6f}`",
            f"- P_aux: `{float(model.get('P_aux', 0.0)):.3f}` W",
            f"- upper_max_iter: `{int(mpc.get('upper_max_iter', 0))}`",
            f"- upper_global_search_enabled: `{bool(mpc.get('upper_global_search_enabled', False))}`",
            f"- upper_global_search_mode: `{str(mpc.get('upper_global_search_mode', 'auto'))}`",
            f"- upper_cem_generations: `{int(mpc.get('upper_cem_generations', 0))}`",
            f"- upper_cem_population: `{int(mpc.get('upper_cem_population', 0))}`",
            f"- upper_cem_elite: `{int(mpc.get('upper_cem_elite', 0))}`",
            f"- upper_local_refine_topk: `{int(mpc.get('upper_local_refine_topk', 0))}`",
            f"- upper prediction horizon dimension Np: `{upper_prediction_dim}`",
            f"- upper control dimension Nc: `{upper_control_dim}`",
            f"- weight-search dimension: `{len(tune_specs)}`",
            f"- active upper-cost term count: `{len(active_terms)}`",
            f"- active upper-cost terms: `{active_terms_label}`",
            "",
            "## 7. evidence bundle",
            "",
            f"- actual_event_yaml: `{(manifest.get('inputs', {}) or {}).get('actual_event_yaml', '')}`",
            f"- actual event count: `{actual_event_count}`",
            f"- source_inventory_json: `{evidence.get('source_inventory_json', '')}`",
            f"- notes_markdown: `{evidence.get('notes_markdown', '')}`",
            f"- grounded_map_summary_yaml: `{grounded.get('grounded_map_summary_yaml', '')}`",
            "",
            "## 8. fit summary snapshot",
            "",
            f"- power_rmse_clean_w: `{fit_summary.get('validation_metrics', {}).get('power_rmse_clean_w', 'nan')}`",
            f"- voltage_rmse_clean_v: `{fit_summary.get('validation_metrics', {}).get('voltage_rmse_clean_v', 'nan')}`",
            f"- retire_anchor_soc_obs: `{fit_summary.get('validation_metrics', {}).get('retire_anchor_soc_obs', 'nan')}`",
            f"- retire_anchor_soc_pred: `{fit_summary.get('validation_metrics', {}).get('retire_anchor_soc_pred', 'nan')}`",
        ]
    )
    md_path = report_dir / "controller_upgrade_worksheet.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8", newline="\n")

    lit_items = "\n".join(
        f"  \\item {item['label']}: \\url{{{item['url']}}}\\\\ {item['reason']}"
        for item in LITERATURE
    )
    tex = f"""
\\documentclass[a4paper,11pt]{{article}}
\\usepackage[top=18mm,bottom=22mm,left=18mm,right=18mm]{{geometry}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\setmainfont{{Times New Roman}}
\\setCJKmainfont{{Yu Gothic}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}
\\usepackage{{booktabs}}
\\usepackage{{xurl}}
\\usepackage[unicode,hidelinks]{{hyperref}}
\\title{{Controller Upgrade Worksheet}}
\\author{{solar\\_ws0129-main}}
\\date{{}}
\\begin{{document}}
\\maketitle

\\section{{目的}}
今回の追加資料は、単なる説明用ではなく、実走 replay の RMSE 低減と、
上位 planner の局所解依存性の除去に直接効かせるための evidence として扱う。

\\section{{今回の制御器改革}}
\\begin{{itemize}}
  \\item 上位 planner の単発 L-BFGS-B を、seed 群、balance-speed seed、CEM 粗探索、L-BFGS-B 局所仕上げのハイブリッドへ変更した。
  \\item `upper\\_global\\_search\\_mode=auto` では、seed 群の局所解が十分に一致したときは CEM を省略し、怪しいときだけ広域探索へ入る。
  \\item 速度 seed は、critical-speed 的に $|P_{{pack}}(v)|$ を小さくする候補を優先する。
  \\item solver の全 knobs は YAML から変更可能にした。
  \\item identification manifest は、actual events、terminal anchor、grounded map provenance を evidence bundle として保持する。
\\end{{itemize}}

\\section{{文献根拠}}
\\begin{{enumerate}}
{lit_items}
\\end{{enumerate}}

\\section{{上位 stage cost}}
現行の上位 stage cost は、概ね
\\[
\\begin{{aligned}}
J_{{stage}} ={{}}&
w_{{wait}} \\Delta t_{{wait}} + w_{{travel}} \\Delta t_{{travel}}
+ w_{{soc,min}} [z_{{min,term}} - z_{{next}}]_+^2 \\\\
&+ w_{{smooth}} (v_k - v_{{k-1}})^2
+ w_{{dv}} [|\\dot{{v}}| - \\dot{{v}}_{{max}}]_+^2 \\\\
&+ w_{{I^2}} I_k^2 \\Delta t_{{travel}}
+ w_{{pack}} E_{{pack}} + w_{{loss}} E_{{loss}} \\\\
&+ w_{{aero}} E_{{aero}} + w_{{mech}} E_{{mech}}
+ w_{{kin}} E_{{kin,+}} + w_{{slew}} (\\Delta P_{{pack}})^2 .
\\end{{aligned}}
\\]
に制約 penalty を加えたものである。

\\section{{balance-speed seed}}
各 control 点で、候補速度集合 $v \\in \\mathcal{{V}}$ を走査し、
\\[
v^\\star = \\arg\\min_{{v \\in \\mathcal{{V}}}} \\left| P_{{pack}}(v) \\right| + \\lambda (v-v_{{prev}})^2
\\]
を選ぶ。これは Howlett, Pudney 系の solar-car 最適速度が、不要な速度上下ではなく、
critical speed 近傍の緩やかな速度保持になるという知見に合わせた seed である。

\\section{{hybrid search}}
\\[
\\mu_{{g+1}} = \\frac{{1}}{{K}} \\sum_{{i \\in elite}} x_i,
\\qquad
\\sigma_{{g+1}} = \\max\\left(\\mathrm{{std}}(elite),\\sigma_{{floor}}\\right)
\\]
で CEM 分布を更新し、その後に上位候補を L-BFGS-B で局所仕上げする。
これにより、単発局所探索よりも fallback と初期値依存を減らす。

\\section{{現在の YAML 値}}
\\begin{{itemize}}
  \\item profile: \\path{{{repo_rel(profile_yaml)}}}
  \\item upper\\_max\\_iter: {int(mpc.get('upper_max_iter', 0))}
  \\item upper\\_global\\_search\\_enabled: {bool(mpc.get('upper_global_search_enabled', False))}
  \\item upper\\_global\\_search\\_mode: {str(mpc.get('upper_global_search_mode', 'auto'))}
  \\item upper\\_cem\\_generations: {int(mpc.get('upper_cem_generations', 0))}
  \\item upper\\_cem\\_population: {int(mpc.get('upper_cem_population', 0))}
  \\item upper\\_cem\\_elite: {int(mpc.get('upper_cem_elite', 0))}
  \\item upper\\_local\\_refine\\_topk: {int(mpc.get('upper_local_refine_topk', 0))}
  \\item upper prediction horizon dimension $N_p$: {upper_prediction_dim}
  \\item upper control dimension $N_c$: {upper_control_dim}
  \\item weight-search dimension: {len(tune_specs)}
  \\item vehicle mass: {float(model.get('m', 0.0)):.3f} kg
  \\item CdA: {float(model.get('CdA', 0.0)):.6f}
  \\item Crr: {float(model.get('Crr', 0.0)):.6f}
  \\item P\\_aux: {float(model.get('P_aux', 0.0)):.3f} W
  \\item active upper-cost term count: {len(active_terms)}
  \\item active upper-cost terms:
  {{\\raggedright\\ttfamily {active_terms_tex}\\par}}
\\end{{itemize}}

\\section{{evidence bundle}}
\\begin{{itemize}}
  \\item actual\\_event\\_yaml: \\path{{{str((manifest.get('inputs', {}) or {}).get('actual_event_yaml', ''))}}}
  \\item actual event count: {actual_event_count}
  \\item source\\_inventory\\_json: \\path{{{str(evidence.get('source_inventory_json', ''))}}}
  \\item notes\\_markdown: \\path{{{str(evidence.get('notes_markdown', ''))}}}
  \\item grounded\\_map\\_summary\\_yaml: \\path{{{str(grounded.get('grounded_map_summary_yaml', ''))}}}
\\end{{itemize}}

\\section{{fit summary snapshot}}
\\begin{{itemize}}
  \\item power\\_rmse\\_clean\\_w: {fit_summary.get('validation_metrics', {}).get('power_rmse_clean_w', 'nan')}
  \\item voltage\\_rmse\\_clean\\_v: {fit_summary.get('validation_metrics', {}).get('voltage_rmse_clean_v', 'nan')}
  \\item retire\\_anchor\\_soc\\_obs: {fit_summary.get('validation_metrics', {}).get('retire_anchor_soc_obs', 'nan')}
  \\item retire\\_anchor\\_soc\\_pred: {fit_summary.get('validation_metrics', {}).get('retire_anchor_soc_pred', 'nan')}
\\end{{itemize}}

\\end{{document}}
"""
    tex_path = report_dir / "controller_upgrade_worksheet.tex"
    tex_path.write_text(textwrap.dedent(tex).strip() + "\n", encoding="utf-8", newline="\n")
    compile_tex(tex_path)
    print(md_path)
    print(tex_path.with_suffix(".pdf"))


if __name__ == "__main__":
    main()
