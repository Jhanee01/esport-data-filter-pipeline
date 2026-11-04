import math
from collections import deque
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSpacerItem, QSizePolicy, QFrame,
)
from PySide6.QtCore import Signal, Qt, QTimer, QPointF, QRectF, QSize
from PySide6.QtGui import (
    QFont, QPalette, QColor, QPixmap, QImage,
    QPainter, QPen, QBrush, QPolygonF, QIcon,
)
from datetime import datetime

from .compat.config import BASE_DIR

# Erőforrás-útvonalak a csomaghoz kötve, hogy tetszőleges telepítési útvonalon működjön
_BALL_IMG = str(BASE_DIR / "assets" / "logo.png")
_FOCI_IMG = str(BASE_DIR / "assets" / "logo.png")


def _make_ball_label(size: int = 32) -> QLabel:
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setStyleSheet("background: transparent;")

    src = QPixmap(_BALL_IMG)
    if src.isNull():
        icon = SoccerBallIcon(size=size)
        return icon

    src = src.scaled(size, size,
                     Qt.AspectRatioMode.IgnoreAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)

    img = src.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    transparent = QColor(0, 0, 0, 0)

    def is_bg(x, y):
        c = img.pixelColor(x, y)
        return c.red() > 215 and c.green() > 215 and c.blue() > 215

    visited: set = set()
    queue: deque = deque()
    for sx, sy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        if is_bg(sx, sy):
            queue.append((sx, sy))
            visited.add((sx, sy))

    while queue:
        x, y = queue.popleft()
        img.setPixelColor(x, y, transparent)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited and is_bg(nx, ny):
                visited.add((nx, ny))
                queue.append((nx, ny))

    # Invertálás: fekete foltok → fehér, fehér foltok → fekete (eltűnik a sötét háttéren)
    for y in range(h):
        for x in range(w):
            c = img.pixelColor(x, y)
            if c.alpha() > 0:
                img.setPixelColor(x, y, QColor(255 - c.red(), 255 - c.green(), 255 - c.blue(), c.alpha()))

    lbl.setPixmap(QPixmap.fromImage(img))
    return lbl


_FC26_IMG = str(BASE_DIR / "assets" / "logo.png")


def _make_logo_icon(size: int = 44) -> QLabel:
    """Betölti a foci.png-t, eltávolítja a fehér hátteret, és visszaad egy QLabel-t."""
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setStyleSheet("background: transparent;")

    src = QPixmap(_FOCI_IMG)
    if src.isNull():
        return _make_fc26_icon_fallback(size)

    src = src.scaled(size, size,
                     Qt.AspectRatioMode.KeepAspectRatio,
                     Qt.TransformationMode.SmoothTransformation)

    img = src.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    w, h = img.width(), img.height()
    transparent = QColor(0, 0, 0, 0)

    def is_bg(x, y):
        c = img.pixelColor(x, y)
        return c.red() > 230 and c.green() > 230 and c.blue() > 230

    visited: set = set()
    queue: deque = deque()
    for sx, sy in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        if is_bg(sx, sy):
            queue.append((sx, sy))
            visited.add((sx, sy))

    while queue:
        x, y = queue.popleft()
        img.setPixelColor(x, y, transparent)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited and is_bg(nx, ny):
                visited.add((nx, ny))
                queue.append((nx, ny))

    lbl.setPixmap(QPixmap.fromImage(img))
    return lbl


def _make_fc26_icon_fallback(size: int = 44) -> QLabel:
    lbl = QLabel()
    lbl.setFixedSize(size, size)
    lbl.setStyleSheet("background: transparent;")
    px = QPixmap(_FC26_IMG)
    if not px.isNull():
        src = px.toImage()
        side = min(src.width(), src.height())
        x = (src.width() - side) // 2
        y = (src.height() - side) // 2
        cropped = src.copy(x, y, side, side)
        px = QPixmap.fromImage(cropped).scaled(
            size, size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        lbl.setPixmap(px)
    return lbl


class SoccerBallIcon(QLabel):
    """Fehér körvonalú rajzolt focilabda ikon."""
    def __init__(self, size: int = 28, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._render(size)

    def _render(self, size: int):
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)

        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor("#ffffff"), max(1.2, size * 0.055))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(QBrush(Qt.BrushStyle.NoBrush))

        cx, cy = size / 2.0, size / 2.0
        R = size / 2.0 - pen.widthF()
        r = R * 0.30

        p.drawEllipse(QRectF(cx - R, cy - R, 2 * R, 2 * R))

        def pent_poly(px, py, radius, offset=0):
            pts = []
            for i in range(5):
                a = math.radians(-90 + offset + i * 72)
                pts.append(QPointF(px + radius * math.cos(a), py + radius * math.sin(a)))
            return QPolygonF(pts)

        p.drawPolygon(pent_poly(cx, cy, r))

        for i in range(5):
            a = math.radians(-90 + i * 72)
            p.drawLine(QPointF(cx + r * math.cos(a), cy + r * math.sin(a)),
                       QPointF(cx + R * math.cos(a), cy + R * math.sin(a)))
            mid_r = (r + R) * 0.62
            p.drawPolygon(pent_poly(cx + mid_r * math.cos(a),
                                    cy + mid_r * math.sin(a),
                                    R * 0.20, i * 72))
        p.end()
        self.setPixmap(pix)


def _make_gear_pixmap(size: int = 19, color: str = "#FDB900") -> QPixmap:
    """Fogaskerék (beállítások) ikon QPainterrel rajzolva — betűtípustól független,
    így garantáltan látszik (a Segoe MDL2 / Symbol glyphek üres dobozként jöttek)."""
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = QColor(color)
    pen = QPen(c, max(1.4, size * 0.11))
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(QBrush(Qt.BrushStyle.NoBrush))

    cx, cy = size / 2.0, size / 2.0
    R = size * 0.30          # fogaskerék-test sugara
    tooth = size * 0.14      # fogak hossza
    teeth = 8

    # Fogak — radiális vonalak a test körül
    for i in range(teeth):
        a = math.radians(i * 360.0 / teeth)
        ca, sa = math.cos(a), math.sin(a)
        p.drawLine(QPointF(cx + R * ca, cy + R * sa),
                   QPointF(cx + (R + tooth) * ca, cy + (R + tooth) * sa))

    # Test + középső lyuk
    p.drawEllipse(QRectF(cx - R, cy - R, 2 * R, 2 * R))
    r = R * 0.42
    p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
    p.end()
    return pix


NAV_ITEMS = [
    ("󰕮", "Dashboard"),
    ("󰐾", "Élő Feed"),
    ("󰈙", "Stratégia Labor"),
    ("󰄬", "Tippek"),
    ("󰈺", "Statisztika"),
    ("󱕬", "H2H Kereső"),
    ("󰆍", "Konzol"),
]

# Unicode ikonok — Segoe UI Symbol betűtípussal garantáltan megjelenik
ICONS = ["◈", "◉", "⊕", "✦", "▤", "⇄", "▸", "✚"]

_SECTION_BTN_STYLE = (
    "QPushButton{background:transparent;color:#ffffff;"
    "border:1px solid rgba(253,185,0,0.35);padding:5px 0;"
    "font-weight:bold;letter-spacing:1px;}"
    "QPushButton:hover{background:rgba(253,185,0,0.10);}"
    "QPushButton:checked{background:#FDB900;color:#111111;border:1px solid #FDB900;}"
)

FONT_FAMILY = "'Karla Variable', 'Karla', 'Segoe UI Variable', 'Inter', 'Segoe UI', sans-serif"

# A menü elválasztói — vastagabb szürke vonal
_GRAY_SEP_QSS = "background: #4f5b62; border: none; min-height: 2px; max-height: 2px;"


def _gray_sep() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(_GRAY_SEP_QSS)
    return sep

# Grasz 1:1 — dark-secondary-400=#404040, border black, csak jobb 15px radius
# Aktív: átlátszó háttér + #FDB900 körvonal + #FDB900 szöveg (mint a FIGYELT gomb)
_ACTIVE_ITEM   = ("background: transparent;"
                  "border-radius: 8px;"
                  "border: 2px solid #FDB900;")
_INACTIVE_ITEM = ("background: transparent;"
                  "border-radius: 8px;"
                  "border: 2px solid transparent;")
_HOVER_ITEM    = ("background: rgba(253,185,0,0.08);"
                  "border-radius: 8px;"
                  "border: 2px solid rgba(253,185,0,0.4);")

_ACTIVE_TEXT   = "color: #FDB900 !important;"
_INACTIVE_TEXT = "color: #ffffff !important;"
_HOVER_TEXT    = "color: #FDB900 !important;"


class NavItem(QWidget):
    clicked = Signal(int)

    def __init__(self, icon: str, label: str, index: int, parent=None):
        super().__init__(parent)
        self.index   = index
        self._active = False

        self.setFixedHeight(68)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout(self)
        row.setContentsMargins(24, 0, 16, 0)
        row.setSpacing(0)

        self.text_lbl = QLabel(label.upper())
        self.text_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)

        row.addWidget(self.text_lbl, 1)

        self._apply(active=False)

    # ------------------------------------------------------------------

    def _apply(self, active: bool, hover: bool = False):
        if active:
            self.setStyleSheet(_ACTIVE_ITEM)
            icon_style = text_style = _ACTIVE_TEXT
            weight = QFont.Weight.Bold
        elif hover:
            self.setStyleSheet(_HOVER_ITEM)
            icon_style = text_style = _HOVER_TEXT
            weight = QFont.Weight.Medium
        else:
            self.setStyleSheet(_INACTIVE_ITEM)
            icon_style = text_style = _INACTIVE_TEXT
            weight = QFont.Weight.Medium

        text_font = QFont("Karla Variable", 30)
        text_font.setWeight(weight)
        self.text_lbl.setFont(text_font)
        self.text_lbl.setStyleSheet(text_style)

        # QPalette-n keresztül is beállítjuk — qt-material nem írja felül
        text_color = QColor("#FDB900") if active or hover else QColor("#ffffff")
        pal = self.text_lbl.palette()
        pal.setColor(QPalette.ColorRole.WindowText, text_color)
        self.text_lbl.setPalette(pal)

    def set_active(self, active: bool):
        self._active = active
        self._apply(active=active)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mousePressEvent(event)

    def enterEvent(self, event):
        if not self._active:
            self._apply(active=False, hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply(active=self._active)
        super().leaveEvent(event)


class Sidebar(QWidget):
    nav_changed = Signal(int)
    settings_requested = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("sidebar")
        self.setFixedWidth(220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Logo terület
        logo_frame = QFrame()
        logo_frame.setObjectName("sidebarLogo")
        logo_frame.setFixedHeight(72)
        logo_row = QHBoxLayout(logo_frame)
        logo_row.setContentsMargins(20, 0, 16, 0)
        logo_row.setSpacing(10)

        dot = _make_logo_icon(size=44)

        title = QLabel("SIGNAL PIPELINE")
        # 14 pt: a hosszabb név így fér ki a logó mellett (a 220 px-es sávban ~130 px jut rá)
        title_font = QFont("Karla Variable", 14)
        title_font.setWeight(QFont.Weight.Bold)
        title.setFont(title_font)
        title.setStyleSheet("color: #ffffff; letter-spacing: 1px;")

        logo_row.addWidget(dot)
        logo_row.addWidget(title)
        logo_row.addStretch()
        layout.addWidget(logo_frame)

        layout.addWidget(_gray_sep())
        layout.addSpacing(8)
        self._section = "fifa"

        # Nav elemek — bal oldal flush (0px), jobb 8px
        layout.setContentsMargins(0, 0, 8, 0)
        self.items: list[NavItem] = []

        # FIFA szekció
        self._fifa_container = QWidget()
        self._fifa_container.setStyleSheet("background: transparent;")
        fifa_vbox = QVBoxLayout(self._fifa_container)
        fifa_vbox.setContentsMargins(0, 0, 0, 0)
        fifa_vbox.setSpacing(2)
        for i, (icon, label) in enumerate(zip(ICONS, [n[1] for n in NAV_ITEMS])):
            item = NavItem(icon, label, i)
            item.clicked.connect(self._on_nav)
            fifa_vbox.addWidget(item)
            self.items.append(item)
        layout.addWidget(self._fifa_container)

        # Egyedi stratégiák szekció (dinamikus, kezdetben rejtett)
        self._custom_sep = QFrame()
        self._custom_sep.setFrameShape(QFrame.Shape.HLine)
        self._custom_sep.setStyleSheet(_GRAY_SEP_QSS)
        self._custom_sep.setVisible(False)
        layout.addWidget(self._custom_sep)

        self._custom_section_lbl = QLabel("  EGYEDI STRATÉGIÁK")
        csl_f = QFont("Segoe UI", 8)
        csl_f.setWeight(QFont.Weight.Bold)
        self._custom_section_lbl.setFont(csl_f)
        self._custom_section_lbl.setStyleSheet("color: #555; letter-spacing: 1px; background: transparent;")
        self._custom_section_lbl.setFixedHeight(22)
        self._custom_section_lbl.setVisible(False)
        layout.addWidget(self._custom_section_lbl)

        self._custom_container = QWidget()
        self._custom_container.setStyleSheet("background: transparent;")
        self._custom_vbox = QVBoxLayout(self._custom_container)
        self._custom_vbox.setContentsMargins(0, 0, 0, 0)
        self._custom_vbox.setSpacing(2)
        self._custom_container.setVisible(False)
        layout.addWidget(self._custom_container)

        self._custom_nav_items: list[NavItem] = []

        layout.addSpacerItem(
            QSpacerItem(0, 0, QSizePolicy.Policy.Minimum,
                        QSizePolicy.Policy.Expanding))


        # Elválasztó lent
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(_GRAY_SEP_QSS)
        layout.addWidget(sep2)

        # Mód + óra
        footer = QWidget()
        footer.setObjectName("sidebarFooter")
        footer.setFixedHeight(56)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(20, 6, 12, 6)
        footer_layout.setSpacing(6)

        _mode_clock = QVBoxLayout()
        _mode_clock.setContentsMargins(0, 0, 0, 0)
        _mode_clock.setSpacing(2)

        self.mode_label = QLabel("● DAY")
        self.mode_label.setObjectName("modeLabel")

        self.clock_label = QLabel()
        self.clock_label.setObjectName("clockLabel")

        _mode_clock.addWidget(self.mode_label)
        _mode_clock.addWidget(self.clock_label)
        footer_layout.addLayout(_mode_clock)
        footer_layout.addStretch()

        # Beállítások (fogaskerék) — a token/csatorna-ID-k és a stratégia→csatorna routing.
        # A gear glyph a Windows "Segoe MDL2 Assets" ikonkészletből (U+E713) — a sima
        # "⚙" (U+2699) sok betűtípusban üres dobozként jelenik meg.
        self.settings_btn = QPushButton()
        self.settings_btn.setObjectName("settingsBtn")
        self.settings_btn.setFixedSize(34, 34)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.setToolTip("Beállítások (token, csatornák, routing)")
        # Fogaskerék ikon QPainterrel rajzolva — betűtípustól függetlenül
        # garantáltan látszik (a font-glyphek üres dobozként jelentek meg).
        self.settings_btn.setIcon(QIcon(_make_gear_pixmap(19, "#FDB900")))
        self.settings_btn.setIconSize(QSize(19, 19))
        self.settings_btn.setStyleSheet(
            "QPushButton#settingsBtn{background:transparent;"
            "border:1px solid rgba(253,185,0,0.5);border-radius:6px;}"
            "QPushButton#settingsBtn:hover{border:1px solid #FDB900;"
            "background:rgba(253,185,0,0.12);}"
        )
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        footer_layout.addWidget(self.settings_btn)

        layout.addWidget(footer)

        self._update_clock()
        timer = QTimer(self)
        timer.timeout.connect(self._update_clock)
        timer.start(1000)

    def add_custom_nav_item(self, label: str, index: int):
        item = NavItem("◈", label, index)
        item.clicked.connect(self._on_nav)
        self._custom_vbox.addWidget(item)
        self._custom_nav_items.append(item)
        self.items.append(item)
        self._update_custom_visibility()

    def remove_custom_nav_items(self):
        for item in self._custom_nav_items:
            self._custom_vbox.removeWidget(item)
            item.deleteLater()
            if item in self.items:
                self.items.remove(item)
        self._custom_nav_items.clear()
        self._update_custom_visibility()

    def _update_custom_visibility(self):
        visible = self._section == "fifa" and bool(self._custom_nav_items)
        self._custom_container.setVisible(visible)
        self._custom_sep.setVisible(visible)
        self._custom_section_lbl.setVisible(visible)

    def _on_nav(self, index: int):
        self.set_active(index)
        self.nav_changed.emit(index)

    def set_active(self, index: int):
        for item in self.items:
            item.set_active(item.index == index)

    def set_mode(self, mode: str):
        if mode == "day":
            self.mode_label.setText("● DAY")
            self.mode_label.setStyleSheet("color: #FDB900; font-size: 11px; font-family: 'Segoe UI Semibold';")
        else:
            self.mode_label.setText("● NIGHT")
            self.mode_label.setStyleSheet("color: #4ab8c4; font-size: 11px; font-family: 'Segoe UI Semibold';")

    def _update_clock(self):
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))
