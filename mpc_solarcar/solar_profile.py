import os
from typing import Any, Dict, Tuple

import yaml

from .path_utils import resolve_path


def load_profile(profile_yaml: str) -> Tuple[str, Dict[str, Any]]:
    """Load a unified solar workflow profile YAML."""
    resolved = resolve_path(profile_yaml, 'config')
    with open(resolved, 'r', encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise ValueError(f'Profile YAML must be a mapping: {resolved}')
    return os.path.abspath(resolved), cfg


def get_section(cfg: Dict[str, Any], name: str) -> Dict[str, Any]:
    value = cfg.get(name, {})
    return value if isinstance(value, dict) else {}


def get_value(cfg: Dict[str, Any], section: str, key: str, default: Any = None) -> Any:
    return get_section(cfg, section).get(key, default)


def merged_dict(*parts: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for part in parts:
        if isinstance(part, dict):
            merged.update(part)
    return merged


def resolve_profile_asset(profile_yaml: str, asset_path: str) -> str:
    if asset_path is None:
        return ''
    raw = os.path.expanduser(str(asset_path)).strip()
    if not raw:
        return ''
    if os.path.isabs(raw):
        return raw

    profile_dir = os.path.dirname(os.path.abspath(profile_yaml))
    candidate = os.path.normpath(os.path.join(profile_dir, raw))
    if os.path.exists(candidate):
        return candidate
    if os.path.exists(raw):
        return os.path.abspath(raw)
    return resolve_path(raw)


def get_path(cfg: Dict[str, Any], profile_yaml: str, key: str, default: str = '') -> str:
    return resolve_profile_asset(profile_yaml, get_value(cfg, 'paths', key, default))

