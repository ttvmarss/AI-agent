"""The particle engine is pure math (no Qt), so every behaviour that is supposed to encode real state is checked here."""
import math, unittest

from praxis.desktop.qt import particles as P
from praxis.desktop.qt.particles import Dynamics, Nebula, Quality, bezier, courier, segment_of


def run(f, secs, step=0.05):
    """Advance in realistic frame-sized steps (advance() clamps a single step so a stalled frame cannot make things jump)."""
    for _ in range(int(round(secs / step))):
        f.advance(step)


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs)


def settled(n, secs=3.0):
    f = Nebula(n, seed=3)
    run(f, 2.5)                                   # past the assembly intro
    return f


class Structure(unittest.TestCase):
    def test_the_radial_table_runs_from_the_core_to_the_rim_and_the_spiral_winds_outward(self):
        self.assertAlmostEqual(P.RT[0], P.RMIN); self.assertAlmostEqual(P.RT[-1], 1.0)
        self.assertEqual(P.RT, sorted(P.RT)); self.assertEqual(P.SPT, sorted(P.SPT))
        self.assertAlmostEqual(P.SPT[0], 0.0); self.assertGreater(P.SPT[-1], 2.0)         # the arms really spiral

    def test_three_arms_each_with_a_fair_share_of_the_particles(self):
        f = Nebula(2000, seed=5)
        arms = sorted(set(round(a, 3) for a in f.ARM))
        self.assertEqual(len(arms), P.ARMS)
        for a in arms:
            self.assertGreater(sum(1 for x in f.ARM if round(x, 3) == a) / f.nd, 0.25)

    def test_a_disc_and_a_sparse_halo(self):
        f = Nebula(2000, seed=5)
        self.assertEqual(f.nd + f.nh, 2000); self.assertEqual(f.nh, int(2000 * P.HALO_SHARE))
        self.assertTrue(all(0.55 <= r <= 1.15 for r in f.HR))

    def test_same_seed_same_galaxy_and_a_different_seed_differs(self):
        a, b, c = Nebula(500, seed=9), Nebula(500, seed=9), Nebula(500, seed=10)
        self.assertEqual(a.S0, b.S0); self.assertNotEqual(a.S0, c.S0)

    def test_sparks_and_comets_are_rare_and_distinct(self):
        f = Nebula(2400, seed=2)
        self.assertLess(sum(f.spark) / f.nd, 0.03); self.assertTrue(any(f.spark))
        self.assertEqual(len(f.comet_ids), P.COMETS); self.assertFalse(any(f.spark[i] for i in f.comet_ids))

    def test_resize_rebuilds_to_the_requested_count(self):
        f = Nebula(900); f.resize(600)
        self.assertEqual((f.n, f.nd + f.nh), (600, 600))


class Projection(unittest.TestCase):
    def setUp(self):
        self.f = settled(2000)
        self.cx, self.cy, self.R = 500.0, 200.0, 100.0

    def test_every_particle_is_accounted_for_once(self):
        buckets, sparks = self.f.project(self.cx, self.cy, self.R)
        self.assertEqual(sum(len(b) for b in buckets) + len(sparks), 2000)
        self.assertEqual(len(buckets), P.NB * 3 * P.VARIANTS)

    def test_the_picture_is_wide_not_tall_and_stays_near_the_widget_radius(self):
        buckets, sparks = self.f.project(self.cx, self.cy, self.R)
        pts = [pt for b in buckets for pt in b]
        xs, ys = [x - self.cx for x, y in pts], [y - self.cy for x, y in pts]
        self.assertLess(max(abs(x) for x in xs), 2.5 * self.R); self.assertLess(max(abs(y) for y in ys), 1.7 * self.R)
        self.assertGreater(mean(abs(x) for x in xs), 1.2 * mean(abs(y) for y in ys))          # the widescreen stretch

    def test_blue_above_and_pink_below_like_the_reference(self):
        buckets, _ = self.f.project(self.cx, self.cy, self.R, mk=lambda x, y: y)
        def mean_bucket(sel):
            tot = n = 0
            for k, b in enumerate(buckets):
                bi = k // (3 * P.VARIANTS)
                if bi < P.BUCKETS:
                    for y in b:
                        if sel(y):
                            tot += bi; n += 1
            return tot / n
        self.assertLess(mean_bucket(lambda y: y < self.cy - 0.2 * self.R), mean_bucket(lambda y: y > self.cy + 0.2 * self.R))
        t, b = P.palette_at(0.0), P.palette_at(1.0)
        self.assertGreater(t[2], t[0]); self.assertGreater(b[0], b[1])

    def test_the_white_hot_core_holds_only_points_right_at_the_centre(self):
        buckets, _ = self.f.project(self.cx, self.cy, self.R, mk=lambda x, y: (x, y))
        core = [pt for k, b in enumerate(buckets) if k // (3 * P.VARIANTS) == P.BUCKETS for pt in b]
        self.assertTrue(core)
        self.assertTrue(all(abs(x - self.cx) < 0.5 * self.R * P.ASP and abs(y - self.cy) < 0.5 * self.R for x, y in core))

    def test_particles_are_split_into_faded_ordinary_and_arm_centre_brightness(self):
        buckets, _ = Nebula(3000, seed=7).project(0, 0, 100)
        by_variant = [0] * P.VARIANTS
        for k, b in enumerate(buckets):
            by_variant[k % P.VARIANTS] += len(b)
        total = sum(by_variant)
        # faded = the whole dim halo (18%) + disc particles being born/dying at the arm ends (~19% of the disc) = ~34%;
        # arm-centre = ~59% of the rest of the disc = ~39%; ordinary = the remainder
        self.assertTrue(0.28 < by_variant[0] / total < 0.40, by_variant)
        self.assertTrue(0.30 < by_variant[2] / total < 0.48, by_variant)
        self.assertGreater(by_variant[1] / total, 0.15)

    def test_all_three_depth_layers_are_used_so_the_rings_can_weave_through(self):
        buckets, _ = settled(2000).project(0, 0, 100)
        per_depth = [0, 0, 0]
        for k, b in enumerate(buckets):
            per_depth[(k // P.VARIANTS) % 3] += len(b)
        self.assertTrue(all(n > 100 for n in per_depth), per_depth)

    def test_the_position_helper_agrees_with_the_projection(self):
        f = settled(300)
        buckets, sparks = f.project(100.0, 50.0, 40.0, mk=lambda x, y: (round(x, 6), round(y, 6)))
        drawn = {pt for b in buckets for pt in b} | {(round(x, 6), round(y, 6)) for x, y, z, i in sparks}
        for i in range(f.nd):
            x, y, z2 = f.pos(i, (f.S0[i] + f.sflow) % 1.0, 100.0, 50.0, 40.0)
            self.assertIn((round(x, 6), round(y, 6)), drawn, i)

    def test_mk_builds_the_points(self):
        buckets, _ = settled(300).project(0, 0, 50, mk=lambda x, y: ("P", round(x), round(y)))
        self.assertTrue(all(pt[0] == "P" for b in buckets for pt in b))

    def test_it_turns_and_cursor_tilt_changes_the_picture_smoothly(self):
        f = settled(400)
        a = f.project(0, 0, 100)[0]
        run(f, 0.5); self.assertNotEqual(a, f.project(0, 0, 100)[0])
        b = f.project(0, 0, 100)[0]
        f.tilt_target = [0.3, 0.4]; f.advance(0.05)
        self.assertTrue(0 < f.tilt[0] < 0.3)                                                # eased, not snapped
        run(f, 3.0); self.assertAlmostEqual(f.tilt[0], 0.3, places=2)


class FlowIsMeaning(unittest.TestCase):
    """Arms flow INWARD while PRAXIS works, hold still when it needs you, flow OUTWARD when a result is verified."""
    def flow(self, mode, secs=3.0):
        f = settled(200)
        f.dyn.set_mode(mode); before = f.sflow
        run(f, secs)
        return (f.sflow - before) / secs, f.dyn.v["flow"]

    def test_direction_per_state(self):
        _, work = self.flow("working"); _, ok = self.flow("ok"); _, wait = self.flow("waiting"); _, idle = self.flow("idle")
        self.assertLess(work, -0.1); self.assertGreater(ok, 0.1); self.assertLess(abs(wait), 0.02); self.assertGreater(idle, 0)
        self.assertLess(self.flow("stopping")[1], work * 3)                                    # STOP drains it in far faster

    def test_a_particle_really_moves_inward_while_working_and_outward_when_verified(self):
        f = settled(200); i = 0
        radius = lambda: P.RT[int(((f.S0[i] + f.sflow) % 1.0) * P.TS)]
        park = lambda: f.S0.__setitem__(i, (0.5 - f.sflow) % 1.0)          # put it exactly mid-arm right now
        f.dyn.set_mode("working"); run(f, 1.0)                            # let the flow ease in
        park(); r0 = radius(); run(f, 0.3); r1 = radius()
        self.assertLess(r1, r0)                                           # moved toward the core
        f.dyn.set_mode("ok"); run(f, 1.5)
        park(); r2 = radius(); run(f, 0.3); r3 = radius()
        self.assertGreater(r3, r2)                                        # moved away from it

    def test_spin_and_ring_spin_follow_the_state(self):
        d = {m: self.settle(m) for m in ("idle", "working", "waiting", "stopping")}
        self.assertGreater(d["working"]["rspin"], d["idle"]["rspin"]); self.assertLess(d["waiting"]["rspin"], d["idle"]["rspin"] * 0.3)
        self.assertGreater(d["working"]["spin"], d["idle"]["spin"]); self.assertLess(d["waiting"]["spin"], d["idle"]["spin"])

    def settle(self, mode):
        d = Dynamics("idle"); d.set_mode(mode)
        for _ in range(160):
            d.step(0.05)
        return d.v


class Assembly(unittest.TestCase):
    def test_it_starts_scattered_and_converges_into_the_galaxy(self):
        f = Nebula(800, seed=4)
        self.assertGreater(min(f._radial_disc(i, P.RT[100]) for i in range(f.nd)), 1.7)        # every point starts well outside
        prev = mean(f._radial_disc(i, 0.5) for i in range(f.nd))
        for _ in range(12):
            f.advance(0.1)
            cur = mean(f._radial_disc(i, 0.5) for i in range(f.nd)) if f.asm < 1.0 else 1.0
            self.assertLessEqual(cur, prev + 1e-9); prev = cur
        run(f, 1.5); self.assertEqual(f.asm, 1.0)

    def test_the_rings_unfold_from_nothing_while_it_assembles(self):
        f = Nebula(200, seed=4)
        closed = f.ring(0, 100.0, 50.0, 80.0)
        self.assertTrue(all(abs(x - 100.0) < 1e-6 and abs(y - 50.0) < 1e-6 for x, y, z, i in closed))
        run(f, 3.0)
        opened = f.ring(0, 100.0, 50.0, 80.0)
        self.assertGreater(max(abs(x - 100.0) for x, y, z, i in opened), 100.0)

    def test_restart_assembly_scatters_again(self):
        f = settled(300); self.assertEqual(f.asm, 1.0)
        f.restart_assembly(); self.assertEqual(f.asm, 0.0)

    def test_the_shockwave_passes_through_and_ends(self):
        f = settled(800)
        self.assertEqual(f._radial_disc(0, 0.6), 1.0)                      # no wave: no displacement
        f.trigger_shock(); run(f, 0.3)
        front = P.ease_out(f.shock / 1.4) * 1.5                            # where the wavefront is right now
        self.assertGreater(f._radial_disc(0, front), 1.05)                 # particles AT the front are pushed outward...
        self.assertAlmostEqual(f._radial_disc(0, front + 1.0), 1.0, places=3)   # ...and those far from it are not
        run(f, 1.5); self.assertIsNone(f.shock)

    def test_events_flare_the_seed_which_then_fades_and_is_capped(self):
        f = settled(100)
        f.pulse(1.0); self.assertAlmostEqual(f.flare, 1.0)
        run(f, 0.4); self.assertTrue(0.2 < f.flare < 0.6)
        run(f, 1.0); self.assertEqual(f.flare, 0.0)
        for _ in range(10):
            f.pulse(1.0)
        self.assertLessEqual(f.flare, 1.6)

    def test_a_stalled_frame_does_not_make_the_simulation_jump(self):
        f = Nebula(100, seed=1); f.advance(30.0)
        self.assertLessEqual(f.t, 0.25 + 1e-9)


class StateEncoding(unittest.TestCase):
    def settled(self, mode):
        d = Dynamics("idle"); d.set_mode(mode)
        for _ in range(120):
            d.step(0.05)
        return d

    def test_each_state_has_its_own_colour(self):
        ok, bad, wait, work = (self.settled(m).tint for m in ("ok", "bad", "waiting", "working"))
        self.assertTrue(ok[1] > ok[0] and ok[1] > ok[2] * 0.9)                    # verified: green
        self.assertTrue(bad[0] > bad[1] * 1.5 and bad[0] > bad[2])                # failed: red
        self.assertTrue(wait[0] > wait[2] * 2 and wait[1] > wait[2] * 1.5)        # needs you: amber
        self.assertTrue(work[2] > work[0] * 1.5 and work[1] > work[0] * 1.5)      # working: cyan

    def test_stopping_collapses_it_and_much_faster_than_other_changes(self):
        stop, wait = Dynamics("idle"), Dynamics("idle")
        stop.set_mode("stopping"); wait.set_mode("waiting")
        for _ in range(6):
            stop.step(0.05); wait.step(0.05)                                      # 0.3 s
        self.assertLess(abs(stop.v["scale"] - 0.50), 0.06)                        # a kill switch must look like one
        self.assertGreater(abs(wait.v["scale"] - 0.94), 0.01)                     # a routine change glides
        self.assertLess(self.settled("stopping").v["scale"], self.settled("idle").v["scale"] * 0.7)

    def test_changes_are_eased_never_snapped(self):
        d = Dynamics("idle"); d.set_mode("ok"); d.step(0.05)
        self.assertGreater(d.v["mix"], 0.0); self.assertLess(d.v["mix"], P.MODE["ok"]["mix"])

    def test_unknown_modes_are_ignored(self):
        d = Dynamics("idle"); d.set_mode("nonsense"); self.assertEqual(d.mode, "idle")

    def test_every_state_defines_every_parameter(self):
        for mode, v in P.MODE.items():
            for key in Dynamics.KEYS + ("tint",):
                self.assertIn(key, v, (mode, key))


class Rings(unittest.TestCase):
    def test_three_rings_that_weave_through_the_galaxy_plane_and_nest_in_size(self):
        f = settled(100)
        rings = [f.ring(k, 0.0, 0.0, 100.0) for k in range(3)]
        for pts in rings:
            self.assertEqual([i for *_, i in pts], list(range(len(pts))))
            zs = [z for x, y, z, i in pts]
            self.assertTrue(min(zs) < -0.1 and max(zs) > 0.1)                       # part behind the galaxy, part in front
        width = [max(abs(x) for x, y, z, i in pts) for pts in rings]
        self.assertTrue(width[0] > width[1] > width[2])                             # PLAN outside ACT outside VERIFY
        self.assertEqual([r["name"] for r in P.RINGS], ["plan", "act", "verify"])

    def test_rings_spin_at_their_own_rates_and_faster_while_working(self):
        f = settled(100)
        a = f.ring(1, 0, 0, 100.0)
        run(f, 1.0); b = f.ring(1, 0, 0, 100.0)
        self.assertNotEqual(a, b)
        f.dyn.set_mode("waiting"); run(f, 4.0)
        c = f.ring(1, 0, 0, 100.0); run(f, 0.5); d = f.ring(1, 0, 0, 100.0)
        mv = lambda p, q: mean(math.hypot(p[i][0] - q[i][0], p[i][1] - q[i][1]) for i in range(len(p)))
        self.assertLess(mv(c, d), mv(a, b))                                         # holds nearly still while it waits for you

    def test_segments_partition_a_ring_with_gaps_between_them(self):
        n, segs = 150, 4
        got = [segment_of(i, n, segs) for i in range(n)]
        self.assertEqual({g[0] for g in got if g}, {0, 1, 2, 3})
        gaps = sum(1 for g in got if g is None)
        self.assertTrue(0.15 * n < gaps < 0.25 * n, gaps)                           # ~GAP of the ring is empty
        self.assertTrue(all(0.0 <= g[1] <= 1.0 for g in got if g))
        self.assertEqual([segment_of(i, n, 1) for i in range(n)].count(None), 0)    # one segment = a closed ring: no gap
        self.assertIsNone(segment_of(3, n, 0))

    def test_segments_run_in_order_around_the_ring(self):
        n = 120
        order = [g[0] for g in (segment_of(i, n, 5) for i in range(n)) if g]
        self.assertEqual(order, sorted(order))

    def test_the_extent_helper_measures_the_unfolded_rings(self):
        hw, hh = P.ring_extent()
        self.assertGreater(hw, 1.5); self.assertGreater(hh, 0.8); self.assertGreater(hw, hh)


class Streams(unittest.TestCase):
    def test_particles_flow_from_the_galaxy_to_the_provider(self):
        p0, p1, p2 = (0.0, 0.0), (50.0, -30.0), (100.0, 0.0)
        self.assertEqual(bezier(p0, p1, p2, 0.0), p0); self.assertEqual(bezier(p0, p1, p2, 1.0), p2)
        pts = courier(0.0, p0, p1, p2, n=40)
        self.assertEqual(len(pts), 40); self.assertTrue(all(0 <= u < 1 for *_, u in pts))
        ends = [a for x, y, a, s, u in pts if u < 0.03 or u > 0.97]
        mids = [a for x, y, a, s, u in pts if 0.45 < u < 0.55]
        self.assertLess(max(ends or [0]), 0.35); self.assertGreater(min(mids), 0.9)        # fade in at the galaxy, out at the node

    def test_the_stream_advances_with_time(self):
        p0, p1, p2 = (0.0, 0.0), (50.0, -30.0), (100.0, 0.0)
        self.assertNotEqual(courier(0.0, p0, p1, p2), courier(0.5, p0, p1, p2))

    def test_comets_have_fading_shrinking_tails_that_follow_their_arm(self):
        f = settled(600)
        tails = f.comets(300.0, 150.0, 100.0)
        self.assertEqual(len(tails), P.COMETS)
        for tail in tails:
            self.assertEqual(len(tail), P.TAIL)
            sizes = [s for x, y, a, s in tail]
            self.assertEqual(sizes, sorted(sizes, reverse=True)); self.assertLess(sizes[-1], sizes[0])
            self.assertTrue(all(0.0 <= a <= 1.0 for x, y, a, s in tail))
        length = lambda t: math.hypot(t[0][0] - t[-1][0], t[0][1] - t[-1][1])
        self.assertGreater(sum(1 for t in tails if length(t) > 0.5), P.COMETS // 2)         # the tails have real length

    def test_a_comets_tail_trails_behind_the_direction_of_flow(self):
        f = settled(600); f.dyn.set_mode("working"); run(f, 3.0)                             # flowing inward
        i = f.comet_ids[0]
        f.S0[i] = (0.5 - f.sflow) % 1.0                                                      # park it mid-arm, away from any wrap-around
        head = f.comets(0.0, 0.0, 100.0)[0]
        r = lambda x, y: math.hypot(x / P.ASP, y)
        self.assertGreater(r(head[-1][0], head[-1][1]), r(head[0][0], head[0][1]))           # flowing in: the tail is farther OUT
        f.dyn.set_mode("ok"); run(f, 3.0)                                                    # flowing outward
        f.S0[i] = (0.5 - f.sflow) % 1.0
        head = f.comets(0.0, 0.0, 100.0)[0]
        self.assertLess(r(head[-1][0], head[-1][1]), r(head[0][0], head[0][1]))              # flowing out: the tail is farther IN


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
            q.record(150 if i == 50 else 12)
        self.assertEqual(q.level, 0)

    def test_it_never_goes_back_up_so_it_cannot_flap(self):
        q = Quality(patience=5)
        levels = []
        for ms in [90] * 8 + [2] * 500:           # a slow patch, then a long fast one
            q.record(ms); levels.append(q.level)
        self.assertEqual(levels, sorted(levels))
        self.assertGreaterEqual(levels[-1], 1)
        settled_level = levels[-1]
        for _ in range(500):
            q.record(2)
        self.assertEqual(q.level, settled_level)

    def test_a_frame_between_the_limit_and_a_slow_one_is_the_governors_boundary(self):
        q = Quality(patience=5, limit_ms=40.0)
        for _ in range(60):
            q.record(39.0)
        self.assertEqual(q.level, 0)                # just under the limit: stays
        q2 = Quality(patience=5, limit_ms=40.0)
        for _ in range(60):
            q2.record(41.0)
        self.assertGreaterEqual(q2.level, 1)        # just over it: steps down


if __name__ == "__main__":
    unittest.main()
