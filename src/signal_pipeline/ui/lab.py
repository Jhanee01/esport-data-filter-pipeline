"""Strategy Lab tab: build a rule from conditions, save it, and backtest it."""

from __future__ import annotations

import threading
from datetime import date, timedelta

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from .. import backtest
from ..features import FEATURE_NAMES
from ..markets import PICKS
from ..store import connect
from ..strategies import RuleError, RuleStrategy, delete_rule, save_rule
from ..strategies.rule import OPS

FEATURE_LABELS = {
    "h2h_n": "Egymás elleni meccsek száma",
    "h2h_avg_goals": "H2H gólátlag",
    "h2h_over_rate": "H2H over-arány (a vonal felett)",
    "h2h_btts_rate": "H2H BTTS-arány",
    "h2h_p1_win_rate": "H2H hazai győzelmi arány",
    "h2h_draw_rate": "H2H döntetlenarány",
    "h2h_p2_win_rate": "H2H vendég győzelmi arány",
    "p1_n": "Hazai játékos meccsszáma (forma)",
    "p1_avg_scored": "Hazai lőtt gól átlag",
    "p1_avg_conceded": "Hazai kapott gól átlag",
    "p2_n": "Vendég játékos meccsszáma (forma)",
    "p2_avg_scored": "Vendég lőtt gól átlag",
    "p2_avg_conceded": "Vendég kapott gól átlag",
    "odds": "Odds",
    "implied_prob": "Odds szerinti valószínűség",
    "line": "Vonal (O/U)",
}
MARKET_LABELS = {"ou": "Gólszám (O/U)", "1x2": "Kimenetel (1X2)", "btts": "Mindkét csapat gólt szerez"}


class _BacktestSignals(QObject):
    done = Signal(object)


class LabTab(QWidget):
    changed = Signal()  # strategies saved or deleted → pipeline should reload

    def __init__(self, pipeline):
        super().__init__()
        self.p = pipeline
        self._bt = _BacktestSignals()
        self._bt.done.connect(self._show_backtest)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._load_selected)
        new_btn = QPushButton("Új stratégia")
        new_btn.clicked.connect(self._new)
        left = QVBoxLayout()
        left.addWidget(QLabel("Stratégiák (labor + Python pluginok)"))
        left.addWidget(self.list)
        left.addWidget(new_btn)

        self.sid, self.name = QLineEdit(), QLineEdit()
        self.enabled = QCheckBox("Aktív")
        self.market = QComboBox()
        for key, label in MARKET_LABELS.items():
            self.market.addItem(label, key)
        self.pick = QComboBox()
        self.market.currentIndexChanged.connect(self._fill_picks)
        self.fmt = QComboBox()
        for label, value in (("Mindkettő", None), ("8 perc", "8min"), ("12 perc", "12min")):
            self.fmt.addItem(label, value)
        self.sessions = {
            s: QCheckBox(label)
            for s, label in (("day", "Nappal"), ("afternoon", "Délután"), ("night", "Éjszaka"))
        }
        sess_row = QHBoxLayout()
        for cb in self.sessions.values():
            sess_row.addWidget(cb)
        self.min_odds, self.max_odds = QDoubleSpinBox(), QDoubleSpinBox()
        for box in (self.min_odds, self.max_odds):
            box.setRange(0, 100)
            box.setDecimals(2)
            box.setSpecialValueText("—")
        self.h2h_window, self.form_window = QSpinBox(), QSpinBox()
        for box, default in ((self.h2h_window, 20), (self.form_window, 10)):
            box.setRange(1, 500)
            box.setValue(default)

        form = QFormLayout()
        form.addRow("Azonosító", self.sid)
        form.addRow("Név", self.name)
        form.addRow("", self.enabled)
        form.addRow("Piac", self.market)
        form.addRow("Tipp", self.pick)
        form.addRow("Formátum", self.fmt)
        form.addRow("Napszak (üres = mind)", sess_row)
        form.addRow("Min. odds", self.min_odds)
        form.addRow("Max. odds", self.max_odds)
        form.addRow("H2H ablak (meccs)", self.h2h_window)
        form.addRow("Forma ablak (meccs)", self.form_window)

        self.conds = QTableWidget(0, 3)
        self.conds.setHorizontalHeaderLabels(["Jellemző", "Művelet", "Érték"])
        self.conds.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.conds.setMinimumHeight(150)
        add_c, del_c = QPushButton("+ Feltétel"), QPushButton("− Kijelölt törlése")
        add_c.clicked.connect(lambda: self._add_condition())
        del_c.clicked.connect(lambda: self.conds.removeRow(self.conds.currentRow()))
        cond_box = QGroupBox("Feltételek (mind teljesüljön)")
        cv = QVBoxLayout(cond_box)
        cv.addWidget(self.conds)
        row = QHBoxLayout()
        row.addWidget(add_c)
        row.addWidget(del_c)
        cv.addLayout(row)

        save_btn, delete_btn = QPushButton("Mentés"), QPushButton("Törlés")
        save_btn.clicked.connect(self._save)
        delete_btn.clicked.connect(self._delete)
        self.plugin_note = QLabel("")
        self.plugin_note.setWordWrap(True)

        self.bt_from, self.bt_to = QDateEdit(), QDateEdit()
        for box, d in ((self.bt_from, date.today() - timedelta(days=30)), (self.bt_to, date.today())):
            box.setCalendarPopup(True)
            box.setDisplayFormat("yyyy-MM-dd")
            box.setDate(d)
        self.bt_line, self.bt_odds = QDoubleSpinBox(), QDoubleSpinBox()
        self.bt_line.setRange(0.5, 20.5)
        self.bt_line.setSingleStep(1.0)
        self.bt_line.setValue(5.5)
        self.bt_odds.setRange(1.01, 20)
        self.bt_odds.setValue(1.90)
        bt_btn = QPushButton("Backteszt futtatása")
        bt_btn.clicked.connect(self._run_backtest)
        self.bt_out = QLabel("")
        self.bt_out.setWordWrap(True)
        self.bt_out.setTextInteractionFlags(Qt.TextSelectableByMouse)
        bt_box = QGroupBox("Backteszt (csak a kezdés előtti adatokból)")
        bf = QFormLayout(bt_box)
        bf.addRow("Ettől", self.bt_from)
        bf.addRow("Eddig", self.bt_to)
        bf.addRow("O/U vonal", self.bt_line)
        bf.addRow("Feltételezett odds", self.bt_odds)
        bf.addRow(bt_btn)
        bf.addRow(self.bt_out)

        right = QVBoxLayout()
        right.addLayout(form)
        right.addWidget(cond_box)
        btns = QHBoxLayout()
        btns.addWidget(save_btn)
        btns.addWidget(delete_btn)
        right.addLayout(btns)
        right.addWidget(self.plugin_note)
        right.addWidget(bt_box)

        root = QHBoxLayout(self)
        root.addLayout(left, 1)
        root.addLayout(right, 2)
        self._fill_picks()
        self.refresh()
        self._new()

    # -- list ----------------------------------------------------------------------------

    def refresh(self) -> None:
        current = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None
        self.list.clear()
        for s in self.p.loaded.strategies:
            kind = "labor" if isinstance(s, RuleStrategy) else "Python"
            item = QListWidgetItem(f"{s.name}  [{kind}]{'' if s.enabled else '  (kikapcsolva)'}")
            item.setData(Qt.UserRole, s.id)
            self.list.addItem(item)
            if s.id == current:
                self.list.setCurrentItem(item)

    def _strategy(self, sid):
        return next((s for s in self.p.loaded.strategies if s.id == sid), None)

    def _load_selected(self, item) -> None:
        if item is None:
            return
        s = self._strategy(item.data(Qt.UserRole))
        if isinstance(s, RuleStrategy):
            self._fill_form(s.spec)
            self.plugin_note.setText("")
        elif s is not None:
            self._new()
            self.plugin_note.setText(
                f"„{s.name}” Python-plugin ({s.id}). A kódja a strategies/ mappában "
                "van, itt csak backtesztelni lehet."
            )

    # -- form ----------------------------------------------------------------------------

    def _fill_picks(self) -> None:
        self.pick.clear()
        for p in PICKS[self.market.currentData()]:
            self.pick.addItem(p, p)

    def _add_condition(self, feature="h2h_n", op=">=", value=0.0) -> None:
        r = self.conds.rowCount()
        self.conds.insertRow(r)
        f = QComboBox()
        for name in FEATURE_NAMES:
            f.addItem(FEATURE_LABELS.get(name, name), name)
        f.setCurrentIndex(FEATURE_NAMES.index(feature))
        o = QComboBox()
        o.addItems(list(OPS))
        o.setCurrentText(op)
        v = QDoubleSpinBox()
        v.setRange(-1000, 1000)
        v.setDecimals(3)
        v.setValue(value)
        self.conds.setCellWidget(r, 0, f)
        self.conds.setCellWidget(r, 1, o)
        self.conds.setCellWidget(r, 2, v)

    def _new(self) -> None:
        self._fill_form(
            {
                "id": "",
                "name": "",
                "enabled": True,
                "market": "ou",
                "pick": "over",
                "conditions": [{"feature": "h2h_n", "op": ">=", "value": 10}],
            }
        )
        self.list.clearSelection()

    def _fill_form(self, spec: dict) -> None:
        self.sid.setText(spec.get("id", ""))
        self.name.setText(spec.get("name", ""))
        self.enabled.setChecked(bool(spec.get("enabled", True)))
        self.market.setCurrentIndex(self.market.findData(spec.get("market", "ou")))
        self._fill_picks()
        self.pick.setCurrentIndex(max(0, self.pick.findData(spec.get("pick"))))
        fmts = spec.get("formats") or [None]
        self.fmt.setCurrentIndex(max(0, self.fmt.findData(fmts[0] if len(fmts) == 1 else None)))
        for s, cb in self.sessions.items():
            cb.setChecked(s in (spec.get("sessions") or []))
        self.min_odds.setValue(spec.get("min_odds") or 0)
        self.max_odds.setValue(spec.get("max_odds") or 0)
        self.h2h_window.setValue(spec.get("h2h_window", 20))
        self.form_window.setValue(spec.get("form_window", 10))
        self.conds.setRowCount(0)
        for c in spec.get("conditions", []):
            self._add_condition(c["feature"], c["op"], float(c["value"]))

    def _spec(self) -> dict:
        conditions = []
        for r in range(self.conds.rowCount()):
            conditions.append(
                {
                    "feature": self.conds.cellWidget(r, 0).currentData(),
                    "op": self.conds.cellWidget(r, 1).currentText(),
                    "value": self.conds.cellWidget(r, 2).value(),
                }
            )
        sessions = [s for s, cb in self.sessions.items() if cb.isChecked()]
        return {
            "id": self.sid.text().strip(),
            "name": self.name.text().strip(),
            "enabled": self.enabled.isChecked(),
            "market": self.market.currentData(),
            "pick": self.pick.currentData(),
            "formats": [self.fmt.currentData()] if self.fmt.currentData() else None,
            "sessions": sessions or None,
            "min_odds": self.min_odds.value() or None,
            "max_odds": self.max_odds.value() or None,
            "h2h_window": self.h2h_window.value(),
            "form_window": self.form_window.value(),
            "conditions": conditions,
        }

    def _save(self) -> None:
        spec = self._spec()
        existing = self._strategy(spec["id"])
        if existing is not None and not isinstance(existing, RuleStrategy):
            QMessageBox.warning(self, "Mentés", "Ez az azonosító egy Python-pluginé. Válassz másikat.")
            return
        try:
            save_rule(self.p.settings.lab_dir, spec)
        except RuleError as e:
            QMessageBox.warning(self, "Hibás stratégia", str(e))
            return
        self.changed.emit()

    def _delete(self) -> None:
        sid = self.sid.text().strip()
        if not isinstance(self._strategy(sid), RuleStrategy):
            return
        if QMessageBox.question(self, "Törlés", f"Törlöd a(z) „{sid}” stratégiát?") == QMessageBox.Yes:
            delete_rule(self.p.settings.lab_dir, sid)
            self.changed.emit()
            self._new()

    # -- backtest ------------------------------------------------------------------------

    def _run_backtest(self) -> None:
        item = self.list.currentItem()
        try:
            strategy = self._strategy(item.data(Qt.UserRole)) if item else RuleStrategy(self._spec())
        except RuleError as e:
            QMessageBox.warning(self, "Hibás stratégia", str(e))
            return
        if strategy is None:
            return
        self.bt_out.setText("Fut…")
        args = dict(
            date_from=self.bt_from.date().toString("yyyy-MM-dd"),
            date_to=self.bt_to.date().toString("yyyy-MM-dd"),
            ou_lines=(self.bt_line.value(),),
            assumed_odds=self.bt_odds.value(),
        )

        def work():
            # own connection: a long backtest must not block the live engine (WAL allows it)
            conn = connect(self.p.settings.db_path)
            try:
                result = backtest.run(conn, strategy, **args)
            except Exception as e:
                result = e
            finally:
                conn.close()
            self._bt.done.emit(result)

        threading.Thread(target=work, daemon=True).start()

    def _show_backtest(self, r) -> None:
        if isinstance(r, Exception):
            self.bt_out.setText(f"Hiba: {r}")
            return
        hr = f"{r.hit_rate:.1%}" if r.hit_rate is not None else "—"
        be = f"{r.break_even_odds:.2f}" if r.break_even_odds else "—"
        months = "\n".join(
            f"  {m}: {v['signals']} jelzés, {v['won']}–{v['lost']}–{v['push']}"
            for m, v in sorted(r.by_month.items())
        )
        self.bt_out.setText(
            f"{r.matches_scanned} meccs, {r.signals} jelzés, {r.won}–{r.lost}–{r.push} (Ny–V–P)\n"
            f"Találati arány: {hr} · nullszaldós odds: {be} · egység @ {r.assumed_odds}: {r.units:+.2f}\n"
            f"{months}"
        )
