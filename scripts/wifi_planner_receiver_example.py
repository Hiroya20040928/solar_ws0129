#!/usr/bin/env python3
import argparse
import json
import socket


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bind_host', default='0.0.0.0')
    ap.add_argument('--bind_port', type=int, default=52002)
    args = ap.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind_host, args.bind_port))
    print(f'listening on udp://{args.bind_host}:{args.bind_port}')

    while True:
        payload, addr = sock.recvfrom(65535)
        try:
            obj = json.loads(payload.decode('utf-8'))
        except Exception as exc:
            print(f'{addr[0]}:{addr[1]} bad json: {exc}')
            continue
        print(f'{addr[0]}:{addr[1]}')
        print(json.dumps(obj, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
