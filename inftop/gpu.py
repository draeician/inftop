"""AMD GPU stats from sysfs (and optional slow rocm-smi)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _first_hwmon(device: Path) -> Path | None:
    hwmon = device / "hwmon"
    if not hwmon.is_dir():
        return None
    for child in sorted(hwmon.iterdir()):
        if child.name.startswith("hwmon"):
            return child
    return None


def discover_cards(sysfs_root: str = "/sys/class/drm") -> list[Path]:
    root = Path(sysfs_root)
    if not root.is_dir():
        return []
    cards: list[Path] = []
    for entry in sorted(root.iterdir()):
        name = entry.name
        if name.startswith("card") and name[4:].isdigit():
            device = entry / "device"
            if device.is_dir():
                cards.append(entry)
    return cards


def read_gpu(
    sysfs_root: str = "/sys/class/drm",
    card_name: str | None = None,
) -> dict[str, Any]:
    """Read GPU busy%, memory, temp, power, sclk from sysfs. Tolerate missing files."""
    cards = discover_cards(sysfs_root)
    if not cards:
        return {"card": None, "error": "no drm cards found"}

    card = cards[0]
    if card_name:
        for c in cards:
            if c.name == card_name:
                card = c
                break

    device = card / "device"
    hw = _first_hwmon(device)

    busy = _read_int(device / "gpu_busy_percent")
    vram_used = _read_int(device / "mem_info_vram_used") or 0
    vram_total = _read_int(device / "mem_info_vram_total") or 0
    gtt_used = _read_int(device / "mem_info_gtt_used") or 0
    gtt_total = _read_int(device / "mem_info_gtt_total") or 0

    temp_c = None
    power_w = None
    sclk_mhz = None
    voltage_mv = None
    if hw:
        t = _read_int(hw / "temp1_input")
        if t is not None:
            temp_c = t / 1000.0
        p = _read_int(hw / "power1_average")
        if p is None:
            p = _read_int(hw / "power1_input")
        if p is not None:
            power_w = p / 1_000_000.0
        f = _read_int(hw / "freq1_input")
        if f is not None:
            sclk_mhz = f / 1_000_000.0
        v = _read_int(hw / "in0_input")
        if v is not None:
            voltage_mv = float(v)

    return {
        "card": card.name,
        "busy_percent": float(busy) if busy is not None else None,
        "vram_used": vram_used,
        "vram_total": vram_total,
        "gtt_used": gtt_used,
        "gtt_total": gtt_total,
        "temp_c": temp_c,
        "power_w": power_w,
        "sclk_mhz": sclk_mhz,
        "voltage_mv": voltage_mv,
    }


class RocmSmiCache:
    """Poll rocm-smi at most every 5 seconds (optional enrichment)."""

    def __init__(self, runner=None, min_interval: float = 5.0) -> None:
        self._runner = runner
        self._min_interval = min_interval
        self._last_t = 0.0
        self._last: dict[str, Any] | None = None

    def get(self) -> dict[str, Any] | None:
        now = time.monotonic()
        if self._last is not None and (now - self._last_t) < self._min_interval:
            return self._last
        data = self._poll()
        self._last_t = now
        self._last = data
        return data

    def _poll(self) -> dict[str, Any] | None:
        if self._runner is None:
            import subprocess

            def runner(cmd: list[str]) -> str:
                try:
                    r = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        timeout=8,
                        check=False,
                    )
                    return r.stdout if r.returncode == 0 else ""
                except (OSError, subprocess.TimeoutExpired):
                    return ""

            self._runner = runner

        out = self._runner(
            [
                "rocm-smi",
                "--showuse",
                "--showmemuse",
                "--showpower",
                "--showtemp",
                "--json",
            ]
        )
        if not out.strip():
            return None
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return None
