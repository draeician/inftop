"""UI alerts for temp, VRAM, stalled requests, disconnects."""

from __future__ import annotations

import time
from typing import Any


def evaluate_alerts(
    gpu: dict[str, Any],
    active: list[dict[str, Any]],
    recent_finished: list[dict[str, Any]],
    now: float | None = None,
    stall_s: float = 30.0,
    temp_c: float = 90.0,
    vram_pct: float = 95.0,
) -> list[str]:
    now = now if now is not None else time.time()
    alerts: list[str] = []

    temp = gpu.get("temp_c")
    if temp is not None and temp > temp_c:
        alerts.append(f"TEMP {temp:.0f}°C > {temp_c:.0f}")

    used = gpu.get("vram_used") or 0
    total = gpu.get("vram_total") or 0
    if total > 0 and (used / total) > (vram_pct / 100.0):
        pct = 100.0 * used / total
        alerts.append(f"VRAM {pct:.0f}% > {vram_pct:.0f}%")

    for req in active:
        last = req.get("last_progress_at")
        if last is None:
            last = req.get("started_at")
        if last is None:
            last = now
        if now - last >= stall_s:
            alerts.append(f"STALLED request ({now - last:.0f}s no progress)")

    for req in recent_finished[-5:]:
        if req.get("finish_reason") == "disconnect" and not req.get("_alerted"):
            alerts.append("DISCONNECT finish")
            req["_alerted"] = True

    return alerts
