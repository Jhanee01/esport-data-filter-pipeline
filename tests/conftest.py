from datetime import UTC, datetime, timedelta

import pytest

from signal_pipeline.store import connect, upsert_matches

BASE = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def match(
    i: int, p1: str, p2: str, s1: int, s2: int, *, at: datetime | None = None, fmt: str = "8min"
) -> dict:
    at = at or BASE + timedelta(minutes=10 * i)
    return {
        "id": i,
        "tournament_id": 1,
        "battle_day": at.date().isoformat(),
        "start_utc": iso(at),
        "local_date": at.date().isoformat(),
        "local_time": at.strftime("%H:%M"),
        "venue": "Wembley",
        "format": fmt,
        "turnus": 1,
        "session": "day",
        "player1": p1,
        "team1": "A",
        "player2": p2,
        "team2": "B",
        "score1": s1,
        "score2": s2,
        "corners1": None,
        "corners2": None,
    }


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    yield c
    c.close()


@pytest.fixture
def seeded(conn):
    """Ten meetings of Ann vs Bob (totals 7,7,7,7,7,7,3,3,3,3) plus one future-dated one."""
    rows = [match(i, "Ann", "Bob", 4, 3) for i in range(6)]
    rows += [match(6 + i, "Bob", "Ann", 2, 1) for i in range(4)]  # reversed order
    rows.append(match(99, "Ann", "Bob", 9, 9, at=BASE + timedelta(days=30)))  # after kick-off
    upsert_matches(conn, rows)
    return conn
