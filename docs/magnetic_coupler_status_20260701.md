# Magnetic Coupler Status 2026-07-01

## Objective Criteria

- `contact_events_total == 0`
- `latched_total == 0`
- `worst_min_clearance_mm >= 1.0`
- `mean_cruise_translation_rms_mm <= 5.0`
- `mean_cruise_yaw_rms_deg <= 1.8`
- `mean_turn_signal_ratio >= 0.35`
- `mean_sensor_peak_n >= 0.5`
- `mean_orthogonal_ratio <= 0.10`
- `mean_forward_torque_ratio <= 0.055`
- `negative_yaw_restore_count == 0`
- `negative_towed_yaw_restore_count == 0`
- `nominal_tow_offset_proxy_mm <= 8.0`
- `reduced_tow_offset_proxy_mm <= 20.0`
- `stiffness_modulation_ratio >= 1.20`
- `package_violation_mm == 0.0`

`dynamic_pass`:
- first 7 runtime criteria all satisfied

`strict_pass`:
- all 15 criteria satisfied

## Completed Numerical Results

### Safety-dominant 4 kg candidate

Source:
- `outputs/magnetic_coupler_hifi_daiso13_mass_frontier_20260701/mass_frontier_summary.json`

Values:
- shape = `arrow_hl0.637_hw0.761_sw0.251_nk0.521_rd0.423`
- gap = `23.300 mm`
- cost = `2640 JPY`
- contact events = `0`
- latched = `0`
- worst clearance = `6.005 mm`
- cruise translation RMS = `12.033 mm`
- cruise yaw RMS = `1.438 deg`
- cue peak yaw = `3.052 deg`
- sensor peak = `2.648 N`
- orthogonal ratio = `0.1712`
- forward torque ratio = `0.0944`
- negative yaw restore count = `41`
- negative towed-yaw restore count = `81`
- nominal tow-offset proxy = `3.402 mm`
- reduced tow-offset proxy = `41.499 mm`

Pass/fail:
- passes `no_contact`, `no_latch`, `clearance`, `cruise_yaw`, `cue`, `sensor`, `nominal_tow`
- fails `cruise_translation`, `orthogonal_ratio`, `forward_torque`, `yaw_restore`, `towed_yaw_restore`, `reduced_tow_offset`

### Tracking-dominant 4 kg candidate

Source:
- `outputs/magnetic_coupler_hifi_daiso13_lowmass_scan_20260701/lowmass_scan.csv`

Values:
- shape = `arrow_hl0.416_hw0.865_sw0.190_nk0.789_rd0.963`
- gap = `18.000 mm`
- cost = `10890 JPY`
- contact events = `3`
- latched = `3`
- worst clearance = `0.000 mm`
- cruise translation RMS = `3.424 mm`
- cruise yaw RMS = `0.960 deg`
- cue peak yaw = `3.442 deg`
- sensor peak = `3.025 N`
- orthogonal ratio = `0.7378`
- forward torque ratio = `0.4499`
- negative yaw restore count = `51`
- negative towed-yaw restore count = `109`
- nominal tow-offset proxy = `0.233 mm`
- reduced tow-offset proxy = `1.3734e9 mm`

Pass/fail:
- passes `cruise_translation`, `cruise_yaw`, `cue`, `sensor`, `nominal_tow`
- fails `contact`, `latch`, `clearance`, `orthogonal_ratio`, `forward_torque`, `yaw_restore`, `towed_yaw_restore`, `reduced_tow_offset`

### Balanced no-contact CMA-ES candidate

Source:
- `outputs/magnetic_coupler_hifi_daiso13_research_cmaes_20260701/best_design_hifi.json`
- `outputs/magnetic_coupler_hifi_daiso13_research_cmaes_20260701/dynamic_validation.csv`

Values:
- shape = `flex_ar1.270_n4.90_poly7w0.166_ph0.000_sig730f1fb7`
- gap = `24.050 mm`
- cost = `2420 JPY`
- contact events = `0`
- latched = `0`
- worst clearance = `8.741 mm`
- mean cruise translation RMS = `11.950 mm`
- mean cruise yaw RMS = `1.171 deg`
- mean turn signal ratio = `0.1425`
- mean sensor peak = `0.960 N`
- mean orthogonal ratio = `0.0787`
- mean forward torque ratio = `0.2314`
- negative yaw restore count = `28`
- negative towed-yaw restore count = `64`

Pass/fail:
- passes `no_contact`, `no_latch`, `clearance`, `cruise_yaw`, `sensor`, `orthogonal_ratio`
- fails `cruise_translation`, `turn_signal`, `forward_torque`, `yaw_restore`, `towed_yaw_restore`

## Bottom Line

- `strict_pass = 0`
- `dynamic_pass = 0`

Within the completed DAISO 13 mm scans summarized above, no candidate satisfies the full objective set.

The observed trade-off is:
- making the system contact-safe tends to produce too much straight-line drift and too little turning signal
- making the system responsive enough to human turning cues tends to reintroduce contact or severe static restoring defects
