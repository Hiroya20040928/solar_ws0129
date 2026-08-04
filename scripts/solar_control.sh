#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT_DIR}/.run"
DISTRO_NAME="${ROS_DISTRO:-humble}"

mkdir -p "${RUN_DIR}"
export AMENT_TRACE_SETUP_FILES="${AMENT_TRACE_SETUP_FILES-}"

action="${1:-up}"
mode="${2:-sim}"
profile="${3:-config/solar/bwsc_2027_demo.yaml}"

case "${mode}" in
  sim)
    launch_file="solarcar_sim.launch.py"
    ;;
  measure)
    launch_file="solar_measurement.launch.py"
    ;;
  live)
    launch_file="solar_race_live.launch.py"
    ;;
  live_wifi)
    launch_file="solar_race_live_wifi.launch.py"
    ;;
  *)
    echo "unknown mode: ${mode}" >&2
    exit 2
    ;;
esac

PID_FILE="${RUN_DIR}/solar_${mode}.pid"
LOG_FILE="${RUN_DIR}/solar_${mode}.log"
GRAPH_BASE="${ROOT_DIR}/rqt_graph_solar_${mode}"

source_ros() {
  set +u
  # shellcheck disable=SC1091
  source "/opt/ros/${DISTRO_NAME}/setup.bash"
  if [[ -f "${ROOT_DIR}/install/setup.bash" ]]; then
    # shellcheck disable=SC1091
    source "${ROOT_DIR}/install/setup.bash"
  fi
  set -u
}

is_running() {
  [[ -f "${PID_FILE}" ]] || return 1                               # [戻り値] 計算結果・計算状態の呼び出し元への返却
  local pid
  pid="$(cat "${PID_FILE}")"
  [[ -n "${pid}" ]] || return 1                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
  ps -p "${pid}" -o pid= 2>/dev/null | grep -q .
}

find_matching_pids() {
  ps -eo pid=,args= | awk '
    $0 ~ /\/opt\/ros\/humble\/bin\/ros2 launch mpc_solarcar solar(car_sim|_measurement|_race_live|_race_live_wifi)\.launch\.py/ || $0 ~ /install\/mpc_solarcar\/lib\/mpc_solarcar\/(gps_sim_node|mpc_node|solar_state_node|dashboard_node|logger_node|distance_node|grade_node|weather_fetch_node|solar_autocal_node|speed_command_bridge_node|telemetry_text_bridge_node|wind_correction_node)/ {
      print $1
    }
  '
}

has_matching_processes() {
  [[ -n "$(find_matching_pids)" ]]
}

kill_matching_processes() {
  local pid
  while read -r pid; do
    [[ -n "${pid}" ]] || continue
    kill -TERM "${pid}" 2>/dev/null || true
  done < <(find_matching_pids)
}

stop_launch() {
  if is_running; then
    local pid
    pid="$(cat "${PID_FILE}")"
    kill -TERM "-${pid}" 2>/dev/null || true
  fi
  kill_matching_processes
  for _ in $(seq 1 20); do
    if ! has_matching_processes; then
      rm -f "${RUN_DIR}"/solar_*.pid
      echo "stopped"
      return 0                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
    fi
    sleep 0.5
  done
  if [[ -f "${PID_FILE}" ]]; then
    local pid
    pid="$(cat "${PID_FILE}")"
    kill -KILL "-${pid}" 2>/dev/null || true
  fi
  while read -r pid; do
    [[ -n "${pid}" ]] || continue
    kill -KILL "${pid}" 2>/dev/null || true
  done < <(find_matching_pids)
  rm -f "${RUN_DIR}"/solar_*.pid
  echo "stopped"
}

build_pkg() {
  source_ros
  cd "${ROOT_DIR}"
  colcon build --packages-select mpc_solarcar                      # [ビルドコマンド] ROS 2 パッケージのコンパイル実行
}

start_launch() {
  source_ros
  cd "${ROOT_DIR}"
  if is_running; then
    echo "already running"
    return 0                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
  fi
  : > "${LOG_FILE}"
  local root_q profile_q launch_cmd
  printf -v root_q "%q" "${ROOT_DIR}"
  printf -v profile_q "%q" "${profile}"
  launch_cmd="export AMENT_TRACE_SETUP_FILES=\${AMENT_TRACE_SETUP_FILES-}; cd ${root_q} && set +u && source /opt/ros/${DISTRO_NAME}/setup.bash && source ${root_q}/install/setup.bash && set -u && exec ros2 launch mpc_solarcar ${launch_file} profile_yaml:=${profile_q}"
  nohup setsid bash -lc "${launch_cmd}" >> "${LOG_FILE}" 2>&1 < /dev/null &
  local pid=$!
  echo "${pid}" > "${PID_FILE}"
  for _ in $(seq 1 20); do
    if ! ps -p "${pid}" -o pid= 2>/dev/null | grep -q .; then
      echo "launch failed: ros2 launch exited immediately" >&2
      [[ -f "${LOG_FILE}" ]] && tail -n 80 "${LOG_FILE}" >&2 || true
      rm -f "${PID_FILE}"
      return 1                                                     # [戻り値] 計算結果・計算状態の呼び出し元への返却
    fi
    sleep 0.5
  done
  echo "started pid=${pid} mode=${mode}"
}

status_launch() {
  if is_running || has_matching_processes; then
    local pid
    pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    echo "running pid=${pid} mode=${mode}"
    return 0                                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却
  fi
  echo "stopped"
  return 1                                                         # [戻り値] 計算結果・計算状態の呼び出し元への返却
}

graph_launch() {
  source_ros
  cd "${ROOT_DIR}"
  python3 "${ROOT_DIR}/scripts/export_rqt_graph.py" --output-base "${GRAPH_BASE}" --wait-sec 20 --mode "${mode}"  # [Python実行] Python スクリプトの起動
}

simulate_offline() {
  source_ros
  cd "${ROOT_DIR}"
  python3 "${ROOT_DIR}/scripts/solar_sim.py" --profile_yaml "${profile}"  # [Python実行] Python スクリプトの起動
}

fetch_weather() {
  source_ros
  cd "${ROOT_DIR}"
  python3 "${ROOT_DIR}/scripts/fetch_weather_forecast.py" --profile_yaml "${profile}"  # [Python実行] Python スクリプトの起動
}

identify_pipeline() {
  source_ros
  cd "${ROOT_DIR}"
  python3 "${ROOT_DIR}/scripts/run_identification_pipeline.py" --profile_yaml "${profile}"  # [Python実行] Python スクリプトの起動
}

tail_log() {
  if [[ -f "${LOG_FILE}" ]]; then
    tail -n 80 "${LOG_FILE}"
  fi
}

case "${action}" in
  build)
    build_pkg
    ;;
  start)
    start_launch
    ;;
  stop)
    stop_launch
    ;;
  restart)
    stop_launch
    start_launch
    ;;
  status)
    status_launch
    ;;
  graph)
    graph_launch
    ;;
  up)
    build_pkg
    stop_launch
    start_launch
    ;;
  simulate)
    build_pkg
    simulate_offline
    ;;
  forecast)
    build_pkg
    fetch_weather
    ;;
  identify)
    build_pkg
    identify_pipeline
    ;;
  log)
    tail_log
    ;;
  *)
    echo "usage: $0 [up|build|start|stop|restart|status|graph|simulate|forecast|identify|log] [sim|measure|live|live_wifi] [profile_yaml]" >&2
    exit 2
    ;;
esac
