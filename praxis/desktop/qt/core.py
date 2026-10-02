"""The PRAXIS core: a living particle sphere with your AIs flanking it. Every visual encodes real state.

  sphere colour / speed / size   what PRAXIS is doing (idle, starting, working, waiting for you, verified, failed, stopping)
  stream of particles            a call to that provider is in flight RIGHT NOW (View.active_provider, from model.try)
  particle ring                  plan progress: lit points = steps verified / total
  ripple through the sphere      a real event just happened (colour = its level)
  shockwave + green              the goal VERIFIED
  node colour / arc / clock      cost class (green local, cyan free cloud, violet subscription) / budget spent / resting
  hollow node                    this goal's data class forbids that provider
  caption                        the latest real event, typed out
Decoration is allowed; fake data is not: nothing here shows a number that is not measured.
"""
import math
import os
import time

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
                           QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QToolTip, QWidget

from . import particles as P
from .theme import C, COST_COLOR, COST_NAME, PRIVACY_NAME, fonts, qc


def pressure_color(x):
    return "ok" if x < 0.6 else "warn" if x < 0.9 else "bad"


def rgb(c, a=255):
    return QColor(int(max(0, min(255, c[0]))), int(max(0, min(255, c[1]))), int(max(0, min(255, c[2]))), int(max(0, min(255, a))))


LEVEL_COLOR = {"info": "accent", "ok": "ok", "warn": "warn", "bad": "bad", "muted": "muted"}
MODE_COLOR = {"idle": "accent", "starting": "muted", "working": "accent", "waiting": "warn", "ok": "ok", "bad": "bad",
              "stopping": "warn", "stopped": "warn"}
REDUCED = bool(os.environ.get("PRAXIS_REDUCE_MOTION"))


class CoreView(QWidget):
    MODE_COLOR = MODE_COLOR

    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 300)
        self.setMouseTracking(True)
        self.ui, self.mono = fonts()
        self.mode, self.progress, self.title, self.subtitle = "starting", 0.0, "STARTING", ""
        self.nodes, self.active, self._hit = [], "", []
        self.t = 0.0
        self.quality = P.Quality()
        self.field = P.Field(P.LEVELS[0] if not REDUCED else P.LEVELS[2])
        self.field.dyn.set_mode("starting")
        self.ripples = []             # (t_start, colour_key)
        self._last_ripple = -1.0
        self.caption, self.cap_level, self.cap_t = "", "info", 0.0
        self.footer = ""
        self._sprites = {}
        self._aura_cache = {}
        self.stars = [(((i * 0.6180339887) % 1.0), ((i * 0.7548776662 + 0.31) % 1.0), 0.4 + 0.6 * ((i * 0.5698402909) % 1.0),
                       (i * 1.7) % 6.28) for i in range(110)]
        self._last = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(80 if REDUCED else 33)

    # ---- the API the pages use ---------------------------------------------------------------------------------
    def set_state(self, mode, progress, title, subtitle=""):
        if mode != self.mode:
            if mode == "starting":
                self.field.restart_assembly()
            elif mode == "ok":
                self.field.trigger_shock()
                self._ripple("ok", force=True)
            elif mode in ("bad", "stopping"):
                self._ripple("bad" if mode == "bad" else "warn", force=True)
            self.field.dyn.set_mode(mode)
            # calm states do not need 30 fps; saves CPU while you are just reading
            self.timer.setInterval(80 if REDUCED else 33 if mode in ("working", "starting", "stopping", "ok") else 42)
        self.mode, self.progress, self.title, self.subtitle = mode, progress, title, subtitle

    def set_nodes(self, nodes):
        self.nodes = nodes

    def set_active(self, name):
        self.active = name

    def set_caption(self, text, level="info"):
        if text != self.caption:
            self.caption, self.cap_level, self.cap_t = text, level, 0.0

    @property
    def caption_shown(self):
        """The part of the caption typed out so far (70 characters per second)."""
        return self.caption[:max(0, int(self.cap_t * 70))]

    def set_footer(self, text):
        self.footer = text

    def pulse(self, level="info"):
        """A real event happened: send a ripple through the sphere (rate limited so a burst stays readable)."""
        self._ripple(level)

    def _ripple(self, level, force=False):
        if not force and self.t - self._last_ripple < 0.14:
            return
        self._last_ripple = self.t
        self.ripples = (self.ripples + [(self.t, LEVEL_COLOR.get(level, "accent"))])[-6:]

    # ---- time ----------------------------------------------------------------------------------------------------
    def advance(self, dt):
        """Step the simulation by dt seconds (the timer calls this with real time; previews and tests step it by hand)."""
        self.t += dt
        self.field.advance(dt * (0.2 if REDUCED else 1.0))
        self.cap_t += dt
        self.ripples = [r for r in self.ripples if self.t - r[0] < 1.6]

    def _tick(self):
        now = time.perf_counter()
        dt, self._last = now - self._last, now
        if self.isVisible():
            self.advance(dt)
            self.update()

    # ---- geometry ----------------------------------------------------------------------------------------------------
    def _geo(self):
        w, h = self.width(), self.height()
        top, bot = 64.0, 56.0
        avail = max(60.0, h - top - bot)
        cx, cy = w / 2.0, top + avail / 2.0
        R = max(28.0, min(avail * 0.45, w * 0.19))
        cx += 3.0 * math.sin(self.t * 0.37); cy += 2.5 * math.sin(self.t * 0.51 + 1.3)      # it hovers
        nr = max(9.0, min(14.0, avail * 0.05))
        order = list(range(len(self.nodes)))
        left = [i for i in order if self.nodes[i]["cost_class"] <= 1]
        right = [i for i in order if self.nodes[i]["cost_class"] >= 2]
        if len(order) > 1 and (not left or not right):       # one side empty: split evenly instead of a lopsided column
            half = (len(order) + 1) // 2
            left, right = order[:half], order[half:]
        pos = {}
        for side, arr in ((-1, left), (1, right)):
            k = len(arr)
            step = min(58.0, avail / max(k, 1))
            for j, i in enumerate(arr):
                dy = (j - (k - 1) / 2.0) * step
                u = dy / (avail / 2.0)
                xoff = R * 1.62 + 34.0 + min(w * 0.07, 64.0) * (1.0 - u * u)
                x = cx + side * xoff
                if w > 300:
                    x = max(124.0, min(w - 124.0, x))
                pos[i] = (QPointF(x, cy + dy), side)
        return dict(w=w, h=h, cx=cx, cy=cy, R=R, nr=nr, top=top, bot=bot, avail=avail, pos=pos)

    def mouseMoveEvent(self, e):
        g = self._geo()
        self.field.tilt_target = [max(-0.5, min(0.5, (e.position().y() - g["cy"]) / max(g["h"], 1) * 0.9)),
                                  max(-0.6, min(0.6, (e.position().x() - g["cx"]) / max(g["w"], 1) * 1.1))]
        for name, pt, r, tip in self._hit:
            if (e.position() - pt).manhattanLength() < r * 1.6:
                QToolTip.showText(e.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, e):
        g = self._geo()
        if math.hypot(e.position().x() - g["cx"], e.position().y() - g["cy"]) < g["R"] * 1.3:
            self._ripple("info", force=True)          # poke the sphere: it answers

    def leaveEvent(self, e):
        self.field.tilt_target = [0.0, 0.0]

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

    # ---- painting ------------------------------------------------------------------------------------------------------
    def _glow(self, hue, size):
        key = (hue, int(size))
        pm = self._sprites.get(key)
        if pm is None:
            s = int(size)
            pm = QPixmap(s, s)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            g = QRadialGradient(s / 2.0, s / 2.0, s / 2.0)
            c = P.SPARKLE[hue % 3]
            g.setColorAt(0.0, QColor(255, 255, 255, 255)); g.setColorAt(0.18, rgb(c, 235)); g.setColorAt(0.5, rgb(c, 70)); g.setColorAt(1.0, rgb(c, 0))
            q.setPen(Qt.NoPen); q.setBrush(g); q.drawEllipse(QPointF(s / 2.0, s / 2.0), s / 2.0, s / 2.0)
            # a four-point flare, like a lens star
            q.setPen(QPen(QColor(255, 255, 255, 90), 1)); q.drawLine(QPointF(s * 0.18, s / 2.0), QPointF(s * 0.82, s / 2.0))
            q.drawLine(QPointF(s / 2.0, s * 0.18), QPointF(s / 2.0, s * 0.82))
            q.end()
            self._sprites[key] = pm
        return pm

    def paintEvent(self, e):
        t0 = time.perf_counter()
        w, h = self.width(), self.height()
        if w < 80 or h < 80:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        g = self._geo()
        tint, mixv = self.field.tint_colour()
        base = QLinearGradient(0, 0, 0, h)                       # its own deep-space base: additive glow must blend onto dark,
        base.setColorAt(0.0, QColor(6, 16, 27)); base.setColorAt(1.0, QColor(4, 7, 13))   # whatever widget it is placed in
        p.fillRect(self.rect(), base)
        self._stars(p, g)
        self._aura(p, g, tint, mixv)
        self._orbit_and_links(p, g)
        self._sphere(p, g, tint, mixv)
        self._ripples(p, g, tint)
        self._nodes(p, g)
        self._hud(p, g)
        p.end()
        if self.quality.record((time.perf_counter() - t0) * 1000.0):
            self.field.resize(self.quality.n)

    def _stars(self, p, g):
        w, h = g["w"], g["h"]
        tx, ty = self.field.tilt[1] * 22, self.field.tilt[0] * 14
        p.setPen(Qt.NoPen)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        for sx, sy, z, ph in self.stars:
            a = (0.35 + 0.65 * (0.5 + 0.5 * math.sin(self.t * (0.6 + z) + ph))) * 90 * z
            p.setBrush(QColor(190, 205, 255, int(a)))
            r = 0.6 + 1.1 * z
            p.drawEllipse(QPointF(((sx * w + tx * z * 2.0) % w), ((sy * h + ty * z * 2.0) % h)), r, r)

    def _aura_pixmap(self, R, tint, mixv):
        """The two-lobed glow (blue above, pink below) plus the inner light, rendered ONCE per colour state at half
        resolution. Painting these huge gradients every frame was most of the frame time."""
        key = (int(R // 4), tuple(int(c // 16) for c in tint), int(mixv * 10))
        pm = self._aura_cache.get(key)
        if pm is None:
            side = int(R * 2.7)                                    # half of the 2 * 2.7R area it covers on screen
            pm = QPixmap(side, side)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            q.setCompositionMode(QPainter.CompositionMode_Plus)
            q.scale(0.5, 0.5)
            c0 = R * 2.7
            top, bot = P.mix(P.palette_at(0.0), tint, mixv), P.mix(P.palette_at(1.0), tint, mixv)
            q.setPen(Qt.NoPen)
            for oy, col, a in ((-R * 0.45, top, 66), (R * 0.45, bot, 60)):
                rad = R * 2.45
                gr = QRadialGradient(c0, c0 + oy, rad)
                gr.setColorAt(0.0, rgb(col, a)); gr.setColorAt(0.55, rgb(col, a * 0.28)); gr.setColorAt(1.0, rgb(col, 0))
                q.setBrush(gr); q.drawEllipse(QPointF(c0, c0 + oy), rad, rad)
            gr = QRadialGradient(c0, c0, R * 0.95)                  # lit from inside
            gr.setColorAt(0.0, rgb(P.mix((255, 255, 255), tint, 0.5 + 0.4 * mixv), 36)); gr.setColorAt(1.0, rgb(tint, 0))
            q.setBrush(gr); q.drawEllipse(QPointF(c0, c0), R * 0.95, R * 0.95)
            q.end()
            if len(self._aura_cache) > 12:
                self._aura_cache.pop(next(iter(self._aura_cache)))
            self._aura_cache[key] = pm
        return pm

    def _aura(self, p, g, tint, mixv):
        cx, cy, R = g["cx"], g["cy"], g["R"]
        pm = self._aura_pixmap(R, tint, mixv)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        breathe = 0.5 + 0.5 * math.sin(self.t * 1.3)
        p.setOpacity(min(1.0, (0.82 + 0.18 * breathe) * self.field.dyn.v["bright"]))
        half = R * 2.7
        p.drawPixmap(QRectF(cx - half, cy - half, 2 * half, 2 * half), pm, QRectF(pm.rect()))
        p.setOpacity(1.0)

    def _link_curve(self, g, i):
        pt, side = g["pos"][i]
        cx, cy, R = g["cx"], g["cy"], g["R"]
        vx, vy = pt.x() - cx, pt.y() - cy
        vl = math.hypot(vx, vy) or 1.0
        p0 = (cx + vx / vl * R * 1.12, cy + vy / vl * R * 1.12)
        p2 = (pt.x() - side * g["nr"] * 1.2, pt.y())
        mx, my = (p0[0] + p2[0]) / 2.0, (p0[1] + p2[1]) / 2.0
        nxv, nyv = -vy / vl, vx / vl
        p1 = (mx + nxv * vl * 0.12, my + nyv * vl * 0.12 - 8)
        return p0, p1, p2

    def _orbit_and_links(self, p, g):
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self._hit = []
        for i, nd in enumerate(self.nodes):
            if i not in g["pos"]:
                continue
            active = bool(self.active) and nd["family"] == self.active.split("/")[0]
            base = COST_COLOR.get(nd["cost_class"], "accent")
            dim = nd["blocked"] or nd["cooling_s"] > 0
            p0, p1, p2 = self._link_curve(g, i)
            path = QPainterPath(QPointF(*p0))
            path.quadTo(QPointF(*p1), QPointF(*p2))
            pen = QPen(qc(base, 235 if active else (26 if dim else 58)), 2.0 if active else 1.0)
            if nd["blocked"]:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            if active:       # the stream: particles carrying the request from the sphere to the provider, right now
                p.setCompositionMode(QPainter.CompositionMode_Plus)
                p.setPen(Qt.NoPen)
                bc = QColor(C[base])
                for x, y, a, s, u in P.courier(self.t, p0, p1, p2):
                    p.setBrush(QColor(bc.red(), bc.green(), bc.blue(), int(235 * a)))
                    p.drawEllipse(QPointF(x, y), s, s)
                    p.setBrush(QColor(255, 255, 255, int(150 * a)))
                    p.drawEllipse(QPointF(x, y), s * 0.45, s * 0.45)
                p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def _sphere(self, p, g, tint, mixv):
        cx, cy, R = g["cx"], g["cy"], g["R"]
        f = self.field
        bright = f.dyn.v["bright"]
        sz = max(0.75, min(1.35, R / 105.0))
        buckets, sparks = f.project(cx, cy, R, QPointF)
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        cols = [P.mix(P.palette_at((b + 0.5) / P.BUCKETS), tint, mixv) for b in range(P.BUCKETS)]
        widths = (1.2 * sz, 1.7 * sz, 2.3 * sz)
        alphas = (95, 165, 245)
        lum_gain = (0.62, 1.25)          # dim points / bright points (the shell and a quarter of the cloud)

        def layer(depth):
            for b in range(P.BUCKETS):
                for v in range(P.VARIANTS):
                    pts = buckets[(b * 3 + depth) * P.VARIANTS + v]
                    if pts:
                        pen = QPen(rgb(cols[b], alphas[depth] * bright * lum_gain[v]), widths[depth] * (0.9 + 0.2 * v))
                        pen.setCapStyle(Qt.RoundCap)
                        p.setPen(pen)
                        p.drawPoints(QPolygonF(pts))

        ring = P.ring(self.t, self.progress)
        layer(0)
        self._ring(p, g, ring, tint, back=True)
        layer(1)
        layer(2)
        # sparkles: warm gold / white / ice stars that twinkle
        for x, y, z, i in sparks:
            a = f.sparkle_alpha(i)
            s = (9 + 13 * a) * sz * (0.8 + 0.4 * z)
            pm = self._glow(f.shue[i], 40)
            p.setOpacity(min(1.0, 0.1 + 0.8 * a) * (0.4 + 0.6 * z))
            p.drawPixmap(QRectF(x - s / 2, y - s / 2, s, s), pm, QRectF(0, 0, 40, 40))
        p.setOpacity(1.0)
        if self.mode in ("working", "starting") and R > 40:     # a scan beam sweeping the sphere
            u = (self.t * 0.55) % 1.5 - 0.25
            by = cy - R * 1.1 + u * R * 2.2
            clip = QPainterPath(); clip.addEllipse(QPointF(cx, cy), R * 1.06, R * 1.06)
            p.save(); p.setClipPath(clip)
            gr = QLinearGradient(0, by - R * 0.28, 0, by + R * 0.28)
            gr.setColorAt(0.0, rgb(tint, 0)); gr.setColorAt(0.5, rgb(P.mix((255, 255, 255), tint, 0.4), 70)); gr.setColorAt(1.0, rgb(tint, 0))
            p.setPen(Qt.NoPen); p.setBrush(gr)
            p.drawRect(QRectF(cx - R * 1.2, by - R * 0.28, R * 2.4, R * 0.56))
            p.restore()
        self._ring(p, g, ring, tint, back=False)

    def _ring(self, p, g, ring, tint, back):
        cx, cy, R = g["cx"], g["cy"], g["R"]
        rr = R * 1.34 * self.field.dyn.v["scale"]
        col = P.mix((0x3f, 0xd7, 0xff), tint, 0.4)
        p.setPen(Qt.NoPen)
        spin = self.t * (0.9 if self.mode == "working" else 0.25)
        cs, sn = math.cos(spin), math.sin(spin)
        for x, y, z, lit, head in ring:
            if (z < 0) != back:
                continue
            xs, ys = x * cs - y * sn, x * sn + y * cs            # slow roll within the ring's plane
            depth = 0.55 + 0.45 * z
            if lit:
                p.setBrush(rgb(col, 235 * (0.55 + 0.45 * depth)))
                s = 1.5 + 0.9 * depth
            else:
                p.setBrush(QColor(110, 140, 190, int(70 + 60 * depth)))
                s = 1.0 + 0.5 * depth
            p.drawEllipse(QPointF(cx + xs * rr, cy - ys * rr), s, s)
            if head and not back:
                gr = QRadialGradient(cx + xs * rr, cy - ys * rr, 16)
                gr.setColorAt(0, QColor(255, 255, 255, 230)); gr.setColorAt(0.4, rgb(col, 140)); gr.setColorAt(1, rgb(col, 0))
                p.setBrush(gr)
                p.drawEllipse(QPointF(cx + xs * rr, cy - ys * rr), 16, 16)
                p.setBrush(rgb(col, 235))

    def _ripples(self, p, g, tint):
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.setBrush(Qt.NoBrush)
        for t0, key in self.ripples:
            u = (self.t - t0) / 1.6
            if not 0 <= u <= 1:
                continue
            col = QColor(C[key])
            r = g["R"] * (0.95 + 1.5 * (1 - (1 - u) ** 2))
            a = int(210 * (1 - u) ** 1.6)
            pen = QPen(QColor(col.red(), col.green(), col.blue(), a), 2.4 * (1 - u) + 0.6)
            p.setPen(pen)
            p.drawEllipse(QPointF(g["cx"], g["cy"]), r, r * 0.97)

    def _nodes(self, p, g):
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        nr = g["nr"]
        for i, nd in enumerate(self.nodes):
            if i not in g["pos"]:
                continue
            pt, side = g["pos"][i]
            active = bool(self.active) and nd["family"] == self.active.split("/")[0]
            base = COST_COLOR.get(nd["cost_class"], "accent")
            dim = nd["blocked"] or nd["cooling_s"] > 0
            track = QRectF(pt.x() - nr - 6, pt.y() - nr - 6, 2 * (nr + 6), 2 * (nr + 6))
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(qc("line", 200), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(track, -225 * 16, -270 * 16)                            # fuel gauge: how much of the allowance is spent
            if nd["pressure"] > 0:
                p.setPen(QPen(qc(pressure_color(nd["pressure"])), 3, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(track, -225 * 16, int(-270 * 16 * min(1.0, nd["pressure"])))
            if nd["blocked"]:
                p.setPen(QPen(qc(base, 120), 1.4, Qt.DashLine)); p.setBrush(qc("bg0", 200))
                p.drawEllipse(pt, nr, nr)
            else:
                if active:
                    p.setCompositionMode(QPainter.CompositionMode_Plus)
                    gr = QRadialGradient(pt, nr * 3.0)
                    pulse = 0.65 + 0.35 * math.sin(self.t * 7.0)
                    gr.setColorAt(0, qc(base, int(170 * pulse))); gr.setColorAt(1, qc(base, 0))
                    p.setPen(Qt.NoPen); p.setBrush(gr); p.drawEllipse(pt, nr * 3.0, nr * 3.0)
                    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                p.setPen(QPen(qc(base, 255 if not dim else 90), 1.8)); p.setBrush(qc(base, 70 if not dim else 25))
                p.drawEllipse(pt, nr, nr)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(base, 255 if not (dim or nd["blocked"]) else 90))
            p.drawEllipse(pt, nr * 0.3, nr * 0.3)
            if nd["cooling_s"] and not nd["blocked"]:                      # a clock hand: it is resting
                ang = -math.pi / 2 + (self.t * 0.4) % math.tau
                p.setPen(QPen(qc("warn", 220), 1.6, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(pt, QPointF(pt.x() + math.cos(ang) * nr * 0.72, pt.y() + math.sin(ang) * nr * 0.72))
            # label, outward of the node
            label = nd["family"] + (f"  x{len(nd['models'])}" if len(nd["models"]) > 1 else "")
            gap = nr + 12
            x0 = pt.x() - gap - 130 if side < 0 else pt.x() + gap
            al = Qt.AlignRight if side < 0 else Qt.AlignLeft
            p.setFont(QFont(self.ui, 9, QFont.DemiBold))
            p.setPen(qc("text" if not (dim or nd["blocked"]) else "dim"))
            p.drawText(QRectF(x0, pt.y() - 17, 130, 16), al | Qt.AlignVCenter, label)
            sub, subcol = "", "dim"
            if nd["cooling_s"]:
                sub, subcol = f"resting {nd['cooling_s'] // 60 + 1}m", "warn"
            elif nd["blocked"]:
                sub = "blocked by data class"
            elif nd["pressure"] >= 0.9:
                sub, subcol = f"{nd['pressure'] * 100:.0f}% spent", "bad"
            elif nd["pressure"] >= 0.6:
                sub, subcol = f"{nd['pressure'] * 100:.0f}% spent", "warn"
            elif active:
                sub, subcol = "calling...", "accent"
            if sub:
                p.setFont(QFont(self.ui, 8)); p.setPen(qc(subcol))
                p.drawText(QRectF(x0, pt.y() - 1, 130, 14), al | Qt.AlignVCenter, sub)
            self._hit.append((nd["family"], pt, nr, self._tip(nd)))

    def _glow_text(self, p, rect, text, col, flags, a=255):
        c = QColor(col)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.setPen(QColor(c.red(), c.green(), c.blue(), 38))
            p.drawText(rect.translated(dx, dy), flags, text)
        p.setPen(QColor(c.red(), c.green(), c.blue(), a))
        p.drawText(rect, flags, text)

    def _hud(self, p, g):
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        w, h = g["w"], g["h"]
        cx = g["cx"]
        # corner brackets
        p.setPen(QPen(qc("line2", 150), 1.4)); p.setBrush(Qt.NoBrush)
        L, m = 16, 8
        for sx, sy in ((m, m), (w - m, m), (m, h - m), (w - m, h - m)):
            dx, dy = (L if sx < w / 2 else -L), (L if sy < h / 2 else -L)
            p.drawLine(QPointF(sx, sy), QPointF(sx + dx, sy)); p.drawLine(QPointF(sx, sy), QPointF(sx, sy + dy))
        # wordmark, like the reference's J.A.R.V.I.S.
        f = QFont(self.mono, 10, QFont.Bold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 6)
        p.setFont(f)
        self._glow_text(p, QRectF(0, 10, w, 18), "P.R.A.X.I.S.", C["accent"], Qt.AlignCenter, 235)
        key = MODE_COLOR.get(self.mode, "accent")
        f2 = QFont(self.mono, 9, QFont.Bold)
        f2.setLetterSpacing(QFont.AbsoluteSpacing, 4)
        p.setFont(f2)
        self._glow_text(p, QRectF(0, 29, w, 16), self.title, C[key], Qt.AlignCenter, 255)
        if self.subtitle:
            p.setFont(QFont(self.mono, 8)); p.setPen(qc("muted"))
            p.drawText(QRectF(0, 45, w, 13), Qt.AlignCenter, self.subtitle)
        # caption: typed out in a dark box, like the reference
        if self.caption:
            f3 = QFont(self.mono, 10)
            p.setFont(f3)
            fm = QFontMetricsF(f3)
            shown = self.caption_shown
            full_w = min(w * 0.78, fm.horizontalAdvance(self.caption) + 28)
            text = fm.elidedText(shown, Qt.ElideRight, full_w - 28)
            cur = "▌" if (self.cap_t < len(self.caption) / 70.0 or int(self.t * 2) % 2 == 0) else " "
            box = QRectF(cx - full_w / 2, h - 52, full_w, 28)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 215))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QPen(qc(LEVEL_COLOR.get(self.cap_level, "accent"), 120), 1)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            p.setPen(qc("text" if self.cap_level == "info" else LEVEL_COLOR.get(self.cap_level, "text")))
            p.drawText(box.adjusted(14, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, text + cur)
        if self.footer:
            f4 = QFont(self.mono, 8)
            f4.setLetterSpacing(QFont.AbsoluteSpacing, 2)
            p.setFont(f4); p.setPen(qc("dim"))
            p.drawText(QRectF(0, h - 20, w, 14), Qt.AlignCenter, self.footer)
