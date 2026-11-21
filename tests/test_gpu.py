"""Unit tests for GPU sysfs reader using a fake directory tree."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from inftop.gpu import read_gpu


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


class TestGpuSysfs(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        card = self.root / "class" / "drm" / "card0" / "device"
        _write(card / "gpu_busy_percent", "42\n")
        _write(card / "mem_info_vram_used", "1073741824\n")
        _write(card / "mem_info_vram_total", "2147483648\n")
        _write(card / "mem_info_gtt_used", "536870912\n")
        _write(card / "mem_info_gtt_total", "1073741824\n")
        hw = card / "hwmon" / "hwmon1"
        _write(hw / "temp1_input", "65000\n")  # m°C
        _write(hw / "power1_average", "25000000\n")  # µW
        _write(hw / "freq1_input", "1500000000\n")  # Hz
        _write(hw / "in0_input", "1050\n")  # mV

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_reads_all_fields(self):
        info = read_gpu(sysfs_root=str(self.root / "class" / "drm"))
        self.assertEqual(info["card"], "card0")
        self.assertEqual(info["busy_percent"], 42.0)
        self.assertEqual(info["vram_used"], 1073741824)
        self.assertEqual(info["vram_total"], 2147483648)
        self.assertEqual(info["gtt_used"], 536870912)
        self.assertEqual(info["gtt_total"], 1073741824)
        self.assertAlmostEqual(info["temp_c"], 65.0)
        self.assertAlmostEqual(info["power_w"], 25.0)
        self.assertAlmostEqual(info["sclk_mhz"], 1500.0)
        self.assertAlmostEqual(info["voltage_mv"], 1050.0)

    def test_missing_files_tolerated(self):
        sparse = Path(self._tmp.name) / "sparse" / "drm"
        card = sparse / "card1" / "device"
        _write(card / "gpu_busy_percent", "10\n")
        info = read_gpu(sysfs_root=str(sparse))
        self.assertEqual(info["busy_percent"], 10.0)
        self.assertIsNone(info["temp_c"])
        self.assertIsNone(info["power_w"])
        self.assertEqual(info["vram_used"], 0)

    def test_no_cards(self):
        empty = Path(self._tmp.name) / "empty"
        empty.mkdir()
        info = read_gpu(sysfs_root=str(empty))
        self.assertIsNone(info.get("card"))
        self.assertIn("error", info)


if __name__ == "__main__":
    unittest.main()
