# 高SoC域Rintモデル修正報告

## 1. 結論

従来の基礎Rintマップは、単一電流のloaded電圧曲線の勾配を内部抵抗のSoC形状へ転写していた。この方法では、OCVの高SoC knee、分極、測定誤差、端点数値微分誤差とRintを分離できない。したがって、独立パルス試験が得られるまで、基礎RintマップをSoC・温度方向に平坦な無情報事前分布へ変更した。

既存MLE35の採用profileと採用マップは上書きしていない。MLE35に対しては、同じSoC・電流・OCV・分極電圧を保った局所反実仮想監査だけを追加した。短縮再同定は実行上限内に完了しなかったため、未完了runとして明示し、比較・昇格には使用しない。

## 2. 従来法の問題

従来法は、loaded cell voltageを `V_load(z)`、SoC 0.5の勾配を基準として、概ね次式でセルDC抵抗を構成していた。

```text
R_cell(z) = 0.040 * (|dV_load/dz| / |dV_load/dz|_z=0.5)^0.60
```

その後、同じ抵抗をloaded電圧へ足し戻してpseudo-OCVを作っていた。

```text
U_pseudo(z) = V_load(z) + I_string * R_cell(z)
```

この組合せは、同じ試験電流で再計算すれば、仮定したRint形状にかかわらず元のloaded電圧を再現しやすい。したがって、その自己整合性はRint形状の独立検証にならない。

## 3. 修正後の基礎モデル

セル抵抗の暫定スカラー事前値は、既存のチーム工学値 `0.040 ohm/cell` を維持する。25s6p packの基礎値は次式である。

```text
R_pack,base = 0.040 * 25 / 6 = 0.1666667 ohm
```

独立したmulti-SoC・multi-temperature pulse試験がないため、基礎面は次式とした。

```text
R_pack,base(T, z) = 0.1666667 ohm
```

温度別capacity値はDCIR測定ではないため、Rint温度形状へ転用しない。loaded電圧勾配もRint SoC形状へ転用しない。制約付き形状MLEは、最後の独立groupで改善した場合に限り形状を採用できる。

pseudo-OCVには一定IR補正のみを使用する。試験電流10 A、試験時9並列、25直列なので、pack補正量は次式である。

```text
Delta U_pack = (10 / 9) * 0.040 * 25 = 1.111111 V
U_pseudo(z) = V_load(z) + 1.111111 V
```

これは真のOCVを証明する式ではなく、単一電流データから作る暫定pseudo-OCVである。

## 4. 実行時モデルの修正

Rintマップの入力範囲外では、SoCと温度をCSVマップの実際の端点へクランプする。従来の `SoC 0.1～0.95` という固定値は `battery_iv()` から除去した。

抵抗値そのものの安全クリップは、別パラメータ `rint_physical_min_ohm` と `rint_physical_max_ohm` で扱う。上限の既定値は0、すなわち無効である。独立試験なしに都合のよい抵抗上限を設定していない。

CasADi symbolic経路はCSV補間を直接使えないため、従来の未測定SoC依存式を廃止し、マップの25 C・SoC 0.5参照値を用いる中立fallbackへ変更した。numeric replayとfull simulationは従来どおりCSVマップを使用する。

## 5. 追加した監査

電圧残差を一つのRMSEへ集約せず、次の層別CSVを生成する。

```text
SoC bin
current bin
SoC x current bin
```

高SoC反実仮想は、指定thresholdより上のRintだけをthreshold値へ平坦化する。SoC、電流、再構成OCV、line resistance、polarization voltage、その他のフィット済み状態は固定する。これは局所的な構造診断であり、再フィット後のfull replayではない。

## 6. MLE35監査結果

対象run:

```text
project_packages/bwsc2025_fitted_mle19_energywindow_inertia/
outputs/identification/runs/mle35_expanded_grade_single_source_ultra_v1
```

25 Cの採用Rintマップは、SoC 0.85で `0.151119 ohm`、SoC 0.95で `0.238337 ohm` であり、マップ成分は57.7%増加していた。MLE35の `rint_scale=0.9` と `r_line_ohm=0.008289` を含む静的抵抗は、`0.144296 ohm` から `0.222792 ohm` へ54.4%増加する。

40 Aでは、この差だけで次の差を生じる。

```text
terminal voltage drop difference = 3.1399 V
I^2 R loss difference            = 125.59 W
```

SoC 0.85以上のclean voltage 1,671点は全てDay 1で、予測電流平均は `1.60 A`、範囲は `-26.60～25.51 A` であった。高SoCと日、温度、初期SoC、OCV誤差が分離されていない。

局所平坦化の結果は次のとおりである。

| 指標 | 現行MLE35 | 高SoC平坦化 |
|---|---:|---:|
| bias observed-predicted [V] | -1.1506 | -1.2187 |
| MAE [V] | 1.1506 | 1.2187 |
| RMSE [V] | 1.2103 | 1.2608 |

平坦化でRMSEは `+0.0506 V` 悪化した。ただし、元のbiasが大きく負であり、抵抗スパイクがOCV・SoC・電流・分極等の誤差を相殺した可能性がある。この結果は高SoCスパイクの物理的正しさを証明しない。

SoC別のbattery-conditioned voltage RMSEは、0.85～0.90で `1.034 V`、0.90～0.95で `1.288 V`、0.95超で `1.757 V` まで増加した。

## 7. 直接変更したプログラム

| プログラム | 役割 | 変更 |
|---|---|---|
| `scripts/build_bwsc2025_fitted_package.py` | 根拠資料からOCV/Rint等の基礎マップを作る | loaded電圧勾配とcapacity温度係数のRint転用を廃止、平坦基礎面、一定pseudo-OCV補正、根拠Excelの共有読取fallback、報告書本文を修正 |
| `mpc_solarcar/model.py` | offline/live共通車体モデル | CSV軸クランプと抵抗値クリップを分離、固定SoC範囲を廃止、symbolic Rintを中立化 |
| `scripts/audit_identification_residuals.py` | replay残差監査 | SoC×電流電圧残差と高SoC局所反実仮想を追加 |
| `scripts/run_vehicle_identification.py` | MLE全工程のオーケストレータ | 採用Rint map・係数を監査へ渡し、新しい監査生成物をrun manifestへ記録 |
| `tests/test_identification_residual_audit.py` | 監査回帰試験 | 層別と反実仮想を検証 |
| `tests/test_identification_and_upper_solver.py` | 同定・モデル回帰試験 | 平坦基礎面、一定IR補正、lookup/physical clip分離を検証 |

## 8. 間接的に関係するプログラム

`scripts/solar_sim.py` と `mpc_solarcar/mpc_node.py` は `SolarCarModel` とprofileのRint mapを使用するため、次回採用MLE後に新モデルを利用する。`scripts/promote_identification_run.py`、`scripts/generate_fit_fullsim_report.py`、`scripts/generate_gpu_acceptance_report.py` は、同定summary・replay・監査生成物を消費する。今回、これらの採用判定閾値は変更していない。

## 9. 生成物

MLE35監査:

```text
.../mle35_expanded_grade_single_source_ultra_v1/reports/rint_high_soc_method_audit/
  residual_audit.json
  voltage_soc_current_metrics.csv
  high_soc_rint_counterfactual_trace.csv
  Rint_T_by_soc_high_soc_flat_counterfactual.csv
  residual_regime_metrics.csv
  soc_divergence_trace.csv
  residual_soc_audit.png
```

短縮再同定は `rint_neutral_prior_quick_v2_20260801` に中間mapまで生成したが未完了である。`RUN_INCOMPLETE.json` があるrunを採用してはならない。

## 10. 検証

```text
110 passed in 8.45s
40 downstream layout/simulation tests passed in 10.69s
total: 150 passed
python py_compile: passed
git diff --check: passed
```

## 11. 次に必要な独立試験

本当にRintを決めるには、各SoC・各温度で休止後に複数電流パルスを与え、少なくとも次のCSVを取得する。

```text
time_utc,soc_reference,temp_cell_c,current_a,terminal_voltage_v,pulse_id,elapsed_from_pulse_s
```

`soc_reference` は同じOCV mapから逆算した値ではなく、独立coulomb counterまたは既知充放電量を基準にする。瞬時DCIR、数秒分極、休止OCVを分離し、SoC・温度ごとのholdoutを通過した後にのみ、平坦基礎面を測定マップへ置換する。

完了runを得る再実行例は次である。完了後もpromotion gateとhistorical full simulationを通すまでcanonical profileへ昇格しない。

```powershell
python scripts\run_vehicle_identification.py `
  --profile project_packages\bwsc2025_fitted_mle19_energywindow_inertia\profile.yaml `
  --quality ultra `
  --output-tag rint_neutral_prior_ultra_v1 `
  --rebuild-grounded-base-maps
```
