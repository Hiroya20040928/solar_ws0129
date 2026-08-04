#!/usr/bin/env python3
"""Independently audit the execution dependency manifest before packaging."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

import yaml

import generate_execution_dependency_manifest as dependency_manifest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT
    / "docs"
    / "execution_dependencies_complete"
    / "execution_dependency_manifest.csv"
)
ACTIVE_NODE_MODULES = {
    "mpc_solarcar/dashboard_node.py",
    "mpc_solarcar/distance_node.py",
    "mpc_solarcar/gps_sim_node.py",
    "mpc_solarcar/grade_node.py",
    "mpc_solarcar/mpc_node.py",
    "mpc_solarcar/solar_autocal_node.py",
    "mpc_solarcar/solar_logger_node.py",
    "mpc_solarcar/solar_preflight_node.py",
    "mpc_solarcar/solar_state_node.py",
    "mpc_solarcar/speed_command_bridge_node.py",
    "mpc_solarcar/telemetry_text_bridge_node.py",
    "mpc_solarcar/weather_fetch_node.py",
    "mpc_solarcar/wind_correction_node.py",
}
DESTINATION_KEYS = {
    "corrected_forecast_csv",
    "latest_manifest_json",
    "log_dir",
    "output_dir",
    "raw_forecast_csv",
}
SCRIPT_REFERENCE_RE = re.compile(
    r"(?:scripts|launch)[/\\][A-Za-z0-9_.-]+\.(?:py|sh|sbatch)"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def profile_source_paths(profile_path: Path) -> set[Path]:
    doc = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    raw_paths = doc.get("paths") or {}
    selected: list[tuple[str, str]] = []
    if isinstance(raw_paths, dict):
        selected.extend((str(key), str(value)) for key, value in raw_paths.items() if value)
    identification = doc.get("identification") or {}
    if isinstance(identification, dict):
        for key in ("fit_summary_yaml", "terminal_consistency_yaml"):
            if identification.get(key):
                selected.append((key, str(identification[key])))
    out: set[Path] = set()
    for key, raw in selected:
        if key in DESTINATION_KEYS:
            continue
        path = dependency_manifest.resolve_declared_path(profile_path.parent, raw)
        if path.is_file():
            out.add(path.resolve())
    return out


def audit(manifest_path: Path) -> dict[str, object]:
    rows = load_rows(manifest_path)
    errors: list[str] = []
    rel_paths = [row.get("path", "") for row in rows]
    if len(rel_paths) != len(set(rel_paths)):
        errors.append("duplicate manifest paths")
    listed = {(ROOT / rel).resolve() for rel in rel_paths}

    hash_checked = 0
    for row in rows:
        rel = row["path"]
        path = (ROOT / rel).resolve()
        if not path.is_file():
            errors.append(f"missing file: {rel}")
            continue
        if path.stat().st_size != int(row["size_bytes"]):
            errors.append(f"size mismatch: {rel}")
        elif sha256(path) != row["sha256"].lower():
            errors.append(f"SHA-256 mismatch: {rel}")
        else:
            hash_checked += 1

    import_edges = 0
    for path in sorted(listed):
        if path.suffix.lower() != ".py":
            continue
        for dependency in dependency_manifest.local_imports(path):
            import_edges += 1
            if dependency not in listed:
                errors.append(
                    "unlisted local import: "
                    f"{dependency_manifest.Manifest.relative(path)} -> "
                    f"{dependency_manifest.Manifest.relative(dependency)}"
                )

    missing_nodes = sorted(
        rel for rel in ACTIVE_NODE_MODULES if (ROOT / rel).resolve() not in listed
    )
    errors.extend(f"unlisted active ROS node: {rel}" for rel in missing_nodes)

    profile_refs = 0
    for row in rows:
        if "workflow profile" not in row.get("role", ""):
            continue
        profile = (ROOT / row["path"]).resolve()
        for source in profile_source_paths(profile):
            profile_refs += 1
            if source not in listed:
                errors.append(
                    "unlisted profile source: "
                    f"{dependency_manifest.Manifest.relative(profile)} -> "
                    f"{dependency_manifest.Manifest.relative(source)}"
                )

    script_refs = 0
    for path in sorted(listed):
        if path.suffix.lower() not in {".ps1", ".sh", ".sbatch"}:
            continue
        text = path.read_text(encoding="utf-8-sig")
        for raw in SCRIPT_REFERENCE_RE.findall(text):
            candidate = (ROOT / raw.replace("\\", "/")).resolve()
            if not candidate.is_file():
                continue
            script_refs += 1
            if candidate not in listed:
                errors.append(
                    "unlisted shell child: "
                    f"{dependency_manifest.Manifest.relative(path)} -> "
                    f"{dependency_manifest.Manifest.relative(candidate)}"
                )

    forbidden = [
        rel
        for rel in rel_paths
        if "magnetic" in rel.lower()
        or "passo" in rel.lower()
        or Path(rel).suffix.lower() in dependency_manifest.IGNORED_SUFFIXES
    ]
    errors.extend(f"forbidden scope/artifact: {rel}" for rel in forbidden)

    return {
        "passed": not errors,
        "manifest": str(manifest_path),
        "files": len(rows),
        "hash_checked": hash_checked,
        "local_import_edges_checked": import_edges,
        "active_ros_nodes_checked": len(ACTIVE_NODE_MODULES),
        "profile_source_edges_checked": profile_refs,
        "shell_child_edges_checked": script_refs,
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args()
    manifest_path = args.manifest.resolve() if args.manifest.is_absolute() else (ROOT / args.manifest).resolve()
    result = audit(manifest_path)
    payload = json.dumps(result, ensure_ascii=False, indent=2)
    print(payload)
    if args.output_json:
        output = args.output_json.resolve() if args.output_json.is_absolute() else (ROOT / args.output_json).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
