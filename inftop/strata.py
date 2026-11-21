"""Strata HTTP probes (/health + optional authenticated endpoints)."""

from __future__ import annotations

from typing import Any, Callable

from inftop.httputil import http_get_json

# Generic default; override via --strata-url, INFTOP_STRATA_URL, or config.toml.
DEFAULT_STRATA_URL = "http://127.0.0.1:8080"

AUTH_PATHS = ("/metrics", "/slots", "/props", "/status", "/v1/models")


class StrataClient:
    def __init__(
        self,
        base_url: str = DEFAULT_STRATA_URL,
        api_key: str | None = None,
        getter: Callable[..., tuple[Any | None, str | None]] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._get = getter or http_get_json
        self._auth_ok: list[str] | None = None  # probed once

    def health(self) -> dict[str, Any]:
        data, err = self._get(f"{self.base_url}/health", timeout=2.0)
        if err or not isinstance(data, dict):
            return {"ok": False, "error": err or "bad response"}
        out = {"ok": True, **data}
        return out

    def probe_auth(self) -> dict[str, Any]:
        """Probe authenticated endpoints once; return raw key/values for working ones."""
        if not self.api_key:
            return {}
        if self._auth_ok is not None:
            return self._fetch_known()

        headers = {"Authorization": f"Bearer {self.api_key}"}
        working: list[str] = []
        result: dict[str, Any] = {}
        for path in AUTH_PATHS:
            data, err = self._get(
                f"{self.base_url}{path}", headers=headers, timeout=2.0
            )
            if err is None and data is not None:
                working.append(path)
                result[path] = data
        self._auth_ok = working
        return result

    def _fetch_known(self) -> dict[str, Any]:
        if not self.api_key or not self._auth_ok:
            return {}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        result: dict[str, Any] = {}
        for path in self._auth_ok:
            data, err = self._get(
                f"{self.base_url}{path}", headers=headers, timeout=2.0
            )
            if err is None and data is not None:
                result[path] = data
        return result
