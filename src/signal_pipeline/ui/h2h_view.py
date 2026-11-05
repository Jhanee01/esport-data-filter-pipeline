import html

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFrame, QPushButton, QScrollArea,
    QSizePolicy, QComboBox,
)
from PySide6.QtCore import Qt, QStringListModel, QTimer
from PySide6.QtGui import QFont

from .compat.config import MATCH_RESULTS_CSV, MATCH_RESULTS_12_CSV
from .compat.h2h_names import load_index, load_teams
from .compat.h2h_reader import get_player_h2h_stats, get_h2h_teams, _OVER_LINES, _LAST_NS
from .compat.tip_history import matchup_tip_history


# A csapat-szűrő kikapcsolt állapota (a legördülők első eleme)
_TEAM_ANY = "Csapat: mind"

_COMBO_QSS = (
    "QComboBox{background:#1e2130;color:#ffffff;border:1px solid #3a3d4a;"
    "border-radius:5px;padding:0 10px 0 10px;font-size:13px;}"
    "QComboBox:focus{border:1px solid #FDB900;}"
    "QComboBox::drop-down{border:none;width:26px;}"
    "QComboBox::down-arrow{border-left:5px solid transparent;"
    "border-right:5px solid transparent;border-top:6px solid #8d8d9f;"
    "width:0;height:0;margin-right:8px;}"
    "QComboBox QAbstractItemView{background:#1e2130;color:#ffffff;"
    "selection-background-color:#FDB900;selection-color:#000000;"
    "border:1px solid #3a3d4a;outline:none;}"
)


def _lbl(text: str, size: int = 12, bold: bool = False,
         color: str = "#ffffff") -> QLabel:
    l = QLabel(text)
    f = QFont("Segoe UI", size)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    l.setFont(f)
    l.setStyleSheet(f"color: {color};")
    return l


def _with_team(name: str, team: str | None) -> str:
    """Játékosnév + a meccsen használt csapat halványan (rich text)."""
    if not team:
        return html.escape(name)
    return (f"{html.escape(name)} "
            f"<span style='color:#8d8d9f;'>({html.escape(team)})</span>")


def _sep() -> QFrame:
    # Sima 1px vonal (nem HLine — az 3D-s, vésett kékes hatást ad sötét témán).
    # A kártyakeret #3a3a3a, de az a sötét app-háttéren ül; a belső vonalak a
    # világosabb kártya-gradiensen vannak, ezért egy árnyalattal világosabb
    # szürkével (#4a4a4a) néznek ki ugyanolyan súllyal, mint a keret.
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet("background:#4a4a4a; border:none;")
    return line


# ──────────────────────────────────────────────
# Eredménypanel
# ──────────────────────────────────────────────

class H2HResultPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(24, 18, 24, 18)
        self._root.setSpacing(14)

    def clear(self):
        while self._root.count():
            item = self._root.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                # Beágyazott layoutok (pl. wdl_box / egyéni-gólátlag oszlopok)
                # gyerek-widgetjeit is törölni kell, különben árván maradnak,
                # a panel gyerekei maradnak, és a régi geometriájukon láthatóak
                # → a következő keresésnél egymásra csúszó, olvashatatlan szöveg.
                self._clear_layout(item.layout())

    def show_stats(self, data: dict, tip_hist: dict | None = None):
        self.clear()
        p1, p2 = data["p1"], data["p2"]
        ov = data["overall"]
        n  = ov["n"]

        # ── Fejléc ───────────────────────────────
        # az aktív csapat-szűrő (ha van) a nevek mellett látszik
        t1, t2 = data.get("team1") or "", data.get("team2") or ""
        title = (f"{p1}{f'  ({t1})' if t1 else ''}"
                 f"  vs  {p2}{f'  ({t2})' if t2 else ''}")
        hdr = QHBoxLayout()
        hdr.addWidget(_lbl(title, size=15, bold=True))
        hdr.addStretch()
        hdr.addWidget(_lbl(f"{n} meccs", size=12, color="#ffffff"))
        self._root.addLayout(hdr)
        self._root.addWidget(_sep())

        # ── Egymás elleni mérleg ─────────────────
        self._root.addWidget(_lbl("EGYMÁS ELLENI MÉRLEG", size=11, bold=True, color="#FDB900"))
        wdl = QHBoxLayout()
        wdl.setSpacing(0)

        def wdl_box(label: str, val: int, color: str):
            box = QVBoxLayout()
            box.setSpacing(2)
            v = QLabel(str(val))
            v.setFont(QFont("Segoe UI Semibold", 22))
            v.setStyleSheet(f"color: {color};")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl = QLabel(label)
            lbl.setFont(QFont("Segoe UI", 10))
            lbl.setStyleSheet("color: #ffffff;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pct = QLabel(f"{val/n*100:.1f}%" if n else "–")
            pct.setFont(QFont("Segoe UI", 10))
            pct.setStyleSheet(f"color: {color};")
            pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(v)
            box.addWidget(lbl)
            box.addWidget(pct)
            return box

        wdl.addLayout(wdl_box(f"{p1} győzelem", ov["w1"], "#3ba560"))
        wdl.addStretch()
        wdl.addLayout(wdl_box("Döntetlen", ov["d"], "#ffffff"))
        wdl.addStretch()
        wdl.addLayout(wdl_box(f"{p2} győzelem", ov["w2"], "#d44a3a"))
        self._root.addLayout(wdl)
        self._root.addWidget(_sep())

        # ── Gólátlag — Last N ────────────────────
        self._root.addWidget(_lbl("GÓLÁTLAG — LAST N MECCS", size=11, bold=True, color="#FDB900"))
        self._root.addWidget(self._make_avg_table(data))
        self._root.addWidget(_sep())

        # ── Over % ───────────────────────────────
        self._root.addWidget(_lbl("OVER %", size=11, bold=True, color="#FDB900"))
        self._root.addWidget(self._make_over_table(data))
        self._root.addWidget(_sep())

        # ── Egyéni gólátlag ──────────────────────
        self._root.addWidget(_lbl("EGYÉNI GÓLÁTLAG (H2H meccseken)", size=11, bold=True, color="#FDB900"))
        row = QHBoxLayout()
        row.setSpacing(40)
        for name, avg_key in ((p1, "p1_avg"), (p2, "p2_avg")):
            col = QVBoxLayout()
            col.setSpacing(2)
            v = QLabel(f"{ov[avg_key]:.2f}")
            v.setFont(QFont("Segoe UI Semibold", 20))
            v.setStyleSheet("color: #FDB900;")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            nl = QLabel(name)
            nl.setFont(QFont("Segoe UI", 11))
            nl.setStyleSheet("color: #ffffff;")
            nl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sl = QLabel("gól/meccs")
            sl.setFont(QFont("Segoe UI", 10))
            sl.setStyleSheet("color: #ffffff;")
            sl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(v); col.addWidget(nl); col.addWidget(sl)
            row.addLayout(col)
        row.addStretch()
        self._root.addLayout(row)
        self._root.addWidget(_sep())

        # ── BTTS & betalálás (All-time / Utolsó 20 / 50) ──
        self._root.addWidget(_lbl("BTTS & BETALÁLÁS", size=11, bold=True, color="#FDB900"))
        self._root.addWidget(self._make_btts_table(data))

        # ── Utolsó 10 egymás elleni meccs ────────
        self._root.addWidget(_sep())
        self._root.addWidget(_lbl("UTOLSÓ 10 EGYMÁS ELLENI MECCS", size=11, bold=True, color="#FDB900"))
        self._root.addWidget(self._make_recent_table(data))

        # ── Múltbeli fogadások erre a párosításra ──
        if tip_hist is not None:
            self._root.addWidget(_sep())
            self._root.addWidget(_lbl("MÚLTBELI FOGADÁSOK ERRE A PÁROSÍTÁSRA",
                                      size=11, bold=True, color="#FDB900"))
            self._root.addWidget(self._make_tips_table(tip_hist))

    def _make_avg_table(self, data: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        grid = QVBoxLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        ov = data["overall"]
        last_n = data["last_n"]

        cols = _LAST_NS + ["Összes"]
        header = QHBoxLayout()
        header.addWidget(_lbl("", size=11, color="#ffffff"))
        header.addStretch()
        for c in cols:
            lbl = _lbl(f"L{c}" if isinstance(c, int) else c, size=10, color="#ffffff")
            lbl.setFixedWidth(58)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            header.addWidget(lbl)
        grid.addLayout(header)

        avg_row = QHBoxLayout()
        avg_row.addWidget(_lbl("Gólátlag", size=12))
        avg_row.addStretch()
        for c in cols:
            val = last_n[c]["avg"] if isinstance(c, int) else ov["avg"]
            n   = last_n[c]["n"]   if isinstance(c, int) else ov["n"]
            txt = f"{val:.2f}" if n > 0 else "–"
            col = "#FDB900" if n > 0 else "#555"
            v = _lbl(txt, size=12, bold=True, color=col)
            v.setFixedWidth(58)
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            avg_row.addWidget(v)
        grid.addLayout(avg_row)

        n_row = QHBoxLayout()
        n_row.addWidget(_lbl("Meccsszám", size=11, color="#ffffff"))
        n_row.addStretch()
        for c in cols:
            cnt = last_n[c]["n"] if isinstance(c, int) else ov["n"]
            v = _lbl(str(cnt), size=11, color="#ffffff")
            v.setFixedWidth(58)
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            n_row.addWidget(v)
        grid.addLayout(n_row)

        return w

    def _make_over_table(self, data: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        grid = QVBoxLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        header = QHBoxLayout()
        header.addWidget(_lbl("", size=11, color="#ffffff"))
        header.addStretch()
        for line in _OVER_LINES:
            lbl = _lbl(f"O{line}", size=10, color="#ffffff")
            lbl.setFixedWidth(54)
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            header.addWidget(lbl)
        grid.addLayout(header)

        pct_row = QHBoxLayout()
        pct_row.addWidget(_lbl("%", size=12))
        pct_row.addStretch()
        for line in _OVER_LINES:
            pct = data["over"][line]
            col = "#3ba560" if pct >= 70 else "#FDB900" if pct >= 45 else "#d44a3a"
            v = _lbl(f"{pct:.0f}%", size=12, bold=True, color=col)
            v.setFixedWidth(54)
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            pct_row.addWidget(v)
        grid.addLayout(pct_row)

        return w

    def _make_recent_table(self, data: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        grid = QVBoxLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        recent = data.get("recent") or []
        p1, p2 = data["p1"], data["p2"]
        if not recent:
            grid.addWidget(_lbl("Nincs adat.", size=12, color="#555"))
            return w

        # GY–D–V összesítő a listázott meccsekből (g1/g2 mindig p1 nézőpontjából)
        gy1 = sum(1 for m in recent if m["g1"] > m["g2"])
        dd  = sum(1 for m in recent if m["g1"] == m["g2"])
        gy2 = sum(1 for m in recent if m["g1"] < m["g2"])

        def _wdl_summary(name: str, gy: int, d: int, v: int) -> QLabel:
            l = QLabel(
                f"{name}:&nbsp;&nbsp;"
                f"<span style='color:#3ba560;'>{gy} GY</span> · "
                f"<span style='color:#ffffff;'>{d} D</span> · "
                f"<span style='color:#d44a3a;'>{v} V</span>"
            )
            l.setTextFormat(Qt.TextFormat.RichText)
            l.setFont(QFont("Segoe UI Semibold", 11))
            l.setStyleSheet("color: #ffffff;")
            return l

        sums = QHBoxLayout()
        sums.setSpacing(40)
        sums.addWidget(_wdl_summary(p1, gy1, dd, gy2))
        sums.addWidget(_wdl_summary(p2, gy2, dd, gy1))
        sums.addStretch()

        # jobbra: utolsó 20 meccs mérlege (a lista marad 10 darabos)
        ln20 = data["last_n"][20]
        if ln20["n"] > len(recent):
            t20 = _lbl(f"UTOLSÓ {ln20['n']}:", size=10, bold=True, color="#8d8d9f")
            sums.addWidget(t20)
            sums.addWidget(_wdl_summary(p1, ln20["w1"], ln20["d"], ln20["w2"]))
            sums.addWidget(_wdl_summary(p2, ln20["w2"], ln20["d"], ln20["w1"]))
        grid.addLayout(sums)

        session_colors = {"day": "#6ec532", "afternoon": "#FDB900", "night": "#4ab8c4"}
        for m in recent:
            r = QHBoxLayout()
            dt = _lbl(f"{m['date']}  {m['time']}", size=11, color="#8d8d9f")
            dt.setFixedWidth(150)
            r.addWidget(dt)
            sess = m.get("session", "")
            sl = _lbl(sess, size=10, color=session_colors.get(sess, "#6e7079"))
            sl.setFixedWidth(76)
            r.addWidget(sl)
            r.addStretch()

            n1 = _lbl(_with_team(p1, m.get("t1")), size=12)
            n1.setTextFormat(Qt.TextFormat.RichText)
            n1.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            sc = _lbl(f"{m['g1']} – {m['g2']}", size=12, bold=True, color="#FDB900")
            sc.setFixedWidth(56)
            sc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            n2 = _lbl(_with_team(p2, m.get("t2")), size=12)
            n2.setTextFormat(Qt.TextFormat.RichText)
            r.addWidget(n1)
            r.addWidget(sc)
            r.addWidget(n2)
            r.addStretch()

            # eredmény-jelző p1 nézőpontjából
            if m["g1"] > m["g2"]:
                res, col = "GY", "#3ba560"
            elif m["g1"] == m["g2"]:
                res, col = "D", "#ffffff"
            else:
                res, col = "V", "#d44a3a"
            b = _lbl(res, size=11, bold=True, color=col)
            b.setFixedWidth(28)
            b.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            r.addWidget(b)
            grid.addLayout(r)

        return w

    def _make_tips_table(self, hist: dict) -> QWidget:
        """A botok által erre a párosításra kiadott tippek (core/tip_history)."""
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        grid = QVBoxLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        pair = hist["pair"]
        if not pair["n"]:
            grid.addWidget(_lbl("Erre a párosításra még nem volt fogadás.",
                                size=12, color="#555"))
            return w

        def _roi_col(roi: float, settled: int) -> str:
            if not settled:
                return "#8d8d9f"
            return "#3ba560" if roi > 0 else ("#d44a3a" if roi < 0 else "#ffffff")

        def _summary(label: str, n: int, st: dict, bold: bool) -> QHBoxLayout:
            r = QHBoxLayout()
            r.addWidget(_lbl(label, size=12, bold=bold))
            r.addStretch()
            parts = f"{n} tipp · {st['won']} GY · {st['lost']} V"
            if st["push"]:
                parts += f" · {st['push']} P"
            if st["pending"]:
                parts += f" · {st['pending']} folyamatban"
            r.addWidget(_lbl(parts, size=11, color="#8d8d9f"))
            roi = _lbl(f"ROI {st['roi']:+.1f}%  ({st['units']:+.2f} u)" if st["settled"] else "–",
                       size=12, bold=True, color=_roi_col(st["roi"], st["settled"]))
            roi.setFixedWidth(190)
            roi.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            r.addWidget(roi)
            return r

        grid.addLayout(_summary("Összesen", pair["n"], pair["total"], True))
        for row in pair["strategies"]:
            grid.addLayout(_summary(row["label"], row["n"], row, False))
        grid.addWidget(_sep())

        status_style = {
            "win":       ("GY",  "#3ba560"),
            "half_win":  ("½GY", "#3ba560"),
            "loss":      ("V",   "#d44a3a"),
            "half_loss": ("½V",  "#d44a3a"),
            "push":      ("P",   "#ffffff"),
        }
        for t in pair["tips"]:
            r = QHBoxLayout()
            dt = _lbl(f"{t['date']}  {t['time']}", size=11, color="#8d8d9f")
            dt.setFixedWidth(150)
            r.addWidget(dt)
            st = _lbl(t["strategy"], size=10, color="#8d8d9f")
            st.setFixedWidth(190)
            r.addWidget(st)

            m = _lbl(f"{_with_team(t['home_player'], t['home_team'])}"
                     f"  <span style='color:#8d8d9f;'>vs</span>  "
                     f"{_with_team(t['away_player'], t['away_team'])}", size=12)
            m.setTextFormat(Qt.TextFormat.RichText)
            r.addWidget(m)
            r.addStretch()

            pk = _lbl(t["pick"], size=12, bold=True, color="#FDB900")
            pk.setFixedWidth(130)
            pk.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            r.addWidget(pk)
            od = _lbl(f"@ {t['odds']:.2f}", size=11, color="#ffffff")
            od.setFixedWidth(60)
            od.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            r.addWidget(od)
            sc = _lbl(t["score"], size=11, color="#8d8d9f")
            sc.setFixedWidth(44)
            sc.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            r.addWidget(sc)

            res, col = status_style.get(t["status"].lower(), ("…", "#8d8d9f"))
            b = _lbl(res, size=11, bold=True, color=col)
            b.setFixedWidth(36)
            b.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            r.addWidget(b)
            grid.addLayout(r)

        return w

    def _make_btts_table(self, data: dict) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        grid = QVBoxLayout(w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)

        ov = data["overall"]
        ln = data["last_n"]
        cols = [("All-time", ov), ("Utolsó 20", ln[20]), ("Utolsó 50", ln[50])]

        header = QHBoxLayout()
        header.addWidget(_lbl("", size=11, color="#ffffff"))
        header.addStretch()
        for label, _stats in cols:
            l = _lbl(label, size=10, color="#ffffff")
            l.setFixedWidth(92)
            l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            header.addWidget(l)
        grid.addLayout(header)

        rows = [
            ("BTTS (mindkét csapat)", "btts"),
            (f"{data['p1']} betalál",  "p1_score"),
            (f"{data['p2']} betalál",  "p2_score"),
        ]
        for row_label, key in rows:
            r = QHBoxLayout()
            r.addWidget(_lbl(row_label, size=12))
            r.addStretch()
            for _label, stats in cols:
                n = stats["n"]
                pct = stats[key]
                txt = f"{pct:.1f}%" if n > 0 else "–"
                if not n:
                    col = "#555"
                elif pct >= 70:
                    col = "#3ba560"
                elif pct >= 45:
                    col = "#FDB900"
                else:
                    col = "#d44a3a"
                v = _lbl(txt, size=12, bold=True, color=col)
                v.setFixedWidth(92)
                v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                r.addWidget(v)
            grid.addLayout(r)

        return w


# ──────────────────────────────────────────────
# H2H Kereső nézet
# ──────────────────────────────────────────────

class H2HView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("contentView")
        self._player_names: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(12)

        root.addWidget(_lbl("H2H Kereső", size=16, bold=True))

        # ── Kereső sor ───────────────────────────
        search_card = QFrame()
        search_card.setObjectName("card")
        sc = QHBoxLayout(search_card)
        sc.setContentsMargins(20, 14, 20, 14)
        sc.setSpacing(14)

        self._cmb_league = QComboBox()
        self._cmb_league.addItems(["8 perc", "12 perc"])
        self._cmb_league.setFixedHeight(36)
        self._cmb_league.setFixedWidth(90)
        self._cmb_league.currentIndexChanged.connect(self._on_league_changed)
        sc.addWidget(self._cmb_league)

        self._p1_input = self._make_player_combo("Játékos 1...")
        sc.addWidget(self._p1_input, 1)

        # Csapat-szűrő — OPCIONÁLIS: üresen hagyva minden meccs beleszámít
        self._t1_input = self._make_team_combo()
        sc.addWidget(self._t1_input)

        vs = _lbl("VS", size=13, bold=True, color="#FDB900")
        vs.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sc.addWidget(vs)

        self._p2_input = self._make_player_combo("Játékos 2...")
        sc.addWidget(self._p2_input, 1)

        self._t2_input = self._make_team_combo()
        sc.addWidget(self._t2_input)

        self._cmb_session = QComboBox()
        self._cmb_session.addItems(["Mind", "Day", "Afternoon", "Night"])
        self._cmb_session.setFixedHeight(36)
        self._cmb_session.setFixedWidth(110)
        sc.addWidget(self._cmb_session)

        btn = QPushButton("Keresés")
        btn.setFixedHeight(36)
        btn.setFixedWidth(90)
        btn.setFont(QFont("Segoe UI Semibold", 12))
        btn.setStyleSheet(
            "QPushButton{background:#FDB900;color:#1a1a1a;border:none;"
            "border-radius:5px;}"
            "QPushButton:hover{background:#ffc929;}"
        )
        btn.clicked.connect(self._do_search)
        sc.addWidget(btn)


        self._p1_input.lineEdit().returnPressed.connect(self._do_search)
        self._p2_input.lineEdit().returnPressed.connect(self._do_search)
        # kézzel begépelt névnél nincs index-váltás → a csapatlistát így frissítjük
        self._p1_input.lineEdit().editingFinished.connect(self._refresh_team_lists)
        self._p2_input.lineEdit().editingFinished.connect(self._refresh_team_lists)
        root.addWidget(search_card)

        # utolsó lekérdezés állapota
        self._last_query: tuple[str, str, str | None, str | None, str | None] | None = None
        self._opponents: dict[str, list[str]] = {}
        self._teams: dict[str, list[str]] = {}

        # Player 1 kiválasztásakor a Player 2 lista az igazi ellenfelekre szűkül
        self._p1_input.currentIndexChanged.connect(self._update_opponents)
        # …és a csapat-legördülők a párosításhoz igazodnak
        self._p1_input.currentIndexChanged.connect(self._refresh_team_lists)
        self._p2_input.currentIndexChanged.connect(self._refresh_team_lists)

        # ── Státusz sor ──────────────────────────
        self._status_lbl = _lbl("Írd be mindkét játékos nevét.", size=12, color="#6e7079")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._status_lbl)

        # ── Scroll terület ───────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")

        self._scroll_inner = QWidget()
        self._scroll_inner.setStyleSheet("background:transparent;")
        self._scroll_layout = QVBoxLayout(self._scroll_inner)
        self._scroll_layout.setContentsMargins(0, 0, 8, 0)
        self._scroll_layout.setSpacing(10)

        self._result_panel = H2HResultPanel()
        self._result_panel.setVisible(False)
        self._scroll_layout.addWidget(self._result_panel)


        self._scroll_layout.addStretch()

        scroll.setWidget(self._scroll_inner)
        root.addWidget(scroll, 1)

        # Autocomplete betöltése késleltetve
        QTimer.singleShot(500, self._load_autocomplete)

    def _make_player_combo(self, placeholder: str) -> QComboBox:
        cmb = QComboBox()
        cmb.setEditable(True)
        cmb.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        cmb.setFixedHeight(36)
        cmb.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        cmb.lineEdit().setPlaceholderText(placeholder)
        cmb.setStyleSheet(_COMBO_QSS)
        return cmb

    def _make_team_combo(self) -> QComboBox:
        """Opcionális csapat-szűrő: az első elem („mind") mellett a kiválasztott
        játékos csapatai. Üresen hagyva a keresés minden meccset számol."""
        cmb = QComboBox()
        cmb.setFixedHeight(36)
        cmb.setFixedWidth(160)
        cmb.addItem(_TEAM_ANY)
        cmb.setStyleSheet(_COMBO_QSS)
        return cmb

    def _team_of(self, cmb: QComboBox) -> str | None:
        """A kiválasztott csapat, vagy None ha a szűrő ki van kapcsolva."""
        return None if cmb.currentIndex() <= 0 else cmb.currentText().strip() or None

    def _refresh_team_lists(self):
        """
        Csapat-legördülők feltöltése. Ha mindkét játékos ki van választva, csak
        az EGYMÁS ELLENI meccseiken használt csapatok jelennek meg (így nincs
        üres találatot adó választás); egyébként a játékos összes csapata.
        """
        p1 = self._p1_input.currentText().strip()
        p2 = self._p2_input.currentText().strip()
        if p1 and p2:
            l1, l2 = get_h2h_teams(p1, p2, self._csv_path())
        else:
            l1 = self._teams.get(p1.lower(), []) if p1 else []
            l2 = self._teams.get(p2.lower(), []) if p2 else []
        self._fill_teams(self._t1_input, l1)
        self._fill_teams(self._t2_input, l2)

    def _fill_teams(self, cmb: QComboBox, teams: list[str]):
        """Lista betöltése; a korábbi választást megtartjuk, ha még érvényes."""
        cur = cmb.currentText() if cmb.currentIndex() > 0 else ""
        cmb.blockSignals(True)
        cmb.clear()
        cmb.addItem(_TEAM_ANY)
        cmb.addItems(teams)
        idx = cmb.findText(cur) if cur else -1
        cmb.setCurrentIndex(idx if idx > 0 else 0)
        cmb.blockSignals(False)

    def _league_key(self) -> str:
        return "12" if self._cmb_league.currentIndex() == 1 else "8"

    def _csv_path(self):
        return MATCH_RESULTS_12_CSV if self._league_key() == "12" else MATCH_RESULTS_CSV

    def _on_league_changed(self):
        # Liga váltáskor új névlista + a korábbi találat elavul
        self._load_autocomplete()
        self._result_panel.setVisible(False)
        self._last_query = None
        self._status_lbl.setText("Írd be mindkét játékos nevét.")

    def _load_autocomplete(self):
        # Nevek + ellenfél-térkép a ténylegesen lejátszott párosításokból
        names, opponents = load_index(self._league_key())
        self._player_names = names
        self._opponents = opponents
        # csapat-térkép kisbetűs kulccsal (a legördülőből jövő név így is talál)
        self._teams = {k.lower(): v for k, v in load_teams(self._league_key()).items()}
        for cmb in (self._t1_input, self._t2_input):
            cmb.blockSignals(True)
            cmb.clear()
            cmb.addItem(_TEAM_ANY)
            cmb.blockSignals(False)
        model = QStringListModel([""] + names)
        for cmb in (self._p1_input, self._p2_input):
            cmb.blockSignals(True)
            cmb.clear()
            cmb.addItem("")
            cmb.addItems(names)
            cmb.setCurrentIndex(0)
            cmb.blockSignals(False)
            from PySide6.QtWidgets import QCompleter
            comp = QCompleter(model, cmb)
            comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
            comp.setFilterMode(Qt.MatchFlag.MatchContains)
            comp.setMaxVisibleItems(12)
            cmb.setCompleter(comp)

    def _update_opponents(self):
        """Player 1 kiválasztása után a Player 2 lista az ő ellenfeleire szűkül."""
        p1 = self._p1_input.currentText().strip()
        opps = self._opponents.get(p1)
        cur = self._p2_input.currentText()
        self._p2_input.blockSignals(True)
        self._p2_input.clear()
        self._p2_input.addItem("")
        self._p2_input.addItems(opps if opps else self._player_names)
        idx = self._p2_input.findText(cur)        # tartsuk meg, ha továbbra is érvényes
        self._p2_input.setCurrentIndex(idx if idx > 0 else 0)
        self._p2_input.blockSignals(False)
        # a Player 2 completer-jét is szűkítsük az aktuális listára
        from PySide6.QtWidgets import QCompleter
        model = QStringListModel([""] + (opps if opps else self._player_names))
        comp = QCompleter(model, self._p2_input)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setMaxVisibleItems(12)
        self._p2_input.setCompleter(comp)

    def _do_search(self):
        p1 = self._p1_input.currentText().strip()
        p2 = self._p2_input.currentText().strip()

        if not p1 or not p2:
            self._status_lbl.setText("Írd be mindkét játékos nevét.")
            self._result_panel.setVisible(False)
            return

        sess_map = {0: None, 1: "day", 2: "afternoon", 3: "night"}
        session = sess_map.get(self._cmb_session.currentIndex())
        t1 = self._team_of(self._t1_input)
        t2 = self._team_of(self._t2_input)

        self._status_lbl.setText("Keresés…")
        data = get_player_h2h_stats(p1, p2, session, self._csv_path(),
                                    team1=t1, team2=t2)

        filt = ""
        if t1 or t2:
            filt = "  (" + " / ".join(
                f"{p} – {t}" for p, t in ((p1, t1), (p2, t2)) if t
            ) + ")"

        if data is None:
            self._status_lbl.setText(
                f"Nincs egymás elleni meccs: {p1}  vs  {p2}{filt}"
            )
            self._result_panel.setVisible(False)
            self._last_query = None
            return

        self._status_lbl.setText(
            f"{data['overall']['n']} egymás elleni meccs találva{filt}"
        )
        self._last_query = (data["p1"], data["p2"], session, t1, t2)
        # a párosításra kiadott tippek — ugyanazokkal a szűrőkkel (session, csapat)
        try:
            tip_hist = matchup_tip_history(data["p1"], data["p2"], self._league_key(),
                                           session, t1, t2)
        except Exception as e:
            print(f"[H2HView] tipp-előzmény hiba: {e}")
            tip_hist = None
        self._result_panel.show_stats(data, tip_hist)
        self._result_panel.setVisible(True)
