"""Curses UI and text dump renderer for inftop."""

from __future__ import annotations

import curses
import time
from typing import Any

from inftop.sparkline import format_history_span, spark, spark_stats
from inftop.timefmt import DEFAULT_TZ, format_display_time

# Fixed widths for recent-request rate columns (keeps '-' aligned with numbers).
_TOK_S_WIDTH = 10
_PROMPT_WIDTH = 7


def _fmt_bytes(n: int | None) -> str:
    if n is None:
        return "?"
    for unit, div in (("GiB", 1 << 30), ("MiB", 1 << 20), ("KiB", 1 << 10)):
        if n >= div:
            return f"{n / div:.2f} {unit}"
    return f"{n} B"


def _bar(used: int, total: int, width: int = 20) -> str:
    if total <= 0:
        return "[" + "?" * width + "]"
    filled = int(round(width * used / total))
    filled = max(0, min(width, filled))
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def _fmt_tok_s(v: float | None) -> str:
    """Fixed-width tok/s field; None → centered '-'."""
    if v is None:
        return f"{'-':>{_TOK_S_WIDTH}}"
    return f"{v:7.1f}/s".rjust(_TOK_S_WIDTH)[:_TOK_S_WIDTH]


def _fmt_prompt(v: int | None) -> str:
    """Fixed-width prompt token count; None → '?'."""
    if v is None:
        return f"{'?':>{_PROMPT_WIDTH}}"
    return f"{v:{_PROMPT_WIDTH}d}"


def _fmt_spark_anchors(
    values: list[float | None],
    *,
    unit: str,
    fmt: str = ".1f",
) -> str:
    cur, lo, hi = spark_stats(values)
    if cur is None:
        return f"cur ?{unit}  min ?{unit}  max ?{unit}"
    return (
        f"cur {cur:{fmt}}{unit}  "
        f"min {lo:{fmt}}{unit}  "
        f"max {hi:{fmt}}{unit}"
    )


def render_lines(
    snap: dict[str, Any],
    width: int = 100,
    height: int = 40,
    show_log: bool = False,
    show_clients: bool = False,
    show_help: bool = False,
    sort_recent: str = "time",
    panel: int = 0,
    tz_name: str = DEFAULT_TZ,
) -> list[str]:
    """Render a text frame (also used by --dump)."""
    lines: list[str] = []
    host = snap.get("host") or {}
    gpu = snap.get("gpu") or {}
    health = snap.get("strata_health") or {}
    ollama = snap.get("ollama")
    _t = lambda ts: format_display_time(ts, tz_name=tz_name)  # noqa: E731

    model = health.get("model") or health.get("status") or "?"
    max_ctx = health.get("max_context") or health.get("max_ctx") or "?"
    st = "ok" if health.get("ok") else f"ERR {health.get('error', '?')}"
    ollama_v = ""
    if ollama:
        ollama_v = f"  ollama {ollama.get('version') or '?'}"

    hdr = (
        f"{host.get('hostname', '?')}  up {host.get('uptime', '?')}  "
        f"model={model}  strata={st}  max_ctx={max_ctx}{ollama_v}"
    )
    lines.append(hdr[:width])

    load = host.get("loadavg") or []
    load_s = " ".join(f"{x:.2f}" for x in load) if load else "?"
    cpu = host.get("cpu_percent")
    cpu_s = f"{cpu:.0f}%" if cpu is not None else "?"
    lines.append(
        f"load {load_s}  cpu {cpu_s}  ram {_fmt_bytes(host.get('ram_used'))}/"
        f"{_fmt_bytes(host.get('ram_total'))}  swap {_fmt_bytes(host.get('swap_used'))}/"
        f"{_fmt_bytes(host.get('swap_total'))}"
    )

    alerts = snap.get("alerts") or []
    if alerts:
        lines.append("ALERTS: " + " | ".join(alerts))

    errors = snap.get("errors") or []
    if errors:
        lines.append("status: " + "; ".join(errors)[: width - 8])

    lines.append("")
    # GPU panel
    busy = gpu.get("busy_percent")
    busy_s = f"{busy:.0f}%" if busy is not None else "?"
    activity = gpu.get("activity") or ""
    act_s = f" {activity}" if activity else ""
    temp = gpu.get("temp_c")
    temp_s = f"{temp:.0f}C" if temp is not None else "?"
    power = gpu.get("power_w")
    power_s = f"{power:.1f}W" if power is not None else "?"
    sclk = gpu.get("sclk_mhz")
    sclk_s = f"{sclk:.0f}MHz" if sclk is not None else "?"
    mark = ">>" if panel == 0 else "  "
    span_s = snap.get("sparkline_span_s")
    span_label = format_history_span(span_s) if span_s is not None else ""
    span_bit = f"  ({span_label})" if span_label else ""
    lines.append(
        f"{mark}GPU {gpu.get('card') or '?'}  busy {busy_s}{act_s}  "
        f"VRAM {_bar(gpu.get('vram_used') or 0, gpu.get('vram_total') or 0)} "
        f"{_fmt_bytes(gpu.get('vram_used'))}/{_fmt_bytes(gpu.get('vram_total'))}  "
        f"GTT {_fmt_bytes(gpu.get('gtt_used'))}/{_fmt_bytes(gpu.get('gtt_total'))}  "
        f"temp {temp_s}  power {power_s}  sclk {sclk_s}{span_bit}"
    )
    sparks = snap.get("sparklines") or {}
    spark_w = min(40, max(10, width - 55))
    busy_vals = sparks.get("busy") or []
    power_vals = sparks.get("power") or []
    decode_vals = sparks.get("decode") or []
    lines.append(
        f"  busy  {spark(busy_vals, spark_w)}  "
        f"{_fmt_spark_anchors(busy_vals, unit='%', fmt='.1f')}"
    )
    lines.append(
        f"  power {spark(power_vals, spark_w)}  "
        f"{_fmt_spark_anchors(power_vals, unit='W', fmt='.1f')}"
    )
    lines.append(
        f"  tok/s {spark(decode_vals, spark_w)}  "
        f"{_fmt_spark_anchors(decode_vals, unit='/s', fmt='.1f')}"
    )

    lines.append("")
    mark = ">>" if panel == 1 else "  "
    lines.append(f"{mark}Active requests")
    active = snap.get("active") or []
    if not active:
        lines.append("  (none)")
    for req in active:
        clients = ",".join(req.get("clients") or []) or "-"
        prog = ""
        if req.get("phase") == "prefill":
            pt = req.get("prompt_tokens")
            pt_s = f"{pt:,}" if pt is not None else "?"
            prog = f"prompt {req.get('prompt_read', 0):,}/{pt_s}"
        else:
            prog = f"gen {req.get('gen_tokens', 0):,}"
        rate = req.get("decode_tok_s")
        if not rate:
            rate = req.get("prefill_tok_s")
        rate_s = f"{rate:.1f} tok/s" if rate is not None else "- tok/s"
        lines.append(
            f"  {req.get('phase')}  {prog}  {rate_s}  "
            f"{req.get('elapsed_s', 0):.0f}s  clients={clients}"
        )

    lines.append("")
    mark = ">>" if panel == 2 else "  "
    lines.append(f"{mark}Clients" + (" (detail)" if show_clients else ""))
    clients = snap.get("clients") or []
    if not clients:
        lines.append("  (none)")
    for c in clients[: (20 if show_clients else 8)]:
        host_n = c.get("hostname") or "-"
        lines.append(
            f"  {c.get('ip')} ({host_n})  open={c.get('open_conns', 0)}  "
            f"reqs={c.get('requests', 0)}  last={_t(c.get('last_seen'))}"
        )

    lines.append("")
    mark = ">>" if panel == 3 else "  "
    lines.append(f"{mark}Recent requests (sort={sort_recent}; best-effort client corr.)")
    recent = list(snap.get("recent") or [])
    if sort_recent == "tok_s":
        recent.sort(key=lambda r: r.get("decode_tok_s") or 0, reverse=True)
    elif sort_recent == "duration":
        recent.sort(key=lambda r: r.get("duration_s") or 0, reverse=True)
    else:
        recent.sort(key=lambda r: r.get("ended_at") or 0, reverse=True)

    lines.append(
        f"  {'time':12} {'prompt':>{_PROMPT_WIDTH}} {'gen':>6} "
        f"{'prefill':>{_TOK_S_WIDTH}} {'decode':>{_TOK_S_WIDTH}} "
        f"{'dur':>5} {'tools':12} reason"
    )
    for r in recent[:12]:
        tools = ",".join(r.get("tools") or [])[:12] or "-"
        pref = r.get("prefill_tok_s")
        lines.append(
            f"  {_t(r.get('ended_at')):12} "
            f"{_fmt_prompt(r.get('prompt_tokens'))} "
            f"{r.get('gen_tokens') or 0:6d} "
            f"{_fmt_tok_s(pref)} "
            f"{_fmt_tok_s(r.get('decode_tok_s'))} "
            f"{(r.get('duration_s') or r.get('elapsed_s') or 0):5.0f} "
            f"{tools:12} {r.get('finish_reason') or '?'}"
        )

    if ollama and ollama.get("models"):
        lines.append("")
        lines.append("Ollama loaded:")
        for m in ollama["models"][:5]:
            lines.append(
                f"  {m.get('name')}  size={_fmt_bytes(m.get('size'))}  "
                f"vram={_fmt_bytes(m.get('size_vram'))}"
            )

    if show_log:
        lines.append("")
        lines.append("Raw log:")
        for line in (snap.get("raw_log") or [])[-15:]:
            lines.append("  " + line[: width - 2])

    if show_help:
        lines.append("")
        lines.append(
            "keys: q quit  p pause  Tab panels  l log  c clients  h help  s sort"
        )

    lines.append("")
    lines.append(
        "q quit | p pause | Tab cycle | l log | c clients | h help | s sort"
    )

    # Clip to height
    if len(lines) > height:
        lines = lines[: height - 1] + ["…"]
    return lines


def dump_frames(
    snaps: list[dict[str, Any]],
    width: int = 100,
    height: int = 40,
    tz_name: str = DEFAULT_TZ,
) -> str:
    parts = []
    for i, snap in enumerate(snaps):
        parts.append(f"===== frame {i + 1}/{len(snaps)} =====")
        parts.extend(
            render_lines(snap, width=width, height=height, tz_name=tz_name)
        )
        parts.append("")
    return "\n".join(parts)


def run_curses(
    collector,
    interval: float = 1.0,
    tz_name: str = DEFAULT_TZ,
) -> int:
    state = {
        "paused": False,
        "show_log": False,
        "show_clients": False,
        "show_help": False,
        "sort": "time",
        "panel": 0,
        "snap": None,
        "stop": False,
    }

    def _cycle_sort() -> None:
        order = ["time", "tok_s", "duration"]
        i = order.index(state["sort"])
        state["sort"] = order[(i + 1) % len(order)]

    def main(stdscr) -> None:
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(int(interval * 1000))
        last = 0.0
        while not state["stop"]:
            now = time.time()
            if not state["paused"] and (now - last) >= interval:
                try:
                    state["snap"] = collector.collect()
                except Exception as e:  # noqa: BLE001
                    state["snap"] = {
                        "host": {},
                        "gpu": {},
                        "strata_health": {"ok": False, "error": str(e)},
                        "errors": [str(e)],
                        "active": [],
                        "recent": [],
                        "clients": [],
                        "alerts": [],
                        "sparklines": {},
                    }
                last = now

            h, w = stdscr.getmaxyx()
            stdscr.erase()
            if state["snap"]:
                frame = render_lines(
                    state["snap"],
                    width=w,
                    height=h,
                    show_log=state["show_log"],
                    show_clients=state["show_clients"],
                    show_help=state["show_help"],
                    sort_recent=state["sort"],
                    panel=state["panel"],
                    tz_name=tz_name,
                )
                for y, line in enumerate(frame):
                    if y >= h:
                        break
                    try:
                        stdscr.addnstr(y, 0, line, w - 1)
                    except curses.error:
                        pass
            else:
                stdscr.addnstr(0, 0, "collecting…", w - 1)
            stdscr.refresh()

            try:
                ch = stdscr.getch()
            except curses.error:
                ch = -1
            if ch == ord("q"):
                break
            if ch == ord("p"):
                state["paused"] = not state["paused"]
            elif ch in (9,):  # Tab
                state["panel"] = (state["panel"] + 1) % 4
            elif ch == ord("l"):
                state["show_log"] = not state["show_log"]
            elif ch == ord("c"):
                state["show_clients"] = not state["show_clients"]
            elif ch == ord("h"):
                state["show_help"] = not state["show_help"]
            elif ch == ord("s"):
                _cycle_sort()

    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        state["stop"] = True
    return 0
