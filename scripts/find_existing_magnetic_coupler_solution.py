import argparse
import json
import math
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


PROFILES = {
    "dynamic_existence_v1": {
        "latched_total_max": 0,
        "contact_events_total_max": 0,
        "worst_min_clearance_mm_min": 5.0,
        "max_contact_demand_mm_max": 0.0,
        "mean_turn_signal_ratio_min": 0.10,
        "mean_sensor_peak_n_min": 0.80,
        "package_violation_mm_max": 0.0,
    },
    "escape_aware_existence_v2": {
        "latched_total_max": 0,
        "contact_events_total_max": 0,
        "worst_min_clearance_mm_min": 5.0,
        "max_contact_demand_mm_max": 0.0,
        "mean_turn_signal_ratio_min": 0.10,
        "mean_sensor_peak_n_min": 0.80,
        "package_violation_mm_max": 0.0,
    },
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan existing magnetic coupler result folders and find already-solved cases under a chosen profile."
    )
    parser.add_argument(
        "--outputs-root",
        type=Path,
        default=ROOT / "outputs",
    )
    parser.add_argument(
        "--profile",
        choices=tuple(PROFILES),
        default="dynamic_existence_v1",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_existing_solution_scan_20260702",
    )
    return parser.parse_args()


def finite_or_nan(value):
    if value is None:
        return math.nan
    try:
        return float(value)
    except (TypeError, ValueError):
        return math.nan


def load_case(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    selected_design = data.get("selected_design", {})
    dynamic_validation = data.get("dynamic_validation", {})
    static_assessment = data.get("static_assessment", {})
    return {
        "result_dir": str(path.parent),
        "shape_label": data.get("shape_label"),
        "magnet_sku_id": selected_design.get("magnet_sku_id"),
        "cart_mass_kg": finite_or_nan(selected_design.get("cart_mass_kg")),
        "gap_mm": 1000.0 * finite_or_nan(selected_design.get("gap_m")),
        "mean_radius_mm": 1000.0 * finite_or_nan(selected_design.get("mean_radius_m")),
        "magnets_per_ring": selected_design.get("magnets_per_ring"),
        "magnet_layers": selected_design.get("magnet_layers"),
        "total_magnets": selected_design.get("total_magnets"),
        "estimated_total_cost_jpy": finite_or_nan(selected_design.get("estimated_total_cost_jpy")),
        "latched_total": finite_or_nan(dynamic_validation.get("latched_total")),
        "contact_events_total": finite_or_nan(dynamic_validation.get("contact_events_total")),
        "worst_min_clearance_mm": finite_or_nan(dynamic_validation.get("worst_min_clearance_mm")),
        "max_contact_demand_mm": finite_or_nan(dynamic_validation.get("max_contact_demand_mm")),
        "mean_turn_signal_ratio": finite_or_nan(dynamic_validation.get("mean_turn_signal_ratio")),
        "mean_turn_latency_s": finite_or_nan(dynamic_validation.get("mean_turn_latency_s")),
        "mean_recenter_s": finite_or_nan(dynamic_validation.get("mean_recenter_s")),
        "mean_cue_peak_yaw_deg": finite_or_nan(dynamic_validation.get("mean_cue_peak_yaw_deg")),
        "mean_sensor_peak_n": finite_or_nan(dynamic_validation.get("mean_sensor_peak_n")),
        "mean_height_return_s": finite_or_nan(dynamic_validation.get("mean_height_return_s")),
        "mean_cruise_translation_rms_mm": finite_or_nan(dynamic_validation.get("mean_cruise_translation_rms_mm")),
        "mean_cruise_yaw_rms_deg": finite_or_nan(dynamic_validation.get("mean_cruise_yaw_rms_deg")),
        "package_violation_mm": 1000.0 * finite_or_nan(static_assessment.get("package_violation_m")),
        "negative_yaw_restore_count": finite_or_nan(static_assessment.get("negative_yaw_restore_count")),
        "negative_towed_yaw_restore_count": finite_or_nan(static_assessment.get("negative_towed_yaw_restore_count")),
        "mean_orthogonal_ratio": finite_or_nan(static_assessment.get("mean_orthogonal_ratio")),
        "mean_forward_torque_ratio": finite_or_nan(static_assessment.get("mean_forward_torque_ratio")),
    }


def check_profile(case, profile):
    checks = {
        "latched_total_ok": int(case["latched_total"] <= profile["latched_total_max"]),
        "contact_events_total_ok": int(case["contact_events_total"] <= profile["contact_events_total_max"]),
        "worst_min_clearance_mm_ok": int(case["worst_min_clearance_mm"] >= profile["worst_min_clearance_mm_min"]),
        "max_contact_demand_mm_ok": int(case["max_contact_demand_mm"] <= profile["max_contact_demand_mm_max"]),
        "mean_turn_signal_ratio_ok": int(case["mean_turn_signal_ratio"] >= profile["mean_turn_signal_ratio_min"]),
        "mean_sensor_peak_n_ok": int(case["mean_sensor_peak_n"] >= profile["mean_sensor_peak_n_min"]),
        "package_violation_mm_ok": int(case["package_violation_mm"] <= profile["package_violation_mm_max"]),
    }
    checks["profile_pass"] = int(all(checks.values()))
    return checks


def ranking_score(case):
    return (
        200.0 * case["profile_pass"]
        + 20.0 * case["latched_total_ok"]
        + 20.0 * case["contact_events_total_ok"]
        + 15.0 * case["worst_min_clearance_mm_ok"]
        + 15.0 * case["max_contact_demand_mm_ok"]
        + 15.0 * case["mean_turn_signal_ratio_ok"]
        + 15.0 * case["mean_sensor_peak_n_ok"]
        + 10.0 * case["package_violation_mm_ok"]
        + case["mean_turn_signal_ratio"]
        + 0.05 * case["mean_sensor_peak_n"]
        + 0.01 * case["worst_min_clearance_mm"]
    )


def build_report_markdown(df: pd.DataFrame, summary: dict, profile_name: str) -> str:
    best_case = summary["best_case"]
    lines = [
        "# 既存解再走査報告",
        "",
        "## 位置づけ",
        "- 本報告は、S0標準シナリオ全体の最終評価ではない。",
        "- 本報告は、既存の磁気カプラ結果群から『少なくとも1解が存在するか』を調べる existence scan である。",
        "- 添付 PDF の指摘に合わせ、過負荷時の `逃がし` は安全機能として扱い、`hold-force 超過` や `dynamic clip` を即失敗条件には入れていない。",
        "",
        "## 使用プロファイル",
        f"- Profile: `{profile_name}`",
        f"- `latched_total <= {summary['profile_definition']['latched_total_max']}`",
        f"- `contact_events_total <= {summary['profile_definition']['contact_events_total_max']}`",
        f"- `worst_min_clearance_mm >= {summary['profile_definition']['worst_min_clearance_mm_min']}`",
        f"- `max_contact_demand_mm <= {summary['profile_definition']['max_contact_demand_mm_max']}`",
        f"- `mean_turn_signal_ratio >= {summary['profile_definition']['mean_turn_signal_ratio_min']}`",
        f"- `mean_sensor_peak_n >= {summary['profile_definition']['mean_sensor_peak_n_min']}`",
        f"- `package_violation_mm <= {summary['profile_definition']['package_violation_mm_max']}`",
        "",
        "## 集計結果",
        f"- 再走査件数: `{summary['result_count']}`",
        f"- 通過件数: `{summary['pass_count']}`",
        "",
        "## 最上位通過解",
        f"- 結果ディレクトリ: `{best_case['result_dir']}`",
        f"- 形状ラベル: `{best_case['shape_label']}`",
        f"- 磁石: `{best_case['magnet_sku_id']}`",
        f"- 台車質量: `{best_case['cart_mass_kg']:.6f} kg`",
        f"- 空隙: `{best_case['gap_mm']:.3f} mm`",
        f"- 平均半径: `{best_case['mean_radius_mm']:.3f} mm`",
        f"- 磁石数: `{int(best_case['magnets_per_ring'])} / ring`",
        f"- 層数: `{int(best_case['magnet_layers'])}`",
        f"- 総磁石数: `{int(best_case['total_magnets'])}`",
        f"- 推定コスト: `{best_case['estimated_total_cost_jpy']:.1f} JPY`",
        "",
        "## 成立指標",
        f"- `latched_total = {best_case['latched_total']:.0f}`",
        f"- `contact_events_total = {best_case['contact_events_total']:.0f}`",
        f"- `worst_min_clearance_mm = {best_case['worst_min_clearance_mm']:.6f}`",
        f"- `max_contact_demand_mm = {best_case['max_contact_demand_mm']:.6f}`",
        f"- `mean_turn_signal_ratio = {best_case['mean_turn_signal_ratio']:.6f}`",
        f"- `mean_sensor_peak_n = {best_case['mean_sensor_peak_n']:.6f}`",
        f"- `package_violation_mm = {best_case['package_violation_mm']:.6f}`",
        "",
        "## 解釈",
        "- この通過は『最終理想解に到達した』ことを意味しない。",
        "- ただし、『接触なし・ラッチなし・有効な入力感知あり』という最低限の existence は確認できたことを意味する。",
        "- したがって、以後の探索はこの通過解を起点に、高質量側・高安定性側へ押し広げるのが妥当である。",
    ]
    return "\n".join(lines)


def main():
    args = parse_args()
    args.outdir.mkdir(parents=True, exist_ok=True)
    profile = PROFILES[args.profile]

    rows = []
    for path in args.outputs_root.rglob("best_design_hifi.json"):
        try:
            case = load_case(path)
        except Exception:
            continue
        case.update(check_profile(case, profile))
        case["ranking_score"] = ranking_score(case)
        rows.append(case)

    if not rows:
        raise SystemExit("No readable best_design_hifi.json files were found.")

    df = pd.DataFrame(rows).sort_values(
        ["profile_pass", "ranking_score", "worst_min_clearance_mm"],
        ascending=[False, False, False],
    )
    df.to_csv(args.outdir / "existing_solution_scan.csv", index=False)

    best_case = df.iloc[0].to_dict()
    summary = {
        "profile_name": args.profile,
        "profile_definition": profile,
        "result_count": int(len(df)),
        "pass_count": int(df["profile_pass"].sum()),
        "best_case": best_case,
    }
    (args.outdir / "existing_solution_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (args.outdir / "existing_solution_report_ja.md").write_text(
        build_report_markdown(df, summary, args.profile),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
