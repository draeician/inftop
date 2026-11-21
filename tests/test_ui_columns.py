"""Recent-request column alignment and prompt ? display."""

from __future__ import annotations

import unittest

from inftop.ui import _fmt_prompt, _fmt_tok_s, render_lines


class TestFixedWidthColumns(unittest.TestCase):
    def test_tok_s_none_same_width_as_number(self):
        a = _fmt_tok_s(None)
        b = _fmt_tok_s(26998.3)
        self.assertEqual(len(a), len(b))

    def test_tok_s_small_same_width(self):
        self.assertEqual(len(_fmt_tok_s(48.0)), len(_fmt_tok_s(None)))

    def test_prompt_unknown_is_question(self):
        self.assertEqual(_fmt_prompt(None).strip(), "?")
        self.assertEqual(len(_fmt_prompt(None)), len(_fmt_prompt(80995)))

    def test_recent_rows_align_when_prefill_dash(self):
        snap = {
            "host": {"hostname": "h", "uptime": "1", "loadavg": []},
            "gpu": {
                "card": "card0",
                "busy_percent": 1,
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
            "recent": [
                {
                    "prompt_tokens": None,
                    "gen_tokens": 50,
                    "prefill_tok_s": None,
                    "decode_tok_s": 40.0,
                    "duration_s": 2.0,
                    "tools": [],
                    "finish_reason": "stop",
                    "ended_at": 1.0,
                },
                {
                    "prompt_tokens": 80995,
                    "gen_tokens": 453,
                    "prefill_tok_s": 26998.3,
                    "decode_tok_s": 48.2,
                    "duration_s": 13.0,
                    "tools": ["write_file"],
                    "finish_reason": "stop",
                    "ended_at": 2.0,
                },
            ],
            "clients": [],
            "alerts": [],
            "errors": [],
            "sparklines": {},
            "ollama": None,
        }
        lines = render_lines(snap, width=120)
        recent = [ln for ln in lines if "stop" in ln and ("40.0" in ln or "48.2" in ln)]
        self.assertEqual(len(recent), 2)
        hdr = next(ln for ln in lines if "prefill" in ln and "decode" in ln)
        reason_idx = hdr.index("reason")
        for ln in recent:
            self.assertTrue(ln[reason_idx:].lstrip().startswith("stop"))
        unknown = next(ln for ln in recent if "40.0" in ln)
        self.assertIn("?", unknown)
        # prefill '-' and numeric rates share the same column start
        pref_idx = hdr.index("prefill")
        for ln in recent:
            self.assertEqual(len(ln[pref_idx : pref_idx + 10].strip()) > 0, True)
            self.assertEqual(len(hdr[pref_idx : pref_idx + 10]), 10)


if __name__ == "__main__":
    unittest.main()
