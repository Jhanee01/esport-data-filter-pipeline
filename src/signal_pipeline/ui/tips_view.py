
import re
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QScrollArea, QPushButton, QComboBox,
    QSizePolicy,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from .compat.tips_reader import TipsReader
from .compat.stats_manager import get_strategy_tabs

# ──────────────────────────────────────────────
# Konstansok
# ──────────────────────────────────────────────

BADGE_STYLE = {
    "win":       ("NYERTES",      "#1c3829", "#3ba560"),
    "loss":      ("VESZTES",      "#3a1c1c", "#d44a3a"),
    "push":      ("PUSH",         "#1c2a3a", "#5794f2"),
    "half_win":  ("FÉLIG NY.",    "#1c3829", "#3ba560"),
    "half_loss": ("FÉLIG V.",     "#3a1c1c", "#d44a3a"),
    "unknown":   ("FOLYAMATBAN",  "#3a341c", "#f2cc0c"),
    "PENDING":   ("FOLYAMATBAN",  "#3a341c", "#f2cc0c"),
    "pending":   ("FOLYAMATBAN",  "#3a341c", "#f2cc0c"),
    "filtered":  ("SZŰRT",        "#2a2d3a", "#6e7079"),
    "void":      ("ÉRVÉNYTELEN",  "#2a2d3a", "#6e7079"),
}

# Egy TipCard felépítése ~1,7 ms. Az összes tipp (több ezer) egyszerre
# kirajzolva több másodpercre megfagyasztja a UI-t, ezért lapozunk.
TIPS_PAGE_SIZE = 200
# Automatikus frissiteskor legfeljebb ennyi kartyat epitunk vissza, meg ha a
# felhasznalo tobbet toltott is be — kulonben a 10 mp-es poll visszahozna a fagyast.
# 400 kartya ujraepitese ~1,3 s; 1000-nel mar 6 s volt, ami megint fagyasnak latszik.
TIPS_AUTO_KEEP = 400

THRESHOLD_COLOR = {
    "high":    "#3ba560",
    "mid":     "#f2cc0c",
    "low":     "#6e7079",
    "unknown": "#6e7079",
}

def _strategy_label(tip: dict) -> str:
    """The strategy's name as loaded by the pipeline (Strategy Lab rule or Python plugin)."""
    raw = tip.get("_raw") or {}
    return raw.get("strategy_label") or raw.get("strategy_name") or str(tip.get("source") or "").upper()


def _badge_for(status: str) -> tuple[str, str, str]:
    key = str(status).lower() if str(status).lower() in BADGE_STYLE else "unknown"
    return BADGE_STYLE[key]


def _session_from_tip(tip: dict) -> str:
    raw = tip.get("_raw") or {}
    t = str(raw.get("time") or "")
    m = re.search(r"(\d{1,2}):(\d{2})", t)
    if not m:
        return "day"
    h = int(m.group(1))
    if h < 6 or h >= 21:
        return "night"
    if h >= 15:
        return "afternoon"
    return "day"


# ──────────────────────────────────────────────
# Tipp kártya
# ──────────────────────────────────────────────

class TipCard(QFrame):
    def __init__(self, tip: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        # Sor 1: meccs neve + eredmény badge
        row1 = QHBoxLayout()

        match_lbl = QLabel(tip["match"])
        match_lbl.setFont(QFont("Segoe UI Semibold", 13))
        match_lbl.setStyleSheet("color: #d9d9d9;")

        status = tip["status"]
        badge_txt, badge_bg, badge_fg = _badge_for(status)
        badge = QLabel(badge_txt)
        badge.setFont(QFont("Segoe UI Semibold", 11))
        badge.setStyleSheet(
            f"background-color: {badge_bg}; color: {badge_fg}; "
            f"border: 1px solid {badge_fg}; border-radius: 4px; "
            f"padding: 2px 10px;"
        )
        badge.setFixedHeight(24)

        row1.addWidget(match_lbl)
        row1.addStretch()
        row1.addWidget(badge)
        layout.addLayout(row1)

        # Sor 2: játékosok
        players = tip.get("player") or ""
        if players and players.strip() != "/":
            pl_lbl = QLabel(players)
            pl_lbl.setFont(QFont("Segoe UI", 11))
            pl_lbl.setStyleSheet("color: #8d8d9f;")
            layout.addWidget(pl_lbl)

        # Sor 3: részletek + stratégia badge
        row3 = QHBoxLayout()
        row3.setSpacing(20)

        pct = tip["value_pct"]
        pct_str = f"{pct:.2f}%" if pct is not None else "–"
        thresh_col = THRESHOLD_COLOR.get(tip["threshold"], "#6e7079")

        raw = tip.get("_raw") or {}
        pick = str(tip.get("pick") or "").upper()
        if pick == "OVER":
            odds_val = raw.get("odds_over")
        elif pick == "UNDER":
            odds_val = raw.get("odds_under")
        else:
            odds_val = raw.get("odds_over") or raw.get("odds_under")
        if odds_val is None:
            odds_val = raw.get("odds")
        try:
            odds_str = f"@ {float(odds_val):.2f}" if odds_val is not None else ""
        except (TypeError, ValueError):
            odds_str = ""

        pick_label = raw.get("pick_label")
        if pick_label:                                  # nem-O/U piac (1X2/BTTS/…)
            pick_disp = str(pick_label)
        elif tip.get("line") is not None:               # O/U
            pick_disp = f"{tip['pick']}  {tip['line']}"
        else:
            pick_disp = str(tip.get("pick") or "")

        details = []
        tip_date = tip.get("date") or raw.get("date") or ""
        if tip_date:
            details.append(("📅", str(tip_date)))
        details.append(("⏰", tip["time"]))
        details.append(("🎯", pick_disp))
        if odds_str:
            details.append(("💰", odds_str))
        details.append(("📊", pct_str))

        for icon, val in details:
            chip = QHBoxLayout()
            chip.setSpacing(4)
            icon_lbl = QLabel(icon)
            icon_lbl.setFont(QFont("Segoe UI", 11))
            val_lbl = QLabel(val)
            val_lbl.setFont(QFont("Segoe UI Semibold", 11))
            if icon == "📊":
                val_lbl.setStyleSheet(f"color: {thresh_col};")
            else:
                val_lbl.setStyleSheet("color: #d9d9d9;")
            chip.addWidget(icon_lbl)
            chip.addWidget(val_lbl)
            row3.addLayout(chip)

        row3.addStretch()

        # Stratégia badge
        strat_lbl = QLabel(_strategy_label(tip))
        strat_lbl.setFont(QFont("Segoe UI", 10))
        strat_lbl.setStyleSheet(
            "background-color: #2d2200; color: #FDB900; "
            "border: 1px solid #FDB900; border-radius: 4px; "
            "padding: 1px 8px;"
        )
        strat_lbl.setFixedHeight(22)
        row3.addWidget(strat_lbl)

        layout.addLayout(row3)

        # Szűrés oka
        raw = tip.get("_raw") or {}
        filter_reason = raw.get("filter_reason") or ""
        if filter_reason:
            fr_lbl = QLabel(f"Szűrve: {filter_reason}")
            fr_lbl.setFont(QFont("Segoe UI", 10))
            fr_lbl.setStyleSheet("color: #6e7079;")
            fr_lbl.setWordWrap(True)
            layout.addWidget(fr_lbl)

        # Outcome
        outcome = tip.get("outcome") or ""
        if outcome:
            out_lbl = QLabel(outcome)
            out_lbl.setFont(QFont("Segoe UI", 11))
            out_lbl.setStyleSheet("color: #8d8d9f;")
            layout.addWidget(out_lbl)


# ──────────────────────────────────────────────
# Stratégia tab gomb
# ──────────────────────────────────────────────

TAB_STYLE_ACTIVE = (
    "QPushButton{background:#FDB900;color:#000000;border:2px solid #FDB900;"
    "padding:0 14px;font-size:12px;font-weight:600;border-radius:6px;}"
)
TAB_STYLE_INACTIVE = (
    "QPushButton{background:transparent;color:#FDB900;border:2px solid #FDB900;"
    "padding:0 14px;font-size:12px;border-radius:6px;}"
    "QPushButton:hover{background:rgba(253,185,0,0.15);color:#FDB900;}"
)


class StrategyTabBar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QFrame{background:#212121;border-radius:8px;}")

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 5, 8, 5)
        self._layout.setSpacing(4)

        self._buttons: dict[str, QPushButton] = {}
        self._active_key: str = ""
        self._callbacks: list = []

        for key, label, _ in get_strategy_tabs():
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._select(k))
            self._buttons[key] = btn
            self._layout.addWidget(btn)

        self._layout.addStretch()

    def rebuild(self):
        from .compat.stats_manager import get_strategy_tabs
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._buttons.clear()
        for key, label, _ in get_strategy_tabs():
            btn = QPushButton(label)
            btn.setFixedHeight(28)
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._select(k))
            self._buttons[key] = btn
            self._layout.addWidget(btn)
        self._layout.addStretch()
        active = self._active_key if self._active_key in self._buttons else "all"
        self._select(active)

    def _select(self, key: str):
        self._active_key = key
        for k, btn in self._buttons.items():
            btn.setStyleSheet(TAB_STYLE_ACTIVE if k == key else TAB_STYLE_INACTIVE)
        for cb in self._callbacks:
            cb(key)

    def set_active(self, key: str):
        self._select(key)

    def on_change(self, callback):
        self._callbacks.append(callback)

    def active_key(self) -> str:
        return self._active_key


# ──────────────────────────────────────────────
# Tippek nézet
# ──────────────────────────────────────────────

class TipsView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentView")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        # Fejléc
        hdr = QHBoxLayout()
        title = QLabel("Tippek")
        title.setObjectName("viewTitle")
        title.setFont(QFont("Segoe UI Semibold", 16))

        self.count_lbl = QLabel("0 tipp")
        self.count_lbl.setStyleSheet("color: #8d8d9f; font-size: 12px;")
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(self.count_lbl)
        layout.addLayout(hdr)

        # Stratégia tab sor — vízszintes csúszkával, hogy minden név kiférjen
        self._tab_bar = StrategyTabBar(self)
        self._tab_bar.setStyleSheet("QFrame { background-color: #2a2d3a; border-radius: 6px; }")
        self._tab_bar.on_change(self._on_tab_change)

        tab_scroll = QScrollArea()
        tab_scroll.setWidget(self._tab_bar)
        tab_scroll.setWidgetResizable(True)
        tab_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        tab_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        tab_scroll.setFixedHeight(50)
        tab_scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:horizontal{height:6px;background:#1a1a1a;border-radius:3px;margin:0;}"
            "QScrollBar::handle:horizontal{background:#FDB900;border-radius:3px;min-width:30px;}"
            "QScrollBar::handle:horizontal:hover{background:#ffd54f;}"
            "QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{width:0;}"
            "QScrollBar::add-page:horizontal,QScrollBar::sub-page:horizontal{background:transparent;}"
        )
        layout.addWidget(tab_scroll)

        # Szűrő sor
        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)

        filter_row.addWidget(QLabel("Eredmény:"))
        self.cmb_result = QComboBox()
        self.cmb_result.addItems(["Mind", "Folyamatban", "Nyertes", "Vesztes", "Push", "Szűrt"])
        self.cmb_result.setFixedHeight(30)
        self.cmb_result.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.cmb_result)

        filter_row.addWidget(QLabel("Napszak:"))
        self.cmb_session = QComboBox()
        self.cmb_session.addItems(["Mind", "Day", "Afternoon", "Night"])
        self.cmb_session.setFixedHeight(30)
        self.cmb_session.currentIndexChanged.connect(self._apply_filter)
        filter_row.addWidget(self.cmb_session)

        filter_row.addStretch()
        layout.addLayout(filter_row)

        # Scroll terület
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self._cards_widget = QWidget()
        self._cards_widget.setStyleSheet("background: transparent;")
        self._cards_layout = QVBoxLayout(self._cards_widget)
        self._cards_layout.setContentsMargins(0, 0, 8, 0)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()

        scroll.setWidget(self._cards_widget)
        layout.addWidget(scroll)

        self._placeholder = QLabel("Még nincsenek tippek.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #6e7079; font-size: 13px;")
        self._cards_layout.insertWidget(0, self._placeholder)

        # „Továbbiak betöltése" — lapozó gomb a kártyák alatt
        self._more_btn = QPushButton()
        self._more_btn.setFixedHeight(34)
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setStyleSheet(
            "QPushButton{background:transparent;color:#FDB900;border:2px solid #FDB900;"
            "border-radius:6px;font-weight:600;}"
            "QPushButton:hover{background:rgba(253,185,0,0.15);}"
        )
        self._more_btn.clicked.connect(self._load_more)
        self._more_btn.setVisible(False)
        self._cards_layout.insertWidget(self._cards_layout.count() - 1, self._more_btn)

        # Állapot
        self._active_tab_key = "all"
        self._all_tips: list[dict] = []
        self._filtered: list[dict] = []   # az aktuális szűrés teljes találata
        self._cards: list[QWidget] = []   # a ténylegesen kirajzolt kártyák
        self._dirty = False               # rejtett nézetben nem rajzolunk

        # TipsReader
        self._reader = TipsReader(self)
        self._reader.tips_updated.connect(self._on_tips_updated)

        # Alapértelmezett tab
        self._tab_bar.set_active("all")

    # ------------------------------------------------------------------

    def refresh_tabs(self):
        self._tab_bar.rebuild()

    def _on_tab_change(self, key: str):
        self._active_tab_key = key
        self._clear_cards()   # uj tab: elolrol lapozunk
        self._apply_filter()

    def _on_tips_updated(self, tips: list):
        # A `void` (a statisztikából kizárt, érvénytelenített) tippek itt sem jelennek meg,
        # ahogy a statisztikában sem (core/tip_history.py). Enélkül a _badge_for() az
        # ismeretlen státuszt "FOLYAMATBAN"-nak rajzolta, azaz a kizárt tipp beragadtnak látszott.
        self._all_tips = [t for t in tips if str(t.get("status") or "").lower() != "void"]
        self._apply_filter()

    def showEvent(self, event):
        """Rejtett nézetben csak jelöljük, hogy változott — itt rajzoljuk ki."""
        super().showEvent(event)
        if self._dirty:
            self._apply_filter()

    def _apply_filter(self):
        # Rejtett nézetbe nem rajzolunk — a következő showEvent pótolja
        if not self.isVisible():
            self._dirty = True
            return
        self._dirty = False

        result_idx  = self.cmb_result.currentIndex()
        session_idx = self.cmb_session.currentIndex()

        result_map = {
            0: None,
            1: ["unknown", "pending", "PENDING"],
            2: ["win", "half_win"],
            3: ["loss", "half_loss"],
            4: ["push"],
            5: ["filtered"],
        }
        session_map = {0: None, 1: "day", 2: "afternoon", 3: "night"}

        # Aktív tab alapján source szűrő
        src_filter = None
        for key, _, sources in get_strategy_tabs():
            if key == self._active_tab_key:
                src_filter = sources
                break

        r_filter = result_map.get(result_idx)
        s_filter = session_map.get(session_idx)

        # Tippek nézetben soha nem jelennek meg a szűrt (filtered) tippek
        filtered = [t for t in self._all_tips if t["status"].lower() != "filtered"]
        if src_filter:
            filtered = [t for t in filtered if t["source"].lower() in src_filter]
        if r_filter:
            filtered = [t for t in filtered if t["status"].lower() in [x.lower() for x in r_filter]]
        if s_filter:
            filtered = [t for t in filtered if _session_from_tip(t) == s_filter]

        self._render(filtered)

    def _render(self, tips: list):
        """Az aktuális szűrés teljes találata. Kártyát csak az első lapnyiról
        építünk — 5000 TipCard felépítése 8+ másodpercre megfagyasztaná a UI-t."""
        keep = min(len(self._cards), TIPS_AUTO_KEEP) or TIPS_PAGE_SIZE
        self._filtered = tips
        self._clear_cards()
        self._placeholder.setVisible(len(tips) == 0)
        while len(self._cards) < keep and len(self._cards) < len(tips):
            self._append_page()
        if not self._cards:
            self._append_page()   # ures lista: a gomb allapotat is beallitja
        self._update_counters(tips)

    def _clear_cards(self):
        for card in self._cards:
            self._cards_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards = []

    def _append_page(self):
        """A következő lapnyi kártya beszúrása a „Továbbiak" gomb elé."""
        start = len(self._cards)
        chunk = self._filtered[start:start + TIPS_PAGE_SIZE]
        insert_at = self._cards_layout.indexOf(self._more_btn)
        for offset, tip in enumerate(chunk):
            card = TipCard(tip)
            self._cards_layout.insertWidget(insert_at + offset, card)
            self._cards.append(card)

        remaining = len(self._filtered) - len(self._cards)
        self._more_btn.setVisible(remaining > 0)
        if remaining > 0:
            step = min(TIPS_PAGE_SIZE, remaining)
            self._more_btn.setText(f"Továbbiak betöltése  ({step} / még {remaining})")

    def _load_more(self):
        self._append_page()

    def _update_counters(self, tips: list):
        # Számlálók az aktív tabon belüli tippekre
        visible = len(tips)
        won  = sum(1 for t in tips if t["status"].lower() in ("win", "half_win"))
        lost = sum(1 for t in tips if t["status"].lower() in ("loss", "half_loss"))
        pend = sum(1 for t in tips if t["status"].lower() in ("unknown", "pending"))
        total_all = len(self._all_tips)

        # Egység P&L: nyert = +(odds-1), vesztett = -1, push = 0
        pl = 0.0
        for t in tips:
            raw = t.get("_raw") or {}
            pick = str(t.get("pick") or "").upper()
            if pick == "OVER":
                o = raw.get("odds_over")
            elif pick == "UNDER":
                o = raw.get("odds_under")
            else:
                o = raw.get("odds_over") or raw.get("odds_under")
            if o is None:
                o = raw.get("odds")
            try:
                odds = float(o) if o is not None else 2.0
            except (TypeError, ValueError):
                odds = 2.0
            st = t["status"].lower()
            if st == "win":
                pl += odds - 1
            elif st == "half_win":
                pl += (odds - 1) / 2
            elif st == "loss":
                pl -= 1
            elif st == "half_loss":
                pl -= 0.5

        pl_str = f"{pl:+.2f} e."
        self.count_lbl.setText(
            f"{visible} / {total_all} tipp  |  +{won} nyert  -{lost} vesztett  {pend} folyamatban  |  P&L: {pl_str}"
        )
