from datetime import datetime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QFrame, QScrollArea, QSizePolicy,
)
from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont, QTextCursor, QColor, QTextCharFormat

# Statisztika-nézettel azonos tab-stílus (2px arany szegély, 6px rádiusz)
TAB_ACTIVE   = ("QPushButton{background:#FDB900;color:#000000;border:2px solid #FDB900;"
                "padding:0 14px;font-size:12px;font-weight:600;border-radius:6px;}")
TAB_INACTIVE = ("QPushButton{background:transparent;color:#FDB900;border:2px solid #FDB900;"
                "padding:0 14px;font-size:12px;border-radius:6px;}"
                "QPushButton:hover{background:rgba(253,185,0,0.15);color:#FDB900;}")

# The pipeline's parts, each with its own console tab (the original had one per bot/scraper).
# Log records are routed here by logger name, see ui.app.
PROCESS_TABS = [
    ("engine",    "Jelzés-motor"),
    ("collector", "Battle gyűjtő"),
    ("odds",      "Odds-forrás"),
    ("resolver",  "Eredmény-feloldó"),
    ("telegram",  "Telegram"),
    ("remote",    "Távvezérlés"),
]

LINE_COLORS = {
    "engine":    "#3ba560",
    "collector": "#5794f2",
    "odds":      "#f2cc0c",
    "resolver":  "#4ab8c4",
    "telegram":  "#FDB900",
    "remote":    "#c678dd",
}


class LogView(QWidget):
    def __init__(self, parent=None, tabs=None, raw=False):
        """tabs: a megjelenítendő (process, címke) párok — alapból a pipeline részei.
        raw=True: a sorok a folyamat nyers kimeneteként jelennek meg (a dashboard
        nem tesz eléjük időbélyeget; a táblázatos kimenet oszlopai így egyben maradnak)."""
        super().__init__(parent)
        self.setObjectName("contentView")
        self._tabs = tabs or PROCESS_TABS
        self._raw = raw

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 12)
        root.setSpacing(10)

        # Process tab sor — Statisztika-stílusú chipek (2px arany szegély), alatta
        # vízszintes arany görgető. A "Konzol" cím és a Törlés gomb szándékosan nincs.
        tab_frame = QFrame()
        tab_frame.setStyleSheet("QFrame{background:#212121;border-radius:8px;}")
        tab_layout = QHBoxLayout(tab_frame)
        tab_layout.setContentsMargins(8, 5, 8, 5)
        tab_layout.setSpacing(4)

        self._tab_btns: list[QPushButton] = []
        self._active_idx = 0
        for i, (key, label) in enumerate(self._tabs):
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            # Fix méret → a gomb nem zsugorodik a szöveg alá, így a csúszka aktiválódik
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, idx=i: self._select_tab(idx))
            self._tab_btns.append(btn)
            tab_layout.addWidget(btn)
        tab_layout.addStretch()

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
        root.addWidget(tab_scroll)

        # Terminal panelek — egy per process
        self._panels: dict[str, QPlainTextEdit] = {}
        self._container = QFrame()
        self._container.setObjectName("card")
        cont_layout = QVBoxLayout(self._container)
        cont_layout.setContentsMargins(0, 0, 0, 0)

        for key, _ in self._tabs:
            pane = QPlainTextEdit()
            pane.setReadOnly(True)
            pane.setFont(QFont("Consolas", 10))
            pane.setObjectName("logPane")
            pane.setStyleSheet(
                "QPlainTextEdit#logPane {"
                "  background-color: #12141a;"
                "  color: #c8c8d4;"
                "  border: none;"
                "  padding: 8px;"
                "}"
            )
            pane.setMaximumBlockCount(2000)
            pane.setVisible(False)
            cont_layout.addWidget(pane)
            self._panels[key] = pane

        root.addWidget(self._container, 1)

        # Állapotsor
        status_row = QHBoxLayout()
        self._status_lbl = QLabel("")
        self._status_lbl.setFont(QFont("Segoe UI", 10))
        self._status_lbl.setStyleSheet("color: #6e7079;")
        status_row.addWidget(self._status_lbl)
        status_row.addStretch()
        root.addLayout(status_row)

        self._line_counts: dict[str, int] = {k: 0 for k, _ in self._tabs}
        self._select_tab(0)

    def _select_tab(self, index: int):
        """Tab-váltás: aktív gomb kiemelése + a hozzá tartozó panel megjelenítése."""
        self._active_idx = index
        for i, btn in enumerate(self._tab_btns):
            btn.setStyleSheet(TAB_ACTIVE if i == index else TAB_INACTIVE)
        for i, (key, _) in enumerate(self._tabs):
            self._panels[key].setVisible(i == index)
        self._update_status()

    def show_process_tab(self, process_name: str):
        """Programmatikusan vált a megadott folyamat tabjára."""
        for i, (key, _) in enumerate(self._tabs):
            if key == process_name:
                self._select_tab(i)
                return

    def _update_status(self):
        key = self._tabs[self._active_idx][0]
        n = self._line_counts[key]
        self._status_lbl.setText(f"{n} sor")

    @Slot(str, str)
    def append_line(self, process_name: str, line: str):
        pane = self._panels.get(process_name)
        if pane is None:
            return

        ts = datetime.now().strftime("%H:%M:%S")
        color = LINE_COLORS.get(process_name, "#c8c8d4")

        cursor = pane.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Timestamp szürke (nyers módban nincs)
        if not self._raw:
            fmt_ts = QTextCharFormat()
            fmt_ts.setForeground(QColor("#4a4d5a"))
            cursor.setCharFormat(fmt_ts)
            cursor.insertText(f"[{ts}] ")

        # Sor színe process szerint
        fmt_line = QTextCharFormat()
        fmt_line.setForeground(QColor(color))
        cursor.setCharFormat(fmt_line)
        cursor.insertText(line + "\n")

        pane.setTextCursor(cursor)
        pane.ensureCursorVisible()

        self._line_counts[process_name] += 1
        if self._tabs[self._active_idx][0] == process_name:
            self._update_status()
