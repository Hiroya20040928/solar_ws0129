# 02. WSL側 実行ルータ

- ファイル: `scripts/solar_control.sh`
- 種別: `Bash`
- 区分: `入口`

## 役割

ROS 2 build、launch、offline simulation、forecast、identification、learn を mode 別に振り分ける。

## 起動文脈

- 起動文脈: SolarSim.ps1 から WSL 内で呼ばれる実行ルータ。
- 呼び出し元: `SolarSim.ps1`
- 次に読むべきファイル: `launch/solarcar_sim.launch.py`, `launch/solar_race_live.launch.py`, `scripts/solar_sim.py`

## 主要ポイント

- mode から launch file を決める。
- ROS 環境を source する。
- 起動 PID 管理と stop/status/graph を一括で持つ。

## 主要構造

action 分岐は 20 件。

## ファイルを上から読んだときの定義順

- L2: set -euo pipefail
- L4: ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
- L5: RUN_DIR="${ROOT_DIR}/.run"
- L6: DISTRO_NAME="${ROS_DISTRO:-humble}"
- L8: mkdir -p "${RUN_DIR}"
- L9: export AMENT_TRACE_SETUP_FILES="${AMENT_TRACE_SETUP_FILES-}"
- L11: action="${1:-up}"
- L12: mode="${2:-sim}"
- L13: profile="${3:-config/solar/bwsc_2027_demo.yaml}"
- L15: case "${mode}" in
- L16: sim)
- L17: launch_file="solarcar_sim.launch.py"
- L18: ;;
- L19: measure)
- L20: launch_file="solar_measurement.launch.py"
- L21: ;;
- L22: live)
- L23: launch_file="solar_race_live.launch.py"
- L24: ;;
- L25: live_wifi)
- L26: launch_file="solar_race_live_wifi.launch.py"
- L27: ;;
- L28: *)
- L29: echo "unknown mode: ${mode}" >&2
- L30: exit 2
- L31: ;;
- L32: esac
- L34: PID_FILE="${RUN_DIR}/solar_${mode}.pid"
- L35: LOG_FILE="${RUN_DIR}/solar_${mode}.log"
- L36: GRAPH_BASE="${ROOT_DIR}/rqt_graph_solar_${mode}"

## shell 分岐と外部コマンド

- Action L16: `sim`
- Action L19: `measure`
- Action L22: `live`
- Action L25: `live_wifi`
- Action L222: `build`
- Action L225: `start`
- Action L228: `stop`
- Action L231: `restart`
- Action L235: `status`
- Action L238: `graph`
- Action L241: `up`
- Action L246: `simulate`
- Action L250: `historical-weather`
- Action L254: `historical-simulate`
- Action L258: `forecast`
- Action L262: `identify`
- Action L266: `fit`
- Action L270: `learn`
- Action L274: `audit`
- Action L277: `log`
- Command L59: `$0 ~ /\/opt\/ros\/humble\/bin\/ros2 launch mpc_solarcar solar(car_sim|_measurement|_race_live|_race_live_wifi)\.launch\.py/ || $0 ~ /install\/mpc_solarcar\/lib\/mpc_solarcar\/(gps_sim_node|mpc_node|solar_state_node|dashboard_node|solar_logger_node|distance_node|grade_node|weather_fetch_node|solar_autocal_node|speed_command_bridge_node|telemetry_text_bridge_node|wind_correction_node)/ {`
- Command L108: `colcon build --packages-select mpc_solarcar`
- Command L122: `launch_cmd="export AMENT_TRACE_SETUP_FILES=\${AMENT_TRACE_SETUP_FILES-}; cd ${root_q} && set +u && source /opt/ros/${DISTRO_NAME}/setup.bash && source ${root_q}/install/setup.bash && set -u && exec ros2 launch mpc_solarcar ${launch_file} profile_yaml:=${profile_q}"`
- Command L123: `nohup setsid bash -lc "${launch_cmd}" >> "${LOG_FILE}" 2>&1 < /dev/null &`
- Command L128: `echo "launch failed: ros2 launch exited immediately" >&2`
- Command L152: `python3 "${ROOT_DIR}/scripts/export_rqt_graph.py" --output-base "${GRAPH_BASE}" --wait-sec 20 --mode "${mode}"`
- Command L158: `python3 "${ROOT_DIR}/scripts/solar_sim.py" --profile_yaml "${profile}"`
- Command L164: `python3 "${ROOT_DIR}/scripts/build_historical_weather_counterfactual_grid.py" \`
- Command L173: `python3 "${ROOT_DIR}/scripts/solar_sim.py" --profile_yaml "${historical_profile}"`
- Command L179: `python3 "${ROOT_DIR}/scripts/fetch_weather_forecast.py" --profile_yaml "${profile}"`
- Command L185: `python3 "${ROOT_DIR}/scripts/run_identification_pipeline.py" --profile_yaml "${profile}"`
- Command L196: `python3 "${ROOT_DIR}/scripts/run_vehicle_identification.py" \`
- Command L204: `python3 "${ROOT_DIR}/scripts/tune_upper_planner_weights.py" \`
- Command L210: `python3 "${ROOT_DIR}/scripts/generate_package_inventory.py"`
- Command L211: `python3 "${ROOT_DIR}/scripts/audit_solar_package.py"`
- Command L212: `python3 -m pytest -q`

## 処理の流れ

1. action と mode を受け取る。
2. ROS 環境と install/setup.bash を読む。
3. launch 実行か offline script 実行かを分岐する。
4. 必要に応じて PID 管理、graph 出力、log tail を行う。
