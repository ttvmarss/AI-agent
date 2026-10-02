"""The PRAXIS core, "The Loom": a galaxy of particles streaming along spiral arms around a bright seed, crossed by three
gimbal rings. Every visual encodes real state:

  arm flow            INWARD while PRAXIS is working (it takes your goal in), still when it needs you, OUTWARD on VERIFIED
  colour / spin       the state: idle, starting, working, needs-you, verified, failed, stopping (STOP collapses it fast)
  PLAN ring (outer)   planning (a comet circles it) -> ready (lit) -> rejected (red)
  ACT ring (middle)   one arc per REAL step, coloured by that step's state; the running step has a comet
  VERIFY ring (inner) one arc per REAL check (green pass, red fail); when the goal verifies it SEALS into a closed green ring
  seed flare          every real event pulses the bright seed and sends a ripple through the galaxy
  particle stream     a call to that provider is in flight RIGHT NOW (View.active_provider, from model.try)
  caption             the latest real event, typed out
  nodes               your AIs: colour = cost class, arc = budget spent, clock = resting, hollow = forbidden by DATA setting
Decoration is allowed; fake data is not: nothing here shows a number that is not measured.
"""
import math
import os
import time

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
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
# how a ring segment looks for each step / check state: (colour, alpha, width)
SEG = {"idle": ((110, 140, 190), 60, 1.3), "pending": ((120, 150, 205), 95, 1.5), "running": ((63, 215, 255), 255, 2.6),
       "waiting": ((255, 184, 74), 255, 2.6), "ran": ((150, 225, 255), 225, 2.3), "verified": ((61, 227, 161), 255, 2.6),
       "denied": ((255, 93, 115), 255, 2.6), "failed": ((255, 93, 115), 255, 2.6), "rolled back": ((255, 184, 74), 150, 2.0)}
REDUCED = bool(os.environ.get("PRAXIS_REDUCE_MOTION"))
RING_NAMES = ("PLAN", "ACT", "VERIFY")
RING_HALF, RING_HEIGHT = P.ring_extent()


class CoreView(QWidget):
    MODE_COLOR = MODE_COLOR

    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 300)
        self.setMouseTracking(True)
        self.ui, self.mono = fonts()
        self.mode, self.progress, self.title, self.subtitle = "starting", 0.0, "STARTING", ""
        self.nodes, self.active, self._hit = [], "", []
        self.pipeline = dict(plan="none", steps=[], checks=[], sealed=False)
        self.t = 0.0
        self.quality = P.Quality()
        self.field = P.Nebula(P.LEVELS[0] if not REDUCED else P.LEVELS[2])
        self.field.dyn.set_mode("starting")
        self.ripples = []             # (t_start, colour_key)
        self._last_ripple = -1.0
        self.caption, self.cap_level, self.cap_t = "", "info", 0.0
        self.footer = ""
        self._sprites, self._aura_cache, self._buf = {}, {}, None
        self._fonts = {}
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
                self.field.pulse(1.4)
                self._ripple("ok", force=True)
            elif mode in ("bad", "stopping"):
                self._ripple("bad" if mode == "bad" else "warn", force=True)
            self.field.dyn.set_mode(mode)
            # calm states do not need 30 fps; saves CPU while you are just reading
            self.timer.setInterval(80 if REDUCED else 33 if mode in ("working", "starting", "stopping", "ok") else 42)
        self.mode, self.progress, self.title, self.subtitle = mode, progress, title, subtitle

    def set_pipeline(self, plan="none", steps=(), checks=(), sealed=False):
        """The real pipeline, for the three rings. plan: none | planning | ready | failed. steps: each step's state.
        checks: True/False per evidence check. sealed: the goal VERIFIED, so the VERIFY ring closes."""
        self.pipeline = dict(plan=plan, steps=list(steps), checks=[bool(c) for c in checks], sealed=bool(sealed))

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
        """A real event happened: flare the seed and send a ripple through the galaxy (rate limited so a burst stays readable)."""
        if self.t - self._last_ripple >= 0.14:
            self.field.pulse(0.8)
        self._ripple(level)

    def _ripple(self, level, force=False):
        if not force and self.t - self._last_ripple < 0.14:
            return
        self._last_ripple = self.t
        self.ripples = (self.ripples + [(self.t, LEVEL_COLOR.get(level, "accent"))])[-6:]

    def ring_states(self, which):
        """The segment states of ring `which`: what the ring is showing right now (also what the tests read)."""
        pl = self.pipeline
        if which == 0:
            return {"planning": ["running"], "ready": ["ran"], "failed": ["failed"]}.get(pl["plan"], [])
        if which == 1:
            return list(pl["steps"])
        if pl["sealed"]:
            return ["verified"]                                       # one closed ring: nothing left to check
        return ["verified" if ok else "failed" for ok in pl["checks"]]

    def legend(self):
        """[(name, text, colour key)] for the three rings: real numbers, shown under the title."""
        pl, st = self.pipeline, self.pipeline["steps"]
        plan = {"planning": ("analysing", "accent"), "ready": ("ready", "accent"), "failed": ("rejected", "bad")}.get(pl["plan"], ("idle", "dim"))
        done = sum(1 for s in st if s in ("verified", "ran"))
        bad = any(s in ("failed", "denied") for s in st)
        act = (f"{done}/{len(st)}" if st else "-", "bad" if bad else "warn" if "waiting" in st else "accent" if st and "running" in st
               else "ok" if st and done == len(st) else "dim")
        ck = pl["checks"]
        if pl["sealed"]:
            ver = ("sealed", "ok")
        else:
            ver = (f"{sum(ck)}/{len(ck)}" if ck else "-", "bad" if (ck and not all(ck)) else "accent" if ck else "dim")
        return [(RING_NAMES[0],) + plan, (RING_NAMES[1],) + act, (RING_NAMES[2],) + ver]

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
        top, bot = 80.0, 58.0
        avail = max(60.0, h - top - bot)
        cx, cy = w / 2.0, top + avail / 2.0
        R = max(24.0, min(avail * 0.5 / RING_HEIGHT, w * 0.5 / (RING_HALF * 1.6)))     # the widest ring must fit the room it has
        nr = max(9.0, min(14.0, avail * 0.05))
        cx += 3.0 * math.sin(self.t * 0.37); cy += 2.5 * math.sin(self.t * 0.51 + 1.3)      # it hovers
        order = list(range(len(self.nodes)))
        left = [i for i in order if self.nodes[i]["cost_class"] <= 1]
        right = [i for i in order if self.nodes[i]["cost_class"] >= 2]
        if len(order) > 1 and (not left or not right):       # one side empty: split evenly instead of a lopsided column
            half = (len(order) + 1) // 2
            left, right = order[:half], order[half:]
        pos = {}
        for side, arr in ((-1, left), (1, right)):
            k = len(arr)
            step = min(58.0, (avail + 30.0) / max(k, 1))
            for j, i in enumerate(arr):
                dy = (j - (k - 1) / 2.0) * step
                u = dy / ((avail + 30.0) / 2.0)
                xoff = R * RING_HALF * 1.04 + nr + 26.0 + min(w * 0.05, 48.0) * (1.0 - u * u)
                x = cx + side * xoff
                if w > 300:
                    x = max(124.0, min(w - 124.0, x))
                pos[i] = (QPointF(x, cy + dy), side)
        return dict(w=w, h=h, cx=cx, cy=cy, R=R, nr=nr, top=top, bot=bot, avail=avail, pos=pos)

    def mouseMoveEvent(self, e):
        g = self._geo()
        self.field.tilt_target = [max(-0.35, min(0.35, (e.position().y() - g["cy"]) / max(g["h"], 1) * 0.8)),
                                  max(-0.5, min(0.5, (e.position().x() - g["cx"]) / max(g["w"], 1) * 1.0))]
        for name, pt, r, tip in self._hit:
            if (e.position() - pt).manhattanLength() < r * 1.6:
                QToolTip.showText(e.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, e):
        g = self._geo()
        if math.hypot(e.position().x() - g["cx"], e.position().y() - g["cy"]) < g["R"] * 1.3:
            self.field.pulse(1.2)
            self._ripple("info", force=True)          # poke it: it answers

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
    def _font(self, family, size, weight=None, spacing=None):
        key = (family, size, weight, spacing)
        f = self._fonts.get(key)
        if f is None:
            f = QFont(family, size) if weight is None else QFont(family, size, weight)
            if spacing:
                f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
            self._fonts[key] = f
        return f

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
        # everything that glows goes into one buffer, which is then bloomed
        if self._buf is None or self._buf.size() != self.size():
            self._buf = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
        buf = self._buf
        buf.fill(Qt.transparent)
        q = QPainter(buf)
        q.setRenderHint(QPainter.Antialiasing)
        q.setRenderHint(QPainter.SmoothPixmapTransform)
        q.setCompositionMode(QPainter.CompositionMode_Plus)
        self._galaxy(q, g, tint, mixv)
        self._streams(q, g)
        self._ripples(q, g)
        q.end()
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        p.drawImage(0, 0, buf)
        if self.quality.level < 2:                                # bloom: two blurred copies added back on top
            small = buf.scaled(max(8, w // 4), max(8, h // 4), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            p.setOpacity(0.9); p.drawImage(QRectF(0, 0, w, h), small)
            tiny = small.scaled(max(4, w // 14), max(4, h // 14), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            p.setOpacity(0.75); p.drawImage(QRectF(0, 0, w, h), tiny)
            p.setOpacity(1.0)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        p.drawPixmap(0, 0, self._overlay(w, h))
        self._nodes(p, g)
        self._hud(p, g)
        p.end()
        if self.quality.record((time.perf_counter() - t0) * 1000.0):
            self.field.resize(self.quality.n)

    def _overlay(self, w, h):
        """Faint horizontal scanlines and a dark vignette: the holographic-display finish. Built once per size."""
        pm = getattr(self, "_ov", None)
        if pm is None or pm.size().width() != w or pm.size().height() != h:
            pm = QPixmap(w, h)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setPen(QPen(QColor(120, 170, 255, 9), 1))
            for y in range(0, h, 3):
                q.drawLine(0, y, w, y)
            vg = QRadialGradient(w / 2.0, h / 2.0, max(w, h) * 0.62)
            vg.setColorAt(0.0, QColor(0, 0, 0, 0)); vg.setColorAt(0.65, QColor(0, 0, 0, 0)); vg.setColorAt(1.0, QColor(0, 0, 0, 120))
            q.setPen(Qt.NoPen); q.setBrush(vg); q.drawRect(0, 0, w, h)
            q.end()
            self._ov = pm
        return pm

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
        """The two-lobed glow (blue above, pink below), rendered ONCE per colour state at half resolution: painting huge
        gradients every frame was most of the frame time."""
        key = (int(R // 4), tuple(int(c // 16) for c in tint), int(mixv * 10))
        pm = self._aura_cache.get(key)
        if pm is None:
            side = int(R * 3.1)
            pm = QPixmap(side, side)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            q.setCompositionMode(QPainter.CompositionMode_Plus)
            q.scale(0.5, 0.5)
            c0 = R * 3.1
            top, bot = P.mix(P.palette_at(0.0), tint, mixv), P.mix(P.palette_at(1.0), tint, mixv)
            q.setPen(Qt.NoPen)
            for oy, col, a in ((-R * 0.45, top, 60), (R * 0.45, bot, 56)):
                rad = R * 2.8
                gr = QRadialGradient(c0, c0 + oy, rad)
                gr.setColorAt(0.0, rgb(col, a)); gr.setColorAt(0.55, rgb(col, a * 0.28)); gr.setColorAt(1.0, rgb(col, 0))
                q.setBrush(gr); q.drawEllipse(QPointF(c0, c0 + oy), rad, rad)
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
        half = R * 3.1
        p.drawPixmap(QRectF(cx - half, cy - half, 2 * half, 2 * half), pm, QRectF(pm.rect()))
        p.setOpacity(1.0)

    def _link_curve(self, g, i):
        pt, side = g["pos"][i]
        cx, cy, R = g["cx"], g["cy"], g["R"]
        vx, vy = pt.x() - cx, pt.y() - cy
        vl = math.hypot(vx, vy) or 1.0
        p0 = (cx + vx / vl * R * 1.22, cy + vy / vl * R * 1.22 * 0.8)
        p2 = (pt.x() - side * g["nr"] * 1.2, pt.y())
        mx, my = (p0[0] + p2[0]) / 2.0, (p0[1] + p2[1]) / 2.0
        nxv, nyv = -vy / vl, vx / vl
        p1 = (mx + nxv * vl * 0.12, my + nyv * vl * 0.12 - 8)
        return p0, p1, p2

    def _is_active(self, nd):
        return bool(self.active) and nd["family"] == self.active.split("/")[0]

    def _orbit_and_links(self, p, g):
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self._hit = []
        for i, nd in enumerate(self.nodes):
            if i not in g["pos"]:
                continue
            active = self._is_active(nd)
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

    def _streams(self, q, g):
        """Particles carrying a request from the galaxy to the provider being called right now (drawn into the bloom buffer)."""
        for i, nd in enumerate(self.nodes):
            if i not in g["pos"] or not self._is_active(nd):
                continue
            base = QColor(C[COST_COLOR.get(nd["cost_class"], "accent")])
            p0, p1, p2 = self._link_curve(g, i)
            q.setPen(Qt.NoPen)
            for x, y, a, s, u in P.courier(self.t, p0, p1, p2):
                q.setBrush(QColor(base.red(), base.green(), base.blue(), int(235 * a)))
                q.drawEllipse(QPointF(x, y), s, s)
                q.setBrush(QColor(255, 255, 255, int(150 * a)))
                q.drawEllipse(QPointF(x, y), s * 0.45, s * 0.45)

    # ---- the galaxy, the rings, the seed ---------------------------------------------------------------------------------
    def _galaxy(self, q, g, tint, mixv):
        cx, cy, R = g["cx"], g["cy"], g["R"]
        f = self.field
        bright = f.dyn.v["bright"]
        sz = max(0.75, min(1.35, R / 105.0))
        buckets, sparks = f.project(cx, cy, R, QPointF)
        cols = [P.mix(P.bucket_colour(b), tint, mixv * (0.35 if b == P.BUCKETS else 1.0)) for b in range(P.NB)]
        widths = (1.15 * sz, 1.65 * sz, 2.25 * sz)
        alphas = (85, 150, 235)
        lum_gain = (0.45, 0.95, 1.35)             # faded / ordinary / on the arm's centre

        def layer(depth):
            for b in range(P.NB):
                for v in range(P.VARIANTS):
                    pts = buckets[(b * 3 + depth) * P.VARIANTS + v]
                    if pts:
                        pen = QPen(rgb(cols[b], alphas[depth] * bright * lum_gain[v]), widths[depth] * (0.85 + 0.15 * v))
                        pen.setCapStyle(Qt.RoundCap)
                        q.setPen(pen)
                        q.drawPoints(QPolygonF(pts))

        rings = [f.ring(k, cx, cy, R) for k in range(3)]
        layer(0)
        for k in range(3):
            self._draw_ring(q, g, k, rings[k], back=True, tint=tint)
        layer(1)
        self._seed(q, g, tint, mixv)
        layer(2)
        for x, y, z, i in sparks:                  # warm gold / white / ice sparks that twinkle
            a = f.sparkle_alpha(i)
            s = (9 + 13 * a) * sz * (0.8 + 0.4 * z)
            q.setOpacity(min(1.0, 0.1 + 0.8 * a) * (0.4 + 0.6 * z))
            q.drawPixmap(QRectF(x - s / 2, y - s / 2, s, s), self._glow(f.shue[i], 40), QRectF(0, 0, 40, 40))
        q.setOpacity(1.0)
        q.setPen(Qt.NoPen)
        for tail in f.comets(cx, cy, R):           # comets: a bright head and a fading trail along the arm
            for x, y, a, s in tail:
                if a > 0.02:
                    q.setBrush(rgb(P.mix((255, 255, 255), tint, 0.3 + 0.5 * mixv), 215 * a * bright))
                    q.drawEllipse(QPointF(x, y), s * sz, s * sz)
        for k in range(3):
            self._draw_ring(q, g, k, rings[k], back=False, tint=tint)

    def _seed(self, q, g, tint, mixv):
        """The bright heart: a glow, a lens-flare cross and an anamorphic streak that swell with every real event."""
        cx, cy, R = g["cx"], g["cy"], g["R"]
        fl = self.field.flare
        col = P.mix(P.SEED_WHITE, tint, 0.45 * mixv)
        rad = R * (0.21 + 0.20 * fl) * (0.92 + 0.08 * math.sin(self.t * 2.1))
        gr = QRadialGradient(cx, cy, rad)
        gr.setColorAt(0.0, rgb((255, 255, 255), 255)); gr.setColorAt(0.10, rgb(col, 215)); gr.setColorAt(0.42, rgb(col, 55)); gr.setColorAt(1.0, rgb(col, 0))
        q.setPen(Qt.NoPen); q.setBrush(gr)
        q.drawEllipse(QPointF(cx, cy), rad, rad)
        L = R * (0.55 + 1.3 * fl)                                   # anamorphic horizontal streak
        sg = QLinearGradient(cx - L, cy, cx + L, cy)
        sg.setColorAt(0.0, rgb(col, 0)); sg.setColorAt(0.5, rgb(col, 95 + 140 * min(1, fl))); sg.setColorAt(1.0, rgb(col, 0))
        q.setBrush(sg)
        q.drawRect(QRectF(cx - L, cy - 1.1, 2 * L, 2.2))
        V = R * (0.2 + 0.4 * fl)                                  # and a short vertical flare
        vg = QLinearGradient(cx, cy - V, cx, cy + V)
        vg.setColorAt(0.0, rgb(col, 0)); vg.setColorAt(0.5, rgb(col, 130)); vg.setColorAt(1.0, rgb(col, 0))
        q.setBrush(vg)
        q.drawRect(QRectF(cx - 0.9, cy - V, 1.8, 2 * V))

    def _draw_ring(self, q, g, which, pts, back, tint):
        """One gimbal ring. Its segments are the REAL steps / checks; the front and back halves are drawn on either side of
        the galaxy plane so the ring really weaves through it."""
        states = self.ring_states(which)
        segs = len(states)
        n = len(pts)
        groups = {}
        for x, y, z, i in pts:
            if (z < 0) != back:
                continue
            if segs == 0:
                st = "idle"
            else:
                sg = P.segment_of(i, n, segs)
                if sg is None:
                    continue
                st = states[sg[0]]
            groups.setdefault(st, []).append(QPointF(x, y))
        depth_gain = 0.55 if back else 1.0
        pulse = 0.65 + 0.35 * math.sin(self.t * 6.0)
        for st, plist in groups.items():
            colour, alpha, width = SEG.get(st, SEG["idle"])
            a = alpha * depth_gain * (pulse if st == "waiting" else 1.0)
            pen = QPen(rgb(P.mix(colour, tint, 0.15), a), width * (1.0 if self.pipeline["sealed"] and which == 2 else 0.92))
            pen.setCapStyle(Qt.RoundCap)
            q.setPen(pen)
            q.drawPoints(QPolygonF(plist))
        if back or segs == 0:
            return
        by_i = {i: (x, y, z) for x, y, z, i in pts}
        if which == 2 and self.pipeline["sealed"]:               # sealed: a highlight keeps circling the closed green ring
            head = int((self.t * 0.45) % 1.0 * n) % n
            for j in range(14):
                x, y, z = by_i[(head - j) % n]
                if z >= 0:
                    a = (1.0 - j / 14.0) ** 1.4
                    q.setPen(Qt.NoPen); q.setBrush(rgb((255, 255, 255) if j == 0 else SEG["verified"][0], 235 * a))
                    q.drawEllipse(QPointF(x, y), 3.0 * (1 - 0.5 * j / 14.0), 3.0 * (1 - 0.5 * j / 14.0))
        if segs > 1:                                             # a bright bead at both ends of every arc: the segments read as separate
            q.setPen(Qt.NoPen)
            for s_i, st in enumerate(states):
                colour, alpha, _ = SEG.get(st, SEG["idle"])
                for end in (0.0, 1.0 - P.GAP - 0.02):
                    i0 = int((s_i + end) * n / segs) % n
                    x, y, z = by_i.get(i0, (0, 0, -1))
                    if z >= 0:
                        q.setBrush(rgb(colour, alpha * 0.9)); q.drawEllipse(QPointF(x, y), 2.3, 2.3)
        for s, st in enumerate(states):                          # comets on running segments: the work happening right now
            if st != "running":
                continue
            frac = (self.t * 0.75 + s * 0.31) % 1.0
            head = int((s + frac * (1.0 - P.GAP)) * n / segs) % n
            for j in range(11):
                x, y, z = by_i[(head - j) % n]
                if z < 0:
                    continue
                a = (1.0 - j / 11.0) ** 1.5
                q.setPen(Qt.NoPen); q.setBrush(rgb((255, 255, 255) if j == 0 else SEG["running"][0], 230 * a))
                q.drawEllipse(QPointF(x, y), 3.2 * (1 - 0.6 * j / 11.0), 3.2 * (1 - 0.6 * j / 11.0))

    def _ripples(self, q, g):
        q.setBrush(Qt.NoBrush)
        ratio = abs(math.cos(P.CAM_TILT + self.field.tilt[0])) * 0.9 + 0.1
        for t0, key in self.ripples:
            u = (self.t - t0) / 1.6
            if not 0 <= u <= 1:
                continue
            col = QColor(C[key])
            r = g["R"] * (0.5 + 2.0 * (1 - (1 - u) ** 2))
            a = int(210 * (1 - u) ** 1.6)
            q.setPen(QPen(QColor(col.red(), col.green(), col.blue(), a), 2.4 * (1 - u) + 0.6))
            q.drawEllipse(QPointF(g["cx"], g["cy"]), r, r * ratio)

    # ---- nodes, HUD ----------------------------------------------------------------------------------------------------------
    def _nodes(self, p, g):
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        nr = g["nr"]
        for i, nd in enumerate(self.nodes):
            if i not in g["pos"]:
                continue
            pt, side = g["pos"][i]
            active = self._is_active(nd)
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
            label = nd["family"] + (f"  x{len(nd['models'])}" if len(nd["models"]) > 1 else "")
            gap = nr + 12
            x0 = pt.x() - gap - 130 if side < 0 else pt.x() + gap
            al = Qt.AlignRight if side < 0 else Qt.AlignLeft
            p.setFont(self._font(self.ui, 9, QFont.DemiBold))
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
                p.setFont(self._font(self.ui, 8)); p.setPen(qc(subcol))
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
        p.setPen(QPen(qc("line2", 150), 1.4)); p.setBrush(Qt.NoBrush)      # corner brackets
        L, m = 16, 8
        for sx, sy in ((m, m), (w - m, m), (m, h - m), (w - m, h - m)):
            dx, dy = (L if sx < w / 2 else -L), (L if sy < h / 2 else -L)
            p.drawLine(QPointF(sx, sy), QPointF(sx + dx, sy)); p.drawLine(QPointF(sx, sy), QPointF(sx, sy + dy))
        p.setFont(self._font(self.mono, 10, QFont.Bold, 6))                  # wordmark, like the reference's J.A.R.V.I.S.
        self._glow_text(p, QRectF(0, 10, w, 18), "P.R.A.X.I.S.", C["accent"], Qt.AlignCenter, 235)
        key = MODE_COLOR.get(self.mode, "accent")
        p.setFont(self._font(self.mono, 9, QFont.Bold, 4))
        self._glow_text(p, QRectF(0, 29, w, 16), self.title, C[key], Qt.AlignCenter, 255)
        if self.subtitle:
            p.setFont(self._font(self.mono, 8)); p.setPen(qc("muted"))
            p.drawText(QRectF(0, 45, w, 13), Qt.AlignCenter, self.subtitle)
        # the pipeline legend: the three rings, with real numbers
        lf = self._font(self.mono, 8, QFont.Bold, 1.5)
        p.setFont(lf)
        fm = QFontMetricsF(lf)
        items = self.legend()
        widths = [14 + fm.horizontalAdvance(f"{n} {t}") + 18 for n, t, _ in items]
        x = cx - sum(widths) / 2.0
        p.setPen(Qt.NoPen); p.setBrush(QColor(3, 8, 14, 150))
        p.drawRoundedRect(QRectF(x - 8, 60, sum(widths) + 12, 18), 9, 9)
        for (name, text, key), wd in zip(items, widths):
            col = QColor(C[key])
            p.setPen(Qt.NoPen); p.setBrush(QColor(col.red(), col.green(), col.blue(), 235 if key != "dim" else 110))
            p.drawEllipse(QPointF(x + 5, 69), 3.2, 3.2)
            p.setPen(qc("muted")); p.drawText(QRectF(x + 14, 62, 60, 14), Qt.AlignVCenter | Qt.AlignLeft, name)
            p.setPen(QColor(col.red(), col.green(), col.blue(), 255 if key != "dim" else 130))
            p.drawText(QRectF(x + 14 + fm.horizontalAdvance(name) + 6, 62, 90, 14), Qt.AlignVCenter | Qt.AlignLeft, text)
            x += wd
        if self.caption:                                                     # caption: typed out in a dark box, like the reference
            f3 = self._font(self.mono, 10)
            p.setFont(f3)
            fm3 = QFontMetricsF(f3)
            shown = self.caption_shown
            full_w = min(w * 0.78, fm3.horizontalAdvance(self.caption) + 28)
            text = fm3.elidedText(shown, Qt.ElideRight, full_w - 28)
            cur = "▌" if (self.cap_t < len(self.caption) / 70.0 or int(self.t * 2) % 2 == 0) else " "
            box = QRectF(cx - full_w / 2, h - 52, full_w, 28)
            p.setPen(Qt.NoPen); p.setBrush(QColor(0, 0, 0, 215))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QPen(qc(LEVEL_COLOR.get(self.cap_level, "accent"), 120), 1)); p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 6, 6)
            p.setPen(qc("text" if self.cap_level == "info" else LEVEL_COLOR.get(self.cap_level, "text")))
            p.drawText(box.adjusted(14, 0, -10, 0), Qt.AlignVCenter | Qt.AlignLeft, text + cur)
        if self.footer:
            p.setFont(self._font(self.mono, 8, None, 2)); p.setPen(qc("dim"))
            p.drawText(QRectF(0, h - 20, w, 14), Qt.AlignCenter, self.footer)
