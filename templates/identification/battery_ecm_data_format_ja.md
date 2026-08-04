# バッテリー OCV・R0・1-RC 同定データ仕様

この入力は、CSVの1行目をヘッダー、2行目以降をデータ行とするUTF-8 CSVです。単位は列名に従い、欠損値、桁区切り、結合セル、説明行を入れません。放電電流を正、充電電流を負とします。

## `battery_rest.csv`

`rest_id,split,soc_reference,temp_c,rest_duration_sec,rest_voltage_v,rest_current_a,rest_voltage_slope_uv_per_s,soc_reference_method,current_accuracy_a,voltage_accuracy_v,source_file` の12列を使用します。

- `rest_id`: 休止試験を一意に識別する文字列。
- `split`: 事前に固定した `train` または `validation`。同じ試験を両方へ入れません。
- `soc_reference`: 0から1の独立SoC。モデル推定SoCや電圧逆引きSoCは禁止です。
- `temp_c`: pack代表温度 [degC]。
- `rest_duration_sec`: 電流遮断後の連続休止時間 [s]。既定では1800秒以上が必要です。
- `rest_voltage_v`: 休止終了時のpack端子電圧 [V]。
- `rest_current_a`: 休止終了時のpack電流 [A]。
- `rest_voltage_slope_uv_per_s`: 休止末尾の事前宣言区間を直線回帰した電圧傾き [uV/s]。既定では絶対値10 uV/s以下が必要で、単に30分待っただけでは平衡と判定しません。
- `soc_reference_method`: `coulomb_counted_from_full`、`gravimetric_capacity`、`independent_calibrated_bms`、`known_charge_state` のいずれか。
- `current_accuracy_a`, `voltage_accuracy_v`: 校正証明または計測器仕様に基づく絶対精度。
- `source_file`: 改変前計測ファイルの相対パス。

## `battery_pulse.csv`

`test_id,split,time_s,step_start_time_s,phase,current_a,voltage_v,temp_c,soc_reference,pre_rest_duration_sec,pre_rest_voltage_slope_uv_per_s,soc_reference_method,current_accuracy_a,voltage_accuracy_v,source_file` の15列を使用します。

- `test_id`: 一つの休止・電流ステップ・緩和系列を一意に識別する文字列。
- `time_s`: 当該試験内の単調増加時刻 [s]。
- `step_start_time_s`: 電流指令を切り替えた正確な時刻 [s]。同一`test_id`内では同じ値です。
- `phase`: ステップ前は `pre_rest`、通電中は `pulse`、遮断後は `post_rest`。
- `current_a`: 同期されたpack電流 [A]。放電正、充電負です。
- `voltage_v`: 電流と同時計測したpack端子電圧 [V]。
- `pre_rest_duration_sec`: パルス直前の連続休止時間 [s]。
- `pre_rest_voltage_slope_uv_per_s`: パルス直前の休止末尾電圧傾き [uV/s]。全行へ同じ試験値を記録します。
- その他の列は休止CSVと同じ定義です。

`R0,total`を分極から分離するには、ステップ開始後の最初の電圧標本が既定0.25秒以内に必要です。同定器は最初の1点を直接`-DeltaV/DeltaI`へ置き換えず、全波形を`R0 + 1-RC`へ非負同時適合して`t=0+`へ外挿します。5秒周期の走行ログや負荷時放電曲線は、この条件を満たさないためR0同定入力には使用できません。

`R0,total`には本pack向け工学制約として、SoC 0.50以上で非増加、温度上昇方向にも非増加を課します。既定の実運用範囲0.05から0.95に対し、`train`は各端から0.05以内まで、`validation`は下端・上端それぞれ0.10幅に最低1試験を配置します。二次フィットは`train`範囲外へ外挿せず最寄り端点を一定保持し、上下端holdoutが計測不確かさ内で合わないmapは昇格しません。実際の運用SoCが異なる場合は、`--operational-soc-min`と`--operational-soc-max`を車両仕様に合わせ、試験点も同時に変更してください。

## 実行

```powershell
python scripts\fit_battery_ecm_from_pulses.py `
  --rest-csv data\identification\raw\battery_rest.csv `
  --pulse-csv data\identification\raw\battery_pulse.csv `
  --output-dir outputs\identification\battery_ecm
```

終了コード0かつ`battery_ecm_identification_summary.json`の`gate_pass: true`の場合だけ、生成されたOCV・R0・R1・tauを実運用候補にできます。OCV、パルス電圧、R0面のholdout誤差は、入力した計測精度から伝播した不確かさで除して評価します。既定の3 sigma基準は物性係数ではなく、JSONへ保存される変更可能な統計的採用規則です。失敗したチェックを閾値緩和で隠さず、試験または計測精度を改善してください。
