"""Renders the real "Loom" widget offscreen and checks what a person would actually see (needs PySide6)."""
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


def pixels(img, x0, y0, x1, y1, stride=1):
    for y in range(max(0, int(y0)), min(img.height(), int(y1)), stride):
        for x in range(max(0, int(x0)), min(img.width(), int(x1)), stride):
            c = img.pixelColor(x, y)
            yield x, y, c.red(), c.green(), c.blue()


def mean_colour(img, box, min_luma=70):
    """Mean RGB of the bright pixels in a box: the colour of the glowing particles, not the dark background."""
    sr = sg = sb = n = 0
    for x, y, r, g, b in pixels(img, *box):
        if 0.3 * r + 0.59 * g + 0.11 * b >= min_luma:
            sr += r; sg += g; sb += b; n += 1
    return (sr / n, sg / n, sb / n, n) if n else (0, 0, 0, 0)


def count(img, box, pred, stride=1):
    return sum(1 for x, y, r, g, b in pixels(img, *box, stride=stride) if pred(r, g, b))


GREEN = lambda r, g, b: g > 150 and g > b + 25 and g > r + 60          # the verified green (61, 227, 161), not cyan
RED = lambda r, g, b: r > 170 and r > g + 80 and r > b + 40            # failure red / pink


@unittest.skipUnless(HAVE_QT, "PySide6 not available")
class Loom(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui, mono = theme.fonts()
        cls.app.setStyleSheet(theme.qss(ui, mono))

    def make(self, w=1100, h=430, nodes=NODES, n=1000):
        c = CoreView(); c.timer.stop()
        c.field.resize(n)                      # fewer points keep the tests quick; the logic is identical
        c.resize(w, h); c.set_nodes(nodes); c.show()
        self.addCleanup(c.close)
        step(c, 3.0)                           # past the assembly intro
        return c

    def gal_box(self, c):
        g = c._geo()
        return (g["cx"] - 1.6 * g["R"], g["cy"] - 0.9 * g["R"], g["cx"] + 1.6 * g["R"], g["cy"] + 0.9 * g["R"])

    def side_box(self, c):                     # the galaxy and its rings, but not the provider nodes on the flanks (Ollama's is green too)
        g = c._geo()
        return (g["cx"] - core_mod.RING_HALF * g["R"], g["top"] - 10, g["cx"] + core_mod.RING_HALF * g["R"], c.height() - g["bot"])

    # ---- the colour is the state ------------------------------------------------------------------------------------
    def colour_of(self, mode):
        c = self.make()
        c.set_state(mode, 0.0, mode.upper(), ""); step(c, 3.0)
        return mean_colour(render(c), self.gal_box(c))

    def test_each_state_is_a_different_colour_you_can_read_at_a_glance(self):
        idle, ok, bad, wait, work = (self.colour_of(m) for m in ("idle", "ok", "bad", "waiting", "working"))
        for name, col in (("idle", idle), ("ok", ok), ("bad", bad), ("waiting", wait), ("working", work)):
            self.assertGreater(col[3], 150, f"{name}: the galaxy must actually be drawn")
        self.assertTrue(idle[2] >= idle[1], f"idle is blue/violet, got {idle}")
        self.assertTrue(ok[1] > ok[0] and ok[1] > idle[1] * 1.1, f"verified is green: {ok} vs idle {idle}")
        self.assertTrue(bad[0] > bad[1] * 1.2 and bad[0] > idle[0], f"failed is red/pink: {bad}")
        self.assertTrue(wait[0] > wait[2] * 1.15 and wait[1] > wait[2], f"needs-you is amber: {wait}")
        self.assertTrue(work[1] > work[0] and work[2] > work[0] * 1.2, f"working is cyan: {work}")

    def test_the_galaxy_is_the_brightest_thing_in_the_frame_and_the_seed_its_brightest_point(self):
        c = self.make()
        img = render(c)
        g = c._geo()
        luma = lambda t: 0.3 * t[0] + 0.59 * t[1] + 0.11 * t[2]
        centre = mean_colour(img, (g["cx"] - 6, g["cy"] - 6, g["cx"] + 6, g["cy"] + 6), min_luma=0)
        arms = mean_colour(img, self.gal_box(c), min_luma=0)
        corner = mean_colour(img, (20, 20, 60, 60), min_luma=0)
        self.assertGreater(luma(arms), luma(corner) * 2)
        self.assertGreater(luma(centre), luma(arms) * 1.5)

    # ---- the three rings show real data ------------------------------------------------------------------------------
    def test_the_act_ring_arcs_are_the_real_steps_in_their_real_states(self):
        c = self.make()
        c.set_pipeline("ready", ["verified", "running", "pending", "waiting"], [])
        self.assertEqual(c.ring_states(1), ["verified", "running", "pending", "waiting"])
        c.set_pipeline("ready", ["verified"] * 4, []); step(c, 0.2)
        good = render(c)
        c.set_pipeline("ready", ["failed"] * 4, []); step(c, 0.2)
        bad = render(c)
        box = self.side_box(c)
        self.assertGreater(count(good, box, GREEN), count(bad, box, GREEN) * 3 + 20)        # four green arcs vs none
        self.assertGreater(count(bad, box, RED), count(good, box, RED) * 3 + 20)            # four red arcs vs none

    def test_the_verify_ring_has_one_arc_per_check_and_seals_shut_when_the_goal_verifies(self):
        c = self.make()
        c.set_pipeline("ready", ["verified"] * 3, [True, True, False])
        self.assertEqual(c.ring_states(2), ["verified", "verified", "failed"])
        c.set_pipeline("ready", ["verified"] * 3, [True, True, True]); step(c, 0.2)
        partial = render(c)
        c.set_pipeline("ready", ["verified"] * 3, [True, True, True], sealed=True)
        self.assertEqual(c.ring_states(2), ["verified"])                                    # one closed ring: no gaps left
        step(c, 0.2)
        sealed = render(c)
        box = self.side_box(c)
        self.assertGreater(count(sealed, box, GREEN), count(partial, box, GREEN))           # a closed ring is more green than arcs

    def test_the_plan_ring_follows_the_planning_stage(self):
        c = self.make()
        for plan, states in (("none", []), ("planning", ["running"]), ("ready", ["ran"]), ("failed", ["failed"])):
            c.set_pipeline(plan); self.assertEqual(c.ring_states(0), states, plan)

    def test_the_legend_shows_the_real_numbers(self):
        c = self.make()
        self.assertEqual(c.legend(), [("PLAN", "idle", "dim"), ("ACT", "-", "dim"), ("VERIFY", "-", "dim")])
        c.set_pipeline("planning")
        self.assertEqual(c.legend()[0], ("PLAN", "analysing", "accent"))
        c.set_pipeline("ready", ["verified", "verified", "running", "pending", "pending"], [True])
        self.assertEqual(c.legend(), [("PLAN", "ready", "accent"), ("ACT", "2/5", "accent"), ("VERIFY", "1/1", "accent")])
        c.set_pipeline("ready", ["ran", "ran", "pending"], [])
        self.assertEqual(c.legend()[1], ("ACT", "2/3", "dim"))                      # a step that has run counts as done
        c.set_pipeline("ready", ["verified", "waiting"], [])
        self.assertEqual(c.legend()[1], ("ACT", "1/2", "warn"))
        c.set_pipeline("ready", ["verified", "failed"], [True, False])
        self.assertEqual(c.legend()[1][2], "bad"); self.assertEqual(c.legend()[2], ("VERIFY", "1/2", "bad"))
        c.set_pipeline("ready", ["verified"] * 3, [True] * 3, sealed=True)
        self.assertEqual(c.legend(), [("PLAN", "ready", "accent"), ("ACT", "3/3", "ok"), ("VERIFY", "sealed", "ok")])
        c.set_pipeline("failed"); self.assertEqual(c.legend()[0], ("PLAN", "rejected", "bad"))

    # ---- motion is meaning ----------------------------------------------------------------------------------------------
    def test_arms_flow_inward_while_working_and_outward_when_verified(self):
        c = self.make()
        c.set_state("working", 0.2, "RUNNING", ""); step(c, 3.0)
        self.assertLess(c.field.dyn.v["flow"], -0.1)
        c.set_state("waiting", 0.2, "NEEDS YOU", ""); step(c, 4.0)
        self.assertLess(abs(c.field.dyn.v["flow"]), 0.03)
        c.set_state("ok", 1.0, "VERIFIED", ""); step(c, 3.0)
        self.assertGreater(c.field.dyn.v["flow"], 0.1)

    def test_a_call_in_flight_draws_a_stream_to_exactly_that_provider(self):
        c = self.make()
        c.set_state("working", 0.0, "RUNNING", ""); step(c, 0.5)
        base = render(c)
        c.set_active("groq/m0"); step(c, 0.3)
        lit = render(c)
        g = c._geo()
        pt, other = g["pos"][1][0], g["pos"][3][0]                # groq (left), claude (right)
        def diff(centre, r=70):
            d = 0
            for y in range(int(centre.y() - r), int(centre.y() + r), 2):
                for x in range(int(centre.x() - r), int(centre.x() + r), 2):
                    a, b = base.pixelColor(x, y), lit.pixelColor(x, y)
                    d += abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())
            return d
        self.assertGreater(diff(pt), diff(other) * 2)
        c.set_active(""); self.assertEqual(c.active, "")

    def test_every_real_event_flares_the_seed_and_ripples_but_a_burst_is_rate_limited_and_ripples_expire(self):
        c = self.make()
        self.assertEqual(c.ripples, []); self.assertEqual(c.field.flare, 0.0)
        c.pulse("ok"); c.pulse("ok"); c.pulse("warn")
        self.assertEqual(len(c.ripples), 1)                       # three events in the same instant: one ripple, readable
        self.assertAlmostEqual(c.field.flare, 0.8)                # ...and one flare
        step(c, 0.2); c.pulse("bad")
        self.assertEqual(len(c.ripples), 2)
        for _ in range(20):
            step(c, 0.2); c.pulse("info")
        self.assertLessEqual(len(c.ripples), 6); self.assertLessEqual(c.field.flare, 1.6)
        step(c, 3.0)
        self.assertEqual(c.ripples, []); self.assertEqual(c.field.flare, 0.0)

    def test_the_seed_visibly_flares_on_an_event(self):
        c = self.make()
        g = c._geo()
        box = (g["cx"] - 0.9 * g["R"], g["cy"] - 6, g["cx"] + 0.9 * g["R"], g["cy"] + 6)       # the streak's row
        quiet = count(render(c), box, lambda r, g_, b: r + g_ + b > 450)
        c.pulse("ok"); c.advance(0.02)
        flared = count(render(c), box, lambda r, g_, b: r + g_ + b > 450)
        self.assertGreater(flared, quiet)

    def test_verified_triggers_the_shockwave_and_a_flare_once(self):
        c = self.make()
        c.set_state("working", 0.5, "RUNNING", ""); step(c, 0.5)
        self.assertIsNone(c.field.shock)
        c.set_state("ok", 1.0, "VERIFIED", "")
        self.assertIsNotNone(c.field.shock); self.assertEqual(len(c.ripples), 1); self.assertGreater(c.field.flare, 1.0)
        step(c, 0.2); c.set_state("ok", 1.0, "VERIFIED", "again")       # same state again: no second shockwave
        self.assertEqual(len(c.ripples), 1)

    def test_starting_assembles_the_galaxy_from_scattered_points_and_unfolds_the_rings(self):
        c = CoreView(); c.timer.stop(); c.field.resize(800); c.resize(900, 400); c.show(); self.addCleanup(c.close)
        self.assertEqual(c.field.asm, 0.0)
        step(c, 0.4); self.assertTrue(0.0 < c.field.asm < 1.0)
        step(c, 2.2); self.assertEqual(c.field.asm, 1.0)
        c.set_state("idle", 0, "READY", ""); c.set_state("starting", 0, "STARTING", "")
        self.assertEqual(c.field.asm, 0.0)                         # re-scatters when it restarts (e.g. a new workspace)

    def test_stopping_pulls_it_in_and_a_bad_end_flashes_red(self):
        c = self.make()
        c.set_state("working", 0.5, "RUNNING", ""); step(c, 1.0)
        c.set_state("stopping", 0.5, "STOPPING", ""); step(c, 0.5)
        self.assertLess(c.field.dyn.v["scale"], 0.7); self.assertEqual(c.ripples[-1][1], "warn")
        c.set_state("bad", 0.5, "FAILED", ""); self.assertEqual(c.ripples[-1][1], "bad")

    def test_bloom_makes_the_glow_spill_beyond_the_particles(self):
        c = self.make(n=1500)
        c.set_state("working", 0.3, "RUNNING", ""); step(c, 1.0)
        c.quality.limit = 1e9                                       # keep the governor out of the comparison
        on = render(c)
        c.quality.level = 2                                         # bloom is dropped at the lower detail levels
        off = render(c)
        box = self.gal_box(c)
        luma = lambda img: sum(0.3 * r + 0.59 * g + 0.11 * b for x, y, r, g, b in pixels(img, *box, stride=2))
        self.assertGreater(luma(on), luma(off) * 1.05)

    # ---- the typed caption -----------------------------------------------------------------------------------------------
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

    # ---- layout ----------------------------------------------------------------------------------------------------------
    def test_nodes_flank_the_galaxy_by_cost_class_outside_the_widest_ring(self):
        for w, h in ((1000, 420), (824, 330), (560, 300), (1500, 520)):
            c = self.make(w, h, n=300)
            g = c._geo()
            for i, nd in enumerate(c.nodes):
                pt, side = g["pos"][i]
                self.assertEqual(side, -1 if nd["cost_class"] <= 1 else 1, (w, nd["family"]))        # free/local left, subscriptions right
                self.assertGreater(abs(pt.x() - g["cx"]), g["R"] * core_mod.RING_HALF * 0.98, (w, h, nd["family"]))
                self.assertTrue(0 <= pt.x() - 12 and pt.x() + 12 <= w and g["top"] - 20 <= pt.y() <= h - 40, (w, h, nd["family"], pt))

    def test_the_widest_ring_always_fits_the_room_it_has(self):
        for w, h in ((1100, 430), (824, 300), (560, 300), (1500, 520)):
            c = self.make(w, h, n=300)
            g = c._geo()
            self.assertLessEqual(g["R"] * core_mod.RING_HEIGHT, g["avail"] / 2 + 1.0, (w, h))      # never under the title or the caption
            self.assertLessEqual(g["R"] * core_mod.RING_HALF * 1.0, w / 2 - 20 + 1.0, (w, h))      # never clipped at the sides

    def test_one_sided_node_sets_are_split_evenly_instead_of_a_lopsided_column(self):
        subs = [node(f"s{i}", 2) for i in range(6)]
        c = self.make(1000, 420, nodes=subs, n=300)
        sides = [c._geo()["pos"][i][1] for i in range(6)]
        self.assertEqual((sides.count(-1), sides.count(1)), (3, 3))

    def test_many_nodes_and_degenerate_sizes_never_crash(self):
        many = [node(f"f{i}", i % 3) for i in range(12)]
        for w, h in ((560, 300), (700, 340), (1400, 520)):
            c = self.make(w, h, nodes=many, n=300)
            img = render(c); self.assertEqual((img.width(), img.height()), (w, h))
        c = self.make(n=300)
        for w, h in ((1, 1), (50, 50), (79, 500), (600, 79), (3000, 120)):
            c.resize(w, h); render(c)
        c.resize(800, 400); c.set_nodes([]); c.set_active("nobody/x"); c.set_footer(""); c.set_caption("")
        c.set_pipeline("ready", ["verified"] * 40, [True] * 40, sealed=True); render(c)                # 40 arcs on a ring: still fine

    # ---- interaction & performance ------------------------------------------------------------------------------------------
    def test_the_galaxy_leans_toward_the_cursor_and_relaxes_when_it_leaves(self):
        c = self.make()
        g = c._geo()
        ev = QMouseEvent(QEvent.MouseMove, QPointF(g["cx"] + 260, g["cy"] - 90), QPointF(0, 0), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        c.mouseMoveEvent(ev)
        self.assertNotEqual(c.field.tilt_target, [0.0, 0.0])
        step(c, 1.0); self.assertGreater(abs(c.field.tilt[1]), 0.05)
        c.leaveEvent(QEvent(QEvent.Leave))
        self.assertEqual(c.field.tilt_target, [0.0, 0.0])

    def test_clicking_the_galaxy_pokes_it_and_clicking_elsewhere_does_not(self):
        c = self.make()
        g = c._geo()
        mk = lambda x, y: QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y), QPointF(0, 0), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        c.mousePressEvent(mk(20, 20)); self.assertEqual(c.ripples, []); self.assertEqual(c.field.flare, 0.0)
        c.mousePressEvent(mk(g["cx"], g["cy"])); self.assertEqual(len(c.ripples), 1); self.assertGreater(c.field.flare, 1.0)

    def test_slow_frames_make_the_widget_drop_detail_by_itself(self):
        c = self.make(n=2500)
        c.quality.limit, c.quality.patience = 0.0001, 5          # pretend every frame is far too slow
        n0 = c.field.n
        for _ in range(12):
            render(c)
        self.assertLess(c.field.n, n0); self.assertEqual(c.field.n, c.quality.n)

    def test_a_frame_is_cheap_enough_to_animate(self):
        import time
        c = self.make(1000, 420, n=P.LEVELS[0])
        c.set_state("working", 0.5, "RUNNING", "step 2 of 4"); c.set_active("groq/m0")
        c.set_pipeline("ready", ["verified", "running", "pending"], [True]); step(c, 1.0)
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
