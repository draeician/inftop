"""GPU activity classification (rule B)."""

from __future__ import annotations


def gpu_activity(
    *,
    active_count: int,
    power_w: float | None,
    power_history: list[float | None],
    idle_band_w: float = 5.0,
) -> str:
    """Return 'busy' or 'idle'.

    Rule B:
    - busy if >= 1 active request
    - else idle if power is within idle_band_w of the rolling minimum
      over the history window
    - else busy
    """
    if active_count >= 1:
        return "busy"
    nums = [v for v in power_history if v is not None]
    if power_w is None or not nums:
        return "idle"
    lo = min(nums)
    if power_w <= lo + idle_band_w:
        return "idle"
    return "busy"
