import os
from typing import Any, Dict, Tuple

import yaml                                                        # [設定処理] プロファイル・設定ファイル読込用 PyYAML ライブラリのインポート

from .path_utils import resolve_path


def load_profile(profile_yaml: str) -> Tuple[str, Dict[str, Any]]:  # [関数定義] load_profile の処理実行ブロック
    """Load a unified solar workflow profile YAML."""
    resolved = resolve_path(profile_yaml, 'config')
    with open(resolved, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f'Profile YAML must be a mapping: {resolved}')
    return os.path.abspath(resolved), cfg                          # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_section(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:  # [関数定義] get_section の処理実行ブロック
    value = cfg.get(name, {})
    return value if isinstance(value, dict) else {}                # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_value(cfg: Dict[str, Any], section: str, key: str, default: Any = None) -> Any:  # [関数定義] get_value の処理実行ブロック
    return get_section(cfg, section).get(key, default)             # [戻り値] 計算結果・計算状態の呼び出し元への返却


def merged_dict(*parts: Dict[str, Any]) -> Dict[str, Any]:         # [関数定義] merged_dict の処理実行ブロック
    merged: Dict[str, Any] = {}
    for part in parts:
        if isinstance(part, dict):
            merged.update(part)
    return merged                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却


def resolve_profile_asset(profile_yaml: str, asset_path: str) -> str:  # [関数定義] resolve_profile_asset の処理実行ブロック
    if asset_path is None:
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    raw = os.path.expanduser(str(asset_path)).strip()
    if not raw:
        return ''                                                  # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.isabs(raw):
        return raw                                                 # [戻り値] 計算結果・計算状態の呼び出し元への返却

    profile_dir = os.path.dirname(os.path.abspath(profile_yaml))
    candidate = os.path.normpath(os.path.join(profile_dir, raw))
    if os.path.exists(candidate):
        return candidate                                           # [戻り値] 計算結果・計算状態の呼び出し元への返却
    if os.path.exists(raw):
        return os.path.abspath(raw)                                # [戻り値] 計算結果・計算状態の呼び出し元への返却
    return resolve_path(raw)                                       # [戻り値] 計算結果・計算状態の呼び出し元への返却


def get_path(cfg: Dict[str, Any], profile_yaml: str, key: str, default: str = '') -> str:  # [関数定義] get_path の処理実行ブロック
    return resolve_profile_asset(profile_yaml, get_value(cfg, 'paths', key, default))  # [戻り値] 計算結果・計算状態の呼び出し元への返却

