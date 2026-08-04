# Solar package static audit

- Generated UTC: 2026-07-17T05:43:46.020233+00:00
- Python files parsed: 151
- PASS/WARN/ERROR: 82/0/0

| Result | Check | Path | Detail |
|---|---|---|---|
| PASS | python_parse | . | 151 Python files parsed |
| PASS | launch_entrypoint | mpc_solarcar/dashboard_node.py | dashboard_node -> mpc_solarcar.dashboard_node:main |
| PASS | launch_entrypoint | mpc_solarcar/distance_node.py | distance_node -> mpc_solarcar.distance_node:main |
| PASS | launch_entrypoint | mpc_solarcar/gps_sim_node.py | gps_sim_node -> mpc_solarcar.gps_sim_node:main |
| PASS | launch_entrypoint | mpc_solarcar/grade_node.py | grade_node -> mpc_solarcar.grade_node:main |
| PASS | launch_entrypoint | mpc_solarcar/mpc_node.py | mpc_node -> mpc_solarcar.mpc_node:main |
| PASS | launch_entrypoint | mpc_solarcar/solar_autocal_node.py | solar_autocal_node -> mpc_solarcar.solar_autocal_node:main |
| PASS | launch_entrypoint | mpc_solarcar/solar_logger_node.py | solar_logger_node -> mpc_solarcar.solar_logger_node:main |
| PASS | launch_entrypoint | mpc_solarcar/solar_preflight_node.py | solar_preflight_node -> mpc_solarcar.solar_preflight_node:main |
| PASS | launch_entrypoint | mpc_solarcar/solar_state_node.py | solar_state_node -> mpc_solarcar.solar_state_node:main |
| PASS | launch_entrypoint | mpc_solarcar/speed_command_bridge_node.py | speed_command_bridge_node -> mpc_solarcar.speed_command_bridge_node:main |
| PASS | launch_entrypoint | mpc_solarcar/telemetry_text_bridge_node.py | telemetry_text_bridge_node -> mpc_solarcar.telemetry_text_bridge_node:main |
| PASS | launch_entrypoint | mpc_solarcar/weather_fetch_node.py | weather_fetch_node -> mpc_solarcar.weather_fetch_node:main |
| PASS | launch_entrypoint | mpc_solarcar/wind_correction_node.py | wind_correction_node -> mpc_solarcar.wind_correction_node:main |
| PASS | solar_scope | . | solar launch/runtime sources contain no PASSO, magnetic, OBD, MAF, or fuel dependency |
| PASS | soc_contract | config/solar/bwsc_2027_demo.yaml | soc0=0.95 <= soc_max=1.0 |
| PASS | aux_contract | config/solar/bwsc_2027_demo.yaml | driving/day-stop=0.0 W, night=0 W |
| PASS | wifi_time_contract | config/solar/bwsc_2027_demo.yaml | UTC required; age/future/order gates enabled |
| PASS | soc_contract | project_packages/bwsc2025_public/profile.yaml | soc0=0.95 <= soc_max=0.98 |
| PASS | aux_contract | project_packages/bwsc2025_public/profile.yaml | driving/day-stop=8.0 W, night=0 W |
| PASS | wifi_time_contract | project_packages/bwsc2025_public/profile.yaml | UTC required; age/future/order gates enabled |
| PASS | soc_contract | project_packages/bwsc2027_template/profile.yaml | soc0=0.95 <= soc_max=1.0 |
| PASS | aux_contract | project_packages/bwsc2027_template/profile.yaml | driving/day-stop=0.0 W, night=0 W |
| PASS | wifi_time_contract | project_packages/bwsc2027_template/profile.yaml | UTC required; age/future/order gates enabled |
| PASS | soc_contract | project_packages/other_template/profile.yaml | soc0=0.95 <= soc_max=1.0 |
| PASS | aux_contract | project_packages/other_template/profile.yaml | driving/day-stop=0.0 W, night=0 W |
| PASS | wifi_time_contract | project_packages/other_template/profile.yaml | UTC required; age/future/order gates enabled |
| PASS | soc_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml | soc0=0.98 <= soc_max=0.98 |
| PASS | aux_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml | driving/day-stop=20.891 W, night=0 W |
| PASS | wifi_time_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml | UTC required; age/future/order gates enabled |
| PASS | drive_efficiency_basis_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml | M2096 Pm/Pin total-efficiency map active; no duplicate inverter loss |
| PASS | air_density_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml | temperature/elevation-dependent ideal-gas density enabled |
| PASS | soc_state_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml | charge SoC with Q_nom_Ah=31.783316 |
| PASS | full_course_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml | full course=3026.9 km |
| PASS | official_event_timing_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_official_control_stops.yaml | 9 official 1800 s stops and finish deadline 2025-08-29T08:00:00Z |
| PASS | ocv_voltage_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml | OCV max=106.889 V <= V_max=108.750 V; product limit grounded at 108.750 V |
| PASS | grade_observation_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/route/bwsc2025_fitted_mle8_mass235_mapfit_route_profile.csv | 30277 elevation-backed route rows; strictly monotonic distance |
| PASS | weather_grid_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv | independent instant GHI/DNI/DHI through 3026.9 km |
| PASS | weather_grid_key_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv | 24696 unique (time,s_km) rows |
| PASS | weather_grid_range_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv | GHI=[0.0,934.5], DNI=[0.0,986.5], DHI=[0.0,365.5], Tamb_C=[3.8,37.9] |
| PASS | pv_hardware_limit_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml | declared aggregate MPPT limit=1000.0 W |
| PASS | soc_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml | soc0=0.98 <= soc_max=0.98 |
| PASS | aux_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml | driving/day-stop=20.891 W, night=0 W |
| PASS | wifi_time_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml | UTC required; age/future/order gates enabled |
| PASS | drive_efficiency_basis_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml | M2096 Pm/Pin total-efficiency map active; no duplicate inverter loss |
| PASS | air_density_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml | temperature/elevation-dependent ideal-gas density enabled |
| PASS | soc_state_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml | charge SoC with Q_nom_Ah=31.783316 |
| PASS | full_course_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml | full course=3026.9 km |
| PASS | official_event_timing_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_official_control_stops.yaml | 9 official 1800 s stops and finish deadline 2025-08-29T08:00:00Z |
| PASS | ocv_voltage_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml | OCV max=106.889 V <= V_max=108.750 V; product limit grounded at 108.750 V |
| PASS | weather_grid_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv | independent instant GHI/DNI/DHI through 3026.9 km |
| PASS | weather_grid_key_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv | 24696 unique (time,s_km) rows |
| PASS | weather_grid_range_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv | GHI=[0.0,934.5], DNI=[0.0,986.5], DHI=[0.0,365.5], Tamb_C=[3.8,37.9] |
| PASS | pv_hardware_limit_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml | declared aggregate MPPT limit=1000.0 W |
| PASS | soc_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml | soc0=0.98 <= soc_max=0.98 |
| PASS | aux_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml | driving/day-stop=20.891 W, night=0 W |
| PASS | wifi_time_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml | UTC required; age/future/order gates enabled |
| PASS | drive_efficiency_basis_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml | M2096 Pm/Pin total-efficiency map active; no duplicate inverter loss |
| PASS | air_density_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml | temperature/elevation-dependent ideal-gas density enabled |
| PASS | soc_state_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml | charge SoC with Q_nom_Ah=31.783316 |
| PASS | full_course_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml | full course=3026.9 km |
| PASS | official_event_timing_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_official_control_stops.yaml | 9 official 1800 s stops and finish deadline 2025-08-29T08:00:00Z |
| PASS | ocv_voltage_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml | OCV max=106.889 V <= V_max=108.750 V; product limit grounded at 108.750 V |
| PASS | historical_weather_separation_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml | PV-conditioned replay is explicitly labeled and isolated from nominal/live outputs |
| PASS | weather_grid_key_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_historical_pv_conditioned_weather_grid.csv | 24696 unique (time,s_km) rows |
| PASS | weather_grid_range_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_historical_pv_conditioned_weather_grid.csv | GHI=[0.0,1200.0], DNI=[0.0,1400.0], DHI=[0.0,499.9], Tamb_C=[3.8,37.9] |
| PASS | pv_hardware_limit_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_historical_counterfactual.yaml | declared aggregate MPPT limit=1000.0 W |
| PASS | soc_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_operational_fine.yaml | soc0=0.98 <= soc_max=0.98 |
| PASS | aux_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_operational_fine.yaml | driving/day-stop=20.891 W, night=0 W |
| PASS | wifi_time_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_operational_fine.yaml | UTC required; age/future/order gates enabled |
| PASS | drive_efficiency_basis_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_operational_fine.yaml | M2096 Pm/Pin total-efficiency map active; no duplicate inverter loss |
| PASS | air_density_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_operational_fine.yaml | temperature/elevation-dependent ideal-gas density enabled |
| PASS | soc_state_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_operational_fine.yaml | charge SoC with Q_nom_Ah=31.783316 |
| PASS | full_course_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_operational_fine.yaml | full course=3026.9 km |
| PASS | official_event_timing_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/race/bwsc2025_official_control_stops.yaml | 9 official 1800 s stops and finish deadline 2025-08-29T08:00:00Z |
| PASS | ocv_voltage_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_operational_fine.yaml | OCV max=106.889 V <= V_max=108.750 V; product limit grounded at 108.750 V |
| PASS | weather_grid_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv | independent instant GHI/DNI/DHI through 3026.9 km |
| PASS | weather_grid_key_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv | 24696 unique (time,s_km) rows |
| PASS | weather_grid_range_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/weather/bwsc2025_nominal_fullcourse_weather_grid.csv | GHI=[0.0,934.5], DNI=[0.0,986.5], DHI=[0.0,365.5], Tamb_C=[3.8,37.9] |
| PASS | pv_hardware_limit_contract | project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_operational_fine.yaml | declared aggregate MPPT limit=1000.0 W |
| PASS | blank_template | project_packages/bwsc2027_template | 14 route/weather/map/replay files are schema-only |
| PASS | blank_template | project_packages/other_template | 14 route/weather/map/replay files are schema-only |
