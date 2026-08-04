# ソーラーカー主要プログラム完全解説

このディレクトリは、2026年7月29日時点の作業ツリーを対象に、以前選定した主要40プログラムを日本語で個別解説した資料群である。

## 最初に読むファイル

1. `pdf/program_reference_index.pdf`
2. `pdf/00_foundations.pdf`
3. `pdf/01_SolarSim_ps1.pdf`から番号順

`00_foundations.pdf`は、プログラム、プロセス、メモリ、関数、クラス、インスタンス、`self`、継承、デコレータ、`@dataclass`、module、package、`console_scripts`、ROS 2、Executor、rcl/rmw/DDS、MPC、CEM、warm start、車体・電池モデルを初学者向けに説明する。

## ディレクトリ

- `pdf/`: 配布・閲覧用PDF。基礎総論1冊、個別解説40冊、索引1冊。
- `markdown/`: 検索・差分確認用の同内容Markdown。
- `tex/`: PDFの生成元TeX。
- `build/`: XeLaTeX中間生成物と文書別コンパイルログ。
- `program_reference_manifest.json`: 対象ソース、SHA-256、行数、定義数、ROS I/O数、生成物パス。

## 個別解説の構成

各冊は、対象ソースのSHA-256を記録し、次を扱う。

1. このファイルの役割と起動文脈
2. 呼出し元、次に読むファイル、同一リポジトリ内依存
3. import文ごとの目的、実体ファイル、実際の使用行
4. ファイルを上から読んだ定義順
5. そのファイルに必要なPython、OS、ROS 2、数値計算の基礎
6. クラス内メソッドと関数内関数を含む全定義
7. 引数、戻り値、ローカル変数、`self`属性の読書き、例外、分岐、ループ
8. 上から順の処理手順と代表コード断片
9. ROS publisher、subscription、timer、parameter、launch Node、CLI引数
10. システム全体における位置づけ

`mpc_node.py`には、launchから`console_scripts`、OSプロセス、`main()`、`spin()`、callbackへ至る起動経路と、時間上位MPC、距離上位MPC、CEM、warm start、下位MPC、MHE、freshness、fallbackを接続した専用章を追加している。

## 再生成

リポジトリルートで次を実行する。

```powershell
python scripts\generate_program_reference_docs.py
```

PDFを作らずMarkdown、TeX、manifestだけ更新する場合は次を使う。

```powershell
python scripts\generate_program_reference_docs.py --skip-pdf
```

## 根拠と限界

ソース構造、行番号、呼出し、属性読書き、ROS I/O、CLI引数は対象ファイルを構文解析して生成している。Python、setuptools、ROS 2、SciPyの一般仕様は各章から公式資料へリンクしている。

この資料は作業ツリーのスナップショット解説であり、制御系の安全性や実車投入可否を保証する証明書ではない。特に`mpc_solarcar/mpc_node.py`は生成時点でGit index上の未解決状態を保持しているため、本資料はindexのどちらかの版ではなく、実際に読み取れる作業ツリー内容と記録SHA-256を基準とする。
