import json
import math
import os
import time
import ast
from dataclasses import dataclass
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(r"C:\Users\user\OneDrive - 和歌山大学\ソーラー\エネマネ\solar_ws0129-main")

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mpc_solarcar import magnetic_coupler_hifi as hifi


OUTDIR = ROOT / "outputs" / "magnetic_coupler_hifi_daiso13_realism_campaign_20260630"
FIXED_SKU = "DAISO_SUPER_13MM_4P"
FIXED_CART_MASS_KG = 18.0
DT_S = 0.06
MAX_WORKERS = max(1, min(4, (os.cpu_count() or 1)))
FINAL_VALIDATION_SAMPLES = 128
FINAL_POLICY_GENERATIONS = 5
FINAL_POLICY_POPULATION = 5
FINAL_POLICY_ELITE_COUNT = 2
TOP_DYNAMIC_CANDIDATES_PER_MODE = 2

MODE_CONFIGS = [
    {
        "mode": "both",
        "quick_points": 80,
        "quick_samples": 32,
        "seed_count": 2,
        "restart_max_evals": 18,
        "restart_population": 4,
        "restart_elite": 2,
        "restart_min_generations": 3,
        "restart_stall_generations": 3,
        "initial_std": 0.88,
    },
    {
        "mode": "flex",
        "quick_points": 80,
        "quick_samples": 32,
        "seed_count": 2,
        "restart_max_evals": 18,
        "restart_population": 4,
        "restart_elite": 2,
        "restart_min_generations": 3,
        "restart_stall_generations": 3,
        "initial_std": 0.84,
    },
    {
        "mode": "arrow",
        "quick_points": 48,
        "quick_samples": 32,
        "seed_count": 1,
        "restart_max_evals": 16,
        "restart_population": 4,
        "restart_elite": 2,
        "restart_min_generations": 3,
        "restart_stall_generations": 3,
        "initial_std": 0.84,
    },
]


def prime_sequence(count: int) -> list[int]:
    primes = []
    candidate = 2
    while len(primes) < count:
        is_prime = True
        limit = int(math.sqrt(candidate)) + 1
        for prime in primes:
            if prime > limit:
                break
            if candidate % prime == 0:
                is_prime = False
                break
        if is_prime:
            primes.append(candidate)
        candidate += 1
    return primes


def van_der_corput(index: int, base: int) -> float:
    result = 0.0
    denom = 1.0
    n = int(index)
    while n > 0:
        n, remainder = divmod(n, base)
        denom *= base
        result += remainder / denom
    return result


def halton_sequence(count: int, dimension: int, start_index: int = 1) -> np.ndarray:
    bases = prime_sequence(dimension)
    points = np.empty((count, dimension), dtype=float)
    for row_index in range(count):
        seq_index = start_index + row_index
        for col_index, base in enumerate(bases):
            points[row_index, col_index] = van_der_corput(seq_index, base)
    return points


def unit_to_latent(unit_points: np.ndarray) -> np.ndarray:
    clipped = np.clip(np.asarray(unit_points, dtype=float), 1.0e-5, 1.0 - 1.0e-5)
    return np.log(clipped / (1.0 - clipped))


def feature_vector(row: dict, mode: str) -> np.ndarray:
    family_flag = 1.0 if row.get("shape_family") == "arrow" else 0.0
    return np.array(
        [
            row["gap_m"] / 0.070,
            row["mean_radius_m"] / 0.210,
            row["magnets_per_ring"] / 80.0,
            row["magnet_layers"] / 6.0,
            row["estimated_total_cost_jpy"] / 9000.0,
            row["mean_orthogonal_ratio"],
            row["mean_forward_torque_ratio"],
            row["negative_yaw_restore_count"] / 40.0,
            row["negative_towed_yaw_restore_count"] / 80.0,
            family_flag if mode == "both" else 0.0,
        ],
        dtype=float,
    )


def greedy_diverse_indices(rows: list[dict], mode: str, wanted: int, distance_threshold: float = 0.18) -> list[int]:
    selected = []
    selected_features: list[np.ndarray] = []
    for index, row in enumerate(rows):
        row_feature = feature_vector(row, mode)
        if not selected_features:
            selected.append(index)
            selected_features.append(row_feature)
        else:
            min_distance = min(float(np.linalg.norm(row_feature - existing)) for existing in selected_features)
            if min_distance >= distance_threshold:
                selected.append(index)
                selected_features.append(row_feature)
        if len(selected) >= wanted:
            break
    if len(selected) < wanted:
        for index in range(len(rows)):
            if index not in selected:
                selected.append(index)
            if len(selected) >= wanted:
                break
    return selected


def quick_worker(job: dict) -> dict:
    mode = job["mode"]
    latent_vector = np.asarray(job["latent_vector"], dtype=float)
    catalog = hifi.resolve_catalog(FIXED_SKU)
    candidate = hifi.evaluate_design_candidate_quick(
        latent_vector=latent_vector,
        num_samples=job["quick_samples"],
        catalog=catalog,
        fixed_cart_mass_kg=FIXED_CART_MASS_KG,
        shape_family_mode=mode,
    )
    design = candidate["design"]
    assessment = candidate["static_assessment"]
    return {
        "mode": mode,
        "latent_vector": latent_vector.tolist(),
        "score": float(candidate["score"]),
        "shape_family": design.shape_parameters.family,
        "shape_label": hifi.shape_name(design.shape_parameters),
        "gap_m": float(design.gap_m),
        "mean_radius_m": float(design.mean_radius_m),
        "magnets_per_ring": int(design.magnets_per_ring),
        "magnet_layers": int(design.magnet_layers),
        "estimated_total_cost_jpy": float(design.estimated_total_cost_jpy),
        "mean_orthogonal_ratio": float(assessment.mean_orthogonal_ratio),
        "mean_forward_torque_ratio": float(assessment.mean_forward_torque_ratio),
        "negative_yaw_restore_count": int(assessment.negative_yaw_restore_count),
        "negative_towed_yaw_restore_count": int(assessment.negative_towed_yaw_restore_count),
    }


def validation_worker(job: dict) -> dict:
    mode = job["mode"]
    latent_vector = np.asarray(job["latent_vector"], dtype=float)
    catalog = hifi.resolve_catalog(FIXED_SKU)
    candidate = hifi.evaluate_design_candidate_validation(
        latent_vector=latent_vector,
        num_samples=job["validation_samples"],
        catalog=catalog,
        fixed_cart_mass_kg=FIXED_CART_MASS_KG,
        shape_family_mode=mode,
    )
    design = candidate["design"]
    assessment = candidate["static_assessment"]
    return {
        "mode": mode,
        "latent_vector": latent_vector.tolist(),
        "search_score": float(job["search_score"]),
        "validation_score": float(candidate["score"]),
        "shape_family": design.shape_parameters.family,
        "shape_label": hifi.shape_name(design.shape_parameters),
        "gap_m": float(design.gap_m),
        "mean_radius_m": float(design.mean_radius_m),
        "magnets_per_ring": int(design.magnets_per_ring),
        "magnet_layers": int(design.magnet_layers),
        "total_magnets": int(design.total_magnets),
        "estimated_total_cost_jpy": float(design.estimated_total_cost_jpy),
        "mean_orthogonal_ratio": float(assessment.mean_orthogonal_ratio),
        "mean_forward_torque_ratio": float(assessment.mean_forward_torque_ratio),
        "negative_yaw_restore_count": int(assessment.negative_yaw_restore_count),
        "negative_towed_yaw_restore_count": int(assessment.negative_towed_yaw_restore_count),
        "min_yaw_restoring_nm": float(assessment.min_yaw_restoring_nm),
        "min_towed_yaw_restoring_nm": float(assessment.min_towed_yaw_restoring_nm),
        "package_violation_mm": 1000.0 * float(assessment.package_violation_m),
    }


def merge_archive_maps(target_map: dict, source_map: dict):
    for signature, payload in source_map.items():
        existing = target_map.get(signature)
        if existing is None or payload["score"] > existing["score"]:
            target_map[signature] = payload


def parse_latent_vector(value) -> np.ndarray:
    if isinstance(value, np.ndarray):
        return value.astype(float, copy=False)
    if isinstance(value, list):
        return np.asarray(value, dtype=float)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("latent vector string is empty")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = ast.literal_eval(text)
        return np.asarray(parsed, dtype=float)
    return np.asarray(value, dtype=float)


def dynamic_candidate_sort_key(row: dict):
    return (
        -int(row["dynamic_contact_events_total"]),
        -int(row["dynamic_latched_total"]),
        float(row["worst_clearance_mm"]),
        float(row["dynamic_worst_score"]),
        float(row["dynamic_mean_score"]),
        float(row["static_validation_score"]),
    )


def tracking_candidate_sort_key(row: dict):
    return (
        -int(row["dynamic_contact_events_total"]),
        -int(row["dynamic_latched_total"]),
        float(row["dynamic_worst_score"]),
        float(row["dynamic_mean_score"]),
        float(row["worst_clearance_mm"]),
        float(row["static_validation_score"]),
    )


def evaluate_dynamic_pipeline(mode: str, latent_vector: np.ndarray, seed: int) -> dict:
    catalog = hifi.resolve_catalog(FIXED_SKU)
    design_candidate = hifi.evaluate_design_candidate_validation(
        latent_vector=latent_vector,
        num_samples=FINAL_VALIDATION_SAMPLES,
        catalog=catalog,
        fixed_cart_mass_kg=FIXED_CART_MASS_KG,
        shape_family_mode=mode,
    )
    design = design_candidate["design"]
    geometry = hifi.build_geometry_from_shape(
        design.shape_parameters,
        design.mean_radius_m,
        design.gap_m,
        96,
    )
    policy_candidate, policy_history_df = hifi.optimize_policy(
        design=design,
        geometry=geometry,
        seed=seed,
        generations=FINAL_POLICY_GENERATIONS,
        population=FINAL_POLICY_POPULATION,
        elite_count=FINAL_POLICY_ELITE_COUNT,
        dt_s=DT_S,
        replica_count=hifi.DYNAMIC_SEARCH_ENV_REPLICAS,
        substeps=hifi.DYNAMIC_SEARCH_SUBSTEPS,
    )
    refined_design, refined_geometry, gap_refinement_df = hifi.refine_gap_after_policy(
        design,
        policy_candidate["policy"],
        seed=seed,
        num_samples=96,
    )
    if abs(refined_design.gap_m - design.gap_m) > 1.0e-6:
        design = refined_design
        geometry = refined_geometry
        policy_candidate, policy_history_df = hifi.optimize_policy(
            design=design,
            geometry=geometry,
            seed=seed + 1000,
            generations=FINAL_POLICY_GENERATIONS,
            population=FINAL_POLICY_POPULATION,
            elite_count=FINAL_POLICY_ELITE_COUNT,
            dt_s=DT_S,
            replica_count=hifi.DYNAMIC_SEARCH_ENV_REPLICAS,
            substeps=hifi.DYNAMIC_SEARCH_SUBSTEPS,
        )
    static_model = hifi.build_array_model(design, geometry, hifi.VALIDATION_DIPOLE_GRID)
    static_assessment = hifi.assess_static_design(
        static_model,
        directions=np.linspace(0.0, 2.0 * math.pi, 16, endpoint=False),
        displacements_m=hifi.VALIDATION_DISPLACEMENTS_M,
        height_fractions=np.linspace(0.0, 0.95, 6),
        yaw_samples_rad=hifi.VALIDATION_YAW_RAD,
    )
    scenarios = hifi.filter_validation_scenarios(seed, DT_S)
    dynamic_outcomes = []
    for scenario in scenarios:
        environments = hifi.build_episode_environments(
            design,
            scenario.name,
            seed=seed + 14000,
            replica_count=hifi.DYNAMIC_VALIDATION_ENV_REPLICAS,
        )
        for environment in environments:
            dynamic_outcomes.append(
                hifi.simulate_dynamic_episode(
                    static_model,
                    policy_candidate["policy"],
                    scenario,
                    environment=environment,
                    record=False,
                    substeps=hifi.DYNAMIC_VALIDATION_SUBSTEPS,
                )
            )
    dynamic_df = hifi.report_dynamic_dataframe(dynamic_outcomes)
    return {
        "mode": mode,
        "latent_vector": latent_vector.tolist(),
        "shape_label": hifi.shape_name(design.shape_parameters),
        "shape_family": design.shape_parameters.family,
        "gap_mm": 1000.0 * float(design.gap_m),
        "mean_radius_mm": 1000.0 * float(design.mean_radius_m),
        "magnets_per_ring": int(design.magnets_per_ring),
        "magnet_layers": int(design.magnet_layers),
        "total_magnets": int(design.total_magnets),
        "cost_jpy": float(design.estimated_total_cost_jpy),
        "static_validation_score": float(static_assessment.score),
        "mean_orthogonal_ratio": float(static_assessment.mean_orthogonal_ratio),
        "mean_forward_torque_ratio": float(static_assessment.mean_forward_torque_ratio),
        "negative_yaw_restore_count": int(static_assessment.negative_yaw_restore_count),
        "negative_towed_yaw_restore_count": int(static_assessment.negative_towed_yaw_restore_count),
        "dynamic_mean_score": float(dynamic_df["score"].mean()),
        "dynamic_worst_score": float(dynamic_df["score"].min()),
        "dynamic_contact_events_total": int(dynamic_df["contact_events"].sum()),
        "dynamic_latched_total": int(dynamic_df["latched"].sum()),
        "worst_clearance_mm": float(dynamic_df["min_clearance_mm"].min()),
        "max_contact_demand_mm": float(dynamic_df["max_contact_demand_mm"].max()),
        "gap_refinement_best_gap_mm": 1000.0
        * float(
            gap_refinement_df.sort_values(
                "dynamic_mean_score" if "dynamic_mean_score" in gap_refinement_df.columns else "screening_score",
                ascending=False,
            ).iloc[0]["gap_m"]
        ),
    }


def format_markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_No rows_"
    columns = [str(column) for column in df.columns]
    rows = [[str(value) for value in row] for row in df.astype(object).itertuples(index=False, name=None)]
    widths = []
    for col_index, column in enumerate(columns):
        cell_width = max(len(column), *(len(row[col_index]) for row in rows))
        widths.append(cell_width)
    header = "| " + " | ".join(column.ljust(widths[index]) for index, column in enumerate(columns)) + " |"
    separator = "| " + " | ".join("-" * widths[index] for index in range(len(columns))) + " |"
    body = [
        "| " + " | ".join(row[index].ljust(widths[index]) for index in range(len(columns))) + " |"
        for row in rows
    ]
    return "\n".join([header, separator] + body)


def plot_quick_screen(df: pd.DataFrame):
    figure, axis = plt.subplots(figsize=(10.0, 5.2), dpi=180)
    for mode, group in df.groupby("mode"):
        sorted_scores = np.sort(group["score"].to_numpy())[::-1]
        axis.plot(np.arange(1, len(sorted_scores) + 1), sorted_scores, marker="o", markersize=2.5, linewidth=1.2, label=mode)
    axis.set_xlabel("rank")
    axis.set_ylabel("quick static score")
    axis.set_title("Quick-screen score ranking by shape-family mode")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(OUTDIR / "quick_screen_scores.png", dpi=180)
    plt.close(figure)


def plot_restart_summary(df: pd.DataFrame):
    figure, axis = plt.subplots(figsize=(10.0, 5.0), dpi=180)
    for mode, group in df.groupby("mode"):
        group_sorted = group.sort_values("restart_index")
        axis.plot(
            group_sorted["restart_index"].to_numpy(),
            group_sorted["best_search_score"].to_numpy(),
            marker="o",
            linewidth=1.5,
            label=mode,
        )
    axis.set_xlabel("restart index")
    axis.set_ylabel("best search score")
    axis.set_title("Local restart search results")
    axis.grid(True, alpha=0.25)
    axis.legend()
    figure.tight_layout()
    figure.savefig(OUTDIR / "restart_search_scores.png", dpi=180)
    plt.close(figure)


def plot_final_candidates(df: pd.DataFrame):
    figure, axis = plt.subplots(figsize=(10.5, 5.2), dpi=180)
    labels = df["label"].tolist()
    values = df["dynamic_mean_score"].to_numpy()
    colors = ["#0f766e" if row["source"] == "campaign" else "#334155" for _, row in df.iterrows()]
    axis.bar(labels, values, color=colors)
    axis.set_ylabel("dynamic mean score")
    axis.set_title("Final candidate comparison")
    axis.grid(True, axis="y", alpha=0.25)
    axis.tick_params(axis="x", rotation=20)
    figure.tight_layout()
    figure.savefig(OUTDIR / "final_candidate_comparison.png", dpi=180)
    plt.close(figure)


def write_report(
    quick_df: pd.DataFrame,
    restart_df: pd.DataFrame,
    validation_df: pd.DataFrame,
    final_df: pd.DataFrame,
    champion: dict,
    tracking_champion: dict,
    elapsed_s: float,
):
    lines = [
        "# Magnetic Coupler Global Search Campaign",
        "",
        "## Campaign Scope",
        f"- SKU fixed to `{FIXED_SKU}`.",
        "- Search executed across `both`, `flex`, and `arrow` family modes.",
        "- Initial global coverage used a deterministic Halton low-discrepancy sequence, not plain IID random seeds.",
        "- Each mode then used multiple local CEM restarts seeded from diverse quick-screen elites.",
        "- High-resolution static validation and final dynamic validation were both required before ranking a candidate.",
        f"- Cart mass was fixed to `{FIXED_CART_MASS_KG:.1f} kg` so every candidate is judged on the same LIMO + cart operating condition.",
        "",
        "## Runtime",
        f"- Elapsed wall-clock time: `{elapsed_s/60.0:.1f} min`.",
        f"- Parallel workers used for quick and validation screens: `{MAX_WORKERS}`.",
        f"- Final static validation samples per candidate: `{FINAL_VALIDATION_SAMPLES}`.",
        f"- Final policy-learning budget per candidate: `{FINAL_POLICY_GENERATIONS}` generations x `{FINAL_POLICY_POPULATION}` population.",
        "",
        "## Quick Screen Summary",
        f"- Total quick evaluations: `{len(quick_df)}`.",
    ]
    for mode, group in quick_df.groupby("mode"):
        lines.append(
            f"- `{mode}`: count=`{len(group)}`, best quick score=`{group['score'].max():.3f}`, median=`{group['score'].median():.3f}`."
        )
    lines.extend(
        [
            "",
            "## Restart Summary",
            f"- Local restart count: `{len(restart_df)}`.",
            "",
            format_markdown_table(restart_df),
            "",
            "## High-Resolution Static Validation",
            "",
            format_markdown_table(validation_df),
            "",
            "## Final Dynamic Comparison",
            "",
            format_markdown_table(final_df),
            "",
            "## Safety-Margin Champion",
            f"- Label: `{champion['label']}`",
            f"- Source: `{champion['source']}`",
            f"- Shape label: `{champion['shape_label']}`",
            f"- Family: `{champion['shape_family']}`",
            f"- Gap: `{champion['gap_mm']:.2f} mm`",
            f"- Mean radius: `{champion['mean_radius_mm']:.2f} mm`",
            f"- Magnets/ring: `{champion['magnets_per_ring']}`",
            f"- Layers: `{champion['magnet_layers']}`",
            f"- Total magnets: `{champion['total_magnets']}`",
            f"- Estimated cost: `{champion['cost_jpy']:.0f} JPY`",
            f"- Static validation score: `{champion['static_validation_score']:.3f}`",
            f"- Dynamic mean score: `{champion['dynamic_mean_score']:.3f}`",
            f"- Dynamic worst score: `{champion['dynamic_worst_score']:.3f}`",
            f"- Contact events: `{champion['dynamic_contact_events_total']}`",
            f"- Latched events: `{champion['dynamic_latched_total']}`",
            f"- Worst physical clearance: `{champion['worst_clearance_mm']:.3f} mm`",
            "",
            "## Tracking Champion",
            f"- Label: `{tracking_champion['label']}`",
            f"- Source: `{tracking_champion['source']}`",
            f"- Shape label: `{tracking_champion['shape_label']}`",
            f"- Family: `{tracking_champion['shape_family']}`",
            f"- Dynamic mean score: `{tracking_champion['dynamic_mean_score']:.3f}`",
            f"- Dynamic worst score: `{tracking_champion['dynamic_worst_score']:.3f}`",
            f"- Worst physical clearance: `{tracking_champion['worst_clearance_mm']:.3f} mm`",
            "",
            "## Convergence Interpretation",
            "- This campaign gives empirical global-search evidence within the modeled search space, but it is not a formal proof of a mathematical global optimum.",
            "- The strongest evidence comes from: deterministic low-discrepancy global coverage, multi-mode restarts, archive revalidation at higher fidelity, and final dynamic comparison of multiple finalists per mode under the same revised realism-focused dynamics.",
            "- Legacy result folders are intentionally not mixed into this ranking because their dynamic scores were produced under an older objective and older disturbance model, so direct numerical comparison would be misleading.",
        ]
    )
    (OUTDIR / "global_campaign_report.md").write_text("\n".join(lines), encoding="utf-8")


def run_jobs(worker, jobs, max_workers: int):
    if max_workers <= 1:
        return [worker(job) for job in jobs]
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(worker, jobs))


def main():
    start_time = time.perf_counter()
    OUTDIR.mkdir(parents=True, exist_ok=True)
    quick_csv = OUTDIR / "quick_screen_results.csv"
    restart_csv = OUTDIR / "restart_results.csv"
    validation_csv = OUTDIR / "validation_results.csv"
    dynamic_csv = OUTDIR / "dynamic_mode_results.csv"

    if validation_csv.exists():
        quick_df = pd.read_csv(quick_csv)
        restart_df = pd.read_csv(restart_csv)
        validation_df = pd.read_csv(validation_csv)
    else:
        if quick_csv.exists():
            quick_df = pd.read_csv(quick_csv)
        else:
            quick_jobs = []
            for mode_index, config in enumerate(MODE_CONFIGS):
                dimension = hifi.design_variable_count(config["mode"])
                halton_points = halton_sequence(config["quick_points"], dimension, start_index=17 + 131 * mode_index)
                latent_points = unit_to_latent(halton_points)
                for latent_vector in latent_points:
                    quick_jobs.append(
                        {
                            "mode": config["mode"],
                            "latent_vector": latent_vector.tolist(),
                            "quick_samples": config["quick_samples"],
                        }
                    )
            quick_rows = run_jobs(quick_worker, quick_jobs, MAX_WORKERS)
            quick_df = pd.DataFrame(quick_rows).sort_values(["mode", "score"], ascending=[True, False])
            quick_df.to_csv(quick_csv, index=False)
            plot_quick_screen(quick_df)

        restart_rows = []
        mode_archives: dict[str, dict] = {}
        validation_jobs = []

        for config in MODE_CONFIGS:
            mode = config["mode"]
            mode_df = quick_df[quick_df["mode"] == mode].sort_values("score", ascending=False).reset_index(drop=True)
            mode_rows = mode_df.to_dict("records")
            chosen_indices = greedy_diverse_indices(mode_rows, mode, config["seed_count"])
            archive_map = {}
            for restart_index, chosen_index in enumerate(chosen_indices):
                seed_row = mode_rows[chosen_index]
                initial_mean = parse_latent_vector(seed_row["latent_vector"])
                initial_std = np.ones_like(initial_mean) * config["initial_std"]
                design_candidate, design_history_df, archive_df, local_archive_map = hifi.optimize_design(
                    seed=7000 + 101 * restart_index + 1000 * (1 + [item["mode"] for item in MODE_CONFIGS].index(mode)),
                    generations=config["restart_min_generations"],
                    population=config["restart_population"],
                    elite_count=config["restart_elite"],
                    num_samples=72,
                    fixed_sku_id=FIXED_SKU,
                    fixed_cart_mass_kg=FIXED_CART_MASS_KG,
                    shape_family_mode=mode,
                    max_evaluations=config["restart_max_evals"],
                    min_generations=config["restart_min_generations"],
                    stall_generations=config["restart_stall_generations"],
                    coarse_presearch_trials=0,
                    coarse_presearch_samples=config["quick_samples"],
                    archive_limit=12,
                    initial_mean=initial_mean,
                    initial_std=initial_std,
                )
                merge_archive_maps(archive_map, local_archive_map)
                restart_rows.append(
                    {
                        "mode": mode,
                        "restart_index": restart_index,
                        "seed_quick_rank": chosen_index + 1,
                        "seed_quick_score": float(seed_row["score"]),
                        "best_search_score": float(design_candidate["score"]),
                        "best_family": design_candidate["design"].shape_parameters.family,
                        "gap_mm": 1000.0 * float(design_candidate["design"].gap_m),
                        "mean_radius_mm": 1000.0 * float(design_candidate["design"].mean_radius_m),
                        "magnets_per_ring": int(design_candidate["design"].magnets_per_ring),
                        "magnet_layers": int(design_candidate["design"].magnet_layers),
                        "cost_jpy": float(design_candidate["design"].estimated_total_cost_jpy),
                        "history_rows": int(len(design_history_df)),
                        "archive_size": int(len(local_archive_map)),
                    }
                )
            mode_archives[mode] = archive_map
            ranked_archive = sorted(archive_map.items(), key=lambda item: item[1]["score"], reverse=True)[: min(3, len(archive_map))]
            for signature, payload in ranked_archive:
                validation_jobs.append(
                    {
                        "mode": mode,
                        "latent_vector": payload["latent_vector"].tolist(),
                        "search_score": payload["score"],
                        "validation_samples": 96,
                        "signature": signature,
                    }
                )

        restart_df = pd.DataFrame(restart_rows)
        restart_df.to_csv(restart_csv, index=False)
        plot_restart_summary(restart_df)

        validation_rows = run_jobs(validation_worker, validation_jobs, MAX_WORKERS)
        validation_df = pd.DataFrame(validation_rows).sort_values("validation_score", ascending=False)
        validation_df.to_csv(validation_csv, index=False)

    cached_dynamic_df = pd.read_csv(dynamic_csv) if dynamic_csv.exists() else pd.DataFrame()
    mode_best_dynamic_rows = []
    for mode in validation_df["mode"].drop_duplicates().tolist():
        mode_validation_df = validation_df[validation_df["mode"] == mode].sort_values("validation_score", ascending=False)
        for candidate_rank, (_, mode_best_row) in enumerate(
            mode_validation_df.head(TOP_DYNAMIC_CANDIDATES_PER_MODE).iterrows(),
            start=1,
        ):
            latent_vector = parse_latent_vector(mode_best_row["latent_vector"]).tolist()
            cached_row = None
            if not cached_dynamic_df.empty:
                match_df = cached_dynamic_df[
                    (cached_dynamic_df["mode"] == mode)
                    & (cached_dynamic_df["latent_vector"].astype(str) == str(latent_vector))
                ]
                if not match_df.empty:
                    cached_row = match_df.iloc[0].to_dict()
            if cached_row is None:
                dynamic_row = evaluate_dynamic_pipeline(
                    mode=mode,
                    latent_vector=np.asarray(latent_vector, dtype=float),
                    seed=26000 + 137 * (1 + [item["mode"] for item in MODE_CONFIGS].index(mode)) + 17 * candidate_rank,
                )
            else:
                dynamic_row = cached_row
            dynamic_row["label"] = f"campaign_{mode}_rank{candidate_rank}"
            dynamic_row["source"] = "campaign"
            dynamic_row["candidate_rank_within_mode"] = candidate_rank
            mode_best_dynamic_rows.append(dynamic_row)
            pd.DataFrame(mode_best_dynamic_rows).to_csv(dynamic_csv, index=False)

    final_rows = mode_best_dynamic_rows
    final_df = pd.DataFrame(final_rows)
    final_df = final_df.sort_values(
        by=[
            "dynamic_contact_events_total",
            "dynamic_latched_total",
            "worst_clearance_mm",
            "dynamic_worst_score",
            "dynamic_mean_score",
            "static_validation_score",
        ],
        ascending=[True, True, False, False, False, False],
    ).reset_index(drop=True)
    final_df.to_csv(OUTDIR / "final_candidate_comparison.csv", index=False)
    plot_final_candidates(final_df)

    champion = max(final_rows, key=dynamic_candidate_sort_key)
    tracking_champion = max(final_rows, key=tracking_candidate_sort_key)
    summary = {
        "campaign_output_dir": str(OUTDIR),
        "fixed_sku": FIXED_SKU,
        "fixed_cart_mass_kg": FIXED_CART_MASS_KG,
        "quick_evaluation_count": int(len(quick_df)),
        "restart_count": int(len(restart_df)),
        "validation_count": int(len(validation_df)),
        "champion": champion,
        "tracking_champion": tracking_champion,
        "elapsed_s": float(time.perf_counter() - start_time),
    }
    (OUTDIR / "campaign_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_report(
        quick_df=quick_df,
        restart_df=restart_df,
        validation_df=validation_df,
        final_df=final_df,
        champion=champion,
        tracking_champion=tracking_champion,
        elapsed_s=summary["elapsed_s"],
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
