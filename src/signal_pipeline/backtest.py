"""Backtest a strategy on the historical Battle results.

There is no historical odds data in this repo, so the backtest replays every past match as
if a price had been offered on it, at a fixed assumed price you choose (`assumed_odds`).
It reports what matters without real prices: how often the rule hit, and the break-even
odds you would have needed. Features come only from matches before each kick-off.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field

from . import features as feat
from .battle_day import session_of, to_local
from .markets import PICKS, profit, settle
from .odds.base import Offer
from .strategies.base import Strategy


@dataclass
class BacktestResult:
    strategy_id: str
    matches_scanned: int = 0
    signals: int = 0
    won: int = 0
    lost: int = 0
    push: int = 0
    units: float = 0.0
    assumed_odds: float = 1.9
    by_month: dict[str, dict] = field(default_factory=dict)

    @property
    def hit_rate(self) -> float | None:
        decided = self.won + self.lost
        return self.won / decided if decided else None

    @property
    def break_even_odds(self) -> float | None:
        hr = self.hit_rate
        return 1.0 / hr if hr else None


def run(
    conn: sqlite3.Connection,
    strategy: Strategy,
    *,
    date_from: str,
    date_to: str,
    ou_lines: tuple[float, ...] = (5.5,),
    assumed_odds: float = 1.9,
    fmt: str | None = None,
    limit: int | None = None,
    sessions: dict[str, tuple[str, str]] | None = None,
) -> BacktestResult:
    """Replay finished matches between two local dates (inclusive)."""
    result = BacktestResult(strategy.id, assumed_odds=assumed_odds)
    q = (
        "SELECT * FROM matches WHERE local_date BETWEEN ? AND ?"
        + (" AND format = ?" if fmt else "")
        + " ORDER BY start_utc"
        + (" LIMIT ?" if limit else "")
    )
    args: list = [date_from, date_to] + ([fmt] if fmt else []) + ([limit] if limit else [])
    month = defaultdict(lambda: {"signals": 0, "won": 0, "lost": 0, "push": 0})
    for m in conn.execute(q, args).fetchall():
        result.matches_scanned += 1
        session = m["session"] or (
            session_of(to_local(m["start_utc"]).strftime("%H:%M"), sessions) if sessions else None
        )
        for market in strategy.markets:
            lines = ou_lines if market == "ou" else (None,)
            for line in lines:
                for pick in PICKS[market]:
                    offer = Offer(
                        source="backtest",
                        kickoff_utc=m["start_utc"],
                        player1=m["player1"],
                        player2=m["player2"],
                        market=market,
                        pick=pick,
                        odds=assumed_odds,
                        line=line,
                        venue=m["venue"],
                        format=m["format"],
                    )
                    if not strategy.enabled or not strategy.wants(offer, session):
                        continue
                    f = feat.compute(
                        conn,
                        m["player1"],
                        m["player2"],
                        m["start_utc"],
                        fmt=m["format"],
                        line=line,
                        odds=assumed_odds,
                        h2h_window=strategy.h2h_window,
                        form_window=strategy.form_window,
                    )
                    if strategy.evaluate(offer, f) is None:
                        continue
                    status = settle(market, pick, line, m["score1"], m["score2"])
                    result.signals += 1
                    setattr(result, status, getattr(result, status) + 1)
                    result.units += profit(status, assumed_odds)
                    mm = month[m["local_date"][:7]]
                    mm["signals"] += 1
                    mm[status] += 1
    result.units = round(result.units, 2)
    result.by_month = dict(month)
    return result
