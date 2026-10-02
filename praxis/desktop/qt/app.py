"""PRAXIS: one screen, and you talk to it. The window IS the core ("The Reactor"). No menus, pages, chat box or mic button.

  just talk (no name needed)   it answers out loud; "stop" stops it     Esc / Ctrl+. / say "stop"   STOP (restores the workspace)
  F2 / F3  data class / frugality     F4  mute the microphone     Ctrl+O  open a folder     Ctrl+R  resume
(If voice cannot start - no microphone, engine missing - a typing line appears so the app is never unusable.)
Everything you need to know is on the core itself (state, rings, stream, caption, the live settings in the footer).
Lessons carried over from the earlier shells (each one was a real bug): the "stack is ready" snapshot runs BEFORE the first
poll, because a poll consumes events; a rendering error is shown, never fatal; an approval is asked about once.
"""
import os
import threading
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QLineEdit, QMainWindow, QMessageBox, QVBoxLayout, QWidget)

from ..view import View, summarize
from . import theme
from .core import CoreView
from ..voice_setup import VoiceUnavailable, build_voice
from .dialogs import ApprovalDialog
from .theme import C
from .widgets import Backdrop

DATA_CYCLE = ["project", "private", "open"]
FRUGAL_CYCLE = ["balanced", "frugal", "quality"]
STRATEGY = {"quality": "measured", "balanced": "auto", "frugal": "frugal"}
STRATEGY_BACK = {"measured": "quality", "auto": "balanced", "frugal": "frugal", "config": "balanced"}
PLACEHOLDER = ("What outcome do you want?     Enter run   |   Esc stop   |   F2 data   |   F3 frugality   |   Ctrl+O folder")


def apply_view(core, v, state, waiting, hint="", error=""):
    """Map the real state onto the core: its mode, plan progress, the three rings, which provider is lit."""
    done = sum(s.state in ("verified", "ran") for s in v.steps)
    prog = done / len(v.steps) if v.steps else 0.0
    if state == "starting":
        mode, ttl, sub = "starting", "STARTING", "detecting hardware, tools and sandbox"
    elif state == "error":
        mode, ttl, sub = "bad", "ERROR", error[:90]
    elif state == "stopping":
        mode, ttl, sub = "stopping", "STOPPING", "killing in-flight calls, restoring the workspace"
    elif waiting:
        mode, ttl, sub = "waiting", "NEEDS YOU", "approval required"
    elif v.status in ("PLANNING", "RUNNING"):
        mode, ttl = "working", v.status
        sub = f"step {min(done + 1, len(v.steps))} of {len(v.steps)}" if v.steps and v.status == "RUNNING" else (v.goal_text[:70] if v.goal_text else "")
    elif v.status == "VERIFIED":
        mode, ttl, sub, prog = "ok", "VERIFIED", f"{sum(e['passed'] for e in v.evidence)} checks passed", 1.0
    elif v.status == "UNVERIFIED":
        mode, ttl, sub = "stopped", "UNVERIFIED", v.reason[:90] or "no real success check"
    elif v.status == "CANCELLED":
        mode, ttl, sub = "stopped", "STOPPED", "workspace restored" if v.rolled_back else "stopped by you"
    elif v.status == "FAILED":
        mode, ttl, sub = "bad", "FAILED", (v.reason[:90] + ("  (rolled back)" if v.rolled_back else ""))
    elif hint and not v.goal_text:
        mode, ttl, sub = "stopped", "SETUP NEEDED", "no AI models yet: add a free key (praxis keys set groq) or sign in to Claude / Codex"
    else:
        mode, ttl, sub = "idle", "READY", "describe an outcome below"
    core.set_state(mode, prog, ttl, sub)
    checks = [bool(e["passed"]) for e in v.evidence]
    plan = ("planning" if v.status == "PLANNING" else "ready" if v.steps
            else "failed" if v.status == "FAILED" and v.reason.startswith("planning failed") else "none")
    core.set_pipeline(plan, [s.state for s in v.steps], checks, sealed=v.status == "VERIFIED" and bool(checks))
    core.set_active(v.active_provider)
    if state == "starting":
        core.set_caption("Booting: detecting hardware, tools and sandbox")
    elif state == "error":
        core.set_caption(error[:160], "bad")
    elif ttl == "SETUP NEEDED":
        core.set_caption(hint[:200], "warn")


class MainWindow(QMainWindow):
    def __init__(self, controller, telemetry=None, voice_factory=None):
        super().__init__()
        self.controller = controller
        self.voice_factory, self.voice, self.voice_error, self.voice_progress = voice_factory, None, "", ""
        self._voice_started, self._voice_msg_shown, self._mute_request, self._heard_at = False, False, False, 0.0
        self._shown, self._loaded_ws, self._closing = set(), None, False
        self._ask_queue, self._asking = [], False
        self._goal_t0, self._goal_dur, self._goal_id = None, None, ""
        self._prev_state, self.hint = None, ""
        self.setWindowTitle("PRAXIS")
        self.setMinimumSize(760, 520)
        self.resize(1280, 760)
        root = Backdrop()
        self.setCentralWidget(root)
        lay = QVBoxLayout(root); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        self.core = CoreView(); self.core.setMinimumSize(560, 300)
        lay.addWidget(self.core, 1)
        bar = QWidget(); bar.setStyleSheet("background: #04070d;")
        bl = QVBoxLayout(bar); bl.setContentsMargins(max(24, 0), 6, 24, 16)
        self.prompt = QLineEdit(); self.prompt.setPlaceholderText(PLACEHOLDER); self.prompt.setFixedHeight(44)
        self.prompt.setStyleSheet(f"QLineEdit {{ background: rgba(8,14,22,0.9); border: 1px solid {C['line2']}; border-radius: 22px; "
                                  f"padding: 0 22px; font-size: 14px; }} QLineEdit:focus {{ border-color: {C['accent']}; }}")
        self.prompt.returnPressed.connect(self.run_goal)
        bl.addWidget(self.prompt)
        lay.addWidget(bar, 0)
        self.prompt_bar = bar
        bar.hide()                       # no chat box: it only appears if voice cannot start
        for key, slot in (("Esc", self._escape), ("Ctrl+.", self.stop), ("F2", self.cycle_data), ("F3", self.cycle_frugality),
                          ("F4", self.toggle_mute), ("Ctrl+O", self.open_folder), ("Ctrl+R", self.resume_goal)):
            QShortcut(QKeySequence(key), self, slot)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(120)

    # ---- actions ---------------------------------------------------------------------------------
    def note(self, text, level="info"):
        self.core.set_caption(text, level)

    def run_goal(self):
        text = self.prompt.text().strip()
        if not text:
            self.note("Type the outcome you want first.", "warn")
            return
        if self.controller.state != "idle":
            self.note("PRAXIS is busy or still starting up.", "warn")
            return
        if self._loaded_ws != self.controller.workspace:
            self._on_ready()   # snapshot the history BEFORE this goal's events begin
        self.prompt.clear()
        self.note("Goal accepted. Planning...")
        self.controller.submit(text)

    def resume_goal(self):
        if not self.controller.resume():
            self.note("Nothing to resume.", "warn")

    def stop(self):
        if self.controller.state in ("working", "stopping"):
            self.controller.stop()
            self.note("Stopping: killing in-flight model calls and restoring the workspace...", "warn")

    def toggle_mute(self):
        if self.voice is None:
            self.note("Voice is not running.", "warn")
            return
        self.voice.set_muted(not self.voice.muted)
        self.note("Microphone off. Press F4 to listen again." if self.voice.muted else "Listening.", "warn" if self.voice.muted else "info")

    def _start_voice(self):
        """Bring the voice up in the background (model downloads and loading take seconds); the window stays alive meanwhile."""
        if self._voice_started:
            return
        self._voice_started = True
        st = self.controller.stack
        vcfg = dict(st.cfg.get("voice", {})) if st is not None else {}
        if not vcfg.get("enabled", True) and self.voice_factory is None:
            self.voice_error = "voice is switched off in your config"
            return

        def work():
            try:
                factory = self.voice_factory or build_voice
                loop = factory(self.controller, vcfg, progress=lambda t, f=None: setattr(self, "voice_progress", t),
                               on_mute=lambda: setattr(self, "_mute_request", True))
                self.voice = loop
                self.voice_progress = ""
                if getattr(loop, "voice_note", ""):
                    self.voice_progress = f"Voice: {loop.voice_note}"       # never leave a poor voice a mystery
                from ...voice.chat import _greeting
                import datetime
                loop.say(f"{_greeting(datetime.datetime.now())} I'm listening. Just talk to me.")
            except VoiceUnavailable as e:
                self.voice_error = str(e)
            except Exception as e:
                self.voice_error = f"{type(e).__name__}: {e}"
        threading.Thread(target=work, daemon=True, name="praxis-voice-start").start()

    def _voice_fallback(self):
        """Voice could not start: show the typing line (once) and say why."""
        self._voice_msg_shown = True
        self.prompt_bar.show(); self.prompt.setFocus()
        self.prompt.setPlaceholderText("Voice is off. Type an outcome here, Enter to run.")
        self.note(f"Voice is unavailable: {self.voice_error}. Type your outcome below.", "warn")

    def _escape(self):
        if self.controller.state in ("working", "stopping"):
            self.stop()
        else:
            self.prompt.clear()

    def cycle_data(self):
        cur = self.controller.effective_data_class()
        nxt = DATA_CYCLE[(DATA_CYCLE.index(cur) + 1) % 3] if cur in DATA_CYCLE else "project"
        self.controller.set_data_class(nxt)
        tip = {"private": "nothing leaves this machine: local models only", "project": "local + providers whose terms say no training",
               "open": "also free tiers that may train on prompts (never with a credential in the prompt)"}[nxt]
        self.note(f"DATA {nxt.upper()}: {tip}")

    def cycle_frugality(self):
        st = self.controller.stack
        cur = STRATEGY_BACK.get(st.router.strategy, "balanced") if st is not None else "balanced"
        nxt = FRUGAL_CYCLE[(FRUGAL_CYCLE.index(cur) + 1) % 3]
        self.controller.set_strategy(STRATEGY[nxt])
        tip = {"quality": "always the highest-scoring model", "balanced": "best first, the cheapest within 0.05 of it once measured",
               "frugal": "local, then free tiers, then Claude small to large; a failed check retries one level up"}[nxt]
        self.note(f"FRUGALITY {nxt.upper()}: {tip}")

    def open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a project folder", self.controller.workspace)
        if d:
            self._switch(d)

    def _switch(self, path):
        if os.path.realpath(path) == self.controller.workspace:
            return
        if not self.controller.open_workspace(path):
            if self.controller.refusal:
                QMessageBox.warning(self, "Choose a project folder", self.controller.refusal)
                self.note(self.controller.refusal, "warn")
            else:
                self.note("Finish or stop the current goal before switching folders.", "warn")
            return
        self._shown.clear()
        self._loaded_ws = None

    # ---- the heartbeat ----------------------------------------------------------------------------
    def _tick(self):
        if self._closing:
            return
        try:
            self._update()
        except Exception as e:   # a rendering bug must never take the whole window down
            self.note(f"UI error: {type(e).__name__}: {e}", "bad")

    def _update(self):
        c = self.controller
        state = c.state
        if state in ("idle", "working", "stopping") and self._loaded_ws != c.workspace:
            self._on_ready()   # BEFORE the first poll (a poll consumes events); tied to "stack built", not to idle
        if state not in ("starting", "error"):
            self._start_voice()
        u = c.poll() if state not in ("starting", "error") else None
        waiting = False
        if u is not None:
            text = level = None
            for e in u.events:
                text, level = summarize(e)
                self.core.pulse(level)               # a real event: the core flares, a ripple runs outward
                if text:
                    self.core.add_log(text, level)   # ...and it is written to the event feed
            if text:
                self.core.set_caption(text, level)   # and the latest one is typed out
            if self.voice is not None and u.events:
                self.voice.conductor.on_events(u.events)     # the milestones among them are spoken
            waiting = (bool(u.approvals) or u.view.status == "WAITING FOR YOU") and state == "working"
            apply_view(self.core, u.view, state, waiting, self.hint, c.error)
            self._update_stats(u.view, state)
            for req in u.approvals:
                if req.id not in self._shown:
                    self._shown.add(req.id)
                    self._ask_queue.append(req)
                    QTimer.singleShot(0, self._next_approval)       # NOT inline: a modal dialog inside this timer's slot would freeze the timer
            if state == "idle" and self._prev_state in ("working", "stopping"):
                self.prompt.setFocus()
        else:
            apply_view(self.core, View(), state, False, self.hint, c.error)
        self._update_voice(state)
        self.core.set_nodes(c.nodes())
        self.core.set_footer(self._footer(state))
        self.prompt.setEnabled(state != "starting")
        if c.notes:
            self.note(c.notes.pop(), "bad")
        self._prev_state = state

    def _update_stats(self, v, state):
        """The real numbers beside the core: how long the goal has run, steps and checks done, which brain is thinking, what it cost."""
        now = time.time()
        if v.goal_id and v.goal_id != self._goal_id:                 # a new goal: the clock starts when we first see it (even a very quick one)
            self._goal_id, self._goal_t0, self._goal_dur = v.goal_id, now, None
        elif state == "working" and self._goal_t0 is None and self._goal_dur is None:
            self._goal_t0 = now
        if state != "working" and self._goal_t0 is not None:
            self._goal_dur, self._goal_t0 = now - self._goal_t0, None
        secs = (now - self._goal_t0) if self._goal_t0 is not None else self._goal_dur
        if not v.goal_id or secs is None:
            self.core.set_stats({})
            return
        done = sum(s.state in ("verified", "ran") for s in v.steps)
        stats = {"elapsed": f"{int(secs) // 60:02d}:{int(secs) % 60:02d}", "steps": f"{done}/{len(v.steps)}",
                 "checks": f"{sum(1 for e in v.evidence if e.get('passed'))}/{len(v.evidence)}",
                 "brain": (v.active_provider.split("/")[0] if v.active_provider else "-")}
        if v.cost:
            stats["cost"] = f"${v.cost:.3f}"
        self.core.set_stats(stats)

    def _update_voice(self, state):
        if self._mute_request:                       # "praxis, mute" arrives from the voice thread
            self._mute_request = False
            if self.voice is not None and not self.voice.muted:
                self.toggle_mute()
        if self.voice is not None:
            if self.voice_progress.startswith("Voice: "):                # the voice is degraded: say why, once
                self.core.set_caption(self.voice_progress[:200], "warn"); self.voice_progress = ""
            snap = self.voice.snapshot()
            self.core.set_voice(snap["state"], snap["level"], snap["speak_level"], snap["attentive"])
            if self.voice.unspoken:                      # it could not speak (no speaker, synthesis failed): say it on screen instead
                self.core.set_caption(self.voice.unspoken[:200], "warn"); self.voice.unspoken = ""
            tr = self.voice.transcripts
            if tr and tr[-1][0] > self._heard_at and not tr[-1][2].startswith("ignored"):
                self._heard_at = tr[-1][0]
                self.core.set_caption(f"\u201c{tr[-1][1].strip()}\u201d", "info")      # what it heard you say, so a mishearing is visible
        elif self.voice_error and not self._voice_msg_shown:
            self._voice_fallback()
        elif self.voice_progress and state in ("idle", "starting"):
            self.core.set_caption(self.voice_progress)

    def _footer(self, state):
        """Real settings, shown under the core: how it is routing, what data it may touch, how many models it can reach."""
        c, st = self.controller, self.controller.stack
        if st is None or state in ("starting", "error"):
            return ""
        return (f"ROUTING {STRATEGY_BACK.get(st.router.strategy, st.router.strategy).upper()}   ·   "
                f"DATA {c.effective_data_class().upper()}   ·   {len(st.providers)} MODELS")

    def _next_approval(self):
        if self._asking or not self._ask_queue:
            return
        self._asking = True
        try:
            req = self._ask_queue.pop(0)
            if any(r.id == req.id for r in self.controller.pending_approvals()):      # it may have been answered by voice meanwhile
                self._ask(req)
        finally:
            self._asking = False
        if self._ask_queue and not self._closing:
            QTimer.singleShot(0, self._next_approval)

    def _ask(self, req):
        dlg = ApprovalDialog(self, req)
        dlg.watch(lambda rid: any(r.id == rid for r in self.controller.pending_approvals()))   # closes itself if answered by voice
        dlg.exec()
        if not dlg.answered_elsewhere:
            self.controller.respond(req.id, dlg.answer)    # closing the dialog any other way is a refusal

    def _on_ready(self):
        c = self.controller
        self._loaded_ws = c.workspace
        c.mark_read()
        self.setWindowTitle(f"PRAXIS - {os.path.basename(c.workspace) or c.workspace}")
        info = c.info
        n = len(info.get("providers", []))
        missing = ", ".join(sorted(info.get("skipped", {})))
        self.hint = "" if n else (
            "No AI models yet. Sign in to Claude (claude), ChatGPT (codex) or Factory (droid), install Ollama for local models, "
            f"or add a free key:  python -m praxis keys set groq   Not found: {missing}.")
        fams = list(dict.fromkeys(str(x).split("/")[0] for x in info.get("providers", [])))
        if fams:
            self.core.add_log("BRAINS ONLINE  " + " \u00b7 ".join(fams), "ok")
        for name in ("devin", "droid"):                                       # the two desktop-app brains: say plainly if one is missing
            why = info.get("skipped", {}).get(name)
            if why:
                self.core.add_log(f"{name.upper()} OFFLINE: {str(why)[:70]}", "warn")
        if info.get("sandbox"):
            self.core.add_log(f"SANDBOX {str(info['sandbox']).upper()}" + ("" if info.get("sandbox_strong") else " \u00b7 risky steps ask first"), "info" if info.get("sandbox_strong") else "warn")
        if n:
            self.note(f"Ready. {n} model instance(s) available." + ("  Interrupted goal found: Ctrl+R resumes it." if c.unfinished() else ""))

    # ---- shutdown ---------------------------------------------------------------------------------
    def closeEvent(self, ev):
        c = self.controller
        if c.state in ("working", "stopping"):
            r = QMessageBox.question(self, "PRAXIS is working", "Stop the current goal and exit?\n\nThe workspace will be restored to its previous state.")
            if r != QMessageBox.Yes:
                ev.ignore()
                return
            c.stop()
            end = time.time() + 8
            while c.state != "idle" and time.time() < end:
                QApplication.processEvents()
                time.sleep(0.05)
        self._closing = True
        self.core.dispose()
        if self.voice is not None:
            self.voice.close()
        try:
            c.settings.geometry = f"{self.width()}x{self.height()}"
            c.settings.save()
        except Exception:
            pass
        ev.accept()


def run(controller, telemetry=None):
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("PRAXIS")
    ui, mono = theme.fonts()
    app.setStyleSheet(theme.qss(ui, mono))
    win = MainWindow(controller, telemetry)
    win.show()
    return app.exec()
