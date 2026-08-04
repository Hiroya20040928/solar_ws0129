# Current execution dependency manifest

This is the complete source/input inventory for the supported solar-car workflows.
Past runs, logs, simulation CSVs, checkpoints, TensorBoard data, reports, QA images,
and build/install artifacts are excluded.

- Unique files: **301**
- Missing required files: **0**
- CSV contains file size and SHA-256 for reproducibility.
- PASSO and magnetic-coupler files are outside this solar-car execution scope.

## Important outputs exceptions

Files in `outputs/identification/adopted_maps`, `grounded_base_maps`, and the selected
MLE35 research profile are included only when they are consumed as current model inputs.
Other files below `outputs` are not dependencies and are excluded.

## GPU/CEM source (18)

- `mpc_solarcar/route_utils.py` - MLE/re-identification, ROS and simulation, multi-fidelity CEM and exact acceptance, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `scripts/check_gpu_surrogate_feasibility.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/check_policy_weather_input.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/finalize_solar_gpu_campaign.sbatch` - multi-fidelity CEM and exact acceptance
- `scripts/generate_gpu_acceptance_report.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/gpu_upper_policy_search.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/merge_exact_candidate_rankings.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/rank_gpu_upper_policy_candidates.py` - multi-fidelity CEM and exact acceptance
- `scripts/resubmit_solar_gpu_refinement_chain.sh` - multi-fidelity CEM and exact acceptance
- `scripts/run_solar_fullsim_cpu.sbatch` - multi-fidelity CEM and exact acceptance
- `scripts/run_solar_gpu_acceptance_pipeline.sbatch` - multi-fidelity CEM and exact acceptance
- `scripts/run_solar_gpu_concurrent_campaign.sbatch` - multi-fidelity CEM and exact acceptance
- `scripts/run_solar_mesh_convergence_cpu.sbatch` - multi-fidelity CEM and exact acceptance
- `scripts/run_solar_upper_gpu_search.sbatch` - multi-fidelity CEM and exact acceptance
- `scripts/run_upper_mesh_convergence.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/setup_gpu_server_env.sh` - multi-fidelity CEM and exact acceptance
- `scripts/submit_solar_gpu_multifidelity_campaign.sh` - multi-fidelity CEM and exact acceptance
- `scripts/validate_gpu_upper_policy_candidates.py` - multi-fidelity CEM and exact acceptance, regression tests

## Grafana (5)

- `grafana/dashboards/solarcar-ems.json` - grafana monitoring
- `grafana/docker-compose.yml` - grafana monitoring
- `grafana/prometheus.yml` - grafana monitoring
- `grafana/provisioning/dashboards/dashboards.yml` - grafana monitoring
- `grafana/provisioning/datasources/prometheus.yml` - grafana monitoring

## ROS launch (6)

- `launch/solar_measurement.launch.py` - sim/measure/live/live_wifi
- `launch/solar_race_live.launch.py` - sim/measure/live/live_wifi
- `launch/solar_race_live_wifi.launch.py` - sim/measure/live/live_wifi
- `launch/solarcar_sim.launch.py` - sim/measure/live/live_wifi
- `mpc_solarcar/live_launch.py` - sim/measure/live/live_wifi
- `mpc_solarcar/solar_profile.py` - MLE/re-identification, ROS and simulation, basic identification, regression tests, sim/measure/live/live_wifi

## ROS runtime source (31)

- `mpc_solarcar/__init__.py` - sim/measure/live/live_wifi
- `mpc_solarcar/dashboard_node.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/distance_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/estimator.py` - sim/measure/live/live_wifi
- `mpc_solarcar/forecast_grid.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/gps_sim_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/grade_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/model.py` - MLE/re-identification, ROS and simulation, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/mpc_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/path_utils.py` - sim/measure/live/live_wifi
- `mpc_solarcar/route_utils.py` - MLE/re-identification, ROS and simulation, multi-fidelity CEM and exact acceptance, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/schedule_utils.py` - CPU self-learning, MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/signal_utils.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/solar_autocal_logic.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/solar_autocal_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/solar_logger_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/solar_preflight_logic.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/solar_preflight_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/solar_profile.py` - MLE/re-identification, ROS and simulation, basic identification, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/solar_state_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/speed_command_bridge_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/telemetry_protocol.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/telemetry_text_bridge_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/upper_cost.py` - CPU self-learning, MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_horizon.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_policy.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_solver.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/utils_maps.py` - MLE/re-identification, ROS and simulation, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/weather_fetch_node.py` - sim/measure/live/live_wifi
- `mpc_solarcar/weather_utils.py` - ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/wind_correction_node.py` - sim/measure/live/live_wifi

## current operational input (28)

- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/observed/bwsc2025_observed_log_5s.csv` - MLE/re-identification, active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_actual_drive_schedule.yaml` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_actual_stops.yaml` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_drive_schedule.yaml` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_official_control_stops.yaml` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/route/bwsc2025_fitted_mle8_mass235_mapfit_route_profile.csv` - current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/route/bwsc2025_fitted_mle8_mass235_mapfit_route_waypoints.csv` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/route/bwsc2025_fitted_mle8_mass235_mapfit_speed_profile.csv` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_historical_pv_conditioned_weather_grid.csv` - current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_historical_pv_conditioned_weather_grid.summary.yaml` - current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_observed_weather_10min.csv` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/adopted_maps/drive_eff_map.csv` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/adopted_maps/drive_eff_map_eco.csv` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/adopted_maps/drive_eff_map_power.csv` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/adopted_maps/mppt_eff_map.csv` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/adopted_maps/ocv_soc_curve.csv` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/adopted_maps/panel_eff_map.csv` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/adopted_maps/regen_eff_map.csv` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/adopted_maps/regen_eff_map_eco.csv` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/adopted_maps/regen_eff_map_power.csv` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/adopted_maps/Rint_T_by_soc_fitted_grounded.csv` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/bwsc2025_fitted_mle19_energywindow_inertia_generic_fit_summary.yaml` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/terminal_soc_consistency.yaml` - current BWSC2025 workflows; exception: current profile consumes adopted model input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml` - current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml` - current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml` - current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_operational_fine.yaml` - current BWSC2025 workflows

## current research input (23)

- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/observed/bwsc2025_observed_log_5s.csv` - MLE/re-identification, active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_actual_drive_schedule.yaml` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_actual_stops.yaml` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_drive_schedule.yaml` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_official_control_stops.yaml` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/route/bwsc2025_fitted_mle8_mass235_mapfit_route_waypoints.csv` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/route/bwsc2025_fitted_mle8_mass235_mapfit_speed_profile.csv` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_observed_weather_10min.csv` - active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_maps/drive_eff_map.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_maps/drive_eff_map_eco.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_maps/drive_eff_map_power.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_maps/mppt_eff_map.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_maps/ocv_soc_curve.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_maps/panel_eff_map.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_maps/regen_eff_map.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_maps/regen_eff_map_eco.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_maps/regen_eff_map_power.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_maps/Rint_T_by_soc_fitted_grounded.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/adopted_route_profile.csv` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/bwsc2025_fitted_mle19_energywindow_inertia_generic_fit_summary.yaml` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/profile_operational_gpu_research.yaml` - active MLE35 GPU campaign; exception: active research input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1/terminal_soc_consistency.yaml` - active MLE35 GPU campaign; exception: active research input under outputs

## dashboard (3)

- `dashboard/app.js` - live/dashboard
- `dashboard/index.html` - live/dashboard
- `dashboard/style.css` - live/dashboard

## demo configuration (17)

- `config/solar/bwsc_2027_demo.yaml` - demo ROS/simulation
- `project_packages/bwsc2027_template/data/race/control_stops.yaml` - demo ROS/simulation
- `project_packages/bwsc2027_template/data/race/drive_schedule.yaml` - demo ROS/simulation
- `project_packages/bwsc2027_template/data/route/route_profile.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/data/route/route_waypoints.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/data/route/speed_profile.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/data/weather/forecast_10min.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/maps/drive_eff_map.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/maps/drive_eff_map_eco.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/maps/drive_eff_map_power.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/maps/mppt_eff_map.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/maps/ocv_soc_curve.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/maps/panel_eff_map.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/maps/regen_eff_map.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/maps/regen_eff_map_eco.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/maps/regen_eff_map_power.csv` - demo ROS/simulation
- `project_packages/bwsc2027_template/maps/rint_map.csv` - demo ROS/simulation

## entry/build (11)

- `.gitignore` - install and dispatch
- `Install-SolarSim.ps1` - install and dispatch
- `package.xml` - install and dispatch
- `pytest.ini` - install and dispatch
- `requirements-dev.txt` - install and dispatch
- `requirements-weather.txt` - install and dispatch
- `resource/mpc_solarcar` - install and dispatch
- `scripts/bootstrap_ubuntu_humble.sh` - ROS and simulation, install and dispatch
- `setup.cfg` - install and dispatch
- `setup.py` - install and dispatch
- `SolarSim.ps1` - install and dispatch

## identification evidence (60)

- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/1.BWSC2025_YATA 修正 1 .xls` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/AllDay/BWSC2025 時系列別メモ.pdf` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/AllDay/BWSC2025時系列メモ.xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/AllDay/Lap_Wh.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/AllDay/ZP Data処理 全行程.xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/AllDay/レース中の書き込みデータ2025-BWSC-Route-Notes.pdf` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day1/ZP_Data0824 1日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day1/ZP_Data0824 1日目temperature.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day1/ZP_Data0824day1.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day2/data_times.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day2/ZP_Data0825 2日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day2/ZP_Data0825day2.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day3/ZP_Data0826 3日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day3/ZP_Data0826day3.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day4/ZP_Data0827 4日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day4/ZP_Data0827day4.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day5,6充電記録データ.xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day5/ZP_Data0828 5日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day5/ZP_Data0828day5.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day6/10km_Data0829day6.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/Day6/ZP_Datayosen 6日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/MPF4279xシリーズによる正確な充電状態の判断 (パートI).url` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/WSC_20230915_和歌山大学様_M2096_特性データ (1).xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/ZP_Data_20231023.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/zp加工データ/ZP_Data0824day1.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/zp加工データ/ZP_Data0825day2.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/zp加工データ/ZP_Data0826day3.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/zp加工データ/ZP_Data0827day4.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/zp加工データ/ZP_Data0828day5.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/元データ/8.16(15.22~15.27)発電実験.xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/元データ/8.18　発電実験　ダーウィン.xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/元データ/Australia_勾配抵抗.xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/元データ/ZP_Data0824 1日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/元データ/ZP_Data0825 2日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/元データ/ZP_Data0826 3日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/元データ/ZP_Data0827 4日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/元データ/ZP_Data0828 5日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/元データ/ZP_Datayosen 6日目.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/元データ/本戦バッテリー放電実験2024_05_26.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/参考になるデータ/2024_05_26_DischargeTest.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/参考になるデータ/8.16(15.22~15.27)発電実験.xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/参考になるデータ/8.18　発電実験　ダーウィン.xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/参考になるデータ/Australia_勾配抵抗.xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/参考になるデータ/BWSC2025バッテリーを6並25直列にした理由.pdf` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/参考になるデータ/放電実験データからのSOC_V対応表.xlsx` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2560km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2590km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2620km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2670km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2720km(CS9).csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2750km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2800km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2830km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2850km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2900km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_2950km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_3000km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/csv_output/ERA5_20250829_3030km.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/analysis_zip/BWSC2025データ分析いろいろ/試しの出力データ/Lap_Wh.csv` - MLE/re-identification
- `inputs/external_docs/bwsc2025_20260713/text_zip/BWSC2025データまとめテキスト/BWSC2025バッテリーSoC推測.pdf` - MLE/re-identification

## identification input (26)

- `inputs/external_docs/bwsc2025_20260713/pptx/報告会資料_2025_山下将矢.pptx` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/actual_event_annotations.yaml` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/counterfactual_no_trouble.yaml` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/document_inventory.json` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/evidence_notes.md` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/field_tests/10km_Data0829day6.csv` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/field_tests/8.16(15.22~15.27)発電実験.xlsx` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/field_tests/8.18　発電実験　ダーウィン.xlsx` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/field_tests/Day5,6充電記録データ.xlsx` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/field_tests/ERA5_20250829_2830km.csv` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/grounded_map_sources.yaml` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/terminal_anchor.yaml` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/generation_lineage.yaml` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/identification_manifest.yaml` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/identification_manifest_pulse_terminal.yaml` - MLE/re-identification
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/observed/bwsc2025_observed_log_5s.csv` - MLE/re-identification, active MLE35 GPU campaign, current BWSC2025 workflows
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/grounded_base_maps/drive_eff_map.csv` - MLE/re-identification; exception: grounded base map is an explicit MLE input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/grounded_base_maps/drive_eff_map_eco.csv` - MLE/re-identification; exception: grounded base map is an explicit MLE input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/grounded_base_maps/drive_eff_map_power.csv` - MLE/re-identification; exception: grounded base map is an explicit MLE input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/grounded_base_maps/mppt_eff_map.csv` - MLE/re-identification; exception: grounded base map is an explicit MLE input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/grounded_base_maps/ocv_soc_curve.csv` - MLE/re-identification; exception: grounded base map is an explicit MLE input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/grounded_base_maps/panel_eff_map.csv` - MLE/re-identification; exception: grounded base map is an explicit MLE input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/grounded_base_maps/regen_eff_map.csv` - MLE/re-identification; exception: grounded base map is an explicit MLE input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/grounded_base_maps/regen_eff_map_eco.csv` - MLE/re-identification; exception: grounded base map is an explicit MLE input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/grounded_base_maps/regen_eff_map_power.csv` - MLE/re-identification; exception: grounded base map is an explicit MLE input under outputs
- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/grounded_base_maps/Rint_T_by_soc_grounded.csv` - MLE/re-identification; exception: grounded base map is an explicit MLE input under outputs

## identification source (30)

- `mpc_solarcar/model.py` - MLE/re-identification, ROS and simulation, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/route_utils.py` - MLE/re-identification, ROS and simulation, multi-fidelity CEM and exact acceptance, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/schedule_utils.py` - CPU self-learning, MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/signal_utils.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/solar_profile.py` - MLE/re-identification, ROS and simulation, basic identification, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_cost.py` - CPU self-learning, MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_horizon.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_solver.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/utils_maps.py` - MLE/re-identification, ROS and simulation, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `scripts/adopt_conditional_identification_candidate.py` - MLE/re-identification
- `scripts/assess_terminal_soc_consistency.py` - MLE/re-identification, regression tests
- `scripts/audit_identification_residuals.py` - MLE/re-identification, regression tests
- `scripts/build_bwsc2025_fitted_package.py` - MLE/re-identification, package, blank, audit, regression tests
- `scripts/build_fastest_certified_profile.py` - MLE/re-identification, regression tests
- `scripts/build_identification_evidence_bundle.py` - MLE/re-identification
- `scripts/build_ocv_curve.py` - basic identification
- `scripts/build_pv_maps_from_csv.py` - basic identification
- `scripts/build_rint_map_from_timeseries.py` - basic identification
- `scripts/build_route_profile_from_gps.py` - basic identification
- `scripts/check_model_validation_gate.py` - MLE/re-identification
- `scripts/compare_identification_runs.py` - MLE/re-identification
- `scripts/create_operational_fine_profile.py` - MLE/re-identification
- `scripts/fit_vehicle_params.py` - basic identification, regression tests
- `scripts/normalize_bwsc2025_field_evidence.py` - MLE/re-identification
- `scripts/promote_identification_run.py` - MLE/re-identification, regression tests
- `scripts/regenerate_identification_report.py` - MLE/re-identification
- `scripts/run_identification_pipeline.py` - basic identification
- `scripts/run_vehicle_identification.py` - MLE/re-identification, regression tests
- `scripts/run_vehicle_identification_cpu.sbatch` - MLE/re-identification
- `scripts/solar_sim.py` - MLE/re-identification, ROS and simulation, regression tests

## input template (28)

- `templates/aux_load_profile_template.csv` - blank package and identification
- `templates/battery_thermal_template.yaml` - blank package and identification
- `templates/drive_eff_map_template.csv` - blank package and identification
- `templates/drive_schedule_template.yaml` - blank package and identification
- `templates/identification/actual_event_annotations_template.yaml` - blank package and identification
- `templates/identification/battery_pulse_template.csv` - blank package and identification
- `templates/identification/battery_rest_template.csv` - blank package and identification
- `templates/identification/bom_hourly_solar_route_template.csv` - blank package and identification
- `templates/identification/counterfactual_no_trouble_template.yaml` - blank package and identification
- `templates/identification/drive_timeseries_template.csv` - blank package and identification
- `templates/identification/evidence_notes_template.md` - blank package and identification
- `templates/identification/gps_track_template.csv` - blank package and identification
- `templates/identification/grounded_map_sources_template.yaml` - blank package and identification
- `templates/identification/observed_replay_log_template.csv` - blank package and identification
- `templates/identification/panel_sweep_template.csv` - blank package and identification
- `templates/identification/source_map_catalog_template.csv` - blank package and identification
- `templates/identification/terminal_anchor_template.yaml` - blank package and identification
- `templates/identification_manifest_template.yaml` - blank package and identification
- `templates/motor_tau_limit_template.csv` - blank package and identification
- `templates/mppt_eff_map_template.csv` - blank package and identification
- `templates/network/esp32_planner_receiver_example.ino` - blank package and identification
- `templates/ocv_soc_curve_template.csv` - blank package and identification
- `templates/panel_eff_map_template.csv` - blank package and identification
- `templates/regen_eff_map_template.csv` - blank package and identification
- `templates/rint_map_template.csv` - blank package and identification
- `templates/route_profile_template.csv` - blank package and identification
- `templates/solar_params_template.yaml` - blank package and identification
- `templates/speed_profile_template.csv` - blank package and identification

## learning source (3)

- `mpc_solarcar/schedule_utils.py` - CPU self-learning, MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_cost.py` - CPU self-learning, MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `scripts/tune_upper_planner_weights.py` - CPU self-learning, regression tests

## packaging/audit source (12)

- `mpc_solarcar/model.py` - MLE/re-identification, ROS and simulation, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/route_utils.py` - MLE/re-identification, ROS and simulation, multi-fidelity CEM and exact acceptance, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/utils_maps.py` - MLE/re-identification, ROS and simulation, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `scripts/audit_solar_package.py` - package, blank, audit
- `scripts/build_bwsc2025_fitted_package.py` - MLE/re-identification, package, blank, audit, regression tests
- `scripts/clone_vehicle_identification_package.py` - package, blank, audit, regression tests
- `scripts/create_project_packages.py` - package, blank, audit
- `scripts/create_solarcar_blank_package.py` - package, blank, audit, regression tests
- `scripts/create_solarcar_only_package.py` - package, blank, audit, regression tests
- `scripts/generate_execution_dependency_manifest.py` - package, blank, audit
- `scripts/generate_package_inventory.py` - package, blank, audit
- `scripts/package_execution_dependencies.py` - package, blank, audit

## runtime/offline source (17)

- `mpc_solarcar/model.py` - MLE/re-identification, ROS and simulation, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/route_utils.py` - MLE/re-identification, ROS and simulation, multi-fidelity CEM and exact acceptance, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/schedule_utils.py` - CPU self-learning, MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/signal_utils.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/solar_profile.py` - MLE/re-identification, ROS and simulation, basic identification, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_cost.py` - CPU self-learning, MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_horizon.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_solver.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/utils_maps.py` - MLE/re-identification, ROS and simulation, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/weather_utils.py` - ROS and simulation, regression tests, sim/measure/live/live_wifi
- `scripts/bootstrap_ubuntu_humble.sh` - ROS and simulation, install and dispatch
- `scripts/build_historical_weather_counterfactual_grid.py` - ROS and simulation, regression tests
- `scripts/dashboard_demo_server.py` - ROS and simulation
- `scripts/export_rqt_graph.py` - ROS and simulation
- `scripts/fetch_weather_forecast.py` - ROS and simulation
- `scripts/solar_control.sh` - ROS and simulation
- `scripts/solar_sim.py` - MLE/re-identification, ROS and simulation, regression tests

## validation source (58)

- `mpc_solarcar/dashboard_node.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/forecast_grid.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/model.py` - MLE/re-identification, ROS and simulation, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/route_utils.py` - MLE/re-identification, ROS and simulation, multi-fidelity CEM and exact acceptance, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/schedule_utils.py` - CPU self-learning, MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/signal_utils.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/solar_autocal_logic.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/solar_preflight_logic.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/solar_profile.py` - MLE/re-identification, ROS and simulation, basic identification, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/telemetry_protocol.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_cost.py` - CPU self-learning, MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_horizon.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_policy.py` - regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/upper_solver.py` - MLE/re-identification, ROS and simulation, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/utils_maps.py` - MLE/re-identification, ROS and simulation, package, blank, audit, regression tests, sim/measure/live/live_wifi
- `mpc_solarcar/weather_utils.py` - ROS and simulation, regression tests, sim/measure/live/live_wifi
- `scripts/assess_terminal_soc_consistency.py` - MLE/re-identification, regression tests
- `scripts/audit_bwsc2025_weather_power_timestep.py` - regression tests
- `scripts/audit_identification_residuals.py` - MLE/re-identification, regression tests
- `scripts/build_bwsc2025_fitted_package.py` - MLE/re-identification, package, blank, audit, regression tests
- `scripts/build_fastest_certified_profile.py` - MLE/re-identification, regression tests
- `scripts/build_historical_weather_counterfactual_grid.py` - ROS and simulation, regression tests
- `scripts/check_gpu_surrogate_feasibility.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/check_policy_weather_input.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/clone_vehicle_identification_package.py` - package, blank, audit, regression tests
- `scripts/create_bwsc2025_fullcourse_nominal_profile.py` - regression tests
- `scripts/create_solarcar_blank_package.py` - package, blank, audit, regression tests
- `scripts/create_solarcar_only_package.py` - package, blank, audit, regression tests
- `scripts/fit_vehicle_params.py` - basic identification, regression tests
- `scripts/generate_fit_fullsim_report.py` - regression tests
- `scripts/generate_gpu_acceptance_report.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/gpu_upper_policy_search.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/import_bom_satellite_solar.py` - regression tests
- `scripts/merge_exact_candidate_rankings.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/promote_identification_run.py` - MLE/re-identification, regression tests
- `scripts/rebuild_planning_weather_from_cache.py` - regression tests
- `scripts/run_upper_mesh_convergence.py` - multi-fidelity CEM and exact acceptance, regression tests
- `scripts/run_vehicle_identification.py` - MLE/re-identification, regression tests
- `scripts/solar_sim.py` - MLE/re-identification, ROS and simulation, regression tests
- `scripts/tune_upper_planner_weights.py` - CPU self-learning, regression tests
- `scripts/validate_gpu_upper_policy_candidates.py` - multi-fidelity CEM and exact acceptance, regression tests
- `tests/test_bom_satellite_solar_import.py` - regression tests
- `tests/test_dashboard_status.py` - regression tests
- `tests/test_fit_vehicle_params.py` - regression tests
- `tests/test_forecast_grid.py` - regression tests
- `tests/test_gpu_upper_policy_search.py` - regression tests
- `tests/test_historical_weather_counterfactual.py` - regression tests
- `tests/test_identification_and_upper_solver.py` - regression tests
- `tests/test_identification_residual_audit.py` - regression tests
- `tests/test_ros_package_layout.py` - regression tests
- `tests/test_route_profile_averaging.py` - regression tests
- `tests/test_sim_detail_mesh_grafana.py` - regression tests
- `tests/test_solar_autocal_logic.py` - regression tests
- `tests/test_solar_preflight_logic.py` - regression tests
- `tests/test_solar_sim_regressions.py` - regression tests
- `tests/test_telemetry_protocol.py` - regression tests
- `tests/test_upper_horizon.py` - regression tests
- `tests/test_weather_identification_pipeline.py` - regression tests

## Generated handoff contracts (not source dependencies)

The GPU pipeline creates `checkpoint.pt`, `latest_policy.csv`, `summary.json`,
completion markers, exact replay CSVs, and acceptance reports. They are outputs of
the listed source/input set, so no existing historical copy is included above.
