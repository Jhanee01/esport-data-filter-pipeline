"""Settle pending signals from the collected Battle results, and summarise them."""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .markets import profit, settle
from .store import now_utc

MATCH_WINDOW = timedelta(minutes=20)  # bookmaker kick-off vs. Battle kick-off tolerance
WAIT_AFTER_KICKOFF = timedelta(minutes=15)
GIVE_UP_AFTER = timedelta(hours=24)  # no result by then → void


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def find_result(
    conn: sqlite3.Connection, player1: str, player2: str, kickoff_utc: str, fmt: str | None
) -> tuple[int, int] | None:
    """Score from player1's point of view, or None if the match isn't in the database yet."""
    k = datetime.fromisoformat(kickoff_utc.replace("Z", "+00:00"))
    q = (
        "SELECT player1, score1, score2, start_utc FROM matches WHERE ((player1 = ? COLLATE NOCASE"
        " AND player2 = ? COLLATE NOCASE) OR (player1 = ? COLLATE NOCASE AND player2 = ? COLLATE NOCASE))"
        " AND start_utc BETWEEN ? AND ?"
    )
    args: list = [player1, player2, player2, player1, _iso(k - MATCH_WINDOW), _iso(k + MATCH_WINDOW)]
    if fmt:
        q += " AND format = ?"
        args.append(fmt)
    rows = conn.execute(q, args).fetchall()
    if not rows:
        return None
    best = min(rows, key=lambda r: abs(datetime.fromisoformat(r["start_utc"].replace("Z", "+00:00")) - k))
    same_order = best["player1"].lower() == player1.lower()
    return (best["score1"], best["score2"]) if same_order else (best["score2"], best["score1"])


SLOT_TOLERANCE = timedelta(minutes=5)  # "is either player busy at the signal's kick-off?"
LEGS_4P = 3  # 4 players: 18 matches in 9 slots of two, every pair meets three times
SLOTS_4P = 9


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def find_moved(
    conn: sqlite3.Connection, player1: str, player2: str, kickoff_utc: str, fmt: str | None
) -> tuple[str, tuple[int, int] | None] | None:
    """A match the Battle played later than listed, or did not play at all.

    Returns ("played", score) with the score from player1's point of view, ("cancelled", None),
    or None when it cannot be decided (the signal keeps waiting).

    It relies on the home/away order of the pair: a postponed match is replayed with the same
    order, teams and players. So the signal's player1 must be the Battle home player, as it is
    on the bookmaker feeds this was built for.

    - 5-player block (20 matches): every pair meets once in each order, so the order alone
      identifies the match, whenever it was played. No match in that order in a finished
      block means it was not played.
    - 4-player block (18 matches, 9 slots): the pair meets three times, often in the same
      order. A postponed match is played after the last regular slot, so that is where we
      look; anything else stays undecided.
    - If either player has a different match at the signal's kick-off, the signal probably
      carries a wrong player name. That is not a postponement, so nothing is decided.
    """
    k = _dt(kickoff_utc)
    fmt_sql, fmt_args = (" AND format = ?", [fmt]) if fmt else ("", [])
    names = [player1, player2]

    busy = conn.execute(
        "SELECT 1 FROM matches WHERE (lower(player1) IN (?, ?) OR lower(player2) IN (?, ?))"
        " AND start_utc BETWEEN ? AND ?" + fmt_sql + " LIMIT 1",
        [*(n.lower() for n in names * 2), _iso(k - SLOT_TOLERANCE), _iso(k + SLOT_TOLERANCE), *fmt_args],
    ).fetchone()
    if busy:
        return None

    tournaments = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT tournament_id FROM matches WHERE ((player1 = ? COLLATE NOCASE AND player2 = ?"
            " COLLATE NOCASE) OR (player1 = ? COLLATE NOCASE AND player2 = ? COLLATE NOCASE))"
            " AND start_utc BETWEEN ? AND ?" + fmt_sql,
            [
                player1,
                player2,
                player2,
                player1,
                _iso(k - timedelta(hours=4)),
                _iso(k + timedelta(hours=4)),
                *fmt_args,
            ],
        )
    ]
    decisions = []
    for tid in tournaments:
        rows = conn.execute("SELECT * FROM matches WHERE tournament_id = ?", (tid,)).fetchall()
        times = sorted(_dt(r["start_utc"]) for r in rows)
        # the first slot can be empty if both of its matches were moved, hence the margin
        if not (times[0] - timedelta(minutes=30) <= k <= times[-1]):
            continue
        done = conn.execute("SELECT 1 FROM tournaments_done WHERE id = ?", (tid,)).fetchone() is not None
        decisions.append(_decide_in_block(rows, times, player1, player2, done))
    if len(decisions) != 1:  # none, or ambiguous between blocks
        return None
    return decisions[0]


def _decide_in_block(rows, times, player1: str, player2: str, done: bool):
    p1, p2 = player1.lower(), player2.lower()
    pair = [r for r in rows if {r["player1"].lower(), r["player2"].lower()} == {p1, p2}]
    ordered = [r for r in pair if r["player1"].lower() == p1]
    n_players = len({r["player1"].lower() for r in rows} | {r["player2"].lower() for r in rows})

    def played(r):
        return "played", (r["score1"], r["score2"])

    if n_players == 5:
        if len(ordered) == 1:
            return played(ordered[0])
        if not ordered and done:
            return "cancelled", None
        return None
    if n_players == 4:
        gaps = Counter(
            int((b - a).total_seconds() // 60) for a, b in zip(times, times[1:], strict=False) if b > a
        )
        if not gaps:
            return None
        interval = timedelta(minutes=gaps.most_common(1)[0][0])
        last_regular = times[0] + (SLOTS_4P - 1) * interval
        late = [r for r in ordered if _dt(r["start_utc"]) > last_regular]
        if len(late) == 1:
            return played(late[0])
        if not late and len(pair) < LEGS_4P and done:
            return "cancelled", None
    return None


def resolve_pending(conn: sqlite3.Connection, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(UTC)
    counts = {"won": 0, "lost": 0, "push": 0, "void": 0, "waiting": 0}
    pending = conn.execute(
        "SELECT * FROM signals WHERE status = 'pending' AND kickoff_utc < ?",
        (_iso(now - WAIT_AFTER_KICKOFF),),
    ).fetchall()
    for s in pending:
        score = find_result(conn, s["player1"], s["player2"], s["kickoff_utc"], s["format"])
        if score is None:
            moved = find_moved(conn, s["player1"], s["player2"], s["kickoff_utc"], s["format"])
            if moved is not None and moved[0] == "cancelled":
                conn.execute(
                    "UPDATE signals SET status = 'void', resolved_at = ? WHERE id = ?", (now_utc(), s["id"])
                )
                counts["void"] += 1
                continue
            if moved is not None:
                score = moved[1]
        if score is None:
            kickoff = datetime.fromisoformat(s["kickoff_utc"].replace("Z", "+00:00"))
            if now - kickoff > GIVE_UP_AFTER:
                conn.execute(
                    "UPDATE signals SET status = 'void', resolved_at = ? WHERE id = ?", (now_utc(), s["id"])
                )
                counts["void"] += 1
            else:
                counts["waiting"] += 1
            continue
        status = settle(s["market"], s["pick"], s["line"], *score)
        conn.execute(
            "UPDATE signals SET status = ?, score1 = ?, score2 = ?, resolved_at = ? WHERE id = ?",
            (status, score[0], score[1], now_utc(), s["id"]),
        )
        counts[status] += 1
    conn.commit()
    return counts


@dataclass(frozen=True)
class Summary:
    strategy_id: str
    signals: int
    settled: int
    won: int
    lost: int
    push: int
    void: int
    pending: int
    units: float

    @property
    def hit_rate(self) -> float | None:
        decided = self.won + self.lost
        return self.won / decided if decided else None

    @property
    def roi(self) -> float | None:
        staked = self.won + self.lost
        return self.units / staked if staked else None


def summarise(conn: sqlite3.Connection, since_utc: str | None = None) -> list[Summary]:
    q = "SELECT strategy_id, status, odds FROM signals"
    args: list = []
    if since_utc:
        q += " WHERE kickoff_utc >= ?"
        args.append(since_utc)
    by: dict[str, dict] = {}
    for r in conn.execute(q, args):
        d = by.setdefault(
            r["strategy_id"], {"won": 0, "lost": 0, "push": 0, "void": 0, "pending": 0, "units": 0.0}
        )
        d[r["status"]] += 1
        d["units"] += profit(r["status"], r["odds"])
    out = []
    for sid, d in sorted(by.items()):
        settled = d["won"] + d["lost"] + d["push"]
        out.append(
            Summary(
                sid,
                settled + d["void"] + d["pending"],
                settled,
                d["won"],
                d["lost"],
                d["push"],
                d["void"],
                d["pending"],
                round(d["units"], 2),
            )
        )
    return out


def _empty_day() -> dict:
    return {"total": 0, "won": 0, "lost": 0, "push": 0, "units": 0.0}


def daily_stats(conn: sqlite3.Connection, strategy_ids: set[str] | None = None) -> dict[str, dict]:
    """Settled signals per Battle day, overall and per session.

    {"2026-11-03": {"all": {...}, "day": {...}, "afternoon": {...}, "night": {...}}}, where each
    bucket has total / won / lost / push / units / roi (roi in percent of decided stakes).
    """
    from .battle_day import battle_day, to_local

    out: dict[str, dict] = {}
    rows = conn.execute(
        "SELECT strategy_id, kickoff_utc, session, status, odds FROM signals"
        " WHERE status IN ('won', 'lost', 'push')"
    ).fetchall()
    for r in rows:
        if strategy_ids is not None and r["strategy_id"] not in strategy_ids:
            continue
        day = battle_day(to_local(r["kickoff_utc"]))
        buckets = out.setdefault(day, {})
        for key in ("all", r["session"] or "day"):
            b = buckets.setdefault(key, _empty_day())
            b["total"] += 1
            b[r["status"]] += 1
            b["units"] += profit(r["status"], r["odds"])
    for buckets in out.values():
        for b in buckets.values():
            decided = b["won"] + b["lost"]
            b["units"] = round(b["units"], 2)
            b["roi"] = 100.0 * b["units"] / decided if decided else 0.0
    return out
