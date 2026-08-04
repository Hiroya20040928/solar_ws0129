#!/usr/bin/env python3
"""Generate per-program Japanese reference PDFs for the solar package."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from program_reference_curriculum import (
    CONCEPTS_BY_KEY,
    FOUNDATION_CHAPTERS,
    MPC_NODE_DEEP_DIVE,
    PROGRAM_EXTRA_CONCEPTS,
    REFERENCE_SOURCES,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "docs" / "program_reference_complete_20260729"
TEX_DIR = OUT_ROOT / "tex"
PDF_DIR = OUT_ROOT / "pdf"
BUILD_DIR = OUT_ROOT / "build"
MARKDOWN_DIR = OUT_ROOT / "markdown"
MANIFEST_PATH = OUT_ROOT / "program_reference_manifest.json"
INDEX_TEX = TEX_DIR / "program_reference_index.tex"
INDEX_PDF = PDF_DIR / "program_reference_index.pdf"
FOUNDATION_TEX = TEX_DIR / "00_foundations.tex"
FOUNDATION_PDF = PDF_DIR / "00_foundations.pdf"
FOUNDATION_MARKDOWN = MARKDOWN_DIR / "00_foundations.md"
GENERATION_DATE = "2026-07-29"


@dataclass(frozen=True)
class ProgramSpec:
    order: int
    path: str
    title: str
    category: str
    purpose: str
    startup_context: str
    called_from: list[str] = field(default_factory=list)
    next_read: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    flow_steps: list[str] = field(default_factory=list)


@dataclass
class ImportItem:
    lineno: int
    source: str
    names: list[str]
    kind: str


@dataclass
class SymbolItem:
    name: str
    lineno: int
    detail: str = ""


@dataclass
class CallItem:
    lineno: int
    value: str
    detail: str = ""


@dataclass
class BlockDetail:
    name: str
    lineno: int
    kind: str
    end_lineno: int = 0
    owner: str = ""
    signature: str = ""
    docstring: str = ""
    return_summary: str = ""
    local_calls: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    source_excerpt: str = ""
    assigned_names: list[str] = field(default_factory=list)
    self_reads: list[str] = field(default_factory=list)
    self_writes: list[str] = field(default_factory=list)
    raised_exceptions: list[str] = field(default_factory=list)
    syntax_notes: list[str] = field(default_factory=list)
    branch_count: int = 0
    loop_count: int = 0
    try_count: int = 0


@dataclass
class TopLevelStep:
    lineno: int
    summary: str


@dataclass
class ProgramAnalysis:
    spec: ProgramSpec
    text: str
    imports: list[ImportItem] = field(default_factory=list)
    classes: list[SymbolItem] = field(default_factory=list)
    functions: list[SymbolItem] = field(default_factory=list)
    parameters: list[CallItem] = field(default_factory=list)
    publishers: list[CallItem] = field(default_factory=list)
    subscriptions: list[CallItem] = field(default_factory=list)
    timers: list[CallItem] = field(default_factory=list)
    cli_args: list[CallItem] = field(default_factory=list)
    launch_nodes: list[CallItem] = field(default_factory=list)
    shell_functions: list[CallItem] = field(default_factory=list)
    shell_actions: list[CallItem] = field(default_factory=list)
    external_commands: list[CallItem] = field(default_factory=list)
    local_dependencies: list[str] = field(default_factory=list)
    docstring: str = ""
    block_details: list[BlockDetail] = field(default_factory=list)
    top_level_steps: list[TopLevelStep] = field(default_factory=list)
    import_use_lines: dict[str, list[int]] = field(default_factory=dict)


PROGRAMS: list[ProgramSpec] = [
    ProgramSpec(
        1,
        "SolarSim.ps1",
        "Windows入口 PowerShell ルータ",
        "入口",
        "Windows PowerShell から build、launch、offline script、Grafana 操作をまとめて呼び出す最上位入口。",
        "オペレータが最初に叩くコマンド入口。",
        called_from=["人間の運用操作"],
        next_read=["scripts/solar_control.sh", "launch/solar_race_live_wifi.launch.py", "scripts/solar_sim.py"],
        key_points=[
            "WSL ディストリビューションを解決する。",
            "Action と Mode を shell 側へ受け渡す。",
            "dashboard や report の自動オープンも担う。",
        ],
        flow_steps=[
            "PowerShell 引数を解釈する。",
            "WSL 側のパスへ変換する。",
            "scripts/solar_control.sh を action と mode 付きで呼ぶ。",
            "必要に応じて dashboard、graph、report を開く。",
        ],
    ),
    ProgramSpec(
        2,
        "scripts/solar_control.sh",
        "WSL側 実行ルータ",
        "入口",
        "ROS 2 build、launch、offline simulation、forecast、identification、learn を mode 別に振り分ける。",
        "SolarSim.ps1 から WSL 内で呼ばれる実行ルータ。",
        called_from=["SolarSim.ps1"],
        next_read=["launch/solarcar_sim.launch.py", "launch/solar_race_live.launch.py", "scripts/solar_sim.py"],
        key_points=[
            "mode から launch file を決める。",
            "ROS 環境を source する。",
            "起動 PID 管理と stop/status/graph を一括で持つ。",
        ],
        flow_steps=[
            "action と mode を受け取る。",
            "ROS 環境と install/setup.bash を読む。",
            "launch 実行か offline script 実行かを分岐する。",
            "必要に応じて PID 管理、graph 出力、log tail を行う。",
        ],
    ),
    ProgramSpec(
        3,
        "launch/solar_race_live_wifi.launch.py",
        "live_wifi ROS2 launch 入口",
        "launch",
        "WiFi テレメトリ、風補正、live MPC 運用をまとめて起動する launch 入口。",
        "live_wifi モード起動時に ros2 launch される。",
        called_from=["scripts/solar_control.sh", "SolarSim.ps1"],
        next_read=["mpc_solarcar/live_launch.py", "mpc_solarcar/telemetry_text_bridge_node.py", "mpc_solarcar/wind_correction_node.py"],
        key_points=[
            "profile_yaml を launch 引数として受ける。",
            "共通 live node 群に WiFi bridge と wind correction を追加する。",
            "live forecast の raw/corrected CSV の入口でもある。",
        ],
    ),
    ProgramSpec(
        4,
        "launch/solar_race_live.launch.py",
        "live ROS2 launch 入口",
        "launch",
        "WiFi 文字列 bridge を使わない live 運用の基本 launch。",
        "live モード起動時に ros2 launch される。",
        called_from=["scripts/solar_control.sh", "SolarSim.ps1"],
        next_read=["mpc_solarcar/live_launch.py", "mpc_solarcar/mpc_node.py"],
        key_points=[
            "profile を読み build_live_nodes に委譲する。",
            "ノード構成の本体は live_launch.py にある。",
        ],
    ),
    ProgramSpec(
        5,
        "launch/solarcar_sim.launch.py",
        "sim ROS2 launch 入口",
        "launch",
        "GPS 模擬、車体状態模擬、MPC、dashboard を立ち上げる simulation launch。",
        "sim モード起動時に ros2 launch される。",
        called_from=["scripts/solar_control.sh", "SolarSim.ps1"],
        next_read=["mpc_solarcar/gps_sim_node.py", "mpc_solarcar/solar_state_node.py", "mpc_solarcar/mpc_node.py"],
        key_points=[
            "route/forecast/maps の存在確認を先に行う。",
            "sim 用の common_mpc パラメータ束を構成する。",
            "planner speed が GPS/state 側へ戻る閉ループを作る。",
        ],
    ),
    ProgramSpec(
        6,
        "launch/solar_measurement.launch.py",
        "measure ROS2 launch 入口",
        "launch",
        "実測収集用に preflight、distance、grade、logger、dashboard を起動する launch。",
        "measure モード起動時に ros2 launch される。",
        called_from=["scripts/solar_control.sh", "SolarSim.ps1"],
        next_read=["mpc_solarcar/distance_node.py", "mpc_solarcar/grade_node.py", "mpc_solarcar/solar_logger_node.py"],
        key_points=[
            "planner を起動せず、計測系だけを立てる。",
            "distance/grade は profile の measurement 設定で可否が決まる。",
        ],
    ),
    ProgramSpec(
        7,
        "mpc_solarcar/live_launch.py",
        "live系 node 構成ビルダ",
        "launch helper",
        "profile を読み、live と live_wifi で共通に使う node 群を Python から組み立てる。",
        "launch/solar_race_live*.launch.py から呼ばれる。",
        called_from=["launch/solar_race_live.launch.py", "launch/solar_race_live_wifi.launch.py"],
        next_read=["mpc_solarcar/solar_profile.py", "mpc_solarcar/mpc_node.py", "mpc_solarcar/speed_command_bridge_node.py"],
        key_points=[
            "forecast CSV の raw/corrected パスを用意する。",
            "mpc_node、logger、dashboard、preflight などの Node action を返す。",
            "use_wifi の有無で planner が読む forecast CSV を切り替える。",
        ],
    ),
    ProgramSpec(
        8,
        "mpc_solarcar/solar_profile.py",
        "profile YAML 読込と検証",
        "config",
        "profile.yaml をロードし、セクション取得、相対パス解決、CSV 最低品質検査を行う。",
        "launch、offline simulation、identification の共通設定入口。",
        called_from=["live_launch.py", "solarcar_sim.launch.py", "solar_state_node.py", "多数の scripts"],
        next_read=["mpc_solarcar/path_utils.py"],
        key_points=[
            "load_profile が YAML 全体を返す。",
            "get_path が profile 基準で実ファイルパスへ変換する。",
            "require_csv_data_rows が空テンプレと実データを区別する。",
        ],
    ),
    ProgramSpec(
        9,
        "mpc_solarcar/path_utils.py",
        "ROS share / 相対パス解決",
        "config",
        "CWD、package share、repo root をまたいで path を実在ファイルへ解決する小さな基盤。",
        "Node 実行時の path ぶれを吸収する補助モジュール。",
        called_from=["mpc_node.py", "gps_sim_node.py", "solar_state_node.py"],
        next_read=["mpc_solarcar/solar_profile.py"],
        key_points=[
            "ament の package share があればそちらを優先する。",
            "インストール後の launch/node 実行でも同じ relative path を使えるようにする。",
        ],
    ),
    ProgramSpec(
        10,
        "scripts/solar_sim.py",
        "offline フルレース simulation 本体",
        "offline core",
        "profile、forecast、route、maps を使って全レースを逐次再生し、upper/lower 相当の実行を CSV と HTML に落とす。",
        "simulate や historical-simulate で直接呼ばれる同期版の基準実装。",
        called_from=["scripts/solar_control.sh"],
        next_read=["mpc_solarcar/model.py", "mpc_solarcar/upper_horizon.py", "mpc_solarcar/upper_solver.py"],
        key_points=[
            "SolarCarModel を直に持つ同期版なので、数理理解の最短入口。",
            "full summary JSON、detail CSV、upper plan CSV、HTML report を生成する。",
            "live の mpc_node とかなり同型の距離上位計画ロジックを持つ。",
        ],
    ),
    ProgramSpec(
        11,
        "mpc_solarcar/mpc_node.py",
        "live / sim 共通 MPC 本体",
        "runtime core",
        "forecast、route、vehicle telemetry、maps を使って上位速度計画と下位追従指令を出す ROS2 ノード。",
        "sim/live/live_wifi で中心に動く単一障害点に近いノード。",
        called_from=["live_launch.py", "solarcar_sim.launch.py"],
        next_read=["mpc_solarcar/model.py", "mpc_solarcar/upper_cost.py", "mpc_solarcar/estimator.py"],
        key_points=[
            "SolarCarModel を直接生成する。",
            "1 Hz upper timer と lower timer 群を並列 callback group で回す。",
            "calibration topic で内部係数を上書きする。",
        ],
    ),
    ProgramSpec(
        12,
        "mpc_solarcar/model.py",
        "車体物理・電気モデル本体",
        "model",
        "空力、転がり、坂、PV、MPPT、drive/regen 効率、battery IV、SoC 更新を統合した vehicle model。",
        "planner と simulation の数理コア。",
        called_from=["mpc_node.py", "solar_state_node.py", "scripts/solar_sim.py", "estimator.py"],
        next_read=["mpc_solarcar/utils_maps.py"],
        key_points=[
            "SolarCarModel と Params が中心。",
            "electrical_balance が planner 側で最も多く呼ばれる。",
            "resistive_forces、battery_iv、soc_step が各所から再利用される。",
        ],
    ),
    ProgramSpec(
        13,
        "mpc_solarcar/utils_maps.py",
        "効率マップ・抵抗マップ読込補間",
        "model helper",
        "CSV で持つ drive/regen efficiency、Rint、OCV などを読み、補間可能な配列へ変換する。",
        "SolarCarModel の map backend。",
        called_from=["mpc_solarcar/model.py"],
        next_read=[],
        key_points=[
            "read_eff_map、read_Rint_map、read_map、read_1d_map が入口。",
            "bilinear_interp が 2D 補間の核。",
        ],
    ),
    ProgramSpec(
        14,
        "mpc_solarcar/upper_horizon.py",
        "上位MPC 距離メッシュ生成",
        "planner helper",
        "固定または適応距離メッシュを作り、現在地点から先の control point と segment を決める。",
        "distance-domain upper planner の最初の一歩。",
        called_from=["mpc_node.py", "scripts/solar_sim.py"],
        next_read=["mpc_solarcar/upper_policy.py"],
        key_points=[
            "build_upper_distance_horizon が中心。",
            "plan_segment_index が現在位置から有効速度区間を引く。",
        ],
    ),
    ProgramSpec(
        15,
        "mpc_solarcar/upper_policy.py",
        "上位速度計画の補間と warm start",
        "planner helper",
        "外部 speed policy CSV と前回解を絶対距離基準で現在メッシュへ補間し直す。",
        "upper planner の初期値品質を決める補助。",
        called_from=["mpc_node.py", "scripts/solar_sim.py"],
        next_read=["mpc_solarcar/upper_solver.py"],
        key_points=[
            "absolute_control_distances と shift_upper_policy_warm_start が重要。",
            "相対距離ではなくルート絶対距離に揃える修正済み箇所。",
        ],
    ),
    ProgramSpec(
        16,
        "mpc_solarcar/upper_cost.py",
        "上位MPC 目的関数",
        "planner helper",
        "速度、SoC、温度、電流、進捗、day-end、terminal 条件を penalty として定義する。",
        "upper planner の良し悪しを数式化する場所。",
        called_from=["mpc_node.py", "scripts/solar_sim.py", "tune_upper_planner_weights.py"],
        next_read=["scripts/tune_upper_planner_weights.py"],
        key_points=[
            "upper_stage_cost と upper_terminal_cost が中心。",
            "load_upper_cost_config が profile の重み束を解く。",
        ],
    ),
    ProgramSpec(
        17,
        "mpc_solarcar/upper_solver.py",
        "上位探索ソルバ",
        "planner helper",
        "bounded global candidate search、CEM、SHGO、L-BFGS-B を束ねて upper policy を最適化する。",
        "upper planner の数値最適化 backend。",
        called_from=["mpc_node.py", "scripts/solar_sim.py"],
        next_read=[],
        key_points=[
            "hybrid_bounded_minimize が中心。",
            "global 探索と local refine の接着層である。",
        ],
    ),
    ProgramSpec(
        18,
        "mpc_solarcar/estimator.py",
        "Battery MHE",
        "estimator",
        "観測された I/V/SoC/Tb と model を使って内部 SoC/Tb を短ホライズンで補正する。",
        "mpc_node 内の状態推定器。",
        called_from=["mpc_node.py"],
        next_read=["mpc_solarcar/model.py"],
        key_points=[
            "BatteryMHE が入力列を保持し、最尤に近い初期状態を逆推定する。",
            "planner 本体の物理モデルをそのまま使う。",
        ],
    ),
    ProgramSpec(
        19,
        "mpc_solarcar/solar_state_node.py",
        "sim 用 車体状態 publisher",
        "runtime node",
        "sim モードで planner 指令速度から速度、距離、電池、PV、altitude を模擬 publish する。",
        "simulation launch における擬似車両。",
        called_from=["launch/solarcar_sim.launch.py"],
        next_read=["mpc_solarcar/model.py", "mpc_solarcar/mpc_node.py"],
        key_points=[
            "SolarCarModel を直接生成する。",
            "/planner/speed_cmd を受けて /vehicle/* を出す。",
        ],
    ),
    ProgramSpec(
        20,
        "mpc_solarcar/telemetry_text_bridge_node.py",
        "WiFi 文字列テレメトリ bridge",
        "runtime node",
        "車両側・伴走車側から届く UDP 文字列を ROS topic に変換し、planner 指令を逆向きに文字列送信する。",
        "live_wifi のセンサ入口と outbound command bridge を兼ねる。",
        called_from=["launch/solar_race_live_wifi.launch.py"],
        next_read=["mpc_solarcar/telemetry_protocol.py", "mpc_solarcar/speed_command_bridge_node.py"],
        key_points=[
            "inbound と outbound の両方向を持つ。",
            "speed、battery、distance、GPS、wind を ROS topic 化する。",
            "planner command を JSON/テキストで送り返す。",
        ],
    ),
    ProgramSpec(
        21,
        "mpc_solarcar/distance_node.py",
        "速度積分距離ノード",
        "runtime node",
        "vehicle speed を積分して /vehicle/s_km を生成する最小ノード。",
        "measure/live 系で direct distance が無い場合の距離供給。",
        called_from=["launch/solar_measurement.launch.py", "mpc_solarcar/live_launch.py"],
        next_read=[],
        key_points=[
            "reset_odometry service も持つ。",
            "入力は /vehicle/speed_kmh だけ。",
        ],
    ),
    ProgramSpec(
        22,
        "mpc_solarcar/weather_fetch_node.py",
        "live forecast 取得ノード",
        "runtime node",
        "chase GPS または fallback 座標から Open-Meteo forecast を取得し、planner が読む CSV を更新する。",
        "live 系の forecast 更新入口。",
        called_from=["mpc_solarcar/live_launch.py"],
        next_read=["mpc_solarcar/weather_utils.py", "mpc_solarcar/wind_correction_node.py"],
        key_points=[
            "raw forecast CSV を定期更新する。",
            "planner 自体は topic ではなく forecast CSV を読む。",
        ],
    ),
    ProgramSpec(
        23,
        "mpc_solarcar/wind_correction_node.py",
        "live 風補正ノード",
        "runtime node",
        "観測 headwind と現在距離から raw forecast CSV を補正し、corrected forecast CSV を書き出す。",
        "live_wifi で planner 入力の風を上書きする前処理。",
        called_from=["launch/solar_race_live_wifi.launch.py"],
        next_read=["mpc_solarcar/mpc_node.py"],
        key_points=[
            "planner は /weather/headwind_corrected_ms を直接読むのではない。",
            "corrected CSV を mpc_node が再読込して効かせる。",
        ],
    ),
    ProgramSpec(
        24,
        "mpc_solarcar/solar_autocal_node.py",
        "live 自動校正ノード",
        "runtime node",
        "観測 solar/pack power と planner 予測との差から solar_gain、drive_power_gain、aux_power_w を推定 publish する。",
        "運用中に mpc_node の係数を微調整する補助ノード。",
        called_from=["mpc_solarcar/live_launch.py"],
        next_read=["mpc_solarcar/solar_autocal_logic.py", "mpc_solarcar/mpc_node.py"],
        key_points=[
            "/calib/* topic を publish する。",
            "mpc_node がそれを購読して内部 gain を更新する。",
        ],
    ),
    ProgramSpec(
        25,
        "mpc_solarcar/solar_autocal_logic.py",
        "自動校正ロジック関数群",
        "runtime helper",
        "solar_autocal_node が使う昼間停止時 aux 推定などの純ロジック関数をまとめる。",
        "Node から切り出された小さな判定ロジック。",
        called_from=["mpc_solarcar/solar_autocal_node.py"],
        next_read=[],
        key_points=[
            "Node 依存を持たないので単体試験しやすい。",
        ],
    ),
    ProgramSpec(
        26,
        "mpc_solarcar/speed_command_bridge_node.py",
        "planner 指令の安全橋渡し",
        "runtime node",
        "planner/speed_cmd と drive_mode を受け、起動直後や system state を見ながら安全な出力 topic/UDP に整形する。",
        "実機へ出る直前のガード層。",
        called_from=["mpc_solarcar/live_launch.py"],
        next_read=["mpc_solarcar/solar_preflight_logic.py"],
        key_points=[
            "rate limiter と command gate を持つ。",
            "planner の生指令をそのまま実車へは出さない。",
        ],
    ),
    ProgramSpec(
        27,
        "mpc_solarcar/solar_preflight_node.py",
        "live 計測鮮度監視",
        "runtime node",
        "speed、distance、battery、planner status の鮮度を見て system/state と health を publish する。",
        "起動可否と運用中の健全性の監視役。",
        called_from=["mpc_solarcar/live_launch.py", "launch/solar_measurement.launch.py"],
        next_read=["mpc_solarcar/solar_preflight_logic.py", "mpc_solarcar/speed_command_bridge_node.py"],
        key_points=[
            "planner 自体は止めずに、system/state と health を出す。",
        ],
    ),
    ProgramSpec(
        28,
        "mpc_solarcar/solar_preflight_logic.py",
        "preflight 判定ロジック",
        "runtime helper",
        "計測鮮度や command gate の純判定を Node 本体から切り出したロジック関数群。",
        "preflight と speed bridge の共通判定層。",
        called_from=["mpc_solarcar/solar_preflight_node.py", "mpc_solarcar/speed_command_bridge_node.py"],
        next_read=[],
        key_points=[
            "evaluate_freshness と evaluate_command_gate が中心。",
        ],
    ),
    ProgramSpec(
        29,
        "mpc_solarcar/solar_logger_node.py",
        "solar 運用 CSV logger",
        "runtime node",
        "vehicle、planner、weather、calib、system、raw telemetry を一つの時刻行へ集約して CSV に書く。",
        "運用ログの最終集約点。",
        called_from=["mpc_solarcar/live_launch.py", "launch/solar_measurement.launch.py"],
        next_read=[],
        key_points=[
            "topic 名と CSV 列名の対応を内部辞書で持つ。",
            "planner/env、planner/metrics、planner/status も記録する。",
        ],
    ),
    ProgramSpec(
        30,
        "mpc_solarcar/dashboard_node.py",
        "dashboard + HTTP API",
        "runtime node",
        "planner と vehicle の現在値を ROS から受け、HTTP サーバと dashboard frontend へ渡す。",
        "可視化の中心ノード。",
        called_from=["launch/solarcar_sim.launch.py", "mpc_solarcar/live_launch.py", "launch/solar_measurement.launch.py"],
        next_read=[],
        key_points=[
            "/api/state と /metrics を持つ。",
            "ROS topic を直接 browser へ出すのではなく、Node 内 state に集約する。",
        ],
    ),
    ProgramSpec(
        31,
        "mpc_solarcar/gps_sim_node.py",
        "sim GPS 軌跡ノード",
        "runtime node",
        "planner/speed_cmd を積分して route waypoints 上の現在位置を求め、/sim/gps を publish する。",
        "sim モードの地図上位置源。",
        called_from=["launch/solarcar_sim.launch.py"],
        next_read=["mpc_solarcar/solar_state_node.py"],
        key_points=[
            "純粋に速度指令から位置を進める。",
        ],
    ),
    ProgramSpec(
        32,
        "mpc_solarcar/grade_node.py",
        "実測勾配推定ノード",
        "runtime node",
        "distance と altitude/GPS から grade を推定し /vehicle/grade へ publish する。",
        "measure/live の監視・記録用の grade source。",
        called_from=["launch/solar_measurement.launch.py", "mpc_solarcar/live_launch.py"],
        next_read=[],
        key_points=[
            "現在の solar mpc_node は route profile 勾配を主に使い、/vehicle/grade を直接は使わない。",
            "ただし logger や補助用途では重要。",
        ],
    ),
    ProgramSpec(
        33,
        "scripts/fetch_weather_forecast.py",
        "offline forecast 取得 CLI",
        "offline tool",
        "profile に基づき計画用 weather forecast CSV を取得・保存する CLI スクリプト。",
        "forecast action で直接呼ばれる。",
        called_from=["scripts/solar_control.sh"],
        next_read=["mpc_solarcar/weather_utils.py", "mpc_solarcar/solar_profile.py"],
        key_points=[
            "live node 版より単発実行向け。",
        ],
    ),
    ProgramSpec(
        34,
        "scripts/run_identification_pipeline.py",
        "テンプレ識別パイプライン入口",
        "identification",
        "template package の raw データから地図生成・基礎整備・識別処理を繋ぐ入口。",
        "identify action で呼ばれる。",
        called_from=["scripts/solar_control.sh"],
        next_read=["scripts/run_vehicle_identification.py"],
        key_points=[
            "template/package 初期整備向きの高位入口。",
        ],
    ),
    ProgramSpec(
        35,
        "scripts/run_vehicle_identification.py",
        "フル MLE 同定本体",
        "identification",
        "実車ログ、weather、grounded maps、battery/PV/vehicle モデルを用いて MLE 同定を実行する大型スクリプト。",
        "fit action の本丸。",
        called_from=["scripts/solar_control.sh"],
        next_read=["scripts/generate_fit_fullsim_report.py", "scripts/tune_upper_planner_weights.py"],
        key_points=[
            "出力 tag を持つ immutable run を作る。",
            "adopt までは canonical profile を上書きしない流れに対応する。",
        ],
    ),
    ProgramSpec(
        36,
        "scripts/tune_upper_planner_weights.py",
        "目的関数重み CEM 学習",
        "planning research",
        "複数シナリオで upper planner の cost weight を探索し、risk-aware な candidate を評価する。",
        "learn action の中心。",
        called_from=["scripts/solar_control.sh"],
        next_read=["mpc_solarcar/upper_cost.py", "scripts/solar_sim.py"],
        key_points=[
            "multi-scenario、CVaR、chance gate を扱う。",
            "operational release ではなく exact validation 前段の性格が強い。",
        ],
    ),
    ProgramSpec(
        37,
        "scripts/gpu_upper_policy_search.py",
        "GPU 上位速度列探索",
        "planning research",
        "全レース distance-indexed speed policy を GPU 上で多段 coarse-to-fine に探索する。",
        "本番前の warm start policy 生成側。",
        called_from=["GPU sbatch / shell campaign"],
        next_read=["scripts/validate_gpu_upper_policy_candidates.py", "scripts/run_upper_mesh_convergence.py"],
        key_points=[
            "runtime MPC を置き換えるのではなく warm start policy 候補を作る。",
        ],
    ),
    ProgramSpec(
        38,
        "scripts/run_upper_mesh_convergence.py",
        "upper mesh 収束確認",
        "planning validation",
        "候補 policy や exact replay を距離分解能違いで再計算し、結果が十分収束しているか確認する。",
        "GPU/learned policy の acceptance 前検証。",
        called_from=["validation pipeline", "手動検証"],
        next_read=["scripts/validate_gpu_upper_policy_candidates.py"],
        key_points=[
            "細かい距離メッシュが本当に必要十分かを調べる。",
        ],
    ),
    ProgramSpec(
        39,
        "scripts/validate_gpu_upper_policy_candidates.py",
        "GPU 候補の厳密検証",
        "planning validation",
        "GPU 探索で得た speed policy 候補を CPU 側 exact replay と gate で再判定する。",
        "GPU acceptance の中心。",
        called_from=["GPU acceptance pipeline", "手動検証"],
        next_read=["scripts/run_upper_mesh_convergence.py", "scripts/solar_sim.py"],
        key_points=[
            "numerical match、mission feasibility、gate pass を確認する。",
        ],
    ),
    ProgramSpec(
        40,
        "scripts/generate_fit_fullsim_report.py",
        "同定後 fullsim レポート生成",
        "report",
        "identification run と replay/fullsim の結果をまとめ、説明用レポートへ整形する。",
        "fit の結果説明と評価集約に使う。",
        called_from=["手動レポート生成", "後処理パイプライン"],
        next_read=[],
        key_points=[
            "同定結果と full simulation を一つの説明資料へまとめる。",
        ],
    ),
]


KNOWN_IMPORT_PURPOSES: dict[str, str] = {
    "__future__.annotations": "型ヒントの遅延評価を有効にし、自己参照型や forward reference を安全に扱うため。",
    "argparse": "CLI 引数を宣言し、実行時パラメータを外から受け取るため。",
    "ast": "Python 構文木としてソースを解析するため。",
    "collections.deque": "固定長の時系列や遅延キューを効率よく保持するため。",
    "copy": "設定辞書や payload を安全に複製するため。",
    "csv": "CSV の逐次読込・逐次書込を行うため。",
    "datetime": "UTC 時刻や相対時間を扱うため。",
    "gzip": "detail CSV などの圧縮出力を行うため。",
    "hashlib": "snapshot ID や入力資産の digest を作るため。",
    "html": "HTML report の文字列を安全に埋め込むため。",
    "json": "manifest、checkpoint、UDP payload をやり取りするため。",
    "launch.LaunchDescription": "launch が実行すべき action 群をまとめるため。",
    "launch.actions": "DeclareLaunchArgument や OpaqueFunction など launch action を使うため。",
    "launch.substitutions.LaunchConfiguration": "launch 引数の実行時値を参照するため。",
    "launch_ros.actions.Node": "ROS 2 ノード起動 action を launch から記述するため。",
    "math": "Python標準のスカラー数値関数と定数を使うため。実際に参照する名前と行は使用位置欄で確認する。",
    "numpy": "数値配列、clip、補間、統計計算を行うため。",
    "os": "パス、環境変数、プロセス外部状態を扱うため。",
    "pandas": "CSV や時刻列の読込・整形・再サンプリングに使うため。",
    "pathlib.Path": "ファイルやディレクトリを安全に扱うため。",
    "rclpy": "ROS 2 Python ノードとして起動・spin するため。",
    "rclpy.node.Node": "ROS 2 ノード本体の基底クラスとして使うため。",
    "rclpy.callback_groups": "同一ノード内 callback の排他・並行関係をCallback Groupとして指定するため。",
    "rclpy.executors.MultiThreadedExecutor": "複数 callback group を並列実行する executor を使うため。",
    "scipy.optimize.minimize": "目的関数と制約・boundsに基づく連続数値最適化を解くため。",
    "sensor_msgs.msg.NavSatFix": "GPS 緯度経度高度を ROS topic でやり取りするため。",
    "std_msgs.msg": "Float32、Bool、Stringなどの標準ROS messageで値をpublishまたはsubscribeするため。",
    "nav_msgs.msg.Path": "将来軌跡を dashboard や logger へ出すため。",
    "geometry_msgs.msg.PoseStamped": "Path を構成する waypoint pose を組み立てるため。",
    "subprocess": "git 情報取得や外部コマンド実行を行うため。",
    "time": "wall/monotonic time に基づく周期制御や freshness 判定を行うため。",
    "traceback": "例外時に crash log を残すため。",
    "yaml": "profile、stop、schedule、summary YAML を読み書きするため。",
}


def slugify(path: str) -> str:
    return (
        path.replace("\\", "_")
        .replace("/", "_")
        .replace(".", "_")
        .replace("-", "_")
        .replace(" ", "_")
    )


def tex_escape(text: str) -> str:
    replacements = {
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
    out = []
    for char in str(text):
        out.append(replacements.get(char, char))
    return "".join(out)


def tex_path(path: str) -> str:
    text = str(path)
    if "\n" not in text:
        for delimiter in ("|", "!", ";", "@", "~", "+", "/"):
            if delimiter not in text:
                return rf"\path{delimiter}{text}{delimiter}"
    return r"\texttt{" + tex_escape(text) + "}"


def tex_ref(text: str) -> str:
    value = str(text)
    if re.search(r"[\\/]|\.py\b|\.ps1\b|\.sh\b|\.yaml\b|\.csv\b|\.json\b|\.html\b|\.md\b", value):
        return tex_path(value)
    return tex_escape(value)


def wrap_paragraphs(text: str) -> str:
    chunks = [chunk.strip() for chunk in str(text).splitlines()]
    chunks = [chunk for chunk in chunks if chunk]
    return "\n\n".join(tex_escape(chunk) for chunk in chunks)


def latex_code_block(code: str, language: str = "") -> str:
    header = r"\begin{lstlisting}"
    if language:
        header = rf"\begin{{lstlisting}}[language={language}]"
    return f"{header}\n{code.rstrip()}\n\\end{{lstlisting}}\n"


def rel_path(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def module_name_for_path(path: Path) -> str | None:
    try:
        relative = path.resolve().relative_to(ROOT)
    except ValueError:
        return None
    if relative.suffix != ".py":
        return None
    parts = list(relative.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def module_path_for_name(module_name: str) -> Path | None:
    candidate = ROOT.joinpath(*module_name.split(".")).with_suffix(".py")
    if candidate.is_file():
        return candidate
    init_candidate = ROOT.joinpath(*module_name.split("."), "__init__.py")
    if init_candidate.is_file():
        return init_candidate
    return None


def literal_string(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        value = ast.literal_eval(node)
    except Exception:
        try:
            return ast.unparse(node)
        except Exception:
            return "dynamic"
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if value is None:
        return "None"
    return str(value)


def node_text(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:
        return type(node).__name__


def import_key(item: ImportItem) -> str:
    if item.kind == "import":
        return f"import {', '.join(item.names)}"
    return f"from {item.source} import {', '.join(item.names)}"


def import_binding_names(item: ImportItem) -> list[str]:
    names: list[str] = []
    for raw in item.names:
        if " as " in raw:
            _, alias = raw.split(" as ", 1)
            names.append(alias.strip())
        elif item.kind == "import":
            names.append(raw.split(".", 1)[0].strip())
        else:
            names.append(raw.strip())
    return [name for name in names if name]


def is_dunder_main_guard(node: ast.AST) -> bool:
    if not isinstance(node, ast.If):
        return False
    left = node_text(node.test)
    return "__name__" in left and "__main__" in left


def statement_summary(node: ast.stmt) -> str:
    if isinstance(node, ast.Assign):
        targets = ", ".join(node_text(target) for target in node.targets[:4])
        return f"{targets} に {node_text(node.value)} の結果を代入する。"
    if isinstance(node, ast.AnnAssign):
        return f"{node_text(node.target)} に {node_text(node.value)} を代入する。"
    if isinstance(node, ast.AugAssign):
        return f"{node_text(node.target)} を {type(node.op).__name__} で更新する。"
    if isinstance(node, ast.Return):
        return f"{node_text(node.value)} を返す。"
    if isinstance(node, ast.Expr):
        if isinstance(node.value, ast.Call):
            return f"{node_text(node.value.func)}(...) を実行する。"
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return "docstring または説明文字列を置く。"
        return f"{node_text(node.value)} を評価する。"
    if isinstance(node, ast.If):
        return f"条件 {node_text(node.test)} を判定し、真なら内部処理を行う。"
    if isinstance(node, ast.For):
        return f"{node_text(node.iter)} を順に走査し、各要素を {node_text(node.target)} に入れて処理する。"
    if isinstance(node, ast.AsyncFor):
        return f"{node_text(node.iter)} を非同期に走査し、各要素を {node_text(node.target)} に入れて処理する。"
    if isinstance(node, ast.While):
        return f"条件 {node_text(node.test)} が成り立つ間くり返す。"
    if isinstance(node, ast.With):
        return f"with 文で {', '.join(node_text(item.context_expr) for item in node.items[:3])} を管理しながら処理する。"
    if isinstance(node, ast.AsyncWith):
        return f"async with 文で {', '.join(node_text(item.context_expr) for item in node.items[:3])} を管理しながら処理する。"
    if isinstance(node, ast.Try):
        return "例外処理を伴う try ブロックを実行する。"
    if isinstance(node, ast.Raise):
        return f"{node_text(node.exc)} を送出する。"
    if isinstance(node, ast.FunctionDef):
        return f"関数 {node.name} を定義する。"
    if isinstance(node, ast.AsyncFunctionDef):
        return f"非同期関数 {node.name} を定義する。"
    if isinstance(node, ast.ClassDef):
        return f"クラス {node.name} を定義する。"
    return f"{type(node).__name__} 文を実行する。"


def function_signature_from_node(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    def format_arg(arg: ast.arg, default: ast.expr | None = None, prefix: str = "") -> str:
        value = prefix + arg.arg
        if arg.annotation is not None:
            value += f": {node_text(arg.annotation)}"
        if default is not None:
            value += f" = {node_text(default)}"
        return value

    args = node.args
    positional = list(args.posonlyargs) + list(args.args)
    default_offset = len(positional) - len(args.defaults)
    pieces: list[str] = []
    for idx, arg in enumerate(positional):
        default = args.defaults[idx - default_offset] if idx >= default_offset else None
        pieces.append(format_arg(arg, default))
        if args.posonlyargs and idx + 1 == len(args.posonlyargs):
            pieces.append("/")
    if args.vararg is not None:
        pieces.append(format_arg(args.vararg, prefix="*"))
    elif args.kwonlyargs:
        pieces.append("*")
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        pieces.append(format_arg(arg, default))
    if args.kwarg is not None:
        pieces.append(format_arg(args.kwarg, prefix="**"))
    returns = f" -> {node_text(node.returns)}" if node.returns is not None else ""
    return f"{node.name}({', '.join(pieces)}){returns}"


def build_name_line_map(tree: ast.AST) -> dict[str, list[int]]:
    names: dict[str, set[int]] = {}

    class NameVisitor(ast.NodeVisitor):
        def visit_Name(self, node: ast.Name) -> Any:
            names.setdefault(node.id, set()).add(node.lineno)
            self.generic_visit(node)

    NameVisitor().visit(tree)
    return {key: sorted(value) for key, value in names.items()}


def collect_call_names(node: ast.AST) -> list[str]:
    calls: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.add(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.add(child.func.attr)
    return sorted(calls)


def flatten_statement_steps(
    statements: list[ast.stmt],
    *,
    depth: int = 0,
    max_depth: int = 3,
    max_steps: int = 80,
) -> list[str]:
    steps: list[str] = []

    def add(prefix: str, stmt: ast.stmt) -> None:
        if len(steps) >= max_steps:
            return
        indent = "  " * min(depth, 4)
        steps.append(f"{indent}{prefix}{statement_summary(stmt)}")

    for stmt in statements:
        if len(steps) >= max_steps:
            break
        add("", stmt)
        if depth >= max_depth:
            continue
        if isinstance(stmt, ast.If):
            steps.extend(
                flatten_statement_steps(
                    stmt.body,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_steps=max_steps - len(steps),
                )
            )
            if stmt.orelse and len(steps) < max_steps:
                steps.append(f"{'  ' * min(depth + 1, 4)}上の条件が偽の場合:")
                steps.extend(
                    flatten_statement_steps(
                        stmt.orelse,
                        depth=depth + 1,
                        max_depth=max_depth,
                        max_steps=max_steps - len(steps),
                    )
                )
        elif isinstance(stmt, (ast.For, ast.AsyncFor, ast.While)):
            steps.extend(
                flatten_statement_steps(
                    stmt.body,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_steps=max_steps - len(steps),
                )
            )
        elif isinstance(stmt, (ast.With, ast.AsyncWith)):
            steps.extend(
                flatten_statement_steps(
                    stmt.body,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_steps=max_steps - len(steps),
                )
            )
        elif isinstance(stmt, ast.Try):
            steps.extend(
                flatten_statement_steps(
                    stmt.body,
                    depth=depth + 1,
                    max_depth=max_depth,
                    max_steps=max_steps - len(steps),
                )
            )
            for handler in stmt.handlers:
                if len(steps) >= max_steps:
                    break
                exception_name = node_text(handler.type) if handler.type is not None else "すべての例外"
                steps.append(f"{'  ' * min(depth + 1, 4)}{exception_name}を捕捉した場合:")
                steps.extend(
                    flatten_statement_steps(
                        handler.body,
                        depth=depth + 1,
                        max_depth=max_depth,
                        max_steps=max_steps - len(steps),
                    )
                )
            if stmt.finalbody and len(steps) < max_steps:
                steps.append(f"{'  ' * min(depth + 1, 4)}成否にかかわらずfinallyで:")
                steps.extend(
                    flatten_statement_steps(
                        stmt.finalbody,
                        depth=depth + 1,
                        max_depth=max_depth,
                        max_steps=max_steps - len(steps),
                    )
                )
    return steps[:max_steps]


def collect_assigned_names(node: ast.AST) -> list[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
    return sorted(names)


def collect_self_attributes(node: ast.AST) -> tuple[list[str], list[str]]:
    reads: set[str] = set()
    writes: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Attribute):
            continue
        if not isinstance(child.value, ast.Name) or child.value.id != "self":
            continue
        if isinstance(child.ctx, (ast.Store, ast.Del)):
            writes.add(child.attr)
        else:
            reads.add(child.attr)
    return sorted(reads), sorted(writes)


def syntax_notes_for_node(node: ast.AST) -> list[str]:
    notes: list[str] = []
    if isinstance(node, ast.ClassDef):
        notes.append("class文は新しい型を定義する。丸括弧内は継承する基底クラスである。")
        if node.decorator_list:
            notes.append("@で始まる行は、定義したクラスを加工するdecoratorである。")
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.args.args and node.args.args[0].arg == "self":
            notes.append("第1引数selfは、このメソッドを呼んだインスタンス自身を受け取る慣習名である。")
        if node.decorator_list:
            notes.append("@で始まる行は、定義した関数を別の関数へ渡して加工するdecoratorである。")
        if node.returns is not None:
            notes.append("`->`以後は戻り値の型注釈であり、実行時の値を自動変換する命令ではない。")
    if any(isinstance(child, ast.Lambda) for child in ast.walk(node)):
        notes.append("lambdaは名前を付けずに短い関数オブジェクトを作る構文である。")
    if any(isinstance(child, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)) for child in ast.walk(node)):
        notes.append("内包表記は、反復・条件・値生成を一つの式で記述してcollectionを作る。")
    if any(isinstance(child, (ast.With, ast.AsyncWith)) for child in ast.walk(node)):
        notes.append("with文はcontext managerに開始・終了処理を任せ、ファイルなどの資源を確実に解放する。")
    if any(isinstance(child, ast.Try) for child in ast.walk(node)):
        notes.append("try文は例外が起き得る処理と、異常時または終了時の経路を分ける。")
    if any(isinstance(child, (ast.Yield, ast.YieldFrom)) for child in ast.walk(node)):
        notes.append("yieldを含むため、通常関数ではなく途中状態を保持するgeneratorとして動く。")
    return notes


def iter_definition_nodes(tree: ast.Module) -> list[tuple[str, ast.AST]]:
    found: list[tuple[str, ast.AST]] = []

    def visit_body(body: list[ast.stmt], owner: str = "") -> None:
        for node in body:
            if isinstance(node, ast.ClassDef):
                qualified = f"{owner}.{node.name}" if owner else node.name
                found.append((owner, node))
                visit_body(node.body, qualified)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = f"{owner}.{node.name}" if owner else node.name
                found.append((owner, node))
                visit_body(node.body, qualified)

    visit_body(tree.body)
    found.sort(key=lambda item: int(getattr(item[1], "lineno", 0)))
    return found


def build_import_use_lines(imports: list[ImportItem], name_line_map: dict[str, list[int]]) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for item in imports:
        lines: set[int] = set()
        for binding in import_binding_names(item):
            for lineno in name_line_map.get(binding, []):
                if lineno != item.lineno:
                    lines.add(lineno)
        out[import_key(item)] = sorted(lines)
    return out


def build_block_detail(text: str, node: ast.AST, owner: str = "") -> BlockDetail:
    source_lines = text.splitlines()
    start = max(1, int(getattr(node, "lineno", 1)))
    end = int(getattr(node, "end_lineno", start))
    if end < start:
        end = start
    excerpt_lines = source_lines[start - 1 : min(end, start + 34)]
    excerpt = "\n".join(excerpt_lines)
    if len(excerpt_lines) < (end - start + 1):
        excerpt += "\n..."

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        body_nodes = list(node.body)
        if body_nodes and isinstance(body_nodes[0], ast.Expr) and isinstance(getattr(body_nodes[0], "value", None), ast.Constant) and isinstance(body_nodes[0].value.value, str):
            body_nodes = body_nodes[1:]
        returns = [node_text(child.value) for child in ast.walk(node) if isinstance(child, ast.Return) and child.value is not None]
        self_reads, self_writes = collect_self_attributes(node)
        raises = [
            node_text(child.exc)
            for child in ast.walk(node)
            if isinstance(child, ast.Raise) and child.exc is not None
        ]
        return BlockDetail(
            name=f"{owner}.{node.name}" if owner else node.name,
            lineno=start,
            kind="async function" if isinstance(node, ast.AsyncFunctionDef) else "function",
            end_lineno=end,
            owner=owner,
            signature=function_signature_from_node(node),
            docstring=(ast.get_docstring(node) or "").strip(),
            return_summary=" / ".join(returns[:4]),
            local_calls=collect_call_names(node),
            steps=flatten_statement_steps(body_nodes),
            source_excerpt=excerpt,
            assigned_names=collect_assigned_names(node),
            self_reads=self_reads,
            self_writes=self_writes,
            raised_exceptions=sorted(set(raises)),
            syntax_notes=syntax_notes_for_node(node),
            branch_count=sum(isinstance(child, ast.If) for child in ast.walk(node)),
            loop_count=sum(isinstance(child, (ast.For, ast.AsyncFor, ast.While)) for child in ast.walk(node)),
            try_count=sum(isinstance(child, ast.Try) for child in ast.walk(node)),
        )

    if isinstance(node, ast.ClassDef):
        bases = ", ".join(node_text(base) for base in node.bases) or "none"
        steps = [statement_summary(stmt) for stmt in node.body[:12]]
        return BlockDetail(
            name=f"{owner}.{node.name}" if owner else node.name,
            lineno=start,
            kind="class",
            end_lineno=end,
            owner=owner,
            signature=f"{node.name}(bases={bases})",
            docstring=(ast.get_docstring(node) or "").strip(),
            local_calls=[],
            steps=steps,
            source_excerpt=excerpt,
            syntax_notes=syntax_notes_for_node(node),
        )

    return BlockDetail(
        name=type(node).__name__,
        lineno=start,
        kind="block",
        end_lineno=end,
        owner=owner,
        steps=[statement_summary(node)] if isinstance(node, ast.stmt) else [],
        source_excerpt=excerpt,
    )


def build_top_level_steps(tree: ast.Module) -> list[TopLevelStep]:
    steps: list[TopLevelStep] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) and isinstance(node.value.value, str):
            continue
        steps.append(TopLevelStep(int(getattr(node, "lineno", 1)), statement_summary(node)))
    return steps


class ProgramVisitor(ast.NodeVisitor):
    def __init__(self, path: Path) -> None:
        self.path = path
        self.imports: list[ImportItem] = []
        self.classes: list[SymbolItem] = []
        self.functions: list[SymbolItem] = []
        self.parameters: list[CallItem] = []
        self.publishers: list[CallItem] = []
        self.subscriptions: list[CallItem] = []
        self.timers: list[CallItem] = []
        self.cli_args: list[CallItem] = []
        self.launch_nodes: list[CallItem] = []

    def visit_Import(self, node: ast.Import) -> Any:
        names = [alias.name if alias.asname is None else f"{alias.name} as {alias.asname}" for alias in node.names]
        self.imports.append(ImportItem(node.lineno, "", names, "import"))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        dots = "." * node.level
        source = f"{dots}{node.module or ''}"
        names = [alias.name if alias.asname is None else f"{alias.name} as {alias.asname}" for alias in node.names]
        self.imports.append(ImportItem(node.lineno, source, names, "from"))
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> Any:
        bases = []
        for base in node.bases:
            try:
                bases.append(ast.unparse(base))
            except Exception:
                pass
        detail = f"bases: {', '.join(bases)}" if bases else ""
        self.classes.append(SymbolItem(node.name, node.lineno, detail))
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        args = [arg.arg for arg in node.args.args]
        detail = f"args: {', '.join(args)}" if args else ""
        self.functions.append(SymbolItem(node.name, node.lineno, detail))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        args = [arg.arg for arg in node.args.args]
        detail = f"args: {', '.join(args)}" if args else ""
        self.functions.append(SymbolItem(node.name, node.lineno, detail))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> Any:
        func_name = ""
        if isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id
        if func_name == "declare_parameter":
            name = literal_string(node.args[0]) if node.args else "dynamic"
            default = literal_string(node.args[1]) if len(node.args) >= 2 else ""
            self.parameters.append(CallItem(node.lineno, name, default))
        elif func_name == "create_publisher":
            topic = literal_string(node.args[1]) if len(node.args) >= 2 else ""
            self.publishers.append(CallItem(node.lineno, topic or "dynamic topic", "publisher"))
        elif func_name == "create_subscription":
            topic = literal_string(node.args[1]) if len(node.args) >= 2 else ""
            callback = literal_string(node.args[2]) if len(node.args) >= 3 else ""
            self.subscriptions.append(CallItem(node.lineno, topic or "dynamic topic", callback))
        elif func_name == "create_timer":
            period = literal_string(node.args[0]) if node.args else ""
            callback = literal_string(node.args[1]) if len(node.args) >= 2 else ""
            self.timers.append(CallItem(node.lineno, period or "dynamic period", callback))
        elif func_name == "add_argument":
            name = literal_string(node.args[0]) if node.args else "dynamic"
            self.cli_args.append(CallItem(node.lineno, name))
        elif func_name == "Node":
            executable = ""
            package = ""
            name = ""
            for keyword in node.keywords:
                if keyword.arg == "executable":
                    executable = literal_string(keyword.value)
                elif keyword.arg == "package":
                    package = literal_string(keyword.value)
                elif keyword.arg == "name":
                    name = literal_string(keyword.value)
            detail = f"package={package}, name={name}" if package or name else ""
            self.launch_nodes.append(CallItem(node.lineno, executable or "dynamic executable", detail))
        self.generic_visit(node)


def analyze_python(spec: ProgramSpec, path: Path, text: str) -> ProgramAnalysis:
    analysis = ProgramAnalysis(spec=spec, text=text)
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return analysis
    analysis.docstring = ast.get_docstring(tree) or ""
    visitor = ProgramVisitor(path)
    visitor.visit(tree)
    analysis.imports = visitor.imports
    analysis.classes = visitor.classes
    analysis.functions = visitor.functions
    analysis.parameters = visitor.parameters
    analysis.publishers = visitor.publishers
    analysis.subscriptions = visitor.subscriptions
    analysis.timers = visitor.timers
    analysis.cli_args = visitor.cli_args
    analysis.launch_nodes = visitor.launch_nodes
    name_line_map = build_name_line_map(tree)
    analysis.import_use_lines = build_import_use_lines(analysis.imports, name_line_map)
    analysis.top_level_steps = build_top_level_steps(tree)
    analysis.block_details = [
        build_block_detail(text, node, owner)
        for owner, node in iter_definition_nodes(tree)
    ]
    analysis.local_dependencies = sorted(filter(None, {resolve_local_dependency(path, item.source) for item in analysis.imports if item.kind == "from"}))
    return analysis


def analyze_shell_like(spec: ProgramSpec, path: Path, text: str) -> ProgramAnalysis:
    analysis = ProgramAnalysis(spec=spec, text=text)
    for lineno, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("function "):
            name = stripped.split()[1].split("{")[0].strip()
            analysis.shell_functions.append(CallItem(lineno, name))
        elif re.match(r"^[A-Za-z0-9_-]+\(\)\s*\{", stripped):
            name = stripped.split("(", 1)[0].strip()
            analysis.shell_functions.append(CallItem(lineno, name))
        elif re.match(r"^'[^']+'\s*\{", stripped):
            label = stripped.split("'", 2)[1]
            analysis.shell_actions.append(CallItem(lineno, label))
        elif re.match(r"^[A-Za-z0-9_-]+\)", stripped):
            label = stripped[:-1].strip()
            analysis.shell_actions.append(CallItem(lineno, label))
        if any(token in stripped for token in ("ros2 launch", "python3 ", "python ", "docker ", "colcon ", "wsl.exe", "bash ")):
            analysis.external_commands.append(CallItem(lineno, stripped))
        if stripped and not stripped.startswith("#"):
            analysis.top_level_steps.append(TopLevelStep(lineno, stripped))
    return analysis


def resolve_local_dependency(current_path: Path, source: str) -> str | None:
    current_module = module_name_for_path(current_path)
    if not current_module:
        return None
    if not source:
        return None
    module_name = source
    if source.startswith("."):
        package = current_module.rsplit(".", 1)[0]
        try:
            module_name = importlib.util.resolve_name(source, package)
        except Exception:
            return None
    module_path = module_path_for_name(module_name)
    if module_path is None:
        return None
    return rel_path(module_path)


def analyze_program(spec: ProgramSpec) -> ProgramAnalysis:
    path = ROOT / spec.path
    text = path.read_text(encoding="utf-8-sig")
    suffix = path.suffix.lower()
    if suffix == ".py":
        return analyze_python(spec, path, text)
    if suffix in {".ps1", ".sh"}:
        return analyze_shell_like(spec, path, text)
    return ProgramAnalysis(spec=spec, text=text)


def summarize_kind(spec: ProgramSpec) -> str:
    suffix = Path(spec.path).suffix.lower()
    if spec.path.endswith(".launch.py"):
        return "ROS 2 launch Python"
    if suffix == ".py":
        return "Python"
    if suffix == ".ps1":
        return "PowerShell"
    if suffix == ".sh":
        return "Bash"
    return suffix or "text"


def import_description(item: ImportItem, current_path: Path, module_title_map: dict[str, str]) -> str:
    if item.kind == "import":
        parts = []
        for name in item.names:
            key = name.split(" as ", 1)[0]
            parts.append(KNOWN_IMPORT_PURPOSES.get(key, f"{key} モジュールを利用するため。"))
        return " ".join(parts)
    if len(item.names) == 1:
        key = f"{item.source}.{item.names[0]}".strip(".")
        if key in KNOWN_IMPORT_PURPOSES:
            return KNOWN_IMPORT_PURPOSES[key]
    if item.source.startswith(".") or item.source.startswith("mpc_solarcar.") or item.source.startswith("scripts."):
        local_dep = resolve_local_dependency(current_path, item.source)
        if local_dep:
            local_module = module_name_for_path(ROOT / local_dep) or ""
            title = module_title_map.get(local_module, Path(local_dep).name)
            joined = ", ".join(item.names)
            return f"{title} から {joined} を読み込み、このファイルの内部処理を分担させるため。"
    key = item.source.strip(".")
    if key in KNOWN_IMPORT_PURPOSES:
        return KNOWN_IMPORT_PURPOSES[key]
    if item.source.startswith("std_msgs.msg"):
        return "ROS 2 標準メッセージ型を使い、軽量な数値や文字列を topic でやり取りするため。"
    if item.source.startswith("sensor_msgs.msg"):
        return "ROS 2 センサメッセージ型を使い、GPS などの外界観測を topic 化するため。"
    if item.source.startswith("nav_msgs.msg"):
        return "Path のような軌跡メッセージを publish するため。"
    if item.source.startswith("geometry_msgs.msg"):
        return "位置姿勢メッセージを組み立てるため。"
    names = ", ".join(item.names)
    return f"{item.source or 'module'} から {names} を読み込み、このファイルの処理を組み立てるため。"


def import_evidence_text(
    analysis: ProgramAnalysis,
    item: ImportItem,
    current_path: Path,
    module_title_map: dict[str, str],
) -> str:
    base = import_description(item, current_path, module_title_map)
    detail_parts = [base]
    local_dep = resolve_local_dependency(current_path, item.source) if item.kind == "from" else None
    if local_dep:
        detail_parts.append(f"実体ファイルは {local_dep}。")
    use_lines = analysis.import_use_lines.get(import_key(item), [])
    if use_lines:
        preview = ", ".join(f"L{line}" for line in use_lines[:8])
        if len(use_lines) > 8:
            preview += ", ..."
        detail_parts.append(f"このファイル内での主な使用位置は {preview}。")
    else:
        detail_parts.append("このファイル内での使用位置は少ないか、間接利用である。")
    return " ".join(detail_parts)


def top_level_summary(analysis: ProgramAnalysis) -> str:
    classes = [item.name for item in analysis.classes if not item.name.startswith("_")]
    funcs = [item.name for item in analysis.functions if not item.name.startswith("_")]
    parts = []
    if classes:
        parts.append(f"主要クラスは {', '.join(classes[:6])}。")
    if funcs:
        parts.append(f"主要関数は {', '.join(funcs[:8])}。")
    if analysis.parameters:
        parts.append(f"ROS パラメータ宣言は {len(analysis.parameters)} 件。")
    if analysis.publishers or analysis.subscriptions:
        parts.append(
            f"ROS I/O は publisher {len(analysis.publishers)} 件、subscription {len(analysis.subscriptions)} 件。"
        )
    if analysis.cli_args:
        parts.append(f"CLI 引数宣言は {len(analysis.cli_args)} 件。")
    if analysis.launch_nodes:
        parts.append(f"launch から起動する Node action は {len(analysis.launch_nodes)} 件。")
    if analysis.shell_actions:
        parts.append(f"action 分岐は {len(analysis.shell_actions)} 件。")
    return " ".join(parts)


def short_list(items: list[str]) -> str:
    if not items:
        return "特になし。"
    return " / ".join(tex_path(item) for item in items)


def code_excerpt(text: str, start: int, end: int) -> str:
    lines = text.splitlines()
    start_idx = max(0, start - 1)
    end_idx = min(len(lines), end)
    return "\n".join(lines[start_idx:end_idx]).strip()


def important_excerpt(analysis: ProgramAnalysis) -> tuple[str, str]:
    path = ROOT / analysis.spec.path
    suffix = path.suffix.lower()
    if suffix == ".py":
        if analysis.launch_nodes:
            line = analysis.launch_nodes[0].lineno
            return code_excerpt(analysis.text, max(1, line - 4), line + 10), "Python"
        if analysis.classes:
            line = analysis.classes[0].lineno
            return code_excerpt(analysis.text, max(1, line - 3), line + 18), "Python"
        if analysis.functions:
            line = analysis.functions[0].lineno
            return code_excerpt(analysis.text, max(1, line - 3), line + 18), "Python"
    elif suffix == ".ps1":
        return code_excerpt(analysis.text, 1, 70), ""
    elif suffix == ".sh":
        return code_excerpt(analysis.text, 1, 80), ""
    return code_excerpt(analysis.text, 1, 40), ""


def build_generic_flow(analysis: ProgramAnalysis) -> list[str]:
    spec = analysis.spec
    if spec.flow_steps:
        return spec.flow_steps
    path = ROOT / spec.path
    if spec.path.endswith(".launch.py"):
        steps = ["launch 引数を受け取り、profile を読み込む。"]
        if analysis.launch_nodes:
            steps.append("Node action を動的に組み立てる。")
            steps.append("LaunchDescription として ROS 2 launch へ返す。")
        return steps
    if path.suffix.lower() == ".py":
        steps = []
        if analysis.parameters:
            steps.append("初期化時に設定値や入力パスを読み込む。")
        if analysis.publishers or analysis.subscriptions:
            steps.append("publisher / subscription / timer を準備する。")
        if analysis.timers:
            steps.append("timer callback 周期で主処理を進める。")
        if analysis.cli_args:
            steps.append("CLI 引数を解釈し、main() から処理を起動する。")
        return steps or ["ソース中の主要関数を通じて処理を進める。"]
    if path.suffix.lower() in {".ps1", ".sh"}:
        return [
            "外部から action / mode / path を受け取る。",
            "条件分岐で launch か script 実行へ振り分ける。",
            "必要な外部コマンドを呼び出す。",
        ]
    return ["テキスト定義に従って処理を記述する。"]


def markdown_block_details(analysis: ProgramAnalysis) -> list[str]:
    lines: list[str] = []
    for block in analysis.block_details:
        kind_label = {
            "function": "関数",
            "async function": "非同期関数",
            "class": "クラス",
        }.get(block.kind, block.kind)
        lines.extend(
            [
                f"### L{block.lineno} {kind_label} `{block.name}`",
                "",
                f"- 定義: `{block.signature or block.name}`",
                f"- 行範囲: L{block.lineno}-L{block.end_lineno or block.lineno}",
            ]
        )
        if block.owner:
            lines.append(f"- 所属: `{block.owner}`")
        if block.docstring:
            lines.append(f"- docstring: {block.docstring}")
        if block.local_calls:
            lines.append(f"- このブロックが直接呼ぶ主な関数/メソッド: {', '.join(f'`{item}`' for item in block.local_calls[:12])}")
        if block.return_summary:
            lines.append(f"- 戻り値の要点: `{block.return_summary}`")
        if block.assigned_names:
            lines.append(f"- この呼出し内で代入する主なローカル名: {', '.join(f'`{item}`' for item in block.assigned_names[:20])}")
        if block.self_reads:
            lines.append(f"- 読み取る主なインスタンス属性: {', '.join(f'`self.{item}`' for item in block.self_reads[:24])}")
        if block.self_writes:
            lines.append(f"- 更新する主なインスタンス属性: {', '.join(f'`self.{item}`' for item in block.self_writes[:24])}")
        if block.raised_exceptions:
            lines.append(f"- 明示的に送出する例外: {', '.join(f'`{item}`' for item in block.raised_exceptions)}")
        lines.append(
            f"- 制御構造の規模: 条件分岐 {block.branch_count}、ループ {block.loop_count}、try {block.try_count}"
        )
        if block.syntax_notes:
            lines.append("- この定義を読むためのPython構文:")
            for note in block.syntax_notes:
                lines.append(f"  - {note}")
        if block.steps:
            lines.extend(["- 上から順の処理:"])
            for idx, step in enumerate(block.steps, start=1):
                lines.append(f"  {idx}. {step}")
        if block.source_excerpt:
            lines.extend(
                [
                    "",
                    "代表コード断片:",
                    "",
                    "```python",
                    block.source_excerpt,
                    "```",
                ]
            )
        lines.append("")
    return lines


def tex_block_details(analysis: ProgramAnalysis) -> str:
    sections: list[str] = []
    for block in analysis.block_details:
        kind_label = {
            "function": "関数",
            "async function": "非同期関数",
            "class": "クラス",
        }.get(block.kind, block.kind)
        call_text = ", ".join(block.local_calls[:12]) if block.local_calls else "特に明示されていない。"
        assigned_text = ", ".join(block.assigned_names[:20]) if block.assigned_names else "特になし。"
        read_text = ", ".join(f"self.{item}" for item in block.self_reads[:24]) if block.self_reads else "特になし。"
        write_text_value = ", ".join(f"self.{item}" for item in block.self_writes[:24]) if block.self_writes else "特になし。"
        exception_text = ", ".join(block.raised_exceptions) if block.raised_exceptions else "明示的raiseはない。"
        step_items = "\n".join(rf"\item {tex_escape(step)}" for step in block.steps) or r"\item 本体が短く、処理段階は少ない。"
        syntax_items = "\n".join(rf"\item {tex_escape(note)}" for note in block.syntax_notes) or r"\item 特別な構文上の補足は少ない。"
        excerpt = latex_code_block(block.source_excerpt, "Python") if block.source_excerpt else ""
        section = textwrap.dedent(
            rf"""
            \subsection*{{L{block.lineno} {tex_escape(kind_label)} {tex_escape(block.name)}}}
            \begin{{itemize}}[leftmargin=1.6em]
              \item 行範囲: L{block.lineno}--L{block.end_lineno or block.lineno}
              \item 所属: {tex_path(block.owner) if block.owner else 'module直下'}
              \item 定義: {tex_path(block.signature or block.name)}
              \item docstring: {tex_escape(block.docstring) if block.docstring else '明示されていない。'}
              \item このブロックが直接呼ぶ主な関数・メソッド: {tex_escape(call_text)}
              \item 戻り値の要点: {tex_escape(block.return_summary) if block.return_summary else '戻り値が無いか、return 文が明示されていない。'}
              \item 主なローカル代入名: {tex_escape(assigned_text)}
              \item 読み取る主なインスタンス属性: {tex_escape(read_text)}
              \item 更新する主なインスタンス属性: {tex_escape(write_text_value)}
              \item 明示的に送出する例外: {tex_escape(exception_text)}
              \item 制御構造の規模: 条件分岐 {block.branch_count}、ループ {block.loop_count}、try {block.try_count}
            \end{{itemize}}
            \paragraph{{この定義を読むためのPython構文}}
            \begin{{itemize}}[leftmargin=1.6em]
            {syntax_items}
            \end{{itemize}}
            \paragraph{{上から順の処理}}
            \begin{{enumerate}}[leftmargin=1.8em]
            {step_items}
            \end{{enumerate}}
            \paragraph{{代表コード断片}}
            {excerpt}
            """
        ).strip()
        sections.append(section)
    return "\n\n".join(sections)


def concept_keys_for_analysis(analysis: ProgramAnalysis) -> list[str]:
    path = analysis.spec.path
    text = analysis.text
    suffix = Path(path).suffix.lower()
    keys: list[str] = []

    def add(*values: str) -> None:
        for value in values:
            if value in CONCEPTS_BY_KEY and value not in keys:
                keys.append(value)

    if suffix == ".py":
        add(
            "program_process_memory",
            "names_assignment_types",
            "functions_arguments_scope",
            "imports_packages_entrypoints",
            "exceptions_context_resources",
        )
    elif suffix in {".ps1", ".sh"}:
        add("program_process_memory", "cli_shell_environment", "exceptions_context_resources")
    if analysis.classes:
        add("classes_objects_self", "underscore_dunder")
    if "@dataclass" in text or "from dataclasses import" in text:
        add("decorators_dataclass")
    if "numpy" in text or "np." in text or "pandas" in text or "pd." in text:
        add("collections_numpy_pandas")
    if "argparse" in text or analysis.cli_args:
        add("cli_shell_environment")
    if "rclpy" in text or analysis.publishers or analysis.subscriptions:
        add("ros_stack", "ros_graph_interfaces", "ros_executor_callbacks", "ros_debug_tools")
    if path.endswith(".launch.py") or "launch_ros.actions" in text:
        add("ros_launch_runtime")
    if "minimize(" in text or "shgo(" in text or "optimize" in text:
        add("numerical_optimization")
    if "cem_" in text or "Cross-Entropy" in text or "cross entropy" in text.lower():
        add("cem")
    if "warm_start" in text or "initial_upper_policy" in text:
        add("warm_start")
    if "electrical_balance" in text or "resistive_forces" in text or path.endswith("/model.py"):
        add("vehicle_energy_model")
    if "BatteryMHE" in text or "MheInput" in text or "soc_step" in text:
        add("battery_model_mhe")
    if "forecast" in text or "route_profile" in text or "timezone" in text:
        add("forecast_route_time")
    if "fresh_enough" in text or "guard" in text or "fallback" in text:
        add("freshness_safety_fallback")
    if any(token in path for token in ("identification", "forecast", "mesh", "validate", "report")):
        add("data_contract_validation", "testing_observability")
    if "mpc" in path.lower() or "_mpc" in text:
        add("control_mpc")
    if "lower_mpc" in text or "hierarchical" in text:
        add("hierarchical_mpc")
    add(*PROGRAM_EXTRA_CONCEPTS.get(path, []))
    return keys


def markdown_items(items: list[dict[str, str]]) -> list[str]:
    lines: list[str] = []
    for item in items:
        kind = item.get("kind", "p")
        text = str(item.get("text", ""))
        if kind == "p":
            lines.extend([text, ""])
        elif kind == "flow":
            lines.extend(["```text", text, "```", ""])
        elif kind == "code":
            lines.extend([f"```{item.get('language', '')}", text, "```", ""])
        elif kind == "equation":
            lines.extend(["$$", text, "$$", ""])
        elif kind == "bullet":
            lines.extend([f"- {part}" for part in text.splitlines() if part.strip()])
            lines.append("")
    return lines


def markdown_chapter(chapter: dict[str, Any], level: int = 3) -> list[str]:
    lines = [f"{'#' * level} {chapter['title']}", ""]
    lines.extend(markdown_items(chapter.get("items", [])))
    sources = chapter.get("sources", [])
    if sources:
        lines.extend(["根拠資料:", ""])
        for key in sources:
            source = REFERENCE_SOURCES.get(key)
            if source:
                lines.append(f"- [{source['label']}]({source['url']})")
        lines.append("")
    return lines


def tex_items(items: list[dict[str, str]]) -> str:
    rendered: list[str] = []
    for item in items:
        kind = item.get("kind", "p")
        text = str(item.get("text", ""))
        if kind == "p":
            rendered.append(tex_escape(text) + "\n")
        elif kind == "flow":
            rendered.append(latex_code_block(text, ""))
        elif kind == "code":
            rendered.append(latex_code_block(text, str(item.get("language", ""))))
        elif kind == "equation":
            rendered.append("\\[\n" + text + "\n\\]")
        elif kind == "bullet":
            bullet_items = "\n".join(
                rf"\item {tex_escape(part)}" for part in text.splitlines() if part.strip()
            )
            rendered.append(
                "\\begin{itemize}[leftmargin=1.6em]\n"
                + bullet_items
                + "\n\\end{itemize}"
            )
    return "\n\n".join(rendered)


def tex_chapter(chapter: dict[str, Any], command: str = "subsection*") -> str:
    source_lines: list[str] = []
    for key in chapter.get("sources", []):
        source = REFERENCE_SOURCES.get(key)
        if source:
            source_lines.append(
                rf"\item \href{{{source['url']}}}{{{tex_escape(source['label'])}}}"
            )
    source_block = ""
    if source_lines:
        source_block = (
            "\\paragraph{根拠資料}\n"
            "\\begin{itemize}[leftmargin=1.6em]\n"
            + "\n".join(source_lines)
            + "\n\\end{itemize}"
        )
    return (
        rf"\{command}{{{tex_escape(str(chapter['title']))}}}"
        + "\n"
        + tex_items(chapter.get("items", []))
        + "\n"
        + source_block
    )


def markdown_foundations() -> str:
    lines = [
        "# ソーラーカーMPCプログラムを読むための基礎知識",
        "",
        f"- 生成日: {GENERATION_DATE}",
        "- 対象: Python、OS、ROS 2、数値最適化、MPC、車両・電池モデル",
        "",
        "この総論は、各プログラム解説で前提になる言葉を、プログラム経験を仮定せずに説明する。"
        "各個別PDFにも、そのファイルで必要な章を再掲する。",
        "",
    ]
    for chapter in FOUNDATION_CHAPTERS:
        lines.extend(markdown_chapter(chapter, level=2))
    return "\n".join(lines).rstrip() + "\n"


def common_tex_preamble(title: str) -> str:
    return textwrap.dedent(
        rf"""
        \documentclass[a4paper,11pt]{{article}}
        \usepackage[top=15mm,bottom=18mm,left=16mm,right=16mm]{{geometry}}
        \usepackage{{fontspec}}
        \usepackage{{xeCJK}}
        \setmainfont{{Times New Roman}}
        \setCJKmainfont{{Yu Gothic}}
        \setmonofont{{Consolas}}
        \setCJKmonofont{{Yu Gothic}}
        \usepackage{{booktabs}}
        \usepackage{{longtable}}
        \usepackage{{tabularx}}
        \usepackage{{array}}
        \usepackage{{enumitem}}
        \usepackage{{hyperref}}
        \usepackage{{listings}}
        \usepackage{{xcolor}}
        \usepackage{{amsmath}}
        \usepackage{{amssymb}}
        \hypersetup{{
          colorlinks=true,
          linkcolor=blue,
          urlcolor=blue,
          pdftitle={{{tex_escape(title)}}},
          pdfauthor={{Codex}}
        }}
        \lstset{{
          basicstyle=\ttfamily\small,
          breaklines=true,
          columns=fullflexible,
          keepspaces=true,
          frame=single,
          framerule=0.2pt,
          rulecolor=\color{{black}},
          showstringspaces=false
        }}
        \setlength{{\parskip}}{{0.42em}}
        \setlength{{\parindent}}{{1em}}
        \setlength{{\emergencystretch}}{{3em}}
        \renewcommand{{\arraystretch}}{{1.15}}
        """
    ).strip()


def finalize_tex_document(document: str) -> str:
    """Register generated headings in the table of contents."""
    return (
        document.replace(r"\section*{", r"\section{")
        .replace(r"\subsection*{", r"\subsection{")
        .replace(r"\subsubsection*{", r"\subsubsection{")
    )


def foundations_tex() -> str:
    chapters = "\n\n".join(tex_chapter(chapter, "section*") for chapter in FOUNDATION_CHAPTERS)
    return finalize_tex_document(
        (
            common_tex_preamble("ソーラーカーMPCプログラムを読むための基礎知識")
            + "\n"
            + textwrap.dedent(
                rf"""
                \title{{ソーラーカーMPCプログラムを読むための基礎知識}}
                \author{{solar\_ws0129-main}}
                \date{{{GENERATION_DATE}}}
                \begin{{document}}
                \maketitle
                \tableofcontents
                \clearpage

                本総論は、各プログラム解説で前提になるPython、OS、ROS 2、
                数値最適化、MPC、車両・電池モデルを、初学者向けに説明する。
                各個別PDFにも、そのファイルで必要な章を再掲する。

                {chapters}

                \end{{document}}
                """
            ).strip()
            + "\n"
        )
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def markdown_for_analysis(analysis: ProgramAnalysis, module_title_map: dict[str, str]) -> str:
    spec = analysis.spec
    source_hash = file_sha256(ROOT / spec.path)
    lines = [
        f"# {spec.order:02d}. {spec.title}",
        "",
        f"- ファイル: `{spec.path}`",
        f"- ソースSHA-256: `{source_hash}`",
        f"- 種別: `{summarize_kind(spec)}`",
        f"- 区分: `{spec.category}`",
        "",
        "## 役割",
        "",
        spec.purpose,
        "",
        "## 起動文脈",
        "",
        f"- 起動文脈: {spec.startup_context}",
        f"- 呼び出し元: {', '.join(f'`{item}`' for item in spec.called_from) if spec.called_from else '特になし'}",
        f"- 次に読むべきファイル: {', '.join(f'`{item}`' for item in spec.next_read) if spec.next_read else '特になし'}",
        "",
        "## 主要ポイント",
        "",
    ]
    for point in spec.key_points:
        lines.append(f"- {point}")
    lines.extend(["", "## 主要構造", "", top_level_summary(analysis) or "主要構造の抽出は空でした。"])
    if analysis.top_level_steps:
        lines.extend(["", "## ファイルを上から読んだときの定義順", ""])
        for item in analysis.top_level_steps[:30]:
            lines.append(f"- L{item.lineno}: {item.summary}")
    if analysis.imports:
        lines.extend(["", "## import 群", ""])
        for item in analysis.imports:
            prefix = f"`import {', '.join(item.names)}`" if item.kind == "import" else f"`from {item.source} import {', '.join(item.names)}`"
            lines.append(f"- L{item.lineno}: {prefix}")
            lines.append(f"  - {import_evidence_text(analysis, item, ROOT / spec.path, module_title_map)}")
    concept_keys = concept_keys_for_analysis(analysis)
    if concept_keys:
        lines.extend(
            [
                "",
                "## このファイルを読む前に必要な基礎知識",
                "",
                "次の章は、構文やROS用語を既知と仮定しないための説明である。",
                "",
            ]
        )
        for key in concept_keys:
            lines.extend(markdown_chapter(CONCEPTS_BY_KEY[key], level=3))
    if spec.path == "mpc_solarcar/mpc_node.py":
        lines.extend(
            [
                "",
                "## `mpc_node.py`専用の統合解説",
                "",
                "この章は、起動機構とMPC内部計算を一つの時間軸で接続する。",
                "",
            ]
        )
        for chapter in MPC_NODE_DEEP_DIVE:
            lines.extend(markdown_chapter(chapter, level=3))
    if analysis.block_details:
        lines.extend(["", "## 関数・クラスを上から順に解説", ""])
        lines.extend(markdown_block_details(analysis))
    if analysis.parameters:
        lines.extend(["", "## パラメータ", ""])
        for item in analysis.parameters[:40]:
            default = f" (default: `{item.detail}`)" if item.detail else ""
            lines.append(f"- L{item.lineno}: `{item.value}`{default}")
    if analysis.publishers or analysis.subscriptions:
        lines.extend(["", "## ROS topic I/O", ""])
        for item in analysis.publishers[:40]:
            lines.append(f"- Publisher L{item.lineno}: `{item.value}`")
        for item in analysis.subscriptions[:40]:
            detail = f" -> `{item.detail}`" if item.detail else ""
            lines.append(f"- Subscription L{item.lineno}: `{item.value}`{detail}")
    if analysis.cli_args:
        lines.extend(["", "## CLI 引数", ""])
        for item in analysis.cli_args[:60]:
            lines.append(f"- L{item.lineno}: `{item.value}`")
    if analysis.launch_nodes:
        lines.extend(["", "## launch から起動するノード", ""])
        for item in analysis.launch_nodes[:40]:
            lines.append(f"- L{item.lineno}: `{item.value}` ({item.detail})")
    if analysis.shell_actions or analysis.external_commands:
        lines.extend(["", "## shell 分岐と外部コマンド", ""])
        for item in analysis.shell_actions[:40]:
            lines.append(f"- Action L{item.lineno}: `{item.value}`")
        for item in analysis.external_commands[:40]:
            lines.append(f"- Command L{item.lineno}: `{item.value}`")
    lines.extend(["", "## 処理の流れ", ""])
    for idx, step in enumerate(build_generic_flow(analysis), start=1):
        lines.append(f"{idx}. {step}")
    return "\n".join(lines).rstrip() + "\n"


def latex_table_rows(items: list[tuple[str, str]]) -> str:
    rows = []
    for key, value in items:
        rows.append(rf"{tex_escape(key)} & {value} \\")
    return "\n".join(rows)


def render_tex(analysis: ProgramAnalysis, module_title_map: dict[str, str]) -> str:
    spec = analysis.spec
    source_hash = file_sha256(ROOT / spec.path)
    excerpt, language = important_excerpt(analysis)
    import_rows = []
    current_path = ROOT / spec.path
    for item in analysis.imports:
        label = (
            tex_path(f"import {', '.join(item.names)}")
            if item.kind == "import"
            else tex_path(f"from {item.source} import {', '.join(item.names)}")
        )
        desc = tex_escape(import_evidence_text(analysis, item, current_path, module_title_map))
        import_rows.append(rf"{item.lineno} & {label} & {desc} \\")
    params_rows = []
    for item in analysis.parameters[:50]:
        detail = tex_escape(item.detail) if item.detail else ""
        params_rows.append(rf"{item.lineno} & {tex_path(item.value)} & {detail} \\")
    topic_rows = []
    for item in analysis.publishers[:50]:
        topic_rows.append(rf"{item.lineno} & publisher & {tex_path(item.value)} & {tex_escape(item.detail)} \\")
    for item in analysis.subscriptions[:50]:
        topic_rows.append(rf"{item.lineno} & subscription & {tex_path(item.value)} & {tex_escape(item.detail)} \\")
    launch_rows = []
    for item in analysis.launch_nodes[:50]:
        launch_rows.append(rf"{item.lineno} & {tex_path(item.value)} & {tex_escape(item.detail)} \\")
    cli_rows = []
    for item in analysis.cli_args[:80]:
        cli_rows.append(rf"{item.lineno} & {tex_path(item.value)} \\")
    shell_rows = []
    for item in analysis.shell_actions[:60]:
        shell_rows.append(rf"{item.lineno} & action & {tex_path(item.value)} \\")
    for item in analysis.external_commands[:60]:
        shell_rows.append(rf"{item.lineno} & command & {tex_path(item.value)} \\")
    structure_rows = []
    for item in analysis.classes[:30]:
        structure_rows.append(rf"{item.lineno} & class & {tex_path(item.name)} & {tex_escape(item.detail)} \\")
    for item in analysis.functions[:60]:
        structure_rows.append(rf"{item.lineno} & function & {tex_path(item.name)} & {tex_escape(item.detail)} \\")
    top_summary = top_level_summary(analysis) or "このファイルでは主要構造抽出結果が少ない。"
    flow_items = "\n".join(rf"\item {tex_escape(step)}" for step in build_generic_flow(analysis))
    key_items = "\n".join(rf"\item {tex_escape(point)}" for point in spec.key_points) or r"\item 特記事項なし。"
    called_from_items = "\n".join(rf"\item {tex_ref(item)}" for item in spec.called_from) or r"\item 特記事項なし。"
    next_read_items = "\n".join(rf"\item {tex_ref(item)}" for item in spec.next_read) or r"\item 特記事項なし。"
    local_dep_items = "\n".join(rf"\item {tex_path(item)}" for item in analysis.local_dependencies) or r"\item 同一リポジトリ内の明示 import は少ない。"
    docstring_text = tex_escape(analysis.docstring.strip()) if analysis.docstring.strip() else "モジュール docstring は明示されていない。"
    code_block = latex_code_block(excerpt, language)
    top_level_rows = []
    for item in analysis.top_level_steps[:40]:
        top_level_rows.append(rf"{item.lineno} & {tex_escape(item.summary)} \\")
    import_table = ""
    if import_rows:
        import_table = textwrap.dedent(
            rf"""
            \subsection*{{import 群の詳細}}
            \begin{{longtable}}{{p{{0.07\linewidth}} p{{0.33\linewidth}} p{{0.50\linewidth}}}}
            \toprule
            行 & import 文 & このファイルで読む理由 \\
            \midrule
            {chr(10).join(import_rows)}
            \bottomrule
            \end{{longtable}}
            """
        ).strip()
    params_table = ""
    if params_rows:
        params_table = textwrap.dedent(
            rf"""
            \subsection*{{設定値と入力パラメータ}}
            \begin{{longtable}}{{p{{0.07\linewidth}} p{{0.35\linewidth}} p{{0.45\linewidth}}}}
            \toprule
            行 & 名前 & 既定値・補足 \\
            \midrule
            {chr(10).join(params_rows)}
            \bottomrule
            \end{{longtable}}
            """
        ).strip()
    topic_table = ""
    if topic_rows:
        topic_table = textwrap.dedent(
            rf"""
            \subsection*{{ROS topic I/O}}
            \begin{{longtable}}{{p{{0.07\linewidth}} p{{0.18\linewidth}} p{{0.34\linewidth}} p{{0.28\linewidth}}}}
            \toprule
            行 & 種別 & topic & callback / 補足 \\
            \midrule
            {chr(10).join(topic_rows)}
            \bottomrule
            \end{{longtable}}
            """
        ).strip()
    structure_table = ""
    if structure_rows:
        structure_table = textwrap.dedent(
            rf"""
            \subsection*{{主要クラス・関数}}
            \begin{{longtable}}{{p{{0.07\linewidth}} p{{0.16\linewidth}} p{{0.25\linewidth}} p{{0.40\linewidth}}}}
            \toprule
            行 & 種別 & 名前 & 補足 \\
            \midrule
            {chr(10).join(structure_rows)}
            \bottomrule
            \end{{longtable}}
            """
        ).strip()
    top_level_table = ""
    if top_level_rows:
        top_level_table = textwrap.dedent(
            rf"""
            \subsection*{{ファイルを上から読んだときの定義順}}
            \begin{{longtable}}{{p{{0.07\linewidth}} p{{0.84\linewidth}}}}
            \toprule
            行 & 内容 \\
            \midrule
            {chr(10).join(top_level_rows)}
            \bottomrule
            \end{{longtable}}
            """
        ).strip()
    launch_table = ""
    if launch_rows:
        launch_table = textwrap.dedent(
            rf"""
            \subsection*{{launch から起動するノード}}
            \begin{{longtable}}{{p{{0.07\linewidth}} p{{0.30\linewidth}} p{{0.50\linewidth}}}}
            \toprule
            行 & executable & package / name \\
            \midrule
            {chr(10).join(launch_rows)}
            \bottomrule
            \end{{longtable}}
            """
        ).strip()
    cli_table = ""
    if cli_rows:
        cli_table = textwrap.dedent(
            rf"""
            \subsection*{{CLI 引数}}
            \begin{{longtable}}{{p{{0.07\linewidth}} p{{0.78\linewidth}}}}
            \toprule
            行 & 引数 \\
            \midrule
            {chr(10).join(cli_rows)}
            \bottomrule
            \end{{longtable}}
            """
        ).strip()
    shell_table = ""
    if shell_rows:
        shell_table = textwrap.dedent(
            rf"""
            \subsection*{{shell 分岐と外部コマンド}}
            \begin{{longtable}}{{p{{0.07\linewidth}} p{{0.18\linewidth}} p{{0.67\linewidth}}}}
            \toprule
            行 & 種別 & 内容 \\
            \midrule
            {chr(10).join(shell_rows)}
            \bottomrule
            \end{{longtable}}
            """
        ).strip()
    block_details_section = tex_block_details(analysis) if analysis.block_details else ""
    concept_keys = concept_keys_for_analysis(analysis)
    concept_section = "\n\n".join(
        tex_chapter(CONCEPTS_BY_KEY[key], "subsection*") for key in concept_keys
    )
    deep_dive_section = ""
    if spec.path == "mpc_solarcar/mpc_node.py":
        deep_dive_section = "\n\n".join(
            tex_chapter(chapter, "subsection*") for chapter in MPC_NODE_DEEP_DIVE
        )
    deep_dive_document_section = ""
    if deep_dive_section:
        deep_dive_document_section = (
            "\\section*{mpc\\_node.py専用の統合解説}\n"
            "起動機構とMPC内部計算を一つの時間軸で接続する。\n\n"
            + deep_dive_section
        )
    document = textwrap.dedent(
        rf"""
        \documentclass[a4paper,11pt]{{article}}
        \usepackage[top=15mm,bottom=18mm,left=16mm,right=16mm]{{geometry}}
        \usepackage{{fontspec}}
        \usepackage{{xeCJK}}
        \setmainfont{{Times New Roman}}
        \setCJKmainfont{{Yu Gothic}}
        \setmonofont{{Consolas}}
        \setCJKmonofont{{Yu Gothic}}
        \usepackage{{booktabs}}
        \usepackage{{longtable}}
        \usepackage{{tabularx}}
        \usepackage{{array}}
        \usepackage{{enumitem}}
        \usepackage{{hyperref}}
        \usepackage{{listings}}
        \usepackage{{xcolor}}
        \usepackage{{amsmath}}
        \usepackage{{amssymb}}
        \hypersetup{{
          colorlinks=true,
          linkcolor=blue,
          urlcolor=blue,
          pdftitle={{{tex_escape(spec.title)}}},
          pdfauthor={{Codex}}
        }}
        \lstset{{
          basicstyle=\ttfamily\small,
          breaklines=true,
          columns=fullflexible,
          keepspaces=true,
          frame=single,
          framerule=0.2pt,
          rulecolor=\color{{black}},
          showstringspaces=false
        }}
        \setlength{{\parskip}}{{0.42em}}
        \setlength{{\parindent}}{{1em}}
        \setlength{{\emergencystretch}}{{3em}}
        \renewcommand{{\arraystretch}}{{1.15}}
        \title{{{spec.order:02d}. {tex_escape(spec.title)}}}
        \author{{solar\_ws0129-main}}
        \date{{{GENERATION_DATE}}}
        \begin{{document}}
        \maketitle
        \tableofcontents
        \clearpage

        \section*{{対象}}
        \begin{{tabularx}}{{\linewidth}}{{>{{\raggedright\arraybackslash}}p{{0.18\linewidth}} X}}
        \toprule
        項目 & 内容 \\
        \midrule
        ファイル & {tex_path(spec.path)} \\
        ソースSHA-256 & {tex_path(source_hash)} \\
        種別 & {tex_escape(summarize_kind(spec))} \\
        区分 & {tex_escape(spec.category)} \\
        役割 & {tex_escape(spec.purpose)} \\
        起動文脈 & {tex_escape(spec.startup_context)} \\
        \bottomrule
        \end{{tabularx}}

        \section*{{このファイルを読む理由}}
        {tex_escape(spec.purpose)}

        \begin{{itemize}}[leftmargin=1.6em]
        {key_items}
        \end{{itemize}}

        \section*{{呼び出し関係}}
        \subsection*{{どこから呼ばれるか}}
        \begin{{itemize}}[leftmargin=1.6em]
        {called_from_items}
        \end{{itemize}}

        \subsection*{{次に読むと理解が進むファイル}}
        \begin{{itemize}}[leftmargin=1.6em]
        {next_read_items}
        \end{{itemize}}

        \subsection*{{同一リポジトリ内の主要依存}}
        \begin{{itemize}}[leftmargin=1.6em]
        {local_dep_items}
        \end{{itemize}}

        \section*{{ソース冒頭の把握}}
        モジュール docstring または先頭意図の要約:

        {docstring_text}

        \subsection*{{代表コード断片}}
        {code_block}

        \section*{{主要構造の読み取り}}
        {tex_escape(top_summary)}

        {structure_table}

        {top_level_table}

        {import_table}

        \section*{{このファイルを読む前に必要な基礎知識}}
        次の章は、構文やROS用語を既知と仮定しないための説明である。

        {concept_section if concept_section else tex_escape('このファイル固有の追加基礎章は少ない。')}

        {deep_dive_document_section}

        \section*{{関数・クラスを上から順に解説}}
        {block_details_section if block_details_section else tex_escape('このファイルでは独立した関数・クラス定義が少ない。')}

        {params_table}

        {topic_table}

        {launch_table}

        {cli_table}

        {shell_table}

        \section*{{処理の流れ}}
        \begin{{enumerate}}[leftmargin=1.7em]
        {flow_items}
        \end{{enumerate}}

        \section*{{このファイルの位置づけ}}
        この資料群では、{tex_path(spec.path)} を
        \textbf{{{tex_escape(spec.category)}}}の中核として扱う。
        したがって、ここで扱う処理は単独で完結せず、
        前段の profile / launch / telemetry と後段の planner / logger / report へ繋がる。

        \end{{document}}
        """
    ).strip() + "\n"
    return finalize_tex_document(document)


def index_tex(specs: list[ProgramSpec], generated: list[dict[str, Any]]) -> str:
    rows = [
        rf"00 & 基礎知識総論 & Python / OS / ROS 2 / MPC / 数値最適化 & {tex_path(FOUNDATION_PDF.name)} \\"
    ]
    for spec, item in zip(specs, generated):
        rows.append(
            rf"{spec.order:02d} & {tex_escape(spec.title)} & {tex_path(spec.path)} & {tex_path(Path(item['pdf']).name)} \\"
        )
    return textwrap.dedent(
        rf"""
        \documentclass[a4paper,11pt]{{article}}
        \usepackage[top=16mm,bottom=20mm,left=16mm,right=16mm]{{geometry}}
        \usepackage{{fontspec}}
        \usepackage{{xeCJK}}
        \setmainfont{{Times New Roman}}
        \setCJKmainfont{{Yu Gothic}}
        \setmonofont{{Consolas}}
        \setCJKmonofont{{Yu Gothic}}
        \usepackage{{booktabs}}
        \usepackage{{longtable}}
        \usepackage{{tabularx}}
        \usepackage{{array}}
        \usepackage{{enumitem}}
        \usepackage{{hyperref}}
        \hypersetup{{
          colorlinks=true,
          linkcolor=blue,
          urlcolor=blue,
          pdftitle={{Program reference index}},
          pdfauthor={{Codex}}
        }}
        \setlength{{\parskip}}{{0.42em}}
        \setlength{{\parindent}}{{1em}}
        \setlength{{\emergencystretch}}{{3em}}
        \renewcommand{{\arraystretch}}{{1.15}}
        \title{{ソーラーカーパッケージ主要プログラム\\個別解説PDF一覧}}
        \author{{solar\_ws0129-main}}
        \date{{{GENERATION_DATE}}}
        \begin{{document}}
        \maketitle

        \section*{{対象と方針}}
        本資料群は、以前列挙した主要プログラムを対象に、
        \begin{{itemize}}[leftmargin=1.6em]
          \item プログラム、プロセス、メモリ、関数、クラス、self、decoratorなどの前提
          \item ファイルの役割
          \item どこから呼ばれ、何へ繋がるか
          \item import 群の意味
          \item クラス内メソッドと関数内関数を含む全定義
          \item 引数、戻り値、self属性の読み書き、分岐、ループ、例外、副作用
          \item ROS I/O、CLI引数、実行の流れ、診断方法
          \item MPC、CEM、warm start、車両・電池モデルの数式と実装対応
        \end{{itemize}}
        を日本語で個別PDF化したものである。ソースから確定する事実と一般仕様を分け、
        各冊に生成対象ソースのSHA-256を記録する。

        \section*{{生成物一覧}}
        \begin{{longtable}}{{p{{0.06\linewidth}} p{{0.26\linewidth}} p{{0.38\linewidth}} p{{0.22\linewidth}}}}
        \toprule
        No. & タイトル & ソース & PDF ファイル \\
        \midrule
        {chr(10).join(rows)}
        \bottomrule
        \end{{longtable}}

        \section*{{推奨読書順}}
        \begin{{enumerate}}[leftmargin=1.8em]
          \item 00 基礎知識総論
          \item 入口: SolarSim.ps1, solar\_control.sh
          \item launch: live\_wifi, live, sim, measure, live\_launch
          \item config: solar\_profile, path\_utils
          \item 数理コア: solar\_sim, mpc\_node, model, upper\_*
          \item runtime node: telemetry, weather, bridge, logger, dashboard
          \item offline pipeline: forecast, identification, learn, GPU search, validation
        \end{{enumerate}}

        \end{{document}}
        """
    ).strip() + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def compile_tex(tex_path_file: Path, pdf_path: Path) -> None:
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    build_dir = BUILD_DIR / tex_path_file.stem
    build_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-output-directory={build_dir}",
        str(tex_path_file),
    ]
    compile_log = build_dir / "xelatex.log"
    passes = []
    for pass_number in (1, 2):
        result = subprocess.run(
            cmd,
            check=False,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        passes.append(
            f"===== xelatex pass {pass_number} =====\n"
            f"{result.stdout}\n{result.stderr}\n"
        )
        compile_log.write_text("\n".join(passes), encoding="utf-8", newline="\n")
        if result.returncode != 0:
            tail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-40:])
            raise RuntimeError(
                f"xelatex failed for {tex_path_file} on pass {pass_number}; "
                f"see {compile_log}\n{tail}"
            )
    built_pdf = build_dir / f"{tex_path_file.stem}.pdf"
    if not built_pdf.is_file():
        raise FileNotFoundError(f"xelatex did not produce {built_pdf}")
    shutil.copy2(built_pdf, pdf_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-pdf", action="store_true", help="Generate sources only.")
    parser.add_argument(
        "--pdf-slug-regex",
        default="",
        help="Compile only program PDF slugs matching this regular expression.",
    )
    args = parser.parse_args()
    pdf_slug_pattern = re.compile(args.pdf_slug_regex) if args.pdf_slug_regex else None

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    TEX_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    MARKDOWN_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    write_text(FOUNDATION_MARKDOWN, markdown_foundations())
    write_text(FOUNDATION_TEX, foundations_tex())
    if not args.skip_pdf and pdf_slug_pattern is None:
        compile_tex(FOUNDATION_TEX, FOUNDATION_PDF)

    analyses = [analyze_program(spec) for spec in PROGRAMS]
    module_title_map: dict[str, str] = {}
    for spec in PROGRAMS:
        module_name = module_name_for_path(ROOT / spec.path)
        if module_name:
            module_title_map[module_name] = spec.title

    generated: list[dict[str, Any]] = []
    for analysis in analyses:
        slug = f"{analysis.spec.order:02d}_{slugify(analysis.spec.path)}"
        tex_path_file = TEX_DIR / f"{slug}.tex"
        pdf_path_file = PDF_DIR / f"{slug}.pdf"
        md_path_file = MARKDOWN_DIR / f"{slug}.md"
        write_text(md_path_file, markdown_for_analysis(analysis, module_title_map))
        write_text(tex_path_file, render_tex(analysis, module_title_map))
        if (
            not args.skip_pdf
            and (pdf_slug_pattern is None or pdf_slug_pattern.search(slug))
        ):
            compile_tex(tex_path_file, pdf_path_file)
        generated.append(
            {
                "order": analysis.spec.order,
                "title": analysis.spec.title,
                "path": analysis.spec.path,
                "source_sha256": file_sha256(ROOT / analysis.spec.path),
                "source_line_count": len(analysis.text.splitlines()),
                "import_count": len(analysis.imports),
                "class_count": len(analysis.classes),
                "function_count": len(analysis.functions),
                "documented_definition_count": len(analysis.block_details),
                "shell_function_count": len(analysis.shell_functions),
                "ros_publisher_count": len(analysis.publishers),
                "ros_subscription_count": len(analysis.subscriptions),
                "ros_timer_count": len(analysis.timers),
                "tex": rel_path(tex_path_file),
                "markdown": rel_path(md_path_file),
                "pdf": rel_path(pdf_path_file),
            }
        )

    write_text(INDEX_TEX, index_tex(PROGRAMS, generated))
    if not args.skip_pdf and pdf_slug_pattern is None:
        compile_tex(INDEX_TEX, INDEX_PDF)

    manifest = {
        "generated_at_date": GENERATION_DATE,
        "output_root": rel_path(OUT_ROOT),
        "document_count": len(generated) + 1,
        "program_document_count": len(generated),
        "foundation_markdown": rel_path(FOUNDATION_MARKDOWN),
        "foundation_tex": rel_path(FOUNDATION_TEX),
        "foundation_pdf": rel_path(FOUNDATION_PDF),
        "documents": generated,
        "index_pdf": rel_path(INDEX_PDF),
    }
    write_text(MANIFEST_PATH, json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
