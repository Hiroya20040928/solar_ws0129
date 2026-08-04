import json
import math
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(r"C:\Users\user\OneDrive - 和歌山大学\ソーラー\エネマネ\solar_ws0129-main")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_hifi as hifi


OUTDIR = ROOT / "outputs" / "bachelor_thesis_magnetic_coupler_20260630"
FIGDIR = OUTDIR / "figures"
PRIMARY_DIR = ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_limo_stable5"
PRIMARY_CAD_DIR = ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_limo_stable5_cad"
MANUFACTURING_DIR = ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_verticalstack78"
MANUFACTURING_CAD_DIR = ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_verticalstack78_cad"
INTERIM_COMPARE_PNG = ROOT / "outputs" / "magnetic_coupler_shape_progress_compare.png"
THESIS_TEX = OUTDIR / "bachelor_thesis_magnetic_coupler_draft_ja.tex"
THESIS_MD = OUTDIR / "bachelor_thesis_magnetic_coupler_draft_ja.md"
THESIS_PDF = OUTDIR / "bachelor_thesis_magnetic_coupler_draft_ja.pdf"
THESIS_DOCX = OUTDIR / "bachelor_thesis_magnetic_coupler_draft_ja.docx"
MANIFEST_JSON = OUTDIR / "thesis_generation_manifest.json"

THESIS_TITLE = "DAISO 13 mm ネオジム磁石有限配列を用いた高さ可変リング型磁気カプラの設計最適化と高忠実度協調搬送シミュレーション"
TITLE_SHORT = "高さ可変磁気カプラの設計最適化と高忠実度協調搬送シミュレーション"
FISCAL_YEAR = "2026 年度 卒業論文ドラフト"
AUTHOR_NAME = "氏名未設定"
STUDENT_ID = "学籍番号未設定"
ADVISOR_NAME = "指導教員未設定"
DEPARTMENT_NAME = "和歌山大学 システム工学部"
SUBMISSION_DATE = "2026 年 6 月 30 日"
KEYWORDS = [
    "Magnetic coupler",
    "High-fidelity simulation",
    "Finite magnet array",
    "DAISO neodymium magnet",
    "AgileX LIMO",
    "Design optimization",
]


@dataclass(frozen=True)
class ResultBundle:
    name: str
    directory: Path
    cad_directory: Path | None
    payload: dict
    dynamic_validation: pd.DataFrame
    design_history: pd.DataFrame
    policy_history: pd.DataFrame


def tex_escape(text):
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
    return "".join(replacements.get(char, char) for char in str(text))


def load_result(name: str, directory: Path, cad_directory: Path | None) -> ResultBundle:
    payload = json.loads((directory / "best_design_hifi.json").read_text(encoding="utf-8"))
    dynamic_validation = pd.read_csv(directory / "dynamic_validation.csv")
    design_history = pd.read_csv(directory / "design_history.csv")
    policy_history = pd.read_csv(directory / "policy_history.csv")
    return ResultBundle(
        name=name,
        directory=directory,
        cad_directory=cad_directory,
        payload=payload,
        dynamic_validation=dynamic_validation,
        design_history=design_history,
        policy_history=policy_history,
    )


def selected_design(bundle: ResultBundle):
    return bundle.payload["selected_design"]


def static_assessment(bundle: ResultBundle):
    return bundle.payload["static_assessment"]


def dynamic_summary(bundle: ResultBundle):
    return bundle.payload["dynamic_validation"]


def mm(value_m):
    return 1000.0 * float(value_m)


def scenario_aggregate(bundle: ResultBundle) -> pd.DataFrame:
    grouped = (
        bundle.dynamic_validation.groupby("scenario_name")
        .agg(
            mean_score=("score", "mean"),
            worst_score=("score", "min"),
            best_score=("score", "max"),
            mean_clearance_mm=("min_clearance_mm", "mean"),
            mean_translation_rms_mm=("translation_rms_mm", "mean"),
            mean_yaw_rms_deg=("yaw_rms_deg", "mean"),
            mean_turn_signal_ratio=("turn_signal_ratio", "mean"),
            peak_height_shift_mm=("height_shift_peak_mm", "max"),
            peak_input_force_n=("input_force_peak_n", "max"),
            peak_input_torque_nm=("input_torque_peak_nm", "max"),
            peak_magnetic_force_n=("magnetic_force_peak_n", "max"),
        )
        .reset_index()
        .sort_values("worst_score")
    )
    return grouped


def copy_figure(src: Path, dest_name: str) -> str:
    if not src.exists():
        raise FileNotFoundError(src)
    dest = FIGDIR / dest_name
    shutil.copy2(src, dest)
    return f"figures/{dest.name}"


def render_shape_preview(bundle: ResultBundle, dest_name: str) -> str:
    design = selected_design(bundle)
    shape = hifi.ShapeParameters(**design["shape_parameters"])
    geometry = hifi.build_geometry_from_shape(
        shape_params=shape,
        mean_radius_m=design["mean_radius_m"],
        gap_m=design["gap_m"],
        num_samples=512,
    )
    figure, axis = plt.subplots(figsize=(7.4, 7.0), dpi=180)
    axis.fill(
        geometry.outer_points_local[:, 0] * 1000.0,
        geometry.outer_points_local[:, 1] * 1000.0,
        color="#cde6f7",
        alpha=0.75,
    )
    axis.plot(
        geometry.outer_points_local[:, 0] * 1000.0,
        geometry.outer_points_local[:, 1] * 1000.0,
        color="#0f6b87",
        linewidth=2.2,
    )
    axis.fill(
        geometry.inner_points[:, 0] * 1000.0,
        geometry.inner_points[:, 1] * 1000.0,
        color="white",
        zorder=3,
    )
    axis.plot(
        geometry.inner_points[:, 0] * 1000.0,
        geometry.inner_points[:, 1] * 1000.0,
        color="#6b7280",
        linewidth=0.8,
        zorder=4,
    )
    sample_count = min(8, design["magnets_per_ring"])
    sample_index = np.linspace(0, len(geometry.outer_points_local) - 1, sample_count, endpoint=False).astype(int)
    for index in sample_index:
        point = geometry.outer_points_local[index]
        tangent = geometry.outer_tangents_local[index]
        normal = geometry.outer_outward_normals_local[index]
        start = point * 1000.0
        arrow_tail = start - 18.0 * tangent
        arrow_head = start + 18.0 * tangent
        axis.annotate(
            "",
            xy=arrow_head,
            xytext=arrow_tail,
            arrowprops=dict(arrowstyle="->", color="#0f6b87", lw=1.6),
        )
        axis.plot(
            [start[0], start[0] + 6.0 * normal[0]],
            [start[1], start[1] + 6.0 * normal[1]],
            color="#ef6c00",
            linewidth=1.0,
        )
    info = (
        f"gap = {mm(design['gap_m']):.1f} mm\n"
        f"mean radius = {mm(design['mean_radius_m']):.1f} mm\n"
        f"magnets / ring = {design['magnets_per_ring']}\n"
        f"layers = {design['magnet_layers']}\n"
        f"total = {design['total_magnets']}"
    )
    axis.text(
        0.03,
        0.03,
        info,
        transform=axis.transAxes,
        fontsize=10,
        va="bottom",
        ha="left",
        bbox=dict(boxstyle="round", facecolor="white", alpha=0.85, edgecolor="#d1d5db"),
    )
    axis.set_title("Final selected coupler contour")
    axis.set_xlabel("x [mm]")
    axis.set_ylabel("y [mm]")
    axis.set_aspect("equal", adjustable="box")
    axis.grid(True, alpha=0.25)
    figure.tight_layout()
    dest = FIGDIR / dest_name
    figure.savefig(dest, dpi=180)
    plt.close(figure)
    return f"figures/{dest.name}"


def format_candidate_comparison_table(rows: list[dict], latex: bool) -> str:
    headers = [
        "候補",
        "磁石総数",
        "推定費用[JPY]",
        "空隙[mm]",
        "平均半径[mm]",
        "フル剛性[N/m]",
        "低高さ剛性[N/m]",
        "最悪Clear[mm]",
        "接触",
        "ラッチ",
        "平均動的Score",
    ]
    rendered_rows = []
    for row in rows:
        rendered_rows.append(
            [
                row["label"],
                str(row["total_magnets"]),
                f"{row['cost_jpy']:.0f}",
                f"{row['gap_mm']:.1f}",
                f"{row['mean_radius_mm']:.1f}",
                f"{row['stiffness_full']:.2f}",
                f"{row['stiffness_reduced']:.2f}",
                f"{row['worst_clearance_mm']:.2f}",
                str(row["contact"]),
                str(row["latched"]),
                f"{row['mean_dynamic_score']:.3f}",
            ]
        )
    if latex:
        lines = [
            r"\begin{longtable}{p{0.19\linewidth}rrrrrrrrrr}",
            r"\toprule",
            " & ".join(tex_escape(header) for header in headers) + r" \\",
            r"\midrule",
            r"\endfirsthead",
            r"\toprule",
            " & ".join(tex_escape(header) for header in headers) + r" \\",
            r"\midrule",
            r"\endhead",
        ]
        for row in rendered_rows:
            lines.append(" & ".join(tex_escape(value) for value in row) + r" \\")
        lines.extend([r"\bottomrule", r"\end{longtable}"])
        return "\n".join(lines)
    widths = [20, 8, 10, 8, 10, 12, 12, 10, 4, 4, 12]
    sep = "| " + " | ".join("-" * width for width in widths) + " |"
    header_line = "| " + " | ".join(header.ljust(width) for header, width in zip(headers, widths)) + " |"
    lines = [header_line, sep]
    for row in rendered_rows:
        lines.append("| " + " | ".join(value.ljust(width) for value, width in zip(row, widths)) + " |")
    return "\n".join(lines)


def format_design_variable_table(latex: bool) -> str:
    manifest = hifi.design_variable_manifest("flex")
    if latex:
        lines = [
            r"\begin{longtable}{r p{0.24\linewidth} p{0.20\linewidth} p{0.44\linewidth}}",
            r"\toprule",
            r"Index & Name & Range & Description \\",
            r"\midrule",
            r"\endfirsthead",
            r"\toprule",
            r"Index & Name & Range & Description \\",
            r"\midrule",
            r"\endhead",
        ]
        for row in manifest:
            lines.append(
                f"{row['index']} & {tex_escape(row['name'])} & {tex_escape(row['range'])} & {tex_escape(row['description'])} \\\\"
            )
        lines.extend([r"\bottomrule", r"\end{longtable}"])
        return "\n".join(lines)
    lines = [
        "| index | name | range | description |",
        "| ---: | --- | --- | --- |",
    ]
    for row in manifest:
        lines.append(f"| {row['index']} | {row['name']} | {row['range']} | {row['description']} |")
    return "\n".join(lines)


def format_program_table(latex: bool) -> str:
    rows = [
        {
            "file": "mpc_solarcar/magnetic_coupler_hifi.py",
            "role": "形状生成、有限磁石配列モデル、静的評価、動的検証、方策探索、図生成、結果出力を担う主解析コード。",
            "lines": "431-3442",
        },
        {
            "file": "mpc_solarcar/magnetic_coupler_interactive_sim.py",
            "role": "0.45 m/s 回廊搬送を想定したキーボード操作型リアルタイム可視化シミュレータ。",
            "lines": "1-末尾",
        },
        {
            "file": "mpc_solarcar/magnetic_coupler_cad.py",
            "role": "選定形状から磁石ポケット、蓋、組立 STEP / STL、図面 PDF を自動生成する CAD スクリプト。",
            "lines": "1-1131",
        },
        {
            "file": "scripts/generate_bachelor_thesis_magnetic_coupler.py",
            "role": "本卒論ドラフト用の図収集、要約生成、LaTeX 組版、DOCX 生成を一括自動化する補助スクリプト。",
            "lines": "本ファイル",
        },
    ]
    if latex:
        lines = [
            r"\begin{longtable}{p{0.28\linewidth} p{0.14\linewidth} p{0.50\linewidth}}",
            r"\toprule",
            r"File & Lines & Role \\",
            r"\midrule",
            r"\endfirsthead",
            r"\toprule",
            r"File & Lines & Role \\",
            r"\midrule",
            r"\endhead",
        ]
        for row in rows:
            lines.append(
                f"{tex_escape(row['file'])} & {tex_escape(row['lines'])} & {tex_escape(row['role'])} \\\\"
            )
        lines.extend([r"\bottomrule", r"\end{longtable}"])
        return "\n".join(lines)
    lines = [
        "| file | lines | role |",
        "| --- | --- | --- |",
    ]
    for row in rows:
        lines.append(f"| {row['file']} | {row['lines']} | {row['role']} |")
    return "\n".join(lines)


def chapter_opener_latex(chapter_title: str, items: list[tuple[str, str]]) -> str:
    lines = [
        rf"\chapter{{{tex_escape(chapter_title)}}}",
        r"\thispagestyle{empty}",
        r"\vspace{2ex}",
        r"{\Large Contents}\par",
        r"\vspace{2ex}",
    ]
    for label_text, label_key in items:
        lines.append(rf"\noindent {tex_escape(label_text)} \dotfill \pageref{{{label_key}}}\par")
    lines.extend([r"\clearpage"])
    return "\n".join(lines)


def reference_entries() -> list[str]:
    return [
        "[1] AgileX Robotics, “LIMO,” official website, https://global.agilex.ai/pages/limo, accessed 2026-06-30.",
        "[2] DAISO ネットストア, “超強力マグネット 4コ入 (JAN 4549131230475),” https://jp.daisonet.com/products/4549131230475, accessed 2026-06-30.",
        "[3] M. Furlani, Permanent Magnet and Electromechanical Devices, Academic Press, 2001.",
        "[4] R. Y. Rubinstein and D. P. Kroese, The Cross-Entropy Method: A Unified Approach to Combinatorial Optimization, Monte-Carlo Simulation and Machine Learning, Springer, 2004.",
        "[5] R. S. Sutton and A. G. Barto, Reinforcement Learning: An Introduction, 2nd ed., MIT Press, 2018.",
        "[6] CadQuery Contributors, “CadQuery Documentation,” https://cadquery.readthedocs.io/, accessed 2026-06-30.",
        "[7] NumPy Developers, “NumPy Documentation,” https://numpy.org/doc/, accessed 2026-06-30.",
        "[8] Matplotlib Development Team, “Matplotlib Documentation,” https://matplotlib.org/stable/, accessed 2026-06-30.",
        "[9] 本研究ワークスペース, `mpc_solarcar/magnetic_coupler_hifi.py`, 2026-06-30 時点.",
        "[10] 本研究ワークスペース, `mpc_solarcar/magnetic_coupler_cad.py`, 2026-06-30 時点.",
    ]


def strip_reference_prefix(entry: str) -> str:
    if "] " in entry:
        return entry.split("] ", 1)[1]
    return entry


def build_candidate_rows(bundles: list[ResultBundle]) -> list[dict]:
    rows = []
    for bundle in bundles:
        design = selected_design(bundle)
        sa = static_assessment(bundle)
        dv = dynamic_summary(bundle)
        rows.append(
            {
                "label": bundle.name,
                "total_magnets": design["total_magnets"],
                "cost_jpy": design["estimated_total_cost_jpy"],
                "gap_mm": mm(design["gap_m"]),
                "mean_radius_mm": mm(design["mean_radius_m"]),
                "stiffness_full": sa["mean_full_height_stiffness_npm"],
                "stiffness_reduced": sa["min_reduced_height_stiffness_npm"],
                "worst_clearance_mm": dv["worst_min_clearance_mm"],
                "contact": dv["contact_events_total"],
                "latched": dv["latched_total"],
                "mean_dynamic_score": dv["mean_score"],
            }
        )
    return rows


def paragraph_lines(text: str, latex: bool) -> list[str]:
    content = text.strip().replace("\n", " ")
    if latex:
        return [tex_escape(content), ""]
    return [content, ""]


def write_markdown(primary: ResultBundle, manufacturing: ResultBundle, figure_map: dict[str, str]):
    primary_design = selected_design(primary)
    primary_static = static_assessment(primary)
    primary_dynamic = dynamic_summary(primary)
    manufacturing_design = selected_design(manufacturing)
    manufacturing_static = static_assessment(manufacturing)
    manufacturing_dynamic = dynamic_summary(manufacturing)
    scenario_table = scenario_aggregate(primary)
    worst_row = scenario_table.iloc[0]
    best_row = scenario_table.sort_values("best_score", ascending=False).iloc[0]
    candidate_table = format_candidate_comparison_table(build_candidate_rows([primary, manufacturing]), latex=False)
    references = reference_entries()

    lines: list[str] = []
    lines.extend(
        [
            f"# {THESIS_TITLE}",
            "",
            f"{FISCAL_YEAR}  ",
            f"{DEPARTMENT_NAME}  ",
            f"学籍番号: {STUDENT_ID}  ",
            f"氏名: {AUTHOR_NAME}  ",
            f"指導教員: {ADVISOR_NAME}  ",
            f"作成日: {SUBMISSION_DATE}",
            "",
            "\\newpage",
            "",
            "## 要旨",
            "",
            (
                "本研究では，AgileX LIMO に接続された内側リングと，4 輪キャスター台車下面に搭載される外側リングから成る"
                "高さ可変磁気カプラを対象に，有限個の実商品ネオジム磁石配列で実現可能な形状と高さ制御則を同時に検討した。"
                "評価の主眼は，(1) 全方向の人入力に対して逆向きの純反力を返すこと，(2) 高さを下げて可動量を増やしても復元力が正のまま維持されること，"
                "(3) 横ずれ吸着やラッチを発生させないこと，(4) 0.45 m/s 定常走行の回廊搬送でもロボット追従が破綻しないことである。"
            ),
            "",
            (
                "解析モデルは，内外リング形状の法線オフセット幾何，有限磁石配列の体積双極子重ね合わせ磁場，"
                "接触投影付きサブステップ動力学，および空隙マージンに応じて重なり高さを減少させる 8 パラメータ方策から構成した。"
                "DAISO 公式通販で購入可能な 13 mm ネオジム磁石 4 個入を対象 SKU とし，磁石総数・層数・空隙・平均半径・形状高調波・重なり高さ・台車質量などを"
                " 23 設計変数として探索した。"
            ),
            "",
            (
                f"現在の完成済みランのうち最も動的安定性が高かった候補は `limo_stable5` であり，空隙 {mm(primary_design['gap_m']):.1f} mm，"
                f"平均半径 {mm(primary_design['mean_radius_m']):.1f} mm，磁石 {primary_design['magnets_per_ring']} 個 / ring × "
                f"{primary_design['magnet_layers']} 層，総数 {primary_design['total_magnets']} 個，推定磁石費用 "
                f"{primary_design['estimated_total_cost_jpy']:.0f} JPY であった。"
                f"動的検証 18 エピソードでは接触 0，ラッチ 0，最悪物理クリアランス {primary_dynamic['worst_min_clearance_mm']:.2f} mm を維持した。"
                f"一方で，より高い静剛性を示す `verticalstack78` は静的には優位であるものの，動的スコアでは主候補を上回らなかった。"
            ),
            "",
            f"**Key words:** {', '.join(KEYWORDS)}",
            "",
            "\\newpage",
            "",
            "# 第1章 序論",
            "",
            "## 1.1 研究背景",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "人とロボットが協調して台車を搬送する場面では，人が望む進行方向や旋回意図を，台車を介してロボットへ途切れなく伝える必要がある。"
            "しかし剛結合では，姿勢ずれや微小な段差がそのまま衝撃となって入力側へ返り，柔結合すぎる構造では逆に操作者の意図が失われる。"
            "磁気カプラは非接触で力を伝えられるためこの中間解として魅力的であるが，有限個の磁石を円周上に並べた実機では，理想連続リングでは現れない"
            "ピッチ起因のコギング，横ずれ吸着，回転時の局所くっつきが生じやすい。",
            latex=False,
        )
    )
    lines.extend(
        paragraph_lines(
            "特に，本研究が対象とする『人が台車へ回転希望入力を与えるときは高さを下げて可変量を大きくし，直進時は十分な復元力で強く追従させる』という運用では，"
            "単に同心円状態で安定な形状では不十分である。高さを下げた瞬間にも復元力の符号が反転せず，外力方向と直交する寄生力や寄生モーメントを増やさず，"
            "しかも内外リングが接触しないことが要求される。したがって，磁場分布，有限個配列，キャスター台車の慣性，LIMO の走行速度，"
            "接触拘束，制御則をまとめて再現する高忠実度シミュレータが必要になる。",
            latex=False,
        )
    )
    lines.extend(
        [
            "## 1.2 関連研究",
            "",
            "### 1.2.1 磁気結合機構と永久磁石の解析",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "永久磁石配列の設計では，単体磁石の表面磁束密度だけでなく，配列位相，空隙，周方向ピッチ，および姿勢ずれ時の場勾配が力学特性を大きく左右する。"
            "解析的には Coulombian / surface-charge 系モデルや均一磁化体近似が広く用いられる一方，実際の設計作業では，有限形状を数値的に分割した双極子近似の方が"
            "形状最適化へ接続しやすい。本研究でも後者を採用し，実商品 SKU の寸法と価格制約をそのまま探索へ組み込んだ。",
            latex=False,
        )
    )
    lines.extend(
        [
            "### 1.2.2 協調搬送と人入力の読み取り",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "人共存搬送では，『大きな直進復元力』と『旋回意図の素早い提示』がしばしばトレードオフになる。剛すぎる結合は操作者の入力自由度を奪い，"
            "柔らかすぎる結合は直進安定性を失う。この矛盾を解消するため，本研究では重なり高さを状態依存で下げる可変結合を導入し，"
            "外力トルクの存在下でだけ横方向可動量を増やす構造を目指した。",
            latex=False,
        )
    )
    lines.extend(
        [
            "### 1.2.3 最適化の位置づけ",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "探索空間は 23 次元であり，連続形状パラメータと離散的な磁石個数・層数が混在する。そのため微分可能性を前提とする方法よりも，"
            "実装が単純で頑健な Cross-Entropy Method 系のサンプリング最適化が適している。また，高さ制御則は動的シナリオ全体の報酬でのみ評価できるため，"
            "こちらも分布更新型の方策探索として扱った。",
            latex=False,
        )
    )
    lines.extend(
        [
            "## 1.3 研究目的",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "本研究の目的は，有限個の DAISO 13 mm ネオジム磁石配列だけで実現可能な高さ可変磁気カプラを設計し，"
            "人が任意方向から台車へ加える入力に対し，常に逆向きの純反力を返す幾何形状と制御則を示すことである。"
            "加えて，AgileX LIMO とキャスター台車を含む動的シミュレーション上で接触・ラッチ・吸着不足の有無を確認し，"
            "製造可能な CAD ケージングまで一貫して整備する。",
            latex=False,
        )
    )
    lines.extend(
        [
            "## 1.4 本論文の構成",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "第 2 章では，対象システム，磁石制約，形状パラメータ化，磁場・接触・高さ制御のモデル化を述べる。"
            "第 3 章では，静的評価指標，動的検証環境，最適化手順，CAD 生成，プログラム構成を説明する。"
            "第 4 章では，探索収束，最終候補形状，静的復元力特性，動的結果，製造候補との比較を示し，"
            "第 5 章で結論と今後の展望をまとめる。",
            latex=False,
        )
    )
    lines.extend(
        [
            "\\newpage",
            "",
            "# 第2章 設計対象とモデル化",
            "",
            "## 2.1 対象システムと要求仕様",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "対象システムは，ロボット側に固定された内側リングと，台車側に固定された外側リングから構成される。両者は同心・同一高さを基準状態とし，"
            "内側リングの外周には外向き同極，外側リングの内周には内向き同極の有限磁石列を配置する。人が台車へ力またはモーメントを加えると，"
            "相対変位に応じた反発力と復元モーメントが発生し，ロボットはその入力方向を読む。要求仕様は以下の四点である。"
            "第一に，直進搬送時には十分な復元剛性で台車が遅れずに追従すること。第二に，旋回希望入力時には高さを下げて可動量を増やし，"
            "入力意図を遅れなく示せること。第三に，どの方向からの入力でも横ずれ吸着やそのままのラッチが起きないこと。第四に，"
            "接触後のめり込みは物理的に不可能であるという拘束をシミュレータが守ることである。",
            latex=False,
        )
    )
    lines.extend(
        [
            "## 2.2 実商品磁石と実装制約",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "本研究で最終的に主対象とした磁石は DAISO 公式通販で販売される『超強力マグネット 4 コ入』である。"
            "公式情報では直径 1.3 cm，厚さ 0.24 cm，4 個入り，税込 110 円とされている。"
            "解析では，円盤磁石を周方向配列へ組み込むため，接線方向寸法と軸方向寸法をいずれも 13 mm，"
            "半径方向厚みを 2.4 mm としたポケットへ収める立て配置として扱い，必要に応じて軸方向へ縦積みする。"
            "これにより，安価で入手しやすい一方，有限ピッチによる磁束切れ目が避けられないという現実的制約をそのまま評価できる。",
            latex=False,
        )
    )
    lines.extend(
        [
            "## 2.3 幾何形状のパラメータ化",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            f"現在の高忠実度コードでは設計変数を {hifi.design_variable_count('flex')} 個持ち，"
            "アスペクト比，スーパー楕円指数，多角形混合率，多角形辺数，形状位相，高調波 3〜12 次，"
            "空隙，平均半径，SKU 選択，磁石層数，充填率，外側位相差，公称重なり高さ，高さ可変量，台車質量を同時に扱う。"
            "またコード上は矢印族パラメータも保持しており，将来はより強い非対称形状探索へ拡張できる。"
            "本論文で主に採用した `limo_stable5` は滑らかな 6 波形寄りの輪郭で，急峻な角や深い首部を持たず，"
            "全方向でほぼ均質な反力を出しつつ，微小なヨー復元を確保する方向へ収束した。",
            latex=False,
        )
    )
    lines.extend(
        [
            f"![最終選定候補の輪郭図]({figure_map['shape_preview']})",
            "",
            "## 2.4 磁場・力学モデル",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "各磁石は均一磁化体を近似する複数双極子へ離散化し，配列全体の磁束密度とポテンシャル勾配を重ね合わせることで，"
            "並進力・ヨートルク・最小ギャップを評価する。以前の実装では外側輪郭を単純な原点相似拡大で作っていたため，"
            "局所的に空隙が不均一になり，姿勢ずれ時の力向きが崩れる問題があった。現行版では内側境界から法線方向へ一定量オフセットして"
            "外側境界を生成し，形状が非円形でも空隙定義が一貫するよう修正した。",
            latex=False,
        )
    )
    lines.extend(
        paragraph_lines(
            f"主候補の有効磁束密度は {primary_design['effective_flux_t']:.3f} T と評価され，"
            "これは DAISO パッケージ記載の表面磁束密度 240 mT をそのまま磁化強度へ置き換えるのではなく，"
            "一様磁化円柱の表面場と整合する等価 remanence へ変換してから双極子モーメントを合成した結果である。"
            "そのため，解析値は単純な 240 mT ではなく，幾何・離散化・有効磁路を含む設計用スカラーとして用いている。",
            latex=False,
        )
    )
    lines.extend(
        [
            f"![最終候補の磁場分布]({figure_map['field_distribution']})",
            "",
            "## 2.5 接触とクリアランスのモデル",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "接触以降のめり込みは物理的に許されないという前提に基づき，動的シミュレーションではサブステップ積分後に接触投影を行い，"
            "法線方向の速度成分も補正する。これにより，計算上の penetration は監査用の『接触要求量』としてのみ記録され，"
            "物理クリアランスは常に 0 mm 以上へクランプされる。現行主候補の動的検証では，最大接触要求量は 0 mm，"
            f"最悪物理クリアランスは {primary_dynamic['worst_min_clearance_mm']:.2f} mm であり，接触投影が発火する前に十分な余裕を保てた。",
            latex=False,
        )
    )
    lines.extend(
        [
            "## 2.6 高さ可変制御モデル",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "高さ制御は，入力トルク意図，入力力意図，相対ヨー，相対ヨー角速度，空隙マージン，並進変位，相対速度を特徴量とする 8 パラメータの方策で表現した。"
            "トルク意図が大きく空隙余裕が十分にあるときは重なり高さを減らし，可動量を増やす。一方，空隙が小さい場合や大きな並進ずれが発生した場合は"
            "重なり高さを戻して復元剛性を確保する。`limo_stable5` では，高さ可変量の上限は "
            f"{mm(primary_design['max_overlap_reduction_m']):.2f} mm であり，動的検証中の実際の最大変位は "
            f"{scenario_table['peak_height_shift_mm'].max():.3f} mm に留まった。",
            latex=False,
        )
    )
    lines.extend(
        [
            "\\newpage",
            "",
            "# 第3章 最適化・検証環境",
            "",
            "## 3.1 静的評価指標",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "静的評価では，同心状態だけでなく，微小並進・微小回転・高さ低下を与えた多数サンプル上で復元力の健全性を測定した。"
            "主な指標は，フル高さ平均剛性，低高さ最小剛性，平均直交漏れ比，方向剛性変動係数，変位線形性 R²，高さ線形性 R²，"
            "純並進入力時の寄生トルク比，前進方向寄生トルク比，負の復元サンプル数，負のヨー復元サンプル数である。"
            "とくに直交漏れ比と寄生トルク比は，『重いが真っ直ぐ押し返さない形状』を排除するための重要な罰則項として働く。",
            latex=False,
        )
    )
    lines.extend(
        [
            "## 3.2 動的シミュレーション環境",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "動的検証では，AgileX LIMO を 0.45 m/s の定速目標で走行させ，その後方にキャスター台車が磁気的に追従する環境を用いた。"
            "シナリオは translation turn, mixed slalom, gentle arc, lateral retarget, aggressive turn, contact challenge の 6 種類で，"
            "各シナリオに対して nominal, perturbed_1, perturbed_2 の 3 環境変動を与え，合計 18 エピソードで評価した。"
            "ばらつき環境では減衰や組付け偏差，位相ずれを変え，設計が一点調整ではなく頑健に働くかを確認した。",
            latex=False,
        )
    )
    lines.extend(
        [
            "## 3.3 設計探索の設定",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "設計探索は CEM 系の分布更新型最適化として実装した。完成済みの `limo_stable5` ランでは 5 世代の設計更新で主候補が得られ，"
            "各世代で設計変数のサンプル群を静的評価した上で，上位群の統計量を次世代のサンプリング分布へ反映した。"
            "同時に，LIMO と台車のパッケージ外形を超える候補，低高さで負剛性を示す候補，接触サンプルが出る候補へは強い罰則を課した。"
            "これにより，単に大きな磁力を出すだけの解ではなく，動的に扱いやすい解が残るようにした。",
            latex=False,
        )
    )
    lines.extend(
        [
            f"![設計探索の収束]({figure_map['design_convergence']})",
            "",
            "## 3.4 高さ制御方策の探索",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "形状が選定された後，高さ制御方策を別段階で最適化した。設計探索が『構造そのものの良し悪し』を決めるのに対し，方策探索は"
            "『その構造をどう使うか』を決める。`limo_stable5` では 5 世代の方策探索により，平均スコアが世代ごとに改善し，"
            "最終世代では best score -240.361，mean score -240.370 へ収束した。",
            latex=False,
        )
    )
    lines.extend(
        [
            f"![高さ制御方策の収束]({figure_map['policy_convergence']})",
            "",
            "## 3.5 CAD ケージングと製造制約",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "選定候補に対しては `magnetic_coupler_cad.py` を用いて，磁石ポケット付きの内側・外側キャリア，蓋，組立 STEP / STL，"
            "および図面 PDF を自動生成した。生成された STEP は Fusion 360 でメッシュではなく BRep solid として扱える構成であり，"
            "ポケットの公差，底面厚み，フランジ厚み，ねじ穴配置もスクリプトから再現できる。"
            "本ドラフトでは，動的主候補である `limo_stable5` についても新たに CAD 一式を再生成し，論文本体と図面の整合を取った。",
            latex=False,
        )
    )
    lines.extend(
        [
            f"![最終候補の CAD アイソメ図]({figure_map['cad_iso']})",
            "",
            "## 3.6 プログラム構成",
            "",
            format_program_table(latex=False),
            "",
        ]
    )
    lines.extend(
        [
            "\\newpage",
            "",
            "# 第4章 結果および考察",
            "",
            "## 4.1 探索収束の概要",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "探索履歴を見ると，初期世代では大きな剛性を持つ一方で package violation や towed yaw 不安定を抱える候補が多かった。"
            "世代更新を進めるにつれ，磁石個数を闇雲に増やす方向ではなく，平均半径と輪郭の波形を整え，"
            "より少ない磁石数で安定した反力方向を得る方向へ分布が移動した。これは『磁力最大化』ではなく『扱いやすさ最大化』が目的関数に反映された結果である。",
            latex=False,
        )
    )
    lines.extend(
        [
            "## 4.2 最終候補の幾何形状と磁石配列",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            f"最終候補 `limo_stable5` は，空隙 {mm(primary_design['gap_m']):.1f} mm，平均半径 {mm(primary_design['mean_radius_m']):.1f} mm，"
            f"公称重なり高さ {mm(primary_design['nominal_overlap_m']):.1f} mm，最大高さ低下 {mm(primary_design['max_overlap_reduction_m']):.2f} mm，"
            f"磁石 {primary_design['magnets_per_ring']} 個 / ring × {primary_design['magnet_layers']} 層，総数 {primary_design['total_magnets']} 個で構成される。"
            "輪郭は完全な円ではなく，角の丸い正方形に緩やかな 6 次波形を重ねた形であり，前後左右の剛性を保ちながら局所的な接線方向成分を抑制している。",
            latex=False,
        )
    )
    lines.extend(
        [
            f"![最終候補の磁石配置 CAD 図面]({figure_map['cad_sheet1']})",
            "",
            "## 4.3 静的復元力特性",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            f"主候補のフル高さ平均剛性は {primary_static['mean_full_height_stiffness_npm']:.2f} N/m，低高さ最小剛性は "
            f"{primary_static['min_reduced_height_stiffness_npm']:.2f} N/m であり，高さを下げても剛性が正のまま保たれた。"
            f"平均直交漏れ比は {primary_static['mean_orthogonal_ratio']:.4f}，方向剛性 CV は {primary_static['direction_stiffness_cv']:.4f}，"
            f"変位線形性 R² は {primary_static['displacement_linearity_r2']:.4f} であった。"
            "これらは，外力方向に対しほぼ同一直線上で反力を返し，かつ力の立ち上がりが素直であることを意味する。",
            latex=False,
        )
    )
    lines.extend(
        paragraph_lines(
            f"一方で，負のヨー復元サンプルは {primary_static['negative_yaw_restore_count']} 件残っており，"
            f"最小ヨー復元モーメントは {primary_static['min_yaw_restoring_nm']:.4f} N m であった。"
            "値そのものは小さいが完全な単調復元には達していないことを示している。したがって，本設計は『実用上かなり安定』ではあるものの，"
            "『全姿勢・全高さで数学的に完全単調』とまでは言えない。この残差は今後さらに探索回数を増やして詰めるべき論点である。",
            latex=False,
        )
    )
    lines.extend(
        [
            f"![方向別復元力の極座標表示]({figure_map['force_polar']})",
            "",
            f"![変位と高さに対する復元力曲線]({figure_map['force_curves']})",
            "",
            "## 4.4 動的検証結果",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            f"動的検証 18 エピソードでは，接触回数 0，制約発火 0，ラッチ 0 であり，"
            f"最悪クリアランスは {primary_dynamic['worst_min_clearance_mm']:.2f} mm，平均スコアは {primary_dynamic['mean_score']:.3f}，"
            f"最悪スコアは {primary_dynamic['worst_score']:.3f} であった。"
            f"最悪シナリオは {worst_row['scenario_name']}，最良シナリオは {best_row['scenario_name']} であり，"
            f"最悪シナリオでも平均並進 RMS は {worst_row['mean_translation_rms_mm']:.3f} mm，平均ヨー RMS は {worst_row['mean_yaw_rms_deg']:.3f} deg に留まった。",
            latex=False,
        )
    )
    lines.extend(
        [
            "| シナリオ | worst score | mean clearance [mm] | mean translation RMS [mm] | mean yaw RMS [deg] | peak height shift [mm] |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for _, row in scenario_table.iterrows():
        lines.append(
            f"| {row['scenario_name']} | {row['worst_score']:.3f} | {row['mean_clearance_mm']:.3f} | "
            f"{row['mean_translation_rms_mm']:.3f} | {row['mean_yaw_rms_deg']:.3f} | {row['peak_height_shift_mm']:.3f} |"
        )
    lines.extend(
        [
            "",
            f"![代表的な良好シナリオの時系列]({figure_map['best_rollout']})",
            "",
            f"![最悪シナリオの時系列]({figure_map['worst_rollout']})",
            "",
            "## 4.5 製造比較候補との比較",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            f"製造比較候補 `verticalstack78` は，総磁石数 {manufacturing_design['total_magnets']} 個，推定磁石費用 "
            f"{manufacturing_design['estimated_total_cost_jpy']:.0f} JPY，フル高さ平均剛性 {manufacturing_static['mean_full_height_stiffness_npm']:.2f} N/m，"
            f"低高さ最小剛性 {manufacturing_static['min_reduced_height_stiffness_npm']:.2f} N/m と，静的には主候補より強い。"
            f"しかし動的平均スコアは {manufacturing_dynamic['mean_score']:.3f}，最悪クリアランスは {manufacturing_dynamic['worst_min_clearance_mm']:.2f} mm であり，"
            "0.45 m/s 回廊搬送での扱いやすさは `limo_stable5` が上回った。"
            "すなわち，『磁力の強さ』だけではなく，質量・入力トルク・高さ変化のもとでどれだけ素直に力を返すかが，最終設計の選定に大きく効いている。",
            latex=False,
        )
    )
    lines.extend(
        [
            candidate_table,
            "",
            f"![探索途中候補と以前の基準形状の比較]({figure_map['shape_progress_compare']})",
            "",
            "## 4.6 反力方向・危険領域の可視化",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "力ベクトルマップ，最小ギャップマップ，bad attraction マップを併用して確認すると，主候補は中心近傍から中程度の横変位まで，"
            "反力方向の乱れが小さく，危険領域も狭い。完全な円環に近い形は方向一様性が高い一方で回転復元が弱くなりやすく，"
            "極端な矢印形状は回転復元を強める代わりに前後方向の寄生成分を増やしやすい。主候補はこの中間に位置し，"
            "穏やかな非円形化によって回復モーメントと純反力性の両立を狙った解釈が妥当である。",
            latex=False,
        )
    )
    lines.extend(
        [
            f"![力ベクトルマップ yaw=0]({figure_map['force_vector_yaw0']})",
            "",
            f"![最小ギャップマップ yaw=0]({figure_map['minimum_gap_yaw0']})",
            "",
            f"![吸着危険領域マップ yaw=0]({figure_map['bad_attraction_yaw0']})",
            "",
            "## 4.7 限界と今後の課題",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "第一の限界は，磁石材料の完全な B-H 曲線や温度依存性をまだ扱っていない点である。現在は実商品寸法・価格・表面磁束表示を用いた設計用近似であり，"
            "材料固有の飽和やヨーク材の影響は簡略化されている。第二に，キャスターの旋回抵抗や床材摩擦は lumped parameter として表現しており，"
            "全ての実床条件を再現したわけではない。第三に，設計探索は完成済みランを基にまとめており，長時間アーカイブ探索の全収束結果はまだ反映しきれていない。"
            "したがって，本論文ドラフトは『現時点で最も整合的な完成版』である一方，実機検証と更なる長期探索によって改善余地が残る。",
            latex=False,
        )
    )
    lines.extend(
        [
            "\\newpage",
            "",
            "# 第5章 結論",
            "",
            "## 5.1 結論",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "本研究では，DAISO 13 mm ネオジム磁石の有限個配列と，AgileX LIMO・キャスター台車を含む高忠実度シミュレーションを用いて，"
            "高さ可変磁気カプラの設計最適化を行った。法線オフセット外形，表面磁束からの等価磁化較正，接触投影付きサブステップ動力学，"
            "CEM 系設計探索，方策探索，そして CAD 自動生成を一つのワークフローへ統合した点が主な貢献である。"
            "現時点での主候補 `limo_stable5` は，接触 0，ラッチ 0，最悪クリアランス 31.95 mm を維持しつつ，"
            "全方向で概ね素直な復元力を返す設計として得られた。",
            latex=False,
        )
    )
    lines.extend(
        [
            "## 5.2 今後の展望",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "今後は，実機リングを 3D プリントで製作し，LIMO と実台車を用いた回廊試験で本シミュレーションの妥当性を検証する必要がある。"
            "また，長期アーカイブ探索，実測磁場分布のフィッティング，床面種別や積載量の多様化，ならびに使用者の左右手入力を模擬した"
            "インタラクティブシミュレータとの統合評価を進めることで，より完成度の高い卒業論文本文へ発展させられる。",
            latex=False,
        )
    )
    lines.extend(
        [
            "\\newpage",
            "",
            "# 謝辞",
            "",
        ]
    )
    lines.extend(
        paragraph_lines(
            "本ドラフトでは個人情報欄を未記入としている。提出版では，研究指導，議論，実験環境整備に関して謝意を記す予定である。",
            latex=False,
        )
    )
    lines.extend(
        [
            "\\newpage",
            "",
            "# 参考文献",
            "",
        ]
    )
    for entry in references:
        lines.append(f"- {entry}")
    lines.extend(
        [
            "",
            "\\newpage",
            "",
            "# 付録A 設計変数一覧",
            "",
            format_design_variable_table(latex=False),
            "",
            "\\newpage",
            "",
            "# 付録B 製造図面一覧",
            "",
            f"![組立図面]({figure_map['cad_sheet1']})",
            "",
            f"![内側キャリア図面]({figure_map['cad_sheet2']})",
            "",
            f"![外側キャリア図面]({figure_map['cad_sheet3']})",
            "",
            "# 付録C プログラム構成一覧",
            "",
            format_program_table(latex=False),
            "",
        ]
    )
    THESIS_MD.write_text("\n".join(lines), encoding="utf-8")


def write_latex(primary: ResultBundle, manufacturing: ResultBundle, figure_map: dict[str, str]):
    primary_design = selected_design(primary)
    primary_static = static_assessment(primary)
    primary_dynamic = dynamic_summary(primary)
    manufacturing_design = selected_design(manufacturing)
    manufacturing_static = static_assessment(manufacturing)
    manufacturing_dynamic = dynamic_summary(manufacturing)
    scenario_table = scenario_aggregate(primary)
    worst_row = scenario_table.iloc[0]
    best_row = scenario_table.sort_values("best_score", ascending=False).iloc[0]
    candidate_table = format_candidate_comparison_table(build_candidate_rows([primary, manufacturing]), latex=True)
    design_variable_table = format_design_variable_table(latex=True)
    program_table = format_program_table(latex=True)
    references = reference_entries()

    lines: list[str] = [
        r"\documentclass[a4paper,11pt,openany]{ltjsbook}",
        r"\usepackage[margin=20mm]{geometry}",
        r"\usepackage{graphicx}",
        r"\usepackage{booktabs}",
        r"\usepackage{longtable}",
        r"\usepackage{array}",
        r"\usepackage{tabularx}",
        r"\usepackage{hyperref}",
        r"\usepackage{float}",
        r"\usepackage{caption}",
        r"\usepackage{titlesec}",
        r"\usepackage{luatexja-fontspec}",
        r"\usepackage{xcolor}",
        r"\setmainjfont{Yu Mincho}",
        r"\setsansjfont{Yu Gothic}",
        r"\setmonofont{Consolas}",
        r"\hypersetup{unicode=true,colorlinks=true,linkcolor=black,urlcolor=blue,citecolor=black}",
        r"\setcounter{tocdepth}{2}",
        r"\renewcommand{\contentsname}{目次}",
        r"\renewcommand{\figurename}{Fig.}",
        r"\renewcommand{\tablename}{Table.}",
        r"\renewcommand{\thefigure}{\thechapter-\arabic{figure}}",
        r"\renewcommand{\thetable}{\thechapter-\arabic{table}}",
        r"\captionsetup{font=small,labelfont=bf}",
        r"\titleformat{\chapter}[display]{\normalfont\bfseries\filcenter}{\Huge 第\ \thechapter\ 章}{1.5ex}{\Huge}",
        r"\titleformat{\section}{\Large\bfseries}{\thesection}{0.7em}{}",
        r"\titleformat{\subsection}{\large\bfseries}{\thesubsection}{0.7em}{}",
        r"\setlength{\parindent}{1em}",
        r"\setlength{\parskip}{0.3em}",
        r"\begin{document}",
        r"\frontmatter",
        r"\begin{titlepage}",
        r"\begin{center}",
        rf"{{\LARGE {tex_escape(FISCAL_YEAR)}}}\\[20mm]",
        rf"{{\Huge \bfseries {tex_escape(THESIS_TITLE)}}}\\[24mm]",
        rf"{{\Large {tex_escape(SUBMISSION_DATE)}}}\\[20mm]",
        rf"{{\Large {tex_escape(STUDENT_ID)}}}\\[8mm]",
        rf"{{\Large {tex_escape(AUTHOR_NAME)}}}\\[12mm]",
        rf"{{\Large 指導教員: {tex_escape(ADVISOR_NAME)}}}\\[8mm]",
        rf"{{\Large {tex_escape(DEPARTMENT_NAME)}}}",
        r"\end{center}",
        r"\end{titlepage}",
        r"\clearpage",
        r"\thispagestyle{empty}",
        r"\begin{center}",
        rf"{{\LARGE {tex_escape(TITLE_SHORT)}}}\\[6mm]",
        rf"{{\large {tex_escape(STUDENT_ID)}\ \ {tex_escape(AUTHOR_NAME)}\ （指導教員: {tex_escape(ADVISOR_NAME)}）}}\\[8mm]",
        rf"{{\large Key words : {tex_escape(', '.join(KEYWORDS))}}}",
        r"\end{center}",
        r"\vspace{6mm}",
    ]
    for paragraph in [
        "本研究では，AgileX LIMO に接続された内側リングと，4 輪キャスター台車下面に搭載される外側リングから成る高さ可変磁気カプラを対象に，有限個の実商品ネオジム磁石配列で実現可能な形状と高さ制御則を同時に検討した。評価の主眼は，(1) 全方向の人入力に対して逆向きの純反力を返すこと，(2) 高さを下げて可動量を増やしても復元力が正のまま維持されること，(3) 横ずれ吸着やラッチを発生させないこと，(4) 0.45 m/s 定常走行の回廊搬送でもロボット追従が破綻しないことである。",
        "解析モデルは，内外リング形状の法線オフセット幾何，有限磁石配列の体積双極子重ね合わせ磁場，接触投影付きサブステップ動力学，および空隙マージンに応じて重なり高さを減少させる 8 パラメータ方策から構成した。DAISO 公式通販で購入可能な 13 mm ネオジム磁石 4 個入を対象 SKU とし，磁石総数・層数・空隙・平均半径・形状高調波・重なり高さ・台車質量などを 23 設計変数として探索した。",
        f"現在の完成済みランのうち最も動的安定性が高かった候補は `limo_stable5` であり，空隙 {mm(primary_design['gap_m']):.1f} mm，平均半径 {mm(primary_design['mean_radius_m']):.1f} mm，磁石 {primary_design['magnets_per_ring']} 個 / ring × {primary_design['magnet_layers']} 層，総数 {primary_design['total_magnets']} 個，推定磁石費用 {primary_design['estimated_total_cost_jpy']:.0f} JPY であった。動的検証 18 エピソードでは接触 0，ラッチ 0，最悪物理クリアランス {primary_dynamic['worst_min_clearance_mm']:.2f} mm を維持した。一方で，より高い静剛性を示す `verticalstack78` は静的には優位であるものの，動的スコアでは主候補を上回らなかった。",
    ]:
        lines.extend([tex_escape(paragraph), "", r"\noindent"])
    lines.extend([r"\clearpage", r"\tableofcontents", r"\clearpage", r"\mainmatter"])

    lines.append(
        chapter_opener_latex(
            "序論",
            [
                ("1.1 研究背景", "sec:intro-background"),
                ("1.2 関連研究", "sec:intro-related"),
                ("1.3 研究目的", "sec:intro-objective"),
                ("1.4 本論文の構成", "sec:intro-structure"),
            ],
        )
    )
    lines.extend(
        [
            r"\section{研究背景}\label{sec:intro-background}",
            tex_escape(
                "人とロボットが協調して台車を搬送する場面では，人が望む進行方向や旋回意図を，台車を介してロボットへ途切れなく伝える必要がある。しかし剛結合では，姿勢ずれや微小な段差がそのまま衝撃となって入力側へ返り，柔結合すぎる構造では逆に操作者の意図が失われる。磁気カプラは非接触で力を伝えられるためこの中間解として魅力的であるが，有限個の磁石を円周上に並べた実機では，理想連続リングでは現れないピッチ起因のコギング，横ずれ吸着，回転時の局所くっつきが生じやすい。"
            ),
            "",
            tex_escape(
                "特に，本研究が対象とする『人が台車へ回転希望入力を与えるときは高さを下げて可変量を大きくし，直進時は十分な復元力で強く追従させる』という運用では，単に同心円状態で安定な形状では不十分である。高さを下げた瞬間にも復元力の符号が反転せず，外力方向と直交する寄生力や寄生モーメントを増やさず，しかも内外リングが接触しないことが要求される。したがって，磁場分布，有限個配列，キャスター台車の慣性，LIMO の走行速度，接触拘束，制御則をまとめて再現する高忠実度シミュレータが必要になる。"
            ),
            "",
            r"\section{関連研究}\label{sec:intro-related}",
            r"\subsection{磁気結合機構と永久磁石の解析}",
            tex_escape(
                "永久磁石配列の設計では，単体磁石の表面磁束密度だけでなく，配列位相，空隙，周方向ピッチ，および姿勢ずれ時の場勾配が力学特性を大きく左右する。解析的には Coulombian / surface-charge 系モデルや均一磁化体近似が広く用いられる一方，実際の設計作業では，有限形状を数値的に分割した双極子近似の方が形状最適化へ接続しやすい。本研究でも後者を採用し，実商品 SKU の寸法と価格制約をそのまま探索へ組み込んだ。"
            ),
            "",
            r"\subsection{協調搬送と人入力の読み取り}",
            tex_escape(
                "人共存搬送では，『大きな直進復元力』と『旋回意図の素早い提示』がしばしばトレードオフになる。剛すぎる結合は操作者の入力自由度を奪い，柔らかすぎる結合は直進安定性を失う。この矛盾を解消するため，本研究では重なり高さを状態依存で下げる可変結合を導入し，外力トルクの存在下でだけ横方向可動量を増やす構造を目指した。"
            ),
            "",
            r"\subsection{最適化の位置づけ}",
            tex_escape(
                "探索空間は 23 次元であり，連続形状パラメータと離散的な磁石個数・層数が混在する。そのため微分可能性を前提とする方法よりも，実装が単純で頑健な Cross-Entropy Method 系のサンプリング最適化が適している。また，高さ制御則は動的シナリオ全体の報酬でのみ評価できるため，こちらも分布更新型の方策探索として扱った。"
            ),
            "",
            r"\section{研究目的}\label{sec:intro-objective}",
            tex_escape(
                "本研究の目的は，有限個の DAISO 13 mm ネオジム磁石配列だけで実現可能な高さ可変磁気カプラを設計し，人が任意方向から台車へ加える入力に対し，常に逆向きの純反力を返す幾何形状と制御則を示すことである。加えて，AgileX LIMO とキャスター台車を含む動的シミュレーション上で接触・ラッチ・吸着不足の有無を確認し，製造可能な CAD ケージングまで一貫して整備する。"
            ),
            "",
            r"\section{本論文の構成}\label{sec:intro-structure}",
            tex_escape(
                "第 2 章では，対象システム，磁石制約，形状パラメータ化，磁場・接触・高さ制御のモデル化を述べる。第 3 章では，静的評価指標，動的検証環境，最適化手順，CAD 生成，プログラム構成を説明する。第 4 章では，探索収束，最終候補形状，静的復元力特性，動的結果，製造候補との比較を示し，第 5 章で結論と今後の展望をまとめる。"
            ),
            "",
        ]
    )

    lines.append(
        chapter_opener_latex(
            "設計対象とモデル化",
            [
                ("2.1 対象システムと要求仕様", "sec:model-target"),
                ("2.2 実商品磁石と実装制約", "sec:model-magnet"),
                ("2.3 幾何形状のパラメータ化", "sec:model-geometry"),
                ("2.4 磁場・力学モデル", "sec:model-field"),
                ("2.5 接触とクリアランスのモデル", "sec:model-contact"),
                ("2.6 高さ可変制御モデル", "sec:model-height"),
            ],
        )
    )
    lines.extend(
        [
            r"\section{対象システムと要求仕様}\label{sec:model-target}",
            tex_escape(
                "対象システムは，ロボット側に固定された内側リングと，台車側に固定された外側リングから構成される。両者は同心・同一高さを基準状態とし，内側リングの外周には外向き同極，外側リングの内周には内向き同極の有限磁石列を配置する。人が台車へ力またはモーメントを加えると，相対変位に応じた反発力と復元モーメントが発生し，ロボットはその入力方向を読む。要求仕様は以下の四点である。第一に，直進搬送時には十分な復元剛性で台車が遅れずに追従すること。第二に，旋回希望入力時には高さを下げて可動量を増やし，入力意図を遅れなく示せること。第三に，どの方向からの入力でも横ずれ吸着やそのままのラッチが起きないこと。第四に，接触後のめり込みは物理的に不可能であるという拘束をシミュレータが守ることである。"
            ),
            "",
            r"\section{実商品磁石と実装制約}\label{sec:model-magnet}",
            tex_escape(
                "本研究で最終的に主対象とした磁石は DAISO 公式通販で販売される『超強力マグネット 4 コ入』である。公式情報では直径 1.3 cm，厚さ 0.24 cm，4 個入り，税込 110 円とされている。解析では，円盤磁石を周方向配列へ組み込むため，接線方向寸法と軸方向寸法をいずれも 13 mm，半径方向厚みを 2.4 mm としたポケットへ収める立て配置として扱い，必要に応じて軸方向へ縦積みする。これにより，安価で入手しやすい一方，有限ピッチによる磁束切れ目が避けられないという現実的制約をそのまま評価できる。"
            ),
            "",
            r"\section{幾何形状のパラメータ化}\label{sec:model-geometry}",
            tex_escape(
                f"現在の高忠実度コードでは設計変数を {hifi.design_variable_count('flex')} 個持ち，アスペクト比，スーパー楕円指数，多角形混合率，多角形辺数，形状位相，高調波 3〜12 次，空隙，平均半径，SKU 選択，磁石層数，充填率，外側位相差，公称重なり高さ，高さ可変量，台車質量を同時に扱う。またコード上は矢印族パラメータも保持しており，将来はより強い非対称形状探索へ拡張できる。本論文で主に採用した `limo_stable5` は滑らかな 6 波形寄りの輪郭で，急峻な角や深い首部を持たず，全方向でほぼ均質な反力を出しつつ，微小なヨー復元を確保する方向へ収束した。"
            ),
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.72\linewidth]{{{figure_map['shape_preview']}}}",
            r"\caption{最終選定候補の輪郭図。}",
            r"\end{figure}",
            r"\section{磁場・力学モデル}\label{sec:model-field}",
            tex_escape(
                f"各磁石は均一磁化体を近似する複数双極子へ離散化し，配列全体の磁束密度とポテンシャル勾配を重ね合わせることで，並進力・ヨートルク・最小ギャップを評価する。以前の実装では外側輪郭を単純な原点相似拡大で作っていたため，局所的に空隙が不均一になり，姿勢ずれ時の力向きが崩れる問題があった。現行版では内側境界から法線方向へ一定量オフセットして外側境界を生成し，形状が非円形でも空隙定義が一貫するよう修正した。主候補の有効磁束密度は {primary_design['effective_flux_t']:.3f} T と評価され，これは DAISO パッケージ記載の表面磁束密度 240 mT をそのまま磁化強度へ置き換えるのではなく，一様磁化円柱の表面場と整合する等価 remanence へ変換してから双極子モーメントを合成した結果である。"
            ),
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.95\linewidth]{{{figure_map['field_distribution']}}}",
            r"\caption{最終候補の磁場分布。}",
            r"\end{figure}",
            r"\section{接触とクリアランスのモデル}\label{sec:model-contact}",
            tex_escape(
                f"接触以降のめり込みは物理的に許されないという前提に基づき，動的シミュレーションではサブステップ積分後に接触投影を行い，法線方向の速度成分も補正する。これにより，計算上の penetration は監査用の『接触要求量』としてのみ記録され，物理クリアランスは常に 0 mm 以上へクランプされる。現行主候補の動的検証では，最大接触要求量は 0 mm，最悪物理クリアランスは {primary_dynamic['worst_min_clearance_mm']:.2f} mm であり，接触投影が発火する前に十分な余裕を保てた。"
            ),
            "",
            r"\section{高さ可変制御モデル}\label{sec:model-height}",
            tex_escape(
                f"高さ制御は，入力トルク意図，入力力意図，相対ヨー，相対ヨー角速度，空隙マージン，並進変位，相対速度を特徴量とする 8 パラメータの方策で表現した。トルク意図が大きく空隙余裕が十分にあるときは重なり高さを減らし，可動量を増やす。一方，空隙が小さい場合や大きな並進ずれが発生した場合は重なり高さを戻して復元剛性を確保する。`limo_stable5` では，高さ可変量の上限は {mm(primary_design['max_overlap_reduction_m']):.2f} mm であり，動的検証中の実際の最大変位は {scenario_table['peak_height_shift_mm'].max():.3f} mm に留まった。"
            ),
            "",
        ]
    )

    lines.append(
        chapter_opener_latex(
            "最適化・検証環境",
            [
                ("3.1 静的評価指標", "sec:env-static"),
                ("3.2 動的シミュレーション環境", "sec:env-dynamic"),
                ("3.3 設計探索の設定", "sec:env-designopt"),
                ("3.4 高さ制御方策の探索", "sec:env-policy"),
                ("3.5 CAD ケージングと製造制約", "sec:env-cad"),
                ("3.6 プログラム構成", "sec:env-program"),
            ],
        )
    )
    lines.extend(
        [
            r"\section{静的評価指標}\label{sec:env-static}",
            tex_escape(
                "静的評価では，同心状態だけでなく，微小並進・微小回転・高さ低下を与えた多数サンプル上で復元力の健全性を測定した。主な指標は，フル高さ平均剛性，低高さ最小剛性，平均直交漏れ比，方向剛性変動係数，変位線形性 R²，高さ線形性 R²，純並進入力時の寄生トルク比，前進方向寄生トルク比，負の復元サンプル数，負のヨー復元サンプル数である。とくに直交漏れ比と寄生トルク比は，『重いが真っ直ぐ押し返さない形状』を排除するための重要な罰則項として働く。"
            ),
            "",
            r"\section{動的シミュレーション環境}\label{sec:env-dynamic}",
            tex_escape(
                "動的検証では，AgileX LIMO を 0.45 m/s の定速目標で走行させ，その後方にキャスター台車が磁気的に追従する環境を用いた。シナリオは translation turn, mixed slalom, gentle arc, lateral retarget, aggressive turn, contact challenge の 6 種類で，各シナリオに対して nominal, perturbed_1, perturbed_2 の 3 環境変動を与え，合計 18 エピソードで評価した。ばらつき環境では減衰や組付け偏差，位相ずれを変え，設計が一点調整ではなく頑健に働くかを確認した。"
            ),
            "",
            r"\section{設計探索の設定}\label{sec:env-designopt}",
            tex_escape(
                "設計探索は CEM 系の分布更新型最適化として実装した。完成済みの `limo_stable5` ランでは 5 世代の設計更新で主候補が得られ，各世代で設計変数のサンプル群を静的評価した上で，上位群の統計量を次世代のサンプリング分布へ反映した。同時に，LIMO と台車のパッケージ外形を超える候補，低高さで負剛性を示す候補，接触サンプルが出る候補へは強い罰則を課した。これにより，単に大きな磁力を出すだけの解ではなく，動的に扱いやすい解が残るようにした。"
            ),
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.90\linewidth]{{{figure_map['design_convergence']}}}",
            r"\caption{設計探索の収束。}",
            r"\end{figure}",
            r"\section{高さ制御方策の探索}\label{sec:env-policy}",
            tex_escape(
                "形状が選定された後，高さ制御方策を別段階で最適化した。設計探索が『構造そのものの良し悪し』を決めるのに対し，方策探索は『その構造をどう使うか』を決める。`limo_stable5` では 5 世代の方策探索により，平均スコアが世代ごとに改善し，最終世代では best score -240.361，mean score -240.370 へ収束した。"
            ),
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.84\linewidth]{{{figure_map['policy_convergence']}}}",
            r"\caption{高さ制御方策の収束。}",
            r"\end{figure}",
            r"\section{CAD ケージングと製造制約}\label{sec:env-cad}",
            tex_escape(
                "選定候補に対しては `magnetic_coupler_cad.py` を用いて，磁石ポケット付きの内側・外側キャリア，蓋，組立 STEP / STL，および図面 PDF を自動生成した。生成された STEP は Fusion 360 でメッシュではなく BRep solid として扱える構成であり，ポケットの公差，底面厚み，フランジ厚み，ねじ穴配置もスクリプトから再現できる。本ドラフトでは，動的主候補である `limo_stable5` についても新たに CAD 一式を再生成し，論文本体と図面の整合を取った。"
            ),
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.83\linewidth]{{{figure_map['cad_iso']}}}",
            r"\caption{最終候補の CAD アイソメ図。}",
            r"\end{figure}",
            r"\section{プログラム構成}\label{sec:env-program}",
            program_table,
            "",
        ]
    )

    lines.append(
        chapter_opener_latex(
            "結果および考察",
            [
                ("4.1 探索収束の概要", "sec:result-overview"),
                ("4.2 最終候補の幾何形状と磁石配列", "sec:result-geometry"),
                ("4.3 静的復元力特性", "sec:result-static"),
                ("4.4 動的検証結果", "sec:result-dynamic"),
                ("4.5 製造比較候補との比較", "sec:result-compare"),
                ("4.6 反力方向・危険領域の可視化", "sec:result-maps"),
                ("4.7 限界と今後の課題", "sec:result-limit"),
            ],
        )
    )
    lines.extend(
        [
            r"\section{探索収束の概要}\label{sec:result-overview}",
            tex_escape(
                "探索履歴を見ると，初期世代では大きな剛性を持つ一方で package violation や towed yaw 不安定を抱える候補が多かった。世代更新を進めるにつれ，磁石個数を闇雲に増やす方向ではなく，平均半径と輪郭の波形を整え，より少ない磁石数で安定した反力方向を得る方向へ分布が移動した。これは『磁力最大化』ではなく『扱いやすさ最大化』が目的関数に反映された結果である。"
            ),
            "",
            r"\section{最終候補の幾何形状と磁石配列}\label{sec:result-geometry}",
            tex_escape(
                f"最終候補 `limo_stable5` は，空隙 {mm(primary_design['gap_m']):.1f} mm，平均半径 {mm(primary_design['mean_radius_m']):.1f} mm，公称重なり高さ {mm(primary_design['nominal_overlap_m']):.1f} mm，最大高さ低下 {mm(primary_design['max_overlap_reduction_m']):.2f} mm，磁石 {primary_design['magnets_per_ring']} 個 / ring × {primary_design['magnet_layers']} 層，総数 {primary_design['total_magnets']} 個で構成される。輪郭は完全な円ではなく，角の丸い正方形に緩やかな 6 次波形を重ねた形であり，前後左右の剛性を保ちながら局所的な接線方向成分を抑制している。"
            ),
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.96\linewidth]{{{figure_map['cad_sheet1']}}}",
            r"\caption{最終候補の磁石配置 CAD 図面。}",
            r"\end{figure}",
            r"\section{静的復元力特性}\label{sec:result-static}",
            tex_escape(
                f"主候補のフル高さ平均剛性は {primary_static['mean_full_height_stiffness_npm']:.2f} N/m，低高さ最小剛性は {primary_static['min_reduced_height_stiffness_npm']:.2f} N/m であり，高さを下げても剛性が正のまま保たれた。平均直交漏れ比は {primary_static['mean_orthogonal_ratio']:.4f}，方向剛性 CV は {primary_static['direction_stiffness_cv']:.4f}，変位線形性 R² は {primary_static['displacement_linearity_r2']:.4f} であった。これらは，外力方向に対しほぼ同一直線上で反力を返し，かつ力の立ち上がりが素直であることを意味する。"
            ),
            "",
            tex_escape(
                f"一方で，負のヨー復元サンプルは {primary_static['negative_yaw_restore_count']} 件残っており，最小ヨー復元モーメントは {primary_static['min_yaw_restoring_nm']:.4f} N m であった。値そのものは小さいが完全な単調復元には達していないことを示している。したがって，本設計は『実用上かなり安定』ではあるものの，『全姿勢・全高さで数学的に完全単調』とまでは言えない。この残差は今後さらに探索回数を増やして詰めるべき論点である。"
            ),
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.95\linewidth]{{{figure_map['force_polar']}}}",
            r"\caption{方向別復元力の極座標表示。}",
            r"\end{figure}",
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.95\linewidth]{{{figure_map['force_curves']}}}",
            r"\caption{変位と高さに対する復元力曲線。}",
            r"\end{figure}",
            r"\section{動的検証結果}\label{sec:result-dynamic}",
            tex_escape(
                f"動的検証 18 エピソードでは，接触回数 0，制約発火 0，ラッチ 0 であり，最悪クリアランスは {primary_dynamic['worst_min_clearance_mm']:.2f} mm，平均スコアは {primary_dynamic['mean_score']:.3f}，最悪スコアは {primary_dynamic['worst_score']:.3f} であった。最悪シナリオは {worst_row['scenario_name']}，最良シナリオは {best_row['scenario_name']} であり，最悪シナリオでも平均並進 RMS は {worst_row['mean_translation_rms_mm']:.3f} mm，平均ヨー RMS は {worst_row['mean_yaw_rms_deg']:.3f} deg に留まった。"
            ),
            r"\begin{longtable}{p{0.24\linewidth}rrrrr}",
            r"\toprule",
            r"Scenario & Worst score & Mean clearance [mm] & Mean translation RMS [mm] & Mean yaw RMS [deg] & Peak height shift [mm] \\",
            r"\midrule",
            r"\endfirsthead",
            r"\toprule",
            r"Scenario & Worst score & Mean clearance [mm] & Mean translation RMS [mm] & Mean yaw RMS [deg] & Peak height shift [mm] \\",
            r"\midrule",
            r"\endhead",
        ]
    )
    for _, row in scenario_table.iterrows():
        lines.append(
            f"{tex_escape(row['scenario_name'])} & {row['worst_score']:.3f} & {row['mean_clearance_mm']:.3f} & "
            f"{row['mean_translation_rms_mm']:.3f} & {row['mean_yaw_rms_deg']:.3f} & {row['peak_height_shift_mm']:.3f} \\\\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{longtable}",
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.93\linewidth]{{{figure_map['best_rollout']}}}",
            r"\caption{代表的な良好シナリオの時系列。}",
            r"\end{figure}",
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.93\linewidth]{{{figure_map['worst_rollout']}}}",
            r"\caption{最悪シナリオの時系列。}",
            r"\end{figure}",
            r"\section{製造比較候補との比較}\label{sec:result-compare}",
            tex_escape(
                f"製造比較候補 `verticalstack78` は，総磁石数 {manufacturing_design['total_magnets']} 個，推定磁石費用 {manufacturing_design['estimated_total_cost_jpy']:.0f} JPY，フル高さ平均剛性 {manufacturing_static['mean_full_height_stiffness_npm']:.2f} N/m，低高さ最小剛性 {manufacturing_static['min_reduced_height_stiffness_npm']:.2f} N/m と，静的には主候補より強い。しかし動的平均スコアは {manufacturing_dynamic['mean_score']:.3f}，最悪クリアランスは {manufacturing_dynamic['worst_min_clearance_mm']:.2f} mm であり，0.45 m/s 回廊搬送での扱いやすさは `limo_stable5` が上回った。すなわち，『磁力の強さ』だけではなく，質量・入力トルク・高さ変化のもとでどれだけ素直に力を返すかが，最終設計の選定に大きく効いている。"
            ),
            candidate_table,
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.95\linewidth]{{{figure_map['shape_progress_compare']}}}",
            r"\caption{探索途中候補と以前の基準形状の比較。}",
            r"\end{figure}",
            r"\section{反力方向・危険領域の可視化}\label{sec:result-maps}",
            tex_escape(
                "力ベクトルマップ，最小ギャップマップ，bad attraction マップを併用して確認すると，主候補は中心近傍から中程度の横変位まで，反力方向の乱れが小さく，危険領域も狭い。完全な円環に近い形は方向一様性が高い一方で回転復元が弱くなりやすく，極端な矢印形状は回転復元を強める代わりに前後方向の寄生成分を増やしやすい。主候補はこの中間に位置し，穏やかな非円形化によって回復モーメントと純反力性の両立を狙った解釈が妥当である。"
            ),
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.90\linewidth]{{{figure_map['force_vector_yaw0']}}}",
            r"\caption{力ベクトルマップ yaw=0。}",
            r"\end{figure}",
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.90\linewidth]{{{figure_map['minimum_gap_yaw0']}}}",
            r"\caption{最小ギャップマップ yaw=0。}",
            r"\end{figure}",
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.90\linewidth]{{{figure_map['bad_attraction_yaw0']}}}",
            r"\caption{吸着危険領域マップ yaw=0。}",
            r"\end{figure}",
            r"\section{限界と今後の課題}\label{sec:result-limit}",
            tex_escape(
                "第一の限界は，磁石材料の完全な B-H 曲線や温度依存性をまだ扱っていない点である。現在は実商品寸法・価格・表面磁束表示を用いた設計用近似であり，材料固有の飽和やヨーク材の影響は簡略化されている。第二に，キャスターの旋回抵抗や床材摩擦は lumped parameter として表現しており，全ての実床条件を再現したわけではない。第三に，設計探索は完成済みランを基にまとめており，長時間アーカイブ探索の全収束結果はまだ反映しきれていない。したがって，本論文ドラフトは『現時点で最も整合的な完成版』である一方，実機検証と更なる長期探索によって改善余地が残る。"
            ),
            "",
        ]
    )

    lines.append(
        chapter_opener_latex(
            "結論",
            [
                ("5.1 結論", "sec:conclusion-main"),
                ("5.2 今後の展望", "sec:conclusion-future"),
            ],
        )
    )
    lines.extend(
        [
            r"\section{結論}\label{sec:conclusion-main}",
            tex_escape(
                "本研究では，DAISO 13 mm ネオジム磁石の有限個配列と，AgileX LIMO・キャスター台車を含む高忠実度シミュレーションを用いて，高さ可変磁気カプラの設計最適化を行った。法線オフセット外形，表面磁束からの等価磁化較正，接触投影付きサブステップ動力学，CEM 系設計探索，方策探索，そして CAD 自動生成を一つのワークフローへ統合した点が主な貢献である。現時点での主候補 `limo_stable5` は，接触 0，ラッチ 0，最悪クリアランス 31.95 mm を維持しつつ，全方向で概ね素直な復元力を返す設計として得られた。"
            ),
            "",
            r"\section{今後の展望}\label{sec:conclusion-future}",
            tex_escape(
                "今後は，実機リングを 3D プリントで製作し，LIMO と実台車を用いた回廊試験で本シミュレーションの妥当性を検証する必要がある。また，長期アーカイブ探索，実測磁場分布のフィッティング，床面種別や積載量の多様化，ならびに使用者の左右手入力を模擬したインタラクティブシミュレータとの統合評価を進めることで，より完成度の高い卒業論文本文へ発展させられる。"
            ),
            "",
            r"\backmatter",
            r"\chapter*{謝辞}",
            tex_escape(
                "本ドラフトでは個人情報欄を未記入としている。提出版では，研究指導，議論，実験環境整備に関して謝意を記す予定である。"
            ),
            "",
            r"\chapter*{参考文献}",
            r"\begin{enumerate}",
        ]
    )
    for entry in references:
        lines.append(rf"\item {tex_escape(strip_reference_prefix(entry))}")
    lines.extend(
        [
            r"\end{enumerate}",
            r"\appendix",
            r"\setcounter{figure}{0}",
            r"\renewcommand{\thefigure}{A-\arabic{figure}}",
            r"\chapter{設計変数一覧}",
            design_variable_table,
        ]
    )
    lines.extend(
        [
            r"\chapter{製造図面一覧}",
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.96\linewidth]{{{figure_map['cad_sheet1']}}}",
            r"\caption{組立図面。}",
            r"\end{figure}",
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.96\linewidth]{{{figure_map['cad_sheet2']}}}",
            r"\caption{内側キャリア図面。}",
            r"\end{figure}",
            r"\begin{figure}[H]\centering",
            rf"\includegraphics[width=0.96\linewidth]{{{figure_map['cad_sheet3']}}}",
            r"\caption{外側キャリア図面。}",
            r"\end{figure}",
            r"\chapter{プログラム構成一覧}",
            program_table,
            r"\end{document}",
        ]
    )
    THESIS_TEX.write_text("\n".join(lines), encoding="utf-8")


def build_figure_map(primary: ResultBundle, manufacturing: ResultBundle) -> dict[str, str]:
    figure_map = {
        "shape_preview": render_shape_preview(primary, "final_shape_preview.png"),
        "field_distribution": copy_figure(primary.directory / "selected_design_field_distribution.png", "final_field_distribution.png"),
        "design_convergence": copy_figure(primary.directory / "design_convergence.png", "final_design_convergence.png"),
        "policy_convergence": copy_figure(primary.directory / "policy_convergence.png", "final_policy_convergence.png"),
        "force_polar": copy_figure(primary.directory / "force_polar.png", "final_force_polar.png"),
        "force_curves": copy_figure(primary.directory / "force_curves.png", "final_force_curves.png"),
        "force_vector_yaw0": copy_figure(primary.directory / "force_vector_map_yaw0.png", "final_force_vector_yaw0.png"),
        "minimum_gap_yaw0": copy_figure(primary.directory / "minimum_gap_map_yaw0.png", "final_minimum_gap_yaw0.png"),
        "bad_attraction_yaw0": copy_figure(primary.directory / "bad_attraction_map_yaw0.png", "final_bad_attraction_yaw0.png"),
        "best_rollout": copy_figure(primary.directory / "best_rollout.png", "final_best_rollout.png"),
        "worst_rollout": copy_figure(primary.directory / "worst_rollout.png", "final_worst_rollout.png"),
        "shape_progress_compare": copy_figure(INTERIM_COMPARE_PNG, "shape_progress_compare.png"),
    }
    if primary.cad_directory:
        figure_map["cad_iso"] = copy_figure(primary.cad_directory / "coupler_isometric_screenshot.png", "final_cad_isometric.png")
        figure_map["cad_sheet1"] = copy_figure(primary.cad_directory / "01_coupler_assembly_sheet.png", "final_cad_sheet1.png")
        figure_map["cad_sheet2"] = copy_figure(primary.cad_directory / "02_inner_carrier_sheet.png", "final_cad_sheet2.png")
        figure_map["cad_sheet3"] = copy_figure(primary.cad_directory / "03_outer_carrier_sheet.png", "final_cad_sheet3.png")
    else:
        figure_map["cad_iso"] = copy_figure(manufacturing.cad_directory / "coupler_isometric_screenshot.png", "fallback_cad_isometric.png")
        figure_map["cad_sheet1"] = copy_figure(manufacturing.cad_directory / "01_coupler_assembly_sheet.png", "fallback_cad_sheet1.png")
        figure_map["cad_sheet2"] = copy_figure(manufacturing.cad_directory / "02_inner_carrier_sheet.png", "fallback_cad_sheet2.png")
        figure_map["cad_sheet3"] = copy_figure(manufacturing.cad_directory / "03_outer_carrier_sheet.png", "fallback_cad_sheet3.png")
    return figure_map


def compile_latex():
    for _ in range(2):
        result = subprocess.run(
            [
                "lualatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                f"-output-directory={OUTDIR}",
                str(THESIS_TEX),
            ],
            cwd=OUTDIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"LuaLaTeX failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def compile_docx():
    result = subprocess.run(
        [
            "pandoc",
            str(THESIS_MD),
            "-o",
            str(THESIS_DOCX),
            "--from=markdown",
            "--toc",
            "--toc-depth=2",
            f"--resource-path={OUTDIR}",
        ],
        cwd=OUTDIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pandoc failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def write_manifest(primary: ResultBundle, manufacturing: ResultBundle, figure_map: dict[str, str]):
    manifest = {
        "title": THESIS_TITLE,
        "generated_files": {
            "markdown": str(THESIS_MD),
            "latex": str(THESIS_TEX),
            "pdf": str(THESIS_PDF),
            "docx": str(THESIS_DOCX),
        },
        "primary_result_dir": str(primary.directory),
        "manufacturing_result_dir": str(manufacturing.directory),
        "figure_map": figure_map,
        "primary_summary": {
            "selected_design": selected_design(primary),
            "static_assessment": static_assessment(primary),
            "dynamic_validation": dynamic_summary(primary),
        },
        "manufacturing_summary": {
            "selected_design": selected_design(manufacturing),
            "static_assessment": static_assessment(manufacturing),
            "dynamic_validation": dynamic_summary(manufacturing),
        },
    }
    MANIFEST_JSON.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    FIGDIR.mkdir(parents=True, exist_ok=True)
    primary = load_result("limo_stable5", PRIMARY_DIR, PRIMARY_CAD_DIR if PRIMARY_CAD_DIR.exists() else None)
    manufacturing = load_result(
        "verticalstack78",
        MANUFACTURING_DIR,
        MANUFACTURING_CAD_DIR if MANUFACTURING_CAD_DIR.exists() else None,
    )
    figure_map = build_figure_map(primary, manufacturing)
    write_markdown(primary, manufacturing, figure_map)
    write_latex(primary, manufacturing, figure_map)
    compile_latex()
    compile_docx()
    write_manifest(primary, manufacturing, figure_map)
    print(str(THESIS_PDF))
    print(str(THESIS_DOCX))


if __name__ == "__main__":
    main()
