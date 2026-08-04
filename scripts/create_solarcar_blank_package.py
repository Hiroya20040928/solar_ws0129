from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

try:
    from build_bwsc2025_fitted_package import compile_tex
    import create_solarcar_only_package as base
except ImportError:
    pass



ROOT = base.ROOT
DEFAULT_OUTPUT = ROOT / "exports" / f"solarcar_blank_package_{datetime.now().strftime('%Y%m%d')}"
PROJECT_PACKAGES = [
    "bwsc2027_template",
    "other_template",
]

BLANK_PROJECT_CSV_DIRS = ("data/route", "data/weather", "data/identification/raw", "maps")


def patch_blank_manual(dst_root: Path) -> None:                    # [関数定義] patch_blank_manual の処理実行ブロック
    md_path = dst_root / "docs" / "solar_all_in_one_manual" / "solar_all_in_one_manual.md"
    tex_path = dst_root / "docs" / "solar_all_in_one_manual" / "solar_all_in_one_manual.tex"

    md_text = md_path.read_text(encoding="utf-8")
    md_start = "## 現在の fitted 例\n"
    md_end = "## 典型コマンド\n"
    if md_start in md_text and md_end in md_text:
        start = md_text.index(md_start)
        end = md_text.index(md_end)
        replacement = """## 空テンプレ配布版
- この配布版には `bwsc2025_public` や過去実走行から作った fitted 実例は含めません。
- 初期状態で使い始める対象は `project_packages/bwsc2027_template/profile.yaml` と `project_packages/other_template/profile.yaml` です。
- route / weather / maps / identification raw を投入した後は、`run_identification_pipeline.py`、`run_vehicle_identification.py`、`SolarSim.ps1` をそのまま使えます。

"""
        md_text = md_text[:start] + replacement + md_text[end:]
    md_text = re.sub(
        r"project_packages/(?:bwsc2025_public|bwsc2025_fitted_[^/\s`]+)/[^\s`]+",
        "project_packages/bwsc2027_template/profile.yaml",
        md_text,
    )
    md_path.write_text(md_text, encoding="utf-8", newline="\n")

    tex_text = tex_path.read_text(encoding="utf-8")
    tex_start = "\\section{現在の maps / coefficients 例}\n"
    tex_end = "\\section{実際の使い方}\n"
    if tex_start in tex_text and tex_end in tex_text:
        start = tex_text.index(tex_start)
        end = tex_text.index(tex_end)
        replacement = r"""\section{空テンプレ配布版}
この配布版には public な大会データや過去実走行から再同定した fitted package を含めず、
\sourcepath{project_packages/bwsc2027_template/} と
\sourcepath{project_packages/other_template/} だけを同梱している。

\begin{itemize}[leftmargin=1.5em]
  \item route, weather, maps, schedule, identification raw をこれから投入する前提の配布版である。
  \item ワークフロー自体は full package と同一であり、\sourcepath{SolarSim.ps1}、
        \sourcepath{scripts/run_identification_pipeline.py}、
        \sourcepath{scripts/run_vehicle_identification.py} をそのまま利用できる。
  \item まずは \sourcepath{project_packages/bwsc2027_template/profile.yaml} を複製し、
        車両固有の paths / model / mpc を埋めていく。
\end{itemize}

"""
        tex_text = tex_text[:start] + replacement + tex_text[end:]
    tex_text = re.sub(
        r"project_packages/(?:bwsc2025_public|bwsc2025_fitted_[^/}\s]+)/[^}\s]+",
        "project_packages/bwsc2027_template/profile.yaml",
        tex_text,
    )
    tex_path.write_text(tex_text, encoding="utf-8", newline="\n")
    compile_tex(tex_path)


def patch_blank_entrypoint(dst_root: Path) -> None:                # [関数定義] patch_blank_entrypoint の処理実行ブロック
    path = dst_root / "SolarSim.ps1"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "[string]$Profile = 'project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml'",
        "[string]$Profile = 'project_packages/bwsc2027_template/profile.yaml'",
    )
    path.write_text(text, encoding="utf-8", newline="\n")


def reset_project_inputs(dst_root: Path) -> list[str]:             # [関数定義] reset_project_inputs の処理実行ブロック
    """Remove sample race/environment/map values while retaining CSV schemas."""
    reset: list[str] = []
    for project_name in PROJECT_PACKAGES:
        project_root = dst_root / "project_packages" / project_name
        for relative_dir in BLANK_PROJECT_CSV_DIRS:
            for path in sorted((project_root / relative_dir).glob("*.csv")):
                lines = path.read_text(encoding="utf-8-sig").splitlines()
                header = lines[0].strip() if lines else ""
                path.write_text((header + "\n") if header else "", encoding="utf-8")
                reset.append(path.relative_to(dst_root).as_posix())

        stops = project_root / "data" / "race" / "control_stops.yaml"
        schedule = project_root / "data" / "race" / "drive_schedule.yaml"
        if stops.exists():
            stops.write_text("stops: []\n", encoding="utf-8")
            reset.append(stops.relative_to(dst_root).as_posix())
        if schedule.exists():
            schedule.write_text("windows: []\n", encoding="utf-8")
            reset.append(schedule.relative_to(dst_root).as_posix())
    return sorted(reset)                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却


def write_readme(dst_root: Path, removed: list[str]) -> None:      # [関数定義] write_readme の処理実行ブロック
    readme = dst_root / "README_SOLAR_BLANK.md"
    lines = [
        "# ソーラーカー空パッケージ",
        "",
        "ソーラーカーEMSの全機能と資料を保持し、車両・コース・天候・実測ログだけをスキーマ付き空入力にした新規車両向け配布版です。",
        "",
        "## 最初に読むもの",
        "- 全機能と物理・数式: `docs/solar_all_in_one_manual/solar_all_in_one_manual.pdf`",
        "- Windows/Ubuntu導入と全モード手順: `docs/deployment_operation_manual/solar_mpc_deployment_operation_manual.pdf`",
        "- MPC手計算問題一式: `docs/complete_flow_workbook/`",
        "- MLE手計算問題一式: `docs/mle_hand_calculation_workbook/`",
        "- 全ソース一覧: `docs/package_inventory/package_source_inventory.md`",
        "",
        "## 含まないもの",
        "- BWSC 2025実データ・同定済み車体、PASSO、燃料計、磁気カプラを含みません。",
        "",
        "## 新規車両を完成させる順序",
        "1. `project_packages/bwsc2027_template` を複製し、車両名へ変更します。",
        "2. route、weather、schedule、製品/試験根拠付きmap、実測時系列CSVを各雛形へ入力します。",
        "3. `powershell -ExecutionPolicy Bypass -File .\\SolarSim.ps1 -Action fit -Profile project_packages/<vehicle>/profile.yaml` を実行します。",
        "4. 独立検証ログのRMSE、物理境界、終端SoC根拠が受入基準を満たすまでデータとモデルを修正します。",
        "5. `powershell -ExecutionPolicy Bypass -File .\\SolarSim.ps1 -Action learn -Profile project_packages/<vehicle>/profile.yaml` で上位目的関数を探索します。",
        "6. `powershell -ExecutionPolicy Bypass -File .\\SolarSim.ps1 -Action simulate -Profile project_packages/<vehicle>/profile.yaml` で大会全行程を検証します。",
        "7. `-Action audit`、preflight、UDP loopback、全行程、shadow-modeに合格後のみ `-Mode live_wifi -Action up` へ進みます。",
        "",
        "コードと資料は同定済み版と同等ですが、値が未入力のため初期状態のシミュレーション結果を車両性能として使用してはいけません。",
        "",
        "## 除外パス一覧",
    ]
    lines.extend(f"- `{item}`" for item in removed)
    content = "\n".join(lines) + "\n"
    readme.write_text(content, encoding="utf-8")
    root_readme = dst_root / "README.md"
    full_manual = root_readme.read_text(encoding="utf-8")
    full_manual = re.sub(
        r"project_packages/bwsc2025_fitted_[^/\s`<]+/[^\s`<]+",
        "project_packages/bwsc2027_template/profile.yaml",
        full_manual,
    )
    full_manual = re.sub(
        r"The evidence record for mle13\s+is <code>.*?</code> inside\s+the fitted project package\.",
        "Create `data/identification/evidence/grounded_map_sources.yaml` in the vehicle project and record every manufacturer curve, official test, and measured map used to build the grounded base model.",
        full_manual,
        flags=re.DOTALL,
    )
    full_manual = re.sub(
        r"Do not call a model high precision from the training residual alone\..*?available\.\n",
        "Do not call a model high precision from the training residual alone. Require held-out replay RMSE, physically bounded coefficients, synchronized BMS coulomb count, rested OCV/temperature, MPPT state, measured POA irradiance, and an independently justified terminal-SoC interval before operational adoption.\n",
        full_manual,
        flags=re.DOTALL,
    )
    full_manual = re.sub(
        r"The two initial SoC values in the fitted example.*?keep\s+them separate\.\n",
        "Keep the operational `simulation.soc0` separate from any latent `identification.fitted_replay_soc0`; the latter may reproduce the first historical sample but must never overwrite the race-start state.\n",
        full_manual,
        flags=re.DOTALL,
    )
    full_manual = re.sub(
        r"## Current MLE\d+ vehicle model\n.*?(?=## Source structure)",
        "## Vehicle model status\n\nThis blank release contains no identified vehicle coefficients or accepted maps. Fill the evidence and measurement templates, run identification, satisfy the independent acceptance gates, and only then use the generated profile for simulation or live control.\n\n",
        full_manual,
        flags=re.DOTALL,
    )
    full_manual = re.sub(
        r"The solar-only distribution keeps the current MLE\d+ fitted example and all operating\n"
        r"functions while removing PASSO, magnetic-coupler, build/install/log, and old\n"
        r"fitted generations\. The blank distribution keeps the same code and manuals but\n"
        r"contains only empty vehicle/race templates\.",
        "This repository is the blank distribution: it keeps the complete operating code and manuals while containing only schema-level vehicle/race templates. It does not include an identified vehicle or an accepted full-race result.",
        full_manual,
    )
    notice = (
        "# 空パッケージについて\n\n"
        "この配布版のroute、weather、map、schedule、replayは意図的にスキーマのみです。"
        "先に `README_SOLAR_BLANK.md` を読み、その後に以下の完全ガイドを使用してください。\n\n"
    )
    root_readme.write_text(notice + full_manual, encoding="utf-8")


def write_manifest(dst_root: Path, removed: list[str], copied: list[str], reset_inputs: list[str]) -> None:  # [関数定義] write_manifest の処理実行ブロック
    payload = {
        "generated_at": datetime.now().isoformat(),
        "source_root": "repository-export-source",
        "output_root": ".",
        "copied_items": copied,
        "removed_items": removed,
        "project_packages": PROJECT_PACKAGES,
        "variant": "blank",
        "reset_input_files": reset_inputs,
    }
    (dst_root / "solarcar_blank_manifest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def build_blank_copy(output_dir: Path, force: bool) -> Path:       # [関数定義] build_blank_copy の処理実行ブロック
    base.prepare_output_dir(output_dir, source_root=ROOT, force=force)

    copied: list[str] = []
    for raw in base.TOP_LEVEL_FILES:
        src = ROOT / raw
        if src.exists():
            base.copy_path(src, output_dir / raw)
            copied.append(raw)
    for raw in base.TOP_LEVEL_DIRS:
        src = ROOT / raw
        if src.exists():
            base.copy_path(src, output_dir / raw)
            copied.append(raw)
    for raw in base.DOC_DIRS:
        src = ROOT / raw
        if src.exists():
            base.copy_path(src, output_dir / raw)
            copied.append(raw)

    project_root = output_dir / "project_packages"
    project_root.mkdir(parents=True, exist_ok=True)
    for name in PROJECT_PACKAGES:
        src = ROOT / "project_packages" / name
        if src.exists():
            base.copy_path(src, project_root / name)
            copied.append(f"project_packages/{name}")

    removed = base.prune_paths(output_dir)
    base.patch_setup_py(output_dir)
    base.patch_mpc_node(output_dir)
    patch_blank_entrypoint(output_dir)
    reset_inputs = reset_project_inputs(output_dir)
    patch_blank_manual(output_dir)
    removed.extend(base.prune_paths(output_dir))
    removed = sorted(set(removed))
    write_readme(output_dir, removed)
    write_manifest(output_dir, removed, copied, reset_inputs)
    base.refresh_quality_artifacts(output_dir)
    return output_dir                                              # [戻り値] 計算結果・計算状態の呼び出し元への返却


def parse_args() -> argparse.Namespace:                            # [関数定義] parse_args の処理実行ブロック
    parser = argparse.ArgumentParser(description="Create a blank solar-car distribution copy with template packages only.")
    parser.add_argument("--output_dir", type=Path, default=DEFAULT_OUTPUT)  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument("--force", action="store_true", help="Replace the output directory if it already exists.")  # [CLI引数] コマンドライン実行引数の定義
    return parser.parse_args()                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却


def main() -> None:                                                # [関数定義] main の処理実行ブロック
    args = parse_args()
    output_dir = build_blank_copy(args.output_dir.resolve(), force=args.force)
    print(output_dir)


if __name__ == "__main__":
    main()