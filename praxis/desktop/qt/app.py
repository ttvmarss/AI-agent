"""The PRAXIS command center (PySide6). One native window; every pixel is a projection of the event log and the router.

Lessons carried over from the Tk shell (each one was a real bug there):
  * the "stack is ready" snapshot runs BEFORE the first poll, because a poll consumes events;
  * the activity feed and the timeline are fed independently, so one failing cannot starve the other;
  * the timeline add is idempotent;
  * a rendering error is shown in the status bar and never takes the window down.
"""
import os
import queue
import threading
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QMainWindow, QMessageBox,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..view import View
from . import theme
from .dialogs import ApprovalDialog, KeyDialog
from .pages import FuelPage, MemoryPage, MissionPage, ModelsPage, SystemPage, TimelinePage
from .theme import C
from .widgets import Backdrop, Chip, ElidedLabel, FuelBar, NavButton, Segmented

NAV = [("Mission", "mission", MissionPage), ("Timeline", "timeline", TimelinePage), ("Fuel", "fuel", FuelPage),
       ("Models", "models", ModelsPage), ("Memory", "memory", MemoryPage), ("System", "system", SystemPage)]
PILL = {"starting": ("STARTING", "muted"), "idle": ("READY", "ok"), "working": ("WORKING", "accent"),
        "stopping": ("STOPPING", "warn"), "error": ("ERROR", "bad")}
DATA_CLASSES = [("private", "PRIVATE"), ("project", "PROJECT"), ("open", "OPEN")]
DATA_TIPS = {"private": "Nothing leaves this machine. Only local models are used.",
             "project": "Local models plus cloud services whose terms say your data is not used for training (Claude, ChatGPT, Groq, Cerebras...).",
             "open": "Also free tiers that may log or train on prompts (Gemini, Mistral, NVIDIA, OpenRouter free). Never used when a credential is detected in the prompt."}
DATA_TONES = {"private": "ok", "project": "accent", "open": "warn"}
FRUGAL = [("quality", "QUALITY"), ("balanced", "BALANCED"), ("frugal", "FRUGAL")]
FRUGAL_TIPS = {"quality": "Always the highest-scoring model, regardless of cost.",
               "balanced": "Best quality first; once models are benchmarked the cheapest one within 0.05 of the best.",
               "frugal": "Local first, then free tiers, then Claude from small to large. A cheaper model that fails verification is retried by the next one up."}
STRATEGY = {"quality": "measured", "balanced": "auto", "frugal": "frugal"}
STRATEGY_BACK = {"measured": "quality", "auto": "balanced", "frugal": "frugal", "config": "balanced"}


class MainWindow(QMainWindow):
    def __init__(self, controller, telemetry=None):
        super().__init__()
        self.controller = controller
        self.bg = queue.Queue()
        self._shown, self._loaded_ws, self._closing = set(), None, False
        self._prev_state, self._tele, self._tele_src, self.current = None, None, telemetry, "Mission"
        self.setWindowTitle("PRAXIS")
        self.setMinimumSize(1100, 760)
        self.resize(1360, 860)
        self._build()
        self._keys()
        self.show_page("Mission")
        if telemetry is not None:
            threading.Thread(target=self._telemetry_loop, daemon=True).start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(120)

    # ---- construction ----------------------------------------------------------------------
    def _build(self):
        root = Backdrop()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(0)
        outer.addWidget(self._header())
        body = QHBoxLayout(); body.setContentsMargins(0, 0, 0, 0); body.setSpacing(0)
        body.addWidget(self._rail())
        self.stack = QStackedWidget()
        self.pages = {}
        for name, _, cls in NAV:
            pg = cls(self)
            self.pages[name] = pg
            self.stack.addWidget(pg)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)
        self.status = QLabel(""); self.status.setObjectName("muted")
        self.status.setStyleSheet(f"background: rgba(5,9,17,0.9); padding: 5px 16px; color: {C['muted']}; font-size: 11px;")
        outer.addWidget(self.status)
        self.mission, self.timeline, self.fuel = self.pages["Mission"], self.pages["Timeline"], self.pages["Fuel"]

    def _header(self):
        bar = QFrame(); bar.setFixedHeight(64)
        bar.setStyleSheet(f"QFrame {{ background: rgba(5,9,17,0.92); border-bottom: 1px solid {C['line']}; }}")
        h = QHBoxLayout(bar); h.setContentsMargins(22, 0, 18, 0); h.setSpacing(14)
        mark = QLabel("PRAXIS"); mark.setStyleSheet(f"font-size: 19px; font-weight: 700; letter-spacing: 6px; color: {C['text']}; background: transparent; border: none;")
        h.addWidget(mark)
        self.pill = Chip("STARTING", "muted"); h.addWidget(self.pill)
        self.wslabel = ElidedLabel(""); self.wslabel.setStyleSheet("background: transparent; border: none; color: #7a8da6;")
        h.addWidget(self.wslabel, 1)
        for text, attr, opts, cur, tones, tips, slot in (
                ("DATA", "data_seg", DATA_CLASSES, "project", DATA_TONES, DATA_TIPS, self._set_data),
                ("FRUGALITY", "frugal_seg", FRUGAL, "balanced", {"quality": "violet", "balanced": "accent", "frugal": "ok"}, FRUGAL_TIPS, self._set_frugal)):
            col = QVBoxLayout(); col.setSpacing(2); col.setContentsMargins(0, 8, 0, 6)
            cap = QLabel(text); cap.setStyleSheet(f"font-size: 9px; letter-spacing: 2px; color: {C['dim']}; background: transparent; border: none;")
            seg = Segmented(opts, cur, tones, tips)
            seg.changed.connect(slot)
            setattr(self, attr, seg)
            col.addWidget(cap); col.addWidget(seg); h.addLayout(col)
        self.sandbox_badge = Chip("SANDBOX ?", "muted"); h.addWidget(self.sandbox_badge)
        self.cost = QLabel("$0.000"); self.cost.setStyleSheet(f"color: {C['muted']}; background: transparent; border: none; font-weight: 600;")
        h.addWidget(self.cost)
        self.stop_btn = QPushButton("STOP"); self.stop_btn.setObjectName("danger"); self.stop_btn.setEnabled(False)
        self.stop_btn.setToolTip("Kill in-flight model calls and restore the workspace  (Ctrl+.)")
        self.stop_btn.clicked.connect(self.stop)
        h.addWidget(self.stop_btn)
        return bar

    def _rail(self):
        rail = QFrame(); rail.setFixedWidth(232)
        rail.setStyleSheet(f"QFrame {{ background: rgba(8,14,22,0.88); border-right: 1px solid {C['line']}; }}")
        v = QVBoxLayout(rail); v.setContentsMargins(0, 14, 0, 14); v.setSpacing(0)
        self.nav = {}
        for name, icon, _ in NAV:
            b = NavButton(name, name, icon)
            b.clicked.connect(self.show_page)
            self.nav[name] = b
            v.addWidget(b)
        v.addSpacing(14)
        cap = QLabel("WORKSPACE"); cap.setStyleSheet(f"font-size: 9px; letter-spacing: 2px; color: {C['dim']}; background: transparent; border: none; padding-left: 20px;")
        v.addWidget(cap)
        self.ws_name = QLabel(""); self.ws_name.setWordWrap(True)
        self.ws_name.setStyleSheet("font-weight: 600; background: transparent; border: none; padding: 2px 20px 6px 20px;")
        v.addWidget(self.ws_name)
        ob = QPushButton("Open folder..."); ob.setObjectName("ghost"); ob.clicked.connect(self.open_folder)
        ob.setStyleSheet("margin: 0 16px;")
        v.addWidget(ob)
        self.recent = QListWidget(); self.recent.setFixedHeight(110)
        self.recent.setStyleSheet(f"QListWidget {{ background: transparent; border: none; color: {C['muted']}; font-size: 11px; padding: 4px 12px; }}"
                                  f"QListWidget::item:selected {{ background: {C['select']}; color: {C['text']}; }}")
        self.recent.itemClicked.connect(self._pick_recent)
        v.addWidget(self.recent)
        v.addStretch(1)
        g = QVBoxLayout(); g.setContentsMargins(20, 0, 20, 4); g.setSpacing(4)
        cap = QLabel("THIS MACHINE"); cap.setStyleSheet(f"font-size: 9px; letter-spacing: 2px; color: {C['dim']}; background: transparent; border: none;")
        g.addWidget(cap)
        self.bars = {k: FuelBar(k) for k in ("CPU", "RAM", "GPU", "VRAM")}
        for b in self.bars.values():
            g.addWidget(b)
        v.addLayout(g)
        return rail

    def _keys(self):
        QShortcut(QKeySequence("Ctrl+."), self, self.stop)
        for i, (name, _, _) in enumerate(NAV, 1):
            QShortcut(QKeySequence(f"Ctrl+{i}"), self, lambda n=name: self.show_page(n))

    # ---- actions ---------------------------------------------------------------------------
    def show_page(self, name):
        self.stack.setCurrentWidget(self.pages[name])
        for n, b in self.nav.items():
            b.set_active(n == name)
        self.current = name
        pg = self.pages[name]
        if hasattr(pg, "refresh"):
            pg.refresh()

    def note(self, text, level="muted"):
        self.status.setText(text)
        self.status.setStyleSheet(f"background: rgba(5,9,17,0.9); padding: 5px 16px; font-size: 11px; color: {C.get(level, C['muted'])};")

    def _set_data(self, key):
        self.controller.set_data_class(key)
        self.note(f"Data class: {key.upper()}. " + DATA_TIPS[key], "muted")
        self.fuel.refresh(force=True)

    def _set_frugal(self, key):
        self.controller.set_strategy(STRATEGY[key])
        self.note(f"{key.upper()}: " + FRUGAL_TIPS[key], "muted")
        self.fuel.refresh(force=True)

    def run_goal(self):
        text = self.mission.objective.toPlainText().strip()
        if not text:
            self.note("Type the outcome you want first.", "warn")
            return
        if self.controller.state != "idle":
            self.note("PRAXIS is busy or still starting up.", "warn")
            return
        if self._loaded_ws != self.controller.workspace:
            self._on_ready()   # snapshot the history BEFORE this goal's events begin
        self.show_page("Mission")
        self.mission.clear_feed()
        self.mission.core.set_caption("Goal accepted. Planning...")
        self.controller.submit(text, no_critic=not self.mission.critic.isChecked(), data_class=self.data_seg.current)

    def resume_goal(self):
        if not self.controller.resume():
            self.note("Nothing to resume.", "warn")

    def stop(self):
        if self.controller.state in ("working", "stopping"):
            self.controller.stop()
            self.note("Stopping: killing in-flight model calls and restoring the workspace...", "warn")

    def open_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a project folder", self.controller.workspace)
        if d:
            self._switch(d)

    def _pick_recent(self, item):
        path = item.data(Qt.UserRole)
        if path:
            self._switch(path)

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
        self.timeline.clear()
        self.mission.clear_feed()
        self._shown.clear()
        self._loaded_ws = None

    def add_key(self, preset):
        from ... import secrets
        dlg = KeyDialog(self, preset)
        if dlg.exec() and dlg.value:
            secrets.set(preset.id, dlg.value)     # stored under the provider id: exactly what config.build_stack and `praxis keys` look up
            if self.controller.reload():
                self._loaded_ws = None
                self.note(f"{preset.label} key saved. Reloading models...", "ok")
            else:
                self.note("Key saved. It takes effect the next time PRAXIS starts (a goal is running).", "warn")

    # ---- the heartbeat ----------------------------------------------------------------------
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
        u = c.poll() if state not in ("starting", "error") else None
        waiting = False
        if u is not None:
            self.mission.append_events(u.events)   # independent of each other: one failing must not starve the other
            self.timeline.add(u.events)
            waiting = bool(u.approvals) or u.view.status == "WAITING FOR YOU"
            self.mission.show_view(u.view, state, waiting and state == "working", c.nodes(), self._footer(state))
            self.cost.setText(f"${u.view.cost:.3f}")
            for req in u.approvals:
                if req.id not in self._shown:
                    self._shown.add(req.id)
                    self._ask(req)
            if state == "idle" and self._prev_state in ("working", "stopping"):
                self.mission.set_busy(False, bool(c.unfinished()))
        else:
            self.mission.show_view(View(), state, False, c.nodes(), "")
        label, tone = PILL.get(state, ("?", "muted"))
        if state == "working" and waiting:
            label, tone = "NEEDS YOU", "warn"
        self.pill.setText(label)
        self.pill.set_tone(tone)
        busy = state in ("working", "stopping")
        self.mission.run_btn.setEnabled(state == "idle")
        self.stop_btn.setEnabled(busy)
        if state == "error":
            self.note(c.error, "bad")
        elif c.notes:
            self.note(c.notes.pop(), "bad")
        self._drain_bg()
        self._paint_gauges()
        if self.current == "Fuel":
            self.fuel.refresh()
        self._prev_state = state

    def _footer(self, state):
        """Real settings, shown under the core: how it is routing, what data it may touch, how many models it can reach."""
        c, st = self.controller, self.controller.stack
        if st is None or state in ("starting", "error"):
            return ""
        return (f"ROUTING {STRATEGY_BACK.get(st.router.strategy, st.router.strategy).upper()}   \u00b7   "
                f"DATA {c.effective_data_class().upper()}   \u00b7   {len(st.providers)} MODELS")

    def _ask(self, req):
        dlg = ApprovalDialog(self, req)
        dlg.exec()
        self.controller.respond(req.id, dlg.answer)    # closing the dialog any other way is a refusal

    def _on_ready(self):
        c = self.controller
        self._loaded_ws = c.workspace
        self.timeline.clear()
        self.timeline.add(c.all_events())
        c.mark_read()
        self.wslabel.setText(c.workspace)
        self.ws_name.setText(os.path.basename(c.workspace) or c.workspace)
        self.setWindowTitle(f"PRAXIS - {os.path.basename(c.workspace) or c.workspace}")
        self.recent.clear()
        from PySide6.QtWidgets import QListWidgetItem
        for p in c.settings.recent:
            it = QListWidgetItem(os.path.basename(p.rstrip("/\\")) or p)
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            self.recent.addItem(it)
        info = c.info
        strong = info.get("sandbox_strong")
        self.sandbox_badge.setText(f"SANDBOX: {info.get('sandbox', '?').upper()}" if strong else "NO SANDBOX")
        self.sandbox_badge.set_tone("ok" if strong else "warn")
        st = c.stack
        if st is not None:   # the control mirrors the router, so what you see is what runs
            self.frugal_seg.set_current(STRATEGY_BACK.get(st.router.strategy, "balanced"))
            self.data_seg.set_current(c.effective_data_class())
        self.mission.set_busy(False, bool(c.unfinished()))
        n = len(info.get("providers", []))
        missing = ", ".join(sorted(info.get("skipped", {})))
        self.mission.hint = "" if n else (
            "No AI models are available yet. Install and sign in to Claude (claude), ChatGPT (codex) or Factory (droid), "
            f"install Ollama for local models, or add a free key on the Fuel page. Not found: {missing}.")
        self.note(f"Ready. {n} model instance(s) available." + ("" if n else "  None found: open Fuel, Models, or run `praxis doctor`."),
                  "muted" if n else "warn")
        if n:
            self.mission.core.set_caption(f"Ready. {n} model instance(s) available.")
        pg = self.pages[self.current]
        if hasattr(pg, "refresh"):
            pg.refresh(force=True) if self.current == "Fuel" else pg.refresh()

    def _drain_bg(self):
        models, system = self.pages["Models"], self.pages["System"]
        while True:
            try:
                msg = self.bg.get_nowait()
            except queue.Empty:
                return
            kind = msg[0]
            if kind == "pull":
                models.bar.setValue(int(msg[1]))
                models.msg.setText(f"{msg[2]}  {msg[1]:.0f}%")
            elif kind == "pull_done":
                models.pull_btn.setEnabled(True)
                models.msg.setText(f"{msg[2]} downloaded." if msg[1] else "Download did not report success.")
                models.refresh()
            elif kind == "pull_err":
                models.pull_btn.setEnabled(True)
                models.msg.setText(f"Download failed: {msg[1]}")
            elif kind == "bench_line":
                models.bench_log.append_line(msg[1], "bad" if "FAIL" in msg[1] or "ATTACK" in msg[1] else "info")
            elif kind == "bench_done":
                models.bench_btn.setEnabled(True)
                models.bench_log.append_line("Scores saved. The router now uses them.", "ok")
            elif kind == "sandbox":
                system.note.setText(f"sandbox: {msg[1]} ({'PROVEN' if msg[2] else 'not available'})")

    # ---- telemetry --------------------------------------------------------------------------
    def _telemetry_loop(self):
        while not self._closing:
            try:
                self._tele = self._tele_src.sample()
            except Exception:
                pass
            time.sleep(2.0)

    def _paint_gauges(self):
        t = self._tele
        if not t:
            return
        self.bars["CPU"].set(t["cpu"] / 100, f"{t['cpu']:.0f}%")
        self.bars["RAM"].set(t["ram_pct"] / 100, f"{t['ram_used_gb']:.1f} / {t['ram_total_gb']:.0f} GB")
        if t["gpus"]:
            g = t["gpus"][0]
            self.bars["GPU"].set(g["util"] / 100, f"{g['util']}%  {g['temp']}C")
            self.bars["VRAM"].set(g["vram_used_gb"] / max(g["vram_total_gb"], 0.1), f"{g['vram_used_gb']:.1f} / {g['vram_total_gb']:.0f} GB")
        else:
            self.bars["GPU"].set(0, "no GPU")
            self.bars["VRAM"].set(0, "-")

    # ---- shutdown ---------------------------------------------------------------------------
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
