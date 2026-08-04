#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "project_packages" / "bwsc2025_fitted_mle19_energywindow_inertia" / "profile.yaml"
DEFAULT_INVENTORY_JSON = ROOT / "inputs" / "external_docs" / "bwsc2025_20260713" / "extracted" / "inventory_summary.json"
DEFAULT_DOC_ROOT = ROOT / "inputs" / "external_docs" / "bwsc2025_20260713"


ACTUAL_EVENTS = [
    {
        "label": "day2_front_mppt_crimp_fault",
        "kind": "trouble_stop_and_reduced_generation",
        "start_local": "2025-08-25T11:23:55",
        "end_local": "2025-08-25T17:33:55",
        "timezone": "Australia/Darwin",
        "s_km": 0.0,
        "fit_flags": {
            "exclude_power_fit": True,
            "exclude_voltage_fit": False,
            "exclude_weather_fit": True,
        },
        "notes": [
            "BWSC2025 時系列別メモ.pdf より、11:23:55 に前系統の集中MPPTかしめ不足箇所が外れ、17:33:55 に復旧。",
            "報告会資料では『発電量約200W減少』『総損失880Wh』と整理されている。",
        ],
    },
    {
        "label": "day4_low_soc_charge_stop",
        "kind": "strategy_stop",
        "start_local": "2025-08-27T15:30:00",
        "end_local": "2025-08-27T16:20:00",
        "timezone": "Australia/Darwin",
        "s_km": 2053.0,
        "fit_flags": {
            "exclude_power_fit": True,
            "exclude_voltage_fit": False,
            "exclude_weather_fit": False,
        },
        "notes": [
            "BWSC2025 時系列別メモ.pdf では『充電残量ピンチ』による 50 分停止。",
            "報告会資料では、トラブルなし想定なら 15:30 時点で残量 45% 程度で、この停車は不要と整理されている。",
        ],
    },
    {
        "label": "day5_delayed_start_for_charge",
        "kind": "strategy_charge_delay",
        "start_local": "2025-08-28T07:16:00",
        "end_local": "2025-08-28T08:35:00",
        "timezone": "Australia/Darwin",
        "s_km": 2088.0,
        "fit_flags": {
            "exclude_power_fit": False,
            "exclude_voltage_fit": False,
            "exclude_weather_fit": False,
        },
        "notes": [
            "BWSC2025 時系列別メモ.pdf より、朝充電で 35 分追加し出走を遅らせた。",
            "報告会資料では、Day2/Day4 の大トラブルが無ければこの追加遅延は不要としている。",
        ],
    },
    {
        "label": "day6_electrical_trouble_stop",
        "kind": "trouble_stop",
        "start_local": "2025-08-29T09:08:00",
        "end_local": "2025-08-29T10:18:00",
        "timezone": "Australia/Darwin",
        "s_km": 2584.0,
        "fit_flags": {
            "exclude_power_fit": True,
            "exclude_voltage_fit": True,
            "exclude_weather_fit": False,
        },
        "notes": [
            "BWSC2025 時系列別メモ.pdf より、ZP の V 表示異常で 70 分停止。",
            "報告会資料でも Day6 電装系トラブルとして整理されている。",
        ],
    },
    {
        "label": "retire_at_2831km",
        "kind": "retire_event",
        "start_local": "2025-08-29T14:46:00",
        "end_local": "2025-08-29T14:46:00",
        "timezone": "Australia/Darwin",
        "s_km": 2831.0,
        "fit_flags": {
            "exclude_power_fit": True,
            "exclude_voltage_fit": False,
            "exclude_weather_fit": False,
        },
        "notes": [
            "実走リタイア地点は 2831 km。",
            "報告会資料では、ここでの残エネルギー推定から 2961 km 程度までの到達可能性を検討している。",
        ],
    },
]


COUNTERFACTUAL_SCENARIO = {
    "scenario": {
        "name": "bwsc2025_no_trouble_counterfactual",
        "assumptions": [
            "Day2 前系統配線脱落を除去し、発電量低下 200W / 総損失 880Wh を発生させない。",
            "Day4 15:30-16:20 の低 SoC 停車は不要とする。",
            "Day5 朝の追加 35 分充電遅延を除去する。",
            "Day6 09:08-10:18 の電装系トラブル停止を除去する。",
            "実際のコースアウト/破損トラブルは発生しないものとし、3027km まで走行継続を評価する。",
        ],
        "derived_team_analysis": {
            "retire_distance_actual_km": 2831.0,
            "retire_distance_official_km": 2717.6,
            "remaining_energy_estimate_wh": 1335.0,
            "extra_generation_assumption_wh": 450.0,
            "simple_post_retire_reach_estimate_km": 2961.0,
            "control_stop_tilt_generation_gap_wh": 1211.511,
            "day5_counterfactual_reach_km": 2692.0,
            "course_distance_counterfactual_km": 3027.0,
        },
        "notes": [
            "数字は主に 報告会資料_2025_山下将矢.pptx の分析スライドから整理。",
            "このシナリオは fit 用の ground truth ではなく、fit 後の counterfactual simulation 用仮説として扱う。",
        ],
    }
}


def relpath_from(base: Path, target: Path) -> str:
    try:
        return os.path.relpath(target, base).replace("\\", "/")
    except Exception:
        return os.fspath(target)


def read_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        yaml.safe_dump(payload, f, sort_keys=False, allow_unicode=True)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def copy_if_exists(src: Path, dst: Path) -> bool:
    if not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def build_notes(package_dir: Path, inventory_rel: str, grounded_rel: str) -> str:
    return f"""# BWSC2025 evidence bundle

## この bundle の目的

- 実走 replay fit を、単なる時系列再生ではなく、資料に基づく拘束付き同定へ拡張する。
- grounded base map の出典、実レース停車イベント、終端 SoC 根拠、counterfactual 仮説を同じ場所で管理する。
- 将来の別車両でも同じ manifest 形式を流用できるようにする。

## 今回追加した主要根拠

- `BWSC2025 時系列別メモ.pdf`
  - Control stop と trouble stop の開始/終了時刻、実距離、理由。
  - Day2 MPPT かしめ不良、Day4 低 SoC 停車、Day5 追加朝充電、Day6 電装トラブル停止、2831km リタイア位置。
- `BWSC2025バッテリーSoC推測.pdf`
  - 25s6p, 33Ah, 約3011Wh の電池構成。
  - 積算電流法と放電曲線法の 2 系統 SoC 推定。
- `報告会資料_2025_山下将矢.pptx`
  - Day2 損失 880Wh、Day4/5/6 の反実仮想、control stop 上屋開閉による 1211.511Wh ギャップ。
  - 2831km 時点の残エネルギー整理と 2961km までの単純推定。

## grounded map provenance

- 現在の grounded base map provenance は `{grounded_rel}` に保持。
- ここではその provenance を identification manifest から直接参照できるようにしている。

## inventory

- 抽出済みファイル inventory: `{inventory_rel}`

## package reform の意味

1. `data/identification/raw/` は観測時系列そのものを置く。
2. `data/identification/evidence/` は根拠文書・イベント・終端アンカー・counterfactual を置く。
3. `identification_manifest.yaml` は上記両者を結ぶ入口になる。
4. `run_vehicle_identification.py` は event / terminal anchor / grounded provenance を summary/report へ残す。
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.fspath(DEFAULT_PROFILE))
    ap.add_argument("--inventory-json", default=os.fspath(DEFAULT_INVENTORY_JSON))
    ap.add_argument("--doc-root", default=os.fspath(DEFAULT_DOC_ROOT))
    args = ap.parse_args()

    profile_yaml = Path(args.profile).resolve()
    package_dir = profile_yaml.parent
    ident_dir = package_dir / "data" / "identification"
    evidence_dir = ident_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    inventory_json = Path(args.inventory_json).resolve()
    doc_root = Path(args.doc_root).resolve()
    grounded_summary_src = package_dir / "outputs" / "identification" / "grounded_base_maps" / "grounded_map_sources.yaml"
    grounded_summary_dst = evidence_dir / "grounded_map_sources.yaml"
    copied_grounded = copy_if_exists(grounded_summary_src, grounded_summary_dst)

    inventory_dst = evidence_dir / "document_inventory.json"
    if inventory_json.exists():
        copy_if_exists(inventory_json, inventory_dst)
    else:
        inventory_dst.write_text("{}\n", encoding="utf-8")

    actual_event_yaml = evidence_dir / "actual_event_annotations.yaml"
    counterfactual_yaml = evidence_dir / "counterfactual_no_trouble.yaml"
    terminal_anchor_yaml = evidence_dir / "terminal_anchor.yaml"
    notes_md = evidence_dir / "evidence_notes.md"

    write_yaml(actual_event_yaml, {"events": ACTUAL_EVENTS})
    write_yaml(counterfactual_yaml, COUNTERFACTUAL_SCENARIO)
    write_yaml(
        terminal_anchor_yaml,
        {
            "terminal_anchor": {
                "s_km": 2831.0,
                "time_utc": "2025-08-29T05:16:15Z",
                "voltage_v": 88.3,
                "current_a": 6.44,
                "temp_c": 11.261157362503141,
                "soc_target": 0.4347590883866299,
                "soc_sigma": 0.0982157863448273,
                "soc_evidence_min": 0.3322356991079173,
                "soc_evidence_max": 0.5286672717975719,
                "voltage_sigma_v": 1.5,
                "soc_target_basis": (
                    "Unweighted center of loaded-voltage, team remaining-energy, and Day6 "
                    "net-energy channels; the interval, not the center alone, is authoritative."
                ),
                "method": (
                    "Uncertainty-aware fusion of the BWSC2025 battery analysis, observed "
                    "end-state voltage/current/temperature, and Day6 signed net-energy integration."
                ),
                "source_documents": [
                    relpath_from(ROOT, doc_root / "extracted" / "BWSC2025バッテリーSoC推測.txt"),
                    relpath_from(ROOT, doc_root / "extracted" / "報告会資料_2025_山下将矢_slides.txt"),
                ],
                "notes": [
                    "The three channels disagree by 19.64 percentage points, so no one channel is exact truth.",
                    "The broad soc_sigma prevents OCV/Rint or current-integration error from being hidden in the endpoint constraint.",
                    "A rested multi-SoC pulse test and calibrated pack current integral are required before narrowing this interval.",
                ],
            }
        },
    )
    write_text(
        notes_md,
        build_notes(
            package_dir,
            relpath_from(package_dir, inventory_dst),
            relpath_from(package_dir, grounded_summary_dst if copied_grounded else grounded_summary_src),
        ),
    )

    manifest_path = ident_dir / "identification_manifest.yaml"
    manifest = read_yaml(manifest_path) if manifest_path.exists() else {}
    manifest["builder"] = manifest.get("builder", "generic_replay_mle")
    manifest.setdefault("inputs", {})
    manifest["inputs"]["actual_event_yaml"] = relpath_from(package_dir, actual_event_yaml)
    manifest["inputs"]["counterfactual_event_yaml"] = relpath_from(package_dir, counterfactual_yaml)
    manifest["inputs"]["terminal_anchor_yaml"] = relpath_from(package_dir, terminal_anchor_yaml)

    manifest.setdefault("grounded_sources", {})
    manifest["grounded_sources"]["grounded_map_summary_yaml"] = relpath_from(package_dir, grounded_summary_dst if copied_grounded else grounded_summary_src)
    manifest["grounded_sources"]["drive_eff_map_csv"] = "outputs/identification/grounded_base_maps/drive_eff_map.csv"
    manifest["grounded_sources"]["drive_map_eco_csv"] = "outputs/identification/grounded_base_maps/drive_eff_map_eco.csv"
    manifest["grounded_sources"]["drive_map_power_csv"] = "outputs/identification/grounded_base_maps/drive_eff_map_power.csv"
    manifest["grounded_sources"]["regen_eff_map_csv"] = "outputs/identification/grounded_base_maps/regen_eff_map.csv"
    manifest["grounded_sources"]["regen_map_eco_csv"] = "outputs/identification/grounded_base_maps/regen_eff_map_eco.csv"
    manifest["grounded_sources"]["regen_map_power_csv"] = "outputs/identification/grounded_base_maps/regen_eff_map_power.csv"
    manifest["grounded_sources"]["rint_map_csv"] = "outputs/identification/grounded_base_maps/Rint_T_by_soc_grounded.csv"
    manifest["grounded_sources"]["panel_eff_map_csv"] = "outputs/identification/grounded_base_maps/panel_eff_map.csv"
    manifest["grounded_sources"]["mppt_eff_map_csv"] = "outputs/identification/grounded_base_maps/mppt_eff_map.csv"
    manifest["grounded_sources"]["ocv_soc_map_csv"] = "outputs/identification/grounded_base_maps/ocv_soc_curve.csv"

    manifest.setdefault("evidence", {})
    manifest["evidence"]["source_inventory_json"] = relpath_from(package_dir, inventory_dst)
    manifest["evidence"]["notes_markdown"] = relpath_from(package_dir, notes_md)
    manifest["evidence"]["external_documents"] = [
        relpath_from(ROOT, doc_root / "analysis_zip"),
        relpath_from(ROOT, doc_root / "text_zip"),
        relpath_from(ROOT, doc_root / "pptx" / "報告会資料_2025_山下将矢.pptx"),
    ]

    manifest.setdefault("options", {})
    manifest["options"]["terminal_anchor_km"] = 2831.0
    manifest["options"]["use_grounded_base_maps"] = True
    manifest["options"]["allow_map_shape_fit"] = True
    write_yaml(manifest_path, manifest)

    summary = {
        "profile_yaml": os.fspath(profile_yaml),
        "manifest_yaml": os.fspath(manifest_path),
        "actual_event_yaml": os.fspath(actual_event_yaml),
        "counterfactual_yaml": os.fspath(counterfactual_yaml),
        "terminal_anchor_yaml": os.fspath(terminal_anchor_yaml),
        "grounded_map_summary_yaml": os.fspath(grounded_summary_dst if copied_grounded else grounded_summary_src),
        "inventory_json": os.fspath(inventory_dst),
        "notes_markdown": os.fspath(notes_md),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
