"""Display timestamps in a configured IANA zone (default: system local)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from inftop.config import SYSTEM_LOCAL_TZ

DEFAULT_TZ = SYSTEM_LOCAL_TZ


def format_display_time(ts: float | None, tz_name: str | None = None) -> str:
    """Format epoch seconds as HH:MM:SS <abbrev> in tz_name.

    ``None`` / ``"local"`` uses the process local timezone.
    """
    if not ts:
        return "--:--:--"
    name = tz_name if tz_name is not None else DEFAULT_TZ
    if not name or name == SYSTEM_LOCAL_TZ:
        dt = datetime.fromtimestamp(ts).astimezone()
        return dt.strftime("%H:%M:%S %Z")
    try:
        tz = ZoneInfo(name)
    except Exception:  # noqa: BLE001 — fall back to system local
        dt = datetime.fromtimestamp(ts).astimezone()
        return dt.strftime("%H:%M:%S %Z")
    dt = datetime.fromtimestamp(ts, tz)
    return dt.strftime("%H:%M:%S %Z")
