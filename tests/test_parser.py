"""Unit tests for Strata log line parser and request state machine."""

from __future__ import annotations

import unittest

from inftop.parser import RequestTracker, parse_line


SAMPLES = [
    "[strata] reading the prompt: 80,990 of 80,995 tokens, 3 s so far",
    "[strata] reading the prompt: 500 tokens, 2 s so far",
    "[strata] thinking: 31 of budget 8192 (max 50069) tokens, 38.5 tok/s, 4 s",
    "[strata] thinking: 100 of max 50069 tokens, 40.0 tok/s, 5 s",
    "[strata] answering: 115 of max 50069 tokens, 39.7 tok/s, 6 s",
    "[strata] writing a tool call: write_file: 1014 of max 51319 tokens, 47.8 tok/s, 37 s",
    "[strata] tool call complete: write_file done",
    "[strata] thinking capped at 8192 tokens",
    "[strata] thinking budget reached (8192 tokens): continuing",
    "[strata] done: 1157 tokens in 40 s (48.0 tok/s) (stop, cancel=False)",
    "[strata] done: 50 tokens in 2 s (25.0 tok/s) (disconnect, cancel=True)",
]


class TestParseLine(unittest.TestCase):
    def test_reading_prompt_with_commas(self):
        ev = parse_line(SAMPLES[0])
        self.assertEqual(ev["kind"], "reading")
        self.assertEqual(ev["tokens"], 80990)
        self.assertEqual(ev["total"], 80995)
        self.assertEqual(ev["elapsed_s"], 3.0)

    def test_reading_prompt_simple(self):
        ev = parse_line(SAMPLES[1])
        self.assertEqual(ev["kind"], "reading")
        self.assertEqual(ev["tokens"], 500)
        self.assertIsNone(ev.get("total"))
        self.assertEqual(ev["elapsed_s"], 2.0)

    def test_thinking_budget(self):
        ev = parse_line(SAMPLES[2])
        self.assertEqual(ev["kind"], "thinking")
        self.assertEqual(ev["tokens"], 31)
        self.assertEqual(ev["budget"], 8192)
        self.assertEqual(ev["max_tokens"], 50069)
        self.assertAlmostEqual(ev["tok_s"], 38.5)
        self.assertEqual(ev["elapsed_s"], 4.0)

    def test_thinking_of_max(self):
        ev = parse_line(SAMPLES[3])
        self.assertEqual(ev["kind"], "thinking")
        self.assertEqual(ev["tokens"], 100)
        self.assertEqual(ev["max_tokens"], 50069)
        self.assertAlmostEqual(ev["tok_s"], 40.0)

    def test_answering(self):
        ev = parse_line(SAMPLES[4])
        self.assertEqual(ev["kind"], "answering")
        self.assertEqual(ev["tokens"], 115)
        self.assertEqual(ev["max_tokens"], 50069)
        self.assertAlmostEqual(ev["tok_s"], 39.7)
        self.assertEqual(ev["elapsed_s"], 6.0)

    def test_writing_tool_call(self):
        ev = parse_line(SAMPLES[5])
        self.assertEqual(ev["kind"], "tool")
        self.assertEqual(ev["tool"], "write_file")
        self.assertEqual(ev["tokens"], 1014)
        self.assertEqual(ev["max_tokens"], 51319)
        self.assertAlmostEqual(ev["tok_s"], 47.8)
        self.assertEqual(ev["elapsed_s"], 37.0)

    def test_tool_call_complete(self):
        ev = parse_line(SAMPLES[6])
        self.assertEqual(ev["kind"], "tool_complete")

    def test_thinking_capped(self):
        ev = parse_line(SAMPLES[7])
        self.assertEqual(ev["kind"], "thinking_capped")

    def test_thinking_budget_reached(self):
        ev = parse_line(SAMPLES[8])
        self.assertEqual(ev["kind"], "thinking_budget_reached")
        self.assertEqual(ev["tokens"], 8192)

    def test_done_stop(self):
        ev = parse_line(SAMPLES[9])
        self.assertEqual(ev["kind"], "done")
        self.assertEqual(ev["tokens"], 1157)
        self.assertEqual(ev["elapsed_s"], 40.0)
        self.assertAlmostEqual(ev["tok_s"], 48.0)
        self.assertEqual(ev["reason"], "stop")
        self.assertFalse(ev["cancel"])

    def test_done_disconnect(self):
        ev = parse_line(SAMPLES[10])
        self.assertEqual(ev["kind"], "done")
        self.assertEqual(ev["reason"], "disconnect")
        self.assertTrue(ev["cancel"])

    def test_unknown_returns_none(self):
        self.assertIsNone(parse_line("some unrelated log line"))
        self.assertIsNone(parse_line("[strata] hello world"))


class TestRequestTracker(unittest.TestCase):
    def test_full_lifecycle(self):
        tr = RequestTracker()
        for line in [
            SAMPLES[0],
            SAMPLES[2],
            SAMPLES[4],
            SAMPLES[5],
            SAMPLES[6],
            SAMPLES[9],
        ]:
            tr.feed(line)

        self.assertEqual(len(tr.active), 0)
        self.assertEqual(len(tr.finished), 1)
        fin = tr.finished[0]
        self.assertEqual(fin["prompt_tokens"], 80995)
        self.assertEqual(fin["gen_tokens"], 1157)
        self.assertIn("write_file", fin["tools"])
        self.assertEqual(fin["finish_reason"], "stop")
        self.assertGreater(fin["prefill_tok_s"], 0)
        self.assertAlmostEqual(fin["decode_tok_s"], 48.0)
        self.assertEqual(fin["duration_s"], 40.0)

    def test_unknown_lines_kept_raw(self):
        tr = RequestTracker()
        tr.feed("noise")
        tr.feed("[strata] weird stuff")
        self.assertEqual(tr.raw_lines[-2:], ["noise", "[strata] weird stuff"])

    def test_active_during_phases(self):
        tr = RequestTracker()
        tr.feed(SAMPLES[0])
        self.assertEqual(len(tr.active), 1)
        self.assertEqual(tr.active[0]["phase"], "prefill")
        tr.feed(SAMPLES[2])
        self.assertEqual(tr.active[0]["phase"], "thinking")
        tr.feed(SAMPLES[5])
        self.assertEqual(tr.active[0]["phase"], "tool:write_file")

    def test_prefill_uses_largest_reading_elapsed(self):
        """Prefill tok/s must use max 'N s so far', not a lone early 1s line."""
        tr = RequestTracker()
        tr.feed(
            "[strata] reading the prompt: 10,000 of 78,934 tokens, 1 s so far",
            at=1000.0,
        )
        tr.feed(
            "[strata] reading the prompt: 78,934 of 78,934 tokens, 12 s so far",
            at=1012.0,
        )
        tr.feed(SAMPLES[3], at=1012.0)
        tr.feed(SAMPLES[9], at=1040.0)
        fin = tr.finished[0]
        self.assertAlmostEqual(fin["prefill_time_s"], 12.0)
        self.assertAlmostEqual(fin["prefill_tok_s"], 78934 / 12.0, places=1)

    def test_prefill_falls_back_to_timestamps(self):
        """When reading elapsed understates wall time, use timestamp span."""
        tr = RequestTracker()
        tr.feed(
            "[strata] reading the prompt: 78,934 of 78,934 tokens, 1 s so far",
            at=1000.0,
        )
        tr.feed(SAMPLES[3], at=1012.0)
        tr.feed(
            "[strata] done: 498 tokens in 12 s (45.6 tok/s) (stop, cancel=False)",
            at=1024.0,
        )
        fin = tr.finished[0]
        self.assertGreaterEqual(fin["prefill_time_s"], 12.0)
        self.assertAlmostEqual(fin["prefill_tok_s"], 78934 / 12.0, places=1)
        # Must not report the bogus tokens/1s rate
        self.assertNotAlmostEqual(fin["prefill_tok_s"], 78934.0, places=0)

    def test_prefill_unknown_when_near_zero(self):
        tr = RequestTracker()
        tr.feed(
            "[strata] reading the prompt: 500 of 500 tokens, 0 s so far",
            at=1000.0,
        )
        tr.feed(SAMPLES[3], at=1000.0)
        tr.feed(SAMPLES[9], at=1005.0)
        fin = tr.finished[0]
        self.assertIsNone(fin["prefill_tok_s"])

    def test_incomplete_recent_progress_is_active(self):
        """SPEC samples: no done, last progress < 30s → active."""
        tr = RequestTracker()
        tr.feed(SAMPLES[0], at=1000.0)
        tr.feed(SAMPLES[2], at=1004.0)
        tr.sweep_stale(now=1020.0, stale_after=30.0)
        self.assertEqual(len(tr.active), 1)
        self.assertEqual(tr.active[0]["phase"], "thinking")
        self.assertEqual(len(tr.finished), 0)

    def test_incomplete_old_progress_is_stale_in_recent(self):
        """No done, last progress ≥ 30s → recent with reason=stale, not dropped."""
        tr = RequestTracker()
        tr.feed(SAMPLES[0], at=1000.0)
        tr.feed(SAMPLES[2], at=1004.0)
        tr.sweep_stale(now=1040.0, stale_after=30.0)
        self.assertEqual(len(tr.active), 0)
        self.assertEqual(len(tr.finished), 1)
        self.assertEqual(tr.finished[0]["finish_reason"], "stale")
        self.assertEqual(tr.finished[0]["prompt_tokens"], 80995)
        self.assertEqual(tr.finished[0]["phase"], "thinking")

    def test_new_reading_stales_previous_incomplete(self):
        tr = RequestTracker()
        tr.feed(SAMPLES[0], at=1000.0)
        tr.feed(SAMPLES[2], at=1004.0)
        tr.feed(SAMPLES[1], at=1010.0)  # new request starts
        self.assertEqual(len(tr.active), 1)
        self.assertEqual(tr.active[0]["phase"], "prefill")
        self.assertEqual(tr.active[0]["prompt_tokens"], 500)
        self.assertEqual(len(tr.finished), 1)
        self.assertEqual(tr.finished[0]["finish_reason"], "stale")

    def test_prompt_unknown_when_reading_not_seen(self):
        """Requests that skip 'reading the prompt' show prompt_tokens=None (UI: ?)."""
        tr = RequestTracker()
        tr.feed(SAMPLES[3], at=1000.0)  # thinking without prior reading
        tr.feed(SAMPLES[9], at=1040.0)
        fin = tr.finished[0]
        self.assertIsNone(fin["prompt_tokens"])
        self.assertIsNone(fin["prefill_tok_s"])


if __name__ == "__main__":
    unittest.main()
