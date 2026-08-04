"""Build a reproducible audit of BWSC weather, 70 km/h load, and sim time steps."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

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
    build_model_from_profile_cfg,
    fit_pv_parameters,
    fit_stop_tilt_fraction,
)

DEFAULT_PACKAGE = ROOT / "project_packages" / "bwsc2025_fitted_mle19_energywindow_inertia"
DEFAULT_OLD_WEATHER = (
    ROOT / ".run" / "mle16_weather" / "bwsc2025_observed_log_5s_weather_components_v2.csv"
)
DEFAULT_NEW_WEATHER = (
    ROOT
    / ".run"
    / "mle17_weather"
    / "bwsc2025_observed_log_5s_weather_components_v3_instant.csv"
)
DEFAULT_OLD_DETAIL = (
    ROOT
    / "project_packages"
    / "bwsc2025_fitted_mle13_grounded_segmented"
    / "outputs"
    / "profile_mle15_fastest_certified"
    / "profile_mle15_fastest_certified_fullcourse_detail_20260714_205250_06f3e495.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=DEFAULT_PACKAGE)
    parser.add_argument("--old-weather", type=Path, default=DEFAULT_OLD_WEATHER)
    parser.add_argument("--instant-weather", type=Path, default=DEFAULT_NEW_WEATHER)
    parser.add_argument("--old-detail", type=Path, default=DEFAULT_OLD_DETAIL)
    parser.add_argument("--outdir", type=Path)
    return parser.parse_args()


def resolve(path: Path) -> Path:
    return path if path.is_absolute() else ROOT / path


def q(series: pd.Series, quantile: float) -> float:
    return float(series.astype(float).quantile(quantile))


def weather_day_summary(path: Path, semantics: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_csv(path, low_memory=False)
    frame["time_utc"] = pd.to_datetime(frame["time_utc"], utc=True)
    frame["day"] = pd.to_numeric(frame["day"], errors="coerce").astype("Int64")
    daylight = frame[pd.to_numeric(frame["GHI_archive"], errors="coerce") >= 20.0].copy()
    rows: list[dict[str, float | int | str]] = []
    for day, group in daylight.groupby("day", dropna=True):
        ghi = pd.to_numeric(group["GHI_archive"], errors="coerce").dropna()
        temp = pd.to_numeric(group["Tamb_archive_C"], errors="coerce").dropna()
        moving = group[
            (pd.to_numeric(group["speed_kmh"], errors="coerce") >= 12.0)
            & ~group["exclude_weather_fit"].astype(bool)
        ]
        observed_pv = pd.to_numeric(moving["solar_power_w_obs"], errors="coerce").dropna()
        rows.append(
            {
                "semantics": semantics,
                "day": int(day),
                "samples": int(len(group)),
                "ghi_mean_wm2": float(ghi.mean()),
                "ghi_median_wm2": float(ghi.median()),
                "ghi_p90_wm2": q(ghi, 0.90),
                "ghi_max_wm2": float(ghi.max()),
                "ambient_mean_c": float(temp.mean()),
                "ambient_min_c": float(temp.min()),
                "ambient_max_c": float(temp.max()),
                "observed_moving_pv_mean_w": float(observed_pv.mean()),
                "observed_moving_pv_max_w": float(observed_pv.max()),
            }
        )
    return pd.DataFrame(rows), frame


def weather_hour_summary(frame: pd.DataFrame, day: int) -> pd.DataFrame:
    """Summarize the late-race weather without hiding noon peaks in a daily mean."""
    selected = frame[pd.to_numeric(frame["day"], errors="coerce").eq(int(day))].copy()
    local_time = pd.to_datetime(selected["time_local"], format="mixed", errors="coerce")
    selected["hour_local"] = local_time.dt.hour
    numeric = [
        "GHI_archive",
        "GHI_effective",
        "Tamb_archive_C",
        "solar_power_w_obs",
        "solar_power_w_model",
    ]
    for column in numeric:
        selected[column] = pd.to_numeric(selected[column], errors="coerce")
    rows: list[dict[str, float | int]] = []
    for hour, group in selected.groupby("hour_local", dropna=True):
        rows.append(
            {
                "day": int(day),
                "hour_local": int(hour),
                "samples": int(len(group)),
                "ghi_archive_mean_wm2": float(group["GHI_archive"].mean()),
                "ghi_archive_max_wm2": float(group["GHI_archive"].max()),
                "ghi_effective_mean_wm2": float(group["GHI_effective"].mean()),
                "ambient_mean_c": float(group["Tamb_archive_C"].mean()),
                "observed_pv_mean_w": float(group["solar_power_w_obs"].mean()),
                "model_pv_mean_w": float(group["solar_power_w_model"].mean()),
            }
        )
    return pd.DataFrame(rows)


def observed_70_summary(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = frame.copy()
    data["vehicle_load_w_obs"] = (
        pd.to_numeric(data["battery_power_w_obs"], errors="coerce")
        + pd.to_numeric(data["solar_power_w_obs"], errors="coerce")
    )
    data["accel_kmhps"] = data.groupby("day")["speed_kmh"].diff() / pd.to_numeric(
        data["dt_sec"], errors="coerce"
    ).clip(lower=0.1)
    clean = (
        pd.to_numeric(data["speed_kmh"], errors="coerce").between(68.0, 72.0)
        & ~data["exclude_power_fit"].astype(bool)
        & pd.to_numeric(data["accel_kmhps"], errors="coerce").abs().le(0.1)
        & pd.to_numeric(data["slope_pct"], errors="coerce").abs().le(0.5)
    )
    low_wind = clean & pd.to_numeric(data["headwind_archive_ms"], errors="coerce").abs().le(2.0)
    rows = []
    for name, mask in (("flat_low_accel", clean), ("flat_low_accel_low_wind", low_wind)):
        values = data.loc[mask, "vehicle_load_w_obs"].dropna()
        rows.append(
            {
                "selection": name,
                "samples": int(len(values)),
                "mean_w": float(values.mean()),
                "p10_w": q(values, 0.10),
                "median_w": float(values.median()),
                "p90_w": q(values, 0.90),
            }
        )
    return pd.DataFrame(rows), data.loc[clean].copy()


def physics_70(profile_path: Path, eta_drive: float = 0.95) -> dict[str, float]:
    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    model = profile["model"]
    speed_ms = 70.0 / 3.6
    gravity = 9.80665
    aero = 0.5 * float(model["rho"]) * float(model["CdA"]) * speed_ms**2
    rolling = float(model["m"]) * gravity * float(model["Crr"])
    wheel = (aero + rolling) * speed_ms
    vehicle = wheel / eta_drive + float(model["P_aux"])
    return {
        "speed_kmh": 70.0,
        "speed_ms": speed_ms,
        "mass_kg": float(model["m"]),
        "rho_kgm3": float(model["rho"]),
        "cda_m2": float(model["CdA"]),
        "crr": float(model["Crr"]),
        "drive_efficiency_assumption": eta_drive,
        "aux_power_w": float(model["P_aux"]),
        "aero_force_n": aero,
        "rolling_force_n": rolling,
        "wheel_power_w": wheel,
        "vehicle_load_w": vehicle,
    }


def compare_pv_temporal_semantics(
    profile_path: Path, old: pd.DataFrame, instant: pd.DataFrame
) -> dict[str, float | int | bool]:
    cfg = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
    base_model = build_model_from_profile_cfg(cfg, profile_path)
    # The temporal comparison must fit one scalar on top of the same declared map.
    base_model.p.panel_gain = 1.0
    results = {}
    for label, frame in (("old", old), ("instant", instant)):
        fit = fit_pv_parameters(
            frame,
            base_model,
            irradiance_source="GHI_archive",
            operating_state="moving",
        )
        fit = fit_stop_tilt_fraction(frame, base_model, fit)
        results.update(
            {
                f"{label}_pv_rmse_60s_w": float(fit.solar_rmse_w),
                f"{label}_panel_gain": float(fit.panel_gain),
                f"{label}_tcell_gain_c_per_wm2": float(fit.tcell_gain_c_per_wm2),
                f"{label}_moving_samples_60s": int(fit.sample_count),
                f"{label}_stop_tilt_fraction": float(fit.stop_tilt_fraction),
                f"{label}_stop_pv_rmse_60s_w": float(fit.stop_solar_rmse_w),
                f"{label}_stop_samples_60s": int(fit.stop_sample_count),
            }
        )
    results["moving_pv_rmse_improved"] = bool(
        float(results["instant_pv_rmse_60s_w"]) < float(results["old_pv_rmse_60s_w"])
    )
    results["instant_stop_tilt_at_upper_bound"] = bool(
        float(results["instant_stop_tilt_fraction"]) >= 1.0 - 1.0e-8
    )
    return results


def time_step_summary(path: Path) -> tuple[pd.DataFrame, dict[str, object]]:
    frame = pd.read_csv(path, low_memory=False)
    dt = pd.to_numeric(frame["step_dt_sec"], errors="coerce").dropna()
    counts = dt.round(9).value_counts().rename_axis("step_dt_sec").reset_index(name="rows")
    counts = counts.sort_values("step_dt_sec", ascending=False).reset_index(drop=True)
    target = frame[np.isclose(pd.to_numeric(frame["step_dt_sec"], errors="coerce"), 11.74725057049)]
    example: dict[str, object] = {
        "source": str(path),
        "rows": int(len(frame)),
        "min_step_dt_sec": float(dt.min()),
        "max_step_dt_sec": float(dt.max()),
        "example_remainder_rows": int(len(target)),
        "decomposition_sec": [600.0, 600.0, 11.74725057049],
        "decomposition_total_sec": 1211.74725057049,
        "new_detail_target_hz": 1.0,
        "expected_new_detail_rows_for_example": 1212,
    }
    if not target.empty:
        row = target.iloc[0]
        example.update(
            {
                "example_time_utc": str(row.get("time_utc", "")),
                "example_s_km": float(row.get("s_km", math.nan)),
                "example_s_end_km": float(row.get("s_end_km", math.nan)),
            }
        )
    return counts, example


def sampled_fullsim_weather_by_day(path: Path) -> pd.DataFrame:
    # Consolidate blocks before adding derived columns; the detail CSV has many
    # columns and can otherwise trigger a misleading fragmentation warning.
    frame = pd.read_csv(path, low_memory=False).copy()
    local_time = pd.to_datetime(frame["time_local"], format="mixed", errors="coerce")
    first_day = local_time.dt.normalize().min()
    frame["day"] = (local_time.dt.normalize() - first_day).dt.days + 1
    frame["G_raw"] = pd.to_numeric(frame["G_raw"], errors="coerce")
    frame["P_pv"] = pd.to_numeric(frame["P_pv"], errors="coerce")
    frame["step_dt_sec"] = pd.to_numeric(frame["step_dt_sec"], errors="coerce")
    drive_window = frame["is_drive_window"].astype(str).str.lower().isin({"true", "1"})
    frame = frame[drive_window & (frame["G_raw"] >= 20.0)].copy()
    rows = []
    for day, group in frame.groupby("day", dropna=True):
        weights = group["step_dt_sec"].clip(lower=0.0)
        rows.append(
            {
                "day": int(day),
                "rows": int(len(group)),
                "duration_weighted_ghi_mean_wm2": float(np.average(group["G_raw"], weights=weights)),
                "sampled_ghi_max_wm2": float(group["G_raw"].max()),
                "duration_weighted_pv_mean_w": float(np.average(group["P_pv"], weights=weights)),
                "sampled_pv_max_w": float(group["P_pv"].max()),
            }
        )
    return pd.DataFrame(rows)


def make_figures(
    outdir: Path,
    weather_summary: pd.DataFrame,
    speed70: pd.DataFrame,
    step_counts: pd.DataFrame,
) -> None:
    plt.rcParams.update({"figure.dpi": 150, "font.size": 9})

    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    markers = {"preceding_hour_mean": "o", "instant_at_timestamp": "s"}
    for semantics, group in weather_summary.groupby("semantics"):
        ax.plot(
            group["day"],
            group["ghi_mean_wm2"],
            color="black",
            linestyle="--" if semantics == "preceding_hour_mean" else "-",
            marker=markers[semantics],
            label=semantics,
        )
    ax.set(xlabel="race day", ylabel="daylight route-sampled GHI [W/m2]")
    ax.grid(True, color="0.85")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(outdir / "weather_daylight_mean_comparison.png", bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    ax.scatter(
        speed70["speed_kmh"],
        speed70["vehicle_load_w_obs"],
        s=4,
        alpha=0.15,
        color="black",
        rasterized=True,
    )
    ax.set(xlabel="observed speed [km/h]", ylabel="observed vehicle load [W]")
    ax.grid(True, color="0.85")
    fig.tight_layout()
    fig.savefig(outdir / "observed_load_near_70kmh.png", bbox_inches="tight")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(7.2, 3.8))
    shown = step_counts.head(12).sort_values("step_dt_sec")
    ax.barh(shown["step_dt_sec"].map(lambda x: f"{x:g}"), shown["rows"], color="0.35")
    ax.set(xlabel="row count", ylabel="old outer step_dt_sec [s]")
    ax.set_xscale("log")
    ax.grid(True, axis="x", color="0.85")
    fig.tight_layout()
    fig.savefig(outdir / "old_outer_step_duration_counts.png", bbox_inches="tight")
    plt.close(fig)


def write_tex(
    outdir: Path,
    weather: pd.DataFrame,
    day6_hourly: pd.DataFrame,
    sampled_fullsim_weather: pd.DataFrame,
    comparison: dict[str, float | int | bool],
    observed70: pd.DataFrame,
    physics: dict[str, float],
    step: dict[str, object],
    sources: dict[str, str],
) -> None:
    instant = weather[weather["semantics"] == "instant_at_timestamp"]
    day_rows = "\n".join(
        f"{int(row.day)} & {row.ghi_mean_wm2:.1f} & {row.ghi_max_wm2:.1f} & "
        f"{row.ambient_mean_c:.1f} & {row.observed_moving_pv_mean_w:.1f} & "
        f"{row.observed_moving_pv_max_w:.1f} \\\\"
        for row in instant.itertuples()
    )
    sim_weather_rows = "\n".join(
        f"{int(row.day)} & {row.duration_weighted_ghi_mean_wm2:.1f} & {row.sampled_ghi_max_wm2:.1f} & "
        f"{row.duration_weighted_pv_mean_w:.1f} & {row.sampled_pv_max_w:.1f} \\\\"
        for row in sampled_fullsim_weather.itertuples()
    )
    day6_hourly_rows = "\n".join(
        f"{int(row.hour_local):02d}:00 & {row.ghi_archive_mean_wm2:.1f} & "
        f"{row.ghi_archive_max_wm2:.1f} & {row.ghi_effective_mean_wm2:.1f} & "
        f"{row.ambient_mean_c:.1f} & {row.observed_pv_mean_w:.1f} & "
        f"{row.model_pv_mean_w:.1f} \\\\"
        for row in day6_hourly.itertuples()
    )
    obs = observed70.iloc[0]
    tex = rf"""\documentclass[a4paper,10pt]{{article}}
\usepackage[top=16mm,bottom=18mm,left=17mm,right=17mm]{{geometry}}
\usepackage{{fontspec,xeCJK,amsmath,booktabs,graphicx,longtable,array}}
\setmainfont{{Times New Roman}}\setCJKmainfont{{Yu Gothic}}\setCJKmonofont{{Yu Gothic}}
\usepackage[unicode,hidelinks]{{hyperref}}
\setlength{{\parindent}}{{1em}}\setlength{{\parskip}}{{0.35em}}
\title{{BWSC2025 天候・70 km/h消費・シミュレーション刻み監査報告}}
\author{{MPCEMS YATA}}\date{{2026-07-15}}
\begin{{document}}\maketitle
\section{{技術要約}}
旧天候入力はOpen-Meteoの「直前1時間平均」を瞬時値として補間していた。
MLE17では\texttt{{*\_instant}}へ変更し、同一ログで移動中PVの60秒RMSEは
{comparison['old_pv_rmse_60s_w']:.3f} Wから{comparison['instant_pv_rmse_60s_w']:.3f} Wへ改善した。
ただし同APIは再解析値であり、車上POA計の代替となる完全な真値ではない。
70 km/h付近の観測車両総負荷中央値は{obs.median_w:.1f} W、
物理モデルは{physics['vehicle_load_w']:.1f} Wであり整合する。
11.747251秒は同期故障ではなく、1211.747251秒の上位距離区間を
$600+600+11.747251$秒に厳密分割した端数である。

\section{{範囲とデータ定義}}
天候表は全距離・全時刻の格子そのものではなく、実走ログの時刻と復元位置に
サンプリングした系列を集計した。車両総負荷の観測定義は
\[
P_{{vehicle,obs}}=P_{{battery,obs}}+P_{{solar,obs}}
\]
であり、PV差引後の電池電力とは区別する。使用ソースは次の通りである。
\begin{{itemize}}
\item instant replay: \nolinkurl{{bwsc2025_observed_log_5s_weather_components_v3_instant.csv}}
\item old replay: \nolinkurl{{bwsc2025_observed_log_5s_weather_components_v2.csv}}
\item old fullsim detail: \nolinkurl{{profile_mle15_fastest_certified_fullcourse_detail_*.csv}}
\item profile: \nolinkurl{{{sources['profile']}}}
\end{{itemize}}
完全な相対パスは同じディレクトリの\nolinkurl{{audit_summary.json}}に保存する。

\section{{天候監査}}
Open-Meteoの通常の日射量は表示時刻までの直前1時間平均である。
例えば10:00値の代表中心は09:30なので、瞬時値として扱うと30分の位相誤差を作る。
MLE17は瞬時変数を要求し、キャッシュschemaを更新した。
\begin{{center}}\small
\begin{{tabular}}{{rrrrrr}}\toprule
day & GHI mean & GHI max & mean $T_{{amb}}$ & observed PV mean & PV max\\
 & \multicolumn{{2}}{{c}}{{[W/m$^2$]}} & [$^\circ$C] & \multicolumn{{2}}{{c}}{{[W]}}\\\midrule
{day_rows}
\bottomrule\end{{tabular}}\end{{center}}
\par\medskip\noindent
\includegraphics[width=\linewidth]{{weather_daylight_mean_comparison.png}}\par
後半日の平均日射は低い一方、短時間の最大値が600--700 W/m$^2$台となることは両立する。
また生の時刻・距離格子に高い値があっても、その時刻に車両が別地点なら車両入力ではない。
Day 6を現地時刻で分解すると次の通りであり、600--700 W/m$^2$台は主に正午帯である。
\begin{{center}}\scriptsize
\begin{{tabular}}{{rrrrrrr}}\toprule
hour & archive mean & archive max & effective mean & $T_{{amb}}$ & observed PV & model PV\\
 & \multicolumn{{3}}{{c}}{{[W/m$^2$]}} & [$^\circ$C] & \multicolumn{{2}}{{c}}{{[W]}}\\\midrule
{day6_hourly_rows}
\bottomrule\end{{tabular}}\end{{center}}
ここで\texttt{{GHI\_effective}}は車上PV観測を用いた補正値であり、
\texttt{{GHI\_archive}}から独立した検証データではない。
旧fullsim detailが実際にサンプリングした\texttt{{G\_raw}}は次の通りである。
\begin{{center}}\small
\begin{{tabular}}{{rrrrr}}\toprule
day & GHI mean & GHI max & model PV mean & PV max\\
 & \multicolumn{{2}}{{c}}{{[W/m$^2$]}} & \multicolumn{{2}}{{c}}{{[W]}}\\\midrule
{sim_weather_rows}
\bottomrule\end{{tabular}}\end{{center}}
従って生格子の600--900 W/m$^2$行を、そのまま後半日の車両入力と解釈してはならない。

\section{{70 km/h消費監査}}
$v=70/3.6$ m/s、平坦・無風として
\[
F_a=\tfrac12\rho C_dAv^2={physics['aero_force_n']:.3f}\ \mathrm{{N}},\quad
F_r=mgC_{{rr}}={physics['rolling_force_n']:.3f}\ \mathrm{{N}},
\]
\[
P_{{wheel}}=(F_a+F_r)v={physics['wheel_power_w']:.3f}\ \mathrm{{W}},\quad
P_{{vehicle}}=P_{{wheel}}/0.95+P_{{aux}}={physics['vehicle_load_w']:.3f}\ \mathrm{{W}}.
\]
観測選別は68--72 km/h、$|a|\le0.1$ km/h/s、$|grade|\le0.5\%$、
power-fit除外である。中央値{obs.median_w:.1f} W、10--90\%範囲は
{obs.p10_w:.1f}--{obs.p90_w:.1f} Wである。
\par\medskip\noindent
\includegraphics[width=\linewidth]{{observed_load_near_70kmh.png}}\par

\section{{時間刻み監査}}
旧detailの行は外側積分区間であり、上位区間終端・control stop・走行窓境界を
厳密に踏むため600秒未満の端数を許す。例は
\[
1211.747251=600+600+11.747251\ \mathrm{{s}}.
\]
新実装はdetailを最低1 Hzとし、この例を1211行の1秒行と1行の0.747251秒境界行、
合計{int(step['expected_new_detail_rows_for_example'])}行へ展開する。
\par\medskip\noindent
\includegraphics[width=\linewidth]{{old_outer_step_duration_counts.png}}\par

\section{{限界、不確かさ、採否}}
Open-Meteo archiveは観測所の車上計測ではなく再解析である。
瞬時化後もPV RMSEはゼロではなく、停止時tilt係数が上限へ達したため、
停止姿勢、遮蔽、電流・電圧時刻同期、POAセンサの独立検証が必要である。
従って本変更は旧入力より妥当だが、日射・PVモデルを「確定済み真値」とは判定しない。

BWSC2025 replayの次の独立候補はBOM Himawari時間積算日射
IDE02327（約2 km）またはIDE02347（約5 km）である。これは衛星画像から導出した
公式格子であるが、車上POA実測そのものではない。また履歴ファイルはNCI rv74研究
アクセスまたはBOMへのデータ申請が必要である。入手後は
\nolinkurl{{scripts/import_bom_satellite_solar.py}}でMJ/m$^2$を区間平均W/m$^2$へ変換し、
積算区間中央へ時刻を合わせる。品質JSON、held-out PV RMSE、25 km energy RMSEが
全て改善するまでactive profileへ昇格してはならない。

\section{{運用上の結論}}
解析では次の3列を混同しない。
\begin{{center}}\small
\nolinkurl{{P_vehicle_load_w}}\quad
\nolinkurl{{P_solar_w}}\quad
\nolinkurl{{P_net_battery_w}}
\end{{center}}
天候は次の組を確認する。
\begin{{center}}\small
\nolinkurl{{radiation_temporal_semantics}} $=$ \nolinkurl{{instant_at_timestamp}}
\end{{center}}
fullsim detailでは\nolinkurl{{detail_step_kind}}と境界理由を併記して読む。

\begin{{thebibliography}}{{9}}
\bibitem{{openmeteo}} Open-Meteo, \emph{{Historical Weather API Documentation}},
\href{{https://open-meteo.com/en/docs/historical-weather-api}}{{official online documentation}},
accessed 2026-07-15.
\bibitem{{bomsolar}} Australian Bureau of Meteorology,
\emph{{Gridded Hourly and Daily Solar Exposure Metadata}},
\href{{https://www.bom.gov.au/climate/how/newproducts/metadata_solarexposure.shtml}}{{official metadata}},
accessed 2026-07-16.
\bibitem{{bomproduct}} Australian Bureau of Meteorology,
\emph{{Himawari-8/9 Global Solar Exposure}},
\href{{https://www.bom.gov.au/climate/how/newproducts/himawari-solarexposure.shtml}}{{official product page}},
accessed 2026-07-16.
\end{{thebibliography}}
\end{{document}}
"""
    (outdir / "weather_power_timestep_audit.tex").write_text(tex, encoding="utf-8")


def main() -> int:
    args = parse_args()
    package = resolve(args.package)
    old_weather_path = resolve(args.old_weather)
    instant_weather_path = resolve(args.instant_weather)
    old_detail_path = resolve(args.old_detail)
    outdir = resolve(args.outdir) if args.outdir else package / "outputs" / "reports" / "weather_power_timestep_audit"
    outdir.mkdir(parents=True, exist_ok=True)

    old_summary, old = weather_day_summary(old_weather_path, "preceding_hour_mean")
    new_summary, instant = weather_day_summary(instant_weather_path, "instant_at_timestamp")
    weather = pd.concat([old_summary, new_summary], ignore_index=True)
    day6_hourly = weather_hour_summary(instant, day=6)
    observed70, speed70 = observed_70_summary(instant)
    physics = physics_70(package / "profile.yaml")
    step_counts, step = time_step_summary(old_detail_path)
    sampled_sim_weather = sampled_fullsim_weather_by_day(old_detail_path)

    comparison = compare_pv_temporal_semantics(package / "profile.yaml", old, instant)
    sources = {
        "old_weather": old_weather_path.relative_to(ROOT).as_posix(),
        "instant_weather": instant_weather_path.relative_to(ROOT).as_posix(),
        "old_detail": old_detail_path.relative_to(ROOT).as_posix(),
        "profile": (package / "profile.yaml").relative_to(ROOT).as_posix(),
    }

    weather.to_csv(outdir / "weather_day_summary.csv", index=False)
    day6_hourly.to_csv(outdir / "weather_day6_hourly_summary.csv", index=False)
    observed70.to_csv(outdir / "observed_70kmh_load_summary.csv", index=False)
    step_counts.to_csv(outdir / "old_outer_step_duration_counts.csv", index=False)
    sampled_sim_weather.to_csv(outdir / "old_fullsim_sampled_weather_by_day.csv", index=False)
    payload = {
        "sources": sources,
        "weather_temporal_semantics_fix": comparison,
        "day6_hourly_weather": day6_hourly.to_dict(orient="records"),
        "physics_70kmh": physics,
        "time_step_example": step,
        "quality_decision": {
            "instant_weather_is_better_than_preceding_hour_mean": bool(
                comparison["moving_pv_rmse_improved"]
            ),
            "weather_is_independent_ground_truth": False,
            "pv_model_high_precision_certified": False,
            "current_external_weather_class": "model/reanalysis; not route-local ground truth",
            "preferred_independent_historical_solar_source": "BOM Himawari IDE02327 or IDE02347",
            "bom_historical_access": "NCI rv74 research access or BOM data request required",
            "bom_importer": "scripts/import_bom_satellite_solar.py",
            "reason": (
                "PV residual remains material and stop tilt reached its bound."
                if comparison["instant_stop_tilt_at_upper_bound"]
                else "PV residual remains material and independent POA validation is absent."
            ),
        },
    }
    (outdir / "audit_summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    make_figures(outdir, weather, speed70, step_counts)
    write_tex(
        outdir,
        weather,
        day6_hourly,
        sampled_sim_weather,
        comparison,
        observed70,
        physics,
        step,
        sources,
    )
    print(outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
