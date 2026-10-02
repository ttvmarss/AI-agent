"""Pure projection of the event log into what a person needs to see. No UI toolkit here, so it is fully testable.

The desktop app never keeps its own notion of state: every pixel is derived from events (design law 3: the log is truth).
"""
import time
from dataclasses import dataclass, field


@dataclass
class StepView:
    id: str
    tool: str
    summary: str
    cls: int = 0
    state: str = "pending"   # pending running waiting ran verified denied failed rolled back


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
    if t == "goal.report":
        r = p.get("reason")
        return f"{p.get('status')}" + (f": {r}" if r else ""), "ok" if p.get("status") == "VERIFIED" else "bad"
    return f"{t}", "info"


def build_view(events):
    """Fold the events of the most recent goal into a View."""
    last = None
    for e in events:
        if e.type == "goal.intent":
            last = e.goal_id
    if last is None:
        return View()
    v = View(goal_id=last, status="PLANNING")
    waiting = None
    for e in (x for x in events if x.goal_id == last):
        t, p = e.type, e.payload
        if t == "goal.intent":
            v.goal_text = p.get("text", "")
        elif t == "plan.accepted":
            v.steps = [StepView(s["id"], s["tool"], _args_summary(s["tool"], s.get("args")))
                       for s in p.get("plan", {}).get("steps", [])]
            v.evidence, v.rolled_back, v.tainted = [], False, bool(p.get("tainted"))
            v.status = "PLANNING"
        elif t == "checkpoint":
            v.checkpoint = p.get("id", "")
            v.status = "RUNNING"
        elif t == "model.call":
            v.cost += float(p.get("cost_usd") or 0)
        elif t == "step.intent":
            s = _step(v, p.get("step"))
            if s:
                s.state = "running"
        elif t == "guard.decision":
            s = _step(v, p.get("step"))
            if s:
                s.cls = p.get("class", 0)
                if p.get("verdict") == "DENY":
                    s.state = "denied"
                elif p.get("verdict") == "ESCALATE":
                    s.state, waiting = "waiting", p.get("step")
        elif t == "guard.authorization":
            s = _step(v, p.get("step"))
            waiting = None
            if s:
                s.state = "running" if p.get("verdict") == "ALLOW" else "denied"
        elif t == "tool.result":
            s = _step(v, p.get("step"))
            if s:
                s.state = "ran" if p.get("ok") else "failed"
        elif t == "verify.result":
            v.evidence.append({"claim": p.get("claim", ""), "passed": bool(p.get("passed"))})
            s = _step(v, p.get("step")) if p.get("step") else None
            if s and s.state in ("ran", "running"):
                s.state = "verified" if p.get("passed") else "failed"
        elif t == "rollback":
            v.rolled_back = True
            for s in v.steps:
                if s.state in ("ran", "verified", "running"):
                    s.state = "rolled back"
        elif t == "goal.report":
            v.status = p.get("status", "FAILED")
            v.reason = p.get("reason", "")
            v.rolled_back = v.rolled_back or bool(p.get("rolled_back"))
            waiting = None
        elif t == "goal.cancelled":
            v.rolled_back = bool(p.get("rolled_back")) or v.rolled_back
    if v.status in ("RUNNING", "PLANNING") and waiting:
        v.status = "WAITING FOR YOU"
    return v


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
