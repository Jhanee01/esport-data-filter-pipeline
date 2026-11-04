"""The turnus constants of the original `config`, derived from the bundled block schedule.

TURNUS_SCHEDULE     8-minute league, main venues (Stamford Bridge, Old Trafford, Wembley):
                    {turnus: {"session", "scrape_at", "slots": [(venue, start), ...]}}
TURNUS_SCHEDULE_12  12-minute league: {turnus: {"session", "scrape_at"}}
TURNUS_VENUE_SCRAPE_AT  {turnus: {venue: scrape_at}}

"scrape_at" is when a block's results are due: the start of the venue's next block plus a
grace period, so the turnus bar turns red only when a finished block has no results.
"""

from ...battle_day import today_battle_day
from ...schedule import GRACE_MIN, Schedule

MAIN_8 = ("Stamford Bridge", "Old Trafford", "Wembley")
LATEST_VENUE = "San Siro"


def _hhmm(day_min: int) -> str:
    m = day_min % 1440
    return f"{m // 60:02d}:{m % 60:02d}"


def build(day: str | None = None) -> tuple[dict, dict, dict, dict]:
    day = day or today_battle_day()
    blocks = Schedule.bundled().blocks(day)
    sched8: dict = {}
    venue_at: dict = {}
    latest: dict = {}
    sched12: dict = {}
    for b in blocks:
        # the original bar treats times before 07:00 as "after midnight"; a block due later
        # than that (the night's last ones) is capped so it doesn't wrap into the past
        due = _hhmm(min(b.end_min + GRACE_MIN, 1440 + 7 * 60 - 1))
        if b.format == "12min":
            sched12[b.turnus] = {"session": b.session, "scrape_at": due}
        elif b.venue in MAIN_8:
            t = sched8.setdefault(b.turnus, {"session": b.session, "scrape_at": due, "slots": []})
            t["slots"].append((b.venue, b.start))
            t["scrape_at"] = due  # the turnus is due when its last venue is
            venue_at.setdefault(b.turnus, {})[b.venue] = due
        elif b.venue == LATEST_VENUE:
            latest[b.turnus] = {"start": b.start, "scrape_at": due, "session": b.session}
    return (dict(sorted(sched8.items())), dict(sorted(sched12.items())), venue_at, latest)


TURNUS_SCHEDULE, TURNUS_SCHEDULE_12, TURNUS_VENUE_SCRAPE_AT, _LATEST = build()


def venue_filter_time(turnus: int, venue: str, scrape_at: str) -> str:
    """The original showed the scraper's page filter time; here it is the due time."""
    return scrape_at


def latest_blocks_for(day: str, fetch: bool = False) -> dict:
    return build(day)[3]
