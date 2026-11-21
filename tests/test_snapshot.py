"""JSON snapshot shape tests (no live network required)."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from inftop.collector import snapshot_to_json
from inftop.parser import RequestTracker
from inftop.ui import render_lines


class TestSnapshotJson(unittest.TestCase):
    def test_snapshot_to_json_roundtrip(self):
        snap = {
            "ts": 1.0,
            "host": {"hostname": "gpu-box", "uptime": "01:00:00", "loadavg": [0.1]},
            "gpu": {
                "card": "card0",
                "busy_percent": 10.0,
                "vram_used": 100,
                "vram_total": 200,
                "gtt_used": 0,
                "gtt_total": 0,
                "temp_c": 50.0,
                "power_w": 12.5,
                "sclk_mhz": 1000.0,
            },
            "strata_health": {"ok": True, "model": "test", "max_context": 65536},
            "strata_auth": {},
            "ollama": None,
            "active": [],
            "recent": [
                {
                    "prompt_tokens": 100,
                    "gen_tokens": 50,
                    "prefill_tok_s": 1000.0,
                    "decode_tok_s": 40.0,
                    "duration_s": 2.0,
                    "tools": [],
                    "finish_reason": "stop",
                    "ended_at": 1.0,
                }
            ],
            "clients": [],
            "raw_log": [],
            "alerts": [],
            "errors": [],
            "sparklines": {"busy": [1.0, 2.0], "power": [10.0], "decode": [40.0]},
        }
        text = snapshot_to_json(snap)
        data = json.loads(text)
        self.assertEqual(data["host"]["hostname"], "gpu-box")
        self.assertTrue(data["strata_health"]["ok"])
        self.assertEqual(data["gpu"]["busy_percent"], 10.0)
        self.assertEqual(len(data["recent"]), 1)

    def test_render_includes_gpu_and_health(self):
        snap = {
            "host": {"hostname": "gpu-box", "uptime": "1d 00:00:00", "loadavg": [1, 1, 1]},
            "gpu": {
                "card": "card0",
                "busy_percent": 5,
                "vram_used": 1 << 30,
                "vram_total": 2 << 30,
                "gtt_used": 0,
                "gtt_total": 1 << 30,
                "temp_c": 55,
                "power_w": 20,
                "sclk_mhz": 1200,
            },
            "strata_health": {"ok": True, "model": "m", "max_context": 32},
            "active": [],
            "recent": [],
            "clients": [],
            "alerts": ["TEMP 91°C > 90"],
            "errors": [],
            "sparklines": {},
            "ollama": {"version": "0.1", "models": []},
        }
        lines = render_lines(snap)
        blob = "\n".join(lines)
        self.assertIn("gpu-box", blob)
        self.assertIn("GPU card0", blob)
        self.assertIn("ALERTS:", blob)
        self.assertIn("strata=ok", blob)


class TestAlerts(unittest.TestCase):
    def test_temp_vram_stall_disconnect(self):
        from inftop.alerts import evaluate_alerts

        gpu = {"temp_c": 95.0, "vram_used": 96, "vram_total": 100}
        active = [{"last_progress_at": 0.0, "started_at": 0.0}]
        finished = [{"finish_reason": "disconnect"}]
        alerts = evaluate_alerts(gpu, active, finished, now=100.0, stall_s=30.0)
        kinds = " ".join(alerts)
        self.assertIn("TEMP", kinds)
        self.assertIn("VRAM", kinds)
        self.assertIn("STALLED", kinds)
        self.assertIn("DISCONNECT", kinds)


if __name__ == "__main__":
    unittest.main()
