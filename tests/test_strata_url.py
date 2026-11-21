"""Strata base URL defaults to localhost; --strata-url overrides."""

from __future__ import annotations

import unittest
from unittest import mock

from inftop.cli import build_parser
from inftop.collector import Collector
from inftop.strata import DEFAULT_STRATA_URL, StrataClient
from inftop.transport import LocalTransport


class TestStrataUrl(unittest.TestCase):
    def test_default_url_is_localhost(self):
        self.assertEqual(DEFAULT_STRATA_URL, "http://127.0.0.1:8080")
        client = StrataClient()
        self.assertEqual(client.base_url, "http://127.0.0.1:8080")

    def test_cli_exposes_strata_url(self):
        p = build_parser()
        args = p.parse_args([])
        self.assertIsNone(args.strata_url)
        args = p.parse_args(["--strata-url", "http://10.0.0.5:9"])
        self.assertEqual(args.strata_url, "http://10.0.0.5:9")

    def test_local_transport_default_matches(self):
        self.assertEqual(LocalTransport().http_base_strata(), DEFAULT_STRATA_URL)

    def test_collector_uses_strata_url_local(self):
        with mock.patch.object(Collector, "_boot_logs", lambda self: None):
            c = Collector(enable_history=False, strata_url="http://example.test:8081")
            try:
                self.assertEqual(c.strata.base_url, "http://example.test:8081")
            finally:
                c.close()

    def test_collector_default_is_localhost(self):
        with mock.patch.object(Collector, "_boot_logs", lambda self: None):
            c = Collector(enable_history=False)
            try:
                self.assertEqual(c.strata.base_url, DEFAULT_STRATA_URL)
                self.assertIn("127.0.0.1", c.strata.base_url)
            finally:
                c.close()


if __name__ == "__main__":
    unittest.main()
