from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FreshnessResult:
    state: str
    health: float
    diagnostic: str


@dataclass(frozen=True)
class CommandGateResult:
    allowed: bool
    reason: str


def evaluate_freshness(
    *,
    elapsed_sec: float,
    ages_sec: dict[str, float | None],
    required: tuple[str, ...],
    timeout_sec: float,
    startup_grace_sec: float,
) -> FreshnessResult:
    if elapsed_sec < startup_grace_sec:
        return FreshnessResult("STARTING", 0.25, "waiting for required solar telemetry")

    missing = [name for name in required if ages_sec.get(name) is None]
    stale = [
        name
        for name in required
        if ages_sec.get(name) is not None and float(ages_sec[name]) > timeout_sec
    ]
    if missing:
        return FreshnessResult("DEGRADED", 0.2, "missing: " + ", ".join(missing))
    if stale:
        return FreshnessResult("DEGRADED", 0.4, "stale: " + ", ".join(stale))
    return FreshnessResult("RUNNING", 1.0, "solar telemetry and planner inputs are fresh")


def evaluate_command_gate(
    *,
    elapsed_sec: float,
    speed_input_age_sec: float | None,
    system_state: str,
    system_state_age_sec: float | None,
    startup_hold_sec: float,
    input_timeout_sec: float,
    system_state_timeout_sec: float,
    require_system_running: bool,
) -> CommandGateResult:
    if elapsed_sec < max(0.0, startup_hold_sec):
        return CommandGateResult(False, "startup_hold")
    if speed_input_age_sec is None:
        return CommandGateResult(False, "missing_speed_command")
    if speed_input_age_sec > max(0.0, input_timeout_sec):
        return CommandGateResult(False, "stale_speed_command")
    if not require_system_running:
        return CommandGateResult(True, "ok_without_system_gate")
    if system_state_age_sec is None:
        return CommandGateResult(False, "missing_system_state")
    if system_state_age_sec > max(0.0, system_state_timeout_sec):
        return CommandGateResult(False, "stale_system_state")
    if str(system_state).strip().upper() != "RUNNING":
        return CommandGateResult(False, "system_not_running")
    return CommandGateResult(True, "ok")
