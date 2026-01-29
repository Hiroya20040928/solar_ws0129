#!/usr/bin/env bash
set -euo pipefail

iface="${1:-can0}"
bitrate="${2:-500000}"
try_250k="${3:-}"

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
setup_script="${root_dir}/scripts/setup_can.sh"

do_test() {
  local iface="$1"
  local search_cmd="rg -q"
  if ! command -v rg >/dev/null 2>&1; then
    search_cmd="grep -q"
  fi
  local tmp
  tmp="$(mktemp)"
  echo "[can_smoke_test] Starting candump on ${iface}"
  candump -L "${iface}" > "${tmp}" 2>/dev/null &
  local dump_pid=$!
  sleep 0.5
  echo "[can_smoke_test] Sending OBD speed request (Mode 01 PID 0x0D)"
  cansend "${iface}" 7DF#02010D0000000000
  sleep 1.0
  kill "${dump_pid}" >/dev/null 2>&1 || true

  if ${search_cmd} "7E8#.*410D" "${tmp}"; then
    echo "[can_smoke_test] PASS: OBD response received."
    rm -f "${tmp}"
    return 0
  fi

  echo "[can_smoke_test] FAIL: no OBD response."
  echo "- Check wiring: Pin6=CANH, Pin14=CANL, Pin5 or Pin4=GND"
  echo "- Verify continuity with a tester (do not trust colors)"
  echo "- Ensure ignition ON (engine running is safer)"
  echo "- Check termination on USB-CAN (try OFF first)"
  echo "- Try another bitrate (500k <-> 250k)"
  rm -f "${tmp}"
  return 1
}

if ! command -v candump >/dev/null 2>&1; then
  echo "can-utils not found. Install with: sudo apt install can-utils" >&2
  exit 1
fi

"${setup_script}" "${iface}" "${bitrate}"
if do_test "${iface}"; then
  exit 0
fi

if [[ "${try_250k}" == "--try-250k" ]]; then
  echo "[can_smoke_test] Retrying with 250000 bps"
  "${setup_script}" "${iface}" 250000
  do_test "${iface}"
fi
