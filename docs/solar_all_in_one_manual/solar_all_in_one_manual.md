# 改良版ソーラーカーパッケージ オールインワン解説

## 目的
- `SolarSim.ps1` から何が起動するか
- `sim / measure / live / live_wifi / forecast / identify` がどう繋がるか
- 実測ログからの MLE / replay fitting がどの値を更新し、`profile.yaml` と maps にどう反映されるか
- WiFi 文字列テレメトリをどう送受信するか
- 現在の maps / coefficients の所在

## 重要な source 入口
- `SolarSim.ps1`
- `scripts/solar_control.sh`
- `launch/solarcar_sim.launch.py`
- `launch/solar_measurement.launch.py`
- `launch/solar_race_live.launch.py`
- `launch/solar_race_live_wifi.launch.py`
- `scripts/solar_sim.py`
- `scripts/fetch_weather_forecast.py`
- `scripts/run_identification_pipeline.py`
- `scripts/run_vehicle_identification.py`
- `mpc_solarcar/mpc_node.py`
- `mpc_solarcar/upper_policy.py`
- `mpc_solarcar/solar_state_node.py`
- `mpc_solarcar/telemetry_text_bridge_node.py`
- `mpc_solarcar/wind_correction_node.py`
- `mpc_solarcar/speed_command_bridge_node.py`
- `mpc_solarcar/weather_fetch_node.py`
- `mpc_solarcar/solar_autocal_node.py`
- `mpc_solarcar/solar_profile.py`
- `mpc_solarcar/weather_utils.py`

## mode ごとの骨格
- `sim`: `gps_sim_node + solar_state_node + mpc_node + dashboard_node`
- `measure`: `distance_node + grade_node + solar_logger_node + dashboard_node`
- `live`: `weather_fetch_node + mpc_node + solar_autocal_node + speed_command_bridge_node + solar_logger_node + dashboard_node`
- `live_wifi`: `telemetry_text_bridge_node + wind_correction_node + live 構成一式`
- `forecast`: `scripts/fetch_weather_forecast.py`
- `identify`: `scripts/run_identification_pipeline.py` または `scripts/run_vehicle_identification.py`

offline detail CSVの`step_dt_sec`は下位指令周期で、通常1秒である。`outer_step_requested_dt_sec=600`に対して`outer_step_actual_dt_sec`が11.747秒などになるのは、停止・走行時間窓・天候格子・上位速度区間の境界で外側ステップを正確に分割したためである。境界直前の`step_dt_sec`だけは1秒未満になり得るが、指令欠落ではない。

## profile の役割
- `paths`: route / weather / maps / schedule
- `runtime`: dashboard / forecast 時刻解釈
- `simulation`: offline sim
- `measurement`: 実測収集
- `identification`: raw 入力と output
- `live`: weather / autocal / command bridge / WiFi / wind model
- `model`: 質量, CdA, Crr, battery, PV
- `mpc`: 上位 / 下位 planner の horizon と重み

## 天候データの品質区分
- liveのOpen-Meteo forecastは運用予報として使用する。
- Open-Meteo archiveはmodel/reanalysisであり、経路上の日射計による独立観測真値ではない。
- no-trouble方策探索は、地点・時刻ごとのarchive瞬時GHI/DNI/DHIを保持する `bwsc2025_nominal_fullcourse_weather_grid.csv` だけを使う。
- `bwsc2025_historical_pv_conditioned_weather_grid.csv` は実車PVから逆補正した循環的な診断専用品であり、方策の順位付け・受入・live入力には使わない。
- PV mapの受入にはBOM Himawari hourly exposureまたは同期した経路上POA・MPPT状態を使う。
- BOM NetCDF/CSVは `scripts/import_bom_satellite_solar.py` で経路・時刻へ対応付ける。
- 独立日射が不足する間は `high_precision_gate_pass=false` とし、楽観的なfull simをlive profileへ昇格しない。

## 物理モデル
- 車輪機械出力:
  - `P_mech = ((1/2) rho CdA (v+w)^2 + m g Crr cos(theta) + m g sin(theta)) v`
- PV:
  - `P_pv = eta_panel(G,Tc) eta_mppt(G,Tc) A_pv G`
  - 停車時の実測校正は `P_batt = P_aux - g_solar P_solar_raw + epsilon` を有界 Huber M 推定で解く
  - WiFi 送信側は未補正の `solar_power_w` を送り、受信側が `g_solar` を一度だけ適用する
- パック:
  - `P_pack = P_drive_dc - P_regen_dc + P_aux - P_pv`
  - 走行中・日中停車 `P_aux = P_aux_stopped = 21.021 W`、日射20 W/m2以下の夜間 `P_aux_night = 0 W`
- SoC 更新:
  - `z[k+1] = z[k] - eta_chg(I[k]) * I[k] * dt / (3600 Q_nom)`
  - `Vp[k+1] = exp(-dt/tau_p) Vp[k] + (1-exp(-dt/tau_p)) Rp I[k]`
  - `V[k] = OCV(z[k]) - I[k] R0[k] - Vp[k]`
  - 25直列・4.35 V/cellより `V_max = 108.75 V`。OCV map最大値はこれ以下、YATA profileの`V_max`は108.75 Vに一致させる
- 向かい風:
  - `w_head = u cos(phi - psi)`

## fitting の流れ
1. raw log を正規化し、距離アンカーと weather を対応づける
2. grounded base maps を作る
3. PV fit
4. battery fit
5. motion fit
6. DEM高度の平滑化窓・距離オフセットをDay1--Day5で選び、Day6で独立検証する
7. 採択した勾配観測に対してmotion fitを再実行する
8. joint replay refinement
9. battery 1-RC polarization fit
10. `profile.model.*`, `profile.paths.*`, map CSV へ書き戻す

勾配同定で保存する`adopted_route_profile.csv`の`slope_pct`は、DEM高度を平滑化して距離微分した未スケール値である。車両側の`grade_scale`とは分離し、選択した窓・距離ずれ・train/holdout RMSE・全候補数をsummaryへ残す。

## WiFi 文字列通信
- 推奨: UTF-8 UDP JSON
- vehicle 例:
  - `{"type":"vehicle_state","speed_kmh":72.3,"soc":0.83,"batt_temp_c":34.2,"batt_current_a":8.5,"batt_voltage_v":97.6,"solar_power_w":410.0,"lat":...}`
- chase 例:
  - `{"type":"chase_state","speed_kmh":74.0,"lat":...,"wind_speed_ms":6.5,"wind_dir_deg":121.0,"course_deg":176.0}`
- planner 応答例:
  - `{"type":"planner_command","planner":{"speed_cmd_kmh":68.0,"upper_speed_cmd_kmh":69.0,"drive_mode":"eco"}}`
- `key=value` 形式も受理
- 参考:
  - `scripts/wifi_vehicle_sender_example.py`
  - `scripts/wifi_chase_sender_example.py`
  - `templates/network/esp32_planner_receiver_example.ino`

## 現在の fitted 研究候補例（未昇格）
- 以下は immutable な MLE35 研究候補であり、canonical live profile ではない。
- 本番用 `profile_operational_fine.yaml` は独立モデル検証ゲート未通過の候補を自動採用しないため、`CdA=0.109802`、`Crr=0.006560`、`P_aux=P_aux_stopped=20.891 W`、`P_aux_night=0 W`、`E_nom_Wh=2899.987`、`Q_nom_Ah=31.783316` を保持している。
- 旧値の方が正確という意味ではなく、MLE35を研究用GPU探索と厳密replayで評価し、独立検証ゲートを通すまで本番へ混入させないための分離である。
- 参照:
  - `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/reports/current_maps_and_coefficients.md`
- 代表値:
  - `m = 235.0`
  - `CdA = 0.111167`
  - `Crr = 0.006262`
  - `P_aux = 21.021 W`
  - `P_aux_stopped = 21.021 W`
  - `P_aux_night = 0 W`
  - `E_nom_Wh = 3011.000`, `Q_nom_Ah = 33.000`
  - `r_polarization_ohm = 0.084252`, `polarization_tau_sec = 73.595`
  - `panel_gain = 0.712687`
  - `solar_measurement_gain_to_pack = 0.922613`
  - `drive_eff_scale = 1.034296`
  - `rint_scale = 0.900000`
- vehicle-conditional replay:
  - clean power RMSE `201.344 W`, clean voltage RMSE `0.968 V`
  - 2831 km anchor SoC error `0.006821`
- weather/PV end-to-end replay:
  - clean power RMSE `246.088 W`, clean voltage RMSE `2.113 V`
  - 25 km energy RMSE `102.944 Wh`
- 2831 km terminal SoC evidence:
  - evidence interval `0.332236` to `0.528667`
  - spread `19.643 percentage points`; therefore `high_precision_gate_pass = false`
- no-trouble MPC experiment:
  - full course `3026.9 km`, start SoC `0.98`, official control stops only, night auxiliary power `0 W`
  - `bwsc2025_official_control_stops.yaml` の9地点を各1800秒停止し、開場前は待機、閉鎖後到着は不成立
  - Adelaide絶対締切 `2025-08-29T08:00:00Z`（現地17:30）超過も不成立
  - integration meshes `5/1/0.1 km`; independent control spacings `25/5/2/1 km`
  - control dimensions `123/607/1515/3028`
  - four seeds, `8400` generations, `32,993,280` CUDA-proposed policies
  - every final policy requires separate fixed-policy 1 Hz replay and mesh convergence
  - CEM is not a proof of the continuous global optimum

## GPU探索結果とlive MPCの接続
- `gpu_upper_policy_search.py` は全行程の速度方策をオフラインで提案する。これは実行時のMPCそのものではない。
- `profile_exact_selected.yaml` は受入試験用であり、方策を固定して1 Hz full replayを再現する。
- `profile_live_mpc_learned.yaml` は受入済みCSVを `paths.initial_upper_policy_csv` に設定するが、方策を固定しない。
- `mpc_node.py` は起動時に方策CSVを現在の距離格子へ補間して初期解に使い、その後は実測SoC、現在距離、更新天候、制約を用いて上位MPCを再度解く。
- 2回目以降の再計画では直前のMPC解を移動した格子へ補間する。従ってGPU方策は探索を高速化する事前解であり、live指令の最終決定権はreceding-horizon MPCにある。

## 典型コマンド
```powershell
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action build
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action forecast
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action simulate -Profile project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action up -Profile project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml
python scripts/run_vehicle_identification.py --profile project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml --quality ultra --output-tag <new_run_tag>
```

Slurm GPU serverでは提案探索と受入判定を分離する。
GPU探索は1割当内で4 seedを直列化する。`REPLICATE_INDEX=0..3`を別jobとして
投入した場合だけschedulerがGPU枠の範囲で並列化し、1 GPU内へ4 CUDA processを
競合配置しない。受入側はCPU処理なので、後述の12並列を使う。

```bash
sbatch --export=ALL,SOLAR_GPU_ROOT=$PWD,PYTHON_BIN=$HOME/.venvs/mpc_gpu/bin/python \
  scripts/run_solar_gpu_concurrent_campaign.sbatch <profile> <campaign_dir>

sbatch --dependency=afterok:<job_id> --export=ALL,SOLAR_GPU_ROOT=$PWD,PYTHON_BIN=$HOME/.venvs/mpc_gpu/bin/python \
  scripts/run_solar_gpu_acceptance_pipeline.sbatch <profile> <campaign_dir> <acceptance_dir>
```

独立ジョブ方式では`campaign_submission.yaml`の`finalize_job_id`を
`sbatch --dependency=afterok:<finalize_job_id>`に指定する。finalizerは4本すべての
`control_1km/latest_policy.csv`を確認してから`CAMPAIGN_COMPLETE`を書く。
投入profileのSHA-256は`campaign_submission.yaml`へ保存され、全stageが開始前に再検証する。
探索中にprofileが変わったrunは失敗扱いとし、異なる車両モデルの結果を混在させない。
受入ジョブは5/2/1 kmの3格子を並列にし、各格子内の4 seedも並列にするため、
最大12 CPUで固定policyの100 m予測と1 Hz全行程再生を行う。各seedは固有のprofile、
manifest、detail CSV、判定表を持ち、全worker終了後にだけ最速の可行seedを選ぶ。
1 seedの未可行は候補棄却であり、出力欠損または全seed未可行をstage失敗とする。

単一GPU割当方式では4本の`PIPELINE_COMPLETE`、独立ジョブ方式では4本の最終policy、さらに`CAMPAIGN_COMPLETE`、
`ACCEPTANCE_COMPLETE`を確認する。`ACCEPTANCE_FAILED`なら昇格しない。
exact 1 Hz replayとmesh収束だけが通った段階では`POLICY_ACCEPTANCE_COMPLETE`と
`profile_exact_selected_research.yaml`だけを作る。独立車両model gateも通った場合に限り
`ACCEPTANCE_COMPLETE`、`profile_exact_selected.yaml`、`profile_live_mpc_learned.yaml`を作る。
従って`POLICY_ACCEPTANCE_COMPLETE`と`ACCEPTANCE_FAILED`の併存は、方策計算は合格したが
車両モデルを実運用認定できないことを表す。
5 km、2 km、1 kmは別々に最適化したpolicyを使い、`--policy`には最細分の
1 km policyを渡す。2 km policyを1 kmとして再利用してはならない。

```powershell
python scripts\generate_gpu_acceptance_report.py `
  --profile <profile> --campaign-dir <campaign_dir> `
  --acceptance-dir <acceptance_dir> --fit-summary <fit_summary> `
  --promotion-gate <promotion_gate.json> --output-dir <report_dir>
```

生成PDFはGPU収束履歴、全exact順位、1 Hz fullsim、積分・制御格子収束、
独立モデルgateを一つにまとめる。

## 関連成果物
- PDF 本体: `docs/solar_all_in_one_manual/solar_all_in_one_manual.pdf`
- TeX 本体: `docs/solar_all_in_one_manual/solar_all_in_one_manual.tex`
- 旧 flow workbook: `docs/flow_workbook/solar_package_flow_workbook.pdf`
