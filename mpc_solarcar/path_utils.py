import os
from ament_index_python.packages import get_package_share_directory


PKG_NAME = 'mpc_solarcar'


def resolve_path(path: str, default_subdir: str = '') -> str:
    """Resolve a path relative to CWD or package share.

    - If absolute, return as-is.
    - If exists relative to CWD, return it.
    - Otherwise, resolve under <pkg_share>/<default_subdir> (or directly under share).
    """
    if path is None:
        return path
    path = os.path.expanduser(str(path))
    if os.path.isabs(path):
        return path
    if os.path.exists(path):
        return path
    pkg_share = get_package_share_directory(PKG_NAME)
    if default_subdir:
        subdir = default_subdir.strip('/\\')
        if path.startswith(subdir + os.sep) or path == subdir:
            return os.path.join(pkg_share, path)
        return os.path.join(pkg_share, subdir, path)
    return os.path.join(pkg_share, path)
