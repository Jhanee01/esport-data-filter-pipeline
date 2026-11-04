"""The Battle block schedule: which venue plays which turnus when, and which session it is.

The data (`data/menetrend.json`) is the same file esoccer-battle-mcp ships: per venue, the
start time of every turnus, versioned by date ('tol' = valid from that Battle day). The
session of a match comes from its turnus, not from the clock, so a schedule change only
needs a new entry in the file.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

TOLERANCE_MIN = 10  # a tournament may start this much off its slot
FORMATS = {"8p": "8min", "12p": "12min"}
VENUE_ABBR = {
    "Stamford Bridge": "S",
    "Old Trafford": "O",
    "Wembley": "W",
    "San Siro": "L",
    "Bernabeu": "B",
    "Anfield": "A",
    "Etihad": "E",
}


def _day_minutes(hhmm: str) -> int:
    """Minutes since 06:00 of the Battle day (times before 06:00 belong to the end of the day)."""
    h, m = map(int, hhmm.split(":"))
    total = h * 60 + m
    return total + 1440 if total < 360 else total


@dataclass(frozen=True)
class Block:
    venue: str
    abbr: str
    format: str  # "8min" | "12min"
    turnus: int
    start: str  # HH:MM local
    session: str
    start_min: int  # minutes in the Battle day, for ordering / due times
    end_min: int  # start of the venue's next block (or +120 for the last one)


class Schedule:
    def __init__(self, data: dict):
        self.venues: dict = data["palyak"]
        self.ignored = set(data.get("kihagyott_palyak", []))
        self.session_map: dict = data["napszak_turnus"]

    @classmethod
    @lru_cache(maxsize=1)
    def bundled(cls) -> Schedule:
        raw = resources.files("signal_pipeline").joinpath("data/menetrend.json").read_text("utf-8")
        return cls(json.loads(raw))

    def format_of(self, venue: str) -> str | None:
        v = self.venues.get(venue)
        return FORMATS.get(v["formatum"]) if v else None

    def _entry(self, venue: str, day: str) -> dict | None:
        valid = [
            e
            for e in self.venues[venue]["menetrend"]
            if e["tol"] <= day and (not e.get("ig") or day <= e["ig"])
        ]
        return valid[-1] if valid else None

    def classify(self, venue: str, day: str, hhmm: str) -> tuple[int | None, str | None]:
        """(turnus, session) of a block starting at `hhmm` on Battle day `day`."""
        if venue not in self.venues:
            return None, None
        entry = self._entry(venue, day)
        if not entry:
            return None, None
        start = _day_minutes(hhmm)
        best, best_diff = None, TOLERANCE_MIN + 1
        for turnus, slot in entry["turnusok"].items():
            diff = abs(_day_minutes(slot) - start)
            if diff < best_diff:
                best, best_diff = int(turnus), diff
        if best is None:
            return None, None
        return best, self.session_map[self.venues[venue]["turnus_csoport"]][str(best)]

    def block_at(self, venue: str, day: str, hhmm: str) -> Block | None:
        """The block of `venue` that a match at `hhmm` belongs to, if any."""
        t = _day_minutes(hhmm)
        return next((b for b in self.blocks(day) if b.venue == venue and b.start_min <= t < b.end_min), None)

    def blocks(self, day: str) -> list[Block]:
        """Every block of a Battle day, in time order."""
        out: list[Block] = []
        for venue, cfg in self.venues.items():
            if venue in self.ignored:
                continue
            entry = self._entry(venue, day)
            if not entry:
                continue
            slots = sorted(
                ((int(t), s) for t, s in entry["turnusok"].items()), key=lambda ts: _day_minutes(ts[1])
            )
            group = self.session_map[cfg["turnus_csoport"]]
            for i, (turnus, start) in enumerate(slots):
                s_min = _day_minutes(start)
                e_min = _day_minutes(slots[i + 1][1]) if i + 1 < len(slots) else s_min + 120
                out.append(
                    Block(
                        venue,
                        VENUE_ABBR.get(venue, venue[:1]),
                        FORMATS[cfg["formatum"]],
                        turnus,
                        start,
                        group[str(turnus)],
                        s_min,
                        e_min,
                    )
                )
        return sorted(out, key=lambda b: (b.start_min, b.venue))


GRACE_MIN = 20  # results may arrive this long after the venue's next block started


def block_status(
    conn, day: str, now_min: int, schedule: Schedule | None = None
) -> dict[tuple[str, int], str]:
    """(venue, turnus) → "done" | "running" | "overdue" | "pending" for a Battle day.

    `now_min` is the current time in Battle-day minutes (see `_day_minutes`); pass a large
    value for a past day. A block is done when its time is over and its results are in.
    """
    sched = schedule or Schedule.bundled()
    seen: dict[str, list[int]] = {}
    for r in conn.execute("SELECT venue, local_time FROM matches WHERE battle_day = ?", (day,)):
        seen.setdefault(r["venue"], []).append(_day_minutes(r["local_time"]))
    out = {}
    for b in sched.blocks(day):
        has = any(b.start_min <= t < b.end_min for t in seen.get(b.venue, ()))
        if has:
            out[(b.venue, b.turnus)] = "done" if now_min >= b.end_min else "running"
        elif now_min >= b.end_min + GRACE_MIN:
            out[(b.venue, b.turnus)] = "overdue"
        else:
            out[(b.venue, b.turnus)] = "pending"
    return out
