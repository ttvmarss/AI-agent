"""The conductor: turns what was heard into actions, and what happened into what is said. Thread-safe, engine-free, testable.

Rules that hold whatever the recogniser hears:
  * a wake word is needed, except (a) STOP while something is running and (b) the answer to a pending approval;
  * after PRAXIS speaks to you (or finishes) there is a short hands-free window with no wake word needed;
  * a risky approval (Class 4+) needs the literal word "approve"; a bare "yes" only asks again; silence means DENY;
  * while an approval is pending nothing else can become a goal; while a goal runs a new one is refused;
  * it never acts on text it already acted on in the last few seconds (an echo or a repeat).
"""
import threading
import time

from . import narrator, wake, chat as chat_mod

PHANTOM = {"thank you", "thanks", "thanks for watching", "you", "bye", "okay", "ok", "hmm", "uh", "um", "the", "so", "yeah"}
PROMPT_DELAY = 0.8


class Conductor:
    def __init__(self, actions, say, clock=time.monotonic, wake_word="praxis", attentive_s=15.0, approval_s=60.0, log=None, chat=None):
        self.a, self.say, self.clock = actions, say, clock
        self.chat, self.chat_lock, self.chatting = chat, threading.Lock(), 0
        self.wake_word, self.attentive_s, self.approval_s = wake_word, attentive_s, approval_s
        self.log = log or (lambda *_: None)
        self.lock = threading.RLock()
        self.attentive_until = 0.0
        self.last_text, self.last_at = "", -99.0
        self.asked = {}                 # approval id -> (asked_at, reminded)
        self.seen = {}                  # approval id -> first seen (the prompt waits PROMPT_DELAY so earlier events are said first)
        self.spoken_reports = set()
        self.last_unknown_at = -99.0

    # ---- what was heard --------------------------------------------------------------------------------------------
    def hear(self, text):
        """Handle one transcript. Returns what it did (also useful in tests and logs)."""
        with self.lock:
            now = self.clock()
            norm = wake.normalize(text)
            if not norm or norm in PHANTOM:
                return "ignored: noise"
            if norm == self.last_text and now - self.last_at < 4.0:
                return "ignored: repeat"
            heard_wake, rest = wake.split_wake(text, self.wake_word)
            if not heard_wake and self.chat is not None:           # "Hello, Praxis." / "What time is it, Praxis?"
                tw, trest = wake.split_trailing_wake(text, self.wake_word)
                if tw and chat_mod.classify(trest) == "chat":
                    heard_wake, rest = True, trest
            pending = self.a.pending()
            approving = bool(pending)
            busy = self.a.state() in ("working", "stopping")
            attentive = now < self.attentive_until
            safe_stop = busy and wake.STOP.match(norm) is not None
            if not (heard_wake or approving or attentive or safe_stop):
                return "ignored: no wake word"
            self.last_text, self.last_at = norm, now
            risky = bool(pending) and pending[0].cls >= 4
            original = rest if heard_wake else (text or "").strip()
            intent = wake.parse(original, busy=busy, approving=approving, risky=risky)
            self.log("heard", text, intent.kind)
            if intent.kind == "approve" and not heard_wake:      # a television or a bystander saying "approve" must never run anything
                return "ignored: an approval must start with my name"
            return self._act(intent, pending, heard_wake, busy, now)

    def _act(self, it, pending, heard_wake, busy, now):
        k = it.kind
        if k == "stop":
            if busy:
                self.a.stop(); self.say("Stopping. I'll restore the workspace.", True)
                return "stop"
            self.say("Nothing is running.")
            return "nothing to stop"
        if k in ("approve", "deny") and pending:
            req = pending[0]
            ok = k == "approve"
            self.a.respond(req.id, ok)
            self.asked.pop(req.id, None)
            self.say("Approved." if ok else "Denied. Nothing was changed.")
            self._attend(now)
            return k
        if k == "confirm_risky":
            self.say("That one is risky. Say Praxis, approve to allow it, or deny.")
            return "asked again"
        if k == "unknown":
            if now - self.last_unknown_at > 8.0:
                self.say("I'm waiting for your answer. Say Praxis, approve, or deny.")
                self.last_unknown_at = now
            return "waiting for answer"
        if k == "stray_answer":
            self.say("Nothing is waiting for your approval.")
            return "nothing pending"
        if k == "mute":
            self.a.mute()
            self.say("Muted. Press F4 to listen again.", True)
            return "mute"
        if k == "wake_only":
            self.say("Yes?"); self._attend(now)
            return "wake"
        if k == "status":
            self.say(self.a.status_text()); self._attend(now)
            return "status"
        if k == "resume":
            if self.a.resume():
                self.say("Resuming the interrupted goal.")
            else:
                self.say("There's nothing to resume.")
            self._attend(now)
            return "resume"
        if k == "data":
            self.a.set_data(it.arg)
            self.say({"private": "Data class private. Only local models will see your goals.",
                      "project": "Data class project. Local models and providers that don't train on your data.",
                      "open": "Data class open. Free tiers that may train on prompts are allowed, but never with a credential in the prompt."}[it.arg])
            self._attend(now)
            return "data"
        if k == "frugal":
            key = "quality" if it.arg in ("quality", "best") else it.arg
            self.a.set_frugality(key)
            self.say({"frugal": "Frugal mode. Local models first, then free tiers, then Claude from small to large.",
                      "balanced": "Balanced mode.", "quality": "Quality mode. Best model, whatever the cost."}[key])
            self._attend(now)
            return "frugal"
        if k == "goal":
            words = it.arg.split()
            if self.chat is not None and chat_mod.classify(it.arg) == "chat" and (heard_wake or len(words) >= 2):
                self._converse(it.arg)                          # a question or small talk: answer it, don't plan and verify it
                self._attend(now)
                return "chat"
            if len(words) < (2 if heard_wake else 3) or len(it.arg) > 600:
                if heard_wake:
                    self.say("Sorry, I didn't catch that.")
                return "ignored: too short"
            if busy:
                self.say("I'm still working on the last goal. Say stop to cancel it.")
                return "busy"
            if self.a.pending():
                return "ignored: approval pending"
            if self.a.submit(it.arg):
                self.say("On it.")
                self._attend(now)
                return "goal"
            self.say("I can't start that right now.")
            return "refused"
        return "ignored"

    def _converse(self, text):
        """Answer in words, off the listening thread. Small talk is instant; anything else asks a model, and if that takes a while
        it says so once rather than leaving you wondering."""
        def work():
            with self.chat_lock:
                self.chatting += 1
                timer = threading.Timer(3.0, lambda: self.say("One moment."))
                timer.daemon = True
                timer.start()
                try:
                    reply = self.chat.reply(text)
                except Exception as e:
                    self.log("chat-error", type(e).__name__, str(e))
                    reply = "Sorry, I lost my train of thought. Say that again?"
                finally:
                    timer.cancel()
                    self.chatting -= 1
                if reply:
                    self.say(reply)
                    with self.lock:
                        self._attend(self.clock())
        threading.Thread(target=work, daemon=True, name="praxis-chat").start()

    def _attend(self, now):
        self.attentive_until = max(self.attentive_until, now + self.attentive_s)

    # ---- what happened -----------------------------------------------------------------------------------------------
    def on_events(self, events):
        """Speak the milestones among these real events (each final report only once)."""
        with self.lock:
            for e in events:
                if e.type == "goal.report":
                    if e.id in self.spoken_reports:
                        continue
                    self.spoken_reports.add(e.id)
                try:
                    sentence, urgent = narrator.for_event(e.type, e.payload)
                except Exception as ex:                          # one odd event must never stop the others being spoken
                    self.log("narrate-error", type(ex).__name__, str(ex))
                    continue
                if sentence:
                    self.say(sentence, urgent)
                    if urgent:
                        self._attend(self.clock())

    def tick(self):
        """Call a few times a second: asks about new approvals, reminds, and denies on silence."""
        with self.lock:
            now = self.clock()
            pending = self.a.pending()
            live = {r.id for r in pending}
            for rid in list(self.asked):
                if rid not in live:
                    del self.asked[rid]
            for rid in list(self.seen):
                if rid not in live:
                    del self.seen[rid]
            for req in pending:
                if req.id not in self.asked:
                    first = self.seen.setdefault(req.id, now)
                    if now - first < PROMPT_DELAY:                 # let the events that led here ("plan ready") be said first
                        continue
                    self.asked[req.id] = [now, False]
                    self.say(narrator.approval_prompt(req), True)
                    self.attentive_until = max(self.attentive_until, now + self.approval_s)
                    continue
                at, reminded = self.asked[req.id]
                if now - at > self.approval_s:
                    self.a.respond(req.id, False)
                    self.asked.pop(req.id, None)
                    self.say("No answer, so I denied that. Nothing was changed.", True)
                elif not reminded and now - at > self.approval_s / 3:
                    self.asked[req.id][1] = True
                    self.say("Still waiting. Say Praxis, approve, or deny.", True)
