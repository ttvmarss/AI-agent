"""The PRAXIS desktop shell: one native window, five workspaces, a permanent kill switch."""
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb
import tkinter.ttk as ttk

from . import theme
from .dialogs import ApprovalDialog
from .pages import MemoryPage, MissionPage, ModelsPage, SystemPage, TimelinePage
from .theme import COL
from .view import View
from .widgets import Bar, NavItem, Reactor

NAV = [("Mission", MissionPage), ("Timeline", TimelinePage), ("Models", ModelsPage),
       ("Memory", MemoryPage), ("System", SystemPage)]
PILL = {"starting": ("STARTING", "muted"), "idle": ("READY", "ok"), "working": ("WORKING", "accent"),
        "stopping": ("STOPPING", "warn"), "error": ("ERROR", "bad")}


class App:
    def __init__(self, controller, telemetry=None, root=None):
        if root is None:
            theme.dpi_awareness()
        self.root = root or tk.Tk()
        self.controller = controller
        self.fonts = theme.setup(self.root)
        self.bg = queue.Queue()
        self._shown, self._loaded_ws, self._closing = set(), None, False
        self._prev_state, self._tele, self._tele_src = None, None, telemetry
        self.root.title("PRAXIS")
        self.root.minsize(1040, 660)
        self.root.geometry(controller.settings.geometry or "1320x840")
        self._build()
        self._bind_keys()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        if telemetry is not None:
            threading.Thread(target=self._telemetry_loop, daemon=True).start()
        self.show("Mission")
        self.root.after(80, self._tick)

    # ---- construction -------------------------------------------------------------
    def _build(self):
        f, r = self.fonts, self.root
        r.columnconfigure(1, weight=1)
        r.rowconfigure(1, weight=1)
        top = tk.Frame(r, bg=COL["bg0"], height=60)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")
        top.grid_propagate(False)
        top.columnconfigure(3, weight=1)
        self.reactor = Reactor(top, 44)
        self.reactor.grid(row=0, column=0, padx=(16, 8), pady=8)
        tk.Label(top, text="PRAXIS", font=("TkDefaultFont", 15, "bold"), bg=COL["bg0"], fg=COL["text"]).grid(row=0, column=1)
        self.pill = tk.Label(top, text="STARTING", font=f["small"], bg=COL["bg2"], fg=COL["muted"], padx=10, pady=3)
        self.pill.grid(row=0, column=2, padx=14)
        self.wslabel = tk.Label(top, text="", font=f["small"], bg=COL["bg0"], fg=COL["muted"], anchor="w")
        self.wslabel.grid(row=0, column=3, sticky="w")
        self.sandbox_badge = tk.Label(top, text="", font=f["small"], bg=COL["bg0"], fg=COL["muted"])
        self.sandbox_badge.grid(row=0, column=4, padx=10)
        self.cost = tk.Label(top, text="$0.000", font=f["small"], bg=COL["bg0"], fg=COL["muted"])
        self.cost.grid(row=0, column=5, padx=10)
        self.stop_btn = ttk.Button(top, text="STOP   Ctrl+.", style="Danger.TButton", command=self.stop)
        self.stop_btn.grid(row=0, column=6, padx=(6, 16))
        self.stop_btn.state(["disabled"])
        # left rail
        rail = tk.Frame(r, bg=COL["bg1"], width=230)
        rail.grid(row=1, column=0, sticky="ns")
        rail.grid_propagate(False)
        rail.rowconfigure(20, weight=1)
        self.nav = {}
        for i, (name, _) in enumerate(NAV):
            n = NavItem(rail, name, lambda nm=name: self.show(nm), f)
            n.grid(row=i, column=0, sticky="ew")
            self.nav[name] = n
        tk.Frame(rail, bg=COL["line"], height=1).grid(row=10, column=0, sticky="ew", pady=12, padx=14)
        tk.Label(rail, text="WORKSPACE", font=f["small"], bg=COL["bg1"], fg=COL["muted"], anchor="w").grid(row=11, column=0, sticky="ew", padx=16)
        self.ws_name = tk.Label(rail, text="", font=f["ui_b"], bg=COL["bg1"], fg=COL["text"], anchor="w", wraplength=190, justify="left")
        self.ws_name.grid(row=12, column=0, sticky="ew", padx=16, pady=(2, 6))
        ttk.Button(rail, text="Open folder...", style="Ghost.TButton", command=self.open_folder).grid(row=13, column=0, sticky="w", padx=8)
        self.recent = tk.Listbox(rail, height=5, bg=COL["bg1"], fg=COL["muted"], selectbackground=COL["select"],
                                 selectforeground=COL["text"], relief="flat", highlightthickness=0, font=f["small"],
                                 activestyle="none", borderwidth=0)
        self.recent.grid(row=14, column=0, sticky="ew", padx=14, pady=(4, 0))
        self.recent.bind("<<ListboxSelect>>", self._pick_recent)
        gauges = tk.Frame(rail, bg=COL["bg1"])
        gauges.grid(row=21, column=0, sticky="ew", padx=16, pady=(0, 14))
        tk.Label(gauges, text="THIS MACHINE", font=f["small"], bg=COL["bg1"], fg=COL["muted"], anchor="w").pack(fill="x", pady=(0, 4))
        self.bars = {k: Bar(gauges, k) for k in ("CPU", "RAM", "GPU", "VRAM")}
        for b in self.bars.values():
            b.pack(pady=1)
        # content
        self.content = tk.Frame(r, bg=COL["bg1"])
        self.content.grid(row=1, column=1, sticky="nsew")
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)
        self.pages = {}
        for name, cls in NAV:
            pg = cls(self.content, self)
            pg.grid(row=0, column=0, sticky="nsew")
            self.pages[name] = pg
        self.mission, self.timeline = self.pages["Mission"], self.pages["Timeline"]
        self.status = tk.Label(r, text="", anchor="w", font=f["small"], bg=COL["bg0"], fg=COL["muted"], padx=14, pady=4)
        self.status.grid(row=2, column=0, columnspan=2, sticky="ew")

    def _bind_keys(self):
        r = self.root
        r.bind("<Control-period>", lambda e: self.stop())
        for i, (name, _) in enumerate(NAV, 1):
            r.bind(f"<Control-Key-{i}>", lambda e, n=name: self.show(n))

    # ---- actions ---------------------------------------------------------------------
    def show(self, name):
        self.pages[name].tkraise()
        for n, w in self.nav.items():
            w.set_active(n == name)
        self.current = name
        if name == "Models":
            self.pages["Models"].refresh()
        elif name == "Memory":
            self.pages["Memory"].refresh()
        elif name == "System":
            self.pages["System"].refresh()

    def note(self, text, level="muted"):
        self.status.configure(text=text, fg=COL.get(level, COL["muted"]))

    def run_goal(self):
        text = self.mission.objective.get("1.0", "end").strip()
        if not text:
            self.note("Type the outcome you want first.", "warn")
            return
        if self.controller.state != "idle":
            self.note("PRAXIS is busy or still starting up.", "warn")
            return
        if self._loaded_ws != self.controller.workspace:
            self._on_ready()  # snapshot the history BEFORE this goal's events begin
        self.show("Mission")
        self.mission.activity.replace("", "info")
        self.controller.submit(text, private=self.mission.private.get(), no_critic=not self.mission.critic.get())

    def resume_goal(self):
        if not self.controller.resume():
            self.note("Nothing to resume.", "warn")

    def stop(self):
        if self.controller.state in ("working", "stopping"):
            self.controller.stop()
            self.note("Stopping: killing in-flight model calls and restoring the workspace...", "warn")

    def open_folder(self):
        d = fd.askdirectory(title="Choose a project folder", initialdir=self.controller.workspace)
        if d:
            self._switch(d)

    def _pick_recent(self, _):
        sel = self.recent.curselection()
        if sel and sel[0] < len(getattr(self, "_recent_paths", [])):
            self._switch(self._recent_paths[sel[0]])

    def _switch(self, path):
        if os.path.realpath(path) == self.controller.workspace:
            return
        if not self.controller.open_workspace(path):
            if self.controller.refusal:
                mb.showwarning("Choose a project folder", self.controller.refusal)
                self.note(self.controller.refusal, "warn")
            else:
                self.note("Finish or stop the current goal before switching folders.", "warn")
            return
        self.timeline.clear()
        self.mission.activity.replace("", "info")
        self._shown.clear()
        self._loaded_ws = None

    # ---- the heartbeat ------------------------------------------------------------------
    def _tick(self):
        if self._closing:
            return
        try:
            self._update()
        except Exception as e:  # a rendering bug must never take the whole window down
            self.note(f"UI error: {type(e).__name__}: {e}", "bad")
        self.root.after(120, self._tick)

    def _update(self):
        c = self.controller
        state = c.state
        if state in ("idle", "working", "stopping") and self._loaded_ws != c.workspace:
            self._on_ready()  # BEFORE the first poll (a poll consumes events); tied to "stack built", not to idle
        u = c.poll() if state not in ("starting", "error") else None
        if u is not None:
            self.mission.append_events(u.events)   # independent of each other: one failing must not starve the other
            self.timeline.add(u.events)
            self.mission.show_view(u.view, state)
            self.cost.configure(text=f"${u.view.cost:.3f}")
            for req in u.approvals:
                if req.id not in self._shown:
                    self._shown.add(req.id)
                    ApprovalDialog(self, req, self._answer)
            waiting = bool(u.approvals) or u.view.status == "WAITING FOR YOU"
            mode = "waiting" if waiting and state == "working" else state
            if u.view.status == "VERIFIED" and state == "idle" and self._prev_state == "working":
                mode = "ok"
            self.reactor.set_mode(mode if mode != "idle" or self.reactor.mode != "ok" else "ok")
            if state == "idle" and self._prev_state in ("working", "stopping"):
                self.mission.set_busy(False, bool(c.unfinished()))
                self.reactor.set_mode("idle" if u.view.status != "VERIFIED" else "ok")
        else:
            self.mission.show_view(View(), state)
            self.reactor.set_mode(state)
        label, tone = PILL.get(state, ("?", "muted"))
        if state == "working" and u is not None and (u.approvals or u.view.status == "WAITING FOR YOU"):
            label, tone = "NEEDS YOU", "warn"
        self.pill.configure(text=label, fg=COL[tone])
        busy = state in ("working", "stopping")
        self.mission.run_btn.configure(state="disabled" if busy or state != "idle" else "normal")
        self.stop_btn.state(["!disabled"] if busy else ["disabled"])
        self.reactor.tick()
        if state == "error":
            self.note(c.error, "bad")
        elif c.notes:
            self.note(c.notes.pop(), "bad")
        self._drain_bg()
        self._paint_gauges()
        self._prev_state = state

    def _on_ready(self):
        c = self.controller
        self._loaded_ws = c.workspace
        self.timeline.clear()
        self.timeline.add(c.all_events())
        c.mark_read()
        self.wslabel.configure(text=c.workspace)
        self.ws_name.configure(text=os.path.basename(c.workspace) or c.workspace)
        self.root.title(f"PRAXIS - {os.path.basename(c.workspace) or c.workspace}")
        self.recent.delete(0, "end")
        self._recent_paths = list(c.settings.recent)
        for p in self._recent_paths:  # show the folder name; the full path is what gets opened
            self.recent.insert("end", os.path.basename(p.rstrip("/\\")) or p)
        info = c.info
        self.sandbox_badge.configure(text=f"sandbox: {info.get('sandbox', '?')}" + ("" if info.get("sandbox_strong") else " (none)"),
                                     fg=COL["ok"] if info.get("sandbox_strong") else COL["warn"])
        self.mission.set_busy(False, bool(c.unfinished()))
        n = len(info.get("providers", []))
        missing = ", ".join(sorted(info.get("skipped", {})))
        self.mission.hint = "" if n else (
            "No AI models are available yet. Install and sign in to at least one of: Claude (claude), ChatGPT (codex), "
            "Factory (droid), or install Ollama for local models. Open Models to see what to download for this machine, "
            f"then restart PRAXIS. Not found: {missing}." )
        self.note(f"Ready. {n} model instance(s) available." + ("" if n else "  None found: open Models or run `praxis doctor`."),
                  "muted" if n else "warn")
        if getattr(self, "current", "") in ("Models", "Memory", "System"):
            self.show(self.current)

    def _answer(self, req, ok):
        self.controller.respond(req.id, ok)

    def _drain_bg(self):
        models = self.pages["Models"]
        while True:
            try:
                msg = self.bg.get_nowait()
            except queue.Empty:
                return
            kind = msg[0]
            if kind == "pull":
                models.pull_bar.configure(value=msg[1])
                models.pull_msg.configure(text=f"{msg[2]}  {msg[1]:.0f}%")
            elif kind == "pull_done":
                models.pull_btn.configure(state="normal")
                models.pull_msg.configure(text=f"{msg[2]} downloaded." if msg[1] else "Download did not report success.")
                models.refresh()
            elif kind == "pull_err":
                models.pull_btn.configure(state="normal")
                models.pull_msg.configure(text=f"Download failed: {msg[1]}")
            elif kind == "bench_line":
                models.bench_log.append(msg[1], "bad" if "FAIL" in msg[1] or "ATTACK" in msg[1] else "info")
            elif kind == "bench_done":
                models.bench_btn.configure(state="normal")
                models.bench_log.append("Scores saved. The router now uses them.", "ok")
            elif kind == "sandbox":
                self.pages["System"].note.configure(text=f"sandbox: {msg[1]} ({'PROVEN' if msg[2] else 'not available'})")

    # ---- telemetry -------------------------------------------------------------------------
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
        self.bars["CPU"].set(t["cpu"], f"{t['cpu']:.0f}%")
        self.bars["RAM"].set(t["ram_pct"], f"{t['ram_used_gb']:.1f} / {t['ram_total_gb']:.0f} GB")
        if t["gpus"]:
            g = t["gpus"][0]
            self.bars["GPU"].set(g["util"], f"{g['util']}%  {g['temp']}C")
            self.bars["VRAM"].set(100.0 * g["vram_used_gb"] / max(g["vram_total_gb"], 0.1),
                                  f"{g['vram_used_gb']:.1f} / {g['vram_total_gb']:.0f} GB")
        else:
            self.bars["GPU"].set(0, "no GPU")
            self.bars["VRAM"].set(0, "-")

    # ---- shutdown ----------------------------------------------------------------------------
    def close(self):
        c = self.controller
        if c.state in ("working", "stopping"):
            if not mb.askyesno("PRAXIS is working", "Stop the current goal and exit?\n\nThe workspace will be restored to its previous state."):
                return
            c.stop()
            end = time.time() + 8
            while c.state != "idle" and time.time() < end:
                self.root.update()
                time.sleep(0.05)
        self._closing = True
        try:
            c.settings.geometry = self.root.winfo_geometry()
            c.settings.save()
        except Exception:
            pass
        self.root.destroy()
