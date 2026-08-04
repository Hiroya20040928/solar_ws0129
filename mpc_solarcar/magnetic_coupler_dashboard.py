import argparse
import csv
import json
import mimetypes
import threading
import time
import webbrowser
from collections import deque
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

try:
    from ament_index_python.packages import get_package_share_directory
except Exception:
    get_package_share_directory = None


ARTIFACT_MEDIA_NAMES = [
    "live_shape_and_magnets.png",
    "live_field_distribution.png",
    "live_corridor_generation_latest.mp4",
    "live_corridor_generation_latest_poster.png",
    "design_convergence.png",
    "policy_convergence.png",
    "force_polar.png",
    "force_curves.png",
    "selected_design_field_distribution.png",
    "selected_dynamic_nominal.mp4",
    "best_rollout.png",
    "worst_rollout.png",
    "force_vector_map_yaw0.png",
    "force_vector_map_yaw20.png",
    "minimum_gap_map_yaw0.png",
    "minimum_gap_map_yaw20.png",
    "bad_attraction_map_yaw0.png",
    "bad_attraction_map_yaw20.png",
    "potential_energy_map_yaw0.png",
    "potential_energy_map_yaw20.png",
]

RUN_MARKERS = (
    "live_monitor_state.json",
    "best_design_hifi.json",
    "design_history.csv",
    "live_design_history.csv",
    "dynamic_validation.csv",
)
VIDEO_SUFFIXES = {".mp4", ".webm"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def resolve_static_dir(explicit_dir: str | None = None) -> Path:
    """Finds the packaged or local static dashboard directory."""

    if explicit_dir:
        return Path(explicit_dir).resolve()
    if get_package_share_directory is not None:
        try:
            return Path(get_package_share_directory("mpc_solarcar")) / "dashboard_magnetic_coupler"
        except Exception:
            pass
    return Path(__file__).resolve().parents[1] / "dashboard_magnetic_coupler"


def parse_args():
    """Parses CLI arguments for the standalone dashboard server."""

    parser = argparse.ArgumentParser(description="TensorBoard-like dashboard for magnetic coupler optimization runs.")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--static-dir", type=str, default="")
    parser.add_argument("--run", type=str, default="")
    parser.add_argument("--history-limit", type=int, default=500)
    parser.add_argument("--open-browser", action="store_true")
    return parser.parse_args()


def is_run_directory(path: Path) -> bool:
    """Returns True when the directory looks like a magnetic-coupler output run."""

    if not path.is_dir():
        return False
    if any((path / marker).exists() for marker in RUN_MARKERS):
        return True
    return path.name.startswith("magnetic_coupler")


def safe_relative_to(path: Path, root: Path) -> bool:
    """Checks whether path stays inside root after resolution."""

    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def list_run_dirs(outputs_root: Path) -> list[Path]:
    """Lists candidate run directories, newest first."""

    if not outputs_root.exists():
        return []
    runs = [child for child in outputs_root.iterdir() if is_run_directory(child)]
    runs.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return runs


def read_json(path: Path):
    """Reads JSON from disk, returning None on failure."""

    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def coerce_csv_scalar(value: str):
    """Converts CSV scalars into numbers when possible."""

    text = value.strip()
    if text == "":
        return None
    lower = text.lower()
    if lower in {"nan", "none", "null"}:
        return None
    try:
        if any(token in text for token in (".", "e", "E")):
            return float(text)
        return int(text)
    except Exception:
        return text


def read_csv_rows(path: Path, limit: int) -> list[dict]:
    """Reads the tail of a CSV file into JSON-friendly row dictionaries."""

    if not path.exists():
        return []
    rows = deque(maxlen=max(int(limit), 1))
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            for row in reader:
                rows.append({str(key): coerce_csv_scalar(value or "") for key, value in row.items()})
    except Exception:
        return []
    return list(rows)


def pick_existing(run_dir: Path, *names: str) -> Path | None:
    """Returns the first existing file among the candidate names."""

    for name in names:
        candidate = run_dir / name
        if candidate.exists():
            return candidate
    return None


def as_float(value, default: float) -> float:
    """Best-effort float conversion used for sorting summaries."""

    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def summarize_run(run_dir: Path) -> dict:
    """Builds the compact metadata shown in the run selector."""

    live_state = read_json(run_dir / "live_monitor_state.json") or {}
    final_json = read_json(run_dir / "best_design_hifi.json") or {}
    final_summary = live_state.get("final_summary") or final_json.get("dynamic_validation") or {}
    stage = live_state.get("stage") or ("completed" if final_json else "unknown")
    status = live_state.get("status") or ("completed" if final_json else "unknown")
    updated = float(live_state.get("updated_at_epoch_s") or run_dir.stat().st_mtime)
    return {
        "name": run_dir.name,
        "mtime_epoch_s": float(run_dir.stat().st_mtime),
        "updated_at_epoch_s": updated,
        "stage": stage,
        "status": status,
        "shape_label": live_state.get("final_shape_label") or final_json.get("shape_label"),
        "best_sku": (live_state.get("final_design") or {}).get("magnet_sku_id") or final_json.get("selected_design", {}).get("magnet_sku_id"),
        "best_score": final_summary.get("static_validation_score") or final_summary.get("mean_score") or live_state.get("design_search_complete", {}).get("best_score"),
        "active": status not in {"completed", "failed"} and updated >= time.time() - 1800.0,
    }


def default_run_name(runs: list[Path]) -> str:
    """Prefers an active run, otherwise the newest run."""

    if not runs:
        return ""
    summarized = [summarize_run(run_dir) for run_dir in runs]
    active = [item for item in summarized if item["active"]]
    if active:
        active.sort(key=lambda item: item["updated_at_epoch_s"], reverse=True)
        return str(active[0]["name"])
    return str(summarized[0]["name"])


def resolve_run_dir(outputs_root: Path, requested_name: str) -> Path | None:
    """Resolves the selected run name safely inside outputs_root."""

    runs = list_run_dirs(outputs_root)
    if not runs:
        return None
    chosen_name = requested_name or default_run_name(runs)
    candidate = (outputs_root / chosen_name).resolve()
    if not safe_relative_to(candidate, outputs_root) or not candidate.exists() or not candidate.is_dir():
        return None
    return candidate


def media_type_for_path(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    return None


def collect_media_artifacts(run_dir: Path) -> list[dict]:
    """Collects image/video artifacts for gallery display."""

    artifacts = []
    seen = set()
    for name in ARTIFACT_MEDIA_NAMES:
        candidate = run_dir / name
        if candidate.exists():
            media_type = media_type_for_path(candidate)
            poster_path = candidate.with_name(candidate.stem + "_poster.png")
            artifacts.append(
                {
                    "name": name,
                    "relative_path": name,
                    "media_type": media_type,
                    "poster_relative_path": str(poster_path.relative_to(run_dir)).replace("\\", "/")
                    if media_type == "video" and poster_path.exists()
                    else None,
                    "mtime_epoch_s": float(candidate.stat().st_mtime),
                }
            )
            seen.add(name)
    for candidate in sorted(run_dir.iterdir()):
        if candidate.is_dir():
            continue
        if candidate.name in seen:
            continue
        media_type = media_type_for_path(candidate)
        if media_type is None:
            continue
        poster_path = candidate.with_name(candidate.stem + "_poster.png")
        artifacts.append(
            {
                "name": candidate.name,
                "relative_path": candidate.name,
                "media_type": media_type,
                "poster_relative_path": str(poster_path.relative_to(run_dir)).replace("\\", "/")
                if media_type == "video" and poster_path.exists()
                else None,
                "mtime_epoch_s": float(candidate.stat().st_mtime),
            }
        )
        seen.add(candidate.name)
    generation_video_dir = run_dir / "generation_videos"
    if generation_video_dir.exists():
        generation_videos = sorted(
            generation_video_dir.glob("*.mp4"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:6]
        for candidate in generation_videos:
            relative_path = str(candidate.relative_to(run_dir)).replace("\\", "/")
            if relative_path in seen:
                continue
            poster_path = candidate.with_name(candidate.stem + "_poster.png")
            artifacts.append(
                {
                    "name": candidate.name,
                    "relative_path": relative_path,
                    "media_type": "video",
                    "poster_relative_path": str(poster_path.relative_to(run_dir)).replace("\\", "/")
                    if poster_path.exists()
                    else None,
                    "mtime_epoch_s": float(candidate.stat().st_mtime),
                }
            )
            seen.add(relative_path)
    artifacts.sort(key=lambda item: float(item["mtime_epoch_s"]), reverse=True)
    return artifacts


def infer_search_method(live_state: dict, design_history: list[dict], policy_history: list[dict]) -> dict:
    """Explains which optimizer produced the curves and whether it is RL."""

    run_args = live_state.get("run_args", {}) if isinstance(live_state, dict) else {}
    design_optimizer = run_args.get("design_optimizer")
    if not design_optimizer and design_history:
        design_optimizer = design_history[-1].get("optimizer")
    if not design_optimizer:
        design_optimizer = "unknown"
    policy_optimizer = "cem"
    design_label = {
        "cem": "Cross-Entropy Method",
        "cmaes": "CMA-ES",
        "unknown": "Unknown",
    }.get(str(design_optimizer), str(design_optimizer).upper())
    policy_label = {
        "cem": "Cross-Entropy Method",
        "unknown": "Unknown",
    }.get(str(policy_optimizer), str(policy_optimizer).upper())
    return {
        "design_optimizer": str(design_optimizer),
        "design_label": design_label,
        "design_is_reinforcement_learning": False,
        "design_family": "population-based black-box optimization",
        "policy_optimizer": str(policy_optimizer),
        "policy_label": policy_label,
        "policy_is_reinforcement_learning": False,
        "policy_family": "population-based policy search",
        "interpretation": (
            "Blue global-best curves are cumulative best-so-far summaries, so smooth or monotone behavior is expected. "
            "If you want to inspect true search roughness, use the candidate scatter and raw evaluation trace."
        ),
    }


def build_state_payload(outputs_root: Path, requested_run: str, history_limit: int) -> dict:
    """Builds the API payload consumed by the browser dashboard."""

    runs = list_run_dirs(outputs_root)
    run_dir = resolve_run_dir(outputs_root, requested_run)
    if run_dir is None:
        return {
            "outputs_root": str(outputs_root.resolve()),
            "available_runs": [summarize_run(item) for item in runs],
            "default_run": default_run_name(runs),
            "selected_run": "",
            "error": "No matching output run directory was found.",
        }

    live_state = read_json(run_dir / "live_monitor_state.json") or {}
    final_json = read_json(run_dir / "best_design_hifi.json") or {}
    design_history = read_csv_rows(pick_existing(run_dir, "live_design_history.csv", "design_history.csv") or Path(), history_limit)
    policy_history = read_csv_rows(pick_existing(run_dir, "live_policy_history.csv", "policy_history.csv") or Path(), history_limit)
    candidate_limit = max(int(history_limit) * 6, 1500)
    design_candidate_history = read_csv_rows(
        pick_existing(run_dir, "live_design_candidate_history.csv", "design_candidate_history.csv") or Path(),
        candidate_limit,
    )
    policy_candidate_history = read_csv_rows(
        pick_existing(run_dir, "live_policy_candidate_history.csv", "policy_candidate_history.csv") or Path(),
        candidate_limit,
    )
    gap_refinement = read_csv_rows(run_dir / "gap_refinement.csv", 64)
    archive_validation = read_csv_rows(run_dir / "design_candidate_archive_validation.csv", 64)
    dynamic_rows = read_csv_rows(run_dir / "dynamic_validation.csv", 256)
    dynamic_rows.sort(key=lambda row: as_float(row.get("score"), float("inf")))

    final_summary = live_state.get("final_summary") or {}
    dynamic_summary = live_state.get("dynamic_validation") or final_json.get("dynamic_validation") or {}
    selected_design = live_state.get("final_design") or final_json.get("selected_design") or {}
    static_assessment = live_state.get("final_static_assessment") or final_json.get("static_assessment") or {}
    search_method = infer_search_method(live_state, design_history, policy_history)

    media_artifacts = collect_media_artifacts(run_dir)
    for artifact in media_artifacts:
        query = urlencode({"run": run_dir.name, "path": artifact["relative_path"], "t": f'{artifact["mtime_epoch_s"]:.6f}'})
        artifact["url"] = f"/api/file?{query}"
        if artifact.get("poster_relative_path"):
            poster_query = urlencode(
                {"run": run_dir.name, "path": artifact["poster_relative_path"], "t": f'{artifact["mtime_epoch_s"]:.6f}'}
            )
            artifact["poster_url"] = f"/api/file?{poster_query}"

    return {
        "outputs_root": str(outputs_root.resolve()),
        "available_runs": [summarize_run(item) for item in runs],
        "default_run": default_run_name(runs),
        "selected_run": run_dir.name,
        "run_dir": str(run_dir.resolve()),
        "live_state": live_state,
        "final_json": final_json,
        "final_summary": final_summary,
        "dynamic_summary": dynamic_summary,
        "selected_design": selected_design,
        "static_assessment": static_assessment,
        "search_method": search_method,
        "latest_design_history": design_history[-1] if design_history else {},
        "latest_policy_history": policy_history[-1] if policy_history else {},
        "design_history": design_history,
        "policy_history": policy_history,
        "design_candidate_history": design_candidate_history,
        "policy_candidate_history": policy_candidate_history,
        "gap_refinement": gap_refinement,
        "archive_validation": archive_validation,
        "dynamic_validation_worst_rows": dynamic_rows[: min(len(dynamic_rows), 16)],
        "media_artifacts": media_artifacts,
        "image_artifacts": media_artifacts,
        "generated_at_epoch_s": time.time(),
    }


class MagneticDashboardHandler(SimpleHTTPRequestHandler):
    """HTTP handler serving static UI plus JSON/file APIs."""

    def __init__(self, *args, outputs_root: Path, history_limit: int, directory: str, **kwargs):
        self._outputs_root = outputs_root
        self._history_limit = history_limit
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/runs":
            runs = list_run_dirs(self._outputs_root)
            self._send_json(
                {
                    "outputs_root": str(self._outputs_root.resolve()),
                    "runs": [summarize_run(item) for item in runs],
                    "default_run": default_run_name(runs),
                    "generated_at_epoch_s": time.time(),
                }
            )
            return
        if parsed.path == "/api/state":
            query = parse_qs(parsed.query)
            requested_run = query.get("run", [""])[0]
            self._send_json(build_state_payload(self._outputs_root, requested_run, self._history_limit))
            return
        if parsed.path == "/api/file":
            query = parse_qs(parsed.query)
            requested_run = query.get("run", [""])[0]
            relative_path = query.get("path", [""])[0]
            self._send_run_file(requested_run, relative_path)
            return
        super().do_GET()

    def log_message(self, format, *args):
        return

    def _send_json(self, data: dict):
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_run_file(self, requested_run: str, relative_path: str):
        run_dir = resolve_run_dir(self._outputs_root, requested_run)
        if run_dir is None:
            self.send_error(404, "Run not found")
            return
        candidate = (run_dir / relative_path).resolve()
        if not safe_relative_to(candidate, run_dir) or not candidate.exists() or not candidate.is_file():
            self.send_error(404, "Artifact not found")
            return
        mime_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        payload = candidate.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime_type)
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    """Starts the magnetic coupler dashboard server."""

    args = parse_args()
    outputs_root = args.outputs_root.resolve()
    outputs_root.mkdir(parents=True, exist_ok=True)
    static_dir = resolve_static_dir(args.static_dir)

    handler = partial(
        MagneticDashboardHandler,
        outputs_root=outputs_root,
        history_limit=args.history_limit,
        directory=str(static_dir),
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    url = f"http://{args.host}:{args.port}/"
    if args.run:
        url += f"?run={args.run}"

    if args.open_browser:
        threading.Timer(0.4, lambda: webbrowser.open_new_tab(url)).start()

    print(f"Magnetic coupler dashboard: {url}")
    print(f"Watching outputs root: {outputs_root}")
    server.serve_forever()


if __name__ == "__main__":
    main()
