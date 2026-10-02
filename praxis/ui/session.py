"""The Session: everything the old desktop window did, with no window. It owns the Controller (the engine) and the voice loop, folds the engine's
real events into one `frame` ten times a second, and executes the commands the interface sends. A frame is plain JSON-able data (see
ui/src/protocol.ts for the contract); the server just streams the latest one. Lessons carried over from the earlier shells, each a real bug:
the history snapshot must be taken BEFORE the first poll (a poll consumes events), a bad frame must never kill the loop, an approval is shown once."""
import datetime
import os
import threading
import time
from collections import deque

from .. import build
from ..desktop.view import View, summarize
from ..desktop.voice_setup import VoiceUnavailable, build_voice
from . import model

MAX_TEXT = 4000


class Session:
    def __init__(self, controller, voice_factory=None, clock=time.time, tick_s=0.1):
        self.c = controller
        self.voice_factory, self.voice, self.voice_error, self.voice_progress = voice_factory, None, "", ""
        self.clock, self.tick_s = clock, tick_s
        self._voice_started, self._mute_request, self._heard_at, self._voice_note = False, False, 0.0, ""
        self._loaded_ws, self._closing, self._hint = None, False, ""
        self._goal_t0, self._goal_dur, self._goal_id = None, None, ""
        self._log, self._log_id = deque(maxlen=60), 0
        self._last_call_ms, self._shock, self._shock_goal = None, 0, ""
        self._notes_seen = 0
        self._frame, self._seq = None, 0
        self._cond = threading.Condition()
        self._thread = None
        self.quit_requested = threading.Event()

    # ---- lifecycle ----------------------------------------------------------------------------------------------
    def start(self):
        self._tick_safely()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="praxis-session")
        self._thread.start()
        return self

    def close(self):
        self._closing = True
        if self.voice is not None:
            try:
                self.voice.close()
            except Exception:
                pass
        try:
            self.c.settings.save()
        except Exception:
            pass

    def _loop(self):
        while not self._closing:
            t0 = time.time()
            self._tick_safely()
            time.sleep(max(0.0, self.tick_s - (time.time() - t0)))

    def _tick_safely(self):
        try:
            self._tick()
        except Exception as e:                       # a bug while folding state must never stop the interface: it is shown in the event stream
            self._add_log(f"UI error: {type(e).__name__}: {e}", "bad")
            self._publish()

    # ---- the frame ----------------------------------------------------------------------------------------------
    def frame(self):
        """The latest frame (a dict) and its sequence number."""
        with self._cond:
            return self._frame, self._seq

    def wait(self, seq, timeout=15.0):
        """Block until a frame newer than `seq` exists (or the timeout passes); -> (frame, seq)."""
        with self._cond:
            if self._seq <= seq:
                self._cond.wait(timeout)
            return self._frame, self._seq

    def _publish(self, **extra):
        f = self._build_frame(**extra)
        with self._cond:
            self._frame, self._seq = f, self._seq + 1
            self._cond.notify_all()

    def _add_log(self, text, level="info", stamp=None):
        text = str(text or "").strip()
        if not text or (self._log and self._log[-1]["text"] == text[:160]):
            return
        self._log_id += 1
        self._log.append({"id": self._log_id, "time": stamp or time.strftime("%H:%M:%S"), "text": text[:160], "level": level})

    def _tick(self):
        c = self.c
        state = c.state
        if state in ("idle", "working", "stopping") and self._loaded_ws != c.workspace:
            self._on_ready()                         # BEFORE the first poll (a poll consumes events); tied to "stack built", not to idle
        if state not in ("starting", "error"):
            self._start_voice()
        u = c.poll() if state not in ("starting", "error") else None
        waiting, view, approvals = False, View(), []
        if u is not None:
            for e in u.events:
                text, level = summarize(e)
                if text:
                    self._add_log(text, level)
                if e.type == "model.call" and e.payload.get("ok") and e.payload.get("duration_ms"):
                    self._last_call_ms = float(e.payload["duration_ms"])
            if self.voice is not None and u.events:
                self.voice.conductor.on_events(u.events)          # the milestones among them are spoken
            waiting = (bool(u.approvals) or u.view.status == "WAITING FOR YOU") and state == "working"
            view, approvals = u.view, u.approvals
            if view.status == "VERIFIED" and view.goal_id and view.goal_id != self._shock_goal:
                self._shock_goal, self._shock = view.goal_id, self._shock + 1
        self._update_stats_state(view, state)
        self._voice_tick(state)
        while self._notes_seen < len(c.notes):                    # errors the engine queued for the user
            self._add_log(c.notes[self._notes_seen], "bad")
            self._notes_seen += 1
        self._publish(view=view, state=state, waiting=waiting, approvals=approvals)
        self._prev_state = state

    def _on_ready(self):
        c = self.c
        self._loaded_ws = c.workspace
        c.mark_read()
        self._add_log("BUILD  " + build.label())
        info = c.info
        n = len(info.get("providers", []))
        missing = ", ".join(sorted(info.get("skipped", {})))
        self._hint = "" if n else ("No AI models yet. Sign in to Claude (claude), ChatGPT (codex) or Factory (droid), install Ollama for local models, "
                                   f"or add a free key:  python -m praxis keys set groq   Not found: {missing}.")
        self._add_log("JARVIS  conversation mind online")
        self._add_log("FRIDAY  execution mind online", "warn")
        fams = list(dict.fromkeys(str(x).split("/")[0] for x in info.get("providers", [])))
        if fams:
            self._add_log("BRAINS ONLINE  " + " · ".join(fams), "ok")
        for name in ("devin", "droid"):
            why = info.get("skipped", {}).get(name)
            if why:
                self._add_log(f"{name.upper()} OFFLINE: {str(why)[:70]}", "warn")
        if info.get("sandbox"):
            strong = bool(info.get("sandbox_strong"))
            self._add_log(f"SANDBOX {str(info['sandbox']).upper()}" + ("" if strong else " · risky steps ask first"), "info" if strong else "warn")
        if n and c.unfinished():
            self._add_log("Interrupted goal found: Ctrl+R resumes it.", "warn")

    def _update_stats_state(self, v, state):
        now = self.clock()
        if v.goal_id and v.goal_id != self._goal_id:                     # a new goal: the clock starts when we first see it (even a very quick one)
            self._goal_id, self._goal_t0, self._goal_dur = v.goal_id, now, None
        elif state == "working" and self._goal_t0 is None and self._goal_dur is None:
            self._goal_t0 = now
        if state != "working" and self._goal_t0 is not None:
            self._goal_dur, self._goal_t0 = now - self._goal_t0, None

    def _stats(self, v):
        now = self.clock()
        secs = (now - self._goal_t0) if self._goal_t0 is not None else self._goal_dur
        if not v.goal_id or secs is None:
            return {"elapsed": "", "steps": "", "checks": "", "brain": "", "cost": "", "last_call_ms": self._last_call_ms}
        done = sum(s.state in ("verified", "ran") for s in v.steps)
        return {"elapsed": f"{int(secs) // 60:02d}:{int(secs) % 60:02d}", "steps": f"{done}/{len(v.steps)}",
                "checks": f"{sum(1 for e in v.evidence if e.get('passed'))}/{len(v.evidence)}",
                "brain": (v.active_provider.split("/")[0] if v.active_provider else "-"), "cost": f"${v.cost:.3f}" if v.cost else "", "last_call_ms": self._last_call_ms}

    def _build_frame(self, view=None, state=None, waiting=False, approvals=()):
        c = self.c
        state = state or c.state
        v = view if view is not None else View()
        mode, title, sub, prog = model.mode_for(v, state, waiting, self._hint, c.error)
        voice = {"state": "off", "level": 0.0, "speak": 0.0, "attentive": False, "heard": "", "said": "", "note": self._voice_note}
        if self.voice is not None:
            try:
                snap = self.voice.snapshot()
                voice.update(state=snap["state"], level=min(1.0, float(snap["level"]) / 0.12) ** 0.6 if snap["level"] > 0 else 0.0,
                             speak=min(1.0, float(snap["speak_level"])), attentive=bool(snap["attentive"]), said=str(snap.get("said", ""))[:200])
            except Exception:
                pass
            tr = self.voice.transcripts
            if tr and not tr[-1][2].startswith("ignored"):
                voice["heard"] = tr[-1][1].strip()[:200]
        elif self.voice_error:
            voice["state"] = "offline"
        stack = c.stack
        settings = {"data_class": c.effective_data_class(), "strategy": model.STRATEGY_BACK.get(stack.router.strategy, stack.router.strategy) if stack else "balanced",
                    "models": len(stack.providers) if stack else 0}
        recent = list(getattr(c.settings, "recent", []))[:8]
        info = c.info if state not in ("starting",) else {}
        return {"v": 1, "t": self.clock(), "mode": mode, "title": title, "subtitle": sub, "goal": v.goal_text[:400], "progress": prog,
                "pipeline": model.pipeline(v), "active": v.active_provider, "brains": [model.brain(n) for n in (c.nodes() if state not in ("starting", "error") else [])],
                "stats": self._stats(v), "voice": voice, "log": list(self._log)[-40:], "approvals": [model.approval(a) for a in approvals][:5],
                "settings": settings,
                "info": {"build": build.label(), "workspace": c.workspace, "workspace_name": os.path.basename(c.workspace) or c.workspace, "hint": self._hint,
                         "sandbox": str(info.get("sandbox", "")), "sandbox_strong": bool(info.get("sandbox_strong")), "recent": recent,
                         "can_type": bool(self.voice_error and self.voice is None)},
                "shock": self._shock}

    # ---- voice --------------------------------------------------------------------------------------------------
    def _start_voice(self):
        """Bring the voice up in the background (model downloads and loading take seconds); the interface stays alive meanwhile."""
        if self._voice_started:
            return
        self._voice_started = True
        st = self.c.stack
        vcfg = dict(st.cfg.get("voice", {})) if st is not None else {}
        if not vcfg.get("enabled", True) and self.voice_factory is None:
            self.voice_error = "voice is switched off in your config"
            self._voice_note = self.voice_error
            return

        def work():
            try:
                factory = self.voice_factory or build_voice
                loop = factory(self.c, vcfg, progress=lambda t, f=None: setattr(self, "voice_progress", t),
                               on_mute=lambda: setattr(self, "_mute_request", True))
                self.voice, self.voice_progress = loop, ""
                if getattr(loop, "voice_note", ""):
                    self._voice_note = f"Voice: {loop.voice_note}"          # never leave a poor voice a mystery
                    self._add_log(self._voice_note, "warn")
                from ..voice.chat import _greeting
                loop.say(f"{_greeting(datetime.datetime.now())} I'm listening. Just talk to me.")
            except VoiceUnavailable as e:
                self.voice_error = str(e)
            except Exception as e:
                self.voice_error = f"{type(e).__name__}: {e}"
            if self.voice_error and self.voice is None:
                self._voice_note = f"Voice is unavailable: {self.voice_error}. Type your outcome instead."
                self._add_log(self._voice_note, "warn")
        threading.Thread(target=work, daemon=True, name="praxis-voice-start").start()

    def _voice_tick(self, state):
        if self._mute_request:                       # "praxis, mute" arrives from the voice thread
            self._mute_request = False
            if self.voice is not None and not self.voice.muted:
                self.cmd_mute()
        if self.voice is not None and self.voice.unspoken:           # it could not speak (no speaker, synthesis failed): say it on screen instead
            self._add_log(self.voice.unspoken[:160], "warn")
            self.voice.unspoken = ""

    # ---- commands -------------------------------------------------------------------------------------------------
    def command(self, cmd):
        """Execute one interface command (a dict, already shape-checked by the server). -> (ok, message)."""
        kind = cmd.get("cmd")
        fn = getattr(self, f"cmd_{kind}", None)
        if fn is None:
            return False, f"unknown command {kind!r}"
        try:
            return fn(cmd)
        except Exception as e:                       # a command can fail; the interface must never see an exception
            return False, f"{type(e).__name__}: {e}"

    def cmd_submit(self, cmd):
        text = str(cmd.get("text", "")).strip()[:MAX_TEXT]
        if not text:
            return False, "Type the outcome you want first."
        if self.c.state != "idle":
            self._add_log("PRAXIS is busy or still starting up.", "warn")
            return False, "busy"
        if self._loaded_ws != self.c.workspace:
            self._on_ready()                         # snapshot the history BEFORE this goal's events begin
        self._add_log("Goal accepted. Planning...")
        return (True, "") if self.c.submit(text) else (False, "could not start")

    def cmd_stop(self, cmd=None):
        if self.c.state in ("working", "stopping"):
            self.c.stop()
            self._add_log("Stopping: killing in-flight model calls and restoring the workspace...", "warn")
            return True, ""
        return False, "nothing is running"

    def cmd_approve(self, cmd):
        rid = str(cmd.get("id", ""))
        if not any(r.id == rid for r in self.c.pending_approvals()):
            return False, "that approval is no longer pending"
        self.c.respond(rid, bool(cmd.get("ok")))
        return True, ""

    def cmd_set_data(self, cmd):
        v = cmd.get("value")
        if v not in model.DATA_CYCLE:
            return False, "bad data class"
        self.c.set_data_class(v)
        tip = {"private": "nothing leaves this machine: local models only", "project": "local + providers whose terms say no training",
               "open": "also free tiers that may train on prompts (never with a credential in the prompt)"}[v]
        self._add_log(f"DATA {v.upper()}: {tip}")
        return True, ""

    def cmd_set_strategy(self, cmd):
        v = cmd.get("value")
        if v not in model.STRATEGY:
            return False, "bad strategy"
        self.c.set_strategy(model.STRATEGY[v])
        tip = {"quality": "always the highest-scoring model", "balanced": "best first, the cheapest within 0.05 of it once measured",
               "frugal": "local, then free tiers, then Claude small to large; a failed check retries one level up"}[v]
        self._add_log(f"FRUGALITY {v.upper()}: {tip}")
        return True, ""

    def cmd_mute(self, cmd=None):
        if self.voice is None:
            self._add_log("Voice is not running.", "warn")
            return False, "voice is not running"
        want = (cmd or {}).get("value")
        self.voice.set_muted((not self.voice.muted) if want is None else bool(want))
        self._add_log("Microphone off. Press F4 to listen again." if self.voice.muted else "Listening.", "warn" if self.voice.muted else "info")
        return True, ""

    def cmd_resume(self, cmd=None):
        if self.c.resume():
            return True, ""
        self._add_log("Nothing to resume.", "warn")
        return False, "nothing to resume"

    def cmd_undo(self, cmd=None):
        return (True, "") if self.c.undo() else (False, "busy")

    def cmd_open_workspace(self, cmd):
        path = str(cmd.get("path", "")).strip()
        if not path:
            return False, "no folder given"
        if os.path.realpath(path) == self.c.workspace:
            return True, ""
        if not self.c.open_workspace(path):
            msg = self.c.refusal or "Finish or stop the current goal before switching folders."
            self._add_log(msg, "warn")
            return False, msg
        self._loaded_ws = None
        return True, ""

    def cmd_quit(self, cmd=None):
        if self.c.state in ("working", "stopping"):
            self.c.stop()
            end = time.time() + 8
            while self.c.state != "idle" and time.time() < end:
                time.sleep(0.05)
        self.quit_requested.set()
        return True, ""
