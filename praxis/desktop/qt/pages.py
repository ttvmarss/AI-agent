"""The six workspaces. Everything shown is a projection of the event log, the router, the usage tracker and the registry."""
import json
import threading
import webbrowser

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QCheckBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSplitter, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ...catalog import recommend
from ...free_tiers import PRESETS, preset
from ...report import hardware_report, ollama_tips
from ..view import clock, summarize
from .theme import C, COST_NAME, PRIVACY_NAME, STATE_COLOR, qc
from .widgets import Chip, CoreView, FuelBar, LogView, StepGraph, card, pressure_color

LEVEL = {"ok": "ok", "warn": "warn", "bad": "bad", "info": "muted"}


def make_tree(headers, widths=None, stretch=-1):
    t = QTreeWidget()
    t.setHeaderLabels(headers)
    t.setRootIsDecorated(False)
    t.setAlternatingRowColors(True)
    t.setUniformRowHeights(True)
    t.setFocusPolicy(Qt.NoFocus)
    hdr = t.header()
    hdr.setStretchLastSection(True)
    for i, w in enumerate(widths or []):
        t.setColumnWidth(i, w)
    return t


def add_row(tree, values, tone=None, key=None):
    it = QTreeWidgetItem([str(v) for v in values])
    if tone:
        for i in range(len(values)):
            it.setForeground(i, QBrush(QColor(C.get(LEVEL.get(tone, tone), tone))))
    if key is not None:
        it.setData(0, Qt.UserRole, key)
    tree.addTopLevelItem(it)
    return it


def title(text, sub=""):
    box = QVBoxLayout(); box.setSpacing(2)
    h = QLabel(text); h.setObjectName("h1"); box.addWidget(h)
    if sub:
        s = QLabel(sub); s.setObjectName("muted"); s.setWordWrap(True); box.addWidget(s)   # wrapping labels can shrink with the window
    return box


class _Objective(QPlainTextEdit):
    submit = Signal()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and e.modifiers() & Qt.ControlModifier:
            self.submit.emit()
            return
        super().keyPressEvent(e)


class MissionPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.hint = ""
        lay = QVBoxLayout(self); lay.setContentsMargins(22, 12, 22, 14); lay.setSpacing(8)
        self.core = CoreView(); lay.addWidget(self.core, 5)
        self.graph = StepGraph(); lay.addWidget(self.graph, 0)
        split = QSplitter(Qt.Horizontal); split.setChildrenCollapsible(False)
        lc, rc = card("cardflat"), card("cardflat")
        for fr, name in ((lc, "ACTIVITY"), (rc, "EVIDENCE")):
            l = QVBoxLayout(fr); l.setContentsMargins(14, 10, 14, 12); l.setSpacing(6)
            h = QLabel(name); h.setObjectName("h2"); l.addWidget(h)
        self.activity = LogView(); lc.layout().addWidget(self.activity)
        self.evidence = make_tree(["", "Check"], [34]); rc.layout().addWidget(self.evidence)
        split.addWidget(lc); split.addWidget(rc); split.setSizes([620, 380]); split.setMinimumHeight(110)
        lay.addWidget(split, 3)
        bar = card("card"); bl = QVBoxLayout(bar); bl.setContentsMargins(12, 10, 12, 10); bl.setSpacing(6)
        self.objective = _Objective()
        self.objective.setPlaceholderText("What outcome do you want?   e.g. \"Fix the failing tests in calc.py without editing the tests\"")
        self.objective.setFixedHeight(54)
        self.objective.submit.connect(app.run_goal)
        bl.addWidget(self.objective)
        row = QHBoxLayout()
        self.run_btn = QPushButton("Run   Ctrl+Enter"); self.run_btn.setObjectName("primary"); self.run_btn.clicked.connect(app.run_goal)
        self.resume_btn = QPushButton("Resume interrupted goal"); self.resume_btn.clicked.connect(app.resume_goal); self.resume_btn.hide()
        self.critic = QCheckBox("Second-opinion critic"); self.critic.setChecked(True)
        self.critic.setToolTip("A different vendor reviews the plan before anything runs (skipped when only one vendor is available).")
        row.addWidget(self.run_btn); row.addWidget(self.resume_btn); row.addStretch(); row.addWidget(self.critic)
        bl.addLayout(row)
        lay.addWidget(bar, 0)
        self._sig = None
        self._ev_sig = None

    def append_events(self, events):
        for e in events:
            text, level = summarize(e)
            self.activity.append_line(f"{clock(e.ts)}  {text}", level)

    def clear_feed(self):
        self.activity.clear()

    def show_view(self, v, state, waiting, nodes):
        """Map real state onto the core: its colour, progress ring, text, and which provider is lit."""
        done = sum(s.state in ("verified", "ran") for s in v.steps)
        prog = done / len(v.steps) if v.steps else 0.0
        sub = ""
        if state == "starting":
            mode, ttl, sub = "starting", "STARTING", "detecting hardware, tools and sandbox"
        elif state == "error":
            mode, ttl, sub = "bad", "ERROR", self.app.controller.error[:90]
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
        elif self.hint and not v.goal_text:
            mode, ttl, sub = "stopped", "SETUP NEEDED", "no AI models yet: add a free key on Fuel, or sign in to Claude / Codex"   # full text: status bar
        else:
            mode, ttl, sub = "idle", "READY", "describe an outcome below"
        self.core.set_state(mode, prog, ttl, sub)
        self.core.set_nodes(nodes)
        self.core.set_active(v.active_provider)
        sig = tuple((s.id, s.state) for s in v.steps)
        if sig != self._sig:
            self.graph.set_steps(v.steps)
            self._sig = sig
        esig = tuple((e["claim"], e["passed"]) for e in v.evidence)
        if esig != self._ev_sig:
            self.evidence.clear()
            for e in v.evidence:
                add_row(self.evidence, ["✓" if e["passed"] else "✗", e["claim"]], "ok" if e["passed"] else "bad")
            self._ev_sig = esig

    def set_busy(self, busy, resumable):
        self.run_btn.setEnabled(not busy)
        self.resume_btn.setVisible(bool(resumable and not busy))


class TimelinePage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self._events = app, {}
        lay = QVBoxLayout(self); lay.setContentsMargins(26, 18, 26, 18); lay.setSpacing(10)
        lay.addLayout(title("Timeline", "Every action, in order, hash-chained. Select one and ask why."))
        row = QHBoxLayout()
        b1 = QPushButton("Why did you do that?"); b1.clicked.connect(self.why)
        b2 = QPushButton("Verify log integrity"); b2.clicked.connect(self.verify)
        self.integrity = QLabel(""); self.integrity.setObjectName("muted")
        row.addWidget(b1); row.addWidget(b2); row.addWidget(self.integrity); row.addStretch()
        lay.addLayout(row)
        self.tree = make_tree(["#", "Time", "Actor", "What happened"], [60, 80, 90])
        self.tree.itemSelectionChanged.connect(self.show_detail)
        lay.addWidget(self.tree, 3)
        self.detail = LogView(); lay.addWidget(self.detail, 2)

    def add(self, events):
        events = [e for e in events if e.id not in self._events]   # idempotent
        for e in events:
            text, level = summarize(e)
            self._events[e.id] = e
            add_row(self.tree, [e.id, clock(e.ts), e.actor, text], level, key=e.id)
        if events:
            self.tree.scrollToBottom()

    def clear(self):
        self.tree.clear()
        self._events.clear()

    def selected(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def show_detail(self):
        i = self.selected()
        if i in self._events:
            e = self._events[i]
            self.detail.replace_all(f"{e.type}   (actor {e.actor}, goal {e.goal_id})\nparents: {e.parent_ids}\nhash: {e.hash[:16]}...\n\n"
                                    + json.dumps(e.payload, indent=2, default=str)[:6000], "info")

    def why(self):
        i = self.selected()
        if i is None:
            self.detail.replace_all("Select an event first.", "warn")
            return
        self.detail.replace_all("WHY: causal chain from this event back to your goal\n\n" + self.app.controller.why(i), "ok")

    def verify(self):
        ok, bad = self.app.controller.verify_log()
        self.integrity.setText("Log intact: every event's hash chains to the previous one." if ok else f"LOG TAMPERED at event {bad}")
        self.integrity.setStyleSheet(f"color: {C['ok'] if ok else C['bad']};")


class FuelPage(QWidget):
    """Where the tokens go. Usage and budgets per provider, resting/blocked state, and the failover ladder."""

    def __init__(self, app):
        super().__init__()
        self.app, self._sig = app, None
        outer = QVBoxLayout(self); outer.setContentsMargins(26, 18, 26, 18); outer.setSpacing(10)
        outer.addLayout(title("Fuel", "How much of each model's allowance is spent, and where PRAXIS goes when one runs out."))
        self.ladder = card("card"); ll = QVBoxLayout(self.ladder); ll.setContentsMargins(16, 12, 16, 14); ll.setSpacing(6)
        h = QLabel("FAILOVER LADDER"); h.setObjectName("h2"); ll.addWidget(h)
        self.ladder_text = QLabel(); self.ladder_text.setWordWrap(True); self.ladder_text.setTextFormat(Qt.RichText)
        ll.addWidget(self.ladder_text)
        self.ladder_note = QLabel(); self.ladder_note.setObjectName("muted"); self.ladder_note.setWordWrap(True)
        ll.addWidget(self.ladder_note)
        outer.addWidget(self.ladder)
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
        self.host = QWidget(); self.grid = QGridLayout(self.host); self.grid.setSpacing(12); self.grid.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.host); outer.addWidget(scroll, 1)

    def refresh(self, force=False):
        c = self.app.controller
        st = c.stack
        if st is None:
            return
        nodes = c.nodes()
        chain = c.chain()
        sig = json.dumps([[n["family"], round(n["pressure"], 2), n["cooling_s"] // 30, n["blocked"],
                           [m["score"] for m in n["models"]]] for n in nodes] + [chain, sorted(st.skipped), c.effective_data_class(),
                                                                                 st.router.strategy], default=str)
        if sig == self._sig and not force:
            return
        self._sig = sig
        arrows = f' <span style="color:{C["dim"]}"> &rarr; </span> '
        names = []
        for m in chain:
            fam = m.split("/")[0]
            nd = next((n for n in nodes if n["family"] == fam), None)
            col = C[{0: "ok", 1: "accent", 2: "violet"}.get(nd["cost_class"], "muted")] if nd else C["muted"]
            names.append(f'<span style="color:{col}; font-weight:600">{m.split("/", 1)[-1] if "/" in m else m}</span>')
        self.ladder_text.setText(arrows.join(names) if names else f'<span style="color:{C["warn"]}">no model can serve this data class right now</span>')
        s = st.router.strategy
        self.ladder_note.setText({"frugal": "Frugal: local first, then free tiers, then Claude from small to large. A cheaper model that fails verification is retried by the next one up.",
                                  "auto": "Balanced: best quality first; once models are benchmarked the cheapest one within 0.05 of the best wins.",
                                  "measured": "Quality: the highest-scoring model first, regardless of cost.",
                                  "config": "Fixed order from your config."}.get(s, s)
                                 + f"   Data class: {c.effective_data_class().upper()}.")
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.setParent(None)   # detach NOW: deleteLater alone leaves the stale card painted and findable until the loop turns
                w.deleteLater()
        cards = [self._node_card(n) for n in nodes] + [self._missing_card(k, v) for k, v in sorted(st.skipped.items())]
        for i, w in enumerate(cards):
            self.grid.addWidget(w, i // 2, i % 2)
        self.grid.setRowStretch(len(cards) // 2 + 1, 1)

    def _node_card(self, n):
        f = card("card"); l = QVBoxLayout(f); l.setContentsMargins(16, 14, 16, 14); l.setSpacing(6)
        head = QHBoxLayout()
        name = QLabel(n["family"]); name.setStyleSheet("font-size: 16px; font-weight: 700;"); head.addWidget(name)
        head.addWidget(Chip(PRIVACY_NAME.get(n["privacy"], n["privacy"]), "ok" if n["privacy"] == "local" else "accent" if n["privacy"] == "cloud" else "warn"))
        if COST_NAME.get(n["cost_class"]) != PRIVACY_NAME.get(n["privacy"]):    # "LOCAL LOCAL" says nothing twice
            head.addWidget(Chip(COST_NAME.get(n["cost_class"], ""), {0: "ok", 1: "accent", 2: "violet"}.get(n["cost_class"], "muted")))
        head.addStretch()
        if n["blocked"]:
            head.addWidget(Chip("BLOCKED BY DATA CLASS", "dim"))
        elif n["cooling_s"]:
            head.addWidget(Chip(f"RESTING {n['cooling_s'] // 60 + 1} MIN", "warn"))
        elif n["delegate_only"]:
            head.addWidget(Chip("DELEGATE-ONLY", "warn"))
        else:
            head.addWidget(Chip("READY", "ok"))
        l.addLayout(head)
        for m in n["models"]:
            bits = [m["name"].split("/", 1)[-1] if "/" in m["name"] else m["name"]]
            if m["tier"]:
                bits.append(f"[{m['tier']}]")
            if m["score"] is not None:
                bits.append(f"quality {m['score']:.2f}")
            if m["cost"]:
                bits.append(f"${m['cost']:.3f}/task")
            if m["tps"]:
                bits.append(f"{m['tps']:.0f} tok/s")
            ml = QLabel("   ".join(bits)); ml.setObjectName("muted"); l.addWidget(ml)
        bar = FuelBar("budget spent")
        if n["pressure"]:
            bar.set(n["pressure"], f"{n['pressure'] * 100:.0f}%")
        else:
            bar.set(0, "no budget set" if n["cost_class"] == 2 else "within limits", "ok")
        l.addWidget(bar)
        u = n["usage"]
        line = "   |   ".join(f"{w}: {u[w]['calls']} calls" + (f", ${u[w]['cost']:.2f}" if u[w]["cost"] else "") for w in ("5h", "24h", "7d"))
        ul = QLabel(line); ul.setObjectName("muted"); ul.setStyleSheet(f"color: {C['dim']}; font-size: 11px;"); l.addWidget(ul)
        return f

    def _missing_card(self, pid, reason):
        f = card("cardflat"); l = QVBoxLayout(f); l.setContentsMargins(16, 14, 16, 14); l.setSpacing(6)
        pr = next((p for p in PRESETS if p.id == pid), None)
        head = QHBoxLayout()
        name = QLabel(pid); name.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {C['muted']};"); head.addWidget(name)
        if pr:
            head.addWidget(Chip("TRUSTED" if pr.privacy == "cloud" else "OPEN", "accent" if pr.privacy == "cloud" else "warn"))
            head.addWidget(Chip("FREE", "accent"))
        head.addStretch(); head.addWidget(Chip("NOT SET UP", "dim")); l.addLayout(head)
        msg = QLabel(pr.caveat if pr and "no API key" in reason else reason); msg.setObjectName("muted"); msg.setWordWrap(True); l.addWidget(msg)
        if pr and "no API key" in reason:
            row = QHBoxLayout()
            b = QPushButton("Add key..."); b.setObjectName("primary"); b.clicked.connect(lambda _=False, p=pr: self.app.add_key(p))
            g = QPushButton("Get a free key"); g.setObjectName("ghost"); g.clicked.connect(lambda _=False, p=pr: webbrowser.open(p.signup_url))
            row.addWidget(b); row.addWidget(g); row.addStretch(); l.addLayout(row)
        return f


class ModelsPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app, self._picks = app, {}
        lay = QVBoxLayout(self); lay.setContentsMargins(26, 18, 26, 18); lay.setSpacing(10)
        lay.addLayout(title("Models", "What fits this machine, what to download, and a benchmark that replaces estimates with measurements."))
        self.hw = LogView(); self.hw.setFixedHeight(150); lay.addWidget(self.hw)
        split = QSplitter(Qt.Horizontal); split.setChildrenCollapsible(False)
        left, right = card("cardflat"), card("cardflat")
        ll = QVBoxLayout(left); ll.setContentsMargins(14, 12, 14, 12)
        h = QLabel("RECOMMENDED FOR THIS MACHINE"); h.setObjectName("h2"); ll.addWidget(h)
        hc = QLabel("Estimates from your hardware's memory bandwidth; measure to confirm."); hc.setObjectName("muted"); hc.setWordWrap(True); ll.addWidget(hc)
        self.rec = make_tree(["Role", "Model", "Size", "~tok/s", "Installed"], [70, 230, 70, 60]); ll.addWidget(self.rec)
        row = QHBoxLayout()
        self.pull_btn = QPushButton("Download selected (Ollama)"); self.pull_btn.setObjectName("primary"); self.pull_btn.clicked.connect(self.pull)
        rb = QPushButton("Refresh"); rb.clicked.connect(self.refresh)
        row.addWidget(self.pull_btn); row.addWidget(rb); row.addStretch(); ll.addLayout(row)
        self.bar = QProgressBar(); self.bar.setRange(0, 100); ll.addWidget(self.bar)
        self.msg = QLabel(""); self.msg.setObjectName("muted"); self.msg.setWordWrap(True); ll.addWidget(self.msg)
        rl = QVBoxLayout(right); rl.setContentsMargins(14, 12, 14, 12)
        h2 = QLabel("MEASURE EVERYTHING"); h2.setObjectName("h2"); rl.addWidget(h2)
        h2c = QLabel("The router uses measured scores instead of guesses."); h2c.setObjectName("muted"); h2c.setWordWrap(True); rl.addWidget(h2c)
        r2 = QHBoxLayout()
        self.bench_btn = QPushButton("Benchmark all available models"); self.bench_btn.clicked.connect(self.bench)
        self.cap = QLineEdit("3.00"); self.cap.setFixedWidth(70)
        r2.addWidget(self.bench_btn); r2.addWidget(QLabel("stop after $")); r2.addWidget(self.cap); r2.addStretch(); rl.addLayout(r2)
        self.bench_log = LogView(); rl.addWidget(self.bench_log)
        split.addWidget(left); split.addWidget(right); split.setSizes([600, 440])
        lay.addWidget(split, 1)

    def _ollama(self):
        st = self.app.controller.stack
        return next((p for p in (st.providers if st else []) if p.card.name.startswith("ollama/")), None)

    def refresh(self):
        st = self.app.controller.stack
        if st is None:
            return
        p = st.profile
        tips = ollama_tips(p)
        self.hw.replace_all(hardware_report(p) + ("\n\n" + tips if tips else ""), "info")
        have, o = set(), self._ollama()
        if o is not None:
            try:
                have = {m["name"] for m in o.models()}
            except Exception:
                pass
        r = recommend(p)
        self.rec.clear(); self._picks = {}
        for role in ("daily", "fast", "deep"):
            x = r[role]
            if x:
                self._picks[role] = x
                add_row(self.rec, [role, x.model.tag, f"{x.model.size_gb:g} GB", f"{x.tps:.0f}", "yes" if x.model.tag in have else "-"],
                        "ok" if x.model.tag in have else None, key=role)
        if o is None:
            self.msg.setText("Ollama is not running. Install it from ollama.com, start it, then Refresh.")

    def pull(self):
        it = self.rec.currentItem()
        o = self._ollama()
        if it is None or o is None:
            self.msg.setText("Select a row first (and make sure Ollama is running).")
            return
        pick = self._picks[it.data(0, Qt.UserRole)]
        if QMessageBox.question(self, "Download model", f"Download {pick.model.tag} ({pick.model.size_gb:g} GB) with Ollama?\n\n"
                                "This uses your internet connection and disk space.") != QMessageBox.Yes:
            return
        self.pull_btn.setEnabled(False)
        self.msg.setText(f"Starting {pick.model.tag}...")

        def work():
            try:
                def prog(ev):
                    if ev.get("total") and ev.get("completed") is not None:
                        self.app.bg.put(("pull", 100.0 * ev["completed"] / ev["total"], ev.get("status", "")))
                self.app.bg.put(("pull_done", o.pull(pick.model.tag, prog), pick.model.tag))
            except Exception as e:
                self.app.bg.put(("pull_err", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def bench(self):
        st = self.app.controller.stack
        if st is None or self.app.controller.state != "idle":
            self.bench_log.append_line("Wait until PRAXIS is idle.", "warn")
            return
        try:
            cap = float(self.cap.text())
        except ValueError:
            cap = 3.0
        if QMessageBox.question(self, "Benchmark", "This sends real test tasks to every available model, including your cloud "
                                f"subscriptions (usage counts against your plans).\n\nStops starting new models after ${cap:.2f}. Continue?") != QMessageBox.Yes:
            return
        self.bench_btn.setEnabled(False)
        self.bench_log.clear()

        def work():
            from ...bench import bench_all
            try:
                provs = [p for p in st.providers if getattr(p, "can_complete", True)]
                bench_all(provs, st.registry, 1, True, log=lambda s: self.app.bg.put(("bench_line", s)), sandbox=st.sandbox, max_cost=cap)
            except Exception as e:
                self.app.bg.put(("bench_line", f"error: {e}"))
            self.app.bg.put(("bench_done", None))
        threading.Thread(target=work, daemon=True).start()


class MemoryPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(26, 18, 26, 18); lay.setSpacing(10)
        lay.addLayout(title("Memory", "Derived from the event log. Failures are remembered with their reasons so they are not repeated."))
        row = QHBoxLayout()
        self.q = QLineEdit(); self.q.setPlaceholderText("search past goals"); self.q.setMaximumWidth(460)
        self.q.returnPressed.connect(self.search)
        b = QPushButton("Search"); b.clicked.connect(self.search)
        row.addWidget(self.q); row.addWidget(b); row.addStretch(); lay.addLayout(row)
        self.tree = make_tree(["Outcome", "Goal", "Reason"], [110, 460]); lay.addWidget(self.tree, 1)

    def refresh(self, query=""):
        c = self.app.controller
        eps = c.memory_search(query, k=50) if query else list(reversed(c.memory_episodes()))
        self.tree.clear()
        for ep in eps:
            add_row(self.tree, [ep["status"], ep["text"], ep["reason"][:200]],
                    "ok" if ep["status"] == "VERIFIED" else "bad" if ep["status"] == "FAILED" else "warn")

    def search(self):
        self.refresh(self.q.text().strip())


class SystemPage(QWidget):
    def __init__(self, app):
        super().__init__()
        self.app = app
        lay = QVBoxLayout(self); lay.setContentsMargins(26, 18, 26, 18); lay.setSpacing(10)
        lay.addLayout(title("System", "The machine, the sandbox, and every model PRAXIS can reach."))
        self.facts = LogView(); self.facts.setFixedHeight(150); lay.addWidget(self.facts)
        self.tree = make_tree(["Provider / model", "Tier", "Data", "Measured", "$/task", "tok/s", "Status"], [300, 80, 80, 90, 80, 70])
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        b = QPushButton("Re-run sandbox self-attack"); b.clicked.connect(self.retest)
        self.note = QLabel(""); self.note.setObjectName("muted")
        row.addWidget(b); row.addWidget(self.note); row.addStretch(); lay.addLayout(row)

    def refresh(self):
        c, st = self.app.controller, self.app.controller.stack
        if st is None:
            return
        sb = st.sandbox
        self.facts.replace_all("\n".join([
            f"workspace   {c.workspace}", f"event log   {c.db_path}", f"machine     {st.profile.describe()}",
            "sandbox     " + (f"{sb.kind.upper()}  (proven: no outside writes, no network, PRAXIS state hidden)" if sb.strong
                              else "NONE - running code needs your approval every time"),
            "not set up  " + (", ".join(f"{k} ({v.split(' (')[0]})" for k, v in st.skipped.items()) or "nothing")]), "info")
        self.tree.clear()
        now = st.router.clock()
        for p in st.providers:
            n = p.card.name
            e = st.registry.data.get(n, {}).get("planning", {})
            cool = st.router.cooling.get(n, 0) - now
            status = f"resting {int(cool / 60) + 1} min" if cool > 0 else ("delegate-only" if not getattr(p, "can_complete", True) else "ready")
            add_row(self.tree, [n, getattr(p, "tier", "") or "", PRIVACY_NAME.get(p.card.privacy, p.card.privacy),
                                f"{e['score']:.2f}" if e else "-", f"{e.get('cost_per_task', 0):.4f}" if e else "-",
                                e.get("tokens_per_s") or "-", status], "warn" if cool > 0 else "ok")

    def retest(self):
        from ...sandbox import detect
        self.note.setText("attacking the sandbox...")

        def work():
            sb = detect()
            self.app.bg.put(("sandbox", sb.kind, sb.strong))
        threading.Thread(target=work, daemon=True).start()
