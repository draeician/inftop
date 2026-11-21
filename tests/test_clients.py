"""Unit tests for ss connection parser and client tracker."""

from __future__ import annotations

import unittest

from inftop.clients import ConnectionTracker, parse_ss_output

SS_SAMPLE = """\
10.0.0.5:8080 10.0.0.10:54321 users:(("pasta.avx2",pid=1234,fd=5))
10.0.0.5:8080 10.0.0.10:54322 users:(("pasta.avx2",pid=1234,fd=6))
10.0.0.5:8080 10.0.1.50:40000 users:(("pasta.avx2",pid=1234,fd=7))
"""


class TestParseSs(unittest.TestCase):
    def test_parse_peers(self):
        peers = parse_ss_output(SS_SAMPLE, listen_port=8080)
        self.assertEqual(len(peers), 3)
        ips = sorted({p["ip"] for p in peers})
        self.assertEqual(ips, ["10.0.0.10", "10.0.1.50"])
        ports = {p["port"] for p in peers if p["ip"] == "10.0.0.10"}
        self.assertEqual(ports, {54321, 54322})

    def test_empty(self):
        self.assertEqual(parse_ss_output("", listen_port=8080), [])


class TestConnectionTracker(unittest.TestCase):
    def test_counts_and_seen(self):
        clock = {"t": 1000.0}

        def now() -> float:
            return clock["t"]

        def fake_dns(ip: str) -> str | None:
            return {"10.0.0.10": "workstation.lan"}.get(ip)

        tr = ConnectionTracker(clock=now, resolve=fake_dns, dns_timeout=0.5)
        tr.update(parse_ss_output(SS_SAMPLE, listen_port=8080))
        rows = tr.summary()
        by_ip = {r["ip"]: r for r in rows}
        self.assertEqual(by_ip["10.0.0.10"]["open_conns"], 2)
        self.assertEqual(by_ip["10.0.0.10"]["hostname"], "workstation.lan")
        self.assertEqual(by_ip["10.0.0.10"]["first_seen"], 1000.0)
        clock["t"] = 1005.0
        tr.update(parse_ss_output(SS_SAMPLE, listen_port=8080))
        rows = tr.summary()
        by_ip = {r["ip"]: r for r in rows}
        self.assertEqual(by_ip["10.0.0.10"]["last_seen"], 1005.0)
        self.assertEqual(by_ip["10.0.0.10"]["first_seen"], 1000.0)

    def test_attrib_request(self):
        tr = ConnectionTracker(clock=lambda: 1.0, resolve=lambda ip: None)
        tr.update(parse_ss_output(SS_SAMPLE, listen_port=8080))
        tr.note_request(["10.0.0.10"])
        rows = {r["ip"]: r for r in tr.summary()}
        self.assertEqual(rows["10.0.0.10"]["requests"], 1)


if __name__ == "__main__":
    unittest.main()
