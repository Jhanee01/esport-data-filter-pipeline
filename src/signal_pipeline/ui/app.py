"""Desktop dashboard (PySide6), in the look of the original tool: qt-material dark theme with
the #FDB900 accent, a sidebar on the left and the views stacked on the right. Hungarian UI."""

from __future__ import annotations

import json
import sys
import threading
from datetime import UTC, datetime, timedelta
from importlib import resources

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, features
from ..battle_day import session_of, to_local
from ..config import Settings
from ..resolver import summarise
from ..service import Pipeline
from ..sinks.telegram import Routing
from .lab import LabTab
from .widgets import (
    LOG_PANE,
    OUTLINE_BTN,
    SCROLL_QSS,
    TAB_ACTIVE,
    TAB_INACTIVE,
    ContentView,
    MiniCard,
    Sidebar,
    SignalCard,
    StatusCard,
    card_title,
)

NAV = ["Dashboard", "Élő Feed", "Stratégia Labor", "Tippek", "Statisztika", "H2H Kereső", "Konzol"]
GREEN, RED = "#3ba560", "#d44a3a"
MARKET_HU = {"ou": "Gólszám", "1x2": "Kimenetel", "btts": "BTTS"}
PICK_HU = {
    "over": "Over",
    "under": "Under",
    "home": "Hazai",
    "draw": "Döntetlen",
    "away": "Vendég",
    "yes": "Igen",
    "no": "Nem",
}


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels([h.upper() for h in headers])
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    # qt-material pads header sections generously; keep the labels from being clipped
    t.horizontalHeader().setStyleSheet("QHeaderView::section{padding:4px 6px;font-size:11px;}")
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    return t


def _fill(table: QTableWidget, rows: list[list], colors: dict[int, str] | None = None) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem("" if value is None else str(value))
            if colors and c in colors and value not in (None, ""):
                item.setForeground(QColor(colors[c]))
            table.setItem(r, c, item)


def _pick(row) -> str:
    line = f" {row['line']:g}" if row["line"] is not None else ""
    return f"{MARKET_HU.get(row['market'], row['market'])} · {PICK_HU.get(row['pick'], row['pick'])}{line}"


# ── views ──────────────────────────────────────────────────────────────────────────────


class DashboardView(ContentView):
    def __init__(self, p: Pipeline):
        super().__init__("Dashboard")
        self.p = p
        version = QLabel(f"v{__version__}")
        version.setFont(QFont("Segoe UI", 10))
        version.setStyleSheet("color: #ffffff;")
        self.collect_btn = QPushButton("Eredmények frissítése")
        self.collect_btn.setFixedHeight(28)
        self.collect_btn.setStyleSheet(OUTLINE_BTN)
        self.collect_btn.clicked.connect(lambda: threading.Thread(target=self.p.collect, daemon=True).start())
        self.title_row.addWidget(version)
        self.title_row.addWidget(self.collect_btn)

        top = QHBoxLayout()
        top.setSpacing(14)
        status_col = QVBoxLayout()
        status_col.setSpacing(8)
        status_col.addWidget(card_title("Rendszer státusz"))
        self.cards = {
            "pipeline": StatusCard("pipeline", "Jelzés-motor", toggleable=True),
            "results": StatusCard("results", "Battle gyűjtő"),
            "odds": StatusCard("odds", "Odds-forrás"),
            "strategies": StatusCard("strategies", "Stratégiák"),
            "telegram": StatusCard("telegram", "Telegram"),
        }
        self.cards["pipeline"].toggle_clicked.connect(self._toggle)
        inner = QWidget()
        inner.setObjectName("transparentWidget")
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 4, 0)
        il.setSpacing(8)
        for card in self.cards.values():
            il.addWidget(card)
        il.addStretch()
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(252)
        scroll.setStyleSheet(SCROLL_QSS)
        status_col.addWidget(scroll)
        top.addLayout(status_col, 3)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(card_title("Teljesítmény — utolsó 24 óra"))
        grid = QGridLayout()
        grid.setSpacing(10)
        self.mini = {
            "signals": MiniCard("Jelzés"),
            "won": MiniCard("Nyertes", color=GREEN),
            "lost": MiniCard("Vesztes", color=RED),
            "pending": MiniCard("Folyamatban", color="#f2cc0c"),
            "hit": MiniCard("Találati arány"),
            "units": MiniCard("Egység"),
        }
        for i, card in enumerate(self.mini.values()):
            grid.addWidget(card, i // 3, i % 3)
        right.addLayout(grid)
        right.addWidget(card_title("Stratégiák"))
        self.table = _table(["Stratégia", "Jelzés", "Ny–V–P", "Folyamatban", "Találati arány", "Egység"])
        right.addWidget(self.table, 1)
        top.addLayout(right, 5)
        self.root.addLayout(top, 1)

    def _toggle(self, _name: str) -> None:
        self.p.stop() if self.p.running else self.p.start()
        self.refresh()

    def refresh(self) -> None:
        last = self.p.last_cycle
        self.cards["pipeline"].update_status(
            "running" if self.p.running else "stopped",
            (f"Utolsó kör: {last.offers} ajánlat, {len(last.new_signals)} új jelzés" if last else "Nem fut"),
        )
        for check in self.p.health():
            if check.name in self.cards:
                self.cards[check.name].update_status(check.level, check.message)
        since = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        with self.p.lock:
            day = summarise(self.p.conn, since_utc=since)
            all_time = summarise(self.p.conn)
        won, lost = sum(s.won for s in day), sum(s.lost for s in day)
        units = sum(s.units for s in day)
        self.mini["signals"].set_value(str(sum(s.signals for s in day)))
        self.mini["won"].set_value(str(won))
        self.mini["lost"].set_value(str(lost))
        self.mini["pending"].set_value(str(sum(s.pending for s in day)))
        self.mini["hit"].set_value(f"{won / (won + lost):.0%}" if won + lost else "–")
        self.mini["units"].set_value(f"{units:+.2f}", GREEN if units > 0 else RED if units < 0 else "#d9d9d9")
        _fill(
            self.table,
            [
                [
                    s.strategy_id,
                    s.signals,
                    f"{s.won}–{s.lost}–{s.push}",
                    s.pending,
                    f"{s.hit_rate:.1%}" if s.hit_rate is not None else "—",
                    f"{s.units:+.2f}",
                ]
                for s in all_time
            ],
        )


class FeedView(ContentView):
    """The open offers the odds source returned, soonest kick-offs first."""

    def __init__(self, p: Pipeline):
        super().__init__("Élő Feed")
        self.p = p
        self.count = QLabel("")
        self.count.setStyleSheet("color: #8d8d9f; font-size: 12px;")
        self.title_row.addWidget(self.count)
        self.table = _table(["Kezdés", "Pálya", "Hazai", "Vendég", "Piac", "Odds", "Forrás"])
        self.root.addWidget(self.table, 1)

    def refresh(self) -> None:
        now = datetime.now(UTC).isoformat()
        with self.p.lock:
            rows = self.p.conn.execute(
                "SELECT * FROM offers WHERE kickoff_utc > ? ORDER BY kickoff_utc, player1, market, pick"
                " LIMIT 400",
                (now,),
            ).fetchall()
        self.count.setText(f"{len(rows)} nyitott ajánlat")
        _fill(
            self.table,
            [
                [
                    to_local(r["kickoff_utc"]).strftime("%H:%M"),
                    r["venue"],
                    r["player1"],
                    r["player2"],
                    _pick(r),
                    f"{r['odds']:.2f}",
                    r["source"],
                ]
                for r in rows
            ],
        )


class LabView(ContentView):
    def __init__(self, p: Pipeline):
        super().__init__("Stratégia Labor")
        self.lab = LabTab(p)
        self.root.addWidget(self.lab, 1)


class TipsView(ContentView):
    """Signals as cards, filterable like the original tips view."""

    FILTERS = [("all", "Mind"), ("pending", "Folyamatban"), ("settled", "Lezárt")]

    def __init__(self, p: Pipeline):
        super().__init__("Tippek")
        self.p = p
        self.filter = "all"
        self.count = QLabel("")
        self.count.setStyleSheet("color: #8d8d9f; font-size: 12px;")
        self.title_row.addWidget(self.count)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.tab_btns = {}
        for key, label in self.FILTERS:
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            bar.addWidget(btn)
            self.tab_btns[key] = btn
        bar.addStretch()
        self.root.addLayout(bar)
        self.cards = QWidget()
        self.cards.setStyleSheet("background: transparent;")
        self.cards_lay = QVBoxLayout(self.cards)
        self.cards_lay.setSpacing(8)
        self.cards_lay.setContentsMargins(0, 0, 4, 0)
        scroll = QScrollArea()
        scroll.setWidget(self.cards)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(SCROLL_QSS)
        self.root.addWidget(scroll, 1)
        self._last_key = None
        self._set_filter("all")

    def _set_filter(self, key: str) -> None:
        self.filter = key
        for k, btn in self.tab_btns.items():
            btn.setStyleSheet(TAB_ACTIVE if k == key else TAB_INACTIVE)
        self._last_key = None
        self.refresh()

    def refresh(self) -> None:
        where = {"all": "", "pending": "WHERE status = 'pending'", "settled": "WHERE status != 'pending'"}[
            self.filter
        ]
        with self.p.lock:
            rows = self.p.conn.execute(
                f"SELECT * FROM signals {where} ORDER BY kickoff_utc DESC LIMIT 150"
            ).fetchall()
        key = (self.filter, tuple((r["id"], r["status"]) for r in rows))
        if key == self._last_key:
            return  # nothing changed: don't rebuild the cards (keeps the scroll position)
        self._last_key = key
        while self.cards_lay.count():
            w = self.cards_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for r in rows:
            score = f"{r['score1']}–{r['score2']}" if r["score1"] is not None else "—"
            reason = json.loads(r["details"] or "{}").get("reason", "")
            self.cards_lay.addWidget(
                SignalCard(
                    f"{r['player1']}  vs  {r['player2']}",
                    r["status"],
                    [
                        ("Kezdés", to_local(r["kickoff_utc"]).strftime("%m-%d %H:%M")),
                        ("Tipp", _pick(r)),
                        ("Odds", f"{r['odds']:.2f}" if r["odds"] else "—"),
                        ("Eredmény", score),
                        ("Küldve", "igen" if r["sent_at"] else "csak helyben"),
                    ],
                    r["strategy_id"],
                    reason,
                )
            )
        self.cards_lay.addStretch()
        self.count.setText(f"{len(rows)} tipp")


class StatsView(ContentView):
    def __init__(self, p: Pipeline):
        super().__init__("Statisztika")
        self.p = p
        grid = QGridLayout()
        grid.setSpacing(10)
        self.mini = {
            "signals": MiniCard("Összes jelzés"),
            "hit": MiniCard("Találati arány"),
            "units": MiniCard("Egység (1 egységes tét)"),
            "roi": MiniCard("ROI"),
        }
        for i, card in enumerate(self.mini.values()):
            grid.addWidget(card, 0, i)
        self.root.addLayout(grid)
        self.root.addWidget(card_title("Stratégiánként"))
        self.table = _table(
            [
                "Stratégia",
                "Jelzés",
                "Nyertes",
                "Vesztes",
                "Push",
                "Érvénytelen",
                "Találati arány",
                "Egység",
                "ROI",
            ]
        )
        self.root.addWidget(self.table, 1)

    def refresh(self) -> None:
        with self.p.lock:
            rows = summarise(self.p.conn)
        won, lost = sum(s.won for s in rows), sum(s.lost for s in rows)
        units = sum(s.units for s in rows)
        self.mini["signals"].set_value(str(sum(s.signals for s in rows)))
        self.mini["hit"].set_value(f"{won / (won + lost):.1%}" if won + lost else "–")
        self.mini["units"].set_value(f"{units:+.2f}", GREEN if units > 0 else RED if units < 0 else None)
        self.mini["roi"].set_value(f"{units / (won + lost):+.1%}" if won + lost else "–")
        _fill(
            self.table,
            [
                [
                    s.strategy_id,
                    s.signals,
                    s.won,
                    s.lost,
                    s.push,
                    s.void,
                    f"{s.hit_rate:.1%}" if s.hit_rate is not None else "—",
                    f"{s.units:+.2f}",
                    f"{s.roi:+.1%}" if s.roi is not None else "—",
                ]
                for s in rows
            ],
            colors={2: GREEN, 3: RED},
        )


class H2HView(ContentView):
    def __init__(self, p: Pipeline):
        super().__init__("H2H Kereső")
        self.p = p
        row = QHBoxLayout()
        self.a, self.b = QLineEdit(), QLineEdit()
        self.a.setPlaceholderText("Hazai játékos")
        self.b.setPlaceholderText("Vendég játékos")
        go = QPushButton("Keresés")
        go.clicked.connect(self._search)
        self.b.returnPressed.connect(self._search)
        row.addWidget(self.a)
        row.addWidget(self.b)
        row.addWidget(go)
        self.root.addLayout(row)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.mini = {
            "n": MiniCard("Meccs"),
            "goals": MiniCard("Gólátlag"),
            "over": MiniCard("Over 5.5"),
            "btts": MiniCard("BTTS"),
            "p1": MiniCard("Hazai nyert", color=GREEN),
            "p2": MiniCard("Vendég nyert", color=RED),
        }
        for i, card in enumerate(self.mini.values()):
            grid.addWidget(card, 0, i)
        self.root.addLayout(grid)
        self.table = _table(["Dátum", "Pálya", "Hazai", "Eredmény", "Vendég"])
        self.root.addWidget(self.table, 1)

    def _search(self) -> None:
        a, b = self.a.text().strip(), self.b.text().strip()
        if not a or not b:
            return
        with self.p.lock:
            f = features.compute(self.p.conn, a, b, "9999-12-31", line=5.5, h2h_window=50)
            rows = self.p.conn.execute(
                "SELECT * FROM matches WHERE (player1 = ? COLLATE NOCASE AND player2 = ? COLLATE NOCASE)"
                " OR (player1 = ? COLLATE NOCASE AND player2 = ? COLLATE NOCASE)"
                " ORDER BY start_utc DESC LIMIT 50",
                (a, b, b, a),
            ).fetchall()

        def pct(v):
            return "–" if v is None else f"{v:.0%}"

        self.mini["n"].set_value(str(f.h2h_n))
        self.mini["goals"].set_value(f"{f.h2h_avg_goals:.2f}" if f.h2h_avg_goals is not None else "–")
        self.mini["over"].set_value(pct(f.h2h_over_rate))
        self.mini["btts"].set_value(pct(f.h2h_btts_rate))
        self.mini["p1"].set_value(pct(f.h2h_p1_win_rate))
        self.mini["p2"].set_value(pct(f.h2h_p2_win_rate))
        _fill(
            self.table,
            [
                [
                    f"{r['local_date']} {r['local_time']}",
                    r["venue"],
                    r["player1"],
                    f"{r['score1']}–{r['score2']}",
                    r["player2"],
                ]
                for r in rows
            ],
        )


class ConsoleView(ContentView):
    def __init__(self, p: Pipeline):
        super().__init__("Konzol")
        self.p = p
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 10))
        self.text.setStyleSheet(LOG_PANE)
        self.text.setMaximumBlockCount(2000)
        self.root.addWidget(self.text, 1)
        self._shown = 0

    def refresh(self) -> None:
        lines = list(self.p.ring.lines)
        if len(lines) != self._shown:
            self.text.setPlainText("\n".join(lines))
            self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())
            self._shown = len(lines)


class RoutingDialog(QDialog):
    """Gear button: which Telegram chat each signal goes to. Empty = record locally only."""

    def __init__(self, p: Pipeline, parent=None):
        super().__init__(parent)
        self.p = p
        self.setWindowTitle("Beállítások — Telegram-csatornák")
        self.resize(620, 520)
        self.default = QLineEdit()
        self.sessions = {s: QLineEdit() for s in ("day", "afternoon", "night")}
        self.by_strategy = _table(["Stratégia", "Chat ID"])
        self.by_strategy.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)
        form = QFormLayout()
        form.addRow("Alapértelmezett chat ID", self.default)
        for s, label in (("day", "Nappal"), ("afternoon", "Délután"), ("night", "Éjszaka")):
            form.addRow(f"{label} chat ID", self.sessions[s])
        save = QPushButton("Mentés")
        save.clicked.connect(self._save)
        hint = QLabel(
            "A legpontosabb szabály nyer: stratégia → napszak → alapértelmezett. "
            "Üres mező = a jelzés csak helyben rögzül."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #8d8d9f;")
        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addLayout(form)
        lay.addWidget(card_title("Stratégiánként"))
        lay.addWidget(self.by_strategy)
        lay.addWidget(save)
        r = Routing.load(p.settings.routing_path)
        self.default.setText(r.default)
        for s, box in self.sessions.items():
            box.setText(r.by_session.get(s, ""))
        ids = [s.id for s in p.loaded.strategies]
        self.by_strategy.setRowCount(len(ids))
        for i, sid in enumerate(ids):
            item = QTableWidgetItem(sid)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.by_strategy.setItem(i, 0, item)
            self.by_strategy.setItem(i, 1, QTableWidgetItem(r.by_strategy.get(sid, "")))

    def _save(self) -> None:
        by_strategy = {}
        for i in range(self.by_strategy.rowCount()):
            sid, chat = self.by_strategy.item(i, 0), self.by_strategy.item(i, 1)
            if sid and chat and chat.text().strip():
                by_strategy[sid.text().strip()] = chat.text().strip()
        Routing(
            default=self.default.text().strip(),
            by_session={s: b.text().strip() for s, b in self.sessions.items() if b.text().strip()},
            by_strategy=by_strategy,
        ).save(self.p.settings.routing_path)
        self.p.reload_routing()
        QMessageBox.information(self, "Beállítások", "Mentve.")
        self.accept()


# ── main window ────────────────────────────────────────────────────────────────────────


class MainWindow(QMainWindow):
    def __init__(self, p: Pipeline):
        super().__init__()
        self.p = p
        self.setWindowTitle("Signal pipeline")
        self.resize(1440, 900)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.views = [
            DashboardView(p),
            FeedView(p),
            LabView(p),
            TipsView(p),
            StatsView(p),
            H2HView(p),
            ConsoleView(p),
        ]
        self.stack = QStackedWidget()
        for view in self.views:
            self.stack.addWidget(view)
        self.sidebar = Sidebar(NAV)
        self.sidebar.nav_changed.connect(self._show)
        self.sidebar.settings_requested.connect(lambda: RoutingDialog(self.p, self).exec())
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.lab.changed.connect(self._strategies_changed)
        self.sidebar.set_active(0)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)
        self.refresh()

    @property
    def lab(self) -> LabTab:
        return self.views[2].lab

    def _show(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.refresh()

    def _strategies_changed(self) -> None:
        self.p.reload_strategies()
        self.lab.refresh()
        self.refresh()

    def refresh(self) -> None:
        self.stack.currentWidget().refresh()
        self.sidebar.set_session(session_of(datetime.now().strftime("%H:%M"), self.p.settings.sessions))

    def closeEvent(self, event) -> None:
        self.p.close()
        super().closeEvent(event)


def apply_theme(app: QApplication) -> None:
    """qt-material dark theme with the #FDB900 accent, exactly like the original dashboard."""
    try:
        from qt_material import apply_stylesheet
    except ImportError:  # optional dependency: plain Qt look without it
        return
    with resources.as_file(resources.files("signal_pipeline.ui").joinpath("theme_fdb900.xml")) as theme:
        apply_stylesheet(app, theme=str(theme))


def run_app(settings: Settings) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Signal pipeline")
    apply_theme(app)
    pipeline = Pipeline(settings)
    if settings.remote_token:  # phone remote only when a token is configured
        from ..remote.server import serve_in_background

        serve_in_background(pipeline)
    window = MainWindow(pipeline)
    window.show()
    return app.exec()
