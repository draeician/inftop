"""Display-time formatting (system local default; override via --tz)."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from inftop.config import SYSTEM_LOCAL_TZ
from inftop.timefmt import DEFAULT_TZ, format_display_time
from inftop.ui import render_lines


class TestTimefmt(unittest.TestCase):
    def test_default_tz_is_system_local(self):
        self.assertEqual(DEFAULT_TZ, SYSTEM_LOCAL_TZ)

    def test_formats_utc_instant_with_chicago_override(self):
        # 2026-11-21 20:08:59 UTC → 14:08:59 CST
        ts = datetime(2026, 11, 21, 20, 8, 59, tzinfo=ZoneInfo("UTC")).timestamp()
        text = format_display_time(ts, tz_name="America/Chicago")
        self.assertTrue(text.startswith("14:08:59"), text)
        self.assertIn("CST", text)

    def test_tz_override(self):
        ts = datetime(2026, 11, 21, 20, 8, 59, tzinfo=ZoneInfo("UTC")).timestamp()
        text = format_display_time(ts, tz_name="UTC")
        self.assertTrue(text.startswith("20:08:59"), text)
        self.assertIn("UTC", text)

    def test_render_recent_uses_tz_label(self):
        ts = datetime(2026, 11, 21, 20, 8, 59, tzinfo=ZoneInfo("UTC")).timestamp()
        snap = {
            "host": {"hostname": "gpu-box", "uptime": "1d", "loadavg": []},
            "gpu": {},
            "strata_health": {"ok": True},
            "active": [],
            "recent": [
                {
                    "prompt_tokens": 100,
                    "gen_tokens": 10,
                    "prefill_tok_s": None,
                    "decode_tok_s": 40.0,
                    "duration_s": 2.0,
                    "tools": [],
                    "finish_reason": "stop",
                    "ended_at": ts,
                }
            ],
            "clients": [],
            "alerts": [],
            "errors": [],
            "sparklines": {},
            "ollama": None,
        }
        blob = "\n".join(render_lines(snap, tz_name="America/Chicago"))
        self.assertIn("14:08:59", blob)
        self.assertIn("CST", blob)
        self.assertIn("-", blob)  # unknown prefill shown as dash


if __name__ == "__main__":
    unittest.main()
