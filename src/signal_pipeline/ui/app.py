"""Desktop dashboard: the original tool's window and views on top of the pipeline.

The sidebar, Dashboard, Élő Feed, Tippek, Statisztika and Konzol views are the original
dashboard's code; they read their data through `ui.compat`, which serves the pipeline's
database in the shapes those views expect. The Strategy Lab and the H2H search are new
views in the same style.
"""

from __future__ import annotations

import logging
import sys
import threading
from importlib import resources

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import features
from ..config import Settings
from ..service import Pipeline
from ..sinks.telegram import Routing
from .compat import runtime

# Log record → console tab (see log_view.PROCESS_TABS); the first matching prefix wins
LOG_TABS = (
    ("signal_pipeline.collectors", "collector"),
    ("signal_pipeline.odds", "odds"),
    ("signal_pipeline.resolver", "resolver"),
    ("signal_pipeline.sinks", "telegram"),
    ("signal_pipeline.remote", "remote"),
    ("signal_pipeline", "engine"),
)
# health check level → state of the dashboard status card
CARD_STATE = {"ok": "running", "warn": "error", "fail": "error"}
GREEN, RED = "#3ba560", "#d44a3a"


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels([h.upper() for h in headers])
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    t.horizontalHeader().setStyleSheet("QHeaderView::section{padding:4px 6px;font-size:11px;}")
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    return t


def _fill(table: QTableWidget, rows: list[list]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))


class _Page(QWidget):
    """A view with the original layout: 24 px margins and a 16 pt title."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("contentView")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 24, 24, 24)
        self.root.setSpacing(14)
        lbl = QLabel(title)
        lbl.setObjectName("viewTitle")
        lbl.setFont(QFont("Segoe UI Semibold", 16))
        self.root.addWidget(lbl)


class LabView(_Page):
    def __init__(self, p: Pipeline):
        super().__init__("Stratégia Labor")
        from .lab import LabTab

        self.lab = LabTab(p)
        # scrollable, so the lab's form never forces the whole window to its height
        scroll = QScrollArea()
        scroll.setWidget(self.lab)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.root.addWidget(scroll, 1)


class H2HView(_Page):
    def __init__(self, p: Pipeline):
        super().__init__("H2H Kereső")
        from .dashboard_view import MiniCard

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
            "p1": MiniCard("Hazai nyert", "–", GREEN),
            "p2": MiniCard("Vendég nyert", "–", RED),
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
        lay.addWidget(QLabel("STRATÉGIÁNKÉNT"))
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


class _LogBridge(QObject, logging.Handler):
    """Log records → console tabs, delivered on the GUI thread through a Qt signal."""

    line = Signal(str, str)

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self)
        self.setFormatter(logging.Formatter("%(levelname)s %(message)s"))

    def emit(self, record: logging.LogRecord) -> None:
        tab = next((t for prefix, t in LOG_TABS if record.name.startswith(prefix)), "engine")
        self.line.emit(tab, self.format(record))


class MainWindow(QMainWindow):
    def __init__(self, p: Pipeline):
        super().__init__()
        self.p = p
        runtime.PIPELINE = p  # the original views read through ui.compat
        from .dashboard_view import DashboardView
        from .feed_view import FeedView
        from .log_view import LogView
        from .sidebar import Sidebar
        from .stats_view import StatsView
        from .tips_view import TipsView

        self.setWindowTitle("Signal pipeline")
        self.resize(1440, 900)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # same order as the original sidebar: Dashboard, Élő Feed, Stratégia Labor, Tippek,
        # Statisztika, H2H Kereső, Konzol
        self.dashboard_view = DashboardView()
        self.labview = LabView(p)
        self.log_view = LogView()
        self.views = [
            self.dashboard_view,
            FeedView(),
            self.labview,
            TipsView(),
            StatsView(),
            H2HView(p),
            self.log_view,
        ]
        self.stack = QStackedWidget()
        for view in self.views:
            self.stack.addWidget(view)
        self.sidebar = Sidebar()
        self.sidebar.nav_changed.connect(self.stack.setCurrentIndex)
        self.sidebar.settings_requested.connect(lambda: RoutingDialog(self.p, self).exec())
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.stack.setCurrentIndex(0)
        self.sidebar.set_active(0)

        # the dashboard's buttons drive the pipeline
        d = self.dashboard_view
        d.toggle_requested.connect(self._toggle)
        d.restart_requested.connect(self._restart)
        d.check_updates_requested.connect(self._collect_now)
        d._update_btn.setText("Eredmények frissítése")
        self.lab.changed.connect(self._strategies_changed)

        self._bridge = _LogBridge()
        self._bridge.line.connect(self.log_view.append_line)
        logging.getLogger().addHandler(self._bridge)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_status)
        self.timer.start(5000)
        self._refresh_status()

    @property
    def lab(self):
        return self.labview.lab

    def _toggle(self, name: str) -> None:
        if name == "pipeline":
            self.p.stop() if self.p.running else self.p.start()
        self._refresh_status()

    def _restart(self, name: str) -> None:
        if name == "results":
            self._collect_now()
        elif name == "strategies":
            self._strategies_changed()
        self._refresh_status()

    def _collect_now(self) -> None:
        threading.Thread(target=self.p.collect, daemon=True).start()

    def _strategies_changed(self) -> None:
        self.p.reload_strategies()
        self.lab.refresh()
        self.dashboard_view.refresh_tabs()
        self._refresh_status()

    def _refresh_status(self) -> None:
        last = self.p.last_cycle
        self.dashboard_view.on_status_changed(
            "pipeline",
            "running" if self.p.running else "stopped",
            f"Utolsó kör: {last.offers} ajánlat, {len(last.new_signals)} új jelzés" if last else "Nem fut",
        )
        for check in self.p.health():
            self.dashboard_view.on_status_changed(check.name, CARD_STATE[check.level], check.message)

    def closeEvent(self, event) -> None:
        logging.getLogger().removeHandler(self._bridge)
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
