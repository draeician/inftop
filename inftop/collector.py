"""Gather one monitoring snapshot from all optional sources."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Any

_PODMAN_TS = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+(?P<rest>.*)$"
)


def _split_podman_ts(line: str) -> tuple[float | None, str]:
    m = _PODMAN_TS.match(line)
    if not m:
        return None, line
    raw = m.group("ts")
    # Normalize fractional seconds to microseconds for fromisoformat
    if "." in raw:
        head, frac_z = raw.split(".", 1)
        frac = frac_z.rstrip("Z")[:6].ljust(6, "0")
        raw = f"{head}.{frac}+00:00"
    else:
        raw = raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(raw)
        return dt.timestamp(), m.group("rest")
    except ValueError:
        return None, line

from inftop.activity import gpu_activity
from inftop.alerts import evaluate_alerts
from inftop.clients import ConnectionTracker, parse_ss_output
from inftop.config import DEFAULTS, listen_port_from_url
from inftop.gpu import RocmSmiCache, read_gpu
from inftop.host import CpuSampler, read_host
from inftop.history import History
from inftop.ollama import read_ollama
from inftop.parser import RequestTracker
from inftop.secrets import load_strata_api_key
from inftop.sparkline import Ring
from inftop.strata import DEFAULT_STRATA_URL, StrataClient
from inftop.transport import LocalTransport, SSHTransport, make_transport


class Collector:
    def __init__(
        self,
        remote: str | None = None,
        strata_url: str | None = None,
        listen_port: int | None = None,
        history: History | None = None,
        enable_history: bool = True,
        tz_name: str | None = None,
        interval_s: float = 1.0,
        history_window: int | None = None,
        ollama_url: str | None = None,
        container_name: str | None = None,
        api_key_file: str | None = None,
        alert_thresholds: dict[str, Any] | None = None,
    ) -> None:
        self.transport = make_transport(remote)
        self.strata_url = (strata_url or DEFAULT_STRATA_URL).rstrip("/")
        self.listen_port = (
            listen_port
            if listen_port is not None
            else listen_port_from_url(self.strata_url)
        )
        self.tz_name = tz_name
        self.interval_s = max(0.2, float(interval_s))
        self.container_name = container_name or str(DEFAULTS["container_name"])
        self.alert_thresholds = {
            **DEFAULTS["alerts"],
            **(alert_thresholds or {}),
        }
        window = int(history_window if history_window is not None else DEFAULTS["history_window"])
        self.errors: list[str] = []
        self.tracker = RequestTracker()
        self.clients = ConnectionTracker()
        if isinstance(self.transport, SSHTransport):
            self.cpu = CpuSampler(
                read_fn=lambda: self.transport.read_text("/proc/stat")
            )
        else:
            self.cpu = CpuSampler()
        self.rocm = RocmSmiCache(runner=self._rocm_runner)
        self._seen_finished = 0
        self.busy_hist = Ring(window)
        self.power_hist = Ring(window)
        self.decode_hist = Ring(window)
        self.history = history
        if enable_history and history is None:
            try:
                self.history = History()
            except OSError as e:
                self.errors.append(f"history: {e}")
                self.history = None

        api_key = None
        try:
            api_key = load_strata_api_key(api_key_file=api_key_file)
        except PermissionError as e:
            self.errors.append(str(e))

        ollama_default = ollama_url or str(DEFAULTS["ollama_url"])
        if isinstance(self.transport, SSHTransport):
            self.strata = StrataClient(
                base_url=self.strata_url,
                api_key=api_key,
                getter=self._ssh_http,
            )
            self._ollama_getter = self._ssh_http
            self._ollama_base = ollama_default
        else:
            self.strata = StrataClient(base_url=self.strata_url, api_key=api_key)
            self._ollama_getter = None
            self._ollama_base = ollama_url or self.transport.http_base_ollama()

        self._log_since = "1h"
        self._fed_lines: set[str] = set()
        self._boot_logs()
        # After historical backfill, classify incomplete requests as active vs stale.
        self.tracker.sweep_stale()

    def _ssh_http(self, url: str, headers=None, timeout: float = 2.0):
        assert isinstance(self.transport, SSHTransport)
        # Absolute http(s) URLs are curled on the remote host as-is.
        return self.transport.remote_http_get(url, headers)

    def _rocm_runner(self, cmd: list[str]) -> str:
        out, _, code = self.transport.run(cmd, timeout=8.0)
        return out if code == 0 else ""

    def _ingest_log_line(self, line: str, *, record_history: bool) -> None:
        if line in self._fed_lines:
            return
        self._fed_lines.add(line)
        if len(self._fed_lines) > 20000:
            # Drop an arbitrary subset to bound memory; rare in practice.
            self._fed_lines = set(list(self._fed_lines)[-10000:])
        at, body = _split_podman_ts(line)
        before = len(self.tracker.finished)
        self.tracker.feed(body, at=at)
        if record_history and len(self.tracker.finished) > before:
            req = self.tracker.finished[-1]
            ips = self.clients.current_ips()
            req["clients"] = ips
            self.clients.note_request(ips)
            if self.history:
                try:
                    self.history.record_request(req)
                except OSError:
                    pass

    def _boot_logs(self) -> None:
        out, err, code = self.transport.run(
            [
                "podman",
                "logs",
                "-t",
                "--since",
                self._log_since,
                self.container_name,
            ],
            timeout=30.0,
        )
        if code != 0:
            self.errors.append(f"podman logs: {err.strip() or code}")
            return
        for line in out.splitlines():
            self._ingest_log_line(line, record_history=False)

    def _poll_logs(self) -> None:
        out, err, code = self.transport.run(
            ["podman", "logs", "-t", "--since", "5s", self.container_name],
            timeout=8.0,
        )
        if code != 0:
            self.errors.append(f"podman logs: {err.strip() or code}")
            return
        for line in out.splitlines():
            self._ingest_log_line(line, record_history=True)

    def _read_gpu(self) -> dict[str, Any]:
        if isinstance(self.transport, LocalTransport):
            return read_gpu(sysfs_root=self.transport.sysfs_drm())
        # Remote: materialize a tiny fake tree via cat of known files
        return self._read_gpu_remote()

    def _read_gpu_remote(self) -> dict[str, Any]:
        # List cards
        out, _, code = self.transport.run(
            ["bash", "-c", "ls -1 /sys/class/drm | grep -E '^card[0-9]+$'"],
            timeout=3.0,
        )
        if code != 0 or not out.strip():
            return {"card": None, "error": "no drm cards (remote)"}
        card = out.strip().splitlines()[0]
        base = f"/sys/class/drm/{card}/device"

        def cat(rel: str) -> str | None:
            return self.transport.read_text(f"{base}/{rel}")

        def as_int(s: str | None) -> int | None:
            if s is None:
                return None
            try:
                return int(s.strip())
            except ValueError:
                return None

        busy = as_int(cat("gpu_busy_percent"))
        vram_used = as_int(cat("mem_info_vram_used")) or 0
        vram_total = as_int(cat("mem_info_vram_total")) or 0
        gtt_used = as_int(cat("mem_info_gtt_used")) or 0
        gtt_total = as_int(cat("mem_info_gtt_total")) or 0

        # find hwmon
        out_h, _, c2 = self.transport.run(
            ["bash", "-c", f"ls -1 {base}/hwmon 2>/dev/null | head -1"],
            timeout=3.0,
        )
        temp_c = power_w = sclk_mhz = voltage_mv = None
        if c2 == 0 and out_h.strip():
            hw = f"{base}/hwmon/{out_h.strip()}"
            t = as_int(self.transport.read_text(f"{hw}/temp1_input"))
            if t is not None:
                temp_c = t / 1000.0
            p = as_int(self.transport.read_text(f"{hw}/power1_average"))
            if p is None:
                p = as_int(self.transport.read_text(f"{hw}/power1_input"))
            if p is not None:
                power_w = p / 1_000_000.0
            f = as_int(self.transport.read_text(f"{hw}/freq1_input"))
            if f is not None:
                sclk_mhz = f / 1_000_000.0
            v = as_int(self.transport.read_text(f"{hw}/in0_input"))
            if v is not None:
                voltage_mv = float(v)

        return {
            "card": card,
            "busy_percent": float(busy) if busy is not None else None,
            "vram_used": vram_used,
            "vram_total": vram_total,
            "gtt_used": gtt_used,
            "gtt_total": gtt_total,
            "temp_c": temp_c,
            "power_w": power_w,
            "sclk_mhz": sclk_mhz,
            "voltage_mv": voltage_mv,
        }

    def _read_ss(self) -> None:
        out, err, code = self.transport.run(
            [
                "ss",
                "-tnpH",
                "state",
                "established",
                "( sport = :%d )" % self.listen_port,
            ],
            timeout=3.0,
        )
        if code != 0:
            # ss filter syntax can vary; try without filter and parse
            out2, err2, code2 = self.transport.run(
                ["ss", "-tnpH", "state", "established"],
                timeout=3.0,
            )
            if code2 != 0:
                self.errors.append(f"ss: {err.strip() or err2.strip() or code}")
                return
            out = out2
        peers = parse_ss_output(out, listen_port=self.listen_port)
        self.clients.update(peers)

    def _read_host(self) -> dict[str, Any]:
        if isinstance(self.transport, LocalTransport):
            return read_host(cpu_sampler=self.cpu)
        # Remote host metrics via /proc
        mem = self.transport.read_text("/proc/meminfo") or ""
        up = self.transport.read_text("/proc/uptime")
        load_out, _, _ = self.transport.run(["cat", "/proc/loadavg"], timeout=2.0)
        hostname_out, _, _ = self.transport.run(["hostname"], timeout=2.0)

        # write temp meminfo for parser — reuse read_host with temp files is messy;
        # parse inline
        meminfo: dict[str, int] = {}
        for line in mem.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0].endswith(":"):
                try:
                    meminfo[parts[0][:-1]] = int(parts[1])
                except ValueError:
                    pass
        total = meminfo.get("MemTotal", 0) * 1024
        avail = meminfo.get("MemAvailable", meminfo.get("MemFree", 0)) * 1024
        used = max(0, total - avail) if total else 0
        swap_total = meminfo.get("SwapTotal", 0) * 1024
        swap_free = meminfo.get("SwapFree", 0) * 1024
        uptime_s = None
        if up:
            try:
                uptime_s = float(up.split()[0])
            except ValueError:
                pass
        load = []
        if load_out:
            try:
                load = [float(x) for x in load_out.split()[:3]]
            except ValueError:
                pass
        from inftop.host import format_uptime

        return {
            "hostname": (hostname_out or "").strip() or "remote",
            "loadavg": load,
            "ram_used": used,
            "ram_total": total,
            "swap_used": max(0, swap_total - swap_free),
            "swap_total": swap_total,
            "cpu_percent": self.cpu.percent(),
            "uptime_s": uptime_s,
            "uptime": format_uptime(uptime_s),
        }

    def collect(self) -> dict[str, Any]:
        self.errors = [e for e in self.errors if e.startswith("history")][:1]
        self._poll_logs()
        self.tracker.sweep_stale()
        self._read_ss()

        gpu = self._read_gpu()
        host = self._read_host()

        health = self.strata.health()
        if not health.get("ok"):
            self.errors.append(f"strata health: {health.get('error')}")

        auth = {}
        try:
            auth = self.strata.probe_auth()
        except Exception as e:  # noqa: BLE001 — degrade
            self.errors.append(f"strata auth: {e}")

        if isinstance(self.transport, SSHTransport):
            ollama = read_ollama(
                base_url=self._ollama_base, getter=self._ollama_getter
            )
        else:
            ollama = read_ollama(base_url=self._ollama_base)

        # Attribute open clients to active requests (best-effort)
        ips = self.clients.current_ips()
        for req in self.tracker.active:
            req["clients"] = ips

        decode = None
        if self.tracker.active:
            decode = self.tracker.active[0].get("decode_tok_s")
        elif self.tracker.finished:
            decode = self.tracker.finished[-1].get("decode_tok_s")

        self.busy_hist.push(gpu.get("busy_percent"))
        self.power_hist.push(gpu.get("power_w"))
        self.decode_hist.push(decode)

        gpu["activity"] = gpu_activity(
            active_count=len(self.tracker.active),
            power_w=gpu.get("power_w"),
            power_history=list(self.power_hist.values),
        )

        if self.history:
            try:
                self.history.record_gpu(gpu, decode)
            except OSError:
                pass

        alerts = evaluate_alerts(
            gpu,
            self.tracker.active,
            self.tracker.finished,
            stall_s=float(self.alert_thresholds["stall_s"]),
            temp_c=float(self.alert_thresholds["temp_c"]),
            vram_pct=float(self.alert_thresholds["vram_pct"]),
        )

        span_s = self.busy_hist.capacity * self.interval_s
        snap = {
            "ts": time.time(),
            "host": host,
            "gpu": gpu,
            "strata_health": health,
            "strata_auth": {k: _summarize(v) for k, v in auth.items()},
            "ollama": ollama,
            "active": list(self.tracker.active),
            "recent": list(self.tracker.finished[-20:]),
            "clients": self.clients.summary(),
            "raw_log": list(self.tracker.raw_lines[-50:]),
            "alerts": alerts,
            "errors": list(self.errors),
            "sparklines": {
                "busy": list(self.busy_hist.values),
                "power": list(self.power_hist.values),
                "decode": list(self.decode_hist.values),
            },
            "sparkline_span_s": span_s,
        }
        return snap

    def close(self) -> None:
        self.transport.close()
        if self.history:
            self.history.close()


def _summarize(v: Any) -> Any:
    if isinstance(v, dict) and len(json.dumps(v, default=str)) > 2000:
        return {k: v[k] for k in list(v)[:20]}
    return v


def snapshot_to_json(snap: dict[str, Any]) -> str:
    def default(o: Any) -> Any:
        return str(o)

    return json.dumps(snap, indent=2, default=default, sort_keys=True)
