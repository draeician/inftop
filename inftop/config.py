"""Load ~/.config/inftop/config.toml (XDG) and resolve settings precedence."""

from __future__ import annotations

import os
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Sentinel: display times in the process local timezone.
SYSTEM_LOCAL_TZ = "local"

DEFAULTS: dict[str, Any] = {
    "strata_url": "http://127.0.0.1:8080",
    "remote_host": None,
    "tz": SYSTEM_LOCAL_TZ,
    "interval": 1.0,
    "history_window": 120,
    "ollama_url": "http://127.0.0.1:11434",
    "container_name": "strata",
    "api_key_file": None,
    "alerts": {
        "temp_c": 90.0,
        "vram_pct": 95.0,
        "stall_s": 30.0,
    },
}

EXAMPLE_TOML = """\
# inftop configuration (TOML)
# Precedence: CLI flag > env (INFTOP_STRATA_URL, INFTOP_REMOTE, INFTOP_TZ,
# STRATA_API_KEY) > this file > built-in defaults.
#
# Uncomment and edit as needed.

# strata_url = "http://127.0.0.1:8080"
# remote_host = "gpu-box"
# tz = "UTC"                    # omit or "local" for system local timezone
# interval = 1.0                # refresh seconds (-d)
# history_window = 120          # sparkline samples
# ollama_url = "http://127.0.0.1:11434"
# container_name = "strata"
# api_key_file = "~/.config/inftop/api_key"  # must be chmod 600 (or stricter)

# [alerts]
# temp_c = 90
# vram_pct = 95
# stall_s = 30
"""


def config_dir(env: dict[str, str] | None = None) -> Path:
    env = env if env is not None else os.environ
    xdg = env.get("XDG_CONFIG_HOME", "").strip()
    if xdg:
        return Path(xdg) / "inftop"
    home = env.get("HOME") or str(Path.home())
    return Path(home) / ".config" / "inftop"


def config_path(env: dict[str, str] | None = None) -> Path:
    return config_dir(env) / "config.toml"


def load_config_file(path: Path | None = None) -> dict[str, Any]:
    """Parse config.toml; return {} if missing. Unknown keys ignored later."""
    path = path if path is not None else config_path()
    if not path.is_file():
        return {}
    with path.open("rb") as f:
        data = tomllib.load(f)
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for key in (
        "strata_url",
        "remote_host",
        "tz",
        "interval",
        "history_window",
        "ollama_url",
        "container_name",
        "api_key_file",
    ):
        if key in data and data[key] is not None:
            out[key] = data[key]
    alerts = data.get("alerts")
    if isinstance(alerts, dict):
        out["alerts"] = {
            k: alerts[k]
            for k in ("temp_c", "vram_pct", "stall_s")
            if k in alerts and alerts[k] is not None
        }
    return out


def init_config(path: Path | None = None, *, force: bool = False) -> bool:
    """Write commented example config. Refuse overwrite unless force."""
    path = path if path is not None else config_path()
    if path.exists() and not force:
        raise FileExistsError(f"{path} already exists (use --force to overwrite)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(EXAMPLE_TOML, encoding="utf-8")
    return True


def listen_port_from_url(url: str, default: int = 8080) -> int:
    try:
        port = urlparse(url).port
        return int(port) if port is not None else default
    except (TypeError, ValueError):
        return default


def resolve_settings(
    cli: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge CLI > env > config > defaults into a flat settings dict.

    cli keys mirror argparse: strata_url, remote, tz, d (interval).
    None / omitted means “not set by this layer”.
    """
    cli = cli or {}
    env = env if env is not None else os.environ
    config = config or {}

    out = deepcopy(DEFAULTS)
    cfg_alerts = config.get("alerts") if isinstance(config.get("alerts"), dict) else {}
    out["alerts"].update(cfg_alerts)

    for key in (
        "strata_url",
        "remote_host",
        "tz",
        "interval",
        "history_window",
        "ollama_url",
        "container_name",
        "api_key_file",
    ):
        if key in config and config[key] is not None:
            out[key] = config[key]

    if env.get("INFTOP_STRATA_URL", "").strip():
        out["strata_url"] = env["INFTOP_STRATA_URL"].strip()
    if env.get("INFTOP_REMOTE", "").strip():
        out["remote_host"] = env["INFTOP_REMOTE"].strip()
    if env.get("INFTOP_TZ", "").strip():
        out["tz"] = env["INFTOP_TZ"].strip()

    if cli.get("strata_url") is not None:
        out["strata_url"] = cli["strata_url"]
    if cli.get("remote") is not None:
        out["remote_host"] = cli["remote"]
    if cli.get("tz") is not None:
        out["tz"] = cli["tz"]
    if cli.get("d") is not None:
        out["interval"] = float(cli["d"])

    if isinstance(out.get("api_key_file"), str):
        out["api_key_file"] = str(Path(out["api_key_file"]).expanduser())

    out["listen_port"] = listen_port_from_url(str(out["strata_url"]))
    return out
