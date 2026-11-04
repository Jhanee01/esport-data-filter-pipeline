"""Battle day and session classification.

A Battle day runs from 06:00 to 06:00 the next morning (Europe/Budapest), so a match at
02:30 belongs to the previous calendar day. Sessions are time windows inside that day.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Budapest")
DAY_START_MIN = 6 * 60
_NAME_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*$")


def to_local(start_utc: str) -> datetime:
    return datetime.fromisoformat(start_utc.replace("Z", "+00:00")).astimezone(TZ)


def battle_day(start_local: datetime, tournament_name: str | None = None) -> str:
    """The date at the end of the tournament name if present, else 06:00 → 06:00 rule."""
    m = _NAME_DATE.search(tournament_name or "")
    if m:
        return m.group(1)
    d = start_local.date()
    if start_local.hour * 60 + start_local.minute < DAY_START_MIN:
        d -= timedelta(days=1)
    return d.isoformat()


def today_battle_day(now: datetime | None = None) -> str:
    return battle_day(now or datetime.now(TZ))


def _minutes(hhmm: str) -> int:
    h, m = map(int, hhmm.split(":"))
    return h * 60 + m


def session_of(hhmm: str, windows: dict[str, tuple[str, str]]) -> str | None:
    """Which session window a local HH:MM falls into. Windows may wrap past midnight."""
    t = _minutes(hhmm)
    for name, (start, end) in windows.items():
        s, e = _minutes(start), _minutes(end)
        if (s <= t < e) if s < e else (t >= s or t < e):
            return name
    return None


def days_back(today: str, n: int) -> list[str]:
    d = date.fromisoformat(today)
    return [(d - timedelta(days=i)).isoformat() for i in range(n)]
