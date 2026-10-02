"""Pure mapping from the engine's real state to what the interface shows: the mode, the words, the pipeline, the brains. No sockets, no UI."""
from ..desktop.view import View

DISPLAY = {"droid": "droid · factory", "devin": "devin", "claude": "claude", "codex": "codex", "ollama": "ollama"}
STRATEGY = {"quality": "measured", "balanced": "auto", "frugal": "frugal"}
STRATEGY_BACK = {"measured": "quality", "auto": "balanced", "frugal": "frugal", "config": "balanced"}
DATA_CYCLE = ["project", "private", "open"]
FRUGAL_CYCLE = ["balanced", "frugal", "quality"]
STEP_STATES = {"pending", "running", "waiting", "ran", "verified", "denied", "failed", "rolled back"}


def mode_for(v, state, waiting=False, hint="", error=""):
    """-> (mode, title, subtitle, progress): the one-word state of the whole system and the sentence under it."""
    done = sum(s.state in ("verified", "ran") for s in v.steps)
    prog = done / len(v.steps) if v.steps else 0.0
    if state == "starting":
        return "starting", "STARTING", "detecting hardware, tools and sandbox", 0.0
    if state == "error":
        return "bad", "ERROR", error[:90], 0.0
    if state == "stopping":
        return "stopping", "STOPPING", "killing in-flight calls, restoring the workspace", prog
    if waiting:
        return "waiting", "NEEDS YOU", "approval required", prog
    if v.status in ("PLANNING", "RUNNING"):
        sub = f"step {min(done + 1, len(v.steps))} of {len(v.steps)}" if v.steps and v.status == "RUNNING" else (v.goal_text[:70] if v.goal_text else "")
        return "working", v.status, sub, prog
    if v.status == "VERIFIED":
        return "ok", "VERIFIED", f"{sum(e['passed'] for e in v.evidence)} checks passed", 1.0
    if v.status == "UNVERIFIED":
        return "stopped", "UNVERIFIED", v.reason[:90] or "no real success check", prog
    if v.status == "CANCELLED":
        return "stopped", "STOPPED", "workspace restored" if v.rolled_back else "stopped by you", prog
    if v.status == "FAILED":
        return "bad", "FAILED", v.reason[:90] + ("  (rolled back)" if v.rolled_back else ""), prog
    if hint and not v.goal_text:
        return "stopped", "SETUP NEEDED", "no AI models yet: add a free key (praxis keys set groq) or sign in to Claude / Codex", prog
    return "idle", "READY", "describe an outcome", prog


def plan_state(v):
    return ("planning" if v.status == "PLANNING" else "ready" if v.steps
            else "failed" if v.status == "FAILED" and v.reason.startswith("planning failed") else "none")


def pipeline(v):
    steps = [{"label": (s.summary or s.tool or "step")[:120], "state": s.state if s.state in STEP_STATES else "pending"} for s in v.steps]
    checks = [{"label": str(e.get("claim", "check"))[:120], "ok": bool(e.get("passed"))} for e in v.evidence]
    return {"plan": plan_state(v), "steps": steps, "checks": checks, "sealed": v.status == "VERIFIED" and bool(checks)}


def brain(node):
    fam = node["family"]
    n = len(node["models"])
    u = node.get("usage", {}).get("24h", {})
    return {"family": fam, "name": (DISPLAY.get(fam, fam) + (f"  x{n}" if n > 1 else "")).upper(), "cost_class": node["cost_class"], "privacy": node.get("privacy", ""),
            "pressure": float(node.get("pressure") or 0.0), "cooling_s": int(node.get("cooling_s") or 0), "blocked": bool(node.get("blocked")),
            "models": [{"name": m["name"], "tier": m.get("tier") or "", "score": m.get("score"), "cooling_s": int(m.get("cooling_s") or 0)} for m in node["models"]][:12],
            "calls_24h": int(u.get("calls", 0)), "cost_24h": float(u.get("cost") or 0.0)}


def approval(req):
    """One approval, as the interface shows it: a human sentence and the exact action."""
    from ..desktop.approvals import describe
    a = req.args if isinstance(req.args, dict) else {}
    if req.tool == "shell.run":
        summary = f"Run: {str(a.get('cmd', ''))[:100]}"
    elif req.tool == "agent.delegate":
        summary = f"Hand a task to {a.get('agent', 'a cloud agent')}"
    elif req.tool == "desktop.open":
        summary = f"Open {str(a.get('target', ''))[:80]}"
    elif req.tool == "plan.replan":
        summary = "Accept a replacement plan written after reading your files"
    else:
        summary = f"Use {req.tool}"
    return {"id": req.id, "tool": req.tool, "cls": int(req.cls), "risky": req.cls >= 4, "reason": str(req.reason)[:300], "summary": summary, "detail": describe(req)[:600]}
