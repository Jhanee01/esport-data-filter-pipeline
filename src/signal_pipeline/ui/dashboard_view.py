from datetime import datetime, timedelta, date
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QPushButton, QSizePolicy, QScrollArea,
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QImage, QPixmap, QAction
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .compat.config import APP_VERSION
from .compat import latest_schedule
from .compat.turnus import TURNUS_SCHEDULE, TURNUS_SCHEDULE_12, TURNUS_VENUE_SCRAPE_AT, venue_filter_time
from .compat.stats_manager import get_strategy_tabs, get_daily_stats, compute_summary, get_last_completed_day_stats, SHADOW_TAB_KEYS
from .compat.process_manager import PROCESSES, TOGGLEABLE
from .compat import runtime
from ..battle_day import today_battle_day
from ..schedule import block_status, _day_minutes
from .stats_view import _CheckableMenu


# ──────────────────────────────────────────────
# Státusz kártya
# ──────────────────────────────────────────────



def _latest8(t_num: int, date_str: str = None):
    """A San Siro napi blokkja ehhez a turnushoz a scraper által mentett API-menetrendből
    (a csomag menetrend-fájljából; hálózatot a dashboard nem hív), vagy None."""
    d = date_str or datetime.now().strftime("%Y-%m-%d")
    return latest_schedule.blocks_for(d, fetch=False).get(t_num)


def _slots8(t_num: int, cfg: dict, date_str: str = None) -> list:
    """A 8p turnus blokkjai a dashboardon: a Latest liga (San Siro) + a 3 régi pálya."""
    lb = _latest8(t_num, date_str)
    return ([(latest_schedule.VENUE, lb["start"])] if lb else []) + list(cfg["slots"])


def _venue_scrape_at8(t_num: int, venue: str, cfg: dict, date_str: str = None) -> str:
    if venue == latest_schedule.VENUE:
        lb = _latest8(t_num, date_str)
        if lb:
            return lb["scrape_at"]
    return TURNUS_VENUE_SCRAPE_AT.get(t_num, {}).get(venue) or cfg["scrape_at"]


def _venue_name(venue: str) -> str:
    return "Latest liga (San Siro)" if venue == "San Siro" else venue

# A Dashboard fülsorából elhagyott stratégiák (a Statisztika nézetben megmaradnak).
_DASH_HIDDEN_TABS: set = set()


class StatusCard(QFrame):
    restart_clicked = Signal(str)
    toggle_clicked  = Signal(str)

    STATUS_COLORS = {"running": "#FDB900", "stopped": "#d44a3a", "error": "#c0392b"}
    STATUS_LABELS = {"running": "● FUT", "stopped": "● LEÁLLÍTVA", "error": "● HIBA"}

    def __init__(self, name: str, label: str, toggleable: bool = False, parent=None):
        super().__init__(parent)
        self.name = name
        self._toggleable = toggleable
        self._running = False
        self.setObjectName("card")
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        hdr = QHBoxLayout()
        self.title_lbl = QLabel(label)
        self.title_lbl.setFont(QFont("Segoe UI Semibold", 12))

        self.badge = QLabel("● LEÁLLÍTVA")
        self.badge.setFont(QFont("Segoe UI Semibold", 11))
        self.badge.setStyleSheet(f"color: {self.STATUS_COLORS['stopped']};")
        self.badge.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        hdr.addWidget(self.title_lbl)
        hdr.addStretch()
        hdr.addWidget(self.badge)
        layout.addLayout(hdr)

        self.msg_lbl = QLabel("Nem fut")
        self.msg_lbl.setFont(QFont("Segoe UI", 11))
        self.msg_lbl.setStyleSheet("color: #8d8d9f;")
        layout.addWidget(self.msg_lbl)

        if toggleable:
            self.toggle_btn = QPushButton("▶  Indítás")
            self.toggle_btn.setFixedHeight(30)
            self.toggle_btn.setFont(QFont("Segoe UI Semibold", 11))
            self.toggle_btn.setStyleSheet("background-color: #0a1e0a; color: #FDB900; border: 1px solid #FDB900; border-radius: 6px;")
            self.toggle_btn.clicked.connect(lambda: self.toggle_clicked.emit(self.name))
            layout.addWidget(self.toggle_btn)
        else:
            self.restart_btn = QPushButton("Újraindítás")
            self.restart_btn.setFixedHeight(26)
            self.restart_btn.setFont(QFont("Segoe UI", 11))
            self.restart_btn.clicked.connect(lambda: self.restart_clicked.emit(self.name))
            layout.addWidget(self.restart_btn)

    def update_status(self, status: str, message: str):
        col   = self.STATUS_COLORS.get(status, "#6e7079")
        label = self.STATUS_LABELS.get(status, "○")
        self.badge.setText(label)
        self.badge.setStyleSheet(f"color: {col};")
        self.msg_lbl.setText(message)
        self._running = (status == "running")

        if self._toggleable:
            if self._running:
                self.toggle_btn.setText("■  Leállítás")
                self.toggle_btn.setStyleSheet("background-color: #3a1c1c; color: #d44a3a; border: 1px solid #d44a3a; border-radius: 6px;")
            else:
                self.toggle_btn.setText("▶  Indítás")
                self.toggle_btn.setStyleSheet("background-color: #0a1e0a; color: #FDB900; border: 1px solid #FDB900; border-radius: 6px;")
        else:
            self.restart_btn.setEnabled(status != "running")


# ──────────────────────────────────────────────
# Összesítő mini kártya
# ──────────────────────────────────────────────

class MiniCard(QFrame):
    def __init__(self, label: str, value: str = "–", color: str = "#d9d9d9", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        lbl = QLabel(label.upper())
        lbl.setObjectName("cardTitle")
        lbl.setFont(QFont("Segoe UI Semibold", 10))

        self.val = QLabel(value)
        self.val.setFont(QFont("Segoe UI Semibold", 30))
        self.val.setStyleSheet(f"color: {color};")

        layout.addWidget(lbl)
        layout.addWidget(self.val)

    def set_value(self, value: str, color: str | None = None):
        self.val.setText(value)
        if color:
            self.val.setStyleSheet(f"color: {color};")


# ──────────────────────────────────────────────
# Előző nap statisztika kártya (Day / Night)
# ──────────────────────────────────────────────

class LastDayCard(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 10, 14, 10)
        root.setSpacing(5)

        # Fejléc: dátum + oszlopfejek
        hdr = QHBoxLayout()
        self._date_lbl = QLabel("ELŐZŐ NAP")
        self._date_lbl.setObjectName("cardTitle")
        self._date_lbl.setFont(QFont("Segoe UI Semibold", 10))
        hdr.addWidget(self._date_lbl)
        hdr.addStretch()
        for txt in ("DAY", "NIGHT"):
            col_hdr = QLabel(txt)
            col_hdr.setFont(QFont("Segoe UI Semibold", 10))
            col_hdr.setStyleSheet("color: #FDB900;")
            col_hdr.setFixedWidth(68)
            col_hdr.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            hdr.addWidget(col_hdr)
        root.addLayout(hdr)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background: #2a2d3a; border: none; max-height: 1px;")
        root.addWidget(sep)

        # Sorok
        self._vals: dict[str, list[QLabel]] = {}
        rows = [
            ("total", "Összes tipp"),
            ("won",   "Nyert"),
            ("lost",  "Vesztett"),
            ("units", "Profit (egység)"),
            ("roi",   "ROI"),
        ]
        for key, label in rows:
            row = QHBoxLayout()
            row.setSpacing(4)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 11))
            lbl.setStyleSheet("color: #ffffff;")
            row.addWidget(lbl)
            row.addStretch()
            vals = []
            for _ in range(2):
                v = QLabel("–")
                v.setFont(QFont("Segoe UI Semibold", 11))
                v.setFixedWidth(68)
                v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row.addWidget(v)
                vals.append(v)
            root.addLayout(row)
            self._vals[key] = vals

    def update_stats(self, data: dict | None):
        if data is None:
            self._date_lbl.setText("ELŐZŐ NAP — nincs adat")
            for lbls in self._vals.values():
                for l in lbls:
                    l.setText("–")
                    l.setStyleSheet("color: #555;")
            return

        self._date_lbl.setText(f"ELŐZŐ NAP  ·  {data['date']}")

        for col, session in enumerate(("day", "night")):
            s = data[session]
            for key, lbls in self._vals.items():
                lbl = lbls[col]
                lbl.setStyleSheet("color: #ffffff;")
                if key == "total":
                    lbl.setText(str(s["total"]) if s["total"] else "–")
                elif key == "won":
                    lbl.setText(str(s["won"]) if s["total"] else "–")
                elif key == "lost":
                    lbl.setText(str(s["lost"]) if s["total"] else "–")
                elif key == "units":
                    lbl.setText(f"{s['units']:+.2f}" if s["total"] else "–")
                elif key == "roi":
                    lbl.setText(f"{s['roi']:+.1f}%" if s["total"] else "–")


# ──────────────────────────────────────────────
# Feldolgozás kezdő dátuma dialógus
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# Turnus állapot sáv
# ──────────────────────────────────────────────

class TurnusBar(QFrame):
    config_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")

        # Külső sor: balra a tartalom (cím + turnusok + jelmagyarázat),
        # jobbra a gomb az üres térben függőlegesen középre igazítva.
        outer = QHBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(12)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.title_lbl = QLabel(f"TURNUSOK — {datetime.now().strftime('%Y-%m-%d')}")
        self.title_lbl.setObjectName("cardTitle")
        self.title_lbl.setFont(QFont("Segoe UI Semibold", 11))
        layout.addWidget(self.title_lbl)

        self.dots_row = QHBoxLayout()
        self.dots_row.setSpacing(5)
        # 8min: pályánként bontva -> {turnus: {venue: QLabel}}
        self.venue_dots: dict[int, dict[str, QLabel]] = {}
        self.dot_labels_12: list[QLabel] = []

        SESSION_COLORS = {"day": "#6ec532", "afternoon": "#FDB900", "night": "#4ab8c4"}
        # pálya -> rövidítés (a mini-jelzőn)
        # „L” = Latest liga (San Siro), a 8p 4. pályája
        VENUE_ABBR = {"Stamford Bridge": "S", "Old Trafford": "O", "Wembley": "W",
                      "San Siro": "L"}

        # ── Battle 8 min blokk: felirat FÖLÜL, alatta a turnusok (S/O/W) ──
        box8 = QVBoxLayout()
        box8.setSpacing(3)
        box8.setContentsMargins(0, 0, 0, 0)
        lbl_8 = QLabel("Battle 8min")
        lbl_8.setFont(QFont("Segoe UI Semibold", 10))
        lbl_8.setStyleSheet("color: #ffffff;")
        box8.addWidget(lbl_8, 0, Qt.AlignmentFlag.AlignLeft)

        row8 = QHBoxLayout()
        row8.setSpacing(4)
        row8.setContentsMargins(0, 0, 0, 0)
        for t_num, cfg in TURNUS_SCHEDULE.items():
            col = QVBoxLayout()
            col.setSpacing(2)
            col.setContentsMargins(0, 0, 0, 0)
            tlbl = QLabel(f"T{t_num}")
            tlbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tlbl.setFont(QFont("Segoe UI Semibold", 8))
            tlbl.setStyleSheet("color: #8a8d99;")
            col.addWidget(tlbl)

            vrow = QHBoxLayout()
            vrow.setSpacing(2)
            vrow.setContentsMargins(0, 0, 0, 0)
            self.venue_dots[t_num] = {}
            # San Siro „L” jelző MINDEN turnusban készül: a napi API-menetrendtől függ,
            # melyik turnusban van blokk -> az update_turnuses rejti el, ahol nincs.
            for venue, _tf in [(latest_schedule.VENUE, "")] + list(cfg["slots"]):
                vd = QLabel(VENUE_ABBR.get(venue, venue[:1]))
                vd.setAlignment(Qt.AlignmentFlag.AlignCenter)
                vd.setFixedSize(16, 18)
                vd.setFont(QFont("Segoe UI Semibold", 8))
                vd.setStyleSheet(
                    "background-color: #111811; color: #3a5a3a; "
                    "border-radius: 3px; border: 1px solid #1e301e;"
                )
                vsat = _venue_scrape_at8(t_num, venue, cfg)
                vd.setToolTip(f"8min T{t_num} {_venue_name(venue)} | {cfg['session']} | scrape: {vsat}")
                self.venue_dots[t_num][venue] = vd
                vrow.addWidget(vd)
            col.addLayout(vrow)
            row8.addLayout(col)
            row8.addSpacing(4)
        box8.addLayout(row8)
        self.dots_row.addLayout(box8)

        # --- Elválasztó ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background: #2a2d3a; border: none;")
        self.dots_row.addSpacing(12)
        self.dots_row.addWidget(sep)
        self.dots_row.addSpacing(12)

        # ── Battle 12 min blokk: felirat FÖLÜL, alatta a turnusok ──
        box12 = QVBoxLayout()
        box12.setSpacing(3)
        box12.setContentsMargins(0, 0, 0, 0)
        lbl_12 = QLabel("Battle 12min")
        lbl_12.setFont(QFont("Segoe UI Semibold", 10))
        lbl_12.setStyleSheet("color: #ffffff;")
        box12.addWidget(lbl_12, 0, Qt.AlignmentFlag.AlignLeft)

        row12 = QHBoxLayout()
        row12.setSpacing(4)
        row12.setContentsMargins(0, 0, 0, 0)
        for t_num, cfg in TURNUS_SCHEDULE_12.items():
            dot = QLabel(f"T{t_num}")
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setFixedSize(30, 26)
            dot.setFont(QFont("Segoe UI Semibold", 10))
            dot.setStyleSheet(
                "background-color: #111811; color: #3a5a3a; "
                "border-radius: 4px; border: 1px solid #1e301e;"
            )
            dot.setToolTip(f"12min T{t_num} | {cfg['session']} | scrape: {cfg['scrape_at']}")
            self.dot_labels_12.append(dot)
            row12.addWidget(dot)
        # a 12min sor aljához igazítjuk, hogy a pötytök a 8min pötytökkel egy vonalban legyenek
        row12.addStretch()
        box12.addLayout(row12)
        self.dots_row.addLayout(box12)

        self.dots_row.addStretch()
        layout.addLayout(self.dots_row)

        # Jelmagyarázat
        leg = QHBoxLayout()
        for sess, col, lbl_txt in [
            ("day", "#6ec532", "Day"),
            ("afternoon", "#FDB900", "Afternoon"),
            ("night", "#4ab8c4", "Night"),
        ]:
            d = QLabel("●"); d.setStyleSheet(f"color: {col}; font-size: 13px;")
            t = QLabel(lbl_txt); t.setObjectName("cardTitle"); t.setFont(QFont("Segoe UI", 10))
            leg.addWidget(d); leg.addWidget(t); leg.addSpacing(14)
        leg.addStretch()
        layout.addLayout(leg)

        outer.addLayout(layout, 1)


    @staticmethod
    def _scrape_at_mins(scrape_at: str) -> int:
        h, m = map(int, scrape_at.split(":"))
        # scrape_at < 07:00 → éjfélen túli slot (másnap reggel)
        return (h + 24) * 60 + m if h < 7 else h * 60 + m

    @staticmethod
    def _now_mins(now: datetime) -> int:
        if now.hour < 7:
            return (now.hour + 24) * 60 + now.minute
        return now.hour * 60 + now.minute

    @staticmethod
    def _add_mins(hhmm: str, mins: int) -> str:
        h, m = map(int, hhmm.split(":"))
        total = (h * 60 + m + mins) % 1440
        return f"{total // 60:02d}:{total % 60:02d}"

    def update_turnuses(self, blocks_8: dict, done_12: set[int], session_date: str = "",
                        failed_8: dict = None, failed_12: set = None):
        """blocks_8: {str(turnus): [kész pályák]} a completed_blocks-ból (pálya-szintű).
        failed_8: {str(turnus): [feladott pályák]} a failed_blocks-ból — végleg piros.
        failed_12: a 12p turnusai, amelyekhez lejárt idő után sincs eredmény — piros."""
        SESSION_COLORS = {"day": "#6ec532", "afternoon": "#FDB900", "night": "#4ab8c4"}
        now = datetime.now()
        now_m = self._now_mins(now)

        for t_num, cfg in TURNUS_SCHEDULE.items():
            col = SESSION_COLORS.get(cfg["session"], "#6e7079")
            done_venues = blocks_8.get(str(t_num), [])
            failed_venues = (failed_8 or {}).get(str(t_num), [])
            lb = _latest8(t_num, session_date or None)
            ld = self.venue_dots.get(t_num, {}).get(latest_schedule.VENUE)
            if ld is not None:
                ld.setVisible(lb is not None)
            for venue, _tf in _slots8(t_num, cfg, session_date or None):
                vd = self.venue_dots.get(t_num, {}).get(venue)
                if vd is None:
                    continue
                vsat = _venue_scrape_at8(t_num, venue, cfg, session_date or None)
                szures = venue_filter_time(t_num, venue, vsat)
                scr_m = self._scrape_at_mins(vsat)
                sess = lb["session"] if venue == latest_schedule.VENUE else cfg["session"]
                if venue == latest_schedule.VENUE:
                    col = SESSION_COLORS.get(sess, "#6e7079")
                else:
                    col = SESSION_COLORS.get(cfg["session"], "#6e7079")
                head = f"T{t_num} · {_venue_name(venue)} ({sess})"
                if venue in done_venues:
                    vd.setStyleSheet(
                        f"background-color: #0a1e0a; color: {col}; "
                        f"border-radius: 3px; border: 1px solid {col};"
                    )
                    vd.setToolTip(f"{head}\nScrape: {vsat} · Szűrés: {szures}\n✅ Kész — scrape-elve")
                elif venue in failed_venues:
                    vd.setStyleSheet(
                        "background-color: #3a0808; color: #ff6b6b; "
                        "border-radius: 3px; border: 2px solid #e03030;"
                    )
                    vd.setToolTip(f"{head}\nScrape: {vsat} · Szűrés: {szures}\n"
                                  f"❌ SIKERTELEN — a scrape a retry-k után is feladva")
                elif scr_m <= now_m:
                    vd.setStyleSheet(
                        "background-color: #2a0a0a; color: #e05555; "
                        "border-radius: 3px; border: 1px solid #c03030;"
                    )
                    vd.setToolTip(f"{head}\nScrape: {vsat} · Szűrés: {szures}\n⏳ Esedékes / retry folyamatban")
                else:
                    left = scr_m - now_m
                    lh, lm = divmod(left, 60)
                    left_txt = f"{lh} ó {lm} p" if lh else f"{lm} perc"
                    vd.setStyleSheet(
                        "background-color: #111811; color: #3a5a3a; "
                        "border-radius: 3px; border: 1px solid #1e301e;"
                    )
                    vd.setToolTip(f"{head}\nScrape: {vsat} ({left_txt} múlva) · Szűrés: {szures}\n⌛ Hátravan")

        for i, (t_num, cfg) in enumerate(TURNUS_SCHEDULE_12.items()):
            dot = self.dot_labels_12[i]
            col = SESSION_COLORS.get(cfg["session"], "#6e7079")
            if t_num in done_12:
                dot.setStyleSheet(
                    f"background-color: #0a1e0a; color: {col}; "
                    f"border-radius: 4px; border: 1px solid {col};"
                )
            elif t_num in (failed_12 or set()):
                dot.setStyleSheet(
                    "background-color: #3a0808; color: #ff6b6b; "
                    "border-radius: 4px; border: 2px solid #e03030;"
                )
            elif self._scrape_at_mins(cfg["scrape_at"]) <= now_m:
                dot.setStyleSheet(
                    "background-color: #2a0a0a; color: #e05555; "
                    "border-radius: 4px; border: 1px solid #c03030;"
                )
            else:
                dot.setStyleSheet(
                    "background-color: #111811; color: #3a5a3a; "
                    "border-radius: 4px; border: 1px solid #1e301e;"
                )

        d = session_date or now.strftime("%Y-%m-%d")
        self.title_lbl.setText(f"TURNUSOK — {d}")


# ──────────────────────────────────────────────
# Főképernyő Dashboard
# ──────────────────────────────────────────────

class DashboardView(QWidget):
    restart_requested       = Signal(str)
    toggle_requested        = Signal(str)
    rebuild_stats_requested = Signal()
    check_updates_requested = Signal()   # "Frissítés keresése" gomb
    update_install_requested = Signal()  # elérhető frissítés telepítése

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentView")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(14)

        # ── Cím + verzió/frissítés ──
        title_row = QHBoxLayout()
        title = QLabel("Dashboard")
        title.setObjectName("viewTitle")
        title.setFont(QFont("Segoe UI Semibold", 16))
        title_row.addWidget(title)
        title_row.addStretch()

        self._version_lbl = QLabel(f"v{APP_VERSION}")
        self._version_lbl.setFont(QFont("Segoe UI", 10))
        self._version_lbl.setStyleSheet("color: #ffffff;")
        title_row.addWidget(self._version_lbl)

        self._update_info = None
        self._update_btn = QPushButton("Frissítés keresése")
        self._update_btn.setFixedHeight(28)
        self._update_btn.setFont(QFont("Segoe UI", 10))
        self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_update_btn(False)
        self._update_btn.clicked.connect(self._on_update_btn)
        title_row.addWidget(self._update_btn)
        root.addLayout(title_row)

        # ── Felső sor: státusz + összesítő ──
        top_row = QHBoxLayout()
        top_row.setSpacing(14)

        # --- Bal: Rendszer státusz ---
        status_col = QVBoxLayout()
        status_col.setSpacing(8)

        status_hdr = QLabel("RENDSZER STÁTUSZ")
        status_hdr.setObjectName("cardTitle")
        status_hdr.setFont(QFont("Segoe UI Semibold", 11))
        status_col.addWidget(status_hdr)

        self.cards: dict[str, StatusCard] = {}
        _TOGGLEABLE = TOGGLEABLE

        cards_widget = QWidget()
        cards_widget.setObjectName("transparentWidget")
        cards_inner = QVBoxLayout(cards_widget)
        cards_inner.setContentsMargins(0, 0, 4, 0)
        cards_inner.setSpacing(8)

        for name, cfg in PROCESSES.items():
            card = StatusCard(name, cfg["label"], toggleable=(name in _TOGGLEABLE))
            card.restart_clicked.connect(self.restart_requested)
            card.toggle_clicked.connect(self.toggle_requested)
            self.cards[name] = card
            cards_inner.addWidget(card)

        cards_inner.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(cards_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # A vízszintes görgetés ki van kapcsolva, ezért ha a viewport a kártya
        # minimumánál (240) keskenyebbre nyomódik, a kártya jobb oldala — a
        # Leállítás/Újraindítás gomb — SZÓ NÉLKÜL levágódik. A jobb oldali
        # stratégia-gombsor szélesedésekor pontosan ez történt, ezért a bal oszlop
        # kap egy védett minimumot: kártya (240) + belső margó (4) + görgetősáv (8).
        scroll.setMinimumWidth(252)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                             "QScrollBar:vertical { width: 8px; background: #1a1a1a; border-radius: 4px; }"
                             "QScrollBar::handle:vertical { background: #FDB900; border-radius: 4px; min-height: 20px; }"
                             "QScrollBar::handle:vertical:hover { background: #ffd54f; }"
                             "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }")

        status_col.addWidget(scroll)
        top_row.addLayout(status_col, 3)

        # --- Jobboldal: Összesítő kártyák + mini grafikon ---
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        # Stratégia választó sor
        strat_row = QHBoxLayout()
        strat_row.setSpacing(8)
        summary_hdr = QLabel("TELJESÍTMÉNY")
        summary_hdr.setObjectName("cardTitle")
        summary_hdr.setFont(QFont("Segoe UI Semibold", 11))
        strat_row.addWidget(summary_hdr)

        # Tab container — QWidget + QVBoxLayout, két külön keret
        tab_container = QWidget()
        tab_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        tab_vbox = QVBoxLayout(tab_container)
        tab_vbox.setContentsMargins(0, 0, 0, 0)
        tab_vbox.setSpacing(4)

        # Mindkét sor: keret a gombokhoz igazítva, középre helyezve
        frame_row1 = QFrame()
        frame_row1.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        frame_row1.setStyleSheet("QFrame{background:#212121;border-radius:8px;}")
        row1_layout = QHBoxLayout(frame_row1)
        row1_layout.setContentsMargins(6, 4, 6, 4)
        row1_layout.setSpacing(4)

        frame_row2 = QFrame()
        frame_row2.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        frame_row2.setStyleSheet("QFrame{background:#212121;border-radius:8px;}")
        row2_layout = QHBoxLayout(frame_row2)
        row2_layout.setContentsMargins(6, 4, 6, 4)
        row2_layout.setSpacing(4)

        self._tab_row1 = row1_layout
        self._tab_row2 = row2_layout
        self._dash_sources: list | None = None
        self._dash_active_key: str = "all"
        self._dash_filter_checked: set[str] = set()
        self._dash_all_btn: QPushButton | None = None
        self._dash_tab_btns: dict[str, QPushButton] = {}
        # Stratégia-szűrő menü — MAGA az "Összes" tab a legördülő
        self._dash_filter_menu = _CheckableMenu(self)
        self._dash_filter_menu.aboutToShow.connect(
            lambda: self._set_dash_strategy("all", None))

        _tab_btn_order: list[QPushButton] = []
        for key, label, sources in get_strategy_tabs():
            if key in _DASH_HIDDEN_TABS:
                continue
            text = (label + "  ▾") if key == "all" else label
            btn = QPushButton(text)
            btn.setFixedHeight(26)
            btn.setFont(QFont("Segoe UI", 11))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if key == "all":
                btn.setMenu(self._dash_filter_menu)
                self._dash_all_btn = btn
            else:
                btn.clicked.connect(
                    lambda _, k=key, s=sources: self._set_dash_strategy(k, s))
            self._dash_tab_btns[key] = btn
            _tab_btn_order.append(btn)

        self._distribute_tab_buttons(_tab_btn_order, row1_layout, row2_layout)

        # Mindkét sor középre igazítva stretch-csel
        for frame in (frame_row1, frame_row2):
            wrap = QHBoxLayout()
            wrap.setContentsMargins(0, 0, 0, 0)
            wrap.addStretch()
            wrap.addWidget(frame)
            wrap.addStretch()
            tab_vbox.addLayout(wrap)

        strat_row.addWidget(tab_container)
        right_col.addLayout(strat_row)
        self._build_dash_filter_menu()

        mini_cards = QHBoxLayout()
        mini_cards.setSpacing(10)
        self.mc_units = MiniCard("Egységek", "–", "#FDB900")
        self.mc_roi   = MiniCard("ROI", "–", "#888888")
        self.mc_won   = MiniCard("Nyert", "–", "#3ba560")
        self.mc_total = MiniCard("Összes", "–", "#888888")
        for mc in (self.mc_units, self.mc_roi, self.mc_won, self.mc_total):
            mini_cards.addWidget(mc)
        right_col.addLayout(mini_cards)

        # Előző nap statisztika
        self._last_day_card = LastDayCard()
        right_col.addWidget(self._last_day_card)

        # Mini grafikon (utolsó 14 nap) — Agg backend: QLabel-be renderelünk, nincs natív Qt ablak
        self._mini_fig = Figure(figsize=(8, 2), dpi=100, facecolor="#12121f", tight_layout=True)
        self._mini_ax  = self._mini_fig.add_subplot(111)
        self._mini_canvas = FigureCanvasAgg(self._mini_fig)
        self.mini_plot = QLabel()
        self.mini_plot.setMinimumHeight(130)
        self.mini_plot.setMaximumHeight(170)
        self.mini_plot.setScaledContents(True)
        self.mini_plot.setStyleSheet("background: #12121f; border-radius: 4px;")
        self.mini_plot.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        right_col.addWidget(self.mini_plot)

        top_row.addLayout(right_col, 4)
        root.addLayout(top_row, 1)

        # ── Turnus sáv ──
        self.turnus_bar = TurnusBar()
        root.addWidget(self.turnus_bar)

        # ── Timerek ──
        self._turnus_timer = QTimer(self)
        self._turnus_timer.timeout.connect(self._refresh_turnuses)
        self._turnus_timer.start(15000)

        self._summary_timer = QTimer(self)
        self._summary_timer.timeout.connect(self._refresh_summary)
        self._summary_timer.start(60000)

        self._refresh_turnuses()
        self._set_dash_strategy("all", None)

    # ------------------------------------------------------------------

    def on_status_changed(self, name: str, status: str, message: str):
        card = self.cards.get(name)
        if card:
            card.update_status(status, message)

    # ── Frissítés gomb ──────────────────────────────────────────────
    def _style_update_btn(self, available: bool):
        if available:
            self._update_btn.setStyleSheet(
                "QPushButton{background:#FDB900;color:#000000;border:1px solid #FDB900;"
                "padding:0 12px;border-radius:6px;font-weight:600;}"
                "QPushButton:hover{background:#ffc92b;}"
                "QPushButton:disabled{background:#3a3a2a;color:#8d8d6f;}")
        else:
            # Sárga keretes, mint a dashboard menüpontok / stratégia-fülek
            self._update_btn.setStyleSheet(
                "QPushButton{background:transparent;color:#FDB900;border:2px solid #FDB900;"
                "padding:0 12px;border-radius:6px;}"
                "QPushButton:hover{background:rgba(253,185,0,0.15);color:#FDB900;}"
                "QPushButton:disabled{color:#7a6a2a;border-color:#5a4a1a;}")

    def _on_update_btn(self):
        if self._update_info:
            self.update_install_requested.emit()
        else:
            self.check_updates_requested.emit()

    def set_update_checking(self):
        self._update_btn.setEnabled(False)
        self._update_btn.setText("Keresés…")

    def set_update_up_to_date(self):
        self._update_info = None
        self._update_btn.setEnabled(True)
        self._update_btn.setText("Naprakész")
        self._style_update_btn(False)

    def set_update_check_failed(self):
        self._update_info = None
        self._update_btn.setEnabled(True)
        self._update_btn.setText("Frissítés keresése")
        self._style_update_btn(False)

    def set_update_available(self, info: dict):
        self._update_info = info
        self._update_btn.setEnabled(True)
        self._update_btn.setText(f"⬇ Frissítés: {info.get('version', '')}")
        self._style_update_btn(True)

    def set_update_installing(self, text: str = "Telepítés…"):
        self._update_btn.setEnabled(False)
        self._update_btn.setText(text)

    def _refresh_turnuses(self):
        """Block states from the collected results (the original read the scraper's state files)."""
        p = runtime.pipeline()
        session_date = today_battle_day()
        with p.lock:
            status = block_status(p.conn, session_date, _day_minutes(datetime.now().strftime("%H:%M")))
        blocks_8: dict = {}
        failed_8: dict = {}
        done_12: set[int] = set()
        failed_12: set[int] = set()
        twelve = set(TURNUS_SCHEDULE_12)
        for (venue, turnus), state in status.items():
            if venue in ("Anfield", "Etihad") and turnus in twelve:
                if state == "done":
                    done_12.add(turnus)
                elif state == "overdue":
                    failed_12.add(turnus)
            elif state == "done":
                blocks_8.setdefault(str(turnus), []).append(venue)
            elif state == "overdue":
                failed_8.setdefault(str(turnus), []).append(venue)
        self.turnus_bar.update_turnuses(blocks_8, done_12, session_date, failed_8, failed_12)

    @staticmethod
    def _distribute_tab_buttons(buttons: list, row1, row2):
        """A stratégia-tabokat két sorra osztja, a gombok SZÖVEGHOSSZA szerint
        kiegyensúlyozva, a lista sorrendjét megtartva.

        Fix szabállyal (egy sorba mind) sok stratégiánál az első sor túl széles lenne,
        és a bal oldali státusz-oszlopot a minimumára nyomná. A súlyozás önműködő, tehát a
        Stratégiai Labor új tabjaitól sem borul fel újra.
        """
        weights = [len(b.text()) + 4 for b in buttons]     # +4 ≈ a gomb vízszintes paddingje
        half, acc = sum(weights) / 2, 0
        for btn, w in zip(buttons, weights):
            if acc == 0 or acc + w <= half:
                row1.addWidget(btn)
                acc += w
            else:
                row2.addWidget(btn)

    def refresh_tabs(self):
        for row in (self._tab_row1, self._tab_row2):
            while row.count():
                item = row.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
        self._dash_tab_btns.clear()
        self._dash_all_btn = None
        _order: list = []
        for key, label, sources in get_strategy_tabs():
            if key in _DASH_HIDDEN_TABS:
                continue
            text = (label + "  ▾") if key == "all" else label
            btn = QPushButton(text)
            btn.setFixedHeight(26)
            btn.setFont(QFont("Segoe UI", 11))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if key == "all":
                btn.setMenu(self._dash_filter_menu)
                self._dash_all_btn = btn
            else:
                btn.clicked.connect(lambda _, k=key, s=sources: self._set_dash_strategy(k, s))
            self._dash_tab_btns[key] = btn
            _order.append(btn)
        self._distribute_tab_buttons(_order, self._tab_row1, self._tab_row2)
        self._tab_row1.insertStretch(0)
        self._tab_row1.addStretch()
        self._build_dash_filter_menu()
        self._set_dash_strategy("all", None)

    def _set_dash_strategy(self, key: str, sources: list | None):
        self._dash_active_key = key
        self._dash_sources = sources
        _ACTIVE   = ("QPushButton{background:#FDB900;color:#000000;border:2px solid #FDB900;"
                     "padding:0 10px;font-size:12px;font-weight:600;border-radius:6px;}"
                     "QPushButton::menu-indicator{width:0;}")
        _INACTIVE = ("QPushButton{background:transparent;color:#FDB900;border:2px solid #FDB900;"
                     "padding:0 10px;font-size:12px;border-radius:6px;}"
                     "QPushButton:hover{background:rgba(253,185,0,0.15);color:#FDB900;}"
                     "QPushButton::menu-indicator{width:0;}")
        for k, btn in self._dash_tab_btns.items():
            btn.setStyleSheet(_ACTIVE if k == key else _INACTIVE)
        self._refresh_summary()

    # --- "Összes" stratégia-szűrő (legördülő pipákkal) ---
    def _dash_filterable_tabs(self) -> list:
        return [(k, l, s) for k, l, s in get_strategy_tabs()
                if k != "all" and s and k not in _DASH_HIDDEN_TABS]

    def _build_dash_filter_menu(self):
        tabs = self._dash_filterable_tabs()
        valid = {k for k, _, _ in tabs}
        if not self._dash_filter_checked:
            self._dash_filter_checked = set(valid) - SHADOW_TAB_KEYS
        else:
            self._dash_filter_checked |= (valid - getattr(self, "_dash_prev_valid", set()) - SHADOW_TAB_KEYS)
            self._dash_filter_checked &= valid

        self._dash_filter_menu.clear()
        for key, label, _ in tabs:
            act = QAction(label, self._dash_filter_menu)
            act.setCheckable(True)
            act.setChecked(key in self._dash_filter_checked)
            act.triggered.connect(lambda checked, k=key: self._toggle_dash_filter(k, checked))
            self._dash_filter_menu.addAction(act)
        self._dash_filter_menu.addSeparator()
        act_all = QAction("Mindet kijelöl", self._dash_filter_menu)
        act_all.triggered.connect(lambda: self._set_all_dash_filter(True))
        self._dash_filter_menu.addAction(act_all)
        act_none = QAction("Kijelölés törlése", self._dash_filter_menu)
        act_none.triggered.connect(lambda: self._set_all_dash_filter(False))
        self._dash_filter_menu.addAction(act_none)
        self._dash_prev_valid = valid
        self._update_dash_filter_label()

    def _toggle_dash_filter(self, key: str, checked: bool):
        if checked:
            self._dash_filter_checked.add(key)
        else:
            self._dash_filter_checked.discard(key)
        self._update_dash_filter_label()
        if self._dash_active_key == "all":
            self._refresh_summary()

    def _set_all_dash_filter(self, select: bool):
        if select:
            self._dash_filter_checked = {k for k, _, _ in self._dash_filterable_tabs()}
        else:
            self._dash_filter_checked = set()
        for act in self._dash_filter_menu.actions():
            if act.isCheckable():
                act.setChecked(select)
        self._update_dash_filter_label()
        if self._dash_active_key == "all":
            self._refresh_summary()

    def _update_dash_filter_label(self):
        if not self._dash_all_btn:
            return
        total = len(self._dash_filterable_tabs())
        n = len(self._dash_filter_checked)
        if n == total:
            self._dash_all_btn.setText("Összes  ▾")
        elif n == 0:
            self._dash_all_btn.setText("Összes: 0  ▾")
        else:
            self._dash_all_btn.setText(f"Összes: {n}/{total}  ▾")

    def _dash_filter_sources(self) -> list | None:
        tabs = self._dash_filterable_tabs()
        if len(self._dash_filter_checked) == len(tabs):
            return None
        if not self._dash_filter_checked:
            return ["__none__"]
        combined: list = []
        for key, _, sources in tabs:
            if key in self._dash_filter_checked:
                combined.extend(sources)
        return combined

    def _refresh_summary(self):
        # A napi bontas es az osszegzes ugyanabbol az adatbol jon: eddig haromszor
        # olvastuk be es szamoltuk ujra ugyanazt (~3x 0,2 s a GUI-szalon).
        sources = self._dash_filter_sources() if self._dash_active_key == "all" else self._dash_sources
        _all     = get_daily_stats(30, sources)
        summary  = compute_summary(_all)
        last_day = get_last_completed_day_stats(sources)

        _today = date.today()
        _dates = [(_today - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
        _map   = {d["date"]: d for d in _all}
        _empty = {"units": 0.0, "tips_total": 0, "tips_won": 0, "tips_lost": 0, "tips_push": 0, "roi": 0.0}
        daily7 = [dict(_empty, date=dt, **{k: v for k, v in _map.get(dt, {}).items() if k != "date"}) for dt in _dates]

        units = summary["units"]
        roi   = summary["roi"]
        u_col = "#FDB900" if units >= 0 else "#d44a3a"
        r_col = "#FDB900" if roi   >= 0 else "#d44a3a"

        self.mc_units.set_value(f"{units:+.2f}", u_col)
        self.mc_roi.set_value(f"{roi:+.2f}%", r_col)
        self.mc_won.set_value(str(summary["tips_won"]))
        self.mc_total.set_value(str(summary["tips_total"]))

        self._last_day_card.update_stats(last_day)
        self._draw_mini_chart(daily7)

    def _draw_mini_chart(self, daily: list[dict]):
        self._mini_ax.clear()
        self._mini_ax.set_facecolor("#12121f")
        self._mini_fig.set_facecolor("#12121f")

        if not daily:
            self._mini_canvas.draw()
            return

        y      = [d.get("units", 0.0) for d in daily]
        labels = [d["date"][5:] for d in daily]
        x      = list(range(len(y)))
        colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in y]
        cumul  = list(np.cumsum(y))

        for i, (v, c) in enumerate(zip(y, colors)):
            self._mini_ax.bar(i, v, color=c, width=0.62, alpha=0.9, zorder=3)
            self._mini_ax.bar(i, v, color=c, width=0.78, alpha=0.12, zorder=2)

        self._mini_ax.plot(x, cumul, color="#FDB900", linewidth=1.8,
                           linestyle="--", alpha=0.85, zorder=4,
                           marker="o", markersize=3, markerfacecolor="#FDB900")

        self._mini_ax.axhline(0, color="#333344", linewidth=0.8, zorder=1)
        self._mini_ax.set_xticks(x)
        self._mini_ax.set_xticklabels(labels, color="#555566", fontsize=7,
                                       rotation=45, ha="right")
        self._mini_ax.tick_params(axis="y", colors="#555566", labelsize=7)
        self._mini_ax.grid(axis="y", color="#ffffff06", linewidth=0.5)
        for spine in self._mini_ax.spines.values():
            spine.set_visible(False)
        self._mini_ax.set_xlim(-0.6, len(y) - 0.4)

        self._mini_canvas.draw()
        buf = self._mini_canvas.buffer_rgba()
        w, h = self._mini_canvas.get_width_height()
        img = QImage(bytes(buf), w, h, QImage.Format.Format_RGBA8888)
        self.mini_plot.setPixmap(QPixmap.fromImage(img))
