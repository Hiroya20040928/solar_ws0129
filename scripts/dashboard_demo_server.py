#!/usr/bin/env python3
"""Serve the real dashboard with deterministic training telemetry."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DEMO_STATE = {
    "speed_cmd_kmh": 71.2,
    "upper_speed_cmd_kmh": 72.0,
    "speed_meas_kmh": 70.8,
    "throttle_cmd_pct": 34.0,
    "drive_mode": "ECO",
    "soc": 0.742,
    "Tb_C": 31.4,
    "batt_current_a": 18.6,
    "batt_voltage_v": 92.8,
    "pack_w": 1726.0,
    "motor_w": 1580.0,
    "motor_a": 17.0,
    "solar_w": 846.0,
    "wheel_w": 1460.0,
    "s_km": 1248.6,
    "G_poa": 782.0,
    "Tcell_C": 46.8,
    "Tamb_C": 33.1,
    "headwind_ms": 3.7,
    "slope_pct": 0.42,
    "plan_dt": 600.0,
    "lower_dt": 1.0,
    "forecast_k": 18.0,
    "sec_to_next": 2870.0,
    "system_state": "READY",
    "system_diag": "telemetry fresh / limits OK",
    "mpc_state": "OPTIMAL",
    "system_health": 0.98,
    "plan_upper": [70, 72, 71, 69, 73, 72, 70],
    "plan_lower": [70.8, 71.0, 71.2, 71.3, 71.4, 71.5, 71.5, 71.6],
}


class DemoHandler(SimpleHTTPRequestHandler):
    def do_GET(self) -> None:
        if urlparse(self.path).path == "/api/state":
            body = json.dumps(DEMO_STATE, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, _format: str, *_args) -> None:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()
    handler = partial(DemoHandler, directory=str(ROOT / "dashboard"))
    with ThreadingHTTPServer((args.host, args.port), handler) as server:
        print(f"dashboard demo: http://{args.host}:{args.port}", flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
