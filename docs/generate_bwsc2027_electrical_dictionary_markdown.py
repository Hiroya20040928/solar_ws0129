# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path


DOCS_DIR = Path(__file__).resolve().parent
REPO_ROOT = DOCS_DIR.parent
SOURCE_TXT = DOCS_DIR / "source_background.txt"
OUT_MD = DOCS_DIR / "bwsc2027_electrical_dictionary_book.md"


MAIN_TITLES = {
    1: "電気を考えるための最小単位",
    2: "回路とは何か",
    3: "導体，絶縁体，半導体",
    4: "金属中の電流",
    5: "液体中の電流",
    6: "水と感電",
    7: "直流と交流",
    8: "相，単相，三相，単相交流",
    9: "GND，グラウンド，アース",
    10: "感電が起こる条件",
    11: "アース線の役割",
    12: "漏電とは何か",
    13: "漏電遮断器の原理",
    14: "電圧源とは何か",
    15: "CV モードと CC モード",
    16: "短絡と重い負荷",
    17: "電力，W，電圧，電流",
    18: "バッテリーとは何か",
    19: "酸化，還元，電位",
    20: "原子，電子殻，イオン化エネルギー",
    21: "LiPo バッテリー",
    22: "OCV と使用中の端子電圧",
    23: "C レート，Ah，Wh",
    24: "バッテリー充電と CC-CV",
    25: "過充電と過放電",
    26: "発電の原理",
    27: "トルク，回転数，馬力，電力",
    28: "全体の整理",
    29: "電子回路を構成する部品の分類",
    30: "受動素子の基本",
    31: "抵抗",
    32: "コンデンサ",
    33: "コイル",
    34: "トランス",
    35: "ダイオード",
    36: "能動素子の基本",
    37: "BJT",
    38: "MOSFET",
    39: "オペアンプ",
    40: "コンパレータ",
    41: "電圧レギュレータ",
    42: "ロジック IC",
    43: "マイコンとは何か",
    44: "マイコンの入力端子",
    45: "マイコンの出力端子",
    46: "PWM とは何か",
    47: "PWM と MOSFET 駆動",
    48: "テスターで能動素子やマイコンを測ると抵抗値が出る理由",
    49: "テスター測定で壊れる場合",
    50: "ノイズとは何か",
    51: "熱雑音",
    52: "ショット雑音",
    53: "1/f 雑音",
    54: "電源ノイズ",
    55: "グラウンドノイズ",
    56: "EMI と EMC",
    57: "クロストーク",
    58: "量子化ノイズ",
    59: "ノイズ対策の全体設計",
    60: "過渡現象とは何か",
    61: "RC 回路の過渡現象",
    62: "RL 回路の過渡現象",
    63: "RLC 回路と二次系",
    64: "不足制動，臨界制動，過制動",
    65: "スイッチ，リレー，モーターの過渡現象",
    66: "制御理論とは何か",
    67: "開ループ制御と閉ループ制御",
    68: "伝達関数",
    69: "ゲインとは何か",
    70: "周波数応答",
    71: "ゲイン線図と位相線図",
    72: "安定性",
    73: "PID 制御",
    74: "フィルタとは何か",
    75: "ローパスフィルタ",
    76: "ハイパスフィルタ",
    77: "バンドパスフィルタとノッチフィルタ",
    78: "フィルタ設計と制御の関係",
    79: "デジタルフィルタ",
    80: "サンプリングとエイリアシング",
    81: "マイコン内部の動き",
    82: "ADC",
    83: "通信回路",
    84: "フィルタ回路の実用設計手順",
    85: "スナバ回路",
    86: "能動素子とノイズの関係",
    87: "なぜフィルタがノイズ対策になるか",
    88: "制御理論とフィルタの接続",
    89: "電気回路，制御，マイコンの関係",
    90: "全体の整理",
    91: "BWSC ソーラーカー電装系とは何か",
    92: "BWSC 電装系の全体構成",
    93: "開発の最初に決めるべき要求仕様",
    94: "電力収支の基本",
    95: "走行抵抗と必要駆動電力",
    96: "太陽電池アレイ",
    97: "太陽電池の基本式",
    98: "太陽電池アレイ設計の手順",
    99: "MPPT の選定",
    100: "バッテリーパック設計",
    101: "バッテリー直列数と並列数",
    102: "セル選定の実務",
    103: "BMS",
    104: "SOC 推定",
    105: "接触器",
    106: "プリチャージ",
    107: "ヒューズとブレーカ",
    108: "配線設計",
    109: "線径選定",
    110: "配線経路",
    111: "コネクタ選定",
    112: "圧着",
    113: "高電圧系と低電圧系",
    114: "DC-DC コンバータ",
    115: "電源分配",
    116: "計測系の目的",
    117: "電圧測定",
    118: "電流測定",
    119: "温度測定",
    120: "速度測定",
    121: "日射量測定",
    122: "通信系の全体",
    123: "CAN 通信",
    124: "CAN 設計の実務",
    125: "UART，SPI，I2C",
    126: "テレメトリ",
    127: "LoRa 通信",
    128: "位相ズレと伝送速度",
    129: "センサ線の線長差",
    130: "ドライバーディスプレイ",
    131: "灯火系",
    132: "ホーン",
    133: "リアビジョン",
    134: "絶縁監視",
    135: "safe state",
    136: "HVIL",
    137: "サービスプラグ",
    138: "モーターとインバータ",
    139: "回生",
    140: "補機電力",
    141: "ロギング",
    142: "データ欠損対策",
    143: "エネルギーマネジメント",
    144: "MPC と電装系の接続",
    145: "故障診断",
    146: "接触器溶着検出",
    147: "ノイズ設計",
    148: "フィルタ設計",
    149: "熱設計",
    150: "防水防塵",
    151: "基板設計",
    152: "ソフトウェア設計",
    153: "ウォッチドッグ",
    154: "試験手順",
    155: "製作管理",
    156: "部品選定の優先順位",
    157: "最低限の推奨構成",
    158: "絶対に避ける設計",
    159: "文系学生が実際に開発できる学習順序",
    160: "最終的な設計思想",
}


PARTS = [
    (
        "第1部 電気と物質の辞書",
        [
            ("第1章 電気の最小概念と安全", 1, 17),
            ("第2章 電池と電気化学", 18, 25),
            ("第3章 発電と機械のつながり", 26, 28),
        ],
    ),
    (
        "第2部 電子回路・計測・制御の辞書",
        [
            ("第4章 回路部品と半導体", 29, 49),
            ("第5章 ノイズと過渡現象", 50, 65),
            ("第6章 制御・フィルタ・マイコン", 66, 90),
        ],
    ),
    (
        "第3部 BWSC2027 電装システムの辞書",
        [
            ("第7章 車両全体像と要求仕様", 91, 95),
            ("第8章 発電系", 96, 99),
            ("第9章 蓄電系", 100, 107),
            ("第10章 配線と補機電源", 108, 115),
            ("第11章 計測・通信・表示", 116, 133),
            ("第12章 安全機構と駆動系", 134, 149),
            ("第13章 防水・基板・ソフト・試験・製作", 150, 160),
        ],
    ),
]


FIGURES_BY_SECTION = {
    22: [
        (
            "assets/bwsc2027_electrical_dictionary/battery_ocv_soc_identified.png",
            "図1: 識別結果によるバッテリーパックの OCV-SOC 特性。出典: `outputs/identification/ocv_soc_curve_identified.csv`。",
        ),
    ],
    99: [
        (
            "assets/bwsc2027_electrical_dictionary/panel_efficiency_identified.png",
            "図2: 識別結果によるパネル効率。出典: `outputs/identification/panel_eff_map_identified.csv`。",
        ),
        (
            "assets/bwsc2027_electrical_dictionary/mppt_efficiency_identified.png",
            "図3: 識別結果による MPPT 効率。出典: `outputs/identification/mppt_eff_map_identified.csv`。",
        ),
    ],
    100: [
        (
            "assets/bwsc2027_electrical_dictionary/battery_rint_identified.png",
            "図4: 識別結果によるパック内部抵抗。出典: `outputs/identification/Rint_T_by_soc_identified.csv`。",
        ),
    ],
}


def parse_main_sections(text: str) -> OrderedDict[int, tuple[str, list[str]]]:
    lines = text.replace("\x0c", "\n").splitlines()
    sections: OrderedDict[int, tuple[str, list[str]]] = OrderedDict()
    expected = 1
    current_num: int | None = None
    current_title = ""
    current_lines: list[str] = []

    for raw in lines:
        stripped = raw.strip()
        if expected <= len(MAIN_TITLES):
            expected_heading = f"{expected}．{MAIN_TITLES[expected]}"
        else:
            expected_heading = None
        if expected_heading is not None and stripped == expected_heading:
            if current_num is not None:
                sections[current_num] = (current_title, current_lines)
            current_num = expected
            current_title = MAIN_TITLES[expected]
            current_lines = []
            expected += 1
            continue
        if current_num is not None:
            current_lines.append(raw.rstrip())

    if current_num is not None:
        sections[current_num] = (current_title, current_lines)

    return sections


def clean_equation(lines: list[str]) -> str:
    expr = " ".join(line.strip() for line in lines)
    expr = re.sub(r"\s+", " ", expr).strip()
    return expr


def reflow_section(lines: list[str]) -> list[str]:
    blocks: list[str] = []
    paragraph: list[str] = []
    in_math = False
    math_lines: list[str] = []

    def flush_paragraph() -> None:
        if paragraph:
            text = "".join(paragraph).strip()
            text = re.sub(r"\s+", " ", text)
            text = sanitize_inline_math(text)
            if text:
                blocks.append(text)
            paragraph.clear()

    def paragraph_can_break() -> bool:
        if not paragraph:
            return True
        joined = "".join(paragraph).rstrip()
        return bool(joined) and joined[-1] in "。．？！：;)]）」』"

    for raw in lines:
        line = raw.replace("\x0c", "").strip()
        if not line:
            if paragraph_can_break():
                flush_paragraph()
            continue
        if line == "BWSC ソーラーカー電装系開発の完全手引き":
            flush_paragraph()
            continue
        if line == "[":
            flush_paragraph()
            in_math = True
            math_lines = []
            continue
        if in_math:
            if line == "]":
                expr = clean_equation(math_lines)
                if expr:
                    blocks.append("$$\n" + expr + "\n$$")
                in_math = False
                math_lines = []
            else:
                math_lines.append(line)
            continue
        if re.match(r"^\d+．", line):
            flush_paragraph()
            item = re.sub(r"^\d+．", "", line).strip()
            blocks.append(f"- {item}")
            continue
        if line.startswith("・"):
            flush_paragraph()
            blocks.append(f"- {line[1:].strip()}")
            continue
        paragraph.append(line)

    flush_paragraph()
    return blocks


def sanitize_inline_math(text: str) -> str:
    def replace_parenthesized(match: re.Match[str]) -> str:
        inner = match.group(1)
        if any(token in inner for token in ("\\", "_", "^", "=", ">", "<")):
            return f"${inner}$"
        return f"({inner})"

    return re.sub(r"\(([^()\n]+)\)", replace_parenthesized, text)


def make_front_matter() -> str:
    return """---
title: "BWSC2027 ソーラーカー電装系開発辞書"
date: "2026-06-21"
lang: ja-JP
documentclass: article
papersize: a4
fontsize: 11pt
mainfont: "Times New Roman"
CJKmainfont: "Yu Gothic"
monofont: "Consolas"
geometry:
  - top=18mm
  - bottom=20mm
  - left=18mm
  - right=18mm
colorlinks: true
linkcolor: black
urlcolor: black
toc-title: "目次"
header-includes:
  - \\usepackage{xeCJK}
  - \\usepackage{booktabs}
  - \\usepackage{longtable}
  - \\usepackage{array}
  - \\usepackage{float}
  - \\setlength{\\parskip}{0.35em}
  - \\setlength{\\parindent}{1em}
  - \\renewcommand{\\arraystretch}{1.15}
---
"""


def make_intro() -> str:
    return """
# 使い方

本書は辞書として使う。最初から読むこともできるが、基本的には「大分類」を開き、その中の項目を順に参照する構成である。説明は、元資料の文体を保ち、余計な装飾を避けて、定義、式、意味、設計上の注意へ進む形で書く。

本書に入れる図は、根拠のあるものだけに限定する。概念図で済ませず、可能なものは `outputs/identification` や `maps` にある識別結果・モデルデータから作図する。したがって、図の数は多くないが、入っている図には出典を付ける。

BWSC2027 に関する公式条件は、2026年6月21日時点で確認した `2027 Event Regulations` と `2027 Team Manager's Guide` に基づく[^reg2027][^guide2027]。ただし、本書の中心は規則要約ではなく、電圧とは何か、電流とは何か、というレベルから電装系全体までを分類して説明することである。
"""


def render_section(number: int, title: str, lines: list[str]) -> str:
    out: list[str] = [f"### {number}．{title}", ""]
    for block in reflow_section(lines):
        out.append(block)
        out.append("")
    for figure_path, note in FIGURES_BY_SECTION.get(number, []):
        out.append(f"![]({figure_path}){{ width=82% }}")
        out.append("")
        out.append(note)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def build_document(sections: OrderedDict[int, tuple[str, list[str]]]) -> str:
    parts: list[str] = [make_front_matter(), make_intro().strip(), ""]

    for part_title, groups in PARTS:
        parts.append(f"# {part_title}")
        parts.append("")
        for group_title, start, end in groups:
            parts.append(f"## {group_title}")
            parts.append("")
            for num in range(start, end + 1):
                title, lines = sections[num]
                parts.append(render_section(num, title, lines).rstrip())
                parts.append("")

    parts.append("# 出典")
    parts.append("")
    parts.append("[^reg2027]: Bridgestone World Solar Challenge, *2027 Event Regulations* (Version 1.0, published 2026-05-07), https://assets.worldsolarchallenge.org/app/uploads/2026/05/06130905/2027-BWSC-Event-Regulations-V1.0-Published-07052026.pdf, accessed 2026-06-21.")
    parts.append("")
    parts.append("[^guide2027]: Bridgestone World Solar Challenge, *2027 Team Manager's Guide* (Version 1, published 2026-05-07), https://assets.worldsolarchallenge.org/app/uploads/2026/05/06130911/2027-BWSC-Team-Managers-Guide-V1-Published-07052026.pdf, accessed 2026-06-21.")
    parts.append("")
    parts.append("本書の本文の主な出典は `0620_シャシダイナモメータを用いた最適エネルギーマネジメント手法の開発_前提知識資料.pdf` である。図の主な出典は `outputs/identification/ocv_soc_curve_identified.csv`、`outputs/identification/Rint_T_by_soc_identified.csv`、`outputs/identification/panel_eff_map_identified.csv`、`outputs/identification/mppt_eff_map_identified.csv` である。")
    parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    text = SOURCE_TXT.read_text(encoding="utf-8")
    sections = parse_main_sections(text)
    if len(sections) != 160:
        raise RuntimeError(f"expected 160 main sections, got {len(sections)}")
    document = build_document(sections)
    OUT_MD.write_text(document, encoding="utf-8")


if __name__ == "__main__":
    main()
