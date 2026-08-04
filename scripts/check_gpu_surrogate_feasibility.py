#!/usr/bin/env python3
"""Reject a high-fidelity GPU surrogate result that violates vehicle limits."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import yaml


def evaluate_summary(profile: dict, summary: dict) -> dict:
    model = profile.get("model", {})
    mpc = profile.get("mpc", {})
    simulation = profile.get("simulation", {})
    soc_floor = float(mpc.get("terminal_soc_min", model.get("soc_min", 0.1)))
    soc_target = float(mpc.get("soc_finish_target", soc_floor))
    if soc_target < 0.0:
        soc_target = soc_floor
    soc_tolerance = float(mpc.get("soc_finish_tol", 0.005))
    discharge_limit_a = float(model.get("I_max", 40.0))
    charge_limit_a = abs(float(model.get("I_chg_min", -16.5)))

    final_soc = float(summary.get("surrogate_final_soc", float("nan")))
    min_soc = float(summary.get("surrogate_min_soc", float("nan")))
    max_discharge_a = float(summary.get("surrogate_max_current_a", float("nan")))
    max_charge_a = float(summary.get("surrogate_max_charge_current_a", float("nan")))
    elapsed_h = float(summary.get("surrogate_elapsed_h", float("nan")))
    timing_required = bool(str(simulation.get("race_deadline_utc", "") or ""))
    max_timing_violation_sec = float(
        summary.get(
            "surrogate_max_timing_violation_sec",
            float("nan") if timing_required else 0.0,
        )
    )
    checks = {
        "finite": all(
            math.isfinite(value)
            for value in (
                final_soc,
                min_soc,
                max_discharge_a,
                max_charge_a,
                elapsed_h,
                max_timing_violation_sec,
            )
        ),
        "soc_floor": min_soc >= soc_floor - 1.0e-4,
        "terminal_target": (
            soc_target - soc_tolerance - 1.0e-4
            <= final_soc
            <= soc_target + soc_tolerance + 1.0e-4
        ),
        "discharge_current": max_discharge_a <= discharge_limit_a + 0.1,
        "charge_current": max_charge_a <= charge_limit_a + 0.1,
        "official_event_timing": max_timing_violation_sec <= 1.0,
    }
    return {
        "scope": "high-fidelity GPU surrogate pre-gate; exact 1 Hz replay remains mandatory",
        "passed": bool(all(checks.values())),
        "checks": checks,
        "limits": {
            "soc_floor": soc_floor,
            "soc_target": soc_target,
            "soc_tolerance": soc_tolerance,
            "max_discharge_current_a": discharge_limit_a,
            "max_charge_current_a": charge_limit_a,
        },
        "observed": {
            "final_soc": final_soc,
            "min_soc": min_soc,
            "max_discharge_current_a": max_discharge_a,
            "max_charge_current_a": max_charge_a,
            "elapsed_h": elapsed_h,
            "max_timing_violation_sec": max_timing_violation_sec,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    profile = yaml.safe_load(args.profile.read_text(encoding="utf-8")) or {}
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    result = evaluate_summary(profile, summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
