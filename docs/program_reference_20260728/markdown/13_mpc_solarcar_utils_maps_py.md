# 13. 効率マップ・抵抗マップ読込補間

- ファイル: `mpc_solarcar/utils_maps.py`
- 種別: `Python`
- 区分: `model helper`

## 役割

CSV で持つ drive/regen efficiency、Rint、OCV などを読み、補間可能な配列へ変換する。

## 起動文脈

- 起動文脈: SolarCarModel の map backend。
- 呼び出し元: `mpc_solarcar/model.py`
- 次に読むべきファイル: 特になし

## 主要ポイント

- read_eff_map、read_Rint_map、read_map、read_1d_map が入口。
- bilinear_interp が 2D 補間の核。

## 主要構造

主要関数は bilinear_interp, read_eff_map, read_Rint_map, read_map, read_1d_map。

## ファイルを上から読んだときの定義順

- L3: 関数 bilinear_interp を定義する。
- L13: 関数 read_eff_map を定義する。
- L16: 関数 read_Rint_map を定義する。
- L20: 関数 read_map を定義する。
- L24: 関数 read_1d_map を定義する。

## import 群

- L1: `import numpy as np`
  - 数値配列、clip、補間、統計計算を行うため。 このファイル内での主な使用位置は L4, L5, L6, L7。
- L2: `import pandas as pd`
  - CSV や時刻列の読込・整形・再サンプリングに使うため。 このファイル内での主な使用位置は L14, L17, L21, L25, L30。

## 関数・クラスを上から順に解説

### L3 関数 `bilinear_interp`

- 定義: `bilinear_interp(xg, yg, Z, x, y)`
- このブロックが直接呼ぶ主な関数/メソッド: `asarray`, `clip`, `len`, `searchsorted`
- 戻り値の要点: `(1 - wx) * (1 - wy) * Z00 + wx * (1 - wy) * Z10 + (1 - wx) * wy * Z01 + wx * wy * Z11`
- 上から順の処理:
  1. xg に np.asarray(xg) の結果を代入する。
  2. yg に np.asarray(yg) の結果を代入する。
  3. Z に np.asarray(Z) の結果を代入する。
  4. x に np.clip(x, xg[0], xg[-1]) の結果を代入する。
  5. y に np.clip(y, yg[0], yg[-1]) の結果を代入する。
  6. i に np.searchsorted(xg, x) - 1 の結果を代入する。
  7. i に np.clip(i, 0, len(xg) - 2) の結果を代入する。
  8. j に np.searchsorted(yg, y) - 1 の結果を代入する。
  9. j に np.clip(j, 0, len(yg) - 2) の結果を代入する。
  10. (x0, x1) に (xg[i], xg[i + 1]) の結果を代入する。

### L13 関数 `read_eff_map`

- 定義: `read_eff_map(path)`
- このブロックが直接呼ぶ主な関数/メソッド: `astype`, `read_csv`
- 戻り値の要点: `(df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float))`
- 上から順の処理:
  1. df に pd.read_csv(path, index_col=0) の結果を代入する。
  2. (df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)) を返す。

### L16 関数 `read_Rint_map`

- 定義: `read_Rint_map(path)`
- このブロックが直接呼ぶ主な関数/メソッド: `astype`, `read_csv`
- 戻り値の要点: `(df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float))`
- 上から順の処理:
  1. df に pd.read_csv(path, index_col=0) の結果を代入する。
  2. (df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)) を返す。

### L20 関数 `read_map`

- 定義: `read_map(path)`
- このブロックが直接呼ぶ主な関数/メソッド: `astype`, `read_csv`
- 戻り値の要点: `(df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float))`
- 上から順の処理:
  1. df に pd.read_csv(path, index_col=0) の結果を代入する。
  2. (df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)) を返す。

### L24 関数 `read_1d_map`

- 定義: `read_1d_map(path)`
- このブロックが直接呼ぶ主な関数/メソッド: `astype`, `read_csv`
- 戻り値の要点: `(x, y) / (x, y)`
- 上から順の処理:
  1. df に pd.read_csv(path) の結果を代入する。
  2. 条件 df.shape[1] >= 2 を判定し、真なら内部処理を行う。
  3. df に pd.read_csv(path, index_col=0) の結果を代入する。
  4. x に df.index.values.astype(float) の結果を代入する。
  5. y に df.iloc[:, 0].values.astype(float) の結果を代入する。
  6. (x, y) を返す。


## 処理の流れ

1. ソース中の主要関数を通じて処理を進める。
