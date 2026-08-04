#!/usr/bin/env python3
"""Create a verified ZIP containing only the current execution dependencies."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from audit_execution_dependency_manifest import audit as audit_dependency_manifest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT
    / "docs"
    / "execution_dependencies_complete"
    / "execution_dependency_manifest.csv"
)
DEFAULT_OUTPUT_ROOT = ROOT / "exports"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reserve_bundle_path(output_root: Path, base_name: str) -> Path:
    candidate = output_root / base_name
    version = 2
    while candidate.exists() or candidate.with_suffix(".zip").exists():
        candidate = output_root / f"{base_name}_v{version}"
        version += 1
    return candidate


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"dependency manifest is empty: {path}")
    required = {"path", "size_bytes", "sha256"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"dependency manifest lacks columns {sorted(missing)}: {path}")
    return rows


def copy_verified_payload(rows: list[dict[str, str]], bundle_dir: Path) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    for row in rows:
        rel = Path(row["path"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"unsafe manifest path: {rel}")
        source = (ROOT / rel).resolve()
        try:
            source.relative_to(ROOT)
        except ValueError as exc:
            raise ValueError(f"manifest path leaves repository: {rel}") from exc
        if not source.is_file():
            raise FileNotFoundError(source)
        expected_size = int(row["size_bytes"])
        expected_hash = row["sha256"].lower()
        actual_size = source.stat().st_size
        actual_hash = sha256(source)
        if actual_size != expected_size or actual_hash != expected_hash:
            raise RuntimeError(
                f"manifest mismatch: {rel} "
                f"size={actual_size}/{expected_size} sha256={actual_hash}/{expected_hash}"
            )
        destination = bundle_dir / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied_hash = sha256(destination)
        if copied_hash != expected_hash:
            raise RuntimeError(f"copy verification failed: {rel}")
        copied.append(
            {
                "path": rel.as_posix(),
                "size_bytes": actual_size,
                "sha256": actual_hash,
            }
        )
    return copied


def add_management_files(bundle_dir: Path, manifest_path: Path) -> list[str]:
    candidates = [
        manifest_path,
        manifest_path.with_suffix(".md"),
        ROOT / "scripts" / "generate_execution_dependency_manifest.py",
        Path(__file__).resolve(),
    ]
    added: list[str] = []
    for source in candidates:
        if not source.is_file():
            raise FileNotFoundError(source)
        rel = source.relative_to(ROOT)
        destination = bundle_dir / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        added.append(rel.as_posix())
    return added


def write_bundle_metadata(
    bundle_dir: Path,
    copied: list[dict[str, object]],
    management_files: list[str],
    dependency_audit: dict[str, object],
) -> list[str]:
    created_utc = datetime.now(timezone.utc).isoformat()
    verification = {
        "schema": 1,
        "created_utc": created_utc,
        "repository_root_at_packaging": str(ROOT),
        "dependency_file_count": len(copied),
        "dependency_total_bytes": sum(int(item["size_bytes"]) for item in copied),
        "management_files": management_files,
        "payload": copied,
        "exclusions": [
            "past simulation outputs",
            "logs",
            "old MLE packages and runs",
            "checkpoints and TensorBoard data",
            "build/install/.run/cache artifacts",
            "PASSO sources",
            "magnetic-coupler sources",
        ],
    }
    verification_path = bundle_dir / "EXECUTION_BUNDLE_VERIFICATION.json"
    verification_path.write_text(
        json.dumps(verification, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    audit_path = bundle_dir / "EXECUTION_DEPENDENCY_AUDIT.json"
    audit_path.write_text(
        json.dumps(dependency_audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    readme_path = bundle_dir / "BUNDLE_CONTENTS.md"
    readme_path.write_text(
        "\n".join(
            [
                "# Solar-car execution dependency bundle",
                "",
                f"- Dependency payload: {len(copied)} files",
                f"- Dependency bytes: {verification['dependency_total_bytes']}",
                "- Every payload file was checked against the SHA-256 manifest before and after copying.",
                "- Past outputs, logs, caches, PASSO, and magnetic-coupler files are not included.",
                "- The adopted maps and selected MLE35 profile under outputs are included because current profiles consume them as inputs.",
                "",
                "See `docs/execution_dependencies/execution_dependency_manifest.md` for the categorized list and",
                "`EXECUTION_BUNDLE_VERIFICATION.json` for the machine-readable verification record.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return [verification_path.name, audit_path.name, readme_path.name]


def create_zip(bundle_dir: Path, archive_root: str) -> Path:
    zip_path = bundle_dir.with_suffix(".zip")
    with zipfile.ZipFile(
        zip_path,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
        allowZip64=True,
    ) as archive:
        for path in sorted(bundle_dir.rglob("*")):
            if path.is_file():
                archive.write(path, (Path(archive_root) / path.relative_to(bundle_dir)).as_posix())
    return zip_path


def verify_zip(zip_path: Path, expected_root: str, expected_files: int) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"ZIP CRC verification failed: {bad}")
        files = [item for item in archive.infolist() if not item.is_dir()]
        if len(files) != expected_files:
            raise RuntimeError(f"ZIP file count mismatch: {len(files)} != {expected_files}")
        if any(not item.filename.startswith(expected_root + "/") for item in files):
            raise RuntimeError("ZIP contains an entry outside its bundle root")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--name", default=f"solarcar_execution_dependencies_{datetime.now():%Y%m%d}")
    parser.add_argument(
        "--archive-root",
        default="M",
        help="Short ZIP-internal root used to avoid Windows Explorer MAX_PATH failures.",
    )
    args = parser.parse_args()

    manifest_path = args.manifest.resolve() if args.manifest.is_absolute() else (ROOT / args.manifest).resolve()
    output_root = args.output_root.resolve() if args.output_root.is_absolute() else (ROOT / args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    archive_root = str(args.archive_root).strip().strip("/\\")
    if not archive_root or "/" in archive_root or "\\" in archive_root or archive_root in {".", ".."}:
        raise ValueError(f"archive root must be one short path component: {args.archive_root!r}")
    bundle_dir = reserve_bundle_path(output_root, args.name)
    bundle_dir.mkdir(parents=True, exist_ok=False)

    rows = read_manifest(manifest_path)
    dependency_audit = audit_dependency_manifest(manifest_path)
    if not dependency_audit["passed"]:
        raise RuntimeError(
            "dependency audit failed: "
            + "; ".join(str(item) for item in dependency_audit["errors"])
        )
    copied = copy_verified_payload(rows, bundle_dir)
    management = add_management_files(bundle_dir, manifest_path)
    generated = write_bundle_metadata(bundle_dir, copied, management, dependency_audit)
    zip_path = create_zip(bundle_dir, archive_root)
    expected_files = len(copied) + len(set(management) - {item["path"] for item in copied}) + len(generated)
    verify_zip(zip_path, archive_root, expected_files)
    zip_hash = sha256(zip_path)
    sha_path = zip_path.with_suffix(".zip.sha256")
    sha_path.write_text(f"{zip_hash}  {zip_path.name}\n", encoding="ascii")

    print(f"bundle_dir={bundle_dir}")
    print(f"zip={zip_path}")
    print(f"dependency_files={len(copied)} zip_files={expected_files}")
    print(f"zip_bytes={zip_path.stat().st_size}")
    print(f"zip_sha256={zip_hash}")
    max_entry_chars = max(
        len((Path(archive_root) / path.relative_to(bundle_dir)).as_posix())
        for path in bundle_dir.rglob("*")
        if path.is_file()
    )
    print(f"archive_root={archive_root} max_entry_chars={max_entry_chars}")
    print(f"sha256_file={sha_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
