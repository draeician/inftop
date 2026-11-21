"""Config file load, precedence, api_key perms, and --init-config."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from inftop.config import (
    DEFAULTS,
    config_path,
    init_config,
    load_config_file,
    resolve_settings,
)
from inftop.secrets import load_strata_api_key


class TestConfigPath(unittest.TestCase):
    def test_honors_xdg_config_home(self):
        with tempfile.TemporaryDirectory() as td:
            env = {"XDG_CONFIG_HOME": td}
            self.assertEqual(config_path(env), Path(td) / "inftop" / "config.toml")

    def test_falls_back_to_home_config(self):
        with tempfile.TemporaryDirectory() as td:
            env = {"HOME": td}
            # No XDG_CONFIG_HOME
            path = config_path(env)
            self.assertEqual(path, Path(td) / ".config" / "inftop" / "config.toml")


class TestLoadConfigFile(unittest.TestCase):
    def test_parses_known_keys(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "config.toml"
            p.write_text(
                "\n".join(
                    [
                        'strata_url = "http://10.0.0.5:8080"',
                        'remote_host = "gpu-box"',
                        'tz = "UTC"',
                        "interval = 2.5",
                        "history_window = 60",
                        'ollama_url = "http://127.0.0.1:11434"',
                        'container_name = "strata"',
                        'api_key_file = "/tmp/key"',
                        "[alerts]",
                        "temp_c = 85",
                        "vram_pct = 90",
                        "stall_s = 45",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            cfg = load_config_file(p)
            self.assertEqual(cfg["strata_url"], "http://10.0.0.5:8080")
            self.assertEqual(cfg["remote_host"], "gpu-box")
            self.assertEqual(cfg["tz"], "UTC")
            self.assertEqual(cfg["interval"], 2.5)
            self.assertEqual(cfg["history_window"], 60)
            self.assertEqual(cfg["alerts"]["temp_c"], 85)
            self.assertEqual(cfg["alerts"]["vram_pct"], 90)
            self.assertEqual(cfg["alerts"]["stall_s"], 45)
            self.assertEqual(cfg["api_key_file"], "/tmp/key")
            self.assertEqual(cfg["container_name"], "strata")

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_config_file(Path("/no/such/inftop-config.toml")), {})


class TestResolvePrecedence(unittest.TestCase):
    def test_defaults(self):
        s = resolve_settings(cli={}, env={}, config={})
        self.assertEqual(s["strata_url"], "http://127.0.0.1:8080")
        self.assertIsNone(s["remote_host"])
        self.assertEqual(s["tz"], DEFAULTS["tz"])  # system local sentinel
        self.assertEqual(s["interval"], 1.0)
        self.assertEqual(s["history_window"], 120)
        self.assertEqual(s["alerts"]["temp_c"], 90)
        self.assertEqual(s["alerts"]["vram_pct"], 95)
        self.assertEqual(s["alerts"]["stall_s"], 30)
        self.assertEqual(s["ollama_url"], "http://127.0.0.1:11434")
        self.assertEqual(s["container_name"], "strata")
        self.assertIsNone(s["api_key_file"])

    def test_config_over_defaults(self):
        s = resolve_settings(
            cli={},
            env={},
            config={"strata_url": "http://10.0.0.5:9", "interval": 3.0},
        )
        self.assertEqual(s["strata_url"], "http://10.0.0.5:9")
        self.assertEqual(s["interval"], 3.0)

    def test_env_over_config(self):
        s = resolve_settings(
            cli={},
            env={
                "INFTOP_STRATA_URL": "http://env.test:1",
                "INFTOP_REMOTE": "from-env",
                "INFTOP_TZ": "Europe/Paris",
            },
            config={
                "strata_url": "http://cfg.test:1",
                "remote_host": "from-cfg",
                "tz": "UTC",
            },
        )
        self.assertEqual(s["strata_url"], "http://env.test:1")
        self.assertEqual(s["remote_host"], "from-env")
        self.assertEqual(s["tz"], "Europe/Paris")

    def test_cli_over_env(self):
        s = resolve_settings(
            cli={
                "strata_url": "http://cli.test:1",
                "remote": "from-cli",
                "tz": "Asia/Tokyo",
                "d": 0.5,
            },
            env={
                "INFTOP_STRATA_URL": "http://env.test:1",
                "INFTOP_REMOTE": "from-env",
                "INFTOP_TZ": "UTC",
            },
            config={"strata_url": "http://cfg.test:1", "interval": 9.0},
        )
        self.assertEqual(s["strata_url"], "http://cli.test:1")
        self.assertEqual(s["remote_host"], "from-cli")
        self.assertEqual(s["tz"], "Asia/Tokyo")
        self.assertEqual(s["interval"], 0.5)


class TestApiKeyFilePerms(unittest.TestCase):
    def test_refuses_looser_than_owner_only(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "api_key"
            key_path.write_text("super-secret-key\n", encoding="utf-8")
            key_path.chmod(0o644)
            with self.assertRaises(PermissionError) as cm:
                load_strata_api_key(env={}, api_key_file=key_path)
            msg = str(cm.exception)
            self.assertNotIn("super-secret-key", msg)
            self.assertIn("600", msg)

    def test_loads_chmod_600_file(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "api_key"
            key_path.write_text("super-secret-key\n", encoding="utf-8")
            key_path.chmod(0o600)
            key = load_strata_api_key(env={}, api_key_file=key_path)
            self.assertEqual(key, "super-secret-key")

    def test_env_beats_file(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "api_key"
            key_path.write_text("file-key\n", encoding="utf-8")
            key_path.chmod(0o600)
            key = load_strata_api_key(
                env={"STRATA_API_KEY": "env-key"},
                api_key_file=key_path,
            )
            self.assertEqual(key, "env-key")

    def test_accepts_owner_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            key_path = Path(td) / "api_key"
            key_path.write_text("only-me\n", encoding="utf-8")
            key_path.chmod(0o400)
            key = load_strata_api_key(env={}, api_key_file=key_path)
            self.assertEqual(key, "only-me")


class TestInitConfig(unittest.TestCase):
    def test_writes_commented_example(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "inftop" / "config.toml"
            written = init_config(dest, force=False)
            self.assertTrue(written)
            self.assertTrue(dest.is_file())
            text = dest.read_text(encoding="utf-8")
            self.assertIn("strata_url", text)
            self.assertIn("#", text)

    def test_refuses_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "config.toml"
            dest.write_text("interval = 9\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                init_config(dest, force=False)
            self.assertEqual(dest.read_text(encoding="utf-8"), "interval = 9\n")

    def test_force_overwrites(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "config.toml"
            dest.write_text("interval = 9\n", encoding="utf-8")
            init_config(dest, force=True)
            self.assertIn("strata_url", dest.read_text(encoding="utf-8"))


class TestCliInitConfig(unittest.TestCase):
    def test_init_config_flag(self):
        from inftop.cli import build_parser, main

        p = build_parser()
        args = p.parse_args(["--init-config"])
        self.assertTrue(args.init_config)

        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "config.toml"
            with mock.patch("inftop.cli.config_path", return_value=dest):
                code = main(["--init-config"])
            self.assertEqual(code, 0)
            self.assertTrue(dest.is_file())


if __name__ == "__main__":
    unittest.main()
