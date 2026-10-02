"""Custom-painted widgets. Every visual element encodes real state (see CoreView)."""
import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient)
from PySide6.QtWidgets import QFrame, QLabel, QPlainTextEdit, QSizePolicy, QToolTip, QWidget

from .theme import C, COST_COLOR, COST_NAME, PRIVACY_NAME, STATE_COLOR, STEP_COLOR, fonts, qc


def pressure_color(x):
    return "ok" if x < 0.6 else "warn" if x < 0.9 else "bad"


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


# ---------------------------------------------------------------------------------------------------------------
class CoreView(QWidget):
    """The command-center hero. A ring of AI providers orbits the core.

    node colour  = cost class (green local, cyan free cloud, violet subscription)
    node arc     = how much of its budget / quota is spent (green -> amber -> red)
    pulse + beam = a call to that provider is in flight RIGHT NOW
    dim + clock  = resting after a rate limit; hollow = blocked by this goal's data class
    core ring    = progress through the plan; core colour = what PRAXIS is doing
    """
    MODE_COLOR = {"idle": "accent_dim", "starting": "muted", "working": "accent", "waiting": "warn", "ok": "ok",
                  "bad": "bad", "stopping": "warn", "stopped": "warn"}
    SPEED = {"idle": 0.5, "starting": 3, "working": 4.5, "waiting": 2.2, "ok": 0.7, "bad": 0.5, "stopping": 6, "stopped": 0.5}

    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 300)
        self.setMouseTracking(True)
        self.ui, self.mono = fonts()
        self.mode, self.progress, self.title, self.subtitle = "starting", 0.0, "STARTING", ""
        self.nodes, self.active, self.phase, self._hit = [], "", 0.0, []
        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(33)

    def set_state(self, mode, progress, title, subtitle=""):
        self.mode, self.progress, self.title, self.subtitle = mode, progress, title, subtitle

    def set_nodes(self, nodes):
        self.nodes = nodes

    def set_active(self, name):
        self.active = name

    def _tick(self):
        if self.isVisible():
            self.phase = (self.phase + self.SPEED.get(self.mode, 1)) % 720
            self.update()

    # -- geometry -----------------------------------------------------------------
    def _layout(self):
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        R = min(w * 0.5, h) * 0.17
        O = min(w * 0.40, h * 0.36)
        self._ox = min(w * 0.40, O * 1.95)      # a wide orbit uses the hero's width instead of leaving it empty
        n = len(self.nodes)
        pos = []
        for i, nd in enumerate(self.nodes):
            a = math.radians(-90 + 360 * i / max(n, 1)) if n > 1 else math.radians(-90)
            pos.append(QPointF(cx + self._ox * math.cos(a), cy + O * math.sin(a)))
        return cx, cy, R, O, pos

    def mouseMoveEvent(self, e):
        for name, pt, r, tip in self._hit:
            if (e.position() - pt).manhattanLength() < r * 1.5:
                QToolTip.showText(e.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()

    @staticmethod
    def _tip(nd):
        lines = [f"{nd['family']}   {PRIVACY_NAME.get(nd['privacy'], nd['privacy'])} / {COST_NAME.get(nd['cost_class'], '')}"]
        for m in nd["models"][:6]:
            bits = [m["name"].split("/", 1)[-1]]
            if m.get("tier"):
                bits.append(f"[{m['tier']}]")
            if m.get("score") is not None:
                bits.append(f"quality {m['score']:.2f}")
            lines.append("  " + " ".join(bits))
        u = nd.get("usage", {}).get("24h", {})
        lines.append(f"used 24h: {u.get('calls', 0)} calls" + (f", ${u['cost']:.2f}" if u.get("cost") else ""))
        if nd["pressure"]:
            lines.append(f"budget spent: {nd['pressure'] * 100:.0f}%")
        if nd["blocked"]:
            lines.append("BLOCKED by this goal's data class")
        elif nd["cooling_s"]:
            lines.append(f"resting {nd['cooling_s'] // 60 + 1} more min (rate limit)")
        elif nd["delegate_only"]:
            lines.append("delegate-only (needs your approval each time)")
        return "\n".join(lines)

    # -- painting --------------------------------------------------------------------
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, R, O, pos = self._layout()
        col = self.MODE_COLOR.get(self.mode, "accent_dim")
        ph = self.phase
        breathe = 0.5 + 0.5 * math.sin(math.radians(ph * 1.4))

        gr = max(R, min(R * 3.2, cx - 2, cy - 2))   # never wider than the widget: no hard clipped edge
        glow = QRadialGradient(cx, cy, gr)
        glow.setColorAt(0, qc(col, int(70 + 40 * breathe))); glow.setColorAt(1, qc(col, 0))
        p.setPen(Qt.NoPen); p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), gr, gr)

        # orbit track
        p.setBrush(Qt.NoBrush)
        pen = QPen(qc("line2", 150), 1, Qt.DotLine)
        p.setPen(pen)
        p.drawEllipse(QPointF(cx, cy), self._ox, O)

        # links + nodes
        self._hit = []
        nr = max(14.0, min(24.0, O * 0.13))
        for nd, pt in zip(self.nodes, pos):
            active = nd["family"] == self.active.split("/")[0] if self.active else False
            base = COST_COLOR.get(nd["cost_class"], "accent")
            dim = nd["blocked"] or nd["cooling_s"] > 0
            link = QPen(qc(base, 255 if active else (30 if dim else 70)), 2.2 if active else 1)
            if nd["blocked"]:
                link.setStyle(Qt.DashLine)
            p.setPen(link)
            vx, vy = pt.x() - cx, pt.y() - cy
            vl = math.hypot(vx, vy) or 1.0
            start = QPointF(cx + vx / vl * R * 1.72, cy + vy / vl * R * 1.72)   # links end at the core's outer ring
            p.drawLine(start, pt)
            if active:  # the beam: a pulse travelling from the node to the core
                t = (ph / 90.0) % 1.0
                q = QPointF(pt.x() + (start.x() - pt.x()) * t, pt.y() + (start.y() - pt.y()) * t)
                g = QRadialGradient(q, 12)
                g.setColorAt(0, qc(base, 230)); g.setColorAt(1, qc(base, 0))
                p.setPen(Qt.NoPen); p.setBrush(g); p.drawEllipse(q, 12, 12)
            # fuel arc: budget spent
            track = QRectF(pt.x() - nr - 6, pt.y() - nr - 6, 2 * (nr + 6), 2 * (nr + 6))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(qc("line", 200), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(track, -225 * 16, -270 * 16)
            if nd["pressure"] > 0:
                p.setPen(QPen(qc(pressure_color(nd["pressure"])), 3, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(track, -225 * 16, int(-270 * 16 * min(1.0, nd["pressure"])))
            # node body
            if nd["blocked"]:
                p.setPen(QPen(qc(base, 120), 1.4, Qt.DashLine)); p.setBrush(qc("bg0", 200))
            else:
                pulse = 1.0 + (0.18 * math.sin(math.radians(ph * 6)) if active else 0)
                fillc = qc(base, 70 if not dim else 25)
                if active:
                    g = QRadialGradient(pt, nr * 2.2)
                    g.setColorAt(0, qc(base, 150)); g.setColorAt(1, qc(base, 0))
                    p.setPen(Qt.NoPen); p.setBrush(g); p.drawEllipse(pt, nr * 2.2, nr * 2.2)
                p.setPen(QPen(qc(base, 255 if not dim else 90), 1.8)); p.setBrush(fillc)
                nrr = nr * pulse
                p.drawEllipse(pt, nrr, nrr)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(base, 255 if not (dim or nd["blocked"]) else 90))
            p.drawEllipse(pt, nr * 0.28, nr * 0.28)
            # label
            p.setFont(QFont(self.ui, 8, QFont.DemiBold))
            p.setPen(qc("text" if not (dim or nd["blocked"]) else "dim"))
            label = nd["family"] + (f"  x{len(nd['models'])}" if len(nd["models"]) > 1 else "")
            p.drawText(QRectF(pt.x() - 70, pt.y() + nr + 8, 140, 14), Qt.AlignCenter, label)
            if nd["cooling_s"]:
                p.setFont(QFont(self.ui, 7)); p.setPen(qc("warn"))
                p.drawText(QRectF(pt.x() - 70, pt.y() + nr + 21, 140, 12), Qt.AlignCenter, f"resting {nd['cooling_s'] // 60 + 1}m")
            elif nd["blocked"]:
                p.setFont(QFont(self.ui, 7)); p.setPen(qc("dim"))
                p.drawText(QRectF(pt.x() - 70, pt.y() + nr + 21, 140, 12), Qt.AlignCenter, "blocked by data class")
            self._hit.append((nd["family"], pt, nr, self._tip(nd)))

        # core: rotating ticks
        p.setBrush(Qt.NoBrush)
        for i in range(72):
            a = math.radians(i * 5 + ph * (0.5 if self.mode in ("idle", "ok", "bad") else 1.6))
            long_ = i % 6 == 0
            r1, r2 = R * 1.55, R * (1.67 if long_ else 1.61)
            p.setPen(QPen(qc(col, 130 if long_ else 55), 1.4 if long_ else 1))
            p.drawLine(QPointF(cx + r1 * math.cos(a), cy + r1 * math.sin(a)), QPointF(cx + r2 * math.cos(a), cy + r2 * math.sin(a)))
        # progress ring
        ring = QRectF(cx - R * 1.3, cy - R * 1.3, R * 2.6, R * 2.6)
        p.setPen(QPen(qc("line2", 170), 5, Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(ring)
        if self.progress > 0:
            p.setPen(QPen(qc(col), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(ring, 90 * 16, int(-360 * 16 * min(1.0, self.progress)))
        elif self.mode in ("working", "stopping", "starting"):
            p.setPen(QPen(qc(col), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(ring, int(-ph * 4 * 16), 70 * 16)
        # inner disc
        disc = QRadialGradient(cx - R * 0.25, cy - R * 0.3, R * 1.2)
        disc.setColorAt(0, qc(col, 120)); disc.setColorAt(0.7, qc(col, 38)); disc.setColorAt(1, qc("bg0", 230))
        p.setPen(QPen(qc(col, 190), 1.6)); p.setBrush(disc)
        rr = R * (0.98 + 0.02 * breathe)
        p.drawEllipse(QPointF(cx, cy), rr, rr)
        # text
        p.setPen(qc("text"))
        p.setFont(QFont(self.ui, max(10, int(R * 0.27)), QFont.Bold))
        p.drawText(QRectF(cx - R, cy - R * 0.38, 2 * R, R * 0.5), Qt.AlignCenter, self.title)
        if self.subtitle:
            p.setPen(qc("muted")); p.setFont(QFont(self.ui, max(8, int(R * 0.14))))
            p.drawText(QRectF(cx - R * 1.2, cy + R * 0.12, 2.4 * R, R * 0.5), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, self.subtitle)


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
