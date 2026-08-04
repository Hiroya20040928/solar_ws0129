from __future__ import annotations

"""
=============================================================================
 SolarCar MPC & Energy Management System - Main Entrypoint
 ソーラーカー最先端最適制御・エネルギーマネジメント・物理同定 システム統括エントリーポイント
=============================================================================
"""

import argparse
import sys
from pathlib import Path

from solar_mpc.live_race import SolarLiveRaceController
from solar_mpc.macro_planner import SolarMacroPlanner
from solar_mpc.vehicle_identification import VehicleIdentifier

def main():
    parser = argparse.ArgumentParser(
        description="SolarCar MPCEMS: ソーラーカー高精度物理同定・マクロCEM計画・10s CasADi MPC制御システム"
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["fit", "plan", "live"],
        default="live",
        help="実行モードを選択: fit (同定・適合), plan (3000kmマクロCEM計画), live (実車リアルタイムMPC制御)"
    )
    parser.add_argument(
        "--config", "-c",
        default="config/solar/bwsc_2027_demo.yaml",
        help="YAML 設定ファイルのパス"
    )
    
    args = parser.parse_args()
    
    print("=" * 75)
    print(f" ソーラーカー最適制御システム [SolarCar MPCEMS v2.0] - 実行モード: {args.mode.upper()}")
    print("=" * 75)
    
    if args.mode == "fit":
        print("[1/3 Pipeline: Fitting] 車両物理・電池等価回路同定 ＆ 3,000km Replay検証を実行します...")
        identifier = VehicleIdentifier()
        identifier.run_full_identification()
    elif args.mode == "plan":
        print("[2/3 Pipeline: CEM Macro Plan] 3,000 km 大域エネルギー・速度分布最適化を実行します...")
        planner = SolarMacroPlanner(config_path=args.config)
        planner.plan()
    elif args.mode == "live":
        print("[3/3 Pipeline: Live Real-Time Control] 10s周期 CasADi MPC ＆ WiFi UDP 通信制御を開始します...")
        controller = SolarLiveRaceController(config_path=args.config)
        controller.run()

if __name__ == "__main__":
    main()