import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\Users\user\OneDrive - 和歌山大学\ソーラー\エネマネ\solar_ws0129-main")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


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


def load_payload(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def metric(value, fmt):
    return "N/A" if value is None else format(value, fmt)


def build_comparison_rows(old_payload, new_payload):
    old_design = old_payload["selected_design"]
    new_design = new_payload["selected_design"]
    old_static = old_payload["static_assessment"]
    new_static = new_payload["static_assessment"]
    old_dynamic = old_payload["dynamic_validation"]
    new_dynamic = new_payload["dynamic_validation"]
    return [
        ("Gap s [mm]", 1000.0 * old_design["gap_m"], 1000.0 * new_design["gap_m"], ".2f"),
        ("Mean radius [mm]", 1000.0 * old_design["mean_radius_m"], 1000.0 * new_design["mean_radius_m"], ".2f"),
        ("Magnets per ring", old_design["magnets_per_ring"], new_design["magnets_per_ring"], ".0f"),
        ("Layers per ring", old_design["magnet_layers"], new_design["magnet_layers"], ".0f"),
        ("Total magnets", old_design["total_magnets"], new_design["total_magnets"], ".0f"),
        ("Estimated cost [JPY]", old_design["estimated_total_cost_jpy"], new_design["estimated_total_cost_jpy"], ".0f"),
        ("Effective flux [T]", old_design["effective_flux_t"], new_design["effective_flux_t"], ".3f"),
        ("Full-height stiffness [N/m]", old_static["mean_full_height_stiffness_npm"], new_static["mean_full_height_stiffness_npm"], ".2f"),
        ("Min reduced stiffness [N/m]", old_static["min_reduced_height_stiffness_npm"], new_static["min_reduced_height_stiffness_npm"], ".2f"),
        ("Directional stiffness CV", old_static["direction_stiffness_cv"], new_static["direction_stiffness_cv"], ".4f"),
        ("Negative yaw restore count", old_static["negative_yaw_restore_count"], new_static["negative_yaw_restore_count"], ".0f"),
        ("Dynamic mean score", old_dynamic["mean_score"], new_dynamic["mean_score"], ".2f"),
        ("Dynamic contact events", old_dynamic["contact_events_total"], new_dynamic["contact_events_total"], ".0f"),
        (
            "Dynamic constraint activations",
            old_dynamic.get("constraint_activations_total"),
            new_dynamic.get("constraint_activations_total"),
            ".0f",
        ),
        ("Dynamic latched count", old_dynamic["latched_total"], new_dynamic["latched_total"], ".0f"),
        (
            "Worst minimum clearance [mm]",
            old_dynamic.get("worst_min_clearance_mm", old_dynamic["worst_min_gap_mm"]),
            new_dynamic.get("worst_min_clearance_mm", new_dynamic["worst_min_gap_mm"]),
            ".3f",
        ),
        (
            "Maximum contact demand [mm]",
            old_dynamic.get("max_contact_demand_mm", old_dynamic["worst_penetration_mm"]),
            new_dynamic.get("max_contact_demand_mm", new_dynamic["worst_penetration_mm"]),
            ".3f",
        ),
    ]


def write_report(old_payload, new_payload, outdir: Path, attached_pdf: Path | None):
    rows = build_comparison_rows(old_payload, new_payload)
    attached_note = (
        rf"\noindent 監査参照PDF: \texttt{{{tex_escape(attached_pdf)}}}\\"
        if attached_pdf
        else r"\noindent 監査参照PDF: なし\\"
    )
    model_revision = new_payload.get("model_revision", {})
    tex_path = outdir / "magnetic_coupler_hifi_revision_report_ja.tex"
    lines = [
        r"\documentclass[a4paper,11pt]{ltjsarticle}",
        r"\usepackage[margin=18mm]{geometry}",
        r"\usepackage{booktabs}",
        r"\usepackage{longtable}",
        r"\usepackage{array}",
        r"\usepackage{hyperref}",
        r"\usepackage{luatexja-fontspec}",
        r"\setmainjfont{Yu Mincho}",
        r"\setsansjfont{Yu Gothic}",
        r"\setmonofont{Consolas}",
        r"\hypersetup{unicode=true,colorlinks=true,linkcolor=blue,urlcolor=blue}",
        r"\begin{document}",
        r"\begin{center}",
        r"{\LARGE DAISO 13 mm 磁気カプラ修正比較報告}\\[3mm]",
        r"{\large 旧モデルからの修正根拠と再解析結果}",
        r"\end{center}",
        r"\section{目的}",
        r"\noindent 添付説明PDFを監査入力として用い、旧DAISO解析で誤っていた点と、"
        r" 実環境再現性を上げるために不足していた点を洗い出し、"
        r" 高忠実度モデル・最適化・最終出力物をすべて再生成した。"
        r" 本PDFは「何を直したか」と「その結果どう変わったか」を比較で示す。",
        attached_note,
        r"\section{主修正}",
        r"\noindent 1. 外側形状生成を原点スケーリングから法線オフセットへ変更した。"
        r" 旧法は非円形で法線ギャップが一定にならず、同心・等間隙リングの前提を壊していた。"
        r" 新法は内側境界から法線方向に平行移動して外側境界を構成し、SATギャップ評価とCAD形状を一致させた。",
        r"\noindent 2. DAISO 13 mm 円盤磁石の 240 mT を、そのまま磁化強度として使うのをやめた。"
        r" 240 mT は表面磁束密度であり、双極子モーメントに直接入れると大幅過小評価になる。"
        r" 一様磁化円柱の軸上表面磁束式から等価 remanence を逆算し、体積双極子モーメントへ反映した。",
        r"\noindent 3. DAISO円盤の軸方向スタック数に実装上限を入れた。"
        r" 旧探索空間は13 mm磁石を多数段積みでき、実装厚みとして不自然だった。"
        r" 新探索では約39 mm級までに制限し、現実の下面搭載厚みに寄せた。",
        r"\noindent 4. 動的接触計算をサブステップ化し、接触後に位置投影と法線速度補正を入れた。"
        r" 旧モデルは粗い1ステップ積分で深い貫入が出やすかった。"
        r" 新モデルは摺り抜けを抑え、接触した時点で非貫入側へ押し戻す。",
        r"\noindent 5. 物理クリアランスの定義を修正した。"
        r" 新モデルでは接触後の空隙は 0 mm 未満を取らず、投影前に要求された重なり量だけを別の監査量として残す。",
        r"\noindent 6. DAISOのような低価格磁石に対して、磁力ばらつき・減衰ばらつき・組付け偏心を含むロバスト検証を追加した。"
        r" これにより nominal 条件だけでは見えないラッチ傾向を評価できるようにした。",
        r"\noindent 7. 形状・配列決定後に、ギャップのみを近傍スイープして動的に危険な近接点を避ける再調整段を追加した。",
        r"\section{比較表}",
        r"\begin{longtable}{>{\raggedright\arraybackslash}p{0.44\linewidth}p{0.22\linewidth}p{0.22\linewidth}}",
        r"\toprule",
        r"指標 & 旧DAISO解析 & 修正版DAISO解析 \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"指標 & 旧DAISO解析 & 修正版DAISO解析 \\",
        r"\midrule",
        r"\endhead",
    ]
    for label, old_value, new_value, fmt in rows:
        lines.append(
            f"{tex_escape(label)} & {metric(old_value, fmt)} & {metric(new_value, fmt)} \\\\"
        )
    lines.extend(
        [
            r"\bottomrule",
            r"\end{longtable}",
            r"\section{今回選ばれた設計の読み方}",
            rf"\noindent 形状ラベル: \texttt{{{tex_escape(new_payload['shape_label'])}}}\\",
            rf"\noindent 修正版 gap: {1000.0 * new_payload['selected_design']['gap_m']:.2f} mm\\",
            rf"\noindent 修正版総磁石数: {new_payload['selected_design']['total_magnets']}\\",
            rf"\noindent 修正版有効磁束密度: {new_payload['selected_design']['effective_flux_t']:.3f} T\\",
            rf"\noindent 修正版モデル改訂要点: {tex_escape('; '.join(str(v) for v in model_revision.values()))}",
            r"\section{解釈}",
            r"\noindent 今回の修正版では、磁化強度の見直しと実装厚み制約の導入により、"
            r" 旧モデルで選ばれた過大スタック・過小空隙の楽観解は排除された。"
            r" さらに、負のギャップを物理状態として扱う誤りを除去したため、"
            r" クリアランス指標と接触監査指標の意味が分離され、設計比較が明確になった。"
            r" 一方で、DAISO 13 mm 制約は磁石単体の寸法・配列自由度が小さいため、"
            r" 厳しい旋回・横入力条件では依然として接触・ラッチ余地が残る。"
            r" したがって、この結果は「DAISO制約下の現実寄り最良候補」であり、"
            r" 実機ゼロ接触を絶対条件とする場合は、より高性能な磁石SKUまたはさらに広いギャップ設計が必要である。",
            r"\section{根拠URL}",
            r"\noindent DAISO 公式商品ページ: \url{https://jp.daisonet.com/products/4549131230475}\\",
            r"\noindent 一様磁化円柱の軸上磁束式の参考: \url{https://web.mit.edu/6.013_book/www/chapter9/9.3.html}\\",
            r"\noindent 円柱タイル磁石の解析解参考: \url{https://arxiv.org/abs/2112.01376}\\",
            r"\end{document}",
        ]
    )
    tex_path.write_text("\n".join(lines), encoding="utf-8")
    return tex_path


def compile_pdf(tex_path: Path):
    command = [
        "lualatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        tex_path.name,
    ]
    subprocess.run(command, cwd=tex_path.parent, check=True)
    subprocess.run(command, cwd=tex_path.parent, check=True)
    return tex_path.with_suffix(".pdf")


def parse_args():
    parser = argparse.ArgumentParser(description="Generate a revision-comparison PDF for the DAISO high-fidelity rerun.")
    parser.add_argument("--old-json", type=Path, required=True)
    parser.add_argument("--new-json", type=Path, required=True)
    parser.add_argument("--outdir", type=Path, required=True)
    parser.add_argument("--attached-pdf", type=Path, default=None)
    return parser.parse_args()


def main():
    args = parse_args()
    old_payload = load_payload(args.old_json)
    new_payload = load_payload(args.new_json)
    tex_path = write_report(old_payload, new_payload, args.outdir, args.attached_pdf)
    pdf_path = compile_pdf(tex_path)
    print(json.dumps({"tex_report": str(tex_path), "pdf_report": str(pdf_path)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
