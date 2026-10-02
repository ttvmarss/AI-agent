"""Tony Stark's breaking-it suite. Seeded, randomised, adversarial. Each test states an invariant that must hold for EVERY input;
a single violation is a real defect. Counts scale with PRAXIS_STRESS (default is quick; the campaign runs millions)."""
import array
import math
import os
import random
import string
import threading
import time
import types
import unittest

from praxis.voice import audio, narrator, wake
from praxis.voice.conductor import Conductor, PROMPT_DELAY

N = int(os.environ.get("PRAXIS_STRESS", "2000"))
SEED = int(os.environ.get("PRAXIS_SEED", "1"))

WORDS = ["praxis", "hey", "yes", "no", "approve", "deny", "stop", "mute", "status", "create", "file", "delete", "run", "shell", "private",
         "open", "frugal", "quality", "resume", "please", "the", "a", "x.txt", "calc.py", "rm", "-rf", "/", "okay", "go", "ahead", "prove",
         "thank", "you", "don't", "not", "never", "mind", "balanced", "project", "listening", "sleep", "cancel", "do", "it"]
JUNK = "\x00\x07‮​́😀🧨“”‘’…—\t\r\n{}[]()<>\\|`$%^&*~"


def rnd_text(r):
    kind = r.random()
    if kind < 0.45:
        return " ".join(r.choice(WORDS) for _ in range(r.randint(0, 9)))
    if kind < 0.6:
        return "".join(r.choice(string.printable + JUNK) for _ in range(r.randint(0, 80)))
    if kind < 0.7:
        return "praxis, " + " ".join(r.choice(WORDS) for _ in range(r.randint(0, 5))) + r.choice(["", ".", "?", "!", "..."])
    if kind < 0.75:
        return r.choice(WORDS) * r.randint(1, 4000)                       # absurdly long
    if kind < 0.8:
        return "".join(r.choice(JUNK) for _ in range(r.randint(0, 30)))
    if kind < 0.9:
        return r.choice(["Hey Praxis, ", "PRAXIS ", "praxis. ", "Prax, ", "Brexis, ", "ok praxis "]) + " ".join(r.choice(WORDS) for _ in range(r.randint(0, 6)))
    return r.choice(["", " ", None, "   \n  ", "."])


class Rec:
    def __init__(self):
        self._state, self.pending_list, self.calls = "idle", [], []

    def pending(self): return list(self.pending_list)
    def state(self): return self._state
    def submit(self, t): self.calls.append(("submit", t)); return True
    def stop(self): self.calls.append(("stop",))
    def respond(self, rid, ok): self.calls.append(("respond", rid, ok)); self.pending_list = [p for p in self.pending_list if p.id != rid]
    def set_data(self, d): self.calls.append(("data", d))
    def set_frugality(self, k): self.calls.append(("frugal", k))
    def resume(self): self.calls.append(("resume",)); return False
    def mute(self): self.calls.append(("mute",))
    def status_text(self): return "STATUS"


class Parsing(unittest.TestCase):
    def test_nothing_the_recogniser_can_emit_crashes_the_parser(self):
        r = random.Random(SEED)
        for _ in range(N * 5):
            t = rnd_text(r)
            wake.normalize(t); h, rest = wake.split_wake(t); self.assertIsInstance(rest, str)
            for approving in (False, True):
                for risky in (False, True):
                    it = wake.parse(rest, busy=r.random() < .5, approving=approving, risky=risky)
                    self.assertIsInstance(it.kind, str)
                    if approving:                    # while an approval is pending NOTHING can become a goal
                        self.assertNotEqual(it.kind, "goal", repr(t))
                    if approving and risky:          # a risky approval needs the literal approve-word, never a bare yes
                        if it.kind == "approve":
                            self.assertRegex(wake.normalize(rest), r"(approve|prove|prue)", repr(t))

    def test_a_goal_never_carries_the_wake_word_or_exceeds_what_was_said(self):
        r = random.Random(SEED + 1)
        for _ in range(N * 3):
            t = "praxis " + " ".join(r.choice(WORDS) for _ in range(r.randint(1, 8)))
            h, rest = wake.split_wake(t)
            self.assertTrue(h)
            self.assertLessEqual(len(rest), len(t)); self.assertTrue(t.endswith(rest))        # the goal is the tail of what was said, unaltered


class ConductorChaos(unittest.TestCase):
    def run_one(self, r):
        a, said, t = Rec(), [], [1000.0]
        opn = r.random() < 0.5                                  # half the conversations run in open mode (no name needed)
        c = Conductor(a, lambda text, urgent=False: said.append(text), clock=lambda: t[0], wake_required=not opn)
        heard_wake_for = {}
        for step in range(r.randint(5, 60)):
            t[0] += r.choice([0, 0.01, 0.5, 1, 3, 9, 11, 30, 61, 500])
            op = r.random()
            if op < 0.15 and len(a.pending_list) < 3:
                a.pending_list.append(types.SimpleNamespace(id=f"r{step}", cls=r.choice([1, 2, 3, 4, 5]), tool=r.choice(["shell.run", "agent.delegate", "plan.replan", "fs.write", "x"]),
                                                            args=r.choice([{}, {"cmd": "rm -rf /"}, {"task": "t" * 500}, None])))
            elif op < 0.25:
                a._state = r.choice(["idle", "working", "stopping", "weird", None])
            elif op < 0.35:
                c.tick()
            elif op < 0.4:
                events = [types.SimpleNamespace(type=r.choice(["plan.accepted", "goal.report", "guard.decision", "escalation", "plan.rejected", "x"]),
                                                payload=r.choice([{}, None, {"status": "VERIFIED", "evidence": [{"passed": True}, None]}, {"plan": None}, {"reason": "x" * 999}]),
                                                id=step) for _ in range(r.randint(0, 4))]
                c.on_events(events)
            else:
                text = rnd_text(r)
                before = len(a.calls)
                pend = a.pending()
                heard = wake.split_wake(text)[0] if isinstance(text, str) else False
                attentive = t[0] < c.attentive_until
                c.hear(text)
                new = a.calls[before:]
                for call in new:
                    if call[0] == "submit":                  # a goal only ever starts from the wake word or the short follow-up window
                        self.assertTrue(heard or attentive or opn, repr(text))
                        self.assertFalse(pend, "a goal started while an approval was pending")
                    if call[0] == "respond" and call[2]:     # approvals: risky ones only on the literal word; everything else on yes/approve
                        req = next(p for p in pend if p.id == call[1])
                        n = wake.normalize(text)
                        self.assertTrue(heard, f"approved without its name: {text!r}")           # in every mode
                        if req.cls >= 4:
                            self.assertRegex(n, r"(approve|prove|prue)", repr(text))
                        else:
                            self.assertRegex(n, r"(approve|prove|prue|yes|yeah|yep|yup|sure|go ahead|do it|okay|ok|proceed|confirm)", repr(text))
        c.tick()
        return a, said

    def test_random_conversations_never_crash_and_never_violate_the_rules(self):
        for i in range(N // 4):
            self.run_one(random.Random(SEED * 100000 + i))

    def test_ambient_speech_without_the_wake_word_can_not_approve_a_risky_action(self):
        # Break found by this campaign: the TV says "approve" and a Class 4 action runs. Risky approvals must carry the wake word.
        for phrase in ("approve", "yes approve", "I approve", "approved", "okay approve"):
            a, said, t = Rec(), [], [10.0]
            c = Conductor(a, lambda text, urgent=False: said.append(text), clock=lambda: t[0])
            a.pending_list = [types.SimpleNamespace(id="r1", cls=4, tool="shell.run", args={"cmd": "rm -rf ~"})]
            c.tick(); t[0] += 1; c.tick()
            c.hear(phrase)
            self.assertNotIn(("respond", "r1", True), a.calls, phrase)
            c.hear("praxis " + phrase)
            self.assertIn(("respond", "r1", True), a.calls, phrase)


class ConversationChaos(unittest.TestCase):
    def test_classifier_smalltalk_and_tidy_are_total_and_chat_never_acts(self):
        from praxis.voice import chat as C
        r = random.Random(SEED + 7)
        for _ in range(N * 2):
            t = rnd_text(r)
            self.assertIn(C.classify(t), ("task", "chat"))
            st = C.smalltalk(t)
            self.assertTrue(st is None or (isinstance(st, str) and 0 < len(st) < 200))
            out = C.tidy(r.choice([t, "x" * 5000, None, "```code```", "sk-ABCDEFGH12345678 " * 30]))
            self.assertLessEqual(len(out), 425); self.assertNotIn("sk-ABCDEFGH", out)

    def test_random_conversations_with_a_flaky_model_never_start_goals_or_answer_approvals(self):
        from praxis.voice.chat import Chat, classify
        r = random.Random(SEED + 8)
        for i in range(max(20, N // 40)):
            calls = {"n": 0}
            def ask(m):
                calls["n"] += 1
                x = r.random()
                if x < .25: raise RuntimeError("no eligible provider")
                if x < .4: raise OSError("net")
                if x < .5: return None
                if x < .6: return "word " * 3000
                return "Fine."
            a, said, t = Rec(), [], [1000.0]
            c = Conductor(a, lambda text, urgent=False: said.append(text), clock=lambda: t[0], chat=Chat(ask))
            for step in range(r.randint(5, 25)):
                t[0] += r.choice([0.5, 3, 12, 40])
                if r.random() < .15 and not a.pending_list:
                    a.pending_list.append(types.SimpleNamespace(id=f"r{step}", cls=r.choice([2, 4]), tool="shell.run", args={"cmd": "x"}))
                text = r.choice(["Praxis, how are you", "Praxis, explain recursion", "what time is it", "Praxis, " + str(rnd_text(r)), rnd_text(r), "Hello Praxis", "approve", "Praxis, approve"])
                before = len(a.calls); pend = a.pending()
                c.hear(text)
                for call in a.calls[before:]:
                    if call[0] == "submit":
                        self.assertFalse(pend); self.assertEqual(classify(call[1]), "task", call)       # only tasks are ever submitted
            time.sleep(0.05)
            for line in said:
                self.assertLess(len(line), 450)


class Audio(unittest.TestCase):
    def feed(self, seg, pcm):
        out = []
        for i in range(0, len(pcm), 1000):                   # odd, uneven chunk sizes
            out += seg.feed(pcm[i:i + 1000])
        return out

    def test_garbage_audio_never_crashes_and_utterances_are_bounded(self):
        r = random.Random(SEED + 2)
        for _ in range(max(20, N // 40)):
            seg = audio.Segmenter()
            kind = r.randint(0, 5)
            n = r.randint(0, 16000 * 20)
            if kind == 0:
                pcm = bytes(r.getrandbits(8) for _ in range(min(n, 60000)))
            elif kind == 1:
                pcm = array.array("h", [32767 if (i // r.randint(1, 50)) % 2 else -32768 for i in range(min(n, 80000))]).tobytes()   # clipped square
            elif kind == 2:
                pcm = array.array("h", [r.choice([-32768, 32767]) for _ in range(min(n, 80000))]).tobytes()
            elif kind == 3:
                pcm = b"\x00" * min(n, 200000)
            elif kind == 4:
                pcm = array.array("h", [12000] * min(n, 200000)).tobytes()                 # a constant DC offset
            else:
                pcm = array.array("h", [int(30000 * math.sin(i * 0.05)) for i in range(min(n, 400000))]).tobytes()   # constant loud tone
            pcm = pcm[: len(pcm) // 2 * 2]
            out = self.feed(seg, pcm)
            for u in out:
                self.assertLessEqual(len(u) / 2 / 16000, 14.0 + 1.0)
        audio.rms(b""); audio.rms(b"\x01"); audio.envelope(b"", 16000); audio.to_mono16k(b"\x01\x02\x03", 44100, 2, "float32")

    def test_endless_loud_noise_is_not_mistaken_for_an_endless_sentence(self):
        # Break found by this campaign: a fan, music or a vacuum cleaner starts and never stops. It must stop being "speech".
        seg = audio.Segmenter()
        quiet = array.array("h", [int(100 * math.sin(i)) for i in range(16000)]).tobytes()
        seg.feed(quiet)
        loud = array.array("h", [int(9000 * math.sin(i * 0.31) + 3000 * math.sin(i * 1.7)) for i in range(16000 * 70)]).tobytes()
        got = self.feed(seg, loud)
        self.assertLessEqual(len(got), 1, f"{len(got)} utterances were cut out of constant noise")


class SpeechBounds(unittest.TestCase):
    def test_a_backlog_and_a_monologue_are_both_bounded(self):
        from praxis.voice import loop as L
        from praxis.voice.devices import FakeMic, FakeSpeaker
        from praxis.voice.stt import FakeRecognizer
        from praxis.voice.tts import FakeVoice
        gate = threading.Event()

        class Slow(FakeVoice):
            def synth(self, text):
                gate.wait(5); return super().synth(text)
        lp = L.VoiceLoop(Rec(), FakeRecognizer(), FakeMic(), FakeSpeaker(), Slow()); lp.start()
        try:
            for i in range(40):
                lp.say(f"sentence number {i}")
            time.sleep(0.2)
            self.assertLessEqual(len(lp._ttsq), L.MAX_QUEUED)
            self.assertIn("sentence number 39", lp._ttsq)                       # the newest survive, the stale ones are dropped
            lp.say("word " * 5000)
            self.assertLessEqual(max(len(t) for t in lp._ttsq), L.MAX_SPOKEN + 3)
            lp.say(None); lp.say("   "); lp.say(12345)                          # not text: ignored, not a crash
        finally:
            gate.set(); lp.close()


class DeviceFailures(unittest.TestCase):
    def test_an_unplugged_microphone_is_noticed_shown_and_recovered(self):
        from praxis.voice import loop as L
        from praxis.voice.devices import FakeMic, FakeSpeaker
        from praxis.voice.stt import FakeRecognizer
        from praxis.voice.tts import FakeVoice

        class Unplugged(FakeMic):
            streams = True
            def __init__(self): super().__init__(); self.starts = 0; self.plugged = True
            def start(self, on_chunk):
                self.starts += 1; self.cb = on_chunk; self._run = True
                if self._t is None: self._t = threading.Thread(target=self._beat, daemon=True); self._t.start()
            def _beat(self):
                while True:
                    if self._run and self.plugged and self.cb: self.cb(b"\x00\x00" * 480)
                    time.sleep(0.03)
            def stop(self): pass
        lp = L.VoiceLoop(Rec(), FakeRecognizer(), Unplugged(), FakeSpeaker(), FakeVoice()); lp.start()
        try:
            time.sleep(0.6); self.assertEqual(lp.state, "listening")
            lp.mic.plugged = False
            end = time.time() + 6
            while lp.state != "offline" and time.time() < end: time.sleep(0.1)
            self.assertEqual(lp.state, "offline"); self.assertIn("microphone", lp.last_error)
            end = time.time() + 7
            while lp.mic.starts < 2 and time.time() < end: time.sleep(0.1)
            self.assertGreaterEqual(lp.mic.starts, 2, "it never tried to bring the microphone back")
            lp.mic.plugged = True
            end = time.time() + 5
            while lp.state != "listening" and time.time() < end: time.sleep(0.1)
            self.assertEqual(lp.state, "listening"); self.assertEqual(lp.last_error, "")
            lp.set_muted(True); lp.mic.plugged = False; time.sleep(3.6)
            self.assertEqual(lp.state, "muted")                                   # muted is muted, not 'offline'
        finally:
            lp.close()

    def test_closing_while_it_is_speaking_does_not_throw_in_a_background_thread(self):
        # Found while rebuilding the screen: shutting the synthesiser down mid-sentence raised "cannot schedule new futures after shutdown".
        from praxis.voice import loop as L
        from praxis.voice.devices import FakeMic, FakeSpeaker
        from praxis.voice.stt import FakeRecognizer
        from praxis.voice.tts import FakeVoice
        errors = []
        old = threading.excepthook
        threading.excepthook = lambda a: errors.append(a)
        try:
            for _ in range(5):
                lp = L.VoiceLoop(Rec(), FakeRecognizer(), FakeMic(), FakeSpeaker(realtime=True), FakeVoice(ms_per_word=30)); lp.start()
                lp.say("First sentence is here. Second sentence follows it. Third one comes after that. And a fourth for luck.")
                time.sleep(0.15); lp.close(); time.sleep(0.4)
        finally:
            threading.excepthook = old
        self.assertEqual([e.exc_value for e in errors], [])

    def test_when_the_speaker_or_voice_fails_the_words_are_kept_for_the_screen(self):
        from praxis.voice import loop as L
        from praxis.voice.devices import FakeMic, FakeSpeaker
        from praxis.voice.stt import FakeRecognizer
        from praxis.voice.tts import FakeVoice

        class Dead(FakeSpeaker):
            def play(self, pcm, rate, stop): raise OSError("no audio device")
        lp = L.VoiceLoop(Rec(), FakeRecognizer(), FakeMic(), Dead(), FakeVoice()); lp.start()
        try:
            lp.say("Done. 2 checks passed.")
            end = time.time() + 3
            while not lp.unspoken and time.time() < end: time.sleep(0.05)
            self.assertEqual(lp.unspoken, "Done. 2 checks passed."); self.assertIn("playback failed", lp.last_error)
            self.assertTrue(all(t.is_alive() for t in lp._threads))
        finally:
            lp.close()


class Narration(unittest.TestCase):
    def test_no_event_shape_crashes_the_narrator_or_leaks_a_secret(self):
        r = random.Random(SEED + 3)
        leak = "sk-ABCDEFGH12345678"
        payloads = [None, {}, {"plan": None}, {"plan": {"steps": None}}, {"status": None}, {"status": "FAILED", "reason": leak * 5},
                    {"status": "VERIFIED", "evidence": [None, {}, {"passed": 1}]}, {"error": 5}, {"reason": ["a"]}, {"evidence": "x"}]
        for _ in range(N):
            et = r.choice(["plan.accepted", "goal.report", "guard.decision", "escalation", "plan.rejected", "model.try", "", None])
            p = r.choice(payloads)
            try:
                s, u = narrator.for_event(et, p if p is not None else {})
            except Exception as e:
                if p is None:
                    continue
                if isinstance(p, dict):
                    self.fail(f"{et} {p!r} -> {type(e).__name__}: {e}")
                continue
            if s:
                self.assertNotIn(leak, s)
                self.assertLess(len(s), 400)
        for req in (types.SimpleNamespace(tool="shell.run", args=None, cls=4), types.SimpleNamespace(tool=None, args={}, cls=1),
                    types.SimpleNamespace(tool="shell.run", args={"cmd": f"curl -H 'api_key={leak}' x" * 50}, cls=5)):
            s = narrator.approval_prompt(req); self.assertNotIn(leak, s); self.assertLess(len(s), 500)


if __name__ == "__main__":
    unittest.main()
