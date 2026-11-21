"""Simple unicode sparklines for history buffers."""

from __future__ import annotations

_BARS = "▁▂▃▄▅▆▇█"


def spark(values: list[float | None], width: int = 40) -> str:
    if not values or width <= 0:
        return ""
    data = values[-width:]
    nums = [v for v in data if v is not None]
    if not nums:
        return " " * len(data)
    lo, hi = min(nums), max(nums)
    span = hi - lo if hi > lo else 1.0
    out = []
    for v in data:
        if v is None:
            out.append(" ")
        else:
            idx = int((v - lo) / span * (len(_BARS) - 1))
            out.append(_BARS[max(0, min(len(_BARS) - 1, idx))])
    return "".join(out)


def spark_stats(
    values: list[float | None],
) -> tuple[float | None, float | None, float | None]:
    """Return (current, min, max) over non-None values; current is last sample."""
    nums = [v for v in values if v is not None]
    if not nums:
        return None, None, None
    # current = last non-None in order
    cur = None
    for v in reversed(values):
        if v is not None:
            cur = v
            break
    return cur, min(nums), max(nums)


def format_history_span(seconds: float | int | None) -> str:
    """Humanize a history window, e.g. 120 → 'last 2m'."""
    if seconds is None or seconds <= 0:
        return "last ?"
    s = int(round(float(seconds)))
    if s < 60:
        return f"last {s}s"
    m, rem = divmod(s, 60)
    if rem == 0:
        return f"last {m}m"
    return f"last {m}m{rem}s"


class Ring:
    def __init__(self, capacity: int = 120) -> None:
        self.capacity = capacity
        self.values: list[float | None] = []

    def push(self, v: float | None) -> None:
        self.values.append(v)
        if len(self.values) > self.capacity:
            self.values = self.values[-self.capacity :]
