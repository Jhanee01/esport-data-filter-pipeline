"""Signals from the pipeline database, in the tip format the original views expect."""

import json

from PySide6.QtCore import QObject, QTimer, Signal

from ...battle_day import battle_day, to_local
from .runtime import pipeline

_STATUS = {"won": "win", "lost": "loss", "push": "push", "void": "void", "pending": "pending"}
_PICK_LABEL = {"home": "Hazai", "draw": "Döntetlen", "away": "Vendég", "yes": "BTTS igen", "no": "BTTS nem"}


def _threshold(edge_pct: float | None) -> str:
    if edge_pct is None:
        return "unknown"
    return "high" if edge_pct >= 10 else "mid" if edge_pct >= 5 else "low"


def _tip(r, names: dict) -> dict:
    local = to_local(r["kickoff_utc"])
    details = json.loads(r["details"] or "{}")
    edge = details.get("edge")
    pct = round(edge * 100, 2) if isinstance(edge, (int, float)) else None
    ou = r["market"] == "ou"
    pick = r["pick"].upper() if ou else r["pick"]
    score = f"{r['score1']}–{r['score2']}" if r["score1"] is not None else ""
    name = names.get(r["strategy_id"], r["strategy_id"])
    raw = {
        "pick": pick,
        "odds": r["odds"],
        "odds_over": r["odds"] if r["pick"] == "over" else None,
        "odds_under": r["odds"] if r["pick"] == "under" else None,
        "pick_label": None if ou else _PICK_LABEL.get(r["pick"], r["pick"]),
        "date": local.strftime("%Y-%m-%d"),
        "time": local.strftime("%H:%M"),
        "battle_day": battle_day(local),
        "session": r["session"] or "day",
        "strategy_name": name,
        "strategy_label": name,
        "home_player": r["player1"],
        "away_player": r["player2"],
        "venue": r["venue"],
        "format": r["format"],
        "reason": details.get("reason", ""),
        "sent": bool(r["sent_at"]),
    }
    return {
        "match": f"{r['team1'] or r['player1']} vs {r['team2'] or r['player2']}",
        "player": f"{r['player1']} / {r['player2']}",
        "time": raw["time"],
        "date": raw["date"],
        "pick": pick,
        "line": f"{r['line']:g}" if r["line"] is not None else None,
        "value_pct": pct,
        "threshold": _threshold(pct),
        "status": _STATUS.get(r["status"], r["status"]),
        "source": r["strategy_id"],
        "saved_at": r["created_at"] or "",
        "outcome": f"Eredmény: {score}" if score else "",
        "_raw": raw,
    }


def load_tips() -> list[dict]:
    p = pipeline()
    names = {s.id: s.name for s in p.loaded.strategies}
    with p.lock:
        rows = p.conn.execute("SELECT * FROM signals ORDER BY created_at DESC").fetchall()
    return [_tip(r, names) for r in rows]


class TipsReader(QObject):
    """Polls the signals table and emits the tip list when it changes (as the original did)."""

    tips_updated = Signal(list)
    new_pending_tips = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_sig = ""
        self._last_pending = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(10000)
        QTimer.singleShot(0, self._poll)

    def _poll(self):
        tips = load_tips()
        pending = sum(1 for t in tips if t["status"] == "pending")
        won = sum(1 for t in tips if t["status"] == "win")
        lost = sum(1 for t in tips if t["status"] == "loss")
        sig = f"{len(tips)}:{pending}:{won}:{lost}"
        if sig != self._last_sig:
            self._last_sig = sig
            self.tips_updated.emit(tips)
        if pending > self._last_pending:
            self.new_pending_tips.emit()
        self._last_pending = pending

    def force_refresh(self):
        self._last_sig = ""
        self._poll()
