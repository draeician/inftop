"""CPU% from two /proc/stat samples (local path and injectable reader)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from inftop.host import CpuSampler, cpu_percent_from_samples


class TestCpuPercent(unittest.TestCase):
    def test_percent_from_two_samples(self):
        # total 100→200, idle 90→170 → busy = 100*(1 - 80/100) = 20%
        pct = cpu_percent_from_samples((100, 90), (200, 170))
        self.assertAlmostEqual(pct, 20.0)

    def test_sampler_with_reader(self):
        lines = [
            "cpu  90 0 10 900 0 0 0 0 0 0\n",
            "cpu  100 0 20 1700 0 0 0 0 0 0\n",
        ]
        idx = {"i": 0}

        def reader() -> str:
            s = lines[min(idx["i"], len(lines) - 1)]
            idx["i"] += 1
            return s

        samp = CpuSampler(read_fn=reader)
        # first percent uses init sample vs next
        pct = samp.percent()
        self.assertIsNotNone(pct)
        self.assertGreaterEqual(pct, 0.0)
        self.assertLessEqual(pct, 100.0)

    def test_sampler_from_temp_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "stat"
            p.write_text("cpu  10 0 0 90 0 0 0 0 0 0\n", encoding="utf-8")
            samp = CpuSampler(path=str(p))
            # total 100→200, idle 90→170 → dt=100, di=80 → 20% busy
            p.write_text("cpu  30 0 0 170 0 0 0 0 0 0\n", encoding="utf-8")
            pct = samp.percent()
            self.assertIsNotNone(pct)
            self.assertAlmostEqual(pct, 20.0)


if __name__ == "__main__":
    unittest.main()
