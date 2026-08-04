# MPCEMS YATA solar-car energy management

This repository is the ROS 2 energy-management package for YATA. It covers
vehicle identification, full-race simulation, hierarchical MPC, live WiFi
telemetry, command transmission, logging, weather correction, and a one-screen
dashboard. PASSO and magnetic-coupler work are not part of the solar-only
distribution.

## Is this MPC?

Yes. The runtime controller is hierarchical model predictive control.

1. The upper planner solves a nonlinear, distance-domain prediction problem
   over the remaining race. Its state includes distance, time, SoC, and battery
   temperature. Its manipulated variable is the speed plan. Route, weather,
   drive windows, stops, voltage/current limits, and efficiency maps are
   predicted through the vehicle model.
2. The lower planner runs at 1 Hz and tracks the upper speed reference while
   penalizing command movement and respecting rate limits.
3. In live operation the horizon is shifted and solved again after measurements
   or forecasts are updated. This is the receding-horizon MPC behavior.
4. A profile with <code>upper_replan_sec: 0</code> performs one full-race
   optimization in an offline simulation. It uses the same MPC prediction
   model, but it is not an hourly receding-horizon replay.

The upper numerical solver uses a bounded global candidate search followed by
local L-BFGS-B refinement. Two offline CEM tools have different roles:
`tune_upper_planner_weights.py` tunes objective weights, while
`gpu_upper_policy_search.py` proposes a complete distance-indexed speed policy.
Neither tool replaces the runtime controller. After independent exact replay
and mesh checks, the accepted policy is written to
`paths.initial_upper_policy_csv`; `mpc_node.py` interpolates it onto the current
control mesh as the initial guess and then solves the upper MPC again. Updated
telemetry, weather, route progress, constraints, and SoC therefore retain final
authority in live operation.

The Japanese design review for objective-function learning, absolute-distance
warm starts, multi-scenario CVaR evaluation, and the remaining safety gaps is
in `docs/mpc_objective_design_application_20260727.md`.

The acceptance pipeline deliberately creates two profiles.  The
`profile_exact_selected.yaml` profile locks the learned policy for repeatable
1 Hz certification.  The `profile_live_mpc_learned.yaml` profile uses the same
policy only as a warm start and preserves receding-horizon replanning.  Use the
second profile for live operation, never the locked certification profile.

## One-command entry

Run these commands in Windows PowerShell from the repository root:

    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action build
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action simulate -Profile project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile_fullsim_selflearned.yaml
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action fit -Profile project_packages/bwsc2027_template/profile.yaml
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action learn -Profile project_packages/bwsc2027_template/profile.yaml
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action audit
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action package
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action blank
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action grafana
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action grafana-stop
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action historical-weather -Profile project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action historical-simulate -Profile project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action up -Profile project_packages/bwsc2025_fitted_mle19_energywindow_inertia/profile.yaml
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action status
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action graph
    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action stop

<code>SolarSim.ps1</code> forwards the action, mode, and profile into WSL and
calls <code>scripts/solar_control.sh</code>. The shell script builds the ROS 2
workspace or dispatches to the matching launch/script entry.

## Modes and outputs

| Action or mode | Main entry | What runs | Main output |
|---|---|---|---|
| <code>simulate</code> | <code>scripts/solar_sim.py</code> | Full-race upper optimization and replay | versioned summary CSV, detail CSV, upper-plan CSV, HTML, manifest JSON |
| <code>sim</code> | <code>launch/solarcar_sim.launch.py</code> | GPS/state simulation, MPC, dashboard | ROS topics, dashboard, runtime logs |
| <code>measure</code> | <code>launch/solar_measurement.launch.py</code> | distance, grade, logger, dashboard | measurement CSV and route data |
| <code>live</code> | <code>launch/solar_race_live.launch.py</code> | weather, autocalibration, MPC, command bridge, logger, dashboard | 1 Hz commands and live CSV |
| <code>live_wifi</code> | <code>launch/solar_race_live_wifi.launch.py</code> | live mode plus telemetry text and wind correction | UDP input/output, ROS topics, corrected weather CSV |
| <code>forecast</code> | <code>scripts/fetch_weather_forecast.py</code> | route/time weather acquisition | forecast CSV selected by profile |
| <code>identify</code> | <code>scripts/run_identification_pipeline.py</code> | template measurement-map fitting | fitted maps and YAML |
| <code>fit</code> | <code>scripts/run_vehicle_identification.py</code> | segmented PV, battery, motion, map shape, and replay MLE | adopted maps, fit summary YAML, PDF |
| <code>learn</code> | <code>scripts/tune_upper_planner_weights.py</code> | CEM objective-weight search and multi-fidelity validation | TensorBoard log, trial CSV, tuned profile, PDF |
| <code>audit</code> | inventory, static audit, pytest | source/package contract verification | inventory CSV, audit JSON/Markdown, test result |
| <code>package</code> / <code>blank</code> | release builders | solar-only fitted copy / functionally equal empty copy | validated export directory and manifest |

All simulation outputs are auto-versioned. The stable pointer is the
<code>latest_simulation_run.json</code> in the configured output directory.
Never identify a result only by a generic filename; use the manifest and the
resolved profile saved beside it.

The detail CSV is the 1 Hz lower-command and energy-balance audit trail, not a
reduced plotting file. Every simulated second records the upper speed request,
lower filtered speed command, executed speed, raw/corrected PV, panel and MPPT efficiencies,
wheel/DC/pack power, voltage/current/OCV, internal and line resistance, Joule
losses, aerodynamic/rolling/grade forces, signed inertial power from the exact
kinetic-energy change, drive/regen map values, incremental
and cumulative Wh, all active model coefficients, and the exact map paths.
Rows are streamed directly to disk, so a full race does not retain hundreds of
thousands of wide rows in RAM. The lightweight HTML report uses one sampled row
per outer planner step, while the CSV remains complete.
Exact and fine-mesh profiles set <code>simulation.detail_compression=gzip</code>;
their complete audit trail is therefore named <code>*.csv.gz</code>. It remains
CSV data and can be read directly with <code>pandas.read_csv(path)</code>, without
expanding a multi-gigabyte temporary file first.

Do not confuse the two time-step columns. `outer_step_requested_dt_sec` is the
upper simulator request, normally 600 s. `outer_step_actual_dt_sec` can become
11.747 s or another short value when the next control stop, drive-window edge,
weather knot, or upper-policy segment lies inside that request. This is an
intentional event-boundary split. The lower-command audit remains
`step_dt_sec=1.0`; only the final row before an event may be shorter than one
second so elapsed time and energy integrate exactly.

## Package lifecycle

### 1. Prepare measured inputs

Start from <code>project_packages/bwsc2027_template</code> or the blank
distribution. Fill the raw templates under
<code>data/identification/raw</code>:

| Input | Required content |
|---|---|
| drive time series | UTC timestamp, speed, voltage, current, temperature, distance/GNSS, PV power where available |
| battery pulse | current step, loaded/rest voltage, temperature, SoC or capacity anchor |
| battery rest | relaxed OCV, temperature, independent SoC/capacity anchor |
| panel sweep | POA irradiance, cell/ambient temperature, panel and MPPT power |
| GPS track | UTC timestamp, latitude, longitude, altitude, course and distance |
| weak-current loads | subsystem state and measured auxiliary power |

Measured manufacturer curves and official tests belong under the evidence
directory. A grounded base map must be generated from those sources before
small MLE scale/shape corrections are accepted. The current evidence record is
<code>project_packages/bwsc2025_fitted_mle19_energywindow_inertia/data/identification/evidence/grounded_map_sources.yaml</code>.

バッテリーmapは、休止OCVと同一packのサブ秒pulseから同定した
`Uocv(z)`, `R0,total(z,T)`, `R1(z,T)`, `tau(z,T)`だけを実運用へ昇格できます。
負荷時放電曲線の傾き、固定40 mOhm/cell、容量温度係数からRintを生成する旧方式は廃止しました。
完全な測定形式、数式、MLE36反実仮想比較、live昇格gateは
<code>docs/battery_ecm_physical_revision_20260802.md</code>を参照してください。

### 2. Identify the vehicle

Run a versioned experiment (the PowerShell entry assigns the UTC tag):

    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action fit -Profile project_packages/bwsc2027_template/profile.yaml

For a direct Python run, always provide an immutable output tag:

    python scripts\run_vehicle_identification.py --profile project_packages\bwsc2027_template\profile.yaml --output-tag fit_YYYYMMDDTHHMMSSZ

For a historical log that has GNSS but not irradiance components, first create
an immutable external-weather-enriched copy:

    python scripts\enrich_replay_weather_components.py --input <observed.csv> --output <observed_weather.csv> --cache <route_weather_cache.csv>

The Open-Meteo request explicitly selects wind speed in m/s and the
`*_instant` variants of GHI, DNI, DHI, and BHI. The ordinary hourly radiation
variables are preceding-hour means and must not be interpolated as
instantaneous samples. Moving-PV fitting uses independent archive GHI only.
`GHI_effective`, reconstructed from measured PV, is diagnostic-only and is
never accepted as an identification input or end-to-end validation feature.
The no-trouble policy search likewise uses
`bwsc2025_nominal_fullcourse_weather_grid.csv`, whose rows retain the
Open-Meteo archive instant GHI/DNI/DHI at each route time and position. The
separate `bwsc2025_historical_pv_conditioned_weather_grid.csv` is a circular,
research-only replay aid and must never rank or certify a policy. Its latent
unclipped values are retained in `*_effective_unclipped`; ordinary radiation
columns are physically bounded before any diagnostic simulation reads them.
Stopped charging is fitted separately through `stop_tilt_fraction`, bounded
between horizontal GHI and a DNI/DHI-derived ideal-tracking POA reference.

Open-Meteo archive is reanalysis/model output, not a route-local irradiance
measurement.  For BWSC historical replay, the preferred independent source is
the Australian Bureau of Meteorology Himawari hourly exposure product
`IDE02327` (2 km) or `IDE02347` (5 km).  Historical files require NCI `rv74`
research access or a BOM data request.  Once the official NetCDF files are
available, import them without changing the active profile:

    python -m pip install -r requirements-weather.txt
    python scripts\import_bom_satellite_solar.py --netcdf <IDE02347 files...> --route project_packages\<vehicle>\data\route\<route_waypoints.csv> --base-weather project_packages\<vehicle>\data\weather\<planning_weather.csv> --output-weather project_packages\<vehicle>\outputs\weather_candidates\bom_candidate.csv --quality-json project_packages\<vehicle>\outputs\weather_candidates\bom_quality.json --normalized-output project_packages\<vehicle>\outputs\weather_candidates\bom_route_samples.csv

The importer converts hourly MJ/m2 exposure to interval-mean W/m2, aligns the
value to the accumulation-interval centre, and writes duplicate, range,
coverage, grid-distance, and provenance checks.  A failed quality JSON must not
replace `paths.forecast_csv`.  A manually route-sampled input can use
`templates/identification/bom_hourly_solar_route_template.csv` with
`--normalized-csv` instead of `--netcdf`.  Promotion still requires held-out
PV and 25 km energy error to improve; source quality alone is not sufficient.

Tagged experiments no longer overwrite `profile.yaml`. They write
`outputs/identification/runs/<tag>/profile_candidate.yaml`; pass
`--adopt-profile` only after reviewing all validation gates.

GPS-derived acceleration is aligned only as a discrete telemetry timestamp
offset; vehicle mass is never varied to absorb that offset. The lag is selected
on the earlier race days and accepted only when the held-out final day has at
least 100 usable samples and its RMSE ratio is no worse than 1.02. Both the
candidate table and the held-out result are saved in the fit summary and are
part of the promotion and full-simulation model gates.

The pipeline normalizes logs, aligns route and weather, builds grounded base
maps, fits PV and cell temperature, fits battery OCV/Rint/capacity, fits
CdA/Crr/drive losses, and performs joint segmented replay validation. Accepted
values are written to the project profile and its adopted map paths. The
machine-readable result is
<code>outputs/identification/*_generic_fit_summary.yaml</code>.

The ZP solar-power channel is calibrated before those fits with stationary
DC-bus samples. With traction power zero, the robust bounded model is
`P_batt = P_aux - solar_measurement_gain_to_pack * P_solar_raw + error`.
The independently measured 21 W auxiliary load fixes the intercept; a
free-intercept fit and per-day gains are diagnostics which must agree before
the coefficient is accepted. WiFi senders always transmit the uncorrected ZP
value as `solar_power_w`. The receiving bridge applies the active profile gain
exactly once. Sending an already corrected value through this field would
double-apply calibration and is prohibited.

`model.V_max` is a hardware constraint, not the largest loaded voltage in a
discharge log. The grounded race-use product limit is 25 series cells times
4.35 V/cell, or 108.75 V. The static audit rejects a fitted profile when its
active OCV map exceeds this limit or its YATA `V_max` differs from 108.75 V.
This prevents the lower controller from
creating artificial traction load merely to pull a high-SoC terminal voltage
below an incorrectly low bound.

Do not call a model high precision from the training residual alone. The MLE35
battery-conditioned replay, which uses observed pack power/current to isolate
battery dynamics, has clean power/voltage RMSE of 201.344 W / 0.968 V. Its
terminal SoC error is 0.682 percentage point. The route-weather and PV model
end-to-end replay has 246.088 W / 2.113 V, but its 25 km energy RMSE is
102.944 Wh and terminal SoC error is 5.769 percentage points. At 2831 km,
loaded-voltage, team-reported remaining energy, and day-6 pack-energy
integration still imply an evidence interval of 0.33224--0.52867 SoC. This
19.64 percentage-point conflict means
the high-precision gate is explicitly false until synchronized BMS coulomb
count, rested OCV/temperature, MPPT state, and measured POA irradiance are
available.

Route grade is also treated as an observation model, not as a free vehicle
coefficient. Identification smooths the source DEM elevation with candidate
Savitzky-Golay windows, differentiates elevation with respect to distance, and
tests bounded route-distance offsets. Candidate window/offset/temporary grade
scale combinations are selected on Day1-Day5 only and must not degrade the
held-out Day6 power RMSE. The adopted route CSV stores the unscaled
elevation-derived grade; `model.grade_scale` is refitted separately afterward.
The run summary records the full candidate count, train/holdout RMSE, selected
window and distance offset, so this correction cannot be hidden inside `Crr`
or `CdA`.

### 3. Add race environment

Set the route, speed limits, drive schedule, control stops, timezone, race
distance, and weather path in <code>profile.yaml</code>. Forecast rows must
cover the entire simulated UTC interval. Live weather is fetched at the chase
GNSS position and saved before correction; wind correction writes a second
versioned CSV.

### 4. Run pre-race simulation

Use <code>SolarSim.ps1 -Action simulate</code>. Confirm:

- the manifest says <code>finish_reached: true</code>;
- SoC remains within the configured floor/ceiling;
- no voltage/current limit is violated;
- drive windows and stops match the regulations;
- speed does not oscillate or remain needlessly low while SoC is clipped at
  its upper bound;
- nominal, upper-risk, and lower-risk plans are not mixed.
- <code>planner_adoption_gate_pass</code> is true. This requires finish,
  terminal SoC band, predicted mission feasibility, solver success, complete
  finite-library enumeration, and prediction/execution terminal-SoC agreement.
- <code>adoption_gate_pass</code> additionally requires the independent model
  gate when <code>simulation.require_model_validation_gate: true</code>.

The nominal plan uses the most likely weather without a growing uncertainty
reserve. Risk bands belong in separate upper/lower scenario outputs.

The detail CSV is always written at least at 1 Hz. A final row shorter than one
second is intentional when it lands exactly on an upper-plan segment, control
stop, drive-window, or finish boundary. Read
`outer_step_boundary_reason` and `detail_step_kind` rather than treating this
remainder as a synchronization fault. Power columns are explicit:
`P_vehicle_load_w` is gross vehicle demand, `P_solar_w` is PV input, and
`P_net_battery_w` is their net battery-side demand. `P_road_load` contains
aerodynamic, rolling and grade demand, while `P_inertia` is computed from
`0.5*m*(v_next^2-v_previous^2)/dt`; acceleration consumes energy and
deceleration enters the bounded regen path. The 1 Hz detail row also records
`v_exec_previous_kmh` and `acceleration_ms2`, so this balance can be recomputed
without hidden state.

For the reproducible BWSC2025 weather/power/time-step audit, run:

    python scripts\audit_bwsc2025_weather_power_timestep.py

The generated CSV, JSON, monochrome figures, TeX, and PDF are placed under the
current fitted package `outputs/reports/weather_power_timestep_audit` directory.

For a large finite-policy certificate on a Slurm Linux server, use the bundled
CPU job script from the repository root:

    sbatch --export=ALL,PYTHON_BIN=$HOME/.venvs/mpc_gpu/bin/python,CERT_WORKERS=16 scripts/run_solar_fullsim_cpu.sbatch project_packages/<vehicle>/outputs/gpu_acceptance/exact_1km/<selected_seed>/profile_exact_1hz.yaml

The job does not need a GPU. It sets each BLAS library to one thread and uses
`CERT_WORKERS` independent fork processes. Always copy back the complete
profile-specific output directory and verify `adoption_gate_pass`, candidate
count, nonfinite count, and prediction/execution SoC synchronization.

### 5. Operate live

The live WiFi cycle is:

1. A Raspberry Pi sends UTF-8 UDP JSON or key-value text to the configured
   inbound port.
2. <code>telemetry_text_bridge_node.py</code> validates timestamps/ranges,
   filters speed, battery and wind, and publishes ROS 2 topics.
3. Distance and grade nodes update route state.
4. Weather and wind nodes update the predicted environment.
5. The upper MPC replans at the configured interval; the lower MPC produces a
   1 Hz reference.
6. <code>speed_command_bridge_node.py</code> applies timeout, startup hold,
   low-pass filtering, acceleration/deceleration limits, deadband, quantization,
   and mode hold.
7. The command is published to ROS and optionally sent as UTF-8 UDP text.
8. Logger and dashboard consume the same topics and timestamps.

Vehicle sender example:

    {"type":"vehicle_state","timestamp_utc":"2027-08-28T01:23:45Z","speed_kmh":72.3,"soc":0.83,"batt_temp_c":34.2,"batt_current_a":8.5,"batt_voltage_v":97.6,"solar_power_w":410.0}

Chase sender example:

    {"type":"chase_state","timestamp_utc":"2027-08-28T01:23:45Z","lat":-22.0,"lon":133.0,"speed_kmh":71.9,"wind_speed_ms":6.5,"wind_dir_deg":121.0,"course_deg":176.0}

Microcontroller and Raspberry Pi examples are in
<code>scripts/wifi_vehicle_sender_example.py</code>,
<code>scripts/wifi_chase_sender_example.py</code>, and
<code>templates/network</code>.

## Time and synchronization contract

Every producer must send UTC timestamps. Local race time is only a schedule and
display conversion. The following contracts are enforced or tested:

- Raspberry Pi clocks must be synchronized by NTP/chrony before launch;
- WiFi packets without a valid <code>timestamp_utc</code> or
  <code>ts_unix</code> are rejected by default;
- packets older than 5 s, more than 2 s in the future, duplicated, or received
  out of source-time order are rejected before any filter or ROS topic update;
- accepted solar/chase source times are logged separately from receive time,
  and accepted GNSS messages retain the sender timestamp;
- speed, distance, and battery measurements have independent timeout limits;
- physically impossible speed/distance jumps are rejected;
- filtered measurements use configured time constants and rate limits;
- forecast timestamps use the profile timezone and are reloaded atomically;
- ISO timestamps with and without fractional seconds may be mixed in one CSV;
  all runtime and report parsers use mixed-format parsing, and generated
  <code>time_local</code> columns are tested for missing values;
- night waits are integrated in at most 600 s pieces so dawn weather/solar is
  not represented by one evening sample;
- active auxiliary load is added on the electrical side, not divided by motor
  efficiency;
- <code>P_aux=21.021 W</code> applies while driving and
  <code>P_aux_stopped=21.021 W</code> conservatively applies at daytime stops;
- <code>P_aux_night=0 W</code> applies below the YAML-configurable 20 W/m2
  irradiance threshold because the team turns the auxiliaries off at night;
- every run saves a resolved profile and versioned manifest.

The two initial SoC values in the fitted example have different purposes and
must never overwrite each other. <code>simulation.soc0=0.98</code> is the
operational start state for a no-trouble race simulation. By contrast,
<code>identification.fitted_replay_soc0=0.966219</code> is a latent state estimated
only to reproduce the first sample of the historical segmented log. Earlier
output that appeared to start near 81--86% was caused by copying the latter
into the former; the identification writer and its regression test now keep
them separate.

## Current vehicle-model generation and acceptance

The current research package is
<code>project_packages/bwsc2025_fitted_mle19_energywindow_inertia</code>.
Its canonical profile is not an operationally certified model: use
<code>profile_operational_fine.yaml</code> when the model-validation gate must
be enforced. Tagged identification runs are immutable candidates and are not
copied into <code>profile.yaml</code> unless every promotion gate passes.

| Parameter | MLE35 research-candidate value (not canonical live) |
|---|---:|
| mass | 235.0 kg |
| CdA | 0.111167 m2 |
| Crr | 0.006262 |
| driving auxiliary power | 21.021 W |
| daytime stopped auxiliary power | 21.021 W |
| night auxiliary power | 0 W |
| battery new-product reference | 3011.000 Wh / 33.000 Ah |
| raw ZP solar-to-pack gain | 0.922613 |
| race-use pack voltage ceiling | 108.75 V |
| PV area | 6.0 m2 |
| max discharge current | 40.0 A |

The newest immutable candidate is
<code>outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1</code>
inside that package. It fixes mass at 235 kg, calibrates the raw ZP solar
channel from 11,005 stationary samples, and estimates
<code>CdA=0.111167</code>, <code>Crr=0.006262</code>,
<code>P_aux=21.021 W</code>, <code>E_nom=3011 Wh</code>,
<code>solar_measurement_gain_to_pack=0.922613</code>, and
<code>drive_eff_scale=1.034296</code>. Its strict promotion gate is false:
battery-conditioned power/voltage RMSE is 201.344 W / 0.968 V, end-to-end
power/voltage RMSE is 246.088 W / 2.113 V, 25 km end-to-end energy RMSE is
102.944 Wh, and the independent 2831 km SoC evidence spans 19.643 percentage
points. Therefore the MLE35 operational profile is explicitly
named <code>profile_operational_gpu_research.yaml</code> and is not copied into
the canonical live profile.

For comparison, the currently released
<code>profile_operational_fine.yaml</code> remains at
<code>CdA=0.109802</code>, <code>Crr=0.006560</code>,
<code>P_aux=P_aux_stopped=20.891 W</code>, <code>P_aux_night=0 W</code>,
<code>E_nom=2899.987 Wh</code>, and <code>Q_nom=31.783316 Ah</code>.
This older set is not claimed to be more physically accurate; it is retained
only because MLE35 has not passed the independent model-validation gate.

The current active maps and their provenance are summarized in
<code>outputs/reports/current_maps_and_coefficients.md</code> and the generic
fit summary. They include drive eco/power maps, regen eco/power maps,
temperature/SoC Rint, OCV-SoC, panel efficiency, and MPPT efficiency.

Every new identification run also writes `reports/residual_audit/` with
`residual_regime_metrics.csv`, `soc_divergence_trace.csv`,
`residual_audit.json`, and `residual_soc_audit.png`. These distinguish the
all-operating-point RMSE from the moving-only RMSE and record where the vehicle
and end-to-end replays first differ from the observed-pack conditional replay
by 2, 5, and 10 SoC percentage points. The same audit can be rerun explicitly:

    python scripts/audit_identification_residuals.py --vehicle-replay <run>/replay_validation.csv --battery-replay <run>/replay_validation_battery_conditioned.csv --end-to-end-replay <run>/replay_validation_end_to_end.csv --output-dir <report_dir>/residual_audit

The old four-knot policy `[70, 70, 70, 67] km/h` is retained only as a legacy
comparison. Four speed knots never meant `Delta s = 3026.9/4 km` for state
integration, but the policy itself was still too coarse for final acceptance.
The current route source is a 100 m DEM profile. Upper-planner grade energy is
now computed from an exact piecewise-linear segment average instead of a
single slope sample at each coarse segment start. The 100 m source mesh remains
the terminal h-refinement authority because averaging alone can hide drive vs
regen efficiency changes within a segment.

Terminal SoC is also not forced to one unsupported value. The loaded-voltage,
team remaining-energy, and Day6 current-integration channels disagree. A local
Thevenin pulse estimate is conditional on the pseudo-OCV map and is marked
`conditional_sensitivity`; it can never be promoted as operational truth.
High-precision acceptance requires evidence-spread, local-anchor quality,
cross-channel consistency, conditional full-replay SoC error, and terminal
voltage error to pass together. The current evidence does not pass that gate.

The operational profile is <code>profile_operational_fine.yaml</code>. GPU
search uses three fidelities: 5 km integration/25 km control, 1 km/5 km, and
0.1 km/5 km, followed by independent 1 km-integration refinements at 2 km and
1 km control spacing. The control dimensions, including the explicit finish
point, are 123 (25 km), 607 (5 km), 1515 (2 km), and 3028 (1 km) over the full
3026.9 km course. The 0.1 km terminal integration has approximately 30,269
physical transitions before exact stop boundaries are inserted. Integration spacing and control
spacing are deliberately different: the former resolves route/weather physics,
while the latter limits policy dimension and enforces an operationally sensible
speed smoothness scale. `scripts/run_upper_mesh_convergence.py`
compares 1, 0.5, 0.2, and 0.1 km integration meshes with one locked policy, and
compares the independently optimized 5, 2, and 1 km control policies with
independent 1 Hz replay. A control-spacing comparison is invalid when the same
policy is merely interpolated onto a different grid. The final pair must
change elapsed time by at most 60 s, terminal SoC by at most 0.002, speed RMS
by at most 0.5 km/h, and prediction/execution SoC by at most 0.002. This follows
the mesh-refinement principle in
[Betts and Huffman (1998)](https://onlinelibrary.wiley.com/doi/10.1002/%28SICI%291099-1514%28199801/02%2919%3A1%3C1%3A%3AAID-OCA616%3E3.0.CO%3B2-Q)

The no-trouble policy experiment still includes every mandatory control stop,
but it does not reuse the team's actual arrival times or trouble dwell. Its
authoritative input is
<code>data/race/bwsc2025_official_control_stops.yaml</code>: nine control
stops, exactly 1800 s each, their published opening/closing times, and the
published Adelaide finish-line close at 2025-08-29 17:30 local
(2025-08-29T08:00:00Z). Early arrival waits until opening; arrival after a
control-stop close or the absolute finish deadline makes both the CUDA
surrogate and exact 1 Hz replay infeasible. These times are transcribed from
the [BWSC 2025 Official Program v4](https://assets.worldsolarchallenge.org/app/uploads/2025/08/20102713/BWSC-2025-Official-Program-v4.pdf),
whose finish-table footnote identifies 17:30 as the latest Cruiser arrival.
and explicit-simulation error checking in
[Haman and Rao (2024)](https://arxiv.org/abs/2410.07488).

`scripts/gpu_upper_policy_search.py` evaluates thousands of policies at once
on CUDA and writes a distance-indexed policy. This is a multi-fidelity
proposer only; the complete map-based model and 1 Hz replay remain the
acceptance authority.

Create the fine profile from the newest fitted canonical profile instead of
reusing an older generation's vehicle coefficients:

    python scripts\create_operational_fine_profile.py --profile project_packages\<vehicle>\profile.yaml

On the Slurm GPU server, submit four independently seeded three-fidelity CEM
runs. Each seed uses 1800 generations at 5 km/25 km, 200 generations at
1 km/5 km, then 60 local generations at 0.1 km/5 km. The first two stages use
4096 candidates per generation and the 100 m stage uses 256. The default
campaign then performs 20 warm-started generations at 2 km control spacing and
20 at 1 km, each with 1024 candidates. It therefore evaluates 8400 generations
and 32,993,280 candidate
policies. Each run has its own checkpoint and TensorBoard directory. The short
100 m stage is intentional: the four-replicate RTX A6000 smoke campaign took
20 minutes end to end, with most of that time in the one-generation 100 m
stage.  Its 30,269 state transitions are causal and cannot be batched over
distance without changing the model.

    bash scripts/submit_solar_gpu_multifidelity_campaign.sh project_packages/<vehicle>/profile_operational_fine.yaml project_packages/<vehicle>/outputs/gpu_multifidelity

The independent-job submitter also queues a small finalizer after all four
`control_1km` jobs. Read `finalize_job_id` from
`gpu_multifidelity/campaign_submission.yaml`; that job verifies all four final
policies before writing `CAMPAIGN_COMPLETE`. Submission also records the input
profile SHA-256 and passes it to every queued stage. A stage fails explicitly
if the YAML changes while the campaign is running, so one campaign cannot mix
different vehicle models or weather inputs across generations.

For one RTX A6000 allocation, the compatibility runner serializes the four
independent seeds and retains each checkpoint separately. To permit scheduler
parallelism, submit one job per seed with `REPLICATE_INDEX=0..3`; actual
concurrency then depends on the account's GPU quota. The runner never launches
four competing CUDA processes inside one GPU allocation:

    sbatch --export=ALL,SOLAR_GPU_ROOT=$PWD,PYTHON_BIN=$HOME/.venvs/mpc_gpu/bin/python scripts/run_solar_gpu_concurrent_campaign.sbatch project_packages/<vehicle>/profile_operational_fine.yaml project_packages/<vehicle>/outputs/gpu_multifidelity

The exact-replay and mesh gates can be chained after the campaign. This job
runs the 5, 2, and 1 km exact-policy sets concurrently and also runs the four
seeds inside each set concurrently, using at most 12 of the requested 16 CPU
cores. Each result remains an independent fixed-policy 1 Hz replay; the
per-seed rankings are merged only after every replay has written its own
manifest and detail CSV:

    sbatch --dependency=afterok:<finalize_job_id> --export=ALL,SOLAR_GPU_ROOT=$PWD,PYTHON_BIN=$HOME/.venvs/mpc_gpu/bin/python scripts/run_solar_gpu_acceptance_pipeline.sbatch project_packages/<vehicle>/profile_operational_fine.yaml project_packages/<vehicle>/outputs/gpu_multifidelity project_packages/<vehicle>/outputs/gpu_acceptance

Before a long run, override the generation/population variables with tiny
values and require one final policy below each of the four `seed_*` directories,
one `CAMPAIGN_COMPLETE`, 20 stage summaries, and no `CAMPAIGN_FAILED`.
`PIPELINE_COMPLETE` is emitted only by the single-allocation concurrent runner;
the independent-job runner is certified by its dependency finalizer.

After all 1 km control-refinement jobs finish, rank the CUDA surrogate results,
then replay every final policy with 100 m prediction integration and the 1 Hz
execution model. Only exact-replay-feasible candidates are eligible. The 5 km,
2 km, and 1 km stages must also be validated separately before policy-resolution
convergence can be claimed.

When exact replay and mesh convergence pass, the pipeline first writes
`POLICY_ACCEPTANCE_COMPLETE` and `profile_exact_selected_research.yaml`.  These
certify the numerical policy only and remain usable for an explicitly
unvalidated research full replay. It then evaluates the independent vehicle-model
gate. Only when that gate also passes does it write `ACCEPTANCE_COMPLETE`,
`profile_exact_selected.yaml`, and `profile_live_mpc_learned.yaml`. The former is
a frozen experiment; the latter points `paths.initial_upper_policy_csv` at the
accepted 1 km policy and leaves the upper MPC unlocked.  At each scheduled live
replan, the previous MPC solution is interpolated onto the shifted control mesh;
the learned policy is used only when no previous online solution is available.

    python scripts/rank_gpu_upper_policy_candidates.py --campaign-dir project_packages/<vehicle>/outputs/gpu_multifidelity
    python scripts/validate_gpu_upper_policy_candidates.py --profile project_packages/<vehicle>/profile_operational_fine.yaml --campaign-dir project_packages/<vehicle>/outputs/gpu_multifidelity --stage ultra_100m --integration-ds-km 0.1 --control-ds-km 5 --output-dir project_packages/<vehicle>/outputs/gpu_exact_validation_5km
    python scripts/validate_gpu_upper_policy_candidates.py --profile project_packages/<vehicle>/profile_operational_fine.yaml --campaign-dir project_packages/<vehicle>/outputs/gpu_multifidelity --stage control_2km --integration-ds-km 0.1 --control-ds-km 2 --output-dir project_packages/<vehicle>/outputs/gpu_exact_validation_2km
    python scripts/validate_gpu_upper_policy_candidates.py --profile project_packages/<vehicle>/profile_operational_fine.yaml --campaign-dir project_packages/<vehicle>/outputs/gpu_multifidelity --stage control_1km --integration-ds-km 0.1 --control-ds-km 1 --output-dir project_packages/<vehicle>/outputs/gpu_exact_validation_1km
    python scripts/run_upper_mesh_convergence.py --profile project_packages/<vehicle>/profile_operational_fine.yaml --policy project_packages/<vehicle>/outputs/gpu_exact_validation_1km/selected_exact_policy.csv --control-policy 5=project_packages/<vehicle>/outputs/gpu_exact_validation_5km/selected_exact_policy.csv --control-policy 2=project_packages/<vehicle>/outputs/gpu_exact_validation_2km/selected_exact_policy.csv --output-dir project_packages/<vehicle>/outputs/mesh_convergence

`--policy` is always assigned to the finest requested control mesh (normally
1 km); it is never relabelled as a supplied 2 km policy. Generate the final
Japanese TeX/PDF only after copying both campaign and acceptance directories:

    python scripts/generate_gpu_acceptance_report.py --profile project_packages/<vehicle>/profile_operational_fine.yaml --campaign-dir project_packages/<vehicle>/outputs/gpu_multifidelity --acceptance-dir project_packages/<vehicle>/outputs/gpu_acceptance --fit-summary project_packages/<vehicle>/outputs/identification/runs/<fit_tag>/<vehicle>_generic_fit_summary.yaml --promotion-gate project_packages/<vehicle>/outputs/reports/identification_comparison_<fit_tag>/<fit_tag>_promotion_gate.json --output-dir project_packages/<vehicle>/outputs/reports/gpu_acceptance_<run_tag>

The GPU result is a multi-start numerical search, not a proof of continuous
global optimality. Exact 1 Hz feasibility and mesh convergence are separate
gates, and independent vehicle-model validation remains mandatory before live
adoption. `ACCEPTANCE_FAILED` can therefore coexist with
`POLICY_ACCEPTANCE_COMPLETE`; that means the policy calculation passed but the
vehicle evidence is not yet accurate enough for operational promotion.

The CUDA evaluator includes drive-window waits, control stops, bilinear
drive/regen, panel/MPPT, Rint and OCV maps, battery IV, and the signed
kinetic-energy term. It is still not accepted until the fixed-policy exact
replay and mesh-convergence gate pass. After downloading the fine-stage
`latest_policy.csv`, set
`paths.initial_upper_policy_csv` and `mpc.upper_lock_initial_policy=true` in a
validation copy, run `scripts/solar_sim.py`, then run
`scripts/run_upper_mesh_convergence.py`. CUDA speed alone is never treated as
a proof or as model validation.

## Grafana dashboard

`dashboard_node.py` exposes Prometheus text at `/metrics` as well as the JSON
API. The provisioned stack under <code>grafana</code> uses Grafana's built-in
Prometheus source and no third-party plugin. Start ROS, then run:

    powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action grafana

Open <code>http://localhost:3000/d/solarcar-ems/yata-solarcar-ems</code>. The
single screen shows measured/upper/lower speed, SoC, distance, health,
telemetry age, power flow, voltage/current, irradiance/wind/slope, and thermal
state. Stop it with <code>SolarSim.ps1 -Action grafana-stop</code>. Docker is an
explicit prerequisite. Configuration follows Grafana's
[Docker Compose](https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/)
and [provisioning](https://grafana.com/docs/grafana/latest/administration/provisioning/)
guidance.

## Source structure

| Path | Responsibility |
|---|---|
| <code>mpc_solarcar/model.py</code> | vehicle, PV, efficiency-map, battery IV, SoC and thermal model |
| <code>mpc_solarcar/mpc_node.py</code> | upper distance MPC and lower 1 Hz MPC |
| <code>mpc_solarcar/upper_policy.py</code> | validate and interpolate an accepted offline speed policy for the upper-MPC warm start |
| <code>mpc_solarcar/solar_state_node.py</code> | simulated state propagation using the drive schedule |
| <code>mpc_solarcar/telemetry_text_bridge_node.py</code> | WiFi text parsing, validation, filtering, ROS topic publication |
| <code>mpc_solarcar/speed_command_bridge_node.py</code> | safe command filtering, rate limiting and UDP output |
| <code>mpc_solarcar/weather_fetch_node.py</code> | live forecast acquisition |
| <code>mpc_solarcar/wind_correction_node.py</code> | measured wind correction and uncertainty |
| <code>mpc_solarcar/solar_autocal_node.py</code> | bounded online solar/drive/aux calibration |
| <code>mpc_solarcar/distance_node.py</code> | measured-speed distance integration |
| <code>mpc_solarcar/grade_node.py</code> | GNSS/altitude grade estimation |
| <code>mpc_solarcar/solar_logger_node.py</code> | synchronized solar telemetry, planner, calibration, WiFi, and safety CSV |
| <code>mpc_solarcar/solar_preflight_node.py</code> | solar telemetry/planner freshness and system health |
| <code>mpc_solarcar/dashboard_node.py</code> | browser API and Prometheus metrics endpoint |
| <code>scripts/solar_sim.py</code> | versioned offline full-race simulation |
| <code>scripts/gpu_upper_policy_search.py</code> | CUDA multi-fidelity fine-policy proposer |
| <code>scripts/run_upper_mesh_convergence.py</code> | fixed-policy h-refinement acceptance gate |
| <code>grafana</code> | provisioned Prometheus/Grafana one-screen dashboard |
| <code>scripts/run_vehicle_identification.py</code> | generic segmented MLE and report |
| <code>scripts/tune_upper_planner_weights.py</code> | reference-free outer CEM tuning and TensorBoard |
| <code>scripts/dashboard_demo_server.py</code> | deterministic training telemetry for the real dashboard UI |
| <code>scripts/create_solarcar_only_package.py</code> | solar-only release builder |
| <code>scripts/create_solarcar_blank_package.py</code> | functionally equivalent empty project builder |

The exhaustive generated audit is in
<code>docs/package_inventory/package_source_inventory.csv</code>. It records
all source/config assets, AST symbols, ROS topic literals, line counts,
bytes, and SHA-256. The generated workspace snapshot records every file, including
historical evidence and generated results.

## Manuals

- <code>docs/development_history/solar_package_development_history.pdf</code>:
  beginner-oriented chronological history of the substantive package changes;
  the adjacent Markdown source is suitable for GitHub release notes.
- <code>docs/solar_all_in_one_manual/solar_all_in_one_manual.pdf</code>:
  integrated operation, fitting, communication, and model manual.
- <code>docs/flow_workbook/solar_package_flow_workbook.pdf</code>:
  mode-by-mode package flow.
- <code>docs/complete_flow_workbook</code>:
  separate question book, answer sheet, and worked solutions covering one
  complete live cycle, map interpolation, vehicle energy, battery IV, upper
  CEM/L-BFGS-B, finite-grid certification, lower MPC, command filtering, MLE,
  and saved outputs.
- <code>docs/mle_hand_calculation_workbook</code>:
  separate question book, answer sheet, and worked solutions for Gaussian and
  Huber losses, grounded-map correction, PV/motion/battery fitting, joint MLE,
  terminal anchors, multi-start selection, and profile deployment.
- <code>docs/deployment_operation_manual/solar_mpc_deployment_operation_manual.pdf</code>:
  Japanese step-by-step installation and all-mode operating manual from GitHub
  ZIP download through Windows/Ubuntu setup, Raspberry Pi protocol, race-day
  release gate, recovery, and output traceability.
- <code>docs/package_inventory</code>:
  generated source and workspace audit records.

## Distribution packages

Run:

    python scripts\create_solarcar_only_package.py --force
    python scripts\create_solarcar_blank_package.py --force

The solar-only distribution keeps the current MLE35 fitted research example and all operating
functions while removing PASSO, magnetic-coupler, build/install/log, and old
fitted generations. The blank distribution keeps the same code and manuals but
contains only empty vehicle/race templates. Both builders emit a manifest and
must be rerun after code, profile, map, or report changes.

## Release gate

Before BWSC operation, run unit tests, build under the target ROS 2
distribution, start each mode, export a real rqt graph while nodes are alive,
perform UDP loopback and stale-packet tests, run a full-course simulation, and
complete a shadow-mode road test. A successful offline CSV alone is not an
operational safety guarantee.
