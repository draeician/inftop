"""Host load, memory, CPU, swap, uptime from /proc."""

from __future__ import annotations

import os
import time
from typing import Any


def _read_meminfo(path: str = "/proc/meminfo") -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0].endswith(":"):
                    key = parts[0][:-1]
                    try:
                        out[key] = int(parts[1])  # kB
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def _parse_stat_cpu_line(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    line = text.splitlines()[0] if text else ""
    if not line.startswith("cpu "):
        return None
    try:
        fields = [int(x) for x in line.split()[1:]]
        total = sum(fields)
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        return total, idle
    except (ValueError, IndexError):
        return None


def _read_stat_cpu(path: str = "/proc/stat") -> tuple[int, int] | None:
    try:
        with open(path, encoding="utf-8") as f:
            return _parse_stat_cpu_line(f.readline())
    except OSError:
        return None


def cpu_percent_from_samples(
    prev: tuple[int, int], cur: tuple[int, int]
) -> float:
    """Busy % from two (total, idle) /proc/stat samples."""
    dt = cur[0] - prev[0]
    di = cur[1] - prev[1]
    if dt <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (1.0 - di / dt)))


class CpuSampler:
    """Two-sample CPU% from /proc/stat (local path or injectable reader)."""

    def __init__(
        self,
        path: str = "/proc/stat",
        read_fn=None,
    ) -> None:
        self._path = path
        self._read_fn = read_fn
        self._prev = self._sample()

    def _sample(self) -> tuple[int, int] | None:
        if self._read_fn is not None:
            try:
                return _parse_stat_cpu_line(self._read_fn())
            except OSError:
                return None
        return _read_stat_cpu(self._path)

    def percent(self) -> float | None:
        cur = self._sample()
        if cur is None or self._prev is None:
            self._prev = cur
            return None
        pct = cpu_percent_from_samples(self._prev, cur)
        self._prev = cur
        return pct


def read_uptime(path: str = "/proc/uptime") -> float | None:
    try:
        with open(path, encoding="utf-8") as f:
            return float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def format_uptime(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    s = int(seconds)
    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    mins, s = divmod(s, 60)
    if days:
        return f"{days}d {hours:02d}:{mins:02d}:{s:02d}"
    return f"{hours:02d}:{mins:02d}:{s:02d}"


def read_host(
    meminfo_path: str = "/proc/meminfo",
    uptime_path: str = "/proc/uptime",
    cpu_sampler: CpuSampler | None = None,
    loadavg_fn=None,
) -> dict[str, Any]:
    mem = _read_meminfo(meminfo_path)
    total = mem.get("MemTotal", 0) * 1024
    avail = mem.get("MemAvailable", mem.get("MemFree", 0)) * 1024
    used = max(0, total - avail) if total else 0
    swap_total = mem.get("SwapTotal", 0) * 1024
    swap_free = mem.get("SwapFree", 0) * 1024
    swap_used = max(0, swap_total - swap_free)

    if loadavg_fn is None:
        try:
            load = list(os.getloadavg())
        except OSError:
            load = []
    else:
        load = list(loadavg_fn())

    cpu = cpu_sampler.percent() if cpu_sampler else None
    up = read_uptime(uptime_path)

    return {
        "hostname": os.uname().nodename,
        "loadavg": load,
        "ram_used": used,
        "ram_total": total,
        "swap_used": swap_used,
        "swap_total": swap_total,
        "cpu_percent": cpu,
        "uptime_s": up,
        "uptime": format_uptime(up),
    }
