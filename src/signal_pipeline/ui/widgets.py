"""Shared dashboard widgets, in the look of the original tool: qt-material dark theme with the
#FDB900 accent, a left sidebar with large uppercase nav items, and gradient "card" frames."""

from __future__ import annotations

import math
from collections import deque
from datetime import datetime
from importlib import resources

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QImage, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

ACCENT = "#FDB900"

TAB_ACTIVE = (
    "QPushButton{background:#FDB900;color:#000000;border:2px solid #FDB900;"
    "padding:0 14px;font-size:12px;font-weight:600;border-radius:6px;}"
)
TAB_INACTIVE = (
    "QPushButton{background:transparent;color:#FDB900;border:2px solid #FDB900;"
    "padding:0 14px;font-size:12px;border-radius:6px;}"
    "QPushButton:hover{background:rgba(253,185,0,0.15);color:#FDB900;}"
)
OUTLINE_BTN = (
    "QPushButton{background:transparent;color:#FDB900;border:2px solid #FDB900;"
    "padding:0 12px;border-radius:6px;}"
    "QPushButton:hover{background:rgba(253,185,0,0.15);color:#FDB900;}"
    "QPushButton:disabled{color:#7a6a2a;border-color:#5a4a1a;}"
)
LOG_PANE = "QPlainTextEdit {background-color: #12141a; color: #c8c8d4; border: none; padding: 8px;}"
SCROLL_QSS = (
    "QScrollArea { background: transparent; border: none; }"
    "QScrollBar:vertical { width: 8px; background: #1a1a1a; border-radius: 4px; }"
    "QScrollBar::handle:vertical { background: #FDB900; border-radius: 4px; min-height: 20px; }"
    "QScrollBar::handle:vertical:hover { background: #ffd54f; }"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }"
)

# status → (label, background, foreground), as on the original tip cards
BADGE_STYLE = {
    "won": ("NYERTES", "#1c3829", "#3ba560"),
    "lost": ("VESZTES", "#3a1c1c", "#d44a3a"),
    "push": ("PUSH", "#1c2a3a", "#5794f2"),
    "void": ("ÉRVÉNYTELEN", "#2a2d3a", "#6e7079"),
    "pending": ("FOLYAMATBAN", "#3a341c", "#f2cc0c"),
}


def card_title(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    lbl.setObjectName("cardTitle")
    lbl.setFont(QFont("Segoe UI Semibold", 11))
    return lbl


def view_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("viewTitle")
    lbl.setFont(QFont("Segoe UI Semibold", 16))
    return lbl


class ContentView(QWidget):
    """A page in the stack: title row + body, 24 px margins like the original views."""

    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("contentView")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 24, 24, 24)
        self.root.setSpacing(14)
        self.title_row = QHBoxLayout()
        self.title_row.addWidget(view_title(title))
        self.title_row.addStretch()
        self.root.addLayout(self.title_row)

    def refresh(self) -> None:
        """Called every few seconds while the view is visible."""


# ── logo and painted icons ─────────────────────────────────────────────────────────────


def _logo_label(size: int = 44) -> QLabel:
    """The logo with its white background flood-filled to transparent (same as the original)."""
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setStyleSheet("background: transparent;")
    data = resources.files("signal_pipeline.ui").joinpath("assets/logo.png").read_bytes()
    src = QPixmap()
    src.loadFromData(data)
    if src.isNull():
        return lbl
    src = src.scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    img = src.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()

    def is_bg(x, y):
        c = img.pixelColor(x, y)
        return c.red() > 230 and c.green() > 230 and c.blue() > 230

    visited, queue = set(), deque()
    for sx, sy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if is_bg(sx, sy):
            queue.append((sx, sy))
            visited.add((sx, sy))
    while queue:
        x, y = queue.popleft()
        img.setPixelColor(x, y, QColor(0, 0, 0, 0))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited and is_bg(nx, ny):
                visited.add((nx, ny))
                queue.append((nx, ny))
    lbl.setPixmap(QPixmap.fromImage(img))
    return lbl


def gear_pixmap(size: int = 19, color: str = ACCENT) -> QPixmap:
    """Gear icon painted with QPainter, so it shows regardless of installed icon fonts."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), max(1.4, size * 0.11))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(QBrush(Qt.BrushStyle.NoBrush))
    cx, cy = size / 2.0, size / 2.0
    r_body, tooth = size * 0.30, size * 0.14
    for i in range(8):
        a = math.radians(i * 45.0)
        p.drawLine(
            QPointF(cx + r_body * math.cos(a), cy + r_body * math.sin(a)),
            QPointF(cx + (r_body + tooth) * math.cos(a), cy + (r_body + tooth) * math.sin(a)),
        )
    p.drawEllipse(QRectF(cx - r_body, cy - r_body, 2 * r_body, 2 * r_body))
    r_hole = r_body * 0.42
    p.drawEllipse(QRectF(cx - r_hole, cy - r_hole, 2 * r_hole, 2 * r_hole))
    p.end()
    return pix


# ── sidebar ────────────────────────────────────────────────────────────────────────────

_ACTIVE_ITEM = "background: transparent; border-radius: 8px; border: 2px solid #FDB900;"
_INACTIVE_ITEM = "background: transparent; border-radius: 8px; border: 2px solid transparent;"
_HOVER_ITEM = "background: rgba(253,185,0,0.08); border-radius: 8px; border: 2px solid rgba(253,185,0,0.4);"
_GRAY_SEP = "background: #4f5b62; border: none; min-height: 2px; max-height: 2px;"


def gray_sep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(_GRAY_SEP)
    return sep


class NavItem(QWidget):
    clicked = Signal(int)

    def __init__(self, label: str, index: int):
        super().__init__()
        self.index = index
        self._active = False
        self.setFixedHeight(68)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(24, 0, 16, 0)
        self.text_lbl = QLabel(label.upper())
        self.text_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        row.addWidget(self.text_lbl, 1)
        self._apply(False)

    def _apply(self, active: bool, hover: bool = False) -> None:
        self.setStyleSheet(_ACTIVE_ITEM if active else _HOVER_ITEM if hover else _INACTIVE_ITEM)
        font = QFont("Karla Variable", 30)
        font.setWeight(QFont.Weight.Bold if active else QFont.Weight.Medium)
        self.text_lbl.setFont(font)
        color = ACCENT if active or hover else "#ffffff"
        self.text_lbl.setStyleSheet(f"color: {color} !important;")
        pal = self.text_lbl.palette()  # palette too: qt-material doesn't override it
        pal.setColor(QPalette.ColorRole.WindowText, QColor(color))
        self.text_lbl.setPalette(pal)

    def set_active(self, active: bool) -> None:
        self._active = active
        self._apply(active)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        if not self._active:
            self._apply(False, hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply(self._active)
        super().leaveEvent(event)


class Sidebar(QWidget):
    nav_changed = Signal(int)
    settings_requested = Signal()

    def __init__(self, labels: list[str], title: str = "SIGNAL PIPELINE"):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(2)

        logo = QFrame()
        logo.setObjectName("sidebarLogo")
        logo.setFixedHeight(72)
        logo_row = QHBoxLayout(logo)
        logo_row.setContentsMargins(20, 0, 16, 0)
        logo_row.setSpacing(10)
        name = QLabel(title)
        name_font = QFont("Karla Variable", 14)
        name_font.setWeight(QFont.Weight.Bold)
        name.setFont(name_font)
        name.setStyleSheet("color: #ffffff; letter-spacing: 1px;")
        logo_row.addWidget(_logo_label(44))
        logo_row.addWidget(name)
        logo_row.addStretch()
        layout.addWidget(logo)
        layout.addWidget(gray_sep())
        layout.addSpacing(8)

        self.items: list[NavItem] = []
        for i, label in enumerate(labels):
            item = NavItem(label, i)
            item.clicked.connect(self._on_nav)
            layout.addWidget(item)
            self.items.append(item)

        layout.addSpacerItem(QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding))
        layout.addWidget(gray_sep())

        footer = QWidget()
        footer.setObjectName("sidebarFooter")
        footer.setFixedHeight(56)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(20, 6, 12, 6)
        mode_clock = QVBoxLayout()
        mode_clock.setSpacing(2)
        self.mode_label = QLabel("● DAY")
        self.clock_label = QLabel()
        self.clock_label.setStyleSheet("color: #3d4559; font-size: 11px;")
        mode_clock.addWidget(self.mode_label)
        mode_clock.addWidget(self.clock_label)
        fl.addLayout(mode_clock)
        fl.addStretch()
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setFixedSize(34, 34)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setToolTip("Beállítások (Telegram-csatornák)")
        self.settings_btn.setIcon(QIcon(gear_pixmap()))
        self.settings_btn.setIconSize(QSize(19, 19))
        self.settings_btn.setStyleSheet(
            "QPushButton#settingsBtn{background:transparent;border:1px solid rgba(253,185,0,0.5);border-radius:6px;}"
            "QPushButton#settingsBtn:hover{border:1px solid #FDB900;background:rgba(253,185,0,0.12);}"
        )
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        fl.addWidget(self.settings_btn)
        layout.addWidget(footer)

        self.set_session("day")
        self._tick()
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(1000)

    def _on_nav(self, index: int) -> None:
        self.set_active(index)
        self.nav_changed.emit(index)

    def set_active(self, index: int) -> None:
        for item in self.items:
            item.set_active(item.index == index)

    def set_session(self, session: str | None) -> None:
        text, color = {
            "day": ("● DAY", ACCENT),
            "afternoon": ("● AFTERNOON", ACCENT),
            "night": ("● NIGHT", "#4ab8c4"),
        }.get(session or "day", ("● —", "#6e7079"))
        self.mode_label.setText(text)
        self.mode_label.setStyleSheet(f"color: {color}; font-size: 11px; font-family: 'Segoe UI Semibold';")

    def _tick(self) -> None:
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))


# ── cards ──────────────────────────────────────────────────────────────────────────────


class StatusCard(QFrame):
    """A component of the pipeline with its state, as on the original "RENDSZER STÁTUSZ" column."""

    toggle_clicked = Signal(str)
    COLORS = {"ok": ACCENT, "warn": "#c8a020", "fail": "#d44a3a", "running": ACCENT, "stopped": "#d44a3a"}
    LABELS = {
        "ok": "● OK",
        "warn": "● FIGYELEM",
        "fail": "● HIBA",
        "running": "● FUT",
        "stopped": "● LEÁLLÍTVA",
    }

    def __init__(self, name: str, label: str, toggleable: bool = False):
        super().__init__()
        self.name = name
        self.setObjectName("card")
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)
        hdr = QHBoxLayout()
        title = QLabel(label)
        title.setFont(QFont("Segoe UI Semibold", 12))
        self.badge = QLabel()
        self.badge.setFont(QFont("Segoe UI Semibold", 11))
        self.badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(self.badge)
        lay.addLayout(hdr)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        self.msg.setFont(QFont("Segoe UI", 11))
        self.msg.setStyleSheet("color: #8d8d9f;")
        lay.addWidget(self.msg)
        self.toggle_btn = None
        if toggleable:
            self.toggle_btn = QPushButton()
            self.toggle_btn.setFixedHeight(30)
            self.toggle_btn.setFont(QFont("Segoe UI Semibold", 11))
            self.toggle_btn.clicked.connect(lambda: self.toggle_clicked.emit(self.name))
            lay.addWidget(self.toggle_btn)
        self.update_status("stopped", "")

    def update_status(self, status: str, message: str) -> None:
        self.badge.setText(self.LABELS.get(status, "○"))
        self.badge.setStyleSheet(f"color: {self.COLORS.get(status, '#6e7079')};")
        self.msg.setText(message)
        if self.toggle_btn is not None:
            if status == "running":
                self.toggle_btn.setText("■  Leállítás")
                self.toggle_btn.setStyleSheet(
                    "background-color: #3a1c1c; color: #d44a3a; "
                    "border: 1px solid #d44a3a; border-radius: 6px;"
                )
            else:
                self.toggle_btn.setText("▶  Indítás")
                self.toggle_btn.setStyleSheet(
                    "background-color: #0a1e0a; color: #FDB900; "
                    "border: 1px solid #FDB900; border-radius: 6px;"
                )


class MiniCard(QFrame):
    def __init__(self, label: str, value: str = "–", color: str = "#d9d9d9"):
        super().__init__()
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(4)
        t = QLabel(label.upper())
        t.setObjectName("cardTitle")
        t.setFont(QFont("Segoe UI Semibold", 10))
        self.val = QLabel(value)
        self.val.setFont(QFont("Segoe UI Semibold", 30))
        self.val.setStyleSheet(f"color: {color};")
        lay.addWidget(t)
        lay.addWidget(self.val)

    def set_value(self, value: str, color: str | None = None) -> None:
        self.val.setText(value)
        if color:
            self.val.setStyleSheet(f"color: {color};")


class SignalCard(QFrame):
    """One signal, laid out like the original tip card: match + status badge, then details."""

    def __init__(self, match: str, status: str, details: list[tuple[str, str]], strategy: str, reason: str):
        super().__init__()
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)
        row1 = QHBoxLayout()
        m = QLabel(match)
        m.setFont(QFont("Segoe UI Semibold", 13))
        m.setStyleSheet("color: #d9d9d9;")
        text, bg, fg = BADGE_STYLE.get(status, BADGE_STYLE["pending"])
        badge = QLabel(text)
        badge.setFont(QFont("Segoe UI Semibold", 11))
        badge.setFixedHeight(24)
        badge.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border: 1px solid {fg}; "
            "border-radius: 4px; padding: 2px 10px;"
        )
        row1.addWidget(m)
        row1.addStretch()
        row1.addWidget(badge)
        lay.addLayout(row1)
        row2 = QHBoxLayout()
        row2.setSpacing(20)
        for key, value in details:
            k = QLabel(key)
            k.setFont(QFont("Segoe UI", 11))
            k.setStyleSheet("color: #8d8d9f;")
            v = QLabel(value)
            v.setFont(QFont("Segoe UI Semibold", 11))
            v.setStyleSheet("color: #d9d9d9;")
            pair = QHBoxLayout()
            pair.setSpacing(6)
            pair.addWidget(k)
            pair.addWidget(v)
            row2.addLayout(pair)
        row2.addStretch()
        strat = QLabel(strategy)
        strat.setFont(QFont("Segoe UI", 10))
        strat.setStyleSheet(
            "color: #FDB900; border: 1px solid rgba(253,185,0,0.5); border-radius: 4px; padding: 1px 8px;"
        )
        row2.addWidget(strat)
        lay.addLayout(row2)
        if reason:
            r = QLabel(reason)
            r.setWordWrap(True)
            r.setFont(QFont("Segoe UI", 10))
            r.setStyleSheet("color: #6e7079;")
            lay.addWidget(r)


SESSION_COLUMNS = (("day", "DAY"), ("afternoon", "AFTERNOON"), ("night", "NIGHT"))


class LastDayCard(QFrame):
    """The previous Battle day per session, like the original "ELŐZŐ NAP" card."""

    ROWS = (
        ("total", "Összes tipp"),
        ("won", "Nyert"),
        ("lost", "Vesztett"),
        ("units", "Profit (egység)"),
        ("roi", "ROI"),
    )

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(5)
        hdr = QHBoxLayout()
        self.date_lbl = QLabel("ELŐZŐ NAP")
        self.date_lbl.setObjectName("cardTitle")
        self.date_lbl.setFont(QFont("Segoe UI Semibold", 10))
        hdr.addWidget(self.date_lbl)
        hdr.addStretch()
        for _, text in SESSION_COLUMNS:
            col = QLabel(text)
            col.setFont(QFont("Segoe UI Semibold", 10))
            col.setStyleSheet(f"color: {ACCENT};")
            col.setFixedWidth(84)
            col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            hdr.addWidget(col)
        root.addLayout(hdr)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #2a2d3a; border: none; max-height: 1px;")
        root.addWidget(sep)
        self.vals: dict[str, list[QLabel]] = {}
        for key, label in self.ROWS:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 11))
            lbl.setStyleSheet("color: #ffffff;")
            row.addWidget(lbl)
            row.addStretch()
            cells = []
            for _ in SESSION_COLUMNS:
                v = QLabel("–")
                v.setFont(QFont("Segoe UI Semibold", 11))
                v.setFixedWidth(84)
                v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row.addWidget(v)
                cells.append(v)
            root.addLayout(row)
            self.vals[key] = cells

    def update_stats(self, day: str | None, buckets: dict | None) -> None:
        if not day or not buckets:
            self.date_lbl.setText("ELŐZŐ NAP — nincs adat")
            for cells in self.vals.values():
                for c in cells:
                    c.setText("–")
                    c.setStyleSheet("color: #555;")
            return
        self.date_lbl.setText(f"ELŐZŐ NAP  ·  {day}")
        for col, (session, _) in enumerate(SESSION_COLUMNS):
            s = buckets.get(session)
            for key, cells in self.vals.items():
                cell = cells[col]
                cell.setStyleSheet("color: #ffffff;")
                if not s or not s["total"]:
                    cell.setText("–")
                elif key == "units":
                    cell.setText(f"{s['units']:+.2f}")
                elif key == "roi":
                    cell.setText(f"{s['roi']:+.1f}%")
                else:
                    cell.setText(str(s[key]))


class MiniChart(QLabel):
    """Daily profit bars + cumulative dashed line, rendered with matplotlib's Agg backend into
    a QLabel (no native window), exactly like the original dashboard. Optional: without
    matplotlib the label just stays empty."""

    BG = "#12121f"

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(130)
        self.setMaximumHeight(170)
        self.setScaledContents(True)
        self.setStyleSheet(f"background: {self.BG}; border-radius: 4px;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        try:
            from matplotlib.backends.backend_agg import FigureCanvasAgg
            from matplotlib.figure import Figure
        except ImportError:
            self.fig = None
            return
        self.fig = Figure(figsize=(8, 2), dpi=100, facecolor=self.BG, tight_layout=True)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasAgg(self.fig)

    def draw(self, days: list[tuple[str, float]]) -> None:
        if self.fig is None:
            return
        ax = self.ax
        ax.clear()
        ax.set_facecolor(self.BG)
        y = [v for _, v in days]
        x = list(range(len(y)))
        cumul, run = [], 0.0
        for v in y:
            run += v
            cumul.append(run)
        for i, v in enumerate(y):
            c = "#2ecc71" if v >= 0 else "#e74c3c"
            ax.bar(i, v, color=c, width=0.62, alpha=0.9, zorder=3)
            ax.bar(i, v, color=c, width=0.78, alpha=0.12, zorder=2)
        ax.plot(
            x,
            cumul,
            color=ACCENT,
            linewidth=1.8,
            linestyle="--",
            alpha=0.85,
            zorder=4,
            marker="o",
            markersize=3,
            markerfacecolor=ACCENT,
        )
        ax.axhline(0, color="#333344", linewidth=0.8, zorder=1)
        ax.set_xticks(x)
        ax.set_xticklabels([d[5:] for d, _ in days], color="#555566", fontsize=7, rotation=45, ha="right")
        ax.tick_params(axis="y", colors="#555566", labelsize=7)
        ax.grid(axis="y", color="#ffffff06", linewidth=0.5)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_xlim(-0.6, max(len(y), 1) - 0.4)
        self.canvas.draw()
        buf = self.canvas.buffer_rgba()
        w, h = self.canvas.get_width_height()
        self.setPixmap(QPixmap.fromImage(QImage(bytes(buf), w, h, QImage.Format.Format_RGBA8888)))


SESSION_COLORS = {"day": "#6ec532", "afternoon": "#FDB900", "night": "#4ab8c4"}
# fixed marker order inside a turnus, as on the original bar: latest league first, then S/O/W
VENUE_ORDER = {"L": 0, "B": 1, "S": 2, "O": 3, "W": 4, "A": 5, "E": 6}


def _dot_style(state: str, session: str, radius: int) -> str:
    col = SESSION_COLORS.get(session, "#6e7079")
    if state == "done":
        return f"background-color: #0a1e0a; color: {col}; border-radius: {radius}px; border: 1px solid {col};"
    if state == "overdue":
        return (
            f"background-color: #2a0a0a; color: #e05555; border-radius: {radius}px; "
            "border: 1px solid #c03030;"
        )
    if state == "running":
        return (
            f"background-color: #111811; color: {col}; border-radius: {radius}px; "
            "border: 1px dashed " + col + ";"
        )
    return f"background-color: #111811; color: #3a5a3a; border-radius: {radius}px; border: 1px solid #1e301e;"


class TurnusBar(QFrame):
    """Today's blocks per turnus, as in the original "TURNUSOK" bar: 8-minute turnuses with one
    small marker per venue, 12-minute turnuses as boxes, coloured by session and state."""

    STATE_HU = {
        "done": "kész",
        "running": "folyamatban",
        "overdue": "késik / nincs eredmény",
        "pending": "hátravan",
    }

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(16, 12, 16, 12)
        self.outer.setSpacing(8)
        self.title_lbl = card_title("Turnusok")
        self.outer.addWidget(self.title_lbl)
        self.body = QHBoxLayout()
        self.body.setSpacing(5)
        self.outer.addLayout(self.body)
        leg = QHBoxLayout()
        for sess, label in (("day", "Day"), ("afternoon", "Afternoon"), ("night", "Night")):
            d = QLabel("●")
            d.setStyleSheet(f"color: {SESSION_COLORS[sess]}; font-size: 13px;")
            t = QLabel(label)
            t.setObjectName("cardTitle")
            t.setFont(QFont("Segoe UI", 10))
            leg.addWidget(d)
            leg.addWidget(t)
            leg.addSpacing(14)
        leg.addStretch()
        self.outer.addLayout(leg)
        self._key = None
        self._dots: dict[tuple[str, int], QLabel] = {}

    def _clear(self) -> None:
        def wipe(layout):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    wipe(item.layout())

        wipe(self.body)
        self._dots = {}

    def _build(self, blocks) -> None:
        self._clear()
        for fmt, label in (("8min", "Battle 8min"), ("12min", "Battle 12min")):
            fblocks = [b for b in blocks if b.format == fmt]
            if not fblocks:
                continue
            if fmt == "12min":
                sep = QFrame()
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setFixedWidth(1)
                sep.setStyleSheet("background: #2a2d3a; border: none;")
                self.body.addSpacing(12)
                self.body.addWidget(sep)
                self.body.addSpacing(12)
            box = QVBoxLayout()
            box.setSpacing(3)
            name = QLabel(label)
            name.setFont(QFont("Segoe UI Semibold", 10))
            name.setStyleSheet("color: #ffffff;")
            box.addWidget(name, 0, Qt.AlignmentFlag.AlignLeft)
            row = QHBoxLayout()
            row.setSpacing(4)
            for turnus in sorted({b.turnus for b in fblocks}):
                tb = sorted(
                    (b for b in fblocks if b.turnus == turnus), key=lambda b: VENUE_ORDER.get(b.abbr, 9)
                )
                if fmt == "12min":
                    dot = QLabel(f"T{turnus}")
                    dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    dot.setFixedSize(30, 26)
                    dot.setFont(QFont("Segoe UI Semibold", 10))
                    for b in tb:
                        self._dots[(b.venue, b.turnus)] = dot
                    row.addWidget(dot)
                    continue
                col = QVBoxLayout()
                col.setSpacing(2)
                t = QLabel(f"T{turnus}")
                t.setAlignment(Qt.AlignmentFlag.AlignCenter)
                t.setFont(QFont("Segoe UI Semibold", 8))
                t.setStyleSheet("color: #8a8d99;")
                col.addWidget(t)
                vrow = QHBoxLayout()
                vrow.setSpacing(2)
                for b in tb:
                    vd = QLabel(b.abbr)
                    vd.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    vd.setFixedSize(16, 18)
                    vd.setFont(QFont("Segoe UI Semibold", 8))
                    self._dots[(b.venue, b.turnus)] = vd
                    vrow.addWidget(vd)
                col.addLayout(vrow)
                row.addLayout(col)
                row.addSpacing(4)
            row.addStretch()
            box.addLayout(row)
            self.body.addLayout(box)
        self.body.addStretch()

    def update_blocks(self, day: str, blocks, status: dict) -> None:
        key = (day, tuple((b.venue, b.turnus) for b in blocks))
        if key != self._key:
            self._build(blocks)
            self._key = key
        self.title_lbl.setText(f"TURNUSOK — {day}")
        for b in blocks:
            w = self._dots.get((b.venue, b.turnus))
            if w is None:
                continue
            state = status.get((b.venue, b.turnus), "pending")
            w.setStyleSheet(_dot_style(state, b.session, 4 if b.format == "12min" else 3))
            w.setToolTip(f"T{b.turnus} · {b.venue} ({b.session}) · kezdés {b.start}\n{self.STATE_HU[state]}")
