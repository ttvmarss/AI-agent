"""What an approval request says. Toolkit-free so the Tk and Qt dialogs show exactly the same words."""
import json

LEGEND = {3: ("EXTERNAL ACTION", "warn", "Sends data off this machine or calls an outside service."),
          4: ("NEEDS YOUR JUDGMENT", "bad", "Spends money, touches security, runs code without a sandbox, or is something the Guard cannot classify."),
          5: ("DESTRUCTIVE", "bad", "Deletes or overwrites in a way that is hard to undo. A checkpoint is taken first, but think twice.")}


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
    if req.tool == "plan.replan":
        steps = a.get("steps", [])
        lines = [f"  {s.get('id')}: {s.get('tool')} {json.dumps(s.get('args', {}))[:110]}" for s in steps]
        return "The first attempt failed. A model proposed this replacement plan after reading file contents:\n\n" + "\n".join(lines)
    return f"{req.tool}\n\n{json.dumps(a, indent=2)[:900]}"
