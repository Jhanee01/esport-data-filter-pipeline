
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QSizePolicy, QScrollArea, QMenu, QDateEdit,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QFont, QColor, QImage, QPixmap, QAction
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .compat.stats_manager import (
    StatsManager, get_daily_stats, get_summary, get_strategy_tabs, SHADOW_TAB_KEYS,
)


TAB_ACTIVE   = ("QPushButton{background:#FDB900;color:#000000;border:2px solid #FDB900;"
                "padding:0 14px;font-size:12px;font-weight:600;border-radius:6px;}"
                "QPushButton::menu-indicator{width:0;}")
TAB_INACTIVE = ("QPushButton{background:transparent;color:#FDB900;border:2px solid #FDB900;"
                "padding:0 14px;font-size:12px;border-radius:6px;}"
                "QPushButton:hover{background:rgba(253,185,0,0.15);color:#FDB900;}"
                "QPushButton::menu-indicator{width:0;}")

DATE_EDIT_STYLE = (
    "QDateEdit{background:#212121;color:#d9d9d9;border:1px solid #3a3a3a;"
    "border-radius:6px;padding:0 8px;font-size:12px;}"
    "QDateEdit:focus{border:1px solid #FDB900;}"
    "QDateEdit::drop-down{width:18px;border:none;}"
)


class _CheckableMenu(QMenu):
    """Olyan menü, amely a checkbox-os elemek pipálásakor NYITVA marad,
    így több stratégia is kiválasztható egyszerre kattintásonként."""

    def mouseReleaseEvent(self, event):
        action = self.activeAction()
        if action is not None and action.isEnabled() and action.isCheckable():
            action.trigger()  # pipa váltás + triggered jel, menü nyitva marad
            return
        super().mouseReleaseEvent(event)


# ──────────────────────────────────────────────
class SummaryCard(QFrame):
    def __init__(self, label: str, value: str, color: str = "#d9d9d9", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setMinimumWidth(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(6)
        lbl = QLabel(label.upper())
        lbl.setObjectName("cardTitle")
        lbl.setFont(QFont("Segoe UI Semibold", 11))
        self.val_lbl = QLabel(value)
        self.val_lbl.setObjectName("cardValue")
        self.val_lbl.setFont(QFont("Segoe UI Semibold", 32))
        self.val_lbl.setStyleSheet(f"color: {color};")
        layout.addWidget(lbl)
        layout.addWidget(self.val_lbl)

    def set_value(self, value: str, color: str | None = None):
        self.val_lbl.setText(value)
        if color:
            self.val_lbl.setStyleSheet(f"color: {color};")


# ──────────────────────────────────────────────
class StatsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentView")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        # ── Fejléc + időszak gombok ──
        hdr = QHBoxLayout()
        title = QLabel("Statisztika")
        title.setObjectName("viewTitle")
        title.setFont(QFont("Segoe UI Semibold", 16))
        hdr.addWidget(title)
        hdr.addStretch()

        # ── Egyéni dátumintervallum (mettől meddig) ──
        self._custom_range = False
        self._date_from = QDateEdit(QDate.currentDate().addDays(-7))
        self._date_to   = QDateEdit(QDate.currentDate())
        for de in (self._date_from, self._date_to):
            de.setCalendarPopup(True)
            de.setDisplayFormat("yyyy.MM.dd")
            de.setFixedHeight(30)
            de.setStyleSheet(DATE_EDIT_STYLE)
            # Statisztika nem lehet jövőbeli — elgépelt év (pl. 2028) a mai
            # napra csorbul, így a végdátum-szűrő mindig ténylegesen vág.
            de.setMinimumDate(QDate(2025, 1, 1))
            de.setMaximumDate(QDate.currentDate())
            de.dateChanged.connect(self._on_range_edited)
        self._range_btn = QPushButton("Egyéni")
        self._range_btn.setObjectName("toggleBtn")
        self._range_btn.setCheckable(True)
        self._range_btn.setFixedHeight(30)
        self._range_btn.clicked.connect(self._activate_custom_range)
        hdr.addWidget(self._date_from)
        _dash = QLabel("–")
        _dash.setStyleSheet("color:#8d8d9f;")
        hdr.addWidget(_dash)
        hdr.addWidget(self._date_to)
        hdr.addWidget(self._range_btn)
        hdr.addSpacing(12)

        self._period = 30
        self._period_btns: dict = {}
        for lbl, days in [("7 nap", 7), ("30 nap", 30), ("Összes", None)]:
            btn = QPushButton(lbl)
            btn.setObjectName("toggleBtn")
            btn.setCheckable(True)
            btn.setChecked(days == 30)
            btn.setFixedHeight(30)
            btn.clicked.connect(lambda _, d=days: self._set_period(d))
            hdr.addWidget(btn)
            self._period_btns[days] = btn

        # ── Stratégia-szűrő menü — MAGA az "Összes" tab a legördülő ──
        # A felhasználó kiválaszthatja, mely stratégiák szerepeljenek az összesítésben.
        self._all_filter_checked: set[str] = set()
        self._all_tab_btn: QPushButton | None = None
        self._strat_filter_menu = _CheckableMenu(self)
        # A menü megnyitása egyúttal az "Összes" összesített nézetre vált
        self._strat_filter_menu.aboutToShow.connect(
            lambda: self._set_strategy("all", None))
        layout.addLayout(hdr)

        # ── Stratégia tab sor ──
        tab_frame = QFrame()
        tab_frame.setStyleSheet(
            "QFrame{background:#212121;border-radius:8px;}")
        tab_layout = QHBoxLayout(tab_frame)
        tab_layout.setContentsMargins(8, 5, 8, 5)
        tab_layout.setSpacing(4)

        self._tab_btns: dict[str, QPushButton] = {}
        self._active_key: str = "all"
        self._active_sources: list | None = None
        self._tab_layout = tab_layout

        self._build_tab_buttons()

        # Vízszintes csúszka, hogy minden tab neve kiférjen
        tab_scroll = QScrollArea()
        tab_scroll.setWidget(tab_frame)
        tab_scroll.setWidgetResizable(True)
        tab_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tab_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tab_scroll.setFixedHeight(52)
        tab_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:horizontal{height:6px;background:#1a1a1a;border-radius:3px;margin:0;}"
            "QScrollBar::handle:horizontal{background:#FDB900;border-radius:3px;min-width:30px;}"
            "QScrollBar::handle:horizontal:hover{background:#ffd54f;}"
            "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}"
            "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:transparent;}"
        )
        layout.addWidget(tab_scroll)

        # ── Összesítő kártyák ──
        cards_row = QHBoxLayout()
        cards_row.setSpacing(12)
        self.card_units = SummaryCard("Egységek",    "–",  "#FDB900")
        self.card_roi   = SummaryCard("ROI",         "–",  "#8d8d9f")
        self.card_won   = SummaryCard("Nyert",        "–", "#3ba560")
        self.card_lost  = SummaryCard("Veszített",    "–", "#d44a3a")
        self.card_total = SummaryCard("Összes tipp",  "–", "#8d8d9f")
        for c in (self.card_units, self.card_roi,
                  self.card_won, self.card_lost, self.card_total):
            cards_row.addWidget(c)
        layout.addLayout(cards_row)

        # ── Grafikon — Agg backend: QLabel-be renderelünk, nincs natív Qt ablak ──
        self._fig = Figure(figsize=(12, 4), dpi=100, facecolor="#12121f", tight_layout=True)
        self._ax  = self._fig.add_subplot(111)
        # Másodlagos jobb oldali tengely a kumulatív összprofit vonalnak (külön skála)
        self._ax2 = self._ax.twinx()
        self._canvas = FigureCanvasAgg(self._fig)
        self.plot_widget = QLabel()
        self.plot_widget.setMinimumHeight(240)
        self.plot_widget.setScaledContents(True)
        self.plot_widget.setStyleSheet("background: #12121f; border-radius: 4px;")
        self.plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(self.plot_widget)

        # ── Napi táblázat ──
        cols = ["Dátum", "Tippek", "Nyert", "Veszített", "Egységek", "ROI%"]
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.table.setShowGrid(False)
        layout.addWidget(self.table)

        # ── StatsManager ──
        self._manager = StatsManager(self)
        self._manager.stats_updated.connect(self._refresh)

        # Alapértelmezett tab
        self._set_strategy("all", None)

    # ------------------------------------------------------------------

    def _build_tab_buttons(self):
        while self._tab_layout.count():
            item = self._tab_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._tab_btns.clear()
        self._all_tab_btn = None
        for key, label, sources in get_strategy_tabs():
            text = (label + "  ▾") if key == "all" else label
            btn = QPushButton(text)
            btn.setFixedHeight(30)
            # Fix méret → a gomb nem zsugorodik a szöveg alá, így a csúszka aktiválódik
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if key == "all":
                # Az "Összes" tab maga a legördülő stratégia-szűrő
                btn.setMenu(self._strat_filter_menu)
                self._all_tab_btn = btn
            else:
                btn.clicked.connect(
                    lambda _, k=key, s=sources: self._set_strategy(k, s))
            self._tab_btns[key] = btn
            self._tab_layout.addWidget(btn)
        self._tab_layout.addStretch()
        active = self._active_key if self._active_key in self._tab_btns else "all"
        for k, btn in self._tab_btns.items():
            btn.setStyleSheet(TAB_ACTIVE if k == active else TAB_INACTIVE)
        self._active_sources = next((s for k, _, s in get_strategy_tabs() if k == active), None)
        self._build_filter_menu()

    def _filterable_tabs(self) -> list:
        """A valódi stratégiák (az 'Összes' kivételével, ahol van source-lista)."""
        return [(k, l, s) for k, l, s in get_strategy_tabs() if k != "all" and s]

    def _build_filter_menu(self):
        """Az 'Összes' nézet stratégia-szűrőjének felépítése. Az újonnan
        megjelent stratégiák alapból be vannak pipálva."""
        tabs = self._filterable_tabs()
        valid = {k for k, _, _ in tabs}
        # Első felépítéskor mindent kiválasztunk; később megőrizzük a választást,
        # az új stratégiákat hozzávesszük, az eltűnteket eldobjuk.
        if not self._all_filter_checked:
            self._all_filter_checked = set(valid) - SHADOW_TAB_KEYS
        else:
            self._all_filter_checked |= (valid - self._prev_filterable() - SHADOW_TAB_KEYS)
            self._all_filter_checked &= valid

        self._strat_filter_menu.clear()
        for key, label, _ in tabs:
            act = QAction(label, self._strat_filter_menu)
            act.setCheckable(True)
            act.setChecked(key in self._all_filter_checked)
            act.triggered.connect(lambda checked, k=key: self._toggle_filter(k, checked))
            self._strat_filter_menu.addAction(act)
        self._strat_filter_menu.addSeparator()
        act_all = QAction("Mindet kijelöl", self._strat_filter_menu)
        act_all.triggered.connect(lambda: self._set_all_filter(True))
        self._strat_filter_menu.addAction(act_all)
        act_none = QAction("Kijelölés törlése", self._strat_filter_menu)
        act_none.triggered.connect(lambda: self._set_all_filter(False))
        self._strat_filter_menu.addAction(act_none)
        self._prev_valid = valid
        self._update_filter_btn_label()

    def _prev_filterable(self) -> set:
        return getattr(self, "_prev_valid", set())

    def _toggle_filter(self, key: str, checked: bool):
        if checked:
            self._all_filter_checked.add(key)
        else:
            self._all_filter_checked.discard(key)
        self._update_filter_btn_label()
        if self._active_key == "all":
            self._refresh()

    def _set_all_filter(self, select: bool):
        if select:
            self._all_filter_checked = {k for k, _, _ in self._filterable_tabs()}
        else:
            self._all_filter_checked = set()
        for act in self._strat_filter_menu.actions():
            if act.isCheckable():
                act.setChecked(select)
        self._update_filter_btn_label()
        if self._active_key == "all":
            self._refresh()

    def _update_filter_btn_label(self):
        if not self._all_tab_btn:
            return
        tabs = self._filterable_tabs()
        total = len(tabs)
        n = len(self._all_filter_checked)
        if n == total:
            self._all_tab_btn.setText("Összes  ▾")
        elif n == 0:
            self._all_tab_btn.setText("Összes: 0  ▾")
        else:
            self._all_tab_btn.setText(f"Összes: {n}/{total}  ▾")

    def _all_filter_sources(self) -> list | None:
        """Az 'Összes' összesítéshez használt source-lista a pipák alapján.
        Mind kijelölve → None (minden, gyors út). Egy sem → üres találat."""
        tabs = self._filterable_tabs()
        if len(self._all_filter_checked) == len(tabs):
            return None
        if not self._all_filter_checked:
            return ["__none__"]  # nem létező source → üres összesítés
        combined: list = []
        for key, _, sources in tabs:
            if key in self._all_filter_checked:
                combined.extend(sources)
        return combined

    def refresh_tabs(self):
        self._build_tab_buttons()

    def _set_period(self, days: int | None):
        self._period = days
        self._custom_range = False
        self._range_btn.setChecked(False)
        for d, btn in self._period_btns.items():
            btn.setChecked(d == days)
        self._refresh()

    def _activate_custom_range(self):
        """'Egyéni' gomb: a dátumintervallum szerinti nézetre vált."""
        self._custom_range = True
        self._range_btn.setChecked(True)
        for btn in self._period_btns.values():
            btn.setChecked(False)
        self._refresh()

    def _on_range_edited(self):
        """Dátum átállítása: ha az egyéni mód aktív, azonnal frissít; ha nem,
        automatikusan átvált rá (a felhasználó nyilván ezt akarja látni)."""
        self._activate_custom_range()

    def _range_dates(self) -> tuple[str, str]:
        """A beállított intervallum (YYYY-MM-DD, YYYY-MM-DD) — fordított
        sorrend esetén megcseréljük, hogy sose legyen üres az elgépeléstől."""
        d1 = self._date_from.date().toString("yyyy-MM-dd")
        d2 = self._date_to.date().toString("yyyy-MM-dd")
        return (d1, d2) if d1 <= d2 else (d2, d1)

    def _set_strategy(self, key: str, sources: list | None):
        self._active_key = key
        self._active_sources = sources
        for k, btn in self._tab_btns.items():
            btn.setStyleSheet(TAB_ACTIVE if k == key else TAB_INACTIVE)
        self._refresh()

    def _refresh(self):
        if self._active_key == "all":
            sources = self._all_filter_sources()
        else:
            sources = self._active_sources
        if self._custom_range:
            date_from, date_to = self._range_dates()
            daily   = get_daily_stats(None, sources, date_from, date_to)
            summary = get_summary(None, sources, date_from, date_to)
        else:
            daily   = get_daily_stats(self._period, sources)
            summary = get_summary(self._period, sources)

        units = summary["units"]
        roi   = summary["roi"]
        u_col = "#3ba560" if units >= 0 else "#d44a3a"
        r_col = "#3ba560" if roi   >= 0 else "#d44a3a"

        self.card_units.set_value(f"{units:+.2f}", u_col)
        self.card_roi.set_value(f"{roi:+.2f}%",    r_col)
        self.card_won.set_value(str(summary["tips_won"]))
        self.card_lost.set_value(str(summary["tips_lost"]))
        self.card_total.set_value(str(summary["tips_total"]))

        self._draw_chart(daily)
        self._fill_table(daily)

    def _draw_chart(self, daily: list[dict]):
        self._ax.clear()
        self._ax2.clear()
        self._ax.set_facecolor("#12121f")
        self._fig.set_facecolor("#12121f")

        if not daily:
            self._ax2.set_yticks([])
            self._canvas.draw()
            return

        y      = [d.get("units", 0.0) for d in daily]
        labels = [d["date"][5:] for d in daily]
        x      = list(range(len(y)))
        colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in y]
        cumul  = list(np.cumsum(y))

        # Glow effect: külső halvány sáv + belső tömör sáv
        for i, (v, c) in enumerate(zip(y, colors)):
            self._ax.bar(i, v, color=c, width=0.62, alpha=0.9, zorder=3)
            self._ax.bar(i, v, color=c, width=0.78, alpha=0.12, zorder=2)

        # Szaggatott #FDB900 kumulatív trend vonal — KÜLÖN jobb oldali tengelyen,
        # hogy a napi oszlopok skáláját ne nyomja össze a növekvő összprofit
        self._ax2.plot(x, cumul, color="#FDB900", linewidth=2,
                       linestyle="--", alpha=0.85, zorder=4, marker="o",
                       markersize=3.5, markerfacecolor="#FDB900")

        # Nulla vonal (napi oszlopok tengelyén)
        self._ax.axhline(0, color="#333344", linewidth=0.8, zorder=1)

        # Bal tengely (napi egységek) stílusa
        self._ax.set_xticks(x)
        self._ax.set_xticklabels(labels, color="#666688", fontsize=8,
                                  rotation=45, ha="right")
        self._ax.tick_params(axis="y", colors="#666688", labelsize=8)
        self._ax.yaxis.label.set_color("#666688")
        self._ax.grid(axis="y", color="#ffffff08", linewidth=0.5, zorder=0)
        for spine in self._ax.spines.values():
            spine.set_visible(False)
        self._ax.set_xlim(-0.6, len(y) - 0.4)

        # Jobb tengely (kumulatív összprofit) stílusa — sárga számok
        self._ax2.tick_params(axis="y", colors="#FDB900", labelsize=8)
        self._ax2.yaxis.label.set_color("#FDB900")
        for spine in self._ax2.spines.values():
            spine.set_visible(False)
        self._ax2.set_xlim(-0.6, len(y) - 0.4)

        self._canvas.draw()
        buf = self._canvas.buffer_rgba()
        w, h = self._canvas.get_width_height()
        img = QImage(bytes(buf), w, h, QImage.Format.Format_RGBA8888)
        self.plot_widget.setPixmap(QPixmap.fromImage(img))

    def _fill_table(self, daily: list[dict]):
        self.table.setRowCount(0)
        for d in reversed(daily):
            row = self.table.rowCount()
            self.table.insertRow(row)
            units = d.get("units", 0.0)
            roi   = d.get("roi",   0.0)
            u_col = QColor("#3ba560" if units >= 0 else "#d44a3a")
            r_col = QColor("#3ba560" if roi   >= 0 else "#d44a3a")

            values = [
                d.get("date", ""),
                str(d.get("tips_total", 0)),
                str(d.get("tips_won",   0)),
                str(d.get("tips_lost",  0)),
                f"{units:+.2f}",
                f"{roi:+.2f}%",
            ]
            colors = [None, None, None, None, u_col, r_col]

            for col, (val, col_color) in enumerate(zip(values, colors)):
                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col_color:
                    item.setForeground(col_color)
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 36)
