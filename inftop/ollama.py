"""Ollama /api/ps and /api/version probes."""

from __future__ import annotations

from typing import Any, Callable

from inftop.httputil import http_get_json


def read_ollama(
    base_url: str = "http://127.0.0.1:11434",
    getter: Callable[..., tuple[Any | None, str | None]] | None = None,
) -> dict[str, Any] | None:
    """Return ollama info or None if unreachable (section should be hidden)."""
    get = getter or http_get_json
    ver, err = get(f"{base_url.rstrip('/')}/api/version", timeout=1.5)
    if err:
        return None
    ps, _ = get(f"{base_url.rstrip('/')}/api/ps", timeout=1.5)
    models = []
    if isinstance(ps, dict):
        for m in ps.get("models") or []:
            models.append(
                {
                    "name": m.get("name") or m.get("model"),
                    "size": m.get("size"),
                    "size_vram": m.get("size_vram"),
                    "expires_at": m.get("expires_at"),
                }
            )
    version = ver.get("version") if isinstance(ver, dict) else None
    return {"version": version, "models": models}
