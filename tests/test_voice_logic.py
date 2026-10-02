"""The voice logic is pure Python: audio, VAD, wake word, intents, narration and the conductor's safety rules."""
import array, math, os, random, tempfile, types, unittest

from praxis.voice import audio, narrator, wake
from praxis.voice.audio import RATE, Segmenter
from praxis.voice.conductor import Conductor
from praxis.voice.wake import Intent, parse, split_wake


def tone(seconds, level=0.3, hz=220, rate=RATE):
    n = int(seconds * rate)
    return array.array("h", (int(32767 * level * math.sin(2 * math.pi * hz * i / rate)) for i in range(n))).tobytes()


def quiet(seconds, level=0.0, seed=1):
    r = random.Random(seed)
    return array.array("h", (int(32767 * level * r.uniform(-1, 1)) for _ in range(int(seconds * RATE)))).tobytes()


class Audio(unittest.TestCase):
    def test_level(self):
        self.assertEqual(audio.rms(b""), 0.0); self.assertEqual(audio.rms(quiet(0.1)), 0.0)
        self.assertAlmostEqual(audio.rms(tone(0.2, 1.0)), 1 / math.sqrt(2), places=2)

    def test_conversion_to_16k_mono(self):
        f = array.array("f", [0.5, -0.5] * 4800)                                     # 48 kHz stereo float: 0.05 s
        out = array.array("h"); out.frombytes(audio.to_mono16k(f.tobytes(), 48000, 2, "float32"))
        self.assertAlmostEqual(len(out) / RATE, 0.1, delta=0.002)
        self.assertTrue(all(abs(x) < 400 for x in out))                              # +0.5 and -0.5 average to silence
        self.assertEqual(audio.to_mono16k(b"", 44100, 1), b"")

    def test_resample_keeps_duration_and_shape(self):
        a = array.array("h", [0, 1000, 0, -1000] * 441)
        out = audio.resample(a, 44100, 16000)
        self.assertAlmostEqual(len(out) / 16000, len(a) / 44100, delta=0.002)

    def test_wav_round_trip_and_envelope(self):
        pcm = tone(0.5, 0.4)
        path = os.path.join(tempfile.mkdtemp(), "x.wav"); audio.write_wav(path, pcm)
        self.assertEqual(audio.read_wav(path), pcm)
        env = audio.envelope(tone(0.3, 0.5) + quiet(0.3), RATE)
        self.assertAlmostEqual(max(env), 1.0); self.assertGreater(env[2], 0.9); self.assertLess(env[-1], 0.05)


class VAD(unittest.TestCase):
    def run_seg(self, pcm, chunk=None, **kw):
        s, out = Segmenter(**kw), []
        if chunk:
            for i in range(0, len(pcm), chunk):
                out += s.feed(pcm[i:i + chunk])
        else:
            out = s.feed(pcm)
        return out

    def test_silence_makes_nothing_and_speech_makes_one_utterance(self):
        self.assertEqual(self.run_seg(quiet(3.0, 0.002)), [])
        out = self.run_seg(quiet(1.0, 0.002) + tone(1.0) + quiet(1.5, 0.002))
        self.assertEqual(len(out), 1)
        self.assertTrue(1.0 < len(out[0]) / 2 / RATE < 2.3)                           # the speech plus pre-roll and hangover

    def test_a_click_is_not_speech_but_a_short_word_is(self):
        self.assertEqual(self.run_seg(quiet(1.0) + tone(0.03, 0.9) + quiet(1.5)), [])
        self.assertEqual(len(self.run_seg(quiet(1.0) + tone(0.4) + quiet(1.5))), 1)

    def test_pauses_inside_a_sentence_do_not_split_it_but_real_gaps_do(self):
        one = self.run_seg(quiet(0.5) + tone(0.6) + quiet(0.3) + tone(0.6) + quiet(1.5))
        self.assertEqual(len(one), 1)
        two = self.run_seg(quiet(0.5) + tone(0.6) + quiet(1.2) + tone(0.6) + quiet(1.5))
        self.assertEqual(len(two), 2)

    def test_the_noise_floor_adapts_to_a_noisy_room_and_does_not_chatter_on_constant_noise(self):
        self.assertEqual(self.run_seg(quiet(6.0, 0.03)), [])                          # a fan: never speech
        out = self.run_seg(quiet(3.0, 0.03) + tone(0.8, 0.4) + quiet(3.0, 0.03))
        self.assertEqual(len(out), 1)

    def test_it_is_independent_of_how_the_audio_arrives(self):
        pcm = quiet(1.0, 0.002) + tone(0.8) + quiet(1.0, 0.002) + tone(0.8) + quiet(1.5, 0.002)
        whole = self.run_seg(pcm)
        for chunk in (7, 480, 961, 4000):
            self.assertEqual(self.run_seg(pcm, chunk), whole, chunk)

    def test_very_long_speech_is_cut_at_the_maximum(self):
        out = self.run_seg(quiet(0.5) + tone(20.0) + quiet(1.5), max_ms=5000)
        self.assertGreaterEqual(len(out), 3); self.assertTrue(all(len(u) / 2 / RATE <= 5.2 for u in out))

    def test_level_and_state_are_exposed(self):
        s = Segmenter(); s.feed(quiet(0.5)); self.assertFalse(s.in_speech)
        s.feed(tone(0.5)); self.assertTrue(s.in_speech); self.assertGreater(s.level, 0.1)
        s.reset(); self.assertFalse(s.in_speech)


class WakeWord(unittest.TestCase):
    def test_the_wake_word_is_found_at_the_start_and_removed(self):
        for text, rest in (("Praxis, fix the tests", "fix the tests"), ("Hey Praxis fix the tests.", "fix the tests."),
                           ("okay praxis stop", "stop"), ("PRAXIS", ""), ("Prax is what's the status", "what's the status"), ("Praxis,fix calc.py now", "fix calc.py now"),
                           ("Pracsis, run it", "run it"), ("hey, praxis, list the files", "list the files")):
            self.assertEqual(split_wake(text), (True, rest), text)

    def test_ordinary_speech_does_not_wake_it(self):
        for text in ("practice makes perfect", "the proxies are down", "please fix the tests", "I think praxis is a nice word",
                     "thanks for watching", "turn the music up", "fix praxis", ""):
            self.assertFalse(split_wake(text)[0], text)

    def test_a_goal_keeps_its_filenames_and_punctuation(self):
        c = Conductor.__new__(Conductor)
        a = FakeActions(); said = []
        cond = Conductor(a, lambda t, u=False: said.append(t), clock=lambda: 1.0)
        cond.hear("Praxis, fix the failing tests in calc.py, without editing test_calc.py.")
        self.assertEqual(a.calls, [("submit", "fix the failing tests in calc.py, without editing test_calc.py.")])

    def test_intents(self):
        cases = [("stop", "stop"), ("stop that", "stop"), ("cancel", "stop"), ("never mind", "stop"), ("abort everything", "stop"),
                 ("mute", "mute"), ("go to sleep", "mute"), ("resume", "resume"), ("what's the status", "status"),
                 ("how is it going", "status"), ("are you done", "status"), ("", "wake_only"),
                 ("fix the failing tests in calc.py", "goal"), ("create hello.txt with hello", "goal")]
        for text, kind in cases:
            self.assertEqual(parse(text).kind, kind, text)
        self.assertEqual(parse("go private"), Intent("data", "private")); self.assertEqual(parse("open mode"), Intent("data", "open"))
        self.assertEqual(parse("set data to project"), Intent("data", "project"))
        self.assertEqual(parse("frugal mode"), Intent("frugal", "frugal")); self.assertEqual(parse("use less claude"), Intent("frugal", "frugal"))
        self.assertEqual(parse("best quality"), Intent("frugal", "quality")); self.assertEqual(parse("balanced"), Intent("frugal", "balanced"))

    def test_a_long_sentence_that_merely_mentions_a_setting_is_still_a_goal(self):
        self.assertEqual(parse("write a function that returns the open file handles in the project directory").kind, "goal")
        self.assertEqual(parse("explain how the frugal strategy works in the router code please now").kind, "goal")

    def test_approval_answers_are_strict(self):
        ap = lambda t, risky=False: parse(t, approving=True, risky=risky).kind
        for t in ("approve", "approved", "I approve", "yes approve", "approve it"):
            self.assertEqual(ap(t, True), "approve", t)
        for t in ("deny", "no", "nope", "don't", "do not", "reject", "stop", "cancel", "I don't approve", "do not approve that", "not approve"):
            self.assertEqual(ap(t, True), "deny", t)
        self.assertEqual(ap("yes", True), "confirm_risky")                            # risky: a bare yes only asks again
        self.assertEqual(ap("go ahead", True), "confirm_risky")
        self.assertEqual(ap("yes", False), "approve"); self.assertEqual(ap("go ahead", False), "approve")
        for t in ("fix the tests", "what time is it", "uh maybe"):
            self.assertEqual(ap(t, True), "unknown", t)                               # nothing else can become a goal meanwhile


class Narration(unittest.TestCase):
    def test_milestones_are_spoken_and_commentary_is_not(self):
        s, u = narrator.for_event("plan.accepted", {"plan": {"steps": [{}, {}, {}]}}); self.assertEqual((s, u), ("Plan ready: 3 steps.", False))
        self.assertIn("1 step.", narrator.for_event("plan.accepted", {"plan": {"steps": [{}]}})[0])
        self.assertIn("reversible", narrator.for_event("plan.accepted", {"plan": {"steps": [{}]}, "tainted": True})[0])
        for t in ("model.try", "model.call", "step.intent", "tool.result", "verify.result", "checkpoint", "guard.decision"):
            self.assertEqual(narrator.for_event(t, {"verdict": "ALLOW"}), (None, False), t)
        self.assertIn("blocked", narrator.for_event("guard.decision", {"verdict": "DENY", "reason": "outside the workspace"})[0])
        self.assertIn("stronger", narrator.for_event("escalation", {})[0])

    def test_final_reports_say_what_really_happened(self):
        rep = lambda **p: narrator.for_event("goal.report", p)
        self.assertEqual(rep(status="VERIFIED", evidence=[{"passed": True}, {"passed": True}, {"passed": False}]), ("Done. 2 checks passed.", True))
        self.assertEqual(rep(status="VERIFIED", evidence=[{"passed": True}])[0], "Done. 1 check passed.")
        self.assertIn("can't prove", rep(status="UNVERIFIED", reason="no real success check")[0])
        f = rep(status="FAILED", reason="verification failed: file_contains a.txt", rolled_back=True)[0]
        self.assertTrue(f.startswith("That failed") and "rolled everything back" in f)
        self.assertNotIn("rolled", rep(status="FAILED", reason="x", rolled_back=False)[0])
        self.assertTrue(rep(status="CANCELLED", rolled_back=True)[0].startswith("Stopped. I restored"))

    def test_speech_never_reads_out_secrets_paths_or_markup(self):
        c = narrator.clean
        self.assertNotIn("sk-", c("bad key sk-abcdefghijklmnopqrstuvwx in config")); self.assertIn("a credential", c("password = hunter2hunter2"))
        self.assertEqual(c("failed in /home/user/project/src/deep/file.py today"), "failed in a file today")
        self.assertNotIn("`", c("run `rm -rf` now")); self.assertTrue(len(c("word " * 100)) <= 150)

    def test_the_spoken_approval_is_the_exact_action_and_the_exact_words_accepted(self):
        req = lambda tool, cls, **a: types.SimpleNamespace(tool=tool, cls=cls, args=a)
        s = narrator.approval_prompt(req("shell.run", 4, cmd="python build.py"))
        self.assertIn("python build.py", s); self.assertIn("approve", s)
        self.assertIn("yes", narrator.approval_prompt(req("agent.delegate", 3, agent="claude", task="make made.txt")))
        self.assertIn("made.txt", narrator.approval_prompt(req("agent.delegate", 3, agent="claude", task="make made.txt")))

    def test_status_is_read_from_the_real_view(self):
        from praxis.desktop.view import StepView, View
        d = narrator.describe_status
        self.assertEqual(d(View(), "starting", []), "I'm still starting up.")
        self.assertEqual(d(View(), "idle", []), "I'm idle and ready.")
        v = View(goal_id="g", goal_text="fix calc", status="RUNNING", steps=[StepView("s1", "t", "", 0, "verified"), StepView("s2", "t", "", 0, "running")])
        self.assertIn("1 of 2 steps", d(v, "working", []))
        self.assertIn("planning", d(View(goal_id="g", goal_text="fix calc", status="PLANNING"), "working", []))
        self.assertIn("2 checks", d(View(goal_id="g", status="VERIFIED", evidence=[{"passed": True}, {"passed": True}]), "idle", []))
        pend = [types.SimpleNamespace(tool="shell.run", cls=4, args={"cmd": "x y"})]
        self.assertIn("waiting for your approval", d(v, "working", pend))


class FakeActions:
    def __init__(self):
        self._state, self.pending_list, self.calls = "idle", [], []
        self.submit_ok = True

    def pending(self): return list(self.pending_list)
    def state(self): return self._state
    def submit(self, t): self.calls.append(("submit", t)); return self.submit_ok
    def stop(self): self.calls.append(("stop",))
    def respond(self, rid, ok): self.calls.append(("respond", rid, ok)); self.pending_list = [p for p in self.pending_list if p.id != rid]
    def set_data(self, d): self.calls.append(("data", d))
    def set_frugality(self, k): self.calls.append(("frugal", k))
    def resume(self): self.calls.append(("resume",)); return False
    def mute(self): self.calls.append(("mute",))
    def status_text(self): return "STATUS"


class Rules(unittest.TestCase):
    def setUp(self):
        self.a, self.said, self.t = FakeActions(), [], [100.0]
        self.c = Conductor(self.a, lambda text, urgent=False: self.said.append((text, urgent)), clock=lambda: self.t[0], attentive_s=10, approval_s=60)

    def adv(self, s): self.t[0] += s
    def req(self, rid="r1", cls=4, tool="shell.run", **args): return types.SimpleNamespace(id=rid, cls=cls, tool=tool, args=args or {"cmd": "python build.py"})
    def spoken(self): return " | ".join(s for s, _ in self.said)

    def test_no_wake_word_means_no_action_and_no_reply(self):
        for t in ("fix the failing tests in calc.py", "please create a file", "thank you", "you", ""):
            self.assertTrue(self.c.hear(t).startswith("ignored"), t)
        self.assertEqual((self.a.calls, self.said), ([], []))

    def test_a_wake_prefixed_goal_runs_and_is_repeated_back_so_a_mishearing_is_caught(self):
        self.assertEqual(self.c.hear("Praxis, fix the failing tests in calc.py"), "goal")
        self.assertEqual(self.a.calls, [("submit", "fix the failing tests in calc.py")])
        self.assertIn("Understood. fix the failing tests in calc.py", self.spoken())

    def test_after_it_speaks_there_is_a_short_hands_free_window(self):
        self.c.hear("praxis what's the status"); self.said.clear()
        self.adv(5); self.assertEqual(self.c.hear("create hello.txt with hello world"), "goal")        # no wake word needed
        self.a.calls.clear(); self.adv(30); self.assertTrue(self.c.hear("create another file please now").startswith("ignored"))

    def test_the_hands_free_window_needs_a_real_sentence_not_a_stray_word(self):
        self.c.hear("praxis"); self.adv(2)
        self.assertEqual(self.c.hear("fix it"), "ignored: too short"); self.assertEqual(self.a.calls, [])
        self.assertEqual(self.c.hear("fix the calc tests"), "goal")

    def test_wake_word_alone_says_yes(self):
        self.assertEqual(self.c.hear("Praxis"), "wake"); self.assertEqual(self.said[-1][0], "Yes?")

    def test_stop_works_without_the_wake_word_only_while_something_runs(self):
        self.assertTrue(self.c.hear("stop").startswith("ignored"))
        self.a._state = "working"; self.assertEqual(self.c.hear("stop that"), "stop"); self.assertEqual(self.a.calls, [("stop",)])
        self.a.calls.clear(); self.a._state = "idle"; self.assertEqual(self.c.hear("praxis stop"), "nothing to stop"); self.assertEqual(self.a.calls, [])

    def test_a_new_goal_is_refused_while_one_is_running(self):
        self.a._state = "working"
        self.assertEqual(self.c.hear("praxis create a new file called b.txt"), "busy")
        self.assertEqual(self.a.calls, []); self.assertIn("Say stop", self.spoken())

    def test_the_same_words_twice_in_a_row_are_one_command(self):
        self.c.hear("praxis fix the failing tests"); self.assertEqual(self.c.hear("praxis fix the failing tests"), "ignored: repeat")
        self.assertEqual(len(self.a.calls), 1)

    def test_whisper_hallucinations_are_ignored_even_in_the_hands_free_window(self):
        self.c.hear("praxis"); 
        for t in ("Thank you.", "Thanks for watching", "you", "Bye"):
            self.assertEqual(self.c.hear(t), "ignored: noise", t)

    def test_settings_by_voice(self):
        self.c.hear("praxis go private"); self.c.hear("praxis frugal mode"); self.c.hear("praxis best quality"); self.c.hear("praxis balanced")
        self.assertEqual(self.a.calls, [("data", "private"), ("frugal", "frugal"), ("frugal", "quality"), ("frugal", "balanced")])
        self.assertIn("Only local models", self.spoken())

    def test_status_resume_and_mute(self):
        self.c.hear("praxis what's the status"); self.assertEqual(self.said[-1][0], "STATUS")
        self.c.hear("praxis resume"); self.assertIn("nothing to resume", self.spoken())
        self.c.hear("praxis mute"); self.assertIn(("mute",), self.a.calls); self.assertIn("F4", self.said[-1][0])

    def test_goal_start_failure_is_said_not_swallowed(self):
        self.a.submit_ok = False
        self.assertEqual(self.c.hear("praxis make a new file now"), "refused"); self.assertIn("can't start", self.spoken())

    # ---- approvals: the safety-critical part --------------------------------------------------------------------------------
    def test_a_new_approval_is_read_out_in_full_and_opens_an_answer_window_without_the_wake_word(self):
        self.a.pending_list = [self.req()]; self.c.tick()
        self.assertIn("python build.py", self.said[-1][0]); self.assertTrue(self.said[-1][1])
        self.said.clear(); self.c.tick(); self.assertEqual(self.said, [])                       # asked once, not every tick
        self.assertEqual(self.c.hear("approve"), "approve"); self.assertEqual(self.a.calls, [("respond", "r1", True)])

    def test_deny_and_ambiguous_negatives_deny(self):
        for words in ("deny", "no", "I don't approve", "do not approve that", "stop", "cancel"):
            self.a.calls.clear(); self.a.pending_list = [self.req()]; self.c.asked.clear(); self.c.last_text = ""
            self.c.hear(words); self.assertEqual(self.a.calls, [("respond", "r1", False)], words)

    def test_a_bare_yes_is_not_enough_for_a_risky_action_but_is_for_a_mild_one(self):
        self.a.pending_list = [self.req(cls=4)]
        self.assertEqual(self.c.hear("yes"), "asked again"); self.assertEqual(self.a.calls, [])
        self.assertIn("risky", self.said[-1][0])
        self.a.pending_list = [self.req("r2", cls=3, tool="agent.delegate", agent="claude", task="x")]; self.c.last_text = ""
        self.assertEqual(self.c.hear("yes"), "approve"); self.assertEqual(self.a.calls, [("respond", "r2", True)])

    def test_nothing_else_can_become_a_goal_while_an_approval_is_pending(self):
        self.a.pending_list = [self.req()]
        for t in ("praxis fix the failing tests in calc.py", "create a new file called x", "what a nice day"):
            self.c.last_text = ""; self.assertEqual(self.c.hear(t), "waiting for answer", t)
        self.assertEqual(self.a.calls, [])

    def test_silence_denies_after_a_reminder(self):
        self.a.pending_list = [self.req()]; self.c.tick(); self.said.clear()
        self.adv(25); self.c.tick(); self.assertIn("Still waiting", self.spoken()); self.assertEqual(self.a.calls, [])
        self.adv(40); self.c.tick()
        self.assertEqual(self.a.calls, [("respond", "r1", False)]); self.assertIn("No answer, so I denied", self.spoken())

    def test_an_approval_answered_elsewhere_is_forgotten(self):
        self.a.pending_list = [self.req()]; self.c.tick(); self.a.pending_list = []; self.c.tick()
        self.assertEqual(self.c.asked, {}); self.adv(100); self.c.tick(); self.assertEqual(self.a.calls, [])

    # ---- narration through the conductor ------------------------------------------------------------------------------------
    def test_events_are_narrated_and_each_final_report_only_once(self):
        ev = lambda i, t, **p: types.SimpleNamespace(id=i, type=t, payload=p)
        self.c.on_events([ev(1, "model.try", provider="x"), ev(2, "plan.accepted", plan={"steps": [{}, {}]}),
                          ev(3, "goal.report", status="VERIFIED", evidence=[{"passed": True}])])
        self.assertEqual([s for s, _ in self.said], ["Plan ready: 2 steps.", "Done. 1 check passed."])
        self.said.clear(); self.c.on_events([ev(3, "goal.report", status="VERIFIED", evidence=[{"passed": True}])]); self.assertEqual(self.said, [])
        self.adv(2); self.assertEqual(self.c.hear("create hello two text file please"), "goal")           # the report opened the hands-free window


if __name__ == "__main__":
    unittest.main()
