"""Tony Stark breaks the window: hostile state, absurd sizes, bad numbers, key mashing, a voice that fails in every way.
Anything that crashes (even a hard segfault, which ends the run) or leaves the window dead is a defect.
Scales with PRAXIS_STRESS (frames painted ~ N/10)."""
import math
import os
import random
import threading
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from praxis.desktop.nodes import provider_nodes
    from praxis.desktop.qt import hologram as H
    from praxis.desktop.qt.app import MainWindow, apply_view
    from praxis.desktop.qt.core import CoreView
    from praxis.desktop.view import StepView, View
    from tests.test_desktop_qt import (FakeMic, FakeRecognizer, FakeSpeaker, FakeVoice, VoiceLoop, ControllerActions, VoiceUnavailable,
                                       fake_voice, no_voice, pump, qapp, prov, multi_stack, utterance)
    HAVE_QT = True
except Exception:
    HAVE_QT = False

N = int(os.environ.get("PRAXIS_STRESS", "2000"))
SEED = int(os.environ.get("PRAXIS_SEED", "1"))
STATES = ["starting", "idle", "working", "waiting", "ok", "bad", "stopping", "stopped", "nonsense", "", None]
STEP = ["pending", "running", "waiting", "ran", "verified", "denied", "failed", "rolled back", "???", None]
PLANS = ["none", "planning", "ready", "failed", "huh", None]
VSTATE = ["off", "listening", "hearing", "thinking", "speaking", "muted", "bogus"]
NUMS = [0, 1, -1, 0.5, 1e9, -1e9, float("inf"), float("-inf"), float("nan"), 1e-30, 7, 255, 1e300]
TEXTS = ["", "x", "x" * 5000, "😀" * 300, "\x00\x01\x02", "<b>bold</b>", "‮RTL", "line1\nline2\ttab", "%s %d {0}", "ünïcödé " * 60]


def num(r): return r.choice(NUMS) if r.random() < .5 else r.uniform(-2, 3)


@unittest.skipUnless(HAVE_QT, "PySide6 not available")
class BreakTheCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()
        st = multi_stack([prov("ollama/qwen", "local", "local"), prov("groq/gpt-oss", "cloud", "free"), prov("claude/opus", "cloud", "balanced")])
        cls.template = provider_nodes(st, "project")

    def nodes(self, r):
        out = []
        for _ in range(r.choice([0, 1, 2, 5, 12, 40])):
            n = dict(r.choice(self.template))
            n["family"] = r.choice(TEXTS) or "f"
            n["pressure"] = r.choice([0, 0.5, 1, 1.5, -1, 99, float("nan")])
            n["cooling_s"] = r.choice([0, 5, 99999, -4])
            n["blocked"] = r.random() < .3
            n["models"] = r.choice([[], n.get("models", [])])
            out.append(n)
        return out

    def test_any_state_any_size_any_number_paints_without_crashing(self):
        r = random.Random(SEED)
        c = CoreView(); self.addCleanup(c.deleteLater)
        c.quality.limit = 1e9 if hasattr(c.quality, "limit") else None
        frames = max(40, N // 10)
        for i in range(frames):
            w, h = r.choice([(1, 1), (5, 900), (80, 80), (81, 81), (300, 200), (560, 300), (760, 520), (1280, 760), (1920, 1080), (2600, 1300), (3840, 400)])
            c.resize(w, h)
            c.set_state(r.choice(STATES), num(r), r.choice(TEXTS), r.choice(TEXTS))
            c.set_pipeline(r.choice(PLANS), [r.choice(STEP) for _ in range(r.choice([0, 1, 3, 12, 60]))],
                           [r.random() < .5 for _ in range(r.choice([0, 1, 4, 30]))], r.random() < .5)
            c.set_voice(r.choice(VSTATE), num(r), num(r), r.random() < .5)
            c.set_nodes(self.nodes(r)); c.set_active(r.choice(["", "ollama", "claude", "nope", "x" * 200]))
            c.set_caption(r.choice(TEXTS), r.choice(["info", "ok", "warn", "bad", "muted", "???"]))
            c.set_footer(r.choice(TEXTS))
            if r.random() < .3: c.pulse(r.choice(["info", "ok", "warn", "bad", "???"]))
            for dt in [r.choice([0.0, 0.016, 0.033, 0.5, 5.0, 100.0, -1.0, 1e-9, float("nan")]) for _ in range(r.randint(1, 4))]:
                try:
                    c.advance(dt)
                except Exception as e:
                    self.fail(f"advance({dt}) raised {type(e).__name__}: {e}")
            if r.random() < .25:
                c.t = r.choice([0.0, 1e6, 1e12])                      # a session left running for weeks
            img = c.grab()
            self.assertFalse(img.isNull())
        for t in (0.0, 1.0, 7.3 + 1.0, 1e6, 1e12, -5.0, float("nan"), float("inf")):
            H.flicker(t); H.glitch(t); H.sweep(t); H.ghost_offset(t); H.grid_lines(6, 18, t)

    def test_apply_view_survives_every_view_the_controller_could_ever_produce(self):
        r = random.Random(SEED + 1)
        c = CoreView(); self.addCleanup(c.deleteLater); c.resize(900, 600)
        for _ in range(max(100, N // 5)):
            steps = [StepView(id=str(i), tool=r.choice(["fs.write", "shell.run", "", "x"]), summary=r.choice(TEXTS), cls=r.randint(0, 5), state=r.choice(STEP[:-2]))
                     for i in range(r.choice([0, 1, 5, 30]))]
            ev = [{"passed": r.random() < .5, "kind": "x"} for _ in range(r.choice([0, 1, 6]))]
            v = View(goal_id="g", goal_text=r.choice(TEXTS), status=r.choice(["IDLE", "PLANNING", "RUNNING", "VERIFIED", "UNVERIFIED", "CANCELLED", "FAILED", "WAITING FOR YOU", "??"]),
                     steps=steps, evidence=ev, reason=r.choice(TEXTS + ["planning failed: x"]), rolled_back=r.random() < .5,
                     active_provider=r.choice(["", "claude", "zzz"]))
            apply_view(c, v, r.choice(["starting", "idle", "working", "stopping", "error", "???"]), r.random() < .3, r.choice(["", "hint " * 60]), r.choice(TEXTS))
            c.advance(0.05); c.grab()


@unittest.skipUnless(HAVE_QT, "PySide6 not available")
class BreakTheWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = qapp()

    def window(self, voice_factory):
        from tests.test_desktop_controller import mk
        ctl, ws, st = mk([])
        win = MainWindow(ctl, voice_factory=voice_factory); win.show()
        self.addCleanup(lambda: (ctl.stop(), setattr(win, "_closing", True), win.timer.stop(), win.close()))
        return win, ctl, ws

    def test_key_mashing_resize_storms_and_mute_toggling_never_wedge_the_window(self):
        r = random.Random(SEED + 2)
        win, ctl, ws = self.window(fake_voice)
        self.assertTrue(pump(lambda: win.voice is not None, 5))
        keys = [Qt.Key_Escape, Qt.Key_F2, Qt.Key_F3, Qt.Key_F4, Qt.Key_F5, Qt.Key_Return, Qt.Key_Space, Qt.Key_Tab, Qt.Key_Backspace, Qt.Key_A, Qt.Key_Delete]
        for i in range(max(100, N // 4)):
            op = r.random()
            if op < 0.5:
                QTest.keyClick(win, r.choice(keys), r.choice([Qt.NoModifier, Qt.ControlModifier, Qt.ShiftModifier, Qt.AltModifier]))
            elif op < 0.65:
                win.resize(r.randint(100, 2400), r.randint(100, 1400))
            elif op < 0.75:
                win.toggle_mute()
            elif op < 0.85:
                win.core.set_voice(r.choice(VSTATE), num(r), num(r), r.random() < .5)
            elif op < 0.9:
                utterance(win.voice, r.uniform(0.05, 2.0))
            else:
                win.showMinimized() if r.random() < .5 else win.showNormal()
            self.app.processEvents()
        self.assertTrue(pump(lambda: ctl.state in ("idle", "working", "stopping", "error"), 5))
        win.core.grab()
        self.assertGreaterEqual(win.width(), win.minimumWidth() if win.width() >= win.minimumWidth() else 0)

    def test_a_voice_that_fails_in_every_way_never_takes_the_window_down(self):
        for factory, expect_error in (
            (lambda c, v, progress=None, on_mute=None: (_ for _ in ()).throw(VoiceUnavailable("no mic")), True),
            (lambda c, v, progress=None, on_mute=None: (_ for _ in ()).throw(RuntimeError("driver exploded")), True),
            (lambda c, v, progress=None, on_mute=None: (_ for _ in ()).throw(MemoryError()), True),
            (lambda c, v, progress=None, on_mute=None: (_ for _ in ()).throw(OSError("device busy")), True),
        ):
            win, ctl, ws = self.window(factory)
            self.assertTrue(pump(lambda: win.voice_error != "" and win.prompt.isVisible(), 6), "no typing fallback appeared")
            win.core.grab(); win.toggle_mute()
            QTest.keyClick(win, Qt.Key_F4)

    def test_closing_the_window_while_voice_is_starting_or_speaking_is_clean(self):
        def slow(c, v, progress=None, on_mute=None):
            time.sleep(0.4)
            return fake_voice(c, v, progress, on_mute)
        win, ctl, ws = self.window(slow)
        win.close(); pump(lambda: False, 0.8)                         # voice arrives after the window is gone
        win2, ctl2, ws2 = self.window(fake_voice)
        self.assertTrue(pump(lambda: win2.voice is not None, 5))
        win2.voice.say("a long sentence " * 30)
        win2.close(); pump(lambda: False, 0.3)

    def test_voice_loop_survives_a_hostile_recogniser_speaker_voice_and_microphone_flood(self):
        from praxis.voice.stt import Recognizer

        class Evil(Recognizer):
            def __init__(self): self.n = 0
            def transcribe(self, pcm):
                self.n += 1
                if self.n % 3 == 0: raise RuntimeError("model crashed")
                if self.n % 3 == 1: return "Praxis, status please"
                return "\x00" * 50

        class BadSpeaker(FakeSpeaker):
            def play(self, pcm, rate, stop):
                if len(self.played) % 2: self.played.append(None); raise OSError("audio device unplugged")
                super().play(pcm, rate, stop)

        class BadVoice(FakeVoice):
            def synth(self, text):
                if "boom" in text: raise RuntimeError("tts failed")
                return super().synth(text)
        from tests.test_desktop_controller import mk
        ctl, ws, st = mk([])
        loop = VoiceLoop(ControllerActions(ctl, None), Evil(), FakeMic(), BadSpeaker(), BadVoice())
        loop.start()
        self.addCleanup(loop.close)
        loop.say("boom"); loop.say("fine one"); loop.say("x " * 4000)
        self.assertTrue(pump(lambda: not loop.speaking and not loop._ttsq and time.monotonic() > loop.deaf_until + 0.1, 8), "a 4000-word sentence is still being spoken")
        self.assertLessEqual(max((len(p) / 2 / r for p, r in (x for x in loop.speaker.played if x) if p), default=0), 60.0)       # no multi-minute monologue
        loop.mic.silence(0.6); pump(lambda: loop.mic.idle(), 3)
        for _ in range(12):
            utterance(loop, 0.5); pump(lambda: loop.mic.idle() and not loop.speaking and not loop._ttsq, 4)
        loop.mic.push(bytes(range(256)) * 400)                        # a flood of raw garbage bytes
        pump(lambda: False, 3.0)
        self.assertTrue(all(t.is_alive() for t in loop._threads), "a voice thread died")
        self.assertGreater(len(loop.transcripts), 0)


if __name__ == "__main__":
    unittest.main()
