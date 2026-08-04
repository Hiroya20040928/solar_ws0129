#!/usr/bin/env bash
# Submit the multi-fidelity CUDA upper-policy campaign as dependent Slurm jobs.
# Usage: scripts/submit_solar_gpu_multifidelity_campaign.sh PROFILE OUTPUT_ROOT

set -euo pipefail

PROFILE=${1:?"usage: submit_solar_gpu_multifidelity_campaign.sh PROFILE OUTPUT_ROOT"}
OUTPUT_ROOT=${2:?"usage: submit_solar_gpu_multifidelity_campaign.sh PROFILE OUTPUT_ROOT"}
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
SOLAR_GPU_ROOT=${SOLAR_GPU_ROOT:-$(cd -- "$SCRIPT_DIR/.." && pwd)}
PYTHON_BIN=${PYTHON_BIN:-python3}
export SOLAR_GPU_ROOT PYTHON_BIN
SBATCH_SCRIPT="$SCRIPT_DIR/run_solar_upper_gpu_search.sbatch"
FINALIZE_SCRIPT="$SCRIPT_DIR/finalize_solar_gpu_campaign.sbatch"

test -f "$PROFILE"
test -f "$SBATCH_SCRIPT"
test -f "$FINALIZE_SCRIPT"
mkdir -p "$OUTPUT_ROOT"
rm -f "$OUTPUT_ROOT/CAMPAIGN_COMPLETE" "$OUTPUT_ROOT/CAMPAIGN_FAILED"
"$PYTHON_BIN" "$SCRIPT_DIR/check_policy_weather_input.py" \
  --profile "$PROFILE" \
  --output "$OUTPUT_ROOT/policy_weather_input_gate.json"
PROFILE_SHA256=$(sha256sum "$PROFILE" | awk '{print $1}')
mapfile -t CAMPAIGN_TIMING_METADATA < <(
  "$PYTHON_BIN" - "$PROFILE" <<'PY'
import json
import sys
from pathlib import Path

import yaml

profile_path = Path(sys.argv[1]).resolve()
profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}
stop_rel = str((profile.get("paths") or {}).get("stop_yaml") or "")
stop_path = (profile_path.parent / stop_rel).resolve() if stop_rel else None
stop_doc = {}
if stop_path is not None and stop_path.is_file():
    stop_doc = yaml.safe_load(stop_path.read_text(encoding="utf-8")) or {}

print(json.dumps(str(stop_path) if stop_path is not None else ""))
print(json.dumps(str(stop_doc.get("source") or "")))
print(json.dumps(str((profile.get("simulation") or {}).get("race_deadline_utc") or "")))
PY
)
OFFICIAL_CONTROL_STOP_PATH=${CAMPAIGN_TIMING_METADATA[0]:-""}
OFFICIAL_CONTROL_STOP_SOURCE=${CAMPAIGN_TIMING_METADATA[1]:-""}
RACE_DEADLINE_UTC=${CAMPAIGN_TIMING_METADATA[2]:-""}

COARSE_GENERATIONS=${COARSE_GENERATIONS:-1800}
COARSE_CHUNK_GENERATIONS=${COARSE_CHUNK_GENERATIONS:-600}
FINE_GENERATIONS=${FINE_GENERATIONS:-200}
ULTRA_GENERATIONS=${ULTRA_GENERATIONS:-60}
POPULATION=${POPULATION:-4096}
ELITE=${ELITE:-128}
# At 100 m integration the route has about 30k segments.  A 256-candidate
# generation already saturates the A6000 and took about 7.3 minutes in the
# measured MLE35 campaign; 16,384 candidates cannot finish inside 24 hours.
ULTRA_POPULATION=${ULTRA_POPULATION:-256}
ULTRA_ELITE=${ULTRA_ELITE:-32}
CONTROL_REFINE_GENERATIONS=${CONTROL_REFINE_GENERATIONS:-20}
CONTROL_REFINE_POPULATION=${CONTROL_REFINE_POPULATION:-1024}
CONTROL_REFINE_ELITE=${CONTROL_REFINE_ELITE:-64}
REPLICATES=${REPLICATES:-4}
BASE_SEED=${BASE_SEED:-20260715}

COARSE_JOBS=()
COARSE_FINAL_JOBS=()
FINE_JOBS=()
ULTRA_JOBS=()
CONTROL_2KM_JOBS=()
CONTROL_1KM_JOBS=()
for ((replicate=0; replicate<REPLICATES; replicate++)); do
  label=$(printf 'seed_%02d' "$replicate")
  coarse_dir="$OUTPUT_ROOT/$label/coarse_5km"
  fine_dir="$OUTPUT_ROOT/$label/fine_1km"
  ultra_dir="$OUTPUT_ROOT/$label/ultra_100m"
  control_2km_dir="$OUTPUT_ROOT/$label/control_2km"
  control_1km_dir="$OUTPUT_ROOT/$label/control_1km"
  coarse_seed=$((BASE_SEED + 2 * replicate))
  fine_seed=$((BASE_SEED + 2 * replicate + 1))
  ultra_seed=$((BASE_SEED + 1000 + replicate))

  coarse_job=""
  coarse_target=0
  while (( coarse_target < COARSE_GENERATIONS )); do
    coarse_target=$((coarse_target + COARSE_CHUNK_GENERATIONS))
    if (( coarse_target > COARSE_GENERATIONS )); then
      coarse_target=$COARSE_GENERATIONS
    fi
    dependency_args=()
    if [[ -n "$coarse_job" ]]; then
      dependency_args+=(--dependency="afterok:$coarse_job")
    fi
    coarse_job=$(
      sbatch --parsable \
        "${dependency_args[@]}" \
      --export="ALL,PROFILE_SHA256=$PROFILE_SHA256,GENERATIONS=$coarse_target,POPULATION=$POPULATION,ELITE=$ELITE,INTEGRATION_DS_KM=5.0,CONTROL_DS_KM=25.0,SEED=$coarse_seed" \
        "$SBATCH_SCRIPT" "$PROFILE" "$coarse_dir"
    )
    COARSE_JOBS+=("$coarse_job")
  done
  COARSE_FINAL_JOBS+=("$coarse_job")
  initial_policy="$coarse_dir/latest_policy.csv"
  fine_job=$(
    sbatch --parsable \
      --dependency="afterok:$coarse_job" \
      --export="ALL,PROFILE_SHA256=$PROFILE_SHA256,GENERATIONS=$FINE_GENERATIONS,POPULATION=$POPULATION,ELITE=$ELITE,INTEGRATION_DS_KM=1.0,CONTROL_DS_KM=5.0,INITIAL_POLICY=$initial_policy,INITIAL_STD_KMH=4.0,SEED=$fine_seed" \
      "$SBATCH_SCRIPT" "$PROFILE" "$fine_dir"
  )
  FINE_JOBS+=("$fine_job")
  ultra_initial_policy="$fine_dir/latest_policy.csv"
  ultra_job=$(
    sbatch --parsable \
      --dependency="afterok:$fine_job" \
      --export="ALL,PROFILE_SHA256=$PROFILE_SHA256,GENERATIONS=$ULTRA_GENERATIONS,POPULATION=$ULTRA_POPULATION,ELITE=$ULTRA_ELITE,INTEGRATION_DS_KM=0.1,CONTROL_DS_KM=5.0,INITIAL_POLICY=$ultra_initial_policy,INITIAL_STD_KMH=1.0,SEED=$ultra_seed,REQUIRE_SURROGATE_FEASIBILITY=1" \
      "$SBATCH_SCRIPT" "$PROFILE" "$ultra_dir"
  )
  ULTRA_JOBS+=("$ultra_job")
  control_2km_job=$(
    sbatch --parsable \
      --dependency="afterok:$ultra_job" \
      --export="ALL,PROFILE_SHA256=$PROFILE_SHA256,GENERATIONS=$CONTROL_REFINE_GENERATIONS,POPULATION=$CONTROL_REFINE_POPULATION,ELITE=$CONTROL_REFINE_ELITE,INTEGRATION_DS_KM=1.0,CONTROL_DS_KM=2.0,INITIAL_POLICY=$ultra_dir/latest_policy.csv,INITIAL_STD_KMH=0.8,SEED=$((ultra_seed + 1000))" \
      "$SBATCH_SCRIPT" "$PROFILE" "$control_2km_dir"
  )
  CONTROL_2KM_JOBS+=("$control_2km_job")
  control_1km_job=$(
    sbatch --parsable \
      --dependency="afterok:$control_2km_job" \
      --export="ALL,PROFILE_SHA256=$PROFILE_SHA256,GENERATIONS=$CONTROL_REFINE_GENERATIONS,POPULATION=$CONTROL_REFINE_POPULATION,ELITE=$CONTROL_REFINE_ELITE,INTEGRATION_DS_KM=1.0,CONTROL_DS_KM=1.0,INITIAL_POLICY=$control_2km_dir/latest_policy.csv,INITIAL_STD_KMH=0.5,SEED=$((ultra_seed + 2000))" \
      "$SBATCH_SCRIPT" "$PROFILE" "$control_1km_dir"
  )
  CONTROL_1KM_JOBS+=("$control_1km_job")
done

coarse_job_csv=$(IFS=,; printf '%s' "${COARSE_JOBS[*]}")
coarse_final_job_csv=$(IFS=,; printf '%s' "${COARSE_FINAL_JOBS[*]}")
fine_job_csv=$(IFS=,; printf '%s' "${FINE_JOBS[*]}")
ultra_job_csv=$(IFS=,; printf '%s' "${ULTRA_JOBS[*]}")
control_2km_job_csv=$(IFS=,; printf '%s' "${CONTROL_2KM_JOBS[*]}")
control_1km_job_csv=$(IFS=,; printf '%s' "${CONTROL_1KM_JOBS[*]}")
control_1km_dependency=$(IFS=:; printf '%s' "${CONTROL_1KM_JOBS[*]}")
finalize_job=$(
  sbatch --parsable \
    --dependency="afterok:$control_1km_dependency" \
    --export="ALL,PROFILE_SHA256=$PROFILE_SHA256" \
    "$FINALIZE_SCRIPT" "$OUTPUT_ROOT" "$REPLICATES" "$PROFILE"
)

cat > "$OUTPUT_ROOT/campaign_submission.yaml" <<EOF
profile: $PROFILE
profile_sha256: $PROFILE_SHA256
output_root: $OUTPUT_ROOT
replicates: $REPLICATES
coarse_job_ids: [$coarse_job_csv]
coarse_final_job_ids: [$coarse_final_job_csv]
fine_job_ids: [$fine_job_csv]
ultra_job_ids: [$ultra_job_csv]
control_2km_job_ids: [$control_2km_job_csv]
control_1km_job_ids: [$control_1km_job_csv]
finalize_job_id: $finalize_job
coarse_generations: $COARSE_GENERATIONS
coarse_chunk_generations: $COARSE_CHUNK_GENERATIONS
fine_generations: $FINE_GENERATIONS
ultra_generations: $ULTRA_GENERATIONS
population: $POPULATION
ultra_population: $ULTRA_POPULATION
control_refine_generations: $CONTROL_REFINE_GENERATIONS
control_refine_population: $CONTROL_REFINE_POPULATION
total_generations: $(( REPLICATES * (COARSE_GENERATIONS + FINE_GENERATIONS + ULTRA_GENERATIONS + 2 * CONTROL_REFINE_GENERATIONS) ))
total_candidates: $(( REPLICATES * ((COARSE_GENERATIONS + FINE_GENERATIONS) * POPULATION + ULTRA_GENERATIONS * ULTRA_POPULATION + 2 * CONTROL_REFINE_GENERATIONS * CONTROL_REFINE_POPULATION) ))
coarse_integration_ds_km: 5.0
coarse_control_ds_km: 25.0
fine_integration_ds_km: 1.0
fine_control_ds_km: 5.0
ultra_integration_ds_km: 0.1
ultra_control_ds_km: 5.0
control_refine_integration_ds_km: 1.0
control_refine_meshes_km: [2.0, 1.0]
mesh_basis: 0.1 km terminal integration matches the native 100 m DEM route profile spacing
independent_seed_strategy: four independent coarse CEM runs, each followed by 1 km and 100 m integration refinements; 2 km and 1 km control-spacing policies are independently optimized convergence checks
acceptance_authority: scripts/solar_sim.py fixed-policy 1 Hz replay plus scripts/run_upper_mesh_convergence.py
official_control_stop_path: $OFFICIAL_CONTROL_STOP_PATH
official_control_stop_source: $OFFICIAL_CONTROL_STOP_SOURCE
race_deadline_utc: $RACE_DEADLINE_UTC
EOF

printf 'coarse_jobs=%s fine_jobs=%s ultra_jobs=%s control_2km_jobs=%s control_1km_jobs=%s\n' "$coarse_job_csv" "$fine_job_csv" "$ultra_job_csv" "$control_2km_job_csv" "$control_1km_job_csv"
printf 'finalize_job=%s\n' "$finalize_job"
