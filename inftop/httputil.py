"""Minimal urllib helpers (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


def http_get_json(
    url: str,
    headers: dict[str, str] | None = None,
    timeout: float = 2.0,
) -> tuple[Any | None, str | None]:
    """GET JSON. Returns (data, error_message). Never raises."""
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if not body.strip():
                return {}, None
            return json.loads(body), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return None, str(e.reason)
    except (TimeoutError, json.JSONDecodeError, OSError) as e:
        return None, str(e)
