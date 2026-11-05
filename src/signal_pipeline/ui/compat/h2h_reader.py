"""The original core.h2h_reader functions, reading the pipeline's `matches` table.

The original scanned the match_results CSV on every search; here the player pair is filtered
in SQL. The returned structures are the same, so the original H2H view works unchanged.
`csv_path` is kept as a parameter and names the league: `config.MATCH_RESULTS_CSV` (8 min) or
`config.MATCH_RESULTS_12_CSV` (12 min).
"""

import unicodedata

from .config import MATCH_RESULTS_12_CSV, MATCH_RESULTS_CSV
from .runtime import pipeline

_OVER_LINES = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5]
_LAST_NS = [10, 20, 30, 40, 50, 100]


def _canon(s) -> str:
    s = str(s or "").strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.split())


def _fmt(csv_path) -> str:
    return "12min" if csv_path == MATCH_RESULTS_12_CSV else "8min"


def _pair_rows(p1: str, p2: str, csv_path) -> list:
    p = pipeline()
    with p.lock:
        return p.conn.execute(
            "SELECT * FROM matches WHERE format = ? AND ((player1 = ? COLLATE NOCASE AND player2 = ? COLLATE NOCASE)"
            " OR (player1 = ? COLLATE NOCASE AND player2 = ? COLLATE NOCASE))",
            (_fmt(csv_path or MATCH_RESULTS_CSV), p1, p2, p2, p1),
        ).fetchall()


def search_player_h2h(query: str, session: str | None = None) -> list[dict]:
    """Not used by the view any more (it built on precomputed JSON files)."""
    return []


def search_team_h2h(query: str, session: str | None = None, **_kwargs) -> list[dict]:
    """Not used by the view any more (it built on precomputed JSON files)."""
    return []


def get_all_player_names(csv_path=None) -> list[str]:
    p = pipeline()
    with p.lock:
        rows = p.conn.execute(
            "SELECT player1 FROM matches WHERE format = ? UNION SELECT player2 FROM matches WHERE format = ?",
            (_fmt(csv_path), _fmt(csv_path)),
        ).fetchall()
    return sorted({r[0] for r in rows if r[0]}, key=str.lower)


def get_h2h_teams(p1: str, p2: str, csv_path=None) -> tuple[list[str], list[str]]:
    """The teams the two players used AGAINST EACH OTHER (p1's list, p2's list)."""
    cp1, cp2 = _canon(p1), _canon(p2)
    if not cp1 or not cp2:
        return [], []
    t1_names: dict[str, str] = {}
    t2_names: dict[str, str] = {}
    for row in _pair_rows(p1, p2, csv_path):
        rp1 = _canon(row["player1"])
        a, b = (row["team1"], row["team2"]) if rp1 == cp1 else (row["team2"], row["team1"])
        if a:
            t1_names.setdefault(_canon(a), a)
        if b:
            t2_names.setdefault(_canon(b), b)
    return (sorted(t1_names.values(), key=str.lower), sorted(t2_names.values(), key=str.lower))


def get_player_h2h_stats(
    p1: str,
    p2: str,
    session: str | None = None,
    csv_path=None,
    team1: str | None = None,
    team2: str | None = None,
) -> dict | None:
    """Head-to-head of two players; team1/team2 optionally restrict to the teams they used."""
    cp1, cp2 = _canon(p1), _canon(p2)
    if not cp1 or not cp2:
        return None
    ct1, ct2 = _canon(team1 or ""), _canon(team2 or "")

    matches: list[dict] = []
    for row in _pair_rows(p1, p2, csv_path):
        if session and (row["session"] or "").lower() != session:
            continue
        s1, s2 = row["score1"], row["score2"]
        if s1 is None or s2 is None:
            continue
        rt1, rt2 = row["team1"] or "", row["team2"] or ""
        if _canon(row["player1"]) == cp1:
            g1, g2, t1, t2 = s1, s2, rt1, rt2
        else:
            g1, g2, t1, t2 = s2, s1, rt2, rt1
        if ct1 and _canon(t1) != ct1:
            continue
        if ct2 and _canon(t2) != ct2:
            continue
        matches.append(
            {
                "g1": g1,
                "g2": g2,
                "t1": t1,
                "t2": t2,
                "date": row["local_date"] or "",
                "time": row["local_time"] or "",
                "session": (row["session"] or "").lower(),
            }
        )
    if not matches:
        return None
    matches.sort(key=lambda x: (x["date"], x["time"]))

    def _stats(ms: list) -> dict:
        if not ms:
            return {
                "n": 0,
                "avg": 0.0,
                "w1": 0,
                "d": 0,
                "w2": 0,
                "p1_avg": 0.0,
                "p2_avg": 0.0,
                "btts": 0.0,
                "p1_score": 0.0,
                "p2_score": 0.0,
            }
        totals = [m["g1"] + m["g2"] for m in ms]
        return {
            "n": len(ms),
            "avg": round(sum(totals) / len(totals), 2),
            "w1": sum(1 for m in ms if m["g1"] > m["g2"]),
            "d": sum(1 for m in ms if m["g1"] == m["g2"]),
            "w2": sum(1 for m in ms if m["g1"] < m["g2"]),
            "p1_avg": round(sum(m["g1"] for m in ms) / len(ms), 2),
            "p2_avg": round(sum(m["g2"] for m in ms) / len(ms), 2),
            "btts": round(sum(1 for m in ms if m["g1"] > 0 and m["g2"] > 0) / len(ms) * 100, 1),
            "p1_score": round(sum(1 for m in ms if m["g1"] > 0) / len(ms) * 100, 1),
            "p2_score": round(sum(1 for m in ms if m["g2"] > 0) / len(ms) * 100, 1),
        }

    def _over(ms: list, line: float) -> float:
        return round(sum(1 for m in ms if m["g1"] + m["g2"] > line) / len(ms) * 100, 1) if ms else 0.0

    return {
        "p1": p1,
        "p2": p2,
        "team1": team1 or "",
        "team2": team2 or "",
        "overall": _stats(matches),
        "last_n": {ln: _stats(matches[-ln:]) for ln in _LAST_NS},
        "over": {line: _over(matches, line) for line in _OVER_LINES},
        "recent": matches[-10:][::-1],  # last 10, newest first (g1/g2 from p1's side)
    }
