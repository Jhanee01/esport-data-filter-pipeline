"""Tip history for one matchup, per strategy (taken over from the original tool).

The H2H search shows the matches' statistics; this module adds the other side: the
signals the strategies sent for this matchup, with the actual result (W/L/push, units,
ROI). The tips come from the pipeline database through `tips_reader`, and the ROI uses the
`stats_manager` formula, so the numbers match the Statistics view.

`void` signals are left out everywhere, as in the statistics.
"""
import unicodedata

from .stats_manager import get_strategy_tabs, _get_odds
from .tips_reader import load_tips

# Ennyi utolsó tippet adunk vissza stratégiánként (a prózai elemzéshez elég).
LAST_N = 5


def _canon(s) -> str:
    """Ékezet- és kisbetű-érzéketlen kulcs (a h2h_reader-rel azonos szabály)."""
    if not isinstance(s, str):
        return ""
    s = s.strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.split())


# ── stratégia-térkép: source → (kulcs, címke, liga) ────────────────────────

def _source_map() -> dict:
    """source → (key, label, league). Every loaded strategy is its own source; the league
    of a tip comes from the tip itself (8 or 12 minute format), see `_tip_league`."""
    out = {}
    for key, label, sources in get_strategy_tabs():
        if not sources:                      # "Összes" fül — nincs saját forrása
            continue
        for src in sources:
            out[src.lower()] = (key, label, "8")
    return out


def _tip_league(tip: dict) -> str:
    return "12" if (tip.get("_raw") or {}).get("format") == "12min" else "8"


def _tip_session(tip: dict, league: str) -> str | None:
    return (tip.get("_raw") or {}).get("session")


# ── tipp-formázás ─────────────────────────────────────────────────────────

_1X2_LABEL = {"home": "Hazai", "away": "Vendég", "draw": "Döntetlen"}


def _pick_label(raw: dict) -> str:
    market = str(raw.get("market") or "").upper()
    pick = str(raw.get("pick") or "").strip()
    if market == "OU":
        line = raw.get("line")
        return f"{pick.upper()} {line}" if line is not None else pick.upper()
    if raw.get("pick_label"):
        return str(raw["pick_label"])
    return _1X2_LABEL.get(pick.lower(), pick.upper() or "–")


def _calc(tips: list) -> dict:
    """W/L/push + unit + ROI a stats_manager képletével (fél nyerés/veszteség is)."""
    won = lost = push = pending = 0
    units = 0.0
    for t in tips:
        status = str(t.get("status") or "").lower()
        odds = _get_odds(t)
        if status == "win":
            won += 1
            units += odds - 1.0
        elif status == "half_win":
            won += 1
            units += (odds - 1.0) / 2.0
        elif status == "loss":
            lost += 1
            units -= 1.0
        elif status == "half_loss":
            lost += 1
            units -= 0.5
        elif status == "push":
            push += 1
        else:
            pending += 1

    settled = won + lost + push
    decided = won + lost
    return {
        "settled":  settled,
        "won":      won,
        "lost":     lost,
        "push":     push,
        "pending":  pending,
        "units":    round(units, 2),
        "roi":      round(units / settled * 100, 2) if settled else 0.0,
        "hit_pct":  round(won / decided * 100, 1) if decided else 0.0,
    }


def _tip_row(t: dict, smap: dict) -> dict:
    """Egy tipp megjelenítésre kész formában (dátum, meccs, tipp, odds, eredmény)."""
    raw = t.get("_raw") or {}
    res = raw.get("result") or {}
    hg, ag = res.get("home_goals"), res.get("away_goals")
    src = str(t.get("source") or "").lower()
    return {
        "date":        str(raw.get("date") or ""),
        "time":        str(raw.get("time") or ""),
        "match":       t.get("match", ""),
        "home_player": str(raw.get("home_player") or ""),
        "away_player": str(raw.get("away_player") or ""),
        "home_team":   str(raw.get("home_team") or ""),
        "away_team":   str(raw.get("away_team") or ""),
        "strategy":    smap.get(src, (src, src, "8"))[1],
        "pick":        _pick_label(raw),
        "odds":        round(_get_odds(t), 2),
        "score":       f"{hg}–{ag}" if hg is not None and ag is not None else "",
        "status":      str(t.get("status") or ""),
    }


def _rows(tips: list, smap: dict) -> list[dict]:
    """Stratégiánkénti bontás, a legtöbb tippet adó stratégiával az élen."""
    by_key: dict = {}
    for t in tips:
        src = str(t.get("source") or "").lower()
        key, label, _league = smap.get(src, (src, src, "8"))
        by_key.setdefault(key, {"label": label, "tips": []})["tips"].append(t)

    rows = []
    for key, bucket in by_key.items():
        group = sorted(bucket["tips"], key=lambda x: str(x.get("saved_at") or ""))
        row = {"key": key, "label": bucket["label"], "n": len(group)}
        row.update(_calc(group))
        row["last"] = [_tip_row(t, smap) for t in group[-LAST_N:]]
        rows.append(row)

    rows.sort(key=lambda r: (-r["n"], r["label"]))
    return rows


# ── publikus API ──────────────────────────────────────────────────────────

def matchup_tip_history(p1: str, p2: str, league: str = "8",
                        session: str | None = None,
                        team1: str | None = None,
                        team2: str | None = None) -> dict:
    """A párosításra kiadott tippek stratégiánként.

    `pair`  — mindkét játékos szerepel a tippben (a keresett párosítás);
              a `tips` kulcs az összes ilyen tippet adja, legújabb elöl,
    `solo`  — játékosonként az ÖSSZES tippje (bármelyik ellenfél ellen).

    A `team1`/`team2` szűrő ugyanúgy opcionális, mint a H2H nézetben: ha meg van
    adva, csak azok a tippek számítanak, ahol az adott játékos azzal a csapattal
    játszott. A `session` szűrő a jelzés napszakát nézi.
    """
    c1, c2 = _canon(p1), _canon(p2)
    ct1, ct2 = _canon(team1), _canon(team2)
    smap = _source_map()

    pair_tips: list = []
    solo_tips: dict = {c1: [], c2: []}

    for t in load_tips():
        raw = t.get("_raw") or {}
        if str(t.get("status") or "").lower() == "void":
            continue

        src = str(t.get("source") or "").lower()
        if _tip_league(t) != league:
            continue

        hp, ap = _canon(raw.get("home_player")), _canon(raw.get("away_player"))
        if c1 not in (hp, ap) and c2 not in (hp, ap):
            continue

        if session and _tip_session(t, league) != session:
            continue

        # csapat-szűrő: játékosonként a HOZZÁ tartozó oldal csapatát nézzük
        ht, at = _canon(raw.get("home_team")), _canon(raw.get("away_team"))
        team_of = {hp: ht, ap: at}
        if ct1 and team_of.get(c1) not in (None, ct1):
            continue
        if ct2 and team_of.get(c2) not in (None, ct2):
            continue

        if {c1, c2} == {hp, ap}:
            pair_tips.append(t)
        for c in (c1, c2):
            if c in (hp, ap):
                solo_tips[c].append(t)

    return {
        "p1": p1, "p2": p2, "league": league, "session": session,
        "team1": team1, "team2": team2,
        "pair": {"n": len(pair_tips), "total": _calc(pair_tips),
                 "strategies": _rows(pair_tips, smap),
                 # az összes tipp, legújabb elöl (a H2H nézet listájához)
                 "tips": [_tip_row(t, smap) for t in sorted(
                     pair_tips, key=lambda x: str(x.get("saved_at") or ""),
                     reverse=True)]},
        "solo": {
            p1: {"n": len(solo_tips[c1]), "total": _calc(solo_tips[c1]),
                 "strategies": _rows(solo_tips[c1], smap)},
            p2: {"n": len(solo_tips[c2]), "total": _calc(solo_tips[c2]),
                 "strategies": _rows(solo_tips[c2], smap)},
        },
    }
