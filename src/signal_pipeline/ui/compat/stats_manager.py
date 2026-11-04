"""Daily statistics over the tips, as in the original tool (logic unchanged).

Only the data source and the strategy tabs differ: tips come from the pipeline database
(`tips_reader`), and every loaded strategy (Strategy Lab rule or Python plugin) is a tab.
"""

from PySide6.QtCore import QObject, QTimer, Signal

from .battle_day import current_battle_day, tip_battle_day, tip_is_night
from .runtime import pipeline

SHADOW_TAB_KEYS: set = set()


def get_strategy_tabs() -> list:
    """[(key, label, sources)] — "Összes" first, then one tab per loaded strategy."""
    return [("all", "Összes", None)] + [(s.id, s.name, [s.id]) for s in pipeline().loaded.strategies]


STRATEGY_TABS = [("all", "Összes", None)]  # backward compat (static importers)


def _today() -> str:
    return current_battle_day()


def _tip_session_date(tip: dict) -> str | None:
    """A tipp battle-napja — lásd core/battle_day.py."""
    return tip_battle_day(tip)


def _session_today() -> str:
    """Az éppen futó battle-nap: 06:30 előtt még a tegnapi tart."""
    return current_battle_day()


def _get_odds(tip: dict) -> float:
    raw  = tip.get("_raw") or {}
    pick = str(raw.get("pick") or tip.get("pick") or "").upper().strip()
    try:
        ov = float(raw.get("odds_over")  or 0)
        un = float(raw.get("odds_under") or 0)
    except (TypeError, ValueError):
        ov = un = 0.0
    if pick == "OVER":
        o = ov
    elif pick == "UNDER":
        o = un
    else:
        o = max(ov, un)
    if o > 1.0:
        return o
    # Fallback: közvetlen odds mező (BTTS/1X2 tippek)
    try:
        direct = float(raw.get("odds") or 0)
        if direct > 1.0:
            return direct
    except (TypeError, ValueError):
        pass
    return 2.0


def compute_daily_stats(tips: list, sources: list | None = None) -> list[dict]:
    """Tipp listából napi statisztika, opcionálisan source szűrővel + tényleges odds."""
    if sources:
        sl = [s.lower() for s in sources]
        tips = [t for t in tips if t.get("source", "").lower() in sl]

    by_date: dict[str, list] = {}
    for tip in tips:
        # Battle-nap szerint csoportosítunk (06:30-tól a másnap reggeli utolsó
        # éjszakai meccsig), nem a saved_at UTC naptári napja szerint — így a
        # hajnali éjszakai blokk oda kerül, ahová tartozik, és a dashboard
        # minden nézet ugyanazt a napot méri.
        by_date.setdefault(tip_battle_day(tip) or _today(), []).append(tip)

    daily = []
    for date_str in sorted(by_date.keys()):
        won = lost = push = 0
        units = 0.0

        for t in by_date[date_str]:
            status = str(t.get("status") or "").lower()
            odds   = _get_odds(t)

            if status == "win":
                won   += 1
                units += odds - 1.0
            elif status == "half_win":
                won   += 1
                units += (odds - 1.0) / 2.0
            elif status == "loss":
                lost  += 1
                units -= 1.0
            elif status == "half_loss":
                lost  += 1
                units -= 0.5
            elif status == "push":
                push  += 1

        total = won + lost + push
        roi   = round(units / total * 100, 2) if total > 0 else 0.0
        daily.append({
            "date":       date_str,
            "tips_total": total,
            "tips_won":   won,
            "tips_lost":  lost,
            "tips_push":  push,
            "units":      round(units, 2),
            "roi":        roi,
        })

    return daily


def compute_summary(daily: list[dict]) -> dict:
    total_tips  = sum(d["tips_total"] for d in daily)
    total_won   = sum(d["tips_won"]   for d in daily)
    total_lost  = sum(d["tips_lost"]  for d in daily)
    total_units = round(sum(d["units"] for d in daily), 2)
    roi = round(total_units / total_tips * 100, 2) if total_tips > 0 else 0.0
    return {
        "tips_total": total_tips,
        "tips_won":   total_won,
        "tips_lost":  total_lost,
        "units":      total_units,
        "roi":        roi,
    }


def get_daily_stats(days: int | None = None,
                    sources: list | None = None,
                    date_from: str | None = None,
                    date_to: str | None = None) -> list[dict]:
    """Napi statisztika. `days`: az utolsó N tippes nap; VAGY `date_from`/`date_to`
    (YYYY-MM-DD) explicit intervallum — ha intervallum van megadva, a `days` nem számít."""
    from .tips_reader import load_tips
    daily = compute_daily_stats(load_tips(), sources)
    if date_from or date_to:
        return [d for d in daily
                if (not date_from or d["date"] >= date_from)
                and (not date_to or d["date"] <= date_to)]
    return daily[-days:] if days else daily


def get_summary(days: int | None = None,
                sources: list | None = None,
                date_from: str | None = None,
                date_to: str | None = None) -> dict:
    return compute_summary(get_daily_stats(days, sources, date_from, date_to))


def get_last_completed_day_stats(sources: list | None = None) -> dict | None:
    """
    Az utolsó lezárt battle-nap statisztikája day/night bontásban. A nap 06:30-kor
    kezdődik és a másnap reggeli utolsó éjszakai meccsig tart (8p: 06:38 Wembley),
    a session pedig a jelzés napszakából jön (lásd compat/battle_day.py).
    """
    from .tips_reader import load_tips
    today_session = _session_today()
    tips = load_tips()

    if sources:
        sl = [s.lower() for s in sources]
        tips = [t for t in tips if t.get("source", "").lower() in sl]

    by_date: dict[str, list] = {}
    for tip in tips:
        date_str = _tip_session_date(tip)
        if not date_str or date_str >= today_session:
            continue
        by_date.setdefault(date_str, []).append(tip)

    if not by_date:
        return None

    last_date = max(by_date.keys())

    def _session(tip: dict) -> str:
        return "night" if tip_is_night(tip) else "day"

    def _calc(tip_list: list) -> dict:
        won = lost = push = 0
        units = 0.0
        for t in tip_list:
            status = str(t.get("status") or "").lower()
            odds   = _get_odds(t)
            if status == "win":
                won   += 1; units += odds - 1.0
            elif status == "half_win":
                won   += 1; units += (odds - 1.0) / 2.0
            elif status == "loss":
                lost  += 1; units -= 1.0
            elif status == "half_loss":
                lost  += 1; units -= 0.5
            elif status == "push":
                push  += 1
        total = won + lost + push
        roi   = round(units / total * 100, 2) if total > 0 else 0.0
        return {
            "total": total, "won": won, "lost": lost,
            "units": round(units, 2), "roi": roi,
        }

    all_tips    = by_date[last_date]
    day_tips    = [t for t in all_tips if _session(t) == "day"]
    night_tips  = [t for t in all_tips if _session(t) == "night"]

    return {
        "date":  last_date,
        "day":   _calc(day_tips),
        "night": _calc(night_tips),
    }


# Backward-compat — stats.json írás elhagyva, on-the-fly számítás van
def update_from_tips(tips: list, sources: list | None = None):
    pass


class StatsManager(QObject):
    stats_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.stats_updated.emit)
        self._timer.start(60000)
