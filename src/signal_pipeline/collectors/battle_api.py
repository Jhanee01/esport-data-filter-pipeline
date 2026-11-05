"""The Battle scraper: results and upcoming fixtures from the public Esoccer Battle JSON API.

Finished matches go to `matches` (used for features and for settling signals); matches that
haven't started yet go to `fixtures` (the demo odds source prices these). The API is
unofficial and may change: every call is wrapped, and a malformed match is skipped and
logged rather than written half-filled.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta

from ..battle_day import battle_day, session_of, to_local
from ..schedule import Schedule
from ..store import now_utc, upsert_matches

log = logging.getLogger(__name__)

BASE = "https://football.esportsbattle.com/api/"
HEADERS = {"User-Agent": "esport-data-filter-pipeline", "Accept": "application/json"}
PAUSE_S = 0.3  # be gentle: pause between requests
FINISHED_MATCH = 3
FINISHED_TOURNAMENT = 4
FIXTURE_HORIZON = timedelta(hours=3)  # fetch upcoming matches this far ahead
VENUE_FORMATS = {
    "Stamford Bridge": "8min",
    "Old Trafford": "8min",
    "Wembley": "8min",
    "San Siro": "8min",
    "Bernabeu": "8min",
    "Anfield": "12min",
    "Etihad": "12min",
}
IGNORED_VENUES = {"Hillsborough", "Emirates Stadium"}


class ApiError(Exception):
    pass


def _get(path: str, retries: int = 3, timeout: float = 30):
    for attempt in range(retries):
        time.sleep(PAUSE_S)
        try:
            req = urllib.request.Request(BASE + path, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            if attempt == retries - 1:
                raise ApiError(f"{path}: {e}") from e
            time.sleep(2 * (attempt + 1))


def tournaments_on(day: str) -> list[dict]:
    d = day.replace("-", "/")
    out, page = [], 1
    while True:
        date_from = urllib.parse.quote(d + " 00:00")
        date_to = urllib.parse.quote(d + " 23:59")
        r = _get(f"tournaments?page={page}&dateFrom={date_from}&dateTo={date_to}")
        out += r.get("tournaments", [])
        if page >= (r.get("totalPages") or 1):
            return out
        page += 1


def _valid(m: dict) -> bool:
    try:
        return (
            isinstance(m["id"], int)
            and isinstance(m["date"], str)
            and all(isinstance(m[p]["nickname"], str) for p in ("participant1", "participant2"))
        )
    except (KeyError, TypeError):
        return False


def parse_tournament(
    t: dict, matches: list[dict], sessions: dict[str, tuple[str, str]]
) -> tuple[list[dict], list[dict]]:
    """Split a tournament's matches into (finished results, upcoming fixtures)."""
    venue = t["location"]["token"]
    sched = Schedule.bundled()
    fmt = sched.format_of(venue) or VENUE_FORMATS.get(venue)
    start_local = to_local(t["start_date"])
    day = battle_day(start_local, t.get("token_international"))
    # turnus and session come from the block schedule, like in the original tool
    turnus, block_session = sched.classify(venue, day, start_local.strftime("%H:%M"))
    results, fixtures = [], []
    for m in matches:
        if not _valid(m):
            log.warning("skipping malformed match in tournament %s", t.get("id"))
            continue
        p1, p2 = m["participant1"], m["participant2"]
        local = to_local(m["date"])
        row = {
            "id": m["id"],
            "tournament_id": t["id"],
            "battle_day": day,
            "start_utc": datetime.fromisoformat(m["date"].replace("Z", "+00:00"))
            .astimezone(UTC)
            .isoformat(timespec="seconds"),
            "local_date": local.strftime("%Y-%m-%d"),
            "local_time": local.strftime("%H:%M"),
            "venue": venue,
            "format": fmt,
            "session": block_session or session_of(local.strftime("%H:%M"), sessions),
            "player1": p1["nickname"],
            "team1": (p1.get("team") or {}).get("token_international"),
            "player2": p2["nickname"],
            "team2": (p2.get("team") or {}).get("token_international"),
        }
        if (
            m.get("status_id") == FINISHED_MATCH
            and p1.get("score") is not None
            and p2.get("score") is not None
        ):
            results.append(
                {
                    **row,
                    "turnus": turnus,
                    "score1": p1["score"],
                    "score2": p2["score"],
                    "corners1": p1.get("cornerScore"),
                    "corners2": p2.get("cornerScore"),
                }
            )
        elif local.astimezone(UTC) > datetime.now(UTC):
            fixtures.append(row)
    return results, fixtures


def collect_day(conn: sqlite3.Connection, day: str, sessions: dict[str, tuple[str, str]]) -> dict:
    """Fetch one calendar day (and the next, for after-midnight blocks)."""
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    stats = {"day": day, "tournaments": 0, "results": 0, "fixtures": 0, "skipped": 0, "errors": 0}
    seen: set[int] = set()
    for d in (day, nxt):
        try:
            tournaments = tournaments_on(d)
        except ApiError as e:
            log.error("tournament list failed: %s", e)
            stats["errors"] += 1
            continue
        done = {r[0] for r in conn.execute("SELECT id FROM tournaments_done")}
        horizon = datetime.now(UTC) + FIXTURE_HORIZON
        for t in tournaments:
            if t["id"] in seen or t["location"]["token"] in IGNORED_VENUES:
                continue
            seen.add(t["id"])
            if t["id"] in done:
                stats["skipped"] += 1  # finished and stored earlier: nothing new to fetch
                continue
            start = datetime.fromisoformat(t["start_date"].replace("Z", "+00:00"))
            if start > horizon:
                stats["skipped"] += 1  # too far ahead to be priced yet
                continue
            try:
                matches = _get(f"tournaments/{t['id']}/matches")
            except ApiError as e:
                log.error("matches of %s failed: %s", t["id"], e)
                stats["errors"] += 1
                continue
            results, fixtures = parse_tournament(t, matches, sessions)
            stats["results"] += upsert_matches(conn, results)
            conn.executemany(
                "INSERT OR REPLACE INTO fixtures(id, start_utc, local_date, local_time, battle_day, venue,"
                " format, session, player1, team1, player2, team2, fetched_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        f["id"],
                        f["start_utc"],
                        f["local_date"],
                        f["local_time"],
                        f["battle_day"],
                        f["venue"],
                        f["format"],
                        f["session"],
                        f["player1"],
                        f["team1"],
                        f["player2"],
                        f["team2"],
                        now_utc(),
                    )
                    for f in fixtures
                ],
            )
            stats["fixtures"] += len(fixtures)
            stats["tournaments"] += 1
            if t.get("status_id") == FINISHED_TOURNAMENT:
                conn.execute("INSERT OR IGNORE INTO tournaments_done(id) VALUES (?)", (t["id"],))
    # a fixture that now has a result is no longer upcoming
    conn.execute("DELETE FROM fixtures WHERE id IN (SELECT id FROM matches)")
    conn.commit()
    return stats
