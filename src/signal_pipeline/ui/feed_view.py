
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QStackedWidget,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor

from .compat.feed_watcher import FeedWatcher
from .compat import runtime

COLUMNS = ["Liga", "Időpont", "Hazai", "Vendég", "O/U sor", "Over", "Under"]
MAX_ROWS = 200

# Konzol-nézettel azonos fül-stílus
TAB_ACTIVE   = ("QPushButton{background:#FDB900;color:#000000;border:2px solid #FDB900;"
                "padding:0 14px;font-size:12px;font-weight:600;border-radius:6px;}")
TAB_INACTIVE = ("QPushButton{background:transparent;color:#FDB900;border:2px solid #FDB900;"
                "padding:0 14px;font-size:12px;border-radius:6px;}"
                "QPushButton:hover{background:rgba(253,185,0,0.15);color:#FDB900;}")


def _parse_entry(obj: dict) -> dict | None:
    ms = obj.get("market_struct") or {}
    if ms.get("type") != "O/U":
        return None
    home = str(obj.get("home") or "").strip()
    away = str(obj.get("away") or "").strip()
    if not home or not away:
        match_str = str(obj.get("match") or "")
        parts = match_str.split(" vs ", 1)
        home = parts[0].strip() if len(parts) >= 1 else "?"
        away = parts[1].strip() if len(parts) >= 2 else "?"
    return {
        "liga":  "",
        "time":  str(obj.get("time") or obj.get("start_time") or "–"),
        "home":  home,
        "away":  away,
        "line":  str(ms.get("line") or "–"),
        "over":  str(ms.get("over") or "–"),
        "under": str(ms.get("under") or "–"),
    }


class _FeedPanel(QWidget):
    """Egy iroda feedje (8min + 12min) egy táblázatban, a legújabb sor felül."""

    def __init__(self, path_8, path_12, missing_text: str,
                 backfill_lines: int = 0, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        # Figyelmeztetés sáv (fájl hiányzik)
        self.warning_bar = QFrame()
        self.warning_bar.setObjectName("card")
        self.warning_bar.setStyleSheet(
            "QFrame#card { background-color: #3a341c; border: 1px solid #f2cc0c; border-radius: 6px; padding: 8px 16px; }"
        )
        warn_lbl = QLabel(missing_text)
        warn_lbl.setStyleSheet("color: #f2cc0c; font-size: 13px;")
        warn_layout = QVBoxLayout(self.warning_bar)
        warn_layout.setContentsMargins(12, 8, 12, 8)
        warn_layout.addWidget(warn_lbl)
        self.warning_bar.setVisible(False)
        layout.addWidget(self.warning_bar)

        # Táblázat
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 80)   # Liga
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setShowGrid(False)
        layout.addWidget(self.table)

        self.total_count = 0
        self.count_changed = None   # a FeedView köti be (fejléc-számláló frissítése)

        # FeedWatcher — 8min és 12min
        self._watcher = FeedWatcher(self, path=path_8, backfill_lines=backfill_lines)
        self._watcher.new_entries.connect(
            lambda entries: self._on_new_entries(entries, "8min"))
        self._watcher.file_missing.connect(self.warning_bar.setVisible)

        self._watcher_12 = FeedWatcher(self, path=path_12, backfill_lines=backfill_lines)
        self._watcher_12.new_entries.connect(
            lambda entries: self._on_new_entries(entries, "12min"))

    def _on_new_entries(self, entries: list, liga: str = "8min"):
        for obj in entries:
            parsed = _parse_entry(obj)
            if parsed is None:
                continue
            parsed["liga"] = liga
            self._insert_row(parsed)
        if self.count_changed:
            self.count_changed()

    def _insert_row(self, data: dict):
        self.table.insertRow(0)
        values = [
            data["liga"], data["time"], data["home"], data["away"],
            data["line"], data["over"], data["under"],
        ]
        for col, val in enumerate(values):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            if col == 0:  # Liga badge — középre
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                color = "#4ab8c4" if val == "12min" else "#6ec532"
                item.setForeground(QColor(color))
                item.setFont(QFont("Segoe UI Semibold", 10))
            if col in (5, 6):  # over/under odds — középre
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if col == 4:  # O/U sor — kiemelve
                item.setForeground(QColor("#FDB900"))
                item.setFont(QFont("Segoe UI Semibold", 12))
            self.table.setItem(0, col, item)

        # Fade-in: az új sor háttere villan egyet
        self._flash_row(0)

        # Limit
        while self.table.rowCount() > MAX_ROWS:
            self.table.removeRow(self.table.rowCount() - 1)

        self.total_count += 1

    def _flash_row(self, row: int):
        FLASH_COLOR = QColor("#2d3a52")
        # A villanás a konkrét cellákhoz kötődik, nem a sorindexhez: gyors egymás
        # utáni beszúrásnál a sor lejjebb csúszik, a 0. index már egy másik sor.
        items = [self.table.item(row, col) for col in range(self.table.columnCount())]
        items = [it for it in items if it]
        for it in items:
            it.setBackground(FLASH_COLOR)

        def restore():
            for it in items:
                try:
                    # alapértelmezett háttér → a táblázat váltakozó sorszíne érvényes
                    it.setData(Qt.ItemDataRole.BackgroundRole, None)
                except RuntimeError:
                    pass   # a sort közben kivágta a MAX_ROWS-limit

        QTimer.singleShot(400, restore)


class FeedView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentView")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # Fejléc sor
        header_row = QHBoxLayout()
        title = QLabel("Élő Feed")
        title.setObjectName("viewTitle")
        title.setFont(QFont("Segoe UI Semibold", 16))

        self.count_lbl = QLabel("0 esemény")
        self.count_lbl.setObjectName("cardTitle")
        self.count_lbl.setFont(QFont("Segoe UI", 12))
        self.count_lbl.setStyleSheet("color: #8d8d9f;")

        header_row.addWidget(title)
        header_row.addStretch()
        header_row.addWidget(self.count_lbl)
        layout.addLayout(header_row)

        # Egy fül az odds-forráshoz (az eredetin irodánként egy fül volt)
        source = runtime.pipeline().source.name
        self._panels = [
            (source.upper(), _FeedPanel(
                "8min", "12min",
                f"⚠  Várakozás az odds-forrásra ({source})...")),
        ]

        tab_row = QHBoxLayout()
        tab_row.setSpacing(6)
        self._tab_btns: list[QPushButton] = []
        self._stack = QStackedWidget()
        for i, (label, panel) in enumerate(self._panels):
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self._select_tab(idx))
            self._tab_btns.append(btn)
            tab_row.addWidget(btn)
            panel.count_changed = self._update_count
            self._stack.addWidget(panel)
        tab_row.addStretch()
        layout.addLayout(tab_row)
        layout.addWidget(self._stack)

        self._select_tab(0)

    def _select_tab(self, index: int):
        for i, btn in enumerate(self._tab_btns):
            btn.setStyleSheet(TAB_ACTIVE if i == index else TAB_INACTIVE)
        self._stack.setCurrentIndex(index)
        self._update_count()

    def _update_count(self):
        panel = self._panels[self._stack.currentIndex()][1]
        self.count_lbl.setText(f"{panel.total_count} esemény")
