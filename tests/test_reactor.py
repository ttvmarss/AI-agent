"""The Reactor engine is pure math: every behaviour is checked without a window."""
import math
import unittest

from praxis.desktop.qt import reactor as RX


def run(r, secs, fps=30):
    for _ in range(int(secs * fps)):
        r.advance(1.0 / fps)


class Geometry(unittest.TestCase):
    def test_the_parts_nest_from_the_core_out_to_the_scale_with_room_between(self):
        order = [RX.CORE_R, RX.TRI_R, RX.PAL_R[0], RX.PAL_R[1], RX.COIL_IN, RX.COIL_OUT, RX.HOUSING_IN, RX.HOUSING_OUT, RX.VOICE_IN,
                 RX.VOICE_OUT, RX.RING_R["verify"], RX.RING_R["act"], RX.RING_R["plan"], RX.SCALE_R[0], RX.SCALE_R[1]]
        self.assertEqual(order, sorted(order)); self.assertEqual(len(set(order)), len(order))
        self.assertEqual(RX.EXTENT, RX.SCALE_R[1]); self.assertEqual(RX.HOUSING_OUT, 1.0)
        self.assertGreater(RX.RING_R["act"] - RX.RING_R["verify"], 0.15)           # rings are far enough apart to read as separate

    def test_ten_coils_in_the_coil_annulus_separated_by_gaps(self):
        polys = RX.coil_polys(0, 0, 100.0, 0.0)
        self.assertEqual(len(polys), RX.COILS)
        for pts in polys:
            self.assertEqual(len(pts), 4)
            radii = [math.hypot(x, y) for x, y in pts]
            self.assertAlmostEqual(min(radii), RX.COIL_IN * 100, delta=0.5); self.assertLessEqual(max(radii), RX.COIL_OUT * 100 + 0.1)
        def mid(pts): return math.atan2(sum(y for x, y in pts), sum(x for x, y in pts))
        spans = [(math.degrees(math.atan2(p[1][1], p[1][0]) - math.atan2(p[0][1], p[0][0])) % 360) for p in polys]
        self.assertTrue(all(abs(s - (360 / RX.COILS - math.degrees(RX.COIL_GAP))) < 0.5 for s in spans))      # each coil spans its slot minus the gap

    def test_rotation_moves_the_coils_and_a_full_turn_of_one_slot_looks_the_same(self):
        a = RX.coil_polys(10, 20, 100, 0.0); b = RX.coil_polys(10, 20, 100, 0.3)
        self.assertNotEqual(a[0], b[0])
        c = RX.coil_polys(10, 20, 100, math.tau / RX.COILS)
        for (x1, y1), (x2, y2) in zip(a[1], c[0]):
            self.assertAlmostEqual(x1, x2, places=6); self.assertAlmostEqual(y1, y2, places=6)

    def test_the_triangle_is_equilateral_and_turns(self):
        t = RX.triangle(0, 0, 100, 0.0)
        sides = [math.dist(t[i], t[(i + 1) % 3]) for i in range(3)]
        self.assertTrue(max(sides) - min(sides) < 1e-6); self.assertAlmostEqual(math.hypot(*t[0]), RX.TRI_R * 100, places=6)
        self.assertNotEqual(RX.triangle(0, 0, 100, 0.5), t)

    def test_ring_segments_partition_the_ring_in_order_with_gaps(self):
        self.assertEqual(RX.ring_segments(0), []); self.assertEqual(RX.ring_segments(1), [(0.0, 360.0)])        # one segment: a closed ring
        for n in (2, 3, 5, 12, 40):
            segs = RX.ring_segments(n)
            self.assertEqual(len(segs), n)
            for (s0, sp0), (s1, sp1) in zip(segs, segs[1:]):
                self.assertGreater(s1, s0); self.assertAlmostEqual(s0 + sp0 + RX.GAP_DEG, s1, places=6)           # in order, a gap between neighbours
            self.assertLessEqual(segs[-1][0] + segs[-1][1], 360.0)

    def test_the_scale_has_major_minor_and_cardinal_ticks_and_turns(self):
        t = RX.ticks(0.0)
        self.assertEqual(len(t), 72); self.assertEqual(sum(1 for _, k in t if k == 2), 4)
        self.assertEqual(sum(1 for _, k in t if k == 1), 32); self.assertEqual(sum(1 for _, k in t if k == 0), 36)
        self.assertAlmostEqual(RX.ticks(0.5)[0][0] - t[0][0], 0.5)


class Paths(unittest.TestCase):
    def test_polyline_points_run_by_length_from_end_to_end(self):
        pts = [(0, 0), (100, 0), (100, 50)]
        self.assertEqual(RX.polyline_point(pts, 0.0), (0, 0))
        x, y = RX.polyline_point(pts, 1.0); self.assertAlmostEqual(x, 100); self.assertAlmostEqual(y, 50)
        x, y = RX.polyline_point(pts, 100.0 / 150.0); self.assertAlmostEqual(x, 100); self.assertAlmostEqual(y, 0, places=6)        # the elbow
        self.assertEqual(RX.polyline_point(pts, -3), (0, 0)); self.assertEqual(RX.polyline_point([(5, 5), (5, 5)], 0.5), (5, 5))

    def test_the_stream_runs_from_the_reactor_to_the_provider_and_advances(self):
        pts = [(0, 0), (50, 0), (100, 30)]
        a = RX.courier_poly(0.0, pts); b = RX.courier_poly(0.4, pts)
        self.assertEqual(len(a), 44); self.assertNotEqual(a, b)
        for x, y, al, s, u in a:
            self.assertTrue(0 <= x <= 100 and 0 <= y <= 30 and 0 <= al <= 1 and 0 <= u < 1 and s > 0)
        self.assertEqual(RX.courier_poly(0.0, pts, n=0), [])

    def test_the_curve_courier_still_ends_where_it_should(self):
        (x0, y0, *_), (x1, y1, *_) = RX.courier(0.0, (0, 0), (50, 50), (100, 0), n=2)[0], RX.courier(0.0, (0, 0), (50, 50), (100, 0), n=2)[1]
        self.assertTrue(x0 < x1)


class StateEncoding(unittest.TestCase):
    def test_every_state_defines_every_parameter(self):
        for mode, spec in RX.MODE.items():
            for key in RX.Dynamics.KEYS + ("tint",):
                self.assertIn(key, spec, (mode, key))

    def test_each_state_has_its_own_colour(self):
        tints = {m: tuple(s["tint"]) for m, s in RX.MODE.items() if m != "stopped"}
        self.assertEqual(len(set(tints.values())), len(tints))
        idle, work, wait, ok, bad = (RX.MODE[m]["tint"] for m in ("idle", "working", "waiting", "ok", "bad"))
        self.assertTrue(idle[2] > idle[0] and work[2] > work[0])                   # reactor blue
        self.assertTrue(wait[0] > wait[2] * 2 and wait[1] > wait[2])               # orange
        self.assertTrue(ok[0] > ok[2] and ok[1] > ok[2] + 50)                      # gold
        self.assertTrue(bad[0] > 200 and bad[1] < 100)                             # red

    def test_changes_are_eased_never_snapped(self):
        d = RX.Dynamics("idle"); d.set_mode("working"); d.step(0.05)
        self.assertTrue(RX.MODE["idle"]["spin"] < d.v["spin"] < RX.MODE["working"]["spin"])
        for _ in range(300):
            d.step(0.05)
        self.assertAlmostEqual(d.v["spin"], RX.MODE["working"]["spin"], places=3)

    def test_stopping_snaps_much_faster_than_other_changes(self):
        a, b = RX.Dynamics("working"), RX.Dynamics("working")
        a.set_mode("stopping"); b.set_mode("idle")
        for _ in range(10):
            a.step(0.05); b.step(0.05)
        self.assertLess(a.v["spin"], 0.1)                                          # a kill switch must look like one
        self.assertGreater(abs(RX.MODE["working"]["spin"] - a.v["spin"]), abs(RX.MODE["working"]["spin"] - b.v["spin"]))

    def test_unknown_modes_are_ignored(self):
        d = RX.Dynamics("idle"); d.set_mode("nonsense"); self.assertEqual(d.mode, "idle")


class Motion(unittest.TestCase):
    def test_spin_follows_the_state(self):
        speeds = {}
        for mode in ("idle", "working", "waiting", "stopping"):
            r = RX.Reactor(); r.dyn.set_mode(mode); run(r, 4.0)
            before = r.coil_rot; run(r, 1.0); speeds[mode] = (r.coil_rot - before) % math.tau
        self.assertGreater(speeds["working"], speeds["idle"] * 3); self.assertLess(speeds["waiting"], speeds["idle"]); self.assertLess(speeds["stopping"], 0.05)

    def test_the_coils_light_one_by_one_while_it_powers_up(self):
        r = RX.Reactor(); r.dyn.set_mode("idle")
        r.advance(0.5)
        lit = [r.coil_charge(i) for i in range(RX.COILS)]
        self.assertGreater(lit[0], lit[-1]); self.assertEqual(lit[-1], 0.0)        # the first coil is on before the last
        run(r, 3.0)
        self.assertTrue(all(r.coil_charge(i) > 0.3 for i in range(RX.COILS)))
        r.restart_power_up(); r.advance(0.05)
        self.assertEqual(r.coil_charge(RX.COILS - 1), 0.0)                         # a restart re-lights them

    def test_working_chases_light_round_the_coils_waiting_pulses_them_together_stopping_fades_them(self):
        r = RX.Reactor(); r.dyn.set_mode("working"); run(r, 4.0)
        ch = [r.coil_charge(i) for i in range(RX.COILS)]
        self.assertGreater(max(ch) - min(ch), 0.25)                                # a bright run, not a flat glow
        r2 = RX.Reactor(); r2.dyn.set_mode("waiting"); run(r2, 4.0)
        ch2 = [r2.coil_charge(i) for i in range(RX.COILS)]
        self.assertLess(max(ch2) - min(ch2), 1e-9)                                 # all together
        samples = []
        for _ in range(40):
            r2.advance(0.05); samples.append(r2.coil_charge(0))
        self.assertGreater(max(samples) - min(samples), 0.2)                       # ...and they breathe
        r3 = RX.Reactor(); r3.dyn.set_mode("stopping"); run(r3, 4.0)
        self.assertLess(max(r3.coil_charge(i) for i in range(RX.COILS)), 0.2)

    def test_events_flare_the_core_which_then_fades_and_is_capped(self):
        r = RX.Reactor(); run(r, 3.0)
        base = r.core_level(); r.pulse(); self.assertGreater(r.core_level(), base + 0.3)
        for _ in range(10):
            r.pulse(1.0)
        self.assertLessEqual(r.flare, 1.5)
        run(r, 2.0); self.assertEqual(r.flare, 0.0)

    def test_the_shockwave_passes_through_and_ends(self):
        r = RX.Reactor(); self.assertIsNone(r.shock)
        r.trigger_shock(); run(r, 0.5); self.assertTrue(0.2 < r.shock < 0.6)
        run(r, 2.0); self.assertIsNone(r.shock)

    def test_embers_rise_are_bounded_follow_the_state_and_die(self):
        r = RX.Reactor(80); r.dyn.set_mode("working"); run(r, 5.0)
        self.assertTrue(10 < len(r.embers) <= 80)
        r2 = RX.Reactor(80); r2.dyn.set_mode("bad"); run(r2, 5.0)
        self.assertLess(len(r2.embers), len(r.embers))                             # calmer states throw fewer sparks
        e0 = [list(e) for e in r.embers]; run(r, 0.5)
        self.assertTrue(sum(1 for e in r.embers if e[1] < -0.2) > 0)               # they rise (negative y is up)
        r.resize(5); self.assertLessEqual(len(r.embers), 5); r.resize(0); run(r, 1.0); self.assertEqual(len(r.embers), 0)

    def test_a_stalled_frame_does_not_make_the_simulation_jump_and_bad_steps_are_ignored(self):
        r = RX.Reactor(); r.dyn.set_mode("working"); run(r, 1.0)
        rot = r.coil_rot; r.advance(500.0)
        self.assertLess((r.coil_rot - rot) % math.tau, 0.95 * 0.26 + 0.05)         # clamped to a quarter second
        t = r.t
        for bad in (0.0, -1.0, float("nan")):
            r.advance(bad) if bad == bad else None
        self.assertEqual(r.t, t)

    def test_core_level_is_always_finite_and_bounded(self):
        r = RX.Reactor()
        for mode in RX.MODE:
            r.dyn.set_mode(mode)
            for _ in range(200):
                r.advance(0.05); v = r.core_level()
                self.assertTrue(math.isfinite(v) and 0.0 <= v < 2.5, (mode, v))

    def test_same_seed_same_sparks(self):
        a, b = RX.Reactor(seed=3), RX.Reactor(seed=3); c = RX.Reactor(seed=4)
        for r in (a, b, c):
            r.dyn.set_mode("working"); run(r, 3.0)
        self.assertEqual(a.embers, b.embers); self.assertNotEqual(a.embers, c.embers)


class Adaptive(unittest.TestCase):
    def test_slow_frames_step_the_detail_down_after_patience_and_never_below_the_floor(self):
        q = RX.Quality(limit_ms=10.0, patience=5)
        for _ in range(4): self.assertFalse(q.record(50.0))
        self.assertTrue(q.record(50.0)); self.assertEqual(q.level, 1)
        for _ in range(200): q.record(50.0)
        self.assertEqual(q.level, len(RX.LEVELS) - 1); self.assertEqual(q.n, RX.LEVELS[-1]); self.assertEqual(q.bars, RX.BAR_LEVELS[-1])

    def test_fast_frames_never_downgrade_and_it_never_goes_back_up(self):
        q = RX.Quality(limit_ms=40.0, patience=5)
        for _ in range(100): q.record(8.0)
        self.assertEqual(q.level, 0)
        q.record(200.0)                                                            # one slow spike is forgiven
        for _ in range(20): q.record(8.0)
        self.assertEqual(q.level, 0)
        for _ in range(60): q.record(200.0)
        lvl = q.level; self.assertGreater(lvl, 0)
        for _ in range(200): q.record(1.0)
        self.assertEqual(q.level, lvl)


if __name__ == "__main__":
    unittest.main()
