"""Load Strata API key without ever printing it."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def _mode_too_open(mode: int) -> bool:
    """True if group/other have any bits (looser than owner-only)."""
    return bool(stat.S_IMODE(mode) & 0o077)


def load_strata_api_key(
    env: dict[str, str] | None = None,
    api_key_file: str | Path | None = None,
    *,
    env_file: str | Path | None = None,
) -> str | None:
    """Return API key from STRATA_API_KEY or a chmod-600 (or stricter) file.

    ``env_file`` is accepted as a deprecated alias of ``api_key_file``.
    Refuses a key file with group/other permissions. Never logs the key.
    """
    env = env if env is not None else os.environ
    key = env.get("STRATA_API_KEY", "").strip()
    if key:
        return key

    path_raw = api_key_file if api_key_file is not None else env_file
    if path_raw is None:
        return None
    path = Path(path_raw).expanduser()
    if not path.is_file():
        return None
    mode = path.stat().st_mode
    if _mode_too_open(mode):
        raise PermissionError(
            f"{path} must be chmod 600 or stricter "
            f"(got {oct(stat.S_IMODE(mode))})"
        )
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("STRATA_API_KEY="):
            val = line.split("=", 1)[1].strip().strip("'\"")
            return val or None
        return line
    return None
