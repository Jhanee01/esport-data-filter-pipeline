
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QGraphicsOpacityEffect
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QFont

TOAST_STYLES = {
    "success": {
        "bg":     "#1c3829",
        "border": "#3ba560",
        "icon":   "✓",
        "fg":     "#3ba560",
    },
    "error": {
        "bg":     "#3a1c1c",
        "border": "#d44a3a",
        "icon":   "✕",
        "fg":     "#d44a3a",
    },
    "warning": {
        "bg":     "#3a341c",
        "border": "#f2cc0c",
        "icon":   "!",
        "fg":     "#f2cc0c",
    },
    "info": {
        "bg":     "#1c2a3a",
        "border": "#5794f2",
        "icon":   "i",
        "fg":     "#5794f2",
    },
}


class Toast(QWidget):
    """Jobb felső sarokba animált értesítő — 3 mp után eltűnik.

    Child widget a szülőn belül (nem külön platform ablak), hogy
    elkerüljük a Windows User Object handle kimerülést.
    """

    def __init__(self, message: str, kind: str = "info", parent: QWidget | None = None):
        # Nincs Tool/FramelessWindowHint/WindowStaysOnTopHint — child widget
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowFlags(Qt.WindowType.Widget)

        style = TOAST_STYLES.get(kind, TOAST_STYLES["info"])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 18, 10)
        layout.setSpacing(10)

        icon_lbl = QLabel(style["icon"])
        icon_lbl.setFont(QFont("Segoe UI Semibold", 14))
        icon_lbl.setStyleSheet(f"color: {style['fg']};")
        icon_lbl.setFixedWidth(20)

        msg_lbl = QLabel(message)
        msg_lbl.setFont(QFont("Segoe UI", 12))
        msg_lbl.setStyleSheet("color: #d9d9d9;")
        msg_lbl.setWordWrap(True)
        msg_lbl.setMaximumWidth(340)

        layout.addWidget(icon_lbl)
        layout.addWidget(msg_lbl)

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {style['bg']};
                border: 1px solid {style['border']};
                border-radius: 6px;
            }}
        """)
        self.adjustSize()

        QTimer.singleShot(3000, self._fade_out)

    def _fade_out(self):
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._anim = QPropertyAnimation(effect, b"opacity")
        self._anim.setDuration(400)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self.close)
        self._anim.start()


class ToastManager:
    """Globális toast kezelő — a MainWindow-hoz kötve."""

    MAX_TOASTS = 6

    def __init__(self, parent: QWidget):
        self._parent = parent
        self._stack: list[Toast] = []

    def show(self, message: str, kind: str = "info"):
        if len(self._stack) >= self.MAX_TOASTS:
            return
        toast = Toast(message, kind, self._parent)
        toast.show()
        toast.raise_()
        self._stack.append(toast)
        toast.destroyed.connect(lambda: self._on_closed(toast))
        self._reposition_all()

    def success(self, message: str):
        self.show(message, "success")

    def error(self, message: str):
        self.show(message, "error")

    def warning(self, message: str):
        self.show(message, "warning")

    def info(self, message: str):
        self.show(message, "info")

    def _on_closed(self, toast: Toast):
        if toast in self._stack:
            self._stack.remove(toast)
        try:
            self._reposition_all()
        except RuntimeError:
            pass

    def _reposition_all(self):
        if not self._parent:
            return
        try:
            pw = self._parent.width()
        except RuntimeError:
            return
        margin = 16
        spacing = 8
        # Szülő widget lokális koordinátái
        x = pw - margin
        y = margin + 40  # 40px: fejléc alá

        live = [t for t in self._stack if t.isVisible()]
        for toast in live:
            toast.adjustSize()
            tx = x - toast.width()
            toast.move(tx, y)
            toast.raise_()
            y += toast.height() + spacing
