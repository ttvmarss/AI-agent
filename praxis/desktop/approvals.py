"""What an approval request says. Toolkit-free so the Tk and Qt dialogs show exactly the same words."""
import json

LEGEND = {3: ("EXTERNAL ACTION", "warn", "Sends data off this machine or calls an outside service."),
          4: ("NEEDS YOUR JUDGMENT", "bad", "Spends money, touches security, runs code without a sandbox, or is something the Guard cannot classify."),
          5: ("DESTRUCTIVE", "bad", "Deletes or overwrites in a way that is hard to undo. A checkpoint is taken first, but think twice.")}


DESKTOP_NOTE = ("Approving lets PRAXIS use your keyboard, mouse and windows for the rest of this goal; each action is still logged. "
                "To stop it at any moment press Esc or move the mouse to the top-left corner of the screen.")


def desktop_sentence(tool, a):
    """One plain sentence for a desktop action."""
    q = lambda v, n=80: str(v if v is not None else "")[:n]
    return {"desktop.focus": lambda: f"Bring the window '{q(a.get('title'))}' to the front",
            "desktop.type": lambda: f"Type on the keyboard: {q(a.get('text'))!r}",
            "desktop.key": lambda: f"Press {q(a.get('keys'))}",
            "desktop.click": lambda: f"Click ({q(a.get('x'), 6)}, {q(a.get('y'), 6)}) with the {q(a.get('button') or 'left', 8)} mouse button",
            "desktop.scroll": lambda: f"Scroll {q(a.get('amount'), 6)}",
            "desktop.close": lambda: f"Ask the window '{q(a.get('title'))}' to close (unsaved work may be lost)",
            "desktop.clipboard": lambda: "Read your clipboard (it may hold a password)" if a.get("op") == "get" else "Put text on your clipboard",
            "desktop.screenshot": lambda: f"Take a screenshot of your screen and save it as {q(a.get('name') or 'screenshot.png', 60)}",
            "desktop.windows": lambda: "List your open windows"}.get(tool, lambda: tool)()


def describe(req):
    a = req.args or {}
    if req.tool == "agent.delegate":
        extra = "\nThis agent runs in the cloud and spends your usage (or money)." if a.get("agent") == "devin" else \
            "\nThe agent can edit files in this workspace; everything it changes is shown and can be rolled back."
        return f"Hand a task to the cloud agent '{a.get('agent')}':\n\n{a.get('task', '')}{extra}"
    if req.tool == "shell.run":
        return f"Run this command in the workspace:\n\n{a.get('cmd', '')}"
    if req.tool == "desktop.open":
        return f"Open this on your computer:\n\n{a.get('target', '')}\n\nA website opens in your browser; an application is started."
    if req.tool.startswith("desktop.") and req.tool != "desktop.open":
        return f"{desktop_sentence(req.tool, a)}\n\n{DESKTOP_NOTE}"
    if req.tool == "plan.replan":
        steps = a.get("steps", [])
        lines = [f"  {s.get('id')}: {s.get('tool')} {json.dumps(s.get('args', {}))[:110]}" for s in steps]
        return "The first attempt failed. A model proposed this replacement plan after reading file contents:\n\n" + "\n".join(lines)
    return f"{req.tool}\n\n{json.dumps(a, indent=2)[:900]}"
