#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WS_DIR="$(cd "${ROOT_DIR}/../.." && pwd)"
CONFIG_PATH="${HOME}/.config/mpc_solarcar/passo_config.yaml"
CLI_ONLY=0
FORCE_WIZARD=0

launch_args=("$@")
for arg in "$@"; do
  case "${arg}" in
    config_path:=*)
      CONFIG_PATH="${arg#config_path:=}"
      ;;
    cli_only:=true)
      CLI_ONLY=1
      ;;
    cli_only:=false)
      CLI_ONLY=0
      ;;
    force_wizard:=true)
      FORCE_WIZARD=1
      ;;
  esac
done
CONFIG_PATH="${CONFIG_PATH/#\~/$HOME}"
if [[ -z "${DISPLAY:-}" ]]; then
  CLI_ONLY=1
fi
if [[ "${CLI_ONLY}" == "1" ]]; then
  has_cli=0
  for arg in "${launch_args[@]}"; do
    if [[ "${arg}" == cli_only:=* ]]; then
      has_cli=1
      break
    fi
  done
  if [[ "${has_cli}" == "0" ]]; then
    launch_args+=("cli_only:=true")
  fi
fi

if ! command -v ros2 >/dev/null 2>&1; then
  echo "ros2 not found in PATH. Source your ROS2 environment first." >&2
fi

if [[ -n "${ROS_DISTRO:-}" && -f "/opt/ros/${ROS_DISTRO}/setup.bash" ]]; then
  source "/opt/ros/${ROS_DISTRO}/setup.bash"
else
  if [[ -d "/opt/ros" ]]; then
    ROS_SETUP="$(ls -1 /opt/ros/*/setup.bash 2>/dev/null | head -n 1)"
    if [[ -n "${ROS_SETUP}" ]]; then
      source "${ROS_SETUP}"
    fi
  fi
fi

if ! command -v candump >/dev/null 2>&1; then
  echo "can-utils not found. Install with: sudo apt install can-utils" >&2
fi

python3 - <<'PY'
try:
    import can  # noqa: F401
except Exception:
    print('python-can not found. Install with: sudo apt install python3-can')
PY

sudo -v

cd "${WS_DIR}"
if [[ ! -f "${WS_DIR}/install/setup.bash" ]]; then
  colcon build --packages-select mpc_solarcar
fi
source "${WS_DIR}/install/setup.bash"

NEED_WIZARD=0
if [[ "${FORCE_WIZARD}" == "1" ]] || [[ ! -f "${CONFIG_PATH}" ]]; then
  NEED_WIZARD=1
fi
if [[ "${CLI_ONLY}" == "1" && "${NEED_WIZARD}" == "1" ]]; then
  echo "[passo_run] CLI wizard expected; running launch in foreground."
  exec ros2 launch mpc_solarcar passo_autostart.launch.py "${launch_args[@]}"
fi

ros2 launch mpc_solarcar passo_autostart.launch.py "${launch_args[@]}" &
LAUNCH_PID=$!

trap 'echo; kill ${LAUNCH_PID} >/dev/null 2>&1 || true; exit 0' INT TERM

while kill -0 "${LAUNCH_PID}" >/dev/null 2>&1; do
  state=$(timeout 2 ros2 topic echo -n 1 /system/state 2>/dev/null | awk -F': ' '/data:/{print $2; exit}')
  if [[ -n "${state}" ]]; then
    printf "\r[STATE] %s" "${state}"
  else
    printf "\r[STATE] waiting"
  fi
  sleep 1
done
