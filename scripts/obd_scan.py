#!/usr/bin/env python3
import argparse
import time

import can

PID_BASES = [0x00, 0x20, 0x40, 0x60, 0x80]


def request_pid(bus, pid, timeout=0.8):
    msg = can.Message(
        arbitration_id=0x7DF,
        data=[0x02, 0x01, pid, 0, 0, 0, 0, 0],
        is_extended_id=False,
    )
    bus.send(msg)
    t_end = time.time() + timeout
    while time.time() < t_end:
        resp = bus.recv(timeout=0.1)
        if resp is None:
            continue
        if resp.is_extended_id:
            continue
        if not (0x7E8 <= resp.arbitration_id <= 0x7EF):
            continue
        data = list(resp.data)
        if len(data) < 7:
            continue
        if data[1] != 0x41:
            continue
        if data[2] != pid:
            continue
        return data[3:7]
    return None


def parse_support_mask(base_pid, mask_bytes):
    mask = (mask_bytes[0] << 24) | (mask_bytes[1] << 16) | (mask_bytes[2] << 8) | mask_bytes[3]
    supported = []
    for i in range(32):
        if mask & (1 << (31 - i)):
            supported.append(base_pid + i + 1)
    return supported


def main():
    parser = argparse.ArgumentParser(description='Scan supported OBD-II Mode 01 PIDs')
    parser.add_argument('--iface', default='can0', help='SocketCAN interface (default: can0)')
    args = parser.parse_args()

    bus = can.interface.Bus(channel=args.iface, bustype='socketcan')

    supported = []
    for base in PID_BASES:
        mask = request_pid(bus, base)
        if mask is None:
            print(f'PID 0x{base:02X}: no response')
            continue
        pids = parse_support_mask(base, mask)
        supported.extend(pids)
        print(f'PID 0x{base:02X}: {len(pids)} supported')

    supported = sorted(set(supported))
    print('\nSupported PIDs (Mode 01):')
    print(' '.join([f'0x{pid:02X}' for pid in supported]))

    print('\nKey checks:')
    print(f'- MAF (0x10): {"YES" if 0x10 in supported else "NO"}')
    print(f'- Fuel Rate (0x5E): {"YES" if 0x5E in supported else "NO"}')


if __name__ == '__main__':
    main()
