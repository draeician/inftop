"""Sparkline scaling, anchors, and history span formatting."""

from __future__ import annotations

import unittest

from inftop.sparkline import Ring, format_history_span, spark, spark_stats
from inftop.ui import render_lines


class TestSpark(unittest.TestCase):
    def test_scales_to_own_min_max(self):
        # Flat mid values should use full bar range against own lo/hi.
        s = spark([10.0, 20.0, 30.0], width=3)
        self.assertEqual(len(s), 3)
        self.assertEqual(s[0], "▁")
        self.assertEqual(s[-1], "█")

    def test_spark_stats_current_min_max(self):
        cur, lo, hi = spark_stats([10.0, 5.0, 20.0, None])
        self.assertEqual(cur, 20.0)
        self.assertEqual(lo, 5.0)
        self.assertEqual(hi, 20.0)

    def test_spark_stats_empty(self):
        cur, lo, hi = spark_stats([])
        self.assertIsNone(cur)
        self.assertIsNone(lo)
        self.assertIsNone(hi)


class TestHistorySpan(unittest.TestCase):
    def test_two_minutes(self):
        self.assertEqual(format_history_span(120), "last 2m")

    def test_seconds(self):
        self.assertEqual(format_history_span(45), "last 45s")

    def test_mixed(self):
        self.assertEqual(format_history_span(90), "last 1m30s")


class TestSparkRender(unittest.TestCase):
    def test_render_shows_anchors_and_span(self):
        snap = {
            "host": {"hostname": "gpu-box", "uptime": "1d", "loadavg": [0.1]},
            "gpu": {
                "card": "card0",
                "busy_percent": 50.0,
                "vram_used": 0,
                "vram_total": 1,
                "gtt_used": 0,
                "gtt_total": 1,
                "temp_c": 40.0,
                "power_w": 25.0,
                "sclk_mhz": 1000.0,
                "activity": "idle",
            },
            "strata_health": {"ok": True, "model": "m", "max_context": 1},
            "active": [],
            "recent": [],
            "clients": [],
            "alerts": [],
            "errors": [],
            "sparklines": {
                "busy": [40.0, 50.0, 60.0],
                "power": [20.0, 25.0, 30.0],
                "decode": [10.0, 20.0, 40.0],
            },
            "sparkline_span_s": 120,
            "ollama": None,
        }
        blob = "\n".join(render_lines(snap, width=120))
        self.assertIn("last 2m", blob)
        self.assertRegex(blob, r"busy\s+.*cur 60\.0%.*min 40\.0%.*max 60\.0%")
        self.assertRegex(blob, r"power\s+.*cur 30\.0W.*min 20\.0W.*max 30\.0W")
        self.assertRegex(blob, r"tok/s\s+.*cur 40\.0/s.*min 10\.0/s.*max 40\.0/s")


class TestRing(unittest.TestCase):
    def test_capacity(self):
        r = Ring(3)
        for v in (1.0, 2.0, 3.0, 4.0):
            r.push(v)
        self.assertEqual(r.values, [2.0, 3.0, 4.0])


if __name__ == "__main__":
    unittest.main()
