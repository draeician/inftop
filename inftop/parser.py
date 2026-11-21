"""Pure Strata log-line parser and request state machine."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

_NUM = r"[\d,]+(?:\.\d+)?"
_MIN_PREFILL_S = 0.05


def _n(s: str) -> float:
    return float(s.replace(",", ""))


def parse_line(line: str) -> dict[str, Any] | None:
    """Parse a single log line into an event dict, or None if unknown."""
    if "[strata]" not in line:
        return None
    msg = line.split("[strata]", 1)[1].strip()

    m = re.match(
        rf"reading the prompt: ({_NUM}) of ({_NUM}) tokens, ({_NUM}) s so far",
        msg,
    )
    if m:
        return {
            "kind": "reading",
            "tokens": int(_n(m.group(1))),
            "total": int(_n(m.group(2))),
            "elapsed_s": _n(m.group(3)),
        }

    m = re.match(
        rf"reading the prompt: ({_NUM}) tokens, ({_NUM}) s so far",
        msg,
    )
    if m:
        return {
            "kind": "reading",
            "tokens": int(_n(m.group(1))),
            "total": None,
            "elapsed_s": _n(m.group(2)),
        }

    m = re.match(
        rf"thinking: ({_NUM}) of budget ({_NUM}) \(max ({_NUM})\) tokens, "
        rf"({_NUM}) tok/s, ({_NUM}) s",
        msg,
    )
    if m:
        return {
            "kind": "thinking",
            "tokens": int(_n(m.group(1))),
            "budget": int(_n(m.group(2))),
            "max_tokens": int(_n(m.group(3))),
            "tok_s": _n(m.group(4)),
            "elapsed_s": _n(m.group(5)),
        }

    m = re.match(
        rf"thinking: ({_NUM}) of max ({_NUM}) tokens, ({_NUM}) tok/s, ({_NUM}) s",
        msg,
    )
    if m:
        return {
            "kind": "thinking",
            "tokens": int(_n(m.group(1))),
            "max_tokens": int(_n(m.group(2))),
            "tok_s": _n(m.group(3)),
            "elapsed_s": _n(m.group(4)),
        }

    m = re.match(
        rf"answering: ({_NUM}) of max ({_NUM}) tokens, ({_NUM}) tok/s, ({_NUM}) s",
        msg,
    )
    if m:
        return {
            "kind": "answering",
            "tokens": int(_n(m.group(1))),
            "max_tokens": int(_n(m.group(2))),
            "tok_s": _n(m.group(3)),
            "elapsed_s": _n(m.group(4)),
        }

    m = re.match(
        rf"writing a tool call: ([^:]+): ({_NUM}) of max ({_NUM}) tokens, "
        rf"({_NUM}) tok/s, ({_NUM}) s",
        msg,
    )
    if m:
        return {
            "kind": "tool",
            "tool": m.group(1).strip(),
            "tokens": int(_n(m.group(2))),
            "max_tokens": int(_n(m.group(3))),
            "tok_s": _n(m.group(4)),
            "elapsed_s": _n(m.group(5)),
        }

    if msg.startswith("tool call complete"):
        return {"kind": "tool_complete", "detail": msg}

    if msg.startswith("thinking capped"):
        return {"kind": "thinking_capped", "detail": msg}

    m = re.match(rf"thinking budget reached \(({_NUM}) tokens\)", msg)
    if m:
        return {
            "kind": "thinking_budget_reached",
            "tokens": int(_n(m.group(1))),
            "detail": msg,
        }

    m = re.match(
        rf"done: ({_NUM}) tokens in ({_NUM}) s \(({_NUM}) tok/s\) "
        rf"\((\w+), cancel=(True|False)\)",
        msg,
    )
    if m:
        return {
            "kind": "done",
            "tokens": int(_n(m.group(1))),
            "elapsed_s": _n(m.group(2)),
            "tok_s": _n(m.group(3)),
            "reason": m.group(4),
            "cancel": m.group(5) == "True",
        }

    return None


def _new_request(now: float) -> dict[str, Any]:
    return {
        "phase": "prefill",
        "prompt_tokens": None,  # None until "reading the prompt" seen (UI: ?)
        "prompt_read": 0,
        "prefill_time_s": 0.0,
        "prefill_tok_s": None,
        "gen_tokens": 0,
        "decode_tok_s": 0.0,
        "elapsed_s": 0.0,
        "tools": [],
        "started_at": now,
        "last_progress_at": now,
        "prefill_ended_at": None,
        "finish_reason": None,
        "clients": [],
    }


def _compute_prefill_tok_s(req: dict[str, Any]) -> None:
    """Set prefill_tok_s from max reading elapsed and/or timestamp span.

    Never divides by a near-zero duration; leaves None when unknown.
    """
    t = float(req.get("prefill_time_s") or 0.0)
    started = req.get("started_at")
    ended = req.get("prefill_ended_at")
    if started is not None and ended is not None:
        t = max(t, float(ended) - float(started))
    req["prefill_time_s"] = t
    tokens = req.get("prompt_tokens")
    if tokens is None:
        req["prefill_tok_s"] = None
        return
    if t >= _MIN_PREFILL_S and tokens:
        req["prefill_tok_s"] = tokens / t
    else:
        req["prefill_tok_s"] = None


class RequestTracker:
    """Track active and finished Strata requests from log lines."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.time
        self.active: list[dict[str, Any]] = []
        self.finished: list[dict[str, Any]] = []
        self.raw_lines: list[str] = []
        self._max_finished = 200
        self._max_raw = 500

    def _retire(self, req: dict[str, Any], *, reason: str, at: float) -> None:
        _compute_prefill_tok_s(req)
        req["finish_reason"] = reason
        req["ended_at"] = at
        if "duration_s" not in req:
            started = req.get("started_at")
            if started is not None:
                req["duration_s"] = max(0.0, at - float(started))
        self.finished.append(req)
        if len(self.finished) > self._max_finished:
            self.finished = self.finished[-self._max_finished :]

    def _leave_prefill(self, req: dict[str, Any], now: float) -> None:
        if req.get("prefill_ended_at") is None:
            req["prefill_ended_at"] = now
            _compute_prefill_tok_s(req)

    def sweep_stale(self, now: float | None = None, stale_after: float = 30.0) -> None:
        """Move incomplete requests with old progress into recent as reason=stale."""
        now = self._clock() if now is None else now
        keep: list[dict[str, Any]] = []
        for req in self.active:
            last = req.get("last_progress_at")
            if last is None:
                last = req.get("started_at", now)
            if now - float(last) >= stale_after:
                self._retire(req, reason="stale", at=now)
            else:
                keep.append(req)
        self.active = keep

    def feed(self, line: str, at: float | None = None) -> None:
        self.raw_lines.append(line)
        if len(self.raw_lines) > self._max_raw:
            self.raw_lines = self.raw_lines[-self._max_raw :]

        ev = parse_line(line)
        if ev is None:
            return

        now = at if at is not None else self._clock()
        kind = ev["kind"]

        if kind == "reading":
            # A new prefill while something incomplete is active → stale the old one.
            if self.active and self.active[0].get("phase") != "prefill":
                old = self.active.pop(0)
                self._retire(old, reason="stale", at=now)
            elif self.active and self.active[0].get("phase") == "prefill":
                # Another reading: same request if still prefill; but if prompt total
                # shrinks dramatically it's a new request — treat as new when the
                # active already finished reading (prompt_read >= prompt_tokens > 0)
                # and a much smaller prompt appears. Prefer: if we already left
                # prefill we handled above. Same-prefill continues below.
                pass
            if not self.active:
                self.active.append(_new_request(now))
            req = self.active[0]
            # If active was a completed-looking prefill from a prior request that
            # already had a different prompt total and we're seeing a fresh small
            # prompt after progress — handled by phase != prefill above.
            # Detect new request: prior prefill already had prefill_ended_at set.
            if req.get("prefill_ended_at") is not None:
                self.active.pop(0)
                self._retire(req, reason="stale", at=now)
                self.active.append(_new_request(now))
                req = self.active[0]
            req["phase"] = "prefill"
            req["prompt_read"] = ev["tokens"]
            if ev.get("total") is not None:
                req["prompt_tokens"] = ev["total"]
            else:
                prev = req.get("prompt_tokens") or 0
                req["prompt_tokens"] = max(prev, ev["tokens"])
            req["prefill_time_s"] = max(
                float(req.get("prefill_time_s") or 0.0), float(ev["elapsed_s"])
            )
            _compute_prefill_tok_s(req)
            req["elapsed_s"] = ev["elapsed_s"]
            req["last_progress_at"] = now
            return

        if not self.active and kind != "done":
            self.active.append(_new_request(now))

        if not self.active:
            return

        req = self.active[0]
        req["last_progress_at"] = now

        if kind == "thinking":
            self._leave_prefill(req, now)
            req["phase"] = "thinking"
            req["gen_tokens"] = ev["tokens"]
            req["decode_tok_s"] = ev.get("tok_s", 0.0)
            req["elapsed_s"] = ev.get("elapsed_s", req["elapsed_s"])
        elif kind == "answering":
            self._leave_prefill(req, now)
            req["phase"] = "answering"
            req["gen_tokens"] = ev["tokens"]
            req["decode_tok_s"] = ev.get("tok_s", 0.0)
            req["elapsed_s"] = ev.get("elapsed_s", req["elapsed_s"])
        elif kind == "tool":
            self._leave_prefill(req, now)
            req["phase"] = f"tool:{ev['tool']}"
            req["gen_tokens"] = ev["tokens"]
            req["decode_tok_s"] = ev.get("tok_s", 0.0)
            req["elapsed_s"] = ev.get("elapsed_s", req["elapsed_s"])
            if ev["tool"] not in req["tools"]:
                req["tools"].append(ev["tool"])
        elif kind == "tool_complete":
            pass
        elif kind in ("thinking_capped", "thinking_budget_reached"):
            pass
        elif kind == "done":
            if req.get("prefill_ended_at") is None:
                req["prefill_ended_at"] = now
            _compute_prefill_tok_s(req)
            req["gen_tokens"] = ev["tokens"]
            req["decode_tok_s"] = ev["tok_s"]
            req["duration_s"] = ev["elapsed_s"]
            req["elapsed_s"] = ev["elapsed_s"]
            req["finish_reason"] = ev["reason"]
            req["cancel"] = ev["cancel"]
            req["ended_at"] = now
            self.finished.append(req)
            if len(self.finished) > self._max_finished:
                self.finished = self.finished[-self._max_finished :]
            self.active.clear()
