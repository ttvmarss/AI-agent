"""The PRAXIS core, "The Reactor": an arc reactor in its housing, ringed by flat HUD gauge rings, in gold and gunmetal. Every visual
encodes real state:

  coil spin / charge   how hard it is working: idle ticks over, working spins up and chases light round the coils, STOP spins it down
  core colour          the state: reactor blue, working bright blue, needs-you orange, verified gold-white, failed red
  PLAN ring (outer)    planning (a comet circles it) -> ready (lit) -> rejected (red)
  ACT ring (middle)    one arc per REAL step, coloured by that step's state; the running step has a comet
  VERIFY ring (inner)  one arc per REAL check (green pass, red fail); when the goal verifies it SEALS into a closed green ring
  core flare / ripple  every real event flares the core and sends a ring outward; VERIFIED sends a big gold shockwave
  voice ring           a radial equaliser of the REAL audio: yours while it listens, its own while it speaks
  links                a call to that provider is in flight RIGHT NOW (View.active_provider, from model.try)
  caption              the latest real event, typed out
  nodes                your AIs: colour = cost class, arc = budget spent, clock = resting, dashed = forbidden by DATA setting
Decoration is allowed; fake data is not: nothing here shows a number that is not measured.
"""
import math
import os
import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QFont, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap, QPolygonF, QRadialGradient)
from PySide6.QtWidgets import QToolTip, QWidget

from . import reactor as RX
from .theme import C, COST_COLOR, COST_NAME, PRIVACY_NAME, fonts, qc


def pressure_color(x):
    return "ok" if x < 0.6 else "warn" if x < 0.9 else "bad"


def fin(x, lo, hi, default=0.0):
    """A number the painter can trust: finite and inside [lo, hi]. A NaN or infinity reaching Qt geometry is a hard crash
    (found by the stress campaign), so everything that arrives from outside the widget is passed through here."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return max(lo, min(hi, x))


def rgb(c, a=255):
    return QColor(int(max(0, min(255, c[0]))), int(max(0, min(255, c[1]))), int(max(0, min(255, c[2]))), int(max(0, min(255, a))))


LEVEL_COLOR = {"info": "accent", "ok": "ok", "warn": "warn", "bad": "bad", "muted": "muted"}
MODE_COLOR = {"idle": "accent", "starting": "muted", "working": "accent", "waiting": "warn", "ok": "ok", "bad": "bad",
              "stopping": "warn", "stopped": "warn"}
# how a ring segment looks for each step / check state: (colour, alpha, width)
SEG = {"idle": ((120, 135, 152), 70, 1.4), "pending": ((140, 155, 172), 120, 1.8), "running": ((110, 214, 255), 245, 3.0),
       "waiting": ((255, 159, 67), 255, 3.2), "ran": ((150, 200, 225), 175, 2.6), "verified": ((61, 227, 161), 235, 3.0),
       "denied": ((255, 74, 61), 255, 3.2), "failed": ((255, 74, 61), 255, 3.2), "rolled back": ((255, 159, 67), 170, 2.4)}
REDUCED = bool(os.environ.get("PRAXIS_REDUCE_MOTION"))
RING_NAMES = ("PLAN", "ACT", "VERIFY")
RING_KEYS = ("plan", "act", "verify")
VOICE_BARS = 96
VOICE_TAG = {"listening": "LISTENING", "hearing": "HEARING", "thinking": "THINKING",
             "speaking": "SPEAKING", "muted": "MIC OFF  ·  F4", "offline": "NO MICROPHONE"}
VOICE_COLOR = {"listening": "accent", "hearing": "accent", "thinking": "violet", "speaking": "ok", "muted": "warn", "offline": "bad"}
EXTENT = RX.EXTENT
DISPLAY = {"droid": "droid \u00b7 factory", "devin": "devin", "claude": "claude", "codex": "codex", "ollama": "ollama"}   # how a brain is named on screen
GOLD, GOLD_B, STEEL = RX.GOLD, RX.GOLD_BRIGHT, RX.STEEL
HEX = 34.0                                             # edge length of the armour-plate hexagons behind the dial


class CoreView(QWidget):
    MODE_COLOR = MODE_COLOR

    def __init__(self):
        super().__init__()
        self.setMinimumSize(560, 300)
        self.setMouseTracking(True)
        self.ui, self.mono = fonts()
        self.mode, self.progress, self.title, self.subtitle = "starting", 0.0, "STARTING", ""
        self.nodes, self.active, self._hit, self._hover = [], "", [], ""
        self.pipeline = dict(plan="none", steps=[], checks=[], sealed=False)
        self.t = 0.0
        self.quality = RX.Quality()
        self.reactor = RX.Reactor(RX.LEVELS[0] if not REDUCED else RX.LEVELS[2])
        self.reactor.dyn.set_mode("starting")
        self.ripples = []             # (t_start, colour_key)
        self._last_ripple = -1.0
        self.caption, self.cap_level, self.cap_t = "", "info", 0.0
        self.footer = ""
        self._buf, self._fonts, self._glow_cache, self._bg = None, {}, {}, None
        self.voice = dict(state="off", level=0.0, speak=0.0, attentive=False)
        self._vhist, self._vacc = [0.0] * VOICE_BARS, 0.0
        self._poke = 0.0
        self.log = deque(maxlen=6)    # (wall clock, text, level): the real event feed shown bottom-left
        self.stats = {}               # real numbers for the readout bottom-right: label -> value
        self._hex = None
        self._last = time.perf_counter()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(80 if REDUCED else 33)

    def dispose(self):
        """Stop animating and drop the timer's reference to this widget (call from the main thread before it is deleted)."""
        self.timer.stop()
        try:
            self.timer.timeout.disconnect()
        except (TypeError, RuntimeError):
            pass

    # ---- the API the window uses ---------------------------------------------------------------------------------
    def set_state(self, mode, progress, title, subtitle=""):
        if mode != self.mode:
            if mode == "starting":
                self.reactor.restart_power_up()
            elif mode == "ok":
                self.reactor.trigger_shock()
                self.reactor.pulse(1.4)
                self._ripple("ok", force=True)
            elif mode in ("bad", "stopping"):
                self._ripple("bad" if mode == "bad" else "warn", force=True)
            self.reactor.dyn.set_mode(mode)
            # calm states do not need 30 fps; saves CPU while you are just reading
            self.timer.setInterval(80 if REDUCED else 33 if mode in ("working", "starting", "stopping", "ok") else 42)
        self.mode, self.progress, self.title, self.subtitle = mode, fin(progress, 0.0, 1.0), str(title), str(subtitle)

    def set_pipeline(self, plan="none", steps=(), checks=(), sealed=False):
        """The real pipeline, for the three rings. plan: none | planning | ready | failed. steps: each step's state.
        checks: True/False per evidence check. sealed: the goal VERIFIED, so the VERIFY ring closes."""
        self.pipeline = dict(plan=plan, steps=list(steps), checks=[bool(c) for c in checks], sealed=bool(sealed))

    def set_voice(self, state, level=0.0, speak=0.0, attentive=False):
        """The voice loop's real state: `level` is the live microphone loudness, `speak` the loudness of PRAXIS's own voice."""
        self.voice = dict(state=state, level=fin(level, 0.0, 10.0), speak=fin(speak, 0.0, 10.0), attentive=bool(attentive))

    def voice_amplitude(self):
        """What the voice ring should show right now, 0..1, from the real audio (never invented)."""
        v = self.voice
        if v["state"] == "speaking":
            return min(1.0, v["speak"])
        if v["state"] in ("hearing", "listening"):
            return min(1.0, (v["level"] / 0.12) ** 0.6) if v["level"] > 0 else 0.0
        return 0.0

    def set_nodes(self, nodes):
        clean = []
        for n in nodes:
            n = dict(n)
            n["pressure"] = fin(n.get("pressure"), 0.0, 1.0)
            n["cooling_s"] = int(fin(n.get("cooling_s"), 0, 10 ** 7))
            clean.append(n)
        self.nodes = clean

    def set_active(self, name):
        self.active = name

    def set_caption(self, text, level="info"):
        """The latest message. It is no longer drawn as a box on the dial (removed on request); warnings and errors are written to the
        event feed instead, so a setup problem is never invisible."""
        if text != self.caption:
            self.caption, self.cap_level, self.cap_t = text, level, 0.0
            if level in ("warn", "bad") and text:
                self.add_log(text, level)

    @property
    def caption_shown(self):
        """The part of the caption typed out so far (70 characters per second)."""
        return self.caption[:max(0, int(self.cap_t * 70))]

    def set_footer(self, text):
        self.footer = text

    def add_log(self, text, level="info", stamp=None):
        """One line for the event feed (real events only). Immediate repeats are collapsed."""
        text = str(text or "").strip()
        if not text or (self.log and self.log[-1][1] == text):
            return
        self.log.append((stamp or time.strftime("%H:%M:%S"), text[:90], level))

    def set_stats(self, stats):
        """Real numbers for the readout (elapsed, steps, checks, which brain is thinking). Pass {} to clear it."""
        self.stats = {str(k): str(v) for k, v in dict(stats or {}).items()}

    def pulse(self, level="info"):
        """A real event happened: flare the core and send a ripple outward (rate limited so a burst stays readable)."""
        if self.t - self._last_ripple >= 0.14:
            self.reactor.pulse(0.8)
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
        dt = fin(dt, 0.0, 0.25, 0.0)                      # NaN, negative or a long stall (laptop lid) must not poison the simulation
        if dt <= 0.0:
            return
        self.t = (self.t + dt) % 100000.0
        self.reactor.advance(dt * (0.2 if REDUCED else 1.0))
        self.cap_t += dt
        self._poke = max(0.0, self._poke - dt * 2.0)
        self._vacc += dt
        while self._vacc >= 1 / 30:                       # the voice ring is a short history of the real audio level
            self._vacc -= 1 / 30
            self._vhist = self._vhist[1:] + [self._vhist[-1] * 0.55 + self.voice_amplitude() * 0.45]
        if self.voice["state"] == "speaking":
            self.reactor.flare = max(self.reactor.flare, 0.5 * min(1.0, self.voice["speak"]))     # the core pulses with its voice
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
        top, bot = 84.0, 58.0
        avail = max(60.0, h - top - bot)
        cx, cy = w / 2.0, top + avail / 2.0
        R = max(24.0, min(avail * 0.5 / (EXTENT * 1.04), w * 0.5 / (EXTENT * 1.55)))     # the whole dial must fit the room it has
        nr = max(9.0, min(14.0, avail * 0.05))
        cy += 1.5 * math.sin(self.t * 0.51 + 1.3)                                          # it hovers, a little
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
                xoff = R * EXTENT * 1.06 + nr + 26.0 + min(w * 0.05, 48.0) * (1.0 - u * u)
                x = cx + side * xoff
                if w > 300:
                    x = max(124.0, min(w - 124.0, x))
                pos[i] = (QPointF(x, cy + dy), side)
        return dict(w=w, h=h, cx=cx, cy=cy, R=R, nr=nr, top=top, bot=bot, avail=avail, pos=pos)

    def mouseMoveEvent(self, e):
        self._hover = ""
        for name, pt, r, tip in self._hit:
            if (e.position() - pt).manhattanLength() < r * 1.6:
                self._hover = name
                QToolTip.showText(e.globalPosition().toPoint(), tip, self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, e):
        g = self._geo()
        if math.hypot(e.position().x() - g["cx"], e.position().y() - g["cy"]) < g["R"] * 1.2:
            self.reactor.pulse(1.2)
            self._poke = 1.0
            self._ripple("info", force=True)          # poke it: it answers

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

    def paintEvent(self, e):
        t0 = time.perf_counter()
        w, h = self.width(), self.height()
        if w < 80 or h < 80:
            return
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            g = self._geo()
            tint, mixv = self.reactor.tint_colour()
            self._background(p, g)
            self._hex_waves(p, g, tint)
            self._aura(p, g, tint, mixv)
            self._decor(p, g, tint)
            self._scale(p, g)
            self._sweep(p, g, tint)
            self._links(p, g)
            self._housing(p, g, tint, mixv)
            # everything that glows goes into one buffer, which is then bloomed
            if self._buf is None or self._buf.size() != self.size():
                self._buf = QImage(self.size(), QImage.Format_ARGB32_Premultiplied)
            buf = self._buf
            buf.fill(Qt.transparent)
            q = QPainter(buf)
            try:
                q.setRenderHint(QPainter.Antialiasing)
                q.setCompositionMode(QPainter.CompositionMode_Plus)
                self._rings(q, g, tint)
                self._voice_ring(q, g)
                self._coils_lit(q, g, tint, mixv)
                self._flow(q, g, tint, mixv)
                self._core(q, g, tint, mixv)
                self._bolts(q, g, tint, mixv)
                self._ripples(q, g)
                self._streams(q, g)
                self._embers(q, g)
            finally:
                q.end()
            p.setCompositionMode(QPainter.CompositionMode_Plus)
            p.drawImage(0, 0, buf)
            if self.quality.level < 2:                                # bloom: two blurred copies added back on top
                small = buf.scaled(max(8, w // 4), max(8, h // 4), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                p.setOpacity(0.55); p.drawImage(QRectF(0, 0, w, h), small)
                tiny = small.scaled(max(4, w // 14), max(4, h // 14), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                p.setOpacity(0.42); p.drawImage(QRectF(0, 0, w, h), tiny)
            p.setOpacity(1.0)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            self._nodes(p, g)
            self._panels(p, g)
            self._hud(p, g)
        finally:
            if p.isActive():
                p.end()      # a bug while painting must never leave a painter open: that is a hard crash, not an error
        if self.quality.record((time.perf_counter() - t0) * 1000.0):
            self.reactor.set_level(self.quality.level)

    # -- background: gunmetal with a faint hex-plate pattern, never a stage set --
    def _background(self, p, g):
        w, h = g["w"], g["h"]
        pm = self._bg
        if pm is None or pm.width() != w or pm.height() != h:
            pm = QPixmap(w, h)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            base = QLinearGradient(0, 0, 0, h)
            base.setColorAt(0.0, QColor(13, 17, 23)); base.setColorAt(0.55, QColor(9, 12, 17)); base.setColorAt(1.0, QColor(5, 7, 10))
            q.fillRect(QRectF(0, 0, w, h), base)
            s = HEX
            q.setPen(QPen(QColor(120, 135, 152, 16), 1))
            for x, y in RX.hex_centers(w, h, s):
                pts = [QPointF(x + math.cos(math.radians(60 * k)) * s, y + math.sin(math.radians(60 * k)) * s) for k in range(6)]
                q.drawPolyline(QPolygonF(pts[:4]))
            vg = QRadialGradient(w / 2.0, h / 2.0, max(w, h) * 0.65)
            vg.setColorAt(0.0, QColor(0, 0, 0, 0)); vg.setColorAt(0.6, QColor(0, 0, 0, 40)); vg.setColorAt(1.0, QColor(0, 0, 0, 170))
            q.setPen(Qt.NoPen); q.setBrush(vg); q.drawRect(0, 0, w, h)
            q.end()
            self._bg = pm
        p.drawPixmap(0, 0, pm)

    # -- hexagon waves: every real event, and a slow ambient pulse, lights the armour plates in a ring that travels outward --
    def _hex_waves(self, p, g, tint):
        w, h, cx, cy, R = g["w"], g["h"], g["cx"], g["cy"], g["R"]
        if self._hex is None or self._hex[0] != (w, h):
            self._hex = ((w, h), RX.hex_centers(w, h, HEX))
        cells = self._hex[1]
        waves = []
        for t0, key in self.ripples:
            u = (self.t - t0) / 1.6
            if 0 <= u <= 1:
                waves.append((R * (0.9 + 2.6 * RX.ease_out(u)), (1 - u) ** 1.3, QColor(C[key])))
        sh = self.reactor.shock
        if sh is not None:
            waves.append((R * (0.9 + 3.4 * RX.ease_out(sh)), (1 - sh) ** 1.2 * 1.3, rgb(GOLD_B)))
        if not REDUCED:
            u = (self.t % 8.0) / 3.0                                         # the ambient pulse: a faint ring every 8 seconds
            if u <= 1:
                waves.append((R * (0.9 + 2.6 * RX.ease_out(u)), (1 - u) * 0.45, rgb(tint)))
        if not waves:
            return
        p.setBrush(Qt.NoBrush)
        s = HEX
        for radius, strength, col in waves:
            for i, k in RX.hex_wave(cells, cx, cy, radius, R * 0.32):
                x, y = cells[i]
                a = int(62 * strength * k)
                if a <= 2:
                    continue
                p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), a), 1.2))
                p.drawPolygon(QPolygonF([QPointF(x + math.cos(math.radians(60 * j)) * s * 0.92, y + math.sin(math.radians(60 * j)) * s * 0.92) for j in range(6)]))

    # -- decorative HUD circles between and around the real rings (dim, so the real data always reads first) --
    def _decor(self, p, g, tint):
        cx, cy, R = g["cx"], g["cy"], g["R"]
        t = self.t
        p.setBrush(Qt.NoBrush)
        rev = self.reactor.reveal
        specs = (
            (RX.DECOR_R[0], 4, (STEEL, 55), [7, 5], 14.0),          # dashed, clockwise
            (RX.DECOR_R[1], 3, (GOLD, 52), [1, 5], -9.0),           # dotted, counter-clockwise
            (RX.DECOR_R[2], 2, (STEEL, 42), [18, 6], 6.0),          # long dashes, slow
        )
        for k, (r, order, (col, alpha), dashes, speed) in enumerate(specs):
            f = rev(order)
            if f <= 0.01:
                continue
            pen = QPen(rgb(col, alpha * f), 1.4)
            pen.setDashPattern(dashes)
            pen.setDashOffset(-t * speed * (0.4 if REDUCED else 1.0))
            p.setPen(pen)
            rr = r * R
            box = QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr)
            if f < 0.999:
                p.drawArc(box, 90 * 16, int(-360 * f * 16))
            else:
                p.drawEllipse(QPointF(cx, cy), rr, rr)
        f = rev(5)
        if f > 0.01:                                                  # three bright data arcs turning round the outside
            rr = RX.DECOR_R[3] * R
            box = QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr)
            p.setPen(QPen(rgb(GOLD, 120 * f), 2.2, Qt.SolidLine, Qt.FlatCap))
            rot = math.degrees(self.reactor.tick_rot) * 3.0
            for k in range(3):
                p.drawArc(box, int((90 - rot - 120 * k) * 16), int(-26 * 16))

    # -- the radar sweep: a bright edge with a fading trail, going round the dial --
    def _sweep(self, p, g, tint):
        cx, cy, R = g["cx"], g["cy"], g["R"]
        f = self.reactor.reveal(4)
        if f <= 0.01:
            return
        ang = -math.degrees(self.reactor.sweep_rot) + 90
        r0, r1 = RX.VOICE_OUT * R * 1.04, RX.DECOR_R[0] * R * 1.04
        cg = QConicalGradient(cx, cy, ang)
        col = rgb(RX.mix(RX.BLUE, tint, 0.5))
        c0 = QColor(col); c0.setAlpha(int(120 * f))
        c1 = QColor(col); c1.setAlpha(0)
        cg.setColorAt(0.0, c0); cg.setColorAt(0.11, c1); cg.setColorAt(1.0, c1)
        band = QPainterPath()
        band.addEllipse(QPointF(cx, cy), r1, r1)
        band.addEllipse(QPointF(cx, cy), r0, r0)
        p.setPen(Qt.NoPen); p.setBrush(cg); p.drawPath(band)
        p.setPen(QPen(rgb(RX.mix(col.getRgb()[:3], RX.WHITE, 0.4), 170 * f), 1.6))
        p.drawLine(QPointF(cx + math.cos(math.radians(ang)) * r0, cy - math.sin(math.radians(ang)) * r0),
                   QPointF(cx + math.cos(math.radians(ang)) * r1, cy - math.sin(math.radians(ang)) * r1))

    def _aura(self, p, g, tint, mixv):
        """A soft glow behind the reactor in the state's colour (cached per colour state)."""
        R = g["R"]
        key = (int(R // 6), tuple(int(c // 24) for c in tint), int(mixv * 10))
        pm = self._glow_cache.get(key)
        if pm is None:
            side = int(R * 4.6)
            pm = QPixmap(side, side)
            pm.fill(Qt.transparent)
            q = QPainter(pm)
            q.setRenderHint(QPainter.Antialiasing)
            col = RX.mix(RX.BLUE, tint, mixv)
            gr = QRadialGradient(side / 2.0, side / 2.0, side / 2.0)
            gr.setColorAt(0.0, rgb(col, 70)); gr.setColorAt(0.35, rgb(col, 26)); gr.setColorAt(1.0, rgb(col, 0))
            q.setPen(Qt.NoPen); q.setBrush(gr); q.drawEllipse(QPointF(side / 2.0, side / 2.0), side / 2.0, side / 2.0)
            q.end()
            if len(self._glow_cache) > 12:
                self._glow_cache.pop(next(iter(self._glow_cache)))
            self._glow_cache[key] = pm
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        half = R * 2.3
        p.setOpacity(min(1.0, self.reactor.dyn.v["bright"] * (0.55 + 0.45 * min(1.2, self.reactor.core_level()))))
        p.drawPixmap(QRectF(g["cx"] - half, g["cy"] - half, 2 * half, 2 * half), pm, QRectF(pm.rect()))
        p.setOpacity(1.0)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    # -- the outer gauge scale and the targeting brackets --
    def _scale(self, p, g):
        cx, cy, R = g["cx"], g["cy"], g["R"]
        p.setOpacity(max(0.0, min(1.0, self.reactor.reveal(4))))                       # fades in at the end of the boot sequence
        rot = self.reactor.tick_rot
        r0 = RX.SCALE_R[0] * R
        for ang, kind in RX.ticks(rot):
            ln = (0.10, 0.065, 0.032)[2 - kind] * R
            col = GOLD_B if kind == 2 else STEEL if kind == 1 else (80, 92, 106)
            p.setPen(QPen(rgb(col, 235 if kind == 2 else 150 if kind == 1 else 90), 1.6 if kind == 2 else 1.0))
            ca, sa = math.cos(ang), math.sin(ang)
            p.drawLine(QPointF(cx + ca * r0, cy + sa * r0), QPointF(cx + ca * (r0 + ln), cy + sa * (r0 + ln)))
        p.setPen(QPen(rgb(STEEL, 70), 1.0)); p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r0 - 2, r0 - 2)
        p.setFont(self._font(self.mono, 7, None, 1))
        p.setPen(rgb(GOLD, 170))
        for k, label in enumerate(("000", "090", "180", "270")):          # bearing numerals at the cardinal points, upright
            a = rot + k * math.pi / 2 - math.pi / 2
            x, y = cx + math.cos(a) * (r0 - 14), cy + math.sin(a) * (r0 - 14)
            p.drawText(QRectF(x - 14, y - 6, 28, 12), Qt.AlignCenter, label)
        p.setBrush(rgb(GOLD_B, 235)); p.setPen(Qt.NoPen)                    # the fixed index at the top
        top = cy - (RX.SCALE_R[1] + 0.07) * R
        p.drawPolygon(QPolygonF([QPointF(cx, top + 9), QPointF(cx - 5, top), QPointF(cx + 5, top)]))
        hearing = self.voice["state"] in ("hearing", "speaking")           # targeting brackets: they close in while it listens
        rb = (RX.SCALE_R[1] + (0.04 if hearing else 0.13) + 0.04 * math.sin(self.t * 2.0)) * R
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(rgb(GOLD, 230 if hearing else 120), 2.0 if hearing else 1.4, Qt.SolidLine, Qt.FlatCap))
        box = QRectF(cx - rb, cy - rb, 2 * rb, 2 * rb)
        for k in range(4):
            mid = 45 + 90 * k
            p.drawArc(box, int((mid - 7) * 16), int(14 * 16))
        p.setOpacity(1.0)

    # -- links to the AIs --
    def _link_pts(self, g, i):
        pt, side = g["pos"][i]
        cx, cy, R = g["cx"], g["cy"], g["R"]
        ang = math.atan2(pt.y() - cy, pt.x() - cx)
        p0 = (cx + math.cos(ang) * R * (RX.SCALE_R[1] + 0.2), cy + math.sin(ang) * R * (RX.SCALE_R[1] + 0.2))
        p2 = (pt.x() - side * g["nr"] * 1.3, pt.y())
        elbow = (p2[0] - side * min(48.0, abs(p2[0] - p0[0]) * 0.5), p2[1])
        return [p0, elbow, p2]

    def _is_active(self, nd):
        return bool(self.active) and nd["family"] == self.active.split("/")[0]

    def _links(self, p, g):
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        self._hit = []
        for i, nd in enumerate(self.nodes):
            if i not in g["pos"]:
                continue
            active = self._is_active(nd)
            dim = nd["blocked"] or nd["cooling_s"] > 0
            base = COST_COLOR.get(nd["cost_class"], "accent")
            pts = self._link_pts(g, i)
            path = QPainterPath(QPointF(*pts[0]))
            path.lineTo(QPointF(*pts[1])); path.lineTo(QPointF(*pts[2]))
            pen = QPen(qc(base, 235 if active else (24 if dim else 52)), 2.0 if active else 1.0)
            if nd["blocked"]:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawPath(path)

    # -- the housing: brushed gunmetal with a gold bevel, and the coil bodies --
    def _housing(self, p, g, tint, mixv):
        cx, cy, R = g["cx"], g["cy"], g["R"]
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        ring = QPainterPath()
        ring.addEllipse(QPointF(cx, cy), RX.HOUSING_OUT * R, RX.HOUSING_OUT * R)
        ring.addEllipse(QPointF(cx, cy), RX.HOUSING_IN * R, RX.HOUSING_IN * R)
        cg = QConicalGradient(cx, cy, 35)
        for stop, shade in ((0.0, 70), (0.12, 150), (0.25, 62), (0.4, 128), (0.55, 52), (0.7, 142), (0.85, 60), (1.0, 70)):
            cg.setColorAt(stop, QColor(shade, shade + 6, shade + 14))
        p.setPen(Qt.NoPen); p.setBrush(cg); p.drawPath(ring)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(rgb(GOLD, 230), 2.2)); p.drawEllipse(QPointF(cx, cy), RX.HOUSING_OUT * R, RX.HOUSING_OUT * R)      # the gold bevel
        p.setPen(QPen(rgb(GOLD, 70), 1.0)); p.drawEllipse(QPointF(cx, cy), RX.HOUSING_IN * R, RX.HOUSING_IN * R)
        p.setPen(Qt.NoPen); p.setBrush(QColor(20, 24, 30))
        for k in range(10):                                                                                           # bolts
            a = math.tau * k / 10 + 0.3
            p.drawEllipse(QPointF(cx + math.cos(a) * 0.92 * R, cy + math.sin(a) * 0.92 * R), R * 0.018, R * 0.018)
        # the well the coils sit in, and the coil bodies: dark bronze until they are charged
        well = QRadialGradient(cx, cy, RX.COIL_OUT * R)
        well.setColorAt(0.0, QColor(6, 9, 13)); well.setColorAt(0.6, QColor(10, 14, 20)); well.setColorAt(1.0, QColor(24, 28, 34))
        p.setBrush(well); p.drawEllipse(QPointF(cx, cy), RX.COIL_OUT * R * 1.02, RX.COIL_OUT * R * 1.02)
        col = RX.mix(RX.BLUE, tint, 0.35 + 0.65 * mixv)
        for i, poly in enumerate(RX.coil_polys(cx, cy, R, self.reactor.coil_rot)):
            mx = sum(x for x, y in poly) / 4.0; my = sum(y for x, y in poly) / 4.0
            gr = QLinearGradient(cx, cy, mx, my)
            gr.setColorAt(0.0, QColor(44, 29, 12)); gr.setColorAt(1.0, QColor(112, 76, 30))
            qp = QPolygonF([QPointF(x, y) for x, y in poly])
            p.setBrush(gr); p.setPen(QPen(rgb(GOLD, 120), 1.0))
            p.drawPolygon(qp)
            c = self.reactor.coil_charge(i)                                       # charged: the coil is lit in the state's colour
            if c > 0.01:
                lg = QLinearGradient(cx, cy, mx, my)
                lg.setColorAt(0.0, rgb(RX.mix(col, RX.WHITE, 0.35), 235 * c)); lg.setColorAt(1.0, rgb(col, 200 * c))
                p.setBrush(lg); p.setPen(Qt.NoPen); p.drawPolygon(qp)

    def _coils_lit(self, q, g, tint, mixv):
        cx, cy, R = g["cx"], g["cy"], g["R"]
        col = RX.mix(RX.BLUE, tint, 0.35 + 0.65 * mixv)
        q.setPen(Qt.NoPen)
        for i, poly in enumerate(RX.coil_polys(cx, cy, R, self.reactor.coil_rot)):
            c = self.reactor.coil_charge(i)
            if c <= 0.01:
                continue
            q.setBrush(rgb(col, 60 * c * self.reactor.dyn.v["bright"]))
            q.drawPolygon(QPolygonF([QPointF(x, y) for x, y in poly]))

    def _flow(self, q, g, tint, mixv):
        """Energy streaks spiralling into the core while it works (it is taking your goal in) and out of it when a goal verifies."""
        cx, cy, R = g["cx"], g["cy"], g["R"]
        col = RX.mix(RX.BLUE, tint, 0.3 + 0.6 * mixv)
        outward = self.reactor.dyn.mode == "ok"
        for ang, r, sp in self.reactor.flow:
            back = -0.16 if not outward else 0.16                # the tail trails behind the motion
            tail_r = r - (0.07 if not outward else -0.07)
            a = int(200 * RX.clamp((1.25 - r) * 1.4 if not outward else (1.25 - r) * 1.2) * (0.5 + 0.5 * RX.clamp(sp / 0.6)))
            if a <= 2:
                continue
            x0, y0 = cx + math.cos(ang) * r * R, cy + math.sin(ang) * r * R
            x1, y1 = cx + math.cos(ang + back) * tail_r * R, cy + math.sin(ang + back) * tail_r * R
            q.setPen(QPen(rgb(col, a), 1.5, Qt.SolidLine, Qt.RoundCap))
            q.drawLine(QPointF(x0, y0), QPointF(x1, y1))

    def _bolts(self, q, g, tint, mixv):
        """Energy arcs from the core to the coils: they crackle on every real event and while it works."""
        cx, cy, R = g["cx"], g["cy"], g["R"]
        col = RX.mix(RX.BLUE, tint, 0.3 + 0.6 * mixv)
        for b in self.reactor.bolts:
            f = 1.0 - b["age"] / b["life"]
            pts = [QPointF(cx + x * R, cy + y * R) for x, y in b["pts"]]
            q.setBrush(Qt.NoBrush)
            q.setPen(QPen(rgb(col, 80 * f), 4.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); q.drawPolyline(QPolygonF(pts))
            q.setPen(QPen(rgb(RX.mix(col, RX.WHITE, 0.7), 235 * f), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); q.drawPolyline(QPolygonF(pts))

    def _core(self, q, g, tint, mixv):
        """The glowing heart: palladium ring, the rotating triangle, and a core that flares with every real event."""
        cx, cy, R = g["cx"], g["cy"], g["R"]
        lvl = self.reactor.core_level()
        col = RX.mix(RX.BLUE, tint, mixv)
        pal = (RX.PAL_R[0] + RX.PAL_R[1]) / 2.0 * R
        q.setBrush(Qt.NoBrush)
        q.setPen(QPen(rgb(RX.mix(col, RX.WHITE, 0.4), min(255, 210 * lvl)), R * (RX.PAL_R[1] - RX.PAL_R[0])))
        q.drawEllipse(QPointF(cx, cy), pal, pal)
        tri = RX.triangle(cx, cy, R, self.reactor.tri_rot)
        q.setPen(QPen(rgb(RX.mix(col, RX.WHITE, 0.55), min(255, 230 * lvl)), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        q.drawPolygon(QPolygonF([QPointF(x, y) for x, y in tri]))
        tri2 = RX.triangle(cx, cy, R, -self.reactor.tri_rot * 1.4, RX.TRI_R * 0.55)
        q.setPen(QPen(rgb(col, min(255, 160 * lvl)), 1.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        q.drawPolygon(QPolygonF([QPointF(x, y) for x, y in tri2]))
        rad = R * RX.CORE_R * (1.0 + 0.5 * min(1.5, lvl))
        gr = QRadialGradient(cx, cy, rad)
        gr.setColorAt(0.0, rgb(RX.WHITE, 255)); gr.setColorAt(0.18, rgb(RX.mix(col, RX.WHITE, 0.6), min(255, 235 * lvl)))
        gr.setColorAt(0.5, rgb(col, min(255, 120 * lvl))); gr.setColorAt(1.0, rgb(col, 0))
        q.setPen(Qt.NoPen); q.setBrush(gr); q.drawEllipse(QPointF(cx, cy), rad, rad)
        fl = self.reactor.flare + 0.6 * self._poke                      # a lens-flare cross that swells with every real event
        if fl > 0.02:
            L = R * (0.5 + 1.1 * fl)
            sg = QLinearGradient(cx - L, cy, cx + L, cy)
            hot = RX.mix(col, RX.GOLD_BRIGHT, 0.5)
            sg.setColorAt(0.0, rgb(hot, 0)); sg.setColorAt(0.5, rgb(hot, min(255, 200 * fl))); sg.setColorAt(1.0, rgb(hot, 0))
            q.setBrush(sg); q.drawRect(QRectF(cx - L, cy - 1.2, 2 * L, 2.4))
            V = L * 0.45
            vg = QLinearGradient(cx, cy - V, cx, cy + V)
            vg.setColorAt(0.0, rgb(hot, 0)); vg.setColorAt(0.5, rgb(hot, min(255, 150 * fl))); vg.setColorAt(1.0, rgb(hot, 0))
            q.setBrush(vg); q.drawRect(QRectF(cx - 1.0, cy - V, 2.0, 2 * V))

    def _voice_ring(self, q, g):
        """A radial equaliser of the real audio around the housing: the newest sample at the top, the history running clockwise.
        Blue while it hears you, green while it speaks, orange when the microphone is off."""
        st = self.voice["state"]
        if st == "off":
            return
        col = QColor(C[VOICE_COLOR.get(st, "accent")])
        base = 0.10 if st == "muted" else (0.24 if self.voice["attentive"] else 0.14)
        cx, cy, R = g["cx"], g["cy"], g["R"]
        n = VOICE_BARS
        step = max(1, n // self.quality.bars)
        r0, span = RX.VOICE_IN * R, (RX.VOICE_OUT - RX.VOICE_IN) * R
        for i in range(0, n, step):
            v = self._vhist[n - 1 - i]
            phi = -math.pi / 2 + math.tau * i / n
            ca, sa = math.cos(phi), math.sin(phi)
            a = int(255 * min(1.0, base + 0.85 * v))
            q.setPen(QPen(QColor(col.red(), col.green(), col.blue(), a), 1.6 + 1.2 * v, Qt.SolidLine, Qt.RoundCap))
            q.drawLine(QPointF(cx + ca * r0, cy + sa * r0), QPointF(cx + ca * (r0 + span * (0.18 + 0.82 * v)), cy + sa * (r0 + span * (0.18 + 0.82 * v))))

    # -- the three HUD rings: the real pipeline --
    def _rings(self, q, g, tint):
        cx, cy, R = g["cx"], g["cy"], g["R"]
        pulse = 0.65 + 0.35 * math.sin(self.t * 6.0)
        for which in range(3):
            r = (RX.RING_R["plan"], RX.RING_R["act"], RX.RING_R["verify"])[which]
            rect = QRectF(cx - r * R, cy - r * R, 2 * r * R, 2 * r * R)
            q.setBrush(Qt.NoBrush)
            rev = self.reactor.reveal(3 - which)                                   # boot: the inner ring draws first, the outer last
            if rev < 0.999:
                if rev > 0.01:
                    q.setPen(QPen(rgb(RX.mix(STEEL, RX.BLUE, 0.6), 200 * rev), 2.0)); q.drawArc(rect, 90 * 16, int(-360 * rev * 16))
                continue
            q.setPen(QPen(rgb(STEEL, 46), 1.0)); q.drawEllipse(QPointF(cx, cy), r * R, r * R)                 # the track
            states = self.ring_states(which)
            segs = RX.ring_segments(len(states))
            if not segs:
                continue
            for (start, span), st in zip(segs, states):
                colour, alpha, width = SEG.get(st, SEG["idle"])
                a = alpha * (pulse if st == "waiting" else 1.0)
                pen = QPen(rgb(RX.mix(colour, tint, 0.10), a), width, Qt.SolidLine, Qt.FlatCap)
                q.setPen(pen)
                q.drawArc(rect, int((90 - start) * 16), int(-span * 16))
            if which == 2 and self.pipeline["sealed"]:                  # sealed: a highlight keeps circling the closed ring
                ang = math.radians(90 - (self.t * 80.0) % 360.0)
                for j in range(14):
                    a2 = ang + math.radians(j * 2.2)
                    f = (1.0 - j / 14.0) ** 1.4
                    q.setPen(Qt.NoPen); q.setBrush(rgb((255, 255, 255) if j == 0 else SEG["verified"][0], 235 * f))
                    q.drawEllipse(QPointF(cx + math.cos(a2) * r * R, cy - math.sin(a2) * r * R), 3.0 * (1 - 0.5 * j / 14.0), 3.0 * (1 - 0.5 * j / 14.0))
            for s_i, (st, (start, span)) in enumerate(zip(states, segs)):
                if st != "running":
                    continue
                frac = (self.t * 0.55 + s_i * 0.31) % 1.0                   # a comet runs along the segment doing work right now
                for j in range(12):
                    ang = math.radians(90 - (start + (frac * span) - j * 1.6))
                    f = (1.0 - j / 12.0) ** 1.5
                    q.setPen(Qt.NoPen); q.setBrush(rgb((255, 255, 255) if j == 0 else SEG["running"][0], 235 * f))
                    q.drawEllipse(QPointF(cx + math.cos(ang) * r * R, cy - math.sin(ang) * r * R), 3.4 * (1 - 0.6 * j / 12.0), 3.4 * (1 - 0.6 * j / 12.0))
            if len(segs) > 1:                                              # end caps: the arcs read as separate pieces
                q.setPen(Qt.NoPen)
                for st, (start, span) in zip(states, segs):
                    colour, alpha, _ = SEG.get(st, SEG["idle"])
                    q.setBrush(rgb(colour, alpha * 0.9))
                    for deg in (start, start + span):
                        ang = math.radians(90 - deg)
                        q.drawEllipse(QPointF(cx + math.cos(ang) * r * R, cy - math.sin(ang) * r * R), 2.3, 2.3)

    def _ripples(self, q, g):
        q.setBrush(Qt.NoBrush)
        cx, cy, R = g["cx"], g["cy"], g["R"]
        for t0, key in self.ripples:
            u = (self.t - t0) / 1.6
            if not 0 <= u <= 1:
                continue
            col = QColor(C[key])
            r = R * (1.0 + 1.0 * (1 - (1 - u) ** 2))
            a = int(190 * (1 - u) ** 1.6)
            q.setPen(QPen(QColor(col.red(), col.green(), col.blue(), a), 2.2 * (1 - u) + 0.6))
            q.drawEllipse(QPointF(cx, cy), r, r)
        sh = self.reactor.shock
        if sh is not None:                                                  # VERIFIED: a gold shockwave sweeps out through the dial
            u = RX.ease_out(sh)
            q.setPen(QPen(rgb(GOLD_B, 230 * (1 - sh) ** 1.4), 5.0 * (1 - sh) + 1.0))
            q.drawEllipse(QPointF(cx, cy), R * (0.9 + 1.25 * u), R * (0.9 + 1.25 * u))

    def _streams(self, q, g):
        """Sparks carrying a request from the reactor to the provider being called right now (drawn into the bloom buffer)."""
        for i, nd in enumerate(self.nodes):
            if i not in g["pos"] or not self._is_active(nd):
                continue
            base = QColor(C[COST_COLOR.get(nd["cost_class"], "accent")])
            pts = self._link_pts(g, i)
            q.setPen(Qt.NoPen)
            for x, y, a, s, u in RX.courier_poly(self.t, pts):
                q.setBrush(QColor(base.red(), base.green(), base.blue(), int(235 * a)))
                q.drawEllipse(QPointF(x, y), s, s)

    def _embers(self, q, g):
        """Warm sparks drifting up from the housing, like a forge: more while it works."""
        cx, cy, R = g["cx"], g["cy"], g["R"]
        q.setPen(Qt.NoPen)
        for x, y, vx, vy, life, age in self.reactor.embers:
            f = math.sin(math.pi * min(1.0, age / life)) ** 0.8
            q.setBrush(rgb(RX.mix(GOLD_B, GOLD, age / life), 215 * f * self.reactor.dyn.v["bright"]))
            q.drawEllipse(QPointF(cx + x * R, cy + y * R), 1.0 + 1.1 * f, 1.0 + 1.1 * f)

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
            p.setPen(QPen(qc("line2", 200), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(track, -225 * 16, -270 * 16)                            # fuel gauge: how much of the allowance is spent
            if nd["pressure"] > 0:
                p.setPen(QPen(qc(pressure_color(nd["pressure"])), 3, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(track, -225 * 16, int(-270 * 16 * min(1.0, nd["pressure"])))
            hexa = QPolygonF([QPointF(pt.x() + math.cos(math.radians(60 * k + 30)) * nr, pt.y() + math.sin(math.radians(60 * k + 30)) * nr) for k in range(6)])
            if nd["blocked"]:
                p.setPen(QPen(qc(base, 120), 1.4, Qt.DashLine)); p.setBrush(qc("bg0", 200))
                p.drawPolygon(hexa)
            else:
                if active:
                    p.setCompositionMode(QPainter.CompositionMode_Plus)
                    gr = QRadialGradient(pt, nr * 3.0)
                    pulse = 0.65 + 0.35 * math.sin(self.t * 7.0)
                    gr.setColorAt(0, qc(base, int(170 * pulse))); gr.setColorAt(1, qc(base, 0))
                    p.setPen(Qt.NoPen); p.setBrush(gr); p.drawEllipse(pt, nr * 3.0, nr * 3.0)
                    p.setCompositionMode(QPainter.CompositionMode_SourceOver)
                p.setPen(QPen(qc(base, 255 if not dim else 90), 1.8)); p.setBrush(qc(base, 70 if not dim else 25))
                p.drawPolygon(hexa)
            p.setPen(Qt.NoPen)
            p.setBrush(qc(base, 255 if not (dim or nd["blocked"]) else 90))
            p.drawEllipse(pt, nr * 0.3, nr * 0.3)
            if nd["cooling_s"] and not nd["blocked"]:                      # a clock hand: it is resting
                ang = -math.pi / 2 + (self.t * 0.4) % math.tau
                p.setPen(QPen(qc("warn", 220), 1.6, Qt.SolidLine, Qt.RoundCap))
                p.drawLine(pt, QPointF(pt.x() + math.cos(ang) * nr * 0.72, pt.y() + math.sin(ang) * nr * 0.72))
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
            self._hit.append((nd["family"], pt, nr, self._tip(nd)))
            hot = active or bool(sub) or nd["family"] == self._hover
            label = DISPLAY.get(nd["family"], nd["family"]) + (f"  x{len(nd['models'])}" if len(nd["models"]) > 1 else "")
            gap = nr + 12
            x0 = pt.x() - gap - 130 if side < 0 else pt.x() + gap
            al = Qt.AlignRight if side < 0 else Qt.AlignLeft
            p.setFont(self._font(self.mono, 8, QFont.Bold, 1.5))
            p.setPen(qc("text" if hot and not (dim or nd["blocked"]) else "muted" if not (dim or nd["blocked"]) else "dim"))
            p.drawText(QRectF(x0, pt.y() - 17, 130, 16), al | Qt.AlignVCenter, label.upper())
            if sub:
                p.setFont(self._font(self.ui, 8)); p.setPen(qc(subcol))
                p.drawText(QRectF(x0, pt.y() - 1, 130, 14), al | Qt.AlignVCenter, sub)

    def _panels(self, p, g):
        """The two readouts: the real event feed (bottom-left) and real numbers about the goal (bottom-right). Wide windows only."""
        w, h = g["w"], g["h"]
        if w < 1000 or h < 560:
            return
        f = self.reactor.reveal(6)
        if f <= 0.02:
            return
        p.setOpacity(f)
        f8 = self._font(self.mono, 8)
        p.setFont(f8)
        x, y0 = 26.0, h - 150.0
        p.setPen(QPen(rgb(GOLD, 150), 1.2))
        p.drawLine(QPointF(x, y0 - 4), QPointF(x + 18, y0 - 4)); p.drawLine(QPointF(x + 18, y0 - 4), QPointF(x + 24, y0 + 2))
        p.setFont(self._font(self.mono, 7, QFont.Bold, 3)); p.setPen(rgb(GOLD, 200))
        p.drawText(QRectF(x + 30, y0 - 11, 160, 14), Qt.AlignVCenter, "EVENT LOG")
        p.setFont(f8)
        lines = list(self.log)
        for k, (stamp, text, level) in enumerate(lines):
            age = len(lines) - 1 - k
            a = int(255 * max(0.25, 1.0 - 0.17 * age))
            col = QColor(C[LEVEL_COLOR.get(level, "accent")]) if level != "info" else QColor(C["text"])
            row = QRectF(x, y0 + 8 + k * 14, 430, 14)
            p.setPen(QColor(120, 135, 152, a)); p.drawText(row, Qt.AlignVCenter | Qt.AlignLeft, stamp)
            p.setPen(QColor(col.red(), col.green(), col.blue(), a))
            p.drawText(row.adjusted(62, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, QFontMetricsF(f8).elidedText(text, Qt.ElideRight, 360))
        if self.stats:
            xr = w - 26.0
            p.setPen(QPen(rgb(GOLD, 150), 1.2))
            p.drawLine(QPointF(xr, y0 - 4), QPointF(xr - 18, y0 - 4)); p.drawLine(QPointF(xr - 18, y0 - 4), QPointF(xr - 24, y0 + 2))
            p.setFont(self._font(self.mono, 7, QFont.Bold, 3)); p.setPen(rgb(GOLD, 200))
            p.drawText(QRectF(xr - 190, y0 - 11, 160, 14), Qt.AlignVCenter | Qt.AlignRight, "THE GOAL")
            for k, (label, value) in enumerate(self.stats.items()):
                row = QRectF(xr - 220, y0 + 8 + k * 16, 220, 16)
                p.setFont(f8); p.setPen(QColor(120, 135, 152, 230))
                p.drawText(row, Qt.AlignVCenter | Qt.AlignLeft, label.upper())
                p.setFont(self._font(self.mono, 9, QFont.Bold)); p.setPen(qc("text"))
                p.drawText(row, Qt.AlignVCenter | Qt.AlignRight, value)
        p.setOpacity(1.0)

    def _glow_text(self, p, rect, text, col, flags, a=255):
        c = QColor(col)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            p.setPen(QColor(c.red(), c.green(), c.blue(), 40))
            p.drawText(rect.translated(dx, dy), flags, text)
        p.setPen(QColor(c.red(), c.green(), c.blue(), a))
        p.drawText(rect, flags, text)

    def _hud(self, p, g):
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        w, h = g["w"], g["h"]
        cx = g["cx"]
        p.setFont(self._font(self.mono, 11, QFont.Bold, 9))                        # wordmark, flanked by gold rules
        self._glow_text(p, QRectF(0, 10, w, 20), "PRAXIS", C["gold"], Qt.AlignCenter, 245)
        if not REDUCED:                                                      # a highlight sweeps along the wordmark every few seconds
            u = (self.t % 5.0) / 1.4
            if u <= 1.0:
                gx = cx - 60 + 120 * u
                lg = QLinearGradient(gx - 22, 0, gx + 22, 0)
                lg.setColorAt(0.0, rgb(GOLD_B, 0)); lg.setColorAt(0.5, rgb((255, 255, 255), 255)); lg.setColorAt(1.0, rgb(GOLD_B, 0))
                p.setPen(QPen(QBrush(lg), 1)); p.drawText(QRectF(0, 10, w, 20), Qt.AlignCenter, "PRAXIS")
        p.setPen(QPen(rgb(GOLD, 150), 1.2))
        for sgn in (-1, 1):
            p.drawLine(QPointF(cx + sgn * 62, 20), QPointF(cx + sgn * 128, 20))
            p.drawLine(QPointF(cx + sgn * 128, 20), QPointF(cx + sgn * 136, 14))
        key = MODE_COLOR.get(self.mode, "accent")
        p.setFont(self._font(self.mono, 9, QFont.Bold, 4))
        self._glow_text(p, QRectF(0, 31, w, 16), self.title, C[key], Qt.AlignCenter, 255)
        if self.subtitle:
            p.setFont(self._font(self.mono, 8)); p.setPen(qc("muted"))
            p.drawText(QRectF(0, 47, w, 13), Qt.AlignCenter, self.subtitle)
        # the pipeline legend: the three rings, with real numbers (only while there is a pipeline to show)
        lf = self._font(self.mono, 8, QFont.Bold, 1.5)
        p.setFont(lf)
        fm = QFontMetricsF(lf)
        items = self.legend() if (self.pipeline["plan"] != "none" or self.pipeline["steps"] or self.pipeline["checks"]) else []
        widths = [14 + fm.horizontalAdvance(f"{n} {t}") + 18 for n, t, _ in items]
        x = cx - sum(widths) / 2.0
        if items:
            p.setPen(QPen(rgb(GOLD, 90), 1.0)); p.setBrush(QColor(5, 8, 12, 170))
            p.drawPolygon(QPolygonF([QPointF(x - 14, 69), QPointF(x - 6, 61), QPointF(x + sum(widths) + 6, 61),
                                     QPointF(x + sum(widths) + 14, 69), QPointF(x + sum(widths) + 6, 77), QPointF(x - 6, 77)]))
        for (name, text, ckey), wd in zip(items, widths):
            col = QColor(C[ckey])
            p.setPen(Qt.NoPen); p.setBrush(QColor(col.red(), col.green(), col.blue(), 235 if ckey != "dim" else 110))
            p.drawPolygon(QPolygonF([QPointF(x + 5, 65.5), QPointF(x + 8.5, 69), QPointF(x + 5, 72.5), QPointF(x + 1.5, 69)]))
            p.setPen(qc("muted")); p.drawText(QRectF(x + 14, 62, 60, 14), Qt.AlignVCenter | Qt.AlignLeft, name)
            p.setPen(QColor(col.red(), col.green(), col.blue(), 255 if ckey != "dim" else 130))
            p.drawText(QRectF(x + 14 + fm.horizontalAdvance(name) + 6, 62, 90, 14), Qt.AlignVCenter | Qt.AlignLeft, text)
            x += wd
        vs = self.voice["state"]
        if vs in VOICE_TAG:                                                 # the real voice state, top right
            tag = VOICE_TAG[vs] if not (vs == "listening" and self.voice["attentive"]) else "LISTENING  ·  go ahead"
            tc = QColor(C[VOICE_COLOR[vs]])
            p.setFont(self._font(self.mono, 8, QFont.Bold, 2))
            fmt = QFontMetricsF(self._font(self.mono, 8, QFont.Bold, 2))
            tw = fmt.horizontalAdvance(tag) + 24
            p.setPen(QPen(rgb(GOLD, 100), 1.0)); p.setBrush(QColor(5, 8, 12, 175))
            p.drawPolygon(QPolygonF([QPointF(w - tw - 22, 22), QPointF(w - tw - 14, 12), QPointF(w - 18, 12), QPointF(w - 18, 32), QPointF(w - tw - 14, 32)]))
            pulse = 0.6 + 0.4 * math.sin(self.t * 4.0) if vs in ("hearing", "speaking") else 1.0
            p.setPen(Qt.NoPen); p.setBrush(QColor(tc.red(), tc.green(), tc.blue(), int(255 * pulse))); p.drawEllipse(QPointF(w - tw - 6, 22), 3.2, 3.2)
            p.setPen(QColor(tc.red(), tc.green(), tc.blue(), 235))
            p.drawText(QRectF(w - tw + 4, 12, tw - 8, 20), Qt.AlignVCenter | Qt.AlignLeft, tag)
        if self.footer:
            p.setFont(self._font(self.mono, 8, None, 2)); p.setPen(qc("dim"))
            p.drawText(QRectF(0, h - 20, w, 14), Qt.AlignCenter, self.footer)

