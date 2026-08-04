# 02. WSL側 実行ルータ

- ファイル: `scripts/solar_control.sh`
- ソースSHA-256: `3a3beda8fd115e6a5f5ce0974d68273fb14f341f19bd1ad72a72fcad44d5ebca`
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

## このファイルを読む前に必要な基礎知識

次の章は、構文やROS用語を既知と仮定しないための説明である。

### プログラム、プロセス、メモリ、オブジェクトを区別する

ソースファイルはディスク上の文字列であり、それ自体は走っていない。Python実行可能プログラムがソースを読み、OSがその実行を一つのプロセスとして管理する。プロセスには仮想メモリ、開いているファイル、スレッド、終了コードなどが対応する。

```text
ソースファイル -> Pythonインタプリタが読み込む -> OS上のプロセス -> Pythonオブジェクトをメモリに生成 -> 関数やcallbackを実行
```

「メモリ上に生成する」とは、実行中プロセスが使う記憶領域に、その値の型、属性、参照関係を表す実体を用意することである。変数は実体そのものというより、そのオブジェクトを指す名前として理解するとPythonの代入が読みやすい。

```python
node = MPCNode()
alias = node
# nodeとaliasは同じオブジェクトを参照する。
```

一つのプロセスには複数スレッドを持たせられる。スレッドは同じプロセスのメモリを共有するため、受信callbackと最適化callbackが同じself.zを書き換える場合は実行順と排他を検討する必要がある。

根拠資料:

- [Python公式チュートリアル: Classes](https://docs.python.org/3/tutorial/classes.html)

### CLI、PowerShell、Bash、環境変数、終了コード

CLIは端末からプログラム名と引数を渡す操作界面である。`argparse`は文字列として届く引数を名前、型、既定値、必須性に従って解析する。

PowerShellとBashは別のshellであり、変数記法、改行継続、引用、パス表記が異なる。このプロジェクトではWindows側のSolarSim.ps1がWSL側のsolar_control.shへ処理を渡す。

環境変数は親プロセスから子プロセスへ受け渡される名前付き文字列である。ROS_DOMAIN_ID、RMW_IMPLEMENTATION、Pythonの数値スレッド数などはコード外から動作を変えるため、実行記録へ残す必要がある。

終了コード0は一般に成功、0以外は失敗を示す。shellルータは子プロセスの終了コードを握り潰さず上位へ返すことで、自動運用が失敗を検知できる。

根拠資料:

- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)

### 例外、try/finally、with、資源解放

例外は通常の戻り値とは別経路で異常を呼出元へ伝える。`try/except`は想定した異常を処理し、`finally`は成功・失敗にかかわらず後始末を行う。

`with open(...) as f:`はcontext managerを使い、ブロックを出るとファイルを閉じる。CSVやログの破損を避けるため、開いた資源の所有者と閉じる場所を明確にする。

`except Exception: pass`はノードを止めない利点がある一方、入力異常を隠して原因追跡を難しくする。安全に関係する値では、少なくとも頻度制限付き警告、異常カウンタ、fallback状態のpublishを検討する。

### 天候、route、補間、時刻、単位

予報は時刻だけの系列か、時刻とroute距離の2次元gridになり得る。現在時刻tと距離sがgrid点の間なら、周囲の値から補間して日射、温度、風を求める。

UTC、現地timezone、naive datetimeを混ぜると数時間のずれが発生する。入力でtimezoneを確定し、内部比較はUTC、表示は現地時刻という役割分担が安全である。

route距離のkm、速度のkm/hとm/s、時間の秒、energyのWhとJを跨ぐため、変換係数3.6、3600、1000の意味を各式で確認する。

### launch Action、Node Action、実行可能名、remapping

`launch_ros.actions.Node(...)`はrclpyのNode基底クラスではなく、指定したpackageのexecutableをプロセスとして起動するlaunch Actionである。

`DeclareLaunchArgument`はlaunch実行時に受け取る入力欄を宣言し、`LaunchConfiguration`はその値を後で解決するsubstitutionを表す。`perform(context)`は実行時contextから確定文字列を取り出す。

launchの`name`はNode名override、`parameters`は起動時parameter、`remappings`はNodeやtopicの既定名を別名へ対応付ける。launchはPythonファイルからmainという名前を推測せず、executableとしてインストールされたconsole scriptを起動する。

根拠資料:

- [ROS 2 Humble公式: Understanding nodes](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html)
- [setuptools公式: Entry Points / Console Scripts](https://setuptools.pypa.io/en/latest/userguide/entry_point.html)

### rqt_graph、ros2 CLI、rosbag2をいつ使うか

rqt_graphは接続関係を見る道具であり、数値の正しさや更新周期までは保証しない。起動直後、topic名変更後、publisherが複数存在する疑いがある時に使う。

```bash
ros2 node list
ros2 node info /mpc_node
ros2 topic list -t
ros2 topic info -v /planner/speed_cmd
ros2 topic hz /planner/speed_cmd
ros2 topic echo /planner/status
rqt_graph
```

rosbag2はtopicメッセージを時系列のまま記録・再生する。通信不具合、freshness、再計画trigger、実車とSILSの差を再現可能にするため、本番前試験では制御入力だけでなく原因となる全telemetry、status、parameter情報を記録する。

```bash
ros2 bag record -o outputs/bags/preflight \
  /vehicle/s_km /vehicle/speed_kmh /vehicle/batt_soc \
  /vehicle/batt_temp_c /vehicle/batt_current_a /vehicle/batt_voltage_v \
  /planner/upper_speed_cmd /planner/speed_cmd /planner/status

ros2 bag info outputs/bags/preflight
ros2 bag play outputs/bags/preflight --clock
```

bag再生時はQoS互換性、simulation time、外部publisherとの二重入力に注意する。実車Nodeを同時に動かす場合はnamespaceまたはremappingで入力源を明確に分離する。

根拠資料:

- [ROS 2 Humble公式: rqt_graph](https://docs.ros.org/en/ros2_packages/humble/api/rqt_graph/index.html)
- [ROS 2 Humble公式: Recording and playing back data](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Recording-And-Playing-Back-Data/Recording-And-Playing-Back-Data.html)
- [ROS 2 Humble公式: Understanding nodes](https://docs.ros.org/en/humble/Tutorials/Beginner-CLI-Tools/Understanding-ROS2-Nodes/Understanding-ROS2-Nodes.html)


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
