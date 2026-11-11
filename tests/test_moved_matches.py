"""Postponed and cancelled Battle matches (resolver.find_moved).

The 5-player block is the real Wembley E1 block of 2026-11-03 (UTC times): the two 06:00
matches were played at 08:00 instead, and the two 07:36 matches were not played at all.
"""

from datetime import UTC, datetime, timedelta

from conftest import iso

from signal_pipeline.resolver import find_moved, resolve_pending

DAY = datetime(2026, 11, 3, tzinfo=UTC)

# (HH:MM UTC, home, away, home goals, away goals)
E1 = [
    ("06:12", "Revange", "Flewless_phoenix", 2, 2),
    ("06:12", "Edwardson", "Jekunam", 0, 3),
    ("06:24", "Jekunam", "Revange", 6, 1),
    ("06:24", "Flewless_phoenix", "dm1trena", 2, 3),
    ("06:36", "dm1trena", "Jekunam", 2, 1),
    ("06:36", "Revange", "Edwardson", 1, 0),
    ("06:48", "Edwardson", "dm1trena", 0, 1),
    ("06:48", "Jekunam", "Flewless_phoenix", 2, 1),
    ("07:00", "Edwardson", "Flewless_phoenix", 0, 2),
    ("07:00", "Revange", "dm1trena", 3, 1),
    ("07:12", "Flewless_phoenix", "Revange", 3, 5),
    ("07:12", "Jekunam", "Edwardson", 3, 2),
    ("07:24", "Revange", "Jekunam", 1, 3),
    ("07:24", "dm1trena", "Flewless_phoenix", 2, 4),
    # 07:36 Edwardson–Revange and Jekunam–dm1trena: not played
    ("07:48", "dm1trena", "Edwardson", 2, 5),
    ("07:48", "Flewless_phoenix", "Jekunam", 4, 2),
    ("08:00", "Flewless_phoenix", "Edwardson", 5, 0),  # listed for 06:00
    ("08:00", "dm1trena", "Revange", 2, 3),  # listed for 06:00
]


def at(hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return DAY + timedelta(hours=h, minutes=m)


def block(rows, tournament_id: int, first_id: int) -> list[dict]:
    out = []
    for n, (hhmm, p1, p2, s1, s2) in enumerate(rows):
        t = at(hhmm)
        out.append(
            {
                "id": first_id + n,
                "tournament_id": tournament_id,
                "battle_day": "2026-11-03",
                "start_utc": iso(t),
                "local_date": "2026-11-03",
                "local_time": hhmm,
                "venue": "Wembley",
                "format": "8min",
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
        )
    return out


def seed(conn, rows, tournament_id=1, done=True):
    from signal_pipeline.store import upsert_matches

    upsert_matches(conn, block(rows, tournament_id, tournament_id * 1000))
    if done:
        conn.execute("INSERT INTO tournaments_done(id) VALUES (?)", (tournament_id,))
    conn.commit()


def moved(conn, hhmm, p1, p2):
    return find_moved(conn, p1, p2, iso(at(hhmm)), "8min")


def test_postponed_match_is_found_by_home_away_order(conn):
    seed(conn, E1)
    # listed 06:00, played 08:00; the 07:00 meeting is the other leg (Edwardson at home)
    assert moved(conn, "06:00", "Flewless_phoenix", "Edwardson") == ("played", (5, 0))
    assert moved(conn, "06:00", "dm1trena", "Revange") == ("played", (2, 3))


def test_unplayed_match_in_a_finished_block_is_cancelled(conn):
    seed(conn, E1)
    # Revange–Edwardson (06:36) was played, the return leg Edwardson–Revange was not
    assert moved(conn, "07:36", "Edwardson", "Revange") == ("cancelled", None)


def test_unfinished_block_is_not_cancelled_yet(conn):
    seed(conn, E1, done=False)
    assert moved(conn, "07:36", "Edwardson", "Revange") is None


def test_busy_player_means_a_wrong_name_not_a_postponement(conn):
    seed(conn, E1)
    # Edwardson plays Jekunam at 06:12, so a "Edwardson–Revange at 06:12" signal is a name error
    assert moved(conn, "06:12", "Edwardson", "Revange") is None


def test_four_player_block_uses_the_match_after_the_last_slot(conn):
    # 4 players, 9 slots of two every 12 minutes from 10:00; Ann–Bob meets three times at
    # home, the 10:36 one was moved to 11:48 (after the last regular slot, 11:36)
    pairs = [("Ann", "Bob"), ("Cid", "Dan"), ("Ann", "Cid"), ("Bob", "Dan"), ("Ann", "Dan"), ("Bob", "Cid")]
    rows, slot = [], at("10:00")
    for i in range(9):
        for p1, p2 in (pairs[(2 * i) % 6], pairs[(2 * i + 1) % 6]):
            rows.append([slot, p1, p2, 1, 1])
        slot += timedelta(minutes=12)
    moved_row = next(r for r in rows if r[0] == at("10:36") and r[1] == "Ann" and r[2] == "Bob")
    moved_row[0], moved_row[3], moved_row[4] = at("11:48"), 4, 2
    seed(conn, [(r[0].strftime("%H:%M"), *r[1:]) for r in rows])
    assert moved(conn, "10:36", "Ann", "Bob") == ("played", (4, 2))


def test_resolver_settles_postponed_and_voids_cancelled(conn):
    seed(conn, E1)
    for hhmm, p1, p2 in (("06:00", "Flewless_phoenix", "Edwardson"), ("07:36", "Edwardson", "Revange")):
        conn.execute(
            "INSERT INTO signals(strategy_id, offer_key, kickoff_utc, format, player1, player2, market,"
            " line, pick, odds) VALUES ('s', ?, ?, '8min', ?, ?, 'ou', 3.5, 'over', 1.9)",
            (hhmm, iso(at(hhmm)), p1, p2),
        )
    counts = resolve_pending(conn, now=at("09:00"))
    assert counts["won"] == 1 and counts["void"] == 1
    rows = {r["offer_key"]: r for r in conn.execute("SELECT * FROM signals")}
    assert (rows["06:00"]["status"], rows["06:00"]["score1"], rows["06:00"]["score2"]) == ("won", 5, 0)
    assert rows["07:36"]["status"] == "void"
