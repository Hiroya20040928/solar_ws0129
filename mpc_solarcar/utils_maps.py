import numpy as np                                                 # [数値計算] 行列計算・ベクトル処理用 NumPy ライブラリのインポート
import pandas as pd                                                # [データ処理] 時系列データ解析・表計算用 Pandas ライブラリのインポート
def bilinear_interp(xg, yg, Z, x, y):                              # [関数定義] bilinear_interp の処理実行ブロック
    xg = np.asarray(xg); yg=np.asarray(yg); Z=np.asarray(Z)
    x = np.clip(x, xg[0], xg[-1]); y=np.clip(y, yg[0], yg[-1])
    i = np.searchsorted(xg, x)-1; i=np.clip(i,0,len(xg)-2)
    j = np.searchsorted(yg, y)-1; j=np.clip(j,0,len(yg)-2)
    x0,x1=xg[i],xg[i+1]; y0,y1=yg[j],yg[j+1]
    Z00=Z[i,j]; Z10=Z[i+1,j]; Z01=Z[i,j+1]; Z11=Z[i+1,j+1]
    wx=0 if x1==x0 else (x-x0)/(x1-x0)
    wy=0 if y1==y0 else (y-y0)/(y1-y0)
    return (1-wx)*(1-wy)*Z00 + wx*(1-wy)*Z10 + (1-wx)*wy*Z01 + wx*wy*Z11  # [戻り値] 計算結果・計算状態の呼び出し元への返却
def read_eff_map(path):                                            # [関数定義] read_eff_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却
def read_Rint_map(path):                                           # [関数定義] read_Rint_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

def read_map(path):                                                # [関数定義] read_map の処理実行ブロック
    df = pd.read_csv(path, index_col=0)
    return df.index.values.astype(float), df.columns.values.astype(float), df.values.astype(float)  # [戻り値] 計算結果・計算状態の呼び出し元への返却

def read_1d_map(path):                                             # [関数定義] read_1d_map の処理実行ブロック
    df = pd.read_csv(path)
    if df.shape[1] >= 2:
        x = df.iloc[:, 0].values.astype(float)
        y = df.iloc[:, 1].values.astype(float)
        return x, y                                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    df = pd.read_csv(path, index_col=0)
    x = df.index.values.astype(float)
    y = df.iloc[:, 0].values.astype(float)
    return x, y                                                    # [戻り値] 計算結果・計算状態の呼び出し元への返却
