#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math                                                        # [数学演算] 標準数学関数 (sqrt, sin, cos 等) のインポート
import os
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート

try:
    from torch.utils.tensorboard import SummaryWriter
except Exception:  # pragma: no cover - optional dependency
    SummaryWriter = None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar.schedule_utils import DriveSchedule
from mpc_solarcar.upper_cost import UpperCostConfig, active_upper_cost_terms, load_upper_cost_config


DEFAULT_PROFILE = ROOT / "project_packages" / "bwsc2025_fitted_mle4" / "profile.yaml"


LITERATURE = [
    {
        "label": "de Boer et al. (2005)",
        "title": "A Tutorial on the Cross-Entropy Method",
        "url": "https://people.smp.uq.edu.au/DirkKroese/ps/aortut.pdf",
        "note": "CEM is a generic derivative-free method for hard optimization problems.",
    },
    {
        "label": "Gros and Zanon (2019/2020)",
        "title": "Data-driven Economic NMPC using Reinforcement Learning",
        "url": "https://arxiv.org/pdf/1904.04152",
        "note": "RL can tune stage cost, terminal cost, and constraints of MPC/Economic MPC.",
    },
    {
        "label": "Zarrouki et al. (2024)",
        "title": "A Safe Reinforcement Learning driven Weights-varying Model Predictive Controller",
        "url": "https://arxiv.org/pdf/2402.02624",
        "note": "Safe RL can adapt MPC weights within a restricted safe search space.",
    },
    {
        "label": "Howlett et al. (1997)",
        "title": "Optimal driving strategy for a solar car on a level road",
        "url": "https://academic.oup.com/imaman/article-abstract/8/1/59/711668",
        "note": "Solar-race strategy is governed by a tight energy-speed trade-off.",
    },
    {
        "label": "Pudney and Howlett (2002)",
        "title": "Critical Speed Control of a Solar Car",
        "url": "https://link.springer.com/article/10.1023/A%3A1020907101234",
        "note": "Large unnecessary speed deviations are undesirable in solar-race operation.",
    },
]


@dataclass
class TermSpec:                                                    # [クラス定義] TermSpec オブジェクトの設計
    name: str
    lo: float
    hi: float
    init_log10: float
    threshold: float = 1.0e-4


@dataclass
class ScenarioSpec:                                                # [クラス定義] ScenarioSpec オブジェクトの設計
    name: str
    cfg_overrides: Dict[str, object]
    cli_overrides: Dict[str, object]
    weight: float


def read_yaml(path: Path) -> dict:                                 # [関数定義] read_yaml の処理実行ブロック
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_yaml(path: Path, payload: dict) -> None:                 # [関数定義] write_yaml の処理実行ブロック
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)


def ensure_dir(path: Path) -> None:                                # [関数定義] ensure_dir の処理実行ブロック
    path.mkdir(parents=True, exist_ok=True)


def log_trial_to_tensorboard(writer, prefix: str, result: Dict[str, object], step: int) -> None:  # [関数定義] log_trial_to_tensorboard の処理実行ブロック
    if writer is None:
        return
    scalar_keys = [
        "score",
        "score_mean",
        "score_worst",
        "final_distance_km",
        "final_distance_worst_km",
        "avg_speed_kmh",
        "min_soc",
        "final_soc",
        "oscillation_mean_abs_dv_kmh",
        "oscillation_p95_abs_dv_kmh",
        "current_rms_a",
        "pack_slew_rms_kw",
        "daylight_stop_h",
        "daylight_full_soc_h",
        "unused_finish_soc",
        "cpu_sec",
        "active_term_count",
    ]
    for key in scalar_keys:
        try:
            writer.add_scalar(f"{prefix}/{key}", float(result[key]), step)
        except Exception:
            continue


def repo_relative(path_like) -> str:                               # [関数定義] repo_relative の処理実行ブロック
    raw = str(path_like or "").strip()
    if not raw:
        return ""                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    path = Path(raw)
    try:
        resolved = path.resolve() if path.is_absolute() else (ROOT / path).resolve()
        return os.fspath(resolved.relative_to(ROOT)).replace("\\", "/")  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    except Exception:
        return raw.replace("\\", "/")                              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def failed_scenario_result(                                        # [関数定義] failed_scenario_result の処理実行ブロック
    scenario_name: str,
    scenario_weight: float,
    upper_cost: Dict[str, float],
    *,
    error: str,
    cfg_overrides: Dict[str, object],
    cli_overrides: Dict[str, object],
    summary_json: Path,
    out_csv: Path,
    detail_csv: Path,
    plan_csv: Path,
    report_html: Path,
    resolved_yaml: Path,
    sim_log_path: Path,
) -> Dict[str, object]:
    active_terms = active_upper_cost_terms(UpperCostConfig(**upper_cost), threshold=1.0e-4)
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "score": -1.0e9,
        "final_distance_km": 0.0,
        "avg_speed_kmh": 0.0,
        "min_soc": 0.0,
        "final_soc": 0.0,
        "elapsed_hours": 0.0,
        "cpu_sec": 0.0,
        "finish_reached": False,
        "oscillation_mean_abs_dv_kmh": 1.0e6,
        "oscillation_p95_abs_dv_kmh": 1.0e6,
        "current_rms_a": 1.0e6,
        "pack_slew_rms_kw": 1.0e6,
        "high_speed_h": 1.0e6,
        "daylight_stop_h": 1.0e6,
        "daylight_full_soc_h": 1.0e6,
        "unused_finish_soc": 1.0,
        "active_term_count": int(len(active_terms)),
        "active_terms": active_terms,
        "scenario": scenario_name,
        "scenario_weight": float(scenario_weight),
        "cfg_overrides": cfg_overrides,
        "cli_overrides": cli_overrides,
        "summary_json": os.fspath(summary_json),
        "out_csv": os.fspath(out_csv),
        "detail_csv": os.fspath(detail_csv),
        "plan_csv": os.fspath(plan_csv),
        "report_html": os.fspath(report_html),
        "resolved_yaml": os.fspath(resolved_yaml),
        "simulation_log": os.fspath(sim_log_path),
        "failed": True,
        "error": error,
    }


def compile_tex(tex_path: Path) -> Path:                           # [関数定義] compile_tex の処理実行ブロック
    pdf_path = tex_path.with_suffix(".pdf")
    for _ in range(2):
        res = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", tex_path.name],
            cwd=tex_path.parent,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if res.returncode != 0 and not pdf_path.exists():
            raise subprocess.CalledProcessError(res.returncode, res.args)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    return pdf_path                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def latex_escape(text: str) -> str:                                # [関数定義] latex_escape の処理実行ブロック
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
    return out                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def format_override_value(value) -> str:                           # [関数定義] format_override_value の処理実行ブロック
    if isinstance(value, bool):
        return "true" if value else "false"                        # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if isinstance(value, int):
        return str(value)                                          # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if isinstance(value, float):
        if math.isfinite(value):
            return f"{value:.12g}"                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return "0"                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return str(value)                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def speed_series(df: pd.DataFrame) -> pd.Series:                   # [関数定義] speed_series の処理実行ブロック
    if "v_exec_kmh" in df.columns:
        return df["v_exec_kmh"].astype(float)                      # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if "v_cmd_kmh" in df.columns:
        return df["v_cmd_kmh"].astype(float)                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return pd.Series(np.zeros(len(df), dtype=float))               # [戻り値] 計算結果・計算状態の呼び出し元への返却


def upper_cost_specs(                                              # [関数定義] upper_cost_specs の処理実行ブロック
    cfg: UpperCostConfig,
    *,
    include_progress_terms: bool = False,
    include_uncertainty_term: bool = True,
    include_terminal_term: bool = True,
) -> List[TermSpec]:
    specs = [
        TermSpec("w_speed_smooth", -2.0, 3.0, math.log10(max(cfg.w_speed_smooth, 1.0e-6))),
        TermSpec("w_speed_limit", -2.0, 3.0, math.log10(max(cfg.w_speed_limit, 1.0e-6))),
        TermSpec("w_current_sq", -5.0, 1.0, math.log10(max(cfg.w_current_sq, 1.0e-6))),
        TermSpec("w_pack_energy", -5.0, 2.0, math.log10(max(cfg.w_pack_energy, 1.0e-6))),
        TermSpec("w_joule_loss", -5.0, 2.0, math.log10(max(cfg.w_joule_loss, 1.0e-6))),
        TermSpec("w_aero_energy", -5.0, 2.0, math.log10(max(cfg.w_aero_energy, 1.0e-6))),
        TermSpec("w_mech_energy", -5.0, 2.0, math.log10(max(cfg.w_mech_energy, 1.0e-6))),
        TermSpec("w_kinetic_pos", -5.0, 2.0, math.log10(max(cfg.w_kinetic_pos, 1.0e-6))),
        TermSpec("w_pack_power_slew", -4.0, 4.0, math.log10(max(cfg.w_pack_power_slew, 1.0e-6))),
        TermSpec("w_speed_quartic", -6.0, 2.0, math.log10(max(cfg.w_speed_quartic, 1.0e-6))),
        TermSpec("w_solar_headroom", -4.0, 4.0, math.log10(max(cfg.w_solar_headroom, 1.0e-6))),
        TermSpec("w_soc_floor_barrier", -6.0, 4.0, math.log10(max(cfg.w_soc_floor_barrier, 1.0e-6))),
        TermSpec("w_terminal_soc_min", -1.0, 4.0, math.log10(max(cfg.w_terminal_soc_min, 1.0e-6))),
        TermSpec("w_day_end_soc_min", 2.0, 6.0, math.log10(max(cfg.w_day_end_soc_min, 1.0e-6))),
    ]
    if include_uncertainty_term:
        specs.append(TermSpec("w_uncertainty_reserve", -6.0, 5.0, math.log10(max(cfg.w_uncertainty_reserve, 1.0e-6))))
    if include_terminal_term:
        specs.append(TermSpec("w_soc_terminal", -6.0, 6.0, math.log10(max(cfg.w_soc_terminal, 1.0e-6))))
    if include_progress_terms:
        specs.extend(
            [
                TermSpec("w_progress_lag", -6.0, 4.0, math.log10(max(cfg.w_progress_lag, 1.0e-6))),
                TermSpec(
                    "w_progress_terminal_lag",
                    -6.0,
                    5.0,
                    math.log10(max(cfg.w_progress_terminal_lag, 1.0e-6)),
                ),
            ]
        )
    return specs                                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却


def vector_to_weights(specs: List[TermSpec], vec: np.ndarray, base_cfg: UpperCostConfig) -> Dict[str, float]:  # [関数定義] vector_to_weights の処理実行ブロック
    weights = base_cfg.to_dict()
    for spec, raw in zip(specs, vec):
        logv = float(np.clip(raw, spec.lo, spec.hi))
        value = 10.0 ** logv
        if value < spec.threshold:
            value = 0.0
        weights[spec.name] = float(value)
    return weights                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def mirror_legacy_weights(cfg: dict, upper_cost: Dict[str, float]) -> None:  # [関数定義] mirror_legacy_weights の処理実行ブロック
    mpc = cfg.setdefault("mpc", {})
    mpc["upper_cost"] = upper_cost
    mpc["w_dv"] = float(upper_cost.get("w_speed_smooth", mpc.get("w_dv", 30.0)))
    mpc["w_dv_limit"] = float(upper_cost.get("w_dv_limit", mpc.get("w_dv_limit", 2.0)))
    mpc["w_speed_limit"] = float(upper_cost.get("w_speed_limit", mpc.get("w_speed_limit", 50.0)))
    mpc["w_current"] = float(upper_cost.get("w_current_sq", mpc.get("w_current", 0.01)))
    mpc["w_T"] = float(upper_cost.get("w_temp", mpc.get("w_T", 5.0)))
    mpc["w_soc_day_max"] = float(upper_cost.get("w_soc_day_max", mpc.get("w_soc_day_max", 1.0e4)))
    mpc["w_soc_day_track"] = float(upper_cost.get("w_soc_day_track", mpc.get("w_soc_day_track", 0.0)))
    mpc["w_soc_terminal"] = float(upper_cost.get("w_soc_terminal", mpc.get("w_soc_terminal", 0.0)))


def build_reference_free_profile(                                  # [関数定義] build_reference_free_profile の処理実行ブロック
    profile_yaml: Path,
    output_dir: Path,
    *,
    disable_uncertainty_reserve: bool = False,
) -> tuple[Path, str]:
    cfg = read_yaml(profile_yaml)
    removed_reference = ""
    paths = cfg.setdefault("paths", {})
    if isinstance(paths, dict):
        removed_reference = str(paths.pop("progress_reference_csv", "") or "")
        for key, value in list(paths.items()):
            if isinstance(value, str) and value.strip():
                candidate = Path(value)
                if not candidate.is_absolute():
                    paths[key] = os.fspath((profile_yaml.parent / candidate).resolve())
    meta = cfg.setdefault("meta", {})
    notes = meta.setdefault("notes", [])
    if isinstance(notes, list):
        notes.append("Self-learning tuner generated a reference-free copy for autonomous weight search.")
    mpc = cfg.setdefault("mpc", {})
    ref_cfg = mpc.setdefault("reference_speed_tracking", {})
    if isinstance(ref_cfg, dict):
        ref_cfg["enabled"] = False
    upper_cost = mpc.setdefault("upper_cost", {})
    if isinstance(upper_cost, dict):
        upper_cost["w_progress_lag"] = 0.0
        upper_cost["w_progress_terminal_lag"] = 0.0
        if disable_uncertainty_reserve:
            upper_cost["w_uncertainty_reserve"] = 0.0
            upper_cost["reserve_soc_per_hour"] = 0.0
            upper_cost["reserve_soc_max_extra"] = 0.0
    out_path = output_dir / "self_learning_reference_free_profile.yaml"
    write_yaml(out_path, cfg)
    return out_path, removed_reference                             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def default_scenarios(profile_yaml: Path, *, mode: str = "nominal") -> List[ScenarioSpec]:  # [関数定義] default_scenarios の処理実行ブロック
    if str(mode).strip().lower() == "nominal":
        return [ScenarioSpec("nominal", cfg_overrides={}, cli_overrides={}, weight=1.0)]  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    cfg = read_yaml(profile_yaml)
    model = cfg.get("model", {}) if isinstance(cfg, dict) else {}
    base_cda = float(model.get("CdA", 0.08))
    base_crr = float(model.get("Crr", 0.008))
    base_aux = float(model.get("P_aux", 0.0))
    return [                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        ScenarioSpec("nominal", cfg_overrides={}, cli_overrides={}, weight=0.5),
        ScenarioSpec(
            "low_solar_high_load",
            cfg_overrides={
                "model.P_aux": max(20.0, base_aux + 20.0),
                "model.CdA": max(base_cda * 1.10, base_cda + 0.005),
                "model.Crr": max(base_crr * 1.05, base_crr + 0.0002),
            },
            cli_overrides={
                "solar_gain": 0.90,
                "poa_gain_drive": 0.94,
                "poa_gain_stop": 0.92,
            },
            weight=0.25,
        ),
        ScenarioSpec(
            "drag_bias",
            cfg_overrides={
                "model.P_aux": max(10.0, base_aux + 10.0),
                "model.CdA": max(base_cda * 1.20, base_cda + 0.010),
                "model.Crr": max(base_crr * 1.08, base_crr + 0.0004),
            },
            cli_overrides={
                "solar_gain": 0.97,
                "poa_gain_drive": 0.98,
                "poa_gain_stop": 0.98,
            },
            weight=0.25,
        ),
    ]


def run_single_scenario(                                           # [関数定義] run_single_scenario の処理実行ブロック
    profile_yaml: Path,
    output_dir: Path,
    candidate_name: str,
    scenario: ScenarioSpec,
    upper_cost: Dict[str, float],
    cfg_overrides: Dict[str, object],
    cli_overrides: Dict[str, object],
) -> Dict[str, object]:
    scenario_dir = output_dir / "candidates" / candidate_name / scenario.name
    ensure_dir(scenario_dir)

    out_csv = scenario_dir / "simulation.csv"
    detail_csv = scenario_dir / "simulation_detail.csv"
    plan_csv = scenario_dir / "upper_plan.csv"
    report_html = scenario_dir / "simulation_report.html"
    summary_json = scenario_dir / "summary.json"
    resolved_yaml = scenario_dir / "resolved.yaml"
    latest_manifest_json = scenario_dir / "latest_manifest.json"
    sim_log_path = scenario_dir / "solar_sim_console.log"

    cmd = [
        os.fspath(Path(sys.executable)),
        os.fspath(ROOT / "scripts" / "solar_sim.py"),
        "--profile_yaml",
        os.fspath(profile_yaml),
        "--out_csv",
        os.fspath(out_csv),
        "--out_detail_csv",
        os.fspath(detail_csv),
        "--out_plan_csv",
        os.fspath(plan_csv),
        "--report_html",
        os.fspath(report_html),
        "--summary_json",
        os.fspath(summary_json),
        "--resolved_yaml",
        os.fspath(resolved_yaml),
        "--latest_manifest_json",
        os.fspath(latest_manifest_json),
    ]

    merged_cli = dict(cli_overrides)
    merged_cli.update(scenario.cli_overrides)
    for key, value in merged_cli.items():
        cmd.extend([f"--{key}", format_override_value(value)])

    merged_cfg = dict(cfg_overrides)
    merged_cfg.update(scenario.cfg_overrides)
    for key, value in upper_cost.items():
        merged_cfg[f"mpc.upper_cost.{key}"] = value
    merged_cfg["mpc.w_dv"] = upper_cost.get("w_speed_smooth", 0.0)
    merged_cfg["mpc.w_dv_limit"] = upper_cost.get("w_dv_limit", 0.0)
    merged_cfg["mpc.w_speed_limit"] = upper_cost.get("w_speed_limit", 0.0)
    merged_cfg["mpc.w_current"] = upper_cost.get("w_current_sq", 0.0)
    merged_cfg["mpc.w_T"] = upper_cost.get("w_temp", 0.0)
    merged_cfg["mpc.w_soc_day_max"] = upper_cost.get("w_soc_day_max", 0.0)
    merged_cfg["mpc.w_soc_day_track"] = upper_cost.get("w_soc_day_track", 0.0)
    merged_cfg["mpc.w_soc_terminal"] = upper_cost.get("w_soc_terminal", 0.0)
    for key, value in merged_cfg.items():
        cmd.extend(["--override", f"{key}={format_override_value(value)}"])

    with sim_log_path.open("w", encoding="utf-8", newline="\n") as log_f:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            check=False,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            text=True,
        )
    if proc.returncode != 0:
        result = failed_scenario_result(
            scenario.name,
            scenario.weight,
            upper_cost,
            error=f"solar_sim failed with exit code {proc.returncode}",
            cfg_overrides=merged_cfg,
            cli_overrides=merged_cli,
            summary_json=summary_json,
            out_csv=out_csv,
            detail_csv=detail_csv,
            plan_csv=plan_csv,
            report_html=report_html,
            resolved_yaml=resolved_yaml,
            sim_log_path=sim_log_path,
        )
    else:
        try:
            summary = json.loads(summary_json.read_text(encoding="utf-8"))
            sim_df = pd.read_csv(out_csv)
            detail_df = pd.read_csv(detail_csv) if detail_csv.exists() else pd.DataFrame()
            result = evaluate_simulation(profile_yaml, summary, sim_df, detail_df, upper_cost)
        except Exception as exc:
            result = failed_scenario_result(
                scenario.name,
                scenario.weight,
                upper_cost,
                error=f"postprocess failed: {exc}",
                cfg_overrides=merged_cfg,
                cli_overrides=merged_cli,
                summary_json=summary_json,
                out_csv=out_csv,
                detail_csv=detail_csv,
                plan_csv=plan_csv,
                report_html=report_html,
                resolved_yaml=resolved_yaml,
                sim_log_path=sim_log_path,
            )
    result.update(
        {
            "scenario": scenario.name,
            "scenario_weight": float(scenario.weight),
            "cfg_overrides": merged_cfg,
            "cli_overrides": merged_cli,
            "summary_json": os.fspath(summary_json),
            "out_csv": os.fspath(out_csv),
            "detail_csv": os.fspath(detail_csv),
            "plan_csv": os.fspath(plan_csv),
            "report_html": os.fspath(report_html),
            "resolved_yaml": os.fspath(resolved_yaml),
            "simulation_log": os.fspath(sim_log_path),
        }
    )
    (scenario_dir / "eval_metrics.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return result                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def evaluate_simulation(                                           # [関数定義] evaluate_simulation の処理実行ブロック
    profile_yaml: Path,
    summary: Dict[str, object],
    sim_df: pd.DataFrame,
    detail_df: pd.DataFrame,
    upper_cost: Dict[str, float],
) -> Dict[str, object]:
    speed_vals = speed_series(sim_df).to_numpy(dtype=float)
    speed_steps = np.abs(np.diff(speed_vals)) if len(speed_vals) >= 2 else np.zeros(0, dtype=float)
    osc = float(np.mean(speed_steps)) if len(speed_steps) else 0.0
    osc_p95 = float(np.percentile(speed_steps, 95.0)) if len(speed_steps) else 0.0

    if "time_utc" in sim_df.columns and len(sim_df) >= 2:
        t_series = pd.to_datetime(sim_df["time_utc"], utc=True, errors="coerce")
        dt_hours = t_series.diff().dt.total_seconds().fillna(t_series.diff().dt.total_seconds().median()).fillna(0.0) / 3600.0
    else:
        t_series = pd.Series([pd.NaT] * len(sim_df))
        dt_hours = pd.Series(np.zeros(len(sim_df), dtype=float))

    profile_cfg = read_yaml(profile_yaml)
    schedule = None
    schedule_rel = ((profile_cfg.get("paths", {}) if isinstance(profile_cfg, dict) else {}) or {}).get("drive_schedule_yaml")
    if schedule_rel:
        schedule_path = (profile_yaml.parent / schedule_rel).resolve()
        if schedule_path.exists():
            schedule = DriveSchedule.from_yaml(os.fspath(schedule_path))

    daylight_mask = sim_df.get("G_poa", pd.Series(np.zeros(len(sim_df), dtype=float))).astype(float) >= 250.0
    stopped_mask = speed_series(sim_df) <= 1.0
    soc_mask = sim_df.get("soc", pd.Series(np.zeros(len(sim_df), dtype=float))).astype(float) >= 0.95
    if schedule is not None and len(t_series) == len(sim_df):
        drive_mask = t_series.map(lambda ts: bool(pd.notna(ts) and schedule.is_drive_time(ts.to_pydatetime())))
    else:
        drive_mask = pd.Series(np.ones(len(sim_df), dtype=bool))
    daylight_stop_h = float(dt_hours[drive_mask & daylight_mask & stopped_mask].sum()) if len(dt_hours) == len(sim_df) else 0.0
    daylight_full_soc_h = float(dt_hours[drive_mask & daylight_mask & soc_mask].sum()) if len(dt_hours) == len(sim_df) else 0.0
    high_speed_mask = speed_series(sim_df) >= 85.0
    high_speed_h = float(dt_hours[drive_mask & high_speed_mask].sum()) if len(dt_hours) == len(sim_df) else 0.0

    if not detail_df.empty and "I" in detail_df.columns:
        current_vals = detail_df["I"].to_numpy(dtype=float)
        current_rms_a = float(np.sqrt(np.mean(np.square(current_vals)))) if len(current_vals) else 0.0
    else:
        current_rms_a = 0.0
    if not detail_df.empty and "P_pack" in detail_df.columns and len(detail_df) >= 2:
        pack_slew_kw = np.diff(detail_df["P_pack"].to_numpy(dtype=float)) / 1000.0
        pack_slew_rms_kw = float(np.sqrt(np.mean(np.square(pack_slew_kw)))) if len(pack_slew_kw) else 0.0
    else:
        pack_slew_rms_kw = 0.0

    final_soc = float(summary.get("final_soc", 0.0))
    unused_finish_soc = max(0.0, final_soc - 0.12)
    finish_reached = bool(summary.get("finish_reached", False))
    elapsed_hours = float(summary.get("elapsed_hours", 0.0))
    active_terms = active_upper_cost_terms(UpperCostConfig(**upper_cost), threshold=1.0e-4)
    finish_bonus = 1500.0 if finish_reached else 0.0
    score = (
        float(summary["final_distance_km"])
        + finish_bonus
        - 1.5 * osc
        - 0.8 * osc_p95
        - 0.2 * current_rms_a
        - 12.0 * pack_slew_rms_kw
        - 10.0 * high_speed_h
        - 40.0 * daylight_stop_h
        - 25.0 * daylight_full_soc_h
        - 120.0 * unused_finish_soc
        - 0.5 * len(active_terms)
        - (5.0 * elapsed_hours if finish_reached else 0.0)
    )

    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "score": float(score),
        "final_distance_km": float(summary["final_distance_km"]),
        "avg_speed_kmh": float(summary.get("avg_speed_kmh", 0.0)),
        "min_soc": float(summary.get("min_soc", 0.0)),
        "final_soc": final_soc,
        "elapsed_hours": elapsed_hours,
        "cpu_sec": float(summary.get("cpu_sec", 0.0)),
        "finish_reached": finish_reached,
        "oscillation_mean_abs_dv_kmh": osc,
        "oscillation_p95_abs_dv_kmh": osc_p95,
        "current_rms_a": current_rms_a,
        "pack_slew_rms_kw": pack_slew_rms_kw,
        "high_speed_h": high_speed_h,
        "daylight_stop_h": daylight_stop_h,
        "daylight_full_soc_h": daylight_full_soc_h,
        "unused_finish_soc": unused_finish_soc,
        "active_term_count": int(len(active_terms)),
        "active_terms": active_terms,
    }


def aggregate_candidate(candidate: str, scenario_results: List[Dict[str, object]], weights: Dict[str, float]) -> Dict[str, object]:  # [関数定義] aggregate_candidate の処理実行ブロック
    if not scenario_results:
        raise ValueError("scenario_results is empty")
    scenario_weights = np.array([max(0.0, float(row.get("scenario_weight", 0.0))) for row in scenario_results], dtype=float)
    if not np.isfinite(scenario_weights).all() or scenario_weights.sum() <= 0.0:
        scenario_weights = np.ones(len(scenario_results), dtype=float)
    scenario_weights = scenario_weights / scenario_weights.sum()
    scenario_scores = np.array([float(row["score"]) for row in scenario_results], dtype=float)
    weighted_mean_score = float(np.dot(scenario_weights, scenario_scores))
    worst_score = float(np.min(scenario_scores))
    robust_score = 0.7 * weighted_mean_score + 0.3 * worst_score

    nominal = next((row for row in scenario_results if row.get("scenario") == "nominal"), scenario_results[0])
    result = {
        "candidate": candidate,
        "score": robust_score,
        "score_mean": weighted_mean_score,
        "score_worst": worst_score,
        "final_distance_km": float(np.dot(scenario_weights, np.array([float(row["final_distance_km"]) for row in scenario_results]))),
        "final_distance_worst_km": float(min(float(row["final_distance_km"]) for row in scenario_results)),
        "avg_speed_kmh": float(np.dot(scenario_weights, np.array([float(row["avg_speed_kmh"]) for row in scenario_results]))),
        "min_soc": float(min(float(row["min_soc"]) for row in scenario_results)),
        "final_soc": float(np.dot(scenario_weights, np.array([float(row["final_soc"]) for row in scenario_results]))),
        "finish_reached": bool(any(bool(row["finish_reached"]) for row in scenario_results)),
        "oscillation_mean_abs_dv_kmh": float(np.dot(scenario_weights, np.array([float(row["oscillation_mean_abs_dv_kmh"]) for row in scenario_results]))),
        "oscillation_p95_abs_dv_kmh": float(np.dot(scenario_weights, np.array([float(row["oscillation_p95_abs_dv_kmh"]) for row in scenario_results]))),
        "current_rms_a": float(np.dot(scenario_weights, np.array([float(row["current_rms_a"]) for row in scenario_results]))),
        "pack_slew_rms_kw": float(np.dot(scenario_weights, np.array([float(row["pack_slew_rms_kw"]) for row in scenario_results]))),
        "high_speed_h": float(np.dot(scenario_weights, np.array([float(row["high_speed_h"]) for row in scenario_results]))),
        "daylight_stop_h": float(np.dot(scenario_weights, np.array([float(row["daylight_stop_h"]) for row in scenario_results]))),
        "daylight_full_soc_h": float(np.dot(scenario_weights, np.array([float(row["daylight_full_soc_h"]) for row in scenario_results]))),
        "unused_finish_soc": float(np.dot(scenario_weights, np.array([float(row["unused_finish_soc"]) for row in scenario_results]))),
        "elapsed_hours": float(np.dot(scenario_weights, np.array([float(row["elapsed_hours"]) for row in scenario_results]))),
        "cpu_sec": float(sum(float(row["cpu_sec"]) for row in scenario_results)),
        "active_term_count": int(round(np.dot(scenario_weights, np.array([float(row["active_term_count"]) for row in scenario_results])))),
        "weights": weights,
        "scenario_results": scenario_results,
        "nominal_out_csv": nominal.get("out_csv", ""),
        "nominal_detail_csv": nominal.get("detail_csv", ""),
    }
    return result                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def run_candidate(                                                 # [関数定義] run_candidate の処理実行ブロック
    profile_yaml: Path,
    output_dir: Path,
    candidate_name: str,
    upper_cost: Dict[str, float],
    cfg_overrides: Dict[str, object],
    cli_overrides: Dict[str, object],
    scenarios: List[ScenarioSpec],
) -> Dict[str, object]:
    scenario_results = [
        run_single_scenario(
            profile_yaml,
            output_dir,
            candidate_name,
            scenario,
            upper_cost,
            cfg_overrides,
            cli_overrides,
        )
        for scenario in scenarios
    ]
    result = aggregate_candidate(candidate_name, scenario_results, upper_cost)
    cand_dir = output_dir / "candidates" / candidate_name
    ensure_dir(cand_dir)
    (cand_dir / "aggregate_metrics.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return result                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def save_trial_checkpoint(output_dir: Path, trials: List[Dict[str, object]], best_result: Dict[str, object] | None) -> None:  # [関数定義] save_trial_checkpoint の処理実行ブロック
    if trials:
        pd.DataFrame(trials).to_csv(output_dir / "trial_results_partial.csv", index=False)
    if best_result is not None:
        write_yaml(
            output_dir / "best_upper_cost_partial.yaml",
            {"upper_cost": best_result.get("weights", {}), "score": float(best_result.get("score", 0.0))},
        )


def csv_row_count(path: Path) -> int:                              # [関数定義] csv_row_count の処理実行ブロック
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        return max(0, sum(1 for _ in f) - 1)                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def summarize_path(path: Path) -> Dict[str, object]:               # [関数定義] summarize_path の処理実行ブロック
    suffix = path.suffix.lower()
    summary = {
        "path": os.fspath(path),
        "exists": path.exists(),
        "kind": suffix.lstrip("."),
        "rows": "",
        "columns": "",
        "column_names": "",
    }
    if not path.exists():
        return summary                                             # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if suffix == ".csv":
        try:
            header = pd.read_csv(path, nrows=0)
            summary["rows"] = csv_row_count(path)
            summary["columns"] = len(header.columns)
            summary["column_names"] = ", ".join(str(col) for col in header.columns[:12])
        except Exception:
            pass
    return summary                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却


def dataframe_to_markdown(df: pd.DataFrame) -> str:                # [関数定義] dataframe_to_markdown の処理実行ブロック
    if df.empty:
        return "(none)"                                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
    cols = [str(col) for col in df.columns]
    lines = [
        "| " + " | ".join(cols) + " |",
        "| " + " | ".join(["---"] * len(cols)) + " |",
    ]
    for _, row in df.iterrows():
        vals = [str(row[col]).replace("\n", " ") for col in df.columns]
        lines.append("| " + " | ".join(vals) + " |")
    return "\n".join(lines)                                        # [戻り値] 計算結果・計算状態の呼び出し元への返却


def flatten_scalars(prefix: str, payload, rows: List[Dict[str, object]]) -> None:  # [関数定義] flatten_scalars の処理実行ブロック
    if isinstance(payload, dict):
        for key, value in payload.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            flatten_scalars(next_prefix, value, rows)
        return
    if isinstance(payload, (int, float, bool, str)):
        rows.append({"key": prefix, "value": payload})


def build_current_asset_manifests(profile_yaml: Path, fit_summary: dict, output_dir: Path) -> Dict[str, Path]:  # [関数定義] build_current_asset_manifests の処理実行ブロック
    profile_cfg = read_yaml(profile_yaml)
    paths_cfg = profile_cfg.get("paths", {}) if isinstance(profile_cfg, dict) else {}

    file_rows = []
    for role, rel_path in sorted(paths_cfg.items()):
        path = (profile_yaml.parent / str(rel_path)).resolve()
        info = summarize_path(path)
        info["role"] = role
        file_rows.append(info)
    files_df = pd.DataFrame(file_rows)
    files_csv = output_dir / "current_active_files.csv"
    files_df.to_csv(files_csv, index=False)

    scalar_rows: List[Dict[str, object]] = []
    for section_name in ("model", "mpc", "runtime", "simulation", "live", "measurement"):
        section = profile_cfg.get(section_name, {})
        local_rows: List[Dict[str, object]] = []
        flatten_scalars("", section, local_rows)
        for row in local_rows:
            scalar_rows.append(
                {
                    "source": f"profile:{section_name}",
                    "key": row["key"],
                    "value": row["value"],
                }
            )
    local_fit_rows: List[Dict[str, object]] = []
    flatten_scalars("", fit_summary, local_fit_rows)
    for row in local_fit_rows:
        scalar_rows.append(
            {
                "source": "fit_summary",
                "key": row["key"],
                "value": row["value"],
            }
        )
    scalars_df = pd.DataFrame(scalar_rows)
    scalars_csv = output_dir / "current_scalar_coefficients.csv"
    scalars_df.to_csv(scalars_csv, index=False)

    md_lines = [
        "# Current maps and coefficients",
        "",
        f"- profile: `{repo_relative(profile_yaml)}`",
        f"- generated_at: `{datetime.now().isoformat(timespec='seconds')}`",
        "",
        "## Active files",
        "",
        dataframe_to_markdown(files_df),
        "",
        "## Scalar coefficients",
        "",
        dataframe_to_markdown(scalars_df),
        "",
    ]
    md_path = output_dir / "current_maps_and_coefficients.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8", newline="\n")

    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "files_csv": files_csv,
        "scalars_csv": scalars_csv,
        "markdown": md_path,
    }


def render_report(                                                 # [関数定義] render_report の処理実行ブロック
    output_dir: Path,
    source_profile_yaml: Path,
    eval_profile_yaml: Path,
    fit_summary: dict,
    baseline_result: Dict[str, object],
    tuned_result: Dict[str, object],
    trials_df: pd.DataFrame,
    best_weights: Dict[str, float],
    manifest_paths: Dict[str, Path],
    removed_reference: str,
    specs: List[TermSpec],
    search_cfg: Dict[str, object],
    tensorboard_dir: Path | None,
) -> tuple[Path, Path]:
    score_label = "robust score" if str(search_cfg.get("scenario_mode", "nominal")) == "robust" else "aggregate score"
    report_dir = output_dir / "report"
    ensure_dir(report_dir)
    source_profile_label = repo_relative(source_profile_yaml)
    eval_profile_label = repo_relative(eval_profile_yaml)
    removed_reference_label = repo_relative(removed_reference) or "(none)"
    files_csv_label = repo_relative(manifest_paths["files_csv"])
    scalars_csv_label = repo_relative(manifest_paths["scalars_csv"])
    markdown_label = repo_relative(manifest_paths["markdown"])
    best_weights_csv_label = repo_relative(output_dir / "best_upper_cost.csv")
    tensorboard_label = repo_relative(tensorboard_dir) if tensorboard_dir else ""
    actual_retire_km = float(fit_summary.get("race_distance", {}).get("actual_retire_km", 2831.0))
    power_rmse_fit = float(
        fit_summary.get("validation_metrics", {}).get(
            "power_rmse_fit_window_w",
            fit_summary.get("validation_metrics", {}).get("power_rmse_clean_w", float("nan")),
        )
    )
    voltage_rmse_fit = float(
        fit_summary.get("validation_metrics", {}).get(
            "voltage_rmse_fit_window_v",
            fit_summary.get("validation_metrics", {}).get("voltage_rmse_clean_v", float("nan")),
        )
    )
    median_cpu_sec = float(pd.to_numeric(trials_df.get("cpu_sec", pd.Series(dtype=float)), errors="coerce").dropna().median()) if not trials_df.empty else float("nan")
    search_candidates = int(sum(1 for _, row in trials_df.iterrows() if str(row.get("candidate", "")).startswith("g")))
    estimated_10000_gen_candidates = int(search_cfg.get("population", 0)) * 10000
    estimated_10000_gen_cpu_days = (
        (median_cpu_sec * estimated_10000_gen_candidates) / 86400.0
        if math.isfinite(median_cpu_sec) and median_cpu_sec > 0.0 and estimated_10000_gen_candidates > 0
        else float("nan")
    )
    human_gap_km = actual_retire_km - float(tuned_result["final_distance_km"])

    learning_png = report_dir / "learning_curve.png"
    if not trials_df.empty:
        plt.figure(figsize=(8.4, 4.6))
        plt.plot(trials_df["trial_index"], trials_df["score"], marker="o", linewidth=1.2, label="robust score")
        plt.plot(trials_df["trial_index"], trials_df["final_distance_km"], marker="s", linewidth=1.0, label="mean distance [km]")
        plt.xlabel("trial index")
        plt.ylabel("score / distance")
        plt.title("Self-learning upper-planner search history")
        plt.grid(True, alpha=0.25)
        plt.legend()
        plt.tight_layout()
        plt.savefig(learning_png, dpi=160)
        plt.close()

    scenario_compare_png = report_dir / "scenario_compare.png"
    base_scenarios = {row["scenario"]: row for row in baseline_result["scenario_results"]}
    tuned_scenarios = {row["scenario"]: row for row in tuned_result["scenario_results"]}
    scenario_names = list(base_scenarios.keys())
    x = np.arange(len(scenario_names))
    width = 0.35
    plt.figure(figsize=(8.6, 4.8))
    plt.bar(x - width / 2, [float(base_scenarios[name]["final_distance_km"]) for name in scenario_names], width=width, label="baseline")
    plt.bar(x + width / 2, [float(tuned_scenarios[name]["final_distance_km"]) for name in scenario_names], width=width, label="self-learned")
    plt.xticks(x, scenario_names, rotation=10)
    plt.ylabel("final distance [km]")
    plt.title("Scenario-wise distance comparison")
    plt.grid(True, axis="y", alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(scenario_compare_png, dpi=160)
    plt.close()

    baseline_series = pd.read_csv(os.fspath(baseline_result["nominal_out_csv"]))
    tuned_series = pd.read_csv(os.fspath(tuned_result["nominal_out_csv"]))

    speed_compare_png = report_dir / "speed_compare.png"
    plt.figure(figsize=(8.6, 4.6))
    plt.plot(baseline_series.index, speed_series(baseline_series), label="baseline", linewidth=1.1, color="#94a3b8")
    plt.plot(tuned_series.index, speed_series(tuned_series), label="self-learned", linewidth=1.1, color="#0f766e")
    plt.xlabel("simulation step")
    plt.ylabel("executed speed [km/h]")
    plt.title("Nominal-scenario speed comparison")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(speed_compare_png, dpi=160)
    plt.close()

    soc_compare_png = report_dir / "soc_compare.png"
    plt.figure(figsize=(8.6, 4.6))
    plt.plot(baseline_series.index, baseline_series["soc"], label="baseline", linewidth=1.1, color="#94a3b8")
    plt.plot(tuned_series.index, tuned_series["soc"], label="self-learned", linewidth=1.1, color="#b45309")
    plt.xlabel("simulation step")
    plt.ylabel("state of charge [-]")
    plt.title("Nominal-scenario SoC comparison")
    plt.grid(True, alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(soc_compare_png, dpi=160)
    plt.close()

    best_weights_df = pd.DataFrame(
        {
            "term": list(best_weights.keys()),
            "value": [float(best_weights[key]) for key in best_weights],
        }
    )
    best_weights_csv = output_dir / "best_upper_cost.csv"
    best_weights_df.to_csv(best_weights_csv, index=False)

    scenario_rows = []
    for base_row in baseline_result["scenario_results"]:
        tuned_row = tuned_scenarios[base_row["scenario"]]
        scenario_rows.append(
            {
                "scenario": base_row["scenario"],
                "weight": float(base_row.get("scenario_weight", 0.0)),
                "baseline_distance_km": float(base_row["final_distance_km"]),
                "tuned_distance_km": float(tuned_row["final_distance_km"]),
                "baseline_score": float(base_row["score"]),
                "tuned_score": float(tuned_row["score"]),
                "baseline_min_soc": float(base_row["min_soc"]),
                "tuned_min_soc": float(tuned_row["min_soc"]),
            }
        )
    scenario_df = pd.DataFrame(scenario_rows)
    scenario_csv = output_dir / "scenario_comparison.csv"
    scenario_df.to_csv(scenario_csv, index=False)
    iter_compare_csv = output_dir / "upper_max_iter_compare" / "upper_max_iter_compare.csv"
    iter_compare_df = pd.read_csv(iter_compare_csv) if iter_compare_csv.exists() else pd.DataFrame()

    fit_rows: List[Dict[str, object]] = []
    flatten_scalars("", fit_summary, fit_rows)
    fit_df = pd.DataFrame(fit_rows)
    fit_csv = output_dir / "fitted_scalar_coefficients.csv"
    fit_df.to_csv(fit_csv, index=False)

    trials_csv = output_dir / "trial_results.csv"
    trials_df.to_csv(trials_csv, index=False)

    active_terms = active_upper_cost_terms(UpperCostConfig(**best_weights), threshold=1.0e-4)
    inactive_terms = sorted(set(best_weights.keys()) - set(active_terms.keys()))

    def tex_path_rel(path: Path) -> str:                           # [関数定義] tex_path_rel の処理実行ブロック
        return latex_escape(os.path.relpath(path, report_dir)).replace("%", r"\%")  # [戻り値] 計算結果・計算状態の呼び出し元への返却

    tex = f"""
\\documentclass[a4paper,11pt]{{article}}
\\usepackage[top=16mm,bottom=20mm,left=16mm,right=16mm]{{geometry}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\setmainfont{{Times New Roman}}
\\setCJKmainfont{{Yu Gothic}}
\\setmonofont{{Consolas}}
\\setCJKmonofont{{Yu Gothic}}
\\usepackage{{graphicx}}
\\usepackage{{booktabs}}
\\usepackage{{longtable}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}
\\usepackage{{float}}
\\usepackage{{pdflscape}}
\\usepackage[unicode]{{hyperref}}
\\hypersetup{{colorlinks=true,linkcolor=blue,urlcolor=blue}}
\\setlength{{\\parskip}}{{0.35em}}
\\setlength{{\\parindent}}{{1em}}
\\title{{BWSC2025 上位プランナ自己学習チューニング報告}}
\\author{{solar\\_ws0129-main}}
\\date{{{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}}
\\begin{{document}}
\\maketitle

\\section{{目的}}
本報告では、BWSC2025 fitted package の上位プランナ重みを、
人間ログの追従ではなく、全大会シミュレーションの成績を直接最大化する
自己学習で調整した。加えて、現在アクティブなマップと係数の所在も整理した。

\\section{{人間参照を切った理由}}
今回の探索では、進捗参照 CSV を評価用 profile から除去し、
\\texttt{{reference\\_speed\\_tracking}} を無効化した。
すなわち、学習器は「人がその時どう走ったか」を見ず、
距離、SoC、安全余裕、速度変動、電流・出力変動といった
競技目的そのものだけで評価される。

除去した参照ファイルは以下である。
\\begin{{itemize}}
  \\item {latex_escape(removed_reference_label)}
\\end{{itemize}}

\\section{{自己学習の理論的根拠}}
de Boer らは Cross-Entropy Method (CEM) を、微分が取れない難しい問題にも使える
一般的なゼロ次最適化法として整理している。
Gros と Zanon は、MPC/ENMPC は stage cost, terminal cost, constraints を調整することで
RL の関数近似器として使えると述べている。
Zarrouki らは、MPC 重みを RL で安全に調整するには、闇雲な連続探索よりも
制約を意識した安全な探索空間が有効であることを示している。

本件の outer loop は black-box simulator の上に載るため、勾配情報は信用しづらい。
そこで、各重みを $\\log_{{10}}$ 空間で正規分布からサンプリングし、
上位 elite の平均と分散を更新する CEM を採用した。

\\section{{最適化問題}}
内側の上位プランナは、速度平滑化、速度上限、電流二乗、
パックエネルギー、ジュール損、空力エネルギー、運動エネルギー増分、
パック出力スルー、速度四乗、日射 headroom、SoC barrier、
終端 SoC、日末 SoC の各項を持つ。

外側の自己学習報酬は
\\[
R_i(\\theta)=d_i + 1500\\,\\mathbf{{1}}_{{\\mathrm{{finish}},i}}
-1.5\\,\\overline{{|\\Delta v|}}_i
-0.8\\,q_{{95}}(|\\Delta v|)_i
-0.2\\,I_{{rms,i}}
-12\\,P_{{slew,rms,i}}
-10\\,T_{{high,i}}
-40\\,T_{{stop,day,i}}
-25\\,T_{{full,day,i}}
-120\\,z_{{unused,i}}
-0.5\\,N_{{active,i}}
\\]
とした。ここで $d_i$ は最終到達距離 [km]、$z_{{unused,i}}$ は最終未使用 SoC、
$N_{{active,i}}$ は閾値を超えた有効項数である。

今回の探索モードは \\texttt{{{latex_escape(str(search_cfg.get('scenario_mode', 'nominal')))}}} である。
"""
    if str(search_cfg.get("scenario_mode", "nominal")) == "robust":
        tex += r"""
さらに、名目・低日射高負荷・高抵抗寄りの 3 シナリオで評価し、
ロバスト集約報酬を
\[
R_{{robust}}(\theta)=0.7\,\mathbb{{E}}[R_i(\theta)] + 0.3\,\min_i R_i(\theta)
\]
とした。これは単一条件への過適合を避けるためである。
"""
    else:
        tex += r"""
名目プランは「最もありそうな天候・車両条件」をそのまま使う設計とし、
不確かさの帯は本学習の報酬関数には混ぜず、別途 upper/lower envelope で扱う。
そのため、\texttt{w\_uncertainty\_reserve} と reserve 関連項は評価 profile で 0 に固定している。
"""
    tex += r"""

CEM 更新は
\\[
\\theta_j^{{(g)}} \\sim \\mathcal{{N}}(\\mu^{{(g)}}, \\mathrm{{diag}}((\\sigma^{{(g)}})^2)),
\\quad
\\mu^{{(g+1)}} = \\frac{{1}}{{|E_g|}}\\sum_{{j\\in E_g}}\\theta_j^{{(g)}},
\\]
\\[
\\sigma^{{(g+1)}} = \\max\\Bigl(\\sigma_{{\\min}},\\,
\\sqrt{{\\frac{{1}}{{|E_g|}}\\sum_{{j\\in E_g}} (\\theta_j^{{(g)}}-\\mu^{{(g+1)}})^2}}\\Bigr)
\\]
で行った。

\\section{{探索設定}}
ソース profile: \\path{{{source_profile_label}}}

評価用 reference-free profile: \\path{{{eval_profile_label}}}

探索は coarse simulation で実施し、最終候補は同一モードで再評価した。

\\begin{{longtable}}{{p{{0.42\\linewidth}}p{{0.22\\linewidth}}}}
\\toprule
項目 & 値 \\\\
\\midrule
\\endhead
最適化次元 & {len(specs)} \\\\
世代数 & {int(search_cfg.get('generations', 0))} \\\\
各世代 population & {int(search_cfg.get('population', 0))} \\\\
elite 数 & {int(search_cfg.get('elite_count', 0))} \\\\
validation top-k & {int(search_cfg.get('validation_top_k', 0))} \\\\
シナリオモード & {latex_escape(str(search_cfg.get('scenario_mode', 'nominal')))} \\\\
planning race km & {float(search_cfg.get('planning_race_km', 0.0)):.3f} \\\\
探索候補数 (coarse) & {search_candidates} \\\\
coarse upper\\_max\\_iter & {int(search_cfg.get('coarse_upper_max_iter', 0))} \\\\
各世代 medium refine top-k & {int(search_cfg.get('elite_medium_top_k', 0))} \\\\
medium refine upper\\_max\\_iter & {int(search_cfg.get('elite_medium_upper_max_iter', 0))} \\\\
validation upper\\_max\\_iter & {int(search_cfg.get('validation_upper_max_iter', 0))} \\\\
TensorBoard log & {"generated" if tensorboard_label else "not generated"} \\\\
trial あたり CPU 秒中央値 & {median_cpu_sec:.2f} \\\\
population={int(search_cfg.get('population', 0))} のまま 10000 世代へ拡張した概算 CPU 日数 & {estimated_10000_gen_cpu_days:.1f} \\\\
\\bottomrule
\\end{{longtable}}
"""
    if tensorboard_label:
        tex += f"\\noindent TensorBoard directory: \\path{{{tensorboard_label}}}\n\n"
    tex += f"""

\\section{{自己学習で有効化された重み}}
\\begin{{itemize}}
"""
    for key, value in active_terms.items():
        tex += f"  \\item {latex_escape(key)} = {float(value):.6g}\n"
    tex += "\\end{itemize}\n\n"
    tex += "\\noindent 無効化された項: " + ", ".join(latex_escape(name) for name in inactive_terms) + "\n\n"
    legacy_structural_note = ""
    try:
        source_cfg_for_notes = read_yaml(Path(source_profile_label)) if source_profile_label else {}
        source_paths = source_cfg_for_notes.get("paths", {}) if isinstance(source_cfg_for_notes, dict) else {}
        source_mpc = source_cfg_for_notes.get("mpc", {}) if isinstance(source_cfg_for_notes, dict) else {}
        source_schedule = str(source_paths.get("drive_schedule_yaml", "") or "")
        source_stops = str(source_paths.get("stop_yaml", "") or "")
        source_race_km = float(source_mpc.get("race_km", 0.0) or 0.0)
        if "actual_drive_schedule" in source_schedule or "actual_stops" in source_stops or abs(source_race_km - actual_retire_km) < 5.0:
            legacy_structural_note = (
                "旧 profile では実リタイア日程や 2831 km 近傍の打ち切り条件が planner に混入しており、"
                "人間未満だった要因の一部は学習不足ではなく構造設定ミスだった。"
            )
    except Exception:
        legacy_structural_note = ""
    tex += f"""
\\section{{なぜまだ人間レベルに未達か}}
実走リタイア距離 {actual_retire_km:.1f} km に対し、今回の self-learned plan の
{latex_escape(score_label)}代表到達距離は {float(tuned_result['final_distance_km']):.2f} km であり、
差は {human_gap_km:.2f} km 残っている。主因は次の 3 つである。
\\begin{{enumerate}}
  \\item モデル誤差: 現在の replay 誤差は power RMSE={power_rmse_fit:.2f} W,
  voltage RMSE={voltage_rmse_fit:.3f} V であり、まだ race-level のエネルギー配分を
  完全に再現するには十分小さいとは言えない。
  \\item 探索量不足: 今回の outer-loop 探索は {len(specs)} 次元に対し
  coarse 候補 {search_candidates} 本であり、一般的な深層 RL の
  数千〜1万世代級更新とは計算予算が大きく異なる。
"""
    if str(search_cfg.get("scenario_mode", "nominal")) == "robust":
        tex += r"""
  \item ロバスト化による保守化: 3 シナリオの worst-case も得点へ入れているため、
  速さ一点張りより安全余裕を取る方向に重みが寄る。
"""
    else:
        tex += r"""
  \item 目的関数と離散化の残課題: 名目モードへ切り替えても、日末 SoC 制約、速度平滑化、
  電流・出力スルー抑制、時間離散化 $\Delta t$ の影響で、まだ人間の細かな攻め方を
  取り切れていない。
"""
    tex += r"""
\\end{{enumerate}}

したがって、「上位重みの学習が弱い」だけでなく、
\\emph{{モデル誤差と探索予算、そして cost/離散化設計}} が未達要因である。
"""
    if legacy_structural_note:
        tex += f"\n\\noindent {latex_escape(legacy_structural_note)}\n"
    tex += r"""

\\section{{RL 的なモデル補正について}}
MPC 重みの自己学習と、物理モデルそのものの同定は分けて扱う方が安全である。
前者は race score を直接目的にできる一方、後者まで同時に自由化すると、
score が上がっても物理量が壊れて外挿に弱くなる危険がある。
このため今回の流れは、
\\begin{{enumerate}}
  \\item 先に replay 誤差を詰める fit
  \\item その後に固定モデル上で upper cost を自己学習
\\end{{enumerate}}
とした。今後 RL 的にモデル補正を入れるなら、$C_dA, C_{{rr}}, k_\\eta, k_w$ のような
\\emph{{少数の補正係数}} に限定し、事前分布と許容範囲を強く入れたうえで
residual minimization を行うのが安全である。

\\section{{baseline と self-learned の比較}}
\\begin{{longtable}}{{p{{0.40\\linewidth}}p{{0.22\\linewidth}}p{{0.22\\linewidth}}}}
\\toprule
metric & baseline & self-learned \\\\
\\midrule
\\endhead
{latex_escape(score_label)} & {float(baseline_result['score']):.3f} & {float(tuned_result['score']):.3f} \\\\
mean score & {float(baseline_result['score_mean']):.3f} & {float(tuned_result['score_mean']):.3f} \\\\
worst-case score & {float(baseline_result['score_worst']):.3f} & {float(tuned_result['score_worst']):.3f} \\\\
mean final distance [km] & {float(baseline_result['final_distance_km']):.2f} & {float(tuned_result['final_distance_km']):.2f} \\\\
worst final distance [km] & {float(baseline_result['final_distance_worst_km']):.2f} & {float(tuned_result['final_distance_worst_km']):.2f} \\\\
mean abs speed step [km/h] & {float(baseline_result['oscillation_mean_abs_dv_kmh']):.3f} & {float(tuned_result['oscillation_mean_abs_dv_kmh']):.3f} \\\\
p95 abs speed step [km/h] & {float(baseline_result['oscillation_p95_abs_dv_kmh']):.3f} & {float(tuned_result['oscillation_p95_abs_dv_kmh']):.3f} \\\\
pack current rms [A] & {float(baseline_result['current_rms_a']):.3f} & {float(tuned_result['current_rms_a']):.3f} \\\\
pack power slew rms [kW] & {float(baseline_result['pack_slew_rms_kw']):.3f} & {float(tuned_result['pack_slew_rms_kw']):.3f} \\\\
daylight stop [h] & {float(baseline_result['daylight_stop_h']):.3f} & {float(tuned_result['daylight_stop_h']):.3f} \\\\
daylight high-soc [h] & {float(baseline_result['daylight_full_soc_h']):.3f} & {float(tuned_result['daylight_full_soc_h']):.3f} \\\\
weighted final SoC [-] & {float(baseline_result['final_soc']):.4f} & {float(tuned_result['final_soc']):.4f} \\\\
\\bottomrule
\\end{{longtable}}

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.92\\linewidth]{{{tex_path_rel(learning_png)}}}
  \\caption{{探索履歴}}
\\end{{figure}}

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.92\\linewidth]{{{tex_path_rel(scenario_compare_png)}}}
  \\caption{{シナリオ別到達距離}}
\\end{{figure}}

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.92\\linewidth]{{{tex_path_rel(speed_compare_png)}}}
  \\caption{{名目シナリオ速度比較}}
\\end{{figure}}

\\begin{{figure}}[H]
  \\centering
  \\includegraphics[width=0.92\\linewidth]{{{tex_path_rel(soc_compare_png)}}}
  \\caption{{名目シナリオ SoC 比較}}
\\end{{figure}}
"""
    if not iter_compare_df.empty:
        tex += f"""

\\section{{upper\\_max\\_iter 比較}}
同一の tuned profile に対し、軽量オフライン条件
($\\Delta t=2400\\,\\mathrm{{s}}$, upper\\_max\\_steps=10, reference speed tracking off)
で \\path{{mpc.upper\\_max\\_iter}} を比較した。

\\scriptsize
{iter_compare_df[['upper_max_iter', 'final_distance_km', 'final_soc', 'min_soc', 'avg_speed_kmh', 'cpu_sec']].to_latex(index=False, escape=True, float_format="%.6g")}
\\normalsize

この比較では、反復回数を増やせば単調に良くなるわけではなく、
\\emph{{現在は solver iteration 数よりも cost 設計とモデル誤差の影響が支配的}}
であることが分かる。
"""
    tex += f"""

\\section{{シナリオ別比較表}}
\\scriptsize
{scenario_df.to_latex(index=False, escape=True, float_format="%.6g")}
\\normalsize

\\section{{現在使用中のマップと係数}}
以下のファイルを自動出力した。
\\begin{{itemize}}
  \\item active files csv: \\path{{{files_csv_label}}}
  \\item scalar coefficients csv: \\path{{{scalars_csv_label}}}
  \\item summary markdown: \\path{{{markdown_label}}}
  \\item best upper cost csv: \\path{{{best_weights_csv_label}}}
  \\item fit summary csv: \\path{{{fit_csv.as_posix()}}}
\\end{{itemize}}

\\section{{試行一覧}}
\\scriptsize
{trials_df[['trial_index', 'generation', 'candidate', 'score', 'score_mean', 'score_worst', 'final_distance_km', 'final_distance_worst_km', 'avg_speed_kmh', 'min_soc', 'final_soc', 'oscillation_mean_abs_dv_kmh', 'current_rms_a', 'pack_slew_rms_kw']].to_latex(index=False, escape=True, longtable=True, float_format="%.6g")}
\\normalsize

\\section{{参考文献と一次ソース}}
\\begin{{enumerate}}
"""
    for item in LITERATURE:
        tex += f"  \\item {latex_escape(item['label'])}: {latex_escape(item['title'])}. \\url{{{item['url']}}}\n"
    tex += "\\end{enumerate}\n\n\\end{document}\n"

    tex_path = report_dir / "self_learning_upper_planner_report.tex"
    tex_path.write_text(textwrap.dedent(tex).strip() + "\n", encoding="utf-8", newline="\n")
    compile_tex(tex_path)

    md_lines = [
        "# BWSC2025 self-learning upper-planner tuning",
        "",
        f"- source profile: `{source_profile_label}`",
        f"- evaluation profile: `{eval_profile_label}`",
        f"- removed human reference: `{removed_reference_label}`",
        f"- optimization dimensions: `{len(specs)}`",
        f"- scenario mode: `{search_cfg.get('scenario_mode', 'nominal')}`",
        f"- planning race km: `{float(search_cfg.get('planning_race_km', 0.0)):.3f}`",
        f"- coarse candidates: `{search_candidates}`",
        f"- coarse upper_max_iter: `{int(search_cfg.get('coarse_upper_max_iter', 0))}`",
        f"- medium-refine top-k: `{int(search_cfg.get('elite_medium_top_k', 0))}`",
        f"- medium-refine upper_max_iter: `{int(search_cfg.get('elite_medium_upper_max_iter', 0))}`",
        f"- validation upper_max_iter: `{int(search_cfg.get('validation_upper_max_iter', 0))}`",
        f"- tensorboard: `{tensorboard_label or '(not generated)'}`",
        "",
        "## Aggregate result",
        "",
        f"- baseline {score_label}: `{baseline_result['score']:.3f}`",
        f"- self-learned {score_label}: `{tuned_result['score']:.3f}`",
        f"- baseline mean distance [km]: `{baseline_result['final_distance_km']:.2f}`",
        f"- self-learned mean distance [km]: `{tuned_result['final_distance_km']:.2f}`",
        f"- baseline worst distance [km]: `{baseline_result['final_distance_worst_km']:.2f}`",
        f"- self-learned worst distance [km]: `{tuned_result['final_distance_worst_km']:.2f}`",
        f"- actual retire distance [km]: `{actual_retire_km:.2f}`",
        f"- human gap [km]: `{human_gap_km:.2f}`",
        f"- replay power RMSE [W]: `{power_rmse_fit:.2f}`",
        f"- replay voltage RMSE [V]: `{voltage_rmse_fit:.3f}`",
        "",
        "## Best weights",
        "",
        dataframe_to_markdown(best_weights_df),
        "",
        "## Scenario comparison",
        "",
        dataframe_to_markdown(scenario_df),
        "",
        "## upper_max_iter comparison",
        "",
        dataframe_to_markdown(iter_compare_df[['upper_max_iter', 'final_distance_km', 'final_soc', 'min_soc', 'avg_speed_kmh', 'cpu_sec']]) if not iter_compare_df.empty else "(not run)",
        "",
        "## Current maps and coefficients",
        "",
        f"- files csv: `{files_csv_label}`",
        f"- scalars csv: `{scalars_csv_label}`",
        f"- markdown: `{markdown_label}`",
        "",
        "## Primary literature",
        "",
    ]
    for item in LITERATURE:
        md_lines.append(f"- {item['label']}: [{item['title']}]({item['url']})")
    md_path = report_dir / "self_learning_upper_planner_report.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8", newline="\n")
    return tex_path, md_path                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def main() -> None:                                                # [関数定義] main の処理実行ブロック
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile_yaml", default=os.fspath(DEFAULT_PROFILE))
    ap.add_argument("--output_profile_yaml", default="")
    ap.add_argument("--generations", type=int, default=16)
    ap.add_argument("--population", type=int, default=8)
    ap.add_argument("--elite_count", type=int, default=3)
    ap.add_argument("--validation_top_k", type=int, default=5)
    ap.add_argument("--elite_medium_top_k", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--include_progress_terms", action="store_true")
    ap.add_argument("--scenario-mode", choices=["nominal", "robust"], default="nominal")
    ap.add_argument("--coarse-upper-max-iter", type=int, default=1)
    ap.add_argument("--elite-medium-upper-max-iter", type=int, default=3)
    ap.add_argument("--validation-upper-max-iter", type=int, default=8)
    args = ap.parse_args()

    profile_yaml = Path(args.profile_yaml).resolve()
    profile_cfg = read_yaml(profile_yaml)
    base_cost_cfg = load_upper_cost_config(profile_cfg.get("mpc", {}), legacy=profile_cfg.get("mpc", {}))
    scenario_mode = str(args.scenario_mode).strip().lower()
    include_terminal_term = float(profile_cfg.get("mpc", {}).get("soc_finish_target", -1.0)) > 0.0
    include_uncertainty_term = scenario_mode != "nominal"
    base_cost_seed = base_cost_cfg.to_dict()
    if not include_uncertainty_term:
        base_cost_seed["w_uncertainty_reserve"] = 0.0
        base_cost_seed["reserve_soc_per_hour"] = 0.0
        base_cost_seed["reserve_soc_max_extra"] = 0.0
    if not include_terminal_term:
        base_cost_seed["w_soc_terminal"] = 0.0
    base_cost_cfg = UpperCostConfig(**base_cost_seed)
    specs = upper_cost_specs(
        base_cost_cfg,
        include_progress_terms=args.include_progress_terms,
        include_uncertainty_term=include_uncertainty_term,
        include_terminal_term=include_terminal_term,
    )
    rng = np.random.default_rng(args.seed)
    planning_race_km = float(profile_cfg.get("mpc", {}).get("race_km", 3035.5))

    package_dir = profile_yaml.parent
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = package_dir / "outputs" / "self_learning_upper" / timestamp
    ensure_dir(output_dir)
    tensorboard_dir = output_dir / "tensorboard"
    tb_writer = SummaryWriter(log_dir=os.fspath(tensorboard_dir)) if SummaryWriter is not None else None

    eval_profile_yaml, removed_reference = build_reference_free_profile(
        profile_yaml,
        output_dir,
        disable_uncertainty_reserve=(scenario_mode == "nominal"),
    )
    fit_summary_path = package_dir / "outputs" / "identification" / f"{package_dir.name}_fit_summary.yaml"
    fit_summary = read_yaml(fit_summary_path) if fit_summary_path.exists() else {}
    manifest_paths = build_current_asset_manifests(profile_yaml, fit_summary, output_dir)

    coarse_cfg_overrides = {
        "mpc.dt": 5400.0,
        "mpc.upper_horizon_mode": "adaptive_full_race",
        "mpc.upper_max_iter": int(args.coarse_upper_max_iter),
        "mpc.upper_max_steps": 6,
        "mpc.race_km": planning_race_km,
        "mpc.upper_horizon_km": planning_race_km,
        "mpc.upper_ctrl_km": 700.0,
        "mpc.upper_replan_km": 0.0,
        "mpc.upper_replan_sec": 0.0,
        "mpc.upper_adaptive_min_ds_km": 20.0,
        "mpc.upper_adaptive_max_ds_km": 400.0,
        "mpc.upper_adaptive_growth": 1.30,
        "mpc.reference_speed_tracking.enabled": False,
        "mpc.upper_cost.w_uncertainty_reserve": 0.0 if scenario_mode == "nominal" else float(base_cost_cfg.w_uncertainty_reserve),
        "mpc.upper_cost.reserve_soc_per_hour": 0.0 if scenario_mode == "nominal" else float(base_cost_cfg.reserve_soc_per_hour),
        "mpc.upper_cost.reserve_soc_max_extra": 0.0 if scenario_mode == "nominal" else float(base_cost_cfg.reserve_soc_max_extra),
    }
    coarse_cli_overrides = {}

    validation_cfg_overrides = {
        "mpc.dt": 2400.0,
        "mpc.upper_horizon_mode": "adaptive_full_race",
        "mpc.upper_max_iter": int(args.validation_upper_max_iter),
        "mpc.upper_max_steps": 10,
        "mpc.race_km": planning_race_km,
        "mpc.upper_horizon_km": planning_race_km,
        "mpc.upper_ctrl_km": 500.0,
        "mpc.upper_replan_km": 0.0,
        "mpc.upper_replan_sec": 0.0,
        "mpc.upper_adaptive_min_ds_km": 20.0,
        "mpc.upper_adaptive_max_ds_km": 350.0,
        "mpc.upper_adaptive_growth": 1.28,
        "mpc.reference_speed_tracking.enabled": False,
        "mpc.upper_cost.w_uncertainty_reserve": 0.0 if scenario_mode == "nominal" else float(base_cost_cfg.w_uncertainty_reserve),
        "mpc.upper_cost.reserve_soc_per_hour": 0.0 if scenario_mode == "nominal" else float(base_cost_cfg.reserve_soc_per_hour),
        "mpc.upper_cost.reserve_soc_max_extra": 0.0 if scenario_mode == "nominal" else float(base_cost_cfg.reserve_soc_max_extra),
    }
    validation_cli_overrides = {}

    medium_cfg_overrides = {
        "mpc.dt": 3600.0,
        "mpc.upper_horizon_mode": "adaptive_full_race",
        "mpc.upper_max_iter": int(args.elite_medium_upper_max_iter),
        "mpc.upper_max_steps": 8,
        "mpc.race_km": planning_race_km,
        "mpc.upper_horizon_km": planning_race_km,
        "mpc.upper_ctrl_km": 600.0,
        "mpc.upper_replan_km": 0.0,
        "mpc.upper_replan_sec": 0.0,
        "mpc.upper_adaptive_min_ds_km": 20.0,
        "mpc.upper_adaptive_max_ds_km": 380.0,
        "mpc.upper_adaptive_growth": 1.29,
        "mpc.reference_speed_tracking.enabled": False,
        "mpc.upper_cost.w_uncertainty_reserve": 0.0 if scenario_mode == "nominal" else float(base_cost_cfg.w_uncertainty_reserve),
        "mpc.upper_cost.reserve_soc_per_hour": 0.0 if scenario_mode == "nominal" else float(base_cost_cfg.reserve_soc_per_hour),
        "mpc.upper_cost.reserve_soc_max_extra": 0.0 if scenario_mode == "nominal" else float(base_cost_cfg.reserve_soc_max_extra),
    }
    medium_cli_overrides = {}

    scenarios = default_scenarios(eval_profile_yaml, mode=scenario_mode)
    base_weights = base_cost_cfg.to_dict()
    if scenario_mode == "nominal":
        base_weights["w_uncertainty_reserve"] = 0.0
        base_weights["reserve_soc_per_hour"] = 0.0
        base_weights["reserve_soc_max_extra"] = 0.0

    baseline_exact = run_candidate(
        eval_profile_yaml,
        output_dir,
        "validation_baseline",
        base_weights,
        validation_cfg_overrides,
        validation_cli_overrides,
        scenarios,
    )
    baseline_exact["generation"] = -1
    baseline_exact["trial_index"] = -1
    log_trial_to_tensorboard(tb_writer, "baseline", baseline_exact, 0)

    mean = np.array([spec.init_log10 for spec in specs], dtype=float)
    sigma = np.array([0.75] * len(specs), dtype=float)
    trials = []
    best_result = None
    trial_index = 0

    for generation in range(args.generations):
        generation_results = []
        for pop_idx in range(args.population):
            if generation == 0 and pop_idx == 0:
                vec = mean.copy()
            else:
                vec = rng.normal(mean, sigma)
            for idx, spec in enumerate(specs):
                vec[idx] = np.clip(vec[idx], spec.lo, spec.hi)
            weights = vector_to_weights(specs, vec, base_cost_cfg)
            weights["w_progress_lag"] = 0.0 if not args.include_progress_terms else weights.get("w_progress_lag", 0.0)
            weights["w_progress_terminal_lag"] = 0.0 if not args.include_progress_terms else weights.get("w_progress_terminal_lag", 0.0)
            result = run_candidate(
                eval_profile_yaml,
                output_dir,
                f"g{generation:02d}_p{pop_idx:02d}",
                weights,
                coarse_cfg_overrides,
                coarse_cli_overrides,
                scenarios,
            )
            result["generation"] = generation
            result["trial_index"] = trial_index
            result["vector"] = vec.tolist()
            result["phase"] = "coarse"
            result["coarse_score"] = float(result["score"])
            result["selection_score"] = float(result["score"])
            trials.append(result)
            generation_results.append(result)
            trial_index += 1
            if best_result is None or float(result["selection_score"]) > float(best_result.get("selection_score", best_result["score"])):
                best_result = dict(result)
            log_trial_to_tensorboard(tb_writer, "coarse", result, trial_index)
            save_trial_checkpoint(output_dir, trials, best_result)

        refine_pool_size = min(len(generation_results), max(1, args.elite_medium_top_k, args.elite_count))
        refine_pool = sorted(generation_results, key=lambda row: float(row["selection_score"]), reverse=True)[:refine_pool_size]
        for refine_rank, coarse_result in enumerate(refine_pool):
            medium_result = run_candidate(
                eval_profile_yaml,
                output_dir,
                f"m{generation:02d}_r{refine_rank:02d}_{coarse_result['candidate']}",
                coarse_result["weights"],
                medium_cfg_overrides,
                medium_cli_overrides,
                scenarios,
            )
            medium_result["generation"] = generation
            medium_result["trial_index"] = trial_index
            medium_result["vector"] = coarse_result["vector"]
            medium_result["phase"] = "medium_refine"
            medium_result["coarse_candidate"] = coarse_result["candidate"]
            medium_result["coarse_score"] = float(coarse_result["coarse_score"])
            medium_result["selection_score"] = float(medium_result["score"])
            coarse_result["medium_score"] = float(medium_result["score"])
            coarse_result["selection_score"] = float(medium_result["score"])
            coarse_result["medium_final_distance_km"] = float(medium_result["final_distance_km"])
            coarse_result["medium_min_soc"] = float(medium_result["min_soc"])
            coarse_result["medium_final_soc"] = float(medium_result["final_soc"])
            coarse_result["phase"] = "coarse+medium"
            trials.append(medium_result)
            trial_index += 1
            if best_result is None or float(coarse_result["selection_score"]) > float(best_result.get("selection_score", best_result["score"])):
                best_result = dict(coarse_result)
            log_trial_to_tensorboard(tb_writer, "medium_refine", medium_result, trial_index)
            save_trial_checkpoint(output_dir, trials, best_result)

        elite = sorted(generation_results, key=lambda row: float(row["selection_score"]), reverse=True)[: max(1, args.elite_count)]
        elite_vecs = np.array([row["vector"] for row in elite], dtype=float)
        mean = elite_vecs.mean(axis=0)
        sigma = np.maximum(elite_vecs.std(axis=0), 0.15)

    if best_result is None:
        raise RuntimeError("No candidate was evaluated.")

    coarse_trials = [row for row in trials if str(row.get("phase", "")) != "medium_refine"]
    validation_pool = sorted(
        coarse_trials,
        key=lambda row: float(row.get("selection_score", row["score"])),
        reverse=True,
    )[: max(1, args.validation_top_k)]
    validation_results = []
    tuned_validation = None
    for rank, coarse_candidate in enumerate(validation_pool):
        validation_result = run_candidate(
            eval_profile_yaml,
            output_dir,
            f"validation_top{rank:02d}_{coarse_candidate['candidate']}",
            coarse_candidate["weights"],
            validation_cfg_overrides,
            validation_cli_overrides,
            scenarios,
        )
        validation_result["generation"] = args.generations
        validation_result["trial_index"] = trial_index
        validation_result["coarse_candidate"] = coarse_candidate["candidate"]
        trials.append(validation_result)
        validation_results.append(validation_result)
        trial_index += 1
        if tuned_validation is None or float(validation_result["score"]) > float(tuned_validation["score"]):
            tuned_validation = validation_result
        log_trial_to_tensorboard(tb_writer, "validation", validation_result, trial_index)
        save_trial_checkpoint(output_dir, trials, best_result)

    if tuned_validation is None:
        raise RuntimeError("Validation stage produced no result.")

    trials_df = pd.DataFrame(trials)
    best_weights_yaml = output_dir / "best_upper_cost.yaml"
    write_yaml(best_weights_yaml, {"upper_cost": tuned_validation["weights"]})

    tuned_profile_cfg = read_yaml(profile_yaml)
    mirror_legacy_weights(tuned_profile_cfg, tuned_validation["weights"])
    notes = tuned_profile_cfg.setdefault("meta", {}).setdefault("notes", [])
    if isinstance(notes, list):
        notes.append("Upper planner weights tuned by autonomous self-learning CEM search without human progress reference.")
    backup_profile = profile_yaml.with_name(profile_yaml.stem + "_before_self_learning_tuning.yaml")
    if not backup_profile.exists():
        shutil.copy2(profile_yaml, backup_profile)
    if args.output_profile_yaml:
        output_profile_yaml = Path(args.output_profile_yaml).resolve()
    else:
        output_profile_yaml = profile_yaml.with_name(profile_yaml.stem + f"_selflearned_upper_cost_{timestamp}.yaml")
    write_yaml(output_profile_yaml, tuned_profile_cfg)
    snapshot_profile = output_dir / "profile_after_self_learning_tuning.yaml"
    write_yaml(snapshot_profile, tuned_profile_cfg)

    tex_path, md_path = render_report(
        output_dir,
        profile_yaml,
        eval_profile_yaml,
        fit_summary,
        baseline_exact,
        tuned_validation,
        trials_df,
        tuned_validation["weights"],
        manifest_paths,
        removed_reference,
        specs,
        {
            "generations": args.generations,
            "population": args.population,
            "elite_count": args.elite_count,
            "validation_top_k": args.validation_top_k,
            "scenario_mode": scenario_mode,
            "planning_race_km": planning_race_km,
            "include_terminal_term": include_terminal_term,
            "include_uncertainty_term": include_uncertainty_term,
            "coarse_upper_max_iter": args.coarse_upper_max_iter,
            "elite_medium_top_k": args.elite_medium_top_k,
            "elite_medium_upper_max_iter": args.elite_medium_upper_max_iter,
            "validation_upper_max_iter": args.validation_upper_max_iter,
        },
        tensorboard_dir if tb_writer is not None else None,
    )
    if tb_writer is not None:
        tb_writer.flush()
        tb_writer.close()

    summary_payload = {
        "profile_yaml": os.fspath(profile_yaml),
        "reference_free_profile_yaml": os.fspath(eval_profile_yaml),
        "backup_profile_yaml": os.fspath(backup_profile),
        "snapshot_profile_yaml": os.fspath(snapshot_profile),
        "tuned_profile_yaml": os.fspath(output_profile_yaml),
        "best_upper_cost_yaml": os.fspath(best_weights_yaml),
        "trial_results_csv": os.fspath(output_dir / "trial_results.csv"),
        "baseline_validation": baseline_exact,
        "validation_candidates": validation_results,
        "tuned_validation": tuned_validation,
        "current_active_files_csv": os.fspath(manifest_paths["files_csv"]),
        "current_scalar_coefficients_csv": os.fspath(manifest_paths["scalars_csv"]),
        "current_maps_and_coefficients_md": os.fspath(manifest_paths["markdown"]),
        "scenario_comparison_csv": os.fspath(output_dir / "scenario_comparison.csv"),
        "tensorboard_dir": os.fspath(tensorboard_dir) if tb_writer is not None else "",
        "report_tex": os.fspath(tex_path),
        "report_pdf": os.fspath(tex_path.with_suffix(".pdf")),
        "report_md": os.fspath(md_path),
    }
    summary_json = output_dir / "self_learning_upper_planner_summary.json"
    summary_json.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary_payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
