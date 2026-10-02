"""Custom-painted widgets. Every visual element encodes real state (see CoreView)."""
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QSizePolicy, QToolTip, QWidget

from .core import CoreView, pressure_color  # noqa: F401  (re-exported: pages import them from here)
from .theme import C, COST_COLOR, COST_NAME, PRIVACY_NAME, STATE_COLOR, STEP_COLOR, fonts, qc


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


def card(name="card"):
    f = QFrame()
    f.setObjectName(name)
    return f


class Chip(QLabel):
    def __init__(self, text="", tone="muted"):
        super().__init__(text)
        self.setObjectName("chip")
        self.setFixedHeight(22)
        self.setAlignment(Qt.AlignCenter)
        self.set_tone(tone)

    def set_tone(self, tone):
        col = C.get(tone, tone)
        self.setStyleSheet(f"QLabel#chip {{ color: {col}; background: rgba({QColor(col).red()},{QColor(col).green()},"
                           f"{QColor(col).blue()},34); border: 1px solid rgba({QColor(col).red()},{QColor(col).green()},"
                           f"{QColor(col).blue()},90); }}")


class ElidedLabel(QLabel):
    """A label that shrinks (with an ellipsis in the middle) instead of forcing its window wider: long Windows paths."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def minimumSizeHint(self):
        return QSize(0, super().minimumSizeHint().height())

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, self.fontMetrics().elidedText(self.text(), Qt.ElideMiddle, self.width()))


class FuelBar(QWidget):
    """Thin labelled bar: how much of a budget / quota / resource is spent."""

    def __init__(self, label="", height=26):
        super().__init__()
        self.setFixedHeight(height)
        self.label, self.value, self.text, self.tone = label, 0.0, "", None
        self.ui, _ = fonts()

    def set(self, value, text="", tone=None):
        self.value, self.text, self.tone = max(0.0, min(1.0, value)), text, tone
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setFont(QFont(self.ui, 8))
        p.setPen(qc("muted"))
        p.drawText(QRectF(0, 0, w, 13), Qt.AlignLeft | Qt.AlignVCenter, self.label)
        p.setPen(qc("text"))
        p.drawText(QRectF(0, 0, w, 13), Qt.AlignRight | Qt.AlignVCenter, self.text)
        y = h - 8
        p.setPen(Qt.NoPen)
        p.setBrush(qc("line"))
        p.drawRoundedRect(QRectF(0, y, w, 5), 2.5, 2.5)
        if self.value > 0:
            g = QLinearGradient(0, 0, w, 0)
            col = self.tone or pressure_color(self.value)
            g.setColorAt(0, qc(col, 150)); g.setColorAt(1, qc(col))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(0, y, max(5.0, w * self.value), 5), 2.5, 2.5)


class Segmented(QWidget):
    """Segmented control (data class / frugality)."""
    changed = Signal(str)

    def __init__(self, options, current, tones=None, tips=None):
        super().__init__()
        self.options, self.current, self.tones, self.tips = options, current, tones or {}, tips or {}
        self.ui, _ = fonts()
        self.setFixedHeight(32)
        self.setCursor(Qt.PointingHandCursor)
        self.setMouseTracking(True)
        self.setMinimumWidth(len(options) * 76)

    def sizeHint(self):
        return QSize(len(self.options) * 84, 32)

    def set_current(self, key):
        if key != self.current and key in dict(self.options):
            self.current = key
            self.update()

    def _slot(self, x):
        return min(len(self.options) - 1, max(0, int(x / (self.width() / len(self.options)))))

    def mousePressEvent(self, e):
        key = self.options[self._slot(e.position().x())][0]
        if key != self.current:
            self.current = key
            self.update()
            self.changed.emit(key)

    def mouseMoveEvent(self, e):
        tip = self.tips.get(self.options[self._slot(e.position().x())][0], "")
        if tip:
            QToolTip.showText(e.globalPosition().toPoint(), tip, self)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h, n = self.width(), self.height(), len(self.options)
        p.setPen(QPen(qc("line2"), 1)); p.setBrush(qc("panel"))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), 9, 9)
        sw = w / n
        p.setFont(QFont(self.ui, 8, QFont.Bold))
        for i, (key, label) in enumerate(self.options):
            r = QRectF(i * sw + 2, 2, sw - 4, h - 4)
            if key == self.current:
                col = self.tones.get(key, "accent")
                p.setPen(Qt.NoPen); p.setBrush(qc(col, 46))
                p.drawRoundedRect(r, 7, 7)
                p.setPen(QPen(qc(col, 170), 1)); p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(r, 7, 7)
                p.setPen(qc(col))
            else:
                p.setPen(qc("muted"))
            p.drawText(r, Qt.AlignCenter, label)


class NavButton(QWidget):
    clicked = Signal(str)

    def __init__(self, key, label, icon):
        super().__init__()
        self.key, self.label, self.icon, self.active, self.hover = key, label, icon, False, False
        self.ui, _ = fonts()
        self.setFixedHeight(42)
        self.setCursor(Qt.PointingHandCursor)

    def set_active(self, on):
        self.active = on
        self.update()

    def enterEvent(self, e):
        self.hover = True; self.update()

    def leaveEvent(self, e):
        self.hover = False; self.update()

    def mousePressEvent(self, e):
        self.clicked.emit(self.key)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        col = "accent" if self.active else ("text" if self.hover else "muted")
        if self.active:
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0, qc("accent", 40)); g.setColorAt(1, qc("accent", 0))
            p.fillRect(QRectF(0, 0, w, h), g)
            p.fillRect(QRectF(0, 8, 3, h - 16), qc("accent"))
        elif self.hover:
            p.fillRect(QRectF(0, 0, w, h), qc("accent", 12))
        draw_icon(p, self.icon, QRectF(20, h / 2 - 9, 18, 18), qc(col))
        p.setPen(qc(col))
        p.setFont(QFont(self.ui, 10, QFont.DemiBold))
        p.drawText(QRectF(50, 0, w - 50, h), Qt.AlignVCenter | Qt.AlignLeft, self.label)


def draw_icon(p, name, r, color):
    p.save()
    p.setPen(QPen(color, 1.6)); p.setBrush(Qt.NoBrush)
    cx, cy, s = r.center().x(), r.center().y(), r.width() / 2
    if name == "mission":
        p.drawEllipse(QPointF(cx, cy), s * 0.9, s * 0.9); p.drawEllipse(QPointF(cx, cy), s * 0.35, s * 0.35)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p.drawLine(QPointF(cx + dx * s * 0.9, cy + dy * s * 0.9), QPointF(cx + dx * s * 1.15, cy + dy * s * 1.15))
    elif name == "timeline":
        for i, y in enumerate((-0.6, 0, 0.6)):
            p.drawLine(QPointF(cx - s * 0.2, cy + y * s), QPointF(cx + s * 0.95, cy + y * s))
            p.drawEllipse(QPointF(cx - s * 0.7, cy + y * s), 1.6, 1.6)
    elif name == "fuel":
        p.drawRoundedRect(QRectF(cx - s * 0.9, cy - s * 0.5, s * 1.6, s), 2.5, 2.5)
        p.drawLine(QPointF(cx + s * 0.8, cy - s * 0.2), QPointF(cx + s * 0.8, cy + s * 0.2))
        p.setBrush(color); p.drawRoundedRect(QRectF(cx - s * 0.75, cy - s * 0.35, s * 0.9, s * 0.7), 1.5, 1.5)
    elif name == "models":
        p.drawRoundedRect(QRectF(cx - s * 0.6, cy - s * 0.6, s * 1.2, s * 1.2), 2.5, 2.5)
        for k in (-0.35, 0.35):
            p.drawLine(QPointF(cx + k * s, cy - s * 0.6), QPointF(cx + k * s, cy - s * 1.0))
            p.drawLine(QPointF(cx + k * s, cy + s * 0.6), QPointF(cx + k * s, cy + s * 1.0))
    elif name == "memory":
        for k in (-0.55, 0, 0.55):
            p.drawRoundedRect(QRectF(cx - s * 0.85, cy + k * s - s * 0.22, s * 1.7, s * 0.44), 2, 2)
    elif name == "system":
        path = QPainterPath()
        for i in range(6):
            a = math.radians(60 * i - 30)
            pt = QPointF(cx + s * 0.95 * math.cos(a), cy + s * 0.95 * math.sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        path.closeSubpath(); p.drawPath(path); p.drawEllipse(QPointF(cx, cy), s * 0.3, s * 0.3)
    p.restore()


class LogView(QPlainTextEdit):
    """Read-only coloured text feed (activity, reports)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("mono")
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        self.setMaximumBlockCount(2000)
        _, mono = fonts()
        self.setFont(QFont(mono, 10))
        self._fmt = {}

    def append_line(self, text, tone="info"):
        from PySide6.QtGui import QTextCharFormat
        key = {"ok": "ok", "warn": "warn", "bad": "bad", "info": "muted", "muted": "dim", "text": "text"}.get(tone, "muted")
        fmt = self._fmt.get(key)
        if fmt is None:
            fmt = QTextCharFormat(); fmt.setForeground(QColor(C[key])); self._fmt[key] = fmt
        cur = self.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        cur.insertText(text + "\n", fmt)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def replace_all(self, text, tone="info"):
        self.clear()
        for line in text.splitlines():
            self.append_line(line, tone)


# CoreView (the particle sphere) lives in core.py and is re-exported above.
# ---------------------------------------------------------------------------------------------------------------
class StepGraph(QWidget):
    """The plan as a real dependency graph with live state."""
    stepClicked = Signal(str)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(96)
        self.setMouseTracking(True)
        self.steps, self.phase, self._hit = [], 0.0, []
        self.ui, _ = fonts()
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(50)

    def set_steps(self, steps):
        self.steps = steps
        self.update()

    def _tick(self):
        if self.isVisible() and any(s.state in ("running", "waiting") for s in self.steps):
            self.phase = (self.phase + 9) % 360
            self.update()

    def mouseMoveEvent(self, e):
        for s, pt in self._hit:
            if (e.position() - pt).manhattanLength() < 24:
                QToolTip.showText(e.globalPosition().toPoint(), f"{s.id}: {s.tool}\n{s.summary}\nClass {s.cls}  -  {s.state}", self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, e):
        for s, pt in self._hit:
            if (e.position() - pt).manhattanLength() < 24:
                self.stepClicked.emit(s.id)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self.steps)
        self._hit = []
        if not n:
            p.setPen(qc("dim")); p.setFont(QFont(self.ui, 10))
            p.drawText(self.rect(), Qt.AlignCenter, "The plan appears here as a graph once PRAXIS has one.")
            return
        m = 46
        xs = [w / 2] if n == 1 else [m + i * (w - 2 * m) / (n - 1) for i in range(n)]
        cy = h / 2 + 4
        pos = {s.id: QPointF(x, cy) for s, x in zip(self.steps, xs)}
        for s in self.steps:  # edges first
            for d in s.deps:
                if d in pos:
                    a, b = pos[d], pos[s.id]
                    path = QPainterPath(a)
                    lift = 16 + 8 * abs(b.x() - a.x()) / max(w, 1) * 4
                    path.quadTo(QPointF((a.x() + b.x()) / 2, cy - lift), b)
                    done = s.state in ("verified", "ran")
                    p.setPen(QPen(qc("ok" if done else "line2", 200 if done else 255), 1.6))
                    p.setBrush(Qt.NoBrush)
                    p.drawPath(path)
        for s in self.steps:
            pt = pos[s.id]
            self._hit.append((s, pt))
            key = {"ran": "muted"}.get(s.state) or STEP_COLOR.get(s.state, "dim")
            col = "muted" if key == "info_" else key
            pulse = 1 + 0.12 * math.sin(math.radians(self.phase * 2)) if s.state in ("running", "waiting") else 1
            r = 14 * pulse
            if s.state in ("running", "waiting"):
                g = QRadialGradient(pt, 30)
                g.setColorAt(0, qc(col, 120)); g.setColorAt(1, qc(col, 0))
                p.setPen(Qt.NoPen); p.setBrush(g); p.drawEllipse(pt, 30, 30)
            p.setPen(QPen(qc(col), 1.8)); p.setBrush(qc(col, 45))
            p.drawEllipse(pt, r, r)
            p.setPen(QPen(qc(col), 2.0, Qt.SolidLine, Qt.RoundCap))
            x, y = pt.x(), pt.y()
            if s.state == "verified":
                p.drawPolyline([QPointF(x - 5, y), QPointF(x - 1.5, y + 4), QPointF(x + 6, y - 4)])
            elif s.state in ("failed", "denied"):
                p.drawLine(QPointF(x - 4.5, y - 4.5), QPointF(x + 4.5, y + 4.5)); p.drawLine(QPointF(x + 4.5, y - 4.5), QPointF(x - 4.5, y + 4.5))
            elif s.state == "running":
                p.setBrush(qc(col)); p.setPen(Qt.NoPen)
                p.drawPolygon([QPointF(x - 3, y - 5), QPointF(x - 3, y + 5), QPointF(x + 5, y)])
            elif s.state == "waiting":
                p.drawArc(QRectF(x - 5, y - 5, 10, 10), 90 * 16, -270 * 16)
            elif s.state == "rolled back":
                p.drawArc(QRectF(x - 5, y - 5, 10, 10), 40 * 16, 270 * 16)
            elif s.state == "ran":
                p.setBrush(qc(col)); p.setPen(Qt.NoPen); p.drawEllipse(pt, 3, 3)
            p.setFont(QFont(self.ui, 8, QFont.DemiBold)); p.setPen(qc("text"))
            p.drawText(QRectF(x - 40, y + 20, 80, 14), Qt.AlignCenter, s.id)
            p.setFont(QFont(self.ui, 7)); p.setPen(qc("dim"))
            p.drawText(QRectF(x - 44, y - 38, 88, 12), Qt.AlignCenter, s.tool)
