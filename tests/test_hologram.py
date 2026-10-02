import math
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from praxis.desktop.qt import hologram as H


class Hologram(unittest.TestCase):
    def test_flicker_stays_in_its_band_and_is_not_constant(self):
        v = [H.flicker(i * 0.01) for i in range(20000)]
        self.assertTrue(all(0.88 <= x <= 1.0 for x in v))
        self.assertGreater(max(v) - min(v), 0.04)               # it does shimmer
        self.assertLess(sum(1 for x in v if x < 0.93) / len(v), 0.2)          # but is steady most of the time

    def test_glitches_are_rare_brief_and_bounded(self):
        ts = [i * 0.01 for i in range(60000)]                    # 10 minutes
        on = [t for t in ts if H.glitch(t)[0]]
        self.assertGreater(len(on) * 0.01, 3.0); self.assertLess(len(on) * 0.01 / 600.0, 0.03)     # a few percent of the time at most
        for t in on:
            _, y, dx = H.glitch(t)
            self.assertTrue(0.0 <= y <= 1.0); self.assertTrue(3.0 <= abs(dx) <= 8.0)
        longest, run = 0, 0
        for t in ts:
            run = run + 1 if H.glitch(t)[0] else 0; longest = max(longest, run)
        self.assertLessEqual(longest * 0.01, H.GLITCH_LEN + 0.02)

    def test_the_sweep_line_travels_the_whole_projection_and_fades_at_the_ends(self):
        ys = [H.sweep(i * 0.05)[0] for i in range(int(H.SWEEP_PERIOD / 0.05))]
        self.assertGreater(max(ys), 0.95); self.assertLess(min(ys), 0.05)
        self.assertLess(H.sweep(0.0)[1], 0.01); self.assertGreater(H.sweep(H.SWEEP_PERIOD / 2)[1], 0.99)

    def test_floor_rings_fade_at_the_centre_and_the_rim(self):
        self.assertEqual(H.ring_alpha(0.0), 0.0)
        self.assertLess(H.ring_alpha(1.0), 1e-6); self.assertGreater(H.ring_alpha(0.5), 0.9)
        self.assertEqual(H.ring_alpha(-3), 0.0); self.assertLess(H.ring_alpha(9), 1e-6)

    def test_every_function_is_total_for_any_time(self):
        for t in (0, 1, -1, 1e-300, 1e12, 1e300, float("nan"), float("inf"), float("-inf"), None, "x", 3):
            f = H.flicker(t); self.assertTrue(0.88 <= f <= 1.0)
            a, y, dx = H.glitch(t); self.assertTrue(math.isfinite(y) and math.isfinite(dx))
            for v in H.sweep(t) + H.ghost_offset(t):
                self.assertTrue(math.isfinite(v))
            rings, spokes = H.grid_lines(6, 18, t)
            self.assertTrue(all(math.isfinite(x) for x in rings + spokes))

    def test_it_is_deterministic(self):
        self.assertEqual([H.glitch(t * 0.37) for t in range(500)], [H.glitch(t * 0.37) for t in range(500)])


try:
    from PySide6.QtWidgets import QApplication
    from praxis.desktop.qt.core import CoreView, fin
    HAVE_QT = True
except Exception:
    HAVE_QT = False


@unittest.skipUnless(HAVE_QT, "PySide6 not available")
class OnScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def view(self, **kw):
        c = CoreView(); c.resize(1000, 620); c.set_state(kw.get("mode", "idle"), 0.3, "READY")
        c.quality.level = 0
        for _ in range(40): c.advance(0.05)
        return c

    def test_a_projector_stands_under_the_galaxy_and_a_beam_rises_from_it(self):
        img = self.view().grab().toImage()
        w, h = img.width(), img.height()
        def lum(x, y): c = img.pixelColor(x, y); return c.red() + c.green() + c.blue()
        ring_row = max(range(int(h * 0.7), h - 8), key=lambda y: sum(lum(x, y) for x in range(int(w * 0.3), int(w * 0.7), 3)))
        self.assertGreater(ring_row, h * 0.7)                                              # the emitter sits low in the frame
        beam = sum(lum(int(w * 0.5) + dx, int(h * 0.22)) for dx in range(-150, 151, 15)) / 21
        outside = sum(lum(int(w * 0.04) + dx, int(h * 0.22)) for dx in range(0, 40, 4)) / 10
        self.assertGreater(beam, outside * 1.3)                                            # lit inside the beam, darker outside it

    def test_the_emitter_is_really_drawn_under_the_galaxy(self):
        c = self.view()
        full = c.grab().toImage()
        c._projector = lambda p, g, tint: None                                           # the same frame without the projector
        bare = c.grab().toImage()
        w, h = full.width(), full.height()
        def region(img): return sum(sum(img.pixelColor(x, y).blue() for x in range(int(w * .25), int(w * .75), 3)) for y in range(int(h * .72), int(h * .95), 2))
        self.assertGreater(region(full), region(bare) * 1.02)                              # light was added where the emitter stands

    def test_hostile_node_numbers_are_cleaned_before_they_reach_the_painter(self):
        c = self.view()
        c.set_nodes([{"family": "x", "cost_class": 1, "pressure": float("nan"), "cooling_s": float("inf"), "privacy": "local", "models": [],
                      "blocked": False, "delegate_only": False, "usage": {}}, {"family": "y", "cost_class": 2, "pressure": 9, "cooling_s": -3,
                      "privacy": "open", "models": [], "blocked": False, "delegate_only": False, "usage": {}}])
        self.assertEqual([n["pressure"] for n in c.nodes], [0.0, 1.0]); self.assertEqual([n["cooling_s"] for n in c.nodes], [0, 0])
        c.grab()

    def test_the_hologram_never_shows_a_wrong_state_it_only_decorates(self):
        a = self.view(mode="ok"); b = self.view(mode="bad")
        self.assertNotEqual(a.grab().toImage(), b.grab().toImage())                        # state colour still dominates

    def test_a_bug_while_painting_cannot_leave_a_painter_open_and_crash_the_app(self):
        c = self.view()
        def boom(*a, **k): raise RuntimeError("bug in a draw routine")
        c._hud = boom
        try:
            c.grab()                                  # the error surfaces as an exception; it must not be a segfault
        except Exception:
            pass
        c._hud = CoreView._hud.__get__(c)
        c.grab()                                      # and the widget keeps working afterwards

    def test_fin_rejects_every_unsafe_number(self):
        for x in (float("nan"), float("inf"), float("-inf"), None, "abc", [], object()):
            self.assertEqual(fin(x, 0.0, 1.0, 0.25), 0.25)
        self.assertEqual(fin(7, 0.0, 1.0), 1.0); self.assertEqual(fin(-7, 0.0, 1.0), 0.0); self.assertEqual(fin("0.5", 0.0, 1.0), 0.5)

    def test_poisoned_time_steps_are_ignored_so_the_scene_is_never_corrupted(self):
        c = self.view()
        t0 = c.t
        for dt in (float("nan"), -5.0, float("inf"), 0.0, None):
            c.advance(dt) if dt is not None else None
        self.assertEqual(c.t, t0)
        c.advance(100.0); self.assertLessEqual(c.t - t0, 0.26)                             # a long stall advances only a little
        c.grab()


if __name__ == "__main__":
    unittest.main()
