"""GPU activity indicator (rule B)."""

from __future__ import annotations

import unittest

from inftop.activity import gpu_activity
from inftop.ui import render_lines


class TestGpuActivity(unittest.TestCase):
    def test_busy_when_active_requests(self):
        self.assertEqual(
            gpu_activity(active_count=1, power_w=12.0, power_history=[10.0, 12.0]),
            "busy",
        )

    def test_idle_near_rolling_min(self):
        # power within 5 W of min over history, no active requests
        hist = [30.0, 28.0, 32.0, 29.0]
        self.assertEqual(
            gpu_activity(active_count=0, power_w=31.0, power_history=hist),
            "idle",
        )

    def test_busy_when_power_above_band(self):
        hist = [10.0, 11.0, 12.0, 50.0]
        self.assertEqual(
            gpu_activity(active_count=0, power_w=50.0, power_history=hist),
            "busy",
        )

    def test_idle_when_no_power_data(self):
        self.assertEqual(
            gpu_activity(active_count=0, power_w=None, power_history=[]),
            "idle",
        )

    def test_render_shows_activity_next_to_busy(self):
        snap = {
            "host": {"hostname": "h", "uptime": "1", "loadavg": []},
            "gpu": {
                "card": "card0",
                "busy_percent": 100.0,
                "activity": "idle",
                "vram_used": 0,
                "vram_total": 1,
                "gtt_used": 0,
                "gtt_total": 1,
                "temp_c": 40,
                "power_w": 20,
                "sclk_mhz": 1000,
            },
            "strata_health": {"ok": True},
            "active": [],
            "recent": [],
            "clients": [],
            "alerts": [],
            "errors": [],
            "sparklines": {},
            "ollama": None,
        }
        blob = "\n".join(render_lines(snap))
        self.assertRegex(blob, r"busy\s+100%\s+idle")


if __name__ == "__main__":
    unittest.main()
