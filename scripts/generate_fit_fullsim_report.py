#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import textwrap
from pathlib import Path
from typing import Dict, Iterable

import matplotlib
import numpy as np
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_bwsc2025_fitted_package import (
    BATTERY_E_NOM_MAX_WH,
    BATTERY_E_NOM_MIN_WH,
    BATTERY_ETA_CHARGE_MAX,
    BATTERY_ETA_CHARGE_MIN,
    BATTERY_RINT_SCALE_MAX,
    BATTERY_RINT_SCALE_MIN,
    compile_tex,
    ensure_dir,
)
from scripts.audit_identification_residuals import weather_and_cruise_metrics


def resolve_path(base_dir: Path, raw: str) -> Path:
    path = Path(str(raw or "").strip())
    if not path:
        return base_dir
    if path.is_absolute():
        return path
    rooted = (ROOT / path).resolve()
    if rooted.exists():
        return rooted
    return (base_dir / path).resolve()


def latex_escape(text: object) -> str:
    value = str(text)
    repl = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for src, dst in repl.items():
        value = value.replace(src, dst)
    value = value.replace("/", r"/\allowbreak{}")
    value = value.replace(r"\_", r"\_\allowbreak{}")
    return value


def rel_display(path: Path | None, base_dir: Path) -> str:
    if path is None:
        return "not found"
    return os.path.relpath(path, base_dir).replace("\\", "/")


def locate_package_dir(profile_yaml: Path) -> Path:
    """Return the owning project package even for versioned run profiles."""
    profile_yaml = profile_yaml.resolve()
    for candidate in (profile_yaml.parent, *profile_yaml.parents):
        if candidate.parent.name != "project_packages":
            continue
        if (candidate / "data").is_dir() and (candidate / "outputs").is_dir():
            return candidate
    return profile_yaml.parent


def locate_fit_summary(package_dir: Path, profile_yaml: Path | None = None) -> Path:
    if profile_yaml is not None and profile_yaml.exists():
        profile = yaml.safe_load(profile_yaml.read_text(encoding="utf-8")) or {}
        output_tag = str((profile.get("identification", {}) or {}).get("output_tag", "") or "").strip()
        if output_tag:
            tagged = (
                package_dir
                / "outputs"
                / "identification"
                / "runs"
                / output_tag
                / f"{package_dir.name}_generic_fit_summary.yaml"
            )
            if tagged.exists():
                return tagged
            raise FileNotFoundError(
                f"fit summary for identification.output_tag={output_tag!r} not found: {tagged}"
            )
    preferred = package_dir / "outputs" / "identification" / f"{package_dir.name}_generic_fit_summary.yaml"
    if preferred.exists():
        return preferred
    candidates = sorted(
        (package_dir / "outputs" / "identification").glob("*_generic_fit_summary.yaml"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("generic fit summary not found")
    return candidates[0]


def rms(values: pd.Series) -> float:
    arr = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean(arr ** 2)))


def day_block_bootstrap_rmse(
    df: pd.DataFrame,
    residual_column: str,
    *,
    draws: int = 10_000,
    seed: int = 20260714,
) -> Dict[str, float]:
    if df.empty or "local_date" not in df.columns or residual_column not in df.columns:
        return {
            "rmse": float("nan"),
            "ci95_min": float("nan"),
            "ci95_max": float("nan"),
            "day_blocks": 0,
            "draws": 0,
        }
    work = pd.DataFrame(
        {
            "local_date": df["local_date"].astype(str),
            "residual": pd.to_numeric(df[residual_column], errors="coerce"),
        }
    ).dropna()
    if work.empty:
        return {
            "rmse": float("nan"),
            "ci95_min": float("nan"),
            "ci95_max": float("nan"),
            "day_blocks": 0,
            "draws": 0,
        }
    blocks = (
        work.assign(sq=lambda frame: frame["residual"] ** 2)
        .groupby("local_date")
        .agg(sse=("sq", "sum"), count=("sq", "size"))
    )
    sse = blocks["sse"].to_numpy(dtype=float)
    count = blocks["count"].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    samples = rng.integers(0, len(blocks), size=(int(draws), len(blocks)))
    sampled_rmse = np.sqrt(sse[samples].sum(axis=1) / count[samples].sum(axis=1))
    return {
        "rmse": float(np.sqrt(sse.sum() / count.sum())),
        "ci95_min": float(np.quantile(sampled_rmse, 0.025)),
        "ci95_max": float(np.quantile(sampled_rmse, 0.975)),
        "day_blocks": int(len(blocks)),
        "draws": int(draws),
    }


def load_replay_diagnostics(package_dir: Path, replay_csv: Path | None = None) -> Dict[str, object]:
    replay_csv = replay_csv or package_dir / "outputs" / "identification" / "replay_validation.csv"
    if not replay_csv.exists():
        return {
            "replay_csv": replay_csv,
            "frame": pd.DataFrame(),
            "clean_frame": pd.DataFrame(),
            "daily": pd.DataFrame(),
            "worst_power": pd.DataFrame(),
            "worst_voltage": pd.DataFrame(),
        }
    df = pd.read_csv(replay_csv, low_memory=False)
    fallback_ts = pd.to_datetime(
        df["time_utc"], format="mixed", utc=True, errors="coerce"
    ).dt.tz_convert("Australia/Darwin").dt.tz_localize(None)
    if "time_local" in df.columns:
        ts = pd.to_datetime(df["time_local"], format="mixed", errors="coerce")
        if getattr(ts.dt, "tz", None) is not None:
            ts = ts.dt.tz_localize(None)
        ts = ts.fillna(fallback_ts)
    else:
        ts = fallback_ts
    df["local_date"] = ts.dt.strftime("%Y-%m-%d")
    df["power_resid_w"] = pd.to_numeric(df["battery_power_w_obs"], errors="coerce") - pd.to_numeric(df["battery_power_w_pred"], errors="coerce")
    df["voltage_resid_v"] = pd.to_numeric(df["battery_voltage_v_obs"], errors="coerce") - pd.to_numeric(df["battery_voltage_v_pred"], errors="coerce")
    if "exclude_power_fit" in df.columns:
        df["exclude_power_fit"] = df["exclude_power_fit"].astype(bool)
    else:
        df["exclude_power_fit"] = False
    if "exclude_voltage_fit" in df.columns:
        df["exclude_voltage_fit"] = df["exclude_voltage_fit"].astype(bool)
    else:
        df["exclude_voltage_fit"] = False

    clean = df.loc[(~df["exclude_power_fit"]) & (~df["exclude_voltage_fit"])].copy()
    daily = (
        clean.groupby("local_date", dropna=False)
        .agg(
            rows=("local_date", "size"),
            max_s_km=("s_km", "max"),
            power_rmse_w=("power_resid_w", rms),
            power_mae_w=("power_resid_w", lambda s: float(np.mean(np.abs(pd.to_numeric(s, errors="coerce"))))),
            voltage_rmse_v=("voltage_resid_v", rms),
            voltage_mae_v=("voltage_resid_v", lambda s: float(np.mean(np.abs(pd.to_numeric(s, errors="coerce"))))),
        )
        .reset_index()
    )
    worst_power = clean.loc[clean["power_resid_w"].abs().nlargest(8).index, [
        "time_utc", "s_km", "speed_kmh", "power_resid_w", "battery_power_w_obs", "battery_power_w_pred"
    ]].copy()
    worst_voltage = clean.loc[clean["voltage_resid_v"].abs().nlargest(8).index, [
        "time_utc", "s_km", "speed_kmh", "voltage_resid_v", "battery_voltage_v_obs", "battery_voltage_v_pred"
    ]].copy()
    return {
        "replay_csv": replay_csv,
        "frame": df,
        "clean_frame": clean,
        "daily": daily,
        "worst_power": worst_power,
        "worst_voltage": worst_voltage,
    }


def locate_fullsim_manifest(package_dir: Path, profile_yaml: Path) -> Path | None:
    profile_cfg = yaml.safe_load(profile_yaml.read_text(encoding="utf-8")) or {}
    sim = profile_cfg.get("simulation", {}) or {}
    raw = str(sim.get("latest_manifest_json", "") or "").strip()
    if raw:
        configured = Path(raw)
        if not configured.is_absolute():
            # Project profiles normally store workspace-relative output paths.  Do
            # not fall back to an older run when this exact manifest is missing.
            configured = (
                ROOT / configured
                if configured.parts and configured.parts[0] == "project_packages"
                else profile_yaml.parent / configured
            )
        configured = configured.resolve()
        return configured if configured.exists() else None

    candidates = [
        package_dir / "outputs" / "prerace_fullsim_selflearned" / "latest_simulation_run.json",
        package_dir / "outputs" / "prerace_final_selflearned" / "latest_simulation_run.json",
        package_dir / "outputs" / "prerace" / "latest_simulation_run.json",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def resolve_manifest_artifact(manifest_path: Path, raw: str, package_dir: Path) -> Path:
    """Resolve copied manifests whose original absolute path belongs to another host."""
    path = Path(str(raw or "").strip())
    if path.is_file():
        return path
    local_sibling = manifest_path.parent / path.name
    if local_sibling.is_file():
        return local_sibling
    return resolve_path(package_dir, str(raw or ""))


def load_fullsim_summary(
    package_dir: Path,
    profile_yaml: Path,
    manifest_path: Path | None = None,
) -> Dict[str, object]:
    manifest_path = manifest_path or locate_fullsim_manifest(package_dir, profile_yaml)
    if manifest_path is None:
        return {
            "manifest_path": None,
            "manifest": {},
            "frame": pd.DataFrame(),
            "daily": pd.DataFrame(),
        }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    out_csv = resolve_manifest_artifact(manifest_path, manifest.get("out_csv", ""), package_dir)
    df = pd.DataFrame()
    daily = pd.DataFrame()
    if out_csv.exists():
        df = pd.read_csv(out_csv, low_memory=False)
        utc_ts = pd.to_datetime(
            df["time_utc"], format="mixed", utc=True, errors="coerce"
        ).dt.tz_convert("Australia/Darwin").dt.tz_localize(None)
        if "time_local" in df.columns:
            local_ts = pd.to_datetime(df["time_local"], format="mixed", errors="coerce")
            if getattr(local_ts.dt, "tz", None) is not None:
                local_ts = local_ts.dt.tz_localize(None)
            local_ts = local_ts.fillna(utc_ts)
        else:
            local_ts = utc_ts
        df["local_date"] = local_ts.dt.strftime("%Y-%m-%d")
        dt_sec = pd.to_numeric(df.get("step_dt_sec", 0.0), errors="coerce").fillna(0.0).clip(lower=0.0)
        energy_columns = {
            "pv_energy_wh": "P_pv",
            "vehicle_load_energy_wh": "P_vehicle_load_w",
            "drive_dc_energy_wh": "P_dc_to_drv",
            "road_load_energy_wh": "P_road_load",
            "aux_energy_wh": "P_aux",
            "pack_net_energy_wh": "P_pack",
            "internal_loss_energy_wh": "losses_int",
            "line_loss_energy_wh": "losses_line",
        }
        for target, source in energy_columns.items():
            if source in df.columns:
                df[target] = pd.to_numeric(df[source], errors="coerce").fillna(0.0) * dt_sec / 3600.0

        if {"eff_drv", "v_exec_kmh"}.issubset(df.columns):
            moving = pd.to_numeric(df["v_exec_kmh"], errors="coerce") > 1.0
            df["eff_drv_moving"] = pd.to_numeric(df["eff_drv"], errors="coerce").where(moving)

        daily_agg: Dict[str, tuple[str, str]] = {
            "rows": ("local_date", "size"),
            "end_s_km": ("s_km", "max"),
            "min_soc": ("soc", "min"),
            "end_soc": ("soc_end" if "soc_end" in df.columns else "soc", "last"),
            "avg_v_exec_kmh": ("v_exec_kmh", "mean"),
            "avg_v_cmd_kmh": ("v_cmd_kmh", "mean"),
        }
        optional_aggregates = {
            "mean_poa_wm2": ("G_poa", "mean"),
            "max_poa_wm2": ("G_poa", "max"),
            "mean_ambient_c": ("Tamb_C", "mean"),
            "min_ambient_c": ("Tamb_C", "min"),
            "max_ambient_c": ("Tamb_C", "max"),
            "mean_cell_c": ("Tcell_C", "mean"),
            "mean_pv_w": ("P_pv", "mean"),
            "max_pv_w": ("P_pv", "max"),
            "max_discharge_current_a": ("I", "max"),
            "max_charge_current_a": ("I", "min"),
            "min_pack_voltage_v": ("V", "min"),
            "mean_drive_eff": ("eff_drv_moving", "mean"),
            **{name: (name, "sum") for name in energy_columns if name in df.columns},
        }
        for name, aggregate in optional_aggregates.items():
            if aggregate[0] in df.columns:
                daily_agg[name] = aggregate
        daily = df.groupby("local_date", dropna=False).agg(**daily_agg).reset_index()
    return {"manifest_path": manifest_path, "manifest": manifest, "frame": df, "daily": daily}


DETAIL_REQUIRED_COLUMNS = {
    "lower_command_index",
    "time_utc",
    "step_dt_sec",
    "detail_target_dt_sec",
    "outer_step_requested_dt_sec",
    "outer_step_actual_dt_sec",
    "outer_step_boundary_reason",
    "s_km",
    "upper_speed_cmd_kmh",
    "lower_speed_cmd_kmh",
    "v_exec_kmh",
    "soc",
    "G_poa",
    "Tamb_C",
    "Tcell_C",
    "P_pv",
    "P_aux",
    "P_vehicle_load_w",
    "P_pack",
    "I",
    "V",
    "OCV",
    "Rint",
    "Rline",
    "eff_drv",
    "eff_reg",
    "F_aero",
    "F_roll",
    "F_grade",
    "P_inertia",
    "param_m",
    "param_CdA",
    "param_Crr",
    "param_P_aux",
    "param_E_nom_Wh",
    "map_drive_eff_map",
    "map_regen_eff_map",
    "map_rint_map",
    "map_panel_eff_map",
    "map_mppt_eff_map",
    "map_ocv_soc_map",
}


def audit_fullsim_detail(
    package_dir: Path,
    manifest_path: Path | None,
    manifest: dict,
) -> Dict[str, object]:
    raw = str(manifest.get("detail_csv", "") or "").strip()
    if not raw or manifest_path is None:
        return {"available": False, "reason": "detail_csv_not_declared"}
    detail_path = resolve_manifest_artifact(manifest_path, raw, package_dir)
    if not detail_path.is_file():
        return {
            "available": False,
            "reason": "detail_csv_missing",
            "detail_csv": str(detail_path),
        }
    header = list(pd.read_csv(detail_path, nrows=0).columns)
    missing = sorted(DETAIL_REQUIRED_COLUMNS.difference(header))
    rows = 0
    nominal_rows = 0
    boundary_partial_rows = 0
    nonfinite_step_rows = 0
    nonpositive_rows = 0
    over_one_second_rows = 0
    target_not_one_second_rows = 0
    min_dt = float("inf")
    max_dt = float("-inf")
    usecols = [column for column in ("step_dt_sec", "detail_target_dt_sec") if column in header]
    if "step_dt_sec" in usecols:
        for chunk in pd.read_csv(detail_path, usecols=usecols, chunksize=200_000):
            dt = pd.to_numeric(chunk["step_dt_sec"], errors="coerce").to_numpy(dtype=float)
            finite = dt[np.isfinite(dt)]
            rows += int(len(chunk))
            nonfinite_step_rows += int(len(dt) - len(finite))
            if "detail_target_dt_sec" in chunk.columns:
                target = pd.to_numeric(
                    chunk["detail_target_dt_sec"], errors="coerce"
                ).to_numpy(dtype=float)
                target_not_one_second_rows += int(
                    np.count_nonzero(
                        (~np.isfinite(target))
                        | (~np.isclose(target, 1.0, atol=1.0e-9))
                    )
                )
            if finite.size:
                min_dt = min(min_dt, float(np.min(finite)))
                max_dt = max(max_dt, float(np.max(finite)))
                nominal_rows += int(np.count_nonzero(np.isclose(finite, 1.0, atol=1.0e-9)))
                boundary_partial_rows += int(np.count_nonzero((finite > 0.0) & (finite < 1.0 - 1.0e-9)))
                nonpositive_rows += int(np.count_nonzero(finite <= 0.0))
                over_one_second_rows += int(np.count_nonzero(finite > 1.0 + 1.0e-9))
    return {
        "available": True,
        "detail_csv": str(detail_path),
        "row_count": rows,
        "column_count": len(header),
        "required_column_count": len(DETAIL_REQUIRED_COLUMNS),
        "missing_required_columns": missing,
        "min_step_dt_sec": min_dt if np.isfinite(min_dt) else float("nan"),
        "max_step_dt_sec": max_dt if np.isfinite(max_dt) else float("nan"),
        "nominal_one_second_rows": nominal_rows,
        "boundary_partial_rows": boundary_partial_rows,
        "nonfinite_step_rows": nonfinite_step_rows,
        "nonpositive_step_rows": nonpositive_rows,
        "over_one_second_rows": over_one_second_rows,
        "target_not_one_second_rows": target_not_one_second_rows,
        "contract_pass": bool(
            not missing
            and rows > 0
            and nonfinite_step_rows == 0
            and nonpositive_rows == 0
            and over_one_second_rows == 0
            and target_not_one_second_rows == 0
        ),
    }


def interpolate_at_distance(df: pd.DataFrame, column: str, distance_km: float) -> float:
    if df.empty or "s_km" not in df.columns or column not in df.columns:
        return float("nan")
    work = pd.DataFrame(
        {
            "s_km": pd.to_numeric(df["s_km"], errors="coerce"),
            "value": pd.to_numeric(df[column], errors="coerce"),
        }
    ).dropna()
    if work.empty:
        return float("nan")
    work = work.groupby("s_km", as_index=False)["value"].last().sort_values("s_km")
    x = work["s_km"].to_numpy(dtype=float)
    y = work["value"].to_numpy(dtype=float)
    if distance_km < x[0] or distance_km > x[-1]:
        return float("nan")
    return float(np.interp(float(distance_km), x, y))


def moving_speed_in_interval(
    df: pd.DataFrame,
    column: str,
    start_km: float,
    end_km: float,
) -> float:
    if df.empty or "s_km" not in df.columns or column not in df.columns:
        return float("nan")
    distance = pd.to_numeric(df["s_km"], errors="coerce")
    speed = pd.to_numeric(df[column], errors="coerce")
    mask = (distance > start_km) & (distance <= end_km) & (speed > 5.0)
    values = speed.loc[mask].dropna()
    return float(values.mean()) if not values.empty else float("nan")


def build_human_mpc_distance_comparison(
    replay_df: pd.DataFrame,
    fullsim_df: pd.DataFrame,
    retire_distance_km: float,
) -> pd.DataFrame:
    if replay_df.empty or fullsim_df.empty:
        return pd.DataFrame()
    endpoints = [500.0, 1000.0, 1500.0, 2000.0, 2500.0, float(retire_distance_km)]
    endpoints = sorted({value for value in endpoints if 0.0 < value <= retire_distance_km})
    human_soc_series = pd.to_numeric(replay_df.get("soc_pred"), errors="coerce").dropna()
    mpc_soc_series = pd.to_numeric(fullsim_df.get("soc"), errors="coerce").dropna()
    if human_soc_series.empty or mpc_soc_series.empty:
        return pd.DataFrame()

    rows = []
    start_km = 0.0
    for end_km in endpoints:
        human_soc = interpolate_at_distance(replay_df, "soc_pred", end_km)
        mpc_soc = interpolate_at_distance(fullsim_df, "soc", end_km)
        rows.append(
            {
                "segment_km": f"{start_km:.0f}-{end_km:.1f}",
                "end_s_km": end_km,
                "human_moving_speed_kmh": moving_speed_in_interval(
                    replay_df, "speed_kmh", start_km, end_km
                ),
                "mpc_moving_speed_kmh": moving_speed_in_interval(
                    fullsim_df, "v_exec_kmh", start_km, end_km
                ),
                "human_reconstructed_soc": human_soc,
                "mpc_no_trouble_soc": mpc_soc,
                "soc_gap_mpc_minus_human": mpc_soc - human_soc,
            }
        )
        start_km = end_km
    return pd.DataFrame(rows)


def build_daily_progress_comparison(
    replay_df: pd.DataFrame,
    fullsim_df: pd.DataFrame,
) -> pd.DataFrame:
    if replay_df.empty or fullsim_df.empty or "local_date" not in replay_df or "local_date" not in fullsim_df:
        return pd.DataFrame()
    human = (
        replay_df.groupby("local_date", as_index=False)["s_km"]
        .max()
        .rename(columns={"s_km": "human_end_s_km"})
    )
    mpc = (
        fullsim_df.groupby("local_date", as_index=False)["s_km"]
        .max()
        .rename(columns={"s_km": "mpc_end_s_km"})
    )
    out = human.merge(mpc, on="local_date", how="outer").sort_values("local_date")
    out["mpc_progress_lead_km"] = out["mpc_end_s_km"] - out["human_end_s_km"]
    return out.reset_index(drop=True)


def write_human_mpc_distance_plot(
    replay_df: pd.DataFrame,
    fullsim_df: pd.DataFrame,
    comparison: pd.DataFrame,
    output_path: Path,
    retire_distance_km: float,
) -> Path | None:
    if comparison.empty:
        return None
    fig, axes = plt.subplots(2, 1, figsize=(10.0, 7.0), sharex=True)
    for df, value_col, label, color, linestyle in (
        (replay_df, "soc_pred", "Historical replay reconstruction", "black", "-"),
        (fullsim_df, "soc", "MPC no-trouble fullsim", "0.35", "--"),
    ):
        work = df[["s_km", value_col]].apply(pd.to_numeric, errors="coerce").dropna()
        work = work.groupby("s_km", as_index=False)[value_col].last().sort_values("s_km")
        axes[0].plot(
            work["s_km"],
            work[value_col],
            label=label,
            color=color,
            linestyle=linestyle,
            linewidth=1.6,
        )
    axes[0].axvline(retire_distance_km, color="0.55", linestyle=":", linewidth=1.0)
    axes[0].set_ylabel("SoC [-]")
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="best")

    axes[1].plot(
        comparison["end_s_km"],
        comparison["human_moving_speed_kmh"],
        marker="o",
        label="Historical moving mean",
        color="black",
        linestyle="-",
    )
    axes[1].plot(
        comparison["end_s_km"],
        comparison["mpc_moving_speed_kmh"],
        marker="s",
        label="MPC moving mean",
        color="0.35",
        linestyle="--",
    )
    axes[1].axvline(retire_distance_km, color="0.55", linestyle=":", linewidth=1.0)
    axes[1].set_xlabel("Route distance [km]")
    axes[1].set_ylabel("Moving speed [km/h]")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="best")
    fig.suptitle("Historical operation vs no-trouble MPC by route distance")
    fig.tight_layout()
    fig.savefig(output_path, dpi=180, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_no data_"
    data = df.copy()
    for col in data.columns:
        if pd.api.types.is_float_dtype(data[col]):
            data[col] = data[col].map(lambda v: f"{v:.4f}" if pd.notna(v) else "")
    headers = [str(c) for c in data.columns]
    rows = [[str(v) for v in row] for row in data.itertuples(index=False, name=None)]
    sep = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def tex_kv_table(items: Iterable[tuple[str, object]]) -> str:
    rows = "\n".join(f"{latex_escape(k)} & {latex_escape(v)} \\\\" for k, v in items)
    return textwrap.dedent(
        f"""
        \\begin{{longtable}}{{p{{0.46\\linewidth}}p{{0.36\\linewidth}}}}
        \\toprule
        項目 & 値 \\\\
        \\midrule
        \\endhead
        {rows}
        \\bottomrule
        \\end{{longtable}}
        """
    ).strip()


def tex_df_table(df: pd.DataFrame, title: str) -> str:
    if df.empty:
        return f"\\paragraph{{{latex_escape(title)}}} no data available."
    data = df.copy()
    for col in data.columns:
        if pd.api.types.is_float_dtype(data[col]):
            data[col] = data[col].map(lambda v: "" if pd.isna(v) else f"{v:.4f}")
    headers = " & ".join(latex_escape(c) for c in data.columns) + r" \\"
    rows = "\n".join(" & ".join(latex_escape(v) for v in row) + r" \\" for row in data.astype(str).itertuples(index=False, name=None))
    max_cell_len = max((len(str(value)) for value in data.to_numpy().ravel()), default=0)
    if len(data.columns) == 2 and max_cell_len > 48:
        colspec = r"p{0.25\textwidth}p{0.68\textwidth}"
    else:
        colspec = "l" * len(data.columns)
    table = textwrap.dedent(
        f"""
        \\begin{{tabular}}{{{colspec}}}
        \\toprule
        {headers}
        \\midrule
        {rows}
        \\bottomrule
        \\end{{tabular}}
        """
    ).strip()
    if len(data.columns) >= 4:
        table = f"\\resizebox{{\\textwidth}}{{!}}{{%\n{table}\n}}"
    return textwrap.dedent(
        f"""
        \\paragraph{{{latex_escape(title)}}}
        \\begin{{center}}
        {table}
        \\end{{center}}
        """
    ).strip()


def build_report(
    package_dir: Path,
    profile_yaml: Path,
    *,
    fit_summary_path: Path | None = None,
    replay_csv: Path | None = None,
    fullsim_manifest: Path | None = None,
) -> tuple[Path, Path]:
    fit_summary_path = fit_summary_path or locate_fit_summary(package_dir, profile_yaml)
    fit_summary = yaml.safe_load(fit_summary_path.read_text(encoding="utf-8")) or {}
    profile = yaml.safe_load(profile_yaml.read_text(encoding="utf-8")) or {}
    if replay_csv is None:
        versioned_replay = fit_summary_path.parent / "replay_validation.csv"
        if versioned_replay.exists():
            replay_csv = versioned_replay
    replay = load_replay_diagnostics(package_dir, replay_csv)
    end_to_end_replay_path = fit_summary_path.parent / "replay_validation_end_to_end.csv"
    end_to_end_replay = (
        pd.read_csv(end_to_end_replay_path, low_memory=False)
        if end_to_end_replay_path.is_file()
        else replay.get("frame", pd.DataFrame())
    )
    weather_daily, _ = weather_and_cruise_metrics(end_to_end_replay)
    _, cruise_70kmh = weather_and_cruise_metrics(
        replay.get("frame", pd.DataFrame())
    )
    cruise_70kmh_rows = pd.DataFrame(
        [{"metric": key, "value": value} for key, value in cruise_70kmh.items()]
    )
    fullsim = load_fullsim_summary(package_dir, profile_yaml, fullsim_manifest)
    detail_audit = audit_fullsim_detail(
        package_dir,
        fullsim.get("manifest_path"),
        fullsim.get("manifest", {}) or {},
    )
    detail_audit_rows = pd.DataFrame(
        [
            {
                "metric": key,
                "value": ", ".join(value) if isinstance(value, list) else value,
            }
            for key, value in detail_audit.items()
            if key != "detail_csv"
        ]
    )
    versioned_terminal_consistency = fit_summary_path.parent / "terminal_soc_consistency.yaml"
    terminal_consistency_path = (
        versioned_terminal_consistency
        if versioned_terminal_consistency.exists()
        else package_dir / "outputs" / "identification" / "terminal_soc_consistency.yaml"
    )
    terminal_consistency = (
        yaml.safe_load(terminal_consistency_path.read_text(encoding="utf-8")) or {}
        if terminal_consistency_path.exists()
        else {}
    )

    report_dir = package_dir / "outputs" / "reports"
    ensure_dir(report_dir)
    stem = f"{profile_yaml.stem}_fit_fullsim_report"
    md_path = report_dir / f"{stem}.md"
    tex_path = report_dir / f"{stem}.tex"
    versioned_current_maps = fit_summary_path.parent / "current_maps_and_coefficients.md"
    release_current_maps = report_dir / "current_maps_and_coefficients.md"
    if versioned_current_maps.exists():
        release_current_maps.write_bytes(versioned_current_maps.read_bytes())

    battery = fit_summary.get("battery_fit", {}) or {}
    battery_dynamic = fit_summary.get("battery_dynamic_fit", {}) or {}
    motion = fit_summary.get("motion_fit", {}) or {}
    pv = fit_summary.get("pv_fit", {}) or {}
    metrics = fit_summary.get("validation_metrics", {}) or {}
    solar_calibration = (
        (fit_summary.get("fit_plan", {}) or {}).get("solar_measurement_calibration", {}) or {}
    )
    model_cfg = profile.get("model", {}) or {}
    clean_replay = replay.get("clean_frame", pd.DataFrame())
    power_bootstrap = day_block_bootstrap_rmse(clean_replay, "power_resid_w", seed=20260714)
    voltage_bootstrap = day_block_bootstrap_rmse(clean_replay, "voltage_resid_v", seed=20260715)
    observed_power = pd.to_numeric(
        clean_replay.get("battery_power_w_obs", pd.Series(dtype=float)), errors="coerce"
    ).dropna()
    observed_power_rms = (
        float(np.sqrt(np.mean(observed_power.to_numpy(dtype=float) ** 2)))
        if not observed_power.empty
        else float("nan")
    )
    conditional_power_nrmse = (
        float(power_bootstrap["rmse"]) / observed_power_rms
        if np.isfinite(observed_power_rms) and observed_power_rms > 0.0
        else float("nan")
    )
    fitted_e_nom_wh = float(battery.get("e_nom_wh", float("nan")))
    fitted_rint_scale = float(battery.get("rint_scale", float("nan")))
    fitted_eta_charge = float(battery.get("eta_charge", float("nan")))
    fitted_q_nom_ah = float(model_cfg.get("Q_nom_Ah", float("nan")))
    physical_parameter_gate_pass = bool(
        np.isfinite(fitted_e_nom_wh)
        and BATTERY_E_NOM_MIN_WH <= fitted_e_nom_wh <= BATTERY_E_NOM_MAX_WH
        and np.isfinite(fitted_rint_scale)
        and BATTERY_RINT_SCALE_MIN <= fitted_rint_scale <= BATTERY_RINT_SCALE_MAX
        and np.isfinite(fitted_eta_charge)
        and BATTERY_ETA_CHARGE_MIN <= fitted_eta_charge <= BATTERY_ETA_CHARGE_MAX
        and np.isfinite(fitted_q_nom_ah)
        and fitted_q_nom_ah > 0.0
    )
    boundary_tolerance = 1.0e-4
    boundary_flags = {
        "e_nom_at_min": abs(fitted_e_nom_wh - BATTERY_E_NOM_MIN_WH) <= boundary_tolerance,
        "e_nom_at_max": abs(fitted_e_nom_wh - BATTERY_E_NOM_MAX_WH) <= boundary_tolerance,
        "rint_scale_at_min": abs(fitted_rint_scale - BATTERY_RINT_SCALE_MIN) <= boundary_tolerance,
        "rint_scale_at_max": abs(fitted_rint_scale - BATTERY_RINT_SCALE_MAX) <= boundary_tolerance,
        "eta_charge_at_min": abs(fitted_eta_charge - BATTERY_ETA_CHARGE_MIN) <= boundary_tolerance,
        "eta_charge_at_max": abs(fitted_eta_charge - BATTERY_ETA_CHARGE_MAX) <= boundary_tolerance,
    }
    boundary_warning = any(boundary_flags.values())
    residual_precision_gate_pass = bool(
        np.isfinite(conditional_power_nrmse)
        and conditional_power_nrmse <= 0.15
        and np.isfinite(float(voltage_bootstrap["rmse"]))
        and float(voltage_bootstrap["rmse"]) <= 1.0
    )
    terminal = fit_summary.get("terminal_anchor", {}) or {}
    active_maps = fit_summary.get("active_maps", {}) or {}
    map_shape_fit = fit_summary.get("map_shape_fit", {}) or {}
    map_rows = pd.DataFrame(
        [{"map": name, "path": path} for name, path in sorted(active_maps.items())]
    )
    shape_rows = pd.DataFrame(
        [
            {
                "map": name,
                "samples": values.get("sample_count", ""),
                "reason": values.get("reason", ""),
                "rmse_before": values.get("rmse_before", ""),
                "rmse_after": values.get("rmse_after", ""),
                "corr_min": values.get("correction_min", ""),
                "corr_max": values.get("correction_max", ""),
            }
            for name, values in sorted(map_shape_fit.items())
            if isinstance(values, dict) and "name" in values
        ]
    )
    evidence_bundle = fit_summary.get("evidence_bundle", {}) or {}
    grounded_summary_path = resolve_path(
        package_dir,
        str(evidence_bundle.get("grounded_map_summary_yaml", "") or ""),
    )
    grounded_summary = (
        yaml.safe_load(grounded_summary_path.read_text(encoding="utf-8")) or {}
        if grounded_summary_path.is_file()
        else {}
    )
    grounded_rows_data = []
    for component, values in grounded_summary.items():
        if not isinstance(values, dict):
            continue
        sources = [
            Path(str(value)).name
            for key, value in values.items()
            if str(key).startswith("source_") and isinstance(value, str)
        ]
        references = [
            f"{key}={value}"
            for key, value in values.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        ]
        grounded_rows_data.append(
            {
                "component": component,
                "source_files": "; ".join(sources),
                "method": values.get("method", ""),
                "reference_values": "; ".join(references),
            }
        )
    grounded_rows = pd.DataFrame(grounded_rows_data)
    grounded_detail_tex = "\n".join(
        "\\subsubsection*{" + latex_escape(row["component"]) + "}\n"
        + tex_kv_table(
            [
                ("source files", row["source_files"]),
                ("physical/test basis", row["method"]),
                ("reference values", row["reference_values"]),
            ]
        )
        for row in grounded_rows_data
    )
    sim_cfg = profile.get("simulation", {}) or {}
    manifest = fullsim.get("manifest", {}) or {}
    solver_rows = manifest.get("upper_solver_diagnostics", []) or []
    certificate_candidates = int(
        sum(int(row.get("discrete_grid_candidates", 0) or 0) for row in solver_rows if isinstance(row, dict))
    )
    finite_library_candidates = int(
        sum(int(row.get("finite_library_candidates", 0) or 0) for row in solver_rows if isinstance(row, dict))
    )
    selected_controls = [
        row.get("selected_x", []) for row in solver_rows if isinstance(row, dict)
    ]
    retire_distance_km = float(terminal.get("s_km", 2831.0) or 2831.0)
    distance_comparison = build_human_mpc_distance_comparison(
        replay.get("frame", pd.DataFrame()),
        fullsim.get("frame", pd.DataFrame()),
        retire_distance_km,
    )
    distance_comparison_display = distance_comparison.rename(
        columns={
            "segment_km": "segment",
            "human_moving_speed_kmh": "v_human_kmh",
            "mpc_moving_speed_kmh": "v_mpc_kmh",
            "human_reconstructed_soc": "z_human_segment",
            "mpc_no_trouble_soc": "z_mpc",
            "soc_gap_mpc_minus_human": "z_gap",
        }
    )
    if not distance_comparison_display.empty:
        distance_comparison_display = distance_comparison_display[
            ["segment", "v_human_kmh", "v_mpc_kmh", "z_human_segment", "z_mpc", "z_gap"]
        ]
    daily_progress_comparison = build_daily_progress_comparison(
        replay.get("frame", pd.DataFrame()),
        fullsim.get("frame", pd.DataFrame()),
    )
    distance_plot_path = write_human_mpc_distance_plot(
        replay.get("frame", pd.DataFrame()),
        fullsim.get("frame", pd.DataFrame()),
        distance_comparison,
        report_dir / f"{stem}_human_mpc_distance.jpg",
        retire_distance_km,
    )
    fullsim_soc_at_retire = interpolate_at_distance(
        fullsim.get("frame", pd.DataFrame()), "soc", retire_distance_km
    )
    historical_replay_soc_at_retire = interpolate_at_distance(
        replay.get("frame", pd.DataFrame()), "soc_pred", retire_distance_km
    )
    fused_human_soc_at_retire = float(
        terminal_consistency.get(
            "random_effects_soc",
            terminal.get("soc_target", float("nan")),
        )
    )
    terminal_energy_delta_wh = (
        (fullsim_soc_at_retire - fused_human_soc_at_retire)
        * float(model_cfg.get("E_nom_Wh", float("nan")))
    )
    first_material_speed_divergence_km = float("nan")
    if not distance_comparison.empty:
        material = distance_comparison.loc[
            (
                distance_comparison["mpc_moving_speed_kmh"]
                - distance_comparison["human_moving_speed_kmh"]
            ).abs()
            >= 3.0
        ]
        if not material.empty:
            first_material_speed_divergence_km = float(material.iloc[0]["end_s_km"])

    counterfactual_path = package_dir / "data" / "identification" / "evidence" / "counterfactual_no_trouble.yaml"
    counterfactual = (
        yaml.safe_load(counterfactual_path.read_text(encoding="utf-8")) or {}
        if counterfactual_path.exists()
        else {}
    )
    counterfactual_scenario = counterfactual.get("scenario", {}) or {}
    counterfactual_analysis = counterfactual_scenario.get("derived_team_analysis", {}) or {}
    distance_plot_md = (
        f"![実走行再構成とMPCの距離別比較]({distance_plot_path.name})"
        if distance_plot_path is not None
        else "比較グラフはfullsim未実行のため未生成。"
    )
    distance_plot_tex = (
        "\\begin{figure}[htbp]\\centering\n"
        f"\\includegraphics[width=0.96\\linewidth]{{\\detokenize{{{distance_plot_path.name}}}}}\n"
        "\\caption{実走行再構成とトラブルなしMPCの距離別SoC・移動速度比較}\n"
        "\\end{figure}"
        if distance_plot_path is not None
        else "fullsim未実行のため比較図は未生成である。"
    )
    manifest_out_csv = rel_display(resolve_path(package_dir, manifest.get("out_csv", "")), report_dir) if manifest.get("out_csv") else ""
    manifest_plan_csv = rel_display(resolve_path(package_dir, manifest.get("plan_csv", "")), report_dir) if manifest.get("plan_csv") else ""

    acceptance_yaml = report_dir / f"{stem}_model_acceptance.yaml"
    high_precision_claim_allowed = bool(
        terminal_consistency.get("high_precision_gate_pass", False)
        and physical_parameter_gate_pass
        and residual_precision_gate_pass
        and not boundary_warning
    )
    with acceptance_yaml.open("w", encoding="utf-8", newline="\n") as stream:
        yaml.safe_dump(
            {
                "profile": rel_display(profile_yaml, package_dir),
                "fit_summary": rel_display(fit_summary_path, package_dir),
                "conditional_replay": {
                    "power_rmse_w": power_bootstrap["rmse"],
                    "power_rmse_day_block_bootstrap_ci95_w": [
                        power_bootstrap["ci95_min"],
                        power_bootstrap["ci95_max"],
                    ],
                    "power_nrmse_by_observed_rms": conditional_power_nrmse,
                    "voltage_rmse_v": voltage_bootstrap["rmse"],
                    "voltage_rmse_day_block_bootstrap_ci95_v": [
                        voltage_bootstrap["ci95_min"],
                        voltage_bootstrap["ci95_max"],
                    ],
                    "day_blocks": power_bootstrap["day_blocks"],
                    "bootstrap_draws": power_bootstrap["draws"],
                },
                "terminal_evidence": terminal_consistency,
                "physical_constraints": {
                    "E_nom_Wh": [BATTERY_E_NOM_MIN_WH, BATTERY_E_NOM_MAX_WH],
                    "rint_scale": [BATTERY_RINT_SCALE_MIN, BATTERY_RINT_SCALE_MAX],
                    "eta_charge": [BATTERY_ETA_CHARGE_MIN, BATTERY_ETA_CHARGE_MAX],
                    "gate_pass": physical_parameter_gate_pass,
                    "boundary_flags": boundary_flags,
                    "boundary_warning": boundary_warning,
                },
                "battery_dynamic_model": battery_dynamic,
                "residual_precision_gate": {
                    "power_nrmse_max": 0.15,
                    "voltage_rmse_max_v": 1.0,
                    "gate_pass": residual_precision_gate_pass,
                },
                "fullsim_adoption_gate_pass": manifest.get("adoption_gate_pass", False),
                "high_precision_claim_allowed": high_precision_claim_allowed,
            },
            stream,
            sort_keys=False,
            allow_unicode=True,
        )

    md = f"""# {profile_yaml.stem} 同定・全行程シミュレーション統合報告書

## 使用成果物
- profile: `{rel_display(profile_yaml, package_dir)}`
- fit summary: `{rel_display(fit_summary_path, package_dir)}`
- replay validation: `{rel_display(replay["replay_csv"], package_dir)}`
- terminal consistency: `{rel_display(terminal_consistency_path if terminal_consistency_path.exists() else None, package_dir)}`
- fullsim manifest: `{rel_display(fullsim.get("manifest_path"), package_dir)}`

## 採用係数
- operational_soc0: `{sim_cfg.get("soc0", float("nan")):.6f}`
- fitted_latent_soc0: `{battery.get("soc0", float("nan")):.6f}`
- vehicle_mass_kg: `{model_cfg.get("m", float("nan")):.3f}`
- panel_gain: `{pv.get("panel_gain", float("nan")):.6f}`
- tcell_gain_c_per_wm2: `{pv.get("tcell_gain_c_per_wm2", float("nan")):.6f}`
- solar_measurement_gain_to_pack: `{float(solar_calibration.get("gain_to_pack", model_cfg.get("solar_measurement_gain_to_pack", 1.0))):.8f}`
- solar_measurement_calibration_samples: `{int(solar_calibration.get("sample_count", 0) or 0)}`
- solar_measurement_free_intercept_w: `{float(solar_calibration.get("free_intercept_w", float("nan"))):.6f}`
- solar_measurement_daily_gain_std: `{float(solar_calibration.get("daily_gain_std", float("nan"))):.8f}`
- soc0: `{battery.get("soc0", float("nan")):.6f}`
- E_nom_Wh: `{battery.get("e_nom_wh", float("nan")):.3f}`
- Q_nom_Ah: `{fitted_q_nom_ah:.6f}`
- rint_scale: `{battery.get("rint_scale", float("nan")):.6f}`
- r_line_ohm: `{battery.get("r_line_ohm", float("nan")):.6f}`
- r_polarization_ohm: `{float(battery_dynamic.get("r_polarization_ohm", 0.0)):.6f}`
- polarization_tau_sec: `{float(battery_dynamic.get("tau_sec", 60.0)):.6f}`
- CdA: `{motion.get("cda", float("nan")):.6f}`
- Crr: `{motion.get("crr", float("nan")):.6f}`
- P_aux_w: `{motion.get("p_aux_w", float("nan")):.3f}`
- drive_eff_scale: `{motion.get("drive_eff_scale", float("nan")):.6f}`
- headwind_gain: `{motion.get("headwind_gain", float("nan")):.6f}`
- V_max_v: `{float(model_cfg.get("V_max", float("nan"))):.3f}`

### 物理制約・境界診断
- E_nom_Wh bounds: `[{BATTERY_E_NOM_MIN_WH:.1f}, {BATTERY_E_NOM_MAX_WH:.1f}]`
- rint_scale bounds: `[{BATTERY_RINT_SCALE_MIN:.3f}, {BATTERY_RINT_SCALE_MAX:.3f}]`
- eta_charge bounds: `[{BATTERY_ETA_CHARGE_MIN:.3f}, {BATTERY_ETA_CHARGE_MAX:.3f}]`
- physical_parameter_gate_pass: `{physical_parameter_gate_pass}`
- boundary_flags: `{boundary_flags}`
- residual_precision_gate_pass: `{residual_precision_gate_pass}`
- high_precision_claim_allowed: `{high_precision_claim_allowed}`

## 同定モデルと数式

車輪機械出力とpack電力は次で評価する。

`P_mech = (0.5*rho*CdA*(v+w_head)^2 + m*g*Crr*cos(theta) + m*g*sin(theta))*v`

`P_pack = P_mech/(eta_drive*eta_inv) + P_aux - P_pv`

`P_pv = eta_panel(G,T_cell)*eta_mppt(G,T_cell)*A_pv*G`

停止時の独立DC bus校正は
`P_batt = P_aux - g_solar*P_solar_raw + epsilon`を有界Huber M推定で解く。
WiFi送信側はraw `solar_power_w`を送り、受信側が`g_solar`を一度だけ適用する。
YATAの電圧上限は`25*4.35 = 108.75 V`で、OCV map最大値はこれを超えてはならない。

電池端子は `V = OCV(z) - I*(k_R*R_map(T,z)+R_line) - V_p`、
分極枝は `dV_p/dt = (R_p*I - V_p)/tau_p`、状態は
`z[k+1] = z[k] - eta(I)*I*dt/(3600*Q_nom)` とする。
係数とmap補正は、物理boundと製品・試験由来base mapを保持しながら、
`theta_hat = argmin sum rho_Huber(y-y_hat(theta))/sigma^2 + prior(theta)`
で推定する。車体係数の検証には実測PVを条件として用い、天候・PVモデルの
誤差をCdA、Crr、駆動効率へ吸収させない。

2831 km終端SoCは独立に、(1) `z_V = OCV^-1(V+I*R)`、
(2) `z_E = 1335/3011`、(3) `z_Q = z_start - integral(eta(I) I dt)/(3600 Q_nom)`
から算出する。三値が受入幅内で一致しない限り、終端一点の一致を高精度判定に使わない。

## 実走行再現検証
- 検証規約: 接頭辞なしの指標は実測PVで車体係数を検証し、`end_to_end_*` は天候・PVモデル誤差も含む
- power_rmse_clean_w: `{metrics.get("power_rmse_clean_w", float("nan")):.3f}`
- voltage_rmse_clean_v: `{metrics.get("voltage_rmse_clean_v", float("nan")):.3f}`
- final_soc_pred: `{metrics.get("final_soc_pred", float("nan")):.6f}`
- retire_anchor_soc_obs: `{metrics.get("retire_anchor_soc_obs", float("nan")):.6f}`
- retire_anchor_soc_pred: `{metrics.get("retire_anchor_soc_pred", float("nan")):.6f}`
- retire_anchor_soc_error: `{metrics.get("retire_anchor_soc_error", float("nan")):.6f}`
- end_to_end_power_rmse_clean_w: `{metrics.get("end_to_end_power_rmse_clean_w", float("nan")):.3f}`
- end_to_end_voltage_rmse_clean_v: `{metrics.get("end_to_end_voltage_rmse_clean_v", float("nan")):.3f}`

## モデル受入判定
- conditional power RMSE day-block bootstrap 95% CI: `[{power_bootstrap["ci95_min"]:.3f}, {power_bootstrap["ci95_max"]:.3f}] W`
- conditional power NRMSE / observed power RMS: `{conditional_power_nrmse:.6f}`
- conditional voltage RMSE day-block bootstrap 95% CI: `[{voltage_bootstrap["ci95_min"]:.3f}, {voltage_bootstrap["ci95_max"]:.3f}] V`
- bootstrap day blocks / draws: `{power_bootstrap["day_blocks"]} / {power_bootstrap["draws"]}`
- high_precision_gate_pass: `{terminal_consistency.get("high_precision_gate_pass", "not evaluated")}`
- terminal_soc_evidence_interval: `[{terminal_consistency.get("evidence_interval_min", float("nan")):.6f}, {terminal_consistency.get("evidence_interval_max", float("nan")):.6f}]`
- terminal_soc_evidence_spread_percentage_points: `{terminal_consistency.get("spread_percentage_points", float("nan")):.3f}`
- random_effects_soc: `{terminal_consistency.get("random_effects_soc", float("nan")):.6f}`
- random_effects_ci95: `[{terminal_consistency.get("random_effects_ci95_min", float("nan")):.6f}, {terminal_consistency.get("random_effects_ci95_max", float("nan")):.6f}]`
- heterogeneity_I2_pct: `{terminal_consistency.get("heterogeneity_i2_pct", float("nan")):.3f}`
- fusion_caution: {terminal_consistency.get("fusion_caution", "not evaluated")}
- interpretation: {terminal_consistency.get("interpretation", "terminal consistency evidence was not available")}

条件付きreplayは実測PVを用いて車体側係数を分離検証する。end-to-end replayは
天候・PV予測誤差も含む。独立した終端SoC根拠が相互に矛盾している場合、
end-to-end終端誤差が小さいことだけではモデル高精度の証明にならない。

## 2831 km終端アンカー
- s_km: `{terminal.get("s_km", float("nan"))}`
- time_utc: `{terminal.get("time_utc", "")}`
- voltage_v: `{terminal.get("voltage_v", float("nan"))}`
- current_a: `{terminal.get("current_a", float("nan"))}`
- temp_c: `{terminal.get("temp_c", float("nan"))}`
- soc_target: `{terminal.get("soc_target", float("nan"))}`

## 人間実走行とトラブルなしMPCの比較

チーム資料の「コースアウトだけを除く」単純外挿は、2831 km時点の残量
`{counterfactual_analysis.get("remaining_energy_estimate_wh", float("nan"))} Wh` と
その後の発電 `{counterfactual_analysis.get("extra_generation_assumption_wh", float("nan"))} Wh` から
`{counterfactual_analysis.get("simple_post_retire_reach_estimate_km", float("nan"))} km` を見込む。一方、本fullsimは
Day 2のパネル損失、Day 4/5の充電遅延、Day 6の70分停止、最後のコースアウトを
すべて除いた反実仮想であり、3026.9 kmまでMPCが速度を最適化する。両者は同じ条件ではない。

- historical replay reconstructed SoC at 2831 km: `{historical_replay_soc_at_retire:.6f}`
- independent evidence random-effects SoC at 2831 km: `{fused_human_soc_at_retire:.6f}`
- no-trouble MPC SoC at 2831 km: `{fullsim_soc_at_retire:.6f}`
- MPC minus fused-human usable-energy equivalent: `{terminal_energy_delta_wh:.3f} Wh`
- first 3 km/h moving-speed divergence checkpoint: `{first_material_speed_divergence_km} km`

`human_reconstructed_soc` は独立BMS測定値ではなく、実速度・実電力・実停止列へ同定モデルを適用した再構成値である。
さらに日／セグメント開始時に観測アンカーへ再初期化されるため、長距離の連続coulomb countとはみなさない。
終端のエネルギー差はこの列ではなく、独立3チャネルのrandom-effects融合値を基準に算出する。

{md_table(distance_comparison_display)}

### 日別到達距離
{md_table(daily_progress_comparison)}

{distance_plot_md}

## 使用中マップ
{md_table(map_rows)}

### Base mapの製品・試験根拠
- grounded provenance YAML: `{rel_display(grounded_summary_path if grounded_summary_path.is_file() else None, package_dir)}`

{md_table(grounded_rows)}

### MLE形状補正
- adoption status: `{map_shape_fit.get("adoption_status", "not recorded")}`
- baseline score: `{map_shape_fit.get("baseline_score", float("nan"))}`
- adopted score: `{map_shape_fit.get("adopted_score", float("nan"))}`

{md_table(shape_rows)}

## 日別replay残差
{md_table(replay["daily"])}

## 天候・70 km/h負荷の整合確認

日別天候は独立archive GHIを使うend-to-end replayから集計する。70 km/h負荷は
実測PVを条件としたvehicle replayで、`gross vehicle power = net battery power + PV power`
として再構成するため、天候誤差を車両負荷へ混入させない。

{md_table(weather_daily)}

{md_table(cruise_70kmh_rows)}

## 電力残差最大点
{md_table(replay["worst_power"])}

## 電圧残差最大点
{md_table(replay["worst_voltage"])}

## 予測器・実行器同期
- 充放電状態式は両者とも `model.soc_step()` を使用し、充電効率を同一に適用する。
- 時変向かい風は weather grid を正とし、route 値は欠損時だけ fallback とする。
- 制御停止、走行時間窓、翌朝開始、適応ホライズン距離境界で両者を同じ時刻・地点に分割する。
- 満充電超過は PV curtailment として SoC 上限へ固定し、未完走・下限違反・終端帯違反を辞書式に実行可能解より劣後させる。
- `adoption_gate_pass` は完走、終端帯、予測制約、solver、有限ライブラリ全列挙、予測実行同期を同時に要求する。

## 全行程シミュレーション結果
- finish_reached: `{manifest.get("finish_reached", "")}`
- final_distance_km: `{manifest.get("final_distance_km", float("nan"))}`
- race_progress_pct: `{manifest.get("race_progress_pct", float("nan"))}`
- final_soc: `{manifest.get("final_soc", float("nan"))}`
- min_soc: `{manifest.get("min_soc", float("nan"))}`
- avg_speed_kmh: `{manifest.get("avg_speed_kmh", float("nan"))}`
- elapsed_hours: `{manifest.get("elapsed_hours", float("nan"))}`
- terminal_soc_target_met: `{manifest.get("terminal_soc_target_met", "")}`
- terminal_usable_energy_wh: `{manifest.get("terminal_usable_energy_wh", float("nan"))}`
- upper_solver_all_success: `{manifest.get("upper_solver_all_success", "")}`
- finite_grid_all_proven: `{manifest.get("upper_discrete_global_all_proven", "")}`
- finite_library_all_proven: `{manifest.get("upper_finite_library_global_all_proven", "")}`
- finite_grid_candidates_evaluated: `{certificate_candidates}`
- finite_library_candidates_evaluated: `{finite_library_candidates}`
- finite_grid_nonfinite_evaluations: `{manifest.get("upper_finite_grid_nonfinite_total", "")}`
- selected_speed_controls_kmh: `{selected_controls}`
- predicted_terminal_soc: `{manifest.get("upper_predicted_terminal_soc", float("nan"))}`
- prediction_execution_terminal_soc_error: `{manifest.get("prediction_execution_terminal_soc_error", float("nan"))}`
- prediction_execution_sync_gate_pass: `{manifest.get("prediction_execution_sync_gate_pass", "")}`
- adoption_gate_pass: `{manifest.get("adoption_gate_pass", "")}`
- certificate_scope: `{manifest.get("upper_global_certificate_scope", "")}`
- cpu_sec: `{manifest.get("cpu_sec", float("nan"))}`
- out_csv: `{manifest_out_csv}`
- plan_csv: `{manifest_plan_csv}`

## 日別全行程シミュレーション
{md_table(fullsim["daily"])}

## 1 Hz detail CSV契約

`outer_step_actual_dt_sec`はイベント境界で短くなり得るが、下位指令周期
`step_dt_sec`は通常1秒で、境界を正確に積分する最後の行だけ1秒未満になる。
必須列には速度3系列、発電・車両・pack電力、電圧・電流・抵抗・損失、
空力・転がり・勾配・慣性、全主要係数とmap pathを含める。

{md_table(detail_audit_rows)}

## 根拠文献
- Rawlings, Mayne, Diehl, *Model Predictive Control: Theory, Computation, and Design*, 2nd ed., 2020.
- Huber, "Robust Estimation of a Location Parameter," *Annals of Mathematical Statistics*, 1964, doi:10.1214/aoms/1177703732.
- Byrd, Lu, Nocedal, Zhu, "A Limited Memory Algorithm for Bound Constrained Optimization," *SIAM J. Sci. Comput.*, 1995, doi:10.1137/0916069.
- de Boer et al., "A Tutorial on the Cross-Entropy Method," *Annals of Operations Research*, 2005, doi:10.1007/s10479-005-5724-z.
- DerSimonian and Laird, "Meta-analysis in clinical trials," *Controlled Clinical Trials*, 1986, doi:10.1016/0197-2456(86)90046-2.
- Ljung, *System Identification: Theory for the User*, 2nd ed., 1999.
- Plett, *Battery Management Systems, Vol. I: Battery Modeling*, 2015.
- Endres, Sandrock, Focke, "A simplicial homology algorithm for Lipschitz optimisation," *Journal of Global Optimization*, 2018, doi:10.1007/s10898-018-0645-y.
"""
    md_path.write_text(md, encoding="utf-8", newline="\n")

    model_equations_tex = r"""
\section{同定モデルと導出式}
車輪機械出力とpack電力は
\[
P_{\mathrm{mech}}=\left\{\frac12\rho C_dA(v+w_{\mathrm{head}})^2
+mgC_{rr}\cos\theta+mg\sin\theta\right\}v,
\]
\[
P_{\mathrm{pack}}=\frac{P_{\mathrm{mech}}}{\eta_{\mathrm{drive}}\eta_{\mathrm{inv}}}
+P_{\mathrm{aux}}-P_{\mathrm{pv}},\qquad
P_{\mathrm{pv}}=\eta_{\mathrm{panel}}\eta_{\mathrm{mppt}}A_{\mathrm{pv}}G
\]
である。停止時の独立DC bus校正は
\[
P_{\mathrm{batt}}=P_{\mathrm{aux}}-g_{\mathrm{solar}}
P_{\mathrm{solar,raw}}+\varepsilon
\]
を有界Huber M推定で解く。WiFi送信側はraw値を送り、受信側が
$g_{\mathrm{solar}}$を一度だけ適用する。YATAの電圧上限は
$25\times4.35=108.75$ Vであり、OCV map最大値はこれを超えてはならない。
電池端子と状態遷移は
\[
V=OCV(z)-I\left\{k_RR_{\mathrm{map}}(T,z)+R_{\mathrm{line}}\right\}-V_p,
\qquad
\dot V_p=\frac{R_pI-V_p}{\tau_p},
\qquad
z_{k+1}=z_k-\eta(I_k)
\frac{I_k\Delta t_k}{3600Q_{\mathrm{nom}}}
\]
とする。製品・試験由来base mapと物理boundを固定し、Huber尤度と事前項を
\[
\widehat\theta=\arg\min_\theta
\sum_k\frac{\rho_{\mathrm{Huber}}(y_k-\widehat y_k(\theta))}{\sigma^2}
+J_{\mathrm{prior}}(\theta)
\]
で最小化する。車体係数の条件付き検証には実測PVを使い、天候・PVモデル誤差を
$C_dA,C_{rr}$、駆動効率へ吸収させない。

2831 km終端SoCは独立に
\[
z_V=OCV^{-1}(V+IR),\qquad
z_E=\frac{1335}{3011},\qquad
z_Q=z_{\mathrm{start}}-\frac{\int \eta(I)I\,dt}{3600Q_{\mathrm{nom}}}
\]
から求める。三根拠が受入幅内で一致しない限り、終端一点の一致を高精度判定に使わない。
三根拠の中心表示にはDerSimonian--Laird random-effects modelを使う。

\[
\widehat z=\frac{\sum_i w_i z_i}{\sum_i w_i},\qquad
w_i=\frac{1}{\sigma_i^2+\tau^2},\qquad
\operatorname{SE}(\widehat z)=\left(\sum_iw_i\right)^{-1/2}.
\]
ここで\(\tau^2\)はチャネル間分散である。融合平均は相互矛盾を隠す真値ではなく、
元チャネルのmax--min幅によるhigh-precision gateを置き換えない。
"""

    synchronization_tex = r"""
\section{予測器・実行器同期と採用条件}
上位予測とoffline実行は同じ充放電状態式
\(z^+=\operatorname{clip}(z-\eta(I)I\Delta t/(3600Q_{nom}))\)
を使う。時変向かい風はweather gridを正とし、route列は欠損時だけfallbackとする。
制御停止、drive-window終端、翌朝開始、適応距離horizon境界で双方の積分を分割する。
満充電超過はPV curtailmentとして上限に固定する。

最速modeの比較はsoft weightの加重和だけに依存させず、
\[
J(u)=
\begin{cases}
t_{finish}(u),&u\in\mathcal F,\\
10^{18}+10^{15}v(u)+t(u),&u\notin\mathcal F,
\end{cases}
\]
とする。ここで\(\mathcal F\)は全行程到達、全時刻SoC下限、終端SoC帯を
満たす候補集合、\(v(u)\)は制約違反量である。したがって実行不可能な高速候補が
soft penaltyの係数調整で実行可能候補を追い越すことはない。

採用gateは、完走、終端帯、予測制約、solver成功、宣言した有限候補集合の全列挙、
予測・実行終端SoC差の許容値内を同時に要求する。有限集合内の最良性は証明できるが、
連続速度空間全体の大域最適性を意味しない。
"""

    tex = f"""
\\documentclass[a4paper,11pt]{{article}}
\\usepackage[top=18mm,bottom=22mm,left=18mm,right=18mm]{{geometry}}
\\usepackage{{fontspec}}
\\usepackage{{xeCJK}}
\\setmainfont{{Times New Roman}}
\\setCJKmainfont{{Yu Gothic}}
\\usepackage{{booktabs}}
\\usepackage{{longtable}}
\\usepackage{{graphicx}}
\\usepackage{{amsmath}}
\\usepackage[unicode]{{hyperref}}
\\title{{{latex_escape(profile_yaml.stem)}\\\\同定・全行程シミュレーション統合報告書}}
\\author{{solar\\_ws0129-main}}
\\date{{}}
\\begin{{document}}
\\maketitle

\\section{{使用成果物}}
{tex_kv_table([
    ("profile", rel_display(profile_yaml, report_dir)),
    ("fit summary", rel_display(fit_summary_path, report_dir)),
    ("replay validation", rel_display(replay["replay_csv"], report_dir)),
    ("terminal consistency", rel_display(terminal_consistency_path if terminal_consistency_path.exists() else None, report_dir)),
    ("fullsim manifest", rel_display(fullsim.get("manifest_path"), report_dir)),
])}

\\section{{採用係数}}
{tex_kv_table([
    ("operational soc0", f"{sim_cfg.get('soc0', float('nan')):.6f}"),
    ("fitted latent soc0", f"{battery.get('soc0', float('nan')):.6f}"),
    ("vehicle mass [kg]", f"{model_cfg.get('m', float('nan')):.3f}"),
    ("panel gain", f"{pv.get('panel_gain', float('nan')):.6f}"),
    ("tcell gain [C/(W/m^2)]", f"{pv.get('tcell_gain_c_per_wm2', float('nan')):.6f}"),
    ("solar measurement gain to pack", f"{float(solar_calibration.get('gain_to_pack', model_cfg.get('solar_measurement_gain_to_pack', 1.0))):.8f}"),
    ("solar calibration samples", int(solar_calibration.get("sample_count", 0) or 0)),
    ("solar free intercept [W]", f"{float(solar_calibration.get('free_intercept_w', float('nan'))):.6f}"),
    ("solar daily gain std", f"{float(solar_calibration.get('daily_gain_std', float('nan'))):.8f}"),
    ("soc0", f"{battery.get('soc0', float('nan')):.6f}"),
    ("E_nom [Wh]", f"{battery.get('e_nom_wh', float('nan')):.3f}"),
    ("Q_nom [Ah]", f"{fitted_q_nom_ah:.6f}"),
    ("rint scale", f"{battery.get('rint_scale', float('nan')):.6f}"),
    ("r_line [ohm]", f"{battery.get('r_line_ohm', float('nan')):.6f}"),
    ("R_polarization [ohm]", f"{float(battery_dynamic.get('r_polarization_ohm', 0.0)):.6f}"),
    ("polarization tau [s]", f"{float(battery_dynamic.get('tau_sec', 60.0)):.6f}"),
    ("CdA", f"{motion.get('cda', float('nan')):.6f}"),
    ("Crr", f"{motion.get('crr', float('nan')):.6f}"),
    ("P_aux [W]", f"{motion.get('p_aux_w', float('nan')):.3f}"),
    ("drive efficiency scale", f"{motion.get('drive_eff_scale', float('nan')):.6f}"),
    ("headwind gain", f"{motion.get('headwind_gain', float('nan')):.6f}"),
    ("V_max [V]", f"{float(model_cfg.get('V_max', float('nan'))):.3f}"),
    ("E_nom bounds [Wh]", f"[{BATTERY_E_NOM_MIN_WH:.1f}, {BATTERY_E_NOM_MAX_WH:.1f}]"),
    ("rint scale bounds", f"[{BATTERY_RINT_SCALE_MIN:.3f}, {BATTERY_RINT_SCALE_MAX:.3f}]"),
    ("eta charge bounds", f"[{BATTERY_ETA_CHARGE_MIN:.3f}, {BATTERY_ETA_CHARGE_MAX:.3f}]"),
    ("physical parameter gate pass", physical_parameter_gate_pass),
    ("boundary warning", boundary_warning),
    ("residual precision gate pass", residual_precision_gate_pass),
    ("high precision claim allowed", high_precision_claim_allowed),
])}

\\section{{モデル受入判定}}
条件付きreplayは実測PVを用いて車体側係数を分離検証する。
end-to-end replayは天候・PV予測誤差も含む。独立した終端SoC根拠が
相互に矛盾している場合、end-to-end終端誤差が小さいことだけでは
モデル高精度の証明にならない。

{tex_kv_table([
    ("power RMSE bootstrap 95% CI [W]", f"[{power_bootstrap['ci95_min']:.3f}, {power_bootstrap['ci95_max']:.3f}]"),
    ("power NRMSE / observed RMS", f"{conditional_power_nrmse:.6f}"),
    ("voltage RMSE bootstrap 95% CI [V]", f"[{voltage_bootstrap['ci95_min']:.3f}, {voltage_bootstrap['ci95_max']:.3f}]"),
    ("day blocks / bootstrap draws", f"{power_bootstrap['day_blocks']} / {power_bootstrap['draws']}"),
    ("high-precision gate pass", terminal_consistency.get("high_precision_gate_pass", "not evaluated")),
    ("terminal SoC evidence min", terminal_consistency.get("evidence_interval_min", "")),
    ("terminal SoC evidence max", terminal_consistency.get("evidence_interval_max", "")),
    ("evidence spread [percentage points]", terminal_consistency.get("spread_percentage_points", "")),
    ("random-effects fused SoC", terminal_consistency.get("random_effects_soc", "")),
    ("random-effects 95% CI min", terminal_consistency.get("random_effects_ci95_min", "")),
    ("random-effects 95% CI max", terminal_consistency.get("random_effects_ci95_max", "")),
    ("heterogeneity I2 [%]", terminal_consistency.get("heterogeneity_i2_pct", "")),
    ("fusion caution", terminal_consistency.get("fusion_caution", "")),
    ("interpretation", terminal_consistency.get("interpretation", "terminal consistency evidence was not available")),
])}

{model_equations_tex}
{synchronization_tex}

\\section{{実走行再現検証}}
接頭辞なしの指標は実測PVで車体モデルを検証する。end-to-end指標は
天候・PVモデル誤差も含むため、両誤差源を分離して報告する。

{tex_kv_table([
    ("power RMSE clean [W]", f"{metrics.get('power_rmse_clean_w', float('nan')):.3f}"),
    ("voltage RMSE clean [V]", f"{metrics.get('voltage_rmse_clean_v', float('nan')):.3f}"),
    ("final SoC prediction", f"{metrics.get('final_soc_pred', float('nan')):.6f}"),
    ("retire anchor observed SoC", f"{metrics.get('retire_anchor_soc_obs', float('nan')):.6f}"),
    ("retire anchor predicted SoC", f"{metrics.get('retire_anchor_soc_pred', float('nan')):.6f}"),
    ("retire anchor SoC error", f"{metrics.get('retire_anchor_soc_error', float('nan')):.6f}"),
    ("end-to-end power RMSE clean [W]", f"{metrics.get('end_to_end_power_rmse_clean_w', float('nan')):.3f}"),
    ("end-to-end voltage RMSE clean [V]", f"{metrics.get('end_to_end_voltage_rmse_clean_v', float('nan')):.3f}"),
])}

\\section{{2831 km終端アンカー}}
{tex_kv_table([
    ("s_km", terminal.get("s_km", "")),
    ("time_utc", terminal.get("time_utc", "")),
    ("voltage_v", terminal.get("voltage_v", "")),
    ("current_a", terminal.get("current_a", "")),
    ("temp_c", terminal.get("temp_c", "")),
    ("soc_target", terminal.get("soc_target", "")),
])}

\\section{{人間実走行とトラブルなしMPCの比較}}
チーム資料のコースアウトだけを除く単純外挿は、2831 km時点の残量
{counterfactual_analysis.get("remaining_energy_estimate_wh", "")} Whと、その後の発電
{counterfactual_analysis.get("extra_generation_assumption_wh", "")} Whから
{counterfactual_analysis.get("simple_post_retire_reach_estimate_km", "")} kmを見込む。
本fullsimはDay 2のパネル損失、Day 4/5の充電遅延、Day 6の70分停止、
最後のコースアウトをすべて除き、3026.9 kmまでMPCで速度を最適化するため、
単純外挿とは異なる反実仮想である。

{tex_kv_table([
    ("historical reconstructed SoC at 2831 km", f"{historical_replay_soc_at_retire:.6f}"),
    ("random-effects evidence SoC at 2831 km", f"{fused_human_soc_at_retire:.6f}"),
    ("no-trouble MPC SoC at 2831 km", f"{fullsim_soc_at_retire:.6f}"),
    ("MPC minus fused-human energy equivalent [Wh]", f"{terminal_energy_delta_wh:.3f}"),
    ("first 3 km/h moving-speed divergence [km]", first_material_speed_divergence_km),
])}

human reconstructed SoCは独立BMS測定ではなく、実速度・実電力・実停止列へ
同定モデルを適用した値である。日・セグメント開始時に観測アンカーへ
再初期化されるため長距離の連続coulomb countとはみなさず、終端のエネルギー差は
独立3チャネルのrandom-effects融合値を基準に算出する。

{tex_df_table(distance_comparison_display, "Historical operation and no-trouble MPC by distance")}
{tex_df_table(daily_progress_comparison, "Daily progress comparison")}
{distance_plot_tex}

\\section{{使用中マップ}}
{tex_df_table(map_rows, "Maps adopted by the reported profile")}

\\subsection{{Base mapの製品・試験根拠}}
{tex_kv_table([("grounded provenance YAML", rel_display(grounded_summary_path if grounded_summary_path.is_file() else None, report_dir))])}
{grounded_detail_tex}

\\subsection{{MLE形状補正}}
{tex_kv_table([
    ("adoption status", map_shape_fit.get("adoption_status", "not recorded")),
    ("baseline score", map_shape_fit.get("baseline_score", "")),
    ("adopted score", map_shape_fit.get("adopted_score", "")),
])}
{tex_df_table(shape_rows, "Map-shape correction diagnostics")}

\\section{{Replay残差診断}}
{tex_df_table(replay["daily"], "Residual by day")}
\\subsection{{天候・70 km/h負荷の整合確認}}
日別天候は独立archive GHIを使うend-to-end replayから集計する。
70 km/h負荷は実測PVを条件としたvehicle replayで
$P_{{vehicle,gross}}=P_{{battery,net}}+P_{{PV}}$ として再構成する。
{tex_df_table(weather_daily, "Daily archive weather and PV")}
{tex_df_table(cruise_70kmh_rows, "Gross vehicle load at 68--72 km/h")}
{tex_df_table(replay["worst_power"], "Worst power residual points")}
{tex_df_table(replay["worst_voltage"], "Worst voltage residual points")}

\\section{{全行程シミュレーション結果}}
{tex_kv_table([
    ("finish reached", manifest.get("finish_reached", "")),
    ("final distance [km]", manifest.get("final_distance_km", "")),
    ("race progress [%]", manifest.get("race_progress_pct", "")),
    ("final SoC", manifest.get("final_soc", "")),
    ("min SoC", manifest.get("min_soc", "")),
    ("avg speed [km/h]", manifest.get("avg_speed_kmh", "")),
    ("elapsed hours", manifest.get("elapsed_hours", "")),
    ("terminal SoC target met", manifest.get("terminal_soc_target_met", "")),
    ("terminal usable energy [Wh]", manifest.get("terminal_usable_energy_wh", "")),
    ("upper solver all success", manifest.get("upper_solver_all_success", "")),
    ("finite-grid all proven", manifest.get("upper_discrete_global_all_proven", "")),
    ("finite-library all proven", manifest.get("upper_finite_library_global_all_proven", "")),
    ("finite-grid candidates evaluated", certificate_candidates),
    ("finite-library candidates evaluated", finite_library_candidates),
    ("finite-grid nonfinite evaluations", manifest.get("upper_finite_grid_nonfinite_total", "")),
    ("selected speed controls [km/h]", selected_controls),
    ("predicted terminal SoC", manifest.get("upper_predicted_terminal_soc", "")),
    ("prediction-execution terminal SoC error", manifest.get("prediction_execution_terminal_soc_error", "")),
    ("prediction-execution sync gate pass", manifest.get("prediction_execution_sync_gate_pass", "")),
    ("adoption gate pass", manifest.get("adoption_gate_pass", "")),
    ("certificate scope", manifest.get("upper_global_certificate_scope", "")),
    ("cpu sec", manifest.get("cpu_sec", "")),
    ("out_csv", manifest_out_csv),
    ("plan_csv", manifest_plan_csv),
])}
{tex_df_table(fullsim["daily"], "Full simulation by day")}

\\subsection{{1 Hz detail CSV契約}}
\\texttt{{outer\\_step\\_actual\\_dt\\_sec}}はイベント境界で短くなり得るが、
下位指令周期\\texttt{{step\\_dt\\_sec}}は通常1秒で、境界直前だけ1秒未満になる。
必須列には速度3系列、発電・車両・pack電力、電圧・電流・抵抗・損失、
空力・転がり・勾配・慣性、主要係数とmap pathを含める。
{tex_df_table(detail_audit_rows, "One-hertz detail CSV contract")}

\\section{{根拠文献}}
\\begin{{thebibliography}}{{9}}
\\bibitem{{rawlings}} J. B. Rawlings, D. Q. Mayne, M. Diehl,
\\textit{{Model Predictive Control: Theory, Computation, and Design}}, 2nd ed., 2020.
\\bibitem{{huber}} P. J. Huber, Robust Estimation of a Location Parameter,
\\textit{{Annals of Mathematical Statistics}}, 1964, doi:10.1214/aoms/1177703732.
\\bibitem{{lbfgsb}} R. H. Byrd, P. Lu, J. Nocedal, C. Zhu,
A Limited Memory Algorithm for Bound Constrained Optimization,
\\textit{{SIAM Journal on Scientific Computing}}, 1995, doi:10.1137/0916069.
\\bibitem{{cem}} P.-T. de Boer et al., A Tutorial on the Cross-Entropy Method,
\\textit{{Annals of Operations Research}}, 2005, doi:10.1007/s10479-005-5724-z.
\\bibitem{{dl}} R. DerSimonian, N. Laird, Meta-analysis in clinical trials,
\\textit{{Controlled Clinical Trials}}, 1986, doi:10.1016/0197-2456(86)90046-2.
\\bibitem{{ljung}} L. Ljung, \\textit{{System Identification: Theory for the User}}, 2nd ed., 1999.
\\bibitem{{plett}} G. L. Plett, \\textit{{Battery Management Systems, Vol. I: Battery Modeling}}, 2015.
\\bibitem{{shgo}} S. C. Endres, C. Sandrock, W. W. Focke,
A simplicial homology algorithm for Lipschitz optimisation,
\\textit{{Journal of Global Optimization}}, 2018, doi:10.1007/s10898-018-0645-y.
\\end{{thebibliography}}

\\end{{document}}
"""
    tex_path.write_text(textwrap.dedent(tex).strip() + "\n", encoding="utf-8", newline="\n")
    compile_tex(tex_path)
    return md_path, tex_path.with_suffix(".pdf")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument(
        "--fit-summary",
        default="",
        help="Optional fit-summary YAML. Defaults to the package generic summary.",
    )
    ap.add_argument(
        "--replay-csv",
        default="",
        help="Optional replay-validation CSV. Defaults to replay_validation.csv.",
    )
    ap.add_argument(
        "--fullsim-manifest",
        default="",
        help="Optional exact full-simulation manifest, including a manifest copied from another host.",
    )
    args = ap.parse_args()
    profile_yaml = resolve_path(ROOT, args.profile)
    package_dir = locate_package_dir(profile_yaml)
    fit_summary_path = resolve_path(ROOT, args.fit_summary) if args.fit_summary else None
    replay_csv = resolve_path(ROOT, args.replay_csv) if args.replay_csv else None
    fullsim_manifest = resolve_path(ROOT, args.fullsim_manifest) if args.fullsim_manifest else None
    md_path, pdf_path = build_report(
        package_dir,
        profile_yaml,
        fit_summary_path=fit_summary_path,
        replay_csv=replay_csv,
        fullsim_manifest=fullsim_manifest,
    )
    print(
        json.dumps(
            {
                "profile_yaml": str(profile_yaml),
                "report_md": str(md_path),
                "report_pdf": str(pdf_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
