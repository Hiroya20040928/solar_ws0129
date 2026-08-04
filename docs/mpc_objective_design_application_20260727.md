# 「MPC目的関数の自動設計」読了・適用報告

作成日: 2026-07-27  
対象資料: `C:\SSD-PUTA\Users\user\Downloads\MPC目的関数の自動設計.pdf`  
対象実装: `solar_ws0129-main`

## 1. 読了範囲と扱い

添付PDFの全42ページを、レイアウト保持テキストと全ページ画像の両方で確認した。数式、表、
コード断片、後半のBWSC向け議論までを対象としており、冒頭だけを要約したものではない。

このPDFは会話形式の設計レビュー資料であり、それ自体を査読論文とは扱わない。資料中の主要な
主張は、末尾に示すDifferentiable MPC、学習ウォームスタート、適応メッシュ、CVaR等の一次資料
と照合した。その上で、現在の車両モデルと安全ゲートに適合するものだけを実装した。

## 2. 結論

PDFの中心的な指摘は正しい。MPCの項と係数は自動探索できるが、「何を良いレースとするか」と
安全制約は人間が外側に与えなければならない。また、CEMは大域最適性を保証せず、単一の名目
計画だけでは、実戦のSoC、進捗、温度、天候、停車、ドライバー追従誤差のずれを覆えない。

今回、直ちに安全かつ後方互換に反映できる次の項目を実装した。

1. 上位MPCの前回解と外部速度計画を、相対メッシュ番号ではなくルート絶対距離でシフトする。
2. 制御停止でメッシュを分割したときの、絶対距離と相対距離の混在を修正する。
3. 目的関数CEMを、期待値だけでなく分散、CVaR、シナリオ失敗確率で評価する。
4. どれか1シナリオが完走すれば完走扱いとなる判定を廃止する。
5. 低SoC、高温、ドライバー遅れ、低日射・高負荷、空力偏差、好天側を評価集合へ加える。
6. SoC偏差、バッテリー温度偏差、停止解除を上位MPCのイベント再計画条件へ加える。
7. リスクゲート又は独立モデル検証に失敗した学習プロファイルを、本番候補と表示しない。

Differentiable MPC、ニューラルネットによるウォームスタート、オンラインでの目的関数学習は
今回は導入していない。現行モデルには効率マップ、クリップ、停止・運転窓、モード選択などの
非滑らかな要素があり、独立モデル検証ゲートも本番昇格条件を満たしていないためである。

## 3. 今回導入した数式

シナリオ `i` の最大化スコアを `S_i`、宣言確率を `p_i` とする。損失は `L_i=-S_i` とする。

```text
E[S]       = sum_i p_i S_i
Var[S]     = sum_i p_i (S_i - E[S])^2
CVaR_a(L)  = 最悪側の確率質量 (1-a) に含まれる損失の重み付き平均
S_risk     = E[S] - lambda_var Var[S]
                   - lambda_cvar max(0, CVaR_a(L) - E[L])
P_fail     = sum_i p_i 1[scenario i is infeasible]
```

`P_fail` が設定値を超えた候補は、性能スコアにかかわらず不適格スコアへ落とす。既定値は
`a=0.90`、`lambda_cvar=0.30`、`lambda_var=0`、`P_fail<=0.01` である。分散項はスコア単位の
スケーリングを決めてから有効化する。

これは有限のストレスシナリオ集合に対する経験的リスクである。宣言重みが実際の発生確率として
校正されていない限り、「現実の失敗確率が1%以下」とは主張できない。

## 4. 絶対距離ウォームスタート

前回計画の絶対制御点を `s_prev`、速度を `v_prev`、現在の絶対制御点を
`s_now=s_vehicle+s_relative` とすると、初期値は次で作る。

```text
v_init,j = clip(interp(s_now,j; s_prev, v_prev), v_min, v_max)
```

従来のオンライン処理は、前回と現在の両方を0 km始まりの相対メッシュとして補間していた。
車両が進んでも同じ配列位置を再利用するため、前回解の「残り」を使うシフトではなかった。
外部CEM計画も同様に、絶対距離で照合しなければ現在地点に対応しない。

共通処理は `mpc_solarcar/upper_policy.py` に集約し、オンライン
`mpc_solarcar/mpc_node.py` とオフライン `scripts/solar_sim.py` の双方が同じ関数を使う。

## 5. ロバストシナリオ

`--scenario-mode robust` の既定集合は次の通りである。

| シナリオ | 重み | 主な偏差 |
|---|---:|---|
| nominal | 0.30 | 基準 |
| low_solar_high_load | 0.20 | 日射低下、弱電増加、CdA/Crr増加 |
| drag_bias | 0.10 | 大きな空力・転がり偏差 |
| low_initial_soc | 0.15 | 初期SoC低下 |
| hot_battery | 0.10 | 初期バッテリー温度上昇 |
| driver_lag | 0.10 | 遅れ、時定数、加減速能力低下 |
| favorable_weather | 0.05 | 日射上振れ、弱電低下 |

好天側も必要である。悪天候側だけで学習すると、エネルギー余剰時の終端SoC、速度上限、
温度、無駄な発電抑制に関する誤りを検出できない。

各シナリオは、完走、終端SoC、最低SoC、上位ソルバ成功、予測ミッション可否、
予測・実行SoC同期を個別に検査する。目的関数学習ゲートには独立モデル検証も必要である。
合格しても「厳密検証へ進める」だけであり、運用リリースにはならない。

## 6. 実行方法

目的関数のロバストCEM探索を直接実行する例:

```powershell
python scripts\tune_upper_planner_weights.py `
  --profile_yaml project_packages\<vehicle>\profile.yaml `
  --scenario-mode robust `
  --risk-cvar-alpha 0.90 `
  --risk-cvar-weight 0.30 `
  --risk-variance-weight 0.0 `
  --max-scenario-failure-probability 0.01 `
  --generations 16 `
  --population 8 `
  --elite_count 3 `
  --validation_top_k 5
```

主な追加出力:

```text
score_mean
score_worst
score_variance
loss_cvar
tail_excess_loss
scenario_failure_probability
chance_constraint_pass
scenario_feasible_all
model_validation_gate_pass_all
objective_design_gate_pass
```

生成プロファイルの `meta.objective_design` には、合否、リスク設定、失敗確率を記録する。
`operational_release_eligible` は常に `false` とし、その後の独立exact replay、
mesh convergence、live acceptanceを省略できないようにした。

## 7. PDF提案との追跡表

| PDFの提案・指摘 | 現在の状態 | 判断 |
|---|---|---|
| 外側の真の評価指標を人間が定義 | 既存 | 完走、時間、終端SoC、振動、電流等の外側スコアを使用 |
| 安全・法規を学習重みから分離 | 部分対応 | 実行クランプ、SoC guard、可否ゲートは維持。内側の全制約のhard化は未完 |
| `a,b,ab` より豊かな候補辞書 | 既存 | 速度差、電流、電力、Joule、空力、温度、終端、barrier等を実装済み |
| 項の正規化 | 未実装 | 既存重みの意味を変えるため、モデル確定後に互換性移行が必要 |
| L1/Group Lasso | 部分対応 | 小重みのゼロ化とactive-term数ペナルティあり。厳密Group Lassoではない |
| 二階層最適化 | 既存 | 外側CEM、内側上位MPCとして実装 |
| Differentiable MPC | 不採用 | 非滑らかなモデルと安全検証不足のため研究ブランチで行うべき |
| 逆最適制御・実演学習 | 未採用 | 人間走行ログを最適教師と仮定できない |
| シンボリック回帰 | 未採用 | 車両物理式・同定マップの置換は独立検証が先 |
| CEM/CMA-ES/BO | CEM実装済み | 目的重みと速度計画で役割を分離 |
| ホライズン・構造探索 | 部分対応 | multi-fidelity固定段階あり。ホライズン自体の外側探索は未実装 |
| 複数初期値 | 既存 | shifted、定速、ramp、balance、CEM上位候補を評価 |
| 前回解の正しいシフト | 今回修正 | 絶対距離補間へ統一 |
| 条件付きwarm-start library | 部分対応 | 距離計画は保持。SoC/温度/天候クラスタ別ライブラリは未実装 |
| 全状態組合せを保存しない | 方針採用 | 次元の呪いを避け、シナリオ・クラスタ・イベント再計画を使う |
| 学習warm start | 未採用 | データ集合とOODゲートが未整備。最適化ソルバ自体は必ず残す |
| 詳細近傍＋粗い全レース | 既存 | adaptive full-race horizonを実装済み |
| 非一様メッシュ | 既存 | 距離適応メッシュと停止境界分割あり |
| メッシュ収束試験 | 既存 | `scripts/run_upper_mesh_convergence.py` を使用 |
| 多シナリオCEM | 今回強化 | 3ケースから7ケースへ拡張 |
| 分散・CVaR | 今回実装 | 有限重み付き経験分布として実装 |
| chance constraint | 今回実装 | 外側シナリオ失敗確率ゲート。内側確率制約ではない |
| 停止時間不確実性 | 未実装 | stop YAMLの複製シナリオ生成が必要 |
| ドライバー追従誤差 | 今回強化 | 1 Hz execution modelに加え、driver_lagシナリオを追加 |
| 状態偏差イベント再計画 | 今回実装 | SoC、Tb、停止解除、既存の予報・距離・時間を使用 |
| 安全fallback | 既存・要継続検証 | solver fallback、速度制限、SoC guardを維持 |
| Pareto集合 | 未実装 | 単一スコア確定前に導入すると選択責任が曖昧になる |
| 独立モデル検証後に学習を昇格 | 今回強化 | モデル検証不合格なら目的関数ゲートも不合格 |

## 8. 「完全自動設計」と呼ばない理由

現在のCEMは候補項の重みを自動探索するが、次は人間の設計として残る。

1. 完走時間、終端SoC、安全余裕、快適性の優先順位。
2. どの状態・外乱をシナリオに含めるか。
3. 各シナリオの重みと失敗許容確率。
4. hard constraintとsoft preferenceの境界。
5. モデル誤差とセンサ故障時の独立安全動作。

従って名称は「人間が定義した外側価値に対する、スパース多シナリオ目的関数探索」が正確である。

## 9. 残る優先作業

1. 過去ログと予報誤差から、日射・風・弱電・走行遅れの確率分布と相関を校正する。
2. 停止時間を短・中・長の分岐シナリオとして自動生成する。
3. SoC、進捗、温度、予報クラスタごとのtop-K warm-start libraryを作る。
4. OOD距離が大きい場合は学習初期値を拒否し、balance/safe seedへ戻す。
5. 目的項を無次元化し、Group Lasso又はstability selectionをholdoutで評価する。
6. 多目的Pareto前線を出し、人間が本番のトレードオフ点を承認する。
7. 全hard constraintを内側ソルバの明示制約へ移す設計を、計算時間と可解性込みで検証する。

## 10. 検証結果

今回追加した単体試験:

```text
tests/test_mpc_objective_design.py: 8 passed
```

既存の上位policy/horizon/solver関連:

```text
tests/test_identification_and_upper_solver.py:
104 passed
```

ROSパッケージ構成試験は一括実行で27件通過後にPythonの一時的な `MemoryError` が発生した。
失敗したAST監査を新規プロセスで単独再実行した後、メモリアロケータを固定して全体を再実行し、
`28 passed` を確認した。変更対象5ファイルは `py_compile` を通過している。

全テストからPyTorch必須の磁気カプラ形状試験を除いた実行では `201 passed, 2 skipped` まで
進み、別の磁気カプラ試験1件だけが `magpylib` 未導入で失敗した。ソーラーカー対象の失敗はない。

実車・全レースの性能改善率は、車両ごとの入力資産とGPU campaignを使った再計測前には断定
しない。本変更はまず誤ったwarm startと危険な候補昇格を防ぐものであり、速度向上値そのものを
保証するものではない。

## 11. 一次資料

- Brandon Amos et al., “Differentiable MPC for End-to-end Planning and Control”  
  https://arxiv.org/abs/1810.13400
- Rajiv Sambharya et al., “Learning to Warm-Start Fixed-Point Optimization Algorithms,” JMLR 25, 2024  
  https://www.jmlr.org/papers/v25/23-1174.html
- M. Diehl et al., “A Real-Time Iteration Scheme for Nonlinear Optimization in Optimal Feedback Control,” 2005  
  https://epubs.siam.org/doi/10.1137/S0363012902400713
- “A Sufficient Condition for Stability of Sampled-data MPC using Adaptive Time-mesh Refinement,” IFAC 2018  
  https://www.sciencedirect.com/science/article/pii/S2405896318326545
- R. T. Rockafellar and S. Uryasev, CVaR optimization formulation  
  https://optimization-online.org/2016/07/5536/
