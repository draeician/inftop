"""SQLite history of finished requests and per-minute GPU samples."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from inftop.config import SYSTEM_LOCAL_TZ
from inftop.timefmt import DEFAULT_TZ


def default_db_path() -> Path:
    return Path.home() / ".local" / "share" / "inftop" / "history.db"


class History:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY,
                ended_at REAL NOT NULL,
                prompt_tokens INTEGER,
                gen_tokens INTEGER,
                prefill_tok_s REAL,
                decode_tok_s REAL,
                duration_s REAL,
                tools TEXT,
                finish_reason TEXT,
                clients TEXT
            );
            CREATE TABLE IF NOT EXISTS gpu_samples (
                id INTEGER PRIMARY KEY,
                minute REAL NOT NULL,
                busy_percent REAL,
                power_w REAL,
                temp_c REAL,
                vram_used INTEGER,
                decode_tok_s REAL
            );
            CREATE INDEX IF NOT EXISTS idx_req_ended ON requests(ended_at);
            CREATE INDEX IF NOT EXISTS idx_gpu_minute ON gpu_samples(minute);
            """
        )
        self._conn.commit()
        self._last_gpu_minute: float | None = None

    def record_request(self, req: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO requests (
                ended_at, prompt_tokens, gen_tokens, prefill_tok_s, decode_tok_s,
                duration_s, tools, finish_reason, clients
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                req.get("ended_at") or time.time(),
                req.get("prompt_tokens"),
                req.get("gen_tokens"),
                req.get("prefill_tok_s"),
                req.get("decode_tok_s"),
                req.get("duration_s") or req.get("elapsed_s"),
                ",".join(req.get("tools") or []),
                req.get("finish_reason"),
                ",".join(req.get("clients") or []),
            ),
        )
        self._conn.commit()

    def record_gpu(self, gpu: dict[str, Any], decode_tok_s: float | None = None) -> None:
        minute = (time.time() // 60) * 60
        if self._last_gpu_minute == minute:
            return
        self._last_gpu_minute = minute
        self._conn.execute(
            """
            INSERT INTO gpu_samples (
                minute, busy_percent, power_w, temp_c, vram_used, decode_tok_s
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                minute,
                gpu.get("busy_percent"),
                gpu.get("power_w"),
                gpu.get("temp_c"),
                gpu.get("vram_used"),
                decode_tok_s,
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()


def parse_since(spec: str) -> float:
    """Parse '24h', '7d', '30m', or seconds into a cutoff epoch."""
    spec = spec.strip().lower()
    now = time.time()
    if spec.endswith("h"):
        return now - float(spec[:-1]) * 3600
    if spec.endswith("d"):
        return now - float(spec[:-1]) * 86400
    if spec.endswith("m"):
        return now - float(spec[:-1]) * 60
    if spec.endswith("s"):
        return now - float(spec[:-1])
    return now - float(spec)


def print_stats(since: str = "24h", path: Path | None = None) -> int:
    hist = History(path)
    cutoff = parse_since(since)
    cur = hist._conn.cursor()
    cur.execute(
        "SELECT * FROM requests WHERE ended_at >= ? ORDER BY ended_at",
        (cutoff,),
    )
    rows = [dict(r) for r in cur.fetchall()]

    print(f"inftop stats since {since} ({len(rows)} requests)")
    if not rows:
        hist.close()
        return 0

    by_client: dict[str, dict[str, Any]] = {}
    reasons: dict[str, int] = {}
    hours: dict[int, int] = {}
    total_prompt = 0
    total_gen = 0
    tok_s_sum = 0.0
    tok_s_n = 0

    for r in rows:
        clients = (r["clients"] or "unknown").split(",")
        for c in clients:
            c = c or "unknown"
            b = by_client.setdefault(
                c, {"requests": 0, "prompt": 0, "gen": 0, "tok_s": 0.0, "n": 0}
            )
            b["requests"] += 1
            b["prompt"] += r["prompt_tokens"] or 0
            b["gen"] += r["gen_tokens"] or 0
            if r["decode_tok_s"]:
                b["tok_s"] += r["decode_tok_s"]
                b["n"] += 1
        reason = r["finish_reason"] or "?"
        reasons[reason] = reasons.get(reason, 0) + 1
        if not DEFAULT_TZ or DEFAULT_TZ == SYSTEM_LOCAL_TZ:
            hour = datetime.fromtimestamp(r["ended_at"]).astimezone().hour
        else:
            hour = datetime.fromtimestamp(
                r["ended_at"], ZoneInfo(DEFAULT_TZ)
            ).hour
        hours[hour] = hours.get(hour, 0) + 1
        total_prompt += r["prompt_tokens"] or 0
        total_gen += r["gen_tokens"] or 0
        if r["decode_tok_s"]:
            tok_s_sum += r["decode_tok_s"]
            tok_s_n += 1

    print("\nPer-client:")
    for c, b in sorted(by_client.items(), key=lambda x: -x[1]["requests"]):
        avg = (b["tok_s"] / b["n"]) if b["n"] else 0
        print(
            f"  {c}: {b['requests']} reqs, prompt={b['prompt']}, "
            f"gen={b['gen']}, avg decode={avg:.1f} tok/s"
        )

    avg_all = (tok_s_sum / tok_s_n) if tok_s_n else 0
    print(f"\nTotals: prompt={total_prompt} gen={total_gen} avg decode={avg_all:.1f} tok/s")

    print("\nFinish reasons:")
    for reason, n in sorted(reasons.items(), key=lambda x: -x[1]):
        print(f"  {reason}: {n}")

    if hours:
        busiest = sorted(hours.items(), key=lambda x: -x[1])[:5]
        print("\nBusiest hours (local):")
        for h, n in busiest:
            print(f"  {h:02d}:00 — {n} requests")

    hist.close()
    return 0
