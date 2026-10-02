"""HudView: the one-screen window content. It owns the REAL state (mode, pipeline, voice, brains, events, numbers) and draws it by interpreting
a JSON spec (default.hud.json, or ~/.praxis/hud.json if you have one). Edit the file while PRAXIS runs and the screen changes within a second;
a mistake never takes the window down: the error goes to the event feed and the last good design stays.

Nothing is drawn that is not either decoration or measured: panels show real steps, real checks, real events, real numbers."""
import math
import os
import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QToolTip, QWidget

from ..theme import COST_NAME, PRIVACY_NAME, fonts, pick
from . import draw, spec as specmod
from .expr import Obj
from .motion import Motion, Quality, clamp

REDUCED = bool(os.environ.get("PRAXIS_REDUCE_MOTION"))
VOICE_BARS = 96
VOICE_TAG = {"listening": "LISTENING", "hearing": "HEARING", "thinking": "THINKING", "speaking": "SPEAKING", "muted": "MIC OFF  ·  F4",
             "offline": "NO MICROPHONE"}
DISPLAY = {"droid": "droid · factory", "devin": "devin", "claude": "claude", "codex": "codex", "ollama": "ollama"}
LEVEL_COLOR = {"info": "text", "ok": "ok", "warn": "warn", "bad": "bad", "muted": "muted"}
RING_NAMES = ("PLAN", "ACT", "VERIFY")
CKEY = {"accent": "accent", "ok": "ok", "bad": "bad", "warn": "warn", "dim": "dim", "muted": "muted"}
COST_COLOR_NAME = {0: "ok", 1: "accent", 2: "violet"}


def fin(x, lo, hi, default=0.0):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    if x != x or x in (float("inf"), float("-inf")):
        return default
    return max(lo, min(hi, x))


def ring_segments(n, gap_deg=7.0):
    if n <= 0:
        return []
    if n == 1:
        return [(0.0, 360.0)]
    span = 360.0 / n
    return [(i * span, span - gap_deg) for i in range(n)]


class HudView(QWidget):
    def __init__(self, spec_path=None):
        super().__init__()
        self.setMinimumSize(560, 300)
        self.setMouseTracking(True)
        ui, mono = fonts()
        self.ui, self.mono = ui, mono
        self.fonts = {"ui": ui, "mono": mono}
        self.mode, self.progress, self.title, self.subtitle = "starting", 0.0, "STARTING", ""
        self.goal = ""
        self.nodes, self.active, self._hover = [], "", ""
        self.pipeline = dict(plan="none", steps=[], checks=[], sealed=False, labels=[])
        self.t = 0.0
        self.quality = Quality()
        self.caption, self.cap_level, self.cap_t = "", "info", 0.0
        self.footer = ""
        self.voice = dict(state="off", level=0.0, speak=0.0, attentive=False)
        self._vhist, self._vacc = [0.0] * VOICE_BARS, 0.0
        self.log = deque(maxlen=7)
        self.stats = {}
        self._poke = 0.0
        self._hits = []
        self._caches, self._layer_pm, self._buf = {}, {}, None
        self._last = time.perf_counter()
        self._spec_err_seen = ""
        self._tip_cache = {}
        self.spec = None
        self.spec_source = ""
        self.motion = None
        self._load_initial(spec_path)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._base_ms = 80 if REDUCED else 33
        self._reload_in = 1.0
        self.timer.start(self._base_ms)

    # ---- the spec -----------------------------------------------------------------------------------------------------
    def _load_initial(self, spec_path):
        errs = []
        for path in ([spec_path] if spec_path else [specmod.user_path(), specmod.DEFAULT_PATH]):
            if not path or (path != specmod.DEFAULT_PATH and not os.path.isfile(path)):
                continue
            sp = specmod.load(path)
            if sp.ok:
                self._adopt(sp)
                break
            errs.append((path, sp.errors[:3]))
        if self.spec is None:
            self._adopt(specmod.load(specmod.DEFAULT_PATH))
        for path, e in errs:                                      # a design that could not be used is said so, not silently skipped
            self.add_log(f"HUD spec {os.path.basename(path)}: {e[0][0]}: {e[0][1]}"[:90], "bad")

    def _adopt(self, sp):
        mode = self.motion.mode if self.motion else "starting"
        old = self.motion
        self.spec = sp
        self.spec_source = sp.path
        self.motion = Motion(sp.modes, sp.persona_rate, mode=mode, boot=sp.boot)
        if old is not None:                                       # keep the picture going across a reload: same time, rotation and detail level
            self.motion.t, self.motion.boot, self.motion.power = old.t, old.boot, old.power
            self.motion.v.update({k: v for k, v in old.v.items() if k in self.motion.v})
            self.motion.set_level(old.level)
        fam = sp.fonts or {}
        self.fonts = {"ui": pick(fam.get("ui", []), self.ui) if fam.get("ui") else self.ui,
                      "mono": pick(fam.get("mono", []), self.mono) if fam.get("mono") else self.mono}
        self.setMinimumSize(*[int(x) for x in sp.min_size])
        self._caches.clear(); self._layer_pm.clear()

    def reload_if_changed(self):
        """Pick up an edited spec file. Returns True if the design changed."""
        path = self.spec_source
        if not path:
            return False
        try:
            m = os.path.getmtime(path)
        except OSError:
            return False
        if m == self.spec.mtime:
            return False
        sp = specmod.load(path)
        if sp.ok:
            self._adopt(sp)
            self._spec_err_seen = ""
            self.add_log(f"HUD design reloaded: {sp.name}", "ok")
            return True
        key = f"{m}"
        if key != self._spec_err_seen:
            self._spec_err_seen = key
            self.spec.mtime = m
            p, _, msg = sp.errors[0]
            self.add_log(f"HUD spec error: {p}: {msg}"[:90], "bad")
        return False

    def dispose(self):
        self.timer.stop()
        try:
            self.timer.timeout.disconnect()
        except (TypeError, RuntimeError):
            pass

    # ---- the API the window uses ---------------------------------------------------------------------------------------
    def set_state(self, mode, progress, title, subtitle=""):
        if mode != self.mode:
            m = self.motion
            if mode == "starting":
                m.restart_power_up()
            elif mode == "ok":
                m.trigger_shock(); m.pulse(1.4); m.ripple("ok", force=True)
            elif mode in ("bad", "stopping"):
                m.ripple("bad" if mode == "bad" else "warn", force=True)
            m.set_mode(mode)
            self._base_ms = 80 if REDUCED else 33 if mode in ("working", "starting", "stopping", "ok") else 42
            self._pace()
        self.mode, self.progress, self.title, self.subtitle = mode, fin(progress, 0.0, 1.0), str(title), str(subtitle)

    def set_goal(self, text):
        """The words of the goal being worked on (shown in the mission panel)."""
        self.goal = str(text or "")

    def set_pipeline(self, plan="none", steps=(), checks=(), sealed=False, labels=()):
        self.pipeline = dict(plan=plan, steps=list(steps), checks=[bool(c) for c in checks], sealed=bool(sealed), labels=list(labels))

    def set_voice(self, state, level=0.0, speak=0.0, attentive=False):
        self.voice = dict(state=state, level=fin(level, 0.0, 10.0), speak=fin(speak, 0.0, 10.0), attentive=bool(attentive))

    def voice_amplitude(self):
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
        """The latest message. It is not drawn on the screen (removed on request); warnings and errors go to the event feed instead."""
        if text != self.caption:
            self.caption, self.cap_level, self.cap_t = text, level, 0.0
            if level in ("warn", "bad") and text:
                self.add_log(text, level)

    @property
    def caption_shown(self):
        return self.caption[:max(0, int(self.cap_t * 70))]

    def set_footer(self, text):
        self.footer = text

    def add_log(self, text, level="info", stamp=None):
        text = str(text or "").strip()
        if not text or (self.log and self.log[-1][1] == text):
            return
        self.log.append((stamp or time.strftime("%H:%M:%S"), text[:90], level))

    def set_stats(self, stats):
        self.stats = {str(k): str(v) for k, v in dict(stats or {}).items()}

    def pulse(self, level="info"):
        m = self.motion
        if m.ripples == [] or m.t - m.ripples[-1][0] >= 0.14:
            m.pulse(0.8)
        m.ripple(LEVEL_COLOR.get(level, "accent"))

    def ring_states(self, which):
        pl = self.pipeline
        if which == 0:
            return {"planning": ["running"], "ready": ["ran"], "failed": ["failed"]}.get(pl["plan"], [])
        if which == 1:
            return list(pl["steps"])
        if pl["sealed"]:
            return ["verified"]
        return ["verified" if ok else "failed" for ok in pl["checks"]]

    def legend(self):
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

    # ---- time --------------------------------------------------------------------------------------------------------
    def advance(self, dt):
        dt = fin(dt, 0.0, 0.25, 0.0)
        if dt <= 0.0:
            return
        self.t = (self.t + dt) % 100000.0
        self.motion.advance(dt * (0.2 if REDUCED else 1.0))
        self.cap_t += dt
        self._poke = max(0.0, self._poke - dt * 2.0)
        self._vacc += dt
        while self._vacc >= 1 / 30:
            self._vacc -= 1 / 30
            self._vhist = self._vhist[1:] + [self._vhist[-1] * 0.55 + self.voice_amplitude() * 0.45]
        if self.voice["state"] == "speaking":
            self.motion.flare = max(self.motion.flare, 0.5 * min(1.0, self.voice["speak"]))
        self._reload_in -= dt
        if self._reload_in <= 0:
            self._reload_in = 1.0
            self.reload_if_changed()

    def _pace(self):
        w = self.window()
        ms = self._base_ms
        if w is not None and w.isMinimized():
            ms = 500
        elif w is not None and not w.isActiveWindow() and self.isVisible():
            ms = max(ms, 66)
        if self.timer.interval() != ms:
            self.timer.setInterval(ms)
        return ms

    def _tick(self):
        now = time.perf_counter()
        dt, self._last = now - self._last, now
        w = self.window()
        if w is not None and w.isMinimized():
            self._pace()
            return
        self._pace()
        if self.isVisible():
            self.advance(dt)
            self.update()

    # ---- data the spec can bind to ----------------------------------------------------------------------------------------
    def _style(self, state):
        st = self.spec.states.get(state, "dim")
        if isinstance(st, dict):
            return st.get("color", "dim"), float(st.get("alpha", 1.0)), float(st.get("width", 3.0))
        return st, 1.0, 3.0

    def _sources(self, ctx):
        sp, pl = self.spec, self.pipeline
        src = {}
        nodes = []
        for i, nd in enumerate(self.nodes):
            fam = nd["family"]
            active = self._is_active(nd)
            sub = ""
            if nd["blocked"]:
                sub = "blocked by data class"
            elif nd["cooling_s"]:
                sub = f"resting {nd['cooling_s'] // 60 + 1}m"
            elif nd["pressure"] >= 0.9:
                sub = f"{nd['pressure'] * 100:.0f}% spent"
            elif nd["pressure"] >= 0.6:
                sub = f"{nd['pressure'] * 100:.0f}% spent"
            elif active:
                sub = "calling..."
            nodes.append(Obj(dict(
                i=i, family=fam, name=(DISPLAY.get(fam, fam) + (f"  x{len(nd['models'])}" if len(nd["models"]) > 1 else "")).upper(),
                cost_class=nd["cost_class"], pressure=nd["pressure"], blocked=bool(nd["blocked"]), cooling_s=nd["cooling_s"],
                models=len(nd["models"]), active=active, sub=sub, hover=(fam == self._hover),
                color=("bad" if nd["blocked"] else COST_COLOR_NAME.get(nd["cost_class"], "accent")),
                subcolor=("warn" if (nd["cooling_s"] or 0.6 <= nd["pressure"] < 0.9) else "bad" if (nd["blocked"] or nd["pressure"] >= 0.9) else "accent"))))
        src["nodes"] = nodes
        steps = []
        labels = pl.get("labels") or []
        for i, st in enumerate(pl["steps"]):
            c, a, w = self._style(st)
            steps.append(Obj(dict(i=i, label=(labels[i] if i < len(labels) and labels[i] else f"step {i + 1}"), state=st,
                                  glyph=sp.glyphs.get(st, "-"), color=c, alpha=a)))
        src["steps"] = steps
        src["checks"] = [Obj(dict(i=i, ok=ok, glyph=sp.glyphs.get("verified" if ok else "failed", "-"), color="ok" if ok else "bad"))
                         for i, ok in enumerate(pl["checks"])]
        n = len(self.log)
        src["log"] = [Obj(dict(i=i, n=n, time=ts, text=tx, level=lv, color=LEVEL_COLOR.get(lv, "text"))) for i, (ts, tx, lv) in enumerate(self.log)]
        order = sp.stats_order
        src["stats"] = [Obj(dict(key=k.upper(), value=self.stats[k])) for k in order if k in self.stats] + \
                       [Obj(dict(key=k.upper(), value=v)) for k, v in self.stats.items() if k not in order]
        src["legend"] = [Obj(dict(name=nm, text=tx, color=CKEY.get(ck, "dim"))) for nm, tx, ck in self.legend()]
        for key, which in (("ring_plan", 0), ("ring_act", 1), ("ring_verify", 2)):
            states = self.ring_states(which)
            segs = ring_segments(len(states))
            items = []
            for i, (st, (start, span)) in enumerate(zip(states, segs)):
                c, a, w = self._style(st)
                items.append(Obj(dict(i=i, n=len(states), start=start, span=span, state=st, color=c, alpha=a, width=w, running=st == "running", waiting=st == "waiting")))
            src[key] = items
        n = len(self._vhist)
        src["voice"] = [Obj(dict(v=v, i=i, n=n)) for i, v in enumerate(self._vhist)]
        return src

    def _is_active(self, nd):
        return bool(self.active) and (self.active == nd["family"] or self.active.split("/")[0] == nd["family"])

    def _context(self):
        sp, m = self.spec, self.motion
        w, h = self.width(), self.height()
        pl = self.pipeline
        done = sum(1 for s in pl["steps"] if s in ("verified", "ran"))
        ctx = {"W": float(w), "H": float(h), "mode": self.mode, "title": self.title, "subtitle": self.subtitle, "goal": self.goal, "progress": self.progress,
               "voice_state": self.voice["state"], "attentive": self.voice["attentive"], "level": self.voice_amplitude(), "hover": self._hover,
               "has_goal": bool(pl["plan"] != "none" or pl["steps"] or pl["checks"]), "plan_state": pl["plan"], "sealed": pl["sealed"],
               "nsteps": len(pl["steps"]), "nchecks": len(pl["checks"]), "done": done, "nnodes": len(self.nodes), "poke": self._poke,
               "voice_tag": VOICE_TAG.get(self.voice["state"], ""), "voice_on": self.voice["state"] in VOICE_TAG,
               "mode_color": sp.modes.get(self.mode, {}).get("color", "accent"), "m": Obj(dict(m.v)), "stats": Obj(dict(self.stats)), "caption": self.caption, "reduced": REDUCED}
        ctx.update(m.frame_vars())
        for name, e in sp.vars:                                               # layout and shared values, in order
            ctx[name] = e(ctx)
        return ctx

    # ---- painting ----------------------------------------------------------------------------------------------------
    def paintEvent(self, e):
        t0 = time.perf_counter()
        w, h = self.width(), self.height()
        if w < 80 or h < 80:
            return
        sp = self.spec
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            void = sp.palette.lookup("void", {})
            p.fillRect(self.rect(), QColor(int(void[0]), int(void[1]), int(void[2])))        # the design owns the whole widget, even if it draws no background
            ctx = self._context()
            srcs = self._sources(ctx)
            fr = draw.Frame(p, ctx, sp, self.motion, srcs, self.fonts, self._caches)
            run = []
            for node in sp.layers:
                if node.glow:
                    run.append(node)
                    continue
                if run:
                    self._glow_run(p, ctx, srcs, run, fr)
                    run = []
                self._layer(p, fr, node)
            if run:
                self._glow_run(p, ctx, srcs, run, fr)
            self._hits = fr.hits
        finally:
            if p.isActive():
                p.end()
        for where, msg in sp.runtime_errors()[:1]:
            key = f"{where}:{msg}"
            if key != getattr(self, "_rt_err", ""):
                self._rt_err = key
                self.add_log(f"HUD {where}: {msg}"[:90], "bad")
        if self.quality.record((time.perf_counter() - t0) * 1000.0):
            self.motion.set_level(self.quality.level)

    def _layer(self, p, fr, node):
        """One top-level layer, from its cache if it is marked `cache` (slow-changing: backgrounds, scales, frames)."""
        try:
            if not node.cache:
                draw.render(fr, node)
                return
            ctx = fr.ctx
            if node.visible is not None and not (node.visible(ctx) if callable(node.visible) else node.visible):
                return
            op = (node.opacity(ctx) if callable(node.opacity) else node.opacity) if node.opacity is not None else 1.0
            if node.boot is not None:
                op *= self.motion.reveal(node.boot(ctx) if callable(node.boot) else node.boot)
            if op <= 0.003:
                return
            ck = node.cache_key(ctx) if node.cache_key is not None else 0
            key = (node.path, int(ctx["W"]), int(ctx["H"]), round(ctx["persona"] * 8) if node.cache_persona else 0, round(ck, 2))
            pm = self._layer_pm.get(node.path)
            if pm is None or pm[0] != key:
                img = QPixmap(int(ctx["W"]), int(ctx["H"]))
                img.fill(Qt.transparent)
                q = QPainter(img)
                try:
                    q.setRenderHint(QPainter.Antialiasing)
                    f2 = draw.Frame(q, dict(ctx, t=0.0), fr.spec, self.motion, fr.sources, self.fonts, self._caches)
                    draw.DRAW[node.type](f2, node, node.values(f2.ctx))
                finally:
                    q.end()
                self._layer_pm[node.path] = pm = (key, img)
            p.setOpacity(min(1.0, op))
            p.drawPixmap(0, 0, pm[1])
            p.setOpacity(1.0)
        except Exception as ex:                                               # one broken layer must not blank the screen
            self._note_error(node.path, ex)

    def _glow_run(self, p, ctx, srcs, run, fr):
        """Consecutive glow layers share one buffer that is added on top and bloomed (the soft light round everything bright)."""
        sp = self.spec
        w, h = int(ctx["W"]), int(ctx["H"])
        gb = sp.glow_box
        if gb:
            bx, by = int(fin(gb["x"](ctx) if callable(gb["x"]) else gb["x"], 0, w)), int(fin(gb["y"](ctx) if callable(gb["y"]) else gb["y"], 0, h))
            bw = int(fin(gb["w"](ctx) if callable(gb["w"]) else gb["w"], 16, w))
            bh = int(fin(gb["h"](ctx) if callable(gb["h"]) else gb["h"], 16, h))
        else:
            bx, by, bw, bh = 0, 0, w, h
        if self._buf is None or self._buf.width() != bw or self._buf.height() != bh:
            self._buf = QImage(bw, bh, QImage.Format_ARGB32_Premultiplied)
        buf = self._buf
        buf.fill(Qt.transparent)
        q = QPainter(buf)
        try:
            q.setRenderHint(QPainter.Antialiasing)
            q.translate(-bx, -by)
            f2 = draw.Frame(q, ctx, sp, self.motion, srcs, self.fonts, self._caches)
            f2.hits = fr.hits
            for node in run:
                try:
                    draw.render(f2, node)
                except Exception as ex:
                    self._note_error(node.path, ex)
        finally:
            q.end()
        p.setCompositionMode(QPainter.CompositionMode_Plus)
        dest = QRectF(bx, by, bw, bh)
        p.drawImage(dest.topLeft(), buf)
        lvl = self.quality.level
        if lvl < 2:                                                  # bloom: one blurred copy of the (small) buffer added back on top
            small = buf.scaled(max(8, bw // 6), max(8, bh // 6), Qt.IgnoreAspectRatio, Qt.SmoothTransformation if lvl < 1 else Qt.FastTransformation)
            p.setOpacity(0.70); p.drawImage(dest, small)
        p.setOpacity(1.0)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    def _note_error(self, path, ex):
        key = f"{path}:{type(ex).__name__}"
        if key != getattr(self, "_draw_err", ""):
            self._draw_err = key
            self.add_log(f"HUD draw error in {path}: {type(ex).__name__}: {ex}"[:90], "bad")

    # ---- mouse -------------------------------------------------------------------------------------------------------
    def mouseMoveEvent(self, e):
        self._hover = ""
        pos = e.position()
        for item, rect in self._hits:
            if rect.contains(pos):
                fam = item["family"]
                self._hover = fam
                nd = next((n for n in self.nodes if n["family"] == fam), None)
                if nd is not None:
                    QToolTip.showText(e.globalPosition().toPoint(), self._tip(nd), self)
                return
        QToolTip.hideText()

    def mousePressEvent(self, e):
        w, h = self.width(), self.height()
        try:
            cx, cy, R = (float(self._context().get(k, 0)) for k in ("cx", "cy", "R"))
        except Exception:
            return
        if math.hypot(e.position().x() - cx, e.position().y() - cy) < R * 1.2:
            self.motion.pulse(1.2)
            self._poke = 1.0
            self.motion.ripple("info", force=True)

    @staticmethod
    def _tip(nd):
        lines = [f"{nd['family']}   {PRIVACY_NAME.get(nd.get('privacy'), nd.get('privacy', ''))} / {COST_NAME.get(nd['cost_class'], '')}"]
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
        elif nd.get("delegate_only"):
            lines.append("delegate-only (needs your approval each time)")
        return "\n".join(lines)
