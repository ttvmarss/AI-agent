"""Reflexes: requests so plain that asking a language model to plan them is waste. "Open Chrome" took a planner call, a critic call, ~20 seconds and
$0.17, and (on the real PC) never opened anything. A reflex recognises the request deterministically and returns a ready-made plan; the plan
goes through exactly the same Guard, approval, execution and verification as any model-written plan (it is logged as `reflex.matched`), it just
skips the model: instant, free, and the same every time. Anything that is not clearly one of these falls through to the planner."""
import re

VERBS = r"(?:open(?: up)?|launch|start(?: up)?|fire up|bring up|pull up|load|go to|goto|take me to|show me|visit|browse to|navigate to)"
POLITE = r"^(?:(?:hey |ok |okay |so |now |and |then )*)(?:(?:please|can you|could you|would you|will you|i want you to|i'd like you to|i need you to|go ahead and)\s+)*"
TAIL = r"(?:\s+(?:please|for me|now|real quick|quickly|thanks|thank you))*$"
PATTERN = re.compile(POLITE + VERBS + r"\s+(?P<what>.+?)" + TAIL, re.I)
NOT_PLAIN = re.compile(r"\b(and|then|also|with|in|on|to|that|which|so|using|containing|called|named|for)\b", re.I)


def match(text, opener):
    """-> a plan dict (the same shape a model would write) or None."""
    t = re.sub(r"[.!?,]+$", "", str(text or "").strip())
    m = PATTERN.match(t)
    if not m:
        return None
    what = m.group("what").strip().strip("\"'")
    if not what or len(what.split()) > 4:
        return None
    action = opener.resolve(what)
    if action.kind not in ("app", "site", "url"):
        return None
    if action.kind != "app" and NOT_PLAIN.search(what) and action.kind != "site":
        return None
    if NOT_PLAIN.search(what) and action.kind == "app" and not re.fullmatch(r"[a-z0-9 .+-]+", what.lower()):
        return None
    check = {"type": "process_running", "name": list(action.procs), "wait": 10}
    return {"steps": [{"id": "open", "tool": "desktop.open", "args": {"target": what}, "deps": [], "verify": dict(check)}],
            "success": [dict(check)], "reflex": "open", "label": action.label}
