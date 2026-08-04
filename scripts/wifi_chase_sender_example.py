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
    speed = 74.0
    lat = -19.13580
    lon = 146.81210
    while True:
        payload = {
            'type': 'chase_state',
            'ts_unix': time.time(),
            'speed_kmh': speed,
            'lat': lat,
            'lon': lon,
            'alt_m': 18.1,
            'wind_speed_ms': 6.5,
            'wind_dir_deg': 121.0,
            'course_deg': 176.0,
        }
        sock.sendto(json.dumps(payload, ensure_ascii=False).encode('utf-8'), (args.host, args.port))
        speed += 0.03
        lat += 0.00001
        lon += 0.00001
        time.sleep(args.period_sec)


if __name__ == '__main__':
    main()
