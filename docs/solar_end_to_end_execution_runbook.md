# ソーラーカーEMS 完全実行手順

この文書は、実車計測からモデル同定、独立検証、次大会の速度計画探索、厳密受入試験、
本番起動、終了後の保存までを、実際に実行する順番のまま一本に並べた手順書である。
途中で計算機が変わる場合も番号を分けない。`[Windows]`、`[WSL]`、`[GPU]` は、その番号を
どこで実行するかだけを表す。

## 0. 絶対条件

- GPU CEMが返す速度列は候補であり、本番指令ではない。
- 過去走行の独立気象は、PVを含む同定と独立検証に使うため、フルMLEより前に固定する。
- 学習に使った行でRMSEを出しても独立検証にはならない。日、走行、または区間単位のholdoutを固定する。
- `profile_exact_selected.yaml` は固定速度列の厳密replay用であり、本番には使わない。
- 本番では `profile_live_mpc_learned.yaml` だけを使う。live MPCは実測SoC、気象、進捗から再計画する。
- `SolarSim.ps1 -Action learn` は上位目的関数の重み探索である。速度計画CEMは
  `gpu_upper_policy_search.py` と `submit_solar_gpu_multifidelity_campaign.sh` が担当する。
- `--allow-failed-gate`、`--no-require-model-validation-gate`、失敗markerの削除を、本番昇格のために使わない。
- 現在のMLE35は独立モデル検証gate不合格の研究用であり、そのまま本番へ進めない。

## 1. 変数を決める `[Windows PowerShell]`

`<vehicle>`、GPUアカウント、保存先だけを実環境に合わせる。

```powershell
$ROOT = (Get-Location).Path
$VEHICLE = "<vehicle>"
$PKG = "project_packages/$VEHICLE"
$PROFILE = "$PKG/profile.yaml"
$MANIFEST = "$PKG/data/identification/identification_manifest.yaml"
$UTC = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$FIT_TAG = "fit_$UTC"
$GPU_HOST = "<user>@<gpu-host>"
$GPU_ROOT = "~/solar_mpc_fine"
```

以後のコマンドはリポジトリrootで実行する。

## 2. 初回だけ環境を導入する `[Windows PowerShell]`

```powershell
powershell -ExecutionPolicy Bypass -File .\Install-SolarSim.ps1
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Action build
```

内部では `scripts/bootstrap_ubuntu_humble.sh` がUbuntu 22.04、ROS 2 Humble、Python依存を準備し、
`colcon build` を実行する。既に導入済みでも、ソースや依存を更新したら `-Action build` は再実行する。

## 3. ソースを監査して基準revisionを固定する `[Windows PowerShell]`

```powershell
python scripts\audit_solar_package.py
python -m pytest -q
git rev-parse HEAD
git status --short
```

監査とtestが成功し、使用するcommit/hashと未commit差分をrun記録へ残す。未解決mergeがある状態を
本番releaseとして扱わない。

## 4. 車両project packageを用意する `[Windows PowerShell]`

新規車両は `project_packages/bwsc2027_template` を複製し、`$PKG` と `$PROFILE` をその車両用にする。
既存車両はこの複製だけを省略する。テンプレート原本へ実測値を直接書き込まない。

必須入力は次である。

- `profile.yaml`: 車両、battery、PV、MPC、runtime、logging、validation閾値。
- `data/identification/identification_manifest.yaml`: 学習、holdout、証拠、mapの所在と役割。
- `data/race/drive_schedule.yaml`: UTC走行窓。
- `data/race/control_stops.yaml`: 距離、滞在時間、開閉時刻。
- `data/route/route_profile.csv`: 距離、緯度経度、標高、勾配。
- `data/route/speed_profile.csv`: 法定、運用上限速度。
- `data/identification/evidence/*`: 根拠、event annotation、終端anchor、反実仮想の区別。

既知の質量、面積、電池容量、電流・電圧・温度限界、補機定格、タイヤ、ギヤ比、製品mapは
出典付きで先に固定する。同定対象には推定幅と単位を記録し、既知定数まで自由にしない。

## 5. 計測前に時刻、配線、通信、loggerを確認する `[WSL/実車]`

CANを使う構成では次を実行する。

```bash
bash scripts/setup_can.sh can0 500000
bash scripts/can_smoke_test.sh can0 500000 --try-250k
```

全機器のUTC差を1秒未満にし、GNSS fix、放電電流が正、pack電圧、SoC範囲、PVの未補正DC値を確認する。
`solar_power_w` のgainはPC側で一度だけ適用し、送信側と受信側で二重補正しない。

## 6. 実車計測を開始する `[Windows PowerShell/実車]`

```powershell
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Mode measure -Action up -Profile $PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Mode measure -Action status -Profile $PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Mode measure -Action graph -Profile $PROFILE
```

内部入口は `launch/solar_measurement.launch.py` で、preflight、distance、grade、logger、dashboardを起動する。
定速、coast-down、加減速、登坂・降坂、battery pulse、battery rest、panel sweepをrun単位で分ける。
運転操作、停止理由、panel状態、機器交換、異常をUTC付きevent annotationへ記録する。

## 7. 計測を停止し、原本を凍結する `[Windows PowerShell]`

```powershell
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Mode measure -Action log -Profile $PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Mode measure -Action stop -Profile $PROFILE
```

CSV、event、resolved profile、rqt graph、時計同期記録を同じimmutable run directoryへ保存する。
原本CSVをExcelで上書きせず、変換後CSVは別ファイルにする。

## 8. 生ログを正規化し、学習と独立holdoutを固定する `[Windows/CPU]`

テンプレートの列名と単位に合わせ、少なくともUTC、距離、速度、加速度、緯度経度、標高、勾配、
pack V/I、SoC、battery温度、PV power、panel状態を同期する。出力先の標準例は次である。

```text
$PKG/data/identification/raw/drive_timeseries.csv
$PKG/data/identification/raw/battery_pulse.csv
$PKG/data/identification/raw/battery_rest.csv
$PKG/data/identification/raw/panel_sweep.csv
$PKG/data/identification/raw/gps_track.csv
$PKG/data/identification/raw/observed_replay_log.csv
```

`identification_manifest.yaml` で、学習runとholdout runを明示する。同一runのランダム行分割ではなく、
日、run、または連続route区間で分離する。

## 9. 過去走行の独立気象を取得し、MLE前に固定する `[Windows/CPU]`

Open-Meteo等の独立cacheを使う標準経路は次である。

```powershell
$RAW_REPLAY = "$PKG/data/identification/raw/observed_replay_log.csv"
$WEATHER_REPLAY = "$PKG/data/identification/raw/observed_replay_log_weather.csv"

python scripts\enrich_replay_weather_components.py `
  --input $RAW_REPLAY `
  --output $WEATHER_REPLAY `
  --cache "<independent-historical-weather-cache.csv>"
```

BOM Himawariを使う場合は、時刻中心補正と品質JSONを同時に作る。

```powershell
python scripts\import_bom_satellite_solar.py `
  --normalized-csv "<bom-hourly-solar.csv>" `
  --route "$PKG/data/route/route_profile.csv" `
  --base-weather "<independent-base-weather.csv>" `
  --output-weather "$PKG/data/weather/historical_independent.csv" `
  --quality-json "$PKG/data/weather/historical_independent_quality.json"
```

`identification_manifest.yaml` の `normalized_replay_log_csv` を `$WEATHER_REPLAY` へ更新する。
`build_historical_weather_counterfactual_grid.py` のPV条件付き出力は診断用であり、独立同定・候補順位・証明には使わない。

## 10. 基礎mapを生成する `[Windows/CPU]`

通常は一括入口を使う。

```powershell
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Action identify -Profile $PROFILE
```

内部の `scripts/run_identification_pipeline.py` は、設定された入力に応じて次を呼ぶ。

```powershell
python scripts\build_route_profile_from_gps.py --gps_csv "<gps.csv>" --out_waypoints_csv "<waypoints.csv>" --out_profile_csv "<route.csv>"
python scripts\fit_battery_ecm_from_pulses.py --rest-csv "<battery_rest.csv>" --pulse-csv "<battery_pulse.csv>" --output-dir "<battery-ecm-output-dir>"
python scripts\build_pv_maps_from_csv.py --panel_csv "<panel.csv>" --out_panel_csv "<panel-map.csv>" --out_mppt_csv "<mppt-map.csv>"
python scripts\fit_vehicle_params.py --drive_csv "<drive.csv>" --out_yaml "<vehicle-fit.yaml>" --mass_kg <measured-mass-kg>
```

製品諸元または理論から得たmapは `source_map_catalog` と `grounded_map_sources` に出典、版、hash、単位を残す。

バッテリー入力の全列、単位、休止時間、電流符号、`train`/`validation`分離は
`templates/identification/battery_ecm_data_format_ja.md`に従う。単一電流の負荷時放電曲線、
5秒周期走行ログ、固定`40 mOhm/cell`、製品の1 kHz AC impedanceからOCV/R0 mapを生成してはならない。
`battery_ecm_identification_summary.json`の`gate_pass`が`true`でない限り、MLEと本番profileへ昇格しない。

## 11. 同定証拠bundleとmanifestを監査する `[Windows/CPU]`

BWSC2025形式の既存証拠を正規化する場合だけ最初のコマンドを使う。

```powershell
python scripts\normalize_bwsc2025_field_evidence.py `
  --package $PKG --weather-cache "<independent-historical-weather-cache.csv>"

python scripts\build_identification_evidence_bundle.py `
  --profile $PROFILE `
  --doc-root "<source-document-root>"

python scripts\run_vehicle_identification.py `
  --profile $PROFILE `
  --manifest $MANIFEST `
  --manifest-only
```

manifest-onlyが成功し、存在しないpath、単位不明、学習とholdoutの重複、終端根拠欠落がないことを確認する。

## 12. タグ付きフルMLEを実行する `[Windows/CPUまたはCPU Slurm]`

ローカルCPUでは次を実行する。canonical profileをまだ上書きしない。

```powershell
python scripts\run_vehicle_identification.py `
  --profile $PROFILE `
  --manifest $MANIFEST `
  --quality ultra `
  --output-tag $FIT_TAG

$RUN = "$PKG/outputs/identification/runs/$FIT_TAG"
$FIT_SUMMARY = "$RUN/${VEHICLE}_generic_fit_summary.yaml"
```

CPU Slurmを使う場合も同じ番号で、代わりに次を実行する。

```bash
PROFILE=project_packages/<vehicle>/profile.yaml
TAG=fit_$(date -u +%Y%m%dT%H%M%SZ)
sbatch scripts/run_vehicle_identification_cpu.sbatch "$PROFILE" "$TAG"
```

完了後にcandidate profile、fit summary、map、replay CSV、residual、PDF、run manifestが揃っていることを確認する。

## 13. 残差、終端SoC、run間差を独立監査する `[Windows/CPU]`

`$RUN` 内の実ファイル名をfit summaryに合わせて指定する。

```powershell
python scripts\audit_identification_residuals.py `
  --vehicle-replay "$RUN/replay_validation.csv" `
  --battery-replay "$RUN/replay_validation_battery_conditioned.csv" `
  --end-to-end-replay "$RUN/replay_validation_end_to_end.csv" `
  --output-dir "$RUN/residual_audit"

python scripts\assess_terminal_soc_consistency.py `
  --profile "$RUN/profile_candidate.yaml" `
  --observed-log $WEATHER_REPLAY `
  --output "$RUN/terminal_consistency.yaml"

python scripts\compare_identification_runs.py `
  --run "candidate=$RUN" `
  --run "baseline=<accepted-baseline-run>" `
  --role "candidate=candidate" `
  --role "baseline=baseline" `
  --output-dir "$RUN/run_comparison"
```

## 14. 同定promotion gateを評価するが、まだ昇格しない `[Windows/CPU]`

```powershell
python scripts\promote_identification_run.py `
  --package-dir $PKG `
  --run-dir $RUN `
  --gate-json "$RUN/promotion_gate.json"

python scripts\check_model_validation_gate.py `
  --profile "$RUN/profile_candidate.yaml" `
  --output "$RUN/model_validation_gate.json"
```

両コマンドが成功し、全checkがtrueでなければ15以降へ進まない。閾値をcandidateに合わせて緩めず、
データ、同期、物理モデル、map、推定幅を修正して8へ戻る。

## 15. 過去走行を独立気象でフルシミュレーションする `[Windows/CPU]`

`<historical-validation-profile.yaml>` はcandidate model、過去の独立気象、実際のroute、schedule、stop、
開始UTCを参照し、`simulation.require_model_validation_gate: true` にする。

```powershell
python scripts\solar_sim.py `
  --profile_yaml "<historical-validation-profile.yaml>"

python scripts\generate_fit_fullsim_report.py `
  --profile "<historical-validation-profile.yaml>" `
  --fit-summary $FIT_SUMMARY `
  --replay-csv "$RUN/replay_validation.csv" `
  --fullsim-manifest "<historical-fullsim-output>/latest_simulation_run.json"
```

RMSEだけでなく、bias、時間集約残差、区間energy誤差、終端SoC/V、温度、制約、予測対実行SoC差、
`finish_reached` と `adoption_gate_pass` を確認する。不合格なら8へ戻る。

## 16. 全gate合格時だけcanonical modelへ昇格する `[Windows/CPU]`

```powershell
python scripts\promote_identification_run.py `
  --package-dir $PKG `
  --run-dir $RUN `
  --gate-json "$RUN/promotion_gate.json" `
  --promote
```

昇格後の `$PROFILE`、map、fit summary、gate JSONのhashを固定する。ここまでが「モデル同定完了」である。

## 17. 必要な場合だけ上位目的関数重みを探索する `[Windows/CPU]`

これは速度列CEMではなく、目的関数weightの調整である。既に受入済みweightを使う場合は省略する。

```powershell
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Action learn -Profile $PROFILE
```

内部入口は `scripts/tune_upper_planner_weights.py`。robust scenario、multi-fidelity再順位、holdoutを通した
tuned profileだけを次工程のcandidateにする。自動でcanonicalへ上書きしない。

## 18. 次大会のroute、規則、schedule、stopを固定する `[Windows]`

公式資料からroute profile、標高、速度制限、走行可能UTC、control stop、開始時刻、終了期限を更新する。
距離基準、timezone、夏時間、日跨ぎを確認し、出典と版を保存する。推測値のまま探索を開始しない。

## 19. 次大会予報を取得する `[Windows/CPU]`

```powershell
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Action forecast -Profile $PROFILE
```

内部入口は `scripts/fetch_weather_forecast.py`。route/time grid、GHI/DNI/DHI、POA、温度、風、coverage、
取得UTCを確認する。予報更新ごとに旧CSVを上書きせずversionを残す。

## 20. CEM入力用fine profileを作り、気象gateを通す `[Windows/CPU]`

```powershell
$FINE_PROFILE = "$PKG/profile_operational_fine.yaml"

python scripts\create_operational_fine_profile.py `
  --profile $PROFILE `
  --output $FINE_PROFILE `
  --integration-ds-km 0.1 `
  --control-ds-km 1.0 `
  --mode exact_replay `
  --no-lock-policy `
  --require-model-validation-gate

python scripts\check_policy_weather_input.py `
  --profile $FINE_PROFILE `
  --output "$PKG/outputs/policy_weather_input_gate.json"
```

気象gateが失敗したらGPUへ送らない。

## 21. GPUへ送る依存関係を生成、監査、梱包する `[Windows/CPU]`

```powershell
$DEP = "$PKG/outputs/execution_dependencies"
$BUNDLE = "$PKG/outputs/transfer"

python scripts\generate_execution_dependency_manifest.py `
  --package $PKG `
  --research-run $RUN `
  --output-dir $DEP

python scripts\audit_execution_dependency_manifest.py `
  --manifest "$DEP/execution_dependency_manifest.csv" `
  --output-json "$DEP/execution_dependency_audit.json"

python scripts\package_execution_dependencies.py `
  --manifest "$DEP/execution_dependency_manifest.csv" `
  --output-root $BUNDLE `
  --name "${VEHICLE}_gpu_$UTC" `
  --archive-root M
```

audit成功後、生成archiveのSHA-256を記録する。全repoを配布する場合は
`python scripts\create_solarcar_only_package.py --fitted-package $PKG --force` も利用できるが、GPU runには
GPU/CEM sourceと選択profileがmanifestに含まれることを必ず確認する。

## 22. archiveをGPU計算機へ転送する `[Windows PowerShell]`

```powershell
$ARCHIVE = Get-ChildItem "$BUNDLE/${VEHICLE}_gpu_$UTC*.zip" |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1
$SHA_FILE = Get-Item ($ARCHIVE.FullName + ".sha256")
Get-FileHash $ARCHIVE.FullName -Algorithm SHA256
scp $ARCHIVE.FullName $SHA_FILE.FullName "${GPU_HOST}:~/"
```

認証に失敗したら停止し、正規のSSH再認証を行う。古いpasswordや鍵をスクリプトへ埋め込まない。

## 23. GPU側で展開し、hashと環境を検証する `[GPU login node]`

```bash
mkdir -p "$HOME/solar_mpc_fine"
cd "$HOME"
ARCHIVE="$HOME/<generated-name>.zip"
sha256sum -c "$(basename "$ARCHIVE").sha256"
unzip -q "$ARCHIVE" -d "$HOME/solar_mpc_fine"
cd "$HOME/solar_mpc_fine/M"
bash scripts/setup_gpu_server_env.sh
srun --partition=lab_gpu --gres=gpu:1 --cpus-per-task=2 --mem=8G --time=00:03:00 \
  "$HOME/.venvs/mpc_gpu/bin/python" -c \
  'import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))'
```

`True` とGPU名が出なければ探索を投入しない。`M` はstep 21の `--archive-root M` と一致させる。

## 24. CUDA Graph高速経路を数値一致benchmarkで承認する `[GPU login node、実装変更時は必須]`

`gpu_upper_policy_search.py` のCUDA Graph、補間、map、battery、weather積分を変更した場合は、
本campaignより先に同一seed・同一sampleのeager比較を行う。変更がない通常runでは、直近releaseの
`BENCHMARK_COMPLETE` とsource hashが一致することを確認してこの再実行だけを省略できる。

```bash
cd "$HOME/solar_mpc_fine/M"
export SOLAR_GPU_ROOT="$PWD"
export PYTHON_BIN="$HOME/.venvs/mpc_gpu/bin/python"
PROFILE="project_packages/<vehicle>/profile_operational_fine.yaml"
BENCH="project_packages/<vehicle>/outputs/cuda_graph_benchmark"
BENCH_JOB=$(sbatch --parsable \
  --export="ALL,SOLAR_GPU_ROOT=$PWD,PYTHON_BIN=$HOME/.venvs/mpc_gpu/bin/python,SEARCH_SCRIPT=scripts/gpu_upper_policy_search.py,DEPLOY_ON_SUCCESS=0" \
  scripts/benchmark_gpu_upper_policy_cuda_graph.sbatch \
  "$PROFILE" "$BENCH")
echo "$BENCH_JOB"
squeue -j "$BENCH_JOB"
```

job終了後に次を実行する。

```bash
test -f "$BENCH/BENCHMARK_COMPLETE"
"$PYTHON_BIN" -c 'import json,sys; p=json.load(open(sys.argv[1])); assert p["numerical_match"]' \
  "$BENCH/benchmark_summary.json"
cat "$BENCH/benchmark_summary.json"
sha256sum scripts/gpu_upper_policy_search.py > "$BENCH/search_source.sha256"
```

`numerical_match: true`、有限なmetric、許容範囲内のpolicy差、実測speedupを確認する。失敗時は高速版を
本番sourceへ昇格せず、同期を発生させる `float(cuda_tensor)`、`.item()`、CPU index化等を修正して再試験する。

## 25. GPU multi-fidelity CEMを投入する `[GPU login node]`

```bash
cd "$HOME/solar_mpc_fine/M"
export SOLAR_GPU_ROOT="$PWD"
export PYTHON_BIN="$HOME/.venvs/mpc_gpu/bin/python"
PROFILE="project_packages/<vehicle>/profile_operational_fine.yaml"
CAMPAIGN="project_packages/<vehicle>/outputs/gpu_multifidelity"
ACCEPT="project_packages/<vehicle>/outputs/gpu_acceptance"

bash scripts/submit_solar_gpu_multifidelity_campaign.sh "$PROFILE" "$CAMPAIGN"
```

この一回の投入で各独立seedについて、`coarse_5km`、`fine_1km`、`ultra_100m`、
`control_2km`、`control_1km`、最後にfinalizerが依存順で登録される。
job IDと `finalize_job_id` は `$CAMPAIGN/campaign_submission.yaml` に保存される。

## 26. GPU campaign完了を確認する `[GPU login node]`

```bash
squeue -u "$USER"
sacct -X --starttime today --format=JobID,JobName,State,Elapsed,ExitCode
test -f "$CAMPAIGN/CAMPAIGN_COMPLETE"
test ! -f "$CAMPAIGN/CAMPAIGN_FAILED"
```

依存jobが失敗したらfinalizerは完了しない。失敗stageを修正・再投入し、全seedの `latest_policy.csv` と
profile hashが揃ってから先へ進む。途中candidateだけを手作業で本番採用しない。

## 27. 厳密1 Hz replayとmesh convergenceを投入する `[GPU login node/CPU Slurm job]`

`campaign_submission.yaml` の `finalize_job_id` を読み、次を実行する。

```bash
FINALIZE_JOB_ID=$(awk '$1 == "finalize_job_id:" {print $2}' "$CAMPAIGN/campaign_submission.yaml")

sbatch --dependency="afterok:${FINALIZE_JOB_ID}" \
  --export="ALL,SOLAR_GPU_ROOT=$PWD,PYTHON_BIN=$HOME/.venvs/mpc_gpu/bin/python" \
  scripts/run_solar_gpu_acceptance_pipeline.sbatch \
  "$PROFILE" "$CAMPAIGN" "$ACCEPT"
```

内部では次の順で実行される。

1. `rank_gpu_upper_policy_candidates.py` でsurrogate順位を作る。
2. `validate_gpu_upper_policy_candidates.py` で全seedの5 km、2 km、1 km制御列を0.1 km/厳密1 Hz replayする。
3. `merge_exact_candidate_rankings.py` で厳密結果を統合する。
4. `run_upper_mesh_convergence.py` でintegration meshと独立control meshの収束を判定する。
5. `check_model_validation_gate.py` で独立車両モデルgateを再確認する。
6. 全合格時だけ `profile_exact_selected.yaml` と `profile_live_mpc_learned.yaml` を作る。

## 28. acceptance完了を確認する `[GPU login node]`

```bash
test -f "$ACCEPT/POLICY_ACCEPTANCE_COMPLETE"
test -f "$ACCEPT/ACCEPTANCE_COMPLETE"
test ! -f "$ACCEPT/ACCEPTANCE_FAILED"
```

3 marker、model gate、exact ranking、mesh convergence、profile hashが揃わなければ不合格である。
`POLICY_ACCEPTANCE_COMPLETE` だけの場合は速度列だけが通り、モデルが本番不合格である。

## 29. campaignとacceptance成果物をWindowsへ戻す `[Windows PowerShell]`

```powershell
$LOCAL_CAMPAIGN = "$PKG/outputs/gpu_multifidelity"
$LOCAL_ACCEPT = "$PKG/outputs/gpu_acceptance"
New-Item -ItemType Directory -Force -Path "$PKG/outputs" | Out-Null
scp -r "${GPU_HOST}:${GPU_ROOT}/M/project_packages/$VEHICLE/outputs/gpu_multifidelity" "$PKG/outputs/"
scp -r "${GPU_HOST}:${GPU_ROOT}/M/project_packages/$VEHICLE/outputs/gpu_acceptance" "$PKG/outputs/"
```

profile、選択policy、summary、CSV、marker、log、reportのhashをGPU側と照合する。

## 30. acceptance reportを生成してから最終オフライン全行程を実行する `[Windows/CPU]`

```powershell
$LIVE_PROFILE = "$LOCAL_ACCEPT/profile_live_mpc_learned.yaml"
$EXACT_PROFILE = "$LOCAL_ACCEPT/profile_exact_selected.yaml"

python scripts\generate_gpu_acceptance_report.py `
  --profile $FINE_PROFILE `
  --campaign-dir $LOCAL_CAMPAIGN `
  --acceptance-dir $LOCAL_ACCEPT `
  --fit-summary $FIT_SUMMARY `
  --promotion-gate "$RUN/promotion_gate.json" `
  --output-dir "$LOCAL_ACCEPT/report"

powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Action simulate -Profile $LIVE_PROFILE

python scripts\solar_sim.py --profile_yaml $EXACT_PROFILE
```

`LIVE_PROFILE` は再計画動作、`EXACT_PROFILE` は選択速度列の固定再現を確認する。nominalだけでなく、
低日射、向かい風、高温、通信欠落、予報更新遅延の別version profileも実行し、全制約とsafe fallbackを確認する。

## 31. 実機通信のloopback、異常packet、安全停止を試験する `[Windows/WSL/実機LAN]`

```bash
# vehicle Pi: telemetryを制御PCへ送り、vehicle向けcommandを受ける
python scripts/wifi_vehicle_sender_example.py --host 192.168.50.10 --port 52001 --period_sec 1.0
python scripts/wifi_planner_receiver_example.py --bind_host 0.0.0.0 --bind_port 52002

# chase Pi: telemetryを制御PCへ送り、chase向けcommandを受ける
python scripts/wifi_chase_sender_example.py --host 192.168.50.10 --port 52001 --period_sec 1.0
python scripts/wifi_planner_receiver_example.py --bind_host 0.0.0.0 --bind_port 52003
```

`templates/network` の固定IP/portをprofileへ反映し、正常、stale、future、duplicate、逆順、欠落、再接続を試す。
timeoutで旧commandを保持して加速しないこと、driver override、独立速度上限、V/I/温度保護、safe speed/停止を確認する。

## 32. ROS全modeとshadow road testを通す `[Windows/WSL/実車]`

```powershell
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode sim -Action up -Profile $LIVE_PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode sim -Action graph -Profile $LIVE_PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode sim -Action stop -Profile $LIVE_PROFILE

powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action up -Profile $LIVE_PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action status -Profile $LIVE_PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action graph -Profile $LIVE_PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action stop -Profile $LIVE_PROFILE
```

最初の実車試験はdriverがcommandを見ても従わないshadow modeで行い、実速度、上下位command、SoC、V/I、PV、風、
packet age、planner status、logger、dashboard、safe fallbackを実測比較する。shadow不合格なら本番へ進まない。

## 33. race-day release gateを二人で確認する `[Windows/実車]`

必須合格条件は次である。

- source: audit、pytest、ROS build、release commit/hash固定。
- model: 独立holdout、RMSE/bias/energy、終端anchor、物理bound、promotion gate合格。
- race: route距離、schedule、timezone、stop、speed limit、期限、予報coverage確認。
- policy: `CAMPAIGN_COMPLETE`、`POLICY_ACCEPTANCE_COMPLETE`、`ACCEPTANCE_COMPLETE`。
- simulation: finish、終端energy帯、全制約、detail balance、予測対実行SoC、robust scenario合格。
- ROS/network: 実node graph、重複nodeなし、NTP、正常/異常UDP、timeout、安全停止合格。
- operation: logger、dashboard、空きdisk、電源、冷却、shadow road test、driver override合格。

profile hash、map/evidence hash、`soc0`、route/weather version、IP/portを読み合わせ、開始後にcanonical profileを編集しない。

## 34. 本番MPCを起動する `[Windows PowerShell/実車]`

```powershell
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Mode live_wifi -Action up -Profile $LIVE_PROFILE
```

必ず `profile_live_mpc_learned.yaml` を指定する。`profile_exact_selected.yaml` をliveへ渡さない。

## 35. 本番中に状態、graph、logを監視する `[Windows PowerShell/実車]`

```powershell
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action status -Profile $LIVE_PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action graph -Profile $LIVE_PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 -Mode live_wifi -Action log -Profile $LIVE_PROFILE
```

logger時刻停止、telemetry age超過、bridge rejected、planner infeasible、V/I/温度異常、disk逼迫では、gateを緩めず
safe speedまたは停止へ移る。通信断で過去commandを保持して加速しない。

## 36. 本番を停止し、その日のrunを凍結する `[Windows PowerShell]`

```powershell
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Mode live_wifi -Action log -Profile $LIVE_PROFILE
powershell -ExecutionPolicy Bypass -File .\SolarSim.ps1 `
  -Mode live_wifi -Action stop -Profile $LIVE_PROFILE
```

live CSV、raw/corrected weather、planner log、resolved profile、map/evidence hash、graph、event、manual override、警告を
一つのversioned runとしてarchiveする。翌日のparameter更新前にその日のreplayと残差監査を行う。

## 完了判定

工程全体が完了したと言えるのは、次を全て満たした場合だけである。

1. 独立気象付きholdoutで同定promotion gateとmodel validation gateが合格している。
2. 過去走行フルシミュレーションが実測を許容誤差内で再現している。
3. GPU campaignの全seedと全mesh stageが完了している。
4. 厳密1 Hz replayとmesh convergenceが合格している。
5. `CAMPAIGN_COMPLETE`、`POLICY_ACCEPTANCE_COMPLETE`、`ACCEPTANCE_COMPLETE` が存在し、failure markerがない。
6. `profile_live_mpc_learned.yaml` による最終全行程、異常通信試験、shadow road testが合格している。
7. race-day release gateを二人で確認し、本番logと停止手順まで準備できている。

どれか一つでも欠ける場合、CEMの最良値やoptimizerの`success`だけを理由に本番投入してはならない。

## 所要時間の目安

時間はデータ量、CPU/GPU割当、queue待ち、修正回数で大きく変わる。作業計画には次の幅を使う。

- 初回導入・build・test: 30分から2時間。
- 実車計測と証拠作成: 最低1日、通常は複数日。ここは計算高速化では短縮できない。
- 正規化、独立気象、基礎map: 1時間から半日。手作業の同期修正を除く。
- ultra MLE、独立監査、過去fullsim: 数時間から1日/iteration。不合格なら再計測・再同定分を加える。
- production GPU CEM: RTX A6000級で4 seedを同時実行できれば概ね8から16時間、1 GPU直列なら概ね1.5から3日。
- 厳密1 Hz replay、12候補、mesh convergence: 数時間から24時間。Slurm scriptの上限は24時間。
- 通信異常試験、shadow road test、release確認: 半日から1日。

したがって、model gateが既に合格しGPU sourceも承認済みなら、予報固定から本番profile生成までの計算は
queue待ちを除いて約1から2日が現実的である。モデルgate不合格、CUDA benchmark失敗、seed依存停止がある場合は、
修正・再投入を含めて2日以上を見込み、終了時刻を断定しない。
