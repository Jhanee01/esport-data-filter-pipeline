"""Features a strategy can use, computed only from matches that finished BEFORE kick-off.

The same function feeds the live engine and the backtest, so a rule is always scored on
what it could have known at the time. That is the whole point of this module.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass

# The names a Strategy Lab rule can refer to. Keep in sync with Features below.
FEATURE_NAMES = (
    "h2h_n",
    "h2h_avg_goals",
    "h2h_over_rate",
    "h2h_btts_rate",
    "h2h_p1_win_rate",
    "h2h_draw_rate",
    "h2h_p2_win_rate",
    "p1_n",
    "p1_avg_scored",
    "p1_avg_conceded",
    "p2_n",
    "p2_avg_scored",
    "p2_avg_conceded",
    "odds",
    "implied_prob",
    "line",
)


@dataclass(frozen=True)
class Features:
    h2h_n: int
    h2h_avg_goals: float | None
    h2h_over_rate: float | None  # share of meetings above the offer's line (O/U only)
    h2h_btts_rate: float | None
    h2h_p1_win_rate: float | None
    h2h_draw_rate: float | None
    h2h_p2_win_rate: float | None
    p1_n: int
    p1_avg_scored: float | None
    p1_avg_conceded: float | None
    p2_n: int
    p2_avg_scored: float | None
    p2_avg_conceded: float | None
    odds: float | None
    implied_prob: float | None
    line: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _rate(flags: list[bool]) -> float | None:
    return sum(flags) / len(flags) if flags else None


def _player_rows(
    conn: sqlite3.Connection, player: str, before_utc: str, fmt: str | None, limit: int
) -> list[tuple[int, int]]:
    """(scored, conceded) of the player's last `limit` matches before `before_utc`."""
    q = (
        "SELECT player1, score1, score2 FROM matches WHERE (player1 = ? COLLATE NOCASE"
        " OR player2 = ? COLLATE NOCASE) AND start_utc < ?"
    )
    args: list = [player, player, before_utc]
    if fmt:
        q += " AND format = ?"
        args.append(fmt)
    q += " ORDER BY start_utc DESC LIMIT ?"
    args.append(limit)
    out = []
    for p1, s1, s2 in conn.execute(q, args).fetchall():
        out.append((s1, s2) if p1.lower() == player.lower() else (s2, s1))
    return out


def _h2h_rows(
    conn: sqlite3.Connection, a: str, b: str, before_utc: str, fmt: str | None, limit: int
) -> list[tuple[int, int]]:
    """(goals of a, goals of b) of their last `limit` meetings before `before_utc`."""
    q = (
        "SELECT player1, score1, score2 FROM matches WHERE ((player1 = ? COLLATE NOCASE AND"
        " player2 = ? COLLATE NOCASE) OR (player1 = ? COLLATE NOCASE AND player2 = ? COLLATE NOCASE))"
        " AND start_utc < ?"
    )
    args: list = [a, b, b, a, before_utc]
    if fmt:
        q += " AND format = ?"
        args.append(fmt)
    q += " ORDER BY start_utc DESC LIMIT ?"
    args.append(limit)
    out = []
    for p1, s1, s2 in conn.execute(q, args).fetchall():
        out.append((s1, s2) if p1.lower() == a.lower() else (s2, s1))
    return out


def compute(
    conn: sqlite3.Connection,
    player1: str,
    player2: str,
    before_utc: str,
    *,
    fmt: str | None = None,
    line: float | None = None,
    odds: float | None = None,
    h2h_window: int = 20,
    form_window: int = 10,
) -> Features:
    h2h = _h2h_rows(conn, player1, player2, before_utc, fmt, h2h_window)
    f1 = _player_rows(conn, player1, before_utc, fmt, form_window)
    f2 = _player_rows(conn, player2, before_utc, fmt, form_window)
    totals = [a + b for a, b in h2h]
    return Features(
        h2h_n=len(h2h),
        h2h_avg_goals=_mean(totals),
        h2h_over_rate=_rate([t > line for t in totals]) if line is not None else None,
        h2h_btts_rate=_rate([a > 0 and b > 0 for a, b in h2h]),
        h2h_p1_win_rate=_rate([a > b for a, b in h2h]),
        h2h_draw_rate=_rate([a == b for a, b in h2h]),
        h2h_p2_win_rate=_rate([b > a for a, b in h2h]),
        p1_n=len(f1),
        p1_avg_scored=_mean([s for s, _ in f1]),
        p1_avg_conceded=_mean([c for _, c in f1]),
        p2_n=len(f2),
        p2_avg_scored=_mean([s for s, _ in f2]),
        p2_avg_conceded=_mean([c for _, c in f2]),
        odds=odds,
        implied_prob=(1.0 / odds) if odds else None,
        line=line,
    )
