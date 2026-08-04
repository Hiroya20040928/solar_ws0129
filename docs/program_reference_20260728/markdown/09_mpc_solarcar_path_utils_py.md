# 09. ROS share / 相対パス解決

- ファイル: `mpc_solarcar/path_utils.py`
- 種別: `Python`
- 区分: `config`

## 役割

CWD、package share、repo root をまたいで path を実在ファイルへ解決する小さな基盤。

## 起動文脈

- 起動文脈: Node 実行時の path ぶれを吸収する補助モジュール。
- 呼び出し元: `mpc_node.py`, `gps_sim_node.py`, `solar_state_node.py`
- 次に読むべきファイル: `mpc_solarcar/solar_profile.py`

## 主要ポイント

- ament の package share があればそちらを優先する。
- インストール後の launch/node 実行でも同じ relative path を使えるようにする。

## 主要構造

主要関数は resolve_path。

## ファイルを上から読んだときの定義順

- L4: 例外処理を伴う try ブロックを実行する。
- L10: PKG_NAME に 'mpc_solarcar' の結果を代入する。
- L11: REPO_ROOT に Path(__file__).resolve().parents[1] の結果を代入する。
- L14: 関数 resolve_path を定義する。

## import 群

- L1: `import os`
  - パス、環境変数、プロセス外部状態を扱うため。 このファイル内での主な使用位置は L23, L24, L26, L31, L34, L35, L36, L37。
- L2: `from pathlib import Path`
  - ファイルやディレクトリを安全に扱うため。 このファイル内での主な使用位置は L11。
- L5: `from ament_index_python.packages import get_package_share_directory`
  - ament_index_python.packages から get_package_share_directory を読み込み、このファイルの処理を組み立てるため。 このファイル内での主な使用位置は L7, L28, L29。

## 関数・クラスを上から順に解説

### L14 関数 `resolve_path`

- 定義: `resolve_path(path, default_subdir)`
- docstring: Resolve a path relative to CWD or package share.

- If absolute, return as-is.
- If exists relative to CWD, return it.
- Otherwise, resolve under <pkg_share>/<default_subdir> (or directly under share).
- このブロックが直接呼ぶ主な関数/メソッド: `exists`, `expanduser`, `fspath`, `get_package_share_directory`, `isabs`, `join`, `startswith`, `str`, `strip`
- 戻り値の要点: `os.path.join(pkg_share, path) / path / path / path`
- 上から順の処理:
  1. 条件 path is None を判定し、真なら内部処理を行う。
  2. path に os.path.expanduser(str(path)) の結果を代入する。
  3. 条件 os.path.isabs(path) を判定し、真なら内部処理を行う。
  4. 条件 os.path.exists(path) を判定し、真なら内部処理を行う。
  5. 条件 get_package_share_directory is not None を判定し、真なら内部処理を行う。
  6. 条件 default_subdir を判定し、真なら内部処理を行う。
  7. os.path.join(pkg_share, path) を返す。


## 処理の流れ

1. ソース中の主要関数を通じて処理を進める。
