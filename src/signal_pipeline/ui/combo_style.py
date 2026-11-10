"""Shared dropdown style for the Tips view filters.

The qt_material theme marks the selected entry with a solid yellow bar and
opens the popup only as wide as the box, so longer entries get cut off. Here:
- the selected / hovered entry looks like a sidebar menu item
  (transparent background, #FDB900 outline and text);
- the popup opens at least as wide as the longest entry.

Rows are painted by a custom delegate, because the theme's QSS rules (dark
text on the selected row) cannot be overridden reliably with a style sheet.
"""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QComboBox, QStyle, QStyledItemDelegate

GOLD = QColor("#FDB900")
GOLD_HOVER_BG = QColor(253, 185, 0, 20)
GOLD_HOVER_BORDER = QColor(253, 185, 0, 102)
TEXT = QColor("#ffffff")

_PAD_X = 12     # text inset inside the outline
_MARGIN = 4     # row margin inside the list
_ROW_H = 34

COMBO_QSS = """
QComboBox {
    background-color: #272727;
    color: #e8e8e8;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 4px 28px 4px 12px;
    font-size: 13px;
}
QComboBox:hover, QComboBox:focus, QComboBox:on {
    border: 1px solid #FDB900;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #FDB900;
    width: 0; height: 0;
}
QComboBox QAbstractItemView {
    background-color: #1e1e1e;
    border: 1px solid #3a3a3a;
    padding: 4px;
    outline: 0;
}
"""


class _NavItemDelegate(QStyledItemDelegate):
    """Sidebar-style row: gold outline and gold text when selected."""

    def sizeHint(self, option, index):
        w = option.fontMetrics.horizontalAdvance(str(index.data() or ""))
        return QSize(w + 2 * (_PAD_X + _MARGIN) + 4, _ROW_H)

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        r = QRectF(option.rect).adjusted(_MARGIN, 2, -_MARGIN, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            p.setPen(QPen(GOLD, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 8, 8)
        elif hover:
            p.setPen(QPen(GOLD_HOVER_BORDER, 2))
            p.setBrush(GOLD_HOVER_BG)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 8, 8)
        p.setPen(GOLD if (selected or hover) else TEXT)
        p.setFont(option.font)
        p.drawText(r.adjusted(_PAD_X, 0, -4, 0),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   str(index.data() or ""))
        p.restore()


def _fit_popup(c: QComboBox):
    fm = c.view().fontMetrics()
    widest = max((fm.horizontalAdvance(c.itemText(i)) for i in range(c.count())), default=0)
    c.view().setMinimumWidth(max(c.width(), widest + 2 * (_PAD_X + _MARGIN) + 24))


def style_combo(c: QComboBox) -> QComboBox:
    """Sidebar-style dropdown whose popup never cuts off long entries."""
    c.setStyleSheet(COMBO_QSS)
    c.setItemDelegate(_NavItemDelegate(c))
    c.view().setMouseTracking(True)
    c.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
    # Keep the popup's Qt container frame from showing a white border
    c.view().window().setStyleSheet(
        "QComboBoxPrivateContainer{background-color:#1e1e1e;"
        "border:1px solid #3a3a3a;border-radius:8px;}")
    m = c.model()
    for sig in (m.rowsInserted, m.rowsRemoved, m.modelReset):
        sig.connect(lambda *_: _fit_popup(c))
    _fit_popup(c)
    return c
