"""Renders the real "Reactor" widget offscreen and checks what a person would actually see (needs PySide6)."""
import math, os, unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QImage, QMouseEvent
    from PySide6.QtWidgets import QApplication
    from praxis.desktop.qt import core as core_mod, reactor as RX, theme
    from praxis.desktop.qt.core import CoreView
    from tests.qtutil import dispose
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
    """Mean RGB of the bright pixels in a box: the colour of what glows, not the dark background."""
    sr = sg = sb = n = 0
    for x, y, r, g, b in pixels(img, *box):
        if 0.3 * r + 0.59 * g + 0.11 * b >= min_luma:
            sr += r; sg += g; sb += b; n += 1
    return (sr / n, sg / n, sb / n, n) if n else (0, 0, 0, 0)


def count(img, box, pred, stride=1):
    return sum(1 for x, y, r, g, b in pixels(img, *box, stride=stride) if pred(r, g, b))


GREEN = lambda r, g, b: g > 150 and g >= b - 12 and g > r + 60         # the verified green (61, 227, 161) even under bloom, not blue
RED = lambda r, g, b: r > 170 and r > g + 80 and r > b + 40            # failure red
WARM = lambda r, g, b: r > 120 and r > b * 1.25 and g > b
luma = lambda t: 0.3 * t[0] + 0.59 * t[1] + 0.11 * t[2]


@unittest.skipUnless(HAVE_QT, "PySide6 not available")
class Reactor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        ui, mono = theme.fonts()
        cls.app.setStyleSheet(theme.qss(ui, mono))

    def make(self, w=1100, h=620, nodes=NODES, n=60):
        c = CoreView(); c.timer.stop()
        c.reactor.resize(n)                    # fewer sparks keep the tests quick; the logic is identical
        c.resize(w, h); c.set_nodes(nodes); c.show()
        self.addCleanup(lambda: dispose(c))
        step(c, 4.2)                           # past the power-up and the boot sequence
        return c

    def core_box(self, c):
        g = c._geo()
        return (g["cx"] - 0.3 * g["R"], g["cy"] - 0.3 * g["R"], g["cx"] + 0.3 * g["R"], g["cy"] + 0.3 * g["R"])

    def dial_box(self, c):                     # the whole dial, but not the provider nodes on the flanks (Ollama's is green too)
        g = c._geo()
        e = RX.EXTENT * g["R"]
        return (g["cx"] - e, g["cy"] - e, g["cx"] + e, g["cy"] + e)

    def ring_px(self, img, c, which, deg):
        """The brightest pixel on HUD ring `which` (0 plan, 1 act, 2 verify) at `deg` degrees clockwise from the top."""
        g = c._geo()
        r = (RX.RING_R["plan"], RX.RING_R["act"], RX.RING_R["verify"])[which] * g["R"]
        x = g["cx"] + math.sin(math.radians(deg)) * r
        y = g["cy"] - math.cos(math.radians(deg)) * r
        best, best_s = (0, 0, 0), -1
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                px = img.pixelColor(int(round(x)) + dx, int(round(y)) + dy)
                t = (px.red(), px.green(), px.blue())
                sat = (max(t) - min(t)) if luma(t) > 40 else -1          # the arc's own colour, not the white-hot bloom on top of it
                if sat > best_s or (best_s < 0 and luma(t) > luma(best)):
                    best, best_s = t, sat
        return best

    # ---- the colour is the state ------------------------------------------------------------------------------------
    def colour_of(self, mode):
        c = self.make()
        c.set_state(mode, 0.0, mode.upper(), ""); step(c, 3.0)
        img = render(c)
        g = c._geo()                                           # the lit coils: the annulus between COIL_IN and COIL_OUT
        sr = sg = sb = n = 0
        for x, y, r, g_, b in pixels(img, g["cx"] - g["R"], g["cy"] - g["R"], g["cx"] + g["R"], g["cy"] + g["R"]):
            rad = math.hypot(x - g["cx"], y - g["cy"]) / g["R"]
            if RX.COIL_IN + 0.03 <= rad <= RX.COIL_OUT - 0.03 and 0.3 * r + 0.59 * g_ + 0.11 * b >= 60:
                sr += r; sg += g_; sb += b; n += 1
        return (sr / n, sg / n, sb / n, n) if n else (0, 0, 0, 0)

    def test_each_state_is_a_different_colour_you_can_read_at_a_glance(self):
        idle, ok, bad, wait, work = (self.colour_of(m) for m in ("idle", "ok", "bad", "waiting", "working"))
        for name, col in (("idle", idle), ("ok", ok), ("bad", bad), ("waiting", wait), ("working", work)):
            self.assertGreater(col[3], 150, f"{name}: the reactor core must actually be drawn")
        hue = lambda c: (c[0] - c[2])                                   # warm (positive) .. cool (negative)
        self.assertLess(hue(work), hue(idle) + 10, f"working is the coolest/bluest: {work} vs {idle}")
        self.assertLess(hue(work), 5, f"working reads as reactor blue: {work}")
        self.assertGreater(hue(ok), hue(idle) + 30, f"verified is gold, warmer than idle: {ok} vs {idle}")
        self.assertGreater(hue(wait), hue(idle) + 30, f"needs-you is orange, warmer than idle: {wait}")
        self.assertTrue(bad[0] > bad[1] * 1.2 and bad[0] > bad[2] * 1.2, f"failed is red: {bad}")
        self.assertGreater(wait[1] / wait[0], bad[1] / bad[0] + 0.08, f"orange has more green in it than red does: {wait} vs {bad}")

    def test_the_reactor_is_the_brightest_thing_in_the_frame_with_the_core_its_brightest_point(self):
        c = self.make()
        img = render(c)
        g = c._geo()
        centre = mean_colour(img, (g["cx"] - 5, g["cy"] - 5, g["cx"] + 5, g["cy"] + 5), min_luma=0)
        dial = mean_colour(img, self.dial_box(c), min_luma=0)
        corner = mean_colour(img, (20, 100, 60, 140), min_luma=0)
        self.assertGreater(luma(dial), luma(corner) * 2)
        self.assertGreater(luma(centre), luma(dial) * 1.5)

    def test_it_is_gold_and_gunmetal_not_a_hologram(self):
        c = self.make()
        img = render(c)
        g = c._geo()
        # the gold bevel on the housing: warm pixels (red > green > blue) on the circle at radius 1.0 R
        gold = 0
        for k in range(0, 360, 5):
            x = g["cx"] + math.sin(math.radians(k)) * g["R"]; y = g["cy"] - math.cos(math.radians(k)) * g["R"]
            for dx in (-2, -1, 0, 1, 2):
                for dy in (-2, -1, 0, 1, 2):
                    px = img.pixelColor(int(x) + dx, int(y) + dy)
                    if px.red() > 150 and px.red() > px.green() > px.blue() + 30:
                        gold += 1; break
                else:
                    continue
                break
        self.assertGreater(gold, 50, "the housing has a gold bevel")
        for name in ("_projector", "_glitch", "_ghost"):
            self.assertFalse(hasattr(c, name), f"{name}: the scan-line hologram effects are gone")

    # ---- the three rings show real data ------------------------------------------------------------------------------
    def test_the_act_ring_arcs_are_the_real_steps_in_their_real_states(self):
        c = self.make()
        c.set_pipeline("ready", ["verified", "running", "pending", "waiting"], [])
        self.assertEqual(c.ring_states(1), ["verified", "running", "pending", "waiting"])
        c.set_pipeline("ready", ["verified", "failed", "verified", "failed"], []); step(c, 0.2)
        img = render(c)
        segs = RX.ring_segments(4)
        mids = [s + sp / 2 for s, sp in segs]
        got = [self.ring_px(img, c, 1, m) for m in mids]
        self.assertTrue(GREEN(*got[0]) and GREEN(*got[2]), got)                     # arcs 1 and 3 are green: verified
        self.assertTrue(RED(*got[1]) and RED(*got[3]), got)                         # arcs 2 and 4 are red: failed
        gap = self.ring_px(img, c, 1, segs[0][0] + segs[0][1] + RX.GAP_DEG / 2)
        self.assertLess(luma(gap), luma(got[0]) * 0.6)                              # and there is a gap between them

    def test_pending_and_waiting_steps_look_different_from_done_ones(self):
        c = self.make()
        c.set_pipeline("ready", ["pending", "waiting"], []); step(c, 0.2)
        img = render(c)
        pend, wait = (self.ring_px(img, c, 1, s + sp / 2) for s, sp in RX.ring_segments(2))
        self.assertFalse(GREEN(*pend) or RED(*pend)); self.assertLess(luma(pend), 190)          # quiet steel
        self.assertTrue(wait[0] > wait[2] * 1.3 and wait[1] > wait[2], wait)                     # orange: it needs you

    def test_the_verify_ring_has_one_arc_per_check_and_seals_shut_when_the_goal_verifies(self):
        c = self.make()
        c.set_pipeline("ready", ["verified"] * 3, [True, True, False])
        self.assertEqual(c.ring_states(2), ["verified", "verified", "failed"])
        step(c, 0.2); img = render(c)
        mids = [s + sp / 2 for s, sp in RX.ring_segments(3)]
        got = [self.ring_px(img, c, 2, m) for m in mids]
        self.assertTrue(GREEN(*got[0]) and GREEN(*got[1]) and RED(*got[2]), got)
        c.set_pipeline("ready", ["verified"] * 3, [True, True, True], sealed=True)
        self.assertEqual(c.ring_states(2), ["verified"])                                    # one closed ring: no gaps left
        step(c, 0.2); sealed = render(c)
        for deg in range(0, 360, 20):
            self.assertTrue(GREEN(*self.ring_px(sealed, c, 2, deg)) or luma(self.ring_px(sealed, c, 2, deg)) > 200, deg)

    def test_the_plan_ring_follows_the_planning_stage(self):
        c = self.make()
        for plan, states in (("none", []), ("planning", ["running"]), ("ready", ["ran"]), ("failed", ["failed"])):
            c.set_pipeline(plan); self.assertEqual(c.ring_states(0), states, plan)
        c.set_pipeline("failed"); step(c, 0.2)
        self.assertTrue(RED(*self.ring_px(render(c), c, 0, 180)))                           # a rejected plan is a red ring

    def test_a_running_step_has_a_comet_that_moves(self):
        c = self.make()
        c.set_pipeline("ready", ["running"], []); step(c, 0.1)
        a = render(c); step(c, 0.4); b = render(c)
        g = c._geo(); r = RX.RING_R["act"] * g["R"]
        box = (g["cx"] - r - 8, g["cy"] - r - 8, g["cx"] + r + 8, g["cy"] + r + 8)
        self.assertNotEqual(a.copy(), b.copy())
        self.assertGreater(count(a, box, lambda r_, g_, b_: r_ + g_ + b_ > 660, stride=2), 0)   # a white-hot head exists

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
    def test_the_coils_spin_up_while_working_hold_still_when_it_needs_you_and_stop_on_stop(self):
        c = self.make()
        def rate(mode):
            c.set_state(mode, 0.2, mode.upper(), ""); step(c, 4.0)
            before = c.reactor.coil_rot; step(c, 1.0); return (c.reactor.coil_rot - before) % math.tau
        idle, work, wait = rate("idle"), rate("working"), rate("waiting")
        self.assertGreater(work, idle * 3); self.assertLess(wait, idle)
        c.set_state("stopping", 0.2, "STOPPING", ""); step(c, 2.0)
        self.assertLess(c.reactor.dyn.v["spin"], 0.05)

    def test_a_call_in_flight_draws_a_stream_to_exactly_that_provider(self):
        c = self.make()
        c.set_state("working", 0.0, "RUNNING", ""); step(c, 0.5)
        base = render(c)
        c.set_active("groq/m0"); step(c, 0.3)
        lit = render(c)
        g = c._geo()
        def diff(i):
            pts = c._link_pts(g, i); d = 0
            for u in (0.25, 0.5, 0.75, 0.9):
                x, y = RX.polyline_point(pts, u)
                for yy in range(int(y) - 12, int(y) + 12, 2):
                    for xx in range(int(x) - 12, int(x) + 12, 2):
                        a, b = base.pixelColor(xx, yy), lit.pixelColor(xx, yy)
                        d += abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())
            return d
        self.assertGreater(diff(1), diff(3) * 2)                  # groq, not claude
        c.set_active(""); self.assertEqual(c.active, "")

    def test_every_real_event_flares_the_core_and_ripples_but_a_burst_is_rate_limited_and_ripples_expire(self):
        c = self.make()
        self.assertEqual(c.ripples, []); self.assertEqual(c.reactor.flare, 0.0)
        c.pulse("ok"); c.pulse("ok"); c.pulse("warn")
        self.assertEqual(len(c.ripples), 1)                       # three events in the same instant: one ripple, readable
        self.assertAlmostEqual(c.reactor.flare, 0.7 * 0.8)        # ...and one flare
        step(c, 0.2); c.pulse("bad")
        self.assertEqual(len(c.ripples), 2)
        for _ in range(20):
            step(c, 0.2); c.pulse("info")
        self.assertLessEqual(len(c.ripples), 6); self.assertLessEqual(c.reactor.flare, 1.5)
        step(c, 3.0)
        self.assertEqual(c.ripples, []); self.assertEqual(c.reactor.flare, 0.0)

    def test_the_core_visibly_flares_on_an_event(self):
        c = self.make()
        g = c._geo()
        box = (g["cx"] - 0.9 * g["R"], g["cy"] - 6, g["cx"] + 0.9 * g["R"], g["cy"] + 6)       # the streak's row
        quiet = count(render(c), box, lambda r, g_, b: r + g_ + b > 600)
        c.pulse("ok"); c.advance(0.02)
        flared = count(render(c), box, lambda r, g_, b: r + g_ + b > 600)
        self.assertGreater(flared, quiet)

    def test_verified_triggers_the_gold_shockwave_and_a_flare_once(self):
        c = self.make()
        c.set_state("working", 0.5, "RUNNING", ""); step(c, 0.5)
        self.assertIsNone(c.reactor.shock)
        c.set_state("ok", 1.0, "VERIFIED", "")
        self.assertIsNotNone(c.reactor.shock); self.assertEqual(len(c.ripples), 1); self.assertGreater(c.reactor.flare, 0.9)
        c.advance(0.4); img = render(c)
        g = c._geo(); u = RX.ease_out(c.reactor.shock); rr = g["R"] * (0.9 + 1.25 * u)
        warm = 0
        for k in range(0, 360, 10):
            x = g["cx"] + math.sin(math.radians(k)) * rr; y = g["cy"] - math.cos(math.radians(k)) * rr
            px = img.pixelColor(int(x), int(y))
            warm += px.red() > 140 and px.red() > px.blue()
        self.assertGreater(warm, 12)                                  # a ring of gold light is travelling outward
        step(c, 0.2); c.set_state("ok", 1.0, "VERIFIED", "again")    # same state again: no second shockwave
        self.assertEqual(len(c.ripples), 1)

    def test_starting_powers_up_coil_by_coil_and_restarts_when_asked(self):
        c = CoreView(); c.timer.stop(); c.reactor.resize(40); c.resize(900, 500); c.show(); self.addCleanup(lambda: dispose(c))
        self.assertEqual(c.reactor.power, 0.0)
        step(c, 0.5); self.assertTrue(0.0 < c.reactor.power < 1.0)
        step(c, 2.5); self.assertEqual(c.reactor.power, 1.0)
        c.set_state("idle", 0, "READY", ""); c.set_state("starting", 0, "STARTING", "")
        self.assertEqual(c.reactor.power, 0.0)                         # re-lights when it restarts (e.g. a new workspace)

    def test_stopping_spins_it_down_and_a_bad_end_flashes_red(self):
        c = self.make()
        c.set_state("working", 0.5, "RUNNING", ""); step(c, 1.0)
        c.set_state("stopping", 0.5, "STOPPING", ""); step(c, 0.5)
        self.assertEqual(c.ripples[-1][1], "warn")
        c.set_state("bad", 0.5, "FAILED", ""); self.assertEqual(c.ripples[-1][1], "bad")

    def test_bloom_makes_the_glow_spill_beyond_the_parts(self):
        c = self.make(n=60)
        c.set_state("working", 0.3, "RUNNING", ""); step(c, 1.0)
        c.quality.limit = 1e9                                       # keep the governor out of the comparison
        on = render(c)
        c.quality.level = 2                                         # bloom is dropped at the lower detail levels
        off = render(c)
        box = self.dial_box(c)
        total = lambda img: sum(0.3 * r + 0.59 * g + 0.11 * b for x, y, r, g, b in pixels(img, *box, stride=2))
        self.assertGreater(total(on), total(off) * 1.03)

    # ---- the voice ring ------------------------------------------------------------------------------------------------------
    def voice_light(self, c):
        g = c._geo()
        r0, r1 = (RX.VOICE_IN - 0.01) * g["R"], (RX.VOICE_OUT + 0.02) * g["R"]
        img = render(c); tot = 0
        for k in range(0, 360, 3):
            for rr in (r0 + (r1 - r0) * f for f in (0.2, 0.5, 0.8)):
                x = g["cx"] + math.sin(math.radians(k)) * rr; y = g["cy"] - math.cos(math.radians(k)) * rr
                px = img.pixelColor(int(x), int(y)); tot += px.red() + px.green() + px.blue()
        return tot

    def test_the_voice_ring_is_an_equaliser_of_the_real_audio(self):
        c = self.make()
        c.set_voice("listening", 0.0, 0.0, False); step(c, 1.0); quiet = self.voice_light(c)
        c.set_voice("hearing", 0.12, 0.0, False); step(c, 1.5); loud = self.voice_light(c)
        self.assertGreater(loud, quiet * 1.4)                                   # louder speech: longer, brighter bars
        c.set_voice("speaking", 0.0, 0.9, False); step(c, 1.5)
        self.assertGreater(self.voice_light(c), quiet * 1.4)                    # its own voice drives it too
        c.set_voice("off", 0.0, 0.0, False); step(c, 2.0)
        self.assertLess(self.voice_light(c), quiet)                             # no voice, no bars
        self.assertAlmostEqual(c.voice_amplitude(), 0.0)

    def test_the_targeting_brackets_close_in_while_it_hears_you(self):
        c = self.make()
        g = c._geo()
        def bracket_radius(img):                                    # where, in units of R, the gold bracket lies on the diagonals
            best = []
            for deg in (45, 135, 225, 315):
                top, at = -1, 0
                for k in range(0, 80):
                    rr = RX.SCALE_R[1] + 0.06 + k * 0.005
                    x = g["cx"] + math.sin(math.radians(deg)) * rr * g["R"]; y = g["cy"] - math.cos(math.radians(deg)) * rr * g["R"]
                    px = img.pixelColor(int(round(x)), int(round(y)))
                    score = px.red() - px.blue()
                    if score > top:
                        top, at = score, rr
                best.append(at)
            return sum(best) / len(best)
        c.set_voice("listening", 0.0, 0.0, False); step(c, 0.5)
        idle = bracket_radius(render(c))
        c.set_voice("hearing", 0.1, 0.0, False); step(c, 0.5)
        near = bracket_radius(render(c))
        self.assertLess(near, idle - 0.05)                          # while it listens they are closer in than at rest

    def test_hostile_voice_numbers_cannot_reach_the_painter(self):
        c = self.make()
        for lvl in (float("nan"), float("inf"), -5, 1e12, None, "x"):
            c.set_voice("hearing", lvl, lvl, True); step(c, 0.1); render(c)
        self.assertTrue(0.0 <= c.voice["level"] <= 10.0)

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
    def test_nodes_flank_the_dial_by_cost_class_outside_the_scale(self):
        for w, h in ((1000, 520), (824, 460), (700, 400), (1500, 700)):
            c = self.make(w, h, n=10)
            g = c._geo()
            for i, nd in enumerate(c.nodes):
                pt, side = g["pos"][i]
                self.assertEqual(side, -1 if nd["cost_class"] <= 1 else 1, (w, nd["family"]))        # free/local left, subscriptions right
                self.assertGreater(abs(pt.x() - g["cx"]), g["R"] * RX.EXTENT * 0.98, (w, h, nd["family"]))
                self.assertTrue(0 <= pt.x() - 12 and pt.x() + 12 <= w and g["top"] - 20 <= pt.y() <= h - 40, (w, h, nd["family"], pt))

    def test_the_whole_dial_always_fits_the_room_it_has(self):
        for w, h in ((1100, 620), (824, 520), (760, 520), (1500, 700)):
            c = self.make(w, h, n=10)
            g = c._geo()
            self.assertLessEqual(g["R"] * RX.EXTENT, g["avail"] / 2 + 1.0, (w, h))      # never under the title or the caption
            self.assertLessEqual(g["R"] * RX.EXTENT, w / 2 - 20 + 1.0, (w, h))          # never clipped at the sides

    def test_one_sided_node_sets_are_split_evenly_instead_of_a_lopsided_column(self):
        subs = [node(f"s{i}", 2) for i in range(6)]
        c = self.make(1000, 520, nodes=subs, n=10)
        sides = [c._geo()["pos"][i][1] for i in range(6)]
        self.assertEqual((sides.count(-1), sides.count(1)), (3, 3))

    def test_many_nodes_and_degenerate_sizes_never_crash(self):
        many = [node(f"f{i}", i % 3) for i in range(12)]
        for w, h in ((560, 300), (700, 340), (1400, 520)):
            c = self.make(w, h, nodes=many, n=10)
            img = render(c); self.assertEqual((img.width(), img.height()), (w, h))
        c = self.make(n=10)
        for w, h in ((1, 1), (50, 50), (79, 500), (600, 79), (3000, 120)):
            c.resize(w, h); render(c)
        c.resize(800, 500); c.set_nodes([]); c.set_active("nobody/x"); c.set_footer(""); c.set_caption("")
        c.set_pipeline("ready", ["verified"] * 40, [True] * 40, sealed=True); render(c)                # 40 arcs on a ring: still fine

    def test_every_brain_is_named_on_screen_and_brighter_when_it_matters_or_you_point_at_it(self):
        nodes = [node("droid", 2), node("devin", 2), node("ollama", 0, "local")]
        c = self.make(nodes=nodes)
        render(c)
        g = c._geo()
        def area(i):
            pt, side = g["pos"][i]
            return (pt.x() - 160, pt.y() - 20, pt.x() - 20, pt.y() + 4) if side < 0 else (pt.x() + 20, pt.y() - 20, pt.x() + 160, pt.y() + 4)
        for i in range(3):
            self.assertGreater(count(render(c), area(i), lambda r, g_, b: r + g_ + b > 200), 15, nodes[i]["family"])        # named, always
        i = 2; pt = g["pos"][i][0]
        quiet = count(render(c), area(i), lambda r, g_, b: r + g_ + b > 450)
        ev = QMouseEvent(QEvent.MouseMove, QPointF(pt.x(), pt.y()), QPointF(0, 0), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
        c.mouseMoveEvent(ev); self.assertEqual(c._hover, "ollama")
        shown = count(render(c), area(i), lambda r, g_, b: r + g_ + b > 450)
        self.assertGreater(shown, quiet + 10)                                                                                 # pointing at it lights it up
        self.assertEqual(core_mod.DISPLAY["droid"], "droid \u00b7 factory")                                                      # Factory's brain is named for what it is

    # ---- the MCU-style layer: boot sequence, event feed, readout, energy ----------------------------------------------------
    def test_the_hud_draws_itself_in_at_boot_and_is_complete_afterwards(self):
        c = CoreView(); c.timer.stop(); c.reactor.resize(10); c.resize(1100, 620); c.show(); self.addCleanup(lambda: dispose(c))
        c.set_pipeline("ready", ["verified"] * 3, [True]); c.set_state("working", 0.5, "RUNNING", "")
        step(c, 0.3); early = render(c)
        step(c, 4.0); late = render(c)
        g = c._geo()
        plan = lambda img: self.ring_px(img, c, 0, 180)
        self.assertLess(luma(plan(early)), 40)                                       # the outer ring has not been drawn yet
        self.assertGreater(luma(plan(late)), 90)                                      # and is there once the boot sequence is over
        self.assertEqual(c.reactor.boot, 1.0)
        c.set_state("idle", 0, "READY", ""); c.set_state("starting", 0, "STARTING", "")
        self.assertEqual(c.reactor.boot, 0.0)                                         # a restart plays it again

    def region(self, c, box, pred=lambda r, g, b: r + g + b > 300):
        return count(render(c), box, pred)

    def test_the_event_feed_shows_real_lines_collapses_repeats_and_keeps_six(self):
        c = self.make(1280, 760, n=10)
        box = (20, 760 - 150, 460, 760 - 40)
        empty = self.region(c, box)
        for i in range(9):
            c.add_log(f"event number {i}", "ok" if i % 2 else "info")
        self.assertEqual(len(c.log), 6); self.assertEqual(c.log[-1][1], "event number 8"); self.assertEqual(c.log[0][1], "event number 3")
        c.add_log("event number 8", "ok"); self.assertEqual(len(c.log), 6)                # an immediate repeat is not added twice
        c.add_log("", "info"); c.add_log(None, "info"); self.assertEqual(len(c.log), 6)
        self.assertGreater(self.region(c, box), empty + 150)                              # the lines are on screen, bottom-left
        small = self.make(900, 600, n=10); small.add_log("hidden when narrow", "ok")
        self.assertEqual(self.region(small, (20, 450, 460, 560)), self.region(self.make(900, 600, n=10), (20, 450, 460, 560)))     # no panels on narrow windows

    def test_the_goal_readout_shows_real_numbers_and_clears(self):
        c = self.make(1280, 760, n=10)
        box = (1280 - 260, 760 - 150, 1280 - 20, 760 - 40)
        none = self.region(c, box)
        c.set_stats({"elapsed": "00:12", "steps": "1/3", "checks": "1/1", "brain": "groq"})
        self.assertGreater(self.region(c, box), none + 100)
        c.set_stats({}); self.assertEqual(c.stats, {}); self.assertEqual(self.region(c, box), none)
        c.set_stats(None); self.assertEqual(c.stats, {})

    def test_an_energy_arc_is_really_drawn_between_the_core_and_the_coils(self):
        c = self.make(n=10)
        c.reactor.bolts = []
        base = render(c)
        g = c._geo()
        c.reactor.bolts = [{"pts": RX.bolt_points(__import__("random").Random(2), 0.0, RX.CORE_R * 1.05, RX.COIL_OUT * 0.97), "age": 0.0, "life": 1.0}]
        with_bolt = render(c)
        x0 = g["cx"] + RX.CORE_R * 1.1 * g["R"]; x1 = g["cx"] + RX.COIL_OUT * 0.95 * g["R"]
        box = (x0, g["cy"] - 14, x1, g["cy"] + 14)
        self.assertGreater(self.region(c, box, lambda r, g_, b: r + g_ + b > 500) , -1)
        diff = sum(abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())
                   for (x, y, *_), a, b in ((p, base.pixelColor(p[0], p[1]), with_bolt.pixelColor(p[0], p[1])) for p in pixels(base, *box)))
        self.assertGreater(diff, 3000)

    def test_events_light_the_armour_plates_in_a_travelling_ring_of_hexagons(self):
        c = self.make(1280, 760, n=10)
        c.ripples = []; c.reactor.shock = None; c.t = 4.0                     # between ambient pulses
        quiet = render(c)
        c.ripples = [(c.t - 0.7, "ok")]
        lit = render(c)
        g = c._geo()
        u = 0.7 / 1.6; radius = g["R"] * (0.9 + 2.6 * RX.ease_out(u))
        box = (g["cx"] + radius - 40, g["cy"] - 40, g["cx"] + radius + 40, g["cy"] + 40)
        green = lambda r, g_, b: g_ > r + 10 and g_ > 40
        self.assertGreater(self.region(c, box, green), 0)
        diff = lambda a, b: sum(abs(a.pixelColor(x, y).green() - b.pixelColor(x, y).green()) for x, y, *_ in pixels(a, *box, stride=2))
        self.assertGreater(diff(lit, quiet), 600)

    def test_the_decorative_circles_turn_and_the_radar_sweeps_round(self):
        c = self.make(n=10)
        a = render(c); step(c, 0.8); b = render(c)
        g = c._geo()
        ring = lambda img: sum(img.pixelColor(int(g["cx"] + math.cos(t) * RX.DECOR_R[0] * g["R"]), int(g["cy"] + math.sin(t) * RX.DECOR_R[0] * g["R"])).blue() for t in [k * 0.05 for k in range(126)])
        self.assertNotEqual(ring(a), ring(b))                                         # dashes moved and the sweep passed
        self.assertNotEqual(c.reactor.sweep_rot, 0.0)

    def test_the_radar_sweep_edge_is_where_the_engine_says_it_is_and_trails_behind(self):
        c = self.make(n=5)
        c.set_state("working", 0.5, "RUNNING", ""); step(c, 2.0)
        g = c._geo()
        def profile(img):                                   # brightness by angle (clockwise from the top) on the sweep band
            out = {}
            for deg in range(0, 360, 4):
                tot = 0
                for rr in (1.33, 1.345, 1.355):                       # inside the sweep band, clear of the dashed circle at 1.31 and the VERIFY ring
                    x = g["cx"] + math.sin(math.radians(deg)) * rr * g["R"]; y = g["cy"] - math.cos(math.radians(deg)) * rr * g["R"]
                    px = img.pixelColor(int(round(x)), int(round(y))); tot += px.red() + px.green() + px.blue()
                out[deg] = tot
            return out
        img = render(c); prof = profile(img)
        edge = math.degrees(c.reactor.sweep_rot) % 360
        near = lambda d: min(abs((d - edge + 180) % 360 - 180), 999)
        peak = max(prof, key=prof.get)
        self.assertLess(near(peak), 14, (peak, edge))                                            # the bright edge is at the engine's angle
        behind = sum(v for d, v in prof.items() if 12 < (edge - d) % 360 < 48) / 9.0               # the trail lies behind the edge (counter-clockwise)
        ahead = sum(v for d, v in prof.items() if 12 < (d - edge) % 360 < 48) / 9.0
        far = sum(v for d, v in prof.items() if 120 < (edge - d) % 360 < 240) / 30.0              # the quiet far side of the dial
        self.assertGreater(behind, ahead * 1.12); self.assertGreater(behind, far * 1.12)

    def test_the_wordmark_shimmer_and_motion_are_off_in_reduced_motion(self):
        with mock.patch.object(core_mod, "REDUCED", True):
            c = CoreView(); c.timer.stop(); c.reactor.resize(5); c.resize(1100, 620); c.show(); self.addCleanup(lambda: dispose(c))
            step(c, 4.0); c.t = 0.5
            a = render(c)
            c.t = 0.9
            b = render(c)
            g = c._geo()
            region = (g["cx"] - 80, 8, g["cx"] + 80, 30)
            self.assertEqual(self.region(c, region), self.region(c, region))                        # deterministic, no shimmer

    # ---- interaction & performance ------------------------------------------------------------------------------------------
    def test_clicking_the_reactor_pokes_it_and_clicking_elsewhere_does_not(self):
        c = self.make()
        g = c._geo()
        mk = lambda x, y: QMouseEvent(QEvent.MouseButtonPress, QPointF(x, y), QPointF(0, 0), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        c.mousePressEvent(mk(20, 20)); self.assertEqual(c.ripples, []); self.assertEqual(c.reactor.flare, 0.0)
        c.mousePressEvent(mk(g["cx"], g["cy"])); self.assertEqual(len(c.ripples), 1); self.assertGreater(c.reactor.flare, 0.8)

    def test_slow_frames_make_the_widget_drop_detail_by_itself(self):
        c = self.make(n=80)
        c.quality.limit, c.quality.patience = 0.0001, 5          # pretend every frame is far too slow
        n0 = c.reactor.n_embers
        for _ in range(12):
            render(c)
        self.assertLess(c.reactor.n_embers, n0); self.assertEqual(c.reactor.n_embers, c.quality.n)

    def test_a_frame_is_cheap_enough_to_animate(self):
        import time
        c = self.make(1000, 560, n=RX.LEVELS[0])
        c.set_state("working", 0.5, "RUNNING", "step 2 of 4"); c.set_active("groq/m0")
        c.set_pipeline("ready", ["verified", "running", "pending"], [True]); step(c, 1.0)
        t0 = time.perf_counter()
        for _ in range(15):
            c.advance(1 / 30); c.repaint()
        ms = 1000 * (time.perf_counter() - t0) / 15
        self.assertLess(ms, 150, f"a frame took {ms:.0f} ms: far too slow to animate")      # generous: this guards against pathologies

    def test_reduced_motion_slows_everything_down(self):
        with mock.patch.object(core_mod, "REDUCED", True):
            c = CoreView(); self.addCleanup(lambda: dispose(c)); c.timer.stop()
            self.assertEqual(c.reactor.n_embers, RX.LEVELS[2])
            c.set_state("working", 0, "RUNNING", ""); self.assertEqual(c.timer.interval(), 80)
            t0 = c.reactor.t; c.advance(0.2)
            self.assertAlmostEqual(c.reactor.t - t0, 0.04, places=3)

    def test_calm_states_run_at_a_lower_frame_rate_than_working(self):
        c = self.make()
        c.set_state("idle", 0, "READY", ""); calm = c.timer.interval()
        c.set_state("working", 0, "RUNNING", ""); busy = c.timer.interval()
        self.assertGreater(calm, busy)

    def test_a_bug_while_painting_cannot_leave_a_painter_open_and_crash_the_app(self):
        c = self.make(n=10)
        def boom(*a, **k): raise RuntimeError("bug in a draw routine")
        orig = c._hud
        c._hud = boom
        try:
            c.grab()                                  # the error surfaces as an exception; it must not be a segfault
        except Exception:
            pass
        c._hud = orig
        render(c)                                     # and the widget keeps working afterwards

    def test_fin_rejects_every_unsafe_number(self):
        fin = core_mod.fin
        for x in (float("nan"), float("inf"), float("-inf"), None, "abc", [], object()):
            self.assertEqual(fin(x, 0.0, 1.0, 0.25), 0.25)
        self.assertEqual(fin(7, 0.0, 1.0), 1.0); self.assertEqual(fin(-7, 0.0, 1.0), 0.0); self.assertEqual(fin("0.5", 0.0, 1.0), 0.5)

    def test_poisoned_time_steps_are_ignored_so_the_scene_is_never_corrupted(self):
        c = self.make(n=10)
        t0 = c.t
        for dt in (float("nan"), -5.0, float("inf"), 0.0):
            c.advance(dt)
        self.assertEqual(c.t, t0)
        c.advance(100.0); self.assertLessEqual(c.t - t0, 0.26)                              # a long stall advances only a little
        render(c)

    def test_hostile_node_numbers_are_cleaned_before_they_reach_the_painter(self):
        c = self.make(n=10)
        c.set_nodes([node("x", 1, press=float("nan"), cool=float("inf")), node("y", 2, press=9, cool=-3)])
        self.assertEqual([n["pressure"] for n in c.nodes], [0.0, 1.0]); self.assertEqual([n["cooling_s"] for n in c.nodes], [0, 0])
        render(c)


if __name__ == "__main__":
    unittest.main()
