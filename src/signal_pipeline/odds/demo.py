"""A made-up odds feed, so the whole pipeline runs without any bookmaker.

It prices the upcoming fixtures that the Battle collector stored (or invented fixtures if
there are none) with a simple model plus noise. The prices are fake: never act on them.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import UTC, datetime, timedelta

from .base import OddsSource, Offer

_FAKE_PLAYERS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel"]
_MARGIN = 1.06  # bookmaker overround applied to the fair price


def _price(prob: float, rng: random.Random) -> float:
    prob = min(max(prob + rng.uniform(-0.04, 0.04), 0.05), 0.95)
    return round(max(1.01, 1.0 / (prob * _MARGIN)), 2)


class DemoOddsSource(OddsSource):
    name = "demo"

    def __init__(self, conn: sqlite3.Connection | None = None, horizon_min: int = 90, seed: int = 7):
        self.conn = conn
        self.horizon = timedelta(minutes=horizon_min)
        self.seed = seed

    def _fixtures(self, now: datetime) -> list[dict]:
        if self.conn is not None:
            rows = self.conn.execute(
                "SELECT start_utc, player1, team1, player2, team2, venue, format FROM fixtures"
                " WHERE start_utc > ? AND start_utc < ? ORDER BY start_utc",
                (now.isoformat(), (now + self.horizon).isoformat()),
            ).fetchall()
            if rows:
                return [dict(r) for r in rows]
        # No collector data (offline demo): invent a match every 10 minutes.
        base = now.replace(second=0, microsecond=0) + timedelta(minutes=10 - now.minute % 10)
        out = []
        for i in range(6):
            rng = random.Random(f"{self.seed}-{(base + timedelta(minutes=10 * i)).isoformat()}")
            p1, p2 = rng.sample(_FAKE_PLAYERS, 2)
            out.append(
                {
                    "start_utc": (base + timedelta(minutes=10 * i)).isoformat(),
                    "player1": p1,
                    "player2": p2,
                    "team1": None,
                    "team2": None,
                    "venue": "Demo Arena",
                    "format": "8min",
                }
            )
        return out

    def fetch(self) -> list[Offer]:
        now = datetime.now(UTC)
        offers: list[Offer] = []
        for fx in self._fixtures(now):
            # Same fixture → same prices on every poll, so offers don't flicker.
            rng = random.Random(f"{self.seed}-{fx['start_utc']}-{fx['player1']}-{fx['player2']}")
            line = rng.choice([4.5, 5.5, 6.5])
            p_over = rng.uniform(0.35, 0.65)
            common = dict(
                source=self.name,
                kickoff_utc=fx["start_utc"],
                player1=fx["player1"],
                player2=fx["player2"],
                team1=fx.get("team1"),
                team2=fx.get("team2"),
                venue=fx.get("venue"),
                format=fx.get("format"),
            )
            offers.append(Offer(market="ou", pick="over", line=line, odds=_price(p_over, rng), **common))
            offers.append(Offer(market="ou", pick="under", line=line, odds=_price(1 - p_over, rng), **common))
            p_home = rng.uniform(0.3, 0.5)
            p_draw = rng.uniform(0.15, 0.25)
            for pick, p in (("home", p_home), ("draw", p_draw), ("away", 1 - p_home - p_draw)):
                offers.append(Offer(market="1x2", pick=pick, odds=_price(p, rng), **common))
        return offers
