from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _root_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def build_profile(
    source: Path,
    destination: Path,
    *,
    grid_levels: int,
    cert_max_evaluations: int,
    shgo_samples: int,
    shgo_iters: int,
    max_iter: int,
    control_km: float = 1000.0,
    grid_values: list[float] | None = None,
    cert_workers: int = 1,
) -> dict:
    cfg = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        raise ValueError("The source profile must contain a YAML mapping.")
    out = deepcopy(cfg)

    model = out.setdefault("model", {})
    sim = out.setdefault("simulation", {})
    mpc = out.setdefault("mpc", {})
    meta = out.setdefault("meta", {})
    if not all(isinstance(block, dict) for block in (model, sim, mpc, meta)):
        raise ValueError("meta, simulation, model, and mpc must be YAML mappings.")

    soc_min = float(model.get("soc_min", mpc.get("soc_min", 0.1)))
    soc_max = float(model.get("soc_max", mpc.get("soc_max", 0.98)))
    if not (0.0 <= soc_min < soc_max <= 1.0):
        raise ValueError(f"Invalid SoC limits: soc_min={soc_min}, soc_max={soc_max}")
    race_km = float(mpc.get("race_km", 0.0))
    if race_km <= 2831.0:
        raise ValueError(
            f"race_km={race_km} is not a complete BWSC-course capability run; "
            "use the official full route distance, not the historical retirement point."
        )
    if grid_levels < 2:
        raise ValueError("grid_levels must be at least 2 for a finite-grid certificate.")
    if control_km <= 0.0:
        raise ValueError("control_km must be positive.")

    # A profile owns its manifest. Reusing one "latest" path across generations
    # silently made a newer smoke/certification run replace older evidence.
    output_dir = destination.parent / "outputs" / destination.stem
    output_prefix = f"{destination.stem}_fullcourse"
    meta["name"] = destination.stem
    refinement_text = (
        " and bounded continuous SHGO refinement"
        if int(shgo_samples) > 0
        else " without an unproved continuous-search claim"
    )
    meta["purpose"] = (
        "No-trouble full-course minimum-time capability run with a terminal usable-energy band, "
        f"an exact finite-grid certificate{refinement_text}."
    )
    notes = meta.setdefault("notes", [])
    if not isinstance(notes, list):
        notes = [str(notes)]
        meta["notes"] = notes
    notes.extend(
        [
            "The historical 2831 km retirement event is not applied; optimization continues to the official course finish.",
            "Nominal weather is used without a growing risk reserve; upper/lower weather risks are separate scenarios.",
            "Discrete global proof applies only to the declared finite speed grid. SHGO does not claim an unconditional finite-run continuous proof.",
            "A nonzero upper_max_iter or SHGO setting adds off-grid candidates and therefore cannot be labeled a finite-library global proof.",
            "Terminal dispatchable energy is measured above the execution safety floor soc_min + soc_guard_margin.",
        ]
    )

    sim["energy_budget"] = False
    sim["soc0"] = min(soc_max, max(soc_min, float(sim.get("soc0", soc_max))))
    sim["output_dir"] = _root_relative(output_dir)
    sim["output_prefix"] = output_prefix
    sim["auto_version_outputs"] = True
    sim["latest_manifest_json"] = _root_relative(output_dir / "latest_simulation_run.json")

    operational_soc_floor = min(
        soc_max,
        soc_min + max(0.0, float(mpc.get("soc_guard_margin", 0.0))),
    )
    mpc["terminal_soc_min"] = operational_soc_floor
    mpc["soc_finish_target"] = operational_soc_floor
    mpc["soc_finish_tol"] = 0.005
    mpc["race_km"] = race_km
    mpc["upper_horizon_km"] = race_km
    mpc["upper_horizon_mode"] = "adaptive_full_race"
    mpc["upper_replan_sec"] = 0.0
    mpc["upper_replan_km"] = 0.0
    mpc["upper_day_end_soc_min"] = soc_min
    mpc["execution_soc_trajectory_guard_enabled"] = False
    mpc["prediction_execution_soc_tolerance"] = 0.005
    mpc["upper_max_iter"] = int(max_iter)
    mpc["upper_ctrl_km"] = float(control_km)
    mpc["upper_global_search_enabled"] = True
    mpc["upper_global_search_mode"] = "certify"
    mpc["upper_shgo_samples"] = int(shgo_samples)
    mpc["upper_shgo_iters"] = int(shgo_iters)
    mpc["upper_cert_grid_levels"] = int(grid_levels)
    if grid_values:
        clean_grid_values = sorted({float(value) for value in grid_values})
        if len(clean_grid_values) < 2:
            raise ValueError("grid_values must contain at least two distinct speeds")
        mpc["upper_cert_grid_values_kmh"] = clean_grid_values
        mpc["upper_cert_grid_levels"] = len(clean_grid_values)
    else:
        mpc.pop("upper_cert_grid_values_kmh", None)
    mpc["upper_cert_max_evaluations"] = int(cert_max_evaluations)
    mpc["upper_cert_workers"] = max(1, int(cert_workers))
    mpc["upper_cert_progress_interval"] = 25
    mpc["w_soc_terminal"] = 1.0e12

    upper_cost = mpc.setdefault("upper_cost", {})
    if not isinstance(upper_cost, dict):
        raise ValueError("mpc.upper_cost must be a YAML mapping.")
    upper_cost.update(
        {
            "objective_mode": "fastest_feasible",
            "w_wait": 1.0,
            "w_travel_time": 1.0,
            "w_soc_terminal": 1.0e12,
            "w_uncertainty_reserve": 0.0,
            "reserve_soc_per_hour": 0.0,
            "reserve_soc_max_extra": 0.0,
            "w_progress_lag": 0.0,
            "w_progress_terminal_lag": 0.0,
            "constraint_penalty": 1.0e12,
        }
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(out, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a no-trouble full-course fastest-feasible profile with explicit optimality certificates."
    )
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output-profile", type=Path)
    parser.add_argument("--grid-levels", type=int, default=5)
    parser.add_argument("--cert-max-evaluations", type=int, default=250000)
    parser.add_argument(
        "--cert-workers",
        type=int,
        default=1,
        help="Parallel workers for independent finite-grid evaluations. Use one for live/ROS execution.",
    )
    parser.add_argument(
        "--grid-values-kmh",
        default="",
        help="Optional comma-separated speed values. Their Cartesian product is exhaustively evaluated.",
    )
    parser.add_argument(
        "--shgo-samples",
        type=int,
        default=0,
        help="Optional continuous SHGO samples. Zero keeps only the exact declared finite-grid certificate.",
    )
    parser.add_argument("--shgo-iters", type=int, default=2)
    parser.add_argument(
        "--max-iter",
        type=int,
        default=0,
        help="Local-refinement iterations. Keep zero for an exact finite-library certificate.",
    )
    parser.add_argument(
        "--control-km",
        type=float,
        default=1000.0,
        help="Distance represented by one optimized speed decision. The default gives four decisions on the 3026.9 km route.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.profile.resolve()
    destination = (
        args.output_profile.resolve()
        if args.output_profile
        else source.with_name(f"{source.stem}_fastest_certified.yaml")
    )
    grid_values = [float(token) for token in args.grid_values_kmh.split(",") if token.strip()]
    cfg = build_profile(
        source,
        destination,
        grid_levels=args.grid_levels,
        cert_max_evaluations=args.cert_max_evaluations,
        shgo_samples=args.shgo_samples,
        shgo_iters=args.shgo_iters,
        max_iter=args.max_iter,
        control_km=args.control_km,
        grid_values=grid_values,
        cert_workers=args.cert_workers,
    )
    mpc = cfg["mpc"]
    print(destination)
    print(
        "race_km={race} target_band=[{lo}, {hi}] control_km={ctrl} "
        "grid_levels={grid} shgo_samples={samples}".format(
            race=mpc["race_km"],
            lo=mpc["soc_finish_target"],
            hi=mpc["soc_finish_target"] + mpc["soc_finish_tol"],
            ctrl=mpc["upper_ctrl_km"],
            grid=mpc["upper_cert_grid_levels"],
            samples=mpc["upper_shgo_samples"],
        )
    )


if __name__ == "__main__":
    main()
