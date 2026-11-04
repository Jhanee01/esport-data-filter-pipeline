"""Open odds offers from the pipeline database, in the original feed's entry format.

The original watched one JSONL file per bookmaker and league; here `path` is the league
("8min" / "12min") and `source` the odds source's name.
"""

from PySide6.QtCore import QObject, QTimer, Signal

from ...battle_day import to_local
from .runtime import pipeline


class FeedWatcher(QObject):
    new_entries = Signal(list)
    file_missing = Signal(bool)

    def __init__(self, parent=None, path: str = "8min", backfill_lines: int = 0, source: str | None = None):
        super().__init__(parent)
        self.fmt = path
        self.source = source
        self._seen: set[str] = set()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(3000)
        QTimer.singleShot(0, self._poll)

    def _poll(self):
        p = pipeline()
        q = "SELECT * FROM offers WHERE market = 'ou' AND (format = ? OR format IS NULL)"
        args = [self.fmt]
        if self.source:
            q += " AND source = ?"
            args.append(self.source)
        with p.lock:
            rows = p.conn.execute(q + " ORDER BY kickoff_utc", args).fetchall()
        self.file_missing.emit(not rows and not self._seen)
        grouped: dict[tuple, dict] = {}
        for r in rows:
            key = (r["kickoff_utc"], r["player1"], r["player2"], r["line"])
            entry = grouped.setdefault(
                key,
                {
                    "home": r["player1"],
                    "away": r["player2"],
                    "time": to_local(r["kickoff_utc"]).strftime("%H:%M"),
                    "market_struct": {"type": "O/U", "line": f"{r['line']:g}"},
                },
            )
            entry["market_struct"][r["pick"]] = f"{r['odds']:.2f}"
        fresh = []
        for key, entry in grouped.items():
            ms = entry["market_struct"]
            k = "|".join(map(str, key)) + f"|{ms.get('over')}|{ms.get('under')}"
            if k not in self._seen:
                self._seen.add(k)
                fresh.append(entry)
        if fresh:
            self.new_entries.emit(fresh)
