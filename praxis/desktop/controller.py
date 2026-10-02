"""UI-independent controller. Owns the stack, one worker thread, the approval broker and the kill switch.

Threading rules (so the window never freezes and nothing races):
  * the executive runs ONLY on the worker thread, with its own SQLite connection;
  * the UI thread polls with `poll()` using its own read-only connection (SQLite WAL allows concurrent reads);
  * the only cross-thread calls are submit/stop/respond/open_workspace, all lock-protected.
"""
import os
import threading
import time
import uuid
from dataclasses import dataclass, field

from ..config import build_stack
from ..events import EventLog
from ..executive import Cancelled, Executive
from ..memory import Memory
from .settings import Settings
from .view import build_view, explain


def workspace_problem(path):
    """Why this folder should not be a workspace (home, a drive root, a system folder), or None if it is fine."""
    p = os.path.realpath(path)
    home = os.path.realpath(os.path.expanduser("~"))
    raw = path.replace("\\", "/").lower().rstrip("/")      # also judge the text as typed (Windows paths on any OS)
    low = p.lower().replace("\\", "/").rstrip("/")
    if p == home:
        return "That is your whole home folder. Choose a specific project folder inside it."
    if os.path.dirname(p) == p or any(len(x) == 2 and x[1] == ":" for x in (raw, low)):
        return "That is a drive root. Choose a specific project folder."
    if p == os.path.dirname(home):
        return "That folder holds every user's home folder. Choose a specific project folder."
    system = ("/usr", "/etc", "/bin", "/sbin", "/lib", "/boot", "/var", "/sys", "/proc", "/dev", "/system", "/library",
              "c:/windows", "c:/program files", "c:/program files (x86)", "c:/programdata")
    if any(x == s or x.startswith(s + "/") for s in system for x in (raw, low)):
        return "That is a system folder. Choose a specific project folder."
    return None


@dataclass
class ApprovalRequest:
    id: str
    tool: str
    cls: int
    args: dict
    reason: str
    ts: float = field(default_factory=time.time)


@dataclass
class Update:
    events: list
    view: object
    approvals: list
    state: str
    error: str


class Controller:
    def __init__(self, workspace, stack_factory=None, home=None, approval_timeout=900.0):
        self.settings = Settings(home)
        self.workspace = os.path.realpath(workspace)
        self.stack_factory = stack_factory or build_stack
        self.approval_timeout = approval_timeout
        self._lock = threading.RLock()
        self._state, self.error, self.info = "starting", "", {}
        self._stopping = False
        self._stack = None
        self._executive = None
        self._approvals = {}
        self._tl = threading.local()
        self._last_id = 0
        self._on_executive_built = None  # test hook
        self.refusal = ""
        self._baseline = None
        self.notes = []  # human-readable messages for the status bar (errors from the worker)

    # ---- state ---------------------------------------------------------------
    @property
    def state(self):
        with self._lock:
            return "stopping" if (self._state == "working" and self._stopping) else self._state

    @property
    def db_path(self):
        return os.path.join(self.workspace, ".praxis", "events.db")

    @property
    def stack(self):
        return self._stack

    # ---- lifecycle -------------------------------------------------------------
    def start(self):
        with self._lock:
            self._state, self.error = "starting", ""
        threading.Thread(target=self._build, daemon=True, name="praxis-build").start()

    def _build(self):
        try:
            os.makedirs(os.path.join(self.workspace, ".praxis"), exist_ok=True)
            stack = self.stack_factory(self.workspace)
            with self._lock:
                self._stack = stack
                self.info = {"providers": [p.card.name for p in stack.providers], "skipped": dict(stack.skipped),
                             "sandbox": stack.sandbox.kind, "sandbox_strong": stack.sandbox.strong,
                             "profile": stack.profile.describe() if getattr(stack, "profile", None) else ""}
                self._state = "idle"
            self.settings.add_recent(self.workspace)
            self.settings.save()
        except Exception as e:  # the UI shows this; the app must never die on a bad config
            with self._lock:
                self._state, self.error = "error", f"{type(e).__name__}: {e}"

    def open_workspace(self, path):
        self.refusal = workspace_problem(path) or ""
        if self.refusal:
            return False
        with self._lock:
            if self._state == "working":
                return False
            self.workspace = os.path.realpath(path)
            self._tl = threading.local()
            self._last_id = 0
            self._baseline = None
        self.start()
        return True

    def shutdown(self):
        self.stop()

    # ---- running goals -----------------------------------------------------------
    def _make_executive(self, log, private, no_critic):
        st, lim = self._stack, self._stack.cfg["limits"]
        return Executive(self.workspace, log, st.router, approver=self._approver, agents=st.agents,
                         critic=not no_critic and len(st.providers) > 1,
                         max_steps=lim["max_steps"], max_model_calls=lim["max_model_calls"],
                         max_cost_usd=lim["max_cost_usd"] or None, max_checkpoint_mb=lim.get("max_checkpoint_mb", 512),
                         data_class="private" if private else st.cfg["privacy"]["data_class"], sandbox=st.sandbox)

    def submit(self, text, private=False, no_critic=False):
        return self._launch(lambda ex: ex.run(text), private, no_critic)

    def resume(self):
        if not self.unfinished():
            return False
        return self._launch(lambda ex: ex.resume(), False, False)

    def _launch(self, action, private, no_critic):
        with self._lock:
            if self._state != "idle":
                return False
            self._state, self._stopping = "working", False
        try:  # where the log stood BEFORE this goal: "mark history as read" must never swallow the goal's own events
            self._baseline = self._reader().db.execute("SELECT MAX(id) FROM events").fetchone()[0] or 0
        except Exception:
            self._baseline = None
        threading.Thread(target=self._work, args=(action, private, no_critic), daemon=True, name="praxis-worker").start()
        return True

    def _work(self, action, private, no_critic):
        log = None
        try:
            log = EventLog(self.db_path)  # connection is created ON the worker thread
            ex = self._make_executive(log, private, no_critic)
            with self._lock:
                self._executive = ex
            if self._on_executive_built:
                self._on_executive_built()
            action(ex)
        except Exception as e:
            self.notes.append(f"error: {type(e).__name__}: {e}")
        finally:
            with self._lock:
                self._executive, self._stopping, self._state = None, False, "idle"
                for req, evt, res in list(self._approvals.values()):
                    res[0] = False
                    evt.set()
            if log is not None:
                log.db.close()

    # ---- kill switch ---------------------------------------------------------------
    def stop(self):
        with self._lock:
            ex = self._executive
            if self._state != "working" or ex is None:
                return
            self._stopping = True
            pending = list(self._approvals.values())
        ex.cancel()          # kills in-flight CLI calls, stops before the next step, rolls back
        for req, evt, res in pending:  # a human who presses Stop is not going to answer the dialog
            res[0] = False
            evt.set()

    # ---- approvals -------------------------------------------------------------------
    def _approver(self, decision):
        req = ApprovalRequest(uuid.uuid4().hex[:8], decision.tool, decision.cls, dict(decision.args), decision.reason)
        evt, res = threading.Event(), [False]
        with self._lock:
            self._approvals[req.id] = (req, evt, res)
        answered = evt.wait(self.approval_timeout)
        with self._lock:
            self._approvals.pop(req.id, None)
            ex = self._executive
        if ex is not None and ex._cancel.is_set():
            raise Cancelled()
        return bool(res[0]) if answered else False  # silence is a no

    def respond(self, req_id, approved):
        with self._lock:
            item = self._approvals.get(req_id)
        if item:
            item[2][0] = bool(approved)
            item[1].set()

    # ---- reading ------------------------------------------------------------------------
    def _reader(self):
        r = getattr(self._tl, "reader", None)
        if r is None or getattr(self._tl, "path", None) != self.db_path:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            r = self._tl.reader = EventLog(self.db_path)
            self._tl.path = self.db_path
        return r

    def poll(self):
        r = self._reader()
        new = r.since(self._last_id)
        if new:
            self._last_id = new[-1].id
        g = r.last_goal_id()
        view = build_view(r.all(goal_id=g) if g else [])
        with self._lock:
            approvals = [x[0] for x in self._approvals.values()]
        return Update(new, view, approvals, self.state, self.error)

    def mark_read(self):
        """Treat everything currently in the log as already seen (used when a workspace is opened)."""
        r = self._reader()
        row = r.db.execute("SELECT MAX(id) FROM events").fetchone()
        newest = row[0] or 0
        with self._lock:
            baseline, self._baseline = self._baseline, None   # consumed: it only matters for the first snapshot
        self._last_id = min(newest, baseline) if baseline is not None else newest

    def all_events(self):
        return self._reader().all()

    def why(self, event_id):
        return explain(self._reader(), event_id)

    def verify_log(self):
        return self._reader().verify_chain()

    def unfinished(self):
        return self._reader().unfinished_goals()

    def memory_search(self, query, k=5):
        return Memory(self._reader()).search(query, k=k)

    def memory_episodes(self):
        return Memory(self._reader()).episodes()
