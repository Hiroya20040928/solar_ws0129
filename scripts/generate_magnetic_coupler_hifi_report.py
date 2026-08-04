import ast
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\user\OneDrive - 和歌山大学\ソーラー\エネマネ\solar_ws0129-main")
SOURCE_FILE = ROOT / "mpc_solarcar" / "magnetic_coupler_hifi.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_rl as base


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


def load_payload(outdir: Path):
    payload = json.loads((outdir / "best_design_hifi.json").read_text(encoding="utf-8"))
    dynamic_rows = []
    csv_path = outdir / "dynamic_validation.csv"
    lines = csv_path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split(",")
    for row in lines[1:]:
        values = row.split(",")
        dynamic_rows.append(dict(zip(header, values)))
    return payload, dynamic_rows


def extract_symbol_summary():
    source_text = SOURCE_FILE.read_text(encoding="utf-8")
    module = ast.parse(source_text)
    rows = []
    for node in module.body:
        if isinstance(node, ast.ClassDef):
            doc = ast.get_docstring(node) or ""
            rows.append((node.lineno, "class", node.name, doc.splitlines()[0] if doc else "クラス定義。"))
        elif isinstance(node, ast.FunctionDef):
            doc = ast.get_docstring(node) or ""
            rows.append((node.lineno, "function", node.name, doc.splitlines()[0] if doc else "関数定義。"))
    return rows


def write_ascii_safe_listing(outdir: Path):
    listing_path = outdir / "magnetic_coupler_hifi_ascii_listing.py"
    source_text = SOURCE_FILE.read_text(encoding="utf-8")
    safe_text = source_text.encode("ascii", "backslashreplace").decode("ascii")
    listing_path.write_text(safe_text, encoding="utf-8")
    return listing_path


def build_dynamic_table(dynamic_rows):
    rendered = []
    for row in dynamic_rows:
        scenario_label = row.get("scenario_label", row["scenario_name"])
        min_clearance_mm = float(row.get("min_clearance_mm", row["min_gap_mm"]))
        max_contact_demand_mm = float(row.get("max_contact_demand_mm", row["max_penetration_mm"]))
        rendered.append(
            " & ".join(
                [
                    tex_escape(scenario_label),
                    f"{float(row['score']):.1f}",
                    row["contact_events"],
                    row.get("constraint_activations", "0"),
                    row["latched"],
                    f"{min_clearance_mm:.2f}",
                    f"{max_contact_demand_mm:.3f}",
                    f"{float(row['translation_rms_mm']):.2f}",
                    f"{float(row['yaw_rms_deg']):.2f}",
                    f"{float(row['turn_latency_s']):.3f}",
                    f"{float(row['recenter_s']):.3f}",
                ]
            )
            + r" \\"
        )
    return rendered


def write_report(outdir: Path):
    payload, dynamic_rows = load_payload(outdir)
    listing_path = write_ascii_safe_listing(outdir)
    listing_rel = Path(os.path.relpath(listing_path, outdir)).as_posix()
    selected_design = payload["selected_design"]
    shape_params = selected_design["shape_parameters"]
    selected_sku = base.MAGNET_CATALOG_BY_ID[selected_design["magnet_sku_id"]]
    disk_stack_limit_mm = float(payload.get("search", {}).get("disk_stack_height_limit_mm", 78.0))
    shape_family_mode = payload.get("search", {}).get("shape_family_mode", "flex")
    selected_shape_family = shape_params.get("family", "flex")
    symbol_rows = extract_symbol_summary()
    tex_path = outdir / "magnetic_coupler_hifi_report_ja.tex"

    best_rollout_exists = (outdir / "best_rollout.png").exists()
    worst_rollout_exists = (outdir / "worst_rollout.png").exists()
    extra_reference_lines = []
    if selected_sku.vendor == "DAISO":
        extra_reference_lines.append(
            r"\noindent 補助根拠（パッケージ磁束密度の公開記述）: \url{https://note.com/madara_typer/n/n3c683bb54b18}\\"
        )

    lines = [
        r"\documentclass[a4paper,11pt]{ltjsarticle}",
        r"\usepackage[margin=18mm]{geometry}",
        r"\usepackage{graphicx}",
        r"\usepackage{booktabs}",
        r"\usepackage{longtable}",
        r"\usepackage{array}",
        r"\usepackage{hyperref}",
        r"\usepackage{xcolor}",
        r"\usepackage{listings}",
        r"\usepackage{caption}",
        r"\usepackage{float}",
        r"\usepackage{titlesec}",
        r"\usepackage{luatexja-fontspec}",
        r"\setmainjfont{Yu Mincho}",
        r"\setsansjfont{Yu Gothic}",
        r"\setmonofont{Consolas}",
        r"\hypersetup{unicode=true,colorlinks=true,linkcolor=blue,urlcolor=blue}",
        r"\titleformat{\section}{\large\bfseries}{\thesection}{0.6em}{}",
        r"\titleformat{\subsection}{\normalsize\bfseries}{\thesubsection}{0.6em}{}",
        r"\lstset{basicstyle=\ttfamily\scriptsize,breaklines=true,columns=fullflexible,frame=single,numbers=left,numberstyle=\tiny,stepnumber=1,tabsize=4}",
        r"\begin{document}",
        r"\begin{center}",
        r"{\LARGE 高忠実度磁気カプラ最適化報告書}\\[4mm]",
        r"{\large 実商品磁石・有限配列・高さ可変・収束結果}",
        r"\end{center}",
        r"\vspace{4mm}",
        r"\section{目的と前提}",
        r"\noindent 本報告書の目的は、有限個の実商品ネオジム磁石を周方向に並べた磁気カプラについて、"
        r" 全方向からの外力に対して常に反対向きの復元力を返し、横ずれ吸着やラッチを避け、"
        r" さらに高さ可変時にも十分な復元力を維持する形状と制御則を、数値最適化により探索した結果をまとめることである。"
        r" 今回は GUI 表示ではなく、実磁石有限配列の力学評価と収束報告に重点を置いた。",
        r"\section{根拠モデル}",
        r"\noindent 磁場モデルは、均一磁化永久磁石の解析で一般に用いられる Coulombian / surface-charge 系の考え方に整合するよう、"
        r" 各磁石を小体積双極子群へ離散化して重ね合わせる方法で構成した。"
        r" 円弧状磁石や円筒タイル磁石については、均一磁化体の磁場が解析的に扱えることが文献で示されており、"
        r" 本実装はそれを有限個 SKU 配列へ落とし込むための計算可能な近似である。"
        r" カタログ値からは寸法、表面磁束密度、吸着力、価格を使用し、吸着力から等価磁束密度を再計算して有効磁化強度へ反映した。",
        r"\section{今回の主修正}",
        r"\noindent 外側形状生成: 非円形でも法線ギャップ一定になるよう、原点相似拡大ではなく内側境界の法線オフセットで外側境界を生成した。\\",
        r"\noindent DAISO円盤磁束較正: 240 mT をそのまま磁化強度とせず、一様磁化円柱の軸上表面磁束式から等価 remanence を逆算して双極子モーメントへ反映した。\\",
        r"\noindent 動的接触: サブステップ積分、接触後の位置投影、法線速度補正、ばらつき環境を導入し、粗い一発積分での深い貫入を抑えた。\\",
        r"\noindent 接触報告: 物理クリアランスは常に 0 mm 以上で記録し、接触前に要求された重なり量だけを「接触要求量」として別管理するよう改めた。\\",
        r"\noindent 別添『磁石反発力の可視化.pdf』反映: 単体の同極対向ディスク対は横方向に自動センタリングせず、半ピッチずれ列では接近方向反発よりコギング的なせん断抵抗を感じやすい。"
        r" このため、本改造では平均直交漏れ比と寄生トルク比の罰則を強め、"
        r" 「重く感じるだけの配置」ではなく「外力に対して反対向きの純反力を返す配置」を優先するようにした。\\",
        r"\noindent 形状探索拡張: 従来の滑らかな半径関数族に加え、斜辺による復元モーメントを直接検証するため、逆矢印系の明示形状族も探索対象へ追加した。\\",
        rf"\noindent 実装制約: DAISO 13 mm 円盤の縦積みスタック高さを約{disk_stack_limit_mm:.0f} mm級まで探索に含め、さらに最終段でギャップ近傍スイープを行って危険な近接解を避けた。",
        r"\section{選定設計}",
        r"\begin{tabular}{p{0.34\linewidth}p{0.58\linewidth}}",
        rf"形状ラベル & {tex_escape(payload['shape_label'])} \\",
        rf"探索形状モード & {tex_escape(shape_family_mode)} \\",
        rf"選定形状ファミリ & {tex_escape(selected_shape_family)} \\",
        rf"空隙 $s$ & {1000.0 * selected_design['gap_m']:.2f} mm \\",
        rf"平均半径 & {1000.0 * selected_design['mean_radius_m']:.2f} mm \\",
        rf"選定 SKU & {tex_escape(selected_design['magnet_sku_id'])} \\",
        rf"販売元 & {tex_escape(selected_design['magnet_vendor'])} \\",
        rf"磁石寸法 & {1000.0 * selected_design['magnet_tangential_length_m']:.0f} $\times$ {1000.0 * selected_design['magnet_axial_height_m']:.0f} $\times$ {1000.0 * selected_design['magnet_radial_depth_m']:.0f} mm \\",
        rf"1周あたり磁石数 & {selected_design['magnets_per_ring']} \\",
        rf"1周あたり層数 & {selected_design['magnet_layers']} \\",
        rf"1ポケット縦積み高さ & {1000.0 * selected_design['nominal_overlap_m']:.2f} mm \\",
        rf"磁石総数 & {selected_design['total_magnets']} \\",
        rf"推定磁石費 & {selected_design['estimated_total_cost_jpy']:.0f} JPY \\",
        rf"有効磁束密度 & {selected_design['effective_flux_t']:.3f} T \\",
        rf"最大高さシフト & {1000.0 * selected_design['max_overlap_reduction_m']:.2f} mm \\",
        r"\end{tabular}",
        r"\vspace{2mm}",
        rf"\noindent SKU備考: {tex_escape(selected_sku.source_note or '追加備考なし。')}",
        r"\section{最適化の考え方}",
        r"\noindent 形状探索では、並進変位の向きに対して復元力の向きがどれだけ一致するか、復元力の大きさが変位量に対してどれだけ線形か、"
        r" 高さを下げても復元剛性が正のまま保たれるか、純並進時に余計なトルクをどれだけ出さないか、"
        r" そして接触・吸着・ラッチの兆候がないかを直接スコア化した。"
        r" 今回はさらに、局所コギングを純反力と誤認しないため、直交漏れ比と前進方向寄生トルク比の閾値超過に追加罰則を入れた。"
        r" その後、選ばれた形状についてのみ、高さ可変制御則を CEM ベースの方策探索で学習した。",
        r"\subsection{形状・設計探索の収束}",
        r"\begin{figure}[H]\centering",
        r"\includegraphics[width=0.92\linewidth]{design_convergence.png}",
        r"\caption{高忠実度形状探索の収束。}",
        r"\end{figure}",
        r"\subsection{高さ制御方策探索の収束}",
        r"\begin{figure}[H]\centering",
        r"\includegraphics[width=0.88\linewidth]{policy_convergence.png}",
        r"\caption{高さ可変方策探索の収束。}",
        r"\end{figure}",
        r"\section{静的結果}",
        r"\begin{figure}[H]\centering",
        r"\includegraphics[width=0.96\linewidth]{force_polar.png}",
        r"\caption{4 mm 並進時の方向別復元力。左はフルオーバーラップ、右は大きく高さを下げた状態。}",
        r"\end{figure}",
        r"\begin{figure}[H]\centering",
        r"\includegraphics[width=0.96\linewidth]{force_curves.png}",
        r"\caption{変位に対する復元力の線形性と、高さ低下に伴う力スケーリング。}",
        r"\end{figure}",
        r"\begin{tabular}{p{0.42\linewidth}p{0.22\linewidth}}",
        rf"フル高さ平均剛性 & {payload['static_assessment']['mean_full_height_stiffness_npm']:.2f} N/m \\",
        rf"低高さ最小剛性 & {payload['static_assessment']['min_reduced_height_stiffness_npm']:.2f} N/m \\",
        rf"平均直交漏れ比 & {payload['static_assessment']['mean_orthogonal_ratio']:.4f} \\",
        rf"方向剛性 CV & {payload['static_assessment']['direction_stiffness_cv']:.4f} \\",
        rf"変位線形性 $R^2$ & {payload['static_assessment']['displacement_linearity_r2']:.4f} \\",
        rf"高さ線形性 $R^2$ & {payload['static_assessment']['height_linearity_r2']:.4f} \\",
        rf"負の復元サンプル数 & {payload['static_assessment']['negative_restore_count']} \\",
        rf"負のヨー復元サンプル数 & {payload['static_assessment']['negative_yaw_restore_count']} \\",
        rf"接触サンプル数 & {payload['static_assessment']['contact_count']} \\",
        r"\end{tabular}",
        r"\section{動的検証結果}",
        r"\begin{longtable}{p{0.20\linewidth}p{0.08\linewidth}p{0.06\linewidth}p{0.07\linewidth}p{0.06\linewidth}p{0.10\linewidth}p{0.10\linewidth}p{0.10\linewidth}p{0.09\linewidth}p{0.07\linewidth}p{0.07\linewidth}}",
        r"\toprule",
        r"Scenario & Score & 接触 & 制約 & ラッチ & 最小Clear[mm] & 接触要求[mm] & RMS並進[mm] & RMS姿勢[deg] & 遅れ[s] & 復帰[s] \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"Scenario & Score & 接触 & 制約 & ラッチ & 最小Clear[mm] & 接触要求[mm] & RMS並進[mm] & RMS姿勢[deg] & 遅れ[s] & 復帰[s] \\",
        r"\midrule",
        r"\endhead",
    ]

    lines.extend(build_dynamic_table(dynamic_rows))
    lines.extend(
        [
            r"\bottomrule",
            r"\end{longtable}",
            r"\noindent ここで最小クリアランスは投影後の物理空隙であり、負値を取らない。"
            r" 一方、接触要求量は投影前にどれだけ重なろうとしたかを表す監査指標である。",
        ]
    )

    if best_rollout_exists:
        lines.extend(
            [
                r"\begin{figure}[H]\centering",
                r"\includegraphics[width=0.93\linewidth]{best_rollout.png}",
                r"\caption{代表的に良好だった動的シナリオの時系列。}",
                r"\end{figure}",
            ]
        )
    if worst_rollout_exists:
        lines.extend(
            [
                r"\begin{figure}[H]\centering",
                r"\includegraphics[width=0.93\linewidth]{worst_rollout.png}",
                r"\caption{最悪シナリオの時系列。最小ギャップと高さシフトの関係を確認できる。}",
                r"\end{figure}",
            ]
        )

    lines.extend(
        [
            r"\section{平面マップ}",
            r"\begin{figure}[H]\centering",
            r"\includegraphics[width=0.48\linewidth]{force_vector_map_yaw0.png}"
            r"\hfill"
            r"\includegraphics[width=0.48\linewidth]{minimum_gap_map_yaw0.png}",
            r"\caption{ヨー0度近傍の平面応答。左は復元力ベクトル、右は最小クリアランスマップ。}",
            r"\end{figure}",
            r"\begin{figure}[H]\centering",
            r"\includegraphics[width=0.48\linewidth]{bad_attraction_map_yaw20.png}"
            r"\hfill"
            r"\includegraphics[width=0.48\linewidth]{potential_energy_map_yaw20.png}",
            r"\caption{ヨー20度近傍の危険吸着マップとポテンシャルエネルギーマップ。}",
            r"\end{figure}",
            r"\section{最終磁場分布}",
            r"\begin{figure}[H]\centering",
            r"\includegraphics[width=0.98\linewidth]{selected_design_field_distribution.png}",
            r"\caption{最終選定案の有限個磁石配列磁場。上面図と $x$-$z$ 断面図。}",
            r"\end{figure}",
            r"\section{プログラム構成}",
            r"\noindent 今回の主要プログラムは \texttt{mpc\_solarcar/magnetic\_coupler\_hifi.py} である。"
            r" 下表は、実際のソースコードに含まれる主要クラス・関数とその役割を抜粋したものである。",
            r"\begin{longtable}{>{\raggedright\arraybackslash}p{0.08\linewidth}>{\raggedright\arraybackslash}p{0.14\linewidth}>{\raggedright\arraybackslash}p{0.22\linewidth}>{\raggedright\arraybackslash}p{0.48\linewidth}}",
            r"\toprule",
            r"行 & 種別 & 名前 & 役割 \\",
            r"\midrule",
            r"\endfirsthead",
            r"\toprule",
            r"行 & 種別 & 名前 & 役割 \\",
            r"\midrule",
            r"\endhead",
        ]
    )

    for lineno, kind, name, doc in symbol_rows:
        lines.append(f"{lineno} & {tex_escape(kind)} & {tex_escape(name)} & {tex_escape(doc)} \\\\")

    lines.extend(
        [
            r"\bottomrule",
            r"\end{longtable}",
            r"\section{考察}",
            r"\noindent 今回の探索では、全方向での純粋な反発復元と高さ変化に対する力の単調スケーリングを直接評価したため、"
            r" 旧来の少数形状候補よりも、連続パラメータで形状を調整した設計の方が望ましい候補を見つけやすくなった。"
            r" 一方で、本モデルは依然として一様磁化・剛体・空気中自由空間・渦電流無視の近似であり、"
            r" ヨーク材、飽和、製造公差、温度変化、実装偏芯までは含めていない。"
            r" したがって、この結果は「実装候補のふるい込み」としては強いが、"
            r" 量産前には 3D FEA または実機計測で最終確認するべきである。",
            r"\section{参考URL}",
            rf"\noindent 選定 SKU 公式ページ: \url{{{selected_sku.source_url}}}\\",
            r"\noindent Slanovc et al., Full analytical solution for the magnetic field of uniformly magnetized cylinder tiles: \url{https://arxiv.org/abs/2112.01376}\\",
            *extra_reference_lines,
            r"\clearpage",
            r"\section{付録A: ソースコード全体}",
            r"\lstinputlisting{" + tex_escape(listing_rel) + r"}",
            r"\end{document}",
        ]
    )

    tex_path.write_text("\n".join(lines), encoding="utf-8")
    return tex_path


def parse_args():
    parser = argparse.ArgumentParser(description="Generate a Japanese PDF report for magnetic_coupler_hifi outputs.")
    parser.add_argument(
        "--outdir",
        type=Path,
        default=ROOT / "outputs" / "magnetic_coupler_hifi",
    )
    return parser.parse_args()


def compile_pdf(tex_path):
    command = [
        "lualatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]
    subprocess.run(command, cwd=tex_path.parent, check=True)
    subprocess.run(command, cwd=tex_path.parent, check=True)
    return tex_path.with_suffix(".pdf")


def main():
    args = parse_args()
    tex_path = write_report(args.outdir)
    pdf_path = compile_pdf(tex_path)
    print(
        json.dumps(
            {
                "tex_report": str(tex_path),
                "pdf_report": str(pdf_path),
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
