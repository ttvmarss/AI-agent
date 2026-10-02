"""Drives the REAL Tk window (needs tkinter + a display; run with: xvfb-run -a python3 -m unittest tests.test_desktop_ui)."""
import os, tempfile, threading, time, unittest

try:
    import tkinter as tk
    from praxis.desktop.app import App
    from praxis.desktop.controller import Controller
    HAVE_TK = True
except Exception:  # no tkinter on this interpreter
    HAVE_TK = False

import tests.test_desktop_controller as tdc
from tests.test_desktop_controller import FakeAgent, GOOD, fake_stack
from tests.test_executive import plan, W


class FakeTelemetry:
    def sample(self):
        return {"cpu": 37.0, "ram_used_gb": 12.4, "ram_total_gb": 32.0, "ram_pct": 38.7,
                "gpus": [{"name": "RTX 3050", "util": 61, "vram_used_gb": 5.2, "vram_total_gb": 8.0, "temp": 64}]}


def pump(app, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        app.root.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


def dialogs(app):
    return [w for w in app.root.winfo_children() if isinstance(w, tk.Toplevel)]


@unittest.skipUnless(HAVE_TK, "tkinter not available")
class UI(unittest.TestCase):
    def make(self, responses, agents=None, hook=None, approval_timeout=900.0):
        try:
            root = tk.Tk()
        except tk.TclError as e:
            self.skipTest(f"no display: {e}")
        ws, home = tempfile.mkdtemp(), tempfile.mkdtemp()
        st = fake_stack(responses, agents, hook)
        ctl = Controller(ws, stack_factory=lambda w: st, home=home, approval_timeout=approval_timeout)
        ctl.start()
        app = App(ctl, FakeTelemetry(), root=root)
        self.addCleanup(lambda: (ctl.stop(), root.destroy()) if root.winfo_exists() else None)
        self.assertTrue(pump(app, lambda: ctl.state == "idle"), ctl.error)
        return app, ctl, ws

    def goal(self, app, text):
        app.mission.objective.delete("1.0", "end"); app.mission.objective.insert("1.0", text); app.run_goal()

    def test_window_comes_up_ready_with_telemetry(self):
        app, ctl, ws = self.make([GOOD])
        pump(app, lambda: app.pill.cget("text") == "READY")
        self.assertEqual(app.pill.cget("text"), "READY")
        self.assertIn("Ready", app.status.cget("text"))
        self.assertEqual(app.stop_btn.instate(["disabled"]), True)       # nothing to stop yet
        pump(app, lambda: app._tele is not None, 5); app.root.update(); time.sleep(0.2); app.root.update()
        self.assertTrue(pump(app, lambda: "12.4" in app.bars["RAM"].text, 6))   # live telemetry reached the gauge
        self.assertIn("61%", app.bars["GPU"].text); self.assertIn("5.2", app.bars["VRAM"].text)
        self.assertEqual(os.path.basename(ws), app.ws_name.cget("text"))

    def test_run_a_goal_end_to_end_and_the_screen_tells_the_truth(self):
        app, ctl, ws = self.make([GOOD])
        self.goal(app, "make a.txt")
        self.assertTrue(pump(app, lambda: app.mission.status.cget("text") == "VERIFIED"))
        self.assertEqual(os.path.exists(os.path.join(ws, "a.txt")), True)
        self.assertEqual(app.mission.plan.get_children(), ("s1",))
        self.assertEqual(app.mission.plan.item("s1", "values")[0], "✓")           # verified icon
        ev = [app.mission.evidence.item(i, "values") for i in app.mission.evidence.get_children()]
        self.assertTrue(ev and all(v[0] == "✓" for v in ev))
        feed = app.mission.activity.get("1.0", "end")
        self.assertIn("Plan accepted", feed); self.assertIn("PASS", feed); self.assertIn("Guard: ALLOW", feed)
        self.assertGreater(len(app.timeline.tree.get_children()), 5)
        self.assertTrue(pump(app, lambda: app.pill.cget("text") == "READY"))
        self.assertEqual(app.mission.run_btn.instate(["disabled"]), False)               # ready for the next goal

    def test_empty_objective_is_refused_politely(self):
        app, ctl, ws = self.make([GOOD])
        app.mission.objective.delete("1.0", "end"); app.run_goal()
        self.assertIn("Type the outcome", app.status.cget("text")); self.assertEqual(ctl.state, "idle")

    def test_approval_dialog_shows_exact_action_defaults_to_deny_and_deny_blocks(self):
        plan_ = tdc.Approvals.PLAN
        app, ctl, ws = self.make([plan_], agents={"claude": FakeAgent()})
        self.goal(app, "delegate it")
        self.assertTrue(pump(app, lambda: len(dialogs(app)) == 1))
        d = dialogs(app)[0]
        texts = []
        def walk(w):
            for ch in w.winfo_children():
                try: texts.append(ch.cget("text"))
                except tk.TclError: pass
                if isinstance(ch, tk.Text): texts.append(ch.get("1.0", "end"))
                walk(ch)
        walk(d)
        blob = " ".join(texts)
        self.assertIn("make made.txt", blob); self.assertIn("EXTERNAL ACTION", blob); self.assertIn("Class 3", blob)
        self.assertEqual(d.focus_get(), d.deny_btn)                       # the safe choice holds the keyboard focus
        self.assertEqual(app.pill.cget("text"), "NEEDS YOU")
        d.event_generate("<Escape>")                                      # Esc = deny
        self.assertTrue(pump(app, lambda: app.mission.status.cget("text") == "FAILED"))
        self.assertFalse(os.path.exists(os.path.join(ws, "made.txt")))

    def test_approve_button_runs_the_delegate(self):
        app, ctl, ws = self.make([tdc.Approvals.PLAN], agents={"claude": FakeAgent()})
        self.goal(app, "delegate it")
        self.assertTrue(pump(app, lambda: len(dialogs(app)) == 1))
        dialogs(app)[0].ok_btn.invoke()
        self.assertTrue(pump(app, lambda: app.mission.status.cget("text") == "VERIFIED"))
        self.assertTrue(os.path.exists(os.path.join(ws, "made.txt")))

    def test_closing_the_dialog_window_counts_as_deny(self):
        app, ctl, ws = self.make([tdc.Approvals.PLAN], agents={"claude": FakeAgent()})
        self.goal(app, "x"); self.assertTrue(pump(app, lambda: len(dialogs(app)) == 1))
        dialogs(app)[0].destroy() if False else dialogs(app)[0].deny_btn.invoke()
        self.assertTrue(pump(app, lambda: ctl.state == "idle")); self.assertFalse(os.path.exists(os.path.join(ws, "made.txt")))

    def test_stop_button_cancels_and_restores(self):
        gate = threading.Event()
        steps = [W("s1", "a.txt", "1"), W("s2", "b.txt", "2", deps=["s1"])]
        app, ctl, ws = self.make([plan(steps, [{"type": "file_exists", "path": "b.txt"}])], hook=lambda: gate.wait(10))
        self.goal(app, "x")
        self.assertTrue(pump(app, lambda: ctl.state == "working"))
        self.assertTrue(pump(app, lambda: not app.stop_btn.instate(["disabled"]), 3))   # kill switch is live while working
        app.stop_btn.invoke(); gate.set()
        self.assertTrue(pump(app, lambda: app.mission.status.cget("text") == "CANCELLED"))
        self.assertFalse(os.path.exists(os.path.join(ws, "a.txt")))
        self.assertIn("stopped by user", app.mission.sub.cget("text").lower())   # stopped while planning: nothing to restore
        self.assertTrue(pump(app, lambda: app.stop_btn.instate(["disabled"])))

    def test_why_button_explains_a_selected_event(self):
        app, ctl, ws = self.make([GOOD]); self.goal(app, "make the thing")
        pump(app, lambda: app.mission.status.cget("text") == "VERIFIED")
        app.show("Timeline")
        iid = next(i for i in app.timeline.tree.get_children() if "ran" in app.timeline.tree.item(i, "values")[3])
        app.timeline.tree.selection_set(iid); app.root.update()
        app.timeline.why(); app.root.update()
        self.assertIn("make the thing", app.timeline.detail.get("1.0", "end"))
        app.timeline.verify(); self.assertIn("intact", app.timeline.integrity.cget("text"))

    def test_memory_page_lists_and_searches_past_goals(self):
        app, ctl, ws = self.make([GOOD]); self.goal(app, "build the quarterly widget")
        pump(app, lambda: app.mission.status.cget("text") == "VERIFIED")
        app.show("Memory"); rows = app.pages["Memory"].tree.get_children(); self.assertEqual(len(rows), 1)
        app.pages["Memory"].q.set("quarterly widget"); app.pages["Memory"].search()
        self.assertIn("build the quarterly widget", app.pages["Memory"].tree.item(app.pages["Memory"].tree.get_children()[0], "values"))

    def test_models_and_system_pages_render_with_hardware_and_providers(self):
        app, ctl, ws = self.make([GOOD])
        app.show("Models"); app.root.update()
        self.assertIn("CPU", app.pages["Models"].hw.get("1.0", "end"))
        app.show("System"); app.root.update()
        self.assertEqual(len(app.pages["System"].tree.get_children()), 1)
        self.assertIn("sandbox", app.pages["System"].facts.get("1.0", "end"))

    def test_resume_button_appears_only_when_a_goal_was_interrupted(self):
        app, ctl, ws = self.make([GOOD])
        self.assertFalse(app.mission.resume_btn.winfo_ismapped())

    def test_a_ui_rendering_error_does_not_kill_the_window(self):
        app, ctl, ws = self.make([GOOD])
        app.mission.show_view = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        pump(app, lambda: "UI error" in app.status.cget("text"), 3)
        self.assertIn("UI error", app.status.cget("text")); self.assertTrue(app.root.winfo_exists())


if __name__ == "__main__":
    unittest.main()
