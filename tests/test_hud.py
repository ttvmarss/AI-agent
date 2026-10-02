"""The HUD's JSON language: expressions, colours, templates, the spec compiler/validator and the motion engine. No Qt needed."""
import copy
import json
import os
import tempfile
import unittest
import unittest.mock

from praxis.desktop.qt.hud import colors, schema as S, spec as specmod
from praxis.desktop.qt.hud.expr import ExprError, Obj, compile_expr
from praxis.desktop.qt.hud.motion import BOLT_MAX, FLOW_LEVELS, LEVELS, Motion, Quality

DEFAULT = specmod.load(specmod.DEFAULT_PATH)


def ev(src, **ctx):
    return compile_expr(src)(ctx)


class Expressions(unittest.TestCase):
    def test_arithmetic_comparison_and_choice(self):
        self.assertAlmostEqual(ev("0.4 + 0.1 * sin(t * 2)", t=1.0), 0.4 + 0.1 * __import__("math").sin(2.0))
        self.assertTrue(ev("a > 2 and b < 5", a=3, b=4))
        self.assertEqual(ev("1 if mode == 'working' else 9", mode="working"), 1)
        self.assertTrue(ev("mode in ('working', 'waiting')", mode="waiting"))
        self.assertTrue(ev("1 < x < 3", x=2)); self.assertFalse(ev("1 < x < 3", x=5))
        self.assertEqual(ev("clamp(x * 3, 0, 2)", x=5), 2)
        self.assertEqual(ev("max(1, 2) + min(5, 4) + abs(-3) + len(items)", items=[1, 2, 3]), 12)

    def test_data_objects_are_read_by_field_and_missing_fields_read_as_zero(self):
        c = {"item": Obj({"pressure": 0.95, "name": "x"}), "steps": [Obj({"a": 1}), Obj({"a": 2})]}
        self.assertEqual(ev("item.pressure * 100", **c), 95.0)
        self.assertEqual(ev("steps[1].a * 3", **c), 6)
        self.assertEqual(ev("item.nope", **c), 0)
        self.assertEqual(ev("steps[7]", **c), 0)

    def test_it_never_raises_and_never_returns_a_nan(self):
        self.assertEqual(ev("1 / 0"), 0.0)
        self.assertEqual(ev("5 % 0"), 0.0)
        self.assertEqual(ev("sqrt(-1)"), 0.0)
        self.assertEqual(ev("9.0 ** 99999"), 0.0)
        e = compile_expr("t.x")                     # a field of a plain number: a runtime failure, recorded once, value falls back
        self.assertEqual(e({"t": 1.0}), 0.0)
        self.assertTrue(e.error)
        self.assertEqual(ev("undefined_name + 1"), 1)

    def test_nothing_outside_the_whitelist_can_be_expressed(self):
        for bad in ("__import__('os').system('x')", "open('/etc/passwd')", "t.__class__", "item._d", "[x for x in t]", "lambda: 1", "sin",
                    "t if t else eval('1')", "{'a': 1}", "x := 1", "f'{t}'", "", "   ", "1 +", "a" * 700):
            with self.assertRaises(ExprError, msg=bad):
                compile_expr(bad)

    def test_a_field_of_a_constant_is_a_harmless_run_time_failure(self):
        e = compile_expr("(1).real")
        self.assertEqual(e({}), 0.0)
        self.assertTrue(e.error)

    def test_ease_pulse_and_friends(self):
        self.assertEqual(ev("ease(0)"), 0.0); self.assertEqual(ev("ease(2)"), 1.0)
        self.assertAlmostEqual(ev("pulse(0.25, 1)"), 1.0)
        self.assertAlmostEqual(ev("tri(0.5)"), 1.0)
        self.assertTrue(-1 <= ev("noise(3.3)") <= 1)
        self.assertEqual(ev("fract(2.25)"), 0.25)


class Colours(unittest.TestCase):
    def pal(self, raw):
        iss = []
        return colors.Palette(raw, iss), iss

    def test_every_colour_form(self):
        p, iss = self.pal({"a": "#112233", "b": "#fff", "c": [10, 20, 30], "d": "#11223380", "alias": "a", "mid": {"mix": ["a", "#ffffff", 0.5]},
                           "p": {"persona": ["a", "c"]}, "faded": {"of": "a", "alpha": 0.5}})
        self.assertEqual(iss, [])
        self.assertEqual(p.compile("a", "x"), (17.0, 34.0, 51.0, 1.0))
        self.assertEqual(p.compile("b", "x")[:3], (255.0, 255.0, 255.0))
        self.assertAlmostEqual(p.compile("d", "x")[3], 128 / 255, places=2)
        self.assertEqual(p.compile("alias", "x"), p.compile("a", "x"))
        self.assertAlmostEqual(p.compile("mid", "x")[0], (17 + 255) / 2)
        f = p.compile("p", "x")
        self.assertEqual(f({"persona": 0.0})[:3], (17.0, 34.0, 51.0)); self.assertEqual(f({"persona": 1.0})[:3], (10.0, 20.0, 30.0))
        self.assertEqual(p.compile("faded", "x")[3], 0.5)

    def test_expression_colours_and_run_time_lookup(self):
        p, iss = self.pal({"ok": "#00ff00", "bad": "#ff0000"})
        f = p.compile("=pick", "x")
        e = compile_expr("'ok' if good else 'bad'")
        self.assertEqual(p.lookup("ok", {})[:3], (0.0, 255.0, 0.0))
        self.assertEqual(p.lookup("nonsense", {}), colors.BLACK)               # a bad name at run time is black, not a crash
        self.assertEqual(p.lookup("#0000ff", {})[:3], (0.0, 0.0, 255.0))

    def test_mistakes_are_reported_with_where_they_are(self):
        p, iss = self.pal({"a": "b", "b": "a", "bad": "#12", "ghost": "nowhere"})
        paths = {i[0] for i in iss}
        self.assertTrue({"palette.a", "palette.bad", "palette.ghost"} <= paths or {"palette.b", "palette.bad", "palette.ghost"} <= paths, iss)
        self.assertTrue(all(i[1] == "error" for i in iss))


class Templates(unittest.TestCase):
    def test_parts_formats_and_escapes(self):
        t = specmod.compile_template("{title}  {cost|.2f}  {{literal}}  {'a' if x else 'b'}")
        self.assertEqual(t({"title": "HI", "cost": 3.14159, "x": 0}), "HI  3.14  {literal}  b")
        self.assertEqual(specmod.compile_template("{n}")({"n": 2.0}), "2")
        with self.assertRaises(ExprError):
            specmod.compile_template("{unclosed")
        with self.assertRaises(ExprError):
            specmod.compile_template("{__import__('os')}")


class SpecValidation(unittest.TestCase):
    def raw(self):
        return copy.deepcopy(DEFAULT.raw)

    def errors(self, raw):
        sp = specmod.compile_spec(raw)
        return sp, [(p, m) for p, s, m in sp.issues if s == "error"]

    def test_the_shipped_design_is_valid_and_has_no_warnings(self):
        self.assertTrue(DEFAULT.ok, DEFAULT.report())
        self.assertEqual([i for i in DEFAULT.issues if i[1] == "warning"], [], DEFAULT.report())
        self.assertGreater(len(DEFAULT.layers), 20)
        self.assertEqual(DEFAULT.runtime_errors(), [])

    def test_the_shipped_design_uses_both_minds_and_every_state_is_defined(self):
        modes = DEFAULT.raw["modes"]
        for m in S.REQUIRED_MODES:
            for k in S.MODE_KEYS_REQUIRED:
                self.assertIn(k, modes[m], (m, k))
        self.assertEqual(modes["idle"]["persona"], 0.0)                         # JARVIS converses
        self.assertEqual(modes["working"]["persona"], 1.0)                      # FRIDAY executes
        for st in S.STATES:
            self.assertIn(st, DEFAULT.states, st)

    def test_every_data_source_the_design_names_exists(self):
        def walk(nodes):
            for n in nodes:
                src = n.props.get("source")
                if src:
                    yield src
                yield from walk(n.kids)
        self.assertTrue(set(walk(DEFAULT.layers)) <= set(S.SOURCES))

    def test_a_typo_is_found_and_located(self):
        raw = self.raw()
        raw["layers"][3]["opacity"] = "0.5 *"
        sp, errs = self.errors(raw)
        self.assertFalse(sp.ok)
        self.assertTrue(any(p.startswith("layers[3].") or p == "layers[3].opacity" for p, m in errs), errs)

    def test_unknown_element_type_property_source_and_enum_are_reported(self):
        raw = self.raw()
        raw["layers"].append({"type": "teapot"})
        raw["layers"].append({"type": "circle", "radiuss": 5})
        raw["layers"].append({"type": "repeat", "source": "nonsense", "item": []})
        raw["layers"].append({"type": "text", "align": "diagonal"})
        raw["layers"].append({"type": "repeat", "item": []})
        sp, errs = self.errors(raw)
        msgs = " | ".join(m for _, m in errs)
        self.assertIn("unknown element type", msgs); self.assertIn("unknown data source", msgs); self.assertIn("must be one of", msgs)
        self.assertIn("needs a 'source'", msgs)
        self.assertTrue(any("radiuss" in m for p, s, m in sp.issues if s == "warning"))        # a typo'd property is a warning, not silence

    def test_missing_palette_colours_modes_and_layers_are_errors(self):
        raw = self.raw(); del raw["palette"]["ok"]
        self.assertIn("palette.ok", [p for p, _ in self.errors(raw)[1]])
        raw = self.raw(); del raw["modes"]["working"]
        self.assertIn("modes.working", [p for p, _ in self.errors(raw)[1]])
        raw = self.raw(); del raw["modes"]["idle"]["bolts"]
        self.assertIn("modes.idle.bolts", [p for p, _ in self.errors(raw)[1]])
        raw = self.raw(); raw["layers"] = []
        self.assertIn("layers", [p for p, _ in self.errors(raw)[1]])
        raw = self.raw(); raw["version"] = 2
        self.assertIn("version", [p for p, _ in self.errors(raw)[1]])

    def test_elements_nested_too_deeply_are_refused(self):
        node = {"type": "circle"}
        for _ in range(20):
            node = {"type": "group", "children": [node]}
        raw = self.raw(); raw["layers"] = [node]
        self.assertTrue(any("deeply" in m for _, m in self.errors(raw)[1]))

    def test_files_never_raise(self):
        d = tempfile.mkdtemp()
        sp = specmod.load(os.path.join(d, "missing.json")); self.assertFalse(sp.ok); self.assertIn("not found", sp.report())
        bad = os.path.join(d, "bad.json"); open(bad, "w").write("{not json")
        sp = specmod.load(bad); self.assertFalse(sp.ok); self.assertIn("not valid JSON", sp.report())
        arr = os.path.join(d, "arr.json"); open(arr, "w").write("[1, 2]")
        self.assertFalse(specmod.load(arr).ok)
        binary = os.path.join(d, "bin.json"); open(binary, "wb").write(b"\xff\xfe\x00\x01")
        self.assertFalse(specmod.load(binary).ok)

    def test_every_element_type_has_a_complete_schema_entry(self):
        for name, props in S.ELEMENTS.items():
            for k, (kind, default) in props.items():
                self.assertIn(kind, (S.NUM, S.BOOL, S.TEXT, S.COLOR, S.STR, S.POINTS, S.LIST, S.SOURCE), (name, k))
        self.assertTrue(set(S.CHOICES) <= {k for p in S.ELEMENTS.values() for k in p})


class MotionEngine(unittest.TestCase):
    def motion(self, **kw):
        return Motion(DEFAULT.modes, DEFAULT.persona_rate, boot=DEFAULT.boot, **kw)

    def run_for(self, m, secs, fps=30):
        for _ in range(int(secs * fps)):
            m.advance(1 / fps)

    def test_the_persona_glides_to_friday_when_work_starts_and_back_to_jarvis_when_it_ends(self):
        m = self.motion(mode="idle")
        self.run_for(m, 3)
        self.assertLess(m.v["persona"], 0.05)
        m.set_mode("working")
        self.run_for(m, 0.25)
        mid = m.v["persona"]
        self.assertTrue(0.1 < mid < 0.95, mid)                                    # a glide, not a snap
        self.run_for(m, 4)
        self.assertGreater(m.v["persona"], 0.97)
        m.set_mode("ok"); self.run_for(m, 4)
        self.assertLess(m.v["persona"], 0.4)

    def test_stop_is_fast_and_the_spin_dies(self):
        m = self.motion(mode="working"); self.run_for(m, 3)
        spin = m.v["spin"]; self.assertGreater(spin, 0.5)
        m.set_mode("stopping"); self.run_for(m, 0.6)
        self.assertLess(m.v["spin"], spin * 0.05)

    def test_the_hud_draws_itself_in_one_element_after_another_and_finishes(self):
        m = self.motion()
        self.assertEqual(m.reveal(0), 0.0)
        self.run_for(m, 1.0)
        early, late = m.reveal(1), m.reveal(12)
        self.assertGreater(early, late)
        self.run_for(m, 4.0)
        self.assertEqual(m.reveal(12), 1.0)                                       # even the last element of the sequence completes (a defect once)
        self.assertEqual(m.reveal(30), 1.0)

    def test_events_flare_the_core_make_ripples_and_light_the_grid_but_a_burst_is_rate_limited(self):
        m = self.motion(mode="idle"); self.run_for(m, 1)
        base = m.core_level()
        m.pulse(1.0)
        self.assertGreater(m.core_level(), base + 0.3)
        for _ in range(20):
            m.ripple("ok")
        self.assertEqual(len(m.ripples), 1)                                          # the 0.14 s gap
        self.assertTrue(m.waves)
        self.run_for(m, 4)
        self.assertEqual(m.ripples, [])                                              # they expire
        self.assertLessEqual(len(m.bolts), BOLT_MAX[0])

    def test_verified_sends_one_shockwave(self):
        m = self.motion(mode="working"); m.trigger_shock()
        seen = []
        for _ in range(60):
            m.advance(1 / 30); seen.append(m.shock)
        self.assertIsNone(m.shock)
        self.assertGreater(len([s for s in seen if s is not None]), 20)

    def test_detail_levels_cap_the_sparks_arcs_and_streaks(self):
        m = self.motion(mode="working"); self.run_for(m, 4)
        full = len(m.embers)
        m.set_level(3); self.run_for(m, 1)
        self.assertLessEqual(len(m.embers), LEVELS[3]); self.assertLessEqual(len(m.flow), FLOW_LEVELS[3]); self.assertLessEqual(len(m.bolts), BOLT_MAX[3])
        self.assertGreater(full, len(m.embers))
        m.set_level(99); self.assertEqual(m.level, 3); m.set_level(-5); self.assertEqual(m.level, 0)

    def test_a_poisoned_time_step_changes_nothing_and_a_long_stall_is_clamped(self):
        m = self.motion(mode="working"); self.run_for(m, 1)
        t = m.t
        for bad in (float("nan"), float("inf"), -1.0, 0.0):
            m.advance(bad)
        self.assertEqual(m.t, t)
        m.advance(30.0)                                                              # a laptop lid: one quarter second at most
        self.assertLessEqual(m.t - t, 0.26)
        for k, v in m.frame_vars().items():
            self.assertEqual(v, v, k)                                                # no NaN anywhere

    def test_the_same_seed_gives_the_same_sparks(self):
        a, b = self.motion(), self.motion()
        for m in (a, b):
            m.set_mode("working"); self.run_for(m, 3)
        self.assertEqual(a.embers, b.embers)

    def test_the_governor_lowers_detail_when_slow_and_restores_it_when_fast(self):
        q = Quality(budget_ms=30, window=10)
        changed = [q.record(80.0) for _ in range(10)]
        self.assertTrue(changed[-1]); self.assertEqual(q.level, 1)
        for _ in range(10 * 4):
            q.record(5.0)
        self.assertEqual(q.level, 0)


if __name__ == "__main__":
    unittest.main()


class DesignTools(unittest.TestCase):
    def run_cli(self, *args, home=None):
        from praxis import hudcli
        out = []
        env = {"PRAXIS_HOME": home or tempfile.mkdtemp()}
        with unittest.mock.patch.dict(os.environ, env):
            os.environ.pop("PRAXIS_HUD", None)
            rc = hudcli.run(*args, out=out.append)
        return rc, "\n".join(out)

    def test_validate_the_shipped_design_and_a_broken_one(self):
        rc, out = self.run_cli("validate")
        self.assertEqual(rc, 0); self.assertIn("OK", out)
        d = tempfile.mkdtemp(); bad = os.path.join(d, "bad.json")
        raw = json.loads(json.dumps(DEFAULT.raw)); raw["layers"][2]["opacity"] = "1 +"
        json.dump(raw, open(bad, "w"))
        rc, out = self.run_cli("validate", bad)
        self.assertEqual(rc, 1); self.assertIn("layers[2].opacity", out); self.assertIn("cannot be used", out)

    def test_export_copies_once_and_never_overwrites_your_edits(self):
        home = tempfile.mkdtemp()
        rc, out = self.run_cli("export", home=home)
        self.assertEqual(rc, 0)
        mine = os.path.join(home, "hud.json")
        self.assertTrue(os.path.isfile(mine))
        open(mine, "a").close()
        with open(mine, "w") as f:
            f.write('{"mine": true}')
        rc, out = self.run_cli("export", home=home)
        self.assertEqual(rc, 1); self.assertIn("not overwritten", out)
        self.assertEqual(open(mine).read(), '{"mine": true}')
        rc, out = self.run_cli("path", home=home)
        self.assertIn("present: it is used", out)

    def test_the_reference_covers_every_element_source_and_variable_and_the_committed_copy_is_current(self):
        from praxis import hudcli
        text = hudcli.docs()
        for name in S.ELEMENTS:
            self.assertIn(f"### `{name}`", text)
        for name in S.SOURCES:
            self.assertIn(f"`{name}`", text)
        for name in S.VARIABLES:
            self.assertIn(f"`{name}`", text)
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(here, "docs", "HUD-DESIGN.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), text, "docs/HUD-DESIGN.md is stale: run  python -m praxis hud docs > docs/HUD-DESIGN.md")
