"""Parse host-side ss output for Strata client connections."""

from __future__ import annotations

import re
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

_ADDR = re.compile(
    r"(?P<lip>\d+\.\d+\.\d+\.\d+|[0-9a-fA-F:]+):(?P<lport>\d+)\s+"
    r"(?P<rip>\d+\.\d+\.\d+\.\d+|[0-9a-fA-F:]+):(?P<rport>\d+)"
)


def parse_ss_output(text: str, listen_port: int = 8080) -> list[dict[str, Any]]:
    """Extract remote peers connected to local listen_port."""
    peers: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _ADDR.search(line)
        if not m:
            continue
        lport = int(m.group("lport"))
        rport = int(m.group("rport"))
        lip = m.group("lip")
        rip = m.group("rip")
        if lport == listen_port:
            peers.append({"ip": rip, "port": rport, "local": f"{lip}:{lport}"})
        elif rport == listen_port:
            peers.append({"ip": lip, "port": lport, "local": f"{rip}:{rport}"})
    return peers


def _default_resolve(ip: str, timeout: float = 0.5) -> str | None:
    result: list[str | None] = [None]

    def worker() -> None:
        try:
            host, _, _ = socket.gethostbyaddr(ip)
            result[0] = host
        except OSError:
            result[0] = None

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(timeout)
    return result[0]


class ConnectionTracker:
    """Track peers over time with cached reverse DNS."""

    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        resolve: Callable[[str], str | None] | None = None,
        dns_timeout: float = 0.5,
    ) -> None:
        self._clock = clock or time.time
        self._dns_timeout = dns_timeout
        self._resolve = resolve
        self._by_ip: dict[str, dict[str, Any]] = {}
        self._dns_cache: dict[str, str | None] = {}

    def _lookup(self, ip: str) -> str | None:
        if ip in self._dns_cache:
            return self._dns_cache[ip]
        if self._resolve is not None:
            host = self._resolve(ip)
        else:
            host = _default_resolve(ip, self._dns_timeout)
        self._dns_cache[ip] = host
        return host

    def update(self, peers: list[dict[str, Any]]) -> None:
        now = self._clock()
        open_counts: dict[str, int] = {}
        for p in peers:
            open_counts[p["ip"]] = open_counts.get(p["ip"], 0) + 1

        for ip, count in open_counts.items():
            row = self._by_ip.get(ip)
            if row is None:
                row = {
                    "ip": ip,
                    "hostname": self._lookup(ip),
                    "open_conns": count,
                    "first_seen": now,
                    "last_seen": now,
                    "requests": 0,
                }
                self._by_ip[ip] = row
            else:
                row["open_conns"] = count
                row["last_seen"] = now

        for ip, row in list(self._by_ip.items()):
            if ip not in open_counts:
                row["open_conns"] = 0

    def note_request(self, ips: list[str]) -> None:
        for ip in ips:
            row = self._by_ip.get(ip)
            if row is None:
                row = {
                    "ip": ip,
                    "hostname": self._lookup(ip),
                    "open_conns": 0,
                    "first_seen": self._clock(),
                    "last_seen": self._clock(),
                    "requests": 0,
                }
                self._by_ip[ip] = row
            row["requests"] += 1

    def current_ips(self) -> list[str]:
        return [ip for ip, r in self._by_ip.items() if r["open_conns"] > 0]

    def summary(self) -> list[dict[str, Any]]:
        return sorted(self._by_ip.values(), key=lambda r: (-r["open_conns"], r["ip"]))
