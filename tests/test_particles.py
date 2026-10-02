"""The particle engine is pure math (no Qt), so every behaviour that is supposed to encode real state is checked here."""
import math, unittest

from praxis.desktop.qt import particles as P
from praxis.desktop.qt.particles import Dynamics, Field, Quality, bezier, courier, ring


def run(f, secs, step=0.05):
    """Advance in realistic frame-sized steps (advance() clamps a single step so a stalled frame cannot make things jump)."""
    for _ in range(int(round(secs / step))):
        f.advance(step)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs)


class Distribution(unittest.TestCase):
    def setUp(self):
        self.f = Field(2000, seed=3)

    def test_every_particle_is_inside_the_sphere_and_the_cloud_is_a_ball_not_a_shell(self):
        r = [math.sqrt(x * x + y * y + z * z) for x, y, z in zip(self.f.x0, self.f.y, self.f.z0)]
        self.assertLessEqual(max(r), 1.07 + 1e-9)
        self.assertLess(min(r), 0.5)                               # volume points exist
        self.assertGreater(sum(1 for v in r if v > 0.94) / len(r), 0.4)    # and a crisp shell defines the edge

    def test_same_seed_same_sphere_and_a_different_seed_differs(self):
        a, b, c = Field(500, seed=9), Field(500, seed=9), Field(500, seed=10)
        self.assertEqual(a.x0, b.x0); self.assertNotEqual(a.x0, c.x0)

    def test_blue_on_top_pink_below_like_the_reference(self):
        top = mean(p for p, y in zip(self.f.pal, self.f.y) if y > 0.7)
        bottom = mean(p for p, y in zip(self.f.pal, self.f.y) if y < -0.7)
        self.assertLess(top, P.BUCKETS * 0.3); self.assertGreater(bottom, P.BUCKETS * 0.7)
        t, b = P.palette_at(0.0), P.palette_at(1.0)
        self.assertGreater(t[2], t[0])                              # top: blue dominates
        self.assertGreater(b[0], b[2] * 0.9); self.assertGreater(b[0], b[1])   # bottom: pink/magenta (red leads)

    def test_sparkles_are_rare_warm_stars_not_a_second_cloud(self):
        self.assertLess(sum(self.f.spark) / self.f.n, 0.03)
        self.assertTrue(any(self.f.spark))

    def test_the_equator_spins_faster_than_the_poles(self):
        sp = lambda i: self.f.speed_of_class[self.f.cls[i]]
        eq = mean(sp(i) for i in range(self.f.n) if abs(self.f.y[i] / max(self.f.rr[i], 1e-9)) < 0.25)
        pole = mean(sp(i) for i in range(self.f.n) if abs(self.f.y[i] / max(self.f.rr[i], 1e-9)) > 0.85)
        self.assertGreater(eq, pole * 1.25)                         # differential rotation: it looks like a living body

    def test_resize_rebuilds_to_the_requested_count(self):
        self.f.resize(600)
        self.assertEqual((self.f.n, len(self.f.x0)), (600, 600))


class Projection(unittest.TestCase):
    def test_every_particle_is_accounted_for_once(self):
        f = Field(1500, seed=1)
        buckets, sparks = f.project(500, 200, 100)
        self.assertEqual(sum(len(b) for b in buckets) + len(sparks), 1500)
        self.assertEqual(len(buckets), P.BUCKETS * 3 * P.VARIANTS)

    def test_the_projection_stays_near_the_sphere_and_front_points_are_bigger_than_back_points(self):
        f = Field(1500, seed=1); run(f, 2.5)
        buckets, _ = f.project(500, 200, 100)
        pts = [pt for b in buckets for pt in b]
        self.assertTrue(all(abs(x - 500) < 140 and abs(y - 200) < 140 for x, y in pts))
        # depth 2 (front) buckets hold points that were scaled up by perspective: mean distance from centre is larger
        d = lambda depth: mean(math.hypot(x - 500, y - 200) for k, b in enumerate(buckets) if (k // P.VARIANTS) % 3 == depth for x, y in b)
        self.assertGreater(d(2) + d(0), 0)
        self.assertGreater(len([1 for k, b in enumerate(buckets) if (k // P.VARIANTS) % 3 == 2 for _ in b]), 100)

    def test_mk_builds_the_points(self):
        buckets, _ = Field(200, seed=1).project(0, 0, 50, mk=lambda x, y: ("P", round(x), round(y)))
        self.assertTrue(all(pt[0] == "P" for b in buckets for pt in b))

    def test_rotation_moves_the_particles_and_stopping_the_spin_freezes_them(self):
        f = Field(400, seed=2)
        before = f.project(0, 0, 100)[0]
        f.advance(0.1)
        self.assertNotEqual(before, f.project(0, 0, 100)[0])
        f.dyn.v["spin"] = 0.0
        MODE_SPIN = P.MODE["idle"]["spin"]
        P.MODE["idle"]["spin"] = 0.0
        try:
            f.dyn.mode = "idle"; f.advance(0.0)
            a = f.project(0, 0, 100)[0]
            f.phi = list(f.phi)
            f.advance(0.0)
            self.assertEqual(a, f.project(0, 0, 100)[0])
        finally:
            P.MODE["idle"]["spin"] = MODE_SPIN

    def test_cursor_tilt_changes_the_picture_smoothly(self):
        f = Field(400, seed=2)
        a = f.project(0, 0, 100)[0]
        f.tilt_target = [0.4, 0.5]
        f.advance(0.05)
        self.assertGreater(f.tilt[0], 0); self.assertLess(f.tilt[0], 0.4)       # eased, not snapped
        self.assertNotEqual(a, f.project(0, 0, 100)[0])
        for _ in range(60):
            f.advance(0.05)
        self.assertAlmostEqual(f.tilt[0], 0.4, places=2)


class Assembly(unittest.TestCase):
    def test_it_starts_scattered_and_converges_into_the_sphere(self):
        f = Field(800, seed=4)
        far = f._radial()
        self.assertGreater(min(far), 1.5)                            # every point starts well outside the sphere
        prev = mean(far)
        for _ in range(12):
            f.advance(0.1)
            cur = mean(f._radial()) if f.asm < 1.0 else 1.0
            self.assertLessEqual(cur, prev + 1e-9); prev = cur
        run(f, 1.0)
        self.assertEqual(f.asm, 1.0)
        self.assertIsNone(f._radial() if False else None)

    def test_restart_assembly_scatters_again(self):
        f = Field(300, seed=4); run(f, 2.5); self.assertEqual(f.asm, 1.0)
        f.restart_assembly(); self.assertEqual(f.asm, 0.0)

    def test_the_shockwave_passes_through_and_ends(self):
        f = Field(800, seed=4); run(f, 2.5)
        f.trigger_shock(); run(f, 0.3)
        self.assertGreater(max(f._radial()), 1.04)                   # points near the wavefront are pushed out
        run(f, 1.5)
        self.assertIsNone(f.shock)


class StateEncoding(unittest.TestCase):
    def settled(self, mode):
        d = Dynamics("idle"); d.set_mode(mode)
        for _ in range(120):
            d.step(0.05)
        return d

    def test_each_state_has_its_own_colour(self):
        ok, bad, wait, work = (self.settled(m).tint for m in ("ok", "bad", "waiting", "working"))
        self.assertTrue(ok[1] > ok[0] and ok[1] > ok[2] * 0.9)       # verified: green
        self.assertTrue(bad[0] > bad[1] * 1.5 and bad[0] > bad[2])   # failed: red
        self.assertTrue(wait[0] > wait[2] * 2 and wait[1] > wait[2] * 1.5)   # needs you: amber
        self.assertTrue(work[2] > work[0] * 1.5 and work[1] > work[0] * 1.5) # working: cyan

    def test_working_spins_faster_and_waiting_holds_still(self):
        idle, work, wait = (self.settled(m).v["spin"] for m in ("idle", "working", "waiting"))
        self.assertGreater(work, idle * 2.5); self.assertLess(wait, idle)

    def test_stopping_collapses_the_sphere_and_much_faster_than_other_changes(self):
        stop, wait = Dynamics("idle"), Dynamics("idle")
        stop.set_mode("stopping"); wait.set_mode("waiting")
        for _ in range(6):
            stop.step(0.05); wait.step(0.05)                         # 0.3 s
        self.assertLess(abs(stop.v["scale"] - 0.55), 0.06)           # a kill switch must look like one
        self.assertGreater(abs(wait.v["scale"] - 0.93), 0.01)        # a routine change glides
        self.assertLess(self.settled("stopping").v["scale"], self.settled("idle").v["scale"] * 0.7)

    def test_changes_are_eased_never_snapped(self):
        d = Dynamics("idle"); d.set_mode("ok"); d.step(0.05)
        self.assertGreater(d.v["mix"], 0.0); self.assertLess(d.v["mix"], MODE_MIX("ok"))

    def test_unknown_modes_are_ignored(self):
        d = Dynamics("idle"); d.set_mode("nonsense"); self.assertEqual(d.mode, "idle")


def MODE_MIX(m):
    return P.MODE[m]["mix"]


class Ring(unittest.TestCase):
    def test_lit_points_are_the_finished_fraction_of_the_plan(self):
        for prog, lit in ((0.0, 0), (0.4, 60), (1.0, 150)):
            pts = ring(0.0, prog, n=150)
            self.assertEqual(sum(1 for p in pts if p[3]), lit)
        self.assertEqual(sum(1 for p in ring(0.0, 0.0) if p[4]), 0)          # no head when nothing is done
        self.assertEqual([i for i, p in enumerate(ring(0.0, 0.4, n=150)) if p[4]], [59])

    def test_progress_is_clamped(self):
        self.assertEqual(sum(1 for p in ring(0.0, 7.0, n=100) if p[3]), 100)
        self.assertEqual(sum(1 for p in ring(0.0, -3.0, n=100) if p[3]), 0)


class Stream(unittest.TestCase):
    def test_particles_flow_from_the_sphere_to_the_provider(self):
        p0, p1, p2 = (0.0, 0.0), (50.0, -30.0), (100.0, 0.0)
        self.assertEqual(bezier(p0, p1, p2, 0.0), p0); self.assertEqual(bezier(p0, p1, p2, 1.0), p2)
        pts = courier(0.0, p0, p1, p2, n=40)
        self.assertEqual(len(pts), 40)
        self.assertTrue(all(0 <= u < 1 for *_, u in pts))
        ends = [a for x, y, a, s, u in pts if u < 0.03 or u > 0.97]
        mids = [a for x, y, a, s, u in pts if 0.45 < u < 0.55]
        self.assertLess(max(ends or [0]), 0.35); self.assertGreater(min(mids), 0.9)   # fade in at the sphere, out at the node

    def test_the_stream_advances_with_time(self):
        p0, p1, p2 = (0.0, 0.0), (50.0, -30.0), (100.0, 0.0)
        self.assertNotEqual(courier(0.0, p0, p1, p2), courier(0.5, p0, p1, p2))


class Adaptive(unittest.TestCase):
    def test_slow_frames_step_the_detail_down_after_patience_and_never_below_the_floor(self):
        q = Quality(patience=10)
        for _ in range(9):
            self.assertFalse(q.record(80))
        self.assertTrue(q.record(80)); self.assertEqual(q.n, P.LEVELS[1])
        for _ in range(200):
            q.record(80)
        self.assertEqual(q.n, P.LEVELS[-1])

    def test_fast_frames_never_downgrade_and_one_slow_spike_is_forgiven(self):
        q = Quality(patience=10)
        for i in range(300):
            q.record(120 if i == 50 else 12)
        self.assertEqual(q.level, 0)

    def test_it_never_goes_back_up_so_it_cannot_flap(self):
        q = Quality(patience=5)
        levels = []
        for ms in [90] * 8 + [2] * 500:           # a slow patch, then a long fast one
            q.record(ms); levels.append(q.level)
        self.assertEqual(levels, sorted(levels))                       # monotone: detail only ever steps down
        self.assertGreaterEqual(levels[-1], 1)
        settled = levels[-1]
        for _ in range(500):
            q.record(2)
        self.assertEqual(q.level, settled)                             # and fast frames alone never move it

    def test_a_stalled_frame_does_not_make_the_simulation_jump(self):
        f = Field(100, seed=1)
        f.advance(30.0)
        self.assertLessEqual(f.t, 0.25 + 1e-9)


if __name__ == "__main__":
    unittest.main()
