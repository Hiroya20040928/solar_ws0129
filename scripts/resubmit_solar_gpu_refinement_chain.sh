#!/usr/bin/env bash
# Reconnect ultra/control refinement and acceptance without rerunning coarse/fine.
# Usage: resubmit_solar_gpu_refinement_chain.sh PROFILE OUTPUT_ROOT FINE_JOB_IDS_CSV ACCEPTANCE_OUTPUT

set -euo pipefail

PROFILE=${1:?"usage: resubmit_solar_gpu_refinement_chain.sh PROFILE OUTPUT_ROOT FINE_JOB_IDS_CSV ACCEPTANCE_OUTPUT"}
OUTPUT_ROOT=${2:?"usage: resubmit_solar_gpu_refinement_chain.sh PROFILE OUTPUT_ROOT FINE_JOB_IDS_CSV ACCEPTANCE_OUTPUT"}
FINE_JOB_IDS_CSV=${3:?"usage: resubmit_solar_gpu_refinement_chain.sh PROFILE OUTPUT_ROOT FINE_JOB_IDS_CSV ACCEPTANCE_OUTPUT"}
ACCEPTANCE_OUTPUT=${4:?"usage: resubmit_solar_gpu_refinement_chain.sh PROFILE OUTPUT_ROOT FINE_JOB_IDS_CSV ACCEPTANCE_OUTPUT"}

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
SBATCH_SCRIPT="$SCRIPT_DIR/run_solar_upper_gpu_search.sbatch"
FINALIZE_SCRIPT="$SCRIPT_DIR/finalize_solar_gpu_campaign.sbatch"
ACCEPTANCE_SCRIPT="$SCRIPT_DIR/run_solar_gpu_acceptance_pipeline.sbatch"
PYTHON_BIN=${PYTHON_BIN:-$HOME/.venvs/mpc_gpu/bin/python}

test -f "$PROFILE"
test -f "$SBATCH_SCRIPT"
test -f "$FINALIZE_SCRIPT"
test -f "$ACCEPTANCE_SCRIPT"
test -x "$PYTHON_BIN"
mkdir -p "$OUTPUT_ROOT" "$ACCEPTANCE_OUTPUT"

PROFILE_SHA256=$(sha256sum "$PROFILE" | awk '{print $1}')
REPLICATES=${REPLICATES:-4}
BASE_SEED=${BASE_SEED:-20260715}
ULTRA_GENERATIONS=${ULTRA_GENERATIONS:-60}
ULTRA_POPULATION=${ULTRA_POPULATION:-256}
ULTRA_ELITE=${ULTRA_ELITE:-32}
CONTROL_REFINE_GENERATIONS=${CONTROL_REFINE_GENERATIONS:-20}
CONTROL_REFINE_POPULATION=${CONTROL_REFINE_POPULATION:-1024}
CONTROL_REFINE_ELITE=${CONTROL_REFINE_ELITE:-64}

IFS=',' read -r -a FINE_JOBS <<< "$FINE_JOB_IDS_CSV"
if (( ${#FINE_JOBS[@]} != REPLICATES )); then
  printf 'expected %d fine job IDs, got %d\n' "$REPLICATES" "${#FINE_JOBS[@]}" >&2
  exit 2
fi

ULTRA_JOBS=()
CONTROL_2KM_JOBS=()
CONTROL_1KM_JOBS=()
for ((replicate=0; replicate<REPLICATES; replicate++)); do
  label=$(printf 'seed_%02d' "$replicate")
  fine_dir="$OUTPUT_ROOT/$label/fine_1km"
  ultra_dir="$OUTPUT_ROOT/$label/ultra_100m"
  control_2km_dir="$OUTPUT_ROOT/$label/control_2km"
  control_1km_dir="$OUTPUT_ROOT/$label/control_1km"
  ultra_seed=$((BASE_SEED + 1000 + replicate))

  ultra_job=$(
    sbatch --parsable \
      --dependency="afterok:${FINE_JOBS[$replicate]}" \
      --export="ALL,PROFILE_SHA256=$PROFILE_SHA256,GENERATIONS=$ULTRA_GENERATIONS,POPULATION=$ULTRA_POPULATION,ELITE=$ULTRA_ELITE,INTEGRATION_DS_KM=0.1,CONTROL_DS_KM=5.0,INITIAL_POLICY=$fine_dir/latest_policy.csv,INITIAL_STD_KMH=1.0,SEED=$ultra_seed,REQUIRE_SURROGATE_FEASIBILITY=1" \
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

control_dependency=$(IFS=:; printf '%s' "${CONTROL_1KM_JOBS[*]}")
finalize_job=$(
  sbatch --parsable \
    --dependency="afterok:$control_dependency" \
    --export="ALL,PROFILE_SHA256=$PROFILE_SHA256,SOLAR_GPU_ROOT=$ROOT" \
    "$FINALIZE_SCRIPT" "$OUTPUT_ROOT" "$REPLICATES" "$PROFILE"
)
acceptance_job=$(
  sbatch --parsable \
    --dependency="afterok:$finalize_job" \
    --export="ALL,SOLAR_GPU_ROOT=$ROOT,PYTHON_BIN=$PYTHON_BIN" \
    --output="$ACCEPTANCE_OUTPUT/slurm_%j.log" \
    "$ACCEPTANCE_SCRIPT" "$PROFILE" "$OUTPUT_ROOT" "$ACCEPTANCE_OUTPUT"
)

ultra_job_csv=$(IFS=,; printf '%s' "${ULTRA_JOBS[*]}")
control_2km_job_csv=$(IFS=,; printf '%s' "${CONTROL_2KM_JOBS[*]}")
control_1km_job_csv=$(IFS=,; printf '%s' "${CONTROL_1KM_JOBS[*]}")
cat > "$OUTPUT_ROOT/refinement_resubmission.yaml" <<EOF
profile: $PROFILE
profile_sha256: $PROFILE_SHA256
fine_job_ids: [$FINE_JOB_IDS_CSV]
ultra_job_ids: [$ultra_job_csv]
control_2km_job_ids: [$control_2km_job_csv]
control_1km_job_ids: [$control_1km_job_csv]
finalize_job_id: $finalize_job
acceptance_job_id: $acceptance_job
ultra_generations: $ULTRA_GENERATIONS
ultra_population: $ULTRA_POPULATION
ultra_elite: $ULTRA_ELITE
ultra_candidates_per_seed: $((ULTRA_GENERATIONS * ULTRA_POPULATION))
measured_runtime_basis: MLE35 A6000 run used about 87 minutes for 12 generations x 256 candidates
replaces_job_ids: ${REPLACES_JOB_IDS:-[]}
EOF

printf 'ultra_jobs=%s\n' "$ultra_job_csv"
printf 'control_2km_jobs=%s\n' "$control_2km_job_csv"
printf 'control_1km_jobs=%s\n' "$control_1km_job_csv"
printf 'finalize_job=%s acceptance_job=%s\n' "$finalize_job" "$acceptance_job"
