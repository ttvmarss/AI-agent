"""What PRAXIS says out loud. Every sentence is built from the same real events the screen shows, so speech cannot claim
something that did not happen. Short on purpose: milestones, never a running commentary."""
import re

SECRET = re.compile(r"(sk-[A-Za-z0-9_\-]{8,}|gh[pousr]_[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{8,}|(?i:password|secret|token|api[_-]?key)\s*[:=]\s*\S+)")


def clean(text, limit=140):
    """Make a reason fit to be spoken: no markup, no secrets, no paths read letter by letter, bounded length."""
    t = SECRET.sub("a credential", str(text or ""))
    t = re.sub(r"[`*_#]+", " ", t)
    t = re.sub(r"(?:[A-Za-z]:)?(?:[\\/][\w.\-]+){3,}", "a file", t)
    t = re.sub(r"\s+", " ", t).strip(" .;:")
    return (t[:limit].rsplit(" ", 1)[0] + "...") if len(t) > limit else t


def for_event(etype, p):
    """-> (sentence or None, urgent). Only milestones are spoken. Any payload shape is survivable."""
    p = p if isinstance(p, dict) else {}
    if etype == "plan.accepted":                          # the plan itself is not narrated: only a warning is worth interrupting for
        if p.get("tainted"):
            return "Heads up: that plan came from file contents, so I'm limiting it to reversible actions.", False
        return None, False
    if etype == "escalation":
        return "That didn't verify. Trying a stronger model.", False
    if etype == "plan.rejected":
        return f"I rejected that plan: {clean(p.get('error'), 90)}.", False
    if etype == "guard.decision" and p.get("verdict") == "DENY":
        return f"I blocked a step: {clean(p.get('reason'), 100)}.", False
    if etype == "goal.undone":
        return "Undone. The workspace is back to how it was before that goal.", True
    if etype == "undo.refused":
        return clean(p.get("reason"), 100) or "I can't undo that.", True
    if etype == "goal.report":
        status, reason = p.get("status"), clean(p.get("reason"))
        ev = p.get("evidence")
        passed = sum(1 for e in (ev if isinstance(ev, (list, tuple)) else []) if isinstance(e, dict) and e.get("passed"))
        if status == "VERIFIED":
            return (f"Done. {passed} check{'s' if passed != 1 else ''} passed." if passed else "Done."), True
        if status == "UNVERIFIED":
            return "I finished, but I can't prove it." + (f" {reason}." if reason else ""), True
        if status == "CANCELLED":
            return "Stopped. " + ("I restored the workspace." if p.get("rolled_back") else ""), True
        return ("That failed" + (f": {reason}." if reason else ".") + (" I rolled everything back." if p.get("rolled_back") else "")), True
    return None, False


def approval_prompt(req):
    """The spoken version of the approval dialog: the exact action, then the exact words that will be accepted."""
    a = req.args if isinstance(req.args, dict) else {}
    if req.tool == "shell.run":
        what = f"run this command: {clean(a.get('cmd'), 100)}"
    elif req.tool == "agent.delegate":
        what = f"hand a task to the {a.get('agent', 'cloud')} agent: {clean(a.get('task'), 100)}"
    elif req.tool == "plan.replan":
        what = "accept a replacement plan that a model wrote after reading your files"
    else:
        what = f"use {req.tool}"
    risky = req.cls >= 4
    ask = "Say Praxis, approve to allow it, or deny." if risky else "Say Praxis, yes to allow it, or deny."
    return f"I need your approval to {what}. {ask}"


def describe_facts(view, state, workspace="", brains=(), cost=None):
    """What is TRUE about this session, as plain lines for the conversational model. It may state only these as things it did."""
    lines = []
    if workspace:
        lines.append(f"Workspace folder: {workspace}.")
    if brains:
        lines.append("Models available: " + ", ".join(list(brains)[:6]) + ".")
    lines.append(f"State right now: {state}.")
    if not getattr(view, "goal_id", ""):
        lines.append("No goal has been run in this workspace yet, so you have not done anything on the computer.")
        return " ".join(lines)
    lines.append(f"Latest goal: {clean(view.goal_text, 160)!r}, status {view.status}.")
    steps = [f"{s.tool} {s.summary}".strip() for s in view.steps][:6]
    if steps:
        lines.append("Its steps: " + "; ".join(clean(x, 60) for x in steps) + ".")
    ev = [("passed" if e.get("passed") else "FAILED") + ": " + clean(e.get("claim"), 70) for e in view.evidence][:5]
    if ev:
        lines.append("Checks: " + "; ".join(ev) + ".")
    if view.reason:
        lines.append(f"Reason: {clean(view.reason, 120)}.")
    if view.rolled_back:
        lines.append("The workspace was rolled back, so that goal left no changes.")
    c = view.cost if cost is None else cost
    if c:
        lines.append(f"Spent on models for it: ${c:.3f}.")
    return " ".join(lines)


def describe_status(view, state, pending):
    """One honest sentence about what is happening right now, from the real View."""
    if state == "starting":
        return "I'm still starting up."
    if pending:
        return "I'm waiting for your approval. " + approval_prompt(pending[0])
    done = sum(1 for s in view.steps if s.state in ("verified", "ran"))
    if state in ("working", "stopping"):
        if state == "stopping":
            return "I'm stopping and restoring the workspace."
        goal = clean(view.goal_text, 90)
        if view.steps:
            return f"I'm working on: {goal}. {done} of {len(view.steps)} steps done."
        return f"I'm planning: {goal}."
    if not view.goal_id:
        return "I'm idle and ready."
    n = sum(1 for e in view.evidence if e.get("passed"))
    return {"VERIFIED": f"Idle. The last goal verified, {n} check{'s' if n != 1 else ''} passed.",
            "FAILED": "Idle. The last goal failed" + (f": {clean(view.reason, 90)}." if view.reason else "."),
            "UNVERIFIED": "Idle. The last goal finished, but I couldn't prove it.",
            "CANCELLED": "Idle. The last goal was stopped."}.get(view.status, "I'm idle and ready.")
