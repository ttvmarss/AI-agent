"""CLI: python -m praxis {run,why,verify-log,rollback} ..."""
import argparse
import os
import sys

from .events import EventLog
from .executive import Executive
from .router import AnthropicProvider, Router


def _paths(ws):
    ws = os.path.abspath(ws)
    os.makedirs(os.path.join(ws, ".praxis"), exist_ok=True)
    return ws, os.path.join(ws, ".praxis", "events.db")


def _approver(decision):
    if not sys.stdin.isatty():
        return False  # non-interactive: fail closed
    print(f"\n[approval needed] Class {decision.cls}: {decision.tool} {decision.args}\n  why: {decision.reason}")
    return input("approve? [y/N] ").strip().lower() == "y"


def main(argv=None):
    ap = argparse.ArgumentParser(prog="praxis")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("goal"); r.add_argument("--workspace", default=".")
    r.add_argument("--model", default="claude-sonnet-5-5")
    w = sub.add_parser("why"); w.add_argument("event_id", type=int); w.add_argument("--workspace", default=".")
    v = sub.add_parser("verify-log"); v.add_argument("--workspace", default=".")
    b = sub.add_parser("rollback"); b.add_argument("checkpoint"); b.add_argument("--workspace", default=".")
    a = ap.parse_args(argv)
    ws, db = _paths(a.workspace)
    log = EventLog(db)

    if a.cmd == "verify-log":
        ok, bad = log.verify_chain()
        print("log intact" if ok else f"LOG TAMPERED at event {bad}")
        return 0 if ok else 2
    ex = Executive(ws, log, Router([AnthropicProvider(getattr(a, "model", "claude-sonnet-5-5"))]), approver=_approver)
    if a.cmd == "why":
        print(ex.why(a.event_id)); return 0
    if a.cmd == "rollback":
        ex.ws.rollback(a.checkpoint); print(f"restored checkpoint {a.checkpoint}"); return 0
    rep = ex.run(a.goal)
    print(f"{rep.status}  goal={rep.goal_id}  checkpoint={rep.checkpoint}")
    if rep.reason:
        print(f"reason: {rep.reason}")
    for e in rep.evidence:
        print(f"  [{'PASS' if e['passed'] else 'FAIL'}] {e['claim']}")
    return 0 if rep.status == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
