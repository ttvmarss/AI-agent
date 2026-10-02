"""Renders the REAL HUD widget offscreen from its JSON spec and checks what a person would actually see (needs PySide6)."""
import json
import math
import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QImage, QMouseEvent
    from PySide6.QtWidgets import QApplication
    from praxis.desktop.qt import theme
    from praxis.desktop.qt.hud import draw, schema as S, spec as specmod, view as view_mod
    from praxis.desktop.qt.hud.view import HudView
    from tests.qtutil import dispose
    HAVE_QT = True
except Exception:
    HAVE_QT = False


def node(fam, cc, priv="cloud", press=0.0, cool=0, blocked=False, n=1):
    return dict(family=fam, cost_class=cc, privacy=priv, pressure=press, cooling_s=cool, blocked=blocked, delegate_only=False,
                usage={"24h": {"calls": 3, "cost": 0.0}},
                models=[dict(name=f"{fam}/m{i}", tier="best", score=0.9, cost=0.0, tps=None, cooling_s=0) for i in range(n)])


NODES = [node("claude", 2, n=3), node("codex", 2, n=2, press=0.7), node("devin", 2), node("droid", 2, n=2), node("ollama", 0, "local")]
STEPS = ["verified", "running", "pending", "pending"]
LABELS = ["Write hello.py", "Run hello.py", "Check output contains 34", "Clean up"]


def step(c, secs, fps=30):
    for _ in range(int(secs * fps)):
        c.advance(1.0 / fps)


def render(c):
    c.repaint()
    return c.grab().toImage().convertToFormat(QImage.Format_RGB32)


def px(img, x0, y0, x1, y1, stride=1):
    for y in range(max(0, int(y0)), min(img.height(), int(y1)), stride):
        for x in range(max(0, int(x0)), min(img.width(), int(x1)), stride):
            c = img.pixelColor(x, y)
            yield c.red(), c.green(), c.blue()


def energy(img, box, stride=1):
    """Total brightness in a box: how much is drawn there."""
    return sum(0.3 * r + 0.59 * g + 0.11 * b for r, g, b in px(img, *box, stride))


def bright(img, box, thr=150):
    """How many pixels are text-bright in a box (the panel's own fill and grid are dim, so this counts writing)."""
    return sum(1 for r, g, b in px(img, *box) if 0.3 * r + 0.59 * g + 0.11 * b >= thr)


def glow_colour(img, box, min_luma=110):
    sr = sg = sb = n = 0
    for r, g, b in px(img, *box):
        if 0.3 * r + 0.59 * g + 0.11 * b >= min_luma:
            sr += r; sg += g; sb += b; n += 1
    return (sr / n, sg / n, sb / n, n) if n else (0, 0, 0, 0)


@unittest.skipUnless(HAVE_QT, "PySide6 not available")
class HudBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui, mono = theme.fonts()
        cls.app.setStyleSheet(theme.qss(ui, mono))

    def make(self, w=1280, h=760, nodes=NODES, secs=4.5, spec_path=None, goal=False, mode="idle"):
        with mock.patch.dict(os.environ, {"PRAXIS_HUD": os.path.join(tempfile.mkdtemp(), "none.json")}):     # never read the developer's own hud.json
            c = HudView(spec_path)
        c.timer.stop(); c.resize(w, h); c.set_nodes(nodes)
        self.addCleanup(lambda: dispose(c))
        c.set_state(mode, 0.0, mode.upper(), "")
        if goal:
            self.goal(c)
        step(c, secs)
        return c

    def goal(self, c, steps=STEPS, labels=LABELS, checks=(True, False)):
        c.set_state("working", 0.3, "RUNNING", "step 2 of 4")
        c.set_goal("Create hello.py that prints the first 10 Fibonacci numbers")
        c.set_pipeline("ready", steps, list(checks), False, labels)
        c.set_stats({"elapsed": "00:27", "steps": "1/4", "checks": "1/2", "brain": "claude", "cost": "$0.024"})

    def ctx(self, c):
        return c._context()


class Design(HudBase):
    def test_it_draws_without_a_single_expression_error_in_every_state(self):
        c = self.make(goal=True)
        for mode in ("starting", "idle", "working", "waiting", "ok", "bad", "stopping", "stopped"):
            c.set_state(mode, 0.5, mode.upper(), "sub")
            step(c, 1.2); render(c)
        self.assertEqual(c.spec.runtime_errors(), [])
        self.assertFalse([l for l in c.log if "HUD" in l[1]], list(c.log))

    def test_every_element_type_the_schema_allows_has_a_renderer(self):
        self.assertEqual(set(S.ELEMENTS), set(draw.DRAW))

    def test_jarvis_is_cool_while_idle_and_friday_is_warm_while_working(self):
        idle, work = self.make(mode="idle"), self.make(goal=True)
        step(work, 3)
        for c, warm in ((idle, False), (work, True)):
            ctx = self.ctx(c)
            R, cx, cy = ctx["R"], ctx["cx"], ctx["cy"]
            r, g, b, n = glow_colour(render(c), (cx - 0.7 * R, cy - 0.7 * R, cx + 0.7 * R, cy + 0.7 * R))
            self.assertGreater(n, 300, "the core must actually be drawn")
            if warm:
                self.assertGreater(r, b + 40, (r, g, b))
            else:
                self.assertGreater(b, r + 25, (r, g, b))

    def test_the_two_minds_are_labelled_and_the_one_in_charge_is_lit(self):
        def lit(c):
            img = render(c)
            return energy(img, (44, 14, 100, 30)), energy(img, (144, 14, 200, 30))
        j_idle, f_idle = lit(self.make(mode="idle"))
        j_work, f_work = lit(self.make(goal=True, secs=5))
        self.assertGreater(j_idle, f_idle * 1.5, (j_idle, f_idle))
        self.assertGreater(f_work, j_work * 1.5, (f_work, j_work))

    def test_panels_show_on_a_wide_window_and_disappear_on_a_narrow_one(self):
        wide, narrow = self.make(goal=True), self.make(w=900, h=600, goal=True)
        cw, cn = self.ctx(wide), self.ctx(narrow)
        self.assertEqual(cw["wide"], 1); self.assertEqual(cn["wide"], 0)
        left = (36, 190, 200, 500)                                  # inside the mission panel; on the narrow window the dial is further right than this
        self.assertGreater(bright(render(wide), left, 140), bright(render(narrow), left, 140) + 120)       # writing in the panel, none without it
        self.assertEqual(cn["pw"], 0)

    def test_the_mission_panel_shows_the_real_steps_and_their_real_states(self):
        c = self.make(goal=True)
        ctx = self.ctx(c)
        box = (ctx["lx"] + 12, ctx["ph_top"] + 100, ctx["lx"] + ctx["pw"] - 12, ctx["ph_top"] + 100 + 22 * 4)
        green = lambda img: sum(1 for r, g, b in px(img, *box) if g > 150 and r < 120 and b < 190)          # the verified green (61, 227, 161)
        base = energy(render(c), box, 1)
        g1 = green(render(c))
        c.set_pipeline("ready", ["verified", "verified", "verified", "verified"], [True, True], True, LABELS)
        step(c, 0.1)
        g4 = green(render(c))
        self.assertGreater(g4, g1 * 2.2, (g1, g4))                                         # one verified row became four: the rows follow the real states
        c.set_pipeline("none", [], [], False, [])
        c.set_goal(""); step(c, 0.1)
        empty = energy(render(c), box, 1)
        self.assertLess(empty, base * 0.6)                                               # no goal: no step rows

    def test_a_row_per_brain_with_a_budget_meter(self):
        c = self.make(goal=True)
        ctx = self.ctx(c)
        busy = render(c)
        meter_y = ctx["ph_top"] + 44 + 46 * 1 + 24                                             # codex has spent 70%: its meter is filled
        filled = energy(busy, (ctx["rx"] + 60, meter_y, ctx["rx"] + 100, meter_y + 3))
        empty = energy(busy, (ctx["rx"] + 60, meter_y + 46 * 2, ctx["rx"] + 100, meter_y + 46 * 2 + 3))
        self.assertGreater(filled, empty * 1.3)

    def test_the_event_log_and_the_readout_show_real_lines_and_clear(self):
        c = self.make(goal=True)
        ctx = self.ctx(c)
        log_box = (ctx["lx"] + 10, ctx["by"] + 12, ctx["lx"] + 430, ctx["by"] + 128)
        empty = bright(render(c), log_box, 110)
        for i in range(9):
            c.add_log(f"event number {i}", "info", stamp="10:00:0%d" % i)
        c.add_log("event number 8", "info")                                                 # an immediate repeat is collapsed
        self.assertEqual(len(c.log), 7)
        self.assertEqual([t for _, t, _ in c.log][-1], "event number 8")
        self.assertGreater(bright(render(c), log_box, 110), empty + 150)
        stat_box = (ctx["rx"] + 10, ctx["by"] + 12, ctx["rx"] + ctx["pw"] - 10, ctx["by"] + 128)
        shown = bright(render(c), stat_box, 150)
        self.assertGreater(shown, 60)
        c.set_stats({}); c.set_pipeline("none", [], [], False, []); c.set_goal(""); step(c, 0.1)
        self.assertLess(bright(render(c), stat_box, 150), shown * 0.3)

    def test_the_voice_ring_is_an_equaliser_of_the_real_audio(self):
        c = self.make(mode="idle")
        c.set_voice("listening", 0.0, 0.0, False); step(c, 1.5)
        ctx = self.ctx(c); R = ctx["R"]
        ring = (ctx["cx"] - 1.1 * R, ctx["cy"] - 1.1 * R, ctx["cx"] + 1.1 * R, ctx["cy"] + 1.1 * R)
        quiet = energy(render(c), ring, 2)
        c.set_voice("hearing", 0.2, 0.0, True); step(c, 1.5)
        loud = energy(render(c), ring, 2)
        self.assertGreater(loud, quiet * 1.04)
        self.assertGreater(c.voice_amplitude(), 0.5)
        c.set_voice("speaking", 0.0, 0.8, False)
        self.assertAlmostEqual(c.voice_amplitude(), 0.8)

    def test_a_goal_that_verifies_sends_a_shockwave_once_and_failure_flashes_red(self):
        c = self.make(goal=True, secs=3)
        c.set_state("ok", 1.0, "VERIFIED", "2 checks passed")
        self.assertIsNotNone(c.motion.shock)
        step(c, 2.5)
        self.assertIsNone(c.motion.shock)
        c.set_state("bad", 1.0, "FAILED", "x"); step(c, 2.5)
        ctx = self.ctx(c); R = ctx["R"]
        r, g, b, n = glow_colour(render(c), (ctx["cx"] - 0.5 * R, ctx["cy"] - 0.5 * R, ctx["cx"] + 0.5 * R, ctx["cy"] + 0.5 * R), 90)
        self.assertGreater(r, g * 1.15)

    def test_the_hud_draws_itself_in_at_boot_and_is_complete_afterwards(self):
        c = self.make(secs=0.0)
        c.set_state("starting", 0, "STARTING", "")
        early = energy(render(c), (0, 0, 1280, 760), 4)
        step(c, 1.5); mid = energy(render(c), (0, 0, 1280, 760), 4)
        step(c, 4.0); late = energy(render(c), (0, 0, 1280, 760), 4)
        self.assertLess(early, mid); self.assertLess(mid, late)

    def test_the_caption_is_not_drawn_but_warnings_reach_the_event_feed(self):
        c = self.make()
        before = energy(render(c), (500, 692, 780, 752), 2)
        c.set_caption("How can I make you on a MCU Tony Stark level?")
        step(c, 3.0)
        self.assertAlmostEqual(before, energy(render(c), (500, 692, 780, 752), 2), delta=before * 0.06 + 200)
        c.set_caption("Voice is unavailable: no microphone", "warn")
        self.assertIn("Voice is unavailable: no microphone", [t for _, t, _ in c.log])


class Behaviour(HudBase):
    def test_a_frame_is_cheap_enough_to_animate(self):
        c = self.make(goal=True, secs=5)
        img = QImage(1280, 760, QImage.Format_ARGB32_Premultiplied)
        ts = []
        for _ in range(25):
            c.advance(1 / 30)
            t0 = time.perf_counter(); c.render(img); ts.append((time.perf_counter() - t0) * 1000)
        self.assertLess(sorted(ts)[len(ts) // 2], 140.0, ts)           # generous (CI software rendering); the governor handles the rest

    def test_static_layers_are_painted_once_not_every_frame(self):
        c = self.make(goal=True)
        render(c)
        first = {k: id(v[1]) for k, v in c._layer_pm.items()}
        self.assertTrue(first, "some layers must be cached")
        for _ in range(5):
            c.advance(1 / 30); render(c)
        self.assertEqual(first, {k: id(v[1]) for k, v in c._layer_pm.items()})
        c.resize(1000, 700); render(c)                                  # a resize does rebuild them
        self.assertNotEqual(first, {k: id(v[1]) for k, v in c._layer_pm.items()})

    def test_slow_frames_make_the_widget_drop_detail_by_itself(self):
        c = self.make(goal=True)
        for _ in range(c.quality.window):
            if c.quality.record(100.0):
                c.motion.set_level(c.quality.level)
        self.assertGreaterEqual(c.motion.level, 1)
        render(c)

    def test_the_api_the_window_uses_keeps_its_promises(self):
        c = self.make()
        self.assertEqual(c.ring_states(0), []); self.assertEqual(c.ring_states(1), [])
        c.set_pipeline("planning", ["running", "pending"], [True], False)
        self.assertEqual(c.ring_states(0), ["running"]); self.assertEqual(c.ring_states(1), ["running", "pending"]); self.assertEqual(c.ring_states(2), ["verified"])
        c.set_pipeline("ready", ["verified"], [True, True], True)
        self.assertEqual(c.ring_states(2), ["verified"])
        leg = dict((n, (t, k)) for n, t, k in c.legend())
        self.assertEqual(leg["VERIFY"], ("sealed", "ok")); self.assertEqual(leg["ACT"], ("1/1", "ok"))
        c.set_pipeline("failed", ["failed"], [], False)
        self.assertEqual(dict((n, (t, k)) for n, t, k in c.legend())["PLAN"], ("rejected", "bad"))
        self.assertEqual(c.caption_shown, "")
        c.set_caption("hello world"); c.cap_t = 0.1
        self.assertEqual(c.caption_shown, "hello w")
        c.set_caption("hello world"); self.assertAlmostEqual(c.cap_t, 0.1)          # setting the same text does not restart the typing
        c.set_footer("ROUTING FRUGAL"); self.assertEqual(c.footer, "ROUTING FRUGAL")

    def test_hostile_numbers_and_text_cannot_reach_the_painter(self):
        c = self.make()
        c.set_nodes([dict(node("x", 0), pressure=float("nan"), cooling_s=float("inf")), dict(node("y", 1), pressure=-5), dict(node("z", 2), pressure=99)])
        c.set_voice("hearing", float("nan"), float("inf"), True)
        c.set_state("working", float("nan"), "T" * 5000, "S" * 5000)
        c.set_goal("G" * 5000)
        c.set_stats({"cost": "9" * 4000, "elapsed": None})
        c.set_pipeline("ready", ["running"] * 400, [True] * 400, False, ["L" * 4000] * 400)
        for _ in range(20):
            c.add_log("L" * 3000, "bad")
        c.advance(float("nan")); c.advance(float("inf")); c.advance(-3.0); c.advance(1e9)
        for w, h in ((81, 81), (300, 200), (1280, 760), (3000, 400), (400, 2000)):
            c.resize(w, h); render(c)
        self.assertEqual(c.spec.runtime_errors(), [])
        for n in c.nodes:
            self.assertTrue(0.0 <= n["pressure"] <= 1.0)

    def test_many_nodes_and_degenerate_sizes_never_crash(self):
        many = [node(f"f{i}", i % 3, n=2) for i in range(40)]
        for w, h in ((560, 300), (700, 340), (1400, 520), (1920, 1080), (80, 80), (79, 79)):
            c = self.make(w, h, nodes=many, secs=0.3); render(c)
        c = self.make(nodes=[], secs=0.3); render(c)

    def test_clicking_the_core_pokes_it_and_clicking_elsewhere_does_not(self):
        c = self.make()
        ctx = self.ctx(c)
        def click(x, y):
            c.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y), QPointF(x, y), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
        c.motion.ripples.clear(); f0 = c.motion.flare
        click(5, 5); self.assertEqual(c.motion.ripples, []); self.assertEqual(c._poke, 0.0)
        click(ctx["cx"], ctx["cy"]); self.assertTrue(c.motion.ripples); self.assertEqual(c._poke, 1.0); self.assertGreater(c.motion.flare, f0)

    def test_pointing_at_a_brain_names_it_and_explains_it(self):
        c = self.make(goal=True)
        render(c)
        self.assertTrue(c._hits, "brain rows are hit-testable")
        item, rect = c._hits[1]
        with mock.patch.object(view_mod.QToolTip, "showText") as show:
            c.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, rect.center(), c.mapToGlobal(rect.center()), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
        self.assertEqual(c._hover, "codex")
        self.assertIn("codex", show.call_args[0][1]); self.assertIn("budget spent: 70%", show.call_args[0][1])
        c.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(3, 3), c.mapToGlobal(QPointF(3, 3)), Qt.NoButton, Qt.NoButton, Qt.NoModifier))
        self.assertEqual(c._hover, "")

    def test_reduced_motion_slows_everything_down(self):
        with mock.patch.object(view_mod, "REDUCED", True):
            c = self.make(secs=0.0)
            t0 = c.motion.t; c.advance(0.2)
            self.assertAlmostEqual(c.motion.t - t0, 0.04, places=3)
            c.set_state("working", 0, "RUNNING", ""); self.assertEqual(c._base_ms, 80)

    def test_calm_states_run_slower_and_a_window_nobody_looks_at_slower_still(self):
        c = self.make(secs=0.0)
        c.set_state("idle", 0, "READY", ""); calm = c._base_ms
        c.set_state("working", 0, "RUNNING", ""); busy = c._base_ms
        self.assertGreater(calm, busy)
        w = mock.Mock(); w.isMinimized.return_value = False; w.isActiveWindow.return_value = True
        with mock.patch.object(c, "window", return_value=w), mock.patch.object(c, "isVisible", return_value=True):
            self.assertEqual(c._pace(), 33)
            w.isActiveWindow.return_value = False; self.assertEqual(c._pace(), 66)
            w.isMinimized.return_value = True; self.assertEqual(c._pace(), 500)
            t0 = c.motion.t; c._last -= 0.5; c._tick(); self.assertEqual(c.motion.t, t0)

    def test_a_bug_while_painting_cannot_leave_a_painter_open(self):
        c = self.make(goal=True)
        orig = draw.DRAW["text"]
        def boom(*a, **k): raise RuntimeError("bug in a draw routine")
        with mock.patch.dict(draw.DRAW, {"text": boom}):
            render(c); render(c)
        self.assertTrue([l for l in c.log if "HUD draw error" in l[1]])
        render(c)                                                       # and it paints normally again afterwards

    def test_dispose_stops_the_timer(self):
        c = self.make(secs=0.0)
        c.timer.start(33); self.assertTrue(c.timer.isActive()); c.dispose(); self.assertFalse(c.timer.isActive())


class Editable(HudBase):
    """The design is a file: edit it while PRAXIS runs and the screen follows; a mistake never breaks the window."""

    def write(self, d, name="hud.json", mutate=None):
        raw = json.loads(json.dumps(specmod.load(specmod.DEFAULT_PATH).raw))
        if mutate:
            mutate(raw)
        p = os.path.join(d, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(raw, f)
        return p

    def bump(self, p):
        os.utime(p, (time.time() + 5, time.time() + 5))

    def test_a_custom_design_file_is_used_and_a_saved_edit_changes_the_screen(self):
        d = tempfile.mkdtemp()
        p = self.write(d)
        c = self.make(spec_path=p, secs=3)
        before = glow_colour(render(c), (500, 250, 780, 520))
        raw = json.load(open(p)); raw["palette"]["jarvis"] = "#ff00ff"; raw["name"] = "magenta"
        json.dump(raw, open(p, "w")); self.bump(p)
        self.assertTrue(c.reload_if_changed())
        self.assertEqual(c.spec.name, "magenta")
        step(c, 2)
        after = glow_colour(render(c), (500, 250, 780, 520))
        self.assertGreater(after[0], before[0] + 30)                                 # it turned pink
        self.assertIn("HUD design reloaded: magenta", [t for _, t, _ in c.log])

    def test_a_broken_edit_keeps_the_last_good_design_and_says_why_once(self):
        d = tempfile.mkdtemp()
        p = self.write(d)
        c = self.make(spec_path=p, secs=2)
        name = c.spec.name
        raw = json.load(open(p)); raw["layers"][3]["opacity"] = "0.5 *"
        json.dump(raw, open(p, "w")); self.bump(p)
        self.assertFalse(c.reload_if_changed())
        self.assertEqual(c.spec.name, name)
        errs = [t for _, t, l in c.log if "HUD spec error" in t]
        self.assertEqual(len(errs), 1); self.assertIn("layers[3]", errs[0])
        c.reload_if_changed(); c.reload_if_changed()
        self.assertEqual(len([t for _, t, l in c.log if "HUD spec error" in t]), 1)       # not repeated every second
        render(c)                                                                          # still draws the old design
        open(p, "w").write("{not json"); self.bump(p)
        self.assertFalse(c.reload_if_changed())
        raw = json.load(open(specmod.DEFAULT_PATH)); raw["name"] = "fixed"
        json.dump(raw, open(p, "w")); os.utime(p, (time.time() + 20, time.time() + 20))
        self.assertTrue(c.reload_if_changed()); self.assertEqual(c.spec.name, "fixed")        # and recovers

    def test_a_bad_file_at_start_falls_back_to_the_shipped_design(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "hud.json"); open(p, "w").write("{broken")
        with mock.patch.dict(os.environ, {"PRAXIS_HUD": p}):
            c = HudView()
        c.timer.stop(); self.addCleanup(lambda: dispose(c))
        self.assertTrue(c.spec.ok)
        self.assertEqual(c.spec_source, specmod.DEFAULT_PATH)
        self.assertTrue([t for _, t, l in c.log if "hud.json" in t], list(c.log))
        render(c)

    def test_a_user_file_is_found_by_the_environment_variable(self):
        d = tempfile.mkdtemp()
        p = self.write(d, mutate=lambda r: r.update(name="mine"))
        with mock.patch.dict(os.environ, {"PRAXIS_HUD": p}):
            c = HudView()
        c.timer.stop(); self.addCleanup(lambda: dispose(c))
        self.assertEqual(c.spec.name, "mine")

    def test_an_expression_that_fails_while_drawing_is_reported_and_the_rest_still_draws(self):
        def mutate(raw):
            raw["layers"].append({"type": "text", "text": "{t.nonsense}", "x": 10, "y": 700, "w": 100, "h": 14, "color": "text"})
            raw["layers"].append({"type": "circle", "x": "t.x", "y": 100, "r": 20, "fill": "accent"})
        c = self.make(spec_path=self.write(tempfile.mkdtemp(), mutate=mutate), secs=1)
        render(c); render(c)
        self.assertTrue(c.spec.runtime_errors())
        self.assertTrue([t for _, t, l in c.log if t.startswith("HUD ")], list(c.log))
        ctx = self.ctx(c)
        self.assertGreater(energy(render(c), (ctx["cx"] - 40, ctx["cy"] - 40, ctx["cx"] + 40, ctx["cy"] + 40), 2), 5000)    # the core is still there

    def test_a_stream_is_drawn_only_to_the_brain_being_called(self):
        raw = {"version": 1, "name": "stream", "palette": {k: "#ffffff" for k in ("text", "muted", "dim", "accent", "ok", "warn", "bad")},
               "modes": {m: {k: 0 for k in S.MODE_KEYS_REQUIRED} for m in S.REQUIRED_MODES},
               "layers": [{"type": "repeat", "source": "nodes", "x": 700, "y": 200, "dy": 120, "item": [
                   {"type": "courier", "active": "item.active", "x1": -600, "y1": 100, "x2": 0, "y2": 0, "bend": 0.0, "color": "accent", "count": 40}]}]}
        raw["palette"]["void"] = "#000000"
        p = os.path.join(tempfile.mkdtemp(), "s.json")
        with open(p, "w") as f:
            json.dump(raw, f)
        c = self.make(spec_path=p, nodes=NODES[:2], secs=0.5)
        c.set_active(""); idle = render(c)
        c.set_active("claude/x"); step(c, 0.2); busy = render(c)
        self.assertLess(bright(idle, (0, 0, 1280, 760), 40), 20)
        self.assertGreater(bright(busy, (0, 100, 720, 330), 40), 120)                      # sparks along the curve into the row of the brain in flight
        self.assertLess(bright(busy, (0, 330, 720, 700), 40), 40)                          # and none to the other one

    def test_the_data_rows_carry_real_meaning_colours_for_each_brain_and_each_step(self):
        raw = {"version": 1, "name": "rows", "palette": {"void": "#000000", "text": "#ffffff", "muted": "#ffffff", "dim": "#222222", "accent": "#00ffff",
                                                          "ok": "#00ff00", "warn": "#ffff00", "bad": "#ff0000", "violet": "#ff00ff"},
               "modes": {m: {k: 0 for k in S.MODE_KEYS_REQUIRED} for m in S.REQUIRED_MODES},
               "states": {"verified": "ok", "failed": "bad", "running": "accent", "pending": "dim", "waiting": "warn"},
               "layers": [{"type": "repeat", "source": "nodes", "x": 40, "y": 40, "dy": 60, "item": [{"type": "circle", "r": 20, "fill": "=item.color"},
                                                                                                      {"type": "circle", "x": 60, "r": 20, "fill": "=item.subcolor"}]},
                          {"type": "repeat", "source": "steps", "x": 400, "y": 40, "dy": 60, "item": [{"type": "circle", "r": 20, "fill": "=item.color"}]}]}
        p = os.path.join(tempfile.mkdtemp(), "r.json")
        with open(p, "w") as f:
            json.dump(raw, f)
        nodes = [node("local", 0, "local"), node("free", 1), node("sub", 2), node("blocked", 2, blocked=True), node("spent", 2, press=0.95), node("warm", 2, press=0.7)]
        c = self.make(spec_path=p, nodes=nodes, secs=0.3)
        c.set_pipeline("ready", ["verified", "failed", "running", "pending", "waiting"], [], False)
        img = render(c)
        col = lambda x, y: tuple(int(v) for v in (img.pixelColor(x, y).red(), img.pixelColor(x, y).green(), img.pixelColor(x, y).blue()))
        near = lambda a, b: all(abs(a[i] - b[i]) < 30 for i in range(3))
        want = [(0, 255, 0), (0, 255, 255), (255, 0, 255), (255, 0, 0), (255, 0, 255), (255, 0, 255)]          # local, free, subscription, blocked...
        for i, w in enumerate(want):
            self.assertTrue(near(col(40, 40 + 60 * i), w), (i, col(40, 40 + 60 * i), w))
        subs = [(0, 255, 255)] * 3 + [(255, 0, 0), (255, 0, 0), (255, 255, 0)]                                  # ...and the budget colour: red when blocked or nearly spent, amber when warm
        subs[0] = (0, 255, 255)
        for i, w in enumerate(subs):
            self.assertTrue(near(col(100, 40 + 60 * i), w), ("sub", i, col(100, 40 + 60 * i), w))
        for i, w in enumerate([(0, 255, 0), (255, 0, 0), (0, 255, 255), (34, 34, 34), (255, 255, 0)]):
            self.assertTrue(near(col(400, 40 + 60 * i), w), ("step", i, col(400, 40 + 60 * i), w))

    def tiny(self, layers, **extra):
        raw = {"version": 1, "name": "t", "palette": {"void": "#000000", "text": "#ffffff", "muted": "#ffffff", "dim": "#ffffff", "accent": "#ffffff",
                                                       "ok": "#ffffff", "warn": "#ffffff", "bad": "#ffffff"},
               "modes": {m: {k: 0 for k in S.MODE_KEYS_REQUIRED} for m in S.REQUIRED_MODES}, "layers": layers}
        raw.update(extra)
        p = os.path.join(tempfile.mkdtemp(), "t.json")
        with open(p, "w") as f:
            json.dump(raw, f)
        return p

    def test_visibility_opacity_and_the_boot_sequence_are_honoured_for_every_element(self):
        dot = lambda x, **kw: dict(type="circle", x=x, y=100, r=20, fill="accent", **kw)
        layers = [dot(60, id="plain"), dot(160, visible=False), dot(260, visible="W > 2000"), dot(360, visible="W < 2000"), dot(460, opacity=0.0),
                  {"type": "group", "opacity": 0.0, "children": [dot(560)]}, {"type": "group", "children": [dot(660, opacity=0.5)]}, dot(760, boot=30),
                  dot(860, visible="mode == 'working'")]
        c = self.make(spec_path=self.tiny(layers), secs=0.0)
        c.set_state("idle", 0, "x", "")
        lum = lambda img, x: sum(0.3 * r + 0.59 * g + 0.11 * b for r, g, b in px(img, x - 4, 96, x + 4, 104)) / 64
        c.motion.boot = 0.0
        early = render(c)
        step(c, 5.0)
        late = render(c)
        self.assertGreater(lum(late, 60), 200)                                  # plain
        self.assertLess(lum(late, 160), 5)                                      # visible: false
        self.assertLess(lum(late, 260), 5)                                      # visible expression that is false
        self.assertGreater(lum(late, 360), 200)                                 # ... and true
        self.assertLess(lum(late, 460), 5)                                      # opacity 0
        self.assertLess(lum(late, 560), 5)                                      # a group's opacity fades its children
        self.assertTrue(80 < lum(late, 660) < 180, lum(late, 660))              # half opacity
        self.assertLess(lum(early, 760), 5)                                     # not yet drawn in at the start of boot...
        self.assertGreater(lum(late, 760), 200)                                 # ...but there when the sequence finishes, even at index 30
        self.assertLess(lum(late, 860), 5)
        c.set_state("working", 0, "x", ""); step(c, 0.2)
        self.assertGreater(lum(render(c), 860), 200)                            # a mode-dependent element appears with the mode

    def test_a_tiny_hand_written_design_works(self):
        raw = {"version": 1, "name": "tiny", "palette": {k: "#888888" for k in ("text", "muted", "dim", "accent", "ok", "warn", "bad")},
               "modes": {m: {k: 0 for k in S.MODE_KEYS_REQUIRED} for m in S.REQUIRED_MODES},
               "layers": [{"type": "circle", "x": "W / 2", "y": "H / 2", "r": 50, "fill": "accent"}]}
        raw["palette"]["void"] = "#000000"
        sp = specmod.compile_spec(raw)
        self.assertTrue(sp.ok, sp.report())
        p = os.path.join(tempfile.mkdtemp(), "t.json"); json.dump(raw, open(p, "w"))
        c = self.make(spec_path=p, secs=0.5)
        img = render(c)
        self.assertGreater(energy(img, (600, 330, 680, 430), 2), 100000)
        self.assertLess(energy(img, (0, 0, 100, 100), 2), 1000)


if __name__ == "__main__":
    unittest.main()
