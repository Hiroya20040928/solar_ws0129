#!/usr/bin/env bash
set -euo pipefail

iface="${1:-can0}"
bitrate="${2:-500000}"

if ! command -v ip >/dev/null 2>&1; then
  echo "ip command not found. Install iproute2." >&2
  exit 1
fi

if ! command -v candump >/dev/null 2>&1; then
  echo "can-utils not found. Install with: sudo apt install can-utils" >&2
fi

echo "[setup_can] iface=${iface} bitrate=${bitrate}"

sudo ip link set "${iface}" down || true
sudo ip link set "${iface}" type can bitrate "${bitrate}" restart-ms 100
sudo ip link set "${iface}" up

ip -details link show "${iface}"
