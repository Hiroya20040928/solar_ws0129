#!/usr/bin/env python3
import argparse
import json
import socket
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='192.168.50.10')
    ap.add_argument('--port', type=int, default=52001)
    ap.add_argument('--period_sec', type=float, default=1.0)
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    speed = 72.0
    dist = 412.0
    while True:
        payload = {
            'type': 'vehicle_state',
            'ts_unix': time.time(),
            'speed_kmh': speed,
            'soc': 0.83,
            'batt_temp_c': 34.2,
            'batt_current_a': 8.5,
            'batt_voltage_v': 97.6,
            's_km': dist,
            'lat': -19.13542,
            'lon': 146.81235,
            'alt_m': 18.4,
            'wind_speed_ms': 6.8,
            'wind_dir_deg': 118.0,
            'course_deg': 176.5,
        }
        sock.sendto(json.dumps(payload, ensure_ascii=False).encode('utf-8'), (args.host, args.port))
        speed += 0.05
        dist += speed * (args.period_sec / 3600.0)
        time.sleep(args.period_sec)


if __name__ == '__main__':
    main()
