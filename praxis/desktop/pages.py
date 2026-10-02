"""The five workspaces of the app. Every widget is fed from the controller / event log; none keeps its own truth."""
import json
import os
import queue
import threading
import tkinter as tk
import tkinter.messagebox as mb
import tkinter.ttk as ttk

from ..catalog import CATALOG, recommend
from ..hardware import GB, estimate_tokens_per_s, fits
from ..report import hardware_report, ollama_tips
from .theme import COL, STATE_COLOR
from .view import clock, summarize
from .widgets import LogText

ICON = {"pending": "○", "running": "▶", "waiting": "◔", "ran": "●", "verified": "✓",
        "denied": "⊘", "failed": "✗", "rolled back": "↺"}
STATE_TAG = {"verified": "ok", "ran": "info", "running": "accent", "waiting": "warn", "denied": "bad",
             "failed": "bad", "rolled back": "warn", "pending": "muted"}


def card(parent, **kw):
    return ttk.Frame(parent, style="Card.TFrame", padding=kw.pop("padding", 14), **kw)


def tree(parent, columns, widths, height=8, anchors=None):
    t = ttk.Treeview(parent, columns=[c[0] for c in columns], show="headings", height=height, selectmode="browse")
    for (cid, label), w in zip(columns, widths):
        t.heading(cid, text=label)
        t.column(cid, width=w, anchor=(anchors or {}).get(cid, "w"), stretch=(cid == columns[-1][0] or w > 160))
    for tag, key in (("ok", "ok"), ("warn", "warn"), ("bad", "bad"), ("info", "info"), ("muted", "muted"), ("accent", "accent")):
        t.tag_configure(tag, foreground=COL[key])
    return t


def vscroll(parent, widget):
    sb = ttk.Scrollbar(parent, orient="vertical", command=widget.yview)
    widget.configure(yscrollcommand=sb.set)
    return sb


class MissionPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=(20, 16, 20, 12))
        self.app, f = app, app.fonts
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=3)
        self.rowconfigure(4, weight=2)
        ttk.Label(self, text="Mission", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        obj = card(self)
        obj.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        obj.columnconfigure(0, weight=1)
        ttk.Label(obj, text="What outcome do you want?", style="Card.TLabel", foreground=COL["muted"]).grid(row=0, column=0, sticky="w")
        self.objective = tk.Text(obj, height=3, bg=COL["bg1"], fg=COL["text"], insertbackground=COL["accent"], relief="flat",
                                 wrap="word", font=f["ui"], padx=10, pady=8, highlightthickness=1,
                                 highlightbackground=COL["line"], highlightcolor=COL["accent_dim"])
        self.objective.grid(row=1, column=0, sticky="ew", pady=(6, 8))
        self.objective.bind("<Control-Return>", lambda e: (self.app.run_goal(), "break")[1])
        bar = ttk.Frame(obj, style="Card.TFrame")
        bar.grid(row=2, column=0, sticky="ew")
        self.run_btn = ttk.Button(bar, text="Run   Ctrl+Enter", style="Accent.TButton", command=app.run_goal)
        self.run_btn.pack(side="left")
        self.resume_btn = ttk.Button(bar, text="Resume interrupted goal", command=app.resume_goal)
        self.private = tk.BooleanVar(value=False)
        self.critic = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Private: local models only", variable=self.private).pack(side="right", padx=(10, 0))
        ttk.Checkbutton(bar, text="Second-opinion critic", variable=self.critic).pack(side="right", padx=(10, 0))

        hdr = ttk.Frame(self)
        hdr.grid(row=2, column=0, sticky="ew", pady=(2, 6))
        hdr.columnconfigure(0, weight=1)
        self.status = tk.Label(hdr, text="IDLE", font=f["big"], bg=COL["bg1"], fg=COL["muted"], anchor="w")
        self.status.grid(row=0, column=0, sticky="w")
        self.sub = tk.Label(hdr, text="Describe an outcome and press Run.", font=f["small"], bg=COL["bg1"],
                            fg=COL["muted"], anchor="w", justify="left", wraplength=900)
        self.sub.grid(row=1, column=0, sticky="w")

        pan = ttk.PanedWindow(self, orient="horizontal")
        pan.grid(row=3, column=0, sticky="nsew")
        left, right = ttk.Frame(pan), ttk.Frame(pan)
        pan.add(left, weight=3)
        pan.add(right, weight=2)
        for fr in (left, right):
            fr.rowconfigure(1, weight=1)
            fr.columnconfigure(0, weight=1)
        ttk.Label(left, text="PLAN", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 3))
        self.plan = tree(left, [("st", ""), ("id", "Step"), ("tool", "Tool"), ("what", "What"), ("cls", "Class")],
                         [38, 56, 110, 320, 52], anchors={"st": "center", "cls": "center"})
        self.plan.grid(row=1, column=0, sticky="nsew")
        vscroll(left, self.plan).grid(row=1, column=1, sticky="ns")
        ttk.Label(right, text="EVIDENCE", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 3), padx=(10, 0))
        self.evidence = tree(right, [("ok", ""), ("claim", "Check")], [36, 420])
        self.evidence.grid(row=1, column=0, sticky="nsew", padx=(10, 0))
        vscroll(right, self.evidence).grid(row=1, column=1, sticky="ns")

        ttk.Label(self, text="ACTIVITY", style="Muted.TLabel").grid(row=4, column=0, sticky="nw", pady=(10, 0))
        box = ttk.Frame(self)
        box.grid(row=5, column=0, sticky="nsew", pady=(3, 0))
        self.rowconfigure(5, weight=2)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.activity = LogText(box, f)
        self.activity.grid(row=0, column=0, sticky="nsew")
        vscroll(box, self.activity).grid(row=0, column=1, sticky="ns")
        self._plan_ids = None
        self.hint = ""   # shown while idle with no goal (e.g. "no models installed yet")

    # -- feed ------------------------------------------------------------------
    def append_events(self, events):
        for e in events:
            text, level = summarize(e)
            self.activity.append(f"{clock(e.ts)}  {text}", level)

    def show_view(self, v, state):
        label = v.status
        color = COL[STATE_COLOR.get(v.status, "muted")]
        if state == "starting":
            label, color = "STARTING", COL["muted"]
        elif state == "stopping":
            label, color = "STOPPING", COL["warn"]
        elif state == "error":
            label, color = "ERROR", COL["bad"]
        if label == "IDLE" and self.hint and not v.goal_text:
            label, color = "SETUP NEEDED", COL["warn"]
        self.status.configure(text=label, fg=color)
        done = sum(s.state in ("verified", "ran") for s in v.steps)
        bits = []
        if v.goal_text:
            bits.append(v.goal_text if len(v.goal_text) < 140 else v.goal_text[:137] + "...")
        if v.status == "RUNNING" and v.steps:
            bits.append(f"step {min(done + 1, len(v.steps))} of {len(v.steps)}")
        if v.status == "VERIFIED":
            bits.append(f"{sum(e['passed'] for e in v.evidence)} checks passed. Rollback point {v.checkpoint}.")
        if v.reason:
            bits.append(v.reason)
        if v.rolled_back and v.status in ("FAILED", "CANCELLED"):
            bits.append("Workspace restored: nothing half-done was left behind.")
        if v.tainted:
            bits.append("Plan was built from file contents, so it is capped at reversible actions.")
        if v.cost:
            bits.append(f"model cost so far ${v.cost:.3f}")
        idle_text = self.hint if (self.hint and not v.goal_text) else "Describe an outcome and press Run."
        self.sub.configure(text="  |  ".join(bits) if bits else idle_text)
        ids = tuple(s.id for s in v.steps)
        if ids != self._plan_ids:
            self.plan.delete(*self.plan.get_children())
            for s in v.steps:
                self.plan.insert("", "end", iid=s.id, values=("", s.id, s.tool, s.summary, ""))
            self._plan_ids = ids
        for s in v.steps:
            self.plan.item(s.id, values=(ICON.get(s.state, "?"), s.id, s.tool, s.summary, s.cls if s.cls else ""),
                           tags=(STATE_TAG.get(s.state, "muted"),))
        sig = [(e["claim"], e["passed"]) for e in v.evidence]
        if sig != getattr(self, "_ev_sig", None):
            self.evidence.delete(*self.evidence.get_children())
            for claim, ok in sig:
                self.evidence.insert("", "end", values=("✓" if ok else "✗", claim), tags=("ok" if ok else "bad",))
            self._ev_sig = sig

    def set_busy(self, busy, resumable):
        self.run_btn.configure(state="disabled" if busy else "normal")
        if resumable and not busy:
            self.resume_btn.pack(side="left", padx=(10, 0))
        else:
            self.resume_btn.pack_forget()


class TimelinePage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=(20, 16, 20, 12))
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=3)
        self.rowconfigure(3, weight=2)
        ttk.Label(self, text="Timeline", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        ttk.Button(bar, text="Why did you do that?", command=self.why).pack(side="left")
        ttk.Button(bar, text="Verify log integrity", command=self.verify).pack(side="left", padx=8)
        self.integrity = ttk.Label(bar, text="", style="Muted.TLabel")
        self.integrity.pack(side="left", padx=8)
        box = ttk.Frame(self)
        box.grid(row=2, column=0, sticky="nsew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.tree = tree(box, [("id", "#"), ("t", "Time"), ("actor", "Actor"), ("what", "What happened")],
                         [60, 80, 90, 700], height=14)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vscroll(box, self.tree).grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self.show_detail)
        self.detail = LogText(self, app.fonts)
        self.detail.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        self._events = {}

    def add(self, events):
        events = [e for e in events if e.id not in self._events]   # idempotent: never add the same event twice
        for e in events:
            text, level = summarize(e)
            self._events[e.id] = e
            self.tree.insert("", "end", iid=str(e.id), values=(e.id, clock(e.ts), e.actor, text), tags=(level,))
        if events:
            self.tree.see(str(events[-1].id))

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self._events.clear()

    def selected(self):
        sel = self.tree.selection()
        return int(sel[0]) if sel else None

    def show_detail(self, _=None):
        i = self.selected()
        if i in self._events:
            e = self._events[i]
            self.detail.replace(f"{e.type}   (actor {e.actor}, goal {e.goal_id})\nparents: {e.parent_ids}\nhash: {e.hash[:16]}...\n\n"
                                + json.dumps(e.payload, indent=2, default=str)[:6000], "info")

    def why(self):
        i = self.selected()
        if i is None:
            self.detail.replace("Select an event first.", "warn")
            return
        self.detail.replace("WHY: causal chain from this event back to your goal\n\n" + self.app.controller.why(i), "ok")

    def verify(self):
        ok, bad = self.app.controller.verify_log()
        self.integrity.configure(text="Log intact: every event's hash chains to the previous one." if ok
                                 else f"LOG TAMPERED at event {bad}", foreground=COL["ok"] if ok else COL["bad"])


class ModelsPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=(20, 16, 20, 12))
        self.app, f = app, app.fonts
        self.columnconfigure(0, weight=3, minsize=560)
        self.columnconfigure(1, weight=2)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="Models", style="Title.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        self.hw = LogText(self, f)
        self.hw.configure(height=9)
        self.hw.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 10))
        left, right = ttk.Frame(self), ttk.Frame(self)
        left.grid(row=2, column=0, sticky="nsew", padx=(0, 8))
        right.grid(row=2, column=1, sticky="nsew", padx=(8, 0))
        for fr in (left, right):
            fr.columnconfigure(0, weight=1)
        ttk.Label(left, text="RECOMMENDED FOR THIS MACHINE  (estimates; measure to confirm)", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.rec = tree(left, [("role", "Role"), ("tag", "Model"), ("size", "Size"), ("tps", "~tok/s"), ("have", "Installed")],
                        [64, 250, 74, 64, 80], height=6)
        self.rec.grid(row=1, column=0, sticky="ew", pady=(3, 6))
        row = ttk.Frame(left)
        row.grid(row=2, column=0, sticky="ew")
        self.pull_btn = ttk.Button(row, text="Download selected (Ollama)", style="Accent.TButton", command=self.pull)
        self.pull_btn.pack(side="left")
        ttk.Button(row, text="Refresh", command=self.refresh).pack(side="left", padx=8)
        self.pull_bar = ttk.Progressbar(left, mode="determinate", maximum=100)
        self.pull_bar.grid(row=3, column=0, sticky="ew", pady=(8, 2))
        self.pull_msg = ttk.Label(left, text="", style="Muted.TLabel", wraplength=520, justify="left")
        self.pull_msg.grid(row=4, column=0, sticky="w")
        ttk.Label(right, text="MEASURE EVERYTHING  (the router uses measured scores)", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        row2 = ttk.Frame(right)
        row2.grid(row=1, column=0, sticky="ew", pady=(3, 6))
        self.bench_btn = ttk.Button(row2, text="Run benchmark on all available models", command=self.bench)
        self.bench_btn.pack(side="left")
        ttk.Label(row2, text="stop after $", style="Muted.TLabel").pack(side="left", padx=(12, 3))
        self.cap = tk.StringVar(value="3.00")
        ttk.Entry(row2, textvariable=self.cap, width=6).pack(side="left")
        self.bench_log = LogText(right, f)
        self.bench_log.grid(row=2, column=0, sticky="nsew")
        right.rowconfigure(2, weight=1)
        self._picks = {}

    def refresh(self):
        st = self.app.controller.stack
        if st is None:
            return
        p = st.profile
        txt = hardware_report(p)
        tips = ollama_tips(p)
        self.hw.replace(txt + ("\n\n" + tips if tips else ""), "info")
        have = set()
        o = self._ollama()
        if o is not None:
            try:
                have = {m["name"] for m in o.models()}
            except Exception:
                pass
        r = recommend(p)
        self.rec.delete(*self.rec.get_children())
        self._picks = {}
        for role in ("daily", "fast", "deep"):
            x = r[role]
            if x:
                self._picks[role] = x
                self.rec.insert("", "end", iid=role, values=(role, x.model.tag, f"{x.model.size_gb:g} GB", f"{x.tps:.0f}",
                                                             "yes" if x.model.tag in have else "-"),
                                tags=("ok" if x.model.tag in have else "info",))
        if o is None:
            self.pull_msg.configure(text="Ollama is not running. Install it from ollama.com, start it, then Refresh.")

    def _ollama(self):
        st = self.app.controller.stack
        return next((p for p in (st.providers if st else []) if p.card.name.startswith("ollama")), None)

    def pull(self):
        sel = self.rec.selection()
        o = self._ollama()
        if not sel or o is None:
            self.pull_msg.configure(text="Select a row first (and make sure Ollama is running).")
            return
        pick = self._picks[sel[0]]
        if not mb.askyesno("Download model", f"Download {pick.model.tag} ({pick.model.size_gb:g} GB) with Ollama?\n\n"
                           "This uses your internet connection and disk space."):
            return
        self.pull_btn.configure(state="disabled")
        self.pull_msg.configure(text=f"Starting {pick.model.tag}...")

        def work():
            try:
                def prog(ev):
                    if ev.get("total") and ev.get("completed") is not None:
                        self.app.bg.put(("pull", 100.0 * ev["completed"] / ev["total"], ev.get("status", "")))
                ok = o.pull(pick.model.tag, prog)
                self.app.bg.put(("pull_done", ok, pick.model.tag))
            except Exception as e:
                self.app.bg.put(("pull_err", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def bench(self):
        st = self.app.controller.stack
        if st is None or self.app.controller.state != "idle":
            self.bench_log.append("Wait until PRAXIS is idle.", "warn")
            return
        try:
            cap = float(self.cap.get())
        except ValueError:
            cap = 3.0
        if not mb.askyesno("Benchmark", "This sends real test tasks to every available model, including your cloud "
                           f"subscriptions (usage counts against your plans).\n\nStops starting new models after ${cap:.2f}. Continue?"):
            return
        self.bench_btn.configure(state="disabled")
        self.bench_log.replace("", "info")

        def work():
            from ..bench import bench_all
            try:
                provs = [p for p in st.providers if getattr(p, "can_complete", True)]
                bench_all(provs, st.registry, 1, True, log=lambda s: self.app.bg.put(("bench_line", s)),
                          sandbox=st.sandbox, max_cost=cap)
                self.app.bg.put(("bench_done", None))
            except Exception as e:
                self.app.bg.put(("bench_line", f"error: {e}"))
                self.app.bg.put(("bench_done", None))
        threading.Thread(target=work, daemon=True).start()


class MemoryPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=(20, 16, 20, 12))
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="Memory", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        bar = ttk.Frame(self)
        bar.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        self.q = tk.StringVar()
        e = ttk.Entry(bar, textvariable=self.q, width=50)
        e.pack(side="left")
        e.bind("<Return>", lambda ev: self.search())
        ttk.Button(bar, text="Search past goals", command=self.search).pack(side="left", padx=8)
        ttk.Label(bar, text="Derived from the event log: failures are remembered with their reasons.", style="Muted.TLabel").pack(side="left", padx=8)
        box = ttk.Frame(self)
        box.grid(row=2, column=0, sticky="nsew")
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        self.tree = tree(box, [("st", "Outcome"), ("goal", "Goal"), ("why", "Reason")], [110, 420, 420], height=16)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vscroll(box, self.tree).grid(row=0, column=1, sticky="ns")

    def refresh(self, query=""):
        eps = self.app.controller.memory_search(query, k=50) if query else list(reversed(self.app.controller.memory_episodes()))
        self.tree.delete(*self.tree.get_children())
        for ep in eps:
            self.tree.insert("", "end", values=(ep["status"], ep["text"], ep["reason"][:200]),
                             tags=("ok" if ep["status"] == "VERIFIED" else "bad" if ep["status"] == "FAILED" else "warn",))

    def search(self):
        self.refresh(self.q.get().strip())


class SystemPage(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=(20, 16, 20, 12))
        self.app = app
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        ttk.Label(self, text="System", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self.facts = LogText(self, app.fonts)
        self.facts.configure(height=9)
        self.facts.grid(row=1, column=0, sticky="ew", pady=(8, 10))
        box = ttk.Frame(self)
        box.grid(row=2, column=0, sticky="nsew")
        box.rowconfigure(1, weight=1)
        box.columnconfigure(0, weight=1)
        ttk.Label(box, text="PROVIDERS", style="Muted.TLabel").grid(row=0, column=0, sticky="w")
        self.tree = tree(box, [("name", "Provider / model"), ("tier", "Tier"), ("priv", "Data"), ("score", "Measured"),
                               ("cost", "$/task"), ("tps", "tok/s"), ("status", "Status")],
                         [290, 80, 70, 90, 80, 70, 200], height=10)
        self.tree.grid(row=1, column=0, sticky="nsew")
        row = ttk.Frame(self)
        row.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(row, text="Re-run sandbox self-attack", command=self.retest).pack(side="left")
        self.note = ttk.Label(row, text="", style="Muted.TLabel")
        self.note.pack(side="left", padx=10)

    def refresh(self):
        c, st = self.app.controller, self.app.controller.stack
        if st is None:
            return
        sb = st.sandbox
        lines = [f"workspace   {c.workspace}", f"event log   {c.db_path}",
                 f"machine     {st.profile.describe()}",
                 f"sandbox     {sb.kind.upper()}  " + ("(proven: no outside writes, no network, PRAXIS state hidden)" if sb.strong
                                                     else "NONE - running code needs your approval every time"),
                 "skipped     " + (", ".join(f"{k} ({v[:40]})" for k, v in st.skipped.items()) or "nothing")]
        self.facts.replace("\n".join(lines), "info")
        self.tree.delete(*self.tree.get_children())
        now = st.router.clock()
        for p in st.providers:
            n = p.card.name
            e = st.registry.data.get(n, {}).get("planning", {})
            cool = st.router.cooling.get(n, 0) - now
            status = f"resting {int(cool / 60) + 1} min" if cool > 0 else ("delegate-only" if not getattr(p, "can_complete", True) else "ready")
            self.tree.insert("", "end", values=(n, getattr(p, "tier", "") or "", p.card.privacy,
                                                f"{e['score']:.2f}" if e else "-", f"{e.get('cost_per_task', 0):.4f}" if e else "-",
                                                e.get("tokens_per_s") or "-", status),
                             tags=("warn" if cool > 0 else "ok",))

    def retest(self):
        from ..sandbox import detect
        self.note.configure(text="attacking the sandbox...")

        def work():
            sb = detect()
            self.app.bg.put(("sandbox", sb.kind, sb.strong))
        threading.Thread(target=work, daemon=True).start()
