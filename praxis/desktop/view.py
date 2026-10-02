"""Pure projection of the event log into what a person needs to see. No UI toolkit here, so it is fully testable.

The desktop app never keeps its own notion of state: every pixel is derived from events (design law 3: the log is truth).
"""
import copy
import time
from dataclasses import dataclass, field


@dataclass
class StepView:
    id: str
    tool: str
    summary: str
    cls: int = 0
    state: str = "pending"   # pending running waiting ran verified denied failed rolled back
    deps: list = field(default_factory=list)


@dataclass
class View:
    goal_id: str = ""
    goal_text: str = ""
    status: str = "IDLE"
    steps: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    reason: str = ""
    rolled_back: bool = False
    cost: float = 0.0
    checkpoint: str = ""
    tainted: bool = False
    active_provider: str = ""   # set while a model call is in flight (model.try without its model.call yet)


def _args_summary(tool, args):
    if not isinstance(args, dict):
        return ""
    if tool == "shell.run":
        return str(args.get("cmd", ""))
    if tool == "agent.delegate":
        return f"{args.get('agent', '?')}: {str(args.get('task', ''))[:70]}"
    return str(args.get("path", ""))


def summarize(e):
    """One human sentence per event + a level for colouring. Never dumps raw JSON."""
    p, t = e.payload, e.type
    if t == "goal.intent":
        return f"Goal: {p.get('text', '')}", "info"
    if t == "goal.resumed":
        return "Resuming after an interruption", "warn"
    if t == "memory.recall":
        return f"Recalled {len(p.get('goal_ids', []))} related earlier goal(s)", "info"
    if t == "model.call":
        who = f"{p.get('provider', '?')} ({p.get('role', '?')})"
        if p.get("ok"):
            ms = p.get("duration_ms")
            cost = p.get("cost_usd")
            tps = p.get("tokens_per_s")
            bits = [f"{ms / 1000:.1f}s"] if ms else []
            if cost:
                bits.append(f"${cost:.3f}")
            if tps:
                bits.append(f"{tps:.0f} tok/s")
            return f"{who} answered" + (f" ({', '.join(bits)})" if bits else ""), "info"
        return f"{who} failed: {str(p.get('error', ''))[:120]}", "warn"
    if t == "model.skipped":
        return f"Skipped {p.get('provider')}: {p.get('reason', '')}", "warn"
    if t == "escalation":
        return (f"Escalating (attempt {p.get('attempt')}): {p.get('from')} failed verification, trying a stronger model "
                f"- {str(p.get('reason', ''))[:100]}"), "warn"
    if t == "model.try":
        return f"Asking {p.get('provider')} ({p.get('role', '?')})...", "info"
    if t == "plan.proposed":
        return "Model proposed a plan (raw output recorded)", "info"
    if t == "plan.accepted":
        n = len(p.get("plan", {}).get("steps", []))
        return f"Plan accepted: {n} step(s)" + (" - built from untrusted file content, capped at Class 2" if p.get("tainted") else ""), \
            "warn" if p.get("tainted") else "info"
    if t == "plan.rejected":
        return f"Plan rejected: {p.get('error', '')}", "warn"
    if t == "critic.verdict":
        n = len(p.get("objections", []))
        return (f"Critic ({p.get('provider', '?')}) approved the plan" if p.get("approve") or not n
                else f"Critic ({p.get('provider', '?')}) raised {n} objection(s)"), "ok" if not n else "warn"
    if t.startswith("critic."):
        return f"Critic: {t.split('.', 1)[1]} - {str(p.get('reason') or p.get('error') or '')[:100]}", "info"
    if t == "observe.result":
        if p.get("denied"):
            return f"Refused to read {p.get('path')}: {p.get('reason', '')}", "bad"
        return f"Read {p.get('path')} ({p.get('bytes', 0)} bytes) - treated as untrusted data", "info"
    if t == "checkpoint":
        return "Checkpoint saved (everything below can be undone)", "info"
    if t == "step.intent":
        return f"Step {p.get('step')}: {p.get('tool')} {_args_summary(p.get('tool'), p.get('args'))}".strip(), "info"
    if t == "guard.decision":
        v = p.get("verdict")
        return f"Guard: {v} (Class {p.get('class')}) - {p.get('reason', '')}", "ok" if v == "ALLOW" else "bad"
    if t == "guard.authorization":
        return f"{'You approved' if p.get('verdict') == 'ALLOW' else 'Denied'}: step {p.get('step')}", \
            "ok" if p.get("verdict") == "ALLOW" else "bad"
    if t == "tool.result":
        ok = p.get("ok")
        return f"Step {p.get('step')} {'ran' if ok else 'FAILED'}: {str(p.get('output', ''))[:100]}", "info" if ok else "bad"
    if t == "verify.result":
        return f"{'PASS' if p.get('passed') else 'FAIL'}: {p.get('claim', '')}", "ok" if p.get("passed") else "bad"
    if t == "rollback":
        return "Rolled back to the checkpoint - nothing half-done is left", "warn"
    if t == "replan.approval":
        return f"Replan {'approved by you' if p.get('approved') else 'not approved'}", "ok" if p.get("approved") else "warn"
    if t == "goal.cancelled":
        return "Stopped by you; workspace restored", "warn"
    if t == "goal.undone":
        return f"Undone: workspace restored to before '{str(p.get('text', ''))[:60]}' (safety copy {p.get('safety', '?')})", "warn"
    if t == "undo.refused":
        return str(p.get("reason", "Nothing to undo")), "warn"
    if t == "goal.report":
        r = p.get("reason")
        return f"{p.get('status')}" + (f": {r}" if r else ""), "ok" if p.get("status") == "VERIFIED" else "bad"
    return f"{t}", "info"


class ViewFolder:
    """Folds events into the View of the most recent goal, ONE EVENT AT A TIME. The window polls ten times a second; re-reading and re-folding
    every event of a long goal on each poll (6,000 events took 60 ms) would eat the main thread, so the fold is kept and only new events are fed."""

    def __init__(self):
        self.v, self.waiting = View(), None

    def feed(self, events):
        for e in events:
            if e.type == "goal.intent":                       # a new goal starts: everything before it is history
                self.v, self.waiting = View(goal_id=e.goal_id, status="PLANNING"), None
            elif e.goal_id != self.v.goal_id or not self.v.goal_id:
                continue
            self._fold(e)
        return self

    def view(self):
        """The current View (a copy, so the WAITING FOR YOU adjustment never leaks into the running fold)."""
        v = copy.copy(self.v)
        if v.status in ("RUNNING", "PLANNING") and self.waiting:
            v.status = "WAITING FOR YOU"
        return v

    def _fold(self, e):
        t, p = e.type, e.payload
        if t == "goal.intent":
            self.v.goal_text = p.get("text", "")
        elif t == "plan.accepted":
            self.v.steps = [StepView(s["id"], s["tool"], _args_summary(s["tool"], s.get("args")), deps=list(s.get("deps", [])))
                       for s in p.get("plan", {}).get("steps", [])]
            self.v.evidence, self.v.rolled_back, self.v.tainted = [], False, bool(p.get("tainted"))
            self.v.status = "PLANNING"
        elif t == "checkpoint":
            self.v.checkpoint = p.get("id", "")
            self.v.status = "RUNNING"
        elif t == "model.try":
            self.v.active_provider = p.get("provider", "")
        elif t == "model.call":
            self.v.cost += float(p.get("cost_usd") or 0)
            if p.get("provider") == self.v.active_provider:
                self.v.active_provider = ""
        elif t == "step.intent":
            s = _step(self.v, p.get("step"))
            if s:
                s.state = "running"
        elif t == "guard.decision":
            s = _step(self.v, p.get("step"))
            if s:
                s.cls = p.get("class", 0)
                if p.get("verdict") == "DENY":
                    s.state = "denied"
                elif p.get("verdict") == "ESCALATE":
                    s.state, self.waiting = "self.waiting", p.get("step")
        elif t == "guard.authorization":
            s = _step(self.v, p.get("step"))
            self.waiting = None
            if s:
                s.state = "running" if p.get("verdict") == "ALLOW" else "denied"
        elif t == "tool.result":
            s = _step(self.v, p.get("step"))
            if s:
                s.state = "ran" if p.get("ok") else "failed"
        elif t == "verify.result":
            self.v.evidence.append({"claim": p.get("claim", ""), "passed": bool(p.get("passed"))})
            s = _step(self.v, p.get("step")) if p.get("step") else None
            if s and s.state in ("ran", "running"):
                s.state = "verified" if p.get("passed") else "failed"
        elif t == "rollback":
            self.v.rolled_back = True
            for s in self.v.steps:
                if s.state in ("ran", "verified", "running"):
                    s.state = "rolled back"
        elif t == "goal.report":
            self.v.active_provider = ""
            self.v.status = p.get("status", "FAILED")
            self.v.reason = p.get("reason", "")
            self.v.rolled_back = self.v.rolled_back or bool(p.get("rolled_back"))
            self.waiting = None
        elif t == "goal.cancelled":
            self.v.rolled_back = bool(p.get("rolled_back")) or self.v.rolled_back


def build_view(events):
    """Fold the events of the most recent goal into a View."""
    return ViewFolder().feed(events).view()


def _step(v, sid):
    return next((s for s in v.steps if s.id == sid), None)


def clock(ts):
    return time.strftime("%H:%M:%S", time.localtime(ts))


def explain(log, event_id):
    """'Why did you do that?': the causal chain from an event back to the user's goal."""
    lines = []
    for e in log.ancestors(event_id):
        text, _ = summarize(e)
        lines.append(f"#{e.id:<4}{clock(e.ts)}  {e.actor:<9}{text}")
    return "\n".join(lines) or "(no such event)"
