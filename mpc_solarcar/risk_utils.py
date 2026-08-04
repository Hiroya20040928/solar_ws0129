from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ScenarioRiskConfig:
    """Risk settings for a score-maximizing multi-scenario evaluation."""

    cvar_alpha: float = 0.90
    cvar_weight: float = 0.30
    variance_weight: float = 0.0
    max_failure_probability: float = 0.01
    infeasible_score: float = -1.0e9


def normalized_scenario_weights(weights) -> np.ndarray:
    values = np.asarray(weights, dtype=float)
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("scenario weights must be a non-empty one-dimensional array")
    if not np.all(np.isfinite(values)) or np.any(values < 0.0):
        raise ValueError("scenario weights must be finite and non-negative")
    total = float(np.sum(values))
    if total <= 0.0:
        raise ValueError("scenario weights must have positive total mass")
    return values / total


def weighted_cvar(losses, weights, alpha: float = 0.90) -> float:
    """Return upper-tail CVaR for a finite weighted empirical loss distribution."""
    loss_values = np.asarray(losses, dtype=float)
    probability = normalized_scenario_weights(weights)
    if loss_values.ndim != 1 or len(loss_values) != len(probability):
        raise ValueError("losses and weights must be one-dimensional arrays of equal length")
    if not np.all(np.isfinite(loss_values)):
        raise ValueError("losses must be finite")
    alpha = float(alpha)
    if not np.isfinite(alpha) or not 0.0 <= alpha < 1.0:
        raise ValueError("alpha must satisfy 0 <= alpha < 1")

    tail_mass = 1.0 - alpha
    order = np.argsort(loss_values)[::-1]
    remaining = tail_mass
    tail_sum = 0.0
    for idx in order:
        included = min(float(probability[idx]), remaining)
        tail_sum += included * float(loss_values[idx])
        remaining -= included
        if remaining <= 1.0e-15:
            break
    return float(tail_sum / tail_mass)


def aggregate_scenario_scores(
    scores,
    weights,
    feasible,
    config: ScenarioRiskConfig | None = None,
) -> dict:
    """Aggregate utilities while enforcing a weighted scenario chance constraint."""
    config = config or ScenarioRiskConfig()
    score_values = np.asarray(scores, dtype=float)
    probability = normalized_scenario_weights(weights)
    feasible_values = np.asarray(feasible, dtype=bool)
    if score_values.ndim != 1 or len(score_values) != len(probability):
        raise ValueError("scores and weights must be one-dimensional arrays of equal length")
    if feasible_values.ndim != 1 or len(feasible_values) != len(probability):
        raise ValueError("feasible and weights must be one-dimensional arrays of equal length")
    if not np.all(np.isfinite(score_values)):
        raise ValueError("scores must be finite")

    cvar_weight = max(0.0, float(config.cvar_weight))
    variance_weight = max(0.0, float(config.variance_weight))
    max_failure_probability = float(config.max_failure_probability)
    if not 0.0 <= max_failure_probability <= 1.0:
        raise ValueError("max_failure_probability must satisfy 0 <= p <= 1")

    mean_score = float(np.dot(probability, score_values))
    score_variance = float(np.dot(probability, np.square(score_values - mean_score)))
    losses = -score_values
    mean_loss = -mean_score
    cvar_loss = weighted_cvar(losses, probability, alpha=float(config.cvar_alpha))
    tail_excess_loss = max(0.0, cvar_loss - mean_loss)
    risk_adjusted_score = (
        mean_score
        - variance_weight * score_variance
        - cvar_weight * tail_excess_loss
    )

    failure_probability = float(np.dot(probability, (~feasible_values).astype(float)))
    chance_constraint_pass = bool(
        failure_probability <= max_failure_probability + 1.0e-12
    )
    aggregate_score = float(risk_adjusted_score)
    if not chance_constraint_pass:
        aggregate_score = min(
            aggregate_score,
            float(config.infeasible_score) - failure_probability,
        )

    return {
        "score": aggregate_score,
        "risk_adjusted_score": float(risk_adjusted_score),
        "score_mean": mean_score,
        "score_worst": float(np.min(score_values)),
        "score_variance": score_variance,
        "loss_cvar": float(cvar_loss),
        "tail_excess_loss": float(tail_excess_loss),
        "scenario_failure_probability": failure_probability,
        "max_scenario_failure_probability": max_failure_probability,
        "chance_constraint_pass": chance_constraint_pass,
        "scenario_feasible_all": bool(np.all(feasible_values)),
        "normalized_scenario_weights": probability.tolist(),
        "risk_config": {
            "cvar_alpha": float(config.cvar_alpha),
            "cvar_weight": cvar_weight,
            "variance_weight": variance_weight,
            "max_failure_probability": max_failure_probability,
            "infeasible_score": float(config.infeasible_score),
        },
    }
