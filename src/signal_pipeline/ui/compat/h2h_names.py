"""The original core.h2h_names index (names, real opponents, teams per player), from SQLite.

Display names are the most frequent spelling of each player; the index is cached per league
and rebuilt when the number of stored matches changes.
"""

import unicodedata
from collections import defaultdict

from .runtime import pipeline

_CACHE: dict[str, tuple[int, tuple]] = {}


def _canon(s) -> str:
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.split())


def _build(league: str) -> tuple[list[str], dict[str, list[str]], dict[str, list[str]]]:
    fmt = "12min" if league == "12" else "8min"
    p = pipeline()
    with p.lock:
        count = p.conn.execute("SELECT COUNT(*) FROM matches WHERE format = ?", (fmt,)).fetchone()[0]
        cached = _CACHE.get(league)
        if cached and cached[0] == count:
            return cached[1]
        rows = p.conn.execute(
            "SELECT player1, player2, team1, team2, COUNT(*) AS n FROM matches WHERE format = ?"
            " GROUP BY player1, player2, team1, team2",
            (fmt,),
        ).fetchall()

    raw_count: dict = defaultdict(lambda: defaultdict(int))
    opp_canon: dict = defaultdict(set)
    team_raw: dict = defaultdict(lambda: defaultdict(int))
    player_teams: dict = defaultdict(set)
    for r in rows:
        p1, p2, n = (r["player1"] or "").strip(), (r["player2"] or "").strip(), r["n"]
        c1, c2 = _canon(p1), _canon(p2)
        if not c1 or not c2:
            continue
        raw_count[c1][p1] += n
        raw_count[c2][p2] += n
        opp_canon[c1].add(c2)
        opp_canon[c2].add(c1)
        for player_c, team in ((c1, (r["team1"] or "").strip()), (c2, (r["team2"] or "").strip())):
            ct = _canon(team)
            if ct:
                team_raw[ct][team] += n
                player_teams[player_c].add(ct)

    display = {c: max(d.items(), key=lambda x: x[1])[0] for c, d in raw_count.items()}
    team_display = {c: max(d.items(), key=lambda x: x[1])[0] for c, d in team_raw.items()}
    names = sorted(display.values(), key=str.lower)
    opponents = {
        display[c]: sorted({display[o] for o in opps if o in display}, key=str.lower)
        for c, opps in opp_canon.items()
    }
    teams = {
        display[c]: sorted({team_display[t] for t in ts if t in team_display}, key=str.lower)
        for c, ts in player_teams.items()
        if c in display
    }
    result = (names, opponents, teams)
    _CACHE[league] = (count, result)
    return result


def load_index(league: str) -> tuple[list[str], dict[str, list[str]]]:
    """(sorted names, {display name: [display names of real opponents]})."""
    names, opponents, _teams = _build(league)
    return names, opponents


def load_teams(league: str) -> dict[str, list[str]]:
    """{display name: [teams the player has used]}."""
    return _build(league)[2]
