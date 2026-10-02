"""The one widget the single-screen window needs besides the core: the deep background behind it."""
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget

from .theme import qc


class Backdrop(QWidget):
    """Deep gradient behind everything; very subtle, so data stays the focus."""

    def paintEvent(self, e):
        p = QPainter(self)
        g = QLinearGradient(0, 0, 0, self.height())
        g.setColorAt(0, QColor("#06101b")); g.setColorAt(1, QColor("#04070d"))
        p.fillRect(self.rect(), g)
        r = QRadialGradient(self.width() * 0.55, self.height() * 0.28, max(self.width(), self.height()) * 0.55)
        r.setColorAt(0, qc("accent", 26)); r.setColorAt(1, qc("accent", 0))
        p.fillRect(self.rect(), r)
