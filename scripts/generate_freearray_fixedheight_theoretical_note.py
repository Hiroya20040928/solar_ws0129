import argparse
import json
import math
import subprocess
from pathlib import Path

import pandas as pd


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a concise theoretical note for the fixed-height free-array magnetic coupler study."
    )
    parser.add_argument(
        "--result-dir",
        type=Path,
        required=True,
        help="Directory containing selected_design.json and report assets.",
    )
    return parser.parse_args()


def escape_tex(text: str) -> str:
    return (
        text.replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("#", "\\#")
        .replace("_", "\\_")
        .replace("^", "\\^{}")
        .replace("~", "\\~{}")
        .replace("{", "\\{")
        .replace("}", "\\}")
    )


def file_lines(result_dir: Path):
    root = result_dir.parents[1]
    candidates = [
        root / "mpc_solarcar" / "magnetic_coupler_rl.py",
        root / "mpc_solarcar" / "magnetic_coupler_hifi.py",
        root / "mpc_solarcar" / "magnetic_coupler_freearray_fixedheight.py",
        root / "scripts" / "generate_freearray_fixedheight_theoretical_note.py",
        result_dir / "selected_design.json",
        result_dir / "case_summary.csv",
        result_dir / "selected_dynamic_summary.csv",
        result_dir / "freearray_fixedheight_report_ja.pdf",
        result_dir / "freearray_fixedheight_theoretical_note_ja.pdf",
    ]
    lines = []
    for path in candidates:
        if path.exists():
            try:
                rel = path.relative_to(root)
            except ValueError:
                rel = path
            lines.append(str(rel).replace("\\", "/"))
    return lines


def main():
    args = parse_args()
    result_dir = args.result_dir.resolve()
    payload = json.loads((result_dir / "selected_design.json").read_text(encoding="utf-8"))
    case_df = pd.read_csv(result_dir / "case_summary.csv")
    dynamic_df = pd.read_csv(result_dir / "selected_dynamic_summary.csv")

    design = payload["design"]
    static = payload["static_assessment"]
    best_case = case_df.sort_values(["ranking_score"], ascending=False).iloc[0].to_dict()
    worst_dynamic = dynamic_df.sort_values(["score"]).iloc[0].to_dict()

    file_items = "\n".join(f"\\item \\texttt{{{escape_tex(item)}}}" for item in file_lines(result_dir))

    tex = rf"""
\documentclass[a4paper,11pt]{{article}}
\usepackage[margin=20mm]{{geometry}}
\usepackage{{fontspec}}
\usepackage{{xeCJK}}
\usepackage{{amsmath,amssymb,bm,mathtools}}
\usepackage{{graphicx}}
\usepackage{{booktabs,longtable,array}}
\setmainfont{{Times New Roman}}
\setmonofont{{Consolas}}
\setCJKmainfont{{Yu Mincho}}
\setCJKmonofont{{Yu Gothic UI}}
\setlength{{\parskip}}{{0.45em}}
\setlength{{\parindent}}{{1em}}
\renewcommand{{\arraystretch}}{{1.18}}
\begin{{document}}

\begin{{center}}
{{\LARGE 自由配置・固定高さ磁気カプラ理論ノート}}\\[0.6em]
{{\large 添付「磁石配置と力マップ.pdf」を踏まえた再定式化と結果整理}}\\[0.4em]
2026-07-05
\end{{center}}

\section*{{1. 結論}}
今回の exact free-array fixed-height 再探索では，半ピッチずれを前提にせず，磁石個数，取り付け半径，角度，磁化方向を自由化した．
その結果，\textbf{{固定高さのみ}}・\textbf{{速度 0.45 m/s}}・\textbf{{避けて戻る単独シナリオ}}という条件に絞っても，
\textbf{{接触 0 / めり込み 0 / クリップ 0}} を同時に満たす存在解は，今回の探索範囲では得られなかった．
最良ケースは \texttt{{8 in / 12 out / 0.10 kg / 1 layer}} であり，最小クリアランス 0 mm，最大めり込み {worst_dynamic['max_penetration_mm']:.3f} mm，
接触イベント {int(worst_dynamic['contact_events'])} 回で止まっている．

\section*{{2. 添付PDFの基本式と今回の拡張}}
添付PDFの最も基本の量は，外側固定・内側移動のときの中心復元方向成分
\begin{{equation}}
F(r,\theta) = -\bm{{F}}_{{\mathrm{{tot}}}}(r,\theta)\cdot \bm{{e}}_r,
\qquad
\bm{{e}}_r = \begin{{bmatrix}}\cos\theta & \sin\theta & 0\end{{bmatrix}}^\top
\end{{equation}}
である．この考え方自体は正しい．
ただし，今回ユーザーが指摘した通り，\textbf{{半ピッチずれは閉じた等間隔リング理論の一つの十分条件であって，自由配置問題の唯一解ではない}}．

したがって今回は状態を
\begin{{equation}}
\bm{{q}} = \begin{{bmatrix}}x & y & \phi\end{{bmatrix}}^\top
\end{{equation}}
とし，理想平衡近傍で
\begin{{equation}}
\bm{{g}}(\bm{{q}}) =
\begin{{bmatrix}}F_x(\bm{{q}})\\F_y(\bm{{q}})\\\tau_z(\bm{{q}})\end{{bmatrix}}
\approx
-\bm{{K}}\bm{{q}},
\quad
\bm{{K}} =
\begin{{bmatrix}}
K_{{xx}} & K_{{xy}} & K_{{x\phi}}\\
K_{{xy}} & K_{{yy}} & K_{{y\phi}}\\
K_{{x\phi}} & K_{{y\phi}} & K_{{\phi\phi}}
\end{{bmatrix}}
\end{{equation}}
を満たすことを目標にした．

要求条件は添付PDFの記号に沿って，
\begin{{align}}
K_{{xx}} &> 0, &
K_{{yy}} &> 0, &
K_{{\phi\phi}} &> 0, \\
K_{{xy}} &\approx 0, &
K_{{x\phi}} &\approx 0, &
K_{{y\phi}} &\approx 0
\end{{align}}
である．

\section*{{3. 現在の exact モデル}}
\subsection*{{3.1 設計変数}}
今回の自由配置設計では，各磁石について
\begin{{equation}}
(\alpha_i, r_i, \gamma_i)
\end{{equation}}
を持たせた．ここで $\alpha_i$ は取り付け角，$r_i$ は中心からの半径，$\gamma_i$ は半径法線からの取り付け傾きである．
内側磁石中心は
\begin{{equation}}
\bm{{c}}_i^{{\mathrm{{in}}}}
=
\begin{{bmatrix}}
r_i^{{\mathrm{{in}}}}\cos\alpha_i^{{\mathrm{{in}}}}\\
r_i^{{\mathrm{{in}}}}\sin\alpha_i^{{\mathrm{{in}}}}\\
z_\ell
\end{{bmatrix}}
- \frac{{t}}{{2}}\hat{{\bm{{m}}}}_i^{{\mathrm{{in}}}},
\end{{equation}}
外側磁石中心は
\begin{{equation}}
\bm{{c}}_j^{{\mathrm{{out}}}}
=
\begin{{bmatrix}}
r_j^{{\mathrm{{out}}}}\cos\alpha_j^{{\mathrm{{out}}}}\\
r_j^{{\mathrm{{out}}}}\sin\alpha_j^{{\mathrm{{out}}}}\\
z_\ell
\end{{bmatrix}}
+ \frac{{t}}{{2}}\hat{{\bm{{m}}}}_j^{{\mathrm{{out}}}}
\end{{equation}}
と置いた．

\subsection*{{3.2 磁力計算}}
ここでは点双極子近似を探索の外に追いやり，\textbf{{Magpylib 5.2.3 の解析解ベース force/torque 計算}}を探索ループ内部に直接使った．
したがって一般化力は
\begin{{equation}}
\bm{{g}}(\bm{{q}})
=
\sum_j
\mathrm{{getFT}}\!\left(
\mathcal{{S}}_{{\mathrm{{in}}}},
\mathcal{{T}}_j(\bm{{q}})
\right)
\end{{equation}}
として exact cylinder model から直接得ている．

\subsection*{{3.3 剛性行列}}
平衡点まわりの剛性は中央差分で
\begin{{equation}}
\bm{{K}} \approx -\frac{{\partial \bm{{g}}}}{{\partial \bm{{q}}}}
\end{{equation}}
とし，実装では
\begin{{equation}}
K_{{:,k}}
\approx
-\frac{{\bm{{g}}(\bm{{q}}+\Delta_k \bm{{e}}_k)-\bm{{g}}(\bm{{q}}-\Delta_k \bm{{e}}_k)}}{{2\Delta_k}}
\end{{equation}}
で評価した．

\section*{{4. 動力学}}
ロボットは AgileX LIMO 相当として，並進は速度指令追従・加速度制限付き，
\begin{{equation}}
v_{{k+1}} = \mathrm{{clip}}\left(v_k + a_{{\mathrm{{cmd}}}} \Delta t,\ 0,\ 0.45\right)
\end{{equation}}
で更新した．姿勢は
\begin{{equation}}
\omega_{{r,k+1}}
=
\mathrm{{clip}}\left(
\omega_{{r,k}} + \dot\omega_{{r,\mathrm{{cmd}}}}\Delta t,
\ -0.80,\ 0.80
\right)
\end{{equation}}
で拘束した．

台車は
\begin{{align}}
m_c \dot{{\bm{{v}}}}_c &= \bm{{F}}_{{\mathrm{{human}}}} + \bm{{F}}_{{\mathrm{{mag}}}} + \bm{{F}}_{{\mathrm{{passive}}}} + \bm{{F}}_{{\mathrm{{contact}}}},\\
I_c \dot{{\omega}}_c &= \tau_{{\mathrm{{human}}}} + \tau_{{\mathrm{{mag}}}} + \tau_{{\mathrm{{passive}}}} + \tau_{{\mathrm{{contact}}}}
\end{{align}}
で更新した．

受動抵抗には，
\begin{{itemize}}
\item 転がり抵抗係数 0.035
\item 横方向抵抗比 1.8
\item キャスタ trail 28 mm
\item 一次遅れキャスタ整列
\end{{itemize}}
を用いた．接触は
\begin{{equation}}
F_n = k_n \delta + c_n \max(-\dot\delta,0),
\qquad
k_n = 80\ \mathrm{{kN/m}},
\quad
c_n = 320\ \mathrm{{N\,s/m}}
\end{{equation}}
で与えた．物理クリアランスは 0 mm 未満を許さず，\texttt{{contact\_demand}} 側にのみめり込み要求を記録した．

\section*{{5. 今回の数値条件}}
今回の existence search で用いた運搬条件は次の通りである．
\begin{{center}}
\begin{{tabular}}{{p{{27mm}}p{{111mm}}}}
\toprule
項目 & 値 \\
\midrule
ロボット速度 & 0--1 s: 0.45 m/s$^2$ で加速，1--2.4 s: 0.45 m/s 巡航 \\
人入力 & 2.4--3.1 s: $F_x=+6.0$ N, $F_y=+2.0$ N, $\tau=-1.40$ N\,m \\
人入力(保持) & 3.1--4.2 s: $F_x=+3.5$ N, $F_y=+1.2$ N, $\tau=-0.80$ N\,m \\
解除後 & 4.2--8.0 s: 入力 0，ロボットは結合誤差に追従補償 \\
路面/台車 & 質量探索値 0.10 または 0.25 kg，転がり抵抗係数 0.035，横比 1.8 \\
評価対象 & (8,8), (8,12) 磁石，1 層，固定高さ，名目環境 1 本 \\
\bottomrule
\end{{tabular}}
\end{{center}}

\section*{{6. 探索結果}}
ケースサマリ最良行は次の通りである．
\begin{{equation}}
\texttt{{8 in / 12 out / 0.10 kg / 1 layer}}
\end{{equation}}
であり，主要値は
\begin{{align}}
\text{{static score}} &= {best_case['static_score']:.3f},\\
\text{{ranking score}} &= {best_case['ranking_score']:.3f},\\
\text{{worst clearance}} &= {best_case['worst_clearance_mm']:.3f}\ \mathrm{{mm}},\\
\text{{max penetration}} &= {best_case['max_penetration_mm']:.3f}\ \mathrm{{mm}},\\
\text{{contact events}} &= {int(best_case['contact_events_total'])},\\
\text{{clip total}} &= {int(best_case['dynamic_clip_total'])}
\end{{align}}
であった．

これは，\textbf{{接触ゼロに届いていない}}だけでなく，\textbf{{台車運動を物理上限で多数回クリップしなければ数値的に破綻する}}ことも意味する．
したがって，今回の条件では「実機投入可能」と断言できる存在解はまだ得られていない．

\section*{{7. 解釈}}
今回の結果から，ユーザーの指摘は妥当である．
\begin{{enumerate}}
\item 半ピッチずれを唯一の基本解とみなす必要はない．自由配置では，対向ペアで並進復元を，外周側磁石で回転復元を担わせる設計のほうが一般的である．
\item ただし，固定高さのみで ``直進時は高剛性，避け入力時は容易に角度差が出る'' を両立するのは難しい．
\item したがって次段では，(i) 人入力シナリオの現実的再定義，(ii) 高さ可変の再導入，(iii) 8 方向対称を陽に埋め込んだ低次元構造最適化，の順で進めるのが合理的である．
\end{{enumerate}}

\section*{{8. 主要ファイル}}
\begin{{itemize}}
{file_items}
\end{{itemize}}

\section*{{9. 図}}
\begin{{figure}}[h]
\centering
\includegraphics[width=0.72\linewidth]{{selected_layout.png}}
\caption{{今回の最良候補の自由配置レイアウト}}
\end{{figure}}

\begin{{figure}}[h]
\centering
\includegraphics[width=0.72\linewidth]{{selected_field_map.png}}
\caption{{最良候補の $z=0$ 磁場強度分布}}
\end{{figure}}

\begin{{figure}}[h]
\centering
\includegraphics[width=0.88\linewidth]{{selected_dynamic_nominal.png}}
\caption{{名目 avoid/return シナリオの動的履歴}}
\end{{figure}}

\end{{document}}
"""

    tex_path = result_dir / "freearray_fixedheight_theoretical_note_ja.tex"
    tex_path.write_text(tex, encoding="utf-8")
    for _ in range(2):
        subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
            cwd=str(result_dir),
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )


if __name__ == "__main__":
    main()
