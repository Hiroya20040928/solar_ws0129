# バッテリー OCV・R0・1-RC 根本改訂報告

## 結論

旧式

```text
R_cell(z) = 0.040 * (|dV/dz| / |dV/dz| at z=0.5)^0.60
```

は廃止した。`0.040 ohm/cell`、指数`0.60`、負荷時放電曲線の傾きのいずれも、新しいOCV/R0生成には使用しない。単一電流の負荷時曲線は、OCV、瞬時抵抗、分極、電圧計誤差を一意に分離できないためである。

新しいpack-levelモデルは、放電電流を正として次式を使用する。

```text
Vt = Uocv(z) - I R0,total(z,T) - V1
dV1/dt = -V1/tau(z,T) + R1(z,T) I/tau(z,T)
dz/dt = -I/(3600 Qnom)
```

`R0,total`はpack二端子で観測できる瞬時総抵抗であり、cell、tab、bus bar、contactor、fuse、配線を含む。四端子計測などの追加証拠がない限り、これを`cell Rint`と`Rline`へ分割しない。

## 同定方法

1. 独立SoC参照を持ち、30分以上かつ休止末尾の電圧傾きが既定10 uV/s以下の休止電圧から、非減少制約付きで基準温度域の`Uocv(z)`を同定する。温度によるOCV変化が計測精度を超える場合はholdout gateが不合格となるため、温度依存を抵抗へ吸収して採用しない。
2. 休止後0.25秒以内から始まる全パルス波形を`DeltaV(t)=DeltaI(t)R0,total + Istep R1(1-exp(-t/tau))`へ同時適合する。各`tau>0`候補で非負最小二乗により`R0,total>=0, R1>=0`を解き、`t=0+`へ外挿した切片をR0とする。最初の1標本をそのままR0へ変換しない。
3. `tau`は正の有界一次元最適化で決定し、`R0`の不確かさは電圧・電流精度、波形残差、回帰情報行列から伝播する。
4. `R0,total`、`R1`、`tau`は、`zeta=(SoC-0.5)/0.5`、`theta=(T-25)/25`として、`log R = beta0 + beta_z*zeta + beta_T*theta + beta_zz*zeta^2 + beta_zT*zeta*theta + beta_TT*theta^2`という低次元面へ適合する。`R=exp(log R)`なので負抵抗・負時定数は生じない。SoC・温度方向は既定で決め打ちせず、独立パルスが支持する高SoC上昇も下降も保持する。`dR0/dSoC <= 0`または`dR0/dT <= 0`の線形不等式は診断仮説として明示指定できるが、実運用mapを作るrelease既定値には用いない。
5. 二次面を学習SoC・温度範囲の外へ外挿しない。範囲外では最寄りの学習境界値を一定保持する。既定の実運用SoC範囲は0.05から0.95であり、trainは両端から0.05以内まで到達し、validationは下端・上端それぞれ0.10幅の領域に独立パルスを含まなければならない。これらは車両の運用範囲に合わせてCLIで明示変更する試験設計値であり、物性係数ではない。
6. 試験前に固定した`train`と`validation`を分離し、独立SoC、休止、サブ秒計測、SoC範囲、温度範囲、上下端holdout誤差、受動性を全て通過した場合だけ`gate_pass=true`とする。任意の方向制約を診断目的で指定した場合は、その仮説の有無、制約数、最大違反量をsummaryへ残し、無制約release fitと比較する。OCV・パルス電圧・R0面の誤差は、計測器精度から伝播した不確かさで除した無次元RMSEで判定する。既定3 sigmaは物性値ではなく、summaryへ保存する統計的採用規則である。

離散時間の実車再生と1 Hz実行器では、各サンプル間の電流を零次ホールドして次式を厳密に進める。

```text
alpha_k = exp(-Delta t_k / tau(z_k,T_k))
V1_(k+1) = alpha_k V1_k + (1-alpha_k) R1(z_k,T_k) I_k
```

上位MPCの区間が`tau`より十分長い場合だけ、計画計算を軽量化する定常近似`V1=I R1`を用いる。識別済み`R1/tau` mapが存在するとき、走行ログから単一`R1/tau`を再フィットして上書きする処理は実行しない。

これは測定範囲内の構造的受動性と独立holdout整合性を示す。未計測温度・SoC・電流・劣化状態まで物理的真値であることを数学的に証明するものではない。

## BWSC2025再監査結果

workspaceには独立した長時間休止・多SoC・多温度・sub-second pulse CSVが存在しない。`mle22_pulse`という名称の証拠は、実際にはBWSC走行ログ終端3 kmの5秒周期V-I回帰であり、独立pulse試験ではない。

現存MLE35から確認できる条件付き数値は次のとおりである。

- 終端3 km V-I回帰の総直列抵抗: `0.176736 ohm`
- 道路ログから得た1-RC条件付き値: `R1 = 0.084252 ohm`, `tau = 73.5951 s`
- 1-RC学習RMSE: `0.840904 -> 0.754758 V`
- Day 6 holdout RMSE: `2.024838 -> 1.970106 V`
- MLE35 battery-conditioned clean voltage RMSE: `0.968187 V`

これらは道路ログ再現を改善するが、SoC自体、OCV、R0面、温度依存を独立に証明しない。このため現状の物理証拠gateは`false`であり、既存MLE35 mapは履歴条件付き研究成果として保存し、新しい実運用mapへ書き換えていない。

20図の再監査HTMLは `outputs/battery_ecm_revision_20260802/OCV_R0_1RC_complete_visual_report.html`、同じ判定のJSONは同名の`.json`に出力した。図4・図5に表示するMLE35面は新フィットではなく、問題を監査するための不採用旧成果物である。高SoC急上昇には独立パルス証拠がないため、図内にも`REJECTED`を明記する。

## 関係プログラム

- `scripts/fit_battery_ecm_from_pulses.py`: 新しいOCV・R0,total・R1・tau同定、物理証拠gate、20図HTML生成。
- `scripts/generate_battery_ecm_current_evidence_report.py`: 既存MLE35を新基準で再監査する20図HTML生成。
- `scripts/run_identification_pipeline.py`: 休止CSVとpulse CSVを一括して新同定器へ渡す入口。
- `scripts/build_ocv_curve.py`: 旧低電流OCV近似を停止する互換ガード。
- `scripts/build_rint_map_from_timeseries.py`: 旧`(OCV-V)/I` map生成を停止する互換ガード。
- `scripts/build_bwsc2025_fitted_package.py`: 固定`0.040`を除去し、合格済みsummaryとmapがない基礎OCV/R0再生成を拒否する。
- `mpc_solarcar/model.py`: R0,total、R1 map、tau mapを読み、R0,total採用時に`Rline`を二重加算しない。MPC用定常枝と実行器用明示`V1`状態を分離する。
- `mpc_solarcar/mpc_node.py`, `mpc_solarcar/live_launch.py`: R1/tau mapを上位MPCへ渡す経路。
- `mpc_solarcar/solar_state_node.py`, `scripts/solar_sim.py`: `V1`を時系列状態として保持する実行・SILS経路。
- `scripts/run_vehicle_identification.py`: 独立pulse mapをロックし、道路ログ由来の後付け1-RCで上書きしない識別経路。
- `templates/identification/battery_ecm_data_format_ja.md`: ユーザー入力CSVの完全仕様。

## 実測後の実行

```powershell
python scripts\fit_battery_ecm_from_pulses.py `
  --rest-csv data\identification\raw\battery_rest.csv `
  --pulse-csv data\identification\raw\battery_pulse.csv `
  --output-dir outputs\identification\battery_ecm
```

`battery_ecm_identification_summary.json`の`gate_pass`が`true`の場合だけ、profileの`identification.battery_ecm`に生成物を指定してMLEを再実行する。不合格時に固定値や閾値緩和で穴埋めしてはならない。

## 理論・試験設計の一次資料

- "How degradation of lithium-ion batteries impacts capacity fade and resistance increase: A systematic, correlative analysis," Journal of Power Sources 656, 237921, 2025. https://doi.org/10.1016/j.jpowsour.2025.237921 （814セルで容量低下と抵抗増加の強い相関を示す一方、化学系と劣化経路をまたぐ単一のYATA係数を与える研究ではない。容量SOHからR0を一意生成せず、両者を独立測定する根拠。）
- "FreedomCAR Battery Test Manual for Power-Assist Hybrid Electric Vehicles," INL, 2003. https://inldigitallibrary.inl.gov/content/uploads/50/2026/04/6308373.pdf （HPPCの2秒・10秒抵抗を別々の時点の`Delta V/Delta I`で定義する。R0と長時間分極を同じ抵抗値として扱わない試験上の根拠。）
- "A study of the open circuit voltage characterization technique and hysteresis assessment of lithium-ion cells," Journal of Power Sources 295, 99--107, 2015. https://doi.org/10.1016/j.jpowsour.2015.06.140 （OCVが無負荷平衡電圧であり、同じSoCでも充放電履歴に依存することを示す。負荷時放電曲線をOCVへ直読しない根拠。）
- "High-power lithium-ion battery characterization dataset for stochastic battery modeling," Scientific Data, 2025. https://doi.org/10.1038/s41597-025-05725-y （NMCセルをSoC 15--95%、5/25/40 degC、充放電0.5C--8Cでpulse試験し、高SoC・低SoCの抵抗が中間SoCより高い例を報告。SoC単調減少を普遍則にできない根拠。）
- "A measurement method for determination of dc internal resistance of batteries and supercapacitors," Electrochemistry Communications 12(2), 242--245, 2010. https://doi.org/10.1016/j.elecom.2009.12.004 （10 ms、2 s、30 sの抵抗を区別し、瞬時オーム抵抗と分極を同一視しない根拠。）
- "Excitation Pulse Influence on the Accuracy and Robustness of Equivalent Circuit Model Parameter Identification for Li-Ion Batteries," World Electric Vehicle Journal 17(1), 38, 2026. https://doi.org/10.3390/wevj17010038
- "One-shot parameter identification of the Thevenin's model for batteries: Methods and validation," Journal of Energy Storage 29, 101282, 2020. https://doi.org/10.1016/j.est.2020.101282
- "Online Parameter Identification and Joint Estimation of the State of Charge and the State of Health of Lithium-Ion Batteries Considering the Degree of Polarization," Energies 12(15), 2939, 2019. https://doi.org/10.3390/en12152939
- "An improved Thevenin model of lithium-ion battery with high accuracy for electric vehicles," Applied Energy 254, 113615, 2019. https://doi.org/10.1016/j.apenergy.2019.113615

これらは1-RC式、離散状態式、pulse/HPPC試験、SoC・温度依存パラメータ、識別可能性の根拠である。ただし、本車両の数値を与える資料ではない。本車両の係数は本車両packの独立試験だけから決める。

## 2026-08-03 旧マップ除去後の同一品質MLE比較

旧MLE35のR0形状から、負荷時放電曲線の傾きと容量温度係数を除いた診断用反実仮想を作った。独立パルス値を捏造しないため、R0は旧mapの25 degC、SoC 0.5値を全測定範囲へ一定保持し、負荷時曲線はOCV候補の形状側へ一度だけ置いた。この候補は`release_eligible=false`であり、実車R0の採用値ではない。

同じ`quick`品質、同じ非電池map、同じ走行ログで旧形状対照と比較した結果は次のとおりである。

| 指標 | 旧形状対照 | 分離後候補 | 変化 |
|---|---:|---:|---:|
| clean voltage RMSE [V] | 1.636560 | 1.480333 | -9.546% |
| battery-conditioned voltage RMSE [V] | 0.973340 | 0.783219 | -19.533% |
| end-to-end voltage RMSE [V] | 1.800742 | 1.782101 | -1.035% |
| terminal SoC error [-] | 0.044781 | 0.027492 | -38.609% |
| dynamic holdout RMSE [V] | 1.947716 | 1.527541 | -0.420175 V |

電力RMSEは両者とも`204.132011 W`で同一であり、差は電池電圧モデルの置換に限定されている。SoC 0.85--0.90のbattery-conditioned RMSE差は`-0.074630 V`で、旧高SoC急上昇を除いても悪化しなかった。ただし、候補の`rint_scale=0.96`と`r_line=0.012 ohm`は上限に張り付き、SoC 0.90以上にはbattery-conditioned標本が0件である。したがって、この結果が証明するのは「旧式が残差改善にも必要でなかった」ことまでであり、「一定R0が真値」ではない。

成果物は次に保存した。

- `project_packages/bwsc2025_fitted_mle19_energywindow_inertia/outputs/identification/experiments/mle36_battery_deconfounded_neutral_quick_20260803/comparison_report.md`
- 同ディレクトリの`reference_vs_candidate_metrics.csv`
- 同ディレクトリの`reference_vs_candidate_soc_binned_voltage.csv`
- 同ディレクトリの`OCV_Rint_complete_visual_report_mle36_deconfounded.html`

## 昇格防止と最終差替え条件

`meta.production_live_allowed=true`を設定したprofileは、live launch時に次を全て検査する。

1. `battery_ecm_identification_summary.json`、OCV、R0,total、R1、tauの5証拠が存在する。
2. summaryの`gate_pass=true`である。
3. 固定40 mOhm prior、負荷時曲線傾き、容量温度係数をR0へ使っていない。
4. 同定SoC範囲がprofileの`model.soc_min`から`model.soc_max`までを覆う。
5. runtimeのOCV、R0、R1、tau pathが同じ合格証拠を参照する。

合格済みR0,total mapを使うと、MLEの第1段から`rint_scale=1`、`r_line=0`へ固定し、走行ログ残差によるR0形状warpと後段scalar再調整を禁止する。R1とtauは実行時に1RC状態として伝播する。これにより、負荷時の高SoC電圧傾斜をR0へ戻す迂回路を閉じた。

現時点の結論は、旧Rint/疑似OCVを本番用として差し替えることは完了したのではなく、**旧式を本番経路から排除し、実測後にのみ物理mapへ原子的に差し替えられる状態まで修正した**、である。YATA実packの休止・サブ秒pulseデータがないまま数値mapを完成扱いすることはできない。
