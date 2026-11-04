"""Desktop dashboard (PySide6). Hungarian UI, like the original tool it was extracted from."""

from __future__ import annotations

import sys
import threading

from PySide6.QtCore import QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import features
from ..battle_day import to_local
from ..config import Settings
from ..resolver import summarise
from ..service import Pipeline
from ..sinks.telegram import Routing
from .lab import LabTab

LEVEL_COLORS = {"ok": "#3fb950", "warn": "#d29922", "fail": "#f85149"}
STATUS_HU = {
    "pending": "folyamatban",
    "won": "nyert",
    "lost": "vesztett",
    "push": "visszajár",
    "void": "érvénytelen",
}
STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 13px; }
QMainWindow, QWidget#root { background: #151515; color: #e6e6e6; }
QLabel, QCheckBox, QGroupBox { color: #d8d8d8; }
QTabWidget::pane { border: 1px solid #2a2a2a; }
QTabBar::tab { background: #1e1e1e; color: #bbb; padding: 8px 16px; }
QTabBar::tab:selected { background: #2a2a2a; color: #fff; }
QPushButton { background: #2cc9b4; color: #111; border: 0; border-radius: 6px; padding: 7px 14px; font-weight: 600; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QPlainTextEdit, QListWidget, QTableWidget {
  background: #1e1e1e; color: #e6e6e6; border: 1px solid #333; border-radius: 4px; }
QHeaderView::section { background: #232323; color: #bbb; border: 0; padding: 4px; }
QGroupBox { border: 1px solid #2a2a2a; margin-top: 12px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #aaa; }
"""


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    return t


def _fill(table: QTableWidget, rows: list[list]) -> None:
    table.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            table.setItem(r, c, QTableWidgetItem("" if value is None else str(value)))


class OverviewTab(QWidget):
    def __init__(self, p: Pipeline):
        super().__init__()
        self.p = p
        self.toggle = QPushButton()
        self.toggle.clicked.connect(self._toggle)
        self.collect_btn = QPushButton("Eredmények frissítése most")
        self.collect_btn.clicked.connect(lambda: threading.Thread(target=self.p.collect, daemon=True).start())
        self.state = QLabel()
        top = QHBoxLayout()
        top.addWidget(self.state)
        top.addStretch()
        top.addWidget(self.collect_btn)
        top.addWidget(self.toggle)
        self.checks = QListWidget()
        self.summary = _table(["Stratégia", "Jelzés", "Ny–V–P", "Folyamatban", "Találati arány", "Egység"])
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(QLabel("Állapot"))
        lay.addWidget(self.checks, 1)
        lay.addWidget(QLabel("Stratégiák eredménye (1 egységes tétekkel)"))
        lay.addWidget(self.summary, 2)

    def _toggle(self) -> None:
        self.p.stop() if self.p.running else self.p.start()
        self.refresh()

    def refresh(self) -> None:
        self.toggle.setText("■ Leállítás" if self.p.running else "▶ Indítás")
        last = self.p.last_cycle
        self.state.setText(
            ("● Fut" if self.p.running else "○ Leállítva")
            + (f" · utolsó kör: {last.offers} ajánlat, {len(last.new_signals)} új jelzés" if last else "")
        )
        self.checks.clear()
        for c in self.p.health():
            item = QListWidgetItem(f"{c.name}: {c.message}")
            item.setForeground(QColor(LEVEL_COLORS[c.level]))
            self.checks.addItem(item)
        with self.p.lock:
            rows = summarise(self.p.conn)
        _fill(
            self.summary,
            [
                [
                    s.strategy_id,
                    s.signals,
                    f"{s.won}–{s.lost}–{s.push}",
                    s.pending,
                    f"{s.hit_rate:.1%}" if s.hit_rate is not None else "—",
                    f"{s.units:+.2f}",
                ]
                for s in rows
            ],
        )


class SignalsTab(QWidget):
    def __init__(self, p: Pipeline):
        super().__init__()
        self.p = p
        self.table = _table(["Kezdés", "Stratégia", "Meccs", "Tipp", "Odds", "Állapot", "Eredmény", "Küldés"])
        lay = QVBoxLayout(self)
        lay.addWidget(self.table)

    def refresh(self) -> None:
        with self.p.lock:
            rows = self.p.conn.execute("SELECT * FROM signals ORDER BY kickoff_utc DESC LIMIT 300").fetchall()
        out = []
        for s in rows:
            line = f" {s['line']:g}" if s["line"] is not None else ""
            score = f"{s['score1']}–{s['score2']}" if s["score1"] is not None else ""
            sent = "✓" if s["sent_at"] else (s["send_error"] or "csak helyben")
            out.append(
                [
                    to_local(s["kickoff_utc"]).strftime("%m-%d %H:%M"),
                    s["strategy_id"],
                    f"{s['player1']} – {s['player2']}",
                    f"{s['market']} {s['pick']}{line}",
                    f"{s['odds']:.2f}" if s["odds"] else "",
                    STATUS_HU.get(s["status"], s["status"]),
                    score,
                    sent,
                ]
            )
        _fill(self.table, out)


class H2HTab(QWidget):
    def __init__(self, p: Pipeline):
        super().__init__()
        self.p = p
        self.a, self.b = QLineEdit(), QLineEdit()
        go = QPushButton("Keresés")
        go.clicked.connect(self._search)
        form = QFormLayout()
        form.addRow("Hazai játékos", self.a)
        form.addRow("Vendég játékos", self.b)
        form.addRow(go)
        self.stats = QLabel()
        self.stats.setWordWrap(True)
        self.table = _table(["Dátum", "Pálya", "Hazai", "Eredmény", "Vendég"])
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.stats)
        lay.addWidget(self.table)

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
            return "—" if v is None else f"{v:.0%}"

        self.stats.setText(
            f"Utolsó {f.h2h_n} egymás elleni meccs · gólátlag {f.h2h_avg_goals or 0:.2f} · over 5.5 "
            f"{pct(f.h2h_over_rate)} · BTTS {pct(f.h2h_btts_rate)} · {a} nyert {pct(f.h2h_p1_win_rate)}, "
            f"döntetlen {pct(f.h2h_draw_rate)}, {b} nyert {pct(f.h2h_p2_win_rate)}"
        )
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


class LogTab(QWidget):
    def __init__(self, p: Pipeline):
        super().__init__()
        self.p = p
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        QVBoxLayout(self).addWidget(self.text)

    def refresh(self) -> None:
        self.text.setPlainText("\n".join(self.p.ring.lines))
        self.text.verticalScrollBar().setValue(self.text.verticalScrollBar().maximum())


class RoutingTab(QWidget):
    """Which Telegram chat each signal goes to. Empty = record locally only."""

    def __init__(self, p: Pipeline):
        super().__init__()
        self.p = p
        self.default = QLineEdit()
        self.sessions = {s: QLineEdit() for s in ("day", "afternoon", "night")}
        self.by_strategy = _table(["Stratégia azonosító", "Chat ID"])
        self.by_strategy.setEditTriggers(QTableWidget.AllEditTriggers)
        save = QPushButton("Mentés")
        save.clicked.connect(self._save)
        form = QFormLayout()
        form.addRow("Alapértelmezett chat ID", self.default)
        for s, label in (("day", "Nappal"), ("afternoon", "Délután"), ("night", "Éjszaka")):
            form.addRow(f"{label} chat ID", self.sessions[s])
        lay = QVBoxLayout(self)
        lay.addWidget(
            QLabel(
                "A legpontosabb szabály nyer: stratégia → napszak → alapértelmezett. "
                "Üres mező = a jelzés csak helyben rögzül."
            )
        )
        lay.addLayout(form)
        lay.addWidget(QLabel("Stratégiánként"))
        lay.addWidget(self.by_strategy)
        lay.addWidget(save)
        self._load()

    def _load(self) -> None:
        r = Routing.load(self.p.settings.routing_path)
        self.default.setText(r.default)
        for s, box in self.sessions.items():
            box.setText(r.by_session.get(s, ""))
        ids = [s.id for s in self.p.loaded.strategies]
        self.by_strategy.setRowCount(len(ids))
        for i, sid in enumerate(ids):
            self.by_strategy.setItem(i, 0, QTableWidgetItem(sid))
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
        QMessageBox.information(self, "Csatornák", "Mentve.")


class MainWindow(QMainWindow):
    def __init__(self, p: Pipeline):
        super().__init__()
        self.p = p
        self.setWindowTitle("Signal pipeline")
        self.resize(1200, 780)
        self.overview, self.signals = OverviewTab(p), SignalsTab(p)
        self.lab, self.h2h, self.log = LabTab(p), H2HTab(p), LogTab(p)
        self.routing = RoutingTab(p)
        self.lab.changed.connect(self._strategies_changed)
        tabs = QTabWidget()
        for widget, title in (
            (self.overview, "Áttekintés"),
            (self.signals, "Jelzések"),
            (self.lab, "Stratégia labor"),
            (self.h2h, "H2H"),
            (self.log, "Napló"),
            (self.routing, "Csatornák"),
        ):
            tabs.addTab(widget, title)
        self.setCentralWidget(tabs)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(5000)
        self.refresh()

    def _strategies_changed(self) -> None:
        self.p.reload_strategies()
        self.lab.refresh()
        self.refresh()

    def refresh(self) -> None:
        for tab in (self.overview, self.signals, self.log):
            tab.refresh()

    def closeEvent(self, event) -> None:
        self.p.close()
        super().closeEvent(event)


def run_app(settings: Settings) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    pipeline = Pipeline(settings)
    if settings.remote_token:  # phone remote only when a token is configured
        from ..remote.server import serve_in_background

        serve_in_background(pipeline)
    window = MainWindow(pipeline)
    window.show()
    return app.exec()
