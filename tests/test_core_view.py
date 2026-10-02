"""Renders the real particle-sphere widget offscreen and checks what a person would actually see (needs PySide6)."""
import math, os, unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QImage, QMouseEvent
    from PySide6.QtWidgets import QApplication
    from praxis.desktop.qt import core as core_mod, particles as P, theme
    from praxis.desktop.qt.core import CoreView
    HAVE_QT = True
except Exception:
    HAVE_QT = False


def node(fam, cc, priv="cloud", press=0.0, cool=0, blocked=False, n=1):
    return dict(family=fam, cost_class=cc, privacy=priv, pressure=press, cooling_s=cool, blocked=blocked, delegate_only=False,
                usage={"24h": {"calls": 3, "cost": 0.0}},
                models=[dict(name=f"{fam}/m{i}", tier="best", score=0.9, cost=0.0, tps=None, cooling_s=0) for i in range(n)])


NODES = [node("ollama", 0, "local"), node("groq", 1, press=0.5), node("gemini", 1, "open", blocked=True),
         node("claude", 2, n=3), node("codex", 2, cool=1500)]


def step(core, secs, fps=30):
    for _ in range(int(secs * fps)):
        core.advance(1.0 / fps)


def render(core):
    core.repaint()
    return core.grab().toImage().convertToFormat(QImage.Format_RGB32)


def mean_colour(img, cx, cy, r, min_luma=70):
    """Mean RGB of the bright pixels inside a disc: the colour of the glowing points, not the dark background."""
    sr = sg = sb = n = 0
    for y in range(max(0, int(cy - r)), min(img.height(), int(cy + r))):
        for x in range(max(0, int(cx - r)), min(img.width(), int(cx + r))):
            if (x - cx) ** 2 + (y - cy) ** 2 > r * r:
                continue
            c = img.pixelColor(x, y)
            if 0.3 * c.red() + 0.59 * c.green() + 0.11 * c.blue() >= min_luma:
                sr += c.red(); sg += c.green(); sb += c.blue(); n += 1
    return (sr / n, sg / n, sb / n, n) if n else (0, 0, 0, 0)


@unittest.skipUnless(HAVE_QT, "PySide6 not available")
class Core(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui, mono = theme.fonts()
        cls.app.setStyleSheet(theme.qss(ui, mono))

    def make(self, w=1000, h=420, nodes=NODES, n=1200):
        c = CoreView(); c.timer.stop()
        c.field.resize(n)                      # fewer points keep the tests quick; the logic is identical
        c.resize(w, h); c.set_nodes(nodes); c.show()
        self.addCleanup(c.close)
        step(c, 2.5)                           # past the assembly intro
        return c

    def colour_of(self, mode, **kw):
        c = self.make()
        c.set_state(mode, kw.get("progress", 0.0), mode.upper(), "")
        step(c, 3.0)
        g = c._geo()
        return mean_colour(render(c), g["cx"], g["cy"], g["R"] * 0.95)

    # ---- the sphere's colour is the state -------------------------------------------------------------
    def test_each_state_is_a_different_colour_you_can_read_at_a_glance(self):
        idle, ok, bad, wait, work = (self.colour_of(m) for m in ("idle", "ok", "bad", "waiting", "working"))
        for name, col in (("idle", idle), ("ok", ok), ("bad", bad), ("waiting", wait), ("working", work)):
            self.assertGreater(col[3], 300, f"{name}: the sphere must actually be drawn")
        self.assertTrue(idle[2] >= idle[1], f"idle is blue/violet/pink, got {idle}")
        self.assertTrue(ok[1] > ok[0] and ok[1] > idle[1] * 1.15, f"verified is green: {ok} vs idle {idle}")
        self.assertTrue(bad[0] > bad[1] * 1.3 and bad[0] > idle[0], f"failed is red: {bad}")
        self.assertTrue(wait[0] > wait[2] * 1.25 and wait[1] > wait[2], f"needs-you is amber: {wait}")
        self.assertTrue(work[1] > work[0] and work[2] > work[0] * 1.3, f"working is cyan: {work}")

    def test_the_sphere_is_the_brightest_thing_in_the_frame(self):
        c = self.make()
        img = render(c)
        g = c._geo()
        centre = mean_colour(img, g["cx"], g["cy"], g["R"] * 0.9, min_luma=0)
        corner = mean_colour(img, 40, 40, 30, min_luma=0)
        luma = lambda t: 0.3 * t[0] + 0.59 * t[1] + 0.11 * t[2]
        self.assertGreater(luma(centre), luma(corner) * 3)

    # ---- real state shows up as pixels ----------------------------------------------------------------------
    def test_a_call_in_flight_draws_a_stream_to_exactly_that_provider(self):
        c = self.make()
        c.set_state("working", 0.0, "RUNNING", ""); step(c, 0.5)
        base = render(c)
        c.set_active("groq/m0"); step(c, 0.3)
        lit = render(c)
        g = c._geo()
        pt = g["pos"][1][0]                                       # groq
        other = g["pos"][3][0]                                    # claude
        def diff(centre, r=70):
            d = 0
            for y in range(int(centre.y() - r), int(centre.y() + r), 2):
                for x in range(int(centre.x() - r), int(centre.x() + r), 2):
                    a, b = base.pixelColor(x, y), lit.pixelColor(x, y)
                    d += abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())
            return d
        self.assertGreater(diff(pt), diff(other) * 2)             # the glow and stream are around groq, not claude
        c.set_active("")
        self.assertEqual(c.active, "")

    def test_the_ring_fills_as_the_plan_progresses(self):
        c = self.make()
        c.set_state("working", 0.0, "RUNNING", ""); step(c, 1.0)
        empty = render(c)
        c.set_state("working", 1.0, "RUNNING", ""); step(c, 0.1)
        full = render(c)
        g = c._geo()
        rr = g["R"] * 1.34
        ring_lit = lambda img: mean_colour(img, g["cx"], g["cy"] - rr * 0.0, rr * 1.2, min_luma=150)[3]
        self.assertGreater(ring_lit(full), ring_lit(empty) * 1.05)

    def test_a_real_event_sends_a_ripple_but_a_burst_is_rate_limited_and_ripples_expire(self):
        c = self.make()
        self.assertEqual(c.ripples, [])
        c.pulse("ok"); c.pulse("ok"); c.pulse("warn")
        self.assertEqual(len(c.ripples), 1)                       # three events in the same instant: one ripple, readable
        step(c, 0.2); c.pulse("bad")
        self.assertEqual(len(c.ripples), 2)
        for _ in range(20):
            step(c, 0.2); c.pulse("info")
        self.assertLessEqual(len(c.ripples), 6)
        step(c, 3.0)
        self.assertEqual(c.ripples, [])

    def test_verified_triggers_the_shockwave_and_a_ripple_once(self):
        c = self.make()
        c.set_state("working", 0.5, "RUNNING", ""); step(c, 0.5)
        self.assertIsNone(c.field.shock)
        c.set_state("ok", 1.0, "VERIFIED", "")
        self.assertIsNotNone(c.field.shock); self.assertEqual(len(c.ripples), 1)
        step(c, 0.2); c.set_state("ok", 1.0, "VERIFIED", "again")      # same state again: no second shockwave
        self.assertEqual(len(c.ripples), 1)

    def test_starting_assembles_the_sphere_from_scattered_points(self):
        c = CoreView(); c.timer.stop(); c.field.resize(800); c.resize(900, 400); c.show(); self.addCleanup(c.close)
        self.assertEqual(c.field.asm, 0.0)
        step(c, 0.4); self.assertTrue(0.0 < c.field.asm < 1.0)
        step(c, 2.0); self.assertEqual(c.field.asm, 1.0)
        c.set_state("idle", 0, "READY", ""); c.set_state("starting", 0, "STARTING", "")
        self.assertEqual(c.field.asm, 0.0)                         # re-scatters when it restarts (e.g. a new workspace)

    def test_stopping_pulls_the_sphere_in_and_a_bad_end_flashes_red(self):
        c = self.make()
        c.set_state("working", 0.5, "RUNNING", ""); step(c, 1.0)
        c.set_state("stopping", 0.5, "STOPPING", ""); step(c, 0.5)
        self.assertLess(c.field.dyn.v["scale"], 0.7)
        self.assertEqual(c.ripples[-1][1], "warn")
        c.set_state("bad", 0.5, "FAILED", ""); self.assertEqual(c.ripples[-1][1], "bad")

    # ---- the typed caption ------------------------------------------------------------------------------------------
    def test_the_caption_types_out_and_does_not_restart_when_set_to_the_same_text(self):
        c = self.make()
        c.set_caption("Asking groq/gpt-oss-120b (planner)...")
        self.assertEqual(c.caption_shown, "")
        step(c, 0.1); n1 = len(c.caption_shown)
        self.assertTrue(0 < n1 < len(c.caption))
        step(c, 0.1); c.set_caption("Asking groq/gpt-oss-120b (planner)...")      # a tick re-asserting the same text
        self.assertGreater(len(c.caption_shown), n1)                               # kept typing; did not restart
        step(c, 2.0); self.assertEqual(c.caption_shown, c.caption)
        c.set_caption("Plan accepted: 3 step(s)"); self.assertEqual(c.caption_shown, "")

    # ---- layout --------------------------------------------------------------------------------------------------------
    def test_nodes_flank_the_sphere_by_cost_class_and_never_touch_it(self):
        c = self.make(1000, 420)
        g = c._geo()
        for i, nd in enumerate(c.nodes):
            pt, side = g["pos"][i]
            self.assertEqual(side, -1 if nd["cost_class"] <= 1 else 1, nd["family"])          # free/local left, subscriptions right
            self.assertGreater(math.hypot(pt.x() - g["cx"], pt.y() - g["cy"]), g["R"] * 1.34 + g["nr"])
            self.assertTrue(130 <= pt.x() <= c.width() - 130 and g["top"] - 10 <= pt.y() <= c.height() - 40, (nd["family"], pt))

    def test_one_sided_node_sets_are_split_evenly_instead_of_a_lopsided_column(self):
        subs = [node(f"s{i}", 2) for i in range(6)]
        c = self.make(1000, 420, nodes=subs)
        sides = [c._geo()["pos"][i][1] for i in range(6)]
        self.assertEqual((sides.count(-1), sides.count(1)), (3, 3))

    def test_everything_fits_at_the_minimum_size_and_with_many_nodes(self):
        many = [node(f"f{i}", i % 3) for i in range(12)]
        for w, h in ((560, 300), (700, 340), (1400, 520)):
            c = self.make(w, h, nodes=many, n=600)
            g = c._geo()
            for i in range(12):
                pt, side = g["pos"][i]
                self.assertTrue(0 <= pt.x() <= w and 0 <= pt.y() <= h, (w, h, i, pt))
            img = render(c)
            self.assertEqual((img.width(), img.height()), (w, h))

    def test_degenerate_sizes_and_empty_data_never_crash(self):
        c = self.make(n=300)
        for w, h in ((1, 1), (50, 50), (79, 500), (600, 79), (3000, 120)):
            c.resize(w, h); render(c)
        c.resize(800, 400); c.set_nodes([]); c.set_active("nobody/x"); c.set_footer(""); c.set_caption(""); render(c)

    # ---- interaction & performance ---------------------------------------------------------------------------------------
    def test_the_sphere_leans_toward_the_cursor_and_relaxes_when_it_leaves(self):
        c = self.make()
        g = c._geo()
        ev = QMouseEvent(QEvent.MouseMove, QPointF(g["cx"] + 260, g["cy"] - 90), QPointF(0, 0), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        c.mouseMoveEvent(ev)
        self.assertNotEqual(c.field.tilt_target, [0.0, 0.0])
        step(c, 1.0); self.assertGreater(abs(c.field.tilt[1]), 0.05)
        c.leaveEvent(QEvent(QEvent.Leave))
        self.assertEqual(c.field.tilt_target, [0.0, 0.0])

    def test_clicking_the_sphere_pokes_it_and_clicking_elsewhere_does_not(self):
        c = self.make()
        g = c._geo()
        mk = lambda x, y: QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y), QPointF(0, 0), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        c.mousePressEvent(mk(20, 20)); self.assertEqual(c.ripples, [])
        c.mousePressEvent(mk(g["cx"], g["cy"])); self.assertEqual(len(c.ripples), 1)

    def test_slow_frames_make_the_widget_drop_detail_by_itself(self):
        c = self.make(n=3000)
        c.quality.limit, c.quality.patience = 0.0001, 5          # pretend every frame is far too slow
        n0 = c.field.n
        for _ in range(12):
            render(c)
        self.assertLess(c.field.n, n0); self.assertEqual(c.field.n, c.quality.n)

    def test_a_frame_is_cheap_enough_to_animate(self):
        import time
        c = self.make(1000, 420, n=P.LEVELS[0])
        c.set_state("working", 0.5, "RUNNING", "step 2 of 4"); c.set_active("groq/m0"); step(c, 1.0)
        t0 = time.perf_counter()
        for _ in range(15):
            c.advance(1 / 30); c.repaint()
        ms = 1000 * (time.perf_counter() - t0) / 15
        self.assertLess(ms, 150, f"a frame took {ms:.0f} ms: far too slow to animate")      # generous: this guards against pathologies

    def test_reduced_motion_slows_everything_down(self):
        with mock.patch.object(core_mod, "REDUCED", True):
            c = CoreView(); self.addCleanup(c.close); c.timer.stop()
            self.assertEqual(c.field.n, P.LEVELS[2])
            c.set_state("working", 0, "RUNNING", ""); self.assertEqual(c.timer.interval(), 80)
            t0 = c.field.t; c.advance(0.2)
            self.assertAlmostEqual(c.field.t - t0, 0.04, places=3)

    def test_calm_states_run_at_a_lower_frame_rate_than_working(self):
        c = self.make()
        c.set_state("idle", 0, "READY", ""); calm = c.timer.interval()
        c.set_state("working", 0, "RUNNING", ""); busy = c.timer.interval()
        self.assertGreater(calm, busy)


if __name__ == "__main__":
    unittest.main()
