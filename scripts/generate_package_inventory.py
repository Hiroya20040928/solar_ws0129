from __future__ import annotations
#!/usr/bin/env python3
"""Generate auditable source and workspace inventories for the ROS 2 package."""


import argparse
import ast
import csv
import hashlib
import os
import re
from pathlib import Path
from typing import Iterable


SOURCE_ROOTS = (
    "mpc_solarcar",
    "launch",
    "scripts",
    "config",
    "templates",
    "dashboard",
)
TOP_LEVEL = ("SolarSim.ps1", "setup.py", "package.xml")
SKIP_PARTS = {
    ".git",
    ".run",
    ".pytest_cache",
    "__pycache__",
    "build",
    "install",
    "log",
    "node_modules",
}
TEXT_SUFFIXES = {
    ".py",
    ".ps1",
    ".xml",
    ".yaml",
    ".yml",
    ".json",
    ".csv",
    ".md",
    ".tex",
    ".html",
    ".css",
    ".js",
    ".txt",
}
TOPIC_RE = re.compile(
    r"(?:create_(?:publisher|subscription)|Publisher|Subscriber)\s*\([^,]+,\s*"
    r"['\"]([^'\"]+)['\"]"
)


def sha256(path: Path) -> str:                                     # [関数定義] sha256 の処理実行ブロック
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def skipped(path: Path) -> bool:                                   # [関数定義] skipped の処理実行ブロック
    return any(part in SKIP_PARTS for part in path.parts)          # [戻り値] 計算結果・計算状態の呼び出し元への返却


def iter_source_files(root: Path) -> Iterable[Path]:               # [関数定義] iter_source_files の処理実行ブロック
    for name in TOP_LEVEL:
        path = root / name
        if path.is_file():
            yield path
    for dirname in SOURCE_ROOTS:
        base = root / dirname
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file() and not skipped(path.relative_to(root)):
                yield path


def iter_workspace_files(root: Path) -> Iterable[Path]:            # [関数定義] iter_workspace_files の処理実行ブロック
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in SKIP_PARTS and not (Path(current) / name).is_symlink()
        )
        for name in sorted(files):
            path = Path(current) / name
            rel = path.relative_to(root)
            if skipped(rel) or path.is_symlink():
                continue
            try:
                if path.is_file():
                    yield path
            except OSError:
                continue


def first_text_line(text: str) -> str:                             # [関数定義] first_text_line の処理実行ブロック
    for line in text.splitlines():
        value = line.strip().lstrip("#").strip()
        if value:
            return value[:240]                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return ""                                                      # [戻り値] 計算結果・計算状態の呼び出し元への返却


def infer_role(rel: str) -> str:                                   # [関数定義] infer_role の処理実行ブロック
    name = Path(rel).name
    if rel.startswith("launch/"):
        return "ROS 2 launch entry"                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if rel.startswith("mpc_solarcar/"):
        if name.endswith("_node.py"):
            return "ROS 2 runtime node"                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return "runtime library/model"                             # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if rel.startswith("scripts/"):
        if "identification" in name or name.startswith("fit_"):
            return "vehicle identification tool"                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if "report" in name or "workbook" in name or "inventory" in name:
            return "documentation/report generator"                # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if "package" in name:
            return "package builder"                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if "tune" in name or "learn" in name:
            return "offline self-learning tool"                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
        if "sim" in name:
            return "offline simulation tool"                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        return "operations/support script"                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if rel.startswith("config/") or rel.startswith("templates/"):
        return "configuration/template"                            # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if rel.startswith("dashboard/"):
        return "dashboard asset"                                   # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if name == "SolarSim.ps1":
        return "PowerShell all-in-one entry"                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if name in {"setup.py", "package.xml"}:
        return "ROS 2 packaging metadata"                          # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return "package asset"                                         # [戻り値] 計算結果・計算状態の呼び出し元への返却


def inspect_python(text: str) -> tuple[str, str, str, str]:        # [関数定義] inspect_python の処理実行ブロック
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return "", "", "", f"syntax error: {exc.msg} at {exc.lineno}"  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    doc = ast.get_docstring(tree) or ""
    classes = [node.name for node in tree.body if isinstance(node, ast.ClassDef)]
    functions = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
    return (                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        doc.splitlines()[0][:240] if doc else "",
        ", ".join(classes),
        ", ".join(functions),
        ", ".join(sorted(set(filter(None, imports)))),
    )


def source_row(root: Path, path: Path) -> dict[str, object]:       # [関数定義] source_row の処理実行ブロック
    rel = path.relative_to(root).as_posix()
    data = path.read_bytes()
    text = ""
    if path.suffix.lower() in TEXT_SUFFIXES:
        text = data.decode("utf-8-sig", errors="replace")
    doc = first_text_line(text)
    classes = functions = imports = ""
    if path.suffix.lower() == ".py":
        doc, classes, functions, imports = inspect_python(text)
    topics = ", ".join(sorted(set(TOPIC_RE.findall(text))))
    return {                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
        "path": rel,
        "role": infer_role(rel),
        "summary": doc,
        "classes": classes,
        "functions": functions,
        "imports": imports,
        "ros_topics": topics,
        "lines": text.count("\n") + (1 if text else 0),
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:  # [関数定義] write_csv の処理実行ブロック
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0].keys()) if rows else ["path"]
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, object]]) -> None:  # [関数定義] write_markdown の処理実行ブロック
    by_role: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        by_role.setdefault(str(row["role"]), []).append(row)
    lines = [
        "# ROS 2 package source inventory",
        "",
        "This file is generated by scripts/generate_package_inventory.py.",
        "The CSV beside it is the authoritative machine-readable record.",
        "",
        f"- Source/config assets scanned: {len(rows)}",
        f"- Total source lines: {sum(int(r['lines']) for r in rows):,}",
        f"- Total bytes: {sum(int(r['bytes']) for r in rows):,}",
        "",
    ]
    for role in sorted(by_role):
        lines.extend((f"## {role}", "", "| Path | Lines | Main symbols | ROS topics |", "|---|---:|---|---|"))
        for row in by_role[role]:
            symbols = ", ".join(filter(None, (str(row["classes"]), str(row["functions"])))) or "-"
            topics = str(row["ros_topics"]) or "-"
            lines.append(f"| {row['path']} | {row['lines']} | {symbols} | {topics} |")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:                                                 # [関数定義] main の処理実行ブロック
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])  # [CLI引数] コマンドライン実行引数の定義
    parser.add_argument(                                           # [CLI引数] コマンドライン実行引数の定義
        "--output-dir",
        type=Path,
        default=Path("docs/package_inventory"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    out = args.output_dir
    if not out.is_absolute():
        out = root / out
    rows = [source_row(root, path) for path in iter_source_files(root)]
    write_csv(out / "package_source_inventory.csv", rows)
    write_markdown(out / "package_source_inventory.md", rows)

    manifest = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "modified_utc_ns": path.stat().st_mtime_ns,
        }
        for path in iter_workspace_files(root)
    ]
    write_csv(out / "workspace_file_manifest.csv", manifest)
    print(f"source assets: {len(rows)}")
    print(f"workspace files: {len(manifest)}")
    print(out)
    return 0                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


if __name__ == "__main__":
    raise SystemExit(main())